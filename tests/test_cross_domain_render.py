"""Render every template for every domain and audit the words that come out.

The contract's central claim is that one set of 24 templates serves every domain
because all domain wording arrives through the lexicon.  `test_domain_adapters.py`
checks that claim structurally -- adapters expose the right helpers, the catalog
holds no domain nouns.  This file checks it the only way that is conclusive: draw
the cards and read them.

Two leaks got past a hand-written smoke check before this existed.  Both were in
the shared catalog, so grepping the renderers found nothing, and one of them
(`秤面` on a sleep card) was never reported at all because the audit's forbidden
list did not happen to mention that word.  So the forbidden vocabulary here is not
written per test: it comes from `DOMAIN_VOCABULARY`, which
`test_every_lexicon_value_is_declared_own_or_shared` forces each new domain to
fill in.  Registering a domain extends this matrix whether or not anyone
remembers to come back here.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.story.adapters import available_domains, get_adapter, lexicon_for
from shared.story.catalog import STYLE_CATALOG
from shared.story.frame import render_ready
from shared.story import render
from shared.story.render import CORE_SHAPE_COPY, render_weight_story_html
from shared.story.selector import select_weight_card_style
from shared.story.svg import render_story_svg

from test_domain_adapters import DOMAIN_VOCABULARY, EVALUATIVE, forbidden_for, hits

# Each domain's reading, in the key its adapter looks for.  A domain absent from
# here cannot be rendered by these tests, so `test_every_domain_has_a_fixture`
# fails rather than letting the matrix quietly shrink.
FIXTURES = {
    "weight": lambda i: {"weight": round(72.0 - i * 0.05, 2)},
    "sleep": lambda i: {"duration_min": 452 + (i * 7) % 41},
    "records": lambda i: {"measurement_count": 1 + i % 3},
    # Heart rate, because `lexicon_for` hands back a domain's default lexicon and
    # vitals' default component is heart_rate -- a systolic fixture would be plotted
    # under 心率/次/分 and `test_every_card_names_its_own_subject` would be checking
    # the wrong word against the right numbers.
    "vitals": lambda i: {"heart_rate": 66 + (i * 3) % 11},
    # Calories, intake's default component, and strictly above zero on every row:
    # the adapter reads `total_calories > 0` as "this row was itemised", so a fixture
    # day that happened to land on 0 would drop out of the series and the plot would
    # be shorter than the 有记录日 count the same card prints.
    "intake": lambda i: {"total_calories": 1780 + (i * 37) % 320},
    # Steps, activity's default component, on the bare `count` key rather than inside a
    # JSON payload -- both are readable and this is the shape a fixture can state plainly.
    # No `source` on any row, which keeps the device-swap gate quiet: these fixtures exist
    # to render all 24 templates, and a fixture that tripped the gate would render the
    # domain's own refusal 24 times instead of the copy under test.
    "activity": lambda i: {"count": 6100 + (i * 431) % 2600},
    # Dose records per day, and the fixture is this thin because the adapter is: it
    # reads the date and `measurement_count`, never `medication_name` and never
    # `dose_taken`.  Rows carrying either would render identically, so putting them
    # here would suggest the renderer had been shown a drug name and declined to print
    # it, when in fact nothing downstream was ever handed one.  The cycle stays 1..2 so
    # a card can print 同日多剂累计 without the count reading like a schedule.
    "adherence": lambda i: {"measurement_count": 1 + i % 2},
    # A member id and a row count, which is the entire surface this adapter reads.
    # The id is opaque on purpose: the refused fields (`name`, `relation`,
    # `birth_date`, `allergies`, `diagnosis`) are absent rather than
    # present-and-ignored, for the reason spelled out on adherence's row above.
    #
    # `_analysis` builds one row per date, so the id cycling across three buckets
    # varies *who* wrote from day to day but leaves one participant on each of them,
    # and the plotted series is flat at 1.0.  That is the honest reading of one row a
    # day, it renders (the plot's spread has a floor), and the copy matrix drives
    # shapes through the `shape` override anyway.  A fixture that stacked several
    # members onto one date would need `_analysis` to emit more than one row per
    # date, which would change every other domain's fixture to exercise this one.
    "family": lambda i: {"member_id": "m%d" % (i % 3), "measurement_count": 1 + i % 2},
}

DATES = ["2026-07-%02d" % day for day in range(1, 15)]

# Judgment words do appear on cards, but only inside a refusal: 「不是健康评分」,
# 「空白不是失败」, 「今天不需要被解释成成功或失败」.  Each is the product declining to
# judge, which is the opposite of the leak worth catching -- an earlier audit flagged
# them and was wrong three times.
#
# So the exemption is scoped to the clause, which fixes two different mistakes the
# earlier predicates made in opposite directions.
#
# It was too loose for 评判词: the old check searched the whole document for a negator
# within three characters, so a card printing 「空白不是失败」 had 失败 excused
# everywhere on the page, including in an unrelated sentence that really was a
# verdict.  And it was too tight for refusals: a character window has to guess how
# far a negator reaches -- 「不是健康评分」 needs one, 「今天不需要被解释成成功或失败」
# needs six to reach 成功 and nine to reach 失败 -- and a window wide enough for the
# longest refusal is wide enough to launder a verdict standing next to it.
#
# Punctuation is the honest boundary: inside one clause a leading negator does govern
# what follows it, across a comma it does not.  The cost is that a negator early in a
# clause excuses the whole rest of that clause, which is why the exemption is proven
# by `RefusalPredicateTests` rather than assumed.
SCORING = ("评分", "评级", "打分", "得分")
JUDGMENT = EVALUATIVE + SCORING
CLAUSE = re.compile(r"[，。；、!?！？\s]+")
NEGATOR = re.compile(r"[不非无未没别莫]")


def _unrefused(text):
    """Judgment words on the page that no negator in their own clause disowns."""
    found = set()
    for clause in CLAUSE.split(text):
        for word in JUDGMENT:
            at = clause.find(word)
            if at != -1 and not NEGATOR.search(clause, 0, at):
                found.add(word)
    return sorted(found)


def _analysis(domain, *, shape=None, days=len(DATES)):
    """A host analysis with enough recorded days that every template is eligible.

    Style eligibility reads `recorded_days`, `trend_claim_allowed` and
    `measurement_count`; 14 days with a permitted trend clears all 24, since no
    style declares `required_domains`.  `shape` is set directly because the
    renderer prefers `analysis["shape"]` -- that is how a Signal Frame arrives --
    which lets one fixture sweep all nine shapes without faking nine data sets.
    """
    payload = FIXTURES[domain]
    records = [dict(payload(index), date=day) for index, day in enumerate(DATES[:days])]
    analysis = {
        "window_days": 14,
        "span_days": 14,
        "daily_records": records,
        "recorded_days": len(records),
        "measurement_count": sum(item.get("measurement_count", 1) for item in records),
        "trend_claim_allowed": days >= 3,
    }
    if shape:
        analysis["shape"] = shape
    return analysis


def _text(markup):
    """Strip markup to the words a reader actually sees.

    `<script>` goes as well as `<style>`: the viewport-fit script contains a JS
    template literal (`${W*s}px`) that reads as an unfilled `{s}` copy slot, which
    is how a false positive appeared on all 24 documents at once.
    """
    text = re.sub(r"<(style|script)\b.*?</\1>", " ", markup, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


SLOT = re.compile(r"\{[a-z_]+\}")


def _complaints(text, *, subject, forbidden):
    """Every audit in this file, applied to one card.

    The four tests below each draw the matrix at whatever shape the fixture data
    happens to produce.  The shape sweep needs all four checks per card instead of
    one, so they live here as well and are named in the failure message.
    """
    found = ["泄漏 %s" % word for word in hits(text, forbidden)]
    found += ["评判 %s" % word for word in _unrefused(text)]
    found += ["空槽 %s" % slot for slot in sorted(set(SLOT.findall(text)))]
    if subject not in text:
        found.append("缺主体 %s" % subject)
    return found


def _render(domain, style_id, fmt, analysis, *, seed="cross-domain"):
    """Draw one card, or explain why the style would not take."""
    lexicon = lexicon_for(domain)
    selection = select_weight_card_style(
        analysis, pinned_style=style_id, seed=seed, domain=domain, lexicon=lexicon
    )
    chosen = (selection.get("selected_style") or {}).get("id")
    if chosen != style_id:
        raise AssertionError("%s/%s: pinned style did not take (%s)" % (domain, style_id, chosen))
    if fmt == "html":
        markup = render_weight_story_html(analysis, selection, domain=domain, lexicon=lexicon)
    else:
        markup = render_story_svg(
            analysis, selection, frame=None, domain=domain, lexicon=lexicon
        )
    return markup


class RefusalPredicateTests(unittest.TestCase):
    """`_unrefused` decides what counts as a verdict, so it gets its own cases.

    Every sentence here is either copy that ships today or the failure mode a past
    version of this predicate had.  Without them the matrix test can go green because
    the predicate stopped flagging anything, which is how the two earlier versions
    were wrong -- one excused a verdict standing beside a refusal, the other reported
    a refusal as a verdict.
    """

    def test_a_bare_verdict_is_reported(self):
        for text in ("已经达标。", "本周成功。", "这周退步了", "记录得很糟"):
            with self.subTest(text=text):
                self.assertTrue(_unrefused(text), text)

    def test_a_refusal_is_not_a_verdict(self):
        """All four are copy that ships; the last two motivated the clause scoping."""
        for text in (
            "这是记录风格，不是健康评分。",
            "空白不是失败",
            "空白不是断签失败",
            "下一次记录会增加信息，但今天不需要被解释成成功或失败。",
        ):
            with self.subTest(text=text):
                self.assertEqual(_unrefused(text), [], text)

    def test_a_negator_does_not_reach_across_punctuation(self):
        """The hole in the old whole-document search, kept as a case.

        A card that refuses in one sentence and judges in the next is judging.
        """
        self.assertEqual(_unrefused("空白不是失败。本周失败。"), ["失败"])


class EveryDomainRendersCleanTests(unittest.TestCase):
    """The full matrix: every registered domain x 24 templates x HTML and SVG."""

    def test_non_weight_artboards_declare_the_actual_story_domain(self):
        """Template preference is not the domain whose records the card narrates."""
        for domain in available_domains():
            if domain == "weight":
                continue
            markup = _render(domain, STYLE_CATALOG[0].id, "html", _ready(domain))
            with self.subTest(domain=domain):
                self.assertIn('data-story-domain="%s"' % domain, markup)

    def test_every_domain_has_a_fixture(self):
        """A registered domain with no fixture would silently skip the matrix."""
        for domain in available_domains():
            self.assertIn(domain, FIXTURES, domain)

    def test_no_card_prints_another_domains_words(self):
        leaks = []
        for domain in available_domains():
            forbidden = forbidden_for(domain)
            analysis = _analysis(domain)
            for style in STYLE_CATALOG:
                for fmt in ("html", "svg"):
                    text = _text(_render(domain, style.id, fmt, analysis))
                    for word in hits(text, forbidden):
                        leaks.append("%s/%s/%s: %s" % (domain, style.id, fmt, word))
        self.assertEqual(leaks, [], "\n".join(["卡面泄漏他域词:"] + leaks))

    def test_no_card_leaves_a_copy_slot_unfilled(self):
        """An unfilled slot is the failure mode of the whole lexicon mechanism."""
        misses = []
        for domain in available_domains():
            analysis = _analysis(domain)
            for style in STYLE_CATALOG:
                for fmt in ("html", "svg"):
                    text = _text(_render(domain, style.id, fmt, analysis))
                    for slot in sorted(set(re.findall(r"\{[a-z_]+\}", text))):
                        misses.append("%s/%s/%s: %s" % (domain, style.id, fmt, slot))
        self.assertEqual(misses, [], "\n".join(["未填充的文案槽:"] + misses))

    def test_every_card_names_its_own_subject(self):
        """Proves the lexicon reached the page, rather than nothing reaching it.

        Without this, a renderer that dropped all domain wording would pass every
        other check in this file by printing nothing at all.
        """
        for domain in available_domains():
            subject = lexicon_for(domain)["subject"]
            analysis = _analysis(domain)
            for style in STYLE_CATALOG:
                for fmt in ("html", "svg"):
                    with self.subTest(domain=domain, style=style.id, fmt=fmt):
                        text = _text(_render(domain, style.id, fmt, analysis))
                        self.assertIn(subject, text)

    def test_no_card_reads_as_a_verdict(self):
        """story-system.md line 43, checked on the page instead of in the lexicon.

        Refusals stay legal: 「不是健康评分」, 「空白不是失败」, 「今天不需要被解释成成功
        或失败」.  All three name a judgment in order to decline it, so the exemption is
        the clause-scoped negator in `_unrefused`, not a per-word allowlist -- an
        allowlist would need a new entry every time the copy finds a new way to say no.
        """
        verdicts = []
        for domain in available_domains():
            analysis = _analysis(domain)
            for style in STYLE_CATALOG:
                for fmt in ("html", "svg"):
                    text = _text(_render(domain, style.id, fmt, analysis))
                    for word in _unrefused(text):
                        verdicts.append("%s/%s/%s: %s" % (domain, style.id, fmt, word))
        self.assertEqual(verdicts, [], "\n".join(["卡面出现评判词:"] + verdicts))

    def test_every_shape_renders_clean_on_every_domain(self):
        """The same four audits, swept across all nine shapes.

        Shape picks which copy table the renderer reads and which visual branch it
        takes, and the tests above reach exactly one of the nine.  `_analysis` sets
        neither `shape` nor `state`, so `_shape_of` falls through to `insufficient`
        for every card in this file -- meaning the four audits above, run 144 times
        each, were all reading the one table that promises nothing about direction or
        trend.  A leak or a verdict written into any of the other eight was invisible.

        Setting `analysis["shape"]` is how a Signal Frame arrives, so the sweep asks
        for each shape directly rather than reverse-engineering nine data sets per
        domain that would land on them.

        9 shapes x 3 domains x 24 templates x 2 formats, under a second.
        """
        complaints = []
        for domain in available_domains():
            forbidden = forbidden_for(domain)
            subject = lexicon_for(domain)["subject"]
            for shape in sorted(CORE_SHAPE_COPY):
                analysis = _analysis(domain, shape=shape)
                for style in STYLE_CATALOG:
                    for fmt in ("html", "svg"):
                        text = _text(_render(domain, style.id, fmt, analysis))
                        for note in _complaints(text, subject=subject, forbidden=forbidden):
                            complaints.append(
                                "%s/%s/%s/%s: %s" % (domain, shape, style.id, fmt, note)
                            )
        self.assertEqual(complaints, [], "\n".join(["形态扫描发现问题:"] + complaints))


# A management block in the shape `analyze_weight_management` returns, trimmed to the
# keys the selector reads.  `_analysis` deliberately never sets this, which is why the
# sweeps above could not see the companion-moment leak: with no `management` key no
# companion moment fires, so its copy never reaches a card to be scanned.
# A management block in the shape `analyze_weight_management` returns.  The copy fields
# are quoted from `synthesis.py` rather than paraphrased, because the leak they defend
# against is that exact prose: `_situation_portrait` writes 「体重、摄入、运动和睡眠」 into
# `hook`, `_synthesis` copies `title`/`summary` into `headline`/`paragraph`, and
# `render._management_details` reads all of them straight onto the card.  A fixture that
# only set `pattern_id` would pass for the wrong reason -- the copy reads would fall back
# to `no_companion_copy_for(domain)` because the keys were absent, not because a gate held.
FORCED_MANAGEMENT = {
    "synthesis": {
        "headline": "四线同框，剧情待续",
        "paragraph": (
            "这一段体重记录较前半段 −0.4 kg；同期前后半段可比较的记录中，饮食记录日平均摄入下降。"
            "同期变化不代表因果。未记录日也不能按零摄入、零运动或零睡眠处理。"
        ),
        "situation": {
            "pattern_id": "four-signals",
            "title": "四线同框，剧情待续",
            "hook": "体重、摄入、运动和睡眠已经能放进同一张阶段肖像。",
            "coverage_line": "14 天窗口 · 体重 9 天 · 饮食 6 天 · 运动 5 天 · 睡眠 7 天",
        },
        "social_packaging": {
            "save_prompt": "保存这张，下一段 14 天回来和自己对照",
            "share_caption": "我的体重译报｜四线同框，剧情待续。数据只描述同期变化，不代表因果。",
        },
    },
    "coverage": {"eligible_lifestyle_domains": 3, "overall_label": "生活方式记录较完整"},
    "sleep": {"claim_allowed": True, "recorded_days": 7, "average_duration_min": 431.0},
    "activity": {"claim_allowed": True, "recorded_days": 5, "total_duration_min": 190.0},
    "intake": {"claim_allowed": True, "recorded_days": 6, "average_calories_on_recorded_days": 1850.0},
}

COMPANION_MOMENTS = ("four-signals", "second-half-shift", "recording-spotlight")


class CompanionMomentsStayOnTheirAxisTests(unittest.TestCase):
    """A domain that reads no companions may not narrate one, data or no data.

    Three of the ten moments in `MOMENT_COPY` are companion moments: their copy names
    the domains a card is read *alongside*, and `four-signals` enumerates all four of
    体重、摄入、运动、睡眠 in one sentence.  They are derived from
    `management.synthesis.situation.pattern_id`, and only the weight branch of
    `weight_truth_card` ever writes `management`, so nothing leaks today.

    That made the protection incidental rather than structural, and this is the class
    of leak no forbidden-word scan finds on its own -- the leaked token is another
    domain's *subject*, not a verdict, so `_unrefused` has nothing to say about it and
    the vocabulary audit only fires if the copy actually reaches a card.  These tests
    hand every domain the `management` block it would never normally get and check the
    gate holds, so a future host that populates `management` for a second domain fails
    here instead of shipping 「体重、摄入、运动和睡眠」 on a sleep card.

    Asserted at the moment layer and again at the render surface, because only some
    templates print a moment: a render-only test would pass for the wrong reason on the
    styles that never show one.
    """

    def test_only_domains_with_companions_emit_companion_moments(self):
        from shared.story.adapters import companions_for
        from shared.story.selector import detect_story_moments

        for domain in available_domains():
            analysis = dict(_analysis(domain), management=dict(FORCED_MANAGEMENT))
            emitted = {item["id"] for item in detect_story_moments(analysis, domain)}
            companion = sorted(emitted.intersection(COMPANION_MOMENTS))
            with self.subTest(domain=domain):
                if companions_for(domain):
                    # Weight has a real companion axis, so the gate must be a no-op for
                    # it -- over-gating would silently drop copy the goldens lock.
                    self.assertTrue(
                        companion, "%s 声明了伴随域，却拿不到伴随时刻" % domain
                    )
                else:
                    self.assertEqual(
                        companion,
                        [],
                        "%s 没有伴随域，却拿到了伴随时刻 %s" % (domain, companion),
                    )

    def test_no_card_leaks_a_foreign_subject_when_management_is_forced(self):
        """The vocabulary audit, re-run over the surface `management` unlocks.

        Reuses `forbidden_for` rather than naming the four subjects, so this keeps
        testing the real contract as domains are added: `forbidden_for` exempts a
        domain's declared companions and subtracts words two domains share, which is
        why weight passes while reading 睡眠记录 out of the lifestyle tables.
        """
        complaints = []
        for domain in available_domains():
            forbidden = forbidden_for(domain)
            subject = lexicon_for(domain)["subject"]
            analysis = dict(_analysis(domain), management=dict(FORCED_MANAGEMENT))
            for style in STYLE_CATALOG:
                for fmt in ("html", "svg"):
                    text = _text(_render(domain, style.id, fmt, analysis))
                    for note in _complaints(text, subject=subject, forbidden=forbidden):
                        complaints.append("%s/%s/%s: %s" % (domain, style.id, fmt, note))
        self.assertEqual(
            complaints, [], "\n".join(["注入 management 后发现问题:"] + complaints)
        )

    def test_style_probability_is_not_moved_by_companion_evidence_a_domain_lacks(self):
        """`_domain_available` answers a catalog tag, gated on the story domain.

        `matched_domains` multiplies a template's weight by 1.28 or 0.55 on the answer,
        so an ungated lookup lets injected companion evidence reshape which template a
        records card draws.  The `weight` and `recording` tags ask about the card's own
        records and must stay answerable for every domain; the rest must read False
        wherever there is no companion axis.
        """
        from shared.story.adapters import companions_for
        from shared.story.selector import _domain_available

        own_tags = ("weight", "recording")
        companion_tags = ("sleep", "activity", "intake", "synthesis")
        for domain in available_domains():
            analysis = dict(_analysis(domain), management=dict(FORCED_MANAGEMENT))
            with self.subTest(domain=domain):
                for tag in own_tags:
                    self.assertTrue(
                        _domain_available(analysis, tag, domain),
                        "%s 的自有记录问题 %s 应当可答" % (domain, tag),
                    )
                expected = bool(companions_for(domain))
                for tag in companion_tags:
                    self.assertEqual(
                        _domain_available(analysis, tag, domain),
                        expected,
                        "%s 的伴随问题 %s 越过了伴随轴" % (domain, tag),
                    )


def _folded_analysis(domain, *, per_day=3, days=len(DATES)):
    """A host analysis whose `recorded_days` counts rows instead of dates.

    This is the shape `_analysis` cannot produce: it lays one row on each date, so a
    row count and a date count agree there by construction and the seam this class
    guards is invisible.  Here `days` dates each carry `per_day` rows, so the host
    reports `days * per_day` while the records span `days` -- which is what a caller
    that hands over raw rows actually looks like for the seven folding domains.

    `days` fills the whole window by default rather than part of it.  A narrower fixture
    reads as the stronger test, and it was one until the selector began routing the same
    count: styles gated at ten or fourteen recorded days then became correctly ineligible,
    and pinning them raised instead of rendering, so these sweeps silently stopped covering
    two thirds of the catalog.  Filling the window keeps all 24 styles reachable while the
    gap this fixture exists to create -- 42 rows against 14 dates -- stays just as wide.
    """
    payload = FIXTURES[domain]
    rows = []
    for index, day in enumerate(DATES[:days]):
        for repeat in range(per_day):
            rows.append(dict(payload(index * per_day + repeat), date=day))
    return {
        "window_days": len(DATES),
        "span_days": len(DATES),
        "daily_records": rows,
        "recorded_days": len(rows),
        "measurement_count": len(rows),
        "trend_claim_allowed": True,
    }


def _folding_domains():
    """The domains whose adapters fold rows to dates -- everything but `weight`.

    Derived from `PREFOLDED` rather than listed, so registering a ninth domain puts it
    under these sweeps automatically instead of silently omitting it.
    """
    from test_story_frame import PREFOLDED

    return tuple(sorted(set(available_domains()) - set(PREFOLDED)))


_FOLDING_DOMAINS = _folding_domains()


class CoverageOnTheCardMatchesTheAdapterTests(unittest.TestCase):
    """The printed coverage count comes from the domain's own `coverage_for`.

    `weight` is PREFOLDED, so its adapter passes the host's numbers through and no
    substitution is observable there -- which is why the goldens stay byte-identical and
    why a weight-only test would prove nothing.  The other seven fold rows to dates
    internally, so reading `analysis["recorded_days"]` straight onto the card printed the
    host's row count against the window denominator: 「15 / 14 天」, fifteen recorded days
    inside a fourteen-day window.  Nothing in the forbidden-word scans catches that -- the
    words are all permitted, the arithmetic is what is wrong.
    """

    def test_a_folded_host_count_and_the_adapter_disagree(self):
        """Without this the rest of the class passes for the wrong reason."""
        from test_story_frame import PREFOLDED

        for domain in available_domains():
            analysis = _folded_analysis(domain)
            host = int(analysis["recorded_days"])
            routed = int(get_adapter(domain).coverage_for(analysis)["recorded_days"])
            with self.subTest(domain=domain):
                if domain in PREFOLDED:
                    self.assertEqual(host, routed, "%s 是预折叠域，两个计数应当一致" % domain)
                else:
                    self.assertNotEqual(host, routed, "%s 的折叠没有发生，用例失去意义" % domain)

    def test_no_card_prints_more_recorded_days_than_the_window_holds(self):
        """The impossible pair, swept over the folding domains, templates and formats.

        `weight` is excluded, and the exclusion is the contract rather than a concession:
        its adapter passes the host's counts through untouched, so a host that declares
        fifteen recorded days in a fourteen-day window gets 「15 / 14 天」 printed back
        faithfully.  That is a defect in the caller, not in the renderer -- for weight the
        analysis *is* the authority on its own window, and a renderer that recomputed
        would be overruling it.  The seven folding domains have no such authority behind
        them, which is why they must be folded here.
        """
        pair = re.compile(r"(\d+)\s*/\s*(\d+)\s*天")
        for domain in _FOLDING_DOMAINS:
            analysis = _folded_analysis(domain)
            window = int(analysis["window_days"])
            for style in STYLE_CATALOG:
                for fmt in ("html", "svg"):
                    text = _text(_render(domain, style.id, fmt, analysis))
                    for recorded, denominator in pair.findall(text):
                        if int(denominator) != window:
                            continue  # a different ratio, not the coverage line
                        with self.subTest(domain=domain, style=style.id, format=fmt):
                            self.assertLessEqual(
                                int(recorded),
                                window,
                                "%s/%s 打印了 %s / %s 天" % (domain, style.id, recorded, denominator),
                            )

    def test_the_printed_count_is_the_adapters_count(self):
        """Not merely plausible -- the same number a frame consumer reads.

        `weight` is excluded for the reason given above; its agreement is already locked
        byte-for-byte by the golden digests, which is a stricter check than this one.
        """
        pair = re.compile(r"(\d+)\s*/\s*(\d+)\s*天")
        for domain in _FOLDING_DOMAINS:
            analysis = _folded_analysis(domain)
            window = int(analysis["window_days"])
            expected = int(get_adapter(domain).coverage_for(analysis)["recorded_days"])
            seen = 0
            for style in STYLE_CATALOG:
                text = _text(_render(domain, style.id, "html", analysis))
                for recorded, denominator in pair.findall(text):
                    if int(denominator) != window:
                        continue
                    seen += 1
                    with self.subTest(domain=domain, style=style.id):
                        self.assertEqual(
                            int(recorded),
                            expected,
                            "%s/%s 的覆盖数与适配器不一致" % (domain, style.id),
                        )
            with self.subTest(domain=domain):
                self.assertTrue(seen, "%s 没有任何模板打印覆盖行，用例无从校验" % domain)


class CoverageGeometryAgreesWithTheCoverageLineTests(unittest.TestCase):
    """The drawn calendar fills as many cells as the caption claims days.

    Three of the twelve family renderers size their geometry from `recorded_days` and
    `coverage_ratio` read off the analysis, not from the view the caption is built from.
    That made a second, quieter version of the same defect: `rhythm-calendar` printed
    「5 / 14 天」 under fourteen filled cells -- a picture of unbroken coverage above a
    caption admitting nine missing days.  The coverage-line tests above cannot see it,
    because the line they read was already right; only the drawing was wrong.
    """

    def test_filled_cells_match_the_printed_record_count(self):
        # Nine dates, not the full fourteen: `_rhythm_visual` fills
        # `min(recorded_days, window_days)`, so a fixture covering the whole window lets the
        # clamp swallow the defect -- an inflated 42 and an honest 14 both clamp to 14 and
        # the case passes without testing anything.  Nine leaves five cells that must stay
        # empty, and still clears the family's seven-day eligibility gate.
        cell = re.compile(r'<i class="(on)?"')
        for domain in _FOLDING_DOMAINS:
            analysis = _folded_analysis(domain, days=9)
            window = int(analysis["window_days"])
            expected = int(get_adapter(domain).coverage_for(analysis)["recorded_days"])
            for style in STYLE_CATALOG:
                if style.family != "rhythm":
                    continue
                markup = _render(domain, style.id, "html", analysis)
                marks = cell.findall(markup)
                with self.subTest(domain=domain, style=style.id):
                    self.assertEqual(
                        len(marks),
                        window,
                        "%s/%s 的格子数不等于窗口天数" % (domain, style.id),
                    )
                    self.assertEqual(
                        sum(1 for mark in marks if mark),
                        expected,
                        "%s/%s 填色格子数与覆盖数不一致" % (domain, style.id),
                    )

    def test_generative_geometry_does_not_read_the_hosts_row_count(self):
        """`_generative_visual` scales its node count by `recorded_days`.

        A host row count inflates the constellation past what the records support, so the
        densest possible drawing accompanies the sparsest coverage.  Comparing two renders
        -- one from the folded analysis, one from a host analysis already reporting the
        folded count -- pins the geometry to the adapter: identical inputs after folding
        must produce identical drawings.
        """
        for domain in _FOLDING_DOMAINS:
            folded = _folded_analysis(domain)
            expected = int(get_adapter(domain).coverage_for(folded)["recorded_days"])
            honest = dict(folded, recorded_days=expected, measurement_count=expected)
            for style in STYLE_CATALOG:
                if style.family != "generative":
                    continue
                with self.subTest(domain=domain, style=style.id):
                    self.assertEqual(
                        _render(domain, style.id, "html", folded),
                        _render(domain, style.id, "html", honest),
                        "%s/%s 的生成式几何跟随宿主行数而非适配器" % (domain, style.id),
                    )


class EligibilityCountsDaysNotRowsTests(unittest.TestCase):
    """A style gated at ten recorded days is not unlocked by ten rows on three dates.

    `min_recorded_days` reaches 14 across the catalog, and those gates are the only thing
    standing between a five-day window and a template built to narrate a fortnight.  Read
    off a host row count they stop holding: fifteen rows across five dates cleared a
    ten-day gate, and the card went on to tell a story its records could not support.  This
    is the evidence-threshold boundary, not a cosmetic mismatch, so it gets its own class
    rather than riding along on the render sweeps -- which cannot see it at all, since by
    the time a style is pinned the gate has already been passed or skipped.
    """

    def test_a_gate_above_the_folded_count_stays_shut(self):
        analysis = _folded_analysis("sleep", days=5)  # 15 rows, 5 dates
        routed = int(get_adapter("sleep").coverage_for(analysis)["recorded_days"])
        self.assertEqual(routed, 5)
        self.assertGreater(int(analysis["recorded_days"]), routed)  # the host says 15

        selection = select_weight_card_style(
            analysis, seed="eligibility", domain="sleep", lexicon=lexicon_for("sleep")
        )
        eligibility = selection["eligibility"]
        checked = 0
        for style in STYLE_CATALOG:
            if style.min_recorded_days <= routed:
                continue
            checked += 1
            with self.subTest(style=style.id, requires=style.min_recorded_days):
                self.assertFalse(
                    eligibility[style.id]["eligible"],
                    "%s 要求 %d 个记录日，却被 %d 行原始记录放行"
                    % (style.id, style.min_recorded_days, analysis["recorded_days"]),
                )
        self.assertTrue(checked, "没有任何模板的门槛高于折叠后的记录日数，用例无从校验")

    def test_a_gate_at_or_below_the_folded_count_still_opens(self):
        """The routed count must not be read as a reason to refuse everything.

        A normalisation that returned zero, or that dropped the key, would pass the test
        above for the wrong reason -- every gate shut, no card renderable.
        """
        analysis = _folded_analysis("sleep", days=5)
        routed = int(get_adapter("sleep").coverage_for(analysis)["recorded_days"])
        selection = select_weight_card_style(
            analysis, seed="eligibility", domain="sleep", lexicon=lexicon_for("sleep")
        )
        eligibility = selection["eligibility"]
        opened = [
            style.id
            for style in STYLE_CATALOG
            if style.min_recorded_days <= routed
            and not style.requires_trend
            and eligibility[style.id]["eligible"]
        ]
        self.assertTrue(opened, "折叠后的记录日数把所有模板都关掉了")

    def test_weight_keeps_the_analysis_it_was_handed(self):
        """`weight` is PREFOLDED, so normalising must be a no-op there.

        Its `coverage_for` passes the host's counts through, which is the contract that
        keeps the goldens byte-identical.  If normalisation ever recomputed for weight, the
        selector would start overruling `weight_truth_card` about its own window.
        """
        from shared.story.selector import _coverage_normalised

        analysis = _folded_analysis("weight", days=5)
        self.assertIs(_coverage_normalised(analysis, "weight"), analysis)

    def test_normalising_does_not_edit_the_callers_analysis(self):
        from shared.story.selector import _coverage_normalised

        analysis = _folded_analysis("sleep", days=5)
        before = dict(analysis)
        _coverage_normalised(analysis, "sleep")
        self.assertEqual(analysis, before)


def _ready(domain, *, per_day=1, days=len(DATES)):
    """The analysis a renderer actually receives from the CLI.

    `weight_truth_card.run` hands every non-weight domain through `render_ready`
    before drawing, so the frame -- and with it the folded, single-component series
    -- is on the analysis at render time.  The fixtures above deliberately stop
    short of that step, which is why the audits in this file could pass on cards
    that had drawn nothing at all.
    """
    base = _analysis(domain, days=days) if per_day == 1 else _folded_analysis(
        domain, per_day=per_day, days=days
    )
    return render_ready(domain, base)


def _plotted(analysis):
    from shared.story.render import _series_points

    return _series_points(analysis)


def _folded_days(domain, analysis):
    return int(get_adapter(domain).coverage_for(analysis)["recorded_days"])


class PlottedPointsComeFromTheFrameTests(unittest.TestCase):
    """A card with records must draw them, whatever key the rows spell them in.

    Every audit above reads the words on the card; none of them asked whether the
    card had any data on it.  So this went unreported: the renderer read magnitudes
    out of `analysis["daily_records"]` through `_point_value`, which understands
    `value` and `weight` and nothing else, while a sleep row spells its number
    `duration_min`, an intake row `total_calories`, an activity row a JSON payload.
    Six of the eight domains therefore plotted zero points on a full window and
    printed 「再记录一次，轨迹会从这里出现」 over fourteen days of records, with every
    unit-bearing statistic falling back to 「—」.

    The folded series was already being computed for all of them -- that is what an
    adapter's `series_for` is for, and `render_ready` puts it on the analysis as
    `frame["series"]` -- so the numbers were present and simply never read.  Weight
    is invisible to this whole class of defect because its rows happen to spell the
    magnitude in one of the two keys `_point_value` knew, which is exactly why the
    goldens stayed green while seven domains drew nothing.
    """

    def test_the_raw_rows_alone_would_not_plot(self):
        """Without this the rest of the class passes for the wrong reason."""
        from test_story_frame import PREFOLDED

        for domain in available_domains():
            with self.subTest(domain=domain):
                raw = _plotted(_analysis(domain))
                if domain in PREFOLDED:
                    self.assertTrue(raw, "%s 的原始行本就可读，用例对它无话可说" % domain)
                else:
                    self.assertFalse(
                        raw, "%s 的原始行已能直接绘制，用例失去意义" % domain
                    )

    def test_every_domain_plots_one_point_per_recorded_day(self):
        for domain in available_domains():
            ready = _ready(domain)
            with self.subTest(domain=domain):
                self.assertEqual(
                    len(_plotted(ready)),
                    _folded_days(domain, ready),
                    "%s 绘制的点数与有记录日数不一致" % domain,
                )

    def test_repeat_rows_on_one_day_plot_one_point(self):
        """Three rows a day is fourteen points, not forty-two.

        The plot and the printed 「有记录日」 count come from different code paths, so
        a renderer reading rows drew a denser trace than the number beside it while
        both looked individually plausible.
        """
        for domain in available_domains():
            ready = _ready(domain, per_day=3)
            with self.subTest(domain=domain):
                self.assertEqual(
                    len(_plotted(ready)),
                    _folded_days(domain, ready),
                    "%s 的同日多行被当成了多天" % domain,
                )

    def test_a_full_window_never_renders_the_empty_series_placeholder(self):
        for domain in available_domains():
            ready = _ready(domain)
            for style in STYLE_CATALOG:
                with self.subTest(domain=domain, style=style.id):
                    markup = _render(domain, style.id, "html", ready)
                    # The element, not the bare word: `.empty-signal` is declared in
                    # every card's stylesheet, so a substring check on the name alone
                    # would match all 24 styles in all 8 domains and never fail.
                    self.assertNotIn(
                        'class="empty-signal"',
                        markup,
                        "%s/%s 在满窗口上仍然显示空轨迹提示" % (domain, style.id),
                    )

    def test_every_domain_prints_a_magnitude_in_its_own_unit(self):
        """The stat block's fallback is 「—」, which reads as 'nothing recorded'."""
        for domain in available_domains():
            ready = _ready(domain)
            unit = lexicon_for(domain)["unit"]
            drawn = [
                style.id
                for style in STYLE_CATALOG
                if unit in _text(_render(domain, style.id, "html", ready))
            ]
            with self.subTest(domain=domain):
                self.assertTrue(
                    drawn, "%s 的 24 个模板没有一个印出带单位「%s」的数值" % (domain, unit)
                )

    def test_the_animated_beats_count_days_not_rows(self):
        """`_beat_css` promises one rule per recorded day; rows made it per row.

        The rules address plotted dots by `nth-child`, so forty-two rules over a
        fourteen-point trace aim two thirds of the timeline at elements that do not
        exist -- and the calendar gaps the motion grammar exists to make audible get
        buried under same-day repeats.
        """
        for domain in available_domains():
            ready = _ready(domain, per_day=3)
            style_id = STYLE_CATALOG[0].id
            markup = _render(domain, style_id, "svg", ready)
            with self.subTest(domain=domain):
                self.assertEqual(
                    markup.count("animation:ms-settle"),
                    _folded_days(domain, ready),
                    "%s 的节拍数不等于有记录日数" % domain,
                )


