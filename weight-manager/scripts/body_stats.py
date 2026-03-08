"""BMI/BMR/TDEE 计算与身体围度记录。"""

from __future__ import annotations

import argparse
import sys
import os
from datetime import datetime

# Unified path setup
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared'))
from path_setup import setup_mediwise_path
setup_mediwise_path()

from health_db import ensure_db, get_connection, generate_id, now_iso, row_to_dict, rows_to_list, output_json, transaction
from metric_utils import calculate_age, calculate_bmr, calculate_tdee

ACTIVITY_LEVELS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

ACTIVITY_LEVEL_NAMES = {
    "sedentary": "久坐不动",
    "light": "轻度活动",
    "moderate": "中度活动",
    "active": "高度活动",
    "very_active": "极高活动",
}

BMI_CATEGORIES = [
    (18.5, "偏瘦"),
    (24.0, "正常"),
    (28.0, "超重"),
    (float("inf"), "肥胖"),
]

MEASUREMENT_TYPES = ["waist", "hip", "chest", "arm", "thigh", "body_fat"]

MEASUREMENT_NAMES = {
    "waist": "腰围",
    "hip": "臀围",
    "chest": "胸围",
    "arm": "臂围",
    "thigh": "大腿围",
    "body_fat": "体脂率",
}

MEASUREMENT_UNITS = {
    "waist": "cm",
    "hip": "cm",
    "chest": "cm",
    "arm": "cm",
    "thigh": "cm",
    "body_fat": "%",
}


def _get_latest_metric(conn, member_id, metric_type):
    """Get latest metric value for a member."""
    row = conn.execute(
        """SELECT value, measured_at FROM health_metrics
           WHERE member_id=? AND metric_type=? AND is_deleted=0
           ORDER BY measured_at DESC LIMIT 1""",
        (member_id, metric_type)
    ).fetchone()
    if not row:
        return None
    try:
        return {"value": float(row["value"]), "measured_at": row["measured_at"]}
    except (ValueError, TypeError):
        return None


def _get_member_info(conn, member_id):
    """Get member with gender and birth_date."""
    return conn.execute(
        "SELECT * FROM members WHERE id=? AND is_deleted=0",
        (member_id,)
    ).fetchone()


def _classify_bmi(bmi):
    """Classify BMI using Chinese standard."""
    for threshold, label in BMI_CATEGORIES:
        if bmi < threshold:
            return label
    return "肥胖"


def bmi(args):
    """计算 BMI。"""
    ensure_db()
    conn = get_connection()
    try:
        m = _get_member_info(conn, args.member_id)
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        weight_data = _get_latest_metric(conn, args.member_id, "weight")
        height_data = _get_latest_metric(conn, args.member_id, "height")

        if not weight_data:
            output_json({"status": "error", "message": f"{m['name']}尚无体重记录，无法计算 BMI"})
            return
        if not height_data:
            output_json({"status": "error", "message": f"{m['name']}尚无身高记录，无法计算 BMI"})
            return

        weight_kg = weight_data["value"]
        height_cm = height_data["value"]
        height_m = height_cm / 100.0
        bmi_value = round(weight_kg / (height_m ** 2), 1)
        category = _classify_bmi(bmi_value)

        output_json({
            "status": "ok",
            "member_name": m["name"],
            "weight": weight_kg,
            "weight_measured_at": weight_data["measured_at"],
            "height": height_cm,
            "height_measured_at": height_data["measured_at"],
            "bmi": bmi_value,
            "category": category,
            "standard": "中国标准（<18.5 偏瘦, 18.5-24 正常, 24-28 超重, >=28 肥胖）",
        })
    finally:
        conn.close()


