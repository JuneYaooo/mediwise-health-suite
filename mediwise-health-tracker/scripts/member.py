"""Family member management for MediWise Health Suite."""

from __future__ import annotations

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from health_db import ensure_db, get_medical_connection, generate_id, now_iso, row_to_dict, rows_to_list, output_json, is_api_mode, transaction, verify_member_ownership
from validators import validate_date_optional
import api_client

# Whitelist of column names allowed in UPDATE statements for the members table.
# Values are always bound via ? placeholders; this set guards the column names.
_MEMBER_UPDATE_FIELDS = frozenset([
    "name", "relation", "gender", "birth_date", "blood_type",
    "allergies", "medical_history", "phone", "emergency_contact", "emergency_phone",
    "custom_metric_ranges", "timezone",
])


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
    with transaction(domain="medical") as conn:
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
    conn = get_medical_connection()
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
    conn = get_medical_connection()
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
    with transaction(domain="medical") as conn:
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
        for field in _MEMBER_UPDATE_FIELDS:
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

        # Column names are from _MEMBER_UPDATE_FIELDS (hardcoded whitelist); values via ?.
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
    with transaction(domain="medical") as conn:
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


_RELATION_ALIASES = {
    "我": "本人", "自己": "本人", "本人": "本人",
    "爸爸": "父亲", "爸": "父亲", "父亲": "父亲",
    "妈妈": "母亲", "妈": "母亲", "母亲": "母亲",
    "老公": "配偶", "老婆": "配偶", "丈夫": "配偶", "妻子": "配偶", "配偶": "配偶",
    "儿子": "子女", "女儿": "子女", "孩子": "子女", "子女": "子女",
}


def _member_option(row):
    member = row_to_dict(row)
    relation = member.get("relation") or "家庭成员"
    member["display_name"] = f"{member.get('name', '未命名')}（{relation}）"
    return member


def resolve_member(args):
    """Resolve a natural-language name/relation to one unambiguous member.

    Defaulting is intentionally narrow: only a sole member whose relation is
    本人 can be selected without an explicit name. Once multiple profiles exist,
    the caller must provide a name (and relation as a disambiguator if needed).
    """
    ensure_db()
    owner_id = getattr(args, "owner_id", None)
    conn = get_medical_connection()
    try:
        if owner_id:
            rows = conn.execute(
                """SELECT * FROM members WHERE is_deleted=0 AND owner_id=?
                   ORDER BY CASE WHEN relation='本人' THEN 0 ELSE 1 END, created_at""",
                (owner_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM members WHERE is_deleted=0
                   ORDER BY CASE WHEN relation='本人' THEN 0 ELSE 1 END, created_at"""
            ).fetchall()

        options = [_member_option(row) for row in rows]
        if not options:
            output_json({
                "status": "needs_creation",
                "message": "还没有家庭成员档案。请先确认用户姓名，并创建关系为“本人”的档案。",
                "members": [],
            })
            return

        requested_name = (getattr(args, "name", None) or "").strip()
        requested_relation = (getattr(args, "relation", None) or "").strip()
        normalized_relation = _RELATION_ALIASES.get(requested_relation, requested_relation)

        matches = options
        if requested_name:
            folded = requested_name.casefold()
            matches = [m for m in matches if str(m.get("name", "")).strip().casefold() == folded]
        if normalized_relation:
            matches = [m for m in matches if (m.get("relation") or "") == normalized_relation]

        if requested_name or normalized_relation:
            if len(matches) == 1:
                output_json({
                    "status": "ok",
                    "resolution": "resolved",
                    "message": f"已匹配成员：{matches[0]['display_name']}",
                    "member": matches[0],
                })
                return
            if not matches:
                output_json({
                    "status": "not_found",
                    "message": "没有找到对应的家庭成员，请核对姓名和身份。",
                    "members": options,
                })
                return
            output_json({
                "status": "needs_selection",
                "message": "找到多位同名或同身份成员，请同时指定姓名和身份。",
                "members": matches,
            })
            return

        if len(options) == 1 and options[0].get("relation") == "本人":
            output_json({
                "status": "ok",
                "resolution": "default_self",
                "message": f"默认使用本人档案：{options[0]['display_name']}",
                "member": options[0],
            })
            return

        output_json({
            "status": "needs_selection",
            "message": "当前有多位家庭成员，请明确说出要记录的姓名。",
            "members": options,
        })
    finally:
        conn.close()


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
    p_add.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    # list
    p_list = sub.add_parser("list")
    p_list.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    # get
    p_get = sub.add_parser("get")
    p_get.add_argument("--id", required=True)
    p_get.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

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
    p_upd.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    # delete
    p_del = sub.add_parser("delete")
    p_del.add_argument("--id", required=True)
    p_del.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    p_resolve = sub.add_parser("resolve", help="按姓名/身份解析目标成员")
    p_resolve.add_argument("--name", default=None)
    p_resolve.add_argument("--relation", default=None)
    p_resolve.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    args = parser.parse_args()
    commands = {"add": add_member, "list": list_members, "get": get_member,
                "update": update_member, "delete": delete_member,
                "resolve": resolve_member}
    commands[args.command](args)


if __name__ == "__main__":
    main()
