"""Robust, share-safe weight trend analysis and fixed-canvas result cards.

The existing weight-analysis actions intentionally remain unchanged for
backward compatibility.  This module adds a separate interpretation layer
that distinguishes a single measurement from the longer trend.  Copy is
selected from curated states; no free-form model output or prescription is
used.

Usage:
  python3 weight_truth_card.py analyze --member-id <id> [--days 14]
  python3 weight_truth_card.py generate --member-id <id> [--days 14]
      [--format html|png|svg|both|all] [--show-exact-weight]
      [--show-member-name] [--show-exact-date] [--context <fact>]
  python3 weight_truth_card.py generate-story --member-id <id> [--days 14]
      [--format html|png|svg|both|all] [--style auto|<style-id>]

`svg` emits the animated card; `all` emits every artifact.  `both` keeps its
original html+png meaning so existing callers see no change.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
from path_setup import setup_mediwise_path

setup_mediwise_path()

from config import DATA_DIR
from health_db import (
    ensure_db,
    get_lifestyle_connection,
    get_medical_connection,
    output_json,
    verify_member_ownership,
)
from weight_card_preferences import get_style_profile, update_style_profile

# The storytelling engine is domain-neutral and lives in shared/story/.  Weight
# is one registered domain there; see story-design/story-system.md.
from _story_bootstrap import story_module, story_package

_story = story_package()
# Poster-frame capture lives with the motion layer, since knowing when a frame is
# settled is a property of the timeline, not of this action.
_story_export = story_module("export")
STYLES_BY_ID = _story.STYLES_BY_ID
analyze_weight_management = _story.analyze_weight_management
render_weight_story_html = _story.render_weight_story_html
render_story_svg = story_module("svg").render_story_svg
derive_style_seed = _story.derive_style_seed
select_weight_card_style = _story.select_weight_card_style
STORY_DOMAIN = _story.DEFAULT_DOMAIN
STORY_DOMAINS = tuple(_story.available_domains())
story_lexicon_for = _story.lexicon_for
# The per-window lookup, not the per-domain one: three domains narrate one
# component of several, and the label has to travel with whichever component the
# rows turned out to be about.  Identical to `story_lexicon_for` for the other five.
story_lexicon_for_analysis = _story.lexicon_for_analysis
story_product_name_for = _story.product_name_for
STORY_DISCLAIMER_TEMPLATE = story_module("render").DISCLAIMER_TEMPLATE
story_prescription_noun_for = story_module("adapters").prescription_noun_for
# `shape` and the coverage counts are what the renderers read; an adapter is what
# knows them.  A weight analysis already carries both, so this only fills gaps.
# The module itself is bound because `theil_sen_fit` below also delegates its
# arithmetic here -- one estimator for all eight domains.
_story_frame = story_module("frame")
story_render_ready = _story_frame.render_ready
# Row folding and the row->analysis normalizer moved into the engine so the
# briefing card can reach them without importing this skill; see the module
# docstring in shared/story/normalize.py.  The names stay bound here because the
# truth-card analysis below and the existing tests call them by these names.
_story_normalize = story_module("normalize")
_parse_date = _story_normalize._parse_date
aggregate_daily_medians = _story_normalize.aggregate_daily_medians
_domain_analysis_from_rows = _story_normalize.domain_analysis_from_rows


CARD_WIDTH = 1080
CARD_HEIGHT = 1440
DEFAULT_DAYS = 14
DISCLAIMER = "相关线索不代表因果；本卡不提供诊断或减重处方。"


def _disclaimer_for(domain: str) -> str:
    """The refusal line, naming the prescription this domain declines to give.

    Weight's literal is kept verbatim rather than rebuilt from the template, so
    the string this action has always returned cannot shift under it.
    """
    if domain == STORY_DOMAIN:
        return DISCLAIMER
    return STORY_DISCLAIMER_TEMPLATE % story_prescription_noun_for(domain)


STATE_COPY = {
    "insufficient": {
        "headline": "先把点连起来，再谈航向。",
        "status": "记录还少，本卡暂不判断趋势方向",
        "closing": "今天的记录，本身就有价值。",
    },
    "daily_up_trend_down": {
        "headline": "今天有浪，航向没变。",
        "status": "单日上浮，长期趋势仍保持向下",
        "closing": "先记录，不判失败。",
    },
    "daily_down_trend_up": {
        "headline": "今天退潮，航向还没掉头。",
        "status": "单日回落，长期趋势仍保持向上",
        "closing": "看一段路，不押一天。",
    },
    "sustained_down": {
        "headline": "浪在往下走，航向也一样。",
        "status": "单日与长期趋势目前方向一致",
        "closing": "记住方向，也允许有浪。",
    },
    "sustained_up": {
        "headline": "不只一朵浪，是一段上行。",
        "status": "单日与长期趋势目前方向一致",
        "closing": "先看清变化，再决定怎么理解。",
    },
    "daily_up_stable": {
        "headline": "今天有浪，航向仍稳。",
        "status": "单日上浮，长期趋势接近水平",
        "closing": "一天是天气，一段才是气候。",
    },
    "daily_down_stable": {
        "headline": "今天退潮，航向仍稳。",
        "status": "单日回落，长期趋势接近水平",
        "closing": "一天是天气，一段才是气候。",
    },
    "stable": {
        "headline": "海面有动，航向近乎水平。",
        "status": "单日变化与长期趋势都在稳定区间",
        "closing": "稳定不是没变化，是变化没改方向。",
    },
}


def theil_sen_fit(daily_records: Sequence[dict]) -> Tuple[Optional[float], Optional[float]]:
    """Return Theil-Sen slope in kg/day and a median intercept.

    The arithmetic moved to `shared.story.frame.robust_fit` when the other seven domains
    needed the same fit; this stays as the weight-shaped door onto it, reading `weight`
    off each row where the shared version reads a caller-named key.  Delegating rather
    than keeping a copy is the point: two implementations of 稳健估计 drifting apart
    would put two different long-run numbers under one label, and the cards give no way
    to tell which one you are looking at.

    `tests/test_story_frame.py::RobustFitTests` asserts the two return identical floats
    -- not approximately equal ones -- across a solid run, a gapped run, a two-day pair,
    a lone point and two readings on the same day.
    """
    return _story_frame.robust_fit(daily_records, value_key="weight")


def _confidence(recorded_days: int, span_days: int) -> Tuple[str, str, bool]:
    if recorded_days >= 10 and span_days >= 10:
        return "high", "较高", True
    if recorded_days >= 7 and span_days >= 7:
        return "medium", "中等", True
    if recorded_days >= 4 and span_days >= 4:
        return "low", "较低", False
    return "insufficient", "不足", False


def _state_for(daily_delta: Optional[float], trend_delta: Optional[float], sufficient: bool) -> str:
    if not sufficient or trend_delta is None:
        return "insufficient"
    daily_direction = "stable"
    if daily_delta is not None and daily_delta > 0.15:
        daily_direction = "up"
    elif daily_delta is not None and daily_delta < -0.15:
        daily_direction = "down"

    trend_direction = "stable"
    if trend_delta > 0.2:
        trend_direction = "up"
    elif trend_delta < -0.2:
        trend_direction = "down"

    if daily_direction == "up" and trend_direction == "down":
        return "daily_up_trend_down"
    if daily_direction == "down" and trend_direction == "up":
        return "daily_down_trend_up"
    if trend_direction == "down":
        return "sustained_down"
    if trend_direction == "up":
        return "sustained_up"
    if daily_direction == "up":
        return "daily_up_stable"
    if daily_direction == "down":
        return "daily_down_stable"
    return "stable"


def analyze_weight_records(records: Iterable[dict], days: int = DEFAULT_DAYS) -> dict:
    """Build deterministic truth-card analysis from raw weight measurements."""
    days = max(7, min(int(days or DEFAULT_DAYS), 90))
    raw_records = list(records)
    daily = aggregate_daily_medians(raw_records)
    recorded_days = len(daily)
    observation_count = sum(item["measurement_count"] for item in daily)

    if not daily:
        confidence, confidence_label, sufficient = _confidence(0, 0)
        state = "insufficient"
        return {
            "window_days": days,
            "daily_records": [],
            "recorded_days": 0,
            "measurement_count": 0,
            "coverage_ratio": 0.0,
            "span_days": 0,
            "latest_weight": None,
            "latest_date": None,
            "previous_date": None,
            "daily_delta": None,
            "comparison_gap_days": None,
            "trend_slope_per_day": None,
            "trend_delta": None,
            "latest_deviation": None,
            "trend_direction": None,
            "confidence": confidence,
            "confidence_label": confidence_label,
            "trend_claim_allowed": sufficient,
            "state": state,
            "copy": dict(STATE_COPY[state]),
            "method": _story_frame.FIT_METHOD,
        }

    first_date = _parse_date(daily[0]["date"])
    latest_date = _parse_date(daily[-1]["date"])
    span_days = (latest_date - first_date).days + 1 if first_date and latest_date else 0
    confidence, confidence_label, sufficient = _confidence(recorded_days, span_days)
    slope, intercept = theil_sen_fit(daily)

    daily_delta = None
    comparison_gap_days = None
    previous_date = None
    if len(daily) >= 2:
        daily_delta = daily[-1]["weight"] - daily[-2]["weight"]
        previous = _parse_date(daily[-2]["date"])
        previous_date = daily[-2]["date"]
        if latest_date and previous:
            comparison_gap_days = (latest_date - previous).days

    trend_delta = slope * (days - 1) if sufficient and slope is not None else None
    latest_deviation = None
    if slope is not None and intercept is not None and latest_date and first_date:
        latest_offset = (latest_date - first_date).days
        latest_deviation = daily[-1]["weight"] - (intercept + slope * latest_offset)

    state = _state_for(daily_delta, trend_delta, sufficient)
    trend_direction = None
    if sufficient and trend_delta is not None:
        trend_direction = "down" if trend_delta < -0.2 else ("up" if trend_delta > 0.2 else "stable")

    return {
        "window_days": days,
        "daily_records": daily,
        "recorded_days": recorded_days,
        "measurement_count": observation_count,
        "coverage_ratio": round(min(recorded_days / float(days), 1.0), 3),
        "span_days": span_days,
        "latest_weight": round(daily[-1]["weight"], 3),
        "latest_date": daily[-1]["date"],
        "previous_date": previous_date,
        "daily_delta": round(daily_delta, 3) if daily_delta is not None else None,
        "comparison_gap_days": comparison_gap_days,
        "trend_slope_per_day": round(slope, 5) if slope is not None else None,
        "trend_delta": round(trend_delta, 3) if trend_delta is not None else None,
        "latest_deviation": round(latest_deviation, 3) if latest_deviation is not None else None,
        "trend_direction": trend_direction,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "trend_claim_allowed": sufficient,
        "state": state,
        "copy": dict(STATE_COPY[state]),
        "method": _story_frame.FIT_METHOD,
    }


def _signed(value: Optional[float], digits: int = 1) -> str:
    if value is None:
        return "—"
    if abs(value) < 0.05:
        value = 0.0
    sign = "+" if value > 0 else ("−" if value < 0 else "")
    return "%s%.*f" % (sign, digits, abs(value))


def _chart_svg(analysis: dict) -> str:
    daily = analysis["daily_records"]
    if len(daily) < 2:
        return (
            '<svg class="chart" viewBox="0 0 936 330" role="img" '
            'aria-label="记录不足，暂不绘制趋势">'
            '<line x1="0" y1="274" x2="936" y2="274" stroke="#0A2F55" '
            'stroke-opacity=".13" stroke-width="2"/>'
            '<circle cx="468" cy="184" r="13" fill="#D66548"/>'
            '<text x="468" y="235" text-anchor="middle" fill="#5B7080" '
            'font-size="23" font-weight="600">再记录几天，趋势会从这里出现</text></svg>'
        )

    parsed_dates = [_parse_date(item["date"]) for item in daily]
    origin = parsed_dates[0]
    offsets = [(item_date - origin).days for item_date in parsed_dates]
    max_offset = max(offsets) or 1
    slope = analysis.get("trend_slope_per_day")
    _, intercept = theil_sen_fit(daily)
    trend_values = []
    if slope is not None and intercept is not None:
        trend_values = [intercept + slope * offset for offset in offsets]
    values = [float(item["weight"]) for item in daily] + trend_values
    low, high = min(values), max(values)
    pad = max((high - low) * 0.22, 0.25)
    low -= pad
    high += pad

    def x_pos(offset):
        return 20 + 880 * offset / float(max_offset)

    def y_pos(value):
        return 54 + (high - value) * 224 / float(high - low)

    points = [(x_pos(offset), y_pos(float(item["weight"]))) for offset, item in zip(offsets, daily)]
    observed_path = "M" + " L".join("%.1f %.1f" % point for point in points)
    circles = []
    for index, (x_value, y_value) in enumerate(points):
        if index == len(points) - 1:
            continue
        circles.append('<circle cx="%.1f" cy="%.1f" r="8"/>' % (x_value, y_value))

    if not analysis.get("trend_claim_allowed"):
        latest_x, latest_y = points[-1]
        return """<svg class="chart" viewBox="0 0 936 330" role="img" aria-label="已有记录点，但记录覆盖不足以判断趋势">
          <path d="M0 90 C120 118 207 74 324 104 S541 151 667 111 S831 84 936 114" fill="none" stroke="#167A9A" stroke-opacity=".07" stroke-width="2"/>
          <line x1="0" y1="294" x2="936" y2="294" stroke="#0A2F55" stroke-opacity=".12" stroke-width="1.5"/>
          <path d="%s" fill="none" stroke="#6F9EB6" stroke-opacity=".34" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
          <g fill="#F7F2E9" stroke="#6F9EB6" stroke-width="4">%s</g>
          <circle cx="%.1f" cy="%.1f" r="27" fill="#D66548" opacity=".12"/>
          <circle cx="%.1f" cy="%.1f" r="13" fill="#D66548" stroke="#F8F3EA" stroke-width="6"/>
          <text x="468" y="320" text-anchor="middle" fill="#5B7080" font-size="21" font-weight="600">记录点尚未形成可判断的趋势</text>
        </svg>""" % (
            observed_path,
            "".join(circles),
            latest_x,
            latest_y,
            latest_x,
            latest_y,
        )

    trend_path = ""
    latest_trend_y = points[-1][1]
    if trend_values:
        trend_points = [(x_pos(offset), y_pos(value)) for offset, value in zip(offsets, trend_values)]
        trend_path = "M" + " L".join("%.1f %.1f" % point for point in trend_points)
        latest_trend_y = trend_points[-1][1]

    latest_x, latest_y = points[-1]
    marker_y1, marker_y2 = sorted((latest_y, latest_trend_y))
    trend_markup = ""
    if trend_path:
        trend_markup = (
            '<path d="%s" fill="none" stroke="#F8F3EA" stroke-width="17" '
            'stroke-linecap="round" opacity=".9"/>'
            '<path d="%s" fill="none" stroke="#0A2F55" stroke-width="8" '
            'stroke-linecap="round" stroke-linejoin="round"/>' % (trend_path, trend_path)
        )

    return """<svg class="chart" viewBox="0 0 936 330" role="img" aria-labelledby="chart-title chart-desc">
      <title id="chart-title">秤面波动与稳健趋势</title>
      <desc id="chart-desc">浅蓝色记录点显示每日中位数，深海蓝线显示稳健趋势，珊瑚色显示最新记录。</desc>
      <path d="M0 90 C120 118 207 74 324 104 S541 151 667 111 S831 84 936 114" fill="none" stroke="#167A9A" stroke-opacity=".07" stroke-width="2"/>
      <path d="M0 128 C93 102 184 151 284 131 S481 98 588 127 S784 155 936 122" fill="none" stroke="#167A9A" stroke-opacity=".08" stroke-width="2"/>
      <line x1="0" y1="294" x2="936" y2="294" stroke="#0A2F55" stroke-opacity=".12" stroke-width="1.5"/>
      <path d="%s" fill="none" stroke="#6F9EB6" stroke-opacity=".34" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
      <g fill="#F7F2E9" stroke="#6F9EB6" stroke-width="4">%s</g>
      %s
      <circle cx="%.1f" cy="%.1f" r="27" fill="#D66548" opacity=".12"/>
      <circle cx="%.1f" cy="%.1f" r="13" fill="#D66548" stroke="#F8F3EA" stroke-width="6"/>
      <line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="#D66548" stroke-width="2.5" stroke-dasharray="3 8" stroke-linecap="round"/>
      <circle cx="%.1f" cy="%.1f" r="7" fill="#0A2F55" stroke="#F8F3EA" stroke-width="4"/>
      <g transform="translate(752 16)"><rect width="137" height="48" rx="24" fill="#F2E6D9" stroke="#D66548" stroke-opacity=".28"/><text x="68.5" y="31" text-anchor="middle" fill="#A84934" font-size="21" font-weight="680">最新记录</text></g>
      <text x="730" y="320" fill="#0A2F55" fill-opacity=".58" font-size="21" font-weight="600">稳健趋势</text>
    </svg>""" % (
        observed_path,
        "".join(circles),
        trend_markup,
        latest_x, latest_y,
        latest_x, latest_y,
        latest_x, marker_y1 + 17, latest_x, marker_y2 - 10,
        latest_x, latest_trend_y,
    )


def _context_lines(analysis: dict, explicit_lines: Optional[Sequence[str]]) -> List[str]:
    lines = [str(item).strip() for item in (explicit_lines or []) if str(item).strip()]
    if analysis["recorded_days"]:
        lines.append(
            "%d 日内记录 %d 天，共 %d 次测量"
            % (analysis["window_days"], analysis["recorded_days"], analysis["measurement_count"])
        )
    deviation = analysis.get("latest_deviation")
    if deviation is not None:
        if abs(deviation) < 0.05:
            lines.append("最新秤面与稳健趋势基本重合")
        else:
            direction = "高" if deviation > 0 else "低"
            lines.append("最新秤面比稳健趋势%s %s kg" % (direction, _signed(abs(deviation))))
    if analysis["measurement_count"] > analysis["recorded_days"]:
        lines.append("同日多次测量已先取中位数，再参与趋势计算")
    if not lines:
        lines.append("目前没有足够记录；本卡不会凭空补全线索")
    return lines[:2]


def render_card_html(
    analysis: dict,
    member_name: str = "",
    show_exact_weight: bool = False,
    show_member_name: bool = False,
    show_exact_date: bool = False,
    show_context: bool = True,
    context_lines: Optional[Sequence[str]] = None,
) -> str:
    """Render a self-contained 1080x1440 HTML card."""
    copy = analysis["copy"]
    comparison_label = "秤面较昨日" if analysis.get("comparison_gap_days") == 1 else "秤面较上次"
    daily_value = _signed(analysis.get("daily_delta"))
    trend_value = _signed(analysis.get("trend_delta"))
    daily_unit = '<span>kg</span>' if analysis.get("daily_delta") is not None else ""
    trend_unit = '<span>kg</span>' if analysis.get("trend_delta") is not None else ""
    latest_weight = analysis.get("latest_weight")
    if show_exact_weight and latest_weight is not None:
        first_qualifier = "当前 %.1f kg" % latest_weight
    else:
        first_qualifier = "看见今天的浪" if analysis.get("daily_delta") is not None else "等待下一次记录"

    observation = "%d 日观察" % analysis["window_days"]
    if show_member_name and member_name:
        observation = html.escape(member_name)
    observation_sub = "%d 个记录日" % analysis["recorded_days"]
    exact_date = ""
    if show_exact_date and analysis.get("latest_date"):
        exact_date = " · 最新 %s" % html.escape(analysis["latest_date"])

    clue_markup = ""
    context_section_class = "context"
    if show_context:
        clues = _context_lines(analysis, context_lines)
        clue_markup = "".join(
            '<li class="clue"><span class="clue-index">%02d</span><span>%s</span></li>'
            % (index + 1, html.escape(line))
            for index, line in enumerate(clues)
        )
    else:
        context_section_class += " context-hidden"

    share_safe = not (show_exact_weight or show_member_name or show_exact_date)
    privacy_label = "默认脱敏 · 可分享" if share_safe else "含已选择展示的个人信息"
    card_title = "MediWise 体重真相卡"
    chart = _chart_svg(analysis)
    trend_legend = "趋势" if analysis.get("trend_claim_allowed") else "暂不判断"
    trend_qualifier = "稳健估计，不押首尾两点" if analysis.get("trend_claim_allowed") else "记录不足，暂不判断"

    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light" />
  <title>%s</title>
  <style>
    :root{--paper:#F5F0E6;--ink:#0A2F55;--blue:#246BCE;--cyan:#167A9A;--coral:#D66548;--muted:#5B7080;--hairline:rgba(10,47,85,.17);--font-body:"Avenir Next","Segoe UI Variable","Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-synthesis:none;line-break:strict}
    *{box-sizing:border-box;margin:0;padding:0}html,body{width:100%%;height:100%%;overflow:hidden}body{display:grid;place-items:center;background:#D8D4CC;font-family:var(--font-body);color:var(--ink)}
    .viewport{position:relative;width:1080px;height:1440px;flex:none}.artboard{position:absolute;inset:0 auto auto 0;width:1080px;height:1440px;overflow:hidden;transform-origin:0 0;background:radial-gradient(circle at 91%% 10%%,rgba(214,101,72,.055),transparent 21%%),linear-gradient(180deg,#F8F3EA 0%%,var(--paper) 62%%,#F1EADC 100%%);box-shadow:0 26px 90px rgba(10,47,85,.18);isolation:isolate}
    .artboard:before{content:"";position:absolute;inset:0;pointer-events:none;opacity:.18;mix-blend-mode:multiply;background-image:url("data:image/svg+xml,%%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180' viewBox='0 0 180 180'%%3E%%3Cfilter id='n'%%3E%%3CfeTurbulence type='fractalNoise' baseFrequency='.82' numOctaves='3' stitchTiles='stitch'/%%3E%%3C/filter%%3E%%3Crect width='100%%25' height='100%%25' filter='url(%%23n)' opacity='.10'/%%3E%%3C/svg%%3E");z-index:6}.top-rule{position:absolute;inset:0 0 auto;height:10px;background:var(--ink)}
    .content{position:relative;z-index:2;padding:58px 72px 0}.brand-row{height:70px;display:flex;align-items:center;justify-content:space-between;border-bottom:1.5px solid var(--hairline);padding-bottom:22px}.brand{display:flex;align-items:center;gap:17px}.brand-mark{display:grid;place-items:center;width:51px;height:51px;border-radius:15px;background:#E8F0F7;color:#215E98;font-size:29px;font-weight:800;line-height:1;letter-spacing:-.04em;box-shadow:inset 0 0 0 1px rgba(10,47,85,.04)}.brand-name{font-size:29px;font-weight:670;letter-spacing:-.02em}.brand-sub{margin-top:2px;color:var(--muted);font-size:21px;font-weight:500;letter-spacing:.02em}.observation-id{text-align:right;color:var(--muted);font-size:22px;font-weight:560;line-height:1.42;font-variant-numeric:tabular-nums}.observation-id strong{display:block;color:var(--ink);font-size:25px;font-weight:680}
    .hero{padding-top:44px}.eyebrow{display:flex;align-items:center;gap:16px;color:var(--cyan);font-size:22px;font-weight:700;letter-spacing:.08em}.eyebrow:before{content:"";width:37px;height:3px;background:var(--coral)}h1{max-width:880px;margin-top:16px;color:var(--ink);font-size:76px;font-weight:690;line-height:1.19;letter-spacing:-.018em;text-wrap:balance;font-feature-settings:"halt" 1}.status-line{margin-top:18px;display:flex;align-items:center;gap:14px;color:#435E71;font-size:26px;font-weight:520;line-height:1.55;text-wrap:pretty}.status-line:before{content:"";flex:none;width:10px;height:10px;border-radius:50%%;background:var(--cyan);box-shadow:0 0 0 6px rgba(22,122,154,.11)}
    .metrics{margin-top:28px;display:grid;grid-template-columns:1fr 1fr 1.03fr;border-top:1.5px solid var(--hairline);border-bottom:1.5px solid var(--hairline);padding:22px 0 23px}.metric{min-height:104px;padding:0 31px;border-left:1.5px solid var(--hairline)}.metric:first-child{padding-left:0;border-left:0}.metric:last-child{padding-right:0}.metric-label{color:var(--muted);font-size:22px;font-weight:580}.metric-value{margin-top:7px;color:var(--ink);font-size:53px;font-weight:700;line-height:1.05;letter-spacing:-.025em;font-variant-numeric:tabular-nums}.metric-value.coral{color:var(--coral)}.metric-value.blue{color:var(--blue)}.metric-value span{margin-left:7px;color:currentColor;font-size:24px;font-weight:620;letter-spacing:0}.metric-qualifier{margin-top:10px;color:var(--muted);font-size:20px;line-height:1.35}
    .chart-section{position:relative;margin-top:25px}.chart-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:0}.chart-title{font-size:25px;font-weight:650}.legend{display:flex;align-items:center;gap:27px;color:var(--muted);font-size:20px;font-weight:540}.legend-item{display:inline-flex;align-items:center;gap:10px}.legend-dot{width:10px;height:10px;border-radius:50%%;background:#6F9EB6;box-shadow:0 0 0 5px rgba(111,158,182,.13)}.legend-line{width:30px;height:5px;border-radius:999px;background:var(--ink)}.chart{display:block;width:936px;height:330px;overflow:visible}.chart text{font-family:var(--font-body)}
    .context{display:grid;grid-template-columns:212px 1fr;column-gap:34px;margin-top:0;padding-top:22px;border-top:1.5px solid var(--hairline)}.context-hidden{display:none}.context-kicker{color:var(--cyan);font-size:21px;font-weight:700;letter-spacing:.08em}.context-kicker span{display:block;margin-top:8px;color:var(--muted);font-size:19px;font-weight:520;letter-spacing:0;line-height:1.5}.clues{list-style:none}.clue{display:grid;grid-template-columns:33px 1fr;gap:12px;color:var(--ink);font-size:23px;font-weight:560;line-height:1.5;text-wrap:pretty}.clue+.clue{margin-top:6px}.clue-index{padding-top:2px;color:var(--coral);font-size:20px;font-weight:760;font-variant-numeric:tabular-nums}
    .footer-sea{position:absolute;left:0;right:0;bottom:0;height:270px;padding:60px 72px 37px;color:#F6F0E5;background:var(--ink);clip-path:polygon(0 11%%,15%% 7%%,30%% 10%%,46%% 4%%,64%% 9%%,82%% 3%%,100%% 8%%,100%% 100%%,0 100%%);z-index:1}.footer-sea:before,.footer-sea:after{content:"";position:absolute;left:-4%%;width:108%%;border-top:1px solid rgba(255,255,255,.12);border-radius:50%%;pointer-events:none}.footer-sea:before{top:46px;height:52px;transform:rotate(-.7deg)}.footer-sea:after{top:63px;height:58px;transform:rotate(.5deg);opacity:.65}.closing{position:relative;z-index:1;font-size:46px;font-weight:610;line-height:1.25;letter-spacing:-.01em}.closing:before{content:"「";color:#8CB6CC}.closing:after{content:"」";color:#8CB6CC}.safety{position:relative;z-index:1;max-width:850px;margin-top:12px;color:rgba(246,240,229,.76);font-size:20px;font-weight:450;line-height:1.55;letter-spacing:.005em;text-wrap:pretty}.footer-meta{position:absolute;z-index:1;left:72px;right:72px;bottom:27px;display:flex;justify-content:space-between;align-items:center;color:rgba(246,240,229,.68);font-size:19px;font-weight:520}.privacy{color:#F6F0E5;font-weight:640}
  </style>
</head>
<body>
  <div class="viewport" id="viewport">
    <main class="artboard" id="artboard" data-share-safe="%s" aria-label="MediWise 体重真相卡">
      <div class="top-rule"></div>
      <div class="content">
        <header class="brand-row"><div class="brand"><div class="brand-mark" aria-hidden="true">M</div><div><div class="brand-name">MediWise</div><div class="brand-sub">体重真相卡</div></div></div><div class="observation-id"><strong>%s</strong>%s</div></header>
        <section class="hero"><div class="eyebrow">今日翻译</div><h1>%s</h1><p class="status-line">%s</p></section>
        <section class="metrics" aria-label="核心数据">
          <div class="metric"><div class="metric-label">%s</div><div class="metric-value coral">%s%s</div><div class="metric-qualifier">%s</div></div>
          <div class="metric"><div class="metric-label">%d 日趋势</div><div class="metric-value blue">%s%s</div><div class="metric-qualifier">%s</div></div>
          <div class="metric"><div class="metric-label">记录覆盖</div><div class="metric-value">%d / %d<span>天</span></div><div class="metric-qualifier">可信度：%s</div></div>
        </section>
        <section class="chart-section" aria-label="秤面波动与稳健趋势示意图"><div class="chart-head"><div class="chart-title">秤面与趋势，不必同一天到达</div><div class="legend"><span class="legend-item"><i class="legend-dot"></i>秤面</span><span class="legend-item"><i class="legend-line"></i>%s</span></div></div>%s</section>
        <section class="%s" aria-label="可能相关的记录线索"><div class="context-kicker">记录线索<span>只陈述事实，不归因</span></div><ol class="clues">%s</ol></section>
      </div>
      <footer class="footer-sea"><div class="closing">%s</div><p class="safety">%s</p><div class="footer-meta"><span>%s%s</span><span class="privacy">MediWise · 数据默认本地</span></div></footer>
    </main>
  </div>
  <script>(()=>{const W=1080,H=1440,v=document.getElementById('viewport'),a=document.getElementById('artboard');function fit(){const s=Math.min(innerWidth/W,innerHeight/H);v.style.width=`${W*s}px`;v.style.height=`${H*s}px`;a.style.transform=`scale(${s})`}addEventListener('resize',fit,{passive:true});fit();window.__ready=true})()</script>
</body></html>""" % (
        html.escape(card_title),
        "true" if share_safe else "false",
        observation,
        html.escape(observation_sub),
        html.escape(copy["headline"]),
        html.escape(copy["status"]),
        html.escape(comparison_label),
        daily_value,
        daily_unit,
        html.escape(first_qualifier),
        analysis["window_days"],
        trend_value,
        trend_unit,
        html.escape(trend_qualifier),
        analysis["recorded_days"],
        analysis["window_days"],
        html.escape(analysis["confidence_label"]),
        html.escape(trend_legend),
        chart,
        context_section_class,
        clue_markup,
        html.escape(copy["closing"]),
        html.escape(DISCLAIMER),
        html.escape(privacy_label),
        exact_date,
    )


