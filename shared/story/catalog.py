"""Declarative catalog for MediWise weight-card storytelling styles.

The catalog deliberately contains visual/narrative preferences only.  It must
never encode BMI, sex, age, diagnosis, medication, or a moral judgement about
weight direction.  Health analysis decides what may be stated; this catalog
only decides how an eligible statement can be expressed.

One catalog is shared by every domain, so no string here may name a domain, a
unit, or a metric.  `signature` is printed on the card, so where it needs to say
what is being measured it carries a `{reading}` / `{subject}` slot that the
renderer fills from the caller's lexicon -- the same mechanism the copy tables in
`render.py` use.  A literal 体重 / 秤面 / 分钟 in this file would print on a sleep
card unchanged; `tests/test_domain_adapters.py` fails the build if one appears.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Tuple

# motion.py depends on nothing in this package, so this import stays acyclic.
from .motion import STYLE_MOTION_MODES


STYLE_LAYOUT_MODES = {
    "weather-now": "radar-poster",
    "weather-week": "horizontal-forecast",
    "direction-course": "navigation-chart",
    "direction-log": "lined-notebook",
    "terrain-contour": "full-bleed-topographic",
    "terrain-valley": "foldout-route-map",
    "editorial-cover": "magazine-cover",
    "editorial-headline": "newspaper-front-page",
    "capsule-seal": "museum-label-and-seal",
    "capsule-letter": "single-letter-sheet",
    "film-roll": "horizontal-film-strip",
    "film-grid": "contact-sheet",
    "rhythm-calendar": "wall-calendar",
    "rhythm-moon": "orbital-poster",
    "ticket-journey": "oversized-ticket",
    "passport-stamps": "open-passport-spread",
    "vinyl-record": "album-sleeve",
    "weekly-single": "music-single-cover",
    "body-letter": "handwritten-letter",
    "no-verdict": "unfinished-manuscript",
    "observer-persona": "trading-card",
    "observation-file": "case-file-folder",
    "constellation": "full-bleed-night-sky",
    "data-fingerprint": "minimal-art-print",
}


STYLE_PREFERRED_DOMAINS = {
    "weather-now": ("weight",),
    "weather-week": ("sleep",),
    "direction-course": ("weight",),
    "direction-log": ("activity",),
    "terrain-contour": ("weight",),
    "terrain-valley": ("activity",),
    "editorial-cover": ("intake",),
    "editorial-headline": ("weight",),
    "capsule-seal": ("intake",),
    "capsule-letter": ("sleep",),
    "film-roll": ("recording",),
    "film-grid": ("intake",),
    "rhythm-calendar": ("recording",),
    "rhythm-moon": ("sleep",),
    "ticket-journey": ("activity",),
    "passport-stamps": ("recording",),
    "vinyl-record": ("activity",),
    "weekly-single": ("synthesis",),
    "body-letter": ("sleep",),
    "no-verdict": ("synthesis",),
    "observer-persona": ("recording",),
    "observation-file": ("synthesis",),
    "constellation": ("synthesis",),
    "data-fingerprint": ("intake",),
}


@dataclass(frozen=True)
class StoryStyle:
    id: str
    family: str
    family_name: str
    name: str
    variant: str
    metaphor: str
    tones: Tuple[str, ...]
    densities: Tuple[str, ...]
    scenes: Tuple[str, ...]
    min_recorded_days: int
    requires_trend: bool
    base_weight: float
    rarity: str
    signature: str
    layout_mode: str
    preferred_domains: Tuple[str, ...]
    # Third uniqueness class, alongside content_role and layout_mode: the gesture
    # this template animates with. Declared in shared/story/motion.py.
    motion_mode: str = ""
    required_domains: Tuple[str, ...] = ()
    renderer_status: str = "production"

    def public_dict(self) -> dict:
        value = asdict(self)
        for key in ("tones", "densities", "scenes", "preferred_domains", "required_domains"):
            value[key] = list(value[key])
        return value


def _style(
    style_id: str,
    family: str,
    family_name: str,
    name: str,
    variant: str,
    metaphor: str,
    tones: Tuple[str, ...],
    densities: Tuple[str, ...],
    scenes: Tuple[str, ...],
    min_days: int,
    requires_trend: bool,
    weight: float,
    rarity: str,
    signature: str,
    renderer_status: str = "production",
) -> StoryStyle:
    return StoryStyle(
        id=style_id,
        family=family,
        family_name=family_name,
        name=name,
        variant=variant,
        metaphor=metaphor,
        tones=tones,
        densities=densities,
        scenes=scenes,
        min_recorded_days=min_days,
        requires_trend=requires_trend,
        base_weight=weight,
        rarity=rarity,
        signature=signature,
        layout_mode=STYLE_LAYOUT_MODES[style_id],
        preferred_domains=STYLE_PREFERRED_DOMAINS[style_id],
        motion_mode=STYLE_MOTION_MODES[style_id],
        renderer_status=renderer_status,
    )


STYLE_CATALOG: Tuple[StoryStyle, ...] = (
    _style("weather-now", "weather", "身体气象", "身体天气预报", "A", "把短期波动译成今天的身体天气", ("gentle", "playful"), ("concise",), ("daily", "share"), 1, False, 1.15, "common", "一枚只描述观测状态、不解释原因的天气印记"),
    _style("weather-week", "weather", "身体气象", "一周气象档案", "B", "把多个记录日排成一周气象带", ("gentle", "playful"), ("detailed",), ("weekly", "share"), 5, False, 0.82, "uncommon", "由真实记录密度生成的气象带"),
    _style("direction-course", "direction", "航行记录", "身体航向", "A", "把单日波动看作浪、长期趋势看作航向", ("calm", "editorial"), ("concise", "detailed"), ("daily", "weekly", "share"), 2, False, 1.28, "common", "最新{reading}与稳健趋势之间的距离", "production"),
    _style("direction-log", "direction", "航行记录", "航海日志", "B", "用航程、浪高和坐标组织阶段记录", ("calm", "editorial"), ("detailed",), ("weekly", "milestone"), 7, True, 0.83, "uncommon", "每次生成都会延续的私人航海编号"),
    _style("terrain-contour", "terrain", "地形探索", "身体等高线", "A", "把较长周期的变化生成一幅等高线地形", ("calm", "bold"), ("detailed",), ("weekly", "milestone", "share"), 10, True, 0.63, "rare", "由趋势、波动和覆盖度共同生成的唯一地形"),
    _style("terrain-valley", "terrain", "地形探索", "山谷与高地", "B", "把阶段波动讲成一段穿越地形的路", ("gentle", "bold"), ("concise", "detailed"), ("milestone", "share"), 14, True, 0.48, "rare", "本阶段独有的最高点、谷地和路径"),
    _style("editorial-cover", "editorial", "编辑出版", "身体数据刊物", "A", "把一次观察做成个人数据杂志封面", ("editorial", "bold"), ("detailed",), ("weekly", "milestone", "share"), 7, True, 0.91, "uncommon", "期号、头条和一条反直觉发现"),
    _style("editorial-headline", "editorial", "编辑出版", "本周身体头条", "B", "只选择一个最值得记住的事实作为头条", ("editorial", "bold"), ("concise",), ("daily", "weekly", "share"), 4, False, 1.02, "common", "像新闻标题一样清楚，但不制造健康危机"),
    _style("capsule-seal", "capsule", "时间收藏", "时间胶囊", "A", "封存这一阶段的观察，等待未来回看", ("gentle", "calm"), ("concise",), ("milestone", "share"), 7, False, 0.67, "uncommon", "封存日期与仅属于这一阶段的状态短句"),
    _style("capsule-letter", "capsule", "时间收藏", "写给未来的身体", "B", "把可靠事实写成一封不催促未来的信", ("gentle",), ("detailed",), ("milestone", "share"), 4, False, 0.50, "rare", "未来再次打开时可以与新数据形成回信"),
    _style("film-roll", "film", "胶片日记", "身体胶片", "A", "把几个数据瞬间排成有时间感的胶卷", ("gentle", "playful"), ("detailed",), ("weekly", "share"), 5, False, 0.84, "uncommon", "同日多次记录会形成双重曝光彩蛋"),
    _style("film-grid", "film", "胶片日记", "本月九宫格", "B", "用九个真实记录切片拼成阶段回忆", ("gentle", "playful"), ("detailed",), ("milestone", "share"), 9, False, 0.61, "rare", "记录不足九格时保留诚实留白而不补造数据"),
    _style("rhythm-calendar", "rhythm", "节律日历", "身体节律", "A", "让记录规律和间隔成为主视觉", ("calm", "editorial"), ("detailed",), ("weekly", "milestone"), 7, False, 1.04, "common", "每个人不同的记录节拍，而不是打卡排名"),
    _style("rhythm-moon", "rhythm", "节律日历", "月相日历", "B", "用抽象月相表达记录覆盖与时间节奏", ("gentle", "calm"), ("concise",), ("weekly", "share"), 7, False, 0.56, "rare", "月相由覆盖度生成，不暗示生理或医学因果"),
    _style("ticket-journey", "journey", "里程成就", "健康车票", "A", "把阶段记录做成一张从此刻出发的车票", ("playful", "bold"), ("concise",), ("daily", "milestone", "share"), 1, False, 1.06, "common", "起点是第一次记录，目的地不是某个{subject}数字"),
    _style("passport-stamps", "journey", "里程成就", "身体护照", "B", "一次阶段观察就是一枚不评价数值高低的印章", ("playful", "editorial"), ("detailed",), ("milestone", "share"), 7, False, 0.72, "uncommon", "只奖励观察行为与时间跨度的收藏印章"),
    _style("vinyl-record", "music", "唱片音乐", "身体唱片", "A", "把数据轨迹变成一张私人唱片纹路", ("playful", "bold"), ("concise", "detailed"), ("weekly", "milestone", "share"), 7, True, 0.70, "uncommon", "由数据生成、可复现的个人唱片纹路"),
    _style("weekly-single", "music", "唱片音乐", "本周身体单曲", "B", "为本周最值得记住的观察生成单曲标题", ("playful", "bold"), ("concise",), ("daily", "weekly", "share"), 4, False, 0.88, "uncommon", "不是随机鸡汤，而是由真实状态映射出的曲名"),
    _style("body-letter", "letter", "身体来信", "身体给你的信", "A", "用第一人称温柔转述已经确认的数据事实", ("gentle", "calm"), ("concise", "detailed"), ("daily", "weekly", "share"), 1, False, 1.16, "common", "不命令、不责备，也不假装知道身体的原因"),
    _style("no-verdict", "letter", "身体来信", "今天先不下结论", "B", "把数据不足时的诚实克制变成主题", ("gentle", "calm"), ("concise",), ("daily", "share"), 0, False, 1.35, "common", "序章页会告诉用户还差什么，而不是显示空仪表盘"),
    _style("observer-persona", "identity", "个性标签", "记录者人格卡", "A", "根据记录行为生成安全的观察者人格", ("playful", "editorial"), ("concise",), ("milestone", "share"), 5, False, 0.76, "uncommon", "长线观察者、节律收藏家等非健康优劣标签"),
    _style("observation-file", "identity", "个性标签", "身体观察档案", "B", "用档案编号、观察习惯和数据签名建立身份感", ("editorial", "calm"), ("detailed",), ("weekly", "milestone", "share"), 7, False, 0.73, "uncommon", "不暴露身份信息的私人观察编号"),
    _style("constellation", "generative", "生成艺术", "身体星图", "A", "把记录点生成一幅可复现的私人星图", ("bold", "gentle"), ("concise",), ("milestone", "share"), 10, True, 0.42, "rare", "点数、密度和主方向都来自真实数据"),
    _style("data-fingerprint", "generative", "生成艺术", "数据指纹", "B", "用趋势、波动和记录频率生成唯一抽象纹理", ("bold", "editorial"), ("concise",), ("milestone", "share"), 10, True, 0.36, "rare", "同一阶段可复现、不同用户不雷同的数据纹理"),
)


STYLES_BY_ID: Dict[str, StoryStyle] = {style.id: style for style in STYLE_CATALOG}


def validate_catalog() -> None:
    if len(STYLE_CATALOG) < 24 or len(STYLE_CATALOG) % 2:
        raise ValueError("story catalog must contain an even number of at least 24 styles")
    if len(STYLES_BY_ID) != len(STYLE_CATALOG):
        raise ValueError("story style ids must be unique")
    if len(set(STYLE_LAYOUT_MODES.values())) != len(STYLE_CATALOG):
        raise ValueError("each story style must have a unique layout mode")
    motion_modes = [style.motion_mode for style in STYLE_CATALOG]
    if not all(motion_modes):
        raise ValueError("every style must declare a motion mode")
    if len(set(motion_modes)) != len(STYLE_CATALOG):
        raise ValueError("each style must have a unique motion mode")
    family_counts: Dict[str, int] = {}
    for style in STYLE_CATALOG:
        family_counts[style.family] = family_counts.get(style.family, 0) + 1
        if style.rarity not in ("common", "uncommon", "rare"):
            raise ValueError("invalid rarity for %s" % style.id)
        if style.base_weight <= 0:
            raise ValueError("base weight must be positive for %s" % style.id)
        if not style.layout_mode or not style.preferred_domains:
            raise ValueError("style layout and preferred domain are required for %s" % style.id)
    if any(count != 2 for count in family_counts.values()):
        raise ValueError("each story family must contain exactly two variants")


validate_catalog()
