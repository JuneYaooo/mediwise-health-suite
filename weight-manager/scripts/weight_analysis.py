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

from health_db import ensure_db, get_connection, row_to_dict, rows_to_list, output_json
from validators import validate_date_optional
from metric_utils import calculate_age, calculate_bmr, calculate_tdee


def _get_active_goal(conn, member_id):
    """Get active weight goal for member."""
    return conn.execute(
        "SELECT * FROM weight_goals WHERE member_id=? AND status='active' AND is_deleted=0",
        (member_id,)
    ).fetchone()


def _get_weight_records(conn, member_id, days=None, start_date=None, end_date=None):
    """Get weight records from health_metrics."""
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
    rows = conn.execute(sql, params).fetchall()
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
    conn = get_connection()
    try:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        goal = _get_active_goal(conn, args.member_id)
        if not goal:
            output_json({"status": "error", "message": f"{m['name']}当前无活跃体重目标"})
            return

        goal = row_to_dict(goal)

        # Get latest weight
        latest = conn.execute(
            """SELECT value, measured_at FROM health_metrics
               WHERE member_id=? AND metric_type='weight' AND is_deleted=0
               ORDER BY measured_at DESC LIMIT 1""",
            (args.member_id,)
        ).fetchone()

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
    finally:
        conn.close()


def trend(args):
    """体重趋势（N 天变化，平均变化速率）。"""
    ensure_db()
    conn = get_connection()
    try:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        days = args.days or 30
        records = _get_weight_records(conn, args.member_id, days=days)

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
    finally:
        conn.close()


def calorie_balance(args):
    """结合 diet_records 和 exercise_records 计算热量收支。"""
    ensure_db()
    conn = get_connection()
    try:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        days = args.days or 7
        end = datetime.now().date()
        start = end - timedelta(days=days - 1)

        # Get goal for calorie target
        goal = _get_active_goal(conn, args.member_id)
        daily_target = goal["daily_calorie_target"] if goal and goal["daily_calorie_target"] else None

        # Get daily calorie intake from diet_records
        rows = conn.execute(
            """SELECT meal_date, SUM(total_calories) as calories
               FROM diet_records
               WHERE member_id=? AND meal_date>=? AND meal_date<=? AND is_deleted=0
               GROUP BY meal_date
               ORDER BY meal_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
        date_map = {r["meal_date"]: r["calories"] or 0 for r in rows}

        # Get daily exercise calories burned
        exercise_rows = conn.execute(
            """SELECT exercise_date, SUM(calories_burned) as burned
               FROM exercise_records
               WHERE member_id=? AND exercise_date>=? AND exercise_date<=? AND is_deleted=0
               GROUP BY exercise_date
               ORDER BY exercise_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
        burned_map = {r["exercise_date"]: r["burned"] or 0 for r in exercise_rows}

        # Estimate TDEE if member data is available
        tdee = None
        member = conn.execute(
            "SELECT gender, birth_date FROM members WHERE id=? AND is_deleted=0",
            (args.member_id,)
        ).fetchone()
        if member and member["gender"] in ("male", "female") and member["birth_date"]:
            weight_data = conn.execute(
                """SELECT value FROM health_metrics WHERE member_id=? AND metric_type='weight' AND is_deleted=0
                   ORDER BY measured_at DESC LIMIT 1""",
                (args.member_id,)
            ).fetchone()
            height_data = conn.execute(
                """SELECT value FROM health_metrics WHERE member_id=? AND metric_type='height' AND is_deleted=0
                   ORDER BY measured_at DESC LIMIT 1""",
                (args.member_id,)
            ).fetchone()
            if weight_data and height_data:
                try:
                    w = float(weight_data["value"])
                    h = float(height_data["value"])
                    age = calculate_age(member["birth_date"])
                    bmr = calculate_bmr(w, h, age, member["gender"])
                    tdee = round(calculate_tdee(bmr, "sedentary"), 1)
                except (ValueError, TypeError):
                    pass

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
                "net": round(intake - burned, 1),
            }
            if daily_target:
                entry["target"] = daily_target
                entry["balance"] = round(intake - daily_target, 1)
            if tdee:
                entry["calorie_deficit"] = round(tdee - (intake - burned), 1)
            daily.append(entry)
            current += timedelta(days=1)

        total_intake = sum(d["intake"] for d in daily)
        total_burned = sum(d["burned"] for d in daily)
        avg_intake = round(total_intake / days, 1)
        avg_burned = round(total_burned / days, 1)

        result = {
            "status": "ok",
            "member_name": m["name"],
            "days": days,
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "daily": daily,
            "total_intake": round(total_intake, 1),
            "total_burned": round(total_burned, 1),
            "average_daily_intake": avg_intake,
            "average_daily_burned": avg_burned,
            "net_intake": round(total_intake - total_burned, 1),
        }
        if daily_target:
            result["daily_calorie_target"] = daily_target
            result["average_balance"] = round(avg_intake - daily_target, 1)
        if tdee:
            result["estimated_tdee"] = tdee

        output_json(result)
    finally:
        conn.close()


