"""Health Advisor - proactive health analysis and recommendations.

Analyzes existing health data to generate actionable advice:
- Medication adherence monitoring
- Metric anomaly detection (blood pressure, blood sugar, etc.)
- Overdue checkup alerts
- Measurement gap detection
- Daily health briefings
"""
from __future__ import annotations

import sys
import json
import copy
from datetime import datetime, timedelta

import health_db
import reminder as reminder_mod
from metric_utils import parse_metric_value, calculate_age as _calculate_age_shared


# --- Metric normal ranges ---

METRIC_RANGES = {
    "blood_pressure": {
        "systolic": {"low": 90, "high": 140, "unit": "mmHg"},
        "diastolic": {"low": 60, "high": 90, "unit": "mmHg"},
    },
    "blood_sugar": {
        "fasting": {"low": 3.9, "high": 6.1, "unit": "mmol/L"},
        "postprandial": {"low": 3.9, "high": 7.8, "unit": "mmol/L"},
        "value": {"low": 3.9, "high": 7.8, "unit": "mmol/L"},
    },
    "heart_rate": {"value": {"low": 60, "high": 100, "unit": "bpm"}},
    "temperature": {"value": {"low": 36.0, "high": 37.3, "unit": "°C"}},
    "blood_oxygen": {"value": {"low": 95, "high": 100, "unit": "%"}},
}

# Age-based adjustments to default ranges
_AGE_ADJUSTMENTS = {
    "elderly": {  # >= 65
        "blood_pressure": {"systolic": {"high": 150}, "diastolic": {"high": 90}},
        "heart_rate": {"value": {"low": 55}},
    },
    "child": {  # < 14
        "blood_pressure": {"systolic": {"low": 80, "high": 120}, "diastolic": {"low": 50, "high": 80}},
        "heart_rate": {"value": {"low": 70, "high": 120}},
    },
}

# How often each metric should ideally be measured (days)
METRIC_MEASURE_INTERVALS = {
    "blood_pressure": 3,
    "blood_sugar": 7,
    "heart_rate": 7,
    "weight": 14,
    "temperature": 7,
    "blood_oxygen": 7,
}

# Checkup intervals by diagnosis keywords (days)
CHECKUP_INTERVALS = {
    "高血压": {"interval": 90, "aliases": ["高血压", "血压高", "血压偏高", "hypertension", "hbp", "高血压病"]},
    "糖尿病": {"interval": 90, "aliases": ["糖尿病", "血糖高", "血糖偏高", "diabetes", "dm", "2型糖尿病", "1型糖尿病"]},
    "高血脂": {"interval": 180, "aliases": ["高血脂", "血脂高", "血脂异常", "高脂血症", "hyperlipidemia", "dyslipidemia"]},
    "冠心病": {"interval": 90, "aliases": ["冠心病", "冠状动脉", "冠脉", "coronary", "chd", "冠状动脉粥样硬化"]},
    "哮喘": {"interval": 180, "aliases": ["哮喘", "支气管哮喘", "asthma"]},
    "甲状腺": {"interval": 180, "aliases": ["甲状腺", "甲亢", "甲减", "甲状腺结节", "thyroid"]},
    "肿瘤": {"interval": 90, "aliases": ["肿瘤", "tumor", "tumour", "neoplasm"]},
    "癌": {"interval": 90, "aliases": ["癌", "cancer", "carcinoma", "恶性肿瘤"]},
}


def _parse_metric_value(value_str: str) -> dict:
    """Parse metric value from JSON string or plain number."""
    return parse_metric_value(value_str)


