"""The weight analysis core, tested where it now lives.

`robust_weight` moved out of `shared/` when the story layer came down, and the
only test that reached `robust_fit` directly went with that layer.  What it
pinned is worth keeping: the estimator's refusal to invent a line.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "weight-manager" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import robust_weight  # noqa: E402


class RobustFitTests(unittest.TestCase):
    def test_an_unfittable_series_returns_no_line_rather_than_a_flat_one(self):
        """A fabricated zero slope reads on the card as 长期持平.

        That is a claim about the body; an absent fit reads as 暂无稳健拟合, which
        is a statement about the records.  The two are not interchangeable, so the
        three inputs that support no slope must come back empty.
        """
        for name, points in {
            "nothing recorded": [],
            "one point": [{"date": "2026-07-20", "value": 60.0}],
            "both readings on one day": [
                {"date": "2026-07-20", "value": 60.0},
                {"date": "2026-07-20", "value": 72.0},
            ],
        }.items():
            with self.subTest(case=name):
                self.assertEqual(
                    robust_weight.robust_fit(points),
                    (None, None),
                    "%s: 造出了一条不存在的拟合线" % name,
                )

    def test_a_key_that_is_not_there_yields_no_fit_rather_than_a_wrong_one(self):
        """Reading the wrong column must come back empty, not silently fit anything.

        The card's rows carry `weight`; a caller that asks for `value` gets no
        line rather than a line drawn from whatever the rows happened to hold.
        """
        rows = [
            {"date": "2026-07-%02d" % day, "weight": 71.0 - day * 0.1}
            for day in range(1, 8)
        ]
        slope, _ = robust_weight.robust_fit(rows, value_key="weight")
        self.assertAlmostEqual(slope, -0.1, places=3)
        self.assertEqual(robust_weight.robust_fit(rows, value_key="value"), (None, None))


class ParseDateTests(unittest.TestCase):
    def test_every_spelling_a_host_writes_is_accepted(self):
        expected = robust_weight.parse_date("2026-07-09")
        self.assertEqual(str(expected), "2026-07-09")
        for spelling in ("2026-07-09T08:00:00", "2026-07-09 08:00:00", "2026-07-09T00:00:00Z"):
            with self.subTest(spelling=spelling):
                self.assertEqual(robust_weight.parse_date(spelling), expected)

    def test_unparseable_input_is_a_row_to_skip_not_a_failure(self):
        for value in (None, "", "   ", "not-a-date", 20260709):
            with self.subTest(value=value):
                self.assertIsNone(robust_weight.parse_date(value))


class StateForTests(unittest.TestCase):
    """The published thresholds: ±0.15 for the day-to-day move, ±0.2 for the trend."""

    def _states(self, daily, trend, sufficient=True):
        return robust_weight.state_for(daily, trend, sufficient)

    def test_insufficient_records_short_circuit_every_threshold(self):
        self.assertEqual(self._states(0.9, -0.9, sufficient=False), "insufficient")

    def test_the_daily_move_needs_to_clear_015_to_count_as_a_move(self):
        self.assertEqual(self._states(0.14, -0.6, True), "sustained_down")
        self.assertEqual(self._states(0.16, -0.6, True), "daily_up_trend_down")
        self.assertEqual(self._states(-0.16, 0.6, True), "daily_down_trend_up")

    def test_agreement_and_stability_are_told_apart(self):
        self.assertEqual(self._states(0.1, -0.6, True), "sustained_down")
        self.assertEqual(self._states(0.1, 0.6, True), "sustained_up")
        self.assertEqual(self._states(0.1, 0.1, True), "stable")
        self.assertEqual(self._states(0.2, 0.1, True), "daily_up_stable")
        self.assertEqual(self._states(-0.2, 0.1, True), "daily_down_stable")

    def test_opposed_directions_are_named_by_both_halves(self):
        self.assertEqual(self._states(0.3, -0.6, True), "daily_up_trend_down")
        self.assertEqual(self._states(-0.3, 0.6, True), "daily_down_trend_up")

    def test_an_absent_trend_is_insufficient_but_an_absent_daily_is_not(self):
        """No trend means no claim at all; no daily reading still leaves the trend.

        The asymmetry is the point: the trend is the fitted number this card
        exists to report, while a missing day-to-day move only means the last
        comparison could not be made.
        """
        self.assertEqual(self._states(0.3, None, True), "insufficient")
        self.assertEqual(self._states(None, -0.6, True), "sustained_down")


if __name__ == "__main__":
    unittest.main()
