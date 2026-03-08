"""体重目标设定与管理。"""

from __future__ import annotations

import argparse
import sys
import os
from datetime import datetime

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from path_setup import setup_mediwise_path
setup_mediwise_path()

from health_db import ensure_db, get_connection, generate_id, now_iso, row_to_dict, output_json, transaction
from validators import validate_date_optional
from metric_utils import calculate_age, calculate_bmr, calculate_tdee

VALID_GOAL_TYPES = ["lose", "gain", "maintain"]
GOAL_TYPE_NAMES = {"lose": "减重", "gain": "增重", "maintain": "维持"}

ACTIVITY_LEVELS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}


def set_goal(args):
    """设定体重目标。"""
    ensure_db()
    with transaction() as conn:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        if args.goal_type not in VALID_GOAL_TYPES:
            output_json({"status": "error", "message": f"不支持的目标类型: {args.goal_type}，支持: {', '.join(VALID_GOAL_TYPES)}"})
            return

        try:
            start_weight = float(args.start_weight)
            target_weight = float(args.target_weight)
        except (ValueError, TypeError):
            output_json({"status": "error", "message": "起始体重和目标体重必须为数值"})
            return

        if not (0.5 <= start_weight <= 500) or not (0.5 <= target_weight <= 500):
            output_json({"status": "error", "message": "体重值应在 0.5-500 kg 范围内"})
            return

        # Validate goal consistency
        if args.goal_type == "lose" and target_weight >= start_weight:
            output_json({"status": "error", "message": "减重目标的目标体重应低于起始体重"})
            return
        if args.goal_type == "gain" and target_weight <= start_weight:
            output_json({"status": "error", "message": "增重目标的目标体重应高于起始体重"})
            return

        # Check for existing active goal
        existing = conn.execute(
            "SELECT id FROM weight_goals WHERE member_id=? AND status='active' AND is_deleted=0",
            (args.member_id,)
        ).fetchone()
        if existing:
            output_json({
                "status": "error",
                "message": f"该成员已有一个活跃目标 ({existing['id']})，请先完成或放弃现有目标"
            })
            return

        try:
            start_date = validate_date_optional(args.start_date, "开始日期") or datetime.now().strftime("%Y-%m-%d")
            target_date = validate_date_optional(args.target_date, "目标日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        daily_calorie_target = None
        auto_calorie_target = None
        if args.daily_calorie_target is not None:
            try:
                daily_calorie_target = int(args.daily_calorie_target)
                if daily_calorie_target < 800 or daily_calorie_target > 10000:
                    output_json({"status": "error", "message": "每日热量目标应在 800-10000 kcal 范围内"})
                    return
            except (ValueError, TypeError):
                output_json({"status": "error", "message": "每日热量目标必须为整数"})
                return
        else:
            # Auto-calculate from BMR/TDEE if member has enough data
            member = conn.execute(
                "SELECT gender, birth_date FROM members WHERE id=? AND is_deleted=0",
                (args.member_id,)
            ).fetchone()
            if member and member["gender"] in ("male", "female") and member["birth_date"]:
                weight_data = conn.execute(
                    """SELECT value FROM health_metrics WHERE member_id=? AND metric_type='weight' AND is_deleted=0
                       ORDER BY measured_at DESC LIMIT 1""",
                    (args.member_id,)
                ).fetchone()
                height_data = conn.execute(
                    """SELECT value FROM health_metrics WHERE member_id=? AND metric_type='height' AND is_deleted=0
                       ORDER BY measured_at DESC LIMIT 1""",
                    (args.member_id,)
                ).fetchone()
                if weight_data and height_data:
                    try:
                        w = float(weight_data["value"])
                        h = float(height_data["value"])
                        age = calculate_age(member["birth_date"])
                        bmr = calculate_bmr(w, h, age, member["gender"])

                        activity_level = getattr(args, 'activity_level', None) or "sedentary"
                        tdee = calculate_tdee(bmr, activity_level)

                        if args.goal_type == "lose":
                            suggested = tdee - 500
                        elif args.goal_type == "gain":
                            suggested = tdee + 300
                        else:
                            suggested = tdee

                        min_cal = 1500 if member["gender"] == "male" else 1200
                        suggested = max(suggested, min_cal)
                        auto_calorie_target = round(suggested)
                        daily_calorie_target = auto_calorie_target
                    except (ValueError, TypeError):
                        pass

        goal_id = generate_id()
        now = now_iso()
        conn.execute(
            """INSERT INTO weight_goals
               (id, member_id, goal_type, start_weight, target_weight, start_date, target_date,
                daily_calorie_target, status, note, created_at, updated_at, is_deleted)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, 0)""",
            (goal_id, args.member_id, args.goal_type, start_weight, target_weight,
             start_date, target_date, daily_calorie_target, args.note, now, now)
        )
        conn.commit()

        goal = row_to_dict(conn.execute("SELECT * FROM weight_goals WHERE id=?", (goal_id,)).fetchone())
        type_name = GOAL_TYPE_NAMES.get(args.goal_type, args.goal_type)
        diff = abs(target_weight - start_weight)
        result = {
            "status": "ok",
            "message": f"已为{m['name']}设定{type_name}目标: {start_weight}kg → {target_weight}kg（{diff:.1f}kg）",
            "goal": goal
        }
        if auto_calorie_target is not None:
            result["auto_calorie_target"] = auto_calorie_target
            result["message"] += f"，已自动设定每日热量目标 {auto_calorie_target} kcal"
        output_json(result)


def view_goal(args):
    """查看当前活跃目标。"""
    ensure_db()
    conn = get_connection()
    try:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        goal = conn.execute(
            "SELECT * FROM weight_goals WHERE member_id=? AND status='active' AND is_deleted=0",
            (args.member_id,)
        ).fetchone()

        if not goal:
            # Show most recent completed/abandoned goal if no active one
            goal = conn.execute(
                "SELECT * FROM weight_goals WHERE member_id=? AND is_deleted=0 ORDER BY updated_at DESC LIMIT 1",
                (args.member_id,)
            ).fetchone()
            if goal:
                output_json({
                    "status": "ok",
                    "message": f"{m['name']}当前无活跃目标，最近的目标状态为: {goal['status']}",
                    "goal": row_to_dict(goal),
                    "has_active": False
                })
            else:
                output_json({
                    "status": "ok",
                    "message": f"{m['name']}尚未设定过体重目标",
                    "goal": None,
                    "has_active": False
                })
            return

        output_json({
            "status": "ok",
            "member_name": m["name"],
            "goal": row_to_dict(goal),
            "has_active": True
        })
    finally:
        conn.close()


def update_goal(args):
    """修改目标参数。"""
    ensure_db()
    with transaction() as conn:
        goal = conn.execute(
            "SELECT * FROM weight_goals WHERE id=? AND is_deleted=0", (args.goal_id,)
        ).fetchone()
        if not goal:
            output_json({"status": "error", "message": f"未找到目标: {args.goal_id}"})
            return
        if goal["status"] != "active":
            output_json({"status": "error", "message": f"目标状态为 {goal['status']}，仅活跃目标可修改"})
            return

        updates = []
        params = []

        if args.target_weight is not None:
            try:
                tw = float(args.target_weight)
                if not (0.5 <= tw <= 500):
                    output_json({"status": "error", "message": "体重值应在 0.5-500 kg 范围内"})
                    return
            except (ValueError, TypeError):
                output_json({"status": "error", "message": "目标体重必须为数值"})
                return
            updates.append("target_weight=?")
            params.append(tw)

        if args.target_date is not None:
            try:
                td = validate_date_optional(args.target_date, "目标日期")
            except ValueError as e:
                output_json({"status": "error", "message": str(e)})
                return
            updates.append("target_date=?")
            params.append(td)

        if args.daily_calorie_target is not None:
            try:
                dct = int(args.daily_calorie_target)
                if dct < 800 or dct > 10000:
                    output_json({"status": "error", "message": "每日热量目标应在 800-10000 kcal 范围内"})
                    return
            except (ValueError, TypeError):
                output_json({"status": "error", "message": "每日热量目标必须为整数"})
                return
            updates.append("daily_calorie_target=?")
            params.append(dct)

        if args.note is not None:
            updates.append("note=?")
            params.append(args.note)

        if not updates:
            output_json({"status": "error", "message": "未指定要更新的字段"})
            return

        updates.append("updated_at=?")
        params.append(now_iso())
        params.append(args.goal_id)

        conn.execute(f"UPDATE weight_goals SET {', '.join(updates)} WHERE id=?", params)
        conn.commit()

        updated = row_to_dict(conn.execute("SELECT * FROM weight_goals WHERE id=?", (args.goal_id,)).fetchone())
        output_json({"status": "ok", "message": "目标已更新", "goal": updated})


def complete_goal(args):
    """标记目标完成。"""
    ensure_db()
    with transaction() as conn:
        goal = conn.execute(
            "SELECT * FROM weight_goals WHERE id=? AND is_deleted=0", (args.goal_id,)
        ).fetchone()
        if not goal:
            output_json({"status": "error", "message": f"未找到目标: {args.goal_id}"})
            return
        if goal["status"] != "active":
            output_json({"status": "error", "message": f"目标状态为 {goal['status']}，仅活跃目标可标记完成"})
            return

        now = now_iso()
        conn.execute(
            "UPDATE weight_goals SET status='completed', updated_at=? WHERE id=?",
            (now, args.goal_id)
        )
        conn.commit()
        output_json({"status": "ok", "message": "目标已标记为完成"})


def abandon_goal(args):
    """放弃目标。"""
    ensure_db()
    with transaction() as conn:
        goal = conn.execute(
            "SELECT * FROM weight_goals WHERE id=? AND is_deleted=0", (args.goal_id,)
        ).fetchone()
        if not goal:
            output_json({"status": "error", "message": f"未找到目标: {args.goal_id}"})
            return
        if goal["status"] != "active":
            output_json({"status": "error", "message": f"目标状态为 {goal['status']}，仅活跃目标可放弃"})
            return

        now = now_iso()
        conn.execute(
            "UPDATE weight_goals SET status='abandoned', updated_at=? WHERE id=?",
            (now, args.goal_id)
        )
        conn.commit()
        output_json({"status": "ok", "message": "目标已放弃"})


def main():
    parser = argparse.ArgumentParser(description="体重目标管理")
    sub = parser.add_subparsers(dest="command", required=True)

    # set
    p_set = sub.add_parser("set")
    p_set.add_argument("--member-id", required=True)
    p_set.add_argument("--goal-type", required=True, help="目标类型: lose/gain/maintain")
    p_set.add_argument("--start-weight", required=True, help="起始体重 kg")
    p_set.add_argument("--target-weight", required=True, help="目标体重 kg")
    p_set.add_argument("--start-date", default=None, help="开始日期 YYYY-MM-DD")
    p_set.add_argument("--target-date", default=None, help="目标日期 YYYY-MM-DD")
    p_set.add_argument("--daily-calorie-target", default=None, help="每日热量目标 kcal")
    p_set.add_argument("--activity-level", default="sedentary",
                        help="活动水平: sedentary/light/moderate/active/very_active（用于自动推算热量目标）")
    p_set.add_argument("--note", default=None)

    # view
    p_view = sub.add_parser("view")
    p_view.add_argument("--member-id", required=True)

    # update
    p_upd = sub.add_parser("update")
    p_upd.add_argument("--goal-id", required=True)
    p_upd.add_argument("--target-weight", default=None)
    p_upd.add_argument("--target-date", default=None)
    p_upd.add_argument("--daily-calorie-target", default=None)
    p_upd.add_argument("--note", default=None)

    # complete
    p_comp = sub.add_parser("complete")
    p_comp.add_argument("--goal-id", required=True)

    # abandon
    p_abn = sub.add_parser("abandon")
    p_abn.add_argument("--goal-id", required=True)

    args = parser.parse_args()
    commands = {
        "set": set_goal,
        "view": view_goal,
        "update": update_goal,
        "complete": complete_goal,
        "abandon": abandon_goal,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
