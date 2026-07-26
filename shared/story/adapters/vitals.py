"""Vitals adapter: the first domain whose reading is not one thing.

Weight, sleep and records each have a single number per day, so one lexicon per
domain was enough.  Vitals does not: 收缩压 in mmHg, 心率 in 次/分 and 体温 in ℃
are different quantities that happen to be stored in the same table.  A card can
carry exactly one unit — the renderer appends `lexicon["unit"]` to every numeric
fact — so the honest unit of narration here is one *component*, not the domain.

Hence `COMPONENTS`: each entry is its own lexicon plus its own noise band, and
`lexicon_for_component` hands the renderer the wording for whichever one the card
is about.  `render_weight_story_html` already accepts a `lexicon` override beside
`domain`, so this costs the renderer nothing.  `subject` names the component
(收缩压), never 血压: plotting only systolic under a 血压 subject would be a card
claiming to show blood pressure while showing half of it.

Systolic and diastolic stay separate for the same reason.  They move
independently, and a single direction word over the pair would misdescribe
whichever half moved the other way.

What this module refuses to read is the entire reference-range apparatus the rest
of the suite owns: `_METRIC_RANGES` in `mediwise-health-tracker/scripts/
validators.py`, `_VALUE_RANGES` in `health-monitor/scripts/threshold.py`, and
`_BP_COMPONENTS` plus the regression fit in `health-monitor/scripts/trend.py`.
Those tables answer 「这个数正常吗」, and answering it on a story card is a
diagnosis.  A reading outside any range is narrated as a recorded number like any
other, which is why the bands below are measurement noise and nothing else.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import List, Mapping, Optional, Sequence

DOMAIN = "vitals"

# One entry per narratable component.
#
# `metric_type` is the key the row carries in `medical.db.health_metrics`; `field`
# is where the number sits inside a blood-pressure payload, which validators.py
# stores as the JSON string {"systolic": 130, "diastolic": 85}.
#
# `band` and `spot_band` are measurement noise in that component's own unit —
# cuff-to-cuff variability, sensor drift, the rounding a person does when they
# write a number down by hand.  They decide when a difference is worth calling a
# direction at all.  They are emphatically not clinical thresholds: nothing here
# knows what a high reading is, and 5 mmHg is meaningless for 体温.
COMPONENTS: Mapping[str, Mapping[str, object]] = {
    "heart_rate": {
        "metric_type": "heart_rate",
        "field": None,
        "band": 4.0,
        "spot_band": 10.0,
        "lexicon": {
            "subject": "心率",
            "reading": "记录心率",
            "unit": "次/分",
            "up": "走高",
            "down": "走低",
            "series_label": "每日中位心率",
            "fold_note": "同日多次取中位数",
            "scope_label": "有记录日",
        },
    },
    "systolic": {
        "metric_type": "blood_pressure",
        "field": "systolic",
        "band": 5.0,
        "spot_band": 12.0,
        "lexicon": {
            "subject": "收缩压",
            "reading": "记录高压",
            "unit": "mmHg",
            "up": "走高",
            "down": "走低",
            "series_label": "每日中位高压",
            "fold_note": "同日多次取中位数",
            "scope_label": "有记录日",
        },
    },
    "diastolic": {
        "metric_type": "blood_pressure",
        "field": "diastolic",
        "band": 4.0,
        "spot_band": 10.0,
        "lexicon": {
            "subject": "舒张压",
            "reading": "记录低压",
            "unit": "mmHg",
            "up": "走高",
            "down": "走低",
            "series_label": "每日中位低压",
            "fold_note": "同日多次取中位数",
            "scope_label": "有记录日",
        },
    },
    "temperature": {
        "metric_type": "temperature",
        "field": None,
        "band": 0.2,
        "spot_band": 0.5,
        "lexicon": {
            "subject": "体温",
            "reading": "记录体温",
            "unit": "℃",
            "up": "走高",
            "down": "走低",
            "series_label": "每日中位体温",
            "fold_note": "同日多次取中位数",
            "scope_label": "有记录日",
        },
    },
    "blood_oxygen": {
        "metric_type": "blood_oxygen",
        "field": None,
        "band": 1.0,
        "spot_band": 3.0,
        "lexicon": {
            "subject": "血氧",
            "reading": "记录血氧",
            "unit": "%",
            "up": "走高",
            "down": "走低",
            "series_label": "每日中位血氧",
            "fold_note": "同日多次取中位数",
            "scope_label": "有记录日",
        },
    },
}

# `register()` wants a `LEXICON` constant at import time, before any data exists,
# so one component has to be the one a caller gets when it names no component.
#
# Heart rate is that component: it is the only vital both wearables and people
# record, it is a plain scalar needing no JSON parse, and it is the least
# clinically loaded label to fall back to.  Blood sugar is excluded from the table
# entirely — fasting and postprandial readings are categorically different
# measurements that would share one axis, and it is the metric whose numbers
# readers most expect to be interpreted, which is the thing we do not do.
DEFAULT_COMPONENT = "heart_rate"

LEXICON: Mapping[str, str] = COMPONENTS[DEFAULT_COMPONENT]["lexicon"]

# The analysis key `component_for` reads an explicit pick from.  Declared here, next
# to the reader, so a host can record which component a window turned out to be
# about without a table of domain->key names living somewhere else and drifting.
COMPONENT_KEY = "vitals_component"

# Vitals states, local to this module, mapped onto the shared shapes.
SHAPE_BY_STATE: Mapping[str, str] = {
    "insufficient": "insufficient",
    "resumed_after_break": "rebuilding",
    "climbing": "sustained-rise",
    "easing": "sustained-fall",
    "spot_against_trend": "today-vs-trend-conflict",
    "level_with_swings": "flat-with-noise",
    "level": "stable",
}

# Several readings in one day — a morning cuff and a bedtime cuff — are several
# attempts at the same quantity, so the fold is a median: it resists the one bad
# reading every home device produces without picking the flattering value the way
# a min or max would.  One constant, because the Signal Frame carries one fold per
# frame and every component here folds the same way.
SERIES_FOLD = "median"

# The disclaimer template already says 诊断, so this noun covers the other half
# without the stutter 诊疗方案 would create: 「本卡不提供诊断或治疗方案。」
PRESCRIPTION_NOUN = "治疗方案"

# Stamped on the case-file folder tab, where CJK at that letter-spacing would not
# read.  Spelled out so the ornament stays stable if the domain key is renamed.
LATIN_TAG = "VITALS"


def _parse_date(raw: object) -> Optional[date]:
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _number(raw: object) -> Optional[float]:
    """A finite float, or None.  Booleans are rejected rather than counted as 1."""
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _payload(raw: object) -> Optional[Mapping[str, object]]:
    """Blood pressure as a mapping, whether it arrived parsed or as JSON text."""
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if isinstance(parsed, Mapping):
            return parsed
    return None


def lexicon_for_component(component: str = DEFAULT_COMPONENT) -> Mapping[str, str]:
    """Wording for one component, falling back to the default component's.

    Unknown names fall back rather than raise: a caller naming a component this
    module does not narrate should get a readable card about heart rate, not a
    traceback in the middle of rendering.
    """
    entry = COMPONENTS.get(str(component or ""), COMPONENTS[DEFAULT_COMPONENT])
    return entry["lexicon"]


def component_for(analysis: Mapping[str, object]) -> str:
    """Which component this analysis is about.

    An explicit `vitals_component` wins.  Otherwise it is inferred from the rows,
    because the alternative is worse than guessing: defaulting a blood-pressure
    analysis to heart rate would print 心率 and 次/分 over systolic values, a leak
    inside the domain that no cross-domain vocabulary check would catch.

    Inference prefers the component with the most readable days, and breaks ties
    by `COMPONENTS` order so the same data always lands on the same component.
    """
    if not isinstance(analysis, Mapping):
        return DEFAULT_COMPONENT
    declared = analysis.get("vitals_component")
    if isinstance(declared, str) and declared in COMPONENTS:
        return declared
    best, best_days = DEFAULT_COMPONENT, 0
    for name in COMPONENTS:
        days = len(_days(analysis, name))
        if days > best_days:
            best, best_days = name, days
    return best


def lexicon_for_analysis(analysis: Mapping[str, object]) -> Mapping[str, str]:
    """The wording table a host should pass to the renderer for this analysis."""
    return lexicon_for_component(component_for(analysis))


def _reading(item: Mapping[str, object], component: str) -> Optional[float]:
    """This component's number in one row, or None if the row has none.

    Reads the shapes vitals data actually arrives in: a `health_metrics` row
    (`metric_type` + `value`, with blood pressure as a JSON payload), the same
    number under its own key (`heart_rate`, `systolic`), and a nested `vitals`
    mapping the way a daily summary nests it.

    There is deliberately no fallback to a bare `value` without a matching
    `metric_type`: that key carries kilograms in a weight analysis and minutes in
    a sleep one, and plotting either as mmHg is exactly the cross-domain leak the
    adapter boundary exists to prevent.  For the same reason a row whose
    `metric_type` names a different metric is skipped, not read.
    """
    entry = COMPONENTS.get(component) or COMPONENTS[DEFAULT_COMPONENT]
    metric_type, field = entry["metric_type"], entry["field"]

    nested = item.get("vitals")
    if isinstance(nested, Mapping):
        found = _reading(nested, component)
        if found is not None:
            return found

    declared = item.get("metric_type")
    if isinstance(declared, str) and declared:
        if declared != metric_type:
            return None
        raw = item.get("value")
        if field:
            payload = _payload(raw)
            return _number(payload.get(field)) if payload else None
        return _number(raw)

    if field:
        payload = _payload(item.get(metric_type)) or _payload(item.get("value"))
        if payload is not None:
            found = _number(payload.get(field))
            if found is not None:
                return found
    else:
        found = _number(item.get(metric_type))
        if found is not None:
            return found
    return _number(item.get(component))


def _repeats(item: Mapping[str, object]) -> int:
    """How many raw readings this row folds in.  Defaults to one, never zero."""
    raw = item.get("measurement_count")
    if raw is None:
        raw = item.get("count")
    try:
        return max(1, int(raw or 1))
    except (TypeError, ValueError):
        return 1


def _median(values: Sequence[float]) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _days(analysis: Mapping[str, object], component: str) -> "dict[date, tuple[float, int]]":
    """Per-day median reading for one component, and how many readings folded in.

    Only this component's rows are read.  A window holding both cuff readings and
    heart rate would otherwise put two units on one axis, which is the intra-domain
    version of the leak the lexicon boundary prevents between domains.

    The mapping check guards every caller at once: `coverage_for` and `series_for`
    pass their argument through untouched, and the junk-input test hands them a bare
    string.
    """
    if not isinstance(analysis, Mapping):
        return {}
    buckets: "dict[date, list[float]]" = {}
    counts: "dict[date, int]" = {}
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        day = _parse_date(item.get("date"))
        if day is None:
            continue
        value = _reading(item, component)
        if value is None:
            continue
        repeats = _repeats(item)
        buckets.setdefault(day, []).append(value)
        counts[day] = counts.get(day, 0) + repeats
    folded: "dict[date, tuple[float, int]]" = {}
    for day, values in buckets.items():
        middle = _median(values)
        if middle is not None:
            folded[day] = (middle, max(counts.get(day, 1), len(values)))
    return folded


def _gaps(dates: Sequence[date]) -> List[int]:
    """Unrecorded days between consecutive recorded days; consecutive gives 0."""
    return [max((later - earlier).days - 1, 0) for earlier, later in zip(dates, dates[1:])]


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / float(len(values)) if values else None


# Same threshold records and sleep use: `rebuilding` is defined around this gap in
# story-design/story-system.md, not per domain.
GAP_DAYS_FOR_BREAK = 5

# The contract sets 每日型域 at ≥3 recorded days.  Vitals is one — a cuff or a
# wearable produces a reading per day — so its window is a daily series.
MIN_DAYS_FOR_TREND = 3


def state_for(analysis: Mapping[str, object]) -> str:
    """Derive this domain's state for whichever component the analysis is about.

    Reads `vitals_state` if a caller precomputed one, and deliberately not
    `state`: that key belongs to whichever domain produced the analysis, so
    honouring it would let a weight state through to be misread as a vitals one.
    """
    if not isinstance(analysis, Mapping):
        return "insufficient"
    declared = analysis.get("vitals_state")
    if isinstance(declared, str) and declared in SHAPE_BY_STATE:
        return declared

    component = component_for(analysis)
    entry = COMPONENTS[component]
    band = float(entry["band"])
    spot_band = float(entry["spot_band"])

    readings = _days(analysis, component)
    dates = sorted(readings)
    if len(dates) < 2:
        return "insufficient"

    gaps = _gaps(dates)
    # A long silence outranks any direction verdict, as in records and sleep:
    # calling the tail 走高 while ignoring the hole before it is the wrong sentence.
    if gaps and max(gaps) >= GAP_DAYS_FOR_BREAK and gaps[-1] < GAP_DAYS_FOR_BREAK:
        return "resumed_after_break"

    if len(dates) < MIN_DAYS_FOR_TREND:
        return "insufficient"

    values = [readings[day][0] for day in dates]
    middle = len(values) // 2
    early = _mean(values[:middle] or values[:1])
    late = _mean(values[middle:])
    if early is None or late is None:
        return "insufficient"

    latest = values[-1]
    overall = _mean(values) or latest
    drift = late - early
    spot_gap = latest - overall

    if drift > band:
        # A direction exists, so the only thing left to ask is whether the newest
        # reading contradicts it — that contradiction is the conflict shape.
        return "spot_against_trend" if spot_gap < -spot_band else "climbing"
    if drift < -band:
        return "spot_against_trend" if spot_gap > spot_band else "easing"

    # Halves are level, so a deviating reading is noise around a flat line rather
    # than a conflict with a direction: there is no direction to conflict with.
    if abs(spot_gap) > spot_band:
        return "level_with_swings"
    # Level halves can still hide a window that swings hard day to day, since two
    # opposite excursions average flat.  Checking the spread as well as the newest
    # reading is what keeps that window from being called 稳定.
    if (max(values) - min(values)) > spot_band * 2:
        return "level_with_swings"
    return "level"


def shape_for(analysis: Mapping[str, object]) -> str:
    """Return the shared narrative shape for a vitals analysis."""
    return SHAPE_BY_STATE.get(state_for(analysis), "insufficient")


def trend_direction(analysis: Mapping[str, object]) -> Optional[str]:
    """Neutral direction word key: 走高 / 走低 only.

    A rising number is not 超标 and a falling one is not 进步 — a fast pulse may be
    a flight of stairs, a fever, or a cold room reading.  So this returns numeric
    direction and nothing evaluative, per the neutral-direction rule in
    story-system.md, which is also why nothing here consults a reference range.
    """
    state = state_for(analysis)
    if state == "climbing":
        return "up"
    if state == "easing":
        return "down"
    if state == "insufficient":
        return None
    return "stable"


def coverage_for(analysis: Mapping[str, object]) -> dict:
    """Extract the coverage block of the Signal Frame.

    Recomputed from the readings this card can actually plot rather than taken
    from the host's `recorded_days`: a day holding only another component's
    reading is missing from this series, and counting it here would put a
    有记录日 number above a shorter plot.

    That defines the frame's coverage block, and it is what a consumer reading
    the frame gets.  It is not yet what the card prints -- today's HTML and SVG
    renderers read the host's `recorded_days` straight off the analysis
    (`render.py:385`, `:1286`, `:1288`), so on a host whose window mixes
    components, the 口径 line and the plot still disagree.  Closing that gap
    means routing the renderer through this function; until then the number here
    is the contract and the number on the card is the host's.
    """
    component = component_for(analysis)
    readings = _days(analysis, component)
    dates = sorted(readings)
    gaps = _gaps(dates)
    source = analysis if isinstance(analysis, Mapping) else {}
    window_days = int(source.get("window_days") or source.get("span_days") or 0)
    span_days = (dates[-1] - dates[0]).days + 1 if dates else 0
    denominator = window_days or span_days
    ratio = min(len(dates) / float(denominator), 1.0) if denominator else 0.0
    return {
        "recorded_days": len(dates),
        "measurement_count": sum(count for _, count in readings.values()),
        "span_days": span_days,
        "ratio": round(ratio, 3),
        "longest_gap_days": max(gaps) if gaps else 0,
        "repeat_days": sum(1 for _, count in readings.values() if count > 1),
    }


def series_for(analysis: Mapping[str, object]) -> list:
    """Return daily medians in Signal Frame form, ascending by date.

    Unrecorded days are absent rather than zero, per the analysis boundary in
    story-system.md: nobody has a heart rate of zero, and a point on the floor
    would say the reading was taken and came back empty.
    """
    component = component_for(analysis)
    readings = _days(analysis, component)
    points = []
    for day in sorted(readings):
        value, count = readings[day]
        points.append({"date": day.isoformat(), "value": round(value, 1), "count": count})
    return points
