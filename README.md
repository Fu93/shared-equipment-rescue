# Shared Equipment Rescue

**A facility manager's AI copilot for shared-instrument outage recovery — a self-hosted MCP 2025-11-25 server that detects every booking an outage breaks, proposes a rule-checked replan, and never writes a single change without explicit human confirmation (MCP elicitation, human-in-the-loop).**

Amazon "Build, Ship, Shape" hackathon entry — **Alexa+ primary track** + **AWS Builder challenge** (Amazon Bedrock).

## What it does

When a confocal microscope (or any shared instrument) goes down mid-day, a manager normally rebooks six papers by hand. This server does the whole recovery loop over MCP:

1. **Report** the outage → engine instantly marks affected bookings `blocked`, bumps `schedule_version`, writes an audit log row.
2. **Propose** a replan → greedy scheduler searches 15-minute increments, FIFO by deadline, enforcing operating hours, per-user equipment permissions, personal calendars, hard deadlines, and a 15-minute post-session buffer — changes carry machine-readable reason codes; impossible items return **per-equipment `earliest_possible` diagnostics** (`available_only_after`, `available_after_deadline` + `deadline_would_need at_least "12:15"`, `no_permission` blockers), never a bare failure.
3. **Apply** → the tool calls `ctx.elicit()` and **refuses to mutate** until a human confirms in the client UI. Decline / cancel / unsupported client → `not_confirmed`, zero side effects, plan stays `proposed`.
4. **Idempotency everywhere**: `plan_id` = `(outage_id, based_on_version)`, monotonic `schedule_version`, stale proposals rejected (`plan_stale`), re-apply → `already_applied`.

## Quick start

```bash
pip install -r requirements.txt        # mcp==1.30.0, uvicorn[standard], pydantic>=2.5
python -m mcp_server                   # → http://127.0.0.1:8765/mcp
```

Optional flags: `python -m mcp_server --host 127.0.0.1 --port 8765 --db server.db`

### Talk to it with any MCP client

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

headers = {"authorization": "Bearer tok-manager"}   # header-only auth

async def confirm_outage(message, schema):          # MUST be async
    # message lists what will move; schema is {"confirm": bool}
    return ElicitResult(action="accept", content={"confirm": True})

async with streamablehttp_client("http://127.0.0.1:8765/mcp", headers=headers) as (r, w, _):
    async with ClientSession(r, w, elicitation_callback=confirm_outage) as s:
        await s.initialize()
        res = await s.call_tool("schedule_get", {})        # res.structuredContent
