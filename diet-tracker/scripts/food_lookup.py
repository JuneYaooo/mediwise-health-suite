"""食物营养查询 - 三层数据源：

优先级：
  1. CFCD6（离线，优先）
     数据来源：《中国食物成分表标准版第6版》（中国疾病预防控制中心营养与健康所）
     JSON 格式整理：https://github.com/Sanotsu/china-food-composition-data
     收录 1657 条中国食材，覆盖谷物、蔬菜、水果、肉蛋奶、水产等全品类

  2. cn-brands（离线，外食场景兜底）
     数据来源：https://github.com/H1an1/health-coach（references/cn-brands.md）
     来源注明：产品包装标注、品牌官方信息、薄荷健康等平台
     收录 339 条，覆盖奶茶、外卖、便利店、火锅、烧烤、早餐等

  3. USDA FoodData Central（在线，国际食材兜底）
     数据来源：美国农业部 https://fdc.nal.usda.gov/
     免费 API，需在环境变量 USDA_API_KEY 配置注册密钥
     注册地址：https://api.data.gov/signup/

用法:
  python food_lookup.py search --query 鸡胸肉
  python food_lookup.py search --query tofu --source usda
  python food_lookup.py search --query 宫保鸡丁 --limit 3
  python food_lookup.py stats
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request

# ── 路径 ───────────────────────────────────────────────────────────────────
_SCRIPT_DIR = os.path.dirname(__file__)
_DATA_DIR   = os.path.join(_SCRIPT_DIR, '..', 'data')
_CFCD_PATH  = os.path.join(_DATA_DIR, 'cfcd6.json')
_BRANDS_PATH = os.path.join(
    _SCRIPT_DIR, '..', '..', '..',
    'mediwise-health-suite',   # 兼容独立部署
    'diet-tracker', 'data', 'cn_brands.json',
)
# 同目录下也看一眼
_BRANDS_PATH2 = os.path.join(_DATA_DIR, 'cn_brands.json')

# ── USDA API ────────────────────────────────────────────────────────────────
USDA_SEARCH_URL = 'https://api.nal.usda.gov/fdc/v1/foods/search'
# 支持的 dataType：Foundation 和 SR Legacy 提供每 100g 数据
USDA_DATA_TYPES = 'Foundation,SR%20Legacy,Survey%20(FNDDS)'

# ── 营养素 ID（USDA） ────────────────────────────────────────────────────────
_USDA_NUTRIENT_IDS = {
    1008: 'kcal',
    1003: 'protein',
    1004: 'fat',
    1005: 'carbs',
    1079: 'fiber',
    1253: 'cholesterol',
    1087: 'Ca',
    1089: 'Fe',
    1162: 'vitC',
}

# ── 内部缓存 ────────────────────────────────────────────────────────────────
_cfcd_cache: list[dict] | None = None
_brands_cache: list[dict] | None = None


# ══════════════════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════════════════

def _load_cfcd() -> list[dict]:
    global _cfcd_cache
    if _cfcd_cache is None:
        if not os.path.exists(_CFCD_PATH):
            _cfcd_cache = []
        else:
            with open(_CFCD_PATH, encoding='utf-8') as f:
                _cfcd_cache = json.load(f)
    return _cfcd_cache


def _load_brands() -> list[dict]:
    """尝试加载 cn_brands.json（由 parse_brands.py 生成）。"""
    global _brands_cache
    if _brands_cache is not None:
        return _brands_cache
    for path in (_BRANDS_PATH2, _BRANDS_PATH):
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                _brands_cache = json.load(f)
            return _brands_cache
    _brands_cache = []
    return _brands_cache


# ══════════════════════════════════════════════════════════════════════════════
# 搜索工具
# ══════════════════════════════════════════════════════════════════════════════

def _normalize(text: str) -> str:
    """转小写、去空格，用于模糊匹配。"""
    return unicodedata.normalize('NFKC', text).lower().replace(' ', '')


def _score(query: str, food: dict) -> int:
    """返回匹配分数（越高越好，0 = 不匹配）。"""
    q  = _normalize(query)
    name = _normalize(food.get('name', ''))
    brand = _normalize(food.get('brand', ''))
    aliases = [_normalize(a) for a in food.get('aliases', [])]
    all_names = [name] + aliases

    # 完全匹配名称
    if q in all_names:
        return 100
    # 名称以查询开头
    if any(n.startswith(q) for n in all_names):
        return 80
    # 名称包含查询
    if any(q in n for n in all_names):
        return 60
    # 查询包含在名称中
    if any(n in q for n in all_names if len(n) >= 2):
        return 40
    # 品牌名匹配（返回该品牌的所有产品）
    if brand and (q in brand or brand in q):
        return 30
    # 中文字符部分重叠匹配（≥2字公共前缀，处理"鸡胸肉"↔"鸡胸脯肉"等变体）
    if len(q) >= 2:
        for n in all_names:
            prefix_len = 0
            for a, b in zip(q, n):
                if a == b:
                    prefix_len += 1
                else:
                    break
            if prefix_len >= 2:
                return 20
    return 0


def _search_local(query: str, foods: list[dict], limit: int = 5) -> list[dict]:
    scored = [(f, _score(query, f)) for f in foods]
    scored = [(f, s) for f, s in scored if s > 0]
    scored.sort(key=lambda x: -x[1])
    return [f for f, _ in scored[:limit]]


# ══════════════════════════════════════════════════════════════════════════════
# CFCD 查询
# ══════════════════════════════════════════════════════════════════════════════

def search_cfcd(query: str, limit: int = 5) -> list[dict]:
    """在《中国食物成分表第6版》中搜索。返回标准化结果列表。"""
    foods = _load_cfcd()
    hits = _search_local(query, foods, limit)
    return [_fmt_cfcd(h) for h in hits]


def _fmt_cfcd(item: dict) -> dict:
    return {
        'name':        item.get('name', ''),
        'name_en':     item.get('name_en'),
        'category':    item.get('category', ''),
        'subcategory': item.get('subcategory', ''),
        'per':         '100g',
        'edible_pct':  item.get('edible_pct'),
        'kcal':        item.get('kcal'),
        'protein':     item.get('protein'),
        'fat':         item.get('fat'),
        'carbs':       item.get('carbs'),
        'fiber':       item.get('fiber'),
        'water':       item.get('water'),
        'cholesterol': item.get('cholesterol'),
        'Ca':          item.get('Ca'),
        'Fe':          item.get('Fe'),
        'vitC':        item.get('vitC'),
        'source':      'cfcd6',
        'source_name': '中国食物成分表第6版（中国疾控中心）',
        'source_url':  'https://github.com/Sanotsu/china-food-composition-data',
    }


# ══════════════════════════════════════════════════════════════════════════════
# cn-brands 查询
# ══════════════════════════════════════════════════════════════════════════════

def search_brands(query: str, limit: int = 5) -> list[dict]:
    """在中国外食/品牌食品库中搜索。"""
    foods = _load_brands()
    hits = _search_local(query, foods, limit)
    return [_fmt_brand(h) for h in hits]


def _fmt_brand(item: dict) -> dict:
    return {
        'name':        item.get('name', ''),
        'brand':       item.get('brand', ''),
        'category':    item.get('category', ''),
        'per':         item.get('per', '份'),
        'serving_desc': item.get('serving_desc', ''),
        'kcal':        item.get('kcal'),
        'protein':     item.get('protein'),
        'fat':         item.get('fat'),
        'carbs':       item.get('carbs'),
        'fiber':       item.get('fiber'),
        'note':        item.get('note', ''),
        'source':      'cn_brands',
        'source_name': '中国品牌/外食数据库（H1an1/health-coach）',
        'source_url':  'https://github.com/H1an1/health-coach',
    }


# ══════════════════════════════════════════════════════════════════════════════
# USDA FoodData Central 查询
# ══════════════════════════════════════════════════════════════════════════════

def _get_usda_key() -> str | None:
    """从环境变量或 config 文件读取 USDA API key。"""
    key = os.environ.get('USDA_API_KEY', '').strip()
    if key:
        return key
    # 尝试读取项目 config
    try:
        sys.path.insert(0, _SCRIPT_DIR)
        import config as _cfg
        return getattr(_cfg, 'USDA_API_KEY', None) or None
    except Exception:
        return None


def search_usda(query: str, limit: int = 5) -> list[dict]:
    """从 USDA FoodData Central 查询。需要 USDA_API_KEY 环境变量。"""
    key = _get_usda_key()
    if not key:
        return [{'error': '未配置 USDA_API_KEY，请在环境变量或 config.py 中设置'}]

    encoded = urllib.parse.quote(query)
    url = (
        f'{USDA_SEARCH_URL}'
        f'?query={encoded}'
        f'&api_key={key}'
        f'&pageSize={limit}'
        f'&dataType={USDA_DATA_TYPES}'
    )
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'mediwise-health/1.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return [{'error': f'USDA API 请求失败: {e}'}]

    results = []
    for food in data.get('foods', [])[:limit]:
        nutrients = {n['nutrientId']: n['value'] for n in food.get('foodNutrients', [])}
        results.append({
            'name':        food.get('description', ''),
            'name_en':     food.get('description', ''),
            'category':    food.get('foodCategory', ''),
            'brand':       food.get('brandOwner', ''),
            'per':         '100g',
            'kcal':        nutrients.get(1008),
            'protein':     nutrients.get(1003),
            'fat':         nutrients.get(1004),
            'carbs':       nutrients.get(1005),
            'fiber':       nutrients.get(1079),
            'cholesterol': nutrients.get(1253),
            'Ca':          nutrients.get(1087),
            'Fe':          nutrients.get(1089),
            'vitC':        nutrients.get(1162),
            'fdc_id':      food.get('fdcId'),
            'data_type':   food.get('dataType'),
            'source':      'usda',
            'source_name': 'USDA FoodData Central（美国农业部）',
            'source_url':  'https://fdc.nal.usda.gov/',
        })
    return results


# ══════════════════════════════════════════════════════════════════════════════
# 统一入口：三层查询
# ══════════════════════════════════════════════════════════════════════════════

def search(
    query: str,
    limit: int = 5,
    source: str = 'auto',
    include_brands: bool = True,
) -> dict:
    """
    统一食物查询接口。

    source:
      'auto'   — 按优先级：CFCD → cn-brands → USDA
      'cfcd'   — 仅查《中国食物成分表》
      'brands' — 仅查外食/品牌库
      'usda'   — 仅查 USDA
      'all'    — 所有来源合并返回
    """
    query = query.strip()
    if not query:
        return {'status': 'error', 'message': '查询词不能为空'}

    if source == 'cfcd':
        return {'status': 'ok', 'query': query, 'results': search_cfcd(query, limit), 'source': 'cfcd'}

    if source == 'brands':
        return {'status': 'ok', 'query': query, 'results': search_brands(query, limit), 'source': 'brands'}

    if source == 'usda':
        return {'status': 'ok', 'query': query, 'results': search_usda(query, limit), 'source': 'usda'}

    if source == 'all':
        cfcd_r   = search_cfcd(query, limit)
        brand_r  = search_brands(query, limit) if include_brands else []
        usda_r   = search_usda(query, limit)
        return {
            'status': 'ok',
            'query': query,
            'cfcd_results': cfcd_r,
            'brand_results': brand_r,
            'usda_results': usda_r,
        }

    # auto 模式：CFCD 优先，未命中再查 brands，再查 USDA
    cfcd_r = search_cfcd(query, limit)
    if cfcd_r:
        return {'status': 'ok', 'query': query, 'results': cfcd_r, 'source': 'cfcd'}

    if include_brands:
        brand_r = search_brands(query, limit)
        if brand_r:
            return {'status': 'ok', 'query': query, 'results': brand_r, 'source': 'cn_brands'}

    usda_r = search_usda(query, limit)
    if usda_r and 'error' not in usda_r[0]:
        return {'status': 'ok', 'query': query, 'results': usda_r, 'source': 'usda'}

    return {
        'status': 'not_found',
        'query': query,
        'message': f'未找到"{query}"的营养数据，建议手动输入或换个关键词',
        'results': [],
    }


def get_by_name(name: str) -> dict | None:
    """精确匹配食物名称，返回单条结果（用于饮食录入自动填充）。"""
    # CFCD 精确匹配
    for food in _load_cfcd():
        if food.get('name') == name:
            return _fmt_cfcd(food)
    # brands 精确匹配
    for food in _load_brands():
        if food.get('name') == name:
            return _fmt_brand(food)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 数据库概况
# ══════════════════════════════════════════════════════════════════════════════

def db_stats() -> dict:
    cfcd = _load_cfcd()
    brands = _load_brands()
    categories: dict[str, int] = {}
    for f in cfcd:
        cat = f.get('category', '其他')
        categories[cat] = categories.get(cat, 0) + 1
    return {
        'cfcd_total': len(cfcd),
        'cfcd_with_kcal': sum(1 for f in cfcd if f.get('kcal') is not None),
        'cfcd_source': '《中国食物成分表标准版第6版》中国疾病预防控制中心营养与健康所',
        'cfcd_json_repo': 'https://github.com/Sanotsu/china-food-composition-data',
        'brands_total': len(brands),
        'brands_source': '中国品牌/外食数据（产品包装、品牌官方信息、薄荷健康等）',
        'brands_repo': 'https://github.com/H1an1/health-coach',
        'usda_source': 'USDA FoodData Central https://fdc.nal.usda.gov/',
        'usda_available': bool(_get_usda_key()),
        'cfcd_categories': categories,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def _output(data: dict) -> None:
    # 尝试导入项目通用输出函数，否则直接 print
    try:
        sys.path.insert(0, _SCRIPT_DIR)
        from health_db import output_json
        output_json(data)
    except Exception:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description='食物营养查询')
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('search', help='搜索食物')
    p.add_argument('--query', '-q', required=True, help='食物名称（中文或英文）')
    p.add_argument('--limit', type=int, default=5)
    p.add_argument('--source', default='auto',
                   choices=['auto', 'cfcd', 'brands', 'usda', 'all'],
                   help='数据来源（默认 auto 按优先级查询）')
    p.add_argument('--no-brands', action='store_true', help='跳过品牌/外食数据库')
    p.add_argument('--owner-id', default=None)  # accepted but unused (multi-tenant injection)

    stats_p = sub.add_parser('stats', help='查看数据库概况')
    stats_p.add_argument('--owner-id', default=None)

    args = parser.parse_args()

    if args.command == 'search':
        result = search(
            args.query,
            limit=args.limit,
            source=args.source,
            include_brands=not args.no_brands,
        )
        _output(result)

    elif args.command == 'stats':
        _output(db_stats())


if __name__ == '__main__':
    main()
