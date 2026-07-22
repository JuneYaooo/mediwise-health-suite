from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mediwise-health-tracker" / "scripts"))

import doctor_visit_report


class ReportRenderingTests(unittest.TestCase):
    def test_pdf_uses_cross_platform_chrome_lookup(self):
        with tempfile.TemporaryDirectory() as tempdir:
            html = Path(tempdir) / "report.html"
            pdf = Path(tempdir) / "report.pdf"
            html.write_text("<html><body>test</body></html>", encoding="utf-8")

            def fake_run(command, **kwargs):
                self.assertEqual(command[0], "/Applications/Google Chrome")
                self.assertTrue(command[-1].startswith("file:"))
                pdf.write_bytes(b"%PDF-test")
                return type("Result", (), {"returncode": 0, "stderr": ""})()

            with patch("html_screenshot.find_chrome", return_value="/Applications/Google Chrome"), \
                    patch("doctor_visit_report.subprocess.run", side_effect=fake_run):
                result = doctor_visit_report.generate_pdf(str(html), str(pdf))

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["pdf_path"], str(pdf))


if __name__ == "__main__":
    unittest.main()
