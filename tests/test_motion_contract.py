"""Locks the motion layer and SVG export against story-design/story-system.md.

The rules under test are the ones that silently rot if nobody asserts them:
calendar-mapped beats, a poster frame that reproduces the static composition,
determinism per seed, reduced-motion degrading to the frozen frame, and motion
not becoming a new privacy leak.
"""

from __future__ import annotations

import hashlib
import re
import sys
import unittest
import xml.dom.minidom
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.story import motion, svg
from shared.story.catalog import STYLE_CATALOG, STYLES_BY_ID

DESIGN_DIR = ROOT / "story-design"
CONTRACT_PATH = DESIGN_DIR / "story-system.md"


class _Index:
    """A minimal element index over a rendered card, with ancestor paths.

    Enough of a DOM to answer the only question the motion contract asks: could
    this selector reach an element the viewer actually sees. Paths are kept so a
    descendant chain can be checked properly, and the document's own <style> text
    is captured so `display:none` can be read off the card instead of hardcoded.

    Parsed with minidom rather than by hand: the exported document is valid XML
    (test_void_elements_are_self_closed_for_xml_parsing pins that), and a
    hand-rolled tag walker has to special-case self-closing tags or it pops the
    wrong ancestor and silently corrupts the paths of everything after the first
    `<path/>` — which reads as a dead target that isn't one.
    """

    def __init__(self, document):
        self.elements = []  # (tag, classes, path-of-ids-including-self)
        self.css = []
        self.layout = ""
        root = xml.dom.minidom.parseString(document).documentElement
        self._walk(root, ())

    def _walk(self, node, path):
        tag = node.tagName.split(":")[-1]  # `svg:foreignObject` -> `foreignObject`
        element_id = len(self.elements)
        path = path + (element_id,)
        self.elements.append((tag, (node.getAttribute("class") or "").split(), path))
        # Read the layout mode off the artboard attribute. Scraping it out of the
        # document text instead would hit the first `[data-layout-mode="..."]`
        # inside the embedded CSS and misreport every card as that one layout.
        mode = node.getAttribute("data-layout-mode")
        if mode:
            self.layout = mode
        for child in node.childNodes:
            if child.nodeType == child.ELEMENT_NODE:
                self._walk(child, path)
            elif tag == "style" and child.nodeType in (child.TEXT_NODE, child.CDATA_SECTION_NODE):
                self.css.append(child.data)


def _part_matches(tag, classes, part):
    part = re.sub(r":[a-z-]+(\([^)]*\))?", "", part)  # `i:not(.on)` -> `i`
    if not part or part == "*":
        return True
    if part.startswith("."):
        return part[1:] in classes
    return tag == part


def _matching(index, selector):
    """Elements a descendant selector could reach, ignoring visibility."""
    parts = selector.strip().split()
    if not parts:
        return []
    hits = []
    by_id = {path[-1]: (tag, classes) for tag, classes, path in index.elements}
    for tag, classes, path in index.elements:
        if not _part_matches(tag, classes, parts[-1]):
            continue
        # Ancestors must contain the remaining parts in order.
        remaining = list(parts[:-1])
        for ancestor in path[:-1]:
            if not remaining:
                break
            a_tag, a_classes = by_id[ancestor]
            if _part_matches(a_tag, a_classes, remaining[0]):
                remaining.pop(0)
        if not remaining:
            hits.append((tag, classes, path))
    return hits


def _hidden_ids(index, layout_mode):
    """Element ids a `display:none` rule in the card's own CSS switches off.

    Derived from the rendered stylesheet rather than a hardcoded list, so a new
    layout that hides a region is caught the first time it is rendered.
    """
    hidden = set()
    css = "".join(index.css)
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors, body = rule.group(1), rule.group(2)
        if "display:none" not in body.replace(" ", ""):
            continue
        for selector in selectors.split(","):
            selector = selector.strip()
            scope = re.search(r'\[data-layout-mode="([^"]+)"\]', selector)
            if scope and scope.group(1) != layout_mode:
                continue  # rule belongs to a different layout mode
            selector = re.sub(r"\[[^\]]*\]", "", selector).strip()
            if not selector:
                continue
            for _tag, _classes, path in _matching(index, selector):
                hidden.add(path[-1])
    return hidden


