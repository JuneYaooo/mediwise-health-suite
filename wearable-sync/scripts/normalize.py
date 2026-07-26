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

    # Direct pass-through: Apple Health single-value types
    for metric_type in ("weight", "height", "body_fat", "calories", "blood_sugar"):
        for rm in by_type.get(metric_type, []):
            normalized.append({
                "metric_type": metric_type,
                "value": rm.value,
                "measured_at": rm.timestamp,
                "source": provider,
            })

    # Direct pass-through: time-series and summary types (Garmin, Huawei, Zepp, etc.)
    #
    # `steps` belongs here rather than in the aggregator above: Zepp (`zepp.py`) and
    # Huawei (`huawei.py`) report a day's count as one finished `steps` row, so there
    # is nothing left to add up.  Only providers that hand over intraday samples name
    # them `steps_raw`, and those are the ones `_aggregate_daily_steps` folds.  Without
    # this branch a `steps` row matched no case in this function and was dropped, which
    # is why those two providers' step data never reached the database.
    for metric_type in ("stress", "body_battery", "hrv", "activity", "steps"):
        for rm in by_type.get(metric_type, []):
            normalized.append({
                "metric_type": metric_type,
                "value": rm.value,
                "measured_at": rm.timestamp,
                "source": provider,
            })

    # Garmin sleep: already fully aggregated by the provider, pass through directly
    for rm in by_type.get("sleep", []):
        normalized.append({
            "metric_type": "sleep",
            "value": rm.value,
            "measured_at": rm.timestamp,
            "source": provider,
        })

    # Blood pressure pairing (Apple Health stores systolic/diastolic separately)
    bp_raw = by_type.get("bp_systolic_raw", []) + by_type.get("bp_diastolic_raw", [])
    if bp_raw:
        normalized.extend(_pair_blood_pressure(bp_raw, provider))

    return normalized


def _aggregate_daily_steps(raw_steps: list[RawMetric], provider: str) -> list[dict]:
    """Aggregate raw step samples into daily totals.

    Two shapes arrive under `steps_raw`.  Apple Health and Gadgetbridge send intraday
    samples whose value is a bare number, and those are what the sum here is for.
    Garmin's `_fetch_stats` sends one already-finished day whose value is a JSON object
    carrying `count` alongside the distance and calories the watch measured itself.

    Both have to be read, because a day's totals cannot be recovered from the wrong one.
    Summing the JSON text is impossible, and a day that arrived pre-aggregated must not
    be added to anything.  When a day has both, the provider's own total wins: it is the
    device's arithmetic over the same samples, and it brings distance and calories that
    no sum of step counts could produce.

    Distance and calories are carried only when a provider actually reported them.  An
    absent key is left absent rather than written as 0, so that a reader can tell 「这台
    设备没报距离」 from 「这天距离是 0」 -- the same distinction the story adapters need
    and cannot make from a zero.
    """
    sampled = defaultdict(int)     # days assembled from intraday samples
    seen_samples = set()
    summary = {}                   # days a provider already totalled for us

    for rm in raw_steps:
        day = rm.timestamp[:10]  # YYYY-MM-DD
        payload = _as_payload(rm.value)
        if payload is not None:
            count = _as_int(payload.get("count"))
            if count is None:
                continue
            row = {"count": count}
            for key in ("distance_m", "calories"):
                extra = _as_int(payload.get(key))
                if extra is not None:
                    row[key] = extra
            summary[day] = row
            continue
        count = _as_int(rm.value)
        if count is None:
            continue
        sampled[day] += count
        seen_samples.add(day)

    result = []
    for day in sorted(seen_samples | set(summary)):
        row = summary.get(day) or {"count": sampled[day]}
        result.append({
            "metric_type": "steps",
            "value": json.dumps(row),
            "measured_at": f"{day} 23:59:00",
            "source": provider,
        })
    return result


