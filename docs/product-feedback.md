# Product Feedback / 產品回饋

### Original header

# Product Feedback（規劃書 §16）

本專案開發過程中對 MCP / Alexa+ 生態的實際觀察與建議，供評審與後續開發者參考。

### English

# Product Feedback (plan §16)

Observations and suggestions about the MCP / Alexa+ ecosystem from building this project, for judges and later developers.

English translation of the original notes. Each original section is kept, then the English. The hackathon asks, for each tool or API: what you used it for, what worked well, what needs work, how onboarding went, and whether you would build with it again. Those fields are filled only where the original says so. Anything it does not say is marked **TODO for the author**. No feedback was added from later review.

The original is six observations. It is not already split per SDK, and it does not answer every official question.

---

## 1. MCP elicitation

### Original

## 1. MCP elicitation 是殺手級功能，但生態還沒跟上
- **現況**：spec 2025-11-25 已定義 elicitation，官方 SDK 已實作，但（截至開發日）多數客戶端（Claude Desktop、VS Code 等公開 build）尚不支援 server-initiated elicitation。
- **實測**：無 elicitation callback 的 client 呼叫 `schedule_apply_replan` 時，伺服端 `ctx.elicit()` 拋 `McpError: Elicitation not supported`；工具層捕獲後安全降級為 `not_confirmed`（無副作用）。
- **建議**：MCP 伺服器作者一律要為 elicitation 不可用設計降級路徑；spec 應考慮新增 capability 宣告讓 server 提前偵測。

### English

## 1. MCP elicitation is a killer feature, but the ecosystem has not caught up
- **Current state:** Spec 2025-11-25 already defines elicitation, and the official SDK implements it, but (as of the day this was written) most clients (public builds of Claude Desktop, VS Code, and similar) do not yet support server-initiated elicitation.
- **What we measured:** When a client with no elicitation callback calls `schedule_apply_replan`, the server-side `ctx.elicit()` raises `McpError: Elicitation not supported`. The tool layer catches that and safely degrades to `not_confirmed` (no side effects).
- **Suggestion:** MCP server authors should always design a fallback for when elicitation is unavailable. The spec should consider adding a capability declaration so the server can detect this in advance.

### Hackathon fields

- **Tool / API / SDK:** MCP spec 2025-11-25 elicitation, and the official MCP SDK (`ctx.elicit()`), as named in the original.
- **Used for:** `schedule_apply_replan` asks the client to confirm before any write.
- **What worked well:** The official SDK implements elicitation. A client without a callback degrades to `not_confirmed` with no side effects.
- **What needs work:** As of the day this was written, most public clients (Claude Desktop, VS Code, and similar) do not support server-initiated elicitation. The original suggests a spec capability declaration so a server can detect that in advance, and a fallback in every server.
- **Onboarding:** **TODO for the author.** The original does not describe onboarding.
- **Would you build with it again (yes/no and why):** **TODO for the author.** The original calls elicitation a killer feature and does not give a yes or no.

---

## 2. `json_response` and server-to-client requests

### Original

## 2. `json_response` 模式應該在 spec 層級禁止與 server→client request 共存
- 純 JSON 模式靜默吞掉 elicitation 請求（沒有錯誤，只是永遠收不到），開發者除錯成本極高。
- 這是我們摩擦紀錄裡最陰險的一條（docs/friction-log.md #2）。

### English

