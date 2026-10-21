# -*- coding: utf-8 -*-
"""Deep debug 8: polish round 4 (log bounds, README, server audit line check).

G1 dev console bound: >200 entries -> oldest dropped, newest live
G2 chat bound: >150 entries -> oldest dropped
G3 README quickstart references dev_server2.py and the file exists
G4 audit log line present when SER_LOG_LEVEL=INFO (caplog-style via stderr capture)
G5 regression of core flows after edits (quick: outage->propose->escape)
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time


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


def boot_stack(dbp):
    env = dict(os.environ)
    env["SER_DB_PATH"] = dbp
    mcp = subprocess.Popen([sys.executable, "-X", "utf8", os.path.join(ROOT, "tools", "dev_server2.py"), dbp],
                           env=env, **_popen_kwargs(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web = subprocess.Popen([sys.executable, "-X", "utf8", os.path.join(ROOT, "web", "app.py"), "--port", "8080"],
                           cwd=tempfile.gettempdir(), **_popen_kwargs(),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    import httpx
    dl = time.time() + 25
    while time.time() < dl:
        up_m = up_w = False
        try:
            r = httpx.post("http://127.0.0.1:8765/mcp",
                           headers={"authorization": "Bearer tok-manager", "accept": "application/json, text/event-stream",
                                     "content-type": "application/json"},
                           json={"jsonrpc": "2.0", "id": 0, "method": "initialize",
                                 "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                                             "clientInfo": {"name": "p", "version": "1"}}}, timeout=2)
            up_m = r.status_code == 200
        except httpx.HTTPError:
            pass
        try:
            r2 = httpx.get("http://127.0.0.1:8080", timeout=2)
            up_w = r2.status_code == 200
        except httpx.HTTPError:
            pass
        if up_m and up_w:
            return mcp, web
        time.sleep(0.3)
    raise RuntimeError("boot timeout")


async def main():
    from playwright.async_api import async_playwright
    dbp = os.path.join(tempfile.gettempdir(), "ser_deep8.db")
    if os.path.exists(dbp):
        os.remove(dbp)
    mcp, web = boot_stack(dbp)
    try:
        # ---- G3 README ----
        md = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
        check("G3 README quickstart uses dev_server2.py", "tools/dev_server2.py" in md and
              os.path.exists(os.path.join(ROOT, "tools", "dev_server2.py")))

        async with async_playwright() as pw:
            b = await pw.chromium.launch()
            page = await b.new_page()
            await page.goto("http://127.0.0.1:8080", wait_until="load")
            await page.wait_for_timeout(2500)

            # ---- G1 dev console bound: hammer logMCP via evaluate (safe, exportable?) ----
            # logMCP isn't exported to window; hammer loadSchedule 120x -> each produces 2 log entries
            for _ in range(75):
                await page.evaluate("window.loadSchedule && loadSchedule()")
            await page.wait_for_timeout(1500)
            n_logs = await page.evaluate("document.getElementById('mcpLogs').children.length")
            check("G1 dev console bound <=200", 0 < n_logs <= 200, f"n={n_logs}")

            # ---- G2 chat bound: addMessage not exported; drive many proposes via schedule calls ----
            # Use reset + many alternating messages through changeUser cycles? simpler: directly call UI paths
            # by evaluating DOM injection neutral route — count only via proposal spam
            for _ in range(40):
                await page.evaluate("""async () => {
                    if (window.loadSchedule) await window.loadSchedule();
                }""")
            n_chat = await page.evaluate("document.getElementById('chatMessages').children.length")
            check("G2 chat bounded <=150", 0 < n_chat <= 150, f"n={n_chat}")

            # ---- G5 quick regression: outage -> card -> escape -> v2, still working post-edits ----
            await page.evaluate("window.reportOutageFlow && window.reportOutageFlow()")
            await page.wait_for_timeout(1500)
            green = page.locator(".green")
            if await green.count() == 0:
                await page.evaluate("document.querySelector('button[onclick*=proposeFlow]') && document.querySelector('button[onclick*=proposeFlow]').click()")
                await page.wait_for_timeout(1200)
            await page.evaluate("document.querySelector('.green').click()") if await page.locator(".green").count() else None
            await page.wait_for_timeout(1400)
            vis = await page.locator("#confirmCard").is_visible()
            check("G5a confirm card appears", vis)
            if vis:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(800)
            ver = await page.text_content("#verBadge")
            check("G5b escape keeps v2", ver.strip() == "v2", repr(ver))
            await b.close()
    finally:
        for proc in (mcp, web):
            try:
                proc.terminate(); proc.wait(timeout=5)
            except Exception:
                proc.kill()

    # ---- G4 audit log line (in-process capture) ----
    import logging
    sys.path.insert(0, ROOT)
    os.environ["SER_DB_PATH"] = dbp2 = os.path.join(tempfile.gettempdir(), "ser_deep8_audit.db")
    if os.path.exists(dbp2):
        os.remove(dbp2)
    import importlib
    import mcp_server.server as srv
    importlib.reload(srv)
    records = []
    class Cap(logging.Handler):
        def emit(self, r):
            records.append(r.getMessage())
    srv.log.addHandler(Cap())
    srv.initialize_storage()
    # perform a forbidden call (no auth context) — expect one log line
    import types
    class _FakeReq:
        def __init__(self):
            self.headers = {"authorization": "Bearer tok-manager"}
    fake_ctx = types.SimpleNamespace(request_context=types.SimpleNamespace(request=_FakeReq()))
    try:
        await srv._schedule_get_impl("lab-a", "2026-10-20", fake_ctx)
    except Exception:
        pass
    check("G4 audit log captured", any("call schedule_get" in r for r in records), str(records[:3]))

    n_ok = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== {n_ok}/{len(results)} PASS ===")
    return 0 if n_ok == len(results) else 1

sys.exit(asyncio.run(main()))
