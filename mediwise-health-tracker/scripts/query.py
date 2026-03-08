"""Query and report generation for MediWise Health Tracker."""
from __future__ import annotations

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from health_db import (
    ensure_db,
    get_connection,
    rows_to_list,
    row_to_dict,
    output_json,
    is_api_mode,
    verify_member_ownership,
)
import api_client


def _ensure_member_access(conn, member_id, owner_id):
    if not verify_member_ownership(conn, member_id, owner_id):
        output_json({"status": "error", "message": f"无权访问成员: {member_id}"})
        return False
    return True


def _get_member_name(conn, member_id):
    row = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (member_id,)).fetchone()
    return row["name"] if row else None


def _parse_json_list(value):
    if not value:
        return []
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _load_lineage(conn, member_id, record_type, record_id):
    attachments = rows_to_list(conn.execute(
        """SELECT a.id, a.category, a.original_filename, a.created_at
           FROM attachments a
           JOIN attachment_links al ON al.attachment_id=a.id AND al.is_deleted=0
           WHERE a.member_id=? AND a.is_deleted=0 AND al.record_type=? AND al.record_id=?
           ORDER BY a.created_at DESC""",
        (member_id, record_type, record_id)
    ).fetchall())
    observation_rows = rows_to_list(conn.execute(
        """SELECT id, title, source_records
           FROM observations
           WHERE member_id=? AND is_deleted=0 AND source_records LIKE ?
           ORDER BY created_at DESC""",
        (member_id, f'%"{record_id}"%')
    ).fetchall())

    source_records = []
    observation_refs = []
    for row in observation_rows:
        source_records.extend(_parse_json_list(row.get("source_records")))
        observation_refs.append({"id": row["id"], "title": row["title"]})

    lineage = {
        "attachments": attachments,
        "source_records": list(dict.fromkeys(source_records)),
        "observations": observation_refs,
    }
    if any(lineage.values()):
        return lineage
    return None


def _attach_lineage(conn, member_id, record, record_type, record_id_key="id"):
    record_id = record.get(record_id_key)
    if not record_id:
        return record
    lineage = _load_lineage(conn, member_id, record_type, record_id)
    if lineage:
        record["lineage"] = lineage
    return record


