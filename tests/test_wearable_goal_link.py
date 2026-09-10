"""Wearable workout rows may update goals; ordinary metrics may not."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SYNC_DIR = ROOT / "wearable-sync" / "scripts"
if str(SYNC_DIR) not in sys.path:
    sys.path.insert(0, str(SYNC_DIR))

import sync as wearable_sync  # noqa: E402


class WearableGoalLinkTests(unittest.TestCase):
    def test_steps_never_become_an_activity_goal_candidate(self):
        metric = {
            "metric_type": "steps",
            "value": '{"count": 8000, "duration_min": 60}',
            "measured_at": "2026-08-01 23:59:00",
        }
        self.assertIsNone(wearable_sync._activity_goal_candidate("metric-steps", metric))

    def test_explicit_activity_uses_reported_duration_only(self):
        metric = {
            "metric_type": "activity",
            "value": '{"activity_type": "running", "duration_sec": 1800}',
            "measured_at": "2026-08-01 07:30:00",
        }
        candidate = wearable_sync._activity_goal_candidate("metric-activity", metric)
        self.assertEqual(candidate["id"], "metric-activity")
        self.assertEqual(candidate["duration_minutes"], 30)

        no_duration = dict(metric, value='{"activity_type": "running", "calories": 200}')
        self.assertIsNone(
            wearable_sync._activity_goal_candidate("metric-no-duration", no_duration)["duration_minutes"]
        )


if __name__ == "__main__":
    unittest.main()
