"""SVG renderer: turns a rendered card plus a motion timeline into an animated SVG.

Design decision worth stating plainly: this module does **not** re-implement the
24 layouts.  It renders the existing document through `render.render_story_html`
and wraps it in `<svg><foreignObject>`, then layers motion on top as CSS.  Two
consequences follow, and both are contract requirements:

- The frozen poster frame is the same composition the golden digests locked,
  because it *is* that composition — not a second implementation of it.
- Adding a domain or a template gets animation for free; motion is a property of
  the timeline, not of each layout's markup.

The trade-off is that these SVGs need a foreignObject-capable renderer (every
modern browser, and Chrome headless for PNG export).  Vector editors that ignore
foreignObject will show an empty frame.  That is acceptable for a share artefact
whose PNG is produced from the same file.

See story-design/story-system.md (运动语法, 幕结构, 冻结海报帧, 动作安全约束).
"""

from __future__ import annotations

import re
from typing import Mapping, Optional, Sequence

from . import motion as motion_mod
from .adapters import DEFAULT_DOMAIN
from .catalog import STYLES_BY_ID
from .render import CARD_HEIGHT, CARD_WIDTH, render_weight_story_html, series_source

# Markers in the rendered document.  Asserted rather than assumed: if the
# renderer's shell changes, SVG export must fail loudly instead of emitting a
# blank frame.
_CSS_OPEN = "<style>"
_CSS_CLOSE = "</style></head>"
_BODY_OPEN = "<body "
_ART_OPEN = '<main id="artboard"'
_ART_CLOSE = "</main></div>"

# `<html lang="...">`.  Not a required marker: a card without it still exports,
# it just falls back to the catalog's own language.
_LANG_PATTERN = re.compile(r"<html[^<>]*\blang=[\"']([^\"']+)[\"']", re.IGNORECASE)


# HTML void elements are legal unclosed in a text/html document but fatal inside
# foreignObject, which is parsed as XML.  Normalizing here keeps the templates
# authored as plain HTML instead of forcing 24 layouts to be XHTML-strict.
_VOID_TAGS = (
    "br", "hr", "img", "input", "meta", "link", "area",
    "base", "col", "embed", "source", "track", "wbr",
)
_VOID_PATTERN = re.compile(
    r"<(%s)((?:\s[^<>]*?)?)(?<!/)>" % "|".join(_VOID_TAGS), re.IGNORECASE
)


def _xhtml_safe(markup: str) -> str:
    """Self-close HTML void elements so the markup parses as XML."""
    return _VOID_PATTERN.sub(lambda m: "<%s%s/>" % (m.group(1), m.group(2)), markup)


# The artboard's inline charts are authored as bare `<svg>` in an HTML document,
# where the parser assigns the SVG namespace implicitly.  Inside foreignObject the
# default namespace is XHTML, so an un-namespaced `<svg>` parses as an unknown
# XHTML element: the class selectors still match, but it lays out as a block of
# zero height and draws nothing.  Declaring the namespace on each chart root puts
# it (and its inherited children) back in SVG.
_NESTED_SVG_PATTERN = re.compile(r"<svg(?![^<>]*\bxmlns=)((?:\s[^<>]*?)?)(/?)>", re.IGNORECASE)


def _namespace_nested_svg(markup: str) -> str:
    """Declare the SVG namespace on inline charts so they render inside XHTML."""
    return _NESTED_SVG_PATTERN.sub(
        lambda m: '<svg xmlns="http://www.w3.org/2000/svg"%s%s>' % (m.group(1), m.group(2)),
        markup,
    )


