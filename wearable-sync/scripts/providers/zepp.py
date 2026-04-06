"""Zepp Health / Xiaomi Mi Fitness provider for wearable-sync.

Fetches data from the Huami/Zepp cloud using account email + password.

## 支持的账号类型

  ✅ 老版 Amazfit 账号 / Zepp Life 原生账号（直接在 Zepp Life 注册）
  ⚠️  小米账号（Xiaomi Account）—— 大部分情况下无法使用（见下方说明）

## 重要限制（2025年现状）

小米正在将小米手环用户从 Huami 身份系统迁移到小米统一账号体系。
迁移后的账号在老版 tokenRefresh 端点上会收到 Error 0117 / 0106，
因为该端点不认识小米账号体系的凭据。

  - 用小米账号登录的小米运动健康 (Mi Fitness) 用户 → ❌ 此 Provider 无法使用
  - 老版 Zepp Life / Amazfit 原生账号（非小米账号注册）→ ✅ 可以尝试

对于小米手环用户，推荐改用 Gadgetbridge Provider（本地蓝牙同步 + SQLite 导出），
稳定性和隐私性都更好。详见: https://gadgetbridge.org/

## 支持设备

任何用 Zepp Life / Mi Fitness App 配对的设备：
  Xiaomi Mi Band 6 / 7 / 8 / 9, Redmi Band, Amazfit Bip / GTR / GTS / T-Rex 等

## 认证流程（非官方 Huami 端点）

  第一步：账号密码 → login_token + user_id
  第二步：login_token → app_token
  第三步：用 app_token 调用数据 API

Token 缓存在设备配置中，后续同步无需重新登录（除非 token 失效）。

## 配置项

  username    账号邮箱（必填）
  password    账号密码（必填，明文存储在本地）
  app_token   缓存的 Bearer token（首次登录后自动写入）
  user_id     Huami 用户 ID（首次登录后自动写入）
  region      "cn"（默认）或 "global"
"""

from __future__ import annotations

import hashlib
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta

from .base import BaseProvider, RawMetric

logger = logging.getLogger(__name__)

_LOGIN_URL    = "https://app-account.huami.com/attaches/app/v2/tokenRefresh"
_EXCHANGE_URL = "https://account.huami.com/v2/client/login"

_API_BASE = {
    "cn":     "https://api-mifit-cn.huami.com/v1",
    "global": "https://api-mifit.huami.com/v1",
}

_APP_NAME    = "com.xiaomi.hm.health"
_APP_VERSION = "7.20.0"   # keep reasonably current to avoid version-rejection

_ENDPOINTS = {
    "heart_rate":   "data/heart_rate",
    "steps":        "data/steps",
    "blood_oxygen": "data/spo2",
    "sleep":        "data/sleep",
    "stress":       "data/stress",
}

# Error codes returned in the Huami login response
_ERR_MIGRATED  = {"0117"}           # account migrated to Xiaomi identity system
_ERR_BAD_CREDS = {"0106", "0103"}   # wrong password or account not found


def _md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def _post_form(url: str, fields: dict) -> dict:
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


