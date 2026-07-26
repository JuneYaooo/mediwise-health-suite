"""Contract tests every registered domain adapter must satisfy.

Parameterized over `available_domains()` rather than written per domain, so the
remaining P3 domains are covered the moment they are registered instead of each
needing a bespoke test file.  A domain that cannot pass these is not wired in.

The point of the shared tests is the claim story-system.md makes: adding a domain
costs one module and one lexicon, not a template or a copy file.  That claim is
only true if the engine can rely on adapters behaving identically, so these
assertions are the interface the promise rests on.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.story.adapters import (
    COPY_SLOTS,
    available_domains,
    companions_for,
    get_adapter,
    lexicon_for,
    register,
)
from shared.story.catalog import STYLE_CATALOG

SCHEMA_PATH = ROOT / "story-design" / "signal-frame.schema.json"
CONTRACT_PATH = ROOT / "story-design" / "story-system.md"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
PROPS = SCHEMA["properties"]

VALID_SHAPES = set(PROPS["shape"]["enum"])
VALID_DOMAINS = set(PROPS["domain"]["enum"])
VALID_FOLDS = set(PROPS["series_meta"]["properties"]["fold"]["enum"])
LEXICON_SCHEMA = PROPS["lexicon"]

# story-system.md line 43: up/down describe numeric direction only. These are the
# words that would turn a reading into a verdict.
EVALUATIVE = ("成功", "失败", "进步", "退步", "达标", "失守", "超标", "合格", "优秀", "糟")

# What each domain's words are, split by whether the word is the domain's alone.
#
# `own` is wording that could only have come from this domain: fine on its own card,
# a leak anywhere else.  Every shared surface -- the catalog here, the copy tables
# in render.py, the SVG builder -- is checked against the union, which catches a
# leak where it was written rather than on whichever card it lands on.
#
# `never` is this domain's own subject matter that must not reach any card at all,
# including its own.  These are the interpretations the product refuses to make:
# 深睡 / REM / 睡眠质量 are nowhere in sleep's lexicon, and the adapter is built so
# that it cannot read `_quality_score` or the `_IDEAL_*` thresholds that would
# produce them.  Kept apart from `own` because `forbidden_for` subtracts a domain's
# own words when auditing its card, which would otherwise exempt exactly these.
#
# `shared` is the opposite claim, and it exists because it is a real one: records'
# subject is 记录 and its unit is 次, words any domain's copy may legitimately use
# ("第一次记录" is not a records leak).  Naming them makes the exemption a decision
# with an author rather than an absence nobody notices.  Deriving these lists from
# the LEXICONs instead would flag those two everywhere.
#
# `test_every_lexicon_value_is_declared_own_or_shared` fails until a newly
# registered domain classifies its words, so the matrix cannot stop covering one.
DOMAIN_VOCABULARY = {
    "weight": {
        "own": ("体重", "秤面", "公斤", "千克", "kg", "减重", "上浮", "回落"),
        "never": ("BMI", "体脂", "胖瘦", "肥胖", "超重", "理想体重"),
        "shared": ("每日中位数", "有记录日"),
    },
    "sleep": {
        "own": ("睡眠", "分钟", "变长", "变短"),
        "never": ("深睡", "浅睡", "REM", "睡眠质量", "睡眠障碍", "失眠", "睡眠评分"),
        "shared": ("记录时长", "每日记录时长", "有记录日"),
    },
    "records": {
        "own": ("记录动作", "变密", "变疏"),
        "never": (),
        "shared": ("记录", "次", "每日记录次数", "有记录日"),
    },
    # Vitals narrates one component at a time, so `own` covers every component's
    # wording rather than only the default one's -- systolic's 收缩压 must not reach
    # a sleep card whether or not today's vitals card happens to be about it.
    #
    # `never` is where this domain's refusal lives, and it is the longest list here
    # because vitals is the domain readers most want interpreted.  正常 / 偏高 /
    # 参考范围 are the reference-range verdicts `_METRIC_RANGES` and `_VALUE_RANGES`
    # could produce and that this adapter is built not to read; 高血压 / 发热 /
    # 心律不齐 / 缺氧 are diagnoses.  Note 走高 sits in `own` and 偏高 in `never`:
    # the first says the number moved, the second says it is too much.
    "vitals": {
        "own": (
            "心率", "收缩压", "舒张压", "血压", "体温", "血氧",
            "mmHg", "次/分", "℃", "走高", "走低",
        ),
        "never": (
            "正常范围", "参考范围", "偏高", "偏低", "异常值",
            "高血压", "低血压", "发热", "发烧", "心律不齐", "缺氧",
        ),
        "shared": ("记录", "次", "有记录日", "同日多次取中位数"),
    },
    # `own` covers all five components, not just the default one, for the same
    # reason vitals' does: `component_for` can put 蛋白质 or 膳食纤维 on the card
    # instead of 热量, and a word only reachable on some cards is still a word no
    # other domain may print.  `克` is deliberately shared and not own — CJK words
    # match as plain substrings, and `诚实克制` in the catalog would otherwise
    # report as an intake leak on every template.
    #
    # `never` is the goal apparatus.  `diet-tracker/scripts/nutrition_goal.py`
    # computes 达标区间, 达标率 and 低于/高于目标范围; `synthesis.py` names 热量缺口
    # only to refuse it.  A card here may say 「这天记录了 1850 千卡」 and may never
    # turn that into a verdict against a target.
    "intake": {
        "own": ("热量", "千卡", "kcal", "蛋白质", "脂肪", "碳水", "膳食纤维", "纤维",
                "饮食", "摄入", "餐", "变多", "变少"),
        "never": ("热量目标", "营养目标", "目标范围", "达标区间", "达标率", "热量缺口",
                  "能量缺口", "营养不良", "营养失衡", "暴食", "节食", "忌口", "食谱",
                  "减脂", "增肌"),
        "shared": ("记录", "次", "克", "有记录日", "同日多餐累计"),
    },
    # Three words are conspicuously absent from `own`, each because shared code
    # already prints it: `步` appears in 最大单步起伏 (`render.py:582`, `:788`,
    # `:894`), `距离` in 「最新{reading}与稳健趋势之间的距离」 on `direction-course`
    # (`catalog.py:154`), and `运动` throughout `motion.py`'s 运动语法.  Claiming any
    # of them would report a leak on templates that have nothing to do with this
    # domain.  步数 is the specific word, and it is clean everywhere.
    #
    # 变多 / 变少 are `own` here and also `own` for intake.  That is not a conflict:
    # `forbidden_for` subtracts each domain's own words from what it is checked
    # against, so a word two domains share is simply exempt on both their cards.
    #
    # `never` is the effort apparatus this adapter refuses to read --
    # `calculate_tdee`'s 活动水平 multipliers and 基础代谢 (`metric_utils.py:132-149`)
    # and Garmin's training score (`garmin.py:697`).  达标 / 超标 need no entry, they
    # are in `EVALUATIVE` already.  A card may say 「这天记录了 8200 步」 and may never
    # turn that into 久坐 or 消耗不足.
    #
    # The expenditure entry is `TDEE`, not the bare 总消耗 it is named after.  Weight's
    # 运动 companion tile already prints 「不是全天总消耗」 (`render.py:868`), a refusal
    # written long before this domain had an adapter, and it renders on weight cards
    # because weight declares activity a companion so the profile is never swapped for
    # `own-change` (`render.py:898`).  `hits()` cannot tell a refusal from a claim -- only
    # `_unrefused` in the cross-domain suite scopes a negator to its clause -- and
    # `forbidden_for` unions `never` into every domain's list regardless of companionship,
    # so listing 总消耗 would report that refusal as a leak.  `TDEE` is the apparatus'
    # own name, it is ASCII so it matches whole-token, and 消耗不足 still catches the
    # verdict form.  Left open: a card asserting 全天总消耗 outright would pass.  Nothing
    # computes it -- activity carries no calories component at all, deliberately, to keep
    # off intake's 千卡 -- and closing it properly means rewording shared copy, which
    # drifts the weight goldens and is not a new domain's business.
    "activity": {
        "own": ("步数", "变多", "变少"),
        "never": ("未达标", "久坐", "基础代谢", "活动水平", "TDEE", "消耗不足",
                  "运动强度", "训练效果", "卡路里消耗"),
        "shared": ("记录", "次", "距离", "米", "有记录日", "同日多次同步"),
    },
    # 用药 sits in `own`, which reads backwards for the domain that refuses the most.
    # It is there because this adapter's `PRESCRIPTION_NOUN` is 用药方案, so
    # `DISCLAIMER_TEMPLATE` (`render.py:40`) prints 「本卡不提供诊断或用药方案」 on all
    # 24 of its cards.  A `never` entry is checked by `hits`, which cannot see the
    # 不提供 in front of it, so declaring it refused would report the refusal itself.
    # The sentence that declines a thing has to be allowed to name it.  Everything
    # this domain must not *do* with 用药 -- 停药, 加量, 减量, 换药 -- is refused
    # separately, and none of those is inside 用药方案.
    #
    # 变密 / 变疏 are records' own words as well, the same overlap intake and activity
    # have on 变多 / 变少: both domains measure how densely something got written down,
    # so a second word pair would imply a difference that is not there.
    #
    # `never` is the adherence apparatus.  `check_medication_adherence`
    # (`health_advisor.py:337-378`) divides logged doses by an expected count and
    # raises a `warning` under half; `check_pairwise_interactions`
    # (`drug_interaction.py:369`) grades pairs Major/Moderate.  A card here may say
    # 「这天记录了 2 次服药」 and may never turn a thin day into 漏服 -- an unrecorded day
    # is a day nobody wrote anything down, and someone may have taken every dose and
    # logged none of them.  按时服药 is listed rather than bare 按时 because the timing
    # claim is what is refused, and the entry has to survive `hits`' substring match
    # against 服药 in `own`: 按时服药 contains it, so the pair must be tested together
    # or the longer word would be unreachable.
    #
    # Absent from every list: 药名 and anything derived from it.  The adapter does not
    # read `medication_name` at all, so there is no wording to police -- a drug name
    # on a shareable card discloses a diagnosis, and so does a count of distinct ones.
    "adherence": {
        "own": ("服药", "剂次", "用药", "变密", "变疏"),
        "never": ("依从性", "依从率", "服药率", "漏服", "按时服药", "停药", "加量",
                  "减量", "换药", "相互作用", "禁忌", "疗效", "副作用"),
        "shared": ("记录", "次", "有记录日", "同日多剂累计"),
    },
    # 照护 is `own` for exactly the reason 用药 is: this adapter's
    # `PRESCRIPTION_NOUN` is 照护方案, so 「本卡不提供诊断或照护方案」 prints on all 24
    # of its cards, and a word shared code prints inside a refusal cannot be
    # declared refused.
    #
    # 变多 / 变少 are `own` here and also intake's and activity's -- the third such
    # overlap, licensed by the same note above: `forbidden_for` subtracts each
    # domain's own words before checking, so a word several domains share is
    # exempt on all their cards.  This domain counts how many people wrote, so the
    # honest direction words are the plain ones.
    #
    # `never` is the identity apparatus, and it is short because the adapter reads
    # so little that most of the danger never becomes wording.  需要关注 is
    # `briefing_report.py`'s family verdict (「{count} 人需要关注」); 家族史 and 遗传 are
    # the inference two members sharing a metric invites and this domain declines
    # to draw; 过敏, 病史 and 血型 are `family_overview` columns
    # (`query.py:484-534`) that a shareable card may not carry.
    #
    # Absent from every list: 姓名 / 关系 / 诊断 and the rest of that query's
    # identity fields, because the adapter reads only `member_id` and a date, so
    # there is no wording to police.  诊断 in particular could not be refused even
    # if it were tempting -- it is already in the shared disclaimer on every
    # domain's cards.  排名 is likewise undeclared: both its occurrences in
    # `shared/` are inside refusals, and either list would report them as leaks.
    # 人数 is undeclared for the same reason, 个人数据 in `catalog.py:158` contains
    # it.  The anti-comparison rule is enforced by the adapter reading no
    # per-member quantity at all, not by a word list.
    "family": {
        "own": ("家庭", "家人", "照护", "变多", "变少"),
        "never": ("家族史", "遗传", "需要关注", "过敏", "病史", "血型"),
        "shared": ("记录", "次", "有记录日", "同一人同日只计一次"),
    },
}

# Interpretations no domain may print, whoever's card it is.
NEVER_WORDS = tuple(
    sorted({word for entry in DOMAIN_VOCABULARY.values() for word in entry["never"]})
)

FOREIGN_WORDS = tuple(
    sorted({word for entry in DOMAIN_VOCABULARY.values() for word in entry["own"]})
)

# What shared code may not contain: no domain's wording, and no refused reading.
POLICED_WORDS = tuple(sorted(set(FOREIGN_WORDS) | set(NEVER_WORDS)))


def forbidden_for(domain):
    """Words that must not appear on this domain's card.

    Every other domain's `own` wording, minus anything this domain also claims --
    a word two domains share is not evidence of a leak, and subtracting keeps the
    check honest as domains accumulate (分钟 will be sleep's and activity's both).
    Plus every `never` word from every domain, including this one's.

    Declared companions are exempt.  Weight reads 摄入、运动、睡眠 out of the lifestyle
    databases, so "睡眠记录 0 天" on a weight card is a coverage disclosure about a
    relationship the domain really has -- it tells the reader what to record next.  A
    domain that declares no companions gets no such exemption, which is the whole
    difference: the same sentence on a records card would assert a relationship its
    schema does not have.
    """
    entry = DOMAIN_VOCABULARY.get(domain, {})
    mine = set(entry.get("own", ())) | set(entry.get("shared", ()))
    for companion in companions_for(domain):
        companion_entry = DOMAIN_VOCABULARY.get(companion, {})
        mine |= set(companion_entry.get("own", ())) | set(companion_entry.get("shared", ()))
    foreign = {word for word in FOREIGN_WORDS if word not in mine}
    return tuple(sorted(foreign | set(NEVER_WORDS)))


def hits(text, words):
    """Return which of `words` appear in `text`.

    ASCII words match on a whole-token basis: `kg` as a plain substring finds the
    `kg` inside `background`, which cost an earlier audit a false positive.
    """
    found = []
    for word in words:
        if word.isascii():
            if re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(word), text, re.I):
                found.append(word)
        elif word in text:
            found.append(word)
    return found


def _analysis(dates, *, repeats=None, values=None, minutes=None, readings=None,
              calories=None, steps=None, window_days=14):
    """Build a minimal host analysis carrying only recording dates.

    Shaped like what `weight_truth_card` produces, since that is the only real
    producer today, but with just the keys an adapter is entitled to read.

    `values` is weight's reading, `minutes` is sleep's, `readings` is vitals'
    (heart rate, its default component), `calories` is intake's and `steps` is
    activity's; a record may carry all five, since an adapter reads its own key and
    ignores the rest.  Passing only `values` to a series test would let the others
    pass it vacuously — no readable day means no point to get wrong — so the shared
    tests below hand over each one.  Intake's number has to be above zero to be read
    at all: `total_calories` is `REAL DEFAULT 0` on `diet_records`, so the adapter
    treats a zero as a row nobody itemised rather than as a day of eating nothing.

    `steps` lands on a bare `count` key rather than inside a JSON `value` payload,
    which is the other shape activity's `_component_value` accepts.  Real sync rows
    carry the payload; this fixture takes the simpler branch on purpose, so the
    fallback that keeps hand-entered rows readable is exercised by the shared tests
    too.  No `source` is set either, which leaves the device-swap gate quiet — a
    fixture with no hardware attached has no swap to report.
    """
    records = []
    for index, day in enumerate(dates):
        item = {"date": day}
        if repeats:
            item["measurement_count"] = repeats[index]
        if values:
            item["weight"] = values[index]
        if minutes:
            item["duration_min"] = minutes[index]
        if readings:
            item["heart_rate"] = readings[index]
        if calories:
            item["total_calories"] = calories[index]
        if steps:
            item["count"] = steps[index]
        records.append(item)
    return {
        "window_days": window_days,
        "daily_records": records,
        "recorded_days": len(records),
        "span_days": window_days,
    }


class EveryAdapterTests(unittest.TestCase):
    """Run for each registered domain. Failures name the domain."""

    def test_registry_is_not_empty_and_every_domain_is_known_to_the_schema(self):
        domains = available_domains()
        self.assertTrue(domains)
        for domain in domains:
            self.assertIn(domain, VALID_DOMAINS, domain)
            self.assertEqual(get_adapter(domain).DOMAIN, domain)

    def test_every_lexicon_fills_every_slot_the_templates_read(self):
        """A missing slot renders as an empty string, not an error.

        That is the failure mode worth guarding: the card would still render,
        just with a blank where a noun belongs, and no test would notice.
        """
        for domain in available_domains():
            lexicon = lexicon_for(domain)
            for field in LEXICON_SCHEMA["required"]:
                self.assertIn(field, lexicon, "%s/%s" % (domain, field))
                self.assertTrue(str(lexicon[field]).strip(), "%s/%s" % (domain, field))
            for field, value in lexicon.items():
                spec = LEXICON_SCHEMA["properties"].get(field)
                self.assertIsNotNone(spec, "%s/%s 不在 schema 中" % (domain, field))
                self.assertLessEqual(
                    len(str(value)), spec["maxLength"], "%s/%s 超长" % (domain, field)
                )

    def test_direction_words_stay_neutral_in_every_domain(self):
        """The one contract rule that applies to all domains, not just weight."""
        for domain in available_domains():
            lexicon = lexicon_for(domain)
            for field in ("up", "down"):
                word = str(lexicon[field])
                for banned in EVALUATIVE:
                    self.assertNotIn(banned, word, "%s/%s: %s" % (domain, field, word))
            self.assertNotEqual(lexicon["up"], lexicon["down"], domain)

    def test_every_state_maps_onto_a_shape_the_schema_declares(self):
        """Copy is keyed on shapes, so an unknown shape has no copy to render."""
        for domain in available_domains():
            mapping = get_adapter(domain).SHAPE_BY_STATE
            self.assertTrue(mapping, domain)
            for state, shape in mapping.items():
                self.assertIn(shape, VALID_SHAPES, "%s/%s -> %s" % (domain, state, shape))

    def test_every_domain_can_reach_the_insufficient_shape(self):
        """Zero data is a first-class case, not an error path.

        story-system.md requires at least one template to survive zero data; that
        template is only reachable if the adapter can report `insufficient`, so
        every domain needs a route to it rather than a nearest-guess shape.
        """
        for domain in available_domains():
            self.assertIn("insufficient", set(get_adapter(domain).SHAPE_BY_STATE.values()), domain)

    def test_zero_data_never_produces_a_trend_claim(self):
        """No records means no direction, in every domain."""
        empty = _analysis([])
        for domain in available_domains():
            adapter = get_adapter(domain)
            self.assertEqual(adapter.shape_for(empty), "insufficient", domain)
            if hasattr(adapter, "trend_direction"):
                self.assertIsNone(adapter.trend_direction(empty), domain)

    def test_shape_for_is_total_over_junk_input(self):
        """Adapters run on real databases, where rows are missing and malformed.

        A adapter that raises on a malformed row takes the whole card down; the
        contract's answer to bad data is a lower-confidence shape, never an
        exception. Junk here is what a partially-written record actually looks
        like: absent keys, nulls, wrong types, unparseable dates.
        """
        junk = {
            "window_days": 14,
            "daily_records": [
                {},
                {"date": None},
                {"date": "not-a-date"},
                {"date": "2026-07-03", "measurement_count": None},
                "not-a-mapping",
                {"date": "2026-07-05", "measurement_count": "two"},
            ],
        }
        for domain in available_domains():
            adapter = get_adapter(domain)
            self.assertIn(adapter.shape_for(junk), VALID_SHAPES, domain)
            for helper in ("trend_direction", "coverage_for", "series_for"):
                if hasattr(adapter, helper):
                    getattr(adapter, helper)(junk)

    def test_direction_is_only_ever_up_down_stable_or_unknown(self):
        """The renderer indexes the lexicon with this, so it cannot be free text."""
        analysis = _analysis(
            ["2026-07-%02d" % day for day in range(1, 13)],
            values=[72.0 - index * 0.1 for index in range(12)],
        )
        for domain in available_domains():
            adapter = get_adapter(domain)
            if not hasattr(adapter, "trend_direction"):
                continue
            self.assertIn(adapter.trend_direction(analysis), ("up", "down", "stable", None), domain)

    def test_series_fold_is_a_declared_operation(self):
        for domain in available_domains():
            adapter = get_adapter(domain)
            if hasattr(adapter, "SERIES_FOLD"):
                self.assertIn(adapter.SERIES_FOLD, VALID_FOLDS, domain)

    def test_series_and_coverage_agree_on_how_many_days_were_recorded(self):
        """Two numbers on the same card, computed twice; they must not disagree.

        The series drives the plot and the calendar-mapped beats; coverage drives
        the 口径 line. A card claiming 8 有记录日 above a 6-point plot is the kind
        of quiet inconsistency a reader does catch.
        """
        analysis = _analysis(
            ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-09", "2026-07-10"],
            repeats=[1, 2, 1, 1, 3],
            values=[72.0, 71.8, 71.9, 71.4, 71.5],
            minutes=[452, 470, 461, 438, 445],
            readings=[64, 66, 63, 68, 65],
            calories=[1820, 1960, 1780, 1710, 2040],
            steps=[6200, 7400, 6800, 5100, 7900],
        )
        for domain in available_domains():
            adapter = get_adapter(domain)
            if not (hasattr(adapter, "series_for") and hasattr(adapter, "coverage_for")):
                continue
            series = adapter.series_for(analysis)
            coverage = adapter.coverage_for(analysis)
            self.assertEqual(len(series), coverage["recorded_days"], domain)
            self.assertEqual(
                sum(point["count"] for point in series), coverage["measurement_count"], domain
            )

    def test_series_is_ascending_and_carries_its_repeat_count(self):
        """`count` > 1 is what gates the double-exposure moment in the schema.

        It was silently pinned to 1 for weight because `series_for` read a key no
        producer emits. Asserting the value here rather than just its presence is
        what makes that class of miss visible.
        """
        analysis = _analysis(
            ["2026-07-01", "2026-07-04", "2026-07-05"],
            repeats=[1, 3, 1],
            values=[72.0, 71.6, 71.7],
            minutes=[452, 468, 455],
            readings=[64, 67, 65],
            calories=[1820, 1940, 1860],
            steps=[6200, 7100, 6600],
        )
        for domain in available_domains():
            adapter = get_adapter(domain)
            if not hasattr(adapter, "series_for"):
                continue
            series = adapter.series_for(analysis)
            dates = [point["date"] for point in series]
            self.assertEqual(dates, sorted(dates), domain)
            self.assertEqual(max(point["count"] for point in series), 3, domain)
            for point in series:
                self.assertGreaterEqual(point["count"], 1, domain)


class SharedCatalogTests(unittest.TestCase):
    """The 24-template catalog is one table shared by every domain.

    Nothing in it may name a domain, a unit or a metric: the same row renders a
    weight card and a sleep card, so a literal there prints unchanged on both.
    Where a string must say what is being measured it carries a `{reading}` /
    `{subject}` slot the renderer fills from the caller's lexicon.

    Two of these leaks shipped before this test existed, both in `signature`, which
    is why a static check earns its place beside the render matrix: grepping the
    renderers for 体重 found nothing, because the string was never in a renderer.
    """

    def _strings(self, style):
        """Every authored string on a catalog row, keyed by field."""
        out = {}
        for field, value in vars(style).items():
            if isinstance(value, str):
                out[field] = value
            elif isinstance(value, tuple):
                for index, item in enumerate(value):
                    if isinstance(item, str):
                        out["%s[%d]" % (field, index)] = item
        return out

    def test_no_catalog_string_names_a_domain(self):
        """Reports every leak in one run, since these tend to arrive in batches."""
        leaks = []
        for style in STYLE_CATALOG:
            for field, text in self._strings(style).items():
                if field == "id" or field.startswith(("preferred_domains", "required_domains")):
                    continue
                for word in hits(text, POLICED_WORDS):
                    leaks.append("%s.%s: %s -- %s" % (style.id, field, word, text))
        self.assertEqual(leaks, [], "\n".join(["catalog 泄漏域词:"] + leaks))

    def test_every_slot_a_catalog_string_carries_is_one_the_renderer_fills(self):
        """An unknown slot renders as an empty string, so it fails silently."""
        for style in STYLE_CATALOG:
            for field, text in self._strings(style).items():
                for token in re.findall(r"\{([a-z_]+)\}", text):
                    self.assertIn(token, COPY_SLOTS, "%s.%s: {%s}" % (style.id, field, token))

    def test_a_catalog_string_stays_clear_of_verdicts(self):
        for style in STYLE_CATALOG:
            for field, text in self._strings(style).items():
                for banned in EVALUATIVE:
                    if banned in text and not re.search(r"[不非无未]{0,1}.{0,2}%s" % banned, text):
                        self.fail("%s.%s: %s" % (style.id, field, text))

    def test_every_lexicon_value_is_declared_own_or_shared(self):
        """Each word a lexicon introduces is either policed or knowingly exempt.

        This is what makes the leak matrix self-maintaining.  The hole it closes is
        the one `秤面` fell through: a word can be a domain's own and still travel
        into shared code unnoticed, because the forbidden list was written by hand
        and simply did not mention it.  Here the lexicon is the source of the
        question and the author has to answer it for every value.
        """
        for domain in available_domains():
            self.assertIn(domain, DOMAIN_VOCABULARY, domain)
            entry = DOMAIN_VOCABULARY[domain]
            self.assertTrue(entry["own"], domain)
            for key in ("own", "never", "shared"):
                self.assertIn(key, entry, "%s/%s" % (domain, key))
            declared = tuple(entry["own"]) + tuple(entry["shared"])
            for field, word in lexicon_for(domain).items():
                word = str(word)
                if field == "fold_note" or len(word) < 2:
                    continue
                self.assertTrue(
                    any(part in word for part in declared),
                    "%s/%s=%s 未在 DOMAIN_VOCABULARY 中分类" % (domain, field, word),
                )

    def test_no_lexicon_contains_a_word_no_card_may_print(self):
        """A `never` word in a lexicon would be printed by every template at once.

        The lexicon is the one thing the renderers are required to trust, so this
        is where a refused reading would do the most damage: sleep naming 深睡 as
        its `reading` would put a stage breakdown on all 24 cards, and no
        renderer test would object, because the renderer did its job.
        """
        for domain in available_domains():
            for field, word in lexicon_for(domain).items():
                leaked = hits(str(word), NEVER_WORDS)
                self.assertEqual(leaked, [], "%s/%s: %s" % (domain, field, leaked))

    def test_no_word_is_claimed_as_own_by_one_domain_and_shared_by_another(self):
        """Otherwise the matrix would forbid a word it elsewhere permits."""
        for domain, entry in DOMAIN_VOCABULARY.items():
            for word in entry["shared"]:
                for other, other_entry in DOMAIN_VOCABULARY.items():
                    if other == domain:
                        continue
                    clash = [own for own in other_entry["own"] if own in word]
                    self.assertEqual(
                        clash, [], "%s 的 shared 词 %s 与 %s 的 own 冲突" % (domain, word, other)
                    )


class RecordsDomainTests(unittest.TestCase):
    """The records domain: recording behaviour as the subject, no reading at all."""

    def setUp(self):
        self.adapter = get_adapter("records")

    def test_lexicon_matches_the_column_the_contract_specifies(self):
        """The lexicon is a transcription, so drift from the contract is a bug."""
        contract = CONTRACT_PATH.read_text(encoding="utf-8")
        for field in ("subject", "reading", "unit", "up", "down", "series_label", "scope_label"):
            self.assertIn(str(self.adapter.LEXICON[field]), contract, field)

    def test_it_reads_dates_and_never_the_reading(self):
        """The structural reason this domain cannot express a health judgement.

        Same recording dates, wildly different underlying values — one plausible
        weight series, one absurd. If any output differs, the adapter is reading a
        reading, and a domain whose subject is 记录行为 would be smuggling a
        verdict about the body into a card about note-taking habits.
        """
        dates = ["2026-07-%02d" % day for day in range(1, 13)]
        plausible = _analysis(dates, values=[72.0 - index * 0.15 for index in range(12)])
        absurd = _analysis(dates, values=[41.0 + index * 9.0 for index in range(12)])
        self.assertEqual(self.adapter.shape_for(plausible), self.adapter.shape_for(absurd))
        self.assertEqual(
            self.adapter.trend_direction(plausible), self.adapter.trend_direction(absurd)
        )
        self.assertEqual(self.adapter.coverage_for(plausible), self.adapter.coverage_for(absurd))
        self.assertEqual(self.adapter.series_for(plausible), self.adapter.series_for(absurd))

    def test_series_plots_counts_not_readings(self):
        analysis = _analysis(
            ["2026-07-01", "2026-07-02"], repeats=[1, 4], values=[72.0, 71.5]
        )
        self.assertEqual(
            self.adapter.series_for(analysis),
            [
                {"date": "2026-07-01", "value": 1.0, "count": 1},
                {"date": "2026-07-02", "value": 4.0, "count": 4},
            ],
        )

    def test_a_resumed_break_reads_as_rebuilding(self):
        """The shape story-system.md wrote for exactly this domain.

        Seven blank days, then the tail picks up again: 断档后重新接上. Density
        alone would have called this 变密 and described the tail while ignoring
        the hole, which is the less truthful sentence about the window.
        """
        analysis = _analysis(
            [
                "2026-07-01", "2026-07-02", "2026-07-03",
                "2026-07-11", "2026-07-12", "2026-07-13", "2026-07-14",
            ],
            window_days=14,
        )
        self.assertEqual(self.adapter.state_for(analysis), "resumed_after_break")
        self.assertEqual(self.adapter.shape_for(analysis), "rebuilding")
        self.assertEqual(self.adapter.coverage_for(analysis)["longest_gap_days"], 7)

    def test_a_break_still_open_is_not_rebuilding(self):
        """Nothing has been rebuilt while the silence is still the newest thing.

        Same gap as above, but the window ends inside it. Calling this 恢复 would
        congratulate someone for a return that has not happened.
        """
        analysis = _analysis(
            ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-12"],
            window_days=14,
        )
        self.assertNotEqual(self.adapter.state_for(analysis), "resumed_after_break")

    def test_consecutive_days_report_no_gap(self):
        """Off-by-one guard: the gap is what is missing between two days, not the span."""
        analysis = _analysis(["2026-07-01", "2026-07-02", "2026-07-03"], window_days=14)
        self.assertEqual(self.adapter.coverage_for(analysis)["longest_gap_days"], 0)
        self.assertEqual(self.adapter.shape_for(analysis), "stable")

    def test_thinning_and_densifying_are_symmetric(self):
        dense_then_sparse = _analysis(
            ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-08", "2026-07-12"],
            window_days=14,
        )
        self.assertEqual(self.adapter.trend_direction(dense_then_sparse), "down")
        sparse_then_dense = _analysis(
            ["2026-07-01", "2026-07-05", "2026-07-09", "2026-07-10", "2026-07-11", "2026-07-12"],
            window_days=14,
        )
        self.assertEqual(self.adapter.trend_direction(sparse_then_dense), "up")

    def test_a_single_recorded_day_cannot_support_any_shape_but_insufficient(self):
        analysis = _analysis(["2026-07-01"], repeats=[6], window_days=14)
        self.assertEqual(self.adapter.shape_for(analysis), "insufficient")
        self.assertIsNone(self.adapter.trend_direction(analysis))
        # The one record is still counted; insufficient describes the claim, not the data.
        self.assertEqual(self.adapter.coverage_for(analysis)["measurement_count"], 6)

    def test_it_never_treats_an_unrecorded_day_as_zero(self):
        """The analysis boundary in story-system.md, checked structurally.

        A zero-valued point would plot as a real observation of 'no records',
        which is a different claim from 'nobody recorded'.
        """
        analysis = _analysis(["2026-07-01", "2026-07-09"], window_days=14)
        series = self.adapter.series_for(analysis)
        self.assertEqual(len(series), 2)
        self.assertTrue(all(point["value"] > 0 for point in series))

    def test_a_precomputed_state_is_honoured_but_a_foreign_one_is_not(self):
        """`state` belongs to whichever domain produced the analysis.

        Honouring it would let a weight state be misread as a recording state, so
        this domain reads `recording_state` and derives its own otherwise.
        """
        dates = ["2026-07-%02d" % day for day in range(1, 8)]
        borrowed = _analysis(dates, window_days=14)
        borrowed["state"] = "sustained_down"
        self.assertEqual(self.adapter.state_for(borrowed), "steady")
        declared = _analysis(dates, window_days=14)
        declared["recording_state"] = "thinning"
        self.assertEqual(self.adapter.state_for(declared), "thinning")

    def test_repeat_days_counts_days_not_extra_entries(self):
        analysis = _analysis(
            ["2026-07-01", "2026-07-02", "2026-07-03"], repeats=[1, 4, 2], window_days=14
        )
        coverage = self.adapter.coverage_for(analysis)
        self.assertEqual(coverage["repeat_days"], 2)
        self.assertEqual(coverage["measurement_count"], 7)
        self.assertEqual(coverage["recorded_days"], 3)


class SleepDomainTests(unittest.TestCase):
    """The sleep domain: a duration reading, folded by mean, never judged."""

    def setUp(self):
        self.adapter = get_adapter("sleep")

    def _nights(self, minutes, *, start_day=1, repeats=None, window_days=14):
        dates = ["2026-07-%02d" % (start_day + index) for index in range(len(minutes))]
        return _analysis(dates, minutes=minutes, repeats=repeats, window_days=window_days)

    def test_lexicon_matches_the_column_the_contract_specifies(self):
        """The lexicon is a transcription, so drift from the contract is a bug."""
        contract = CONTRACT_PATH.read_text(encoding="utf-8")
        for field in ("subject", "reading", "unit", "up", "down", "series_label", "scope_label"):
            self.assertIn(str(self.adapter.LEXICON[field]), contract, field)

    def test_the_fold_note_is_the_one_the_contract_wrote(self):
        self.assertEqual(self.adapter.SERIES_FOLD, "mean")
        self.assertIn(
            self.adapter.LEXICON["fold_note"], CONTRACT_PATH.read_text(encoding="utf-8")
        )

    def test_same_night_imports_average_rather_than_sum(self):
        """Two wearables disagreeing about one night is one night, not two.

        Summing would invent sleep that did not happen, and taking the longer
        would be picking the flattering reading. The mean is the only fold here
        that can neither overstate the night nor choose a favourite.
        """
        analysis = {
            "window_days": 14,
            "daily_records": [
                {"date": "2026-07-01", "duration_min": 420},
                {"date": "2026-07-01", "duration_min": 480},
            ],
        }
        series = self.adapter.series_for(analysis)
        self.assertEqual(series, [{"date": "2026-07-01", "value": 450.0, "count": 2}])

    def test_a_repeat_count_folds_the_same_way_as_separate_rows(self):
        """The mean must not depend on how the host grouped the imports."""
        grouped = {
            "window_days": 14,
            "daily_records": [
                {"date": "2026-07-01", "duration_min": 420, "measurement_count": 2},
                {"date": "2026-07-01", "duration_min": 480, "measurement_count": 1},
            ],
        }
        spread = {
            "window_days": 14,
            "daily_records": [
                {"date": "2026-07-01", "duration_min": 420},
                {"date": "2026-07-01", "duration_min": 420},
                {"date": "2026-07-01", "duration_min": 480},
            ],
        }
        self.assertEqual(self.adapter.series_for(grouped), self.adapter.series_for(spread))
        self.assertEqual(self.adapter.series_for(grouped)[0]["count"], 3)

    def test_it_reads_duration_and_never_the_stage_breakdown(self):
        """The structural reason this domain cannot express a sleep diagnosis.

        Same durations, opposite stage compositions — one that `sleep.py`'s
        quality model would score well and one it would flag. If any output
        differs, the adapter is reading the stages, and a card that varies with
        深睡比例 is giving a sleep-quality verdict this product does not give.
        """
        dates = ["2026-07-%02d" % day for day in range(1, 13)]
        good = _analysis(dates, minutes=[470] * 12)
        bad = _analysis(dates, minutes=[470] * 12)
        for item in good["daily_records"]:
            item.update({"deep_min": 100, "rem_min": 110, "awake_min": 10, "light_min": 260})
        for item in bad["daily_records"]:
            item.update({"deep_min": 12, "rem_min": 20, "awake_min": 120, "light_min": 318})
        self.assertEqual(self.adapter.shape_for(good), self.adapter.shape_for(bad))
        self.assertEqual(self.adapter.trend_direction(good), self.adapter.trend_direction(bad))
        self.assertEqual(self.adapter.coverage_for(good), self.adapter.coverage_for(bad))
        self.assertEqual(self.adapter.series_for(good), self.adapter.series_for(bad))

    def test_a_nested_sleep_object_is_read(self):
        """`sleep.py`'s cmd_daily nests the parsed record under `sleep`."""
        analysis = {
            "window_days": 14,
            "daily_records": [
                {"date": "2026-07-01", "sleep": {"duration_min": 455, "deep_min": 90}},
            ],
        }
        self.assertEqual(self.adapter.series_for(analysis)[0]["value"], 455.0)

    def test_a_weight_reading_is_never_plotted_as_minutes(self):
        """`value` carries kilograms in a weight analysis; reading it would leak.

        71.6 plotted on a minutes axis is a night of just over an hour, which is
        both false and alarming. The adapter has to come back empty instead.
        """
        analysis = _analysis(
            ["2026-07-01", "2026-07-02", "2026-07-03"], values=[72.0, 71.8, 71.6]
        )
        analysis["daily_records"][0]["value"] = 72.0
        self.assertEqual(self.adapter.series_for(analysis), [])
        self.assertEqual(self.adapter.shape_for(analysis), "insufficient")

    def test_an_unreadable_night_is_missing_from_both_series_and_coverage(self):
        """One number above a plot one point shorter is the inconsistency to avoid."""
        analysis = {
            "window_days": 14,
            "daily_records": [
                {"date": "2026-07-01", "duration_min": 450},
                {"date": "2026-07-02", "duration_min": 0},
                {"date": "2026-07-03", "duration_min": 460},
            ],
        }
        self.assertEqual(len(self.adapter.series_for(analysis)), 2)
        self.assertEqual(self.adapter.coverage_for(analysis)["recorded_days"], 2)

    def test_zero_minutes_is_not_a_night_of_no_sleep(self):
        """`_parse_sleep_value` coerces a missing duration to 0.

        So a 0 means the field was empty far more often than it means someone
        recorded a sleepless night, and plotting it would draw a line to the floor
        and make a claim about the night rather than about the record.
        """
        analysis = self._nights([450, 0, 455, 0, 448])
        series = self.adapter.series_for(analysis)
        self.assertTrue(all(point["value"] > 0 for point in series))
        self.assertEqual(len(series), 3)

    def test_lengthening_and_shortening_are_symmetric(self):
        longer = self._nights([400, 405, 410, 470, 475, 480])
        self.assertEqual(self.adapter.trend_direction(longer), "up")
        self.assertEqual(self.adapter.shape_for(longer), "sustained-rise")
        shorter = self._nights([480, 475, 470, 410, 405, 400])
        self.assertEqual(self.adapter.trend_direction(shorter), "down")
        self.assertEqual(self.adapter.shape_for(shorter), "sustained-fall")

    def test_a_night_against_the_trend_is_the_conflict_shape(self):
        """The shape the whole system was built around, in a second domain.

        The window is lengthening and the newest night is far short of the mean.
        Both facts are true, and the card's job is to hold them at once rather
        than let the newest number overwrite the direction.
        """
        analysis = self._nights([400, 405, 410, 415, 470, 475, 480, 330])
        self.assertEqual(self.adapter.state_for(analysis), "night_against_trend")
        self.assertEqual(self.adapter.shape_for(analysis), "today-vs-trend-conflict")

    def test_a_flat_window_with_one_odd_night_is_noise_not_conflict(self):
        """There is no direction here for the night to conflict with."""
        analysis = self._nights([455, 450, 460, 450, 455, 460, 450, 455, 370])
        self.assertEqual(self.adapter.state_for(analysis), "level_with_swings")
        self.assertEqual(self.adapter.shape_for(analysis), "flat-with-noise")

    def test_a_window_that_swings_hard_is_not_called_level(self):
        """5h/9h alternating averages flat; calling it 稳定 would be false.

        The newest night here sits right on the window mean, so the only thing
        that can catch this is the spread — which is the reason the spread check
        exists next to the newest-night one.
        """
        analysis = self._nights([300, 540, 300, 540, 300, 540, 300, 540, 420])
        self.assertEqual(self.adapter.state_for(analysis), "level_with_swings")

    def test_a_quarter_hour_of_drift_is_not_a_direction(self):
        """Bedtimes get rounded and wearables disagree by about this much.

        Under the band this is the recording method, not the sleep, so it has to
        read as level rather than as a trend the reader should act on.
        """
        analysis = self._nights([450, 452, 455, 458, 460, 462])
        self.assertEqual(self.adapter.state_for(analysis), "level")
        self.assertEqual(self.adapter.trend_direction(analysis), "stable")

    def test_a_resumed_break_reads_as_rebuilding(self):
        analysis = _analysis(
            [
                "2026-07-01", "2026-07-02", "2026-07-03",
                "2026-07-11", "2026-07-12", "2026-07-13",
            ],
            minutes=[450, 455, 448, 460, 452, 458],
            window_days=14,
        )
        self.assertEqual(self.adapter.state_for(analysis), "resumed_after_break")
        self.assertEqual(self.adapter.shape_for(analysis), "rebuilding")
        self.assertEqual(self.adapter.coverage_for(analysis)["longest_gap_days"], 7)

    def test_a_break_still_open_is_not_rebuilding(self):
        """Nothing has been rebuilt while the silence is still the newest thing."""
        analysis = _analysis(
            ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-12"],
            minutes=[450, 455, 448, 452, 460],
            window_days=14,
        )
        self.assertNotEqual(self.adapter.state_for(analysis), "resumed_after_break")

    def test_two_nights_cannot_support_a_trend(self):
        """The contract sets 每日型域 at ≥3 recorded days."""
        analysis = self._nights([450, 470])
        self.assertEqual(self.adapter.shape_for(analysis), "insufficient")
        self.assertIsNone(self.adapter.trend_direction(analysis))
        # The nights are still counted; insufficient describes the claim, not the data.
        self.assertEqual(self.adapter.coverage_for(analysis)["recorded_days"], 2)

    def test_a_precomputed_state_is_honoured_but_a_foreign_one_is_not(self):
        """`state` belongs to whichever domain produced the analysis."""
        borrowed = self._nights([450, 452, 455, 458, 460, 462])
        borrowed["state"] = "sustained_down"
        self.assertEqual(self.adapter.state_for(borrowed), "level")
        declared = self._nights([450, 452, 455, 458, 460, 462])
        declared["sleep_state"] = "shortening"
        self.assertEqual(self.adapter.state_for(declared), "shortening")

    def test_the_disclaimer_refuses_the_thing_sleep_readers_ask_for(self):
        self.assertEqual(self.adapter.PRESCRIPTION_NOUN, "助眠处方")


