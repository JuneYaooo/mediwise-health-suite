"""Generate a self-contained HTML recent-health card.

Renders briefing data, recent metric trends, and reminders into a single
HTML file with inline CSS and SVG sparklines. No remote chart assets are used.

Usage:
  python3 scripts/briefing_report.py generate [--member-id <id>]
"""

from __future__ import annotations

import os
import sys
import json
from datetime import datetime, timedelta
from string import Template

import health_db
import health_advisor
from config import DATA_DIR


# --- Metric display names ---

METRIC_DISPLAY = {
    "blood_pressure": "血压",
    "blood_sugar": "血糖",
    "heart_rate": "心率",
    "weight": "体重",
    "temperature": "体温",
    "blood_oxygen": "血氧",
}

METRIC_UNITS = {
    "blood_pressure": "mmHg",
    "blood_sugar": "mmol/L",
    "heart_rate": "bpm",
    "weight": "kg",
    "temperature": "°C",
    "blood_oxygen": "%",
}

SOURCE_DISPLAY = {
    "manual": "手动记录",
    "apple_health": "Apple Health",
    "gadgetbridge": "Gadgetbridge",
    "garmin": "Garmin Connect",
}

# Severity styles
SEVERITY_COLORS = {
    "alert": {"bg": "#FEE2E2", "border": "#EF4444", "text": "#991B1B", "icon": "&#x1F6A8;"},
    "warning": {"bg": "#FEF3C7", "border": "#F59E0B", "text": "#92400E", "icon": "&#x26A0;&#xFE0F;"},
    "info": {"bg": "#DBEAFE", "border": "#3B82F6", "text": "#1E40AF", "icon": "&#x2139;&#xFE0F;"},
}


def _query_metric_trends(member_id: str, days: int = 30) -> dict:
    """Query the last N days of key metrics for a member.

    Returns dict keyed by metric_type, each containing a list of
    {date, value/systolic/diastolic} dicts ordered chronologically.
    """
    conn = health_db.get_connection()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    trends = {}
    try:
        for metric_type in ("blood_pressure", "blood_sugar", "heart_rate", "weight", "blood_oxygen"):
            rows = conn.execute(
                """SELECT measured_at, value, source FROM health_metrics
                   WHERE member_id=? AND metric_type=? AND is_deleted=0
                   AND measured_at >= ?
                   ORDER BY measured_at""",
                (member_id, metric_type, cutoff),
            ).fetchall()
            if not rows:
                continue
            points = []
            for row in rows:
                date_str = row["measured_at"][:10]
                try:
                    parsed = json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                except (json.JSONDecodeError, TypeError):
                    try:
                        parsed = {"value": float(row["value"])}
                    except (TypeError, ValueError):
                        continue
                if isinstance(parsed, dict):
                    point = {"date": date_str, "source": row["source"] or "手动记录"}
                    point.update(parsed)
                    points.append(point)
                else:
                    try:
                        points.append({"date": date_str, "value": float(parsed), "source": row["source"] or "手动记录"})
                    except (TypeError, ValueError):
                        continue
            if points:
                trends[metric_type] = points
        return trends
    finally:
        conn.close()


def _query_active_medications(member_id: str) -> list[dict]:
    """Get active medications for a member."""
    conn = health_db.get_connection()
    try:
        rows = health_db.rows_to_list(conn.execute(
            """SELECT name, dosage, frequency, start_date, purpose
               FROM medications
               WHERE member_id=? AND is_deleted=0 AND end_date IS NULL
               ORDER BY start_date""",
            (member_id,),
        ).fetchall())
        return rows
    finally:
        conn.close()


