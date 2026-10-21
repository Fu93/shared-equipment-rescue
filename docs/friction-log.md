# Friction Log / 摩擦紀錄

### Original header

# Friction Log（規劃書 §16 模板）

格式：`日期時間 | 問題 | 我們試過什麼 | 根本原因 | 最終解法`

### English

# Friction Log (plan §16 template)

Format: `date and time | problem | what we tried | root cause | final resolution`

English translation of the original log. Each entry keeps the original, then the English.

The original format, as written at the top of the file, was:

`日期時間 | 問題 | 我們試過什麼 | 根本原因 | 最終解法`

(date and time | problem | what we tried | root cause | final resolution)

The hackathon's friction-log fields are: task attempted, steps taken, expected vs. actual result, severity rating, workaround used, and actionable suggestion. Below, those fields are filled only from that entry. Severity is not in any original entry, so every severity line is **TODO for the author**. Where the original records a final fix but not a separate suggestion, the suggestion line is **TODO for the author**. No issue, time, or claim was added.

---

## 1. 2026-10-19 21:05 — which MCP package to pin

### Original

## 1. 2026-10-19 21:05 | MCP SDK 文件 ecosystem 混亂：`fastmcp` 或 `mcp`？pin 哪個？ |
**我們試過**：先裝 `fastmcp>=2.0.0`（jlowin 獨立專案），與官方 `mcp` 完全不同的 import 路徑（`fastmcp.FastMCP` vs `mcp.server.fastmcp.FastMCP`）。 |
**根本原因**：同名工具兩個 ecosystem，AI 建議程式碼常混用兩者 import。 |
**最終解法**：全案 pin `mcp==1.30.0`（官方 SDK，2025-11-25 spec），`requirements.txt` 明確單一依賴。

### English

