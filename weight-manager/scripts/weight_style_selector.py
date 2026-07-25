"""Explainable, privacy-safe style selection for weight storytelling cards.

This module is intentionally independent from rendering.  It chooses among
the 24 declared storytelling templates using data eligibility, explicit user
preferences, recent history, and a small exploration budget.  It never reads
or scores BMI, sex, age, diagnoses, medication, or target weight.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from weight_card_styles import STYLE_CATALOG, STYLES_BY_ID, WeightCardStyle


VALID_SCENES = ("daily", "weekly", "milestone", "share")
VALID_TONES = ("auto", "gentle", "calm", "playful", "editorial", "bold")
VALID_DENSITIES = ("auto", "concise", "detailed")


MOMENT_STYLE_BOOSTS: Dict[str, Dict[str, float]] = {
    "prologue": {
        "no-verdict": 3.4,
        "ticket-journey": 1.8,
        "weather-now": 1.5,
        "body-letter": 1.45,
    },
    "plot-twist": {
        "editorial-headline": 2.2,
        "weekly-single": 2.0,
        "weather-now": 1.8,
        "direction-course": 1.65,
    },
    "clear-signal": {
        "rhythm-calendar": 1.85,
        "passport-stamps": 1.55,
        "observation-file": 1.45,
        "terrain-contour": 1.35,
    },
    "double-exposure": {
        "film-roll": 2.5,
        "data-fingerprint": 1.5,
        "observation-file": 1.35,
    },
    "quiet-current": {
        "terrain-contour": 1.55,
        "body-letter": 1.45,
        "rhythm-moon": 1.4,
        "capsule-seal": 1.3,
    },
    "long-view": {
        "terrain-valley": 1.9,
        "constellation": 1.85,
        "data-fingerprint": 1.75,
        "capsule-letter": 1.45,
        "vinyl-record": 1.4,
    },
    "welcome-back": {
        "body-letter": 1.8,
        "capsule-letter": 1.55,
        "ticket-journey": 1.45,
        "no-verdict": 1.35,
    },
    "four-signals": {
        "weekly-single": 2.1,
        "observation-file": 1.8,
        "constellation": 1.7,
        "passport-stamps": 1.35,
    },
    "second-half-shift": {
        "editorial-cover": 1.8,
        "direction-log": 1.7,
        "weekly-single": 1.65,
        "terrain-valley": 1.45,
    },
    "recording-spotlight": {
        "rhythm-calendar": 1.75,
        "observer-persona": 1.55,
        "data-fingerprint": 1.4,
    },
}


MOMENT_COPY = {
    "prologue": {
        "label": "故事刚刚开始",
        "share_line": "这不是空白，是身体故事的序章。",
    },
    "plot-twist": {
        "label": "今天出现了剧情反转",
        "share_line": "今天的波动和长期方向，讲了两件不同的事。",
    },
    "clear-signal": {
        "label": "信号正在变清楚",
        "share_line": "不是每一天都一样，但记录已经开始连成线。",
    },
    "double-exposure": {
        "label": "发现一格双重曝光",
        "share_line": "同一天的多次记录，被折叠成了一枚更稳的中位数。",
    },
    "quiet-current": {
        "label": "捕捉到一段安静水流",
        "share_line": "稳定不是没有变化，是变化暂时没有改写方向。",
    },
    "long-view": {
        "label": "长线视野已解锁",
        "share_line": "时间足够长，身体终于不必被一天代表。",
    },
    "welcome-back": {
        "label": "记录重新接上了",
        "share_line": "中间有空白也没关系，今天可以继续往下写。",
    },
    "four-signals": {
        "label": "四线同框",
        "share_line": "体重、摄入、运动和睡眠，终于能在同一张阶段肖像里见面。",
    },
    "second-half-shift": {
        "label": "后半场换挡",
        "share_line": "至少两条生活记录线，在后半段出现了可比较的变化。",
    },
    "recording-spotlight": {
        "label": "发现记录聚光灯",
        "share_line": "这一阶段有一类记录明显更连续，先让它把故事讲清楚。",
    },
}


def _date_ordinal(value: object) -> Optional[int]:
    text = str(value or "")[:10]
    try:
        parts = [int(item) for item in text.split("-")]
        if len(parts) != 3:
            return None
        # Gregorian ordinal without importing the parent analysis module.
        import datetime
        return datetime.date(parts[0], parts[1], parts[2]).toordinal()
    except (TypeError, ValueError):
        return None


def detect_story_moments(analysis: Mapping[str, object]) -> List[dict]:
    """Return fun but non-judgemental moments derived from recording behavior."""
    moments: List[str] = []
    recorded_days = int(analysis.get("recorded_days") or 0)
    span_days = int(analysis.get("span_days") or 0)
    measurement_count = int(analysis.get("measurement_count") or 0)
    coverage = float(analysis.get("coverage_ratio") or 0.0)
    state = str(analysis.get("state") or "")

    if recorded_days < 4:
        moments.append("prologue")
    if state in ("daily_up_trend_down", "daily_down_trend_up"):
        moments.append("plot-twist")
    if recorded_days >= 7 and coverage >= 0.7:
        moments.append("clear-signal")
    if measurement_count > recorded_days and recorded_days > 0:
        moments.append("double-exposure")
    if state == "stable" and bool(analysis.get("trend_claim_allowed")):
        moments.append("quiet-current")
    if span_days >= 28 and recorded_days >= 10:
        moments.append("long-view")

    dates = []
    for item in analysis.get("daily_records") or []:
        if isinstance(item, Mapping):
            ordinal = _date_ordinal(item.get("date"))
            if ordinal is not None:
                dates.append(ordinal)
    if any(second - first >= 5 for first, second in zip(dates, dates[1:])):
        moments.append("welcome-back")

    management = analysis.get("management") or {}
    synthesis = management.get("synthesis") if isinstance(management, Mapping) else {}
    situation = synthesis.get("situation") if isinstance(synthesis, Mapping) else {}
    pattern = str(situation.get("pattern_id") or "") if isinstance(situation, Mapping) else ""
    if pattern in ("four-signals", "steady-rhythm"):
        moments.append("four-signals")
    elif pattern == "second-half-shift":
        moments.extend(("four-signals", "second-half-shift"))
    elif pattern == "recording-spotlight":
        moments.append("recording-spotlight")

    return [{"id": moment_id, **MOMENT_COPY[moment_id]} for moment_id in moments]


def observer_persona(analysis: Mapping[str, object]) -> dict:
    """Assign an identity label using recording behavior, never health outcome."""
    recorded_days = int(analysis.get("recorded_days") or 0)
    measurement_count = int(analysis.get("measurement_count") or 0)
    coverage = float(analysis.get("coverage_ratio") or 0.0)
    span_days = int(analysis.get("span_days") or 0)
    if recorded_days < 4:
        return {"id": "new-observer", "label": "刚刚启程的人", "basis": "记录仍在序章"}
    if span_days >= 28 and recorded_days >= 10:
        return {"id": "long-view-observer", "label": "长线观察者", "basis": "观察跨度较长"}
    if measurement_count > recorded_days * 1.25:
        return {"id": "detail-observer", "label": "细节观察者", "basis": "有多个同日记录"}
    if recorded_days >= 7 and coverage >= 0.75:
        return {"id": "rhythm-collector", "label": "节律收藏家", "basis": "记录覆盖较连续"}
    return {"id": "steady-observer", "label": "稳稳记录者", "basis": "正在积累个人记录"}


def _eligible(style: WeightCardStyle, analysis: Mapping[str, object]) -> Tuple[bool, Optional[str]]:
    recorded_days = int(analysis.get("recorded_days") or 0)
    if recorded_days < style.min_recorded_days:
        return False, "至少需要 %d 个记录日" % style.min_recorded_days
    if style.requires_trend and not bool(analysis.get("trend_claim_allowed")):
        return False, "需要已经允许陈述的稳健趋势"
    unavailable = [domain for domain in style.required_domains if not _domain_available(analysis, domain)]
    if unavailable:
        return False, "缺少模板要求的同期数据：%s" % "、".join(unavailable)
    return True, None


def _domain_available(analysis: Mapping[str, object], domain: str) -> bool:
    if domain == "weight":
        return int(analysis.get("recorded_days") or 0) > 0
    if domain == "recording":
        return int(analysis.get("measurement_count") or 0) > 0
    management = analysis.get("management") or {}
    if not isinstance(management, Mapping):
        return False
    if domain == "synthesis":
        coverage = management.get("coverage") or {}
        return int(coverage.get("eligible_lifestyle_domains") or 0) > 0
    value = management.get(domain) or {}
    return isinstance(value, Mapping) and bool(value.get("claim_allowed"))


def _normalise(weights: Mapping[str, float]) -> Dict[str, float]:
    positive = {key: max(float(value), 0.0) for key, value in weights.items() if value > 0}
    total = sum(positive.values())
    if total <= 0:
        return {}
    result = {key: value / total for key, value in positive.items()}
    # Keep the public result stable and make its rounded sum exactly one.
    rounded = {key: round(value, 8) for key, value in result.items()}
    if rounded:
        largest = max(rounded, key=rounded.get)
        rounded[largest] = round(rounded[largest] + (1.0 - sum(rounded.values())), 8)
    return rounded


def _seed_number(seed: object) -> int:
    digest = hashlib.sha256(str(seed if seed is not None else "mediwise-style").encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def derive_style_seed(member_key: object, latest_date: object, generation_index: int = 0) -> str:
    """Create a reproducible seed without returning the member identifier."""
    raw = "%s|%s|%d" % (member_key or "anonymous", latest_date or "undated", int(generation_index or 0))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _weighted_pick(probabilities: Mapping[str, float], rng: random.Random) -> str:
    cursor = rng.random()
    cumulative = 0.0
    last = None
    for style_id in sorted(probabilities):
        last = style_id
        cumulative += probabilities[style_id]
        if cursor <= cumulative:
            return style_id
    if last is None:
        raise ValueError("cannot select from empty probability map")
    return last


def _signature(style: WeightCardStyle, seed: object) -> dict:
    digest = hashlib.sha256((style.id + "|" + str(seed)).encode("utf-8")).hexdigest()
    return {
        "edition": "%s-%s" % (style.family.upper()[:3], digest[:4].upper()),
        "palette_variant": int(digest[4:6], 16) % 6,
        "composition_variant": int(digest[6:8], 16) % 8,
        "texture_seed": digest[8:20],
        "reproducible": True,
    }


def select_weight_card_style(
    analysis: Mapping[str, object],
    *,
    scene: str = "daily",
    tone: str = "auto",
    density: str = "auto",
    preferred_styles: Optional[Iterable[str]] = None,
    disliked_styles: Optional[Iterable[str]] = None,
    recent_styles: Optional[Sequence[str]] = None,
    pinned_style: Optional[str] = None,
    surprise_level: float = 0.5,
    seed: object = None,
) -> dict:
    """Choose a style and return a complete, explainable probability trace."""
    if scene not in VALID_SCENES:
        raise ValueError("invalid scene: %s" % scene)
    if tone not in VALID_TONES:
        raise ValueError("invalid tone: %s" % tone)
    if density not in VALID_DENSITIES:
        raise ValueError("invalid density: %s" % density)
    surprise_level = min(max(float(surprise_level), 0.0), 1.0)
    preferred = {item for item in (preferred_styles or []) if item in STYLES_BY_ID}
    disliked = {item for item in (disliked_styles or []) if item in STYLES_BY_ID}
    recent = [item for item in (recent_styles or []) if item in STYLES_BY_ID][-6:]
    recent_counts = Counter(recent[-3:])
    last_style = STYLES_BY_ID.get(recent[-1]) if recent else None
    moments = detect_story_moments(analysis)
    moment_ids = {item["id"] for item in moments}

    eligibility = {}
    raw_weights: Dict[str, float] = {}
    traces: Dict[str, List[str]] = {}
    for style in STYLE_CATALOG:
        allowed, disabled_reason = _eligible(style, analysis)
        eligibility[style.id] = {
            "eligible": allowed,
            "disabled_reason": disabled_reason,
        }
        if not allowed:
            continue
        weight = style.base_weight
        trace = ["基础权重 %.2f" % style.base_weight]

        scene_factor = 1.5 if scene in style.scenes else 0.32
        weight *= scene_factor
        if scene in style.scenes:
            trace.append("适合%s场景" % scene)

        if tone != "auto":
            tone_factor = 1.55 if tone in style.tones else 0.58
            weight *= tone_factor
            if tone in style.tones:
                trace.append("匹配%s语气" % tone)
        if density != "auto":
            density_factor = 1.3 if density in style.densities else 0.68
            weight *= density_factor
            if density in style.densities:
                trace.append("匹配%s信息密度" % density)

        matched_domains = [domain for domain in style.preferred_domains if _domain_available(analysis, domain)]
        if matched_domains:
            weight *= 1.28
            trace.append("当前有%s同期证据" % "、".join(matched_domains))
        else:
            weight *= 0.55
            trace.append("主导信号记录不足，已降低出现概率")

        if style.id in preferred:
            weight *= 1.8
            trace.append("用户喜欢过")
        if style.id in disliked:
            weight *= 0.03
            trace.append("用户要求少出现")

        if recent and style.id == recent[-1]:
            weight *= 0.30
            trace.append("刚刚出现过，已降低重复")
        if recent_counts.get(style.id, 0) >= 2:
            weight *= 0.15
            trace.append("最近三次重复较多")
        if last_style and last_style.family == style.family and last_style.id != style.id:
            weight *= 0.68
            trace.append("上一张属于同一母风格")

        for moment_id in moment_ids:
            factor = MOMENT_STYLE_BOOSTS.get(moment_id, {}).get(style.id)
            if factor:
                weight *= factor
                trace.append("响应趣味时刻「%s」" % MOMENT_COPY[moment_id]["label"])

        raw_weights[style.id] = max(weight, 0.000001)
        traces[style.id] = trace

    eligible_ids = list(raw_weights)
    if not eligible_ids:
        raise ValueError("no eligible weight-card style")

    if pinned_style:
        if pinned_style not in STYLES_BY_ID:
            raise ValueError("unknown pinned style: %s" % pinned_style)
        if pinned_style not in raw_weights:
            raise ValueError("pinned style is not eligible: %s" % pinned_style)
        probabilities = {style_id: (1.0 if style_id == pinned_style else 0.0) for style_id in eligible_ids}
        selected_id = pinned_style
        exploration = False
        exploration_rate = 0.0
        traces[selected_id].append("用户已固定此模板")
    else:
        match_probabilities = _normalise(raw_weights)
        # Exploration flattens the distribution and favours families not just seen.
        explore_weights = {}
        seen_families = {STYLES_BY_ID[item].family for item in recent}
        for style_id, weight in raw_weights.items():
            style = STYLES_BY_ID[style_id]
            novelty = 1.55 if style.family not in seen_families else 0.62
            rarity = {"common": 0.85, "uncommon": 1.15, "rare": 1.5}[style.rarity]
            dislike_guard = 0.05 if style_id in disliked else 1.0
            explore_weights[style_id] = math.sqrt(weight) * novelty * rarity * dislike_guard
        explore_probabilities = _normalise(explore_weights)
        exploration_rate = round(0.08 + 0.10 * surprise_level, 4)
        probabilities = _normalise({
            style_id: (1.0 - exploration_rate) * match_probabilities.get(style_id, 0.0)
            + exploration_rate * explore_probabilities.get(style_id, 0.0)
            for style_id in raw_weights
        })
        rng = random.Random(_seed_number(seed))
        exploration = rng.random() < exploration_rate
        source = explore_probabilities if exploration else match_probabilities
        selected_id = _weighted_pick(source, rng)

    selected = STYLES_BY_ID[selected_id]
    selected_reasons = [item for item in traces[selected_id] if not item.startswith("基础权重")]
    if not selected_reasons:
        selected_reasons.append("与当前可用数据和场景相容")
    selected_reasons.append(selected.signature)

    ranked = sorted(probabilities.items(), key=lambda item: (-item[1], item[0]))
    return {
        "selected_style": selected.public_dict(),
        "probabilities": {style_id: probability for style_id, probability in ranked},
        "eligible_styles": [style_id for style_id, _ in ranked],
        "eligibility": eligibility,
        "reasons": selected_reasons,
        "exploration": exploration,
        "exploration_rate": exploration_rate,
        "story_moments": moments,
        "observer_persona": observer_persona(analysis),
        "visual_signature": _signature(selected, seed),
        "selection_policy": {
            "non_uniform": True,
            "anti_repeat": True,
            "explicit_preference": True,
            "health_traits_used_for_aesthetics": [],
            "eligibility_uses": ["recorded_days", "trend_claim_allowed", "required_record_domains"],
            "aesthetic_uses": ["scene", "tone", "density", "available_record_domains", "likes", "dislikes", "recent_styles", "surprise_level"],
        },
    }
