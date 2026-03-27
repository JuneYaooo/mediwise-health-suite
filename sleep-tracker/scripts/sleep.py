"""Sleep tracking and analysis for MediWise.

Reads sleep records from health_metrics (metric_type='sleep').
Supports manual entry, daily summary, weekly trend, and quality scoring.

Sleep value JSON format (shared with wearable-sync):
  {"duration_min": 480, "deep_min": 90, "light_min": 240, "rem_min": 90, "awake_min": 30}
"""

from __future__ import annotations

import sys
import os
import json
import argparse
from datetime import datetime, timedelta, date
from collections import defaultdict

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.path_setup import setup_mediwise_path
setup_mediwise_path()

import health_db


# Sleep quality thresholds (minutes)
_IDEAL_TOTAL_MIN = (420, 540)       # 7–9 hours
_IDEAL_DEEP_RATIO = (0.13, 0.23)    # 13–23% deep sleep
_IDEAL_REM_RATIO = (0.20, 0.25)     # 20–25% REM
_MAX_AWAKE_RATIO = 0.10             # <10% awake


def _parse_sleep_value(raw: str) -> dict | None:
    """Parse sleep JSON value. Returns dict or None on failure."""
    if not raw:
        return None
    try:
        v = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(v, dict):
            return None
        return {
            "duration_min": int(v.get("duration_min") or 0),
            "deep_min":     int(v.get("deep_min") or 0),
            "light_min":    int(v.get("light_min") or 0),
            "rem_min":      int(v.get("rem_min") or 0),
            "awake_min":    int(v.get("awake_min") or 0),
        }
    except (ValueError, TypeError):
        return None


