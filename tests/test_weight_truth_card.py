from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "weight-manager" / "scripts"
HEALTH_SCRIPT_DIR = ROOT / "mediwise-health-tracker" / "scripts"
for item in (str(SCRIPT_DIR), str(HEALTH_SCRIPT_DIR)):
    if item not in sys.path:
        sys.path.insert(0, item)

import weight_truth_card


def records(values, start=date(2026, 7, 1)):
    return [
        {"value": value, "measured_at": (start + timedelta(days=index)).isoformat() + " 08:00:00"}
        for index, value in enumerate(values)
    ]


class WeightTruthAnalysisTests(unittest.TestCase):
    def test_same_day_measurements_use_median(self):
        daily = weight_truth_card.aggregate_daily_medians([
            {"value": 70.0, "measured_at": "2026-07-01 07:00:00"},
            {"value": 80.0, "measured_at": "2026-07-01 08:00:00"},
            {"value": 71.0, "measured_at": "2026-07-01 09:00:00"},
            {"value": 70.5, "measured_at": "2026-07-02 08:00:00"},
        ])

        self.assertEqual(len(daily), 2)
        self.assertEqual(daily[0]["weight"], 71.0)
        self.assertEqual(daily[0]["measurement_count"], 3)

    def test_theil_sen_resists_a_large_middle_outlier(self):
        daily = weight_truth_card.aggregate_daily_medians(
            records([70.0, 69.9, 69.8, 90.0, 69.6, 69.5, 69.4])
        )
        slope, _ = weight_truth_card.theil_sen_fit(daily)

        self.assertAlmostEqual(slope, -0.1, places=3)

    def test_single_day_spike_does_not_reverse_longer_trend(self):
        values = [71.0, 70.9, 70.8, 70.7, 70.6, 70.5, 70.4, 70.3, 70.2, 70.1, 70.0, 70.8]
        analysis = weight_truth_card.analyze_weight_records(records(values), days=14)

        self.assertEqual(analysis["state"], "daily_up_trend_down")
        self.assertGreater(analysis["daily_delta"], 0)
        self.assertLess(analysis["trend_delta"], 0)
        self.assertTrue(analysis["trend_claim_allowed"])

    def test_too_few_days_does_not_claim_direction(self):
        analysis = weight_truth_card.analyze_weight_records(records([70.0, 69.8, 69.7]), days=14)

        self.assertEqual(analysis["state"], "insufficient")
        self.assertIsNone(analysis["trend_delta"])
        self.assertIsNone(analysis["trend_direction"])
        self.assertFalse(analysis["trend_claim_allowed"])

        chart = weight_truth_card._chart_svg(analysis)
        self.assertIn("记录点尚未形成可判断的趋势", chart)
        self.assertNotIn("深海蓝线显示稳健趋势", chart)


class WeightTruthCardPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.analysis = weight_truth_card.analyze_weight_records(
            records([70.8, 70.7, 70.6, 70.5, 70.4, 70.3, 70.2, 70.1, 70.0, 69.9]),
            days=14,
        )

    def test_default_html_hides_identity_exact_weight_and_dates(self):
        rendered = weight_truth_card.render_card_html(
            self.analysis,
            member_name="林安",
            context_lines=["晚餐记录仅用于时间对齐"],
        )

        self.assertIn('data-share-safe="true"', rendered)
        self.assertIn("默认脱敏 · 可分享", rendered)
        self.assertNotIn("林安", rendered)
        self.assertNotIn("69.9 kg", rendered)
        self.assertNotIn("2026-07-10", rendered)
        self.assertIn(weight_truth_card.DISCLAIMER, rendered)

    def test_personal_fields_only_appear_after_explicit_opt_in(self):
        rendered = weight_truth_card.render_card_html(
            self.analysis,
            member_name="林安",
            show_exact_weight=True,
            show_member_name=True,
            show_exact_date=True,
        )

        self.assertIn('data-share-safe="false"', rendered)
        self.assertIn("林安", rendered)
        self.assertIn("当前 69.9 kg", rendered)
        self.assertIn("2026-07-10", rendered)

    def test_context_is_escaped_and_copy_is_non_prescriptive(self):
        rendered = weight_truth_card.render_card_html(
            self.analysis,
            context_lines=['<script>alert("x")</script>'],
        )

        self.assertNotIn('<script>alert("x")</script>', rendered)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", rendered)
        for phrase in ("建议少吃", "控制热量", "增加运动", "必须减重", "戒掉主食"):
            self.assertNotIn(phrase, rendered)

    def test_png_renderer_degrades_to_html_only_without_chrome(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "card.html"
            png_path = Path(temp_dir) / "card.png"
            html_path.write_text(weight_truth_card.render_card_html(self.analysis), encoding="utf-8")

            result = weight_truth_card.render_png_fixed(str(html_path), str(png_path), chrome_binary="")

            self.assertEqual(result["status"], "unavailable")
            self.assertFalse(png_path.exists())

    def test_png_is_fixed_canvas_when_chrome_is_available(self):
        chrome = weight_truth_card._find_chrome()
        if not chrome:
            self.skipTest("Chrome/Chromium is not installed")
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "card.html"
            png_path = Path(temp_dir) / "card.png"
            html_path.write_text(weight_truth_card.render_card_html(self.analysis), encoding="utf-8")

            result = weight_truth_card.render_png_fixed(str(html_path), str(png_path), chrome_binary=chrome)

            self.assertEqual(result["status"], "ok")
            self.assertEqual((result["width"], result["height"]), (1080, 1440))
            self.assertEqual(weight_truth_card._png_dimensions(str(png_path)), (1080, 1440))


if __name__ == "__main__":
    unittest.main()
