from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "weight-manager" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from weight_card_preferences import get_style_profile, update_style_profile


class WeightCardPreferenceTests(unittest.TestCase):
    def test_preferences_are_private_hashed_and_do_not_store_health_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "preferences.json"
            result = update_style_profile(
                "member-private-id",
                tone="playful",
                density="concise",
                surprise_level=0.8,
                like_styles=["weather-now"],
                dislike_styles=["editorial-cover"],
                pinned_style="weather-now",
                generated_style="direction-course",
                path=str(path),
            )

            raw = path.read_text(encoding="utf-8")
            stored = json.loads(raw)
            self.assertNotIn("member-private-id", raw)
            self.assertEqual(len(stored["members"]), 1)
            self.assertNotIn("weight", raw.lower())
            self.assertNotIn("bmi", raw.lower())
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertTrue(result["storage"]["member_id_hashed"])
            self.assertFalse(result["storage"]["health_values_stored"])

            profile = get_style_profile("member-private-id", str(path))
            self.assertEqual(profile["tone"], "playful")
            self.assertEqual(profile["preferred_styles"], ["weather-now"])
            self.assertEqual(profile["disliked_styles"], ["editorial-cover"])
            self.assertEqual(profile["recent_styles"], ["direction-course"])
            self.assertEqual(profile["generation_count"], 1)

    def test_like_dislike_and_neutral_are_mutually_consistent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "preferences.json")
            update_style_profile("member", like_styles=["weather-now"], path=path)
            update_style_profile("member", dislike_styles=["weather-now"], path=path)
            profile = get_style_profile("member", path)
            self.assertNotIn("weather-now", profile["preferred_styles"])
            self.assertIn("weather-now", profile["disliked_styles"])

            update_style_profile("member", neutral_styles=["weather-now"], path=path)
            profile = get_style_profile("member", path)
            self.assertNotIn("weather-now", profile["preferred_styles"])
            self.assertNotIn("weather-now", profile["disliked_styles"])

    def test_history_is_limited_and_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "preferences.json")
            styles = [
                "direction-course", "weather-now", "body-letter", "ticket-journey",
                "editorial-headline", "rhythm-calendar", "weekly-single",
            ]
            for style_id in styles:
                update_style_profile("member", generated_style=style_id, path=path)

            profile = get_style_profile("member", path)
            self.assertEqual(profile["recent_styles"], styles[-6:])
            self.assertEqual(profile["generation_count"], 7)

            update_style_profile("member", clear_history=True, path=path)
            profile = get_style_profile("member", path)
            self.assertEqual(profile["recent_styles"], [])
            self.assertEqual(profile["generation_count"], 0)

    def test_unknown_styles_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "unknown styles"):
                update_style_profile(
                    "member",
                    like_styles=["not-a-style"],
                    path=str(Path(temp_dir) / "preferences.json"),
                )


if __name__ == "__main__":
    unittest.main()
