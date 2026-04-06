"""Device management CLI for wearable-sync.

Manages wearable device registration, configuration, and connection testing.
"""

from __future__ import annotations

import sys
import os
import json
import argparse
import getpass

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from path_setup import setup_mediwise_path
setup_mediwise_path()
sys.path.insert(0, os.path.dirname(__file__))

import health_db
from providers.gadgetbridge import GadgetbridgeProvider
from providers.huawei import HuaweiProvider
from providers.zepp import ZeppProvider
from providers.openwearables import OpenWearablesProvider
from providers.apple_health import AppleHealthProvider
from providers.garmin import GarminProvider

PROVIDERS = {
    "gadgetbridge":  GadgetbridgeProvider,
    "huawei":        HuaweiProvider,
    "zepp":          ZeppProvider,
    "openwearables":  OpenWearablesProvider,
    "apple_health":  AppleHealthProvider,
    "garmin":        GarminProvider,
}

# Providers that use a local export file (--export-path) for authentication
_FILE_EXPORT_PROVIDERS = {"gadgetbridge", "apple_health"}


def _get_provider(name):
    cls = PROVIDERS.get(name)
    if not cls:
        return None
    return cls()


def add_device(args):
    """Register a new wearable device for a member."""
    health_db.ensure_db()

    if args.provider not in PROVIDERS:
        health_db.output_json({
            "status": "error",
            "message": f"不支持的 Provider: {args.provider}，支持: {', '.join(PROVIDERS.keys())}"
        })
        return

    provider = _get_provider(args.provider)

    with health_db.transaction(domain="medical") as conn:
        # Verify member exists
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            health_db.output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

    with health_db.transaction(domain="lifestyle") as conn:
        device_id = health_db.generate_id()
        now = health_db.now_iso()
        supported = json.dumps(provider.get_supported_metrics())
        conn.execute(
            """INSERT INTO wearable_devices
               (id, member_id, provider, device_name, config, supported_metrics, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (device_id, args.member_id, args.provider,
             args.device_name or "", "{}", supported, now, now)
        )
        conn.commit()

    health_db.output_json({
        "status": "ok",
        "message": f"设备已添加: {args.device_name or args.provider}",
        "device_id": device_id,
        "provider": args.provider,
        "supported_metrics": provider.get_supported_metrics(),
    })


def list_devices(args):
    """List registered wearable devices for a member."""
    health_db.ensure_db()
    conn = health_db.get_lifestyle_connection()
    try:
        rows = conn.execute(
            """SELECT * FROM wearable_devices
               WHERE member_id=? AND is_deleted=0
               ORDER BY created_at""",
            (args.member_id,)
        ).fetchall()
        devices = health_db.rows_to_list(rows)
        # Parse JSON fields for readability
        for d in devices:
            try:
                d["supported_metrics"] = json.loads(d.get("supported_metrics") or "[]")
            except (json.JSONDecodeError, TypeError):
                pass
            # Mask sensitive config
            try:
                cfg = json.loads(d.get("config") or "{}")
                for k in ("access_token", "refresh_token", "client_secret", "password"):
                    if k in cfg:
                        cfg[k] = "***"
                d["config"] = cfg
            except (json.JSONDecodeError, TypeError):
                pass
        health_db.output_json({"status": "ok", "count": len(devices), "devices": devices})
    finally:
        conn.close()


def remove_device(args):
    """Soft-delete a wearable device."""
    health_db.ensure_db()
    with health_db.transaction(domain="lifestyle") as conn:
        row = conn.execute(
            "SELECT * FROM wearable_devices WHERE id=? AND is_deleted=0",
            (args.device_id,)
        ).fetchone()
        if not row:
            health_db.output_json({"status": "error", "message": f"未找到设备: {args.device_id}"})
            return
        conn.execute(
            "UPDATE wearable_devices SET is_deleted=1, is_active=0, updated_at=? WHERE id=?",
            (health_db.now_iso(), args.device_id)
        )
        conn.commit()
    health_db.output_json({"status": "ok", "message": "设备已移除"})


def auth_device(args):
    """Configure authentication/connection for a device.

    For Gadgetbridge: --export-path /path/to/Gadgetbridge.db
    For OAuth providers: --client-id, --client-secret, --redirect-uri
    """
    health_db.ensure_db()
    conn = health_db.get_lifestyle_connection()
    try:
        row = conn.execute(
            "SELECT * FROM wearable_devices WHERE id=? AND is_deleted=0",
            (args.device_id,)
        ).fetchone()
        if not row:
            health_db.output_json({"status": "error", "message": f"未找到设备: {args.device_id}"})
            return
        device = dict(row)
    finally:
        conn.close()

    # Build config based on provider type
    try:
        existing_config = json.loads(device.get("config") or "{}")
    except (json.JSONDecodeError, TypeError):
        existing_config = {}

    provider_name = device["provider"]

    if provider_name in _FILE_EXPORT_PROVIDERS:
        if not args.export_path:
            _file_hints = {
                "gadgetbridge": "Gadgetbridge SQLite 导出文件路径（Gadgetbridge.db）",
                "apple_health": "Apple 健康导出文件路径（export.xml 或 export.zip）",
            }
            hint = _file_hints.get(provider_name, "导出文件路径")
            health_db.output_json({
                "status": "error",
                "message": f"此 Provider 需要指定 --export-path 参数：{hint}"
            })
            return
        export_path = os.path.abspath(args.export_path)
        if not os.path.isfile(export_path):
            health_db.output_json({
                "status": "error",
                "message": f"文件不存在: {export_path}"
            })
            return
        existing_config["export_path"] = export_path
    elif provider_name == "garmin":
        # Resolve password: --prompt-password > env var > --password (plaintext, discouraged)
        password = args.password
        if getattr(args, "prompt_password", False):
            if not sys.stdin.isatty():
                health_db.output_json({
                    "status": "error",
                    "message": "无法使用 --prompt-password：当前环境没有终端（non-TTY）。\n"
                               "请改用环境变量：export GARMIN_PASSWORD='你的密码'",
                })
                return
            password = getpass.getpass("请输入 Garmin Connect 密码（输入不回显）：")
        elif not password:
            password = os.environ.get("GARMIN_PASSWORD", "")

        if not args.username or not password:
            health_db.output_json({
                "status": "error",
                "message": (
                    "佳明（Garmin）设备需要提供 Garmin Connect 账号信息：\n"
                    "  --username       你的 Garmin Connect 登录邮箱\n"
                    "  --prompt-password  交互式输入密码（推荐，密码不经过模型）\n"
                    "  或设置环境变量：   export GARMIN_PASSWORD='你的密码'\n"
                    "  --tokenstore     存放登录令牌的目录路径（可选，配置后登录一次即可）"
                )
            })
            return
        existing_config["username"] = args.username
        existing_config["password"] = password
        if args.tokenstore:
            existing_config["tokenstore"] = args.tokenstore
    elif provider_name == "zepp":
        # Resolve password: --prompt-password > env var > --password (plaintext, discouraged)
        password = args.password
        if getattr(args, "prompt_password", False):
            if not sys.stdin.isatty():
                health_db.output_json({
                    "status": "error",
                    "message": "无法使用 --prompt-password：当前环境没有终端（non-TTY）。\n"
                               "请改用环境变量：export ZEPP_PASSWORD='你的密码'",
                })
                return
            password = getpass.getpass("请输入 Zepp / 小米账号密码（输入不回显）：")
        elif not password:
            password = os.environ.get("ZEPP_PASSWORD", "")

        if not args.username or not password:
            health_db.output_json({
                "status": "error",
                "message": (
                    "Zepp / 小米设备需要提供账号信息：\n"
                    "  --username       小米运动健康 / Zepp Life 登录邮箱\n"
                    "  --prompt-password  交互式输入密码（推荐，密码不经过模型）\n"
                    "  或设置环境变量：   export ZEPP_PASSWORD='你的密码'\n"
                    "登录成功后 token 会自动缓存，下次同步无需重新输入密码"
                )
            })
            return
        existing_config["username"] = args.username
        existing_config["password"] = password
        # Clear cached token to force fresh login with new credentials
        existing_config.pop("app_token", None)
        existing_config.pop("user_id", None)
    else:
        # OAuth-based providers
        if args.client_id:
            existing_config["client_id"] = args.client_id
        if args.client_secret:
            existing_config["client_secret"] = args.client_secret
        if args.redirect_uri:
            existing_config["redirect_uri"] = args.redirect_uri

    # Test connection
    provider = _get_provider(provider_name)
    try:
        valid = provider.authenticate(existing_config)
    except NotImplementedError as e:
        health_db.output_json({"status": "error", "message": str(e)})
        return
    except RuntimeError as e:
        health_db.output_json({"status": "error", "message": str(e)})
        return

    if not valid:
        health_db.output_json({
            "status": "error",
            "message": "认证失败，请检查配置是否正确"
        })
        return

    # Save config (provider.authenticate() may have written back new tokens, e.g. Zepp app_token)
    with health_db.transaction(domain="lifestyle") as conn:
        conn.execute(
            "UPDATE wearable_devices SET config=?, updated_at=? WHERE id=?",
            (json.dumps(existing_config, ensure_ascii=False), health_db.now_iso(), args.device_id)
        )
        conn.commit()

    health_db.output_json({
        "status": "ok",
        "message": f"{provider_name} 设备配置已更新并验证通过",
        "device_id": args.device_id,
    })


def auth_callback(args):
    """Handle OAuth callback for providers that use authorization codes."""
    health_db.ensure_db()
    conn = health_db.get_lifestyle_connection()
    try:
        row = conn.execute(
            "SELECT * FROM wearable_devices WHERE id=? AND is_deleted=0",
            (args.device_id,)
        ).fetchone()
        if not row:
            health_db.output_json({"status": "error", "message": f"未找到设备: {args.device_id}"})
            return
        device = dict(row)
    finally:
        conn.close()

    provider_name = device["provider"]
    if provider_name == "gadgetbridge":
        health_db.output_json({"status": "error", "message": "Gadgetbridge 不需要 OAuth 回调"})
        return

    # OAuth providers are stubs for now
    health_db.output_json({
        "status": "error",
        "message": f"{provider_name} Provider 的 OAuth 回调尚未实现（第二阶段）"
    })


def test_device(args):
    """Test connection for a registered device."""
    health_db.ensure_db()
    conn = health_db.get_lifestyle_connection()
    try:
        row = conn.execute(
            "SELECT * FROM wearable_devices WHERE id=? AND is_deleted=0",
            (args.device_id,)
        ).fetchone()
        if not row:
            health_db.output_json({"status": "error", "message": f"未找到设备: {args.device_id}"})
            return
        device = dict(row)
    finally:
        conn.close()

    try:
        config = json.loads(device.get("config") or "{}")
    except (json.JSONDecodeError, TypeError):
        config = {}

    provider = _get_provider(device["provider"])
    try:
        ok = provider.test_connection(config)
        health_db.output_json({
            "status": "ok" if ok else "error",
            "message": "连接测试通过" if ok else "连接测试失败",
            "device_id": args.device_id,
            "provider": device["provider"],
        })
    except NotImplementedError as e:
        health_db.output_json({"status": "error", "message": str(e)})
    except RuntimeError as e:
        health_db.output_json({"status": "error", "message": str(e)})


def main():
    parser = argparse.ArgumentParser(description="可穿戴设备管理")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="添加设备")
    p_add.add_argument("--member-id", required=True)
    p_add.add_argument("--provider", required=True, choices=list(PROVIDERS.keys()))
    p_add.add_argument("--device-name", default=None, help="设备名称")

    p_list = sub.add_parser("list", help="查看设备")
    p_list.add_argument("--member-id", required=True)

    p_remove = sub.add_parser("remove", help="移除设备")
    p_remove.add_argument("--device-id", required=True)

    p_auth = sub.add_parser("auth", help="配置设备认证")
    p_auth.add_argument("--device-id", required=True)
    p_auth.add_argument("--export-path", default=None, help="Gadgetbridge/Apple Health 导出文件路径")
    p_auth.add_argument("--username", default=None, help="Garmin/Zepp Connect 登录邮箱")
    p_auth.add_argument("--password", default=None, help="密码（明文，不推荐；建议用 --prompt-password）")
    p_auth.add_argument("--prompt-password", action="store_true",
                        help="交互式输入密码（不回显，不经过模型/日志，推荐）")
    p_auth.add_argument("--tokenstore", default=None, help="Garmin token 缓存目录（可选，避免重复登录）")
    p_auth.add_argument("--client-id", default=None, help="OAuth Client ID")
    p_auth.add_argument("--client-secret", default=None, help="OAuth Client Secret")
    p_auth.add_argument("--redirect-uri", default=None, help="OAuth Redirect URI")

    p_callback = sub.add_parser("auth-callback", help="OAuth 回调")
    p_callback.add_argument("--device-id", required=True)
    p_callback.add_argument("--code", required=True, help="Authorization code")

    p_test = sub.add_parser("test", help="测试设备连接")
    p_test.add_argument("--device-id", required=True)

    args = parser.parse_args()
    commands = {
        "add": add_device,
        "list": list_devices,
        "remove": remove_device,
        "auth": auth_device,
        "auth-callback": auth_callback,
        "test": test_device,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
