"""Voice is the browser Web Speech API, plus a labelled simulation hook.

The hook is how this test, and a screen recording with no microphone, inject
a transcript through the same function as a final recognition result.
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "web", "static", "index.html")


def _page() -> str:
    with open(PAGE, encoding="utf-8") as f:
        return f.read()


def test_page_uses_web_speech_and_the_simulation_hook():
    html = _page()
    assert "Simulation hook" in html
    assert "window.serSimulateUtterance" in html
    assert "onFinalUtterance" in html
    assert "SpeechRecognition" in html
    assert "webkitSpeechRecognition" in html
    assert "speechSynthesis" in html
    assert "en-US" in html
    assert re.search(r"/\^\\s\*alexa\\b/i", html)
    assert "get('utterance')" in html
    assert "Fallback: pattern parser (Bedrock off)" in html
    assert "This browser has no speech recognition" in html
    assert "Microphone permission was denied" in html
    lowered = html.lower()
    for banned in (
        "transcribe", "speech.googleapis", "deepgram", "assemblyai",
        "whisper", "elevenlabs", "polly",
    ):
        assert banned not in lowered


def _playwright_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            browser.close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _playwright_available(), reason="no browser available in this environment")
def test_simulation_hook_uses_the_wake_word_path():
    import asyncio
    asyncio.run(_drive())


async def _drive():
    import socket
    import subprocess
    import sys
    import tempfile
    import time

    import httpx
    from playwright.async_api import async_playwright

    def free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    dbp = os.path.join(tempfile.gettempdir(), f"ser_voice_{os.getpid()}.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(dbp + suffix):
            os.remove(dbp + suffix)
    env = dict(os.environ)
    env["SER_DB_PATH"] = dbp
    env["SER_DEMO_DATE"] = "2026-10-20"
    env["SER_DEMO_TZ"] = "Europe/London"
    env["SER_LLM_MODE"] = "scripted"
    env["PYTHONUTF8"] = "1"
    mcp_port = free_port()
    web_port = free_port()
    boot = os.path.join(tempfile.gettempdir(), f"ser_voice_boot_{os.getpid()}.py")
    with open(boot, "w", encoding="utf-8") as handle:
        handle.write(
            "import os, sys, uvicorn\n"
            f"sys.path.insert(0, {ROOT!r})\n"
            f"os.environ['SER_DB_PATH'] = {dbp!r}\n"
            "os.environ['SER_DEMO_DATE'] = '2026-10-20'\n"
            "os.environ['SER_DEMO_TZ'] = 'Europe/London'\n"
            "os.environ['SER_LLM_MODE'] = 'scripted'\n"
            "os.environ['SER_NO_RATE_LIMIT'] = '1'\n"
            "from mcp_server.server import build_app\n"
            "uvicorn.run(build_app(), host='127.0.0.1', port=%d, log_level='error')\n"
            % mcp_port
        )
    mcp = subprocess.Popen(
        [sys.executable, "-X", "utf8", boot], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    web = subprocess.Popen(
        [sys.executable, "-X", "utf8", "app.py", "--port", str(web_port), "--mcp-port", str(mcp_port)],
        cwd=os.path.join(ROOT, "web"), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{web_port}"
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if httpx.get(url, timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        else:
            raise AssertionError("web shell did not start")
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_function(
                "() => document.getElementById('connText') && document.getElementById('connText').textContent.includes('connected')",
                timeout=20000,
            )
            assert await page.evaluate("typeof window.serSimulateUtterance") == "function"
            await page.evaluate("window.serSimulateUtterance('Confocal A is down until 4pm')")
            await page.wait_for_timeout(800)
            assert "v1" in (await page.text_content("#verBadge") or "")
            transcript = await page.text_content("#liveTranscript")
            assert "Confocal A is down until 4pm" in (transcript or "")
            chat = await page.locator(".chat-messages").inner_text()
            assert "Understood" not in chat
            await page.evaluate("window.serSimulateUtterance('Alexa, Confocal A is down until 4pm')")
            await page.wait_for_function(
                "() => (document.getElementById('verBadge') || {}).textContent === 'v2'",
                timeout=20000,
            )
            body = await page.inner_text("body")
            assert "Fallback: pattern parser (Bedrock off)" in body
            assert not errors, errors
            await browser.close()
    finally:
        for proc in (web, mcp):
            proc.terminate()
        for proc in (web, mcp):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
