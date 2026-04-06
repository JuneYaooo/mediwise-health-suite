"""健康做梦机制 — 素材聚合与锁管理。

dream.py 负责收集当天的健康原始素材，供 agent 在"做梦"时消化整合。
它本身不生成洞察，只负责把数据结构化地取出来，以及管理做梦状态。

做梦的实际反思和写入工作由 DREAM.md skill 驱动的 agent 完成。

Commands:
  gather  --owner-id               采集今日素材，输出 JSON 供 agent 消化
  status  --owner-id               查看上次做梦状态和下次触发时机
  lock    --owner-id               尝试获取做梦锁（防止并发）
  unlock  --owner-id [--rollback]  释放/回滚锁

Importable API:
  gather_dream_material(owner_id, date_str=None) -> dict
  get_dream_status(owner_id) -> dict
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import health_db
from health_db import (
    ensure_db, get_medical_connection, get_lifestyle_connection,
    rows_to_list, row_to_dict, output_json,
    verify_member_ownership,
)

# 两次做梦之间最少间隔（小时）
MIN_HOURS_BETWEEN_DREAMS = 20

# 做梦锁文件，存在 DATA_DIR 下
def _lock_path() -> str:
    from config import DATA_DIR
    return os.path.join(DATA_DIR, ".dream-lock")


# ------------------------------------------------------------------ lock

def try_acquire_lock(owner_id: str) -> bool:
    """尝试获取做梦锁。返回 True 表示成功获取。"""
    lock_file = _lock_path()
    now_ts = time.time()

    # 检查现有锁
    if os.path.exists(lock_file):
        try:
            with open(lock_file) as f:
                data = json.load(f)
            locked_at = data.get("locked_at", 0)
            last_dream_at = data.get("last_dream_at", 0)

            # 锁超过1小时视为僵尸锁，强制释放
            if now_ts - locked_at < 3600 and data.get("status") == "running":
                return False  # 另一进程正在做梦

            # 距上次做梦不足 MIN_HOURS
            hours_since = (now_ts - last_dream_at) / 3600
            if last_dream_at > 0 and hours_since < MIN_HOURS_BETWEEN_DREAMS:
                return False
        except (json.JSONDecodeError, KeyError, OSError):
            pass  # 损坏的锁文件，覆盖它

    # 写入锁
    try:
        lock_data = {
            "owner_id": owner_id,
            "locked_at": now_ts,
            "status": "running",
            "last_dream_at": _read_last_dream_at(),
        }
        os.makedirs(os.path.dirname(lock_file), exist_ok=True)
        with open(lock_file, "w") as f:
            json.dump(lock_data, f)
        return True
    except OSError:
        return False


def release_lock(rollback: bool = False) -> None:
    """释放锁。rollback=True 时恢复 last_dream_at（失败时用）。"""
    lock_file = _lock_path()
    if not os.path.exists(lock_file):
        return
    try:
        with open(lock_file) as f:
            data = json.load(f)
        if rollback:
            # 保留 last_dream_at，只清除 running 状态
            data["status"] = "failed"
            data["locked_at"] = 0
        else:
            data["status"] = "completed"
            data["last_dream_at"] = time.time()
            data["locked_at"] = 0
        with open(lock_file, "w") as f:
            json.dump(data, f)
    except (OSError, json.JSONDecodeError):
        pass


def _read_last_dream_at() -> float:
    lock_file = _lock_path()
    try:
        with open(lock_file) as f:
            return json.load(f).get("last_dream_at", 0)
    except (OSError, json.JSONDecodeError):
        return 0


def get_dream_status(owner_id: str) -> dict:
    """返回做梦状态和下次触发时机。"""
    lock_file = _lock_path()
    last_dream_at = _read_last_dream_at()
    now_ts = time.time()
    hours_since = (now_ts - last_dream_at) / 3600 if last_dream_at else None
    next_dream_in = max(0, MIN_HOURS_BETWEEN_DREAMS - (hours_since or 999))

    status = "idle"
    if os.path.exists(lock_file):
        try:
            with open(lock_file) as f:
                data = json.load(f)
            status = data.get("status", "idle")
        except (OSError, json.JSONDecodeError):
            pass

    last_iso = datetime.fromtimestamp(last_dream_at).strftime("%Y-%m-%d %H:%M") if last_dream_at else None
    return {
        "status": status,
        "last_dream_at": last_iso,
        "hours_since_last_dream": round(hours_since, 1) if hours_since else None,
        "next_dream_in_hours": round(next_dream_in, 1),
        "ready": hours_since is None or hours_since >= MIN_HOURS_BETWEEN_DREAMS,
    }


# ------------------------------------------------------------------ gather

def gather_dream_material(owner_id: str, date_str: str = None) -> dict:
    """收集指定日期的健康素材，供 agent 做梦时消化。

    返回结构：
    {
      "date": "YYYY-MM-DD",
      "members": [
        {
          "member_id": ..., "name": ..., "relation": ...,
          "snapshot": { risk_level, summary_text, alerts_count, ... },
          "metrics": [ { metric_type, value, measured_at } ... ],  # 当日原始指标
          "alerts": [ { metric_type, severity, message, ... } ],
          "today_mentions": [ { content, category, mentioned_at } ],  # 今日对话中记录的健康提及
          "health_notes": [ { content, category, days_since_mentioned } ],  # 历史未解决备注
          "new_since_last_dream": {
            "metrics_count": N,    # 自上次做梦新增的指标条数
            "notes_count": N,
          }
        }
      ],
      "last_dream_at": "...",
      "days_of_snapshots": N,      # 已有多少天的快照记录
    }
    """
    ensure_db()
    today = date_str or datetime.now().strftime("%Y-%m-%d")
    last_dream_at = _read_last_dream_at()
    last_dream_date = (
        datetime.fromtimestamp(last_dream_at).strftime("%Y-%m-%d")
        if last_dream_at else None
    )

    med_conn = get_medical_connection()
    try:
        members = rows_to_list(med_conn.execute(
            "SELECT id, name, relation FROM members WHERE is_deleted=0 AND owner_id=? ORDER BY created_at",
            (owner_id,),
        ).fetchall())
    finally:
        med_conn.close()

    member_data = []
    for m in members:
        mid = m["id"]
        member_data.append({
            "member_id": mid,
            "name": m["name"],
            "relation": m["relation"],
            "snapshot": _get_today_snapshot(mid, today),
            "metrics": _get_today_metrics(mid, today),
            "alerts": _get_recent_alerts(mid, last_dream_date or today),
            "health_notes": _get_pending_notes(mid),
            "today_mentions": _get_today_mentions(mid, today),  # 今日对话中记录的健康提及
            "new_since_last_dream": _count_new_since(mid, last_dream_date),
        })

    # 已有快照的天数
    snap_days = _count_snapshot_days(owner_id)

    return {
        "date": today,
        "owner_id": owner_id,
        "last_dream_at": (
            datetime.fromtimestamp(last_dream_at).strftime("%Y-%m-%d %H:%M")
            if last_dream_at else None
        ),
        "members": member_data,
        "days_of_snapshots": snap_days,
    }


def _get_today_snapshot(member_id: str, date_str: str) -> dict | None:
    conn = get_medical_connection()
    try:
        if not _table_exists(conn, "daily_health_snapshots"):
            return None
        row = conn.execute(
            "SELECT * FROM daily_health_snapshots WHERE member_id=? AND snapshot_date=? AND is_deleted=0",
            (member_id, date_str),
        ).fetchone()
        if not row:
            return None
        d = row_to_dict(row)
        d.pop("briefing_json", None)  # 太大，不放进素材
        return d
    finally:
        conn.close()


def _get_today_metrics(member_id: str, date_str: str) -> list[dict]:
    """返回当日的健康指标原始值（血压、心率、睡眠、步数等）。"""
    conn = get_medical_connection()
    try:
        rows = conn.execute(
            """SELECT metric_type, value, measured_at, source
               FROM health_metrics
               WHERE member_id=? AND date(measured_at)=? AND is_deleted=0
               ORDER BY measured_at""",
            (member_id, date_str),
        ).fetchall()
        result = []
        for row in rows:
            d = row_to_dict(row)
            # 尝试解析 JSON value
            try:
                d["value_parsed"] = json.loads(d["value"])
            except (json.JSONDecodeError, TypeError):
                d["value_parsed"] = d["value"]
            result.append(d)
        return result
    finally:
        conn.close()


def _get_recent_alerts(member_id: str, since_date: str) -> list[dict]:
    """返回自上次做梦以来的监测告警。"""
    conn = get_medical_connection()
    try:
        if not _table_exists(conn, "monitor_alerts"):
            return []
        rows = conn.execute(
            """SELECT metric_type, severity, message, triggered_at, is_resolved
               FROM monitor_alerts
               WHERE member_id=? AND date(triggered_at)>=? AND is_deleted=0
               ORDER BY triggered_at DESC LIMIT 20""",
            (member_id, since_date),
        ).fetchall()
        return rows_to_list(rows)
    finally:
        conn.close()


def _get_pending_notes(member_id: str) -> list[dict]:
    """返回未解决的健康备注（历史积压，不含今日新增）。"""
    conn = get_medical_connection()
    try:
        if not _table_exists(conn, "health_notes"):
            return []
        today = datetime.now().strftime("%Y-%m-%d")
        rows = conn.execute(
            """SELECT content, category, mentioned_at, follow_up_date
               FROM health_notes
               WHERE member_id=? AND is_resolved=0 AND is_deleted=0
                 AND mentioned_at < ?
               ORDER BY mentioned_at DESC LIMIT 10""",
            (member_id, today),
        ).fetchall()
        result = rows_to_list(rows)
        today_dt = datetime.now().date()
        for note in result:
            try:
                d = datetime.strptime(note["mentioned_at"], "%Y-%m-%d").date()
                note["days_since_mentioned"] = (today_dt - d).days
            except Exception:
                note["days_since_mentioned"] = 0
        return result
    finally:
        conn.close()


def _get_today_mentions(member_id: str, today: str) -> list[dict]:
    """返回今日对话中新记录的健康提及（当天 mentioned_at 的健康备注）。

    这些是用户在当天聊天中随口提到、由 agent 实时记录的健康信息，
    做梦时需要单独列出，作为"今日对话素材"纳入回顾。
    """
    conn = get_medical_connection()
    try:
        if not _table_exists(conn, "health_notes"):
            return []
        rows = conn.execute(
            """SELECT content, category, mentioned_at, follow_up_date, is_resolved
               FROM health_notes
               WHERE member_id=? AND mentioned_at=? AND is_deleted=0
               ORDER BY rowid ASC""",
            (member_id, today),
        ).fetchall()
        return rows_to_list(rows)
    finally:
        conn.close()


def _count_new_since(member_id: str, since_date: str | None) -> dict:
    if not since_date:
        return {"metrics_count": 0, "notes_count": 0}
    conn = get_medical_connection()
    try:
        m = conn.execute(
            "SELECT COUNT(*) as n FROM health_metrics WHERE member_id=? AND date(measured_at)>=? AND is_deleted=0",
            (member_id, since_date),
        ).fetchone()
        metrics_count = m["n"] if m else 0

        notes_count = 0
        if _table_exists(conn, "health_notes"):
            n = conn.execute(
                "SELECT COUNT(*) as n FROM health_notes WHERE member_id=? AND mentioned_at>=? AND is_deleted=0",
                (member_id, since_date),
            ).fetchone()
            notes_count = n["n"] if n else 0

        return {"metrics_count": metrics_count, "notes_count": notes_count}
    finally:
        conn.close()


def _count_snapshot_days(owner_id: str) -> int:
    conn = get_medical_connection()
    try:
        if not _table_exists(conn, "daily_health_snapshots"):
            return 0
        row = conn.execute(
            """SELECT COUNT(DISTINCT snapshot_date) as n
               FROM daily_health_snapshots ds
               JOIN members m ON ds.member_id = m.id
               WHERE m.owner_id=? AND ds.is_deleted=0""",
            (owner_id,),
        ).fetchone()
        return row["n"] if row else 0
    finally:
        conn.close()


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return bool(row)


# ------------------------------------------------------------------ CLI

def cmd_gather(args):
    owner_id = args.owner_id or os.environ.get("MEDIWISE_OWNER_ID", "")
    if not owner_id:
        output_json({"status": "error", "message": "需要 --owner-id"})
        return
    material = gather_dream_material(owner_id, getattr(args, "date", None))
    output_json({"status": "ok", "material": material})


def cmd_status(args):
    owner_id = args.owner_id or os.environ.get("MEDIWISE_OWNER_ID", "")
    output_json(get_dream_status(owner_id))


def cmd_lock(args):
    owner_id = args.owner_id or os.environ.get("MEDIWISE_OWNER_ID", "")
    ok = try_acquire_lock(owner_id)
    output_json({"status": "ok" if ok else "locked", "acquired": ok})


def cmd_unlock(args):
    rollback = getattr(args, "rollback", False)
    release_lock(rollback=rollback)
    output_json({"status": "ok", "rollback": rollback})


def main():
    parser = argparse.ArgumentParser(description="健康做梦素材聚合")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("gather", help="收集今日做梦素材")
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
    p.add_argument("--date", default=None, help="YYYY-MM-DD，默认今天")

    p = sub.add_parser("status", help="查看做梦状态")
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    p = sub.add_parser("lock", help="获取做梦锁")
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    p = sub.add_parser("unlock", help="释放做梦锁")
    p.add_argument("--rollback", action="store_true", help="失败时回滚（不更新 last_dream_at）")

    args = parser.parse_args()
    {"gather": cmd_gather, "status": cmd_status,
     "lock": cmd_lock, "unlock": cmd_unlock}[args.command](args)


if __name__ == "__main__":
    main()
