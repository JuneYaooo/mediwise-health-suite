"""Garmin Connect provider - fetches health data via python-garminconnect.

Uses the unofficial Garmin Connect API (reverse-engineered web session).
Requires: pip install garminconnect

Configuration keys (stored in wearable_devices.config as JSON):
- username:    Garmin Connect account email
- password:    Garmin Connect account password
- tokenstore:  (optional) path to persist session tokens between runs

Supported metrics:
- heart_rate          全天每5分钟心率
- sleep               睡眠分期（深睡/浅睡/REM/清醒）
- hrv                 夜间HRV（RMSSD，毫秒）
- body_battery        身体电量（0-100，每5分钟）
- stress              压力指数（0-100）
- steps               每日步数
- calories            活动卡路里
- blood_oxygen        血氧（SpO2）
- weight              体重（kg，含BMI/体脂率等扩展字段）
- respiration         呼吸频率（次/分钟，夜间睡眠期间）
- training_readiness  训练准备度评分（0-100）
- training_status     训练状态（VO2 Max、训练负荷等）
- floors              爬楼层数（每日汇总）
- hydration           水分摄入（ml，来自 Garmin Connect 记录）
- activity            活动记录（跑步/骑行/游泳等）
"""

from __future__ import annotations

import json
import logging
import os
import time
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


