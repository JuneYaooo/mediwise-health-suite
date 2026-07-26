"""Intake adapter: the first domain whose daily number is a sum of several rows.

Weight, sleep, vitals and records each answer 「这天的读数是多少」 from readings
that are attempts at one quantity, so folding them means picking a middle or
counting them.  Intake does not work that way.  `diet_records` holds one row per
meal, and the day's figure is those rows added up — which makes the fold a `sum`
and creates this domain's distinctive honesty problem:

    一天少记一餐，和一天少吃一餐，在数据里长得一模一样。

Both produce a smaller total.  So a sum taken from an under-logged day is an
undercount, not a smaller intake, and a window whose totals rise may only be a
window whose logging improved.  `state_for` therefore refuses to name a direction
unless the number of computed meal rows per day is itself stable across the
window's two halves; when that count drifts it returns `logging_changed`, which
maps to the `insufficient` shape so the card says 记录还在序章 instead of 变多.
That gate is to this domain what the 断档 check is to the others: the structural
reason a true sentence gets printed where a plausible one would have fit.

`COMPONENTS` follows vitals for the same reason vitals needed it — 热量 in 千卡
and 蛋白质 in 克 are different quantities, a card carries exactly one unit, and
one direction word laid over calories and five macros would misdescribe whichever
nutrient moved the other way.

What this module refuses to read is the goal apparatus the rest of the suite owns:
the targets in `diet-tracker/scripts/nutrition_goal.py` and the goal-vs-actual
comparison in `diet-tracker/scripts/nutrition.py`.  Those answer 「吃够了吗 / 吃超
了吗」, and answering it on a story card is nutrition therapy.  A card here may say
「这天记录了 1850 千卡」 and may never say 超出目标.  The bands below are logging
noise in each component's own unit — the smallest difference hand-entered food
data can express — and are nothing else.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Mapping, Optional, Sequence

DOMAIN = "intake"

# One entry per narratable component.
#
# `column` is the `diet_records` column the number lives in; `aliases` are the
# other keys the same number arrives under when a host has already aggregated a
# day (`calories`, `protein`) rather than handing over raw meal rows.
#
# `band` and `spot_band` are logging noise in that component's own unit: the
# rounding a person does when they pick 一碗米饭 off a food table, the snack that
# never got entered, the difference between two cooks' idea of one serving.  They
# decide when a difference is worth calling a direction at all.  They are not
# targets, allowances or reference intakes: nothing here knows how much is enough,
# and 150 千卡 means nothing at all for 膳食纤维.
COMPONENTS: Mapping[str, Mapping[str, object]] = {
    "calories": {
        "column": "total_calories",
        "aliases": ("calories", "kcal", "energy"),
        "band": 150.0,
        "spot_band": 400.0,
        "lexicon": {
            "subject": "热量",
            "reading": "记录热量",
            "unit": "千卡",
            "up": "变多",
            "down": "变少",
            "series_label": "每日记录热量",
            "fold_note": "同日多餐累计",
            "scope_label": "有记录日",
        },
    },
    "protein": {
        "column": "total_protein",
        "aliases": ("protein",),
        "band": 10.0,
        "spot_band": 25.0,
        "lexicon": {
            "subject": "蛋白质",
            "reading": "记录蛋白质",
            "unit": "克",
            "up": "变多",
            "down": "变少",
            "series_label": "每日记录蛋白质",
            "fold_note": "同日多餐累计",
            "scope_label": "有记录日",
        },
    },
    "fat": {
        "column": "total_fat",
        "aliases": ("fat",),
        "band": 10.0,
        "spot_band": 25.0,
        "lexicon": {
            "subject": "脂肪",
            "reading": "记录脂肪",
            "unit": "克",
            "up": "变多",
            "down": "变少",
            "series_label": "每日记录脂肪",
            "fold_note": "同日多餐累计",
            "scope_label": "有记录日",
        },
    },
    "carbs": {
        "column": "total_carbs",
        "aliases": ("carbs", "carbohydrate", "carbohydrates"),
        "band": 20.0,
        "spot_band": 50.0,
        "lexicon": {
            "subject": "碳水",
            "reading": "记录碳水",
            "unit": "克",
            "up": "变多",
            "down": "变少",
            "series_label": "每日记录碳水",
            "fold_note": "同日多餐累计",
            "scope_label": "有记录日",
        },
    },
    "fiber": {
        "column": "total_fiber",
        "aliases": ("fiber", "fibre"),
        "band": 3.0,
        "spot_band": 8.0,
        "lexicon": {
            "subject": "膳食纤维",
            "reading": "记录纤维",
            "unit": "克",
            "up": "变多",
            "down": "变少",
            "series_label": "每日记录纤维",
            "fold_note": "同日多餐累计",
            "scope_label": "有记录日",
        },
    },
}

DEFAULT_COMPONENT = "calories"
LEXICON: Mapping[str, str] = COMPONENTS[DEFAULT_COMPONENT]["lexicon"]  # type: ignore[assignment]

# The analysis key `component_for` reads an explicit pick from — see the same
# constant in `vitals.py`.  Kept next to the reader so the name cannot drift.
COMPONENT_KEY = "intake_component"

# The day's figure is the sum of that day's meal rows — the first domain to need
# this fold, and the reason the logging-stability gate below has to exist.
SERIES_FOLD = "sum"

PRESCRIPTION_NOUN = "饮食方案"

# Intake reads no other domain.  A card here reports meals and nothing else; the
# cross-domain reading of 摄入 alongside 运动 stays on weight's cards, where the
# companion axis is declared.
COMPANIONS: Sequence[str] = ()

SHAPE_BY_STATE: Mapping[str, str] = {
    "insufficient": "insufficient",
    # Logging density moved, so the totals moved.  Same shape as too-few-days,
    # because the honest report is the same: not enough comparable record to
    # call a direction.
    "logging_changed": "insufficient",
    "resumed_after_break": "rebuilding",
    "rising": "sustained-rise",
    "falling": "sustained-fall",
    "spot_against_trend": "today-vs-trend-conflict",
    "level_with_swings": "flat-with-noise",
    "level": "stable",
}

GAP_DAYS_FOR_BREAK = 5
MIN_DAYS_FOR_TREND = 3

# Meals per day may drift by this much between the window's halves before the
# totals stop being comparable.  Three quarters of a meal is deliberately tight:
# going from two logged meals a day to three lifts a daily total by roughly a
# third on logging alone.
MEAL_COUNT_BAND = 0.75


def _parse_date(raw: object) -> Optional[date]:
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _row_date(item: Mapping[str, object]) -> Optional[date]:
    """The day a meal row belongs to.

    `diet_records` names the column `meal_date`, while a host that has already
    assembled a window hands its rows over under `date`.  Reading both is what lets
    one adapter serve the table and the summary without a translation step between.
    """
    return _parse_date(item.get("date")) or _parse_date(item.get("meal_date"))


def _number(raw: object) -> Optional[float]:
    """A finite float, or None.  Booleans are rejected rather than counted as 1."""
    if isinstance(raw, bool) or raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value == value and abs(value) != float("inf") else None


def _nested(item: Mapping[str, object]) -> Optional[Mapping[str, object]]:
    """A daily summary's nutrition block, when the totals arrive one level down."""
    for key in ("intake", "nutrition", "totals"):
        found = item.get(key)
        if isinstance(found, Mapping):
            return found
    return None


