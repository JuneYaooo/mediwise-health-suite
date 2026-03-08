"""Health metrics tracking for MediWise Health Tracker."""

from __future__ import annotations

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from health_db import ensure_db, get_connection, generate_id, now_iso, row_to_dict, rows_to_list, output_json, is_api_mode, transaction, verify_member_ownership, verify_record_ownership
from validators import validate_metric_value
import api_client

VALID_TYPES = [
    "blood_pressure", "blood_sugar", "heart_rate", "weight", "temperature", "blood_oxygen", "height",
    # 可穿戴设备指标
    "sleep", "steps", "stress", "calories",
    # 身体围度指标
    "waist", "hip", "chest", "arm", "thigh", "body_fat",
]


def add_metric(args):
    if is_api_mode():
        data = {
            "member_id": args.member_id,
            "metric_type": args.type,
            "value": args.value,
        }
        if args.measured_at:
            data["measured_at"] = args.measured_at
        if args.note:
            data["note"] = args.note
        try:
            result = api_client.add_metric(data)
            output_json({"status": "ok", "message": "健康指标已记录", "metric": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        if not verify_member_ownership(conn, args.member_id, getattr(args, 'owner_id', None)):
            output_json({"status": "error", "message": f"无权访问成员: {args.member_id}"})
            return
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        if args.type not in VALID_TYPES:
            output_json({"status": "error", "message": f"不支持的指标类型: {args.type}，支持: {', '.join(VALID_TYPES)}"})
            return

        # Validate value format and range
        try:
            value = validate_metric_value(args.type, args.value)
        except (ValueError, json.JSONDecodeError) as e:
            output_json({"status": "error", "message": str(e)})
            return

        metric_id = generate_id()
        measured_at = args.measured_at or now_iso()
        source = getattr(args, 'source', None) or 'manual'
        conn.execute(
            """INSERT INTO health_metrics (id, member_id, metric_type, value, measured_at, note, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (metric_id, args.member_id, args.type, value, measured_at, args.note, source, now_iso())
        )
        conn.commit()
        metric = row_to_dict(conn.execute("SELECT * FROM health_metrics WHERE id=?", (metric_id,)).fetchone())
        type_names = {
            "blood_pressure": "血压", "blood_sugar": "血糖", "heart_rate": "心率",
            "weight": "体重", "temperature": "体温", "blood_oxygen": "血氧", "height": "身高"
        }
        output_json({"status": "ok", "message": f"已记录{m['name']}的{type_names.get(args.type, args.type)}", "metric": metric})


def list_metrics(args):
    if is_api_mode():
        params = {"member_id": args.member_id}
        if args.type:
            params["metric_type"] = args.type
        if args.start_date:
            params["start_date"] = args.start_date
        if args.end_date:
            params["end_date"] = args.end_date
        if args.limit:
            params["limit"] = args.limit
        try:
            result = api_client.list_metrics(params)
            metrics = result if isinstance(result, list) else result.get("metrics", [])
            output_json({"status": "ok", "count": len(metrics), "metrics": metrics})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        if not verify_member_ownership(conn, args.member_id, getattr(args, 'owner_id', None)):
            output_json({"status": "error", "message": f"无权访问成员: {args.member_id}"})
            return
        sql = "SELECT * FROM health_metrics WHERE member_id=? AND is_deleted=0"
        params = [args.member_id]
        if args.type:
            if args.type not in VALID_TYPES:
                output_json({"status": "error", "message": f"不支持的指标类型: {args.type}"})
                return
            sql += " AND metric_type=?"
            params.append(args.type)
        if args.start_date:
            sql += " AND measured_at>=?"
            params.append(args.start_date)
        if args.end_date:
            sql += " AND measured_at<=?"
            params.append(args.end_date + " 23:59:59")
        sql += " ORDER BY measured_at DESC"
        if args.limit:
            sql += " LIMIT ?"
            params.append(int(args.limit))

        rows = conn.execute(sql, params).fetchall()
        metrics = rows_to_list(rows)
        # Parse blood_pressure JSON values for readability
        for m in metrics:
            if m["metric_type"] == "blood_pressure":
                try:
                    m["value_parsed"] = json.loads(m["value"])
                except (json.JSONDecodeError, TypeError):
                    pass
        output_json({"status": "ok", "count": len(metrics), "metrics": metrics})
    finally:
        conn.close()


def delete_metric(args):
    if is_api_mode():
        try:
            api_client.delete_metric(args.id)
            output_json({"status": "ok", "message": "指标记录已删除"})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        row = conn.execute("SELECT * FROM health_metrics WHERE id=? AND is_deleted=0", (args.id,)).fetchone()
        if not row:
            output_json({"status": "error", "message": f"未找到指标记录: {args.id}"})
            return
        if not verify_record_ownership(conn, "health_metrics", args.id, getattr(args, 'owner_id', None)):
            output_json({"status": "error", "message": f"无权访问指标记录: {args.id}"})
            return
        conn.execute("UPDATE health_metrics SET is_deleted=1 WHERE id=?", (args.id,))
        conn.commit()
        output_json({"status": "ok", "message": "指标记录已删除"})


def main():
    parser = argparse.ArgumentParser(description="健康指标管理")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("--member-id", required=True)
    p_add.add_argument("--owner-id", default=None)
    p_add.add_argument("--type", required=True, help=f"指标类型: {', '.join(VALID_TYPES)}")
    p_add.add_argument("--value", required=True, help="指标值，血压格式: {\"systolic\":130,\"diastolic\":85}")
    p_add.add_argument("--measured-at", default=None, help="测量时间 (YYYY-MM-DD HH:MM)")
    p_add.add_argument("--note", default=None)
    p_add.add_argument("--source", default="manual", help="数据来源: manual|huawei|zepp|gadgetbridge|openwearables")

    p_list = sub.add_parser("list")
    p_list.add_argument("--member-id", required=True)
    p_list.add_argument("--owner-id", default=None)
    p_list.add_argument("--type", default=None)
    p_list.add_argument("--start-date", default=None)
    p_list.add_argument("--end-date", default=None)
    p_list.add_argument("--limit", default=None)

    p_del = sub.add_parser("delete")
    p_del.add_argument("--id", required=True)
    p_del.add_argument("--owner-id", default=None)

    args = parser.parse_args()
    commands = {"add": add_metric, "list": list_metrics, "delete": delete_metric}
    commands[args.command](args)


if __name__ == "__main__":
    main()