def _split_document(html: str) -> dict:
    """Pull the stylesheet, artboard markup, and root attributes out of the card."""
    for marker in (_CSS_OPEN, _CSS_CLOSE, _BODY_OPEN, _ART_OPEN, _ART_CLOSE):
        if marker not in html:
            raise ValueError("card document is missing the %r marker required for SVG export" % marker)
    css = html.split(_CSS_OPEN, 1)[1].split(_CSS_CLOSE, 1)[0]
    body_attrs = html.split(_BODY_OPEN, 1)[1].split(">", 1)[0]
    artboard = _ART_OPEN + html.split(_ART_OPEN, 1)[1].split(_ART_CLOSE, 1)[0] + "</main>"
    lang = _LANG_PATTERN.search(html)
    return {
        "css": css,
        "body_attrs": body_attrs,
        "artboard": _namespace_nested_svg(_xhtml_safe(artboard)),
        # The card declares its own language on <html>; carry it rather than
        # assuming Chinese, so a future localized card exports its own metrics.
        "lang": lang.group(1) if lang else "zh-CN",
    }


def _keyframes() -> str:
    """The six primitives as CSS keyframes.

    Value-neutral by construction: no colour changes, no scale-up on any
    direction, nothing that reads as celebration or alarm.  `breathe` touches
    opacity on decoration only; `count` never animates an absolute reading.
    """
    return (
        "@keyframes ms-draw{from{stroke-dashoffset:var(--ms-len,2400)}to{stroke-dashoffset:0}}"
        # `translate`/`scale`, not `transform`: several layouts tilt their own
        # elements (a letter sheet at .6deg, a ticket stub at .8deg), and a
        # keyframe ending in `transform:translateY(0)` replaces that rotation
        # instead of composing with it — straightening the card in the poster
        # frame.  The independent properties are applied before `transform`, so
        # the authored tilt survives.
        "@keyframes ms-settle{from{opacity:0;translate:0 14px}"
        "60%{opacity:var(--ms-op,1)}to{opacity:var(--ms-op,1);translate:0 0}}"
        "@keyframes ms-reveal{from{opacity:0;translate:0 18px}"
        "to{opacity:var(--ms-op,1);translate:0 0}}"
        # Starts and ends at full opacity so that parking this animation at any
        # cycle boundary — which is what the poster frame does — reproduces the
        # static card's decoration rather than a dimmed version of it.
        "@keyframes ms-breathe{0%,100%{opacity:var(--ms-op,1)}50%{opacity:.78}}"
        "@keyframes ms-count{from{opacity:0}to{opacity:var(--ms-op,1)}}"
        "@keyframes ms-trace{from{opacity:0;scale:.94}"
        "to{opacity:var(--ms-op,1);scale:1}}"
    )


# Elements the card authors *deliberately dim*, because the dimming carries
# meaning: an unrecorded day in a month grid is drawn faint precisely so it does
# not read as recorded.  A fade-in animation ending at a hard `opacity:1` would
# overwrite that and make the poster frame assert data the card never claimed.
# So every fade terminates at `var(--ms-op,1)` and the authored value is declared
# here — animation restores what the layout meant, it does not outvote it.
_AUTHORED_OPACITY = (
    ("#artboard .moon-grid i:not(.on)", ".25"),
)


def _authored_opacity_css() -> str:
    return "".join("%s{--ms-op:%s}" % (selector, value) for selector, value in _AUTHORED_OPACITY)


def _scoped(selector: str) -> str:
    """Prefix every comma part with `#artboard`.

    A bare part would also match the SVG host wrapper outside the artboard, and the
    freeze path parks `#artboard *` only — an unscoped rule would keep animating in
    the poster frame.
    """
    return ",".join("#artboard %s" % part.strip() for part in selector.split(","))


