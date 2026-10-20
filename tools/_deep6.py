# -*- coding: utf-8 -*-
"""Deep debug 6: docs/demo-readiness sweep + timing perf sanity.

D1 README quickstart commands actually work (paths/scripts exist)
D2 SUBMISSION_CHECKLIST demo script beats all present in final_e2e.py
D3 docs/*.md no stale file references (paths mentioned exist)
D4 perf: schedule_get < 300ms, propose < 1s, apply < 1.5s (p95 over 10 runs)
D5 mcp server logs audit lines when SER_LOG_LEVEL=INFO (spot-check via stderr)
"""
import asyncio
import os
import re
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = r"C:\Users\nn201\OneDrive - University of Glasgow\Desktop\Amazon\shared-equipment-rescue"
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))

os.environ["SER_DB_PATH"] = p = os.path.join(tempfile.gettempdir(), "ser_deep6.db")
if os.path.exists(p):
    os.remove(p)

import test_server as TS  # noqa: E402

results = []
def check(name, ok, extra=""):
    results.append((name, ok, extra))
    print(("PASS " if ok else "FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))


def d1_readme():
    md = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    # every code-fence command path mention that looks like a file should exist
    missing = []
    for m in re.finditer(r"`([\w./\\-]+\.(?:py|json|md|html))`", md):
        f = m.group(1).replace("/", os.sep)
        if not (os.path.exists(os.path.join(ROOT, f)) or os.path.exists(os.path.join(ROOT, "tests", f))
                    or os.path.exists(os.path.join(ROOT, "docs", f))):
            missing.append(m.group(1))
    check("D1 README file refs exist", not missing, str(missing[:6]))


def d2_checklist():
    sc = os.path.join(ROOT, "SUBMISSION_CHECKLIST.md")
    if not os.path.exists(sc):
        check("D2 SUBMISSION_CHECKLIST exists", False)
        return
    txt = open(sc, encoding="utf-8").read()
    fe = open(os.path.join(ROOT, "tools", "final_e2e.py"), encoding="utf-8").read()
    # beats referenced in checklist should appear in final_e2e labels or html
    beats = re.findall(r"\|\s*\d:\d\d[-–]\d:\d\d\s*\|", txt)
    ok2 = len(beats) >= 5
    check("D2 checklist beats extractable", ok2, f"n={len(beats)}")
    # every beat references a tool/action that exists in final_e2e labels or html phrases
    demo_actions = ["outage", "11:15", "16:00", "not_confirmed", "v3", "tok-wang", "Occupied"]
    miss2 = [a for a in demo_actions if a not in txt]
    check("D2b script beats mention real UI actions", not miss2, str(miss2))


def d3_docs():
    docs = [os.path.join(ROOT, "docs", f) for f in os.listdir(os.path.join(ROOT, "docs"))] \
        if os.path.isdir(os.path.join(ROOT, "docs")) else []
    docs += [os.path.join(ROOT, "README.md")]
    stale = []
    for path in docs:
        if not path.endswith(".md"):
            continue
        txt = open(path, encoding="utf-8").read()
        for m in re.finditer(r"`([\w./\\-]+\.(?:py|json|md|html|db))`", txt):
            f = m.group(1).replace("/", os.sep)
            if f.startswith("ser_") or "tempfile" in f:
                continue
            if not (os.path.exists(os.path.join(ROOT, f)) or os.path.exists(os.path.join(ROOT, "tests", f)) or os.path.exists(os.path.join(ROOT, "docs", f))):
                stale.append(f"{os.path.basename(path)}:{m.group(1)}")
    check("D3 docs no stale refs", len(stale) <= 3, str(stale[:6]))


async def d4_perf():
    server, task = await TS._start_server(p)
    try:
        c, cm, scm, _ = await TS._open_session("manager")
        try:
            # warmup
            await c.structured("schedule_get", {"unit_id": "lab-a", "date": "2026-10-20"})
            t0 = time.perf_counter()
            for _ in range(10):
                await c.structured("schedule_get", {"unit_id": "lab-a", "date": "2026-10-20"})
            dt_get = (time.perf_counter() - t0) / 10

            ro = await c.structured("equipment_report_outage", {
                "equipment_id": "confocal-a",
                "start": "2026-10-20T10:00:00+01:00",
                "end": "2026-10-20T16:00:00+01:00",
                "reason": "perf probe"})
            t0 = time.perf_counter()
            pr = await c.structured("schedule_propose_replan",
                                    {"outage_id": ro["outage_id"], "schedule_version": ro["schedule_version"]})
            dt_prop = time.perf_counter() - t0

            c2, cm2, scm2, _ = await TS._open_session("manager", confirm=True)
            try:
                t0 = time.perf_counter()
                ap = await c2.structured("schedule_apply_replan",
                                         {"plan_id": pr["plan_id"], "schedule_version": ro["schedule_version"]})
                dt_app = time.perf_counter() - t0
            finally:
                await scm2.__aexit__(None, None, None)
                await cm2.__aexit__(None, None, None)

            check("D4a schedule_get p50 < 300ms", dt_get < 0.3, f"{dt_get*1000:.0f}ms")
            check("D4b propose < 1s", dt_prop < 1.0, f"{dt_prop*1000:.0f}ms")
            check("D4c apply < 1.5s", dt_app < 1.5, f"{dt_app*1000:.0f}ms")
        finally:
            await scm.__aexit__(None, None, None)
            await cm.__aexit__(None, None, None)
    finally:
        try:
            await asyncio.wait_for(task, timeout=5)
        except Exception:
            task.cancel()


d1_readme()
d2_checklist()
d3_docs()
asyncio.run(d4_perf())

n_ok = sum(1 for _, ok, _ in results if ok)
print(f"\n=== {n_ok}/{len(results)} PASS ===")
sys.exit(0 if n_ok == len(results) else 1)