```

Clients **without** an elicitation callback are safe by design: apply returns `not_confirmed` and nothing changes.

### Demo tokens (Authorization: Bearer …)

| token | role | can see / do |
|---|---|---|
| `tok-manager` | manager | both confocals; write tools |
| `tok-chen` | researcher | confocal-a + confocal-b |
| `tok-wang` | researcher | confocal-a only |
| `tok-li` | researcher | confocal-b only |

Identity comes **only** from the per-request header — never from tool arguments.

## The eight tools (contracts/)

`contracts/tools.json` holds the machine-readable input/output schemas (generated verbatim from the live tool registry, locked by tests). `contracts/examples/` holds 13 frozen end-to-end fixtures replayed byte-exact in CI:

| tool | writes? | notes |
|---|---|---|
| `schedule_get` | no | full day view, role-masked, narration in `message` |
| `equipment_report_outage` | **yes** | manager-only; duplicates rejected |
| `schedule_propose_replan` | no (creates plan row) | stale-check + idempotent plan_id |
| `schedule_apply_replan` | **yes** | **elicitation-gated**; human confirm required |
| `schedule_audit_get` | no | **who did what, when** — managers see the full trail; researchers see own actions + public events (outages, replans, applies, resets). Token hints show only a truncated non-identifying fragment (`manager…`, `chen…`), never a full secret. |
| `verify_audit_chain` | no | manager-only; recomputes the SHA-256 hash chain over the audit trail and flags any edit, deletion or splice (`broken_at` row). |
| `reset_demo_data` | **yes** | manager-only; restores seed schedule (version 1); clears the audit trail and records the reset itself as the final entry |
| `debug_confirm` | no | echoes elicitation wiring for client bring-up |

## Engine guarantees (§10 rules)

1. Only `movable` bookings affected by the outage are rescheduled.
2. FIFO by deadline; ties by original start.
3. 15-min slot grid; original equipment preferred if still available ≥ required duration.
4. Hard constraints: operating hours, per-user equipment grants, personal calendar (no double-booking), hard deadline, 15-min post-session cleaning buffer.
5. Greedy, determinstic — no randomness, no LLM decisions in the write path.

**Demo day (2026-10-20, Europe/London):** outage on Confocal A 10:00–16:00 ⇒ `B2 → Confocal B 11:15–12:15` (first slot after Li's immovable B3), `B4 → Confocal A 16:00–17:00` (after outage). Failing both (deadline 11:30 scenario) yields per-equipment diagnostics: B could host 11:15–12:15 `available_after_deadline` + `deadline_would_need at_least 12:15`; A shows `no_slot_today` — while B4 still relocates to A 16:00 in the same plan.

## LLM layer (dual-mode, §7 of the plan)

`mcp_server/llm.py` — **no AWS credentials? Everything still works.**

- `SER_LLM_MODE=auto|scripted|bedrock` (default `auto`).
- Bedrock path: single `Converse` call with a system prompt that hard-binds the six prohibitions (never invent facts, never override the engine, never reorder tool args, never claim authority, never unmask other users, never claim to be the system of record — the DB is). Any failure → scripted fallback, so the demo cannot break live.
- Scripted path: deterministic narration built only from returned JSON facts.

## Architecture

```
Browser (web/)                MCP host/agent (Bedrock or any MCP client)      This repo
┌────────────────┐            ┌──────────────────────────┐   Streamable      ┌─────────────────────────┐
│ schedule cards │  ──MCP──▶  │ agent loop, tool calls,  │  ──HTTP+MCP──▶    │ FastMCP server           │
│ elicitation UI │            │ elicitation prompt       │   127.0.0.1:8765  │  engine + SQLite + audit │
└────────────────┘            └──────────────────────────┘                   └─────────────────────────┘
```

## Browser demo (web/)

```bash
python -X utf8 tools/dev_server2.py     # MCP server on http://127.0.0.1:8765/mcp (fresh temp DB each boot)
cd web && python app.py --port 8080     # web shell on http://127.0.0.1:8080
```

Or run the MCP server against a persistent DB file: `python -X utf8 -m mcp_server`.

`web/` is part of this repo (an MCP Streamable-HTTP client UI): FastAPI serves the
static client and same-origin-proxies `/mcp` to the MCP server, streaming `GET /mcp`
SSE chunk-by-chunk so server-initiated `elicitation/create` reaches the browser live.
The apply confirmation card is answered only by a human click — the demo identity is
carried solely in the `Authorization: Bearer <token>` header, never in tool arguments.

## Hardening (OWASP MCP Security Cheat Sheet)

Transport-level header validation runs at **both** layers and rejects
DNS-rebinding browsers / cross-site attackers before any MCP logic executes:

| layer | check | behavior |
|---|---|---|
| web proxy (`web/app.py`) | `Origin` + `Host` allowlist | present-but-unrecognized → JSON-RPC error `-32002`, HTTP 403; absent Origin allowed (native MCP clients send none) |
| MCP server (`mcp_server/server.py`) | pure-ASGI `TransportGuardMiddleware` wrapping the Streamable HTTP app | same policy for anyone bypassing the proxy |

Plus a structured **audit trail** (`audit_log` SQLite table, `schedule_audit_get`
tool, "Audit log" tab in the web UI): every tool call records actor, role, tool,
result, detail and a truncated token hint. Writes are best-effort and can never
break a tool response. Production-grade details: **WAL journal mode** (concurrent
reads never block on the write lock), **cursor pagination** (`before_id` +
`tool_filter` on `schedule_audit_get`, `next_before_id` cursor returned), a
**10k-row rolling retention** enforced after every audit insert, and a **SHA-256
hash chain** over the trail — `verify_audit_chain` (manager-only) recomputes the
chain and flags edits, deletions or splices, and the UI shows a live
"✓ chain N rows" / "⚠ tamper @row" badge. Both the MCP guard middleware and the
web proxy apply a **per-IP token-bucket rate limit** (~4 req/s, burst 16) that
answers floods with HTTP 429 / `-32002` instead of letting them through. The
audit tab carries a **tool filter dropdown** and 10-second auto-refresh; each
worker thread reuses one **thread-local SQLite connection**; deployments on a
different proxy port / HTTPS tunnel can whitelist their browser origin via
`SER_ALLOWED_ORIGINS` (comma-separated exact origins, honoured by both layers).

Tier 3 additions: every audit row also stores a **structured JSON mirror**
(`detail_json`) of the event — `{tool, result, ...structured keys}` such as
`plan_id`, `blocked_count` or `schedule_version` — exposed through
`schedule_audit_get` and rendered as an expandable `json` chip in the audit tab,
so SIEM-style log scrapers get machine-readable fields without parsing prose
(the mirror is best-effort and excluded from the hash chain, so its structure
can evolve without invalidating tamper evidence). A **`GET /metrics`**
observability endpoint exists on both layers (MCP :8765 and the web proxy
:8080, which aggregates both): process uptime, token-bucket state, schedule
version, table row counts and journal mode — JSON, `no-store`, before any MCP
session resources are consumed. The UI ships a **deep link** (`/#audit` /
`/?view=audit`) that opens the audit tab pre-connect, covered by a
**Playwright visual regression suite** (9 browser checks: deep link, chain
badge, json chip expansion, tool filter, timeline).


