# Friction Log（規劃書 §16 模板）

格式：`日期時間 | 問題 | 我們試過什麼 | 根本原因 | 最終解法`

---

## 1. 2026-10-19 21:05 | MCP SDK 文件 ecosystem 混亂：`fastmcp` 或 `mcp`？pin 哪個？ |
**我們試過**：先裝 `fastmcp>=2.0.0`（jlowin 獨立專案），與官方 `mcp` 完全不同的 import 路徑（`fastmcp.FastMCP` vs `mcp.server.fastmcp.FastMCP`）。 |
**根本原因**：同名工具兩個 ecosystem，AI 建議程式碼常混用兩者 import。 |
**最終解法**：全案 pin `mcp==1.30.0`（官方 SDK，2025-11-25 spec），`requirements.txt` 明確單一依賴。

## 2. 2026-10-19 21:40 | elicitation 第一次完全沒有輸出 |
**我們試過**：`FastMCP(json_response=True)` + elicitation → client 收不到任何 elicitation 請求，tool 直接回 `not_confirmed`。 |
**根本原因**：JSON response 模式是純 request/response，伺服器→client 的請求（elicitation 是 server 發起的 request）沒有通道；必須 SSE responses。 |
**最終解法**：`FastMCP(stateless_http=False, json_response=False)`；elicitation 是「stateless 模式被靜默吞掉」的 triple 驗證於 spike5。

## 3. 2026-10-19 22:10 | elicitation callback 收到 INVALID_PARAMS |
**我們試過**：client 端用 `def cb(...)` 同步函式註冊 `elicitation_callback`。 |
**根本原因**：SDK 內部 `await cb(...)`，同步回傳值被視為非法 result。 |
**最終解法**：callback 必須 `async def`，回傳 `ElicitResult(action=...)`。spike5 三態（accept+confirm / decline / cancel）確定性通過。

## 4. 2026-10-19 22:30 | `ctx.request_context.request.headers` 型別不確定 |
**我們試過**：猜 `ctx.request_context.headers`、`ctx.session.request`。 |
**根本原因**：FastMCP 1.30 的 `Context.request_context` 是 property，指向該次 starlette Request 的 container；header 速度路徑無文件。 |
**最終解法**：`ctx.request_context.request.headers.get("authorization")`（spike_ctx_request 實測）。身份驗證完全來自 header，不從工具參數。

## 5. 2026-10-19 22:50 | engine 第二次通過計算漏掉新 outage |
**我們試過**：直接在傳入的 `world` 上搜尋 → engine 找到 outage 前的舊 slot（B4 停在 11:00 A）。 |
**根本原因**：純函式 `compute_plan(world, outage)` 收到 outage 參數但搜尋時只看 `world.outages`。 |
**最終解法**：compute_plan 內建 `search_world`（把 outage 併入 outages 列表），單元測試 10 條鎖死。

## 6. 2026-10-20 00:05 | contract replay 測試非確定性 |
**我們試過**：13 個 example fixture 對 live replay 深度相等 → `generated_at`/`confirmed_at` 每次都不同，永遠失敗。 |
**根本原因**：`db.now_iso()` 用真實時鐘。 |
**最終解法**：`SER_FROZEN_NOW` 環境變數凍結時鐘（生產不設即為真實時間），example 生成與 replay 都釘在 `2026-10-20T12:00:00+01:00`。

## 7. 2026-10-20 00:15 | Windows PowerShell 測試管線輸出亂碼 |
**我們試過**：`python -c` 長腳本 + `2>&1 | Tail-Object`。 |
**根本原因**：PS v5 沒有 `Tail-Object`（是 `Select-Object -Last`）；codepage 不符。 |
**最終解法**：一律 `python -X utf8` + `Select-Object`；長腳本寫檔再執行，不塞 here-string。
