"""Activity adapter: the first domain whose numbers are counted by hardware.

Every other domain's record is entered by a person or derived from one reading.  Steps
are tallied by a device, and two devices tallying the same walk disagree — a phone in a
pocket and a watch on a wrist do not count the same day the same way.  That is this
domain's distinctive honesty problem:

    换了一只表，和多走了两千步，在数据里长得一模一样。

`sync.py:86-94` makes it concrete.  Its duplicate key is
`(member_id, metric_type, measured_at, source)`, so `source` is part of what makes a row
unique, and a phone's day and a watch's day both survive insertion even though
`_aggregate_daily_steps` stamps every same-day steps row with the same `23:59:00`.  A
window that changed device mid-way therefore holds two hardware's counts side by side,
and comparing its halves measures the swap.  `_source_changed` below is the gate that
refuses that comparison, placed before any direction and before 稳定 too.  It is to this
domain what the 断档 check is to the others: the structural reason a true sentence gets
printed where a plausible one would have fit.

What this module refuses to read is the expenditure apparatus the rest of the suite owns.
`calculate_tdee(bmr, activity_level)` at `mediwise-health-tracker/scripts/metric_utils.py`
:132-149 sorts a person into sedentary / light / moderate / active / very_active and
multiplies out a daily burn; Garmin reports its own `aerobic_te` training-effect score at
`wearable-sync/scripts/providers/garmin.py:697`.  Both answer 「练够了吗」, and answering
it on a story card is exercise prescription.  A card here may say 「这天记录了 8200 步」
and may never say 达标, 消耗不足, or 久坐.  The bands below are device noise in each
component's own unit — the smallest difference a day's counting can express — and are
nothing else.

Per-workout rows (`metric_type: "activity"`, from `garmin.py:672`) are out of scope for
this cut.  They are event rows that stack within a day, so they want a `sum` fold, and a
sum cannot coexist with the `last` fold the daily step rows need under one frame-level
`SERIES_FOLD`.  That is the same categorical mismatch that kept blood sugar out of vitals
(`vitals.py:136-139`): one domain, one fold, so the readings that fold differently wait
for their own entry rather than being averaged into nonsense.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import List, Mapping, Optional, Sequence

DOMAIN = "activity"

# Each component names the field it reads inside a steps payload, and carries its own
# noise bands.  `band` is how far the window's two halves may sit apart before the
# difference is worth a direction; `spot_band` is how far one day may sit from the trend
# before it is worth remarking on.  Both are device counting noise in the component's own
# unit.  Neither is a target, a quota, or a recommended amount — nothing in this module
# knows what a person should do, only what their device recorded.
COMPONENTS: Mapping[str, Mapping[str, object]] = {
    "steps": {
        "metric_type": "steps",
        "field": "count",
        # 800 steps is a few minutes of walking: the difference between parking closer
        # and parking further, which is not a change in how someone moves.
        "band": 800.0,
        "spot_band": 2500.0,
        "lexicon": {
            "subject": "步数",
            "reading": "记录步数",
            # The host's own label for this metric: `METRIC_UNITS["steps"] = "步"`.
            "unit": "步",
            "up": "变多",
            "down": "变少",
            "series_label": "每日记录步数",
            "fold_note": "同日多次同步取最新",
            "scope_label": "有记录日",
        },
    },
    "distance": {
        "metric_type": "steps",
        "field": "distance_m",
        # 600 m is roughly the 800-step band walked, kept in step with it so the two
        # components do not disagree about whether the same day moved.
        "band": 600.0,
        "spot_band": 1900.0,
        "lexicon": {
            "subject": "记录距离",
            "reading": "记录距离",
            "unit": "米",
            "up": "变多",
            "down": "变少",
            "series_label": "每日记录距离",
            "fold_note": "同日多次同步取最新",
            "scope_label": "有记录日",
        },
    },
}

DEFAULT_COMPONENT = "steps"
LEXICON: Mapping[str, str] = COMPONENTS[DEFAULT_COMPONENT]["lexicon"]  # type: ignore[assignment]

# The analysis key `component_for` reads an explicit pick from.  It reads two more
# aliases (`metric`, `metric_type`) because activity rows arrive carrying a provider's
# own field name, but this is the one a host should write.
COMPONENT_KEY = "component"

# The day is already a day when it arrives: `_aggregate_daily_steps` folds intraday
# samples into one row per date, and the providers that report a finished total send one
# row to begin with.  So a second row for the same date is a re-sync of that same day,
# not a second attempt at it.
#
# That rules out the other folds rather than merely preferring this one.  `sum` would
# double-count a re-sync into a day nobody walked.  `median` and `mean` would average a
# corrected figure with the figure it corrected, landing between two numbers of which one
# is simply wrong.  `last` keeps the newest sync, which is the right reading of a device
# correction.
#
# It resolves by row order, because same-day rows share the `23:59:00` stamp
# (`normalize.py:108`) and carry no finer time to sort by.  For a host handing rows over
# in insertion order that is the newest sync, which is what makes the choice correct
# rather than arbitrary.
SERIES_FOLD = "last"

PRESCRIPTION_NOUN = "运动方案"

# Stamped on the case-file folder tab, where CJK at that letter-spacing would not read.
LATIN_TAG = "ACTIVITY"

# Activity reads no other domain.  A card here reports what a device counted and nothing
# else; the cross-domain reading of 运动 alongside 体重 stays on weight's cards, where the
# companion axis is declared (`weight.py:73`).
COMPANIONS: Sequence[str] = ()

SHAPE_BY_STATE: Mapping[str, str] = {
    "insufficient": "insufficient",
    # The device changed, so the counting changed.  Same shape as too-few-days, because
    # the honest report is the same: not enough comparable record to call a direction.
    "source_changed": "insufficient",
    "resumed_after_break": "rebuilding",
    "rising": "sustained-rise",
    "falling": "sustained-fall",
    "spot_against_trend": "today-vs-trend-conflict",
    "level_with_swings": "flat-with-noise",
    "level": "stable",
}

GAP_DAYS_FOR_BREAK = 5
MIN_DAYS_FOR_TREND = 3

# Share of a half's days that must come from one device for that half to be attributed to
# it.  Below this the half is mixed and no swap can be claimed either way, so the gate stays
# quiet rather than firing on a window that was always mixed.
#
# Three quarters rather than a bare majority, because a bare majority is reachable by a
# window that never swapped anything.  Someone who wears a watch and carries a phone syncs
# both, and whichever happens to win a given day alternates; over three days that lands at
# 2/3 for each half with opposite winners, which a 0.6 gate reads as a swap and silences a
# window with nothing wrong with it.  0.75 is above every period-2 alternation's ceiling, so
# a half only gets attributed to a device that genuinely dominated it.
SOURCE_MAJORITY = 0.75


def _row_date(item: Mapping[str, object]) -> Optional[date]:
    """Read a row's date from either the table column or the summary key.

    `health_metrics` stores `measured_at` as a timestamp; the analysis dicts the report
    layer assembles carry a plain `date`.  Reading both is what lets one adapter serve
    the table and the summary without a translation step between.
    """
    raw = item.get("date") or item.get("measured_at") or item.get("recorded_at")
    if isinstance(raw, date):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:len(fmt) + 2].strip(), fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None


def _number(value: object) -> Optional[float]:
    """Coerce a reading to float, or None when it is not a number.

    None rather than 0.0, so a field nobody reported drops out of the series instead of
    landing on the floor as a day of no movement.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _payload(item: Mapping[str, object]) -> Mapping[str, object]:
    """Read the row's JSON body, whether it arrives parsed or as text."""
    raw = item.get("value")
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, str) and raw.strip().startswith("{"):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
        if isinstance(parsed, Mapping):
            return parsed
    return {}


