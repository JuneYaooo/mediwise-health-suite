"""Build a shareable, multi-domain health-story video package.

The Signal Frame remains the source of truth.  This module only lays several
already-normalized stories out as independent poster images and joins those
images into a short MP4.  It never compares values across domains, fills missing
days with zero, or turns concurrent movement into a causal claim.

The public deliverables are deliberately boring to locate:

    public/health_story.mp4
    public/cover.png
    public/frames/*.png

HTML scene files, the storyboard and render diagnostics stay outside `public/`.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from .export import capture_poster_png, png_dimensions
from .render import _signed


FRAME_WIDTH = 1080
FRAME_HEIGHT = 1440
VIDEO_WIDTH = 1080
VIDEO_HEIGHT = 1920
FPS = 30
TRANSITION_SECONDS = 0.22
MOTION_STRATEGY = "scene_aware_ken_burns"

_PALETTE = (
    ("#246BCE", "#DCEBFF"),
    ("#0B7895", "#D8F1F5"),
    ("#8A5BCE", "#EEE4FF"),
    ("#C56645", "#F8E4DC"),
    ("#297B68", "#DDF1EB"),
    ("#A46B18", "#F7E9CA"),
)

_COPY = {
    "zh-CN": {
        "product": "MediWise 健康译报",
        "cover_eyebrow": "多维健康观察",
        "cover_title": "最近 {days} 天，记录留下了这些线索",
        "cover_body": "只连接已有记录，不补零，也不把同期变化写成原因。",
        "dimensions": "记录维度",
        "records": "合计记录",
        "window": "观察窗口",
        "day_unit": "天",
        "rate_day": "天",
        "record_unit": "次",
        "overview_eyebrow": "本期总览",
        "overview_title": "{count} 个维度，分别看清",
        "overview_body": "每一行都保留自己的单位和记录边界，不做跨域相减。",
        "recorded_days": "有记录日",
        "measurements": "记录次数",
        "long_run": "长期变化",
        "not_enough": "记录不足，暂不判断",
        "unfitted": "暂无稳健拟合",
        "stable": "记录数字方向接近水平",
        "up": "记录数字呈上行方向",
        "down": "记录数字呈下行方向",
        "conflict": "最近一次与长期方向不同",
        "rebuilding": "记录在间隔后重新接续",
        "spotlight": "这一组记录最为完整",
        "multi": "多组记录可同框观察",
        "domain_eyebrow": "维度观察 · {index}/{count}",
        "domain_title": "{subject}记录",
        "fit_method": "日内折叠 + Theil–Sen",
        "gap_note": "横轴按日历时间展开；空白区表示没有记录，不代表数值为零。",
        "boundary_eyebrow": "解读边界",
        "boundary_title": "看到线索，也保留边界",
        "boundary_body": "这份译报整理已记录事实，不替代医学判断。",
        "boundary_a": "同期不等于因果",
        "boundary_a_body": "几个维度在同一阶段变化，只能并列观察，不能写成原因。",
        "boundary_b": "未记录不等于零",
        "boundary_b_body": "没有数据的日期保持空白，不参与均值、趋势或结论。",
        "boundary_c": "不提供诊疗方案",
        "boundary_c_body": "不根据这些记录给出诊断、治疗、饮食、运动或用药建议。",
        "footer": "默认脱敏 · 本地生成",
    },
    "en-US": {
        "product": "MediWise Health Story",
        "cover_eyebrow": "MULTI-DOMAIN HEALTH OBSERVATION",
        "cover_title": "What the last {days} days of records show",
        "cover_body": "Only recorded facts are connected. Missing days are not zero, and concurrent change is not causation.",
        "dimensions": "Recorded domains",
        "records": "Total records",
        "window": "Window",
        "day_unit": "days",
        "rate_day": "day",
        "record_unit": "records",
        "overview_eyebrow": "PERIOD OVERVIEW",
        "overview_title": "{count} domains, kept separate",
        "overview_body": "Each row retains its own unit and recording boundary; values are never subtracted across domains.",
        "recorded_days": "Recorded days",
        "measurements": "Records",
        "long_run": "Long-run change",
        "not_enough": "Not enough records to infer a direction",
        "unfitted": "No robust fit available",
        "stable": "Recorded values are near level",
        "up": "Recorded values point upward",
        "down": "Recorded values point downward",
        "conflict": "Latest movement differs from the longer direction",
        "rebuilding": "Recording resumed after a gap",
        "spotlight": "This is the most complete recorded signal",
        "multi": "Several recorded signals can be viewed together",
        "domain_eyebrow": "DOMAIN {index}/{count}",
        "domain_title": "Recorded {subject}",
        "fit_method": "daily fold + Theil–Sen",
        "gap_note": "The horizontal axis follows calendar time. Blank space means no record, not zero.",
        "boundary_eyebrow": "INTERPRETATION BOUNDARY",
        "boundary_title": "Keep the clues and the limits together",
        "boundary_body": "This story organizes recorded facts and does not replace medical judgment.",
        "boundary_a": "Concurrent is not causal",
        "boundary_a_body": "Changes in the same period can be viewed side by side, but not described as causes.",
        "boundary_b": "Unrecorded is not zero",
        "boundary_b_body": "Dates without data remain blank and do not enter averages, trends, or conclusions.",
        "boundary_c": "No care plan is provided",
        "boundary_c_body": "The records are not used to prescribe diagnosis, treatment, diet, exercise, or medication changes.",
        "footer": "De-identified by default · Generated locally",
    },
}

_SHAPE_COPY = {
    "insufficient": "not_enough",
    "today-vs-trend-conflict": "conflict",
    "sustained-rise": "up",
    "sustained-fall": "down",
    "flat-with-noise": "stable",
    "stable": "stable",
    "rebuilding": "rebuilding",
    "spotlight": "spotlight",
    "multi-signal": "multi",
}


def _private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    _private(path)


def _write_json(path: Path, value: object) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _copy(locale: str) -> Mapping[str, str]:
    return _COPY.get(locale, _COPY["zh-CN"])


def _subject(story: Mapping[str, object], domain_labels: Mapping[str, str]) -> str:
    domain = str(story.get("domain") or "")
    if domain in domain_labels:
        return str(domain_labels[domain])
    lexicon = story.get("lexicon") or {}
    return str(lexicon.get("subject") or domain)


def _trend_state(story: Mapping[str, object], locale: str) -> tuple[str, str, bool]:
    """Return display value, explanatory copy, and whether a fit exists."""
    c = _copy(locale)
    frame = story.get("frame") or {}
    trend = frame.get("trend") or {}
    # `claim_allowed` is the shared minimum-record gate.  An adapter may still
    # return the stronger `insufficient` shape (for example, a source change or
    # a domain-specific confidence rule).  In that state the fitted number is an
    # internal calculation, not an earned public claim.
    if not trend.get("claim_allowed") or frame.get("shape") == "insufficient":
        return "—", c["not_enough"], False
    delta = trend.get("delta")
    if delta is None:
        return "—", c["unfitted"], False
    lexicon = story.get("lexicon") or {}
    unit = str(lexicon.get("unit") or "").strip()
    slope = trend.get("slope_per_day")
    if isinstance(slope, (int, float)) and not isinstance(slope, bool) and math.isfinite(float(slope)):
        display_number = slope
        suffix = (" %s/%s" % (unit, c["rate_day"])).strip()
    else:
        # Compatibility with an older/fake frame that has a window delta but no
        # daily slope: show the available total in its own unit.  Appending `/day`
        # here would relabel a whole-window change as a daily rate.
        display_number = delta
        suffix = (" %s" % unit).strip()
    shape_key = _SHAPE_COPY.get(str(frame.get("shape") or ""), "stable")
    return "%s%s" % (_signed(display_number), suffix), c[shape_key], True


def _coverage(story: Mapping[str, object]) -> tuple[int, int]:
    frame = story.get("frame") or {}
    coverage = frame.get("coverage") or {}
    return (
        int(coverage.get("recorded_days") or 0),
        int(coverage.get("measurement_count") or 0),
    )


def plan_story_scenes(
    stories: Sequence[Mapping[str, object]],
    *,
    days: int,
    locale: str = "zh-CN",
    domain_labels: Optional[Mapping[str, str]] = None,
) -> list[dict]:
    """Create the public storyboard from non-empty, normalized domain stories."""
    c = _copy(locale)
    labels = dict(domain_labels or {})
    usable = [story for story in stories if (story.get("frame") or {}).get("series")]
    if not usable:
        return []

    total_records = sum(_coverage(story)[1] for story in usable)
    subjects = [_subject(story, labels) for story in usable]
    scenes = [
        {
            "id": "00-cover",
            "role": "cover",
            "duration_ms": 3000,
            "eyebrow": c["cover_eyebrow"],
            "title": c["cover_title"].format(days=days),
            "body": c["cover_body"],
            "chips": subjects,
            "facts": [
                (str(len(usable)), c["dimensions"]),
                (str(total_records), c["records"]),
                ("%d %s" % (days, c["day_unit"]), c["window"]),
            ],
        },
        {
            "id": "01-overview",
            "role": "overview",
            "duration_ms": 3200,
            "eyebrow": c["overview_eyebrow"],
            "title": c["overview_title"].format(count=len(usable)),
            "body": c["overview_body"],
            "rows": [
                {
                    "subject": _subject(story, labels),
                    "recorded_days": _coverage(story)[0],
                    "measurement_count": _coverage(story)[1],
                    "trend_value": _trend_state(story, locale)[0],
                    "trend_copy": _trend_state(story, locale)[1],
                }
                for story in usable
            ],
        },
    ]
    for index, story in enumerate(usable, start=1):
        recorded_days, measurement_count = _coverage(story)
        trend_value, trend_copy, fitted = _trend_state(story, locale)
        frame = story.get("frame") or {}
        scenes.append(
            {
                "id": "%02d-%s" % (index + 1, story.get("domain") or "domain"),
                "role": "domain",
                "domain": story.get("domain"),
                "duration_ms": 3000,
                "eyebrow": c["domain_eyebrow"].format(index=index, count=len(usable)),
                "title": c["domain_title"].format(subject=_subject(story, labels)),
                "body": trend_copy,
                "facts": [
                    (str(recorded_days), c["recorded_days"]),
                    (str(measurement_count), c["measurements"]),
                    (trend_value, c["long_run"]),
                ],
                "series": [dict(point) for point in frame.get("series") or []],
                "fit_label": c["fit_method"] if fitted else trend_copy,
                "gap_note": c["gap_note"],
            }
        )
    scenes.append(
        {
            "id": "%02d-boundary" % (len(usable) + 2),
            "role": "boundary",
            "duration_ms": 3200,
            "eyebrow": c["boundary_eyebrow"],
            "title": c["boundary_title"],
            "body": c["boundary_body"],
            "boundaries": [
                (c["boundary_a"], c["boundary_a_body"]),
                (c["boundary_b"], c["boundary_b_body"]),
                (c["boundary_c"], c["boundary_c_body"]),
            ],
        }
    )
    return scenes


def _series_svg(series: Sequence[Mapping[str, object]], accent: str) -> str:
    parsed = []
    for point in series:
        try:
            date = datetime.fromisoformat(str(point.get("date"))[:10]).date()
            value = float(point.get("value"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            parsed.append((date, value))
    if not parsed:
        return '<div class="chart-empty">—</div>'
    parsed.sort(key=lambda item: item[0])
    first_date, last_date = parsed[0][0], parsed[-1][0]
    span = max((last_date - first_date).days, 1)
    values = [value for _, value in parsed]
    low, high = min(values), max(values)
    value_span = max(high - low, 1e-9)
    points = []
    for date, value in parsed:
        x = 55 + ((date - first_date).days / span) * 730
        y = 230 - ((value - low) / value_span) * 165 if high != low else 148
        points.append((x, y))
    polyline = " ".join("%.1f,%.1f" % point for point in points)
    circles = "".join(
        '<circle cx="%.1f" cy="%.1f" r="8" fill="white" stroke="%s" stroke-width="5"/>'
        % (x, y, accent)
        for x, y in points
    )
    return (
        '<svg class="chart" viewBox="0 0 840 280" aria-hidden="true">'
        '<path d="M55 242 H785" stroke="#DCE5EF" stroke-width="3"/>'
        '<polyline points="%s" fill="none" stroke="%s" stroke-width="7" '
        'stroke-linecap="round" stroke-linejoin="round"/>%s</svg>'
        % (polyline, accent, circles)
    )


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_scene_html(scene: Mapping[str, object], *, locale: str = "zh-CN", index: int = 0) -> str:
    """Render one deterministic 1080x1440 poster; no remote assets are loaded."""
    c = _copy(locale)
    accent, soft = _PALETTE[index % len(_PALETTE)]
    role = str(scene.get("role") or "domain")
    chips = "".join('<span class="chip">%s</span>' % _e(item) for item in scene.get("chips") or [])
    facts = "".join(
        '<div class="fact"><b>%s</b><span>%s</span></div>' % (_e(value), _e(label))
        for value, label in scene.get("facts") or []
    )
    rows = ""
    for row in scene.get("rows") or []:
        if locale == "zh-CN":
            coverage_text = "有记录日 %s 天 · 记录 %s 次" % (
                row["recorded_days"], row["measurement_count"]
            )
        else:
            coverage_text = "%s recorded days · %s records" % (
                row["recorded_days"], row["measurement_count"]
            )
        rows += (
            '<div class="overview-row"><div><b>%s</b><small>%s</small></div>'
            '<div class="row-trend"><b>%s</b><small>%s</small></div></div>'
            % (
                _e(row["subject"]), _e(coverage_text), _e(row["trend_value"]),
                _e(row["trend_copy"]),
            )
        )
    boundaries = "".join(
        '<div class="boundary"><i>%02d</i><div><b>%s</b><p>%s</p></div></div>'
        % (number, _e(title), _e(body))
        for number, (title, body) in enumerate(scene.get("boundaries") or [], start=1)
    )
    chart = _series_svg(scene.get("series") or [], accent) if role == "domain" else ""
    detail = ""
    if role == "domain":
        detail = (
            '<div class="chart-card">%s<div class="chart-meta"><span>%s</span><span>%s</span></div></div>'
            % (chart, _e(scene.get("fit_label") or ""), _e(scene.get("gap_note") or ""))
        )
    if role == "overview":
        content = '<div class="overview-list">%s</div>' % rows
    elif role == "boundary":
        content = '<div class="boundary-list">%s</div>' % boundaries
    else:
        content = '<div class="facts">%s</div>%s' % (facts, detail)
    return '''<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=1080,height=1440,initial-scale=1">
<style>
*{{box-sizing:border-box}} html,body{{margin:0;width:1080px;height:1440px;overflow:hidden}}
body{{--accent:{accent};--soft:{soft};font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Noto Sans CJK SC","Microsoft YaHei",Arial,sans-serif;color:#102A43;background:#F4F7FB}}
.page{{position:relative;width:1080px;height:1440px;padding:82px 84px 70px;background:radial-gradient(circle at 88% 5%,var(--soft),transparent 33%),linear-gradient(155deg,#F8FBFF 0%,#EEF4FA 100%)}}
.page:before{{content:"";position:absolute;left:0;top:0;width:18px;height:100%;background:var(--accent)}}
.brand{{display:flex;align-items:center;gap:16px;color:#49647B;font-size:24px;font-weight:700}} .mark{{display:grid;place-items:center;width:48px;height:48px;border-radius:15px;background:var(--accent);color:white;font-size:25px}}
.eyebrow{{margin-top:82px;color:var(--accent);font-weight:800;font-size:24px;letter-spacing:.08em;text-transform:uppercase}}
h1{{max-width:890px;margin:22px 0 0;font-size:66px;line-height:1.14;letter-spacing:-.035em;color:#102A43}} .lead{{max-width:880px;margin:26px 0 0;color:#526D82;font-size:29px;line-height:1.65}}
.chip-row{{display:flex;flex-wrap:wrap;gap:14px;margin-top:46px}} .chip{{padding:13px 21px;border:2px solid color-mix(in srgb,var(--accent) 36%,white);border-radius:999px;background:white;color:#294E6B;font-size:22px;font-weight:750}}
.content{{margin-top:56px}} .facts{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}} .fact{{min-height:166px;padding:27px 25px;border-radius:26px;background:rgba(255,255,255,.88);border:2px solid #D9E4EF;box-shadow:0 18px 45px rgba(22,59,92,.06)}} .fact b,.fact span{{display:block}} .fact b{{font-size:43px;color:#163A59;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}} .fact span{{margin-top:15px;color:#668096;font-size:21px}}
.overview-list{{display:grid;gap:14px}} .overview-row{{display:grid;grid-template-columns:1fr 1.18fr;align-items:center;gap:25px;padding:23px 27px;border:2px solid #DCE6EF;border-radius:22px;background:rgba(255,255,255,.9)}} .overview-row>div>b,.overview-row small{{display:block}} .overview-row>div>b{{font-size:29px}} .overview-row small{{margin-top:7px;color:#6A8194;font-size:18px;line-height:1.35}} .row-trend{{text-align:right}} .row-trend b{{font-size:25px;color:var(--accent);font-variant-numeric:tabular-nums}}
.chart-card{{margin-top:25px;padding:22px 30px 26px;border:2px solid #D9E4EF;border-radius:28px;background:white;box-shadow:0 20px 55px rgba(22,59,92,.07)}} .chart{{display:block;width:100%;height:270px}} .chart-empty{{display:grid;place-items:center;height:270px;color:#7890A4;font-size:44px}} .chart-meta{{display:grid;grid-template-columns:.7fr 1.3fr;gap:22px;padding-top:17px;border-top:2px solid #E5ECF3;color:#60798E;font-size:18px;line-height:1.45}} .chart-meta span:first-child{{font-weight:780;color:var(--accent)}}
.boundary-list{{display:grid;gap:20px}} .boundary{{display:grid;grid-template-columns:62px 1fr;gap:22px;padding:25px 27px;border:2px solid #DAE5EF;border-radius:24px;background:white}} .boundary i{{display:grid;place-items:center;width:54px;height:54px;border-radius:17px;background:var(--soft);color:var(--accent);font-style:normal;font-size:20px;font-weight:850}} .boundary b{{font-size:28px}} .boundary p{{margin:7px 0 0;color:#5C758A;font-size:21px;line-height:1.45}}
.footer{{position:absolute;left:84px;right:84px;bottom:48px;display:flex;justify-content:space-between;padding-top:20px;border-top:2px solid #DCE5ED;color:#6B8295;font-size:18px}} .footer b{{color:#34536D}}
.cover .eyebrow{{margin-top:135px}} .cover h1{{font-size:76px;max-width:900px}} .cover .content{{margin-top:70px}} .cover .facts{{margin-top:46px}}
.overview .eyebrow{{margin-top:54px}} .overview h1{{font-size:58px}} .overview .lead{{font-size:25px}} .overview .content{{margin-top:34px}}
.domain .eyebrow{{margin-top:50px}} .domain h1{{font-size:62px}} .domain .lead{{font-size:28px}} .domain .content{{margin-top:38px}}
.boundary-page .eyebrow{{margin-top:58px}} .boundary-page h1{{font-size:58px}} .boundary-page .lead{{font-size:26px}} .boundary-page .content{{margin-top:35px}}
</style></head><body><main class="page {role_class}"><div class="brand"><span class="mark">M</span><span>{product}</span></div><div class="eyebrow">{eyebrow}</div><h1>{title}</h1><p class="lead">{body}</p><div class="chip-row">{chips}</div><section class="content">{content}</section><footer class="footer"><b>MediWise Health Suite</b><span>{footer}</span></footer></main><script>document.fonts.ready.then(()=>{{window.__ready=true}});</script></body></html>'''.format(
        lang=_e(c.get("lang", locale)),
        accent=accent,
        soft=soft,
        role_class="boundary-page" if role == "boundary" else role,
        product=_e(c["product"]),
        eyebrow=_e(scene.get("eyebrow") or ""),
        title=_e(scene.get("title") or ""),
        body=_e(scene.get("body") or ""),
        chips=chips,
        content=content,
        footer=_e(c["footer"]),
    )


def viewer_facing_text(scenes: Sequence[Mapping[str, object]], locale: str = "zh-CN") -> str:
    """Extract only words a viewer can see, for copy lint and review."""
    c = _copy(locale)
    lines = [c["product"], "MediWise Health Suite", c["footer"]]
    for scene in scenes:
        lines.extend(str(scene.get(key) or "") for key in ("eyebrow", "title", "body"))
        lines.extend(str(item) for item in scene.get("chips") or [])
        for value, label in scene.get("facts") or []:
            lines.extend((str(value), str(label)))
        for row in scene.get("rows") or []:
            lines.extend(str(row.get(key) or "") for key in ("subject", "trend_value", "trend_copy"))
            if locale == "zh-CN":
                lines.append("有记录日 %s 天 · 记录 %s 次" % (
                    row.get("recorded_days"), row.get("measurement_count")
                ))
            else:
                lines.append("%s recorded days · %s records" % (
                    row.get("recorded_days"), row.get("measurement_count")
                ))
        for title, body in scene.get("boundaries") or []:
            lines.extend((str(title), str(body)))
        if scene.get("fit_label"):
            lines.append(str(scene["fit_label"]))
        if scene.get("gap_note"):
            lines.append(str(scene["gap_note"]))
    return "\n".join(line for line in lines if line) + "\n"


def _motion_filter(index: int, scene: Mapping[str, object], duration: float) -> str:
    """Give every poster a quiet camera move without changing its evidence.

    The independent PNG remains the canonical still.  Motion is applied only
    while assembling the MP4: cover and overview establish the canvas, domain
    cards alternate their drift so five consecutive analyses do not feel like a
    slideshow, and the boundary page eases back to a settled frame.  All moves
    are small enough to keep the complete card and footer inside the 9:16 frame.
    """
    frames = max(int(round(duration * FPS)), 2)
    last = frames - 1
    progress = "on/%d" % last
    role = str(scene.get("role") or "domain")
    if role == "cover":
        zoom = "1.000+0.034*(%s)" % progress
        x_anchor = "0.30+0.12*(%s)" % progress
        y_anchor = "0.58-0.10*(%s)" % progress
    elif role == "overview":
        zoom = "1.014+0.022*(%s)" % progress
        x_anchor = "0.68-0.28*(%s)" % progress
        y_anchor = "0.42+0.10*(%s)" % progress
    elif role == "boundary":
        zoom = "1.034-0.022*(%s)" % progress
        x_anchor = "0.46+0.06*(%s)" % progress
        y_anchor = "0.52-0.04*(%s)" % progress
    elif index % 2:
        zoom = "1.010+0.030*(%s)" % progress
        x_anchor = "0.70-0.34*(%s)" % progress
        y_anchor = "0.44+0.12*(%s)" % progress
    else:
        zoom = "1.010+0.030*(%s)" % progress
        x_anchor = "0.28+0.34*(%s)" % progress
        y_anchor = "0.56-0.12*(%s)" % progress
    return (
        "zoompan=z='%s':x='(iw-iw/zoom)*(%s)':y='(ih-ih/zoom)*(%s)'"
        ":d=1:s=%dx%d:fps=%d"
        % (zoom, x_anchor, y_anchor, VIDEO_WIDTH, VIDEO_HEIGHT, FPS)
    )


def _video_command(ffmpeg: str, frame_paths: Sequence[Path], scenes: Sequence[Mapping[str, object]], output: Path) -> tuple[list[str], float]:
    command = [ffmpeg, "-y"]
    durations = []
    for path, scene in zip(frame_paths, scenes):
        duration = max(float(scene.get("duration_ms") or 3000) / 1000.0, 0.8)
        durations.append(duration)
        command.extend(["-loop", "1", "-framerate", str(FPS), "-t", "%.3f" % duration, "-i", str(path)])
    filters = []
    for index, duration in enumerate(durations):
        fade_out = max(duration - TRANSITION_SECONDS, 0.0)
        chain = (
            "[%d:v]scale=1000:1333:force_original_aspect_ratio=decrease,"
            "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=0x0B1F35,"
            "setsar=1,%s,trim=duration=%.3f,setpts=PTS-STARTPTS"
            % (index, _motion_filter(index, scenes[index], duration), duration)
        )
        if index > 0:
            chain += ",fade=t=in:st=0:d=%.3f" % TRANSITION_SECONDS
        if index < len(frame_paths) - 1:
            chain += ",fade=t=out:st=%.3f:d=%.3f" % (
                fade_out, TRANSITION_SECONDS
            )
        filters.append(chain + ",format=yuv420p[v%d]" % index)
    if len(frame_paths) == 1:
        output_label = "v0"
        total = durations[0]
    else:
        output_label = "joined"
        filters.append(
            "%sconcat=n=%d:v=1:a=0[%s]"
            % ("".join("[v%d]" % index for index in range(len(frame_paths))), len(frame_paths), output_label)
        )
        total = sum(durations)
    command.extend(
        [
            "-filter_complex", ";".join(filters),
            "-map", "[%s]" % output_label,
            "-t", "%.3f" % total,
            "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
        ]
    )
    return command, total


def _probe_video(ffprobe: str, path: Path) -> dict:
    completed = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration,size:stream=index,codec_name,codec_type,width,height,pix_fmt,r_frame_rate", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or "ffprobe failed")[:500])
    return json.loads(completed.stdout)


def _contact_sheet(ffmpeg: str, frame_paths: Sequence[Path], output: Path) -> Optional[str]:
    scene_count = len(frame_paths)
    columns = min(4, max(1, scene_count))
    rows = int(math.ceil(scene_count / columns))
    completed = subprocess.run(
        [
            ffmpeg, "-y", "-pattern_type", "glob", "-framerate", "1",
            "-i", str(frame_paths[0].parent / "*.png"),
            "-vf", "scale=240:-1,tile=%dx%d:padding=8:margin=8:color=0x0B1F35" % (columns, rows),
            "-frames:v", "1", str(output),
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    if completed.returncode != 0 or not output.is_file():
        return (completed.stderr or "contact sheet unavailable")[:500]
    _private(output)
    return None


def _relative(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def render_health_story_video(
    stories: Sequence[Mapping[str, object]],
    output_dir: str,
    *,
    days: int,
    locale: str = "zh-CN",
    domain_labels: Optional[Mapping[str, str]] = None,
    chrome_binary: Optional[str] = None,
    ffmpeg_binary: Optional[str] = None,
    ffprobe_binary: Optional[str] = None,
    capture: Optional[Callable[..., dict]] = None,
) -> dict:
    """Render scene PNGs and a silent H.264 MP4, returning a manifest envelope.

    Missing Chrome or FFmpeg is an `unavailable` result, not an exception: the
    caller may still deliver its already-generated HTML/PNG/SVG report.
    """
    scenes = plan_story_scenes(
        stories, days=days, locale=locale, domain_labels=domain_labels
    )
    if not scenes:
        return {"status": "unavailable", "message": "没有可生成多维视频的有效记录"}

    root = Path(output_dir).resolve()
    public_dir = root / "public"
    frames_dir = public_dir / "frames"
    qa_dir = root / "qa"
    technical_dir = root / "technical"
    internal_dir = root / "internal"
    scene_html_dir = internal_dir / "scene_html"
    for directory in (frames_dir, qa_dir, technical_dir, scene_html_dir):
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
    # A report for the same member/date may be regenerated after new records
    # arrive.  Remove only files this renderer owns so a shorter new storyboard
    # cannot leave an obsolete shareable PNG beside the current manifest.
    for directory, pattern in (
        (frames_dir, "*.png"),
        (scene_html_dir, "*.html"),
    ):
        for stale in directory.glob(pattern):
            try:
                stale.unlink()
            except OSError:
                pass
    for stale in (
        public_dir / "health_story.mp4",
        public_dir / "cover.png",
        qa_dir / "contact_sheet.png",
    ):
        try:
            stale.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    _write_json(
        internal_dir / "storyboard.json",
        {
            "audio_strategy": "silent",
            "motion_strategy": MOTION_STRATEGY,
            "scenes": scenes,
        },
    )
    visible_text_path = qa_dir / "viewer_facing_text.txt"
    _write_text(visible_text_path, viewer_facing_text(scenes, locale))

    capture_fn = capture or capture_poster_png
    frame_paths = []
    capture_results = []
    for index, scene in enumerate(scenes):
        html_path = scene_html_dir / (scene["id"] + ".html")
        frame_path = frames_dir / (scene["id"] + ".png")
        _write_text(html_path, render_scene_html(scene, locale=locale, index=index))
        result = capture_fn(
            str(html_path), str(frame_path), width=FRAME_WIDTH, height=FRAME_HEIGHT,
            chrome_binary=chrome_binary, expect_exact_size=True,
        )
        capture_results.append({"scene": scene["id"], **result})
        if result.get("status") != "ok":
            _write_json(technical_dir / "render_manifest.json", {"status": "unavailable", "captures": capture_results})
            return {"status": "unavailable", "message": result.get("message") or "镜头 PNG 渲染失败", "package_dir": str(root)}
        frame_paths.append(frame_path)

    cover_path = public_dir / "cover.png"
    shutil.copyfile(frame_paths[0], cover_path)
    _private(cover_path)

    ffmpeg = ffmpeg_binary or shutil.which("ffmpeg")
    ffprobe = ffprobe_binary or shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        _write_json(technical_dir / "render_manifest.json", {"status": "unavailable", "captures": capture_results, "ffmpeg": bool(ffmpeg), "ffprobe": bool(ffprobe)})
        return {"status": "unavailable", "message": "未找到 FFmpeg/ffprobe；镜头 PNG 已生成", "package_dir": str(root), "scene_images": [str(path) for path in frame_paths]}

    video_path = public_dir / "health_story.mp4"
    command, expected_duration = _video_command(ffmpeg, frame_paths, scenes, video_path)
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if completed.returncode != 0 or not video_path.is_file():
        _write_json(technical_dir / "render_manifest.json", {"status": "failed", "captures": capture_results, "ffmpeg_error": (completed.stderr or "ffmpeg failed")[-1000:]})
        return {"status": "unavailable", "message": "MP4 编码失败", "package_dir": str(root), "scene_images": [str(path) for path in frame_paths]}
    _private(video_path)

    probe = _probe_video(ffprobe, video_path)
    _write_json(technical_dir / "ffprobe.json", probe)
    video_stream = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"), {})
    actual_duration = float((probe.get("format") or {}).get("duration") or 0.0)
    qa_checks = {
        "video_readable": bool(video_stream),
        "dimensions": [video_stream.get("width"), video_stream.get("height")],
        "dimensions_match": (video_stream.get("width"), video_stream.get("height")) == (VIDEO_WIDTH, VIDEO_HEIGHT),
        "codec": video_stream.get("codec_name"),
        "pixel_format": video_stream.get("pix_fmt"),
        "duration_seconds": actual_duration,
        "duration_matches_plan": abs(actual_duration - expected_duration) <= 0.2,
        "audio_strategy": "silent",
        "scene_png_count": len(frame_paths),
        "all_scene_pngs_1080x1440": all(png_dimensions(str(path)) == (FRAME_WIDTH, FRAME_HEIGHT) for path in frame_paths),
    }
    qa_status = "pass" if all(
        qa_checks[key]
        for key in ("video_readable", "dimensions_match", "duration_matches_plan", "all_scene_pngs_1080x1440")
    ) else "fail"
    _write_json(qa_dir / "video_qa.json", {"status": qa_status, "checks": qa_checks})
    contact_sheet_path = qa_dir / "contact_sheet.png"
    contact_sheet_warning = _contact_sheet(ffmpeg, frame_paths, contact_sheet_path)

    render_manifest = {
        "status": "ok",
        "frame_size": [FRAME_WIDTH, FRAME_HEIGHT],
        "video_size": [VIDEO_WIDTH, VIDEO_HEIGHT],
        "fps": FPS,
        "transition_seconds": TRANSITION_SECONDS,
        "audio_strategy": "silent",
        "motion_strategy": MOTION_STRATEGY,
        "captures": capture_results,
        "contact_sheet_warning": contact_sheet_warning,
    }
    _write_json(technical_dir / "render_manifest.json", render_manifest)

    artifacts = [
        {"path": _relative(video_path, root), "category": "final_video", "title": "Health story MP4"},
        {"path": _relative(cover_path, root), "category": "cover", "title": "Cover"},
        {"path": _relative(visible_text_path, root), "category": "copywriting", "title": "Viewer-facing text"},
    ]
    artifacts.extend(
        {"path": _relative(path, root), "category": "storyboard_image", "title": scenes[index]["title"]}
        for index, path in enumerate(frame_paths)
    )
    artifact_manifest_path = root / "artifact_manifest.json"
    _write_json(artifact_manifest_path, {"artifacts": artifacts})

    release_manifest_path = root / "release_manifest.json"
    domains = [str(story.get("domain")) for story in stories if (story.get("frame") or {}).get("series")]
    release_manifest = {
        "status": qa_status,
        "final_video": _relative(video_path, root),
        "cover": _relative(cover_path, root),
        "scene_images": [_relative(path, root) for path in frame_paths],
        "viewer_facing_text": _relative(visible_text_path, root),
        "qa_report": "qa/video_qa.json",
        "contact_sheet": "qa/contact_sheet.png" if contact_sheet_path.is_file() else None,
        "render_manifest": "technical/render_manifest.json",
        "ffprobe": "technical/ffprobe.json",
        "audio_strategy": "silent",
        "motion_strategy": MOTION_STRATEGY,
        "domains": domains,
        "share_safe": True,
    }
    _write_json(release_manifest_path, release_manifest)
    digest = hashlib.sha256(video_path.read_bytes()).hexdigest()
    return {
        "status": "ok" if qa_status == "pass" else "failed_qa",
        "mp4_path": str(video_path),
        "package_dir": str(root),
        "manifest_path": str(release_manifest_path),
        "artifact_manifest_path": str(artifact_manifest_path),
        "duration_ms": round(actual_duration * 1000),
        "width": VIDEO_WIDTH,
        "height": VIDEO_HEIGHT,
        "codec": video_stream.get("codec_name"),
        "audio_strategy": "silent",
        "motion_strategy": MOTION_STRATEGY,
        "share_safe": True,
        "domains": domains,
        "scene_images": [
            {"index": index, "role": scenes[index]["role"], "domain": scenes[index].get("domain"), "png_path": str(path)}
            for index, path in enumerate(frame_paths)
        ],
        "qa_path": str(qa_dir / "video_qa.json"),
        "contact_sheet_path": str(contact_sheet_path) if contact_sheet_path.is_file() else None,
        "sha256": digest,
    }


__all__ = (
    "FRAME_HEIGHT",
    "FRAME_WIDTH",
    "MOTION_STRATEGY",
    "VIDEO_HEIGHT",
    "VIDEO_WIDTH",
    "plan_story_scenes",
    "render_health_story_video",
    "render_scene_html",
    "viewer_facing_text",
)
