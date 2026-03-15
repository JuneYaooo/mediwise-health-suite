"""Setup and configuration check for MediWise Health Tracker.

Usage:
  python3 scripts/setup.py check          # Check current config status
  python3 scripts/setup.py init           # Initialize with defaults
  python3 scripts/setup.py set-db-path --path /path/to/health.db
  python3 scripts/setup.py set-vision --provider siliconflow --model Qwen/Qwen2.5-VL-72B-Instruct --api-key sk-xxx --base-url https://api.siliconflow.cn/v1
  python3 scripts/setup.py disable-vision
  python3 scripts/setup.py set-privacy --level anonymized
  python3 scripts/setup.py show           # Show current config
  python3 scripts/setup.py backup --output mediwise-backup.tar.gz
  python3 scripts/setup.py restore --input mediwise-backup.tar.gz
"""

from __future__ import annotations

import argparse
import json
import sys
import os
import sqlite3
import tarfile
import datetime

sys.path.insert(0, os.path.dirname(__file__))
from config import (
    load_config, save_config, config_exists, check_config_status,
    ensure_data_dir, DEFAULT_CONFIG, CONFIG_PATH,
    check_pdf_tools,
)
from health_db import (
    init_db,
    get_medical_db_path,
    get_lifestyle_db_path,
    MEDICAL_TABLES,
    LIFESTYLE_TABLES,
)

# ---------------------------------------------------------------------------
# Vision provider presets — users only need to supply --api-key
# ---------------------------------------------------------------------------
VISION_PROVIDER_PRESETS = {
    "siliconflow": {
        "label": "硅基流动（国内推荐）",
        "provider": "siliconflow",
        "model": "Qwen/Qwen2.5-VL-72B-Instruct",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_hint": "在 https://cloud.siliconflow.cn 注册获取，有免费额度",
        "notes": "国内访问速度快，Qwen2.5-VL 中文医疗报告识别效果佳",
    },
    "gemini": {
        "label": "Google Gemini（海外推荐）",
        "provider": "openai",  # uses OpenAI-compatible endpoint
        "model": "gemini-3.1-pro-preview",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key_hint": "在 https://aistudio.google.com/apikey 获取，免费",
        "notes": "Google Gemini，多语言医疗文档识别，需海外网络",
    },
    "openai": {
        "label": "OpenAI GPT-4o",
        "provider": "openai",
        "model": "gpt-4o",
        "base_url": "https://api.openai.com/v1",
        "api_key_hint": "在 https://platform.openai.com 获取",
        "notes": "全球通用，需海外网络及付费账户",
    },
    "stepfun": {
        "label": "阶跃星辰 Step-1V（国内备选）",
        "provider": "openai",
        "model": "step-1v-32k",
        "base_url": "https://api.stepfun.com/v1",
        "api_key_hint": "在 https://platform.stepfun.com 注册获取",
        "notes": "国产多模态模型，支持中文医疗文档",
    },
    "ollama": {
        "label": "本地 Ollama（完全离线）",
        "provider": "ollama",
        "model": "qwen2-vl:7b",
        "base_url": "http://localhost:11434/v1",
        "api_key_hint": "本地运行无需 API Key，填任意字符（如 ollama）即可",
        "notes": "需本地安装 Ollama 并 `ollama pull qwen2-vl:7b`，完全私有化",
    },
}


