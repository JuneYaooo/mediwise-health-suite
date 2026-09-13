from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mediwise-health-tracker" / "scripts"))

import health_db


# The members table as it stood at schema v15, before standalone ages were added.
LEGACY_MEMBERS_SQL = """
CREATE TABLE members_legacy (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    relation TEXT NOT NULL,
    gender TEXT,
    birth_date TEXT,
    blood_type TEXT,
    allergies TEXT,
    medical_history TEXT,
    phone TEXT,
    emergency_contact TEXT,
    emergency_phone TEXT,
    owner_id TEXT,
    custom_metric_ranges TEXT,
    timezone TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0
);
"""


class SchemaMigrationTests(unittest.TestCase):
    """An existing database file must upgrade in place, keeping its records."""

    def setUp(self):
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.medical_db = Path(self._tempdir.name) / "medical.db"
        self.lifestyle_db = Path(self._tempdir.name) / "lifestyle.db"

        patcher = patch.dict(os.environ, {
            "MEDIWISE_MEDICAL_DB_PATH": str(self.medical_db),
            "MEDIWISE_LIFESTYLE_DB_PATH": str(self.lifestyle_db)})
        patcher.start()
        self.addCleanup(patcher.stop)

        health_db.init_db("medical")
        health_db.init_db("lifestyle")
        self._rewind_medical_db_to_v15()

    def _rewind_medical_db_to_v15(self):
        """Turn the current schema back into a v15 file, with one member on it.

        Dropping the two age columns is what makes this a genuine pre-migration
        database rather than a fresh one; every other table is left in place so
        the upgrade runs against a realistic file.
        """
        conn = sqlite3.connect(self.medical_db)
        try:
            conn.executescript(LEGACY_MEMBERS_SQL)
            conn.execute(
                """INSERT INTO members_legacy (id, name, relation, gender, birth_date, blood_type,
                   allergies, medical_history, phone, emergency_contact, emergency_phone, owner_id,
                   custom_metric_ranges, timezone, created_at, updated_at, is_deleted)
                   SELECT id, name, relation, gender, birth_date, blood_type, allergies,
                          medical_history, phone, emergency_contact, emergency_phone, owner_id,
                          custom_metric_ranges, timezone, created_at, updated_at, is_deleted
                   FROM members""")
            conn.execute("DROP TABLE members")
            conn.execute("ALTER TABLE members_legacy RENAME TO members")
            conn.execute(
                """INSERT INTO members (id, name, relation, gender, birth_date, medical_history,
                   allergies, created_at, updated_at)
                   VALUES ('m1', '张建国', '父亲', '男', NULL, '高血压病史约20年', '否认药物过敏史',
                           '2025-01-01T00:00:00', '2025-01-01T00:00:00')"""
            )
            conn.execute("UPDATE schema_version SET version=15")
            conn.commit()
        finally:
            conn.close()

    def _columns(self, table="members"):
        conn = sqlite3.connect(self.medical_db)
        try:
            return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
        finally:
            conn.close()

    def _version(self):
        conn = sqlite3.connect(self.medical_db)
        try:
            return conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()[0]
        finally:
            conn.close()

    def test_existing_records_gain_the_age_columns_without_being_rewritten(self):
        health_db.ensure_db()

        columns = self._columns()
        self.assertIn("age_years", columns)
        self.assertIn("age_recorded_at", columns)
        self.assertEqual(self._version(), health_db.SCHEMA_VERSION)

        conn = sqlite3.connect(self.medical_db)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM members WHERE id='m1'").fetchone()
        finally:
            conn.close()
        self.assertEqual(row["name"], "张建国")
        self.assertEqual(row["medical_history"], "高血压病史约20年")
        self.assertEqual(row["allergies"], "否认药物过敏史")
        self.assertIsNone(row["birth_date"])
        # Nothing is back-derived from an age, and no age was invented either.
        self.assertIsNone(row["age_years"])
        self.assertIsNone(row["age_recorded_at"])

    def test_the_upgrade_is_idempotent(self):
        health_db.ensure_db()
        health_db.ensure_db()

        self.assertEqual(self._columns().count("age_years"), 1)
        self.assertEqual(self._version(), health_db.SCHEMA_VERSION)

    def test_an_age_can_be_stored_on_an_upgraded_record(self):
        health_db.ensure_db()

        conn = sqlite3.connect(self.medical_db)
        try:
            conn.execute("UPDATE members SET age_years=89, age_recorded_at='2026-09-08' WHERE id='m1'")
            conn.commit()
            stored = conn.execute("SELECT age_years, age_recorded_at FROM members WHERE id='m1'").fetchone()
        finally:
            conn.close()
        self.assertEqual(stored, (89, "2026-09-08"))

    def test_a_fresh_database_lands_on_the_current_version(self):
        self.medical_db.unlink()
        self.lifestyle_db.unlink()

        health_db.ensure_db()

        self.assertEqual(self._version(), health_db.SCHEMA_VERSION)
        self.assertIn("age_recorded_at", self._columns())


if __name__ == "__main__":
    unittest.main()