class ZeppProvider(BaseProvider):
    """Provider for Zepp Health / Mi Fitness cloud (Xiaomi Mi Band, Amazfit).

    Works with legacy Amazfit / Zepp Life accounts.
    Does NOT work with Xiaomi Account (小米账号) — see module docstring.
    """

    provider_name = "zepp"

    def __init__(self):
        self._app_token: str = ""
        self._user_id:   str = ""
        self._username:  str = ""
        self._password:  str = ""
        self._region:    str = "cn"

    # ------------------------------------------------------------------ auth

    def authenticate(self, config: dict) -> bool:
        """Authenticate using email + password, or reuse a cached app_token."""
        self._username  = config.get("username",  "")
        self._password  = config.get("password",  "")
        self._app_token = config.get("app_token", "")
        self._user_id   = config.get("user_id",   "")
        self._region    = config.get("region", "cn")

        if self._app_token and self._user_id:
            return True     # fast path: cached token

        if not self._username or not self._password:
            logger.error("Zepp/小米: 未找到 app_token，也未提供 username/password")
            return False

        return self._login(config)

    def _login(self, config: dict) -> bool:
        """Two-step Huami login. Writes app_token / user_id back into config."""
        try:
            device_id = str(uuid.uuid4())

            # Step 1: credentials → login_token
            resp1 = _post_form(_LOGIN_URL, {
                "country_code": "CN" if self._region == "cn" else "US",
                "user":         self._username,
                "password":     _md5(self._password),
                "client_id":    "HuaMi",
                "token_type":   "access_token",
                "app_name":     _APP_NAME,
                "app_version":  _APP_VERSION,
                "code":         "",
            })

            err_code = str(resp1.get("error_code", resp1.get("errorCode", "")))
            if err_code in _ERR_MIGRATED:
                raise RuntimeError(
                    "此账号已迁移至小米账号体系（Error 0117），Zepp Provider 无法使用。\n"
                    "请改用 Gadgetbridge Provider：\n"
                    "  1. Android 安装 Gadgetbridge，用它配对小米手环\n"
                    "  2. MediWise 添加 gadgetbridge 设备，指定 --export-path\n"
                    "  详见: https://gadgetbridge.org/"
                )
            if err_code in _ERR_BAD_CREDS:
                raise RuntimeError(f"账号或密码错误（Error {err_code}），请检查后重试。")

            token_info  = resp1.get("token_info", {})
            login_token = token_info.get("login_token", "")
            user_id     = token_info.get("user_id",     "")
            if not login_token or not user_id:
                raise RuntimeError(f"登录第一步未返回 token，响应: {resp1}")

            # Step 2: login_token → app_token
            third_name = "huami_xiaomi_name" if self._region == "cn" else "huami_phone_name"
            resp2 = _post_form(_EXCHANGE_URL, {
                "grant_type":   "access_token",
                "country_code": "CN" if self._region == "cn" else "US",
                "code":         login_token,
                "user_id":      user_id,
                "third_name":   third_name,
                "lang":         "zh_CN" if self._region == "cn" else "en_US",
                "device_id":    device_id,
                "device_model": "phone",
                "app_name":     _APP_NAME,
                "source":       "login",
                "app_version":  _APP_VERSION,
            })

            token_info2 = resp2.get("token_info", {})
            app_token   = token_info2.get("app_token", "")
            uid         = token_info2.get("user_id", user_id)
            if not app_token:
                raise RuntimeError(f"登录第二步未返回 app_token，响应: {resp2}")

            self._app_token     = app_token
            self._user_id       = uid
            config["app_token"] = app_token
            config["user_id"]   = uid
            logger.info("Zepp/小米: 登录成功，user_id=%s", uid)
            return True

        except RuntimeError:
            raise   # propagate user-readable messages as-is
        except (urllib.error.URLError, urllib.error.HTTPError,
                json.JSONDecodeError, KeyError) as e:
            logger.error("Zepp/小米: 登录失败: %s", e)
            return False

    # ------------------------------------------------------------------ data API

    @property
    def _api_base(self) -> str:
        return _API_BASE.get(self._region, _API_BASE["cn"])

    def _get(self, path: str, params: dict) -> dict | None:
        query = urllib.parse.urlencode(params)
        url   = f"{self._api_base}/{path}?{query}"
        req   = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._app_token}",
                "apptoken":      self._app_token,
                "Accept":        "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401:
                logger.warning("Zepp/小米: token 已失效，下次同步将重新登录")
                self._app_token = ""    # force re-login next sync
            else:
                logger.error("Zepp/小米: API HTTP %s (%s)", e.code, path)
            return None
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.error("Zepp/小米: 请求失败 %s: %s", path, e)
            return None

    # ------------------------------------------------------------------ fetch

    def fetch_metrics(self, device_id: str, start_time: str = None,
                      end_time: str = None) -> list[RawMetric]:
        if not self._app_token:
            logger.error("Zepp/小米: 未认证")
            return []

        end_dt   = datetime.fromisoformat(end_time[:19])   if end_time   else datetime.now()
        start_dt = datetime.fromisoformat(start_time[:19]) if start_time else end_dt - timedelta(days=7)
        from_date = start_dt.strftime("%Y-%m-%d")
        to_date   = end_dt.strftime("%Y-%m-%d")

        metrics: list[RawMetric] = []
        for metric_type, path in _ENDPOINTS.items():
            params: dict = {"from_date": from_date, "to_date": to_date}
            if self._user_id:
                params["userid"] = self._user_id
            result = self._get(path, params)
            if not result:
                continue
            for item in result.get("data", []):
                rm = self._parse(metric_type, item)
                if rm:
                    metrics.append(rm)

        logger.info("Zepp/小米: 获取 %d 条指标 (%s ~ %s)", len(metrics), from_date, to_date)
        return metrics

    # ------------------------------------------------------------------ parsers

    @staticmethod
    def _parse(metric_type: str, item: dict) -> RawMetric | None:
        try:
            ts = item.get("timestamp") or item.get("time")
            if isinstance(ts, (int, float)):
                iso = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(ts, str) and ts:
                iso = ts[:19]
            else:
                date_str = item.get("date") or item.get("dateTime", "")
                iso = f"{date_str[:10]} 23:59:00" if date_str else None
            if not iso:
                return None

            if metric_type == "heart_rate":
                raw = item.get("heartRate") or item.get("value")
                if not raw or int(raw) <= 0:
                    return None
                value = str(int(raw))

            elif metric_type == "steps":
                count = item.get("steps") or item.get("value") or 0
                value = json.dumps({"count": int(count)})

            elif metric_type == "blood_oxygen":
                raw = item.get("spo2") or item.get("value")
                if not raw or int(raw) <= 0:
                    return None
                value = str(int(raw))

            elif metric_type == "sleep":
                value = json.dumps({
                    "duration_min": item.get("totalDuration") or item.get("duration") or 0,
                    "deep_min":     item.get("deepSleepDuration") or item.get("deepSleep") or 0,
                    "light_min":    item.get("lightSleepDuration") or item.get("lightSleep") or 0,
                    "rem_min":      item.get("remSleepDuration") or item.get("remSleep") or 0,
                    "awake_min":    item.get("awakeDuration") or item.get("awake") or 0,
                })

            elif metric_type == "stress":
                raw = item.get("stress") or item.get("value")
                if not raw:
                    return None
                value = str(int(raw))

            else:
                raw = item.get("value", "")
                if not raw:
                    return None
                value = str(raw)

            return RawMetric(
                metric_type=metric_type,
                value=value,
                timestamp=iso,
                extra={"source": "zepp"},
            )

        except (KeyError, TypeError, ValueError) as e:
            logger.debug("Zepp/小米: 解析 %s 失败: %s", metric_type, e)
            return None

    # ------------------------------------------------------------------ misc

    def get_supported_metrics(self) -> list[str]:
        return ["heart_rate", "steps", "blood_oxygen", "sleep", "stress"]

    def test_connection(self, config: dict) -> bool:
        if not self.authenticate(config):
            return False
        today  = datetime.now().strftime("%Y-%m-%d")
        params: dict = {"from_date": today, "to_date": today}
        if self._user_id:
            params["userid"] = self._user_id
        return self._get("data/steps", params) is not None
