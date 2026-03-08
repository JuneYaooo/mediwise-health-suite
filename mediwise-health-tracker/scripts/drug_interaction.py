"""Drug interaction query via DDInter database for MediWise Health Tracker.

Uses urllib.request (no extra dependencies) to query the DDInter drug-drug
interaction database (https://ddinter.scbdd.com).
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import os
import urllib.request
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.dirname(__file__))
from health_db import ensure_db, get_connection, rows_to_list, output_json, is_api_mode
import api_client


# ---------------------------------------------------------------------------
# DDInter API helpers
# ---------------------------------------------------------------------------

# DDInter SSL certificate is expired; create an unverified context.
_SSL_CTX = ssl._create_unverified_context()
_TIMEOUT = 10  # seconds


def _ddinter_get(path: str) -> dict | list | None:
    """GET request to DDInter.  Returns parsed JSON or None on failure."""
    url = "https://ddinter.scbdd.com" + path
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL_CTX) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return None
            return json.loads(body)
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError,
            TimeoutError, OSError):
        return None


# ---------------------------------------------------------------------------
# Chinese -> English drug name dictionary (~150 common drugs)
# ---------------------------------------------------------------------------

# Suffixes to strip before dictionary lookup
_DOSAGE_FORM_SUFFIXES = re.compile(
    r"(片|胶囊|缓释片|控释片|缓释胶囊|肠溶片|滴丸|颗粒|口服液|注射液|分散片|咀嚼片|泡腾片|软胶囊|滴眼液|喷雾剂|贴剂|凝胶|乳膏|软膏)$"
)

DRUG_NAME_DICT: dict[str, str] = {
    # --- 降压药 Antihypertensives ---
    "氨氯地平": "amlodipine",
    "硝苯地平": "nifedipine",
    "非洛地平": "felodipine",
    "拉西地平": "lacidipine",
    "贝尼地平": "benidipine",
    "尼莫地平": "nimodipine",
    "缬沙坦": "valsartan",
    "厄贝沙坦": "irbesartan",
    "氯沙坦": "losartan",
    "坎地沙坦": "candesartan",
    "替米沙坦": "telmisartan",
    "奥美沙坦": "olmesartan",
    "依那普利": "enalapril",
    "卡托普利": "captopril",
    "赖诺普利": "lisinopril",
    "贝那普利": "benazepril",
    "培哚普利": "perindopril",
    "雷米普利": "ramipril",
    "福辛普利": "fosinopril",
    "美托洛尔": "metoprolol",
    "比索洛尔": "bisoprolol",
    "阿替洛尔": "atenolol",
    "普萘洛尔": "propranolol",
    "卡维地洛": "carvedilol",
    "拉贝洛尔": "labetalol",
    "奈必洛尔": "nebivolol",
    "氢氯噻嗪": "hydrochlorothiazide",
    "吲达帕胺": "indapamide",
    "呋塞米": "furosemide",
    "螺内酯": "spironolactone",
    "托拉塞米": "torasemide",
    "特拉唑嗪": "terazosin",
    "多沙唑嗪": "doxazosin",

    # --- 降糖药 Antidiabetics ---
    "二甲双胍": "metformin",
    "格列本脲": "glibenclamide",
    "格列美脲": "glimepiride",
    "格列齐特": "gliclazide",
    "格列吡嗪": "glipizide",
    "瑞格列奈": "repaglinide",
    "那格列奈": "nateglinide",
    "阿卡波糖": "acarbose",
    "伏格列波糖": "voglibose",
    "吡格列酮": "pioglitazone",
    "罗格列酮": "rosiglitazone",
    "西格列汀": "sitagliptin",
    "维格列汀": "vildagliptin",
    "沙格列汀": "saxagliptin",
    "利格列汀": "linagliptin",
    "达格列净": "dapagliflozin",
    "恩格列净": "empagliflozin",
    "卡格列净": "canagliflozin",
    "利拉鲁肽": "liraglutide",
    "司美格鲁肽": "semaglutide",
    "度拉糖肽": "dulaglutide",
    "艾塞那肽": "exenatide",
    "胰岛素": "insulin",

    # --- 降脂药 Lipid-lowering ---
    "阿托伐他汀": "atorvastatin",
    "瑞舒伐他汀": "rosuvastatin",
    "辛伐他汀": "simvastatin",
    "普伐他汀": "pravastatin",
    "氟伐他汀": "fluvastatin",
    "匹伐他汀": "pitavastatin",
    "洛伐他汀": "lovastatin",
    "依折麦布": "ezetimibe",
    "非诺贝特": "fenofibrate",
    "吉非贝齐": "gemfibrozil",
    "烟酸": "niacin",

    # --- 抗凝/抗血小板 Anticoagulants/Antiplatelets ---
    "阿司匹林": "aspirin",
    "氯吡格雷": "clopidogrel",
    "替格瑞洛": "ticagrelor",
    "华法林": "warfarin",
    "利伐沙班": "rivaroxaban",
    "达比加群": "dabigatran",
    "阿哌沙班": "apixaban",
    "依度沙班": "edoxaban",
    "双嘧达莫": "dipyridamole",

    # --- 抗生素 Antibiotics ---
    "阿莫西林": "amoxicillin",
    "头孢氨苄": "cefalexin",
    "头孢克洛": "cefaclor",
    "头孢呋辛": "cefuroxime",
    "头孢地尼": "cefdinir",
    "头孢克肟": "cefixime",
    "头孢曲松": "ceftriaxone",
    "头孢他啶": "ceftazidime",
    "阿奇霉素": "azithromycin",
    "红霉素": "erythromycin",
    "克拉霉素": "clarithromycin",
    "罗红霉素": "roxithromycin",
    "左氧氟沙星": "levofloxacin",
    "莫西沙星": "moxifloxacin",
    "环丙沙星": "ciprofloxacin",
    "诺氟沙星": "norfloxacin",
    "甲硝唑": "metronidazole",
    "多西环素": "doxycycline",
    "米诺环素": "minocycline",
    "利奈唑胺": "linezolid",
    "万古霉素": "vancomycin",
    "克林霉素": "clindamycin",
    "复方磺胺甲噁唑": "sulfamethoxazole",

    # --- 解热镇痛 / NSAIDs ---
    "布洛芬": "ibuprofen",
    "对乙酰氨基酚": "acetaminophen",
    "双氯芬酸": "diclofenac",
    "萘普生": "naproxen",
    "吲哚美辛": "indomethacin",
    "美洛昔康": "meloxicam",
    "塞来昔布": "celecoxib",
    "依托考昔": "etoricoxib",
    "洛索洛芬": "loxoprofen",

    # --- 消化系统 Gastrointestinal ---
    "奥美拉唑": "omeprazole",
    "兰索拉唑": "lansoprazole",
    "泮托拉唑": "pantoprazole",
    "雷贝拉唑": "rabeprazole",
    "艾司奥美拉唑": "esomeprazole",
    "雷尼替丁": "ranitidine",
    "法莫替丁": "famotidine",
    "多潘立酮": "domperidone",
    "莫沙必利": "mosapride",
    "蒙脱石散": "smectite",
    "枸橼酸铋钾": "bismuth",
    "乳果糖": "lactulose",

    # --- 呼吸系统 Respiratory ---
    "沙丁胺醇": "salbutamol",
    "布地奈德": "budesonide",
    "孟鲁司特": "montelukast",
    "茶碱": "theophylline",
    "异丙托溴铵": "ipratropium",
    "噻托溴铵": "tiotropium",
    "氨溴索": "ambroxol",
    "右美沙芬": "dextromethorphan",
    "福莫特罗": "formoterol",
    "沙美特罗": "salmeterol",

    # --- 抗过敏 Antihistamines ---
    "氯雷他定": "loratadine",
    "西替利嗪": "cetirizine",
    "非索非那定": "fexofenadine",
    "依巴斯汀": "ebastine",
    "苯海拉明": "diphenhydramine",

    # --- 精神/神经 CNS ---
    "艾司西酞普兰": "escitalopram",
    "舍曲林": "sertraline",
    "氟西汀": "fluoxetine",
    "帕罗西汀": "paroxetine",
    "文拉法辛": "venlafaxine",
    "度洛西汀": "duloxetine",
    "米氮平": "mirtazapine",
    "阿米替林": "amitriptyline",
    "丙戊酸钠": "valproic acid",
    "卡马西平": "carbamazepine",
    "奥卡西平": "oxcarbazepine",
    "拉莫三嗪": "lamotrigine",
    "苯妥英钠": "phenytoin",
    "加巴喷丁": "gabapentin",
    "普瑞巴林": "pregabalin",
    "左乙拉西坦": "levetiracetam",
    "地西泮": "diazepam",
    "阿普唑仑": "alprazolam",
    "劳拉西泮": "lorazepam",
    "佐匹克隆": "zopiclone",
    "唑吡坦": "zolpidem",
    "氯氮平": "clozapine",
    "奥氮平": "olanzapine",
    "利培酮": "risperidone",
    "喹硫平": "quetiapine",
    "阿立哌唑": "aripiprazole",
    "多奈哌齐": "donepezil",
    "美金刚": "memantine",

    # --- 甲状腺 Thyroid ---
    "左甲状腺素": "levothyroxine",
    "甲巯咪唑": "methimazole",
    "丙硫氧嘧啶": "propylthiouracil",

    # --- 骨质疏松 Osteoporosis ---
    "阿仑膦酸钠": "alendronate",
    "唑来膦酸": "zoledronic acid",
    "碳酸钙": "calcium carbonate",

    # --- 其他常用 Other common ---
    "别嘌醇": "allopurinol",
    "非布司他": "febuxostat",
    "秋水仙碱": "colchicine",
    "甲氨蝶呤": "methotrexate",
    "羟氯喹": "hydroxychloroquine",
    "环孢素": "cyclosporine",
    "他克莫司": "tacrolimus",
    "泼尼松": "prednisone",
    "地塞米松": "dexamethasone",
    "甲泼尼龙": "methylprednisolone",
    "西地那非": "sildenafil",
    "他达拉非": "tadalafil",
    "坦索罗辛": "tamsulosin",
    "非那雄胺": "finasteride",
}


def _strip_dosage_form(name: str) -> str:
    """Remove common dosage-form suffixes from a Chinese drug name."""
    return _DOSAGE_FORM_SUFFIXES.sub("", name.strip())


def _translate_drug_name(name: str) -> tuple[str, str | None]:
    """Translate a Chinese drug name to English using the built-in dictionary.

    Returns (english_name, chinese_name).  If the name is already English or not
    found in the dictionary, returns (original_name, None).
    """
    cleaned = _strip_dosage_form(name)
    # Direct lookup
    if cleaned in DRUG_NAME_DICT:
        return DRUG_NAME_DICT[cleaned], cleaned
    # Try original (without stripping)
    if name.strip() in DRUG_NAME_DICT:
        return DRUG_NAME_DICT[name.strip()], name.strip()
    # Not Chinese or not in dictionary – assume already English
    return name.strip(), None


# ---------------------------------------------------------------------------
# DDInter search & interaction lookup
# ---------------------------------------------------------------------------

def _search_ddinter(query: str) -> list[dict]:
    """Search DDInter for a drug name.  Returns list of {id, name}."""
    encoded = urllib.parse.quote(query, safe="")
    raw = _ddinter_get(f"/check-datasource/{encoded}/")
    if not raw:
        return []
    # Response may be {"data": [...]} or a bare list
    items = raw
    if isinstance(raw, dict):
        items = raw.get("data", [])
    if not isinstance(items, list):
        return []
    results = []
    for item in items:
        if not isinstance(item, dict):
            continue
        drug_id = item.get("internalID") or item.get("id")
        drug_name = item.get("name") or item.get("Drug_Name")
        if drug_id and drug_name:
            results.append({"id": drug_id, "name": drug_name})
    return results


def _resolve_drug(name: str) -> tuple[str, str | None, list[dict]]:
    """Resolve a drug name to DDInter search results.

    Returns (english_name, chinese_name, ddinter_results).
    """
    en_name, cn_name = _translate_drug_name(name)
    results = _search_ddinter(en_name)
    # If no results with translated name, try original
    if not results and cn_name:
        results = _search_ddinter(name.strip())
    return en_name, cn_name, results


def _get_interactions(ddinter_id: str) -> list[dict]:
    """Get all interactions for a drug from DDInter grapher endpoint.

    Returns list of dicts with keys: id (target drug ID), name, level (list), actions (list).
    """
    data = _ddinter_get(f"/ddinter/grapher-datasource/{ddinter_id}/")
    if not data or not isinstance(data, dict):
        return []
    # Response format: {"info": {...}, "interactions": [{id, name, level, actions}, ...]}
    interactions = data.get("interactions", [])
    if not isinstance(interactions, list):
        return []
    return interactions


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_search(args):
    """Search DDInter for a drug by name."""
    name = args.name.strip()
    en_name, cn_name, results = _resolve_drug(name)
    display = f"{cn_name} ({en_name})" if cn_name else en_name
    if not results:
        output_json({
            "status": "ok",
            "drug": display,
            "found": False,
            "message": f"在 DDInter 数据库中未找到 '{display}'",
            "results": [],
        })
        return
    output_json({
        "status": "ok",
        "drug": display,
        "found": True,
        "count": len(results),
        "results": results,
    })


def cmd_check(args):
    """Check interactions between a new drug and a member's active medications."""
    member_id = args.member_id
    drug_name = args.drug_name.strip()

    # 1. Get member's active medications
    active_meds = _get_active_medications(member_id)
    if active_meds is None:
        output_json({"status": "error", "message": f"未找到成员: {member_id}"})
        return

    if not active_meds:
        en_name, cn_name, _ = _resolve_drug(drug_name)
        display = f"{cn_name} ({en_name})" if cn_name else en_name
        output_json({
            "status": "ok",
            "drug": display,
            "member_active_medications": [],
            "interactions_found": 0,
            "interactions": [],
            "no_interaction": [],
            "not_found_in_db": [],
            "message": "该成员目前没有在用药物，无需检查交互",
            "reference": _reference(),
        })
        return

    # 2. Resolve new drug
    new_en, new_cn, new_results = _resolve_drug(drug_name)
    new_display = f"{new_cn} ({new_en})" if new_cn else new_en

    if not new_results:
        output_json({
            "status": "ok",
            "drug": new_display,
            "member_active_medications": [m["name"] for m in active_meds],
            "interactions_found": 0,
            "interactions": [],
            "no_interaction": [],
            "not_found_in_db": [new_display],
            "message": f"新药 '{new_display}' 未在 DDInter 数据库中找到，无法自动检查交互，建议咨询药师",
            "reference": _reference(),
        })
        return

    new_drug_id = new_results[0]["id"]

    # 3. Get all interactions for the new drug
    interactions_data = _get_interactions(new_drug_id)

    # Build a map: target drug DDInter ID -> interaction info
    interaction_map: dict[str, dict] = {}
    for item in interactions_data:
        target_id = item.get("id")
        if target_id:
            interaction_map[target_id] = item

    # 4. Resolve each active medication and check intersection
    interactions = []
    no_interaction = []
    not_found = []

    for med in active_meds:
        med_name = med["name"]
        med_en, med_cn, med_results = _resolve_drug(med_name)
        med_display = f"{med_cn} ({med_en})" if med_cn else med_en

        if not med_results:
            not_found.append(med_display)
            continue

        med_drug_id = med_results[0]["id"]
        matched = interaction_map.get(med_drug_id)

        if matched:
            level_raw = matched.get("level", [])
            level = level_raw[0] if isinstance(level_raw, list) and level_raw else str(level_raw)
            actions = matched.get("actions", [])
            interaction_entry = {
                "drug_a": new_results[0].get("name", new_en),
                "drug_b": med_results[0].get("name", med_en),
                "drug_b_chinese": med_cn or med_name,
                "level": level,
                "actions": actions,
            }
            interactions.append(interaction_entry)
        else:
            no_interaction.append(med_display)

    # Sort: Major first, then Moderate, then Minor
    level_order = {"Major": 0, "Moderate": 1, "Minor": 2}
    interactions.sort(key=lambda x: level_order.get(x.get("level", ""), 3))

    output_json({
        "status": "ok",
        "drug": new_display,
        "member_active_medications": [m["name"] for m in active_meds],
        "interactions_found": len(interactions),
        "interactions": interactions,
        "no_interaction": no_interaction,
        "not_found_in_db": not_found,
        "reference": _reference(),
    })


