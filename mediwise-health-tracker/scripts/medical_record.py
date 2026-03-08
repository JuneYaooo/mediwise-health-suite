"""Medical record management for MediWise Health Tracker."""

from __future__ import annotations

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from health_db import ensure_db, get_connection, generate_id, now_iso, row_to_dict, rows_to_list, output_json, is_api_mode, transaction
from validators import validate_date, validate_date_optional
import api_client


# --- Visit ---

def add_visit(args):
    if is_api_mode():
        data = {"member_id": args.member_id, "visit_type": args.visit_type, "visit_date": args.visit_date}
        for f in ["end_date", "hospital", "department", "chief_complaint", "diagnosis", "summary"]:
            val = getattr(args, f, None)
            if val is not None:
                data[f] = val
        try:
            result = api_client.add_medical_record("visits", data)
            output_json({"status": "ok", "message": f"已添加就诊记录", "visit": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        # verify member exists
        m = conn.execute("SELECT id,name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        try:
            args.visit_date = validate_date(args.visit_date, "就诊日期")
            args.end_date = validate_date_optional(getattr(args, 'end_date', None), "结束日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        visit_id = generate_id()
        ts = now_iso()
        conn.execute(
            """INSERT INTO visits (id, member_id, visit_type, visit_date, end_date, hospital,
               department, chief_complaint, diagnosis, summary, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (visit_id, args.member_id, args.visit_type, args.visit_date, args.end_date,
             args.hospital, args.department, args.chief_complaint, args.diagnosis,
             args.summary, ts, ts)
        )
        conn.commit()
        visit = row_to_dict(conn.execute("SELECT * FROM visits WHERE id=?", (visit_id,)).fetchone())
        output_json({"status": "ok", "message": f"已为{m['name']}添加{args.visit_type}记录", "visit": visit})


def list_visits(args):
    if is_api_mode():
        params = {"member_id": args.member_id}
        if args.start_date:
            params["start_date"] = args.start_date
        if args.end_date:
            params["end_date"] = args.end_date
        if args.visit_type:
            params["visit_type"] = args.visit_type
        try:
            result = api_client.list_medical_records("visits", params)
            visits = result if isinstance(result, list) else result.get("visits", [])
            output_json({"status": "ok", "count": len(visits), "visits": visits})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        sql = "SELECT * FROM visits WHERE member_id=? AND is_deleted=0"
        params = [args.member_id]
        if args.start_date:
            sql += " AND visit_date>=?"
            params.append(args.start_date)
        if args.end_date:
            sql += " AND visit_date<=?"
            params.append(args.end_date)
        if args.visit_type:
            sql += " AND visit_type=?"
            params.append(args.visit_type)
        sql += " ORDER BY visit_date DESC"

        rows = conn.execute(sql, params).fetchall()
        output_json({"status": "ok", "count": len(rows), "visits": rows_to_list(rows)})
    finally:
        conn.close()


def update_visit(args):
    if is_api_mode():
        data = {}
        for f in ["visit_type", "visit_date", "end_date", "hospital", "department",
                   "chief_complaint", "diagnosis", "summary"]:
            val = getattr(args, f, None)
            if val is not None:
                data[f] = val
        if not data:
            output_json({"status": "error", "message": "未指定要更新的字段"})
            return
        try:
            result = api_client.update_medical_record("visits", args.id, data)
            output_json({"status": "ok", "message": "就诊记录已更新", "visit": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        row = conn.execute("SELECT * FROM visits WHERE id=? AND is_deleted=0", (args.id,)).fetchone()
        if not row:
            output_json({"status": "error", "message": f"未找到就诊记录: {args.id}"})
            return

        try:
            if getattr(args, 'visit_date', None) is not None:
                args.visit_date = validate_date(args.visit_date, "就诊日期")
            if getattr(args, 'end_date', None) is not None:
                args.end_date = validate_date_optional(args.end_date, "结束日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        fields, values = [], []
        for f in ["visit_type", "visit_date", "end_date", "hospital", "department",
                   "chief_complaint", "diagnosis", "summary"]:
            val = getattr(args, f, None)
            if val is not None:
                fields.append(f"{f}=?")
                values.append(val)
        if not fields:
            output_json({"status": "error", "message": "未指定要更新的字段"})
            return

        fields.append("updated_at=?")
        values.append(now_iso())
        values.append(args.id)
        conn.execute(f"UPDATE visits SET {', '.join(fields)} WHERE id=?", values)
        conn.commit()
        visit = row_to_dict(conn.execute("SELECT * FROM visits WHERE id=?", (args.id,)).fetchone())
        output_json({"status": "ok", "message": "就诊记录已更新", "visit": visit})


def delete_visit(args):
    if is_api_mode():
        try:
            api_client.delete_medical_record("visits", args.id)
            output_json({"status": "ok", "message": "就诊记录已删除"})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        row = conn.execute("SELECT * FROM visits WHERE id=? AND is_deleted=0", (args.id,)).fetchone()
        if not row:
            output_json({"status": "error", "message": f"未找到就诊记录: {args.id}"})
            return
        conn.execute("UPDATE visits SET is_deleted=1, updated_at=? WHERE id=?", (now_iso(), args.id))
        conn.commit()
        output_json({"status": "ok", "message": "就诊记录已删除"})


# --- Symptom ---

def add_symptom(args):
    if is_api_mode():
        data = {"member_id": args.member_id, "symptom": args.symptom}
        for f in ["visit_id", "severity", "onset_date", "end_date", "description"]:
            val = getattr(args, f, None)
            if val is not None:
                data[f] = val
        try:
            result = api_client.add_medical_record("symptoms", data)
            output_json({"status": "ok", "message": f"已记录症状: {args.symptom}", "symptom": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        try:
            args.onset_date = validate_date_optional(getattr(args, 'onset_date', None), "发病日期")
            args.end_date = validate_date_optional(getattr(args, 'end_date', None), "结束日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        symptom_id = generate_id()
        conn.execute(
            """INSERT INTO symptoms (id, member_id, visit_id, symptom, severity, onset_date,
               end_date, description, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symptom_id, args.member_id, args.visit_id, args.symptom, args.severity,
             args.onset_date, args.end_date, args.description, now_iso())
        )
        conn.commit()
        s = row_to_dict(conn.execute("SELECT * FROM symptoms WHERE id=?", (symptom_id,)).fetchone())
        output_json({"status": "ok", "message": f"已记录症状: {args.symptom}", "symptom": s})


def list_symptoms(args):
    if is_api_mode():
        params = {"member_id": args.member_id}
        if args.visit_id:
            params["visit_id"] = args.visit_id
        try:
            result = api_client.list_medical_records("symptoms", params)
            symptoms = result if isinstance(result, list) else result.get("symptoms", [])
            output_json({"status": "ok", "count": len(symptoms), "symptoms": symptoms})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        sql = "SELECT * FROM symptoms WHERE member_id=? AND is_deleted=0"
        params = [args.member_id]
        if args.visit_id:
            sql += " AND visit_id=?"
            params.append(args.visit_id)
        sql += " ORDER BY onset_date DESC, created_at DESC"
        rows = conn.execute(sql, params).fetchall()
        output_json({"status": "ok", "count": len(rows), "symptoms": rows_to_list(rows)})
    finally:
        conn.close()


# --- Medication ---

def add_medication(args):
    if is_api_mode():
        data = {"member_id": args.member_id, "name": args.name}
        for f in ["visit_id", "dosage", "frequency", "start_date", "end_date", "purpose"]:
            val = getattr(args, f, None)
            if val is not None:
                data[f] = val
        try:
            result = api_client.add_medical_record("medications", data)
            output_json({"status": "ok", "message": f"已添加用药: {args.name}", "medication": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        try:
            args.start_date = validate_date_optional(getattr(args, 'start_date', None), "开始日期")
            args.end_date = validate_date_optional(getattr(args, 'end_date', None), "结束日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        med_id = generate_id()
        ts = now_iso()
        conn.execute(
            """INSERT INTO medications (id, member_id, visit_id, name, dosage, frequency,
               start_date, end_date, purpose, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (med_id, args.member_id, args.visit_id, args.name, args.dosage, args.frequency,
             args.start_date, args.end_date, args.purpose, ts, ts)
        )
        conn.commit()
        med = row_to_dict(conn.execute("SELECT * FROM medications WHERE id=?", (med_id,)).fetchone())
        output_json({"status": "ok", "message": f"已添加用药: {args.name}", "medication": med})


def stop_medication(args):
    if is_api_mode():
        data = {"end_date": args.end_date, "stop_reason": args.reason}
        try:
            result = api_client.update_medical_record("medications", args.medication_id, {"is_active": False, **data})
            output_json({"status": "ok", "message": "已停用药物", "medication": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        row = conn.execute("SELECT * FROM medications WHERE id=? AND is_deleted=0", (args.medication_id,)).fetchone()
        if not row:
            output_json({"status": "error", "message": f"未找到用药记录: {args.medication_id}"})
            return
        conn.execute(
            "UPDATE medications SET is_active=0, end_date=?, stop_reason=?, updated_at=? WHERE id=?",
            (args.end_date or now_iso()[:10], args.reason, now_iso(), args.medication_id)
        )
        conn.commit()
        med = row_to_dict(conn.execute("SELECT * FROM medications WHERE id=?", (args.medication_id,)).fetchone())
        output_json({"status": "ok", "message": f"已停用药物: {row['name']}", "medication": med})


def list_medications(args):
    if is_api_mode():
        params = {"member_id": args.member_id}
        if args.active_only:
            params["active_only"] = "true"
        try:
            result = api_client.list_medical_records("medications", params)
            meds = result if isinstance(result, list) else result.get("medications", [])
            output_json({"status": "ok", "count": len(meds), "medications": meds})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        sql = "SELECT * FROM medications WHERE member_id=? AND is_deleted=0"
        params = [args.member_id]
        if args.active_only:
            sql += " AND is_active=1"
        sql += " ORDER BY start_date DESC"
        rows = conn.execute(sql, params).fetchall()
        output_json({"status": "ok", "count": len(rows), "medications": rows_to_list(rows)})
    finally:
        conn.close()


# --- Lab Result ---

def add_lab_result(args):
    if is_api_mode():
        data = {"member_id": args.member_id, "test_name": args.test_name, "test_date": args.test_date, "items": args.items}
        if args.visit_id:
            data["visit_id"] = args.visit_id
        try:
            result = api_client.add_medical_record("lab-results", data)
            output_json({"status": "ok", "message": f"已记录检验: {args.test_name}", "lab_result": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        # validate items JSON
        try:
            items = json.loads(args.items)
        except json.JSONDecodeError:
            output_json({"status": "error", "message": "items 格式错误，需要 JSON 数组"})
            return

        try:
            args.test_date = validate_date(args.test_date, "检验日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        lab_id = generate_id()
        conn.execute(
            """INSERT INTO lab_results (id, member_id, visit_id, test_name, test_date, items, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (lab_id, args.member_id, args.visit_id, args.test_name, args.test_date,
             json.dumps(items, ensure_ascii=False), now_iso())
        )
        conn.commit()
        lab = row_to_dict(conn.execute("SELECT * FROM lab_results WHERE id=?", (lab_id,)).fetchone())
        lab["items"] = json.loads(lab["items"])
        output_json({"status": "ok", "message": f"已记录检验: {args.test_name}", "lab_result": lab})


def list_lab_results(args):
    if is_api_mode():
        params = {"member_id": args.member_id}
        if args.start_date:
            params["start_date"] = args.start_date
        if args.end_date:
            params["end_date"] = args.end_date
        try:
            result = api_client.list_medical_records("lab-results", params)
            labs = result if isinstance(result, list) else result.get("lab_results", [])
            output_json({"status": "ok", "count": len(labs), "lab_results": labs})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        sql = "SELECT * FROM lab_results WHERE member_id=? AND is_deleted=0"
        params = [args.member_id]
        if args.start_date:
            sql += " AND test_date>=?"
            params.append(args.start_date)
        if args.end_date:
            sql += " AND test_date<=?"
            params.append(args.end_date)
        sql += " ORDER BY test_date DESC"
        rows = conn.execute(sql, params).fetchall()
        results = rows_to_list(rows)
        for r in results:
            r["items"] = json.loads(r["items"])
        output_json({"status": "ok", "count": len(results), "lab_results": results})
    finally:
        conn.close()


# --- Imaging Result ---

def add_imaging(args):
    if is_api_mode():
        data = {"member_id": args.member_id, "exam_name": args.exam_name, "exam_date": args.exam_date}
        for f in ["visit_id", "findings", "conclusion"]:
            val = getattr(args, f, None)
            if val is not None:
                data[f] = val
        try:
            result = api_client.add_medical_record("imaging", data)
            output_json({"status": "ok", "message": f"已记录影像检查: {args.exam_name}", "imaging_result": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    with transaction() as conn:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        try:
            args.exam_date = validate_date(args.exam_date, "检查日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        img_id = generate_id()
        conn.execute(
            """INSERT INTO imaging_results (id, member_id, visit_id, exam_name, exam_date,
               findings, conclusion, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (img_id, args.member_id, args.visit_id, args.exam_name, args.exam_date,
             args.findings, args.conclusion, now_iso())
        )
        conn.commit()
        img = row_to_dict(conn.execute("SELECT * FROM imaging_results WHERE id=?", (img_id,)).fetchone())
        output_json({"status": "ok", "message": f"已记录影像检查: {args.exam_name}", "imaging_result": img})


def list_imaging(args):
    if is_api_mode():
        params = {"member_id": args.member_id}
        if args.start_date:
            params["start_date"] = args.start_date
        if args.end_date:
            params["end_date"] = args.end_date
        try:
            result = api_client.list_medical_records("imaging", params)
            imgs = result if isinstance(result, list) else result.get("imaging_results", [])
            output_json({"status": "ok", "count": len(imgs), "imaging_results": imgs})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        sql = "SELECT * FROM imaging_results WHERE member_id=? AND is_deleted=0"
        params = [args.member_id]
        if args.start_date:
            sql += " AND exam_date>=?"
            params.append(args.start_date)
        if args.end_date:
            sql += " AND exam_date<=?"
            params.append(args.end_date)
        sql += " ORDER BY exam_date DESC"
        rows = conn.execute(sql, params).fetchall()
        output_json({"status": "ok", "count": len(rows), "imaging_results": rows_to_list(rows)})
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="病程记录管理")
    sub = parser.add_subparsers(dest="command", required=True)

    # --- visit commands ---
    p = sub.add_parser("add-visit")
    p.add_argument("--member-id", required=True)
    p.add_argument("--visit-type", required=True, help="门诊/住院/急诊/体检/其他")
    p.add_argument("--visit-date", required=True)
    p.add_argument("--end-date", default=None)
    p.add_argument("--hospital", default=None)
    p.add_argument("--department", default=None)
    p.add_argument("--chief-complaint", default=None)
    p.add_argument("--diagnosis", default=None)
    p.add_argument("--summary", default=None)

    p = sub.add_parser("list-visits")
    p.add_argument("--member-id", required=True)
    p.add_argument("--start-date", default=None)
    p.add_argument("--end-date", default=None)
    p.add_argument("--visit-type", default=None)

    p = sub.add_parser("update-visit")
    p.add_argument("--id", required=True)
    p.add_argument("--visit-type", default=None)
    p.add_argument("--visit-date", default=None)
    p.add_argument("--end-date", default=None)
    p.add_argument("--hospital", default=None)
    p.add_argument("--department", default=None)
    p.add_argument("--chief-complaint", default=None)
    p.add_argument("--diagnosis", default=None)
    p.add_argument("--summary", default=None)

    p = sub.add_parser("delete-visit")
    p.add_argument("--id", required=True)

    # --- symptom commands ---
    p = sub.add_parser("add-symptom")
    p.add_argument("--member-id", required=True)
    p.add_argument("--visit-id", default=None)
    p.add_argument("--symptom", required=True)
    p.add_argument("--severity", default=None, help="轻度/中度/重度")
    p.add_argument("--onset-date", default=None)
    p.add_argument("--end-date", default=None)
    p.add_argument("--description", default=None)

    p = sub.add_parser("list-symptoms")
    p.add_argument("--member-id", required=True)
    p.add_argument("--visit-id", default=None)

    # --- medication commands ---
    p = sub.add_parser("add-medication")
    p.add_argument("--member-id", required=True)
    p.add_argument("--visit-id", default=None)
    p.add_argument("--name", required=True)
    p.add_argument("--dosage", default=None)
    p.add_argument("--frequency", default=None)
    p.add_argument("--start-date", default=None)
    p.add_argument("--end-date", default=None)
    p.add_argument("--purpose", default=None)

    p = sub.add_parser("stop-medication")
    p.add_argument("--medication-id", required=True)
    p.add_argument("--end-date", default=None)
    p.add_argument("--reason", default=None)

    p = sub.add_parser("list-medications")
    p.add_argument("--member-id", required=True)
    p.add_argument("--active-only", action="store_true")

    # --- lab result commands ---
    p = sub.add_parser("add-lab-result")
    p.add_argument("--member-id", required=True)
    p.add_argument("--visit-id", default=None)
    p.add_argument("--test-name", required=True)
    p.add_argument("--test-date", required=True)
    p.add_argument("--items", required=True, help='JSON数组，每项含 name/value/unit/reference/is_abnormal')

    p = sub.add_parser("list-lab-results")
    p.add_argument("--member-id", required=True)
    p.add_argument("--start-date", default=None)
    p.add_argument("--end-date", default=None)

    # --- imaging commands ---
    p = sub.add_parser("add-imaging")
    p.add_argument("--member-id", required=True)
    p.add_argument("--visit-id", default=None)
    p.add_argument("--exam-name", required=True)
    p.add_argument("--exam-date", required=True)
    p.add_argument("--findings", default=None)
    p.add_argument("--conclusion", default=None)

    p = sub.add_parser("list-imaging")
    p.add_argument("--member-id", required=True)
    p.add_argument("--start-date", default=None)
    p.add_argument("--end-date", default=None)

    args = parser.parse_args()
    commands = {
        "add-visit": add_visit, "list-visits": list_visits,
        "update-visit": update_visit, "delete-visit": delete_visit,
        "add-symptom": add_symptom, "list-symptoms": list_symptoms,
        "add-medication": add_medication, "stop-medication": stop_medication,
        "list-medications": list_medications,
        "add-lab-result": add_lab_result, "list-lab-results": list_lab_results,
        "add-imaging": add_imaging, "list-imaging": list_imaging,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
