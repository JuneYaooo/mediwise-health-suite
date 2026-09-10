"""The weight analysis core: one robust estimator, one date parser, one fold.

`weight_truth_card.py` reads raw weighings out of SQLite, folds them to daily
medians, fits a robust direction, and classifies the result into one of eight
states.  Every one of those steps is here rather than in the card because they
are *analysis*, not presentation — the card decides how to say 「上浮」, this
module decides whether the numbers support saying it at all.

There is exactly one implementation of each on purpose:

* `robust_fit` is the Theil–Sen fit.  A second copy would let 稳健估计 mean two
  different things on two surfaces reading the same database, and the whole point
  of the estimator is that its answer does not depend on who is asking.
* `parse_date` is the single parser.  The hosts write `2026-07-09`, full ISO
  timestamps and a `Z` suffix; a second parser is a second set of edge cases to
  disagree over, which shows up as a day silently dropped from a window.
* `aggregate_daily_medians` is the single fold.  Weight is a level reading, so
  same-day duplicates take the median — summing or keeping the best-looking value
  would both be wrong, and one point per *weighing* reaching the fit is a
  different series from one point per *day*.

The story engine shared all three while it existed, which is how they ended up
outside weight-manager in the first place.  Nothing here imports a renderer, a
template, or any narrative vocabulary.

Scale-free by construction: the fit's x-axis is calendar-day offset from the
first point and its y-axis is whatever the series holds, so the same
median-of-pairwise-slopes serves kg/day, 分钟/day or 步/day with no threshold
anywhere in it.  Calendar offsets are also why a gap is handled correctly — five
silent days widen the run rather than counting as one.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from statistics import median
from typing import Dict, Iterable, List, Optional

__all__ = [
    "ESTIMATOR_METHOD",
    "FIT_METHOD",
    "aggregate_daily_medians",
    "dated_pairwise_slopes",
    "parse_date",
    "robust_fit",
    "state_for",
]

#: The estimator identifier stamped on analysis output.  Same-day folding travels
#: separately, but weight's fold is fixed at median, so the two halves are joined
#: here into the one string the truth card has always emitted.
ESTIMATOR_METHOD = "theil_sen"
FIT_METHOD = "daily_median+" + ESTIMATOR_METHOD


def parse_date(value) -> Optional[date]:
    """Parse a date through the one parser the suite uses.

    Accepts a bare `2026-07-09`, a full ISO timestamp and a `Z` suffix, which is
    the range of spellings the hosts actually write.  Returns None rather than
    raising: an unparseable date is a row to skip, not a reason to fail a report.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None


def aggregate_daily_medians(records: Iterable[dict]) -> List[dict]:
    """Collapse same-day measurements to a median before trend analysis.

    Out-of-range values are dropped rather than clamped: 10..500 kg is the range
    a scale can produce, so anything outside it is a typo or a unit mix-up, and
    folding it into the day's median would move the number everything downstream
    is computed from.  `measurement_count` is carried through because a day with
    three weighings is not the same evidence as a day with one.
    """
    grouped = {}  # type: Dict[date, List[float]]
    for record in records:
        measured_date = parse_date(record.get("measured_at") or record.get("date"))
        raw_value = record.get("weight", record.get("value"))
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if measured_date is None or not math.isfinite(value) or not 10 <= value <= 500:
            continue
        grouped.setdefault(measured_date, []).append(value)

    result = []
    for measured_date in sorted(grouped):
        values = grouped[measured_date]
        result.append({
            "date": measured_date.isoformat(),
            "weight": round(float(median(values)), 3),
            "measurement_count": len(values),
        })
    return result


def dated_pairwise_slopes(points, value_key: str):
    """Return parsed dated values and their calendar-day pairwise slopes.

    The fit and the visual direction score must read precisely the same pairs. A
    second loop with slightly different date or value filtering would put a needle
    beside a number derived from different evidence.
    """
    if len(points) < 2:
        return [], []
    origin = parse_date(points[0].get("date"))
    if origin is None:
        return [], []
    dated = []
    for item in points:
        item_date = parse_date(item.get("date"))
        if item_date is None:
            continue
        try:
            dated.append(((item_date - origin).days, float(item[value_key])))
        except (KeyError, TypeError, ValueError):
            continue
    slopes = []
    for index, (x1, y1) in enumerate(dated):
        for x2, y2 in dated[index + 1:]:
            if x2 != x1:
                slopes.append((y2 - y1) / (x2 - x1))
    return dated, slopes


def robust_fit(points, value_key: str = "value"):
    """Theil–Sen slope per day and median intercept over dated points.

    `weight_truth_card.theil_sen_fit` is a thin delegation to this, so the card
    and any other reader of the same window cannot report different directions
    for it.  `tests/test_weight_truth_card.py` pins the two to identical floats
    rather than approximately equal ones.

    Returns `(None, None)` rather than a flat line whenever the points cannot
    support a fit: fewer than two of them, an unparseable first date, or every
    point on the same day.  A fabricated zero slope would read on the card as
    「长期持平」, which is a claim, where an absent one reads as 暂无稳健拟合, which
    is the truth.
    """
    dated, slopes = dated_pairwise_slopes(points, value_key)
    if not slopes:
        return None, None
    slope = float(median(slopes))
    intercept = float(median([value - slope * offset for offset, value in dated]))
    return slope, intercept


def state_for(daily_delta, trend_delta, sufficient: bool) -> str:
    """Map weight signals to the historic eight states in one canonical place.

    The thresholds are in kg — ±0.15 for the day-to-day move, ±0.2 for the
    long-run direction — and they are deliberately asymmetric in meaning: a daily
    move is mostly water and food, so it takes more of it to count than a trend
    that has already been fitted over the window.
    """
    if not sufficient or trend_delta is None:
        return "insufficient"
    daily_direction = "stable"
    if daily_delta is not None and daily_delta > 0.15:
        daily_direction = "up"
    elif daily_delta is not None and daily_delta < -0.15:
        daily_direction = "down"

    trend_direction = "stable"
    if trend_delta > 0.2:
        trend_direction = "up"
    elif trend_delta < -0.2:
        trend_direction = "down"

    if daily_direction == "up" and trend_direction == "down":
        return "daily_up_trend_down"
    if daily_direction == "down" and trend_direction == "up":
        return "daily_down_trend_up"
    if trend_direction == "down":
        return "sustained_down"
    if trend_direction == "up":
        return "sustained_up"
    if daily_direction == "up":
        return "daily_up_stable"
    if daily_direction == "down":
        return "daily_down_stable"
    return "stable"
