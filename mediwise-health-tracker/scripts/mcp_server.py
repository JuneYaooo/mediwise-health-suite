"""MCP Server for MediWise Health Tracker.

Exposes read-only health data tools via MCP protocol (stdio transport).
All tools respect privacy levels.

Usage:
  python3 scripts/mcp_server.py
"""

from __future__ import annotations

import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

import health_db
import privacy
import export as fhir_export
import smart_intake
import reminder as reminder_mod
import health_advisor
import briefing_report


server = Server("mediwise-health")


def _level(privacy_level: str = None) -> str:
    return privacy_level or privacy.get_default_privacy_level()


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _text(data) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=_json(data))]


# --- Tool definitions ---

TOOLS = [
    types.Tool(
        name="list_members",
        description="列出家庭成员",
        inputSchema={
            "type": "object",
            "properties": {
                "privacy_level": {"type": "string", "enum": ["full", "anonymized", "statistical"], "description": "隐私级别"},
            },
        },
    ),
    types.Tool(
        name="get_member_summary",
        description="获取成员健康摘要",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID"},
                "privacy_level": {"type": "string", "enum": ["full", "anonymized", "statistical"]},
            },
            "required": ["member_id"],
        },
    ),
    types.Tool(
        name="get_timeline",
        description="获取成员病程时间线",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID"},
                "privacy_level": {"type": "string", "enum": ["full", "anonymized", "statistical"]},
            },
            "required": ["member_id"],
        },
    ),
    types.Tool(
        name="get_active_medications",
        description="获取当前在用药物",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID"},
                "privacy_level": {"type": "string", "enum": ["full", "anonymized", "statistical"]},
            },
            "required": ["member_id"],
        },
    ),
    types.Tool(
        name="get_health_metrics",
        description="获取健康指标记录",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID"},
                "metric_type": {"type": "string", "description": "指标类型"},
                "privacy_level": {"type": "string", "enum": ["full", "anonymized", "statistical"]},
            },
            "required": ["member_id"],
        },
    ),
    types.Tool(
        name="get_visits",
        description="获取就诊记录",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID"},
                "start_date": {"type": "string", "description": "开始日期"},
                "end_date": {"type": "string", "description": "结束日期"},
                "privacy_level": {"type": "string", "enum": ["full", "anonymized", "statistical"]},
            },
            "required": ["member_id"],
        },
    ),
    types.Tool(
        name="search_records",
        description="关键词搜索健康记录",
        inputSchema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "member_id": {"type": "string", "description": "成员 ID（可选）"},
                "privacy_level": {"type": "string", "enum": ["full", "anonymized", "statistical"]},
            },
            "required": ["keyword"],
        },
    ),
    types.Tool(
        name="get_family_overview",
        description="获取全家健康概览",
        inputSchema={
            "type": "object",
            "properties": {
                "privacy_level": {"type": "string", "enum": ["full", "anonymized", "statistical"]},
            },
        },
    ),
    types.Tool(
        name="export_fhir",
        description="导出 FHIR R4 Bundle",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID"},
                "privacy_level": {"type": "string", "enum": ["full", "anonymized", "statistical"]},
            },
            "required": ["member_id"],
        },
    ),
    types.Tool(
        name="get_statistics",
        description="获取聚合统计数据",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID（可选，不指定则全家聚合）"},
            },
        },
    ),
    types.Tool(
        name="smart_extract",
        description="智能录入：从图片、PDF 或自由文本中自动提取结构化健康数据。返回提取结果供用户确认。",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID"},
                "text": {"type": "string", "description": "自由文本输入"},
                "image_base64": {"type": "string", "description": "Base64 编码的图片"},
                "image_mime_type": {"type": "string", "description": "图片 MIME 类型，默认 image/jpeg"},
                "pdf_path": {"type": "string", "description": "PDF 文件路径"},
            },
            "required": ["member_id"],
        },
    ),
    types.Tool(
        name="smart_confirm",
        description="智能录入确认：将提取的数据录入系统。传入 smart_extract 返回的数据（可经用户修改）。",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID"},
                "records": {"type": "array", "description": "smart_extract 返回的 records 数组"},
            },
            "required": ["member_id", "records"],
        },
    ),
    # --- Reminder & Health Advice tools ---
    types.Tool(
        name="create_reminder",
        description="创建健康提醒（用药/测量/复查/自定义）。支持一次性、每日、每周、每月调度。",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID"},
                "type": {"type": "string", "enum": ["medication", "metric", "checkup", "custom"], "description": "提醒类型"},
                "title": {"type": "string", "description": "提醒标题"},
                "schedule_type": {"type": "string", "enum": ["once", "daily", "weekly", "monthly"], "description": "调度类型"},
                "schedule_value": {"type": "string", "description": "调度值。once: '2025-03-15 09:00', daily: '08:00', weekly: 'monday 09:00', monthly: '15 09:00'"},
                "content": {"type": "string", "description": "提醒详细内容"},
                "related_record_id": {"type": "string", "description": "关联记录 ID（如药物 ID）"},
                "related_record_type": {"type": "string", "description": "关联记录类型（medication/visit/metric）"},
                "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"], "description": "优先级"},
                "auto_medication": {"type": "boolean", "description": "设为 true 时自动为该成员所有在用药物创建提醒，忽略其他参数"},
                "timezone": {"type": "string", "description": "时区（如 Asia/Shanghai, America/New_York），覆盖全局和成员默认时区"},
            },
            "required": ["member_id"],
        },
    ),
    types.Tool(
        name="list_reminders",
        description="查看提醒列表",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID（可选，不指定则全部）"},
                "include_inactive": {"type": "boolean", "description": "是否包含已暂停的提醒"},
            },
        },
    ),
    types.Tool(
        name="update_reminder",
        description="修改提醒（标题、内容、调度、暂停/恢复、优先级）",
        inputSchema={
            "type": "object",
            "properties": {
                "reminder_id": {"type": "string", "description": "提醒 ID"},
                "title": {"type": "string", "description": "新标题"},
                "content": {"type": "string", "description": "新内容"},
                "schedule_type": {"type": "string", "enum": ["once", "daily", "weekly", "monthly"]},
                "schedule_value": {"type": "string", "description": "新调度值"},
                "is_active": {"type": "integer", "enum": [0, 1], "description": "0=暂停, 1=恢复"},
                "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
            },
            "required": ["reminder_id"],
        },
    ),
    types.Tool(
        name="delete_reminder",
        description="删除提醒",
        inputSchema={
            "type": "object",
            "properties": {
                "reminder_id": {"type": "string", "description": "提醒 ID"},
            },
            "required": ["reminder_id"],
        },
    ),
    types.Tool(
        name="get_health_advice",
        description="获取智能健康建议和每日简报。分析指标异常、用药依从性、复查逾期、测量断档等，生成主动健康建议。",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID（可选，不指定则全家）"},
                "mode": {"type": "string", "enum": ["tips", "briefing"], "description": "tips=单人健康建议, briefing=每日简报（默认 briefing）"},
            },
        },
    ),
    types.Tool(
        name="generate_briefing_report",
        description="生成可视化健康简报 HTML 报告。包含警告摘要、健康建议、指标趋势图（Chart.js）、在用药物列表等，输出自包含的单 HTML 文件。",
        inputSchema={
            "type": "object",
            "properties": {
                "member_id": {"type": "string", "description": "成员 ID（可选，不指定则全家）"},
            },
        },
    ),
]


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return TOOLS


