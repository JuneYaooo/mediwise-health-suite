"""Setup and configuration check for MediWise Health Tracker.

Usage:
  python3 scripts/setup.py check          # Check current config status
  python3 scripts/setup.py init           # Initialize with defaults
  python3 scripts/setup.py set-db-path --path /path/to/health.db
  python3 scripts/setup.py set-vision --provider siliconflow --model Qwen/Qwen2.5-VL-72B-Instruct --api-key sk-xxx --base-url https://api.siliconflow.cn/v1
  python3 scripts/setup.py disable-vision
  python3 scripts/setup.py set-privacy --level anonymized
  python3 scripts/setup.py show           # Show current config
"""

from __future__ import annotations

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    load_config, save_config, config_exists, check_config_status,
    ensure_data_dir, DEFAULT_CONFIG, CONFIG_PATH,
    check_pdf_tools,
)


def output_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_check(args):
    """Check config status and report issues."""
    status = check_config_status()
    # Check backend connectivity if enabled
    cfg = load_config()
    backend = cfg.get("backend", {})
    if backend.get("enabled") and backend.get("base_url"):
        status["backend_enabled"] = True
        status["backend_url"] = backend["base_url"]
        try:
            import api_client
            api_client._request("GET", "/members")
            status["backend_connected"] = True
        except Exception as e:
            status["backend_connected"] = False
            status["backend_error"] = str(e)
            status.setdefault("issues", []).append(f"后端 API 连接失败: {e}")
    else:
        status["backend_enabled"] = False
    output_json({"status": "ok", **status})


def cmd_init(args):
    """Initialize config with defaults if not exists."""
    ensure_data_dir()
    if config_exists():
        cfg = load_config()
        output_json({
            "status": "ok",
            "message": "配置文件已存在，无需重新初始化",
            "config_path": CONFIG_PATH,
            "config": cfg
        })
    else:
        save_config(DEFAULT_CONFIG)
        output_json({
            "status": "ok",
            "message": "配置已初始化",
            "config_path": CONFIG_PATH,
            "config": DEFAULT_CONFIG
        })


def cmd_set_db_path(args):
    """Set custom database path."""
    cfg = load_config()
    cfg["db_path"] = os.path.abspath(args.path)
    save_config(cfg)
    output_json({
        "status": "ok",
        "message": f"数据库路径已设置为: {cfg['db_path']}",
        "config": cfg
    })


def cmd_set_vision(args):
    """Configure vision model."""
    cfg = load_config()
    cfg["vision"] = {
        "enabled": True,
        "provider": args.provider,
        "model": args.model,
        "api_key": args.api_key,
        "base_url": args.base_url or ""
    }
    save_config(cfg)
    # Mask API key in output
    display = {**cfg}
    display["vision"] = {**cfg["vision"], "api_key": cfg["vision"]["api_key"][:8] + "***"}
    output_json({
        "status": "ok",
        "message": f"多模态视觉模型已配置: {args.provider}/{args.model}",
        "config": display
    })


def cmd_disable_vision(args):
    """Disable vision model."""
    cfg = load_config()
    cfg["vision"]["enabled"] = False
    save_config(cfg)
    output_json({
        "status": "ok",
        "message": "多模态视觉模型已禁用",
        "config": cfg
    })


def cmd_show(args):
    """Show current config."""
    if not config_exists():
        output_json({
            "status": "warning",
            "message": "配置文件不存在，请先运行 setup.py init 初始化",
            "config_path": CONFIG_PATH
        })
        return
    cfg = load_config()
    # Mask API keys
    display = {**cfg}
    if cfg.get("vision", {}).get("api_key"):
        display["vision"] = {**cfg["vision"], "api_key": cfg["vision"]["api_key"][:8] + "***"}
    if cfg.get("embedding", {}).get("api_key"):
        display["embedding"] = {**cfg["embedding"], "api_key": cfg["embedding"]["api_key"][:8] + "***"}
    if cfg.get("backend", {}).get("token"):
        display["backend"] = {**cfg.get("backend", {}), "token": cfg["backend"]["token"][:8] + "***"}
    output_json({"status": "ok", "config_path": CONFIG_PATH, "config": display})


