"""Reminder management for MediWise Health Tracker.

Supports medication reminders, metric measurement reminders, checkup reminders,
and custom reminders with flexible scheduling (once, daily, weekly, monthly, cycle).
"""
from __future__ import annotations

import sys
import json
import calendar
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import health_db


def _verify_member_access(conn, member_id: str, owner_id: str = None) -> bool:
    return health_db.verify_member_ownership(conn, member_id, owner_id)


def _verify_reminder_access(conn, reminder_id: str, owner_id: str = None) -> bool:
    return health_db.verify_record_ownership(conn, "reminders", reminder_id, owner_id)


# --- Schedule computation ---

def compute_next_trigger(schedule_type: str, schedule_value: str, from_time: datetime = None, timezone: str = None) -> str | None:
    """Compute the next trigger time based on schedule type and value.

    schedule_type: once | daily | weekly | monthly
    schedule_value:
      - once: ISO datetime "2025-03-15 09:00"
      - daily: time "08:00"
      - weekly: "monday 09:00" or "1 09:00" (1=monday)
      - monthly: "15 09:00" (day-of-month + time)

    Returns ISO datetime string or None if schedule is exhausted (past one-time).
    """
    now = from_time or datetime.now()

    tz = None
    if timezone:
        try:
            tz = ZoneInfo(timezone)
            if from_time is None:
                now = datetime.now(tz)
        except (KeyError, Exception):
            pass  # Invalid timezone, fall back to local time

    if schedule_type == "once":
        target = datetime.strptime(schedule_value, "%Y-%m-%d %H:%M")
        return target.strftime("%Y-%m-%d %H:%M:%S") if target > now else None

    if schedule_type == "daily":
        hour, minute = map(int, schedule_value.split(":"))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target.strftime("%Y-%m-%d %H:%M:%S")

    if schedule_type == "weekly":
        parts = schedule_value.lower().split()
        day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                   "friday": 4, "saturday": 5, "sunday": 6}
        if parts[0] in day_map:
            target_weekday = day_map[parts[0]]
        else:
            target_weekday = int(parts[0]) - 1  # 1=monday
        time_parts = parts[1].split(":")
        hour, minute = int(time_parts[0]), int(time_parts[1])
        days_ahead = target_weekday - now.weekday()
        if days_ahead < 0 or (days_ahead == 0 and now.hour * 60 + now.minute >= hour * 60 + minute):
            days_ahead += 7
        target = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target.strftime("%Y-%m-%d %H:%M:%S")

    if schedule_type == "monthly":
        parts = schedule_value.split()
        day = int(parts[0])
        time_parts = parts[1].split(":")
        hour, minute = int(time_parts[0]), int(time_parts[1])
        _, last_day = calendar.monthrange(now.year, now.month)
        target = now.replace(day=min(day, last_day), hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            month = now.month + 1
            year = now.year
            if month > 12:
                month = 1
                year += 1
            _, next_last_day = calendar.monthrange(year, month)
            target = target.replace(year=year, month=month, day=min(day, next_last_day))
        return target.strftime("%Y-%m-%d %H:%M:%S")

    if schedule_type == "cycle":
        # schedule_value format: "member_id:cycle_type:days_before"
        # e.g. "abc123:menstrual:3" means 3 days before predicted period
        try:
            parts = schedule_value.split(":")
            if len(parts) != 3:
                return None
            cycle_member_id, cycle_type, days_before_str = parts
            days_before = int(days_before_str)

            import cycle_tracker
            prediction = cycle_tracker.predict_next_cycle(cycle_member_id, cycle_type)
            if prediction.get("error") or not prediction.get("predicted_start"):
                return None

            predicted_start = datetime.strptime(prediction["predicted_start"], "%Y-%m-%d")
            target = predicted_start - timedelta(days=days_before)
            # Set to 09:00 on that day
            target = target.replace(hour=9, minute=0, second=0, microsecond=0)

            if target <= now:
                # If target already passed, return None (will be recomputed next cycle)
                return None
            return target.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, ImportError):
            return None

    return None


# --- CRUD ---

