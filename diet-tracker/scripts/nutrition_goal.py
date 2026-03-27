"""营养目标设定与达标追踪。

支持设置每日热量和三大营养素目标，并与饮食记录对比达标情况。

Commands:
  set      --member-id --calories [--protein] [--fat] [--carbs] [--fiber] [--note]
  view     --member-id
  daily    --member-id [--date]
  weekly   --member-id [--days]
"""

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
    ensure_db, transaction, get_lifestyle_connection, get_medical_connection,
    generate_id, now_iso, row_to_dict, rows_to_list, output_json,
    verify_member_ownership,
)


def _get_active_goal(conn, member_id: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM nutrition_goals
           WHERE member_id=? AND is_active=1 AND is_deleted=0
           ORDER BY created_at DESC LIMIT 1""",
        (member_id,)
    ).fetchone()
    return dict(row) if row else None


def _get_daily_intake(member_id: str, date_str: str) -> dict:
    """从 diet_records 获取指定日期的营养摄入合计。"""
    conn = get_lifestyle_connection()
    try:
        row = conn.execute(
            """SELECT
                 SUM(total_calories) as calories,
                 SUM(total_protein)  as protein,
                 SUM(total_fat)      as fat,
                 SUM(total_carbs)    as carbs,
                 SUM(total_fiber)    as fiber
               FROM diet_records
               WHERE member_id=? AND meal_date=? AND is_deleted=0""",
            (member_id, date_str)
        ).fetchone()
    finally:
        conn.close()
    return {
        "calories": round(row["calories"] or 0, 1),
        "protein":  round(row["protein"]  or 0, 1),
        "fat":      round(row["fat"]      or 0, 1),
        "carbs":    round(row["carbs"]    or 0, 1),
        "fiber":    round(row["fiber"]    or 0, 1),
    } if row else {"calories": 0, "protein": 0, "fat": 0, "carbs": 0, "fiber": 0}


def _compare(intake: dict, goal: dict) -> dict:
    """计算摄入与目标的差距和达标情况。"""
    result = {}
    fields = {
        "calories": ("kcal", 0.9, 1.1),   # 达标区间：90-110%
        "protein":  ("g",    0.85, None),  # 至少达到 85%
        "fat":      ("g",    None, 1.15),  # 不超过 115%
        "carbs":    ("g",    0.8,  1.2),
        "fiber":    ("g",    0.8,  None),
    }
    for field, (unit, lo, hi) in fields.items():
        target = goal.get(f"{field}_g") if field != "calories" else goal.get("calories")
        actual = intake.get(field, 0)
        if target is None or target == 0:
            continue
        pct = round(actual / target * 100, 1)
        gap = round(actual - target, 1)
        status = "ok"
        if lo and pct < lo * 100:
            status = "low"
        elif hi and pct > hi * 100:
            status = "high"
        result[field] = {
            "target": target,
            "actual": actual,
            "unit": unit,
            "pct": pct,
            "gap": gap,
            "status": status,
        }
    return result


def cmd_set(args):
    """设置/更新营养目标。"""
    ensure_db()

    try:
        calories = int(args.calories) if args.calories else None
        protein  = float(args.protein) if args.protein else None
        fat      = float(args.fat) if args.fat else None
        carbs    = float(args.carbs) if args.carbs else None
        fiber    = float(args.fiber) if args.fiber else None
    except (ValueError, TypeError) as e:
        output_json({"status": "error", "message": f"参数格式错误: {e}"})
        return

    if not any([calories, protein, fat, carbs, fiber]):
        output_json({"status": "error", "message": "至少需要设置一个营养目标"})
        return

    now = now_iso()
    with transaction(domain="lifestyle") as conn:
        # Verify member exists
        med = get_medical_connection()
        try:
            m = med.execute(
                "SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)
            ).fetchone()
        finally:
            med.close()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        # Deactivate existing goals
        conn.execute(
            "UPDATE nutrition_goals SET is_active=0, updated_at=? WHERE member_id=? AND is_active=1 AND is_deleted=0",
            (now, args.member_id)
        )

        goal_id = generate_id()
        conn.execute(
            """INSERT INTO nutrition_goals
               (id, member_id, calories, protein_g, fat_g, carbs_g, fiber_g,
                is_active, note, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (goal_id, args.member_id, calories, protein, fat, carbs, fiber,
             getattr(args, 'note', None), now, now)
        )
        conn.commit()

    output_json({
        "status": "ok",
        "message": f"营养目标已设置",
        "goal_id": goal_id,
        "goal": {
            "calories": calories,
            "protein_g": protein,
            "fat_g": fat,
            "carbs_g": carbs,
            "fiber_g": fiber,
        },
    })


def cmd_view(args):
    """查看当前营养目标。"""
    ensure_db()
    conn = get_lifestyle_connection()
    try:
        goal = _get_active_goal(conn, args.member_id)
    finally:
        conn.close()

    if not goal:
        output_json({
            "status": "ok",
            "message": "尚未设置营养目标，使用 set 命令设置",
            "goal": None,
        })
        return

    output_json({"status": "ok", "goal": goal})


def cmd_daily(args):
    """查看今日（或指定日期）营养摄入与目标对比。"""
    ensure_db()
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    conn = get_lifestyle_connection()
    try:
        goal = _get_active_goal(conn, args.member_id)
    finally:
        conn.close()

    intake = _get_daily_intake(args.member_id, date_str)

    if not goal:
        output_json({
            "status": "ok",
            "date": date_str,
            "intake": intake,
            "goal": None,
            "message": "尚未设置营养目标",
        })
        return

    comparison = _compare(intake, goal)

    # 生成简短建议
    issues = []
    for field, data in comparison.items():
        if data["status"] == "low":
            label = {"calories": "热量", "protein": "蛋白质",
                     "fat": "脂肪", "carbs": "碳水", "fiber": "膳食纤维"}.get(field, field)
            issues.append(f"{label}摄入不足（{data['pct']}%）")
        elif data["status"] == "high":
            label = {"calories": "热量", "protein": "蛋白质",
                     "fat": "脂肪", "carbs": "碳水", "fiber": "膳食纤维"}.get(field, field)
            issues.append(f"{label}摄入偏高（{data['pct']}%）")

    output_json({
        "status": "ok",
        "date": date_str,
        "intake": intake,
        "goal_id": goal["id"],
        "comparison": comparison,
        "issues": issues,
        "on_track": len(issues) == 0,
    })


def cmd_weekly(args):
    """近 N 天每日达标率汇总。"""
    ensure_db()
    days = int(args.days or 7)
    end = datetime.now().date()
    start = end - timedelta(days=days - 1)

    conn = get_lifestyle_connection()
    try:
        goal = _get_active_goal(conn, args.member_id)
    finally:
        conn.close()

    if not goal:
        output_json({
            "status": "ok",
            "message": "尚未设置营养目标",
            "goal": None,
        })
        return

    daily = []
    on_track_days = 0
    current = start
    while current <= end:
        ds = current.isoformat()
        intake = _get_daily_intake(args.member_id, ds)
        has_data = intake["calories"] > 0
        if has_data:
            comparison = _compare(intake, goal)
            on_track = all(v["status"] == "ok" for v in comparison.values())
            if on_track:
                on_track_days += 1
            daily.append({
                "date": ds,
                "intake": intake,
                "on_track": on_track,
                "issues": [f for f, d in comparison.items() if d["status"] != "ok"],
            })
        else:
            daily.append({"date": ds, "intake": intake, "on_track": None, "no_data": True})
        current += timedelta(days=1)

    recorded_days = sum(1 for d in daily if not d.get("no_data"))
    output_json({
        "status": "ok",
        "days": days,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "recorded_days": recorded_days,
        "on_track_days": on_track_days,
        "on_track_rate": round(on_track_days / recorded_days * 100, 1) if recorded_days else 0,
        "goal": goal,
        "daily": daily,
    })


def main():
    parser = argparse.ArgumentParser(description="营养目标管理")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="设置营养目标")
    p_set.add_argument("--member-id", required=True)
    p_set.add_argument("--calories", default=None, help="每日热量目标 (kcal)")
    p_set.add_argument("--protein", default=None, help="蛋白质目标 (g)")
    p_set.add_argument("--fat", default=None, help="脂肪目标 (g)")
    p_set.add_argument("--carbs", default=None, help="碳水目标 (g)")
    p_set.add_argument("--fiber", default=None, help="膳食纤维目标 (g)")
    p_set.add_argument("--note", default=None)
    p_set.add_argument("--owner-id", default=None)

    p_view = sub.add_parser("view", help="查看当前目标")
    p_view.add_argument("--member-id", required=True)
    p_view.add_argument("--owner-id", default=None)

    p_daily = sub.add_parser("daily", help="今日达标情况")
    p_daily.add_argument("--member-id", required=True)
    p_daily.add_argument("--date", default=None, help="日期 YYYY-MM-DD（默认今天）")
    p_daily.add_argument("--owner-id", default=None)

    p_weekly = sub.add_parser("weekly", help="近N天达标率")
    p_weekly.add_argument("--member-id", required=True)
    p_weekly.add_argument("--days", default="7")
    p_weekly.add_argument("--owner-id", default=None)

    args = parser.parse_args()
    commands = {"set": cmd_set, "view": cmd_view, "daily": cmd_daily, "weekly": cmd_weekly}
    commands[args.command](args)


if __name__ == "__main__":
    main()
