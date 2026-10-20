## 2026-10-20 12:55 — Lead（巡檢 round 4 · E2E 確定性）
- 雙跑測定：瀏覽器 E2E 連續兩輪 20/20、CLI E2E 連續兩輪 ALL PASS、pytest 連續兩輪 44 passed → **零 flake**。
- 8 warnings 皆來自 mcp==1.30.0 lib 內部 deprecation（contextlib 層），非本專案代碼；imports 使用現行 API（streamablehttp_client），無升級風險。
- 順帶確認 root _shot 截圖不殘留（E2E 由 repo root 跑時會落 root，已清）。

## 2026-10-20 12:40 — Lead（巡檢 round 3 · 身分隔离）
- 並發身分隔离探測：同時兩個 bearer session（tok-manager / tok-chen）各自 schedule_get → viewer 逐一正確（Priya / Chen）、訂位數一致、無 cross-session 洩漏。identity 純由 header token 決定 ✅。
- 暫存探針已清（web/_soak.py、web/_ident_probe.py）。工作樹乾淨。
- Partner 自 10:54 backup 後零動作（INBOX 416B 不變）。

## 2026-10-20 12:05 — Lead（巡檢 round 2 · regen 確定性 + 惡意輸入面）
- regen 確定性：tools/gen_contracts.py + gen_examples.py 重跑 → git 零 diff（byte-stable ✅）。
- 惡意/畸形輸入探測：bad-JSON、no-Accept、1MB 大body、錯誤 Content-Type 全部被 MCP SDK/代理正確拒絕（406/400），無 crash，事後 health 200。
- Partner 仍無動工跡象（INBOX 416B 不變）。

# STATUS — 共享專案狀態（Lead/Partner 都可編輯，最後更新者標註）

## 2026-10-20 11:50 — Lead（穩定度巡檢 done · commit `c92900c`）
- **穩定度巡檢完成**（與 Partner Phase 1 平行，不重疊）：
  - DB 連線生命週期：5/5 `dbm.connect()` 呼叫點皆於 `finally` 關閉，零洩漏。
  - 裸 except 全查：5 處皆為刻意 fallback（DB rollback-re-raise / 參數格式→structured 狀態 / Bedrock 失敗→scripted fallback），無吞錯。
  - SSE 長開壓測：2 並發 MCP session（GET SSE held）＋交叉 tool call → 全 200、關閉後無 ghost socket、server 仍健康。
  - **修**：`web/app.py` proxy 上游傳輸錯誤捕獲 `ConnectError` → `TransportError`（涵蓋 ReadError/WriteError 等），502 fallback 更穩。
- 全套回歸閘門重跑：pytest **44 passed**、CLI E2E **19/19**、瀏覽器 E2E **20/20**。
- Partner 動工跡象：10:54 有 `server.py.backup`（內容相同，已由 Partner 範圍處理）。穩定度任務 Leader 自查 done，持續護線中。

## 2026-10-20 01:20 — Lead
- **L4 `web/` MCP client 化：done**（commit `c3249ef`）。FastAPI shell 同源代理 `/mcp` → :8765（SSE stream 逐塊轉發 — elicitation 可即時送達瀏覽器）。
- **L5 elicit verify：done**。TS SDK 1.32.1 `ElicitRequestSchema` handler；套件以 esbuild 打包；確認卡只由人類點擊回答。
- **L6 瀏覽器 E2E：20/20 PASS**（manager schedule → Wang 遮蔽 → outage→propose→decline→reset→accept(applied v3)→Wang 複核）。截圖 `_shot_1..6.png`（未入 git）。
- 重跑方式：`mcp_server` 在 :8765 + `python web/app.py --port 8080`（同一 demo DB）。
- 剩餘：影片 + Devpost（需人類）、README 收尾。

## 2026-10-20 00:25 — Lead
- **M0..M3 伺服器端：完成。** commit `f1c10a6`，34 tests green（10 engine + 17 contract + 7 live HTTP）。
- `mcp_server/`：6 工具全部就緒，elicitation 三態處理完畢（accept+confirm / decline / 不支援 → not_confirmed）。
- `contracts/tools.json` + 13 examples：從 live registry 產生，test_contract.py 鎖死 schema 相等 + example 位元組相等。
- `requirements.txt`：`mcp==1.30.0`。
- 啟動：`python -m mcp_server` → http://127.0.0.1:8765/mcp
- **Partner 待辦**：`web/` MCP client 化（見 OUTBOX.md MSG-002）。
- M3 功能凍結：今晚。剩餘：README/docs/friction-log、`web/` 收尾、清理暫存檔。