def timeline(args):
    """Generate a chronological timeline of all medical events for a member."""
    if is_api_mode():
        try:
            result = api_client.get_timeline(args.member_id)
            output_json({"status": "ok", **(result if isinstance(result, dict) else {"data": result})})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        if not _ensure_member_access(conn, args.member_id, getattr(args, 'owner_id', None)):
            return
        name = _get_member_name(conn, args.member_id)
        if not name:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        # Gather all events
        events = []

        # Visits
        visits = conn.execute(
            "SELECT * FROM visits WHERE member_id=? AND is_deleted=0 ORDER BY visit_date",
            (args.member_id,)
        ).fetchall()
        for v in visits:
            v = dict(v)
            visit_id = v["id"]

            # Attach symptoms
            symptoms = rows_to_list(conn.execute(
                "SELECT * FROM symptoms WHERE visit_id=? AND is_deleted=0", (visit_id,)
            ).fetchall())
            symptoms = [_attach_lineage(conn, args.member_id, item, "symptom") for item in symptoms]

            # Attach medications
            meds = rows_to_list(conn.execute(
                "SELECT * FROM medications WHERE visit_id=? AND is_deleted=0", (visit_id,)
            ).fetchall())
            meds = [_attach_lineage(conn, args.member_id, item, "medication") for item in meds]

            # Attach lab results
            labs = rows_to_list(conn.execute(
                "SELECT * FROM lab_results WHERE visit_id=? AND is_deleted=0", (visit_id,)
            ).fetchall())
            for lab in labs:
                try:
                    lab["items"] = json.loads(lab["items"])
                except (json.JSONDecodeError, TypeError):
                    pass
                _attach_lineage(conn, args.member_id, lab, "lab_result")

            # Attach imaging
            imaging = rows_to_list(conn.execute(
                "SELECT * FROM imaging_results WHERE visit_id=? AND is_deleted=0", (visit_id,)
            ).fetchall())
            imaging = [_attach_lineage(conn, args.member_id, item, "imaging_result") for item in imaging]

            events.append(_attach_lineage(conn, args.member_id, {
                "date": v["visit_date"],
                "type": "visit",
                "visit_type": v["visit_type"],
                "hospital": v["hospital"],
                "department": v["department"],
                "chief_complaint": v["chief_complaint"],
                "diagnosis": v["diagnosis"],
                "summary": v["summary"],
                "visit_id": visit_id,
                "symptoms": symptoms,
                "medications": meds,
                "lab_results": labs,
                "imaging_results": imaging,
            }, "visit", "visit_id"))

        # Standalone symptoms (no visit)
        standalone_symptoms = rows_to_list(conn.execute(
            "SELECT * FROM symptoms WHERE member_id=? AND visit_id IS NULL AND is_deleted=0 ORDER BY onset_date",
            (args.member_id,)
        ).fetchall())
        for s in standalone_symptoms:
            events.append(_attach_lineage(conn, args.member_id, {"date": s["onset_date"] or s["created_at"], "type": "symptom", **s}, "symptom"))

        # Standalone medications (no visit)
        standalone_meds = rows_to_list(conn.execute(
            "SELECT * FROM medications WHERE member_id=? AND visit_id IS NULL AND is_deleted=0 ORDER BY start_date",
            (args.member_id,)
        ).fetchall())
        for m in standalone_meds:
            events.append(_attach_lineage(conn, args.member_id, {"date": m["start_date"] or m["created_at"], "type": "medication", **m}, "medication"))

        # Standalone lab results
        standalone_labs = rows_to_list(conn.execute(
            "SELECT * FROM lab_results WHERE member_id=? AND visit_id IS NULL AND is_deleted=0 ORDER BY test_date",
            (args.member_id,)
        ).fetchall())
        for l in standalone_labs:
            try:
                l["items"] = json.loads(l["items"])
            except (json.JSONDecodeError, TypeError):
                pass
            events.append(_attach_lineage(conn, args.member_id, {"date": l["test_date"], "type": "lab_result", **l}, "lab_result"))

        # Standalone imaging
        standalone_img = rows_to_list(conn.execute(
            "SELECT * FROM imaging_results WHERE member_id=? AND visit_id IS NULL AND is_deleted=0 ORDER BY exam_date",
            (args.member_id,)
        ).fetchall())
        for i in standalone_img:
            events.append(_attach_lineage(conn, args.member_id, {"date": i["exam_date"], "type": "imaging", **i}, "imaging_result"))

        # Sort by date
        events.sort(key=lambda e: e.get("date") or "")

        # Member info
        member = row_to_dict(conn.execute("SELECT * FROM members WHERE id=?", (args.member_id,)).fetchone())

        output_json({
            "status": "ok",
            "member": member,
            "event_count": len(events),
            "timeline": events
        })
    finally:
        conn.close()


def active_medications(args):
    """List currently active medications for a member."""
    if is_api_mode():
        try:
            result = api_client.get_active_medications(args.member_id)
            output_json({"status": "ok", **(result if isinstance(result, dict) else {"data": result})})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        if not _ensure_member_access(conn, args.member_id, getattr(args, 'owner_id', None)):
            return
        name = _get_member_name(conn, args.member_id)
        if not name:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        rows = conn.execute(
            """SELECT m.*, v.hospital, v.department, v.visit_date
               FROM medications m LEFT JOIN visits v ON m.visit_id=v.id
               WHERE m.member_id=? AND m.is_active=1 AND m.is_deleted=0
               ORDER BY m.start_date DESC""",
            (args.member_id,)
        ).fetchall()
        output_json({"status": "ok", "member": name, "count": len(rows), "medications": rows_to_list(rows)})
    finally:
        conn.close()


def visits(args):
    """Query visits by date range."""
    if is_api_mode():
        try:
            result = api_client.get_visits(args.member_id, args.start_date, args.end_date)
            output_json({"status": "ok", **(result if isinstance(result, dict) else {"data": result})})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        if not _ensure_member_access(conn, args.member_id, getattr(args, 'owner_id', None)):
            return
        name = _get_member_name(conn, args.member_id)
        if not name:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        sql = "SELECT * FROM visits WHERE member_id=? AND is_deleted=0"
        params = [args.member_id]
        if args.start_date:
            sql += " AND visit_date>=?"
            params.append(args.start_date)
        if args.end_date:
            sql += " AND visit_date<=?"
            params.append(args.end_date)
        sql += " ORDER BY visit_date DESC"

        rows = conn.execute(sql, params).fetchall()
        output_json({"status": "ok", "member": name, "count": len(rows), "visits": rows_to_list(rows)})
    finally:
        conn.close()