def _escape(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _source_display(source: str | None) -> str:
    if not source:
        return "手动记录"
    return SOURCE_DISPLAY.get(source, source.replace("_", " "))


def _build_alert_cards_html(briefing: dict) -> str:
    """Build the alert/warning/info summary cards."""
    total_alerts = briefing.get("total_alerts", 0)
    total_warnings = briefing.get("total_warnings", 0)
    total_reminders = briefing.get("total_due_reminders", 0)

    cards = []
    if total_alerts > 0:
        s = SEVERITY_COLORS["alert"]
        cards.append(
            f'<div class="summary-card" style="background:{s["bg"]};border-left:4px solid {s["border"]}">'
            f'<div class="card-icon">{s["icon"]}</div>'
            f'<div class="card-body"><div class="card-count" style="color:{s["text"]}">{total_alerts}</div>'
            f'<div class="card-label">项警告</div></div></div>'
        )
    if total_warnings > 0:
        s = SEVERITY_COLORS["warning"]
        cards.append(
            f'<div class="summary-card" style="background:{s["bg"]};border-left:4px solid {s["border"]}">'
            f'<div class="card-icon">{s["icon"]}</div>'
            f'<div class="card-body"><div class="card-count" style="color:{s["text"]}">{total_warnings}</div>'
            f'<div class="card-label">项提醒</div></div></div>'
        )
    if total_reminders > 0:
        s = SEVERITY_COLORS["info"]
        cards.append(
            f'<div class="summary-card" style="background:{s["bg"]};border-left:4px solid {s["border"]}">'
            f'<div class="card-icon">&#x1F48A;</div>'
            f'<div class="card-body"><div class="card-count" style="color:{s["text"]}">{total_reminders}</div>'
            f'<div class="card-label">项待处理提醒</div></div></div>'
        )

    if not cards:
        cards.append(
            '<div class="summary-card" style="background:#D1FAE5;border-left:4px solid #10B981">'
            '<div class="card-icon">&#x2705;</div>'
            '<div class="card-body"><div class="card-label" style="color:#065F46;font-size:16px">'
            '未发现告警或待办提醒</div></div></div>'
        )

    return '<div class="summary-cards">' + "\n".join(cards) + "</div>"


def _metric_number(point: dict, metric_type: str):
    if metric_type == "blood_pressure":
        return point.get("systolic")
    if metric_type == "blood_sugar" and point.get("fasting") is not None:
        return point.get("fasting")
    return point.get("value")


def _sparkline_svg(metric_type: str, points: list[dict]) -> str:
    """Build an inline SVG sparkline without external JavaScript."""
    width, height, pad = 250, 62, 6

    def line(values, color):
        valid = [(idx, float(value)) for idx, value in enumerate(values) if value is not None]
        if not valid:
            return ""
        all_values = [value for _, value in valid]
        low, high = min(all_values), max(all_values)
        span = high - low or 1.0
        count = max(len(values) - 1, 1)
        coords = []
        for idx, value in valid:
            x = pad + (width - 2 * pad) * idx / count
            y = pad + (height - 2 * pad) * (high - value) / span
            coords.append(f"{x:.1f},{y:.1f}")
        dots = "".join(
            f'<circle cx="{coord.split(",")[0]}" cy="{coord.split(",")[1]}" r="2.5" fill="{color}"/>'
            for coord in coords
        )
        return f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>{dots}'

    if metric_type == "blood_pressure":
        paths = line([p.get("systolic") for p in points], "#D76A4A")
        paths += line([p.get("diastolic") for p in points], "#2F6FEB")
    else:
        paths = line([_metric_number(p, metric_type) for p in points], "#1E7A6E")
    return (
        f'<svg class="sparkline" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="{_escape(METRIC_DISPLAY.get(metric_type, metric_type))}趋势">'
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#DDE8E5"/>'
        f'{paths}</svg>'
    )


def _build_metric_cards_html(trends: dict, days: int) -> str:
    cards = []
    for metric_type, points in trends.items():
        if not points:
            continue
        latest = points[-1]
        first = points[0]
        if metric_type == "blood_pressure":
            latest_value = f'{latest.get("systolic", "-")}/{latest.get("diastolic", "-")}'
            first_value = first.get("systolic")
            last_number = latest.get("systolic")
        else:
            last_number = _metric_number(latest, metric_type)
            first_value = _metric_number(first, metric_type)
            latest_value = "-" if last_number is None else f"{float(last_number):g}"

        delta_text = "记录不足，暂不判断趋势"
        if first_value is not None and last_number is not None and len(points) > 1:
            delta = float(last_number) - float(first_value)
            if abs(delta) < 1e-9:
                delta_text = "与期初持平"
            else:
                delta_text = f'较期初 {"+" if delta > 0 else ""}{delta:g}'

        cards.append(
            '<div class="metric-card">'
            '<div class="metric-card-head">'
            f'<span class="metric-name">{_escape(METRIC_DISPLAY.get(metric_type, metric_type))}</span>'
            f'<span class="metric-count">{len(points)} 条</span>'
            '</div>'
            f'<div class="metric-value">{_escape(latest_value)} <small>{_escape(METRIC_UNITS.get(metric_type, ""))}</small></div>'
            f'<div class="metric-delta">{_escape(delta_text)}</div>'
            f'{_sparkline_svg(metric_type, points)}'
            '<div class="metric-meta">'
            f'<span>最近：{_escape(latest.get("date", ""))}</span>'
            f'<span>来源：{_escape(_source_display(latest.get("source")))}</span>'
            '</div></div>'
        )
    if not cards:
        return '<div class="empty-state">最近还没有可展示的健康指标。先记录一项血压、心率、血糖、体重或血氧吧。</div>'
    return f'<div class="metric-grid" data-days="{days}">' + "".join(cards) + "</div>"


def _build_member_section(member_data: dict, trends: dict, medications: list[dict], days: int) -> str:
    """Build HTML for a single member's section."""
    name = _escape(member_data.get("member_name", ""))
    relation = _escape(member_data.get("relation", ""))
    parts = [f'<div class="member-section"><h2>&#x1F464; {name}（{relation}）</h2>']

    # Due reminders
    due = member_data.get("due_reminders", [])
    if due:
        parts.append('<div class="subsection"><h3>&#x23F0; 待处理提醒</h3><ul class="reminder-list">')
        for r in due:
            title = _escape(r.get("title", ""))
            content = _escape(r.get("content", ""))
            priority = r.get("priority", "normal")
            badge_class = f"badge-{priority}"
            parts.append(
                f'<li><span class="badge {badge_class}">{_escape(priority)}</span> '
                f'{title}'
                + (f' <span class="detail">— {content}</span>' if content else "")
                + "</li>"
            )
        parts.append("</ul></div>")

    # Health tips
    tips = member_data.get("health_tips", [])
    if tips:
        parts.append('<div class="subsection"><h3>&#x1F4CB; 健康建议</h3>')
        for tip in tips:
            severity = tip.get("severity", "info")
            s = SEVERITY_COLORS.get(severity, SEVERITY_COLORS["info"])
            title = _escape(tip.get("title", ""))
            detail = _escape(tip.get("detail", ""))
            suggestion = _escape(tip.get("suggestion", ""))
            parts.append(
                f'<div class="tip-card" style="background:{s["bg"]};border-left:4px solid {s["border"]}">'
                f'<div class="tip-header" style="color:{s["text"]}">{s["icon"]} {title}</div>'
                f'<div class="tip-detail">{detail}</div>'
                f'<div class="tip-suggestion">{suggestion}</div>'
                f"</div>"
            )
        parts.append("</div>")

    # Recent metric cards with self-contained SVG trends
    parts.append(
        f'<div class="subsection"><h3>&#x1F4C8; 最近 {days} 天健康记录</h3>'
        f'{_build_metric_cards_html(trends, days)}</div>'
    )

    # Active medications
    if medications:
        parts.append('<div class="subsection"><h3>&#x1F48A; 在用药物</h3>'
                      '<table class="med-table"><thead><tr>'
                      '<th>药品名称</th><th>剂量</th><th>频次</th><th>用途</th><th>开始日期</th>'
                      '</tr></thead><tbody>')
        for med in medications:
            parts.append(
                f'<tr><td>{_escape(med.get("name", ""))}</td>'
                f'<td>{_escape(med.get("dosage", ""))}</td>'
                f'<td>{_escape(med.get("frequency", ""))}</td>'
                f'<td>{_escape(med.get("purpose", ""))}</td>'
                f'<td>{_escape(med.get("start_date", "")[:10] if med.get("start_date") else "")}</td></tr>'
            )
        parts.append("</tbody></table></div>")

    parts.append("</div>")

    return "\n".join(parts)


def generate_report(member_id: str = None, owner_id: str = None, days: int = 7) -> dict:
    """Generate a self-contained HTML health briefing report.

    Args:
        member_id: Optional member ID. If None, generates for all members.

    Returns:
        dict with status, report_path, and file_size.
    """
    health_db.ensure_db()

    # 1. Get daily briefing data
    briefing = health_advisor.get_daily_briefing(member_id, owner_id)
    report_date = briefing.get("date", datetime.now().strftime("%Y-%m-%d"))

    # 2. Get member list for trend queries
    conn = health_db.get_connection()
    try:
        if member_id:
            if not health_db.verify_member_ownership(conn, member_id, owner_id):
                return {"status": "error", "message": f"无权访问成员: {member_id}"}
            members = health_db.rows_to_list(conn.execute(
                "SELECT id, name, relation FROM members WHERE id=? AND is_deleted=0",
                (member_id,),
            ).fetchall())
        elif owner_id:
            members = health_db.rows_to_list(conn.execute(
                "SELECT id, name, relation FROM members WHERE is_deleted=0 AND owner_id=? ORDER BY created_at",
                (owner_id,),
            ).fetchall())
        else:
            members = health_db.rows_to_list(conn.execute(
                "SELECT id, name, relation FROM members WHERE is_deleted=0 ORDER BY created_at",
            ).fetchall())
    finally:
        conn.close()

    member_count = len(members)

    # 3. Build briefing-to-member lookup
    briefing_lookup = {}
    for b in briefing.get("briefing", []):
        briefing_lookup[b.get("member_id")] = b

    # 4. Build member sections
    member_sections = []
    for m in members:
        mid = m["id"]
        # Get or create member briefing data
        member_data = briefing_lookup.get(mid, {
            "member_id": mid,
            "member_name": m["name"],
            "relation": m["relation"],
            "due_reminders": [],
            "health_tips": [],
        })
        if "member_name" not in member_data:
            member_data["member_name"] = m["name"]
        if "relation" not in member_data:
            member_data["relation"] = m["relation"]

        trends = _query_metric_trends(mid, days=days)
        medications = _query_active_medications(mid)

        member_sections.append(_build_member_section(member_data, trends, medications, days))

    # 5. Assemble HTML
    alert_cards_html = _build_alert_cards_html(briefing)
    members_html = "\n".join(member_sections)
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    period_start = (datetime.now() - timedelta(days=max(days - 1, 0))).strftime("%Y-%m-%d")
    period_label = f"{period_start} 至 {report_date}"

    html = _HTML_TEMPLATE.safe_substitute(
        report_date=_escape(report_date),
        period_label=_escape(period_label),
        days=days,
        member_count=member_count,
        alert_cards=alert_cards_html,
        members_content=members_html,
        gen_time=_escape(gen_time),
    )

    # 6. Write to file
    reports_dir = os.path.join(DATA_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)

    filename = f"briefing_{report_date}"
    if member_id:
        filename += f"_{member_id}"
    filename += ".html"
    report_path = os.path.join(reports_dir, filename)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)

    # 7. Persist daily health snapshot for each member (memory)
    try:
        import daily_snapshot
        for m in members:
            daily_snapshot.save_snapshot(m["id"], owner_id, briefing)
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("daily_snapshot save failed: %s", e)

    file_size = os.path.getsize(report_path)
    return {
        "status": "ok",
        "report_path": report_path,
        "file_size": file_size,
        "date": report_date,
        "member_count": member_count,
        "days": days,
    }


