"""Weight adapter: the first domain wired into the shared narrative engine.

Weight is a case study, not the subject of the system.  This module holds
everything the renderer must not know: the word 体重, the unit kg, and the eight
weight-specific analysis states.  The renderer only ever sees `LEXICON` wording
and a shared `shape`.

It deliberately does not re-implement analysis.  `weight_truth_card.py` keeps
owning same-day median folding and the Theil-Sen fit; this adapter translates
that result into the domain-neutral vocabulary.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Mapping, Optional

DOMAIN = "weight"

LEXICON: Mapping[str, str] = {
    "subject": "体重",
    "reading": "秤面",
    "unit": "kg",
    "up": "上浮",
    "down": "回落",
    "series_label": "每日中位数",
    "fold_note": "同日多次取中位数",
    "scope_label": "有记录日",
}

# Maps the eight weight analysis states onto the nine shared shapes declared in
# story-design/story-system.md.  Copy is keyed on the shape, never on these.
SHAPE_BY_STATE: Mapping[str, str] = {
    "insufficient": "insufficient",
    "daily_up_trend_down": "today-vs-trend-conflict",
    "daily_down_trend_up": "today-vs-trend-conflict",
    "sustained_up": "sustained-rise",
    "sustained_down": "sustained-fall",
    "daily_up_stable": "flat-with-noise",
    "daily_down_stable": "flat-with-noise",
    "stable": "stable",
}

# Same-day duplicates fold to a median: weight is a level reading, so summing or
# taking the best-looking value would both be wrong.
SERIES_FOLD = "median"

# Narrower than the default 处理方案, because this is the domain where users most
# expect a prescription and the disclaimer has to refuse the specific thing.
PRESCRIPTION_NOUN = "减重处方"

# Stamped on the case-file folder tab, where CJK at that letter-spacing would not
# read.  Matches the domain key, and is spelled out so the ornament stays stable if
# the key is ever renamed.
LATIN_TAG = "WEIGHT"

# Weight is the one domain whose companion axis is fixed and known — the lifestyle
# databases hold intake, activity and sleep, and a weight card with none of them is
# specifically missing those three.  So it may name them where the neutral default
# cannot.  This also pins the string the golden digests were taken against: the
# generalised default is a change of wording, and weight's output is not supposed to
# move when the mechanism underneath it does.
NO_COMPANION_COPY = {
    "headline": "{subject}之外的同期记录还在积累",
    "paragraph": "目前主要有{subject}记录；摄入、运动与睡眠数据不足，因此这张卡不把单一数字解释成原因。",
}

# The companion axis the copy above is allowed to name, and the reason it may: these
# three are what `lifestyle.db` actually holds, so a weight card missing them is
# missing something specific and "睡眠记录 0 天" tells the reader what to record next.
# A domain that declares nothing here gets own-subject wording on the same templates
# instead — see `companions_for`.
COMPANIONS = ("intake", "activity", "sleep")


def shape_for(analysis: Mapping[str, object]) -> str:
    """Return the shared narrative shape for a weight analysis result."""
    state = str(analysis.get("state") or "insufficient")
    shape = SHAPE_BY_STATE.get(state)
    if shape:
        return shape
    if not analysis.get("trend_claim_allowed"):
        return "insufficient"
    return "stable"


def trend_direction(analysis: Mapping[str, object]) -> Optional[str]:
    """Neutral direction word key.  Never success, failure, progress, or 达标."""
    state = str(analysis.get("state") or "")
    if state in ("sustained_up",):
        return "up"
    if state in ("sustained_down",):
        return "down"
    if state in ("stable", "daily_up_stable", "daily_down_stable"):
        return "stable"
    delta = analysis.get("trend_delta")
    if not isinstance(delta, (int, float)):
        return None
    if delta > 0.2:
        return "up"
    if delta < -0.2:
        return "down"
    return "stable"


def _parse_date(value: str) -> Optional[date]:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _repeats(item: Mapping[str, object]) -> int:
    """Per-day raw measurement count, tolerant of a producer that omits or fumbles it.

    `weight_truth_card.aggregate_daily_medians` spells it `measurement_count`; the
    Signal Frame spells the same number `count`, so a frame-shaped point handed
    straight in also reads correctly.
    """
    raw = item.get("measurement_count")
    if raw is None:
        raw = item.get("count")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def _day_counts(analysis: Mapping[str, object]) -> dict:
    """Recorded day -> raw measurements on it, read straight off `daily_records`."""
    counts = {}
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        day = str(item.get("date") or "")[:10]
        # Parsed, not just length-checked: an unparseable date cannot take part in
        # the gap arithmetic below, and inventing one could turn 断档 into 连续.
        if _parse_date(day) is None:
            continue
        counts[day] = counts.get(day, 0) + _repeats(item)
    return counts


def coverage_for(analysis: Mapping[str, object]) -> dict:
    """Extract the coverage block of the Signal Frame.

    `recorded_days` and `measurement_count` are taken from the analysis when it
    declares them, since `weight_truth_card` is the authority on its own window,
    and derived from `daily_records` otherwise.

    `repeat_days` is counted from the daily records rather than as
    `measurement_count - recorded_days`.  The schema defines it as days holding
    more than one raw measurement; the subtraction yields extra measurements,
    which is a different number the moment any single day holds three.
    """
    day_counts = _day_counts(analysis)
    recorded_days = int(analysis.get("recorded_days") or 0) or len(day_counts)
    measurement_count = int(analysis.get("measurement_count") or 0) or sum(day_counts.values())
    dates = sorted(day_counts)
    gaps = [
        max((_parse_date(later) - _parse_date(earlier)).days - 1, 0)
        for earlier, later in zip(dates, dates[1:])
    ]
    return {
        "recorded_days": recorded_days,
        "measurement_count": measurement_count,
        "span_days": int(analysis.get("span_days") or 0),
        "ratio": float(analysis.get("coverage_ratio") or 0.0),
        "longest_gap_days": max(gaps) if gaps else 0,
        "repeat_days": sum(1 for count in day_counts.values() if count > 1),
    }


def series_for(analysis: Mapping[str, object]) -> list:
    """Return folded daily points in Signal Frame form, ascending by date.

    The per-day repeat count lives under `measurement_count` in what
    `weight_truth_card.aggregate_daily_medians` produces; `count` is accepted as a
    fallback because that is the Signal Frame's own spelling and a future
    producer may hand us a frame-shaped point directly.  Reading only `count`
    silently pinned every point to 1 and discarded the repeat-day signal the
    schema reserves for the double-exposure moment.
    """
    points = []
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        value = item.get("weight")
        if not isinstance(value, (int, float)):
            continue
        points.append(
            {
                "date": str(item.get("date") or "")[:10],
                "value": float(value),
                "count": _repeats(item),
            }
        )
    points.sort(key=lambda point: point["date"])
    return points
