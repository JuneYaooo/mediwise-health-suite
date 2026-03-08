"""饮食记录 CRUD 与每日摘要。"""

from __future__ import annotations

import argparse
import json
import sys
import os

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from path_setup import setup_mediwise_path
setup_mediwise_path()

from health_db import ensure_db, get_connection, generate_id, now_iso, row_to_dict, rows_to_list, output_json, transaction
from validators import validate_date, validate_date_optional
from metric_utils import get_member_or_error

VALID_MEAL_TYPES = ["breakfast", "lunch", "dinner", "snack"]

MEAL_TYPE_NAMES = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "dinner": "晚餐",
    "snack": "加餐",
}


def _parse_items(items_json):
    """Parse and validate items JSON array."""
    if not items_json:
        return []
    if isinstance(items_json, str):
        items = json.loads(items_json)
    else:
        items = items_json
    if not isinstance(items, list):
        raise ValueError("items 必须为 JSON 数组")
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"items[{i}] 必须为对象")
        if not item.get("food_name"):
            raise ValueError(f"items[{i}].food_name 不能为空")
    return items


def _compute_totals(conn, record_id):
    """Recompute and update totals for a diet record from its items."""
    rows = conn.execute(
        "SELECT calories, protein, fat, carbs, fiber FROM diet_items WHERE record_id=? AND is_deleted=0",
        (record_id,)
    ).fetchall()
    totals = {"total_calories": 0, "total_protein": 0, "total_fat": 0, "total_carbs": 0, "total_fiber": 0}
    for r in rows:
        totals["total_calories"] += r["calories"] or 0
        totals["total_protein"] += r["protein"] or 0
        totals["total_fat"] += r["fat"] or 0
        totals["total_carbs"] += r["carbs"] or 0
        totals["total_fiber"] += r["fiber"] or 0
    conn.execute(
        """UPDATE diet_records SET total_calories=?, total_protein=?, total_fat=?, total_carbs=?, total_fiber=?
           WHERE id=?""",
        (totals["total_calories"], round(totals["total_protein"], 1),
         round(totals["total_fat"], 1), round(totals["total_carbs"], 1),
         round(totals["total_fiber"], 1), record_id)
    )
    return totals


