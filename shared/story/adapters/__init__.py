"""Per-domain adapters: the only place a health domain is named.

An adapter turns one domain's raw records into a Signal Frame
(story-design/signal-frame.schema.json).  Adding a domain means adding one
module here plus a ~20-line lexicon — never a new template or a new copy file.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Tuple

from . import activity, adherence, family, intake, records, sleep, vitals, weight

DEFAULT_DOMAIN = "weight"

_REGISTRY: Dict[str, object] = {
    weight.DOMAIN: weight,
    records.DOMAIN: records,
    sleep.DOMAIN: sleep,
    vitals.DOMAIN: vitals,
    intake.DOMAIN: intake,
    activity.DOMAIN: activity,
    adherence.DOMAIN: adherence,
    family.DOMAIN: family,
}


def available_domains() -> List[str]:
    """Return registered domain ids, stable order for reproducible output."""
    return sorted(_REGISTRY)


def get_adapter(domain: str = DEFAULT_DOMAIN):
    """Return the adapter module for `domain`.

    Raises ValueError rather than silently falling back, so a caller asking for
    an unimplemented domain gets an explicit error instead of a weight card.
    """
    try:
        return _REGISTRY[domain]
    except KeyError:
        raise ValueError(
            "未接入的域：%s；当前可用：%s" % (domain, "、".join(available_domains()))
        ) from None


def lexicon_for(domain: str = DEFAULT_DOMAIN) -> Mapping[str, str]:
    """Return the wording table templates must read instead of hardcoding nouns."""
    return get_adapter(domain).LEXICON


def component_key_for(domain: str = DEFAULT_DOMAIN) -> str:
    """Which analysis key names the component this domain's card is about.

    Empty for the five single-component domains: a weight card is about weight, so
    there is nothing to pick.  The three that narrate one component of several
    (vitals, intake, activity) each declare their own key, because the key travels
    in the analysis dict that hosts pass around and a central table of
    domain->key would be a second spelling of a name the adapter already owns.
    """
    return str(getattr(get_adapter(domain), "COMPONENT_KEY", "") or "")


def component_for(domain: str = DEFAULT_DOMAIN, analysis: Mapping[str, object] | None = None) -> str:
    """Return the component of `domain` that `analysis` turned out to be about.

    Empty for domains with only one component.  Delegating rather than
    reimplementing: each adapter decides whether an absent explicit pick may be
    inferred from the rows at all — vitals infers, activity deliberately does not.
    """
    adapter = get_adapter(domain)
    reader = getattr(adapter, "component_for", None)
    if reader is None:
        return ""
    return str(reader(dict(analysis or {})))


def lexicon_for_analysis(
    domain: str = DEFAULT_DOMAIN, analysis: Mapping[str, object] | None = None
) -> Mapping[str, str]:
    """Return the wording for the component this particular window is about.

    `lexicon_for` answers for the domain; this answers for the analysis.  The two
    differ only for the multi-component domains, and there the difference is the
    whole point: printing 心率 / 次/分 over a window of systolic readings is a leak
    inside the domain, one no cross-domain vocabulary check would catch, because
    every word on the card is a legitimate vitals word.
    """
    adapter = get_adapter(domain)
    reader = getattr(adapter, "lexicon_for_analysis", None)
    if reader is None:
        return adapter.LEXICON
    return reader(dict(analysis or {}))


# The lexicon fills the subject slot: 体重译报 / 睡眠译报 / 记录译报.  It lives here
# rather than in `render` because both the renderer and the CLI envelope build the
# name from it, and a second spelling of the template is a second thing to drift.
PRODUCT_NAME_TEMPLATE = "MediWise %s译报"


def product_name_for(domain: str = DEFAULT_DOMAIN) -> str:
    """Return the card name built from the same domain subject the renderer reads."""
    return PRODUCT_NAME_TEMPLATE % lexicon_for(domain)["subject"]


# Slots an authored copy string may carry.  Kept explicit rather than derived from
# a lexicon so a typo'd slot stays visible in output instead of silently resolving
# to an empty string.  `today` is not a lexicon key: it is filled at render time
# with whichever direction word the newest reading earned.
COPY_SLOTS = ("subject", "reading", "unit", "up", "down", "today", "series_label", "scope_label")


def fill_slots(text: str, lexicon: Mapping[str, str]) -> str:
    """Substitute `{slot}` tokens in authored copy with this domain's wording.

    Lives beside `lexicon_for` because the slot names are the lexicon's own keys,
    and because both the selector and the renderers need it — putting it in either
    one would make the other import it across a layer it should not know about.

    Deliberately not `str.format`: the copy tables contain literal braces in no
    place today, but `format` would also choke on any future CSS or JSON in a copy
    string, and it raises on an unknown slot where plain replacement leaves the
    token visible for a test to catch.
    """
    if "{" not in text:
        return text
    for slot in COPY_SLOTS:
        token = "{%s}" % slot
        if token in text:
            text = text.replace(token, str(lexicon.get(slot, "")))
    return text


# What the disclaimer promises not to produce.  This cannot live in `LEXICON`:
# the Signal Frame schema closes that object at eight keys, and the word is not
# frame data — it is a legal boundary the renderer states about the domain.  So
# it is an optional module attribute, neutral unless an adapter narrows it.
DEFAULT_PRESCRIPTION_NOUN = "处理方案"


def prescription_noun_for(domain: str = DEFAULT_DOMAIN) -> str:
    """Return the domain's word for the advice this product never gives."""
    return getattr(get_adapter(domain), "PRESCRIPTION_NOUN", DEFAULT_PRESCRIPTION_NOUN)


