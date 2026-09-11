"""饮食记录 CRUD 与每日摘要。"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import os

_logger = logging.getLogger(__name__)

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from path_setup import setup_mediwise_path
setup_mediwise_path()

from health_db import (
    ensure_db,
    get_medical_connection,
    get_lifestyle_connection,
    generate_id,
    now_iso,
    row_to_dict,
    rows_to_list,
    output_json,
    transaction,
    verify_member_ownership,
)
from validators import validate_date, validate_date_optional
from metric_utils import get_member_or_error

VALID_MEAL_TYPES = ["breakfast", "lunch", "dinner", "snack"]

_GRAM_UNITS = {'g', '克', 'gram', 'grams'}

# 记录级与条目级共用的营养列，顺序即响应中列出待补字段的顺序
_NUTRITION_FIELDS = ("calories", "protein", "fat", "carbs", "fiber")

# diet_items 列名 → food_lookup 结果字段名
_SOURCE_FIELDS = {
    "calories": "kcal",
    "protein": "protein",
    "fat": "fat",
    "carbs": "carbs",
    "fiber": "fiber",
}

# 未解析条目的 note 前缀，对齐既有的 [自动填充] 惯例。
# 落库的人文标记：NULL 是给机器看的信号，note 是给人看的。
_UNRESOLVED_NOTES = {
    "unavailable": "[未解析营养] 未配置食物数据源，营养值未知",
    "not_found": "[未解析营养] 数据源中未找到该食物，营养值未知",
    "error": "[未解析营养] 数据源查询失败，营养值未知",
    "source_missing_field": "[未解析营养] 数据源命中但缺少热量等关键字段",
}

# 给宿主 Agent 转述用户的一句话，按未解析原因区分措辞——
# "去配置数据源"和"这个食物不在库里"需要问用户的事情完全不同。
_ACTION_REQUIRED = {
    "unavailable": (
        "请向用户索取包装营养标签（每 100g 或每份的热量/蛋白质/脂肪/碳水/膳食纤维），"
        "或由配置 Agent 在取得用户同意后启用数据源（本地数据包 / USDA_API_KEY / "
        "OPENFOODFACTS_ENABLED=1），然后用 add-item 补全。"
    ),
    "not_found": (
        "数据源本身可用，但其中没有这些食物。"
        "请向用户索取对应食物的营养标签，或用 add-item 补录已知营养值。"
    ),
    "error": "营养数据源查询失败，请稍后重试；确认数据源可用后再补录。",
    "source_missing_field": (
        "数据源命中了该食物，但缺少热量等关键字段。"
        "请向用户核对包装营养标签后补录。"
    ),
}


def _fmt_kcal(v):
    """未知热量渲染为 —，绝不把 None 印成 0。"""
    if v is None:
        return "—"
    return f"{v:g}"


def _autofill_item_nutrition(item: dict) -> tuple[dict, dict]:
    """解析条目的营养值，返回 (item, verdict)。

    verdict 形如 {'reason': ...}，reason 取值：
      provided             — 调用方已给出热量，不查询
      resolved             — 从数据源解析成功
      unavailable          — 未配置任何数据源
      not_found            — 数据源可用，但没有这个食物
      error                — 已配置的来源查询失败
      source_missing_field — 命中但缺热量等关键字段

    绝不用 0 代替未知：解析不到就不写营养键，由调用方落 NULL。
    0 只能来自调用方的显式断言（如水、黑咖啡）。
    """
    if item.get('calories') is not None:
        return item, {'reason': 'provided'}
    food_name = item.get('food_name', '')
    if not food_name:
        return item, {'reason': 'not_found', 'reason_text': '食物名称为空'}

    try:
        import food_lookup as _fl
        found = _fl.lookup(food_name)
    except Exception as e:
        _logger.warning("food_lookup lookup failed for '%s': %s", food_name, e)
        return item, {'reason': 'error', 'reason_text': str(e)}

    if found.get('status') != 'ok' or not found.get('result'):
        status = found.get('status')
        if status not in _UNRESOLVED_NOTES:
            status = 'not_found'
        return item, {'reason': status, 'reason_text': found.get('message', '')}

    result = found['result']
    # Scale per-100g sources by amount if user specified grams
    amount = item.get('amount')
    unit = (item.get('unit') or '').lower().strip()
    scale = 1.0
    if result.get('per') == '100g' and amount and unit in _GRAM_UNITS:
        scale = float(amount) / 100.0

    item = dict(item)
    for col, src in _SOURCE_FIELDS.items():
        v = result.get(src)
        item[col] = round(v * scale, 1) if v is not None else None

    # 命中但热量为空 —— 不能假装解析成功。已知的其余字段照常保留。
    if item.get('calories') is None:
        return item, {'reason': 'source_missing_field'}

    source_name = result.get('source_name', result.get('source', ''))
    if item.get('note'):
        item['note'] = f"[自动填充] {item['note']}"
    else:
        item['note'] = f"[自动填充] 营养数据来源: {source_name}"
    return item, {'reason': 'resolved'}

MEAL_TYPE_NAMES = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "dinner": "晚餐",
    "snack": "加餐",
}


def _parse_items(items_json):
    """Parse and validate items JSON array.

    返回 (items, unresolved)。unresolved 是未能解析营养的条目清单，
    每项带 index/food_name/amount/unit/reason/reason_text，供响应透出。
    """
    if not items_json:
        return [], []
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

    resolved_items = []
    unresolved = []
    for i, item in enumerate(items):
        filled, verdict = _autofill_item_nutrition(item)
        reason = verdict.get('reason')
        if reason not in ('provided', 'resolved'):
            filled = dict(filled)
            if not filled.get('note'):
                filled['note'] = _UNRESOLVED_NOTES.get(reason, _UNRESOLVED_NOTES['not_found'])
            unresolved.append({
                "index": i,
                "food_name": item.get("food_name", ""),
                "amount": item.get("amount"),
                "unit": item.get("unit"),
                "reason": reason,
                **({'reason_text': verdict['reason_text']} if verdict.get('reason_text') else {}),
            })
        resolved_items.append(filled)
    return resolved_items, unresolved


def _nutrition_summary(record, known, unresolved):
    """构造响应的营养解析契约字段。

    nutrition_status 只以热量为准，且描述的是**记录**而非单次操作——
    add_item 追加一个已解析条目时，记录里原有的未解析条目依然存在。
    record.total_calories 正是下游唯一能看到的信号，故以它为准：
      resolved   — 记录级热量已知
      partial    — 记录级热量未知，但至少有一个条目已知
      unresolved — 所有条目热量都未知
    nutrition_fields_pending 列出其余为 NULL 的记录级总计——只给了热量、
    没给 fiber 的条目不应把整体判成"未解析"。
    """
    if record.get("total_calories") is not None:
        status = "resolved"
    elif known:
        status = "partial"
    else:
        status = "unresolved"

    pending = [c for c in _NUTRITION_FIELDS if record.get(f"total_{c}") is None]

    summary = {
        "nutrition_status": status,
        "nutrition_fields_pending": pending,
        "unresolved_items": unresolved,
    }
    if status != "resolved":
        # 去重后拼接：一餐里可能同时存在"没有数据源"和"库里没这个食物"
        seen = []
        for u in unresolved:
            action = _ACTION_REQUIRED.get(u["reason"])
            if action and action not in seen:
                seen.append(action)
        summary["action_required"] = " ".join(seen)
    return summary


def _meal_message(member_name, meal_date, meal_name, items, record, summary):
    """如实描述这次记录——未解析时绝不印出 "共0.0kcal"。"""
    head = f"已记录{member_name}的{meal_date}{meal_name}（{len(items)}个食物"
    status = summary["nutrition_status"]
    if status == "resolved":
        return f"{head}，共 {_fmt_kcal(record['total_calories'])}kcal）"
    if status == "unresolved":
        return f"{head}）。营养数据未解析，热量记为未知（未按 0 计）。"
    known = sum(it["calories"] for it in items if it.get("calories") is not None)
    return (
        f"{head}，共 {len(summary['unresolved_items'])} 个未解析营养数据）。"
        f"已知部分合计 {_fmt_kcal(known)}kcal，实际热量高于该值。"
    )


def _compute_totals(conn, record_id):
    """Recompute and update totals for a diet record from its items.

    未知（NULL）逐字段向上传播：只要有一个条目缺该项，记录级该项即 NULL。
    部分和会静默低估（300 已知 + 未知 报成 300 会被读成真实的 300），
    比"未知"更危险。空记录仍为 0（空和，数学上正确）。
    """
    rows = conn.execute(
        "SELECT calories, protein, fat, carbs, fiber FROM diet_items WHERE record_id=? AND is_deleted=0",
        (record_id,)
    ).fetchall()
    totals = {}
    for col in _NUTRITION_FIELDS:
        vals = [r[col] for r in rows]
        if any(v is None for v in vals):
            totals[f"total_{col}"] = None
        else:
            s = sum(vals)
            # 保持既有约定：total_calories 不取整，其余四项取一位小数
            totals[f"total_{col}"] = s if col == "calories" else round(s, 1)
    conn.execute(
        """UPDATE diet_records SET total_calories=?, total_protein=?, total_fat=?, total_carbs=?, total_fiber=?
           WHERE id=?""",
        (totals["total_calories"], totals["total_protein"], totals["total_fat"],
         totals["total_carbs"], totals["total_fiber"], record_id)
    )
    return totals


def add_meal(args):
    """添加一餐记录（含多个食物条目）。"""
    ensure_db()

    with transaction(domain="medical") as medical_conn:
        m = get_member_or_error(medical_conn, args.member_id)
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return
        if not verify_member_ownership(medical_conn, args.member_id, args.owner_id):
            output_json({"status": "error", "message": "无权访问该成员"})
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
        items, unresolved = _parse_items(args.items)
    except (ValueError, json.JSONDecodeError) as e:
        output_json({"status": "error", "message": f"食物条目格式错误: {e}"})
        return

    with transaction(domain="lifestyle") as conn:
        # Re-verify member still exists before writing (reduces TOCTOU window)
        member_check = get_medical_connection()
        try:
            if not member_check.execute(
                "SELECT 1 FROM members WHERE id=? AND is_deleted=0", (args.member_id,)
            ).fetchone():
                output_json({"status": "error", "message": f"成员已不存在: {args.member_id}"})
                return
        finally:
            member_check.close()

        record_id = generate_id()
        # 总计先置 NULL，随即由 _compute_totals 按条目重算覆盖
        conn.execute(
            """INSERT INTO diet_records
               (id, member_id, meal_type, meal_date, meal_time, total_calories, total_protein, total_fat, total_carbs, total_fiber, note, created_at, is_deleted)
               VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, NULL, ?, ?, 0)""",
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
                 item.get("calories"), item.get("protein"), item.get("fat"),
                 item.get("carbs"), item.get("fiber"),
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
    known = sum(1 for it in items if it.get("calories") is not None)
    summary = _nutrition_summary(record, known, unresolved)
    payload = {
        "status": "ok",
        "message": _meal_message(m['name'], meal_date, meal_name, items, record, summary),
        "record": record,
    }
    payload.update(summary)
    output_json(payload)


def add_item(args):
    """向已有餐次追加食物条目。"""
    ensure_db()
    with transaction(domain="lifestyle") as conn:
        record = conn.execute(
            "SELECT * FROM diet_records WHERE id=? AND is_deleted=0", (args.record_id,)
        ).fetchone()
        if not record:
            output_json({"status": "error", "message": f"未找到餐次记录: {args.record_id}"})
            return

        medical_conn = get_medical_connection()
        try:
            if not verify_member_ownership(medical_conn, record["member_id"], args.owner_id):
                output_json({"status": "error", "message": "无权访问该餐次记录"})
                return
        finally:
            medical_conn.close()
        if not args.food_name:
            output_json({"status": "error", "message": "食物名称不能为空"})
            return

        # 仅在调用方未给出热量时解析。--calories 0 是显式断言（如水），不查询。
        unresolved = []
        if args.calories is None:
            _filled, _verdict = _autofill_item_nutrition({
                'food_name': args.food_name,
                'amount': args.amount,
                'unit': args.unit,
            })
            args.calories = _filled.get('calories')
            args.protein = _filled.get('protein')
            args.fat = _filled.get('fat')
            args.carbs = _filled.get('carbs')
            args.fiber = _filled.get('fiber')
            args.note = args.note or _filled.get('note')
            _reason = _verdict.get('reason')
            if _reason not in ('provided', 'resolved'):
                if not args.note:
                    args.note = _UNRESOLVED_NOTES.get(_reason, _UNRESOLVED_NOTES['not_found'])
                unresolved.append({
                    "index": 0,
                    "food_name": args.food_name,
                    "amount": args.amount,
                    "unit": args.unit,
                    "reason": _reason,
                    **({'reason_text': _verdict['reason_text']} if _verdict.get('reason_text') else {}),
                })

        item_id = generate_id()
        conn.execute(
            """INSERT INTO diet_items
               (id, record_id, food_name, amount, unit, calories, protein, fat, carbs, fiber, note, created_at, is_deleted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (item_id, args.record_id, args.food_name,
             args.amount, args.unit,
             args.calories, args.protein, args.fat,
             args.carbs, args.fiber,
             args.note, now_iso())
        )

        _compute_totals(conn, args.record_id)
        conn.commit()

        item = row_to_dict(conn.execute("SELECT * FROM diet_items WHERE id=?", (item_id,)).fetchone())
        record_row = row_to_dict(conn.execute(
            "SELECT * FROM diet_records WHERE id=?", (args.record_id,)
        ).fetchone())
        # 状态描述整条记录：记录里可能还有别的未解析条目
        stats = conn.execute(
            "SELECT SUM(CASE WHEN calories IS NOT NULL THEN 1 ELSE 0 END) AS known "
            "FROM diet_items WHERE record_id=? AND is_deleted=0", (args.record_id,)
        ).fetchone()
        summary = _nutrition_summary(record_row, stats["known"] or 0, unresolved)
        payload = {
            "status": "ok",
            "message": (
                f"已向餐次 {args.record_id} 添加食物: {args.food_name}"
                f"（{_fmt_kcal(item['calories'])}kcal）"
            ),
            "item": item,
            "record": record_row,
        }
        payload.update(summary)
        output_json(payload)