def bmr_tdee(args):
    """计算 BMR 和 TDEE（Mifflin-St Jeor 公式）。"""
    ensure_db()
    conn = get_connection()
    try:
        m = _get_member_info(conn, args.member_id)
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        weight_data = _get_latest_metric(conn, args.member_id, "weight")
        height_data = _get_latest_metric(conn, args.member_id, "height")

        if not weight_data:
            output_json({"status": "error", "message": f"{m['name']}尚无体重记录，无法计算 BMR"})
            return
        if not height_data:
            output_json({"status": "error", "message": f"{m['name']}尚无身高记录，无法计算 BMR"})
            return

        gender = m["gender"]
        if not gender or gender not in ("male", "female"):
            output_json({"status": "error", "message": f"{m['name']}未设置性别或性别无效，需要 male/female"})
            return

        birth_date = m["birth_date"]
        if not birth_date:
            output_json({"status": "error", "message": f"{m['name']}未设置出生日期，无法计算年龄"})
            return

        age = calculate_age(birth_date)
        weight_kg = weight_data["value"]
        height_cm = height_data["value"]

        # Mifflin-St Jeor formula
        bmr_value = round(calculate_bmr(weight_kg, height_cm, age, gender), 1)

        activity_level = args.activity_level or "sedentary"
        if activity_level not in ACTIVITY_LEVELS:
            output_json({
                "status": "error",
                "message": f"不支持的活动水平: {activity_level}，支持: {', '.join(ACTIVITY_LEVELS.keys())}"
            })
            return

        tdee_value = round(calculate_tdee(bmr_value, activity_level), 1)

        output_json({
            "status": "ok",
            "member_name": m["name"],
            "gender": gender,
            "age": age,
            "weight": weight_kg,
            "height": height_cm,
            "bmr": bmr_value,
            "activity_level": activity_level,
            "activity_level_name": ACTIVITY_LEVEL_NAMES.get(activity_level, activity_level),
            "activity_multiplier": ACTIVITY_LEVELS[activity_level],
            "tdee": tdee_value,
            "formula": "Mifflin-St Jeor",
        })
    finally:
        conn.close()


def suggest_calories(args):
    """根据 TDEE + 目标类型自动推算每日热量目标。"""
    ensure_db()
    conn = get_connection()
    try:
        m = _get_member_info(conn, args.member_id)
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        weight_data = _get_latest_metric(conn, args.member_id, "weight")
        height_data = _get_latest_metric(conn, args.member_id, "height")

        if not weight_data:
            output_json({"status": "error", "message": f"{m['name']}尚无体重记录"})
            return
        if not height_data:
            output_json({"status": "error", "message": f"{m['name']}尚无身高记录"})
            return

        gender = m["gender"]
        if not gender or gender not in ("male", "female"):
            output_json({"status": "error", "message": f"{m['name']}未设置性别或性别无效"})
            return

        birth_date = m["birth_date"]
        if not birth_date:
            output_json({"status": "error", "message": f"{m['name']}未设置出生日期"})
            return

        age = calculate_age(birth_date)
        weight_kg = weight_data["value"]
        height_cm = height_data["value"]

        bmr_value = calculate_bmr(weight_kg, height_cm, age, gender)

        activity_level = args.activity_level or "sedentary"
        if activity_level not in ACTIVITY_LEVELS:
            output_json({
                "status": "error",
                "message": f"不支持的活动水平: {activity_level}，支持: {', '.join(ACTIVITY_LEVELS.keys())}"
            })
            return

        tdee_value = round(calculate_tdee(bmr_value, activity_level), 1)

        # Check active goal
        goal = conn.execute(
            "SELECT * FROM weight_goals WHERE member_id=? AND status='active' AND is_deleted=0",
            (args.member_id,)
        ).fetchone()

        goal_type = args.goal_type
        if not goal_type and goal:
            goal_type = goal["goal_type"]
        if not goal_type:
            goal_type = "maintain"

        if goal_type == "lose":
            suggested = tdee_value - 500
        elif goal_type == "gain":
            suggested = tdee_value + 300
        else:
            suggested = tdee_value

        # Apply minimum clamp
        min_calories = 1500 if gender == "male" else 1200
        suggested = max(suggested, min_calories)
        suggested = round(suggested)

        output_json({
            "status": "ok",
            "member_name": m["name"],
            "bmr": round(bmr_value, 1),
            "tdee": tdee_value,
            "activity_level": activity_level,
            "goal_type": goal_type,
            "suggested_daily_calories": suggested,
            "min_calories": min_calories,
            "explanation": {
                "lose": f"TDEE({tdee_value}) - 500 = {tdee_value - 500}，约每周减 0.45kg",
                "gain": f"TDEE({tdee_value}) + 300 = {tdee_value + 300}",
                "maintain": f"TDEE({tdee_value})",
            }.get(goal_type, ""),
        })
    finally:
        conn.close()


