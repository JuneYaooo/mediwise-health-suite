"""体重进度分析、趋势预测、热量收支。"""

from __future__ import annotations

import argparse
import sys
import os
from datetime import datetime, timedelta

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from path_setup import setup_mediwise_path
setup_mediwise_path()

from health_db import (
    ensure_db,
    get_medical_connection,
    get_lifestyle_connection,
    row_to_dict,
    rows_to_list,
    output_json,
    verify_member_ownership,
)
from validators import validate_date_optional
from metric_utils import calculate_age, calculate_bmr, calculate_tdee


def _get_member_name(member_id, owner_id=None):
    """Get member name from medical DB."""
    conn = get_medical_connection()
    try:
        if not verify_member_ownership(conn, member_id, owner_id):
            return None
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (member_id,)).fetchone()
    finally:
        conn.close()
    return m


def _get_active_goal(member_id):
    """Get active weight goal for member from lifestyle DB."""
    conn = get_lifestyle_connection()
    try:
        return conn.execute(
            "SELECT * FROM weight_goals WHERE member_id=? AND status='active' AND is_deleted=0",
            (member_id,)
        ).fetchone()
    finally:
        conn.close()


def _get_weight_records(member_id, days=None, start_date=None, end_date=None):
    """Get weight records from medical DB health_metrics."""
    sql = "SELECT value, measured_at FROM health_metrics WHERE member_id=? AND metric_type='weight' AND is_deleted=0"
    params = [member_id]
    if start_date:
        sql += " AND measured_at>=?"
        params.append(start_date)
    if end_date:
        sql += " AND measured_at<=?"
        params.append(end_date + " 23:59:59")
    if days and not start_date:
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        sql += " AND measured_at>=?"
        params.append(start)
    sql += " ORDER BY measured_at ASC"

    conn = get_medical_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    result = []
    for r in rows:
        try:
            result.append({"weight": float(r["value"]), "measured_at": r["measured_at"]})
        except (ValueError, TypeError):
            pass
    return result


def progress(args):
    """当前进度（已减/增多少，完成百分比）。"""
    ensure_db()
    m = _get_member_name(args.member_id, args.owner_id)
    if not m:
        output_json({"status": "error", "message": f"未找到成员或无权访问: {args.member_id}"})
        return

    goal = _get_active_goal(args.member_id)
    if not goal:
        output_json({"status": "error", "message": f"{m['name']}当前无活跃体重目标"})
        return

    goal = row_to_dict(goal)

    # Get latest weight
    medical_conn = get_medical_connection()
    try:
        latest = medical_conn.execute(
            """SELECT value, measured_at FROM health_metrics
               WHERE member_id=? AND metric_type='weight' AND is_deleted=0
               ORDER BY measured_at DESC LIMIT 1""",
            (args.member_id,)
        ).fetchone()
    finally:
        medical_conn.close()
    if not latest:
        output_json({
            "status": "ok",
            "message": f"{m['name']}尚无体重记录，无法计算进度",
            "goal": goal,
            "current_weight": None,
            "progress_pct": 0
        })
        return

    try:
        current_weight = float(latest["value"])
    except (ValueError, TypeError):
        output_json({"status": "error", "message": "最新体重记录数据异常"})
        return

    start_weight = goal["start_weight"]
    target_weight = goal["target_weight"]
    total_change_needed = abs(target_weight - start_weight)
    actual_change = start_weight - current_weight if goal["goal_type"] == "lose" else current_weight - start_weight
    remaining = abs(target_weight - current_weight)

    if total_change_needed > 0:
        progress_pct = round(max(0, min(100, actual_change / total_change_needed * 100)), 1)
    else:
        progress_pct = 100.0 if abs(current_weight - target_weight) <= 0.5 else 0

    # Days info
    start_date = goal.get("start_date") or goal["created_at"][:10]
    days_elapsed = (datetime.now().date() - datetime.strptime(start_date, "%Y-%m-%d").date()).days
    target_date = goal.get("target_date")
    days_remaining = None
    if target_date:
        days_remaining = (datetime.strptime(target_date, "%Y-%m-%d").date() - datetime.now().date()).days

    output_json({
        "status": "ok",
        "member_name": m["name"],
        "goal": goal,
        "current_weight": current_weight,
        "latest_measured_at": latest["measured_at"],
        "change": round(actual_change, 1),
        "remaining": round(remaining, 1),
        "progress_pct": progress_pct,
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
    })


