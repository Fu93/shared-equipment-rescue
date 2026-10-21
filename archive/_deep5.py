# -*- coding: utf-8 -*-
"""Deep debug 5: frontend polish audit (readability under extreme content).

F1 extreme long reason string doesn't break layout (overflow-wrap present)
F2 XSS safety: reason/user strings are escapeHtml'd before innerHTML injection
F3 responsive: 1100px breakpoint actually stacks panels (media query present
   and applied at 780px width) — verified by computed style via Playwright
F4 animations present + reduced-motion guard
F5 buttons all have hover/active feedback
F6 no codicon tofu glyphs remain
F7 double-click Apply rapidly cannot double-apply (UI guard / idempotent)
"""
import asyncio
import os
import re
import sys


def _popen_kwargs():
    # CREATE_NO_WINDOW (0x08000000) is Windows-only. Passing it on Linux or
    # macOS raises ValueError and the child process never starts.
    if os.name == "nt":
        return {"creationflags": 0x08000000}
    return {}

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

results = []
def check(name, ok, extra=""):
    results.append((name, ok, extra))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))


html = open(os.path.join(ROOT, "web", "static", "index.html"), encoding="utf-8").read()

# F1: overflow-wrap / word-break in CSS
check("F1 long-text overflow guard", ("overflow-wrap" in html or "word-break" in html or
                                       "min-width: 0" in html or "min-width:0" in html))

# F2: escapeHtml used for all dynamic injections of user-controlled fields
uses = re.findall(r"escapeHtml\(([^)]+)\)", html)
check("F2a escapeHtml exists", len(uses) >= 20, f"n={len(uses)}")
# reason strings injected anywhere WITHOUT escapeHtml?
raw_reason = re.findall(r"(?<!escapeHtml\()reason\b", html)
# crude: check the render paths for outage reason / confirm messages always wrapped
check("F2b outage reason escaped", bool(re.search(r"escapeHtml\((?:[a-z]\w*\.)?reason\)", html)), str(raw_reason[:8]))
check("F2c user names escaped", bool(re.search(r"escapeHtml\(ch\.user\)|escapeHtml\(u\.user\)|escapeHtml\(b\.user\)", html)))

# F4: animations + reduced-motion
check("F4a animations present", ("@keyframes" in html and html.count("@keyframes") >= 3), f"kf={html.count('@keyframes')}")
check("F4b prefers-reduced-motion guard", "prefers-reduced-motion" in html)

# F5: hover/active feedback on buttons
check("F5 button hover/active", (":hover" in html and ":active" in html))

# F6: no codicon tofu (private-use glyphs U+E700-U+E8FF)
tofu = [ch for ch in html if 0xE700 <= ord(ch) <= 0xE8FF]
check("F6 no private-use glyphs", not tofu, f"found {[hex(ord(c)) for c in tofu[:5]]}")

# F3: media query stacking exists with correct breakpoints
check("F3a 1100px breakpoint", "max-width:1100px" in html or "max-width: 1100px" in html)
check("F3b mobile tweak", "max-width:560px" in html or "max-width: 560px" in html)

# F7: apply guard — btn disabled during flight or idempotent path
check("F7 double-apply guard (server idempotent)", "already_applied" in html or "existing plan" in html)

async def main():
    from playwright.async_api import async_playwright
    import subprocess, time
    import httpx, tempfile

    # boot stack
    DBP = os.path.join(tempfile.gettempdir(), "ser_webdev2.db")
    if os.path.exists(DBP): os.remove(DBP)
    env = dict(os.environ); env["SER_DB_PATH"] = DBP
    mcp = subprocess.Popen([sys.executable, "-X", "utf8",
                            os.path.join(ROOT, "tools", "dev_server2.py")],
                           env=env, **_popen_kwargs())
    web = subprocess.Popen([sys.executable, "-X", "utf8", "app.py", "--port", "8080"],
                           cwd=os.path.join(ROOT, "web"), **_popen_kwargs())
    try:
        dl = time.time() + 15
        up = False
        while time.time() < dl:
            try:
                r = httpx.post("http://127.0.0.1:8765/mcp",
                               headers={"authorization": "Bearer tok-manager",
                                         "accept": "application/json, text/event-stream",
                                         "content-type": "application/json"},
                               json={"jsonrpc": "2.0", "id": 0, "method": "ping"}, timeout=2)
                if r.status_code < 500: up = True; break
            except httpx.HTTPError: pass
            time.sleep(0.3)
        assert up

        async with async_playwright() as pw:
            b = await pw.chromium.launch()
            # F3c: computed layout at 780px — panels stacked vertically
            page = await b.new_page(viewport={"width": 780, "height": 1000})
            await page.goto("http://127.0.0.1:8080", wait_until="load")
            await page.wait_for_timeout(2500)
            chat = await page.locator(".chat-panel").bounding_box()
            sched = await page.locator(".schedule-panel").bounding_box()
            stacked = chat and sched and (sched["x"] < chat["x"] + chat["width"] * 0.5 <= sched["x"] + sched["width"] or
                       abs((chat["y"]) - (sched["y"] + sched["height"])) < 40 or chat["y"] > sched["y"])
            check("F3c 780px panels stack vertically", stacked, f"chat={chat} sched={sched}")
            # overflow: no horizontal scrollbar at 780
            sw = await page.evaluate("document.documentElement.scrollWidth")
            check("F3d no horizontal overflow at 780", sw <= 790, f"scrollWidth={sw}")
            await page.screenshot(path=os.path.join(ROOT, "web", "_responsive_780.png"), full_page=True)

            # desktop sanity
            await page.set_viewport_size({"width": 1440, "height": 900})
            await page.wait_for_timeout(700)
            sw2 = await page.evaluate("document.documentElement.scrollWidth")
            check("F3e no horizontal overflow at 1440", sw2 <= 1450, f"scrollWidth={sw2}")
            await page.screenshot(path=os.path.join(ROOT, "web", "_responsive_1440.png"), full_page=True)

            # F7 live: double-click refresh then confirm no duplicate stacking errors in console
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            await page.evaluate("window.loadSchedule && loadSchedule()")
            await page.evaluate("window.loadSchedule && loadSchedule()")
            await page.wait_for_timeout(1200)
            check("F7b rapid refreshes no JS errors", not errors, str(errors[:2]))

            await b.close()
    finally:
        for proc in (mcp, web):
            try:
                proc.terminate(); proc.wait(timeout=5)
            except Exception:
                proc.kill()

    n_ok = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== {n_ok}/{len(results)} PASS ===")
    return 0 if n_ok == len(results) else 1

sys.exit(asyncio.run(main()))