def _visible_matches(index, hidden, selector):
    """Elements the selector reaches that no ancestor hides."""
    return [hit for hit in _matching(index, selector) if not (set(hit[2]) & hidden)]


def _selector_matches(markup, selector):
    """Whether a rendered card contains an element the selector could match.

    Every part of a descendant chain must be present, not just the leaf: `li` and
    `div` occur in almost every layout, so a leaf-only check would let a selector
    like `.tracklist li` claim a match in a card that has no tracklist and mask a
    genuinely dead act.
    """
    for part in selector.strip().split():
        if part.startswith("."):
            found = re.search(r'class="[^"]*\b%s\b' % re.escape(part[1:]), markup)
        else:
            found = re.search(r"<%s[ >]" % re.escape(part), markup)
        if not found:
            return False
    return True


def _series(days, start="2026-07-01"):
    year, month, day = (int(part) for part in start.split("-"))
    from datetime import date, timedelta

    origin = date(year, month, day)
    return [
        {
            "date": (origin + timedelta(days=offset)).isoformat(),
            "weight": 72.0 - offset * 0.1,
            "count": 1,
        }
        for offset in range(days)
    ]


def _analysis(days=12):
    return {
        "state": "sustained_down",
        "trend_claim_allowed": True,
        "trend_delta": -1.2,
        "recorded_days": days,
        "measurement_count": days + 2,
        "span_days": 14,
        "coverage_ratio": round(days / 14.0, 2),
        "daily_records": _series(days),
    }


def _selection(style_id, seed="contract-seed"):
    return {
        "selected_style": STYLES_BY_ID[style_id].public_dict(),
        "visual_signature": {"texture_seed": seed, "palette_variant": 2},
        "story_moments": [],
        "observer_persona": {},
    }


class MotionCatalogTests(unittest.TestCase):
    def test_every_template_declares_a_unique_motion_mode(self):
        modes = [style.motion_mode for style in STYLE_CATALOG]
        self.assertTrue(all(modes), "a template is missing motion_mode")
        self.assertEqual(len(set(modes)), len(modes))

    def test_motion_modes_cover_the_catalog_exactly(self):
        self.assertEqual(set(motion.STYLE_MOTION_MODES), set(STYLES_BY_ID))

    def test_every_mode_declares_primitives_from_the_closed_set(self):
        for mode, primitives in motion.MODE_PRIMITIVES.items():
            self.assertTrue(primitives, mode)
            for primitive in primitives:
                self.assertIn(primitive, motion.MOTION_PRIMITIVES, "%s/%s" % (mode, primitive))

    def test_primitive_vocabulary_stays_closed(self):
        self.assertEqual(
            motion.MOTION_PRIMITIVES,
            ("draw", "settle", "reveal", "breathe", "count", "trace"),
        )

    def test_every_mode_has_a_primitive_table_entry(self):
        for mode in motion.STYLE_MOTION_MODES.values():
            self.assertIn(mode, motion.MODE_PRIMITIVES, mode)


