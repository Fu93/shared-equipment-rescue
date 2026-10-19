"""Generate contracts/examples/*.json from a fresh live server flow.

Run from repo root:  python _gen_examples.py
Each example is the structuredContent of one tool call in sequence:
reset → get(manager) → outage → propose → apply → get-after.
"""

import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mcp_server.server as S  # noqa: E402
from mcp_server import db as dbm  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EX_DIR = os.path.join(HERE, "contracts", "examples")


class FakeReq:
    def __init__(self, token):
        self.headers = {"authorization": "Bearer " + token} if token else {}

    def get(self, k, d=None):
        return self.headers.get(k, d)


class FakeRC:
    def __init__(self, token):
        self.request = FakeReq(token)


class FakeCtx:
    def __init__(self, token, elicit_action=None, elicit_data=None):
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


def dump(obj) -> dict:
    return obj.model_dump(by_alias=True)


async def main():
    os.environ["SER_FROZEN_NOW"] = "2026-10-20T12:00:00+01:00"
    dbp = os.path.join(tempfile.gettempdir(), "ser_examples.db")
    if os.path.exists(dbp):
        os.remove(dbp)
    os.environ["SER_DB_PATH"] = dbp
    S.initialize_storage()
    mgr = FakeCtx("tok-manager")

    os.makedirs(EX_DIR, exist_ok=True)

    examples = {}

    # 1. schedule_get (manager, fresh)
    r = await S._schedule_get_impl("lab-a", "2026-10-20", mgr)
    examples["schedule_get_manager.json"] = dump(r)

    # 2. schedule_get (researcher masked)
    r = await S._schedule_get_impl("lab-a", "2026-10-20", FakeCtx("tok-li"))
    examples["schedule_get_researcher.json"] = dump(r)

    # 3. schedule_get forbidden
    r = await S._schedule_get_impl("lab-a", "2026-10-20", FakeCtx(None))
    examples["schedule_get_forbidden.json"] = dump(r)

    # 4. report_outage recorded
    ro = await S._report_outage_impl(
        "confocal-a", "2026-10-20T10:00:00+01:00", "2026-10-20T16:00:00+01:00",
        "laser fault", mgr,
    )
    examples["equipment_report_outage_recorded.json"] = dump(ro)

    # 5. duplicate outage
    ro_dup = await S._report_outage_impl(
        "confocal-a", "2026-10-20T12:00:00+01:00", "2026-10-20T14:00:00+01:00",
        "other", mgr,
    )
    examples["equipment_report_outage_duplicate.json"] = dump(ro_dup)

    # 6. propose (complete plan)
    pr = await S._propose_impl(ro.outage_id, ro.schedule_version, mgr)
    examples["schedule_propose_replan_complete.json"] = dump(pr)

    # 7. not_confirmed (decline)
    ap_deny = await S._apply_impl(pr.plan_id, pr.schedule_version,
                                  FakeCtx("tok-manager", "decline", None))
    examples["schedule_apply_replan_not_confirmed.json"] = dump(ap_deny)

    # 8. apply applied
    ap = await S._apply_impl(pr.plan_id, pr.schedule_version,
                             FakeCtx("tok-manager", "accept", True))
    examples["schedule_apply_replan_applied.json"] = dump(ap)

    # 9. already_applied
    ap2 = await S._apply_impl(pr.plan_id, pr.schedule_version, mgr)
    examples["schedule_apply_replan_already_applied.json"] = dump(ap2)

    # 10. schedule_get after apply
    r2 = await S._schedule_get_impl("lab-a", "2026-10-20", mgr)
    examples["schedule_get_after_apply.json"] = dump(r2)

    # 11. no-solution plan: reseed, deadline 11:30 on B2
    S._reseed()
    conn = dbm.connect()
    conn.execute(
        "UPDATE bookings SET deadline=? WHERE id='B2'",
        ("2026-10-20T11:30:00+01:00",),
    )
    conn.commit()
    conn.close()
    ro2 = await S._report_outage_impl(
        "confocal-a", "2026-10-20T10:00:00+01:00", "2026-10-20T16:00:00+01:00",
        "laser fault", mgr,
    )
    pr2 = await S._propose_impl(ro2.outage_id, ro2.schedule_version, mgr)
    examples["schedule_propose_replan_unresolved.json"] = dump(pr2)

    # 12. stale propose
    pr_stale = await S._propose_impl(ro2.outage_id, ro2.schedule_version - 1, mgr)
    examples["schedule_propose_replan_stale.json"] = dump(pr_stale)

    # 13. reset
    rs = await S.reset_demo_data.fn(mgr) if hasattr(S.reset_demo_data, "fn") else None
    if rs is None:
        # tool decorator returns a function wrapper; call via tool_manager
        tool = next(t for t in S.mcp._tool_manager._tools.values() if t.name == "reset_demo_data")
        rs = await tool.run(arguments={}, context=mgr)
    examples["reset_demo_data.json"] = dump(rs)

    for fname, doc in examples.items():
        with open(os.path.join(EX_DIR, fname), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
    print("wrote", len(examples), "examples:", sorted(examples))


asyncio.run(main())
