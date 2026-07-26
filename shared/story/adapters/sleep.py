"""Sleep adapter: the first domain with a reading that is not a level.

Weight proved the engine can narrate a level reading; records proved it can
narrate no reading at all.  Sleep is the case in between and the one that
matters most for the domain-neutral claim: it has a real number per day, but the
number is a *duration*, so the honest words for its movement are 变长 / 变短
rather than 上浮 / 回落, and the honest fold is a mean rather than a median.  If
the same twenty-four templates read correctly with those substitutions, the
lexicon really is the only domain-specific surface.

What this module deliberately does not do is judge the sleep.  `sleep.py` owns a
quality model — `_quality_score`, `_IDEAL_TOTAL_MIN`, `_IDEAL_DEEP_RATIO` — and
none of it is read here.  A story card that said 深睡比例偏低 would be a sleep
diagnosis, which this product does not give; and 睡得久 is not 睡得好, so even
the duration is reported as a recorded number, never as a verdict.  The stage
breakdown (deep/light/rem/awake) is left on the floor for the same reason: it
exists to be interpreted, and interpreting it is the thing we refuse.

There is no `sleep_truth_card.py`, so like records this module derives its own
state.  It is halves-comparison over nightly durations, close enough to weight's
shape logic to read familiarly and small enough to keep beside the lexicon.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Mapping, Optional, Sequence

DOMAIN = "sleep"

LEXICON: Mapping[str, str] = {
    "subject": "睡眠",
    "reading": "记录时长",
    "unit": "分钟",
    "up": "变长",
    "down": "变短",
    "series_label": "每日记录时长",
    "fold_note": "同夜多次导入取平均",
    "scope_label": "有记录日",
}

# Minutes.  A night-to-night difference smaller than this is inside the slack of
# how sleep gets recorded: bedtimes get rounded to the quarter hour, wearables
# disagree with each other by about this much on the same night, and a manual
# entry is a person's estimate.  Calling a smaller difference a direction would
# be reading the recording method rather than the sleep.
LEVEL_BAND_MIN = 20.0

# Minutes.  How far the newest night has to sit from the window's own mean before
# it is worth mentioning as a single night at all.  Deliberately looser than
# LEVEL_BAND_MIN: one night differing is ordinary, and the card should not
# announce it until the difference is something the reader would have noticed.
NIGHT_BAND_MIN = 45.0

# Same threshold records uses, and for the same reason: `rebuilding` is defined
# around this gap in story-design/story-system.md, not per domain.
GAP_DAYS_FOR_BREAK = 5

# The contract sets 每日型域 at ≥3 recorded days.  Sleep is one: it produces a
# reading per night, so its window is a daily series and not an event list.
MIN_DAYS_FOR_TREND = 3

# Sleep states, local to this module.  They exist only to be mapped onto the
# shared shapes; nothing outside this file should branch on them.
SHAPE_BY_STATE: Mapping[str, str] = {
    "insufficient": "insufficient",
    "resumed_after_break": "rebuilding",
    "lengthening": "sustained-rise",
    "shortening": "sustained-fall",
    "night_against_trend": "today-vs-trend-conflict",
    "level_with_swings": "flat-with-noise",
    "level": "stable",
}

# A duration is an amount of time, and several imports of the same night are
# several attempts to measure one amount.  Summing them would invent sleep that
# did not happen; taking the longest would be picking the flattering one.  The
# mean is what the contract's fold note says, and it is also the only fold here
# that cannot overstate the night.
SERIES_FOLD = "mean"

# The disclaimer has to refuse the specific thing this domain's readers ask for.
# 助眠 covers both halves of what we will not do — no insomnia diagnosis and no
# sleep medication or therapy plan.
PRESCRIPTION_NOUN = "助眠处方"


def _parse_date(raw: object) -> Optional[date]:
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _minutes(item: Mapping[str, object]) -> Optional[float]:
    """Recorded sleep minutes for one entry, or None if this entry has none.

    Reads the keys sleep data actually arrives under: `duration_min` as
    `sleep.py` spells it, the same key nested under `sleep` as `cmd_daily`
    returns it, and `duration_min`'s looser spellings.  It pointedly does not
    fall back to a bare `value`: that key carries kilograms in a weight analysis,
    and silently plotting one as minutes is exactly the cross-domain leak the
    adapter boundary exists to prevent.

    Zero is treated as absent.  `_parse_sleep_value` coerces a missing duration
    to 0, so a 0 here means the field was empty far more often than it means
    someone recorded a night of no sleep — and 0 分钟 plotted as a point would be
    a claim about the night rather than about the record.
    """
    nested = item.get("sleep")
    if isinstance(nested, Mapping):
        found = _minutes(nested)
        if found is not None:
            return found
    for key in ("duration_min", "sleep_minutes", "duration_minutes", "duration"):
        raw = item.get(key)
        if isinstance(raw, bool) or raw is None:
            continue
        try:
            minutes = float(raw)
        except (TypeError, ValueError):
            continue
        if minutes > 0:
            return minutes
    return None


def _repeats(item: Mapping[str, object]) -> int:
    """How many raw imports this entry folds in.  Defaults to one, never zero."""
    raw = item.get("measurement_count")
    if raw is None:
        raw = item.get("count")
    try:
        return max(1, int(raw or 1))
    except (TypeError, ValueError):
        return 1


def _nights(analysis: Mapping[str, object]) -> "dict[date, tuple[float, int]]":
    """Per-night mean minutes and how many imports folded into it.

    Same-night entries are averaged as they accumulate, so the result does not
    depend on how the host happened to group them: one row carrying
    `measurement_count: 3` and three separate rows for one night both land on the
    same mean.  A night whose duration is unreadable is absent entirely — the
    scope line says 有记录日, and a night we cannot read a duration for is not a
    day this card has a reading for.
    """
    totals: "dict[date, tuple[float, int]]" = {}
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        day = _parse_date(item.get("date"))
        if day is None:
            continue
        minutes = _minutes(item)
        if minutes is None:
            continue
        repeats = _repeats(item)
        total, count = totals.get(day, (0.0, 0))
        totals[day] = (total + minutes * repeats, count + repeats)
    return {day: (total / count, count) for day, (total, count) in totals.items()}


def _gaps(dates: Sequence[date]) -> List[int]:
    """Unrecorded days between consecutive recorded nights.

    Consecutive nights give 0, not 1: the gap is what is missing between them.
    """
    return [max((later - earlier).days - 1, 0) for earlier, later in zip(dates, dates[1:])]


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / float(len(values)) if values else None


def state_for(analysis: Mapping[str, object]) -> str:
    """Derive this domain's sleep-duration state.

    Reads `sleep_state` if a caller precomputed one, and deliberately not
    `state`: that key belongs to whichever domain produced the analysis, so
    honouring it would let a weight state through to be misread as a sleep one.
    """
    declared = analysis.get("sleep_state")
    if isinstance(declared, str) and declared in SHAPE_BY_STATE:
        return declared

    nights = _nights(analysis)
    dates = sorted(nights)
    if len(dates) < 2:
        return "insufficient"

    gaps = _gaps(dates)
    # A long silence outranks any duration verdict, as in records: describing the
    # tail as 变长 while ignoring the hole before it would be the wrong sentence.
    if gaps and max(gaps) >= GAP_DAYS_FOR_BREAK and gaps[-1] < GAP_DAYS_FOR_BREAK:
        return "resumed_after_break"

    if len(dates) < MIN_DAYS_FOR_TREND:
        return "insufficient"

    minutes = [nights[day][0] for day in dates]
    middle = len(minutes) // 2
    early = _mean(minutes[:middle] or minutes[:1])
    late = _mean(minutes[middle:])
    if early is None or late is None:
        return "insufficient"

    latest = minutes[-1]
    overall = _mean(minutes) or latest
    drift = late - early
    night_gap = latest - overall

    if drift > LEVEL_BAND_MIN:
        # A trend exists, so the only thing left to check is whether the newest
        # night contradicts it.  That contradiction is the whole point of the
        # conflict shape: 今天变短，长期方向未改变.
        return "night_against_trend" if night_gap < -NIGHT_BAND_MIN else "lengthening"
    if drift < -LEVEL_BAND_MIN:
        return "night_against_trend" if night_gap > NIGHT_BAND_MIN else "shortening"

    # Halves are level, so a deviating night is noise around a flat line rather
    # than a conflict with a direction — there is no direction to conflict with.
    if abs(night_gap) > NIGHT_BAND_MIN:
        return "level_with_swings"
    # Level halves can still hide a window that swings hard night to night — a
    # 5h/9h alternation averages flat.  Checking the spread as well as the newest
    # night is what keeps that window from being called 稳定.
    if (max(minutes) - min(minutes)) > NIGHT_BAND_MIN * 2:
        return "level_with_swings"
    return "level"


def shape_for(analysis: Mapping[str, object]) -> str:
    """Return the shared narrative shape for a sleep-duration analysis."""
    return SHAPE_BY_STATE.get(state_for(analysis), "insufficient")


def trend_direction(analysis: Mapping[str, object]) -> Optional[str]:
    """Neutral direction word key: 变长 / 变短 only.

    Sleeping longer is not 进步 and sleeping less is not 失守 — a short night may
    be a newborn, a flight, or a deadline.  So this returns duration direction
    and nothing evaluative, per the neutral-direction rule in story-system.md.
    """
    state = state_for(analysis)
    if state == "lengthening":
        return "up"
    if state == "shortening":
        return "down"
    if state == "insufficient":
        return None
    return "stable"


def coverage_for(analysis: Mapping[str, object]) -> dict:
    """Extract the coverage block of the Signal Frame.

    Recomputed from the nights this card can actually read rather than taken
    from the host's `recorded_days`: a night whose duration is unreadable is
    missing from the series, and counting it here would put a 有记录日 number
    above a plot that is one point shorter.

    That defines the frame's coverage block, and it is what a consumer reading
    the frame gets.  It is not yet what the card prints -- today's HTML and SVG
    renderers read the host's `recorded_days` straight off the analysis
    (`render.py:385`, `:1286`, `:1288`), so on a host that hands over nights
    this adapter cannot read, the 口径 line and the plot still disagree.
    Closing that gap means routing the renderer through this function; until
    then the number here is the contract and the number on the card is the host's.
    """
    nights = _nights(analysis)
    dates = sorted(nights)
    gaps = _gaps(dates)
    window_days = int(analysis.get("window_days") or analysis.get("span_days") or 0)
    span_days = (dates[-1] - dates[0]).days + 1 if dates else 0
    denominator = window_days or span_days
    ratio = min(len(dates) / float(denominator), 1.0) if denominator else 0.0
    return {
        "recorded_days": len(dates),
        "measurement_count": sum(count for _, count in nights.values()),
        "span_days": span_days,
        "ratio": round(ratio, 3),
        "longest_gap_days": max(gaps) if gaps else 0,
        "repeat_days": sum(1 for _, count in nights.values() if count > 1),
    }


def series_for(analysis: Mapping[str, object]) -> list:
    """Return nightly mean durations in Signal Frame form, ascending by date.

    Unrecorded nights are absent rather than zero, per the analysis boundary in
    story-system.md: a night nobody recorded is not a night of no sleep, and a
    zero would draw a line to the floor and say so.
    """
    nights = _nights(analysis)
    points = []
    for day in sorted(nights):
        minutes, count = nights[day]
        points.append({"date": day.isoformat(), "value": round(minutes, 1), "count": count})
    return points
