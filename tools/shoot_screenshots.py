# -*- coding: utf-8 -*-
"""Regenerate the demo screenshots (_shot_1..6.png) from the CURRENT build.

The old screenshots were captured on 2026-10-20 and showed a UI that no
longer exists: the "Priya" name, the raw reason dump
("equipment_id=null booking_id=null ..."), an empty "switched equipment (-)"
range, and the "Working..." spinner painting on top of the confirm card.

Run:  python -X utf8 tools/shoot_screenshots.py

Each shot corresponds to a beat of the video script in
SUBMISSION_CHECKLIST.md section 2:

  _shot_1_initial.png     0:00-0:15  six bookings, two confocals, dev console
  _shot_2_outage.png      0:15-0:40  outage recorded, board at v2, B2/B4 blocked
  _shot_3_proposed.png    0:40-1:20  the proposal, both moves, machine-readable reasons
  _shot_4_elicit.png      1:45-2:10  the elicitation confirm card
  _shot_5_applied.png     1:45-2:10  applied, schedule at v3
  _shot_6_wang_after.png  2:10-2:30  acting as Wang: his own slot, others masked

The servers run on ephemeral ports so this never fights a running demo,
and they are always stopped again.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile


def _popen_kwargs():
    # CREATE_NO_WINDOW (0x08000000) is Windows-only. Passing it on Linux or
    # macOS raises ValueError and the child process never starts.
    if os.name == "nt":
        return {"creationflags": 0x08000000}
    return {}
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Two destinations:
#   docs/screenshots/  - the curated, version-controlled copies a judge sees
#   web/               - the live capture output (recording scratch, ignored)
SHOTS = os.path.join(ROOT, "docs", "screenshots")
SCRATCH = os.path.join(ROOT, "web")
VIEWPORT = {"width": 1500, "height": 900}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def main() -> int:
    from playwright.async_api import async_playwright

    dbp = os.path.join(tempfile.gettempdir(), "ser_screenshots.db")
    for suf in ("", "-wal", "-shm"):
        if os.path.exists(dbp + suf):
            os.remove(dbp + suf)
    env = dict(os.environ)
    env["SER_DB_PATH"] = dbp
    env["PYTHONUTF8"] = "1"
    env["SER_DEMO_DATE"] = "2026-10-20"
    env["SER_DEMO_TZ"] = "Europe/London"
    env["SER_LLM_MODE"] = "scripted"

    mcp_port = _free_port()
    web_port = _free_port()
    while web_port == mcp_port:
        web_port = _free_port()
    web_url = f"http://127.0.0.1:{web_port}"

    boot = os.path.join(tempfile.gettempdir(), f"ser_shots_mcp_{os.getpid()}.py")
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
                           **_popen_kwargs())
    web = subprocess.Popen([sys.executable, "-X", "utf8", "app.py",
                            "--port", str(web_port), "--mcp-port", str(mcp_port)],
                           cwd=os.path.join(ROOT, "web"), env=env,
                           **_popen_kwargs(),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    taken = []
    try:
        import httpx
        dl = time.time() + 30
        while time.time() < dl:
            try:
                if httpx.get(web_url, timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.3)

        async with async_playwright() as pw:
            b = await pw.chromium.launch()
            page = await b.new_page(viewport=VIEWPORT)
            await page.goto(web_url, wait_until="load")
            await page.wait_for_timeout(3500)

            async def shot(name: str) -> None:
                # Write the curated copy (version-controlled) and the live
                # scratch copy (recording material) side by side.
                for folder in (SHOTS, SCRATCH):
                    os.makedirs(folder, exist_ok=True)
                    await page.screenshot(path=os.path.join(folder, name))
                taken.append(name)
                print(f"  captured {name}")

            async def facts() -> dict:
                """The facts this frame shows, as text.

                Recorded next to the image so the staleness test can compare
                them with a fresh render. Comparing images is unreliable (a
                PNG is compressed and a re-capture is never bit-identical);
                comparing text is exact.
                """
                panel = await page.locator(".schedule-panel").inner_text()
                chat = await page.locator(".chat-panel").inner_text()
                return {
                    "panel": panel,
                    "chat": chat,
                    "verBadge": (await page.text_content("#verBadge") or "").strip(),
                    "roleBadge": (await page.text_content("#roleBadge") or "").strip(),
                }

            print("capturing...")
            frames = {}

            # 1 - the initial board
            await shot("_shot_1_initial.png")
            frames["_shot_1_initial.png"] = await facts()

            # 2 - the outage, board at v2 with B2/B4 blocked
            await page.evaluate("window.reportOutageFlow()")
            await page.wait_for_timeout(3500)
            await shot("_shot_2_outage.png")
            frames["_shot_2_outage.png"] = await facts()

            # 3 - the proposal
            await page.wait_for_timeout(1500)
            await shot("_shot_3_proposed.png")
            frames["_shot_3_proposed.png"] = await facts()

            # 4 - the elicitation confirm card
            apply_btn = page.locator("button.green").first
            if await apply_btn.count():
                await apply_btn.click()
            await page.wait_for_timeout(3000)
            await shot("_shot_4_elicit.png")
            frames["_shot_4_elicit.png"] = await facts()

            # 5 - applied, v3
            if await page.locator("#confirmYes").count():
                await page.evaluate("document.getElementById('confirmYes').click()")
            await page.wait_for_timeout(3500)
            await shot("_shot_5_applied.png")
            frames["_shot_5_applied.png"] = await facts()

            # 6 - acting as Wang: his own new slot, everyone else masked
            await page.select_option("#userSelect", "tok-wang")
            await page.wait_for_timeout(3500)
            await shot("_shot_6_wang_after.png")
            frames["_shot_6_wang_after.png"] = await facts()

            # The manifest travels with the images: it is what the staleness
            # test compares, because text compares exactly and images do not.
            manifest = os.path.join(SHOTS, "manifest.json")
            with open(manifest, "w", encoding="utf-8") as f:
                json.dump(frames, f, ensure_ascii=False, indent=1, sort_keys=True)
            print("  wrote", manifest)

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

    print(f"\n{len(taken)} screenshots written to {SHOTS}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
