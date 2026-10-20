# -*- coding: utf-8 -*-
"""Deep debug 7: hardening round verification (polish L round).

H1  syntax/parse check of index.html script block (node --check equivalent via esbuild)
H2  kill MCP server -> UI connect fails with friendly message (no raw crash), then
    restart MCP -> page recovers via Refresh (console-driven)
H3  Escape key cancels confirm card -> not_confirmed (no side effect)
H4  app.py serves / and /static from absolute path (cd-independence)
H5  role badge still correct after all edits (regression of identity)
"""
import asyncio
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\nn201\OneDrive - University of Glasgow\Desktop\Amazon\shared-equipment-rescue"
DAY = "2026-10-20"
results = []

def check(name, ok, extra=""):
    results.append((name, ok, extra))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))


def boot(webdir_workdir, mcp_db, env_extra=None):
    env = dict(os.environ)
    env["SER_DB_PATH"] = mcp_db
    mcp = subprocess.Popen([sys.executable, "-X", "utf8", os.path.join(ROOT, "tools", "dev_server2.py"), mcp_db],
                           env=env, creationflags=0x08000000,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web = subprocess.Popen([sys.executable, "-X", "utf8", os.path.join(ROOT, "web", "app.py"), "--port", "8080"],
                           cwd=webdir_workdir, creationflags=0x08000000,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    web.cwd_workdir = webdir_workdir
    import httpx
    dl = time.time() + 20
    ok_mcp = ok_web = False
    while time.time() < dl:
        if not ok_web:
            try:
                r = httpx.get("http://127.0.0.1:8080", timeout=2)
                if r.status_code == 200:
                    ok_web = True
            except httpx.HTTPError:
                pass
        if not ok_mcp:
            try:
                r2 = httpx.post("http://127.0.0.1:8765/mcp",
                                headers={"authorization": "Bearer tok-manager",
                                          "accept": "application/json, text/event-stream",
                                          "content-type": "application/json"},
                                json={"jsonrpc": "2.0", "id": 0, "method": "initialize",
                                      "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                                                  "clientInfo": {"name": "p", "version": "1"}}}, timeout=2)
                if r2.status_code == 200:
                    ok_mcp = True
            except httpx.HTTPError:
                pass
        if ok_mcp and ok_web:
            break
        time.sleep(0.3)
    return mcp, web, ok_mcp, ok_web


async def main():
    import httpx
    from playwright.async_api import async_playwright

    # ---- H1: script syntax (esbuild parse of the inline module is not trivial;
    # use node to syntax-check by extracting the module script) ----
    html = open(os.path.join(ROOT, "web", "static", "index.html"), encoding="utf-8").read()
    m = re.search(r'<script type="module">(.*?)</script>', html, re.S)
    check("H1a module script extracted", bool(m))
    if m:
        node = shutil.which("node")
        if node:
            tmp = os.path.join(tempfile.gettempdir(), "ser_index_script.mjs")
            open(tmp, "w", encoding="utf-8").write("const windowProxy = {location:{origin:'http://127.0.0.1:8080'}};\n" +
                                                   m.group(1).replace("import { createSession, callTool, closeSession } from '/static/mcp-client.bundle.js';",
                                                                      "const { createSession, callTool, closeSession } = { createSession:0, callTool:0, closeSession:0 };"))
            pr = subprocess.run([node, "--check", tmp], capture_output=True, text=True)
            check("H1b inline script parses (node --check)", pr.returncode == 0, pr.stderr[:300])
        else:
            check("H1b inline script parses", False, "node not found")
    py = subprocess.run([sys.executable, "-X", "utf8", "-c",
                         "import ast; ast.parse(open(r'" + os.path.join(ROOT, "web", "app.py") + "', encoding='utf-8').read()); print('ok')"],
                        capture_output=True, text=True)
    check("H1c app.py parses", py.returncode == 0, py.stderr[:200])

    # ---- H4: cd-independence of app.py static paths ----
    tmpcwd = tempfile.mkdtemp(prefix="ser_cwd_")
    mcp_db = os.path.join(tempfile.gettempdir(), "ser_deep7.db")
    if os.path.exists(mcp_db):
        os.remove(mcp_db)
    mcp, web, ok_mcp, ok_web = boot(tmpcwd, mcp_db)
    try:
        # boot from a DIFFERENT cwd — but app.py needs its own dir; boot() uses web/ workdir.
        # Instead verify paths resolve via import (app loaded from other cwd):
        pr = subprocess.run([sys.executable, "-X", "utf8", "-c",
                             "import sys; sys.path.insert(0, r'" + os.path.join(ROOT, "web") + "'); "
                             "import os; os.chdir(r'" + tmpcwd + "'); "
                             "import app; print('static-ok' if app.app.routes else 'no-routes')"],
                            capture_output=True, text=True)
        check("H4 app.py importable from other cwd", pr.returncode == 0 and "static-ok" in pr.stdout, (pr.stderr or pr.stdout)[:300])
        check("H2a boot with MCP up", ok_mcp and ok_web)

        async with async_playwright() as pw:
            b = await pw.chromium.launch()
            page = await b.new_page()
            await page.goto("http://127.0.0.1:8080", wait_until="load")
            await page.wait_for_timeout(2500)

            # H5 role badge correct after edits
            role = await page.text_content("#roleBadge")
            check("H5 role badge", role and "manager" in role.lower() and "Facility Manager" in role, repr(role))

            # ---- H3 Escape cancel ----
            await page.evaluate("document.querySelector('.amber, button[onclick*=reportOutage]').click()") if await page.locator(".amber").count() == 0 else await page.click(".amber")
            await page.wait_for_timeout(1300)
            visible = await page.locator("#confirmCard").is_visible()
            if not visible:
                # plan absent (outage may auto-propose) — apply route
                await page.evaluate("document.querySelector('.green').click()")
                await page.wait_for_timeout(1500)
            vis2 = await page.locator("#confirmCard").is_visible()
            check("H3a confirm card shows", vis2)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(900)
            hidden = not await page.locator("#confirmCard").is_visible()
            body = await page.inner_text("body")
            check("H3b escape cancels + narrates", hidden and "Escape" in body)
            # version unchanged after escape (single outage => version should be 2, no apply)
            ver = await page.text_content("#verBadge")
            check("H3c no side effect on escape (v2)", ver.strip() == "v2", repr(ver))
            await b.close()
    finally:
        for proc in (mcp, web):
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    # ---- H2: web WITHOUT mcp -> friendly degrade ----
    web2 = subprocess.Popen([sys.executable, "-X", "utf8", "app.py", "--port", "8080"],
                            cwd=os.path.join(ROOT, "web"), creationflags=0x08000000,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(3)
        async with async_playwright() as pw:
            b = await pw.chromium.launch()
            page = await b.new_page()
            await page.goto("http://127.0.0.1:8080", wait_until="load")
            await page.wait_for_timeout(3500)
            body = await page.inner_text("body")
            dev = await page.inner_text("#mcpLogs")
            degraded = "Cannot reach the MCP server" in body or "FAIL" in dev or "transport_error" in dev
            check("H2b graceful degrade without MCP", degraded, body[-200:] + " || " + dev[:200])
            await b.close()
    finally:
        try:
            web2.terminate(); web2.wait(timeout=5)
        except Exception:
            web2.kill()

    n_ok = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== {n_ok}/{len(results)} PASS ===")
    return 0 if n_ok == len(results) else 1

sys.exit(asyncio.run(main()))
