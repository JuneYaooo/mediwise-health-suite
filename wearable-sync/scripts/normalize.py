"""Data normalization for wearable device metrics.

Converts provider-specific raw metrics into the standardized health_metrics format
used by mediwise-health-tracker.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from collections import defaultdict

from providers.base import RawMetric


def normalize_metrics(raw_metrics: list[RawMetric], provider: str) -> list[dict]:
    """Normalize raw metrics from a provider into health_metrics format.

    Handles aggregation for certain metric types:
    - steps_raw: aggregates into daily totals
    - sleep_raw: aggregates into sleep sessions with stage breakdown

    Args:
        raw_metrics: List of RawMetric from a provider's fetch_metrics().
        provider: Provider name (used as source field).

    Returns:
        List of dicts ready for insertion into health_metrics table:
        {metric_type, value, measured_at, source}
    """
    normalized = []

    # Separate raw metrics by type for aggregation
    by_type = defaultdict(list)
    for rm in raw_metrics:
        by_type[rm.metric_type].append(rm)

    # Direct pass-through metrics (heart_rate, blood_oxygen)
    for metric_type in ("heart_rate", "blood_oxygen"):
        for rm in by_type.get(metric_type, []):
            normalized.append({
                "metric_type": metric_type,
                "value": rm.value,
                "measured_at": rm.timestamp,
                "source": provider,
            })

    # Aggregate steps into daily totals
    if "steps_raw" in by_type:
        normalized.extend(_aggregate_daily_steps(by_type["steps_raw"], provider))

    # Aggregate sleep into sessions
    if "sleep_raw" in by_type:
        normalized.extend(_aggregate_sleep_sessions(by_type["sleep_raw"], provider))

    return normalized


def _aggregate_daily_steps(raw_steps: list[RawMetric], provider: str) -> list[dict]:
    """Aggregate raw step samples into daily totals."""
    daily = defaultdict(int)
    for rm in raw_steps:
        day = rm.timestamp[:10]  # YYYY-MM-DD
        try:
            daily[day] += int(rm.value)
        except (ValueError, TypeError):
            pass

    result = []
    for day, total in sorted(daily.items()):
        result.append({
            "metric_type": "steps",
            "value": json.dumps({"count": total, "distance_m": 0, "calories": 0}),
            "measured_at": f"{day} 23:59:00",
            "source": provider,
        })
    return result


def _aggregate_sleep_sessions(raw_sleep: list[RawMetric], provider: str) -> list[dict]:
    """Aggregate raw sleep stage samples into sleep sessions.

    Groups consecutive sleep samples into sessions (gap > 2h = new session).
    Calculates duration breakdown by stage.
    """
    if not raw_sleep:
        return []

    # Sort by timestamp
    sorted_samples = sorted(raw_sleep, key=lambda r: r.timestamp)

    sessions = []
    current_session = [sorted_samples[0]]

    for i in range(1, len(sorted_samples)):
        prev_ts = datetime.strptime(sorted_samples[i - 1].timestamp[:19], "%Y-%m-%d %H:%M:%S")
        curr_ts = datetime.strptime(sorted_samples[i].timestamp[:19], "%Y-%m-%d %H:%M:%S")
        gap = (curr_ts - prev_ts).total_seconds()

        if gap > 7200:  # >2 hours gap = new session
            sessions.append(current_session)
            current_session = [sorted_samples[i]]
        else:
            current_session.append(sorted_samples[i])

    if current_session:
        sessions.append(current_session)

    result = []
    for session in sessions:
        if len(session) < 2:
            continue

        start_ts = datetime.strptime(session[0].timestamp[:19], "%Y-%m-%d %H:%M:%S")
        end_ts = datetime.strptime(session[-1].timestamp[:19], "%Y-%m-%d %H:%M:%S")
        total_min = int((end_ts - start_ts).total_seconds() / 60)

        if total_min < 30:  # Too short to be a real sleep session
            continue

        # Count stage minutes (assuming ~1 sample per minute interval)
        stage_counts = defaultdict(int)
        for sample in session:
            stage_counts[sample.value] += 1

        # Estimate minutes per stage based on sample count ratio
        deep_min = int(total_min * stage_counts.get("deep_sleep", 0) / max(len(session), 1))
        light_min = int(total_min * stage_counts.get("light_sleep", 0) / max(len(session), 1))
        rem_min = int(total_min * stage_counts.get("rem_sleep", 0) / max(len(session), 1))
        awake_min = total_min - deep_min - light_min - rem_min

        sleep_value = {
            "duration_min": total_min,
            "deep_min": deep_min,
            "light_min": light_min,
            "rem_min": rem_min,
            "awake_min": max(0, awake_min),
        }

        result.append({
            "metric_type": "sleep",
            "value": json.dumps(sleep_value),
            "measured_at": session[0].timestamp,
            "source": provider,
        })

    return result