def _date_range(start_time: Optional[str], end_time: Optional[str]) -> list[str]:
    """Return list of YYYY-MM-DD strings between start and end (inclusive).

    - If start_time is given (incremental sync), sync from that date up to
      today, capped at 7 days to avoid hammering the API in normal operation.
    - If start_time is None (first sync), default to yesterday + today only
      (2 days) as a safe bootstrap; user can widen range manually if needed.
    - Hard cap of 30 days applies only when the caller explicitly provides
      a very old start_time (e.g. manual backfill).
    """
    today = datetime.now().strftime("%Y-%m-%d")
    end_str = end_time[:10] if end_time else today
    end = datetime.strptime(end_str, "%Y-%m-%d")

    if start_time:
        # Incremental: sync from last_sync_at date, cap at 7 days by default
        start = datetime.strptime(start_time[:10], "%Y-%m-%d")
        default_cap = 7
    else:
        # First sync: only yesterday + today
        start = datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)
        default_cap = 2

    days = []
    cur = start
    while cur <= end:
        days.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)

    # Cap: 30 days hard limit (for manual backfill); 7 days for incremental
    return days[-30:] if len(days) > 30 else days[-default_cap:]


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
        """Login to Garmin Connect with username/password (or cached token).

        Flow:
        1. If tokenstore exists and contains valid tokens → load them directly,
           no password needed. Password is removed from config after first
           successful tokenstore login so it is never persisted further.
        2. Otherwise fall back to username/password login, then persist the
           session tokens to tokenstore (if configured) and wipe the password
           from config so subsequent runs use the token only.
        """
        gc = _require_garminconnect()

        username   = config.get("username", "")
        password   = config.get("password", "")
        tokenstore = config.get("tokenstore", None)

        # Fast path: try token-only login when tokenstore exists and has files.
        # Pass username (not password) so display_name resolves correctly;
        # garth.load() + refresh_oauth2() never use the password field.
        if tokenstore and os.path.isdir(tokenstore) and os.listdir(tokenstore):
            try:
                client = gc.Garmin(username, "")
                client.login(tokenstore)
                self._client   = client
                self._username = username
                logger.info("Garmin: loaded session from tokenstore (no password used)")
                # Password is no longer needed — remove it from the live config
                # dict so auth_device will persist the scrubbed version to DB.
                config.pop("password", None)
                return True
            except Exception:
                # Token expired or invalid — fall through to password login.
                logger.info("Garmin: tokenstore login failed, retrying with password")

        if not username or not password:
            logger.error("Garmin: missing username or password in config")
            return False

        try:
            client = gc.Garmin(username, password)
            if tokenstore:
                os.makedirs(tokenstore, exist_ok=True)
                os.chmod(tokenstore, 0o700)  # owner-only: rwx------
            # login(tokenstore) saves tokens to disk after fresh login.
            client.login(tokenstore)

            self._client   = client
            self._username = username
            logger.info("Garmin: authenticated as %s", username)

            # Tokens are now persisted to tokenstore — wipe password from config.
            if tokenstore:
                config.pop("password", None)
                logger.info("Garmin: password removed from config (token saved to %s)", tokenstore)

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
            "heart_rate", "sleep", "hrv", "body_battery", "stress",
            "steps", "calories", "blood_oxygen", "weight",
            "respiration", "training_readiness", "training_status",
            "floors", "hydration", "activity",
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

        for i, date in enumerate(dates):
            if i > 0:
                time.sleep(1)  # 天与天之间额外间隔 1s
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
            self._fetch_weight,
            self._fetch_respiration,
            self._fetch_training_readiness,
            self._fetch_training_status,
            self._fetch_floors,
            self._fetch_hydration,
            self._fetch_activities,
        ]
        for fetcher in fetchers:
            try:
                metrics.extend(fetcher(date))
                time.sleep(0.5)  # 每次请求间隔 0.5s，避免触发 Garmin 限流
            except gc.GarminConnectTooManyRequestsError:
                logger.warning(
                    "Garmin: rate limited on %s/%s, backing off 60s then stopping for this day",
                    fetcher.__name__, date,
                )
                time.sleep(60)  # 429 后退避 60s，再跳过当天剩余
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

    def _fetch_weight(self, date: str) -> list[RawMetric]:
        """Fetch weight entries logged in Garmin Connect for the day.

        get_weight(cdate) returns a dict with 'dateWeightList', each entry has
        'calendarDate', 'weight' (grams), 'bmi', 'bodyFat', 'bodyWater',
        'boneMass', 'muscleMass', 'physiqueRating', 'visceralFat', 'metabolicAge'.
        Not all devices support all fields; only weight (grams) is always present.
        """
        try:
            data = self._client.get_weight(date)
        except Exception:
            return []

        metrics = []
        for entry in (data.get("dateWeightList") or []):
            weight_g = entry.get("weight")
            if weight_g is None:
                continue
            weight_kg = round(weight_g / 1000, 2)
            calendar_date = entry.get("calendarDate", date)
            iso = f"{calendar_date} 08:00:00"  # weight entries have no time component

            extra = {}
            for field in ("bmi", "bodyFat", "bodyWater", "boneMass", "muscleMass"):
                v = entry.get(field)
                if v is not None:
                    extra[field] = v

            metrics.append(RawMetric(
                metric_type="weight",
                value=str(weight_kg),
                timestamp=iso,
                extra=extra if extra else None,
            ))
        return metrics

    def _fetch_respiration(self, date: str) -> list[RawMetric]:
        """Fetch overnight respiration rate (breaths/min).

        get_respiration_data(cdate) returns a dict with 'respirationValues',
        a list of [timestamp_ms, breaths_per_min]. Only available on devices
        with respiration tracking (Fenix 6+, Forerunner 945+, etc.).
        Returns [] silently if the device doesn't support it.
        """
        try:
            data = self._client.get_respiration_data(date)
        except Exception:
            return []

        metrics = []
        for entry in (data.get("respirationValues") or []):
            if not entry or len(entry) < 2:
                continue
            ts_ms, bpm = entry[0], entry[1]
            if bpm is None or bpm <= 0:
                continue
            iso = datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")
            metrics.append(RawMetric(
                metric_type="respiration",
                value=str(round(float(bpm), 1)),
                timestamp=iso,
            ))
        return metrics

    def _fetch_training_readiness(self, date: str) -> list[RawMetric]:
        """Fetch training readiness score (0-100) and contributing factors.

        get_training_readiness(cdate) returns a dict with 'score', 'level'
        ('EXCELLENT'/'GOOD'/'MODERATE'/'LOW'/'NO_DATA'), and sub-scores like
        'sleepScore', 'recoveryTime', 'acuteLoad', 'hrv'. Newer devices only.
        """
        try:
            data = self._client.get_training_readiness(date)
        except Exception:
            return []

        score = data.get("score")
        if score is None:
            return []

        val = {
            "score":         int(score),
            "level":         data.get("level"),
            "sleep_score":   data.get("sleepScore"),
            "recovery_time": data.get("recoveryTime"),
            "hrv_status":    data.get("hrvStatus"),
            "acute_load":    data.get("acuteLoad"),
        }
        # Remove None values to keep output clean
        val = {k: v for k, v in val.items() if v is not None}

        return [RawMetric(
            metric_type="training_readiness",
            value=json.dumps(val),
            timestamp=f"{date} 06:00:00",
            extra={"date": date},
        )]

    def _fetch_training_status(self, date: str) -> list[RawMetric]:
        """Fetch training status: VO2 Max estimate and training load balance.

        get_training_status(cdate) returns a dict with 'vo2MaxValue',
        'fitnessAge', 'trainingLoadBalance' (aerobic/anaerobic split),
        and 'trainingStatus' string. Most fields require newer Garmin devices.
        """
        try:
            data = self._client.get_training_status(date)
        except Exception:
            return []

        # Top-level or nested under 'latestTrainingStatus'
        latest = data.get("latestTrainingStatus") or data
        vo2 = latest.get("vo2MaxValue") or data.get("vo2MaxValue")
        if vo2 is None:
            return []

        val = {
            "vo2_max":        round(float(vo2), 1),
            "fitness_age":    latest.get("fitnessAge") or data.get("fitnessAge"),
            "status":         latest.get("trainingStatus") or data.get("trainingStatus"),
        }
        load = data.get("trainingLoadBalance") or {}
        if load:
            val["aerobic_load"]    = load.get("aerobicTrainingEffect")
            val["anaerobic_load"]  = load.get("anaerobicTrainingEffect")
        val = {k: v for k, v in val.items() if v is not None}

        return [RawMetric(
            metric_type="training_status",
            value=json.dumps(val),
            timestamp=f"{date} 06:00:00",
            extra={"date": date},
        )]

    def _fetch_floors(self, date: str) -> list[RawMetric]:
        """Fetch floors climbed for the day (daily summary).

        get_floors(cdate) returns a list of dicts with 'floorsValueDescriptorDTOList'
        and 'floorValuesArray'. Each entry in floorValuesArray: [ts_ms, ascended, descended].
        We emit a single daily summary (last entry = end-of-day total).
        """
        try:
            data = self._client.get_floors(date)
        except Exception:
            return []

        entries = []
        for day in (data or []):
            for entry in (day.get("floorValuesArray") or []):
                if entry and len(entry) >= 2:
                    entries.append(entry)

        if not entries:
            return []

        # Last entry represents end-of-day cumulative total
        last = entries[-1]
        ascended  = last[1] if len(last) > 1 else None
        descended = last[2] if len(last) > 2 else None
        if ascended is None:
            return []

        val = {"ascended": int(ascended)}
        if descended is not None:
            val["descended"] = int(descended)

        return [RawMetric(
            metric_type="floors",
            value=json.dumps(val),
            timestamp=f"{date} 23:59:00",
            extra={"aggregated": True},
        )]

    def _fetch_hydration(self, date: str) -> list[RawMetric]:
        """Fetch hydration intake logged in Garmin Connect (ml).

        get_hydration_data(cdate) returns a dict with 'valueInML' (total for day)
        and 'sweatLossInML' (estimated sweat loss). Only populated if the user
        logs water intake in the Garmin Connect app.
        """
        try:
            data = self._client.get_hydration_data(date)
        except Exception:
            return []

        intake_ml = data.get("valueInML")
        if not intake_ml:
            return []

        val = {"intake_ml": round(float(intake_ml), 1)}
        sweat = data.get("sweatLossInML")
        if sweat:
            val["sweat_loss_ml"] = round(float(sweat), 1)

        return [RawMetric(
            metric_type="hydration",
            value=json.dumps(val),
            timestamp=f"{date} 23:59:00",
            extra={"aggregated": True},
        )]

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