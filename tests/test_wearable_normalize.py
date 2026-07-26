"""Normalization tests for step data, where providers disagree about shape.

Two providers report a day's steps as a finished total (`steps`), two report intraday
samples to be summed (`steps_raw`), and one reports a finished total *under* the sample
name.  Each of the cases below is a shape that reached the database wrong.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "wearable-sync" / "scripts"))

from normalize import normalize_metrics
from providers.base import RawMetric


def _steps(normalized):
    return [item for item in normalized if item["metric_type"] == "steps"]


def _value(row):
    return json.loads(row["value"])


class DailyStepAggregationTests(unittest.TestCase):
    def test_provider_aggregated_day_keeps_its_own_totals(self):
        """Garmin's daily summary arrives as JSON under `steps_raw`.

        It used to be cast with `int(float(...))`, which raised; the day was already
        inserted into the defaultdict by then, so the row persisted as a confident
        `count: 0` -- a card could read it and report 「这天记录了 0 步」 for a day the
        watch had counted 8231.
        """
        raw = [RawMetric(
            metric_type="steps_raw",
            value=json.dumps({"count": 8231, "distance_m": 6120, "calories": 410}),
            timestamp="2026-07-20 23:59:00",
            extra={"aggregated": True},
        )]
        rows = _steps(normalize_metrics(raw, "garmin"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(_value(rows[0]), {"count": 8231, "distance_m": 6120, "calories": 410})

    def test_intraday_samples_are_summed_per_day(self):
        raw = [
            RawMetric(metric_type="steps_raw", value="10", timestamp="2026-07-20 08:00:00"),
            RawMetric(metric_type="steps_raw", value="25", timestamp="2026-07-20 09:00:00"),
            RawMetric(metric_type="steps_raw", value="40", timestamp="2026-07-21 08:00:00"),
        ]
        rows = _steps(normalize_metrics(raw, "apple_health"))
        self.assertEqual([_value(row)["count"] for row in rows], [35, 40])
        self.assertEqual([row["measured_at"] for row in rows],
                         ["2026-07-20 23:59:00", "2026-07-21 23:59:00"])

    def test_absent_distance_is_omitted_rather_than_zeroed(self):
        """A sum of step counts cannot produce a distance, so it must not claim one.

        Writing `distance_m: 0` here would be indistinguishable from a day the device
        measured as zero distance, and a reader has no way back from that.
        """
        raw = [RawMetric(metric_type="steps_raw", value="35", timestamp="2026-07-20 08:00:00")]
        payload = _value(_steps(normalize_metrics(raw, "apple_health"))[0])
        self.assertEqual(payload, {"count": 35})
        self.assertNotIn("distance_m", payload)
        self.assertNotIn("calories", payload)

    def test_provider_total_wins_over_samples_for_the_same_day(self):
        """The device's own arithmetic over the same samples, plus fields a sum lacks."""
        raw = [
            RawMetric(metric_type="steps_raw", value="10", timestamp="2026-07-20 08:00:00"),
            RawMetric(metric_type="steps_raw", value="25", timestamp="2026-07-20 09:00:00"),
            RawMetric(metric_type="steps_raw",
                      value=json.dumps({"count": 9000, "distance_m": 7000}),
                      timestamp="2026-07-20 23:59:00"),
        ]
        rows = _steps(normalize_metrics(raw, "garmin"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(_value(rows[0]), {"count": 9000, "distance_m": 7000})

    def test_unreadable_sample_does_not_fabricate_a_day(self):
        raw = [RawMetric(metric_type="steps_raw", value="n/a", timestamp="2026-07-22 08:00:00")]
        self.assertEqual(_steps(normalize_metrics(raw, "zepp")), [])


class FinishedStepRowTests(unittest.TestCase):
    def test_finished_step_rows_survive_normalization(self):
        """Zepp (`zepp.py:287`) and Huawei (`huawei.py:209`) emit `steps`, not `steps_raw`.

        That metric type matched no branch in `normalize_metrics`, so every step row from
        both providers was dropped between fetch and insert.
        """
        for provider in ("zepp", "huawei"):
            raw = [RawMetric(metric_type="steps", value=json.dumps({"count": 7345}),
                             timestamp="2026-07-19 23:59:00")]
            rows = _steps(normalize_metrics(raw, provider))
            self.assertEqual(len(rows), 1, provider)
            self.assertEqual(_value(rows[0])["count"], 7345)
            self.assertEqual(rows[0]["source"], provider)

    def test_finished_rows_are_not_folded_into_sampled_days(self):
        """A finished row and samples for one day must not be added together."""
        raw = [
            RawMetric(metric_type="steps", value=json.dumps({"count": 7345}),
                      timestamp="2026-07-19 23:59:00"),
            RawMetric(metric_type="steps_raw", value="120",
                      timestamp="2026-07-19 08:00:00"),
        ]
        counts = sorted(_value(row)["count"] for row in _steps(normalize_metrics(raw, "zepp")))
        self.assertEqual(counts, [120, 7345])


if __name__ == "__main__":
    unittest.main()
