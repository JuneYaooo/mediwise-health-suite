"""User-confirmed health goals, check-ins, progress, and idempotent milestones.

The engine tracks actions the user explicitly chose. It never derives a target from
weight, heart rate, diagnosis, age, or any other health reading. Card rendering lives
in the health-goals Skill; this module is the deterministic evidence layer shared by
manual exercise and wearable imports.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Mapping, Optional

from health_db import (
    ensure_db,
    generate_id,
    get_lifestyle_connection,
    get_medical_connection,
    now_iso,
    row_to_dict,
    rows_to_list,
    transaction,
    verify_member_ownership,
)


VALID_DOMAINS = ("activity", "sleep", "records", "custom")
VALID_GOAL_TYPES = (
    "weekly_frequency",
    "weekly_duration",
    "cumulative_count",
    "cumulative_duration",
)
VALID_SOURCES = ("user_defined", "professional_defined", "imported_plan")
VALID_STATUSES = ("active", "paused", "completed", "abandoned")

GOAL_UNITS = {
    "weekly_frequency": "次",
    "weekly_duration": "分钟",
    "cumulative_count": "次",
    "cumulative_duration": "分钟",
}


def _as_date(value: object, fallback: Optional[date] = None) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        if fallback is not None:
            return fallback
        raise ValueError("日期必须是 YYYY-MM-DD")


def _as_datetime_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return now_iso()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError("打卡时间格式无效")


def _member(member_id: str, owner_id: Optional[str]) -> Optional[dict]:
    conn = get_medical_connection()
    try:
        if not verify_member_ownership(conn, member_id, owner_id):
            return None
        row = conn.execute(
            "SELECT id,name,relation FROM members WHERE id=? AND is_deleted=0", (member_id,)
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def _period_start(day: date, week_start: int) -> date:
    offset = (day.weekday() - int(week_start or 0)) % 7
    return day - timedelta(days=offset)


def _goal_measure(goal: Mapping[str, object], checkin: Mapping[str, object]) -> float:
    goal_type = str(goal.get("goal_type") or "")
    if goal_type in ("weekly_frequency", "cumulative_count"):
        return 1.0
    raw = checkin.get("duration_minutes")
    if raw is None:
        raw = checkin.get("value")
    try:
        return max(float(raw or 0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def create_goal(
    member_id: str,
    *,
    domain: str,
    goal_type: str,
    title: str,
    target_value: float,
    confirmed: bool,
    owner_id: Optional[str] = None,
    total_periods: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    week_start: int = 0,
    source: str = "user_defined",
    rules: Optional[Mapping[str, object]] = None,
) -> dict:
    """Create one active goal per member and domain after explicit confirmation."""
    ensure_db()
    if not confirmed:
        return {"status": "error", "message": "创建目标前必须由用户明确确认目标内容"}
    if not _member(member_id, owner_id):
        return {"status": "error", "message": "未找到成员或无权访问"}
    if domain not in VALID_DOMAINS:
        return {"status": "error", "message": "当前支持的目标域：%s" % "、".join(VALID_DOMAINS)}
    if goal_type not in VALID_GOAL_TYPES:
        return {"status": "error", "message": "当前支持的目标类型：%s" % "、".join(VALID_GOAL_TYPES)}
    if source not in VALID_SOURCES:
        return {"status": "error", "message": "目标来源无效"}
    try:
        target = float(target_value)
    except (TypeError, ValueError):
        return {"status": "error", "message": "目标值必须是数字"}
    if not math.isfinite(target) or target <= 0 or target > 1000000:
        return {"status": "error", "message": "目标值必须大于 0 且在合理范围内"}
    if not str(title or "").strip():
        return {"status": "error", "message": "目标标题不能为空"}
    if total_periods is not None:
        try:
            total_periods = int(total_periods)
        except (TypeError, ValueError):
            return {"status": "error", "message": "目标周期数必须是整数"}
        if total_periods < 1 or total_periods > 520:
            return {"status": "error", "message": "目标周期数应为 1-520"}
    if goal_type.startswith("weekly_") and total_periods is None:
        total_periods = 4
    if goal_type.startswith("cumulative_"):
        total_periods = None
    try:
        start = _as_date(start_date, date.today())
        end = _as_date(end_date) if end_date else None
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    if end and end < start:
        return {"status": "error", "message": "结束日期不能早于开始日期"}
    try:
        week_start = int(week_start)
    except (TypeError, ValueError):
        return {"status": "error", "message": "week_start 必须为 0-6（周一到周日）"}
    if week_start not in range(7):
        return {"status": "error", "message": "week_start 必须为 0-6（周一到周日）"}

    with transaction(domain="lifestyle") as conn:
        existing = conn.execute(
            """SELECT id,title FROM health_goals
               WHERE member_id=? AND domain=? AND status='active' AND is_deleted=0""",
            (member_id, domain),
        ).fetchone()
        if existing:
            return {
                "status": "error",
                "message": "该领域已有一个进行中的目标，请先完成、暂停或放弃现有目标",
                "existing_goal_id": existing["id"],
            }
        goal_id = generate_id()
        now = now_iso()
        conn.execute(
            """INSERT INTO health_goals
               (id,member_id,domain,goal_type,title,target_value,target_unit,period_type,
                total_periods,start_date,end_date,week_start,status,source,rules,version,
                created_at,updated_at,is_deleted)
               VALUES (?,?,?,?,?,?,?,'week',?,?,?,?, 'active',?,?,1,?,?,0)""",
            (
                goal_id,
                member_id,
                domain,
                goal_type,
                str(title).strip()[:120],
                target,
                GOAL_UNITS[goal_type],
                total_periods,
                start.isoformat(),
                end.isoformat() if end else None,
                int(week_start),
                source,
                json.dumps(dict(rules or {}), ensure_ascii=False, sort_keys=True)[:8000],
                now,
                now,
            ),
        )
        conn.commit()
        goal = row_to_dict(conn.execute("SELECT * FROM health_goals WHERE id=?", (goal_id,)).fetchone())
    return {"status": "ok", "message": "健康目标已创建", "goal": goal, "progress": evaluate_goal(goal_id, owner_id=owner_id)["progress"]}


def get_goal(goal_id: str, owner_id: Optional[str] = None) -> Optional[dict]:
    ensure_db()
    conn = get_lifestyle_connection()
    try:
        row = conn.execute(
            "SELECT * FROM health_goals WHERE id=? AND is_deleted=0", (goal_id,)
        ).fetchone()
        goal = row_to_dict(row)
    finally:
        conn.close()
    if not goal or not _member(goal["member_id"], owner_id):
        return None
    return goal


def list_goals(member_id: str, owner_id: Optional[str] = None, include_inactive: bool = False) -> dict:
    ensure_db()
    member = _member(member_id, owner_id)
    if not member:
        return {"status": "error", "message": "未找到成员或无权访问"}
    conn = get_lifestyle_connection()
    try:
        sql = "SELECT * FROM health_goals WHERE member_id=? AND is_deleted=0"
        params: List[object] = [member_id]
        if not include_inactive:
            sql += " AND status IN ('active','paused')"
        sql += " ORDER BY created_at DESC"
        goals = rows_to_list(conn.execute(sql, params).fetchall())
    finally:
        conn.close()
    for goal in goals:
        evaluated = evaluate_goal(goal["id"], owner_id=owner_id)
        goal["progress"] = evaluated.get("progress")
    return {"status": "ok", "member": member, "goals": goals, "count": len(goals)}


def set_goal_status(goal_id: str, status: str, owner_id: Optional[str] = None) -> dict:
    if status not in VALID_STATUSES:
        return {"status": "error", "message": "目标状态无效"}
    goal = get_goal(goal_id, owner_id)
    if not goal:
        return {"status": "error", "message": "未找到目标或无权访问"}
    if goal["status"] in ("completed", "abandoned") and status == "active":
        return {"status": "error", "message": "已完成或已放弃的目标不能直接恢复"}
    if status == "active":
        conn = get_lifestyle_connection()
        try:
            conflict = conn.execute(
                """SELECT id FROM health_goals WHERE member_id=? AND domain=?
                   AND status='active' AND is_deleted=0 AND id<>?""",
                (goal["member_id"], goal["domain"], goal_id),
            ).fetchone()
        finally:
            conn.close()
        if conflict:
            return {"status": "error", "message": "该领域已有另一个进行中的目标"}
    with transaction(domain="lifestyle") as conn:
        conn.execute(
            "UPDATE health_goals SET status=?,updated_at=? WHERE id=?",
            (status, now_iso(), goal_id),
        )
        conn.commit()
    return {"status": "ok", "message": "目标状态已更新", "goal": get_goal(goal_id, owner_id)}


def _checkins(goal_id: str) -> List[dict]:
    conn = get_lifestyle_connection()
    try:
        return rows_to_list(
            conn.execute(
                """SELECT * FROM goal_checkins WHERE goal_id=? AND is_deleted=0
                   ORDER BY occurred_at,created_at""",
                (goal_id,),
            ).fetchall()
        )
    finally:
        conn.close()


def _store_milestone(
    goal: Mapping[str, object], milestone_key: str, milestone_type: str,
    evidence: Mapping[str, object], achieved_at: str,
) -> Optional[dict]:
    milestone_id = generate_id()
    try:
        with transaction(domain="lifestyle") as conn:
            conn.execute(
                """INSERT INTO goal_milestones
                   (id,goal_id,member_id,milestone_key,milestone_type,achieved_at,evidence,
                    goal_version,created_at,is_deleted)
                   VALUES (?,?,?,?,?,?,?,?,?,0)""",
                (
                    milestone_id,
                    goal["id"],
                    goal["member_id"],
                    milestone_key,
                    milestone_type,
                    achieved_at,
                    json.dumps(dict(evidence), ensure_ascii=False, sort_keys=True),
                    int(goal.get("version") or 1),
                    now_iso(),
                ),
            )
            conn.commit()
            return row_to_dict(
                conn.execute("SELECT * FROM goal_milestones WHERE id=?", (milestone_id,)).fetchone()
            )
    except sqlite3.IntegrityError:
        return None


def _completed_streak(period_values: Mapping[date, float], target: float) -> int:
    completed = sorted(day for day, value in period_values.items() if value >= target)
    if not completed:
        return 0
    streak = 1
    cursor = completed[-1]
    completed_set = set(completed)
    while cursor - timedelta(days=7) in completed_set:
        streak += 1
        cursor -= timedelta(days=7)
    return streak


def _ratio(value: float, target: float) -> float:
    return min(max(value / target, 0.0), 1.0) if target else 0.0


def _action_days(goal: Mapping[str, object], entries: Iterable[Mapping[str, object]]) -> List[dict]:
    """Collapse local evidence to one factual amount per calendar day."""
    values: Dict[date, float] = {}
    for entry in entries:
        day = _as_date(entry["occurred_at"])
        values[day] = values.get(day, 0.0) + _goal_measure(goal, entry)
    return [
        {"date": day.isoformat(), "weekday": day.weekday(), "value": round(value, 2)}
        for day, value in sorted(values.items())
    ]


def _progress_snapshot(
    goal: Mapping[str, object],
    entries: List[dict],
    period_values: Mapping[date, float],
    total_value: float,
    event_day: date,
) -> dict:
    """Freeze the exact goal state that existed when one event was earned."""
    target = float(goal["target_value"])
    is_weekly = str(goal["goal_type"]).startswith("weekly_")
    week_start = int(goal.get("week_start") or 0)
    event_period = _period_start(event_day, week_start)
    completed_periods = sum(1 for value in period_values.values() if value >= target)
    total_periods = goal.get("total_periods")
    if is_weekly and total_periods:
        overall_value = float(completed_periods)
        overall_target = float(total_periods)
    elif is_weekly:
        overall_value = None
        overall_target = None
    else:
        overall_value = total_value
        overall_target = target
    overall_ratio = (
        _ratio(float(overall_value), float(overall_target))
        if overall_value is not None and overall_target is not None else None
    )
    current_value = period_values.get(event_period, 0.0) if is_weekly else total_value
    period_entries = [
        entry for entry in entries
        if not is_weekly or _period_start(_as_date(entry["occurred_at"]), week_start) == event_period
    ]
    actions = _action_days(goal, period_entries if is_weekly else entries)
    action_dates = [_as_date(item["date"]) for item in actions]
    gaps = [
        (later - earlier).days for earlier, later in zip(action_dates, action_dates[1:])
    ]
    remaining_value = max(target - current_value, 0.0)
    remaining_periods = (
        max(int(total_periods) - completed_periods, 0)
        if is_weekly and total_periods else None
    )
    return {
        "schema_version": 2,
        "goal_title": goal["title"],
        "goal_type": goal["goal_type"],
        "target_value": target,
        "unit": goal["target_unit"],
        "achieved_value": round(current_value, 2),
        "checkin_count": len(entries),
        "distinct_action_days": len(actions),
        "action_days": actions,
        "spacing_days": gaps,
        "period_start": event_period.isoformat() if is_weekly else None,
        "period_end": (event_period + timedelta(days=6)).isoformat() if is_weekly else None,
        "completed_periods": completed_periods if is_weekly else None,
        "total_periods": total_periods,
        "overall_value": round(overall_value, 2) if overall_value is not None else None,
        "overall_target": overall_target,
        "overall_ratio": round(overall_ratio, 4) if overall_ratio is not None else None,
        "remaining_value": round(remaining_value, 2),
        "remaining_periods": remaining_periods,
    }


def _meaningful_milestone_candidates(
    goal: Mapping[str, object], entries: List[dict]
) -> List[tuple]:
    """Replay history and keep at most one meaningful card event per action.

    A normal check-in and an ordinary completed week stay as lightweight progress
    feedback. Cards are reserved for a newly demonstrated pattern, recovery,
    sustained consistency, a substantial halfway point, or completion.
    """
    target = float(goal["target_value"])
    goal_type = str(goal["goal_type"])
    is_weekly = goal_type.startswith("weekly_")
    week_start = int(goal.get("week_start") or 0)
    total_periods = goal.get("total_periods")
    period_values: Dict[date, float] = {}
    total_value = 0.0
    seen: List[dict] = []
    completed_periods: set[date] = set()
    rhythm_earned = False
    recovery_earned = False
    halfway_earned = False
    previous_day: Optional[date] = None
    candidates: List[tuple] = []

    for entry in entries:
        day = _as_date(entry["occurred_at"])
        amount = _goal_measure(goal, entry)
        event_period = _period_start(day, week_start)
        before_period = period_values.get(event_period, 0.0)
        before_total = total_value
        period_values[event_period] = before_period + amount
        total_value += amount
        seen.append(entry)

        period_completed_now = is_weekly and before_period < target <= period_values[event_period]
        if period_completed_now:
            completed_periods.add(event_period)
        snapshot = _progress_snapshot(goal, seen, period_values, total_value, day)
        event_options: List[tuple] = []

        overall_ratio = snapshot.get("overall_ratio")
        before_overall_ratio = None
        if is_weekly and total_periods:
            before_completed = snapshot["completed_periods"] - (1 if period_completed_now else 0)
            before_overall_ratio = _ratio(float(before_completed), float(total_periods))
        elif not is_weekly:
            before_overall_ratio = _ratio(before_total, target)

        if overall_ratio is not None and before_overall_ratio is not None:
            if before_overall_ratio < 1.0 <= float(overall_ratio):
                proof = dict(snapshot, reason_code="goal_completed")
                event_options.append((100, "completion", "completion", proof))

        gap_days = (day - previous_day).days if previous_day is not None else 0
        if gap_days >= 14 and not recovery_earned:
            proof = dict(
                snapshot,
                reason_code="returned_after_gap",
                gap_days=gap_days,
                previous_action_date=previous_day.isoformat(),
                return_action_date=day.isoformat(),
            )
            event_options.append((90, "recovery", "recovery", proof))

        if period_completed_now:
            streak = 1
            cursor = event_period
            while cursor - timedelta(days=7) in completed_periods:
                streak += 1
                cursor -= timedelta(days=7)
            if streak in (2, 4, 8):
                proof = dict(snapshot, reason_code="consecutive_completed_periods", streak=streak)
                event_options.append((80, "consistency-%d" % streak, "consistency", proof))
            if not rhythm_earned:
                proof = dict(snapshot, reason_code="first_complete_period")
                event_options.append((70, "rhythm-established", "rhythm", proof))

        if not is_weekly and not rhythm_earned and len(seen) >= 3:
            action_dates = sorted({_as_date(item["occurred_at"]) for item in seen})
            if len(action_dates) >= 3 and (action_dates[-1] - action_dates[0]).days >= 2:
                proof = dict(snapshot, reason_code="three_actions_across_days")
                event_options.append((70, "rhythm-established", "rhythm", proof))

        halfway_allowed = False
        if overall_ratio is not None and before_overall_ratio is not None:
            if is_weekly:
                halfway_allowed = bool(total_periods and int(total_periods) >= 4)
            elif goal_type == "cumulative_count":
                halfway_allowed = target >= 6
            else:
                halfway_allowed = target >= 120
        if (
            halfway_allowed and not halfway_earned
            and before_overall_ratio is not None and overall_ratio is not None
            and before_overall_ratio < 0.5 <= float(overall_ratio) < 1.0
        ):
            proof = dict(snapshot, reason_code="substantial_halfway")
            event_options.append((60, "halfway", "halfway", proof))

        if event_options:
            _, key, kind, proof = max(event_options, key=lambda item: item[0])
            achieved_at = entry["occurred_at"]
            candidates.append((key, kind, proof, achieved_at))
            if kind == "rhythm":
                rhythm_earned = True
            if kind == "recovery":
                recovery_earned = True
            if kind == "halfway":
                halfway_earned = True
            # A stronger event may have displaced a weaker one permanently. This is
            # intentional: one action should never spray several collectible cards.
            if any(option[2] == "rhythm" for option in event_options):
                rhythm_earned = True
            if any(option[2] == "recovery" for option in event_options):
                recovery_earned = True
            if any(option[2] == "halfway" for option in event_options):
                halfway_earned = True

        previous_day = day
    return candidates


def evaluate_goal(goal_id: str, *, owner_id: Optional[str] = None, as_of: Optional[str] = None) -> dict:
    """Calculate progress and persist newly earned milestones exactly once."""
    goal = get_goal(goal_id, owner_id)
    if not goal:
        return {"status": "error", "message": "未找到目标或无权访问"}
    today = _as_date(as_of, date.today())
    entries = [
        entry for entry in _checkins(goal_id)
        if _as_date(entry["occurred_at"]) <= today
    ]
    target = float(goal["target_value"])
    goal_type = goal["goal_type"]
    start = _as_date(goal["start_date"])
    week_start = int(goal.get("week_start") or 0)
    current_period = _period_start(today, week_start)
    period_values: Dict[date, float] = {}
    total_value = 0.0
    for entry in entries:
        occurred = _as_date(entry["occurred_at"])
        if occurred < start:
            continue
        amount = _goal_measure(goal, entry)
        total_value += amount
        period = _period_start(occurred, week_start)
        period_values[period] = period_values.get(period, 0.0) + amount

    is_weekly = goal_type.startswith("weekly_")
    current_value = period_values.get(current_period, 0.0) if is_weekly else total_value
    current_ratio = min(current_value / target, 1.0) if target else 0.0
    completed_periods = sum(1 for value in period_values.values() if value >= target)
    total_periods = goal.get("total_periods")
    if is_weekly and total_periods:
        overall_value = float(completed_periods)
        overall_target = float(total_periods)
        overall_ratio = min(overall_value / overall_target, 1.0)
    elif is_weekly:
        overall_value = None
        overall_target = None
        overall_ratio = None
    else:
        overall_value = total_value
        overall_target = target
        overall_ratio = min(total_value / target, 1.0) if target else 0.0

    streak = _completed_streak(period_values, target) if is_weekly else 0
    progress = {
        "goal_id": goal_id,
        "goal_type": goal_type,
        "status": goal["status"],
        "target_value": target,
        "unit": goal["target_unit"],
        "current_period_start": current_period.isoformat() if is_weekly else None,
        "current_value": round(current_value, 2),
        "current_ratio": round(current_ratio, 4),
        "completed_periods": completed_periods if is_weekly else None,
        "total_periods": total_periods,
        "overall_value": round(overall_value, 2) if overall_value is not None else None,
        "overall_target": overall_target,
        "overall_ratio": round(overall_ratio, 4) if overall_ratio is not None else None,
        "checkin_count": len(entries),
        "consistency_streak": streak,
    }

    new_milestones: List[dict] = []
    for key, kind, proof, achieved_at in _meaningful_milestone_candidates(goal, entries):
        created = _store_milestone(goal, key, kind, proof, achieved_at)
        if created:
            new_milestones.append(created)

    completed_now = overall_ratio is not None and overall_ratio >= 1.0
    if completed_now and goal["status"] == "active":
        with transaction(domain="lifestyle") as conn:
            conn.execute(
                "UPDATE health_goals SET status='completed',updated_at=? WHERE id=?",
                (now_iso(), goal_id),
            )
            conn.commit()
        progress["status"] = "completed"

    if is_weekly:
        remaining = max(target - current_value, 0.0)
    else:
        remaining = max(target - total_value, 0.0)
    progress["remaining"] = round(remaining, 2)
    return {
        "status": "ok",
        "goal": get_goal(goal_id, owner_id),
        "progress": progress,
        "new_milestones": new_milestones,
        "new_milestone_count": len(new_milestones),
    }


def record_checkin(
    goal_id: str,
    *,
    occurred_at: Optional[str] = None,
    value: Optional[float] = None,
    duration_minutes: Optional[float] = None,
    source: str = "manual",
    source_record_type: Optional[str] = None,
    source_record_id: Optional[str] = None,
    note: Optional[str] = None,
    owner_id: Optional[str] = None,
) -> dict:
    goal = get_goal(goal_id, owner_id)
    if not goal:
        return {"status": "error", "message": "未找到目标或无权访问"}
    if goal["status"] != "active":
        return {"status": "error", "message": "只有进行中的目标可以打卡"}
    if bool(source_record_type) != bool(source_record_id):
        return {"status": "error", "message": "source_record_type 和 source_record_id 必须同时提供"}
    try:
        occurred = _as_datetime_text(occurred_at)
        numeric_value = float(value if value is not None else 1)
        numeric_duration = float(duration_minutes) if duration_minutes is not None else None
    except (TypeError, ValueError) as exc:
        return {"status": "error", "message": str(exc)}
    if (not math.isfinite(numeric_value) or numeric_value < 0 or numeric_value > 1000000
            or (numeric_duration is not None and (
                not math.isfinite(numeric_duration) or numeric_duration <= 0 or numeric_duration > 1440
            ))):
        return {"status": "error", "message": "打卡值必须大于等于 0，时长必须大于 0"}
    if goal["goal_type"].endswith("duration") and numeric_duration is None and value is None:
        return {"status": "error", "message": "时长目标的打卡必须提供 duration_minutes"}
    checkin_id = generate_id()
    try:
        with transaction(domain="lifestyle") as conn:
            conn.execute(
                """INSERT INTO goal_checkins
                   (id,goal_id,member_id,occurred_at,value,unit,duration_minutes,source,
                    source_record_type,source_record_id,note,created_at,is_deleted)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (
                    checkin_id,
                    goal_id,
                    goal["member_id"],
                    occurred,
                    numeric_value,
                    goal["target_unit"],
                    numeric_duration,
                    str(source or "manual").strip()[:40] or "manual",
                    str(source_record_type).strip()[:60] if source_record_type else None,
                    str(source_record_id).strip()[:120] if source_record_id else None,
                    str(note).strip()[:500] if note else None,
                    now_iso(),
                ),
            )
            conn.commit()
    except sqlite3.IntegrityError:
        return {"status": "ok", "message": "这条来源记录已经关联过目标", "duplicate": True, "progress": evaluate_goal(goal_id, owner_id=owner_id)["progress"]}
    evaluated = evaluate_goal(goal_id, owner_id=owner_id, as_of=occurred[:10])
    milestones = evaluated["new_milestones"]
    if milestones:
        feedback = {
            "kind": "meaningful_milestone",
            "title": "出现了一个值得保存的阶段",
            "card_available": True,
            "milestone_ids": [item["id"] for item in milestones],
        }
    elif evaluated["progress"].get("current_ratio") == 1.0 and goal["goal_type"].startswith("weekly_"):
        feedback = {
            "kind": "period_recorded",
            "title": "本周期目标已经完成",
            "card_available": False,
        }
    else:
        feedback = {
            "kind": "checkin_recorded",
            "title": "这次行动已记录",
            "card_available": False,
        }
    return {
        "status": "ok",
        "message": "目标打卡已记录",
        "checkin_id": checkin_id,
        "duplicate": False,
        "progress": evaluated["progress"],
        "new_milestones": milestones,
        "feedback": feedback,
    }


