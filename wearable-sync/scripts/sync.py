"""Data sync CLI for wearable-sync.

Orchestrates data fetching from providers, normalization, deduplication,
and insertion into health_metrics.
"""

from __future__ import annotations

import sys
import os
import json
import argparse
import logging
import subprocess
from datetime import datetime

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from path_setup import setup_mediwise_path
setup_mediwise_path()
sys.path.insert(0, os.path.dirname(__file__))

logger = logging.getLogger(__name__)

import health_db
from normalize import normalize_metrics
from providers.gadgetbridge import GadgetbridgeProvider
from providers.huawei import HuaweiProvider
from providers.zepp import ZeppProvider
from providers.openwearables import OpenWearablesProvider
from providers.apple_health import AppleHealthProvider
from providers.garmin import GarminProvider

PROVIDERS = {
    "gadgetbridge": GadgetbridgeProvider,
    "huawei": HuaweiProvider,
    "zepp": ZeppProvider,
    "openwearables": OpenWearablesProvider,
    "apple_health": AppleHealthProvider,
    "garmin": GarminProvider,
}


def _get_provider(name):
    cls = PROVIDERS.get(name)
    if not cls:
        return None
    return cls()


def _load_device(conn, device_id):
    """Load a device record, return dict or None."""
    row = conn.execute(
        "SELECT * FROM wearable_devices WHERE id=? AND is_deleted=0 AND is_active=1",
        (device_id,)
    ).fetchone()
    return dict(row) if row else None


def _check_duplicate(conn, member_id, metric_type, measured_at, source):
    """Check if a metric with the same key already exists."""
    row = conn.execute(
        """SELECT 1 FROM health_metrics
           WHERE member_id=? AND metric_type=? AND measured_at=? AND source=? AND is_deleted=0
           LIMIT 1""",
        (member_id, metric_type, measured_at, source)
    ).fetchone()
    return row is not None


