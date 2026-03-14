"""服药打卡记录（自愿打卡，用户随手记录已服药）。

Commands:
  log-taken  --member-id --medication-name [--taken-at] [--dose-taken] [--note]
             → 记录一次服药打卡

  list       --member-id [--medication-name] [--days 30] [--limit]
             → 查看服药打卡历史
"""

from __future__ import annotations

import argparse
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from health_db import (
    ensure_db, transaction, get_medical_connection,
    generate_id, now_iso, row_to_dict, rows_to_list,
    output_json, verify_member_ownership,
)
from validators import validate_datetime_optional


def cmd_log_taken(args):
    """记录一次服药打卡。"""
    ensure_db()

    try:
        taken_at = validate_datetime_optional(getattr(args, 'taken_at', None), "服药时间") or now_iso()
    except ValueError as e:
        output_json({"status": "error", "message": str(e)})
        return

    with transaction(domain="medical") as conn:
        m = conn.execute(
            "SELECT id, name FROM members WHERE id=? AND is_deleted=0",
            (args.member_id,)
        ).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return
        if not verify_member_ownership(conn, args.member_id, getattr(args, 'owner_id', None)):
            output_json({"status": "error", "message": "无权操作该成员"})
            return

        # Try to resolve medication_id from active medications
        med_row = conn.execute(
            """SELECT id FROM medications
               WHERE member_id=? AND name=? AND is_active=1 AND is_deleted=0
               ORDER BY start_date DESC LIMIT 1""",
            (args.member_id, args.medication_name)
        ).fetchone()
        medication_id = med_row["id"] if med_row else None

        log_id = generate_id()
        conn.execute(
            """INSERT INTO medication_logs
               (id, member_id, medication_id, medication_name, taken_at, dose_taken, note, created_at, is_deleted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (log_id, args.member_id, medication_id, args.medication_name,
             taken_at, getattr(args, 'dose_taken', None), getattr(args, 'note', None), now_iso())
        )
        conn.commit()
        log = row_to_dict(conn.execute("SELECT * FROM medication_logs WHERE id=?", (log_id,)).fetchone())

    output_json({
        "status": "ok",
        "message": f"已记录{m['name']}服药打卡：{args.medication_name}",
        "log": log,
    })


def cmd_list(args):
    """查看服药打卡历史。"""
    ensure_db()
    conn = get_medical_connection()
    try:
        if not verify_member_ownership(conn, args.member_id, getattr(args, 'owner_id', None)):
            output_json({"status": "error", "message": "无权操作该成员"})
            return

        days = getattr(args, 'days', 30) or 30
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        sql = """SELECT * FROM medication_logs
                 WHERE member_id=? AND is_deleted=0 AND taken_at >= ?"""
        params = [args.member_id, cutoff]

        med_name = getattr(args, 'medication_name', None)
        if med_name:
            sql += " AND medication_name=?"
            params.append(med_name)

        sql += " ORDER BY taken_at DESC"

        limit = getattr(args, 'limit', None)
        if limit:
            sql += " LIMIT ?"
            params.append(int(limit))

        rows = rows_to_list(conn.execute(sql, params).fetchall())

        # Group by medication_name for summary
        summary: dict[str, int] = {}
        for r in rows:
            summary[r["medication_name"]] = summary.get(r["medication_name"], 0) + 1

        output_json({
            "status": "ok",
            "member_id": args.member_id,
            "period_days": days,
            "count": len(rows),
            "summary": summary,
            "logs": rows,
        })
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="服药打卡记录")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("log-taken", help="记录服药打卡")
    p.add_argument("--member-id", required=True)
    p.add_argument("--medication-name", required=True, help="药物名称")
    p.add_argument("--taken-at", default=None, help="服药时间 (YYYY-MM-DD HH:MM)，默认当前时间")
    p.add_argument("--dose-taken", default=None, help="本次剂量，如 '1粒'、'500mg'")
    p.add_argument("--note", default=None, help="备注")
    p.add_argument("--owner-id", default=None)

    p = sub.add_parser("list", help="查看打卡历史")
    p.add_argument("--member-id", required=True)
    p.add_argument("--medication-name", default=None, help="按药物名筛选")
    p.add_argument("--days", type=int, default=30, help="查看最近几天（默认 30）")
    p.add_argument("--limit", type=int, default=None, help="最多返回条数")
    p.add_argument("--owner-id", default=None)

    args = parser.parse_args()
    {"log-taken": cmd_log_taken, "list": cmd_list}[args.command](args)


if __name__ == "__main__":
    main()
