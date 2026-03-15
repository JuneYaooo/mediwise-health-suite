"""Physical checkup report interpretation and comparison for MediWise Health Tracker.

Provides structured extraction and historical comparison of medical checkup reports.
"""

from __future__ import annotations

import sys
import os
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

import health_db

# ---------------------------------------------------------------------------
# Reference ranges (~50 items)
# Keys are canonical Chinese names; values include min/max/unit,
# optionally gender-split with {"male": {...}, "female": {...}, "unit": ...}
# ---------------------------------------------------------------------------
NORMAL_RANGES = {
    # 血糖代谢
    "空腹血糖":        {"min": 3.9, "max": 6.1, "unit": "mmol/L"},
    "餐后2小时血糖":   {"min": 0,   "max": 7.8, "unit": "mmol/L"},
    "糖化血红蛋白":    {"min": 4.0, "max": 6.0, "unit": "%"},
    # 血脂四项
    "总胆固醇":        {"min": 0,   "max": 5.2, "unit": "mmol/L"},
    "甘油三酯":        {"min": 0,   "max": 1.7, "unit": "mmol/L"},
    "高密度脂蛋白":    {
        "male":   {"min": 1.0, "max": 99},
        "female": {"min": 1.3, "max": 99},
        "unit": "mmol/L",
    },
    "低密度脂蛋白":    {"min": 0,   "max": 3.4, "unit": "mmol/L"},
    # 肝功能
    "丙氨酸氨基转移酶": {"min": 0, "max": 40,  "unit": "U/L"},
    "天冬氨酸氨基转移酶": {"min": 0, "max": 40, "unit": "U/L"},
    "总胆红素":        {"min": 3.4, "max": 17.1, "unit": "μmol/L"},
    "直接胆红素":      {"min": 0,   "max": 6.8,  "unit": "μmol/L"},
    "间接胆红素":      {"min": 1.7, "max": 10.2, "unit": "μmol/L"},
    "碱性磷酸酶":      {"min": 40,  "max": 150,  "unit": "U/L"},
    "γ-谷氨酰转肽酶": {"min": 0,   "max": 50,   "unit": "U/L"},
    "总蛋白":          {"min": 64,  "max": 83,   "unit": "g/L"},
    "白蛋白":          {"min": 35,  "max": 55,   "unit": "g/L"},
    # 肾功能
    "肌酐":            {
        "male":   {"min": 53, "max": 106},
        "female": {"min": 44, "max": 97},
        "unit": "μmol/L",
    },
    "尿酸":            {
        "male":   {"min": 149, "max": 420},
        "female": {"min": 89,  "max": 357},
        "unit": "μmol/L",
    },
    "尿素氮":          {"min": 1.7, "max": 8.3, "unit": "mmol/L"},
    "胱抑素C":         {"min": 0.5, "max": 1.03,"unit": "mg/L"},
    # 血常规
    "血红蛋白":        {
        "male":   {"min": 130, "max": 175},
        "female": {"min": 115, "max": 150},
        "unit": "g/L",
    },
    "红细胞计数":      {
        "male":   {"min": 4.3, "max": 5.8},
        "female": {"min": 3.8, "max": 5.1},
        "unit": "×10¹²/L",
    },
    "白细胞计数":      {"min": 4.0, "max": 10.0, "unit": "×10⁹/L"},
    "中性粒细胞百分比":{"min": 50,  "max": 70,   "unit": "%"},
    "淋巴细胞百分比":  {"min": 20,  "max": 40,   "unit": "%"},
    "血小板计数":      {"min": 125, "max": 350,  "unit": "×10⁹/L"},
    "血细胞比容":      {
        "male":   {"min": 0.40, "max": 0.50},
        "female": {"min": 0.35, "max": 0.45},
        "unit": "L/L",
    },
    # 甲状腺
    "促甲状腺激素":    {"min": 0.27, "max": 4.2,  "unit": "mIU/L"},
    "游离三碘甲状腺原氨酸": {"min": 3.1, "max": 6.8, "unit": "pmol/L"},
    "游离甲状腺素":    {"min": 12.0, "max": 22.0, "unit": "pmol/L"},
    # 肿瘤标志物
    "癌胚抗原":        {"min": 0, "max": 5.0,   "unit": "ng/mL"},
    "甲胎蛋白":        {"min": 0, "max": 20.0,  "unit": "ng/mL"},
    "糖类抗原125":     {"min": 0, "max": 35.0,  "unit": "U/mL"},
    "糖类抗原19-9":    {"min": 0, "max": 37.0,  "unit": "U/mL"},
    "前列腺特异抗原":  {"min": 0, "max": 4.0,   "unit": "ng/mL"},
    # 其他
    "血压收缩压":      {"min": 90, "max": 130,  "unit": "mmHg"},
    "血压舒张压":      {"min": 60, "max": 80,   "unit": "mmHg"},
    "体重指数":        {"min": 18.5, "max": 24.0, "unit": "kg/m²"},
}

