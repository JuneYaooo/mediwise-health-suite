"""Quick Entry — 快速录入常见健康指标。

纯正则解析常见指标短文本（血压、血糖、心率、体温、体重、血氧），
无需调用 LLM，适用于简单数值录入场景。

Usage:
  python3 quick_entry.py parse --text "血压130/85 心率72" --member-id <id>
  python3 quick_entry.py parse-and-save --text "血压130/85 心率72" --member-id <id>
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(__file__))
import health_db


# ---------------------------------------------------------------------------
# Regex patterns for common health metrics
# ---------------------------------------------------------------------------

_PATTERNS = [
    # Blood pressure: 血压130/85, BP 130/85, 收缩压130 舒张压85
    {
        "type": "blood_pressure",
        "patterns": [
            r"(?:血压|BP|bp)\s*[:：]?\s*(\d{2,3})\s*[/／]\s*(\d{2,3})",
            r"收缩压\s*[:：]?\s*(\d{2,3})\s*[,，/／\s]+\s*舒张压\s*[:：]?\s*(\d{2,3})",
        ],
        "extract": lambda m: {
            "metric_type": "blood_pressure",
            "value": json.dumps({"systolic": int(m.group(1)), "diastolic": int(m.group(2))}),
            "unit": "mmHg",
        },
    },
    # Blood sugar: 血糖5.8, 空腹血糖6.1, 餐后血糖7.2
    {
        "type": "blood_sugar",
        "patterns": [
            r"(?:空腹|餐前)\s*(?:血糖|血糖值)\s*[:：]?\s*(\d{1,2}(?:\.\d{1,2})?)",
            r"(?:餐后|饭后)\s*(?:血糖|血糖值)\s*[:：]?\s*(\d{1,2}(?:\.\d{1,2})?)",
            r"(?:血糖|血糖值)\s*[:：]?\s*(\d{1,2}(?:\.\d{1,2})?)",
        ],
        "extract": lambda m: {
            "metric_type": "blood_sugar",
            "value": json.dumps(
                {"fasting": float(m.group(1))} if "空腹" in m.group(0) or "餐前" in m.group(0)
                else {"postprandial": float(m.group(1))} if "餐后" in m.group(0) or "饭后" in m.group(0)
                else {"value": float(m.group(1))}
            ),
            "unit": "mmol/L",
        },
    },
    # Heart rate: 心率72, 脉搏80, HR 72
    {
        "type": "heart_rate",
        "patterns": [
            r"(?:心率|脉搏|HR|hr)\s*[:：]?\s*(\d{2,3})",
        ],
        "extract": lambda m: {
            "metric_type": "heart_rate",
            "value": m.group(1),
            "unit": "bpm",
        },
    },
    # Temperature: 体温36.5, 37.2°C, 温度37.8
    {
        "type": "temperature",
        "patterns": [
            r"(?:体温|温度)\s*[:：]?\s*(\d{2}(?:\.\d{1,2})?)\s*(?:°?[Cc]|度)?",
        ],
        "extract": lambda m: {
            "metric_type": "temperature",
            "value": m.group(1),
            "unit": "°C",
        },
    },
    # Weight: 体重70kg, 体重70公斤, 70kg
    {
        "type": "weight",
        "patterns": [
            r"(?:体重|重量)\s*[:：]?\s*(\d{2,3}(?:\.\d{1,2})?)\s*(?:kg|公斤|千克|斤)?",
        ],
        "extract": lambda m: {
            "metric_type": "weight",
            "value": m.group(1),
            "unit": "kg",
        },
    },
    # Blood oxygen: 血氧98, SpO2 97, 氧饱和度96
    {
        "type": "blood_oxygen",
        "patterns": [
            r"(?:血氧|SpO2|spo2|氧饱和度)\s*[:：]?\s*(\d{2,3})\s*%?",
        ],
        "extract": lambda m: {
            "metric_type": "blood_oxygen",
            "value": m.group(1),
            "unit": "%",
        },
    },
]


def parse_text(text: str) -> dict:
    """Parse health metrics from free text using regex patterns.

    Returns:
        dict with 'records' list (compatible with smart_intake.py extract output)
        or 'fallback: true' if nothing matched.
    """
    records = []
    matched_spans = []
    today = date.today().isoformat()

    for spec in _PATTERNS:
        for pattern in spec["patterns"]:
            for m in re.finditer(pattern, text):
                # Skip if this span overlaps with an already-matched span
                start, end = m.span()
                overlap = False
                for ms, me in matched_spans:
                    if start < me and end > ms:
                        overlap = True
                        break
                if overlap:
                    continue

                matched_spans.append((start, end))
                data = spec["extract"](m)
                data["measured_at"] = today
                records.append({
                    "type": "health_metric",
                    "confidence": 1.0,
                    "data": data,
                })

    if not records:
        return {"fallback": True, "message": "未能从文本中识别到常见健康指标，建议使用 smart_intake.py extract 进行智能提取"}

    return {
        "records": records,
        "method": "regex",
        "source_summary": f"从文本中快速提取了 {len(records)} 条健康指标",
    }


def parse_and_save(text: str, member_id: str) -> dict:
    """Parse health metrics and save them directly to the database.

    Returns parse result with save status.
    """
    import health_metric

    result = parse_text(text)

    if result.get("fallback"):
        return result

    save_results = []
    for rec in result["records"]:
        data = rec["data"]
        try:
            args = argparse.Namespace(
                member_id=member_id,
                type=data["metric_type"],
                value=data["value"],
                measured_at=data.get("measured_at"),
                note=f"快速录入: {text[:100]}",
            )
            # Call add_metric and capture output
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                health_metric.add_metric(args)
            output = buf.getvalue().strip()
            if output:
                save_result = json.loads(output)
                save_results.append({"status": "ok", "data": save_result})
            else:
                save_results.append({"status": "ok"})
        except Exception as e:
            save_results.append({"status": "error", "message": str(e)})

    ok_count = sum(1 for r in save_results if r["status"] == "ok")
    result["saved"] = True
    result["save_results"] = save_results
    result["save_summary"] = f"成功保存 {ok_count}/{len(save_results)} 条记录"

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="快速录入 — 正则解析常见健康指标")
    sub = parser.add_subparsers(dest="command", required=True)

    p_parse = sub.add_parser("parse", help="解析文本中的健康指标（不保存）")
    p_parse.add_argument("--text", required=True, help="待解析的文本")
    p_parse.add_argument("--member-id", required=True, help="成员 ID")
    p_parse.add_argument("--owner-id", default=None, help="所有者 ID")

    p_save = sub.add_parser("parse-and-save", help="解析并保存健康指标")
    p_save.add_argument("--text", required=True, help="待解析的文本")
    p_save.add_argument("--member-id", required=True, help="成员 ID")
    p_save.add_argument("--owner-id", default=None, help="所有者 ID")

    args = parser.parse_args()

    if args.command == "parse":
        result = parse_text(args.text)
        health_db.output_json(result)
    elif args.command == "parse-and-save":
        health_db.ensure_db()
        conn = health_db.get_connection()
        try:
            if not health_db.verify_member_ownership(conn, args.member_id, args.owner_id):
                health_db.output_json({"error": f"无权访问成员: {args.member_id}"})
                return
        finally:
            conn.close()
        result = parse_and_save(args.text, args.member_id)
        health_db.output_json(result)


if __name__ == "__main__":
    main()
