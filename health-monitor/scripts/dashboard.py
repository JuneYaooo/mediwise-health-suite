"""全家健康 Dashboard —— 一屏看全家状态。

聚合：
- 各成员未解决告警（按级别排序）
- 各成员最新关键指标
- 各成员趋势警告
- 全家总体风险摘要
"""

from __future__ import annotations

import sys
import os
import argparse
from datetime import datetime

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.path_setup import setup_mediwise_path
setup_mediwise_path()

sys.path.insert(0, os.path.dirname(__file__))

import health_db
from trend import generate_report as trend_report
from metric_utils import parse_metric_value, extract_numeric_value, METRIC_UNITS


# 需要在 dashboard 展示的关键指标类型
_KEY_METRICS = [
    "heart_rate",
    "blood_pressure",
    "blood_oxygen",
    "blood_sugar",
    "temperature",
    "weight",
]


def _get_open_alerts(conn, member_id: str) -> list[dict]:
    """获取成员所有未解决告警，按严重程度排序。"""
    rows = conn.execute(
        """SELECT id, metric_type, level, title, detail, created_at
           FROM monitor_alerts
           WHERE member_id=? AND is_resolved=0
           ORDER BY
             CASE level
               WHEN 'emergency' THEN 0
               WHEN 'urgent' THEN 1
               WHEN 'warning' THEN 2
               WHEN 'info' THEN 3
             END,
             created_at DESC""",
        (member_id,)
    ).fetchall()
    return health_db.rows_to_list(rows)


def _get_latest_metrics(conn, member_id: str) -> dict:
    """获取各关键指标的最新一条记录。"""
    result = {}
    for mt in _KEY_METRICS:
        query_type = "blood_pressure" if mt == "blood_pressure" else mt
        row = conn.execute(
            """SELECT value, measured_at FROM health_metrics
               WHERE member_id=? AND metric_type=? AND is_deleted=0
               ORDER BY measured_at DESC LIMIT 1""",
            (member_id, query_type)
        ).fetchone()
        if not row:
            continue

        raw = row["value"]
        measured_at = row["measured_at"]

        if mt == "blood_pressure":
            parsed = parse_metric_value(raw)
            sys_val = parsed.get("systolic")
            dia_val = parsed.get("diastolic")
            if sys_val is not None and dia_val is not None:
                result[mt] = {
                    "value": f"{sys_val}/{dia_val}",
                    "unit": "mmHg",
                    "measured_at": measured_at,
                }
        else:
            val = extract_numeric_value(raw, mt)
            if val is not None:
                result[mt] = {
                    "value": val,
                    "unit": METRIC_UNITS.get(mt, ""),
                    "measured_at": measured_at,
                }
    return result


def _member_risk_level(alerts: list[dict], trend_warnings: list[str]) -> str:
    """根据告警和趋势警告评估成员整体风险级别。"""
    if any(a["level"] == "emergency" for a in alerts):
        return "emergency"
    if any(a["level"] == "urgent" for a in alerts):
        return "urgent"
    if alerts or trend_warnings:
        return "warning"
    return "normal"


def _risk_label(level: str) -> str:
    return {"normal": "正常", "warning": "需关注", "urgent": "紧急", "emergency": "危急"}.get(level, level)


def generate_dashboard(owner_id: str | None = None) -> dict:
    """生成全家健康 dashboard。"""
    health_db.ensure_db()

    # 1. 获取成员列表
    conn = health_db.get_connection()
    try:
        if owner_id:
            members = health_db.rows_to_list(conn.execute(
                """SELECT id, name, birth_date, gender
                   FROM members
                   WHERE owner_id=? AND is_deleted=0
                   ORDER BY name""",
                (owner_id,)
            ).fetchall())
        else:
            members = health_db.rows_to_list(conn.execute(
                "SELECT id, name, birth_date, gender FROM members WHERE is_deleted=0 ORDER BY name"
            ).fetchall())
    finally:
        conn.close()

    if not members:
        return {
            "status": "ok",
            "member_count": 0,
            "summary": "暂无家庭成员，请先添加成员。",
            "members": [],
            "family_risk": "normal",
            "family_risk_label": "正常",
        }

    # 2. 逐成员聚合数据（每次用独立连接，与 trend_report 隔离）
    member_reports = []
    all_risk_levels = []

    for m in members:
        mid = m["id"]

        conn = health_db.get_connection()
        try:
            alerts = _get_open_alerts(conn, mid)
            latest_metrics = _get_latest_metrics(conn, mid)
        finally:
            conn.close()

        # trend_report 内部自己管理连接
        trend_data = trend_report(mid)
        trend_warnings = trend_data.get("warnings", [])

        risk = _member_risk_level(alerts, trend_warnings)
        all_risk_levels.append(risk)

        member_reports.append({
            "member_id": mid,
            "name": m["name"],
            "risk_level": risk,
            "risk_label": _risk_label(risk),
            "open_alerts": len(alerts),
            "alerts": alerts[:3],       # dashboard 只展示前3条最高优先级告警
            "latest_metrics": latest_metrics,
            "trend_warnings": trend_warnings,
        })

    # 3. 全家整体风险 = 最高个人风险
    for level in ("emergency", "urgent", "warning"):
        if level in all_risk_levels:
            family_risk = level
            break
    else:
        family_risk = "normal"

    # 4. 生成摘要文字
    total_alerts = sum(r["open_alerts"] for r in member_reports)
    emergency_members = [r["name"] for r in member_reports if r["risk_level"] == "emergency"]
    urgent_members = [r["name"] for r in member_reports if r["risk_level"] == "urgent"]

    summary_parts = []
    if emergency_members:
        summary_parts.append(f"【危急】{', '.join(emergency_members)} 需立即关注")
    if urgent_members:
        summary_parts.append(f"【紧急】{', '.join(urgent_members)} 有紧急告警")
    if total_alerts == 0:
        summary_parts.append("全家健康状态良好，无未解决告警")
    else:
        summary_parts.append(f"共 {total_alerts} 条未解决告警")

    return {
        "status": "ok",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "member_count": len(member_reports),
        "family_risk": family_risk,
        "family_risk_label": _risk_label(family_risk),
        "total_open_alerts": total_alerts,
        "summary": "；".join(summary_parts),
        "members": member_reports,
    }


def cmd_dashboard(args):
    result = generate_dashboard(getattr(args, "owner_id", None))
    health_db.output_json(result)


def main():
    parser = argparse.ArgumentParser(description="全家健康 Dashboard")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("show", help="展示全家健康概览")
    p.add_argument("--owner-id", default=None, help="按 owner 过滤成员")
    args = parser.parse_args()
    cmd_dashboard(args)


if __name__ == "__main__":
    main()