class CalendarTimelineTests(unittest.TestCase):
    """动画时间轴 = 日历时间轴: gaps cost real silence and are never interpolated."""

    def test_a_gap_costs_more_time_than_a_consecutive_day(self):
        gapped = [
            {"date": "2026-07-01"},
            {"date": "2026-07-02"},
            {"date": "2026-07-09"},
        ]
        beats = motion.compile_beats(gapped, tempo=2.0, stagger_ms=0, exact_dates=True)
        first_step = beats[1]["at_ms"] - beats[0]["at_ms"]
        gap_step = beats[2]["at_ms"] - beats[1]["at_ms"]
        self.assertGreater(gap_step, first_step)

    def test_gap_beats_are_labelled_with_their_bucket(self):
        beats = motion.compile_beats(
            [{"date": "2026-07-01"}, {"date": "2026-07-09"}],
            tempo=2.0, stagger_ms=0, exact_dates=True,
        )
        self.assertEqual(beats[1]["gap_bucket"], "long")
        self.assertEqual(beats[1]["gap_days"], 7)

    def test_no_recorded_day_is_ever_dropped(self):
        series = _series(60)
        frame = motion.compile_motion("rhythm-calendar", seed="s", series=series)
        self.assertEqual(len(frame["beats"]), min(len(series), motion.MAX_BEATS))

    def test_beats_stay_inside_the_evidence_act(self):
        frame = motion.compile_motion("rhythm-calendar", seed="s", series=_series(40))
        evidence = next(act for act in frame["acts"] if act["act"] == "evidence")
        self.assertGreaterEqual(frame["beats"][0]["at_ms"], evidence["start_ms"])
        self.assertLessEqual(frame["beats"][-1]["at_ms"], evidence["end_ms"] + 1)

    def test_acts_run_in_order_and_tile_the_loop(self):
        frame = motion.compile_motion("weather-now", seed="s", series=_series(9))
        acts = frame["acts"]
        self.assertEqual([act["act"] for act in acts], ["claim", "evidence", "analysis", "closing"])
        self.assertEqual(acts[0]["start_ms"], 0)
        self.assertEqual(acts[-1]["end_ms"], frame["duration_ms"])
        for earlier, later in zip(acts, acts[1:]):
            self.assertEqual(earlier["end_ms"], later["start_ms"])


class MotionPrivacyTests(unittest.TestCase):
    """Motion is a leakage channel; redacted cards must not encode exact dates."""

    def test_redacted_cards_quantize_gaps_instead_of_exposing_day_counts(self):
        frame = motion.compile_motion(
            "rhythm-calendar", seed="s", series=[{"date": "2026-07-01"}, {"date": "2026-07-19"}],
            exact_dates=False,
        )
        self.assertEqual(frame["gap_precision"], "bucketed")
        for beat in frame["beats"]:
            self.assertNotIn("gap_days", beat)

    def test_two_different_gaps_in_the_same_bucket_are_indistinguishable(self):
        short = motion.compile_motion(
            "rhythm-calendar", seed="s",
            series=[{"date": "2026-07-01"}, {"date": "2026-07-06"}],
        )
        longer = motion.compile_motion(
            "rhythm-calendar", seed="s",
            series=[{"date": "2026-07-01"}, {"date": "2026-07-20"}],
        )
        self.assertEqual(
            [beat["at_ms"] for beat in short["beats"]],
            [beat["at_ms"] for beat in longer["beats"]],
        )

    def test_opting_into_exact_dates_is_the_only_way_to_get_exact_beats(self):
        frame = motion.compile_motion(
            "rhythm-calendar", seed="s",
            series=[{"date": "2026-07-01"}, {"date": "2026-07-09"}],
            exact_dates=True,
        )
        self.assertEqual(frame["gap_precision"], "exact")
        self.assertEqual(frame["beats"][1]["gap_days"], 7)


