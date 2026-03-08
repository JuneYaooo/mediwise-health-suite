"""Configuration management for MediWise Health Tracker.

Manages config file at the platform-appropriate location:
- Windows: %LOCALAPPDATA%/mediwise/config.json
- macOS:   ~/Library/Application Support/mediwise/config.json
- Linux:   $XDG_DATA_HOME/mediwise/config.json
"""

from __future__ import annotations

import os
import json
import platform

_KEYRING_SERVICE = "mediwise-health-tracker"
_KEYRING_SENTINEL = "__KEYRING__"

# Secret fields: (section, key) pairs
_SECRET_FIELDS = [
    ("vision", "api_key"),
    ("llm", "api_key"),
    ("embedding", "api_key"),
    ("backend", "token"),
    ("wearable_huawei", "client_secret"),
    ("wearable_huawei", "access_token"),
    ("wearable_huawei", "refresh_token"),
    ("wearable_zepp", "client_secret"),
    ("wearable_zepp", "access_token"),
    ("wearable_zepp", "refresh_token"),
]


def _keyring_available():
    """Check if keyring is usable."""
    try:
        import keyring
        # Test with a probe read to ensure backend works
        keyring.get_password(_KEYRING_SERVICE, "__probe__")
        return True
    except Exception:
        return False


def _store_secret(section, key, value):
    """Store a secret in OS keyring. Returns True on success."""
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, f"{section}.{key}", value)
        return True
    except Exception:
        return False


def _retrieve_secret(section, key):
    """Retrieve a secret from OS keyring. Returns None on failure."""
    try:
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, f"{section}.{key}")
    except Exception:
        return None


def _default_data_dir():
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            base = os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "mediwise")
    elif system == "Darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "mediwise")
    else:
        base = os.environ.get("XDG_DATA_HOME")
        if not base:
            base = os.path.join(os.path.expanduser("~"), ".local", "share")
        return os.path.join(base, "mediwise")


DATA_DIR = os.environ.get("MEDIWISE_DATA_DIR", _default_data_dir())
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

DEFAULT_CONFIG = {
    "db_path": os.path.join(DATA_DIR, "health.db"),
    "timezone": "Asia/Shanghai",
    "vision": {
        "enabled": False,
        "provider": "",
        "model": "",
        "api_key": "",
        "base_url": ""
    },
    "llm": {
        "provider": "",
        "model": "",
        "api_key": "",
        "base_url": ""
    },
    "embedding": {
        "provider": "auto",
        "model": "",
        "api_key": "",
        "base_url": "",
        "dimensions": 0
    },
    "backend": {
        "enabled": False,
        "base_url": "",
        "token": ""
    },
    "privacy": {
        "default_level": "anonymized"
    },
    "wearable": {
        "sync_interval_minutes": 30,
        "auto_check_after_sync": True,
    },
    "monitor": {
        "alert_cooldown_hours": 24,
        "trend_window_days": 7,
        "daily_digest_enabled": True,
    },
    "pdf": {
        "ocr_engine": "auto"  # "auto" | "mineru" | "paddleocr" | "vision"
    }
}


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_config():
    """Load config from file. Returns default config if file doesn't exist.

    Secrets stored in keyring are transparently restored from the sentinel value.
    On first load, existing plaintext secrets are migrated to keyring if available.
    """
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        # Merge with defaults for any missing keys
        merged = {**DEFAULT_CONFIG, **cfg}
        for key, default_val in DEFAULT_CONFIG.items():
            if isinstance(default_val, dict):
                merged[key] = {**default_val, **cfg.get(key, {})}
            else:
                merged[key] = cfg.get(key, default_val)

        # Restore secrets from keyring where sentinel is present
        migrated = False
        for section, key in _SECRET_FIELDS:
            val = merged.get(section, {}).get(key, "")
            if val == _KEYRING_SENTINEL:
                real = _retrieve_secret(section, key)
                if real is not None:
                    merged[section][key] = real
                else:
                    # Keyring lost — clear sentinel so user knows to reconfigure
                    merged[section][key] = ""
            elif val and val != _KEYRING_SENTINEL:
                # Plaintext secret found — try to migrate to keyring
                if _keyring_available() and _store_secret(section, key, val):
                    cfg.setdefault(section, {})[key] = _KEYRING_SENTINEL
                    migrated = True

        if migrated:
            # Persist the sentinel values back to config file
            ensure_data_dir()
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)

        return merged
    return {**DEFAULT_CONFIG}


def save_config(config):
    """Save config to file. Secrets are stored in keyring if available."""
    ensure_data_dir()
    # Work on a copy to avoid mutating the caller's dict
    to_save = json.loads(json.dumps(config, ensure_ascii=False))

    has_plaintext_secrets = False
    if _keyring_available():
        for section, key in _SECRET_FIELDS:
            val = to_save.get(section, {}).get(key, "")
            if val and val != _KEYRING_SENTINEL:
                if _store_secret(section, key, val):
                    to_save[section][key] = _KEYRING_SENTINEL
    else:
        for section, key in _SECRET_FIELDS:
            val = to_save.get(section, {}).get(key, "")
            if val and val != _KEYRING_SENTINEL:
                has_plaintext_secrets = True
                break

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(to_save, f, ensure_ascii=False, indent=2)

    if has_plaintext_secrets:
        import sys
        print(f"⚠ 警告: 系统 keyring 不可用，API 密钥以明文存储在 {CONFIG_PATH}，请注意保护文件权限。", file=sys.stderr)