def _quality_score(s: dict) -> dict:
    """Score a sleep record 0-100 and return label + issues."""
    total = s["duration_min"]
    if total == 0:
        return {"score": 0, "label": "无数据", "issues": []}

    score = 100
    issues = []

    # Duration
    lo, hi = _IDEAL_TOTAL_MIN
    if total < lo:
        deficit = lo - total
        score -= min(30, deficit // 10 * 5)
        issues.append(f"睡眠不足（{total // 60}h{total % 60}m，建议 7-9 小时）")
    elif total > hi + 60:  # >10h
        score -= 10
        issues.append(f"睡眠过长（{total // 60}h{total % 60}m）")

    # Deep sleep ratio
    deep_ratio = s["deep_min"] / total
    lo_d, hi_d = _IDEAL_DEEP_RATIO
    if deep_ratio < lo_d:
        score -= 20
        issues.append(f"深睡比例偏低（{deep_ratio:.0%}，建议 13-23%）")

    # REM ratio
    rem_ratio = s["rem_min"] / total if s["rem_min"] > 0 else 0
    if rem_ratio > 0 and rem_ratio < _IDEAL_REM_RATIO[0]:
        score -= 10
        issues.append(f"REM 比例偏低（{rem_ratio:.0%}，建议 20-25%）")

    # Awake ratio
    awake_ratio = s["awake_min"] / total
    if awake_ratio > _MAX_AWAKE_RATIO:
        score -= 15
        issues.append(f"夜间清醒时间过多（{s['awake_min']}min，建议 <10%）")

    score = max(0, score)
    if score >= 85:
        label = "优质"
    elif score >= 70:
        label = "良好"
    elif score >= 55:
        label = "一般"
    else:
        label = "较差"

    return {"score": score, "label": label, "issues": issues}


def _format_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_log(args):
    """Manually log a sleep record."""
    health_db.ensure_db()

    # Parse and validate
    try:
        duration = int(args.duration)
    except (ValueError, TypeError):
        health_db.output_json({"status": "error", "message": "--duration 必须为整数（分钟）"})
        return

    deep = int(args.deep or 0)
    light = int(args.light or 0)
    rem = int(args.rem or 0)
    awake = int(args.awake or 0)

    if deep + light + rem + awake > duration:
        health_db.output_json({"status": "error", "message": "各阶段之和不能超过总时长"})
        return

    # Default light to remainder if not specified
    if light == 0 and deep + rem + awake < duration:
        light = duration - deep - rem - awake

    sleep_value = json.dumps({
        "duration_min": duration,
        "deep_min": deep,
        "light_min": light,
        "rem_min": rem,
        "awake_min": awake,
    }, ensure_ascii=False)

    # measured_at: use provided date or yesterday night
    if args.date:
        measured_at = f"{args.date} 07:00:00"
    else:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        measured_at = f"{yesterday} 07:00:00"

    with health_db.transaction() as conn:
        # Verify member
        m = conn.execute(
            "SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)
        ).fetchone()
        if not m:
            health_db.output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        metric_id = health_db.generate_id()
        conn.execute(
            """INSERT INTO health_metrics
               (id, member_id, metric_type, value, measured_at, source, created_at)
               VALUES (?, ?, 'sleep', ?, ?, 'manual', ?)""",
            (metric_id, args.member_id, sleep_value, measured_at, health_db.now_iso())
        )
        conn.commit()

    parsed = _parse_sleep_value(sleep_value)
    quality = _quality_score(parsed)
    health_db.output_json({
        "status": "ok",
        "message": f"睡眠记录已添加（{_format_duration(duration)}，{quality['label']}）",
        "metric_id": metric_id,
        "sleep": parsed,
        "quality": quality,
    })


def cmd_daily(args):
    """Show sleep summary for a specific date (default: yesterday)."""
    health_db.ensure_db()

    target_date = args.date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    day_start = f"{target_date} 00:00:00"
    # Sleep for a given night may be recorded on the next morning
    day_end_dt = datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=1)
    day_end = day_end_dt.strftime("%Y-%m-%d") + " 14:00:00"

    conn = health_db.get_connection()
    try:
        rows = health_db.rows_to_list(conn.execute(
            """SELECT id, value, measured_at, source FROM health_metrics
               WHERE member_id=? AND metric_type='sleep' AND is_deleted=0
               AND measured_at BETWEEN ? AND ?
               ORDER BY measured_at DESC""",
            (args.member_id, day_start, day_end)
        ).fetchall())
    finally:
        conn.close()

    if not rows:
        health_db.output_json({
            "status": "ok",
            "date": target_date,
            "message": f"{target_date} 没有睡眠记录",
            "records": [],
        })
        return

    records = []
    for row in rows:
        parsed = _parse_sleep_value(row["value"])
        if parsed:
            quality = _quality_score(parsed)
            records.append({
                "metric_id": row["id"],
                "measured_at": row["measured_at"],
                "source": row["source"],
                "sleep": parsed,
                "duration_fmt": _format_duration(parsed["duration_min"]),
                "quality": quality,
            })

    # If multiple sessions, pick the longest as primary
    primary = max(records, key=lambda r: r["sleep"]["duration_min"])

    health_db.output_json({
        "status": "ok",
        "date": target_date,
        "record_count": len(records),
        "primary": primary,
        "all_records": records,
    })


def cmd_weekly(args):
    """Show weekly sleep trend and averages."""
    health_db.ensure_db()

    days = int(args.days or 7)
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days)
    start_str = start_dt.strftime("%Y-%m-%d %H:%M:%S")

    conn = health_db.get_connection()
    try:
        member = conn.execute(
            "SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)
        ).fetchone()
        if not member:
            health_db.output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        rows = health_db.rows_to_list(conn.execute(
            """SELECT value, measured_at FROM health_metrics
               WHERE member_id=? AND metric_type='sleep' AND is_deleted=0
               AND measured_at >= ?
               ORDER BY measured_at ASC""",
            (args.member_id, start_str)
        ).fetchall())
    finally:
        conn.close()

    if not rows:
        health_db.output_json({
            "status": "ok",
            "member_name": member["name"],
            "days": days,
            "message": f"近 {days} 天没有睡眠记录",
            "daily": [],
        })
        return

    # Group by date, pick longest session per day
    by_day = defaultdict(list)
    for row in rows:
        day = row["measured_at"][:10]
        parsed = _parse_sleep_value(row["value"])
        if parsed and parsed["duration_min"] >= 30:
            by_day[day].append(parsed)

    daily = []
    total_duration = 0
    total_deep = 0
    total_rem = 0
    total_awake = 0
    scores = []

    for day in sorted(by_day.keys()):
        sessions = by_day[day]
        # Pick longest session as the day's main sleep
        s = max(sessions, key=lambda x: x["duration_min"])
        quality = _quality_score(s)
        total_duration += s["duration_min"]
        total_deep += s["deep_min"]
        total_rem += s["rem_min"]
        total_awake += s["awake_min"]
        scores.append(quality["score"])
        daily.append({
            "date": day,
            "duration_min": s["duration_min"],
            "duration_fmt": _format_duration(s["duration_min"]),
            "deep_min": s["deep_min"],
            "rem_min": s["rem_min"],
            "awake_min": s["awake_min"],
            "quality_score": quality["score"],
            "quality_label": quality["label"],
        })

    n = len(daily)
    avg_duration = total_duration // n if n else 0
    avg_score = sum(scores) // n if n else 0

    # Trend: compare first half vs second half
    trend = "stable"
    if n >= 4:
        mid = n // 2
        first_avg = sum(d["duration_min"] for d in daily[:mid]) / mid
        second_avg = sum(d["duration_min"] for d in daily[mid:]) / (n - mid)
        if second_avg > first_avg + 20:
            trend = "improving"
        elif second_avg < first_avg - 20:
            trend = "declining"

    trend_cn = {"stable": "稳定", "improving": "改善", "declining": "下降"}.get(trend, trend)

    health_db.output_json({
        "status": "ok",
        "member_name": member["name"],
        "days": days,
        "record_days": n,
        "avg_duration_min": avg_duration,
        "avg_duration_fmt": _format_duration(avg_duration),
        "avg_quality_score": avg_score,
        "trend": trend,
        "trend_cn": trend_cn,
        "daily": daily,
    })


