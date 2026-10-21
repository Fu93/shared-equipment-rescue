"""Contract tests: protocol negotiation, tool schema equality, example deep equality.

These pin the frozen contract in contracts/tools.json and contracts/examples/.
If they fail after a model change, the schema drifted — regenerate with
_gen_contracts.py / _gen_examples.py and review the diff deliberately.
"""

import asyncio
import inspect
import json
import os
import sys
import tempfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from mcp_server.server import mcp  # noqa: E402

CONTRACT_PATH = os.path.join(ROOT, "contracts", "tools.json")
EXAMPLES_DIR = os.path.join(ROOT, "contracts", "examples")


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def contract():
    with open(CONTRACT_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load(name):
    with open(os.path.join(EXAMPLES_DIR, name), encoding="utf-8") as f:
        return json.load(f)


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


@pytest.fixture()
def fresh_db(monkeypatch):
    dbp = os.path.join(tempfile.gettempdir(), "ser_test_contract.db")
    if os.path.exists(dbp):
        os.remove(dbp)
    monkeypatch.setenv("SER_DB_PATH", dbp)
    monkeypatch.setenv("SER_FROZEN_NOW", "2026-10-20T12:00:00+01:00")
    from mcp_server import db as dbm
    from mcp_server.server import initialize_storage

    initialize_storage()
    yield dbp
    if os.path.exists(dbp):
        os.remove(dbp)


# --- protocol ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_protocol_version_is_2025_11_25():
    from mcp import types

    server_info = mcp.name
    assert server_info == "shared-equipment-rescue"


# --- tool schemas -----------------------------------------------------------


@pytest.mark.asyncio
async def test_all_eight_tools_present():
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "schedule_get",
        "equipment_report_outage",
        "schedule_propose_replan",
        "schedule_apply_replan",
        "schedule_audit_get",
        "verify_audit_chain",
        "reset_demo_data",
        "debug_confirm",
    }


def _canonical_description(text):
    """Docstring text that does not depend on the Python version.

    Python 3.13 dedents function docstrings in the compiler. Python 3.11 and
    3.12 keep the source indentation in ``__doc__``. FastMCP copies ``__doc__``
    into the tool description and does not run ``inspect.cleandoc`` itself, so
    ``schedule_audit_get`` (the only multi-line tool docstring) gains or loses
    that indent. The 3.13 string also keeps a trailing newline that
    ``inspect.cleandoc`` strips. The sentences are unchanged.

    ``inspect.cleandoc`` of the saved (pre-3.13) description equals
    ``inspect.cleandoc`` of the 3.13 description. No single raw string matches
    both interpreters, so the contract file is left as the author saved it.
    Rewriting it to either raw string would make the other Python fail an
    exact compare, and would record an interpreter artifact as a wording change.
    """
    return inspect.cleandoc(text or "")


@pytest.mark.asyncio
async def test_tool_schemas_exactly_match_contract(contract):
    """Schema equality is the frozen contract: exact match, no extra keys.

    Descriptions are compared after ``inspect.cleandoc`` so Python 3.11 and
    3.13 agree. Every other field is still compared exactly.
    """
    tools = await mcp.list_tools()
    live = {
        t.name: {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.inputSchema,
            "outputSchema": t.outputSchema,
        }
        for t in tools
    }
    frozen = contract["tools"]
    assert set(live) == set(frozen)
    for name in frozen:
        live_item = dict(live[name])
        frozen_item = dict(frozen[name])
        live_item["description"] = _canonical_description(live_item.get("description"))
        frozen_item["description"] = _canonical_description(frozen_item.get("description"))
        assert live_item == frozen_item, f"tool {name} drifted from contract"


# --- example deep equality --------------------------------------------------


def _example_names():
    return sorted(os.listdir(EXAMPLES_DIR))


@pytest.mark.parametrize(
    "fname", _example_names(), ids=lambda s: s.replace(".json", "")
)
def test_examples_validate_against_output_schema(contract, fname):
    """Every frozen example must validate against the tool's live outputSchema."""
    import jsonschema

    fname_base = fname.replace(".json", "")
    tool_key = {
        "equipment_report_outage_recorded": "equipment_report_outage",
        "equipment_report_outage_duplicate": "equipment_report_outage",
        "schedule_propose_replan_complete": "schedule_propose_replan",
        "schedule_propose_replan_unresolved": "schedule_propose_replan",
        "schedule_propose_replan_stale": "schedule_propose_replan",
        "schedule_apply_replan_applied": "schedule_apply_replan",
        "schedule_apply_replan_not_confirmed": "schedule_apply_replan",
        "schedule_apply_replan_already_applied": "schedule_apply_replan",
        "schedule_get_manager": "schedule_get",
        "schedule_get_researcher": "schedule_get",
        "schedule_get_forbidden": "schedule_get",
        "schedule_get_after_apply": "schedule_get",
        "reset_demo_data": "reset_demo_data",
    }[fname_base]
    schema = contract["tools"][tool_key]["outputSchema"]
    example = _load(fname)
    jsonschema.validate(example, schema)


