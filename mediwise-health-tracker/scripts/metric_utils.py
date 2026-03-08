"""Shared metric utilities for cross-module use.

Provides unified functions for:
- Metric value parsing
- Age calculation
- BMR/TDEE calculation
- Member lookup
- Standard metric unit definitions
"""

from __future__ import annotations

import json
from datetime import datetime


# --- Unified metric units dictionary ---

METRIC_UNITS = {
    "heart_rate": "bpm",
    "blood_oxygen": "%",
    "temperature": "°C",
    "blood_sugar": "mmol/L",
    "blood_pressure": "mmHg",
    "blood_pressure_systolic": "mmHg",
    "blood_pressure_diastolic": "mmHg",
    "weight": "kg",
    "height": "cm",
    "steps": "步",
    "stress": "",
    "calories": "kcal",
    "waist": "cm",
    "hip": "cm",
    "chest": "cm",
    "arm": "cm",
    "thigh": "cm",
    "body_fat": "%",
}


def parse_metric_value(value_str: str) -> dict:
    """Parse metric value from JSON string or plain number.

    Handles:
    - JSON objects like '{"systolic": 120, "diastolic": 80}'
    - JSON numbers like '72'
    - Plain number strings like '36.5'

    Returns:
        Dict with parsed values. For simple numbers, returns {"value": <float>}.
        Returns empty dict if parsing fails.
    """
    try:
        v = json.loads(value_str)
        if isinstance(v, dict):
            return v
        return {"value": float(v)}
    except (json.JSONDecodeError, TypeError, ValueError):
        try:
            return {"value": float(value_str)}
        except (TypeError, ValueError):
            return {}


def extract_numeric_value(raw_value: str, metric_type: str) -> float | None:
    """Extract a single numeric value from a raw metric value string.

    For 'steps', extracts 'count'; for 'blood_sugar', prefers fasting /
    postprandial / random; other types use 'value'.

    Returns:
        The numeric value as float, or None if extraction fails.
    """
    parsed = parse_metric_value(raw_value)
    if metric_type == "steps":
        v = parsed.get("count", parsed.get("value"))
    elif metric_type == "blood_sugar":
        v = parsed.get(
            "fasting",
            parsed.get(
                "postprandial",
                parsed.get("random", parsed.get("value"))
            )
        )
    else:
        v = parsed.get("value")
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    return None


def calculate_age(birth_date_str: str) -> int | None:
    """Calculate age from birth date string (YYYY-MM-DD).

    Args:
        birth_date_str: Date string in YYYY-MM-DD format.

    Returns:
        Age in years, or None if input is invalid.
    """
    if not birth_date_str:
        return None
    try:
        birth = datetime.strptime(birth_date_str[:10], "%Y-%m-%d")
        today = datetime.now()
        return today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    except (ValueError, TypeError):
        return None


def calculate_bmr(weight: float, height: float, age: int, gender: str) -> float:
    """Calculate Basal Metabolic Rate using Mifflin-St Jeor formula.

    Args:
        weight: Weight in kg.
        height: Height in cm.
        age: Age in years.
        gender: 'male' or 'female'.

    Returns:
        BMR in kcal/day.
    """
    if gender == "male":
        return 10 * weight + 6.25 * height - 5 * age + 5
    else:
        return 10 * weight + 6.25 * height - 5 * age - 161


def calculate_tdee(bmr: float, activity_level: str) -> float:
    """Calculate Total Daily Energy Expenditure from BMR and activity level.

    Args:
        bmr: Basal Metabolic Rate in kcal/day.
        activity_level: One of 'sedentary', 'light', 'moderate', 'active', 'very_active'.

    Returns:
        TDEE in kcal/day.
    """
    multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }
    multiplier = multipliers.get(activity_level, 1.2)
    return bmr * multiplier


def get_member_or_error(conn, member_id: str) -> dict | None:
    """Look up a member by ID, returning the row dict or None.

    Args:
        conn: Database connection.
        member_id: Member ID to look up.

    Returns:
        Row dict if found, None otherwise.
    """
    row = conn.execute(
        "SELECT * FROM members WHERE id=? AND is_deleted=0",
        (member_id,)
    ).fetchone()
    return dict(row) if row else None
