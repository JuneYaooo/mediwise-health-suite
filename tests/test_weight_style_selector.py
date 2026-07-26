from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "weight-manager" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from weight_card_styles import STYLE_CATALOG
from weight_style_selector import detect_story_moments, select_weight_card_style


def analysis(**overrides):
    value = {
        "recorded_days": 12,
        "measurement_count": 12,
        "coverage_ratio": 0.86,
        "span_days": 14,
        "state": "daily_up_trend_down",
        "trend_claim_allowed": True,
        "daily_records": [
            {"date": "2026-07-11"},
            {"date": "2026-07-12"},
            {"date": "2026-07-24"},
        ],
    }
    value.update(overrides)
    return value


class WeightStyleCatalogTests(unittest.TestCase):
    def test_catalog_has_paired_real_families_and_at_least_twenty_four_variants(self):
        families = {}
        for style in STYLE_CATALOG:
            families.setdefault(style.family, []).append(style.id)

        self.assertGreaterEqual(len(STYLE_CATALOG), 24)
        self.assertEqual(len(STYLE_CATALOG) % 2, 0)
        self.assertEqual(len(families), len(STYLE_CATALOG) // 2)
        self.assertTrue(all(len(styles) == 2 for styles in families.values()))
        self.assertEqual(
            [style.id for style in STYLE_CATALOG if style.renderer_status == "production"],
            [style.id for style in STYLE_CATALOG],
        )


class WeightStyleSelectorTests(unittest.TestCase):
    def test_insufficient_data_excludes_trend_dependent_styles(self):
        result = select_weight_card_style(
            analysis(
                recorded_days=2,
                measurement_count=2,
                coverage_ratio=0.14,
                span_days=2,
                state="insufficient",
                trend_claim_allowed=False,
            ),
            seed="few-days",
        )

        self.assertNotIn("terrain-contour", result["eligible_styles"])
        self.assertNotIn("data-fingerprint", result["eligible_styles"])
        self.assertFalse(result["eligibility"]["terrain-contour"]["eligible"])
        self.assertIn("no-verdict", result["eligible_styles"])
        self.assertEqual(result["story_moments"][0]["id"], "prologue")

    def test_pinned_eligible_style_wins_without_randomness(self):
        result = select_weight_card_style(
            analysis(),
            pinned_style="editorial-cover",
            seed="ignored-by-pin",
        )

        self.assertEqual(result["selected_style"]["id"], "editorial-cover")
        self.assertEqual(result["probabilities"]["editorial-cover"], 1.0)
        self.assertFalse(result["exploration"])

    def test_no_verdict_is_auto_only_until_a_robust_direction_exists(self):
        sufficient = analysis(trend_delta=-0.8)
        automatic = select_weight_card_style(sufficient, seed="has-a-fit")
        self.assertNotIn("no-verdict", automatic["eligible_styles"])
        self.assertEqual(
            automatic["eligibility"]["no-verdict"]["disabled_reason"],
            "已有可陈述的稳健方向",
        )

        pinned = select_weight_card_style(
            sufficient, pinned_style="no-verdict", seed="explicit-design-request"
        )
        self.assertEqual(pinned["selected_style"]["id"], "no-verdict")

    def test_ineligible_pin_returns_an_explicit_error(self):
        with self.assertRaisesRegex(ValueError, "not eligible"):
            select_weight_card_style(
                analysis(recorded_days=2, trend_claim_allowed=False),
                pinned_style="terrain-contour",
            )

    def test_dislike_and_recent_history_lower_probability(self):
        baseline = select_weight_card_style(analysis(), scene="share", seed="same")
        adjusted = select_weight_card_style(
            analysis(),
            scene="share",
            disliked_styles=["direction-course"],
            recent_styles=["direction-course", "weather-now", "direction-course"],
            seed="same",
        )

        self.assertLess(
            adjusted["probabilities"]["direction-course"],
            baseline["probabilities"]["direction-course"] * 0.2,
        )

    def test_probabilities_are_non_uniform_and_sum_to_one(self):
        result = select_weight_card_style(analysis(), scene="share", seed="distribution")
        probabilities = list(result["probabilities"].values())

        self.assertAlmostEqual(sum(probabilities), 1.0, places=7)
        self.assertGreater(max(probabilities), min(probabilities) * 2)
        self.assertTrue(result["selection_policy"]["non_uniform"])
        self.assertGreaterEqual(result["exploration_rate"], 0.08)

    def test_same_seed_is_reproducible(self):
        first = select_weight_card_style(analysis(), scene="weekly", seed="repeatable")
        second = select_weight_card_style(analysis(), scene="weekly", seed="repeatable")

        self.assertEqual(first["selected_style"]["id"], second["selected_style"]["id"])
        self.assertEqual(first["visual_signature"], second["visual_signature"])
        self.assertEqual(first["probabilities"], second["probabilities"])

    def test_forbidden_health_traits_do_not_change_aesthetic_selection(self):
        clean = analysis()
        profiled = analysis(
            bmi=38.2,
            sex="female",
            age=72,
            diagnosis="example diagnosis",
            medication="example medication",
            target_weight=50,
        )
        first = select_weight_card_style(clean, scene="share", seed="privacy-boundary")
        second = select_weight_card_style(profiled, scene="share", seed="privacy-boundary")

        self.assertEqual(first["selected_style"]["id"], second["selected_style"]["id"])
        self.assertEqual(first["probabilities"], second["probabilities"])
        self.assertEqual(first["selection_policy"]["health_traits_used_for_aesthetics"], [])

    def test_fun_moments_reward_observation_without_judging_weight(self):
        moments = detect_story_moments(
            analysis(
                measurement_count=18,
                span_days=35,
                state="stable",
                daily_records=[{"date": "2026-06-01"}, {"date": "2026-06-12"}, {"date": "2026-07-05"}],
            )
        )
        moment_ids = {item["id"] for item in moments}

        self.assertIn("double-exposure", moment_ids)
        self.assertIn("long-view", moment_ids)
        self.assertIn("welcome-back", moment_ids)
        copy = " ".join(item["label"] + item["share_line"] for item in moments)
        for forbidden in ("成功", "失败", "胖", "瘦", "BMI"):
            self.assertNotIn(forbidden, copy)


if __name__ == "__main__":
    unittest.main()
