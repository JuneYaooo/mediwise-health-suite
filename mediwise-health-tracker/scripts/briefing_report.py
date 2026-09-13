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
import math
import os
import sys
from datetime import datetime, timedelta

import health_advisor
import health_db
from config import DATA_DIR
from metric_utils import resolve_age


LOG = logging.getLogger(__name__)

COPY = {
    "zh-CN": {
        "lang": "zh-CN", "title": "健康卡片", "family_title": "家庭健康卡片",
        "last_days": "最近 {days} 天", "period": "{start} 至 {end}",
        "local_profile": "个人本地档案", "local_family": "本地家庭档案",
        "members": "{count} 位成员", "attention_people": "{count} 人需要关注",
        "pending": "{count} 项待办", "attention": "需要关注", "all_clear": "未发现告警或待办提醒",
        "alerts": "{count} 项警告", "warnings": "{count} 项提醒", "todos": "{count} 项待处理提醒",
        "metrics": "指标趋势", "records": "{count} 条", "latest": "最近",
        "source": "来源", "systolic": "收缩压", "diastolic": "舒张压",
        "fasting": "空腹", "postprandial": "餐后", "random": "随机", "value": "测量值",
        "undrawn": "另有 {count} 条记录未绘入图表",
        "no_metrics": "所选时间范围内暂无可展示的健康指标。",
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
        "snapshot_title": "病情速览", "abnormal_reported": "报告标记的异常",
        "abnormal_threshold": "阈值告警", "history": "既往史", "allergies_label": "过敏史",
        "reference_label": "参考", "age_exact": "{age} 岁", "age_approx": "{age} 岁（{date} 记录）",
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
        "chief_complaint": "主诉：{value}",
        "unknown": "未填写", "day": "天",
    },
    "en-US": {
        "lang": "en", "title": "Health Card", "family_title": "Family Health Card",
        "last_days": "Last {days} days", "period": "{start} to {end}",
        "local_profile": "Private local profile", "local_family": "Private local family record",
        "members": "{count} members", "attention_people": "{count} need attention",
        "pending": "{count} pending", "attention": "Needs attention", "all_clear": "No alerts or pending reminders found",
        "alerts": "{count} alerts", "warnings": "{count} notices", "todos": "{count} pending reminders",
        "metrics": "Metric trends", "records": "{count} records", "latest": "Latest",
        "source": "Source", "systolic": "Systolic", "diastolic": "Diastolic",
        "fasting": "Fasting", "postprandial": "After meal", "random": "Random", "value": "Measured",
        "undrawn": "{count} more records are not charted",
        "no_metrics": "No supported health metrics were recorded in this period.",
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
        "snapshot_title": "Clinical snapshot", "abnormal_reported": "Flags printed on the report",
        "abnormal_threshold": "Configured-range alerts", "history": "Medical history", "allergies_label": "Allergies",
        "reference_label": "ref.", "age_exact": "{age} years old", "age_approx": "{age} years old (recorded {date})",
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
        "chief_complaint": "Chief complaint: {value}",
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
# Recorded sex is either the Chinese value the intake agent writes or an English
# one; anything else is shown exactly as recorded rather than guessed at.
GENDERS = {
    "zh-CN": {"male": "男", "m": "男", "男": "男", "female": "女", "f": "女", "女": "女"},
    "en-US": {"male": "Male", "m": "Male", "男": "Male", "female": "Female", "f": "Female", "女": "Female"},
}
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


def _identity_text(member: dict, locale: str) -> str:
    """Describe sex and age for the card header.

    Age comes from a birth date whenever one is on file. A recorded age is used
    only when there is no birth date, and is shown with the date it was taken
    because a bare age goes stale. With neither recorded the age is left out
    rather than guessed, and the birth date is never back-derived from an age.
    """
    c = COPY[locale]
    parts = []
    gender = str(member.get("gender") or "").strip()
    if gender:
        parts.append(GENDERS[locale].get(gender.lower(), gender))
    age, approximate = resolve_age(member.get("birth_date"), member.get("age_years"),
                                   member.get("age_recorded_at"))
    if age is not None:
        if approximate and member.get("age_recorded_at"):
            parts.append(c["age_approx"].format(age=age, date=str(member["age_recorded_at"])[:10]))
        else:
            parts.append(c["age_exact"].format(age=age))
    return " · ".join(parts)


def _source(value: str | None, locale: str) -> str:
    value = value or "manual"
    return SOURCES[locale].get(value, value.replace("_", " ").title() if locale == "en-US" else value.replace("_", " "))


# The measurement-gap label is the one advisor string that carries a number, so
# its two fixed halves are named rather than left as slice offsets.
GAP_TIP_SUFFIX = " 天未测量"


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
        if value.startswith(f"{chinese}已 ") and value.endswith(GAP_TIP_SUFFIX):
            # Read the count from between the fixed halves rather than by an
            # offset into the number: a -6 slice dropped the last digit of a
            # two-digit count and printed "for 1 days" for ten days.
            count = value[len(chinese) + 2:-len(GAP_TIP_SUFFIX)].strip()
            return f"No {english} measurement for {count} {'day' if count == '1' else 'days'}"
    return value


def _query_metric_trends(member_id: str, days: int = 30) -> dict:
    conn = health_db.get_medical_connection()
    cutoff = (datetime.now() - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
    trends = {}
    try:
        for metric_type in ("blood_pressure", "blood_sugar", "heart_rate", "weight", "temperature", "blood_oxygen"):
            rows = conn.execute(
                """SELECT measured_at, value, source, related_visit_id FROM health_metrics
                   WHERE member_id=? AND metric_type=? AND is_deleted=0 AND measured_at>=?
                   ORDER BY measured_at""", (member_id, metric_type, cutoff)).fetchall()
            points = []
            for row in rows:
                raw = row["value"]
                try:
                    parsed = json.loads(raw) if isinstance(raw, str) else raw
                except (json.JSONDecodeError, TypeError):
                    parsed = raw
                # The visit link travels with the point: the timeline attributes a
                # measurement to a visit only through this explicit foreign key.
                if isinstance(parsed, dict):
                    point = {"date": row["measured_at"][:10], "source": row["source"] or "manual",
                             "metric_type": metric_type, "related_visit_id": row["related_visit_id"],
                             **parsed}
                else:
                    try:
                        point = {"date": row["measured_at"][:10], "source": row["source"] or "manual",
                                 "metric_type": metric_type, "related_visit_id": row["related_visit_id"],
                                 "value": float(parsed)}
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
              "recent_diet": None, "recent_exercise": [], "diet_records": [],
              "exercise_records": [], "step_records": []}
    conn = health_db.get_lifestyle_connection()
    try:
        row = conn.execute(
            """SELECT COUNT(DISTINCT meal_date) AS days, SUM(total_calories) AS calories,
                      SUM(total_protein) AS protein, SUM(total_fat) AS fat,
                      SUM(total_carbs) AS carbs, SUM(total_fiber) AS fiber,
                      MAX(CASE WHEN total_calories IS NULL THEN 1 ELSE 0 END) AS calories_unknown,
                      MAX(CASE WHEN total_protein  IS NULL THEN 1 ELSE 0 END) AS protein_unknown,
                      MAX(CASE WHEN total_fat      IS NULL THEN 1 ELSE 0 END) AS fat_unknown,
                      MAX(CASE WHEN total_carbs    IS NULL THEN 1 ELSE 0 END) AS carbs_unknown,
                      MAX(CASE WHEN total_fiber    IS NULL THEN 1 ELSE 0 END) AS fiber_unknown,
                      COUNT(DISTINCT CASE WHEN total_calories IS NOT NULL THEN meal_date END) AS calories_days,
                      COUNT(DISTINCT CASE WHEN total_protein  IS NOT NULL THEN meal_date END) AS protein_days,
                      COUNT(DISTINCT CASE WHEN total_fat      IS NOT NULL THEN meal_date END) AS fat_days,
                      COUNT(DISTINCT CASE WHEN total_carbs    IS NOT NULL THEN meal_date END) AS carbs_days,
                      COUNT(DISTINCT CASE WHEN total_fiber    IS NOT NULL THEN meal_date END) AS fiber_days
               FROM diet_records WHERE member_id=? AND is_deleted=0 AND meal_date>=?""", (member_id, cutoff)).fetchone()
        # diet_days 保持"有记录即计"的原义：它门控饮食段落是否出现
        # （_has_lifestyle_data / _has_timeline_data），改义会让饮食段落静默消失。
        diet_days = int(row["days"] or 0)
        result["diet_days"] = diet_days
        nutrition_days = int(row["calories_days"] or 0)
        result["diet_nutrition_days"] = nutrition_days
        result["diet_days_unresolved"] = diet_days - nutrition_days
        if diet_days:
            # 日均逐字段用自己的"已解析天数"作分母：条目没给 fiber 是常态，
            # 用统一分母必然对某一项说谎。未知一律为 None，由渲染层印成 —。
            result["diet"] = {}
            for key in ("calories", "protein", "fat", "carbs", "fiber"):
                field_days = int(row[f"{key}_days"] or 0)
                result["diet"][key] = (
                    None if row[f"{key}_unknown"] or not field_days
                    else float(row[key]) / field_days
                )
            recent_diet = conn.execute(
                """SELECT meal_date, SUM(total_calories) AS calories, SUM(total_protein) AS protein,
                          SUM(total_fat) AS fat, SUM(total_carbs) AS carbs, SUM(total_fiber) AS fiber
                   FROM diet_records WHERE member_id=? AND is_deleted=0 AND meal_date>=?
                   GROUP BY meal_date ORDER BY meal_date DESC LIMIT 1""", (member_id, cutoff)).fetchone()
            result["recent_diet"] = {key: recent_diet[key] for key in recent_diet.keys()} if recent_diet else None
        result["diet_records"] = health_db.rows_to_list(conn.execute(
            """SELECT meal_date,total_calories,total_protein,total_fat,total_carbs,total_fiber
               FROM diet_records WHERE member_id=? AND is_deleted=0 AND meal_date>=?
               ORDER BY meal_date, meal_time""", (member_id, cutoff)).fetchall())
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
        result["exercise_records"] = health_db.rows_to_list(conn.execute(
            """SELECT exercise_date, exercise_type, exercise_name, duration, calories_burned, intensity
               FROM exercise_records WHERE member_id=? AND is_deleted=0 AND exercise_date>=?
               ORDER BY exercise_date, exercise_time""", (member_id, cutoff)).fetchall())
    finally:
        conn.close()

    conn = health_db.get_medical_connection()
    try:
        rows = conn.execute(
            """SELECT metric_type, measured_at, value, source FROM health_metrics WHERE member_id=? AND metric_type='steps'
               AND is_deleted=0 AND measured_at>=? ORDER BY measured_at""", (member_id, cutoff)).fetchall()
        daily = {}
        for row in rows:
            result["step_records"].append({key: row[key] for key in row.keys()})
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
        return {"count": 0, "daily_records": []}
    def average(key):
        values = [float(item[key]) for item in records if item.get(key) is not None]
        return sum(values) / len(values) if values else None
    return {"count": len(records), "avg_duration": average("duration_min"), "avg_score": average("score"),
            "latest_deep": records[-1].get("deep_min"), "latest_rem": records[-1].get("rem_min"),
            "latest_duration": records[-1].get("duration_min"), "latest_score": records[-1].get("score"),
            "latest_date": records[-1]["date"], "daily_records": records}


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
    # A bare dash stands for "nothing printed here" on the sheet, so it is
    # dropped rather than transcribed as a unit or a flag.
    name = _clean_lab_field(item.get("name") or item.get("item_name") or item.get("test_name") or
                            item.get("indicator"))
    value = item.get("value")
    unit = _clean_lab_field(item.get("unit"))
    flag = _clean_lab_field(item.get("flag") or item.get("status"))
    pieces = [name] if name else []
    if value not in (None, ""):
        pieces.append(f"{value} {unit}".strip())
    if flag:
        pieces.append(str(flag))
    return " · ".join(pieces)


def _lab_abnormal_details(lab: dict, limit: int | None = 2) -> tuple[int, list[str]]:
    """Count flagged items and return their labels, truncated to fill one line.

    `limit=None` returns every label, for callers that render the full picture
    rather than a summary line.
    """
    abnormal = [item for item in _lab_items(lab.get("items")) if _is_abnormal(item)]
    labels = [_abnormal_label(item) for item in abnormal if _abnormal_label(item)]
    return len(abnormal), labels if limit is None else labels[:limit]


def _query_recent_care(member_id: str, days: int, limit: int = 3) -> dict:
    cutoff = (datetime.now() - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
    conn = health_db.get_medical_connection()
    try:
        # Only structured columns are loaded. The card renders extracted fields, so
        # `visits.summary` and `imaging_results.findings` — the pasted source
        # narrative — are deliberately not selected: a field that is never read
        # cannot be printed again by a later edit to the template.
        visits = health_db.rows_to_list(conn.execute(
            """SELECT id, visit_date, visit_type, hospital, department, chief_complaint, diagnosis FROM visits
               WHERE member_id=? AND is_deleted=0 AND visit_date>=? ORDER BY visit_date DESC LIMIT ?""",
            (member_id, cutoff, limit)).fetchall())
        labs = health_db.rows_to_list(conn.execute(
            """SELECT test_date, test_name, items FROM lab_results WHERE member_id=? AND is_deleted=0
               AND test_date>=? ORDER BY test_date DESC LIMIT ?""", (member_id, cutoff, limit)).fetchall())
        all_labs = health_db.rows_to_list(conn.execute(
            """SELECT test_date, test_name, items FROM lab_results WHERE member_id=? AND is_deleted=0
               AND test_date>=? ORDER BY test_date DESC""", (member_id, cutoff)).fetchall())
        imaging = health_db.rows_to_list(conn.execute(
            """SELECT exam_date, exam_name, conclusion FROM imaging_results WHERE member_id=?
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


# Lab sheets print a bare dash when a field carries no unit or no range.
_EMPTY_MARKERS = {"-", "—", "–", "－", "~", "/"}


def _clean_lab_field(value) -> str:
    """Normalize a lab field, treating dash-only placeholders as absent."""
    text = str(value or "").strip()
    return "" if text in _EMPTY_MARKERS else text


def _abnormal_item(item: dict) -> dict:
    """Normalize one flagged lab item, carrying the printed values through verbatim.

    Nothing is recomputed here: the name, value, flag, and reference range are the
    ones printed on the report. Only dash placeholders are dropped so the card
    does not render an empty unit.
    """
    return {
        "name": _clean_lab_field(item.get("name") or item.get("item_name") or
                                 item.get("test_name") or item.get("indicator")),
        "value": item.get("value"),
        "unit": _clean_lab_field(item.get("unit")),
        "reference": _clean_lab_field(item.get("reference") or item.get("reference_range") or
                                      item.get("ref_range") or item.get("normal_range")),
        "flag": _clean_lab_field(item.get("flag") or item.get("status")),
    }


def _abnormal_report_groups(labs: list[dict]) -> list[dict]:
    """Group every flagged lab item by the report that printed it.

    Items are never dropped or deduplicated across reports: the same analyte
    measured twice is a trend, not a repeat.
    """
    groups = []
    for lab in labs:
        items = [_abnormal_item(item) for item in _lab_items(lab.get("items")) if _is_abnormal(item)]
        items = [item for item in items if item["name"] or item["value"] not in (None, "")]
        if items:
            groups.append({
                "test_date": str(lab.get("test_date") or "")[:10],
                "test_name": lab.get("test_name") or "",
                "items": items,
            })
    return groups


def _collapse_diagnoses(visits: list[dict]) -> list[dict]:
    """Return one entry per distinct diagnosis phrase, newest first.

    A visit's diagnosis field can hold several diagnoses separated by a
    semicolon; each phrase is kept exactly as written. Commas are never used as
    separators — they divide clauses inside a single diagnosis such as
    "原发性高血压（3级，极高危）". Repeats collapse onto their most recent
    mention so a chronic condition does not fill the card with its history.
    """
    collapsed = {}
    for visit in visits:
        raw = str(visit.get("diagnosis") or "")
        for phrase in raw.replace("；", ";").split(";"):
            phrase = phrase.strip()
            if not phrase or phrase in collapsed:
                continue
            collapsed[phrase] = {
                "diagnosis": phrase,
                "visit_date": str(visit.get("visit_date") or "")[:10],
                "hospital": visit.get("hospital"),
                "department": visit.get("department"),
                "visit_type": visit.get("visit_type"),
            }
    return list(collapsed.values())


def _query_clinical_snapshot(member_id: str) -> dict:
    """Read a member's standing clinical picture, ignoring the report's day window.

    Chronic diagnoses and older flagged labs stay clinically relevant long after
    the "recent records" window closes, so this path queries all history and
    leaves truncation to the renderer. Values are read back exactly as recorded.
    """
    conn = health_db.get_medical_connection()
    try:
        visits = health_db.rows_to_list(conn.execute(
            """SELECT visit_date, visit_type, hospital, department, diagnosis FROM visits
               WHERE member_id=? AND is_deleted=0
               AND diagnosis IS NOT NULL AND TRIM(diagnosis)<>''
               ORDER BY visit_date DESC""", (member_id,)).fetchall())
        labs = health_db.rows_to_list(conn.execute(
            """SELECT test_date, test_name, items FROM lab_results WHERE member_id=? AND is_deleted=0
               ORDER BY test_date DESC""", (member_id,)).fetchall())
    finally:
        conn.close()
    return {
        "diagnoses": _collapse_diagnoses(visits),
        "abnormal_reports": _abnormal_report_groups(labs),
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


# A trend needs a longer window than the card's own. The card answers "what has
# been happening lately" and its `--days` window bounds every other panel; a
# chart drawn inside that window would flatten into the last few days of a
# longer series and read as noise. Charts therefore look back a fixed 90 days
# (never less than the card window) and print the span actually drawn.
TREND_DAYS = 90

# Trend charts are drawn at two fixed widths so the wide lead chart and the
# two-up charts under it share one geometry: same margins, same type sizes,
# same axis rules. Every coordinate comes from the recorded numbers, so the
# same records always draw the same picture.
CHART_WIDE, CHART_NARROW = 960, 460
CHART_HEIGHT = 250
CHART_LEFT, CHART_RIGHT, CHART_TOP, CHART_BOTTOM = 54, 20, 30, 36

# Series colours, in draw order. All cool blues and teals from the card's own
# palette: a series must never be painted in --coral, the tone the count strip
# and the timeline use for "needs attention", because then the colour of a line
# would read as a verdict on it. Which series a value belongs to is the only
# thing a colour may say here.
SERIES_COLORS = ("#246BCE", "#167A9A", "#557FBA", "#164F91")

# Blood sugar is recorded per context, and a reading carries only its own
# context key -- a 餐后 record holds `postprandial` and no `value` at all. Each
# context is therefore its own line rather than one line built from whichever
# key happens to be present, which would drop records the card still counts.
BLOOD_SUGAR_CONTEXTS = ("fasting", "postprandial", "random", "value")

# A 90-day window of wearable data can hold thousands of samples (Apple Health
# exports heart rate every few minutes). Past this many records the chart is
# drawn from an even sample of them, and the card states how many were left out.
MAX_CHART_POINTS = 180
MAX_CHART_DOTS = 24


def _chart_date(value):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _is_number(value) -> bool:
    if value is None:
        return False
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _metric_series(metric_type: str, points: list[dict]) -> list[tuple[str | None, list]]:
    """The numeric series a metric actually holds, in a fixed order."""
    if metric_type == "blood_pressure":
        keys = ("systolic", "diastolic")
    elif metric_type == "blood_sugar":
        keys = tuple(key for key in BLOOD_SUGAR_CONTEXTS
                     if any(_is_number(point.get(key)) for point in points))
    else:
        keys = (None,)
    return [(key, [point.get(key) if key else _metric_number(point, metric_type) for point in points])
            for key in keys]


def _chart_window_days(days: int) -> int:
    """Days the metric charts read: never shorter than the card's own window."""
    return max(TREND_DAYS, int(days))


def _thin(points: list[dict], limit: int = MAX_CHART_POINTS) -> list[dict]:
    """Evenly sample a long series for drawing, keeping the first and last record.

    Every drawn point is still a real record on its real date -- a selection of
    them, never a computed value -- and the first and last survive so the span
    the chart states stays the span the window holds. Whatever is left out is
    counted on the card rather than dropped quietly.
    """
    if len(points) <= limit:
        return list(points)
    # One of the limit is held back for the newest record, so a series that
    # does not divide evenly still ends on the last reading rather than near it.
    drawn = points[::math.ceil((len(points) - 1) / (limit - 1))]
    if drawn[-1] is not points[-1]:
        drawn.append(points[-1])
    return drawn


def _chart_numbers(series: list[tuple[str | None, list]]) -> list[float]:
    """Every value that can be plotted, ignoring blanks and non-numbers."""
    numbers = []
    for _, values in series:
        for value in values:
            if _is_number(value):
                numbers.append(float(value))
    return numbers


def _metric_digits(metric_type: str) -> int:
    """Decimals a metric is printed with, shared by the chart and the timeline."""
    return 1 if metric_type in ("blood_sugar", "weight", "temperature") else 0


def _tick_digits(step: float) -> int:
    """Decimals a tick label needs to state its gridline exactly.

    A 0.25 step needs two: printed at one digit it would put "6.2" on a line
    drawn at 6.25, and the label would disagree with the chart.
    """
    digits = 0
    while digits < 4 and abs(round(step, digits) - step) > 1e-9:
        digits += 1
    return digits


def _nice_step(raw: float) -> float:
    """Round a tick interval up to 1/2/2.5/5/10 times a power of ten."""
    if raw <= 0:
        return 1.0
    magnitude = 10 ** math.floor(math.log10(raw))
    rungs = (1, 2, 2.5, 5, 10)
    if _tick_digits(2.5 * magnitude) > 1:
        # Below a magnitude of 1 the 2.5 rung lands on quarter steps, which no
        # one-decimal label can state, so that rung is skipped.
        rungs = (1, 2, 5, 10)
    for multiplier in rungs:
        if multiplier * magnitude >= raw:
            return multiplier * magnitude
    return 10 * magnitude


def _axis_ticks(numbers: list[float]) -> tuple[list[float], float]:
    """Round the recorded range out to whole ticks.

    The axis is a scale for the drawn points and nothing else: no reference
    band, no shaded "normal" zone, no colour that would read as a verdict.
    """
    if not numbers:
        return [0.0, 1.0], 1.0
    low, high = min(numbers), max(numbers)
    span = high - low or max(abs(high) * 0.2, 2.0)
    pad = span * 0.12
    step = _nice_step((span + 2 * pad) / 5)
    while (span + 2 * pad) / step > 6:
        step *= 2
    ticks, value = [], math.floor((low - pad) / step) * step
    last = math.ceil((high + pad) / step) * step
    while value <= last + step * 1e-6:
        ticks.append(round(value, 6))
        value += step
    return ticks, step


def _chart_svg(metric_type: str, points: list[dict], series: list, locale: str, wide: bool) -> str:
    width = CHART_WIDE if wide else CHART_NARROW
    right, bottom = width - CHART_RIGHT, CHART_HEIGHT - CHART_BOTTOM
    ticks, step = _axis_ticks(_chart_numbers(series))
    top_tick, bottom_tick = ticks[-1], ticks[0]

    def y_position(value):
        return CHART_TOP + (top_tick - float(value)) * (bottom - CHART_TOP) / (top_tick - bottom_tick)

    dates = [_chart_date(point.get("date")) for point in points]
    origin = next((value for value in dates if value), None)
    spaced = origin is not None and all(value is not None for value in dates) and any(value != origin for value in dates)
    if spaced:
        offsets = [(value - origin).days for value in dates]
        span = float(max(offsets))
        xs = [CHART_LEFT + (right - CHART_LEFT) * offset / span for offset in offsets]
    else:
        # Missing or identical dates cannot space the points, so they are laid
        # out in record order rather than pretending to a time axis.
        span = float(max(len(points) - 1, 1))
        xs = [CHART_LEFT + (right - CHART_LEFT) * index / span for index in range(len(points))]

    parts = []
    for tick in ticks[1:]:
        y = y_position(tick)
        parts.append(f'<line x1="{CHART_LEFT}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#E3EDF7" stroke-width="1"/>')
        parts.append(f'<text x="{CHART_LEFT - 9}" y="{y + 4:.1f}" text-anchor="end" fill="#587087" font-size="11">'
                     f'{_escape(_fmt_number(tick, _tick_digits(step)))}</text>')
    parts.append(f'<line x1="{CHART_LEFT}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#C9DBEB" stroke-width="1.5"/>')

    label_all = len(points) <= 6
    # Past a couple of dozen points the dots run into each other and the line
    # already carries the shape, so only the last one is kept to anchor its label.
    dot_all = len(points) <= MAX_CHART_DOTS
    for series_index, (key, values) in enumerate(series):
        color = SERIES_COLORS[series_index % len(SERIES_COLORS)]
        valid = [(index, float(value)) for index, value in enumerate(values) if _is_number(value)]
        if not valid:
            continue
        if len(valid) >= 2:
            line = " ".join(f"{xs[index]:.1f},{y_position(value):.1f}" for index, value in valid)
            parts.append(f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2.5" '
                         f'stroke-linecap="round" stroke-linejoin="round"/>')
        labelled = {valid[0][0], valid[-1][0]}
        for index, value in valid:
            x, y = xs[index], y_position(value)
            if dot_all or index == valid[-1][0]:
                parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.6" fill="{color}" stroke="#FFFFFF" stroke-width="1.6"/>')
            if not (label_all or index in labelled):
                continue
            anchor = "start" if x < CHART_LEFT + 8 else ("end" if x > right - 8 else "middle")
            text_y = y + (-10 if series_index % 2 == 0 else 18)
            if text_y < 12:
                text_y = y + 18
            elif text_y > CHART_HEIGHT - 4:
                text_y = y - 10
            parts.append(f'<text x="{x:.1f}" y="{text_y:.1f}" text-anchor="{anchor}" fill="#15324B" '
                         f'font-size="12" font-weight="600">{_escape(_fmt_number(value, _metric_digits(metric_type)))}</text>')
    if all(value is not None for value in dates):
        if len(set(dates)) == 1:
            # Every reading shares one date, so the axis carries that date once
            # instead of printing the same label under each point.
            parts.append(f'<text x="{(CHART_LEFT + right) / 2:.1f}" y="{CHART_HEIGHT - 12}" text-anchor="middle" '
                         f'fill="#587087" font-size="11">{_escape(dates[0].strftime("%m-%d"))}</text>')
        else:
            indexes = [0, len(points) // 2, len(points) - 1] if len(points) >= 3 else [0, len(points) - 1]
            for index in dict.fromkeys(indexes):
                anchor = "start" if index == 0 else ("end" if index == len(points) - 1 else "middle")
                parts.append(f'<text x="{xs[index]:.1f}" y="{CHART_HEIGHT - 12}" text-anchor="{anchor}" '
                             f'fill="#587087" font-size="11">{_escape(dates[index].strftime("%m-%d"))}</text>')

    label = _escape(METRIC_NAMES[locale].get(metric_type, metric_type))
    return (f'<svg class="chart" viewBox="0 0 {width} {CHART_HEIGHT}" role="img" aria-label="{label}">'
            f'{"".join(parts)}</svg>')


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
                     care: dict, meds: list[dict], requested_focus: str = "auto",
                     chart_trends: dict | None = None, chart_days: int = TREND_DAYS) -> dict:
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
        # The section draws the chart series, so it is available whenever those
        # exist -- including when every record in it falls outside the card's own
        # window. Coverage above still counts the card window only, so the layout
        # score is unchanged.
        "metrics": bool(chart_trends if chart_trends is not None else trends),
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
        # The metric section reads its own, longer window than the rest of the
        # card, so the profile states which one so it can be checked.
        "metrics_window_days": chart_days,
        "coverage": coverage,
        "risk": risk,
        "reasons": reasons,
        "section_order": section_order,
        "metric_focus": _metric_types_from_tips(member_data, trends),
        "lifestyle_focus": lifestyle_focus,
    }


def _metric_chart(metric_type: str, records: list[dict], drawn: list[dict], locale: str, wide: bool) -> str:
    """One metric's recorded series, drawn with its own axis and value labels."""
    c = COPY[locale]
    name = _escape(METRIC_NAMES[locale].get(metric_type, metric_type))
    unit = _escape(METRIC_UNITS.get(metric_type, ""))
    series = _metric_series(metric_type, drawn)
    # A legend only where a colour has to be told apart; one line needs none,
    # the header already names the metric.
    legend = ""
    if len(series) >= 2:
        legend = '<span class="trend-legend">' + "".join(
            f'<i style="background:{SERIES_COLORS[index % len(SERIES_COLORS)]}"></i>'
            f'{_escape(c[key] if key else METRIC_NAMES[locale].get(metric_type, metric_type))}'
            for index, (key, _) in enumerate(series)) + '</span>'
    span = c["period"].format(start=_escape(str(records[0].get("date") or "")[:10]),
                              end=_escape(str(records[-1].get("date") or "")[:10]))
    count = _count_phrase(locale, len(records), "条", "record")
    undrawn = ""
    if len(records) > len(drawn):
        undrawn = f'<span>{_escape(c["undrawn"].format(count=len(records) - len(drawn)))}</span>'
    source = _escape(_source(records[-1].get("source"), locale))
    return (f'<article class="trend-chart{" wide" if wide else ""}">'
            f'<div class="trend-head"><b>{name}</b><small>{unit}</small>{legend}'
            f'<span class="trend-span">{count} · {span}</span></div>'
            f'{_chart_svg(metric_type, drawn, series, locale, wide)}'
            f'<div class="trend-source"><span>{c["source"]}: {source}</span>{undrawn}</div></article>')


def _metric_single(metric_type: str, points: list[dict], locale: str) -> str:
    """No line can be drawn from what is recorded, so its value is printed instead."""
    c = COPY[locale]
    latest = points[-1]
    name = _escape(METRIC_NAMES[locale].get(metric_type, metric_type))
    # The same formatter the timeline uses, so the two never disagree.
    value = _escape(_timeline_metric_value(metric_type, latest))
    meta = " · ".join([
        _count_phrase(locale, len(points), "条", "record"),
        f'{c["latest"]} {_escape(str(latest.get("date") or "")[:10])}',
        f'{c["source"]}: {_escape(_source(latest.get("source"), locale))}',
    ])
    return (f'<div class="trend-single"><b>{name}</b><span class="trend-value">{value}</span>'
            f'<span class="trend-meta">{meta}</span></div>')


def _metric_trend_section(chart_trends: dict, locale: str, featured_types: list[str] | None = None) -> str:
    """Draw every metric's records: a trend when there is a line, the latest value when there is not."""
    c = COPY[locale]
    featured_types = featured_types or []
    ordered = sorted(chart_trends.items(), key=lambda item: (item[0] not in featured_types, -len(item[1])))
    blocks, wide = [], True
    for metric_type, points in ordered:
        drawn = _thin(points)
        if len(drawn) >= 2 and len(_chart_numbers(_metric_series(metric_type, drawn))) >= 2:
            # The first chart that can be drawn carries the full width; the rest
            # share a row. Reading the flag, not the position, keeps the wide
            # slot from landing on a metric that turned out to be a value line.
            blocks.append(_metric_chart(metric_type, points, drawn, locale, wide))
            wide = False
        else:
            blocks.append(_metric_single(metric_type, points, locale))
    if not blocks:
        return f'<div class="empty">{c["no_metrics"]}</div>'
    return f'<div class="trend-grid">{"".join(blocks)}</div>'


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
          <div class="muted">{c["daily_average"]} · {_count_phrase(locale, lifestyle.get("diet_nutrition_days", 0), "个营养记录日", "nutrition log day")}</div>
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
        value = _fmt_number(_metric_number(point, metric_type), _metric_digits(metric_type))
    return f'{value} {METRIC_UNITS.get(metric_type, "")}'.strip()


def _personal_timeline(trends: dict, lifestyle: dict, sleep: dict, care: dict, locale: str,
                       section_number: str = "03", featured_section: bool = False) -> str:
    """Build a compact chronology spanning care and everyday health records."""
    c = COPY[locale]
    events = []

    # A measurement belongs to a visit only through its own `related_visit_id`.
    # Nothing is inferred from dates: a home reading taken on a clinic day is a
    # different measurement, not "that visit's" value.
    visit_points = {item.get("id"): {} for item in care["visits"] if item.get("id")}
    for metric_type, points in trends.items():
        for index, point in enumerate(points):
            visit_id = point.get("related_visit_id")
            if visit_id in visit_points:
                visit_points[visit_id][metric_type] = index

    for item in care["visits"]:
        visit_id = item.get("id")
        title = item.get("diagnosis") or item.get("department") or item.get("visit_type") or c["unknown"]
        parts = [item.get("visit_type"), item.get("hospital"), item.get("department")]
        if item.get("chief_complaint"):
            parts.append(c["chief_complaint"].format(value=item["chief_complaint"]))
        # Points run oldest to newest, so the last one linked to this visit is
        # the one shown — the same rule the metric event below already uses.
        covered = set()
        for metric_type, points in trends.items():
            index = visit_points.get(visit_id, {}).get(metric_type)
            if index is None:
                continue
            parts.append(f'{METRIC_NAMES[locale].get(metric_type, metric_type)} {_timeline_metric_value(metric_type, points[index])}')
            covered.add((metric_type, index))
        # With no diagnosis the title is already the department or visit type.
        detail = " · ".join(dict.fromkeys(part for part in parts if part and part != title))
        events.append({"date": item.get("visit_date", "")[:10], "priority": 0, "tone": "care-event",
                       "kind": c["visit_event"], "title": title, "detail": detail or c["unknown"],
                       "covers": covered})
    for item in care["labs"]:
        count, labels = _lab_abnormal_details(item, limit=None)
        detail = c["abnormal"].format(count=count) if count else c["no_flagged"]
        if labels:
            detail += " · " + "; ".join(labels)
        events.append({"date": item.get("test_date", "")[:10], "priority": 0, "tone": "care-event",
                       "kind": c["lab_event"], "title": item.get("test_name") or c["unknown"], "detail": detail})
    for item in care["imaging"]:
        events.append({"date": item.get("exam_date", "")[:10], "priority": 0, "tone": "care-event",
                       "kind": c["imaging_event"], "title": item.get("exam_name") or c["unknown"],
                       "detail": item.get("conclusion") or c["unknown"]})

    metric_dates = {}
    for metric_type, points in trends.items():
        if points:
            point = points[-1]
            metric_dates.setdefault(point.get("date", ""), []).append(
                (f'{METRIC_NAMES[locale].get(metric_type, metric_type)} {_timeline_metric_value(metric_type, point)}',
                 (metric_type, len(points) - 1)))
    for date, parts in metric_dates.items():
        events.append({"date": date, "priority": 1, "tone": "metric-event", "kind": c["metric_event"],
                       "title": c["health_metric_update"], "detail": " · ".join(text for text, _ in parts),
                       "parts": parts})

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

    # A value drawn inside a visit event is not repeated as a metric update —
    # but only against visits that survived the cap above, so a visit the cap
    # dropped cannot take its measurements off the card with it.
    covered = set().union(*(event["covers"] for event in events if event.get("covers")))
    kept = []
    for event in events:
        parts = event.pop("parts", None)
        if parts is None:
            kept.append(event)
            continue
        remaining = [text for text, key in parts if key not in covered]
        if remaining:
            event["detail"] = " · ".join(remaining)
            kept.append(event)
    events = kept

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


def _pending_tips(member_data: dict) -> list[dict]:
    """Tips that still ask for something, leaving clinical findings to the snapshot.

    Configured-range alerts are drawn in the clinical snapshot with their measured
    value and range, so repeating a title-only copy here would say less in more
    space. What remains are the record gaps, checkup and medication reminders.
    """
    return [tip for tip in member_data.get("health_tips", []) if not _is_threshold_alert(tip)]


def _attention_html(member_data: dict, locale: str) -> str:
    c = COPY[locale]
    items = []
    for tip in _pending_tips(member_data):
        if len(items) >= 3:
            break
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


def _attention_section(member_data: dict, locale: str) -> str:
    tips = _pending_tips(member_data)
    if not (tips or member_data.get("due_reminders")):
        return ""
    c = COPY[locale]
    has_risk = any(tip.get("severity") in ("alert", "warning") for tip in tips)
    return f'<section class="attention-section{" has-risk" if has_risk else ""}"><div class="compact-attention"><b>{c["attention"]}</b>{_attention_html(member_data, locale)}</div></section>'


# Display tone per printed marker. High and low are the only directions a report
# marker carries; anything else keeps a neutral tone.
_FLAG_CLASSES = {"h": "high", "hh": "high", "high": "high", "↑": "high",
                 "l": "low", "ll": "low", "low": "low", "↓": "low"}


def _is_threshold_alert(tip: dict) -> bool:
    """Identify configured-range alerts, which the clinical snapshot renders in full."""
    return tip.get("type") == "metric_anomaly" and tip.get("severity") in ("alert", "warning")


def _threshold_alerts(member_data: dict) -> list[dict]:
    """Configured-range alerts that carry something to show.

    The renderer and the layout profile both read this list, so the count the
    card reports and the alerts it draws can never disagree.
    """
    return [tip for tip in member_data.get("health_tips", [])
            if _is_threshold_alert(tip) and (tip.get("title") or tip.get("detail") or tip.get("message"))]


def _flag_class(flag: str) -> str:
    """Map a report's printed marker to a display tone (never to a new meaning)."""
    return _FLAG_CLASSES.get(str(flag or "").strip().lower(), "other")


def _snapshot_report_rows(items: list[dict], locale: str) -> str:
    c = COPY[locale]
    rows = []
    for item in items:
        measurement = " ".join(part for part in (
            "" if item.get("value") in (None, "") else str(item.get("value")),
            item.get("unit") or "") if part)
        reference = f'{c["reference_label"]} {item["reference"]}' if item.get("reference") else ""
        flag = item.get("flag") or ""
        flag_html = f'<i class="snapshot-flag {_flag_class(flag)}">{_escape(flag)}</i>' if flag else ""
        rows.append(f'<li><b>{_escape(item.get("name"))}</b><span>{_escape(measurement)}</span>'
                    f'{flag_html}<small>{_escape(reference)}</small></li>')
    return f'<ul>{"".join(rows)}</ul>'


def _snapshot_diagnoses_html(diagnoses: list[dict], locale: str) -> str:
    """Show each recorded diagnosis as written, with where it was recorded."""
    if not diagnoses:
        return ""
    c = COPY[locale]
    chips = "".join(f'<span class="snapshot-chip">{_escape(item.get("diagnosis"))}</span>'
                    for item in diagnoses)
    sources = []
    for item in diagnoses:
        source = " · ".join(str(item.get(key)) for key in ("visit_date", "hospital", "department")
                            if item.get(key))
        if source and source not in sources:
            sources.append(source)
    meta = f'<div class="snapshot-meta">{_escape("；".join(sources[:2]))}</div>' if sources else ""
    return (f'<div class="snapshot-block"><div class="snapshot-block-title">{c["diagnosis"]}</div>'
            f'<div class="snapshot-diagnosis">{chips}</div>{meta}</div>')


def _snapshot_abnormal_html(groups: list[dict], locale: str) -> str:
    """Show every item the reports themselves flagged, in full.

    These are the markers the source printed (H/L), not a judgement computed
    from the numbers.
    """
    if not groups:
        return ""
    c = COPY[locale]
    reports = []
    for group in groups:
        heading = " · ".join(str(part) for part in (group.get("test_date"), group.get("test_name")) if part)
        reports.append(f'<div class="snapshot-report"><div class="snapshot-meta">{_escape(heading)}</div>'
                       f'{_snapshot_report_rows(group.get("items") or [], locale)}</div>')
    return (f'<div class="snapshot-block"><div class="snapshot-block-title">{c["abnormal_reported"]}</div>'
            f'{"".join(reports)}</div>')


def _snapshot_threshold_html(member_data: dict, locale: str) -> str:
    """Show alerts raised by the configured ranges — including user-set thresholds."""
    c = COPY[locale]
    items = []
    for tip in _threshold_alerts(member_data):
        title = _system_text(tip.get("title") or "", locale)
        detail = _system_text(tip.get("detail") or tip.get("message") or "", locale)
        detail_html = f'<small>{_escape(detail)}</small>' if detail else ""
        items.append(f'<li class="snapshot-threshold {_escape(str(tip.get("severity")))}"><span></span>'
                     f'<div><b>{_escape(title)}</b>{detail_html}</div></li>')
    if not items:
        return ""
    return (f'<div class="snapshot-block"><div class="snapshot-block-title">{c["abnormal_threshold"]}</div>'
            f'<ul class="snapshot-thresholds">{"".join(items)}</ul></div>')


def _snapshot_history_html(member: dict, locale: str) -> str:
    c = COPY[locale]
    entries = []
    for key, label in (("medical_history", c["history"]), ("allergies", c["allergies_label"])):
        text = str(member.get(key) or "").strip()
        if text:
            entries.append(f'<div class="snapshot-history"><div class="snapshot-block-title">{label}</div>'
                           f'<p>{_escape(text)}</p></div>')
    if not entries:
        return ""
    return f'<div class="snapshot-block snapshot-history-row">{"".join(entries)}</div>'


def _snapshot_section(member: dict, snapshot: dict, member_data: dict, locale: str) -> str:
    """Assemble the fixed clinical header: diagnoses, flagged results, history.

    This block is not part of section_order — it is the standing clinical
    picture rather than one of the sortable report modules. It is omitted
    entirely when nothing clinical is on file, so an empty record does not
    produce a panel of blanks.
    """
    c = COPY[locale]
    blocks = [
        _snapshot_diagnoses_html(snapshot.get("diagnoses") or [], locale),
        _snapshot_abnormal_html(snapshot.get("abnormal_reports") or [], locale),
        _snapshot_threshold_html(member_data, locale),
        _snapshot_history_html(member, locale),
    ]
    if not any(blocks):
        return ""
    return (f'<section class="snapshot-section"><div class="section-title"><h2>{c["snapshot_title"]}</h2></div>'
            f'{"".join(blocks)}</section>')


def _snapshot_abnormal_count(snapshot: dict) -> int:
    """Count every flagged item in the snapshot, so the totals match what is drawn."""
    return sum(len(group.get("items") or []) for group in snapshot.get("abnormal_reports") or [])


def _snapshot_profile(member: dict, snapshot: dict, member_data: dict) -> dict:
    """Describe the clinical header block so the layout stays machine-checkable."""
    reports = snapshot.get("abnormal_reports") or []
    return {
        "diagnosis_count": len(snapshot.get("diagnoses") or []),
        "report_count": len(reports),
        "abnormal_item_count": _snapshot_abnormal_count(snapshot),
        "threshold_count": len(_threshold_alerts(member_data)),
        "has_history": bool(str(member.get("medical_history") or "").strip()),
        "has_allergies": bool(str(member.get("allergies") or "").strip()),
    }


def _personal_content(member: dict, member_data: dict, trends: dict, lifestyle: dict, sleep: dict,
                      care: dict, meds: list[dict], locale: str, layout: dict,
                      snapshot: dict | None = None, chart_trends: dict | None = None) -> str:
    c = COPY[locale]
    sections = []
    for index, section in enumerate(layout["section_order"], start=1):
        number = f"{index:02d}"
        if section == "metrics":
            featured = layout["focus"] == "metrics"
            classes = "overview-section section-featured" if featured else "overview-section"
            cards = _metric_trend_section(chart_trends if chart_trends is not None else trends,
                                          locale, layout.get("metric_focus"))
            sections.append(f'<section class="{classes}"><div class="section-title"><span>{number}</span><h2>{c["metrics"]}</h2></div>{cards}</section>')
        elif section == "lifestyle":
            sections.append(_lifestyle_sleep(lifestyle, sleep, locale, number,
                                              layout.get("lifestyle_focus"), layout["focus"] == "lifestyle"))
        elif section == "timeline":
            sections.append(_personal_timeline(trends, lifestyle, sleep, care, locale, number,
                                                layout["focus"] == "care"))
        elif section == "medications":
            sections.append(_medications_html(meds, locale, number, layout["focus"] == "medications"))
    return (_snapshot_section(member, snapshot or {}, member_data, locale) +
            _attention_section(member_data, locale) + "".join(sections))


def _family_latest_metrics(trends: dict, locale: str) -> str:
    c = COPY[locale]
    latest_metrics = []
    for metric_type, points in list(trends.items())[:3]:
        point = points[-1]
        if metric_type == "blood_pressure":
            value = f'{point.get("systolic", "—")}/{point.get("diastolic", "—")}'
        else:
            value = _fmt_number(_metric_number(point, metric_type), 1 if metric_type in ("blood_sugar", "weight", "temperature") else 0)
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
    abnormal_count = int(briefing.get("total_abnormal", 0) or 0)
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
    elif not (alert_count or warning_count or abnormal_count or reminder_count):
        return f'<div class="clear hero-clear"><i>✓</i>{c["all_clear"]}</div>'
    else:
        cards = [(str(alert_count), c["alerts"].format(count=alert_count), "coral"), (str(warning_count), c["warnings"].format(count=warning_count), "gold"),
                 (str(abnormal_count), c["abnormal"].format(count=abnormal_count), "blue"), (str(reminder_count), c["todos"].format(count=reminder_count), "green")]
    strip_class = "summary-strip four" if len(cards) == 4 else "summary-strip"
    return f'<div class="{strip_class}">'+"".join(f'<div><b class="{color}">{value}</b><span>{label}</span></div>' for value, label, color in cards)+'</div>'


def _render_html(title: str, subtitle: str, privacy: str, summary: str, content: str, locale: str) -> str:
    c = COPY[locale]
    generated = c["generated"].format(time=datetime.now().strftime("%Y-%m-%d %H:%M"))
    return f'''<!DOCTYPE html><html lang="{c["lang"]}"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{_escape(title)}</title>
<style>
:root{{--page:#F3F7FC;--surface:#FFFFFF;--surface-muted:#F7FAFD;--ink:#15324B;--ink-strong:#0D2942;--muted:#526B82;--line:#D8E4F0;--line-strong:#BBD2E8;--primary:#246BCE;--primary-strong:#164F91;--primary-soft:#EAF3FD;--cyan:#167A9A;--cyan-soft:#EAF6FA;--coral:#D66548;--coral-soft:#FCF0EC;--gold:#B7791F}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--page);color:var(--ink);font:16px/1.65 "Avenir Next","Segoe UI Variable","Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-break:strict;overflow-wrap:break-word;font-synthesis:none}} .container{{max-width:1040px;margin:auto;padding:26px}}
.header{{position:relative;overflow:hidden;border-radius:24px;padding:31px 36px;background:linear-gradient(135deg,#0A2F55,#155E9E);color:#fff;box-shadow:0 18px 42px rgba(16,68,116,.20)}} .header:after{{content:"";position:absolute;width:250px;height:250px;border:1px solid rgba(255,255,255,.15);border-radius:50%;right:-48px;top:-112px;box-shadow:0 0 0 38px rgba(255,255,255,.045)}}
.brand{{display:flex;align-items:center;gap:14px}} .mark{{display:grid;place-items:center;width:44px;height:44px;border-radius:13px;background:#EAF4FF;color:#175D9B;font-weight:800;font-size:22px;box-shadow:0 8px 18px rgba(4,37,68,.16)}} h1{{font-size:32px;line-height:1.22;margin:0;letter-spacing:-.25px;text-wrap:balance}} .subtitle{{margin-top:16px;color:#D9EAFE;font-size:15px}} .privacy{{display:inline-block;margin-top:14px;padding:6px 12px;border:1px solid rgba(255,255,255,.28);border-radius:99px;color:#EFF7FF;font-size:13px;background:rgba(4,35,63,.10)}}
.summary-strip{{display:grid;grid-template-columns:repeat(3,1fr);background:var(--surface);border:1px solid var(--line);border-radius:18px;margin:18px 0;padding:18px;box-shadow:0 9px 28px rgba(21,63,104,.07)}} .summary-strip.four{{grid-template-columns:repeat(4,1fr)}} .summary-strip>div{{padding:2px 22px;border-right:1px solid #E2EAF2}} .summary-strip>div:last-child{{border:0}} .summary-strip b{{font-size:29px;display:block;line-height:1.1;font-variant-numeric:tabular-nums}} .summary-strip span{{font-size:13px;color:var(--muted)}} .green{{color:var(--cyan)}} .blue{{color:var(--primary)}} .coral{{color:var(--coral)}} .gold{{color:var(--gold)}}
section{{background:var(--surface);border:1px solid var(--line);border-radius:19px;padding:24px;margin:15px 0;box-shadow:0 10px 30px rgba(21,63,104,.065)}} .section-featured{{border-color:#A8C9E8;box-shadow:0 12px 34px rgba(31,91,147,.11)}} .section-title{{display:flex;align-items:center;gap:10px;margin-bottom:15px}} .section-title>span{{font-size:11px;font-weight:800;color:#2F6EA5;border:1px solid #C5D9EC;background:#F2F7FC;border-radius:99px;padding:3px 8px}} h2{{font-size:21px;line-height:1.3;margin:0;color:var(--ink-strong);text-wrap:balance}} h3{{margin:0;font-size:16px;color:var(--ink-strong)}} p{{text-wrap:pretty}} .muted{{color:var(--muted);font-size:12px}} .empty{{padding:20px;text-align:center;border:1px dashed #B9CDE0;border-radius:12px;background:#F8FAFD;color:var(--muted)}} .empty.compact{{padding:14px 9px;margin-top:8px}}
.trend-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:11px}} .trend-chart{{padding:15px;border-radius:13px;background:var(--surface-muted);border:1px solid #D9E4EF;min-width:0}} .trend-chart.wide{{grid-column:span 2}} .trend-head{{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}} .trend-head b{{font-size:14px;color:var(--ink-strong)}} .trend-head small,.big small{{font-size:11px;color:var(--muted)}} .trend-span{{margin-left:auto;font-size:11px;color:#587087}} .trend-legend{{display:inline-flex;align-items:center;gap:5px;font-size:11px;color:#587087}} .trend-legend i{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-left:4px}} .chart{{display:block;width:100%;height:auto;margin:6px 0 2px}} .trend-source{{display:flex;justify-content:space-between;gap:8px;font-size:11px;color:var(--muted)}} .trend-single{{grid-column:span 2;display:flex;align-items:baseline;gap:9px;flex-wrap:wrap;padding:11px 13px;border-radius:11px;background:var(--surface-muted);border:1px dashed #C6D8E8}} .trend-single b{{font-size:13px;color:var(--ink-strong)}} .trend-value{{font-size:15px;font-weight:700;color:var(--ink-strong);font-variant-numeric:tabular-nums}} .trend-meta{{margin-left:auto;font-size:11px;color:var(--muted)}}
.wellness-grid{{display:grid;grid-template-columns:1.05fr 1fr 1fr;gap:11px}} .wellness-grid.focused{{grid-template-columns:repeat(4,minmax(0,1fr))}} .featured-panel{{grid-column:span 2}} .panel{{min-height:174px;border-radius:14px;padding:16px;border:1px solid #D9E4EF;background:#F8FAFD}} .intake{{background:#F2F7FE;border-color:#D4E2F2}} .activity{{background:#F1F8FC;border-color:#D2E7F0}} .sleep{{background:#FCF6F3;border-color:#EFDCD3}} .eyebrow{{font-size:12px;font-weight:760;color:#496780}} .big{{font-size:28px;font-weight:780;margin-top:7px;font-variant-numeric:tabular-nums}} .macro,.sleep-row{{display:grid;grid-template-columns:repeat(2,1fr);gap:6px;margin-top:10px}} .macro span,.sleep-row span{{font-size:11px;color:#526B82}} .macro b,.sleep-row b{{display:block;font-size:12px;color:#24445F}} .step-box{{margin-top:10px;padding-top:9px;border-top:1px solid #D2E3EE;display:grid;grid-template-columns:1fr auto}} .step-box b{{font-size:17px;color:var(--cyan)}} .step-box small{{grid-column:1/3;color:#587087}} .top-gap{{margin-top:11px}} .scope-note{{margin:11px 2px 0;font-size:11px;color:#587087}}
.table-wrap{{overflow:hidden;border:1px solid var(--line);border-radius:13px}} table{{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}} th{{background:#EDF4FA;color:#274E70;font-size:12px;text-align:left}} th,td{{padding:11px 13px;border-bottom:1px solid #E8EEF4}} tr:last-child td{{border:0}} td{{font-size:12px}}
.clear{{display:flex;align-items:center;gap:9px;padding:11px 14px;border-radius:12px;background:#EAF3FB;color:#195F93}} .clear i{{display:grid;place-items:center;width:23px;height:23px;border-radius:50%;background:#2C78B8;color:white;font-style:normal}} .hero-clear{{margin:14px 0;background:white;border:1px solid #D3E1EE;box-shadow:0 9px 28px rgba(21,63,104,.06)}} .attention-section{{padding:15px 18px}} .attention-section.has-risk{{border-color:#E9B9AA;background:#FFFCFB}} .attention-section .compact-attention{{padding:0;border:0}} .attention-list{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;flex:1}} .attention-item{{display:flex;gap:9px;padding:8px 11px;border-radius:10px;background:#F4F7FA}} .attention-item span{{width:6px;height:6px;border-radius:50%;background:var(--primary);margin-top:7px;flex:none}} .attention-item.alert span{{background:#D65F45}} .attention-item.warning span{{background:#D49A30}} .attention-item p{{margin:0;font-size:12px}} .compact-attention{{display:flex;align-items:center;gap:14px;padding-bottom:13px;border-bottom:1px solid #E4EBF2}} .compact-attention>b{{font-size:12px;white-space:nowrap;color:#385A76}} .compact-attention>.clear{{flex:1;padding:8px 11px}} .compact-attention>.clear i{{width:20px;height:20px}}
.family-grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:15px}} .family-card{{padding:20px;border:1px solid #D6E2ED;border-radius:16px;background:#FBFCFE}} .family-card.featured-member{{border-color:#E7A48E;background:#FFF9F7;box-shadow:0 10px 24px rgba(174,78,49,.10)}} .family-card-head{{display:flex;justify-content:space-between;gap:10px;margin-bottom:13px}} .family-card-head p{{margin:3px 0;color:var(--muted);font-size:11px}} .family-grid>.family-card:nth-child(odd):last-child{{grid-column:1/-1;display:grid;grid-template-columns:1.3fr .85fr .85fr;column-gap:15px}} .family-grid>.family-card:nth-child(odd):last-child .family-card-head{{grid-column:1/-1}} .status{{height:max-content;padding:5px 9px;border-radius:99px;background:#EAF3FB;color:#195F93;font-size:11px;white-space:nowrap}} .status.watch{{background:#FCEBE5;color:#A64C36}} .family-block{{padding:12px 0;border-top:1px solid #E3EBF2}} .family-block-title{{font-size:11px;font-weight:760;color:#46657E;margin-bottom:8px}} .family-metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}} .family-metrics span{{padding:9px;background:#EFF5FA;border-radius:9px;min-width:0}} .family-metrics small,.family-metrics b{{display:block}} .family-metrics small{{font-size:11px;color:var(--muted)}} .family-metrics b{{font-size:15px;margin-top:2px;white-space:nowrap;color:var(--ink-strong)}} .family-metrics i{{font-size:11px;font-style:normal;color:#587087}} .family-state-note,.family-empty{{padding:9px 11px;border-radius:9px;background:#F1F5F9;color:var(--muted);font-size:11px}} .family-empty.clear-state{{background:#EAF3FB;color:#195F93}} .family-list{{display:grid;gap:7px}} .family-list-item{{display:flex;align-items:center;gap:8px;padding:9px 10px;border-radius:9px;background:#F1F5F9;min-width:0}} .family-list-item.medication{{justify-content:space-between;background:#EDF4FC}} .family-list-item.medication div{{min-width:0}} .family-list-item.medication b,.family-list-item.medication small{{display:block}} .family-list-item.medication b{{font-size:13px;color:#234D70}} .family-list-item.medication small{{font-size:11px;color:#526B82;margin-top:1px}} .family-list-item.medication em{{font-size:11px;font-style:normal;color:var(--primary);background:#fff;padding:3px 7px;border-radius:99px;white-space:nowrap}} .family-list-item.attention{{align-items:flex-start}} .family-list-item.attention i{{width:6px;height:6px;border-radius:50%;background:var(--primary);margin-top:7px;flex:none}} .family-list-item.attention.warning i{{background:#D49A30}} .family-list-item.attention.alert i{{background:#D65F45}} .family-list-item.attention p{{margin:0;font-size:11px;color:#405E77}} .family-more{{font-size:11px;color:var(--muted);padding-left:3px}}
.timeline{{padding-left:6px}} .timeline-item{{display:grid;grid-template-columns:82px 12px 1fr;gap:10px;min-height:64px}} .timeline-item time{{font-size:11px;color:var(--muted);padding-top:2px;font-variant-numeric:tabular-nums}} .timeline-item>span{{position:relative}} .timeline-item>span:before{{content:"";position:absolute;width:7px;height:7px;border-radius:50%;background:var(--coral);top:6px;left:2px}} .timeline-item>span:after{{content:"";position:absolute;width:1px;background:#D9E4EF;top:16px;bottom:0;left:5px}} .timeline-item:last-child>span:after{{display:none}} .timeline-item b{{font-size:13px;color:var(--ink-strong)}} .timeline-item small{{margin-left:7px;padding:2px 7px;border-radius:99px;background:#F4E9E5;color:#9B5A47;font-size:11px}} .timeline-item p{{font-size:12px;color:#536D83;margin:2px 0}} .personal-timeline{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:26px}} .personal-timeline .timeline-item{{grid-template-columns:76px 12px 1fr;min-height:61px}} .personal-timeline .metric-event>span:before{{background:var(--primary)}} .personal-timeline .metric-event small{{background:var(--primary-soft);color:var(--primary)}} .personal-timeline .food-event>span:before{{background:#557FBA}} .personal-timeline .food-event small{{background:#EDF3FA;color:#446A9E}} .personal-timeline .activity-event>span:before{{background:var(--cyan)}} .personal-timeline .activity-event small{{background:var(--cyan-soft);color:#126985}} .personal-timeline .sleep-event>span:before{{background:#C8775E}} .personal-timeline .sleep-event small{{background:#F7EAE5;color:#A45C47}}
.snapshot-section{{border-color:#B7D0E8;background:linear-gradient(180deg,#FBFDFF,#F5FAFE)}} .snapshot-block{{padding:13px 0;border-top:1px solid #E3EBF2}} .snapshot-block:first-of-type{{border-top:0;padding-top:2px}} .snapshot-block-title{{font-size:11px;font-weight:760;color:#46657E;margin-bottom:8px}} .snapshot-diagnosis{{display:flex;flex-wrap:wrap;gap:7px}} .snapshot-chip{{padding:6px 11px;border-radius:9px;background:#EAF3FD;border:1px solid #C9DEF3;color:#174A78;font-size:15px;font-weight:700}} .snapshot-meta{{margin-top:7px;font-size:11px;color:#587087}} .snapshot-report{{margin-top:10px}} .snapshot-report:first-of-type{{margin-top:0}} .snapshot-report ul{{list-style:none;margin:7px 0 0;padding:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:22px}} .snapshot-report li{{display:flex;align-items:baseline;gap:8px;padding:6px 0;border-bottom:1px dashed #E4EBF2;min-width:0;font-size:12px}} .snapshot-report li b{{font-weight:600;color:#1E3E5C;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}} .snapshot-report li>span{{color:#0D2942;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}} .snapshot-report li small{{margin-left:auto;color:#587087;white-space:nowrap}} .snapshot-flag{{font-style:normal;font-size:11px;font-weight:800;border-radius:5px;padding:1px 6px;flex:none}} .snapshot-flag.high{{background:#FCEBE5;color:#A64C36}} .snapshot-flag.low{{background:#E7F3FA;color:#126985}} .snapshot-flag.other{{background:#EEF2F6;color:#526B82}} .snapshot-thresholds{{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}} .snapshot-threshold{{display:flex;gap:9px;align-items:flex-start;padding:9px 12px;border-radius:10px;background:#FBF2EE}} .snapshot-threshold.warning{{background:#FCF7EC}} .snapshot-threshold span{{width:6px;height:6px;border-radius:50%;background:#D65F45;margin-top:7px;flex:none}} .snapshot-threshold.warning span{{background:#D49A30}} .snapshot-threshold b{{display:block;font-size:12px;color:#8C3B28}} .snapshot-threshold.warning b{{color:#8A6314}} .snapshot-threshold small{{display:block;font-size:11px;color:#5B6E82;margin-top:2px}} .snapshot-history-row{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}} .snapshot-history p{{margin:0;font-size:12px;color:#3E5B74}}
.footer{{text-align:center;color:#526B82;font-size:11px;padding:16px 10px 7px}} .footer b{{display:block;color:#2B5475;margin:3px}} @media(max-width:700px){{.container{{padding:12px}}.header{{padding:25px}}.trend-grid{{grid-template-columns:1fr}}.trend-single{{align-items:flex-start;flex-direction:column}}.trend-meta{{margin-left:0}}.wellness-grid,.wellness-grid.focused,.family-grid,.personal-timeline{{grid-template-columns:1fr}}.family-grid>.family-card:nth-child(odd):last-child{{grid-column:auto;display:block}}.featured-panel{{grid-column:auto}}.attention-list{{grid-template-columns:1fr}}.snapshot-report ul,.snapshot-thresholds,.snapshot-history-row{{grid-template-columns:1fr}}.compact-attention{{align-items:flex-start;flex-direction:column}}.summary-strip>div{{padding:2px 8px}}.summary-strip.four{{grid-template-columns:repeat(2,1fr)}}.summary-strip.four>div:nth-child(2){{border-right:0}}.family-metrics{{grid-template-columns:repeat(2,1fr)}}}} @media print{{body{{background:white}}.container{{max-width:none}}section,.header{{box-shadow:none;break-inside:avoid}}}}
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
            members = health_db.rows_to_list(conn.execute(
                """SELECT id, name, relation, gender, birth_date, age_years, age_recorded_at,
                          blood_type, allergies, medical_history
                   FROM members WHERE id=? AND is_deleted=0""", (member_id,)).fetchall())
        elif owner_id:
            members = health_db.rows_to_list(conn.execute(
                """SELECT id, name, relation, gender, birth_date, age_years, age_recorded_at,
                          blood_type, allergies, medical_history
                   FROM members WHERE owner_id=? AND is_deleted=0 ORDER BY created_at""",
                (owner_id,)).fetchall())
        else:
            members = health_db.rows_to_list(conn.execute(
                """SELECT id, name, relation, gender, birth_date, age_years, age_recorded_at,
                          blood_type, allergies, medical_history
                   FROM members WHERE is_deleted=0 ORDER BY created_at""").fetchall())
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
    chart_days = _chart_window_days(days)
    all_data = []
    for member in members:
        mid = member["id"]
        member_data = lookup.get(mid, {"member_id": mid, "member_name": member["name"], "relation": member["relation"], "due_reminders": [], "health_tips": []})
        trends = _query_metric_trends(mid, days)
        # The charts read their own, longer window. `trends` above keeps feeding
        # the timeline and the layout coverage at the card window, so a
        # measurement older than the card window can never leak into the
        # timeline and contradict the header's "last N days".
        chart_trends = _query_metric_trends(mid, chart_days)
        lifestyle = _query_lifestyle_summary(mid, days)
        sleep = _query_sleep_summary(mid, days)
        all_data.append({"member": member, "member_data": member_data, "trends": trends,
                         "chart_trends": chart_trends,
                         "lifestyle": lifestyle, "sleep": sleep,
                         "care": _query_recent_care(mid, days), "meds": _query_active_medications(mid),
                         "reminders": _query_active_reminders(mid),
                         "snapshot": _query_clinical_snapshot(mid)})

    # health_advisor's reminder total is global. Recalculate card totals from
    # the selected member set so a personal card never inherits family tasks.
    card_briefing = dict(briefing)
    tips = [tip for data in all_data for tip in data["member_data"].get("health_tips", [])]
    card_briefing["total_alerts"] = sum(1 for tip in tips if tip.get("severity") == "alert")
    card_briefing["total_warnings"] = sum(1 for tip in tips if tip.get("severity") == "warning")
    # Flagged lab items stay their own figure: folding them into "warnings" made
    # one number mean two different things. It is counted from the snapshot so
    # the strip always agrees with the clinical block drawn right below it.
    card_briefing["total_abnormal"] = sum(_snapshot_abnormal_count(data["snapshot"]) for data in all_data)
    card_briefing["total_due_reminders"] = sum(len(data["member_data"].get("due_reminders", [])) for data in all_data)

    c = COPY[locale]
    end = briefing.get("date") or datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days-1)).strftime("%Y-%m-%d")
    if resolved_view == "personal":
        data = all_data[0]
        layout_profile = _personal_layout(data["member_data"], data["trends"], data["lifestyle"],
                                          data["sleep"], data["care"], data["meds"], focus,
                                          data["chart_trends"], chart_days)
        layout_profile["snapshot"] = _snapshot_profile(data["member"], data["snapshot"], data["member_data"])
        title = c["title"]
        identity = _identity_text(data["member"], locale)
        subtitle = " · ".join(part for part in (
            _member_label(data["member"], locale), identity,
            c["period"].format(start=start, end=end), c["last_days"].format(days=days)) if part)
        has_priority_items = any(card_briefing.get(key, 0) for key in
                                 ("total_alerts", "total_warnings", "total_abnormal", "total_due_reminders"))
        summary = _summary_strip(card_briefing, locale) if has_priority_items else ""
        content = _personal_content(data["member"], data["member_data"], data["trends"], data["lifestyle"],
                                    data["sleep"], data["care"], data["meds"], locale, layout_profile,
                                    data["snapshot"], data["chart_trends"])
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
    report = generate_report(args.member_id, args.owner_id, args.days, args.locale, args.view,
                             args.focus)
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
