"""Health memory and proactive tracking for MediWise Health Tracker.

Commands:
  log      --member-id --content --category [--follow-up-days 5]
           → Capture a casual health mention and create a follow-up reminder

  list     --member-id [--owner-id] [--include-resolved]
           → List unresolved health notes; highlights overdue follow-ups

  resolve  --note-id [--resolution-note] [--owner-id]
           → Mark a health note as resolved with an optional resolution note

Importable API:
  get_pending_notes(member_id, owner_id=None) → list[dict]
           → Returns unresolved notes whose follow_up_date is today or earlier;
             used by health_advisor.get_daily_briefing() for briefing integration.
"""

from __future__ import annotations

import argparse
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import health_db
from health_db import (
    ensure_db, transaction, generate_id, now_iso,
    row_to_dict, rows_to_list, output_json,
    verify_member_ownership,
)
import reminder as reminder_mod


VALID_CATEGORIES = ("symptom", "concern", "goal", "observation", "other")


def _table_exists(conn) -> bool:
    """Check whether the health_notes table exists (may not be migrated yet)."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='health_notes'"
    ).fetchone()
    return bool(row)


def get_pending_notes(member_id: str, owner_id: str = None) -> list[dict]:
    """Return unresolved health notes whose follow_up_date is today or earlier.

    Designed to be imported by health_advisor.get_daily_briefing() for
    seamless integration into the daily health briefing.
    """
    ensure_db()
    today = datetime.now().strftime("%Y-%m-%d")
    conn = health_db.get_medical_connection()
    try:
        if not _table_exists(conn):
            return []
        rows = conn.execute(
            """SELECT * FROM health_notes
               WHERE member_id=? AND is_resolved=0 AND is_deleted=0
                 AND follow_up_date IS NOT NULL AND follow_up_date <= ?
               ORDER BY follow_up_date ASC""",
            (member_id, today),
        ).fetchall()
    finally:
        conn.close()

    notes = rows_to_list(rows)
    today_dt = datetime.now().date()
    for note in notes:
        try:
            mentioned = datetime.strptime(note["mentioned_at"], "%Y-%m-%d").date()
            note["days_since_mentioned"] = (today_dt - mentioned).days
        except Exception:
            note["days_since_mentioned"] = 0
    return notes


def cmd_log(args):
    """Capture a casual health mention and schedule a follow-up reminder."""
    ensure_db()

    category = args.category if args.category in VALID_CATEGORIES else "other"
    today = datetime.now().strftime("%Y-%m-%d")
    follow_up_days = getattr(args, "follow_up_days", 5) or 5
    follow_up_date = (datetime.now() + timedelta(days=follow_up_days)).strftime("%Y-%m-%d")
    owner_id = getattr(args, "owner_id", None)

    with transaction(domain="medical") as conn:
        if not _table_exists(conn):
            output_json({
                "status": "error",
                "message": "health_notes 表不存在，请先运行 setup.py 更新数据库",
            })
            return

        m = conn.execute(
            "SELECT id, name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)
        ).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return
        if not verify_member_ownership(conn, args.member_id, owner_id):
            output_json({"status": "error", "message": "无权操作该成员"})
            return

        note_id = generate_id()
        ts = now_iso()
        conn.execute(
            """INSERT INTO health_notes
               (id, member_id, owner_id, content, category, mentioned_at,
                follow_up_date, is_resolved, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (note_id, args.member_id, owner_id, args.content, category, today, follow_up_date, ts),
        )
        conn.commit()
        note = row_to_dict(conn.execute(
            "SELECT * FROM health_notes WHERE id=?", (note_id,)
        ).fetchone())

    # Create follow-up reminder
    reminder_result = None
    try:
        reminder_result = reminder_mod.create_reminder(
            member_id=args.member_id,
            reminder_type="health_note",
            title=f"健康跟进：{args.content[:30]}",
            schedule_type="once",
            schedule_value=follow_up_date,
            content=f"你之前提到：{args.content}\n记得告诉我是否有改善。",
            related_record_id=note_id,
            related_record_type="health_note",
            priority="normal",
            owner_id=owner_id,
        )
    except Exception as e:
        reminder_result = {"error": str(e)}

    output_json({
        "status": "ok",
        "message": f"已记录健康备注，将在{follow_up_days}天后（{follow_up_date}）跟进",
        "note": note,
        "follow_up_reminder": reminder_result,
    })


