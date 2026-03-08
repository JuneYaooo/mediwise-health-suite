"""Generate a doctor-visit preparation summary report and image.

Builds a concise, doctor-facing summary card from:
- current free-form symptom/visit description from the user
- recent visits, symptoms, metrics, labs, and imaging
- past medical history, allergies, and active medications
- medication interaction warnings when available

Usage:
  python3 scripts/doctor_visit_report.py generate --member-id <id> --description "最近头晕..."
  python3 scripts/doctor_visit_report.py screenshot --member-id <id> --description "最近头晕..."
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import subprocess
from datetime import datetime, timedelta
from string import Template

sys.path.insert(0, os.path.dirname(__file__))

import health_db
import health_advisor
from config import DATA_DIR
from metric_utils import calculate_age, parse_metric_value

try:
    import drug_interaction
except Exception:
    drug_interaction = None


METRIC_LABELS = {
    "blood_pressure": "血压",
    "blood_sugar": "血糖",
    "heart_rate": "心率",
    "weight": "体重",
    "temperature": "体温",
    "blood_oxygen": "血氧",
}

STOPWORDS = {
    "最近", "一直", "感觉", "有点", "就是", "这个", "那个", "情况", "因为", "所以", "然后",
    "已经", "还有", "比较", "今天", "昨天", "明天", "医生", "医院", "就医", "看病", "检查",
    "一下", "一下子", "不是", "没有", "不能", "需要", "想去", "准备", "大概", "描述",
}


def _escape(text: object) -> str:
    if text is None:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _split_text_items(text: str | None) -> list[str]:
    if not text:
        return []
    parts = re.split(r"[，,；;。！？!\n]+", text)
    result = []
    seen = set()
    for part in parts:
        cleaned = re.sub(r"\s+", " ", part).strip(" -•·\t")
        if len(cleaned) < 2:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _extract_highlights(description: str) -> list[str]:
    items = _split_text_items(description)
    if not items:
        return []
    highlights = []
    for item in items:
        if len(item) > 38:
            item = item[:38].rstrip() + "…"
        highlights.append(item)
        if len(highlights) >= 5:
            break
    return highlights


def _extract_keywords(description: str) -> list[str]:
    tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}|\d+(?:\.\d+)?", description or "")
    result = []
    seen = set()
    for token in tokens:
        token = token.strip().lower()
        if not token or token in STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        result.append(token)
        if len(result) >= 8:
            break
    return result


def _format_metric(metric_type: str, raw_value: str, measured_at: str | None) -> str:
    parsed = parse_metric_value(raw_value)
    label = METRIC_LABELS.get(metric_type, metric_type)
    date_text = measured_at[:10] if measured_at else ""
    if metric_type == "blood_pressure":
        systolic = parsed.get("systolic")
        diastolic = parsed.get("diastolic")
        if systolic is not None and diastolic is not None:
            return f"{label} {systolic}/{diastolic} mmHg（{date_text}）"
    value = parsed.get("value")
    if value is not None:
        unit = ""
        if metric_type == "blood_sugar":
            unit = " mmol/L"
        elif metric_type == "heart_rate":
            unit = " bpm"
        elif metric_type == "weight":
            unit = " kg"
        elif metric_type == "temperature":
            unit = " °C"
        elif metric_type == "blood_oxygen":
            unit = " %"
        return f"{label} {value}{unit}（{date_text}）"
    return f"{label}（{date_text}）"


def _summarize_lab_items(items_raw: str | list | None) -> str:
    items = items_raw
    if isinstance(items_raw, str):
        try:
            items = json.loads(items_raw)
        except Exception:
            return ""
    if not isinstance(items, list):
        return ""
    abnormal = []
    normal = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("item_name") or ""
        value = item.get("value") or ""
        unit = item.get("unit") or ""
        if not name:
            continue
        text = f"{name} {value}{unit}".strip()
        if item.get("is_abnormal"):
            abnormal.append(text + " ↑")
        else:
            normal.append(text)
    chosen = abnormal[:3] if abnormal else normal[:2]
    return "、".join(chosen)


def _truncate(text: str | None, limit: int = 60) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _fetch_member(conn, member_id: str, owner_id: str | None) -> dict | None:
    row = conn.execute(
        "SELECT * FROM members WHERE id=? AND is_deleted=0",
        (member_id,),
    ).fetchone()
    if not row:
        return None
    if not health_db.verify_member_ownership(conn, member_id, owner_id):
        return None
    return dict(row)


def _recent_symptoms(conn, member_id: str, days: int, limit: int = 5) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT symptom, severity, onset_date, description
           FROM symptoms
           WHERE member_id=? AND is_deleted=0
           AND COALESCE(onset_date, created_at) >= ?
           ORDER BY COALESCE(onset_date, created_at) DESC
           LIMIT ?""",
        (member_id, cutoff, limit),
    ).fetchall()
    return health_db.rows_to_list(rows)