# Alias mapping: input name → canonical name
NAME_ALIASES = {
    "HbA1c":         "糖化血红蛋白",
    "A1C":           "糖化血红蛋白",
    "FBG":           "空腹血糖",
    "ALT":           "丙氨酸氨基转移酶",
    "GPT":           "丙氨酸氨基转移酶",
    "AST":           "天冬氨酸氨基转移酶",
    "GOT":           "天冬氨酸氨基转移酶",
    "TBIL":          "总胆红素",
    "DBIL":          "直接胆红素",
    "IBIL":          "间接胆红素",
    "ALP":           "碱性磷酸酶",
    "GGT":           "γ-谷氨酰转肽酶",
    "γ-GT":          "γ-谷氨酰转肽酶",
    "TP":            "总蛋白",
    "ALB":           "白蛋白",
    "SCr":           "肌酐",
    "Cr":            "肌酐",
    "UA":            "尿酸",
    "BUN":           "尿素氮",
    "CysC":          "胱抑素C",
    "Hb":            "血红蛋白",
    "HGB":           "血红蛋白",
    "RBC":           "红细胞计数",
    "WBC":           "白细胞计数",
    "NEU%":          "中性粒细胞百分比",
    "LYM%":          "淋巴细胞百分比",
    "PLT":           "血小板计数",
    "HCT":           "血细胞比容",
    "TSH":           "促甲状腺激素",
    "FT3":           "游离三碘甲状腺原氨酸",
    "FT4":           "游离甲状腺素",
    "CEA":           "癌胚抗原",
    "AFP":           "甲胎蛋白",
    "CA125":         "糖类抗原125",
    "CA19-9":        "糖类抗原19-9",
    "PSA":           "前列腺特异抗原",
    "TC":            "总胆固醇",
    "TG":            "甘油三酯",
    "HDL":           "高密度脂蛋白",
    "HDL-C":         "高密度脂蛋白",
    "LDL":           "低密度脂蛋白",
    "LDL-C":         "低密度脂蛋白",
    "BMI":           "体重指数",
}

# Item-to-category mapping
ITEM_CATEGORIES = {
    "空腹血糖": "血糖代谢", "餐后2小时血糖": "血糖代谢", "糖化血红蛋白": "血糖代谢",
    "总胆固醇": "血脂", "甘油三酯": "血脂", "高密度脂蛋白": "血脂", "低密度脂蛋白": "血脂",
    "丙氨酸氨基转移酶": "肝功能", "天冬氨酸氨基转移酶": "肝功能",
    "总胆红素": "肝功能", "直接胆红素": "肝功能", "间接胆红素": "肝功能",
    "碱性磷酸酶": "肝功能", "γ-谷氨酰转肽酶": "肝功能", "总蛋白": "肝功能", "白蛋白": "肝功能",
    "肌酐": "肾功能", "尿酸": "肾功能", "尿素氮": "肾功能", "胱抑素C": "肾功能",
    "血红蛋白": "血常规", "红细胞计数": "血常规", "白细胞计数": "血常规",
    "中性粒细胞百分比": "血常规", "淋巴细胞百分比": "血常规",
    "血小板计数": "血常规", "血细胞比容": "血常规",
    "促甲状腺激素": "甲状腺", "游离三碘甲状腺原氨酸": "甲状腺", "游离甲状腺素": "甲状腺",
    "癌胚抗原": "肿瘤标志物", "甲胎蛋白": "肿瘤标志物",
    "糖类抗原125": "肿瘤标志物", "糖类抗原19-9": "肿瘤标志物", "前列腺特异抗原": "肿瘤标志物",
    "血压收缩压": "体格检查", "血压舒张压": "体格检查", "体重指数": "体格检查",
}