# --- Tool implementations ---

def _tool_list_members(args: dict):
    level = _level(args.get("privacy_level"))
    if level == "statistical":
        health_db.ensure_db()
        conn = health_db.get_connection()
        try:
            stats = privacy.aggregate_statistics(conn)
            return {"member_count": stats.get("member_count", 0)}
        finally:
            conn.close()
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        rows = conn.execute("SELECT * FROM members WHERE is_deleted=0 ORDER BY created_at").fetchall()
        members = health_db.rows_to_list(rows)
        filtered = [m for m in (privacy.filter_member(m, level) for m in members) if m]
        return {"members": filtered}
    finally:
        conn.close()


def _tool_get_member_summary(args: dict):
    member_id = args["member_id"]
    level = _level(args.get("privacy_level"))
    if level == "statistical":
        health_db.ensure_db()
        conn = health_db.get_connection()
        try:
            return privacy.aggregate_statistics(conn, member_id)
        finally:
            conn.close()
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        member = health_db.row_to_dict(conn.execute(
            "SELECT * FROM members WHERE id=? AND is_deleted=0", (member_id,)
        ).fetchone())
        if not member:
            return {"error": f"未找到成员: {member_id}"}
        member = privacy.filter_member(member, level)
        active_meds = health_db.rows_to_list(conn.execute(
            "SELECT * FROM medications WHERE member_id=? AND is_deleted=0 AND end_date IS NULL", (member_id,)
        ).fetchall())
        active_meds = [m for m in (privacy.filter_record(m, level) for m in active_meds) if m]
        recent_visits = health_db.rows_to_list(conn.execute(
            "SELECT * FROM visits WHERE member_id=? AND is_deleted=0 ORDER BY visit_date DESC LIMIT 5", (member_id,)
        ).fetchall())
        recent_visits = [v for v in (privacy.filter_record(v, level) for v in recent_visits) if v]
        latest_metrics = {}
        for mtype in ["blood_pressure", "blood_sugar", "heart_rate", "weight", "temperature", "blood_oxygen"]:
            row = conn.execute(
                "SELECT * FROM health_metrics WHERE member_id=? AND metric_type=? AND is_deleted=0 ORDER BY measured_at DESC LIMIT 1",
                (member_id, mtype)
            ).fetchone()
            if row:
                r = privacy.filter_record(health_db.row_to_dict(row), level)
                if r:
                    latest_metrics[mtype] = r
        return {"member": member, "active_medications": active_meds, "recent_visits": recent_visits, "latest_metrics": latest_metrics}
    finally:
        conn.close()