def output_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _mask_key(s: str) -> str:
    """Mask a secret string, showing at most the first 4 chars."""
    if not s or len(s) <= 4:
        return "***"
    return s[:4] + "***"


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

    # When vision is not configured, include a step-by-step quick setup guide
    if not status.get("vision_configured"):
        status["vision_quick_setup"] = {
            "message": "配置视觉模型只需两步：① 选方案 ② 填 API Key",
            "step1_list_providers": "python3 setup.py list-vision-providers",
            "step2_example": "python3 setup.py set-vision --provider siliconflow --api-key sk-xxx",
            "step3_test": "python3 setup.py test-vision",
            "note": "--model 和 --base-url 有默认值，只需填 --provider 和 --api-key 即可完成配置",
        }

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
    """Configure vision model, with provider presets for common choices."""
    preset = VISION_PROVIDER_PRESETS.get(args.provider, {})

    # Resolve actual provider name (gemini maps to "openai" for API compat)
    resolved_provider = preset.get("provider", args.provider)

    # Fill defaults from preset when caller omits model / base-url
    model = args.model or preset.get("model", "")
    base_url = args.base_url or preset.get("base_url", "")

    if not model:
        output_json({
            "status": "error",
            "message": (
                f"未知的提供商预设 '{args.provider}'，且未提供 --model。"
                f" 已知预设: {', '.join(VISION_PROVIDER_PRESETS)}。"
                " 对于未知提供商，请同时指定 --model 和 --base-url。"
            ),
        })
        return

    cfg = load_config()
    cfg["vision"] = {
        "enabled": True,
        "provider": resolved_provider,
        "model": model,
        "api_key": args.api_key,
        "base_url": base_url,
    }
    save_config(cfg)
    # Mask API key in output
    display = {**cfg}
    display["vision"] = {**cfg["vision"], "api_key": _mask_key(cfg["vision"]["api_key"])}
    output_json({
        "status": "ok",
        "message": (
            f"多模态视觉模型已配置: {resolved_provider}/{model}"
            + (f"（使用 {args.provider} 预设）" if preset else "")
        ),
        "next_step": "运行 `python3 setup.py test-vision` 验证配置是否正常",
        "config": display,
    })