def _calculate_age(birth_date_str: str) -> int | None:
    """Calculate age from birth date string (YYYY-MM-DD)."""
    return _calculate_age_shared(birth_date_str)


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base (non-destructive)."""
    result = copy.deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = copy.deepcopy(v)
    return result


def get_metric_ranges(member_id: str) -> dict:
    """Get metric ranges for a member, merging defaults + age adjustments + custom overrides."""
    ranges = copy.deepcopy(METRIC_RANGES)

    conn = health_db.get_connection()
    try:
        row = conn.execute(
            "SELECT birth_date, custom_metric_ranges FROM members WHERE id=? AND is_deleted=0",
            (member_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return ranges

    # Age-based adjustments
    age = _calculate_age(row["birth_date"])
    if age is not None:
        if age >= 65:
            ranges = _deep_merge(ranges, _AGE_ADJUSTMENTS["elderly"])
        elif age < 14:
            ranges = _deep_merge(ranges, _AGE_ADJUSTMENTS["child"])

    # Custom overrides from member record
    custom = row["custom_metric_ranges"]
    if custom:
        try:
            custom_ranges = json.loads(custom)
            if isinstance(custom_ranges, dict):
                ranges = _deep_merge(ranges, custom_ranges)
        except (json.JSONDecodeError, TypeError):
            pass

    return ranges


def check_metric_anomalies(member_id: str) -> list[dict]:
    """Check recent metrics for values outside normal ranges."""
    conn = health_db.get_connection()
    try:
        alerts = []
        member_ranges = get_metric_ranges(member_id)
        for metric_type, ranges in member_ranges.items():
            rows = health_db.rows_to_list(conn.execute(
                """SELECT * FROM health_metrics
                   WHERE member_id=? AND metric_type=? AND is_deleted=0
                   ORDER BY measured_at DESC LIMIT 5""",
                (member_id, metric_type)
            ).fetchall())
            if not rows:
                continue

            abnormal_count = 0
            latest = rows[0]
            values = _parse_metric_value(latest["value"])

            for key, bounds in ranges.items():
                val = values.get(key)
                if val is None:
                    continue
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    continue

                if val > bounds["high"]:
                    abnormal_count += 1
                    alerts.append({
                        "type": "metric_anomaly",
                        "severity": "alert" if val > bounds["high"] * 1.15 else "warning",
                        "member_id": member_id,
                        "title": f"{metric_type} 偏高",
                        "detail": f"{key}: {val} {bounds['unit']}（正常范围 {bounds['low']}-{bounds['high']}）",
                        "suggestion": f"建议关注 {metric_type}，如持续偏高请就医",
                        "measured_at": latest["measured_at"],
                    })
                elif val < bounds["low"]:
                    abnormal_count += 1
                    alerts.append({
                        "type": "metric_anomaly",
                        "severity": "alert" if val < bounds["low"] * 0.85 else "warning",
                        "member_id": member_id,
                        "title": f"{metric_type} 偏低",
                        "detail": f"{key}: {val} {bounds['unit']}（正常范围 {bounds['low']}-{bounds['high']}）",
                        "suggestion": f"建议关注 {metric_type}，如持续偏低请就医",
                        "measured_at": latest["measured_at"],
                    })

            # Check trend: if last 3+ readings are all abnormal
            if len(rows) >= 3 and abnormal_count > 0:
                trend_abnormal = 0
                for row in rows[:3]:
                    rv = _parse_metric_value(row["value"])
                    for key, bounds in ranges.items():
                        v = rv.get(key)
                        if v is not None:
                            try:
                                v = float(v)
                                if v > bounds["high"] or v < bounds["low"]:
                                    trend_abnormal += 1
                                    break
                            except (TypeError, ValueError):
                                pass
                if trend_abnormal >= 3:
                    alerts.append({
                        "type": "metric_trend",
                        "severity": "alert",
                        "member_id": member_id,
                        "title": f"{metric_type} 持续异常",
                        "detail": f"最近 {len(rows[:3])} 次测量均不在正常范围内",
                        "suggestion": "建议尽快就医复查",
                    })
        return alerts
    finally:
        conn.close()


def check_metric_gaps(member_id: str) -> list[dict]:
    """Check if any metric types haven't been measured recently enough."""
    conn = health_db.get_connection()
    now = datetime.now()
    gaps = []
    try:
        for metric_type, interval_days in METRIC_MEASURE_INTERVALS.items():
            row = conn.execute(
                """SELECT measured_at FROM health_metrics
                   WHERE member_id=? AND metric_type=? AND is_deleted=0
                   ORDER BY measured_at DESC LIMIT 1""",
                (member_id, metric_type)
            ).fetchone()

            if row is None:
                # Never measured — only flag if member has any health data at all
                has_data = conn.execute(
                    "SELECT 1 FROM health_metrics WHERE member_id=? AND is_deleted=0 LIMIT 1",
                    (member_id,)
                ).fetchone()
                if has_data:
                    gaps.append({
                        "type": "metric_gap",
                        "severity": "info",
                        "member_id": member_id,
                        "title": f"从未记录 {metric_type}",
                        "detail": f"建议定期测量 {metric_type}",
                        "suggestion": f"建议每 {interval_days} 天测量一次",
                    })
            else:
                last_date = datetime.strptime(row["measured_at"][:10], "%Y-%m-%d")
                days_since = (now - last_date).days
                if days_since > interval_days:
                    gaps.append({
                        "type": "metric_gap",
                        "severity": "warning" if days_since > interval_days * 2 else "info",
                        "member_id": member_id,
                        "title": f"{metric_type} 已 {days_since} 天未测量",
                        "detail": f"上次测量: {row['measured_at'][:10]}，建议间隔 {interval_days} 天",
                        "suggestion": f"请尽快测量 {metric_type}",
                    })
        return gaps
    finally:
        conn.close()


