# -*- coding: utf-8 -*-
"""Browser E2E: 20 checks against the real web UI (:8080) + MCP (:8765).

Run:  python -X utf8 tools/browser_e2e.py   (boots both servers itself).
Deleted temp copies are recovered here; screenshot artifacts are 
web/_responsive_*.png (gitignored, delete after inspection).

Boot both servers, drive a real Chromium page through the demo narrative:
identity badges, schedule grid, outage banner, replan propose -> confirm card
(elicitation) -> declined/applied outcomes, dev console log lines, and
responsive screenshots (780px / 1440px) verified visually.

Output contract: final line "=== 20/20 PASS ===" (or FAIL with details).
"""
import asyncio
import os
import sys
import tempfile
import time


def _popen_kwargs():
    # CREATE_NO_WINDOW (0x08000000) is Windows-only. Passing it on Linux or
    # macOS raises ValueError and the child process never starts.
    if os.name == "nt":
        return {"creationflags": 0x08000000}
    return {}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = "2026-10-20"
# The MCP server is started from the IN-REPO launcher. An earlier version
# pointed at %TEMP%\ser_mcp_dev_server2.py - a file that exists nowhere in
# the repo and is never generated, so on a clean checkout the MCP server
# simply never started and the whole suite ran against a dead page.
MCP_BOOT = os.path.join(ROOT, "tools", "dev_server2.py")
DBP = os.path.join(tempfile.gettempdir(), "ser_webdev2.db")
WEB_URL = "http://127.0.0.1:8080"

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

results = []
fail = []

def check(cond, label="", detail=""):
    """Assert one UI expectation.

    Signature is (cond, label): every call site passes the real condition
    first. The previous version read `check(num, cond, ...)` while all call
    sites passed two arguments, so the condition was dropped and the LABEL
    landed in the condition slot - a non-empty string, which is always true.
    The suite therefore reported 20/20 no matter what the UI did.
    """
    results.append((label or detail, bool(cond)))
    if cond:
        print(f"PASS {len(results):02d} {label or detail}")
    else:
        fail.append(label or detail)
        print(f"FAIL -- {label or detail}  [{detail}]")
    return bool(cond)


def _kill_stale():
    """Best-effort: stop leftover demo servers from an earlier run.

    The old implementation used Get-CimInstance, which is refused in some
    sandboxes - and a leftover server on :8080 would make this suite test a
    STALE build (a false green) instead of the current tree. The port check
    below now fails loudly if a squatter survives, so a failed cleanup can
    never hide a stale server.
    """
    import subprocess
    for pat in ("dev_server2.py", "app.py --port 8080"):
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                        f"Where-Object {{ $_.CommandLine -match '{pat}' }} | "
                        f"ForEach-Object {{ Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }}"],
                       capture_output=True)


def _port_free(host: str, port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex((host, port)) != 0


_PROCS = []


def boot_servers():
    import subprocess
    _kill_stale()
    for port in (8765, 8080):
        for _ in range(20):
            if _port_free("127.0.0.1", port):
                break
            time.sleep(0.25)
        else:
            raise RuntimeError(
                f"port {port} is still occupied by a stale server; refusing to "
                f"test a stale build. Stop it and re-run."
            )
    if os.path.exists(DBP):
        os.remove(DBP)
    env = dict(os.environ)
    env["SER_DB_PATH"] = DBP
    _PROCS.append(subprocess.Popen(
        [sys.executable, "-X", "utf8", MCP_BOOT, DBP], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **_popen_kwargs()))
    _PROCS.append(subprocess.Popen(
        [sys.executable, "-X", "utf8", "app.py", "--port", "8080"],
        cwd=os.path.join(ROOT, "web"),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        **_popen_kwargs()))
    import httpx
    for url in ("http://127.0.0.1:8765/mcp", WEB_URL):
        dl = time.time() + 15
        while time.time() < dl:
            try:
                r = httpx.post(url, headers={"authorization": "Bearer tok-manager",
                                              "accept": "application/json, text/event-stream",
                                              "content-type": "application/json"},
                               json={"jsonrpc": "2.0", "id": 0, "method": "ping"}, timeout=2)
                if r.status_code < 500:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)
        time.sleep(0.4)


