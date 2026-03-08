"""Attachment management for MediWise Health Tracker.

Handles file storage, metadata tracking, and record linking for
uploaded files (photos, lab reports, prescriptions, etc.).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from health_db import (
    ensure_db,
    generate_id,
    get_record_member_id,
    now_iso,
    output_json,
    row_to_dict,
    rows_to_list,
    transaction,
    verify_member_ownership,
    verify_record_ownership,
)
from config import DATA_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = [
    "body_photo",
    "food_photo",
    "medical_image",
    "lab_report",
    "prescription",
    "exercise_photo",
    "other",
]

VALID_RECORD_TYPES = [
    "health_metric",
    "diet_record",
    "exercise_record",
    "visit",
    "medication",
    "lab_result",
    "imaging_result",
    "weight_goal",
]

_RECORD_TYPE_TABLE = {
    "health_metric": "health_metrics",
    "diet_record": "diet_records",
    "exercise_record": "exercise_records",
    "visit": "visits",
    "medication": "medications",
    "lab_result": "lab_results",
    "imaging_result": "imaging_results",
    "weight_goal": "weight_goals",
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_BASE64_FILE_SIZE = 10 * 1024 * 1024  # 10 MB for base64 encoding

# Extra MIME mappings not always present in the stdlib
_EXTRA_MIME = {
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".webp": "image/webp",
    ".dcm": "application/dicom",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_filename(name: str, max_len: int = 50) -> str:
    """Keep letters, digits, CJK chars, and underscores."""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]", "_", name)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:max_len] if cleaned else "file"


def _guess_mime(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _EXTRA_MIME:
        return _EXTRA_MIME[ext]
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _attachments_dir(member_id: str) -> str:
    return os.path.join(DATA_DIR, "attachments", member_id)


def _abs_path(rel: str) -> str:
    """Convert a DATA_DIR-relative path to absolute."""
    return os.path.join(DATA_DIR, rel)


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------


def cmd_add(args):
    ensure_db()

    src = args.source_path
    if not os.path.isfile(src):
        output_json({"status": "error", "message": f"文件不存在: {src}"})
        return

    file_size = os.path.getsize(src)
    if file_size > MAX_FILE_SIZE:
        output_json({"status": "error", "message": f"文件过大 ({file_size} bytes)，最大允许 {MAX_FILE_SIZE} bytes"})
        return

    if args.category not in VALID_CATEGORIES:
        output_json({"status": "error", "message": f"不支持的分类: {args.category}，支持: {', '.join(VALID_CATEGORIES)}"})
        return

    with transaction() as conn:
        if not verify_member_ownership(conn, args.member_id, getattr(args, "owner_id", None)):
            output_json({"status": "error", "message": f"无权访问成员: {args.member_id}"})
            return
        m = conn.execute("SELECT id FROM members WHERE id=? AND is_deleted=0", (args.member_id,)).fetchone()
        if not m:
            output_json({"status": "error", "message": f"未找到成员: {args.member_id}"})
            return

        file_hash = _sha256(src)

        # Dedup: same member + same sha256
        existing = conn.execute(
            "SELECT * FROM attachments WHERE member_id=? AND sha256=? AND is_deleted=0",
            (args.member_id, file_hash),
        ).fetchone()
        if existing:
            att = row_to_dict(existing)
            att["file_path"] = _abs_path(att["file_path"])
            output_json({"status": "ok", "message": "文件已存在（去重）", "attachment": att, "deduplicated": True})
            return

        att_id = generate_id()
        original = os.path.basename(src)
        name_part, ext = os.path.splitext(original)
        sanitized = _sanitize_filename(name_part)
        stored = f"{att_id}_{sanitized}{ext}"

        dest_dir = _attachments_dir(args.member_id)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, stored)

        if args.move:
            shutil.move(src, dest)
        else:
            shutil.copy2(src, dest)

        rel_path = os.path.relpath(dest, DATA_DIR)
        mime = _guess_mime(dest)
        ts = now_iso()

        conn.execute(
            """INSERT INTO attachments
               (id, member_id, original_filename, stored_filename, file_path,
                file_size, mime_type, category, sha256, description, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (att_id, args.member_id, original, stored, rel_path,
             file_size, mime, args.category, file_hash, args.description, ts, ts),
        )

        # Optional immediate link
        link_msg = ""
        if args.link_record_type and args.link_record_id:
            rt, ri = args.link_record_type, args.link_record_id
            if rt not in VALID_RECORD_TYPES:
                conn.rollback()
                output_json({"status": "error", "message": f"不支持的记录类型: {rt}"})
                return
            tbl = _RECORD_TYPE_TABLE[rt]
            rec = conn.execute(f"SELECT id FROM {tbl} WHERE id=? AND is_deleted=0", (ri,)).fetchone()
            if not rec:
                conn.rollback()
                output_json({"status": "error", "message": f"未找到记录: {rt}/{ri}"})
                return
            record_member_id = get_record_member_id(conn, tbl, ri)
            if record_member_id != args.member_id:
                conn.rollback()
                output_json({"status": "error", "message": f"记录不属于成员: {rt}/{ri}"})
                return
            link_id = generate_id()
            conn.execute(
                "INSERT INTO attachment_links (id, attachment_id, record_type, record_id, created_at) VALUES (?,?,?,?,?)",
                (link_id, att_id, rt, ri, ts),
            )
            link_msg = f"，已关联到 {rt}/{ri}"

        conn.commit()

        att = row_to_dict(conn.execute("SELECT * FROM attachments WHERE id=?", (att_id,)).fetchone())
        att["file_path"] = _abs_path(att["file_path"])
        output_json({"status": "ok", "message": f"附件已添加{link_msg}", "attachment": att})