def _canonical_name(raw_name: str) -> str:
    """Resolve raw indicator name to canonical Chinese name via alias map."""
    return NAME_ALIASES.get(raw_name, raw_name)


def _get_reference_range(canonical_name: str, gender: str | None):
    """Return (min, max, unit) for a canonical name, considering gender."""
    ref = NORMAL_RANGES.get(canonical_name)
    if ref is None:
        return None, None, None
    if "male" in ref:
        key = gender if gender in ("male", "female") else "male"
        sub = ref[key]
        return sub["min"], sub["max"], ref.get("unit", "")
    return ref.get("min"), ref.get("max"), ref.get("unit", "")


def _flag_value(value_str: str, lo, hi) -> str:
    """Assign flag: normal / attention / abnormal."""
    if lo is None or hi is None:
        return "unknown"
    try:
        val = float(str(value_str).replace(",", "").strip())
    except (ValueError, TypeError):
        return "unknown"
    delta_pct = max(abs(val - lo) / (lo if lo > 0 else 1), abs(val - hi) / (hi if hi > 0 else 1)) if lo > 0 or hi > 0 else 0
    if lo <= val <= hi:
        return "normal"
    # Within 20% outside range = attention, else abnormal
    bound = lo if val < lo else hi
    if bound > 0 and abs(val - bound) / bound <= 0.20:
        return "attention"
    return "abnormal"


def _build_explanation(canonical_name: str, flag: str, value_str: str, lo, hi, unit: str) -> str:
    if flag == "normal":
        return "正常范围内"
    if flag == "unknown":
        return "无参考范围"
    direction = "偏低" if lo is not None and _try_float(value_str, 0) < lo else "偏高"
    ref_str = f"{lo}-{hi} {unit}".strip() if lo is not None else ""
    severity = "轻度" if flag == "attention" else "明显"
    return f"{canonical_name}{direction}（参考值 {ref_str}），{severity}异常"


def _try_float(s, default=None):
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return default


def _parse_report_text(text: str, gender: str | None) -> dict:
    """
    Parse a plain-text checkup report into structured items.
    Uses LLM if available (via api_client), otherwise falls back to a simple
    keyword-scan approach that works without network access.
    """
    try:
        from api_client import call_llm
        prompt = f"""你是专业医学数据提取助手。请从以下体检报告文本中提取所有检验指标，
输出严格的JSON数组，每项格式：
{{"name": "指标名称", "value": "数值", "unit": "单位", "reference": "参考范围（原文）"}}

只输出JSON数组，不要其他文字。

报告内容：
{text}"""
        resp = call_llm(prompt, max_tokens=2000)
        items_raw = json.loads(resp)
    except Exception:
        # Fallback: simple regex-based extraction for common formats
        import re
        items_raw = []
        # Match patterns like: "空腹血糖  5.8  mmol/L  3.9-6.1"
        pattern = re.compile(
            r"([^\d\n]{2,20})\s+(\d+\.?\d*)\s*([a-zA-Z%μ×¹²⁹/Lg·]+)?\s*([0-9.<>~\-]+)?",
        )
        for m in pattern.finditer(text):
            name = m.group(1).strip().rstrip("：:")
            val = m.group(2)
            unit = (m.group(3) or "").strip()
            ref = (m.group(4) or "").strip()
            if name and val:
                items_raw.append({"name": name, "value": val, "unit": unit, "reference": ref})

    categories: dict[str, list] = {}
    for item in items_raw:
        raw_name = str(item.get("name", "")).strip()
        canonical = _canonical_name(raw_name)
        lo, hi, unit_ref = _get_reference_range(canonical, gender)
        val_str = str(item.get("value", "")).strip()
        ref_str = item.get("reference") or (f"{lo}-{hi}" if lo is not None else "")
        unit = item.get("unit") or unit_ref or ""
        flag = _flag_value(val_str, lo, hi)
        explanation = _build_explanation(canonical, flag, val_str, lo, hi, unit)
        cat = ITEM_CATEGORIES.get(canonical, "其他")

        entry = {
            "name": canonical,
            "value": val_str,
            "unit": unit,
            "reference": str(ref_str),
            "flag": flag,
            "explanation": explanation,
        }
        categories.setdefault(cat, []).append(entry)

    total = sum(len(v) for v in categories.values())
    normal_count = sum(1 for v in categories.values() for e in v if e["flag"] == "normal")
    attention_count = sum(1 for v in categories.values() for e in v if e["flag"] == "attention")
    abnormal_count = sum(1 for v in categories.values() for e in v if e["flag"] == "abnormal")
    key_concerns = [e["name"] + ("偏高" if _try_float(e["value"], 0) > (_get_reference_range(e["name"], gender)[1] or 999) else "偏低")
                    for v in categories.values() for e in v if e["flag"] == "abnormal"]

    return {
        "categories": categories,
        "summary": {
            "total_items": total,
            "normal_count": normal_count,
            "attention_count": attention_count,
            "abnormal_count": abnormal_count,
            "key_concerns": key_concerns[:10],
        },
    }


