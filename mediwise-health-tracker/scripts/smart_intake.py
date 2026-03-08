"""Smart Intake — 智能录入模块。

从图片、PDF 或自由文本中自动提取结构化健康数据，确认后录入。

三阶段管线：
  输入 (image/PDF/text) → 预处理 → 分类+提取 → 结构化 JSON

Usage:
  python3 scripts/smart_intake.py extract --text "血压130/85" --member-id <id>
  python3 scripts/smart_intake.py extract --image report.jpg --member-id <id>
  python3 scripts/smart_intake.py extract --pdf report.pdf --member-id <id>
  python3 scripts/smart_intake.py confirm --member-id <id> --intake-data '<JSON>'
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import os
import re
import sys
import urllib.request
import urllib.error
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from config import get_vision_config, get_llm_config, get_pdf_config, check_pdf_tools
from validators import validate_intake_records
import health_db


# ---------------------------------------------------------------------------
# LLM call layer
# ---------------------------------------------------------------------------

def _build_openai_payload(messages, model, max_tokens=16384):
    """Build OpenAI-compatible chat completion payload."""
    return json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }, ensure_ascii=False).encode("utf-8")


def _build_anthropic_payload(messages, model, max_tokens=16384):
    """Build Anthropic /v1/messages payload."""
    # Convert from OpenAI message format to Anthropic format
    system_text = ""
    anthropic_msgs = []
    for m in messages:
        if m["role"] == "system":
            system_text = m["content"] if isinstance(m["content"], str) else m["content"]
        else:
            anthropic_msgs.append(m)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "messages": anthropic_msgs,
    }
    if system_text:
        payload["system"] = system_text
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _parse_anthropic_response(body):
    """Extract text from Anthropic response. Returns (text, is_truncated)."""
    text = ""
    for block in body.get("content", []):
        if block.get("type") == "text":
            text = block["text"]
            break
    is_truncated = body.get("stop_reason") == "max_tokens"
    return text, is_truncated


def _parse_openai_response(body):
    """Extract text from OpenAI-compatible response. Returns (text, is_truncated)."""
    choices = body.get("choices", [])
    if choices:
        text = choices[0].get("message", {}).get("content", "")
        is_truncated = choices[0].get("finish_reason") == "length"
        return text, is_truncated
    return "", False


def _http_post(url, headers, data, timeout=120):
    """Make an HTTP POST request and return parsed JSON."""
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        raise RuntimeError(f"LLM API 错误 (HTTP {e.code}): {body[:500]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM API 连接失败: {e.reason}")


def _call_llm_single(messages, config, model_override=None):
    """Call LLM with a single model. Returns (text, is_truncated)."""
    provider = config.get("provider", "")
    model = model_override or config.get("model", "")
    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "").rstrip("/")
    max_tokens = config.get("max_tokens", 16384)

    if not provider or not model or not api_key:
        raise RuntimeError(
            "LLM 未配置。请先配置 vision 或 llm：\n"
            "  python3 scripts/setup.py set-vision --provider <provider> --model <model> --api-key <key> --base-url <url>"
        )

    is_anthropic = provider == "anthropic"

    if is_anthropic:
        url = (base_url or "https://api.anthropic.com") + "/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = _build_anthropic_payload(messages, model, max_tokens)
    else:
        url = (base_url or "https://api.openai.com/v1") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = _build_openai_payload(messages, model, max_tokens)

    body = _http_post(url, headers, payload)

    if is_anthropic:
        return _parse_anthropic_response(body)
    return _parse_openai_response(body)


def _call_llm(messages, config):
    """Call LLM with fallback models. Returns (text, is_truncated).

    Tries the primary model first. If it fails, tries each fallback model
    in order until one succeeds.
    """
    fallback_models = config.get("fallback_models", [])
    primary_model = config.get("model", "")
    models_to_try = [primary_model] + [m for m in fallback_models if m != primary_model]

    last_error = None
    for model in models_to_try:
        try:
            return _call_llm_single(messages, config, model_override=model)
        except RuntimeError as e:
            last_error = e
            import sys
            print(f"⚠ 模型 {model} 调用失败: {e}，尝试下一个备选模型...", file=sys.stderr)
            continue

    raise RuntimeError(f"所有模型均调用失败。最后错误: {last_error}")


def _call_vision_llm(prompt_text, image_base64, mime_type, config):
    """Call vision LLM with an image. Returns (text, is_truncated)."""
    provider = config.get("provider", "")
    model = config.get("model", "")
    api_key = config.get("api_key", "")
    base_url = config.get("base_url", "").rstrip("/")

    if not provider or not model or not api_key:
        raise RuntimeError(
            "视觉模型未配置。请先配置：\n"
            "  python3 scripts/setup.py set-vision --provider <provider> --model <model> --api-key <key> --base-url <url>"
        )

    is_anthropic = provider == "anthropic"

    image_content = {
        "type": "image_url",
        "image_url": {"url": f"data:{mime_type};base64,{image_base64}"},
    }
    if is_anthropic:
        image_content = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": image_base64,
            },
        }

    user_message = {
        "role": "user",
        "content": [
            image_content,
            {"type": "text", "text": prompt_text},
        ],
    }

    if is_anthropic:
        url = (base_url or "https://api.anthropic.com") + "/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = json.dumps({
            "model": model,
            "max_tokens": 16384,
            "temperature": 0.1,
            "messages": [user_message],
        }, ensure_ascii=False).encode("utf-8")
    else:
        url = (base_url or "https://api.openai.com/v1") + "/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        payload = json.dumps({
            "model": model,
            "messages": [user_message],
            "temperature": 0.1,
            "max_tokens": 16384,
        }, ensure_ascii=False).encode("utf-8")

    body = _http_post(url, headers, payload)

    if is_anthropic:
        return _parse_anthropic_response(body)
    return _parse_openai_response(body)


def _call_llm_with_continuation(messages, config, max_attempts=3):
    """Call LLM with automatic continuation on truncation. Returns full text."""
    text, is_truncated = _call_llm(messages, config)
    if not is_truncated:
        return text

    fragments = [text]
    conversation = list(messages)
    for _ in range(max_attempts - 1):
        conversation.append({"role": "assistant", "content": text})
        conversation.append({"role": "user", "content": "输出被截断了，请从截断处继续输出剩余内容。"})
        text, is_truncated = _call_llm(conversation, config)
        fragments.append(text)
        if not is_truncated:
            break
    return "".join(fragments)


def _call_vision_llm_with_continuation(prompt_text, image_base64, mime_type,
                                       vision_config, llm_config, max_attempts=3):
    """Call vision LLM with continuation via text LLM fallback. Returns full text."""
    text, is_truncated = _call_vision_llm(prompt_text, image_base64, mime_type, vision_config)
    if not is_truncated:
        return text

    fragments = [text]
    # Continue via text LLM with the partial output
    messages = [
        {"role": "system", "content": "你是医疗数据结构化提取专家。请严格按照 JSON 格式输出。"},
        {"role": "user", "content": prompt_text},
        {"role": "assistant", "content": text},
        {"role": "user", "content": "输出被截断了，请从截断处继续输出剩余内容。"},
    ]
    for _ in range(max_attempts - 1):
        text, is_truncated = _call_llm(messages, llm_config)
        fragments.append(text)
        if not is_truncated:
            break
        messages.append({"role": "assistant", "content": text})
        messages.append({"role": "user", "content": "输出被截断了，请从截断处继续输出剩余内容。"})
    return "".join(fragments)


# ---------------------------------------------------------------------------
# Preprocessing
# ---------------------------------------------------------------------------

_MIME_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".gif": "image/gif",
    ".webp": "image/webp", ".bmp": "image/bmp",
}


def _image_to_base64(path):
    """Read image file and return (base64_str, mime_type)."""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"图片文件不存在: {path}")
    ext = os.path.splitext(path)[1].lower()
    mime = _MIME_MAP.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii"), mime


def _pdf_pages_to_images(path):
    """Convert PDF pages to PNG bytes list using PyMuPDF (fitz)."""
    import fitz
    doc = fitz.open(path)
    images = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        images.append(pix.tobytes("png"))
    doc.close()
    return images


def _extract_text_with_mineru(path):
    """Extract text from PDF using MinerU (magic-pdf). Returns None if unavailable."""
    import shutil
    import subprocess
    import tempfile
    import glob as glob_mod

    if not shutil.which("magic-pdf"):
        return None

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            result = subprocess.run(
                ["magic-pdf", "-p", path, "-o", tmpdir, "-m", "auto"],
                capture_output=True, text=True, timeout=300
            )
            if result.returncode != 0:
                print(f"⚠ MinerU 处理失败: {result.stderr[:200]}", file=sys.stderr)
                return None

            # Find output markdown file (path structure varies by version)
            md_files = glob_mod.glob(os.path.join(tmpdir, "**", "*.md"), recursive=True)
            if md_files:
                # Prefer the largest markdown file
                md_files.sort(key=lambda f: os.path.getsize(f), reverse=True)
                with open(md_files[0], "r", encoding="utf-8") as f:
                    text = f.read()
                if len(text.strip()) >= 50:
                    return text
        except subprocess.TimeoutExpired:
            print("⚠ MinerU 处理超时", file=sys.stderr)
        except Exception as e:
            print(f"⚠ MinerU 处理异常: {e}", file=sys.stderr)
    return None


def _extract_text_with_paddleocr(path):
    """Extract text from PDF using PaddleOCR. Returns None if unavailable."""
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        return None

    # PaddleOCR works on images, need fitz to convert PDF pages
    try:
        page_images = _pdf_pages_to_images(path)
    except ImportError:
        return None

    try:
        ocr = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)
    except Exception as e:
        print(f"⚠ PaddleOCR 初始化失败: {e}", file=sys.stderr)
        return None

    all_texts = []
    for page_idx, img_bytes in enumerate(page_images):
        try:
            import numpy as np
            from PIL import Image
            img = Image.open(io.BytesIO(img_bytes))
            img_array = np.array(img)
            result = ocr.ocr(img_array, cls=True)
            if result:
                page_lines = []
                for line_group in result:
                    if line_group:
                        for line in line_group:
                            page_lines.append(line[1][0])
                if page_lines:
                    all_texts.append("\n".join(page_lines))
        except Exception as e:
            print(f"⚠ PaddleOCR 第{page_idx + 1}页处理失败: {e}", file=sys.stderr)

    text = "\n\n".join(all_texts)
    return text if len(text.strip()) >= 50 else None


def _build_pdf_install_hint(tools=None):
    """Build install recommendation hint based on missing PDF tools."""
    if tools is None:
        tools = check_pdf_tools()

    hints = []
    if not tools["mineru"]:
        hints.append(
            "  • MinerU（推荐，支持复杂版面分析）:\n"
            "    pip install 'magic-pdf[full]'\n"
            "    详见: https://github.com/opendatalab/MinerU"
        )
    if not tools["paddleocr"]:
        hints.append(
            "  • PaddleOCR（轻量级中文 OCR）:\n"
            "    pip install paddlepaddle paddleocr\n"
            "    详见: https://github.com/PaddlePaddle/PaddleOCR"
        )
    if not tools["pdfplumber"]:
        hints.append("  • pdfplumber: pip install pdfplumber")
    if not tools["PyPDF2"]:
        hints.append("  • PyPDF2: pip install PyPDF2")
    if not tools["PyMuPDF"]:
        hints.append("  • PyMuPDF: pip install PyMuPDF")

    if not hints:
        return ""
    return "💡 建议安装以下工具以增强 PDF 处理能力:\n" + "\n".join(hints)


def _extract_text_from_pdf(path, vision_config=None):
    """Extract text from PDF.

    Priority chain:
      pdfplumber → PyPDF2 → [text too short?] → MinerU → PaddleOCR → Vision LLM
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"PDF 文件不存在: {path}")

    extracted_text = ""
    import_errors = []

    # --- Stage 1: Text-based extraction (for electronic PDFs) ---

    # Try pdfplumber first (better table extraction)
    try:
        import pdfplumber
        texts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    texts.append(text)
                # Also try extracting tables
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if row:
                            texts.append("\t".join(str(c) if c else "" for c in row))
        if texts:
            extracted_text = "\n".join(texts)
    except ImportError:
        import_errors.append("pdfplumber")

    # Fallback to PyPDF2
    if not extracted_text:
        try:
            import PyPDF2
            texts = []
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        texts.append(text)
            if texts:
                extracted_text = "\n".join(texts)
        except ImportError:
            import_errors.append("PyPDF2")

    # If text is long enough, return it (electronic PDF successfully extracted)
    if len(extracted_text) >= 50:
        return extracted_text

    # --- Stage 2: Local OCR for scanned PDFs ---

    pdf_config = get_pdf_config()
    ocr_engine = pdf_config.get("ocr_engine", "auto")

    # Try MinerU
    if ocr_engine in ("auto", "mineru"):
        mineru_text = _extract_text_with_mineru(path)
        if mineru_text:
            return mineru_text

    # Try PaddleOCR
    if ocr_engine in ("auto", "paddleocr"):
        paddle_text = _extract_text_with_paddleocr(path)
        if paddle_text:
            return paddle_text

    # --- Stage 3: Vision LLM OCR fallback (requires API) ---

    try:
        page_images = _pdf_pages_to_images(path)
    except ImportError:
        import_errors.append("PyMuPDF")
        tools = check_pdf_tools()
        hint = _build_pdf_install_hint(tools)
        install_hint = "\n".join(f"  pip install {lib}" for lib in import_errors)
        raise RuntimeError(
            f"无法提取 PDF 文本。以下库均未安装：\n{install_hint}\n"
            f"请至少安装其中一个以支持 PDF 处理。\n\n{hint}"
        )

    if not vision_config:
        vision_config = get_vision_config()

    if not vision_config.get("enabled") or not vision_config.get("api_key"):
        tools = check_pdf_tools()
        hint = _build_pdf_install_hint(tools)
        raise RuntimeError(
            "扫描件 PDF 需要 OCR 能力，但当前无可用方案：\n"
            "  • 视觉模型未配置（用于 Vision OCR）\n"
            "  • MinerU / PaddleOCR 未安装（用于本地 OCR）\n\n"
            f"{hint}\n\n"
            "或配置视觉模型:\n"
            "  python3 scripts/setup.py set-vision --provider <provider> --model <model> --api-key <key>"
        )

    ocr_texts = []
    for img_bytes in page_images:
        img_b64 = base64.b64encode(img_bytes).decode("ascii")
        prompt = "请完整提取图片中的所有文字和表格内容，保持原始格式。如果有表格，用制表符分隔列。"
        text, _ = _call_vision_llm(prompt, img_b64, "image/png", vision_config)
        if text:
            ocr_texts.append(text)

    ocr_result = "\n".join(ocr_texts) if ocr_texts else ""

    # Add recommendation hint if local OCR tools are missing
    tools = check_pdf_tools()
    if not tools["mineru"] or not tools["paddleocr"]:
        hint = _build_pdf_install_hint(tools)
        if hint:
            msg = (
                "\n\n💡 当前通过 Vision LLM 提取扫描件文本（按页调用 API，较慢且有成本）。"
                f"\n{hint}"
            )
            if ocr_result:
                ocr_result += msg
            elif extracted_text:
                extracted_text += msg

    if ocr_result:
        return ocr_result

    # If we had some short text from pdfplumber/PyPDF2, return it as last resort
    if extracted_text:
        return extracted_text

    raise RuntimeError("PDF 文本提取失败：未能从任何页面中提取到文字内容")


