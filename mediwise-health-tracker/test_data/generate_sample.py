#!/usr/bin/env python3
"""Generate a comprehensive synthetic dataset for MediWise Health Tracker.

This script creates a fully synthetic household dataset for end-to-end manual
testing of the following capabilities:

- member management
- visit / symptom / medication / lab / imaging records
- home health metrics and trend analysis
- reminders, observations, summaries, and family overview
- cycle tracking
- attachments
- diet / exercise / weight goal related tables
- health-monitor thresholds and alert history fixtures

Usage:
  python3 mediwise-health-tracker/test_data/generate_sample.py
  python3 mediwise-health-tracker/test_data/generate_sample.py --output-dir /tmp/mediwise-demo

The generated dataset is safe to share because it is entirely synthetic.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace


ROOT_DIR = Path(__file__).resolve().parents[2]
SKILL_DIR = ROOT_DIR / "mediwise-health-tracker"
SCRIPTS_DIR = SKILL_DIR / "scripts"
DEFAULT_OUTPUT_DIR = SKILL_DIR / "test_data" / "generated_dataset"


@dataclass(frozen=True)
class Ids:
    owner_primary: str = "owner_demo_a"
    owner_secondary: str = "owner_demo_b"
    member_self: str = "mem_self_li_chen"
    member_spouse: str = "mem_spouse_wang_min"
    member_child: str = "mem_child_li_xiaoyu"
    member_mother: str = "mem_mother_chen_xiulan"
    member_tenant_b: str = "mem_owner_b_zhao_lin"


IDS = Ids()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成 MediWise 合成测试数据")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="输出数据目录，默认写到 mediwise-health-tracker/test_data/generated_dataset",
    )
    return parser.parse_args()


def dt_at(day: date, hh: int, mm: int) -> str:
    return datetime.combine(day, time(hh, mm)).strftime("%Y-%m-%d %H:%M:%S")


def day_str(day: date) -> str:
    return day.strftime("%Y-%m-%d")


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def insert_many(conn: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(rows[0].keys())
    placeholders = ", ".join(["?"] * len(columns))
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    conn.executemany(sql, [[row[col] for col in columns] for row in rows])


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def prepare_environment(output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MEDIWISE_DATA_DIR"] = str(output_dir)
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))


def build_members(today: date) -> list[dict]:
    created = dt_at(today - timedelta(days=200), 9, 0)
    updated = dt_at(today, 9, 0)
    return [
        {
            "id": IDS.member_self,
            "name": "李晨",
            "relation": "本人",
            "gender": "男",
            "birth_date": "1987-04-18",
            "blood_type": "B+",
            "allergies": "青霉素,海鲜",
            "medical_history": "高血压,2型糖尿病,高脂血症,脂肪肝",
            "phone": "13800000001",
            "emergency_contact": "王敏",
            "emergency_phone": "13800000002",
            "owner_id": IDS.owner_primary,
            "custom_metric_ranges": json_text({"blood_pressure": {"systolic_high": 135, "diastolic_high": 85}}),
            "timezone": "Asia/Shanghai",
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": IDS.member_spouse,
            "name": "王敏",
            "relation": "配偶",
            "gender": "女",
            "birth_date": "1990-09-12",
            "blood_type": "A+",
            "allergies": "花粉",
            "medical_history": "偏头痛,季节性过敏性鼻炎",
            "phone": "13800000002",
            "emergency_contact": "李晨",
            "emergency_phone": "13800000001",
            "owner_id": IDS.owner_primary,
            "custom_metric_ranges": None,
            "timezone": "Asia/Shanghai",
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": IDS.member_child,
            "name": "李小宇",
            "relation": "子女",
            "gender": "男",
            "birth_date": "2018-02-03",
            "blood_type": "O+",
            "allergies": "无",
            "medical_history": "既往体健",
            "phone": None,
            "emergency_contact": "李晨",
            "emergency_phone": "13800000001",
            "owner_id": IDS.owner_primary,
            "custom_metric_ranges": None,
            "timezone": "Asia/Shanghai",
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": IDS.member_mother,
            "name": "陈秀兰",
            "relation": "母亲",
            "gender": "女",
            "birth_date": "1958-11-26",
            "blood_type": "O+",
            "allergies": "磺胺类",
            "medical_history": "冠心病,高脂血症,骨质疏松",
            "phone": "13800000003",
            "emergency_contact": "李晨",
            "emergency_phone": "13800000001",
            "owner_id": IDS.owner_primary,
            "custom_metric_ranges": None,
            "timezone": "Asia/Shanghai",
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": IDS.member_tenant_b,
            "name": "赵琳",
            "relation": "本人",
            "gender": "女",
            "birth_date": "1995-06-08",
            "blood_type": "AB+",
            "allergies": "无",
            "medical_history": "轻度贫血",
            "phone": "13800000009",
            "emergency_contact": "赵强",
            "emergency_phone": "13800000010",
            "owner_id": IDS.owner_secondary,
            "custom_metric_ranges": None,
            "timezone": "Asia/Shanghai",
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
    ]


def build_visits(today: date) -> list[dict]:
    visits = [
        {
            "id": "visit_self_physical",
            "member_id": IDS.member_self,
            "visit_type": "体检",
            "visit_date": day_str(today - timedelta(days=150)),
            "end_date": None,
            "hospital": "协和国际体检中心",
            "department": "体检中心",
            "chief_complaint": "年度体检",
            "diagnosis": "高血压2级；2型糖尿病；高脂血症",
            "summary": "空腹血糖、糖化血红蛋白和血脂偏高，建议控制饮食并规律复诊。",
        },
        {
            "id": "visit_self_cardiology",
            "member_id": IDS.member_self,
            "visit_type": "门诊",
            "visit_date": day_str(today - timedelta(days=22)),
            "end_date": None,
            "hospital": "市人民医院",
            "department": "心内科",
            "chief_complaint": "晨起头晕、近两周血压波动",
            "diagnosis": "原发性高血压；2型糖尿病控制欠佳",
            "summary": "调整降压方案，建议继续家庭血压监测并复查血脂和肝功能。",
        },
        {
            "id": "visit_spouse_neuro",
            "member_id": IDS.member_spouse,
            "visit_type": "门诊",
            "visit_date": day_str(today - timedelta(days=41)),
            "end_date": None,
            "hospital": "市第三医院",
            "department": "神经内科",
            "chief_complaint": "反复右侧搏动性头痛伴畏光",
            "diagnosis": "偏头痛",
            "summary": "建议记录诱因，必要时发作早期使用曲普坦类药物。",
        },
        {
            "id": "visit_spouse_allergy",
            "member_id": IDS.member_spouse,
            "visit_type": "门诊",
            "visit_date": day_str(today - timedelta(days=11)),
            "end_date": None,
            "hospital": "市第三医院",
            "department": "变态反应科",
            "chief_complaint": "晨起喷嚏、鼻痒、眼痒",
            "diagnosis": "季节性过敏性鼻炎",
            "summary": "花粉季建议提前使用抗过敏药物，并减少户外暴露。",
        },
        {
            "id": "visit_child_urgent",
            "member_id": IDS.member_child,
            "visit_type": "急诊",
            "visit_date": day_str(today - timedelta(days=2)),
            "end_date": None,
            "hospital": "儿童医院",
            "department": "急诊儿科",
            "chief_complaint": "发热 39℃、咳嗽 2 天",
            "diagnosis": "急性上呼吸道感染",
            "summary": "建议退热、多饮水和居家观察，如精神差或呼吸急促及时复诊。",
        },
        {
            "id": "visit_mother_hospital",
            "member_id": IDS.member_mother,
            "visit_type": "住院",
            "visit_date": day_str(today - timedelta(days=96)),
            "end_date": day_str(today - timedelta(days=91)),
            "hospital": "市人民医院",
            "department": "心血管内科",
            "chief_complaint": "胸闷、活动后气短",
            "diagnosis": "冠状动脉粥样硬化性心脏病",
            "summary": "住院期间完善心电图、超声心动图及药物调整，出院后规律随访。",
        },
        {
            "id": "visit_mother_followup",
            "member_id": IDS.member_mother,
            "visit_type": "门诊",
            "visit_date": day_str(today - timedelta(days=12)),
            "end_date": None,
            "hospital": "市人民医院",
            "department": "心血管内科",
            "chief_complaint": "复诊评估胸闷和活动耐量",
            "diagnosis": "冠心病稳定期",
            "summary": "建议继续二级预防用药，监测血氧和活动后症状。",
        },
        {
            "id": "visit_owner_b_checkup",
            "member_id": IDS.member_tenant_b,
            "visit_type": "体检",
            "visit_date": day_str(today - timedelta(days=35)),
            "end_date": None,
            "hospital": "社区体检中心",
            "department": "体检中心",
            "chief_complaint": "年度体检",
            "diagnosis": "轻度贫血",
            "summary": "建议补铁并复查血常规。",
        },
    ]
    created = dt_at(today - timedelta(days=200), 10, 0)
    updated = dt_at(today, 10, 0)
    for row in visits:
        row["created_at"] = created
        row["updated_at"] = updated
        row["is_deleted"] = 0
    return visits


def build_symptoms(today: date) -> list[dict]:
    created = dt_at(today - timedelta(days=30), 9, 30)
    return [
        {
            "id": "sym_self_dizzy",
            "member_id": IDS.member_self,
            "visit_id": "visit_self_cardiology",
            "symptom": "头晕",
            "severity": "中度",
            "onset_date": day_str(today - timedelta(days=14)),
            "end_date": None,
            "description": "晨起和快速起身时更明显，偶有眼前发黑。",
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "sym_self_headache",
            "member_id": IDS.member_self,
            "visit_id": None,
            "symptom": "头痛",
            "severity": "轻度",
            "onset_date": day_str(today - timedelta(days=4)),
            "end_date": None,
            "description": "工作紧张后出现，伴颈肩部僵硬。",
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "sym_spouse_migraine",
            "member_id": IDS.member_spouse,
            "visit_id": "visit_spouse_neuro",
            "symptom": "右侧搏动性头痛",
            "severity": "重度",
            "onset_date": day_str(today - timedelta(days=42)),
            "end_date": None,
            "description": "常伴畏光、恶心，睡眠不足时更易发作。",
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "sym_spouse_allergy",
            "member_id": IDS.member_spouse,
            "visit_id": "visit_spouse_allergy",
            "symptom": "鼻痒喷嚏",
            "severity": "中度",
            "onset_date": day_str(today - timedelta(days=15)),
            "end_date": None,
            "description": "户外活动后明显，伴流清涕和眼痒。",
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "sym_child_fever",
            "member_id": IDS.member_child,
            "visit_id": "visit_child_urgent",
            "symptom": "发热",
            "severity": "重度",
            "onset_date": day_str(today - timedelta(days=3)),
            "end_date": None,
            "description": "最高体温 39.1℃，伴乏力。",
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "sym_child_cough",
            "member_id": IDS.member_child,
            "visit_id": "visit_child_urgent",
            "symptom": "咳嗽",
            "severity": "中度",
            "onset_date": day_str(today - timedelta(days=3)),
            "end_date": None,
            "description": "夜间偏重，无明显喘息。",
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "sym_mother_chest",
            "member_id": IDS.member_mother,
            "visit_id": "visit_mother_followup",
            "symptom": "胸闷",
            "severity": "中度",
            "onset_date": day_str(today - timedelta(days=14)),
            "end_date": None,
            "description": "快走后明显，休息后可缓解。",
            "created_at": created,
            "is_deleted": 0,
        },
    ]


def build_medications(today: date) -> list[dict]:
    updated = dt_at(today, 9, 45)
    created = dt_at(today - timedelta(days=120), 9, 45)
    return [
        {
            "id": "med_self_amlodipine",
            "member_id": IDS.member_self,
            "visit_id": "visit_self_cardiology",
            "name": "氨氯地平",
            "dosage": "5mg",
            "frequency": "每日一次 早晨",
            "start_date": day_str(today - timedelta(days=120)),
            "end_date": None,
            "purpose": "控制血压",
            "stop_reason": None,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "med_self_metformin",
            "member_id": IDS.member_self,
            "visit_id": "visit_self_physical",
            "name": "二甲双胍",
            "dosage": "500mg",
            "frequency": "每日两次 餐后",
            "start_date": day_str(today - timedelta(days=110)),
            "end_date": None,
            "purpose": "控制血糖",
            "stop_reason": None,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "med_self_rosuvastatin",
            "member_id": IDS.member_self,
            "visit_id": "visit_self_physical",
            "name": "瑞舒伐他汀",
            "dosage": "10mg",
            "frequency": "每晚一次",
            "start_date": day_str(today - timedelta(days=105)),
            "end_date": None,
            "purpose": "降脂",
            "stop_reason": None,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "med_self_nifedipine_old",
            "member_id": IDS.member_self,
            "visit_id": "visit_self_physical",
            "name": "硝苯地平缓释片",
            "dosage": "30mg",
            "frequency": "每日一次",
            "start_date": day_str(today - timedelta(days=180)),
            "end_date": day_str(today - timedelta(days=90)),
            "purpose": "控制血压",
            "stop_reason": "改用氨氯地平后停用",
            "is_active": 0,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "med_spouse_sumatriptan",
            "member_id": IDS.member_spouse,
            "visit_id": "visit_spouse_neuro",
            "name": "舒马曲普坦",
            "dosage": "50mg",
            "frequency": "发作时一次，必要时2小时后可重复",
            "start_date": day_str(today - timedelta(days=41)),
            "end_date": None,
            "purpose": "缓解偏头痛急性发作",
            "stop_reason": None,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "med_spouse_loratadine",
            "member_id": IDS.member_spouse,
            "visit_id": "visit_spouse_allergy",
            "name": "氯雷他定",
            "dosage": "10mg",
            "frequency": "每日一次",
            "start_date": day_str(today - timedelta(days=11)),
            "end_date": None,
            "purpose": "缓解过敏性鼻炎",
            "stop_reason": None,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "med_child_ibuprofen",
            "member_id": IDS.member_child,
            "visit_id": "visit_child_urgent",
            "name": "布洛芬混悬液",
            "dosage": "5mL",
            "frequency": "发热时每6-8小时一次",
            "start_date": day_str(today - timedelta(days=2)),
            "end_date": None,
            "purpose": "退热",
            "stop_reason": None,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "med_mother_aspirin",
            "member_id": IDS.member_mother,
            "visit_id": "visit_mother_hospital",
            "name": "阿司匹林肠溶片",
            "dosage": "100mg",
            "frequency": "每日一次",
            "start_date": day_str(today - timedelta(days=95)),
            "end_date": None,
            "purpose": "冠心病二级预防",
            "stop_reason": None,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "med_mother_metoprolol",
            "member_id": IDS.member_mother,
            "visit_id": "visit_mother_hospital",
            "name": "美托洛尔缓释片",
            "dosage": "47.5mg",
            "frequency": "每日一次",
            "start_date": day_str(today - timedelta(days=95)),
            "end_date": None,
            "purpose": "控制心率并改善心绞痛症状",
            "stop_reason": None,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "med_mother_atorvastatin",
            "member_id": IDS.member_mother,
            "visit_id": "visit_mother_hospital",
            "name": "阿托伐他汀",
            "dosage": "20mg",
            "frequency": "每晚一次",
            "start_date": day_str(today - timedelta(days=95)),
            "end_date": None,
            "purpose": "降脂稳定斑块",
            "stop_reason": None,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
    ]


def build_labs(today: date) -> list[dict]:
    created = dt_at(today - timedelta(days=20), 11, 0)
    return [
        {
            "id": "lab_self_metabolic",
            "member_id": IDS.member_self,
            "visit_id": "visit_self_cardiology",
            "test_name": "代谢与血脂组合",
            "test_date": day_str(today - timedelta(days=3)),
            "items": json_text([
                {"name": "空腹血糖", "value": "8.3", "unit": "mmol/L", "reference": "3.9-6.1", "is_abnormal": True},
                {"name": "糖化血红蛋白", "value": "7.4", "unit": "%", "reference": "4.0-6.0", "is_abnormal": True},
                {"name": "总胆固醇", "value": "5.9", "unit": "mmol/L", "reference": "<5.2", "is_abnormal": True},
                {"name": "低密度脂蛋白", "value": "3.8", "unit": "mmol/L", "reference": "<3.4", "is_abnormal": True},
                {"name": "丙氨酸氨基转移酶", "value": "36", "unit": "U/L", "reference": "9-50", "is_abnormal": False},
            ]),
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "lab_child_cbc",
            "member_id": IDS.member_child,
            "visit_id": "visit_child_urgent",
            "test_name": "血常规",
            "test_date": day_str(today - timedelta(days=2)),
            "items": json_text([
                {"name": "白细胞", "value": "12.8", "unit": "10^9/L", "reference": "4.0-10.0", "is_abnormal": True},
                {"name": "中性粒细胞比例", "value": "78", "unit": "%", "reference": "40-75", "is_abnormal": True},
                {"name": "血红蛋白", "value": "122", "unit": "g/L", "reference": "110-160", "is_abnormal": False},
            ]),
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "lab_mother_cardiac",
            "member_id": IDS.member_mother,
            "visit_id": "visit_mother_followup",
            "test_name": "心功能与生化",
            "test_date": day_str(today - timedelta(days=12)),
            "items": json_text([
                {"name": "BNP", "value": "268", "unit": "pg/mL", "reference": "<100", "is_abnormal": True},
                {"name": "肌酐", "value": "79", "unit": "μmol/L", "reference": "45-84", "is_abnormal": False},
                {"name": "总胆固醇", "value": "4.2", "unit": "mmol/L", "reference": "<5.2", "is_abnormal": False},
            ]),
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "lab_owner_b_cbc",
            "member_id": IDS.member_tenant_b,
            "visit_id": "visit_owner_b_checkup",
            "test_name": "血常规",
            "test_date": day_str(today - timedelta(days=35)),
            "items": json_text([
                {"name": "血红蛋白", "value": "108", "unit": "g/L", "reference": "115-150", "is_abnormal": True},
                {"name": "红细胞压积", "value": "0.33", "unit": "L/L", "reference": "0.35-0.45", "is_abnormal": True},
            ]),
            "created_at": created,
            "is_deleted": 0,
        },
    ]


def build_imaging(today: date) -> list[dict]:
    created = dt_at(today - timedelta(days=18), 14, 0)
    return [
        {
            "id": "img_self_carotid",
            "member_id": IDS.member_self,
            "visit_id": "visit_self_cardiology",
            "exam_name": "颈动脉超声",
            "exam_date": day_str(today - timedelta(days=4)),
            "findings": "双侧颈动脉内中膜轻度增厚，左侧颈总动脉可见小斑块。",
            "conclusion": "颈动脉粥样硬化早期改变。",
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "img_spouse_mri",
            "member_id": IDS.member_spouse,
            "visit_id": None,
            "exam_name": "头颅 MRI",
            "exam_date": day_str(today - timedelta(days=180)),
            "findings": "未见明显占位或急性缺血灶。",
            "conclusion": "头颅 MRI 未见明显异常。",
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "img_mother_echo",
            "member_id": IDS.member_mother,
            "visit_id": "visit_mother_followup",
            "exam_name": "超声心动图",
            "exam_date": day_str(today - timedelta(days=12)),
            "findings": "左室舒张功能减低，射血分数约 58%，未见明显瓣膜重度异常。",
            "conclusion": "轻度舒张功能减低。",
            "created_at": created,
            "is_deleted": 0,
        },
    ]


def build_metrics(today: date) -> list[dict]:
    rows: list[dict] = []
    created = dt_at(today, 8, 0)

    def add(member_id: str, metric_type: str, value, measured_at: str, note: str = None, source: str = "manual"):
        rows.append(
            {
                "id": f"metric_{len(rows) + 1:03d}",
                "member_id": member_id,
                "metric_type": metric_type,
                "value": value if isinstance(value, str) else json_text(value),
                "measured_at": measured_at,
                "note": note,
                "source": source,
                "created_at": created,
                "is_deleted": 0,
            }
        )

    bp_series = [
        (148, 96), (146, 94), (149, 95), (151, 96), (145, 92), (152, 97), (154, 98),
        (150, 94), (153, 95), (156, 99), (158, 100), (155, 98), (162, 101), (165, 102),
    ]
    sugar_series = [7.4, 7.1, 7.6, 7.2, 7.8, 7.5, 7.9, 8.1, 7.7, 7.9, 8.0, 8.2, 8.1, 8.4]
    weight_series = [78.6, 78.4, 78.2, 78.0, 77.8, 77.6, 77.4]

    for offset, (sys_bp, dia_bp) in enumerate(bp_series[::-1]):
        day = today - timedelta(days=offset)
        add(IDS.member_self, "blood_pressure", {"systolic": sys_bp, "diastolic": dia_bp}, dt_at(day, 7, 20), "家用上臂式血压计")
    add(IDS.member_self, "blood_pressure", {"systolic": 168, "diastolic": 104}, dt_at(today, 8, 40), "晨起复测偏高")

    for offset, value in enumerate(sugar_series[::-1]):
        day = today - timedelta(days=offset)
        add(IDS.member_self, "blood_sugar", {"fasting": value}, dt_at(day, 6, 55), "空腹血糖")

    for offset, value in enumerate(weight_series[::-1]):
        day = today - timedelta(days=offset * 2)
        add(IDS.member_self, "weight", str(value), dt_at(day, 7, 5), "晨起空腹")

    add(IDS.member_self, "height", "174", dt_at(today - timedelta(days=150), 8, 10), "体检身高")
    add(IDS.member_self, "heart_rate", "82", dt_at(today - timedelta(days=1), 22, 0), "静息")
    add(IDS.member_self, "heart_rate", "123", dt_at(today, 8, 45), "头晕时心率")
    add(IDS.member_self, "blood_oxygen", "97", dt_at(today, 8, 46), "指夹式血氧仪")
    add(IDS.member_self, "temperature", "36.6", dt_at(today, 8, 47), "额温枪")

    spouse_period_days = [today - timedelta(days=140), today - timedelta(days=112), today - timedelta(days=84), today - timedelta(days=56), today - timedelta(days=29)]
    for index, d in enumerate(spouse_period_days):
        add(IDS.member_spouse, "weight", str(56.5 - index * 0.1), dt_at(d, 7, 0), "晨起体重")
    add(IDS.member_spouse, "blood_pressure", {"systolic": 112, "diastolic": 72}, dt_at(today - timedelta(days=6), 7, 30), "家用血压计")
    add(IDS.member_spouse, "heart_rate", "76", dt_at(today - timedelta(days=6), 7, 31), "静息")
    add(IDS.member_spouse, "temperature", "36.5", dt_at(today - timedelta(days=6), 7, 32), "晨测")

    add(IDS.member_child, "temperature", "38.3", dt_at(today - timedelta(days=3), 20, 0), "耳温枪")
    add(IDS.member_child, "temperature", "39.1", dt_at(today - timedelta(days=2), 7, 30), "耳温枪")
    add(IDS.member_child, "temperature", "37.8", dt_at(today - timedelta(days=1), 19, 40), "耳温枪")
    add(IDS.member_child, "heart_rate", "128", dt_at(today - timedelta(days=2), 7, 35), "发热时")
    add(IDS.member_child, "blood_oxygen", "97", dt_at(today - timedelta(days=2), 7, 36), "指夹式血氧仪")
    add(IDS.member_child, "weight", "24.5", dt_at(today - timedelta(days=30), 8, 0), "门诊称重")

    add(IDS.member_mother, "blood_pressure", {"systolic": 136, "diastolic": 78}, dt_at(today - timedelta(days=5), 8, 10), "家用血压计")
    add(IDS.member_mother, "blood_pressure", {"systolic": 134, "diastolic": 76}, dt_at(today - timedelta(days=1), 8, 15), "家用血压计")
    add(IDS.member_mother, "heart_rate", "58", dt_at(today - timedelta(days=1), 8, 16), "静息")
    add(IDS.member_mother, "blood_oxygen", "92", dt_at(today, 8, 20), "晨起轻度气短时")
    add(IDS.member_mother, "blood_oxygen", "89", dt_at(today, 8, 50), "活动后复测")
    add(IDS.member_mother, "weight", "63.2", dt_at(today - timedelta(days=10), 8, 5), "晨起体重")

    add(IDS.member_tenant_b, "weight", "52.4", dt_at(today - timedelta(days=35), 8, 0), "体检称重")
    add(IDS.member_tenant_b, "heart_rate", "72", dt_at(today - timedelta(days=35), 9, 0), "仅用于隔离测试")
    return rows


def build_cycle_records(today: date) -> list[dict]:
    created = dt_at(today - timedelta(days=160), 12, 0)
    records: list[dict] = []

    def add(record_id: str, member_id: str, cycle_type: str, event_type: str, event_day: date, details=None):
        records.append(
            {
                "id": record_id,
                "member_id": member_id,
                "cycle_type": cycle_type,
                "event_type": event_type,
                "event_date": day_str(event_day),
                "details": json_text(details) if details is not None else None,
                "created_at": created,
                "is_deleted": 0,
            }
        )

    menstrual_starts = [today - timedelta(days=140), today - timedelta(days=112), today - timedelta(days=84), today - timedelta(days=56), today - timedelta(days=29)]
    for idx, start_day in enumerate(menstrual_starts, start=1):
        add(f"cycle_menstrual_start_{idx}", IDS.member_spouse, "menstrual", "period_start", start_day, {"flow": "normal"})
        add(f"cycle_menstrual_end_{idx}", IDS.member_spouse, "menstrual", "period_end", start_day + timedelta(days=4), {"pain": "mild"})

    migraine_starts = [today - timedelta(days=118), today - timedelta(days=89), today - timedelta(days=60), today - timedelta(days=31)]
    for idx, start_day in enumerate(migraine_starts, start=1):
        add(f"cycle_migraine_start_{idx}", IDS.member_spouse, "migraine", "attack_start", start_day, {"trigger": "睡眠不足" if idx % 2 else "经前"})
        add(f"cycle_migraine_end_{idx}", IDS.member_spouse, "migraine", "attack_end", start_day + timedelta(days=1), {"response": "服药后缓解"})

    allergy_starts = [today - timedelta(days=95), today - timedelta(days=7)]
    for idx, start_day in enumerate(allergy_starts, start=1):
        add(f"cycle_allergy_start_{idx}", IDS.member_spouse, "allergy", "flare_start", start_day, {"season": "spring"})
        add(f"cycle_allergy_end_{idx}", IDS.member_spouse, "allergy", "flare_end", start_day + timedelta(days=6), {"treatment": "口服抗组胺药"})

    return records


def build_observations(today: date) -> list[dict]:
    created = dt_at(today - timedelta(days=6), 18, 0)
    return [
        {
            "id": "obs_self_bp_trend",
            "member_id": IDS.member_self,
            "obs_type": "metric",
            "title": "近两周晨起血压持续偏高",
            "facts": json_text(["最近 14 天收缩压多次 ≥150mmHg", "今晨复测 168/104mmHg"]),
            "narrative": "晨起血压整体高于目标范围，伴间断头晕，建议结合家庭血压监测评估药物是否需调整。",
            "source_records": json_text(["metric_001", "metric_015", "visit_self_cardiology"]),
            "discovery_tokens": 42,
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "obs_self_glucose",
            "member_id": IDS.member_self,
            "obs_type": "metric",
            "title": "空腹血糖控制欠佳",
            "facts": json_text(["近一周空腹血糖多次 >7.8mmol/L", "糖化血红蛋白 7.4%"]),
            "narrative": "近期血糖控制不理想，需复盘饮食和药物依从性。",
            "source_records": json_text(["lab_self_metabolic"]),
            "discovery_tokens": 36,
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "obs_spouse_cycle",
            "member_id": IDS.member_spouse,
            "obs_type": "note",
            "title": "经前 1-2 天偏头痛易发",
            "facts": json_text(["近 4 次偏头痛与经期前后时间接近", "睡眠不足时发作更明显"]),
            "narrative": "偏头痛与经期及睡眠不足相关，适合测试周期预测和就诊摘要。",
            "source_records": json_text(["cycle_migraine_start_2", "cycle_menstrual_start_4"]),
            "discovery_tokens": 28,
            "created_at": created,
            "is_deleted": 0,
        },
        {
            "id": "obs_global_demo",
            "member_id": None,
            "obs_type": "note",
            "title": "本数据集为完全合成数据",
            "facts": json_text(["适合演示录入、查询、监测、导出和附件功能", "不包含任何真实个人信息"]),
            "narrative": "可以安全用于截图、回归测试和演示。",
            "source_records": json_text([]),
            "discovery_tokens": 18,
            "created_at": created,
            "is_deleted": 0,
        },
    ]


def build_monitor_thresholds(today: date) -> list[dict]:
    created = dt_at(today - timedelta(days=30), 9, 0)
    updated = dt_at(today - timedelta(days=1), 9, 0)
    return [
        {
            "id": "thr_self_hr_warning",
            "member_id": IDS.member_self,
            "metric_type": "heart_rate",
            "level": "warning",
            "direction": "above",
            "threshold_value": 95,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "thr_self_bp_urgent",
            "member_id": IDS.member_self,
            "metric_type": "blood_pressure_systolic",
            "level": "urgent",
            "direction": "above",
            "threshold_value": 155,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
        {
            "id": "thr_mother_spo2_warning",
            "member_id": IDS.member_mother,
            "metric_type": "blood_oxygen",
            "level": "warning",
            "direction": "below",
            "threshold_value": 93,
            "is_active": 1,
            "created_at": created,
            "updated_at": updated,
            "is_deleted": 0,
        },
    ]


def build_monitor_alerts(today: date) -> list[dict]:
    return [
        {
            "id": "alert_self_resolved_old",
            "member_id": IDS.member_self,
            "metric_type": "blood_pressure_systolic",
            "level": "urgent",
            "title": "李晨 blood_pressure_systolic 高于阈值",
            "detail": "2 天前家庭血压收缩压 161mmHg，已人工复核。",
            "metric_value": "161",
            "threshold_value": 155,
            "is_resolved": 1,
            "resolved_at": dt_at(today - timedelta(days=4), 9, 0),
            "created_at": dt_at(today - timedelta(days=5), 8, 0),
        },
        {
            "id": "alert_self_pending_old",
            "member_id": IDS.member_self,
            "metric_type": "blood_pressure_systolic",
            "level": "warning",
            "title": "李晨 blood_pressure_systolic 高于阈值",
            "detail": "48 小时前家庭监测收缩压 152mmHg。",
            "metric_value": "152",
            "threshold_value": 140,
            "is_resolved": 0,
            "resolved_at": None,
            "created_at": dt_at(today - timedelta(days=2), 8, 0),
        },
        {
            "id": "alert_child_pending_old",
            "member_id": IDS.member_child,
            "metric_type": "temperature",
            "level": "warning",
            "title": "李小宇 temperature 高于阈值",
            "detail": "两天前体温 38.3℃。",
            "metric_value": "38.3",
            "threshold_value": 37.3,
            "is_resolved": 0,
            "resolved_at": None,
            "created_at": dt_at(today - timedelta(days=2), 20, 10),
        },
    ]


def build_diet(today: date) -> tuple[list[dict], list[dict]]:
    records = [
        {
            "id": "diet_self_breakfast_1",
            "member_id": IDS.member_self,
            "meal_type": "breakfast",
            "meal_date": day_str(today - timedelta(days=2)),
            "meal_time": "07:50",
            "total_calories": 420,
            "total_protein": 24,
            "total_fat": 13,
            "total_carbs": 46,
            "total_fiber": 7,
            "note": "低糖早餐",
            "created_at": dt_at(today - timedelta(days=2), 8, 0),
            "is_deleted": 0,
        },
        {
            "id": "diet_self_lunch_1",
            "member_id": IDS.member_self,
            "meal_type": "lunch",
            "meal_date": day_str(today - timedelta(days=1)),
            "meal_time": "12:20",
            "total_calories": 610,
            "total_protein": 33,
            "total_fat": 18,
            "total_carbs": 72,
            "total_fiber": 8,
            "note": "米饭半碗",
            "created_at": dt_at(today - timedelta(days=1), 12, 30),
            "is_deleted": 0,
        },
        {
            "id": "diet_self_dinner_1",
            "member_id": IDS.member_self,
            "meal_type": "dinner",
            "meal_date": day_str(today),
            "meal_time": "18:40",
            "total_calories": 560,
            "total_protein": 31,
            "total_fat": 16,
            "total_carbs": 58,
            "total_fiber": 9,
            "note": "晚餐后散步",
            "created_at": dt_at(today, 18, 50),
            "is_deleted": 0,
        },
    ]
    items = [
        {"id": "diet_item_001", "record_id": "diet_self_breakfast_1", "food_name": "全麦面包", "amount": 2, "unit": "片", "calories": 160, "protein": 8, "fat": 2, "carbs": 28, "fiber": 4, "note": None, "created_at": dt_at(today - timedelta(days=2), 8, 0), "is_deleted": 0},
        {"id": "diet_item_002", "record_id": "diet_self_breakfast_1", "food_name": "水煮蛋", "amount": 2, "unit": "个", "calories": 140, "protein": 12, "fat": 10, "carbs": 1, "fiber": 0, "note": None, "created_at": dt_at(today - timedelta(days=2), 8, 0), "is_deleted": 0},
        {"id": "diet_item_003", "record_id": "diet_self_breakfast_1", "food_name": "无糖酸奶", "amount": 200, "unit": "mL", "calories": 120, "protein": 4, "fat": 1, "carbs": 17, "fiber": 3, "note": None, "created_at": dt_at(today - timedelta(days=2), 8, 0), "is_deleted": 0},
        {"id": "diet_item_004", "record_id": "diet_self_lunch_1", "food_name": "糙米饭", "amount": 150, "unit": "g", "calories": 180, "protein": 4, "fat": 1, "carbs": 38, "fiber": 2, "note": None, "created_at": dt_at(today - timedelta(days=1), 12, 30), "is_deleted": 0},
        {"id": "diet_item_005", "record_id": "diet_self_lunch_1", "food_name": "清蒸鸡胸肉", "amount": 180, "unit": "g", "calories": 260, "protein": 28, "fat": 10, "carbs": 0, "fiber": 0, "note": None, "created_at": dt_at(today - timedelta(days=1), 12, 30), "is_deleted": 0},
        {"id": "diet_item_006", "record_id": "diet_self_lunch_1", "food_name": "西兰花", "amount": 180, "unit": "g", "calories": 90, "protein": 1, "fat": 2, "carbs": 12, "fiber": 6, "note": None, "created_at": dt_at(today - timedelta(days=1), 12, 30), "is_deleted": 0},
        {"id": "diet_item_007", "record_id": "diet_self_dinner_1", "food_name": "三文鱼", "amount": 160, "unit": "g", "calories": 300, "protein": 24, "fat": 14, "carbs": 0, "fiber": 0, "note": None, "created_at": dt_at(today, 18, 50), "is_deleted": 0},
        {"id": "diet_item_008", "record_id": "diet_self_dinner_1", "food_name": "藜麦", "amount": 120, "unit": "g", "calories": 180, "protein": 5, "fat": 2, "carbs": 30, "fiber": 4, "note": None, "created_at": dt_at(today, 18, 50), "is_deleted": 0},
        {"id": "diet_item_009", "record_id": "diet_self_dinner_1", "food_name": "生菜番茄沙拉", "amount": 200, "unit": "g", "calories": 80, "protein": 2, "fat": 0, "carbs": 28, "fiber": 5, "note": None, "created_at": dt_at(today, 18, 50), "is_deleted": 0},
    ]
    return records, items


def build_weight_goals(today: date) -> list[dict]:
    return [
        {
            "id": "weight_goal_self_cut",
            "member_id": IDS.member_self,
            "goal_type": "lose",
            "start_weight": 78.6,
            "target_weight": 72.0,
            "start_date": day_str(today - timedelta(days=20)),
            "target_date": day_str(today + timedelta(days=90)),
            "daily_calorie_target": 1800,
            "status": "active",
            "note": "配合控糖与降脂饮食。",
            "created_at": dt_at(today - timedelta(days=20), 8, 30),
            "updated_at": dt_at(today, 8, 30),
            "is_deleted": 0,
        }
    ]


def build_exercises(today: date) -> list[dict]:
    return [
        {
            "id": "exercise_self_walk_1",
            "member_id": IDS.member_self,
            "exercise_type": "cardio",
            "exercise_name": "快走",
            "duration": 45,
            "calories_burned": 260,
            "exercise_date": day_str(today - timedelta(days=2)),
            "exercise_time": "19:30",
            "intensity": "中等",
            "note": "晚饭后公园快走",
            "created_at": dt_at(today - timedelta(days=2), 20, 20),
            "is_deleted": 0,
        },
        {
            "id": "exercise_self_cycle_1",
            "member_id": IDS.member_self,
            "exercise_type": "cardio",
            "exercise_name": "室内骑行",
            "duration": 35,
            "calories_burned": 310,
            "exercise_date": day_str(today - timedelta(days=1)),
            "exercise_time": "20:10",
            "intensity": "中等偏高",
            "note": "心率控制在 120 左右",
            "created_at": dt_at(today - timedelta(days=1), 20, 50),
            "is_deleted": 0,
        },
        {
            "id": "exercise_self_strength_1",
            "member_id": IDS.member_self,
            "exercise_type": "strength",
            "exercise_name": "自重训练",
            "duration": 25,
            "calories_burned": 140,
            "exercise_date": day_str(today),
            "exercise_time": "21:00",
            "intensity": "中等",
            "note": "俯卧撑、深蹲、平板支撑",
            "created_at": dt_at(today, 21, 30),
            "is_deleted": 0,
        },
    ]


def write_fixture_files(output_dir: Path, today: date) -> dict:
    fixtures_dir = output_dir / "fixtures"
    sources_dir = fixtures_dir / "attachment_sources"
    intake_dir = fixtures_dir / "intake_inputs"

    write_text(
        sources_dir / "self_lab_report.txt",
        """代谢与血脂组合报告\n受检人：李晨\n日期：{date}\n\n空腹血糖 8.3 mmol/L (3.9-6.1) ↑\n糖化血红蛋白 7.4 % (4.0-6.0) ↑\n总胆固醇 5.9 mmol/L (<5.2) ↑\n低密度脂蛋白 3.8 mmol/L (<3.4) ↑\n""".format(date=day_str(today - timedelta(days=3))),
    )
    write_text(
        sources_dir / "self_prescription.txt",
        """门诊处方\n姓名：李晨\n日期：{date}\n氨氯地平 5mg 每日一次\n二甲双胍 500mg 每日两次\n瑞舒伐他汀 10mg 每晚一次\n""".format(date=day_str(today - timedelta(days=22))),
    )
    write_text(
        sources_dir / "child_discharge_note.txt",
        """儿童急诊随访单\n姓名：李小宇\n日期：{date}\n诊断：急性上呼吸道感染\n建议：继续监测体温，多饮水，发热超过 3 天复诊。\n""".format(date=day_str(today - timedelta(days=2))),
    )
    write_text(
        sources_dir / "mother_echo.dcm",
        "DICOM_PLACEHOLDER\n超声心动图摘要：左室舒张功能减低，EF 58%。\n",
    )
    write_text(
        intake_dir / "quick_entry_case_01.txt",
        "今早空腹血糖7.1，血压148/96，心率82，体重77.3kg，血氧97%",
    )
    write_text(
        intake_dir / "smart_intake_case_01.txt",
        """{date} 在市人民医院心内科复诊，主诉晨起头晕和血压波动，诊断原发性高血压。\n目前服用氨氯地平5mg每日一次、二甲双胍500mg每日两次。\n今晨血压 168/104，心率 123。\n""".format(date=day_str(today - timedelta(days=22))),
    )
    write_text(
        intake_dir / "smart_intake_case_02_lab.txt",
        """代谢与血脂组合\n日期：{date}\n空腹血糖 8.3 mmol/L 参考 3.9-6.1\n糖化血红蛋白 7.4 % 参考 4.0-6.0\n低密度脂蛋白 3.8 mmol/L 参考 <3.4\n""".format(date=day_str(today - timedelta(days=3))),
    )
    write_text(
        intake_dir / "doctor_visit_case_01.txt",
        "最近两周晨起头晕明显，偶尔头痛，家里测血压多次超过160/100。正在吃氨氯地平和二甲双胍，担心是不是血压药需要调整。",
    )
    write_text(
        intake_dir / "expected_records.json",
        json.dumps(
            {
                "quick_entry_case_01.txt": ["health_metric:blood_sugar", "health_metric:blood_pressure", "health_metric:heart_rate", "health_metric:weight", "health_metric:blood_oxygen"],
                "smart_intake_case_01.txt": ["visit", "medication", "health_metric"],
                "smart_intake_case_02_lab.txt": ["lab_result"],
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    return {
        "fixtures_dir": str(fixtures_dir),
        "sources_dir": str(sources_dir),
        "intake_dir": str(intake_dir),
    }


def attach_demo_files(output_dir: Path) -> None:
    import attachment

    sources_dir = output_dir / "fixtures" / "attachment_sources"
    commands = [
        SimpleNamespace(
            member_id=IDS.member_self,
            source_path=str(sources_dir / "self_lab_report.txt"),
            category="lab_report",
            description="代谢与血脂组合原始文本",
            move=False,
            link_record_type="lab_result",
            link_record_id="lab_self_metabolic",
        ),
        SimpleNamespace(
            member_id=IDS.member_self,
            source_path=str(sources_dir / "self_prescription.txt"),
            category="prescription",
            description="心内科复诊处方",
            move=False,
            link_record_type="visit",
            link_record_id="visit_self_cardiology",
        ),
        SimpleNamespace(
            member_id=IDS.member_child,
            source_path=str(sources_dir / "child_discharge_note.txt"),
            category="other",
            description="急诊随访单",
            move=False,
            link_record_type="visit",
            link_record_id="visit_child_urgent",
        ),
        SimpleNamespace(
            member_id=IDS.member_mother,
            source_path=str(sources_dir / "mother_echo.dcm"),
            category="medical_image",
            description="超声心动图占位文件",
            move=False,
            link_record_type="imaging_result",
            link_record_id="img_mother_echo",
        ),
    ]

    for args in commands:
        with contextlib.redirect_stdout(io.StringIO()):
            attachment.cmd_add(args)


def create_reminders(today: date) -> None:
    import reminder

    reminder.auto_create_medication_reminders(IDS.member_self)
    reminder.auto_create_medication_reminders(IDS.member_mother)
    reminder.auto_create_cycle_reminders(IDS.member_spouse, "menstrual")
    reminder.create_reminder(
        member_id=IDS.member_self,
        reminder_type="metric",
        title="晨起测血压",
        schedule_type="daily",
        schedule_value="07:20",
        content="请在早餐前记录血压和心率。",
        related_record_type="health_metric",
        priority="normal",
    )
    reminder.create_reminder(
        member_id=IDS.member_child,
        reminder_type="checkup",
        title="儿童发热复查",
        schedule_type="once",
        schedule_value=(today + timedelta(days=1)).strftime("%Y-%m-%d 09:30"),
        content="如果仍高热或精神差，请带李小宇复诊。",
        related_record_type="visit",
        related_record_id="visit_child_urgent",
        priority="high",
    )
    reminder.create_reminder(
        member_id=IDS.member_mother,
        reminder_type="checkup",
        title="心内科复诊",
        schedule_type="once",
        schedule_value=(today + timedelta(days=7)).strftime("%Y-%m-%d 09:00"),
        content="携带近期血氧、血压和药物清单复诊。",
        related_record_type="visit",
        related_record_id="visit_mother_followup",
        priority="high",
    )


def generate_summaries() -> None:
    import memory

    for member_id in [IDS.member_self, IDS.member_spouse, IDS.member_mother]:
        args = SimpleNamespace(member_id=member_id, type="all")
        with contextlib.redirect_stdout(io.StringIO()):
            memory.generate_summary(args)


def build_manifest(conn: sqlite3.Connection, output_dir: Path, fixture_paths: dict) -> dict:
    return {
        "dataset_name": "mediwise-synthetic-household",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_dir": str(output_dir),
        "db_path": str(output_dir / "health.db"),
        "config_path": str(output_dir / "config.json"),
        "owner_ids": {"primary": IDS.owner_primary, "secondary": IDS.owner_secondary},
        "members": {
            "self": IDS.member_self,
            "spouse": IDS.member_spouse,
            "child": IDS.member_child,
            "mother": IDS.member_mother,
            "tenant_b": IDS.member_tenant_b,
        },
        "key_record_ids": {
            "self_cardiology_visit": "visit_self_cardiology",
            "self_metabolic_lab": "lab_self_metabolic",
            "mother_echo": "img_mother_echo",
            "child_urgent_visit": "visit_child_urgent",
            "weight_goal": "weight_goal_self_cut",
        },
        "fixture_paths": fixture_paths,
        "record_counts": {
            "members": count_rows(conn, "members"),
            "visits": count_rows(conn, "visits"),
            "symptoms": count_rows(conn, "symptoms"),
            "medications": count_rows(conn, "medications"),
            "lab_results": count_rows(conn, "lab_results"),
            "imaging_results": count_rows(conn, "imaging_results"),
            "health_metrics": count_rows(conn, "health_metrics"),
            "observations": count_rows(conn, "observations"),
            "reminders": count_rows(conn, "reminders"),
            "cycle_records": count_rows(conn, "cycle_records"),
            "attachments": count_rows(conn, "attachments"),
            "attachment_links": count_rows(conn, "attachment_links"),
            "diet_records": count_rows(conn, "diet_records"),
            "diet_items": count_rows(conn, "diet_items"),
            "weight_goals": count_rows(conn, "weight_goals"),
            "exercise_records": count_rows(conn, "exercise_records"),
            "monitor_thresholds": count_rows(conn, "monitor_thresholds"),
            "monitor_alerts": count_rows(conn, "monitor_alerts"),
            "member_summaries": count_rows(conn, "member_summaries"),
        },
        "suggested_keywords": ["糖化血红蛋白", "偏头痛", "胸闷", "阿司匹林", "花粉"],
    }


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).resolve()
    prepare_environment(output_dir)

    import health_db

    today = date.today()
    fixture_paths = write_fixture_files(output_dir, today)
    health_db.ensure_db()

    conn = health_db.get_connection()
    try:
        insert_many(conn, "members", build_members(today))
        insert_many(conn, "visits", build_visits(today))
        insert_many(conn, "symptoms", build_symptoms(today))
        insert_many(conn, "medications", build_medications(today))
        insert_many(conn, "lab_results", build_labs(today))
        insert_many(conn, "imaging_results", build_imaging(today))
        insert_many(conn, "health_metrics", build_metrics(today))
        insert_many(conn, "cycle_records", build_cycle_records(today))
        insert_many(conn, "observations", build_observations(today))
        insert_many(conn, "monitor_thresholds", build_monitor_thresholds(today))
        insert_many(conn, "monitor_alerts", build_monitor_alerts(today))
        diet_records, diet_items = build_diet(today)
        insert_many(conn, "diet_records", diet_records)
        insert_many(conn, "diet_items", diet_items)
        insert_many(conn, "weight_goals", build_weight_goals(today))
        insert_many(conn, "exercise_records", build_exercises(today))
        conn.commit()
    finally:
        conn.close()

    attach_demo_files(output_dir)
    create_reminders(today)
    generate_summaries()

    conn = health_db.get_connection()
    try:
        manifest = build_manifest(conn, output_dir, fixture_paths)
        write_text(output_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    finally:
        conn.close()

    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