# The forecast profile, because it is the style that puts all four of the fields
# below on one card: the hero sentence quotes 今日 and 长期 inline, and the metric
# block prints each with its own label and note.  A break here is legible as a
# sentence rather than as a diff.
FORECAST_STYLE = "weather-now"


def _view_of(domain, analysis, **kwargs):
    """The rendered forecast card's visible text, for reading the metric block."""
    lexicon = lexicon_for(domain)
    selection = select_weight_card_style(
        analysis, pinned_style=FORECAST_STYLE, seed="cross-domain", domain=domain, lexicon=lexicon
    )
    markup = render_weight_story_html(
        analysis, selection, domain=domain, lexicon=lexicon, **kwargs
    )
    return _text(markup)


class TheLatestStepIsReadableInEveryDomainTests(unittest.TestCase):
    """The card's headline numbers came from `analyze_weight_records`' key names.

    `render.py` read `daily_delta`, `comparison_gap_days` and `latest_weight` off
    the analysis.  All three are spellings only weight's own analyser writes, so on
    the other seven domains every one of them was `None` and `_signed(None)` put
    「—」 where the reading belongs: 「今天的记录时长是 —」 on a sleep card that had
    fourteen recorded nights and a frame stating the step between the last two.

    This is the same defect as `PlottedPointsComeFromTheFrameTests` at a second
    site -- the frame was built, carried on the analysis, and not read -- so it is
    proven the same way: against the frame that was already there.
    """

    def _frame_trend(self, domain, analysis):
        return analysis["frame"]["trend"]

    def test_every_domain_prints_the_step_from_its_last_two_days(self):
        """The signed step is the frame's `latest_delta`, in the domain's own unit."""
        for domain in available_domains():
            ready = _ready(domain)
            expected = self._frame_trend(domain, ready).get("latest_delta")
            with self.subTest(domain=domain):
                self.assertIsNotNone(
                    expected, "%s 的 frame 没有给出最近一次变化，测试前提不成立" % domain
                )
                self.assertEqual(
                    ready.get("daily_delta"),
                    expected,
                    "%s 的 daily_delta 没有落到分析上" % domain,
                )
                text = _view_of(domain, ready)
                self.assertNotIn(
                    "等待下一次记录",
                    text,
                    "%s 在满窗口上仍然说等待下一次记录" % domain,
                )

    def test_every_domain_states_the_gap_it_compared_across(self):
        """Consecutive days must read 较昨日, not the fallback 较上次记录.

        The fixture records every day in the window, so 较上次记录 would be a card
        declining to say something it knows.  The gap is also what a member reads to
        tell a one-day step from a five-day one.
        """
        for domain in available_domains():
            ready = _ready(domain)
            with self.subTest(domain=domain):
                self.assertEqual(
                    ready.get("comparison_gap_days"),
                    1,
                    "%s 没有算出最近两个有记录日之间的日历间隔" % domain,
                )
                self.assertIn("较昨日", _view_of(domain, ready), "%s 未说明比较口径" % domain)

    def test_a_gap_in_the_records_is_counted_in_calendar_days(self):
        """Six recorded days ending three days apart compare 较上次记录, not 较昨日.

        A gap the member can see in their own log must not be narrated as if the two
        readings were adjacent; this is the same 未记录日不按 0 处理 rule the coverage
        line follows, applied to the comparison.
        """
        for domain in available_domains():
            payload = FIXTURES[domain]
            kept = [DATES[0], DATES[1], DATES[2], DATES[3], DATES[4], DATES[9]]
            records = [dict(payload(index), date=day) for index, day in enumerate(kept)]
            analysis = render_ready(
                domain,
                {
                    "window_days": 14,
                    "span_days": 14,
                    "daily_records": records,
                    "recorded_days": len(records),
                    "measurement_count": len(records),
                    "trend_claim_allowed": True,
                },
            )
            with self.subTest(domain=domain):
                self.assertEqual(
                    analysis.get("comparison_gap_days"),
                    5,
                    "%s 把日历间隔算错了" % domain,
                )
                self.assertIn(
                    "较上次记录",
                    _view_of(domain, analysis),
                    "%s 把隔了五天的两次记录说成昨日" % domain,
                )

    def test_the_exact_reading_is_available_to_show(self):
        """With the privacy flag on, the absolute reading must appear.

        `show_exact_weight` gates the one privacy-sensitive number on the card, and
        it read `latest_weight`.  On the other seven domains the flag therefore did
        nothing at all: the member asked to see their reading and the card kept
        saying it was hidden.
        """
        for domain in available_domains():
            ready = _ready(domain)
            series = ready["frame"]["series"]
            expected = float(series[-1]["value"])
            with self.subTest(domain=domain):
                self.assertAlmostEqual(
                    float(ready.get("latest_value")),
                    expected,
                    places=4,
                    msg="%s 的 latest_value 不是最后一个折叠点" % domain,
                )
                shown = _view_of(domain, ready, show_exact_weight=True)
                self.assertIn(
                    "当前 %.1f" % expected,
                    shown,
                    "%s 打开精确值后仍未显示当前读数" % domain,
                )
                self.assertNotIn("已隐藏", shown, "%s 打开精确值后仍说已隐藏" % domain)

    def test_weight_keeps_its_own_numbers(self):
        """Weight's analyser stays authoritative wherever it has already spoken.

        `render_ready` fills and never corrects, and these three keys are the test of
        that: `latest_weight` is rounded to three places by `analyze_weight_records`
        and the frame's own value is not, so a fill that overwrote would move the
        number the goldens are locked on.
        """
        pinned = {
            "daily_delta": -0.25,
            "comparison_gap_days": 4,
            "latest_value": 71.111,
            "latest_weight": 71.111,
        }
        ready = render_ready("weight", dict(_analysis("weight"), **pinned))
        for key, value in pinned.items():
            self.assertEqual(ready.get(key), value, "%s 被 render_ready 改写了" % key)