def preprocess(input_type, content, vision_config=None):
    """Preprocess input into plain text for extraction.

    Args:
        input_type: "image", "pdf", or "text"
        content: file path (image/pdf) or text string
        vision_config: vision model config (needed for image)

    Returns:
        Extracted text string
    """
    if input_type == "text":
        return content

    if input_type == "pdf":
        return _extract_text_from_pdf(content, vision_config)

    if input_type == "image":
        if not vision_config:
            vision_config = get_vision_config()
        img_b64, mime = _image_to_base64(content)
        prompt = "请完整提取图片中的所有文字和表格内容，保持原始格式。如果有表格，用制表符分隔列。"
        text, _ = _call_vision_llm(prompt, img_b64, mime, vision_config)
        return text

    raise ValueError(f"不支持的输入类型: {input_type}")


# ---------------------------------------------------------------------------
# Extraction prompt & parsing
# ---------------------------------------------------------------------------

_EXTRACTION_PROMPT = """你是医疗数据结构化提取专家。请分析以下医疗相关文本，完成两个任务：

1. 识别文本中包含的数据类型
2. 提取结构化数据

## 支持的数据类型及字段

### visit（就诊记录）
- visit_type: 门诊/住院/急诊
- visit_date: YYYY-MM-DD
- hospital, department, chief_complaint, diagnosis, summary

### symptom（症状）
- symptom: 症状名称
- severity: 轻度/中度/重度
- onset_date: YYYY-MM-DD
- description

### medication（用药）
- name: 药品名称
- dosage: 剂量（如"0.5g"）
- frequency: 用法（如"每日三次"）
- start_date: YYYY-MM-DD
- purpose: 用途

### lab_result（检验报告）
- test_name: 检验名称（如"血常规"）
- test_date: YYYY-MM-DD
- items: 数组，每项包含:
  - name: 项目名
  - value: 数值（字符串）
  - unit: 单位
  - reference: 参考范围（如"3.5-9.5"）
  - is_abnormal: true/false

### imaging（影像检查）
- exam_name: 检查名称
- exam_date: YYYY-MM-DD
- findings: 所见
- conclusion: 结论

### health_metric（健康指标）
- metric_type: blood_pressure/blood_sugar/heart_rate/weight/temperature/blood_oxygen/height
- value: 数值（血压用 {{"systolic": N, "diastolic": N}} 格式）
- unit: 单位
- measured_at: YYYY-MM-DD HH:MM 或 YYYY-MM-DD
- notes: 备注

## 提取规则
- 提取所有能识别的数据，一段文本可能包含多种类型
- 检验报告必须提取每一个检验项目，不要遗漏或汇总
- 日期缺失时用 {today} 填充
- 医院名称：将"本院""我院"替换为文中能找到的具体医院名
- 数值保持原始精度
- 不确定的字段设为 null，不要猜测

## 输出格式（严格 JSON）
{{
  "records": [
    {{
      "type": "lab_result",
      "confidence": 0.95,
      "data": {{ ... }}
    }}
  ],
  "source_summary": "一句话描述输入内容"
}}

## 待分析文本
{text_content}"""


