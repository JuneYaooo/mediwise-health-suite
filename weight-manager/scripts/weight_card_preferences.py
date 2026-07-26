"""Private local preference memory for weight-card presentation styles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Iterable, Optional


import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))
from path_setup import setup_mediwise_path

setup_mediwise_path()

from config import DATA_DIR
from health_db import output_json

from _story_bootstrap import story_module

STYLES_BY_ID = story_module("catalog").STYLES_BY_ID


PROFILE_VERSION = 1
DEFAULT_FILENAME = "weight-card-preferences.json"
VALID_TONES = ("auto", "gentle", "calm", "playful", "editorial", "bold")
VALID_DENSITIES = ("auto", "concise", "detailed")


def _default_profile() -> dict:
    return {
        "tone": "auto",
        "density": "auto",
        "surprise_level": 0.5,
        "preferred_styles": [],
        "disliked_styles": [],
        "pinned_style": None,
        "recent_styles": [],
        "generation_count": 0,
    }


def _member_key(member_id: object) -> str:
    return hashlib.sha256(str(member_id or "anonymous").encode("utf-8")).hexdigest()


def _store_path(path: Optional[str] = None) -> Path:
    return Path(path or os.path.join(DATA_DIR, DEFAULT_FILENAME)).expanduser().resolve()


def _read_store(path: Optional[str] = None) -> dict:
    target = _store_path(path)
    if not target.exists():
        return {"version": PROFILE_VERSION, "members": {}}
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": PROFILE_VERSION, "members": {}}
    if not isinstance(value, dict) or not isinstance(value.get("members"), dict):
        return {"version": PROFILE_VERSION, "members": {}}
    return value


def _write_store(value: dict, path: Optional[str] = None) -> Path:
    target = _store_path(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=str(target.parent), prefix=".weight-card-", delete=False
    )
    temp_name = handle.name
    try:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, target)
        os.chmod(target, 0o600)
    except Exception:
        handle.close()
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return target


def get_style_profile(member_id: object, path: Optional[str] = None) -> dict:
    store = _read_store(path)
    saved = store["members"].get(_member_key(member_id), {})
    profile = _default_profile()
    if isinstance(saved, dict):
        profile.update({key: value for key, value in saved.items() if key in profile})
    profile["preferred_styles"] = [
        item for item in profile.get("preferred_styles", []) if item in STYLES_BY_ID
    ]
    profile["disliked_styles"] = [
        item for item in profile.get("disliked_styles", []) if item in STYLES_BY_ID
    ]
    profile["recent_styles"] = [
        item for item in profile.get("recent_styles", []) if item in STYLES_BY_ID
    ][-6:]
    if profile.get("pinned_style") not in STYLES_BY_ID:
        profile["pinned_style"] = None
    if profile.get("tone") not in VALID_TONES:
        profile["tone"] = "auto"
    if profile.get("density") not in VALID_DENSITIES:
        profile["density"] = "auto"
    profile["surprise_level"] = min(max(float(profile.get("surprise_level", 0.5)), 0.0), 1.0)
    profile["generation_count"] = max(int(profile.get("generation_count", 0)), 0)
    return profile


def update_style_profile(
    member_id: object,
    *,
    tone: Optional[str] = None,
    density: Optional[str] = None,
    surprise_level: Optional[float] = None,
    like_styles: Optional[Iterable[str]] = None,
    dislike_styles: Optional[Iterable[str]] = None,
    neutral_styles: Optional[Iterable[str]] = None,
    pinned_style: Optional[str] = None,
    clear_pin: bool = False,
    generated_style: Optional[str] = None,
    clear_history: bool = False,
    path: Optional[str] = None,
) -> dict:
    if tone is not None and tone not in VALID_TONES:
        raise ValueError("invalid tone: %s" % tone)
    if density is not None and density not in VALID_DENSITIES:
        raise ValueError("invalid density: %s" % density)
    style_inputs = list(like_styles or []) + list(dislike_styles or []) + list(neutral_styles or [])
    if pinned_style:
        style_inputs.append(pinned_style)
    if generated_style:
        style_inputs.append(generated_style)
    unknown = sorted({item for item in style_inputs if item not in STYLES_BY_ID})
    if unknown:
        raise ValueError("unknown styles: %s" % ", ".join(unknown))

    store = _read_store(path)
    key = _member_key(member_id)
    profile = get_style_profile(member_id, path)
    if tone is not None:
        profile["tone"] = tone
    if density is not None:
        profile["density"] = density
    if surprise_level is not None:
        profile["surprise_level"] = min(max(float(surprise_level), 0.0), 1.0)

    preferred = set(profile["preferred_styles"])
    disliked = set(profile["disliked_styles"])
    for style_id in like_styles or []:
        preferred.add(style_id)
        disliked.discard(style_id)
    for style_id in dislike_styles or []:
        disliked.add(style_id)
        preferred.discard(style_id)
    for style_id in neutral_styles or []:
        preferred.discard(style_id)
        disliked.discard(style_id)
    profile["preferred_styles"] = sorted(preferred)
    profile["disliked_styles"] = sorted(disliked)

    if clear_pin:
        profile["pinned_style"] = None
    elif pinned_style is not None:
        profile["pinned_style"] = pinned_style
    if clear_history:
        profile["recent_styles"] = []
        profile["generation_count"] = 0
    if generated_style:
        profile["recent_styles"] = (profile["recent_styles"] + [generated_style])[-6:]
        profile["generation_count"] += 1

    store["version"] = PROFILE_VERSION
    store.setdefault("members", {})[key] = profile
    target = _write_store(store, path)
    return {
        "profile": profile,
        "storage": {
            "path": str(target),
            "member_id_hashed": True,
            "health_values_stored": False,
            "file_mode": "0600",
        },
    }


def _parser(command: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--member-id", required=True)
    parser.add_argument("--store-path")
    if command == "update":
        parser.add_argument("--tone", choices=VALID_TONES)
        parser.add_argument("--density", choices=VALID_DENSITIES)
        parser.add_argument("--surprise-level", type=float)
        parser.add_argument("--like-style", action="append", default=[])
        parser.add_argument("--dislike-style", action="append", default=[])
        parser.add_argument("--neutral-style", action="append", default=[])
        parser.add_argument("--pin-style")
        parser.add_argument("--clear-pin", action="store_true")
        parser.add_argument("--generated-style")
        parser.add_argument("--clear-history", action="store_true")
    return parser


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("get", "update"):
        output_json({"status": "error", "message": "Usage: weight_card_preferences.py get|update [options]"})
        return
    command = sys.argv[1]
    args = _parser(command).parse_args(sys.argv[2:])
    try:
        if command == "get":
            result = {"profile": get_style_profile(args.member_id, args.store_path)}
        else:
            result = update_style_profile(
                args.member_id,
                tone=args.tone,
                density=args.density,
                surprise_level=args.surprise_level,
                like_styles=args.like_style,
                dislike_styles=args.dislike_style,
                neutral_styles=args.neutral_style,
                pinned_style=args.pin_style,
                clear_pin=args.clear_pin,
                generated_style=args.generated_style,
                clear_history=args.clear_history,
                path=args.store_path,
            )
        output_json({"status": "ok", **result})
    except (OSError, ValueError) as exc:
        output_json({"status": "error", "message": str(exc)})


if __name__ == "__main__":
    main()