class TheLongRunNumberIsHonestInEveryDomainTests(unittest.TestCase):
    """长期 either carries a number or says it has none — never a dash under 稳健估计.

    The metric block prints 「长期气流」 with `trend_value` above `trend_note`, and the
    note read 稳健估计 whenever the *window* allowed a claim, with no regard for
    whether an estimate had actually been made.  On the seven domains that had no
    estimator that produced 「— / 稳健估计」: an empty value asserting a robust fit
    beneath it.  Two tests, because there are two ways to be honest here and the card
    needs both — print the fit when there is one, name its absence when there is not.
    """

    def test_every_domain_prints_its_long_run_change_with_a_unit(self):
        for domain in available_domains():
            ready = _ready(domain)
            expected = ready["frame"]["trend"].get("delta")
            with self.subTest(domain=domain):
                self.assertIsNotNone(expected, "%s 的 frame 没有给出长期变化量" % domain)
                self.assertEqual(
                    ready.get("trend_delta"), expected, "%s 的长期变化量没有落到分析上" % domain
                )
                text = _view_of(domain, ready)
                unit = lexicon_for(domain)["unit"]
                # Formatted through the renderer's own `_signed` rather than a local
                # `"%+.1f"`.  This test's claim is that the frame's number reaches the
                # card carrying its unit; how a sign is drawn is `_signed`'s claim, and
                # `SignedNumeralTests` below pins that separately.  Spelling the format
                # twice would make one of the two a silent second source of truth --
                # `adherence`'s +0.004 次/day rounds to a bare `0.0`, and a hand-written
                # `%+.1f` here would demand `+0.0`, i.e. a direction the fit never found.
                self.assertIn(
                    "%s %s" % (render._signed(expected), unit),
                    text,
                    "%s 的长期数字没有带单位印在卡上" % domain,
                )
                self.assertIn("稳健估计", text, "%s 有了拟合却不说明口径" % domain)

    def test_an_unfitted_window_says_so_instead_of_claiming_an_estimate(self):
        """`claim_allowed` with no fit is a real state, not a defect to paper over.

        One recorded component-day inside a multi-day window earns a coverage
        sentence but not a slope.  The card may print no number there; what it may
        not do is print 稳健估计 next to the dash that stands in for one.
        """
        for domain in available_domains():
            ready = dict(_ready(domain))
            ready.pop("trend_delta", None)
            ready["frame"] = dict(ready["frame"])
            ready["frame"]["trend"] = {
                key: value
                for key, value in ready["frame"]["trend"].items()
                if key not in ("delta", "slope_per_day", "method")
            }
            with self.subTest(domain=domain):
                text = _view_of(domain, ready)
                self.assertNotIn(
                    "稳健估计", text, "%s 在没有拟合的情况下声称稳健估计" % domain
                )
                # Anchored to the prose slot, not merely present somewhere on the card.
                # The metric block's note and the sentence are filled from two different
                # values, so 「暂无稳健拟合」 appearing anywhere would pass while the
                # sentence still read 长期气流为 —, which is the card declining to say
                # what it knows.  Both halves are asserted because either one alone
                # leaves the other free to regress.
                self.assertIn(
                    "长期气流为 暂无稳健拟合",
                    text,
                    "%s 的正文没有说明长期数字为何缺席" % domain,
                )
                self.assertNotIn(
                    "长期气流为 —",
                    text,
                    "%s 的正文用破折号代替了缺席的理由" % domain,
                )