class MotionSafetyTests(unittest.TestCase):
    def test_flicker_never_reaches_the_three_hertz_ceiling(self):
        self.assertLessEqual(motion.MAX_FLICKER_HZ, 3.0)
        for style in STYLE_CATALOG:
            frame = motion.compile_motion(style.id, seed=style.id, series=_series(12))
            self.assertLessEqual(frame["flicker_hz_max"], 3.0, style.id)

    def test_reduced_motion_degrades_to_the_poster_frame_not_a_slow_loop(self):
        frame = motion.compile_motion(
            "constellation", seed="s", series=_series(12), reduced_motion=True
        )
        self.assertTrue(frame["reduced_motion"])
        self.assertEqual(frame["beats"], [])
        self.assertEqual(frame["primitives"], ["reveal"])

    def test_durations_and_tempo_stay_inside_the_schema_window(self):
        for style in STYLE_CATALOG:
            for days in (0, 1, 7, 30, 60):
                frame = motion.compile_motion(style.id, seed=style.id, series=_series(days))
                self.assertGreaterEqual(frame["duration_ms"], motion.DURATION_BOUNDS[0])
                self.assertLessEqual(frame["duration_ms"], motion.DURATION_BOUNDS[1])
                if not frame["reduced_motion"]:
                    self.assertGreaterEqual(frame["tempo"], motion.TEMPO_BOUNDS[0])
                    self.assertLessEqual(frame["tempo"], motion.TEMPO_BOUNDS[1])


class ZeroDataMotionTests(unittest.TestCase):
    def test_a_zero_data_card_still_moves_something(self):
        frame = motion.compile_motion("no-verdict", seed="s", series=[])
        self.assertTrue(frame["primitives"])
        self.assertFalse(frame["calendar_mapped"])

    def test_a_zero_data_card_never_animates_absent_evidence(self):
        frame = motion.compile_motion("no-verdict", seed="s", series=[])
        for primitive in frame["primitives"]:
            self.assertNotIn(primitive, motion.SERIES_PRIMITIVES, primitive)


class DeterminismTests(unittest.TestCase):
    def test_same_seed_and_data_yield_an_identical_timeline(self):
        first = motion.compile_motion("constellation", seed="fixed", series=_series(12))
        second = motion.compile_motion("constellation", seed="fixed", series=_series(12))
        self.assertEqual(first, second)

    def test_different_seeds_yield_different_timelines(self):
        variants = {
            motion.compile_motion("constellation", seed="seed-%d" % index, series=_series(12))[
                "motion_variant"
            ]
            for index in range(24)
        }
        self.assertGreater(len(variants), 1)


