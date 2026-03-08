"""运动/消耗记录管理。"""

from __future__ import annotations

import argparse
import sys
import os
from datetime import datetime

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from path_setup import setup_mediwise_path
setup_mediwise_path()

from health_db import ensure_db, get_connection, generate_id, now_iso, row_to_dict, rows_to_list, output_json, transaction
from validators import validate_date_optional

VALID_EXERCISE_TYPES = [
    "running", "walking", "cycling", "swimming", "strength", "yoga", "hiit", "other",
]

EXERCISE_TYPE_NAMES = {
    "running": "跑步",
    "walking": "步行",
    "cycling": "骑行",
    "swimming": "游泳",
    "strength": "力量训练",
    "yoga": "瑜伽",
    "hiit": "高强度间歇",
    "other": "其他",
}

VALID_INTENSITIES = ["low", "medium", "high"]


def add_exercise(args):
    """添加运动记录。"""
    ensure_db()

    if args.exercise_type not in VALID_EXERCISE_TYPES:
        output_json({
            "status": "error",
            "message": f"不支持的运动类型: {args.exercise_type}，支持: {', '.join(VALID_EXERCISE_TYPES)}"
        })
        return

    if args.intensity and args.intensity not in VALID_INTENSITIES:
        output_json({
            "status": "error",
            "message": f"不支持的强度: {args.intensity}，支持: {', '.join(VALID_INTENSITIES)}"
        })
        return

    with transaction() as conn:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        try:
            exercise_date = validate_date_optional(args.exercise_date, "运动日期") or datetime.now().strftime("%Y-%m-%d")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        duration = None
        if args.duration is not None:
            try:
                duration = int(args.duration)
                if duration <= 0 or duration > 1440:
                    output_json({"status": "error", "message": "运动时长应在 1-1440 分钟范围内"})
                    return
            except (ValueError, TypeError):
                output_json({"status": "error", "message": "运动时长必须为整数（分钟）"})
                return

        calories_burned = 0
        if args.calories_burned is not None:
            try:
                calories_burned = float(args.calories_burned)
                if calories_burned < 0 or calories_burned > 10000:
                    output_json({"status": "error", "message": "消耗热量应在 0-10000 kcal 范围内"})
                    return
            except (ValueError, TypeError):
                output_json({"status": "error", "message": "消耗热量必须为数值"})
                return

        record_id = generate_id()
        now = now_iso()
        conn.execute(
            """INSERT INTO exercise_records
               (id, member_id, exercise_type, exercise_name, duration, calories_burned,
                exercise_date, exercise_time, intensity, note, created_at, is_deleted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (record_id, args.member_id, args.exercise_type, args.exercise_name,
             duration, calories_burned, exercise_date, args.exercise_time,
             args.intensity, args.note, now)
        )
        conn.commit()

        record = row_to_dict(conn.execute("SELECT * FROM exercise_records WHERE id=?", (record_id,)).fetchone())
        type_name = EXERCISE_TYPE_NAMES.get(args.exercise_type, args.exercise_type)
        msg_parts = [f"已记录{m['name']}的运动: {type_name}"]
        if duration:
            msg_parts.append(f"{duration}分钟")
        if calories_burned > 0:
            msg_parts.append(f"消耗{calories_burned}kcal")

        output_json({
            "status": "ok",
            "message": "，".join(msg_parts),
            "record": record,
        })


def list_exercises(args):
    """查看运动记录。"""
    ensure_db()
    conn = get_connection()
    try:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        sql = "SELECT * FROM exercise_records WHERE member_id=? AND is_deleted=0"
        params = [args.member_id]

        if args.exercise_type:
            sql += " AND exercise_type=?"
            params.append(args.exercise_type)
        if args.start_date:
            sql += " AND exercise_date>=?"
            params.append(args.start_date)
        if args.end_date:
            sql += " AND exercise_date<=?"
            params.append(args.end_date)

        sql += " ORDER BY exercise_date DESC, created_at DESC"
        if args.limit:
            sql += " LIMIT ?"
            params.append(int(args.limit))

        rows = conn.execute(sql, params).fetchall()
        records = rows_to_list(rows)

        output_json({
            "status": "ok",
            "member_name": m["name"],
            "count": len(records),
            "records": records,
        })
    finally:
        conn.close()


def delete_exercise(args):
    """删除运动记录（软删除）。"""
    ensure_db()
    with transaction() as conn:
        row = conn.execute(
            "SELECT * FROM exercise_records WHERE id=? AND is_deleted=0",
            (args.id,)
        ).fetchone()
        if not row:
            output_json({"status": "error", "message": f"未找到运动记录: {args.id}"})
            return

        conn.execute("UPDATE exercise_records SET is_deleted=1 WHERE id=?", (args.id,))
        conn.commit()
        output_json({"status": "ok", "message": "运动记录已删除"})


def daily_summary(args):
    """某日运动摘要。"""
    ensure_db()
    conn = get_connection()
    try:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        date = args.date or datetime.now().strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT * FROM exercise_records
               WHERE member_id=? AND exercise_date=? AND is_deleted=0
               ORDER BY created_at""",
            (args.member_id, date)
        ).fetchall()
        records = rows_to_list(rows)

        total_duration = sum(r["duration"] or 0 for r in records)
        total_calories = sum(r["calories_burned"] or 0 for r in records)

        # Type breakdown
        by_type = {}
        for r in records:
            t = r["exercise_type"]
            if t not in by_type:
                by_type[t] = {"count": 0, "duration": 0, "calories": 0, "name": EXERCISE_TYPE_NAMES.get(t, t)}
            by_type[t]["count"] += 1
            by_type[t]["duration"] += r["duration"] or 0
            by_type[t]["calories"] += r["calories_burned"] or 0

        output_json({
            "status": "ok",
            "member_name": m["name"],
            "date": date,
            "exercise_count": len(records),
            "total_duration": total_duration,
            "total_calories_burned": round(total_calories, 1),
            "by_type": by_type,
            "records": records,
        })
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="运动记录管理")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add")
    p_add.add_argument("--member-id", required=True)
    p_add.add_argument("--exercise-type", required=True, help=f"运动类型: {', '.join(VALID_EXERCISE_TYPES)}")
    p_add.add_argument("--exercise-name", default=None, help="自定义名称（如'跑步5公里'）")
    p_add.add_argument("--duration", default=None, help="时长（分钟）")
    p_add.add_argument("--calories-burned", default=None, help="消耗热量 kcal")
    p_add.add_argument("--exercise-date", default=None, help="运动日期 YYYY-MM-DD")
    p_add.add_argument("--exercise-time", default=None, help="运动时间 HH:MM")
    p_add.add_argument("--intensity", default=None, help="强度: low/medium/high")
    p_add.add_argument("--note", default=None)

    # list
    p_list = sub.add_parser("list")
    p_list.add_argument("--member-id", required=True)
    p_list.add_argument("--exercise-type", default=None)
    p_list.add_argument("--start-date", default=None)
    p_list.add_argument("--end-date", default=None)
    p_list.add_argument("--limit", default=None, type=int)

    # delete
    p_del = sub.add_parser("delete")
    p_del.add_argument("--id", required=True)

    # daily-summary
    p_ds = sub.add_parser("daily-summary")
    p_ds.add_argument("--member-id", required=True)
    p_ds.add_argument("--date", default=None, help="日期 YYYY-MM-DD（默认今天）")

    args = parser.parse_args()
    commands = {
        "add": add_exercise,
        "list": list_exercises,
        "delete": delete_exercise,
        "daily-summary": daily_summary,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
