"""Compatibility shell.  The selector now lives in shared/story/selector.py.

Kept so existing imports, actions, tests, and the design gallery keep working
unchanged after the domain-neutral extraction.  New code should import from
`shared.story` instead.
"""

from __future__ import annotations

from _story_bootstrap import story_module

_selector = story_module("selector")

VALID_SCENES = _selector.VALID_SCENES
VALID_TONES = _selector.VALID_TONES
VALID_DENSITIES = _selector.VALID_DENSITIES
MOMENT_STYLE_BOOSTS = _selector.MOMENT_STYLE_BOOSTS
MOMENT_COPY = _selector.MOMENT_COPY

detect_story_moments = _selector.detect_story_moments
observer_persona = _selector.observer_persona
derive_style_seed = _selector.derive_style_seed
select_weight_card_style = _selector.select_weight_card_style

# Domain-neutral name for the same entry point.
select_story_style = _selector.select_weight_card_style

__all__ = [
    "MOMENT_COPY",
    "MOMENT_STYLE_BOOSTS",
    "VALID_DENSITIES",
    "VALID_SCENES",
    "VALID_TONES",
    "derive_style_seed",
    "detect_story_moments",
    "observer_persona",
    "select_story_style",
    "select_weight_card_style",
]