class SvgExportTests(unittest.TestCase):
    def test_every_template_exports_well_formed_animated_and_frozen_svg(self):
        analysis = _analysis()
        for style in STYLE_CATALOG:
            selection = _selection(style.id)
            for freeze in (False, True):
                document = svg.render_story_svg(analysis, selection, freeze=freeze)
                xml.dom.minidom.parseString(document)
                self.assertIn('data-renderer="story-svg-v1"', document)
                self.assertIn("<foreignObject", document)

    def test_same_seed_svg_is_byte_identical(self):
        analysis = _analysis()
        selection = _selection("constellation")
        first = svg.render_story_svg(analysis, selection)
        second = svg.render_story_svg(analysis, selection)
        self.assertEqual(
            hashlib.sha256(first.encode("utf-8")).hexdigest(),
            hashlib.sha256(second.encode("utf-8")).hexdigest(),
        )

    def test_frozen_export_stops_all_motion_and_gates_on_ready(self):
        """Assert that nothing moves, not the mechanism that stops it.

        The freeze path removes the animations rather than seeking and pausing them,
        because a paused `translate` still promotes a compositing layer and shifts
        text antialiasing away from the static card. Asserting on
        `animation-play-state:paused` pinned the old mechanism, so it failed on a
        change that made the poster frame strictly more faithful. What matters is
        that no CSS animation is left running and the capture still gates on
        `window.__ready`.
        """
        document = svg.render_story_svg(_analysis(), _selection("weekly-single"), freeze=True)
        self.assertIn("pauseAnimations", document)  # SMIL, which the CSS cannot reach
        self.assertIn("window.__ready", document)
        self.assertIn('data-freeze="true"', document)
        self.assertIn("animation:none !important", document)
        # The blanket rule only wins because nothing it has to override is itself
        # `!important`. An act rule that ever became `!important` would keep playing
        # through the freeze and desynchronize the poster frame from the static card,
        # so the cascade assumption is checked rather than trusted.
        index = _Index(document)
        for _, body in re.findall(r"([^{}]+)\{([^{}]*)\}", "".join(index.css)):
            if re.search(r"animation:\s*ms-[a-z]+", body):
                self.assertNotIn("!important", body)

    def test_animated_export_respects_prefers_reduced_motion(self):
        document = svg.render_story_svg(_analysis(), _selection("weekly-single"))
        self.assertIn("prefers-reduced-motion:reduce", document)
        self.assertIn('data-freeze="false"', document)

    def test_poster_time_lands_after_every_act_has_played(self):
        for style in STYLE_CATALOG:
            frame = motion.compile_motion(style.id, seed=style.id, series=_series(12))
            self.assertGreaterEqual(frame["poster_time_ms"], frame["duration_ms"], style.id)

    def test_poster_frame_carries_the_same_composition_as_the_static_card(self):
        from shared.story.render import render_weight_story_html

        analysis, selection = _analysis(), _selection("editorial-cover")
        html = render_weight_story_html(analysis, selection)
        frozen = svg.render_story_svg(analysis, selection, freeze=True)
        # The analysis paragraph, situation portrait, and save reason must all be
        # present in the poster frame, since it is the same markup.  Prefix match:
        # layouts append their own variant class after the shared one.
        for marker in ('class="analysis-note', 'class="social-hook', "<footer>"):
            self.assertIn(marker, html, marker)
            self.assertIn(marker, frozen, marker)

    def _coverage_report(self, style_id, selectors):
        """(visible hits, hits hidden by the card's own CSS) for a target set."""
        document = svg.render_story_svg(_analysis(), _selection(style_id))
        index = _Index(document)
        hidden = _hidden_ids(index, index.layout)
        visible = sum(len(_visible_matches(index, hidden, s)) for s in selectors)
        in_markup = sum(len(_matching(index, s)) for s in selectors)
        return visible, in_markup - visible

    def _assert_covered(self, style_id, label, selectors):
        visible, hidden = self._coverage_report(style_id, selectors)
        self.assertTrue(
            visible,
            "%s has no *visible* target for %s%s"
            % (
                style_id,
                label,
                " (%d matched but a display:none rule hides them)" % hidden if hidden else "",
            ),
        )

    def test_every_act_finds_a_visible_target_in_every_template(self):
        """No act may play to an empty or hidden selector.

        A layout whose evidence is a sentence rather than a metric grid would
        otherwise hold one frame for a whole act, which reads as a broken card.
        Hidden counts as empty: five families replace `.hero` with a printed object
        of their own via `display:none`, so a selector that matches markup can still
        animate nothing the viewer sees. Visibility is read off the card's own
        stylesheet, which is what makes a new domain's layouts safe to add — bring a
        new class vocabulary, or hide an existing one, and this fails until the act
        map covers it.
        """
        required = {
            "claim": tuple(svg.CLAIM_SELECTOR.split(",")),
            "evidence": tuple(svg.EVIDENCE_SELECTOR.split(",")),
            "analysis": (".analysis-note",),
            "closing": tuple(svg.CLOSING_SELECTOR.split(",")),
        }
        for style in STYLE_CATALOG:
            for act, selectors in required.items():
                self._assert_covered(style.id, "act %s" % act, selectors)

    def test_claim_body_is_opportunistic_but_present_where_hero_survives(self):
        """`.hero p` is 立论's second wave, not a fifth act.

        Only the layouts that keep `.hero` have a body paragraph to stagger under
        the headline. Where `.hero` survives it must be reachable; where the family
        replaces it, the single claim wave is the whole opening — and that case is
        already covered by the act test above.
        """
        staggered = 0
        for style in STYLE_CATALOG:
            hero, _ = self._coverage_report(style.id, (".hero h1",))
            body, _ = self._coverage_report(style.id, (".hero p",))
            if hero:
                self.assertTrue(body, "%s shows .hero but has no .hero p" % style.id)
                staggered += 1
        self.assertGreater(staggered, 0)

    def test_every_declared_primitive_finds_a_visible_target(self):
        """A mode may not promise motion its layout cannot show."""
        targets = {
            "settle": svg.SETTLE_TARGETS,
            "draw": svg.DRAW_TARGETS,
            "trace": svg.TRACE_TARGETS,
            "breathe": tuple(
                part.replace("#artboard ", "") for part in svg.BREATHE_SELECTOR.split(",")
            ),
            "reveal": tuple(svg.CLAIM_SELECTOR.split(",")),
            "count": tuple(svg.COUNT_SELECTOR.split(",")),
        }
        for style in STYLE_CATALOG:
            frame = motion.compile_motion(style.id, seed=style.id, series=_series(12))
            for primitive in frame["primitives"]:
                self._assert_covered(
                    style.id, "declared primitive %s" % primitive, targets[primitive]
                )

    def test_settle_targets_are_disjoint_from_other_primitives(self):
        """A per-day slot may not also be a whole-set target.

        `_beat_css` emits an `nth-child` rule per beat, which outranks a whole-set
        rule on the same element — so an element in both SETTLE_TARGETS and
        DRAW/TRACE_TARGETS would silently drop the second primitive while the mode
        still advertises it.
        """
        settle = set(svg.SETTLE_TARGETS)
        for name, other in (("draw", svg.DRAW_TARGETS), ("trace", svg.TRACE_TARGETS)):
            overlap = settle & set(other)
            self.assertFalse(overlap, "settle and %s both claim %s" % (name, sorted(overlap)))

    def test_no_template_holds_a_still_frame_longer_than_the_reading_pause(self):
        """Measure the timeline off the card's own stylesheet, not off the act map.

        The act map says when an act *starts*; it cannot say whether anything plays
        during it. A card whose evidence region landed as one synchronized block held
        ~3.9s of 证据 with nothing moving — an act boundary the viewer reads as a
        stalled render. So this walks the emitted rules and finds the longest stretch
        where no new animation starts and none is still running.

        The ceiling is the 分析 pause: `.analysis-note` is the longest text on the
        card and 收束 waits for it to be read. That stretch is the act working, so it
        sets the bound — anything longer is a region that forgot to move.

        Only visible rules count, and two kinds are excluded. `infinite` means
        continuous decoration, which would mask a real dead zone on the five
        breathing cards. A negative delay means the rule was seeked rather than
        played; the freeze path no longer emits one, but the filter stays as a guard
        so a reintroduced seek cannot read as motion that never happens.
        """
        for style in STYLE_CATALOG:
            document = svg.render_story_svg(_analysis(), _selection(style.id))
            index = _Index(document)
            hidden = _hidden_ids(index, index.layout)
            spans = []
            for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", "".join(index.css)):
                shape = re.search(r"animation:\s*(ms-[a-z]+)\s+(\d+)ms", body)
                delay = re.search(r"animation-delay:\s*(-?\d+)ms", body)
                if not shape or not delay or "infinite" in body:
                    continue
                at = int(delay.group(1))
                # `_matching` walks tag/class parts, so the `#artboard` scope prefix
                # every emitted rule carries has to come off or the descendant chain
                # fails on an id it cannot represent and every rule reads as dead.
                parts = [p.strip().replace("#artboard ", "") for p in selector.split(",")]
                if at < 0 or not any(_visible_matches(index, hidden, p) for p in parts):
                    continue
                spans.append((at, at + int(shape.group(2))))
            self.assertTrue(spans, "%s emits no visible motion at all" % style.id)
            spans.sort()
            # The longest stretch with nothing starting and nothing still running.
            still, running = 0, spans[0][1]
            for start, end in spans[1:]:
                still = max(still, start - running)
                running = max(running, end)
            if style.id in svg.STILLNESS_IS_AUTHORED:
                # The exemption is not a free pass: a card claiming its stillness is
                # authored has to actually be breathing through it, or it is just a
                # stalled card with a note attached.
                frame = motion.compile_motion(style.id, seed=style.id, series=_series(12))
                self.assertIn("breathe", frame["primitives"], style.id)
                self._assert_covered(
                    style.id,
                    "authored stillness",
                    tuple(p.replace("#artboard ", "") for p in svg.BREATHE_SELECTOR.split(",")),
                )
                continue
            self.assertLessEqual(
                still,
                svg.MAX_STILL_MS,
                "%s holds a %dms still frame; the reading pause allows %dms"
                % (style.id, still, svg.MAX_STILL_MS),
            )

    def test_void_elements_are_self_closed_for_xml_parsing(self):
        # These four layouts emit <br>; the export must not produce invalid XML.
        for style_id in ("body-letter", "capsule-letter", "no-verdict", "passport-stamps"):
            document = svg.render_story_svg(_analysis(), _selection(style_id))
            self.assertNotIn("<br>", document)
            xml.dom.minidom.parseString(document)

    def test_export_fails_loudly_if_the_card_shell_changes(self):
        with self.assertRaises(ValueError):
            svg._split_document("<html><body>no artboard here</body></html>")

    def test_unknown_style_is_rejected(self):
        selection = {"selected_style": {"id": "not-a-style"}}
        with self.assertRaises(ValueError):
            svg.render_story_svg(_analysis(), selection)


