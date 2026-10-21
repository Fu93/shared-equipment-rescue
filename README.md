# Shared Equipment Rescue / 共享儀器搶救

<div align="center">

**🌐 [English](#shared-equipment-rescue) · [繁體中文](#共享儀器搶救)**

</div>

> Both versions are kept in this file so nothing goes stale in two places:
> the English section is the reference, the Chinese section is a faithful
> translation of the same content (same commands, same numbers, same images).

---

# Shared Equipment Rescue

**A facility manager's AI copilot for shared-instrument outage recovery — a self-hosted MCP 2025-11-25 server that detects every booking an outage breaks, proposes a rule-checked replan, and never writes a single change without explicit human confirmation (MCP elicitation, human-in-the-loop).**

Amazon "Build, Ship, Shape" hackathon entry — **Alexa+ primary track** + **AWS Builder challenge** (Amazon Nova Lite via the Bedrock Converse API). A board refresh uses the scripted sentence. On the simulated page, a bounded tool loop can propose MCP calls. The engine decides every move, and the Confirm click stays human.

The page served from `web/` is a **simulated Alexa+ experience**: a browser MCP client, not a physical Alexa device.

## Try it live

Hosted demo: **<https://shared-equipment-rescue.onrender.com>**. Nothing to install.

1. **Voice:** in desktop Chrome or Edge, press **Mic**, allow the microphone, and say *"Alexa, Confocal A is down until 4pm, please sort out the bookings"*. No microphone? Open <https://shared-equipment-rescue.onrender.com/?utterance=Alexa%2C%20Confocal%20A%20is%20down%20until%204pm%2C%20please%20sort%20out%20the%20bookings>, which sends the same line through the page's simulation hook.
2. The page reports the outage (`v2`) and proposes plan P1. Press **Apply P1**: the Confirm card is a real MCP elicitation. Press **Confirm** and the board becomes `v3`.
3. **Reset demo data** puts the board back to `v1`.

Notes: every visitor shares one demo state, so press **Reset demo data** if someone else has already applied the plan. Bedrock is off on the hosted demo; the chat is labelled `Fallback: pattern parser (Bedrock off)`. Speech recognition is the browser's own Web Speech API: the page calls no cloud speech service itself (Chrome may process the audio on Google's servers). All bookings, people, and instruments are synthetic, and the demo tokens are fake.

## Testing instructions for judges

Clean-clone setup, then the MCP server (spec 2025-11-25, Streamable HTTP) and the web client. Open <http://127.0.0.1:8080>. That page is the simulated Alexa+ experience. It sends `initialize`, `tools/list`, and `tools/call` over Streamable HTTP. It is not connected to the Alexa+ developer console.

### Clean clone

```bash
git clone https://github.com/Fu93/shared-equipment-rescue.git
cd shared-equipment-rescue
python3 -m venv .venv
source .venv/bin/activate
# Windows Command Prompt, instead of the python3 and source lines above:
# python -m venv .venv
# .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

On Windows Command Prompt, use `python -m venv .venv` and `.venv\Scripts\activate` instead of the `python3` and `source .venv/bin/activate` lines. Each later terminal needs that same activate step before the server commands.

`requirements.txt` is the runtime install, including `boto3`. `requirements-dev.txt` adds `pytest`, `pytest-asyncio`, `jsonschema`, and `playwright`. The demo tokens are fake.

On Windows, start Python with `python -X utf8` so pytest output stays UTF-8. That flag is optional on Linux and macOS.

### Start the MCP server and the web client

Use two terminals, from the repository root, with the virtualenv active. Do not run `python -m mcp_server` in a third terminal at the same time: both servers bind port 8765.

```bash
python tools/dev_server2.py
```

That process is the MCP server: spec 2025-11-25, Streamable HTTP, at `http://127.0.0.1:8765/mcp`, with a fresh temporary database on each boot. `python -m mcp_server` is the same server pointed at a persistent `server.db`.

```bash
cd web && python app.py --port 8080
```

Open <http://127.0.0.1:8080>. The right-hand MCP protocol console should show a connection and protocol `2025-11-25`. The default identity is Facility Manager (`tok-manager`).

### Golden path

