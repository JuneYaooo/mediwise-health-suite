from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "wearable-sync" / "scripts"))

from normalize import normalize_metrics
from providers.apple_health import AppleHealthProvider, _map_sleep_value


class AppleHealthProviderTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.provider = AppleHealthProvider()

    def tearDown(self):
        self.tempdir.cleanup()

    def _write_export(self, records: str, name: str = "export.xml") -> Path:
        path = self.root / name
        path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<HealthData locale="en_US">{records}</HealthData>',
            encoding="utf-8",
        )
        return path

    def test_named_and_numeric_sleep_values(self):
        self.assertEqual(_map_sleep_value("HKCategoryValueSleepAnalysisAwake"), "awake")
        self.assertEqual(_map_sleep_value("HKCategoryValueSleepAnalysisAsleepCore"), "light_sleep")
        self.assertEqual(_map_sleep_value("HKCategoryValueSleepAnalysisAsleepDeep"), "deep_sleep")
        self.assertEqual(_map_sleep_value("HKCategoryValueSleepAnalysisAsleepREM"), "rem_sleep")
        self.assertEqual(_map_sleep_value("1"), "light_sleep")

    def test_sleep_uses_exact_intervals_and_avoids_in_bed_double_count(self):
        def record(value, start, end):
            return (
                '<Record type="HKCategoryTypeIdentifierSleepAnalysis" '
                f'value="{value}" startDate="{start} +0800" endDate="{end} +0800"/>'
            )

        export = self._write_export("".join([
            record("HKCategoryValueSleepAnalysisInBed", "2026-07-21 22:00:00", "2026-07-22 07:00:00"),
            record("HKCategoryValueSleepAnalysisAsleepCore", "2026-07-21 22:30:00", "2026-07-22 00:30:00"),
            record("HKCategoryValueSleepAnalysisAsleepDeep", "2026-07-22 00:30:00", "2026-07-22 01:30:00"),
            record("HKCategoryValueSleepAnalysisAsleepREM", "2026-07-22 01:30:00", "2026-07-22 02:00:00"),
            record("HKCategoryValueSleepAnalysisAsleepCore", "2026-07-22 02:00:00", "2026-07-22 06:30:00"),
            record("HKCategoryValueSleepAnalysisAwake", "2026-07-22 06:30:00", "2026-07-22 07:00:00"),
        ]))
        self.assertTrue(self.provider.authenticate({"export_path": str(export)}))
        raw = self.provider._parse_xml(str(export), None, None)
        normalized = normalize_metrics(raw, "apple_health")
        self.assertEqual(len(normalized), 1)
        value = json.loads(normalized[0]["value"])
        self.assertEqual(value, {
            "duration_min": 540,
            "deep_min": 60,
            "light_min": 390,
            "rem_min": 30,
            "awake_min": 60,
        })

    def test_zip_requires_and_prefers_canonical_export_xml(self):
        export = self._write_export(
            '<Record type="HKQuantityTypeIdentifierHeartRate" value="70" unit="count/min" '
            'startDate="2026-07-22 08:00:00 +0800" endDate="2026-07-22 08:00:00 +0800"/>'
        )
        archive_path = self.root / "export.zip"
        with zipfile.ZipFile(archive_path, "w") as archive:
            archive.writestr("other.xml", "<not-health/>")
            archive.write(export, "apple_health_export/export.xml")
        self.assertTrue(self.provider.test_connection({"export_path": str(archive_path)}))
        with self.provider._open_export_xml(str(archive_path)) as source:
            metrics = self.provider._parse_xml(source, None, None)
        self.assertEqual(metrics[0].metric_type, "heart_rate")

        wrong_archive = self.root / "wrong.zip"
        with zipfile.ZipFile(wrong_archive, "w") as archive:
            archive.writestr("other.xml", "<HealthData/>")
        self.assertFalse(self.provider.test_connection({"export_path": str(wrong_archive)}))

    def test_corrupt_or_non_health_xml_is_rejected(self):
        corrupt = self.root / "corrupt.xml"
        corrupt.write_text("<HealthData><Record", encoding="utf-8")
        other = self.root / "other.xml"
        other.write_text("<root/>", encoding="utf-8")
        self.assertFalse(self.provider.test_connection({"export_path": str(corrupt)}))
        self.assertFalse(self.provider.test_connection({"export_path": str(other)}))
        with self.assertRaisesRegex(ValueError, "损坏"):
            self.provider._parse_xml(str(corrupt), None, None)


if __name__ == "__main__":
    unittest.main()
