"""Motion layer: compiles a Signal Frame into a deterministic animation timeline.

See story-design/story-system.md (运动语法, 幕结构, 冻结海报帧, 动作安全约束) and
the `motion` block of story-design/signal-frame.schema.json, which this module is
the only producer of.

Three rules from the contract shape every function here:

1. **动画时间轴 = 日历时间轴.**  `settle` beats advance by the *real* interval
   between recorded days.  A five-day gap costs five beats of silence; missing
   days are never interpolated, back-filled, or averaged into an even cadence.
2. **确定性.**  Every parameter derives from the existing style seed, so the same
   seed plus the same data yields a byte-identical SVG.  No clock, no RNG state
   that outlives this call.
3. **动作不泄露脱敏内容.**  Motion is a fresh leakage channel: exact beat gaps
   reconstruct exact dates.  When dates are redacted, gaps quantize to buckets
   and only the bucket reaches the timeline.

This module is domain-neutral.  It sees a series of points and a style, never
体重, kg, or any other domain noun.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Mapping, Optional, Sequence, Tuple

# The closed set from 运动语法. Adding a seventh primitive is a contract change,
# not an implementation detail: it must be argued for in story-system.md first.
MOTION_PRIMITIVES: Tuple[str, ...] = ("draw", "settle", "reveal", "breathe", "count", "trace")

# Globally unique per template, alongside content_role and layout_mode. Named for
# the physical gesture of the layout's metaphor, so a reviewer can predict the
# motion from the name without reading the renderer.
STYLE_MOTION_MODES: Mapping[str, str] = {
    "weather-now": "radar-sweep",
    "weather-week": "forecast-slide",
    "direction-course": "compass-swing",
    "direction-log": "line-by-line",
    "terrain-contour": "contour-rise",
    "terrain-valley": "foldout-unfold",
    "editorial-cover": "cover-drop",
    "editorial-headline": "press-roll",
    "capsule-seal": "seal-press",
    "capsule-letter": "sheet-unfold",
    "film-roll": "strip-advance",
    "film-grid": "frame-fill",
    "rhythm-calendar": "cell-tick",
    "rhythm-moon": "orbit-turn",
    "ticket-journey": "stub-tear",
    "passport-stamps": "stamp-land",
    "vinyl-record": "disc-spin",
    "weekly-single": "needle-drop",
    "body-letter": "hand-write",
    "no-verdict": "margin-note",
    "observer-persona": "card-flip",
    "observation-file": "folder-open",
    "constellation": "star-trace",
    "data-fingerprint": "ridge-etch",
}

# Which primitives each mode is allowed to use. Order is the authoring order, not
# the playback order; acts decide timing.
MODE_PRIMITIVES: Mapping[str, Tuple[str, ...]] = {
    "radar-sweep": ("draw", "settle", "breathe"),
    "forecast-slide": ("reveal", "settle", "count"),
    "compass-swing": ("draw", "settle", "reveal"),
    "line-by-line": ("reveal", "count"),
    # The contour paths are `draw`'s target, so `trace` would have duplicated it,
    # and the layout has no decoration to breathe. Declares what it can show.
    "contour-rise": ("draw", "reveal", "count"),
    "foldout-unfold": ("reveal", "draw", "settle"),
    "cover-drop": ("reveal", "count"),
    "press-roll": ("reveal", "draw"),
    "seal-press": ("reveal", "breathe"),
    "sheet-unfold": ("reveal", "count"),
    "strip-advance": ("settle", "reveal"),
    "frame-fill": ("settle", "reveal", "count"),
    "cell-tick": ("settle", "reveal"),
    # The moon grid is per-day slots, so it settles rather than traces, and the
    # orbital poster hides `.metrics` and carries no decoration — nothing breathes.
    "orbit-turn": ("settle", "reveal", "count"),
    # A ticket is printed type, not plotted geometry — nothing here takes a stroke.
    "stub-tear": ("reveal", "count"),
    "stamp-land": ("settle", "reveal", "breathe"),
    # The sleeve's plotted line is `draw`'s target and the disc itself breathes;
    # there is no third figure to trace.
    "disc-spin": ("breathe", "draw", "count"),
    "needle-drop": ("reveal", "draw", "count"),
    # A handwritten letter has no plotted line; its figures are inline in the prose,
    # which `count` now reaches. See COUNT_SELECTOR in svg.py.
    "hand-write": ("reveal", "count"),
    "margin-note": ("reveal", "breathe"),
    "card-flip": ("reveal", "count"),
    "folder-open": ("reveal", "settle"),
    "star-trace": ("trace", "settle", "count"),
    "ridge-etch": ("trace", "draw"),
}

# Primitives that need a plotted series. A zero-data card keeps its mode but
# cannot draw, settle, trace, or count what was never recorded.
SERIES_PRIMITIVES = frozenset({"draw", "settle", "trace", "count"})

# 幕结构: four acts, one loop. Fractions of duration_ms, in playback order:
# 立论 -> 证据 -> 分析 -> 收束.
ACT_BOUNDS: Tuple[Tuple[str, float, float], ...] = (
    ("claim", 0.00, 0.18),
    ("evidence", 0.18, 0.58),
    ("analysis", 0.58, 0.85),
    ("closing", 0.85, 1.00),
)

# Schema bounds, restated so a bad derivation fails here instead of at validation.
DURATION_BOUNDS = (4000, 12000)
TEMPO_BOUNDS = (0.5, 8.0)
STAGGER_BOUNDS = (0, 2000)
HOLD_BOUNDS = (0, 4000)
MAX_BEATS = 90

# 动作安全约束: no flicker above 3 Hz anywhere in the system.
MAX_FLICKER_HZ = 3.0

GAP_BUCKETS: Tuple[Tuple[str, int], ...] = (
    ("none", 0),
    ("short", 1),
    ("medium", 2),
    ("long", 4),
)


def motion_mode_for(style_id: str) -> str:
    """Return the globally unique motion mode for a template id."""
    mode = STYLE_MOTION_MODES.get(style_id)
    if not mode:
        raise ValueError("no motion_mode declared for style %s" % style_id)
    return mode


def _seed_digest(style_id: str, seed: object) -> str:
    # Same construction as selector._signature so motion and visuals stay in the
    # same deterministic family without importing each other.
    return hashlib.sha256(("motion|" + style_id + "|" + str(seed)).encode("utf-8")).hexdigest()


def _clamp(value, low, high):
    return max(low, min(high, value))


def _parse_date(value: object) -> Optional[date]:
    text = str(value or "")[:10]
    try:
        parts = [int(part) for part in text.split("-")]
    except ValueError:
        return None
    if len(parts) != 3:
        return None
    try:
        return date(parts[0], parts[1], parts[2])
    except ValueError:
        return None


def _bucket_for(gap_days: int) -> str:
    label = "none"
    for name, threshold in GAP_BUCKETS:
        if gap_days >= threshold:
            label = name
    return label


def _bucket_beats(gap_days: int) -> int:
    """Quantized beat cost used when exact dates are redacted.

    A redacted card still shows that a gap happened, and roughly how big, but the
    animation no longer encodes the exact day count that would let a viewer
    reconstruct the calendar.
    """
    return {"none": 0, "short": 1, "medium": 2, "long": 3}[_bucket_for(gap_days)]


def compile_beats(
    series: Sequence[Mapping[str, object]],
    *,
    tempo: float,
    stagger_ms: int,
    start_ms: int = 0,
    exact_dates: bool = False,
) -> list:
    """Map recorded days onto beats, charging real calendar gaps as real silence.

    `exact_dates=False` (the default, matching the privacy defaults) keeps the
    perceptible silence but quantizes it, so beat timing cannot be inverted into
    the underlying dates.
    """
    beat_ms = int(round(1000.0 / _clamp(float(tempo), *TEMPO_BOUNDS)))
    beats = []
    cursor = int(start_ms)
    previous: Optional[date] = None
    for index, point in enumerate(series[:MAX_BEATS]):
        current = _parse_date(point.get("date")) if isinstance(point, Mapping) else None
        gap_days = 0
        if previous is not None and current is not None:
            gap_days = max(0, (current - previous).days - 1)
        # Silence first, then the point lands: the pause belongs to the gap it
        # represents, not to the day that follows it.
        silent_beats = gap_days if exact_dates else _bucket_beats(gap_days)
        cursor += silent_beats * beat_ms
        beat = {"index": index, "at_ms": cursor}
        if gap_days:
            if exact_dates:
                beat["gap_days"] = gap_days
            beat["gap_bucket"] = _bucket_for(gap_days)
        beats.append(beat)
        cursor += beat_ms + int(stagger_ms)
        if current is not None:
            previous = current
    return beats


def act_timeline(duration_ms: int) -> list:
    """Absolute act boundaries for one loop, in playback order."""
    return [
        {
            "act": name,
            "start_ms": int(round(duration_ms * start)),
            "end_ms": int(round(duration_ms * end)),
        }
        for name, start, end in ACT_BOUNDS
    ]


def compile_motion(
    style_id: str,
    *,
    seed: object,
    series: Sequence[Mapping[str, object]] = (),
    shape: str = "insufficient",
    exact_dates: bool = False,
    reduced_motion: bool = False,
) -> dict:
    """Compile the `motion` block of a Signal Frame.

    `reduced_motion=True` collapses the timeline to the poster frame alone: the
    contract requires prefers-reduced-motion to degrade to the frozen frame, not
    to a slower animation.
    """
    mode = motion_mode_for(style_id)
    digest = _seed_digest(style_id, seed)

    allowed = MODE_PRIMITIVES[mode]
    has_series = len(series) >= 2
    primitives = tuple(p for p in allowed if has_series or p not in SERIES_PRIMITIVES)
    if not primitives:
        # Every card must still move something; `reveal` only needs text, which a
        # zero-data card always has.
        primitives = ("reveal",)

    motion_variant = int(digest[0:2], 16) % 8
    tempo = _clamp(1.6 + (int(digest[2:4], 16) % 9) * 0.2, *TEMPO_BOUNDS)
    stagger_ms = int(_clamp(40 + (int(digest[4:6], 16) % 8) * 15, *STAGGER_BOUNDS))
    hold_ms = int(_clamp(1200 + (int(digest[6:8], 16) % 5) * 100, *HOLD_BOUNDS))

    # Evidence act is where beats live; its length follows how much was actually
    # recorded, then the whole loop is scaled to fit the schema window.
    beats = compile_beats(
        series, tempo=tempo, stagger_ms=stagger_ms, exact_dates=exact_dates
    ) if has_series else []
    evidence_span = ACT_BOUNDS[1][2] - ACT_BOUNDS[1][1]
    beats_end = (beats[-1]["at_ms"] + int(round(1000.0 / tempo))) if beats else 0
    natural = int(round(beats_end / evidence_span)) if beats_end else DURATION_BOUNDS[0]
    duration_ms = int(_clamp(natural + (int(digest[8:10], 16) % 5) * 200, *DURATION_BOUNDS))

    if beats_end > int(round(duration_ms * evidence_span)):
        # More recorded days than the loop can hold at this tempo: compress the
        # cadence rather than dropping points, so no day silently disappears.
        scale = (duration_ms * evidence_span) / float(beats_end)
        offset = int(round(duration_ms * ACT_BOUNDS[1][1]))
        for beat in beats:
            beat["at_ms"] = offset + int(round(beat["at_ms"] * scale))
    else:
        offset = int(round(duration_ms * ACT_BOUNDS[1][1]))
        for beat in beats:
            beat["at_ms"] += offset

    # Poster frame sits in the trailing hold, after all four acts have played:
    # that is the only instant where claim, evidence, full analysis, and the save
    # reason are simultaneously on screen, so it is the frame that reproduces the
    # pre-animation static composition the golden digests locked.
    poster_time_ms = duration_ms + hold_ms // 2

    if reduced_motion:
        return {
            "motion_mode": mode,
            "primitives": ["reveal"],
            "motion_variant": motion_variant,
            "duration_ms": DURATION_BOUNDS[0],
            "hold_ms": 0,
            "poster_time_ms": 0,
            "beats": [],
            "reduced_motion": True,
            "acts": act_timeline(DURATION_BOUNDS[0]),
            "flicker_hz_max": MAX_FLICKER_HZ,
            "calendar_mapped": False,
            "gap_precision": "poster-only",
        }

    return {
        "motion_mode": mode,
        "primitives": list(primitives),
        "motion_variant": motion_variant,
        "tempo": round(tempo, 2),
        "stagger_ms": stagger_ms,
        "duration_ms": duration_ms,
        "hold_ms": hold_ms,
        "poster_time_ms": poster_time_ms,
        "beats": beats,
        "reduced_motion": False,
        "acts": act_timeline(duration_ms),
        "flicker_hz_max": MAX_FLICKER_HZ,
        "calendar_mapped": bool(beats),
        "gap_precision": "exact" if exact_dates else "bucketed",
        "shape": shape,
    }
