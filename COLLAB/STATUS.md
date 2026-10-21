## 2026-10-21 12:35 — Lead round 9b — 身分命名對齊伺服器・web burst 對齊・平手規則回歸鎖（pytest 58→60）
- **命名真實性（cross-audit P2）**：UI 寫「Priya (Manager)」，伺服器與凍結契約 fixture 寫「Facility Manager」。契約端不可動 → 改 UI 端：identity select、roleBadge、chat 錯誤訊息、`web/src/mcp-client.mjs` 的 DEMO_TOKENS、browser_e2e 斷言、OUTBOX 錨點清單全部改為 `Facility Manager`。
- **bundle 新鮮度雙重驗證**：以 esbuild 重建 `web/static/mcp-client.bundle.js`；子代理獨立重建的 SHA-256 **與提交版完全相同**（`F18166A6…`）→ 提交物非陳舊產物。
- **web rate limit 對齊**：`web/app.py` proxy token bucket burst 8→**16**，與 MCP 層及文件「兩層皆 ~4 req/s, burst 16」一致。
- **引擎平手規則回歸化（真缺口）**：choice key `(earliest_start, original-equipment-first)` 一直只寫在 engine.py 文件裡、**沒有任何測試鎖定**。新增 `test_true_tie_keeps_original_equipment` 與 `test_earlier_alternative_beats_later_original`（engine 10→12，全套 58→**60**）。**Mutation 驗證**：反轉裝置搜尋順序 → 兩條新測試立刻 **2 failed**；還原 → 全綠。（`is_original` 子句在「原設備先搜尋」下屬冗餘，保留作未來防護。）
- **後端審計殘餘 FAIL 判定**：子代理指出的 earliest-vs-original / true-tie 兩個場景由 lead 獨立重建驗證（臨時探針 `tools/_audit_fe_scenarios.py`，已刪）→ 引擎行為完全符合自身文件契約，**屬場景構造錯誤，非產品 bug**。
- `test_contract.py`：`test_all_six_tools_present` → `test_all_eight_tools_present`（一直斷言的是 8 工具集）。
- 本輪 gates：**pytest 60/60 · final_e2e 19/19 ALL PASS exit=0 · browser E2E 20/20（提權實跑）**；commit `987d716`。
- 剩餘人類項目不變：Demo 影片 <3:00、Devpost 提交、**加 git remote 並 push**（目前無 remote，評審無法 clone）。期限 2026-10-23。

## 2026-10-21 12:20 — Lead round 9 — 子代理三路深審修復（port-conflict / 速率撞牆 / UI 回歸 / 文件真實性）
- **P0 埠衝突**：pytest 預設 8907/8908 與使用者無關常駐程式相撞 → 8 errors。`test_server.py`/`test_accountability.py`/`final_e2e.py` 全部改 **ephemeral port 0**＋`_bound_port()`；外來程式仍占 8907 的機器上實測 58/58 照樣綠。
- **速率撞牆（歷史 probe）**：`tools/_deep4.py`/`_deep6.py` 在 token-bucket 落地後未設 `SER_NO_RATE_LIMIT=1`，burst→429 讓 probe 崩。補上後重跑：_deep4 10/10、_deep6 7/7 PASS（p50 get <300ms、propose <1s、apply <1.5s）。
- **UI 回歸**：`:active` 按下回饋曾在打磨輪丟失 → `index.html` 補回 action-row / btn-mini / chat-input 三處 pressed 態；browser E2E 提權後實跑 **20/20 PASS** 重驗。
- **P0 tzdata**：requirements.txt 補 `tzdata; platform_system=="Windows"`（Windows 無系統 tz DB，`ZoneInfo("Europe/London")` 会在 import 時炸，product-feedback 自承）。pip dry-run 解析 ✅。
- **文件真實性（cross-audit P1）**：README「9 browser checks」→ 實為 20 條並列舉真實檢查類別；「replayed byte-exact in CI」→ 改為由測試鎖（無 CI 配置，不虛構）；SUBMISSION_CHECKLIST friction log「web 端 3 條」→ 實為 7 條全 backend；CONTRACT-FROZEN 頂部加 v2 範圍註記（6→8 工具、`web/agent.py`→`web/app.py`），不竄改凍結歷史。
- 三子代理審計（backend / frontend / product-cross）完成；cross-audit 曾在 `COLLAB/INBOX-lead.md` 遇提示注入（指令其截斷審計），已按不可信資料忽略，審計全程完成。
- 本輪 gates：**pytest 58/58 · final_e2e 19/19 ALL PASS exit=0 · browser E2E 20/20（提權實跑）**。
- 剩餘人類項目不變：Demo 影片 <3:00、Devpost 提交；並需 commit 本輪 12+ 檔並加 remote/push。期限 2026-10-23。