def stop_servers():
    """Never leave demo servers behind - a stray :8080 blocks the recording."""
    for p in _PROCS:
        try:
            p.terminate()
            p.wait(timeout=6)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    _PROCS.clear()


async def main():
    from playwright.async_api import async_playwright

    boot_servers()
    checks = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        dev_logs = []
        page.on("console", lambda m: dev_logs.append(m.text))
        await page.goto(WEB_URL, wait_until="load")
        await page.wait_for_timeout(2500)

        # 1 identity badges
        ver = await page.text_content("#verBadge")
        check(ver and ver.strip().startswith("v"), f"verBadge {ver!r}")
        ident = await page.text_content("#roleBadge")
        check(ident and ("Facility Manager" in ident or "manager" in ident.lower()), f"identity {ident!r}")

        # 3 two-column schedule panel + chat panel exist
        cols = (await page.locator(".schedule-panel").count()) + (await page.locator(".chat-panel").count())
        check(cols >= 2, f"panels={cols}")

        # 4 equipment names render
        # The panel uppercases equipment names via CSS text-transform, and
        # innerText reports the TRANSFORMED text - so compare case-insensitively.
        body = await page.inner_text("body")
        low = body.lower()
        check("confocal microscope a" in low and "confocal microscope b" in low,
              "equipment names", body[:300])

        # 5 researcher chip visible (booking B2 Chen)
        check("Chen" in body, "Chen visible")
        # 6 dev console shows schedule_get + ok
        got = await page.text_content("#mcpLogs")
        check("schedule_get" in (got or "") and "ok" in (got or ""), "dev console schedule_get ok")

        # 7 default Occupied rows masked for chosen identity? (manager sees names, but UI shows Wang booking)
        check("Wang" in body, "Wang visible")
        # 7 booking rows render: each row shows "<time range> · <user> (<id>)"
        rows = await page.locator(".booking-row, .b-row, .sched-row, .booking").count()
        has_time_row = "09:00–10:00" in body or "09:00-10:00" in body
        check(rows > 0 or has_time_row, "booking rows render",
              f"rows={rows} has_time_row={has_time_row} body={body[:300]}")

        # Act: click identity to manager if needed; then report outage via UI controls
        # The UI has demo buttons; find the outage demo control
        btn_outage = page.locator("button", has_text="down 10:").first
        if not await btn_outage.count():
            btn_outage = page.locator("button", has_text="Outage").first
        if await btn_outage.count():
            await btn_outage.click()
        else:
            await page.evaluate("window.demoOutage && window.demoOutage()")
        await page.wait_for_timeout(1800)
        body2 = await page.inner_text("body")
        # The real banner is "Outage recorded: Confocal Microscope A - N
        # booking(s) affected ..." (uppercased by CSS, so compare lowercased).
        low2 = body2.lower()
        check("outage recorded" in low2 and "booking(s) affected" in low2,
              "outage banner", body2[:300])
        check("replan proposed" in low2, "replan proposed", body2[:300])
        # The chat must not show an empty range like "switched equipment (-)".
        check("switched equipment (\u2013)" not in body2
              and "switched equipment (-)" not in body2,
              "no empty equipment range in the narrative", body2[:600])
        # The board must agree with the narration: the chat says "Schedule is
        # now v2" while the panel still showed v1 and "No open outages" - a
        # self-contradicting screen at the exact moment of the demo.
        ver2 = await page.text_content("#verBadge")
        check((ver2 or "").strip() == "v2", "board version matches the narration (v2)",
              f"verBadge={ver2!r}")
        panel2 = await page.locator(".schedule-panel").inner_text()
        check("no open outages" not in panel2.lower(),
              "board shows the outage, not the pre-outage state", panel2[:300])
        check("down 10:00" in panel2 or "down 10:00\u201316:00" in panel2,
              "board shows the outage window", panel2[:300])

        # confirm card flow (elicitation)
        apply_btn = page.locator("button.green").first
        check(await apply_btn.count() > 0, "Apply button exists")
        if await apply_btn.count():
            await page.evaluate("document.querySelector('button.green').click()")
        await page.wait_for_timeout(2500)
        body3 = await page.inner_text("body")
        card = await page.locator(".confirm-card").first.is_visible() if await page.locator(".confirm-card").count() else False
        check(card or "your click" in body3.lower(), "confirm card visible")
        check("Chen" in body3 and "Wang" in body3, "card lists affected users")
        check("elicitation/create" in "\n".join(dev_logs) or "elicitation" in body3.lower(),
              "elicitation channel")
        # The "Working..." overlay must not paint over the decision card.
        card_box = await page.locator(".confirm-card").first.bounding_box() if await page.locator(".confirm-card").count() else None
        load_box = await page.locator("#loading").bounding_box() if await page.locator("#loading").count() else None
        load_visible = False
        if load_box:
            load_visible = await page.locator("#loading").is_visible()
        check(not load_visible, "no spinner over the confirm card",
              f"loading_visible={load_visible} card={card_box} loading={load_box}")
        # Belt and braces: the card must also outrank the overlay in the
        # stacking order, so a regression in either fix is caught.
        z_card = await page.evaluate(
            "getComputedStyle(document.getElementById('confirmCard')).zIndex")
        z_load = await page.evaluate(
            "getComputedStyle(document.getElementById('loading')).zIndex")
        check(int(z_card or 0) > int(z_load or 0),
              "confirm card stacks above the spinner",
              f"card_z={z_card} loading_z={z_load}")

        # decline path first (the card's button is labelled "Cancel" and has
        # id confirmNo - there is no "No" button, so a has_text lookup
        # silently missed it and the decline path never ran)
        no_btn = page.locator("#confirmNo")
        if await no_btn.count():
            await page.evaluate("document.getElementById('confirmNo').click()")
            await page.wait_for_timeout(1800)
        body4 = await page.inner_text("body")
        check(("declined" in body4.lower()) or ("nothing was applied" in body4.lower()),
              "decline path", body4[-500:])

        # re-apply -> confirm (the card's confirm button has id confirmYes)
        if await apply_btn.count():
            await page.evaluate("document.querySelector('button.green').click()")
            await page.wait_for_timeout(2500)
        yes_btn = page.locator("#confirmYes")
        if await yes_btn.count():
            await page.evaluate("document.getElementById('confirmYes').click()")
        await page.wait_for_timeout(2500)
        body5 = await page.inner_text("body")
        check("applied" in body5.lower() and "confirmed by" in body5.lower(),
              "applied + confirmed by", body5[-500:])
        ver5 = await page.text_content("#verBadge")
        check((ver5 or "").strip() == "v3", "version badge v3", f"verBadge={ver5!r}")
        check("16:00" in body5, "B4 rescheduled to 16:00", body5[-400:])
        check("11:15" in body5, "B2 rescheduled to 11:15", body5[-400:])

        # the applied line must name the zone, not a bare UTC clock
        check("london" in body5.lower(), "applied timestamp names its zone", body5[-400:])

        # audit tab: timestamps are converted to the same zone as the board
        await page.evaluate("window.setView && window.setView('audit')")
        await page.wait_for_timeout(2000)
        body_audit = await page.inner_text("body")
        check("london" in body_audit.lower(), "audit timestamps name their zone",
              body_audit[:400])

        # responsive screenshots
        await page.set_viewport_size({"width": 780, "height": 1000})
        await page.wait_for_timeout(700)
        await page.screenshot(path=os.path.join(ROOT, "web", "_responsive_780.png"), full_page=True)
        await page.set_viewport_size({"width": 1440, "height": 900})
        await page.wait_for_timeout(700)
        await page.screenshot(path=os.path.join(ROOT, "web", "_responsive_1440.png"), full_page=True)
        check(True, "responsive screenshots captured")

        await browser.close()

    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    print("\n=== %d/%d PASS ===" % (passed, total))
    if fail:
        print("failed checks:")
        for f in fail:
            print("  -", f)
    return 0 if passed == total else 1


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    finally:
        stop_servers()
