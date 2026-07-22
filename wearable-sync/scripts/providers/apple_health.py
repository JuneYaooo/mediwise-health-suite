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
import xml.etree.ElementTree as ET
import zipfile
from contextlib import contextmanager
from datetime import datetime
from typing import BinaryIO, Iterator, Optional, Union

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
    0: "in_bed",
    1: "light_sleep",
    2: "awake",
    3: "light_sleep",
    4: "deep_sleep",
    5: "rem_sleep",
}

SLEEP_STRING_VALUE_MAP = {
    "hkcategoryvaluesleepanalysisinbed": "in_bed",
    "hkcategoryvaluesleepanalysisasleep": "light_sleep",
    "hkcategoryvaluesleepanalysisasleepunspecified": "light_sleep",
    "hkcategoryvaluesleepanalysisawake": "awake",
    "hkcategoryvaluesleepanalysisasleepcore": "light_sleep",
    "hkcategoryvaluesleepanalysisasleepdeep": "deep_sleep",
    "hkcategoryvaluesleepanalysisasleeprem": "rem_sleep",
}


def _parse_apple_timestamp(ts: str) -> str:
    """Parse Apple Health timestamp '2024-01-15 08:30:00 +0800' → 'YYYY-MM-DD HH:MM:SS'."""
    return ts[:19] if ts else ts


def _map_sleep_value(value: str) -> str:
    """Map both legacy numeric and modern named HealthKit sleep values."""
    normalized = str(value or "").strip()
    try:
        return SLEEP_VALUE_MAP.get(int(normalized), "light_sleep")
    except (ValueError, TypeError):
        return SLEEP_STRING_VALUE_MAP.get(normalized.casefold(), "light_sleep")


def _local_name(tag: str) -> str:
    """Return an XML tag without an optional namespace."""
    return tag.rsplit("}", 1)[-1]


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
        """Validate that the file is a readable Apple Health export."""
        path = config.get("export_path", "")
        return self._validate_export(path, full=False)

    def test_connection(self, config: dict) -> bool:
        return self._validate_export(config.get("export_path", ""), full=True)

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

        export_path = config.get("export_path", "")
        if not export_path:
            return []
        with self._open_export_xml(export_path) as xml_source:
            return self._parse_xml(xml_source, start_time, end_time)

    @staticmethod
    def _select_export_xml(names: list[str]) -> Optional[str]:
        """Select the canonical export.xml instead of an arbitrary XML file."""
        candidates = [name for name in names if name.lower().endswith(".xml")]
        exact = [name for name in candidates if os.path.basename(name).lower() == "export.xml"]
        if exact:
            return sorted(exact, key=lambda name: (name.count("/"), len(name)))[0]
        return None

    @contextmanager
    def _open_export_xml(self, export_path: str) -> Iterator[Union[str, BinaryIO]]:
        """Yield the export XML path or a streaming member from an export ZIP."""
        ext = os.path.splitext(export_path)[1].lower()
        if ext == ".xml":
            yield export_path
            return
        if ext != ".zip":
            raise ValueError("Apple Health 导出文件必须是 export.xml 或 export.zip")

        try:
            with zipfile.ZipFile(export_path, "r") as archive:
                xml_name = self._select_export_xml(archive.namelist())
                if not xml_name:
                    raise ValueError("ZIP 中未找到 Apple Health export.xml")
                with archive.open(xml_name, "r") as stream:
                    yield stream
        except zipfile.BadZipFile as exc:
            raise ValueError("Apple Health ZIP 文件损坏或不可读") from exc

    def _validate_export(self, export_path: str, full: bool = False) -> bool:
        if not export_path or not os.path.isfile(export_path):
            return False
        if os.path.splitext(export_path)[1].lower() not in (".xml", ".zip"):
            return False
        try:
            with self._open_export_xml(export_path) as xml_source:
                context = ET.iterparse(xml_source, events=("start", "end"))
                event, root = next(context)
                if event != "start" or _local_name(root.tag) != "HealthData":
                    return False
                if full:
                    for event, element in context:
                        if event == "end":
                            element.clear()
                return True
        except (ET.ParseError, OSError, StopIteration, ValueError):
            return False

    def _parse_xml(
        self, xml_source: Union[str, BinaryIO], start_time: Optional[str], end_time: Optional[str]
    ) -> list[RawMetric]:
        """Stream-parse export.xml using iterparse for memory efficiency."""
        metrics = []

        start_dt = datetime.strptime(start_time[:19], "%Y-%m-%d %H:%M:%S") if start_time else None
        end_dt = datetime.strptime(end_time[:19], "%Y-%m-%d %H:%M:%S") if end_time else None

        try:
            context = ET.iterparse(xml_source, events=("start",))
            for event, elem in context:
                if _local_name(elem.tag) != "Record":
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
                    value_str = _map_sleep_value(value_str)
                else:
                    converted = _convert_value(metric_type, value_str, unit)
                    if converted is None:
                        elem.clear()
                        continue
                    value_str = converted

                extra = {"unit": unit, "hk_type": hk_type}
                if metric_type == "sleep_raw":
                    end_ts = _parse_apple_timestamp(elem.get("endDate", ""))
                    if end_ts:
                        extra["end_timestamp"] = end_ts
                        try:
                            start_value = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
                            end_value = datetime.strptime(end_ts, "%Y-%m-%d %H:%M:%S")
                            duration = (end_value - start_value).total_seconds() / 60
                            if duration > 0:
                                extra["duration_min"] = duration
                        except ValueError:
                            pass

                metrics.append(RawMetric(
                    metric_type=metric_type,
                    value=value_str,
                    timestamp=ts,
                    extra=extra,
                ))
                elem.clear()

        except ET.ParseError as exc:
            raise ValueError("Apple Health export.xml 损坏或格式不完整") from exc

        return metrics