def cmd_list(args):
    ensure_db()
    with transaction() as conn:
        if not verify_member_ownership(conn, args.member_id, getattr(args, "owner_id", None)):
            output_json({"status": "error", "message": f"无权访问成员: {args.member_id}"})
            return
        clauses = ["a.member_id=?", "a.is_deleted=0"]
        params: list = [args.member_id]

        if args.category:
            if args.category not in VALID_CATEGORIES:
                output_json({"status": "error", "message": f"不支持的分类: {args.category}"})
                return
            clauses.append("a.category=?")
            params.append(args.category)

        join = ""
        if args.record_type and args.record_id:
            join = " JOIN attachment_links al ON al.attachment_id=a.id AND al.is_deleted=0"
            clauses.append("al.record_type=?")
            clauses.append("al.record_id=?")
            params.append(args.record_type)
            params.append(args.record_id)

        where = " AND ".join(clauses)
        limit = min(args.limit, 200)
        sql = f"SELECT DISTINCT a.* FROM attachments a{join} WHERE {where} ORDER BY a.created_at DESC LIMIT ?"
        params.append(limit)

        rows = rows_to_list(conn.execute(sql, params).fetchall())
        for r in rows:
            r["file_path"] = _abs_path(r["file_path"])
        output_json({"status": "ok", "attachments": rows, "count": len(rows)})


def cmd_get(args):
    ensure_db()
    with transaction() as conn:
        row = conn.execute("SELECT * FROM attachments WHERE id=? AND is_deleted=0", (args.id,)).fetchone()
        if not row:
            output_json({"status": "error", "message": f"未找到附件: {args.id}"})
            return
        if not verify_record_ownership(conn, "attachments", args.id, getattr(args, "owner_id", None)):
            output_json({"status": "error", "message": f"无权访问附件: {args.id}"})
            return

        att = row_to_dict(row)
        abs_p = _abs_path(att["file_path"])
        att["file_path"] = abs_p
        att["file_exists"] = os.path.isfile(abs_p)

        links = rows_to_list(
            conn.execute(
                "SELECT * FROM attachment_links WHERE attachment_id=? AND is_deleted=0",
                (args.id,),
            ).fetchall()
        )

        result = {"status": "ok", "attachment": att, "links": links}

        if getattr(args, "base64", False):
            if not os.path.isfile(abs_p):
                output_json({"status": "error", "message": f"文件不存在: {abs_p}"})
                return
            file_size = os.path.getsize(abs_p)
            if file_size > MAX_BASE64_FILE_SIZE:
                output_json({
                    "status": "error",
                    "message": f"文件过大 ({file_size} bytes)，base64 编码最大允许 {MAX_BASE64_FILE_SIZE} bytes",
                })
                return
            with open(abs_p, "rb") as f:
                raw = f.read()
            b64 = base64.b64encode(raw).decode("ascii")
            mime = att.get("mime_type", "application/octet-stream")
            result["data"] = b64
            result["data_uri"] = f"data:{mime};base64,{b64}"

        output_json(result)


