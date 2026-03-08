"""Anomaly detection engine for health-monitor.

Checks health_metrics against thresholds and generates alerts.
Supports time-window based checking and 24h deduplication.
"""

from __future__ import annotations

import sys
import os
import argparse
import re
import importlib
import logging
from datetime import datetime, timedelta

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.path_setup import setup_mediwise_path
setup_mediwise_path()

sys.path.insert(0, os.path.dirname(__file__))

health_db = importlib.import_module("health_db")
metric_utils = importlib.import_module("metric_utils")
parse_metric_value = metric_utils.parse_metric_value
extract_numeric_value = metric_utils.extract_numeric_value
METRIC_UNITS = metric_utils.METRIC_UNITS
from threshold import get_thresholds
load_config = importlib.import_module("config").load_config

logger = logging.getLogger(__name__)


def _parse_window(window_str: str) -> timedelta:
    """Parse a time window string like '1h', '24h', '7d' into timedelta."""
    match = re.match(r'^(\d+)(h|d|m)$', window_str.strip())
    if not match:
        return timedelta(hours=1)  # default 1h
    num = int(match.group(1))
    unit = match.group(2)
    if unit == 'h':
        return timedelta(hours=num)
    elif unit == 'd':
        return timedelta(days=num)
    elif unit == 'm':
        return timedelta(minutes=num)
    return timedelta(hours=1)


def _has_recent_alert(conn, member_id: str, metric_type: str, level: str,
                      cooldown_hours: int = 24) -> bool:
    """Check if an alert of the same type+level was created within cooldown period."""
    cutoff = (datetime.now() - timedelta(hours=cooldown_hours)).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        """SELECT 1 FROM monitor_alerts
           WHERE member_id=? AND metric_type=? AND level=? AND created_at>=?
           LIMIT 1""",
        (member_id, metric_type, level, cutoff)
    ).fetchone()
    return row is not None


def _determine_level(value: float, direction: str, levels: dict) -> str | None:
    """Determine the highest alert level triggered.

    Checks from emergency → urgent → warning (highest first).
    Returns the level name or None if no threshold is breached.
    """
    for level in ("emergency", "urgent", "warning"):
        threshold = levels.get(level)
        if threshold is None:
            continue
        if direction == "above" and value > threshold:
            return level
        if direction == "below" and value < threshold:
            return level
    return None


