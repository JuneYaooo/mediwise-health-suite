"""Locks the narrative contract in story-design/ before the shared/story extraction.

Two jobs:
  1. golden-file digests — the 24 weight templates must stay byte-for-byte identical
     while the engine moves out of weight-manager/ into a domain-neutral package;
  2. contract invariants — signal-frame.schema.json and story-system.md must stay in
     sync with each other and with the catalog the renderer actually ships.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
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
    STYLE_CONTENT_ROLES,
    available_story_styles,
    render_weight_story_html,
)
from weight_style_selector import select_weight_card_style

DESIGN_DIR = ROOT / "story-design"
SCHEMA_PATH = DESIGN_DIR / "signal-frame.schema.json"
CONTRACT_PATH = DESIGN_DIR / "story-system.md"
GOLDEN_PATH = ROOT / "tests" / "golden" / "weight_story_digests.json"

FIXTURE_START = date(2026, 6, 20)
FIXTURE_DAYS = 30
FIXTURE_AS_OF = date(2026, 7, 19)


def _base_analysis():
    values = [
        72.0 - index * 0.045 + (0.16 if index % 5 == 0 else 0.0)
        for index in range(FIXTURE_DAYS)
    ]
    records = [
        {
            "value": value,
            "measured_at": (FIXTURE_START + timedelta(days=index)).isoformat() + " 08:00:00",
        }
        for index, value in enumerate(values)
    ]
    return weight_truth_card.analyze_weight_records(records, days=FIXTURE_DAYS)


def _enriched_analysis():
    analysis = _base_analysis()
    diet, exercise, sleep = weight_truth_card._demo_management_records(
        FIXTURE_AS_OF, FIXTURE_DAYS
    )
    analysis["management"] = analyze_weight_management(
        analysis, diet, exercise, sleep, days=FIXTURE_DAYS, as_of=FIXTURE_AS_OF
    )
    return analysis


def _digest(analysis, style_id):
    selection = select_weight_card_style(
        analysis, scene="share", pinned_style=style_id, seed="render-" + style_id
    )
    rendered = render_weight_story_html(analysis, selection)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


class WeightStoryGoldenTests(unittest.TestCase):
    """Byte-for-byte lock. A diff here means the extraction changed user-visible output."""

    @classmethod
    def setUpClass(cls):
        cls.golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        cls.base = _base_analysis()
        cls.enriched = _enriched_analysis()

    def test_golden_file_covers_every_shipped_style(self):
        styles = set(available_story_styles())
        for fixture in ("redacted", "enriched"):
            self.assertEqual(set(self.golden[fixture]), styles, fixture)

    def test_redacted_render_matches_golden_digests(self):
        for style_id, expected in sorted(self.golden["redacted"].items()):
            self.assertEqual(_digest(self.base, style_id), expected, style_id)

    def test_enriched_render_matches_golden_digests(self):
        for style_id, expected in sorted(self.golden["enriched"].items()):
            self.assertEqual(_digest(self.enriched, style_id), expected, style_id)

    def test_render_is_deterministic_within_a_process(self):
        for style_id in available_story_styles():
            first = _digest(self.base, style_id)
            second = _digest(self.base, style_id)
            self.assertEqual(first, second, style_id)

    def test_companion_signals_change_every_template(self):
        """Lifestyle records must reach all 24 cards, not just the synthesis-led ones."""
        for style_id in available_story_styles():
            self.assertNotEqual(
                self.golden["redacted"][style_id],
                self.golden["enriched"][style_id],
                style_id,
            )


class SignalFrameSchemaTests(unittest.TestCase):
    SHAPES = {
        "insufficient",
        "today-vs-trend-conflict",
        "sustained-rise",
        "sustained-fall",
        "flat-with-noise",
        "stable",
        "rebuilding",
        "spotlight",
        "multi-signal",
    }
    PRIMITIVES = {"draw", "settle", "reveal", "breathe", "count", "trace"}

    @classmethod
    def setUpClass(cls):
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.props = cls.schema["properties"]
        cls.contract = CONTRACT_PATH.read_text(encoding="utf-8")

    def test_frame_carries_every_layer_the_renderer_consumes(self):
        for field in (
            "domain",
            "lexicon",
            "series",
            "shape",
            "trend",
            "coverage",
            "facts",
            "companions",
            "situation",
            "motion",
            "limits",
        ):
            self.assertIn(field, self.props, field)

    def test_shape_vocabulary_matches_the_written_contract(self):
        self.assertEqual(set(self.props["shape"]["enum"]), self.SHAPES)
        for shape in self.SHAPES:
            self.assertIn("`%s`" % shape, self.contract, shape)

    def test_motion_grammar_is_a_closed_set_of_six_primitives(self):
        primitives = self.props["motion"]["properties"]["primitives"]["items"]["enum"]
        self.assertEqual(set(primitives), self.PRIMITIVES)
        self.assertEqual(len(primitives), 6)
        for name in self.PRIMITIVES:
            self.assertIn("`%s`" % name, self.contract, name)

    def test_poster_frame_and_reduced_motion_are_required(self):
        motion = self.props["motion"]
        self.assertIn("poster_time_ms", motion["required"])
        self.assertIn("duration_ms", motion["required"])
        self.assertEqual(
            motion["properties"]["reduced_motion_fallback"]["const"], "poster"
        )

    def test_analysis_boundaries_are_pinned_by_const_not_convention(self):
        limits = self.props["limits"]["properties"]
        self.assertFalse(limits["causal_claim"]["const"])
        self.assertFalse(limits["prescription"]["const"])
        self.assertFalse(limits["unrecorded_is_zero"]["const"])
        self.assertFalse(limits["cross_domain_arithmetic"]["const"])
        self.assertFalse(
            self.props["social_packaging"]["properties"]["clickbait"]["const"]
        )
        for field in ("causal_claim", "prescription", "unrecorded_is_zero"):
            self.assertIn(field, self.props["limits"]["required"], field)

    def test_lexicon_covers_the_words_templates_must_not_hardcode(self):
        lexicon = self.props["lexicon"]
        for field in ("subject", "reading", "unit", "up", "down", "series_label", "scope_label"):
            self.assertIn(field, lexicon["required"], field)
            self.assertIn(field, lexicon["properties"], field)

    def test_every_domain_in_the_frame_is_also_valid_for_companions(self):
        domains = set(self.props["domain"]["enum"])
        companion = self.props["companions"]["items"]["properties"]["domain"]["enum"]
        self.assertEqual(set(companion), domains)
        self.assertIn("weight", domains)

    def test_frame_rejects_unknown_fields_so_domains_cannot_smuggle_state(self):
        self.assertFalse(self.schema["additionalProperties"])
        for field in ("lexicon", "trend", "coverage", "situation", "motion", "limits"):
            self.assertFalse(self.props[field]["additionalProperties"], field)

    def test_schema_validates_a_minimal_zero_data_frame(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is not installed")
        frame = {
            "domain": "sleep",
            "lexicon": {
                "subject": "睡眠",
                "reading": "记录时长",
                "unit": "分钟",
                "up": "变长",
                "down": "变短",
                "series_label": "每日记录时长",
                "scope_label": "有记录日",
            },
            "window": {"days": 14, "start": "2026-07-06", "end": "2026-07-19"},
            "series": [],
            "series_meta": {"fold": "mean", "relative_only": True},
            "shape": "insufficient",
            "trend": {"claim_allowed": False, "confidence": "insufficient"},
            "coverage": {"recorded_days": 0, "span_days": 14, "ratio": 0.0},
            "facts": [],
            "limits": {
                "causal_claim": False,
                "prescription": False,
                "unrecorded_is_zero": False,
                "non_causal_note": "相关线索不代表因果。",
            },
        }
        jsonschema.validate(frame, self.schema)

    def test_schema_rejects_a_frame_that_claims_causality(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is not installed")
        frame = {
            "domain": "weight",
            "lexicon": {
                "subject": "体重",
                "reading": "秤面",
                "unit": "kg",
                "up": "上浮",
                "down": "回落",
                "series_label": "每日中位数",
                "scope_label": "有记录日",
            },
            "window": {"days": 30, "start": "2026-06-20", "end": "2026-07-19"},
            "series": [{"date": "2026-06-20", "value": 72.0, "count": 1}],
            "series_meta": {"fold": "median", "relative_only": True},
            "shape": "sustained-fall",
            "trend": {"claim_allowed": True, "confidence": "high"},
            "coverage": {"recorded_days": 30, "span_days": 30, "ratio": 1.0},
            "facts": [],
            "limits": {
                "causal_claim": True,
                "prescription": False,
                "unrecorded_is_zero": False,
                "non_causal_note": "x",
            },
        }
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(frame, self.schema)


class CatalogInvariantTests(unittest.TestCase):
    """The structural invariants that replace the old 'exactly 24' assertion.

    story-system.md drops '恰好 24 套 / 恰好 12 家族' in favour of rules that keep
    holding as domains are added. These assertions must survive P1-P3 unchanged.
    """

    def test_template_count_is_even_and_never_shrinks(self):
        count = len(available_story_styles())
        self.assertGreaterEqual(count, 24)
        self.assertEqual(count % 2, 0)

    def test_every_family_ships_exactly_two_variants(self):
        families = {}
        for style in STYLE_CATALOG:
            families.setdefault(style.family, []).append(style.id)
        for family, members in sorted(families.items()):
            self.assertEqual(len(members), 2, "%s -> %s" % (family, members))

    def test_content_roles_and_layout_modes_stay_globally_unique(self):
        roles = [STYLE_CONTENT_ROLES[style.id] for style in STYLE_CATALOG]
        layouts = [style.layout_mode for style in STYLE_CATALOG]
        self.assertEqual(len(set(roles)), len(roles))
        self.assertEqual(len(set(layouts)), len(layouts))

    def test_every_template_declares_a_content_role(self):
        for style in STYLE_CATALOG:
            self.assertIn(style.id, STYLE_CONTENT_ROLES, style.id)

    def test_every_dominant_signal_has_at_least_one_template(self):
        signals = {
            style.preferred_domains[0]
            for style in STYLE_CATALOG
            if style.preferred_domains
        }
        for expected in ("weight", "intake", "activity", "sleep", "recording", "synthesis"):
            self.assertIn(expected, signals, expected)

    def test_at_least_one_template_survives_zero_data(self):
        zero_data = [style.id for style in STYLE_CATALOG if style.min_recorded_days <= 0]
        self.assertTrue(zero_data)
        self.assertIn("no-verdict", zero_data)

    def test_every_template_is_production_ready(self):
        self.assertEqual({style.renderer_status for style in STYLE_CATALOG}, {"production"})


class ShapeKeyedCopyTests(unittest.TestCase):
    """The copy tables are keyed on shape, and the legacy state surface is derived.

    Two things have to stay true for a new domain to be renderable without touching
    the copy tables at all: every shape in the schema enum must have core copy, and
    the renderer's private legacy-state translation must agree with the weight
    adapter's own SHAPE_BY_STATE. The renderer spells that table out locally rather
    than importing the adapter — the dependency must not point back at one domain —
    so this test is the only thing keeping the two from drifting apart.
    """

    @classmethod
    def setUpClass(cls):
        from shared.story import render as story_render
        from shared.story.adapters import weight as weight_adapter

        cls.render = story_render
        cls.adapter = weight_adapter
        cls.shapes = set(json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
                         ["properties"]["shape"]["enum"])

    def test_every_shape_in_the_schema_has_core_copy(self):
        self.assertEqual(set(self.render.CORE_SHAPE_COPY), self.shapes)
        for shape, value in self.render.CORE_SHAPE_COPY.items():
            title, status = value
            self.assertTrue(title.strip(), shape)
            self.assertTrue(status.strip(), shape)

    def test_legacy_state_table_agrees_with_the_weight_adapter(self):
        mine = {state: shape for state, (shape, _) in self.render._LEGACY_STATE_SHAPE.items()}
        self.assertEqual(mine, dict(self.adapter.SHAPE_BY_STATE))

    def test_legacy_state_shapes_are_all_real_shapes(self):
        for state, (shape, direction) in self.render._LEGACY_STATE_SHAPE.items():
            self.assertIn(shape, self.shapes, state)
            self.assertIn(direction, ("up", "down", None), state)

    def test_family_headlines_only_key_on_real_shapes(self):
        for family, table in self.render.FAMILY_SHAPE_HEADLINES.items():
            for shape, value in table.items():
                self.assertIn(shape, self.shapes, "%s/%s" % (family, shape))
                if isinstance(value, dict):
                    self.assertTrue(set(value) <= {"up", "down"}, "%s/%s" % (family, shape))

    def test_derived_legacy_tables_cover_every_legacy_state(self):
        self.assertEqual(set(self.render.CORE_STATE_COPY),
                         set(self.render._LEGACY_STATE_SHAPE))
        slots = {"{%s}" % name for name in self.render._COPY_SLOTS}
        for state, value in self.render.CORE_STATE_COPY.items():
            for text in value:
                # Derivation resolves `{today}` into the state's own direction slot —
                # which is what the table held before the re-key, so `{up}` / `{down}`
                # surviving here is the point. Only `{today}` must be gone: a state
                # knows its direction, so leaving the shape-layer token in place would
                # push the choice downstream to a `_fill` pass that cannot make it.
                self.assertNotIn("{today}", text, state)
                for token in re.findall(r"\{[a-z_]+\}", text):
                    self.assertIn(token, slots, "%s -> %s" % (state, token))

    def test_no_authored_copy_leaks_an_unfilled_slot(self):
        slots = {"{%s}" % name for name in self.render._COPY_SLOTS}
        for shape, value in self.render.CORE_SHAPE_COPY.items():
            for text in value:
                for token in re.findall(r"\{[a-z_]+\}", text):
                    self.assertIn(token, slots, "%s -> %s" % (shape, token))
        for family, table in self.render.FAMILY_SHAPE_HEADLINES.items():
            for shape, value in table.items():
                texts = list(value.values()) if isinstance(value, dict) else [value]
                for text in texts:
                    for token in re.findall(r"\{[a-z_]+\}", text):
                        self.assertIn(token, slots, "%s/%s -> %s" % (family, shape, token))

    def test_today_is_a_fillable_slot_so_conflict_copy_resolves(self):
        self.assertIn("today", self.render._COPY_SLOTS)

    def test_a_frame_shape_outranks_a_legacy_state_name(self):
        analysis = {"shape": "multi-signal", "state": "insufficient"}
        self.assertEqual(self.render._shape_of(analysis), "multi-signal")

    def test_an_unknown_shape_falls_back_to_the_only_safe_one(self):
        self.assertEqual(self.render._shape_of({"shape": "invented"}), "insufficient")
        self.assertEqual(self.render._shape_of({}), "insufficient")

    def test_direction_reads_the_delta_not_the_state_name(self):
        self.assertEqual(self.render._today_direction({"latest_delta": 0.4}), "up")
        self.assertEqual(self.render._today_direction({"latest_delta": -0.4}), "down")
        self.assertIsNone(self.render._today_direction({"latest_delta": 0}))
        self.assertIsNone(self.render._today_direction({}))
        # A bool is not a delta; True must not read as a rise.
        self.assertIsNone(self.render._today_direction({"latest_delta": True}))


class ContractDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = CONTRACT_PATH.read_text(encoding="utf-8")

    def test_contract_is_domain_neutral_about_its_subject(self):
        self.assertIn("体重不是这套系统的主题", self.contract)
        self.assertIn("signal-frame.schema.json", self.contract)

    def test_contract_keeps_animation_timeline_bound_to_calendar_time(self):
        self.assertIn("动画时间轴 = 日历时间轴", self.contract)
        self.assertIn("不插值", self.contract)

    def test_contract_names_the_compatibility_surface_that_must_not_break(self):
        for action in (
            "weight-truth",
            "generate-weight-card",
            "generate-weight-story-card",
            "select-weight-card-style",
            "weight-card-preferences",
            "update-weight-card-preferences",
        ):
            self.assertIn(action, self.contract, action)

    def test_contract_has_no_replacement_characters(self):
        self.assertNotIn("�", self.contract)
        self.assertNotIn("�", SCHEMA_PATH.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