def create_reminder(member_id: str, reminder_type: str, title: str,
                    schedule_type: str, schedule_value: str,
                    content: str = None, related_record_id: str = None,
                    related_record_type: str = None, priority: str = "normal",
                    timezone: str = None, owner_id: str = None) -> dict:
    """Create a new reminder."""
    health_db.ensure_db()
    rid = health_db.generate_id()
    now = health_db.now_iso()
    next_trigger = compute_next_trigger(schedule_type, schedule_value, timezone=timezone)

    if next_trigger is None and schedule_type == "once":
        return {"error": "一次性提醒的时间已过期"}

    with health_db.transaction() as conn:
        if not _verify_member_access(conn, member_id, owner_id):
            return {"error": f"无权访问成员: {member_id}"}
        conn.execute(
            """INSERT INTO reminders (id, member_id, type, title, content, schedule_type,
               schedule_value, next_trigger_at, related_record_id, related_record_type,
               priority, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rid, member_id, reminder_type, title, content, schedule_type,
             schedule_value, next_trigger, related_record_id, related_record_type,
             priority, now, now)
        )
        conn.commit()
    return {"id": rid, "title": title, "next_trigger_at": next_trigger}


def update_reminder(reminder_id: str, **kwargs) -> dict:
    """Update a reminder. Supported fields: title, content, schedule_type, schedule_value,
    is_active, priority."""
    health_db.ensure_db()
    allowed = {"title", "content", "schedule_type", "schedule_value", "is_active", "priority"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    owner_id = kwargs.get("owner_id")
    if not updates:
        return {"error": "没有可更新的字段"}

    # Recompute next_trigger if schedule changed
    if "schedule_type" in updates or "schedule_value" in updates:
        conn = health_db.get_connection()
        try:
            if not _verify_reminder_access(conn, reminder_id, owner_id):
                return {"error": f"无权访问提醒: {reminder_id}"}
            row = conn.execute("SELECT schedule_type, schedule_value FROM reminders WHERE id=? AND is_deleted=0",
                               (reminder_id,)).fetchone()
            if not row:
                return {"error": f"未找到提醒: {reminder_id}"}
            st = updates.get("schedule_type", row["schedule_type"])
            sv = updates.get("schedule_value", row["schedule_value"])
            updates["next_trigger_at"] = compute_next_trigger(st, sv)
        finally:
            conn.close()

    updates["updated_at"] = health_db.now_iso()
    set_clause = ", ".join(f"{k}=?" for k in updates)
    values = list(updates.values()) + [reminder_id]

    with health_db.transaction() as conn:
        if not _verify_reminder_access(conn, reminder_id, owner_id):
            return {"error": f"无权访问提醒: {reminder_id}"}
        conn.execute(f"UPDATE reminders SET {set_clause} WHERE id=? AND is_deleted=0", values)
        conn.commit()
    return {"id": reminder_id, "updated": list(updates.keys())}


def delete_reminder(reminder_id: str, owner_id: str = None) -> dict:
    """Soft-delete a reminder."""
    health_db.ensure_db()
    now = health_db.now_iso()
    with health_db.transaction() as conn:
        if not _verify_reminder_access(conn, reminder_id, owner_id):
            return {"error": f"无权访问提醒: {reminder_id}"}
        conn.execute("UPDATE reminders SET is_deleted=1, is_active=0, updated_at=? WHERE id=?",
                     (now, reminder_id))
        conn.commit()
    return {"id": reminder_id, "deleted": True}


def list_reminders(member_id: str = None, active_only: bool = True, owner_id: str = None) -> dict:
    """List reminders, optionally filtered by member and active status."""
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        sql = "SELECT r.* FROM reminders r"
        params = []
        clauses = ["r.is_deleted=0"]
        if owner_id:
            sql += " JOIN members m ON r.member_id = m.id AND m.is_deleted=0"
            clauses.append("m.owner_id=?")
            params.append(owner_id)
        if member_id:
            if not _verify_member_access(conn, member_id, owner_id):
                return {"error": f"无权访问成员: {member_id}"}
            clauses.append("r.member_id=?")
            params.append(member_id)
        if active_only:
            clauses.append("r.is_active=1")
        sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY r.next_trigger_at"
        rows = health_db.rows_to_list(conn.execute(sql, params).fetchall())
        return {"reminders": rows, "count": len(rows)}
    finally:
        conn.close()


def get_due_reminders() -> list[dict]:
    """Get all active reminders whose next_trigger_at <= now."""
    health_db.ensure_db()
    now = health_db.now_iso()
    conn = health_db.get_connection()
    try:
        rows = conn.execute(
            """SELECT r.*, m.name as member_name FROM reminders r
               JOIN members m ON r.member_id = m.id
               WHERE r.is_deleted=0 AND r.is_active=1
               AND r.next_trigger_at IS NOT NULL AND r.next_trigger_at <= ?
               ORDER BY r.priority DESC, r.next_trigger_at""",
            (now,)
        ).fetchall()
        return health_db.rows_to_list(rows)
    finally:
        conn.close()


def mark_triggered(reminder_id: str, channel: str = "session",
                   status: str = "delivered") -> dict:
    """Log a reminder trigger and advance next_trigger_at."""
    health_db.ensure_db()
    now = health_db.now_iso()
    log_id = health_db.generate_id()

    with health_db.transaction() as conn:
        # Insert log
        conn.execute(
            """INSERT INTO reminder_logs (id, reminder_id, triggered_at, delivery_channel,
               delivery_status, created_at) VALUES (?, ?, ?, ?, ?, ?)""",
            (log_id, reminder_id, now, channel, status, now)
        )
        # Get current schedule to compute next trigger
        row = conn.execute("SELECT schedule_type, schedule_value FROM reminders WHERE id=?",
                           (reminder_id,)).fetchone()
        if row:
            next_trigger = compute_next_trigger(row["schedule_type"], row["schedule_value"])
            if next_trigger is None:
                # One-time reminder exhausted, deactivate
                conn.execute("UPDATE reminders SET is_active=0, last_triggered_at=?, updated_at=? WHERE id=?",
                             (now, now, reminder_id))
            else:
                conn.execute("UPDATE reminders SET next_trigger_at=?, last_triggered_at=?, updated_at=? WHERE id=?",
                             (next_trigger, now, now, reminder_id))
        conn.commit()
    return {"log_id": log_id, "reminder_id": reminder_id, "status": status}


def auto_create_medication_reminders(member_id: str) -> dict:
    """Auto-create reminders for all active medications of a member.

    Uses the medication's frequency field to determine schedule:
    - "每日一次" / "once daily" → daily 08:00
    - "每日两次" / "twice daily" → daily 08:00 + 20:00
    - "每日三次" / "three times daily" → daily 08:00 + 13:00 + 20:00
    """
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        meds = health_db.rows_to_list(conn.execute(
            "SELECT * FROM medications WHERE member_id=? AND is_deleted=0 AND end_date IS NULL",
            (member_id,)
        ).fetchall())
    finally:
        conn.close()

    if not meds:
        return {"created": 0, "message": "没有在用药物"}

    # Check existing medication reminders to avoid duplicates
    existing = list_reminders(member_id, active_only=True)
    existing_med_ids = {r.get("related_record_id") for r in existing.get("reminders", [])
                       if r.get("type") == "medication"}

    created = []
    for med in meds:
        if med["id"] in existing_med_ids:
            continue

        freq = (med.get("frequency") or "").lower()
        times = ["08:00"]  # default
        if any(k in freq for k in ["两次", "twice", "2次", "bid"]):
            times = ["08:00", "20:00"]
        elif any(k in freq for k in ["三次", "three", "3次", "tid"]):
            times = ["08:00", "13:00", "20:00"]

        for t in times:
            result = create_reminder(
                member_id=member_id,
                reminder_type="medication",
                title=f"服药提醒：{med['name']}",
                schedule_type="daily",
                schedule_value=t,
                content=f"{med['name']} {med.get('dosage', '')} - {med.get('frequency', '')}".strip(),
                related_record_id=med["id"],
                related_record_type="medication",
                priority="high"
            )
            created.append(result)

    return {"created": len(created), "reminders": created}


def auto_create_cycle_reminders(member_id: str, cycle_type: str = "menstrual") -> dict:
    """Auto-create cycle reminders: 3 days before, 1 day before, and on the day.

    Creates three reminders with cycle schedule type for the specified member and cycle type.
    """
    health_db.ensure_db()

    # Check existing cycle reminders to avoid duplicates
    existing = list_reminders(member_id, active_only=True)
    existing_cycle = [
        r for r in existing.get("reminders", [])
        if r.get("type") == "cycle" and r.get("schedule_type") == "cycle"
        and r.get("schedule_value", "").startswith(f"{member_id}:{cycle_type}:")
    ]

    if existing_cycle:
        return {"created": 0, "message": f"已存在 {len(existing_cycle)} 个 {cycle_type} 周期提醒，跳过创建"}

    labels = {
        "menstrual": {3: "经期预告（3天后）", 1: "经期即将到来（明天）", 0: "经期提醒（今天）"},
        "migraine": {3: "偏头痛预警（3天内）", 1: "偏头痛预警（明天）", 0: "偏头痛关注日"},
        "allergy": {3: "过敏季预警（3天内）", 1: "过敏季预警（明天）", 0: "过敏季关注日"},
    }
    default_labels = {3: "周期预警（3天内）", 1: "周期预警（明天）", 0: "周期提醒（今天）"}

    created = []
    for days_before in [3, 1, 0]:
        title = labels.get(cycle_type, default_labels).get(days_before, f"周期提醒（{days_before}天前）")
        result = create_reminder(
            member_id=member_id,
            reminder_type="cycle",
            title=title,
            schedule_type="cycle",
            schedule_value=f"{member_id}:{cycle_type}:{days_before}",
            priority="normal" if days_before > 0 else "high",
        )
        created.append(result)

    return {"created": len(created), "cycle_type": cycle_type, "reminders": created}


# --- CLI interface ---

def main():
    if len(sys.argv) < 2:
        health_db.output_json({"error": "用法: reminder.py <command> [args]"})
        return

    health_db.ensure_db()
    cmd = sys.argv[1]

    if cmd == "create":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id", required=True)
        p.add_argument("--owner-id", default=None)
        p.add_argument("--type", required=True, choices=["medication", "metric", "checkup", "custom", "cycle"])
        p.add_argument("--title", required=True)
        p.add_argument("--schedule-type", required=True, choices=["once", "daily", "weekly", "monthly", "cycle"])
        p.add_argument("--schedule-value", required=True)
        p.add_argument("--content")
        p.add_argument("--related-record-id")
        p.add_argument("--related-record-type")
        p.add_argument("--priority", default="normal", choices=["low", "normal", "high", "urgent"])
        args = p.parse_args(sys.argv[2:])
        result = create_reminder(args.member_id, args.type, args.title,
                                 args.schedule_type, args.schedule_value,
                                 args.content, args.related_record_id,
                                 args.related_record_type, args.priority,
                                 owner_id=args.owner_id)
        health_db.output_json(result)

    elif cmd == "list":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id")
        p.add_argument("--owner-id", default=None)
        p.add_argument("--all", action="store_true", help="Include inactive reminders")
        args = p.parse_args(sys.argv[2:])
        result = list_reminders(args.member_id, active_only=not args.all, owner_id=args.owner_id)
        health_db.output_json(result)

    elif cmd == "update":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--reminder-id", required=True)
        p.add_argument("--title")
        p.add_argument("--content")
        p.add_argument("--schedule-type")
        p.add_argument("--schedule-value")
        p.add_argument("--is-active", type=int, choices=[0, 1])
        p.add_argument("--priority", choices=["low", "normal", "high", "urgent"])
        p.add_argument("--owner-id", default=None)
        args = p.parse_args(sys.argv[2:])
        kwargs = {k.replace("-", "_"): v for k, v in vars(args).items()
                  if k != "reminder_id" and v is not None}
        result = update_reminder(args.reminder_id, **kwargs)
        health_db.output_json(result)

    elif cmd == "delete":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--reminder-id", required=True)
        p.add_argument("--owner-id", default=None)
        args = p.parse_args(sys.argv[2:])
        result = delete_reminder(args.reminder_id, args.owner_id)
        health_db.output_json(result)

    elif cmd == "due":
        result = get_due_reminders()
        health_db.output_json({"due_reminders": result, "count": len(result)})

    elif cmd == "mark-triggered":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--reminder-id", required=True)
        p.add_argument("--channel", default="session")
        p.add_argument("--status", default="delivered")
        args = p.parse_args(sys.argv[2:])
        result = mark_triggered(args.reminder_id, args.channel, args.status)
        health_db.output_json(result)

    elif cmd == "auto-medication":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id", required=True)
        p.add_argument("--owner-id", default=None)
        args = p.parse_args(sys.argv[2:])
        conn = health_db.get_connection()
        try:
            if not _verify_member_access(conn, args.member_id, args.owner_id):
                health_db.output_json({"error": f"无权访问成员: {args.member_id}"})
                return
        finally:
            conn.close()
        result = auto_create_medication_reminders(args.member_id)
        health_db.output_json(result)

    elif cmd == "auto-cycle":
        import argparse
        p = argparse.ArgumentParser()
        p.add_argument("--member-id", required=True)
        p.add_argument("--owner-id", default=None)
        p.add_argument("--cycle-type", default="menstrual", choices=["menstrual", "migraine", "allergy", "custom"])
        args = p.parse_args(sys.argv[2:])
        conn = health_db.get_connection()
        try:
            if not _verify_member_access(conn, args.member_id, args.owner_id):
                health_db.output_json({"error": f"无权访问成员: {args.member_id}"})
                return
        finally:
            conn.close()
        result = auto_create_cycle_reminders(args.member_id, args.cycle_type)
        health_db.output_json(result)

    else:
        health_db.output_json({"error": f"未知命令: {cmd}", "commands": ["create", "list", "update", "delete", "due", "mark-triggered", "auto-medication", "auto-cycle"]})


if __name__ == "__main__":
    main()