# An act must never play to an empty selector: a layout that carries its evidence
# in a prose paragraph instead of a metric grid would otherwise hold one frame for
# the whole 证据 act, and the card would read as broken rather than as quiet.
# `.metrics .metric` covers 20 of 24 templates; the rest name their evidence
# region themselves, so both vocabularies are listed. Layout-specific names are
# checked by tests/test_motion_contract.py, which fails if any template loses its
# target — that guard is what makes a new domain's layouts safe to add.
#
# "Losing a target" has two shapes, and both are dead air: the selector matches no
# element at all, or it matches an element a layout-mode rule sets `display:none`.
# The second is the one that bit here — ten templates hide `.hero` and carry their
# headline in their own vocabulary, so the 立论 act was animating a region the
# viewer never sees. Hence CLAIM_SELECTOR below.
EVIDENCE_SELECTOR = (
    ".metrics .metric,"
    ".letter-evidence,"  # family-letter: evidence is a sentence, not a number
    ".tracklist li,"  # music A: the tracklist is the evidence
    ".single-notes dl div,"  # music B: liner notes carry the readings
    ".moon-title p"  # rhythm B hides `.metrics`; the phase caption is the reading
)

# 立论 has to land on something visible in all 24 layouts. `.hero` is the shared
# headline region, but five families replace it outright (`display:none`) with a
# printed object of their own — a film caption, a ticket, a passport cover, a
# sleeve, a letterhead, a case file. Each names its own opening line here.
CLAIM_SELECTOR = (
    ".social-hook,.hero-kicker,.hero h1,"
    ".film-caption,.film-grid-caption,"  # film A/B: the caption is the headline
    ".ticket-main,.passport-cover,"  # journey A/B
    ".tracklist strong,.single-cover strong,"  # music A/B
    ".letter-sheet h2,"  # letter A/B, incl. the no-verdict sheet
    ".identity-card strong,.dossier-main h2"  # identity A/B
)

# 收束 lands on the footer everywhere; the letter families sign off instead.
CLOSING_SELECTOR = "footer,.letter-sign"

# `count` is the primitive that says "this number was measured". The letter
# families carry their figures inline inside the evidence sentence, so the number
# has to be reachable there too or `hand-write` counts nothing.
COUNT_SELECTOR = (
    ".metric strong,.letter-evidence b,.tracklist b,"
    ".single-notes dd,"  # music B: the liner-note figure is the <dd>, not a <b>
    ".moon-title strong"  # rhythm B: the phase count, since `.metrics` is hidden
)


def _act_css(acts: Sequence[Mapping[str, object]], duration_ms: int, hold_ms: int) -> str:
    """Map the four acts onto the card's regions, in reading order."""
    by_act = {str(a["act"]): a for a in acts}
    total = duration_ms + hold_ms
    rules = [
        # 立论: the situation portrait and headline arrive first.
        (CLAIM_SELECTOR, "ms-reveal", by_act["claim"]["start_ms"], 620),
        # The second wave of 立论, not a separate act: only the layouts that keep
        # `.hero` have a body paragraph under the headline to stagger.
        (".hero p", "ms-reveal", by_act["claim"]["end_ms"], 620),
        # 证据: the whole-region floor. `_evidence_css` staggers the individual
        # readings on top of this; the floor is what a single-block evidence
        # region (a letter's sentence, a phase caption) plays instead.
        (EVIDENCE_SELECTOR, "ms-reveal", by_act["evidence"]["start_ms"], 520),
        (COUNT_SELECTOR, "ms-count", by_act["evidence"]["start_ms"] + 160, 700),
        # 分析: the full synthesis paragraph and its causality boundary.
        (".analysis-note", "ms-reveal", by_act["analysis"]["start_ms"], 700),
        (".moment,.context", "ms-reveal", by_act["analysis"]["end_ms"] - 400, 600),
        # 收束: save reason and edition.
        (CLOSING_SELECTOR, "ms-reveal", by_act["closing"]["start_ms"], 560),
    ]
    css = []
    for selector, name, delay, dur in rules:
        css.append(
            "%s{animation:%s %dms both ease-out;animation-delay:%dms;"
            "animation-iteration-count:1}"
            % (_scoped(selector), name, dur, max(0, int(delay)))
        )
    # Decoration only, and slow enough that flicker never approaches 3 Hz.
    css.append(
        "%s{animation:ms-breathe %dms ease-in-out infinite}"
        % (BREATHE_SELECTOR, max(2400, total))
    )
    return "".join(css)


