"""Take a screenshot of an HTML file using Chrome headless + Pillow auto-crop.

Usage:
  python3 html_screenshot.py <input.html> [output.png] [--width 960]

Outputs JSON: {"status": "ok", "image_path": "...", "width": ..., "height": ...}
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent.parent


def _story_export():
    """Import shared.story.export, adding the repo root to sys.path if needed.

    This script is executed directly as well as imported, so the root is not
    guaranteed to be importable already.
    """
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    import importlib

    return importlib.import_module("shared.story.export")


def _strip_external_scripts(html_path: str) -> str:
    """Create a temp copy of the HTML with external <script src=...> tags removed.

    This prevents Chrome from hanging when CDN hosts are unreachable.
    Canvas elements that relied on those scripts will simply render as
    empty boxes, which is acceptable for a static screenshot.

    Returns the path to the temp file (caller should delete it).
    """
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # Remove <script src="https://...">...</script> tags
    cleaned = re.sub(
        r'<script\s+[^>]*src\s*=\s*["\']https?://[^"\']+["\'][^>]*>.*?</script>',
        '',
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    if cleaned == html:
        # No external scripts found, use original file directly
        return html_path

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".html", prefix="screenshot_")
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        f.write(cleaned)
    return tmp_path


def screenshot(html_path: str, output_path: str | None = None, width: int = 960) -> dict:
    """Render an HTML file to a PNG image.

    Uses google-chrome in headless mode to capture the page, then uses
    Pillow to auto-crop trailing blank space.

    Args:
        html_path: Absolute path to the HTML file.
        output_path: Where to save the PNG. Defaults to same dir as HTML with .png ext.
        width: Viewport width in pixels.

    Returns:
        dict with status, image_path, width, height.
    """
    if not os.path.isfile(html_path):
        return {"status": "error", "error": f"File not found: {html_path}"}

    if output_path is None:
        output_path = os.path.splitext(html_path)[0] + ".png"

    # Pre-process: strip external scripts to avoid CDN timeouts
    render_path = _strip_external_scripts(html_path)
    tmp_created = render_path != html_path

    try:
        return _do_screenshot(render_path, output_path, width)
    finally:
        if tmp_created and os.path.isfile(render_path):
            os.unlink(render_path)


def _do_screenshot(render_path: str, output_path: str, width: int) -> dict:
    """Internal: run Chrome and crop the result."""
    # Use a tall viewport so the whole page fits in one frame
    viewport_height = 5000

    # Chrome headless screenshot
    chrome_binary = find_chrome()
    if not chrome_binary:
        return {"status": "error", "error": "Chrome/Chromium not found"}

    # Story cards park their animations and only then set window.__ready.  Waiting
    # for a settled frame is the motion layer's concern, so the flags come from
    # shared/story/export.py rather than being duplicated here.
    chrome_cmd = _story_export().chrome_command(
        chrome_binary,
        Path(render_path).resolve().as_uri(),
        output_path,
        width=width,
        height=viewport_height,
        extra_flags=("--disable-software-rasterizer",),
    )

    try:
        result = subprocess.run(
            chrome_cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        return {"status": "error", "error": "Chrome/Chromium not found"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Chrome screenshot timed out"}

    if not os.path.isfile(output_path):
        stderr = result.stderr[:500] if result.stderr else ""
        return {"status": "error", "error": f"Screenshot failed: {stderr}"}

    # Auto-crop trailing blank space using Pillow
    try:
        from PIL import Image

        img = Image.open(output_path)

        # Find the bottom boundary of actual content.
        # Scan from the bottom up, looking for rows that aren't the
        # background color (the page bg is #F3F7FC ≈ rgb(243,247,252)).
        pixels = img.load()
        w, h = img.size
        bg_threshold = 10  # tolerance for "close to background color"
        bg_r, bg_g, bg_b = 243, 247, 252

        bottom = h
        for y in range(h - 1, 0, -1):
            row_is_blank = True
            # Sample pixels across the row (check every 10th pixel for speed)
            for x in range(0, w, 10):
                r, g, b = pixels[x, y][:3]
                if (abs(r - bg_r) > bg_threshold or
                        abs(g - bg_g) > bg_threshold or
                        abs(b - bg_b) > bg_threshold):
                    row_is_blank = False
                    break
            if not row_is_blank:
                bottom = min(y + 30, h)  # 30px padding below content
                break

        if bottom < h:
            img = img.crop((0, 0, w, bottom))
            img.save(output_path, "PNG", optimize=True)

        final_w, final_h = img.size
        file_size = os.path.getsize(output_path)
        img.close()

        return {
            "status": "ok",
            "image_path": output_path,
            "width": final_w,
            "height": final_h,
            "file_size": file_size,
        }

    except ImportError:
        # Pillow not available — return the uncropped screenshot
        file_size = os.path.getsize(output_path)
        return {
            "status": "ok",
            "image_path": output_path,
            "width": width,
            "height": viewport_height,
            "file_size": file_size,
            "note": "Pillow not installed, image not cropped",
        }
    except Exception as e:
        # Cropping failed, but raw screenshot exists
        file_size = os.path.getsize(output_path)
        return {
            "status": "ok",
            "image_path": output_path,
            "width": width,
            "height": viewport_height,
            "file_size": file_size,
            "note": f"Auto-crop failed: {e}",
        }


def find_chrome() -> str | None:
    """Locate Chrome/Chromium on Linux, macOS, or Windows.

    One implementation, in shared/story/export.py, so the card renderer and this
    generic screenshot helper can never disagree about which binary is used.
    """
    return _story_export().find_chrome()


# Backward-compatible alias for callers that imported the former private helper.
_find_chrome = find_chrome


def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "error": "Usage: html_screenshot.py <input.html> [output.png] [--width 960]"
        }))
        sys.exit(1)

    html_path = sys.argv[1]
    output_path = None
    width = 960

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--width" and i + 1 < len(sys.argv):
            width = int(sys.argv[i + 1])
            i += 2
        elif not sys.argv[i].startswith("--"):
            output_path = sys.argv[i]
            i += 1
        else:
            i += 1

    result = screenshot(html_path, output_path, width)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
