"""Vector semantic search for MediWise Health Tracker.

Usage:
  python3 scripts/vector_search.py search --query "胸口不舒服" [--member-id X] [--limit 10]
  python3 scripts/vector_search.py index [--member-id X]
  python3 scripts/vector_search.py reindex [--member-id X]
  python3 scripts/vector_search.py status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)

sys.path.insert(0, os.path.dirname(__file__))
from health_db import ensure_db, get_connection, rows_to_list, output_json, generate_id, now_iso
from config import get_embedding_config, load_config, save_config, DATA_DIR
from embedding_provider import (
    get_provider, text_hash, embedding_to_blob, blob_to_embedding, cosine_similarity
)

# hnswlib is optional
try:
    import hnswlib
    HAS_HNSWLIB = True
except ImportError:
    HAS_HNSWLIB = False


VECTOR_INDEX_PATH = os.path.join(DATA_DIR, "vector.idx")

# Record type -> (table, text fields to concatenate)
RECORD_TEXT_MAP = {
    "visit": ("visits", ["diagnosis", "chief_complaint", "summary"]),
    "symptom": ("symptoms", ["symptom", "description"]),
    "medication": ("medications", ["name", "purpose"]),
    "lab_result": ("lab_results", ["test_name"]),
    "imaging": ("imaging_results", ["exam_name", "findings", "conclusion"]),
    "observation": ("observations", ["title", "facts"]),
    "member_summary": ("member_summaries", ["content"]),
}


def _build_text(row, fields):
    """Concatenate non-empty fields from a row into a single text."""
    parts = []
    for f in fields:
        val = row.get(f)
        if val and str(val).strip():
            parts.append(str(val).strip())
    return " ".join(parts)


def _collect_records(conn, member_id=None):
    """Collect all indexable records. Returns list of (record_type, record_id, text)."""
    records = []
    for rec_type, (table, fields) in RECORD_TEXT_MAP.items():
        if member_id:
            if rec_type == "member_summary":
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE member_id=? AND is_deleted=0", (member_id,)
                ).fetchall()
            elif rec_type == "observation":
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE (member_id=? OR member_id IS NULL) AND is_deleted=0",
                    (member_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE member_id=? AND is_deleted=0", (member_id,)
                ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM {table} WHERE is_deleted=0"
            ).fetchall()

        for row in rows:
            row = dict(row)
            text = _build_text(row, fields)
            if text:
                records.append((rec_type, row["id"], text))
    return records


def _get_existing_hashes(conn):
    """Get existing embeddings as {(record_type, record_id): (text_hash, id)}."""
    rows = conn.execute("SELECT id, record_type, record_id, text_hash FROM embeddings").fetchall()
    return {(r["record_type"], r["record_id"]): (r["text_hash"], r["id"]) for r in rows}


def _save_embeddings(conn, items, provider):
    """Save embedding results to DB. items: list of (record_type, record_id, text, embedding)."""
    now = now_iso()
    for rec_type, rec_id, text, emb in items:
        blob = embedding_to_blob(emb)
        h = text_hash(text)
        eid = generate_id()
        conn.execute(
            """INSERT OR REPLACE INTO embeddings
               (id, record_type, record_id, embedding, text_content, text_hash, model_name, dimensions, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (eid, rec_type, rec_id, blob, text, h, provider.model_name, provider.dimensions, now)
        )
    conn.commit()


def _build_hnsw_index(conn):
    """Build hnswlib index from all embeddings in DB. Returns (index, id_list) or (None, None)."""
    if not HAS_HNSWLIB:
        return None, None

    rows = conn.execute("SELECT id, embedding, dimensions FROM embeddings WHERE embedding IS NOT NULL").fetchall()
    if not rows:
        return None, None

    dim = rows[0]["dimensions"]
    if not dim:
        blob = rows[0]["embedding"]
        dim = len(blob) // 4

    index = hnswlib.Index(space="cosine", dim=dim)
    index.init_index(max_elements=max(len(rows), 100), ef_construction=200, M=16)

    ids = []
    for i, row in enumerate(rows):
        emb = blob_to_embedding(row["embedding"])
        index.add_items([emb], [i])
        ids.append(row["id"])

    index.set_ef(50)
    return index, ids


