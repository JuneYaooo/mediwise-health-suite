"""Poster-frame PNG export: the one place that knows how to wait for a card.

Both the static HTML card and the animated SVG set `window.__ready = true` only
after the composition is actually parked — fonts resolved, animations held at
`poster_time`.  A screenshot taken before that flag is a race: with animation in
play it captures whatever frame the renderer happened to be on, which is exactly
how a locked golden digest turns non-deterministic.

Two capture strategies, in order of fidelity:

1. **Playwright** — genuinely waits on `window.__ready === true`, then shoots.
   This is the only path that observes the flag, so it is preferred whenever the
   package is importable.
2. **Chrome headless + `--virtual-time-budget`** — no flag observation, but
   virtual time advances timers, fonts, and animation parking to completion
   before the frame is drawn, rather than sleeping on the wall clock.  Chrome
   holds the screenshot until the budget is exhausted or the page goes idle, so
   the captured frame is the settled one.

See story-design/story-system.md (冻结海报帧).
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Mapping, Optional, Sequence

READY_EXPRESSION = "window.__ready === true"

# Generous enough to cover the longest loop (12 s) plus the trailing hold, since
# virtual time is not wall-clock time: a larger budget costs nothing when the
# page settles early.
VIRTUAL_TIME_BUDGET_MS = 20000

# Wall-clock ceilings. These are process guards, not timing assumptions.
CHROME_TIMEOUT_S = 30
READY_TIMEOUT_MS = 15000

_CHROME_COMMANDS = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "chrome",
)

_CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
    r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
)


def find_chrome() -> Optional[str]:
    """Locate Chrome/Chromium on Linux, macOS, or Windows."""
    for command in _CHROME_COMMANDS:
        resolved = shutil.which(command)
        if resolved:
            return resolved
    for candidate in _CHROME_PATHS:
        expanded = os.path.expandvars(candidate)
        if expanded and os.path.isfile(expanded):
            return expanded
    return None


def chrome_command(
    chrome: str,
    url: str,
    output_path: str,
    *,
    width: int,
    height: int,
    virtual_time_budget_ms: int = VIRTUAL_TIME_BUDGET_MS,
    extra_flags: Sequence[str] = (),
) -> list:
    """Headless flags that make the capture wait for a settled frame.

    `--virtual-time-budget` is the load-bearing one: without it Chrome shoots as
    soon as load fires, which for an animated card means an arbitrary frame.
    `--run-all-compositor-stages-before-draw` keeps the compositor from
    presenting a partially-composited frame.
    """
    return [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--hide-scrollbars",
        "--disable-background-networking",
        "--force-device-scale-factor=1",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=%d" % max(0, int(virtual_time_budget_ms)),
        *list(extra_flags),
        "--window-size=%d,%d" % (int(width), int(height)),
        "--screenshot=%s" % output_path,
        url,
    ]


def png_dimensions(path: str) -> Optional[tuple]:
    """Read width/height straight from the IHDR chunk."""
    try:
        with open(path, "rb") as handle:
            header = handle.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", header[16:24])
    except (OSError, struct.error):
        return None


def _unavailable(message: str, **extra) -> dict:
    result = {"status": "unavailable", "message": message}
    result.update(extra)
    return result


def _capture_with_playwright(
    url: str, output_path: str, *, width: int, height: int, chrome_binary: Optional[str]
) -> Optional[dict]:
    """Wait on the ready flag, then shoot.  Returns None if Playwright is absent."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as playwright:
            launch = {"headless": True}
            if chrome_binary:
                launch["executable_path"] = chrome_binary
            browser = playwright.chromium.launch(**launch)
            try:
                page = browser.new_page(
                    viewport={"width": int(width), "height": int(height)},
                    device_scale_factor=1,
                )
                page.goto(url, wait_until="load")
                # The contract's actual requirement: do not capture until the
                # renderer says the frame is parked.
                page.wait_for_function(READY_EXPRESSION, timeout=READY_TIMEOUT_MS)
                page.screenshot(path=output_path)
            finally:
                browser.close()
    except Exception as exc:  # noqa: BLE001 - any launch/driver failure falls back
        return _unavailable("Playwright 捕获失败：%s" % exc, waited_for_ready=False)
    return {"status": "ok", "waited_for_ready": True, "capture": "playwright"}


