"""FHIR R4 export and statistics export for MediWise Health Tracker.

Usage:
  python3 scripts/export.py fhir --member-id <id> [--privacy-level full|anonymized|statistical] [--output <file>]
  python3 scripts/export.py statistics [--member-id <id>] [--output <file>]
"""

from __future__ import annotations

import argparse
import json
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import health_db
from health_db import ensure_db, get_connection, rows_to_list, row_to_dict, verify_member_ownership
import privacy

# LOINC mappings for health_metrics
LOINC_MAP = {
    "blood_pressure": {"code": "85354-9", "display": "Blood pressure panel"},
    "blood_sugar":    {"code": "2339-0",  "display": "Glucose"},
    "heart_rate":     {"code": "8867-4",  "display": "Heart rate"},
    "weight":         {"code": "29463-7", "display": "Body weight"},
    "temperature":    {"code": "8310-5",  "display": "Body temperature"},
    "blood_oxygen":   {"code": "2708-6",  "display": "Oxygen saturation"},
    "height":         {"code": "8302-2",  "display": "Body height"},
}

VISIT_TYPE_MAP = {
    "门诊": "AMB",
    "住院": "IMP",
    "急诊": "EMER",
}


def _make_bundle(entries: list) -> dict:
    return {
        "resourceType": "Bundle",
        "type": "collection",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        "entry": [{"resource": r} for r in entries],
    }


def _write_export_audit(conn, event_type: str, member_id: str | None = None,
                        owner_id: str | None = None, payload: dict | None = None):
    health_db.append_audit_event(
        conn,
        event_type,
        member_id=member_id,
        owner_id=owner_id,
        record_type="export",
        record_id=member_id,
        payload=payload,
    )


def _build_patient(member: dict) -> dict:
    """Build FHIR Patient resource from member dict."""
    patient = {
        "resourceType": "Patient",
        "id": member["id"],
        "name": [{"text": member.get("name", "")}],
    }
    if member.get("gender"):
        gender_map = {"男": "male", "女": "female"}
        patient["gender"] = gender_map.get(member["gender"], "unknown")
    if member.get("birth_date"):
        patient["birthDate"] = member["birth_date"]
    if member.get("blood_type"):
        patient["extension"] = [{
            "url": "http://mediwise.local/fhir/blood-type",
            "valueString": member["blood_type"],
        }]
    telecom = []
    if member.get("phone"):
        telecom.append({"system": "phone", "value": member["phone"]})
    if telecom:
        patient["telecom"] = telecom
    return patient


def _build_allergy(member: dict) -> list:
    """Build FHIR AllergyIntolerance resources from member allergies."""
    if not member.get("allergies"):
        return []
    items = [a.strip() for a in member["allergies"].split(",") if a.strip()]
    resources = []
    for i, allergy in enumerate(items):
        resources.append({
            "resourceType": "AllergyIntolerance",
            "id": f"{member['id']}-allergy-{i}",
            "patient": {"reference": f"Patient/{member['id']}"},
            "code": {"text": allergy},
        })
    return resources


def _build_encounter(visit: dict) -> dict:
    """Build FHIR Encounter resource from visit dict."""
    enc = {
        "resourceType": "Encounter",
        "id": visit["id"],
        "status": "finished",
        "class": {
            "code": VISIT_TYPE_MAP.get(visit.get("visit_type", ""), "AMB"),
            "display": visit.get("visit_type", "门诊"),
        },
        "subject": {"reference": f"Patient/{visit['member_id']}"},
        "period": {"start": visit.get("visit_date", "")},
    }
    if visit.get("end_date"):
        enc["period"]["end"] = visit["end_date"]
    if visit.get("hospital"):
        enc["serviceProvider"] = {"display": visit["hospital"]}
    if visit.get("department"):
        enc["type"] = [{"text": visit["department"]}]
    if visit.get("diagnosis"):
        enc["diagnosis"] = [{"condition": {"display": visit["diagnosis"]}}]
    return enc


def _build_condition(symptom: dict) -> dict:
    """Build FHIR Condition resource from symptom dict."""
    cond = {
        "resourceType": "Condition",
        "id": symptom["id"],
        "subject": {"reference": f"Patient/{symptom['member_id']}"},
        "code": {"text": symptom.get("symptom", "")},
    }
    if symptom.get("severity"):
        cond["severity"] = {"text": symptom["severity"]}
    if symptom.get("onset_date"):
        cond["onsetDateTime"] = symptom["onset_date"]
    if symptom.get("visit_id"):
        cond["encounter"] = {"reference": f"Encounter/{symptom['visit_id']}"}
    return cond


def _build_medication_statement(med: dict) -> dict:
    """Build FHIR MedicationStatement from medication dict."""
    status = "active" if not med.get("end_date") else "completed"
    ms = {
        "resourceType": "MedicationStatement",
        "id": med["id"],
        "status": status,
        "subject": {"reference": f"Patient/{med['member_id']}"},
        "medicationCodeableConcept": {"text": med.get("name", "")},
    }
    period = {}
    if med.get("start_date"):
        period["start"] = med["start_date"]
    if med.get("end_date"):
        period["end"] = med["end_date"]
    if period:
        ms["effectivePeriod"] = period
    dosage = {}
    if med.get("dosage"):
        dosage["text"] = med["dosage"]
    if med.get("frequency"):
        dosage["timing"] = {"code": {"text": med["frequency"]}}
    if dosage:
        ms["dosage"] = [dosage]
    if med.get("purpose"):
        ms["reasonCode"] = [{"text": med["purpose"]}]
    return ms