def cmd_delete(args):
    ensure_db()
    with transaction() as conn:
        row = conn.execute("SELECT * FROM attachments WHERE id=? AND is_deleted=0", (args.id,)).fetchone()
        if not row:
            output_json({"status": "error", "message": f"未找到附件: {args.id}"})
            return
        if not verify_record_ownership(conn, "attachments", args.id, getattr(args, "owner_id", None)):
            output_json({"status": "error", "message": f"无权访问附件: {args.id}"})
            return

        ts = now_iso()
        conn.execute("UPDATE attachments SET is_deleted=1, updated_at=? WHERE id=?", (ts, args.id))
        conn.execute("UPDATE attachment_links SET is_deleted=1 WHERE attachment_id=?", (args.id,))

        purged = False
        if args.purge:
            abs_p = _abs_path(row["file_path"])
            if os.path.isfile(abs_p):
                os.remove(abs_p)
                purged = True

        conn.commit()
        msg = "附件已删除" + ("（文件已清除）" if purged else "（软删除）")
        output_json({"status": "ok", "message": msg})


def cmd_link(args):
    ensure_db()
    if args.record_type not in VALID_RECORD_TYPES:
        output_json({"status": "error", "message": f"不支持的记录类型: {args.record_type}，支持: {', '.join(VALID_RECORD_TYPES)}"})
        return

    with transaction() as conn:
        owner_id = getattr(args, "owner_id", None)
        att = conn.execute("SELECT id FROM attachments WHERE id=? AND is_deleted=0", (args.attachment_id,)).fetchone()
        if not att:
            output_json({"status": "error", "message": f"未找到附件: {args.attachment_id}"})
            return
        if not verify_record_ownership(conn, "attachments", args.attachment_id, owner_id):
            output_json({"status": "error", "message": f"无权访问附件: {args.attachment_id}"})
            return

        tbl = _RECORD_TYPE_TABLE[args.record_type]
        rec = conn.execute(f"SELECT id FROM {tbl} WHERE id=? AND is_deleted=0", (args.record_id,)).fetchone()
        if not rec:
            output_json({"status": "error", "message": f"未找到记录: {args.record_type}/{args.record_id}"})
            return
        if not verify_record_ownership(conn, tbl, args.record_id, owner_id):
            output_json({"status": "error", "message": f"无权访问记录: {args.record_type}/{args.record_id}"})
            return
        attachment_member_id = get_record_member_id(conn, "attachments", args.attachment_id)
        record_member_id = get_record_member_id(conn, tbl, args.record_id)
        if attachment_member_id != record_member_id:
            output_json({"status": "error", "message": "附件只能关联到同一成员的记录"})
            return

        # Check for existing active link
        dup = conn.execute(
            "SELECT id FROM attachment_links WHERE attachment_id=? AND record_type=? AND record_id=? AND is_deleted=0",
            (args.attachment_id, args.record_type, args.record_id),
        ).fetchone()
        if dup:
            output_json({"status": "ok", "message": "关联已存在", "link_id": dup["id"]})
            return

        link_id = generate_id()
        ts = now_iso()
        conn.execute(
            "INSERT INTO attachment_links (id, attachment_id, record_type, record_id, created_at) VALUES (?,?,?,?,?)",
            (link_id, args.attachment_id, args.record_type, args.record_id, ts),
        )
        conn.commit()
        output_json({"status": "ok", "message": "已关联", "link_id": link_id})