1. **Report an outage.** In the chat box send `Confocal A is down until 4pm`, or press the button **Report outage (Confocal A 10:00–16:00)**. The version badge becomes `v2`, an outage banner appears, and bookings B2 and B4 are marked `blocked`. The page then proposes a replan on its own.
2. **Review the proposed replan.** The notebook lists two moves: Chen to Confocal B 11:15–12:15, and Wang to Confocal A 16:00–17:00, each with a machine-readable reason. The board shows pending plan P1.
3. **Cancel, then Confirm.** Press **Apply P1**. The confirmation card is a real MCP `elicitation/create`. Only a click answers it. Press **Cancel**. The badge stays `v2` and no booking moves. Press **Apply P1** again, then **Confirm**. The badge becomes `v3` and the moves are on the board.
4. **Researcher view.** Under **Acting as**, choose Wang (`tok-wang`). Wang's own 16:00 slot stays visible. Other bookings on Confocal B show `Occupied`.
5. **Audit log.** Open **Audit log**. The chain badge should show an intact chain. Under `tok-wang` the trail is the researcher view (that user's actions plus public events). Switch back to `tok-manager` to see every row.

### Run the tests

```bash
python -m pytest tests/ -q
```

Measured on Linux after `pip install -r requirements-dev.txt`. On CPython 3.11.17, 3.12.8, and 3.13.5, with the Playwright browser installed (`python -m playwright install chromium`): **129 passed**, 1 skipped. Without that browser: **121 passed**, 9 skipped. The commit before the hosted-demo change, on CPython 3.11.17, 3.12.3, and 3.13.16, was **111 passed** with the browser and **103 passed**, 9 skipped, without it. Without a browser the skips are `test_video_walk.py`, `test_screenshots_current.py`, the browser tests in `test_voice_hook.py`, and `test_bedrock_converse_live` (`AWS_BEARER_TOKEN_BEDROCK` was unset). With the browser, only `test_bedrock_converse_live` skipped. The rate-limit commit before this stub and queue fix, on the same runs, was **108 passed** with the browser and **102 passed**, 7 skipped, without it. The verification commit before that rate-limit fix, on the same runs, was **99 passed** with the browser and **96 passed**, 4 skipped, without it. The tool-loop commit before those fixes, on the same runs, was **90 passed** with the browser and **87 passed**, 4 skipped, without it. The narration-only commit before this tool loop, on the same Linux 3.11 and 3.13 runs, was **73 passed** with the browser and **71 passed**, 3 skipped, without it. The commit before those Bedrock tests was **70 passed** with the browser and **68 passed**, 2 skipped, without it.

### What is real, and what is simulated

**Real in this repository:** the MCP server (`mcp==1.30.0`, spec 2025-11-25, Streamable HTTP); this web page as an MCP client, including server-initiated elicitation; the deterministic replan engine; SQLite, monotonic `schedule_version`, idempotent `plan_id`, and the hash-chained audit log. The demo tokens (`tok-manager`, `tok-chen`, `tok-wang`, `tok-li`) are intentional fakes.

**Simulated:** the web UI is a simulated Alexa+ experience, labelled Alexa+ (simulated) — MCP client. The bookings, people, and two confocal microscopes are synthetic data. The seeded day is `SER_DEMO_DATE`, or today in `SER_DEMO_TZ` (default Europe/London). The published scenario in the tests is 2026-10-20. With Bedrock off, the chat matches a few fixed phrases and labels that path Fallback: pattern parser (Bedrock off). With Bedrock on, the same chat can propose tool calls, bounded at 4 steps. A board refresh does not call Bedrock. Bedrock rephrases the `schedule_get` overview only when the request sends `x-ser-narrate`. The model does not decide bookings. The Confirm card stays a click.

## What it does

When a confocal microscope (or any shared instrument) goes down mid-day, a manager normally rebooks six papers by hand. This server does the whole recovery loop over MCP:

1. **Report** the outage → engine instantly marks affected bookings `blocked`, bumps `schedule_version`, writes an audit log row.
2. **Propose** a replan → greedy scheduler searches 15-minute increments, FIFO by deadline, enforcing operating hours, per-user equipment permissions, personal calendars, hard deadlines, and a 15-minute post-session buffer — changes carry machine-readable reason codes; impossible items return **per-equipment `earliest_possible` diagnostics** (`available_only_after`, `available_after_deadline` + `deadline_would_need at_least "12:15"`, `no_permission` blockers), never a bare failure.
3. **Apply** → the tool calls `ctx.elicit()` and **refuses to mutate** until a human confirms in the client UI. Decline / cancel / unsupported client → `not_confirmed`, zero side effects, plan stays `proposed`.
4. **Idempotency everywhere**: `plan_id` = `(outage_id, based_on_version)`, monotonic `schedule_version`, stale proposals rejected (`plan_stale`), re-apply → `already_applied`.

## The demo, frame by frame

The six frames below are the actual demo (regenerated from this build by
`tools/shoot_screenshots.py`; `tests/test_screenshots_current.py` fails if
they ever drift from what the code renders).

**1 — the board, straight after `initialize`** — six bookings across two
confocals, and the right-hand panel showing the real MCP traffic
(`tools/call` → `ok`, protocol `2025-11-25`, identity taken from the header):

![initial board](docs/screenshots/_shot_1_initial.png)

**2 — one tool call, the outage is recorded** — the version badge jumps to
`v2`, the outage banner appears and B2/B4 are marked `blocked`:

![outage recorded](docs/screenshots/_shot_2_outage.png)

**3 — the proposal** — Chen moves to Confocal B 11:15–12:15, Wang to
Confocal A 16:00–17:00, each with a machine-readable reason
(`switched equipment (CONFOCAL A → CONFOCAL B)`, `still meets deadline`):

![proposal](docs/screenshots/_shot_3_proposed.png)

**4 — the human-in-the-loop gate** — the server sends a real MCP
`elicitation/create`; the confirmation card is answered by a click and
nothing else. No spinner on top of the decision:

![confirm card](docs/screenshots/_shot_4_elicit.png)

**5 — applied, `v3`** — the audit row records who confirmed and when
(London time):

![applied](docs/screenshots/_shot_5_applied.png)

**6 — the same board as a researcher** — Wang sees his own new 16:00 slot
while everyone else's booking is masked as `Occupied`:

![researcher view](docs/screenshots/_shot_6_wang_after.png)

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

`contracts/tools.json` holds the machine-readable input/output schemas (generated verbatim from the live tool registry, locked by tests). `contracts/examples/` holds 13 frozen end-to-end fixtures replayed byte-exact by the test-suite deep-equality lock — any drift in a fixture or a schema breaks the build:

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

`mcp_server/llm.py` can phrase the `schedule_get` sentence, and `agent_converse` proposes tool calls for the chat loop. Neither path chooses slots or moves bookings. `schedule_apply_replan` still waits for the human Confirm card. **No AWS credentials? The demo still runs on the scripted sentence and the pattern parser.**

A board refresh calls `schedule_get` and returns the scripted sentence. That refresh does not call Bedrock. Bedrock rephrases the sentence only when the MCP request includes the header `x-ser-narrate` set to 1, and only after the engine has already built the bookings, the outage, and any pending plan. The tool loop is a separate call, once per user turn.

When narration is requested:

- `SER_LLM_MODE=scripted` never calls Bedrock, even if a token is set. The test suite sets this.
- `SER_LLM_MODE=auto` (the default) and `SER_LLM_MODE=bedrock` call Bedrock only when credentials exist: a non-empty `AWS_BEARER_TOKEN_BEDROCK`, or `AWS_ACCESS_KEY_ID` together with `AWS_SECRET_ACCESS_KEY`, or `AWS_PROFILE` with an existing shared credentials or config file, or `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`. With none of those, the mode stays scripted and no client is built.
- The client is one cached `boto3` `bedrock-runtime` client, built at startup. `BEDROCK_MODEL_ID` defaults to amazon.nova-lite-v1:0. `AWS_REGION` defaults to `us-east-1`. boto3 reads `AWS_BEARER_TOKEN_BEDROCK` from the environment. The token is not a client argument. When that bearer token is set, the process sets `AWS_EC2_METADATA_DISABLED`. Converse runs on a worker thread with a timeout. The audited latency is the Converse call itself. The client allows 2 attempts in total via `total_max_attempts`. botocore's `max_attempts` counts only retries after the first call, so a value of 2 there would be 3 attempts.
- If narration fails or returns no text, `schedule_get` returns the scripted sentence. A failed user turn shows a short error and falls back to the pattern parser for that turn. The visible label is Fallback: pattern parser (Bedrock error: <code>). The audit row stores the code and the request id, not the raw exception. When Bedrock is not attempted, the label is `Bedrock: off`.
- Each attempt appends one `bedrock_converse` audit row with the timestamp, model, region, request id, and latency. The token is not in that row. The system prompt forbids inventing facts, overriding the engine, reordering tool arguments, claiming authority, revealing masked data, and posing as the system of record.
- `SER_BEDROCK_STUB` set to voice is test-only and never calls AWS. The badge reads Bedrock: STUB (test). The audit row records provider stub and model stub. The outage window uses `SER_DEMO_DATE` and `SER_DEMO_TZ`. `SER_BEDROCK_STUB_DELAY` is an optional test-only pause in seconds.

When the dev panel says Bedrock is on, a typed line, or a final spoken line that starts with the wake word Alexa, goes into a tool loop capped at 4 converse rounds and 4 tool executions. The cap is enforced on the server for that `conversation_id`. The page stops at 4 as well. Converse receives a `toolConfig` of the read and propose tools, plus `schedule_apply_replan`. `reset_demo_data`, `debug_confirm`, and `verify_audit_chain` are not in that list, and the server refuses them if the model asks. The browser runs each accepted call on its existing MCP session, so the Confirm card still appears for `schedule_apply_replan`. The board refreshes once before that Confirm card, and once when the turn ends. A malformed call, an unknown tool, or arguments that do not match the schema stops the loop, and that call is not executed. The model does not choose slots, move bookings, invent facts, or confirm an apply. Each proposal is an `agent_tool_call` audit row. A result the browser reports is stored as `client-reported`. After a confirmed apply the page reports `completed` and cites `schedule_apply_replan` with the plan id. A client status of `applied`, including a lookalike, is refused and writes no audit row. An apply is recorded only by the server's own apply path. The token is not in that row. New `conversation_id` values for one token are capped, and idle counters expire. `GET /metrics` and the agent posts use a separate budget keyed by client IP address, the same address as the MCP flood limit. It is not a browser session. A non-JSON or HTTP 429 reply shows a short message, retries, then uses the pattern parser labelled Fallback: pattern parser (rate limit). While Bedrock is off, the chat uses the pattern parser and the page labels it Fallback: pattern parser (Bedrock off). A failed Bedrock call uses the same parser for that turn and labels it Fallback: pattern parser (Bedrock error: <code>). If that failure happens after this turn already recorded an outage, the parser calls `schedule_propose_replan` for that outage and continues from the current state.

The Mic button is push-to-talk. It uses `SpeechRecognition` or `webkitSpeechRecognition` in the browser, language en-US, and shows the live transcript. A final utterance that starts with Alexa is sent with no Enter key. The reply is shown in the bubble and spoken with `speechSynthesis`. If the browser has no speech API, or the microphone is denied, a notice stays visible and typing still works. This page does not call a cloud speech service.

`serSimulateUtterance` and the `?utterance=` query are a simulation hook. They wait until the MCP session exists, the schedule has loaded, the Bedrock status has resolved, and any in-flight call has finished, including a pending `/agent/step`. Calls on one page run one after another, and the queue waits until that turn's tool loop finishes. Then they inject a transcript through the same function as a recognised utterance, so a test or a screen recording with no microphone can drive the turn. The wake word still applies.

The seeded day is `SER_DEMO_DATE` (an ISO date). When that variable is unset, the day is today's date in `SER_DEMO_TZ`, which defaults to Europe/London. Audit timestamps stay on the real UTC clock and are not rewritten to the demo day. Start the MCP server and the web shell with the same values. The protocol console says MCP spec 2025-11-25.

## Amazon Bedrock

```bash
export AWS_BEARER_TOKEN_BEDROCK=your-bedrock-api-key
export AWS_REGION=us-east-1
export BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
```

```bash
export SER_DEMO_DATE=2026-10-20
export SER_DEMO_TZ=Europe/London
```

`boto3` (>=1.39, listed in `requirements.txt`) builds one cached client at startup. Standard AWS credentials can stand in for the bearer token. Start the MCP server from that environment. The dev panel shows `Bedrock: on (amazon.nova-lite-v1:0, us-east-1)` from `/metrics`, without a Converse call on each board refresh. A user turn is what calls Converse. `test_bedrock_converse_live` makes that one call and skips when `AWS_BEARER_TOKEN_BEDROCK` is unset. This repository does not use any other AWS service.

## Architecture

```
Simulated Alexa+ (web/, an MCP client)                         This repo
┌────────────────┐              Streamable HTTP           ┌─────────────────────────┐
│ schedule cards │  ──────── tools/call + Confirm ─────▶  │ FastMCP server           │
│ elicitation UI │              127.0.0.1:8765            │  engine + SQLite + audit │
└────────────────┘                                        └─────────────────────────┘
```

## Browser demo (web/) — simulated Alexa+ experience

```bash
python -X utf8 tools/dev_server2.py     # MCP server on http://127.0.0.1:8765/mcp (fresh temp DB each boot)
cd web && python app.py --port 8080     # web shell on http://127.0.0.1:8080 (any --port works)
```

Or run the MCP server against a persistent DB file: `python -X utf8 -m mcp_server`.

This UI is the simulated Alexa+ experience. `web/` is part of this repo (an MCP Streamable-HTTP client UI): FastAPI serves the
static client and same-origin-proxies `/mcp` to the MCP server, streaming `GET /mcp`
SSE chunk-by-chunk so server-initiated `elicitation/create` reaches the browser live.
The apply confirmation card is answered only by a human click — the demo identity is
carried solely in the `Authorization: Bearer <token>` header, never in tool arguments.

## Hardening (OWASP MCP Security Cheat Sheet)

Transport-level header validation runs at **both** layers and rejects
DNS-rebinding browsers / cross-site attackers before any MCP logic executes:

| layer | check | behavior |
|---|---|---|
| web proxy (`web/app.py`) | `Origin` + `Host` allowlist | present-but-unrecognized → JSON-RPC error `-32002`, HTTP 403; absent Origin allowed (native MCP clients send none). Any **loopback** origin/host is accepted on any port, so `--port` other than 8080 works; foreign hosts/origins stay blocked (DNS-rebinding defence) |
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
**Playwright suite** (28 browser checks covering the full outage→propose→confirm→apply loop: identity select, panels, equipment report, dev console, confirm card, decline path, applied v3, responsive layout - mutation-verified: each check was shown to fail when its defect is injected).


```bash
python -X utf8 -m pytest tests/ -q
```

Measured on Linux. CPython 3.11.17, 3.12.8, and 3.13.5 with the Playwright browser installed: **129 passed**, 1 skipped. Without that browser: **121 passed**, 9 skipped. Before the hosted-demo change the stub and queue fix, on CPython 3.11.17, 3.12.3, and 3.13.16, was **111 passed** with the browser and **103 passed**, 9 skipped, without it. Before this stub and queue fix the rate-limit commit was **108 passed** with the browser and **102 passed**, 7 skipped, without it. Before that rate-limit fix the verification commit was **99 passed** with the browser and **96 passed**, 4 skipped, without it. Before those fixes the tool-loop commit was **90 passed** with the browser and **87 passed**, 4 skipped, without it. Before that tool loop the same 3.11 and 3.13 runs were **73 passed** with the browser and **71 passed**, 3 skipped, without it, and before those Bedrock tests **70 passed** with the browser and **68 passed**, 2 skipped, without it.

- `test_engine.py` (12): slot search, buffer semantics, permissions, the B4-scoping engine fix, outage-visible-to-search regression, and the choice-key tie-break (earliest start wins; the original equipment wins an exact tie).
- `test_engine_edges.py` (6): boundary edges — half-open intervals, zero-duration, zero-buffer adjacency, unknown equipment.
- `test_contract.py` (17): schema equality against `contracts/tools.json` + byte-exact replay of 13 frozen examples under `SER_FROZEN_NOW=2026-10-20T12:00:00+01:00`.
- `test_server.py` (8): **real uvicorn + real MCP client** over Streamable HTTP — token/tool tables, full outage→propose→apply→`already_applied` loop, elicitation declined leaves the plan untouched, `plan_stale` after version bump, reset, and a **crash/restart cycle** that proves outage + pending plan survive a server restart (subprocess, same SQLite file).
- `test_llm.py` (14): mode selection with and without credentials, prohibition wording, a stubbed Converse success and a stubbed failure (audit row, token not logged), and `test_bedrock_converse_live`, which skips unless `AWS_BEARER_TOKEN_BEDROCK` is set.
- `test_accountability.py` (7): real-client audit-trail checks — researcher public-visibility SQL boundary, concurrent double-apply applies exactly once (TOCTOU), 403 origin/host rejections land in the hash-chained transport ledger, the ledger survives `reset_demo_data`, a replayed apply leaves an audit row with the chain verifying green, audit pagination drops no row at any page boundary (limit 1/2/3 walks over 5 seeded rows), and `debug_confirm` elicitation outcomes are audited.
- `test_web_proxy.py` (6): the `web/` layer — loopback `Origin`/`Host` accepted on any port, foreign hosts/origins still 403, a real MCP client relayed through the proxy sees all 8 tools and a working `schedule_get`, `/metrics` aggregates both layers, and a dead upstream returns 502 with a restart hint.
- `test_video_walk.py` (1, 29 scene checks): drives the real UI through **the demo video script beat by beat** — the six bookings and two confocals, the version bump to v2 with the outage banner, both proposed moves with machine-readable reasons, the confirm card naming the human-in-the-loop rule, Cancel leaving the version untouched, Confirm reaching v3, the identity switch masking other people's slots as "Occupied", and the audit tab with zone-labelled timestamps — so the recording cannot show something the narration does not claim. Needs Playwright; skips cleanly where no browser can launch.
- `test_screenshots_current.py` (1): the committed screenshots in `docs/screenshots/` must still show what the build renders today — it re-renders the same scenes and compares the recorded text, so the images in the README cannot silently go stale. Needs Playwright; skips cleanly where no browser can launch.
- `test_hosted_deploy.py` (18): the opt-in hosted-demo settings — public Host allowlist with numeric-port check, edge client-IP header (never X-Forwarded-For), proxy overwrites `x-ser-client-ip`, the loopback-only server key, the platform `HEAD /` probe ledgered as `host_probe` while real foreign hosts stay `host`, `deploy/render_start.sh` startup timeout and exit reporting, and the light-only page.
- `test_readme_i18n.py` (2): the English and Chinese sections of this file must agree — same commands, same images, same identifiers, same numbers. A bilingual README that drifts is worse than none, because a reader cannot tell. The second test checks the live rendered page, so the language switch is proven to jump.

Windows note: use `python -X utf8` to keep pytest output clean.

## Demo screenshots

```bash
python -X utf8 tools/shoot_screenshots.py
```

Regenerates the six demo screenshots from the current build, one per beat of
the video script (initial board, outage, proposal, confirm card, applied, and
the identity switch). It boots its own servers on ephemeral ports, so it never
disturbs a running demo.

It writes two copies: `docs/screenshots/` (version-controlled — what the README
shows and what a judge sees) and `web/` (the live capture, gitignored — your
recording scratch). Alongside the images it writes `docs/screenshots/manifest.json`,
the text each frame displayed; `tests/test_screenshots_current.py` re-renders
the same scenes and compares the text, so a committed screenshot can never
silently go stale.

## Development docs

- `docs/friction-log.md` — 7 hard-won findings (SSE-only elicitation, async-callback requirement, `Context.request_context.request.headers`, engine visibility fix, `SER_FROZEN_NOW` clock freeze).
- `docs/product-feedback.md` — MCP-ecosystem observations (elicitation gaps, json_response hazard).
- `docs/dev-notes/COLLAB/CONTRACT-FROZEN.md` — the partner contract; `docs/dev-notes/COLLAB/OUTBOX.md` has the client wiring guide. Internal notes live in `docs/dev-notes/`. The ad-hoc probes that used to be `tools/_deep4.py` through `tools/_deep8.py` live in `archive/`.
- `tools/check_readme_i18n.py` — keeps this file's two language sections in sync (code blocks, images, identifiers, numbers). Run it after editing either side; `tests/test_readme_i18n.py` runs it as part of the suite.

## Tech choices

| Component | Choice | Why |
|---|---|---|
| MCP SDK | `mcp==1.30.0` (FastMCP) | official, 2025-11-25 spec, elicitation support |
| Transport | Streamable HTTP (SSE responses) | required for server→client elicitation |
| DB | SQLite (`server.db`) | transactional versioning + audit log, zero ops |
| Narration | Amazon Nova Lite via Bedrock Converse | Advisory wording of the `schedule_get` sentence when the request sends `x-ser-narrate`, plus a 4-step tool loop on the simulated page when Bedrock is on. A board refresh stays on the scripted sentence. Scripted sentence and the pattern parser when the call is not made or it fails. |

## License

MIT — see LICENSE. Synthetic demo data; not production-hardened.

---

# 共享儀器搶救

**共用儀器故障復原的 AI 助手 —— 一個自架的 MCP 2025-11-25 伺服器：偵測故障會影響哪些預約、提出通過規則檢查的重排方案，而且在人類明確確認之前，絕不寫入任何變更（MCP elicitation，人類在環）。**

Amazon「Build, Ship, Shape」黑客松參賽作品 —— **Alexa+ 主賽道** ＋ **AWS Builder 挑戰**（Amazon Nova Lite，經 Bedrock Converse API）。看板重新整理用的是 scripted 句子。在模擬頁面上，有上限的工具迴圈可以提出 MCP 呼叫。每一次搬移都由引擎決定，Confirm 點擊仍是人類的。

`web/` 提供的頁面是 **simulated Alexa+ experience**（模擬的 Alexa+ 體驗）：瀏覽器裡的 MCP 客戶端，不是實體 Alexa 裝置。

## 線上試用

託管的 demo：**<https://shared-equipment-rescue.onrender.com>**。不需要安裝任何東西。

1. **語音：**在桌機版 Chrome 或 Edge 按 **Mic**，允許使用麥克風，然後說 *"Alexa, Confocal A is down until 4pm, please sort out the bookings"*。沒有麥克風？開啟 <https://shared-equipment-rescue.onrender.com/?utterance=Alexa%2C%20Confocal%20A%20is%20down%20until%204pm%2C%20please%20sort%20out%20the%20bookings>，它會經由頁面的模擬 hook 送出同一句話。
2. 頁面會記錄故障（`v2`）並提出方案 P1。按 **Apply P1**：Confirm 卡片是真正的 MCP elicitation。按 **Confirm**，看板會變成 `v3`。
3. **Reset demo data** 會把看板恢復成 `v1`。

注意：所有訪客共用同一份 demo 狀態，如果別人已經套用了方案，請按 **Reset demo data**。託管的 demo 關閉了 Bedrock；聊天區標示為 `Fallback: pattern parser (Bedrock off)`。語音辨識用的是瀏覽器自己的 Web Speech API：頁面本身不呼叫任何雲端語音服務（Chrome 可能會在 Google 的伺服器上處理音訊）。所有預約、人員與儀器都是合成資料，demo token 也是假的。

## 評審測試說明

以下是乾淨 clone 的步驟，然後啟動 MCP 伺服器（spec 2025-11-25，Streamable HTTP）與 web client。開啟 <http://127.0.0.1:8080>。那個頁面就是 simulated Alexa+ experience。它透過 Streamable HTTP 送出 `initialize`、`tools/list`、`tools/call`。它沒有連到 Alexa+ developer console。

### 乾淨 clone

```bash
git clone https://github.com/Fu93/shared-equipment-rescue.git
cd shared-equipment-rescue
python3 -m venv .venv
source .venv/bin/activate
# Windows 命令提示字元，用來取代上面的 python3 與 source 兩行：
# python -m venv .venv
# .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

在 Windows 命令提示字元，請改用 `python -m venv .venv` 與 `.venv\Scripts\activate`，不要用上面的 `python3` 與 `source .venv/bin/activate`。之後每個新終端機在跑伺服器指令前，都要再做一次同樣的啟動。

`requirements.txt` 是執行期安裝，含 `boto3`。`requirements-dev.txt` 另外安裝 `pytest`、`pytest-asyncio`、`jsonschema`、`playwright`。示範 token 是假的。

Windows 請用 `python -X utf8` 啟動，pytest 輸出才會維持 UTF-8。這個旗標在 Linux 與 macOS 可選。

### 啟動 MCP 伺服器與 web client

從儲存庫根目錄開兩個終端機，virtualenv 要在作用中。不要同時再開第三個終端機跑 `python -m mcp_server`：兩個伺服器都會綁 port 8765。

```bash
python tools/dev_server2.py
```

這個行程就是 MCP 伺服器：spec 2025-11-25、Streamable HTTP、位址 `http://127.0.0.1:8765/mcp`，每次啟動都用一份新的暫存資料庫。`python -m mcp_server` 是同一個伺服器，資料庫改為持久的 `server.db`。

```bash
cd web && python app.py --port 8080
```

開啟 <http://127.0.0.1:8080>。右側 MCP protocol console 應顯示已連線，協定為 `2025-11-25`。預設身分是 Facility Manager（`tok-manager`）。

### 主要示範路徑

1. **回報故障。** 在對話框送出 `Confocal A is down until 4pm`，或按 **Report outage (Confocal A 10:00–16:00)**。版本徽章變成 `v2`，出現故障橫幅，預約 B2 與 B4 標成 `blocked`。頁面接著會自己提出重排。
2. **看提出的重排。** 筆記本列出兩筆移動：Chen 到 Confocal B 11:15–12:15，Wang 到 Confocal A 16:00–17:00，每筆都有機器可讀的原因。看板顯示待處理方案 P1。
3. **先 Cancel，再 Confirm。** 按 **Apply P1**。確認卡是真正的 MCP `elicitation/create`。只有點擊能回答。按 **Cancel**。徽章維持 `v2`，沒有預約被搬走。再按一次 **Apply P1**，然後 **Confirm**。徽章變成 `v3`，移動出現在看板上。
4. **研究員視角。** 在 **Acting as** 選擇 Wang（`tok-wang`）。Wang 自己的 16:00 時段仍看得到。Confocal B 上其他人的預約顯示 `Occupied`。
5. **審計紀錄。** 打開 **Audit log**。鏈徽章應顯示鏈是完整的。在 `tok-wang` 之下，軌跡是研究員視角（該使用者自己的操作加上公開事件）。切回 `tok-manager` 可看到每一列。

### 執行測試

```bash
python -m pytest tests/ -q
```

在 Linux 上，於 `pip install -r requirements-dev.txt` 之後量測。CPython 3.11.17、3.12.8 與 3.13.5，已安裝 Playwright 瀏覽器（`python -m playwright install chromium`）：**129 passed**、1 skipped。沒有那個瀏覽器：**121 passed**、9 skipped。託管 demo 變更之前的 commit，在 CPython 3.11.17、3.12.3 與 3.13.16 上是有瀏覽器 **111 passed**、沒有瀏覽器 **103 passed**、9 skipped。沒有瀏覽器時跳過的是 `test_video_walk.py`、`test_screenshots_current.py`、`test_voice_hook.py` 裡的瀏覽器測試，以及 `test_bedrock_converse_live`（當時 `AWS_BEARER_TOKEN_BEDROCK` 沒有設定）。有瀏覽器時只跳過 `test_bedrock_converse_live`。這次 stub 與佇列修正之前的速率限制 commit，在同樣的測試上是有瀏覽器 **108 passed**、沒有瀏覽器 **102 passed**、7 skipped。那次速率限制修正之前的驗證 commit，在同樣的測試上是有瀏覽器 **99 passed**、沒有瀏覽器 **96 passed**、4 skipped。那些修正之前的工具迴圈 commit，在同樣的測試上是有瀏覽器 **90 passed**、沒有瀏覽器 **87 passed**、4 skipped。這個工具迴圈之前、只有敘事的那個 commit，在同樣的 Linux 3.11 與 3.13 上是有瀏覽器 **73 passed**、沒有瀏覽器 **71 passed**、3 skipped。那些 Bedrock 測試加入之前的 commit 是有瀏覽器 **70 passed**、沒有瀏覽器 **68 passed**、2 skipped。

### 什麼是真的，什麼是模擬的

**這個儲存庫裡真的有：** MCP 伺服器（`mcp==1.30.0`、spec 2025-11-25、Streamable HTTP）；這個網頁作為 MCP 客戶端，含伺服器發起的 elicitation；確定性的重排引擎；SQLite、單調的 `schedule_version`、冪等的 `plan_id`，以及雜湊鏈審計紀錄。示範 token（`tok-manager`、`tok-chen`、`tok-wang`、`tok-li`）是故意的假 token。

**模擬的：** web UI 是 simulated Alexa+ experience，標題是 Alexa+ (simulated) — MCP client。預約、人物，以及兩台共軛焦顯微鏡都是合成資料。種子日是 `SER_DEMO_DATE`，沒設定時就是 `SER_DEMO_TZ` 的今天（預設 Europe/London）。測試裡發表的情境是 2026-10-20。Bedrock 關閉時，對話框比對幾句固定說法，並把那條路徑標成 Fallback: pattern parser (Bedrock off)。Bedrock 開啟時，同一個對話框可以提出工具呼叫，上限 4 步。看板重新整理不會呼叫 Bedrock。只有請求帶了 `x-ser-narrate` 時，Bedrock 才會改寫 `schedule_get` 的總覽句。模型不決定預約。Confirm 卡仍是一次點擊。

## 它在做什麼

當共軛焦顯微鏡（或任何共用儀器）白天中途故障，管理員通常得手工改期六篇論文。這個伺服器用 MCP 跑完整條復原迴路：

1. **回報**故障 → 引擎立刻把受影響的預約標成 `blocked`、`schedule_version` 遞增、寫入一筆審計紀錄。
2. **提出**重排方案 → 貪婪排程器以 15 分鐘為網格搜尋、依截止時間 FIFO，遵守營業時間、每人的設備權限、個人行事曆、硬性截止，以及場次後 15 分鐘緩衝 —— 每次異動都帶機器可讀的原因碼；排不進去的項目會回傳 **per-equipment `earliest_possible` 診斷**（`available_only_after`、`available_after_deadline` ＋ `deadline_would_need at_least "12:15"`、`no_permission` 阻擋原因），絕不是一句「做不到」。
3. **套用** → 工具呼叫 `ctx.elicit()`，在客戶端 UI 有人工確認之前**拒絕任何寫入**。拒絕／取消／不支援 elicitation 的客戶端 → `not_confirmed`，零副作用，方案維持 `proposed`。
4. **處處冪等**：`plan_id` = `(outage_id, based_on_version)`、`schedule_version` 單調遞增、過期方案被拒（`plan_stale`）、重複套用 → `already_applied`。

## 示範畫面，逐格看

下面六張就是實際的 demo（由 `tools/shoot_screenshots.py` 依當前版本重新產生；`tests/test_screenshots_current.py` 會在它們與程式實際渲染的內容不一致時報錯）。

**1 — `initialize` 之後的看板** —— 兩台共軛焦上六個預約，右側面板是真正的 MCP 流量（`tools/call` → `ok`、協定 `2025-11-25`、身分只來自標頭）：

![初始看板](docs/screenshots/_shot_1_initial.png)

**2 — 一次工具呼叫，故障被記錄** —— 版本徽章跳到 `v2`、出現故障橫幅、B2/B4 標成 `blocked`：

![故障已記錄](docs/screenshots/_shot_2_outage.png)

**3 — 重排方案** —— Chen 改到 Confocal B 11:15–12:15、Wang 改到 Confocal A 16:00–17:00，每筆都附機器可讀的原因（`switched equipment (CONFOCAL A → CONFOCAL B)`、`still meets deadline`）：

![重排方案](docs/screenshots/_shot_3_proposed.png)

**4 — 人類在環的閘門** —— 伺服器送出真正的 MCP `elicitation/create`；確認卡只由點擊回答，別無他法。決策之上沒有任何轉圈遮罩：

![確認卡](docs/screenshots/_shot_4_elicit.png)

**5 — 已套用，`v3`** —— 審計列記錄了是誰確認、何時確認（倫敦時間）：

![已套用](docs/screenshots/_shot_5_applied.png)

**6 — 同一張看板，以研究員身分看** —— Wang 看得到自己新的 16:00 時段，其他人的預約則被遮蔽成 `Occupied`：

![研究員視角](docs/screenshots/_shot_6_wang_after.png)

## 快速開始

```bash
pip install -r requirements.txt        # mcp==1.30.0, uvicorn[standard], pydantic>=2.5
python -m mcp_server                   # → http://127.0.0.1:8765/mcp
```

可選參數：`python -m mcp_server --host 127.0.0.1 --port 8765 --db server.db`

### 用任何 MCP 客戶端與它對話

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

headers = {"authorization": "Bearer tok-manager"}   # 只認標頭

async def confirm_outage(message, schema):          # 必須是 async
    # message 會列出哪些預約要動；schema 是 {"confirm": bool}
    return ElicitResult(action="accept", content={"confirm": True})

async with streamablehttp_client("http://127.0.0.1:8765/mcp", headers=headers) as (r, w, _):
    async with ClientSession(r, w, elicitation_callback=confirm_outage) as s:
        await s.initialize()
        res = await s.call_tool("schedule_get", {})        # res.structuredContent
```

**沒有** elicitation callback 的客戶端依設計是安全的：套用會回 `not_confirmed`，什麼都不會變。

### 示範 token（Authorization: Bearer …）

| token | 角色 | 能看／能做 |
|---|---|---|
| `tok-manager` | 管理員 | 兩台共軛焦；可寫入的工具 |
| `tok-chen` | 研究員 | confocal-a ＋ confocal-b |
| `tok-wang` | 研究員 | 只有 confocal-a |
| `tok-li` | 研究員 | 只有 confocal-b |

身分**只**來自每個請求的標頭 —— 絕不從工具參數取得。

## 八個工具（contracts/）

`contracts/tools.json` 放的是機器可讀的輸入／輸出 schema（逐字由線上的工具註冊表產生，並由測試鎖死）。`contracts/examples/` 放的是 13 份凍結的端到端範例，由測試套件的深度相等鎖定逐位元重播 —— 範例或 schema 只要有任何漂移就會讓建置失敗：

| 工具 | 會寫入？ | 說明 |
|---|---|---|
| `schedule_get` | 否 | 整日視圖，依角色遮蔽，敘事放在 `message` |
| `equipment_report_outage` | **是** | 僅限管理員；重複回報會被拒 |
| `schedule_propose_replan` | 否（會建立 plan 列） | 過期檢查 ＋ 冪等的 plan_id |
| `schedule_apply_replan` | **是** | **以 elicitation 為閘門**；必須人工確認 |
| `schedule_audit_get` | 否 | **誰、在什麼時候、做了什麼** —— 管理員看完整軌跡；研究員只看自己的操作 ＋ 公開事件（故障、重排、套用、重置）。token 只顯示截斷且不可識別的片段（`manager…`、`chen…`），絕不顯示完整密鑰。 |
| `verify_audit_chain` | 否 | 僅限管理員；重算審計軌跡上的 SHA-256 雜湊鏈，標出任何竄改、刪除或拼接（`broken_at` 列）。 |
| `reset_demo_data` | **是** | 僅限管理員；還原成種子排程（版本 1）；清空審計軌跡，並把這次重置本身記為最後一筆 |
| `debug_confirm` | 否 | 讓客戶端接線時確認 elicitation 串接是否正確 |

## 引擎保證（§10 條規則）

1. 只有受故障影響**且**可移動（`movable`）的預約會被重排。
2. 依截止時間 FIFO；同截止者依原始開始時間。
3. 15 分鐘時段網格；若原設備仍能提供所需時長，優先留在原設備。
4. 硬性限制：營業時間、每人的設備授權、個人行事曆（不得重複預約）、硬性截止、場次後 15 分鐘清潔緩衝。
5. 貪婪且**確定性** —— 沒有隨機性，寫入路徑上沒有任何 LLM 決策。

**示範日（2026-10-20，Europe/London）：** Confocal A 於 10:00–16:00 故障 ⇒ `B2 → Confocal B 11:15–12:15`（Li 不可移動的 B3 之後第一個空檔）、`B4 → Confocal A 16:00–17:00`（故障結束後）。若兩邊都不行（截止 11:30 的情境）會回傳 per-equipment 診斷：B 可承接 11:15–12:15，標為 `available_after_deadline` ＋ `deadline_would_need at_least 12:15`；A 顯示 `no_slot_today` —— 而同一份方案裡 B4 仍然移到 A 的 16:00。

## LLM 層（雙模式，計畫 §7）

`mcp_server/llm.py` 可以改寫 `schedule_get` 那句話，`agent_converse` 則為對話迴圈提出工具呼叫。兩條路徑都不選時段、也不搬預約。`schedule_apply_replan` 仍然要等人類的 Confirm 卡。**沒有 AWS 憑證？demo 仍用 scripted 那句話和 pattern parser 跑完。**

看板重新整理會呼叫 `schedule_get` 並回傳 scripted 句子。那次重新整理不會呼叫 Bedrock。只有 MCP 請求帶了標頭 `x-ser-narrate` 且值為 1 時，Bedrock 才改寫那句話，而且是在引擎已經組好預約、故障與待處理方案之後。工具迴圈是另外一通呼叫，每一輪使用者的話一次。

要求敘事時：

- `SER_LLM_MODE=scripted` 即使有 token 也不呼叫 Bedrock。測試套件就是這樣設的。
- `SER_LLM_MODE=auto`（預設）與 `SER_LLM_MODE=bedrock` 只有在憑證存在時才呼叫：非空的 `AWS_BEARER_TOKEN_BEDROCK`，或 `AWS_ACCESS_KEY_ID` 加上 `AWS_SECRET_ACCESS_KEY`，或 `AWS_PROFILE` 指向已存在的共用 credentials 或 config 檔，或 `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI`。這些都沒有時，模式維持 scripted，不會建立 client。
- Client 是啟動時建立的一個快取過的 `boto3` `bedrock-runtime` client。`BEDROCK_MODEL_ID` 預設 amazon.nova-lite-v1:0。`AWS_REGION` 預設 `us-east-1`。boto3 自己從環境讀 `AWS_BEARER_TOKEN_BEDROCK`。token 不是 client 參數。設定了這個 bearer token 時，行程會設定 `AWS_EC2_METADATA_DISABLED`。Converse 在工作執行緒上跑，並有逾時。審計裡的 latency 只算 Converse 那一次呼叫。Client 透過 `total_max_attempts` 總共允許 2 次嘗試。botocore 的 `max_attempts` 只計算第一次呼叫之後的重試，所以那裡的 2 會變成 3 次嘗試。
- 敘事失敗或沒有文字時，`schedule_get` 回傳 scripted 那句。使用者這一輪如果呼叫失敗，會顯示一句短錯誤，並在這一輪改走 pattern parser。畫面上的標籤是 Fallback: pattern parser (Bedrock error: <code>)。審計列存的是 code 和 request id，不是原始例外。沒有嘗試 Bedrock 時，標籤是 `Bedrock: off`。
- 每一次嘗試追加一筆 `bedrock_converse` 審計列，內容是 timestamp、model、region、request id、latency。那一列沒有 token。system prompt 禁止捏造事實、覆寫引擎、重排工具參數、宣稱權限、揭露被遮蔽的資料，以及自稱是唯一真實紀錄。
- `SER_BEDROCK_STUB` 設為 voice 只供測試，不會呼叫 AWS。徽章顯示 Bedrock: STUB (test)。審計列的 provider 與 model 都是 stub。故障時段使用 `SER_DEMO_DATE` 與 `SER_DEMO_TZ`。`SER_BEDROCK_STUB_DELAY` 是可選的測試用暫停，單位是秒。

當 dev panel 顯示 Bedrock 為 on，打字的一行，或一句以喚醒詞 Alexa 開頭的最終語音，會進入工具迴圈。上限是 4 輪 Converse 與 4 次工具執行。這個上限由伺服器按那個 `conversation_id` 執行。頁面也會在 4 步停下。Converse 收到的 `toolConfig` 是讀取與提案工具，再加上 `schedule_apply_replan`。`reset_demo_data`、`debug_confirm` 與 `verify_audit_chain` 不在那份清單裡，模型如果開口要，伺服器會拒絕。瀏覽器在自己既有的 MCP session 上執行每一個被接受的呼叫，所以 `schedule_apply_replan` 仍會出現 Confirm 卡。看板會在那張 Confirm 卡出現前重新整理一次，這一輪結束時再整理一次。格式錯誤的呼叫、未知的工具，或不符合 schema 的參數會停掉迴圈，那個呼叫不會被執行。模型不選時段、不搬預約、不捏造事實、也不確認套用。每一次提案是一筆 `agent_tool_call` 審計列。瀏覽器回報的結果存成 `client-reported`。確認套用之後，頁面回報 `completed`，並註明 `schedule_apply_replan` 與 plan id。客戶端狀態若是 `applied`，或長得像它的字，會被拒絕且不寫審計列。套用只由伺服器自己的 apply 路徑記錄。那一列沒有 token。同一個 token 能開的新 `conversation_id` 有上限，閒置的計數會過期。`GET /metrics` 與 agent 的 POST 使用另一個依客戶端 IP 位址計算的預算，和 MCP 洪水限制用同一個位址。它不是瀏覽器 session。非 JSON 或 HTTP 429 的回覆會顯示一句短訊息、重試，然後改用標成 Fallback: pattern parser (rate limit) 的 pattern parser。Bedrock 關閉時，對話框使用 pattern parser，頁面把它標成 Fallback: pattern parser (Bedrock off)。Bedrock 呼叫失敗時，這一輪同樣改用這個 parser，並標成 Fallback: pattern parser (Bedrock error: <code>)。若這次失敗發生在這一輪已經記錄故障之後，parser 會對那個故障呼叫 `schedule_propose_replan`，並從目前的狀態繼續。

Mic 按鈕是 push-to-talk。它在瀏覽器裡使用 `SpeechRecognition` 或 `webkitSpeechRecognition`，語言 en-US，並顯示即時逐字稿。一句以 Alexa 開頭的最終語句不需要按 Enter 就會送出。回覆顯示在氣泡裡，並用 `speechSynthesis` 唸出來。瀏覽器沒有語音 API，或麥克風被拒絕時，畫面上會留著提示，打字仍然可用。這個頁面不呼叫雲端語音服務。

`serSimulateUtterance` 與 `?utterance=` 查詢是 simulation hook。它們會等到 MCP session 存在、排程已載入、Bedrock 狀態已解析，而且沒有進行中的呼叫，包含尚未回來的 `/agent/step`。同一個頁面上的呼叫會一個接一個跑，佇列會等到這一輪的工具迴圈結束。然後才把一段逐字稿送進與辨識結果相同的函式，所以沒有麥克風的測試或螢幕錄影也能驅動這一輪。喚醒詞仍然要有。

種子日是 `SER_DEMO_DATE`（ISO 日期）。這個變數沒設定時，那天是 `SER_DEMO_TZ` 的今天，預設 Europe/London。審計時間戳維持真實的 UTC 時鐘，不會被改寫成示範日。MCP server 與 web shell 要用同一組值啟動。協定主控台寫的是 MCP spec 2025-11-25。

## Amazon Bedrock

```bash
export AWS_BEARER_TOKEN_BEDROCK=your-bedrock-api-key
export AWS_REGION=us-east-1
export BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
```

```bash
export SER_DEMO_DATE=2026-10-20
export SER_DEMO_TZ=Europe/London
```

`boto3`（`requirements.txt` 裡的 >=1.39）在啟動時建立一個快取過的 client。標準 AWS 憑證可以取代 bearer token。從那個環境啟動 MCP server。dev panel 從 `/metrics` 顯示 `Bedrock: on (amazon.nova-lite-v1:0, us-east-1)`，看板每次重新整理不會打一通 Converse。使用者的一輪才會呼叫 Converse。`test_bedrock_converse_live` 打這一通，`AWS_BEARER_TOKEN_BEDROCK` 沒設定時跳過。這個儲存庫不使用任何其他 AWS 服務。

## 架構

```
Simulated Alexa+ (web/, an MCP client)                         This repo
┌────────────────┐              Streamable HTTP           ┌─────────────────────────┐
│ schedule cards │  ──────── tools/call + Confirm ─────▶  │ FastMCP server           │
│ elicitation UI │              127.0.0.1:8765            │  engine + SQLite + audit │
└────────────────┘                                        └─────────────────────────┘
```

## 瀏覽器 demo（web/）—— simulated Alexa+ experience

```bash
python -X utf8 tools/dev_server2.py     # MCP server on http://127.0.0.1:8765/mcp (fresh temp DB each boot)
cd web && python app.py --port 8080     # web shell on http://127.0.0.1:8080 (any --port works)
```

也可以讓 MCP server 對著持久化的 DB 檔跑：`python -X utf8 -m mcp_server`。

這個 UI 就是 simulated Alexa+ experience。`web/` 是這個 repo 的一部分（本身是一個 MCP Streamable-HTTP 客戶端 UI）：FastAPI 提供靜態頁，並以同源代理把 `/mcp` 轉到 MCP server，`GET /mcp` 的 SSE 會逐塊轉發，所以伺服器發起的 `elicitation/create` 能即時抵達瀏覽器。套用確認卡只由人類點擊回答 —— demo 身分只承載在 `Authorization: Bearer <token>` 標頭裡，絕不放在工具參數中。

## 強化（OWASP MCP Security Cheat Sheet）

傳輸層的標頭驗證在**兩層**都跑，在任何 MCP 邏輯執行前就先擋掉 DNS-rebinding 瀏覽器／跨站攻擊者：

| 層 | 檢查 | 行為 |
|---|---|---|
| web 代理（`web/app.py`） | `Origin` ＋ `Host` 白名單 | 有但不認識 → JSON-RPC 錯誤 `-32002`、HTTP 403；沒有 Origin 則放行（原生 MCP 客戶端不會送）。任何 **loopback** 的 origin/host 在任何 port 都接受，所以 `--port` 設成 8080 以外也能用；外部 host/origin 依然被擋（這就是防 DNS-rebinding 的重點） |
| MCP server（`mcp_server/server.py`） | 純 ASGI 的 `TransportGuardMiddleware`，包住 Streamable HTTP app | 繞過代理直接連也套用同一套政策 |

另外還有結構化的**審計軌跡**（`audit_log` SQLite 資料表、`schedule_audit_get` 工具、web UI 的「Audit log」分頁）：每次工具呼叫都記下操作者、角色、工具、結果、明細與截斷的 token 提示。寫入是 best-effort，永遠不會讓工具回應出錯。產品級細節：**WAL journal 模式**（併發讀取不會卡在寫入鎖上）、**游標分頁**（`schedule_audit_get` 支援 `before_id` ＋ `tool_filter`，回傳 `next_before_id` 游標）、**一萬筆的滾動保留**（每次審計寫入後強制執行），以及覆蓋整條軌跡的 **SHA-256 雜湊鏈** —— `verify_audit_chain`（僅限管理員）會重算整條鏈並標出竄改、刪除或拼接，UI 上還有即時的「✓ chain N rows」／「⚠ tamper @row」徽章。MCP 的 guard middleware 與 web 代理都套用**每 IP 的 token-bucket 速率限制**（約 4 req/s、burst 16），遇到洪水以 HTTP 429／`-32002` 回應而不是放行。審計分頁有**工具篩選下拉選單**與 10 秒自動更新；每個 worker 執行緒重複使用一條**執行緒層級的 SQLite 連線**；若部署在不同的代理 port／HTTPS tunnel，可用 `SER_ALLOWED_ORIGINS`（逗號分隔的精確 origin，兩層都遵守）白名單化瀏覽器來源。

Tier 3 加項：每一筆審計紀錄還會存一份事件的**結構化 JSON 鏡像**（`detail_json`）—— 例如 `{tool, result, ...}` 加 `plan_id`、`blocked_count` 或 `schedule_version` —— 透過 `schedule_audit_get` 公開，並在審計分頁呈現成可展開的 `json` chip，讓 SIEM 類型的日誌擷取器不必解析散文就能拿到機器可讀欄位（這個鏡像屬 best-effort 且**不含**在雜湊鏈裡，所以它可以演進而不會破壞防篡改證據）。兩層都有 **`GET /metrics`** 觀測端點（MCP 在 :8765，web 代理在 :8080 並聚合兩者）：行程運行時間、token-bucket 狀態、排程版本、資料表列數與 journal 模式 —— JSON、`no-store`，且在消耗任何 MCP session 資源之前就可取得。UI 另有**深連結**（`/#audit` ／ `/?view=audit`）可直接開啟審計分頁，由一套 **Playwright 測試**涵蓋（28 項瀏覽器檢查，完整走過故障→提出→確認→套用：身分切換、面板、故障回報、dev console、確認卡、拒絕路徑、套用後 v3、響應式版面 —— 並以 mutation 驗證：每條檢查都實測過在注入對應缺陷時會失敗）。


```bash
python -X utf8 -m pytest tests/ -q
```

在 Linux 上量測。CPython 3.11.17、3.12.8 與 3.13.5，已安裝 Playwright 瀏覽器：**129 passed**、1 skipped。沒有那個瀏覽器：**121 passed**、9 skipped。託管 demo 變更之前，stub 與佇列修正那次在 CPython 3.11.17、3.12.3 與 3.13.16 上是有瀏覽器 **111 passed**、沒有瀏覽器 **103 passed**、9 skipped。這次 stub 與佇列修正之前的速率限制 commit 是有瀏覽器 **108 passed**、沒有瀏覽器 **102 passed**、7 skipped。那次速率限制修正之前的驗證 commit 是有瀏覽器 **99 passed**、沒有瀏覽器 **96 passed**、4 skipped。那些修正之前的工具迴圈 commit 是有瀏覽器 **90 passed**、沒有瀏覽器 **87 passed**、4 skipped。這個工具迴圈之前，同樣的 3.11 與 3.13 是有瀏覽器 **73 passed**、沒有瀏覽器 **71 passed**、3 skipped；那些 Bedrock 測試加入之前是有瀏覽器 **70 passed**、沒有瀏覽器 **68 passed**、2 skipped。

- `test_engine.py`（12）：時段搜尋、緩衝語意、權限、B4 範圍的引擎修正、故障可見於搜尋的回歸，以及選擇鍵的平手規則（最早開始者勝；完全平手時留在原設備）。
- `test_engine_edges.py`（6）：邊界 —— 半開區間、零時長、零緩衝相鄰、未知設備。
- `test_contract.py`（17）：對 `contracts/tools.json` 的 schema 相等性 ＋ 在 `SER_FROZEN_NOW=2026-10-20T12:00:00+01:00` 下逐位元重播 13 份凍結範例。
- `test_server.py`（8）：走 Streamable HTTP 的**真 uvicorn ＋ 真 MCP client** —— token/工具表、完整的故障→提出→套用→`already_applied` 迴路、拒絕 elicitation 後方案原封不動、版本前進後的 `plan_stale`、重置，以及一次**當機／重啟循環**（子行程、同一個 SQLite 檔）證明故障與待套用方案能跨越伺服器重啟存活。
- `test_llm.py`（14）：有／無憑證的模式選擇、禁令措辭、一次 stub 的 Converse 成功與一次 stub 的失敗（審計列、token 不入紀錄），以及 `test_bedrock_converse_live`（`AWS_BEARER_TOKEN_BEDROCK` 沒設定就跳過）。
- `test_accountability.py`（7）：真 client 的審計軌跡檢查 —— 研究員可見性的 SQL 邊界、併發重複套用只會套用一次（TOCTOU）、403 origin/host 拒絕會落進雜湊鏈的傳輸帳本、帳本在 `reset_demo_data` 後仍存、重播套用會留下鏈驗證為綠的審計列、審計分頁在任何頁邊界都不掉列（limit 1/2/3 走過 5 筆種子列），以及 `debug_confirm` 的 elicitation 結果會被審計。
- `test_web_proxy.py`（6）：`web/` 那一層 —— loopback 的 `Origin`/`Host` 在任何 port 都接受、外部 host/origin 依然 403、經代理轉發的真 MCP client 看得到全部 8 個工具且 `schedule_get` 可用、`/metrics` 聚合兩層，以及上游掛掉時回 502 加上重啟提示。
- `test_video_walk.py`（1 項測試、29 條場景檢查）：**逐幕**驅動真實 UI 走完 demo 影片腳本 —— 六個預約與兩台共軛焦、版本跳 v2 與故障橫幅、兩筆異動與機器可讀原因、確認卡寫明人類在環規則、取消後版本不變、確認後到 v3、切换身分後他人槽位顯示「Occupied」、審計分頁的時區標註 —— 所以錄影不可能出現旁白沒說的畫面。需要 Playwright；沒有瀏覽器時會乾淨跳過。
- `test_screenshots_current.py`（1）：`docs/screenshots/` 裡已提交的截圖必須仍反映當前版本 —— 它會重跑同樣的場景並比對記錄下來的文字，所以 README 的圖不可能在無聲無息中過期。需要 Playwright；沒有瀏覽器時會乾淨跳過。
- `test_hosted_deploy.py`（18）：託管 demo 的選用設定 —— 公開 Host 允許清單與數字 port 檢查、edge 設定的 client IP 標頭（絕不用 X-Forwarded-For）、proxy 覆寫 `x-ser-client-ip`、只信任 loopback 的伺服器 key、平台的 `HEAD /` 探測記為 `host_probe` 而真正的外來 Host 仍記為 `host`、`deploy/render_start.sh` 的啟動逾時與結束回報，以及只用淺色的頁面。
- `test_readme_i18n.py`（2）：本檔的英文與中文兩節必須一致 —— 同樣的指令、同樣的圖片、同樣的識別字、同樣的數字。會漂移的雙語 README 比沒有更糟，因為讀者無從分辨。第二條測試會檢查線上算繪後的頁面，確保語言切換確實會跳轉。

Windows 請用 `python -X utf8`，pytest 輸出才不會亂碼。

## Demo 截圖

```bash
python -X utf8 tools/shoot_screenshots.py
```

依當前版本重新產生六張 demo 截圖，對應影片腳本的每一幕（初始看板、故障、重排方案、確認卡、已套用、身分切換）。它會用 ephemeral port 自行起伺服器，所以不會干擾正在跑的 demo。

它會寫兩份：`docs/screenshots/`（納入版控 —— README 顯示的、評審看到的）與 `web/`（當次擷取，gitignored —— 你的錄影素材）。同時還會寫 `docs/screenshots/manifest.json`，記錄每一幀顯示的文字；`tests/test_screenshots_current.py` 會重跑同樣的場景並比對文字，所以已提交的截圖不可能在無聲無息中過期。

## 開發文件

- `docs/friction-log.md` —— 7 條得來不易的結論（只能用 SSE 的 elicitation、callback 必須 async、`Context.request_context.request.headers`、引擎可見性修正、`SER_FROZEN_NOW` 凍結時鐘）。
- `docs/product-feedback.md` —— 對 MCP 生態的觀察（elicitation 的落差、json_response 的陷阱）。
- `docs/dev-notes/COLLAB/CONTRACT-FROZEN.md` —— 給夥伴的契約；`docs/dev-notes/COLLAB/OUTBOX.md` 有客戶端接線指南。內部筆記在 `docs/dev-notes/`。原本的 `tools/_deep4.py` 到 `tools/_deep8.py` 探針現在在 `archive/`。
- `tools/check_readme_i18n.py` —— 確保本檔中英兩節內容一致（程式碼區塊、圖片、識別字、數字）。改動任一邊後請執行；`tests/test_readme_i18n.py` 會把它納入測試套件。

## 技術選型

| 元件 | 選擇 | 原因 |
|---|---|---|
| MCP SDK | `mcp==1.30.0`（FastMCP） | 官方、支援 2025-11-25 規格與 elicitation |
| 傳輸 | Streamable HTTP（SSE 回應） | 伺服器→客戶端 elicitation 的必要條件 |
| 資料庫 | SQLite（`server.db`） | 交易式版本控制 ＋ 審計紀錄，零維運 |
| 敘事 | Amazon Nova Lite，Bedrock Converse | 請求帶了 `x-ser-narrate` 時改寫 `schedule_get` 那句，並在 Bedrock 開啟時於模擬頁面跑 4 步的工具迴圈。看板重新整理維持 scripted 句子。沒呼叫或呼叫失敗時用 scripted 句子和 pattern parser。 |

## 授權

MIT —— 見 LICENSE。示範資料為虛構資料；未做生產環境強化。
