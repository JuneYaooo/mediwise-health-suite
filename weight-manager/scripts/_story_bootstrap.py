"""Locate the shared.story package from inside weight-manager/scripts.

The scripts in this directory are executed directly (`python3 weight_truth_card.py`)
and are also imported flat by the existing tests and the design gallery, so the
repository root is not guaranteed to be on sys.path.  This helper puts it there
once and returns submodules of `shared.story`.
"""

from __future__ import annotations

import importlib
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def ensure_root_on_path() -> str:
    """Make the repository root importable so `shared.story` resolves."""
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    return _ROOT


def story_module(name: str):
    """Import and return `shared.story.<name>`."""
    ensure_root_on_path()
    return importlib.import_module("shared.story." + name)


def story_package():
    """Import and return the `shared.story` package itself."""
    ensure_root_on_path()
    return importlib.import_module("shared.story")