def _create_alert(conn, member_id: str, metric_type: str, level: str,
                  title: str, detail: str, metric_value: str,
                  threshold_value: float):
    """Insert a new alert record."""
    alert_id = health_db.generate_id()
    now = health_db.now_iso()
    owner_id = health_db.get_member_owner_id(conn, member_id)
    conn.execute(
        """INSERT INTO monitor_alerts
           (id, member_id, metric_type, level, title, detail, metric_value,
            threshold_value, status, updated_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (alert_id, member_id, metric_type, level, title, detail,
         metric_value, threshold_value, "open", now, now)
    )
    health_db.append_audit_event(
        conn,
        "alert.created",
        member_id=member_id,
        owner_id=owner_id,
        record_type="monitor_alert",
        record_id=alert_id,
        payload={
            "metric_type": metric_type,
            "level": level,
            "status": "open",
        },
    )
    return alert_id


def _create_reminder_for_alert(member_id: str, alert_id: str, level: str, title: str, detail: str):
    """Create a reminder based on alert level."""
    if level == "info":
        return None

    try:
        reminder_mod = importlib.import_module("reminder")

        priority_map = {
            "warning": "normal",
            "urgent": "high",
            "emergency": "urgent",
        }
        priority = priority_map.get(level, "normal")

        result = reminder_mod.create_reminder(
            member_id=member_id,
            reminder_type="custom",
            title=f"健康告警: {title}",
            schedule_type="once",
            schedule_value=(datetime.now() + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M"),
            content=detail,
            related_record_id=alert_id,
            related_record_type="monitor_alert",
            priority=priority,
        )
        return result.get("id") if isinstance(result, dict) else None
    except Exception as e:
        logger.warning("Failed to create reminder for alert '%s': %s", title, e)
    return None


def _check_metric_value(conn, member_id: str, member_name: str,
                        metric_type: str, value: float, unit: str,
                        thresholds: dict, cooldown_hours: int,
                        alerts_generated: list,
                        reminders_to_create: list):
    """Check a single metric value against thresholds and generate alerts.

    This unified function handles both blood pressure sub-metrics and
    regular single-value metrics identically.
    """
    directions = thresholds.get(metric_type, {})
    for direction, levels in directions.items():
        level = _determine_level(value, direction, levels)
        if level and not _has_recent_alert(conn, member_id, metric_type, level, cooldown_hours):
            threshold_val = levels[level]
            dir_cn = "高于" if direction == "above" else "低于"
            display_unit = METRIC_UNITS.get(metric_type, unit)
            title = f"{member_name} {metric_type} {dir_cn}阈值"
            detail = f"{metric_type}: {value} {display_unit}，{level} 阈值: {threshold_val} {display_unit}"

            alert_id = _create_alert(conn, member_id, metric_type, level,
                                     title, detail, str(value), threshold_val)
            alerts_generated.append({
                "alert_id": alert_id,
                "metric_type": metric_type,
                "level": level,
                "title": title,
                "value": value,
                "threshold": threshold_val,
            })
            reminders_to_create.append({
                "alert_id": alert_id,
                "member_id": member_id,
                "level": level,
                "title": title,
                "detail": detail,
            })


def check_member(member_id: str, window: str = "1h") -> dict:
    """Run anomaly detection for a single member.

    Args:
        member_id: Member to check.
        window: Time window string (e.g. "1h", "24h", "7d").

    Returns:
        Dict with alerts generated.
    """
    health_db.ensure_db()
    thresholds = get_thresholds(member_id)

    # Load cooldown config
    cfg = load_config()
    cooldown_hours = cfg.get("monitor", {}).get("alert_cooldown_hours", 24)

    td = _parse_window(window)
    cutoff = (datetime.now() - td).strftime("%Y-%m-%d %H:%M:%S")

    conn = health_db.get_connection()
    alerts_generated = []
    reminders_to_create = []

    try:
        # Get member name
        member = conn.execute(
            "SELECT name FROM members WHERE id=? AND is_deleted=0",
            (member_id,)
        ).fetchone()
        if not member:
            return {"status": "error", "message": f"未找到成员: {member_id}"}
        member_name = member["name"]

        # Fetch recent metrics within window
        metrics = health_db.rows_to_list(conn.execute(
            """SELECT * FROM health_metrics
               WHERE member_id=? AND is_deleted=0 AND measured_at>=?
               ORDER BY measured_at DESC""",
            (member_id, cutoff)
        ).fetchall())

        for metric in metrics:
            mt = metric["metric_type"]
            raw_value = metric["value"]
            parsed = parse_metric_value(raw_value)

            # Blood pressure: expand to systolic + diastolic sub-checks
            if mt == "blood_pressure":
                for sub_key, threshold_key in [("systolic", "blood_pressure_systolic"),
                                                ("diastolic", "blood_pressure_diastolic")]:
                    val = parsed.get(sub_key)
                    if val is None:
                        continue
                    try:
                        val = float(val)
                    except (TypeError, ValueError):
                        continue
                    _check_metric_value(conn, member_id, member_name,
                                        threshold_key, val, "mmHg",
                                        thresholds, cooldown_hours, alerts_generated,
                                        reminders_to_create)
            else:
                # Single-value metrics
                val = extract_numeric_value(raw_value, mt)
                if val is None:
                    continue
                _check_metric_value(conn, member_id, member_name,
                                    mt, val, "",
                                    thresholds, cooldown_hours, alerts_generated,
                                    reminders_to_create)

        conn.commit()
    finally:
        conn.close()

    for reminder_payload in reminders_to_create:
        reminder_id = _create_reminder_for_alert(
            reminder_payload["member_id"],
            reminder_payload["alert_id"],
            reminder_payload["level"],
            reminder_payload["title"],
            reminder_payload["detail"],
        )
        if reminder_id:
            with health_db.transaction() as conn:
                conn.execute(
                    "UPDATE monitor_alerts SET last_reminder_id=? WHERE id=?",
                    (reminder_id, reminder_payload["alert_id"]),
                )
                conn.commit()

    return {
        "status": "ok",
        "member_id": member_id,
        "window": window,
        "metrics_checked": len(metrics),
        "alerts_generated": len(alerts_generated),
        "alerts": alerts_generated,
    }


def cmd_run(args):
    """Run check for a member."""
    result = check_member(args.member_id, args.window or "1h")
    health_db.output_json(result)


def cmd_run_all(args):
    """Run check for all members."""
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        members = conn.execute(
            "SELECT id, name FROM members WHERE is_deleted=0"
        ).fetchall()
    finally:
        conn.close()

    window = args.window or "1h"
    results = []
    total_alerts = 0
    for m in members:
        result = check_member(m["id"], window)
        total_alerts += result.get("alerts_generated", 0)
        results.append(result)

    health_db.output_json({
        "status": "ok",
        "members_checked": len(members),
        "total_alerts": total_alerts,
        "window": window,
        "results": results,
    })


def main():
    parser = argparse.ArgumentParser(description="健康异常检测")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="检查单个成员")
    p_run.add_argument("--member-id", required=True)
    p_run.add_argument("--window", default="1h", help="检查时间窗口: 1h/24h/7d")

    p_all = sub.add_parser("run-all", help="检查所有成员")
    p_all.add_argument("--window", default="1h", help="检查时间窗口: 1h/24h/7d")

    args = parser.parse_args()
    commands = {"run": cmd_run, "run-all": cmd_run_all}
    commands[args.command](args)


if __name__ == "__main__":
    main()
