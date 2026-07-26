"""Coverage for the domain-aware story CLI path."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "weight-manager" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import weight_truth_card


AS_OF = date(2026, 7, 24)
WINDOW_DAYS = 14
DOCUMENTED_KEYS = {
    "daily_records",
    "window_days",
    "span_days",
    "recorded_days",
    "measurement_count",
    "coverage_ratio",
    "trend_claim_allowed",
    "latest_date",
}
EVENT_DOMAINS = {"adherence", "family", "records"}


def _rows_for(domain: str, recorded_days: int) -> list[dict]:
    """Small valid row set in each adapter's own input shape."""
    rows = []
    for index in range(recorded_days):
        day = (AS_OF - timedelta(days=recorded_days - index - 1)).isoformat()
        if domain == "weight":
            rows.append({"date": day, "weight": 70.0 + index, "measurement_count": 1})
        elif domain == "sleep":
            rows.append({"date": day, "duration_min": 410 + index * 10})
        elif domain == "vitals":
            rows.append({"date": day, "metric_type": "heart_rate", "value": 68 + index})
        elif domain == "intake":
            rows.append({"meal_date": day, "total_calories": 1700 + index * 50})
        elif domain == "activity":
            rows.append({
                "date": day,
                "metric_type": "steps",
                "value": {"count": 6000 + index * 500},
                "source": "test-device",
            })
        elif domain == "family":
            rows.append({"date": day, "member_id": "member-a"})
        else:
            rows.append({"date": day})
    return rows


def _row_date(row: dict) -> str:
    return str(row.get("date") or row.get("meal_date") or "")[:10]


def _contains_numeric_zero(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, dict):
        return any(_contains_numeric_zero(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_numeric_zero(item) for item in value)
    return False


class DomainCliTests(unittest.TestCase):
    def test_demo_analysis_is_usable_for_every_domain(self):
        for domain in weight_truth_card.STORY_DOMAINS:
            with self.subTest(domain=domain):
                analysis = weight_truth_card._demo_domain_analysis(
                    domain, AS_OF, WINDOW_DAYS
                )
                self.assertGreaterEqual(analysis["recorded_days"], 1)
                self.assertGreaterEqual(
                    analysis["measurement_count"], analysis["recorded_days"]
                )
                self.assertRegex(analysis["latest_date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_shared_normalizer_returns_documented_keys(self):
        analysis = weight_truth_card._domain_analysis_from_rows(
            "records", _rows_for("records", 3), WINDOW_DAYS
        )
        self.assertTrue(DOCUMENTED_KEYS.issubset(analysis))

    def test_conclusion_threshold_matches_domain_shape(self):
        for domain in weight_truth_card.STORY_DOMAINS:
            with self.subTest(domain=domain, recorded_days=2):
                at_two = weight_truth_card._domain_analysis_from_rows(
                    domain, _rows_for(domain, 2), WINDOW_DAYS
                )
                self.assertEqual(
                    at_two["trend_claim_allowed"], domain in EVENT_DOMAINS
                )
            with self.subTest(domain=domain, recorded_days=3):
                at_three = weight_truth_card._domain_analysis_from_rows(
                    domain, _rows_for(domain, 3), WINDOW_DAYS
                )
                self.assertTrue(at_three["trend_claim_allowed"])

    def test_demo_gaps_are_absent_instead_of_zero_filled(self):
        for domain in weight_truth_card.STORY_DOMAINS:
            with self.subTest(domain=domain):
                analysis = weight_truth_card._demo_domain_analysis(
                    domain, AS_OF, WINDOW_DAYS
                )
                recorded_dates = {_row_date(row) for row in analysis["daily_records"]}
                self.assertLess(analysis["recorded_days"], analysis["window_days"])
                self.assertEqual(len(recorded_dates), analysis["recorded_days"])
                self.assertLess(len(recorded_dates), analysis["window_days"])
                self.assertFalse(
                    any(_contains_numeric_zero(row) for row in analysis["daily_records"])
                )

    def test_story_directories_preserve_weight_history(self):
        self.assertEqual(weight_truth_card._story_dir_for("weight"), "weight-stories")
        for domain in weight_truth_card.STORY_DOMAINS:
            if domain != "weight":
                with self.subTest(domain=domain):
                    self.assertEqual(
                        weight_truth_card._story_dir_for(domain), f"{domain}-stories"
                    )

    def test_multi_component_domain_narrates_whatever_was_recorded(self):
        """A window holding only one component must still be readable.

        Pinning a multi-component domain to its default component drops every
        other component's rows at the adapter boundary: someone who records only
        blood pressure gets `recorded_days: 0` from a window that is full of
        readings, and the card reports 记录不足 about data it was handed.

        The label has to travel with the pick.  Reading systolic values under
        心率 / 次/分 is the in-domain leak `adapters/vitals.py:_reading` refuses at
        the row level, so this asserts both halves: the component the rows are
        about, and the lexicon the renderer will print over them.
        """
        rows = [
            {
                "date": (AS_OF - timedelta(days=4 - index)).isoformat(),
                "metric_type": "blood_pressure",
                "value": json.dumps({"systolic": 118 + index, "diastolic": 78}),
            }
            for index in range(5)
        ]
        analysis = weight_truth_card._domain_analysis_from_rows("vitals", rows, WINDOW_DAYS)
        self.assertEqual(analysis["recorded_days"], 5)
        self.assertTrue(analysis["trend_claim_allowed"])
        lexicon = weight_truth_card.story_lexicon_for_analysis("vitals", analysis)
        self.assertEqual(lexicon["subject"], "收缩压")
        self.assertEqual(lexicon["unit"], "mmHg")

    def test_product_names_follow_each_domain_subject(self):
        for domain in weight_truth_card.STORY_DOMAINS:
            with self.subTest(domain=domain):
                subject = weight_truth_card.story_lexicon_for(domain)["subject"]
                self.assertEqual(
                    weight_truth_card.story_product_name_for(domain),
                    f"MediWise {subject}译报",
                )
        self.assertEqual(
            weight_truth_card.story_product_name_for("weight"), "MediWise 体重译报"
        )


if __name__ == "__main__":
    unittest.main()
