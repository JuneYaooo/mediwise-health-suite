"""Apple Health export.xml provider for wearable-sync.

Supports both .xml and .zip (containing export.xml) formats.
Uses iterparse for memory-efficient streaming of large files.

## Implementation References

### Apple HealthKit Official Documentation
- HKQuantityTypeIdentifier enumeration (all supported type strings):
  https://developer.apple.com/documentation/healthkit/hkquantitytypeidentifier
- HKCategoryTypeIdentifier (sleep, mindfulness, etc.):
  https://developer.apple.com/documentation/healthkit/hkcategorytypeidentifier
- HKCategoryValueSleepAnalysis (int values 0-5 mapped to sleep stages):
  https://developer.apple.com/documentation/healthkit/hkcategoryvaluesleepanalysis
  Values used in SLEEP_VALUE_MAP:
    0 = inBed (awake)  1 = asleepUnspecified (awake)  2 = awake
    3 = asleepCore / light_sleep  4 = asleepDeep / deep_sleep  5 = asleepREM / rem_sleep
  Note: values 0-2 were the original API; 3-5 added in iOS 16 (WWDC 2022 session 10005).
- HealthKit export XML format (Record element attributes: type, startDate, value, unit):
  https://developer.apple.com/documentation/healthkit/data_types

### Unit Conversions
- Blood glucose mg/dL → mmol/L: divide by 18.0182
  Reference: WHO / SI unit standard; 18.0182 is the molar mass of glucose (g/mol)
  See also: https://www.diabetes.co.uk/blood-sugar-converter.html
- Body height metres → cm: multiply by 100 (SI)
- Body mass lbs → kg: multiply by 0.453592 (1 lb = 0.453592 kg, NIST)
- Blood oxygen / body fat stored as fraction 0-1 on older iOS versions → multiply by 100

### Blood Pressure Pairing (60-second window)
- Apple Health stores HKQuantityTypeIdentifierBloodPressureSystolic and
  HKQuantityTypeIdentifierBloodPressureDiastolic as separate Record entries.
- The 60-second co-occurrence window follows the HealthKit Correlation model:
  https://developer.apple.com/documentation/healthkit/hkcorrelation
  (BloodPressure correlation groups systolic + diastolic taken at the same moment.)

### Memory-Efficient XML Parsing
- xml.etree.ElementTree.iterparse with elem.clear() pattern:
  https://docs.python.org/3/library/xml.etree.elementtree.html#xml.etree.ElementTree.iterparse
  Recommended for Apple Health exports which can exceed 1 GB.

### Step Count Aggregation
- HKQuantityTypeIdentifierStepCount records are per-interval samples (not cumulative).
  Daily totals are obtained by summing all samples within a calendar day.
  Reference: Apple Developer Forums QA1952 and HealthKit best practices guide.
"""

from __future__ import annotations

import json
import os
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from typing import Optional

from providers.base import BaseProvider, RawMetric

# HKQuantity/Category type → normalized metric_type
APPLE_TYPE_MAP = {
    "HKQuantityTypeIdentifierHeartRate":          "heart_rate",
    "HKQuantityTypeIdentifierRestingHeartRate":   "heart_rate",
    "HKQuantityTypeIdentifierStepCount":          "steps_raw",
    "HKQuantityTypeIdentifierBloodOxygen":        "blood_oxygen",
    "HKCategoryTypeIdentifierSleepAnalysis":      "sleep_raw",
    "HKQuantityTypeIdentifierBodyMass":           "weight",
    "HKQuantityTypeIdentifierHeight":             "height",
    "HKQuantityTypeIdentifierBloodGlucose":       "blood_sugar",
    "HKQuantityTypeIdentifierBloodPressureSystolic":   "bp_systolic_raw",
    "HKQuantityTypeIdentifierBloodPressureDiastolic":  "bp_diastolic_raw",
    "HKQuantityTypeIdentifierBodyFatPercentage":  "body_fat",
    "HKQuantityTypeIdentifierActiveEnergyBurned": "calories",
}

# Sleep value int → stage string
SLEEP_VALUE_MAP = {
    0: "awake",
    1: "awake",
    2: "awake",
    3: "light_sleep",
    4: "deep_sleep",
    5: "rem_sleep",
}


def _parse_apple_timestamp(ts: str) -> str:
    """Parse Apple Health timestamp '2024-01-15 08:30:00 +0800' → 'YYYY-MM-DD HH:MM:SS'."""
    return ts[:19] if ts else ts


