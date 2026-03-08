"""Shared validation module for MediWise Health Tracker.

Provides date validation, medical metric range checks, and intake schema validation.
"""

from __future__ import annotations

import json
import re
from datetime import datetime


def validate_date(value, field_name="日期"):
    """Validate a required YYYY-MM-DD date string.

    Returns the validated date string.
    Raises ValueError if invalid.
    """
    if not value or not isinstance(value, str):
        raise ValueError(f"{field_name} 不能为空")
    value = value.strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise ValueError(f"{field_name} 格式错误，应为 YYYY-MM-DD，收到: {value}")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{field_name} 日期不合法: {value}")
    return value


def validate_date_optional(value, field_name="日期"):
    """Validate an optional YYYY-MM-DD date string.

    Returns validated string or None if empty/None.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return validate_date(value, field_name)


def validate_datetime_optional(value, field_name="日期时间"):
    """Validate an optional YYYY-MM-DD HH:MM datetime string.

    Also accepts plain YYYY-MM-DD.
    Returns validated string or None if empty/None.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    value = value.strip()
    # Accept YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return validate_date(value, field_name)
    # Accept YYYY-MM-DD HH:MM
    if not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", value):
        raise ValueError(f"{field_name} 格式错误，应为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM，收到: {value}")
    try:
        datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError(f"{field_name} 日期时间不合法: {value}")
    return value


# Metric range definitions: (min, max)
_METRIC_RANGES = {
    "blood_sugar": (0.5, 50),       # mmol/L
    "heart_rate": (20, 300),         # bpm
    "weight": (0.5, 500),            # kg
    "temperature": (30.0, 45.0),     # °C
    "blood_oxygen": (50, 100),       # %
    "height": (20, 300),             # cm
    "stress": (0, 100),              # score
    "calories": (0, 99999),          # kcal
    "waist": (30, 200),              # cm
    "hip": (30, 200),                # cm
    "chest": (30, 200),              # cm
    "arm": (10, 80),                 # cm
    "thigh": (20, 100),              # cm
    "body_fat": (2, 60),             # %
}


def validate_metric_value(metric_type, value):
    """Validate a health metric value against known ranges.

    For blood_pressure: validates JSON with systolic (40-300) and diastolic (20-200),
    and ensures diastolic < systolic.

    For other types: validates numeric value within range.

    Returns the validated value (string for blood_pressure JSON, original string otherwise).
    Raises ValueError or json.JSONDecodeError on invalid input.
    """
    if metric_type == "blood_pressure":
        v = json.loads(value) if isinstance(value, str) else value
        if not isinstance(v, dict) or "systolic" not in v or "diastolic" not in v:
            raise ValueError('血压值格式应为: {"systolic": 130, "diastolic": 85}')
        try:
            sys_val = float(v["systolic"])
            dia_val = float(v["diastolic"])
        except (ValueError, TypeError):
            raise ValueError("血压值必须为数值")
        if not (40 <= sys_val <= 300):
            raise ValueError(f"收缩压超出合理范围 (40-300 mmHg)，收到: {sys_val}")
        if not (20 <= dia_val <= 200):
            raise ValueError(f"舒张压超出合理范围 (20-200 mmHg)，收到: {dia_val}")
        if dia_val >= sys_val:
            raise ValueError(f"舒张压 ({dia_val}) 应小于收缩压 ({sys_val})")
        return json.dumps(v, ensure_ascii=False)

    # JSON-structured types (sleep, steps) — validate structure, pass through
    if metric_type in ("sleep", "steps"):
        if isinstance(value, str):
            try:
                v = json.loads(value)
            except json.JSONDecodeError:
                raise ValueError(f"{metric_type} 值应为 JSON 格式")
            if not isinstance(v, dict):
                raise ValueError(f"{metric_type} 值应为 JSON 对象")
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    # Numeric types
    try:
        num = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"指标值应为数值，收到: {value}")

    if metric_type in _METRIC_RANGES:
        lo, hi = _METRIC_RANGES[metric_type]
        if not (lo <= num <= hi):
            units = {
                "blood_sugar": "mmol/L", "heart_rate": "bpm", "weight": "kg",
                "temperature": "°C", "blood_oxygen": "%", "height": "cm",
            }
            unit = units.get(metric_type, "")
            raise ValueError(f"{metric_type} 超出合理范围 ({lo}-{hi} {unit})，收到: {num}")

    return value


_VALID_RECORD_TYPES = {"visit", "symptom", "medication", "lab_result", "imaging", "health_metric"}
_MAX_RECORDS = 100
_MAX_STRING_LEN = 5000


def validate_intake_records(records):
    """Validate intake records array structure.

    Checks:
    - records is a list
    - length <= 100
    - each item has "type" (string in valid set) and "data" (dict)
    - string field values <= 5000 chars

    Returns the validated records list.
    Raises ValueError on invalid input.
    """
    if not isinstance(records, list):
        raise ValueError("records 必须为数组")
    if len(records) > _MAX_RECORDS:
        raise ValueError(f"records 数量超出上限 ({_MAX_RECORDS})，收到: {len(records)}")
    if len(records) == 0:
        raise ValueError("records 数组不能为空")

    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            raise ValueError(f"records[{i}] 必须为对象")
        rec_type = rec.get("type")
        if not isinstance(rec_type, str) or rec_type not in _VALID_RECORD_TYPES:
            raise ValueError(f"records[{i}].type 无效: {rec_type}，支持: {', '.join(sorted(_VALID_RECORD_TYPES))}")
        data = rec.get("data")
        if not isinstance(data, dict):
            raise ValueError(f"records[{i}].data 必须为对象")
        # Check string field lengths
        for key, val in data.items():
            if isinstance(val, str) and len(val) > _MAX_STRING_LEN:
                raise ValueError(f"records[{i}].data.{key} 长度超出上限 ({_MAX_STRING_LEN})，实际: {len(val)}")

    return records