class CompassDirectionContractTests(unittest.TestCase):
    """The compass carries unitless direction consistency, never raw cross-domain units."""

    STYLE_ID = "direction-course"
    ANGLE = re.compile(r'--angle:([+\-]?[0-9.]+)deg')

    def _angle(self, domain, analysis):
        markup = _render(domain, self.STYLE_ID, "html", analysis, seed="compass-contract")
        match = self.ANGLE.search(markup)
        self.assertIsNotNone(match, "%s 的罗盘没有输出角度" % domain)
        return float(match.group(1))

    def test_every_domain_points_in_the_sign_of_its_robust_change(self):
        for domain in available_domains():
            ready = _ready(domain)
            delta = float(ready["trend_delta"])
            angle = self._angle(domain, ready)
            with self.subTest(domain=domain, delta=delta):
                self.assertLessEqual(abs(angle), 28.0)
                if delta > 0:
                    self.assertGreater(angle, 0.0)
                elif delta < 0:
                    self.assertLess(angle, 0.0)
                else:
                    self.assertEqual(angle, 0.0)

    def test_missing_or_zero_change_points_north_and_is_deterministic(self):
        for domain in available_domains():
            for delta in (None, 0.0):
                ready = _ready(domain)
                ready["trend_delta"] = delta
                first = self._angle(domain, ready)
                second = self._angle(domain, ready)
                with self.subTest(domain=domain, delta=delta):
                    self.assertEqual(first, 0.0)
                    self.assertEqual(second, first)

    def test_physical_units_do_not_drive_every_domain_into_the_stop(self):
        angles = {
            domain: self._angle(domain, _ready(domain))
            for domain in ("activity", "intake", "sleep", "vitals")
        }
        self.assertNotIn(32.0, {abs(angle) for angle in angles.values()})
        self.assertGreaterEqual(len({abs(angle) for angle in angles.values()}), 3)

    def test_legacy_weight_without_a_frame_keeps_its_locked_angle(self):
        analysis = _ready("weight")
        analysis.pop("trend_visual_strength", None)
        analysis["trend_delta"] = -0.65
        self.assertEqual(self._angle("weight", analysis), -11.7)