def _save_hnsw_index(index):
    """Save hnswlib index to disk."""
    if index is not None and HAS_HNSWLIB:
        os.makedirs(os.path.dirname(VECTOR_INDEX_PATH), exist_ok=True)
        index.save_index(VECTOR_INDEX_PATH)


def _brute_force_search(conn, query_embedding, limit=10, member_id=None):
    """Fallback: brute-force cosine similarity search using SQLite BLOBs."""
    if member_id:
        # Join with source tables to filter by member_id
        rows = conn.execute(
            "SELECT e.id, e.record_type, e.record_id, e.embedding, e.text_content FROM embeddings e"
        ).fetchall()
        # Filter by member_id post-query (simpler than joining all tables)
        member_records = set()
        for rec_type, (table, _) in RECORD_TEXT_MAP.items():
            try:
                mrows = conn.execute(
                    f"SELECT id FROM {table} WHERE member_id=? AND is_deleted=0", (member_id,)
                ).fetchall()
                for mr in mrows:
                    member_records.add((rec_type, mr["id"]))
            except Exception:
                pass
        rows = [r for r in rows if (r["record_type"], r["record_id"]) in member_records]
    else:
        rows = conn.execute(
            "SELECT id, record_type, record_id, embedding, text_content FROM embeddings WHERE embedding IS NOT NULL"
        ).fetchall()

    scored = []
    for row in rows:
        emb = blob_to_embedding(row["embedding"])
        sim = cosine_similarity(query_embedding, emb)
        scored.append({
            "embedding_id": row["id"],
            "record_type": row["record_type"],
            "record_id": row["record_id"],
            "text_content": row["text_content"],
            "score": round(sim, 4)
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def _enrich_results(conn, results):
    """Attach source record details to search results."""
    for r in results:
        rec_type = r["record_type"]
        rec_id = r["record_id"]
        if rec_type in RECORD_TEXT_MAP:
            table = RECORD_TEXT_MAP[rec_type][0]
            try:
                row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (rec_id,)).fetchone()
                if row:
                    r["record"] = dict(row)
            except Exception:
                pass
    return results


def cmd_index(args):
    """Incremental index: only embed records that are new or changed."""
    ensure_db()
    provider = get_provider()
    if provider.name == "none":
        output_json({
            "status": "warning",
            "message": "无可用的 Embedding 模型。请安装 sentence-transformers 或配置硅基智能 API。",
            "hint": "pip install sentence-transformers 或 python3 setup.py set-embedding --provider siliconflow --api-key <key>"
        })
        return

    conn = get_connection()
    try:
        member_id = getattr(args, "member_id", None)
        records = _collect_records(conn, member_id)
        existing = _get_existing_hashes(conn)

        # Find records that need embedding (new or changed)
        to_embed = []
        for rec_type, rec_id, text in records:
            h = text_hash(text)
            key = (rec_type, rec_id)
            if key in existing and existing[key][0] == h:
                continue  # unchanged
            to_embed.append((rec_type, rec_id, text))

        if not to_embed:
            output_json({"status": "ok", "message": "所有记录已是最新，无需索引", "total_records": len(records)})
            return

        # Batch encode
        texts = [t[2] for t in to_embed]
        embeddings = provider.encode(texts)
        if embeddings is None:
            output_json({"status": "error", "message": "Embedding 编码失败"})
            return

        items = [(t[0], t[1], t[2], e) for t, e in zip(to_embed, embeddings)]
        _save_embeddings(conn, items, provider)

        # Update dimensions in config if needed
        cfg = load_config()
        if provider.dimensions and cfg.get("embedding", {}).get("dimensions") != provider.dimensions:
            cfg.setdefault("embedding", {})["dimensions"] = provider.dimensions
            save_config(cfg)

        # Rebuild hnswlib index
        hnsw_index, _ = _build_hnsw_index(conn)
        _save_hnsw_index(hnsw_index)

        output_json({
            "status": "ok",
            "message": f"索引完成: 新增/更新 {len(items)} 条",
            "provider": provider.name,
            "model": provider.model_name,
            "indexed": len(items),
            "total_records": len(records),
            "hnswlib": HAS_HNSWLIB
        })
    finally:
        conn.close()


def cmd_reindex(args):
    """Full reindex: clear all embeddings and rebuild."""
    ensure_db()
    provider = get_provider()
    if provider.name == "none":
        output_json({
            "status": "warning",
            "message": "无可用的 Embedding 模型。请安装 sentence-transformers 或配置硅基智能 API。"
        })
        return

    conn = get_connection()
    try:
        member_id = getattr(args, "member_id", None)
        if member_id:
            # Delete embeddings for records belonging to this member
            for rec_type, (table, _) in RECORD_TEXT_MAP.items():
                try:
                    rec_ids = [r["id"] for r in conn.execute(
                        f"SELECT id FROM {table} WHERE member_id=? AND is_deleted=0", (member_id,)
                    ).fetchall()]
                    for rid in rec_ids:
                        conn.execute(
                            "DELETE FROM embeddings WHERE record_type=? AND record_id=?",
                            (rec_type, rid)
                        )
                except Exception:
                    pass
        else:
            conn.execute("DELETE FROM embeddings")
        conn.commit()

        # Remove old index file
        if os.path.exists(VECTOR_INDEX_PATH):
            os.remove(VECTOR_INDEX_PATH)

        records = _collect_records(conn, member_id)
        if not records:
            output_json({"status": "ok", "message": "无记录可索引", "total_records": 0})
            return

        texts = [r[2] for r in records]
        embeddings = provider.encode(texts)
        if embeddings is None:
            output_json({"status": "error", "message": "Embedding 编码失败"})
            return

        items = [(r[0], r[1], r[2], e) for r, e in zip(records, embeddings)]
        _save_embeddings(conn, items, provider)

        cfg = load_config()
        if provider.dimensions:
            cfg.setdefault("embedding", {})["dimensions"] = provider.dimensions
            save_config(cfg)

        hnsw_index, _ = _build_hnsw_index(conn)
        _save_hnsw_index(hnsw_index)

        output_json({
            "status": "ok",
            "message": f"全量重建完成: {len(items)} 条记录",
            "provider": provider.name,
            "model": provider.model_name,
            "indexed": len(items),
            "hnswlib": HAS_HNSWLIB
        })
    finally:
        conn.close()


def cmd_search(args):
    """Semantic search, with keyword fallback."""
    ensure_db()
    provider = get_provider()
    query = args.query
    limit = getattr(args, "limit", 10) or 10
    member_id = getattr(args, "member_id", None)

    if provider.name == "none":
        # Fallback to keyword search
        output_json({
            "status": "fallback",
            "message": "无 Embedding 模型，降级为关键词搜索。安装 sentence-transformers 可启用语义搜索。",
            "results": _keyword_fallback(query, member_id, limit)
        })
        return

    conn = get_connection()
    try:
        # Check if we have any embeddings
        count = conn.execute("SELECT COUNT(*) as c FROM embeddings").fetchone()["c"]
        if count == 0:
            output_json({
                "status": "fallback",
                "message": "尚未建立索引，降级为关键词搜索。请先运行: vector_search.py index",
                "results": _keyword_fallback(query, member_id, limit)
            })
            return

        # Encode query
        query_emb = provider.encode([query])
        if query_emb is None or len(query_emb) == 0:
            output_json({
                "status": "fallback",
                "message": "查询编码失败，降级为关键词搜索",
                "results": _keyword_fallback(query, member_id, limit)
            })
            return

        query_vec = query_emb[0]

        # Try hnswlib first
        results = None
        if HAS_HNSWLIB and os.path.exists(VECTOR_INDEX_PATH):
            try:
                dim = len(query_vec)
                index = hnswlib.Index(space="cosine", dim=dim)
                index.load_index(VECTOR_INDEX_PATH)
                index.set_ef(50)

                # Get all embedding IDs in order
                all_rows = conn.execute(
                    "SELECT id FROM embeddings WHERE embedding IS NOT NULL"
                ).fetchall()
                id_list = [r["id"] for r in all_rows]

                labels, distances = index.knn_query([query_vec], k=min(limit * 3, len(id_list)))
                results = []
                for idx, dist in zip(labels[0], distances[0]):
                    if idx < len(id_list):
                        emb_id = id_list[idx]
                        row = conn.execute(
                            "SELECT * FROM embeddings WHERE id=?", (emb_id,)
                        ).fetchone()
                        if row:
                            results.append({
                                "embedding_id": row["id"],
                                "record_type": row["record_type"],
                                "record_id": row["record_id"],
                                "text_content": row["text_content"],
                                "score": round(1.0 - float(dist), 4)
                            })
            except Exception as e:
                logger.warning("HNSW index search failed, falling back to brute force: %s", e)
                results = None  # Fall through to brute force

        # Brute force fallback
        if results is None:
            results = _brute_force_search(conn, query_vec, limit * 3, member_id)

        # Filter by member_id if using hnswlib (brute force already filters)
        if member_id and HAS_HNSWLIB and os.path.exists(VECTOR_INDEX_PATH):
            member_records = set()
            for rec_type, (table, _) in RECORD_TEXT_MAP.items():
                try:
                    mrows = conn.execute(
                        f"SELECT id FROM {table} WHERE member_id=? AND is_deleted=0", (member_id,)
                    ).fetchall()
                    for mr in mrows:
                        member_records.add((rec_type, mr["id"]))
                except Exception as e:
                    logger.warning("Failed to query member records for filtering: %s", e)
            results = [r for r in results if (r["record_type"], r["record_id"]) in member_records]

        results = results[:limit]
        results = _enrich_results(conn, results)

        output_json({
            "status": "ok",
            "query": query,
            "provider": provider.name,
            "model": provider.model_name,
            "count": len(results),
            "results": results
        })
    finally:
        conn.close()


def _keyword_fallback(query, member_id=None, limit=10):
    """Simple keyword search as fallback."""
    conn = get_connection()
    try:
        kw = f"%{query}%"
        results = []

        base = "member_id=? AND is_deleted=0" if member_id else "is_deleted=0"
        params_base = [member_id] if member_id else []

        search_map = {
            "visit": ("visits", ["chief_complaint", "diagnosis", "summary"]),
            "symptom": ("symptoms", ["symptom", "description"]),
            "medication": ("medications", ["name", "purpose"]),
            "lab_result": ("lab_results", ["test_name"]),
            "imaging": ("imaging_results", ["exam_name", "findings", "conclusion"]),
        }

        for rec_type, (table, fields) in search_map.items():
            like_clauses = " OR ".join(f"{f} LIKE ?" for f in fields)
            sql = f"SELECT * FROM {table} WHERE {base} AND ({like_clauses})"
            params = params_base + [kw] * len(fields)
            rows = conn.execute(sql, params).fetchall()
            for row in rows:
                row = dict(row)
                results.append({
                    "record_type": rec_type,
                    "record_id": row["id"],
                    "record": row,
                    "score": 1.0
                })

        return results[:limit]
    finally:
        conn.close()


def cmd_status(args):
    """Show index status."""
    ensure_db()
    provider = get_provider()
    conn = get_connection()
    try:
        total_embeddings = conn.execute("SELECT COUNT(*) as c FROM embeddings").fetchone()["c"]

        # Count total indexable records
        total_records = 0
        for rec_type, (table, _) in RECORD_TEXT_MAP.items():
            try:
                c = conn.execute(f"SELECT COUNT(*) as c FROM {table} WHERE is_deleted=0").fetchone()["c"]
                total_records += c
            except Exception:
                pass

        # Model info from existing embeddings
        model_row = conn.execute(
            "SELECT model_name, dimensions FROM embeddings LIMIT 1"
        ).fetchone()

        output_json({
            "status": "ok",
            "provider": provider.name,
            "provider_available": provider.available(),
            "model": provider.model_name,
            "indexed": total_embeddings,
            "total_records": total_records,
            "unindexed": max(0, total_records - total_embeddings),
            "hnswlib_available": HAS_HNSWLIB,
            "hnswlib_index_exists": os.path.exists(VECTOR_INDEX_PATH),
            "current_index_model": model_row["model_name"] if model_row else None,
            "current_index_dimensions": model_row["dimensions"] if model_row else None,
        })
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="MediWise 向量语义搜索")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="语义搜索")
    p.add_argument("--query", required=True, help="搜索内容")
    p.add_argument("--member-id", default=None, help="限定成员")
    p.add_argument("--limit", type=int, default=10, help="返回数量")

    p = sub.add_parser("index", help="增量索引")
    p.add_argument("--member-id", default=None, help="限定成员")

    p = sub.add_parser("reindex", help="全量重建索引")
    p.add_argument("--member-id", default=None, help="限定成员")

    sub.add_parser("status", help="索引状态")

    args = parser.parse_args()
    commands = {
        "search": cmd_search, "index": cmd_index,
        "reindex": cmd_reindex, "status": cmd_status,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
