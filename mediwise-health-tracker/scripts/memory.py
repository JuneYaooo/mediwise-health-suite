"""Memory and data compression management for MediWise Health Tracker.

Implements two core strategies:
1. Hierarchical summarization (inspired by claude-mem):
   - Observations: atomic facts extracted from each interaction
   - Member summaries: compressed health profiles per member
   - Compression log: tracks compression history and token savings

2. Priority-based compression (inspired by patient_data_crew):
   - Critical data (never compressed): diagnoses, allergies, active medications
   - Important data (preserved when possible): lab results, imaging, symptoms
   - Optional data (compressed first): historical visit details, old metrics
"""

from __future__ import annotations

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from health_db import ensure_db, get_connection, generate_id, now_iso, row_to_dict, rows_to_list, output_json, is_api_mode
import api_client

# Token estimation: ~2 chars per token for Chinese, ~4 for English
CHARS_PER_TOKEN_CN = 2
CHARS_PER_TOKEN_EN = 4


def estimate_tokens(text):
    """Estimate token count for mixed Chinese/English text."""
    if not text:
        return 0
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - cn_chars
    return int(cn_chars / CHARS_PER_TOKEN_CN + other_chars / CHARS_PER_TOKEN_EN)


# --- Priority definitions for compression ---
CRITICAL_FIELDS = {
    "member": ["name", "relation", "gender", "birth_date", "blood_type", "allergies"],
    "visit": ["visit_date", "visit_type", "hospital", "department", "diagnosis"],
    "medication": ["name", "dosage", "frequency", "is_active", "start_date", "purpose"],
}

IMPORTANT_FIELDS = {
    "visit": ["chief_complaint", "summary"],
    "symptom": ["symptom", "severity", "onset_date"],
    "lab_result": ["test_name", "test_date", "items"],
    "imaging": ["exam_name", "exam_date", "conclusion"],
}


# --- Observations ---