def cmd_set_embedding(args):
    """Configure embedding provider."""
    cfg = load_config()
    cfg["embedding"] = {
        "provider": args.provider,
        "model": args.model or "",
        "api_key": args.api_key or "",
        "base_url": args.base_url or "",
        "dimensions": cfg.get("embedding", {}).get("dimensions", 0)
    }
    save_config(cfg)
    display = {**cfg}
    if cfg["embedding"].get("api_key"):
        display["embedding"] = {**cfg["embedding"], "api_key": cfg["embedding"]["api_key"][:8] + "***"}
    output_json({
        "status": "ok",
        "message": f"Embedding 已配置: provider={args.provider}",
        "config": display
    })


def cmd_test_embedding(args):
    """Test current embedding provider."""
    from embedding_provider import get_provider
    provider = get_provider()

    if provider.name == "none":
        output_json({
            "status": "warning",
            "provider": "none",
            "message": "无可用的 Embedding 模型。",
            "hint": "安装 sentence-transformers (pip install sentence-transformers) 或配置硅基智能 API (setup.py set-embedding --provider siliconflow --api-key <key>)"
        })
        return

    test_texts = ["测试文本", "这是一个测试"]
    try:
        result = provider.encode(test_texts)
        if result and len(result) == 2:
            output_json({
                "status": "ok",
                "provider": provider.name,
                "model": provider.model_name,
                "dimensions": len(result[0]),
                "message": f"Embedding 测试成功: {provider.name}/{provider.model_name}, 维度={len(result[0])}"
            })
        else:
            output_json({
                "status": "error",
                "provider": provider.name,
                "message": "Embedding 返回结果异常"
            })
    except Exception as e:
        output_json({
            "status": "error",
            "provider": provider.name,
            "message": f"Embedding 测试失败: {e}"
        })


def cmd_set_backend(args):
    """Enable backend API mode."""
    cfg = load_config()
    cfg["backend"] = {
        "enabled": True,
        "base_url": args.url.rstrip("/"),
        "token": args.token
    }
    save_config(cfg)
    display_token = args.token[:8] + "***" if len(args.token) > 8 else "***"
    output_json({
        "status": "ok",
        "message": f"后端 API 模式已启用: {args.url}",
        "backend": {"enabled": True, "base_url": args.url, "token": display_token}
    })


def cmd_disable_backend(args):
    """Disable backend API mode, fall back to local SQLite."""
    cfg = load_config()
    cfg["backend"] = {"enabled": False, "base_url": "", "token": ""}
    save_config(cfg)
    output_json({
        "status": "ok",
        "message": "后端 API 模式已禁用，已回退到本地 SQLite 模式"
    })


