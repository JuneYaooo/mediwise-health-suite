#!/usr/bin/env python3
"""Generate an edge-case synthetic dataset for MediWise Health Tracker.

Builds on the standard synthetic dataset and adds members/records focused on
boundary conditions, empty states, emergency alerts, due reminders, standalone
records, and tenant isolation checks.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

import generate_sample as base

ROOT_DIR = THIS_DIR.parent.parent
DEFAULT_OUTPUT_DIR = THIS_DIR / "generated_edge_dataset"

EDGE_EMPTY_MEMBER = "mem_empty_sun_qi"
EDGE_CRISIS_MEMBER = "mem_edge_guo_tao"


def parse_args():
    import argparse

    parser = argparse.ArgumentParser(description="生成 MediWise 边界场景测试数据")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="输出目录，默认写到 mediwise-health-tracker/test_data/generated_edge_dataset",
    )
    return parser.parse_args()


def write_edge_inputs(output_dir: Path, today: date) -> dict:
    intake_dir = output_dir / "fixtures" / "intake_inputs"
    attachment_dir = output_dir / "fixtures" / "attachment_sources"

    base.write_text(
        intake_dir / "quick_entry_edge_valid.txt",
        "BP 186/118 HR 154 SpO2 83 体温39.8 空腹血糖12.6 体重92kg",
    )
    base.write_text(
        intake_dir / "quick_entry_edge_invalid.txt",
        "血压有点高，心率很快，今天不舒服",
    )
    base.write_text(
        intake_dir / "smart_intake_edge_multitype.txt",
        (
            f"{base.day_str(today - timedelta(days=1))} 夜间突发胸闷和气促，到市急救中心急诊就诊，"
            "诊断为重症肺部感染待排并低氧血症。"
            "体温39.8℃，血氧83%，心率154次/分。"
            "给予吸氧、头孢曲松静滴、布地奈德雾化。"
        ),
    )
    base.write_text(
        intake_dir / "expected_edge_records.json",
        json.dumps(
            {
                "quick_entry_edge_valid.txt": [
                    "health_metric:blood_pressure",
                    "health_metric:heart_rate",
                    "health_metric:blood_oxygen",
                    "health_metric:temperature",
                    "health_metric:blood_sugar",
                    "health_metric:weight",
                ],
                "quick_entry_edge_invalid.txt": ["fallback"],
                "smart_intake_edge_multitype.txt": ["visit", "medication", "health_metric"],
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    base.write_text(
        attachment_dir / "edge_chest_ct.txt",
        "胸部 CT 报告摘要\n双肺多发斑片状高密度影，考虑感染性病变。\n",
    )
    return {
        "edge_intake_dir": str(intake_dir),
        "edge_attachment_source": str(attachment_dir / "edge_chest_ct.txt"),
    }


def build_edge_members(today: date) -> list[dict]:
    created = base.dt_at(today - timedelta(days=10), 10, 0)
    updated = base.dt_at(today, 10, 0)
    return [
        {
            "id": EDGE_EMPTY_MEMBER,
            "name": "孙琪",
            "relation": "其他",
            "gender": "女",
            "birth_date": "2001-01-16",
            "blood_type": None,
            "allergies": None,
            "medical_history": None,
            "phone": None,
            "emergency_contact": None,
            "emergency_phone": None,
            "owner_id": base.IDS.owner_primary,
            "custom_metric_ranges": None,
            "timezone": "Asia/Shanghai",
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": EDGE_CRISIS_MEMBER,
            "name": "郭涛",
            "relation": "其他",
            "gender": "男",
            "birth_date": "1976-07-21",
            "blood_type": "A+",
            "allergies": "无",
            "medical_history": "哮喘,睡眠呼吸暂停综合征",
            "phone": "13800000021",
            "emergency_contact": "郭宁",
            "emergency_phone": "13800000022",
            "owner_id": base.IDS.owner_primary,
            "custom_metric_ranges": json.dumps({"blood_oxygen": {"low": 94}}, ensure_ascii=False),
            "timezone": "Asia/Shanghai",
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
    ]


def build_edge_visits(today: date) -> list[dict]:
    created = base.dt_at(today - timedelta(days=2), 3, 0)
    updated = base.dt_at(today, 3, 0)
    return [
        {
            "id": "visit_edge_emergency",
            "member_id": EDGE_CRISIS_MEMBER,
            "visit_type": "急诊",
            "visit_date": base.day_str(today - timedelta(days=1)),
            "end_date": None,
            "hospital": "市急救中心",
            "department": "急诊医学科",
            "chief_complaint": "突发胸闷、气促、发热",
            "diagnosis": "低氧血症；重症肺部感染待排",
            "summary": "给予吸氧、抗感染和雾化治疗，建议严密观察呼吸状态。",
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "visit_edge_old",
            "member_id": EDGE_CRISIS_MEMBER,
            "visit_type": "门诊",
            "visit_date": base.day_str(today - timedelta(days=420)),
            "end_date": None,
            "hospital": "呼吸专科门诊",
            "department": "呼吸内科",
            "chief_complaint": "夜间打鼾、白天嗜睡",
            "diagnosis": "睡眠呼吸暂停待进一步检查",
            "summary": "建议完善睡眠监测。",
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
    ]


def build_edge_symptoms(today: date) -> list[dict]:
    created = base.dt_at(today - timedelta(days=1), 5, 0)
    return [
        {
            "id": "sym_edge_dyspnea",
            "member_id": EDGE_CRISIS_MEMBER,
            "visit_id": "visit_edge_emergency",
            "symptom": "呼吸困难",
            "severity": "重度",
            "onset_date": base.day_str(today - timedelta(days=1)),
            "end_date": None,
            "description": "说整句话费力，活动后明显加重。",
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "sym_edge_fever",
            "member_id": EDGE_CRISIS_MEMBER,
            "visit_id": "visit_edge_emergency",
            "symptom": "高热",
            "severity": "重度",
            "onset_date": base.day_str(today - timedelta(days=2)),
            "end_date": None,
            "description": "最高体温 39.8℃。",
            "created_at": created,
            "is_deleted": 0,
        },
    ]


def build_edge_medications(today: date) -> list[dict]:
    created = base.dt_at(today - timedelta(days=5), 8, 0)
    updated = base.dt_at(today, 8, 0)
    return [
        {
            "id": "med_edge_budesonide",
            "member_id": EDGE_CRISIS_MEMBER,
            "visit_id": "visit_edge_emergency",
            "name": "布地奈德雾化液",
            "dosage": "2mg",
            "frequency": "每日两次 雾化",
            "start_date": base.day_str(today - timedelta(days=1)),
            "end_date": None,
            "purpose": "缓解气道炎症",
            "stop_reason": None,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "med_edge_ceftriaxone",
            "member_id": EDGE_CRISIS_MEMBER,
            "visit_id": "visit_edge_emergency",
            "name": "头孢曲松",
            "dosage": "2g",
            "frequency": "每日一次 静滴",
            "start_date": base.day_str(today - timedelta(days=1)),
            "end_date": None,
            "purpose": "抗感染",
            "stop_reason": None,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "med_edge_prednisone_old",
            "member_id": EDGE_CRISIS_MEMBER,
            "visit_id": None,
            "name": "泼尼松",
            "dosage": "20mg",
            "frequency": "每日一次",
            "start_date": base.day_str(today - timedelta(days=30)),
            "end_date": base.day_str(today - timedelta(days=25)),
            "purpose": "既往哮喘急性加重短疗程",
            "stop_reason": "疗程结束",
            "is_active": 0,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
    ]


def build_edge_labs(today: date) -> list[dict]:
    created = base.dt_at(today - timedelta(days=1), 6, 30)
    return [
        {
            "id": "lab_edge_abg",
            "member_id": EDGE_CRISIS_MEMBER,
            "visit_id": None,
            "test_name": "动脉血气分析",
            "test_date": base.day_str(today - timedelta(days=1)),
            "items": json.dumps(
                [
                    {"name": "PaO2", "value": "58", "unit": "mmHg", "reference": "80-100", "is_abnormal": True},
                    {"name": "SaO2", "value": "84", "unit": "%", "reference": ">95", "is_abnormal": True},
                    {"name": "乳酸", "value": "2.6", "unit": "mmol/L", "reference": "0.5-2.2", "is_abnormal": True},
                ],
                ensure_ascii=False,
            ),
            "created_at": created,
            "is_deleted": 0,
        }
    ]


def build_edge_imaging(today: date) -> list[dict]:
    created = base.dt_at(today - timedelta(days=1), 7, 0)
    return [
        {
            "id": "img_edge_ct",
            "member_id": EDGE_CRISIS_MEMBER,
            "visit_id": None,
            "exam_name": "胸部 CT",
            "exam_date": base.day_str(today - timedelta(days=1)),
            "findings": "双肺多发斑片状高密度影，下叶更明显。",
            "conclusion": "考虑感染性病变，建议结合临床治疗后复查。",
            "created_at": created,
            "is_deleted": 0,
        }
    ]


def build_edge_metrics(today: date) -> list[dict]:
    rows = []
    created = base.dt_at(today, 9, 0)

    def add(metric_type: str, value, measured_at: str, note: str = None):
        rows.append(
            {
                "id": f"edge_metric_{len(rows)+1:03d}",
                "member_id": EDGE_CRISIS_MEMBER,
                "metric_type": metric_type,
                "value": value if isinstance(value, str) else json.dumps(value, ensure_ascii=False),
                "measured_at": measured_at,
                "note": note,
                "source": "manual",
                "created_at": created,
                "is_deleted": 0,
            }
        )

    temp_series = [37.6, 38.1, 38.7, 39.1, 39.4, 39.6, 39.8]
    spo2_series = [93, 92, 91, 89, 88, 85, 83]
    hr_series = [102, 110, 118, 126, 132, 145, 154]
    sugar_series = [8.4, 8.8, 9.2, 9.7, 10.4, 11.2, 12.6]

    for idx, value in enumerate(temp_series):
        day = today - timedelta(days=6 - idx)
        add("temperature", str(value), base.dt_at(day, 7, 0), "连续发热")
    for idx, value in enumerate(spo2_series):
        day = today - timedelta(days=6 - idx)
        add("blood_oxygen", str(value), base.dt_at(day, 7, 5), "血氧逐日下降")
    for idx, value in enumerate(hr_series):
        day = today - timedelta(days=6 - idx)
        add("heart_rate", str(value), base.dt_at(day, 7, 10), "静息心率")
    for idx, value in enumerate(sugar_series):
        day = today - timedelta(days=6 - idx)
        add("blood_sugar", json.dumps({"fasting": value}, ensure_ascii=False), base.dt_at(day, 6, 40), "空腹血糖")

    add("blood_pressure", {"systolic": 186, "diastolic": 118}, base.dt_at(today - timedelta(days=1), 7, 15), "急诊前自测")
    add("weight", "92", base.dt_at(today - timedelta(days=2), 8, 0), "门诊称重")
    add("blood_pressure", {"systolic": 182, "diastolic": 112}, base.dt_at(today, 7, 20), "晨起复测")
    return rows


def build_edge_cycles(today: date) -> list[dict]:
    created = base.dt_at(today - timedelta(days=3), 12, 0)
    return [
        {
            "id": "cycle_edge_single_attack",
            "member_id": EDGE_CRISIS_MEMBER,
            "cycle_type": "migraine",
            "event_type": "attack_start",
            "event_date": base.day_str(today - timedelta(days=20)),
            "details": json.dumps({"note": "仅 1 次记录，用于测试预测不足"}, ensure_ascii=False),
            "created_at": created,
            "is_deleted": 0,
        }
    ]


def build_edge_observations(today: date) -> list[dict]:
    created = base.dt_at(today - timedelta(days=1), 20, 0)
    return [
        {
            "id": "obs_edge_respiratory",
            "member_id": EDGE_CRISIS_MEMBER,
            "obs_type": "metric",
            "title": "血氧持续下降并伴高热",
            "facts": json.dumps(["近 7 天血氧由 93% 下降至 83%", "最高体温 39.8℃"], ensure_ascii=False),
            "narrative": "适合测试趋势分析、异常检测、就医摘要和告警联动。",
            "source_records": json.dumps(["edge_metric_008", "edge_metric_001", "visit_edge_emergency"], ensure_ascii=False),
            "discovery_tokens": 40,
            "created_at": created,
            "is_deleted": 0,
        }
    ]


def build_edge_thresholds(today: date) -> list[dict]:
    created = base.dt_at(today - timedelta(days=3), 9, 0)
    updated = base.dt_at(today, 9, 0)
    return [
        {
            "id": "thr_edge_spo2_urgent",
            "member_id": EDGE_CRISIS_MEMBER,
            "metric_type": "blood_oxygen",
            "level": "urgent",
            "direction": "below",
            "threshold_value": 88,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        }
    ]


def build_edge_alert_history(today: date) -> list[dict]:
    return [
        {
            "id": "alert_edge_old_resolved",
            "member_id": EDGE_CRISIS_MEMBER,
            "metric_type": "blood_oxygen",
            "level": "warning",
            "title": "郭涛 blood_oxygen 低于阈值",
            "detail": "三天前血氧 91%。",
            "metric_value": "91",
            "threshold_value": 95,
            "is_resolved": 1,
            "resolved_at": base.dt_at(today - timedelta(days=2), 10, 0),
            "created_at": base.dt_at(today - timedelta(days=3), 7, 30),
        }
    ]


def insert_due_reminders(conn: sqlite3.Connection, today: date) -> None:
    now = base.dt_at(today, 8, 0)
    rows = [
        {
            "id": "rem_edge_due_now",
            "member_id": EDGE_CRISIS_MEMBER,
            "type": "custom",
            "title": "立即复测血氧",
            "content": "请现在复测血氧并记录。",
            "schedule_type": "once",
            "schedule_value": f"{base.day_str(today - timedelta(days=1))} 23:30",
            "next_trigger_at": f"{base.day_str(today - timedelta(days=1))} 23:30:00",
            "related_record_id": None,
            "related_record_type": None,
            "priority": "urgent",
            "last_triggered_at": None,
            "created_at": now,
            "updated_at": now,
            "is_active": 1,
            "is_deleted": 0,
        },
        {
            "id": "rem_edge_inactive_old",
            "member_id": EDGE_CRISIS_MEMBER,
            "type": "custom",
            "title": "已完成旧提醒",
            "content": "用于测试 list --all。",
            "schedule_type": "once",
            "schedule_value": f"{base.day_str(today - timedelta(days=3))} 09:00",
            "next_trigger_at": None,
            "related_record_id": None,
            "related_record_type": None,
            "priority": "low",
            "last_triggered_at": base.dt_at(today - timedelta(days=3), 9, 0),
            "created_at": base.dt_at(today - timedelta(days=4), 9, 0),
            "updated_at": base.dt_at(today - timedelta(days=3), 9, 0),
            "is_active": 0,
            "is_deleted": 0,
        },
    ]
    base.insert_many(conn, "reminders", rows)
    base.insert_many(
        conn,
        "reminder_logs",
        [
            {
                "id": "rlog_edge_old",
                "reminder_id": "rem_edge_inactive_old",
                "triggered_at": base.dt_at(today - timedelta(days=3), 9, 0),
                "delivery_channel": "session",
                "delivery_status": "delivered",
                "created_at": base.dt_at(today - timedelta(days=3), 9, 0),
            }
        ],
    )


def attach_edge_file(output_dir: Path) -> None:
    import attachment

    src = output_dir / "fixtures" / "attachment_sources" / "edge_chest_ct.txt"
    args = type("Args", (), {
        "member_id": EDGE_CRISIS_MEMBER,
        "source_path": str(src),
        "category": "medical_image",
        "description": "胸部 CT 文本摘要",
        "move": False,
        "link_record_type": "imaging_result",
        "link_record_id": "img_edge_ct",
    })
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        attachment.cmd_add(args)


def generate_extra_summaries():
    import memory

    for member_id in [EDGE_EMPTY_MEMBER, EDGE_CRISIS_MEMBER]:
        args = type("Args", (), {"member_id": member_id, "type": "all"})
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            memory.generate_summary(args)


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    base.prepare_environment(output_dir)

    import health_db

    today = date.today()
    fixture_paths = base.write_fixture_files(output_dir, today)
    fixture_paths.update(write_edge_inputs(output_dir, today))

    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        base.insert_many(conn, "members", base.build_members(today))
        base.insert_many(conn, "visits", base.build_visits(today))
        base.insert_many(conn, "symptoms", base.build_symptoms(today))
        base.insert_many(conn, "medications", base.build_medications(today))
        base.insert_many(conn, "lab_results", base.build_labs(today))
        base.insert_many(conn, "imaging_results", base.build_imaging(today))
        base.insert_many(conn, "health_metrics", base.build_metrics(today))
        base.insert_many(conn, "cycle_records", base.build_cycle_records(today))
        base.insert_many(conn, "observations", base.build_observations(today))
        base.insert_many(conn, "monitor_thresholds", base.build_monitor_thresholds(today))
        base.insert_many(conn, "monitor_alerts", base.build_monitor_alerts(today))
        diet_records, diet_items = base.build_diet(today)
        base.insert_many(conn, "diet_records", diet_records)
        base.insert_many(conn, "diet_items", diet_items)
        base.insert_many(conn, "weight_goals", base.build_weight_goals(today))
        base.insert_many(conn, "exercise_records", base.build_exercises(today))

        base.insert_many(conn, "members", build_edge_members(today))
        base.insert_many(conn, "visits", build_edge_visits(today))
        base.insert_many(conn, "symptoms", build_edge_symptoms(today))
        base.insert_many(conn, "medications", build_edge_medications(today))
        base.insert_many(conn, "lab_results", build_edge_labs(today))
        base.insert_many(conn, "imaging_results", build_edge_imaging(today))
        base.insert_many(conn, "health_metrics", build_edge_metrics(today))
        base.insert_many(conn, "cycle_records", build_edge_cycles(today))
        base.insert_many(conn, "observations", build_edge_observations(today))
        base.insert_many(conn, "monitor_thresholds", build_edge_thresholds(today))
        base.insert_many(conn, "monitor_alerts", build_edge_alert_history(today))
        insert_due_reminders(conn, today)
        conn.commit()
    finally:
        conn.close()

    base.attach_demo_files(output_dir)
    attach_edge_file(output_dir)
    base.create_reminders(today)
    generate_extra_summaries()
    base.generate_summaries()

    conn = health_db.get_connection()
    try:
        manifest = base.build_manifest(conn, output_dir, fixture_paths)
        manifest["members"].update({"empty": EDGE_EMPTY_MEMBER, "crisis": EDGE_CRISIS_MEMBER})
        manifest["edge_scenarios"] = {
            "empty_member": EDGE_EMPTY_MEMBER,
            "emergency_member": EDGE_CRISIS_MEMBER,
            "standalone_lab": "lab_edge_abg",
            "standalone_imaging": "img_edge_ct",
            "due_reminder": "rem_edge_due_now",
            "insufficient_cycle_record": "cycle_edge_single_attack",
        }
        base.write_text(output_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    finally:
        conn.close()

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