def weekly_report(args):
    """周报（体重变化 + 饮食热量 + 运动统计 + 建议）。"""
    ensure_db()
    conn = get_connection()
    try:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        if args.end_date:
            end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        else:
            end = datetime.now().date()
        start = end - timedelta(days=6)

        # Weight data
        weight_records = _get_weight_records(
            conn, args.member_id,
            start_date=start.isoformat(), end_date=end.isoformat()
        )
        weight_change = None
        if len(weight_records) >= 2:
            weight_change = round(weight_records[-1]["weight"] - weight_records[0]["weight"], 2)

        # Diet data
        diet_rows = conn.execute(
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
        exercise_rows = conn.execute(
            """SELECT * FROM exercise_records
               WHERE member_id=? AND exercise_date>=? AND exercise_date<=? AND is_deleted=0
               ORDER BY exercise_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
        exercise_list = rows_to_list(exercise_rows)
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
        goal = _get_active_goal(conn, args.member_id)
        goal_dict = row_to_dict(goal) if goal else None

        # Suggestions
        suggestions = []
        if goal:
            target = goal["daily_calorie_target"]
            if target and avg_calories > 0:
                if avg_calories > target * 1.1:
                    suggestions.append(f"本周日均热量 {avg_calories} kcal 超过目标 {target} kcal，建议适当控制饮食")
                elif avg_calories < target * 0.8:
                    suggestions.append(f"本周日均热量 {avg_calories} kcal 低于目标 {target} kcal 较多，注意营养充足")
                else:
                    suggestions.append(f"本周日均热量 {avg_calories} kcal 接近目标 {target} kcal，继续保持")

            if weight_change is not None:
                if goal["goal_type"] == "lose":
                    if weight_change < -0.1:
                        suggestions.append(f"体重下降 {abs(weight_change)} kg，进展良好")
                    elif weight_change > 0.1:
                        suggestions.append(f"体重上升 {weight_change} kg，建议检查饮食和运动计划")
                    else:
                        suggestions.append("体重基本持平，可适当增加运动量")
                elif goal["goal_type"] == "gain":
                    if weight_change > 0.1:
                        suggestions.append(f"体重增加 {weight_change} kg，进展良好")
                    elif weight_change < -0.1:
                        suggestions.append(f"体重下降 {abs(weight_change)} kg，建议增加热量摄入")

        if not weight_records:
            suggestions.append("本周无体重记录，建议定期称重追踪变化")
        if diet_days < 3:
            suggestions.append("本周饮食记录较少，建议每日记录以获得更准确的分析")

        # Exercise suggestions
        if exercise_count == 0:
            suggestions.append("本周无运动记录，建议每周至少运动3次以促进健康")
        elif exercise_count < 3:
            suggestions.append(f"本周运动{exercise_count}次，建议增加到每周3-5次")
        else:
            suggestions.append(f"本周运动{exercise_count}次，运动习惯良好，继续保持")

        if total_exercise_calories > 0 and avg_calories > 0 and goal and goal["goal_type"] == "lose":
            net_avg = avg_calories - round(total_exercise_calories / 7, 1)
            suggestions.append(f"考虑运动消耗后，日均净摄入约 {round(net_avg, 1)} kcal")

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
    finally:
        conn.close()


def projection(args):
    """按当前速度预测达标日期。"""
    ensure_db()
    conn = get_connection()
    try:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        goal = _get_active_goal(conn, args.member_id)
        if not goal:
            output_json({"status": "error", "message": f"{m['name']}当前无活跃体重目标"})
            return
        goal = row_to_dict(goal)

        # Get recent weight data (last 30 days) for rate calculation
        records = _get_weight_records(conn, args.member_id, days=30)

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
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="体重分析")
    sub = parser.add_subparsers(dest="command", required=True)

    p_prog = sub.add_parser("progress")
    p_prog.add_argument("--member-id", required=True)

    p_trend = sub.add_parser("trend")
    p_trend.add_argument("--member-id", required=True)
    p_trend.add_argument("--days", type=int, default=30, help="天数（默认 30）")

    p_cal = sub.add_parser("calorie-balance")
    p_cal.add_argument("--member-id", required=True)
    p_cal.add_argument("--days", type=int, default=7, help="天数（默认 7）")

    p_wr = sub.add_parser("weekly-report")
    p_wr.add_argument("--member-id", required=True)
    p_wr.add_argument("--end-date", default=None, help="结束日期 YYYY-MM-DD")

    p_proj = sub.add_parser("projection")
    p_proj.add_argument("--member-id", required=True)

    args = parser.parse_args()
    commands = {
        "progress": progress,
        "trend": trend,
        "calorie-balance": calorie_balance,
        "weekly-report": weekly_report,
        "projection": projection,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