def cmd_test_vision(args):
    """Test vision model with a reference medical report image."""
    from config import get_vision_config
    import base64

    vision_cfg = get_vision_config()
    if not vision_cfg.get("enabled") or not vision_cfg.get("api_key"):
        output_json({
            "status": "error",
            "message": "视觉模型未配置。请先运行 set-vision 配置视觉模型。"
        })
        return

    # Locate test image
    script_dir = os.path.dirname(os.path.abspath(__file__))
    test_image = os.path.join(script_dir, "..", "references", "test-vision.jpg")
    if not os.path.isfile(test_image):
        output_json({
            "status": "error",
            "message": f"测试图片不存在: {test_image}"
        })
        return

    # Read and encode image
    with open(test_image, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("ascii")

    # Expected keywords that a working vision model must identify
    # Test image is a blood lipid report with: TC 7.23, LDL-C 4.33, diagnosis 高胆固醇血症
    expected_keywords = ["7.23", "4.33", "胆固醇"]

    # Call vision model
    try:
        from smart_intake import _call_vision_llm
        prompt = (
            "请提取这张医疗检验报告图片中的所有检验项目和结果。"
            "输出格式：每行一个项目，格式为 项目名: 结果值 单位。"
            "最后列出诊断结论。"
        )
        text, _ = _call_vision_llm(prompt, img_b64, "image/jpeg", vision_cfg)
    except Exception as e:
        output_json({
            "status": "error",
            "message": f"视觉模型调用失败: {e}",
            "hint": "请检查 API Key、模型名称和 Base URL 是否正确。"
        })
        return

    if not text or not text.strip():
        output_json({
            "status": "error",
            "message": "视觉模型返回空结果，无法识别图片内容。",
            "hint": "请检查模型是否支持图片输入。"
        })
        return

    # Check if response contains expected keywords
    matched = [kw for kw in expected_keywords if kw in text]
    missing = [kw for kw in expected_keywords if kw not in text]

    if len(matched) >= 2:
        output_json({
            "status": "ok",
            "message": f"视觉模型测试通过！成功识别 {len(matched)}/{len(expected_keywords)} 个关键指标。",
            "matched_keywords": matched,
            "model": f"{vision_cfg.get('provider')}/{vision_cfg.get('model')}",
            "response_preview": text[:500]
        })
    else:
        output_json({
            "status": "error",
            "message": f"视觉模型识别能力不足：仅识别 {len(matched)}/{len(expected_keywords)} 个关键指标。",
            "matched_keywords": matched,
            "missing_keywords": missing,
            "hint": "建议更换为更强的多模态模型（如 Qwen2.5-VL-72B、GPT-4o 等）。",
            "response_preview": text[:500]
        })


def cmd_check_pdf(args):
    """Check PDF extraction tools availability and provide install guidance."""
    tools = check_pdf_tools()
    cfg = load_config()
    pdf_config = cfg.get("pdf", DEFAULT_CONFIG.get("pdf", {}))
    ocr_engine = pdf_config.get("ocr_engine", "auto")

    # Categorize tools
    text_tools = {k: v for k, v in tools.items() if k in ("pdfplumber", "PyPDF2")}
    ocr_tools = {k: v for k, v in tools.items() if k in ("mineru", "paddleocr")}
    support_tools = {k: v for k, v in tools.items() if k == "PyMuPDF"}

    installed = [k for k, v in tools.items() if v]
    missing = [k for k, v in tools.items() if not v]

    # Build capability assessment
    capabilities = []
    if any(text_tools.values()):
        capabilities.append("电子版 PDF 文本提取")
    if tools["mineru"]:
        capabilities.append("复杂版面分析 + OCR（MinerU）")
    if tools["paddleocr"]:
        capabilities.append("中文 OCR 识别（PaddleOCR）")
    if tools["PyMuPDF"]:
        capabilities.append("PDF 转图片（用于 Vision LLM OCR）")

    # Build install recommendations
    recommendations = []
    if not tools["mineru"]:
        recommendations.append({
            "tool": "MinerU",
            "description": "文档智能解析工具，支持复杂版面分析、表格识别、公式提取",
            "install": "pip install 'magic-pdf[full]'",
            "url": "https://github.com/opendatalab/MinerU",
            "priority": "推荐" if not tools["paddleocr"] else "可选",
        })
    if not tools["paddleocr"]:
        recommendations.append({
            "tool": "PaddleOCR",
            "description": "百度飞桨 OCR 工具，中文识别效果优秀，轻量高效",
            "install": "pip install paddlepaddle paddleocr",
            "url": "https://github.com/PaddlePaddle/PaddleOCR",
            "priority": "推荐" if not tools["mineru"] else "可选",
        })
    if not tools["pdfplumber"]:
        recommendations.append({
            "tool": "pdfplumber",
            "description": "电子版 PDF 文本和表格提取",
            "install": "pip install pdfplumber",
            "priority": "推荐",
        })
    if not tools["PyMuPDF"]:
        recommendations.append({
            "tool": "PyMuPDF",
            "description": "PDF 渲染和转图片（PaddleOCR 和 Vision LLM 依赖此库）",
            "install": "pip install PyMuPDF",
            "priority": "推荐" if tools["paddleocr"] else "可选",
        })

    status = "ok" if (any(text_tools.values()) and any(ocr_tools.values())) else "warning"

    output_json({
        "status": status,
        "ocr_engine": ocr_engine,
        "tools": tools,
        "installed": installed,
        "missing": missing,
        "capabilities": capabilities,
        "recommendations": recommendations,
        "hint": (
            "当前 PDF 处理优先级: pdfplumber → PyPDF2 → MinerU → PaddleOCR → Vision LLM\n"
            f"OCR 引擎偏好: {ocr_engine}\n"
            "可通过 set-pdf-engine 命令调整 OCR 引擎偏好"
        ),
    })


def cmd_set_pdf_engine(args):
    """Set preferred PDF OCR engine."""
    valid = ("auto", "mineru", "paddleocr", "vision")
    if args.engine not in valid:
        output_json({
            "status": "error",
            "message": f"无效的 OCR 引擎: {args.engine}，可选: {', '.join(valid)}"
        })
        return
    cfg = load_config()
    if "pdf" not in cfg:
        cfg["pdf"] = {}
    cfg["pdf"]["ocr_engine"] = args.engine
    save_config(cfg)

    engine_desc = {
        "auto": "自动（MinerU → PaddleOCR → Vision LLM）",
        "mineru": "MinerU（复杂版面分析 + OCR）",
        "paddleocr": "PaddleOCR（轻量中文 OCR）",
        "vision": "Vision LLM（通过视觉大模型 OCR，需 API）",
    }
    output_json({
        "status": "ok",
        "message": f"PDF OCR 引擎已设置为: {args.engine}（{engine_desc[args.engine]}）",
        "config": cfg.get("pdf"),
    })


def cmd_set_privacy(args):
    """Set default privacy level."""
    valid = ("full", "anonymized", "statistical")
    if args.level not in valid:
        output_json({"status": "error", "message": f"无效的隐私级别: {args.level}，可选: {', '.join(valid)}"})
        return
    cfg = load_config()
    if "privacy" not in cfg:
        cfg["privacy"] = {}
    cfg["privacy"]["default_level"] = args.level
    save_config(cfg)
    level_desc = {"full": "完整（含 PII）", "anonymized": "匿名化（PII 替换为伪名）", "statistical": "仅统计聚合"}
    output_json({
        "status": "ok",
        "message": f"默认隐私级别已设置为: {args.level}（{level_desc[args.level]}）",
        "config": cfg
    })


def main():
    parser = argparse.ArgumentParser(description="MediWise Health Tracker 配置管理")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="检查配置状态")
    sub.add_parser("init", help="初始化默认配置")

    p = sub.add_parser("set-db-path", help="设置数据库路径")
    p.add_argument("--path", required=True)

    p = sub.add_parser("set-vision", help="配置多模态视觉模型")
    p.add_argument("--provider", required=True, help="提供商: siliconflow / openai / anthropic / ollama")
    p.add_argument("--model", required=True, help="模型名称")
    p.add_argument("--api-key", required=True, help="API Key")
    p.add_argument("--base-url", default="", help="API Base URL（如硅基智能: https://api.siliconflow.cn/v1）")

    sub.add_parser("disable-vision", help="禁用多模态视觉模型")
    sub.add_parser("test-vision", help="测试视觉模型是否能正确识别医疗报告图片")
    sub.add_parser("show", help="显示当前配置")

    p = sub.add_parser("set-embedding", help="配置 Embedding 模型")
    p.add_argument("--provider", required=True, help="提供商: auto / local / siliconflow / none")
    p.add_argument("--api-key", default="", help="API Key（硅基智能需要）")
    p.add_argument("--model", default="", help="模型名称（可选）")
    p.add_argument("--base-url", default="", help="API Base URL（可选）")

    sub.add_parser("test-embedding", help="测试当前 Embedding 模型")

    sub.add_parser("check-pdf", help="检查 PDF 提取工具安装状态并给出安装建议")

    p = sub.add_parser("set-pdf-engine", help="设置 PDF OCR 引擎偏好")
    p.add_argument("--engine", required=True, choices=["auto", "mineru", "paddleocr", "vision"],
                   help="OCR 引擎: auto（自动选择）/ mineru / paddleocr / vision（视觉大模型）")

    p = sub.add_parser("set-backend", help="启用后端 API 模式")
    p.add_argument("--url", required=True, help="后端 API 地址，如 http://localhost:8000/api")
    p.add_argument("--token", required=True, help="JWT Token")

    sub.add_parser("disable-backend", help="禁用后端 API 模式，回退到本地 SQLite")

    p = sub.add_parser("set-privacy", help="设置默认隐私级别")
    p.add_argument("--level", required=True, choices=["full", "anonymized", "statistical"],
                   help="隐私级别: full（完整）/ anonymized（匿名化）/ statistical（仅统计）")

    args = parser.parse_args()
    commands = {
        "check": cmd_check, "init": cmd_init, "set-db-path": cmd_set_db_path,
        "set-vision": cmd_set_vision, "disable-vision": cmd_disable_vision,
        "test-vision": cmd_test_vision,
        "show": cmd_show, "set-embedding": cmd_set_embedding,
        "test-embedding": cmd_test_embedding,
        "check-pdf": cmd_check_pdf, "set-pdf-engine": cmd_set_pdf_engine,
        "set-backend": cmd_set_backend, "disable-backend": cmd_disable_backend,
        "set-privacy": cmd_set_privacy,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