def list_meals(args):
    """查看某日/某段时间的饮食记录。"""
    ensure_db()
    medical_conn = get_medical_connection()
    try:
        if not verify_member_ownership(medical_conn, args.member_id, args.owner_id):
            output_json({"status": "error", "message": "无权访问该成员"})
            return
    finally:
        medical_conn.close()
    conn = get_lifestyle_connection()
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
    with transaction(domain="lifestyle") as conn:
        if delete_type == "item":
            row = conn.execute(
                """SELECT di.*, dr.member_id
                   FROM diet_items di
                   JOIN diet_records dr ON dr.id=di.record_id
                   WHERE di.id=? AND di.is_deleted=0 AND dr.is_deleted=0""",
                (args.id,)
            ).fetchone()
            if not row:
                output_json({"status": "error", "message": f"未找到食物条目: {args.id}"})
                return

            medical_conn = get_medical_connection()
            try:
                if not verify_member_ownership(medical_conn, row["member_id"], args.owner_id):
                    output_json({"status": "error", "message": "无权访问该食物条目"})
                    return
            finally:
                medical_conn.close()
            conn.execute("UPDATE diet_items SET is_deleted=1 WHERE id=?", (args.id,))
            _compute_totals(conn, row["record_id"])
            conn.commit()
            output_json({"status": "ok", "message": f"食物条目已删除: {row['food_name']}"})
        else:
            row = conn.execute("SELECT * FROM diet_records WHERE id=? AND is_deleted=0", (args.id,)).fetchone()
            if not row:
                output_json({"status": "error", "message": f"未找到餐次记录: {args.id}"})
                return

            medical_conn = get_medical_connection()
            try:
                if not verify_member_ownership(medical_conn, row["member_id"], args.owner_id):
                    output_json({"status": "error", "message": "无权访问该餐次记录"})
                    return
            finally:
                medical_conn.close()
            conn.execute("UPDATE diet_records SET is_deleted=1 WHERE id=?", (args.id,))
            conn.execute("UPDATE diet_items SET is_deleted=1 WHERE record_id=?", (args.id,))
            conn.commit()
            meal_name = MEAL_TYPE_NAMES.get(row["meal_type"], row["meal_type"])
            output_json({"status": "ok", "message": f"已删除{row['meal_date']}{meal_name}记录"})