def _component_value(item: Mapping[str, object], component: str) -> Optional[float]:
    """One component's reading on one row, or None when the row does not carry it.

    A steps payload only holds what its provider measured.  `normalize.py` now omits
    `distance_m` when a provider never reported it, but rows written before that carry a
    hard `distance_m: 0` from the old aggregator, and `garmin.py:429` still fills an
    absent distance with 0 at the source.

    So a zero distance is read as 「这台设备没报距离」 rather than as a measurement.  On a
    day with steps recorded it is not a day of walking nowhere, and plotting it as one
    would put a floor point under a day that had thousands of steps in it.  Steps
    themselves are read as they stand: a recorded day of very few steps is a real day,
    and rewriting that would be the opposite mistake.
    """
    spec = COMPONENTS.get(component) or COMPONENTS[DEFAULT_COMPONENT]
    wanted = spec.get("metric_type")
    kind = item.get("metric_type")
    if isinstance(kind, str) and kind and wanted and kind != wanted:
        return None
    field = str(spec.get("field") or "")
    value = _number(_payload(item).get(field))
    if value is None:
        value = _number(item.get(field))
    if value is None:
        return None
    if field != "count" and value == 0:
        return None
    return value


def _source(item: Mapping[str, object]) -> str:
    """Which device reported this row, or "" when nothing says.

    Hand-entered rows and test fixtures carry no source, and an empty string keeps them
    out of the swap gate entirely rather than grouping them together as one pseudo-device.
    """
    raw = item.get("source") or item.get("provider")
    return raw.strip() if isinstance(raw, str) else ""


