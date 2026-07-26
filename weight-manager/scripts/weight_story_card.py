"""Compatibility shell.  The renderer now lives in shared/story/render.py.

Kept so existing imports, actions, tests, and the design gallery keep working
unchanged after the domain-neutral extraction.  New code should import from
`shared.story` instead.
"""

from __future__ import annotations

from _story_bootstrap import story_module

_render = story_module("render")

CARD_WIDTH = _render.CARD_WIDTH
CARD_HEIGHT = _render.CARD_HEIGHT
PRODUCT_NAME = _render.PRODUCT_NAME
DISCLAIMER = _render.DISCLAIMER
STYLE_CONTENT_ROLES = _render.STYLE_CONTENT_ROLES
MOMENT_VISIBLE_STYLES = _render.MOMENT_VISIBLE_STYLES
CONTEXT_VISIBLE_STYLES = _render.CONTEXT_VISIBLE_STYLES
ANALYSIS_LABELS = _render.ANALYSIS_LABELS
FAMILY_HEADLINES = _render.FAMILY_HEADLINES
FAMILY_RENDERERS = _render.FAMILY_RENDERERS
CORE_STATE_COPY = _render.CORE_STATE_COPY

render_weight_story_html = _render.render_weight_story_html
available_story_styles = _render.available_story_styles

# Domain-neutral name for the same entry point.
render_story_html = _render.render_weight_story_html

__all__ = [
    "ANALYSIS_LABELS",
    "CARD_HEIGHT",
    "CARD_WIDTH",
    "CONTEXT_VISIBLE_STYLES",
    "CORE_STATE_COPY",
    "DISCLAIMER",
    "FAMILY_HEADLINES",
    "FAMILY_RENDERERS",
    "MOMENT_VISIBLE_STYLES",
    "PRODUCT_NAME",
    "STYLE_CONTENT_ROLES",
    "available_story_styles",
    "render_story_html",
    "render_weight_story_html",
]
