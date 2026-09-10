"""Turn raw per-domain rows into the analysis dict the renderers read.

Both surfaces that build a story from database rows need this step, and they must
not each own a copy of it: `recorded_days` and `coverage_ratio` decide which
templates are eligible, so two implementations would let the card and the
briefing disagree about the same window.  That is the defect class
`tests/test_cross_domain_render.py` locks down.

`aggregate_daily_medians` is re-read from `shared.robust_weight` rather than
owned here because weight is the one pre-folded domain (`PREFOLDED = ("weight",)`
in tests/test_story_frame.py): the pipeline in story-design/story-system.md folds
weight rows *upstream* of the adapter, which is why `adapters/weight.py` is
pass-through.  A caller holding raw weighings must fold them first, or one point
per weighing reaches the frame instead of one point per day.  The fold and the
date parser live with the weight analyser that has to agree with them; this
module only imports them.

Nothing here touches a database, a renderer, or any domain vocabulary.
"""

from __future__ import annotations

from typing import List

from ..robust_weight import aggregate_daily_medians, parse_date as _parse_date
from .adapters import component_for, component_key_for
from .frame import render_ready, robust_fit

# Event-shaped domains conclude from two recorded days; daily-series domains need
# three.  See 分析边界 in story-design/story-system.md.
EVENT_SHAPED_DOMAINS = ("adherence", "family", "records")


def domain_analysis_from_rows(domain: str, rows: List[dict], days: int) -> dict:
    """Normalize one domain's rows into the analysis dict the renderer reads.

    Real data and demo data both come through here, so their coverage numbers
    cannot drift apart.

    For the three multi-component domains the component is asked of the adapter
    rather than pinned here.  Pinning looks harmless and is not: the vitals adapter
    skips rows whose `metric_type` names a different metric, so a member who
    records only blood pressure got `recorded_days: 0` out of a window full of
    readings, and the card reported 记录不足 about data it had been handed.  The
    pick is written back into the analysis so the renderer narrates the same
    component this coverage was counted over, and so a later re-inference over
    changed rows cannot silently relabel a window already reported on.
    """
    seed = {"daily_records": rows, "window_days": days}
    component_key = component_key_for(domain)
    component = component_for(domain, seed) if component_key else ""
    if component_key and component:
        seed[component_key] = component
    normalized = render_ready(domain, seed)
    frame = normalized["frame"]
    coverage = frame["coverage"]
    series = frame["series"]
    recorded_days = int(coverage.get("recorded_days") or 0)
    parsed_dates = [_parse_date(point.get("date")) for point in series]
    valid_dates = [item for item in parsed_dates if item is not None]
    observed_span = (
        (max(valid_dates) - min(valid_dates)).days + 1 if valid_dates else 0
    )
    span_days = int(coverage.get("span_days") or 0) or observed_span
    coverage_ratio = float(coverage.get("ratio") or 0.0)
    if recorded_days and coverage_ratio <= 0:
        coverage_ratio = min(recorded_days / float(max(days, 1)), 1.0)
    minimum = 2 if domain in EVENT_SHAPED_DOMAINS else 3
    claim_allowed = recorded_days >= minimum
    analysis = {
        "daily_records": rows,
        "window_days": days,
        "span_days": span_days,
        "recorded_days": recorded_days,
        "measurement_count": int(coverage.get("measurement_count") or 0),
        "coverage_ratio": round(coverage_ratio, 3),
        "trend_claim_allowed": claim_allowed,
        "latest_date": series[-1]["date"] if series else None,
    }
    if len(series) >= 2:
        try:
            analysis["daily_delta"] = round(
                float(series[-1]["value"]) - float(series[-2]["value"]), 4
            )
        except (KeyError, TypeError, ValueError):
            pass
    if claim_allowed:
        slope, _intercept = robust_fit(series)
        if slope is not None:
            analysis["trend_slope_per_day"] = round(slope, 5)
            analysis["slope_per_day"] = round(slope, 5)
            analysis["trend_delta"] = round(slope * (days - 1), 3)
    if component_key and component:
        analysis[component_key] = component
    return analysis