## 2. `json_response` mode should be forbidden, at the spec level, from coexisting with server-to-client requests
- Pure JSON mode silently swallows elicitation requests (there is no error; they simply never arrive). The debugging cost for developers is extremely high.
- This is the most insidious entry in our friction log (docs/friction-log.md #2).

### Hackathon fields

- **Tool / API / SDK:** MCP SDK `FastMCP` `json_response` mode, together with elicitation (a server-to-client request). The original does not name a separate package version here.
- **Used for:** **TODO for the author.** This entry describes a failure mode, not a successful use.
- **What worked well:** **TODO for the author.** The original does not say what worked well.
- **What needs work:** Pure JSON mode swallows elicitation with no error. The original says this should be forbidden at the spec level when server-to-client requests exist, and points at friction log entry 2.
- **Onboarding:** **TODO for the author.** The original does not describe onboarding.
- **Would you build with it again (yes/no and why):** **TODO for the author.** The original does not say yes or no.

---

## 3. Identity: Authorization header vs tool arguments

### Original

## 3. 身份識別：Authorization header vs 工具參數
- 我們選擇「身份只來自 per-request `Authorization` header」，杜絕工具參數偽造 (`user_id` 參數欺騙)。
- 建議 MCP spec 把 HTTP transport 的標準 auth header 語意正式化（目前各家自訂）。

### English

## 3. Identity: Authorization header vs tool arguments
- We chose "identity comes only from the per-request `Authorization` header", which stops tool-argument forgery (`user_id` parameter spoofing).
- Suggestion: the MCP spec should formalize the meaning of the standard auth header on the HTTP transport (today each implementation defines its own).

### Hackathon fields

- **Tool / API / SDK:** MCP over HTTP, the `Authorization` header. The original does not name a client SDK for this item.
- **Used for:** Per-request identity, so a tool argument such as `user_id` cannot spoof the caller.
- **What worked well:** The original presents this as the choice that blocks argument forgery. It does not describe a separate success metric.
- **What needs work:** The original says HTTP-transport auth-header semantics are still custom per implementation, and suggests the spec formalize them.
- **Onboarding:** **TODO for the author.** The original does not describe onboarding.
- **Would you build with it again (yes/no and why):** **TODO for the author.** The original does not say yes or no.

---

## 4. Versioning and an idempotent `plan_id`

### Original

## 4. 版本化 + 冪等 plan_id 讓 managed classifier 安全
- `schedule_version` 單調遞增、`plan_id` 以 `(outage_id, based_on_version)` 冪等、apply 前 stale 檢查 — 這三件事讓 LLM 代理 remix 常見失敗（重複套用、過期套用）在協定層被擋掉，而非依賴 LLM 自律。

### English

## 4. Versioning plus an idempotent `plan_id` makes the "managed classifier" safe
- `schedule_version` increases monotonically, `plan_id` is idempotent on `(outage_id, based_on_version)`, and there is a stale check before apply. Those three things block common LLM-agent remix failures (applying twice, applying a stale plan) at the protocol layer, rather than relying on the LLM to police itself.

**TODO for the author:** the original heading keeps the English phrase "managed classifier" and does not define it.

### Hackathon fields

- **Tool / API / SDK:** **TODO for the author.** This entry describes this server's `schedule_version`, `plan_id`, and stale check. It does not name an external tool or SDK.
- **Used for:** Stopping double-apply and stale-apply without relying on the LLM.
- **What worked well:** The original says those three checks block those failures at the protocol layer.
- **What needs work:** **TODO for the author.** The original does not say what still needs work.
- **Onboarding:** **TODO for the author.** The original does not describe onboarding.
- **Would you build with it again (yes/no and why):** **TODO for the author.** The original does not say yes or no.

---

## 5. Per-equipment `earliest_possible` when no slot fits

### Original

## 5. 不可解方案的候選叉 (per-equipment earliest_possible)
- 不只回 `no_slot_found`，而是逐台設備回報 `earliest_start / blockers / would_work_if (deadline_would_need at_least ...)`。
- 這讓 manager 立即知道「延長 deadline 到 12:15 就能救回」— 人類決策所需的資訊密度，純規則引擎 + LLM 解釋層的產品示範點。

### English

## 5. A candidate fork for plans that cannot be solved (per-equipment `earliest_possible`)
- Do not return only `no_slot_found`. Report, per piece of equipment, `earliest_start / blockers / would_work_if (deadline_would_need at_least ...)`.
- This lets the manager know immediately that "extending the deadline to 12:15 saves it" — the information density a human decision needs, and a product demonstration of a pure rules engine plus an LLM explanation layer.

### Hackathon fields

- **Tool / API / SDK:** **TODO for the author.** This entry describes this server's replan diagnostics. It does not name an external tool or SDK. The LLM is mentioned only as an explanation layer.
- **Used for:** Telling a manager why a booking cannot move, and what would make it fit.
- **What worked well:** The original says the manager can see that extending the deadline to 12:15 would save the booking.
- **What needs work:** **TODO for the author.** The original does not say what still needs work.
- **Onboarding:** **TODO for the author.** The original does not describe onboarding.
- **Would you build with it again (yes/no and why):** **TODO for the author.** The original does not say yes or no.

---

## 6. Windows development friction

### Original

## 6. Windows 開發摩擦
- `zoneinfo` 在 Windows 無 tzdata 時需要 `pip install tzdata`；示範日 BST+01:00 一切正常。
- 建議 anyio/uvicorn 專案在 README 特別標註 Windows `-X utf8` 啟動。

### English

## 6. Windows development friction
- On Windows, `zoneinfo` needs `pip install tzdata` when tzdata is not already present. On the demo day, BST+01:00, everything was fine.
- Suggestion: anyio/uvicorn projects should specifically call out Windows `-X utf8` startup in the README.

### Hackathon fields

- **Tool / API / SDK:** Python `zoneinfo` (and the `tzdata` package) on Windows; anyio/uvicorn, for the README suggestion.
- **Used for:** Time zones (`Europe/London` is the demo zone elsewhere in this repo; this entry itself says the demo day was BST+01:00). **TODO for the author** if "used for" should name a more specific call site. The original only states the install requirement and that the demo day was fine.
- **What worked well:** On the demo day (BST+01:00) everything was fine, as the original says.
- **What needs work:** Windows without tzdata needs `pip install tzdata`. The original also suggests that anyio/uvicorn READMEs call out `python -X utf8` on Windows.
- **Onboarding:** The original's onboarding note is the missing tzdata install and the Windows UTF-8 flag. It does not describe account setup or docs quality beyond that.
- **Would you build with it again (yes/no and why):** **TODO for the author.** The original does not say yes or no.

---

## Not in the original

**TODO for the author:** the hackathon also asks for product feedback on each tool you actually used. These notes do not contain a separate entry for Amazon Bedrock, Alexa+, Kiro, or any other AWS API. Do not add one unless you write it from what you observed.
