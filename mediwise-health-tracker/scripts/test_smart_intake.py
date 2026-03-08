"""Tests for smart_intake module — no real LLM calls needed."""

import argparse
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import smart_intake
import config


class TestExtractJsonFromText(unittest.TestCase):
    """Test JSON extraction from LLM response text."""

    def test_plain_json(self):
        text = '{"records": [], "source_summary": "test"}'
        result = smart_intake._extract_json_from_text(text)
        self.assertEqual(result["source_summary"], "test")

    def test_markdown_fenced_json(self):
        text = '```json\n{"records": [{"type": "visit"}], "source_summary": "x"}\n```'
        result = smart_intake._extract_json_from_text(text)
        self.assertEqual(len(result["records"]), 1)

    def test_json_with_surrounding_text(self):
        text = 'Here is the result:\n{"records": [], "source_summary": "ok"}\nDone.'
        result = smart_intake._extract_json_from_text(text)
        self.assertEqual(result["source_summary"], "ok")

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            smart_intake._extract_json_from_text("no json here")

    def test_incomplete_json_raises(self):
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            smart_intake._extract_json_from_text('{"records": [')


class TestNormalizeHealthMetric(unittest.TestCase):
    """Test blood pressure normalization."""

    def test_bp_string_format(self):
        data = {"metric_type": "blood_pressure", "value": "130/85"}
        smart_intake._normalize_health_metric(data)
        parsed = json.loads(data["value"])
        self.assertEqual(parsed["systolic"], 130)
        self.assertEqual(parsed["diastolic"], 85)

    def test_bp_dict_format(self):
        data = {"metric_type": "blood_pressure", "value": {"systolic": 120, "diastolic": 80}}
        smart_intake._normalize_health_metric(data)
        parsed = json.loads(data["value"])
        self.assertEqual(parsed["systolic"], 120)

    def test_non_bp_unchanged(self):
        data = {"metric_type": "heart_rate", "value": "72"}
        smart_intake._normalize_health_metric(data)
        self.assertEqual(data["value"], "72")


class TestPreprocess(unittest.TestCase):
    """Test preprocessing for different input types."""

    def test_text_passthrough(self):
        result = smart_intake.preprocess("text", "血压130/85")
        self.assertEqual(result, "血压130/85")

    def test_invalid_type_raises(self):
        with self.assertRaises(ValueError):
            smart_intake.preprocess("video", "something")

    def test_pdf_no_library(self):
        """PDF extraction should raise if no library available and file doesn't exist."""
        with self.assertRaises(Exception):
            smart_intake.preprocess("pdf", "/nonexistent/file.pdf")

    def test_image_no_vision_config(self):
        """Image extraction should raise if file doesn't exist."""
        with self.assertRaises(FileNotFoundError):
            smart_intake.preprocess("image", "/nonexistent/image.jpg")


