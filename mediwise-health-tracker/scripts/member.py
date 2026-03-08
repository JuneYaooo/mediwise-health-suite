"""Family member management for MediWise Health Tracker."""

from __future__ import annotations

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from health_db import ensure_db, get_connection, generate_id, now_iso, row_to_dict, rows_to_list, output_json, is_api_mode, transaction, verify_member_ownership
from validators import validate_date_optional
import api_client


def add_member(args):
    if is_api_mode():
        data = {"name": args.name, "relation": args.relation}
        for field in ["gender", "birth_date", "blood_type", "allergies",
                       "medical_history", "phone", "emergency_contact", "emergency_phone",
                       "custom_metric_ranges", "timezone"]:
            val = getattr(args, field, None)
            if val is not None:
                data[field] = val
        try:
            result = api_client.add_member(data)
            output_json({"status": "ok", "message": f"已添加成员: {args.name}", "member": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        try:
            args.birth_date = validate_date_optional(getattr(args, 'birth_date', None), "出生日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        member_id = generate_id()
        ts = now_iso()
        owner_id = getattr(args, 'owner_id', None)
        conn.execute(
            """INSERT INTO members (id, name, relation, gender, birth_date, blood_type,
               allergies, medical_history, phone, emergency_contact, emergency_phone,
               custom_metric_ranges, timezone, owner_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (member_id, args.name, args.relation, args.gender, args.birth_date,
             args.blood_type, args.allergies, args.medical_history, args.phone,
             args.emergency_contact, args.emergency_phone,
             getattr(args, 'custom_metric_ranges', None), getattr(args, 'timezone', None),
             owner_id, ts, ts)
        )
        conn.commit()
        member = row_to_dict(conn.execute("SELECT * FROM members WHERE id=?", (member_id,)).fetchone())
        output_json({"status": "ok", "message": f"已添加成员: {args.name}", "member": member})


def list_members(args):
    if is_api_mode():
        try:
            result = api_client.list_members()
            members = result if isinstance(result, list) else result.get("members", [])
            output_json({"status": "ok", "count": len(members), "members": members})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        owner_id = getattr(args, 'owner_id', None)
        if owner_id:
            rows = conn.execute("SELECT * FROM members WHERE is_deleted=0 AND owner_id=? ORDER BY created_at", (owner_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM members WHERE is_deleted=0 ORDER BY created_at").fetchall()
        members = rows_to_list(rows)
        output_json({"status": "ok", "count": len(members), "members": members})
    finally:
        conn.close()


def get_member(args):
    if is_api_mode():
        try:
            result = api_client.get_member(args.id)
            output_json({"status": "ok", "member": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM members WHERE id=? AND is_deleted=0", (args.id,)).fetchone()
        if not row:
            output_json({"status": "error", "message": f"未找到成员: {args.id}"})
            return
        owner_id = getattr(args, 'owner_id', None)
        if not verify_member_ownership(conn, args.id, owner_id):
            output_json({"status": "error", "message": f"未找到成员: {args.id}"})
            return
        output_json({"status": "ok", "member": row_to_dict(row)})
    finally:
        conn.close()


def update_member(args):
    if is_api_mode():
        data = {}
        for field in ["name", "relation", "gender", "birth_date", "blood_type",
                       "allergies", "medical_history", "phone", "emergency_contact", "emergency_phone",
                       "custom_metric_ranges", "timezone"]:
            val = getattr(args, field.replace("-", "_"), None)
            if val is not None:
                data[field] = val
        if not data:
            output_json({"status": "error", "message": "未指定要更新的字段"})
            return
        try:
            result = api_client.update_member(args.id, data)
            output_json({"status": "ok", "message": "成员信息已更新", "member": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        row = conn.execute("SELECT * FROM members WHERE id=? AND is_deleted=0", (args.id,)).fetchone()
        if not row:
            output_json({"status": "error", "message": f"未找到成员: {args.id}"})
            return

        owner_id = getattr(args, 'owner_id', None)
        if not verify_member_ownership(conn, args.id, owner_id):
            output_json({"status": "error", "message": f"未找到成员: {args.id}"})
            return

        try:
            if getattr(args, 'birth_date', None) is not None:
                args.birth_date = validate_date_optional(args.birth_date, "出生日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        fields = []
        values = []
        for field in ["name", "relation", "gender", "birth_date", "blood_type",
                       "allergies", "medical_history", "phone", "emergency_contact", "emergency_phone",
                       "custom_metric_ranges", "timezone"]:
            val = getattr(args, field.replace("-", "_"), None)
            if val is not None:
                fields.append(f"{field}=?")
                values.append(val)

        if not fields:
            output_json({"status": "error", "message": "未指定要更新的字段"})
            return

        fields.append("updated_at=?")
        values.append(now_iso())
        values.append(args.id)

        conn.execute(f"UPDATE members SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()
        member = row_to_dict(conn.execute("SELECT * FROM members WHERE id=?", (args.id,)).fetchone())
        output_json({"status": "ok", "message": "成员信息已更新", "member": member})


def delete_member(args):
    if is_api_mode():
        try:
            api_client.delete_member(args.id)
            output_json({"status": "ok", "message": f"已删除成员: {args.id}"})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        row = conn.execute("SELECT * FROM members WHERE id=? AND is_deleted=0", (args.id,)).fetchone()
        if not row:
            output_json({"status": "error", "message": f"未找到成员: {args.id}"})
            return
        owner_id = getattr(args, 'owner_id', None)
        if not verify_member_ownership(conn, args.id, owner_id):
            output_json({"status": "error", "message": f"未找到成员: {args.id}"})
            return
        conn.execute("UPDATE members SET is_deleted=1, updated_at=? WHERE id=?", (now_iso(), args.id))
        conn.commit()
        output_json({"status": "ok", "message": f"已删除成员: {row['name']}"})


def main():
    parser = argparse.ArgumentParser(description="家庭成员管理")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add")
    p_add.add_argument("--name", required=True)
    p_add.add_argument("--relation", required=True, help="与用户的关系: 本人/父亲/母亲/配偶/子女/其他")
    p_add.add_argument("--gender", default=None)
    p_add.add_argument("--birth-date", default=None)
    p_add.add_argument("--blood-type", default=None)
    p_add.add_argument("--allergies", default=None)
    p_add.add_argument("--medical-history", default=None)
    p_add.add_argument("--phone", default=None)
    p_add.add_argument("--emergency-contact", default=None)
    p_add.add_argument("--emergency-phone", default=None)
    p_add.add_argument("--custom-metric-ranges", default=None)
    p_add.add_argument("--timezone", default=None)
    p_add.add_argument("--owner-id", default=None)

    # list
    p_list = sub.add_parser("list")
    p_list.add_argument("--owner-id", default=None)

    # get
    p_get = sub.add_parser("get")
    p_get.add_argument("--id", required=True)
    p_get.add_argument("--owner-id", default=None)

    # update
    p_upd = sub.add_parser("update")
    p_upd.add_argument("--id", required=True)
    p_upd.add_argument("--name", default=None)
    p_upd.add_argument("--relation", default=None)
    p_upd.add_argument("--gender", default=None)
    p_upd.add_argument("--birth-date", default=None)
    p_upd.add_argument("--blood-type", default=None)
    p_upd.add_argument("--allergies", default=None)
    p_upd.add_argument("--medical-history", default=None)
    p_upd.add_argument("--phone", default=None)
    p_upd.add_argument("--emergency-contact", default=None)
    p_upd.add_argument("--emergency-phone", default=None)
    p_upd.add_argument("--custom-metric-ranges", default=None)
    p_upd.add_argument("--timezone", default=None)
    p_upd.add_argument("--owner-id", default=None)

    # delete
    p_del = sub.add_parser("delete")
    p_del.add_argument("--id", required=True)
    p_del.add_argument("--owner-id", default=None)

    args = parser.parse_args()
    commands = {"add": add_member, "list": list_members, "get": get_member,
                "update": update_member, "delete": delete_member}
    commands[args.command](args)


if __name__ == "__main__":
    main()
