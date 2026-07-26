"""The Signal Frame producer: every domain, schema-valid, and no cross-domain leak.

`tests/test_story_contract.py` validates hand-written frame literals, which proves
the schema is sane but not that anything can build a conforming frame.  These tests
drive `shared.story.frame` over all eight registered domains, so a new domain that
forgets an accessor, or an adapter that starts reading a foreign row key, fails here
rather than at render time.
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.story import adapters, frame as frame_mod  # noqa: E402

SCHEMA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "story-design", "signal-frame.schema.json"
)
with open(SCHEMA_PATH, encoding="utf-8") as handle:
    SCHEMA = json.load(handle)

#: Read off the schema rather than restated, so the two cannot drift apart.
SHAPES = tuple(SCHEMA["properties"]["shape"]["enum"])

#: Subjects that are also the suite's neutral vocabulary for the act of recording.
#: `records` calls its subject 「记录」, which is the same word every frame uses in
#: 「有记录日」 and 「记录次数」 — so its presence in another domain's frame is the
#: shared scaffolding, not a leak.  Kept as an explicit exemption rather than a
#: looser match, so a genuinely foreign subject still fails.
NEUTRAL_STEMS = ("记录",)

END = date(2026, 7, 20)

#: Every row carries every domain's value key at once, which is the point: an adapter
#: that reached for a foreign reading would succeed quietly on a hand-tailored row and
#: only surface once the keys sit side by side, as they do in a real `health_metrics`
#: row.  Two keys cannot be shared, and both are load-bearing:
#:
#: `metric_type` is the discriminator on a `health_metrics` row — `vitals.py:258` and
#: `activity.py:219` both refuse a row whose type is not theirs, so one value cannot
#: satisfy both.  `count` is the steps field itself on an activity row
#: (`activity.py:248`) where every other adapter treats it as a same-day fold count.
METRIC_TYPE = {"vitals": "heart_rate", "activity": "steps", "weight": "weight"}

#: Domains whose adapter expects `daily_records` to arrive already folded to one row
#: per day.  Only weight: `series_for` (`weight.py:184`) maps one row to one point
#: because `weight_truth_card.aggregate_daily_medians` does the median upstream, and
#: that output is locked byte-for-byte.  The other seven fold raw rows themselves.
#:
#: Any host that feeds a domain-general loader has to know which side of this line a
#: domain sits on — handing weight two raw rows for one day yields two points on the
#: same date, which is why the fixture below folds for weight rather than papering
#: over it in the assertion.
PREFOLDED = ("weight",)

EMPTY_ANALYSIS = {
    "window_days": 14,
    "span_days": 14,
    "daily_records": [],
    "recorded_days": 0,
    "measurement_count": 0,
    "coverage_ratio": 0.0,
    "trend_claim_allowed": False,
}


def _rows(domain: str, offsets, per_day: int = 2) -> list:
    """Rows for each day `offsets` days before `END`, `per_day` marks apiece.

    Offsets rather than a count so a caller can leave a real hole in the window
    instead of only ever producing a solid run.

    A `PREFOLDED` domain gets one row per day carrying `per_day` in its
    `measurement_count`, which is what its host hands the adapter; everything else
    gets `per_day` separate rows to fold.  Feeding both the same shape would let a
    real regression hide: raw rows to weight look like duplicate days, and folded
    rows to the other seven look like every day held one mark.
    """
    rows = []
    folded = domain in PREFOLDED
    emit = 1 if folded else per_day
    for index, offset in enumerate(sorted(offsets, reverse=True)):
        day = (END - timedelta(days=offset)).isoformat()
        for repeat in range(emit):
            rows.append(
                {
                    "date": day,
                    "meal_date": day,
                    "measured_at": "%sT08:0%d:00" % (day, repeat),
                    "recorded_at": "%sT08:0%d:00" % (day, repeat),
                    "taken_at": "%sT08:0%d:00" % (day, repeat),
                    "value": 60.0 + index * 0.3 + repeat * 0.1,
                    "weight": 60.0 + index * 0.3,
                    "duration_min": 430 + index * 5,
                    "total_calories": 1800 + index * 20,
                    "count": 6200 + index * 90 if domain == "activity" else 1,
                    "measurement_count": per_day if folded else 1,
                    "metric_type": METRIC_TYPE.get(domain, domain),
                    "field": "steps",
                    "provider": "manual",
                    "source": "manual",
                    "member_id": 1 + (repeat % 2),
                }
            )
    return rows


def _loaded_analysis(domain: str, days: int = 9, per_day: int = 2) -> dict:
    """A window holding `days` recorded days, each carrying `per_day` marks.

    The measurement count sums each row's own repeat count rather than counting
    rows, because a pre-folded domain reports its repeats in `measurement_count`
    while the rest carry one repeat per row.  Both spellings have to describe the
    same window, or `coverage.repeat_days` reads as zero for weight alone.
    """
    rows = _rows(domain, range(days), per_day)
    recorded = len({row["date"] for row in rows})
    return {
        "window_days": 14,
        "span_days": 14,
        "daily_records": rows,
        "recorded_days": recorded,
        "measurement_count": sum(int(row["measurement_count"]) for row in rows),
        "coverage_ratio": round(recorded / 14.0, 3),
        "trend_claim_allowed": True,
        "latest_date": END.isoformat(),
    }


def _validate(frame: dict) -> None:
    import jsonschema

    jsonschema.validate(frame, SCHEMA)


class SignalFrameProducerTests(unittest.TestCase):
    def test_every_domain_builds_a_schema_valid_frame_with_data(self):
        for domain in adapters.available_domains():
            with self.subTest(domain=domain):
                frame = frame_mod.build_frame(domain, _loaded_analysis(domain))
                _validate(frame)
                self.assertTrue(frame["series"], "adapter read none of its own rows")

    def test_every_domain_builds_a_schema_valid_frame_with_no_data(self):
        """A zero-data frame is the one every domain must always be able to emit.

        It is what backs the `no-verdict` template, the single style whose
        `min_recorded_days` is 0 — so if this fails, that domain has no card at all
        on the day a user first opens it.
        """
        for domain in adapters.available_domains():
            with self.subTest(domain=domain):
                frame = frame_mod.build_frame(domain, dict(EMPTY_ANALYSIS))
                _validate(frame)
                self.assertEqual(frame["series"], [])
                self.assertEqual(frame["shape"], "insufficient")
                self.assertIsNone(frame["trend"]["direction"])

    def test_window_stays_inside_the_schema_bounds(self):
        """`days` is clamped to 7..90 whatever the caller asks for."""
        for requested, expected in ((1, 7), (14, 14), (365, 90)):
            with self.subTest(requested=requested):
                analysis = dict(EMPTY_ANALYSIS, window_days=requested)
                frame = frame_mod.build_frame("records", analysis)
                self.assertEqual(frame["window"]["days"], expected)
                _validate(frame)

    def test_limits_are_false_for_every_domain(self):
        """The four boundary flags are the contract; no domain may soften them."""
        for domain in adapters.available_domains():
            with self.subTest(domain=domain):
                limits = frame_mod.build_frame(domain, _loaded_analysis(domain))["limits"]
                self.assertIs(limits["causal_claim"], False)
                self.assertIs(limits["prescription"], False)
                self.assertIs(limits["unrecorded_is_zero"], False)
                self.assertIs(limits["cross_domain_arithmetic"], False)

    def test_series_never_invents_an_unrecorded_day(self):
        """A gap stays a gap, and a repeated day stays one point.

        Six recorded days either side of a five-day hole, two marks each.  A series
        of six points proves the fold; a series of eleven would mean some adapter
        filled the hole with zeroes, which `limits.unrecorded_is_zero` forbids.
        """
        offsets = [13, 12, 11] + [2, 1, 0]
        for domain in adapters.available_domains():
            with self.subTest(domain=domain):
                rows = _rows(domain, offsets, per_day=2)
                analysis = dict(_loaded_analysis(domain), daily_records=rows)
                frame = frame_mod.build_frame(domain, analysis)
                dates = [point["date"] for point in frame["series"]]
                self.assertEqual(dates, sorted(dates))
                self.assertEqual(len(dates), 6, "expected one point per recorded day")
                self.assertEqual(len(set(dates)), len(dates), "a day appeared twice")
                self.assertLessEqual(len(dates), frame["window"]["days"])
                self.assertEqual([point["count"] for point in frame["series"]], [2] * 6)

    def test_repeat_marks_survive_whichever_side_folds_them(self):
        """The repeat count reaches the frame from both input contracts.

        Weight's `series_for` (`weight.py:184`) is pass-through: the host folds the
        day first, so its repeats arrive in each row's `measurement_count`.  The
        other seven fold raw rows themselves and count the rows.  Both have to end
        up with `count: 2` on every point, because that is what the schema calls
        「>1 enables the double-exposure moment」 — a domain that loses it renders a
        repeat-heavy window as though every day held a single mark.
        """
        for domain in adapters.available_domains():
            with self.subTest(domain=domain, prefolded=domain in PREFOLDED):
                frame = frame_mod.build_frame(domain, _loaded_analysis(domain, days=4))
                self.assertEqual([point["count"] for point in frame["series"]], [2] * 4)
                self.assertGreaterEqual(frame["coverage"]["measurement_count"], 8)

    def test_frame_names_no_domain_outside_its_own_lexicon(self):
        """The subject word of one domain must not appear in another's frame.

        The frame is the domain-neutral contract, so every domain-specific word in
        it has to come from `lexicon`.  A subject leaking in from elsewhere means an
        adapter, or this producer, hard-coded a reading it does not own.
        """
        subjects = {
            domain: adapters.lexicon_for(domain)["subject"]
            for domain in adapters.available_domains()
        }
        for domain in adapters.available_domains():
            frame = frame_mod.build_frame(domain, _loaded_analysis(domain))
            own = subjects[domain]
            blob = json.dumps(
                {key: value for key, value in frame.items() if key != "lexicon"},
                ensure_ascii=False,
            )
            for other, subject in subjects.items():
                if other == domain or subject in own or own in subject:
                    continue
                if subject in NEUTRAL_STEMS:
                    continue
                with self.subTest(domain=domain, foreign=other):
                    self.assertNotIn(subject, blob)


class RenderReadyTests(unittest.TestCase):
    def test_shape_reaches_the_dict_the_renderer_reads(self):
        """The gap this function exists to close.

        `render.py:657` reads `analysis["shape"]`, and nothing in `shared/story/`
        calls an adapter, so an analysis that arrives without it narrates as
        `insufficient` however much data it holds.
        """
        for domain in ("sleep", "intake", "vitals", "activity", "records"):
            with self.subTest(domain=domain):
                analysis = _loaded_analysis(domain)
                self.assertNotIn("shape", analysis)
                ready = frame_mod.render_ready(domain, analysis)
                self.assertEqual(ready["shape"], ready["frame"]["shape"])
                self.assertIn(ready["shape"], SHAPES)
                self.assertNotEqual(ready["shape"], "insufficient")

    def test_existing_keys_are_never_overwritten(self):
        """Weight's output is locked byte-for-byte, so its dialect wins outright."""
        analysis = dict(
            _loaded_analysis("weight"), shape="stable", coverage_ratio=0.5, window_days=30
        )
        ready = frame_mod.render_ready("weight", analysis)
        self.assertEqual(ready["shape"], "stable")
        self.assertEqual(ready["coverage_ratio"], 0.5)
        self.assertEqual(ready["window_days"], 30)

    def test_render_ready_leaves_the_caller_dict_alone(self):
        analysis = _loaded_analysis("sleep")
        before = json.dumps(analysis, ensure_ascii=False, sort_keys=True)
        frame_mod.render_ready("sleep", analysis)
        self.assertEqual(json.dumps(analysis, ensure_ascii=False, sort_keys=True), before)

    def test_unknown_domain_is_refused_rather_than_guessed(self):
        with self.assertRaises(Exception):
            frame_mod.build_frame("bloodline", _loaded_analysis("weight"))


