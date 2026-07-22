"""Generate local, self-contained personal and family health record cards.

The renderer uses only local data and inline CSS/SVG. It deliberately reports
recorded intake and recorded activity separately: without a complete energy
expenditure model, it must not imply a calorie deficit or clinical fluid I/O.

Usage:
  python3 scripts/briefing_report.py generate [--member-id <id>]
      [--days 7] [--locale zh-CN|en-US] [--view auto|personal|family]
      [--focus auto|metrics|lifestyle|care|medications]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta

import health_advisor
import health_db
from config import DATA_DIR


LOG = logging.getLogger(__name__)

COPY = {
    "zh-CN": {
        "lang": "zh-CN", "title": "健康记录卡片", "family_title": "家庭健康记录卡片",
        "last_days": "最近 {days} 天", "period": "{start} 至 {end}",
        "local_profile": "个人本地档案", "local_family": "本地家庭档案",
        "members": "{count} 位成员", "attention_people": "{count} 人需要关注",
        "pending": "{count} 项待办", "attention": "需要关注", "all_clear": "未发现告警或待办提醒",
        "alerts": "{count} 项警告", "warnings": "{count} 项提醒", "todos": "{count} 项待处理提醒",
        "metrics": "核心健康指标", "records": "{count} 条", "latest": "最近",
        "source": "来源", "not_enough": "记录不足，暂不判断趋势", "flat": "与期初持平",
        "change": "较期初 {value}", "no_metrics": "所选时间范围内暂无可展示的健康指标。",
        "intake_activity": "摄入与消耗", "recorded_intake": "记录摄入",
        "recorded_days": "{count} 个饮食记录日", "daily_average": "日均（按记录日）",
        "protein": "蛋白质", "carbs": "碳水", "fat": "脂肪", "fiber": "膳食纤维",
        "activity": "运动记录", "sessions": "{count} 次", "duration": "运动时长",
        "activity_burn": "运动消耗", "steps": "日均步数", "step_days": "{count} 个步数记录日",
        "no_diet": "暂无饮食记录", "no_activity": "暂无运动记录", "no_steps": "暂无步数记录",
        "not_balance": "摄入与运动消耗均为已记录数据，不代表完整能量收支。",
        "sleep": "睡眠", "sleep_nights": "{count} 个睡眠记录夜", "avg_sleep": "平均睡眠",
        "avg_score": "平均评分", "latest_deep": "最近深睡", "latest_rem": "最近 REM",
        "no_sleep": "暂无睡眠记录", "hours": "小时", "minutes": "分钟",
        "recent_care": "最近医疗记录", "visits": "最近就医", "labs": "最近检验",
        "imaging": "最近检查", "no_visits": "所选时间范围内暂无就医记录",
        "no_labs": "所选时间范围内暂无检验记录", "no_imaging": "所选时间范围内暂无检查记录",
        "abnormal": "{count} 项明确异常", "no_flagged": "无明确异常标记", "diagnosis": "诊断",
        "conclusion": "结论", "active_meds": "当前在用药", "medicine": "药品名称",
        "dosage": "剂量", "frequency": "频次", "purpose": "用途", "start_date": "开始日期",
        "no_meds": "暂无在用药记录", "family_overview": "成员状态、用药与提醒",
        "stable": "当前无明确提醒", "needs_attention": "需要关注",
        "data_present": "近期有状态记录", "data_missing": "近期状态记录较少",
        "current_status": "当前状态", "current_meds": "当前用药", "reminders_attention": "提醒与注意",
        "no_family_meds": "暂无在用药", "no_family_attention": "暂无待处理提醒或明确注意事项",
        "attention_count": "{count} 项需要注意", "daily_at": "每天 {times}", "next_at": "下次 {time}",
        "more_meds": "另有 {count} 种在用药", "more_attention": "另有 {count} 项提醒或注意事项",
        "due_prefix": "待处理", "upcoming_prefix": "计划提醒",
        "health_timeline": "个人健康时间轴",
        "no_health_timeline": "所选时间范围内暂无可展示的健康动态。", "metric_event": "指标",
        "food_event": "饮食", "activity_event": "运动", "sleep_event": "睡眠", "health_metric_update": "健康指标更新",
        "food_log": "饮食记录", "sleep_log": "睡眠记录", "sleep_score": "评分 {score}",
        "generated": "生成时间：{time}",
        "disclaimer": "本卡片只记录、展示和提醒，不提供诊断、治疗、用药或其他医疗指导；如需医学判断，请咨询专业医疗人员。",
        "self": "本人", "visit_event": "就医", "lab_event": "检验", "imaging_event": "检查",
        "unknown": "未填写", "day": "天",
    },
    "en-US": {
        "lang": "en", "title": "Health Record Card", "family_title": "Family Health Record Card",
        "last_days": "Last {days} days", "period": "{start} to {end}",
        "local_profile": "Private local profile", "local_family": "Private local family record",
        "members": "{count} members", "attention_people": "{count} need attention",
        "pending": "{count} pending", "attention": "Needs attention", "all_clear": "No alerts or pending reminders found",
        "alerts": "{count} alerts", "warnings": "{count} notices", "todos": "{count} pending reminders",
        "metrics": "Key health metrics", "records": "{count} records", "latest": "Latest",
        "source": "Source", "not_enough": "Not enough records to show a trend", "flat": "No change from first record",
        "change": "{value} from first record", "no_metrics": "No supported health metrics were recorded in this period.",
        "intake_activity": "Intake and activity", "recorded_intake": "Recorded intake",
        "recorded_days": "{count} food log days", "daily_average": "Daily average on logged days",
        "protein": "Protein", "carbs": "Carbohydrate", "fat": "Fat", "fiber": "Fiber",
        "activity": "Recorded activity", "sessions": "{count} sessions", "duration": "Active time",
        "activity_burn": "Activity burn", "steps": "Average daily steps", "step_days": "{count} step log days",
        "no_diet": "No food logs", "no_activity": "No activity logs", "no_steps": "No step logs",
        "not_balance": "Intake and activity burn are recorded values, not a complete energy balance.",
        "sleep": "Sleep", "sleep_nights": "{count} sleep records", "avg_sleep": "Average sleep",
        "avg_score": "Average score", "latest_deep": "Latest deep sleep", "latest_rem": "Latest REM",
        "no_sleep": "No sleep records", "hours": "hr", "minutes": "min",
        "recent_care": "Recent care", "visits": "Recent visits", "labs": "Recent lab results",
        "imaging": "Recent imaging and exams", "no_visits": "No visits recorded in this period",
        "no_labs": "No lab results recorded in this period", "no_imaging": "No imaging or exams recorded in this period",
        "abnormal": "{count} explicitly flagged", "no_flagged": "No explicit abnormal flags", "diagnosis": "Diagnosis",
        "conclusion": "Conclusion", "active_meds": "Active medications", "medicine": "Medication",
        "dosage": "Dose", "frequency": "Frequency", "purpose": "Purpose", "start_date": "Start date",
        "no_meds": "No active medications recorded", "family_overview": "Member status, medications, and reminders",
        "stable": "No explicit alerts", "needs_attention": "Needs attention",
        "data_present": "Recent status records available", "data_missing": "Limited recent status data",
        "current_status": "Current status", "current_meds": "Current medications", "reminders_attention": "Reminders and attention",
        "no_family_meds": "No active medications", "no_family_attention": "No due reminders or explicit attention items",
        "attention_count": "{count} items need attention", "daily_at": "Daily at {times}", "next_at": "Next {time}",
        "more_meds": "{count} more active medications", "more_attention": "{count} more reminders or attention items",
        "due_prefix": "Due", "upcoming_prefix": "Planned",
        "health_timeline": "Personal health timeline",
        "no_health_timeline": "No health events are available for this period.", "metric_event": "Metrics",
        "food_event": "Food", "activity_event": "Activity", "sleep_event": "Sleep", "health_metric_update": "Health metrics updated",
        "food_log": "Food log", "sleep_log": "Sleep record", "sleep_score": "Score {score}",
        "generated": "Generated {time}",
        "disclaimer": "This card only records, displays, and reminds. It provides no diagnosis, treatment, medication, or other medical guidance. Consult a qualified professional for medical judgment.",
        "self": "self", "visit_event": "Visit", "lab_event": "Lab", "imaging_event": "Imaging",
        "unknown": "Not recorded", "day": "days",
    },
}

METRIC_NAMES = {
    "zh-CN": {"blood_pressure": "血压", "blood_sugar": "血糖", "heart_rate": "心率", "weight": "体重", "temperature": "体温", "blood_oxygen": "血氧"},
    "en-US": {"blood_pressure": "Blood pressure", "blood_sugar": "Blood glucose", "heart_rate": "Heart rate", "weight": "Weight", "temperature": "Temperature", "blood_oxygen": "Blood oxygen"},
}
METRIC_UNITS = {"blood_pressure": "mmHg", "blood_sugar": "mmol/L", "heart_rate": "bpm", "weight": "kg", "temperature": "°C", "blood_oxygen": "%"}
SOURCES = {
    "zh-CN": {"manual": "手动记录", "手动记录": "手动记录", "apple_health": "Apple Health", "gadgetbridge": "Gadgetbridge", "garmin": "Garmin Connect"},
    "en-US": {"manual": "Manual", "手动记录": "Manual", "apple_health": "Apple Health", "gadgetbridge": "Gadgetbridge", "garmin": "Garmin Connect"},
}
RELATIONS_EN = {"本人": "self", "父亲": "father", "母亲": "mother", "配偶": "partner", "丈夫": "husband", "妻子": "wife", "儿子": "son", "女儿": "daughter", "子女": "child", "祖父": "grandfather", "祖母": "grandmother"}
ABNORMAL_WORDS = {"high", "low", "abnormal", "critical", "h", "l", "a", "hh", "ll"}
FOCUS_CHOICES = ("auto", "metrics", "lifestyle", "care", "medications")


def _escape(value) -> str:
    if value is None:
        return ""
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#x27;"))


def _fmt_number(value, digits=0) -> str:
    if value is None:
        return "—"
    try:
        number = float(value)
        return f"{number:.{digits}f}" if digits else f"{number:,.0f}"
    except (TypeError, ValueError):
        return str(value)


def _count_phrase(locale: str, count: int, zh_noun: str, en_singular: str, en_plural: str | None = None) -> str:
    """Format a small localized count with correct English plurality."""
    if locale == "zh-CN":
        return f"{count} {zh_noun}"
    noun = en_singular if count == 1 else (en_plural or f"{en_singular}s")
    return f"{count} {noun}"


def _relation(value: str | None, locale: str) -> str:
    value = value or COPY[locale]["self"]
    return RELATIONS_EN.get(value, value) if locale == "en-US" else value


def _member_label(member: dict, locale: str) -> str:
    return f'{member.get("name", "")} ({_relation(member.get("relation"), locale)})' if locale == "en-US" else f'{member.get("name", "")}（{_relation(member.get("relation"), locale)}）'


def _source(value: str | None, locale: str) -> str:
    value = value or "manual"
    return SOURCES[locale].get(value, value.replace("_", " ").title() if locale == "en-US" else value.replace("_", " "))


def _system_text(value: str | None, locale: str) -> str:
    """Localize short, system-generated advisor labels without altering user notes."""
    if not value or locale != "en-US":
        return value or ""
    metric_map = {"血压": "blood pressure", "血糖": "blood glucose", "心率": "heart rate",
                  "体重": "weight", "体温": "temperature", "血氧": "blood oxygen"}
    if value.startswith("尚未记录"):
        metric = metric_map.get(value[4:], value[4:])
        return f"No {metric} recorded"
    for chinese, english in metric_map.items():
        if value == f"{chinese}偏高":
            return f"High {english}"
        if value == f"{chinese}偏低":
            return f"Low {english}"
        if value == f"{chinese}持续异常":
            return f"Persistent {english} concern"
        if value.startswith(f"{chinese}已 ") and value.endswith(" 天未测量"):
            count = value[len(chinese)+2:-6].strip()
            return f"No {english} measurement for {count} days"
    return value


def _query_metric_trends(member_id: str, days: int = 30) -> dict:
    conn = health_db.get_medical_connection()
    cutoff = (datetime.now() - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
    trends = {}
    try:
        for metric_type in ("blood_pressure", "blood_sugar", "heart_rate", "weight", "temperature", "blood_oxygen"):
            rows = conn.execute(
                """SELECT measured_at, value, source FROM health_metrics
                   WHERE member_id=? AND metric_type=? AND is_deleted=0 AND measured_at>=?
                   ORDER BY measured_at""", (member_id, metric_type, cutoff)).fetchall()
            points = []
            for row in rows:
                raw = row["value"]
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError):
                    parsed = raw
                if isinstance(parsed, dict):
                    point = {"date": row["measured_at"][:10], "source": row["source"] or "manual", **parsed}
                else:
                    try:
                        point = {"date": row["measured_at"][:10], "source": row["source"] or "manual", "value": float(parsed)}
                    except (TypeError, ValueError):
                        continue
                points.append(point)
            if points:
                trends[metric_type] = points
        return trends
    finally:
        conn.close()


def _query_active_medications(member_id: str) -> list[dict]:
    conn = health_db.get_medical_connection()
    try:
        return health_db.rows_to_list(conn.execute(
            """SELECT id, name, dosage, frequency, start_date, purpose FROM medications
               WHERE member_id=? AND is_deleted=0 AND (end_date IS NULL OR end_date='')
               AND (is_active=1 OR is_active IS NULL) ORDER BY start_date DESC""", (member_id,)).fetchall())
    finally:
        conn.close()


def _query_active_reminders(member_id: str) -> list[dict]:
    conn = health_db.get_medical_connection()
    try:
        return health_db.rows_to_list(conn.execute(
            """SELECT id, type, title, content, schedule_type, schedule_value,
                      next_trigger_at, related_record_id, related_record_type, priority
               FROM reminders
               WHERE member_id=? AND is_deleted=0 AND is_active=1
               ORDER BY next_trigger_at, created_at""", (member_id,)).fetchall())
    finally:
        conn.close()


def _query_lifestyle_summary(member_id: str, days: int) -> dict:
    cutoff = (datetime.now() - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
    result = {"diet_days": 0, "diet": None, "exercise_count": 0, "exercise_days": 0,
              "duration": 0, "calories_burned": 0.0, "step_days": 0, "avg_steps": None,
              "recent_diet": None, "recent_exercise": []}
    conn = health_db.get_lifestyle_connection()
    try:
        row = conn.execute(
            """SELECT COUNT(DISTINCT meal_date) AS days, SUM(total_calories) AS calories,
                      SUM(total_protein) AS protein, SUM(total_fat) AS fat,
                      SUM(total_carbs) AS carbs, SUM(total_fiber) AS fiber
               FROM diet_records WHERE member_id=? AND is_deleted=0 AND meal_date>=?""", (member_id, cutoff)).fetchone()
        diet_days = int(row["days"] or 0)
        result["diet_days"] = diet_days
        if diet_days:
            result["diet"] = {key: float(row[key] or 0) / diet_days for key in ("calories", "protein", "fat", "carbs", "fiber")}
            recent_diet = conn.execute(
                """SELECT meal_date, SUM(total_calories) AS calories, SUM(total_protein) AS protein,
                          SUM(total_fat) AS fat, SUM(total_carbs) AS carbs, SUM(total_fiber) AS fiber
                   FROM diet_records WHERE member_id=? AND is_deleted=0 AND meal_date>=?
                   GROUP BY meal_date ORDER BY meal_date DESC LIMIT 1""", (member_id, cutoff)).fetchone()
            result["recent_diet"] = {key: recent_diet[key] for key in recent_diet.keys()} if recent_diet else None
        row = conn.execute(
            """SELECT COUNT(*) AS count, COUNT(DISTINCT exercise_date) AS days,
                      SUM(duration) AS duration, SUM(calories_burned) AS burned
               FROM exercise_records WHERE member_id=? AND is_deleted=0 AND exercise_date>=?""", (member_id, cutoff)).fetchone()
        result.update(exercise_count=int(row["count"] or 0), exercise_days=int(row["days"] or 0),
                      duration=int(row["duration"] or 0), calories_burned=float(row["burned"] or 0))
        result["recent_exercise"] = health_db.rows_to_list(conn.execute(
            """SELECT exercise_date, exercise_type, exercise_name, duration, calories_burned, intensity
               FROM exercise_records WHERE member_id=? AND is_deleted=0 AND exercise_date>=?
               ORDER BY exercise_date DESC, exercise_time DESC LIMIT 2""", (member_id, cutoff)).fetchall())
    finally:
        conn.close()

    conn = health_db.get_medical_connection()
    try:
        rows = conn.execute(
            """SELECT measured_at, value FROM health_metrics WHERE member_id=? AND metric_type='steps'
               AND is_deleted=0 AND measured_at>=? ORDER BY measured_at""", (member_id, cutoff)).fetchall()
        daily = {}
        for row in rows:
            try:
                parsed = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                value = parsed.get("value", parsed.get("steps")) if isinstance(parsed, dict) else parsed
                daily[row["measured_at"][:10]] = daily.get(row["measured_at"][:10], 0) + float(value)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        if daily:
            result["step_days"] = len(daily)
            result["avg_steps"] = sum(daily.values()) / len(daily)
    finally:
        conn.close()
    return result


def _query_sleep_summary(member_id: str, days: int) -> dict:
    cutoff = (datetime.now() - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
    conn = health_db.get_medical_connection()
    records = []
    try:
        rows = conn.execute(
            """SELECT measured_at, value FROM health_metrics WHERE member_id=? AND metric_type='sleep'
               AND is_deleted=0 AND measured_at>=? ORDER BY measured_at""", (member_id, cutoff)).fetchall()
        for row in rows:
            try:
                value = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(value, dict) and value.get("duration_min") is not None:
                records.append({"date": row["measured_at"][:10], **value})
    finally:
        conn.close()
    if not records:
        return {"count": 0}
    def average(key):
        values = [float(item[key]) for item in records if item.get(key) is not None]
        return sum(values) / len(values) if values else None
    return {"count": len(records), "avg_duration": average("duration_min"), "avg_score": average("score"),
            "latest_deep": records[-1].get("deep_min"), "latest_rem": records[-1].get("rem_min"),
            "latest_duration": records[-1].get("duration_min"), "latest_score": records[-1].get("score"),
            "latest_date": records[-1]["date"]}


def _lab_items(raw) -> list[dict]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("items", "results", "tests"):
            if isinstance(value.get(key), list):
                return [item for item in value[key] if isinstance(item, dict)]
        if value and all(isinstance(item, dict) for item in value.values()):
            return [{"name": name, **item} for name, item in value.items()]
        return [value]
    return []


def _is_abnormal(item: dict) -> bool:
    if item.get("abnormal") is True or item.get("is_abnormal") is True:
        return True
    return any(str(item.get(key, "")).strip().lower() in ABNORMAL_WORDS for key in ("status", "flag"))


def _abnormal_label(item: dict) -> str:
    name = item.get("name") or item.get("item_name") or item.get("test_name") or item.get("indicator") or ""
    value = item.get("value")
    unit = item.get("unit") or ""
    flag = item.get("flag") or item.get("status") or ""
    pieces = [str(name)] if name else []
    if value not in (None, ""):
        pieces.append(f"{value} {unit}".strip())
    if flag:
        pieces.append(str(flag))
    return " · ".join(pieces)


def _lab_abnormal_details(lab: dict) -> tuple[int, list[str]]:
    abnormal = [item for item in _lab_items(lab.get("items")) if _is_abnormal(item)]
    labels = [_abnormal_label(item) for item in abnormal if _abnormal_label(item)]
    return len(abnormal), labels[:2]


def _query_recent_care(member_id: str, days: int, limit: int = 3) -> dict:
    cutoff = (datetime.now() - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
    conn = health_db.get_medical_connection()
    try:
        visits = health_db.rows_to_list(conn.execute(
            """SELECT visit_date, visit_type, hospital, department, diagnosis, summary FROM visits
               WHERE member_id=? AND is_deleted=0 AND visit_date>=? ORDER BY visit_date DESC LIMIT ?""",
            (member_id, cutoff, limit)).fetchall())
        labs = health_db.rows_to_list(conn.execute(
            """SELECT test_date, test_name, items FROM lab_results WHERE member_id=? AND is_deleted=0
               AND test_date>=? ORDER BY test_date DESC LIMIT ?""", (member_id, cutoff, limit)).fetchall())
        all_labs = health_db.rows_to_list(conn.execute(
            """SELECT test_date, test_name, items FROM lab_results WHERE member_id=? AND is_deleted=0
               AND test_date>=? ORDER BY test_date DESC""", (member_id, cutoff)).fetchall())
        imaging = health_db.rows_to_list(conn.execute(
            """SELECT exam_date, exam_name, findings, conclusion FROM imaging_results WHERE member_id=?
               AND is_deleted=0 AND exam_date>=? ORDER BY exam_date DESC LIMIT ?""", (member_id, cutoff, limit)).fetchall())
        record_counts = {
            "visits": conn.execute(
                "SELECT COUNT(*) FROM visits WHERE member_id=? AND is_deleted=0 AND visit_date>=?",
                (member_id, cutoff)).fetchone()[0],
            "labs": conn.execute(
                "SELECT COUNT(*) FROM lab_results WHERE member_id=? AND is_deleted=0 AND test_date>=?",
                (member_id, cutoff)).fetchone()[0],
            "imaging": conn.execute(
                "SELECT COUNT(*) FROM imaging_results WHERE member_id=? AND is_deleted=0 AND exam_date>=?",
                (member_id, cutoff)).fetchone()[0],
        }
    finally:
        conn.close()
    for lab in labs:
        lab["abnormal_count"], lab["abnormal_labels"] = _lab_abnormal_details(lab)
    abnormal_reports = []
    for lab in all_labs:
        count, labels = _lab_abnormal_details(lab)
        if count:
            abnormal_reports.append({
                "test_date": lab.get("test_date"),
                "test_name": lab.get("test_name"),
                "abnormal_count": count,
                "abnormal_labels": labels,
            })
    return {
        "visits": visits,
        "labs": labs,
        "imaging": imaging,
        "record_counts": record_counts,
        "abnormal_summary": {
            "report_count": len(abnormal_reports),
            "item_count": sum(item["abnormal_count"] for item in abnormal_reports),
            "reports": abnormal_reports[:3],
        },
    }


def _care_record_count(care: dict) -> int:
    """Count all recent care records while keeping rendered lists intentionally short."""
    counts = care.get("record_counts")
    if isinstance(counts, dict):
        return sum(int(counts.get(key, 0) or 0) for key in ("visits", "labs", "imaging"))
    return sum(len(care.get(key, [])) for key in ("visits", "labs", "imaging"))


def _care_abnormal_count(care: dict) -> int:
    summary = care.get("abnormal_summary")
    if isinstance(summary, dict):
        return int(summary.get("item_count", 0) or 0)
    return sum(int(lab.get("abnormal_count", 0) or 0) for lab in care.get("labs", []))


def _care_abnormal_reports(care: dict) -> list[dict]:
    summary = care.get("abnormal_summary")
    if isinstance(summary, dict) and isinstance(summary.get("reports"), list):
        return summary["reports"]
    return [lab for lab in care.get("labs", []) if int(lab.get("abnormal_count", 0) or 0)]


def _metric_number(point: dict, metric_type: str):
    if metric_type == "blood_pressure":
        return point.get("systolic")
    if metric_type == "blood_sugar" and point.get("fasting") is not None:
        return point.get("fasting")
    return point.get("value")


def _sparkline(metric_type: str, points: list[dict], locale: str) -> str:
    width, height, pad = 260, 54, 5
    def path(values, color):
        valid = [(i, float(v)) for i, v in enumerate(values) if v is not None]
        if not valid:
            return ""
        low, high = min(v for _, v in valid), max(v for _, v in valid)
        span, denom = high - low or 1, max(len(values) - 1, 1)
        coords = [(pad + (width - 2 * pad) * i / denom, pad + (height - 2 * pad) * (high - v) / span) for i, v in valid]
        line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.3" fill="{color}"/>' for x, y in coords)
        return f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>{dots}'
    if metric_type == "blood_pressure":
        content = path([p.get("systolic") for p in points], "#D76A4A") + path([p.get("diastolic") for p in points], "#2F6FEB")
    else:
        content = path([_metric_number(p, metric_type) for p in points], "#1E7A6E")
    label = _escape(METRIC_NAMES[locale].get(metric_type, metric_type))
    return f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" aria-label="{label}"><line x1="{pad}" y1="{height-pad}" x2="{width-pad}" y2="{height-pad}" stroke="#DDE8E5"/>{content}</svg>'


def _tip_focus(tip: dict) -> str | None:
    """Map deterministic advisor signals to the card module they affect."""
    tip_type = str(tip.get("type", ""))
    if tip_type.startswith("metric_"):
        return "metrics"
    if tip_type == "medication_adherence":
        return "medications"
    if tip_type in ("overdue_checkup", "cycle_alert"):
        return "care"
    return None


def _metric_types_from_tips(member_data: dict, trends: dict) -> list[str]:
    """Find metric cards named by an alert without guessing from numeric values."""
    names = {
        metric_type: {METRIC_NAMES["zh-CN"].get(metric_type, ""), METRIC_NAMES["en-US"].get(metric_type, "")}
        for metric_type in trends
    }
    focused = []
    for tip in member_data.get("health_tips", []):
        if tip.get("severity") not in ("alert", "warning") or _tip_focus(tip) != "metrics":
            continue
        text = " ".join(str(tip.get(key, "")) for key in ("title", "detail", "message"))
        for metric_type, labels in names.items():
            if metric_type not in focused and any(label and label.lower() in text.lower() for label in labels):
                focused.append(metric_type)
    return focused


def _has_lifestyle_data(lifestyle: dict, sleep: dict) -> bool:
    return bool(lifestyle.get("diet_days") or lifestyle.get("exercise_count") or
                lifestyle.get("step_days") or sleep.get("count"))


def _has_timeline_data(trends: dict, lifestyle: dict, sleep: dict, care: dict) -> bool:
    return bool(trends or lifestyle.get("recent_diet") or lifestyle.get("recent_exercise") or
                sleep.get("count") or any(care.get(key) for key in ("visits", "labs", "imaging")))


def _personal_layout(member_data: dict, trends: dict, lifestyle: dict, sleep: dict,
                     care: dict, meds: list[dict], requested_focus: str = "auto") -> dict:
    """Choose a reproducible layout from risk signals, coverage, and user intent."""
    coverage = {
        "metrics": sum(len(points) for points in trends.values()),
        "lifestyle": int(lifestyle.get("diet_days", 0)) + int(lifestyle.get("exercise_count", 0)) +
                     int(lifestyle.get("step_days", 0)) + int(sleep.get("count", 0)),
        "care": _care_record_count(care),
        "medications": len(meds),
    }
    risk = {key: 0 for key in coverage}
    reasons = []
    for tip in member_data.get("health_tips", []):
        severity = tip.get("severity")
        module = _tip_focus(tip)
        if module and severity in ("alert", "warning"):
            risk[module] += 3 if severity == "alert" else 2
            reasons.append(f'{module}:{severity}')
    abnormal_labs = _care_abnormal_count(care)
    if abnormal_labs:
        risk["care"] += min(abnormal_labs, 3) * 2
        reasons.append("care:flagged-lab")
    for reminder in member_data.get("due_reminders", []):
        text = " ".join(str(reminder.get(key, "")) for key in ("type", "title", "related_record_type")).lower()
        if any(token in text for token in ("medication", "medicine", "用药", "服药")):
            risk["medications"] += 1
        elif any(token in text for token in ("visit", "checkup", "follow", "复查", "就诊")):
            risk["care"] += 1

    scores = {module: coverage[module] + risk[module] * 10 for module in coverage}
    if requested_focus != "auto":
        focus = requested_focus
        reasons.insert(0, "user-request")
    else:
        risk_modules = [module for module, value in risk.items() if value]
        if risk_modules:
            focus = max(risk_modules, key=lambda module: (risk[module], scores[module]))
        else:
            ranked = sorted(scores, key=scores.get, reverse=True)
            first, second = scores[ranked[0]], scores[ranked[1]]
            focus = ranked[0] if first >= 4 and first >= max(second * 1.35, second + 3) else "balanced"

    total_records = sum(coverage.values())
    density = "rich" if total_records >= 30 else ("standard" if total_records >= 8 else "sparse")
    base_orders = {
        "metrics": ["metrics", "lifestyle", "timeline", "medications"],
        "lifestyle": ["lifestyle", "metrics", "timeline", "medications"],
        "care": ["timeline", "metrics", "lifestyle", "medications"],
        "medications": ["medications", "metrics", "timeline", "lifestyle"],
        "balanced": ["metrics", "lifestyle", "timeline", "medications"],
    }
    available = {
        "metrics": bool(trends),
        "lifestyle": _has_lifestyle_data(lifestyle, sleep),
        "timeline": _has_timeline_data(trends, lifestyle, sleep, care),
        "medications": bool(meds),
    }
    requested_section = {"care": "timeline"}.get(requested_focus, requested_focus)
    section_order = [section for section in base_orders[focus]
                     if available[section] or section == requested_section]
    if not section_order:
        section_order = ["metrics"]

    lifestyle_counts = {
        "diet": int(lifestyle.get("diet_days", 0)),
        "activity": max(int(lifestyle.get("exercise_count", 0)), int(lifestyle.get("step_days", 0))),
        "sleep": int(sleep.get("count", 0)),
    }
    lifestyle_focus = max(lifestyle_counts, key=lifestyle_counts.get) if focus == "lifestyle" and any(lifestyle_counts.values()) else None
    return {
        "focus": focus,
        "density": density,
        "coverage": coverage,
        "risk": risk,
        "reasons": reasons,
        "section_order": section_order,
        "metric_focus": _metric_types_from_tips(member_data, trends),
        "lifestyle_focus": lifestyle_focus,
    }


def _metric_cards(trends: dict, locale: str, featured_types: list[str] | None = None,
                  feature_leader: bool = False) -> str:
    c = COPY[locale]
    cards = []
    has_featured = False
    featured_types = featured_types or []
    ordered = sorted(trends.items(), key=lambda item: (item[0] not in featured_types, -len(item[1])))
    for index, (metric_type, points) in enumerate(ordered):
        latest, first = points[-1], points[0]
        if metric_type == "blood_pressure":
            value = f'{latest.get("systolic", "—")}/{latest.get("diastolic", "—")}'
            first_num, last_num = first.get("systolic"), latest.get("systolic")
        else:
            first_num, last_num = _metric_number(first, metric_type), _metric_number(latest, metric_type)
            value = _fmt_number(last_num, 1 if metric_type in ("blood_sugar", "weight") else 0)
        delta = c["not_enough"]
        if first_num is not None and last_num is not None and len(points) > 1:
            diff = float(last_num) - float(first_num)
            delta = c["flat"] if abs(diff) < 1e-9 else c["change"].format(value=f'{diff:+g}')
        featured = ((featured_types and metric_type == featured_types[0]) or
                    (not featured_types and feature_leader and index == 0 and len(points) >= 3))
        has_featured = has_featured or featured
        cards.append(f'''<article class="metric-card{' featured' if featured else ''}">
          <div class="metric-head"><b>{_escape(METRIC_NAMES[locale].get(metric_type, metric_type))}</b><span>{_count_phrase(locale, len(points), "条", "record")}</span></div>
          <div class="metric-value">{_escape(value)} <small>{_escape(METRIC_UNITS.get(metric_type, ""))}</small></div>
          <div class="muted">{_escape(delta)}</div>{_sparkline(metric_type, points, locale)}
          <div class="meta"><span>{c["latest"]}: {_escape(latest.get("date"))}</span><span>{c["source"]}: {_escape(_source(latest.get("source"), locale))}</span></div>
        </article>''')
    grid_class = "metric-grid focused" if has_featured else "metric-grid"
    return '<div class="empty">'+c["no_metrics"]+'</div>' if not cards else f'<div class="{grid_class}">'+"".join(cards)+"</div>"


def _hours(minutes, locale: str) -> str:
    if minutes is None:
        return "—"
    return f'{float(minutes)/60:.1f} {COPY[locale]["hours"]}'


def _lifestyle_sleep(lifestyle: dict, sleep: dict, locale: str, section_number: str = "02",
                     featured_panel: str | None = None, featured_section: bool = False) -> str:
    c = COPY[locale]
    diet = lifestyle.get("diet")
    intake_class = "panel intake" + (" featured-panel" if featured_panel == "diet" else "")
    if diet:
        intake = f'''<div class="{intake_class}"><div class="eyebrow">{c["recorded_intake"]}</div>
          <div class="big blue">{_fmt_number(diet["calories"])} <small>kcal</small></div>
          <div class="muted">{c["daily_average"]} · {_count_phrase(locale, lifestyle["diet_days"], "个饮食记录日", "food log day")}</div>
          <div class="macro"><span>{c["protein"]}<b>{_fmt_number(diet["protein"])}g</b></span><span>{c["carbs"]}<b>{_fmt_number(diet["carbs"])}g</b></span><span>{c["fat"]}<b>{_fmt_number(diet["fat"])}g</b></span><span>{c["fiber"]}<b>{_fmt_number(diet["fiber"])}g</b></span></div></div>'''
    else:
        intake = f'<div class="{intake_class}"><div class="eyebrow">{c["recorded_intake"]}</div><div class="empty compact">{c["no_diet"]}</div></div>'
    activity_bits = []
    if lifestyle["exercise_count"]:
        session_noun = "次" if locale == "zh-CN" else ("session" if lifestyle["exercise_count"] == 1 else "sessions")
        activity_bits.append(f'<div><div class="big green">{lifestyle["exercise_count"]} <small>{session_noun}</small></div><div class="muted">{c["duration"]} {_fmt_number(lifestyle["duration"])} {c["minutes"]} · {c["activity_burn"]} {_fmt_number(lifestyle["calories_burned"])} kcal</div></div>')
    else:
        activity_bits.append(f'<div class="empty compact">{c["no_activity"]}</div>')
    if lifestyle["step_days"]:
        activity_bits.append(f'<div class="step-box"><span>{c["steps"]}</span><b>{_fmt_number(lifestyle["avg_steps"])}</b><small>{_count_phrase(locale, lifestyle["step_days"], "个步数记录日", "step log day")}</small></div>')
    else:
        activity_bits.append(f'<div class="muted top-gap">{c["no_steps"]}</div>')
    activity_class = "panel activity" + (" featured-panel" if featured_panel == "activity" else "")
    activity = f'<div class="{activity_class}"><div class="eyebrow">{c["activity"]}</div>{"".join(activity_bits)}</div>'
    sleep_class = "panel sleep" + (" featured-panel" if featured_panel == "sleep" else "")
    sleep_html = f'<div class="{sleep_class}"><div class="eyebrow">{c["sleep"]}</div>'
    if sleep.get("count"):
        sleep_html += f'<div class="big coral">{_hours(sleep.get("avg_duration"), locale)}</div><div class="muted">{_count_phrase(locale, sleep["count"], "个睡眠记录夜", "sleep record")}</div><div class="sleep-row"><span>{c["avg_score"]}<b>{_fmt_number(sleep.get("avg_score"))}</b></span><span>{c["latest_deep"]}<b>{_fmt_number(sleep.get("latest_deep"))} {c["minutes"]}</b></span><span>{c["latest_rem"]}<b>{_fmt_number(sleep.get("latest_rem"))} {c["minutes"]}</b></span></div>'
    else:
        sleep_html += f'<div class="empty compact">{c["no_sleep"]}</div>'
    sleep_html += '</div>'
    section_class = "section-featured" if featured_section else ""
    grid_class = "wellness-grid focused" if featured_panel else "wellness-grid"
    return f'<section class="{section_class}"><div class="section-title"><span>{section_number}</span><h2>{c["intake_activity"]}</h2></div><div class="{grid_class}">{intake}{activity}{sleep_html}</div><p class="scope-note">{c["not_balance"]}</p></section>'


def _timeline_metric_value(metric_type: str, point: dict) -> str:
    if metric_type == "blood_pressure":
        value = f'{point.get("systolic", "—")}/{point.get("diastolic", "—")}'
    else:
        value = _fmt_number(_metric_number(point, metric_type), 1 if metric_type in ("blood_sugar", "weight") else 0)
    return f'{value} {METRIC_UNITS.get(metric_type, "")}'.strip()


def _personal_timeline(trends: dict, lifestyle: dict, sleep: dict, care: dict, locale: str,
                       section_number: str = "03", featured_section: bool = False) -> str:
    """Build a compact chronology spanning care and everyday health records."""
    c = COPY[locale]
    events = []

    for item in care["visits"]:
        title = item.get("diagnosis") or item.get("department") or item.get("visit_type") or c["unknown"]
        detail = " · ".join(value for value in (item.get("hospital"), item.get("department"), item.get("summary")) if value)
        events.append({"date": item.get("visit_date", "")[:10], "priority": 0, "tone": "care-event",
                       "kind": c["visit_event"], "title": title, "detail": detail})
    for item in care["labs"]:
        detail = c["abnormal"].format(count=item["abnormal_count"]) if item["abnormal_count"] else c["no_flagged"]
        if item.get("abnormal_labels"):
            detail += " · " + "; ".join(item["abnormal_labels"])
        events.append({"date": item.get("test_date", "")[:10], "priority": 0, "tone": "care-event",
                       "kind": c["lab_event"], "title": item.get("test_name") or c["unknown"], "detail": detail})
    for item in care["imaging"]:
        events.append({"date": item.get("exam_date", "")[:10], "priority": 0, "tone": "care-event",
                       "kind": c["imaging_event"], "title": item.get("exam_name") or c["unknown"],
                       "detail": item.get("conclusion") or item.get("findings") or c["unknown"]})

    metric_dates = {}
    for metric_type, points in trends.items():
        if points:
            point = points[-1]
            metric_dates.setdefault(point.get("date", ""), []).append(
                f'{METRIC_NAMES[locale].get(metric_type, metric_type)} {_timeline_metric_value(metric_type, point)}')
    for date, values in metric_dates.items():
        events.append({"date": date, "priority": 1, "tone": "metric-event", "kind": c["metric_event"],
                       "title": c["health_metric_update"], "detail": " · ".join(values)})

    recent_diet = lifestyle.get("recent_diet")
    if recent_diet:
        detail = f'{c["recorded_intake"]} {_fmt_number(recent_diet.get("calories"))} kcal · {c["protein"]} {_fmt_number(recent_diet.get("protein"))}g · {c["fiber"]} {_fmt_number(recent_diet.get("fiber"))}g'
        events.append({"date": str(recent_diet.get("meal_date", ""))[:10], "priority": 3, "tone": "food-event",
                       "kind": c["food_event"], "title": c["food_log"], "detail": detail})
    for exercise in lifestyle.get("recent_exercise", []):
        title = exercise.get("exercise_name") or exercise.get("exercise_type") or c["activity_event"]
        detail = f'{c["duration"]} {_fmt_number(exercise.get("duration"))} {c["minutes"]} · {c["activity_burn"]} {_fmt_number(exercise.get("calories_burned"))} kcal'
        events.append({"date": str(exercise.get("exercise_date", ""))[:10], "priority": 2, "tone": "activity-event",
                       "kind": c["activity_event"], "title": title, "detail": detail})
    if sleep.get("count"):
        score = c["sleep_score"].format(score=_fmt_number(sleep.get("latest_score"))) if sleep.get("latest_score") is not None else ""
        detail = " · ".join(value for value in (_hours(sleep.get("latest_duration"), locale), score,
                                                   f'{c["latest_deep"]} {_fmt_number(sleep.get("latest_deep"))} {c["minutes"]}') if value)
        events.append({"date": sleep.get("latest_date", ""), "priority": 4, "tone": "sleep-event",
                       "kind": c["sleep_event"], "title": c["sleep_log"], "detail": detail})

    def event_sort_key(event):
        return event["date"], -event["priority"]

    # Keep one true chronology. Medical events only win ties on the same day;
    # an older visit must not displace today's sleep, meal, or activity log.
    events = sorted(events, key=event_sort_key, reverse=True)[:10]
    if not events:
        body = f'<div class="empty">{c["no_health_timeline"]}</div>'
    else:
        body = '<div class="timeline personal-timeline">' + "".join(
            f'<div class="timeline-item {event["tone"]}"><time>{_escape(event["date"])}</time><span></span><div><b>{_escape(event["title"])}</b><small>{_escape(event["kind"])}</small><p>{_escape(event["detail"])}</p></div></div>'
            for event in events) + '</div>'
    section_class = "timeline-section section-featured" if featured_section else "timeline-section"
    return f'<section class="{section_class}"><div class="section-title"><span>{section_number}</span><h2>{c["health_timeline"]}</h2></div>{body}</section>'


def _medications_html(meds: list[dict], locale: str, section_number: str = "04",
                      featured_section: bool = False) -> str:
    c = COPY[locale]
    if not meds:
        body = f'<div class="empty">{c["no_meds"]}</div>'
    else:
        trs = "".join(f'<tr><td><b>{_escape(m.get("name"))}</b></td><td>{_escape(m.get("dosage"))}</td><td>{_escape(m.get("frequency"))}</td><td>{_escape(m.get("purpose"))}</td><td>{_escape((m.get("start_date") or "")[:10])}</td></tr>' for m in meds)
        body = f'<div class="table-wrap"><table><thead><tr><th>{c["medicine"]}</th><th>{c["dosage"]}</th><th>{c["frequency"]}</th><th>{c["purpose"]}</th><th>{c["start_date"]}</th></tr></thead><tbody>{trs}</tbody></table></div>'
    section_class = "section-featured" if featured_section else ""
    return f'<section class="{section_class}"><div class="section-title"><span>{section_number}</span><h2>{c["active_meds"]}</h2></div>{body}</section>'


def _attention_html(member_data: dict, care: dict, locale: str) -> str:
    c = COPY[locale]
    items = []
    for lab in _care_abnormal_reports(care):
        count = int(lab.get("abnormal_count", 0) or 0)
        if not count:
            continue
        text = f'{lab.get("test_name") or c["lab_event"]}: {c["abnormal"].format(count=count)}'
        if lab.get("abnormal_labels"):
            text += " · " + "; ".join(lab["abnormal_labels"])
        items.append(f'<div class="attention-item alert"><span></span><p>{_escape(text)}</p></div>')
        if len(items) >= 3:
            break
    for tip in member_data.get("health_tips", [])[:max(0, 3-len(items))]:
        severity = tip.get("severity", "info")
        text = tip.get("title") or tip.get("message") or tip.get("detail")
        if text:
            items.append(f'<div class="attention-item {severity}"><span></span><p>{_escape(_system_text(text, locale))}</p></div>')
    for reminder in member_data.get("due_reminders", [])[:max(0, 3-len(items))]:
        text = reminder.get("title") or reminder.get("content")
        if text:
            items.append(f'<div class="attention-item info"><span></span><p>{_escape(text)}</p></div>')
    if not items:
        return f'<div class="clear"><i>✓</i>{c["all_clear"]}</div>'
    return '<div class="attention-list">'+"".join(items)+'</div>'


def _attention_section(member_data: dict, care: dict, locale: str) -> str:
    if not (member_data.get("health_tips") or member_data.get("due_reminders") or _care_abnormal_count(care)):
        return ""
    c = COPY[locale]
    has_risk = (_care_abnormal_count(care) > 0 or
                any(tip.get("severity") in ("alert", "warning") for tip in member_data.get("health_tips", [])))
    return f'<section class="attention-section{" has-risk" if has_risk else ""}"><div class="compact-attention"><b>{c["attention"]}</b>{_attention_html(member_data, care, locale)}</div></section>'


def _personal_content(member: dict, member_data: dict, trends: dict, lifestyle: dict, sleep: dict,
                      care: dict, meds: list[dict], locale: str, layout: dict) -> str:
    c = COPY[locale]
    sections = []
    for index, section in enumerate(layout["section_order"], start=1):
        number = f"{index:02d}"
        if section == "metrics":
            featured = layout["focus"] == "metrics"
            classes = "overview-section section-featured" if featured else "overview-section"
            cards = _metric_cards(trends, locale, layout.get("metric_focus"), feature_leader=featured)
            sections.append(f'<section class="{classes}"><div class="section-title"><span>{number}</span><h2>{c["metrics"]}</h2></div>{cards}</section>')
        elif section == "lifestyle":
            sections.append(_lifestyle_sleep(lifestyle, sleep, locale, number,
                                              layout.get("lifestyle_focus"), layout["focus"] == "lifestyle"))
        elif section == "timeline":
            sections.append(_personal_timeline(trends, lifestyle, sleep, care, locale, number,
                                                layout["focus"] == "care"))
        elif section == "medications":
            sections.append(_medications_html(meds, locale, number, layout["focus"] == "medications"))
    return _attention_section(member_data, care, locale) + "".join(sections)


def _family_latest_metrics(trends: dict, locale: str) -> str:
    c = COPY[locale]
    latest_metrics = []
    for metric_type, points in list(trends.items())[:3]:
        point = points[-1]
        if metric_type == "blood_pressure":
            value = f'{point.get("systolic", "—")}/{point.get("diastolic", "—")}'
        else:
            value = _fmt_number(_metric_number(point, metric_type), 1 if metric_type in ("blood_sugar", "weight") else 0)
        latest_metrics.append(f'<span><small>{_escape(METRIC_NAMES[locale].get(metric_type, metric_type))}</small><b>{_escape(value)} <i>{_escape(METRIC_UNITS.get(metric_type, ""))}</i></b></span>')
    if not latest_metrics:
        return f'<div class="family-state-note">{c["data_missing"]}</div>'
    return f'<div class="family-metrics">{"".join(latest_metrics)}</div>'


def _family_medication_schedule(medication: dict, reminders: list[dict], locale: str) -> str:
    c = COPY[locale]
    linked = [
        reminder for reminder in reminders
        if reminder.get("type") == "medication"
        and reminder.get("related_record_id") == medication.get("id")
    ]
    daily_times = sorted({
        str(reminder.get("schedule_value") or "")
        for reminder in linked
        if reminder.get("schedule_type") == "daily" and reminder.get("schedule_value")
    })
    if daily_times:
        separator = "、" if locale == "zh-CN" else ", "
        return c["daily_at"].format(times=separator.join(daily_times))
    next_times = sorted(
        str(reminder.get("next_trigger_at") or "")[:16]
        for reminder in linked if reminder.get("next_trigger_at")
    )
    return c["next_at"].format(time=next_times[0]) if next_times else ""


def _family_medications_html(meds: list[dict], reminders: list[dict], locale: str) -> str:
    c = COPY[locale]
    if not meds:
        return f'<div class="family-empty">{c["no_family_meds"]}</div>'
    rows = []
    for med in meds[:3]:
        details = " · ".join(str(value) for value in (med.get("dosage"), med.get("frequency")) if value)
        schedule = _family_medication_schedule(med, reminders, locale)
        schedule_html = f'<em>{_escape(schedule)}</em>' if schedule else ""
        rows.append(
            f'<div class="family-list-item medication"><div><b>{_escape(med.get("name"))}</b>'
            f'<small>{_escape(details)}</small></div>'
            f'{schedule_html}</div>'
        )
    if len(meds) > 3:
        rows.append(f'<div class="family-more">{c["more_meds"].format(count=len(meds)-3)}</div>')
    return '<div class="family-list">' + "".join(rows) + '</div>'


def _family_reminder_schedule(reminder: dict, locale: str) -> str:
    c = COPY[locale]
    if reminder.get("schedule_type") == "daily" and reminder.get("schedule_value"):
        return c["daily_at"].format(times=reminder["schedule_value"])
    if reminder.get("next_trigger_at"):
        return c["next_at"].format(time=str(reminder["next_trigger_at"])[:16])
    return ""


def _family_attention_entries(member_data: dict, care: dict, reminders: list[dict], locale: str) -> list[tuple[str, str]]:
    c = COPY[locale]
    entries = []
    seen = set()

    def add(tone: str, text: str):
        normalized = str(text or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            entries.append((tone, normalized))

    abnormal_reports = _care_abnormal_reports(care)
    for lab in abnormal_reports:
        text = f'{lab.get("test_name") or c["lab_event"]}: {c["abnormal"].format(count=lab.get("abnormal_count", 0))}'
        if lab.get("abnormal_labels"):
            text += " · " + "; ".join(lab["abnormal_labels"])
        add("alert", text)
    for tip in member_data.get("health_tips", []):
        if tip.get("severity") not in ("alert", "warning"):
            continue
        add(tip.get("severity", "warning"), _system_text(tip.get("title") or tip.get("message") or tip.get("detail") or "", locale))
    due_ids = set()
    for reminder in member_data.get("due_reminders", []):
        due_ids.add(reminder.get("id"))
        text = reminder.get("title") or reminder.get("content") or ""
        add("warning", f'{c["due_prefix"]}：{text}' if locale == "zh-CN" else f'{c["due_prefix"]}: {text}')
    for reminder in reminders:
        if reminder.get("id") in due_ids or reminder.get("type") == "medication":
            continue
        text = reminder.get("title") or reminder.get("content") or ""
        schedule = _family_reminder_schedule(reminder, locale)
        prefix = f'{c["upcoming_prefix"]}：' if locale == "zh-CN" else f'{c["upcoming_prefix"]}: '
        add("info", prefix + text + (f' · {schedule}' if schedule else ""))
    return entries


def _family_attention_html(entries: list[tuple[str, str]], locale: str) -> str:
    c = COPY[locale]
    if not entries:
        return f'<div class="family-empty clear-state">✓ {c["no_family_attention"]}</div>'
    visible = entries[:4]
    items = "".join(
        f'<div class="family-list-item attention {tone}"><i></i><p>{_escape(text)}</p></div>'
        for tone, text in visible
    )
    if len(entries) > len(visible):
        items += f'<div class="family-more">{c["more_attention"].format(count=len(entries)-len(visible))}</div>'
    return '<div class="family-list">' + items + '</div>'


def _family_card(member: dict, member_data: dict, trends: dict, care: dict,
                 meds: list[dict], reminders: list[dict], locale: str,
                 featured: bool = False) -> str:
    c = COPY[locale]
    attention_entries = _family_attention_entries(member_data, care, reminders, locale)
    attention_count = sum(1 for tone, _ in attention_entries if tone in ("alert", "warning"))
    has_recent_data = bool(trends or _care_record_count(care))
    status = c["needs_attention"] if attention_count else c["stable"]
    summary = c["attention_count"].format(count=attention_count) if attention_count else (c["data_present"] if has_recent_data else c["stable"])
    return f'''<article class="family-card{' featured-member' if featured else ''}"><div class="family-card-head"><div><h3>{_escape(_member_label(member, locale))}</h3><p>{_escape(summary)}</p></div><span class="status {'watch' if attention_count else ''}">{status}</span></div>
      <div class="family-block"><div class="family-block-title">{c["current_status"]}</div>{_family_latest_metrics(trends, locale)}</div>
      <div class="family-block"><div class="family-block-title">{c["current_meds"]}</div>{_family_medications_html(meds, reminders, locale)}</div>
      <div class="family-block"><div class="family-block-title">{c["reminders_attention"]}</div>{_family_attention_html(attention_entries, locale)}</div></article>'''


def _family_rank(data: dict) -> tuple:
    """Put urgent members first, then members with active care plans or recent data."""
    tips = data["member_data"].get("health_tips", [])
    alerts = sum(1 for tip in tips if tip.get("severity") == "alert")
    warnings = sum(1 for tip in tips if tip.get("severity") == "warning")
    abnormal_labs = _care_abnormal_count(data["care"])
    reminders = len(data["member_data"].get("due_reminders", []))
    coverage = (len(data.get("meds", [])) + len(data.get("reminders", [])) +
                sum(len(points) for points in data["trends"].values()) +
                int(data["lifestyle"].get("diet_days", 0)) +
                int(data["lifestyle"].get("exercise_count", 0)) +
                int(data["sleep"].get("count", 0)) +
                _care_record_count(data["care"]))
    return alerts, warnings + abnormal_labs, reminders, coverage


def _family_content(all_data: list[dict], locale: str, featured_member: str | None) -> str:
    c = COPY[locale]
    cards = "".join(
        _family_card(
            data["member"], data["member_data"], data["trends"], data["care"],
            data["meds"], data["reminders"], locale,
            featured=data["member"]["id"] == featured_member,
        )
        for data in all_data
    )
    return f'<section><div class="section-title"><h2>{c["family_overview"]}</h2></div><div class="family-grid">{cards}</div></section>'


def _summary_strip(briefing: dict, locale: str, family_data=None) -> str:
    c = COPY[locale]
    alert_count = int(briefing.get("total_alerts", 0) or 0)
    warning_count = int(briefing.get("total_warnings", 0) or 0)
    reminder_count = int(briefing.get("total_due_reminders", 0) or 0)
    if family_data is not None:
        people = sum(
            1 for data in family_data
            if (_care_abnormal_count(data["care"]) or
                any(tip.get("severity") in ("alert", "warning")
                    for tip in data["member_data"].get("health_tips", [])) or
                data["member_data"].get("due_reminders"))
        )
        cards = [(str(len(family_data)), c["members"].format(count=len(family_data)), "green"), (str(people), c["attention_people"].format(count=people), "coral"), (str(reminder_count), c["pending"].format(count=reminder_count), "blue")]
    elif not (alert_count or warning_count or reminder_count):
        return f'<div class="clear hero-clear"><i>✓</i>{c["all_clear"]}</div>'
    else:
        cards = [(str(alert_count), c["alerts"].format(count=alert_count), "coral"), (str(warning_count), c["warnings"].format(count=warning_count), "gold"), (str(reminder_count), c["todos"].format(count=reminder_count), "blue")]
    return '<div class="summary-strip">'+"".join(f'<div><b class="{color}">{value}</b><span>{label}</span></div>' for value, label, color in cards)+'</div>'


def _render_html(title: str, subtitle: str, privacy: str, summary: str, content: str, locale: str) -> str:
    c = COPY[locale]
    generated = c["generated"].format(time=datetime.now().strftime("%Y-%m-%d %H:%M"))
    return f'''<!DOCTYPE html><html lang="{c["lang"]}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_escape(title)}</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#F4F8F7;color:#173B35;font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif;line-break:strict;overflow-wrap:break-word;font-synthesis:none}} .container{{max-width:1040px;margin:auto;padding:26px}}
.header{{position:relative;overflow:hidden;border-radius:24px;padding:29px 36px;background:linear-gradient(135deg,#123C35,#1A6B5E);color:#fff;box-shadow:0 18px 42px rgba(18,60,53,.18)}} .header:after{{content:"";position:absolute;width:250px;height:250px;border:1px solid rgba(255,255,255,.12);border-radius:50%;right:-48px;top:-112px;box-shadow:0 0 0 38px rgba(255,255,255,.035)}}
.brand{{display:flex;align-items:center;gap:13px}} .mark{{display:grid;place-items:center;width:42px;height:42px;border-radius:13px;background:#E1F1ED;color:#17695D;font-weight:800;font-size:22px}} h1{{font-size:28px;line-height:1.2;margin:0;letter-spacing:-.4px}} .subtitle{{margin-top:15px;color:#CCE3DE}} .privacy{{display:inline-block;margin-top:14px;padding:5px 11px;border:1px solid rgba(255,255,255,.22);border-radius:99px;color:#E1EFEC;font-size:12px}}
.summary-strip{{display:grid;grid-template-columns:repeat(3,1fr);background:white;border:1px solid #DFEAE7;border-radius:18px;margin:18px 0;padding:16px;box-shadow:0 9px 28px rgba(18,60,53,.06)}} .summary-strip>div{{padding:2px 22px;border-right:1px solid #E4ECEA}} .summary-strip>div:last-child{{border:0}} .summary-strip b{{font-size:25px;display:block;line-height:1.1}} .summary-strip span{{font-size:12px;color:#718580}} .green{{color:#167568}} .blue{{color:#2F6FEB}} .coral{{color:#D66548}} .gold{{color:#B7791F}}
section{{background:#fff;border:1px solid #DFEAE7;border-radius:20px;padding:21px;margin:14px 0;box-shadow:0 10px 30px rgba(18,60,53,.055)}} .section-featured{{border-color:#A9D0C7;box-shadow:0 12px 34px rgba(18,92,79,.09)}} .section-title{{display:flex;align-items:center;gap:10px;margin-bottom:13px}} .section-title>span{{font-size:10px;font-weight:800;color:#72A69C;border:1px solid #CDE1DC;border-radius:99px;padding:2px 7px}} h2{{font-size:18px;margin:0;text-wrap:balance}} h3{{margin:0;font-size:14px}} p{{text-wrap:pretty}} .muted{{color:#718580;font-size:11px}} .empty{{padding:20px;text-align:center;border:1px dashed #BFD2CD;border-radius:13px;background:#F8FBFA;color:#718580}} .empty.compact{{padding:14px 9px;margin-top:8px}}
.metric-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}} .metric-grid.focused{{grid-template-columns:repeat(5,1fr)}} .metric-card{{padding:13px;border-radius:14px;background:#F7FAF9;border:1px solid #DCE8E5;min-width:0}} .metric-card.featured{{grid-column:span 2;background:#F2F8F6;border-color:#BBD9D2}} .metric-card.featured .spark{{height:50px}} .metric-head,.meta{{display:flex;justify-content:space-between;gap:6px}} .metric-head b{{font-size:12px}} .metric-head span{{font-size:9px;background:#E8F0FA;color:#2F6FEB;border-radius:99px;padding:2px 6px;white-space:nowrap}} .metric-value{{font-size:24px;font-weight:760;margin-top:6px;font-variant-numeric:tabular-nums}} .metric-value small,.big small{{font-size:10px;color:#718580}} .spark{{display:block;width:100%;height:42px;margin:5px 0}} .meta{{font-size:8px;color:#82938F}} .metric-title{{margin-top:16px}}
.wellness-grid{{display:grid;grid-template-columns:1.05fr 1fr 1fr;gap:10px}} .wellness-grid.focused{{grid-template-columns:repeat(4,minmax(0,1fr))}} .featured-panel{{grid-column:span 2}} .panel{{min-height:158px;border-radius:15px;padding:14px;border:1px solid #DCE8E5;background:#F9FBFB}} .intake{{background:#F5F8FC;border-color:#DCE6F3}} .activity{{background:#F3F9F7;border-color:#D6E9E4}} .sleep{{background:#FCF7F4;border-color:#F1E0D9}} .eyebrow{{font-size:11px;font-weight:750;color:#506D67}} .big{{font-size:24px;font-weight:780;margin-top:6px;font-variant-numeric:tabular-nums}} .macro,.sleep-row{{display:grid;grid-template-columns:repeat(2,1fr);gap:5px;margin-top:9px}} .macro span,.sleep-row span{{font-size:9px;color:#7A8D88}} .macro b,.sleep-row b{{display:block;font-size:11px;color:#284A44}} .step-box{{margin-top:9px;padding-top:8px;border-top:1px solid #D7E8E4;display:grid;grid-template-columns:1fr auto}} .step-box b{{font-size:16px;color:#176F63}} .step-box small{{grid-column:1/3;color:#82938F}} .top-gap{{margin-top:10px}} .scope-note{{margin:9px 2px 0;font-size:9px;color:#82938F}}
.table-wrap{{overflow:hidden;border:1px solid #DFE8E6;border-radius:14px}} table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}} th{{background:#EDF4F2;color:#31564F;font-size:11px;text-align:left}} th,td{{padding:9px 12px;border-bottom:1px solid #EDF2F1}} tr:last-child td{{border:0}} td{{font-size:11px}}
.clear{{display:flex;align-items:center;gap:9px;padding:11px 14px;border-radius:13px;background:#E7F5F1;color:#16665B}} .clear i{{display:grid;place-items:center;width:23px;height:23px;border-radius:50%;background:#1B786B;color:white;font-style:normal}} .hero-clear{{margin:14px 0;background:white;border:1px solid #D7E8E3;box-shadow:0 9px 28px rgba(18,60,53,.05)}} .attention-section{{padding:14px 18px}} .attention-section.has-risk{{border-color:#E9B9AA;background:#FFFCFB}} .attention-section .compact-attention{{padding:0;border:0}} .attention-list{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;flex:1}} .attention-item{{display:flex;gap:9px;padding:8px 11px;border-radius:10px;background:#F4F8F7}} .attention-item span{{width:6px;height:6px;border-radius:50%;background:#2F6FEB;margin-top:7px;flex:none}} .attention-item.alert span{{background:#D65F45}} .attention-item.warning span{{background:#D49A30}} .attention-item p{{margin:0;font-size:12px}} .compact-attention{{display:flex;align-items:center;gap:14px;padding-bottom:13px;border-bottom:1px solid #E5EEEB}} .compact-attention>b{{font-size:12px;white-space:nowrap;color:#45645E}} .compact-attention>.clear{{flex:1;padding:8px 11px}} .compact-attention>.clear i{{width:20px;height:20px}}
.family-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}} .family-card{{padding:18px;border:1px solid #DCE8E5;border-radius:17px;background:#FAFCFB}} .family-card.featured-member{{border-color:#E8A58F;background:#FFFAF8;box-shadow:inset 3px 0 #D76A4A}} .family-card-head{{display:flex;justify-content:space-between;gap:10px;margin-bottom:12px}} .family-card-head p{{margin:3px 0;color:#718580;font-size:10px}} .status{{height:max-content;padding:4px 8px;border-radius:99px;background:#E5F3EF;color:#176B60;font-size:9px;white-space:nowrap}} .status.watch{{background:#FCEBE5;color:#A64C36}} .family-block{{padding:11px 0;border-top:1px solid #E5EEEB}} .family-block-title{{font-size:10px;font-weight:760;color:#527069;margin-bottom:7px}} .family-metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:7px}} .family-metrics span{{padding:8px;background:#F0F6F4;border-radius:10px;min-width:0}} .family-metrics small,.family-metrics b{{display:block}} .family-metrics small{{font-size:9px;color:#718580}} .family-metrics b{{font-size:13px;margin-top:2px;white-space:nowrap}} .family-metrics i{{font-size:8px;font-style:normal;color:#7B8E89}} .family-state-note,.family-empty{{padding:8px 10px;border-radius:10px;background:#F2F6F5;color:#718580;font-size:10px}} .family-empty.clear-state{{background:#EAF5F2;color:#176B60}} .family-list{{display:grid;gap:6px}} .family-list-item{{display:flex;align-items:center;gap:8px;padding:8px 9px;border-radius:10px;background:#F2F6F5;min-width:0}} .family-list-item.medication{{justify-content:space-between;background:#EEF4FA}} .family-list-item.medication div{{min-width:0}} .family-list-item.medication b,.family-list-item.medication small{{display:block}} .family-list-item.medication b{{font-size:11px;color:#274D66}} .family-list-item.medication small{{font-size:9px;color:#71818D;margin-top:1px}} .family-list-item.medication em{{font-size:8px;font-style:normal;color:#2F6FEB;background:#fff;padding:3px 6px;border-radius:99px;white-space:nowrap}} .family-list-item.attention{{align-items:flex-start}} .family-list-item.attention i{{width:6px;height:6px;border-radius:50%;background:#2F6FEB;margin-top:6px;flex:none}} .family-list-item.attention.warning i{{background:#D49A30}} .family-list-item.attention.alert i{{background:#D65F45}} .family-list-item.attention p{{margin:0;font-size:10px;color:#49645E}} .family-more{{font-size:9px;color:#718580;padding-left:3px}}
.timeline{{padding-left:6px}} .timeline-item{{display:grid;grid-template-columns:78px 12px 1fr;gap:9px;min-height:55px}} .timeline-item time{{font-size:10px;color:#718580;padding-top:2px;font-variant-numeric:tabular-nums}} .timeline-item>span{{position:relative}} .timeline-item>span:before{{content:"";position:absolute;width:7px;height:7px;border-radius:50%;background:#D76A4A;top:5px;left:2px}} .timeline-item>span:after{{content:"";position:absolute;width:1px;background:#DDE8E5;top:15px;bottom:0;left:5px}} .timeline-item:last-child>span:after{{display:none}} .timeline-item b{{font-size:12px}} .timeline-item small{{margin-left:7px;padding:2px 6px;border-radius:99px;background:#F4E9E5;color:#9B5A47;font-size:8px}} .timeline-item p{{font-size:11px;color:#59726C;margin:1px 0}} .personal-timeline{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:25px}} .personal-timeline .timeline-item{{grid-template-columns:72px 12px 1fr;min-height:52px}} .personal-timeline .metric-event>span:before{{background:#2F6FEB}} .personal-timeline .metric-event small{{background:#E8F0FA;color:#2F6FEB}} .personal-timeline .food-event>span:before{{background:#557FBA}} .personal-timeline .food-event small{{background:#EDF3FA;color:#446A9E}} .personal-timeline .activity-event>span:before{{background:#1E7A6E}} .personal-timeline .activity-event small{{background:#E4F2EE;color:#176B60}} .personal-timeline .sleep-event>span:before{{background:#C8775E}} .personal-timeline .sleep-event small{{background:#F7EAE5;color:#A45C47}}
.footer{{text-align:center;color:#758984;font-size:10px;padding:14px 10px 6px}} .footer b{{display:block;color:#385C55;margin:3px}} @media(max-width:700px){{.container{{padding:12px}}.header{{padding:25px}}.metric-grid,.metric-grid.focused{{grid-template-columns:repeat(2,1fr)}}.wellness-grid,.wellness-grid.focused,.family-grid,.personal-timeline{{grid-template-columns:1fr}}.featured-panel{{grid-column:auto}}.attention-list{{grid-template-columns:1fr}}.compact-attention{{align-items:flex-start;flex-direction:column}}.summary-strip>div{{padding:2px 8px}}.family-metrics{{grid-template-columns:repeat(2,1fr)}}}} @media print{{body{{background:white}}.container{{max-width:none}}section,.header{{box-shadow:none;break-inside:avoid}}}}
</style></head><body><main class="container"><header class="header"><div class="brand"><div class="mark">M</div><h1>{_escape(title)}</h1></div><div class="subtitle">{_escape(subtitle)}</div><div class="privacy">●&nbsp; {_escape(privacy)} · MediWise</div></header>{summary}{content}<footer class="footer"><span>{_escape(generated)}</span><b>MediWise Health Suite</b><span>{_escape(c["disclaimer"])}</span></footer></main></body></html>'''


def generate_report(member_id: str | None = None, owner_id: str | None = None, days: int = 7,
                    locale: str = "zh-CN", view: str = "auto", focus: str = "auto") -> dict:
    """Generate a personal or family card and return its local HTML path."""
    if locale not in COPY:
        return {"status": "error", "message": f"Unsupported locale: {locale}", "supported_locales": list(COPY)}
    if view not in ("auto", "personal", "family"):
        return {"status": "error", "message": f"Unsupported view: {view}", "supported_views": ["auto", "personal", "family"]}
    if focus not in FOCUS_CHOICES:
        return {"status": "error", "message": f"Unsupported focus: {focus}", "supported_focus": list(FOCUS_CHOICES)}
    try:
        days = max(1, min(int(days), 365))
    except (TypeError, ValueError):
        return {"status": "error", "message": f"Invalid days value: {days}"}
    health_db.ensure_db()
    conn = health_db.get_medical_connection()
    try:
        if member_id:
            if not health_db.verify_member_ownership(conn, member_id, owner_id):
                return {"status": "error", "message": f"Member not found or access denied: {member_id}"}
            members = health_db.rows_to_list(conn.execute("SELECT id,name,relation FROM members WHERE id=? AND is_deleted=0", (member_id,)).fetchall())
        elif owner_id:
            members = health_db.rows_to_list(conn.execute("SELECT id,name,relation FROM members WHERE owner_id=? AND is_deleted=0 ORDER BY created_at", (owner_id,)).fetchall())
        else:
            members = health_db.rows_to_list(conn.execute("SELECT id,name,relation FROM members WHERE is_deleted=0 ORDER BY created_at").fetchall())
    finally:
        conn.close()
    if not members:
        return {"status": "error", "message": "No member profiles found"}
    resolved_view = ("personal" if member_id else "family") if view == "auto" else view
    if resolved_view == "personal" and not member_id:
        return {"status": "error", "message": "Personal view requires --member-id"}
    if resolved_view == "family" and member_id:
        return {"status": "error", "message": "Family view does not accept --member-id"}
    if resolved_view == "family" and focus != "auto":
        return {"status": "error", "message": "Family view chooses member priority automatically and does not accept --focus"}

    briefing = health_advisor.get_daily_briefing(member_id if resolved_view == "personal" else None, owner_id)
    lookup = {item.get("member_id"): item for item in briefing.get("briefing", [])}
    all_data = []
    for member in members:
        mid = member["id"]
        member_data = lookup.get(mid, {"member_id": mid, "member_name": member["name"], "relation": member["relation"], "due_reminders": [], "health_tips": []})
        all_data.append({"member": member, "member_data": member_data, "trends": _query_metric_trends(mid, days),
                         "lifestyle": _query_lifestyle_summary(mid, days), "sleep": _query_sleep_summary(mid, days),
                         "care": _query_recent_care(mid, days), "meds": _query_active_medications(mid),
                         "reminders": _query_active_reminders(mid)})

    # health_advisor's reminder total is global. Recalculate card totals from
    # the selected member set so a personal card never inherits family tasks.
    card_briefing = dict(briefing)
    tips = [tip for data in all_data for tip in data["member_data"].get("health_tips", [])]
    card_briefing["total_alerts"] = sum(1 for tip in tips if tip.get("severity") == "alert")
    card_briefing["total_warnings"] = (
        sum(1 for tip in tips if tip.get("severity") == "warning") +
        sum(_care_abnormal_count(data["care"]) for data in all_data)
    )
    card_briefing["total_due_reminders"] = sum(len(data["member_data"].get("due_reminders", [])) for data in all_data)

    c = COPY[locale]
    end = briefing.get("date") or datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days-1)).strftime("%Y-%m-%d")
    if resolved_view == "personal":
        data = all_data[0]
        layout_profile = _personal_layout(data["member_data"], data["trends"], data["lifestyle"],
                                          data["sleep"], data["care"], data["meds"], focus)
        title = c["title"]
        subtitle = f'{_member_label(data["member"], locale)} · {c["period"].format(start=start, end=end)} · {c["last_days"].format(days=days)}'
        has_priority_items = any(card_briefing.get(key, 0) for key in ("total_alerts", "total_warnings", "total_due_reminders"))
        summary = _summary_strip(card_briefing, locale) if has_priority_items else ""
        content = _personal_content(data["member"], data["member_data"], data["trends"], data["lifestyle"],
                                    data["sleep"], data["care"], data["meds"], locale, layout_profile)
        privacy = c["local_profile"]
    else:
        all_data.sort(key=_family_rank, reverse=True)
        ranked = [_family_rank(data) for data in all_data]
        featured_member = all_data[0]["member"]["id"] if ranked and any(ranked[0][:3]) else None
        layout_profile = {
            "focus": "attention" if featured_member else "status",
            "member_order": [data["member"]["id"] for data in all_data],
            "featured_member": featured_member,
        }
        title = c["family_title"]
        subtitle = f'{c["period"].format(start=start, end=end)} · {c["last_days"].format(days=days)} · {c["members"].format(count=len(all_data))}'
        summary = _summary_strip(card_briefing, locale, all_data)
        content = _family_content(all_data, locale, featured_member)
        privacy = c["local_family"]
    html = _render_html(title, subtitle, privacy, summary, content, locale)
    reports_dir = os.path.join(DATA_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    locale_slug = "en" if locale == "en-US" else "zh"
    filename = (f'health_card_{resolved_view}_{locale_slug}_{end}' +
                (f'_{member_id}' if member_id else '') +
                (f'_{focus}' if focus != "auto" else '') + '.html')
    path = os.path.join(reports_dir, filename)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
    try:
        import daily_snapshot
        for member in members:
            daily_snapshot.save_snapshot(member["id"], owner_id, briefing)
    except Exception as exc:
        LOG.warning("daily_snapshot save failed: %s", exc)
    return {"status": "ok", "report_path": path, "file_size": os.path.getsize(path), "date": end,
            "member_count": len(members), "days": days, "locale": locale, "view": resolved_view,
            "layout_profile": layout_profile}


def _parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--member-id")
    parser.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--locale", choices=sorted(COPY), default="zh-CN")
    parser.add_argument("--view", choices=("auto", "personal", "family"), default="auto")
    parser.add_argument("--focus", choices=FOCUS_CHOICES, default="auto")
    if command == "screenshot":
        parser.add_argument("--width", type=int, default=1040)
    return parser


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("generate", "screenshot"):
        health_db.output_json({"error": "Usage: briefing_report.py generate|screenshot [options]"})
        return
    command = sys.argv[1]
    args = _parser(command).parse_args(sys.argv[2:])
    report = generate_report(args.member_id, args.owner_id, args.days, args.locale, args.view, args.focus)
    if command == "generate" or report.get("status") != "ok":
        health_db.output_json(report)
        return
    import html_screenshot
    png = html_screenshot.screenshot(report["report_path"], width=args.width)
    png["html_path"] = report["report_path"]
    png.update({key: report[key] for key in ("locale", "view", "member_count", "days")})
    png["layout_profile"] = report["layout_profile"]
    health_db.output_json(png)


if __name__ == "__main__":
    main()