class TestExtractWithMockedLLM(unittest.TestCase):
    """Test extract() with mocked LLM calls."""

    @patch("smart_intake._call_llm_with_continuation")
    @patch("smart_intake.get_llm_config")
    @patch("smart_intake.get_vision_config")
    def test_text_extract_visit_medication_metric(self, mock_vision_cfg, mock_llm_cfg, mock_call_llm):
        mock_vision_cfg.return_value = {"provider": "test", "model": "test", "api_key": "test", "base_url": "http://test"}
        mock_llm_cfg.return_value = {"provider": "test", "model": "test", "api_key": "test", "base_url": "http://test"}

        mock_call_llm.return_value = json.dumps({
            "records": [
                {
                    "type": "visit",
                    "confidence": 0.9,
                    "data": {
                        "visit_type": "门诊",
                        "visit_date": "2025-02-25",
                        "hospital": "协和医院",
                        "department": None,
                        "chief_complaint": "感冒",
                        "diagnosis": "感冒",
                        "summary": None,
                    }
                },
                {
                    "type": "medication",
                    "confidence": 0.95,
                    "data": {
                        "name": "阿莫西林",
                        "dosage": "0.5g",
                        "frequency": "每日三次",
                        "start_date": "2025-02-25",
                        "purpose": None,
                    }
                },
                {
                    "type": "health_metric",
                    "confidence": 0.9,
                    "data": {
                        "metric_type": "blood_pressure",
                        "value": "130/85",
                        "unit": "mmHg",
                        "measured_at": "2025-02-25",
                        "notes": None,
                    }
                },
            ],
            "source_summary": "协和医院门诊感冒就诊记录，含用药和血压数据"
        })

        result = smart_intake.extract("text", "今天去协和医院看了感冒，开了阿莫西林0.5g每日三次，血压130/85", "test-member")

        self.assertEqual(len(result["records"]), 3)
        types_found = [r["type"] for r in result["records"]]
        self.assertIn("visit", types_found)
        self.assertIn("medication", types_found)
        self.assertIn("health_metric", types_found)

        # Check BP was normalized
        bp_rec = [r for r in result["records"] if r["type"] == "health_metric"][0]
        bp_value = json.loads(bp_rec["data"]["value"])
        self.assertEqual(bp_value["systolic"], 130)
        self.assertEqual(bp_value["diastolic"], 85)

    @patch("smart_intake._call_llm_with_continuation")
    @patch("smart_intake.get_llm_config")
    @patch("smart_intake.get_vision_config")
    def test_extract_empty_text(self, mock_vision_cfg, mock_llm_cfg, mock_call_llm):
        mock_vision_cfg.return_value = {"provider": "test", "model": "test", "api_key": "test"}
        mock_llm_cfg.return_value = {"provider": "test", "model": "test", "api_key": "test"}

        result = smart_intake.extract("text", "", "test-member")
        self.assertEqual(result["records"], [])
        mock_call_llm.assert_not_called()

    @patch("smart_intake._call_llm_with_continuation")
    @patch("smart_intake.get_llm_config")
    @patch("smart_intake.get_vision_config")
    def test_extract_bad_llm_response(self, mock_vision_cfg, mock_llm_cfg, mock_call_llm):
        mock_vision_cfg.return_value = {"provider": "test", "model": "test", "api_key": "test"}
        mock_llm_cfg.return_value = {"provider": "test", "model": "test", "api_key": "test"}
        mock_call_llm.return_value = "I don't understand the input"

        result = smart_intake.extract("text", "some text", "test-member")
        self.assertEqual(result["records"], [])
        self.assertIn("raw_response", result)


class TestConfirmWithMockedRecorders(unittest.TestCase):
    """Test confirm() with mocked add_* functions."""

    @patch("smart_intake._check_duplicate", return_value=False)
    @patch("medical_record.add_visit")
    @patch("medical_record.add_medication")
    @patch("health_metric.add_metric")
    def test_confirm_multiple_records(self, mock_add_metric, mock_add_med, mock_add_visit, mock_dedup):
        records = [
            {"type": "visit", "confidence": 0.9, "data": {
                "visit_type": "门诊", "visit_date": "2025-02-25",
                "hospital": "协和医院", "chief_complaint": "感冒",
                "diagnosis": "感冒",
            }},
            {"type": "medication", "confidence": 0.95, "data": {
                "name": "阿莫西林", "dosage": "0.5g", "frequency": "每日三次",
                "start_date": "2025-02-25",
            }},
            {"type": "health_metric", "confidence": 0.9, "data": {
                "metric_type": "blood_pressure",
                "value": '{"systolic": 130, "diastolic": 85}',
                "measured_at": "2025-02-25",
            }},
        ]

        result = smart_intake.confirm("test-member", records)

        self.assertEqual(result["total"], 3)
        self.assertEqual(result["success"], 3)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["status"], "ok")

        mock_add_visit.assert_called_once()
        mock_add_med.assert_called_once()
        mock_add_metric.assert_called_once()

        # Verify visit args
        visit_args = mock_add_visit.call_args[0][0]
        self.assertEqual(visit_args.member_id, "test-member")
        self.assertEqual(visit_args.visit_type, "门诊")
        self.assertEqual(visit_args.hospital, "协和医院")

    @patch("smart_intake._check_duplicate", return_value=False)
    @patch("medical_record.add_lab_result")
    def test_confirm_lab_result(self, mock_add_lab, mock_dedup):
        records = [
            {"type": "lab_result", "confidence": 0.95, "data": {
                "test_name": "血常规", "test_date": "2025-02-25",
                "items": [
                    {"name": "白细胞", "value": "5.2", "unit": "10^9/L", "reference": "3.5-9.5", "is_abnormal": False},
                    {"name": "红细胞", "value": "4.5", "unit": "10^12/L", "reference": "3.8-5.1", "is_abnormal": False},
                ],
            }},
        ]

        result = smart_intake.confirm("test-member", records)
        self.assertEqual(result["success"], 1)

        lab_args = mock_add_lab.call_args[0][0]
        items = json.loads(lab_args.items)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["name"], "白细胞")

    @patch("smart_intake._check_duplicate", return_value=False)
    @patch("medical_record.add_imaging")
    def test_confirm_imaging(self, mock_add_imaging, mock_dedup):
        records = [
            {"type": "imaging", "confidence": 0.9, "data": {
                "exam_name": "胸部CT", "exam_date": "2025-02-25",
                "findings": "双肺纹理清晰", "conclusion": "未见明显异常",
            }},
        ]

        result = smart_intake.confirm("test-member", records)
        self.assertEqual(result["success"], 1)

        img_args = mock_add_imaging.call_args[0][0]
        self.assertEqual(img_args.exam_name, "胸部CT")
        self.assertEqual(img_args.findings, "双肺纹理清晰")

    @patch("smart_intake._check_duplicate", return_value=False)
    def test_confirm_unknown_type(self, mock_dedup):
        records = [{"type": "unknown_thing", "data": {}}]
        result = smart_intake.confirm("test-member", records)
        self.assertEqual(result["failed"], 1)
        self.assertIn("无效", result["details"][0]["message"])

    @patch("smart_intake._check_duplicate", return_value=False)
    @patch("medical_record.add_visit", side_effect=Exception("DB error"))
    def test_confirm_handles_exception(self, mock_add_visit, mock_dedup):
        records = [{"type": "visit", "data": {"visit_type": "门诊", "visit_date": "2025-02-25"}}]
        result = smart_intake.confirm("test-member", records)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["status"], "error")
        self.assertIn("DB error", result["details"][0]["message"])

    @patch("smart_intake._check_duplicate", return_value=False)
    @patch("medical_record.add_visit")
    @patch("medical_record.add_symptom", side_effect=Exception("fail"))
    def test_confirm_partial_success(self, mock_symptom, mock_visit, mock_dedup):
        records = [
            {"type": "visit", "data": {"visit_type": "门诊", "visit_date": "2025-02-25"}},
            {"type": "symptom", "data": {"symptom": "头痛"}},
        ]
        result = smart_intake.confirm("test-member", records)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["success"], 1)
        self.assertEqual(result["failed"], 1)