def _repeats(item: Mapping[str, object]) -> int:
    """How many syncs this row folds in.  Defaults to one, never zero.

    Reads `measurement_count` and deliberately not `count`, which every other adapter
    accepts as a fallback spelling.  Here `count` is the steps field itself, so honouring
    it would read 6200 步 as 6200 syncs of one day.  A host that pre-aggregates activity
    days has to say `measurement_count`; nothing else is unambiguous on this domain's rows.
    """
    raw = item.get("measurement_count")
    try:
        return max(1, int(raw or 1))
    except (TypeError, ValueError):
        return 1


def _days(analysis: Mapping[str, object], component: str) -> "dict[date, tuple[float, int, str]]":
    """Per-day reading for one component, plus its sync count and reporting device.

    The reading is the last row for that date, per `SERIES_FOLD`. The count is how many
    syncs resolved to it, which is what the 同日多次同步取最新 note refers to. The source
    is the device the winning row came from, which is what `_source_changed` compares.

    Counting adds each row's own `measurement_count` rather than incrementing by one, so
    the total does not depend on how the host grouped its rows: three separate sync rows
    for a day and one pre-aggregated row declaring three syncs both report 3.  `sync.py`
    writes the first shape and a `weight_truth_card`-style host produces the second.

    The mapping check guards every caller at once, since `coverage_for` and `series_for`
    pass their argument straight through and the junk-input test hands them a bare string.
    """
    if not isinstance(analysis, Mapping):
        return {}
    readings: "dict[date, tuple[float, int, str]]" = {}
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        day = _row_date(item)
        if day is None:
            continue
        value = _component_value(item, component)
        if value is None:
            continue
        seen = readings[day][1] if day in readings else 0
        readings[day] = (value, seen + _repeats(item), _source(item))
    return readings


def _gaps(dates: Sequence[date]) -> List[int]:
    """Unrecorded days between consecutive recorded days; consecutive gives 0."""
    return [max((later - earlier).days - 1, 0) for earlier, later in zip(dates, dates[1:])]


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / float(len(values)) if values else None


