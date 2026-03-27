"""SQLite database initialization and management for MediWise Health Tracker."""

from __future__ import annotations

import os
import sys
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from config import (
    get_db_path as _cfg_get_db_path,
    get_medical_db_path as _cfg_get_medical_db_path,
    get_lifestyle_db_path as _cfg_get_lifestyle_db_path,
    config_exists,
    check_config_status,
    save_config,
    DEFAULT_CONFIG,
    ensure_data_dir,
    is_backend_mode,
)


def is_api_mode():
    """Check if backend API mode is enabled."""
    return is_backend_mode()

SCHEMA_VERSION = 15

MEDICAL_TABLES = {
    "schema_version",
    "members",
    "visits",
    "symptoms",
    "medications",
    "lab_results",
    "imaging_results",
    "health_metrics",
    "member_summaries",
    "observations",
    "compression_log",
    "reminders",
    "reminder_logs",
    "embeddings",
    "cycle_records",
    "cycle_predictions",
    "monitor_thresholds",
    "monitor_alerts",
    "audit_events",
    "attachments",
    "attachment_links",
    "health_notes",
    "medication_logs",
    "chronic_disease_profiles",
}

LIFESTYLE_TABLES = {
    "diet_records",
    "diet_items",
    "weight_goals",
    "exercise_records",
    "wearable_devices",
    "wearable_sync_log",
    "nutrition_goals",
}

TABLE_DOMAIN = {
    **{table: "medical" for table in MEDICAL_TABLES},
    **{table: "lifestyle" for table in LIFESTYLE_TABLES},
}


def get_table_domain(table_name: str | None) -> str:
    """Return table domain. Unknown tables default to medical."""
    if not table_name:
        return "medical"
    return TABLE_DOMAIN.get(table_name, "medical")


def get_db_path():
    """Legacy accessor kept for backward compatibility (medical DB)."""
    return _cfg_get_db_path()


def get_medical_db_path():
    return _cfg_get_medical_db_path()


def get_lifestyle_db_path():
    return _cfg_get_lifestyle_db_path()