def _extract_json_from_text(text):
    """Extract JSON object from LLM response text, handling markdown fences."""
    text = text.strip()
    # Remove markdown code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    # Find the outermost JSON object
    start = text.find("{")
    if start == -1:
        raise ValueError("LLM 返回中未找到 JSON 对象")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("LLM 返回的 JSON 不完整")


def extract(input_type, content, member_id=None):
    """Extract structured health data from input.

    Args:
        input_type: "image", "pdf", or "text"
        content: file path or text string
        member_id: optional, for context

    Returns:
        dict with "records" and "source_summary"
    """
    vision_config = get_vision_config()
    llm_config = get_llm_config()

    today = date.today().isoformat()
    text = None

    try:
        # Fix 3: Image → single vision call (OCR + extraction in one shot)
        if input_type == "image":
            img_b64, mime = _image_to_base64(content)
            prompt = _EXTRACTION_PROMPT.replace("{today}", today).replace(
                "{text_content}", "[图片内容见上方]"
            )
            response_text = _call_vision_llm_with_continuation(
                prompt, img_b64, mime, vision_config, llm_config
            )
        else:
            # Step 1: Preprocess (text / pdf)
            text = preprocess(input_type, content, vision_config)
            if not text or not text.strip():
                return {"records": [], "source_summary": "未能从输入中提取到文本内容"}

            # Step 2: Extract via LLM with continuation
            prompt = _EXTRACTION_PROMPT.replace("{today}", today).replace("{text_content}", text)

            messages = [
                {"role": "system", "content": "你是医疗数据结构化提取专家。请严格按照 JSON 格式输出。"},
                {"role": "user", "content": prompt},
            ]

            response_text = _call_llm_with_continuation(messages, llm_config)
    except Exception as e:
        return {
            "records": [],
            "source_summary": f"提取失败: {e}",
            "error": str(e),
            "text_preview": text[:200] + ("..." if len(text) > 200 else "") if text else ("[图片输入]" if input_type == "image" else ""),
        }

    # Step 3: Parse response
    try:
        result = _extract_json_from_text(response_text)
    except (json.JSONDecodeError, ValueError) as e:
        return {
            "records": [],
            "source_summary": f"提取失败: {e}",
            "raw_response": response_text[:1000],
        }

    records = result.get("records", [])
    source_summary = result.get("source_summary", "")

    # Normalize health_metric values
    for rec in records:
        if rec.get("type") == "health_metric":
            _normalize_health_metric(rec.get("data", {}))

    return {
        "records": records,
        "source_summary": source_summary,
        "text_preview": text[:200] + ("..." if len(text) > 200 else "") if input_type != "image" and text else "[图片输入]" if input_type == "image" else "",
    }


