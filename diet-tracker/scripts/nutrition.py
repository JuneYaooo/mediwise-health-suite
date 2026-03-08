"""营养分析、热量趋势。"""

from __future__ import annotations

import argparse
import sys
import os
from datetime import datetime, timedelta

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from path_setup import setup_mediwise_path
setup_mediwise_path()

from health_db import ensure_db, get_connection, rows_to_list, output_json
from validators import validate_date_optional
from metric_utils import get_member_or_error


def weekly_summary(args):
    """一周营养趋势（每日热量、平均三大营养素）。"""
    ensure_db()
    conn = get_connection()
    try:
        m = get_member_or_error(conn, args.member_id)
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        if args.end_date:
            end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        else:
            end = datetime.now().date()
        start = end - timedelta(days=6)

        rows = conn.execute(
            """SELECT meal_date,
                      SUM(total_calories) as calories,
                      SUM(total_protein) as protein,
                      SUM(total_fat) as fat,
                      SUM(total_carbs) as carbs,
                      SUM(total_fiber) as fiber
               FROM diet_records
               WHERE member_id=? AND meal_date>=? AND meal_date<=? AND is_deleted=0
               GROUP BY meal_date
               ORDER BY meal_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
        daily = rows_to_list(rows)

        # Compute weekly averages
        days_with_data = len(daily)
        if days_with_data > 0:
            avg = {
                "calories": round(sum(d["calories"] or 0 for d in daily) / days_with_data, 1),
                "protein": round(sum(d["protein"] or 0 for d in daily) / days_with_data, 1),
                "fat": round(sum(d["fat"] or 0 for d in daily) / days_with_data, 1),
                "carbs": round(sum(d["carbs"] or 0 for d in daily) / days_with_data, 1),
                "fiber": round(sum(d["fiber"] or 0 for d in daily) / days_with_data, 1),
            }
        else:
            avg = {"calories": 0, "protein": 0, "fat": 0, "carbs": 0, "fiber": 0}

        output_json({
            "status": "ok",
            "member_name": m["name"],
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "days_with_data": days_with_data,
            "daily": daily,
            "average": avg,
        })
    finally:
        conn.close()


def calorie_trend(args):
    """热量趋势分析（N 天每日总热量）。"""
    ensure_db()
    conn = get_connection()
    try:
        m = get_member_or_error(conn, args.member_id)
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        days = args.days or 7
        end = datetime.now().date()
        start = end - timedelta(days=days - 1)

        rows = conn.execute(
            """SELECT meal_date, SUM(total_calories) as calories
               FROM diet_records
               WHERE member_id=? AND meal_date>=? AND meal_date<=? AND is_deleted=0
               GROUP BY meal_date
               ORDER BY meal_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
        daily = rows_to_list(rows)

        # Fill in missing days with 0
        date_map = {d["meal_date"]: d["calories"] or 0 for d in daily}
        trend = []
        current = start
        while current <= end:
            ds = current.isoformat()
            trend.append({"date": ds, "calories": date_map.get(ds, 0)})
            current += timedelta(days=1)

        total = sum(d["calories"] for d in trend)
        avg = round(total / days, 1) if days > 0 else 0

        output_json({
            "status": "ok",
            "member_name": m["name"],
            "days": days,
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "trend": trend,
            "total_calories": total,
            "average_daily": avg,
        })
    finally:
        conn.close()


def nutrition_balance(args):
    """三大营养素比例分析。"""
    ensure_db()
    conn = get_connection()
    try:
        m = get_member_or_error(conn, args.member_id)
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        days = args.days or 7
        end = datetime.now().date()
        start = end - timedelta(days=days - 1)

        row = conn.execute(
            """SELECT SUM(total_calories) as calories,
                      SUM(total_protein) as protein,
                      SUM(total_fat) as fat,
                      SUM(total_carbs) as carbs,
                      SUM(total_fiber) as fiber
               FROM diet_records
               WHERE member_id=? AND meal_date>=? AND meal_date<=? AND is_deleted=0""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchone()

        protein = (row["protein"] or 0) if row else 0
        fat = (row["fat"] or 0) if row else 0
        carbs = (row["carbs"] or 0) if row else 0
        fiber = (row["fiber"] or 0) if row else 0
        calories = (row["calories"] or 0) if row else 0

        total_macro_g = protein + fat + carbs
        ratio = {}
        if total_macro_g > 0:
            ratio = {
                "protein_pct": round(protein / total_macro_g * 100, 1),
                "fat_pct": round(fat / total_macro_g * 100, 1),
                "carbs_pct": round(carbs / total_macro_g * 100, 1),
            }

        # Reference: Chinese Dietary Guidelines recommendation
        # Protein 10-15%, Fat 20-30%, Carbs 50-65%
        assessment = []
        if ratio:
            if ratio["protein_pct"] < 10:
                assessment.append("蛋白质摄入偏低，建议增加鱼肉蛋奶豆类")
            elif ratio["protein_pct"] > 20:
                assessment.append("蛋白质比例偏高")
            if ratio["fat_pct"] > 35:
                assessment.append("脂肪摄入偏高，建议减少油炸食物")
            elif ratio["fat_pct"] < 15:
                assessment.append("脂肪摄入偏低")
            if ratio["carbs_pct"] > 70:
                assessment.append("碳水摄入偏高，建议增加蔬菜蛋白质比例")
            elif ratio["carbs_pct"] < 40:
                assessment.append("碳水摄入偏低")

        output_json({
            "status": "ok",
            "member_name": m["name"],
            "days": days,
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "totals": {
                "calories": round(calories, 1),
                "protein": round(protein, 1),
                "fat": round(fat, 1),
                "carbs": round(carbs, 1),
                "fiber": round(fiber, 1),
            },
            "daily_average": {
                "calories": round(calories / days, 1) if days > 0 else 0,
                "protein": round(protein / days, 1) if days > 0 else 0,
                "fat": round(fat / days, 1) if days > 0 else 0,
                "carbs": round(carbs / days, 1) if days > 0 else 0,
                "fiber": round(fiber / days, 1) if days > 0 else 0,
            },
            "macro_ratio": ratio,
            "assessment": assessment,
        })
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="营养分析")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ws = sub.add_parser("weekly-summary")
    p_ws.add_argument("--member-id", required=True)
    p_ws.add_argument("--end-date", default=None, help="结束日期 YYYY-MM-DD（默认今天）")

    p_ct = sub.add_parser("calorie-trend")
    p_ct.add_argument("--member-id", required=True)
    p_ct.add_argument("--days", type=int, default=7, help="天数（默认 7）")

    p_nb = sub.add_parser("nutrition-balance")
    p_nb.add_argument("--member-id", required=True)
    p_nb.add_argument("--days", type=int, default=7, help="天数（默认 7）")

    args = parser.parse_args()
    commands = {
        "weekly-summary": weekly_summary,
        "calorie-trend": calorie_trend,
        "nutrition-balance": nutrition_balance,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
