"""Shared metric calculation utilities.

Provides reusable functions for age, BMR (Mifflin-St Jeor), and TDEE calculations
used across weight-manager and other modules.
"""

from __future__ import annotations

from datetime import datetime

ACTIVITY_LEVELS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


def calculate_age(birth_date_str: str) -> int:
    """Calculate age from birth date string (YYYY-MM-DD)."""
    birth = datetime.strptime(birth_date_str, "%Y-%m-%d").date()
    today = datetime.now().date()
    age = today.year - birth.year
    if (today.month, today.day) < (birth.month, birth.day):
        age -= 1
    return age


def calculate_bmr(weight: float, height: float, age: int, gender: str) -> float:
    """Calculate BMR using Mifflin-St Jeor formula.

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
    """Calculate TDEE from BMR and activity level.

    Args:
        bmr: Basal metabolic rate in kcal/day.
        activity_level: One of 'sedentary', 'light', 'moderate', 'active', 'very_active'.

    Returns:
        TDEE in kcal/day.
    """
    multiplier = ACTIVITY_LEVELS.get(activity_level, 1.2)
    return bmr * multiplier
