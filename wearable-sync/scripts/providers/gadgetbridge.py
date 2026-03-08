"""Gadgetbridge provider - imports data from Gadgetbridge SQLite export.

Gadgetbridge exports a SQLite database containing activity samples from
various wearable devices (Mi Band, Amazfit, Huawei Band, etc.).

Key tables:
- MI_BAND_ACTIVITY_SAMPLE: heart rate, steps, activity type (with timestamps)
- HUAMI_EXTENDED_ACTIVITY_SAMPLE: SpO2, stress
- *_SLEEP_SAMPLE / sleep-related activity types in activity samples
"""

from __future__ import annotations

import os
import json
import sqlite3
from datetime import datetime, timedelta

from .base import BaseProvider, RawMetric


# Gadgetbridge activity type constants
_ACTIVITY_TYPE_SLEEP = {
    # Common Gadgetbridge raw activity kinds mapped to sleep stages
    # Activity type values vary by device; these are common ones
    112: "light_sleep",
    121: "deep_sleep",
    122: "rem_sleep",
    120: "light_sleep",  # alternate
}

# Known table names for activity samples across device types
_SAMPLE_TABLES = [
    "MI_BAND_ACTIVITY_SAMPLE",
    "HUAMI_EXTENDED_ACTIVITY_SAMPLE",
    "XIAOMI_ACTIVITY_SAMPLE",
    "PEBBLE_HEALTH_ACTIVITY_SAMPLE",
    "HPP_ACTIVITY_SAMPLE",
]


class GadgetbridgeProvider(BaseProvider):
    """Provider for Gadgetbridge local SQLite database export."""

    provider_name = "gadgetbridge"

    def __init__(self):
        self._db_path = None

    def authenticate(self, config: dict) -> bool:
        """Validate that the export file exists and is a valid SQLite DB."""
        export_path = config.get("export_path", "")
        if not export_path or not os.path.isfile(export_path):
            return False
        try:
            conn = sqlite3.connect(f"file:{export_path}?mode=ro", uri=True)
            conn.execute("SELECT 1")
            conn.close()
            self._db_path = export_path
            return True
        except sqlite3.Error:
            return False

    def test_connection(self, config: dict) -> bool:
        """Test the Gadgetbridge DB is readable and has expected tables."""
        if not self.authenticate(config):
            return False
        try:
            conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            conn.close()
            # At least one known sample table should exist
            return any(t in tables for t in _SAMPLE_TABLES)
        except sqlite3.Error:
            return False

    def get_supported_metrics(self) -> list[str]:
        return ["heart_rate", "steps", "blood_oxygen", "sleep"]

    def fetch_metrics(self, device_id: str, start_time: str = None,
                      end_time: str = None) -> list[RawMetric]:
        """Read activity samples from the Gadgetbridge SQLite export.

        Gadgetbridge stores timestamps as Unix epoch seconds in the TIMESTAMP column.
        """
        if not self._db_path:
            return []

        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        # Find which sample tables exist
        existing_tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]

        metrics = []

        # Determine time range as unix timestamps
        start_ts = None
        end_ts = None
        if start_time:
            try:
                start_ts = int(datetime.strptime(start_time[:19], "%Y-%m-%d %H:%M:%S").timestamp())
            except (ValueError, TypeError):
                pass
        if end_time:
            try:
                end_ts = int(datetime.strptime(end_time[:19], "%Y-%m-%d %H:%M:%S").timestamp())
            except (ValueError, TypeError):
                pass

        # Read from main activity sample table (MI_BAND / XIAOMI / etc.)
        for table in _SAMPLE_TABLES:
            if table not in existing_tables:
                continue

            # Check available columns
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}

            where_clauses = []
            params = []
            if start_ts is not None:
                where_clauses.append("TIMESTAMP >= ?")
                params.append(start_ts)
            if end_ts is not None:
                where_clauses.append("TIMESTAMP <= ?")
                params.append(end_ts)
            where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

            try:
                rows = conn.execute(f"SELECT * FROM {table}{where_sql} ORDER BY TIMESTAMP", params).fetchall()
            except sqlite3.Error:
                continue

            for row in rows:
                row_dict = dict(row)
                ts = row_dict.get("TIMESTAMP", 0)
                iso_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else None
                if not iso_time:
                    continue

                # Heart rate
                hr = row_dict.get("HEART_RATE", 0)
                if hr and hr > 0 and hr < 255:  # 255 = invalid/no reading in GB
                    metrics.append(RawMetric(
                        metric_type="heart_rate",
                        value=str(hr),
                        timestamp=iso_time,
                    ))

                # Steps (RAW_INTENSITY stores step count per sample interval)
                steps = row_dict.get("STEPS", row_dict.get("RAW_INTENSITY", 0))
                if steps and steps > 0:
                    metrics.append(RawMetric(
                        metric_type="steps_raw",
                        value=str(steps),
                        timestamp=iso_time,
                        extra={"raw_kind": row_dict.get("RAW_KIND", 0)},
                    ))

                # SpO2 (in extended tables)
                if "SPO2" in cols:
                    spo2 = row_dict.get("SPO2", 0)
                    if spo2 and 50 < spo2 <= 100:
                        metrics.append(RawMetric(
                            metric_type="blood_oxygen",
                            value=str(spo2),
                            timestamp=iso_time,
                        ))

                # Sleep detection via RAW_KIND
                raw_kind = row_dict.get("RAW_KIND", 0)
                if raw_kind in _ACTIVITY_TYPE_SLEEP:
                    metrics.append(RawMetric(
                        metric_type="sleep_raw",
                        value=_ACTIVITY_TYPE_SLEEP[raw_kind],
                        timestamp=iso_time,
                        extra={"raw_kind": raw_kind},
                    ))

        conn.close()
        return metrics
