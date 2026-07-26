"""Records adapter: the domain whose subject is the act of recording itself.

This is the cheapest possible test of the domain-neutral contract, and that is
why it comes first after weight.  It needs no new table, no new query, and no
new analysis module: every domain's analysis already carries when it was
recorded, and that is the entire raw material here.  If a story card can be
narrated from nothing but recording dates, the engine is genuinely
domain-neutral rather than weight-shaped with the labels swapped.

What it narrates is only 记录行为 itself — 连续、断档、恢复.  It never reads a
reading, so it cannot express a health judgement even accidentally: 一天记了两次
说明记得勤，不说明任何身体状况.  `up` / `down` are 变密 / 变疏, densities of
recording, per the neutral-direction rule in story-design/story-system.md.

Unlike weight, no upstream module owns this domain's analysis — there is no
`records_truth_card.py` — so the state derivation lives here.  It is gap
arithmetic over dates, small enough to keep next to the lexicon it serves.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Mapping, Optional, Sequence

DOMAIN = "records"

LEXICON: Mapping[str, str] = {
    "subject": "记录",
    "reading": "记录动作",
    "unit": "次",
    "up": "变密",
    "down": "变疏",
    "series_label": "每日记录次数",
    "fold_note": "同日多次累计",
    "scope_label": "有记录日",
}

# A gap this long is what `rebuilding` is defined around in story-system.md.
# It is the one shape written for this domain rather than adapted to it.
GAP_DAYS_FOR_BREAK = 5

# Below this the window cannot be split into halves worth comparing.  The
# contract sets 事件型域 at ≥2 recorded days; comparing densities needs one more
# than that, so the two halves are not each a single point.
MIN_DAYS_FOR_TREND = 3

# A density change smaller than this is noise in a per-day count, not a
# direction.  Counts are integers, so half a record per day is the smallest
# difference that cannot be produced by one extra entry in a short window.
DENSITY_BAND = 0.5

# Recording states, local to this domain.  They exist only to be mapped onto the
# shared shapes below; nothing outside this module should branch on them.
SHAPE_BY_STATE: Mapping[str, str] = {
    "insufficient": "insufficient",
    "resumed_after_break": "rebuilding",
    "densifying": "sustained-rise",
    "thinning": "sustained-fall",
    "today_breaks_streak": "today-vs-trend-conflict",
    "steady_with_spikes": "flat-with-noise",
    "steady": "stable",
}

# Records are events without magnitude, so a day's value *is* how many there
# were.  `count` and `sum` are arithmetically identical here — summing ones is
# counting — and `count` is the honest name for the operation, where weight's
# median was the honest name for folding a level reading.
SERIES_FOLD = "count"


def _parse_date(raw: object) -> Optional[date]:
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _dates(analysis: Mapping[str, object]) -> List[date]:
    """Ascending recorded dates, deduplicated, from any domain's analysis.

    Reads only the date field, which is the one thing every domain's
    `daily_records` is guaranteed to carry.  A point with an unparseable or
    missing date is dropped rather than guessed at: an invented date would move
    a gap boundary and could turn 断档 into 连续.
    """
    seen = set()
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        parsed = _parse_date(item.get("date"))
        if parsed is not None:
            seen.add(parsed)
    return sorted(seen)


def _gaps(dates: Sequence[date]) -> List[int]:
    """Unrecorded days between consecutive recorded days.

    Consecutive days give 0, not 1: the gap is what is missing between them.
    """
    return [max((later - earlier).days - 1, 0) for earlier, later in zip(dates, dates[1:])]


def _counts_by_date(analysis: Mapping[str, object]) -> "dict[date, int]":
    """How many raw entries each recorded day holds."""
    counts: "dict[date, int]" = {}
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        parsed = _parse_date(item.get("date"))
        if parsed is None:
            continue
        repeats = item.get("measurement_count")
        if repeats is None:
            repeats = item.get("count")
        try:
            value = int(repeats or 1)
        except (TypeError, ValueError):
            value = 1
        counts[parsed] = counts.get(parsed, 0) + max(1, value)
    return counts


def _density(dates: Sequence[date], counts: Mapping[date, int]) -> Optional[float]:
    """Records per calendar day across the span the dates cover.

    Denominator is calendar days, not recorded days, because the question this
    domain answers is how densely the window was covered.  Dividing by recorded
    days would make every window look equally dense.
    """
    if not dates:
        return None
    span = (dates[-1] - dates[0]).days + 1
    if span <= 0:
        return None
    return sum(counts.get(day, 1) for day in dates) / float(span)


def state_for(analysis: Mapping[str, object]) -> str:
    """Derive this domain's recording state.

    Reads `recording_state` if a caller precomputed one, and deliberately not
    `state`: that key belongs to whichever domain produced the analysis, so
    honouring it would let a weight state leak in and be misread as a recording
    state.
    """
    declared = analysis.get("recording_state")
    if isinstance(declared, str) and declared in SHAPE_BY_STATE:
        return declared

    dates = _dates(analysis)
    if len(dates) < 2:
        return "insufficient"

    counts = _counts_by_date(analysis)
    gaps = _gaps(dates)

    # 断档后恢复 outranks any density verdict: resuming after a long silence is
    # the more truthful thing to say about the window, and saying 变密 instead
    # would describe the tail while ignoring the hole before it.
    if gaps and max(gaps) >= GAP_DAYS_FOR_BREAK:
        tail_gap = gaps[-1]
        if tail_gap < GAP_DAYS_FOR_BREAK:
            return "resumed_after_break"

    if len(dates) < MIN_DAYS_FOR_TREND:
        return "insufficient"

    middle = len(dates) // 2
    early = _density(dates[:middle] or dates[:1], counts)
    late = _density(dates[middle:], counts)
    if early is None or late is None:
        return "insufficient"

    latest_gap = gaps[-1] if gaps else 0
    typical_gap = sorted(gaps)[len(gaps) // 2] if gaps else 0

    if late - early > DENSITY_BAND:
        return "densifying"
    if early - late > DENSITY_BAND:
        return "thinning"

    # Stable density, so the remaining question is what the newest day did.
    if latest_gap > typical_gap + 1:
        return "today_breaks_streak"
    if max(counts.values() or [1]) > 1:
        return "steady_with_spikes"
    return "steady"


def shape_for(analysis: Mapping[str, object]) -> str:
    """Return the shared narrative shape for a recording-behaviour analysis."""
    return SHAPE_BY_STATE.get(state_for(analysis), "insufficient")


def trend_direction(analysis: Mapping[str, object]) -> Optional[str]:
    """Neutral direction word key: 变密 / 变疏 only.

    Recording more is not progress and recording less is not failure — someone
    may simply have had a week without a scale nearby.  So this returns density
    direction and nothing evaluative.
    """
    state = state_for(analysis)
    if state == "densifying":
        return "up"
    if state == "thinning":
        return "down"
    if state == "insufficient":
        return None
    return "stable"


def coverage_for(analysis: Mapping[str, object]) -> dict:
    """Extract the coverage block of the Signal Frame.

    Recomputed from dates rather than read from the host analysis's
    `recorded_days`, because for this domain coverage is not metadata about the
    story — it *is* the story, and it has to agree with the series exactly.

    Within the frame, that is: today's HTML and SVG renderers read the host's
    `recorded_days` straight off the analysis (`render.py:385`, `:1286`,
    `:1288`) rather than this block, so the agreement holds for a consumer
    reading the frame and not yet for the printed card.  Closing that gap means
    routing the renderer through this function.
    """
    dates = _dates(analysis)
    counts = _counts_by_date(analysis)
    gaps = _gaps(dates)
    total = sum(counts.get(day, 1) for day in dates)
    window_days = int(analysis.get("window_days") or analysis.get("span_days") or 0)
    span_days = (dates[-1] - dates[0]).days + 1 if dates else 0
    denominator = window_days or span_days
    ratio = min(len(dates) / float(denominator), 1.0) if denominator else 0.0
    return {
        "recorded_days": len(dates),
        "measurement_count": total,
        "span_days": span_days,
        "ratio": round(ratio, 3),
        "longest_gap_days": max(gaps) if gaps else 0,
        "repeat_days": sum(1 for day in dates if counts.get(day, 1) > 1),
    }


def series_for(analysis: Mapping[str, object]) -> list:
    """Return daily record counts in Signal Frame form, ascending by date.

    `value` and `count` coincide by construction: the plotted value is the
    number of entries that day, and that number is also how many raw entries
    were folded into the point.  Unrecorded days are absent rather than zero,
    per the analysis boundary in story-system.md — a day with no record is a day
    nobody measured, not a day with nothing to measure.
    """
    counts = _counts_by_date(analysis)
    points = []
    for day in sorted(counts):
        total = counts[day]
        points.append({"date": day.isoformat(), "value": float(total), "count": total})
    return points
