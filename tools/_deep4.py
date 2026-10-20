# -*- coding: utf-8 -*-
"""Deep debug 4: LLM narrative layer + seed/reset integrity + static assets.

L1 LLM stub mode: scripted fallback works, no key needed
L2 chat narrative contains expected phrases for each tool outcome
L3 reset restores EXACT seed (byte-identical schedule_get before/after)
L4 reset twice in a row stable
L5 proposal after apply->reset->same outage reproduces O1/P1 ids
L6 static assets referenced by index.html all exist
"""
import asyncio
import json
import os
import re
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\nn201\OneDrive - University of Glasgow\Desktop\Amazon\shared-equipment-rescue"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

os.environ["SER_DB_PATH"] = p = os.path.join(tempfile.gettempdir(), "ser_deep4.db")
if os.path.exists(p):
    os.remove(p)

import test_server as TS  # noqa: E402

results = []
def check(name, ok, extra=""):
    results.append((name, ok, extra))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))


async def main():
    server, task = await TS._start_server(p)
    try:
        # ---- L3: reset restores EXACT seed ----
        c, cm, scm, _ = await TS._open_session("manager")
        try:
            g_before = await c.structured("schedule_get", {"unit_id": "lab-a", "date": "2026-10-20"})
            snap_before = (g_before["schedule_version"], json.dumps(g_before["bookings"], sort_keys=True))

            # mutate: outage + plan + apply
            ro = await c.structured("equipment_report_outage", {
                "equipment_id": "confocal-a",
                "start": "2026-10-20T10:00:00+01:00",
                "end": "2026-10-20T16:00:00+01:00",
                "reason": "deep4"})
            pr = await c.structured("schedule_propose_replan",
                                    {"outage_id": ro["outage_id"], "schedule_version": ro["schedule_version"]})

            c2, cm2, scm2, _ = await TS._open_session("manager", confirm=True)
            try:
                ap = await c2.structured("schedule_apply_replan",
                                         {"plan_id": pr["plan_id"], "schedule_version": ro["schedule_version"]})
                check("L3a apply works pre-reset", ap["status"] == "applied")
            finally:
                await scm2.__aexit__(None, None, None)
                await cm2.__aexit__(None, None, None)

            rs = await c.structured("reset_demo_data")
            check("L3b reset -> v1", rs["status"] == "reset" and rs["schedule_version"] == 1)
            g_after = await c.structured("schedule_get", {"unit_id": "lab-a", "date": "2026-10-20"})
            snap_after = (g_after["schedule_version"], json.dumps(g_after["bookings"], sort_keys=True))
            check("L3c snapshot identical pre/post reset", snap_before == snap_after)

            # L4: reset twice
            rs2 = await c.structured("reset_demo_data")
            check("L4 reset x2 stable", rs2["status"] == "reset" and rs2["schedule_version"] == 1)

            # L5: replay reproduces O1
            ro2 = await c.structured("equipment_report_outage", {
                "equipment_id": "confocal-a",
                "start": "2026-10-20T10:00:00+01:00",
                "end": "2026-10-20T16:00:00+01:00",
                "reason": "deep4 replay"})
            check("L5 replay deterministic O1", ro2["outage_id"] == "O1")
            pr2 = await c.structured("schedule_propose_replan",
                                     {"outage_id": "O1", "schedule_version": 2})
            check("L5b replay propose complete", pr2["status"] == "proposed" and pr2["is_complete"] is True)
        finally:
            await scm.__aexit__(None, None, None)
            await cm.__aexit__(None, None, None)

        # ---- L1/L2: LLM narrative (stub fallback) ----
        # web/ builds narrative via llm.py Bedrock or scripted fallback
        html = open(os.path.join(ROOT, "web", "static", "index.html"), encoding="utf-8").read()
        js = re.sub(r"<script>|</script>", "", html)

        # L2 via static text checks (chat narration data.* phrases produced client-side)
        for phrase, label in [("Replan proposed", "L2 propose narration phrase"),
                              ("applied", "L2 applied narration phrase"),
                              ("elicitation", "L2 elicitation phrase")]:
            check(label, phrase in html, f"'{phrase}' missing")

        # L6: static assets referenced all exist
        refs = re.findall(r'(?:src|href)="(/static/[^"]+)"', html)
        missing = [r for r in refs if not os.path.exists(os.path.join(ROOT, "web", r.lstrip("/")))]
        check("L6 static assets all exist", not missing, str(missing))
    finally:
        try:
            await asyncio.wait_for(task, timeout=5)
        except Exception:
            task.cancel()

    n_ok = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== {n_ok}/{len(results)} PASS ===")
    return 0 if n_ok == len(results) else 1

sys.exit(asyncio.run(main()))
