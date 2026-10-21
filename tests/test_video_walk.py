# -*- coding: utf-8 -*-
"""Walk the demo video script scene by scene and assert what the judge sees.

SUBMISSION_CHECKLIST.md section 2 lists the 2:30-2:50 script. Each scene has
a stated on-screen state. This walks the real UI and checks every stated
claim, so "the demo works" is an observation, not an assumption.

This is the recording gate: if a scene's on-screen state is wrong, the video
would show something the narration does not claim (or contradicts). It needs
Playwright; on a machine where the browser cannot launch the test skips
rather than fails, so it never blocks the rest of the suite.
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
results = []


def check(scene, name, ok, extra=""):
    results.append((scene, name, ok))
    print(("PASS " if ok else "FAIL ") + f"[{scene}] " + name +
          (f"  [{extra}]" if extra and not ok else ""))


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
def test_demo_video_script_walkthrough():
    """Every scene the video script promises actually appears on screen."""
    failures = asyncio.run(_walk())
    assert not failures, "\n".join(f"[{s}] {n}" for s, n in failures)


async def _walk():
    from playwright.async_api import async_playwright

    dbp = os.path.join(tempfile.gettempdir(), "ser_video_walk.db")
    for suf in ("", "-wal", "-shm"):
        if os.path.exists(dbp + suf):
            os.remove(dbp + suf)
    env = dict(os.environ)
    env["SER_DB_PATH"] = dbp
    env["PYTHONUTF8"] = "1"
    # Ephemeral ports: the test must never fight a running demo (or another
    # test) for :8765 / :8080.
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

    boot = os.path.join(tempfile.gettempdir(), f"ser_videowalk_mcp_{os.getpid()}.py")
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
    try:
        import httpx
        dl = time.time() + 30
        up = False
        while time.time() < dl and not up:
            try:
                if httpx.get(web_url, timeout=2).status_code == 200:
                    up = True
                    break
            except httpx.HTTPError:
                pass
            if mcp.poll() is not None or web.poll() is not None:
                raise RuntimeError(
                    f"server died early: mcp_rc={mcp.poll()} web_rc={web.poll()} "
                    f"(mcp_port={mcp_port} web_port={web_port})"
                )
            time.sleep(0.3)
        if not up:
            raise RuntimeError(f"web proxy never came up on {web_url}")

        async with async_playwright() as pw:
            b = await pw.chromium.launch()
            page = await b.new_page(viewport={"width": 1440, "height": 900})
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            await page.goto(web_url, wait_until="load")
            await page.wait_for_timeout(3000)

            # SCENE 0:15-0:40 - initial board: 6 bookings, 2 confocals
            panel = await page.locator(".schedule-panel").inner_text()
            body = await page.inner_text("body")
            check("0:00", "six bookings on the board", panel.count("·") >= 6, panel[:200])
            check("0:00", "two confocales", "confocal microscope a" in panel.lower()
                  and "confocal microscope b" in panel.lower(), panel[:200])
            check("0:00", "MCP dev console shows real tools/call",
                  "tools/call" in body.lower(), body[:200])
            check("0:00", "protocol version shown", "2025-11-25" in body, body[:200])
            check("0:00", "no JS errors", not errs, str(errs[:2]))

            # The badge row must not overlap: the connection lamp used to be
            # a fixed overlay that sat on top of the transport badge, so a
            # screenshot taken for the video showed both stacked on each
            # other. Any two visible boxes in the bar must not intersect.
            boxes = {}
            for sel in ("#verBadge", "#roleBadge", "#chainBadge", "#ledgerBadge",
                        "#connLamp"):
                loc = page.locator(sel)
                if await loc.count():
                    bb = await loc.first.bounding_box()
                    if bb:
                        boxes[sel] = bb
            overlaps = []
            keys = list(boxes)
            for i in range(len(keys)):
                for j in range(i + 1, len(keys)):
                    box_a, box_b = boxes[keys[i]], boxes[keys[j]]
                    if (box_a["x"] < box_b["x"] + box_b["width"]
                            and box_b["x"] < box_a["x"] + box_a["width"]
                            and box_a["y"] < box_b["y"] + box_b["height"]
                            and box_b["y"] < box_a["y"] + box_a["height"]):
                        overlaps.append(f"{keys[i]} x {keys[j]}")
            check("0:00", "badge row has no overlapping elements",
                  not overlaps, str(overlaps))
            # and the lamp must be readable, not clipped by the panel edge
            lamp = boxes.get("#connLamp")
            check("0:00", "connection lamp is inside the viewport",
                  lamp is not None and lamp["x"] >= 0
                  and lamp["x"] + lamp["width"] <= 1440,
                  str(lamp))

            # SCENE 0:15-0:40 - report outage -> B2/B4 blocked, version v2
            await page.evaluate("window.reportOutageFlow()")
            await page.wait_for_timeout(3000)
            panel = await page.locator(".schedule-panel").inner_text()
            body = await page.inner_text("body")
            check("0:15", "version badge v2", "v2" in (await page.text_content("#verBadge") or ""),
                  await page.text_content("#verBadge"))
            check("0:15", "outage banner on the board", "down 10:00" in panel.lower(),
                  panel[:200])
            check("0:15", "narrator explains the outage",
                  "outage recorded" in body.lower(), body[:200])

            # SCENE 0:40-1:20 - propose card: Chen->B 11:15-12:15, Wang->A 16:00-17:00
            check("0:40", "proposal narrated with both moves",
                  "11:15" in body and "16:00" in body, body[-400:])
            check("0:40", "machine-readable reasons shown",
                  "deadline" in body.lower() or "outage window" in body.lower(),
                  body[-400:])

            # SCENE 1:45-2:10 - elicitation card
            await page.locator("button.green").first.click()
            await page.wait_for_timeout(3000)
            card_visible = await page.locator("#confirmCard").is_visible()
            check("1:45", "confirm card opens", card_visible)
            card = await page.locator("#confirmCard").inner_text() if card_visible else ""
            check("1:45", "card names the human-in-the-loop rule",
                  "only your click" in card.lower(), card[:200])
            check("1:45", "card lists both affected users",
                  "Chen" in card and "Wang" in card, card[:300])
            check("1:45", "card has Confirm and Cancel",
                  "Confirm" in card and "Cancel" in card, card[:200])

            # SCENE 1:45-2:10 - Cancel -> nothing applied
            await page.evaluate("document.getElementById('confirmNo').click()")
            await page.wait_for_timeout(2500)
            body = await page.inner_text("body")
            check("1:45", "cancel leaves the schedule unchanged",
                  "nothing was applied" in body.lower(), body[-300:])
            check("1:45", "version still v2 after cancel",
                  (await page.text_content("#verBadge") or "").strip() == "v2",
                  await page.text_content("#verBadge"))

            # SCENE 1:45-2:10 - Confirm -> applied v3
            await page.locator("button.green").first.click()
            await page.wait_for_timeout(3000)
            await page.evaluate("document.getElementById('confirmYes').click()")
            await page.wait_for_timeout(3000)
            body = await page.inner_text("body")
            panel = await page.locator(".schedule-panel").inner_text()
            check("1:45", "apply confirmed by the manager",
                  "confirmed by" in body.lower(), body[-300:])
            check("1:45", "version badge v3",
                  (await page.text_content("#verBadge") or "").strip() == "v3",
                  await page.text_content("#verBadge"))
            check("1:45", "board shows B4 at 16:00", "16:00" in panel, panel[:300])
            check("1:45", "board shows B2 at 11:15", "11:15" in panel, panel[:300])

            # SCENE 2:10-2:30 - switch identity to wang: own booking + masked others
            await page.select_option("#userSelect", "tok-wang")
            await page.wait_for_timeout(3000)
            panel = await page.locator(".schedule-panel").inner_text()
            body = await page.inner_text("body")
            check("2:10", "acting as Wang", "wang" in
                  (await page.text_content("#roleBadge") or "").lower(),
                  await page.text_content("#roleBadge"))
            check("2:10", "other people's slots are masked as Occupied",
                  "Occupied" in panel, panel[:400])
            check("2:10", "Wang still sees his own new slot", "16:00" in panel,
                  panel[:400])
            check("2:10", "no JS errors across the whole flow", not errs, str(errs[:2]))

            # SCENE 2:30-2:50 - audit tab: chain badge + rows
            await page.evaluate("window.setView('audit')")
            await page.wait_for_timeout(2500)
            body = await page.inner_text("body")
            check("2:30", "audit tab shows the trail",
                  "OUTAGE" in body or "APPLY" in body, body[:400])
            check("2:30", "timestamps are labelled with the zone",
                  "london" in body.lower(), body[:300])
            check("2:30", "no JS errors at the end", not errs, str(errs[:2]))

            await b.close()
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

    n_ok = sum(1 for _, _, ok in results if ok)
    print(f"\n=== {n_ok}/{len(results)} PASS ===")
    failed = [(s, n) for s, n, ok in results if not ok]
    if failed:
        print("failed:")
        for s, n in failed:
            print(f"  [{s}] {n}")
    return failed


if __name__ == "__main__":
    bad = asyncio.run(_walk())
    sys.exit(1 if bad else 0)
