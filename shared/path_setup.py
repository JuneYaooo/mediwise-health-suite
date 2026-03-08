"""Unified path setup for cross-module imports.

All skill modules (health-monitor, wearable-sync, diet-tracker, weight-manager)
need to import from mediwise-health-tracker/scripts. This module provides a
single function to set up that path correctly.
"""

from __future__ import annotations

import os
import sys


def setup_mediwise_path():
    """Ensure mediwise-health-tracker/scripts is first on sys.path."""
    scripts_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), '..', 'mediwise-health-tracker', 'scripts')
    )
    sys.path = [path for path in sys.path if os.path.abspath(path or os.curdir) != scripts_dir]
    sys.path.insert(0, scripts_dir)
