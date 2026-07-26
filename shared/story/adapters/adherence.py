"""Adherence adapter: the domain that counts dose records and reads nothing else.

The domain key is `adherence` because the Signal Frame schema fixes that spelling,
but the honest name for what this narrates is 服药记录 — how densely doses were
logged, and whether logging broke off and resumed.  依从性 is a different quantity
entirely: it needs a prescribed schedule to divide by, and dividing recorded doses
by a prescribed count is the one calculation this module exists to not perform.
`health_advisor.check_medication_adherence`
(mediwise-health-tracker/scripts/health_advisor.py:337-378) does compute that ratio
and raises a `warning` when it falls under half, and its own docstring says why the
number is not what it looks like: "Trigger logs show reminder delivery activity, not
whether medication was actually taken."  This adapter reads neither side of that
comparison.

Two fields on the row are refused outright, and the refusals are the design:

`medication_name` — a drug name on a shareable card discloses a diagnosis.  So does
a count of distinct names: someone logging six medications has told you something
about themselves that six of anything else would not.  The coverage block is
schema-closed (`additionalProperties: false`), which happens to leave nowhere to put
such a count even if it were safe, and it is not.  This module therefore reads only
the date, exactly as records does.

`dose_taken` — parsing "5mg" into a magnitude is the 加量 / 减量 apparatus.  A dose
is a prescription fact, and its changes belong to whoever wrote the prescription.
Counting events sidesteps this: three doses logged is three doses logged whether each
was 5mg or 500mg.

What remains is date arithmetic identical to records', and that identity is the
point rather than a shortcut.  The subject differs, the refusals differ, and the
lexicon differs; the arithmetic does not need to.  A day with no dose record is a day
nobody wrote anything down — per the analysis boundary in
story-design/story-system.md, it is emphatically not a 漏服.  Someone may have taken
every dose and logged none of them, and the card cannot tell those apart, so it says
neither.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Mapping, Optional, Sequence

DOMAIN = "adherence"

LEXICON: Mapping[str, str] = {
    "subject": "服药记录",
    "reading": "记录剂次",
    "unit": "次",
    "up": "变密",
    "down": "变疏",
    "series_label": "每日记录剂次",
    "fold_note": "同日多剂累计",
    "scope_label": "有记录日",
}

# 变密 / 变疏 are records' direction words too, and reused here deliberately.  Both
# domains measure how densely something was written down, so a second pair of words
# for the same operation would imply a distinction that does not exist.  The
# vocabulary test handles the overlap the way it handles intake and activity both
# claiming 变多 / 变少: a word two domains own is exempt on both their cards.
#
# The disclaimer noun is 用药方案, which puts 用药 on this domain's own cards via
# `DISCLAIMER_TEMPLATE` (`render.py:40`).  That is why 用药 is one of this domain's
# own words rather than a refused one -- 「本卡不提供诊断或用药方案」 is the sentence
# that refuses it, and the sentence has to be able to say the word.
PRESCRIPTION_NOUN = "用药方案"

# Not "ADHERENCE".  The tag is ornament some layouts stamp on the card, and stamping
# the word this module spends its docstring declining to compute would undo the
# distinction in the one place a reader looks first.  MED-LOG says what the card is.
LATIN_TAG = "MED-LOG"

# No companion axis.  Naming 摄入 or 运动 beside a dose log would assert a
# relationship this domain does not read, which is what `companions_for` guards.
COMPANIONS: Sequence[str] = ()

# A gap this long is what `rebuilding` is defined around in story-system.md.  Same
# five days as records: the shape is shared, so the threshold that triggers it is too.
GAP_DAYS_FOR_BREAK = 5

# 事件型域 is ≥2 recorded days by the contract; comparing two halves needs one more
# than that so neither half is a single point.
MIN_DAYS_FOR_TREND = 3

# Half a dose record per day.  Counts are integers, so anything smaller cannot be
# produced by a real difference in a short window -- it is one extra entry showing up
# as a slope.
DENSITY_BAND = 0.5

# Recording states, local to this module.  They exist to be mapped onto the shared
# shapes; nothing outside branches on them.  Every name here describes the writing
# down, never the taking: `thinning` is 记录变疏, not 漏服变多.
SHAPE_BY_STATE: Mapping[str, str] = {
    "insufficient": "insufficient",
    "resumed_after_break": "rebuilding",
    "densifying": "sustained-rise",
    "thinning": "sustained-fall",
    "today_breaks_streak": "today-vs-trend-conflict",
    "steady_with_spikes": "flat-with-noise",
    "steady": "stable",
}

# Doses are events without magnitude — deliberately, since the magnitude is on
# `dose_taken` and refused above — so a day's value is how many were logged.
SERIES_FOLD = "count"


def _parse_date(raw: object) -> Optional[date]:
    return _parse_iso(str(raw)[:10]) if raw is not None else None


def _parse_iso(text: str) -> Optional[date]:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _row_date(item: Mapping[str, object]) -> Optional[date]:
    """The day a row belongs to, from `date` or from `taken_at`.

    `medication_logs` stores `taken_at` as a timestamp and has no `date` column
    (`health_db.py:626-638`), so a host handing rows over unchanged supplies the
    second spelling.  Both are truncated to ten characters, which takes the calendar
    day off either shape and discards the clock time — and discarding it is
    intentional: what time of day doses were logged is the raw material for 按时服药,
    and this module has no state that could consume it.
    """
    for key in ("date", "taken_at"):
        if key in item:
            parsed = _parse_date(item.get(key))
            if parsed is not None:
                return parsed
    return None


def _dates(analysis: Mapping[str, object]) -> List[date]:
    """Ascending recorded dates, deduplicated.

    A row whose date will not parse is dropped rather than guessed at: an invented
    date moves a gap boundary, and a moved boundary can turn 断档 into 连续.
    """
    seen = set()
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        parsed = _row_date(item)
        if parsed is not None:
            seen.add(parsed)
    return sorted(seen)


def _gaps(dates: Sequence[date]) -> List[int]:
    """Unrecorded days between consecutive recorded days.

    Consecutive days give 0, not 1 — the gap is what is missing between them.  These
    are days without a record, and the module never calls them anything else.
    """
    return [max((later - earlier).days - 1, 0) for earlier, later in zip(dates, dates[1:])]


def _counts_by_date(analysis: Mapping[str, object]) -> "dict[date, int]":
    """How many dose records each day holds.

    `measurement_count` first, then `count`, then one.  Unlike activity — where
    `count` is the steps field and honouring it would read 6200 步 as 6200 syncs —
    nothing on this domain's rows contests the name, so the fallback other adapters
    accept is safe here.  A row declaring three doses and three separate rows for the
    same day both land on 3.
    """
    counts: "dict[date, int]" = {}
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        parsed = _row_date(item)
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
    """Dose records per calendar day across the span the dates cover.

    Calendar days in the denominator, not recorded days: dividing by recorded days
    would make every window equally dense and erase the only thing this domain reads.
    The denominator is the span the records themselves cover — never a prescribed
    schedule, which is the divisor that would turn this into 依从率.
    """
    if not dates:
        return None
    span = (dates[-1] - dates[0]).days + 1
    if span <= 0:
        return None
    return sum(counts.get(day, 1) for day in dates) / float(span)


def state_for(analysis: Mapping[str, object]) -> str:
    """Derive this domain's recording state.

    Reads `adherence_state` if a caller precomputed one, and deliberately not
    `state`: that key belongs to whichever domain produced the analysis, so honouring
    it would let another domain's state through to be misread as a dose-record state.
    """
    declared = analysis.get("adherence_state")
    if isinstance(declared, str) and declared in SHAPE_BY_STATE:
        return declared

    dates = _dates(analysis)
    if len(dates) < 2:
        return "insufficient"

    counts = _counts_by_date(analysis)
    gaps = _gaps(dates)

    # 断档后恢复 outranks any density verdict.  Resuming after a silence is the more
    # truthful thing to say about the window; 变密 would describe the tail and say
    # nothing about the hole before it.
    if gaps and max(gaps) >= GAP_DAYS_FOR_BREAK:
        if gaps[-1] < GAP_DAYS_FOR_BREAK:
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

    if latest_gap > typical_gap + 1:
        return "today_breaks_streak"
    if max(counts.values() or [1]) > 1:
        return "steady_with_spikes"
    return "steady"


def shape_for(analysis: Mapping[str, object]) -> str:
    """Return the shared narrative shape for a dose-record analysis."""
    return SHAPE_BY_STATE.get(state_for(analysis), "insufficient")


def trend_direction(analysis: Mapping[str, object]) -> Optional[str]:
    """Neutral direction word key: 变密 / 变疏 only.

    Logging more doses is not 依从性提高 and logging fewer is not 漏服 — a week away
    from home is a week of thinner records and says nothing about what was swallowed.
    So this returns density direction and nothing evaluative, per story-system.md:43.
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

    Recomputed from dates rather than read off the host's `recorded_days`, because
    here coverage is not metadata about the story — it is the story, and it has to
    agree with the series exactly.

    Within the frame, that is: today's HTML and SVG renderers read the host's
    `recorded_days` straight off the analysis (`render.py:385`, `:1286`, `:1288`)
    rather than this block, so the agreement holds for a consumer reading the frame
    and not yet for the printed card.  Closing that gap means routing the renderer
    through this function.

    `longest_gap_days` is the run of days with no dose record.  It is a coverage
    number and stays one: nothing downstream may present it as a treatment
    interruption, which is a clinical event this data cannot witness.
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
    """Return daily dose-record counts in Signal Frame form, ascending by date.

    `value` and `count` coincide by construction: the plotted value is how many dose
    records that day held, and that number is also how many raw rows folded into the
    point.  Unrecorded days are absent rather than zero — a zero here would draw a
    day of no doses taken, which is precisely the claim the data cannot support.
    """
    counts = _counts_by_date(analysis)
    points = []
    for day in sorted(counts):
        total = counts[day]
        points.append({"date": day.isoformat(), "value": float(total), "count": total})
    return points