class WeightSeriesRegressionTests(unittest.TestCase):
    """The producer's key is `measurement_count`; the frame's spelling is `count`."""

    def test_repeat_days_survive_the_trip_into_the_frame(self):
        adapter = get_adapter("weight")
        analysis = _analysis(
            ["2026-07-01", "2026-07-02"], repeats=[1, 3], values=[72.0, 71.6]
        )
        series = adapter.series_for(analysis)
        self.assertEqual([point["count"] for point in series], [1, 3])

    def test_a_frame_shaped_point_is_read_too(self):
        adapter = get_adapter("weight")
        analysis = {"daily_records": [{"date": "2026-07-01", "weight": 72.0, "count": 2}]}
        self.assertEqual(adapter.series_for(analysis)[0]["count"], 2)


class FrameAssemblyTests(unittest.TestCase):
    """Assemble a Signal Frame from the adapter helpers and validate it.

    The contract's whole claim is that a domain reaches the renderers through this
    one object. Hand-written frames elsewhere in the suite prove the schema is
    well-formed; only building one from a real adapter proves an adapter can
    actually fill it.
    """

    def setUp(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is not installed")
        self.jsonschema = jsonschema

    def _frame(self, domain, analysis):
        adapter = get_adapter(domain)
        direction = adapter.trend_direction(analysis)
        coverage = adapter.coverage_for(analysis)
        series = adapter.series_for(analysis)
        return {
            "domain": domain,
            "lexicon": dict(lexicon_for(domain)),
            "window": {
                "days": int(analysis.get("window_days") or 0),
                "start": "2026-07-01",
                "end": "2026-07-14",
            },
            "series": series,
            "series_meta": {"fold": adapter.SERIES_FOLD, "relative_only": True},
            "shape": adapter.shape_for(analysis),
            "trend": {
                "claim_allowed": direction is not None,
                "confidence": "insufficient" if direction is None else "medium",
                "direction": direction,
            },
            "coverage": coverage,
            "facts": [],
            "limits": {
                "causal_claim": False,
                "prescription": False,
                "unrecorded_is_zero": False,
                "cross_domain_arithmetic": False,
                "non_causal_note": "相关线索不代表因果。",
            },
        }

    def test_every_adapter_fills_a_schema_valid_frame(self):
        analysis = _analysis(
            ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-09", "2026-07-10"],
            repeats=[1, 2, 1, 1, 3],
            values=[72.0, 71.8, 71.9, 71.4, 71.5],
        )
        for domain in available_domains():
            with self.subTest(domain=domain):
                self.jsonschema.validate(self._frame(domain, analysis), SCHEMA)

    def test_every_adapter_fills_a_schema_valid_zero_data_frame(self):
        """Zero data is the state the system is most likely to be seen in."""
        empty = {"window_days": 14, "daily_records": [], "recorded_days": 0, "span_days": 14}
        for domain in available_domains():
            with self.subTest(domain=domain):
                frame = self._frame(domain, empty)
                self.assertEqual(frame["series"], [])
                self.assertEqual(frame["shape"], "insufficient")
                self.assertFalse(frame["trend"]["claim_allowed"])
                self.jsonschema.validate(frame, SCHEMA)

    def test_a_zero_data_template_is_reachable_for_every_domain(self):
        """至少 1 套零数据模板, checked against the selector rather than asserted.

        `no-verdict` is the template whose subject *is* the absence of a verdict;
        if the selector cannot reach it with nothing recorded, the honest-restraint
        path is decorative.
        """
        from shared.story.selector import select_weight_card_style

        empty = {"window_days": 14, "daily_records": [], "recorded_days": 0, "span_days": 14}
        for domain in available_domains():
            with self.subTest(domain=domain):
                analysis = dict(empty, domain=domain)
                trace = select_weight_card_style(analysis, seed="records-zero-data")
                self.assertIn("no-verdict", trace["eligible_styles"], domain)
                self.assertEqual(trace["selected_style"]["id"], "no-verdict", domain)
                # It must be reached by being eligible, not by a special case.
                self.assertEqual(trace["selected_style"]["min_recorded_days"], 0)
                self.assertFalse(trace["selected_style"]["requires_trend"])

    def test_motion_compiles_for_a_new_domain_series_without_dead_air(self):
        """The P2 stillness guard, re-run against a series this domain produced.

        The occupancy guards exist to catch a new domain reintroducing dead air,
        so they are the acceptance test for the domain-neutral claim, not an
        afterthought.
        """
        from shared.story.catalog import STYLE_CATALOG
        from shared.story.motion import compile_motion

        adapter = get_adapter("records")
        analysis = _analysis(
            ["2026-07-%02d" % day for day in (1, 2, 3, 4, 8, 9, 10, 11)],
            repeats=[1, 2, 1, 1, 1, 3, 1, 2],
            window_days=14,
        )
        series = adapter.series_for(analysis)
        shape = adapter.shape_for(analysis)
        for style in STYLE_CATALOG:
            with self.subTest(style=style.id):
                motion = compile_motion(
                    style.id, seed="records-motion", series=series, shape=shape
                )
                self.assertTrue(motion["primitives"], style.id)
                self.assertEqual(
                    motion["poster_time_ms"],
                    motion["duration_ms"] + motion["hold_ms"] // 2,
                    style.id,
                )
                self.assertGreaterEqual(motion["duration_ms"], 4000, style.id)
                self.assertLessEqual(motion["duration_ms"], 12000, style.id)


if __name__ == "__main__":
    unittest.main()