```bash
python -X utf8 -m pytest tests/ -q      # 56 passed
```

- `test_engine.py` (10): slot search, buffer semantics, permissions, the B4-scoping engine fix, outage-visible-to-search regression.
- `test_engine_edges.py` (6): boundary edges — half-open intervals, zero-duration, zero-buffer adjacency, unknown equipment.
- `test_contract.py` (17): schema equality against `contracts/tools.json` + byte-exact replay of 13 frozen examples under `SER_FROZEN_NOW=2026-10-20T12:00:00+01:00`.
- `test_server.py` (8): **real uvicorn + real MCP client** over Streamable HTTP — token/tool tables, full outage→propose→apply→`already_applied` loop, elicitation declined leaves the plan untouched, `plan_stale` after version bump, reset, and a **crash/restart cycle** that proves outage + pending plan survive a server restart (subprocess, same SQLite file).
- `test_llm.py` (10): mode selection with/without credentials, prohibition wording, graceful Bedrock failure fallback.
- `test_accountability.py` (5): real-client audit-trail checks — researcher public-visibility SQL boundary, concurrent double-apply applies exactly exactly once (TOCTOU), 403 origin/host rejections land in the hash-chained transport ledger, the ledger survives `reset_demo_data`, and a replayed apply leaves an audit row with the chain verifying green.

Windows note: use `python -X utf8` to keep pytest output clean.

## Development docs

- `docs/friction-log.md` — 7 hard-won findings (SSE-only elicitation, async-callback requirement, `Context.request_context.request.headers`, engine visibility fix, `SER_FROZEN_NOW` clock freeze).
- `docs/product-feedback.md` — MCP-ecosystem observations (elicitation gaps, json_response hazard).
- `COLLAB/CONTRACT-FROZEN.md` — the partner contract; `COLLAB/OUTBOX.md` has the client wiring guide.

## Tech choices

| Component | Choice | Why |
|---|---|---|
| MCP SDK | `mcp==1.30.0` (FastMCP) | official, 2025-11-25 spec, elicitation support |
| Transport | Streamable HTTP (SSE responses) | required for server→client elicitation |
| DB | SQLite (`server.db`) | transactional versioning + audit log, zero ops |
| Agent model | Amazon Bedrock (Claude) | AWS Builder challenge; scripted fallback keeps demo offline-safe |
| Narration | Bedrock Converse / scripted | dual-mode §7 |

## License

MIT — see LICENSE. Synthetic demo data; not production-hardened.
