"""Family adapter: how many people in the household wrote something down.

Every other domain aggregates one person's readings across days.  This one
aggregates *across people* — the fold is over 家人, and the day's value is how
many of them had any record written at all.  That makes it the last structural
shape the engine had not been asked to narrate, and the reason it comes last:
it is also the only domain where the raw material is mostly identity, and
identity is the one thing a shareable card may not carry.

So this module refuses more than it reads.  `family_overview`
(mediwise-health-tracker/scripts/query.py:484-534) returns, per member, a
`name`, a `relation`, a `gender`, a `birth_date`, `allergies`, `total_visits`,
`active_medications`, and the `hospital` and `diagnosis` of the last visit.
A story card may read none of it.  Not the name — a card that says who is on it
has published a household roster.  Not the diagnosis or the allergies — those
are the disclosure this whole suite is built to avoid.  Not `total_visits` or
`active_medications` either, because a per-member count is a comparison waiting
to be drawn, and 谁的记录最少 is the sentence this domain exists to not write.

What is left is a `member_id` and a date, and it turns out to be enough: 这一段
里，每天有几位家人写下了记录.  That is a real story with a real shape — 一个人在
记，慢慢变成一家人在记 — and it needs no identity to tell.  `up` / `down` are
变多 / 变少, breadth of participation, neutral in the direction sense
story-design/story-system.md requires.

The other refusal is arithmetic rather than lexical.  The obvious framing of
this domain is a fraction: 3 位家人里有 1 位记录了.  That denominator is a
statement about the two people who did not, printed on a card they may not have
consented to appear on, and it is why coverage here counts recorded days like
every other domain rather than members.  Nothing in this module divides by how
many people exist.

Like records and adherence, no upstream module owns this analysis, so the state
derivation lives here.  It is set arithmetic over member ids per day.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Mapping, Optional, Sequence, Set

DOMAIN = "family"

LEXICON: Mapping[str, str] = {
    "subject": "家庭记录",
    "reading": "记录人数",
    "unit": "人",
    "up": "变多",
    "down": "变少",
    "series_label": "每日记录人数",
    "fold_note": "同一人同日只计一次",
    "scope_label": "有记录日",
}

# 「本卡不提供诊断或照护方案」 is the sentence that refuses this domain's most
# tempting output, and the sentence has to be able to say the word — which is
# why 照护 is declared as vocabulary this domain owns rather than vocabulary it
# forbids.  A forbidden word is checked without regard for the 不提供 in front
# of it, so refusing it here would flag the refusal.
PRESCRIPTION_NOUN = "照护方案"

# Not "FAMILY".  The engine has used `family` for its own template families
# since long before this domain existed — catalog.py:84, the 12×2 invariant at
# catalog.py:194, FAMILY_RENDERERS, and an ASCII CSS class `.family-weather` at
# render.py:1371 — and letting the default tag fall out of the domain name would
# stamp that word on the card in a third, unrelated sense.  HOUSEHOLD says what
# the card is and collides with nothing.
LATIN_TAG = "HOUSEHOLD"

# No companion axis.  A companion sentence asserts that two signals moved in the
# same stretch of time; pairing 家庭记录 with 摄入 or 运动 would quietly relocate
# one member's readings under a household heading, which is the identity leak
# this module is built around.
COMPANIONS: Sequence[str] = ()

# A five-day silence is what `rebuilding` is defined around in story-system.md.
# Households go quiet for ordinary reasons, so this is deliberately the same
# threshold the records domain uses rather than a tighter one.
GAP_DAYS_FOR_BREAK = 5

# Two recorded days is the 事件型域 floor in the contract; comparing two halves
# needs one more, so neither half is a single day.
MIN_DAYS_FOR_TREND = 3

# Head counts are integers, so half a person per day is the smallest change that
# one extra row cannot manufacture in a short window.
BREADTH_BAND = 0.5

# Household states, local to this domain, mapped onto the shared shapes.
SHAPE_BY_STATE: Mapping[str, str] = {
    "insufficient": "insufficient",
    "resumed_after_break": "rebuilding",
    "widening": "sustained-rise",
    "narrowing": "sustained-fall",
    "today_breaks_streak": "today-vs-trend-conflict",
    "uneven_participation": "flat-with-noise",
    "steady": "stable",
}

# The fold is a count — of people, not of rows.  `sum` would double-count the
# member who wrote twice, which is exactly what `fold_note` promises not to do.
SERIES_FOLD = "count"


def _parse_date(raw: object) -> Optional[date]:
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _member_key(row: Mapping[str, object]) -> str:
    """Which household member a row belongs to, as an opaque bucket label.

    `member_id` only.  Never `id`: on a visits or medications row that is the
    row's own primary key, and counting those would report a household of four
    because one person logged four times.  Never `name` either — this module
    reads no identity, and a name would leak through the head count as surely as
    it would through the copy.

    Rows without a `member_id` all land in one bucket.  If nothing in the data
    carries one, every day reads as one participant, which is the honest answer:
    records exist, and how many different people wrote them is not knowable from
    what was handed over.
    """
    raw = row.get("member_id")
    if raw is None or raw == "":
        return ""
    return str(raw)


def _dates(analysis: Mapping[str, object]) -> List[date]:
    """Recorded days, ascending and deduped.  Unparseable dates are dropped
    rather than guessed at, per the analysis boundaries in story-system.md."""
    seen: Set[date] = set()
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        parsed = _parse_date(item.get("date"))
        if parsed is not None:
            seen.add(parsed)
    return sorted(seen)


def _gaps(dates: Sequence[date]) -> List[int]:
    """Blank days between consecutive records.  Adjacent days give 0."""
    return [max((later - earlier).days - 1, 0) for earlier, later in zip(dates, dates[1:])]


def _members_by_date(analysis: Mapping[str, object]) -> Dict[date, Set[str]]:
    """Distinct member buckets per day — the set 『同一人同日只计一次』 names."""
    members: Dict[date, Set[str]] = {}
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        parsed = _parse_date(item.get("date"))
        if parsed is None:
            continue
        members.setdefault(parsed, set()).add(_member_key(item))
    return members


def _counts_by_date(analysis: Mapping[str, object]) -> Dict[date, int]:
    """Raw row multiplicity per day, for the repeat bookkeeping the frame wants.

    `measurement_count` only, defaulting to 1 — no fallback to a bare `count`,
    which records and adherence can afford because on their rows the word has
    one meaning.  Here it does not: a family row is whatever upstream table it
    came from, and `count` on it could be a visit tally or a medication tally,
    neither of which is a number of writes.
    """
    counts: Dict[date, int] = {}
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        parsed = _parse_date(item.get("date"))
        if parsed is None:
            continue
        try:
            value = int(item.get("measurement_count") or 1)
        except (TypeError, ValueError):
            value = 1
        counts[parsed] = counts.get(parsed, 0) + max(1, value)
    return counts


def _breadth(dates: Sequence[date], members: Mapping[date, Set[str]]) -> Optional[float]:
    """Average number of participants across the days that hold any record.

    The denominator is recorded days, not calendar days — where the records
    domain divides by the span because its question is how densely the window
    was covered, the question here is how many people wrote on the days anyone
    wrote.  Dividing by the span would blend two changes, fewer people and fewer
    days, into one number and then name it after only one of them.

    It is not a share of the household either.  Nothing here knows how many
    members exist, by construction.
    """
    if not dates:
        return None
    total = sum(len(members.get(day) or {""}) for day in dates)
    return total / float(len(dates))


def state_for(analysis: Mapping[str, object]) -> str:
    """Derive the household state, or accept one the caller already computed.

    The declared key is `family_state`, not `state`: analyses reach this adapter
    from several upstream modules and a bare `state` is too general a name to
    claim, the same care records takes with `recording_state`.
    """
    declared = analysis.get("family_state")
    if isinstance(declared, str) and declared in SHAPE_BY_STATE:
        return declared

    dates = _dates(analysis)
    if len(dates) < 2:
        return "insufficient"

    members = _members_by_date(analysis)
    gaps = _gaps(dates)

    # A long silence that has since ended is 恢复, whatever the breadth did
    # across it.  Checked before the trend so a resumed household is not read as
    # a narrowing one on the strength of the days it missed.
    if gaps and max(gaps) >= GAP_DAYS_FOR_BREAK and gaps[-1] < GAP_DAYS_FOR_BREAK:
        return "resumed_after_break"

    if len(dates) < MIN_DAYS_FOR_TREND:
        return "insufficient"

    middle = len(dates) // 2
    early = _breadth(dates[:middle] or dates[:1], members)
    late = _breadth(dates[middle:], members)
    if early is None or late is None:
        return "insufficient"

    if late - early > BREADTH_BAND:
        return "widening"
    if early - late > BREADTH_BAND:
        return "narrowing"

    latest_gap = gaps[-1] if gaps else 0
    typical_gap = sorted(gaps)[len(gaps) // 2] if gaps else 0
    if latest_gap > typical_gap + 1:
        return "today_breaks_streak"

    # Uneven participation is keyed on how many people wrote, not how many rows
    # they wrote.  Row multiplicity would report 一个人记了两次 as a household
    # that fluctuates, and this domain counts people.
    sizes = [len(members.get(day) or {""}) for day in dates]
    if sizes and max(sizes) != min(sizes):
        return "uneven_participation"

    return "steady"


def shape_for(analysis: Mapping[str, object]) -> str:
    return SHAPE_BY_STATE.get(state_for(analysis), "insufficient")


def trend_direction(analysis: Mapping[str, object]) -> Optional[str]:
    state = state_for(analysis)
    if state == "widening":
        return "up"
    if state == "narrowing":
        return "down"
    if state == "insufficient":
        return None
    return "stable"


def coverage_for(analysis: Mapping[str, object]) -> Mapping[str, object]:
    """Recorded days and repeats, in the shared Signal Frame shape.

    Counted in days, like every other domain, and deliberately not in members:
    the frame's coverage block is closed at a fixed set of keys, so there is
    nowhere to put a household size, and the fraction it would license — 几位家人
    里有几位记录了 — is a printed observation about whoever is missing.

    Today's HTML and SVG renderers read the host's `recorded_days` straight off
    the analysis (render.py:385, :1286, :1288) rather than this block; routing
    them through here is P4 work, and this docstring is the marker for it.
    """
    dates = _dates(analysis)
    members = _members_by_date(analysis)
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
        # Days more than one *row* landed on, matching the schema's wording and
        # every other domain's arithmetic.  Days more than one person wrote on
        # is a different number, and it is the one the series carries.
        "repeat_days": sum(1 for day in dates if counts.get(day, 1) > 1),
    }


def series_for(analysis: Mapping[str, object]) -> List[Mapping[str, object]]:
    """One point per recorded day: how many people wrote, and how many rows.

    Here `value` and `count` come apart, where records and adherence have them
    coincide by construction.  `count` is raw row multiplicity, which the frame
    uses for its repeat bookkeeping and which the shared series gates check
    against `coverage_for`; `value` is the number of distinct people, which is
    what this domain narrates.  Two rows from one member is a repeat, not a
    second participant, and only one of those two numbers may be plotted.

    Days without records are absent rather than zero, per story-system.md: a
    silent day is a day nobody wrote, not a day the household emptied.
    """
    members = _members_by_date(analysis)
    counts = _counts_by_date(analysis)
    points: List[Mapping[str, object]] = []
    for day in sorted(members):
        points.append(
            {
                "date": day.isoformat(),
                "value": float(len(members[day] or {""})),
                "count": counts.get(day, 1),
            }
        )
    return points
