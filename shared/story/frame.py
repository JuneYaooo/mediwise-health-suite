"""Build a Signal Frame from a domain adapter, and flatten one for the renderers.

Two functions, one direction of travel.  `build_frame` turns a host analysis dict
into the schema-valid, domain-neutral IR that `story-design/signal-frame.schema.json`
describes.  `render_ready` takes the same inputs and returns an analysis dict the
existing HTML/SVG renderers can consume unchanged.

The second function exists because the renderers predate the frame.  `render.py`
reads `analysis["shape"]` (`render.py:657`) and a signed `daily_delta` /
`latest_delta` (`render.py:690`) straight off the dict, and `selector.py` branches
on `analysis["state"]` (`:153`, `:163`) — none of them call an adapter.  So a
non-weight analysis that arrives without those keys narrates as `insufficient`
with no direction, no matter how much data it carries.  `render_ready` is the
adapter call the renderers never make.

Weight is deliberately left alone: `render_ready` fills only keys that are absent,
so a legacy weight analysis (which already carries `state`, and whose byte-for-byte
output is locked by `tests/golden/`) passes through untouched.
"""

from __future__ import annotations

from datetime import date, timedelta
from statistics import median as _median
from typing import Mapping, Optional

from . import adapters as _adapters

__all__ = [
    "build_frame",
    "render_ready",
    "robust_fit",
    "robust_direction_strength",
    "ESTIMATOR_METHOD",
    "FIT_METHOD",
]

NON_CAUSAL_NOTE = "相关线索不代表因果。"

#: The estimator identifier stored in the domain-neutral Signal Frame. Same-day
#: folding already travels separately as `series_meta.fold`; putting `daily_median`
#: here would be false for sleep/mean, intake/sum, activity/last and event/count.
ESTIMATOR_METHOD = "theil_sen"

#: Compatibility spelling returned by the legacy weight analyser. Its input really
#: is folded to a daily median before the shared estimator runs. New domain-neutral
#: consumers use `ESTIMATOR_METHOD` together with `series_meta.fold`.
FIT_METHOD = "daily_median+" + ESTIMATOR_METHOD


