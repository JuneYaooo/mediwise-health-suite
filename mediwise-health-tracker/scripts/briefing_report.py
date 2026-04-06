"""Generate a self-contained HTML health briefing report.

Renders daily briefing data, 30-day metric trends, and reminders into
a single HTML file with inline CSS and Chart.js visualizations.

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
    "temperature": "C",
    "blood_oxygen": "%",
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
        for metric_type in ("blood_pressure", "blood_sugar", "heart_rate"):
            rows = conn.execute(
                """SELECT measured_at, value FROM health_metrics
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
                    point = {"date": date_str}
                    point.update(parsed)
                    points.append(point)
                else:
                    try:
                        points.append({"date": date_str, "value": float(parsed)})
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
            '一切正常，无待处理事项</div></div></div>'
        )

    return '<div class="summary-cards">' + "\n".join(cards) + "</div>"


def _build_chart_js(chart_id: str, metric_type: str, points: list[dict]) -> str:
    """Build a Chart.js line chart script block for a metric."""
    labels = json.dumps([p["date"] for p in points], ensure_ascii=False).replace("</", "<\\/")
    display_name = METRIC_DISPLAY.get(metric_type, metric_type)
    unit = METRIC_UNITS.get(metric_type, "")

    if metric_type == "blood_pressure":
        sys_data = json.dumps([p.get("systolic") for p in points]).replace("</", "<\\/")
        dia_data = json.dumps([p.get("diastolic") for p in points]).replace("</", "<\\/")
        datasets = f"""[
            {{
                label: '收缩压 ({unit})',
                data: {sys_data},
                borderColor: '#EF4444',
                backgroundColor: 'rgba(239,68,68,0.1)',
                tension: 0.3,
                fill: false,
                pointRadius: 3,
            }},
            {{
                label: '舒张压 ({unit})',
                data: {dia_data},
                borderColor: '#3B82F6',
                backgroundColor: 'rgba(59,130,246,0.1)',
                tension: 0.3,
                fill: false,
                pointRadius: 3,
            }}
        ]"""
    else:
        key = "value"
        if metric_type == "blood_sugar":
            # Try fasting first, then value
            if points and "fasting" in points[0]:
                key = "fasting"
        data = json.dumps([p.get(key) for p in points]).replace("</", "<\\/")
        datasets = f"""[{{
            label: '{display_name} ({unit})',
            data: {data},
            borderColor: '#3B82F6',
            backgroundColor: 'rgba(59,130,246,0.1)',
            tension: 0.3,
            fill: true,
            pointRadius: 3,
        }}]"""

    return f"""
<script>
new Chart(document.getElementById('{chart_id}'), {{
    type: 'line',
    data: {{
        labels: {labels},
        datasets: {datasets}
    }},
    options: {{
        responsive: true,
        maintainAspectRatio: false,
        plugins: {{
            legend: {{ position: 'top', labels: {{ font: {{ size: 12 }} }} }},
            title: {{ display: true, text: '{display_name}趋势（近30天）', font: {{ size: 14 }} }}
        }},
        scales: {{
            x: {{ ticks: {{ maxRotation: 45, font: {{ size: 10 }} }} }},
            y: {{ beginAtZero: false }}
        }}
    }}
}});
</script>
"""


def _build_member_section(member_data: dict, trends: dict, medications: list[dict], chart_idx: int) -> tuple[str, str]:
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

    # Metric trend charts
    if trends:
        parts.append('<div class="subsection"><h3>&#x1F4C8; 指标趋势（近30天）</h3><div class="charts-grid">')
        for i, (metric_type, points) in enumerate(trends.items()):
            chart_id = f"chart_{chart_idx}_{i}"
            parts.append(
                f'<div class="chart-container">'
                f'<canvas id="{chart_id}"></canvas>'
                f"</div>"
            )
            # Chart script will be appended at the end
        parts.append("</div></div>")

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

    # Generate chart scripts (placed after the member section so canvas elements exist)
    chart_scripts = []
    if trends:
        for i, (metric_type, points) in enumerate(trends.items()):
            chart_id = f"chart_{chart_idx}_{i}"
            chart_scripts.append(_build_chart_js(chart_id, metric_type, points))

    return "\n".join(parts), "\n".join(chart_scripts)


