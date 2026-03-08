"""Cycle Tracker — 周期追踪（经期/周期性疾病）。

支持经期、偏头痛、过敏等周期性事件的记录、历史查看、预测和状态查询。

Usage:
  python3 cycle_tracker.py record --member-id <id> --cycle-type menstrual --event-type period_start --date 2025-03-01
  python3 cycle_tracker.py history --member-id <id> --cycle-type menstrual [--limit 12]
  python3 cycle_tracker.py predict --member-id <id> --cycle-type menstrual
  python3 cycle_tracker.py status --member-id <id> --cycle-type menstrual
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, date

sys.path.insert(0, os.path.dirname(__file__))
import health_db


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CYCLE_TYPES = ["menstrual", "migraine", "allergy", "custom"]
VALID_EVENT_TYPES = {
    "menstrual": ["period_start", "period_end", "symptom", "note"],
    "migraine": ["attack_start", "attack_end", "symptom", "note"],
    "allergy": ["flare_start", "flare_end", "symptom", "note"],
    "custom": ["event_start", "event_end", "symptom", "note"],
}

# Default cycle length assumptions for first prediction
DEFAULT_CYCLE_LENGTHS = {
    "menstrual": 28,
    "migraine": 30,
    "allergy": 90,
    "custom": 30,
}

# Menstrual phase definitions (days from period start)
MENSTRUAL_PHASES = {
    "menstrual": (0, 5),      # Day 0-5: menstruation
    "follicular": (6, 13),    # Day 6-13: follicular phase
    "ovulation": (14, 16),    # Day 14-16: ovulation window
    "luteal": (17, 28),       # Day 17-28: luteal phase
}

CARE_TIPS = {
    "menstrual": {
        "menstrual": [
            "注意保暖，避免受凉",
            "适当休息，避免剧烈运动",
            "可以喝红糖姜茶缓解不适",
            "如痛经严重可咨询医生用药",
        ],
        "follicular": [
            "精力较好的时期，适合增加运动量",
            "注意补充铁质食物（红肉、菠菜等）",
        ],
        "ovulation": [
            "排卵期，如有生育计划可关注",
            "部分人可能出现排卵痛，属于正常现象",
        ],
        "luteal": [
            "可能出现经前综合征（PMS）症状",
            "注意调节情绪，保持充足睡眠",
            "减少咖啡因和盐分摄入",
            "适当运动有助于缓解不适",
        ],
        "premenstrual": [
            "经期即将到来，请提前准备",
            "注意保暖和休息",
            "如有痛经史，可提前咨询医生准备用药",
        ],
    },
    "migraine": {
        "warning": [
            "根据历史规律，偏头痛可能即将发作",
            "注意避免已知诱因（如强光、噪音、特定食物）",
            "保持规律作息，避免熬夜",
            "如有预防性用药，请按时服用",
        ],
    },
    "allergy": {
        "warning": [
            "根据历史规律，过敏症状可能即将出现",
            "提前准备抗过敏药物",
            "注意减少过敏原接触",
            "外出戴口罩，回家后清洗面部和鼻腔",
        ],
    },
}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def record_event(member_id: str, cycle_type: str, event_type: str,
                 event_date: str, details: str = None) -> dict:
    """Record a cycle event."""
    health_db.ensure_db()

    if cycle_type not in VALID_CYCLE_TYPES:
        return {"error": f"不支持的周期类型: {cycle_type}，支持: {', '.join(VALID_CYCLE_TYPES)}"}

    valid_events = VALID_EVENT_TYPES.get(cycle_type, VALID_EVENT_TYPES["custom"])
    if event_type not in valid_events:
        return {"error": f"不支持的事件类型: {event_type}，{cycle_type} 支持: {', '.join(valid_events)}"}

    rid = health_db.generate_id()
    now = health_db.now_iso()

    with health_db.transaction() as conn:
        conn.execute(
            """INSERT INTO cycle_records (id, member_id, cycle_type, event_type,
               event_date, details, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (rid, member_id, cycle_type, event_type, event_date, details, now)
        )
        conn.commit()

    return {
        "id": rid,
        "member_id": member_id,
        "cycle_type": cycle_type,
        "event_type": event_type,
        "event_date": event_date,
        "message": f"已记录 {cycle_type} {event_type} ({event_date})",
    }


def get_history(member_id: str, cycle_type: str, limit: int = 12) -> dict:
    """Get cycle event history."""
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        rows = health_db.rows_to_list(conn.execute(
            """SELECT * FROM cycle_records
               WHERE member_id=? AND cycle_type=? AND is_deleted=0
               ORDER BY event_date DESC LIMIT ?""",
            (member_id, cycle_type, limit)
        ).fetchall())

        # Parse details JSON
        for row in rows:
            if row.get("details"):
                try:
                    row["details"] = json.loads(row["details"])
                except (json.JSONDecodeError, TypeError):
                    pass

        return {"records": rows, "count": len(rows), "cycle_type": cycle_type}
    finally:
        conn.close()