# --- HTML Template ---

_HTML_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>健康记录卡片 - $report_date</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei",
                 "Helvetica Neue", Helvetica, Arial, sans-serif;
    background: #F4F8F7;
    color: #173B35;
    line-height: 1.6;
}
.container { max-width: 960px; margin: 0 auto; padding: 24px; }
/* Header */
.header {
    background: linear-gradient(135deg, #153F38, #1E6A5E);
    color: white;
    padding: 30px 32px;
    border-radius: 20px;
    margin-bottom: 24px;
    box-shadow: 0 14px 34px rgba(21,63,56,0.16);
    position: relative;
    overflow: hidden;
}
.header::after { content: ""; position: absolute; width: 180px; height: 180px; border-radius: 50%; right: -45px; top: -80px; background: rgba(151,201,190,0.18); }
.header-top { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.brand-mark { width: 38px; height: 38px; border-radius: 12px; display: grid; place-items: center; background: #E4F1EE; color: #1E7A6E; font-size: 21px; font-weight: 800; }
.header h1 { font-size: 25px; font-weight: 760; letter-spacing: -0.3px; }
.header .subtitle { font-size: 14px; color: #C9E2DC; }
.privacy-pill { display: inline-flex; align-items: center; margin-top: 14px; padding: 5px 10px; border: 1px solid rgba(255,255,255,0.2); border-radius: 999px; font-size: 12px; color: #DCEBE8; }
/* Summary cards */
.summary-cards {
    display: flex;
    gap: 16px;
    margin-bottom: 24px;
    flex-wrap: wrap;
}
.summary-card {
    flex: 1;
    min-width: 180px;
    padding: 16px 20px;
    border-radius: 14px;
    display: flex;
    align-items: center;
    gap: 12px;
    box-shadow: 0 8px 24px rgba(21,63,56,0.06);
}
.card-icon { font-size: 28px; }
.card-count { font-size: 28px; font-weight: 700; }
.card-label { font-size: 13px; color: #6B7280; }
/* Member section */
.member-section {
    background: white;
    border-radius: 20px;
    padding: 26px;
    margin-bottom: 20px;
    box-shadow: 0 10px 30px rgba(21,63,56,0.07);
    border: 1px solid #E1EBE8;
}
.member-section h2 {
    font-size: 19px;
    color: #173F38;
    border-bottom: 2px solid #DDEEEA;
    padding-bottom: 10px;
    margin-bottom: 16px;
}
.subsection { margin-bottom: 20px; }
.subsection h3 {
    font-size: 15px;
    color: #45645E;
    margin-bottom: 12px;
}
/* Reminders */
.reminder-list { list-style: none; }
.reminder-list li {
    padding: 8px 12px;
    background: #F9FAFB;
    border-radius: 6px;
    margin-bottom: 6px;
    font-size: 14px;
}
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    margin-right: 6px;
}
.badge-urgent { background: #FEE2E2; color: #991B1B; }
.badge-high { background: #FEF3C7; color: #92400E; }
.badge-normal { background: #DDEEEA; color: #17665C; }
.badge-low { background: #E5E7EB; color: #6B7280; }
.detail { color: #6B7280; font-size: 13px; }
/* Tips */
.tip-card {
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 8px;
}
.tip-header { font-weight: 600; font-size: 14px; margin-bottom: 4px; }
.tip-detail { font-size: 13px; color: #4B5563; margin-bottom: 2px; }
.tip-suggestion { font-size: 13px; color: #6B7280; font-style: italic; }
/* Metric cards */
.metric-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
    gap: 14px;
}
.metric-card { background: #F8FBFA; border: 1px solid #DDE8E5; border-radius: 16px; padding: 16px; min-height: 194px; }
.metric-card-head { display: flex; justify-content: space-between; align-items: center; }
.metric-name { font-size: 14px; font-weight: 700; color: #31564F; }
.metric-count { font-size: 11px; padding: 3px 8px; border-radius: 999px; color: #2F6FEB; background: #E8F0FA; }
.metric-value { margin-top: 8px; font-size: 28px; line-height: 1.2; font-weight: 760; color: #153F38; }
.metric-value small { font-size: 12px; font-weight: 600; color: #718580; }
.metric-delta { margin-top: 4px; color: #6A7F79; font-size: 12px; }
.sparkline { width: 100%; height: 62px; display: block; margin: 8px 0 5px; }
.metric-meta { display: flex; justify-content: space-between; gap: 8px; color: #80918D; font-size: 10px; }
.empty-state { padding: 22px; text-align: center; border: 1px dashed #B9CEC8; border-radius: 14px; background: #F8FBFA; color: #6A7F79; font-size: 13px; }
/* Medication table */
.med-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}
.med-table th {
    background: #EDF4F2;
    color: #31564F;
    padding: 8px 12px;
    text-align: left;
    font-weight: 600;
    border-bottom: 2px solid #E5E7EB;
}
.med-table td {
    padding: 8px 12px;
    border-bottom: 1px solid #F3F4F6;
}
.med-table tr:hover td { background: #F4F8F7; }
/* Footer */
.footer {
    text-align: center;
    padding: 20px;
    color: #718580;
    font-size: 12px;
    border-top: 1px solid #DDE8E5;
    margin-top: 24px;
}
.footer .disclaimer {
    color: #9AA9A5;
    margin-top: 4px;
}
/* Print */
@media print {
    body { background: white; }
    .container { max-width: 100%; }
    .member-section, .header { box-shadow: none; break-inside: avoid; }
}
/* Mobile */
@media (max-width: 640px) {
    .container { padding: 12px; }
    .header { padding: 20px; }
    .header h1 { font-size: 20px; }
    .summary-cards { flex-direction: column; }
    .metric-grid { grid-template-columns: 1fr; }
    .metric-meta { flex-direction: column; }
}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <div class="header-top"><div class="brand-mark">M</div><h1>健康记录卡片</h1></div>
        <div class="subtitle">$period_label &middot; 最近 $days 天 &middot; 展示 $member_count 位成员</div>
        <div class="privacy-pill">&#x1F512;&nbsp; 个人本地档案 · MediWise</div>
    </div>

    $alert_cards

    $members_content

    <div class="footer">
        <div>报告生成时间：$gen_time</div>
        <div>MediWise Health Suite</div>
        <div class="disclaimer">本报告仅供参考，不构成医疗建议。如有健康问题请咨询专业医生。</div>
    </div>
</div>

</body>
</html>
""")


# --- CLI ---

def main():
    if len(sys.argv) < 2:
        health_db.output_json({"error": "用法: briefing_report.py generate [--member-id <id>]"})
        return

    cmd = sys.argv[1]

    if cmd == "generate":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id")
        p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
        p.add_argument("--days", type=int, default=7)
        args = p.parse_args(sys.argv[2:])
        result = generate_report(args.member_id, args.owner_id, max(1, min(args.days, 365)))
        health_db.output_json(result)
    elif cmd == "screenshot":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id")
        p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
        p.add_argument("--width", type=int, default=960)
        p.add_argument("--days", type=int, default=7)
        args = p.parse_args(sys.argv[2:])
        # Generate HTML first
        report = generate_report(args.member_id, args.owner_id, max(1, min(args.days, 365)))
        if report.get("status") != "ok":
            health_db.output_json(report)
            return
        # Convert to PNG
        import html_screenshot
        png_result = html_screenshot.screenshot(
            report["report_path"], width=args.width
        )
        png_result["html_path"] = report["report_path"]
        health_db.output_json(png_result)
    else:
        health_db.output_json({"error": f"未知命令: {cmd}", "commands": ["generate", "screenshot"]})


if __name__ == "__main__":
    main()