def _build_lab_observation(lab: dict) -> list:
    """Build FHIR Observation resources from lab_results dict."""
    items = lab.get("items", "[]")
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except (json.JSONDecodeError, TypeError):
            items = []
    observations = []
    for i, item in enumerate(items):
        obs = {
            "resourceType": "Observation",
            "id": f"{lab['id']}-item-{i}",
            "status": "final",
            "category": [{"coding": [{"code": "laboratory", "display": "Laboratory"}]}],
            "subject": {"reference": f"Patient/{lab['member_id']}"},
            "code": {"text": item.get("name", lab.get("test_name", ""))},
            "effectiveDateTime": lab.get("test_date", ""),
        }
        if item.get("value") is not None:
            obs["valueQuantity"] = {"value": item["value"]}
            if item.get("unit"):
                obs["valueQuantity"]["unit"] = item["unit"]
        if item.get("reference"):
            obs["referenceRange"] = [{"text": item["reference"]}]
        if item.get("is_abnormal"):
            obs["interpretation"] = [{"text": "异常"}]
        if lab.get("visit_id"):
            obs["encounter"] = {"reference": f"Encounter/{lab['visit_id']}"}
        observations.append(obs)
    # If no items parsed, create a single observation for the test
    if not observations:
        obs = {
            "resourceType": "Observation",
            "id": lab["id"],
            "status": "final",
            "category": [{"coding": [{"code": "laboratory", "display": "Laboratory"}]}],
            "subject": {"reference": f"Patient/{lab['member_id']}"},
            "code": {"text": lab.get("test_name", "")},
            "effectiveDateTime": lab.get("test_date", ""),
        }
        observations.append(obs)
    return observations


def _build_diagnostic_report(imaging: dict) -> dict:
    """Build FHIR DiagnosticReport from imaging_results dict."""
    report = {
        "resourceType": "DiagnosticReport",
        "id": imaging["id"],
        "status": "final",
        "subject": {"reference": f"Patient/{imaging['member_id']}"},
        "code": {"text": imaging.get("exam_name", "")},
        "effectiveDateTime": imaging.get("exam_date", ""),
    }
    if imaging.get("conclusion"):
        report["conclusion"] = imaging["conclusion"]
    if imaging.get("findings"):
        report["presentedForm"] = [{"data": imaging["findings"]}]
    if imaging.get("visit_id"):
        report["encounter"] = {"reference": f"Encounter/{imaging['visit_id']}"}
    return report


def _build_vital_observation(metric: dict) -> dict:
    """Build FHIR Observation (vital-signs) from health_metrics dict."""
    mtype = metric.get("metric_type", "")
    loinc = LOINC_MAP.get(mtype, {"code": "unknown", "display": mtype})
    obs = {
        "resourceType": "Observation",
        "id": metric["id"],
        "status": "final",
        "category": [{"coding": [{"code": "vital-signs", "display": "Vital Signs"}]}],
        "subject": {"reference": f"Patient/{metric['member_id']}"},
        "code": {"coding": [{"system": "http://loinc.org", "code": loinc["code"], "display": loinc["display"]}]},
        "effectiveDateTime": metric.get("measured_at", ""),
    }
    value = metric.get("value", "")
    if mtype == "blood_pressure":
        try:
            bp = json.loads(value) if isinstance(value, str) else value
            obs["component"] = [
                {"code": {"text": "Systolic"}, "valueQuantity": {"value": bp.get("systolic"), "unit": "mmHg"}},
                {"code": {"text": "Diastolic"}, "valueQuantity": {"value": bp.get("diastolic"), "unit": "mmHg"}},
            ]
        except (json.JSONDecodeError, TypeError, AttributeError):
            obs["valueString"] = str(value)
    else:
        unit_map = {
            "blood_sugar": "mmol/L", "heart_rate": "/min", "weight": "kg",
            "temperature": "°C", "blood_oxygen": "%", "height": "cm",
        }
        try:
            obs["valueQuantity"] = {"value": float(value), "unit": unit_map.get(mtype, "")}
        except (ValueError, TypeError):
            obs["valueString"] = str(value)
    if metric.get("note"):
        obs["note"] = [{"text": metric["note"]}]
    return obs