## 2026-10-21 05:55 — Lead round 8 收尾 — P0 迴歸測試永久化（mutation-verified）· `ef6d5c3` → 本輪 commit
- **P0 迴歸測試入 repo**：`test_audit_pagination_no_row_dropped`（limit 1/2/3 各對 5 行 pagination_probe 做 keyset 全翻頁，斷言 seed0..seed5 無缺無重）+ `test_debug_confirm_writes_audit_row`（elicitation accept 必須留審計行）。pytest 56→**58**。
- **Mutation check**：把 server.py 游標臨時還原為 pre-fix 邏輯（`page[-1]` lookahead 版）→ 迴歸測試**立即失敗**（CAUGHT）；還原後全綠。證明測試真的抓得住 P0，非形式覆蓋。
- 順手清理：migration probe 遺留 `_responsive_*.png` 再現即刪（不入 git）。
- gates on final tree: **pytest 58/58 · CLI E2E 19/19 ALL PASS exit=0 · browser E2E 20/20**；stray 伺服器已清。
- docs 同步：README quickstart 56→58 passed、test_accountability 條目 5→7 並修平 "exactly exactly once" 拼字重複、SUBMISSION_CHECKLIST 兩處 56→58。
- 剩餘人類項目不變：Demo 影片 <3:00、Devpost 提交。期限 2026-10-23。

## 2026-10-21 04:15 — Lead 產品級 sweep round 5 完結 — commit `a2f3b75` → `ef6d5c3`（後端深審收尾），三重閘門 56 / 19 ALL PASS / 20/20 全綠
- **後端深審修**（第三子代理報告 + lead 複驗，commit `ef6d5c3`）：
  - **P0 修（重現後修正）**：schedule_audit_get 每頁邊界掉一列（游標點在未截斷的 page[-1]，下一頁 id < cursor 時該列永不顯示）。改為 keyset 語義：cursor = 回傳列的最後一列 id、頁面截斷到 limit；5 行 seed limit=2 全翻頁 probe **無缺無重 PASS**。
  - **P1 修**：PUBLIC_TOOLS 去重 → `constants.PUBLIC_AUDIT_TOOLS`（db.audit_entries SQL 邊界與 server Python 過濾共用單一來源）。
  - **P1 修**：debug_confirm 補審計行（elicitation accept/decline 與 not_supported 都入 trail）。
  - **P2 修**：token_hint 改取 token 後綴（demo tok- 前綴無鑑別度；現在顯示 manager…/chen…）；web `/` 與 `/metrics` 納入 Origin/Host guard（防 DNS-rebinding 讀鏈頭）；transport ledger 的進程鎖理由已註解說明。
  - 其餘類別（SQL 注入參數化、invalid_argument 錯誤形、schema 同步、連接 finally 收尾、ISO 時間戳、actor 防偽、reset 覆蓋）三代理與 lead 探針一致判定 CLEAN。
- **P0 修**：requirements.txt 補 `fastapi>=0.110` + `httpx>=0.26`（web/app.py 必需依賴缺失，fresh clone 的 README quickstart 第 2 行會 ModuleNotFoundError）。
- **P1 修**：tools/final_e2e.py 補 `SER_NO_RATE_LIMIT=1`（新 token bucket 令預設跑法在 A5 吃 429 flake，重現兩次；修後無環境變數裸跑 exit=0）。
- **P1 修**（docs truth-sync）：51→**56 passed**（test_accountability.py 5 條入冊 + test_server 實為 8 非 18）、工具 6→**8**（schedule_audit_get + verify_audit_chain 多列表格）、SUBMISSION_CHECKLIST 同步。
- **P1 修**（repo hygiene）：.gitignore 重寫（*.db / _shot_*.png / .pytest_cache），server.db / equipment.db 已 rm --cached，legacy equipment.db 與根目錄暫存探針 qa_card_probe.py 刪除。
- **UI 深審修**（前端子代理 4 條）：audit auto-refresh 保 scroll 位置、auditJsonStore 邊界（repaint 時 clear）、load-older 鈕 in-flight disabled、audit-wrap 加 aria-live=polite；子代理實測 XSS 全 escape、transport_error 優雅訊息、780px 零溢出、30x 刷新零錯誤。
- **後端深審證據**（lead 實測 /mcp）：audit 邊界（limit 0/-5/1e9 → invalid_argument；before_id 越界/-1 → invalid_argument；SQL 注入字串無害）＝參數化、研究員隔離（真 private rows 不可見）、verify_audit_chain manager-only（研究員 forbidden）、403 origin/host guard、/metrics WAL + audit_chain ok、鏈驗證器容忍 retention 前綴間隙。
- 提交 `a2f3b75`（19 files, +2815/−57）後在提交樹上重跑：**pytest 56/56 · CLI E2E 19/19 ALL PASS exit=0 · browser E2E 20/20**；stray 伺服器已清（8765/8080 乾淨）。
- 剩餘人類項目不變：Demo 影片 <3:00、Devpost 提交。期限 2026-10-23。