class CardFormatTests(unittest.TestCase):
    """`format` decides which artifacts land, and `both` must not change meaning."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "weight-manager" / "scripts"))
        import weight_truth_card

        cls.card = weight_truth_card

    def test_the_vocabulary_is_exactly_the_five_documented_values(self):
        self.assertEqual(self.card.CARD_FORMATS, ("html", "png", "svg", "both", "all"))

    def test_html_is_written_for_every_format(self):
        # The still composition is the frame of record; the PNG and the SVG are
        # both derived from it, so it can never be the artifact that is skipped.
        for fmt in self.card.CARD_FORMATS:
            self.assertTrue(self.card.wants(fmt, "html"), fmt)

    def test_both_still_means_html_plus_png_and_never_animates(self):
        self.assertTrue(self.card.wants("both", "png"))
        self.assertFalse(self.card.wants("both", "svg"))

    def test_only_svg_and_all_produce_an_animated_card(self):
        animated = {f for f in self.card.CARD_FORMATS if self.card.wants(f, "svg")}
        self.assertEqual(animated, {"svg", "all"})

    def test_all_produces_every_artifact(self):
        for artifact in ("html", "png", "svg"):
            self.assertTrue(self.card.wants("all", artifact), artifact)

    def test_an_unknown_format_degrades_to_the_default_rather_than_crashing(self):
        # argparse is the real gate; this keeps a direct caller from getting an
        # empty artifact set out of a typo.
        for artifact in ("html", "png"):
            self.assertTrue(self.card.wants("nonsense", artifact), artifact)
        self.assertFalse(self.card.wants("nonsense", "svg"))

    def test_both_commands_accept_the_same_format_vocabulary(self):
        for command in ("generate-story", "generate"):
            parser = self.card._parser(command)
            action = next(a for a in parser._actions if a.dest == "format")
            self.assertEqual(tuple(action.choices), self.card.CARD_FORMATS, command)
            self.assertEqual(action.default, "both", command)


class MotionContractDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = CONTRACT_PATH.read_text(encoding="utf-8")

    def test_contract_names_all_six_primitives(self):
        for primitive in motion.MOTION_PRIMITIVES:
            self.assertIn(primitive, self.contract, primitive)

    def test_contract_keeps_the_reduced_motion_and_flicker_constraints(self):
        self.assertIn("prefers-reduced-motion", self.contract)
        # The ceiling MAX_FLICKER_HZ enforces, stated in the contract's own words.
        self.assertIn("3 次/秒", self.contract)


if __name__ == "__main__":
    unittest.main()
