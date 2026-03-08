"""Generate a sample Gadgetbridge SQLite database for testing.

Creates a mock database with 48 hours of simulated data:
- Heart rate samples (every 5 minutes)
- Step data (every 5 minutes)
- SpO2 readings (every 30 minutes)
- Sleep activity types (8 hours per night)
"""

import sqlite3
import os
import random
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "gadgetbridge_sample.db")


def create_sample_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = sqlite3.connect(DB_PATH)

    # Create MI_BAND_ACTIVITY_SAMPLE table (main table for most Gadgetbridge devices)
    conn.execute("""
        CREATE TABLE MI_BAND_ACTIVITY_SAMPLE (
            TIMESTAMP INTEGER NOT NULL,
            DEVICE_ID INTEGER NOT NULL,
            USER_ID INTEGER NOT NULL,
            RAW_INTENSITY INTEGER NOT NULL,
            STEPS INTEGER NOT NULL,
            RAW_KIND INTEGER NOT NULL,
            HEART_RATE INTEGER NOT NULL
        )
    """)

    # Create HUAMI_EXTENDED_ACTIVITY_SAMPLE table (for SpO2 data)
    conn.execute("""
        CREATE TABLE HUAMI_EXTENDED_ACTIVITY_SAMPLE (
            TIMESTAMP INTEGER NOT NULL,
            DEVICE_ID INTEGER NOT NULL,
            USER_ID INTEGER NOT NULL,
            RAW_INTENSITY INTEGER NOT NULL,
            STEPS INTEGER NOT NULL,
            RAW_KIND INTEGER NOT NULL,
            HEART_RATE INTEGER NOT NULL,
            SPO2 INTEGER DEFAULT 0
        )
    """)

    now = datetime.now()
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=48)

    # Activity type constants
    ACTIVITY_NOT_MEASURED = 0
    ACTIVITY_NOT_WORN = 10
    ACTIVITY_LIGHT_SLEEP = 112
    ACTIVITY_DEEP_SLEEP = 121
    ACTIVITY_REM_SLEEP = 122
    ACTIVITY_NORMAL = 1

    samples_main = []
    samples_extended = []

    current = start
    while current < now:
        ts = int(current.timestamp())
        hour = current.hour

        # Determine activity type and values based on time of day
        if 23 <= hour or hour < 7:
            # Night time — sleep
            if hour in (23, 0, 1):
                raw_kind = ACTIVITY_LIGHT_SLEEP
            elif hour in (2, 3):
                raw_kind = ACTIVITY_DEEP_SLEEP
            elif hour in (4, 5):
                raw_kind = ACTIVITY_REM_SLEEP
            else:
                raw_kind = ACTIVITY_LIGHT_SLEEP

            hr = random.randint(50, 65)
            steps = 0
            intensity = random.randint(0, 20)
        else:
            # Daytime — normal activity
            raw_kind = ACTIVITY_NORMAL
            hr = random.randint(65, 95)
            # More steps during active hours
            if 8 <= hour <= 20:
                steps = random.randint(0, 50)
                intensity = random.randint(20, 100)
            else:
                steps = random.randint(0, 10)
                intensity = random.randint(0, 30)

        # Some anomalous readings for testing alerts
        if current == start + timedelta(hours=24):
            hr = 135  # High heart rate for alert testing

        if current == start + timedelta(hours=36):
            hr = 42  # Low heart rate for alert testing

        samples_main.append((ts, 1, 1, intensity, steps, raw_kind, hr))

        # SpO2 every 30 minutes
        if current.minute == 0 or current.minute == 30:
            spo2 = random.randint(95, 99)
            # One low reading for testing
            if current == start + timedelta(hours=30):
                spo2 = 88
            samples_extended.append((ts, 1, 1, intensity, steps, raw_kind, hr, spo2))

        current += timedelta(minutes=5)

    conn.executemany(
        "INSERT INTO MI_BAND_ACTIVITY_SAMPLE VALUES (?, ?, ?, ?, ?, ?, ?)",
        samples_main
    )
    conn.executemany(
        "INSERT INTO HUAMI_EXTENDED_ACTIVITY_SAMPLE VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        samples_extended
    )

    conn.commit()
    total_main = conn.execute("SELECT COUNT(*) FROM MI_BAND_ACTIVITY_SAMPLE").fetchone()[0]
    total_ext = conn.execute("SELECT COUNT(*) FROM HUAMI_EXTENDED_ACTIVITY_SAMPLE").fetchone()[0]
    conn.close()

    print(f"Sample Gadgetbridge DB created: {DB_PATH}")
    print(f"  MI_BAND_ACTIVITY_SAMPLE: {total_main} rows")
    print(f"  HUAMI_EXTENDED_ACTIVITY_SAMPLE: {total_ext} rows")
    print(f"  Time range: {start.isoformat()} to {now.isoformat()}")


if __name__ == "__main__":
    create_sample_db()