def _tool_get_timeline(args: dict):
    member_id = args["member_id"]
    level = _level(args.get("privacy_level"))
    if level == "statistical":
        health_db.ensure_db()
        conn = health_db.get_connection()
        try:
            return privacy.aggregate_statistics(conn, member_id)
        finally:
            conn.close()
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        events = []
        for row in health_db.rows_to_list(conn.execute(
            "SELECT * FROM visits WHERE member_id=? AND is_deleted=0 ORDER BY visit_date", (member_id,)
        ).fetchall()):
            r = privacy.filter_record(row, level)
            if r:
                events.append({"date": r.get("visit_date"), "type": "visit", "data": r})
        for row in health_db.rows_to_list(conn.execute(
            "SELECT * FROM symptoms WHERE member_id=? AND is_deleted=0 ORDER BY onset_date", (member_id,)
        ).fetchall()):
            r = privacy.filter_record(row, level)
            if r:
                events.append({"date": r.get("onset_date"), "type": "symptom", "data": r})
        for row in health_db.rows_to_list(conn.execute(
            "SELECT * FROM medications WHERE member_id=? AND is_deleted=0 ORDER BY start_date", (member_id,)
        ).fetchall()):
            r = privacy.filter_record(row, level)
            if r:
                events.append({"date": r.get("start_date"), "type": "medication", "data": r})
        events.sort(key=lambda e: e.get("date") or "")
        return {"timeline": events}
    finally:
        conn.close()


def _tool_get_active_medications(args: dict):
    member_id = args["member_id"]
    level = _level(args.get("privacy_level"))
    if level == "statistical":
        health_db.ensure_db()
        conn = health_db.get_connection()
        try:
            stats = privacy.aggregate_statistics(conn, member_id)
            return {"active_medication_count": stats.get("active_medication_count", 0),
                    "medication_categories": stats.get("medication_categories", [])}
        finally:
            conn.close()
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        rows = health_db.rows_to_list(conn.execute(
            "SELECT * FROM medications WHERE member_id=? AND is_deleted=0 AND end_date IS NULL", (member_id,)
        ).fetchall())
        filtered = [m for m in (privacy.filter_record(m, level) for m in rows) if m]
        return {"medications": filtered}
    finally:
        conn.close()


def _tool_get_health_metrics(args: dict):
    member_id = args["member_id"]
    metric_type = args.get("metric_type")
    level = _level(args.get("privacy_level"))
    if level == "statistical":
        health_db.ensure_db()
        conn = health_db.get_connection()
        try:
            stats = privacy.aggregate_statistics(conn, member_id)
            trends = stats.get("metric_trends", {})
            if metric_type:
                trends = {metric_type: trends.get(metric_type, [])}
            return {"metric_trends": trends}
        finally:
            conn.close()
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        sql = "SELECT * FROM health_metrics WHERE member_id=? AND is_deleted=0"
        params = [member_id]
        if metric_type:
            sql += " AND metric_type=?"
            params.append(metric_type)
        sql += " ORDER BY measured_at DESC"
        rows = health_db.rows_to_list(conn.execute(sql, params).fetchall())
        filtered = [m for m in (privacy.filter_record(m, level) for m in rows) if m]
        return {"metrics": filtered}
    finally:
        conn.close()