def cmd_list(args):
    """List health notes for a member, highlighting overdue follow-ups."""
    ensure_db()
    today = datetime.now().strftime("%Y-%m-%d")
    today_dt = datetime.now().date()
    owner_id = getattr(args, "owner_id", None)

    conn = health_db.get_medical_connection()
    try:
        if not _table_exists(conn):
            output_json({"status": "ok", "notes": [], "message": "暂无健康备注记录"})
            return
        if not verify_member_ownership(conn, args.member_id, owner_id):
            output_json({"status": "error", "message": "无权操作该成员"})
            return

        include_resolved = getattr(args, "include_resolved", False)
        if include_resolved:
            rows = conn.execute(
                """SELECT * FROM health_notes
                   WHERE member_id=? AND is_deleted=0
                   ORDER BY is_resolved ASC, mentioned_at DESC""",
                (args.member_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM health_notes
                   WHERE member_id=? AND is_deleted=0 AND is_resolved=0
                   ORDER BY follow_up_date ASC, mentioned_at DESC""",
                (args.member_id,),
            ).fetchall()
    finally:
        conn.close()

    notes = rows_to_list(rows)
    overdue = []
    upcoming = []

    for note in notes:
        try:
            mentioned = datetime.strptime(note["mentioned_at"], "%Y-%m-%d").date()
            note["days_since_mentioned"] = (today_dt - mentioned).days
        except Exception:
            note["days_since_mentioned"] = 0

        fd = note.get("follow_up_date")
        if fd and not note.get("is_resolved"):
            if fd <= today:
                overdue.append(note)
            else:
                upcoming.append(note)

    output_json({
        "status": "ok",
        "total": len(notes),
        "overdue_count": len(overdue),
        "notes": notes,
        "overdue": overdue,
        "upcoming": upcoming,
    })


def cmd_resolve(args):
    """Mark a health note as resolved."""
    ensure_db()
    owner_id = getattr(args, "owner_id", None)

    with transaction(domain="medical") as conn:
        if not _table_exists(conn):
            output_json({"status": "error", "message": "health_notes 表不存在"})
            return

        note = row_to_dict(conn.execute(
            "SELECT * FROM health_notes WHERE id=? AND is_deleted=0", (args.note_id,)
        ).fetchone())
        if not note:
            output_json({"status": "error", "message": f"未找到健康备注: {args.note_id}"})
            return
        if not verify_member_ownership(conn, note["member_id"], owner_id):
            output_json({"status": "error", "message": "无权操作该记录"})
            return

        ts = now_iso()
        conn.execute(
            """UPDATE health_notes SET
               is_resolved=1, resolved_at=?, resolution_note=?
               WHERE id=?""",
            (ts, getattr(args, "resolution_note", None), args.note_id),
        )
        conn.commit()
        updated = row_to_dict(conn.execute(
            "SELECT * FROM health_notes WHERE id=?", (args.note_id,)
        ).fetchone())

    output_json({
        "status": "ok",
        "message": "健康备注已标记为已解决",
        "note": updated,
    })


def main():
    parser = argparse.ArgumentParser(description="健康记忆追踪")
    sub = parser.add_subparsers(dest="command", required=True)

    # log
    p = sub.add_parser("log", help="记录健康备注")
    p.add_argument("--member-id", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--category", default="other", choices=list(VALID_CATEGORIES))
    p.add_argument("--follow-up-days", type=int, default=5)
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    # list
    p = sub.add_parser("list", help="查看健康备注")
    p.add_argument("--member-id", required=True)
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
    p.add_argument("--include-resolved", action="store_true", default=False)

    # resolve
    p = sub.add_parser("resolve", help="标记健康备注已解决")
    p.add_argument("--note-id", required=True)
    p.add_argument("--resolution-note", default=None)
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    args = parser.parse_args()
    commands = {
        "log": cmd_log,
        "list": cmd_list,
        "resolve": cmd_resolve,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