def cmd_check_pair(args):
    """Check interaction between two specified drugs."""
    drug_a_name = args.drug_a.strip()
    drug_b_name = args.drug_b.strip()

    # Resolve both drugs
    a_en, a_cn, a_results = _resolve_drug(drug_a_name)
    b_en, b_cn, b_results = _resolve_drug(drug_b_name)
    a_display = f"{a_cn} ({a_en})" if a_cn else a_en
    b_display = f"{b_cn} ({b_en})" if b_cn else b_en

    not_found = []
    if not a_results:
        not_found.append(a_display)
    if not b_results:
        not_found.append(b_display)

    if not_found:
        output_json({
            "status": "ok",
            "drug_a": a_display,
            "drug_b": b_display,
            "interaction_found": False,
            "not_found_in_db": not_found,
            "message": f"以下药物未在 DDInter 数据库中找到: {', '.join(not_found)}，无法自动检查交互，建议咨询药师",
            "reference": _reference(),
        })
        return

    a_id = a_results[0]["id"]
    b_id = b_results[0]["id"]

    # Get interactions for drug A and check if drug B is in the list
    interactions_data = _get_interactions(a_id)
    matched = None
    for item in interactions_data:
        if item.get("id") == b_id:
            matched = item
            break

    if not matched:
        output_json({
            "status": "ok",
            "drug_a": a_display,
            "drug_b": b_display,
            "interaction_found": False,
            "message": f"未发现 {a_display} 与 {b_display} 之间的已知交互",
            "reference": _reference(),
        })
        return

    level_raw = matched.get("level", [])
    level = level_raw[0] if isinstance(level_raw, list) and level_raw else str(level_raw)
    actions = matched.get("actions", [])
    interaction = {
        "drug_a": a_results[0].get("name", a_en),
        "drug_b": b_results[0].get("name", b_en),
        "drug_a_chinese": a_cn or drug_a_name,
        "drug_b_chinese": b_cn or drug_b_name,
        "level": level,
        "actions": actions,
    }

    output_json({
        "status": "ok",
        "drug_a": a_display,
        "drug_b": b_display,
        "interaction_found": True,
        "interaction": interaction,
        "reference": _reference(),
    })


