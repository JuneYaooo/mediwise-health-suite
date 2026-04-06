"""每日健康状态快照 — 存储与查询。

每日简报生成后调用 save，将当日健康状态持久化到 daily_health_snapshots 表，
供后续对话中回顾（"昨天状态怎么样"、"这周血压趋势"等）。

Commands:
  save    --member-id --owner-id          保存当日快照（从 health_advisor 实时生成）
  save-all --owner-id                     为 owner 所有成员各保存一份
  get     --member-id --date YYYY-MM-DD   查询某天快照
  history --member-id [--days 7]          查询最近 N 天快照列表
  trend   --member-id [--days 30]         返回风险等级趋势（用于图表/对话描述）

Importable API:
  save_snapshot(member_id, owner_id, briefing_data) -> dict
  get_snapshot(member_id, date_str, owner_id) -> dict | None
  get_history(member_id, days, owner_id) -> list[dict]
  get_trend(member_id, days, owner_id) -> list[dict]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import health_db
from health_db import (
    ensure_db, transaction, get_medical_connection,
    generate_id, now_iso,
    row_to_dict, rows_to_list, output_json,
    verify_member_ownership,
)


# ------------------------------------------------------------------ helpers

def _table_exists(conn) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_health_snapshots'"
    ).fetchone()
    return bool(row)


def _risk_from_briefing(briefing_data: dict) -> str:
    """Derive a single risk_level string from briefing dict."""
    alerts   = briefing_data.get("total_alerts", 0)
    warnings = briefing_data.get("total_warnings", 0)
    if alerts > 0:
        return "alert"
    if warnings > 0:
        return "warning"
    return "ok"


def _build_summary_text(briefing_data: dict, member_name: str) -> str:
    """Produce a ≤120-char plain-text summary for quick display."""
    risk = _risk_from_briefing(briefing_data)
    alerts   = briefing_data.get("total_alerts", 0)
    warnings = briefing_data.get("total_warnings", 0)
    reminders = briefing_data.get("total_due_reminders", 0)

    if risk == "ok" and reminders == 0:
        return f"{member_name}今日健康状况良好，无待处理事项"

    parts = []
    if alerts:
        parts.append(f"{alerts}项异常")
    if warnings:
        parts.append(f"{warnings}项提醒")
    if reminders:
        parts.append(f"{reminders}项待处理提醒")
    return f"{member_name}今日：{'、'.join(parts)}"


def _extract_metrics_summary(briefing_data: dict) -> str:
    """Extract key metric values from briefing tips for quick recall."""
    metrics = {}
    for mb in briefing_data.get("briefing", []):
        for tip in mb.get("health_tips", []):
            detail = tip.get("detail", "")
            # Store short tip titles as context
            title = tip.get("title", "")
            if title and len(title) < 40:
                t = tip.get("type", "general")
                metrics[t] = title
    return json.dumps(metrics, ensure_ascii=False) if metrics else "{}"


# ------------------------------------------------------------------ public API

def save_snapshot(member_id: str, owner_id: str, briefing_data: dict) -> dict:
    """Persist today's health snapshot for a single member.

    briefing_data: the full dict returned by health_advisor.get_daily_briefing()
                   (either the whole-family dict or a single-member subset).
    """
    ensure_db()
    today = datetime.now().strftime("%Y-%m-%d")

    conn = get_medical_connection()
    try:
        if not _table_exists(conn):
            return {"status": "error", "message": "daily_health_snapshots 表不存在，请先运行 setup.py"}
        if not verify_member_ownership(conn, member_id, owner_id):
            return {"status": "error", "message": f"无权操作成员: {member_id}"}
        row = conn.execute(
            "SELECT name FROM members WHERE id=? AND is_deleted=0", (member_id,)
        ).fetchone()
        member_name = row["name"] if row else member_id
    finally:
        conn.close()

    # Extract per-member briefing slice if passed a whole-family briefing
    member_briefing = briefing_data
    for mb in briefing_data.get("briefing", []):
        if mb.get("member_id") == member_id:
            # Wrap in same top-level shape for consistency
            member_briefing = {
                **briefing_data,
                "briefing": [mb],
                "total_alerts":       len([t for t in mb.get("health_tips", []) if t.get("severity") == "alert"]),
                "total_warnings":     len([t for t in mb.get("health_tips", []) if t.get("severity") == "warning"]),
                "total_due_reminders": len(mb.get("due_reminders", [])),
            }
            break

    risk_level     = _risk_from_briefing(member_briefing)
    summary_text   = _build_summary_text(member_briefing, member_name)
    metrics_summary = _extract_metrics_summary(member_briefing)
    briefing_json  = json.dumps(member_briefing, ensure_ascii=False)
    ts = now_iso()

    with transaction(domain="medical") as conn:
        # Upsert: one row per (member_id, snapshot_date)
        existing = conn.execute(
            "SELECT id FROM daily_health_snapshots WHERE member_id=? AND snapshot_date=? AND is_deleted=0",
            (member_id, today),
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE daily_health_snapshots SET
                   risk_level=?, summary_text=?, briefing_json=?,
                   metrics_summary=?,
                   alerts_count=?, warnings_count=?, reminders_count=?,
                   updated_at=?
                   WHERE id=?""",
                (risk_level, summary_text, briefing_json,
                 metrics_summary,
                 member_briefing.get("total_alerts", 0),
                 member_briefing.get("total_warnings", 0),
                 member_briefing.get("total_due_reminders", 0),
                 ts, existing["id"]),
            )
            snap_id = existing["id"]
            action = "updated"
        else:
            snap_id = generate_id()
            conn.execute(
                """INSERT INTO daily_health_snapshots
                   (id, member_id, owner_id, snapshot_date,
                    risk_level, summary_text, briefing_json,
                    metrics_summary,
                    alerts_count, warnings_count, reminders_count,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (snap_id, member_id, owner_id, today,
                 risk_level, summary_text, briefing_json,
                 metrics_summary,
                 member_briefing.get("total_alerts", 0),
                 member_briefing.get("total_warnings", 0),
                 member_briefing.get("total_due_reminders", 0),
                 ts, ts),
            )
            action = "created"
        conn.commit()

    return {
        "status": "ok",
        "action": action,
        "snapshot_id": snap_id,
        "snapshot_date": today,
        "member_id": member_id,
        "risk_level": risk_level,
        "summary": summary_text,
    }


def get_snapshot(member_id: str, date_str: str, owner_id: str = None) -> dict | None:
    """Return a single day's snapshot, or None if not found."""
    ensure_db()
    conn = get_medical_connection()
    try:
        if not _table_exists(conn):
            return None
        if not verify_member_ownership(conn, member_id, owner_id):
            return None
        row = conn.execute(
            """SELECT * FROM daily_health_snapshots
               WHERE member_id=? AND snapshot_date=? AND is_deleted=0""",
            (member_id, date_str),
        ).fetchone()
        return row_to_dict(row) if row else None
    finally:
        conn.close()


def get_history(member_id: str, days: int = 7, owner_id: str = None) -> list[dict]:
    """Return the last N days of snapshots, newest first."""
    ensure_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_medical_connection()
    try:
        if not _table_exists(conn):
            return []
        if not verify_member_ownership(conn, member_id, owner_id):
            return []
        rows = conn.execute(
            """SELECT id, snapshot_date, risk_level, summary_text,
                      alerts_count, warnings_count, reminders_count
               FROM daily_health_snapshots
               WHERE member_id=? AND snapshot_date>=? AND is_deleted=0
               ORDER BY snapshot_date DESC""",
            (member_id, cutoff),
        ).fetchall()
        return rows_to_list(rows)
    finally:
        conn.close()


def get_trend(member_id: str, days: int = 30, owner_id: str = None) -> list[dict]:
    """Return risk-level trend for charting/narrative.

    Each entry: {snapshot_date, risk_level, alerts_count, warnings_count}
    Ordered chronologically (oldest first) for trend display.
    """
    ensure_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    conn = get_medical_connection()
    try:
        if not _table_exists(conn):
            return []
        if not verify_member_ownership(conn, member_id, owner_id):
            return []
        rows = conn.execute(
            """SELECT snapshot_date, risk_level, alerts_count, warnings_count
               FROM daily_health_snapshots
               WHERE member_id=? AND snapshot_date>=? AND is_deleted=0
               ORDER BY snapshot_date ASC""",
            (member_id, cutoff),
        ).fetchall()
        return rows_to_list(rows)
    finally:
        conn.close()


# ------------------------------------------------------------------ CLI

def cmd_save(args):
    import health_advisor
    owner_id = getattr(args, "owner_id", None) or os.environ.get("MEDIWISE_OWNER_ID")
    briefing = health_advisor.get_daily_briefing(args.member_id, owner_id)
    result = save_snapshot(args.member_id, owner_id, briefing)
    output_json(result)


def cmd_save_all(args):
    ensure_db()
    owner_id = getattr(args, "owner_id", None) or os.environ.get("MEDIWISE_OWNER_ID")

    import health_advisor
    briefing = health_advisor.get_daily_briefing(None, owner_id)

    conn = get_medical_connection()
    try:
        if owner_id:
            rows = conn.execute(
                "SELECT id FROM members WHERE is_deleted=0 AND owner_id=?", (owner_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM members WHERE is_deleted=0"
            ).fetchall()
    finally:
        conn.close()

    results = []
    for row in rows:
        mid = row["id"]
        results.append(save_snapshot(mid, owner_id, briefing))

    total_saved = sum(1 for r in results if r.get("status") == "ok")
    output_json({
        "status": "ok",
        "message": f"已为 {total_saved}/{len(results)} 位成员保存今日快照",
        "results": results,
    })


def cmd_get(args):
    owner_id = getattr(args, "owner_id", None) or os.environ.get("MEDIWISE_OWNER_ID")
    snap = get_snapshot(args.member_id, args.date, owner_id)
    if snap is None:
        output_json({"status": "error", "message": f"未找到 {args.date} 的快照"})
        return
    # Don't return the full briefing_json by default (too large for chat)
    snap.pop("briefing_json", None)
    output_json({"status": "ok", "snapshot": snap})


def cmd_history(args):
    owner_id = getattr(args, "owner_id", None) or os.environ.get("MEDIWISE_OWNER_ID")
    days = int(args.days) if args.days else 7
    history = get_history(args.member_id, days, owner_id)
    output_json({
        "status": "ok",
        "member_id": args.member_id,
        "days": days,
        "count": len(history),
        "history": history,
    })


def cmd_trend(args):
    owner_id = getattr(args, "owner_id", None) or os.environ.get("MEDIWISE_OWNER_ID")
    days = int(args.days) if args.days else 30
    trend = get_trend(args.member_id, days, owner_id)
    output_json({
        "status": "ok",
        "member_id": args.member_id,
        "days": days,
        "trend": trend,
    })


def main():
    parser = argparse.ArgumentParser(description="每日健康快照管理")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("save", help="保存当日快照（单个成员）")
    p.add_argument("--member-id", required=True)
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    p = sub.add_parser("save-all", help="为 owner 所有成员保存今日快照")
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    p = sub.add_parser("get", help="查询某天快照")
    p.add_argument("--member-id", required=True)
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    p = sub.add_parser("history", help="查询最近 N 天快照列表")
    p.add_argument("--member-id", required=True)
    p.add_argument("--days", default="7")
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    p = sub.add_parser("trend", help="返回风险等级趋势")
    p.add_argument("--member-id", required=True)
    p.add_argument("--days", default="30")
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    args = parser.parse_args()
    {
        "save":     cmd_save,
        "save-all": cmd_save_all,
        "get":      cmd_get,
        "history":  cmd_history,
        "trend":    cmd_trend,
    }[args.command](args)


if __name__ == "__main__":
    main()