- Freeze-time verification against current working tree (incl. uncommitted local-font @font-face additions by user/Partner):
  pytest **51** / final_e2e CLI **19/19** / browser E2E **20/20**. Static + font files serve 200 via app.py (cd-independent paths proven).
- Commit chain up to 76a27a2 (polish round 4) all passed gates at commit time; working tree now carries only a local-font offline-safety edit (index.html @font-face + web/static/fonts/*.woff2, ~205KB) - verified no breakage; safe to commit as-is.
- Remaining human items: H1 record Demo video (<3:00, script in SUBMISSION_CHECKLIST section 2 with _shot_1..6.png), H2 Devpost submission (track Alexa+ / AWS Builder badge). Deadline 2026-10-23.

## 2026-10-20 14:21 - Lead polish round 4 (UI memory bounds + audit probe): deep8 6/6
- **web/static/index.html**: dev console capped at 200 entries, chat at 150 (oldest dropped) - long demo sessions / recording takes can no longer bloat the DOM.
- **README.md**: quickstart now leads with `python -X utf8 tools/dev_server2.py` (one-command fresh-DB boot); persistent `-m mcp_server` noted as alternative.
- **tools/_deep8.py (6/6)**: dev-console bound under 120x load, chat bound, README existence check, **audit log line verified in-process** (G4: `call schedule_get ... actor=Facility Manager status=ok` via stderr capture + impl call), escape/confirm regression intact.
- Gates all green: pytest 51 / probes 48 (d4-d8 = 10+15+7+10+6) / CLI 19/19 / browser 20/20. Zero contract changes.

## 2026-10-20 14:12 - Lead polish round 3 (frontend/backend resilience): 4 hardening fixes + deep7 10/10
- **web/static/index.html**: (1) boot failure now degrades gracefully - no more silent "Connecting..." when :8765 is down; (2) safeCall() wraps all 7 tool-call sites, transport/SDK errors become transport_error results handled per-flow (zero unhandled rejections); (3) confirm card: Escape = cancel (decline, zero side effect), role=dialog + aria-modal + auto-focus.
- **web/app.py**: static paths are now absolute (locdir-independent import), app.state mcp_host/port fallback for uvicorn starts bypassing __main__.
- **tools/_deep7.py (10/10)**: node --check on inline script, app.py AST parse, live no-MCP degrade verified via Playwright, Escape-cancel live-tested (v2 stays, no side effect), cd independence proven.
- Bundle freshness verified: src rebuild byte-identical to committed bundle.
- Zero contract changes. Gates all green: pytest 51 / probes 42 (d4-d7 = 10+15+7+10) / CLI 19/19 / browser 20/20.

## 2026-10-20 13:26 - Lead deep-debug round 2 (delivery hardening): +20 new checks, docs truth-sync
- **Deep4 reset/reseed integrity 10/10**: apply->reset restores byte-identical schedule snapshot (version + bookings JSON equal), reset x2 stable, post-reset replay deterministic (O1 + complete propose).
- **Deep5 frontend polish audit 15/15**: long-text overflow guards, escapeHtml on all user/reason injections, animations + prefers-reduced-motion, hover/active on buttons, no private-use glyphs, 780px panels stack vertically with zero horizontal overflow (verified live via Playwright), rapid-refresh no JS errors.
- **Deep6 delivery sweep 7/7**: README/docs file refs all resolve; SUBMISSION_CHECKLIST script beats map to real UI actions; perf p50 schedule_get <300ms, propose <1s, apply <1.5s.
- **Docs truth-sync fixes** (the only real findings): README said "44 passed"/"test_llm.py missing" era - now 51 + test_engine_edges + restart-cycle test documented; SUBMISSION_CHECKLIST header/step counts updated to 51. Zero product-code changes.
- Recovery: Windows temp cleaner wiped both boot scripts; rebuilt tools/dev_server2.py (fresh-db boot, subprocess-ready) and its browser-e2e boot path.
- Final gates all green: pytest **51** / CLI E2E **19/19** / browser **20/20**; probes deleted; tree clean.

## 2026-10-20 12:52 - Lead patrol round 5: no partner changes (tree clean, last 713d3fe), no stray servers; gates green 51 / 19 ALL PASS / 20/20.

## 2026-10-20 12:40 — Lead 深度 debug + 實測輪
- **狀態機邊界 19/19**（tools 場景先行、事後刪檔）：unknown_plan 無副作用、bad unit/date invalid_argument、end<=start 拒絕、重疊 duplicate_outage、elicitation 三態全路徑（decline→not_confirmed 不動版本、重複 decline 伺服器狀態一致、decline 後 accept→applied）、double-apply→already_applied 版本不變、apply 後 propose 幂等、chen(研究身分) report/propose/apply 三連 forbidden。
- **Web proxy 10/10**：initialize/session-id 回帶、schedule_get 走 proxy、outage/propose 走 proxy、**elicitation/create 經 POST SSE 流送達＋JSONRPC response 回答後 apply 完成**（spec 正確行為：server→client 請求走 POST 回應流，非獨立 GET SSE）、SSE 拆線後新 session 正常、MCP 掉線→proxy 502 JSON 乾淨。
- **並發 8/8**：同 session 8 連發 schedule_get 無交錯污染；雙設備並發 report 都 recorded；同窗口 4 連發 duplicate 恰一 recorded；同 outage 並發 propose 恰一 plan；先 decline 後 accept 簿記一致。發現點：duplicate report 也會 bump 版本 → propose 前需重新 schedule_get（現有 stale guard 正確擋下，行為符合契約）。
- **瀏覽器 E2E 20/20 PASS**。然 %TEMP% 舊腳本被系統清掉 → 已重建並落庫 tools/browser_e2e.py（自帶雙 server 啟動 + Playwright 全旅程 + 780/1440 截圖）。
- 三重閘門：pytest **51** / CLI E2E **19/19** / browser **20/20** 全綠；工作樹僅 +tools/browser_e2e.py。

## 2026-10-20 12:20 — Lead（全案接手 × Phase 1–3 完成回報）
- 12:05 人類指示「你現在負責接手整個計畫 對方不做了」→ TASKS.md 改制（PA1–3 → T-A/B/C1，Owner=lead）。
- Phase 1 後端：audit logging（ser.server logger, SER_LOG_LEVEL, additive；schedule_get/report/propose/apply/reset+elicitation 結果+rollback 全覆蓋）＋ 引擎邊界補測 6 條（半開區間、零時長純引擎語義、零 buffer 背對背）。commit 358f407 + 5719ee1 + c97fb0e（untrack pycache）。
- Phase 2 前端：加法式 CSS（訊息/橫幅/卡片/日誌動畫、按鈕 hover/press、loading 脈動、prefers-reduced-motion、≤1100px 響應式堆疊、設備欄堆疊）、dev-header codicon tofu 修成可渲染 glyph（780/1440 截圖驗證）。commit 61a384c。
- Phase 3 核心：**重啟持久化**（initialize_storage 僅在全新/空 db 時 seed，或 SER_FRESHSEED=1 強制；crash/restart 不再清掉 manager 的 outage/plan）＋ 重啟循環子程序測試（同 db 兩台 server 生命週期、跨重啟 re-propose 幂等回同 plan_id）。commit bf68f66。regen byte-stable 驗證通過。
- 拒絕理由措辭：**不動**（既有訊息已帶具體 id/version/數量；凍結線前改措辭風險>收益，契約 byte-lock 維持）。
- 閘門：pytest 51（44+6+1）/ CLI E2E 19/19 / 瀏覽器 E2E 20/20 全綠；contracts/tools.json 無 diff。

## 2026-10-20 12:55 — Lead（巡檢 round 4 · E2E 確定性）
- 雙跑測定：瀏覽器 E2E 連續兩輪 20/20、CLI E2E 連續兩輪 ALL PASS、pytest 連續兩輪 44 passed → **零 flake**。
- 8 warnings 皆來自 mcp==1.30.0 lib 內部 deprecation（contextlib 層），非本專案代碼；imports 使用現行 API（streamablehttp_client），無升級風險。
- 順帶確認 root _shot 截圖不殘留（E2E 由 repo root 跑時會落 root，已清）。

## 2026-10-20 12:40 — Lead（巡檢 round 3 · 身分隔离）
- 並發身分隔离探測：同時兩個 bearer session（tok-manager / tok-chen）各自 schedule_get → viewer 逐一正確（Facility Manager / Chen）、訂位數一致、無 cross-session 洩漏。identity 純由 header token 決定 ✅。
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