class RobustFitTests(unittest.TestCase):
    """The long-run number, which weight computed and the other seven did not.

    `trend.delta` is declared by the schema as 「Robust change across the window, in
    `lexicon.unit`」, but the only estimator in the repository lived in
    `weight-manager/scripts/weight_truth_card.py` and read `item["weight"]`.  So the
    other seven domains left the field absent and the card printed 「—」 under a note
    that said 稳健估计 — an empty value asserting an estimate that was never made.

    The fit is scale-free by construction: its x-axis is calendar-day offset and its
    y-axis is whatever the series holds, so the same median-of-pairwise-slopes yields
    kg/day, 分钟/day or 步/day without a threshold anywhere in it.  What it must not
    do is disagree with weight's own arithmetic, which is what the first test pins.
    """

    def test_the_shared_fit_agrees_with_weights_own_estimator(self):
        """Same estimator or none: two spellings of 稳健估计 must not differ.

        `weight_truth_card.theil_sen_fit` is locked by `tests/golden/`, so this is
        the byte-level guard on lifting the math into `shared/`: identical inputs,
        identical floats, no `assertAlmostEqual` to hide a re-derivation.
        """
        sys.path.insert(
            0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "weight-manager", "scripts"))
        )
        from weight_truth_card import theil_sen_fit

        cases = {
            "solid run": [13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
            "gap in the middle": [13, 12, 11, 2, 1, 0],
            "two days only": [1, 0],
            "one day": [0],
            "same day twice": [0, 0],
        }
        for name, offsets in cases.items():
            rows = _rows("weight", offsets, per_day=1)
            with self.subTest(case=name):
                self.assertEqual(
                    frame_mod.robust_fit(rows, value_key="weight"),
                    theil_sen_fit(rows),
                    "%s: shared fit and weight's fit disagree" % name,
                )

    def test_an_unfittable_series_returns_no_line_rather_than_a_flat_one(self):
        """The three inputs that support no slope, asserted on the fit directly.

        Held here and not by the agreement test above, which can no longer see these:
        `theil_sen_fit` delegates now, so the two sides move together and a mutation
        that made both return `0.0` would keep them equal.  What this pins is the
        value itself, and the distinction is editorial — a fabricated zero slope reads
        on the card as 长期持平, a claim about the body, where an absent one reads as
        暂无稳健拟合, which is a statement about the records.

        The empty case is not hypothetical: `_trend` calls the fit whenever the host
        set `claim_allowed`, and an event-shaped domain can allow a claim on a window
        whose narrated component contributed no rows at all.  Without the `< 2` guard
        that call reaches `points[0]` and raises.
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
                    frame_mod.robust_fit(points),
                    (None, None),
                    "%s: 造出了一条不存在的拟合线" % name,
                )

    def test_an_empty_series_with_a_permitted_claim_survives_the_fit(self):
        """`claim_allowed` on a window the narrated component never appears in.

        Separate from the unit test above because the crash it guards is reached
        through `build_frame`, and a guard that only the fit's own test covers would
        not notice the frame losing its `series`.
        """
        analysis = dict(EMPTY_ANALYSIS, trend_claim_allowed=True)
        trend = frame_mod.build_frame("vitals", analysis)["trend"]
        self.assertIs(trend["claim_allowed"], True)
        self.assertNotIn("delta", trend)

    def test_visual_direction_strength_is_unitless_and_noise_sensitive(self):
        rising = [
            {"date": "2026-07-%02d" % day, "value": float(day * 1000)}
            for day in range(1, 8)
        ]
        falling = [dict(point, value=-point["value"]) for point in rising]
        mixed = [
            {"date": "2026-07-%02d" % day, "value": value}
            for day, value in enumerate((0, 10, 1, 11, 2, 12, 3), start=1)
        ]

        self.assertEqual(frame_mod.robust_direction_strength(rising), 1.0)
        self.assertEqual(frame_mod.robust_direction_strength(falling), -1.0)
        self.assertLess(abs(frame_mod.robust_direction_strength(mixed)), 1.0)
        self.assertIsNone(frame_mod.robust_direction_strength(rising[:1]))

    def test_every_domain_gets_a_long_run_change_in_its_own_unit(self):
        """The field the renderer prints as 长期, filled for all eight domains.

        Extrapolated across the window exactly as weight defines it — slope times
        `window.days - 1` — so 长期 means the same span in every domain rather than
        a per-domain interval that happens to share a label.
        """
        for domain in adapters.available_domains():
            with self.subTest(domain=domain):
                frame = frame_mod.build_frame(domain, _loaded_analysis(domain))
                trend = frame["trend"]
                slope = trend.get("slope_per_day")
                self.assertIsNotNone(slope, "%s: 没有拟合斜率" % domain)
                self.assertIsNotNone(trend.get("delta"), "%s: 没有长期变化量" % domain)
                self.assertEqual(trend.get("method"), "theil_sen")
                self.assertGreaterEqual(trend.get("visual_strength"), -1.0)
                self.assertLessEqual(trend.get("visual_strength"), 1.0)
                self.assertIn(trend.get("confidence"), ("low", "medium", "high"))
                self.assertNotEqual(trend.get("confidence_label"), "不足")
                self.assertIn(
                    frame["series_meta"]["fold"],
                    ("median", "mean", "sum", "count", "last"),
                )
                self.assertAlmostEqual(
                    trend["delta"], slope * (frame["window"]["days"] - 1), places=6
                )
                _validate(frame)

    def test_no_long_run_claim_without_the_records_to_earn_it(self):
        """`claim_allowed` gates the estimate, not just the sentence about it.

        Weight computes `trend_delta` only when `sufficient`; a frame that filled the
        field anyway would let a two-day window print a fortnight-long extrapolation
        while the note beside it still said 记录不足.
        """
        for domain in adapters.available_domains():
            analysis = dict(_loaded_analysis(domain, days=2), trend_claim_allowed=False)
            with self.subTest(domain=domain):
                trend = frame_mod.build_frame(domain, analysis)["trend"]
                self.assertNotIn("delta", trend, "%s: 记录不足却给了长期变化量" % domain)
                self.assertNotIn("slope_per_day", trend, "%s: 记录不足却给了斜率" % domain)
                self.assertNotIn("method", trend, "%s: 记录不足却声明了估计方法" % domain)

    def test_a_single_point_earns_no_fit_even_when_the_window_allows_one(self):
        """The state the fill makes common: enough recorded days, one usable point.

        A `health_metrics` window can hold five recorded days of which only one is
        the component this domain narrates, so `claim_allowed` is True while the
        series is too short to fit.  The frame must leave the field absent rather
        than invent a flat line.
        """
        rows = _rows("vitals", [0], per_day=1)
        analysis = dict(
            _loaded_analysis("vitals"), daily_records=rows, trend_claim_allowed=True
        )
        trend = frame_mod.build_frame("vitals", analysis)["trend"]
        self.assertIs(trend["claim_allowed"], True)
        self.assertNotIn("delta", trend)
        self.assertNotIn("slope_per_day", trend)

    def test_weights_own_long_run_number_still_wins(self):
        """Weight arrives with `trend_delta` already computed; the fit must not move it."""
        analysis = dict(
            _loaded_analysis("weight"),
            trend_delta=-0.875,
            trend_slope_per_day=-0.06731,
            method="daily_median+theil_sen",
        )
        frame = frame_mod.build_frame("weight", analysis)
        self.assertEqual(frame["trend"]["delta"], -0.875)
        self.assertEqual(frame["trend"]["slope_per_day"], -0.06731)
        self.assertEqual(frame["trend"]["method"], "theil_sen")
        self.assertEqual(frame["series_meta"]["fold"], "median")
        ready = frame_mod.render_ready("weight", analysis)
        self.assertEqual(ready["trend_delta"], -0.875)

    def test_render_ready_surfaces_frame_confidence_without_overwriting_weight(self):
        sleep = frame_mod.render_ready("sleep", _loaded_analysis("sleep"))
        self.assertIn(sleep["confidence"], ("low", "medium", "high"))
        self.assertNotEqual(sleep["confidence_label"], "不足")

        weight = dict(_loaded_analysis("weight"), confidence="high", confidence_label="较高")
        ready = frame_mod.render_ready("weight", weight)
        self.assertEqual(ready["confidence"], "high")
        self.assertEqual(ready["confidence_label"], "较高")


if __name__ == "__main__":
    unittest.main()