class TestConfigLLM(unittest.TestCase):
    """Test LLM config fallback logic."""

    @patch("config.load_config")
    def test_llm_config_returns_llm_when_set(self, mock_load):
        mock_load.return_value = {
            "llm": {"provider": "openai", "model": "gpt-4", "api_key": "sk-test", "base_url": ""},
            "vision": {"provider": "siliconflow", "model": "qwen-vl", "api_key": "sk-vis", "base_url": ""},
        }
        cfg = config.get_llm_config()
        self.assertEqual(cfg["provider"], "openai")
        self.assertEqual(cfg["model"], "gpt-4")

    @patch("config.load_config")
    def test_llm_config_falls_back_to_vision(self, mock_load):
        mock_load.return_value = {
            "llm": {"provider": "", "model": "", "api_key": "", "base_url": ""},
            "vision": {"provider": "siliconflow", "model": "qwen-vl", "api_key": "sk-vis", "base_url": "http://test"},
        }
        cfg = config.get_llm_config()
        self.assertEqual(cfg["provider"], "siliconflow")
        self.assertEqual(cfg["model"], "qwen-vl")


class TestMakeNamespace(unittest.TestCase):
    """Test _make_namespace helper."""

    def test_creates_namespace(self):
        ns = smart_intake._make_namespace(member_id="abc", name="test", dosage=None)
        self.assertEqual(ns.member_id, "abc")
        self.assertEqual(ns.name, "test")
        self.assertIsNone(ns.dosage)


class TestImageToBase64(unittest.TestCase):
    """Test image file reading."""

    def test_nonexistent_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            smart_intake._image_to_base64("/nonexistent/image.jpg")