def _recent_visits(conn, member_id: str, days: int, limit: int = 4) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT visit_date, visit_type, hospital, department, chief_complaint, diagnosis, summary
           FROM visits
           WHERE member_id=? AND is_deleted=0 AND visit_date >= ?
           ORDER BY visit_date DESC LIMIT ?""",
        (member_id, cutoff, limit),
    ).fetchall()
    return health_db.rows_to_list(rows)


def _recent_labs(conn, member_id: str, days: int, limit: int = 3) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT test_name, test_date, items FROM lab_results
           WHERE member_id=? AND is_deleted=0 AND test_date >= ?
           ORDER BY test_date DESC LIMIT ?""",
        (member_id, cutoff, limit),
    ).fetchall()
    return health_db.rows_to_list(rows)


def _recent_imaging(conn, member_id: str, days: int, limit: int = 2) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT exam_name, exam_date, findings, conclusion FROM imaging_results
           WHERE member_id=? AND is_deleted=0 AND exam_date >= ?
           ORDER BY exam_date DESC LIMIT ?""",
        (member_id, cutoff, limit),
    ).fetchall()
    return health_db.rows_to_list(rows)


def _latest_metrics(conn, member_id: str, days: int = 30) -> list[dict]:
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute(
        """SELECT metric_type, value, measured_at FROM health_metrics
           WHERE member_id=? AND is_deleted=0 AND measured_at >= ?
           ORDER BY measured_at DESC""",
        (member_id, cutoff),
    ).fetchall()
    latest = []
    seen = set()
    for row in rows:
        metric_type = row["metric_type"]
        if metric_type in seen:
            continue
        seen.add(metric_type)
        latest.append(dict(row))
    return latest


def _active_medications(conn, member_id: str) -> list[dict]:
    rows = conn.execute(
        """SELECT name, dosage, frequency, start_date, purpose
           FROM medications
           WHERE member_id=? AND is_active=1 AND is_deleted=0
           ORDER BY start_date DESC, created_at DESC""",
        (member_id,),
    ).fetchall()
    return health_db.rows_to_list(rows)


def _match_score(text: str, keywords: list[str]) -> int:
    if not text or not keywords:
        return 0
    lower_text = text.lower()
    return sum(1 for kw in keywords if kw in lower_text)


def _related_history(conn, member_id: str, member: dict, keywords: list[str], limit: int = 4) -> list[str]:
    rows = conn.execute(
        """SELECT visit_date, hospital, department, chief_complaint, diagnosis, summary
           FROM visits
           WHERE member_id=? AND is_deleted=0
           ORDER BY visit_date DESC LIMIT 20""",
        (member_id,),
    ).fetchall()
    candidates = []
    for row in rows:
        item = dict(row)
        text = " ".join(filter(None, [
            item.get("chief_complaint"),
            item.get("diagnosis"),
            item.get("summary"),
            item.get("department"),
            item.get("hospital"),
        ]))
        score = _match_score(text, keywords)
        if score <= 0 and keywords:
            continue
        line = f"{item.get('visit_date', '')} {item.get('hospital', '')} {item.get('department', '')}：{item.get('diagnosis') or item.get('chief_complaint') or item.get('summary') or '既往就诊'}"
        candidates.append((score, item.get("visit_date") or "", _truncate(line, 72)))

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    result = []
    seen = set()
    if member.get("medical_history"):
        for part in _split_text_items(member.get("medical_history"))[:3]:
            result.append(f"既往史：{part}")
            seen.add(part)
    for _, _, line in candidates:
        if line in seen:
            continue
        seen.add(line)
        result.append(line)
        if len(result) >= limit:
            break
    if not result:
        recent = conn.execute(
            """SELECT visit_date, diagnosis, chief_complaint FROM visits
               WHERE member_id=? AND is_deleted=0
               ORDER BY visit_date DESC LIMIT 3""",
            (member_id,),
        ).fetchall()
        for row in recent:
            item = dict(row)
            result.append(f"{item.get('visit_date', '')}：{item.get('diagnosis') or item.get('chief_complaint') or '既往就诊'}")
    return result[:limit]


def _medication_interactions(active_meds: list[dict], limit: int = 4) -> tuple[list[dict], list[str]]:
    if drug_interaction is None or len(active_meds) < 2:
        return [], []

    resolved = []
    not_covered = []
    for med in active_meds[:8]:
        name = (med.get("name") or "").strip()
        if not name:
            continue
        try:
            en_name, cn_name, results = drug_interaction._resolve_drug(name)
        except Exception:
            continue
        if not results:
            not_covered.append(name)
            continue
        resolved.append({
            "name": name,
            "cn_name": cn_name or name,
            "en_name": en_name or name,
            "ddinter_id": results[0].get("id"),
            "ddinter_name": results[0].get("name", en_name or name),
        })

    if len(resolved) < 2:
        return [], not_covered[:3]

    interactions_by_id = {}
    found = []
    seen_pairs = set()
    for med in resolved:
        drug_id = med["ddinter_id"]
        if drug_id not in interactions_by_id:
            try:
                interactions_by_id[drug_id] = drug_interaction._get_interactions(drug_id) or []
            except Exception:
                interactions_by_id[drug_id] = []

    level_order = {"Major": 0, "Moderate": 1, "Minor": 2}
    for idx, med_a in enumerate(resolved):
        interaction_map = {item.get("id"): item for item in interactions_by_id.get(med_a["ddinter_id"], [])}
        for med_b in resolved[idx + 1:]:
            pair_key = tuple(sorted([med_a["ddinter_id"], med_b["ddinter_id"]]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            matched = interaction_map.get(med_b["ddinter_id"])
            if not matched:
                continue
            raw_level = matched.get("level", [])
            level = raw_level[0] if isinstance(raw_level, list) and raw_level else str(raw_level)
            if level not in {"Major", "Moderate"}:
                continue
            actions = matched.get("actions", [])
            found.append({
                "drug_a": med_a["cn_name"],
                "drug_b": med_b["cn_name"],
                "level": level,
                "actions": actions[:2] if isinstance(actions, list) else [],
            })

    found.sort(key=lambda x: level_order.get(x.get("level", "Minor"), 9))
    return found[:limit], not_covered[:3]


def _humanize_tip_text(text: str | None) -> str:
    if not text:
        return ""
    result = str(text)
    for key, label in METRIC_LABELS.items():
        result = result.replace(key, label)
    result = result.replace('systolic', '收缩压').replace('diastolic', '舒张压')
    result = result.replace('fasting', '空腹').replace('postprandial', '餐后')
    return result


def _doctor_notes(context: dict) -> list[str]:
    notes = []
    highlights = context.get("highlights") or []
    if highlights:
        notes.append("本次主要不适：" + "；".join(highlights[:3]))
    if context.get("allergies"):
        notes.append("请主动告知过敏史：" + context["allergies"])
    if context.get("active_medications"):
        med_names = [m.get("name") for m in context["active_medications"] if m.get("name")]
        if med_names:
            notes.append("请主动告知当前在用药：" + "、".join(med_names[:5]))
    alert_titles = [t.get("title") for t in context.get("tips", []) if t.get("severity") in {"alert", "warning"} and t.get("title")]
    if alert_titles:
        notes.append("近期需要重点说明：" + "；".join(alert_titles[:3]))
    if context.get("related_history"):
        notes.append("相关既往史建议一并告诉医生")
    return notes[:5]


def build_visit_summary(member_id: str, description: str, days: int = 180, owner_id: str | None = None) -> dict:
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        member = _fetch_member(conn, member_id, owner_id)
        if not member:
            return {"status": "error", "message": f"未找到成员: {member_id}"}

        keywords = _extract_keywords(description)
        highlights = _extract_highlights(description)
        recent_visits = _recent_visits(conn, member_id, days)
        recent_symptoms = _recent_symptoms(conn, member_id, min(days, 90))
        recent_labs = _recent_labs(conn, member_id, min(days, 180))
        recent_imaging = _recent_imaging(conn, member_id, min(days, 365))
        latest_metrics = _latest_metrics(conn, member_id, 45)
        active_meds = _active_medications(conn, member_id)
        related_history = _related_history(conn, member_id, member, keywords)
    finally:
        conn.close()

    tips_result = health_advisor.generate_health_tips(member_id)
    tips = [t for t in tips_result.get("tips", []) if t.get("severity") in {"alert", "warning"}][:5]
    interactions, uncovered_meds = _medication_interactions(active_meds)

    return {
        "status": "ok",
        "member": member,
        "age": calculate_age(member.get("birth_date")),
        "description": description,
        "highlights": highlights,
        "keywords": keywords,
        "recent_visits": recent_visits,
        "recent_symptoms": recent_symptoms,
        "recent_labs": recent_labs,
        "recent_imaging": recent_imaging,
        "latest_metrics": latest_metrics,
        "active_medications": active_meds,
        "allergies": member.get("allergies") or "",
        "medical_history": member.get("medical_history") or "",
        "related_history": related_history,
        "tips": tips,
        "medication_interactions": interactions,
        "interaction_uncovered_meds": uncovered_meds,
        "doctor_notes": _doctor_notes({
            "highlights": highlights,
            "allergies": member.get("allergies") or "",
            "active_medications": active_meds,
            "tips": tips,
            "related_history": related_history,
        }),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _render_bullets(items: list[str], empty_text: str = "暂无") -> str:
    if not items:
        return f'<div class="empty">{_escape(empty_text)}</div>'
    return "".join(f"<li>{_escape(item)}</li>" for item in items)


def _render_recent_visits(visits: list[dict]) -> str:
    if not visits:
        return '<div class="empty">最近未记录门诊/住院信息</div>'
    rows = []
    for visit in visits[:4]:
        text = visit.get("diagnosis") or visit.get("chief_complaint") or visit.get("summary") or "近期就诊"
        place = " ".join(filter(None, [visit.get("hospital"), visit.get("department")])).strip()
        rows.append(f"<li><b>{_escape(visit.get('visit_date', ''))}</b> {_escape(place)}：{_escape(_truncate(text, 58))}</li>")
    return "".join(rows)


def _render_recent_metrics(metrics: list[dict]) -> str:
    if not metrics:
        return '<div class="empty">最近 45 天未记录关键指标</div>'
    return "".join(
        f"<li>{_escape(_format_metric(m['metric_type'], m['value'], m.get('measured_at')))}</li>"
        for m in metrics[:6]
    )


def _render_recent_symptoms(symptoms: list[dict]) -> str:
    if not symptoms:
        return '<div class="empty">最近未单独记录症状条目</div>'
    items = []
    for symptom in symptoms[:5]:
        detail = symptom.get("description") or symptom.get("severity") or ""
        date_text = symptom.get("onset_date") or ""
        items.append(f"<li><b>{_escape(date_text[:10])}</b> {_escape(symptom.get('symptom', ''))} {_escape(_truncate(detail, 30))}</li>")
    return "".join(items)


def _render_recent_labs(labs: list[dict]) -> str:
    if not labs:
        return '<div class="empty">最近未记录化验结果</div>'
    items = []
    for lab in labs[:3]:
        summary = _summarize_lab_items(lab.get("items"))
        suffix = f"：{summary}" if summary else ""
        items.append(f"<li><b>{_escape(lab.get('test_date', ''))}</b> {_escape(lab.get('test_name', ''))}{_escape(suffix)}</li>")
    return "".join(items)


def _render_recent_imaging(imaging: list[dict]) -> str:
    if not imaging:
        return '<div class="empty">最近未记录影像检查</div>'
    items = []
    for exam in imaging[:2]:
        summary = exam.get("conclusion") or exam.get("findings") or ""
        items.append(f"<li><b>{_escape(exam.get('exam_date', ''))}</b> {_escape(exam.get('exam_name', ''))}：{_escape(_truncate(summary, 48))}</li>")
    return "".join(items)


def _render_medications(meds: list[dict]) -> str:
    if not meds:
        return '<div class="empty">当前未记录在用药</div>'
    items = []
    for med in meds[:6]:
        detail = " / ".join(filter(None, [med.get("dosage"), med.get("frequency"), med.get("purpose")]))
        items.append(f"<li><b>{_escape(med.get('name', ''))}</b>{('：' + _escape(detail)) if detail else ''}</li>")
    return "".join(items)


def _render_interactions(interactions: list[dict], uncovered: list[str]) -> str:
    parts = []
    if interactions:
        for item in interactions:
            actions = item.get("actions") or []
            action_text = "；".join(_truncate(a, 22) for a in actions[:2])
            parts.append(
                f"<li><span class=\"level level-{item['level'].lower()}\">{_escape(item['level'])}</span>"
                f" {_escape(item['drug_a'])} + {_escape(item['drug_b'])}"
                f"{('：' + _escape(action_text)) if action_text else ''}</li>"
            )
    if uncovered:
        parts.append(f"<li>部分药物未在交互数据库覆盖：{_escape('、'.join(uncovered))}</li>")
    if not parts:
        return '<div class="empty">当前在用药未检出明确的中高风险相互作用（基于 DDInter 可覆盖范围）</div>'
    return "".join(parts)


def _member_identity(member: dict, age: int | None) -> str:
    parts = [member.get("name") or ""]
    if member.get("relation"):
        parts.append(member["relation"])
    if member.get("gender"):
        parts.append(member["gender"])
    if age is not None:
        parts.append(f"{age}岁")
    return " · ".join([p for p in parts if p])


def render_visit_summary_html(data: dict) -> str:
    member = data["member"]
    identity = _member_identity(member, data.get("age"))
    highlights_html = _render_bullets(data.get("highlights") or [], "未从本次描述中提取到明确重点")
    recent_symptoms_html = _render_recent_symptoms(data.get("recent_symptoms") or [])
    recent_visits_html = _render_recent_visits(data.get("recent_visits") or [])
    recent_metrics_html = _render_recent_metrics(data.get("latest_metrics") or [])
    related_history_html = _render_bullets(data.get("related_history") or [], "暂无可用相关病史")
    recent_labs_html = _render_recent_labs(data.get("recent_labs") or [])
    recent_imaging_html = _render_recent_imaging(data.get("recent_imaging") or [])
    meds_html = _render_medications(data.get("active_medications") or [])
    interactions_html = _render_interactions(data.get("medication_interactions") or [], data.get("interaction_uncovered_meds") or [])
    doctor_notes_html = _render_bullets(data.get("doctor_notes") or [], "建议就诊时直接展示本图，并主动补充症状起始时间和加重缓解因素")
    alert_items = [f"{tip.get('title')}：{tip.get('detail') or tip.get('suggestion') or ''}" for tip in data.get("tips") or []]
    alerts_html = _render_bullets(alert_items, "最近未发现高优先级异常提醒")
    allergies = data.get("allergies") or "未记录"
    medical_history = data.get("medical_history") or "未记录"

    return _HTML_TEMPLATE.safe_substitute(
        report_date=_escape(datetime.now().strftime("%Y-%m-%d")),
        generated_at=_escape(data.get("generated_at")),
        identity=_escape(identity),
        description=_escape(data.get("description") or ""),
        highlights=highlights_html,
        recent_symptoms=recent_symptoms_html,
        recent_visits=recent_visits_html,
        recent_metrics=recent_metrics_html,
        alerts=alerts_html,
        related_history=related_history_html,
        medical_history=_escape(medical_history),
        recent_labs=recent_labs_html,
        recent_imaging=recent_imaging_html,
        allergies=_escape(allergies),
        medications=meds_html,
        interactions=interactions_html,
        doctor_notes=doctor_notes_html,
    )


def build_text_summary(data: dict) -> str:
    member = data.get("member", {})
    name = member.get("name") or "该成员"
    parts = [f"我先帮你整理一版就医前摘要："]

    highlights = data.get("highlights") or []
    if highlights:
        parts.append(f"- 这次主要不适：{'；'.join(highlights[:4])}。")
    elif data.get("description"):
        parts.append(f"- 这次主要不适：{_truncate(data.get('description'), 80)}")

    related_history = data.get("related_history") or []
    if related_history:
        parts.append(f"- 相关既往史：{'；'.join(related_history[:3])}。")

    metrics = data.get("latest_metrics") or []
    if metrics:
        metric_lines = [_format_metric(m.get("metric_type", ""), m.get("value", ""), m.get("measured_at")) for m in metrics[:4]]
        parts.append(f"- 最近记录的关键指标：{'；'.join(metric_lines)}。")

    recent_visits = data.get("recent_visits") or []
    if recent_visits:
        visit = recent_visits[0]
        visit_text = visit.get("diagnosis") or visit.get("chief_complaint") or visit.get("summary") or "近期有过就诊记录"
        place = ' '.join(filter(None, [visit.get('hospital'), visit.get('department')])).strip()
        parts.append(f"- 最近相关就诊：{visit.get('visit_date', '')} {place}，{visit_text}。")

    meds = data.get("active_medications") or []
    if meds:
        med_text = '、'.join(m.get('name') for m in meds[:5] if m.get('name'))
        if med_text:
            parts.append(f"- 当前在用药：{med_text}。")

    allergies = data.get("allergies")
    if allergies:
        parts.append(f"- 过敏或禁忌提醒：已记录过敏史为“{allergies}”。")

    interactions = data.get("medication_interactions") or []
    if interactions:
        interaction_text = '；'.join(f"{i.get('drug_a')} + {i.get('drug_b')}（{i.get('level')}）" for i in interactions[:3])
        parts.append(f"- 用药注意：当前记录到的中高风险相互作用包括 {interaction_text}。")

    tips = data.get("tips") or []
    if tips:
        tip = tips[0]
        detail = _humanize_tip_text(tip.get('detail') or tip.get('suggestion') or '')
        title = _humanize_tip_text(tip.get('title', ''))
        parts.append(f"- 近期还需要注意：{title}{('，' + detail) if detail else ''}。")

    parts.append(f"如果你愿意，我还可以继续把这份内容整理成图片或 PDF，方便 {name} 就诊时直接出示给医生。")
    return '\n'.join(parts)


def generate_pdf(html_path: str, output_path: str | None = None) -> dict:
    if not os.path.isfile(html_path):
        return {"status": "error", "error": f"File not found: {html_path}"}
    if output_path is None:
        output_path = os.path.splitext(html_path)[0] + '.pdf'

    chrome_cmd = [
        'google-chrome',
        '--headless=new',
        '--disable-gpu',
        '--no-sandbox',
        '--disable-dev-shm-usage',
        '--print-to-pdf-no-header',
        f'--print-to-pdf={output_path}',
        f'file://{os.path.abspath(html_path)}',
    ]
    try:
        result = subprocess.run(chrome_cmd, capture_output=True, text=True, timeout=25)
    except FileNotFoundError:
        return {"status": "error", "error": 'google-chrome not found'}
    except subprocess.TimeoutExpired:
        subprocess.run(['pkill', '-f', 'chrome.*headless'], capture_output=True)
        return {"status": "error", "error": 'Chrome print-to-pdf timed out'}

    if result.returncode != 0 or not os.path.isfile(output_path):
        stderr = (result.stderr or '')[:500]
        return {"status": "error", "error": f"PDF generation failed: {stderr}"}

    return {
        "status": "ok",
        "pdf_path": output_path,
        "file_size": os.path.getsize(output_path),
    }


def generate_report(member_id: str, description: str, days: int = 180, owner_id: str | None = None) -> dict:
    data = build_visit_summary(member_id, description, days=days, owner_id=owner_id)
    if data.get("status") != "ok":
        return data

    html = render_visit_summary_html(data)
    reports_dir = os.path.join(DATA_DIR, "reports")
    os.makedirs(reports_dir, exist_ok=True)
    date_part = datetime.now().strftime("%Y-%m-%d")
    report_path = os.path.join(reports_dir, f"doctor_visit_{date_part}_{member_id}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    return {
        "status": "ok",
        "report_path": report_path,
        "file_size": os.path.getsize(report_path),
        "member_id": member_id,
        "member_name": data["member"].get("name"),
        "highlights": data.get("highlights", []),
        "interaction_count": len(data.get("medication_interactions") or []),
        "generated_at": data.get("generated_at"),
        "summary_text": build_text_summary(data),
    }


_HTML_TEMPLATE = Template("""\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>就医前摘要 - $report_date</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #F3F6FB;
    color: #1F2937;
    line-height: 1.5;
}
.container { max-width: 1080px; margin: 0 auto; padding: 20px; }
.header {
    background: linear-gradient(135deg, #0F766E, #14B8A6);
    color: #fff;
    border-radius: 16px;
    padding: 28px 32px;
    margin-bottom: 20px;
    box-shadow: 0 10px 24px rgba(15,118,110,0.22);
}
.header h1 { font-size: 28px; margin-bottom: 8px; }
.header .meta { font-size: 14px; opacity: 0.92; }
.hero-grid {
    display: grid;
    grid-template-columns: 1.3fr 1fr;
    gap: 16px;
    margin-bottom: 18px;
}
.card {
    background: #fff;
    border-radius: 14px;
    padding: 18px 20px;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
}
.card h2 {
    font-size: 17px;
    color: #0F766E;
    margin-bottom: 12px;
    border-bottom: 2px solid #CCFBF1;
    padding-bottom: 8px;
}
.card h3 {
    font-size: 14px;
    color: #374151;
    margin: 12px 0 8px;
}
.description {
    background: #F8FAFC;
    border-left: 4px solid #14B8A6;
    border-radius: 10px;
    padding: 12px 14px;
    font-size: 14px;
}
.grid-2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 18px;
}
.grid-3 {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 16px;
    margin-bottom: 18px;
}
ul { padding-left: 18px; }
li { margin-bottom: 8px; font-size: 14px; }
.empty {
    color: #6B7280;
    font-size: 14px;
    background: #F8FAFC;
    border-radius: 10px;
    padding: 10px 12px;
}
.pill {
    display: inline-block;
    background: #CCFBF1;
    color: #115E59;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    margin: 0 8px 8px 0;
}
.level {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 700;
    margin-right: 6px;
}
.level-major { background: #FEE2E2; color: #991B1B; }
.level-moderate { background: #FEF3C7; color: #92400E; }
.kv {
    display: grid;
    grid-template-columns: 110px 1fr;
    gap: 8px;
    font-size: 14px;
    margin-bottom: 6px;
}
.kv .label { color: #6B7280; }
.footer {
    text-align: center;
    color: #94A3B8;
    font-size: 12px;
    padding: 16px 0 8px;
}
@media (max-width: 860px) {
    .hero-grid, .grid-2, .grid-3 { grid-template-columns: 1fr; }
    .container { padding: 12px; }
}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>🩺 就医前摘要图</h1>
        <div class="meta">$identity · 生成时间 $generated_at</div>
        <div class="meta">适合在门诊前快速展示给医生，帮助快速了解当前问题、既往史、在用药和注意事项</div>
    </div>

    <div class="hero-grid">
        <div class="card">
            <h2>本次想就诊的主要问题</h2>
            <div class="description">$description</div>
            <h3>自动提取的重点</h3>
            <ul>$highlights</ul>
        </div>
        <div class="card">
            <h2>基础信息</h2>
            <div class="kv"><div class="label">身份</div><div>$identity</div></div>
            <div class="kv"><div class="label">已知过敏</div><div>$allergies</div></div>
            <div class="kv"><div class="label">既往史</div><div>$medical_history</div></div>
        </div>
    </div>

    <div class="grid-2">
        <div class="card">
            <h2>近期关键信息</h2>
            <h3>近期异常 / 提醒</h3>
            <ul>$alerts</ul>
            <h3>最近记录的关键指标</h3>
            <ul>$recent_metrics</ul>
            <h3>最近症状记录</h3>
            <ul>$recent_symptoms</ul>
        </div>
        <div class="card">
            <h2>最近就诊与病情变化</h2>
            <ul>$recent_visits</ul>
            <h3>就诊时建议主动告诉医生</h3>
            <ul>$doctor_notes</ul>
        </div>
    </div>

    <div class="grid-2">
        <div class="card">
            <h2>相关既往史</h2>
            <ul>$related_history</ul>
        </div>
        <div class="card">
            <h2>当前在用药与注意事项</h2>
            <h3>在用药</h3>
            <ul>$medications</ul>
            <h3>中高风险药物相互作用提示</h3>
            <ul>$interactions</ul>
        </div>
    </div>

    <div class="grid-2">
        <div class="card">
            <h2>最近化验</h2>
            <ul>$recent_labs</ul>
        </div>
        <div class="card">
            <h2>最近影像</h2>
            <ul>$recent_imaging</ul>
        </div>
    </div>

    <div class="footer">
        <div>MediWise Health Tracker · Doctor Visit Summary</div>
        <div>本摘要基于本人描述与历史记录自动整理，仅供辅助沟通，不替代正式病历和医生判断。</div>
    </div>
</div>
</body>
</html>
""")


def main():
    if len(sys.argv) < 2:
        health_db.output_json({
            "error": "用法: doctor_visit_report.py <text|generate|screenshot|pdf|data> --member-id <id> --description <text> [--days 180]"
        })
        return

    cmd = sys.argv[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--member-id", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--width", type=int, default=1080)
    parser.add_argument("--owner-id", default=None)
    args = parser.parse_args(sys.argv[2:])

    if cmd == "data":
        health_db.output_json(build_visit_summary(args.member_id, args.description, args.days, args.owner_id))
        return

    if cmd == "text":
        data = build_visit_summary(args.member_id, args.description, args.days, args.owner_id)
        if data.get("status") != "ok":
            health_db.output_json(data)
            return
        health_db.output_json({
            "status": "ok",
            "member_id": args.member_id,
            "summary_text": build_text_summary(data),
            "next_options": ["image", "pdf"],
        })
        return

    if cmd == "generate":
        health_db.output_json(generate_report(args.member_id, args.description, args.days, args.owner_id))
        return

    if cmd == "screenshot":
        report = generate_report(args.member_id, args.description, args.days, args.owner_id)
        if report.get("status") != "ok":
            health_db.output_json(report)
            return
        import html_screenshot
        png_result = html_screenshot.screenshot(report["report_path"], width=args.width)
        png_result["html_path"] = report["report_path"]
        png_result["member_id"] = args.member_id
        png_result["summary_text"] = report.get("summary_text", "")
        health_db.output_json(png_result)
        return

    if cmd == "pdf":
        report = generate_report(args.member_id, args.description, args.days, args.owner_id)
        if report.get("status") != "ok":
            health_db.output_json(report)
            return
        pdf_result = generate_pdf(report["report_path"])
        pdf_result["html_path"] = report["report_path"]
        pdf_result["member_id"] = args.member_id
        pdf_result["summary_text"] = report.get("summary_text", "")
        health_db.output_json(pdf_result)
        return

    health_db.output_json({
        "error": f"未知命令: {cmd}",
        "commands": ["data", "text", "generate", "screenshot", "pdf"],
    })


if __name__ == "__main__":
    main()
