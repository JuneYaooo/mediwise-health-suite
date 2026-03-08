"""Trend analysis for health-monitor.

Analyzes health metric data over configurable time periods,
computing statistics and detecting deteriorating trends.
"""

from __future__ import annotations

import sys
import os
import json
import argparse
import logging
from datetime import datetime, timedelta

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from path_setup import setup_mediwise_path
setup_mediwise_path()

sys.path.insert(0, os.path.dirname(__file__))

import health_db
from metric_utils import parse_metric_value, extract_numeric_value
from threshold import get_thresholds

logger = logging.getLogger(__name__)


# Metric types suitable for trend analysis (single numeric value)
_TRENDABLE_TYPES = ["heart_rate", "blood_oxygen", "temperature", "blood_sugar", "weight", "steps", "stress", "calories"]

_BP_COMPONENTS = {
    "blood_pressure": [("systolic", "blood_pressure_systolic"), ("diastolic", "blood_pressure_diastolic")],
    "blood_pressure_systolic": [("systolic", "blood_pressure_systolic")],
    "blood_pressure_diastolic": [("diastolic", "blood_pressure_diastolic")],
}


def _linear_regression_slope(values: list[float]) -> float:
    """Simple linear regression slope (least squares).

    Positive slope = rising trend, negative = declining.
    """
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    numerator = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _std_dev(values: list[float], mean: float) -> float:
    """Calculate standard deviation."""
    n = len(values)
    if n < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return variance ** 0.5


def _summarize_values(values: list[float]) -> dict:
    """Build statistics and direction for a numeric series."""
    mean_val = sum(values) / len(values)
    max_val = max(values)
    min_val = min(values)
    std_val = _std_dev(values, mean_val)
    slope = _linear_regression_slope(values)
    relative_slope = slope / mean_val if mean_val != 0 else 0
    if relative_slope > 0.02:
        direction = "rising"
        direction_cn = "上升"
    elif relative_slope < -0.02:
        direction = "declining"
        direction_cn = "下降"
    else:
        direction = "stable"
        direction_cn = "稳定"
    return {
        "statistics": {
            "mean": round(mean_val, 2),
            "max": round(max_val, 2),
            "min": round(min_val, 2),
            "std_dev": round(std_val, 2),
            "slope": round(slope, 4),
        },
        "trend": direction,
        "trend_cn": direction_cn,
    }


def _check_sustained_abnormality(member_id: str, threshold_key: str, rows: list[dict], extractor) -> bool:
    """Check if daily averages exceed warning threshold for 3+ consecutive days."""
    thresholds = get_thresholds(member_id)
    directions_cfg = thresholds.get(threshold_key, {})
    if not directions_cfg:
        return False

    daily_values = {}
    for row in rows:
        day = row["measured_at"][:10]
        value = extractor(row)
        if value is not None:
            daily_values.setdefault(day, []).append(value)

    daily_avgs = sorted(
        [(day, sum(vs) / len(vs)) for day, vs in daily_values.items()],
        key=lambda x: x[0]
    )
    if len(daily_avgs) < 3:
        return False

    for dir_name, levels in directions_cfg.items():
        warning_val = levels.get("warning")
        if warning_val is None:
            continue
        consecutive = 0
        for _, avg in daily_avgs:
            if (dir_name == "above" and avg > warning_val) or                (dir_name == "below" and avg < warning_val):
                consecutive += 1
            else:
                consecutive = 0
        if consecutive >= 3:
            return True
    return False


