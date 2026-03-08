"""Alert management CLI for health-monitor.

View, resolve, and manage health monitoring alerts.
"""

from __future__ import annotations

import sys
import os
import json
import argparse
import importlib

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.path_setup import setup_mediwise_path
setup_mediwise_path()

health_db = importlib.import_module("health_db")


def _deny_member(member_id):
    health_db.output_json({"status": "error", "message": f"无权访问成员: {member_id}"})


def _deny_alert(alert_id):
    health_db.output_json({"status": "error", "message": f"无权访问告警: {alert_id}"})


def _verify_member_access(conn, member_id, owner_id):
    if owner_id and not health_db.verify_member_ownership(conn, member_id, owner_id):
        _deny_member(member_id)
        return False
    return True


def cmd_list(args):
    """List active (unresolved) alerts for a member."""
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        if not _verify_member_access(conn, args.member_id, getattr(args, "owner_id", None)):
            return
        sql = """SELECT * FROM monitor_alerts
                 WHERE member_id=? AND is_resolved=0
                 ORDER BY
                   CASE level
                     WHEN 'emergency' THEN 0
                     WHEN 'urgent' THEN 1
                     WHEN 'warning' THEN 2
                     WHEN 'info' THEN 3
                   END,
                   created_at DESC"""
        params = [args.member_id]

        if args.level:
            sql = """SELECT * FROM monitor_alerts
                     WHERE member_id=? AND is_resolved=0 AND level=?
                     ORDER BY created_at DESC"""
            params.append(args.level)

        rows = conn.execute(sql, params).fetchall()
        alerts = health_db.rows_to_list(rows)

        health_db.output_json({
            "status": "ok",
            "count": len(alerts),
            "alerts": alerts,
        })
    finally:
        conn.close()


def cmd_resolve(args):
    """Mark an alert as resolved."""
    health_db.ensure_db()

    with health_db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM monitor_alerts WHERE id=? AND is_resolved=0",
            (args.alert_id,)
        ).fetchone()
        if not row:
            health_db.output_json({"status": "error", "message": f"未找到未解决告警: {args.alert_id}"})
            return

        owner_id = getattr(args, "owner_id", None)
        if owner_id and not health_db.verify_member_ownership(conn, row["member_id"], owner_id):
            _deny_alert(args.alert_id)
            return

        resolved_at = health_db.now_iso()
        conn.execute(
            """UPDATE monitor_alerts
               SET is_resolved=1,
                   status='resolved',
                   resolved_at=?,
                   updated_at=?,
                   resolved_by=?,
                   resolution_note=?
               WHERE id=?""",
            (resolved_at, resolved_at, owner_id, getattr(args, "note", None), args.alert_id)
        )

        if row["last_reminder_id"]:
            conn.execute(
                "UPDATE reminders SET is_active=0, updated_at=? WHERE id=? AND is_deleted=0",
                (resolved_at, row["last_reminder_id"]),
            )

        health_db.append_audit_event(
            conn,
            "alert.resolved",
            member_id=row["member_id"],
            owner_id=owner_id,
            record_type="monitor_alert",
            record_id=args.alert_id,
            payload={
                "status": "resolved",
                "level": row["level"],
                "note_present": bool(getattr(args, "note", None)),
            },
        )
        conn.commit()

    health_db.output_json({
        "status": "ok",
        "message": "告警已标记为已解决",
        "alert_id": args.alert_id,
    })


def cmd_history(args):
    """Show alert history (including resolved)."""
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        if not _verify_member_access(conn, args.member_id, getattr(args, "owner_id", None)):
            return
        limit = int(args.limit) if args.limit else 20
        rows = conn.execute(
            """SELECT * FROM monitor_alerts
               WHERE member_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (args.member_id, limit)
        ).fetchall()
        alerts = health_db.rows_to_list(rows)

        health_db.output_json({
            "status": "ok",
            "count": len(alerts),
            "alerts": alerts,
        })
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="健康告警管理")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="查看未解决告警")
    p_list.add_argument("--member-id", required=True)
    p_list.add_argument("--owner-id", default=None)
    p_list.add_argument("--level", default=None, choices=["info", "warning", "urgent", "emergency"])

    p_resolve = sub.add_parser("resolve", help="标记告警已解决")
    p_resolve.add_argument("--alert-id", required=True)
    p_resolve.add_argument("--owner-id", default=None)
    p_resolve.add_argument("--note", default=None)

    p_history = sub.add_parser("history", help="告警历史")
    p_history.add_argument("--member-id", required=True)
    p_history.add_argument("--owner-id", default=None)
    p_history.add_argument("--limit", default="20")

    args = parser.parse_args()
    commands = {"list": cmd_list, "resolve": cmd_resolve, "history": cmd_history}
    commands[args.command](args)


if __name__ == "__main__":
    main()
