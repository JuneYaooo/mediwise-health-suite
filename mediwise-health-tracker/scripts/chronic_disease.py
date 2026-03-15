"""Chronic disease management for MediWise Health Tracker.

Supports diabetes and hypertension profiling and analysis.
"""

from __future__ import annotations

import sys
import os
import json
import argparse
import statistics
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

import health_db

DEFAULT_TARGETS = {
    "diabetes": {
        "fasting_glucose_target": 7.0,
        "postprandial_glucose_target": 10.0,
        "hba1c_target": 7.0,
    },
    "hypertension": {
        "systolic_target": 130,
        "diastolic_target": 80,
    },
}

VALID_DISEASE_TYPES = {"diabetes", "hypertension"}


def _get_profile(conn, member_id, disease_type):
    """Fetch the active chronic disease profile, or None."""
    row = conn.execute(
        """SELECT * FROM chronic_disease_profiles
           WHERE member_id=? AND disease_type=? AND is_active=1 AND is_deleted=0
           ORDER BY created_at DESC LIMIT 1""",
        (member_id, disease_type),
    ).fetchone()
    return dict(row) if row else None


def _get_targets(profile, disease_type):
    """Return targets dict from profile (or defaults), plus a flag."""
    if profile:
        try:
            targets = json.loads(profile["targets"])
            return targets, False
        except (json.JSONDecodeError, TypeError):
            pass
    return DEFAULT_TARGETS.get(disease_type, {}), True