def sync_device(device_id, owner_id=None):
    """Sync a single device. Returns sync result dict.

    If owner_id is provided, the device's owning member is verified against it
    before any sync work begins.
    """
    health_db.ensure_db()
    conn = health_db.get_lifestyle_connection()

    try:
        device = _load_device(conn, device_id)
        if not device:
            return {"status": "error", "message": f"未找到活跃设备: {device_id}"}
    finally:
        conn.close()

    # Verify that the caller has access to the member this device belongs to
    if owner_id is not None:
        med_conn = health_db.get_medical_connection()
        try:
            if not health_db.verify_member_ownership(med_conn, device["member_id"], owner_id):
                return {"status": "error", "message": f"无权访问设备: {device_id}"}
        finally:
            med_conn.close()

    provider_name = device["provider"]
    provider = _get_provider(provider_name)
    if not provider:
        return {"status": "error", "message": f"未知 Provider: {provider_name}"}

    try:
        config = json.loads(device.get("config") or "{}")
    except (json.JSONDecodeError, TypeError):
        config = {}

    # Authenticate
    config_before = json.dumps(config, ensure_ascii=False, sort_keys=True)
    try:
        if not provider.authenticate(config):
            return {"status": "error", "message": "设备认证失败，请检查配置"}
    except NotImplementedError as e:
        return {"status": "error", "message": str(e)}
    except RuntimeError as e:
        return {"status": "error", "message": str(e)}

    # If authenticate() scrubbed sensitive fields (e.g. Garmin password after
    # tokenstore login), persist the cleaned config back to the database now.
    config_after = json.dumps(config, ensure_ascii=False, sort_keys=True)
    if config_after != config_before:
        with health_db.transaction(domain="lifestyle") as conn:
            conn.execute(
                "UPDATE wearable_devices SET config=?, updated_at=? WHERE id=?",
                (json.dumps(config, ensure_ascii=False), health_db.now_iso(), device_id),
            )
            conn.commit()
        logger.info("Garmin: sensitive fields removed from stored config for device %s", device_id)

    # Create sync log entry
    sync_id = health_db.generate_id()
    sync_start = health_db.now_iso()

    with health_db.transaction(domain="lifestyle") as conn:
        conn.execute(
            """INSERT INTO wearable_sync_log (id, device_id, sync_start, status, created_at)
               VALUES (?, ?, ?, 'running', ?)""",
            (sync_id, device_id, sync_start, sync_start)
        )
        conn.commit()

    # Fetch raw metrics
    start_time = device.get("last_sync_at")
    try:
        raw_metrics = provider.fetch_metrics(device_id, start_time=start_time)
    except Exception as e:
        _update_sync_log(sync_id, "failed", 0, 0, str(e))
        return {"status": "error", "message": f"数据获取失败: {e}"}

    if not raw_metrics:
        _update_sync_log(sync_id, "success", 0, 0, None)
        return {"status": "ok", "message": "无新数据", "synced": 0, "skipped": 0}

    # Normalize
    normalized = normalize_metrics(raw_metrics, provider_name)

    # Insert with deduplication
    member_id = device["member_id"]
    synced = 0
    skipped = 0

    with health_db.transaction(domain="medical") as conn:
        for metric in normalized:
            if _check_duplicate(conn, member_id, metric["metric_type"],
                                metric["measured_at"], metric["source"]):
                skipped += 1
                continue
            metric_id = health_db.generate_id()
            conn.execute(
                """INSERT INTO health_metrics
                   (id, member_id, metric_type, value, measured_at, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (metric_id, member_id, metric["metric_type"],
                 metric["value"], metric["measured_at"], metric["source"],
                 health_db.now_iso())
            )
            synced += 1
        conn.commit()

    # Update device last_sync_at in lifestyle domain (separate transaction)
    with health_db.transaction(domain="lifestyle") as conn:
        conn.execute(
            "UPDATE wearable_devices SET last_sync_at=?, updated_at=? WHERE id=?",
            (health_db.now_iso(), health_db.now_iso(), device_id)
        )
        conn.commit()

    # Update sync log
    status = "success" if synced > 0 else ("partial" if skipped > 0 else "success")
    _update_sync_log(sync_id, status, synced, skipped, None)

    # Auto-check after sync if configured
    _auto_check_after_sync(member_id)

    return {
        "status": "ok",
        "message": f"同步完成: {synced} 条新数据，{skipped} 条跳过（重复）",
        "synced": synced,
        "skipped": skipped,
        "device_id": device_id,
        "sync_id": sync_id,
    }


def _update_sync_log(sync_id, status, synced, skipped, error_msg):
    """Update sync log entry with final status."""
    with health_db.transaction(domain="lifestyle") as conn:
        conn.execute(
            """UPDATE wearable_sync_log
               SET sync_end=?, status=?, metrics_synced=?, metrics_skipped=?, error_message=?
               WHERE id=?""",
            (health_db.now_iso(), status, synced, skipped, error_msg, sync_id)
        )
        conn.commit()


def _auto_check_after_sync(member_id):
    """Call health-monitor check.py after sync if configured."""
    try:
        # Load config to check auto_check setting
        from config import load_config
        cfg = load_config()
        if not cfg.get("wearable", {}).get("auto_check_after_sync", True):
            return

        monitor_check = os.path.join(
            os.path.dirname(__file__), "..", "..", "health-monitor", "scripts", "check.py"
        )
        if os.path.isfile(monitor_check):
            subprocess.run(
                [sys.executable, monitor_check, "run", "--member-id", member_id, "--window", "1h"],
                timeout=30, capture_output=True
            )
    except Exception as e:
        logger.warning("Auto-check after sync failed: %s", e)


def cmd_run(args):
    """Run sync for a device or all devices of a member."""
    health_db.ensure_db()
    owner_id = getattr(args, "owner_id", None)

    if args.device_id:
        result = sync_device(args.device_id, owner_id=owner_id)
        health_db.output_json(result)
        return

    if args.member_id:
        # Verify the caller has access to this member before listing their devices
        if owner_id is not None:
            med_conn = health_db.get_medical_connection()
            try:
                if not health_db.verify_member_ownership(med_conn, args.member_id, owner_id):
                    health_db.output_json({"status": "error", "message": f"无权访问成员: {args.member_id}"})
                    return
            finally:
                med_conn.close()

        conn = health_db.get_lifestyle_connection()
        try:
            rows = conn.execute(
                "SELECT id FROM wearable_devices WHERE member_id=? AND is_active=1 AND is_deleted=0",
                (args.member_id,)
            ).fetchall()
        finally:
            conn.close()

        if not rows:
            health_db.output_json({"status": "ok", "message": "该成员没有活跃设备"})
            return

        results = []
        for row in rows:
            results.append(sync_device(row["id"], owner_id=owner_id))
        total_synced = sum(r.get("synced", 0) for r in results)
        total_skipped = sum(r.get("skipped", 0) for r in results)
        health_db.output_json({
            "status": "ok",
            "message": f"同步 {len(rows)} 个设备完成: {total_synced} 条新数据，{total_skipped} 条跳过",
            "devices": results,
        })
        return

    health_db.output_json({"status": "error", "message": "请指定 --device-id 或 --member-id"})


def cmd_run_all(args):
    """Run sync for all active devices."""
    health_db.ensure_db()
    conn = health_db.get_lifestyle_connection()
    try:
        rows = conn.execute(
            "SELECT id, member_id, provider, device_name FROM wearable_devices WHERE is_active=1 AND is_deleted=0"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        health_db.output_json({"status": "ok", "message": "没有活跃设备"})
        return

    results = []
    for row in rows:
        results.append(sync_device(row["id"]))

    total_synced = sum(r.get("synced", 0) for r in results)
    total_skipped = sum(r.get("skipped", 0) for r in results)
    health_db.output_json({
        "status": "ok",
        "message": f"同步 {len(rows)} 个设备完成: {total_synced} 条新数据，{total_skipped} 条跳过",
        "device_count": len(rows),
        "total_synced": total_synced,
        "total_skipped": total_skipped,
        "devices": results,
    })


def cmd_status(args):
    """Show sync status for a device."""
    health_db.ensure_db()
    conn = health_db.get_lifestyle_connection()
    try:
        device = conn.execute(
            "SELECT * FROM wearable_devices WHERE id=? AND is_deleted=0",
            (args.device_id,)
        ).fetchone()
        if not device:
            health_db.output_json({"status": "error", "message": f"未找到设备: {args.device_id}"})
            return

        last_sync = conn.execute(
            """SELECT * FROM wearable_sync_log WHERE device_id=?
               ORDER BY created_at DESC LIMIT 1""",
            (args.device_id,)
        ).fetchone()

        health_db.output_json({
            "status": "ok",
            "device": health_db.row_to_dict(device),
            "last_sync": health_db.row_to_dict(last_sync),
        })
    finally:
        conn.close()


def cmd_history(args):
    """Show sync history for a device."""
    health_db.ensure_db()
    conn = health_db.get_lifestyle_connection()
    try:
        limit = int(args.limit) if args.limit else 10
        rows = conn.execute(
            """SELECT * FROM wearable_sync_log WHERE device_id=?
               ORDER BY created_at DESC LIMIT ?""",
            (args.device_id, limit)
        ).fetchall()
        health_db.output_json({
            "status": "ok",
            "count": len(rows),
            "history": health_db.rows_to_list(rows),
        })
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="可穿戴设备数据同步")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="同步设备数据")
    p_run.add_argument("--device-id", default=None)
    p_run.add_argument("--member-id", default=None)
    p_run.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"), help="调用方的 owner_id，用于归属校验")

    sub.add_parser("run-all", help="同步所有活跃设备")

    p_status = sub.add_parser("status", help="查看同步状态")
    p_status.add_argument("--device-id", required=True)

    p_history = sub.add_parser("history", help="同步历史")
    p_history.add_argument("--device-id", required=True)
    p_history.add_argument("--limit", default="10")

    args = parser.parse_args()
    commands = {
        "run": cmd_run,
        "run-all": cmd_run_all,
        "status": cmd_status,
        "history": cmd_history,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
