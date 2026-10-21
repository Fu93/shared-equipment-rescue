"""Final acceptance dry-run: entire demo flow over real MCP transport.

Self-contained: temp DB, spawns server (task), runs a real client, asserts
the video script针 for each beat, resets, verifies seed restore, exits 0.
"""

import asyncio
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import httpx
from mcp import ClientSession, types
from mcp.client.streamable_http import streamablehttp_client

URL = "http://127.0.0.1:0/mcp"  # resolved after boot (ephemeral port)
DAY = "2026-10-20"
TOKENS = {"manager": "tok-manager", "chen": "tok-chen", "li": "tok-li"}


def make_client_cls(confirm: bool):
    async def elicita(message, schema):
        return types.ElicitResult(
            action="accept" if confirm else "decline",
            content={"confirm": confirm} if confirm else None,
        )
    return elicita


async def connect(token, confirm=False):
    headers = {"authorization": f"Bearer {TOKENS[token]}"}
    elic = make_client_cls(confirm)
    hcm = streamablehttp_client(URL, headers=headers)
    r, w, _ = await hcm.__aenter__()
    scm = ClientSession(r, w, elicitation_callback=elic)
    session = await scm.__aenter__()
    await session.initialize()
    return hcm, scm, session


def _bound_port(server) -> int:
    ports = [sock.getsockname()[1] for s in (getattr(server, "servers", None) or [])
             for sock in (getattr(s, "sockets", None) or [])]
    assert len(ports) == 1, f"expected exactly one bound port, got {ports}"
    return ports[0]


async def call(session, name, args=None):
    res = await session.call_tool(name, args or {})
    assert res.isError is False, res.content
    return res.structuredContent