def _get_previous_checkup(conn, member_id, exclude_id=None):
    """Fetch the most recent previous checkup report items from lab_results."""
    q = """SELECT id, test_date, items FROM lab_results
           WHERE member_id=? AND test_name='体检报告' AND is_deleted=0"""
    params = [member_id]
    if exclude_id:
        q += " AND id != ?"
        params.append(exclude_id)
    q += " ORDER BY test_date DESC LIMIT 1"
    row = conn.execute(q, params).fetchone()
    if not row:
        return None, None
    try:
        return dict(row), json.loads(row["items"] or "{}")
    except (json.JSONDecodeError, TypeError):
        return dict(row), {}


def interpret(args):
    health_db.ensure_db()

    # Get report text
    text = None
    if getattr(args, "text", None):
        text = args.text
    elif getattr(args, "pdf", None):
        try:
            from smart_intake import _extract_text_from_pdf
            text = _extract_text_from_pdf(args.pdf)
        except Exception as e:
            health_db.output_json({"status": "error", "message": f"PDF 提取失败: {e}"})
            return
    elif getattr(args, "image", None):
        health_db.output_json({"status": "error", "message": "图片解析请使用 --text 参数提供提取后的文字"})
        return

    if not text:
        health_db.output_json({"status": "error", "message": "请通过 --text / --pdf 提供报告内容"})
        return

    gender = getattr(args, "gender", None)
    report_date = getattr(args, "report_date", None) or datetime.now().strftime("%Y-%m-%d")

    parsed = _parse_report_text(text, gender)

    # Fetch previous checkup for trend
    conn = health_db.get_medical_connection()
    try:
        prev_row, prev_data = _get_previous_checkup(conn, args.member_id)
    finally:
        conn.close()

    if prev_data and isinstance(prev_data, dict):
        prev_items = {}
        for cat_items in prev_data.get("categories", {}).values():
            for item in cat_items:
                prev_items[item["name"]] = item.get("value")

        for cat_items in parsed["categories"].values():
            for item in cat_items:
                prev_val = prev_items.get(item["name"])
                if prev_val is not None:
                    item["previous"] = str(prev_val)
                    curr_f = _try_float(item["value"])
                    prev_f = _try_float(prev_val)
                    if curr_f is not None and prev_f is not None:
                        item["trend"] = "up" if curr_f > prev_f else ("down" if curr_f < prev_f else "stable")
                    else:
                        item["trend"] = "unknown"

    # Save to lab_results if requested
    saved_id = None
    if getattr(args, "save", False):
        with health_db.transaction(domain="medical") as conn:
            m = conn.execute(
                "SELECT id FROM members WHERE id=? AND is_deleted=0", (args.member_id,)
            ).fetchone()
            if not m:
                health_db.output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
                return
            saved_id = health_db.generate_id()
            now = health_db.now_iso()
            conn.execute(
                """INSERT INTO lab_results
                   (id, member_id, test_name, test_date, items, source, created_at)
                   VALUES (?, ?, '体检报告', ?, ?, 'manual', ?)""",
                (saved_id, args.member_id, report_date,
                 json.dumps(parsed, ensure_ascii=False), now),
            )
            conn.commit()

    health_db.output_json({
        "status": "ok",
        "member_id": args.member_id,
        "report_date": report_date,
        "saved_id": saved_id,
        **parsed,
    })


