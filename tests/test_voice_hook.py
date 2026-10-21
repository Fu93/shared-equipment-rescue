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
    assert "Fallback: pattern parser (rate limit)" in html
    assert "The assistant is busy. Waiting a moment, then trying again." in html
    assert "utteranceChain" in html
    assert "agentInflight" in html
    assert "return runAgentLoop(text)" in html
    assert "await onFinalUtterance(text)" in html
    assert "light: true" in html
    assert "server_audit_tool" in html
    assert "'completed'" in html
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
            from urllib.parse import quote

            # The query hook has to run on its own, from the first paint,
            # and the version has to change. A string search is not this test.
            await page.goto(
                url + "/?utterance=" + quote("Alexa, Confocal A is down until 4pm"),
                wait_until="domcontentloaded",
            )
            await page.wait_for_function(
                "() => (document.getElementById('verBadge') || {}).textContent === 'v2'",
                timeout=20000,
            )
            body = await page.inner_text("body")
            assert "Understood" in body
            assert "Fallback: pattern parser (Bedrock off)" in body
            assert not errors, errors

            # Called before the session is up, the function waits, then drives
            # the same path. A line without the wake word changes nothing.
            page2 = await browser.new_page(viewport={"width": 1440, "height": 900})
            errors2 = []
            page2.on("pageerror", lambda err: errors2.append(str(err)))
            await page2.goto(url, wait_until="domcontentloaded")
            await page2.wait_for_function(
                "() => typeof window.serSimulateUtterance === 'function'",
                timeout=20000,
            )
            await page2.evaluate(
                "(text) => window.serSimulateUtterance(text)",
                "Confocal B is down until 5pm",
            )
            await page2.wait_for_function(
                "() => (document.getElementById('verBadge') || {}).textContent === 'v2'",
                timeout=20000,
            )
            chat = await page2.locator(".chat-messages").inner_text()
            assert "Understood" not in chat
            transcript = await page2.text_content("#liveTranscript")
            assert "Confocal B is down until 5pm" in (transcript or "")
            await page2.evaluate(
                "(text) => window.serSimulateUtterance(text)",
                "Alexa, Confocal B is down until 5pm",
            )
            await page2.wait_for_function(
                "() => (document.getElementById('verBadge') || {}).textContent === 'v3'",
                timeout=20000,
            )
            assert not errors2, errors2
            await browser.close()
    finally:
        for proc in (web, mcp):
            proc.terminate()
        for proc in (web, mcp):
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