def _tool_get_visits(args: dict):
    member_id = args["member_id"]
    level = _level(args.get("privacy_level"))
    if level == "statistical":
        health_db.ensure_db()
        conn = health_db.get_connection()
        try:
            stats = privacy.aggregate_statistics(conn, member_id)
            return {"visit_frequency": stats.get("visit_frequency", []), "total_visits": stats.get("total_visits", 0)}
        finally:
            conn.close()
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        sql = "SELECT * FROM visits WHERE member_id=? AND is_deleted=0"
        params = [member_id]
        if args.get("start_date"):
            sql += " AND visit_date>=?"
            params.append(args["start_date"])
        if args.get("end_date"):
            sql += " AND visit_date<=?"
            params.append(args["end_date"])
        sql += " ORDER BY visit_date DESC"
        rows = health_db.rows_to_list(conn.execute(sql, params).fetchall())
        filtered = [v for v in (privacy.filter_record(v, level) for v in rows) if v]
        return {"visits": filtered}
    finally:
        conn.close()


def _tool_search_records(args: dict):
    keyword = args["keyword"]
    member_id = args.get("member_id")
    level = _level(args.get("privacy_level"))
    if level == "statistical":
        return {"error": "统计级别不支持关键词搜索"}
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        results = []
        like = f"%{keyword}%"
        # Search visits
        sql = "SELECT * FROM visits WHERE is_deleted=0 AND (diagnosis LIKE ? OR chief_complaint LIKE ? OR summary LIKE ?)"
        params = [like, like, like]
        if member_id:
            sql += " AND member_id=?"
            params.append(member_id)
        for row in health_db.rows_to_list(conn.execute(sql, params).fetchall()):
            r = privacy.filter_record(row, level)
            if r:
                results.append({"type": "visit", "data": r})
        # Search medications
        sql = "SELECT * FROM medications WHERE is_deleted=0 AND (name LIKE ? OR purpose LIKE ?)"
        params = [like, like]
        if member_id:
            sql += " AND member_id=?"
            params.append(member_id)
        for row in health_db.rows_to_list(conn.execute(sql, params).fetchall()):
            r = privacy.filter_record(row, level)
            if r:
                results.append({"type": "medication", "data": r})
        # Search symptoms
        sql = "SELECT * FROM symptoms WHERE is_deleted=0 AND (symptom LIKE ? OR description LIKE ?)"
        params = [like, like]
        if member_id:
            sql += " AND member_id=?"
            params.append(member_id)
        for row in health_db.rows_to_list(conn.execute(sql, params).fetchall()):
            r = privacy.filter_record(row, level)
            if r:
                results.append({"type": "symptom", "data": r})
        return {"keyword": keyword, "count": len(results), "results": results}
    finally:
        conn.close()


def _tool_get_family_overview(args: dict):
    level = _level(args.get("privacy_level"))
    if level == "statistical":
        health_db.ensure_db()
        conn = health_db.get_connection()
        try:
            return privacy.aggregate_statistics(conn)
        finally:
            conn.close()
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        rows = health_db.rows_to_list(conn.execute(
            "SELECT * FROM members WHERE is_deleted=0 ORDER BY created_at"
        ).fetchall())
        overview = []
        for member in rows:
            mid = member["id"]
            fm = privacy.filter_member(member, level)
            if not fm:
                continue
            active_med_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM medications WHERE member_id=? AND is_deleted=0 AND end_date IS NULL", (mid,)
            ).fetchone()["cnt"]
            visit_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM visits WHERE member_id=? AND is_deleted=0", (mid,)
            ).fetchone()["cnt"]
            overview.append({"member": fm, "active_medications": active_med_count, "total_visits": visit_count})
        return {"family": overview}
    finally:
        conn.close()


def _tool_export_fhir(args: dict):
    member_id = args["member_id"]
    level = _level(args.get("privacy_level"))
    return fhir_export.export_fhir(member_id, level)


