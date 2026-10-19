# Product Feedback（規劃書 §16）

本專案開發過程中對 MCP / Alexa+ 生態的實際觀察與建議，供評審與後續開發者參考。

## 1. MCP elicitation 是殺手級功能，但生態還沒跟上
- **現況**：spec 2025-11-25 已定義 elicitation，官方 SDK 已實作，但（截至開發日）多數客戶端（Claude Desktop、VS Code 等公開 build）尚不支援 server-initiated elicitation。
- **實測**：無 elicitation callback 的 client 呼叫 `schedule_apply_replan` 時，伺服端 `ctx.elicit()` 拋 `McpError: Elicitation not supported`；工具層捕獲後安全降級為 `not_confirmed`（無副作用）。
- **建議**：MCP 伺服器作者一律要為 elicitation 不可用設計降級路徑；spec 應考慮新增 capability 宣告讓 server 提前偵測。

## 2. `json_response` 模式應該在 spec 層級禁止與 server→client request 共存
- 純 JSON 模式靜默吞掉 elicitation 請求（沒有錯誤，只是永遠收不到），開發者除錯成本極高。
- 這是我們摩擦紀錄裡最陰險的一條（docs/friction-log.md #2）。

## 3. 身份識別：Authorization header vs 工具參數
- 我們選擇「身份只來自 per-request `Authorization` header」，杜絕工具參數偽造 (`user_id` 參數欺騙)。
- 建議 MCP spec 把 HTTP transport 的標準 auth header 語意正式化（目前各家自訂）。

## 4. 版本化 + 冪等 plan_id 讓 managed classifier 安全
- `schedule_version` 單調遞增、`plan_id` 以 `(outage_id, based_on_version)` 冪等、apply 前 stale 檢查 — 這三件事讓 LLM 代理 remix 常見失敗（重複套用、過期套用）在協定層被擋掉，而非依賴 LLM 自律。

## 5. 不可解方案的候選叉 (per-equipment earliest_possible)
- 不只回 `no_slot_found`，而是逐台設備回報 `earliest_start / blockers / would_work_if (deadline_would_need at_least ...)`。
- 這讓 manager 立即知道「延長 deadline 到 12:15 就能救回」— 人類決策所需的資訊密度，純規則引擎 + LLM 解釋層的產品示範點。

## 6. Windows 開發摩擦
- `zoneinfo` 在 Windows 無 tzdata 時需要 `pip install tzdata`；示範日 BST+01:00 一切正常。
- 建議 anyio/uvicorn 專案在 README 特別標註 Windows `-X utf8` 啟動。