## 1. 2026-10-19 21:05 | The MCP SDK documentation ecosystem is confusing: `fastmcp` or `mcp`? Which one do we pin? |
**What we tried:** Installed `fastmcp>=2.0.0` first (jlowin's separate project). Its import path is completely different from the official `mcp` (`fastmcp.FastMCP` vs `mcp.server.fastmcp.FastMCP`). |
**Root cause:** Two ecosystems share the tool name. AI-suggested code often mixes the two imports. |
**Final resolution:** Pin the whole project to `mcp==1.30.0` (official SDK, 2025-11-25 spec). `requirements.txt` states that single dependency.

### Hackathon fields

- **Task attempted:** Decide whether to pin `fastmcp` or `mcp`.
- **Steps taken:** Installed `fastmcp>=2.0.0` (jlowin's separate project) and compared it with the official `mcp` import path.
- **Expected vs. actual result:** **TODO for the author** on the expected result. The original does not say what outcome was expected. Actual, as written: the two packages expose different imports (`fastmcp.FastMCP` vs `mcp.server.fastmcp.FastMCP`), and AI-suggested code mixes them.
- **Severity rating:** **TODO for the author.** Not in the original.
- **Workaround used:** Pin `mcp==1.30.0` in `requirements.txt` as the only MCP dependency.
- **Actionable suggestion:** **TODO for the author.** The original records the pin, not a separate suggestion.

---

## 2. 2026-10-19 21:40 — first elicitation produced no output

### Original

## 2. 2026-10-19 21:40 | elicitation 第一次完全沒有輸出 |
**我們試過**：`FastMCP(json_response=True)` + elicitation → client 收不到任何 elicitation 請求，tool 直接回 `not_confirmed`。 |
**根本原因**：JSON response 模式是純 request/response，伺服器→client 的請求（elicitation 是 server 發起的 request）沒有通道；必須 SSE responses。 |
**最終解法**：`FastMCP(stateless_http=False, json_response=False)`；elicitation 是「stateless 模式被靜默吞掉」的 triple 驗證於 spike5。

### English

## 2. 2026-10-19 21:40 | The first elicitation produced no output at all |
**What we tried:** `FastMCP(json_response=True)` plus elicitation. The client received no elicitation request, and the tool returned `not_confirmed` directly. |
**Root cause:** JSON response mode is pure request/response. There is no channel for a server-to-client request (elicitation is a request the server initiates). SSE responses are required. |
**Final resolution:** `FastMCP(stateless_http=False, json_response=False)`. The rest of the sentence, translated as written: elicitation was the "triple" verification, in spike5, that it is silently swallowed in stateless mode.

**TODO for the author:** "triple 驗證於 spike5" is terse. This entry does not list the three checks. Entry 3 below names spike5 and three callback states (accept+confirm / decline / cancel). This translation does not treat those three states as this entry's triple check unless you confirm that.

### Hackathon fields

- **Task attempted:** Get a first elicitation to produce output.
- **Steps taken:** Ran `FastMCP(json_response=True)` with elicitation.
- **Expected vs. actual result:** The title says the first elicitation produced no output at all. Actual, as written: the client received no elicitation request, and the tool returned `not_confirmed`. The original does not spell out a separate expected payload beyond that contrast.
- **Severity rating:** **TODO for the author.** Not in the original. (Product feedback calls this the most insidious friction-log entry. That judgment is in `docs/product-feedback.md`, not in this entry.)
- **Workaround used:** `FastMCP(stateless_http=False, json_response=False)`, so responses are SSE.
- **Actionable suggestion:** **TODO for the author.** The original records the constructor flags, not a separate suggestion. Product feedback section 2 suggests forbidding this combination at the spec level; that suggestion is not repeated as a new claim here.

---

## 3. 2026-10-19 22:10 — elicitation callback returned INVALID_PARAMS

### Original

## 3. 2026-10-19 22:10 | elicitation callback 收到 INVALID_PARAMS |
**我們試過**：client 端用 `def cb(...)` 同步函式註冊 `elicitation_callback`。 |
**根本原因**：SDK 內部 `await cb(...)`，同步回傳值被視為非法 result。 |
**最終解法**：callback 必須 `async def`，回傳 `ElicitResult(action=...)`。spike5 三態（accept+confirm / decline / cancel）確定性通過。

### English

## 3. 2026-10-19 22:10 | The elicitation callback received INVALID_PARAMS |
**What we tried:** On the client, registered `elicitation_callback` with a synchronous `def cb(...)`. |
**Root cause:** The SDK internally does `await cb(...)`. A synchronous return value is treated as an illegal result. |
**Final resolution:** The callback must be `async def` and return `ElicitResult(action=...)`. spike5's three states (accept+confirm / decline / cancel) passed deterministically.

### Hackathon fields

- **Task attempted:** Register an elicitation callback.
- **Steps taken:** Registered a synchronous `def cb(...)` as `elicitation_callback`.
- **Expected vs. actual result:** Actual, as written: the callback received `INVALID_PARAMS` because a synchronous return value was treated as an illegal result. The original does not quote a separate expected result beyond the working `async def` form in the resolution.
- **Severity rating:** **TODO for the author.** Not in the original.
- **Workaround used:** Make the callback `async def` and return `ElicitResult(action=...)`.
- **Actionable suggestion:** **TODO for the author.** The original records the required callback shape, not a separate suggestion to the SDK.

---

## 4. 2026-10-19 22:30 — `ctx.request_context.request.headers` type was uncertain

### Original

## 4. 2026-10-19 22:30 | `ctx.request_context.request.headers` 型別不確定 |
**我們試過**：猜 `ctx.request_context.headers`、`ctx.session.request`。 |
**根本原因**：FastMCP 1.30 的 `Context.request_context` 是 property，指向該次 starlette Request 的 container；header 速度路徑無文件。 |
**最終解法**：`ctx.request_context.request.headers.get("authorization")`（spike_ctx_request 實測）。身份驗證完全來自 header，不從工具參數。

### English

## 4. 2026-10-19 22:30 | The type of `ctx.request_context.request.headers` was uncertain |
**What we tried:** Guessed `ctx.request_context.headers` and `ctx.session.request`. |
**Root cause:** In FastMCP 1.30, `Context.request_context` is a property pointing at the container for that Starlette Request. The original then says 「header 速度路徑無文件」. |
**Final resolution:** `ctx.request_context.request.headers.get("authorization")` (measured in spike_ctx_request). Authentication comes entirely from the header, not from tool arguments.

**TODO for the author:** 「header 速度路徑無文件」 is ambiguous. It may mean "the header fast path is undocumented" or it may be a typo. This translation does not pick one.

### Hackathon fields

- **Task attempted:** Read the caller's headers from the MCP `Context`.
- **Steps taken:** Tried `ctx.request_context.headers` and `ctx.session.request`.
- **Expected vs. actual result:** The title says the type was uncertain. The guesses are what was tried. The path that worked is in the resolution. The original does not state a separate expected type.
- **Severity rating:** **TODO for the author.** Not in the original.
- **Workaround used:** `ctx.request_context.request.headers.get("authorization")`, checked in spike_ctx_request. Identity is taken only from that header.
- **Actionable suggestion:** **TODO for the author.** The original says the header path is undocumented (see the TODO on wording above) and does not write a separate suggestion.

---

## 5. 2026-10-19 22:50 — the engine's second pass missed the new outage

### Original

## 5. 2026-10-19 22:50 | engine 第二次通過計算漏掉新 outage |
**我們試過**：直接在傳入的 `world` 上搜尋 → engine 找到 outage 前的舊 slot（B4 停在 11:00 A）。 |
**根本原因**：純函式 `compute_plan(world, outage)` 收到 outage 參數但搜尋時只看 `world.outages`。 |
**最終解法**：compute_plan 內建 `search_world`（把 outage 併入 outages 列表），單元測試 10 條鎖死。

### English

## 5. 2026-10-19 22:50 | On the second pass, the engine's calculation missed the new outage |
**What we tried:** Searched directly on the `world` that was passed in. The engine found the old slot from before the outage (B4 stayed at 11:00 on A). |
**Root cause:** The pure function `compute_plan(world, outage)` receives the outage argument, but the search only looks at `world.outages`. |
**Final resolution:** `compute_plan` builds an internal `search_world` (the outage is merged into the outages list). Locked by 10 unit tests.

**TODO for the author:** "第二次通過計算" is translated as "on the second pass, the calculation". If "第二次通過" means the second test run rather than a second scheduling pass, correct this sentence.

### Hackathon fields

- **Task attempted:** Recompute a plan after a new outage.
- **Steps taken:** Searched on the passed-in `world`.
- **Expected vs. actual result:** Actual, as written: the engine found the pre-outage slot (B4 stayed at 11:00 on A) because the search ignored the `outage` argument and read only `world.outages`. The original does not state the expected slot in a separate sentence.
- **Severity rating:** **TODO for the author.** Not in the original.
- **Workaround used:** Build `search_world` inside `compute_plan` and merge the outage into the outages list. The original says 10 unit tests lock this.
- **Actionable suggestion:** **TODO for the author.** The original records the code change, not a separate suggestion.

---

## 6. 2026-10-20 00:05 — contract replay was non-deterministic

### Original

## 6. 2026-10-20 00:05 | contract replay 測試非確定性 |
**我們試過**：13 個 example fixture 對 live replay 深度相等 → `generated_at`/`confirmed_at` 每次都不同，永遠失敗。 |
**根本原因**：`db.now_iso()` 用真實時鐘。 |
**最終解法**：`SER_FROZEN_NOW` 環境變數凍結時鐘（生產不設即為真實時間），example 生成與 replay 都釘在 `2026-10-20T12:00:00+01:00`。

### English

## 6. 2026-10-20 00:05 | Contract replay tests were non-deterministic |
**What we tried:** Deep-equality of 13 example fixtures against a live replay. `generated_at` / `confirmed_at` were different every time, so it always failed. |
**Root cause:** `db.now_iso()` uses the real clock. |
**Final resolution:** The `SER_FROZEN_NOW` environment variable freezes the clock (if it is unset in production, the clock is the real time). Example generation and replay are both pinned to `2026-10-20T12:00:00+01:00`.

### Hackathon fields

- **Task attempted:** Replay 13 example fixtures and deep-compare them with a live run.
- **Steps taken:** Compared the fixtures to a live replay.
- **Expected vs. actual result:** Expected, as written: deep equality with the fixtures. Actual: `generated_at` and `confirmed_at` changed every run, so the comparison always failed.
- **Severity rating:** **TODO for the author.** Not in the original.
- **Workaround used:** `SER_FROZEN_NOW`, with examples and replay pinned to `2026-10-20T12:00:00+01:00`. Unset means the real clock.
- **Actionable suggestion:** **TODO for the author.** The original records the environment variable, not a separate suggestion.

---

## 7. 2026-10-20 00:15 — Windows PowerShell test output was garbled

### Original

## 7. 2026-10-20 00:15 | Windows PowerShell 測試管線輸出亂碼 |
**我們試過**：`python -c` 長腳本 + `2>&1 | Tail-Object`。 |
**根本原因**：PS v5 沒有 `Tail-Object`（是 `Select-Object -Last`）；codepage 不符。 |
**最終解法**：一律 `python -X utf8` + `Select-Object`；長腳本寫檔再執行，不塞 here-string。

### English

## 7. 2026-10-20 00:15 | Windows PowerShell test-pipeline output was garbled |
**What we tried:** A long `python -c` script, plus `2>&1 | Tail-Object`. |
**Root cause:** PowerShell v5 has no `Tail-Object` (the cmdlet is `Select-Object -Last`). The code page did not match. |
**Final resolution:** Always use `python -X utf8` plus `Select-Object`. Write long scripts to a file and run the file; do not stuff them into a here-string.

### Hackathon fields

- **Task attempted:** Read test output from a Windows PowerShell pipeline.
- **Steps taken:** Ran a long `python -c` script and piped it through `2>&1 | Tail-Object`.
- **Expected vs. actual result:** The title says the output was garbled. Actual causes, as written: PowerShell v5 has no `Tail-Object`, and the code page did not match. The original does not quote the garbled text.
- **Severity rating:** **TODO for the author.** Not in the original.
- **Workaround used:** `python -X utf8`, `Select-Object`, and running long scripts from a file instead of a here-string.
- **Actionable suggestion:** **TODO for the author.** The original records the commands that worked, not a separate suggestion.
