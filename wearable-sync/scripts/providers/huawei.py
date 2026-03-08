"""Huawei Health Kit provider - REST API integration.

Implements OAuth2 authorization code flow and data fetching for:
- Heart rate, steps, blood oxygen, sleep, stress, calories

Requires enterprise developer credentials on Huawei AppGallery.
Configuration keys (stored in mediwise config under wearable_huawei):
- client_id: Huawei AppGallery app ID
- client_secret: OAuth2 client secret
- access_token: Current OAuth2 access token
- refresh_token: OAuth2 refresh token
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
import urllib.parse
import logging
from datetime import datetime, timedelta

from .base import BaseProvider, RawMetric

logger = logging.getLogger(__name__)

_AUTH_URL = "https://oauth-login.cloud.huawei.com/oauth2/v3/token"
_API_BASE = "https://health-api.cloud.huawei.com/healthkit/v1"

# Huawei data type IDs mapped to our metric types
_DATA_TYPES = {
    "heart_rate": "com.huawei.health.heartrate",
    "steps": "com.huawei.health.step",
    "blood_oxygen": "com.huawei.health.spo2",
    "sleep": "com.huawei.health.sleep",
    "stress": "com.huawei.health.stress",
    "calories": "com.huawei.health.calories",
}


class HuaweiProvider(BaseProvider):
    """Provider for Huawei Health Kit REST API."""

    provider_name = "huawei"

    def __init__(self):
        self._access_token = None
        self._client_id = None
        self._client_secret = None
        self._refresh_token = None

    def authenticate(self, config: dict) -> bool:
        """Validate and authenticate with Huawei Health Kit.

        Config should contain:
        - client_id: App ID from Huawei AppGallery
        - client_secret: OAuth2 client secret
        - access_token: Current access token (optional, will refresh if expired)
        - refresh_token: Refresh token for obtaining new access tokens
        """
        self._client_id = config.get("client_id", "")
        self._client_secret = config.get("client_secret", "")
        self._access_token = config.get("access_token", "")
        self._refresh_token = config.get("refresh_token", "")

        if not self._client_id or not self._client_secret:
            logger.error("Huawei Health Kit: missing client_id or client_secret")
            return False

        if not self._access_token and not self._refresh_token:
            logger.error("Huawei Health Kit: no access_token or refresh_token provided")
            return False

        # If we have a refresh token but no access token, try to refresh
        if not self._access_token and self._refresh_token:
            return self._refresh_access_token()

        return True

    def _refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        data = urllib.parse.urlencode({
            "grant_type": "refresh_token",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "refresh_token": self._refresh_token,
        }).encode("utf-8")

        req = urllib.request.Request(
            _AUTH_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            self._access_token = result.get("access_token", "")
            new_refresh = result.get("refresh_token")
            if new_refresh:
                self._refresh_token = new_refresh
            logger.info("Huawei Health Kit: access token refreshed successfully")
            return bool(self._access_token)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            logger.error("Huawei Health Kit: token refresh failed: %s", e)
            return False

    def _api_request(self, path: str, body: dict | None = None) -> dict | None:
        """Make an authenticated API request to Huawei Health Kit."""
        url = f"{_API_BASE}/{path}"
        payload = json.dumps(body).encode("utf-8") if body else None

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Content-Type": "application/json",
            },
            method="POST" if payload else "GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 401 and self._refresh_token:
                # Token expired, try to refresh
                if self._refresh_access_token():
                    req.add_header("Authorization", f"Bearer {self._access_token}")
                    try:
                        with urllib.request.urlopen(req, timeout=30) as resp:
                            return json.loads(resp.read().decode("utf-8"))
                    except (urllib.error.URLError, urllib.error.HTTPError) as e2:
                        logger.error("Huawei API request failed after token refresh: %s", e2)
                        return None
            logger.error("Huawei API HTTP error: %s", e)
            return None
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.error("Huawei API request error: %s", e)
            return None

    def fetch_metrics(self, device_id: str, start_time: str = None,
                      end_time: str = None) -> list[RawMetric]:
        """Fetch health metrics from Huawei Health Kit.

        Args:
            device_id: Not used directly (Huawei uses user-level access).
            start_time: ISO datetime string for range start.
            end_time: ISO datetime string for range end.

        Returns:
            List of RawMetric objects.
        """
        if not self._access_token:
            logger.error("Huawei Health Kit: not authenticated")
            return []

        # Default time range: last 24 hours
        if end_time:
            end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        else:
            end_dt = datetime.now()

        if start_time:
            start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        else:
            start_dt = end_dt - timedelta(hours=24)

        # Convert to millisecond timestamps
        start_ms = int(start_dt.timestamp() * 1000)
        end_ms = int(end_dt.timestamp() * 1000)

        metrics = []

        # Fetch each data type
        for metric_type, data_type in _DATA_TYPES.items():
            try:
                result = self._api_request("data/read", {
                    "dataTypeName": data_type,
                    "startTime": start_ms,
                    "endTime": end_ms,
                })

                if not result or "data" not in result:
                    continue

                for item in result.get("data", []):
                    raw_metric = self._parse_data_point(metric_type, item)
                    if raw_metric:
                        metrics.append(raw_metric)

            except Exception as e:
                logger.warning("Huawei: failed to fetch %s: %s", metric_type, e)

        logger.info("Huawei Health Kit: fetched %d metrics", len(metrics))
        return metrics

    def _parse_data_point(self, metric_type: str, item: dict) -> RawMetric | None:
        """Parse a Huawei Health Kit data point into a RawMetric."""
        try:
            timestamp_ms = item.get("startTime", item.get("timestamp", 0))
            if not timestamp_ms:
                return None
            iso_time = datetime.fromtimestamp(timestamp_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

            if metric_type == "heart_rate":
                value = str(item.get("value", item.get("heartRate", "")))
            elif metric_type == "steps":
                value = json.dumps({"count": item.get("value", item.get("steps", 0))})
            elif metric_type == "blood_oxygen":
                value = str(item.get("value", item.get("spo2", "")))
            elif metric_type == "sleep":
                value = json.dumps({
                    "duration": item.get("duration", 0),
                    "deep": item.get("deepSleep", 0),
                    "light": item.get("lightSleep", 0),
                    "rem": item.get("remSleep", 0),
                    "awake": item.get("awake", 0),
                })
            elif metric_type == "stress":
                value = str(item.get("value", item.get("stress", "")))
            elif metric_type == "calories":
                value = str(item.get("value", item.get("calories", "")))
            else:
                value = str(item.get("value", ""))

            if not value or value in ("", "None"):
                return None

            return RawMetric(
                metric_type=metric_type,
                value=value,
                timestamp=iso_time,
                extra={"source": "huawei", "raw": item},
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Huawei: failed to parse %s data point: %s", metric_type, e)
            return None

    def get_supported_metrics(self) -> list[str]:
        return ["heart_rate", "blood_oxygen", "sleep", "steps", "stress", "calories"]

    def test_connection(self, config: dict) -> bool:
        """Test if the Huawei Health Kit connection is working."""
        if not self.authenticate(config):
            return False

        # Try a simple API call to verify access
        result = self._api_request("data/read", {
            "dataTypeName": _DATA_TYPES["steps"],
            "startTime": int((datetime.now() - timedelta(hours=1)).timestamp() * 1000),
            "endTime": int(datetime.now().timestamp() * 1000),
        })
        return result is not None