def _field_value(item: Mapping[str, object], entry: Mapping[str, object]) -> Optional[float]:
    """One component's number in one row, by column name first and then alias."""
    names = [str(entry["column"])] + [str(alias) for alias in entry["aliases"]]
    for name in names:
        if name in item:
            found = _number(item.get(name))
            if found is not None:
                return found
    return None


def _is_computed(item: Mapping[str, object]) -> bool:
    """Whether this row's nutrition was ever worked out.

    Every nutrition column on `diet_records` is `REAL DEFAULT 0`, so a row entered
    as 「午餐，食堂」 without a food breakdown is indistinguishable by type from a
    row whose contents genuinely came to zero.  Calories break the tie: no meal a
    person records has zero of them, so `total_calories > 0` is the marker that the
    row was computed.  On a computed row the macros are then read as they stand —
    black coffee really does have no protein, and rewriting that zero would be the
    opposite mistake.
    """
    entry = COMPONENTS["calories"]
    calories = _field_value(item, entry)
    if calories is None:
        nested = _nested(item)
        calories = _field_value(nested, entry) if nested is not None else None
    return calories is not None and calories > 0


def _component_value(item: Mapping[str, object], component: str) -> Optional[float]:
    """This component's number on one computed meal row, or None.

    Uncomputed rows return None for every component rather than zero.  Summing a
    zero from a row nobody itemised would put a smaller number on the card and call
    it a smaller day, which is the specific error this domain exists to avoid.
    """
    entry = COMPONENTS.get(component) or COMPONENTS[DEFAULT_COMPONENT]
    if not _is_computed(item):
        return None
    found = _field_value(item, entry)
    if found is None:
        nested = _nested(item)
        found = _field_value(nested, entry) if nested is not None else None
    return found


def _meals(item: Mapping[str, object]) -> int:
    """How many meal rows this record stands for.  Defaults to one, never zero.

    A raw `diet_records` row is one meal.  A host that pre-aggregated a day hands
    over its meal count, which is what makes the logging-stability gate work on
    summaries as well as on raw rows.
    """
    for key in ("meal_count", "measurement_count", "count"):
        raw = item.get(key)
        if raw is None:
            continue
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            continue
    return 1