def config_exists():
    """Check if config file exists."""
    return os.path.exists(CONFIG_PATH)


def get_db_path():
    """Get database path from config or environment."""
    env_path = os.environ.get("MEDIWISE_DB_PATH")
    if env_path:
        return env_path
    cfg = load_config()
    return cfg.get("db_path", DEFAULT_CONFIG["db_path"])


def get_vision_config():
    """Get vision model config."""
    cfg = load_config()
    return cfg.get("vision", DEFAULT_CONFIG["vision"])


def get_llm_config():
    """Get LLM config for text extraction. Falls back to vision config if not set."""
    cfg = load_config()
    llm = cfg.get("llm", {})
    if llm.get("provider") and llm.get("model") and llm.get("api_key"):
        return llm
    return get_vision_config()


def get_embedding_config():
    """Get embedding config."""
    cfg = load_config()
    return cfg.get("embedding", DEFAULT_CONFIG["embedding"])


def get_backend_config():
    """Get backend API config."""
    cfg = load_config()
    return cfg.get("backend", DEFAULT_CONFIG["backend"])


def is_backend_mode():
    """Check if backend API mode is enabled."""
    backend = get_backend_config()
    return backend.get("enabled", False) and bool(backend.get("base_url"))


def check_config_status():
    """Check configuration status and return a report.

    Returns a dict with:
    - initialized: bool, whether config file exists
    - db_path: str, current database path
    - db_exists: bool, whether database file exists
    - vision_configured: bool, whether vision model is configured
    - vision: dict, vision config details
    - pdf_ocr_engine: str, preferred PDF OCR engine
    - pdf_tools: dict, availability of PDF extraction tools
    - issues: list of strings describing what needs attention
    """
    ensure_data_dir()
    cfg = load_config()
    db_path = get_db_path()
    vision = cfg.get("vision", DEFAULT_CONFIG["vision"])

    issues = []

    if not config_exists():
        issues.append("配置文件不存在，需要初始化")

    if not os.path.exists(db_path):
        issues.append("数据库文件不存在，将在首次使用时自动创建")

    vision_configured = (
        vision.get("enabled", False)
        and vision.get("provider", "")
        and vision.get("model", "")
        and vision.get("api_key", "")
    )
    if not vision_configured:
        issues.append("多模态视觉模型未配置（可选，用于识别体检报告图片/PDF）")

    embedding = cfg.get("embedding", DEFAULT_CONFIG["embedding"])
    embedding_provider = embedding.get("provider", "auto")
    embedding_status = "auto"
    if embedding_provider == "none":
        embedding_status = "disabled"
    elif embedding_provider == "siliconflow":
        if embedding.get("api_key"):
            embedding_status = "siliconflow_api"
        else:
            embedding_status = "siliconflow_no_key"
            issues.append("硅基智能 Embedding API 已配置但缺少 API Key")
    elif embedding_provider == "local":
        embedding_status = "local"
    else:
        embedding_status = "auto"

    pdf_ocr = cfg.get("pdf", DEFAULT_CONFIG["pdf"]).get("ocr_engine", "auto")
    pdf_tools = check_pdf_tools()

    # Add PDF-related issues
    has_any_ocr = pdf_tools["mineru"] or pdf_tools["paddleocr"]
    if not has_any_ocr and not vision_configured:
        issues.append(
            "扫描件 PDF 处理能力不足：MinerU、PaddleOCR 均未安装且视觉模型未配置。"
            "建议运行 setup.py check-pdf 查看安装指引"
        )

    return {
        "initialized": config_exists(),
        "config_path": CONFIG_PATH,
        "data_dir": DATA_DIR,
        "db_path": db_path,
        "db_exists": os.path.exists(db_path),
        "vision_configured": vision_configured,
        "vision": vision,
        "embedding_provider": embedding_provider,
        "embedding_status": embedding_status,
        "pdf_ocr_engine": pdf_ocr,
        "pdf_tools": pdf_tools,
        "issues": issues
    }


def get_pdf_config():
    """Get PDF OCR engine config."""
    cfg = load_config()
    return cfg.get("pdf", DEFAULT_CONFIG["pdf"])


def check_pdf_tools():
    """Check availability of PDF extraction tools. Returns dict of tool status."""
    import shutil

    tools = {
        "pdfplumber": False,
        "PyPDF2": False,
        "PyMuPDF": False,
        "mineru": False,
        "paddleocr": False,
    }
    try:
        import pdfplumber  # noqa: F401
        tools["pdfplumber"] = True
    except ImportError:
        pass
    try:
        import PyPDF2  # noqa: F401
        tools["PyPDF2"] = True
    except ImportError:
        pass
    try:
        import fitz  # noqa: F401
        tools["PyMuPDF"] = True
    except ImportError:
        pass
    # MinerU: check CLI first, then Python API
    if shutil.which("magic-pdf"):
        tools["mineru"] = True
    else:
        try:
            import magic_pdf  # noqa: F401
            tools["mineru"] = True
        except ImportError:
            pass
    try:
        from paddleocr import PaddleOCR  # noqa: F401
        tools["paddleocr"] = True
    except ImportError:
        pass
    return tools