# Decoration that breathes. Named once because the freeze path has to switch this
# same set off: an infinite loop parked at an arbitrary instant would hold the
# decoration mid-dip, and the poster frame would be a dimmed copy of the static
# card instead of a match for it.
BREATHE_SELECTOR = (
    "#artboard .weather-rings i,#artboard .vinyl,#artboard .capsule-seal,#artboard .stamp,"
    # The ellipsis is the whole point of the no-verdict card: the one card that
    # declines to conclude should be the one visibly still waiting.
    "#artboard .ellipsis"
)


def _park_css(poster_ms: int) -> str:
    """Declarations that hold every animation at the poster instant.

    Removes the animations outright rather than seeking them to `poster_ms` and
    pausing.  The two are equivalent in intent — the poster instant is always
    `duration_ms + hold_ms // 2`, past the end of every act, so a sought animation
    would sit on its final keyframe — and every keyframe here is authored to end at
    the value the static card already has: `translate:0 0`, `scale:1`,
    `stroke-dashoffset:0`, `opacity:var(--ms-op,1)`.  So removing them lands on the
    same composition.

    They are not equivalent in rasterization.  A paused animation is still a running
    animation as far as compositing goes, and one holding a `translate` promotes its
    element to its own layer, which switches that subtree's text from subpixel to
    grayscale antialiasing.  The result was a poster frame that matched the static
    card in geometry, colour and opacity but differed along glyph edges on three
    templates.  With the animations gone there is no layer and no shift, and the
    frozen frame is the static card exactly.

    `poster_ms` is kept in the signature: it is what makes the equivalence argument
    above true, and a future poster instant that is *not* terminal would have to seek
    rather than remove.  Asserted rather than assumed, so that change cannot pass
    silently.
    """
    if poster_ms < 0:
        raise ValueError("poster instant cannot be negative: %r" % (poster_ms,))
    return "#artboard *,#artboard{animation:none !important}"


# One entry per per-day slot vocabulary. The last four mark days as objects rather
# than plotted points and hold far fewer slots than there are beats, so late beats
# simply find no nth-child — a truncated cadence, never a wrong one.
#
# `.moon-grid i` lives here rather than in TRACE_TARGETS because it *is* a per-day
# slot: one cell per day, lit when recorded. It cannot be in both — `_beat_css`
# emits an `nth-child` rule per beat, which outranks any whole-set rule on the same
# element, so a trace declaration there would be silently overridden.
SETTLE_TARGETS = (
    ".signal-dots circle",
    ".rhythm-grid i",
    ".film-strip i",
    ".film-grid i",
    ".stars circle",
    ".passport-page .stamp",
    ".dossier-main dl div",
    ".route-points g",
    ".moon-grid i",
)

DRAW_TARGETS = (".signal-path", ".route", ".terrain-map path", ".finger-rings circle")

TRACE_TARGETS = (".generative-art", ".star-lines line")


# The longest stretch any card may hold with nothing moving. Not an arbitrary
# comfort figure: it is the 分析 pause on the longest possible loop, where
# `.analysis-note` has finished revealing and 收束 is waiting for the synthesis
# paragraph — the card's longest text — to be read. Anything beyond that is a
# region that forgot to move, not an act being read. Absolute rather than a
# fraction of `duration_ms`, because the pause is set by reading speed, and a
# shorter loop should shorten the pause rather than keep it proportional.
MAX_STILL_MS = 2600

# The one mode where a long still frame is the content rather than a defect. The
# no-verdict card exists to decline a conclusion, so its 证据 act is a single
# sentence and a breathing ellipsis: the viewer is meant to see the card waiting.
# Listed here rather than waved through in the test so that a later domain wanting
# the same latitude has to add itself and say why — and the exemption is only
# honoured for a mode that really does declare `breathe` and show it.
STILLNESS_IS_AUTHORED = frozenset({"no-verdict"})