def _days(analysis: Mapping[str, object], component: str) -> "dict[date, tuple[float, int]]":
    """Per-day total for one component, and how many meal rows it adds up.

    Summing rather than folding to a middle is the whole difference between this
    domain and the others: two meals of 600 千卡 make an 1200 千卡 day, not a 600
    千卡 one.  Which is also why the count travels alongside the total — a sum is
    only comparable to another sum taken from the same number of meals, and
    `state_for` is the caller that has to know that.

    The mapping check guards every caller at once, since `coverage_for` and
    `series_for` pass their argument straight through and the junk-input test hands
    them a bare string.
    """
    if not isinstance(analysis, Mapping):
        return {}
    totals: "dict[date, float]" = {}
    meals: "dict[date, int]" = {}
    for item in analysis.get("daily_records") or []:
        if not isinstance(item, Mapping):
            continue
        day = _row_date(item)
        if day is None:
            continue
        value = _component_value(item, component)
        if value is None:
            continue
        totals[day] = totals.get(day, 0.0) + value
        meals[day] = meals.get(day, 0) + _meals(item)
    return {day: (total, max(meals.get(day, 1), 1)) for day, total in totals.items()}


def _gaps(dates: Sequence[date]) -> List[int]:
    """Unrecorded days between consecutive recorded days; consecutive gives 0."""
    return [max((later - earlier).days - 1, 0) for earlier, later in zip(dates, dates[1:])]


def _mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / float(len(values)) if values else None


def lexicon_for_component(component: str = DEFAULT_COMPONENT) -> Mapping[str, str]:
    """Wording for one component, falling back to the default component's.

    Unknown names fall back rather than raise, as in vitals: a caller naming a
    nutrient this module does not narrate should get a readable card about 热量,
    not a traceback mid-render.
    """
    entry = COMPONENTS.get(str(component or ""), COMPONENTS[DEFAULT_COMPONENT])
    return entry["lexicon"]  # type: ignore[return-value]


def component_for(analysis: Mapping[str, object]) -> str:
    """Which component this analysis is about.

    An explicit `intake_component` wins.  Otherwise the component with the most
    readable days, tie-broken by `COMPONENTS` order — which puts 热量 first, the
    right default because it is the one column a food log fills even when nobody
    itemised the macros.
    """
    if not isinstance(analysis, Mapping):
        return DEFAULT_COMPONENT
    declared = analysis.get("intake_component")
    if isinstance(declared, str) and declared in COMPONENTS:
        return declared
    best, best_days = DEFAULT_COMPONENT, 0
    for name in COMPONENTS:
        days = len(_days(analysis, name))
        if days > best_days:
            best, best_days = name, days
    return best


def lexicon_for_analysis(analysis: Mapping[str, object]) -> Mapping[str, str]:
    """The wording table a host should pass to the renderer for this analysis."""
    return lexicon_for_component(component_for(analysis))


def _logging_drifted(readings: "Mapping[date, tuple[float, int]]", dates: Sequence[date]) -> bool:
    """Whether meals per day moved enough to explain a change in the totals.

    This is the gate that makes an intake card honest.  Sums are only comparable
    across halves that were logged at the same density: two meals a day becoming
    three lifts every daily total without anyone eating differently, and one meal
    quietly going unlogged lowers them the same way.  When that density is itself
    what moved, the truthful report is that the record changed, not that intake did.
    """
    counts = [float(readings[day][1]) for day in dates]
    middle = len(counts) // 2
    early = _mean(counts[:middle] or counts[:1])
    late = _mean(counts[middle:])
    if early is None or late is None:
        return False
    return abs(late - early) > MEAL_COUNT_BAND