def export_fhir(member_id: str, level: str, owner_id: str | None = None) -> dict:
    """Export FHIR R4 Bundle for a member. Returns Bundle dict or statistics dict."""
    if level == "statistical":
        # Statistical level doesn't produce FHIR, return aggregate stats
        ensure_db()
        conn = get_connection()
        try:
            if member_id and not verify_member_ownership(conn, member_id, owner_id):
                return {"error": f"无权访问成员: {member_id}"}
            result = privacy.aggregate_statistics(conn, member_id, owner_id)
            _write_export_audit(
                conn,
                "export.statistics",
                member_id=member_id,
                owner_id=owner_id,
                payload={"scope": "member" if member_id else "owner", "member_count": result.get("member_count")},
            )
            conn.commit()
            return result
        finally:
            conn.close()

    ensure_db()
    conn = get_connection()
    try:
        resources = []

        # Patient
        member = row_to_dict(conn.execute(
            "SELECT * FROM members WHERE id=? AND is_deleted=0", (member_id,)
        ).fetchone())
        if not member:
            return {"error": f"未找到成员: {member_id}"}
        if not verify_member_ownership(conn, member_id, owner_id):
            return {"error": f"无权访问成员: {member_id}"}
        member = privacy.filter_member(member, level)
        resources.append(_build_patient(member))

        # Allergies
        resources.extend(_build_allergy(member))

        # Visits -> Encounter
        visits = rows_to_list(conn.execute(
            "SELECT * FROM visits WHERE member_id=? AND is_deleted=0 ORDER BY visit_date", (member_id,)
        ).fetchall())
        for v in visits:
            v = privacy.filter_record(v, level)
            if v:
                resources.append(_build_encounter(v))

        # Symptoms -> Condition
        symptoms = rows_to_list(conn.execute(
            "SELECT * FROM symptoms WHERE member_id=? AND is_deleted=0", (member_id,)
        ).fetchall())
        for s in symptoms:
            s = privacy.filter_record(s, level)
            if s:
                resources.append(_build_condition(s))

        # Medications -> MedicationStatement
        meds = rows_to_list(conn.execute(
            "SELECT * FROM medications WHERE member_id=? AND is_deleted=0", (member_id,)
        ).fetchall())
        for m in meds:
            m = privacy.filter_record(m, level)
            if m:
                resources.append(_build_medication_statement(m))

        # Lab results -> Observation (laboratory)
        labs = rows_to_list(conn.execute(
            "SELECT * FROM lab_results WHERE member_id=? AND is_deleted=0", (member_id,)
        ).fetchall())
        for lab in labs:
            lab = privacy.filter_record(lab, level)
            if lab:
                resources.extend(_build_lab_observation(lab))

        # Imaging -> DiagnosticReport
        imaging = rows_to_list(conn.execute(
            "SELECT * FROM imaging_results WHERE member_id=? AND is_deleted=0", (member_id,)
        ).fetchall())
        for img in imaging:
            img = privacy.filter_record(img, level)
            if img:
                resources.append(_build_diagnostic_report(img))

        # Health metrics -> Observation (vital-signs)
        metrics = rows_to_list(conn.execute(
            "SELECT * FROM health_metrics WHERE member_id=? AND is_deleted=0 ORDER BY measured_at", (member_id,)
        ).fetchall())
        for met in metrics:
            met = privacy.filter_record(met, level)
            if met:
                resources.append(_build_vital_observation(met))

        result = _make_bundle(resources)
        _write_export_audit(
            conn,
            "export.fhir",
            member_id=member_id,
            owner_id=owner_id,
            payload={
                "privacy_level": level,
                "resource_count": len(resources),
            },
        )
        conn.commit()
        return result
    finally:
        conn.close()


def _output(data: dict, output_path: str = None):
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(json.dumps({"status": "ok", "message": f"已导出到 {output_path}"}, ensure_ascii=False))
    else:
        print(text)


def cmd_fhir(args):
    level = args.privacy_level or privacy.get_default_privacy_level()
    result = export_fhir(args.member_id, level, getattr(args, "owner_id", None))
    _output(result, args.output)


def cmd_statistics(args):
    ensure_db()
    conn = get_connection()
    try:
        owner_id = getattr(args, "owner_id", None)
        if args.member_id and not verify_member_ownership(conn, args.member_id, owner_id):
            _output({"error": f"无权访问成员: {args.member_id}"}, args.output)
            return
        stats = privacy.aggregate_statistics(conn, args.member_id, owner_id)
        _write_export_audit(
            conn,
            "export.statistics",
            member_id=args.member_id,
            owner_id=owner_id,
            payload={"scope": "member" if args.member_id else "owner", "member_count": stats.get("member_count")},
        )
        conn.commit()
        _output(stats, args.output)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="FHIR R4 导出与统计摘要")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fhir", help="导出 FHIR R4 Bundle")
    p.add_argument("--member-id", required=True, help="成员 ID")
    p.add_argument("--owner-id", default=None, help="所有者 ID")
    p.add_argument("--privacy-level", default=None, choices=["full", "anonymized", "statistical"])
    p.add_argument("--output", default=None, help="输出文件路径")

    p = sub.add_parser("statistics", help="导出聚合统计数据")
    p.add_argument("--member-id", default=None, help="成员 ID（不指定则全家聚合）")
    p.add_argument("--owner-id", default=None, help="所有者 ID")
    p.add_argument("--output", default=None, help="输出文件路径")

    args = parser.parse_args()
    commands = {"fhir": cmd_fhir, "statistics": cmd_statistics}
    commands[args.command](args)


if __name__ == "__main__":
    main()