def check(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    return cond


async def main():
    dbp = os.path.join(tempfile.gettempdir(), "ser_final_e2e.db")
    if os.path.exists(dbp):
        os.remove(dbp)
    os.environ["SER_DB_PATH"] = dbp
    os.environ.setdefault("SER_DEMO_DATE", "2026-10-20")
    os.environ.setdefault("SER_DEMO_TZ", "Europe/London")
    # the suite fires sessions faster than any real client; a token bucket
    # built for untrusted traffic must not flake the acceptance run
    # (same policy as tests/test_server.py)
    os.environ.setdefault("SER_NO_RATE_LIMIT", "1")

    import uvicorn
    from mcp_server.server import build_app

    app = build_app()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    srv = uvicorn.Server(cfg)
    task = asyncio.create_task(srv.serve())
    for _ in range(100):
        if srv.started:
            break
        if task.done():
            raise RuntimeError(f"uvicorn failed to start: {task.exception()!r}")
        await asyncio.sleep(0.05)
    if not srv.started:
        raise RuntimeError("uvicorn did not start within 5 seconds")
    global URL
    URL = f"http://127.0.0.1:{_bound_port(srv)}/mcp"

    ok = True
    try:
        # ---- Act 1: manager views the day ----
        h, s, sess = await connect("manager")
        g = await call(sess, "schedule_get")
        ok &= check(g["status"] == "ok" and g["schedule_version"] == 1, "A1 baseline version 1")
        ok &= check(len(g["bookings"]) == 6 and len(g["equipment"]) == 2, "A1 six bookings, two confocals")

        # researcher masking
        h2, s2, sess2 = await connect("li")
        g2 = await call(sess2, "schedule_get")
        masked = [b for b in g2["bookings"] if b["masked"]]
        own = [b for b in g2["bookings"] if not b["masked"]]
        ok &= check(len(own) == 2 and len(masked) == 4 and all(
            b["user"] == "Occupied" and b["user_id"] is None for b in masked),
            "A1 researcher sees own 2 + 4 masked 'Occupied'")
        await s2.__aexit__(None, None, None); await h2.__aexit__(None, None, None)

        # ---- Act 2: outage hits ----
        ro = await call(sess, "equipment_report_outage", {
            "equipment_id": "confocal-a",
            "start": f"{DAY}T10:00:00+01:00", "end": f"{DAY}T16:00:00+01:00",
            "reason": "laser fault, service call booked",
        })
        ok &= check(ro["status"] == "recorded" and ro["outage_id"] == "O1"
                    and ro["schedule_version"] == 2, "A2 outage recorded, version 2")
        ok &= check(sorted(b["id"] for b in ro["affected_bookings"]) == ["B2", "B4"],
                    "A2 exactly B2+B4 blocked")

        # ---- Act 3: propose ----
        pr = await call(sess, "schedule_propose_replan",
                        {"outage_id": "O1", "schedule_version": 2})
        ok &= check(pr["status"] == "proposed" and pr["is_complete"] is True,
                    "A3 proposed & complete")
        ok &= check([(c["booking_id"], c["new_equipment"],
                      c["new_start"][11:16], c["new_end"][11:16]) for c in pr["changes"]]
                    == [("B2", "confocal-b", "11:15", "12:15"),
                        ("B4", "confocal-a", "16:00", "17:00")],
                    "A3 changes: B2→B 11:15-12:15, B4→A 16:00-17:00")
        ok &= check(any(r["code"] == "original_slot_in_outage" for r in pr["changes"][0]["reasons"])
                    and any(r["code"] == "switched_equipment"
                            for r in pr["changes"][0]["reasons"]),
                    "A3 machine-readable reasons include slot-in-outage/switched-equipment")

        # ---- Act 4: decline apply → no effect ----
        hd, sd, sessd = await connect("manager", confirm=False)
        der = await call(sessd, "schedule_apply_replan",
                         {"plan_id": pr["plan_id"], "schedule_version": 2})
        ok &= check(der["status"] == "not_confirmed", "A4 declined → not_confirmed")
        g4 = await call(sessd, "schedule_get")
        ok &= check(g4["schedule_version"] == 2, "A4 version unchanged after decline")
        blk = [b for b in g4["bookings"] if b["status"] == "blocked"]
        ok &= check(len(blk) == 2, "A4 bookings still blocked (no side effect)")
        await sd.__aexit__(None, None, None); await hd.__aexit__(None, None, None)

        # ---- Act 5: confirm → applied ----
        # sess was opened via connect("manager") (default confirm=False, matching
        # the read-only default); for this act we open a TRUE accepting session.
        h5, s5, sess5 = await connect("manager", confirm=True)
        ap = await call(sess5, "schedule_apply_replan",
                        {"plan_id": pr["plan_id"], "schedule_version": 2})
        ok &= check(ap["status"] == "applied" and ap["new_version"] == 3,
                    "A5 applied, version 3")
        ok &= check((ap["confirmed_by"] or {}).get("user_id") == "user-manager",
                    "A5 confirmed_by=manager (got %r)" % (ap["confirmed_by"],))

        # idempotency
        ap2 = await call(sess5, "schedule_apply_replan",
                         {"plan_id": pr["plan_id"], "schedule_version": 3})
        ok &= check(ap2["status"] == "already_applied", "A5 re-apply → already_applied")

        # post-state
        g5 = await call(sess5, "schedule_get")
        b2 = next(b for b in g5["bookings"] if b["id"] == "B2")
        b4 = next(b for b in g5["bookings"] if b["id"] == "B4")
        ok &= check(b2["equipment"] == "confocal-b" and b2["start"][11:16] == "11:15"
                    and b2["status"] == "confirmed", "A5 B2 now confirmed on B 11:15")
        ok &= check(b4["equipment"] == "confocal-a" and b4["start"][11:16] == "16:00",
                    "A5 B4 now on A 16:00")

        # ---- Act 6: duplicate outage ----
        dup = await call(sess5, "equipment_report_outage", {
            "equipment_id": "confocal-a",
            "start": f"{DAY}T11:00:00+01:00", "end": f"{DAY}T12:00:00+01:00",
        })
        ok &= check(dup["status"] == "duplicate_outage"
                    and dup["schedule_version"] == 3, "A6 duplicate rejected, no bump")

        # ---- Act 7: reset to seed ----
        rs = await call(sess5, "reset_demo_data")
        ok &= check(rs["status"] == "reset" and rs["schedule_version"] == 1, "A7 reset → version 1")

        # replay round-trip after reset
        ro2 = await call(sess5, "equipment_report_outage", {
            "equipment_id": "confocal-a",
            "start": f"{DAY}T10:00:00+01:00", "end": f"{DAY}T16:00:00+01:00",
        })
        ok &= check(ro2["outage_id"] == "O1", "A7 re-run reproducible O1")

        await s5.__aexit__(None, None, None); await h5.__aexit__(None, None, None)
        await s.__aexit__(None, None, None); await h.__aexit__(None, None, None)

        print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
        return 0 if ok else 1
    finally:
        srv.should_exit = True
        try:
            await asyncio.wait_for(task, 5)
        except Exception:
            task.cancel()
        if os.path.exists(dbp):
            os.remove(dbp)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