def _convert_value(metric_type: str, value_str: str, unit: str) -> Optional[str]:
    """Apply unit conversions for Apple Health quirks."""
    try:
        val = float(value_str)
    except (ValueError, TypeError):
        return None

    if metric_type == "blood_sugar":
        # mg/dL → mmol/L
        if unit and "mg" in unit.lower():
            val = round(val / 18.0182, 3)

    elif metric_type in ("blood_oxygen", "body_fat"):
        # Old iOS records may store as fraction 0-1
        if val <= 1.0:
            val = round(val * 100, 1)

    elif metric_type == "height":
        # metres → cm
        if (unit and unit.lower() in ("m", "meter", "metre")) or val < 3.0:
            val = round(val * 100, 1)

    elif metric_type == "weight":
        # lbs → kg
        if unit and "lb" in unit.lower():
            val = round(val * 0.453592, 3)

    return str(val)


class AppleHealthProvider(BaseProvider):
    """Provider for Apple Health export.xml / export.zip files."""

    provider_name = "apple_health"

    def authenticate(self, config: dict) -> bool:
        """Validate that the export file exists (xml or zip)."""
        path = config.get("export_path", "")
        if not path:
            return False
        if not os.path.exists(path):
            return False
        ext = os.path.splitext(path)[1].lower()
        if ext == ".zip":
            # Verify there's an XML inside
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    return any(n.endswith(".xml") for n in zf.namelist())
            except (zipfile.BadZipFile, OSError):
                return False
        return ext == ".xml"

    def test_connection(self, config: dict) -> bool:
        return self.authenticate(config)

    def get_supported_metrics(self) -> list[str]:
        return [
            "heart_rate", "steps", "blood_oxygen", "sleep",
            "weight", "height", "blood_sugar", "blood_pressure",
            "body_fat", "calories",
        ]

    def fetch_metrics(
        self,
        device_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> list[RawMetric]:
        """Stream-parse the Apple Health export file and return RawMetric list."""
        # Load config from device record
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "mediwise-health-tracker", "scripts"))
        import health_db

        conn = health_db.get_lifestyle_connection()
        try:
            row = conn.execute(
                "SELECT config FROM wearable_devices WHERE id=? AND is_deleted=0", (device_id,)
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return []

        try:
            config = json.loads(row["config"] or "{}")
        except (json.JSONDecodeError, TypeError):
            config = {}

        xml_path = self._resolve_xml_path(config.get("export_path", ""))
        if not xml_path:
            return []

        return self._parse_xml(xml_path, start_time, end_time)

    def _resolve_xml_path(self, export_path: str) -> Optional[str]:
        """Resolve .xml or extract .zip to get the XML path."""
        if not export_path or not os.path.exists(export_path):
            return None

        ext = os.path.splitext(export_path)[1].lower()
        if ext == ".xml":
            return export_path

        if ext == ".zip":
            try:
                zf = zipfile.ZipFile(export_path, "r")
                xml_names = [n for n in zf.namelist() if n.endswith(".xml")]
                if not xml_names:
                    zf.close()
                    return None
                xml_name = xml_names[0]
                tmp_dir = tempfile.mkdtemp(prefix="apple_health_")
                extracted = zf.extract(xml_name, tmp_dir)
                zf.close()
                return extracted
            except (zipfile.BadZipFile, OSError):
                return None

        return None

    def _parse_xml(
        self, xml_path: str, start_time: Optional[str], end_time: Optional[str]
    ) -> list[RawMetric]:
        """Stream-parse export.xml using iterparse for memory efficiency."""
        metrics = []

        start_dt = datetime.strptime(start_time[:19], "%Y-%m-%d %H:%M:%S") if start_time else None
        end_dt = datetime.strptime(end_time[:19], "%Y-%m-%d %H:%M:%S") if end_time else None

        try:
            context = ET.iterparse(xml_path, events=("start",))
            for event, elem in context:
                if elem.tag != "Record":
                    elem.clear()
                    continue

                hk_type = elem.get("type", "")
                metric_type = APPLE_TYPE_MAP.get(hk_type)
                if metric_type is None:
                    elem.clear()
                    continue

                raw_ts = elem.get("startDate", "") or elem.get("creationDate", "")
                ts = _parse_apple_timestamp(raw_ts)
                if not ts:
                    elem.clear()
                    continue

                # Time filter
                if start_dt or end_dt:
                    try:
                        record_dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
                        if start_dt and record_dt < start_dt:
                            elem.clear()
                            continue
                        if end_dt and record_dt > end_dt:
                            elem.clear()
                            continue
                    except ValueError:
                        pass

                value_str = elem.get("value", "")
                unit = elem.get("unit", "")

                if metric_type == "sleep_raw":
                    # Category value is an int → stage string
                    try:
                        stage = SLEEP_VALUE_MAP.get(int(value_str), "light_sleep")
                    except (ValueError, TypeError):
                        stage = "light_sleep"
                    value_str = stage
                else:
                    converted = _convert_value(metric_type, value_str, unit)
                    if converted is None:
                        elem.clear()
                        continue
                    value_str = converted

                metrics.append(RawMetric(
                    metric_type=metric_type,
                    value=value_str,
                    timestamp=ts,
                    extra={"unit": unit, "hk_type": hk_type},
                ))
                elem.clear()

        except ET.ParseError:
            pass

        return metrics