# The primitives that put something on screen *for the length of* 证据. Narrower
# than `motion.SERIES_PRIMITIVES`, which also holds `count` because count needs
# data to roll — but a 700ms number roll does not occupy a five-second act, so
# using that set here would classify every card as dense and collapse the spread.
PLOTTED_PRIMITIVES = frozenset({"draw", "settle", "trace"})


# The evidence vocabularies that hold more than one reading, so a stagger has
# something to walk. `.letter-evidence` and `.moon-title p` are deliberately absent:
# they are a single block of prose, so there are no sibling slots to step through.
# `_prose_figure_css` handles them instead, by stepping the figures *inside* the
# sentence — the same idea one level down.
EVIDENCE_SLOTS = (
    ".metrics .metric",
    ".tracklist li",
    ".single-notes dl div",
)

# How many slots a card is assumed to hold at most. Rules past the real child
# count simply never match — the same truncated-cadence tolerance `_beat_css`
# relies on, which is what lets one emitter serve every layout.
MAX_EVIDENCE_SLOTS = 8


def _evidence_slot_count(artboard: str) -> int:
    """How many separate readings this card's evidence region actually holds.

    Counted off the rendered markup rather than assumed, because the step between
    readings has to divide the act the card really has: three metrics stepped as
    if there were eight would finish in the first fifth of 证据 and leave the rest
    of the act still, which is the dead air this stagger exists to remove.
    """
    counts = [
        len(re.findall(r'class="[^"]*\bmetric\b[^"]*"', artboard)),
        len(re.findall(r"<li[ >]", artboard)),
        artboard.count("<dt>"),
    ]
    return min(MAX_EVIDENCE_SLOTS, max(counts))


