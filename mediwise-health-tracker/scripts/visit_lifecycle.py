"""Visit lifecycle management for MediWise Health Tracker.

Commands:
  plan     --member-id --visit-date --hospital [--department] [--chief-complaint]
           → Create a planned visit (visit_status='planned') with preparation tips

  prep     --member-id [--visit-id] [--days 30]
           → Pre-visit intelligence: symptoms grouped by body system,
             recent anomalous metrics, active medications, interaction warnings

  outcome  --visit-id --diagnosis [--summary] [--follow-up-date] [--follow-up-notes]
           [--medications '[]'] [--lab-orders '[]']
           → Record visit outcome, batch-create prescriptions, schedule follow-up reminder

  pending  --member-id [--owner-id]
           → List visits that are planned or need outcome recorded
"""

from __future__ import annotations

import argparse
import json
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import health_db
from health_db import (
    ensure_db, transaction, generate_id, now_iso,
    row_to_dict, rows_to_list, output_json, is_api_mode,
    verify_member_ownership,
)
from validators import validate_date
import reminder as reminder_mod


# Keyword-based body system classifier for symptom grouping
BODY_SYSTEM_KEYWORDS = {
    "心血管": ["心", "血压", "心率", "胸痛", "胸闷", "心悸", "心慌", "心绞痛", "水肿", "高血压", "低血压", "心跳", "血管"],
    "呼吸系统": ["咳嗽", "咳痰", "气短", "气喘", "喘息", "呼吸", "肺", "鼻塞", "流涕", "打喷嚏", "咽痛", "喉咙"],
    "消化系统": ["腹痛", "腹泻", "便秘", "恶心", "呕吐", "反酸", "胃痛", "腹胀", "消化", "食欲", "大便", "肠", "腹部"],
    "神经系统": ["头痛", "头晕", "头疼", "眩晕", "失眠", "睡眠", "抽搐", "麻木", "刺痛", "记忆", "焦虑", "抑郁", "情绪"],
    "肌肉骨骼": ["关节", "肌肉", "腰痛", "腰背", "背痛", "膝盖", "颈椎", "颈部", "骨骼", "肩膀", "肩痛", "脚踝", "扭伤"],
    "泌尿生殖": ["尿频", "尿急", "尿痛", "血尿", "排尿", "肾", "膀胱", "尿道"],
    "皮肤": ["皮疹", "荨麻疹", "瘙痒", "红肿", "皮肤", "过敏", "湿疹", "痤疮"],
    "眼耳口鼻": ["眼睛", "视力", "耳鸣", "耳痛", "牙痛", "口腔", "口干", "耳朵"],
    "内分泌代谢": ["血糖", "糖尿病", "甲状腺", "体重", "激素", "代谢", "内分泌"],
}


def _classify_symptom(text: str) -> str:
    """Classify a symptom string into a body system category."""
    for system, keywords in BODY_SYSTEM_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return system
    return "其他"


def cmd_plan(args):
    """Create a planned visit appointment with preparation tips."""
    ensure_db()
    with transaction(domain="medical") as conn:
        m = conn.execute(
            "SELECT id, name FROM members WHERE id=? AND is_deleted=0",
            (args.member_id,)
        ).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return
        if not verify_member_ownership(conn, args.member_id, getattr(args, "owner_id", None)):
            output_json({"status": "error", "message": "无权操作该成员"})
            return

        try:
            visit_date = validate_date(args.visit_date, "就诊日期")
        except ValueError as e:
            output_json({"status": "error", "message": str(e)})
            return

        visit_id = generate_id()
        ts = now_iso()
        conn.execute(
            """INSERT INTO visits
               (id, member_id, visit_type, visit_date, hospital, department,
                chief_complaint, visit_status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'planned', ?, ?)""",
            (
                visit_id, args.member_id,
                getattr(args, "visit_type", None) or "门诊",
                visit_date,
                getattr(args, "hospital", None),
                getattr(args, "department", None),
                getattr(args, "chief_complaint", None),
                ts, ts,
            ),
        )
        conn.commit()
        visit = row_to_dict(conn.execute("SELECT * FROM visits WHERE id=?", (visit_id,)).fetchone())

    # Build contextual preparation tips
    prep_tips = [
        "整理近期症状：记录开始时间、持续时长、加重/缓解因素",
        "准备好过往病历、检查报告和化验单",
        "列出当前所有在用药物（名称、剂量、频次）",
        "提前写下要问医生的问题，避免就诊时遗忘",
    ]
    location = " ".join(filter(None, [getattr(args, "hospital", None), getattr(args, "department", None)]))
    if location:
        prep_tips.insert(0, f"预约确认：{location}，{visit_date}")

    output_json({
        "status": "ok",
        "message": f"已为{m['name']}创建就诊预约（{visit_date}）",
        "visit": visit,
        "prep_tips": prep_tips,
    })