class TestBuildPayloads(unittest.TestCase):
    """Test LLM payload builders."""

    def test_openai_payload(self):
        messages = [{"role": "user", "content": "hello"}]
        payload = json.loads(smart_intake._build_openai_payload(messages, "gpt-4"))
        self.assertEqual(payload["model"], "gpt-4")
        self.assertEqual(payload["messages"][0]["content"], "hello")
        self.assertEqual(payload["response_format"]["type"], "json_object")
        self.assertEqual(payload["max_tokens"], 16384)

    def test_anthropic_payload_extracts_system(self):
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hello"},
        ]
        payload = json.loads(smart_intake._build_anthropic_payload(messages, "claude-3"))
        self.assertEqual(payload["system"], "You are helpful")
        self.assertEqual(len(payload["messages"]), 1)
        self.assertEqual(payload["messages"][0]["role"], "user")

    def test_parse_openai_response(self):
        body = {"choices": [{"message": {"content": "result"}, "finish_reason": "stop"}]}
        text, truncated = smart_intake._parse_openai_response(body)
        self.assertEqual(text, "result")
        self.assertFalse(truncated)

    def test_parse_anthropic_response(self):
        body = {"content": [{"type": "text", "text": "result"}], "stop_reason": "end_turn"}
        text, truncated = smart_intake._parse_anthropic_response(body)
        self.assertEqual(text, "result")
        self.assertFalse(truncated)

    def test_parse_empty_responses(self):
        self.assertEqual(smart_intake._parse_openai_response({}), ("", False))
        self.assertEqual(smart_intake._parse_anthropic_response({}), ("", False))


class TestContinuation(unittest.TestCase):
    """Fix 1: Test LLM continuation on truncation."""

    @patch("smart_intake._call_llm")
    def test_no_truncation_returns_directly(self, mock_call):
        mock_call.return_value = ("complete response", False)
        result = smart_intake._call_llm_with_continuation(
            [{"role": "user", "content": "test"}],
            {"provider": "openai", "model": "gpt-4", "api_key": "k", "base_url": ""}
        )
        self.assertEqual(result, "complete response")
        self.assertEqual(mock_call.call_count, 1)

    @patch("smart_intake._call_llm")
    def test_truncation_triggers_continuation(self, mock_call):
        mock_call.side_effect = [
            ("partial output...", True),
            ("...continued output", False),
        ]
        result = smart_intake._call_llm_with_continuation(
            [{"role": "user", "content": "test"}],
            {"provider": "openai", "model": "gpt-4", "api_key": "k", "base_url": ""}
        )
        self.assertEqual(result, "partial output......continued output")
        self.assertEqual(mock_call.call_count, 2)

    @patch("smart_intake._call_llm")
    def test_truncation_max_attempts(self, mock_call):
        mock_call.side_effect = [
            ("part1", True),
            ("part2", True),
            ("part3", True),
        ]
        result = smart_intake._call_llm_with_continuation(
            [{"role": "user", "content": "test"}],
            {"provider": "openai", "model": "gpt-4", "api_key": "k", "base_url": ""},
            max_attempts=3
        )
        self.assertEqual(result, "part1part2part3")
        self.assertEqual(mock_call.call_count, 3)

    @patch("smart_intake._call_llm")
    @patch("smart_intake._call_vision_llm")
    def test_vision_continuation_falls_back_to_text(self, mock_vision, mock_text):
        mock_vision.return_value = ("partial vision", True)
        mock_text.return_value = ("...rest of text", False)
        result = smart_intake._call_vision_llm_with_continuation(
            "prompt", "base64img", "image/png",
            {"provider": "openai", "model": "gpt-4o", "api_key": "k", "base_url": ""},
            {"provider": "openai", "model": "gpt-4", "api_key": "k", "base_url": ""},
        )
        self.assertEqual(result, "partial vision...rest of text")
        mock_vision.assert_called_once()
        mock_text.assert_called_once()


class TestParseResponseTruncation(unittest.TestCase):
    """Fix 1: Test truncation detection in parse functions."""

    def test_anthropic_truncated(self):
        body = {"content": [{"type": "text", "text": "partial"}], "stop_reason": "max_tokens"}
        text, truncated = smart_intake._parse_anthropic_response(body)
        self.assertEqual(text, "partial")
        self.assertTrue(truncated)

    def test_openai_truncated(self):
        body = {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}
        text, truncated = smart_intake._parse_openai_response(body)
        self.assertEqual(text, "partial")
        self.assertTrue(truncated)

    def test_anthropic_not_truncated(self):
        body = {"content": [{"type": "text", "text": "full"}], "stop_reason": "end_turn"}
        _, truncated = smart_intake._parse_anthropic_response(body)
        self.assertFalse(truncated)

    def test_openai_not_truncated(self):
        body = {"choices": [{"message": {"content": "full"}, "finish_reason": "stop"}]}
        _, truncated = smart_intake._parse_openai_response(body)
        self.assertFalse(truncated)