def add_meal(args):
    """添加一餐记录（含多个食物条目）。"""
    ensure_db()
    with transaction() as conn:
        m = get_member_or_error(conn, args.member_id)
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        if args.meal_type not in VALID_MEAL_TYPES:
            output_json({"status": "error", "message": f"不支持的餐次类型: {args.meal_type}，支持: {', '.join(VALID_MEAL_TYPES)}"})
            return

        try:
            meal_date = validate_date(args.meal_date, "用餐日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        try:
            items = _parse_items(args.items)
        except (ValueError, json.JSONDecodeError) as e:
            output_json({"status": "error", "message": f"食物条目格式错误: {e}"})
            return

        record_id = generate_id()
        conn.execute(
            """INSERT INTO diet_records
               (id, member_id, meal_type, meal_date, meal_time, total_calories, total_protein, total_fat, total_carbs, total_fiber, note, created_at, is_deleted)
               VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, 0, ?, ?, 0)""",
            (record_id, args.member_id, args.meal_type, meal_date, args.meal_time, args.note, now_iso())
        )

        for item in items:
            item_id = generate_id()
            conn.execute(
                """INSERT INTO diet_items
                   (id, record_id, food_name, amount, unit, calories, protein, fat, carbs, fiber, note, created_at, is_deleted)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (item_id, record_id, item["food_name"],
                 item.get("amount"), item.get("unit"),
                 item.get("calories", 0), item.get("protein", 0), item.get("fat", 0),
                 item.get("carbs", 0), item.get("fiber", 0),
                 item.get("note"), now_iso())
            )

        _compute_totals(conn, record_id)
        conn.commit()

        record = row_to_dict(conn.execute("SELECT * FROM diet_records WHERE id=?", (record_id,)).fetchone())
        item_rows = rows_to_list(conn.execute(
            "SELECT * FROM diet_items WHERE record_id=? AND is_deleted=0", (record_id,)
        ).fetchall())
        record["items"] = item_rows

        meal_name = MEAL_TYPE_NAMES.get(args.meal_type, args.meal_type)
        output_json({
            "status": "ok",
            "message": f"已记录{m['name']}的{meal_date}{meal_name}（{len(items)}个食物，共{record['total_calories']}kcal）",
            "record": record
        })


def add_item(args):
    """向已有餐次追加食物条目。"""
    ensure_db()
    with transaction() as conn:
        record = conn.execute(
            "SELECT * FROM diet_records WHERE id=? AND is_deleted=0", (args.record_id,)
        ).fetchone()
        if not record:
            output_json({"status": "error", "message": f"未找到餐次记录: {args.record_id}"})
            return

        if not args.food_name:
            output_json({"status": "error", "message": "食物名称不能为空"})
            return

        item_id = generate_id()
        conn.execute(
            """INSERT INTO diet_items
               (id, record_id, food_name, amount, unit, calories, protein, fat, carbs, fiber, note, created_at, is_deleted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (item_id, args.record_id, args.food_name,
             args.amount, args.unit,
             args.calories or 0, args.protein or 0, args.fat or 0,
             args.carbs or 0, args.fiber or 0,
             args.note, now_iso())
        )

        _compute_totals(conn, args.record_id)
        conn.commit()

        item = row_to_dict(conn.execute("SELECT * FROM diet_items WHERE id=?", (item_id,)).fetchone())
        output_json({
            "status": "ok",
            "message": f"已向餐次 {args.record_id} 添加食物: {args.food_name}",
            "item": item
        })


def list_meals(args):
    """查看某日/某段时间的饮食记录。"""
    ensure_db()
    conn = get_connection()
    try:
        sql = "SELECT * FROM diet_records WHERE member_id=? AND is_deleted=0"
        params = [args.member_id]

        if args.date:
            sql += " AND meal_date=?"
            params.append(args.date)
        else:
            if args.start_date:
                sql += " AND meal_date>=?"
                params.append(args.start_date)
            if args.end_date:
                sql += " AND meal_date<=?"
                params.append(args.end_date)

        if args.meal_type:
            if args.meal_type not in VALID_MEAL_TYPES:
                output_json({"status": "error", "message": f"不支持的餐次类型: {args.meal_type}"})
                return
            sql += " AND meal_type=?"
            params.append(args.meal_type)

        sql += " ORDER BY meal_date DESC, meal_time DESC"
        if args.limit:
            sql += " LIMIT ?"
            params.append(int(args.limit))

        rows = conn.execute(sql, params).fetchall()
        records = rows_to_list(rows)

        # Batch-fetch all diet_items for the returned records in one query
        record_ids = [rec["id"] for rec in records]
        items_by_record = {rid: [] for rid in record_ids}
        if record_ids:
            placeholders = ",".join("?" for _ in record_ids)
            all_items = conn.execute(
                f"SELECT * FROM diet_items WHERE record_id IN ({placeholders}) AND is_deleted=0 ORDER BY created_at",
                record_ids
            ).fetchall()
            for item in rows_to_list(all_items):
                items_by_record[item["record_id"]].append(item)

        for rec in records:
            rec["items"] = items_by_record.get(rec["id"], [])

        output_json({"status": "ok", "count": len(records), "records": records})
    finally:
        conn.close()


def delete_record(args):
    """删除饮食记录或食物条目（软删除）。"""
    ensure_db()
    delete_type = args.type or "record"
    with transaction() as conn:
        if delete_type == "item":
            row = conn.execute("SELECT * FROM diet_items WHERE id=? AND is_deleted=0", (args.id,)).fetchone()
            if not row:
                output_json({"status": "error", "message": f"未找到食物条目: {args.id}"})
                return
            conn.execute("UPDATE diet_items SET is_deleted=1 WHERE id=?", (args.id,))
            _compute_totals(conn, row["record_id"])
            conn.commit()
            output_json({"status": "ok", "message": f"食物条目已删除: {row['food_name']}"})
        else:
            row = conn.execute("SELECT * FROM diet_records WHERE id=? AND is_deleted=0", (args.id,)).fetchone()
            if not row:
                output_json({"status": "error", "message": f"未找到餐次记录: {args.id}"})
                return
            conn.execute("UPDATE diet_records SET is_deleted=1 WHERE id=?", (args.id,))
            conn.execute("UPDATE diet_items SET is_deleted=1 WHERE record_id=?", (args.id,))
            conn.commit()
            meal_name = MEAL_TYPE_NAMES.get(row["meal_type"], row["meal_type"])
            output_json({"status": "ok", "message": f"已删除{row['meal_date']}{meal_name}记录"})


def daily_summary(args):
    """某日营养摘要（总热量/三大营养素）。"""
    ensure_db()
    conn = get_connection()
    try:
        try:
            date = validate_date(args.date, "日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        m = get_member_or_error(conn, args.member_id)
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        records = conn.execute(
            "SELECT * FROM diet_records WHERE member_id=? AND meal_date=? AND is_deleted=0 ORDER BY meal_time",
            (args.member_id, date)
        ).fetchall()
        records = rows_to_list(records)

        # Batch-fetch all diet_items for the day's records in one query
        record_ids = [rec["id"] for rec in records]
        items_by_record = {rid: [] for rid in record_ids}
        if record_ids:
            placeholders = ",".join("?" for _ in record_ids)
            all_items = conn.execute(
                f"SELECT record_id, food_name, calories FROM diet_items WHERE record_id IN ({placeholders}) AND is_deleted=0",
                record_ids
            ).fetchall()
            for item in rows_to_list(all_items):
                items_by_record[item["record_id"]].append(
                    {"food_name": item["food_name"], "calories": item["calories"]}
                )

        totals = {"calories": 0, "protein": 0, "fat": 0, "carbs": 0, "fiber": 0}
        meals = []
        for rec in records:
            totals["calories"] += rec["total_calories"] or 0
            totals["protein"] += rec["total_protein"] or 0
            totals["fat"] += rec["total_fat"] or 0
            totals["carbs"] += rec["total_carbs"] or 0
            totals["fiber"] += rec["total_fiber"] or 0

            meals.append({
                "meal_type": rec["meal_type"],
                "meal_type_name": MEAL_TYPE_NAMES.get(rec["meal_type"], rec["meal_type"]),
                "calories": rec["total_calories"] or 0,
                "items": items_by_record.get(rec["id"], []),
            })

        # Round totals
        for k in ("protein", "fat", "carbs", "fiber"):
            totals[k] = round(totals[k], 1)

        # Macronutrient ratio
        total_macro_g = totals["protein"] + totals["fat"] + totals["carbs"]
        ratio = {}
        if total_macro_g > 0:
            ratio = {
                "protein_pct": round(totals["protein"] / total_macro_g * 100, 1),
                "fat_pct": round(totals["fat"] / total_macro_g * 100, 1),
                "carbs_pct": round(totals["carbs"] / total_macro_g * 100, 1),
            }

        output_json({
            "status": "ok",
            "member_name": m["name"],
            "date": date,
            "meal_count": len(meals),
            "meals": meals,
            "totals": totals,
            "macro_ratio": ratio,
        })
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="饮食记录管理")
    sub = parser.add_subparsers(dest="command", required=True)

    # add-meal
    p_add = sub.add_parser("add-meal")
    p_add.add_argument("--member-id", required=True)
    p_add.add_argument("--meal-type", required=True, help=f"餐次: {', '.join(VALID_MEAL_TYPES)}")
    p_add.add_argument("--meal-date", required=True, help="日期 YYYY-MM-DD")
    p_add.add_argument("--meal-time", default=None, help="时间 HH:MM")
    p_add.add_argument("--note", default=None)
    p_add.add_argument("--items", default=None, help="食物条目 JSON 数组")

    # add-item
    p_item = sub.add_parser("add-item")
    p_item.add_argument("--record-id", required=True, help="餐次记录 ID")
    p_item.add_argument("--food-name", required=True, help="食物名称")
    p_item.add_argument("--amount", type=float, default=None, help="数量")
    p_item.add_argument("--unit", default=None, help="单位（g/ml/份/个）")
    p_item.add_argument("--calories", type=float, default=None, help="热量 kcal")
    p_item.add_argument("--protein", type=float, default=None, help="蛋白质 g")
    p_item.add_argument("--fat", type=float, default=None, help="脂肪 g")
    p_item.add_argument("--carbs", type=float, default=None, help="碳水 g")
    p_item.add_argument("--fiber", type=float, default=None, help="膳食纤维 g")
    p_item.add_argument("--note", default=None)

    # list
    p_list = sub.add_parser("list")
    p_list.add_argument("--member-id", required=True)
    p_list.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD")
    p_list.add_argument("--start-date", default=None)
    p_list.add_argument("--end-date", default=None)
    p_list.add_argument("--meal-type", default=None)
    p_list.add_argument("--limit", default=None)

    # delete
    p_del = sub.add_parser("delete")
    p_del.add_argument("--id", required=True)
    p_del.add_argument("--type", default="record", choices=["record", "item"], help="删除类型")

    # daily-summary
    p_sum = sub.add_parser("daily-summary")
    p_sum.add_argument("--member-id", required=True)
    p_sum.add_argument("--date", required=True, help="日期 YYYY-MM-DD")

    args = parser.parse_args()
    commands = {
        "add-meal": add_meal,
        "add-item": add_item,
        "list": list_meals,
        "delete": delete_record,
        "daily-summary": daily_summary,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