def cmd_unlink(args):
    ensure_db()
    with transaction() as conn:
        owner_id = getattr(args, "owner_id", None)
        if not verify_record_ownership(conn, "attachments", args.attachment_id, owner_id):
            output_json({"status": "error", "message": f"无权访问附件: {args.attachment_id}"})
            return
        link = conn.execute(
            "SELECT id FROM attachment_links WHERE attachment_id=? AND record_type=? AND record_id=? AND is_deleted=0",
            (args.attachment_id, args.record_type, args.record_id),
        ).fetchone()
        if not link:
            output_json({"status": "error", "message": "未找到该关联"})
            return
        conn.execute("UPDATE attachment_links SET is_deleted=1 WHERE id=?", (link["id"],))
        conn.commit()
        output_json({"status": "ok", "message": "已取消关联"})


# ---------------------------------------------------------------------------
# Signing helpers
# ---------------------------------------------------------------------------


def _make_signature(secret: str, attachment_id: str, exp: int) -> str:
    """HMAC-SHA256 signature for a file URL."""
    msg = f"{attachment_id}:{exp}"
    return hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()


def _get_secret(args) -> str:
    """Resolve secret from args or environment variable."""
    secret = getattr(args, "secret", None) or os.environ.get("MEDIWISE_FILE_SECRET")
    if not secret:
        output_json({
            "status": "error",
            "message": "未提供 secret，请通过 --secret 参数或 MEDIWISE_FILE_SECRET 环境变量指定",
        })
        return ""
    return secret


# ---------------------------------------------------------------------------
# serve sub-command
# ---------------------------------------------------------------------------


def cmd_serve(args):
    import http.server
    import urllib.parse

    secret = args.secret or os.environ.get("MEDIWISE_FILE_SECRET") or os.urandom(32).hex()
    ensure_db()

    class FileHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)

            # Only handle /file/<attachment_id>
            parts = parsed.path.strip("/").split("/")
            if len(parts) != 2 or parts[0] != "file":
                self.send_error(404, "Not Found")
                return

            attachment_id = parts[1]
            exp_list = qs.get("exp")
            sig_list = qs.get("sig")

            if not exp_list or not sig_list:
                self.send_error(403, "Forbidden")
                return

            try:
                exp = int(exp_list[0])
            except (ValueError, IndexError):
                self.send_error(403, "Forbidden")
                return

            sig = sig_list[0]

            # Verify expiration
            if time.time() > exp:
                self.send_error(403, "Link expired")
                return

            # Verify signature
            expected = _make_signature(secret, attachment_id, exp)
            if not hmac.compare_digest(sig, expected):
                self.send_error(403, "Forbidden")
                return

            # Look up attachment
            with transaction() as conn:
                row = conn.execute(
                    "SELECT * FROM attachments WHERE id=? AND is_deleted=0",
                    (attachment_id,),
                ).fetchone()

            if not row:
                self.send_error(404, "Attachment not found")
                return

            att = row_to_dict(row)
            abs_p = _abs_path(att["file_path"])
            if not os.path.isfile(abs_p):
                self.send_error(404, "File not found on disk")
                return

            mime = att.get("mime_type", "application/octet-stream")
            filename = att.get("original_filename", "file")

            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header(
                "Content-Disposition",
                f'inline; filename="{filename}"',
            )
            file_size = os.path.getsize(abs_p)
            self.send_header("Content-Length", str(file_size))
            self.end_headers()

            with open(abs_p, "rb") as f:
                shutil.copyfileobj(f, self.wfile)

        def log_message(self, format, *log_args):
            # Suppress default stderr logging
            pass

    server = http.server.HTTPServer((args.host, args.port), FileHandler)
    startup = json.dumps({
        "status": "ok",
        "message": "文件服务已启动",
        "port": args.port,
        "secret": secret,
    }, ensure_ascii=False)
    print(startup, flush=True)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


# ---------------------------------------------------------------------------
# get-url sub-command
# ---------------------------------------------------------------------------