def lexicon_for_component(component: str = DEFAULT_COMPONENT) -> Mapping[str, str]:
    """Wording for one component, falling back to the default component's.

    Falling back rather than raising: an unknown component name is a caller's bug, and a
    card labelled 步数 is a better failure than a traceback in a rendering path.
    """
    spec = COMPONENTS.get(component) or COMPONENTS[DEFAULT_COMPONENT]
    return spec["lexicon"]  # type: ignore[return-value]


def component_for(analysis: Mapping[str, object]) -> str:
    """Which component this window is about.

    An explicit `component` / `metric` key wins.  Otherwise steps, which every provider
    reports; distance only arrives from the one that measures it.
    """
    if not isinstance(analysis, Mapping):
        return DEFAULT_COMPONENT
    for key in ("component", "metric", "metric_type"):
        raw = analysis.get(key)
        if isinstance(raw, str) and raw.strip() in COMPONENTS:
            return raw.strip()
    return DEFAULT_COMPONENT


def lexicon_for_analysis(analysis: Mapping[str, object]) -> Mapping[str, str]:
    """Wording for whichever component this window turned out to be about."""
    return lexicon_for_component(component_for(analysis))


def _halves(dates: Sequence[date]) -> "tuple[Sequence[date], Sequence[date]]":
    """Split recorded days into an earlier and a later half.

    One split shared by the swap gate and the direction check, so the two can never
    disagree about which days they are comparing.
    """
    middle = len(dates) // 2
    return dates[:middle] or dates[:1], dates[middle:]


def _dominant_source(readings, dates: Sequence[date]) -> str:
    """The device that reported most of these days, or "" when none has a majority.

    Below `SOURCE_MAJORITY` the half is mixed, and "" makes the caller treat it as
    unattributable rather than picking a winner from a tie.
    """
    counts: "dict[str, int]" = {}
    for day in dates:
        name = readings[day][2]
        if name:
            counts[name] = counts.get(name, 0) + 1
    if not counts:
        return ""
    winner = max(sorted(counts), key=lambda name: counts[name])
    return winner if counts[winner] >= len(dates) * SOURCE_MAJORITY else ""


def _source_changed(readings, dates: Sequence[date]) -> bool:
    """Whether the window's halves were counted by different devices.

    This is the gate that makes an activity card honest.  Counts are only comparable
    across halves the same hardware produced: a wrist counts a day of dishwashing as steps
    that a pocket never sees, and a phone left on a desk misses a walk the watch records.
    When the device is what changed, the truthful report is that the counting changed, not
    that the walking did.

    False when nothing carries a source, so hand-entered rows and fixtures are unaffected;
    false too when either half is mixed, since a window that was always mixed had no swap.
    """
    early, late = _halves(dates)
    first = _dominant_source(readings, early)
    second = _dominant_source(readings, late)
    if not first or not second:
        return False
    return first != second


def state_for(analysis: Mapping[str, object]) -> str:
    """Derive this domain's state for whichever component the analysis is about.

    Reads `activity_state` if a caller precomputed one, and deliberately not `state`:
    that key belongs to whichever domain produced the analysis, so honouring it would
    let a weight state through to be misread as an activity one.
    """
    if not isinstance(analysis, Mapping):
        return "insufficient"
    declared = analysis.get("activity_state")
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
    # A long silence outranks any direction verdict, as in every other domain.
    if gaps and max(gaps) >= GAP_DAYS_FOR_BREAK and gaps[-1] < GAP_DAYS_FOR_BREAK:
        return "resumed_after_break"

    if len(dates) < MIN_DAYS_FOR_TREND:
        return "insufficient"

    # Before any direction, and before 稳定 too: halves counted by different hardware
    # give no comparable pair, so flat counts across a swap are as unearned as rising
    # ones.  A watch that counts more generously than the phone it replaced can hold a
    # falling week level, and calling that 稳定 would credit the device's arithmetic to
    # the person wearing it.
    if _source_changed(readings, dates):
        return "source_changed"

    values = [readings[day][0] for day in dates]
    early, late_dates = _halves(dates)
    first = _mean([readings[day][0] for day in early])
    second = _mean([readings[day][0] for day in late_dates])
    if first is None or second is None:
        return "insufficient"

    latest = values[-1]
    overall = _mean(values) or latest
    drift = second - first
    spot_gap = latest - overall

    if drift > band:
        # A direction exists, so the only thing left to ask is whether the newest day
        # contradicts it — that contradiction is the conflict shape.
        return "spot_against_trend" if spot_gap < -spot_band else "rising"
    if drift < -band:
        return "spot_against_trend" if spot_gap > spot_band else "falling"

    # Halves are level, so a deviating day is noise around a flat line rather than a
    # conflict with a direction: there is no direction to conflict with.
    if abs(spot_gap) > spot_band:
        return "level_with_swings"
    # Level halves still hide a window that swings hard day to day, since one long hike
    # and one day indoors average out flat.  Checking the spread is what keeps that
    # window from being called 稳定.
    if (max(values) - min(values)) > spot_band * 2:
        return "level_with_swings"
    return "level"