def add_observation(args):
    """Record an atomic observation from a user interaction."""
    if is_api_mode():
        data = {
            "member_id": args.member_id, "type": args.type,
            "title": args.title, "facts": args.facts,
        }
        if args.narrative:
            data["narrative"] = args.narrative
        if args.source_records:
            data["source_records"] = args.source_records
        try:
            result = api_client.add_observation(data)
            output_json({"status": "ok", "message": f"已记录观察: {args.title}", "observation": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        obs_id = generate_id()
        facts = args.facts
        # Accept JSON array or comma-separated string
        if isinstance(facts, str) and not facts.startswith("["):
            facts = json.dumps([f.strip() for f in facts.split(",")], ensure_ascii=False)

        narrative = args.narrative or ""
        source_records = args.source_records or "[]"
        discovery_tokens = estimate_tokens(narrative) + estimate_tokens(facts)

        conn.execute(
            """INSERT INTO observations (id, member_id, obs_type, title, facts, narrative,
               source_records, discovery_tokens, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (obs_id, args.member_id, args.type, args.title, facts, narrative,
             source_records, discovery_tokens, now_iso())
        )
        conn.commit()
        obs = row_to_dict(conn.execute("SELECT * FROM observations WHERE id=?", (obs_id,)).fetchone())
        obs["facts"] = json.loads(obs["facts"])
        output_json({"status": "ok", "message": f"已记录观察: {args.title}", "observation": obs})
    finally:
        conn.close()


def list_observations(args):
    """List observations, optionally filtered by member and type."""
    if is_api_mode():
        try:
            result = api_client.list_observations(
                member_id=getattr(args, 'member_id', None),
                obs_type=getattr(args, 'type', None),
                limit=getattr(args, 'limit', None),
            )
            obs = result if isinstance(result, list) else result.get("observations", [])
            output_json({"status": "ok", "count": len(obs), "observations": obs})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        sql = "SELECT * FROM observations WHERE is_deleted=0"
        params = []
        if args.member_id:
            sql += " AND member_id=?"
            params.append(args.member_id)
        if args.type:
            sql += " AND obs_type=?"
            params.append(args.type)
        sql += " ORDER BY created_at DESC"
        if args.limit:
            sql += " LIMIT ?"
            params.append(int(args.limit))

        rows = conn.execute(sql, params).fetchall()
        observations = rows_to_list(rows)
        for obs in observations:
            try:
                obs["facts"] = json.loads(obs["facts"])
            except (json.JSONDecodeError, TypeError):
                pass
        output_json({"status": "ok", "count": len(observations), "observations": observations})
    finally:
        conn.close()


# --- Member Summaries ---

def generate_summary(args):
    """Generate or update a compressed summary for a member.

    Summary types:
    - profile: basic info + allergies + medical history
    - diagnosis_history: all diagnoses with timeline
    - medication_history: all medications (active + stopped)
    - recent_activity: recent visits, symptoms, metrics (last 90 days)
    """
    if is_api_mode():
        try:
            result = api_client.generate_summary(args.member_id, args.type)
            output_json({"status": "ok", "message": "摘要已生成", "data": result})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        member = row_to_dict(conn.execute(
            "SELECT * FROM members WHERE id=? AND is_deleted=0", (args.member_id,)
        ).fetchone())
        if not member:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        summary_type = args.type
        generators = {
            "profile": _gen_profile_summary,
            "diagnosis_history": _gen_diagnosis_summary,
            "medication_history": _gen_medication_summary,
            "recent_activity": _gen_recent_summary,
        }

        if summary_type == "all":
            results = {}
            total_tokens = 0
            for st, gen_fn in generators.items():
                content, facts, token_count = gen_fn(conn, args.member_id, member)
                _save_summary(conn, args.member_id, st, content, facts, token_count)
                results[st] = {"token_count": token_count, "facts_count": len(facts)}
                total_tokens += token_count
            conn.commit()
            output_json({
                "status": "ok",
                "message": f"已为{member['name']}生成全部摘要",
                "member": member["name"],
                "summaries": results,
                "total_tokens": total_tokens
            })
        elif summary_type in generators:
            content, facts, token_count = generators[summary_type](conn, args.member_id, member)
            _save_summary(conn, args.member_id, summary_type, content, facts, token_count)
            conn.commit()
            output_json({
                "status": "ok",
                "message": f"已为{member['name']}生成{summary_type}摘要",
                "summary": {"type": summary_type, "content": content, "facts": facts, "token_count": token_count}
            })
        else:
            output_json({"status": "error", "message": f"不支持的摘要类型: {summary_type}，支持: {', '.join(list(generators.keys()) + ['all'])}"})
    finally:
        conn.close()


def _save_summary(conn, member_id, summary_type, content, facts, token_count):
    """Insert or update a member summary."""
    existing = conn.execute(
        "SELECT id FROM member_summaries WHERE member_id=? AND summary_type=? AND is_deleted=0",
        (member_id, summary_type)
    ).fetchone()

    ts = now_iso()
    facts_json = json.dumps(facts, ensure_ascii=False)
    source_count = len(facts)

    if existing:
        # Log compression
        old = conn.execute("SELECT token_count FROM member_summaries WHERE id=?", (existing["id"],)).fetchone()
        old_tokens = old["token_count"] if old else 0

        conn.execute(
            """UPDATE member_summaries SET content=?, facts=?, source_count=?,
               token_count=?, updated_at=? WHERE id=?""",
            (content, facts_json, source_count, token_count, ts, existing["id"])
        )

        if old_tokens > 0:
            _log_compression(conn, member_id, f"update_{summary_type}", old_tokens, token_count)
    else:
        sid = generate_id()
        conn.execute(
            """INSERT INTO member_summaries (id, member_id, summary_type, content, facts,
               source_count, token_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, member_id, summary_type, content, facts_json, source_count, token_count, ts, ts)
        )


def _log_compression(conn, member_id, action, original_tokens, compressed_tokens):
    """Log a compression event."""
    ratio = compressed_tokens / original_tokens if original_tokens > 0 else 1.0
    conn.execute(
        """INSERT INTO compression_log (id, member_id, action, original_tokens,
           compressed_tokens, compression_ratio, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (generate_id(), member_id, action, original_tokens, compressed_tokens, ratio, now_iso())
    )


def _gen_profile_summary(conn, member_id, member):
    """Generate profile summary with critical info."""
    facts = []
    content_parts = []

    # Basic info (critical, always preserved)
    name = member["name"]
    facts.append(f"{name}，{member.get('relation', '未知')}，{member.get('gender', '未知')}")
    if member.get("birth_date"):
        facts.append(f"出生日期: {member['birth_date']}")
    if member.get("blood_type"):
        facts.append(f"血型: {member['blood_type']}")
    if member.get("allergies"):
        facts.append(f"过敏史: {member['allergies']}")
    if member.get("medical_history"):
        facts.append(f"既往病史: {member['medical_history']}")
    if member.get("phone"):
        facts.append(f"联系电话: {member['phone']}")

    content = f"【{name}健康档案】\n" + "\n".join(f"- {f}" for f in facts)
    return content, facts, estimate_tokens(content)


def _gen_diagnosis_summary(conn, member_id, member):
    """Generate diagnosis history summary."""
    facts = []
    visits = conn.execute(
        """SELECT visit_date, visit_type, hospital, department, diagnosis
           FROM visits WHERE member_id=? AND is_deleted=0 AND diagnosis IS NOT NULL
           ORDER BY visit_date""",
        (member_id,)
    ).fetchall()

    diagnoses_seen = {}
    for v in visits:
        if v["diagnosis"]:
            for d in v["diagnosis"].split(","):
                d = d.strip()
                if d:
                    if d not in diagnoses_seen:
                        diagnoses_seen[d] = []
                    diagnoses_seen[d].append({
                        "date": v["visit_date"],
                        "hospital": v["hospital"],
                        "type": v["visit_type"]
                    })

    for diag, records in diagnoses_seen.items():
        first = records[0]
        fact = f"诊断: {diag}，首次发现于{first['date']}（{first['hospital'] or '未知医院'}）"
        if len(records) > 1:
            fact += f"，共{len(records)}次就诊记录"
        facts.append(fact)

    if not facts:
        facts.append("暂无诊断记录")

    content = f"【{member['name']}诊断历史】\n" + "\n".join(f"- {f}" for f in facts)
    return content, facts, estimate_tokens(content)


def _gen_medication_summary(conn, member_id, member):
    """Generate medication history summary."""
    facts = []

    # Active medications (critical)
    active = conn.execute(
        """SELECT name, dosage, frequency, start_date, purpose
           FROM medications WHERE member_id=? AND is_active=1 AND is_deleted=0
           ORDER BY start_date DESC""",
        (member_id,)
    ).fetchall()

    for m in active:
        fact = f"[在用] {m['name']}"
        if m["dosage"]:
            fact += f" {m['dosage']}"
        if m["frequency"]:
            fact += f" {m['frequency']}"
        if m["start_date"]:
            fact += f"，自{m['start_date']}起"
        if m["purpose"]:
            fact += f"（{m['purpose']}）"
        facts.append(fact)

    # Stopped medications (compressed: only name + reason)
    stopped = conn.execute(
        """SELECT name, start_date, end_date, stop_reason
           FROM medications WHERE member_id=? AND is_active=0 AND is_deleted=0
           ORDER BY end_date DESC LIMIT 20""",
        (member_id,)
    ).fetchall()

    for m in stopped:
        fact = f"[已停] {m['name']}（{m['start_date'] or '?'}~{m['end_date'] or '?'}）"
        if m["stop_reason"]:
            fact += f" 原因: {m['stop_reason']}"
        facts.append(fact)

    if not facts:
        facts.append("暂无用药记录")

    content = f"【{member['name']}用药记录】\n" + "\n".join(f"- {f}" for f in facts)
    return content, facts, estimate_tokens(content)


def _gen_recent_summary(conn, member_id, member):
    """Generate recent activity summary (last 90 days)."""
    facts = []

    # Recent visits
    visits = conn.execute(
        """SELECT visit_date, visit_type, hospital, department, diagnosis, summary
           FROM visits WHERE member_id=? AND is_deleted=0
           AND visit_date >= date('now', '-90 days')
           ORDER BY visit_date DESC LIMIT 10""",
        (member_id,)
    ).fetchall()

    for v in visits:
        fact = f"{v['visit_date']} {v['visit_type']}@{v['hospital'] or '未知'}"
        if v["diagnosis"]:
            fact += f" 诊断:{v['diagnosis']}"
        facts.append(fact)

    # Recent symptoms
    symptoms = conn.execute(
        """SELECT symptom, severity, onset_date
           FROM symptoms WHERE member_id=? AND is_deleted=0
           AND (onset_date >= date('now', '-90 days') OR onset_date IS NULL)
           ORDER BY onset_date DESC LIMIT 10""",
        (member_id,)
    ).fetchall()

    for s in symptoms:
        fact = f"症状: {s['symptom']}"
        if s["severity"]:
            fact += f"（{s['severity']}）"
        if s["onset_date"]:
            fact += f" 自{s['onset_date']}"
        facts.append(fact)

    # Latest metrics
    metrics = conn.execute(
        """SELECT metric_type, value, measured_at FROM health_metrics
           WHERE member_id=? AND is_deleted=0
           AND measured_at >= date('now', '-90 days')
           ORDER BY measured_at DESC""",
        (member_id,)
    ).fetchall()

    type_names = {
        "blood_pressure": "血压", "blood_sugar": "血糖", "heart_rate": "心率",
        "weight": "体重", "temperature": "体温", "blood_oxygen": "血氧"
    }
    seen_types = set()
    for m in metrics:
        mt = m["metric_type"]
        if mt not in seen_types:
            seen_types.add(mt)
            val = m["value"]
            if mt == "blood_pressure":
                try:
                    v = json.loads(val)
                    val = f"{v['systolic']}/{v['diastolic']}mmHg"
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
            facts.append(f"最近{type_names.get(mt, mt)}: {val}（{m['measured_at']}）")

    if not facts:
        facts.append("近90天无活动记录")

    content = f"【{member['name']}近期动态】\n" + "\n".join(f"- {f}" for f in facts)
    return content, facts, estimate_tokens(content)


def get_summary(args):
    """Get existing summaries for a member."""
    if is_api_mode():
        try:
            result = api_client.get_memory_summary(args.member_id, getattr(args, 'type', 'all'))
            output_json({"status": "ok", **(result if isinstance(result, dict) else {"data": result})})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        sql = "SELECT * FROM member_summaries WHERE member_id=? AND is_deleted=0"
        params = [args.member_id]
        if args.type and args.type != "all":
            sql += " AND summary_type=?"
            params.append(args.type)
        sql += " ORDER BY summary_type"

        rows = conn.execute(sql, params).fetchall()
        summaries = rows_to_list(rows)
        for s in summaries:
            try:
                s["facts"] = json.loads(s["facts"])
            except (json.JSONDecodeError, TypeError):
                pass

        total_tokens = sum(s.get("token_count", 0) for s in summaries)
        output_json({
            "status": "ok",
            "count": len(summaries),
            "total_tokens": total_tokens,
            "summaries": summaries
        })
    finally:
        conn.close()


def get_context(args):
    """Build a compressed context for a member, suitable for injecting into LLM prompts.

    Combines all summaries into a single compressed text block with token budget awareness.
    Priority order: profile > diagnosis > medication > recent_activity > observations
    """
    if is_api_mode():
        try:
            result = api_client.get_memory_context(args.member_id, getattr(args, 'max_tokens', None))
            output_json({"status": "ok", **(result if isinstance(result, dict) else {"data": result})})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        member = row_to_dict(conn.execute(
            "SELECT * FROM members WHERE id=? AND is_deleted=0", (args.member_id,)
        ).fetchone())
        if not member:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        max_tokens = int(args.max_tokens) if args.max_tokens else 4000
        context_parts = []
        used_tokens = 0

        # Priority 1: Profile (critical, always included)
        profile = conn.execute(
            "SELECT content, token_count FROM member_summaries WHERE member_id=? AND summary_type='profile' AND is_deleted=0",
            (args.member_id,)
        ).fetchone()
        if profile:
            context_parts.append(profile["content"])
            used_tokens += profile["token_count"]

        # Priority 2: Diagnosis history
        diag = conn.execute(
            "SELECT content, token_count FROM member_summaries WHERE member_id=? AND summary_type='diagnosis_history' AND is_deleted=0",
            (args.member_id,)
        ).fetchone()
        if diag and used_tokens + diag["token_count"] <= max_tokens:
            context_parts.append(diag["content"])
            used_tokens += diag["token_count"]

        # Priority 3: Active medications
        med = conn.execute(
            "SELECT content, token_count FROM member_summaries WHERE member_id=? AND summary_type='medication_history' AND is_deleted=0",
            (args.member_id,)
        ).fetchone()
        if med and used_tokens + med["token_count"] <= max_tokens:
            context_parts.append(med["content"])
            used_tokens += med["token_count"]

        # Priority 4: Recent activity
        recent = conn.execute(
            "SELECT content, token_count FROM member_summaries WHERE member_id=? AND summary_type='recent_activity' AND is_deleted=0",
            (args.member_id,)
        ).fetchone()
        if recent and used_tokens + recent["token_count"] <= max_tokens:
            context_parts.append(recent["content"])
            used_tokens += recent["token_count"]

        # Priority 5: Recent observations (fill remaining budget)
        remaining = max_tokens - used_tokens
        if remaining > 100:
            obs_rows = conn.execute(
                """SELECT title, facts FROM observations
                   WHERE (member_id=? OR member_id IS NULL) AND is_deleted=0
                   ORDER BY created_at DESC LIMIT 20""",
                (args.member_id,)
            ).fetchall()
            obs_parts = []
            for o in obs_rows:
                line = f"- {o['title']}"
                tokens = estimate_tokens(line)
                if used_tokens + tokens > max_tokens:
                    break
                obs_parts.append(line)
                used_tokens += tokens
            if obs_parts:
                context_parts.append("【近期观察】\n" + "\n".join(obs_parts))

        context = "\n\n".join(context_parts)

        output_json({
            "status": "ok",
            "member": member["name"],
            "token_count": used_tokens,
            "max_tokens": max_tokens,
            "utilization": f"{used_tokens/max_tokens*100:.1f}%",
            "context": context
        })
    finally:
        conn.close()


def compression_stats(args):
    """Show compression statistics."""
    if is_api_mode():
        try:
            result = api_client.get_memory_stats()
            output_json({"status": "ok", **(result if isinstance(result, dict) else {"data": result})})
        except api_client.APIError as e:
            output_json({"status": "error", "message": str(e)})
        return
    ensure_db()
    conn = get_connection()
    try:
        # Overall stats
        total_raw = 0
        total_compressed = 0

        # Count raw data tokens per member
        members = conn.execute("SELECT id, name FROM members WHERE is_deleted=0").fetchall()
        member_stats = []

        for m in members:
            mid = m["id"]
            raw_tokens = 0

            # Count visits
            for row in conn.execute("SELECT * FROM visits WHERE member_id=? AND is_deleted=0", (mid,)).fetchall():
                raw_tokens += estimate_tokens(json.dumps(dict(row), ensure_ascii=False))

            # Count medications
            for row in conn.execute("SELECT * FROM medications WHERE member_id=? AND is_deleted=0", (mid,)).fetchall():
                raw_tokens += estimate_tokens(json.dumps(dict(row), ensure_ascii=False))

            # Count lab results
            for row in conn.execute("SELECT * FROM lab_results WHERE member_id=? AND is_deleted=0", (mid,)).fetchall():
                raw_tokens += estimate_tokens(json.dumps(dict(row), ensure_ascii=False))

            # Count imaging
            for row in conn.execute("SELECT * FROM imaging_results WHERE member_id=? AND is_deleted=0", (mid,)).fetchall():
                raw_tokens += estimate_tokens(json.dumps(dict(row), ensure_ascii=False))

            # Count symptoms
            for row in conn.execute("SELECT * FROM symptoms WHERE member_id=? AND is_deleted=0", (mid,)).fetchall():
                raw_tokens += estimate_tokens(json.dumps(dict(row), ensure_ascii=False))

            # Count metrics
            for row in conn.execute("SELECT * FROM health_metrics WHERE member_id=? AND is_deleted=0", (mid,)).fetchall():
                raw_tokens += estimate_tokens(json.dumps(dict(row), ensure_ascii=False))

            # Compressed tokens
            compressed = conn.execute(
                "SELECT COALESCE(SUM(token_count), 0) as total FROM member_summaries WHERE member_id=? AND is_deleted=0",
                (mid,)
            ).fetchone()["total"]

            ratio = compressed / raw_tokens if raw_tokens > 0 else 0
            savings = max(0, raw_tokens - compressed)

            member_stats.append({
                "name": m["name"],
                "raw_tokens": raw_tokens,
                "compressed_tokens": compressed,
                "compression_ratio": f"{ratio:.1%}",
                "token_savings": savings
            })

            total_raw += raw_tokens
            total_compressed += compressed

        # Compression log
        recent_logs = rows_to_list(conn.execute(
            "SELECT * FROM compression_log ORDER BY created_at DESC LIMIT 10"
        ).fetchall())

        output_json({
            "status": "ok",
            "total_raw_tokens": total_raw,
            "total_compressed_tokens": total_compressed,
            "overall_ratio": f"{total_compressed/total_raw:.1%}" if total_raw > 0 else "N/A",
            "total_savings": max(0, total_raw - total_compressed),
            "members": member_stats,
            "recent_compression_log": recent_logs
        })
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="记忆与数据压缩管理")
    sub = parser.add_subparsers(dest="command", required=True)

    # Observations
    p = sub.add_parser("add-observation", help="记录一条观察")
    p.add_argument("--member-id", default=None)
    p.add_argument("--type", required=True, help="类型: diagnosis, medication, symptom, metric, visit, note")
    p.add_argument("--title", required=True, help="观察标题")
    p.add_argument("--facts", required=True, help="原子事实（JSON数组或逗号分隔）")
    p.add_argument("--narrative", default=None, help="完整叙述")
    p.add_argument("--source-records", default=None, help="来源记录ID（JSON数组）")

    p = sub.add_parser("list-observations", help="列出观察记录")
    p.add_argument("--member-id", default=None)
    p.add_argument("--type", default=None)
    p.add_argument("--limit", default=None)

    # Summaries
    p = sub.add_parser("generate-summary", help="生成成员摘要")
    p.add_argument("--member-id", required=True)
    p.add_argument("--type", required=True, help="摘要类型: profile, diagnosis_history, medication_history, recent_activity, all")

    p = sub.add_parser("get-summary", help="获取成员摘要")
    p.add_argument("--member-id", required=True)
    p.add_argument("--type", default="all")

    # Context
    p = sub.add_parser("get-context", help="获取成员压缩上下文（用于注入LLM）")
    p.add_argument("--member-id", required=True)
    p.add_argument("--max-tokens", default="4000", help="最大token数")

    # Stats
    sub.add_parser("stats", help="查看压缩统计")

    args = parser.parse_args()
    commands = {
        "add-observation": add_observation,
        "list-observations": list_observations,
        "generate-summary": generate_summary,
        "get-summary": get_summary,
        "get-context": get_context,
        "stats": compression_stats,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