_find_chrome = _story_export.find_chrome
_png_dimensions = _story_export.png_dimensions


# `both` predates the motion layer and meant html+png.  It keeps that meaning so
# existing callers are unaffected; `all` is the opt-in that adds the animated SVG.
CARD_FORMATS = ("html", "png", "svg", "both", "all")
_FORMAT_ARTIFACTS = {
    "html": ("html",),
    "png": ("html", "png"),
    "svg": ("html", "svg"),
    "both": ("html", "png"),
    "all": ("html", "png", "svg"),
}


_SVG_ATTR = re.compile(r'data-%s="(\d+)"')


def _svg_attr(document: str, name: str) -> Optional[int]:
    """Read one numeric `data-*` off the SVG root the renderer just produced."""
    found = re.search(_SVG_ATTR.pattern % name, document)
    return int(found.group(1)) if found else None


def wants(fmt: str, artifact: str) -> bool:
    """Whether `fmt` asks for this artifact.  HTML is always written: it is the
    composition of record, and both the PNG and the SVG are derived from it."""
    return artifact in _FORMAT_ARTIFACTS.get(fmt, _FORMAT_ARTIFACTS["both"])


def render_png_fixed(html_path: str, output_path: str, chrome_binary: Optional[str] = None) -> dict:
    """Render exactly 1080x1440 from the *settled* frame.

    Capture is delegated to shared/story/export.py, which waits for
    `window.__ready` (Playwright) or advances virtual time until the composition
    parks (Chrome).  Before that, this function shot the page the instant load
    fired — fine for a static card, but with the motion layer in place it would
    capture an arbitrary animation frame and make the golden digests drift.
    """
    return _story_export.capture_poster_png(
        html_path,
        output_path,
        width=CARD_WIDTH,
        height=CARD_HEIGHT,
        chrome_binary=chrome_binary,
    )


