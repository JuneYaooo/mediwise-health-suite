"""Compatibility shell.  The catalog now lives in shared/story/catalog.py.

Kept so existing imports, actions, tests, and the design gallery keep working
unchanged after the domain-neutral extraction.  New code should import from
`shared.story` instead.
"""

from __future__ import annotations

from _story_bootstrap import story_module

_catalog = story_module("catalog")

STYLE_LAYOUT_MODES = _catalog.STYLE_LAYOUT_MODES
STYLE_PREFERRED_DOMAINS = _catalog.STYLE_PREFERRED_DOMAINS
STYLE_CATALOG = _catalog.STYLE_CATALOG
STYLES_BY_ID = _catalog.STYLES_BY_ID
StoryStyle = _catalog.StoryStyle
validate_catalog = _catalog.validate_catalog

# Pre-extraction name for the dataclass.
WeightCardStyle = _catalog.StoryStyle

__all__ = [
    "STYLES_BY_ID",
    "STYLE_CATALOG",
    "STYLE_LAYOUT_MODES",
    "STYLE_PREFERRED_DOMAINS",
    "StoryStyle",
    "WeightCardStyle",
    "validate_catalog",
]
