"""Privacy filtering module for MediWise Health Tracker.

Three privacy levels:
- full: all data including PII (self-use, family doctor)
- anonymized: medical data intact, PII replaced with pseudonyms (AI doctor consultation)
- statistical: aggregate statistics only (insurance assessment)
"""

from __future__ import annotations

import os
import sys
import json
import re
from collections import defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from config import load_config

VALID_LEVELS = ("full", "anonymized", "statistical")

PII_FIELDS = ["name", "phone", "emergency_contact", "emergency_phone"]


def get_default_privacy_level() -> str:
    """Read default privacy level from config.json, default 'anonymized'."""
    cfg = load_config()
    level = cfg.get("privacy", {}).get("default_level", "anonymized")
    if level not in VALID_LEVELS:
        return "anonymized"
    return level


# Deterministic pseudonym mapping based on member_id hash
_PSEUDONYM_LABELS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _get_pseudonym(member_id: str) -> str:
    """Deterministic pseudonym mapping based on member_id hash.

    Same member_id always maps to the same pseudonym, regardless of
    process restarts or call order.
    """
    idx = hash(member_id) % len(_PSEUDONYM_LABELS)
    return f"成员{_PSEUDONYM_LABELS[idx]}"


# Regex patterns for Chinese PII
_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_ID_CARD_RE = re.compile(r"\d{17}[\dXx]")


def _get_member_names(member_id):
    """Query real member name from DB. Returns list of name strings."""
    try:
        from health_db import get_connection
        conn = get_connection()
        try:
            row = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (member_id,)).fetchone()
            if row and row["name"]:
                return [row["name"]]
        finally:
            conn.close()
    except Exception:
        pass
    return []


def _redact_text(text, names, pseudonym):
    """Replace known names and regex-matched PII in text."""
    if not text or not isinstance(text, str):
        return text
    for name in names:
        if name and name in text:
            text = text.replace(name, pseudonym)
    text = _PHONE_RE.sub("***手机号***", text)
    text = _ID_CARD_RE.sub("***身份证号***", text)
    return text


def filter_member(member: dict, level: str) -> dict:
    """Filter a member dict according to privacy level.

    - full: return as-is
    - anonymized: replace PII fields with pseudonyms, keep medical fields
    - statistical: return None (individual data not exposed)
    """
    if level not in VALID_LEVELS:
        level = "anonymized"
    if member is None:
        return None
    if level == "full":
        return dict(member)
    if level == "statistical":
        return None
    # anonymized
    result = dict(member)
    pseudonym = _get_pseudonym(result.get("id", "unknown"))
    result["name"] = pseudonym
    result["phone"] = None
    result["emergency_contact"] = None
    result["emergency_phone"] = None
    return result


def filter_record(record: dict, level: str) -> dict:
    """Filter a medical record dict according to privacy level.

    - full: return as-is
    - anonymized: remove member name references, keep medical content
    - statistical: return None (individual records not exposed)
    """
    if level not in VALID_LEVELS:
        level = "anonymized"
    if record is None:
        return None
    if level == "full":
        return dict(record)
    if level == "statistical":
        return None
    # anonymized: remove name references from text fields
    result = dict(record)
    member_id = result.get("member_id")
    if member_id:
        pseudonym = _get_pseudonym(member_id)
        names = _get_member_names(member_id)
        # Redact known names and PII patterns in free-text fields
        for field in ("summary", "description", "chief_complaint", "note",
                      "diagnosis", "findings", "conclusion"):
            if result.get(field) and isinstance(result[field], str):
                result[field] = _redact_text(result[field], names, pseudonym)
    # Remove any direct name fields if present
    for f in PII_FIELDS:
        if f in result:
            result[f] = None
    return result


def aggregate_statistics(db_conn, member_id: str = None, owner_id: str = None) -> dict:
    """Return aggregate statistics: diagnosis distribution, medication categories,
    metric trends, visit frequency.

    If member_id is None, aggregate across all family members.
    """
    where = ""
    params = ()
    if member_id:
        where = " AND member_id=?"
        params = (member_id,)
    elif owner_id:
        member_rows = db_conn.execute(
            "SELECT id FROM members WHERE is_deleted=0 AND owner_id=?",
            (owner_id,)
        ).fetchall()
        member_ids = [row["id"] for row in member_rows]
        if member_ids:
            placeholders = ",".join("?" for _ in member_ids)
            where = f" AND member_id IN ({placeholders})"
            params = tuple(member_ids)
        else:
            where = " AND 1=0"
            params = ()

    stats = {}

    # Diagnosis distribution
    rows = db_conn.execute(
        f"SELECT diagnosis, COUNT(*) as cnt FROM visits WHERE is_deleted=0{where} AND diagnosis IS NOT NULL GROUP BY diagnosis ORDER BY cnt DESC",
        params
    ).fetchall()
    stats["diagnosis_distribution"] = [{"diagnosis": r["diagnosis"], "count": r["cnt"]} for r in rows]

    # Medication categories (by purpose)
    rows = db_conn.execute(
        f"SELECT purpose, COUNT(*) as cnt FROM medications WHERE is_deleted=0{where} GROUP BY purpose ORDER BY cnt DESC",
        params
    ).fetchall()
    stats["medication_categories"] = [{"purpose": r["purpose"] or "未分类", "count": r["cnt"]} for r in rows]

    # Active medication count
    row = db_conn.execute(
        f"SELECT COUNT(*) as cnt FROM medications WHERE is_deleted=0 AND end_date IS NULL{where}",
        params
    ).fetchone()
    stats["active_medication_count"] = row["cnt"] if row else 0

    # Visit frequency by type
    rows = db_conn.execute(
        f"SELECT visit_type, COUNT(*) as cnt FROM visits WHERE is_deleted=0{where} GROUP BY visit_type ORDER BY cnt DESC",
        params
    ).fetchall()
    stats["visit_frequency"] = [{"visit_type": r["visit_type"], "count": r["cnt"]} for r in rows]

    # Total visits
    row = db_conn.execute(
        f"SELECT COUNT(*) as cnt FROM visits WHERE is_deleted=0{where}",
        params
    ).fetchone()
    stats["total_visits"] = row["cnt"] if row else 0

    # Health metric trends (latest 10 per type)
    metric_types = db_conn.execute(
        f"SELECT DISTINCT metric_type FROM health_metrics WHERE is_deleted=0{where}",
        params
    ).fetchall()
    trends = {}
    for mt in metric_types:
        mtype = mt["metric_type"]
        rows = db_conn.execute(
            f"SELECT metric_type, value, measured_at FROM health_metrics WHERE is_deleted=0 AND metric_type=?{where} ORDER BY measured_at DESC LIMIT 10",
            (mtype, *params)
        ).fetchall()
        trends[mtype] = [{"value": r["value"], "measured_at": r["measured_at"]} for r in rows]
    stats["metric_trends"] = trends

    # Symptom count
    row = db_conn.execute(
        f"SELECT COUNT(*) as cnt FROM symptoms WHERE is_deleted=0{where}",
        params
    ).fetchone()
    stats["total_symptoms"] = row["cnt"] if row else 0

    # Member count (only when aggregating all)
    if not member_id:
        if owner_id:
            row = db_conn.execute(
                "SELECT COUNT(*) as cnt FROM members WHERE is_deleted=0 AND owner_id=?",
                (owner_id,)
            ).fetchone()
        else:
            row = db_conn.execute("SELECT COUNT(*) as cnt FROM members WHERE is_deleted=0").fetchone()
        stats["member_count"] = row["cnt"] if row else 0

    return stats