def summary(args):
    """Generate a health summary for a member."""
    if is_api_mode():
        try:
            result = api_client.get_summary(args.member_id)
            output_json({"status": "ok", **(result if isinstance(result, dict) else {"data": result})})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        if not _ensure_member_access(conn, args.member_id, getattr(args, 'owner_id', None)):
            return
        member = row_to_dict(conn.execute(
            "SELECT * FROM members WHERE id=? AND is_deleted=0", (args.member_id,)
        ).fetchone())
        if not member:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        # Basic stats
        visit_count = conn.execute(
            "SELECT COUNT(*) as c FROM visits WHERE member_id=? AND is_deleted=0", (args.member_id,)
        ).fetchone()["c"]

        active_med_count = conn.execute(
            "SELECT COUNT(*) as c FROM medications WHERE member_id=? AND is_active=1 AND is_deleted=0",
            (args.member_id,)
        ).fetchone()["c"]

        # Recent visits (last 5)
        recent_visits = rows_to_list(conn.execute(
            "SELECT visit_date, visit_type, hospital, department, diagnosis FROM visits WHERE member_id=? AND is_deleted=0 ORDER BY visit_date DESC LIMIT 5",
            (args.member_id,)
        ).fetchall())

        # Active medications
        active_meds = rows_to_list(conn.execute(
            "SELECT name, dosage, frequency, start_date, purpose FROM medications WHERE member_id=? AND is_active=1 AND is_deleted=0",
            (args.member_id,)
        ).fetchall())

        # Recent metrics (last reading per type)
        latest_metrics = {}
        for row in conn.execute(
            """SELECT metric_type, value, measured_at FROM health_metrics
               WHERE member_id=? AND is_deleted=0
               ORDER BY measured_at DESC""",
            (args.member_id,)
        ).fetchall():
            mt = row["metric_type"]
            if mt not in latest_metrics:
                val = row["value"]
                if mt == "blood_pressure":
                    try:
                        val = json.loads(val)
                    except (json.JSONDecodeError, TypeError):
                        pass
                latest_metrics[mt] = {"value": val, "measured_at": row["measured_at"]}

        # All diagnoses
        diagnoses = []
        for row in conn.execute(
            "SELECT DISTINCT diagnosis FROM visits WHERE member_id=? AND is_deleted=0 AND diagnosis IS NOT NULL",
            (args.member_id,)
        ).fetchall():
            if row["diagnosis"]:
                diagnoses.extend([d.strip() for d in row["diagnosis"].split(",") if d.strip()])
        diagnoses = list(set(diagnoses))

        output_json({
            "status": "ok",
            "member": {
                "name": member["name"],
                "relation": member["relation"],
                "gender": member["gender"],
                "birth_date": member["birth_date"],
                "blood_type": member["blood_type"],
                "allergies": member["allergies"],
                "medical_history": member["medical_history"],
            },
            "stats": {
                "total_visits": visit_count,
                "active_medications": active_med_count,
                "known_diagnoses": diagnoses,
            },
            "recent_visits": recent_visits,
            "active_medications": active_meds,
            "latest_metrics": latest_metrics,
        })
    finally:
        conn.close()


def _build_search_query(table: str, search_columns: list[str], member_id: str = None, member_ids: list[str] = None):
    """Build a parameterized search query for keyword search.

    Returns (sql, base_params) where the caller appends LIKE params.
    """
    conditions = ["is_deleted=0"]
    params = []
    if member_id:
        conditions.append("member_id=?")
        params.append(member_id)
    elif member_ids is not None:
        if not member_ids:
            # No members for this owner — return impossible condition
            conditions.append("1=0")
        else:
            placeholders = ",".join("?" for _ in member_ids)
            conditions.append(f"member_id IN ({placeholders})")
            params.extend(member_ids)
    like_clauses = " OR ".join(f"{col} LIKE ?" for col in search_columns)
    conditions.append(f"({like_clauses})")
    sql = f"SELECT * FROM {table} WHERE " + " AND ".join(conditions)
    return sql, params