def cmd_get_url(args):
    secret = _get_secret(args)
    if not secret:
        return

    ensure_db()
    with transaction() as conn:
        row = conn.execute(
            "SELECT id FROM attachments WHERE id=? AND is_deleted=0",
            (args.id,),
        ).fetchone()
        if not row:
            output_json({"status": "error", "message": f"未找到附件: {args.id}"})
            return
        if not verify_record_ownership(conn, "attachments", args.id, getattr(args, "owner_id", None)):
            output_json({"status": "error", "message": f"无权访问附件: {args.id}"})
            return

    exp = int(time.time()) + args.expires
    sig = _make_signature(secret, args.id, exp)
    url = f"http://{args.host}:{args.port}/file/{args.id}?exp={exp}&sig={sig}"
    expires_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(exp))

    output_json({
        "status": "ok",
        "url": url,
        "expires_at": expires_at,
        "attachment_id": args.id,
    })


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="附件管理")
    sub = parser.add_subparsers(dest="command")

    # add
    p_add = sub.add_parser("add", help="添加附件")
    p_add.add_argument("--member-id", required=True)
    p_add.add_argument("--source-path", required=True, help="源文件路径")
    p_add.add_argument("--category", required=True, choices=VALID_CATEGORIES)
    p_add.add_argument("--description", default=None)
    p_add.add_argument("--move", action="store_true", help="移动文件而非复制")
    p_add.add_argument("--link-record-type", default=None, choices=VALID_RECORD_TYPES)
    p_add.add_argument("--link-record-id", default=None)
    p_add.add_argument("--owner-id", default=None)

    # list
    p_list = sub.add_parser("list", help="列出附件")
    p_list.add_argument("--member-id", required=True)
    p_list.add_argument("--category", default=None, choices=VALID_CATEGORIES)
    p_list.add_argument("--record-type", default=None, choices=VALID_RECORD_TYPES)
    p_list.add_argument("--record-id", default=None)
    p_list.add_argument("--limit", type=int, default=50)
    p_list.add_argument("--owner-id", default=None)

    # get
    p_get = sub.add_parser("get", help="查看附件详情")
    p_get.add_argument("--id", required=True)
    p_get.add_argument("--base64", action="store_true", help="返回文件 base64 编码内容")
    p_get.add_argument("--owner-id", default=None)

    # delete
    p_del = sub.add_parser("delete", help="删除附件")
    p_del.add_argument("--id", required=True)
    p_del.add_argument("--purge", action="store_true", help="同时删除磁盘文件")
    p_del.add_argument("--owner-id", default=None)

    # link
    p_link = sub.add_parser("link", help="关联附件到记录")
    p_link.add_argument("--attachment-id", required=True)
    p_link.add_argument("--record-type", required=True, choices=VALID_RECORD_TYPES)
    p_link.add_argument("--record-id", required=True)
    p_link.add_argument("--owner-id", default=None)

    # unlink
    p_unlink = sub.add_parser("unlink", help="取消关联")
    p_unlink.add_argument("--attachment-id", required=True)
    p_unlink.add_argument("--record-type", required=True, choices=VALID_RECORD_TYPES)
    p_unlink.add_argument("--record-id", required=True)
    p_unlink.add_argument("--owner-id", default=None)

    # serve
    p_serve = sub.add_parser("serve", help="启动签名 URL 文件服务")
    p_serve.add_argument("--port", type=int, default=9120)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--secret", default=None, help="HMAC 签名密钥")

    # get-url
    p_get_url = sub.add_parser("get-url", help="生成签名临时链接")
    p_get_url.add_argument("--id", required=True)
    p_get_url.add_argument("--expires", type=int, default=3600, help="链接有效期秒数")
    p_get_url.add_argument("--host", default="localhost")
    p_get_url.add_argument("--port", type=int, default=9120)
    p_get_url.add_argument("--secret", default=None, help="HMAC 签名密钥")
    p_get_url.add_argument("--owner-id", default=None)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {
        "add": cmd_add,
        "list": cmd_list,
        "get": cmd_get,
        "delete": cmd_delete,
        "link": cmd_link,
        "unlink": cmd_unlink,
        "serve": cmd_serve,
        "get-url": cmd_get_url,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