def record_activity_source(
    member_id: str,
    *,
    source_record_type: str,
    source_record_id: str,
    occurred_at: str,
    duration_minutes: Optional[float] = None,
    owner_id: Optional[str] = None,
) -> List[dict]:
    """Link one committed manual/device workout to the active activity goal."""
    ensure_db()
    if not _member(member_id, owner_id):
        return []
    conn = get_lifestyle_connection()
    try:
        goals = rows_to_list(
            conn.execute(
                """SELECT * FROM health_goals WHERE member_id=? AND domain='activity'
                   AND status='active' AND is_deleted=0 ORDER BY created_at DESC""",
                (member_id,),
            ).fetchall()
        )
    finally:
        conn.close()
    results = []
    for goal in goals:
        if goal["goal_type"].endswith("duration") and not duration_minutes:
            continue
        results.append(
            record_checkin(
                goal["id"],
                occurred_at=occurred_at,
                duration_minutes=duration_minutes,
                source="linked_record",
                source_record_type=source_record_type,
                source_record_id=source_record_id,
                owner_id=owner_id,
            )
        )
    return results


def list_milestones(
    goal_id: str, owner_id: Optional[str] = None, unclaimed_only: bool = False
) -> dict:
    goal = get_goal(goal_id, owner_id)
    if not goal:
        return {"status": "error", "message": "未找到目标或无权访问"}
    conn = get_lifestyle_connection()
    try:
        sql = "SELECT * FROM goal_milestones WHERE goal_id=? AND is_deleted=0"
        params: List[object] = [goal_id]
        if unclaimed_only:
            sql += " AND claimed_at IS NULL"
        sql += " ORDER BY achieved_at DESC,created_at DESC"
        milestones = rows_to_list(conn.execute(sql, params).fetchall())
    finally:
        conn.close()
    for milestone in milestones:
        try:
            milestone["evidence"] = json.loads(milestone.get("evidence") or "{}")
        except (TypeError, ValueError):
            milestone["evidence"] = {}
    return {"status": "ok", "goal": goal, "milestones": milestones, "count": len(milestones)}
