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

from .adapters import DEFAULT_DOMAIN, companions_for, fill_slots, get_adapter, lexicon_for
from .catalog import STYLE_CATALOG, STYLES_BY_ID, StoryStyle


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


def detect_story_moments(
    analysis: Mapping[str, object], domain: str = DEFAULT_DOMAIN
) -> List[dict]:
    """Return fun but non-judgemental moments derived from recording behavior.

    The last three moments are companion moments: their copy names the domains a
    card is read *alongside*, so they are gated on `companions_for(domain)` the
    same way `render._management_details` gates its companion axis.  Without that
    gate the protection is only incidental — a host that filled in `management` for a
    non-weight domain would put 「体重、摄入、运动和睡眠」 on a sleep card, and no
    forbidden-word scan would catch it, because the leak is another domain's
    subject rather than a verdict.
    """
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

    management = analysis.get("management") or {} if companions_for(domain) else {}
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


def _coverage_normalised(analysis: Mapping[str, object], domain: str) -> Mapping[str, object]:
    """`analysis` with its coverage counts taken from the domain's own adapter.

    Returns the mapping unchanged when the adapter agrees, so `weight` -- whose
    `coverage_for` is pass-through by contract -- keeps object identity and cannot drift.
    The caller's dict is never mutated: a selection must not edit the analysis it was
    handed, or a later render would silently inherit the edit.
    """
    coverage = get_adapter(domain).coverage_for(analysis)
    routed = {
        "recorded_days": (int, int(coverage.get("recorded_days") or 0)),
        "measurement_count": (int, int(coverage.get("measurement_count") or 0)),
        "coverage_ratio": (float, float(coverage.get("ratio") or 0.0)),
    }
    # Compared after the same coercion the rules below apply -- `int(... or 0)`, not the
    # raw value.  An absent key and a routed 0 are the same number to every reader, so
    # treating them as a difference would hand back a copy that changes no decision, and
    # would break the identity `weight` relies on whenever its analysis omits a count.
    changed = {
        key: value
        for key, (cast, value) in routed.items()
        if cast(analysis.get(key) or cast(0)) != value
    }
    if not changed:
        return analysis
    return dict(analysis, **changed)


def _eligible(
    style: StoryStyle, analysis: Mapping[str, object], story_domain: str = DEFAULT_DOMAIN
) -> Tuple[bool, Optional[str]]:
    recorded_days = int(analysis.get("recorded_days") or 0)
    if recorded_days < style.min_recorded_days:
        return False, "至少需要 %d 个记录日" % style.min_recorded_days
    if style.requires_trend and not bool(analysis.get("trend_claim_allowed")):
        return False, "需要已经允许陈述的稳健趋势"
    unavailable = [
        tag for tag in style.required_domains if not _domain_available(analysis, tag, story_domain)
    ]
    if unavailable:
        return False, "缺少模板要求的同期数据：%s" % "、".join(unavailable)
    return True, None


def _domain_available(
    analysis: Mapping[str, object], domain: str, story_domain: str = DEFAULT_DOMAIN
) -> bool:
    """Is the evidence a style prefers present in this analysis?

    `domain` here is a catalog tag from `STYLE_PREFERRED_DOMAINS`, not a story
    domain: `weight` and `recording` ask about the card's own records, and the
    rest ask about the companion block.  Companion questions are gated on
    `story_domain`'s companion axis, so a domain that reads no companions cannot
    have a template's probability moved by companion evidence it never had.
    """
    if domain == "weight":
        return int(analysis.get("recorded_days") or 0) > 0
    if domain == "recording":
        return int(analysis.get("measurement_count") or 0) > 0
    if not companions_for(story_domain):
        return False
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


def _signature(style: StoryStyle, seed: object) -> dict:
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
    domain: str = DEFAULT_DOMAIN,
    lexicon: Optional[Mapping[str, str]] = None,
) -> dict:
    """Choose a style and return a complete, explainable probability trace.

    `domain` / `lexicon` reach no scoring rule: which template suits a window is
    decided by coverage, trend and scene, which every domain expresses the same
    way.  They are here only so the returned `reasons` can name the reading in the
    caller's words, since one style signature quotes it.
    """
    if scene not in VALID_SCENES:
        raise ValueError("invalid scene: %s" % scene)
    if tone not in VALID_TONES:
        raise ValueError("invalid tone: %s" % tone)
    if density not in VALID_DENSITIES:
        raise ValueError("invalid density: %s" % density)
    surprise_level = min(max(float(surprise_level), 0.0), 1.0)
    # `min_recorded_days` runs up to 14 across the catalog, and every gate below counts
    # recorded days off the analysis.  A caller handing over raw rows reports rows, so for
    # the seven folding domains fifteen rows spread across five dates unlocked templates
    # that exist precisely because they need ten or fourteen days of evidence -- the card
    # would tell a story its records cannot support.  `render_ready` cannot repair this:
    # it fills absent keys only, deliberately, so weight's analysis stays authoritative.
    # So the count is routed here, once, before any rule reads it.  For `weight` the
    # adapter passes these keys straight through, which is why the goldens do not move.
    analysis = _coverage_normalised(analysis, domain)
    preferred = {item for item in (preferred_styles or []) if item in STYLES_BY_ID}
    disliked = {item for item in (disliked_styles or []) if item in STYLES_BY_ID}
    recent = [item for item in (recent_styles or []) if item in STYLES_BY_ID][-6:]
    recent_counts = Counter(recent[-3:])
    last_style = STYLES_BY_ID.get(recent[-1]) if recent else None
    moments = detect_story_moments(analysis, domain)
    moment_ids = {item["id"] for item in moments}

    eligibility = {}
    raw_weights: Dict[str, float] = {}
    traces: Dict[str, List[str]] = {}
    for style in STYLE_CATALOG:
        allowed, disabled_reason = _eligible(style, analysis, domain)
        # `no-verdict` turns insufficient evidence into an honest visual theme. Once
        # a robust long-run number exists, choosing it automatically makes the style
        # name and its "还缺什么" copy contradict the card's own estimate. An explicit
        # pin still wins: pinning is an authored design request, not auto narration.
        if (
            allowed
            and style.id == "no-verdict"
            and pinned_style != style.id
            and analysis.get("trend_delta") is not None
        ):
            allowed = False
            disabled_reason = "已有可陈述的稳健方向"
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

        matched_domains = [
            tag for tag in style.preferred_domains if _domain_available(analysis, tag, domain)
        ]
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
    words = dict(lexicon) if lexicon else dict(lexicon_for(domain))
    selected_reasons.append(fill_slots(selected.signature, words))

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
