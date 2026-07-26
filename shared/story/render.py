"""Dynamic renderers for the MediWise 译报 card system.

Professional analysis is supplied by each domain's analysis module.  This module
only changes narrative form and visual structure.  All 24 styles use the same
analysis facts and privacy flags; none may invent a diagnosis, cause, promise,
or treatment prescription.

Every user-visible domain noun here comes from a `lexicon` (see
`shared/story/adapters/`).  A literal 体重 / 秤面 / kg in this file is a contract
violation per story-design/story-system.md: the renderer draws shapes, and the
adapter supplies the words that name them.
"""

from __future__ import annotations

import html
import math
import random
from datetime import datetime
from typing import List, Mapping, Optional, Sequence, Tuple

from .adapters import (
    COPY_SLOTS,
    DEFAULT_DOMAIN,
    companions_for,
    fill_slots,
    get_adapter,
    PRODUCT_NAME_TEMPLATE,
    latin_tag_for,
    lexicon_for,
    no_companion_copy_for,
    prescription_noun_for,
)
from .catalog import STYLES_BY_ID


CARD_WIDTH = 1080
CARD_HEIGHT = 1440
COMPASS_MAX_DEGREES = 32.0
COMPASS_STRENGTH_DEGREES = 28.0

# `PRODUCT_NAME_TEMPLATE` is imported from `adapters`, which owns it: the CLI's JSON
# envelope builds the same name from the same subject, and one template means the
# card and the envelope cannot disagree about what the card is called.
DISCLAIMER_TEMPLATE = "相关线索不代表因果；本卡不提供诊断或%s。"

# Weight-valued aliases.  Kept as module constants because `weight_story_card`
# re-exports both names and tests outside this package assert on their values.
PRODUCT_NAME = PRODUCT_NAME_TEMPLATE % "体重"
DISCLAIMER = DISCLAIMER_TEMPLATE % "减重处方"

# The slot vocabulary and its filler live in `adapters/` beside the lexicon whose
# keys they are; the selector needs the same pass over `signature`.  Re-exported
# under the private names this module's call sites and contract tests already use.
_COPY_SLOTS = COPY_SLOTS
_fill = fill_slots


def _resolve_lexicon(lexicon: Optional[Mapping[str, str]] = None) -> dict:
    """Return the wording table to narrate with, defaulting to the default domain.

    Defaulting rather than requiring one keeps every existing weight caller —
    `weight_story_card`, the gallery generator, the golden-file harness — working
    unchanged, since the default domain is weight.
    """
    resolved = dict(lexicon_for(DEFAULT_DOMAIN))
    if lexicon:
        resolved.update({key: str(value) for key, value in lexicon.items()})
    return resolved


def _point_value(item: Mapping[str, object]) -> Optional[float]:
    """Read one series point's magnitude, whichever spelling the producer used.

    `weight_truth_card.build_daily_records` spells it `weight`; the Signal Frame
    spells the same number `value`.  Reading both means a frame-shaped series and
    a legacy weight analysis are equally renderable, and no other domain has to
    pretend its readings are weights to be drawn.
    """
    for key in ("value", "weight"):
        if key not in item:
            continue
        try:
            number = float(item[key])
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None
    return None


def series_source(analysis: Mapping[str, object]) -> List[Mapping[str, object]]:
    """Return the points to draw: the Signal Frame's series when there is one.

    An adapter's `series_for` exists precisely to turn a domain's own rows into
    one comparable point per recorded day — folding same-day repeats, picking the
    single narrated component, and spelling the magnitude `value`.  `render_ready`
    puts that result on the analysis as `frame["series"]`, so preferring it here is
    what lets a sleep card draw `duration_min` and an intake card draw
    `total_calories` without the renderer learning either name.

    The fallback matters just as much: a legacy weight analysis from
    `analyze_weight_records` carries no frame, and its rows already spell the
    magnitude `weight` and are already folded to one row per day by
    `aggregate_daily_medians`.  Those cards keep rendering byte-for-byte as before.
    """
    frame = analysis.get("frame")
    if isinstance(frame, Mapping):
        series = frame.get("series")
        if isinstance(series, Sequence) and not isinstance(series, (str, bytes)):
            points = [point for point in series if isinstance(point, Mapping)]
            if points:
                return points
    daily = analysis.get("daily_records") or []
    if not isinstance(daily, Sequence) or isinstance(daily, (str, bytes)):
        return []
    return [point for point in daily if isinstance(point, Mapping)]


# Copy is keyed on the nine shared shapes, never on a domain's own state names.
# That is what keeps the copy tables O(templates × shapes) instead of
# O(templates × shapes × domains): a sleep frame and a weight frame that both
# resolve to `flat-with-noise` read the same sentence, in their own words.
#
# `{up}` / `{down}` / `{today}` are filled from the active lexicon by `_fill`, so a
# card says 上浮 / 回落 for weight, 变长 / 变短 for sleep, 变密 / 变疏 for records
# without this table knowing which domain it is narrating.  Per story-system.md
# these words describe numeric direction only and never success or failure.
#
# `{today}` is the direction of the most recent recorded step.  It resolves to the
# lexicon's `up` or `down`, or to NEUTRAL_TODAY when the analysis carries no signed
# latest step at all — a shape is reachable without one, and inventing a direction
# to fill the sentence would be a claim the records do not support.
NEUTRAL_TODAY = "有变化"

CORE_SHAPE_COPY = {
    "insufficient": ("记录还在序章", "当前记录不足以判断长期方向"),
    "today-vs-trend-conflict": ("今天{today}，长期方向未改变", "单日变化与稳健长期趋势方向不同"),
    "sustained-rise": ("短期与长期方向一致", "当前记录显示两个时间尺度方向相同"),
    "sustained-fall": ("短期与长期方向一致", "当前记录显示两个时间尺度方向相同"),
    "flat-with-noise": ("今天{today}，长期仍近似稳定", "一天的变化尚未改写稳健趋势"),
    "stable": ("海面有动，长期方向近似稳定", "稳定不是没有变化，而是变化暂未改写方向"),
    "rebuilding": ("中间空了一段，记录又接上了", "断档前后不连成一条趋势，这里只说重新开始记录"),
    "spotlight": ("这段时间，只有一条线记得比较全", "其余信号覆盖不足，卡片只讲有记录的那一条"),
    "multi-signal": ("几条线同时有记录，可以并排看", "并排只是同期发生，不做跨域计算，也不推因果"),
}

# The legacy weight states, and which shape and direction each one resolves to.
# Only legacy callers reach this: a Signal Frame carries `shape` outright, so no new
# domain has to invent states to be renderable.  It mirrors the weight adapter's own
# `SHAPE_BY_STATE` and is verified against it by the story contract tests, so the two
# cannot drift; it is spelled out here rather than imported because the renderer must
# not depend on one particular domain module to do its job.
_LEGACY_STATE_SHAPE = {
    "insufficient": ("insufficient", None),
    "daily_up_trend_down": ("today-vs-trend-conflict", "up"),
    "daily_down_trend_up": ("today-vs-trend-conflict", "down"),
    "sustained_up": ("sustained-rise", None),
    "sustained_down": ("sustained-fall", None),
    "daily_up_stable": ("flat-with-noise", "up"),
    "daily_down_stable": ("flat-with-noise", "down"),
    "stable": ("stable", None),
}


# Also keyed on shape.  A value is either one string, or a `{direction: string}` map
# for the shapes whose families author genuinely different prose per direction —
# 短时有云 and 短时转晴 are not the same sentence with a word swapped, so a single
# `{today}` slot could not reproduce them.  A shape absent from a family falls back
# to that shape's core title, which is how `sustained-*` and `flat-with-noise` have
# always behaved; the fallback is deliberate, not a gap waiting to be filled.
FAMILY_SHAPE_HEADLINES = {
    "weather": {
        "insufficient": "观测天气，正在形成",
        "today-vs-trend-conflict": {"up": "短时有云，长期气流未改", "down": "短时转晴，长期气流未改"},
        "stable": "今日微风，长期平稳",
        "rebuilding": "观测中断过，气象站又开机了",
        "spotlight": "只有一个观测站持续在报数",
        "multi-signal": "几个观测站同时在报数",
    },
    "direction": {
        "insufficient": "先把点连起来，再谈航向",
        "today-vs-trend-conflict": {"up": "今天有浪，航向没变", "down": "今天退潮，航向还没掉头"},
        "stable": "海面有动，航向近乎水平",
        "rebuilding": "航海日志空了几页，这一页重新写起",
        "spotlight": "只有一条航线留下了连续记录",
        "multi-signal": "几条航线同时留下了记录",
    },
    "terrain": {
        "insufficient": "地形仍在显影",
        "today-vs-trend-conflict": {
            "up": "眼前是坡，整段路仍向原方向延伸",
            "down": "眼前是谷，整段路仍向原方向延伸",
        },
        "stable": "这是一段缓坡，不是一条直线",
        "rebuilding": "地图中间有空白，路从这里接上",
        "spotlight": "只有一条等高线是完整的",
        "multi-signal": "几条等高线同时可读",
    },
    "editorial": {
        "insufficient": "本期头条：暂不下结论",
        "today-vs-trend-conflict": {"up": "一日{up}，并未改写长期趋势", "down": "一日{down}，并未改写长期趋势"},
        "stable": "变化存在，方向近似稳定",
        "rebuilding": "停刊一段后，本期复刊",
        "spotlight": "本期只有一条线索够写",
        "multi-signal": "本期有几条线索可以并排刊出",
    },
    "capsule": {
        "insufficient": "先封存今天，不急着解释",
        "today-vs-trend-conflict": {
            "up": "把今天的浪，留给更长的时间回答",
            "down": "把今天的退潮，留给更长的时间回答",
        },
        "stable": "封存一段平静但并不静止的日子",
        "rebuilding": "封存中断过，这一封重新开始",
        "spotlight": "这一封里，只有一件事记得完整",
        "multi-signal": "这一封里，装进了好几条记录",
    },
    "film": {
        "insufficient": "第一格胶片，已经装进来了",
        "today-vs-trend-conflict": {"up": "这一格{up}，不代表整卷胶片", "down": "这一格{down}，不代表整卷胶片"},
        "stable": "每一格不同，整卷仍有自己的节奏",
        "rebuilding": "中间有几格空白，机器又转起来了",
        "spotlight": "只有一卷胶片是连续的",
        "multi-signal": "几卷胶片可以并排看",
    },
    "rhythm": {
        "insufficient": "节拍刚刚开始",
        "today-vs-trend-conflict": {"up": "今天换了拍，整段节奏未变", "down": "今天轻了一拍，整段节奏未变"},
        "rebuilding": "节拍停过，又重新数起来",
        "spotlight": "只有一个声部在持续打拍",
        "multi-signal": "几个声部同时在打拍",
        "stable": "变化有节拍，方向近似稳定",
    },
    "journey": {
        "insufficient": "这是一张启程票",
        "today-vs-trend-conflict": {"up": "这一次颠簸，没有改写路线", "down": "这一站{down}，路线仍未改变"},
        "rebuilding": "中间空了几站，这一段重新出发",
        "spotlight": "只有一条线路有连续班次",
        "multi-signal": "几条线路同时有班次",
        "stable": "列车在走，路线近似平稳",
    },
    "music": {
        "insufficient": "序曲已经落针",
        "today-vs-trend-conflict": {
            "up": "今天升调，整首歌仍沿原来的旋律",
            "down": "今天降调，整首歌仍沿原来的旋律",
        },
        "rebuilding": "曲子停过一段，现在重新落针",
        "spotlight": "只有一条旋律线是完整的",
        "multi-signal": "几条旋律线同时完整",
        "stable": "每一拍都不同，主旋律近似稳定",
    },
    "letter": {
        "insufficient": "今天，我只想请你继续认识我",
        "today-vs-trend-conflict": {
            "up": "今天的数字变了，但我没有突然变成另一个故事",
            "down": "今天的数字{down}，也不需要替整段时间下结论",
        },
        "rebuilding": "我有一段时间没留下记录，现在又开始了",
        "spotlight": "这段时间，我只把一件事记得比较全",
        "multi-signal": "这段时间，我把好几件事都记了下来",
        "stable": "我一直在变化，只是方向暂时很安静",
    },
    "identity": {
        "insufficient": "你是刚刚启程的人",
        "today-vs-trend-conflict": {
            "up": "你在看一段路，而不是审判一天",
            "down": "你在保存变化，而不是追逐一个数字",
        },
        "rebuilding": "你把中断过的记录重新接上了",
        "spotlight": "你把一件事记得很完整",
        "multi-signal": "你同时在记录好几条线",
        "stable": "你正在收藏身体的节律",
    },
    "generative": {
        "insufficient": "第一颗记录点已经亮起",
        "today-vs-trend-conflict": {"up": "一颗星偏离了轨迹，星群方向未变", "down": "一颗星{down}，星群方向未变"},
        "rebuilding": "星图空了一块，新的点又亮起来",
        "spotlight": "只有一片星区足够亮",
        "multi-signal": "几片星区同时亮着",
        "stable": "点在移动，星群近似稳定",
    },
}


def _legacy_state_copy():
    """Rebuild the old state-keyed tables from the shape-keyed ones.

    `weight-manager/scripts/weight_story_card.py` re-exports `CORE_STATE_COPY` and
    `FAMILY_HEADLINES`, and story-system.md lists both on the compatibility surface,
    so the names stay bound and hold exactly what they held before the re-key.
    Deriving them rather than maintaining a second copy is the point: a future edit
    to the shape tables cannot leave a stale duplicate behind, and a state whose
    shape has no authored family entry drops out here just as it fell back before.
    """
    core, families = {}, {family: {} for family in FAMILY_SHAPE_HEADLINES}
    for state, (shape, direction) in _LEGACY_STATE_SHAPE.items():
        token = "{%s}" % direction if direction else NEUTRAL_TODAY
        title, status = CORE_SHAPE_COPY[shape]
        core[state] = (title.replace("{today}", token), status.replace("{today}", token))
        for family, table in FAMILY_SHAPE_HEADLINES.items():
            value = table.get(shape)
            if isinstance(value, Mapping):
                value = value.get(direction)
            if value:
                families[family][state] = value.replace("{today}", token)
    return core, families


CORE_STATE_COPY, FAMILY_HEADLINES = _legacy_state_copy()


STYLE_CONTENT_ROLES = {
    "weather-now": "live-weather-snapshot",
    "weather-week": "observation-forecast-strip",
    "direction-course": "short-versus-long-course",
    "direction-log": "evidence-logbook",
    "terrain-contour": "variation-landscape",
    "terrain-valley": "stage-route-recap",
    "editorial-cover": "evidence-led-cover-story",
    "editorial-headline": "single-fact-headline",
    "capsule-seal": "stage-memory-seal",
    "capsule-letter": "future-facing-letter",
    "film-roll": "recent-moments-sequence",
    "film-grid": "nine-moment-contact-sheet",
    "rhythm-calendar": "recording-cadence-calendar",
    "rhythm-moon": "coverage-phase-cycle",
    "ticket-journey": "observation-departure-ticket",
    "passport-stamps": "recording-milestone-passport",
    "vinyl-record": "two-timescale-album",
    "weekly-single": "one-insight-single",
    "body-letter": "compassionate-body-letter",
    "no-verdict": "uncertainty-prologue",
    "observer-persona": "recording-behaviour-persona",
    "observation-file": "private-observation-dossier",
    "constellation": "minimal-data-constellation",
    "data-fingerprint": "minimal-data-fingerprint",
}


MOMENT_VISIBLE_STYLES = {
    "weather-now",
    "direction-course",
    "editorial-headline",
    "film-roll",
    "ticket-journey",
    "weekly-single",
    "body-letter",
}


