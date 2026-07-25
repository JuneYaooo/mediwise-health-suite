"""Robust, share-safe weight trend analysis and fixed-canvas result cards.

The existing weight-analysis actions intentionally remain unchanged for
backward compatibility.  This module adds a separate interpretation layer
that distinguishes a single measurement from the longer trend.  Copy is
selected from curated states; no free-form model output or prescription is
used.

Usage:
  python3 weight_truth_card.py analyze --member-id <id> [--days 14]
  python3 weight_truth_card.py generate --member-id <id> [--days 14]
      [--format html|png|both] [--show-exact-weight]
      [--show-member-name] [--show-exact-date] [--context <fact>]
"""

from __future__ import annotations

import argparse
import html
import math
import os
import re
import struct
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import median
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
from weight_card_styles import STYLES_BY_ID
from weight_management_analysis import analyze_weight_management
from weight_story_card import PRODUCT_NAME as STORY_PRODUCT_NAME, render_weight_story_html
from weight_style_selector import derive_style_seed, select_weight_card_style


CARD_WIDTH = 1080
CARD_HEIGHT = 1440
DEFAULT_DAYS = 14
DISCLAIMER = "相关线索不代表因果；本卡不提供诊断或减重处方。"


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


def _parse_date(value) -> Optional[date]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None


def aggregate_daily_medians(records: Iterable[dict]) -> List[dict]:
    """Collapse same-day measurements to a median before trend analysis."""
    grouped = {}  # type: Dict[date, List[float]]
    for record in records:
        measured_date = _parse_date(record.get("measured_at") or record.get("date"))
        raw_value = record.get("weight", record.get("value"))
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if measured_date is None or not math.isfinite(value) or not 10 <= value <= 500:
            continue
        grouped.setdefault(measured_date, []).append(value)

    result = []
    for measured_date in sorted(grouped):
        values = grouped[measured_date]
        result.append({
            "date": measured_date.isoformat(),
            "weight": round(float(median(values)), 3),
            "measurement_count": len(values),
        })
    return result


def theil_sen_fit(daily_records: Sequence[dict]) -> Tuple[Optional[float], Optional[float]]:
    """Return Theil-Sen slope in kg/day and a median intercept."""
    if len(daily_records) < 2:
        return None, None
    origin = _parse_date(daily_records[0]["date"])
    if origin is None:
        return None, None
    points = []
    for item in daily_records:
        item_date = _parse_date(item["date"])
        if item_date is not None:
            points.append(((item_date - origin).days, float(item["weight"])))
    slopes = []
    for index, (x1, y1) in enumerate(points):
        for x2, y2 in points[index + 1:]:
            if x2 != x1:
                slopes.append((y2 - y1) / (x2 - x1))
    if not slopes:
        return None, None
    slope = float(median(slopes))
    intercept = float(median([weight - slope * offset for offset, weight in points]))
    return slope, intercept


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
            "method": "daily_median+theil_sen",
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
        "method": "daily_median+theil_sen",
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


def _find_chrome() -> Optional[str]:
    try:
        import html_screenshot
        return html_screenshot.find_chrome()
    except (ImportError, AttributeError):
        return None


def _png_dimensions(path: str) -> Optional[Tuple[int, int]]:
    try:
        with open(path, "rb") as handle:
            header = handle.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", header[16:24])
    except (OSError, struct.error):
        return None


def render_png_fixed(html_path: str, output_path: str, chrome_binary: Optional[str] = None) -> dict:
    """Render exactly 1080x1440; return unavailable instead of failing HTML output."""
    chrome = chrome_binary if chrome_binary is not None else _find_chrome()
    if not chrome:
        return {"status": "unavailable", "message": "未找到 Chrome/Chromium，HTML 已正常生成"}
    command = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--hide-scrollbars",
        "--disable-background-networking",
        "--force-device-scale-factor=1",
        "--window-size=%d,%d" % (CARD_WIDTH, CARD_HEIGHT),
        "--screenshot=%s" % output_path,
        Path(html_path).resolve().as_uri(),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=25)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"status": "unavailable", "message": "PNG 渲染不可用：%s" % exc}
    if completed.returncode != 0 or not os.path.isfile(output_path):
        detail = (completed.stderr or "Chrome screenshot failed")[:400]
        return {"status": "unavailable", "message": detail}
    dimensions = _png_dimensions(output_path)
    if dimensions != (CARD_WIDTH, CARD_HEIGHT):
        try:
            os.unlink(output_path)
        except OSError:
            pass
        return {"status": "unavailable", "message": "PNG 尺寸异常：%s" % (dimensions,)}
    try:
        os.chmod(output_path, 0o600)
    except OSError:
        pass
    return {
        "status": "ok",
        "image_path": output_path,
        "width": CARD_WIDTH,
        "height": CARD_HEIGHT,
        "file_size": os.path.getsize(output_path),
    }


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
        parser.add_argument("--format", choices=("html", "png", "both"), default="both")
        parser.add_argument("--show-exact-weight", action="store_true")
        parser.add_argument("--show-member-name", action="store_true")
        parser.add_argument("--show-exact-date", action="store_true")
        parser.add_argument("--hide-context", action="store_true")
        parser.add_argument("--context", action="append", default=[])
        parser.add_argument("--output-dir")
        parser.add_argument("--no-save-history", action="store_true")
    if command == "generate":
        parser.add_argument("--format", choices=("html", "png", "both"), default="both")
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
    base_result = {
        "status": "ok",
        "analysis": analysis,
        "interpretation": {
            "copy": analysis["copy"],
            "disclaimer": DISCLAIMER,
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
            )
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}

        output_dir = args.output_dir or os.path.join(DATA_DIR, "reports", "weight-stories")
        os.makedirs(output_dir, mode=0o700, exist_ok=True)
        try:
            os.chmod(output_dir, 0o700)
        except OSError:
            pass
        selected_style = selection["selected_style"]["id"]
        slug = _safe_slug(member["id"])
        stem = "weight_story_%s_%s_%s" % (slug, as_of.isoformat(), _safe_slug(selected_style))
        html_path = os.path.abspath(os.path.join(output_dir, stem + ".html"))
        png_path = os.path.abspath(os.path.join(output_dir, stem + ".png"))
        story_context = [] if args.hide_context else _context_lines(analysis, args.context)
        try:
            card_html = render_weight_story_html(
                analysis,
                selection,
                member_name=member.get("name", ""),
                show_exact_weight=args.show_exact_weight,
                show_member_name=args.show_member_name,
                show_exact_date=args.show_exact_date,
                context_lines=story_context,
            )
            _write_private(html_path, card_html)
        except (OSError, ValueError) as exc:
            return {"status": "error", "message": "体重译报生成失败：%s" % exc}

        card = {
            "product_name": STORY_PRODUCT_NAME,
            "style": selected_style,
            "style_name": selection["selected_style"]["name"],
            "format": args.format,
            "width": CARD_WIDTH,
            "height": CARD_HEIGHT,
            "html_path": html_path,
            "png_path": None,
            "render": {"status": "not_requested"},
            "share_safe": not (
                args.show_exact_weight or args.show_member_name or args.show_exact_date
            ),
        }
        if args.format in ("png", "both"):
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

        base_result["product_name"] = STORY_PRODUCT_NAME
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
    if args.format in ("png", "both"):
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