# What a card says when it has no companion axis at all — no intake, activity or
# sleep records to set the subject beside.  Every template reaches this copy, so it
# is the one paragraph guaranteed to print, which is why it may not enumerate
# domains: naming 摄入、运动与睡眠 here put the word 睡眠 on all 48 weight and
# records cards, and on a records card those three are signals it knows nothing
# about.  The rule the wording follows is the general one — a card may name a
# companion domain only while reporting that companion's actual records.
#
# `{subject}` is filled from the caller's lexicon, so the default reads correctly
# for a domain the adapter author never anticipated.  "这一路数据" rather than
# "这一路记录" because records' own subject is 记录 and the pairing stuttered.
DEFAULT_NO_COMPANION_COPY = {
    "headline": "{subject}之外的同期记录还在积累",
    "paragraph": "目前只有{subject}这一路数据；同期还没有其他信号可以对照，因此这张卡不把单一数字解释成原因。",
}


def no_companion_copy_for(domain: str = DEFAULT_DOMAIN) -> Dict[str, str]:
    """Return the headline and paragraph for a card with no companion records.

    An adapter overriding this owns both halves rather than merging one into the
    default: the two sentences are read together, and a headline written for one
    paragraph beside a different paragraph is how copy stops making sense.
    """
    authored = getattr(get_adapter(domain), "NO_COMPANION_COPY", None) or {}
    return {
        "headline": str(authored.get("headline") or DEFAULT_NO_COMPANION_COPY["headline"]),
        "paragraph": str(authored.get("paragraph") or DEFAULT_NO_COMPANION_COPY["paragraph"]),
    }


def companions_for(domain: str = DEFAULT_DOMAIN) -> Tuple[str, ...]:
    """Which other domains this one is entitled to name on its card.

    A card may name a companion domain only while it is reporting that companion's
    actual records, and this is the half of that rule an adapter owns: whether the
    relationship exists at all.  Weight declares 摄入、运动、睡眠 because the lifestyle
    databases hold exactly those three, so a weight card with none of them is
    specifically missing them and saying "睡眠记录 0 天" is a coverage disclosure.  A
    records card has no companion axis, so the same sentence would assert a
    relationship its schema does not have -- it would be reporting on a signal it
    knows nothing about, which is the thing the product refuses to do.

    Default is empty: a new adapter names nothing but itself until its author says
    which companions it actually reads.  The 12 companion-emphasis templates fall
    back to their own-subject wording for those domains rather than dropping out, so
    every domain keeps all 24.
    """
    declared = getattr(get_adapter(domain), "COMPANIONS", ()) or ()
    return tuple(str(name) for name in declared)


def latin_tag_for(domain: str = DEFAULT_DOMAIN) -> str:
    """Return the all-caps Latin tag some layouts stamp on the card.

    A few templates use a Latin tag as ornament (the case-file folder's tab, for
    one) where CJK at that weight and letter-spacing would not read.  Adapters that
    do not supply one fall back to the domain key, which is already ASCII.
    """
    return str(getattr(get_adapter(domain), "LATIN_TAG", "") or domain).upper()


def register(module) -> None:
    """Register an adapter module.  Used by tests and future domain packages."""
    domain = getattr(module, "DOMAIN", "")
    if not domain:
        raise ValueError("adapter 缺少 DOMAIN")
    for required in ("LEXICON", "SHAPE_BY_STATE", "shape_for"):
        if not hasattr(module, required):
            raise ValueError("adapter %s 缺少 %s" % (domain, required))
    _REGISTRY[domain] = module


__all__ = [
    "COPY_SLOTS",
    "DEFAULT_DOMAIN",
    "DEFAULT_NO_COMPANION_COPY",
    "DEFAULT_PRESCRIPTION_NOUN",
    "available_domains",
    "companions_for",
    "component_for",
    "component_key_for",
    "fill_slots",
    "get_adapter",
    "latin_tag_for",
    "lexicon_for",
    "lexicon_for_analysis",
    "no_companion_copy_for",
    "prescription_noun_for",
    "product_name_for",
    "register",
]