def add_measurement(args):
    """记录身体围度。"""
    ensure_db()
    if args.type not in MEASUREMENT_TYPES:
        output_json({
            "status": "error",
            "message": f"不支持的围度类型: {args.type}，支持: {', '.join(MEASUREMENT_TYPES)}"
        })
        return

    with transaction() as conn:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        try:
            value = float(args.value)
        except (ValueError, TypeError):
            output_json({"status": "error", "message": "围度值必须为数值"})
            return

        metric_id = generate_id()
        measured_at = args.measured_at or now_iso()
        conn.execute(
            """INSERT INTO health_metrics (id, member_id, metric_type, value, measured_at, note, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'manual', ?)""",
            (metric_id, args.member_id, args.type, str(value), measured_at, args.note, now_iso())
        )
        conn.commit()

        name = MEASUREMENT_NAMES.get(args.type, args.type)
        unit = MEASUREMENT_UNITS.get(args.type, "")
        output_json({
            "status": "ok",
            "message": f"已记录{m['name']}的{name}: {value}{unit}",
            "metric_id": metric_id,
            "type": args.type,
            "value": value,
            "measured_at": measured_at,
        })


def list_measurements(args):
    """查看围度记录历史。"""
    ensure_db()
    conn = get_connection()
    try:
        m = conn.execute("SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        sql = """SELECT * FROM health_metrics
                 WHERE member_id=? AND metric_type IN ('waist','hip','chest','arm','thigh','body_fat')
                 AND is_deleted=0"""
        params = [args.member_id]

        if args.type:
            if args.type not in MEASUREMENT_TYPES:
                output_json({"status": "error", "message": f"不支持的围度类型: {args.type}"})
                return
            sql = """SELECT * FROM health_metrics
                     WHERE member_id=? AND metric_type=? AND is_deleted=0"""
            params = [args.member_id, args.type]

        sql += " ORDER BY measured_at DESC"
        if args.limit:
            sql += " LIMIT ?"
            params.append(int(args.limit))

        rows = conn.execute(sql, params).fetchall()
        metrics = rows_to_list(rows)

        output_json({
            "status": "ok",
            "member_name": m["name"],
            "count": len(metrics),
            "measurements": metrics,
        })
    finally:
        conn.close()


def body_summary(args):
    """综合身体报告（BMI + 围度变化 + 体脂率趋势）。"""
    ensure_db()
    conn = get_connection()
    try:
        m = _get_member_info(conn, args.member_id)
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        result = {
            "status": "ok",
            "member_name": m["name"],
        }

        # BMI
        weight_data = _get_latest_metric(conn, args.member_id, "weight")
        height_data = _get_latest_metric(conn, args.member_id, "height")

        if weight_data and height_data:
            height_m = height_data["value"] / 100.0
            bmi_value = round(weight_data["value"] / (height_m ** 2), 1)
            result["bmi"] = {
                "value": bmi_value,
                "category": _classify_bmi(bmi_value),
                "weight": weight_data["value"],
                "height": height_data["value"],
            }
        else:
            result["bmi"] = None

        # Latest measurements for each type
        measurements = {}
        for mt in MEASUREMENT_TYPES:
            latest = _get_latest_metric(conn, args.member_id, mt)
            if latest:
                measurements[mt] = {
                    "name": MEASUREMENT_NAMES[mt],
                    "value": latest["value"],
                    "unit": MEASUREMENT_UNITS[mt],
                    "measured_at": latest["measured_at"],
                }

                # Get oldest record for trend
                oldest = conn.execute(
                    """SELECT value, measured_at FROM health_metrics
                       WHERE member_id=? AND metric_type=? AND is_deleted=0
                       ORDER BY measured_at ASC LIMIT 1""",
                    (args.member_id, mt)
                ).fetchone()
                if oldest and oldest["measured_at"] != latest["measured_at"]:
                    try:
                        change = round(latest["value"] - float(oldest["value"]), 1)
                        measurements[mt]["change"] = change
                        measurements[mt]["first_value"] = float(oldest["value"])
                        measurements[mt]["first_measured_at"] = oldest["measured_at"]
                    except (ValueError, TypeError):
                        pass

        result["measurements"] = measurements

        # Body fat trend (last 10 records)
        bf_rows = conn.execute(
            """SELECT value, measured_at FROM health_metrics
               WHERE member_id=? AND metric_type='body_fat' AND is_deleted=0
               ORDER BY measured_at DESC LIMIT 10""",
            (args.member_id,)
        ).fetchall()
        body_fat_trend = []
        for r in bf_rows:
            try:
                body_fat_trend.append({"value": float(r["value"]), "measured_at": r["measured_at"]})
            except (ValueError, TypeError):
                pass
        body_fat_trend.reverse()
        result["body_fat_trend"] = body_fat_trend

        # Waist-hip ratio
        waist = measurements.get("waist")
        hip = measurements.get("hip")
        if waist and hip and hip["value"] > 0:
            whr = round(waist["value"] / hip["value"], 2)
            result["waist_hip_ratio"] = whr

        output_json(result)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="身体指标计算与围度记录")
    sub = parser.add_subparsers(dest="command", required=True)

    # bmi
    p_bmi = sub.add_parser("bmi")
    p_bmi.add_argument("--member-id", required=True)

    # bmr-tdee
    p_bmr = sub.add_parser("bmr-tdee")
    p_bmr.add_argument("--member-id", required=True)
    p_bmr.add_argument("--activity-level", default="sedentary",
                        help="活动水平: sedentary/light/moderate/active/very_active")

    # suggest-calories
    p_sc = sub.add_parser("suggest-calories")
    p_sc.add_argument("--member-id", required=True)
    p_sc.add_argument("--activity-level", default="sedentary")
    p_sc.add_argument("--goal-type", default=None, help="目标类型: lose/gain/maintain（默认从活跃目标读取）")

    # add-measurement
    p_am = sub.add_parser("add-measurement")
    p_am.add_argument("--member-id", required=True)
    p_am.add_argument("--type", required=True, help=f"围度类型: {', '.join(MEASUREMENT_TYPES)}")
    p_am.add_argument("--value", required=True, help="数值")
    p_am.add_argument("--measured-at", default=None, help="测量时间 YYYY-MM-DD HH:MM")
    p_am.add_argument("--note", default=None)

    # list-measurements
    p_lm = sub.add_parser("list-measurements")
    p_lm.add_argument("--member-id", required=True)
    p_lm.add_argument("--type", default=None, help="围度类型（可选筛选）")
    p_lm.add_argument("--limit", default=None, type=int, help="最多返回条数")

    # body-summary
    p_bs = sub.add_parser("body-summary")
    p_bs.add_argument("--member-id", required=True)

    args = parser.parse_args()
    commands = {
        "bmi": bmi,
        "bmr-tdee": bmr_tdee,
        "suggest-calories": suggest_calories,
        "add-measurement": add_measurement,
        "list-measurements": list_measurements,
        "body-summary": body_summary,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