def cmd_prep(args):
    """Generate a pre-visit intelligence summary for the doctor visit."""
    ensure_db()
    conn = health_db.get_medical_connection()
    try:
        m = conn.execute(
            "SELECT id, name FROM members WHERE id=? AND is_deleted=0",
            (args.member_id,)
        ).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return
        if not verify_member_ownership(conn, args.member_id, getattr(args, "owner_id", None)):
            output_json({"status": "error", "message": "无权操作该成员"})
            return

        days = getattr(args, "days", 30) or 30
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        # --- Symptoms: group by body system ---
        symptoms = rows_to_list(conn.execute(
            """SELECT symptom, severity, onset_date, description
               FROM symptoms
               WHERE member_id=? AND is_deleted=0
                 AND (onset_date >= ? OR onset_date IS NULL)
               ORDER BY onset_date DESC""",
            (args.member_id, cutoff),
        ).fetchall())

        symptom_groups: dict[str, list[str]] = {}
        for s in symptoms:
            combined = (s.get("symptom") or "") + " " + (s.get("description") or "")
            system = _classify_symptom(combined)
            if system not in symptom_groups:
                symptom_groups[system] = []
            entry = s["symptom"]
            if s.get("severity"):
                entry += f"（{s['severity']}）"
            if s.get("onset_date"):
                entry += f" 始于{s['onset_date']}"
            symptom_groups[system].append(entry)

        # --- Anomalous metrics (from health_advisor) ---
        anomalies = []
        try:
            import health_advisor as _advisor
            tips_result = _advisor.generate_health_tips(args.member_id)
            anomalies = [t for t in tips_result.get("tips", []) if t.get("severity") in ("alert", "warning")]
        except Exception:
            pass

        # --- Active medications ---
        meds = rows_to_list(conn.execute(
            """SELECT name, dosage, frequency, purpose, start_date
               FROM medications
               WHERE member_id=? AND is_active=1 AND is_deleted=0
               ORDER BY start_date DESC""",
            (args.member_id,),
        ).fetchall())

        # --- Drug interaction warnings (major/moderate pairs) ---
        interaction_warnings = []
        if len(meds) >= 2:
            try:
                import drug_interaction as _di
                interaction_warnings = _di.check_pairwise_interactions(meds)
            except Exception:
                pass

        # --- Visit context if visit_id provided ---
        visit_info = None
        if getattr(args, "visit_id", None):
            v = conn.execute(
                "SELECT * FROM visits WHERE id=? AND is_deleted=0", (args.visit_id,)
            ).fetchone()
            if v:
                visit_info = row_to_dict(v)

    finally:
        conn.close()

    summary_parts = [f"过去{days}天内记录了{len(symptoms)}条症状"]
    if symptom_groups:
        summary_parts.append(f"涉及{len(symptom_groups)}个身体系统")
    summary_parts.append(f"当前服用{len(meds)}种药物")
    if interaction_warnings:
        summary_parts.append(f"发现{len(interaction_warnings)}个需关注的药物相互作用")

    output_json({
        "status": "ok",
        "member_name": m["name"],
        "period_days": days,
        "visit": visit_info,
        "symptoms_by_system": symptom_groups,
        "symptom_count": len(symptoms),
        "anomalous_metrics": anomalies,
        "active_medications": meds,
        "interaction_warnings": interaction_warnings,
        "summary": "，".join(summary_parts),
    })


