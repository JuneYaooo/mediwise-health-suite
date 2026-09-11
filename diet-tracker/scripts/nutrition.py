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

from health_db import ensure_db, get_medical_connection, get_lifestyle_connection, rows_to_list, output_json, verify_member_ownership
from metric_utils import get_member_or_error

# 与 diet.py 的记录级营养列一致。NULL = 未知（未解析），0 = 确认是零。
_NUTRITION_FIELDS = ("calories", "protein", "fat", "carbs", "fiber")


def _get_member(member_id, owner_id=None):
    medical_conn = get_medical_connection()
    try:
        m = get_member_or_error(medical_conn, member_id)
        if not m:
            return None
        if not verify_member_ownership(medical_conn, member_id, owner_id):
            return None
        return m
    finally:
        medical_conn.close()
def weekly_summary(args):
    """一周营养趋势（每日热量、平均三大营养素）。"""
    ensure_db()
    m = _get_member(args.member_id, args.owner_id)
    if not m:
        output_json({"status": "error", "message": f"未找到成员或无权访问: {args.member_id}"})
        return

    if args.end_date:
        end = datetime.strptime(args.end_date, "%Y-%m-%d").date()
    else:
        end = datetime.now().date()
    start = end - timedelta(days=6)

    lifestyle_conn = get_lifestyle_connection()
    try:
        rows = lifestyle_conn.execute(
            """SELECT meal_date,
                      SUM(total_calories) as calories,
                      SUM(total_protein) as protein,
                      SUM(total_fat) as fat,
                      SUM(total_carbs) as carbs,
                      SUM(total_fiber) as fiber,
                      MAX(CASE WHEN total_calories IS NULL THEN 1 ELSE 0 END) as calories_unknown,
                      MAX(CASE WHEN total_protein  IS NULL THEN 1 ELSE 0 END) as protein_unknown,
                      MAX(CASE WHEN total_fat      IS NULL THEN 1 ELSE 0 END) as fat_unknown,
                      MAX(CASE WHEN total_carbs    IS NULL THEN 1 ELSE 0 END) as carbs_unknown,
                      MAX(CASE WHEN total_fiber    IS NULL THEN 1 ELSE 0 END) as fiber_unknown
               FROM diet_records
               WHERE member_id=? AND meal_date>=? AND meal_date<=? AND is_deleted=0
               GROUP BY meal_date
               ORDER BY meal_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
    finally:
        lifestyle_conn.close()
    daily = rows_to_list(rows)

    # 未解析日不进均值：把它当 0 等于把"不知道吃了多少"平均成"吃得很少"。
    # 分母逐字段各算——同一天可能热量已知而 fiber 未知（条目没给 fiber），
    # 用一个统一分母就必然对某一项说谎。
    # 逐日标记而非只依赖 SUM：SQLite 的 SUM 仅在整组皆 NULL 时返回 NULL，
    # 混合组会漏出部分和，而部分和读起来就是一个真实的数字。
    avg = {}
    days_averaged = {}
    for f in _NUTRITION_FIELDS:
        known = [d[f] for d in daily if not d.get(f"{f}_unknown")]
        days_averaged[f] = len(known)
        avg[f] = round(sum(known) / len(known), 1) if known else None

    unresolved_days = sum(1 for d in daily if d.get("calories_unknown"))
    # daily 只保留公开列，unknown 标记已由 unresolved_days 与 average 的 null 表达
    for d in daily:
        for f in _NUTRITION_FIELDS:
            d.pop(f"{f}_unknown", None)

    output_json({
        "status": "ok",
        "member_name": m["name"],
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "days_with_data": len(daily),
        "unresolved_days": unresolved_days,
        "days_averaged": days_averaged,
        "daily": daily,
        "average": avg,
    })


def calorie_trend(args):
    """热量趋势分析（N 天每日总热量）。"""
    ensure_db()
    m = _get_member(args.member_id, args.owner_id)
    if not m:
        output_json({"status": "error", "message": f"未找到成员或无权访问: {args.member_id}"})
        return

    days = args.days or 7
    end = datetime.now().date()
    start = end - timedelta(days=days - 1)

    lifestyle_conn = get_lifestyle_connection()
    try:
        rows = lifestyle_conn.execute(
            """SELECT meal_date, SUM(total_calories) as calories,
                      MAX(CASE WHEN total_calories IS NULL THEN 1 ELSE 0 END) as calories_unknown
               FROM diet_records
               WHERE member_id=? AND meal_date>=? AND meal_date<=? AND is_deleted=0
               GROUP BY meal_date
               ORDER BY meal_date""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchall()
    finally:
        lifestyle_conn.close()
    daily = rows_to_list(rows)

    # 只收已解析日。未解析日既不入 trend 也不入分母——
    # 旧写法把未记录日和未解析日都按 0 计入，等于用"没吃"拉低均值。
    date_map = {d["meal_date"]: d["calories"] for d in daily if not d.get("calories_unknown")}
    trend = []
    current = start
    while current <= end:
        ds = current.isoformat()
        # 缺失即为 null（不知道），不是 0（没吃）
        trend.append({"date": ds, "calories": date_map.get(ds)})
        current += timedelta(days=1)

    recorded = [t["calories"] for t in trend if t["calories"] is not None]
    total = sum(recorded) if recorded else None
    avg = round(total / len(recorded), 1) if recorded else None

    output_json({
        "status": "ok",
        "member_name": m["name"],
        "days": days,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "days_recorded": len(recorded),
        "trend": trend,
        "total_calories": total,
        "average_daily": avg,
    })


def nutrition_balance(args):
    """三大营养素比例分析。"""
    ensure_db()
    m = _get_member(args.member_id, args.owner_id)
    if not m:
        output_json({"status": "error", "message": f"未找到成员或无权访问: {args.member_id}"})
        return

    days = args.days or 7
    end = datetime.now().date()
    start = end - timedelta(days=days - 1)

    lifestyle_conn = get_lifestyle_connection()
    try:
        row = lifestyle_conn.execute(
            """SELECT SUM(total_calories) as calories,
                      SUM(total_protein) as protein,
                      SUM(total_fat) as fat,
                      SUM(total_carbs) as carbs,
                      SUM(total_fiber) as fiber,
                      MAX(CASE WHEN total_calories IS NULL THEN 1 ELSE 0 END) as calories_unknown,
                      MAX(CASE WHEN total_protein  IS NULL THEN 1 ELSE 0 END) as protein_unknown,
                      MAX(CASE WHEN total_fat      IS NULL THEN 1 ELSE 0 END) as fat_unknown,
                      MAX(CASE WHEN total_carbs    IS NULL THEN 1 ELSE 0 END) as carbs_unknown,
                      MAX(CASE WHEN total_fiber    IS NULL THEN 1 ELSE 0 END) as fiber_unknown,
                      COUNT(DISTINCT CASE WHEN total_calories IS NOT NULL THEN meal_date END) as calories_days,
                      COUNT(DISTINCT CASE WHEN total_protein  IS NOT NULL THEN meal_date END) as protein_days,
                      COUNT(DISTINCT CASE WHEN total_fat      IS NOT NULL THEN meal_date END) as fat_days,
                      COUNT(DISTINCT CASE WHEN total_carbs    IS NOT NULL THEN meal_date END) as carbs_days,
                      COUNT(DISTINCT CASE WHEN total_fiber    IS NOT NULL THEN meal_date END) as fiber_days
               FROM diet_records
               WHERE member_id=? AND meal_date>=? AND meal_date<=? AND is_deleted=0""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchone()

        # 有记录的日子（含未解析）——用来区分"整周没记"与"记了但没解析"
        days_with_data = lifestyle_conn.execute(
            """SELECT COUNT(DISTINCT meal_date) FROM diet_records
               WHERE member_id=? AND meal_date>=? AND meal_date<=? AND is_deleted=0""",
            (args.member_id, start.isoformat(), end.isoformat())
        ).fetchone()[0]
    finally:
        lifestyle_conn.close()

    # 窗口内任一记录该字段未知，则合计未知——绝不把部分和当成合计。
    # 窗口内一条记录都没有时 SUM 本就为 NULL，与"未知"同义（days_with_data 加以区分）。
    def _field(f):
        if row is None or row[f"{f}_unknown"]:
            return None
        return row[f]

    protein = _field("protein")
    fat = _field("fat")
    carbs = _field("carbs")
    fiber = _field("fiber")
    calories = _field("calories")

    # 三者皆已知才算比例。任一为 NULL 时算出来的是被未知拉歪的假比例。
    ratio = {}
    if protein is not None and fat is not None and carbs is not None:
        total_macro_g = protein + fat + carbs
        if total_macro_g > 0:
            ratio = {
                "protein_pct": round(protein / total_macro_g * 100, 1),
                "fat_pct": round(fat / total_macro_g * 100, 1),
                "carbs_pct": round(carbs / total_macro_g * 100, 1),
            }

    # Built-in comparison ranges. These are displayed as reference differences,
    # not interpreted as nutrition therapy or diet advice.
    # Protein 10-15%, Fat 20-30%, Carbs 50-65%
    assessment = []
    if ratio:
        if ratio["protein_pct"] < 10:
            assessment.append(f"蛋白质占比 {ratio['protein_pct']}%，低于内置参考下限 10%")
        elif ratio["protein_pct"] > 20:
            assessment.append(f"蛋白质占比 {ratio['protein_pct']}%，高于内置参考上限 20%")
        if ratio["fat_pct"] > 35:
            assessment.append(f"脂肪占比 {ratio['fat_pct']}%，高于内置参考上限 35%")
        elif ratio["fat_pct"] < 15:
            assessment.append(f"脂肪占比 {ratio['fat_pct']}%，低于内置参考下限 15%")
        if ratio["carbs_pct"] > 70:
            assessment.append(f"碳水占比 {ratio['carbs_pct']}%，高于内置参考上限 70%")
        elif ratio["carbs_pct"] < 40:
            assessment.append(f"碳水占比 {ratio['carbs_pct']}%，低于内置参考下限 40%")

    output_json({
        "status": "ok",
        "member_name": m["name"],
        "days": days,
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "days_with_data": days_with_data,
        "totals": {
            "calories": round(calories, 1) if calories is not None else None,
            "protein": round(protein, 1) if protein is not None else None,
            "fat": round(fat, 1) if fat is not None else None,
            "carbs": round(carbs, 1) if carbs is not None else None,
            "fiber": round(fiber, 1) if fiber is not None else None,
        },
        # 分母是"该字段已知的日数"，不是窗口天数——用窗口天数会把未记录日算成没吃
        "daily_average": {
            f: (round(v / (row[f"{f}_days"] or 0), 1) if v is not None and row[f"{f}_days"] else None)
            for f, v in (("calories", calories), ("protein", protein), ("fat", fat),
                         ("carbs", carbs), ("fiber", fiber))
        },
        "macro_ratio": ratio,
        "assessment": assessment,
    })


def main():
    parser = argparse.ArgumentParser(description="营养分析")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ws = sub.add_parser("weekly-summary")
    p_ws.add_argument("--member-id", required=True)
    p_ws.add_argument("--end-date", default=None, help="统计截止日期 YYYY-MM-DD，默认今天")
    p_ws.add_argument("--owner-id", default=None)

    p_ct = sub.add_parser("calorie-trend")
    p_ct.add_argument("--member-id", required=True)
    p_ct.add_argument("--days", type=int, default=7, help="统计天数，默认 7")
    p_ct.add_argument("--owner-id", default=None)

    p_nb = sub.add_parser("nutrition-balance")
    p_nb.add_argument("--member-id", required=True)
    p_nb.add_argument("--days", type=int, default=7, help="统计天数，默认 7")
    p_nb.add_argument("--owner-id", default=None)

    args = parser.parse_args()
    commands = {
        "weekly-summary": weekly_summary,
        "calorie-trend": calorie_trend,
        "nutrition-balance": nutrition_balance,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