def daily_summary(args):
    """某日营养摘要（总热量/三大营养素）。"""
    ensure_db()
    conn = get_lifestyle_connection()
    try:
        try:
            date = validate_date(args.date, "日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        medical_conn = get_medical_connection()
        try:
            m = get_member_or_error(medical_conn, args.member_id)
            if not m:
                output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
                return
            if not verify_member_ownership(medical_conn, args.member_id, args.owner_id):
                output_json({"status": "error", "message": "无权访问该成员"})
                return
        finally:
            medical_conn.close()
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

        # 逐字段独立传播未知：当日任一条记录该字段为 NULL，合计即为 NULL。
        # 部分和（300 已知 + 未知）会被下游读成真实的 300，比"未知"更糟。
        # 当日无记录时 any([]) 为 False、合计为 0——"没记"由 meal_count 表达。
        totals = {}
        for f in _NUTRITION_FIELDS:
            vals = [rec[f"total_{f}"] for rec in records]
            if any(v is None for v in vals):
                totals[f] = None
            else:
                s = sum(vals)
                totals[f] = s if f == "calories" else round(s, 1)

        meals = []
        unresolved_records = 0
        for rec in records:
            if rec["total_calories"] is None:
                unresolved_records += 1
            meals.append({
                "meal_type": rec["meal_type"],
                "meal_type_name": MEAL_TYPE_NAMES.get(rec["meal_type"], rec["meal_type"]),
                "calories": rec["total_calories"],
                "items": items_by_record.get(rec["id"], []),
            })

        # 三大营养素比例：三者皆已知才算。任一为 NULL 时给出的是被未知拉歪的假比例。
        ratio = {}
        if all(totals[k] is not None for k in ("protein", "fat", "carbs")):
            total_macro_g = totals["protein"] + totals["fat"] + totals["carbs"]
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
            "unresolved_records": unresolved_records,
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
    p_add.add_argument("--items", default=None, help="食物条目 JSON 数组")
    p_add.add_argument("--note", default=None)
    p_add.add_argument("--owner-id", default=None)

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
    p_item.add_argument("--owner-id", default=None)

    # list
    p_list = sub.add_parser("list")
    p_list.add_argument("--member-id", required=True)
    p_list.add_argument("--date", default=None, help="指定日期 YYYY-MM-DD")
    p_list.add_argument("--start-date", default=None)
    p_list.add_argument("--end-date", default=None)
    p_list.add_argument("--meal-type", default=None)
    p_list.add_argument("--limit", type=int, default=None, help="最多返回条数")
    p_list.add_argument("--owner-id", default=None)

    # delete
    p_del = sub.add_parser("delete")
    p_del.add_argument("--id", required=True)
    p_del.add_argument("--type", default=None, help="删除类型: record（默认）或 item")
    p_del.add_argument("--owner-id", default=None)

    # daily-summary
    p_sum = sub.add_parser("daily-summary")
    p_sum.add_argument("--member-id", required=True)
    p_sum.add_argument("--date", required=True, help="日期 YYYY-MM-DD")
    p_sum.add_argument("--owner-id", default=None)

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
