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

# 与 diet.py 的记录级营养列一致。NULL = 未知（未解析），0 = 确认是零。
_NUTRITION_FIELDS = ("calories", "protein", "fat", "carbs", "fiber")
_FIELD_LABELS = {"calories": "热量", "protein": "蛋白质", "fat": "脂肪",
                 "carbs": "碳水", "fiber": "膳食纤维"}


def _get_active_goal(conn, member_id: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM nutrition_goals
           WHERE member_id=? AND is_active=1 AND is_deleted=0
           ORDER BY created_at DESC LIMIT 1""",
        (member_id,)
    ).fetchone()
    return dict(row) if row else None


def _get_daily_intake(member_id: str, date_str: str) -> dict:
    """从 diet_records 获取指定日期的营养摄入合计。

    字段值 None 表示未知（当天有记录但营养未解析），0 表示确认是零。
    两种"零摄入"必须分开：
      has_records False — 当天没有任何记录
      has_records True + 字段为 None — 记了，但营养未解析
    旧写法把两者都返回 0，于是"不知道吃了多少"被当成"没吃"参与目标对比。
    """
    conn = get_lifestyle_connection()
    try:
        row = conn.execute(
            """SELECT
                 SUM(total_calories) as calories,
                 SUM(total_protein)  as protein,
                 SUM(total_fat)      as fat,
                 SUM(total_carbs)    as carbs,
                 SUM(total_fiber)    as fiber,
                 COUNT(*) as record_count,
                 MAX(CASE WHEN total_calories IS NULL THEN 1 ELSE 0 END) as calories_unknown,
                 MAX(CASE WHEN total_protein  IS NULL THEN 1 ELSE 0 END) as protein_unknown,
                 MAX(CASE WHEN total_fat      IS NULL THEN 1 ELSE 0 END) as fat_unknown,
                 MAX(CASE WHEN total_carbs    IS NULL THEN 1 ELSE 0 END) as carbs_unknown,
                 MAX(CASE WHEN total_fiber    IS NULL THEN 1 ELSE 0 END) as fiber_unknown
               FROM diet_records
               WHERE member_id=? AND meal_date=? AND is_deleted=0""",
            (member_id, date_str)
        ).fetchone()
    finally:
        conn.close()

    has_records = bool(row and row["record_count"])
    intake = {}
    unresolved_fields = []
    for f in _NUTRITION_FIELDS:
        if not has_records or row[f"{f}_unknown"]:
            intake[f] = None
            if has_records:
                unresolved_fields.append(f)
        else:
            intake[f] = round(row[f], 1)
    intake["has_records"] = has_records
    intake["unresolved"] = bool(unresolved_fields)
    intake["unresolved_fields"] = unresolved_fields
    return intake


def _compare(intake: dict, goal: dict) -> dict:
    """计算摄入与目标的差距和达标情况。

    未知字段一律跳过：把 None 当 0 对比，会凭空产出
    "记录值为用户设置目标的 0.0%"这类结论。
    """
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
        actual = intake.get(field)
        if target is None or target == 0 or actual is None:
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

    # Generate factual differences from the user's saved goal. These are not
    # nutrition or treatment recommendations.
    issues = []
    for field, data in comparison.items():
        if data["status"] == "low":
            issues.append(f"{_FIELD_LABELS.get(field, field)}记录值为用户设置目标的 {data['pct']}%（低于目标范围）")
        elif data["status"] == "high":
            issues.append(f"{_FIELD_LABELS.get(field, field)}记录值为用户设置目标的 {data['pct']}%（高于目标范围）")

    # 没有可判断的摄入值就不下"是否达标"的结论——未知不是未达标，也不是达标。
    # 当天根本没记录同样不可判断，`_compare` 只会得到一个空对比表。
    unresolved_fields = intake["unresolved_fields"]
    judgeable = intake["has_records"] and not unresolved_fields

    output_json({
        "status": "ok",
        "date": date_str,
        "intake": intake,
        "goal_id": goal["id"],
        "comparison": comparison,
        "issues": issues,
        "unresolved_fields": unresolved_fields,
        "on_track": len(issues) == 0 if judgeable else None,
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
    judged_days = 0
    current = start
    while current <= end:
        ds = current.isoformat()
        intake = _get_daily_intake(args.member_id, ds)
        if not intake["has_records"]:
            # 没记录：与"记了但未解析"是两回事，分开表达
            daily.append({"date": ds, "intake": intake, "on_track": None, "no_data": True})
        elif intake["unresolved"]:
            # 未解析：没有可判断的摄入值，不下达标结论，也不进达标率分母
            daily.append({
                "date": ds, "intake": intake, "on_track": None,
                "unresolved": True, "unresolved_fields": intake["unresolved_fields"],
            })
        else:
            comparison = _compare(intake, goal)
            on_track = all(v["status"] == "ok" for v in comparison.values()) if comparison else None
            if on_track:
                on_track_days += 1
            if on_track is not None:
                judged_days += 1
            daily.append({
                "date": ds,
                "intake": intake,
                "on_track": on_track,
                "issues": [f for f, d in comparison.items() if d["status"] != "ok"],
            })
        current += timedelta(days=1)

    output_json({
        "status": "ok",
        "days": days,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "recorded_days": sum(1 for d in daily if not d.get("no_data")),
        "unresolved_days": sum(1 for d in daily if d.get("unresolved")),
        "judged_days": judged_days,
        "on_track_days": on_track_days,
        # 分母是"能判断的天数"：未解析天既非达标也非未达标，计入会凭空拉低达标率
        "on_track_rate": round(on_track_days / judged_days * 100, 1) if judged_days else None,
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