def _as_payload(value) -> dict | None:
    """Read a value as a JSON object, or None if it is not one.

    Used to tell a pre-aggregated day from an intraday sample without trusting
    `RawMetric.extra`: the `aggregated` flag Garmin sets is advisory and no other
    provider sets it, so the value's own shape is the more reliable signal.
    """
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _as_int(value) -> int | None:
    """Coerce a reported number to int, or None when it is not a number.

    None is returned rather than 0 so that callers can drop an unreadable field
    instead of recording a measurement nobody took.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _aggregate_sleep_sessions(raw_sleep: list[RawMetric], provider: str) -> list[dict]:
    """Aggregate raw sleep stage samples into sleep sessions.

    Groups consecutive sleep samples into sessions (gap > 2h = new session).
    Calculates duration breakdown by stage.
    """
    if not raw_sleep:
        return []

    interval_samples = [sample for sample in raw_sleep if sample.extra.get("end_timestamp")]
    if interval_samples:
        return _aggregate_interval_sleep_sessions(interval_samples, provider)

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


def _aggregate_interval_sleep_sessions(raw_sleep: list[RawMetric], provider: str) -> list[dict]:
    """Aggregate sleep records with explicit start/end intervals.

    Apple Health exports intervals, not one-minute samples. Split overlapping
    intervals into non-overlapping segments so in-bed records do not double-count
    detailed awake/core/deep/REM records.
    """
    intervals = []
    for sample in raw_sleep:
        try:
            start = datetime.strptime(sample.timestamp[:19], "%Y-%m-%d %H:%M:%S")
            end = datetime.strptime(sample.extra["end_timestamp"][:19], "%Y-%m-%d %H:%M:%S")
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        intervals.append((start, end, sample.value))

    if not intervals:
        return []
    intervals.sort(key=lambda item: (item[0], item[1]))

    sessions = []
    current = [intervals[0]]
    current_end = intervals[0][1]
    for interval in intervals[1:]:
        if interval[0] - current_end > timedelta(hours=2):
            sessions.append(current)
            current = [interval]
            current_end = interval[1]
            continue
        current.append(interval)
        current_end = max(current_end, interval[1])
    sessions.append(current)

    priority = {
        "awake": 5,
        "deep_sleep": 4,
        "rem_sleep": 3,
        "light_sleep": 2,
        "in_bed": 1,
    }
    results = []
    for session in sessions:
        boundaries = sorted({point for start, end, _ in session for point in (start, end)})
        minutes = defaultdict(float)
        for start, end in zip(boundaries, boundaries[1:]):
            if end <= start:
                continue
            midpoint = start + (end - start) / 2
            active = [stage for item_start, item_end, stage in session
                      if item_start <= midpoint < item_end]
            if not active:
                continue
            stage = max(active, key=lambda name: priority.get(name, 0))
            if stage == "in_bed":
                stage = "awake"
            minutes[stage] += (end - start).total_seconds() / 60

        deep_min = round(minutes.get("deep_sleep", 0))
        light_min = round(minutes.get("light_sleep", 0))
        rem_min = round(minutes.get("rem_sleep", 0))
        awake_min = round(minutes.get("awake", 0))
        total_min = deep_min + light_min + rem_min + awake_min
        if total_min < 30:
            continue
        sleep_value = {
            "duration_min": total_min,
            "deep_min": deep_min,
            "light_min": light_min,
            "rem_min": rem_min,
            "awake_min": awake_min,
        }
        results.append({
            "metric_type": "sleep",
            "value": json.dumps(sleep_value),
            "measured_at": min(item[0] for item in session).strftime("%Y-%m-%d %H:%M:%S"),
            "source": provider,
        })
    return results


def _pair_blood_pressure(raw_bp: list[RawMetric], provider: str) -> list[dict]:
    """Pair Apple Health systolic and diastolic readings within a 60-second window.

    Apple Health stores blood pressure as two separate record types. This function
    matches them by timestamp proximity and combines them into the standard
    {"systolic": N, "diastolic": N} JSON format.
    """
    systolic = [rm for rm in raw_bp if rm.metric_type == "bp_systolic_raw"]
    diastolic = [rm for rm in raw_bp if rm.metric_type == "bp_diastolic_raw"]

    systolic.sort(key=lambda r: r.timestamp)
    diastolic.sort(key=lambda r: r.timestamp)

    paired = []
    used_dia = set()

    for sys_rm in systolic:
        try:
            sys_dt = datetime.strptime(sys_rm.timestamp[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        sys_val = sys_rm.value

        best_match = None
        best_gap = None
        for i, dia_rm in enumerate(diastolic):
            if i in used_dia:
                continue
            try:
                dia_dt = datetime.strptime(dia_rm.timestamp[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            gap = abs((dia_dt - sys_dt).total_seconds())
            if gap <= 60 and (best_gap is None or gap < best_gap):
                best_match = (i, dia_rm)
                best_gap = gap

        if best_match:
            idx, dia_rm = best_match
            used_dia.add(idx)
            try:
                bp_value = json.dumps(
                    {"systolic": float(sys_val), "diastolic": float(dia_rm.value)},
                    ensure_ascii=False,
                )
                paired.append({
                    "metric_type": "blood_pressure",
                    "value": bp_value,
                    "measured_at": sys_rm.timestamp,
                    "source": provider,
                })
            except (ValueError, TypeError):
                continue

    return paired