def _load_member_records(member_id: str, owner_id: Optional[str], days: int, as_of: date) -> Tuple[Optional[dict], List[dict]]:
    ensure_db()
    start = as_of - timedelta(days=days - 1)
    conn = get_medical_connection()
    try:
        if not verify_member_ownership(conn, member_id, owner_id):
            return None, []
        member = conn.execute(
            "SELECT id,name FROM members WHERE id=? AND is_deleted=0", (member_id,)
        ).fetchone()
        if not member:
            return None, []
        rows = conn.execute(
            """SELECT value, measured_at FROM health_metrics
               WHERE member_id=? AND metric_type='weight' AND is_deleted=0
                 AND measured_at>=? AND measured_at<=?
               ORDER BY measured_at ASC""",
            (member_id, start.isoformat(), as_of.isoformat() + " 23:59:59"),
        ).fetchall()
        return dict(member), [dict(row) for row in rows]
    finally:
        conn.close()


def _load_weight_management_records(
    member_id: str, owner_id: Optional[str], days: int, as_of: date
) -> Tuple[Optional[dict], List[dict], List[dict], List[dict], List[dict]]:
    """Load the four parallel record domains used by the story-card analysis."""
    member, weight_records = _load_member_records(member_id, owner_id, days, as_of)
    if not member:
        return None, [], [], [], []
    start = as_of - timedelta(days=days - 1)
    medical = get_medical_connection()
    lifestyle = get_lifestyle_connection()
    try:
        sleep_rows = medical.execute(
            """SELECT value, measured_at FROM health_metrics
               WHERE member_id=? AND metric_type='sleep' AND is_deleted=0
                 AND measured_at>=? AND measured_at<=?
               ORDER BY measured_at ASC""",
            (member_id, start.isoformat(), as_of.isoformat() + " 23:59:59"),
        ).fetchall()
        diet_rows = lifestyle.execute(
            """SELECT meal_date,total_calories,total_protein,total_fat,total_carbs,total_fiber
               FROM diet_records
               WHERE member_id=? AND is_deleted=0 AND meal_date>=? AND meal_date<=?
               ORDER BY meal_date ASC, meal_time ASC""",
            (member_id, start.isoformat(), as_of.isoformat()),
        ).fetchall()
        exercise_rows = lifestyle.execute(
            """SELECT exercise_date,duration,calories_burned,exercise_type,intensity
               FROM exercise_records
               WHERE member_id=? AND is_deleted=0 AND exercise_date>=? AND exercise_date<=?
               ORDER BY exercise_date ASC, exercise_time ASC""",
            (member_id, start.isoformat(), as_of.isoformat()),
        ).fetchall()
        return (
            member,
            weight_records,
            [dict(row) for row in diet_rows],
            [dict(row) for row in exercise_rows],
            [dict(row) for row in sleep_rows],
        )
    finally:
        medical.close()
        lifestyle.close()


