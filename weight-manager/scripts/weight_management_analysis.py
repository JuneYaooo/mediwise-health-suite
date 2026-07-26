"""Compatibility shell.  Companion-domain synthesis now lives in
shared/story/synthesis.py.

Kept so existing imports, actions, tests, and the design gallery keep working
unchanged after the domain-neutral extraction.  New code should import from
`shared.story` instead.
"""

from __future__ import annotations

from _story_bootstrap import story_module

_synthesis = story_module("synthesis")

NON_CAUSAL_LIMIT = _synthesis.NON_CAUSAL_LIMIT
DOMAIN_NAMES = _synthesis.DOMAIN_NAMES

analyze_weight_management = _synthesis.analyze_weight_management

# Domain-neutral name for the same entry point.
analyze_companions = _synthesis.analyze_weight_management

__all__ = [
    "DOMAIN_NAMES",
    "NON_CAUSAL_LIMIT",
    "analyze_companions",
    "analyze_weight_management",
]
