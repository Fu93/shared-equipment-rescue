"""Full clean-room scenario check (fresh DB each run)."""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mcp_server.server as S  # noqa: E402
from mcp_server import db as dbm  # noqa: E402


class FakeReq:
    def __init__(self, token):
        self.headers = {"authorization": "Bearer " + token}

    def get(self, k, d=None):
        return self.headers.get(k, d)


class FakeRC:
    def __init__(self, token):
        self.request = FakeReq(token)


class FakeCtx:
    def __init__(self, token=None, elicit_action=None, elicit_data=None):
        self.request_context = FakeRC(token)
        self._el = (elicit_action, elicit_data)

    async def elicit(self, msg, schema):
        act, data = self._el

        class R:
            pass

        r = R()
        r.action = act
        if data is None:
            r.data = None
        else:

            class D:
                def __init__(self, c):
                    self.confirm = c

            r.data = D(data)
        return r


async def main():
    dbp = os.path.join(tempfile.gettempdir(), "ser_fresh2.db")
    if os.path.exists(dbp):
        os.remove(dbp)
    os.environ["SER_DB_PATH"] = dbp
    S.initialize_storage()
    mgr = FakeCtx("tok-manager")
    ro = await S._report_outage_impl(
        "confocal-a", "2026-10-20T10:00:00+01:00", "2026-10-20T16:00:00+01:00",
        "laser fault", mgr,
    )
    pr = await S._propose_impl(ro.outage_id, ro.schedule_version, mgr)
    print("P1:", pr.status,
          [(c.booking_id, c.new_equipment, c.new_start[11:16], c.new_end[11:16]) for c in pr.changes],
          "unr:", [(u.booking_id,) for u in pr.unresolved])
    ap = await S._apply_impl(pr.plan_id, pr.schedule_version,
                             FakeCtx("tok-manager", "accept", True))
    print("apply:", ap.status, "v", ap.new_version)

    # no-solution scenario
    S._reseed()
    conn = dbm.connect()
    conn.execute(
        "UPDATE bookings SET deadline=? WHERE id='B2'",
        ("2026-10-20T11:30:00+01:00",),
    )
    conn.commit()
    conn.close()
    print("--- no-solution scenario ---")
    ro2 = await S._report_outage_impl(
        "confocal-a", "2026-10-20T10:00:00+01:00", "2026-10-20T16:00:00+01:00",
        "laser", mgr,
    )
    pr2 = await S._propose_impl(ro2.outage_id, ro2.schedule_version, mgr)
    print("P2:", pr2.status,
          [(c.booking_id, c.new_equipment, c.new_start[11:16], c.new_end[11:16]) for c in pr2.changes])
    for u in pr2.unresolved:
        print("  unresolved:", u.booking_id, "movable", u.movable,
              [r.code for r in u.reasons])
        for e in u.earliest_possible:
            print("    ep:", e.equipment_id, e.status, e.earliest_start,
                  e.earliest_finish, [(r.code, r.at_least) for r in e.would_work_if])
    ap2 = await S._apply_impl(pr2.plan_id, pr2.schedule_version,
                              FakeCtx("tok-manager", "accept", True))
    print("apply:", ap2.status, "v", ap2.new_version,
          "unresolved:", [u.booking_id for u in ap2.unresolved])
    sg = await S._schedule_get_impl("lab-a", "2026-10-20", mgr)
    for b in sg.model_dump(by_alias=True)["bookings"]:
        if b["status"] in ("unresolved", "blocked"):
            print("  ", b["id"], b["status"], b["start"][11:16])
    print("open outages:",
          [(o.id, o.resolved, o.unresolved_booking_ids) for o in sg.open_outages])


asyncio.run(main())