def _load_domain_analysis(
    domain: str,
    member_id: str,
    owner_id: Optional[str],
    days: int,
    as_of: date,
) -> Tuple[Optional[dict], dict]:
    """Load one story domain without crossing its adapter's data boundary."""
    ensure_db()
    start = as_of - timedelta(days=days - 1)
    conn = get_medical_connection()
    lifestyle = None
    try:
        if not verify_member_ownership(conn, member_id, owner_id):
            return None, {}

        # A family card must not acquire a name that a reveal flag could print.
        # Every other domain retains the existing member-card behavior.
        if domain == "family":
            member = conn.execute(
                "SELECT id FROM members WHERE id=? AND is_deleted=0", (member_id,)
            ).fetchone()
        else:
            member = conn.execute(
                "SELECT id,name FROM members WHERE id=? AND is_deleted=0", (member_id,)
            ).fetchone()
        if not member:
            return None, {}

        end_of_day = as_of.isoformat() + " 23:59:59"
        raw_rows = []
        if domain == "weight":
            raw_rows = conn.execute(
                """SELECT value, measured_at FROM health_metrics
                   WHERE member_id=? AND metric_type='weight' AND is_deleted=0
                     AND measured_at>=? AND measured_at<=?
                   ORDER BY measured_at ASC""",
                (member_id, start.isoformat(), end_of_day),
            ).fetchall()
        elif domain == "sleep":
            # A night's record may arrive the following morning.  This matches
            # sleep.py's 14:00 next-day upper bound.
            sleep_end = (as_of + timedelta(days=1)).isoformat() + " 14:00:00"
            raw_rows = conn.execute(
                """SELECT value, measured_at FROM health_metrics
                   WHERE member_id=? AND metric_type='sleep' AND is_deleted=0
                     AND measured_at>=? AND measured_at<=?
                   ORDER BY measured_at ASC""",
                (member_id, start.isoformat(), sleep_end),
            ).fetchall()
        elif domain == "vitals":
            raw_rows = conn.execute(
                """SELECT metric_type, value, measured_at FROM health_metrics
                   WHERE member_id=? AND is_deleted=0
                     AND metric_type IN ('heart_rate','blood_pressure','temperature','blood_oxygen')
                     AND measured_at>=? AND measured_at<=?
                   ORDER BY measured_at ASC""",
                (member_id, start.isoformat(), end_of_day),
            ).fetchall()
        elif domain == "activity":
            raw_rows = conn.execute(
                """SELECT metric_type, value, measured_at, source FROM health_metrics
                   WHERE member_id=? AND metric_type='steps' AND is_deleted=0
                     AND measured_at>=? AND measured_at<=?
                   ORDER BY measured_at ASC""",
                (member_id, start.isoformat(), end_of_day),
            ).fetchall()
        elif domain == "adherence":
            raw_rows = conn.execute(
                """SELECT taken_at FROM medication_logs
                   WHERE member_id=? AND is_deleted=0
                     AND taken_at>=? AND taken_at<=?
                   ORDER BY taken_at ASC""",
                (member_id, start.isoformat(), end_of_day),
            ).fetchall()
        elif domain == "intake":
            lifestyle = get_lifestyle_connection()
            raw_rows = lifestyle.execute(
                """SELECT meal_date,total_calories,total_protein,total_fat,total_carbs
                   FROM diet_records
                   WHERE member_id=? AND is_deleted=0
                     AND meal_date>=? AND meal_date<=?
                   ORDER BY meal_date ASC, meal_time ASC""",
                (member_id, start.isoformat(), as_of.isoformat()),
            ).fetchall()
        elif domain == "family":
            # Use the selected member only when it has no owner grouping.  This
            # prevents unrelated owner-less records from becoming one household.
            raw_rows = conn.execute(
                """SELECT metric.member_id AS member_id,
                          substr(metric.measured_at, 1, 10) AS date
                   FROM health_metrics AS metric
                   JOIN members AS household
                     ON household.id=metric.member_id AND household.is_deleted=0
                   JOIN members AS anchor
                     ON anchor.id=? AND anchor.is_deleted=0
                   WHERE metric.is_deleted=0
                     AND ((anchor.owner_id IS NOT NULL AND household.owner_id=anchor.owner_id)
                          OR (anchor.owner_id IS NULL AND household.id=anchor.id))
                     AND metric.measured_at>=? AND metric.measured_at<=?
                   ORDER BY metric.measured_at ASC""",
                (member_id, start.isoformat(), end_of_day),
            ).fetchall()
        elif domain == "records":
            raw_rows = conn.execute(
                """SELECT substr(measured_at, 1, 10) AS date FROM health_metrics
                   WHERE member_id=? AND is_deleted=0
                     AND measured_at>=? AND measured_at<=?
                   ORDER BY measured_at ASC""",
                (member_id, start.isoformat(), end_of_day),
            ).fetchall()
        else:
            raise ValueError("未接入的域：%s" % domain)

        converted = [dict(row) for row in raw_rows]
        if domain == "weight":
            # Weight alone is pass-through at the adapter boundary; it must be
            # folded before it gets there.
            return dict(member), analyze_weight_records(converted, days)

        rows = []
        for row in converted:
            if domain == "sleep":
                try:
                    payload = json.loads(row.get("value") or "")
                except (TypeError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                raw_duration = payload.get("duration_min")
                if isinstance(raw_duration, bool):
                    continue
                try:
                    duration = float(raw_duration)
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(duration) or duration <= 0:
                    continue
                rows.append({
                    "date": str(row.get("measured_at") or "")[:10],
                    "duration_min": int(duration) if duration.is_integer() else duration,
                })
            elif domain == "vitals":
                rows.append({
                    "date": str(row.get("measured_at") or "")[:10],
                    "metric_type": row.get("metric_type"),
                    "value": row.get("value"),
                })
            elif domain == "activity":
                rows.append({
                    "metric_type": row.get("metric_type"),
                    "value": row.get("value"),
                    "measured_at": row.get("measured_at"),
                    "source": row.get("source"),
                })
            elif domain == "adherence":
                rows.append({"date": str(row.get("taken_at") or "")[:10]})
            else:
                # Intake already uses its table's canonical column names;
                # family and records were projected to their safe two/one-key
                # shapes in SQL.
                rows.append(row)

        return dict(member), _domain_analysis_from_rows(domain, rows, days)
    finally:
        if lifestyle is not None:
            lifestyle.close()
        conn.close()


def _demo_records(as_of: date) -> List[dict]:
    values = [70.7, 70.5, 70.6, 70.2, 70.3, 70.1, 70.0, 69.9, 70.0, 69.8, 69.7, 70.5]
    offsets = [0, 1, 2, 4, 5, 6, 7, 9, 10, 11, 12, 13]
    start = as_of - timedelta(days=13)
    return [
        {"value": value, "measured_at": (start + timedelta(days=offset)).isoformat() + " 08:00:00"}
        for offset, value in zip(offsets, values)
    ]


def _demo_management_records(as_of: date, days: int) -> Tuple[List[dict], List[dict], List[dict]]:
    """Create a rich but non-prescriptive demo for the story-card gallery."""
    start = as_of - timedelta(days=days - 1)
    diet = []
    exercise = []
    sleep = []
    for index in range(days):
        day = (start + timedelta(days=index)).isoformat()
        if index % 4 != 3:
            diet.append({
                "meal_date": day,
                "total_calories": 1910 - (70 if index >= days // 2 else 0) + (index % 3) * 18,
                "total_protein": 78 + (index % 4) * 3,
            })
        if index % 3 == 1:
            exercise.append({
                "exercise_date": day,
                "duration": 34 + (18 if index >= days // 2 else 0) + (index % 2) * 8,
                "calories_burned": 210 + (index % 4) * 20,
            })
        if index % 5 != 0:
            duration = 412 + (28 if index >= days // 2 else 0) + (index % 3) * 7
            sleep.append({"measured_at": day + " 07:00:00", "value": {"duration_min": duration}})
    return diet, exercise, sleep


def _demo_domain_analysis(domain: str, as_of: date, days: int) -> dict:
    """Build a gap-aware, direction-visible demo in the domain's raw shape."""
    if domain == "weight":
        return analyze_weight_records(_demo_records(as_of), days)
    if domain not in STORY_DOMAINS:
        raise ValueError("未接入的域：%s" % domain)

    start = as_of - timedelta(days=days - 1)
    rows = []
    for index in range(days):
        # Leave real gaps; an unrecorded day is absent, never a synthetic zero.
        if index % 5 == 2:
            continue
        day = (start + timedelta(days=index)).isoformat()
        later = index >= days // 2
        wobble = (index % 3) - 1

        if domain == "sleep":
            rows.append({"date": day, "duration_min": 390 + (55 if later else 0) + wobble * 8})
        elif domain == "vitals":
            rows.append({
                "date": day,
                "metric_type": "heart_rate",
                "value": str(68 + (9 if later else 0) + wobble * 2),
            })
        elif domain == "activity":
            rows.append({
                "date": day,
                "metric_type": "steps",
                "value": {"count": 5100 + (1900 if later else 0) + wobble * 260},
                "source": "demo-device",
            })
        elif domain == "intake":
            for meal_index in range(2):
                rows.append({
                    "meal_date": day,
                    "total_calories": 690 + (180 if later else 0) + meal_index * 35 + wobble * 12,
                    "total_protein": 28 + (5 if later else 0) + meal_index * 3,
                    "total_fat": 22 + (4 if later else 0) + meal_index * 2,
                    "total_carbs": 82 + (12 if later else 0) + meal_index * 6,
                })
        elif domain in ("adherence", "records"):
            rows.append({"date": day})
            if later:
                rows.append({"date": day})
        elif domain == "family":
            rows.append({"date": day, "member_id": "demo-a"})
            if later:
                rows.append({"date": day, "member_id": "demo-b"})

    return _domain_analysis_from_rows(domain, rows, days)


def _story_dir_for(domain: str) -> str:
    """Keep weight's historic folder while namespacing every other domain."""
    return "weight-stories" if domain == STORY_DOMAIN else "%s-stories" % domain


def _safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value or "member").strip(".-")
    return cleaned[:80] or "member"


def _write_private(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--member-id")
    parser.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--as-of")
    parser.add_argument("--demo", action="store_true")
    if command in ("select-style", "generate-story"):
        # Which reading the card narrates.  The storytelling engine is domain-neutral;
        # weight is the default only because it is the case this action shipped with.
        parser.add_argument("--domain", choices=STORY_DOMAINS, default=STORY_DOMAIN)
        parser.add_argument("--scene", choices=("daily", "weekly", "milestone", "share"), default="daily")
        parser.add_argument(
            "--tone",
            choices=("auto", "gentle", "calm", "playful", "editorial", "bold"),
        )
        parser.add_argument("--density", choices=("auto", "concise", "detailed"))
        parser.add_argument("--preferred-style", action="append", default=[])
        parser.add_argument("--disliked-style", action="append", default=[])
        parser.add_argument("--recent-style", action="append", default=[])
        parser.add_argument("--pinned-style")
        parser.add_argument("--surprise-level", type=float)
        parser.add_argument("--seed")
    if command == "generate-story":
        parser.add_argument("--style", choices=("auto", *sorted(STYLES_BY_ID)), default="auto")
        parser.add_argument("--format", choices=CARD_FORMATS, default="both")
        parser.add_argument("--show-exact-weight", action="store_true")
        parser.add_argument("--show-member-name", action="store_true")
        parser.add_argument("--show-exact-date", action="store_true")
        parser.add_argument("--hide-context", action="store_true")
        parser.add_argument("--context", action="append", default=[])
        parser.add_argument("--output-dir")
        parser.add_argument("--no-save-history", action="store_true")
    if command == "generate":
        parser.add_argument("--format", choices=CARD_FORMATS, default="both")
        parser.add_argument("--theme", choices=("direction",), default="direction")
        parser.add_argument("--show-exact-weight", action="store_true")
        parser.add_argument("--show-member-name", action="store_true")
        parser.add_argument("--show-exact-date", action="store_true")
        parser.add_argument("--hide-context", action="store_true")
        parser.add_argument("--context", action="append", default=[])
        parser.add_argument("--output-dir")
    return parser


def run(command: str, args: argparse.Namespace) -> dict:
    days = max(7, min(int(args.days or DEFAULT_DAYS), 90))
    try:
        as_of = datetime.strptime(args.as_of, "%Y-%m-%d").date() if args.as_of else datetime.now().date()
    except ValueError:
        return {"status": "error", "message": "--as-of 必须是 YYYY-MM-DD"}

    domain = getattr(args, "domain", STORY_DOMAIN) or STORY_DOMAIN

    if domain != STORY_DOMAIN:
        # Every other domain reads its own table and narrates from a Signal Frame.
        # Weight keeps its original path untouched: its output is locked
        # byte-for-byte, and `analyze_weight_records` is the producer that lock
        # was taken against.
        if args.demo:
            member = {"id": "demo", "name": "演示成员"}
            analysis = _demo_domain_analysis(domain, as_of, days)
        else:
            if not args.member_id:
                return {"status": "error", "message": "缺少 --member-id"}
            member, analysis = _load_domain_analysis(
                domain, args.member_id, args.owner_id, days, as_of
            )
            if not member:
                return {"status": "error", "message": "未找到成员或无权访问: %s" % args.member_id}
        analysis = story_render_ready(domain, analysis)
    else:
        if args.demo:
            member = {"id": "demo", "name": "演示成员"}
            records = _demo_records(as_of)
            diet_records, exercise_records, sleep_records = _demo_management_records(as_of, days)
        else:
            if not args.member_id:
                return {"status": "error", "message": "缺少 --member-id"}
            if command in ("select-style", "generate-story"):
                member, records, diet_records, exercise_records, sleep_records = _load_weight_management_records(
                    args.member_id, args.owner_id, days, as_of
                )
            else:
                member, records = _load_member_records(args.member_id, args.owner_id, days, as_of)
                diet_records, exercise_records, sleep_records = [], [], []
            if not member:
                return {"status": "error", "message": "未找到成员或无权访问: %s" % args.member_id}

        analysis = analyze_weight_records(records, days)
        if command in ("select-style", "generate-story"):
            analysis["management"] = analyze_weight_management(
                analysis,
                diet_records,
                exercise_records,
                sleep_records,
                days=days,
                as_of=as_of,
            )
    # After the analysis, not before it: for vitals, intake and activity the wording
    # depends on which component the window turned out to hold, and that is only
    # known once the rows have been read.
    lexicon = story_lexicon_for_analysis(domain, analysis)
    base_result = {
        "status": "ok",
        "domain": domain,
        "analysis": analysis,
        "interpretation": {
            # Only the weight producer writes curated `copy`; every other domain
            # carries its wording in the frame, which the renderers read directly.
            "copy": analysis.get("copy"),
            "disclaimer": _disclaimer_for(domain),
            "deterministic": True,
        },
        "privacy": {
            "share_safe_default": True,
            "hidden_by_default": ["member_name", "exact_weight", "goal_weight", "exact_dates", "medications", "labs"],
        },
    }
    if command == "analyze":
        return base_result

    if command == "select-style":
        profile = get_style_profile(member.get("id", "anonymous"))
        style_seed = args.seed or derive_style_seed(
            member.get("id", "anonymous"),
            analysis.get("latest_date") or as_of.isoformat(),
            profile.get("generation_count", 0),
        )
        try:
            base_result["style_selection"] = select_weight_card_style(
                analysis,
                scene=args.scene,
                tone=args.tone or profile["tone"],
                density=args.density or profile["density"],
                preferred_styles=set(profile["preferred_styles"]) | set(args.preferred_style),
                disliked_styles=set(profile["disliked_styles"]) | set(args.disliked_style),
                recent_styles=args.recent_style or profile["recent_styles"],
                pinned_style=args.pinned_style or profile["pinned_style"],
                surprise_level=(
                    args.surprise_level
                    if args.surprise_level is not None
                    else profile["surprise_level"]
                ),
                seed=style_seed,
                domain=domain,
                lexicon=lexicon,
            )
            base_result["style_profile"] = profile
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}
        return base_result

    if command == "generate-story":
        profile = get_style_profile(member.get("id", "anonymous"))
        style_seed = args.seed or derive_style_seed(
            member.get("id", "anonymous"),
            analysis.get("latest_date") or as_of.isoformat(),
            profile.get("generation_count", 0),
        )
        explicit_style = args.style if args.style != "auto" else None
        try:
            selection = select_weight_card_style(
                analysis,
                scene=args.scene,
                tone=args.tone or profile["tone"],
                density=args.density or profile["density"],
                preferred_styles=set(profile["preferred_styles"]) | set(args.preferred_style),
                disliked_styles=set(profile["disliked_styles"]) | set(args.disliked_style),
                recent_styles=args.recent_style or profile["recent_styles"],
                pinned_style=explicit_style or args.pinned_style or profile["pinned_style"],
                surprise_level=(
                    args.surprise_level
                    if args.surprise_level is not None
                    else profile["surprise_level"]
                ),
                seed=style_seed,
                domain=domain,
                lexicon=lexicon,
            )
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}

        output_dir = args.output_dir or os.path.join(DATA_DIR, "reports", _story_dir_for(domain))
        os.makedirs(output_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(output_dir, 0o700)
        except OSError:
            pass
        selected_style = selection["selected_style"]["id"]
        slug = _safe_slug(member["id"])
        stem = "%s_story_%s_%s_%s" % (domain, slug, as_of.isoformat(), _safe_slug(selected_style))
        html_path = os.path.abspath(os.path.join(output_dir, stem + ".html"))
        png_path = os.path.abspath(os.path.join(output_dir, stem + ".png"))
        svg_path = os.path.abspath(os.path.join(output_dir, stem + ".svg"))
        story_context = [] if args.hide_context else _context_lines(analysis, args.context)
        reveal = {
            "show_exact_weight": args.show_exact_weight,
            "show_member_name": args.show_member_name,
            "show_exact_date": args.show_exact_date,
        }
        try:
            card_html = render_weight_story_html(
                analysis,
                selection,
                member_name=member.get("name", ""),
                context_lines=story_context,
                domain=domain,
                lexicon=lexicon,
                **reveal,
            )
            _write_private(html_path, card_html)
            card_svg = None
            if wants(args.format, "svg"):
                # Same analysis, same selection, same reveal flags as the HTML:
                # the animated card must never disclose more than the still one.
                card_svg = render_story_svg(
                    analysis,
                    selection,
                    member_name=member.get("name", ""),
                    context_lines=story_context,
                    domain=domain,
                    lexicon=lexicon,
                    **reveal,
                )
                _write_private(svg_path, card_svg)
        except (OSError, ValueError) as exc:
            return {"status": "error", "message": "体重译报生成失败：%s" % exc}

        card = {
            "product_name": story_product_name_for(domain),
            "style": selected_style,
            "style_name": selection["selected_style"]["name"],
            "format": args.format,
            "width": CARD_WIDTH,
            "height": CARD_HEIGHT,
            "html_path": html_path,
            "png_path": None,
            "svg_path": svg_path if card_svg is not None else None,
            "render": {"status": "not_requested"},
            "share_safe": not (
                args.show_exact_weight or args.show_member_name or args.show_exact_date
            ),
        }
        if card_svg is not None:
            # What the SVG will actually do, so a caller can describe the card
            # without parsing it.
            card["motion"] = {
                "mode": selection["selected_style"].get("motion_mode"),
                "duration_ms": _svg_attr(card_svg, "duration-ms"),
                "poster_time_ms": _svg_attr(card_svg, "poster-time-ms"),
            }
        if wants(args.format, "png"):
            # Captured from the HTML, not the SVG: the still card is the frame of
            # record, and the frozen SVG is verified to reproduce it pixel for pixel.
            card["render"] = render_png_fixed(html_path, png_path)
            if card["render"].get("status") == "ok":
                card["png_path"] = png_path

        history = {"saved": False, "profile": profile}
        if not args.no_save_history:
            try:
                updated = update_style_profile(
                    member.get("id", "anonymous"), generated_style=selected_style
                )
                history = {"saved": True, "profile": updated["profile"]}
            except OSError as exc:
                history = {"saved": False, "message": str(exc), "profile": profile}

        base_result["product_name"] = story_product_name_for(domain)
        base_result["style_selection"] = selection
        base_result["style_history"] = history
        base_result["card"] = card
        return base_result

    output_dir = args.output_dir or os.path.join(DATA_DIR, "reports", "weight-cards")
    os.makedirs(output_dir, mode=0o700, exist_ok=True)
    try:
        os.chmod(output_dir, 0o700)
    except OSError:
        pass
    slug = _safe_slug(member["id"])
    stem = "weight_truth_%s_%s" % (slug, as_of.isoformat())
    html_path = os.path.abspath(os.path.join(output_dir, stem + ".html"))
    png_path = os.path.abspath(os.path.join(output_dir, stem + ".png"))
    card_html = render_card_html(
        analysis,
        member_name=member.get("name", ""),
        show_exact_weight=args.show_exact_weight,
        show_member_name=args.show_member_name,
        show_exact_date=args.show_exact_date,
        show_context=not args.hide_context,
        context_lines=args.context,
    )
    _write_private(html_path, card_html)

    card = {
        "theme": args.theme,
        "format": args.format,
        "width": CARD_WIDTH,
        "height": CARD_HEIGHT,
        "html_path": html_path,
        "png_path": None,
        "render": {"status": "not_requested"},
        "share_safe": not (args.show_exact_weight or args.show_member_name or args.show_exact_date),
    }
    if wants(args.format, "svg"):
        # The direction card is a single fixed layout with no motion_mode, so there
        # is no timeline to compile.  Say so instead of writing a still SVG that
        # pretends to be animated; `generate-story` is the animated product.
        card["svg_path"] = None
        card["motion"] = {
            "status": "unavailable",
            "message": "体重真相卡为固定版式，动画卡请使用 generate-weight-story-card",
        }
    if wants(args.format, "png"):
        card["render"] = render_png_fixed(html_path, png_path)
        if card["render"].get("status") == "ok":
            card["png_path"] = png_path
    base_result["card"] = card
    return base_result


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("analyze", "select-style", "generate-story", "generate"):
        output_json({
            "status": "error",
            "message": "Usage: weight_truth_card.py analyze|select-style|generate-story|generate [options]",
        })
        return
    command = sys.argv[1]
    args = _parser(command).parse_args(sys.argv[2:])
    output_json(run(command, args))


if __name__ == "__main__":
    main()