def compare(args):
    health_db.ensure_db()

    conn = health_db.get_medical_connection()
    try:
        q = """SELECT id, test_date, items FROM lab_results
               WHERE member_id=? AND test_name='体检报告' AND is_deleted=0
               ORDER BY test_date DESC"""
        rows = conn.execute(q, (args.member_id,)).fetchall()
    finally:
        conn.close()

    if len(rows) < 2:
        health_db.output_json({
            "status": "error",
            "message": "历史体检报告不足2份，无法对比",
        })
        return

    def _pick_report(rows, date_str):
        if date_str:
            for r in rows:
                if r["test_date"] == date_str:
                    return dict(r)
            health_db.output_json({"status": "error", "message": f"未找到 {date_str} 的体检报告"})
            return None
        return dict(rows[0])

    report2 = _pick_report(rows, getattr(args, "date2", None))
    if not report2:
        return
    remaining = [r for r in rows if r["id"] != report2["id"]]
    if not remaining:
        health_db.output_json({"status": "error", "message": "历史体检报告不足2份，无法对比"})
        return
    report1 = _pick_report(remaining, getattr(args, "date1", None))
    if not report1:
        return

    def _extract_items(report_row):
        try:
            data = json.loads(report_row["items"] or "{}")
            result = {}
            for cat_items in data.get("categories", {}).values():
                for item in cat_items:
                    result[item["name"]] = item
            return result
        except (json.JSONDecodeError, TypeError):
            return {}

    items1 = _extract_items(report1)
    items2 = _extract_items(report2)

    all_names = sorted(set(items1) | set(items2))
    comparison = []
    for name in all_names:
        i1 = items1.get(name, {})
        i2 = items2.get(name, {})
        v1 = i1.get("value")
        v2 = i2.get("value")
        f1 = _try_float(v1)
        f2 = _try_float(v2)
        delta = round(f2 - f1, 4) if f1 is not None and f2 is not None else None
        direction = None
        if delta is not None:
            direction = "up" if delta > 0 else ("down" if delta < 0 else "stable")
        comparison.append({
            "name": name,
            "value_old": v1,
            "value_new": v2,
            "unit": i2.get("unit") or i1.get("unit", ""),
            "flag_old": i1.get("flag"),
            "flag_new": i2.get("flag"),
            "delta": delta,
            "direction": direction,
        })

    health_db.output_json({
        "status": "ok",
        "member_id": args.member_id,
        "report_old": {"id": report1["id"], "date": report1["test_date"]},
        "report_new": {"id": report2["id"], "date": report2["test_date"]},
        "comparison": comparison,
        "changed_count": sum(1 for c in comparison if c["direction"] in ("up", "down")),
    })


def main():
    parser = argparse.ArgumentParser(description="体检报告解读与对比")
    sub = parser.add_subparsers(dest="command", required=True)

    p_int = sub.add_parser("interpret", help="解读体检报告")
    p_int.add_argument("--member-id", required=True)
    p_int.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
    p_int.add_argument("--text", default=None, help="报告文字内容")
    p_int.add_argument("--pdf", default=None, help="PDF 文件路径")
    p_int.add_argument("--image", default=None, help="图片文件路径")
    p_int.add_argument("--report-date", default=None, help="报告日期 YYYY-MM-DD")
    p_int.add_argument("--save", action="store_true", help="保存到 lab_results")
    p_int.add_argument("--gender", default=None, choices=["male", "female"], help="性别（影响部分参考值）")

    p_cmp = sub.add_parser("compare", help="对比两份体检报告")
    p_cmp.add_argument("--member-id", required=True)
    p_cmp.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
    p_cmp.add_argument("--date1", default=None, help="较早报告日期 YYYY-MM-DD")
    p_cmp.add_argument("--date2", default=None, help="较新报告日期 YYYY-MM-DD")

    args = parser.parse_args()
    commands = {"interpret": interpret, "compare": compare}
    commands[args.command](args)


if __name__ == "__main__":
    main()
