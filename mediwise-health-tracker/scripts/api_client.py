"""Backend API client for MediWise Health Tracker.

Uses urllib.request (no extra dependencies) to call the backend REST API
when backend mode is enabled in config.
"""

from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
import urllib.parse
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from config import get_backend_config


class APIError(Exception):
    """Raised when the backend API returns an error."""
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


_LOCAL_HTTP_RE = re.compile(r"^http://(localhost|127\.0\.0\.1|\[?::1\]?|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?(/|$)")


def _validate_base_url(base_url):
    """Enforce HTTPS for remote URLs. Allow HTTP only for local/private addresses."""
    if base_url.startswith("https://"):
        return
    if _LOCAL_HTTP_RE.match(base_url):
        return
    raise APIError(f"不安全的 URL: {base_url}，远程服务必须使用 HTTPS")


def _get_config():
    cfg = get_backend_config()
    if not cfg.get("enabled") or not cfg.get("base_url"):
        raise APIError("后端 API 模式未启用，请先运行: python3 setup.py set-backend --url <url> --token <token>")
    return cfg


def _request(method, path, data=None, params=None):
    """Make an HTTP request to the backend API.

    Args:
        method: HTTP method (GET, POST, PUT, DELETE, PATCH)
        path: API path (e.g. "/members")
        data: Request body dict (for POST/PUT/PATCH)
        params: Query parameters dict (for GET)

    Returns:
        Parsed response data (the "data" field from {"code": 0, "data": ...})
    """
    cfg = _get_config()
    base_url = cfg["base_url"].rstrip("/")
    _validate_base_url(base_url)
    token = cfg.get("token", "")

    url = base_url + path
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if qs:
            url += "?" + qs

    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data else None

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode("utf-8")
            if not resp_body:
                return None
            result = json.loads(resp_body)
            # Support both {"code": 0, "data": ...} and direct response formats
            if isinstance(result, dict) and "code" in result:
                if result["code"] != 0:
                    raise APIError(result.get("message", f"API 错误 (code={result['code']})"))
                return result.get("data")
            return result
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8")
        except Exception:
            pass
        if e.code == 401:
            raise APIError("认证失败：Token 无效或已过期，请重新设置: python3 setup.py set-backend --url <url> --token <token>", status_code=401)
        if e.code == 403:
            raise APIError("权限不足：当前 Token 无权执行此操作", status_code=403)
        if e.code == 404:
            raise APIError(f"资源未找到: {path}", status_code=404)
        msg = f"HTTP {e.code} 错误"
        if body_text:
            try:
                err = json.loads(body_text)
                msg = err.get("message", err.get("detail", msg))
            except (json.JSONDecodeError, AttributeError):
                msg += f": {body_text[:200]}"
        raise APIError(msg, status_code=e.code)
    except urllib.error.URLError as e:
        raise APIError(f"无法连接到后端服务 ({base_url}): {e.reason}")


# --- Members ---

def list_members():
    return _request("GET", "/members")


def add_member(data):
    return _request("POST", "/members", data=data)


def get_member(member_id):
    return _request("GET", f"/members/{member_id}")


def update_member(member_id, data):
    return _request("PUT", f"/members/{member_id}", data=data)


def delete_member(member_id):
    return _request("DELETE", f"/members/{member_id}")


# --- Health Metrics ---

def add_metric(data):
    return _request("POST", "/health-metrics", data=data)


def list_metrics(params=None):
    return _request("GET", "/health-metrics", params=params)


def delete_metric(metric_id):
    return _request("DELETE", f"/health-metrics/{metric_id}")


# --- Medical Records ---

def add_medical_record(record_type, data):
    return _request("POST", f"/medical-records/{record_type}", data=data)


def list_medical_records(record_type, params=None):
    return _request("GET", f"/medical-records/{record_type}", params=params)


def update_medical_record(record_type, record_id, data):
    return _request("PUT", f"/medical-records/{record_type}/{record_id}", data=data)


def delete_medical_record(record_type, record_id):
    return _request("DELETE", f"/medical-records/{record_type}/{record_id}")


# --- Query ---

def get_timeline(member_id):
    return _request("GET", f"/query/timeline", params={"member_id": member_id})


def get_active_medications(member_id):
    return _request("GET", f"/query/active-medications", params={"member_id": member_id})


def get_visits(member_id, start_date=None, end_date=None):
    params = {"member_id": member_id}
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    return _request("GET", f"/query/visits", params=params)


def get_summary(member_id):
    return _request("GET", f"/query/summary", params={"member_id": member_id})


def search_records(keyword, member_id=None):
    params = {"keyword": keyword}
    if member_id:
        params["member_id"] = member_id
    return _request("GET", f"/query/search", params=params)


def get_family_overview():
    return _request("GET", f"/query/family-overview")


# --- Memory ---

def get_memory_context(member_id, max_tokens=None):
    params = {"member_id": member_id}
    if max_tokens:
        params["max_tokens"] = str(max_tokens)
    return _request("GET", "/memory/context", params=params)


def get_memory_summary(member_id, summary_type="all"):
    return _request("GET", "/memory/summary", params={"member_id": member_id, "type": summary_type})


def list_observations(member_id=None, obs_type=None, limit=None):
    params = {}
    if member_id:
        params["member_id"] = member_id
    if obs_type:
        params["type"] = obs_type
    if limit:
        params["limit"] = str(limit)
    return _request("GET", "/memory/observations", params=params)


def add_observation(data):
    return _request("POST", "/memory/observations", data=data)


def generate_summary(member_id, summary_type):
    return _request("POST", "/memory/summary/generate", data={"member_id": member_id, "type": summary_type})


def get_memory_stats():
    return _request("GET", "/memory/stats")
