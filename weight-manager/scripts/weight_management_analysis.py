"""Deterministic multi-signal analysis for MediWise 体重译报.

Weight is treated as an outcome signal, while recorded food intake, exercise
and sleep are described as parallel observations from the same time window.
The module deliberately does not estimate an energy deficit, infer causality,
diagnose a condition, or generate a weight-loss prescription.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Iterable, Mapping, Optional


NON_CAUSAL_LIMIT = "这些变化发生在同一阶段，但当前记录不能证明它们造成了体重变化。"


def _date(value: object) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None


def _number(value: object, *, minimum: float = 0.0, maximum: float = 1_000_000.0) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result < minimum or result > maximum:
        return None
    return result


def _rounded(value: Optional[float], digits: int = 1) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _average(values: Iterable[float]) -> Optional[float]:
    items = list(values)
    return float(mean(items)) if items else None


def _split_date(day: date, start: date, days: int) -> str:
    return "first" if (day - start).days < max(days // 2, 1) else "second"


def _change_label(value: Optional[float], stable_band: float) -> str:
    if value is None:
        return "insufficient"
    if value > stable_band:
        return "higher"
    if value < -stable_band:
        return "lower"
    return "similar"


def _diet_summary(records: Iterable[Mapping[str, object]], start: date, end: date, days: int) -> dict:
    daily = defaultdict(lambda: {"calories": 0.0, "protein": 0.0, "calorie_items": 0, "protein_items": 0})
    recorded_dates = set()
    for item in records or []:
        day = _date(item.get("meal_date") or item.get("date"))
        if day is None or day < start or day > end:
            continue
        recorded_dates.add(day)
        calories = _number(item.get("total_calories"), maximum=20_000)
        protein = _number(item.get("total_protein"), maximum=1_000)
        # Zero-valued nutrition fields are usually unfilled defaults, not proof
        # of a zero-calorie or zero-protein day.
        if calories is not None and calories > 0:
            daily[day]["calories"] += calories
            daily[day]["calorie_items"] += 1
        if protein is not None and protein > 0:
            daily[day]["protein"] += protein
            daily[day]["protein_items"] += 1

    calorie_days = {day: values["calories"] for day, values in daily.items() if values["calorie_items"]}
    protein_days = {day: values["protein"] for day, values in daily.items() if values["protein_items"]}
    halves = {
        "first": [value for day, value in calorie_days.items() if _split_date(day, start, days) == "first"],
        "second": [value for day, value in calorie_days.items() if _split_date(day, start, days) == "second"],
    }
    first_average = _average(halves["first"]) if len(halves["first"]) >= 3 else None
    second_average = _average(halves["second"]) if len(halves["second"]) >= 3 else None
    change = second_average - first_average if first_average is not None and second_average is not None else None
    recorded_days = len(recorded_dates)
    calorie_recorded_days = len(calorie_days)
    return {
        "recorded_days": recorded_days,
        "calorie_recorded_days": calorie_recorded_days,
        "protein_recorded_days": len(protein_days),
        "coverage_ratio": round(min(recorded_days / float(days), 1.0), 3),
        "claim_allowed": calorie_recorded_days >= 3,
        "average_calories_on_recorded_days": _rounded(_average(calorie_days.values()), 0) if calorie_recorded_days >= 3 else None,
        "average_protein_on_recorded_days": _rounded(_average(protein_days.values()), 1) if len(protein_days) >= 3 else None,
        "first_half_recorded_days": len(halves["first"]),
        "second_half_recorded_days": len(halves["second"]),
        "first_half_average_calories": _rounded(first_average, 0),
        "second_half_average_calories": _rounded(second_average, 0),
        "change_calories": _rounded(change, 0),
        "change_direction": _change_label(change, 50.0),
        "scope_label": "有记录日摄入",
        "missing_days_are_zero": False,
    }


def _activity_summary(records: Iterable[Mapping[str, object]], start: date, end: date, days: int) -> dict:
    daily = defaultdict(lambda: {"duration": 0.0, "burn": 0.0, "sessions": 0})
    for item in records or []:
        day = _date(item.get("exercise_date") or item.get("date"))
        if day is None or day < start or day > end:
            continue
        duration = _number(item.get("duration"), maximum=1_440)
        burn = _number(item.get("calories_burned"), maximum=10_000)
        daily[day]["sessions"] += 1
        if duration is not None:
            daily[day]["duration"] += duration
        if burn is not None:
            daily[day]["burn"] += burn

    halves = {
        "first": [values["duration"] for day, values in daily.items() if _split_date(day, start, days) == "first"],
        "second": [values["duration"] for day, values in daily.items() if _split_date(day, start, days) == "second"],
    }
    first_total = sum(halves["first"]) if len(halves["first"]) >= 2 else None
    second_total = sum(halves["second"]) if len(halves["second"]) >= 2 else None
    change = second_total - first_total if first_total is not None and second_total is not None else None
    recorded_days = len(daily)
    total_duration = sum(values["duration"] for values in daily.values())
    return {
        "recorded_days": recorded_days,
        "session_count": sum(values["sessions"] for values in daily.values()),
        "coverage_ratio": round(min(recorded_days / float(days), 1.0), 3),
        "claim_allowed": recorded_days >= 2,
        "total_duration_min": _rounded(total_duration, 0) if recorded_days >= 2 else None,
        "average_duration_on_active_days": _rounded(total_duration / recorded_days, 0) if recorded_days >= 2 else None,
        "recorded_exercise_burn": _rounded(sum(values["burn"] for values in daily.values()), 0) if recorded_days >= 2 else None,
        "first_half_recorded_days": len(halves["first"]),
        "second_half_recorded_days": len(halves["second"]),
        "first_half_duration_min": _rounded(first_total, 0),
        "second_half_duration_min": _rounded(second_total, 0),
        "change_duration_min": _rounded(change, 0),
        "change_direction": _change_label(change, 20.0),
        "scope_label": "已记录运动",
        "missing_days_are_zero": False,
        "burn_is_total_expenditure": False,
    }


def _sleep_value(raw: object) -> Optional[dict]:
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(value, Mapping):
        return None
    duration = _number(value.get("duration_min"), minimum=1, maximum=1_440)
    return {"duration_min": duration} if duration is not None else None


def _sleep_summary(records: Iterable[Mapping[str, object]], start: date, end: date, days: int) -> dict:
    by_day = defaultdict(list)
    for item in records or []:
        day = _date(item.get("measured_at") or item.get("date"))
        value = _sleep_value(item.get("value", item.get("sleep")))
        if day is None or day < start or day > end or value is None:
            continue
        by_day[day].append(value["duration_min"])
    # Multiple imports for one night are collapsed rather than added together.
    daily = {day: float(mean(values)) for day, values in by_day.items()}
    halves = {
        "first": [value for day, value in daily.items() if _split_date(day, start, days) == "first"],
        "second": [value for day, value in daily.items() if _split_date(day, start, days) == "second"],
    }
    first_average = _average(halves["first"]) if len(halves["first"]) >= 3 else None
    second_average = _average(halves["second"]) if len(halves["second"]) >= 3 else None
    change = second_average - first_average if first_average is not None and second_average is not None else None
    recorded_days = len(daily)
    return {
        "recorded_days": recorded_days,
        "coverage_ratio": round(min(recorded_days / float(days), 1.0), 3),
        "claim_allowed": recorded_days >= 3,
        "average_duration_min": _rounded(_average(daily.values()), 0) if recorded_days >= 3 else None,
        "first_half_recorded_days": len(halves["first"]),
        "second_half_recorded_days": len(halves["second"]),
        "first_half_average_min": _rounded(first_average, 0),
        "second_half_average_min": _rounded(second_average, 0),
        "change_min": _rounded(change, 0),
        "change_direction": _change_label(change, 15.0),
        "scope_label": "睡眠记录时长",
        "missing_days_are_zero": False,
    }


def _signed(value: Optional[float], unit: str) -> str:
    if value is None:
        return "—"
    rounded = int(round(abs(value)))
    sign = "+" if value > 0 else ("−" if value < 0 else "")
    return "%s%d%s" % (sign, rounded, unit)


def _duration(minutes: Optional[float]) -> str:
    if minutes is None:
        return "—"
    total = int(round(minutes))
    hours, remainder = divmod(total, 60)
    return "%d 小时 %d 分" % (hours, remainder) if hours else "%d 分钟" % remainder


DOMAIN_NAMES = {"intake": "摄入", "activity": "运动", "sleep": "睡眠"}


def _weight_sentence(weight: Mapping[str, object]) -> str:
    state = str(weight.get("state") or "insufficient")
    trend = weight.get("trend_delta")
    if not weight.get("trend_claim_allowed") or trend is None:
        return "体重记录还不足以概括长期方向"
    direction = "向下" if float(trend) < -0.2 else ("向上" if float(trend) > 0.2 else "接近水平")
    if state == "daily_up_trend_down":
        return "最新一次秤面上浮，但稳健长线仍向下"
    if state == "daily_down_trend_up":
        return "最新一次秤面回落，但稳健长线仍向上"
    return "体重稳健长线%s，阶段估计约 %+.1f kg" % (direction, float(trend))


def _comparison_evidence(intake: dict, activity: dict, sleep: dict) -> list:
    evidence = []
    if intake["change_calories"] is not None:
        evidence.append({
            "domain": "intake",
            "direction": intake["change_direction"],
            "text": "有记录日摄入平均值%s" % _signed(intake["change_calories"], " kcal"),
        })
    if activity["change_duration_min"] is not None:
        evidence.append({
            "domain": "activity",
            "direction": activity["change_direction"],
            "text": "已记录运动总时长%s" % _signed(activity["change_duration_min"], " 分钟"),
        })
    if sleep["change_min"] is not None:
        evidence.append({
            "domain": "sleep",
            "direction": sleep["change_direction"],
            "text": "睡眠记录平均时长%s" % _signed(sleep["change_min"], " 分钟"),
        })
    return evidence


def _situation_portrait(weight: Mapping[str, object], intake: dict, activity: dict, sleep: dict, days: int) -> dict:
    """Name the observed stage without turning it into a health judgement."""
    domains = {"intake": intake, "activity": activity, "sleep": sleep}
    eligible = [name for name, value in domains.items() if value["claim_allowed"]]
    evidence = _comparison_evidence(intake, activity, sleep)
    changed = [item for item in evidence if item["direction"] in ("higher", "lower")]
    comparable = [item["domain"] for item in evidence]
    weight_state = str(weight.get("state") or "insufficient")
    coverages = {name: float(value["coverage_ratio"]) for name, value in domains.items()}
    dominant = max(coverages, key=coverages.get) if coverages and max(coverages.values()) > 0 else None
    sorted_coverage = sorted(coverages.values(), reverse=True)
    coverage_gap = sorted_coverage[0] - sorted_coverage[-1] if len(sorted_coverage) == 3 else 0.0

    if weight_state in ("daily_up_trend_down", "daily_down_trend_up"):
        pattern_id = "scale-plot-twist"
        title = "今天抢镜，长线没改剧本"
        hook = "最新一次数字和整段趋势说了两件不同的事。"
    elif len(eligible) == 3 and len(changed) >= 2:
        pattern_id = "second-half-shift"
        title = "后半场换挡"
        hook = "后半段至少两条生活记录线出现了可比较的变化。"
    elif len(eligible) == 3 and len(evidence) == 3 and not changed:
        pattern_id = "steady-rhythm"
        title = "节奏守恒局"
        hook = "三条生活记录线前后半段都没有出现明显位移。"
    elif len(eligible) == 3:
        pattern_id = "four-signals"
        title = "四线同框，剧情待续"
        hook = "体重、摄入、运动和睡眠已经能放进同一张阶段肖像。"
    elif dominant and coverage_gap >= 0.35 and coverages[dominant] >= 0.5:
        pattern_id = "recording-spotlight"
        title = "聚光灯落在%s" % DOMAIN_NAMES[dominant]
        hook = "%s是这一阶段记录最连续的一条线。" % DOMAIN_NAMES[dominant]
    elif len(eligible) == 2:
        pattern_id = "two-signals"
        title = "两条生活线已经接上"
        hook = "%s和%s已经足够形成同期观察。" % tuple(DOMAIN_NAMES[name] for name in eligible)
    elif len(eligible) == 1:
        pattern_id = "one-signal"
        title = "%s先开口" % DOMAIN_NAMES[eligible[0]]
        hook = "目前最清楚的生活方式线索来自%s记录。" % DOMAIN_NAMES[eligible[0]]
    else:
        pattern_id = "loading-signals"
        title = "线索还在加载"
        hook = "目前主要能看体重记录，生活方式记录还不足以组成阶段故事。"

    weight_text = _weight_sentence(weight)
    if evidence:
        evidence_text = "；".join(item["text"] for item in evidence)
        lifestyle_text = "同期前后半段可比较的记录中，%s。" % evidence_text
    elif eligible:
        readable = "、".join(DOMAIN_NAMES[name] for name in eligible)
        lifestyle_text = "%s已有阶段记录，但前后半段的有效天数还不足以比较。" % readable
    else:
        lifestyle_text = "摄入、运动和睡眠记录尚不足以比较前后半段或形成阶段概括。"

    summary = "%s；%s%s" % (weight_text, lifestyle_text, NON_CAUSAL_LIMIT)
    evidence_lines = [weight_text] + [item["text"] for item in evidence]
    coverage_line = "%d 天窗口 · 体重 %d 天 · 饮食 %d 天 · 运动 %d 天 · 睡眠 %d 天" % (
        days,
        int(weight.get("recorded_days") or 0),
        intake["recorded_days"],
        activity["recorded_days"],
        sleep["recorded_days"],
    )
    return {
        "pattern_id": pattern_id,
        "title": title,
        "hook": hook,
        "summary": summary,
        "share_line": "%s｜%s" % (title, hook),
        "evidence": evidence_lines,
        "coverage_line": coverage_line,
        "comparable_domains": comparable,
        "changed_domains": [item["domain"] for item in changed],
        "dominant_record_domain": dominant,
        "non_judgemental": True,
    }


def _social_packaging(portrait: Mapping[str, object], days: int) -> dict:
    pattern_id = str(portrait.get("pattern_id") or "loading-signals")
    mechanisms = ["result_first", "numbers_proof"]
    if pattern_id == "scale-plot-twist":
        mechanisms.append("contrarian")
    elif pattern_id in ("loading-signals", "four-signals"):
        mechanisms.append("curiosity_gap")
    elif pattern_id in ("second-half-shift", "steady-rhythm"):
        mechanisms.append("before_after")
    title = str(portrait.get("title") or "这一段记录，有自己的剧情")
    hook = str(portrait.get("hook") or "先看结论，再看证据。")
    return {
        "cover_hook": title,
        "cover_subhook": hook,
        "hook_mechanisms": mechanisms,
        "proof_points": list(portrait.get("evidence") or [])[:3],
        "save_prompt": "保存这张，下一段 %d 天回来和自己对照" % days,
        "share_caption": "我的体重译报｜%s。%s数据只描述同期变化，不代表因果。" % (title, hook),
        "share_reason": "结论先行、证据可核对、默认隐藏身份与绝对体重",
        "clickbait": False,
        "privacy_safe": True,
    }


def _synthesis(weight: Mapping[str, object], intake: dict, activity: dict, sleep: dict, days: int) -> dict:
    portrait = _situation_portrait(weight, intake, activity, sleep, days)
    social = _social_packaging(portrait, days)
    observations = list(portrait["evidence"])
    eligible_domains = [name for name, value in (("intake", intake), ("activity", activity), ("sleep", sleep)) if value["claim_allowed"]]
    return {
        "headline": portrait["title"],
        "paragraph": portrait["summary"] + "未记录日也不能按零摄入、零运动或零睡眠处理。",
        "situation": portrait,
        "social_packaging": social,
        "observations": observations,
        "eligible_domains": eligible_domains,
        "limitations": [
            "摄入只统计有营养数据的记录日，未记录日不按 0 kcal 处理",
            "已记录运动消耗不是全天总能量消耗，不能与摄入相减为热量缺口",
            "睡眠只描述记录时长，不作医学判断",
            "同期变化不代表因果",
        ],
        "causal_claim": False,
        "prescription": False,
    }


def analyze_weight_management(
    weight_analysis: Mapping[str, object],
    diet_records: Optional[Iterable[Mapping[str, object]]] = None,
    exercise_records: Optional[Iterable[Mapping[str, object]]] = None,
    sleep_records: Optional[Iterable[Mapping[str, object]]] = None,
    *,
    days: Optional[int] = None,
    as_of: Optional[date] = None,
) -> dict:
    """Return a structured parallel analysis without inferring causality."""
    window_days = max(7, min(int(days or weight_analysis.get("window_days") or 14), 90))
    end = as_of or _date(weight_analysis.get("latest_date")) or date.today()
    start = end - timedelta(days=window_days - 1)
    intake = _diet_summary(diet_records or [], start, end, window_days)
    activity = _activity_summary(exercise_records or [], start, end, window_days)
    sleep = _sleep_summary(sleep_records or [], start, end, window_days)
    weight_coverage = float(weight_analysis.get("coverage_ratio") or 0.0)
    available = sum(1 for item in (intake, activity, sleep) if item["claim_allowed"])
    overall_label = "较完整" if available == 3 else ("部分完整" if available else "主要是体重记录")
    synthesis = _synthesis(weight_analysis, intake, activity, sleep, window_days)
    return {
        "window": {"days": window_days, "start": start.isoformat(), "end": end.isoformat()},
        "weight": {
            "recorded_days": int(weight_analysis.get("recorded_days") or 0),
            "coverage_ratio": round(weight_coverage, 3),
            "trend_claim_allowed": bool(weight_analysis.get("trend_claim_allowed")),
            "trend_delta": weight_analysis.get("trend_delta"),
        },
        "intake": intake,
        "activity": activity,
        "sleep": sleep,
        "coverage": {
            "weight": round(weight_coverage, 3),
            "intake": intake["coverage_ratio"],
            "activity": activity["coverage_ratio"],
            "sleep": sleep["coverage_ratio"],
            "eligible_lifestyle_domains": available,
            "overall_label": overall_label,
        },
        "synthesis": synthesis,
        "method": "daily_weight_median+theil_sen+parallel_recorded_lifestyle_summary",
    }
