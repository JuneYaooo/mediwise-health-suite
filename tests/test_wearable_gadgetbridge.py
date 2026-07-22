from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "wearable-sync" / "scripts"))

from normalize import normalize_metrics
from providers.gadgetbridge import GadgetbridgeProvider


class GadgetbridgeProviderTests(unittest.TestCase):
    def test_overlapping_activity_tables_do_not_double_count(self):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "Gadgetbridge.db"
            conn = sqlite3.connect(path)
            conn.execute(
                """CREATE TABLE MI_BAND_ACTIVITY_SAMPLE (
                   TIMESTAMP INTEGER, STEPS INTEGER, RAW_INTENSITY INTEGER,
                   RAW_KIND INTEGER, HEART_RATE INTEGER)"""
            )
            conn.execute(
                """CREATE TABLE HUAMI_EXTENDED_ACTIVITY_SAMPLE (
                   TIMESTAMP INTEGER, STEPS INTEGER, RAW_INTENSITY INTEGER,
                   RAW_KIND INTEGER, HEART_RATE INTEGER, SPO2 INTEGER)"""
            )
            start = datetime(2026, 7, 21, 23, 0)
            rows = []
            for index in range(7):
                timestamp = int((start + timedelta(minutes=index * 5)).timestamp())
                rows.append((timestamp, 10, 1, 112, 60, 98))
            conn.executemany(
                "INSERT INTO MI_BAND_ACTIVITY_SAMPLE VALUES (?, ?, ?, ?, ?)",
                [row[:5] for row in rows],
            )
            conn.executemany(
                "INSERT INTO HUAMI_EXTENDED_ACTIVITY_SAMPLE VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
            conn.close()

            provider = GadgetbridgeProvider()
            config = {"export_path": str(path)}
            self.assertTrue(provider.authenticate(config))
            self.assertTrue(provider.test_connection(config))
            raw = provider.fetch_metrics("unused")
            normalized = normalize_metrics(raw, "gadgetbridge")

            heart_rates = [item for item in normalized if item["metric_type"] == "heart_rate"]
            steps = [item for item in normalized if item["metric_type"] == "steps"]
            sleep = [item for item in normalized if item["metric_type"] == "sleep"]
            oxygen = [item for item in normalized if item["metric_type"] == "blood_oxygen"]
            self.assertEqual(len(heart_rates), 7)
            self.assertEqual(json.loads(steps[0]["value"])["count"], 70)
            self.assertEqual(json.loads(sleep[0]["value"])["duration_min"], 30)
            self.assertEqual(len(oxygen), 7)


if __name__ == "__main__":
    unittest.main()
