"""食物营养查询 - 按可用性选择本地数据包或官方在线 API：

优先级：
  1. CFCD6（可选本地数据包，优先）
     数据来源：《中国食物成分表标准版第6版》（中国疾病预防控制中心营养与健康所）
     JSON 格式整理：https://github.com/Sanotsu/china-food-composition-data
     因来源授权与再分发条件需由安装者确认，仓库不捆绑该数据文件

  2. cn-brands（可选本地数据包，外食场景兜底）
     数据来源：https://github.com/H1an1/health-coach（references/cn-brands.md）
     来源注明：产品包装标注、品牌官方信息、薄荷健康等平台
     仓库不捆绑该数据文件

  3. USDA FoodData Central（在线，国际食材兜底）
     数据来源：美国农业部 https://fdc.nal.usda.gov/
     免费 API，需在环境变量 USDA_API_KEY 配置注册密钥
     注册地址：https://api.data.gov/signup/

  4. Open Food Facts（在线，包装/品牌食品兜底）
     数据来源：https://world.openfoodfacts.org/
     需要显式设置 OPENFOODFACTS_ENABLED=1，不需要 API Key
     数据库采用 ODbL，查询结果会保留来源和许可证信息

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

# ── Open Food Facts / Search-a-licious ──────────────────────────────────────
OPENFOODFACTS_DEFAULT_SEARCH_URL = 'https://search.openfoodfacts.org/search'
OPENFOODFACTS_FIELDS = (
    'code,product_name,product_name_en,product_name_zh,brands,categories,'
    'nutriments,serving_size'
)
DEFAULT_USER_AGENT = (
    'MediWiseHealthSuite/2.0.9 '
    '(https://github.com/JuneYaooo/mediwise-health-suite)'
)

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


def _cfcd_installed() -> bool:
    return os.path.isfile(_CFCD_PATH)


def _brands_installed() -> bool:
    return any(os.path.isfile(path) for path in (_BRANDS_PATH2, _BRANDS_PATH))


def _env_true(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _online_allowed() -> bool:
    """A global explicit false disables every remote food provider."""
    value = os.environ.get('MEDIWISE_FOOD_ONLINE_ENABLED')
    if value is None:
        return True  # preserves USDA_API_KEY as an explicit opt-in
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def _openfoodfacts_enabled() -> bool:
    return _online_allowed() and _env_true('OPENFOODFACTS_ENABLED')


def _request_timeout() -> float:
    try:
        timeout = float(os.environ.get('MEDIWISE_FOOD_HTTP_TIMEOUT', '8'))
    except ValueError:
        timeout = 8.0
    return max(1.0, min(timeout, 30.0))


def _user_agent() -> str:
    value = os.environ.get('MEDIWISE_FOOD_USER_AGENT', DEFAULT_USER_AGENT).strip()
    if not value or '\n' in value or '\r' in value:
        return DEFAULT_USER_AGENT
    return value[:256]


def _openfoodfacts_search_url() -> str:
    """Return a validated official endpoint, or an explicitly allowed HTTPS URL."""
    value = os.environ.get(
        'OPENFOODFACTS_SEARCH_URL', OPENFOODFACTS_DEFAULT_SEARCH_URL
    ).strip()
    parsed = urllib.parse.urlsplit(value)
    host = (parsed.hostname or '').lower()
    official_host = host == 'openfoodfacts.org' or host.endswith('.openfoodfacts.org')
    custom_allowed = _env_true('MEDIWISE_ALLOW_CUSTOM_FOOD_SOURCE_URL')
    if parsed.scheme != 'https' or not host or (not official_host and not custom_allowed):
        raise ValueError(
            'OPENFOODFACTS_SEARCH_URL 必须是 Open Food Facts 官方 HTTPS 地址；'
            '自托管 HTTPS 端点需显式设置 MEDIWISE_ALLOW_CUSTOM_FOOD_SOURCE_URL=1'
        )
    return value


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
    if not _online_allowed():
        return [{'error': '在线食物数据源已由 MEDIWISE_FOOD_ONLINE_ENABLED=0 禁用'}]
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
        req = urllib.request.Request(url, headers={'User-Agent': _user_agent()})
        with urllib.request.urlopen(req, timeout=_request_timeout()) as resp:
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
# Open Food Facts 查询（Search-a-licious 官方全文搜索 API）
# ══════════════════════════════════════════════════════════════════════════════

def _grams_to_mg(value):
    if isinstance(value, (int, float)):
        return round(value * 1000, 6)
    return None


def search_openfoodfacts(query: str, limit: int = 5) -> list[dict]:
    """查询 Open Food Facts；只发送查询词和非敏感搜索参数。"""
    if not _openfoodfacts_enabled():
        return [{
            'error': 'Open Food Facts 未启用，请设置 OPENFOODFACTS_ENABLED=1'
        }]
    try:
        base_url = _openfoodfacts_search_url()
    except ValueError as error:
        return [{'error': str(error)}]

    page_size = max(1, min(int(limit), 20))
    params = urllib.parse.urlencode({
        'q': query,
        'langs': os.environ.get('OPENFOODFACTS_LANGS', 'zh,en')[:64],
        'page_size': page_size,
        'page': 1,
        'fields': OPENFOODFACTS_FIELDS,
    })
    separator = '&' if '?' in base_url else '?'
    request = urllib.request.Request(
        f'{base_url}{separator}{params}',
        headers={
            'User-Agent': _user_agent(),
            'Accept': 'application/json',
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_request_timeout()) as response:
            payload = json.loads(response.read())
    except Exception as error:
        return [{'error': f'Open Food Facts API 请求失败: {error}'}]

    hits = payload.get('hits', []) if isinstance(payload, dict) else []
    if not isinstance(hits, list):
        return [{'error': 'Open Food Facts API 返回格式无效'}]

    results = []
    for food in hits[:page_size]:
        if not isinstance(food, dict):
            continue
        nutrients = food.get('nutriments')
        if not isinstance(nutrients, dict):
            nutrients = {}
        brands = food.get('brands', '')
        if isinstance(brands, list):
            brands = ', '.join(str(item) for item in brands if item)
        code = str(food.get('code') or '').strip()
        product_url = (
            f'https://world.openfoodfacts.org/product/{urllib.parse.quote(code)}'
            if code else 'https://world.openfoodfacts.org/'
        )
        results.append({
            'name': (
                food.get('product_name_zh')
                or food.get('product_name')
                or food.get('product_name_en')
                or ''
            ),
            'name_en': food.get('product_name_en'),
            'category': food.get('categories', ''),
            'brand': brands,
            'per': '100g',
            'serving_desc': food.get('serving_size', ''),
            'kcal': nutrients.get('energy-kcal_100g'),
            'protein': nutrients.get('proteins_100g'),
            'fat': nutrients.get('fat_100g'),
            'carbs': nutrients.get('carbohydrates_100g'),
            'fiber': nutrients.get('fiber_100g'),
            'cholesterol': _grams_to_mg(nutrients.get('cholesterol_100g')),
            'Ca': _grams_to_mg(nutrients.get('calcium_100g')),
            'Fe': _grams_to_mg(nutrients.get('iron_100g')),
            'vitC': _grams_to_mg(nutrients.get('vitamin-c_100g')),
            'barcode': code or None,
            'source': 'openfoodfacts',
            'source_name': 'Open Food Facts',
            'source_url': product_url,
            'license': 'Open Database License (ODbL) 1.0',
            'license_url': 'https://opendatacommons.org/licenses/odbl/1-0/',
        })
    return results


# ══════════════════════════════════════════════════════════════════════════════
# 统一入口：多来源查询
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
      'auto'   — 按优先级：CFCD → cn-brands → USDA → Open Food Facts
      'cfcd'   — 仅查《中国食物成分表》
      'brands' — 仅查外食/品牌库
      'usda'   — 仅查 USDA
      'openfoodfacts' / 'off' — 仅查 Open Food Facts
      'all'    — 所有来源合并返回
    """
    query = query.strip()
    if not query:
        return {'status': 'error', 'message': '查询词不能为空'}
    if len(query) > 200:
        return {'status': 'error', 'message': '查询词不能超过 200 个字符'}
    limit = max(1, min(int(limit), 20))
    if source == 'off':
        source = 'openfoodfacts'

    if source == 'cfcd' and not _cfcd_installed():
        return {'status': 'unavailable', 'query': query, 'source': 'cfcd',
                'message': 'CFCD6 离线数据包未安装。请安装授权数据包，或显式启用在线来源。', 'results': []}
    if source == 'cfcd':
        return {'status': 'ok', 'query': query, 'results': search_cfcd(query, limit), 'source': 'cfcd'}

    if source == 'brands' and not _brands_installed():
        return {'status': 'unavailable', 'query': query, 'source': 'brands',
                'message': '中国品牌/外食离线数据包未安装。请安装授权数据包，或显式启用在线来源。', 'results': []}
    if source == 'brands':
        return {'status': 'ok', 'query': query, 'results': search_brands(query, limit), 'source': 'brands'}

    if source == 'usda':
        usda_r = search_usda(query, limit)
        if usda_r and 'error' in usda_r[0]:
            return {
                'status': 'unavailable' if not (_online_allowed() and _get_usda_key()) else 'error',
                'query': query,
                'source': 'usda',
                'message': usda_r[0]['error'],
                'results': [],
            }
        return {'status': 'ok', 'query': query, 'results': usda_r, 'source': 'usda'}

    if source == 'openfoodfacts':
        off_r = search_openfoodfacts(query, limit)
        if off_r and 'error' in off_r[0]:
            return {
                'status': 'unavailable' if not _openfoodfacts_enabled() else 'error',
                'query': query,
                'source': 'openfoodfacts',
                'message': off_r[0]['error'],
                'results': [],
            }
        return {
            'status': 'ok', 'query': query, 'results': off_r,
            'source': 'openfoodfacts',
        }

    if source == 'all':
        available = {
            'cfcd': _cfcd_installed(),
            'brands': include_brands and _brands_installed(),
            'usda': _online_allowed() and bool(_get_usda_key()),
            'openfoodfacts': _openfoodfacts_enabled(),
        }
        cfcd_r = search_cfcd(query, limit) if available['cfcd'] else []
        brand_r = search_brands(query, limit) if available['brands'] else []
        usda_raw = search_usda(query, limit) if available['usda'] else []
        off_raw = search_openfoodfacts(query, limit) if available['openfoodfacts'] else []
        warnings = []
        successful_sources = sum((available['cfcd'], available['brands']))
        if usda_raw and 'error' in usda_raw[0]:
            warnings.append(usda_raw[0]['error'])
            usda_r = []
        else:
            usda_r = usda_raw
            successful_sources += int(available['usda'])
        if off_raw and 'error' in off_raw[0]:
            warnings.append(off_raw[0]['error'])
            off_r = []
        else:
            off_r = off_raw
            successful_sources += int(available['openfoodfacts'])

        if not any(available.values()):
            status = 'unavailable'
            message = '当前没有可用的营养数据源，请安装本地数据包或显式启用在线来源。'
        elif warnings and not successful_sources:
            status = 'error'
            message = '已配置的在线营养数据源查询失败。'
        elif warnings:
            status = 'partial'
            message = '部分营养数据源查询失败，其余结果仍可使用。'
        else:
            status = 'ok'
            message = None
        result = {
            'status': status,
            'query': query,
            'cfcd_results': cfcd_r,
            'brand_results': brand_r,
            'usda_results': usda_r,
            'openfoodfacts_results': off_r,
            'available_sources': available,
        }
        if message:
            result['message'] = message
        if warnings:
            result['warnings'] = warnings
        return result

    if source != 'auto':
        return {'status': 'error', 'message': f'未知数据源: {source}', 'results': []}

    # auto 模式：本地优先，再查已明确启用的在线来源。
    cfcd_r = search_cfcd(query, limit)
    if cfcd_r:
        return {'status': 'ok', 'query': query, 'results': cfcd_r, 'source': 'cfcd'}

    if include_brands:
        brand_r = search_brands(query, limit)
        if brand_r:
            return {'status': 'ok', 'query': query, 'results': brand_r, 'source': 'cn_brands'}

    available_sources = []
    warnings = []
    if _cfcd_installed():
        available_sources.append('cfcd')
    if include_brands and _brands_installed():
        available_sources.append('brands')

    if _online_allowed() and _get_usda_key():
        available_sources.append('usda')
        usda_r = search_usda(query, limit)
        if usda_r and 'error' in usda_r[0]:
            warnings.append(usda_r[0]['error'])
        elif usda_r:
            result = {'status': 'ok', 'query': query, 'results': usda_r, 'source': 'usda'}
            if warnings:
                result['warnings'] = warnings
            return result

    if _openfoodfacts_enabled():
        available_sources.append('openfoodfacts')
        off_r = search_openfoodfacts(query, limit)
        if off_r and 'error' in off_r[0]:
            warnings.append(off_r[0]['error'])
        elif off_r:
            result = {
                'status': 'ok', 'query': query, 'results': off_r,
                'source': 'openfoodfacts',
            }
            if warnings:
                result['warnings'] = warnings
            return result

    if warnings and available_sources and all(
        item in {'usda', 'openfoodfacts'} for item in available_sources
    ):
        return {
            'status': 'error',
            'query': query,
            'message': '；'.join(warnings),
            'results': [],
        }
    return {
        'status': 'not_found' if available_sources else 'unavailable',
        'query': query,
        'message': (
            f'未找到"{query}"的营养数据，建议手动输入或换个关键词'
            if available_sources
            else '当前没有可用的营养数据源：离线数据包未安装，也未启用在线来源。'
        ),
        'results': [],
        **({'warnings': warnings} if warnings else {}),
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
        'usda_available': _online_allowed() and bool(_get_usda_key()),
        'openfoodfacts_source': 'Open Food Facts https://world.openfoodfacts.org/',
        'openfoodfacts_search_docs': 'https://search.openfoodfacts.org/docs',
        'openfoodfacts_license': 'Open Database License (ODbL) 1.0',
        'openfoodfacts_available': _openfoodfacts_enabled(),
        'online_enabled': _online_allowed(),
        'local_data_installed': _cfcd_installed() or _brands_installed(),
        'local_sources': {
            'cfcd': _cfcd_installed(),
            'brands': _brands_installed(),
        },
        'data_directory': os.path.abspath(_DATA_DIR),
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
                   choices=['auto', 'cfcd', 'brands', 'usda', 'openfoodfacts', 'off', 'all'],
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