def _get_cycle_starts(conn, member_id: str, cycle_type: str, limit: int = 12) -> list[str]:
    """Get start event dates for a cycle type, sorted ascending."""
    start_event = {
        "menstrual": "period_start",
        "migraine": "attack_start",
        "allergy": "flare_start",
        "custom": "event_start",
    }.get(cycle_type, "event_start")

    rows = conn.execute(
        """SELECT event_date FROM cycle_records
           WHERE member_id=? AND cycle_type=? AND event_type=? AND is_deleted=0
           ORDER BY event_date DESC LIMIT ?""",
        (member_id, cycle_type, start_event, limit)
    ).fetchall()

    return sorted([r["event_date"] for r in rows])


def predict_next_cycle(member_id: str, cycle_type: str) -> dict:
    """Predict the next cycle using weighted rolling average.

    Uses up to the last 6 cycles, with more recent cycles weighted higher.
    Weights: [1, 1, 2, 2, 3, 3] (most recent = weight 3)
    """
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        starts = _get_cycle_starts(conn, member_id, cycle_type, limit=7)

        if len(starts) < 2:
            default_len = DEFAULT_CYCLE_LENGTHS.get(cycle_type, 28)
            if len(starts) == 1:
                last_start = datetime.strptime(starts[0], "%Y-%m-%d")
                predicted_start = last_start + timedelta(days=default_len)
                return {
                    "predicted_start": predicted_start.strftime("%Y-%m-%d"),
                    "avg_cycle_length": default_len,
                    "confidence": 0.3,
                    "based_on_cycles": 1,
                    "days_until_next": (predicted_start - datetime.now()).days,
                    "note": f"仅有1次记录，使用默认周期长度 {default_len} 天预测",
                }
            return {
                "error": "记录不足，至少需要 2 次周期起始记录才能预测",
                "based_on_cycles": 0,
            }

        # Calculate cycle lengths
        cycle_lengths = []
        for i in range(1, len(starts)):
            d1 = datetime.strptime(starts[i - 1], "%Y-%m-%d")
            d2 = datetime.strptime(starts[i], "%Y-%m-%d")
            length = (d2 - d1).days
            if length > 0:
                cycle_lengths.append(length)

        if not cycle_lengths:
            return {"error": "无法计算周期长度"}

        # Take at most 6 cycles for prediction
        recent = cycle_lengths[-6:]

        # Weighted average (more recent = higher weight)
        # Weights: [1, 1, 2, 2, 3, 3] for 6 items
        base_weights = [1, 1, 2, 2, 3, 3]
        weights = base_weights[-len(recent):]
        weighted_sum = sum(l * w for l, w in zip(recent, weights))
        total_weight = sum(weights)
        avg_length = weighted_sum / total_weight

        # Confidence based on consistency and sample size
        if len(recent) >= 4:
            std_dev = (sum((l - avg_length) ** 2 for l in recent) / len(recent)) ** 0.5
            cv = std_dev / avg_length if avg_length > 0 else 1
            confidence = max(0.3, min(0.95, 1.0 - cv))
        elif len(recent) >= 2:
            confidence = 0.5
        else:
            confidence = 0.3

        last_start = datetime.strptime(starts[-1], "%Y-%m-%d")
        predicted_start = last_start + timedelta(days=round(avg_length))

        result = {
            "predicted_start": predicted_start.strftime("%Y-%m-%d"),
            "avg_cycle_length": round(avg_length, 1),
            "confidence": round(confidence, 2),
            "based_on_cycles": len(recent),
            "days_until_next": (predicted_start - datetime.now()).days,
            "recent_lengths": recent,
        }

        # Menstrual-specific predictions
        if cycle_type == "menstrual":
            ovulation_day = round(avg_length) - 14
            ovulation_date = last_start + timedelta(days=ovulation_day)
            fertile_start = ovulation_date - timedelta(days=3)
            fertile_end = ovulation_date + timedelta(days=1)
            predicted_end = predicted_start + timedelta(days=5)

            result["ovulation_date"] = ovulation_date.strftime("%Y-%m-%d")
            result["fertile_window"] = {
                "start": fertile_start.strftime("%Y-%m-%d"),
                "end": fertile_end.strftime("%Y-%m-%d"),
            }
            result["predicted_end"] = predicted_end.strftime("%Y-%m-%d")

        # Save prediction
        pred_id = health_db.generate_id()
        now = health_db.now_iso()
        conn.execute(
            """INSERT INTO cycle_predictions (id, member_id, cycle_type, predicted_start,
               predicted_end, confidence, based_on_cycles, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (pred_id, member_id, cycle_type, result["predicted_start"],
             result.get("predicted_end"), confidence, len(recent), now)
        )
        conn.commit()

        return result
    finally:
        conn.close()


def get_status(member_id: str, cycle_type: str) -> dict:
    """Get current cycle status and care tips."""
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        starts = _get_cycle_starts(conn, member_id, cycle_type)

        if not starts:
            return {
                "cycle_type": cycle_type,
                "phase": "unknown",
                "message": "暂无记录，无法判断当前状态",
                "care_tips": [],
            }

        last_start = datetime.strptime(starts[-1], "%Y-%m-%d")
        today = datetime.now()
        days_since_start = (today - last_start).days

        if cycle_type == "menstrual":
            # Check if there's a period_end for the current cycle
            end_row = conn.execute(
                """SELECT event_date FROM cycle_records
                   WHERE member_id=? AND cycle_type='menstrual' AND event_type='period_end'
                   AND event_date >= ? AND is_deleted=0
                   ORDER BY event_date ASC LIMIT 1""",
                (member_id, starts[-1])
            ).fetchone()

            period_ended = end_row is not None

            # Determine phase
            if not period_ended and days_since_start <= 7:
                phase = "menstrual"
                phase_cn = "经期"
            elif days_since_start <= MENSTRUAL_PHASES["follicular"][1]:
                phase = "follicular"
                phase_cn = "卵泡期"
            elif days_since_start <= MENSTRUAL_PHASES["ovulation"][1]:
                phase = "ovulation"
                phase_cn = "排卵期"
            else:
                phase = "luteal"
                phase_cn = "黄体期"

            # Check if premenstrual (within 3 days of predicted next period)
            prediction = predict_next_cycle(member_id, cycle_type)
            days_until_next = prediction.get("days_until_next", 999)
            if 0 < days_until_next <= 3:
                phase = "premenstrual"
                phase_cn = "经前期"

            care_tips = CARE_TIPS.get("menstrual", {}).get(phase, [])

            result = {
                "cycle_type": cycle_type,
                "phase": phase,
                "phase_cn": phase_cn,
                "days_since_last_start": days_since_start,
                "last_period_start": starts[-1],
                "care_tips": care_tips,
            }

            if prediction and not prediction.get("error"):
                result["next_predicted_start"] = prediction.get("predicted_start")
                result["days_until_next"] = prediction.get("days_until_next")
                result["avg_cycle_length"] = prediction.get("avg_cycle_length")

            return result

        else:
            # Generic cycle type (migraine, allergy, custom)
            # Calculate average interval
            prediction = predict_next_cycle(member_id, cycle_type)
            days_until_next = prediction.get("days_until_next", 999)

            care_tips = []
            if 0 < days_until_next <= 7:
                care_tips = CARE_TIPS.get(cycle_type, {}).get("warning", [])

            return {
                "cycle_type": cycle_type,
                "phase": "warning" if 0 < days_until_next <= 7 else "normal",
                "days_since_last_event": days_since_start,
                "last_event_date": starts[-1],
                "next_predicted": prediction.get("predicted_start") if not prediction.get("error") else None,
                "days_until_next": days_until_next if not prediction.get("error") else None,
                "care_tips": care_tips,
            }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="周期追踪 — 经期/偏头痛/过敏等周期性事件")
    sub = parser.add_subparsers(dest="command", required=True)

    p_rec = sub.add_parser("record", help="记录周期事件")
    p_rec.add_argument("--member-id", required=True)
    p_rec.add_argument("--owner-id", default=None)
    p_rec.add_argument("--cycle-type", required=True, choices=VALID_CYCLE_TYPES)
    p_rec.add_argument("--event-type", required=True)
    p_rec.add_argument("--date", required=True, help="事件日期 YYYY-MM-DD")
    p_rec.add_argument("--details", default=None, help="详细信息 JSON")

    p_hist = sub.add_parser("history", help="查看周期历史")
    p_hist.add_argument("--member-id", required=True)
    p_hist.add_argument("--owner-id", default=None)
    p_hist.add_argument("--cycle-type", required=True, choices=VALID_CYCLE_TYPES)
    p_hist.add_argument("--limit", type=int, default=12)

    p_pred = sub.add_parser("predict", help="预测下次周期")
    p_pred.add_argument("--member-id", required=True)
    p_pred.add_argument("--owner-id", default=None)
    p_pred.add_argument("--cycle-type", required=True, choices=VALID_CYCLE_TYPES)

    p_stat = sub.add_parser("status", help="查看当前周期状态")
    p_stat.add_argument("--member-id", required=True)
    p_stat.add_argument("--owner-id", default=None)
    p_stat.add_argument("--cycle-type", required=True, choices=VALID_CYCLE_TYPES)

    args = parser.parse_args()
    health_db.ensure_db()

    conn = health_db.get_connection()
    try:
        if not health_db.verify_member_ownership(conn, args.member_id, getattr(args, "owner_id", None)):
            health_db.output_json({"error": f"无权访问成员: {args.member_id}"})
            return
    finally:
        conn.close()

    if args.command == "record":
        result = record_event(args.member_id, args.cycle_type, args.event_type,
                              args.date, args.details)
        health_db.output_json(result)

    elif args.command == "history":
        result = get_history(args.member_id, args.cycle_type, args.limit)
        health_db.output_json(result)

    elif args.command == "predict":
        result = predict_next_cycle(args.member_id, args.cycle_type)
        health_db.output_json(result)

    elif args.command == "status":
        result = get_status(args.member_id, args.cycle_type)
        health_db.output_json(result)


if __name__ == "__main__":
    main()