def search(args):
    """Search records by keyword, with vector semantic search when available."""
    if is_api_mode():
        try:
            result = api_client.search_records(args.keyword, getattr(args, 'member_id', None))
            output_json({"status": "ok", **(result if isinstance(result, dict) else {"data": result})})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()

    conn = get_connection()
    try:
        if args.member_id and not _ensure_member_access(conn, args.member_id, getattr(args, 'owner_id', None)):
            return
    finally:
        conn.close()

    # Try vector semantic search first
    try:
        from embedding_provider import get_provider
        provider = get_provider()
        if provider.name != "none":
            conn = get_connection()
            try:
                count = conn.execute("SELECT COUNT(*) as c FROM embeddings").fetchone()["c"]
            finally:
                conn.close()

            if count > 0:
                from vector_search import cmd_search as _vs_search
                # Build a fake args object for vector_search
                class VArgs:
                    pass
                vargs = VArgs()
                vargs.query = args.keyword
                vargs.member_id = args.member_id
                vargs.owner_id = getattr(args, 'owner_id', None)
                vargs.limit = 10
                _vs_search(vargs)
                return
    except Exception:
        pass  # Fall through to keyword search

    # Keyword search fallback
    conn = get_connection()
    try:
        kw = f"%{args.keyword}%"
        results = {"visits": [], "symptoms": [], "medications": [], "lab_results": [], "imaging": []}

        # Resolve owner_id to member_ids for scoping
        owner_id = getattr(args, 'owner_id', None)
        owner_member_ids = None
        if owner_id and not args.member_id:
            rows = conn.execute(
                "SELECT id FROM members WHERE is_deleted=0 AND owner_id=?", (owner_id,)
            ).fetchall()
            owner_member_ids = [r["id"] for r in rows]

        _SEARCH_TABLES = [
            ("visits", ["chief_complaint", "diagnosis", "summary", "hospital", "department"]),
            ("symptoms", ["symptom", "description"]),
            ("medications", ["name", "purpose"]),
            ("lab_results", ["test_name", "items"]),
            ("imaging", ["exam_name", "findings", "conclusion"]),
        ]
        # Map table names to result keys (imaging_results table -> "imaging" key)
        _TABLE_MAP = {"imaging": "imaging_results"}

        for result_key, columns in _SEARCH_TABLES:
            table = _TABLE_MAP.get(result_key, result_key)
            sql, params = _build_search_query(table, columns, args.member_id, owner_member_ids)
            params.extend([kw] * len(columns))
            rows = conn.execute(sql, params).fetchall()
            results[result_key] = rows_to_list(rows)

        total = sum(len(v) for v in results.values())
        output_json({"status": "ok", "keyword": args.keyword, "total_matches": total, "results": results})
    finally:
        conn.close()


def family_overview(args):
    """Show health overview for all family members."""
    if is_api_mode():
        try:
            result = api_client.get_family_overview()
            output_json({"status": "ok", **(result if isinstance(result, dict) else {"data": result})})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        owner_id = getattr(args, 'owner_id', None)
        if owner_id:
            members = rows_to_list(conn.execute(
                "SELECT * FROM members WHERE is_deleted=0 AND owner_id=? ORDER BY created_at",
                (owner_id,)
            ).fetchall())
        else:
            members = rows_to_list(conn.execute(
                "SELECT * FROM members WHERE is_deleted=0 ORDER BY created_at"
            ).fetchall())

        overview = []
        for m in members:
            mid = m["id"]
            visit_count = conn.execute(
                "SELECT COUNT(*) as c FROM visits WHERE member_id=? AND is_deleted=0", (mid,)
            ).fetchone()["c"]
            active_meds = conn.execute(
                "SELECT COUNT(*) as c FROM medications WHERE member_id=? AND is_active=1 AND is_deleted=0", (mid,)
            ).fetchone()["c"]
            last_visit = conn.execute(
                "SELECT visit_date, hospital, diagnosis FROM visits WHERE member_id=? AND is_deleted=0 ORDER BY visit_date DESC LIMIT 1", (mid,)
            ).fetchone()

            overview.append({
                "id": mid,
                "name": m["name"],
                "relation": m["relation"],
                "gender": m["gender"],
                "birth_date": m["birth_date"],
                "allergies": m["allergies"],
                "total_visits": visit_count,
                "active_medications": active_meds,
                "last_visit": row_to_dict(last_visit) if last_visit else None,
            })

        output_json({"status": "ok", "family_size": len(overview), "members": overview})
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="查询与报告")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("timeline")
    p.add_argument("--member-id", required=True)
    p.add_argument("--owner-id", default=None)

    p = sub.add_parser("active-medications")
    p.add_argument("--member-id", required=True)
    p.add_argument("--owner-id", default=None)

    p = sub.add_parser("visits")
    p.add_argument("--member-id", required=True)
    p.add_argument("--start-date", default=None)
    p.add_argument("--end-date", default=None)
    p.add_argument("--owner-id", default=None)

    p = sub.add_parser("summary")
    p.add_argument("--member-id", required=True)
    p.add_argument("--owner-id", default=None)

    p = sub.add_parser("search")
    p.add_argument("--member-id", default=None)
    p.add_argument("--keyword", required=True)
    p.add_argument("--owner-id", default=None)

    p = sub.add_parser("family-overview")
    p.add_argument("--owner-id", default=None)

    args = parser.parse_args()
    commands = {
        "timeline": timeline, "active-medications": active_medications,
        "visits": visits, "summary": summary, "search": search,
        "family-overview": family_overview,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