def _normalize_health_metric(data):
    """Normalize health metric data to match health_metric.py expectations."""
    mt = data.get("metric_type", "")
    value = data.get("value")

    if mt == "blood_pressure" and isinstance(value, str):
        # Convert "130/85" to {"systolic": 130, "diastolic": 85}
        match = re.match(r"(\d+)\s*/\s*(\d+)", str(value))
        if match:
            data["value"] = json.dumps({
                "systolic": int(match.group(1)),
                "diastolic": int(match.group(2)),
            })
        elif isinstance(value, dict):
            data["value"] = json.dumps(value)
    elif mt == "blood_pressure" and isinstance(value, dict):
        data["value"] = json.dumps(value)


# ---------------------------------------------------------------------------
# Confirm & record
# ---------------------------------------------------------------------------

def _call_and_capture(fn, args):
    """Call fn(args), capture stdout, return parsed JSON result."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(args)
    output = buf.getvalue().strip()
    if output:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {"status": "error", "message": f"输出解析失败: {output[:200]}"}
    return {"status": "ok"}


def _check_duplicate(rec_type, member_id, data):
    """Check if a record already exists in the database. Returns True if duplicate found."""
    if health_db.is_api_mode():
        return False

    try:
        conn = health_db.get_connection()
    except Exception:
        return False

    try:
        if rec_type == "visit":
            row = conn.execute(
                "SELECT 1 FROM visits WHERE member_id=? AND visit_date=? AND visit_type=? AND is_deleted=0 LIMIT 1",
                (member_id, data.get("visit_date", ""), data.get("visit_type", ""))
            ).fetchone()
        elif rec_type == "symptom":
            row = conn.execute(
                "SELECT 1 FROM symptoms WHERE member_id=? AND symptom=? AND onset_date=? AND is_deleted=0 LIMIT 1",
                (member_id, data.get("symptom", ""), data.get("onset_date", ""))
            ).fetchone()
        elif rec_type == "medication":
            row = conn.execute(
                "SELECT 1 FROM medications WHERE member_id=? AND name=? AND dosage=? AND is_deleted=0 LIMIT 1",
                (member_id, data.get("name", ""), data.get("dosage", ""))
            ).fetchone()
        elif rec_type == "lab_result":
            row = conn.execute(
                "SELECT 1 FROM lab_results WHERE member_id=? AND test_name=? AND test_date=? AND is_deleted=0 LIMIT 1",
                (member_id, data.get("test_name", ""), data.get("test_date", ""))
            ).fetchone()
        elif rec_type == "imaging":
            row = conn.execute(
                "SELECT 1 FROM imaging_results WHERE member_id=? AND exam_name=? AND exam_date=? AND is_deleted=0 LIMIT 1",
                (member_id, data.get("exam_name", ""), data.get("exam_date", ""))
            ).fetchone()
        elif rec_type == "health_metric":
            value = data.get("value", "")
            if isinstance(value, dict):
                value = json.dumps(value, ensure_ascii=False)
            else:
                value = str(value)
            row = conn.execute(
                "SELECT 1 FROM health_metrics WHERE member_id=? AND metric_type=? AND value=? AND measured_at=? AND is_deleted=0 LIMIT 1",
                (member_id, data.get("metric_type", ""), value, data.get("measured_at", ""))
            ).fetchone()
        else:
            return False
        return row is not None
    except Exception:
        return False
    finally:
        conn.close()


def confirm(member_id, records):
    """Confirm and record extracted data.

    Calls existing add_* functions from medical_record.py and health_metric.py.
    Captures stdout to detect errors, and skips duplicates.

    Args:
        member_id: target member ID
        records: list of {"type": ..., "data": {...}, "confidence": ...}

    Returns:
        dict with results for each record
    """
    import medical_record
    import health_metric

    try:
        records = validate_intake_records(records)
    except ValueError as e:
        return {"status": "error", "total": 0, "success": 0, "failed": 1, "skipped": 0,
                "details": [{"index": 0, "type": "schema", "status": "error", "message": str(e)}]}

    results = []

    for i, rec in enumerate(records):
        rec_type = rec.get("type", "")
        data = rec.get("data", {})

        # Fix 5: Dedup check
        if _check_duplicate(rec_type, member_id, data):
            results.append({"index": i, "type": rec_type, "status": "skipped",
                            "message": "重复记录，已跳过"})
            continue

        try:
            if rec_type == "visit":
                args = _make_namespace(
                    member_id=member_id,
                    visit_type=data.get("visit_type", "门诊"),
                    visit_date=data.get("visit_date", date.today().isoformat()),
                    end_date=data.get("end_date"),
                    hospital=data.get("hospital"),
                    department=data.get("department"),
                    chief_complaint=data.get("chief_complaint"),
                    diagnosis=data.get("diagnosis"),
                    summary=data.get("summary"),
                )
                result = _call_and_capture(medical_record.add_visit, args)

            elif rec_type == "symptom":
                args = _make_namespace(
                    member_id=member_id,
                    symptom=data.get("symptom", ""),
                    visit_id=data.get("visit_id"),
                    severity=data.get("severity"),
                    onset_date=data.get("onset_date"),
                    end_date=data.get("end_date"),
                    description=data.get("description"),
                )
                result = _call_and_capture(medical_record.add_symptom, args)

            elif rec_type == "medication":
                args = _make_namespace(
                    member_id=member_id,
                    name=data.get("name", ""),
                    visit_id=data.get("visit_id"),
                    dosage=data.get("dosage"),
                    frequency=data.get("frequency"),
                    start_date=data.get("start_date"),
                    end_date=data.get("end_date"),
                    purpose=data.get("purpose"),
                )
                result = _call_and_capture(medical_record.add_medication, args)

            elif rec_type == "lab_result":
                items = data.get("items", [])
                args = _make_namespace(
                    member_id=member_id,
                    test_name=data.get("test_name", ""),
                    test_date=data.get("test_date", date.today().isoformat()),
                    items=json.dumps(items, ensure_ascii=False),
                    visit_id=data.get("visit_id"),
                )
                result = _call_and_capture(medical_record.add_lab_result, args)

            elif rec_type == "imaging":
                args = _make_namespace(
                    member_id=member_id,
                    exam_name=data.get("exam_name", ""),
                    exam_date=data.get("exam_date", date.today().isoformat()),
                    visit_id=data.get("visit_id"),
                    findings=data.get("findings"),
                    conclusion=data.get("conclusion"),
                )
                result = _call_and_capture(medical_record.add_imaging, args)

            elif rec_type == "health_metric":
                value = data.get("value", "")
                if isinstance(value, dict):
                    value = json.dumps(value, ensure_ascii=False)
                else:
                    value = str(value)
                args = _make_namespace(
                    member_id=member_id,
                    type=data.get("metric_type", ""),
                    value=value,
                    measured_at=data.get("measured_at"),
                    note=data.get("notes"),
                )
                result = _call_and_capture(health_metric.add_metric, args)

            else:
                results.append({"index": i, "type": rec_type, "status": "error", "message": f"未知类型: {rec_type}"})
                continue

            # Fix 4: Check captured result status
            if result.get("status") == "error":
                results.append({"index": i, "type": rec_type, "status": "error",
                                "message": result.get("message", "录入失败")})
            else:
                results.append({"index": i, "type": rec_type, "status": "ok"})

        except Exception as e:
            results.append({"index": i, "type": rec_type, "status": "error", "message": str(e)})

    ok_count = sum(1 for r in results if r["status"] == "ok")
    err_count = sum(1 for r in results if r["status"] == "error")
    skip_count = sum(1 for r in results if r["status"] == "skipped")

    if err_count == 0 and skip_count == 0:
        status = "ok"
    elif err_count == 0 and skip_count > 0:
        status = "ok"
    elif ok_count > 0:
        status = "partial"
    else:
        status = "error"

    return {
        "status": status,
        "total": len(records),
        "success": ok_count,
        "failed": err_count,
        "skipped": skip_count,
        "details": results,
    }


def _make_namespace(**kwargs):
    """Create an argparse.Namespace-like object from keyword arguments."""
    return argparse.Namespace(**kwargs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="智能录入 — 从图片/PDF/文本提取结构化健康数据")
    sub = parser.add_subparsers(dest="command", required=True)

    # extract command
    p_ext = sub.add_parser("extract", help="提取结构化数据")
    p_ext.add_argument("--member-id", required=True, help="成员 ID")
    p_ext.add_argument("--owner-id", default=None, help="所有者 ID")
    input_group = p_ext.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--text", help="自由文本输入")
    input_group.add_argument("--image", help="图片文件路径")
    input_group.add_argument("--pdf", help="PDF 文件路径")

    # confirm command
    p_conf = sub.add_parser("confirm", help="确认录入提取的数据")
    p_conf.add_argument("--member-id", required=True, help="成员 ID")
    p_conf.add_argument("--owner-id", default=None, help="所有者 ID")
    p_conf.add_argument("--intake-data", required=True, help="extract 返回的 JSON 数据")

    args = parser.parse_args()

    if args.command == "extract":
        try:
            conn = health_db.get_connection()
            try:
                if not health_db.verify_member_ownership(conn, args.member_id, args.owner_id):
                    health_db.output_json({"records": [], "source_summary": f"无权访问成员: {args.member_id}", "error": "unauthorized"})
                    return
            finally:
                conn.close()
            if args.text:
                result = extract("text", args.text, args.member_id)
            elif args.image:
                result = extract("image", args.image, args.member_id)
            elif args.pdf:
                result = extract("pdf", args.pdf, args.member_id)
            health_db.output_json(result)
        except Exception as e:
            health_db.output_json({"records": [], "source_summary": f"提取失败: {e}", "error": str(e)})

    elif args.command == "confirm":
        conn = health_db.get_connection()
        try:
            if not health_db.verify_member_ownership(conn, args.member_id, args.owner_id):
                health_db.output_json({"status": "error", "message": f"无权访问成员: {args.member_id}"})
                return
        finally:
            conn.close()
        try:
            intake = json.loads(args.intake_data)
        except json.JSONDecodeError:
            health_db.output_json({"status": "error", "message": "intake-data 格式错误，需要 JSON"})
            return
        records = intake if isinstance(intake, list) else intake.get("records", [])
        result = confirm(args.member_id, records)
        health_db.output_json(result)


if __name__ == "__main__":
    main()