def state_for(analysis: Mapping[str, object]) -> str:
    """Derive this domain's state for whichever component the analysis is about.

    Reads `intake_state` if a caller precomputed one, and deliberately not `state`:
    that key belongs to whichever domain produced the analysis, so honouring it
    would let a weight state through to be misread as an intake one.
    """
    if not isinstance(analysis, Mapping):
        return "insufficient"
    declared = analysis.get("intake_state")
    if isinstance(declared, str) and declared in SHAPE_BY_STATE:
        return declared

    component = component_for(analysis)
    entry = COMPONENTS[component]
    band = float(entry["band"])
    spot_band = float(entry["spot_band"])

    readings = _days(analysis, component)
    dates = sorted(readings)
    if len(dates) < 2:
        return "insufficient"

    gaps = _gaps(dates)
    # A long silence outranks any direction verdict, as in every other domain.
    if gaps and max(gaps) >= GAP_DAYS_FOR_BREAK and gaps[-1] < GAP_DAYS_FOR_BREAK:
        return "resumed_after_break"

    if len(dates) < MIN_DAYS_FOR_TREND:
        return "insufficient"

    # Before any direction, and before 稳定 too: a window whose meal count drifted
    # gives no comparable pair of halves, so flat totals across it are as unearned
    # as rising ones.  Fewer meals holding the same total is not a level window.
    if _logging_drifted(readings, dates):
        return "logging_changed"

    values = [readings[day][0] for day in dates]
    middle = len(values) // 2
    early = _mean(values[:middle] or values[:1])
    late = _mean(values[middle:])
    if early is None or late is None:
        return "insufficient"

    latest = values[-1]
    overall = _mean(values) or latest
    drift = late - early
    spot_gap = latest - overall

    if drift > band:
        # A direction exists, so the only thing left to ask is whether the newest
        # day contradicts it — that contradiction is the conflict shape.
        return "spot_against_trend" if spot_gap < -spot_band else "rising"
    if drift < -band:
        return "spot_against_trend" if spot_gap > spot_band else "falling"

    # Halves are level, so a deviating day is noise around a flat line rather than
    # a conflict with a direction: there is no direction to conflict with.
    if abs(spot_gap) > spot_band:
        return "level_with_swings"
    # Level halves still hide a window that swings hard day to day, since a feast
    # and a fast average out flat.  Checking the spread is what keeps that window
    # from being called 稳定.
    if (max(values) - min(values)) > spot_band * 2:
        return "level_with_swings"
    return "level"


def shape_for(analysis: Mapping[str, object]) -> str:
    """Return the shared narrative shape for an intake analysis."""
    return SHAPE_BY_STATE.get(state_for(analysis), "insufficient")


def trend_direction(analysis: Mapping[str, object]) -> Optional[str]:
    """Neutral direction word key: 变多 / 变少 only.

    A bigger number is not 超标 and a smaller one is not 自律 — a 2400 千卡 day may
    be a hike, a holiday, or two people sharing one entry.  So this returns numeric
    direction and nothing evaluative, per the neutral-direction rule in
    story-system.md, which is also why nothing here consults a nutrition goal.

    `logging_changed` returns None with `insufficient`: both mean the window cannot
    support a direction, and the caller asking for one deserves the same answer.
    """
    state = state_for(analysis)
    if state == "rising":
        return "up"
    if state == "falling":
        return "down"
    if state in ("insufficient", "logging_changed"):
        return None
    return "stable"


def coverage_for(analysis: Mapping[str, object]) -> dict:
    """Extract the coverage block of the Signal Frame.

    Recomputed from the days this card can actually plot rather than taken from the
    host's `recorded_days`: a day holding only uncomputed rows is missing from the
    series, and counting it here would put a 有记录日 number above a shorter plot.

    `measurement_count` is meal rows, not days — the number the 同日多餐累计 note
    refers to, and the one that makes a 3-meal day legible as denser than a 1-meal
    day at the same total.

    The recomputation defines the frame's coverage block, and it is what a consumer
    reading the frame gets.  It is not yet what the card prints -- today's HTML and
    SVG renderers read the host's `recorded_days` straight off the analysis
    (`render.py:385`, `:1286`, `:1288`), and a window of un-itemised meals prints
    「目前有 3 / 14 天」 beside an empty plot.  Closing that gap means routing the
    renderer through this function; until then the number here is the contract and
    the number on the card is the host's.
    """
    component = component_for(analysis)
    readings = _days(analysis, component)
    dates = sorted(readings)
    gaps = _gaps(dates)
    source = analysis if isinstance(analysis, Mapping) else {}
    window_days = int(source.get("window_days") or source.get("span_days") or 0)
    span_days = (dates[-1] - dates[0]).days + 1 if dates else 0
    denominator = window_days or span_days
    ratio = min(len(dates) / float(denominator), 1.0) if denominator else 0.0
    return {
        "recorded_days": len(dates),
        "measurement_count": sum(count for _, count in readings.values()),
        "span_days": span_days,
        "ratio": round(ratio, 3),
        "longest_gap_days": max(gaps) if gaps else 0,
        "repeat_days": sum(1 for _, count in readings.values() if count > 1),
    }


def series_for(analysis: Mapping[str, object]) -> list:
    """Return daily totals in Signal Frame form, ascending by date.

    Unrecorded days are absent rather than zero, per the analysis boundary in
    story-system.md.  The distinction matters more here than anywhere else: a point
    on the floor would read as a day of eating nothing, when all it means is that
    nobody opened the app.
    """
    component = component_for(analysis)
    readings = _days(analysis, component)
    points = []
    for day in sorted(readings):
        value, count = readings[day]
        points.append({"date": day.isoformat(), "value": round(value, 1), "count": count})
    return points
