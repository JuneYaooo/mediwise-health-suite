"""openFDA Drug Label Query - 查询美国 FDA 药品标签信息

通过 openFDA 免费 API 查询处方药的：
- 药物交互信息 (drug_interactions)
- 警告信息 (warnings)
- 禁忌症 (contraindications)
- 不良反应 (adverse_reactions)

API 免费，无需 key，限制 240 req/min。
注意：数据为英文，适合作为结构化数据源补充 DDInter。
"""
from __future__ import annotations

import sys
import json
import argparse
import urllib.request
import urllib.parse
import urllib.error


BASE_URL = "https://api.fda.gov/drug/label.json"


def _query_fda(search: str, limit: int = 3) -> dict:
    """Query openFDA API."""
    params = urllib.parse.urlencode({"search": search, "limit": limit})
    url = f"{BASE_URL}?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MediWise/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"error": "未找到相关药品信息", "status": 404}
        return {"error": f"API 请求失败: HTTP {e.code}", "status": e.code}
    except Exception as e:
        return {"error": f"请求失败: {str(e)}"}


def _extract_fields(result: dict) -> dict:
    """Extract relevant fields from a single FDA label result."""
    openfda = result.get("openfda", {})
    extracted = {
        "brand_name": openfda.get("brand_name", []),
        "generic_name": openfda.get("generic_name", []),
        "manufacturer": openfda.get("manufacturer_name", []),
        "route": openfda.get("route", []),
    }

    # Extract text fields (each is a list of strings)
    text_fields = [
        "drug_interactions", "warnings", "warnings_and_cautions",
        "contraindications", "adverse_reactions", "boxed_warning",
        "indications_and_usage", "dosage_and_administration",
        "pregnancy_or_breast_feeding", "do_not_use",
    ]
    for field in text_fields:
        val = result.get(field)
        if val:
            # Join list into single string, truncate if very long
            text = "\n".join(val) if isinstance(val, list) else str(val)
            if len(text) > 3000:
                text = text[:3000] + "...(truncated)"
            extracted[field] = text

    return extracted


def search_drug(drug_name: str, field: str = "generic_name") -> dict:
    """Search for a drug by name and return label info."""
    search = f'openfda.{field}:"{drug_name}"'
    data = _query_fda(search, limit=1)

    if "error" in data:
        return data

    results = data.get("results", [])
    if not results:
        return {"error": f"未找到药品: {drug_name}", "search_field": field}

    extracted = _extract_fields(results[0])
    extracted["source"] = "openFDA Drug Label API"
    extracted["note"] = "数据来自美国 FDA 药品标签，英文内容，仅供参考"
    return extracted


def search_interaction(drug_name: str) -> dict:
    """Search specifically for drug interaction info."""
    # Try generic name first
    search = f'openfda.generic_name:"{drug_name}"'
    data = _query_fda(search, limit=1)

    results = data.get("results", [])
    if not results:
        # Fallback to brand name
        search = f'openfda.brand_name:"{drug_name}"'
        data = _query_fda(search, limit=1)
        results = data.get("results", [])

    if not results:
        return {"error": f"未找到药品 {drug_name} 的交互信息"}

    result = results[0]
    openfda = result.get("openfda", {})

    output = {
        "drug": drug_name,
        "brand_name": openfda.get("brand_name", []),
        "generic_name": openfda.get("generic_name", []),
    }

    if "drug_interactions" in result:
        output["drug_interactions"] = "\n".join(result["drug_interactions"])
    else:
        output["drug_interactions"] = None
        output["note"] = "该药品标签中未包含单独的 drug_interactions 章节，交互信息可能在 warnings 中"

    if "warnings" in result:
        warnings_text = "\n".join(result["warnings"])
        if len(warnings_text) > 2000:
            warnings_text = warnings_text[:2000] + "...(truncated)"
        output["warnings"] = warnings_text
    elif "warnings_and_cautions" in result:
        wac_text = "\n".join(result["warnings_and_cautions"])
        if len(wac_text) > 2000:
            wac_text = wac_text[:2000] + "...(truncated)"
        output["warnings_and_cautions"] = wac_text

    if "contraindications" in result:
        output["contraindications"] = "\n".join(result["contraindications"])

    output["source"] = "openFDA Drug Label API"
    return output


def search_two_drugs(drug_a: str, drug_b: str) -> dict:
    """Search interaction info for drug A, check if drug B is mentioned."""
    result_a = search_interaction(drug_a)
    if "error" in result_a:
        return result_a

    interaction_text = result_a.get("drug_interactions", "") or ""
    warnings_text = result_a.get("warnings", "") or result_a.get("warnings_and_cautions", "") or ""
    all_text = (interaction_text + " " + warnings_text).lower()

    drug_b_lower = drug_b.lower()
    mentioned = drug_b_lower in all_text

    return {
        "drug_a": drug_a,
        "drug_b": drug_b,
        "drug_b_mentioned_in_label": mentioned,
        "drug_a_interactions": interaction_text[:2000] if interaction_text else None,
        "drug_a_warnings_excerpt": warnings_text[:1000] if warnings_text else None,
        "source": "openFDA Drug Label API",
        "note": f"在 {drug_a} 的 FDA 标签中{'找到' if mentioned else '未找到'}对 {drug_b} 的提及。建议结合 DDInter 和中文来源交叉验证。",
    }


def output_json(data: dict):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main():
    if len(sys.argv) < 2:
        output_json({
            "error": "用法: openfda_query.py <command> [args]",
            "commands": ["search", "interaction", "check-pair"],
        })
        return

    cmd = sys.argv[1]
    p = argparse.ArgumentParser()

    if cmd == "search":
        p.add_argument("--name", required=True, help="药品名称（英文通用名或品牌名）")
        p.add_argument("--field", default="generic_name", choices=["generic_name", "brand_name"])
        args = p.parse_args(sys.argv[2:])
        output_json(search_drug(args.name, args.field))

    elif cmd == "interaction":
        p.add_argument("--name", required=True, help="药品名称（英文）")
        args = p.parse_args(sys.argv[2:])
        output_json(search_interaction(args.name))

    elif cmd == "check-pair":
        p.add_argument("--drug-a", required=True, help="药品 A（英文）")
        p.add_argument("--drug-b", required=True, help="药品 B（英文）")
        args = p.parse_args(sys.argv[2:])
        output_json(search_two_drugs(args.drug_a, args.drug_b))

    else:
        output_json({"error": f"未知命令: {cmd}"})


if __name__ == "__main__":
    main()