def _open_connection(db_path):
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _auto_init_config():
    """Auto-initialize config if it doesn't exist. Returns config status."""
    if not config_exists():
        ensure_data_dir()
        save_config(DEFAULT_CONFIG)
    return check_config_status()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS members (
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

CREATE TABLE IF NOT EXISTS visits (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    visit_type TEXT NOT NULL,
    visit_date TEXT NOT NULL,
    end_date TEXT,
    hospital TEXT,
    department TEXT,
    chief_complaint TEXT,
    diagnosis TEXT,
    summary TEXT,
    visit_status TEXT DEFAULT 'completed',
    follow_up_date TEXT,
    follow_up_notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE TABLE IF NOT EXISTS symptoms (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    visit_id TEXT,
    symptom TEXT NOT NULL,
    severity TEXT,
    onset_date TEXT,
    end_date TEXT,
    description TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (visit_id) REFERENCES visits(id)
);

CREATE TABLE IF NOT EXISTS medications (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    visit_id TEXT,
    name TEXT NOT NULL,
    dosage TEXT,
    frequency TEXT,
    start_date TEXT,
    end_date TEXT,
    purpose TEXT,
    stop_reason TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (visit_id) REFERENCES visits(id)
);

CREATE TABLE IF NOT EXISTS lab_results (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    visit_id TEXT,
    test_name TEXT NOT NULL,
    test_date TEXT NOT NULL,
    items TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (visit_id) REFERENCES visits(id)
);

CREATE TABLE IF NOT EXISTS imaging_results (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    visit_id TEXT,
    exam_name TEXT NOT NULL,
    exam_date TEXT NOT NULL,
    findings TEXT,
    conclusion TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (visit_id) REFERENCES visits(id)
);

CREATE TABLE IF NOT EXISTS health_metrics (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    value TEXT NOT NULL,
    measured_at TEXT NOT NULL,
    note TEXT,
    source TEXT DEFAULT 'manual',
    context TEXT DEFAULT 'routine',
    related_visit_id TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE INDEX IF NOT EXISTS idx_visits_member ON visits(member_id, visit_date);
CREATE INDEX IF NOT EXISTS idx_members_owner ON members(owner_id);
CREATE INDEX IF NOT EXISTS idx_symptoms_member ON symptoms(member_id);
CREATE INDEX IF NOT EXISTS idx_medications_member ON medications(member_id, is_active);
CREATE INDEX IF NOT EXISTS idx_lab_results_member ON lab_results(member_id, test_date);
CREATE INDEX IF NOT EXISTS idx_imaging_member ON imaging_results(member_id, exam_date);
CREATE INDEX IF NOT EXISTS idx_metrics_member ON health_metrics(member_id, metric_type, measured_at);

-- Memory & Compression tables

CREATE TABLE IF NOT EXISTS member_summaries (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    summary_type TEXT NOT NULL,
    content TEXT NOT NULL,
    facts TEXT,
    source_count INTEGER DEFAULT 0,
    token_count INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    member_id TEXT,
    obs_type TEXT NOT NULL,
    title TEXT NOT NULL,
    facts TEXT NOT NULL,
    narrative TEXT,
    source_records TEXT,
    discovery_tokens INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE TABLE IF NOT EXISTS compression_log (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    action TEXT NOT NULL,
    original_tokens INTEGER,
    compressed_tokens INTEGER,
    compression_ratio REAL,
    details TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE INDEX IF NOT EXISTS idx_member_summaries ON member_summaries(member_id, summary_type);
CREATE INDEX IF NOT EXISTS idx_observations_member ON observations(member_id, obs_type);
CREATE INDEX IF NOT EXISTS idx_compression_log ON compression_log(member_id, created_at);

-- Reminders & reminder logs

CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    schedule_type TEXT NOT NULL,
    schedule_value TEXT,
    next_trigger_at TEXT,
    last_triggered_at TEXT,
    related_record_id TEXT,
    related_record_type TEXT,
    is_active INTEGER DEFAULT 1,
    priority TEXT DEFAULT 'normal',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE TABLE IF NOT EXISTS reminder_logs (
    id TEXT PRIMARY KEY,
    reminder_id TEXT NOT NULL,
    triggered_at TEXT NOT NULL,
    delivery_channel TEXT,
    delivery_status TEXT,
    response TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (reminder_id) REFERENCES reminders(id)
);

CREATE INDEX IF NOT EXISTS idx_reminders_member ON reminders(member_id, is_active);
CREATE INDEX IF NOT EXISTS idx_reminders_next_trigger ON reminders(next_trigger_at, is_active);
CREATE INDEX IF NOT EXISTS idx_reminder_logs ON reminder_logs(reminder_id, triggered_at);

-- Embeddings table for vector semantic search

CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    embedding BLOB,
    text_content TEXT,
    text_hash TEXT,
    model_name TEXT,
    dimensions INTEGER,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_embeddings_record ON embeddings(record_type, record_id);

-- Cycle tracking tables

CREATE TABLE IF NOT EXISTS cycle_records (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    cycle_type TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_date TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE TABLE IF NOT EXISTS cycle_predictions (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    cycle_type TEXT NOT NULL,
    predicted_start TEXT NOT NULL,
    predicted_end TEXT,
    confidence REAL,
    based_on_cycles INTEGER,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE INDEX IF NOT EXISTS idx_cycle_records_member ON cycle_records(member_id, cycle_type, event_date);
CREATE INDEX IF NOT EXISTS idx_cycle_predictions_member ON cycle_predictions(member_id, cycle_type, predicted_start);

-- Wearable device and sync tables

CREATE TABLE IF NOT EXISTS wearable_devices (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    device_name TEXT,
    device_id TEXT,
    config TEXT NOT NULL,
    supported_metrics TEXT,
    last_sync_at TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE INDEX IF NOT EXISTS idx_wearable_devices_member ON wearable_devices(member_id, is_active);

CREATE TABLE IF NOT EXISTS wearable_sync_log (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    sync_start TEXT NOT NULL,
    sync_end TEXT,
    status TEXT NOT NULL,
    metrics_synced INTEGER DEFAULT 0,
    metrics_skipped INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (device_id) REFERENCES wearable_devices(id)
);

CREATE INDEX IF NOT EXISTS idx_sync_log_device ON wearable_sync_log(device_id, created_at);

-- Health monitor tables

CREATE TABLE IF NOT EXISTS monitor_thresholds (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    level TEXT NOT NULL,
    direction TEXT NOT NULL,
    threshold_value REAL NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id),
    UNIQUE(member_id, metric_type, level, direction)
);

CREATE TABLE IF NOT EXISTS monitor_alerts (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    level TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    metric_value TEXT,
    threshold_value REAL,
    is_resolved INTEGER DEFAULT 0,
    status TEXT DEFAULT 'open',
    resolved_at TEXT,
    updated_at TEXT,
    resolved_by TEXT,
    resolution_note TEXT,
    last_reminder_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE INDEX IF NOT EXISTS idx_alerts_member ON monitor_alerts(member_id, level, is_resolved);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    member_id TEXT,
    owner_id TEXT,
    record_type TEXT,
    record_id TEXT,
    payload TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE INDEX IF NOT EXISTS idx_audit_events_type_time ON audit_events(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_member_time ON audit_events(member_id, created_at);

-- Diet tracking tables

CREATE TABLE IF NOT EXISTS diet_records (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    meal_date TEXT NOT NULL,
    meal_time TEXT,
    total_calories REAL DEFAULT 0,
    total_protein REAL DEFAULT 0,
    total_fat REAL DEFAULT 0,
    total_carbs REAL DEFAULT 0,
    total_fiber REAL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE TABLE IF NOT EXISTS diet_items (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    food_name TEXT NOT NULL,
    amount REAL,
    unit TEXT,
    calories REAL DEFAULT 0,
    protein REAL DEFAULT 0,
    fat REAL DEFAULT 0,
    carbs REAL DEFAULT 0,
    fiber REAL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (record_id) REFERENCES diet_records(id)
);

CREATE INDEX IF NOT EXISTS idx_diet_records_member ON diet_records(member_id, meal_date);
CREATE INDEX IF NOT EXISTS idx_diet_items_record ON diet_items(record_id);

-- Weight goal table

CREATE TABLE IF NOT EXISTS weight_goals (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    goal_type TEXT NOT NULL,
    start_weight REAL NOT NULL,
    target_weight REAL NOT NULL,
    start_date TEXT,
    target_date TEXT,
    daily_calorie_target INTEGER,
    status TEXT DEFAULT 'active',
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE INDEX IF NOT EXISTS idx_weight_goals_member ON weight_goals(member_id, status);

-- Exercise records table
CREATE TABLE IF NOT EXISTS exercise_records (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    exercise_type TEXT NOT NULL,
    exercise_name TEXT,
    duration INTEGER,
    calories_burned REAL DEFAULT 0,
    exercise_date TEXT NOT NULL,
    exercise_time TEXT,
    intensity TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_exercise_records_member ON exercise_records(member_id, exercise_date);

-- Attachment management tables

CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    sha256 TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_attachments_member ON attachments(member_id, category, is_deleted);
CREATE INDEX IF NOT EXISTS idx_attachments_sha256 ON attachments(sha256);

CREATE TABLE IF NOT EXISTS attachment_links (
    id TEXT PRIMARY KEY,
    attachment_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (attachment_id) REFERENCES attachments(id)
);
CREATE INDEX IF NOT EXISTS idx_attachment_links_attachment ON attachment_links(attachment_id, is_deleted);
CREATE INDEX IF NOT EXISTS idx_attachment_links_record ON attachment_links(record_type, record_id, is_deleted);

-- Health notes table for memory and proactive tracking

CREATE TABLE IF NOT EXISTS health_notes (
    id TEXT PRIMARY KEY,
    member_id TEXT,
    owner_id TEXT,
    content TEXT NOT NULL,
    category TEXT,
    mentioned_at TEXT NOT NULL,
    follow_up_date TEXT,
    is_resolved INTEGER DEFAULT 0,
    resolved_at TEXT,
    resolution_note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_health_notes_member ON health_notes(member_id, is_resolved);
CREATE INDEX IF NOT EXISTS idx_health_notes_follow_up ON health_notes(follow_up_date, is_resolved);

-- Medication intake logs (voluntary check-in)

CREATE TABLE IF NOT EXISTS medication_logs (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    medication_id TEXT,
    medication_name TEXT NOT NULL,
    taken_at TEXT NOT NULL,
    dose_taken TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (medication_id) REFERENCES medications(id)
);

CREATE INDEX IF NOT EXISTS idx_medication_logs_member ON medication_logs(member_id, medication_name, taken_at);

-- Chronic disease profiles (diabetes, hypertension management)

CREATE TABLE IF NOT EXISTS chronic_disease_profiles (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    disease_type TEXT NOT NULL,
    targets TEXT NOT NULL,
    diagnosed_date TEXT,
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);

CREATE INDEX IF NOT EXISTS idx_chronic_disease_member
    ON chronic_disease_profiles(member_id, disease_type, is_active);

"""

LIFESTYLE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS diet_records (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    meal_date TEXT NOT NULL,
    meal_time TEXT,
    total_calories REAL DEFAULT 0,
    total_protein REAL DEFAULT 0,
    total_fat REAL DEFAULT 0,
    total_carbs REAL DEFAULT 0,
    total_fiber REAL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS diet_items (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    food_name TEXT NOT NULL,
    amount REAL,
    unit TEXT,
    calories REAL DEFAULT 0,
    protein REAL DEFAULT 0,
    fat REAL DEFAULT 0,
    carbs REAL DEFAULT 0,
    fiber REAL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (record_id) REFERENCES diet_records(id)
);

CREATE INDEX IF NOT EXISTS idx_diet_records_member ON diet_records(member_id, meal_date);
CREATE INDEX IF NOT EXISTS idx_diet_items_record ON diet_items(record_id);

CREATE TABLE IF NOT EXISTS weight_goals (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    goal_type TEXT NOT NULL,
    start_weight REAL NOT NULL,
    target_weight REAL NOT NULL,
    start_date TEXT,
    target_date TEXT,
    daily_calorie_target INTEGER,
    status TEXT DEFAULT 'active',
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_weight_goals_member ON weight_goals(member_id, status);

CREATE TABLE IF NOT EXISTS exercise_records (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    exercise_type TEXT NOT NULL,
    exercise_name TEXT,
    duration INTEGER,
    calories_burned REAL DEFAULT 0,
    exercise_date TEXT NOT NULL,
    exercise_time TEXT,
    intensity TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_exercise_records_member ON exercise_records(member_id, exercise_date);

CREATE TABLE IF NOT EXISTS nutrition_goals (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    calories INTEGER,
    protein_g REAL,
    fat_g REAL,
    carbs_g REAL,
    fiber_g REAL,
    is_active INTEGER DEFAULT 1,
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_nutrition_goals_member ON nutrition_goals(member_id, is_active);

CREATE TABLE IF NOT EXISTS wearable_devices (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    device_name TEXT,
    device_id TEXT,
    config TEXT NOT NULL,
    supported_metrics TEXT,
    last_sync_at TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_wearable_devices_member ON wearable_devices(member_id, is_active);

CREATE TABLE IF NOT EXISTS wearable_sync_log (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    sync_start TEXT NOT NULL,
    sync_end TEXT,
    status TEXT NOT NULL,
    metrics_synced INTEGER DEFAULT 0,
    metrics_skipped INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (device_id) REFERENCES wearable_devices(id)
);

CREATE INDEX IF NOT EXISTS idx_sync_log_device ON wearable_sync_log(device_id, created_at);
"""


def _schema_sql_for_domain(domain: str) -> str:
    return LIFESTYLE_SCHEMA_SQL if domain == "lifestyle" else SCHEMA_SQL


def get_connection():
    """Get legacy default connection (medical DB) for compatibility."""
    return get_medical_connection()


def get_medical_connection():
    """Get a connection to the medical database."""
    return _open_connection(get_medical_db_path())


def get_lifestyle_connection():
    """Get a connection to the lifestyle database."""
    return _open_connection(get_lifestyle_db_path())


def get_connection_for_domain(domain: str):
    """Get a connection for a specific data domain."""
    if domain == "lifestyle":
        return get_lifestyle_connection()
    return get_medical_connection()


def get_connection_for_table(table_name: str):
    """Get a connection by table name routing."""
    return get_connection_for_domain(get_table_domain(table_name))


def init_db(domain: str = "medical"):
    """Initialize schema for a specific database domain."""
    conn = get_connection_for_domain(domain)
    try:
        conn.executescript(_schema_sql_for_domain(domain))
        cursor = conn.execute("SELECT version FROM schema_version LIMIT 1")
        row = cursor.fetchone()
        if not row:
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
        conn.commit()
    finally:
        conn.close()


def ensure_db():
    """Ensure config is initialized and database is ready.

    On first run:
    1. Auto-creates config file with defaults
    2. Creates database and schema
    3. Returns config status (with issues list for agent to act on)
    """
    status = _auto_init_config()
    db_path = get_db_path()
    medical_db_path = get_medical_db_path()
    lifestyle_db_path = get_lifestyle_db_path()

    created_any = False
    if not os.path.exists(medical_db_path):
        init_db("medical")
        status["medical_db_exists"] = True
        status["db_exists"] = True
        created_any = True

    if not os.path.exists(lifestyle_db_path):
        init_db("lifestyle")
        status["lifestyle_db_exists"] = True
        created_any = True

    status["first_run"] = created_any

    conn = get_medical_connection()
    try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='members'")
            if not cursor.fetchone():
                conn.executescript(SCHEMA_SQL)
                conn.commit()
            else:
                # Migrate: add embeddings table if missing (v2 -> v3)
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='embeddings'")
                if not cursor.fetchone():
                    conn.executescript("""
CREATE TABLE IF NOT EXISTS embeddings (
    id TEXT PRIMARY KEY,
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    embedding BLOB,
    text_content TEXT,
    text_hash TEXT,
    model_name TEXT,
    dimensions INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_embeddings_record ON embeddings(record_type, record_id);
""")
                    conn.execute("UPDATE schema_version SET version=?", (3,))
                    conn.commit()
                # Migrate: add reminders tables if missing (v3 -> v4)
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reminders'")
                if not cursor.fetchone():
                    conn.executescript("""
CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    schedule_type TEXT NOT NULL,
    schedule_value TEXT,
    next_trigger_at TEXT,
    last_triggered_at TEXT,
    related_record_id TEXT,
    related_record_type TEXT,
    is_active INTEGER DEFAULT 1,
    priority TEXT DEFAULT 'normal',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE TABLE IF NOT EXISTS reminder_logs (
    id TEXT PRIMARY KEY,
    reminder_id TEXT NOT NULL,
    triggered_at TEXT NOT NULL,
    delivery_channel TEXT,
    delivery_status TEXT,
    response TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (reminder_id) REFERENCES reminders(id)
);
CREATE INDEX IF NOT EXISTS idx_reminders_member ON reminders(member_id, is_active);
CREATE INDEX IF NOT EXISTS idx_reminders_next_trigger ON reminders(next_trigger_at, is_active);
CREATE INDEX IF NOT EXISTS idx_reminder_logs ON reminder_logs(reminder_id, triggered_at);
""")
                    conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
                    conn.commit()
                # Migrate: add custom_metric_ranges and timezone to members (v4 -> v5)
                # Always check columns regardless of version number (handles
                # databases where version was bumped but columns are missing)
                existing = [row[1] for row in conn.execute("PRAGMA table_info(members)").fetchall()]
                migrated = False
                if "custom_metric_ranges" not in existing:
                    conn.execute("ALTER TABLE members ADD COLUMN custom_metric_ranges TEXT")
                    migrated = True
                if "timezone" not in existing:
                    conn.execute("ALTER TABLE members ADD COLUMN timezone TEXT")
                    migrated = True
                current_version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                if migrated or (current_version and current_version[0] < 5):
                    conn.execute("UPDATE schema_version SET version=?", (5,))
                    conn.commit()
                # Migrate: add cycle tracking tables if missing (v5 -> v6)
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cycle_records'")
                if not cursor.fetchone():
                    conn.executescript("""
CREATE TABLE IF NOT EXISTS cycle_records (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    cycle_type TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_date TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE TABLE IF NOT EXISTS cycle_predictions (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    cycle_type TEXT NOT NULL,
    predicted_start TEXT NOT NULL,
    predicted_end TEXT,
    confidence REAL,
    based_on_cycles INTEGER,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_cycle_records_member ON cycle_records(member_id, cycle_type, event_date);
CREATE INDEX IF NOT EXISTS idx_cycle_predictions_member ON cycle_predictions(member_id, cycle_type, predicted_start);
""")
                    conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
                    conn.commit()
                else:
                    # Tables exist but version may be stale
                    current_version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                    if current_version and current_version[0] < SCHEMA_VERSION:
                        conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
                        conn.commit()
                # Migrate: add owner_id to members (v6 -> v7)
                existing = [row[1] for row in conn.execute("PRAGMA table_info(members)").fetchall()]
                if "owner_id" not in existing:
                    conn.execute("ALTER TABLE members ADD COLUMN owner_id TEXT")
                    conn.executescript("CREATE INDEX IF NOT EXISTS idx_members_owner ON members(owner_id);")
                    conn.execute("UPDATE schema_version SET version=?", (7,))
                    conn.commit()
                else:
                    current_version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                    if current_version and current_version[0] < 7:
                        conn.execute("UPDATE schema_version SET version=?", (7,))
                        conn.commit()
                # Migrate: add wearable & monitor tables, source column (v7 -> v8)
                existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(health_metrics)").fetchall()]
                if "source" not in existing_cols:
                    conn.execute("ALTER TABLE health_metrics ADD COLUMN source TEXT DEFAULT 'manual'")
                wearable_tables = {
                    "wearable_devices": """
CREATE TABLE IF NOT EXISTS wearable_devices (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    device_name TEXT,
    device_id TEXT,
    config TEXT NOT NULL,
    supported_metrics TEXT,
    last_sync_at TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_wearable_devices_member ON wearable_devices(member_id, is_active);
""",
                    "wearable_sync_log": """
CREATE TABLE IF NOT EXISTS wearable_sync_log (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    sync_start TEXT NOT NULL,
    sync_end TEXT,
    status TEXT NOT NULL,
    metrics_synced INTEGER DEFAULT 0,
    metrics_skipped INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (device_id) REFERENCES wearable_devices(id)
);
CREATE INDEX IF NOT EXISTS idx_sync_log_device ON wearable_sync_log(device_id, created_at);
""",
                    "monitor_thresholds": """
CREATE TABLE IF NOT EXISTS monitor_thresholds (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    level TEXT NOT NULL,
    direction TEXT NOT NULL,
    threshold_value REAL NOT NULL,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id),
    UNIQUE(member_id, metric_type, level, direction)
);
""",
                    "monitor_alerts": """
CREATE TABLE IF NOT EXISTS monitor_alerts (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    metric_type TEXT NOT NULL,
    level TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT,
    metric_value TEXT,
    threshold_value REAL,
    is_resolved INTEGER DEFAULT 0,
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_alerts_member ON monitor_alerts(member_id, level, is_resolved);
""",
                }
                v8_migrated = False
                for tbl_name, tbl_sql in wearable_tables.items():
                    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl_name,))
                    if not cursor.fetchone():
                        conn.executescript(tbl_sql)
                        v8_migrated = True
                current_version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                if v8_migrated or (current_version and current_version[0] < 8):
                    conn.execute("UPDATE schema_version SET version=?", (8,))
                    conn.commit()
                # Migrate: add diet & weight goal tables (v8 -> v9)
                v9_tables = {
                    "diet_records": """
CREATE TABLE IF NOT EXISTS diet_records (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    meal_type TEXT NOT NULL,
    meal_date TEXT NOT NULL,
    meal_time TEXT,
    total_calories REAL DEFAULT 0,
    total_protein REAL DEFAULT 0,
    total_fat REAL DEFAULT 0,
    total_carbs REAL DEFAULT 0,
    total_fiber REAL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_diet_records_member ON diet_records(member_id, meal_date);
""",
                    "diet_items": """
CREATE TABLE IF NOT EXISTS diet_items (
    id TEXT PRIMARY KEY,
    record_id TEXT NOT NULL,
    food_name TEXT NOT NULL,
    amount REAL,
    unit TEXT,
    calories REAL DEFAULT 0,
    protein REAL DEFAULT 0,
    fat REAL DEFAULT 0,
    carbs REAL DEFAULT 0,
    fiber REAL DEFAULT 0,
    note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (record_id) REFERENCES diet_records(id)
);
CREATE INDEX IF NOT EXISTS idx_diet_items_record ON diet_items(record_id);
""",
                    "weight_goals": """
CREATE TABLE IF NOT EXISTS weight_goals (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    goal_type TEXT NOT NULL,
    start_weight REAL NOT NULL,
    target_weight REAL NOT NULL,
    start_date TEXT,
    target_date TEXT,
    daily_calorie_target INTEGER,
    status TEXT DEFAULT 'active',
    note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_weight_goals_member ON weight_goals(member_id, status);
""",
                }
                v9_migrated = False
                for tbl_name, tbl_sql in v9_tables.items():
                    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl_name,))
                    if not cursor.fetchone():
                        conn.executescript(tbl_sql)
                        v9_migrated = True
                current_version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                if v9_migrated or (current_version and current_version[0] < 9):
                    conn.execute("UPDATE schema_version SET version=?", (9,))
                    conn.commit()
                # Migrate: add exercise_records table (v9 -> v10)
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='exercise_records'")
                if not cursor.fetchone():
                    conn.executescript("""
CREATE TABLE IF NOT EXISTS exercise_records (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    exercise_type TEXT NOT NULL,
    exercise_name TEXT,
    duration INTEGER,
    calories_burned REAL DEFAULT 0,
    exercise_date TEXT NOT NULL,
    exercise_time TEXT,
    intensity TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_exercise_records_member ON exercise_records(member_id, exercise_date);
""")
                    conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
                    conn.commit()
                else:
                    current_version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                    if current_version and current_version[0] < SCHEMA_VERSION:
                        conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
                        conn.commit()
                # Migrate: add attachment tables (v10 -> v11)
                v11_tables = {
                    "attachments": """
CREATE TABLE IF NOT EXISTS attachments (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    sha256 TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_attachments_member ON attachments(member_id, category, is_deleted);
CREATE INDEX IF NOT EXISTS idx_attachments_sha256 ON attachments(sha256);
""",
                    "attachment_links": """
CREATE TABLE IF NOT EXISTS attachment_links (
    id TEXT PRIMARY KEY,
    attachment_id TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (attachment_id) REFERENCES attachments(id)
);
CREATE INDEX IF NOT EXISTS idx_attachment_links_attachment ON attachment_links(attachment_id, is_deleted);
CREATE INDEX IF NOT EXISTS idx_attachment_links_record ON attachment_links(record_type, record_id, is_deleted);
""",
                }
                v11_migrated = False
                for tbl_name, tbl_sql in v11_tables.items():
                    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (tbl_name,))
                    if not cursor.fetchone():
                        conn.executescript(tbl_sql)
                        v11_migrated = True
                current_version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                if v11_migrated or (current_version and current_version[0] < 11):
                    conn.execute("UPDATE schema_version SET version=?", (11,))
                    conn.commit()
                alert_cols = [row[1] for row in conn.execute("PRAGMA table_info(monitor_alerts)").fetchall()]
                v12_migrated = False
                if "status" not in alert_cols:
                    conn.execute("ALTER TABLE monitor_alerts ADD COLUMN status TEXT DEFAULT 'open'")
                    v12_migrated = True
                if "updated_at" not in alert_cols:
                    conn.execute("ALTER TABLE monitor_alerts ADD COLUMN updated_at TEXT")
                    v12_migrated = True
                if "resolved_by" not in alert_cols:
                    conn.execute("ALTER TABLE monitor_alerts ADD COLUMN resolved_by TEXT")
                    v12_migrated = True
                if "resolution_note" not in alert_cols:
                    conn.execute("ALTER TABLE monitor_alerts ADD COLUMN resolution_note TEXT")
                    v12_migrated = True
                if "last_reminder_id" not in alert_cols:
                    conn.execute("ALTER TABLE monitor_alerts ADD COLUMN last_reminder_id TEXT")
                    v12_migrated = True
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='audit_events'")
                if not cursor.fetchone():
                    conn.executescript("""
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    member_id TEXT,
    owner_id TEXT,
    record_type TEXT,
    record_id TEXT,
    payload TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_audit_events_type_time ON audit_events(event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_audit_events_member_time ON audit_events(member_id, created_at);
""")
                    v12_migrated = True
                conn.execute(
                    """UPDATE monitor_alerts
                       SET status=CASE WHEN is_resolved=1 THEN 'resolved' ELSE 'open' END
                       WHERE status IS NULL OR status=''"""
                )
                conn.execute(
                    "UPDATE monitor_alerts SET updated_at=COALESCE(updated_at, resolved_at, created_at) WHERE updated_at IS NULL"
                )
                current_version = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
                if v12_migrated or (current_version and current_version[0] < SCHEMA_VERSION):
                    conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
                    conn.commit()
                # Migrate: visit lifecycle columns + health_notes table (v12 -> v13)
                visit_cols = [row[1] for row in conn.execute("PRAGMA table_info(visits)").fetchall()]
                v13_migrated = False
                if "visit_status" not in visit_cols:
                    conn.execute("ALTER TABLE visits ADD COLUMN visit_status TEXT DEFAULT 'completed'")
                    v13_migrated = True
                if "follow_up_date" not in visit_cols:
                    conn.execute("ALTER TABLE visits ADD COLUMN follow_up_date TEXT")
                    v13_migrated = True
                if "follow_up_notes" not in visit_cols:
                    conn.execute("ALTER TABLE visits ADD COLUMN follow_up_notes TEXT")
                    v13_migrated = True
                metric_cols = [row[1] for row in conn.execute("PRAGMA table_info(health_metrics)").fetchall()]
                if "context" not in metric_cols:
                    conn.execute("ALTER TABLE health_metrics ADD COLUMN context TEXT DEFAULT 'routine'")
                    v13_migrated = True
                if "related_visit_id" not in metric_cols:
                    conn.execute("ALTER TABLE health_metrics ADD COLUMN related_visit_id TEXT")
                    v13_migrated = True
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='health_notes'"
                )
                if not cursor.fetchone():
                    conn.executescript("""
CREATE TABLE IF NOT EXISTS health_notes (
    id TEXT PRIMARY KEY,
    member_id TEXT,
    owner_id TEXT,
    content TEXT NOT NULL,
    category TEXT,
    mentioned_at TEXT NOT NULL,
    follow_up_date TEXT,
    is_resolved INTEGER DEFAULT 0,
    resolved_at TEXT,
    resolution_note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_health_notes_member ON health_notes(member_id, is_resolved);
CREATE INDEX IF NOT EXISTS idx_health_notes_follow_up ON health_notes(follow_up_date, is_resolved);
""")
                    v13_migrated = True
                if v13_migrated:
                    conn.execute("UPDATE schema_version SET version=?", (13,))
                    conn.commit()
                # Migrate: add medication_logs table (v13 -> v14)
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='medication_logs'"
                )
                if not cursor.fetchone():
                    conn.executescript("""
CREATE TABLE IF NOT EXISTS medication_logs (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    medication_id TEXT,
    medication_name TEXT NOT NULL,
    taken_at TEXT NOT NULL,
    dose_taken TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id),
    FOREIGN KEY (medication_id) REFERENCES medications(id)
);
CREATE INDEX IF NOT EXISTS idx_medication_logs_member ON medication_logs(member_id, medication_name, taken_at);
""")
                    conn.execute("UPDATE schema_version SET version=?", (14,))
                    conn.commit()
                # Migrate: add chronic_disease_profiles table (v14 -> v15)
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='chronic_disease_profiles'"
                )
                if not cursor.fetchone():
                    conn.executescript("""
CREATE TABLE IF NOT EXISTS chronic_disease_profiles (
    id TEXT PRIMARY KEY,
    member_id TEXT NOT NULL,
    disease_type TEXT NOT NULL,
    targets TEXT NOT NULL,
    diagnosed_date TEXT,
    notes TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER DEFAULT 0,
    FOREIGN KEY (member_id) REFERENCES members(id)
);
CREATE INDEX IF NOT EXISTS idx_chronic_disease_member
    ON chronic_disease_profiles(member_id, disease_type, is_active);
""")
                    conn.execute("UPDATE schema_version SET version=?", (15,))
                    conn.commit()
    finally:
        conn.close()
    _set_last_status(status)
    return status


def generate_id():
    """Generate a short unique ID."""
    import uuid
    return uuid.uuid4().hex[:12]


import contextlib

@contextlib.contextmanager
def transaction(domain: str = "medical", table_name: str | None = None):
    """Context manager for database write operations with auto-rollback on error.

    Usage:
        with transaction() as conn:
            conn.execute(...)
            conn.commit()

        with transaction(domain="lifestyle") as conn:
            conn.execute(...)
            conn.commit()

        with transaction(table_name="diet_records") as conn:
            conn.execute(...)
            conn.commit()

    On exception, conn.rollback() is called before re-raising.
    """
    if table_name:
        conn = get_connection_for_table(table_name)
    else:
        conn = get_connection_for_domain(domain)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now_iso():
    """Return current time in ISO format."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _fetch_member_owner_id(conn, member_id):
    row = conn.execute(
        "SELECT owner_id FROM members WHERE id=? AND is_deleted=0", (member_id,)
    ).fetchone()
    if not row:
        return None
    return row["owner_id"]


def _resolve_member_owner_id(conn, member_id):
    try:
        return _fetch_member_owner_id(conn, member_id)
    except sqlite3.OperationalError:
        pass
    medical_conn = get_medical_connection()
    try:
        return _fetch_member_owner_id(medical_conn, member_id)
    finally:
        medical_conn.close()


def verify_member_ownership(conn, member_id, owner_id):
    """Verify member belongs to owner.

    Resolution order:
    1. Explicit ``owner_id`` argument
    2. ``MEDIWISE_OWNER_ID`` environment variable
    3. No owner context → allow (admin / direct CLI use)
    """
    effective = owner_id or os.environ.get("MEDIWISE_OWNER_ID")
    if not effective:
        return True
    actual_owner_id = _resolve_member_owner_id(conn, member_id)
    if not actual_owner_id:
        return False
    return actual_owner_id == effective


def get_record_member_id(conn, table, record_id):
    """Return the member_id for a row in a member-owned table."""
    row = conn.execute(
        f"SELECT member_id FROM {table} WHERE id=? AND is_deleted=0",
        (record_id,)
    ).fetchone()
    if not row:
        return None
    return row["member_id"]


def verify_record_ownership(conn, table, record_id, owner_id):
    """Verify a member-owned record belongs to ``owner_id`` (or env-var context)."""
    effective = owner_id or os.environ.get("MEDIWISE_OWNER_ID")
    if not effective:
        return True
    member_id = get_record_member_id(conn, table, record_id)
    if not member_id:
        return False
    return verify_member_ownership(conn, member_id, effective)


def get_member_owner_id(conn, member_id):
    return _resolve_member_owner_id(conn, member_id)


def append_audit_event(conn, event_type, member_id=None, owner_id=None,
                       record_type=None, record_id=None, payload=None):
    conn.execute(
        """INSERT INTO audit_events
           (id, event_type, member_id, owner_id, record_type, record_id, payload, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            generate_id(),
            event_type,
            member_id,
            owner_id,
            record_type,
            record_id,
            json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")),
            now_iso(),
        ),
    )


def row_to_dict(row):
    """Convert a sqlite3.Row to a dict."""
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    """Convert a list of sqlite3.Row to a list of dicts."""
    return [dict(r) for r in rows]


def output_json(data):
    """Print data as formatted JSON. Auto-attaches config issues on first run."""
    if _last_status and _last_status.get("issues"):
        data["_config_issues"] = _last_status["issues"]
    if _last_status and _last_status.get("first_run"):
        data["_first_run"] = True
        data["_config_path"] = _last_status.get("config_path", "")
        data["_data_dir"] = _last_status.get("data_dir", "")
    print(json.dumps(data, ensure_ascii=False, indent=2))


# Holds the last ensure_db status for output_json to reference
_last_status = None


def _set_last_status(status):
    global _last_status
    _last_status = status