def cmd_lookup(args):
    """Look up a single drug's interaction overview in DDInter."""
    name = args.name.strip()
    en_name, cn_name, results = _resolve_drug(name)
    display = f"{cn_name} ({en_name})" if cn_name else en_name

    if not results:
        output_json({
            "status": "ok",
            "drug": display,
            "found": False,
            "message": f"在 DDInter 数据库中未找到 '{display}'",
            "reference": _reference(),
        })
        return

    drug_id = results[0]["id"]
    interactions_data = _get_interactions(drug_id)

    # Count by level
    level_counts: dict[str, int] = {}
    for item in interactions_data:
        level_raw = item.get("level", [])
        lvl = level_raw[0] if isinstance(level_raw, list) and level_raw else str(level_raw)
        level_counts[lvl] = level_counts.get(lvl, 0) + 1

    output_json({
        "status": "ok",
        "drug": display,
        "ddinter_id": drug_id,
        "found": True,
        "total_interactions": len(interactions_data),
        "by_level": level_counts,
        "reference": _reference(),
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_active_medications(member_id: str) -> list[dict] | None:
    """Fetch active medications for a member.  Returns None if member not found."""
    if is_api_mode():
        try:
            result = api_client.get_active_medications(member_id)
            if isinstance(result, dict):
                return result.get("medications", [])
            return result if isinstance(result, list) else []
        except api_client.APIError:
            return None

    ensure_db()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM members WHERE id=? AND is_deleted=0", (member_id,)
        ).fetchone()
        if not row:
            return None
        rows = conn.execute(
            "SELECT name, dosage, frequency FROM medications "
            "WHERE member_id=? AND is_active=1 AND is_deleted=0",
            (member_id,),
        ).fetchall()
        return rows_to_list(rows)
    finally:
        conn.close()


def _reference() -> dict:
    return {
        "source": "DDInter - Drug-Drug Interaction Database",
        "url": "https://ddinter.scbdd.com",
        "note": "数据仅供参考，不构成医疗建议，具体用药请咨询医生或药师",
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="药物交互查询 (DDInter)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("search", help="搜索药品")
    p.add_argument("--name", required=True, help="药品名称（中文或英文）")

    p = sub.add_parser("check", help="检查新药与成员在用药物的交互")
    p.add_argument("--member-id", required=True, help="成员 ID")
    p.add_argument("--drug-name", required=True, help="新药名称")

    p = sub.add_parser("check-pair", help="检查两个药物之间的交互")
    p.add_argument("--drug-a", required=True, help="药品 A 名称")
    p.add_argument("--drug-b", required=True, help="药品 B 名称")

    p = sub.add_parser("lookup", help="查询单个药品的交互概览")
    p.add_argument("--name", required=True, help="药品名称（中文或英文）")

    args = parser.parse_args()
    commands = {
        "search": cmd_search,
        "check": cmd_check,
        "check-pair": cmd_check_pair,
        "lookup": cmd_lookup,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