class TestPdfVisionFallback(unittest.TestCase):
    """Fix 2: Test PDF vision OCR fallback for scanned PDFs."""

    @patch("smart_intake._extract_text_with_paddleocr", return_value=None)
    @patch("smart_intake._extract_text_with_mineru", return_value=None)
    @patch("smart_intake.get_pdf_config", return_value={"ocr_engine": "auto"})
    @patch("smart_intake._call_vision_llm")
    @patch("smart_intake._pdf_pages_to_images")
    def test_short_text_triggers_vision_fallback(self, mock_pages, mock_vision,
                                                  mock_pdf_cfg, mock_mineru, mock_paddle):
        """When pdfplumber extracts < 50 chars, fall back to vision OCR."""
        mock_pages.return_value = [b"fake_png_bytes"]
        mock_vision.return_value = ("完整的OCR提取文本，包含很多内容", False)

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake")
            tmp_path = f.name

        try:
            with patch("smart_intake.get_vision_config", return_value={
                "provider": "test", "model": "test", "api_key": "test", "base_url": "",
                "enabled": True,
            }):
                # Mock pdfplumber to return short text
                mock_pdfplumber = MagicMock()
                mock_page = MagicMock()
                mock_page.extract_text.return_value = "短"
                mock_page.extract_tables.return_value = []
                mock_pdfplumber.open.return_value.__enter__ = lambda s: MagicMock(pages=[mock_page])
                mock_pdfplumber.open.return_value.__exit__ = MagicMock(return_value=False)

                with patch.dict("sys.modules", {"pdfplumber": mock_pdfplumber}):
                    result = smart_intake._extract_text_from_pdf(tmp_path)
                    self.assertIn("OCR", result)
        finally:
            os.unlink(tmp_path)

    @patch("smart_intake._extract_text_with_paddleocr", return_value=None)
    @patch("smart_intake._extract_text_with_mineru", return_value=None)
    @patch("smart_intake.get_pdf_config", return_value={"ocr_engine": "auto"})
    @patch("smart_intake._call_vision_llm")
    @patch("smart_intake._pdf_pages_to_images")
    def test_no_libraries_uses_vision(self, mock_pages, mock_vision,
                                       mock_pdf_cfg, mock_mineru, mock_paddle):
        """When no PDF library is available, use vision fallback."""
        mock_pages.return_value = [b"fake_png"]
        mock_vision.return_value = ("OCR结果文本内容足够长度超过五十个字符的测试数据", False)

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 fake")
            tmp_path = f.name

        try:
            with patch("smart_intake.get_vision_config", return_value={
                "provider": "test", "model": "test", "api_key": "test", "base_url": "",
                "enabled": True,
            }):
                # Remove both PDF libraries
                with patch.dict("sys.modules", {"pdfplumber": None, "PyPDF2": None}):
                    result = smart_intake._extract_text_from_pdf(tmp_path)
                    self.assertIn("OCR", result)
        finally:
            os.unlink(tmp_path)


class TestImageSingleVisionCall(unittest.TestCase):
    """Fix 3: Test that image extract uses a single vision call."""

    @patch("smart_intake._call_vision_llm_with_continuation")
    @patch("smart_intake._image_to_base64")
    @patch("smart_intake.get_llm_config")
    @patch("smart_intake.get_vision_config")
    def test_image_extract_single_call(self, mock_vision_cfg, mock_llm_cfg, mock_img_b64, mock_vision_call):
        mock_vision_cfg.return_value = {"provider": "test", "model": "test", "api_key": "test", "base_url": ""}
        mock_llm_cfg.return_value = {"provider": "test", "model": "test", "api_key": "test", "base_url": ""}
        mock_img_b64.return_value = ("base64data", "image/jpeg")
        mock_vision_call.return_value = json.dumps({
            "records": [{"type": "visit", "confidence": 0.9, "data": {
                "visit_type": "门诊", "visit_date": "2025-02-25",
                "hospital": "协和医院", "chief_complaint": "感冒", "diagnosis": "感冒",
            }}],
            "source_summary": "门诊记录"
        })

        result = smart_intake.extract("image", "/fake/image.jpg", "test-member")

        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["type"], "visit")
        mock_vision_call.assert_called_once()
        # preprocess should NOT have been called for image
        mock_img_b64.assert_called_once_with("/fake/image.jpg")