def check_overdue_checkups(member_id: str) -> list[dict]:
    """Check if follow-up visits are overdue based on diagnosis history."""
    conn = health_db.get_connection()
    now = datetime.now()
    alerts = []
    try:
        visits = health_db.rows_to_list(conn.execute(
            """SELECT * FROM visits WHERE member_id=? AND is_deleted=0
               ORDER BY visit_date DESC""",
            (member_id,)
        ).fetchall())

        # Collect diagnoses and their latest visit dates
        diagnosis_dates = {}
        for visit in visits:
            diag = visit.get("diagnosis") or ""
            diag_lower = diag.lower()
            visit_date = visit.get("visit_date", "")[:10]
            for keyword, config in CHECKUP_INTERVALS.items():
                interval = config["interval"]
                matched = any(alias in diag_lower for alias in config["aliases"])
                if matched and keyword not in diagnosis_dates:
                    diagnosis_dates[keyword] = (visit_date, interval, diag)

        for keyword, (last_date_str, interval, full_diag) in diagnosis_dates.items():
            try:
                last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
            except ValueError:
                continue
            days_since = (now - last_date).days
            if days_since > interval:
                alerts.append({
                    "type": "overdue_checkup",
                    "severity": "warning" if days_since > interval * 1.5 else "info",
                    "member_id": member_id,
                    "title": f"{keyword} 复查逾期",
                    "detail": f"上次就诊: {last_date_str}（{days_since} 天前），建议每 {interval} 天复查",
                    "suggestion": f"建议预约 {keyword} 相关复查",
                    "diagnosis": full_diag,
                })
        return alerts
    finally:
        conn.close()


def check_medication_adherence(member_id: str) -> list[dict]:
    """Check medication adherence by looking at reminder trigger logs.

    If a medication reminder has been missed (no trigger log in expected window),
    flag it.
    """
    conn = health_db.get_connection()
    now = datetime.now()
    alerts = []
    try:
        # Get active medication reminders
        reminders = health_db.rows_to_list(conn.execute(
            """SELECT * FROM reminders
               WHERE member_id=? AND type='medication' AND is_active=1 AND is_deleted=0""",
            (member_id,)
        ).fetchall())

        for rem in reminders:
            # Check last 7 days of logs
            week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            logs = conn.execute(
                """SELECT COUNT(*) as cnt FROM reminder_logs
                   WHERE reminder_id=? AND triggered_at >= ?""",
                (rem["id"], week_ago)
            ).fetchone()

            expected = 7  # daily reminders should have ~7 logs per week
            if rem.get("schedule_type") == "weekly":
                expected = 1
            elif rem.get("schedule_type") == "monthly":
                expected = 0  # too early to judge

            actual = logs["cnt"] if logs else 0
            if expected > 0 and actual < expected * 0.5:
                alerts.append({
                    "type": "medication_adherence",
                    "severity": "warning",
                    "member_id": member_id,
                    "title": f"用药提醒响应不足：{rem['title']}",
                    "detail": f"过去 7 天预期 {expected} 次提醒，实际触发 {actual} 次",
                    "suggestion": "请注意按时服药，如有疑问请咨询医生",
                })
        return alerts
    finally:
        conn.close()


