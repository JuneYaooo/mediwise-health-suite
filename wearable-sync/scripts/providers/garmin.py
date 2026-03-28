"""Garmin Connect provider - fetches health data via python-garminconnect.

Uses the unofficial Garmin Connect API (reverse-engineered web session).
Requires: pip install garminconnect

Configuration keys (stored in wearable_devices.config as JSON):
- username:    Garmin Connect account email
- password:    Garmin Connect account password
- tokenstore:  (optional) path to persist session tokens between runs

Supported metrics:
- heart_rate        全天每5分钟心率
- sleep             睡眠分期（深睡/浅睡/REM/清醒）
- hrv               夜间HRV（RMSSD，毫秒）
- body_battery      身体电量（0-100，每5分钟）
- stress            压力指数（0-100）
- steps             每日步数
- calories          活动卡路里
- blood_oxygen      血氧（SpO2）
- activity          活动记录（跑步/骑行/游泳等）
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from .base import BaseProvider, RawMetric

logger = logging.getLogger(__name__)


def _require_garminconnect():
    """Import garminconnect, raise with install hint if missing."""
    try:
        import garminconnect
        return garminconnect
    except ImportError:
        raise ImportError(
            "garminconnect 未安装。请运行: pip install garminconnect"
        )


def _check_garminconnect_version():
    """Return (current_version, upgrade_hint) for user-facing messages."""
    try:
        from importlib.metadata import version
        current = version("garminconnect")
    except Exception:
        current = "未知"
    return current


def _to_date(ts: Optional[str]) -> str:
    """Convert ISO datetime string or None to YYYY-MM-DD."""
    if ts:
        return ts[:10]
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _date_range(start_time: Optional[str], end_time: Optional[str]) -> list[str]:
    """Return list of YYYY-MM-DD strings between start and end (inclusive)."""
    start = datetime.strptime(_to_date(start_time), "%Y-%m-%d")
    end_str = end_time[:10] if end_time else datetime.now().strftime("%Y-%m-%d")
    end = datetime.strptime(end_str, "%Y-%m-%d")
    days = []
    cur = start
    while cur <= end:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
    # Cap at 30 days to avoid hammering the API
    return days[-30:]


class GarminProvider(BaseProvider):
    """Provider for Garmin Connect health data."""

    provider_name = "garmin"

    def __init__(self):
        self._client = None
        self._username = None

    # ------------------------------------------------------------------
    # BaseProvider interface
    # ------------------------------------------------------------------

    def authenticate(self, config: dict) -> bool:
        """Login to Garmin Connect with username/password.

        On success, stores the session in tokenstore path (if configured)
        so subsequent runs skip re-login.
        """
        gc = _require_garminconnect()

        username = config.get("username", "")
        password = config.get("password", "")
        tokenstore = config.get("tokenstore", None)

        if not username or not password:
            logger.error("Garmin: missing username or password in config")
            return False

        try:
            client = gc.Garmin(username, password)
            if tokenstore:
                os.makedirs(tokenstore, exist_ok=True)
            # login(tokenstore) loads saved tokens if dir exists, else does
            # fresh username/password login and saves tokens to tokenstore.
            client.login(tokenstore)

            self._client = client
            self._username = username
            logger.info("Garmin: authenticated as %s", username)
            return True

        except gc.GarminConnectAuthenticationError as e:
            ver = _check_garminconnect_version()
            logger.error("Garmin: authentication error: %s", e)
            # Authentication errors can mean wrong password OR Garmin changed
            # their login flow and the library needs updating.
            raise RuntimeError(
                f"Garmin Connect 登录失败（当前库版本 {ver}）。\n"
                "可能原因：\n"
                "1. 邮箱或密码错误，请检查 Garmin Connect 账号信息\n"
                "2. 账号开启了两步验证（首次登录需要在终端手动输入验证码）\n"
                "3. Garmin 更新了登录接口，请升级库后重试：\n"
                "   pip install --upgrade garminconnect"
            ) from e

        except gc.GarminConnectConnectionError as e:
            logger.error("Garmin: connection error: %s", e)
            raise RuntimeError(
                "无法连接到 Garmin Connect 服务器，请检查网络连接后重试。"
            ) from e

        except gc.GarminConnectTooManyRequestsError as e:
            logger.error("Garmin: rate limited: %s", e)
            raise RuntimeError(
                "Garmin Connect 请求过于频繁，请等待一段时间后再同步。\n"
                "建议同步频率不超过每小时一次。"
            ) from e

        except Exception as e:
            ver = _check_garminconnect_version()
            logger.error("Garmin: authentication failed: %s", e)
            raise RuntimeError(
                f"Garmin 登录出现未知错误（库版本 {ver}）：{e}\n"
                "如果问题持续，可尝试升级库：pip install --upgrade garminconnect"
            ) from e

    def test_connection(self, config: dict) -> bool:
        """Authenticate and fetch today's step count as a connectivity check."""
        if not self.authenticate(config):
            return False
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            self._client.get_stats(today)
            return True
        except Exception as e:
            logger.error("Garmin: connection test failed: %s", e)
            return False

    def get_supported_metrics(self) -> list[str]:
        return [
            "heart_rate", "sleep", "hrv", "body_battery",
            "stress", "steps", "calories", "blood_oxygen", "activity",
        ]

    def fetch_metrics(
        self,
        device_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> list[RawMetric]:
        """Fetch all supported metrics from Garmin Connect.

        Loads config from wearable_devices, authenticates, then pulls data
        for each day in the requested range.
        """
        config = self._load_config(device_id)
        if config is None:
            return []

        if not self.authenticate(config):
            return []

        dates = _date_range(start_time, end_time)
        metrics: list[RawMetric] = []

        for date in dates:
            metrics.extend(self._fetch_day(date))

        logger.info("Garmin: fetched %d metrics across %d days", len(metrics), len(dates))
        return metrics

    # ------------------------------------------------------------------
    # Per-day fetchers
    # ------------------------------------------------------------------

    def _fetch_day(self, date: str) -> list[RawMetric]:
        """Fetch all metric types for a single calendar day."""
        gc = _require_garminconnect()
        metrics: list[RawMetric] = []
        fetchers = [
            self._fetch_heart_rate,
            self._fetch_sleep,
            self._fetch_hrv,
            self._fetch_body_battery,
            self._fetch_stress,
            self._fetch_stats,
            self._fetch_blood_oxygen,
            self._fetch_activities,
        ]
        for fetcher in fetchers:
            try:
                metrics.extend(fetcher(date))
            except gc.GarminConnectTooManyRequestsError:
                logger.warning("Garmin: rate limited on %s/%s, stopping further requests for this day",
                               fetcher.__name__, date)
                break  # stop fetching more endpoints for today
            except Exception as e:
                logger.warning("Garmin: %s failed for %s: %s", fetcher.__name__, date, e)
        return metrics

    def _fetch_heart_rate(self, date: str) -> list[RawMetric]:
        """Fetch all-day heart rate (5-minute intervals)."""
        data = self._client.get_heart_rates(date)
        metrics = []
        # data["heartRateValues"] is list of [timestamp_ms, bpm]
        for ts_ms, bpm in (data.get("heartRateValues") or []):
            if bpm is None or bpm <= 0:
                continue
            iso = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
            metrics.append(RawMetric(
                metric_type="heart_rate",
                value=str(bpm),
                timestamp=iso,
                extra={"resting_hr": data.get("restingHeartRate")},
            ))
        return metrics

    def _fetch_sleep(self, date: str) -> list[RawMetric]:
        """Fetch sleep data with stage breakdown."""
        data = self._client.get_sleep_data(date)
        daily = (data.get("dailySleepDTO") or {})

        if not daily:
            return []

        # Duration fields are in seconds
        def _sec_to_min(v):
            return int((v or 0) / 60)

        sleep_val = {
            "duration_min": _sec_to_min(daily.get("sleepTimeSeconds")),
            "deep_min":     _sec_to_min(daily.get("deepSleepSeconds")),
            "light_min":    _sec_to_min(daily.get("lightSleepSeconds")),
            "rem_min":      _sec_to_min(daily.get("remSleepSeconds")),
            "awake_min":    _sec_to_min(daily.get("awakeSleepSeconds")),
            "score":        daily.get("sleepScores", {}).get("overall", {}).get("value") if isinstance(daily.get("sleepScores"), dict) else None,
        }

        if sleep_val["duration_min"] < 30:
            return []

        # Timestamp: sleep start time
        start_gmt = daily.get("sleepStartTimestampGMT")
        if start_gmt:
            iso = datetime.fromtimestamp(start_gmt / 1000).strftime("%Y-%m-%d %H:%M:%S")
        else:
            iso = f"{date} 00:00:00"

        return [RawMetric(
            metric_type="sleep",
            value=json.dumps(sleep_val),
            timestamp=iso,
            extra={"date": date},
        )]

    def _fetch_hrv(self, date: str) -> list[RawMetric]:
        """Fetch HRV (RMSSD) nightly summary."""
        data = self._client.get_hrv_data(date)
        summary = (data.get("hrvSummary") or {})
        rmssd = summary.get("rmssd")
        if rmssd is None:
            return []

        hrv_val = {
            "rmssd":          round(float(rmssd), 1),
            "weekly_avg":     summary.get("weeklyAvg"),
            "last_night_5min_high": summary.get("lastNight5MinHigh"),
            "status":         summary.get("hrvStatus"),   # "BALANCED", "UNBALANCED", etc.
        }

        start_ts = summary.get("startTimestampGMT")
        iso = datetime.fromtimestamp(start_ts / 1000).strftime("%Y-%m-%d %H:%M:%S") if start_ts else f"{date} 04:00:00"

        return [RawMetric(
            metric_type="hrv",
            value=json.dumps(hrv_val),
            timestamp=iso,
            extra={"date": date},
        )]

    def _fetch_body_battery(self, date: str) -> list[RawMetric]:
        """Fetch Body Battery charged/drained events (5-minute resolution).

        get_body_battery(startdate, enddate) returns a list of dicts,
        each with 'date' and 'bodyBatteryValuesArray'.
        Each entry in bodyBatteryValuesArray: [timestamp_ms, level, charged, drained]
        """
        data = self._client.get_body_battery(date, date)
        metrics = []
        for day_data in (data or []):
            for entry in (day_data.get("bodyBatteryValuesArray") or []):
                # entry: [timestamp_ms, battery_level, charged, drained]
                if not entry or len(entry) < 2:
                    continue
                ts_ms = entry[0]
                level = entry[1]
                if level is None:
                    continue
                iso = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
                bb_val = {
                    "level":   int(level),
                    "charged": entry[2] if len(entry) > 2 else None,
                    "drained": entry[3] if len(entry) > 3 else None,
                }
                metrics.append(RawMetric(
                    metric_type="body_battery",
                    value=json.dumps(bb_val),
                    timestamp=iso,
                ))
        return metrics

    def _fetch_stress(self, date: str) -> list[RawMetric]:
        """Fetch all-day stress levels (3-minute intervals)."""
        data = self._client.get_stress_data(date)
        metrics = []
        for ts_ms, level in (data.get("stressValuesArray") or []):
            if level is None or level < 0:
                continue
            iso = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
            metrics.append(RawMetric(
                metric_type="stress",
                value=str(level),
                timestamp=iso,
            ))
        return metrics

    def _fetch_stats(self, date: str) -> list[RawMetric]:
        """Fetch daily summary: steps, calories, distance."""
        data = self._client.get_stats(date)
        metrics = []
        ts = f"{date} 23:59:00"

        steps = data.get("totalSteps")
        if steps is not None:
            metrics.append(RawMetric(
                metric_type="steps_raw",
                value=json.dumps({
                    "count":      int(steps),
                    "distance_m": int(data.get("totalDistanceMeters") or 0),
                    "calories":   int(data.get("activeKilocalories") or 0),
                }),
                timestamp=ts,
                extra={"aggregated": True},
            ))

        calories = data.get("activeKilocalories")
        if calories is not None:
            metrics.append(RawMetric(
                metric_type="calories",
                value=str(int(calories)),
                timestamp=ts,
            ))

        return metrics

    def _fetch_blood_oxygen(self, date: str) -> list[RawMetric]:
        """Fetch SpO2 data via get_spo2_data(cdate).

        Returns dict with 'spO2HourlyAverages' list, each entry has
        'startGMT' (ISO string) and 'spo2Reading' (int or None).
        Not all Garmin devices support SpO2; returns [] if unavailable.
        """
        data = self._client.get_spo2_data(date)
        metrics = []
        for entry in (data.get("spO2HourlyAverages") or []):
            spo2 = entry.get("spo2Reading")
            if spo2 is None:
                continue
            start_gmt = entry.get("startGMT", "")
            try:
                iso = datetime.strptime(start_gmt[:19], "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                iso = f"{date} 00:00:00"
            metrics.append(RawMetric(
                metric_type="blood_oxygen",
                value=str(spo2),
                timestamp=iso,
            ))
        return metrics

    def _fetch_activities(self, date: str) -> list[RawMetric]:
        """Fetch activity records (runs, rides, swims, etc.) for the day."""
        # Fetch recent activities and filter by date
        try:
            activities = self._client.get_activities_by_date(date, date)
        except Exception:
            return []

        metrics = []
        for act in (activities or []):
            start_local = act.get("startTimeLocal", "")
            if not start_local:
                continue
            try:
                iso = datetime.strptime(start_local[:19], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                iso = f"{date} 12:00:00"

            act_val = {
                "activity_type": act.get("activityType", {}).get("typeKey", "unknown"),
                "name":          act.get("activityName", ""),
                "duration_sec":  int(act.get("duration") or 0),
                "distance_m":    round(float(act.get("distance") or 0), 1),
                "calories":      int(act.get("calories") or 0),
                "avg_hr":        act.get("averageHR"),
                "max_hr":        act.get("maxHR"),
                "aerobic_te":    act.get("aerobicTrainingEffect"),
                "activity_id":   act.get("activityId"),
            }
            metrics.append(RawMetric(
                metric_type="activity",
                value=json.dumps(act_val),
                timestamp=iso,
                extra={"activity_id": act.get("activityId")},
            ))
        return metrics

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_config(self, device_id: str) -> Optional[dict]:
        """Load device config from wearable_devices table."""
        import sys
        sys.path.insert(0, os.path.join(
            os.path.dirname(__file__), "..", "..", "..",
            "mediwise-health-tracker", "scripts"
        ))
        import health_db

        conn = health_db.get_lifestyle_connection()
        try:
            row = conn.execute(
                "SELECT config FROM wearable_devices WHERE id=? AND is_deleted=0",
                (device_id,)
            ).fetchone()
        finally:
            conn.close()

        if not row:
            logger.error("Garmin: device not found: %s", device_id)
            return None

        try:
            return json.loads(row["config"] or "{}")
        except (json.JSONDecodeError, TypeError):
            return {}