def shape_for(analysis: Mapping[str, object]) -> str:
    """Return the shared narrative shape for an activity analysis."""
    return SHAPE_BY_STATE.get(state_for(analysis), "insufficient")


def trend_direction(analysis: Mapping[str, object]) -> Optional[str]:
    """Neutral direction word key: 变多 / 变少 only.

    More steps is not 达标 and fewer is not 久坐 — a 3000 步 day may be a desk day, a
    rest day between two long runs, or a day the watch spent on a charger.  So this
    returns numeric direction and nothing evaluative, per the neutral-direction rule in
    story-system.md, which is also why nothing here consults a TDEE activity level or a
    vendor training score.

    `source_changed` returns None with `insufficient`: both mean the window cannot
    support a direction, and the caller asking for one deserves the same answer.
    """
    state = state_for(analysis)
    if state == "rising":
        return "up"
    if state == "falling":
        return "down"
    if state in ("insufficient", "source_changed"):
        return None
    return "stable"


def coverage_for(analysis: Mapping[str, object]) -> dict:
    """Extract the coverage block of the Signal Frame.

    Recomputed from the days this card can actually plot rather than taken from the
    host's `recorded_days`: a day whose only row carried an unreadable count is missing
    from the series, and counting it here would put a 有记录日 number above a shorter
    plot.

    `measurement_count` is sync rows, not days — the number the 同日多次同步取最新 note
    refers to.  Unlike intake's meal rows it does not make a day denser: three syncs of
    one day are three tellings of it, which is why `SERIES_FOLD` keeps only the last.

    The recomputation defines the frame's coverage block, and it is what a consumer
    reading the frame gets.  It is not yet what the card prints -- today's HTML and SVG
    renderers read the host's `recorded_days` straight off the analysis (`render.py:385`,
    `:1286`, `:1288`).  Closing that gap means routing the renderer through this
    function; until then the number here is the contract and the number on the card is
    the host's.
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
        "measurement_count": sum(count for _, count, _ in readings.values()),
        "span_days": span_days,
        "ratio": round(ratio, 3),
        "longest_gap_days": max(gaps) if gaps else 0,
        "repeat_days": sum(1 for _, count, _ in readings.values() if count > 1),
    }


def series_for(analysis: Mapping[str, object]) -> list:
    """Return daily readings in Signal Frame form, ascending by date.

    Unrecorded days are absent rather than zero, per the analysis boundary in
    story-system.md.  A point on the floor would read as a day of sitting still, when
    all it means is that the device was not worn.
    """
    component = component_for(analysis)
    readings = _days(analysis, component)
    points = []
    for day in sorted(readings):
        value, count, _ = readings[day]
        points.append({"date": day.isoformat(), "value": round(value, 1), "count": count})
    return points