def cmd_list_vision_providers(args):
    """List all built-in vision provider presets with default model and base URL."""
    providers = []
    for key, p in VISION_PROVIDER_PRESETS.items():
        providers.append({
            "preset_name": key,
            "label": p["label"],
            "provider": p["provider"],
            "default_model": p["model"],
            "default_base_url": p["base_url"],
            "api_key_hint": p["api_key_hint"],
            "notes": p["notes"],
            "quick_command": f"python3 setup.py set-vision --provider {key} --api-key <YOUR_KEY>",
        })
    output_json({
        "status": "ok",
        "message": "以下是内置的视觉模型预设。使用 --provider <preset_name> 即可自动填入模型和 Base URL。",
        "providers": providers,
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
        display["vision"] = {**cfg["vision"], "api_key": _mask_key(cfg["vision"]["api_key"])}
    if cfg.get("embedding", {}).get("api_key"):
        display["embedding"] = {**cfg["embedding"], "api_key": _mask_key(cfg["embedding"]["api_key"])}
    if cfg.get("backend", {}).get("token"):
        display["backend"] = {**cfg.get("backend", {}), "token": _mask_key(cfg["backend"]["token"])}
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
        display["embedding"] = {**cfg["embedding"], "api_key": _mask_key(cfg["embedding"]["api_key"])}
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
    display_token = _mask_key(args.token)
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
    if getattr(args, "image", None):
        test_image = os.path.abspath(args.image)
    else:
        test_image = os.path.join(script_dir, "..", "references", "test-vision.jpg")
    if not os.path.isfile(test_image):
        output_json({
            "status": "error",
            "message": (
                f"测试图片不存在: {test_image}。"
                "请使用 --image /path/to/any_medical_image.jpg 指定一张本地图片进行测试，"
                "或将测试图片放置到 mediwise-health-tracker/references/test-vision.jpg。"
            )
        })
        return

    # Read and encode image
    with open(test_image, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("ascii")

    ext = os.path.splitext(test_image)[1].lower()
    mime_type = {"jpg": "image/jpeg", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp"}.get(ext, "image/jpeg")

    # Expected keywords that a working vision model must identify
    # Test image is a blood lipid report with: TC 7.23, LDL-C 4.33, diagnosis 高胆固醇血症
    # When using a custom image (--image), skip keyword check and just verify non-empty response
    using_custom_image = bool(getattr(args, "image", None))
    expected_keywords = [] if using_custom_image else ["7.23", "4.33", "胆固醇"]

    # Call vision model
    try:
        from smart_intake import _call_vision_llm
        prompt = (
            "请提取这张医疗检验报告图片中的所有检验项目和结果。"
            "输出格式：每行一个项目，格式为 项目名: 结果值 单位。"
            "最后列出诊断结论。"
        )
        text, _ = _call_vision_llm(prompt, img_b64, mime_type, vision_cfg)
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

    # Check if response contains expected keywords (skipped for custom images)
    matched = [kw for kw in expected_keywords if kw in text]
    missing = [kw for kw in expected_keywords if kw not in text]

    if using_custom_image or len(matched) >= 2:
        output_json({
            "status": "ok",
            "message": (
                "视觉模型测试通过！图片内容已成功识别。"
                if using_custom_image
                else f"视觉模型测试通过！成功识别 {len(matched)}/{len(expected_keywords)} 个关键指标。"
            ),
            "matched_keywords": matched if not using_custom_image else [],
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


def _table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,)
    ).fetchone()
    return bool(row)


# Union of all known tables — used to guard against unexpected names in SQL
_ALL_KNOWN_TABLES: frozenset[str] = MEDICAL_TABLES | LIFESTYLE_TABLES


def _validate_table_name(table_name: str) -> str:
    """Raise ValueError if table_name is not a recognised internal table.

    This is a defence-in-depth guard: callers already pass names from the
    MEDICAL_TABLES / LIFESTYLE_TABLES constants, so this should never fire
    in normal operation.  It prevents an accidentally wrong value from being
    silently interpolated into a SQL string.
    """
    if table_name not in _ALL_KNOWN_TABLES:
        raise ValueError(f"Unexpected table name: {table_name!r}")
    return table_name


def _table_count(conn, table_name):
    if not _table_exists(conn, table_name):
        return 0
    _validate_table_name(table_name)
    row = conn.execute(f"SELECT COUNT(*) AS c FROM {table_name}").fetchone()
    return int(row["c"] if row else 0)


def _table_columns(conn, table_name):
    _validate_table_name(table_name)
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table_name})").fetchall()]


def _copy_table_data(source_conn, target_conn, table_name):
    if not _table_exists(source_conn, table_name) or not _table_exists(target_conn, table_name):
        return {
            "table": table_name,
            "source_exists": _table_exists(source_conn, table_name),
            "target_exists": _table_exists(target_conn, table_name),
            "copied": 0,
            "before": _table_count(target_conn, table_name),
            "after": _table_count(target_conn, table_name),
            "skipped": "table_missing",
        }

    _validate_table_name(table_name)
    source_cols = _table_columns(source_conn, table_name)
    target_cols = _table_columns(target_conn, table_name)
    common_cols = [c for c in source_cols if c in target_cols]

    before = _table_count(target_conn, table_name)
    if not common_cols:
        return {
            "table": table_name,
            "source_exists": True,
            "target_exists": True,
            "copied": 0,
            "before": before,
            "after": before,
            "skipped": "no_common_columns",
        }

    # Column names come from PRAGMA table_info of our own schema — safe to interpolate.
    col_sql = ", ".join(common_cols)
    placeholders = ", ".join(["?"] * len(common_cols))
    rows = source_conn.execute(f"SELECT {col_sql} FROM {table_name}").fetchall()

    copied = 0
    for row in rows:
        values = [row[col] for col in common_cols]
        cur = target_conn.execute(
            f"INSERT OR IGNORE INTO {table_name} ({col_sql}) VALUES ({placeholders})",
            values,
        )
        copied += cur.rowcount

    after = _table_count(target_conn, table_name)
    return {
        "table": table_name,
        "source_exists": True,
        "target_exists": True,
        "copied": copied,
        "before": before,
        "after": after,
    }


def cmd_migrate_split_db(args):
    """Migrate legacy single DB data into split medical/lifestyle DBs."""
    cfg = load_config()
    legacy_db_path = os.path.abspath(cfg.get("db_path", DEFAULT_CONFIG["db_path"]))
    medical_db_path = os.path.abspath(get_medical_db_path())
    lifestyle_db_path = os.path.abspath(get_lifestyle_db_path())

    init_db("medical")
    init_db("lifestyle")

    if not os.path.exists(legacy_db_path):
        output_json({
            "status": "ok",
            "message": "未检测到旧版单库文件，无需迁移",
            "legacy_db_path": legacy_db_path,
            "medical_db_path": medical_db_path,
            "lifestyle_db_path": lifestyle_db_path,
            "migrated": False,
        })
        return

    source_conn = sqlite3.connect(legacy_db_path)
    source_conn.row_factory = sqlite3.Row
    medical_conn = sqlite3.connect(medical_db_path)
    medical_conn.row_factory = sqlite3.Row
    lifestyle_conn = sqlite3.connect(lifestyle_db_path)
    lifestyle_conn.row_factory = sqlite3.Row

    medical_details = []
    lifestyle_details = []
    try:
        for table in sorted(MEDICAL_TABLES):
            if legacy_db_path == medical_db_path:
                medical_details.append({
                    "table": table,
                    "source_exists": _table_exists(source_conn, table),
                    "target_exists": True,
                    "copied": 0,
                    "before": _table_count(medical_conn, table),
                    "after": _table_count(medical_conn, table),
                    "skipped": "same_source_target",
                })
            else:
                medical_details.append(_copy_table_data(source_conn, medical_conn, table))

        for table in sorted(LIFESTYLE_TABLES):
            if legacy_db_path == lifestyle_db_path:
                lifestyle_details.append({
                    "table": table,
                    "source_exists": _table_exists(source_conn, table),
                    "target_exists": True,
                    "copied": 0,
                    "before": _table_count(lifestyle_conn, table),
                    "after": _table_count(lifestyle_conn, table),
                    "skipped": "same_source_target",
                })
            else:
                lifestyle_details.append(_copy_table_data(source_conn, lifestyle_conn, table))

        medical_conn.commit()
        lifestyle_conn.commit()
    finally:
        source_conn.close()
        medical_conn.close()
        lifestyle_conn.close()

    output_json({
        "status": "ok",
        "message": "拆库迁移完成",
        "legacy_db_path": legacy_db_path,
        "medical_db_path": medical_db_path,
        "lifestyle_db_path": lifestyle_db_path,
        "medical": {
            "table_count": len(medical_details),
            "copied_rows": sum(d.get("copied", 0) for d in medical_details),
            "details": medical_details,
        },
        "lifestyle": {
            "table_count": len(lifestyle_details),
            "copied_rows": sum(d.get("copied", 0) for d in lifestyle_details),
            "details": lifestyle_details,
        },
    })


def cmd_migration_status(args):
    """Show split DB migration status by per-table row counts."""
    cfg = load_config()
    legacy_db_path = os.path.abspath(cfg.get("db_path", DEFAULT_CONFIG["db_path"]))
    medical_db_path = os.path.abspath(get_medical_db_path())
    lifestyle_db_path = os.path.abspath(get_lifestyle_db_path())

    status = {
        "status": "ok",
        "legacy_db_path": legacy_db_path,
        "legacy_exists": os.path.exists(legacy_db_path),
        "medical_db_path": medical_db_path,
        "medical_exists": os.path.exists(medical_db_path),
        "lifestyle_db_path": lifestyle_db_path,
        "lifestyle_exists": os.path.exists(lifestyle_db_path),
        "medical": {},
        "lifestyle": {},
    }

    legacy_conn = None
    medical_conn = None
    lifestyle_conn = None
    try:
        if status["legacy_exists"]:
            legacy_conn = sqlite3.connect(legacy_db_path)
            legacy_conn.row_factory = sqlite3.Row
        if status["medical_exists"]:
            medical_conn = sqlite3.connect(medical_db_path)
            medical_conn.row_factory = sqlite3.Row
        if status["lifestyle_exists"]:
            lifestyle_conn = sqlite3.connect(lifestyle_db_path)
            lifestyle_conn.row_factory = sqlite3.Row

        for table in sorted(MEDICAL_TABLES):
            legacy_count = _table_count(legacy_conn, table) if legacy_conn else None
            split_count = _table_count(medical_conn, table) if medical_conn else None
            status["medical"][table] = {
                "legacy": legacy_count,
                "split": split_count,
                "match": None if legacy_count is None or split_count is None else legacy_count == split_count,
            }

        for table in sorted(LIFESTYLE_TABLES):
            legacy_count = _table_count(legacy_conn, table) if legacy_conn else None
            split_count = _table_count(lifestyle_conn, table) if lifestyle_conn else None
            status["lifestyle"][table] = {
                "legacy": legacy_count,
                "split": split_count,
                "match": None if legacy_count is None or split_count is None else legacy_count == split_count,
            }

        medical_matched = [v["match"] for v in status["medical"].values() if v["match"] is not None]
        lifestyle_matched = [v["match"] for v in status["lifestyle"].values() if v["match"] is not None]

        status["summary"] = {
            "medical_tables": len(status["medical"]),
            "lifestyle_tables": len(status["lifestyle"]),
            "medical_match_ratio": (
                f"{sum(1 for x in medical_matched if x)}/{len(medical_matched)}" if medical_matched else "N/A"
            ),
            "lifestyle_match_ratio": (
                f"{sum(1 for x in lifestyle_matched if x)}/{len(lifestyle_matched)}" if lifestyle_matched else "N/A"
            ),
        }
    finally:
        if legacy_conn:
            legacy_conn.close()
        if medical_conn:
            medical_conn.close()
        if lifestyle_conn:
            lifestyle_conn.close()

    output_json(status)


def cmd_backup(args):
    """Pack databases and config into a portable tar.gz archive."""
    from config import DATA_DIR, CONFIG_PATH

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        output_path = os.path.abspath(f"mediwise-backup-{timestamp}.tar.gz")

    candidates = [
        os.path.join(DATA_DIR, "medical.db"),
        os.path.join(DATA_DIR, "lifestyle.db"),
        os.path.join(DATA_DIR, "health.db"),  # legacy single-db
        CONFIG_PATH,
    ]
    included = []
    missing = []
    for path in candidates:
        if os.path.exists(path):
            included.append(path)
        else:
            missing.append(path)

    if not included:
        output_json({
            "status": "error",
            "message": "数据目录中没有找到任何数据库或配置文件，请先初始化。",
            "data_dir": DATA_DIR,
        })
        sys.exit(1)

    with tarfile.open(output_path, "w:gz") as tar:
        for path in included:
            # Store files with path relative to DATA_DIR so restore is location-independent
            arcname = os.path.relpath(path, DATA_DIR)
            tar.add(path, arcname=arcname)

    output_json({
        "status": "ok",
        "message": f"备份已保存到 {output_path}",
        "output": output_path,
        "files": [os.path.relpath(p, DATA_DIR) for p in included],
        "skipped": [os.path.relpath(p, DATA_DIR) for p in missing],
    })


def cmd_restore(args):
    """Restore databases and config from a tar.gz archive created by backup."""
    from config import DATA_DIR, CONFIG_PATH
    from health_db import ensure_db

    input_path = os.path.abspath(args.input)
    if not os.path.exists(input_path):
        output_json({
            "status": "error",
            "message": f"备份文件不存在: {input_path}",
        })
        sys.exit(1)

    if not tarfile.is_tarfile(input_path):
        output_json({
            "status": "error",
            "message": f"文件不是有效的 tar 归档: {input_path}",
        })
        sys.exit(1)

    os.makedirs(DATA_DIR, exist_ok=True)

    restored = []
    with tarfile.open(input_path, "r:gz") as tar:
        for member in tar.getmembers():
            # Security: strip any leading / or .. components
            safe_name = os.path.normpath(member.name)
            if safe_name.startswith(".."):
                continue
            dest = os.path.join(DATA_DIR, safe_name)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            source = tar.extractfile(member)
            if source is None:
                continue
            with open(dest, "wb") as f:
                f.write(source.read())
            restored.append(safe_name)

    # Apply any pending schema migrations automatically
    try:
        ensure_db()
        migration_ok = True
        migration_error = None
    except Exception as e:
        migration_ok = False
        migration_error = str(e)

    result = {
        "status": "ok" if migration_ok else "warning",
        "message": "数据恢复完成，Schema 已自动升级到最新版本。" if migration_ok
                   else f"数据已恢复，但 Schema 自动升级失败: {migration_error}",
        "data_dir": DATA_DIR,
        "restored_files": restored,
    }
    if migration_error:
        result["migration_error"] = migration_error
    output_json(result)


def main():
    parser = argparse.ArgumentParser(description="MediWise Health Tracker 配置管理")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="检查配置状态")
    sub.add_parser("init", help="初始化默认配置")

    p = sub.add_parser("set-db-path", help="设置数据库路径")
    p.add_argument("--path", required=True)

    p = sub.add_parser("set-vision", help="配置多模态视觉模型（--model/--base-url 对内置预设可省略）")
    p.add_argument("--provider", required=True,
                   help="提供商预设名或自定义名: siliconflow / gemini / openai / stepfun / ollama，"
                        "或任意自定义值（需同时指定 --model 和 --base-url）")
    p.add_argument("--model", default="", help="模型名称（内置预设会自动填入，可省略）")
    p.add_argument("--api-key", required=True, help="API Key")
    p.add_argument("--base-url", default="", help="API Base URL（内置预设会自动填入，可省略）")

    sub.add_parser("list-vision-providers", help="列出所有内置视觉模型预设及默认配置")

    sub.add_parser("disable-vision", help="禁用多模态视觉模型")
    p = sub.add_parser("test-vision", help="测试视觉模型是否能正确识别医疗报告图片")
    p.add_argument("--image", default="", help="自定义测试图片路径（可选，默认使用内置测试图片）")
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

    sub.add_parser("migrate-split-db", help="将旧版单库数据迁移到 medical/lifestyle 双库")
    sub.add_parser("migration-status", help="查看拆库迁移状态和表行数对比")

    p = sub.add_parser("backup", help="将数据库和配置打包为可迁移的 tar.gz 备份文件")
    p.add_argument("--output", default="", help="输出路径（默认: ./mediwise-backup-<时间戳>.tar.gz）")

    p = sub.add_parser("restore", help="从备份文件恢复数据库和配置，并自动升级 Schema")
    p.add_argument("--input", required=True, help="备份文件路径（.tar.gz）")

    args = parser.parse_args()
    commands = {
        "check": cmd_check, "init": cmd_init, "set-db-path": cmd_set_db_path,
        "set-vision": cmd_set_vision, "disable-vision": cmd_disable_vision,
        "list-vision-providers": cmd_list_vision_providers,
        "test-vision": cmd_test_vision,
        "show": cmd_show, "set-embedding": cmd_set_embedding,
        "test-embedding": cmd_test_embedding,
        "check-pdf": cmd_check_pdf, "set-pdf-engine": cmd_set_pdf_engine,
        "set-backend": cmd_set_backend, "disable-backend": cmd_disable_backend,
        "set-privacy": cmd_set_privacy,
        "migrate-split-db": cmd_migrate_split_db,
        "migration-status": cmd_migration_status,
        "backup": cmd_backup,
        "restore": cmd_restore,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
