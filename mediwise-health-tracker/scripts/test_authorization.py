"""Authorization regression tests for multi-tenant access control."""

from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
FIXTURE_DIR = SCRIPTS_DIR.parent / "test_data" / "generated_dataset"
HEALTH_MONITOR_SCRIPTS_DIR = SCRIPTS_DIR.parent.parent / "health-monitor" / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
if str(HEALTH_MONITOR_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(HEALTH_MONITOR_SCRIPTS_DIR))


class AuthorizationRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        shutil.copytree(FIXTURE_DIR, self.tmpdir.name, dirs_exist_ok=True)
        os.environ["MEDIWISE_DATA_DIR"] = self.tmpdir.name
        self.config = self._reload("config")
        self.health_db = self._reload("health_db")
        self.privacy = self._reload("privacy")
        self.query = self._reload("query")
        self.attachment = self._reload("attachment")
        self.reminder = self._reload("reminder")
        self.export_mod = self._reload("export")
        self.alert = self._reload("alert")

        conn = self.health_db.get_connection()
        try:
            reminder_row = conn.execute(
                "SELECT id, title FROM reminders WHERE member_id=? AND is_deleted=0 ORDER BY created_at LIMIT 1",
                ("mem_self_li_chen",)
            ).fetchone()
            attachment_row = conn.execute(
                "SELECT id FROM attachments WHERE member_id=? AND is_deleted=0 ORDER BY created_at LIMIT 1",
                ("mem_self_li_chen",)
            ).fetchone()
            alert_row = conn.execute(
                "SELECT id FROM monitor_alerts WHERE member_id=? AND is_resolved=0 ORDER BY created_at LIMIT 1",
                ("mem_self_li_chen",)
            ).fetchone()
            self.self_reminder_id = reminder_row["id"]
            self.baseline_reminder_title = reminder_row["title"]
            self.self_attachment_id = attachment_row["id"]
            self.self_alert_id = alert_row["id"]
        finally:
            conn.close()

    def tearDown(self):
        os.environ.pop("MEDIWISE_DATA_DIR", None)
        self.tmpdir.cleanup()

    def _reload(self, module_name: str):
        module = importlib.import_module(module_name)
        return importlib.reload(module)

    def _capture_json(self, func, *args, **kwargs):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            func(*args, **kwargs)
        output = buf.getvalue().strip()
        self.assertTrue(output, f"No JSON output from {func.__name__}")
        return json.loads(output)

    def test_query_summary_denies_cross_tenant_member(self):
        result = self._capture_json(
            self.query.summary,
            argparse.Namespace(member_id="mem_self_li_chen", owner_id="owner_demo_b"),
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("无权访问成员", result["message"])

    def test_attachment_get_denies_cross_tenant_access(self):
        result = self._capture_json(
            self.attachment.cmd_get,
            argparse.Namespace(id=self.self_attachment_id, base64=True, owner_id="owner_demo_b"),
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("无权访问附件", result["message"])

    def test_export_fhir_denies_cross_tenant_access(self):
        result = self.export_mod.export_fhir(
            "mem_self_li_chen", "full", owner_id="owner_demo_b"
        )
        self.assertEqual(result["error"], "无权访问成员: mem_self_li_chen")

    def test_reminder_update_denies_cross_tenant_write(self):
        reminder_id = self.self_reminder_id
        result = self.reminder.update_reminder(
            reminder_id,
            owner_id="owner_demo_b",
            title="PWNED by owner_b",
        )
        self.assertEqual(result["error"], f"无权访问提醒: {reminder_id}")

        conn = self.health_db.get_connection()
        try:
            row = conn.execute(
                "SELECT title FROM reminders WHERE id=?", (reminder_id,)
            ).fetchone()
            self.assertEqual(row["title"], self.baseline_reminder_title)
        finally:
            conn.close()

    def test_reminder_update_allows_owner(self):
        reminder_id = self.self_reminder_id
        result = self.reminder.update_reminder(
            reminder_id,
            owner_id="owner_demo_a",
            title="合法更新",
        )
        self.assertEqual(result["id"], reminder_id)
        self.assertIn("title", result["updated"])

        conn = self.health_db.get_connection()
        try:
            row = conn.execute(
                "SELECT title FROM reminders WHERE id=?", (reminder_id,)
            ).fetchone()
            self.assertEqual(row["title"], "合法更新")
        finally:
            conn.close()

    def test_statistics_scope_respects_owner(self):
        conn = self.health_db.get_connection()
        try:
            stats = self.privacy.aggregate_statistics(conn, owner_id="owner_demo_b")
        finally:
            conn.close()
        self.assertEqual(stats["member_count"], 1)
        self.assertEqual(stats["total_visits"], 1)

    def test_alert_list_denies_cross_tenant_member(self):
        result = self._capture_json(
            self.alert.cmd_list,
            argparse.Namespace(member_id="mem_self_li_chen", owner_id="owner_demo_b", level=None),
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("无权访问成员", result["message"])
        self.assertNotIn("alerts", result)

    def test_alert_history_denies_cross_tenant_member(self):
        result = self._capture_json(
            self.alert.cmd_history,
            argparse.Namespace(member_id="mem_self_li_chen", owner_id="owner_demo_b", limit="5"),
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("无权访问成员", result["message"])
        self.assertNotIn("alerts", result)

    def test_alert_resolve_denies_cross_tenant_member(self):
        result = self._capture_json(
            self.alert.cmd_resolve,
            argparse.Namespace(alert_id=self.self_alert_id, owner_id="owner_demo_b", note="denied"),
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("无权访问告警", result["message"])

        conn = self.health_db.get_connection()
        try:
            row = conn.execute(
                "SELECT is_resolved, status, resolved_by, resolution_note FROM monitor_alerts WHERE id=?",
                (self.self_alert_id,),
            ).fetchone()
            self.assertEqual(row["is_resolved"], 0)
            self.assertEqual(row["status"], "open")
            self.assertIsNone(row["resolved_by"])
            self.assertIsNone(row["resolution_note"])
        finally:
            conn.close()

    def test_alert_resolve_allows_owner(self):
        result = self._capture_json(
            self.alert.cmd_resolve,
            argparse.Namespace(alert_id=self.self_alert_id, owner_id="owner_demo_a", note="reviewed"),
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["alert_id"], self.self_alert_id)

        conn = self.health_db.get_connection()
        try:
            row = conn.execute(
                "SELECT is_resolved, status, resolved_by, resolution_note FROM monitor_alerts WHERE id=?",
                (self.self_alert_id,),
            ).fetchone()
            self.assertEqual(row["is_resolved"], 1)
            self.assertEqual(row["status"], "resolved")
            self.assertEqual(row["resolved_by"], "owner_demo_a")
            self.assertEqual(row["resolution_note"], "reviewed")
        finally:
            conn.close()

    def test_query_timeline_includes_lineage_metadata(self):
        result = self._capture_json(
            self.query.timeline,
            argparse.Namespace(member_id="mem_self_li_chen", owner_id="owner_demo_a"),
        )
        self.assertEqual(result["status"], "ok")
        visit_event = next(event for event in result["timeline"] if event.get("visit_id") == "visit_self_cardiology")
        self.assertIn("lineage", visit_event)
        self.assertTrue(visit_event["lineage"]["attachments"])
        self.assertIn("visit_self_cardiology", visit_event["lineage"]["source_records"])

    def test_export_fhir_success_writes_audit_event(self):
        result = self.export_mod.export_fhir(
            "mem_self_li_chen", "anonymized", owner_id="owner_demo_a"
        )
        self.assertEqual(result["resourceType"], "Bundle")

        conn = self.health_db.get_connection()
        try:
            row = conn.execute(
                "SELECT event_type, member_id, owner_id, payload FROM audit_events WHERE event_type=? ORDER BY created_at DESC LIMIT 1",
                ("export.fhir",),
            ).fetchone()
            self.assertEqual(row["member_id"], "mem_self_li_chen")
            self.assertEqual(row["owner_id"], "owner_demo_a")
            payload = json.loads(row["payload"])
            self.assertEqual(payload["privacy_level"], "anonymized")
            self.assertEqual(sorted(payload.keys()), ["privacy_level", "resource_count"])
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