def check_cycle_alerts(member_id: str) -> list[dict]:
    """Check for cycle-related alerts (menstrual, migraine, allergy)."""
    alerts = []
    try:
        import cycle_tracker
    except ImportError:
        return alerts

    conn = health_db.get_connection()
    try:
        # Check all cycle types that have records for this member
        cycle_types = conn.execute(
            """SELECT DISTINCT cycle_type FROM cycle_records
               WHERE member_id=? AND is_deleted=0""",
            (member_id,)
        ).fetchall()
    finally:
        conn.close()

    for row in cycle_types:
        cycle_type = row["cycle_type"]
        try:
            status = cycle_tracker.get_status(member_id, cycle_type)
        except Exception:
            continue

        if cycle_type == "menstrual":
            days_until = status.get("days_until_next")
            phase = status.get("phase", "")

            if days_until is not None and 0 < days_until <= 3:
                alerts.append({
                    "type": "cycle_alert",
                    "severity": "info",
                    "member_id": member_id,
                    "title": f"经期将至（{days_until}天后）",
                    "detail": f"预计 {status.get('next_predicted_start', '未知')} 来经，请提前准备",
                    "suggestion": "注意保暖和休息，准备好必需用品",
                    "care_tips": status.get("care_tips", []),
                })
            elif phase == "menstrual":
                alerts.append({
                    "type": "cycle_alert",
                    "severity": "info",
                    "member_id": member_id,
                    "title": "当前处于经期",
                    "detail": f"经期第 {status.get('days_since_last_start', '?')} 天",
                    "suggestion": "注意保暖，适当休息，避免剧烈运动",
                    "care_tips": status.get("care_tips", []),
                })

        elif cycle_type == "migraine":
            days_until = status.get("days_until_next")
            if days_until is not None and 0 < days_until <= 7:
                alerts.append({
                    "type": "cycle_alert",
                    "severity": "info",
                    "member_id": member_id,
                    "title": f"偏头痛发作预警（约{days_until}天后）",
                    "detail": "根据历史规律，偏头痛可能即将发作",
                    "suggestion": "避免已知诱因，保持规律作息",
                    "care_tips": status.get("care_tips", []),
                })

        elif cycle_type == "allergy":
            days_until = status.get("days_until_next")
            if days_until is not None and 0 < days_until <= 7:
                alerts.append({
                    "type": "cycle_alert",
                    "severity": "info",
                    "member_id": member_id,
                    "title": f"过敏发作预警（约{days_until}天后）",
                    "detail": "根据历史规律，过敏症状可能即将出现",
                    "suggestion": "提前准备抗过敏药物，减少过敏原接触",
                    "care_tips": status.get("care_tips", []),
                })

    return alerts


def generate_health_tips(member_id: str) -> dict:
    """Generate comprehensive health tips for a member by running all checks."""
    health_db.ensure_db()

    conn = health_db.get_connection()
    try:
        member = health_db.row_to_dict(conn.execute(
            "SELECT id, name, relation FROM members WHERE id=? AND is_deleted=0",
            (member_id,)
        ).fetchone())
    finally:
        conn.close()

    if not member:
        return {"error": f"未找到成员: {member_id}"}

    tips = []
    tips.extend(check_metric_anomalies(member_id))
    tips.extend(check_metric_gaps(member_id))
    tips.extend(check_overdue_checkups(member_id))
    tips.extend(check_medication_adherence(member_id))
    tips.extend(check_cycle_alerts(member_id))

    # Attach member name to all tips
    for tip in tips:
        tip["member_name"] = member.get("name", "")

    # Sort by severity
    severity_order = {"alert": 0, "warning": 1, "info": 2}
    tips.sort(key=lambda t: severity_order.get(t.get("severity", "info"), 9))

    return {
        "member_id": member_id,
        "member_name": member.get("name", ""),
        "tips": tips,
        "alert_count": sum(1 for t in tips if t["severity"] == "alert"),
        "warning_count": sum(1 for t in tips if t["severity"] == "warning"),
        "info_count": sum(1 for t in tips if t["severity"] == "info"),
    }