def trend(args):
    """体重趋势（N 天变化，平均变化速率）。"""
    ensure_db()
    m = _get_member_name(args.member_id, args.owner_id)
    if not m:
        output_json({"status": "error", "message": f"未找到成员或无权访问: {args.member_id}"})
        return

    days = args.days or 30
    records = _get_weight_records(args.member_id, days=days)

    if len(records) < 2:
        output_json({
            "status": "ok",
            "message": f"体重记录不足（需要至少2条），当前{len(records)}条",
            "member_name": m["name"],
            "days": days,
            "records": records,
            "trend": None
        })
        return

    first = records[0]
    last = records[-1]
    total_change = last["weight"] - first["weight"]
    days_span = (datetime.strptime(last["measured_at"][:10], "%Y-%m-%d") -
                 datetime.strptime(first["measured_at"][:10], "%Y-%m-%d")).days
    daily_rate = total_change / days_span if days_span > 0 else 0
    weekly_rate = daily_rate * 7

    output_json({
        "status": "ok",
        "member_name": m["name"],
        "days": days,
        "record_count": len(records),
        "records": records,
        "first_weight": first["weight"],
        "latest_weight": last["weight"],
        "total_change": round(total_change, 2),
        "daily_rate": round(daily_rate, 3),
        "weekly_rate": round(weekly_rate, 2),
        "trend_direction": "down" if total_change < -0.1 else ("up" if total_change > 0.1 else "stable"),
    })


