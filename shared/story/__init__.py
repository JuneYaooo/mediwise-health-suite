"""Domain-neutral narrative engine for MediWise 健康译报.

Layering (see story-design/story-system.md):

    各域原始记录 -> adapters/<domain>.py -> Signal Frame -> selector -> render

The four modules below know nothing about any specific health domain; every
domain-specific noun reaches them through the adapter's `lexicon`.  Weight is
one registered domain, not the subject of the system.

`domain` defaults to "weight" everywhere so the pre-extraction weight actions
keep producing byte-identical output.
"""

from __future__ import annotations

from .adapters import (
    DEFAULT_DOMAIN,
    available_domains,
    get_adapter,
    lexicon_for,
    lexicon_for_analysis,
    product_name_for,
)
from .catalog import (
    STYLE_CATALOG,
    STYLES_BY_ID,
    StoryStyle,
    validate_catalog,
)
from .render import (
    CARD_HEIGHT,
    CARD_WIDTH,
    CONTEXT_VISIBLE_STYLES,
    DISCLAIMER,
    MOMENT_VISIBLE_STYLES,
    PRODUCT_NAME,
    STYLE_CONTENT_ROLES,
    available_story_styles,
    render_weight_story_html,
)
from .selector import (
    VALID_DENSITIES,
    VALID_SCENES,
    VALID_TONES,
    derive_style_seed,
    detect_story_moments,
    observer_persona,
    select_weight_card_style,
)
from .synthesis import NON_CAUSAL_LIMIT, analyze_weight_management

# Domain-neutral aliases.  The weight-shaped names above stay exported so the
# existing actions, tests, and the design gallery keep importing what they
# always did; new domains should prefer these.
render_story_html = render_weight_story_html
select_story_style = select_weight_card_style
analyze_companions = analyze_weight_management

__all__ = [
    "CARD_HEIGHT",
    "CARD_WIDTH",
    "CONTEXT_VISIBLE_STYLES",
    "DEFAULT_DOMAIN",
    "DISCLAIMER",
    "MOMENT_VISIBLE_STYLES",
    "NON_CAUSAL_LIMIT",
    "PRODUCT_NAME",
    "STYLES_BY_ID",
    "STYLE_CATALOG",
    "STYLE_CONTENT_ROLES",
    "StoryStyle",
    "VALID_DENSITIES",
    "VALID_SCENES",
    "VALID_TONES",
    "analyze_companions",
    "analyze_weight_management",
    "available_domains",
    "available_story_styles",
    "derive_style_seed",
    "detect_story_moments",
    "get_adapter",
    "lexicon_for",
    "lexicon_for_analysis",
    "observer_persona",
    "product_name_for",
    "render_story_html",
    "render_weight_story_html",
    "select_story_style",
    "select_weight_card_style",
    "validate_catalog",
]