def _dated_pairwise_slopes(points, value_key: str):
    """Return parsed dated values and their calendar-day pairwise slopes.

    The fit and the visual direction score must read precisely the same pairs. A
    second loop with slightly different date or value filtering would put a needle
    beside a number derived from different evidence.
    """
    if len(points) < 2:
        return [], []
    origin = _as_date(points[0].get("date"))
    if origin is None:
        return [], []
    dated = []
    for item in points:
        item_date = _as_date(item.get("date"))
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

    Lifted verbatim out of `weight_truth_card.theil_sen_fit`, which is now a thin
    delegation to this — one estimator, so 稳健估计 cannot mean two different things
    on two cards.  `tests/test_story_frame.py::RobustFitTests` pins the two to
    identical floats rather than approximately equal ones.

    Scale-free by construction, which is what lets it serve all eight domains: the
    x-axis is calendar-day offset from the first point and the y-axis is whatever the
    series holds, so the same median-of-pairwise-slopes returns kg/day, 分钟/day or
    步/day with no threshold anywhere in it.  Calendar offsets are also why a gap is
    handled correctly — five silent days widen the run rather than counting as one.

    Returns `(None, None)` rather than a flat line whenever the points cannot support
    a fit: fewer than two of them, an unparseable first date, or every point on the
    same day.  A fabricated zero slope would read on the card as 「长期持平」, which is
    a claim, where an absent one reads as 暂无稳健拟合, which is the truth.
    """
    dated, slopes = _dated_pairwise_slopes(points, value_key)
    if not slopes:
        return None, None
    slope = float(_median(slopes))
    intercept = float(_median([value - slope * offset for offset, value in dated]))
    return slope, intercept


def robust_direction_strength(points, value_key: str = "value") -> Optional[float]:
    """Return a unitless signed score for directional visualisations.

    The numerator is the same Theil–Sen median slope used by `robust_fit`; the
    denominator is the median absolute pairwise slope. Their units cancel, so the
    result can drive one compass for kg, minutes, steps and event counts without a
    domain table. A clean one-way series approaches ±1, a mixed or noisy series
    moves toward 0, and a flat fit is exactly 0.

    This score is presentation metadata, not a second trend estimate and not a
    health magnitude. The printed long-run number remains `trend.delta` in the
    domain's own unit.
    """
    _dated, slopes = _dated_pairwise_slopes(points, value_key)
    if not slopes:
        return None
    slope = float(_median(slopes))
    if slope == 0.0:
        return 0.0
    scale = float(_median([abs(item) for item in slopes]))
    if scale == 0.0:
        return 0.0
    return max(-1.0, min(1.0, slope / scale))


def _as_date(value) -> Optional[date]:
    """Parse a date through the one parser the rest of the suite already uses.

    `normalize._parse_date` accepts a bare `2026-07-09`, a full ISO timestamp and a
    `Z` suffix, which is the range of spellings the hosts actually write.  Reused
    rather than reimplemented because `robust_fit` has to agree with weight's fit on
    every input, and a second date parser is a second set of edge cases to disagree
    over.  Imported lazily: `normalize` calls `render_ready`, so importing it at
    module scope here would close a cycle.
    """
    global _PARSE_DATE
    if _PARSE_DATE is None:
        from .normalize import _parse_date

        _PARSE_DATE = _parse_date
    return _PARSE_DATE(value)


#: Resolved on first use by `_as_date`; see the cycle note there.
_PARSE_DATE = None


def _window(analysis: Mapping[str, object], series: list) -> dict:
    """The observed window, clamped to the schema's 7..90 days.

    `days` is what the caller asked for; `start` / `end` bound what was actually
    recorded, falling back to the requested window when nothing was.
    """
    requested = int(analysis.get("window_days") or analysis.get("span_days") or 14)
    days = max(7, min(requested, 90))
    dates = [str(point["date"]) for point in series if point.get("date")]
    if dates:
        end = date.fromisoformat(max(dates))
    else:
        latest = analysis.get("latest_date") or analysis.get("as_of")
        try:
            end = date.fromisoformat(str(latest))
        except (TypeError, ValueError):
            end = date.today()
    start = end - timedelta(days=days - 1)
    return {"days": days, "start": start.isoformat(), "end": end.isoformat()}


def _trend(analysis: Mapping[str, object], adapter, series: list, window_days: int) -> dict:
    """The trend block, with direction taken from the adapter, never guessed here.

    `claim_allowed` stays the host's call: an adapter reports which way a series
    points, but whether the window earns a trend sentence at all is a data-quality
    judgement the loader already made.  It also gates the fit below — a two-day
    window must not print a fortnight-long extrapolation beside a note that says
    记录不足.

    `direction` is read off the incoming analysis before the fit runs, so filling
    `delta` here can never feed back into it.  That matters for weight alone, whose
    adapter falls back to `trend_delta` when `state` is missing; every other adapter
    derives direction from its own rows and ignores this field entirely.
    """
    direction = adapter.trend_direction(analysis)
    trend = {
        "claim_allowed": bool(analysis.get("trend_claim_allowed")),
        "direction": direction if direction in ("up", "down", "stable") else None,
    }
    delta = analysis.get("trend_delta")
    if isinstance(delta, (int, float)) and not isinstance(delta, bool):
        # The host already fitted this window; weight always has, and its output is
        # locked byte-for-byte, so an incoming number is authoritative over ours.
        trend["delta"] = float(delta)
        slope = analysis.get("trend_slope_per_day")
        if slope is None:
            slope = analysis.get("slope_per_day")
        if isinstance(slope, (int, float)) and not isinstance(slope, bool):
            trend["slope_per_day"] = float(slope)
        trend["method"] = ESTIMATOR_METHOD
    elif trend["claim_allowed"]:
        slope, _intercept = robust_fit(series)
        if slope is not None:
            trend["slope_per_day"] = round(slope, 5)
            # Extrapolated across the requested window exactly as weight defines it
            # (`weight_truth_card.py:263`), so 长期 spans the same stretch of calendar
            # in every domain instead of a per-domain interval sharing one label.
            trend["delta"] = round(slope * (window_days - 1), 3)
            trend["method"] = ESTIMATOR_METHOD
    if trend.get("delta") is not None:
        visual_strength = robust_direction_strength(series)
        if visual_strength is not None:
            trend["visual_strength"] = round(visual_strength, 5)
    latest = _latest_delta(series)
    if latest is not None:
        trend["latest_delta"] = latest
    return trend


def _latest_delta(series: list) -> Optional[float]:
    """Change between the two most recent folded points, or None below two points."""
    if len(series) < 2:
        return None
    try:
        return round(float(series[-1]["value"]) - float(series[-2]["value"]), 4)
    except (KeyError, TypeError, ValueError):
        return None


def _latest_value(series: list) -> Optional[float]:
    """The most recent folded reading — the one absolute number a card may show.

    Deliberately unrounded: `analyze_weight_records` rounds its own `latest_weight`
    to three places and `render_ready` never overwrites a key that is already there,
    so rounding here would only ever change a non-weight domain's number, and 452
    minutes of sleep has no place it wants rounding to.
    """
    if not series:
        return None
    try:
        return float(series[-1]["value"])
    except (KeyError, TypeError, ValueError):
        return None


def _comparison_gap_days(series: list) -> Optional[int]:
    """Calendar days between the two most recent recorded days.

    Calendar, not index: the series holds one point per *recorded* day, so the last
    two points can be a week apart.  Counting positions instead would report 1 and
    the card would say 较昨日 about two readings the member can see are five days
    apart — the same 未记录日不按 0 处理 rule the coverage line follows, applied to
    the comparison itself.
    """
    if len(series) < 2:
        return None
    try:
        recent = date.fromisoformat(str(series[-1]["date"]))
        previous = date.fromisoformat(str(series[-2]["date"]))
    except (KeyError, TypeError, ValueError):
        return None
    return (recent - previous).days


def _facts(coverage: Mapping[str, object], lexicon: Mapping[str, str]) -> list:
    """The two facts every domain can always state: how many days, how many marks.

    Both are counts of recording behaviour, so they carry no reading, no unit and
    no direction — which is why they survive for a zero-data frame too.
    """
    scope = lexicon.get("scope_label") or "有记录日"
    return [
        {
            "id": "recorded-days",
            "label": scope,
            "value_text": "%d 天" % int(coverage.get("recorded_days") or 0),
        },
        {
            "id": "measurement-count",
            "label": "记录次数",
            "value_text": "%d 次" % int(coverage.get("measurement_count") or 0),
        },
    ]


def _companions(domain: str, analysis: Mapping[str, object]) -> list:
    """Reduced companion frames, read off the host's `management` block.

    `companions_for(domain)` says which domains this one is allowed to show
    alongside itself; the numbers come from whatever the host already computed for
    them (`synthesis.analyze_weight_management`).  A companion the host did not
    summarise is omitted rather than invented — an absent companion means "not
    observed", and a zero-filled one would read as "observed and empty".

    Only coverage and a direction label cross over.  No companion reading, no
    companion unit, and no arithmetic between a companion and the subject: the
    schema's `cross_domain_arithmetic: false` is a boundary, not a default.
    """
    management = analysis.get("management")
    if not isinstance(management, Mapping):
        return []
    out = []
    for name in _adapters.companions_for(domain):
        summary = management.get(name)
        if not isinstance(summary, Mapping):
            continue
        block = {
            "domain": name,
            "claim_allowed": bool(summary.get("claim_allowed")),
            "coverage_ratio": float(summary.get("coverage_ratio") or 0.0),
        }
        recorded = summary.get("recorded_days")
        if isinstance(recorded, int) and not isinstance(recorded, bool):
            block["recorded_days"] = max(recorded, 0)
        direction = summary.get("change_direction")
        if direction in ("higher", "lower", "similar", "insufficient"):
            block["change_direction"] = direction
        scope = summary.get("scope_label")
        if isinstance(scope, str) and scope:
            block["scope_label"] = scope[:12]
        out.append(block)
    return out[:6]


def build_frame(domain: str, analysis: Mapping[str, object]) -> dict:
    """Assemble the Signal Frame for `domain` from a host analysis dict.

    Every narrative decision is delegated to the domain's adapter — `shape_for`,
    `trend_direction`, `coverage_for`, `series_for` — so this function names no
    domain, no unit and no metric of its own.  The result validates against
    `story-design/signal-frame.schema.json`.
    """
    adapter = _adapters.get_adapter(domain)
    lexicon = _adapters.lexicon_for(domain)
    series = list(adapter.series_for(analysis))
    coverage = dict(adapter.coverage_for(analysis))
    window = _window(analysis, series)
    frame = {
        "schema_version": 1,
        "domain": adapter.DOMAIN,
        "lexicon": dict(lexicon),
        "window": window,
        "series": series,
        "series_meta": {
            "fold": getattr(adapter, "SERIES_FOLD", "median"),
            "relative_only": True,
        },
        "shape": adapter.shape_for(analysis),
        "trend": _trend(analysis, adapter, series, window["days"]),
        "coverage": coverage,
        "facts": _facts(coverage, lexicon),
        "limits": {
            "causal_claim": False,
            "prescription": False,
            "unrecorded_is_zero": False,
            "cross_domain_arithmetic": False,
            "non_causal_note": NON_CAUSAL_NOTE,
        },
    }
    companions = _companions(domain, analysis)
    if companions:
        frame["companions"] = companions
    return frame


def render_ready(domain: str, analysis: Mapping[str, object]) -> dict:
    """A copy of `analysis` carrying the flat keys the renderers read.

    Fills `shape`, the coverage counts and the signed deltas from the frame, so
    `render.py` and `selector.py` see the adapter's answer instead of falling back
    to `insufficient`.  Existing keys always win: a weight analysis already speaks
    the renderers' dialect, and its output is locked byte-for-byte.

    `daily_delta`, `comparison_gap_days` and `latest_value` are the renderers' own
    spellings for three numbers `analyze_weight_records` computes and no other
    loader does.  Reading them off the frame is what stops the other seven domains
    printing 「—」 in the headline of a card whose trace they had just drawn.  Each
    matches weight's definition exactly rather than approximately: the step is
    last-minus-previous over folded days, the gap is the calendar distance between
    those two days, the reading is the last folded value.

    `trend_delta` is in that list on the same terms, because the fit that defines it
    now lives here as `robust_fit` and `weight_truth_card.theil_sen_fit` delegates to
    it.  One estimator, one method string (`ESTIMATOR_METHOD`): filing two different lines
    under the same key would make two domains' 长期 numbers incomparable while looking
    identical, and that is exactly what a shared fit prevents.  Weight's own number
    still wins where it exists, as every key here does.
    """
    frame = build_frame(domain, analysis)
    ready = dict(analysis)
    coverage, trend, window = frame["coverage"], frame["trend"], frame["window"]
    series = frame["series"]
    derived = {
        "shape": frame["shape"],
        "recorded_days": coverage.get("recorded_days"),
        "measurement_count": coverage.get("measurement_count"),
        "coverage_ratio": coverage.get("ratio"),
        "span_days": coverage.get("span_days") or window["days"],
        "window_days": window["days"],
        "latest_delta": trend.get("latest_delta"),
        "daily_delta": trend.get("latest_delta"),
        "comparison_gap_days": _comparison_gap_days(series),
        "latest_value": _latest_value(series),
        "trend_delta": trend.get("delta"),
        "trend_visual_strength": trend.get("visual_strength"),
    }
    for key, value in derived.items():
        if value is not None and ready.get(key) in (None, ""):
            ready[key] = value
    ready["frame"] = frame
    return ready