class SignedNumeralTests(unittest.TestCase):
    """The one place a direction is drawn, pinned so the tests above can lean on it.

    `_signed` had no test of its own while eight domains' every printed delta went
    through it.  It carries three judgements that are editorial, not cosmetic, and each
    one is a way the card could lie about a number:

    * a sign is only drawn where a direction was actually measured -- a fit of
      +0.004 次/day prints `0.0`, unsigned, because 「+0.0」 asserts an upward drift the
      estimator did not find;
    * the minus is U+2212, not a hyphen, so a negative delta cannot be read as a
      list dash or line-broken away from its numeral;
    * an absent or non-finite value renders 「—」 rather than `0.0`, keeping 没有数字
      distinct from 数字是零.
    """

    def test_a_direction_is_only_signed_when_one_was_measured(self):
        self.assertEqual(render._signed(1.84), "+1.8")
        self.assertEqual(render._signed(0.0), "0.0")
        # Below the printing threshold: rounds to zero, so it must not claim a sign.
        self.assertEqual(render._signed(0.004), "0.0")
        self.assertEqual(render._signed(-0.004), "0.0")

    def test_a_negative_delta_uses_a_minus_sign_not_a_hyphen(self):
        self.assertEqual(render._signed(-2.17), "−2.2")
        self.assertNotIn("-", render._signed(-2.17))

    def test_a_missing_number_is_a_dash_not_a_zero(self):
        for absent in (None, "", "n/a", float("nan"), float("inf")):
            with self.subTest(value=absent):
                self.assertEqual(render._signed(absent), "—")