def cmd_outcome(args):
    """Record visit outcome: diagnosis, medications, and optional follow-up scheduling."""
    ensure_db()
    with transaction(domain="medical") as conn:
        visit = row_to_dict(conn.execute(
            "SELECT * FROM visits WHERE id=? AND is_deleted=0", (args.visit_id,)
        ).fetchone())
        if not visit:
            output_json({"status": "error", "message": f"未找到就诊记录: {args.visit_id}"})
            return

        member_id = visit["member_id"]
        owner_id = getattr(args, "owner_id", None)
        if not verify_member_ownership(conn, member_id, owner_id):
            output_json({"status": "error", "message": "无权操作该成员"})
            return

        m = conn.execute(
            "SELECT name FROM members WHERE id=? AND is_deleted=0", (member_id,)
        ).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {member_id}"})
            return

        if visit.get("visit_status") == "completed":
            output_json({
                "status": "error",
                "message": (
                    f"该就诊记录已完成（诊断：{visit.get('diagnosis') or '未记录'}）。"
                    "如需修改诊断或复诊信息，请使用 update-visit 命令；"
                    "如需追加处方，请使用 add-medication 命令。"
                ),
                "visit": visit,
            })
            return
        follow_up_date = None
        if getattr(args, "follow_up_date", None):
            try:
                follow_up_date = validate_date(args.follow_up_date, "复诊日期")
            except ValueError as e:
                output_json({"status": "error", "message": str(e)})
                return

        ts = now_iso()

        # Update visit record
        conn.execute(
            """UPDATE visits SET
               diagnosis=?, summary=?, visit_status='completed',
               follow_up_date=?, follow_up_notes=?, updated_at=?
               WHERE id=?""",
            (
                args.diagnosis,
                getattr(args, "summary", None),
                follow_up_date,
                getattr(args, "follow_up_notes", None),
                ts,
                args.visit_id,
            ),
        )

        # Batch-create prescribed medications
        created_meds = []
        medications_json = getattr(args, "medications", None)
        if medications_json:
            try:
                medications = json.loads(medications_json)
                if isinstance(medications, list):
                    for med in medications:
                        if not isinstance(med, dict) or not med.get("name"):
                            continue
                        med_id = generate_id()
                        conn.execute(
                            """INSERT INTO medications
                               (id, member_id, visit_id, name, dosage, frequency,
                                start_date, end_date, purpose, is_active, created_at, updated_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
                            (
                                med_id, member_id, args.visit_id,
                                med["name"],
                                med.get("dosage"),
                                med.get("frequency"),
                                med.get("start_date", ts[:10]),
                                med.get("end_date"),
                                med.get("purpose") or args.diagnosis,
                                ts, ts,
                            ),
                        )
                        created_meds.append({"id": med_id, **med})
            except (json.JSONDecodeError, TypeError) as e:
                output_json({"status": "error", "message": f"药物列表格式错误: {e}"})
                return

        # Batch-create lab orders (pending lab tests ordered at this visit)
        created_labs = []
        lab_orders_json = getattr(args, "lab_orders", None)
        if lab_orders_json:
            try:
                lab_orders = json.loads(lab_orders_json)
                if isinstance(lab_orders, list):
                    for order in lab_orders:
                        if not isinstance(order, dict) or not order.get("test_name"):
                            continue
                        lab_id = generate_id()
                        conn.execute(
                            """INSERT INTO lab_results
                               (id, member_id, visit_id, test_name, test_date, items, created_at, is_deleted)
                               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                            (
                                lab_id, member_id, args.visit_id,
                                order["test_name"],
                                order.get("test_date", ts[:10]),
                                json.dumps(order.get("items", []), ensure_ascii=False),
                                ts,
                            ),
                        )
                        created_labs.append({"id": lab_id, **order})
            except (json.JSONDecodeError, TypeError) as e:
                output_json({"status": "error", "message": f"化验单列表格式错误: {e}"})
                return

        conn.commit()
        updated_visit = row_to_dict(conn.execute(
            "SELECT * FROM visits WHERE id=?", (args.visit_id,)
        ).fetchone())

    # Create follow-up reminder outside transaction
    follow_up_reminder = None
    if follow_up_date:
        try:
            hospital = visit.get("hospital") or "医院"
            follow_up_reminder = reminder_mod.create_reminder(
                member_id=member_id,
                reminder_type="checkup",
                title=f"复诊提醒：{hospital} - {args.diagnosis}",
                schedule_type="once",
                schedule_value=follow_up_date,
                content=f"本次诊断：{args.diagnosis}。请于{follow_up_date}复诊。",
                related_record_id=args.visit_id,
                related_record_type="visit",
                priority="high",
                owner_id=owner_id,
            )
        except Exception as e:
            follow_up_reminder = {"error": str(e)}

    output_json({
        "status": "ok",
        "message": f"已为{m['name']}记录就诊结果：{args.diagnosis}",
        "visit": updated_visit,
        "prescribed_medications": created_meds,
        "lab_orders": created_labs,
        "follow_up_reminder": follow_up_reminder,
    })