def calorie_balance(args):
    """Separately summarize recorded intake and recorded activity burn."""
    ensure_db()
    m = _get_member_name(args.member_id, args.owner_id)
    if not m:
        output_json({"status": "error", "message": f"未找到成员或无权访问: {args.member_id}"})
        return

    days = args.days or 7
    end = datetime.now().date()
    start = end - timedelta(days=days - 1)

    # Get goal for calorie target
    goal = _get_active_goal(args.member_id)
    daily_target = goal["daily_calorie_target"] if goal and goal["daily_calorie_target"] else None

    lifestyle_conn = get_lifestyle_connection()
    try:
        # Get daily calorie intake from diet_records
        rows = lifestyle_conn.execute(
            """SELECT meal_date, SUM(total_calories) as calories
               FROM diet_records
               WHERE member_id=? AND meal_date>=? AND meal_date<=? AND is_deleted=0
               GROUP BY meal_date
               ORDER BY meal_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
        date_map = {r["meal_date"]: r["calories"] or 0 for r in rows}

        # Get daily exercise calories burned
        exercise_rows = lifestyle_conn.execute(
            """SELECT exercise_date, SUM(calories_burned) as burned
               FROM exercise_records
               WHERE member_id=? AND exercise_date>=? AND exercise_date<=? AND is_deleted=0
               GROUP BY exercise_date
               ORDER BY exercise_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
        burned_map = {r["exercise_date"]: r["burned"] or 0 for r in exercise_rows}
    finally:
        lifestyle_conn.close()
    daily = []
    current = start
    while current <= end:
        ds = current.isoformat()
        intake = date_map.get(ds, 0)
        burned = burned_map.get(ds, 0)
        entry = {
            "date": ds,
            "intake": round(intake, 1),
            "burned": round(burned, 1),
        }
        if daily_target:
            entry["target"] = daily_target
            entry["balance"] = round(intake - daily_target, 1)
        daily.append(entry)
        current += timedelta(days=1)

    total_intake = sum(d["intake"] for d in daily)
    total_burned = sum(d["burned"] for d in daily)
    intake_days = len(date_map)
    activity_days = len(burned_map)
    avg_intake = round(total_intake / intake_days, 1) if intake_days else 0
    avg_burned = round(total_burned / activity_days, 1) if activity_days else 0

    result = {
        "status": "ok",
        "member_name": m["name"],
        "days": days,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "daily": daily,
        "total_intake": round(total_intake, 1),
        "total_burned": round(total_burned, 1),
        "intake_record_days": intake_days,
        "activity_record_days": activity_days,
        "average_intake_on_recorded_days": avg_intake,
        "average_activity_burn_on_recorded_days": avg_burned,
        "note": "摄入与运动消耗为分别记录的数据，不代表完整能量收支或热量缺口",
    }
    if daily_target:
        result["daily_calorie_target"] = daily_target
        result["average_balance"] = round(avg_intake - daily_target, 1)
    output_json(result)


def weekly_report(args):
    """周报（体重变化 + 饮食热量 + 运动记录 + 目标差异）。"""
    ensure_db()
    m = _get_member_name(args.member_id, args.owner_id)
    if not m:
        output_json({"status": "error", "message": f"未找到成员或无权访问: {args.member_id}"})
        return

    if args.end_date:
        end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    else:
        end = datetime.now().date()
    start = end - timedelta(days=6)

    # Weight data
    weight_records = _get_weight_records(
        args.member_id,
        start_date=start.isoformat(), end_date=end.isoformat()
    )
    weight_change = None
    if len(weight_records) >= 2:
        weight_change = round(weight_records[-1]["weight"] - weight_records[0]["weight"], 2)

    lifestyle_conn = get_lifestyle_connection()
    try:
        # Diet data
        diet_rows = lifestyle_conn.execute(
            """SELECT meal_date, SUM(total_calories) as calories,
                      SUM(total_protein) as protein,
                      SUM(total_fat) as fat,
                      SUM(total_carbs) as carbs
               FROM diet_records
               WHERE member_id=? AND meal_date>=? AND meal_date<=? AND is_deleted=0
               GROUP BY meal_date
               ORDER BY meal_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
        diet_daily = rows_to_list(diet_rows)
        diet_days = len(diet_daily)
        avg_calories = round(sum(d["calories"] or 0 for d in diet_daily) / diet_days, 1) if diet_days > 0 else 0

        # Exercise data
        exercise_rows = lifestyle_conn.execute(
            """SELECT * FROM exercise_records
               WHERE member_id=? AND exercise_date>=? AND exercise_date<=? AND is_deleted=0
               ORDER BY exercise_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
        exercise_list = rows_to_list(exercise_rows)
    finally:
        lifestyle_conn.close()
    exercise_count = len(exercise_list)
    total_exercise_duration = sum(r["duration"] or 0 for r in exercise_list)
    total_exercise_calories = round(sum(r["calories_burned"] or 0 for r in exercise_list), 1)

    # Exercise by type
    exercise_by_type = {}
    for r in exercise_list:
        t = r["exercise_type"]
        if t not in exercise_by_type:
            exercise_by_type[t] = {"count": 0, "duration": 0, "calories": 0}
        exercise_by_type[t]["count"] += 1
        exercise_by_type[t]["duration"] += r["duration"] or 0
        exercise_by_type[t]["calories"] += r["calories_burned"] or 0

    # Goal
    goal = _get_active_goal(args.member_id)
    goal_dict = row_to_dict(goal) if goal else None

    # Compatibility field containing factual notices, not health advice.
    suggestions = []
    if goal:
        target = goal["daily_calorie_target"]
        if target and avg_calories > 0:
            if avg_calories > target * 1.1:
                suggestions.append(f"本周饮食记录日日均热量 {avg_calories} kcal，高于用户设置目标 {target} kcal")
            elif avg_calories < target * 0.8:
                suggestions.append(f"本周饮食记录日日均热量 {avg_calories} kcal，低于用户设置目标 {target} kcal")
            else:
                suggestions.append(f"本周饮食记录日日均热量 {avg_calories} kcal，接近用户设置目标 {target} kcal")

        if weight_change is not None:
            if goal["goal_type"] == "lose":
                if weight_change < -0.1:
                    suggestions.append(f"本周已记录体重下降 {abs(weight_change)} kg")
                elif weight_change > 0.1:
                    suggestions.append(f"本周已记录体重上升 {weight_change} kg，与用户设置的减重目标方向不同")
                else:
                    suggestions.append("本周已记录体重基本持平")
            elif goal["goal_type"] == "gain":
                if weight_change > 0.1:
                    suggestions.append(f"本周已记录体重增加 {weight_change} kg")
                elif weight_change < -0.1:
                    suggestions.append(f"本周已记录体重下降 {abs(weight_change)} kg，与用户设置的增重目标方向不同")

    if not weight_records:
        suggestions.append("本周无体重记录")
    if diet_days < 3:
        suggestions.append(f"本周只有 {diet_days} 个饮食记录日，汇总可能不完整")

    # Exercise suggestions
    if exercise_count == 0:
        suggestions.append("本周无运动记录")
    else:
        suggestions.append(f"本周有 {exercise_count} 次运动记录")

    output_json({
        "status": "ok",
        "member_name": m["name"],
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "weight": {
            "record_count": len(weight_records),
            "records": weight_records,
            "change": weight_change,
            "latest": weight_records[-1]["weight"] if weight_records else None,
        },
        "diet": {
            "days_recorded": diet_days,
            "daily": diet_daily,
            "average_calories": avg_calories,
        },
        "exercise": {
            "total_count": exercise_count,
            "total_duration": total_exercise_duration,
            "total_calories_burned": total_exercise_calories,
            "by_type": exercise_by_type,
        },
        "goal": goal_dict,
        "suggestions": suggestions,
    })


def projection(args):
    """按当前速度预测达标日期。"""
    ensure_db()
    m = _get_member_name(args.member_id, args.owner_id)
    if not m:
        output_json({"status": "error", "message": f"未找到成员或无权访问: {args.member_id}"})
        return

    goal = _get_active_goal(args.member_id)
    if not goal:
        output_json({"status": "error", "message": f"{m['name']}当前无活跃体重目标"})
        return
    goal = row_to_dict(goal)

    # Get recent weight data (last 30 days) for rate calculation
    records = _get_weight_records(args.member_id, days=30)

    if len(records) < 2:
        output_json({
            "status": "ok",
            "message": "体重记录不足（需要至少2条近30天记录），无法预测",
            "goal": goal,
            "projection": None
        })
        return

    first = records[0]
    last = records[-1]
    days_span = (datetime.strptime(last["measured_at"][:10], "%Y-%m-%d") -
                 datetime.strptime(first["measured_at"][:10], "%Y-%m-%d")).days

    if days_span == 0:
        output_json({
            "status": "ok",
            "message": "所有体重记录在同一天，无法计算变化速率",
            "goal": goal,
            "projection": None
        })
        return

    daily_rate = (last["weight"] - first["weight"]) / days_span
    remaining = goal["target_weight"] - last["weight"]

    # Check if moving in right direction
    moving_right = (goal["goal_type"] == "lose" and daily_rate < 0) or \
                   (goal["goal_type"] == "gain" and daily_rate > 0) or \
                   goal["goal_type"] == "maintain"

    projected_date = None
    days_to_target = None
    if moving_right and abs(daily_rate) > 0.001:
        days_to_target = int(abs(remaining / daily_rate))
        projected_date = (datetime.now() + timedelta(days=days_to_target)).strftime("%Y-%m-%d")

    output_json({
        "status": "ok",
        "member_name": m["name"],
        "goal": goal,
        "current_weight": last["weight"],
        "daily_rate": round(daily_rate, 3),
        "weekly_rate": round(daily_rate * 7, 2),
        "remaining": round(remaining, 1),
        "moving_right_direction": moving_right,
        "projected_date": projected_date,
        "days_to_target": days_to_target,
    })


def diet_weight_correlation(args):
    """Show recorded diet, activity, and weight side by side without inference."""
    ensure_db()
    m = _get_member_name(args.member_id, args.owner_id)
    if not m:
        output_json({"status": "error", "message": f"未找到成员或无权访问: {args.member_id}"})
        return

    days = args.days or 14
    end = datetime.now().date()
    start = end - timedelta(days=days - 1)

    medical_conn = get_medical_connection()
    try:
        weight_rows = medical_conn.execute(
            """SELECT DATE(measured_at) as day, AVG(CAST(value AS REAL)) as avg_weight
               FROM health_metrics
               WHERE member_id=? AND metric_type='weight' AND is_deleted=0
               AND DATE(measured_at) BETWEEN ? AND ?
               GROUP BY DATE(measured_at)
               ORDER BY day""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
    finally:
        medical_conn.close()

    weight_by_day = {r["day"]: round(r["avg_weight"], 2) for r in weight_rows}

    lifestyle_conn = get_lifestyle_connection()
    try:
        diet_rows = lifestyle_conn.execute(
            """SELECT meal_date, SUM(total_calories) as intake
               FROM diet_records
               WHERE member_id=? AND meal_date BETWEEN ? AND ? AND is_deleted=0
               GROUP BY meal_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
        exercise_rows = lifestyle_conn.execute(
            """SELECT exercise_date, SUM(calories_burned) as burned
               FROM exercise_records
               WHERE member_id=? AND exercise_date BETWEEN ? AND ? AND is_deleted=0
               GROUP BY exercise_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
    finally:
        lifestyle_conn.close()

    intake_by_day = {r["meal_date"]: round(r["intake"] or 0, 1) for r in diet_rows}
    burned_by_day = {r["exercise_date"]: round(r["burned"] or 0, 1) for r in exercise_rows}

    daily = []
    current = start
    while current <= end:
        ds = current.isoformat()
        intake = intake_by_day.get(ds, None)
        burned = burned_by_day.get(ds, 0)
        weight = weight_by_day.get(ds, None)

        daily.append({"date": ds, "weight": weight, "intake": intake, "burned": burned})
        current += timedelta(days=1)

    weight_days = [(d["date"], d["weight"]) for d in daily if d["weight"] is not None]
    actual_change = None
    if len(weight_days) >= 2:
        actual_change = round(weight_days[-1][1] - weight_days[0][1], 2)

    diet_days_count = len([d for d in daily if d["intake"] is not None])
    activity_days_count = len([d for d in daily if d["burned"] > 0])

    output_json({
        "status": "ok",
        "member_name": m["name"],
        "days": days,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "actual_weight_change": actual_change,
        "diet_days_recorded": diet_days_count,
        "activity_days_recorded": activity_days_count,
        "daily": daily,
        "note": "仅并列展示已记录数据，不推断热量缺口、因果关系或理论体重变化",
    })


def main():
    parser = argparse.ArgumentParser(description="体重分析")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prog = sub.add_parser("progress")
    p_prog.add_argument("--member-id", required=True)
    p_prog.add_argument("--owner-id", default=None)

    p_trend = sub.add_parser("trend")
    p_trend.add_argument("--member-id", required=True)
    p_trend.add_argument("--days", type=int, default=30)
    p_trend.add_argument("--owner-id", default=None)

    p_cal = sub.add_parser("calorie-balance")
    p_cal.add_argument("--member-id", required=True)
    p_cal.add_argument("--days", type=int, default=7)
    p_cal.add_argument("--owner-id", default=None)

    p_wr = sub.add_parser("weekly-report")
    p_wr.add_argument("--member-id", required=True)
    p_wr.add_argument("--end-date", type=validate_date_optional, default=None)
    p_wr.add_argument("--owner-id", default=None)

    p_proj = sub.add_parser("projection")
    p_proj.add_argument("--member-id", required=True)
    p_proj.add_argument("--owner-id", default=None)

    p_corr = sub.add_parser("diet-weight-correlation")
    p_corr.add_argument("--member-id", required=True)
    p_corr.add_argument("--days", type=int, default=14)
    p_corr.add_argument("--owner-id", default=None)

    args = parser.parse_args()
    commands = {
        "progress": progress,
        "trend": trend,
        "calorie-balance": calorie_balance,
        "weekly-report": weekly_report,
        "projection": projection,
        "diet-weight-correlation": diet_weight_correlation,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