def setup_profile(args):
    health_db.ensure_db()

    disease_type = args.disease_type
    if disease_type not in VALID_DISEASE_TYPES:
        health_db.output_json({
            "status": "error",
            "message": f"不支持的病种: {disease_type}，支持: {', '.join(sorted(VALID_DISEASE_TYPES))}",
        })
        return

    # Parse targets JSON
    if args.targets:
        try:
            targets = json.loads(args.targets)
        except json.JSONDecodeError as e:
            health_db.output_json({"status": "error", "message": f"targets JSON 解析错误: {e}"})
            return
    else:
        targets = DEFAULT_TARGETS[disease_type]

    with health_db.transaction(domain="medical") as conn:
        # Verify member
        m = conn.execute(
            "SELECT name FROM members WHERE id=? AND is_deleted=0", (args.member_id,)
        ).fetchone()
        if not m:
            health_db.output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        # Deactivate existing active profiles of this type
        conn.execute(
            """UPDATE chronic_disease_profiles SET is_active=0, updated_at=?
               WHERE member_id=? AND disease_type=? AND is_active=1 AND is_deleted=0""",
            (health_db.now_iso(), args.member_id, disease_type),
        )

        profile_id = health_db.generate_id()
        now = health_db.now_iso()
        conn.execute(
            """INSERT INTO chronic_disease_profiles
               (id, member_id, disease_type, targets, diagnosed_date, notes, is_active, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (
                profile_id,
                args.member_id,
                disease_type,
                json.dumps(targets, ensure_ascii=False),
                getattr(args, "diagnosed_date", None),
                getattr(args, "notes", None),
                now,
                now,
            ),
        )
        conn.commit()

    health_db.output_json({
        "status": "ok",
        "message": f"慢病档案已创建: {disease_type}",
        "profile_id": profile_id,
        "disease_type": disease_type,
        "targets": targets,
    })


def view_profile(args):
    health_db.ensure_db()

    disease_type = args.disease_type
    if disease_type not in VALID_DISEASE_TYPES:
        health_db.output_json({
            "status": "error",
            "message": f"不支持的病种: {disease_type}",
        })
        return

    with health_db.get_medical_connection() as conn:
        profile = _get_profile(conn, args.member_id, disease_type)

    if not profile:
        health_db.output_json({
            "status": "ok",
            "profile": None,
            "message": f"未找到 {disease_type} 档案，将使用默认目标值",
            "default_targets": DEFAULT_TARGETS.get(disease_type, {}),
        })
        return

    try:
        profile["targets"] = json.loads(profile["targets"])
    except (json.JSONDecodeError, TypeError):
        pass

    health_db.output_json({"status": "ok", "profile": profile})


def analyze_diabetes(args):
    health_db.ensure_db()

    days = int(args.days) if args.days else 30
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    conn = health_db.get_medical_connection()
    try:
        profile = _get_profile(conn, args.member_id, "diabetes")
        targets, using_defaults = _get_targets(profile, "diabetes")

        fasting_target = float(targets.get("fasting_glucose_target", 7.0))
        post_target = float(targets.get("postprandial_glucose_target", 10.0))
        hba1c_target = float(targets.get("hba1c_target", 7.0))

        rows = conn.execute(
            """SELECT value, context, measured_at FROM health_metrics
               WHERE member_id=? AND metric_type='blood_sugar'
               AND measured_at >= ? AND is_deleted=0
               ORDER BY measured_at""",
            (args.member_id, since),
        ).fetchall()

        fasting_vals = []
        post_vals = []
        other_vals = []
        dated_fasting = {}
        dated_post = {}

        for row in rows:
            try:
                val = float(row["value"])
            except (ValueError, TypeError):
                continue
            ctx = row["context"] or "routine"
            day = (row["measured_at"] or "")[:10]
            if ctx == "fasting":
                fasting_vals.append(val)
                dated_fasting[day] = val
            elif ctx == "postprandial_2h":
                post_vals.append(val)
                dated_post[day] = val
            else:
                other_vals.append(val)

        def _stats(vals, target):
            if len(vals) < 3:
                return {"count": len(vals), "status": "insufficient_data"}
            mid = len(vals) // 2
            return {
                "count": len(vals),
                "mean": round(sum(vals) / len(vals), 2),
                "target": target,
                "compliance_rate": round(sum(1 for v in vals if v <= target) / len(vals) * 100, 1),
                "trend": {
                    "first_half_mean": round(sum(vals[:mid]) / mid, 2),
                    "second_half_mean": round(sum(vals[mid:]) / len(vals[mid:]), 2),
                },
            }

        # Paired readings (same day)
        paired_days = sorted(set(dated_fasting) & set(dated_post))
        pairs = [{"date": d, "fasting": dated_fasting[d], "postprandial_2h": dated_post[d]}
                 for d in paired_days]

        # HbA1c from lab_results
        hba1c_result = None
        lab_rows = conn.execute(
            """SELECT items, test_date FROM lab_results
               WHERE member_id=? AND is_deleted=0
               ORDER BY test_date DESC LIMIT 20""",
            (args.member_id,),
        ).fetchall()
        for lab in lab_rows:
            try:
                items = json.loads(lab["items"] or "[]")
                for item in items:
                    name = str(item.get("name", ""))
                    if "HbA1c" in name or "糖化" in name:
                        hba1c_result = {
                            "value": item.get("value"),
                            "unit": item.get("unit", "%"),
                            "date": lab["test_date"],
                            "target": hba1c_target,
                            "flag": "normal" if item.get("value") and float(str(item["value"]).replace(",", "")) <= hba1c_target else "attention",
                        }
                        break
                if hba1c_result:
                    break
            except (json.JSONDecodeError, TypeError, ValueError):
                continue

    finally:
        conn.close()

    health_db.output_json({
        "status": "ok",
        "disease_type": "diabetes",
        "member_id": args.member_id,
        "period_days": days,
        "using_default_targets": using_defaults,
        "fasting_glucose": _stats(fasting_vals, fasting_target),
        "postprandial_glucose": _stats(post_vals, post_target),
        "other_glucose": {"count": len(other_vals)},
        "paired_readings": pairs,
        "hba1c": hba1c_result,
    })


def analyze_hypertension(args):
    health_db.ensure_db()

    days = int(args.days) if args.days else 30
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    conn = health_db.get_medical_connection()
    try:
        profile = _get_profile(conn, args.member_id, "hypertension")
        targets, using_defaults = _get_targets(profile, "hypertension")

        sys_target = float(targets.get("systolic_target", 130))
        dia_target = float(targets.get("diastolic_target", 80))

        rows = conn.execute(
            """SELECT value, measured_at FROM health_metrics
               WHERE member_id=? AND metric_type='blood_pressure'
               AND measured_at >= ? AND is_deleted=0
               ORDER BY measured_at""",
            (args.member_id, since),
        ).fetchall()

        morning_sys = []
        morning_dia = []
        daytime_sys = []
        daytime_dia = []
        all_sys = []
        all_dia = []

        for row in rows:
            try:
                bp = json.loads(row["value"])
                sys_val = float(bp["systolic"])
                dia_val = float(bp["diastolic"])
            except (json.JSONDecodeError, TypeError, KeyError, ValueError):
                continue

            all_sys.append(sys_val)
            all_dia.append(dia_val)

            ts = row["measured_at"] or ""
            try:
                hour = int(ts[11:13]) if len(ts) >= 13 else 12
            except (ValueError, TypeError):
                hour = 12

            if 6 <= hour < 10:
                morning_sys.append(sys_val)
                morning_dia.append(dia_val)
            elif 10 <= hour < 20:
                daytime_sys.append(sys_val)
                daytime_dia.append(dia_val)

    finally:
        conn.close()

    def _safe_mean(vals):
        return round(sum(vals) / len(vals), 1) if vals else None

    def _safe_cv(vals):
        if len(vals) < 2:
            return None
        try:
            return round(statistics.stdev(vals) / statistics.mean(vals) * 100, 1)
        except statistics.StatisticsError:
            return None

    morning_sys_mean = _safe_mean(morning_sys)
    daytime_sys_mean = _safe_mean(daytime_sys)
    if morning_sys_mean and daytime_sys_mean and daytime_sys_mean > 0:
        morning_surge = round(morning_sys_mean / daytime_sys_mean, 3)
    else:
        morning_surge = None

    total = len(all_sys)
    if total > 0:
        compliance_rate = round(
            sum(1 for s, d in zip(all_sys, all_dia) if s <= sys_target and d <= dia_target) / total * 100,
            1,
        )
    else:
        compliance_rate = None

    health_db.output_json({
        "status": "ok",
        "disease_type": "hypertension",
        "member_id": args.member_id,
        "period_days": days,
        "using_default_targets": using_defaults,
        "targets": {"systolic": sys_target, "diastolic": dia_target},
        "total_readings": total,
        "compliance_rate": compliance_rate,
        "overall": {
            "systolic_mean": _safe_mean(all_sys),
            "diastolic_mean": _safe_mean(all_dia),
            "systolic_cv": _safe_cv(all_sys),
            "diastolic_cv": _safe_cv(all_dia),
        },
        "morning_segment": {
            "count": len(morning_sys),
            "systolic_mean": morning_sys_mean,
            "diastolic_mean": _safe_mean(morning_dia),
        },
        "daytime_segment": {
            "count": len(daytime_sys),
            "systolic_mean": daytime_sys_mean,
            "diastolic_mean": _safe_mean(daytime_dia),
        },
        "morning_surge_ratio": morning_surge,
    })


def disease_summary(args):
    health_db.ensure_db()

    disease_types = []
    if getattr(args, "disease_type", None):
        disease_types = [args.disease_type]
    else:
        disease_types = list(VALID_DISEASE_TYPES)

    conn = health_db.get_medical_connection()
    try:
        results = {}
        for dt in disease_types:
            profile = _get_profile(conn, args.member_id, dt)
            if profile:
                try:
                    profile["targets"] = json.loads(profile["targets"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results[dt] = {
                "has_profile": profile is not None,
                "profile": profile,
                "default_targets": DEFAULT_TARGETS.get(dt, {}),
            }
    finally:
        conn.close()

    health_db.output_json({
        "status": "ok",
        "member_id": args.member_id,
        "diseases": results,
    })


def main():
    parser = argparse.ArgumentParser(description="慢病管理（糖尿病/高血压）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup-profile", help="创建/更新慢病档案")
    p_setup.add_argument("--member-id", required=True)
    p_setup.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
    p_setup.add_argument("--disease-type", required=True, choices=sorted(VALID_DISEASE_TYPES))
    p_setup.add_argument("--targets", default=None, help="JSON 格式的目标值")
    p_setup.add_argument("--diagnosed-date", default=None, help="确诊日期 YYYY-MM-DD")
    p_setup.add_argument("--notes", default=None)

    p_view = sub.add_parser("view-profile", help="查看慢病档案")
    p_view.add_argument("--member-id", required=True)
    p_view.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
    p_view.add_argument("--disease-type", required=True, choices=sorted(VALID_DISEASE_TYPES))

    p_dm = sub.add_parser("analyze-diabetes", help="分析糖尿病数据")
    p_dm.add_argument("--member-id", required=True)
    p_dm.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
    p_dm.add_argument("--days", default=30, type=int, help="分析天数（默认30）")

    p_ht = sub.add_parser("analyze-hypertension", help="分析高血压数据")
    p_ht.add_argument("--member-id", required=True)
    p_ht.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
    p_ht.add_argument("--days", default=30, type=int, help="分析天数（默认30）")

    p_sum = sub.add_parser("disease-summary", help="慢病概览")
    p_sum.add_argument("--member-id", required=True)
    p_sum.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))
    p_sum.add_argument("--disease-type", default=None, choices=sorted(VALID_DISEASE_TYPES))

    args = parser.parse_args()
    commands = {
        "setup-profile": setup_profile,
        "view-profile": view_profile,
        "analyze-diabetes": analyze_diabetes,
        "analyze-hypertension": analyze_hypertension,
        "disease-summary": disease_summary,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