def cmd_pending(args):
    """List visits that are planned or need outcome data filled in."""
    ensure_db()
    conn = health_db.get_medical_connection()
    try:
        if not verify_member_ownership(conn, args.member_id, getattr(args, "owner_id", None)):
            output_json({"status": "error", "message": "无权操作该成员"})
            return

        # Visits with status='planned' (upcoming, not yet happened)
        planned = rows_to_list(conn.execute(
            """SELECT * FROM visits
               WHERE member_id=? AND is_deleted=0 AND visit_status='planned'
               ORDER BY visit_date ASC""",
            (args.member_id,),
        ).fetchall())

        # Completed/old visits missing diagnosis (need outcome recorded)
        needs_outcome = rows_to_list(conn.execute(
            """SELECT * FROM visits
               WHERE member_id=? AND is_deleted=0
                 AND (visit_status IS NULL OR visit_status='completed')
                 AND (diagnosis IS NULL OR diagnosis='')
                 AND visit_date >= date('now', '-60 days')
               ORDER BY visit_date DESC""",
            (args.member_id,),
        ).fetchall())

        # Visits with upcoming follow-up dates
        follow_up_pending = rows_to_list(conn.execute(
            """SELECT * FROM visits
               WHERE member_id=? AND is_deleted=0
                 AND follow_up_date IS NOT NULL
                 AND follow_up_date >= date('now')
                 AND visit_status='completed'
               ORDER BY follow_up_date ASC""",
            (args.member_id,),
        ).fetchall())

    finally:
        conn.close()

    total = len(planned) + len(needs_outcome) + len(follow_up_pending)
    output_json({
        "status": "ok",
        "total": total,
        "planned_visits": planned,
        "needs_outcome": needs_outcome,
        "upcoming_follow_ups": follow_up_pending,
        "message": (
            f"共{total}条待处理：{len(planned)}个待就诊，"
            f"{len(needs_outcome)}个待填写结果，"
            f"{len(follow_up_pending)}个复诊提醒"
        ) if total > 0 else "暂无待处理就诊记录",
    })


def main():
    parser = argparse.ArgumentParser(description="就诊生命周期管理")
    sub = parser.add_subparsers(dest="command", required=True)

    # plan
    p = sub.add_parser("plan", help="创建就诊预约")
    p.add_argument("--member-id", required=True)
    p.add_argument("--visit-date", required=True)
    p.add_argument("--hospital", default=None)
    p.add_argument("--department", default=None)
    p.add_argument("--chief-complaint", default=None)
    p.add_argument("--visit-type", default="门诊")
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    # prep
    p = sub.add_parser("prep", help="就诊前智能汇总")
    p.add_argument("--member-id", required=True)
    p.add_argument("--visit-id", default=None)
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    # outcome
    p = sub.add_parser("outcome", help="记录就诊结果")
    p.add_argument("--visit-id", required=True)
    p.add_argument("--diagnosis", required=True)
    p.add_argument("--summary", default=None)
    p.add_argument("--follow-up-date", default=None)
    p.add_argument("--follow-up-notes", default=None)
    p.add_argument(
        "--medications", default=None,
        help='处方药 JSON 数组，如 \'[{"name":"阿司匹林","dosage":"100mg","frequency":"每日一次"}]\'',
    )
    p.add_argument("--lab-orders", default=None)
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    # pending
    p = sub.add_parser("pending", help="待处理就诊列表")
    p.add_argument("--member-id", required=True)
    p.add_argument("--owner-id", default=os.environ.get("MEDIWISE_OWNER_ID"))

    args = parser.parse_args()
    commands = {
        "plan": cmd_plan,
        "prep": cmd_prep,
        "outcome": cmd_outcome,
        "pending": cmd_pending,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