def _free_port() -> int:
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _spawn(env, boot_source: str):
    """Start MCP and the web shell. Caller terminates both processes."""
    import subprocess
    import sys
    import tempfile

    mcp_port = _free_port()
    web_port = _free_port()
    boot = os.path.join(tempfile.gettempdir(), f"ser_voice_boot_{os.getpid()}_{mcp_port}.py")
    with open(boot, "w", encoding="utf-8") as handle:
        handle.write(boot_source % mcp_port)
    mcp = subprocess.Popen(
        [sys.executable, "-X", "utf8", boot], cwd=ROOT, env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    web = subprocess.Popen(
        [sys.executable, "-X", "utf8", "app.py", "--port", str(web_port), "--mcp-port", str(mcp_port)],
        cwd=os.path.join(ROOT, "web"), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return mcp, web, f"http://127.0.0.1:{web_port}", boot


def _stop(mcp, web, boot):
    import subprocess
    for proc in (web, mcp):
        if proc.poll() is None:
            proc.terminate()
    for proc in (web, mcp):
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    if boot and os.path.exists(boot):
        os.remove(boot)


async def _wait_ready(url: str):
    import time
    import httpx
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.3)
    raise AssertionError("web shell did not start")


def _base_env(dbp: str) -> dict:
    env = dict(os.environ)
    env["SER_DB_PATH"] = dbp
    env["SER_DEMO_DATE"] = "2026-10-20"
    env["SER_DEMO_TZ"] = "Europe/London"
    env["PYTHONUTF8"] = "1"
    env.pop("SER_NO_RATE_LIMIT", None)
    return env


@pytest.mark.skipif(not _playwright_available(), reason="no browser available in this environment")
def test_voice_turn_reaches_confirm_with_the_rate_limiter_on():
    import asyncio
    asyncio.run(_confirm_under_limit())


async def _confirm_under_limit():
    import tempfile

    from playwright.async_api import async_playwright

    dbp = os.path.join(tempfile.gettempdir(), f"ser_voice_limit_{os.getpid()}.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(dbp + suffix):
            os.remove(dbp + suffix)
    env = _base_env(dbp)
    env["SER_LLM_MODE"] = "bedrock"
    env["AWS_BEARER_TOKEN_BEDROCK"] = "bearer-secret-do-not-log"
    env["AWS_REGION"] = "us-east-1"
    env["BEDROCK_MODEL_ID"] = "amazon.nova-lite-v1:0"
    env["SER_BEDROCK_STUB"] = "voice"
    boot_source = (
        "import os, sys, uvicorn\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        f"os.environ['SER_DB_PATH'] = {dbp!r}\n"
        "os.environ['SER_DEMO_DATE'] = '2026-10-20'\n"
        "os.environ['SER_DEMO_TZ'] = 'Europe/London'\n"
        "os.environ['SER_LLM_MODE'] = 'bedrock'\n"
        "os.environ['AWS_BEARER_TOKEN_BEDROCK'] = 'bearer-secret-do-not-log'\n"
        "os.environ['AWS_REGION'] = 'us-east-1'\n"
        "os.environ['BEDROCK_MODEL_ID'] = 'amazon.nova-lite-v1:0'\n"
        "os.environ['SER_BEDROCK_STUB'] = 'voice'\n"
        "os.environ.pop('SER_NO_RATE_LIMIT', None)\n"
        "from mcp_server.server import build_app\n"
        "uvicorn.run(build_app(), host='127.0.0.1', port=%d, log_level='error')\n"
    )
    mcp, web, url, boot = _spawn(env, boot_source)
    limited = []
    try:
        await _wait_ready(url)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            page.on("response", lambda res: limited.append(res.url) if res.status == 429 else None)
            from urllib.parse import quote
            await page.goto(
                url + "/?utterance=" + quote("Alexa, Confocal A is down until 4pm"),
                wait_until="domcontentloaded",
            )
            try:
                await page.wait_for_function(
                    """() => {
                        const card = document.getElementById('confirmCard');
                        const badge = document.getElementById('verBadge');
                        return card && !card.classList.contains('hidden')
                            && badge && badge.textContent === 'v2';
                    }""",
                    timeout=25000,
                )
            except Exception:
                body = await page.inner_text("body")
                raise AssertionError(body[:2500] + "\n429s=" + str(limited))
            assert not limited, limited
            body = await page.inner_text("body")
            assert "bearer-secret-do-not-log" not in body
            assert "Bedrock: STUB (test)" in body
            assert "Bedrock: on (amazon.nova" not in body
            assert not errors, errors
            await browser.close()
    finally:
        _stop(mcp, web, boot)


@pytest.mark.skipif(not _playwright_available(), reason="no browser available in this environment")
def test_back_to_back_hooks_run_one_at_a_time():
    import asyncio
    asyncio.run(_serialized_hooks())


async def _serialized_hooks():
    import tempfile

    from playwright.async_api import async_playwright

    dbp = os.path.join(tempfile.gettempdir(), f"ser_voice_queue_{os.getpid()}.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(dbp + suffix):
            os.remove(dbp + suffix)
    env = _base_env(dbp)
    env["SER_LLM_MODE"] = "scripted"
    env["SER_NO_RATE_LIMIT"] = "1"
    boot_source = (
        "import os, sys, uvicorn\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        f"os.environ['SER_DB_PATH'] = {dbp!r}\n"
        "os.environ['SER_DEMO_DATE'] = '2026-10-20'\n"
        "os.environ['SER_DEMO_TZ'] = 'Europe/London'\n"
        "os.environ['SER_LLM_MODE'] = 'scripted'\n"
        "os.environ['SER_NO_RATE_LIMIT'] = '1'\n"
        "from mcp_server.server import build_app\n"
        "uvicorn.run(build_app(), host='127.0.0.1', port=%d, log_level='error')\n"
    )
    mcp, web, url, boot = _spawn(env, boot_source)
    try:
        await _wait_ready(url)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_function(
                "() => typeof window.serSimulateUtterance === 'function'",
                timeout=20000,
            )
            await page.wait_for_function(
                "() => (document.getElementById('verBadge') || {}).textContent === 'v1'",
                timeout=20000,
            )
            await page.evaluate(
                """() => Promise.all([
                    window.serSimulateUtterance('Alexa, Confocal A is down until 4pm'),
                    window.serSimulateUtterance('Alexa, Confocal A is down until 4pm'),
                ])"""
            )
            await page.wait_for_function(
                "() => (document.getElementById('verBadge') || {}).textContent === 'v2'",
                timeout=20000,
            )
            chat = await page.locator(".chat-messages").inner_text()
            assert "already recorded" in chat
            assert "already in flight" not in chat
            assert "busy" not in chat.lower()
            assert not errors, errors
            await browser.close()
    finally:
        _stop(mcp, web, boot)


@pytest.mark.skipif(not _playwright_available(), reason="no browser available in this environment")
def test_non_json_429_falls_back_to_the_pattern_parser():
    import asyncio
    asyncio.run(_routed_429())


async def _routed_429():
    import json
    import tempfile

    from playwright.async_api import async_playwright

    dbp = os.path.join(tempfile.gettempdir(), f"ser_voice_429_{os.getpid()}.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(dbp + suffix):
            os.remove(dbp + suffix)
    env = _base_env(dbp)
    env["SER_LLM_MODE"] = "scripted"
    env["SER_NO_RATE_LIMIT"] = "1"
    boot_source = (
        "import os, sys, uvicorn\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        f"os.environ['SER_DB_PATH'] = {dbp!r}\n"
        "os.environ['SER_DEMO_DATE'] = '2026-10-20'\n"
        "os.environ['SER_DEMO_TZ'] = 'Europe/London'\n"
        "os.environ['SER_LLM_MODE'] = 'scripted'\n"
        "os.environ['SER_NO_RATE_LIMIT'] = '1'\n"
        "from mcp_server.server import build_app\n"
        "uvicorn.run(build_app(), host='127.0.0.1', port=%d, log_level='error')\n"
    )
    mcp, web, url, boot = _spawn(env, boot_source)
    try:
        await _wait_ready(url)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            metrics = {
                "proxy": {},
                "server": {"bedrock": {
                    "on": True,
                    "label": "Bedrock: on (amazon.nova-lite-v1:0, us-east-1)",
                    "error": None,
                }},
            }

            async def metrics_route(route):
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(metrics),
                )

            async def step_route(route):
                await route.fulfill(status=429, content_type="text/plain", body="not-json")

            await page.route("**/metrics", metrics_route)
            await page.route("**/agent/step", step_route)
            from urllib.parse import quote
            await page.goto(
                url + "/?utterance=" + quote("Alexa, Confocal A is down until 4pm"),
                wait_until="domcontentloaded",
            )
            await page.wait_for_function(
                "() => (document.getElementById('verBadge') || {}).textContent === 'v2'",
                timeout=20000,
            )
            mode = await page.text_content("#chatMode")
            chat = await page.locator(".chat-messages").inner_text()
            assert mode == "Fallback: pattern parser (rate limit)"
            assert "The assistant is busy. Waiting a moment, then trying again." in chat
            assert "not-json" not in chat
            assert not errors, errors
            await browser.close()
    finally:
        _stop(mcp, web, boot)


@pytest.mark.skipif(not _playwright_available(), reason="no browser available in this environment")
def test_slow_stub_keeps_back_to_back_hooks_from_overlapping():
    import asyncio
    asyncio.run(_slow_double_hook())


async def _slow_double_hook():
    import tempfile

    from playwright.async_api import async_playwright

    dbp = os.path.join(tempfile.gettempdir(), f"ser_voice_slow_{os.getpid()}.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(dbp + suffix):
            os.remove(dbp + suffix)
    env = _base_env(dbp)
    env["SER_LLM_MODE"] = "bedrock"
    env["AWS_BEARER_TOKEN_BEDROCK"] = "bearer-secret-do-not-log"
    env["AWS_REGION"] = "us-east-1"
    env["BEDROCK_MODEL_ID"] = "amazon.nova-lite-v1:0"
    env["SER_BEDROCK_STUB"] = "voice"
    env["SER_BEDROCK_STUB_DELAY"] = "0.3"
    env["SER_NO_RATE_LIMIT"] = "1"
    boot_source = (
        "import os, sys, uvicorn\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        f"os.environ['SER_DB_PATH'] = {dbp!r}\n"
        "os.environ['SER_DEMO_DATE'] = '2026-10-20'\n"
        "os.environ['SER_DEMO_TZ'] = 'Europe/London'\n"
        "os.environ['SER_LLM_MODE'] = 'bedrock'\n"
        "os.environ['AWS_BEARER_TOKEN_BEDROCK'] = 'bearer-secret-do-not-log'\n"
        "os.environ['AWS_REGION'] = 'us-east-1'\n"
        "os.environ['BEDROCK_MODEL_ID'] = 'amazon.nova-lite-v1:0'\n"
        "os.environ['SER_BEDROCK_STUB'] = 'voice'\n"
        "os.environ['SER_BEDROCK_STUB_DELAY'] = '0.3'\n"
        "os.environ['SER_NO_RATE_LIMIT'] = '1'\n"
        "from mcp_server.server import build_app\n"
        "uvicorn.run(build_app(), host='127.0.0.1', port=%d, log_level='error')\n"
    )
    mcp, web, url, boot = _spawn(env, boot_source)
    try:
        await _wait_ready(url)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            await page.goto(url, wait_until="domcontentloaded")
            await page.wait_for_function(
                "() => typeof window.serSimulateUtterance === 'function'",
                timeout=20000,
            )
            await page.wait_for_function(
                "() => (document.getElementById('verBadge') || {}).textContent === 'v1'",
                timeout=20000,
            )
            # Do not return the promises. The first loop blocks on Confirm,
            # and Playwright would wait if evaluate returned them.
            await page.evaluate(
                """() => {
                    window.serSimulateUtterance('Alexa, Confocal A is down until 4pm');
                    window.serSimulateUtterance('Alexa, Confocal A is down until 4pm');
                }"""
            )
            try:
                await page.wait_for_function(
                    """() => {
                        const card = document.getElementById('confirmCard');
                        const badge = document.getElementById('verBadge');
                        return card && !card.classList.contains('hidden')
                            && badge && badge.textContent === 'v2';
                    }""",
                    timeout=25000,
                )
            except Exception:
                body = await page.inner_text("body")
                raise AssertionError(body[:2500])
            await page.wait_for_timeout(1200)
            chat = await page.locator(".chat-messages").inner_text()
            assert chat.count("equipment_report_outage") == 1, chat
            assert chat.count("schedule_propose_replan") == 1, chat
            assert "duplicate_outage" not in chat
            assert "already recorded" not in chat
            assert "Nothing changed" not in chat
            assert "already in flight" not in chat
            assert "\u2192 busy" not in chat
            assert "busy" not in chat.lower()
            assert "Bedrock: STUB (test)" in await page.inner_text("body")
            assert not errors, errors
            await browser.close()
    finally:
        _stop(mcp, web, boot)


@pytest.mark.skipif(not _playwright_available(), reason="no browser available in this environment")
def test_partial_bedrock_failure_proposes_the_recorded_outage():
    import asyncio
    asyncio.run(_partial_failure_proposes())


async def _partial_failure_proposes():
    import json
    import tempfile

    from playwright.async_api import async_playwright

    dbp = os.path.join(tempfile.gettempdir(), f"ser_voice_partial_{os.getpid()}.db")
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(dbp + suffix):
            os.remove(dbp + suffix)
    env = _base_env(dbp)
    env["SER_LLM_MODE"] = "bedrock"
    env["AWS_BEARER_TOKEN_BEDROCK"] = "bearer-secret-do-not-log"
    env["AWS_REGION"] = "us-east-1"
    env["BEDROCK_MODEL_ID"] = "amazon.nova-lite-v1:0"
    env["SER_BEDROCK_STUB"] = "voice"
    env["SER_NO_RATE_LIMIT"] = "1"
    boot_source = (
        "import os, sys, uvicorn\n"
        f"sys.path.insert(0, {ROOT!r})\n"
        f"os.environ['SER_DB_PATH'] = {dbp!r}\n"
        "os.environ['SER_DEMO_DATE'] = '2026-10-20'\n"
        "os.environ['SER_DEMO_TZ'] = 'Europe/London'\n"
        "os.environ['SER_LLM_MODE'] = 'bedrock'\n"
        "os.environ['AWS_BEARER_TOKEN_BEDROCK'] = 'bearer-secret-do-not-log'\n"
        "os.environ['AWS_REGION'] = 'us-east-1'\n"
        "os.environ['BEDROCK_MODEL_ID'] = 'amazon.nova-lite-v1:0'\n"
        "os.environ['SER_BEDROCK_STUB'] = 'voice'\n"
        "os.environ['SER_NO_RATE_LIMIT'] = '1'\n"
        "from mcp_server.server import build_app\n"
        "uvicorn.run(build_app(), host='127.0.0.1', port=%d, log_level='error')\n"
    )
    mcp, web, url, boot = _spawn(env, boot_source)
    try:
        await _wait_ready(url)
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 1440, "height": 900})
            errors = []
            page.on("pageerror", lambda err: errors.append(str(err)))
            seen = {"n": 0}

            async def step_route(route):
                seen["n"] += 1
                if seen["n"] == 1:
                    await route.continue_()
                    return
                await route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "bedrock": True,
                        "fallback": True,
                        "stopped": False,
                        "reason": "model_error",
                        "error_code": "Timeout",
                        "label": "Fallback: pattern parser (Bedrock error: Timeout)",
                        "message": "Bedrock took too long.",
                        "text": "",
                        "calls": [],
                    }),
                )

            await page.route("**/agent/step", step_route)
            from urllib.parse import quote
            await page.goto(
                url + "/?utterance=" + quote("Alexa, Confocal A is down until 4pm"),
                wait_until="domcontentloaded",
            )
            try:
                await page.wait_for_function(
                    """() => {
                        const chat = document.querySelector('.chat-messages');
                        return chat && chat.innerText.indexOf('Replan proposed') !== -1;
                    }""",
                    timeout=25000,
                )
            except Exception:
                body = await page.inner_text("body")
                raise AssertionError(body[:2500])
            chat = await page.locator(".chat-messages").inner_text()
            assert "Replan proposed" in chat
            assert "Nothing changed" not in chat
            assert "duplicate_outage" not in chat
            assert "already recorded" not in chat
            badge = await page.text_content("#bedrockLabel")
            assert badge == "Bedrock: STUB (test)"
            assert not errors, errors
            await browser.close()
    finally:
        _stop(mcp, web, boot)
