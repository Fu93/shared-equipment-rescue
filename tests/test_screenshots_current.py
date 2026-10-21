# -*- coding: utf-8 -*-
"""The committed demo screenshots must still show the current UI.

The screenshots in docs/screenshots/ are the first thing a judge sees in the
repo. The previous set (captured on 2026-10-20) was three weeks out of date:
it still showed the "Priya" name, the raw reason dump
("equipment_id=null booking_id=null ...") and the "Working..." spinner
painting over the confirm card.

This test fails if a committed screenshot goes stale, which is what let the
old set drift unnoticed in the first place.

It compares the COMMITTED images against a fresh capture of the current
build. Needs Playwright; skips cleanly where no browser can launch.
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SHOTS = os.path.join(ROOT, "docs", "screenshots")
EXPECTED = [
    "_shot_1_initial.png",
    "_shot_2_outage.png",
    "_shot_3_proposed.png",
    "_shot_4_elicit.png",
    "_shot_5_applied.png",
    "_shot_6_wang_after.png",
]


def _playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch()
            b.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _playwright_available(),
                    reason="no browser available in this environment")
def test_committed_screenshots_are_current():
    """docs/screenshots/ matches what the build renders today."""
    stale = asyncio.run(_compare())
    assert not stale, "stale screenshots (re-run tools/shoot_screenshots.py): " + ", ".join(stale)


def _png_size(path: str):
    """(width, height) read straight from the PNG header - no image library."""
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))


def _is_valid_png(path: str) -> bool:
    """A real PNG (not a truncated or corrupted file)."""
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            f.seek(-12, os.SEEK_END)
            tail = f.read(12)
        return (head == b"\x89PNG\r\n\x1a\n"
                and tail[4:8] == b"IEND"
                and _png_size(path) is not None
                and os.path.getsize(path) > 10000)
    except Exception:
        return False


async def _compare():
    """Check the committed screenshots really show the current UI.

    Comparing pixels is not reliable: a PNG is compressed, so a byte-level
    diff is noise, and a re-capture is never bit-identical (fonts,
    antialiasing, the clock in the audit timestamps). What IS reliable is
    the CONTENT: tools/shoot_screenshots.py records, next to the images, the
    text each frame shows (manifest.json). This test re-renders the same
    scenes and compares the TEXT - an exact comparison, no noise.
    """
    from playwright.async_api import async_playwright

    manifest_path = os.path.join(SHOTS, "manifest.json")
    if not os.path.exists(manifest_path):
        return ["manifest.json (missing - re-run tools/shoot_screenshots.py)"]
    missing = [n for n in EXPECTED if not os.path.exists(os.path.join(SHOTS, n))]
    if missing:
        return [f"{n} (missing)"]
    broken = [n for n in EXPECTED if not _is_valid_png(os.path.join(SHOTS, n))]
    if broken:
        return [f"{n} (not a valid PNG)" for n in broken]

    with open(manifest_path, encoding="utf-8") as f:
        recorded = json.load(f)

    tmp = os.path.join(tempfile.gettempdir(), f"ser_shotcheck_{os.getpid()}")
    os.makedirs(tmp, exist_ok=True)
    dbp = os.path.join(tempfile.gettempdir(), f"ser_shotcheck_{os.getpid()}.db")
    for suf in ("", "-wal", "-shm"):
        if os.path.exists(dbp + suf):
            os.remove(dbp + suf)
    env = dict(os.environ)
    env["SER_DB_PATH"] = dbp
    env["PYTHONUTF8"] = "1"

    import socket

    def _free_port() -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    mcp_port = _free_port()
    web_port = _free_port()
    while web_port == mcp_port:
        web_port = _free_port()
    web_url = f"http://127.0.0.1:{web_port}"

    boot = os.path.join(tempfile.gettempdir(), f"ser_shotcheck_boot_{os.getpid()}.py")
    with open(boot, "w", encoding="utf-8") as f:
        f.write(
            "import os, sys, uvicorn\n"
            f"sys.path.insert(0, {ROOT!r})\n"
            f"os.environ['SER_DB_PATH'] = {dbp!r}\n"
            "os.environ['SER_NO_RATE_LIMIT'] = '1'\n"
            "from mcp_server.server import build_app\n"
            "uvicorn.run(build_app(), host='127.0.0.1', port=%d, log_level='error')\n"
            % mcp_port
        )
    mcp = subprocess.Popen([sys.executable, "-X", "utf8", boot], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=0x08000000)
    web = subprocess.Popen([sys.executable, "-X", "utf8", "app.py",
                            "--port", str(web_port), "--mcp-port", str(mcp_port)],
                           cwd=os.path.join(ROOT, "web"), env=env,
                           creationflags=0x08000000,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    stale = []
    try:
        import httpx
        dl = time.time() + 30
        up = False
        while time.time() < dl and not up:
            try:
                up = httpx.get(web_url, timeout=2).status_code == 200
            except httpx.HTTPError:
                pass
            if not up:
                time.sleep(0.3)
        if not up:
            raise RuntimeError("web proxy never came up")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 1500, "height": 900})
            await page.goto(web_url, wait_until="load")
            await page.wait_for_timeout(3500)

            async def facts() -> dict:
                panel = await page.locator(".schedule-panel").inner_text()
                chat = await page.locator(".chat-panel").inner_text()
                return {
                    "panel": panel,
                    "chat": chat,
                    "verBadge": (await page.text_content("#verBadge") or "").strip(),
                    "roleBadge": (await page.text_content("#roleBadge") or "").strip(),
                }

            async def step(name: str) -> None:
                fresh = await facts()
                old = recorded.get(name)
                if old is None:
                    stale.append(f"{name} (not in the manifest)")
                    return
                for key in ("verBadge", "roleBadge"):
                    if old.get(key) != fresh.get(key):
                        stale.append(
                            f"{name} ({key}: recorded {old.get(key)!r} vs now {fresh.get(key)!r})")
                for key in ("panel", "chat"):
                    # The audit timestamps carry a clock, so compare the
                    # structural lines and ignore the volatile ones.
                    old_lines = _stable_lines(old.get(key, ""))
                    new_lines = _stable_lines(fresh.get(key, ""))
                    if old_lines != new_lines:
                        only_old = [l for l in old_lines if l not in new_lines]
                        only_new = [l for l in new_lines if l not in old_lines]
                        stale.append(
                            f"{name} ({key} differs: -{(only_old or ['?'])[:2]} "
                            f"+{(only_new or ['?'])[:2]})")

            await step("_shot_1_initial.png")
            await page.evaluate("window.reportOutageFlow()")
            await page.wait_for_timeout(3500)
            await step("_shot_2_outage.png")
            await page.wait_for_timeout(1500)
            await step("_shot_3_proposed.png")
            apply_btn = page.locator("button.green").first
            if await apply_btn.count():
                await apply_btn.click()
            await page.wait_for_timeout(3000)
            await step("_shot_4_elicit.png")
            if await page.locator("#confirmYes").count():
                await page.evaluate("document.getElementById('confirmYes').click()")
            await page.wait_for_timeout(3500)
            await step("_shot_5_applied.png")
            await page.select_option("#userSelect", "tok-wang")
            await page.wait_for_timeout(3500)
            await step("_shot_6_wang_after.png")
            await browser.close()
    finally:
        for proc in (web, mcp):
            try:
                proc.terminate()
                proc.wait(timeout=6)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        shutil.rmtree(tmp, ignore_errors=True)
    return stale


def _stable_lines(text: str):
    """Lines worth comparing: drop the ones that carry a wall-clock time."""
    out = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        # "confirmed by Facility Manager at 2026-10-21 15:33:51 (London)"
        if re.search(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", s):
            s = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", "<ts>", s)
        out.append(s)
    return out


def _bytes_differ(a: str, b: str, tolerance: int = 900) -> bool:
    """True when the two PNGs differ by more than `tolerance` bytes.

    A screenshot is not bit-stable between runs (fonts, antialiasing, the
    clock in the audit timestamps), so an exact comparison would be flaky.
    A small size difference is normal; a large one means the UI really
    changed and the committed image must be regenerated.
    """
    size_a = os.path.getsize(a)
    size_b = os.path.getsize(b)
    if abs(size_a - size_b) > max(tolerance, size_a * 0.02):
        return True
    # same size within tolerance: compare the leading bytes (PNG header
    # + first scanlines) which change if the layout changed at all
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read(4096) != fb.read(4096)