class TestCallAndCapture(unittest.TestCase):
    """Fix 4: Test stdout capture from add_* functions."""

    def test_capture_success_json(self):
        def fake_add(args):
            print(json.dumps({"status": "ok", "id": "123"}))
        result = smart_intake._call_and_capture(fake_add, None)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["id"], "123")

    def test_capture_error_json(self):
        def fake_add(args):
            print(json.dumps({"status": "error", "message": "DB写入失败"}))
        result = smart_intake._call_and_capture(fake_add, None)
        self.assertEqual(result["status"], "error")
        self.assertIn("DB写入失败", result["message"])

    def test_capture_no_output(self):
        def fake_add(args):
            pass
        result = smart_intake._call_and_capture(fake_add, None)
        self.assertEqual(result["status"], "ok")

    def test_capture_invalid_json(self):
        def fake_add(args):
            print("not json at all")
        result = smart_intake._call_and_capture(fake_add, None)
        self.assertEqual(result["status"], "error")
        self.assertIn("输出解析失败", result["message"])

    @patch("smart_intake._check_duplicate", return_value=False)
    @patch("medical_record.add_visit")
    def test_confirm_detects_error_from_stdout(self, mock_add_visit, mock_dedup):
        """confirm() should report failure when add_visit prints error JSON."""
        def print_error(args):
            print(json.dumps({"status": "error", "message": "成员不存在"}))
        mock_add_visit.side_effect = print_error

        records = [{"type": "visit", "data": {
            "visit_type": "门诊", "visit_date": "2025-02-25",
        }}]
        result = smart_intake.confirm("test-member", records)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["details"][0]["status"], "error")
        self.assertIn("成员不存在", result["details"][0]["message"])


class TestDeduplication(unittest.TestCase):
    """Fix 5: Test duplicate detection."""

    @patch("health_db.is_api_mode", return_value=True)
    def test_api_mode_skips_dedup(self, mock_api):
        result = smart_intake._check_duplicate("visit", "m1", {"visit_date": "2025-01-01", "visit_type": "门诊"})
        self.assertFalse(result)

    @patch("health_db.is_api_mode", return_value=False)
    @patch("health_db.get_connection")
    def test_visit_duplicate_found(self, mock_conn, mock_api):
        mock_cursor = MagicMock()
        mock_cursor.execute.return_value.fetchone.return_value = (1,)
        mock_conn.return_value = mock_cursor
        # Make execute return the cursor itself for chaining
        mock_cursor.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)

        result = smart_intake._check_duplicate("visit", "m1", {
            "visit_date": "2025-01-01", "visit_type": "门诊"
        })
        self.assertTrue(result)

    @patch("health_db.is_api_mode", return_value=False)
    @patch("health_db.get_connection")
    def test_visit_no_duplicate(self, mock_conn, mock_api):
        mock_cursor = MagicMock()
        mock_cursor.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        mock_conn.return_value = mock_cursor

        result = smart_intake._check_duplicate("visit", "m1", {
            "visit_date": "2025-01-01", "visit_type": "门诊"
        })
        self.assertFalse(result)

    @patch("health_db.is_api_mode", return_value=False)
    @patch("health_db.get_connection")
    def test_medication_duplicate(self, mock_conn, mock_api):
        mock_cursor = MagicMock()
        mock_cursor.execute.return_value = mock_cursor
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.return_value = mock_cursor

        result = smart_intake._check_duplicate("medication", "m1", {
            "name": "阿莫西林", "dosage": "0.5g"
        })
        self.assertTrue(result)

    @patch("smart_intake._check_duplicate", return_value=True)
    @patch("medical_record.add_visit")
    def test_confirm_skips_duplicate(self, mock_add_visit, mock_dedup):
        records = [{"type": "visit", "data": {
            "visit_type": "门诊", "visit_date": "2025-02-25",
        }}]
        result = smart_intake.confirm("test-member", records)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["success"], 0)
        self.assertEqual(result["details"][0]["status"], "skipped")
        mock_add_visit.assert_not_called()

    @patch("health_db.is_api_mode", return_value=False)
    @patch("health_db.get_connection", side_effect=Exception("DB error"))
    def test_dedup_db_error_returns_false(self, mock_conn, mock_api):
        """If DB connection fails, dedup should return False (allow insert)."""
        result = smart_intake._check_duplicate("visit", "m1", {
            "visit_date": "2025-01-01", "visit_type": "门诊"
        })
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