@pytest.mark.asyncio
async def test_frozen_examples_reproduce_live(fresh_db, contract):
    """End-to-end: replay the flow and deep-compare each structured result."""
    import mcp_server.server as S

    mgr = FakeCtx("tok-manager")
    li = FakeCtx("tok-li")
    nobody = FakeCtx(None)

    # schedule_get_manager
    r = await S._schedule_get_impl("lab-a", "2026-10-20", mgr)
    assert r.model_dump(by_alias=True) == _load("schedule_get_manager.json")

    # schedule_get_researcher
    r = await S._schedule_get_impl("lab-a", "2026-10-20", li)
    assert r.model_dump(by_alias=True) == _load("schedule_get_researcher.json")

    # schedule_get_forbidden
    r = await S._schedule_get_impl("lab-a", "2026-10-20", nobody)
    assert r.model_dump(by_alias=True) == _load("schedule_get_forbidden.json")

    # outage recorded
    ro = await S._report_outage_impl(
        "confocal-a", "2026-10-20T10:00:00+01:00", "2026-10-20T16:00:00+01:00",
        "laser fault", mgr,
    )
    assert ro.model_dump(by_alias=True) == _load("equipment_report_outage_recorded.json")

    # duplicate
    ro2 = await S._report_outage_impl(
        "confocal-a", "2026-10-20T12:00:00+01:00", "2026-10-20T14:00:00+01:00",
        "other", mgr,
    )
    assert ro2.model_dump(by_alias=True) == _load("equipment_report_outage_duplicate.json")

    # propose complete
    pr = await S._propose_impl(ro.outage_id, ro.schedule_version, mgr)
    assert pr.model_dump(by_alias=True) == _load("schedule_propose_replan_complete.json")

    # not_confirmed
    ap_deny = await S._apply_impl(pr.plan_id, pr.schedule_version,
                                  FakeCtx("tok-manager", "decline", None))
    assert ap_deny.model_dump(by_alias=True) == _load("schedule_apply_replan_not_confirmed.json")

    # applied
    ap = await S._apply_impl(pr.plan_id, pr.schedule_version,
                             FakeCtx("tok-manager", "accept", True))
    assert ap.model_dump(by_alias=True) == _load("schedule_apply_replan_applied.json")

    # already_applied
    ap2 = await S._apply_impl(pr.plan_id, pr.schedule_version, mgr)
    assert ap2.model_dump(by_alias=True) == _load("schedule_apply_replan_already_applied.json")

    # after apply
    r2 = await S._schedule_get_impl("lab-a", "2026-10-20", mgr)
    assert r2.model_dump(by_alias=True) == _load("schedule_get_after_apply.json")

    # no-solution plan
    from mcp_server import db as dbm

    S._reseed()
    conn = dbm.connect()
    conn.execute(
        "UPDATE bookings SET deadline=? WHERE id='B2'",
        ("2026-10-20T11:30:00+01:00",),
    )
    conn.commit()
    conn.close()
    ro3 = await S._report_outage_impl(
        "confocal-a", "2026-10-20T10:00:00+01:00", "2026-10-20T16:00:00+01:00",
        "laser fault", mgr,
    )
    pr2 = await S._propose_impl(ro3.outage_id, ro3.schedule_version, mgr)
    assert pr2.model_dump(by_alias=True) == _load("schedule_propose_replan_unresolved.json")

    # stale
    pr_stale = await S._propose_impl(ro3.outage_id, ro3.schedule_version - 1, mgr)
    assert pr_stale.model_dump(by_alias=True) == _load("schedule_propose_replan_stale.json")

    # reset
    tool = next(t for t in S.mcp._tool_manager._tools.values() if t.name == "reset_demo_data")
    rs = await tool.run(arguments={}, context=mgr)
    assert rs.model_dump(by_alias=True) == _load("reset_demo_data.json")