def _evidence_css(
    start_ms: int, span_ms: int, stagger_ms: int, slots: int, dense: bool
) -> str:
    """Walk the readings one at a time across 证据, and roll each as it lands.

    Two cadences, because the act carries different weight in the two cases. When
    the card also plots a series (`draw`/`settle`/`trace`), the numbers ripple in
    at the seed's own `stagger_ms` and the plotted line carries the rest of the
    act. When it does not — six of the twenty-four modes, plus every zero-data
    card — the readings *are* the act, so they spread across it and each figure
    gets its own moment instead of the whole block landing at once.

    `count` follows the same offsets rather than firing once at the top: a number
    that rolls before it has appeared reads as a glitch, not as a measurement.
    """
    if slots < 2:
        return ""
    step = max(1, int(stagger_ms)) if dense else max(1, int(span_ms) // slots)
    css = []
    for index in range(slots):
        at = max(0, int(start_ms) + step * index)
        reveal = ",".join(
            "#artboard %s:nth-child(%d)" % (part, index + 1) for part in EVIDENCE_SLOTS
        )
        css.append(
            "%s{animation:ms-reveal 520ms both ease-out;animation-delay:%dms;"
            "animation-iteration-count:1}" % (reveal, at)
        )
        count = ",".join(
            "#artboard %s:nth-child(%d) %s" % (part, index + 1, leaf.strip())
            for part in EVIDENCE_SLOTS
            for leaf in ("strong", "b", "dd")
        )
        css.append(
            "%s{animation:ms-count 700ms both ease-out;animation-delay:%dms;"
            "animation-iteration-count:1}" % (count, at + 160)
        )
    return "".join(css)


# The evidence regions that are one block of prose with the figures set inline.
# They have no sibling slots for `_evidence_css` to walk, so the stagger moves
# inside the sentence instead: each `<b>` rolls as the eye reaches it.
PROSE_EVIDENCE = (
    (".letter-evidence", "b"),  # letter A/B: "今天的变化是 <b>…</b>，稳健长期趋势是 <b>…</b>"
    (".moon-title p", "strong"),  # rhythm B: the phase caption, since `.metrics` is hidden
)

# Figures per sentence past which stepping stops being reading and starts being a
# ticker. Two is what the letters actually carry; the ceiling is for later domains
# whose prose may carry more.
MAX_PROSE_FIGURES = 4


def _prose_figure_count(artboard: str) -> int:
    """How many inline figures the prose evidence sentence carries.

    Counted per region and maxed rather than summed: only one prose vocabulary is
    ever present on a card, and a sum would let a stray `<b>` elsewhere stretch the
    cadence past the figures that exist.
    """
    counts = [0]
    for region, leaf in PROSE_EVIDENCE:
        pattern = r'class="[^"]*\b%s\b[^"]*"(.*?)</p>' % re.escape(region.split(".")[-1].split(" ")[0])
        for body in re.findall(pattern, artboard, re.S):
            counts.append(len(re.findall(r"<%s[ >]" % leaf, body)))
    return min(MAX_PROSE_FIGURES, max(counts))


def _prose_figure_css(start_ms: int, span_ms: int, figures: int) -> str:
    """Roll the inline figures one at a time across 证据.

    The letter families are the cards where the act *is* a sentence, so the act
    should advance at reading pace: the first figure lands as the sentence opens,
    the last one near its end. Rolling both at the top would leave the rest of the
    act still on the one card that has no plotted line to carry it.

    Deliberately not a `_evidence_css` special case: that emitter steps sibling
    blocks and this one steps inside a single block, so they select differently and
    read differently. Keeping them apart is what stops either from acquiring a mode
    flag that only one caller ever sets.
    """
    if figures < 2:
        return ""
    step = max(1, int(span_ms) // figures)
    css = []
    for index in range(figures):
        at = max(0, int(start_ms) + step * index)
        selector = ",".join(
            "#artboard %s %s:nth-of-type(%d)" % (region, leaf, index + 1)
            for region, leaf in PROSE_EVIDENCE
        )
        css.append(
            "%s{animation:ms-count 700ms both ease-out;animation-delay:%dms;"
            "animation-iteration-count:1}" % (selector, at)
        )
    return "".join(css)


def _beat_css(beats: Sequence[Mapping[str, object]]) -> str:
    """One rule per recorded day, at its calendar-mapped instant.

    This is where 动画时间轴 = 日历时间轴 becomes literal: a gap in the data is a
    gap in the delay sequence, so a five-day silence is five beats of stillness
    rather than a smoothed-out cadence.
    """
    css = []
    for beat in beats:
        index = int(beat["index"]) + 1
        selector = ",".join(
            "#artboard %s:nth-child(%d)" % (part, index) for part in SETTLE_TARGETS
        )
        css.append(
            "%s{animation:ms-settle 420ms both ease-out;animation-delay:%dms}"
            % (selector, max(0, int(beat["at_ms"])))
        )
    return "".join(css)


def _draw_css(delay_ms: int, duration_ms: int) -> str:
    return (
        "%s{stroke-dasharray:var(--ms-len,2400);"
        "animation:ms-draw %dms both ease-in-out;animation-delay:%dms}"
        % (_scoped(",".join(DRAW_TARGETS)), max(400, int(duration_ms)), max(0, int(delay_ms)))
    )


def _trace_css(delay_ms: int) -> str:
    return (
        "%s{animation:ms-trace 780ms both ease-out;animation-delay:%dms}"
        % (_scoped(",".join(TRACE_TARGETS)), max(0, int(delay_ms)))
    )


def render_story_svg(
    analysis: Mapping[str, object],
    selection: Mapping[str, object],
    *,
    member_name: str = "",
    show_exact_weight: bool = False,
    show_member_name: bool = False,
    show_exact_date: bool = False,
    context_lines: Optional[Sequence[str]] = None,
    frame: Optional[Mapping[str, object]] = None,
    freeze: bool = False,
    domain: str = DEFAULT_DOMAIN,
    lexicon: Optional[Mapping[str, str]] = None,
) -> str:
    """Render an animated 1080×1440 SVG for any registered style.

    `freeze=True` emits the poster frame: the animations are removed, which lands
    on their end state because every keyframe here is authored to terminate at the
    static card's own value.  A screenshot of this file therefore reproduces the
    static composition exactly rather than catching the card mid-motion — see
    `_park_css` for why removing beats seeking-and-pausing.  `frame` accepts a
    precompiled `motion` block; when omitted, one is compiled from the selection's
    seed and the analysis series.

    `domain` and `lexicon` pass straight through to the card renderer and reach no
    motion code at all: the timeline is authored against the nine shapes, not against
    any domain's vocabulary, so a sleep card animates on the same grammar as a weight
    card and only its wording differs.  A caller holding a Signal Frame should pass
    that frame's own `lexicon` so the narration and the animation describe the same
    table rather than two independently-derived ones.
    """
    style = selection.get("selected_style") or {}
    style_id = str(style.get("id") or "")
    if style_id not in STYLES_BY_ID:
        raise ValueError("unknown story-card style: %s" % style_id)

    html = render_weight_story_html(
        analysis, selection,
        member_name=member_name,
        show_exact_weight=show_exact_weight,
        show_member_name=show_member_name,
        show_exact_date=show_exact_date,
        context_lines=context_lines,
        domain=domain,
        lexicon=lexicon,
    )
    parts = _split_document(html)

    if frame is None:
        signature = selection.get("visual_signature") or {}
        # The same points the card draws, so a beat lands on a dot rather than on
        # the third row of a day the trace shows once.  `_beat_css` addresses dots
        # by `nth-child`, so a raw-row series would aim past the end of the trace.
        series = series_source(analysis)
        frame = motion_mod.compile_motion(
            style_id,
            seed=signature.get("texture_seed") or style_id,
            series=series,
            exact_dates=bool(show_exact_date),
        )

    duration_ms = int(frame.get("duration_ms") or motion_mod.DURATION_BOUNDS[0])
    hold_ms = int(frame.get("hold_ms") or 0)
    poster_ms = int(frame.get("poster_time_ms") or duration_ms)
    acts = frame.get("acts") or motion_mod.act_timeline(duration_ms)
    primitives = set(frame.get("primitives") or ())
    beats = frame.get("beats") or []
    evidence = next((a for a in acts if a.get("act") == "evidence"), {"start_ms": 0, "end_ms": duration_ms})

    motion_css = [_keyframes(), _authored_opacity_css(), _act_css(acts, duration_ms, hold_ms)]
    motion_css.append(
        _evidence_css(
            int(evidence["start_ms"]),
            int(evidence["end_ms"]) - int(evidence["start_ms"]),
            int(frame.get("stagger_ms") or 0) or 80,
            _evidence_slot_count(parts["artboard"]),
            dense=bool(primitives & PLOTTED_PRIMITIVES),
        )
    )
    motion_css.append(
        _prose_figure_css(
            int(evidence["start_ms"]),
            int(evidence["end_ms"]) - int(evidence["start_ms"]),
            _prose_figure_count(parts["artboard"]),
        )
    )
    if "settle" in primitives:
        motion_css.append(_beat_css(beats))
    if "draw" in primitives:
        motion_css.append(_draw_css(int(evidence["start_ms"]), int(evidence["end_ms"]) - int(evidence["start_ms"])))
    if "trace" in primitives:
        motion_css.append(_trace_css(int(evidence["start_ms"])))

    # 冻结海报帧: hold every animation at poster_time via a negative delay, then
    # pause. The export side waits for window.__ready, which is only set after
    # this has been applied.
    freeze_css = _park_css(poster_ms)
    # prefers-reduced-motion degrades to the poster frame, per 动作安全约束 —
    # not to a slower animation.
    reduced_css = "@media (prefers-reduced-motion:reduce){%s}" % _park_css(poster_ms)
    if freeze or frame.get("reduced_motion"):
        motion_css.append(freeze_css)
    else:
        motion_css.append(reduced_css)

    return _svg_document(
        parts,
        style_id=style_id,
        frame=frame,
        motion_css="".join(motion_css),
        freeze=bool(freeze or frame.get("reduced_motion")),
        poster_ms=poster_ms,
    )


def _svg_document(
    parts: Mapping[str, str],
    *,
    style_id: str,
    frame: Mapping[str, object],
    motion_css: str,
    freeze: bool,
    poster_ms: int,
) -> str:
    """Assemble the SVG.  No clock, no randomness: byte-identical for equal input."""
    # The artboard is absolutely positioned inside the card's own CSS; inside a
    # foreignObject it must sit at the origin at natural size, since the SVG
    # viewBox already owns the scaling the HTML shell's script used to do.
    # `:root` and not `svg`: the artboard contains inline chart <svg> elements, and
    # a bare `svg` selector would repaint every one of them with the page
    # background — which is how a full-bleed layout loses its own artwork.
    host_css = (
        ":root{background:#F5F0E6}"
        ".ms-host{width:%dpx;height:%dpx;overflow:hidden}"
        ".ms-host #artboard{position:relative;transform:none;margin:0}"
    ) % (CARD_WIDTH, CARD_HEIGHT)

    # window.__ready gates PNG export: it is set only after animations are
    # actually parked at the poster time, so a screenshot can never race the
    # timeline. pauseAnimations() covers SMIL; the CSS above covers WAAPI.
    ready_script = (
        '<script type="application/ecmascript"><![CDATA['
        "(()=>{const s=document.documentElement;"
        "const park=()=>{try{s.pauseAnimations&&s.pauseAnimations();"
        "s.setCurrentTime&&s.setCurrentTime(%(poster)f)}catch(e){}"
        "window.__ready=true};"
        "%(body)s})()"
        "]]></script>"
    ) % {
        "poster": poster_ms / 1000.0,
        "body": (
            "if(document.fonts&&document.fonts.ready){document.fonts.ready.then(park)}"
            "else{park()}" if freeze else "window.__ready=true"
        ),
    }

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        # xml:lang carries the card's own language: font fallback for CJK depends
        # on it, and losing it changes the line metrics of every Chinese run.
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xhtml="http://www.w3.org/1999/xhtml" '
        'xml:lang="%(lang)s" width="%(w)d" height="%(h)d" viewBox="0 0 %(w)d %(h)d" '
        'data-style-id="%(style)s" data-motion-mode="%(mode)s" '
        'data-duration-ms="%(duration)d" data-poster-time-ms="%(poster)d" '
        'data-freeze="%(freeze)s" data-renderer="story-svg-v1">\n'
        "<style><![CDATA[%(host_css)s\n%(card_css)s\n%(motion_css)s]]></style>\n"
        '<foreignObject x="0" y="0" width="%(w)d" height="%(h)d">\n'
        # The default namespace must switch to XHTML *here*, not via a prefix on
        # this element alone: unprefixed descendants inherit the default
        # namespace, so with only xmlns:xhtml the whole artboard would land in
        # the SVG namespace and lay out as nothing.
        # A real <body>, not a <div>: the card's stylesheet styles `body` directly
        # (background, colour, font stack), and those declarations have to keep
        # applying or the poster frame drifts from the static card.
        '<body xmlns="http://www.w3.org/1999/xhtml" xml:lang="%(lang)s" '
        'class="ms-host" %(body_attrs)s>'
        "%(artboard)s</body>\n"
        "</foreignObject>\n%(script)s\n</svg>\n"
    ) % {
        "w": CARD_WIDTH,
        "h": CARD_HEIGHT,
        "lang": parts["lang"],
        "style": style_id,
        "mode": str(frame.get("motion_mode") or ""),
        "duration": int(frame.get("duration_ms") or 0),
        "poster": poster_ms,
        "freeze": "true" if freeze else "false",
        "host_css": host_css,
        "card_css": parts["css"],
        "motion_css": motion_css,
        "body_attrs": parts["body_attrs"],
        "artboard": parts["artboard"],
        "script": ready_script,
    }