def generate_report(member_id: str = None, owner_id: str = None) -> dict:
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
    chart_scripts = []

    for idx, m in enumerate(members):
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

        trends = _query_metric_trends(mid)
        medications = _query_active_medications(mid)

        section_html, section_charts = _build_member_section(member_data, trends, medications, idx)
        member_sections.append(section_html)
        if section_charts:
            chart_scripts.append(section_charts)

    # 5. Assemble HTML
    alert_cards_html = _build_alert_cards_html(briefing)
    members_html = "\n".join(member_sections)
    charts_html = "\n".join(chart_scripts)
    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = _HTML_TEMPLATE.safe_substitute(
        report_date=_escape(report_date),
        member_count=member_count,
        alert_cards=alert_cards_html,
        members_content=members_html,
        chart_scripts=charts_html,
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
    }


# --- HTML Template ---

_HTML_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>健康简报 - $report_date</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei",
                 "Helvetica Neue", Helvetica, Arial, sans-serif;
    background: #F0F4F8;
    color: #1A202C;
    line-height: 1.6;
}
.container { max-width: 960px; margin: 0 auto; padding: 20px; }
/* Header */
.header {
    background: linear-gradient(135deg, #1E40AF, #3B82F6);
    color: white;
    padding: 32px;
    border-radius: 12px;
    margin-bottom: 24px;
    box-shadow: 0 4px 12px rgba(30,64,175,0.3);
}
.header h1 { font-size: 24px; font-weight: 700; margin-bottom: 8px; }
.header .subtitle { font-size: 14px; opacity: 0.85; }
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
    border-radius: 10px;
    display: flex;
    align-items: center;
    gap: 12px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.06);
}
.card-icon { font-size: 28px; }
.card-count { font-size: 28px; font-weight: 700; }
.card-label { font-size: 13px; color: #6B7280; }
/* Member section */
.member-section {
    background: white;
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 20px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.member-section h2 {
    font-size: 18px;
    color: #1E40AF;
    border-bottom: 2px solid #DBEAFE;
    padding-bottom: 10px;
    margin-bottom: 16px;
}
.subsection { margin-bottom: 20px; }
.subsection h3 {
    font-size: 15px;
    color: #374151;
    margin-bottom: 10px;
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
.badge-normal { background: #DBEAFE; color: #1E40AF; }
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
/* Charts */
.charts-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 16px;
}
.chart-container {
    background: #FAFBFC;
    border: 1px solid #E5E7EB;
    border-radius: 8px;
    padding: 12px;
    height: 260px;
    position: relative;
}
/* Medication table */
.med-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}
.med-table th {
    background: #F3F4F6;
    color: #374151;
    padding: 8px 12px;
    text-align: left;
    font-weight: 600;
    border-bottom: 2px solid #E5E7EB;
}
.med-table td {
    padding: 8px 12px;
    border-bottom: 1px solid #F3F4F6;
}
.med-table tr:hover td { background: #F9FAFB; }
/* Footer */
.footer {
    text-align: center;
    padding: 20px;
    color: #9CA3AF;
    font-size: 12px;
    border-top: 1px solid #E5E7EB;
    margin-top: 24px;
}
.footer .disclaimer {
    color: #D1D5DB;
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
    .charts-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>&#x1F4CB; 每日健康简报</h1>
        <div class="subtitle">$report_date &middot; 共 $member_count 位家庭成员</div>
    </div>

    $alert_cards

    $members_content

    <div class="footer">
        <div>报告生成时间：$gen_time</div>
        <div>MediWise Health Tracker</div>
        <div class="disclaimer">本报告仅供参考，不构成医疗建议。如有健康问题请咨询专业医生。</div>
    </div>
</div>

$chart_scripts

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
        args = p.parse_args(sys.argv[2:])
        result = generate_report(args.member_id, args.owner_id)
        health_db.output_json(result)
    elif cmd == "screenshot":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id")
        p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
        p.add_argument("--width", type=int, default=960)
        args = p.parse_args(sys.argv[2:])
        # Generate HTML first
        report = generate_report(args.member_id, args.owner_id)
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
