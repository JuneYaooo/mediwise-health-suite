"""Threshold configuration management for health-monitor.

Manages default and custom alert thresholds for health metrics.
Multi-level: warning → urgent → emergency.
"""

from __future__ import annotations

import sys
import os
import json
import argparse
import logging

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from path_setup import setup_mediwise_path
setup_mediwise_path()

import health_db
from metric_utils import calculate_age

logger = logging.getLogger(__name__)

# Default multi-level thresholds: {metric_type: {direction: {level: value}}}
DEFAULT_THRESHOLDS = {
    "heart_rate": {
        "above": {"warning": 100, "urgent": 120, "emergency": 150},
        "below": {"warning": 55, "urgent": 45, "emergency": 35},
    },
    "blood_oxygen": {
        "below": {"warning": 95, "urgent": 90, "emergency": 85},
    },
    "blood_pressure_systolic": {
        "above": {"warning": 140, "urgent": 160, "emergency": 180},
    },
    "blood_pressure_diastolic": {
        "above": {"warning": 90, "urgent": 100, "emergency": 110},
    },
    "temperature": {
        "above": {"warning": 37.3, "urgent": 38.5, "emergency": 39.5},
    },
    "blood_sugar": {
        "above": {"warning": 6.1, "urgent": 7.8, "emergency": 11.1},
    },
}

# Age-based threshold adjustments
_THRESHOLD_AGE_ADJUSTMENTS = {
    "elderly": {  # >= 65
        "heart_rate": {
            "below": {"warning": 50, "urgent": 40, "emergency": 30},
        },
        "blood_pressure_systolic": {
            "above": {"warning": 150, "urgent": 170, "emergency": 190},
        },
    },
    "child": {  # < 14
        "heart_rate": {
            "above": {"warning": 120, "urgent": 140, "emergency": 170},
            "below": {"warning": 70, "urgent": 60, "emergency": 50},
        },
        "blood_pressure_systolic": {
            "above": {"warning": 120, "urgent": 130, "emergency": 150},
        },
    },
}

# Reasonable value ranges per metric type for validation
_VALUE_RANGES = {
    "heart_rate": (20, 250),
    "blood_oxygen": (50, 100),
    "blood_pressure_systolic": (60, 260),
    "blood_pressure_diastolic": (30, 160),
    "temperature": (30, 45),
    "blood_sugar": (1.0, 35.0),
}


def get_thresholds(member_id: str) -> dict:
    """Get effective thresholds for a member (defaults + age adjustments + custom overrides).

    Returns dict: {metric_type: {direction: {level: value}}}
    """
    import copy
    thresholds = copy.deepcopy(DEFAULT_THRESHOLDS)

    # Single connection for both queries
    conn = health_db.get_connection()
    try:
        # Age-based adjustments
        row = conn.execute(
            "SELECT birth_date FROM members WHERE id=? AND is_deleted=0",
            (member_id,)
        ).fetchone()

        if row:
            age = calculate_age(row["birth_date"])
            if age is not None:
                if age >= 65:
                    _merge_thresholds(thresholds, _THRESHOLD_AGE_ADJUSTMENTS.get("elderly", {}))
                elif age < 14:
                    _merge_thresholds(thresholds, _THRESHOLD_AGE_ADJUSTMENTS.get("child", {}))

        # Custom overrides from monitor_thresholds table
        rows = conn.execute(
            """SELECT metric_type, direction, level, threshold_value
               FROM monitor_thresholds
               WHERE member_id=? AND is_active=1 AND is_deleted=0""",
            (member_id,)
        ).fetchall()
        for r in rows:
            mt = r["metric_type"]
            direction = r["direction"]
            level = r["level"]
            if mt not in thresholds:
                thresholds[mt] = {}
            if direction not in thresholds[mt]:
                thresholds[mt][direction] = {}
            thresholds[mt][direction][level] = r["threshold_value"]
    finally:
        conn.close()

    return thresholds


def _merge_thresholds(base: dict, override: dict):
    """Merge override thresholds into base (in-place)."""
    for metric, directions in override.items():
        if metric not in base:
            base[metric] = {}
        for direction, levels in directions.items():
            if direction not in base[metric]:
                base[metric][direction] = {}
            base[metric][direction].update(levels)