def _capture_with_chrome(
    url: str, output_path: str, *, width: int, height: int, chrome_binary: Optional[str]
) -> dict:
    chrome = chrome_binary or find_chrome()
    if not chrome:
        return _unavailable("未找到 Chrome/Chromium，HTML 已正常生成", waited_for_ready=False)
    command = chrome_command(chrome, url, output_path, width=width, height=height)
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=CHROME_TIMEOUT_S
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return _unavailable("PNG 渲染不可用：%s" % exc, waited_for_ready=False)
    if completed.returncode != 0 or not os.path.isfile(output_path):
        detail = (completed.stderr or "Chrome screenshot failed")[:400]
        return _unavailable(detail, waited_for_ready=False)
    # Virtual time settles the frame but never reports the flag back to us.
    return {"status": "ok", "waited_for_ready": False, "capture": "chrome-virtual-time"}


def capture_poster_png(
    source_path: str,
    output_path: str,
    *,
    width: int,
    height: int,
    chrome_binary: Optional[str] = None,
    expect_exact_size: bool = True,
) -> dict:
    """Capture the settled poster frame of an HTML or SVG card.

    Returns `{"status": "unavailable", ...}` rather than raising when no renderer
    is installed: a missing Chrome must not fail the HTML/SVG output the caller
    has already produced.
    """
    # `None` means "find a renderer"; `""` means "there is no renderer" — the
    # caller has already decided, so honour it instead of auto-detecting one
    # behind their back.  Callers rely on this to exercise the degraded path.
    if chrome_binary == "":
        return _unavailable("未找到 Chrome/Chromium，HTML 已正常生成", waited_for_ready=False)

    url = Path(source_path).resolve().as_uri()
    # Resolve the binary once and hand it to Playwright too: a Playwright install
    # without its bundled browser is common, and the system Chrome is a perfectly
    # good driver target — that keeps the ready-flag path available instead of
    # silently degrading to virtual time.
    chrome = chrome_binary or find_chrome()
    outcome = _capture_with_playwright(
        url, output_path, width=width, height=height, chrome_binary=chrome
    )
    if outcome is None or outcome.get("status") != "ok":
        outcome = _capture_with_chrome(
            url, output_path, width=width, height=height, chrome_binary=chrome
        )
    if outcome.get("status") != "ok":
        return outcome

    dimensions = png_dimensions(output_path)
    if expect_exact_size and dimensions != (int(width), int(height)):
        try:
            os.unlink(output_path)
        except OSError:
            pass
        return _unavailable("PNG 尺寸异常：%s" % (dimensions,), waited_for_ready=False)
    try:
        os.chmod(output_path, 0o600)
    except OSError:
        pass
    outcome.update(
        {
            "image_path": output_path,
            "width": int(dimensions[0]) if dimensions else int(width),
            "height": int(dimensions[1]) if dimensions else int(height),
            "file_size": os.path.getsize(output_path),
        }
    )
    return outcome


def poster_time_of(frame: Optional[Mapping[str, object]]) -> int:
    """The instant a poster capture should represent, in ms."""
    if not frame:
        return 0
    return int(frame.get("poster_time_ms") or frame.get("duration_ms") or 0)


__all__: Sequence[str] = (
    "READY_EXPRESSION",
    "VIRTUAL_TIME_BUDGET_MS",
    "capture_poster_png",
    "chrome_command",
    "find_chrome",
    "png_dimensions",
    "poster_time_of",
)