CONTEXT_VISIBLE_STYLES = {
    "direction-log",
    "editorial-cover",
    "rhythm-calendar",
    "rhythm-moon",
    "body-letter",
    "no-verdict",
    "observation-file",
}


def _signed(value: object, digits: int = 1) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    if abs(number) < 0.05:
        number = 0.0
    sign = "+" if number > 0 else ("−" if number < 0 else "")
    return "%s%.*f" % (sign, digits, abs(number))


def _safe(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _css_string(value: object) -> str:
    """Escape a word for use inside a CSS `content:"…"` declaration.

    `_safe` is wrong here: `<style>` is raw text, so its `&quot;` would render as
    six literal characters on the card.  A quote, backslash, newline or `<` would
    each break out of the declaration or the element, so they are dropped rather
    than encoded — every value reaching here is an authored domain noun, and none
    of them legitimately contains any of these.
    """
    return "".join(ch for ch in str(value or "") if ch not in '"\\\n\r<')


def _analysis_details(
    analysis: Mapping[str, object],
    lexicon: Optional[Mapping[str, str]] = None,
    domain: str = DEFAULT_DOMAIN,
) -> dict:
    """Derive privacy-safe relative facts for style-specific editorial choices.

    Coverage comes from the domain's own `coverage_for`, not from the analysis keys
    directly.  The two agree for weight, whose adapter passes `recorded_days` and
    `measurement_count` through because `weight_truth_card` is the authority on its
    own window — but the other seven recompute them from dates, because for those
    domains the host's `recorded_days` counts raw rows and the card counts days.
    Reading the analysis here left the printed card able to disagree with the Signal
    Frame a consumer reads for the same window; the adapters' marker paragraphs
    (`records.py:213`, `activity.py`, `intake.py`, `adherence.py`, `family.py`)
    name this function as the seam that closes it.
    """
    words = _resolve_lexicon(lexicon)
    unit = " " + words["unit"]
    values = []
    for item in series_source(analysis):
        value = _point_value(item)
        if value is None:
            continue
        values.append(value)
    changes = [abs(second - first) for first, second in zip(values, values[1:])]
    range_delta = max(values) - min(values) if values else None
    net_delta = values[-1] - values[0] if len(values) >= 2 else None
    mean_swing = sum(changes) / len(changes) if changes else None
    max_swing = max(changes) if changes else None
    coverage_block = get_adapter(domain).coverage_for(analysis)
    longest_gap = int(coverage_block.get("longest_gap_days") or 0)
    recorded_days = int(coverage_block.get("recorded_days") or 0)
    measurement_count = int(coverage_block.get("measurement_count") or 0)
    coverage = float(coverage_block.get("ratio") or 0.0)
    return {
        "net_value": _signed(net_delta) + (unit if net_delta is not None else ""),
        "range_value": ("%.1f%s" % (range_delta, unit)) if range_delta is not None else "—",
        "mean_swing": ("%.2f%s" % (mean_swing, unit)) if mean_swing is not None else "—",
        "max_swing": ("%.1f%s" % (max_swing, unit)) if max_swing is not None else "—",
        "longest_gap": "%d 天" % longest_gap,
        # Extra measurements, not days holding more than one — the card reads
        # 「同日复测 N 次」.  `coverage_block["repeat_days"]` is the other number, and the
        # adapters' docstrings are explicit that the two diverge the moment one day holds
        # three, so this stays a subtraction rather than becoming that key.
        "repeat_count": str(max(measurement_count - recorded_days, 0)),
        "measurement_count": str(measurement_count),
        "coverage_percent": "%d%%" % int(round(coverage * 100)),
        # `_view_model` prints both of these directly, and takes them from here rather
        # than re-reading the analysis so one card cannot show a count in its stat block
        # that disagrees with its own coverage line.
        "recorded_days": str(recorded_days),
        "span_days": str(int(coverage_block.get("span_days") or 0)),
    }


def _whole_signed(value: object, unit: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(number):
        return "—"
    sign = "+" if number > 0 else ("−" if number < 0 else "")
    return "%s%d%s" % (sign, int(round(abs(number))), unit)


def _duration_text(value: object) -> str:
    try:
        minutes = int(round(float(value)))
    except (TypeError, ValueError):
        return "—"
    hours, remainder = divmod(minutes, 60)
    return "%d 小时 %d 分" % (hours, remainder) if hours else "%d 分钟" % remainder


def _management_details(analysis: Mapping[str, object], domain: str = DEFAULT_DOMAIN) -> dict:
    # Gated at the read rather than at each use: every field below is derived from
    # `management`, including five that are host-supplied prose copied verbatim onto
    # the card (`headline`, `paragraph`, `situation.title/hook`, `share_caption`).
    # Those five are written by `synthesis._situation_portrait`, which names
    # 「体重、摄入、运动和睡眠」 in one sentence, so an ungated read hands a host the
    # ability to print weight's subject on a vitals card without tripping any
    # forbidden-word scan — the leaked token is another domain's subject, not a verdict.
    # Dropping the block here leaves exactly the state a domain with no companion
    # records already renders, which is what the green cross-domain sweeps assert.
    management = (analysis.get("management") or {}) if companions_for(domain) else {}
    intake = management.get("intake") or {}
    activity = management.get("activity") or {}
    sleep = management.get("sleep") or {}
    synthesis = management.get("synthesis") or {}
    situation = synthesis.get("situation") or {}
    social = synthesis.get("social_packaging") or {}
    coverage = management.get("coverage") or {}

    intake_days = int(intake.get("recorded_days") or 0)
    activity_days = int(activity.get("recorded_days") or 0)
    sleep_days = int(sleep.get("recorded_days") or 0)
    intake_average = intake.get("average_calories_on_recorded_days")
    activity_total = activity.get("total_duration_min")
    sleep_average = sleep.get("average_duration_min")
    intake_change = intake.get("change_calories")
    activity_change = activity.get("change_duration_min")
    sleep_change = sleep.get("change_min")

    intake_fact = (
        "饮食记录 %d 天，有记录日平均约 %d kcal" % (intake_days, int(round(float(intake_average))))
        if intake_average is not None else "饮食记录 %d 天，营养数据暂不足" % intake_days
    )
    if intake_change is not None:
        intake_fact += "，后半段较前半段 %s" % _whole_signed(intake_change, " kcal")
    activity_fact = (
        "运动记录 %d 天，共 %s" % (activity_days, _duration_text(activity_total))
        if activity_total is not None else "运动记录 %d 天，暂不足以概括阶段" % activity_days
    )
    if activity_change is not None:
        activity_fact += "，后半段总时长变化 %s" % _whole_signed(activity_change, " 分钟")
    sleep_fact = (
        "睡眠记录 %d 天，有记录日平均 %s" % (sleep_days, _duration_text(sleep_average))
        if sleep_average is not None else "睡眠记录 %d 天，暂不足以概括时长" % sleep_days
    )
    if sleep_change is not None:
        sleep_fact += "，后半段较前半段 %s" % _whole_signed(sleep_change, " 分钟")

    # Two separate questions, and conflating them is what put 睡眠 on a records card:
    # `has_companion_axis` is whether this domain reads companions at all, and
    # `has_management` is whether those companions have records to report right now.
    # Weight answers yes to the first either way, which is why a weight card with no
    # lifestyle data still prints "睡眠记录 0 天" — that is a coverage disclosure about
    # a relationship it really has.  Records answers no, so nothing downstream may
    # name a companion on its card, with or without data attached.
    has_companion_axis = bool(companions_for(domain))
    # `and has_companion_axis` is redundant now that the read above is gated, and it
    # stays anyway: it is the assertion a reader checks this line for, and it keeps the
    # invariant local instead of depending on a decision made forty lines up.
    has_management = bool(management) and has_companion_axis
    # The fallbacks below are the copy for a card with no companion axis, and they
    # are the only lines every one of the 24 templates prints, so they come from the
    # adapter rather than from here: a paragraph hardcoded in the shared renderer
    # names the same three domains on a records card, which knows nothing about them.
    no_companion = no_companion_copy_for(domain)
    return {
        "has_management": has_management,
        "has_companion_axis": has_companion_axis,
        "management_label": str(coverage.get("overall_label") or "生活方式记录待补充"),
        "intake_days": str(intake_days),
        "activity_days": str(activity_days),
        "sleep_days": str(sleep_days),
        "intake_value": ("约 %d kcal" % int(round(float(intake_average)))) if intake_average is not None else "记录不足",
        "activity_value": _duration_text(activity_total) if activity_total is not None else "记录不足",
        "sleep_value": _duration_text(sleep_average) if sleep_average is not None else "记录不足",
        "intake_change": _whole_signed(intake_change, " kcal"),
        "activity_change": _whole_signed(activity_change, " 分钟"),
        "sleep_change": _whole_signed(sleep_change, " 分钟"),
        "intake_fact": intake_fact,
        "activity_fact": activity_fact,
        "sleep_fact": sleep_fact,
        "synthesis_headline": str(synthesis.get("headline") or no_companion["headline"]),
        "synthesis_paragraph": str(synthesis.get("paragraph") or no_companion["paragraph"]),
        "situation_title": str(situation.get("title") or "这一段记录，有自己的剧情"),
        "situation_hook": str(situation.get("hook") or "先看结论，再看证据。"),
        "situation_pattern": str(situation.get("pattern_id") or "loading-signals"),
        "coverage_line": str(situation.get("coverage_line") or "记录覆盖正在形成"),
        "save_prompt": str(social.get("save_prompt") or "保存这张，留给下一段记录对照"),
        "share_caption": str(social.get("share_caption") or ""),
    }


ANALYSIS_LABELS = {
    "weather-now": "气象员综合简报", "weather-week": "恢复气候附注",
    "direction-course": "航向判读", "direction-log": "船长同期日志",
    "terrain-contour": "地形说明", "terrain-valley": "行程复盘",
    "editorial-cover": "本期编辑导语", "editorial-headline": "事实核查",
    "capsule-seal": "馆藏说明", "capsule-letter": "给未来的附言",
    "film-roll": "场记", "film-grid": "饮食联系印样说明",
    "rhythm-calendar": "节律编者按", "rhythm-moon": "睡眠轨道注释",
    "ticket-journey": "行程说明", "passport-stamps": "入境记录说明",
    "vinyl-record": "运动侧 Liner Notes", "weekly-single": "本周完整曲解",
    "body-letter": "来信正文", "no-verdict": "未完稿说明",
    "observer-persona": "卡牌背面分析", "observation-file": "档案结论",
    "constellation": "星图图例", "data-fingerprint": "作品说明",
}

# Three of those labels name the companion the template foregrounds, which reads wrong
# on a domain that has no companion axis: a records card cannot annotate a 睡眠轨道.
OWN_SUBJECT_ANALYSIS_LABELS = {
    "film-grid": "联系印样说明", "rhythm-moon": "观测轨道注释", "vinyl-record": "Liner Notes",
}


def _analysis_label(style_id: str, view: Mapping[str, object]) -> str:
    if not view.get("has_companion_axis") and style_id in OWN_SUBJECT_ANALYSIS_LABELS:
        return OWN_SUBJECT_ANALYSIS_LABELS[style_id]
    return ANALYSIS_LABELS[style_id]


def _style_analysis_text(style_id: str, view: Mapping[str, object]) -> str:
    if not view.get("has_management"):
        return str(view["synthesis_paragraph"])
    subject_fact = "%s层面：%s。" % (view["subject"], view["core_status"])
    coverage_fact = "同期覆盖饮食 %s 天、运动 %s 天、睡眠 %s 天。" % (
        view["intake_days"], view["activity_days"], view["sleep_days"]
    )
    # `preferred_domains[0]` is the *template's* emphasis slot, not the card's
    # domain: `"weight"` here reads as "foreground the card's own subject", which
    # is why these keys stay fixed while the wording above comes from the lexicon.
    domain = STYLES_BY_ID[style_id].preferred_domains[0]
    facts = {
        "weight": subject_fact + coverage_fact + "%s；%s；%s。" % (view["intake_fact"], view["activity_fact"], view["sleep_fact"]),
        "intake": "%s。%s%s另外，%s；%s。" % (view["intake_fact"], subject_fact, coverage_fact, view["activity_fact"], view["sleep_fact"]),
        "activity": "%s。%s%s另外，%s；%s。" % (view["activity_fact"], subject_fact, coverage_fact, view["intake_fact"], view["sleep_fact"]),
        "sleep": "%s。%s%s另外，%s；%s。" % (view["sleep_fact"], subject_fact, coverage_fact, view["intake_fact"], view["activity_fact"]),
        "recording": coverage_fact + "%s；%s；%s。%s" % (view["intake_fact"], view["activity_fact"], view["sleep_fact"], subject_fact),
        "synthesis": str(view["synthesis_paragraph"]),
    }
    if domain == "synthesis":
        return facts[domain]
    return "%s %s 同期变化只作为线索，不代表因果。" % (
        view["situation_hook"], facts.get(domain, str(view["synthesis_paragraph"]))
    )


def _synthesis_block(style_id: str, view: Mapping[str, object]) -> str:
    tag = ("article" if style_id in {"editorial-cover", "body-letter", "capsule-letter"}
           else "aside" if style_id in {"weather-now", "ticket-journey", "observer-persona"}
           else "section")
    return '<%s class="analysis-note analysis-%s" data-situation-pattern="%s"><small>%s</small><strong>%s</strong><p>%s</p><span>%s</span></%s>' % (
        tag, _safe(style_id), _safe(view["situation_pattern"]), _safe(_analysis_label(style_id, view)),
        _safe(view["situation_title"]), _safe(_style_analysis_text(style_id, view)), _safe(view["save_prompt"]), tag
    )


def _own_subject_frames(view: Mapping[str, str]) -> dict:
    """The twelve companion-emphasis frames, rewritten to speak only of the subject.

    Used for a domain with no companion axis.  The alternative — making those twelve
    templates ineligible — would leave such a domain nine cards instead of 24, and the
    catalog's whole claim is that the story shape, not the domain, picks the template.
    So each one keeps its metaphor and its editorial job and changes what it is about:
    the weekly climate band is drawn from the subject's own recorded days, the ship's
    log logs the subject's own course.

    Everything domain-specific here comes from the lexicon via `{slot}` tokens or from
    already-filled view values, so a domain registered later reads correctly without
    an entry being added below.
    """
    return {
        "weather-week": ("一周气候", "%s 个有记录日，连成一条气象带" % view["recorded_days"],
                         "覆盖 %s；没有记录的日子留白，不补成 0。" % view["coverage_percent"]),
        "direction-log": ("航海日志", "%s 个记录日，写进这本航海日志" % view["recorded_days"],
                          "净变化 %s，最大单步起伏 %s；日志只记发生过的事。" % (view["net_value"], view["max_swing"])),
        "terrain-valley": ("阶段穿越", "把 %s 个记录日，画成一段穿越路线" % view["recorded_days"],
                           "路径净变化 %s，穿越跨度 %s 天。" % (view["net_value"], view["span_days"])),
        "editorial-cover": ("本期刊物", "%s，是本期最值得核对的一件事" % view["daily_value"],
                            "%s；封面只放一个数字，其余退到证据席。" % view["core_status"]),
        "capsule-seal": ("阶段封存", "封存 %s 个有记录日" % view["recorded_days"],
                         "本期净变化 %s；未记录日不会被补成 0。" % view["net_value"]),
        "capsule-letter": ("写给下一次回看", "亲爱的未来，这一段的%s是 %s" % (view["reading"], view["daily_value"]),
                           "%s；今天不替未来做承诺。" % view["core_status"]),
        "film-grid": ("九格联系印样", "选九个真实记录日，不补造空白",
                      "整卷共 %s 次记录；空格是没有记录，不是零。" % view["measurement_count"]),
        "rhythm-moon": ("观测月相", "%s 个有记录日，生成这一轮月相" % view["recorded_days"],
                        "最长暗相 %s；月相只表示记录覆盖，不暗示生理因果。" % view["longest_gap"]),
        "ticket-journey": ("阶段行程", "一张从 %s 个记录日出发的车票" % view["recorded_days"],
                           "已经过 %s 天，路线净变化 %s；目的地不是某个%s数字。" % (
                               view["span_days"], view["net_value"], view["subject"])),
        "vinyl-record": ("阶段唱片", "A 面 %s 个记录日，B 面净变化 %s" % (view["recorded_days"], view["net_value"]),
                         "最大格间起伏 %s；唱片只播放已经录进去的部分。" % view["max_swing"]),
        "weekly-single": ("本周单曲", "《%s》" % view["synthesis_headline"],
                          "这一周的%s自己写完了 liner notes。" % view["subject"]),
        "data-fingerprint": ("数据指纹", "%s 个有记录日 · %s · 唯一生成" % (
            view["recorded_days"], view["coverage_percent"]),
            "纹理由已记录覆盖生成，未记录日不补零。"),
    }


def _story_frame(style_id: str, state: str, view: Mapping[str, str]) -> dict:
    """Give every template a distinct editorial job, not merely a visual skin."""
    insufficient = not view.get("trend_allowed")
    if insufficient:
        trend = "还不足以判断"
    elif not view.get("trend_fitted"):
        # Records enough, fit absent.  Reading the em dash out of `trend_value` would
        # work today and break the moment `_signed` changes its placeholder, so the
        # renderer is told the state instead of inferring it from formatted copy.
        trend = "暂无稳健拟合"
    else:
        trend = view["trend_value"]
    frames = {
        "weather-now": ("此刻天气", view["headline"], "今天的%s是 %s；长期气流为 %s。" % (view["reading"], view["daily_value"], trend)),
        "weather-week": ("恢复气候", "%s 个睡眠记录日，连成一条恢复气象带" % view["sleep_days"], view["sleep_fact"] + "。"),
        "direction-course": ("航向校准", view["headline"], "浪高 %s，航向 %s；两个时间尺度分开看。" % (view["daily_value"], trend)),
        "direction-log": ("运动航海日志", "%s 个运动日，写入身体航海日志" % view["activity_days"], view["activity_fact"] + "。"),
        "terrain-contour": ("变化地形", "%s 的起伏，生成这张等高线" % view["range_value"], "路径净变化 %s，典型日间起伏 %s。" % (view["net_value"], view["mean_swing"])),
        "terrain-valley": ("运动阶段穿越", "把 %s 个运动日，画成一段穿越路线" % view["activity_days"], view["activity_fact"] + "。"),
        "editorial-cover": ("本期摄入刊物", "%s，是本期最值得核对的摄入事实" % view["intake_value"], view["intake_fact"] + "。"),
        "editorial-headline": ("今日头条", "%s，没有单独改写整段时间" % view["daily_value"], "把最值得记住的一件事放大，其他数字退到证据席。"),
        "capsule-seal": ("摄入阶段封存", "封存 %s 个饮食记录日" % view["intake_days"], view["intake_fact"] + "；未记录日不会被补成 0。"),
        "capsule-letter": ("写给下一次睡眠回看", "亲爱的未来，这一段睡眠记录是 %s" % view["sleep_value"], view["sleep_fact"] + "；今天不替未来做承诺。"),
        "film-roll": ("最近六格", "每一格都在动，整卷胶片净变化 %s" % view["net_value"], "最大相邻起伏 %s，不用最刺眼的一格代表全部。" % view["max_swing"]),
        "film-grid": ("饮食九格联系印样", "选九个真实饮食记录日，不补造空白", view["intake_fact"] + "；空格不是零摄入。"),
        "rhythm-calendar": ("记录节拍", "%s 的日子有记录" % view["coverage_percent"], "最长空白 %s。这里看的是节律，不是打卡排名。" % view["longest_gap"]),
        "rhythm-moon": ("睡眠观测月相", "%s 个睡眠记录日，生成这一轮月相" % view["sleep_days"], view["sleep_fact"] + "；月相不暗示生理因果。"),
        "ticket-journey": ("运动行程", "一张从 %s 个运动日出发的车票" % view["activity_days"], view["activity_fact"] + ("；目的地不是某个%s数字。" % view["subject"])),
        "passport-stamps": ("阶段入境章", "获得“%s”观察印章" % view["persona"], "印章只收藏观察行为，不奖励某个%s方向。" % view["subject"]),
        "vinyl-record": ("运动唱片", "A 面 %s 个运动日，B 面总时长 %s" % (view["activity_days"], view["activity_value"]), view["activity_fact"] + "。"),
        "weekly-single": ("本周综合单曲", "《%s》" % view["synthesis_headline"], "%s、摄入、运动和睡眠共同写进 liner notes。" % view["subject"]),
        "body-letter": ("身体来信", view["headline"], "把数据写成一封不命令、不责备、不假装知道原因的信。"),
        "no-verdict": ("今天的序章", "先不下结论，也是一种认真", "目前有 %s；卡片会说清楚还缺什么。" % view["coverage"]),
        "observer-persona": ("观察者人格", "你是“%s”" % view["persona"], view["persona_basis"] + "。这是记录风格，不是健康评分。"),
        "observation-file": ("私人观察档案", "%s 天的记录，归档为 %s" % (view["span_days"], view["persona"]), "档案只保留观察习惯、证据强度和匿名编号。"),
        "constellation": ("身体星图", "%s 个记录点，连成这一张私人星群" % view["recorded_days"], "少说一点，让点数、密度和方向自己成为记忆。"),
        "data-fingerprint": ("摄入数据指纹", "%s 个饮食记录日 · %s · 唯一生成" % (view["intake_days"], view["intake_value"]), "纹理由已记录摄入覆盖生成，未记录日不补零。"),
    }
    if not view.get("has_companion_axis"):
        frames.update(_own_subject_frames(view))
    kicker, headline, subhead = frames.get(style_id, ("本次观察", view["headline"], view["core_status"]))
    return {
        "story_kicker": _safe(kicker),
        "story_headline": _safe(headline),
        "story_subhead": _safe(subhead),
        "content_role": STYLE_CONTENT_ROLES.get(style_id, "general-observation"),
    }


def _shape_of(analysis: Mapping[str, object]) -> str:
    """Which of the nine shared shapes this analysis narrates as.

    A Signal Frame declares `shape` outright, so every domain past weight arrives
    here already answered.  A legacy weight analysis carries `state` instead, and is
    translated; anything unrecognised narrates as `insufficient`, which is the only
    shape that promises nothing about direction or trend.
    """
    shape = str(analysis.get("shape") or "")
    if shape in CORE_SHAPE_COPY:
        return shape
    state = str(analysis.get("state") or "")
    known = _LEGACY_STATE_SHAPE.get(state)
    if known:
        return known[0]
    return "insufficient"


def _today_direction(analysis: Mapping[str, object]) -> Optional[str]:
    """Sign of the most recent recorded step, as a neutral direction key or None.

    Read from the signed delta rather than from a state name, so a frame-shaped
    analysis from any domain answers it the same way a weight analysis does.  The
    legacy state name is consulted only when no delta is present at all: `up` and
    `down` here name a numeric direction, never success, failure, or 达标.
    """
    for key in ("daily_delta", "latest_delta"):
        delta = analysis.get(key)
        if isinstance(delta, (int, float)) and not isinstance(delta, bool) and delta:
            return "up" if delta > 0 else "down"
    known = _LEGACY_STATE_SHAPE.get(str(analysis.get("state") or ""))
    return known[1] if known else None


def _headline(family: str, shape: str, direction: Optional[str], variant: str) -> str:
    base, _ = CORE_SHAPE_COPY.get(shape, CORE_SHAPE_COPY["insufficient"])
    value = FAMILY_SHAPE_HEADLINES.get(family, {}).get(shape)
    if isinstance(value, Mapping):
        # A family that authors per-direction prose has nothing to say when the
        # records carry no signed step, so it falls back rather than picking a side.
        value = value.get(direction) if direction else None
    value = value or base
    if variant == "B" and family == "editorial":
        return "今日观察：" + base
    if variant == "B" and family == "letter" and shape == "insufficient":
        return "今天先不下结论，也是一种认真"
    return value


def _series_points(analysis: Mapping[str, object], width: float = 820, height: float = 250) -> List[Tuple[float, float]]:
    values = []
    for item in series_source(analysis):
        value = _point_value(item)
        if value is not None:
            values.append(value)
    if not values:
        return []
    low, high = min(values), max(values)
    spread = max(high - low, 0.4)
    return [
        (
            28 + (width - 56) * index / max(len(values) - 1, 1),
            24 + (height - 48) * (high - value + spread * 0.08) / (spread * 1.16),
        )
        for index, value in enumerate(values)
    ]


def _path(points: Sequence[Tuple[float, float]]) -> str:
    if not points:
        return ""
    return "M" + " L".join("%.1f %.1f" % point for point in points)


def _sparkline(analysis: Mapping[str, object], class_name: str = "signal") -> str:
    points = _series_points(analysis)
    if not points:
        return '<div class="empty-signal">再记录一次，轨迹会从这里出现</div>'
    path = _path(points)
    dots = "".join(
        '<circle cx="%.1f" cy="%.1f" r="%d" />' % (x, y, 10 if index == len(points) - 1 else 5)
        for index, (x, y) in enumerate(points)
    )
    return (
        '<svg class="%s" viewBox="0 0 820 250" role="img" aria-label="每日中位数的相对变化轨迹">'
        '<line x1="20" y1="224" x2="800" y2="224" class="baseline"/>'
        '<path d="%s" class="signal-path"/><g class="signal-dots">%s</g></svg>'
    ) % (_safe(class_name), path, dots)


# Which own-subject profile stands in for each companion profile.  Coverage-shaped
# profiles (how many days were recorded) map to coverage; the change-shaped ones
# (how much moved) map to change, so the tile keeps answering the question the layout
# around it was drawn to ask.
_OWN_SUBJECT_METRIC_PROFILES = {
    "intake": "own-coverage",
    "sleep": "own-coverage",
    "multi-signal": "own-coverage",
    "activity": "own-change",
}


def _metrics(view: Mapping[str, str], variant: str = "default") -> str:
    profiles = {
        "default": (
            (view["daily_label"], view["daily_value"], view["daily_note"]),
            ("稳健长期趋势", view["trend_value"], view["trend_note"]),
            ("记录覆盖", view["coverage"], "可信度 " + view["confidence"]),
        ),
        "forecast": (
            ("今日天气", view["daily_value"], view["daily_label"]),
            ("长期气流", view["trend_value"], view["trend_note"]),
            ("观测能见度", view["coverage_percent"], "证据 " + view["confidence"]),
        ),
        "forecast-week": (
            ("本期有记录", view["recorded_days"] + " 天", view["coverage_percent"] + " 覆盖"),
            ("最长空白", view["longest_gap"], "只描述记录节律"),
            ("同日复测", view["repeat_count"] + " 次", "已折叠为日中位数"),
        ),
        "course": (
            ("今日浪高", view["daily_value"], view["daily_label"]),
            ("长期航向", view["trend_value"], view["trend_note"]),
            ("航向可信度", view["confidence"], view["recorded_days"] + " 个记录日"),
        ),
        "logbook": (
            ("航程", view["span_days"] + " 天", "从第一笔到现在"),
            ("入志", view["recorded_days"] + " 页", view["measurement_count"] + " 次测量"),
            ("全程净变化", view["net_value"], "只是相对变化"),
        ),
        "terrain": (
            ("地形振幅", view["range_value"], "阶段最高与最低差"),
            ("日间起伏", view["mean_swing"], "相邻记录的典型变化"),
            ("路径净变化", view["net_value"], view["span_days"] + " 天路程"),
        ),
        "route": (
            ("起点到终点", view["net_value"], "不评价方向"),
            ("最大单步起伏", view["max_swing"], "相邻两个记录日"),
            ("穿越时间", view["span_days"] + " 天", view["recorded_days"] + " 个落点"),
        ),
        "editorial": (
            ("头条证据", view["trend_value"], view["trend_note"]),
            ("校对样本", view["recorded_days"] + " 天", view["measurement_count"] + " 次测量"),
            ("编辑判断", view["confidence"], "数据不足就不发长期结论"),
        ),
        "headline": (
            ("今日数字", view["daily_value"], view["daily_label"]),
            ("是否改写长期", "没有" if view["state_conflict"] else "分开看", view["core_status"]),
            ("证据底注", view["confidence"], view["coverage_percent"] + " 覆盖"),
        ),
        "capsule": (
            ("封存记录日", view["recorded_days"], view["span_days"] + " 天观察跨度"),
            ("本期净变化", view["net_value"], "下次回看的对照点"),
            ("封存编号", view["edition"], "可复现的阶段标记"),
        ),
        "future": (
            ("今日留言", view["daily_value"], "不是未来承诺"),
            ("待回信跨度", view["span_days"] + " 天", "等下一段数据"),
            ("当前证据", view["confidence"], view["coverage_percent"] + " 覆盖"),
        ),
        "film": (
            ("入镜记录日", view["recorded_days"], "整卷共 " + view["measurement_count"] + " 次测量"),
            ("最大格间起伏", view["max_swing"], "不用单格代表整卷"),
            ("整卷净变化", view["net_value"], view["span_days"] + " 天"),
        ),
        "grid": (
            ("胶片切片", "9 格", "不足时诚实留白"),
            ("双重曝光", view["repeat_count"] + " 次", "同日复测"),
            ("记录库", view["measurement_count"] + " 次", view["recorded_days"] + " 个记录日"),
        ),
        "rhythm": (
            ("有记录", view["recorded_days"] + " 天", view["coverage_percent"] + " 覆盖"),
            ("最长空白", view["longest_gap"], "空白不是断签失败"),
            ("复测节点", view["repeat_count"] + " 次", "已稳健聚合"),
        ),
        "moon": (
            ("观测相位", view["coverage_percent"], "只表示记录覆盖"),
            ("完整记录日", view["recorded_days"], "不暗示生理周期"),
            ("最长暗相", view["longest_gap"], "中断后仍可继续"),
        ),
        "journey": (
            ("已经过", view["span_days"] + " 天", "目的地不是某个" + view["subject"]),
            ("已记录", view["recorded_days"] + " 站", view["measurement_count"] + " 次测量"),
            ("路线净变化", view["net_value"], "只描述，不评分"),
        ),
        "passport": (
            ("观察印章", view["persona"], view["persona_basis"]),
            ("入境记录", view["recorded_days"] + " 天", view["span_days"] + " 天跨度"),
            ("证据等级", view["confidence"], "与" + view["subject"] + "方向无关"),
        ),
        "identity": (
            ("观察跨度", view["span_days"] + " 天", view["recorded_days"] + " 个记录日"),
            ("记录风格", view["persona"], view["persona_basis"]),
            ("档案编号", view["edition"], "不包含身份信息"),
        ),
        "dossier": (
            ("档案密度", view["coverage_percent"], view["measurement_count"] + " 次测量"),
            ("复测记录", view["repeat_count"] + " 次", "同日观察习惯"),
            ("可信等级", view["confidence"], "只用于判断能说什么"),
        ),
        "star": (
            ("星点", view["recorded_days"], "每个点对应一个记录日"),
            ("星群振幅", view["range_value"], "来自相对变化"),
            ("星图编号", view["edition"], "同阶段可复现"),
        ),
        "fingerprint": (
            ("纹理覆盖", view["coverage_percent"], view["recorded_days"] + " 个记录点"),
            ("纹理振幅", view["range_value"], "不含绝对" + view["subject"]),
            ("指纹编号", view["edition"], "数据驱动、可复现"),
        ),
        "intake": (
            ("饮食记录", view["intake_days"] + " 天", "未记录日不按零摄入"),
            ("有记录日平均", view["intake_value"], "仅统计已有营养数据"),
            ("前后半段变化", view["intake_change"], "同期线索，不代表因果"),
        ),
        "activity": (
            ("运动记录", view["activity_days"] + " 天", "没有记录不等于没有运动"),
            ("已记录总时长", view["activity_value"], "不是全天总消耗"),
            ("前后半段变化", view["activity_change"], "同期线索，不代表因果"),
        ),
        "sleep": (
            ("睡眠记录", view["sleep_days"] + " 天", "只描述有记录的夜晚"),
            ("有记录日平均", view["sleep_value"], "记录时长，不作医学判断"),
            ("前后半段变化", view["sleep_change"], "同期线索，不代表因果"),
        ),
        "multi-signal": (
            ("有记录日摄入", view["intake_value"], view["intake_days"] + " 个饮食日"),
            ("已记录运动", view["activity_value"], view["activity_days"] + " 个运动日"),
            ("睡眠记录时长", view["sleep_value"], view["sleep_days"] + " 个睡眠日"),
        ),
        # The four profiles above read a companion axis.  A domain without one gets
        # these instead: same three-tile shape, all of it about the card's own subject.
        # The swap happens before the class and `data-metric-profile` are written, so a
        # records card is marked `own-coverage` rather than `sleep` — the attribute names
        # what was actually rendered, which is the point of having it.  Nothing keys on
        # these names today; if a stylesheet ever does, it needs both spellings.
        "own-coverage": (
            ("有记录", view["recorded_days"] + " 天", view["coverage_percent"] + " 覆盖"),
            ("记录次数", view["measurement_count"] + " 次", "未记录日不补零"),
            ("最长空白", view["longest_gap"], "空白不是失败"),
        ),
        "own-change": (
            ("本期净变化", view["net_value"], view["span_days"] + " 天跨度"),
            ("最大单步起伏", view["max_swing"], "相邻两个记录日"),
            ("前后半段", view["trend_value"], view["trend_note"]),
        ),
    }
    if not view.get("has_companion_axis"):
        variant = _OWN_SUBJECT_METRIC_PROFILES.get(variant, variant)
    items = profiles.get(variant, profiles["default"])
    cells = "".join(
        '<div class="metric"><small>%s</small><strong>%s</strong><span>%s</span></div>' % item
        for item in items
    )
    return '<section class="metrics metrics-%s" data-metric-profile="%s" aria-label="分析证据">%s</section>' % (
        _safe(variant), _safe(variant), cells
    )


def _moment(view: Mapping[str, str]) -> str:
    if not view.get("show_moment") or not view.get("moment_label"):
        return ""
    return """<aside class="moment"><small>本次发现</small><strong>%s</strong><p>%s</p></aside>""" % (
        view["moment_label"], view["moment_line"]
    )


def _context(view: Mapping[str, str]) -> str:
    if not view.get("show_context") or not view.get("context_1"):
        return ""
    second = "<li>%s</li>" % view["context_2"] if view.get("context_2") else ""
    return """<section class="context"><small>记录线索 · 不代表因果</small><ul><li>%s</li>%s</ul></section>""" % (
        view["context_1"], second
    )


# Six family visuals name a companion axis inside their own markup rather than through
# a metric profile — a captain's log with 运动记录日 in the `<dt>`, a tracklist whose first
# track is 运动记录.  Those two helpers are the same substitution `_metrics` does for its
# profiles, moved to where the label lives: with a companion axis, read the companion;
# without one, read the card's own subject and relabel so the block still answers the
# question its layout was drawn to ask.  Labels are literals and every view value is
# already escaped by `_view_model`, so neither helper re-escapes.
_AXIS_ROWS = {
    "activity": (
        (("运动记录日", "activity_days", " 天"), ("已记录总时长", "activity_value", ""),
         ("后半段变化", "activity_change", "")),
        (("有记录日", "recorded_days", " 天"), ("本期净变化", "net_value", ""),
         ("后半段变化", "trend_value", "")),
    ),
    "tracklist": (
        (("运动记录", "activity_days", " 天"), ("已记录时长", "activity_value", ""),
         ("后半段变化", "activity_change", "")),
        (("有记录日", "recorded_days", " 天"), ("本期净变化", "net_value", ""),
         ("后半段变化", "trend_value", "")),
    ),
    "liner": (
        (("摄入", "intake_value", ""), ("运动", "activity_value", ""), ("睡眠", "sleep_value", "")),
        (("有记录日", "recorded_days", " 天"), ("本期净变化", "net_value", ""),
         ("覆盖", "coverage_percent", "")),
    ),
}

# Single-value slots: the same idea where the markup holds one number and its caption.
_AXIS_VALUES = {
    "capsule-seal": (("intake_days", "个饮食记录日"), ("recorded_days", "个有记录日")),
    "ticket-journey": (("activity_value", ""), ("net_value", "")),
    "rhythm-moon": (("sleep_value", ""), ("coverage_percent", "")),
}


def _axis_rows(view: Mapping[str, object], slot: str, markup: str) -> str:
    companion, own = _AXIS_ROWS[slot]
    rows = companion if view.get("has_companion_axis") else own
    return "".join(markup % (label, str(view[key]) + suffix) for label, key, suffix in rows)


def _axis_value(view: Mapping[str, object], slot: str) -> Tuple[str, str]:
    companion, own = _AXIS_VALUES[slot]
    key, caption = companion if view.get("has_companion_axis") else own
    return str(view[key]), caption


def _weather_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    coverage = float(analysis.get("coverage_ratio") or 0.0)
    rings = max(3, min(8, int(round(coverage * 8))))
    ring_markup = "".join('<i style="--i:%d"></i>' % index for index in range(rings))
    if variant == "B":
        # The seven cells are a coverage strip, so they have to count the days this card
        # can actually see: the companion axis when there is one, its own recorded days
        # otherwise.  Reading `sleep_days` unconditionally would draw seven 留白 cells on
        # a domain with fourteen recorded days.
        source = "sleep_days" if view.get("has_companion_axis") else "recorded_days"
        recorded = int(view.get(source) or 0)
        cells = "".join(
            '<i class="%s"><b>%s</b><span></span><small>%s</small></i>' % (
                "on" if index < min(recorded, 7) else "",
                ("一", "二", "三", "四", "五", "六", "日")[index],
                "有记录" if index < min(recorded, 7) else "留白",
            )
            for index in range(7)
        )
        return """<div class="weather-week"><div class="weather-week-title"><small>7-DAY OBSERVATION</small><strong>%s</strong></div>
          <div class="weather-week-cells">%s</div><div class="weather-week-line">%s</div></div>
          %s%s""" % (view["story_subhead"], cells, _sparkline(analysis, "weather-signal"), _metrics(view, "sleep"), _moment(view))
    return """<div class="weather-orb" aria-label="抽象身体天气观测"><div class="weather-rings">%s</div>
      <div class="weather-reading"><small>OBSERVATION</small><strong>%s</strong><span>%s</span></div></div>
      <div class="forecast-strip">%s</div>%s%s""" % (
        ring_markup, view["daily_value"], view["daily_label"], _sparkline(analysis, "weather-signal"),
        _metrics(view, "forecast"), _moment(view)
    )


def _compass_angle(analysis: Mapping[str, object]) -> float:
    """Map a trend to the compass without comparing incompatible physical units.

    Signal Frame callers provide a unitless direction-consistency score. Legacy
    weight callers do not, so their historical kg-based angle remains the exact
    fallback; this keeps the locked weight documents byte-identical while every new
    domain shares one scale. A missing/zero printed trend always points north even
    if a stale visual field is present.
    """
    try:
        delta = float(analysis.get("trend_delta"))
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(delta) or delta == 0.0:
        return 0.0
    strength = analysis.get("trend_visual_strength")
    try:
        strength = float(strength)
    except (TypeError, ValueError):
        strength = None
    if strength is not None and math.isfinite(strength):
        return max(
            -COMPASS_STRENGTH_DEGREES,
            min(COMPASS_STRENGTH_DEGREES, strength * COMPASS_STRENGTH_DEGREES),
        )
    return max(-COMPASS_MAX_DEGREES, min(COMPASS_MAX_DEGREES, delta * 18.0))


def _direction_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    angle = _compass_angle(analysis)
    if variant == "B":
        return """<div class="logbook"><div class="logbook-title"><small>CAPTAIN'S LOG / %s</small><strong>%s</strong></div>
          <dl>%s</dl>
          <div class="logbook-chart">%s</div></div>%s%s""" % (
            view["edition"], view["story_headline"],
            _axis_rows(view, "activity", "<div><dt>%s</dt><dd>%s</dd></div>"),
            _sparkline(analysis, "course-signal"), _metrics(view, "activity"), _moment(view)
        )
    return """<div class="course-map"><div class="course-compass" style="--angle:%.1fdeg"><i></i><b>N</b></div>
      <div class="course-line">%s</div><div class="course-note"><small>当前航向</small><strong>%s</strong></div></div>
      %s%s""" % (angle, _sparkline(analysis, "course-signal"), view["trend_value"], _metrics(view, "course"), _moment(view))


def _terrain_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    points = _series_points(analysis, 860, 360)
    base = _path(points)
    contours = "".join(
        '<path d="%s" transform="translate(0 %d)" opacity="%.2f"/>' % (base, offset, opacity)
        for offset, opacity in ((-84, .16), (-54, .25), (-26, .38), (0, .85), (30, .38), (62, .22), (96, .14))
    ) if base else ""
    if variant == "B":
        markers = ""
        if points:
            indexes = sorted({0, len(points) // 2, len(points) - 1})
            markers = "".join(
                '<g transform="translate(%.1f %.1f)"><circle r="14"/><text y="42">%02d</text></g>' % (points[index][0], points[index][1] + 45, number + 1)
                for number, index in enumerate(indexes)
            )
        return """<div class="terrain-map terrain-route"><svg viewBox="0 0 860 480" role="img" aria-label="阶段变化生成的山谷路线"><path class="route" d="%s"/><g class="route-points">%s</g></svg>
          <div class="terrain-caption"><small>VALLEY ROUTE</small><strong>%s</strong><span>%s</span></div></div>%s%s""" % (
            base, markers, view["edition"], view["story_subhead"], _metrics(view, "activity"), _moment(view)
        )
    return """<div class="terrain-map"><svg viewBox="0 0 860 480" role="img" aria-label="由相对变化生成的等高线地形"><g>%s</g></svg>
      <div class="terrain-caption"><small>PERSONAL CONTOUR</small><strong>%s</strong><span>%s</span></div></div>
      %s%s""" % (contours, view["edition"], view["core_status"], _metrics(view, "terrain"), _moment(view))


def _editorial_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    if variant == "B":
        return """<div class="headline-sheet"><div class="headline-number"><small>THE NUMBER</small><strong>%s</strong><span>%s</span></div>
          <div class="headline-copy"><small>TODAY'S HEADLINE</small><p>%s</p></div></div>
          <div class="headline-signal">%s</div>%s<div class="editorial-rule"></div>%s""" % (
            view["daily_value"], view["daily_label"], view["core_status"], _sparkline(analysis, "editorial-signal"),
            _metrics(view, "headline"), _moment(view)
        )
    return """<div class="editorial-grid"><div class="issue"><small>ISSUE</small><strong>%s</strong></div>
      <div class="editorial-chart">%s</div><div class="editorial-fact"><small>THE FACT</small><p>%s</p></div></div>
      %s<div class="editorial-rule"></div>%s""" % (
        view["edition"], _sparkline(analysis, "editorial-signal"), view["core_status"],
        _metrics(view, "intake"), _moment(view)
    )


def _capsule_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    if variant == "B":
        return """<div class="future-letter"><div class="future-stamp">%s</div><small>TO MY FUTURE SELF</small>
          <p>%s</p><div class="future-note">%s<br>今天的%s是 %s，长期趋势是 %s。</div></div>
          %s%s""" % (
            view["edition"], view["story_headline"], view["story_subhead"], view["reading"],
            view["daily_value"], view["trend_value"], _metrics(view, "sleep"), _moment(view)
        )
    return """<div class="capsule-stage"><div class="capsule-seal"><small>SEALED</small><strong>%s</strong><span>%s</span></div>
      <div class="capsule-message"><p>%s</p><small>等下一段时间，再回来读这一页。</small></div></div>
      %s%s""" % (_axis_value(view, "capsule-seal") + (view["story_headline"], _metrics(view, "intake"), _moment(view)))


def _film_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    points = _series_points(analysis, 720, 160)
    if variant == "B":
        frames = []
        for index in range(9):
            active = index < min(len(points), 9)
            y = points[min(index, len(points) - 1)][1] if active else 130
            frames.append('<i class="%s"><b>%02d</b><span style="height:%.1fpx"></span></i>' % ("active" if active else "", index + 1, max(20, 150 - y * .55)))
        return """<div class="film-grid" aria-label="九个真实记录切片">%s</div>
          <div class="film-grid-caption"><small>NINE REAL MOMENTS / %s</small><p>%s</p></div>%s%s""" % (
            "".join(frames), view["edition"], view["story_headline"], _metrics(view, "intake"), _moment(view)
        )
    frames = []
    for index in range(6):
        active = index < min(len(points), 6)
        level = int(points[min(index, len(points) - 1)][1]) if active else 120
        frames.append('<i class="%s" style="--level:%dpx"><b>%02d</b></i>' % ("active" if active else "", level, index + 1))
    return """<div class="film-strip" aria-label="最近记录的胶片切片">%s</div>
      <div class="film-caption"><small>ROLL %s</small><p>%s</p></div>%s%s""" % (
        "".join(frames), view["edition"], view["story_headline"], _sparkline(analysis, "film-signal"), _metrics(view, "film")
    )


def _rhythm_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    days = int(analysis.get("window_days") or 14)
    records = min(int(analysis.get("recorded_days") or 0), days)
    if variant == "B":
        phases = "".join(
            '<i class="%s" style="--phase:%d%%"><span>%02d</span></i>' % (
                "on" if index < records else "", int(15 + 70 * (index + 1) / max(days, 1)), index + 1
            ) for index in range(days)
        )
        return """<div class="moon-board"><div class="moon-title"><small>OBSERVATION PHASES</small><strong>%s</strong><p>%s</p></div>
          <div class="moon-grid" aria-label="由记录覆盖生成的抽象月相">%s</div></div>%s%s%s""" % (
            _axis_value(view, "rhythm-moon")[0], view["story_subhead"], phases,
            _metrics(view, "sleep"), _moment(view), _context(view)
        )
    cells = "".join('<i class="%s"><span>%02d</span></i>' % ("on" if index < records else "", index + 1) for index in range(days))
    return """<div class="rhythm-board"><div class="rhythm-count"><strong>%s</strong><small>个记录日</small></div>
      <div class="rhythm-grid" aria-label="记录覆盖节律">%s</div></div>
      %s%s%s""" % (view["recorded_days"], cells, _metrics(view, "rhythm"), _moment(view), _context(view))


def _journey_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    if variant == "B":
        return """<div class="passport"><div class="passport-cover"><small>MEDIWISE</small><strong>身体护照</strong><span>%s</span></div>
          <div class="passport-page"><div class="stamp stamp-one">已观察<br><b>%s 日</b></div><div class="stamp stamp-two">跨度<br><b>%s 日</b></div>
          <p>%s</p><small>%s</small></div></div>%s%s""" % (
            view["edition"], view["recorded_days"], view["span_days"], view["story_headline"], view["story_subhead"], _metrics(view, "multi-signal"), _moment(view)
        )
    return """<div class="ticket"><div class="ticket-main"><small>MEDIWISE / PERSONAL LINE</small>
      <div class="stations"><b>记录</b><i></i><b>理解</b><i></i><b>继续</b></div><p>%s</p></div>
      <div class="ticket-stub"><small>EDITION</small><strong>%s</strong><span>%s</span></div></div>
      %s%s""" % (view["story_headline"], view["edition"], _axis_value(view, "ticket-journey")[0],
                 _metrics(view, "activity"), _moment(view))


def _music_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    if variant == "B":
        return """<div class="single-stage"><div class="single-cover"><small>MW / SINGLE</small><div class="single-wave">%s</div><strong>%s</strong><span>%s</span></div>
          <div class="single-notes"><small>THIS WEEK'S LINER NOTES</small><p>%s</p><dl>%s</dl></div></div>%s""" % (
            _sparkline(analysis, "music-signal"), view["story_headline"], view["edition"], view["story_subhead"],
            _axis_rows(view, "liner", "<div><dt>%s</dt><dd>%s</dd></div>"), _moment(view)
        )
    return """<div class="record-stage"><div class="vinyl"><div class="vinyl-label"><small>MW</small><strong>%s</strong></div></div>
      <div class="tracklist"><small>NOW PLAYING</small><strong>%s</strong><ol>%s</ol></div></div>
      <div class="music-wave">%s</div>%s""" % (
        view["edition"], view["story_headline"],
        _axis_rows(view, "tracklist", "<li>%s <b>%s</b></li>"),
        _sparkline(analysis, "music-signal"), _moment(view)
    )


def _letter_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    greeting = "你好，%s" % view["member_name"] if view.get("member_name") else "你好，正在记录的你"
    if variant == "B":
        return """<article class="letter-sheet no-verdict-sheet"><div class="ellipsis">…</div><small>%s</small><h2>%s</h2>
          <p>%s</p><p class="letter-evidence">目前有 <b>%s</b>。下一次记录会增加信息，但今天不需要被解释成成功或失败。</p>
          <div class="letter-sign">MediWise<br><span>%s</span></div></article>%s%s""" % (
            view["edition"], view["headline"], view["core_status"], view["coverage"], view["date_label"], _moment(view), _context(view)
        )
    return """<article class="letter-sheet"><small>%s</small><h2>%s：</h2><p>%s</p>
      <p class="letter-evidence">今天的变化是 <b>%s</b>，稳健长期趋势是 <b>%s</b>。%s。这是记录，不是评语。</p>
      <div class="letter-sign">MediWise<br><span>%s</span></div></article>%s%s""" % (
        view["edition"], greeting, view["core_status"], view["daily_value"], view["trend_value"],
        view["daily_note"], view["date_label"], _moment(view), _context(view)
    )


def _identity_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    if variant == "B":
        return """<div class="dossier"><div class="dossier-index"><small>FILE</small><strong>%s</strong><span>PRIVATE OBSERVATION</span></div>
          <div class="dossier-main"><small>OBSERVER PROFILE</small><h2>%s</h2><p>%s</p>
          <dl><div><dt>记录日</dt><dd>%s</dd></div><div><dt>观察跨度</dt><dd>%s 天</dd></div><div><dt>可信度</dt><dd>%s</dd></div></dl></div></div>%s%s""" % (
            view["edition"], view["persona"], view["persona_basis"], view["recorded_days"], view["span_days"], view["confidence"],
            _metrics(view, "multi-signal"), _moment(view)
        )
    return """<div class="identity-card"><small>YOUR OBSERVER TYPE</small><strong>%s</strong><p>%s</p>
      <dl><div><dt>观察跨度</dt><dd>%s 天</dd></div><div><dt>记录日</dt><dd>%s</dd></div><div><dt>档案编号</dt><dd>%s</dd></div></dl></div>
      %s%s""" % (
        view["persona"], view["persona_basis"], view["span_days"], view["recorded_days"], view["edition"],
        _metrics(view, "identity"), _moment(view)
    )


def _generative_visual(analysis: Mapping[str, object], view: Mapping[str, str], variant: str) -> str:
    rng = random.Random(view["texture_seed"])
    if variant == "A":
        nodes = [(rng.randint(80, 780), rng.randint(55, 500), rng.randint(3, 10)) for _ in range(max(7, int(analysis.get("recorded_days") or 0)))]
        lines = "".join(
            '<line x1="%d" y1="%d" x2="%d" y2="%d"/>' % (a[0], a[1], b[0], b[1])
            for a, b in zip(nodes, nodes[1:])
        )
        circles = "".join('<circle cx="%d" cy="%d" r="%d"/>' % node for node in nodes)
        art = '<svg viewBox="0 0 860 560" role="img" aria-label="由记录生成的身体星图"><g class="star-lines">%s</g><g class="stars">%s</g></svg>' % (lines, circles)
    else:
        coverage = float(analysis.get("coverage_ratio") or 0.0)
        rings = []
        for index in range(12):
            radius = 55 + index * 18
            dash = 18 + int(coverage * 24) + rng.randint(0, 14)
            gap = 8 + rng.randint(0, 15)
            rings.append('<circle cx="430" cy="280" r="%d" style="stroke-dasharray:%d %d;transform:rotate(%ddeg);transform-origin:430px 280px"/>' % (radius, dash, gap, rng.randint(0, 180)))
        art = '<svg viewBox="0 0 860 560" role="img" aria-label="由记录生成的数据指纹"><g class="finger-rings">%s</g></svg>' % "".join(rings)
    metric_profile = "multi-signal" if variant == "A" else "intake"
    return """<div class="generative-art">%s<div class="art-label"><small>UNIQUE SIGNAL</small><strong>%s</strong></div></div>
      %s%s""" % (art, view["edition"], _metrics(view, metric_profile), _moment(view))


FAMILY_RENDERERS = {
    "weather": _weather_visual,
    "direction": _direction_visual,
    "terrain": _terrain_visual,
    "editorial": _editorial_visual,
    "capsule": _capsule_visual,
    "film": _film_visual,
    "rhythm": _rhythm_visual,
    "journey": _journey_visual,
    "music": _music_visual,
    "letter": _letter_visual,
    "identity": _identity_visual,
    "generative": _generative_visual,
}


def _view_model(
    analysis: Mapping[str, object],
    selection: Mapping[str, object],
    member_name: str,
    show_exact_weight: bool,
    show_member_name: bool,
    show_exact_date: bool,
    context_lines: Optional[Sequence[str]],
    lexicon: Optional[Mapping[str, str]] = None,
    domain: str = DEFAULT_DOMAIN,
) -> dict:
    words = _resolve_lexicon(lexicon)
    unit_suffix = " " + words["unit"]
    style = selection["selected_style"]
    family = style["family"]
    state = str(analysis.get("state") or "insufficient")
    shape = _shape_of(analysis)
    direction = _today_direction(analysis)
    # `{today}` is resolved into the wording table rather than at each use site, so
    # the one `_fill` pass below reaches it in every field — including the ones
    # `_story_frame` composes out of these values.  It is added here and never read
    # off a frame: the Signal Frame lexicon is schema-closed at eight keys, and a
    # ninth arriving from outside would be a domain smuggling in copy.
    words["today"] = words.get(direction or "", "") or NEUTRAL_TODAY
    core_title, core_status = CORE_SHAPE_COPY.get(shape, CORE_SHAPE_COPY["insufficient"])
    daily_delta = analysis.get("daily_delta")
    trend_delta = analysis.get("trend_delta")
    gap = analysis.get("comparison_gap_days")
    latest_value = analysis.get("latest_weight")
    if latest_value is None:
        latest_value = analysis.get("latest_value")
    daily_note = "较昨日" if gap == 1 else "较上次记录"
    if daily_delta is None:
        daily_note = "等待下一次记录"
    # Three states, not two.  The window can permit a long-run claim and the estimator
    # can still decline to make one -- every point landing on the same calendar day, or
    # a single surviving point -- and the card must not print 稳健估计 beside the 「—」
    # that leaves.  「暂无稳健拟合」 says the records were enough but the fit was not,
    # which is a different sentence from 记录不足.
    if not analysis.get("trend_claim_allowed"):
        trend_note = "记录不足，暂不判断"
    elif trend_delta is None:
        trend_note = "暂无稳健拟合"
    else:
        trend_note = "稳健估计"
    # "Exact" here means the absolute reading, which is the privacy-sensitive part
    # in every domain: 68.4 kg and 07:12 of sleep are both re-identifying in a way
    # that a signed delta is not.  So the flag name stays, the wording generalises.
    exact_value = "绝对%s已隐藏" % words["subject"]
    exact_weight_footer = ""
    if show_exact_weight and latest_value is not None:
        exact_value = "当前 %.1f%s" % (float(latest_value), unit_suffix)
        exact_weight_footer = " · " + exact_value
    date_label = "本次观察"
    if show_exact_date and analysis.get("latest_date"):
        date_label = str(analysis["latest_date"])
    moments = selection.get("story_moments") or []
    moment = moments[0] if moments else {}
    persona = selection.get("observer_persona") or {}
    signature = selection.get("visual_signature") or {}
    contexts = [_safe(item) for item in (context_lines or []) if str(item).strip()][:2]
    details = _analysis_details(analysis, lexicon, domain)
    view = {
        "style_id": str(style.get("id") or ""),
        "state": state,
        "shape": shape,
        "subject": _safe(words["subject"]),
        "reading": _safe(words["reading"]),
        "unit": _safe(words["unit"]),
        "trend_allowed": bool(analysis.get("trend_claim_allowed")),
        # Whether an estimate actually exists, separate from whether the window earns
        # one.  `_story_frame` composes prose out of these values and needs the two
        # apart: 记录不足 and 暂无稳健拟合 are different admissions.
        "trend_fitted": trend_delta is not None,
        "state_conflict": shape == "today-vs-trend-conflict",
        "core_title": _safe(core_title),
        "core_status": _safe(core_status),
        "headline": _safe(_headline(family, shape, direction, style.get("variant", "A"))),
        "daily_label": _safe(words["reading"] + daily_note),
        "daily_value": _safe(_signed(daily_delta) + (unit_suffix if daily_delta is not None else "")),
        "daily_note": _safe(exact_value),
        "trend_value": _safe(_signed(trend_delta) + (unit_suffix if trend_delta is not None else "")),
        "trend_note": _safe(trend_note),
        # `recorded_days` and `span_days` come from `details`, which read them through the
        # domain's own `coverage_for`; the merge at the bottom of this function would
        # overwrite them anyway, so they are spelled here instead of shadowed silently.
        # `window_days` has no adapter accessor -- it is the requested window, not a
        # measured property of the records -- so it stays a direct read.
        "coverage": _safe("%s / %d 天" % (details["recorded_days"], int(analysis.get("window_days") or 0))),
        "confidence": _safe(str(analysis.get("confidence_label") or "不足")),
        "recorded_unit": "个记录日",
        "edition": _safe(signature.get("edition") or "MW-0000"),
        "texture_seed": str(signature.get("texture_seed") or "mediwise"),
        "moment_label": _safe(moment.get("label")),
        "moment_line": _safe(moment.get("share_line")),
        "persona": _safe(persona.get("label") or "稳稳记录者"),
        "persona_basis": _safe(persona.get("basis") or "正在积累个人记录"),
        "member_name": _safe(member_name) if show_member_name and member_name else "",
        "member_footer": _safe(" · " + member_name) if show_member_name and member_name else "",
        "exact_weight_footer": _safe(exact_weight_footer),
        "date_label": _safe(date_label),
        "context_1": contexts[0] if contexts else "",
        "context_2": contexts[1] if len(contexts) > 1 else "",
    }
    view["show_moment"] = view["style_id"] in MOMENT_VISIBLE_STYLES
    view["show_context"] = view["style_id"] in CONTEXT_VISIBLE_STYLES
    view.update({key: _safe(value) for key, value in details.items()})
    management_details = _management_details(analysis, domain)
    for key, value in management_details.items():
        view[key] = value if isinstance(value, bool) else _safe(value)
    # Resolve authored `{slot}` tokens before `_story_frame`, which composes its
    # kickers and subheads out of these same values — a token left unfilled here
    # would be copied into the frame and reach the card.
    for key, value in view.items():
        if isinstance(value, str):
            view[key] = _fill(value, words)
    view.update(_story_frame(view["style_id"], state, view))
    return view


def render_weight_story_html(
    analysis: Mapping[str, object],
    selection: Mapping[str, object],
    *,
    member_name: str = "",
    show_exact_weight: bool = False,
    show_member_name: bool = False,
    show_exact_date: bool = False,
    context_lines: Optional[Sequence[str]] = None,
    domain: str = DEFAULT_DOMAIN,
    lexicon: Optional[Mapping[str, str]] = None,
) -> str:
    """Render any registered style as a self-contained 1080×1440 document.

    `domain` selects the wording; `lexicon` overrides it field by field, which is
    how a caller holding a Signal Frame narrates from the frame's own table rather
    than re-deriving it from the registry.
    """
    style = selection.get("selected_style") or {}
    style_id = str(style.get("id") or "")
    if style_id not in STYLES_BY_ID:
        raise ValueError("unknown story-card style: %s" % style_id)
    catalog_style = STYLES_BY_ID[style_id]
    family = catalog_style.family
    renderer = FAMILY_RENDERERS.get(family)
    if renderer is None:
        raise ValueError("no renderer for style family: %s" % family)
    variant = catalog_style.variant
    words = _resolve_lexicon(lexicon if lexicon else lexicon_for(domain))
    product_name = PRODUCT_NAME_TEMPLATE % words["subject"]
    disclaimer = DISCLAIMER_TEMPLATE % prescription_noun_for(domain)
    case_label = "CASE / %s + LIFE" % latin_tag_for(domain)
    view = _view_model(
        analysis, selection, member_name, show_exact_weight, show_member_name,
        show_exact_date, context_lines, words, domain,
    )
    # The twelve family renderers read `recorded_days` and `coverage_ratio` straight off
    # the analysis to size generative geometry -- filled calendar cells, node counts, ring
    # opacity.  Left raw those numbers came from a different source than the coverage line
    # printed beside them, so a folding domain could draw fourteen filled cells under the
    # words 「5 / 14 天」.  Normalising here rather than threading `domain` through twelve
    # signatures keeps one coverage source per render; for `weight` both keys pass through
    # the adapter unchanged, which is why the goldens do not move.
    coverage_block = get_adapter(domain).coverage_for(analysis)
    visual_analysis = dict(analysis)
    visual_analysis["recorded_days"] = int(coverage_block.get("recorded_days") or 0)
    visual_analysis["coverage_ratio"] = float(coverage_block.get("ratio") or 0.0)
    content = renderer(visual_analysis, view, variant) + _synthesis_block(style_id, view)
    if view.get("show_context") and view.get("context_1") and 'class="context"' not in content:
        content += _context(view)
    share_safe = not (show_exact_weight or show_member_name or show_exact_date)
    privacy = "默认脱敏 · 可分享" if share_safe else "含已选择展示的个人信息"
    exploration = " · 惊喜探索" if selection.get("exploration") else ""
    palette = int((selection.get("visual_signature") or {}).get("palette_variant") or 0)

    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>%s · %s</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}html,body{width:100%%;height:100%%;overflow:hidden}body{background:#d9e0df;color:#0A2F55;font-family:"Avenir Next","Segoe UI Variable","PingFang SC","Microsoft YaHei",sans-serif}.viewport{position:absolute;inset:0;margin:auto;transform-origin:0 0}.artboard{position:relative;width:1080px;height:1440px;overflow:hidden;background:var(--paper);color:var(--ink);padding:70px 74px 58px;display:flex;flex-direction:column;--paper:#F5F0E6;--ink:#0A2F55;--muted:#647783;--accent:#D66548;--accent2:#167A9A;--soft:#E7DED0;--line:rgba(10,47,85,.16)}
.artboard[data-palette="1"]{--paper:#EDF3EC;--ink:#183C37;--muted:#657A70;--accent:#C86D50;--accent2:#4B8074;--soft:#DCE8DE}.artboard[data-palette="2"]{--paper:#F6EBDD;--ink:#293C59;--muted:#786F68;--accent:#C05A46;--accent2:#4D7394;--soft:#EADAC5}.artboard[data-palette="3"]{--paper:#EAF0F2;--ink:#123A4B;--muted:#617984;--accent:#C9664D;--accent2:#2A7480;--soft:#D8E3E5}.artboard[data-palette="4"]{--paper:#F2ECE6;--ink:#3D3541;--muted:#776D75;--accent:#B45E52;--accent2:#68788C;--soft:#E6DCD5}.artboard[data-palette="5"]{--paper:#F5F1E8;--ink:#273E37;--muted:#6B776E;--accent:#CB6C45;--accent2:#537F6E;--soft:#E6E3D4}
.brand{display:flex;align-items:center;justify-content:space-between;min-height:54px;position:relative;z-index:3}.brandmark{display:flex;align-items:center;gap:15px;font-size:22px;font-weight:720;letter-spacing:.01em}.mark{display:grid;place-items:center;width:48px;height:48px;border:2px solid currentColor;border-radius:13px;font-size:25px;font-weight:820}.style-meta{text-align:right;color:var(--muted);font-size:18px;line-height:1.5}.style-meta b{display:block;color:var(--ink);font-size:20px}.hero{position:relative;z-index:2;margin-top:48px}.hero-kicker{color:var(--accent2);font-size:19px;font-weight:760;letter-spacing:.14em}.hero h1{max-width:900px;margin-top:18px;font-family:"Songti SC","STSong","Noto Serif CJK SC",serif;font-size:66px;line-height:1.08;letter-spacing:-.035em;text-wrap:balance}.hero p{margin-top:18px;color:var(--muted);font-size:25px;line-height:1.5;text-wrap:pretty}.story-content{position:relative;z-index:2;flex:1;display:flex;flex-direction:column;margin-top:30px;min-height:0}.metrics{display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.metric{padding:20px 20px 18px;border-left:1px solid var(--line)}.metric:first-child{border-left:0;padding-left:0}.metric small,.context small,.moment small{display:block;color:var(--muted);font-size:17px;font-weight:700;letter-spacing:.08em}.metric strong{display:block;margin-top:8px;font-size:38px;line-height:1;font-variant-numeric:tabular-nums}.metric span{display:block;margin-top:10px;color:var(--muted);font-size:17px;line-height:1.35}.moment{padding:20px 24px;background:var(--soft);border-radius:3px}.moment strong{display:block;margin-top:8px;font-family:"Songti SC","STSong",serif;font-size:27px}.moment p{margin-top:6px;color:var(--muted);font-size:19px;line-height:1.45}.context{padding-top:18px;border-top:1px solid var(--line)}.context ul{display:grid;gap:6px;margin-top:9px;padding-left:23px;color:var(--muted);font-size:18px;line-height:1.4}.signal,.weather-signal,.course-signal,.editorial-signal,.film-signal,.music-signal{display:block;width:100%%;height:auto}.baseline{stroke:var(--line);stroke-width:2}.signal-path{fill:none;stroke:var(--ink);stroke-width:7;stroke-linecap:round;stroke-linejoin:round}.signal-dots circle{fill:var(--paper);stroke:var(--accent);stroke-width:5}.empty-signal{display:grid;place-items:center;min-height:180px;color:var(--muted);font-size:21px;border-bottom:1px solid var(--line)}
/* Weather: circular observation first, forecast evidence second. */.family-weather{background:linear-gradient(180deg,var(--paper) 0 68%%,var(--soft) 68%%)}.family-weather .hero{display:grid;grid-template-columns:1fr 280px;gap:25px;align-items:end}.family-weather .hero h1{font-size:62px}.family-weather .story-content{display:grid;grid-template-columns:420px 1fr;grid-template-rows:475px auto;gap:28px 34px}.weather-orb{position:relative;display:grid;place-items:center;border-radius:50%%;background:var(--soft);overflow:hidden}.weather-rings{position:absolute;inset:0}.weather-rings i{position:absolute;left:50%%;top:50%%;width:calc(90px + var(--i)*42px);height:calc(90px + var(--i)*42px);border:2px solid color-mix(in srgb,var(--accent2) 55%%,transparent);border-radius:50%%;transform:translate(-50%%,-50%%)}.weather-rings i:nth-child(even){border-style:dashed}.weather-reading{position:relative;text-align:center}.weather-reading small{font-size:15px;letter-spacing:.16em;color:var(--muted)}.weather-reading strong{display:block;margin-top:8px;font-size:55px}.weather-reading span{font-size:19px;color:var(--muted)}.forecast-strip{align-self:center}.family-weather .metrics{grid-column:1/-1}.family-weather .moment{position:absolute;right:0;bottom:148px;width:476px}
/* Direction: map and compass. */.family-direction .story-content{gap:26px}.course-map{position:relative;display:grid;grid-template-columns:1fr 180px;align-items:center;min-height:470px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.course-line{padding-right:30px}.course-compass{position:absolute;right:6px;top:30px;width:150px;height:150px;border:1px solid var(--line);border-radius:50%%}.course-compass:before,.course-compass:after{content:"";position:absolute;background:var(--line)}.course-compass:before{left:50%%;top:0;width:1px;height:100%%}.course-compass:after{left:0;top:50%%;width:100%%;height:1px}.course-compass i{position:absolute;left:50%%;top:50%%;width:5px;height:65px;background:var(--accent);transform-origin:50%% 100%%;transform:translate(-50%%,-100%%) rotate(var(--angle));border-radius:3px}.course-compass b{position:absolute;left:50%%;top:9px;transform:translateX(-50%%);font-size:15px}.course-note{position:absolute;right:4px;bottom:44px;width:160px;text-align:center}.course-note small{color:var(--muted);font-size:16px}.course-note strong{display:block;margin-top:5px;font-size:27px}.family-direction .moment{margin-top:0}
/* Terrain: contour art dominates. */.family-terrain{padding:0;background:var(--ink);color:var(--paper)}.family-terrain .brand,.family-terrain .hero,.family-terrain .story-content,.family-terrain footer{margin-left:74px;margin-right:74px}.family-terrain .brand{margin-top:70px}.family-terrain .style-meta,.family-terrain .hero p,.family-terrain .metric small,.family-terrain .metric span,.family-terrain footer{color:color-mix(in srgb,var(--paper) 67%%,transparent)}.family-terrain .hero h1{color:var(--paper);font-size:61px}.terrain-map{position:relative;height:540px;margin-left:-74px;margin-right:-74px;overflow:hidden}.terrain-map svg{width:100%%;height:100%%}.terrain-map path{fill:none;stroke:var(--paper);stroke-width:7;stroke-linecap:round}.terrain-caption{position:absolute;right:74px;bottom:34px;text-align:right}.terrain-caption small{font-size:15px;letter-spacing:.18em;color:var(--accent)}.terrain-caption strong{display:block;margin-top:6px;font-size:33px}.terrain-caption span{display:block;margin-top:6px;max-width:420px;color:color-mix(in srgb,var(--paper) 65%%,transparent);font-size:18px}.family-terrain .metrics{border-color:color-mix(in srgb,var(--paper) 22%%,transparent)}.family-terrain .metric{border-color:color-mix(in srgb,var(--paper) 22%%,transparent)}.family-terrain .moment{margin-top:18px;background:color-mix(in srgb,var(--paper) 12%%,transparent)}
/* Editorial: hard rules, issue number, two-column evidence. */.family-editorial{background:var(--paper)}.family-editorial .brand{border-bottom:5px solid var(--ink);padding-bottom:18px}.family-editorial .hero{display:grid;grid-template-columns:1fr 220px;border-bottom:1px solid var(--ink);padding-bottom:28px}.family-editorial .hero h1{font-family:Georgia,"Songti SC",serif;font-size:71px}.editorial-grid{display:grid;grid-template-columns:170px 1fr 250px;gap:24px;align-items:stretch;border-bottom:1px solid var(--ink);padding-bottom:22px}.issue{border-right:1px solid var(--ink)}.issue small,.editorial-fact small{font-size:15px;letter-spacing:.15em}.issue strong{display:block;margin-top:10px;font-family:Georgia,serif;font-size:35px}.editorial-chart{align-self:center}.editorial-fact{padding-left:12px}.editorial-fact p{margin-top:12px;font-family:Georgia,"Songti SC",serif;font-size:23px;line-height:1.45}.family-editorial .metrics{margin-top:22px;border-color:var(--ink)}.family-editorial .metric{border-color:var(--ink)}.editorial-rule{height:8px;margin-top:22px;background:var(--accent)}.family-editorial .moment{margin-top:18px;background:transparent;border:1px solid var(--ink);border-radius:0}
/* Capsule: centered seal and message. */.family-capsule{background:radial-gradient(circle at 50%% 51%%,var(--soft) 0 290px,var(--paper) 292px)}.family-capsule .hero{text-align:center}.family-capsule .hero h1{margin-left:auto;margin-right:auto;font-size:58px}.family-capsule .hero p{max-width:720px;margin-left:auto;margin-right:auto}.capsule-stage{display:grid;grid-template-columns:390px 1fr;gap:52px;align-items:center;min-height:475px}.capsule-seal{display:grid;place-items:center;align-content:center;width:360px;height:360px;border:2px solid var(--accent);border-radius:50%%;outline:1px dashed var(--accent);outline-offset:-17px;text-align:center}.capsule-seal small{letter-spacing:.2em;color:var(--accent)}.capsule-seal strong{font-size:80px;line-height:1}.capsule-seal span{font-size:18px;color:var(--muted)}.capsule-message p{font-family:"Songti SC",serif;font-size:32px;line-height:1.55}.capsule-message small{display:block;margin-top:20px;color:var(--muted);font-size:18px}.family-capsule .moment{margin-top:20px}
/* Film: tactile strip and frames. */.family-film{background:#EEE4D4}.family-film .hero{margin-left:90px}.film-strip{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:0 -74px;padding:38px 74px;background:var(--ink)}.film-strip i{position:relative;height:238px;background:#D8D2C2;border:9px solid #F5EEDC;overflow:hidden}.film-strip i:before{content:"";position:absolute;left:12px;right:12px;bottom:15px;height:calc(180px - var(--level));min-height:20px;background:var(--accent2);opacity:.26}.film-strip i.active:after{content:"";position:absolute;left:50%%;bottom:24px;width:18px;height:18px;border-radius:50%%;background:var(--accent);transform:translateX(-50%%)}.film-strip b{position:absolute;left:8px;top:7px;color:var(--muted);font-size:12px}.film-caption{display:flex;justify-content:space-between;align-items:start;padding:18px 0}.film-caption small{letter-spacing:.14em}.film-caption p{max-width:610px;font-family:"Songti SC",serif;font-size:25px}.family-film .film-signal{height:145px}.family-film .metrics{margin-top:auto}
/* Rhythm: recording calendar as the hero. */.family-rhythm .hero{display:grid;grid-template-columns:1fr 310px}.rhythm-board{display:grid;grid-template-columns:180px 1fr;gap:35px;align-items:center;padding:35px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.rhythm-count strong{display:block;font-size:92px;line-height:1}.rhythm-count small{color:var(--muted);font-size:18px}.rhythm-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:12px}.rhythm-grid i{position:relative;display:grid;place-items:center;aspect-ratio:1;border:1px solid var(--line);border-radius:50%%}.rhythm-grid i.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}.rhythm-grid span{font-size:14px}.family-rhythm .metrics{margin-top:28px}.family-rhythm .moment{margin-top:22px}.family-rhythm .context{margin-top:18px}
/* Journey: one large perforated ticket. */.family-journey{background:var(--soft)}.family-journey .hero h1{font-size:63px}.ticket{position:relative;display:grid;grid-template-columns:1fr 245px;min-height:430px;margin-top:5px;background:var(--paper);border:2px solid var(--ink)}.ticket:before,.ticket:after{content:"";position:absolute;right:225px;width:38px;height:38px;border-radius:50%%;background:var(--soft);z-index:2}.ticket:before{top:-21px}.ticket:after{bottom:-21px}.ticket-main{padding:42px 48px;border-right:2px dashed var(--ink)}.ticket-main>small{letter-spacing:.15em}.ticket-main p{margin-top:62px;font-family:"Songti SC",serif;font-size:29px;line-height:1.5}.stations{display:flex;align-items:center;gap:12px;margin-top:52px}.stations b{font-size:20px}.stations i{flex:1;height:2px;background:var(--accent);position:relative}.stations i:after{content:"";position:absolute;right:0;top:-5px;border-left:9px solid var(--accent);border-top:6px solid transparent;border-bottom:6px solid transparent}.ticket-stub{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;writing-mode:vertical-rl}.ticket-stub small{letter-spacing:.18em}.ticket-stub strong{margin:20px 0;font-size:31px}.ticket-stub span{color:var(--muted);font-size:18px}.family-journey .metrics{margin-top:28px}.family-journey .moment{margin-top:20px}
/* Music: physical record + tracklist. */.family-music{background:var(--ink);color:var(--paper)}.family-music .style-meta,.family-music .hero p,.family-music .metric small,.family-music .metric span,.family-music footer{color:color-mix(in srgb,var(--paper) 65%%,transparent)}.family-music .hero h1{color:var(--paper);font-size:60px}.record-stage{display:grid;grid-template-columns:430px 1fr;gap:55px;align-items:center}.vinyl{display:grid;place-items:center;width:410px;height:410px;border-radius:50%%;background:repeating-radial-gradient(circle,#172E45 0 4px,#0A2037 5px 9px);box-shadow:inset 0 0 0 2px rgba(255,255,255,.15)}.vinyl-label{display:grid;place-items:center;align-content:center;width:136px;height:136px;border-radius:50%%;background:var(--accent);color:var(--paper);text-align:center}.vinyl-label small{font-size:16px}.vinyl-label strong{font-size:18px}.tracklist>small{color:var(--accent);letter-spacing:.17em}.tracklist>strong{display:block;margin-top:15px;font-family:"Songti SC",serif;font-size:32px;line-height:1.35}.tracklist ol{margin-top:28px;list-style-position:inside}.tracklist li{padding:15px 0;border-bottom:1px solid rgba(255,255,255,.18);font-size:19px}.tracklist b{float:right}.music-wave{height:145px;overflow:hidden}.family-music .signal-path{stroke:var(--paper)}.family-music .baseline{stroke:rgba(255,255,255,.2)}.family-music .signal-dots circle{fill:var(--ink);stroke:var(--accent)}.family-music .moment{margin-top:16px;background:rgba(255,255,255,.08)}
/* Letter: a private page, evidence inside prose. */.family-letter{background:#E9DFD0}.family-letter .hero{display:none}.family-letter .story-content{justify-content:center}.letter-sheet{position:relative;margin:15px 42px 25px;padding:64px 72px 55px;background:var(--paper);box-shadow:0 24px 70px rgba(36,43,42,.12);transform:rotate(-.7deg)}.letter-sheet>small{letter-spacing:.17em;color:var(--accent)}.letter-sheet h2{margin-top:40px;font-family:"Songti SC",serif;font-size:34px}.letter-sheet p{margin-top:28px;font-family:"Songti SC",serif;font-size:31px;line-height:1.75}.letter-sheet .letter-evidence{font-family:inherit;font-size:24px;color:var(--muted)}.letter-sign{margin-top:45px;text-align:right;font-family:"Songti SC",serif;font-size:27px}.letter-sign span{color:var(--muted);font-size:17px}.family-letter .moment,.family-letter .context{margin-left:42px;margin-right:42px}
/* Identity: bold observer label and dossier. */.family-identity{background:var(--paper)}.family-identity .hero h1{font-size:54px}.identity-card{position:relative;padding:48px 52px;background:var(--ink);color:var(--paper)}.identity-card>small{letter-spacing:.18em;color:var(--accent)}.identity-card>strong{display:block;margin-top:22px;font-family:"Songti SC",serif;font-size:82px;line-height:1}.identity-card>p{margin-top:18px;color:rgba(255,255,255,.66);font-size:21px}.identity-card dl{display:grid;grid-template-columns:repeat(3,1fr);margin-top:55px;border-top:1px solid rgba(255,255,255,.25)}.identity-card dl div{padding:20px;border-left:1px solid rgba(255,255,255,.25)}.identity-card dl div:first-child{border-left:0}.identity-card dt{font-size:15px;color:rgba(255,255,255,.55)}.identity-card dd{margin-top:8px;font-size:24px}.family-identity .metrics{margin-top:26px}.family-identity .moment{margin-top:18px}
/* Generative: art owns the canvas. */.family-generative{background:var(--ink);color:var(--paper)}.family-generative .style-meta,.family-generative .hero p,.family-generative .metric small,.family-generative .metric span,.family-generative footer{color:rgba(255,255,255,.62)}.family-generative .hero{position:absolute;left:74px;top:126px;width:650px}.family-generative .hero h1{color:var(--paper);font-size:57px}.family-generative .story-content{margin-top:175px}.generative-art{position:relative;height:620px}.generative-art svg{width:100%%;height:100%%}.star-lines line{stroke:rgba(255,255,255,.28);stroke-width:1.5}.stars circle{fill:var(--paper);stroke:var(--accent);stroke-width:2}.finger-rings circle{fill:none;stroke:var(--paper);stroke-width:7;opacity:.72}.art-label{position:absolute;right:20px;bottom:30px;text-align:right}.art-label small{color:var(--accent);letter-spacing:.17em}.art-label strong{display:block;margin-top:7px;font-size:29px}.family-generative .metrics{border-color:rgba(255,255,255,.2)}.family-generative .metric{border-color:rgba(255,255,255,.2)}.family-generative .moment{margin-top:18px;background:rgba(255,255,255,.08)}
/* B variants change narrative structure, not only color or title. */
.weather-week{grid-column:1/-1;padding:26px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.weather-week-title{display:flex;align-items:end;justify-content:space-between}.weather-week-title small{letter-spacing:.16em;color:var(--accent2)}.weather-week-title strong{max-width:560px;text-align:right;font-family:"Songti SC",serif;font-size:27px}.weather-week-cells{display:grid;grid-template-columns:repeat(7,1fr);gap:12px;margin-top:25px}.weather-week-cells i{display:grid;place-items:center;min-height:118px;border:1px solid var(--line);font-style:normal}.weather-week-cells i.on{background:var(--ink);color:var(--paper)}.weather-week-cells b{font-size:17px}.weather-week-cells span{width:24px;height:24px;border:2px solid currentColor;border-radius:50%%}.weather-week-cells small{font-size:12px}.weather-week-line{height:118px;overflow:hidden;margin-top:12px}
.logbook{padding:34px 38px;border:1px solid var(--ink);background:repeating-linear-gradient(0deg,transparent 0 46px,var(--line) 47px 48px)}.logbook-title{display:flex;justify-content:space-between;gap:30px}.logbook-title small{letter-spacing:.16em}.logbook-title strong{max-width:560px;text-align:right;font-family:"Songti SC",serif;font-size:28px}.logbook dl{display:grid;grid-template-columns:repeat(3,1fr);margin-top:28px;background:var(--paper);border:1px solid var(--line)}.logbook dl div{padding:18px;border-left:1px solid var(--line)}.logbook dl div:first-child{border-left:0}.logbook dt{font-size:14px;color:var(--muted)}.logbook dd{margin-top:8px;font-size:26px;font-weight:750}.logbook-chart{height:205px;overflow:hidden;background:var(--paper);margin-top:20px}
.terrain-route .route{fill:none;stroke:var(--accent);stroke-width:12}.terrain-route .route-points circle{fill:var(--ink);stroke:var(--paper);stroke-width:5}.terrain-route .route-points text{fill:var(--paper);font-size:17px;text-anchor:middle}.terrain-route:after{content:"A ROUTE THROUGH THIS PERIOD";position:absolute;left:74px;bottom:42px;color:var(--accent);font-size:15px;letter-spacing:.15em}
.headline-sheet{display:grid;grid-template-columns:340px 1fr;border-top:1px solid var(--ink);border-bottom:1px solid var(--ink)}.headline-number{padding:28px 30px 28px 0;border-right:1px solid var(--ink)}.headline-number small,.headline-copy small{letter-spacing:.15em}.headline-number strong{display:block;margin-top:15px;font-family:Georgia,serif;font-size:67px}.headline-number span{color:var(--muted);font-size:17px}.headline-copy{padding:28px 0 28px 34px}.headline-copy p{margin-top:18px;font-family:Georgia,"Songti SC",serif;font-size:33px;line-height:1.35}.headline-signal{height:190px;overflow:hidden}
.future-letter{position:relative;margin:10px 90px 28px;padding:60px 66px;background:var(--paper);border:1px solid var(--accent);box-shadow:12px 14px 0 var(--soft)}.future-letter>small{letter-spacing:.18em;color:var(--accent)}.future-letter>p{max-width:650px;margin-top:38px;font-family:"Songti SC",serif;font-size:35px;line-height:1.6}.future-note{margin-top:30px;padding-top:23px;border-top:1px solid var(--line);color:var(--muted);font-size:20px;line-height:1.55}.future-stamp{position:absolute;right:45px;top:35px;width:100px;height:100px;display:grid;place-items:center;border:2px dashed var(--accent);border-radius:50%%;color:var(--accent);font-size:14px;transform:rotate(8deg)}
.film-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:15px;padding:28px;background:var(--ink)}.film-grid i{position:relative;height:145px;background:#D8D2C2;border:7px solid #F5EEDC;overflow:hidden}.film-grid i span{position:absolute;left:18px;right:18px;bottom:18px;background:var(--accent2);opacity:.35}.film-grid i.active:after{content:"";position:absolute;right:15px;top:15px;width:12px;height:12px;border-radius:50%%;background:var(--accent)}.film-grid i b{position:absolute;left:12px;top:10px;color:var(--muted);font-size:12px}.film-grid-caption{display:flex;justify-content:space-between;padding:18px 0}.film-grid-caption small{letter-spacing:.14em}.film-grid-caption p{max-width:560px;font-family:"Songti SC",serif;font-size:23px}
.moon-board{display:grid;grid-template-columns:250px 1fr;gap:38px;align-items:center;padding:30px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.moon-title small{letter-spacing:.14em;color:var(--accent2)}.moon-title strong{display:block;margin-top:16px;font-size:38px}.moon-title p{margin-top:13px;color:var(--muted);font-size:18px;line-height:1.45}.moon-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:15px}.moon-grid i{position:relative;display:grid;place-items:center;aspect-ratio:1;border-radius:50%%;background:var(--soft);overflow:hidden;font-style:normal}.moon-grid i:before{content:"";position:absolute;inset:0;background:var(--ink);clip-path:inset(0 calc(100%% - var(--phase)) 0 0)}.moon-grid i:not(.on){opacity:.25}.moon-grid span{position:relative;z-index:2;color:var(--paper);font-size:11px}
.passport{display:grid;grid-template-columns:340px 1fr;min-height:440px;box-shadow:12px 14px 0 color-mix(in srgb,var(--ink) 12%%,transparent)}.passport-cover{display:flex;flex-direction:column;align-items:center;justify-content:center;background:var(--ink);color:var(--paper);text-align:center}.passport-cover small{letter-spacing:.2em;color:var(--accent)}.passport-cover strong{margin-top:25px;font-family:"Songti SC",serif;font-size:44px}.passport-cover span{margin-top:18px;font-size:17px}.passport-page{position:relative;padding:48px;background:var(--paper)}.passport-page p{margin-top:190px;font-family:"Songti SC",serif;font-size:25px;line-height:1.5}.passport-page>small{display:block;margin-top:16px;color:var(--muted)}.stamp{position:absolute;display:grid;place-items:center;align-content:center;width:135px;height:135px;border:3px double var(--accent);border-radius:50%%;text-align:center;color:var(--accent);transform:rotate(-7deg)}.stamp b{font-size:23px}.stamp-one{left:52px;top:43px}.stamp-two{right:52px;top:73px;transform:rotate(9deg)}
.single-stage{display:grid;grid-template-columns:430px 1fr;gap:48px;align-items:center}.single-cover{position:relative;height:430px;padding:35px;background:var(--accent);color:var(--paper);overflow:hidden}.single-cover>small{letter-spacing:.16em}.single-cover>strong{position:absolute;left:35px;right:35px;bottom:63px;font-family:"Songti SC",serif;font-size:35px}.single-cover>span{position:absolute;left:35px;bottom:30px;font-size:16px}.single-wave{position:absolute;left:-55px;right:-55px;top:85px;transform:rotate(-8deg);opacity:.8}.single-wave .signal-path{stroke:var(--paper)}.single-wave .signal-dots circle{fill:var(--accent);stroke:var(--paper)}.single-notes>small{color:var(--accent);letter-spacing:.16em}.single-notes>p{margin-top:18px;font-family:"Songti SC",serif;font-size:28px;line-height:1.5}.single-notes dl{margin-top:25px}.single-notes dl div{display:flex;justify-content:space-between;padding:14px 0;border-bottom:1px solid rgba(255,255,255,.18)}.single-notes dt{color:rgba(255,255,255,.55)}.single-notes dd{font-weight:750}
.no-verdict-sheet{min-height:650px;padding-left:180px}.no-verdict-sheet .ellipsis{position:absolute;left:55px;top:30px;font-family:Georgia,serif;font-size:118px;color:var(--accent)}.no-verdict-sheet h2{font-size:43px}.no-verdict-sheet p{font-size:29px}
.dossier{display:grid;grid-template-columns:245px 1fr;border:2px solid var(--ink)}.dossier-index{display:flex;flex-direction:column;justify-content:space-between;padding:35px;background:var(--soft);border-right:2px solid var(--ink)}.dossier-index small{letter-spacing:.18em}.dossier-index strong{font-size:31px;writing-mode:vertical-rl}.dossier-index span{font-size:13px}.dossier-main{padding:42px 48px}.dossier-main>small{color:var(--accent);letter-spacing:.16em}.dossier-main h2{margin-top:20px;font-family:"Songti SC",serif;font-size:52px}.dossier-main p{margin-top:13px;color:var(--muted);font-size:20px}.dossier-main dl{display:grid;grid-template-columns:repeat(3,1fr);margin-top:45px;border-top:1px solid var(--line)}.dossier-main dl div{padding:20px 10px;border-left:1px solid var(--line)}.dossier-main dl div:first-child{border-left:0}.dossier-main dt{color:var(--muted);font-size:14px}.dossier-main dd{margin-top:8px;font-size:24px;font-weight:720}
/* Content-led layouts: these templates own their headline inside the artefact. */
.family-direction.variant-b .hero,.family-capsule.variant-b .hero,.family-film .hero,.family-journey .hero,.family-music .hero,.family-identity .hero{display:none}
.family-direction.variant-b .story-content,.family-capsule.variant-b .story-content,.family-film .story-content,.family-journey .story-content,.family-music .story-content,.family-identity .story-content{margin-top:54px;justify-content:center}
.family-film .film-caption p,.family-film .film-grid-caption p{font-size:29px;line-height:1.35}.family-direction.variant-b .logbook-title strong{font-size:35px;line-height:1.25}.family-journey .ticket-main p{font-size:34px}.family-music .tracklist>strong{font-size:36px}.family-identity .identity-card>strong{font-size:56px}
/* Final family corrections after shared flex sizing. */.family-weather .story-content{grid-template-rows:420px auto auto;gap:24px 34px}.family-weather .moment{position:static;width:auto;grid-column:1/-1}.family-weather.variant-b .story-content{grid-template-rows:auto auto auto}.family-film.variant-b .metrics{margin-top:18px}.family-rhythm.variant-b .metrics{margin-top:24px}.family-journey.variant-b .metrics{margin-top:26px}.family-music.variant-b .moment{margin-top:24px}
.social-hook{display:flex;align-items:baseline;gap:13px;width:max-content;max-width:100%%;margin-bottom:13px;padding-bottom:9px;border-bottom:2px solid var(--accent)}.social-hook small{flex:none;color:var(--accent);font-size:13px;font-weight:850;letter-spacing:.14em}.social-hook strong{overflow:hidden;color:var(--ink);font-family:"Songti SC","STSong",serif;font-size:22px;line-height:1.2;text-overflow:ellipsis;white-space:nowrap}.family-terrain .social-hook strong,.family-music .social-hook strong,.family-generative .social-hook strong{color:var(--paper)}
.analysis-note{position:relative;flex-shrink:0;margin-top:16px;padding:15px 21px;border-left:5px solid var(--accent);background:color-mix(in srgb,var(--soft) 72%%,transparent)}.analysis-note small{display:block;color:var(--accent2);font-size:13px;font-weight:800;letter-spacing:.13em}.analysis-note>strong{display:block;margin-top:6px;color:var(--ink);font-family:"Songti SC","STSong",serif;font-size:25px;line-height:1.15}.analysis-note p{margin-top:6px;color:var(--ink);font-family:"Songti SC","STSong",serif;font-size:16px;line-height:1.42;text-wrap:pretty}.analysis-note>span{display:block;margin-top:7px;padding-top:6px;border-top:1px solid var(--line);color:var(--accent2);font-size:13px;font-weight:750;letter-spacing:.03em}.family-terrain .analysis-note,.family-music .analysis-note,.family-generative .analysis-note{background:rgba(255,255,255,.09);border-left-color:var(--accent)}.family-terrain .analysis-note p,.family-music .analysis-note p,.family-generative .analysis-note p,.family-terrain .analysis-note>strong,.family-music .analysis-note>strong,.family-generative .analysis-note>strong{color:var(--paper)}.family-terrain .analysis-note small,.family-music .analysis-note small,.family-generative .analysis-note small,.family-terrain .analysis-note>span,.family-music .analysis-note>span,.family-generative .analysis-note>span{color:var(--accent)}
/* Twenty-four silhouette grammars: each layout changes the physical object, not just its palette. */
[data-layout-mode="radar-poster"]{background:radial-gradient(circle at 24%% 45%%,var(--soft) 0 285px,transparent 287px),var(--paper)}[data-layout-mode="radar-poster"] .brand{justify-content:flex-end}[data-layout-mode="radar-poster"] .brandmark{position:absolute;left:0;top:0}[data-layout-mode="radar-poster"] .hero{margin-top:24px}[data-layout-mode="radar-poster"] .hero h1{font-size:52px}[data-layout-mode="radar-poster"] .story-content{grid-template-rows:340px auto auto;margin-top:16px}[data-layout-mode="radar-poster"] .analysis-note{border:0;border-radius:160px 0 0 160px;padding-left:54px}
[data-layout-mode="horizontal-forecast"]{padding-left:118px;background:linear-gradient(90deg,var(--ink) 0 52px,var(--paper) 52px)}[data-layout-mode="horizontal-forecast"] .brandmark{writing-mode:vertical-rl;position:absolute;left:-83px;top:0;color:var(--paper)}[data-layout-mode="horizontal-forecast"] .hero{margin-top:26px}[data-layout-mode="horizontal-forecast"] .analysis-note{border-left:0;border-top:5px solid var(--accent2);background:transparent}
[data-layout-mode="navigation-chart"]{background-image:linear-gradient(var(--line) 1px,transparent 1px),linear-gradient(90deg,var(--line) 1px,transparent 1px);background-size:64px 64px}[data-layout-mode="navigation-chart"] .brand{background:var(--paper);padding:0 14px}[data-layout-mode="navigation-chart"] .hero{background:var(--paper);padding:12px 22px;margin-top:20px;margin-left:-22px;width:78%%}[data-layout-mode="navigation-chart"] .hero h1{font-size:52px}[data-layout-mode="navigation-chart"] .story-content{margin-top:12px}[data-layout-mode="navigation-chart"] .course-map{min-height:350px}[data-layout-mode="navigation-chart"] .metric{padding-top:13px;padding-bottom:12px}[data-layout-mode="navigation-chart"] .analysis-note{margin-left:180px;background:var(--ink)}[data-layout-mode="navigation-chart"] .analysis-note p{color:var(--paper)}
[data-layout-mode="lined-notebook"]{padding-left:142px;background:linear-gradient(90deg,var(--paper) 0 105px,var(--accent) 106px 109px,var(--paper) 110px),repeating-linear-gradient(0deg,transparent 0 46px,var(--line) 47px 48px),var(--paper)}[data-layout-mode="lined-notebook"] .brandmark{position:absolute;left:-112px;top:8px;writing-mode:vertical-rl}[data-layout-mode="lined-notebook"] .analysis-note{background:transparent;border:2px solid var(--ink);transform:rotate(.4deg)}
[data-layout-mode="full-bleed-topographic"] .brand{border-bottom:1px solid rgba(255,255,255,.25)}[data-layout-mode="full-bleed-topographic"] .analysis-note{position:absolute;left:74px;bottom:118px;width:510px;backdrop-filter:blur(8px)}[data-layout-mode="full-bleed-topographic"] footer{position:absolute;left:74px;right:74px;bottom:55px}
[data-layout-mode="foldout-route-map"]{background:linear-gradient(90deg,var(--ink) 0 33%%,#123B58 33%% 66%%,var(--ink) 66%%)}[data-layout-mode="foldout-route-map"]:after{content:"";position:absolute;inset:0 33%%;border-left:1px dashed rgba(255,255,255,.35);border-right:1px dashed rgba(255,255,255,.35);pointer-events:none}[data-layout-mode="foldout-route-map"] .analysis-note{margin:0 -26px;background:var(--paper);color:var(--ink);transform:rotate(-1deg)}[data-layout-mode="foldout-route-map"] .analysis-note p{color:var(--ink)}
[data-layout-mode="magazine-cover"]{padding:38px 50px 34px;box-shadow:inset 0 0 0 24px var(--ink)}[data-layout-mode="magazine-cover"] .brand{border-bottom:9px solid var(--ink)}[data-layout-mode="magazine-cover"] .style-meta b{font-family:Georgia,serif;font-size:31px}[data-layout-mode="magazine-cover"] .analysis-note{border:0;background:var(--accent);color:var(--paper);columns:2;column-gap:26px}[data-layout-mode="magazine-cover"] .analysis-note p,[data-layout-mode="magazine-cover"] .analysis-note small{color:var(--paper)}
[data-layout-mode="newspaper-front-page"]{filter:grayscale(.18)}[data-layout-mode="newspaper-front-page"] .brandmark{font-family:Georgia,serif;font-size:32px}[data-layout-mode="newspaper-front-page"] .hero h1{font-size:82px;line-height:.96}[data-layout-mode="newspaper-front-page"] .analysis-note{background:transparent;border:1px solid var(--ink);border-left:12px solid var(--ink);columns:2;column-rule:1px solid var(--line)}
[data-layout-mode="museum-label-and-seal"]{background:linear-gradient(90deg,var(--paper) 0 67%%,var(--soft) 67%%)}[data-layout-mode="museum-label-and-seal"] .brand{width:64%%}[data-layout-mode="museum-label-and-seal"] .analysis-note{position:absolute;right:48px;top:190px;width:290px;min-height:500px;border:1px solid var(--ink);background:var(--paper);display:flex;flex-direction:column;justify-content:center}[data-layout-mode="museum-label-and-seal"] .story-content{width:62%%}
[data-layout-mode="single-letter-sheet"]{background:#D9CDBB;padding:42px 50px}[data-layout-mode="single-letter-sheet"] .brand{opacity:.7}[data-layout-mode="single-letter-sheet"] .future-letter{margin:0 45px;padding-bottom:42px;transform:rotate(.6deg)}[data-layout-mode="single-letter-sheet"] .analysis-note{margin:0 45px;background:var(--paper);border:0;padding:28px 52px;box-shadow:12px 14px 0 rgba(0,0,0,.08)}
[data-layout-mode="horizontal-film-strip"]{background:linear-gradient(180deg,#171F29 0 135px,#EEE4D4 135px 1305px,#171F29 1305px)}[data-layout-mode="horizontal-film-strip"] .brand{color:#F5EEDC}[data-layout-mode="horizontal-film-strip"] .analysis-note{background:#F5EEDC;border:0;box-shadow:8px 8px 0 var(--accent);transform:rotate(-.5deg)}
[data-layout-mode="contact-sheet"]{padding:52px;background:#20252B;color:#F5EEDC}[data-layout-mode="contact-sheet"] .brand{color:#F5EEDC}[data-layout-mode="contact-sheet"] .film-grid{border:18px solid #111820}[data-layout-mode="contact-sheet"] .analysis-note{background:#F5EEDC;border:0}[data-layout-mode="contact-sheet"] .analysis-note p{color:#20252B}
[data-layout-mode="wall-calendar"]{background:linear-gradient(180deg,var(--accent) 0 175px,var(--paper) 175px)}[data-layout-mode="wall-calendar"] .brand{color:var(--paper)}[data-layout-mode="wall-calendar"] .hero{margin-top:55px}[data-layout-mode="wall-calendar"] .analysis-note{border:0;border-top:12px solid var(--ink);background:transparent}
[data-layout-mode="orbital-poster"]{background:radial-gradient(circle at 72%% 43%%,var(--ink) 0 300px,var(--soft) 302px 304px,var(--paper) 306px)}[data-layout-mode="orbital-poster"] .hero{width:54%%;margin-top:18px}[data-layout-mode="orbital-poster"] .hero h1{font-size:44px}[data-layout-mode="orbital-poster"] .hero p{font-size:20px}[data-layout-mode="orbital-poster"] .story-content{margin-top:8px}[data-layout-mode="orbital-poster"] .moon-board{grid-template-columns:190px 1fr;border:0;padding:5px 0}[data-layout-mode="orbital-poster"] .moon-grid{grid-template-columns:repeat(10,1fr);gap:8px}[data-layout-mode="orbital-poster"] .metrics{display:none}[data-layout-mode="orbital-poster"] .analysis-note{width:72%%;margin-left:auto;border-radius:100px 0 0 100px;padding:14px 18px 14px 48px}[data-layout-mode="orbital-poster"] .analysis-note p{font-size:15px}
[data-layout-mode="oversized-ticket"]{padding:55px 45px;background:repeating-linear-gradient(135deg,var(--soft) 0 18px,#DFD5C7 18px 36px)}[data-layout-mode="oversized-ticket"] .ticket{transform:rotate(-1.2deg);box-shadow:18px 20px 0 rgba(10,47,85,.13)}[data-layout-mode="oversized-ticket"] .analysis-note{border:2px dashed var(--ink);background:var(--paper);transform:rotate(.8deg)}
[data-layout-mode="open-passport-spread"]{padding:58px 48px;background:#C9B89C}[data-layout-mode="open-passport-spread"] .brand{color:#493B31}[data-layout-mode="open-passport-spread"] .passport{transform:perspective(900px) rotateX(2deg);box-shadow:0 28px 55px rgba(30,25,20,.22)}[data-layout-mode="open-passport-spread"] .analysis-note{border:3px double var(--accent);background:#F4EAD8;transform:rotate(-.4deg)}
[data-layout-mode="album-sleeve"]{padding:48px;background:#092842}[data-layout-mode="album-sleeve"] .record-stage{background:#E5644D;padding:35px;color:#F8F0E5}[data-layout-mode="album-sleeve"] .analysis-note{margin-left:310px;border:0;background:transparent;border-bottom:1px solid rgba(255,255,255,.3)}
[data-layout-mode="music-single-cover"]{background:linear-gradient(135deg,#0A2F55 0 50%%,#D66548 50%%);padding:55px}[data-layout-mode="music-single-cover"] .single-stage{align-items:stretch}[data-layout-mode="music-single-cover"] .single-cover{background:var(--paper);color:var(--ink);transform:rotate(-2deg)}[data-layout-mode="music-single-cover"] .analysis-note{background:var(--paper);border:0;transform:translateX(35px)}[data-layout-mode="music-single-cover"] .analysis-note p{color:var(--ink)}
[data-layout-mode="handwritten-letter"]{background:repeating-linear-gradient(0deg,#E9DFD0 0 42px,#DCCFBD 43px 44px)}[data-layout-mode="handwritten-letter"] .letter-sheet{border-radius:0;transform:rotate(-1.2deg)}[data-layout-mode="handwritten-letter"] .analysis-note{margin:0 90px;background:transparent;border:0;border-bottom:2px solid var(--accent);font-style:italic}
[data-layout-mode="unfinished-manuscript"]{background:#EEE7DA}[data-layout-mode="unfinished-manuscript"] .brandmark{opacity:.45}[data-layout-mode="unfinished-manuscript"] .no-verdict-sheet{background:transparent;box-shadow:none;border-left:1px solid var(--accent);transform:none}[data-layout-mode="unfinished-manuscript"] .analysis-note{background:transparent;border:0;padding-left:180px}[data-layout-mode="unfinished-manuscript"] .analysis-note:before{content:"待续";position:absolute;left:30px;top:25px;color:var(--accent);font-size:34px;transform:rotate(-8deg)}
[data-layout-mode="trading-card"]{padding:84px;border-radius:42px;background:linear-gradient(155deg,var(--paper),var(--soft));box-shadow:inset 0 0 0 50px #d9e0df,inset 0 0 0 64px var(--ink)}[data-layout-mode="trading-card"] .identity-card{border-radius:24px;box-shadow:0 15px 0 var(--accent)}[data-layout-mode="trading-card"] .analysis-note{border-radius:18px;border:2px solid var(--ink);background:var(--paper)}
[data-layout-mode="case-file-folder"]{background:linear-gradient(90deg,#D8C79E 0 34px,#E9DAB7 34px);padding:80px 70px 45px}[data-layout-mode="case-file-folder"]:before{content:"%s";position:absolute;right:70px;top:32px;padding:12px 34px;background:#E9DAB7;border-radius:14px 14px 0 0;font-weight:800;letter-spacing:.12em}[data-layout-mode="case-file-folder"] .analysis-note{background:#FFFDF5;border:1px solid var(--ink);box-shadow:7px 9px 0 rgba(0,0,0,.09)}
[data-layout-mode="full-bleed-night-sky"]{padding:46px;background:radial-gradient(circle at 20%% 20%%,#244C69,#071E34 60%%)}[data-layout-mode="full-bleed-night-sky"] .brandmark .mark{border-radius:50%%}[data-layout-mode="full-bleed-night-sky"] .analysis-note{position:absolute;left:80px;right:80px;bottom:120px;background:rgba(7,30,52,.64);border:1px solid rgba(255,255,255,.25);backdrop-filter:blur(10px)}[data-layout-mode="full-bleed-night-sky"] footer{position:absolute;left:80px;right:80px;bottom:48px}
[data-layout-mode="minimal-art-print"]{padding:108px;background:#FAF8F0;color:#151D25;box-shadow:inset 0 0 0 54px #d9e0df,inset 0 0 0 55px #151D25}[data-layout-mode="minimal-art-print"] .brand{border-bottom:1px solid #151D25}[data-layout-mode="minimal-art-print"] .generative-art{height:500px}[data-layout-mode="minimal-art-print"] .analysis-note{background:transparent;border:0;border-top:1px solid #151D25;padding-left:0}[data-layout-mode="minimal-art-print"] footer{color:#55606A}
footer{position:relative;z-index:3;display:grid;grid-template-columns:1fr auto;gap:30px;align-items:end;margin-top:24px;padding-top:17px;border-top:1px solid var(--line);color:var(--muted);font-size:15px;line-height:1.45}footer b{display:block;color:var(--ink);font-size:16px}.family-terrain footer b,.family-music footer b,.family-generative footer b{color:var(--paper)}
</style></head>
<body data-share-safe="%s" data-style-id="%s" data-content-role="%s" data-renderer="weight-story-v2"><div id="viewport" class="viewport"><main id="artboard" class="artboard family-%s variant-%s" data-layout-mode="%s" data-motion-mode="%s" data-primary-domain="%s"%s data-palette="%d">
<header class="brand"><div class="brandmark"><span class="mark">M</span><span>%s</span></div><div class="style-meta"><b>%s</b>%s%s</div></header>
<section class="hero"><div><div class="social-hook"><small>阶段肖像</small><strong>%s</strong></div><div class="hero-kicker">%s · %s</div><h1>%s</h1><p>%s</p></div></section>
<div class="story-content">%s</div>
<footer><div><b>%s</b>%s</div><div>%s%s%s%s</div></footer>
</main></div><script>(()=>{const W=1080,H=1440,v=document.getElementById('viewport'),a=document.getElementById('artboard');function fit(){const s=Math.min(innerWidth/W,innerHeight/H);v.style.width=`${W*s}px`;v.style.height=`${H*s}px`;a.style.transform=`scale(${s})`}addEventListener('resize',fit,{passive:true});fit();window.__ready=true})()</script></body></html>""" % (
        _safe(product_name), _safe(catalog_style.name),
        _css_string(case_label),
        "true" if share_safe else "false", _safe(style_id), _safe(view["content_role"]), _safe(family), _safe(variant.lower()),
        _safe(catalog_style.layout_mode), _safe(catalog_style.motion_mode),
        _safe(catalog_style.preferred_domains[0]),
        (' data-story-domain="%s"' % _safe(domain)) if domain != DEFAULT_DOMAIN else "",
        palette,
        _safe(product_name), _safe(catalog_style.name), _safe(view["edition"]), _safe(exploration),
        view["situation_title"], view["story_kicker"], _safe(catalog_style.variant), view["story_headline"], view["story_subhead"],
        content, _safe(privacy), _safe(disclaimer), _safe(_fill(catalog_style.signature, words)),
        view["member_footer"], view["exact_weight_footer"], _safe(" · " + view["date_label"]),
    )


def available_story_styles() -> List[str]:
    return sorted(style_id for style_id, style in STYLES_BY_ID.items() if style.family in FAMILY_RENDERERS)
