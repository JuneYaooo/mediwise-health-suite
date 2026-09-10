"""Generate local evidence cards for meaningful health-goal moments.

The card is rendered from the milestone's frozen evidence snapshot. It never
re-reads later progress to rewrite an earlier achievement, and it does not issue
collectible cards for ordinary check-ins or arbitrary percentage increments.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import random
import tempfile
from pathlib import Path
from typing import Mapping, Optional

import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
from path_setup import setup_mediwise_path

setup_mediwise_path()

from config import DATA_DIR
from goal_engine import _member, evaluate_goal, get_goal, list_milestones
from health_db import generate_id, get_lifestyle_connection, now_iso, output_json, rows_to_list, transaction
from card_capture import capture_card_png


WIDTH = 1080
HEIGHT = 1440
CARDABLE_TYPES = ("rhythm", "consistency", "recovery", "halfway", "completion")
STYLES = {
    "timeline": {"name": "行动时间轴", "weight": 1.15, "moments": ("rhythm",)},
    "calendar": {"name": "周期日历", "weight": 1.0, "moments": ("rhythm", "consistency")},
    "ledger": {"name": "周期账本", "weight": 1.1, "moments": ("consistency",)},
    "repair": {"name": "重新接上线", "weight": 1.15, "moments": ("recovery",)},
    "route": {"name": "阶段路线", "weight": 1.05, "moments": ("halfway", "completion")},
    "archive": {"name": "完成存档", "weight": 1.15, "moments": ("completion",)},
    "letter": {"name": "给自己的便笺", "weight": 0.9, "moments": ("recovery", "completion")},
}
TONES = ("gentle", "calm", "playful", "editorial")
DENSITIES = ("concise", "standard", "detailed")
PREF_PATH = Path(DATA_DIR) / "goal-card-preferences.json"
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def _member_key(member_id: object) -> str:
    return hashlib.sha256(str(member_id or "anonymous").encode("utf-8")).hexdigest()


def _default_pref() -> dict:
    return {
        "tone": "calm",
        "density": "standard",
        "preferred_styles": [],
        "disliked_styles": [],
        "recent_styles": [],
        "generation_count": 0,
    }


def _read_prefs() -> dict:
    try:
        value = json.loads(PREF_PATH.read_text(encoding="utf-8"))
        if isinstance(value, dict) and isinstance(value.get("members"), dict):
            return value
    except (OSError, ValueError):
        pass
    return {"version": 2, "members": {}}


def get_preferences(member_id: object) -> dict:
    pref = _default_pref()
    saved = _read_prefs()["members"].get(_member_key(member_id), {})
    if isinstance(saved, dict):
        pref.update({key: value for key, value in saved.items() if key in pref})
    pref["preferred_styles"] = [item for item in pref["preferred_styles"] if item in STYLES]
    pref["disliked_styles"] = [item for item in pref["disliked_styles"] if item in STYLES]
    pref["recent_styles"] = [item for item in pref["recent_styles"] if item in STYLES][-6:]
    if pref["tone"] not in TONES:
        pref["tone"] = "calm"
    if pref["density"] not in DENSITIES:
        pref["density"] = "standard"
    pref["generation_count"] = max(int(pref.get("generation_count") or 0), 0)
    return pref


def update_preferences(
    member_id: object, *, tone: Optional[str] = None, density: Optional[str] = None,
    like=None, dislike=None, neutral=None, generated_style: Optional[str] = None,
) -> dict:
    if tone is not None and tone not in TONES:
        raise ValueError("不支持的语气")
    if density is not None and density not in DENSITIES:
        raise ValueError("不支持的信息密度")
    choices = list(like or []) + list(dislike or []) + list(neutral or [])
    if generated_style:
        choices.append(generated_style)
    unknown = [item for item in choices if item not in STYLES]
    if unknown:
        raise ValueError("未知卡面：%s" % "、".join(sorted(set(unknown))))
    store = _read_prefs()
    pref = get_preferences(member_id)
    if tone is not None:
        pref["tone"] = tone
    if density is not None:
        pref["density"] = density
    preferred = set(pref["preferred_styles"])
    disliked = set(pref["disliked_styles"])
    for item in like or []:
        preferred.add(item)
        disliked.discard(item)
    for item in dislike or []:
        disliked.add(item)
        preferred.discard(item)
    for item in neutral or []:
        preferred.discard(item)
        disliked.discard(item)
    pref["preferred_styles"] = sorted(preferred)
    pref["disliked_styles"] = sorted(disliked)
    if generated_style:
        pref["recent_styles"] = (pref["recent_styles"] + [generated_style])[-6:]
        pref["generation_count"] += 1
    store["version"] = 2
    store.setdefault("members", {})[_member_key(member_id)] = pref
    PREF_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(PREF_PATH.parent), delete=False)
    try:
        json.dump(store, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.chmod(handle.name, 0o600)
        os.replace(handle.name, PREF_PATH)
        os.chmod(PREF_PATH, 0o600)
    except Exception:
        handle.close()
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise
    return pref


def _evidence(milestone: Mapping[str, object]) -> dict:
    value = milestone.get("evidence") or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = {}
    return dict(value) if isinstance(value, Mapping) else {}


def _select_style(
    milestone: Mapping[str, object], pref: Mapping[str, object], seed: str, explicit: Optional[str]
) -> dict:
    kind = str(milestone.get("milestone_type") or "")
    compatible = [key for key, spec in STYLES.items() if kind in spec["moments"]]
    if not compatible:
        raise ValueError("这个旧里程碑没有可用的证据卡版式")
    if explicit:
        if explicit not in STYLES:
            raise ValueError("未知卡面：%s" % explicit)
        if explicit not in compatible:
            raise ValueError("%s 不能准确表达当前阶段；可选：%s" % (
                STYLES[explicit]["name"], "、".join(compatible)
            ))
        selected = explicit
        probabilities = {key: (1.0 if key == explicit else 0.0) for key in compatible}
    else:
        recent = list(pref.get("recent_styles") or [])
        weights = {}
        for style_id in compatible:
            weight = float(STYLES[style_id]["weight"])
            if style_id in pref.get("preferred_styles", []):
                weight *= 1.7
            if style_id in pref.get("disliked_styles", []):
                weight *= 0.08
            if recent and style_id == recent[-1]:
                weight *= 0.35
            weights[style_id] = max(weight, 0.000001)
        total = sum(weights.values())
        probabilities = {key: value / total for key, value in weights.items()}
        rng = random.Random(int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16], 16))
        cursor = rng.random()
        selected = compatible[-1]
        cumulative = 0.0
        for style_id in sorted(compatible):
            cumulative += probabilities.get(style_id, 0.0)
            if cursor <= cumulative:
                selected = style_id
                break
    digest = hashlib.sha256((selected + "|" + seed).encode("utf-8")).hexdigest()
    return {
        "style_id": selected,
        "style_name": STYLES[selected]["name"],
        "compatible_styles": compatible,
        "probabilities": {key: round(value, 6) for key, value in probabilities.items()},
        "composition_variant": int(digest[:2], 16) % 3,
        "reproducible": True,
        "selection_rule": "meaning-first",
    }


def _fmt(value: object) -> str:
    try:
        number = float(value)
        return str(int(number)) if number.is_integer() else ("%.1f" % number).rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value or 0)


def _copy(milestone: Mapping[str, object]) -> dict:
    kind = str(milestone.get("milestone_type") or "")
    evidence = _evidence(milestone)
    unit = str(evidence.get("unit") or "")
    checkins = int(evidence.get("checkin_count") or 0)
    if kind == "rhythm":
        action_days = evidence.get("action_days") or []
        weekday_text = "、".join(
            WEEKDAYS[int(item.get("weekday") or 0) % 7]
            for item in action_days
        )
        gaps = evidence.get("spacing_days") or []
        gap_text = "、".join("%s 天" % _fmt(value) for value in gaps)
        detail = "行动分布在%s" % weekday_text if weekday_text else "多次行动已经分布到不同日期"
        if gap_text:
            detail += "，相邻间隔为%s" % gap_text
        return {
            "label": "节奏建立",
            "title": "你找到了第一套可重复的节奏",
            "hero": "%s 次" % _fmt(len(action_days) or checkins),
            "detail": detail + "。",
            "reason": "首次用真实记录完整完成一个目标周期。" if evidence.get("period_start") else "至少三次行动分布在多个日期，已经出现可见节奏。",
            "next": "下一个阶段先按原目标继续记录，不自动加量。",
        }
    if kind == "consistency":
        streak = int(evidence.get("streak") or 0)
        return {
            "label": "稳定发生",
            "title": "这已经不是偶然的一周",
            "hero": "%s 个周期" % _fmt(streak),
            "detail": "你连续 %s 个周期达到了自己确认的目标。" % _fmt(streak),
            "reason": "连续完成的周期彼此相邻，不是零散累计。",
            "next": "继续按原目标记录；不需要为了升级卡片而增加负担。",
        }
    if kind == "recovery":
        gap = int(evidence.get("gap_days") or 0)
        return {
            "label": "重新接上",
            "title": "你把中断接回了行动",
            "hero": "%s 天之后" % _fmt(gap),
            "detail": "相隔 %s 天后，新的行动再次被记录。" % _fmt(gap),
            "reason": "这张卡记录的是回来，不评价中间的空白。",
            "next": "从这次记录继续，不需要补写过去。",
        }
    if kind == "halfway":
        value = evidence.get("overall_value")
        target = evidence.get("overall_target")
        remaining = max(float(target or 0) - float(value or 0), 0.0)
        return {
            "label": "走过一半",
            "title": "这段目标已经越过中点",
            "hero": "%s / %s" % (_fmt(value), _fmt(target)),
            "detail": "已经完成目标总量的一半，仍有 %s %s 留在后半程。" % (_fmt(remaining), unit),
            "reason": "目标规模足够形成前后两段，且进度首次越过 50%。",
            "next": "下一次行动仍按原目标记录，后半程不自动加码。",
        }
    if kind == "completion":
        value = evidence.get("overall_value")
        target = evidence.get("overall_target")
        if evidence.get("total_periods"):
            hero = "%s / %s 周期" % (_fmt(value), _fmt(target))
        else:
            hero = "%s / %s %s" % (_fmt(value), _fmt(target), unit)
        return {
            "label": "目标完成",
            "title": "这个目标有了完整结尾",
            "hero": hero,
            "detail": "从第一条记录到最后一个完成节点，证据已经闭合。",
            "reason": "用户确认的整体目标已由已记录行动完成。",
            "next": "是否开始下一段目标由你决定；当前记录不会被改写。",
        }
    raise ValueError("这个里程碑不再生成收藏卡")


def _action_timeline(evidence: Mapping[str, object], show_exact_date: bool) -> str:
    actions = list(evidence.get("action_days") or [])
    nodes = []
    for index, item in enumerate(actions):
        weekday = WEEKDAYS[int(item.get("weekday") or 0) % 7]
        date_text = str(item.get("date") or "") if show_exact_date else "第 %d 次" % (index + 1)
        nodes.append(
            '<div class="action-node"><span class="dot"></span><b>%s</b><small>%s</small></div>'
            % (html.escape(weekday), html.escape(date_text))
        )
    return '<div class="action-timeline">%s</div>' % "".join(nodes)


def _period_grid(evidence: Mapping[str, object], complete: bool = False) -> str:
    total = int(evidence.get("total_periods") or evidence.get("overall_target") or 0)
    done = int(evidence.get("completed_periods") or evidence.get("overall_value") or 0)
    total = min(max(total, done, 1), 24)
    cells = []
    for index in range(total):
        state = "done" if index < done or complete else "pending"
        cells.append('<div class="period-cell %s"><span>%02d</span><b>%s</b></div>' % (
            state, index + 1, "已完成" if state == "done" else "待记录"
        ))
    return '<div class="period-grid">%s</div>' % "".join(cells)


def _meaning_visual(kind: str, evidence: Mapping[str, object], show_exact_date: bool) -> str:
    if kind == "rhythm":
        return _action_timeline(evidence, show_exact_date)
    if kind == "consistency":
        return _period_grid(evidence)
    if kind == "recovery":
        before = str(evidence.get("previous_action_date") or "") if show_exact_date else "上一次记录"
        after = str(evidence.get("return_action_date") or "") if show_exact_date else "本次记录"
        return '''<div class="recovery-line"><div><span class="dot"></span><b>%s</b></div>
        <div class="gap"><i></i><strong>%s 天</strong><i></i></div>
        <div><span class="dot current"></span><b>%s</b></div></div>''' % (
            html.escape(before), _fmt(evidence.get("gap_days")), html.escape(after)
        )
    if kind == "halfway":
        percent = int(round(float(evidence.get("overall_ratio") or 0) * 100))
        return '''<div class="route-line"><span class="start">开始</span><i><b style="width:%s%%"></b></i>
        <span class="current">%s%%</span><span class="end">完成</span></div>''' % (percent, percent)
    return _period_grid(evidence, complete=True)


def _render_html(
    goal: Mapping[str, object], milestone: Mapping[str, object], selection: Mapping[str, object],
    tone: str, density: str, show_member_name: bool, show_exact_date: bool, member_name: str,
) -> str:
    kind = str(milestone.get("milestone_type") or "")
    evidence = _evidence(milestone)
    copy = _copy(milestone)
    palette = {
        "rhythm": ("#23362f", "#f3efe5", "#cf6542", "#e5dcc9"),
        "consistency": ("#21352b", "#edf1e8", "#4f7b5e", "#d7e1d5"),
        "recovery": ("#3d2d28", "#f4ece5", "#b85d40", "#e7d4c9"),
        "halfway": ("#203447", "#eaf0f3", "#42708c", "#cfdee5"),
        "completion": ("#352f20", "#f1ead7", "#9b7428", "#dfd1a8"),
    }[kind]
    ink, paper, accent, muted = palette
    member = " · " + html.escape(member_name) if show_member_name and member_name else ""
    exact_date = html.escape(str(milestone.get("achieved_at") or "")[:10]) if show_exact_date else "阶段证据"
    visual = _meaning_visual(kind, evidence, show_exact_date)
    goal_title = html.escape(str(evidence.get("goal_title") or goal.get("title") or ""))
    why = html.escape(copy["reason"])
    next_step = html.escape(copy["next"])
    detail = html.escape(copy["detail"])
    if density == "concise":
        detail = ""
    detail_html = '<p class="detail">%s</p>' % detail if detail else ""
    exact_class = "shows-exact-date" if show_exact_date else "hides-exact-date"
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MediWise 目标证据卡</title><style>
*{{box-sizing:border-box}}html,body{{margin:0;width:100%;height:100%;background:#c9cec9}}body{{display:grid;place-items:center;color:{ink};font-family:"Avenir Next","Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;font-synthesis:none;line-break:strict}}
.card{{position:relative;width:{WIDTH}px;height:{HEIGHT}px;overflow:hidden;background:{paper};padding:72px 74px 62px;display:grid;grid-template-rows:auto auto auto 1fr auto auto;gap:0}}
.card:before{{content:"";position:absolute;right:-90px;top:-70px;width:270px;height:270px;border:1px solid {accent};border-radius:50%;opacity:.32}}.card:after{{content:"";position:absolute;right:38px;top:62px;width:13px;height:13px;background:{accent};border-radius:50%}}
.top{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid {ink};padding-bottom:22px;font-size:18px;letter-spacing:.08em}}.top strong{{font-size:21px}}.top span{{opacity:.7}}
.intro{{padding-top:68px;display:grid;grid-template-columns:1fr 210px;gap:44px;align-items:start}}.label{{color:{accent};font-size:22px;font-weight:760;letter-spacing:.16em}}h1{{font-family:"Noto Serif SC","Songti SC","STSong",serif;font-size:66px;line-height:1.22;letter-spacing:-.015em;text-wrap:balance;margin:22px 0 0;max-width:720px}}.hero{{font-variant-numeric:tabular-nums;text-align:right;font-size:30px;line-height:1.25;font-weight:800;color:{accent};padding-top:4px}}
.detail{{margin:28px 0 0;font-size:25px;line-height:1.72;max-width:800px;text-wrap:pretty;opacity:.78}}
.visual{{margin-top:54px;align-self:start}}.action-timeline{{position:relative;display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:0;padding-top:26px}}.action-timeline:before{{content:"";position:absolute;left:8%;right:8%;top:37px;height:2px;background:{ink};opacity:.28}}.action-node{{position:relative;text-align:center;display:grid;justify-items:center;gap:12px}}.action-node .dot{{z-index:1;width:24px;height:24px;border-radius:50%;background:{paper};border:7px solid {accent}}}.action-node b{{font-size:25px}}.action-node small{{font-size:17px;opacity:.62}}
.calendar .action-node .dot{{border-radius:4px;transform:rotate(45deg)}}.period-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}.period-cell{{min-height:104px;border-top:4px solid {muted};padding:16px 8px 8px}}.period-cell span{{font-size:18px;opacity:.62;font-variant-numeric:tabular-nums}}.period-cell b{{display:block;margin-top:14px;font-size:19px}}.period-cell.done{{border-color:{accent}}}.period-cell.pending{{opacity:.42}}
.recovery-line{{display:grid;grid-template-columns:190px 1fr 190px;align-items:center;gap:12px;margin-top:30px}}.recovery-line>div:not(.gap){{display:grid;justify-items:center;gap:16px;font-size:19px}}.recovery-line .dot{{width:26px;height:26px;border-radius:50%;border:6px solid {ink};background:{paper}}}.recovery-line .dot.current{{border-color:{accent};background:{accent}}}.gap{{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:14px;color:{accent}}}.gap i{{height:2px;background:repeating-linear-gradient(90deg,{accent} 0 8px,transparent 8px 15px)}}.gap strong{{font-size:30px;font-variant-numeric:tabular-nums}}
.route-line{{position:relative;display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:18px;margin-top:64px;font-size:18px}}.route-line i{{height:12px;background:{muted};position:relative}}.route-line i b{{display:block;height:100%;background:{accent}}}.route-line .current{{position:absolute;left:50%;top:-62px;transform:translateX(-50%);font-size:42px;font-weight:850;color:{accent}}}.route-line .end{{grid-column:3}}.route-line .start{{grid-column:1}}
.meaning{{display:grid;grid-template-columns:1fr 1fr;border-top:1px solid {ink};border-bottom:1px solid {ink};margin-top:44px}}.meaning section{{padding:25px 30px 28px 0;min-height:150px}}.meaning section+section{{border-left:1px solid {ink};padding-left:30px}}.meaning small{{display:block;color:{accent};font-size:16px;letter-spacing:.15em;font-weight:760}}.meaning p{{font-size:22px;line-height:1.58;margin:14px 0 0;text-wrap:pretty}}
.goal{{display:flex;justify-content:space-between;align-items:flex-end;padding-top:26px;gap:36px}}.goal div{{max-width:700px}}.goal small{{display:block;font-size:15px;letter-spacing:.14em;color:{accent};font-weight:760}}.goal b{{display:block;margin-top:10px;font-size:23px;line-height:1.4}}.goal>span{{font-size:16px;opacity:.56;text-align:right}}.letter h1{{font-size:60px}}.tone-gentle{{filter:saturate(.88)}}.tone-playful .label{{text-decoration:underline;text-decoration-thickness:4px;text-underline-offset:8px}}.tone-editorial h1{{font-family:"Noto Sans SC","PingFang SC",sans-serif;font-weight:820}}
.detailed .meaning p{{font-size:23px}}.concise .intro{{padding-top:84px}}.concise .visual{{margin-top:72px}}
</style></head><body><main class="card {selection['style_id']} {density} tone-{tone} {exact_class}" data-share-safe="{'false' if show_member_name or show_exact_date else 'true'}" data-milestone-type="{kind}" data-style-id="{selection['style_id']}" data-snapshot-version="{html.escape(str(evidence.get('schema_version') or 1))}" data-snapshot-checkins="{html.escape(str(evidence.get('checkin_count') or 0))}"><header class="top"><strong>MediWise · 目标证据卡{member}</strong><span>{exact_date}</span></header><section class="intro"><div><div class="label">{html.escape(copy['label'])}</div><h1>{html.escape(copy['title'])}</h1>{detail_html}</div><div class="hero">{html.escape(copy['hero'])}</div></section><section class="visual">{visual}</section><div></div><section class="meaning"><section><small>WHY · 为什么获得</small><p>{why}</p></section><section><small>NEXT · 下一步</small><p>{next_step}</p></section></section><footer class="goal"><div><small>USER-SET GOAL · 用户设定目标</small><b>{goal_title}</b></div><span>本地证据快照<br>默认隐藏姓名与精确日期</span></footer></main><script>window.__ready=true</script></body></html>'''


def _load_milestone(
    goal_id: str, milestone_id: Optional[str], owner_id: Optional[str], allow_claimed: bool
) -> tuple:
    listed = list_milestones(goal_id, owner_id, unclaimed_only=False)
    if listed.get("status") != "ok":
        return None, None, listed
    all_milestones = listed["milestones"]
    if milestone_id:
        selected = next((item for item in all_milestones if item["id"] == milestone_id), None)
        if not selected:
            return listed["goal"], None, {"status": "error", "message": "未找到指定阶段"}
        if selected.get("milestone_type") not in CARDABLE_TYPES:
            return listed["goal"], None, {"status": "error", "message": "这个旧节点只是进度记录，不再生成收藏卡"}
        if selected.get("claimed_at") and not allow_claimed:
            return listed["goal"], None, {"status": "error", "message": "这张阶段卡已经领取；如需重绘请传 redraw=true"}
        return listed["goal"], selected, None
    eligible = [
        item for item in all_milestones
        if item.get("milestone_type") in CARDABLE_TYPES
        and (allow_claimed or not item.get("claimed_at"))
    ]
    if not eligible:
        return listed["goal"], None, {
            "status": "error",
            "message": "目前没有值得发卡的新阶段；普通打卡和普通周期完成只保留轻反馈",
        }
    return listed["goal"], eligible[0], None


def generate_card(args) -> dict:
    goal = get_goal(args.goal_id, args.owner_id)
    if not goal:
        return {"status": "error", "message": "未找到目标或无权访问"}
    evaluated = evaluate_goal(goal["id"], owner_id=args.owner_id)
    goal, milestone, error = _load_milestone(
        args.goal_id, args.milestone_id, args.owner_id, args.redraw
    )
    if error:
        return error
    pref = get_preferences(goal["member_id"])
    tone = args.tone or pref["tone"]
    density = args.density or pref["density"]
    seed = args.seed or hashlib.sha256(
        (goal["id"] + "|" + milestone["id"] + "|" + str(pref["generation_count"])).encode("utf-8")
    ).hexdigest()[:20]
    selection = _select_style(milestone, pref, seed, args.style)
    member_name = ""
    if args.show_member_name:
        member = _member(goal["member_id"], args.owner_id)
        member_name = (member or {}).get("name", "")
    card_html = _render_html(
        goal, milestone, selection, tone, density,
        args.show_member_name, args.show_exact_date, member_name,
    )
    output_dir = Path(args.output_dir or (Path(DATA_DIR) / "reports" / "goal-cards")).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    card_id = generate_id()
    kind = milestone["milestone_type"]
    stem = "goal_evidence_%s_%s_%s" % (goal["id"], kind, selection["style_id"])
    html_path = output_dir / (stem + ".html")
    png_path = output_dir / (stem + ".png")
    html_path.write_text(card_html, encoding="utf-8")
    try:
        os.chmod(html_path, 0o600)
    except OSError:
        pass
    render = {"status": "not_requested"}
    actual_png = None
    if args.format in ("png", "both"):
        render = capture_card_png(str(html_path), str(png_path), width=WIDTH, height=HEIGHT)
        if render.get("status") == "ok":
            actual_png = str(png_path)
    with transaction(domain="lifestyle") as conn:
        conn.execute(
            """INSERT INTO goal_cards
               (id,goal_id,milestone_id,member_id,style_id,tone,density,seed,html_path,png_path,created_at,is_deleted)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,0)""",
            (card_id, goal["id"], milestone["id"], goal["member_id"], selection["style_id"], tone, density, seed, str(html_path), actual_png, now_iso()),
        )
        conn.execute(
            "UPDATE goal_milestones SET claimed_at=COALESCE(claimed_at,?),card_id=? WHERE id=?",
            (now_iso(), card_id, milestone["id"]),
        )
        conn.commit()
    update_preferences(goal["member_id"], generated_style=selection["style_id"])
    copy = _copy(milestone)
    evidence = _evidence(milestone)
    return {
        "status": "ok",
        "message": "目标证据卡已在本地生成",
        "goal": goal,
        "milestone": milestone,
        "current_progress": evaluated["progress"],
        "selection": selection,
        "card": {
            "id": card_id,
            "product_name": "MediWise 目标证据卡",
            "meaning": milestone["milestone_type"],
            "why_earned": copy["reason"],
            "next_step": copy["next"],
            "snapshot_frozen": int(evidence.get("schema_version") or 1) >= 2,
            "snapshot_checkin_count": evidence.get("checkin_count"),
            "html_path": str(html_path),
            "png_path": actual_png,
            "render": render,
            "width": WIDTH,
            "height": HEIGHT,
            "share_safe": not (args.show_member_name or args.show_exact_date),
            "contains_goal_details": True,
        },
    }


def list_cards(args) -> dict:
    goal = get_goal(args.goal_id, args.owner_id)
    if not goal:
        return {"status": "error", "message": "未找到目标或无权访问"}
    conn = get_lifestyle_connection()
    try:
        cards = rows_to_list(conn.execute(
            "SELECT * FROM goal_cards WHERE goal_id=? AND is_deleted=0 ORDER BY created_at DESC",
            (args.goal_id,),
        ).fetchall())
    finally:
        conn.close()
    return {"status": "ok", "goal": goal, "cards": cards, "count": len(cards)}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MediWise 目标证据卡")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--goal-id", required=True)
    generate.add_argument("--milestone-id")
    generate.add_argument("--style", choices=sorted(STYLES))
    generate.add_argument("--tone", choices=TONES)
    generate.add_argument("--density", choices=DENSITIES)
    generate.add_argument("--seed")
    generate.add_argument("--format", choices=("html", "png", "both"), default="png")
    generate.add_argument("--output-dir")
    generate.add_argument("--redraw", action="store_true")
    generate.add_argument("--show-member-name", action="store_true")
    generate.add_argument("--show-exact-date", action="store_true")
    generate.add_argument("--owner-id")
    listing = sub.add_parser("list")
    listing.add_argument("--goal-id", required=True)
    listing.add_argument("--owner-id")
    get_pref = sub.add_parser("preferences-get")
    get_pref.add_argument("--member-id", required=True)
    get_pref.add_argument("--owner-id")
    update_pref = sub.add_parser("preferences-update")
    update_pref.add_argument("--member-id", required=True)
    update_pref.add_argument("--tone", choices=TONES)
    update_pref.add_argument("--density", choices=DENSITIES)
    update_pref.add_argument("--like-style", action="append", default=[])
    update_pref.add_argument("--dislike-style", action="append", default=[])
    update_pref.add_argument("--neutral-style", action="append", default=[])
    update_pref.add_argument("--owner-id")
    return parser


def main() -> None:
    args = _parser().parse_args()
    try:
        if args.command == "generate":
            result = generate_card(args)
        elif args.command == "list":
            result = list_cards(args)
        elif args.command == "preferences-get":
            if not _member(args.member_id, args.owner_id):
                result = {"status": "error", "message": "未找到成员或无权访问"}
            else:
                result = {
                    "status": "ok", "preferences": get_preferences(args.member_id),
                    "storage": {"local": True, "member_id_hashed": True, "health_values_stored": False},
                }
        else:
            if not _member(args.member_id, args.owner_id):
                result = {"status": "error", "message": "未找到成员或无权访问"}
            else:
                pref = update_preferences(
                    args.member_id, tone=args.tone, density=args.density,
                    like=args.like_style, dislike=args.dislike_style, neutral=args.neutral_style,
                )
                result = {"status": "ok", "preferences": pref}
    except (OSError, ValueError) as exc:
        result = {"status": "error", "message": str(exc)}
    output_json(result)


if __name__ == "__main__":
    main()