def get_daily_briefing(member_id: str = None, owner_id: str = None) -> dict:
    """Generate a daily health briefing with due reminders + health tips.

    If member_id is None, generates briefing for all family members.
    If owner_id is provided (and member_id is None), only includes that owner's members.
    """
    health_db.ensure_db()
    conn = health_db.get_connection()

    try:
        if member_id:
            if not health_db.verify_member_ownership(conn, member_id, owner_id):
                return {"briefing": [], "has_items": False, "error": f"无权访问成员: {member_id}"}
            members = health_db.rows_to_list(conn.execute(
                "SELECT id, name, relation FROM members WHERE id=? AND is_deleted=0",
                (member_id,)
            ).fetchall())
        elif owner_id:
            members = health_db.rows_to_list(conn.execute(
                "SELECT id, name, relation FROM members WHERE is_deleted=0 AND owner_id=? ORDER BY created_at",
                (owner_id,)
            ).fetchall())
        else:
            members = health_db.rows_to_list(conn.execute(
                "SELECT id, name, relation FROM members WHERE is_deleted=0 ORDER BY created_at"
            ).fetchall())
    finally:
        conn.close()

    if not members:
        return {"briefing": [], "has_items": False}

    # Due reminders
    due = reminder_mod.get_due_reminders()

    # Health tips per member
    member_briefings = []
    total_alerts = 0
    total_warnings = 0

    for m in members:
        mid = m["id"]
        tips_result = generate_health_tips(mid)
        member_due = [r for r in due if r.get("member_id") == mid]

        total_alerts += tips_result.get("alert_count", 0)
        total_warnings += tips_result.get("warning_count", 0)

        if tips_result.get("tips") or member_due:
            member_briefings.append({
                "member_id": mid,
                "member_name": m["name"],
                "relation": m["relation"],
                "due_reminders": member_due,
                "health_tips": tips_result.get("tips", []),
            })

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "briefing": member_briefings,
        "has_items": len(member_briefings) > 0,
        "total_alerts": total_alerts,
        "total_warnings": total_warnings,
        "total_due_reminders": len(due),
    }


# --- CLI ---

def main():
    if len(sys.argv) < 2:
        health_db.output_json({"error": "用法: health_advisor.py <command> [args]"})
        return

    health_db.ensure_db()
    cmd = sys.argv[1]

    if cmd == "tips":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id", required=True)
        p.add_argument("--owner-id", default=None)
        args = p.parse_args(sys.argv[2:])
        health_db.output_json(generate_health_tips(args.member_id))

    elif cmd == "briefing":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id")
        p.add_argument("--owner-id", default=None)
        args = p.parse_args(sys.argv[2:])
        health_db.output_json(get_daily_briefing(args.member_id, getattr(args, 'owner_id', None)))

    elif cmd == "check-metrics":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id", required=True)
        p.add_argument("--owner-id", default=None)
        args = p.parse_args(sys.argv[2:])
        health_db.output_json({"anomalies": check_metric_anomalies(args.member_id)})

    elif cmd == "check-gaps":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id", required=True)
        p.add_argument("--owner-id", default=None)
        args = p.parse_args(sys.argv[2:])
        health_db.output_json({"gaps": check_metric_gaps(args.member_id)})

    elif cmd == "check-checkups":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id", required=True)
        p.add_argument("--owner-id", default=None)
        args = p.parse_args(sys.argv[2:])
        health_db.output_json({"overdue": check_overdue_checkups(args.member_id)})

    else:
        health_db.output_json({"error": f"未知命令: {cmd}",
                               "commands": ["tips", "briefing", "check-metrics", "check-gaps", "check-checkups"]})


if __name__ == "__main__":
    main()