def _tool_get_statistics(args: dict):
    member_id = args.get("member_id")
    health_db.ensure_db()
    conn = health_db.get_connection()
    try:
        return privacy.aggregate_statistics(conn, member_id)
    finally:
        conn.close()


def _tool_smart_extract(args: dict):
    member_id = args["member_id"]
    text = args.get("text")
    image_base64 = args.get("image_base64")
    pdf_path = args.get("pdf_path")

    if text:
        return smart_intake.extract("text", text, member_id)
    elif image_base64:
        mime_type = args.get("image_mime_type", "image/jpeg")
        # Write base64 to a temp file, then process as image
        import tempfile
        suffix = ".jpg" if "jpeg" in mime_type or "jpg" in mime_type else ".png"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(__import__("base64").b64decode(image_base64))
            tmp_path = tmp.name
        try:
            return smart_intake.extract("image", tmp_path, member_id)
        finally:
            os.unlink(tmp_path)
    elif pdf_path:
        return smart_intake.extract("pdf", pdf_path, member_id)
    else:
        return {"error": "请提供 text、image_base64 或 pdf_path 之一"}


def _tool_smart_confirm(args: dict):
    member_id = args["member_id"]
    records = args.get("records", [])
    if not records:
        return {"error": "records 不能为空"}
    return smart_intake.confirm(member_id, records)


def _tool_create_reminder(args: dict):
    member_id = args["member_id"]
    if args.get("auto_medication"):
        return reminder_mod.auto_create_medication_reminders(member_id)
    required = ["type", "title", "schedule_type", "schedule_value"]
    missing = [f for f in required if not args.get(f)]
    if missing:
        return {"error": f"缺少必填参数: {', '.join(missing)}"}
    return reminder_mod.create_reminder(
        member_id=member_id,
        reminder_type=args["type"],
        title=args["title"],
        schedule_type=args["schedule_type"],
        schedule_value=args["schedule_value"],
        content=args.get("content"),
        related_record_id=args.get("related_record_id"),
        related_record_type=args.get("related_record_type"),
        priority=args.get("priority", "normal"),
        timezone=args.get("timezone"),
    )


def _tool_list_reminders(args: dict):
    return reminder_mod.list_reminders(
        member_id=args.get("member_id"),
        active_only=not args.get("include_inactive", False),
    )


def _tool_update_reminder(args: dict):
    reminder_id = args["reminder_id"]
    kwargs = {k: v for k, v in args.items() if k != "reminder_id" and v is not None}
    return reminder_mod.update_reminder(reminder_id, **kwargs)


def _tool_delete_reminder(args: dict):
    return reminder_mod.delete_reminder(args["reminder_id"])


def _tool_get_health_advice(args: dict):
    mode = args.get("mode", "briefing")
    member_id = args.get("member_id")
    if mode == "tips":
        if not member_id:
            return {"error": "tips 模式需要指定 member_id"}
        return health_advisor.generate_health_tips(member_id)
    return health_advisor.get_daily_briefing(member_id)


def _tool_generate_briefing_report(args: dict):
    member_id = args.get("member_id")
    return briefing_report.generate_report(member_id)


_TOOL_HANDLERS = {
    "list_members": _tool_list_members,
    "get_member_summary": _tool_get_member_summary,
    "get_timeline": _tool_get_timeline,
    "get_active_medications": _tool_get_active_medications,
    "get_health_metrics": _tool_get_health_metrics,
    "get_visits": _tool_get_visits,
    "search_records": _tool_search_records,
    "get_family_overview": _tool_get_family_overview,
    "export_fhir": _tool_export_fhir,
    "get_statistics": _tool_get_statistics,
    "smart_extract": _tool_smart_extract,
    "smart_confirm": _tool_smart_confirm,
    "create_reminder": _tool_create_reminder,
    "list_reminders": _tool_list_reminders,
    "update_reminder": _tool_update_reminder,
    "delete_reminder": _tool_delete_reminder,
    "get_health_advice": _tool_get_health_advice,
    "generate_briefing_report": _tool_generate_briefing_report,
}


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    handler = _TOOL_HANDLERS.get(name)
    if not handler:
        return _text({"error": f"未知工具: {name}"})
    try:
        result = handler(arguments or {})
        return _text(result)
    except Exception as e:
        return _text({"error": str(e)})


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