def cmd_list(args):
    """List recent sleep records."""
    health_db.ensure_db()
    limit = int(args.limit or 14)

    conn = health_db.get_connection()
    try:
        rows = health_db.rows_to_list(conn.execute(
            """SELECT id, value, measured_at, source FROM health_metrics
               WHERE member_id=? AND metric_type='sleep' AND is_deleted=0
               ORDER BY measured_at DESC LIMIT ?""",
            (args.member_id, limit)
        ).fetchall())
    finally:
        conn.close()

    records = []
    for row in rows:
        parsed = _parse_sleep_value(row["value"])
        if parsed:
            quality = _quality_score(parsed)
            records.append({
                "metric_id": row["id"],
                "measured_at": row["measured_at"],
                "source": row["source"],
                "duration_fmt": _format_duration(parsed["duration_min"]),
                "duration_min": parsed["duration_min"],
                "deep_min": parsed["deep_min"],
                "rem_min": parsed["rem_min"],
                "awake_min": parsed["awake_min"],
                "quality_score": quality["score"],
                "quality_label": quality["label"],
            })

    health_db.output_json({
        "status": "ok",
        "count": len(records),
        "records": records,
    })


def main():
    parser = argparse.ArgumentParser(description="睡眠追踪")
    sub = parser.add_subparsers(dest="command", required=True)

    p_log = sub.add_parser("log", help="手动录入睡眠记录")
    p_log.add_argument("--member-id", required=True)
    p_log.add_argument("--duration", required=True, help="总时长（分钟）")
    p_log.add_argument("--deep", default="0", help="深睡时长（分钟）")
    p_log.add_argument("--light", default="0", help="浅睡时长（分钟）")
    p_log.add_argument("--rem", default="0", help="REM 时长（分钟）")
    p_log.add_argument("--awake", default="0", help="清醒时长（分钟）")
    p_log.add_argument("--date", default=None, help="日期 YYYY-MM-DD（默认昨天）")

    p_daily = sub.add_parser("daily", help="查看某天睡眠")
    p_daily.add_argument("--member-id", required=True)
    p_daily.add_argument("--date", default=None, help="日期 YYYY-MM-DD（默认昨天）")

    p_weekly = sub.add_parser("weekly", help="每周睡眠趋势")
    p_weekly.add_argument("--member-id", required=True)
    p_weekly.add_argument("--days", default="7", help="分析天数（默认7）")

    p_list = sub.add_parser("list", help="查看历史睡眠记录")
    p_list.add_argument("--member-id", required=True)
    p_list.add_argument("--limit", default="14", help="条数限制（默认14）")

    args = parser.parse_args()
    commands = {
        "log": cmd_log,
        "daily": cmd_daily,
        "weekly": cmd_weekly,
        "list": cmd_list,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
