"""Zepp Health provider - REST API integration for Xiaomi/Amazfit devices.

Implements OAuth2 authorization code flow and data fetching for:
- Heart rate, steps, blood oxygen, sleep, stress

Requires a Zepp Health developer account with API access.
Configuration keys (stored in mediwise config under wearable_zepp):
- client_id: Zepp Health app ID
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

_AUTH_URL = "https://auth-cn.huami.com/oauth/token"
_API_BASE = "https://api-mifit-cn.huami.com/v1"

# Zepp data type paths
_DATA_ENDPOINTS = {
    "heart_rate": "data/heart_rate",
    "steps": "data/steps",
    "blood_oxygen": "data/spo2",
    "sleep": "data/sleep",
    "stress": "data/stress",
}


class ZeppProvider(BaseProvider):
    """Provider for Zepp Health REST API (Xiaomi/Amazfit devices)."""

    provider_name = "zepp"

    def __init__(self):
        self._access_token = None
        self._client_id = None
        self._client_secret = None
        self._refresh_token = None
        self._user_id = None

    def authenticate(self, config: dict) -> bool:
        """Validate and authenticate with Zepp Health API.

        Config should contain:
        - client_id: Zepp Health developer app ID
        - client_secret: OAuth2 client secret
        - access_token: Current access token (optional, will refresh if expired)
        - refresh_token: Refresh token for obtaining new access tokens
        """
        self._client_id = config.get("client_id", "")
        self._client_secret = config.get("client_secret", "")
        self._access_token = config.get("access_token", "")
        self._refresh_token = config.get("refresh_token", "")
        self._user_id = config.get("user_id", "")

        if not self._client_id or not self._client_secret:
            logger.error("Zepp Health: missing client_id or client_secret")
            return False

        if not self._access_token and not self._refresh_token:
            logger.error("Zepp Health: no access_token or refresh_token provided")
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
            self._user_id = result.get("user_id", self._user_id)
            logger.info("Zepp Health: access token refreshed successfully")
            return bool(self._access_token)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            logger.error("Zepp Health: token refresh failed: %s", e)
            return False

    def _api_request(self, endpoint: str, params: dict | None = None) -> dict | None:
        """Make an authenticated GET request to Zepp Health API."""
        query = urllib.parse.urlencode(params) if params else ""
        url = f"{_API_BASE}/{endpoint}"
        if query:
            url = f"{url}?{query}"

        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._access_token}",
                "Accept": "application/json",
            },
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
                        logger.error("Zepp API request failed after token refresh: %s", e2)
                        return None
            logger.error("Zepp API HTTP error: %s", e)
            return None
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            logger.error("Zepp API request error: %s", e)
            return None

    def fetch_metrics(self, device_id: str, start_time: str = None,
                      end_time: str = None) -> list[RawMetric]:
        """Fetch health metrics from Zepp Health API.

        Args:
            device_id: Not used directly (Zepp uses user-level access).
            start_time: ISO datetime string for range start.
            end_time: ISO datetime string for range end.

        Returns:
            List of RawMetric objects.
        """
        if not self._access_token:
            logger.error("Zepp Health: not authenticated")
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

        start_date = start_dt.strftime("%Y-%m-%d")
        end_date = end_dt.strftime("%Y-%m-%d")

        metrics = []

        for metric_type, endpoint in _DATA_ENDPOINTS.items():
            try:
                params = {
                    "from_date": start_date,
                    "to_date": end_date,
                }
                if self._user_id:
                    params["userid"] = self._user_id

                result = self._api_request(endpoint, params)

                if not result or "data" not in result:
                    continue

                for item in result.get("data", []):
                    raw_metric = self._parse_data_point(metric_type, item)
                    if raw_metric:
                        metrics.append(raw_metric)

            except Exception as e:
                logger.warning("Zepp: failed to fetch %s: %s", metric_type, e)

        logger.info("Zepp Health: fetched %d metrics", len(metrics))
        return metrics

    def _parse_data_point(self, metric_type: str, item: dict) -> RawMetric | None:
        """Parse a Zepp Health data point into a RawMetric."""
        try:
            # Zepp timestamps can be epoch seconds or ISO strings
            ts = item.get("timestamp", item.get("time", ""))
            if isinstance(ts, (int, float)):
                iso_time = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            elif isinstance(ts, str) and ts:
                iso_time = ts[:19]  # Truncate to YYYY-MM-DD HH:MM:SS
            else:
                # Try date field for daily aggregates
                date_str = item.get("date", item.get("dateTime", ""))
                if date_str:
                    iso_time = f"{date_str[:10]} 23:59:00"
                else:
                    return None

            if metric_type == "heart_rate":
                value = str(item.get("heartRate", item.get("value", "")))
                if not value or value in ("0", ""):
                    return None
            elif metric_type == "steps":
                count = item.get("steps", item.get("value", 0))
                value = json.dumps({"count": count})
            elif metric_type == "blood_oxygen":
                value = str(item.get("spo2", item.get("value", "")))
                if not value or value in ("0", ""):
                    return None
            elif metric_type == "sleep":
                value = json.dumps({
                    "duration": item.get("totalDuration", item.get("duration", 0)),
                    "deep": item.get("deepSleepDuration", item.get("deepSleep", 0)),
                    "light": item.get("lightSleepDuration", item.get("lightSleep", 0)),
                    "rem": item.get("remSleepDuration", item.get("remSleep", 0)),
                    "awake": item.get("awakeDuration", item.get("awake", 0)),
                })
            elif metric_type == "stress":
                value = str(item.get("stress", item.get("value", "")))
            else:
                value = str(item.get("value", ""))

            if not value or value in ("", "None"):
                return None

            return RawMetric(
                metric_type=metric_type,
                value=value,
                timestamp=iso_time,
                extra={"source": "zepp", "raw": item},
            )
        except (KeyError, TypeError, ValueError) as e:
            logger.warning("Zepp: failed to parse %s data point: %s", metric_type, e)
            return None

    def get_supported_metrics(self) -> list[str]:
        return ["heart_rate", "blood_oxygen", "sleep", "steps", "stress"]

    def test_connection(self, config: dict) -> bool:
        """Test if the Zepp Health connection is working."""
        if not self.authenticate(config):
            return False

        # Try a simple API call to verify access
        today = datetime.now().strftime("%Y-%m-%d")
        params = {"from_date": today, "to_date": today}
        if self._user_id:
            params["userid"] = self._user_id

        result = self._api_request("data/steps", params)
        return result is not None
