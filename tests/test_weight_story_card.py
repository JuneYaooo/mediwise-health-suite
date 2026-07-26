from __future__ import annotations

import sys
import tempfile
import unittest
import re
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "weight-manager" / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import weight_truth_card
from weight_card_styles import STYLE_CATALOG
from weight_management_analysis import analyze_weight_management
from weight_story_card import (
    CONTEXT_VISIBLE_STYLES,
    PRODUCT_NAME,
    available_story_styles,
    render_weight_story_html,
)
from weight_style_selector import select_weight_card_style


def long_analysis():
    start = date(2026, 6, 20)
    values = [72.0 - index * 0.045 + (0.16 if index % 5 == 0 else 0.0) for index in range(30)]
    records = [
        {"value": value, "measured_at": (start + timedelta(days=index)).isoformat() + " 08:00:00"}
        for index, value in enumerate(values)
    ]
    return weight_truth_card.analyze_weight_records(records, days=30)


class WeightStoryCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analysis = long_analysis()

    def test_all_catalog_styles_have_dynamic_renderers(self):
        style_count = len(STYLE_CATALOG)
        self.assertGreaterEqual(len(available_story_styles()), 24)
        self.assertEqual(len(available_story_styles()), style_count)
        self.assertEqual({style.renderer_status for style in STYLE_CATALOG}, {"production"})

        family_markup = set()
        content_roles = set()
        layout_modes = set()
        analysis_roles = set()
        metric_profiles = set()
        for style_id in available_story_styles():
            selection = select_weight_card_style(
                self.analysis,
                scene="share",
                pinned_style=style_id,
                seed="render-" + style_id,
            )
            rendered = render_weight_story_html(self.analysis, selection)
            family = selection["selected_style"]["family"]
            family_markup.add('class="artboard family-%s' % family)
            self.assertIn(PRODUCT_NAME, rendered, style_id)
            self.assertIn('data-style-id="%s"' % style_id, rendered, style_id)
            self.assertIn('data-renderer="weight-story-v2"', rendered, style_id)
            self.assertIn('data-share-safe="true"', rendered, style_id)
            self.assertIn(selection["selected_style"]["name"], rendered, style_id)
            self.assertIn(weight_truth_card.DISCLAIMER, rendered, style_id)
            self.assertNotIn("2026-07-19", rendered, style_id)
            self.assertNotIn("70.7 kg", rendered, style_id)
            role = re.search(r'data-content-role="([^"]+)"', rendered)
            self.assertIsNotNone(role, style_id)
            content_roles.add(role.group(1))
            layout = re.search(r'<main[^>]+data-layout-mode="([^"]+)"', rendered)
            self.assertIsNotNone(layout, style_id)
            layout_modes.add(layout.group(1))
            analysis_role = re.search(r'class="analysis-note analysis-([^"]+)"', rendered)
            self.assertIsNotNone(analysis_role, style_id)
            analysis_roles.add(analysis_role.group(1))
            metric_profiles.update(re.findall(r'data-metric-profile="([^"]+)"', rendered))

        self.assertEqual(len(family_markup), style_count // 2)
        self.assertEqual(len(content_roles), style_count)
        self.assertEqual(len(layout_modes), style_count)
        self.assertEqual(len(analysis_roles), style_count)
        self.assertGreaterEqual(len(metric_profiles), 10)

    def test_templates_make_different_editorial_choices_from_the_same_analysis(self):
        expected_copy = {
            "weather-week": "恢复气象带",
            "terrain-contour": "生成这张等高线",
            "editorial-headline": "没有单独改写整段时间",
            "film-grid": "不补造空白",
            "rhythm-calendar": "这里看的是节律",
            "passport-stamps": "观察印章",
            "weekly-single": "共同写进 liner notes",
            "observer-persona": "这是记录风格",
            "data-fingerprint": "唯一生成",
        }
        for style_id, phrase in expected_copy.items():
            selection = select_weight_card_style(
                self.analysis, scene="share", pinned_style=style_id, seed="editorial-" + style_id
            )
            rendered = render_weight_story_html(self.analysis, selection)
            self.assertIn(phrase, rendered, style_id)

    def test_explicit_personal_fields_remain_opt_in(self):
        for style_id in available_story_styles():
            selection = select_weight_card_style(
                self.analysis, pinned_style=style_id, seed="private-" + style_id
            )
            safe = render_weight_story_html(
                self.analysis, selection, member_name="林安", context_lines=['<script>alert("x")</script>']
            )
            private = render_weight_story_html(
                self.analysis,
                selection,
                member_name="林安",
                show_exact_weight=True,
                show_member_name=True,
                show_exact_date=True,
            )

            self.assertNotIn("林安", safe, style_id)
            self.assertNotIn('<script>alert("x")</script>', safe, style_id)
            if style_id in CONTEXT_VISIBLE_STYLES:
                self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", safe, style_id)
            else:
                self.assertNotIn("alert(&quot;x&quot;)", safe, style_id)
            self.assertIn('data-share-safe="false"', private, style_id)
            self.assertIn("林安", private, style_id)
            self.assertIn("当前 70.7 kg", private, style_id)
            self.assertIn("2026-07-19", private, style_id)

    def test_story_copy_keeps_professional_boundary(self):
        forbidden = ("必须减重", "建议少吃", "控制热量", "增加运动", "戒掉主食", "脂肪增加")
        for style_id in available_story_styles():
            selection = select_weight_card_style(
                self.analysis, pinned_style=style_id, seed="scope-" + style_id
            )
            rendered = render_weight_story_html(self.analysis, selection)
            for phrase in forbidden:
                self.assertNotIn(phrase, rendered, "%s contains %s" % (style_id, phrase))

    def test_enriched_card_leads_with_a_grounded_social_hook_and_save_reason(self):
        analysis = long_analysis()
        as_of = date(2026, 7, 19)
        diet, exercise, sleep = weight_truth_card._demo_management_records(as_of, 30)
        analysis["management"] = analyze_weight_management(
            analysis, diet, exercise, sleep, days=30, as_of=as_of
        )
        selection = select_weight_card_style(
            analysis, scene="share", pinned_style="weekly-single", seed="social-proof"
        )
        rendered = render_weight_story_html(analysis, selection)

        self.assertIn("阶段肖像", rendered)
        self.assertIn("后半场换挡", rendered)
        self.assertIn('data-situation-pattern="second-half-shift"', rendered)
        self.assertIn("保存这张，下一段 30 天回来和自己对照", rendered)
        moment_ids = [item["id"] for item in selection["story_moments"]]
        self.assertIn("four-signals", moment_ids)
        self.assertIn("second-half-shift", moment_ids)

    def test_story_card_exports_fixed_png_with_production_renderer(self):
        chrome = weight_truth_card._find_chrome()
        if not chrome:
            self.skipTest("Chrome/Chromium is not installed")
        selection = select_weight_card_style(
            self.analysis, pinned_style="weekly-single", seed="png-story"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "story.html"
            png_path = Path(temp_dir) / "story.png"
            html_path.write_text(
                render_weight_story_html(self.analysis, selection), encoding="utf-8"
            )

            result = weight_truth_card.render_png_fixed(
                str(html_path), str(png_path), chrome_binary=chrome
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual((result["width"], result["height"]), (1080, 1440))
            self.assertEqual(weight_truth_card._png_dimensions(str(png_path)), (1080, 1440))


if __name__ == "__main__":
    unittest.main()
