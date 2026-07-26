#!/usr/bin/env python3
"""Regenerate tests/golden/weight_story_digests.json.

The golden file locks the 24 weight story templates byte-for-byte while the
narrative engine moves out of weight-manager/ into a domain-neutral package.
A digest diff during that move means user-visible output changed, which is a
bug, not a reason to run this script.

Only run it when the copy or layout change is intentional and reviewed:

    python3 tests/golden/regenerate_weight_story_digests.py --diff    # inspect first
    python3 tests/golden/regenerate_weight_story_digests.py --write   # then commit

--diff prints which styles moved and exits non-zero if any did, so it also
works as a pre-commit check.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
for candidate in (ROOT / "weight-manager" / "scripts", ROOT / "mediwise-health-tracker" / "scripts"):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import weight_truth_card  # noqa: E402
from weight_management_analysis import analyze_weight_management  # noqa: E402
from weight_story_card import (  # noqa: E402
    available_story_styles,
    render_weight_story_html,
)
from weight_style_selector import select_weight_card_style  # noqa: E402

GOLDEN_PATH = Path(__file__).resolve().parent / "weight_story_digests.json"

FIXTURE_START = date(2026, 6, 20)
FIXTURE_DAYS = 30
FIXTURE_AS_OF = date(2026, 7, 19)


def base_analysis():
    values = [
        72.0 - index * 0.045 + (0.16 if index % 5 == 0 else 0.0)
        for index in range(FIXTURE_DAYS)
    ]
    records = [
        {
            "value": value,
            "measured_at": (FIXTURE_START + timedelta(days=index)).isoformat() + " 08:00:00",
        }
        for index, value in enumerate(values)
    ]
    return weight_truth_card.analyze_weight_records(records, days=FIXTURE_DAYS)


def enriched_analysis():
    analysis = base_analysis()
    diet, exercise, sleep = weight_truth_card._demo_management_records(
        FIXTURE_AS_OF, FIXTURE_DAYS
    )
    analysis["management"] = analyze_weight_management(
        analysis, diet, exercise, sleep, days=FIXTURE_DAYS, as_of=FIXTURE_AS_OF
    )
    return analysis


def compute():
    fixtures = {"redacted": base_analysis(), "enriched": enriched_analysis()}
    digests = {}
    for name, analysis in fixtures.items():
        digests[name] = {}
        for style_id in sorted(available_story_styles()):
            selection = select_weight_card_style(
                analysis, scene="share", pinned_style=style_id, seed="render-" + style_id
            )
            rendered = render_weight_story_html(analysis, selection)
            digests[name][style_id] = hashlib.sha256(
                rendered.encode("utf-8")
            ).hexdigest()
    return digests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--diff", action="store_true", help="report drift, do not write")
    group.add_argument("--write", action="store_true", help="overwrite the golden file")
    args = parser.parse_args()

    fresh = compute()
    current = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    drift = []
    for fixture, styles in fresh.items():
        recorded = current.get(fixture, {})
        for style_id, digest in styles.items():
            if recorded.get(style_id) != digest:
                drift.append("%s/%s" % (fixture, style_id))
        for style_id in recorded:
            if style_id not in styles:
                drift.append("%s/%s (removed)" % (fixture, style_id))

    if args.diff:
        if drift:
            print("digest drift in %d entries:" % len(drift))
            for item in sorted(drift):
                print("  " + item)
            return 1
        print("no drift; %d styles locked per fixture" % len(fresh["redacted"]))
        return 0

    payload = dict(current)
    payload.update(fresh)
    GOLDEN_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("wrote %s (%d changed)" % (GOLDEN_PATH.name, len(drift)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