def analyze_trend(member_id: str, metric_type: str, days: int = 7) -> dict:
    """Analyze trend for a specific metric type over a period.

    Returns:
        Dict with statistics and trend direction.
    """
    health_db.ensure_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    query_type = "blood_pressure" if metric_type in _BP_COMPONENTS else metric_type
    conn = health_db.get_connection()
    try:
        rows = health_db.rows_to_list(conn.execute(
            """SELECT value, measured_at FROM health_metrics
               WHERE member_id=? AND metric_type=? AND is_deleted=0 AND measured_at>=?
               ORDER BY measured_at ASC""",
            (member_id, query_type, cutoff)
        ).fetchall())
    finally:
        conn.close()

    if not rows:
        return {
            "metric_type": metric_type,
            "days": days,
            "data_points": 0,
            "message": "该时间段内没有数据",
        }

    if metric_type in _BP_COMPONENTS:
        component_results = {}
        total_points = 0
        sustained_abnormal = False

        for field_name, threshold_key in _BP_COMPONENTS[metric_type]:
            values = []
            for row in rows:
                parsed = parse_metric_value(row["value"])
                value = parsed.get(field_name)
                if value is None:
                    continue
                try:
                    values.append(float(value))
                except (TypeError, ValueError):
                    continue

            if not values:
                continue

            summary = _summarize_values(values)
            component_results[field_name] = {
                **summary["statistics"],
                "trend": summary["trend"],
                "trend_cn": summary["trend_cn"],
            }
            total_points = max(total_points, len(values))

            def extract_component(row, field=field_name):
                parsed = parse_metric_value(row["value"])
                value = parsed.get(field)
                if value is None:
                    return None
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            sustained_abnormal = sustained_abnormal or _check_sustained_abnormality(
                member_id,
                threshold_key,
                rows,
                extract_component,
            )

        if not component_results:
            return {
                "metric_type": metric_type,
                "days": days,
                "data_points": 0,
                "message": "无有效数值数据",
            }

        primary_key = "systolic" if "systolic" in component_results else next(iter(component_results))
        primary = component_results[primary_key]
        result = {
            "metric_type": metric_type,
            "days": days,
            "data_points": total_points,
            "statistics": {
                key: primary[key] for key in ("mean", "max", "min", "std_dev", "slope")
            },
            "trend": primary["trend"],
            "trend_cn": primary["trend_cn"],
            "sustained_abnormal": sustained_abnormal,
            "first_date": rows[0]["measured_at"][:10],
            "last_date": rows[-1]["measured_at"][:10],
        }
        if metric_type == "blood_pressure":
            result["components"] = component_results
        return result

    values = []
    for row in rows:
        v = extract_numeric_value(row["value"], metric_type)
        if v is not None:
            values.append(v)

    if not values:
        return {
            "metric_type": metric_type,
            "days": days,
            "data_points": 0,
            "message": "无有效数值数据",
        }

    summary = _summarize_values(values)
    sustained_abnormal = _check_sustained_abnormality(
        member_id,
        metric_type,
        rows,
        lambda row: extract_numeric_value(row["value"], metric_type),
    )

    return {
        "metric_type": metric_type,
        "days": days,
        "data_points": len(values),
        "statistics": summary["statistics"],
        "trend": summary["trend"],
        "trend_cn": summary["trend_cn"],
        "sustained_abnormal": sustained_abnormal,
        "first_date": rows[0]["measured_at"][:10],
        "last_date": rows[-1]["measured_at"][:10],
    }


def generate_report(member_id: str) -> dict:
    """Generate a full trend report across all metric types."""
    health_db.ensure_db()
    from config import load_config
    cfg = load_config()
    days = cfg.get("monitor", {}).get("trend_window_days", 7)

    conn = health_db.get_connection()
    try:
        member = conn.execute(
            "SELECT name FROM members WHERE id=? AND is_deleted=0",
            (member_id,)
        ).fetchone()
        if not member:
            return {"status": "error", "message": f"未找到成员: {member_id}"}

        # Find which metric types have data
        metric_types = [r["metric_type"] for r in conn.execute(
            """SELECT DISTINCT metric_type FROM health_metrics
               WHERE member_id=? AND is_deleted=0""",
            (member_id,)
        ).fetchall()]
    finally:
        conn.close()

    trends = []
    warnings = []
    for mt in metric_types:
        result = analyze_trend(member_id, mt, days)
        if result.get("data_points", 0) > 0:
            trends.append(result)
            if result.get("sustained_abnormal"):
                warnings.append(f"{mt} 持续异常（{days}天内）")
            elif result.get("trend") == "rising" and mt in ("heart_rate", "blood_sugar", "temperature"):
                warnings.append(f"{mt} 呈上升趋势")
            elif result.get("trend") == "declining" and mt in ("blood_oxygen",):
                warnings.append(f"{mt} 呈下降趋势")

    return {
        "status": "ok",
        "member_id": member_id,
        "member_name": member["name"],
        "period_days": days,
        "trends": trends,
        "warnings": warnings,
        "warning_count": len(warnings),
    }


def cmd_analyze(args):
    """Analyze trend for a single metric type."""
    result = analyze_trend(args.member_id, args.type, int(args.days))
    health_db.output_json({"status": "ok", **result})


def cmd_report(args):
    """Generate full trend report."""
    result = generate_report(args.member_id)
    health_db.output_json(result)


def main():
    parser = argparse.ArgumentParser(description="健康趋势分析")
    sub = parser.add_subparsers(dest="command", required=True)

    p_analyze = sub.add_parser("analyze", help="单指标趋势分析")
    p_analyze.add_argument("--member-id", required=True)
    p_analyze.add_argument("--type", required=True, help="指标类型")
    p_analyze.add_argument("--days", default="7", help="分析天数")

    p_report = sub.add_parser("report", help="全指标趋势报告")
    p_report.add_argument("--member-id", required=True)

    args = parser.parse_args()
    commands = {"analyze": cmd_analyze, "report": cmd_report}
    commands[args.command](args)


if __name__ == "__main__":
    main()
