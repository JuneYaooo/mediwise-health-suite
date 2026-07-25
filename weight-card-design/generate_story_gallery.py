#!/usr/bin/env python3
"""Generate and browser-QA all 24 dynamic 体重译报 styles.

This is a design/development helper, not a runtime dependency.  It uses a
fictional 30-day dataset, writes self-contained HTML files, screenshots each
at 1080×1440, checks browser errors and canvas bounds, and optionally creates
12-family and full 24-template contact sheets for the README.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT_DIR = ROOT / "weight-manager" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import weight_truth_card
from weight_card_styles import STYLE_CATALOG
from weight_management_analysis import analyze_weight_management
from weight_story_card import render_weight_story_html
from weight_style_selector import select_weight_card_style


def demo_analysis() -> dict:
    start = date(2026, 6, 20)
    values = [72.0 - index * 0.045 + (0.16 if index % 5 == 0 else 0.0) for index in range(30)]
    records = [
        {"value": value, "measured_at": (start + timedelta(days=index)).isoformat() + " 08:00:00"}
        for index, value in enumerate(values)
    ]
    analysis = weight_truth_card.analyze_weight_records(records, days=30)
    as_of = start + timedelta(days=29)
    diet, exercise, sleep = weight_truth_card._demo_management_records(as_of, 30)
    analysis["management"] = analyze_weight_management(
        analysis, diet, exercise, sleep, days=30, as_of=as_of
    )
    return analysis


def build_gallery(
    images,
    output: Path,
    *,
    columns: int = 4,
    thumb_width: int = 324,
    thumb_height: int = 432,
    gap: int = 24,
    label_height: int = 46,
    font_size: int = 18,
) -> None:
    from PIL import Image, ImageDraw, ImageFont

    rows = (len(images) + columns - 1) // columns
    canvas = Image.new(
        "RGB",
        (columns * thumb_width + (columns + 1) * gap, rows * (thumb_height + label_height) + (rows + 1) * gap),
        "#D9E0DF",
    )
    draw = ImageDraw.Draw(canvas)
    font_candidates = (
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    )
    font = next(
        (ImageFont.truetype(candidate, font_size) for candidate in font_candidates if Path(candidate).exists()),
        ImageFont.load_default(size=font_size),
    )
    for index, (label, path) in enumerate(images):
        row, column = divmod(index, columns)
        x = gap + column * (thumb_width + gap)
        y = gap + row * (thumb_height + label_height + gap)
        image = Image.open(path).convert("RGB").resize((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        canvas.paste(image, (x, y))
        draw.multiline_text(
            (x, y + thumb_height + 9),
            label,
            fill="#0A2F55",
            font=font,
            spacing=4,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, quality=92)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--gallery", help="write the 12-family representative contact sheet")
    parser.add_argument("--full-gallery", help="write the full 24-template A/B contact sheet")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    analysis = demo_analysis()

    html_paths = []
    representative = []
    complete_collection = []
    for style in STYLE_CATALOG:
        selection = select_weight_card_style(
            analysis, scene="share", pinned_style=style.id, seed="gallery-" + style.id
        )
        rendered = render_weight_story_html(
            analysis,
            selection,
        )
        path = output / (style.id + ".html")
        path.write_text(rendered, encoding="utf-8")
        html_paths.append((style, path))

    from playwright.sync_api import sync_playwright

    chrome = weight_truth_card._find_chrome()
    errors = []
    with sync_playwright() as playwright:
        launch = {"headless": True}
        if chrome:
            launch["executable_path"] = chrome
        browser = playwright.chromium.launch(**launch)
        page = browser.new_page(viewport={"width": 1080, "height": 1440}, device_scale_factor=1)
        current = {"style": ""}
        page.on("console", lambda message: errors.append({"style": current["style"], "type": "console", "text": message.text}) if message.type == "error" else None)
        page.on("pageerror", lambda error: errors.append({"style": current["style"], "type": "pageerror", "text": str(error)}))
        for style, html_path in html_paths:
            current["style"] = style.id
            page.goto(html_path.as_uri(), wait_until="load")
            page.wait_for_function("window.__ready === true")
            bounds = page.evaluate("""() => {
              const a=document.getElementById('artboard'), r=a.getBoundingClientRect();
              return {w:a.offsetWidth,h:a.offsetHeight,scrollW:a.scrollWidth,scrollH:a.scrollHeight,
                      bodyW:document.body.scrollWidth,bodyH:document.body.scrollHeight,
                      rectW:r.width,rectH:r.height};
            }""")
            if bounds["w"] != 1080 or bounds["h"] != 1440 or bounds["scrollW"] != 1080 or bounds["scrollH"] != 1440:
                errors.append({"style": style.id, "type": "bounds", "text": json.dumps(bounds)})
            png_path = output / (style.id + ".png")
            page.screenshot(path=str(png_path))
            complete_collection.append(
                (
                    f"{len(complete_collection) + 1:02d} · {style.family_name} · {style.variant}\n{style.name}",
                    png_path,
                )
            )
            if style.variant == "A":
                representative.append((style.family_name, png_path))
        browser.close()

    report = {
        "styles": len(html_paths),
        "width": 1080,
        "height": 1440,
        "errors": errors,
    }
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.gallery:
        build_gallery(representative, Path(args.gallery).resolve())
    if args.full_gallery:
        build_gallery(
            complete_collection,
            Path(args.full_gallery).resolve(),
            columns=6,
            thumb_width=216,
            thumb_height=288,
            gap=18,
            label_height=58,
            font_size=15,
        )
    print(json.dumps(report, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