def cmd_list(args):
    """List effective thresholds for a member."""
    health_db.ensure_db()
    thresholds = get_thresholds(args.member_id)

    # Also load custom overrides to mark them
    conn = health_db.get_connection()
    try:
        custom_rows = conn.execute(
            """SELECT metric_type, direction, level, threshold_value
               FROM monitor_thresholds
               WHERE member_id=? AND is_active=1 AND is_deleted=0""",
            (args.member_id,)
        ).fetchall()
    finally:
        conn.close()

    custom_keys = {(r["metric_type"], r["direction"], r["level"]) for r in custom_rows}

    result = []
    for metric_type, directions in sorted(thresholds.items()):
        for direction, levels in sorted(directions.items()):
            for level, value in sorted(levels.items()):
                is_custom = (metric_type, direction, level) in custom_keys
                result.append({
                    "metric_type": metric_type,
                    "direction": direction,
                    "level": level,
                    "value": value,
                    "source": "custom" if is_custom else "default",
                })

    health_db.output_json({
        "status": "ok",
        "member_id": args.member_id,
        "count": len(result),
        "thresholds": result,
    })


def _validate_threshold_logic(metric_type: str, direction: str, level: str, value: float) -> str | None:
    """Validate threshold value logic. Returns error message or None if valid."""
    # Check metric_type is known
    if metric_type not in DEFAULT_THRESHOLDS:
        known = ", ".join(sorted(DEFAULT_THRESHOLDS.keys()))
        return f"未知的指标类型: {metric_type}，已知类型: {known}"

    # Check value is in reasonable range
    if metric_type in _VALUE_RANGES:
        lo, hi = _VALUE_RANGES[metric_type]
        if not (lo <= value <= hi):
            return f"{metric_type} 的阈值 {value} 不在合理范围 [{lo}, {hi}] 内"

    return None


def cmd_set(args):
    """Set a custom threshold."""
    health_db.ensure_db()

    if args.level not in ("warning", "urgent", "emergency"):
        health_db.output_json({"status": "error", "message": "level 必须为 warning/urgent/emergency"})
        return
    if args.direction not in ("above", "below"):
        health_db.output_json({"status": "error", "message": "direction 必须为 above/below"})
        return

    try:
        value = float(args.value)
    except (ValueError, TypeError):
        health_db.output_json({"status": "error", "message": "value 必须为数值"})
        return

    # Validate metric_type and value range
    validation_error = _validate_threshold_logic(args.type, args.direction, args.level, value)
    if validation_error:
        health_db.output_json({"status": "error", "message": validation_error})
        return

    with health_db.transaction() as conn:
        # Verify member
        m = conn.execute("SELECT 1 FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            health_db.output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        now = health_db.now_iso()

        # Upsert: check if exists
        existing = conn.execute(
            """SELECT id FROM monitor_thresholds
               WHERE member_id=? AND metric_type=? AND level=? AND direction=? AND is_deleted=0""",
            (args.member_id, args.type, args.level, args.direction)
        ).fetchone()

        if existing:
            conn.execute(
                """UPDATE monitor_thresholds
                   SET threshold_value=?, is_active=1, updated_at=?
                   WHERE id=?""",
                (value, now, existing["id"])
            )
        else:
            tid = health_db.generate_id()
            conn.execute(
                """INSERT INTO monitor_thresholds
                   (id, member_id, metric_type, level, direction, threshold_value, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (tid, args.member_id, args.type, args.level, args.direction, value, now, now)
            )
        conn.commit()

    health_db.output_json({
        "status": "ok",
        "message": f"已设置 {args.type} {args.direction} {args.level} 阈值为 {value}",
    })


def cmd_reset(args):
    """Reset custom thresholds for a metric type (revert to defaults)."""
    health_db.ensure_db()

    with health_db.transaction() as conn:
        conn.execute(
            """UPDATE monitor_thresholds
               SET is_deleted=1, is_active=0, updated_at=?
               WHERE member_id=? AND metric_type=? AND is_deleted=0""",
            (health_db.now_iso(), args.member_id, args.type)
        )
        conn.commit()

    health_db.output_json({
        "status": "ok",
        "message": f"已恢复 {args.type} 的默认阈值",
    })


def main():
    parser = argparse.ArgumentParser(description="健康监测阈值管理")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="查看阈值")
    p_list.add_argument("--member-id", required=True)

    p_set = sub.add_parser("set", help="设置自定义阈值")
    p_set.add_argument("--member-id", required=True)
    p_set.add_argument("--type", required=True, help="指标类型")
    p_set.add_argument("--level", required=True, choices=["warning", "urgent", "emergency"])
    p_set.add_argument("--direction", required=True, choices=["above", "below"])
    p_set.add_argument("--value", required=True, help="阈值")

    p_reset = sub.add_parser("reset", help="恢复默认阈值")
    p_reset.add_argument("--member-id", required=True)
    p_reset.add_argument("--type", required=True, help="指标类型")

    args = parser.parse_args()
    commands = {"list": cmd_list, "set": cmd_set, "reset": cmd_reset}
    commands[args.command](args)


if __name__ == "__main__":
    main()
