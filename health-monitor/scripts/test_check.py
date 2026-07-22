"""Regression tests for health-monitor anomaly checks."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
ROOT_DIR = TEST_DIR.parent.parent
MEDIWISE_SCRIPTS_DIR = ROOT_DIR / "mediwise-health-tracker" / "scripts"

for path in (TEST_DIR, MEDIWISE_SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


class CheckRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["MEDIWISE_DATA_DIR"] = self.tmpdir.name
        self.config = self._reload("config")
        self.health_db = self._reload("health_db")
        self.check = self._reload("check")
        self.alert = self._reload("alert")
        self._create_minimal_fixture()

    def tearDown(self):
        os.environ.pop("MEDIWISE_DATA_DIR", None)
        self.tmpdir.cleanup()

    def _reload(self, module_name: str):
        module = importlib.import_module(module_name)
        return importlib.reload(module)

    def _create_minimal_fixture(self):
        """Create deterministic synthetic metrics without repository test data."""
        self.health_db.ensure_db()
        now = self.health_db.now_iso()
        with self.health_db.transaction() as conn:
            conn.execute(
                """INSERT INTO members
                   (id, name, relation, birth_date, owner_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ("mem_edge_guo_tao", "测试成员", "本人", "1980-01-01", "owner_demo_a", now, now),
            )
            conn.executemany(
                """INSERT INTO health_metrics
                   (id, member_id, metric_type, value, measured_at, source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [
                    ("metric_hr", "mem_edge_guo_tao", "heart_rate", "154", now, "test", now),
                    ("metric_spo2", "mem_edge_guo_tao", "blood_oxygen", "83", now, "test", now),
                    ("metric_bp", "mem_edge_guo_tao", "blood_pressure", json.dumps({"systolic": 186, "diastolic": 118}), now, "test", now),
                    ("metric_temp", "mem_edge_guo_tao", "temperature", "39.8", now, "test", now),
                    ("metric_glucose", "mem_edge_guo_tao", "blood_sugar", json.dumps({"fasting": 12.6}), now, "test", now),
                ],
            )
            conn.commit()

    def test_check_member_recognizes_blood_sugar_json_values(self):
        result = self.check.check_member("mem_edge_guo_tao", "24h")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["alerts_generated"], 6)
        self.assertTrue(
            any(alert["metric_type"] == "blood_sugar" for alert in result["alerts"]),
            "Expected a blood_sugar alert from fasting JSON metric values",
        )

    def test_check_member_links_reminders_and_writes_audit_trail(self):
        result = self.check.check_member("mem_edge_guo_tao", "24h")
        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["alerts_generated"], 0)

        alert_id = result["alerts"][0]["alert_id"]

        conn = self.health_db.get_connection()
        try:
            row = conn.execute(
                "SELECT status, updated_at, last_reminder_id, created_at FROM monitor_alerts WHERE id=?",
                (alert_id,),
            ).fetchone()
            self.assertEqual(row["status"], "open")
            self.assertEqual(row["updated_at"], row["created_at"])
            self.assertTrue(row["last_reminder_id"])

            reminder_row = conn.execute(
                "SELECT related_record_type, related_record_id, is_active FROM reminders WHERE id=?",
                (row["last_reminder_id"],),
            ).fetchone()
            self.assertEqual(reminder_row["related_record_type"], "monitor_alert")
            self.assertEqual(reminder_row["related_record_id"], alert_id)
            self.assertEqual(reminder_row["is_active"], 1)

            create_events = conn.execute(
                "SELECT event_type, record_id, payload FROM audit_events WHERE event_type=? ORDER BY created_at",
                ("alert.created",),
            ).fetchall()
            self.assertEqual(len(create_events), result["alerts_generated"])
            payload = json.loads(create_events[0]["payload"])
            self.assertIn("metric_type", payload)
            self.assertNotIn("detail", payload)
        finally:
            conn.close()

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.alert.cmd_resolve(
                argparse.Namespace(alert_id=alert_id, owner_id="owner_demo_a", note="reviewed")
            )
        resolve_output = json.loads(buf.getvalue().strip())
        self.assertEqual(resolve_output["status"], "ok")

        conn = self.health_db.get_connection()
        try:
            resolved = conn.execute(
                "SELECT is_resolved, status, resolved_by, resolution_note, last_reminder_id FROM monitor_alerts WHERE id=?",
                (alert_id,),
            ).fetchone()
            self.assertEqual(resolved["is_resolved"], 1)
            self.assertEqual(resolved["status"], "resolved")
            self.assertEqual(resolved["resolved_by"], "owner_demo_a")
            self.assertEqual(resolved["resolution_note"], "reviewed")

            reminder_row = conn.execute(
                "SELECT is_active FROM reminders WHERE id=?",
                (resolved["last_reminder_id"],),
            ).fetchone()
            self.assertEqual(reminder_row["is_active"], 0)

            resolve_event = conn.execute(
                "SELECT event_type, record_id, owner_id, payload FROM audit_events WHERE event_type=? AND record_id=? ORDER BY created_at DESC LIMIT 1",
                ("alert.resolved", alert_id),
            ).fetchone()
            self.assertEqual(resolve_event["owner_id"], "owner_demo_a")
            payload = json.loads(resolve_event["payload"])
            self.assertEqual(payload["status"], "resolved")
            self.assertEqual(payload["note_present"], True)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
