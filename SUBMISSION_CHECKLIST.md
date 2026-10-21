# Amazon Build, Ship, Shape Hackathon — submission checklist / 提交檢查清單

English translation of the original checklist. Each section keeps the original, then the English. Status marks are the author's. This translation does not re-measure them and does not change a check into a cross.

**TODO for the author:** the "70 passed" line is the checklist's own status note from 2026-10-21. The README states the count measured for this change. Do not read the "70" below as a new measurement.

**TODO for the author:** section 3 marks the AWS Builder / Amazon Bedrock items done. This translation does not verify a live Bedrock call. `boto3` is not in `requirements.txt`. Confirm before ticking AWS Builder on Devpost.

---

## 1. Required items / 必交項目

### Original

## 1. 必交項目

| 項目 | 狀態 | 證據 / 位置 |
|---|---|---|
| GitHub repo（公開） | ✅ | **https://github.com/Fu93/shared-equipment-rescue**（public，`master`＝已推送，MIT license） |
| README | ✅ | **中英雙語**（頂部可切換，兩節同檔避免兩份各自過期）；安裝/架構/demo 皆有；`python -m mcp_server` 一行啟動；web demo 兩行啟動；含 6 張 demo 截圖與逐幕說明 |
| **MCP 伺服器** | ✅ | `mcp_server/`，`mcp==1.30.0`，Streamable HTTP，`2025-11-25` |
| 工具（≥4） | ✅ | 8 個：`schedule_get`、`equipment_report_outage`、`schedule_propose_replan`、`schedule_apply_replan`、`schedule_audit_get`、`verify_audit_chain`、`reset_demo_data`、`debug_confirm` |
| **Elicitation** | ✅ | **真協定**：`schedule_apply_replan` 伺服器端 `ctx.elicit()`，拒絕→`not_confirmed` 無副作用；瀏覽器端確認卡只由人類點擊回答（`web/` TS SDK `ElicitRequestSchema` handler） |
| 狀態持久化 | ✅ | SQLite＋單調 `schedule_version`＋audit `change_log` |
| 權限 | ✅ | Header-only auth（`tok-manager/chen/wang/li`），researcher 掩碼視圖有測試鎖 |
| Product Feedback | ✅ | `docs/product-feedback.md` |
| Friction Log | ✅ | `docs/friction-log.md`（7 條） |
| web/ MCP client | ✅ | commit `c3249ef`/`ba7e2dc`：同源 streaming 代理＋確認卡＋MCP dev log；瀏覽器 E2E 28/28 |
| **Demo 影片 <3:00** | ⬜ 未拍 | 腳本見下（錄影即用 web UI，下列流程逐幕對應 `_shot_1..6.png`） |
| **Devpost 提交** | ⬜ 未填 | 主賽道 Alexa+；AWS Builder 勾選 |

> **截止**：2026-10-23 12:00 太平洋時間 = 20:00 倫敦時間。
> **本清單以最新實況為準**（2026-10-21：70 tests green；web 瀏覽器 E2E 28/28 PASS（已 mutation 驗證：注入缺陷即失敗）；server CLI E2E 19/19；深度 debug 探針全綠）。

The two blockquotes above are the original file's opening notes. They are placed here, next to section 1, because that is the status the table refers to.

### English

## 1. Required items

| Item | Status | Evidence / where |
|---|---|---|
| GitHub repo (public) | ✅ | **https://github.com/Fu93/shared-equipment-rescue** (public, `master` = pushed, MIT license) |
| README | ✅ | **Bilingual, Chinese and English** (a switch at the top; both sections live in one file so the two copies cannot go stale separately). Install, architecture, and demo are all there. `python -m mcp_server` starts it in one line. The web demo starts in two lines. Includes 6 demo screenshots and a frame-by-frame description |
| **MCP server** | ✅ | `mcp_server/`, `mcp==1.30.0`, Streamable HTTP, `2025-11-25` |
| Tools (≥4) | ✅ | 8: `schedule_get`, `equipment_report_outage`, `schedule_propose_replan`, `schedule_apply_replan`, `schedule_audit_get`, `verify_audit_chain`, `reset_demo_data`, `debug_confirm` |
| **Elicitation** | ✅ | **Real protocol:** server-side `ctx.elicit()` in `schedule_apply_replan`. Decline → `not_confirmed`, no side effects. The browser confirmation card is answered only by a human click (`web/` TS SDK `ElicitRequestSchema` handler) |
| Persistent state | ✅ | SQLite + monotonic `schedule_version` + audit `change_log` |
| Permissions | ✅ | Header-only auth (`tok-manager/chen/wang/li`). The researcher masked view is locked by tests |
| Product Feedback | ✅ | `docs/product-feedback.md` |
| Friction Log | ✅ | `docs/friction-log.md` (7 entries) |
| web/ MCP client | ✅ | commits `c3249ef` / `ba7e2dc`: same-origin streaming proxy + confirmation card + MCP dev log; browser E2E 28/28 |
| **Demo video <3:00** | ⬜ not recorded | Script below (record the web UI; the flow matches `_shot_1..6.png` frame by frame) |
| **Devpost submission** | ⬜ not filled in | Primary track Alexa+; AWS Builder checked |

> **Deadline:** 2026-10-23 12:00 Pacific Time = 20:00 London time.
> **This checklist follows the latest status it recorded** (2026-10-21: 70 tests green; web browser E2E 28/28 PASS, mutation-checked: injecting the defect makes the check fail; server CLI E2E 19/19; deep debug probes all green).

**TODO for the author:** "70 tests green", "browser E2E 28/28", "CLI E2E 19/19", and "deep debug probes all green" are the checklist's recorded status. They were not re-run for this translation.

---

## 2. Video script / 影片腳本

### Original

## 2. 影片腳本（2:30–2:50，對映 web E2E 28 個 PASS）

> **每一幕的畫面狀態都由 `tests/test_video_walk.py`（29 條場景檢查）自動驗證**：開頭六個預約、v2 與 outage banner、兩筆 move 與 reasons、確認卡文字、Cancel 後版本不變、Confirm 後 v3、切身分後掩碼、審計頁時區標註、徽章列不重疊。**腳本說什麼，螢幕就顯示什麼**——可以直接照這張表錄。
>
> 截圖由 `python -X utf8 tools/shoot_screenshots.py` 產生（`_shot_1_initial` → `_shot_6_wang_after`，一幕一張）。

| 時間 | 畫面 | 旁白 |
|---|---|---|
| 0:00–0:15 | 啟動兩伺服器 → `http://127.0.0.1:8080` 初始時間軸（`_shot_1_initial.png`） | 「六個預約、兩台共焦顯微鏡；瀏覽器直連 MCP 2025-11-25 Streamable HTTP，dev console 顯示真 `tools/call`」 |
| 0:15–0:40 | manager 回報 Confocal A 10:00–16:00 故障 → 看板 v2、B2/B4 標 blocked（`_shot_2_outage.png`） | 「一次工具呼叫：B2/B4 標 blocked、版本跳 v2、旁白即時解說」 |
| 0:40–1:20 | propose：Chen→B 11:15–12:15、Wang→A 16:00–17:00＋機器可讀 reasons（`_shot_3_proposed.png`） | 「引擎 15 分鐘網格、FIFO 按截止、避開 Li 不可動的 B3、15 分鐘緩衝」 |
| 1:20–1:45 | **摩擦亮點**：不可解預約顯示 per-equipment `earliest_possible` 診斷（敘事面板） | 「不說 impossible——告訴你最早何時可行、差在哪條規則」 |
| 1:45–2:10 | **elicitation 確認卡**：Cancel → not_confirmed 零副作用；Confirm → applied v3（`_shot_4_elicit.png` / `_shot_5_applied.png`） | 「人類在環：只有點擊能回答；LLM 不能代答」 |
| 2:10–2:30 | 右側身分切換 tok-wang：自己的 16:00 新時段＋他人 Occupied 掩碼（`_shot_6_wang_after.png`） | 「Header-only auth，權限在伺服器強制」 |
| 2:30–2:50 | 架構＋雙模式 LLM | 「Bedrock Converse 有憑證走真模型；無憑證走 scripted fallback——demo 不依賴雲端」 |

### English

## 2. Video script (2:30–2:50, mapped to 28 web E2E PASSes)

> **Every frame's on-screen state is checked automatically by `tests/test_video_walk.py` (29 scene checks):** six bookings at the start, v2 and the outage banner, two moves and their reasons, the confirmation-card text, the version unchanged after Cancel, v3 after Confirm, masking after the identity switch, time-zone labels on the audit page, and the badge row not overlapping. **What the script says is what the screen shows** — you can record from this table.
>
> Screenshots are produced by `python -X utf8 tools/shoot_screenshots.py` (`_shot_1_initial` → `_shot_6_wang_after`, one frame each).

| Time | Picture | Narration |
|---|---|---|
| 0:00–0:15 | Start both servers → initial timeline at `http://127.0.0.1:8080` (`_shot_1_initial.png`) | "Six bookings, two confocal microscopes. The browser talks directly to MCP 2025-11-25 Streamable HTTP, and the dev console shows a real `tools/call`." |
| 0:15–0:40 | The manager reports Confocal A down 10:00–16:00 → board v2, B2/B4 marked blocked (`_shot_2_outage.png`) | "One tool call: B2/B4 marked blocked, version jumps to v2, narration explains it as it happens." |
| 0:40–1:20 | Propose: Chen → B 11:15–12:15, Wang → A 16:00–17:00, plus machine-readable reasons (`_shot_3_proposed.png`) | "The engine uses a 15-minute grid, FIFO by deadline, avoids Li's immovable B3, and a 15-minute buffer." |
| 1:20–1:45 | **Friction highlight:** an unschedulable booking shows per-equipment `earliest_possible` diagnostics (narration panel) | "Don't say impossible — say the earliest time it would work, and which rule is in the way." |
| 1:45–2:10 | **Elicitation confirmation card:** Cancel → `not_confirmed`, zero side effects; Confirm → applied v3 (`_shot_4_elicit.png` / `_shot_5_applied.png`) | "Human in the loop: only a click can answer. The LLM cannot answer for you." |
| 2:10–2:30 | Identity switch on the right to tok-wang: his own new 16:00 slot, other people masked as Occupied (`_shot_6_wang_after.png`) | "Header-only auth. Permissions are enforced on the server." |
| 2:30–2:50 | Architecture + dual-mode LLM | "Bedrock Converse uses the real model when credentials are present; without credentials it uses the scripted fallback — the demo does not depend on the cloud." |

**TODO for the author:** the heading says 28 web E2E PASSes and the paragraph says 29 scene checks in `tests/test_video_walk.py`. Both numbers are in the original. This translation does not reconcile them.

**TODO for the author:** the 2:30–2:50 narration says Bedrock Converse uses a real model when credentials are present. This translation does not verify that a live call was made.

---

## 3. AWS Builder challenge / AWS Builder 挑戰符合

### Original

## 3. AWS Builder 挑戰符合

- [x] Bedrock 雙模式整合（`mcp_server/llm.py`：`Converse`＋scripted fallback，`SER_LLM_MODE`）
- [x] §7 六條禁令寫進 system prompt，測試鎖死措辭
- [x] 文件：README 段落＋friction log
- [ ] 錄影時旁白點名 Bedrock 回退設計

### English

## 3. Fit for the AWS Builder challenge

- [x] Bedrock dual-mode integration (`mcp_server/llm.py`: `Converse` + scripted fallback, `SER_LLM_MODE`)
- [x] The six prohibitions from §7 are written into the system prompt, and tests lock the wording
- [x] Docs: a README paragraph + the friction log
- [ ] During the recording, the narration names the Bedrock fallback design

**TODO for the author:** these boxes are copied from the original. This change did not verify a live Amazon Bedrock call. See the note at the top of this file before ticking AWS Builder on the Devpost form.

**TODO for the author:** the original says the friction log documents Bedrock. The friction log's seven entries, as translated, do not name Bedrock. Confirm which doc you meant.

---

## 4. Finish order / 收尾順序

### Original

## 4. 收尾順序

1. ~~Partner / web/ 改 MCP client~~ ✅ Lead 完成（`c3249ef`，E2E 28/28）
2. ✅ 重跑 `python -X utf8 -m pytest tests/ -q`（70 passed）
3. ✅ 公開 repo 已推：https://github.com/Fu93/shared-equipment-rescue
4. ✅ 重拍截圖：`python -X utf8 tools/shoot_screenshots.py` → `web/_shot_1..6.png`（對映上表每一幕，gitignored）
5. 錄影（腳本上表）→ 上傳 YouTube 公開 **[僅人類可做]**
6. Devpost 填寫：intro、Alexa+ 主賽道、AWS Builder 勾選、連 repo＋影片 **[僅人類可做]**
7. 10/22 全流程彩排一次；10/23 只做緩衝

### English

## 4. Finish order

1. ~~Partner / change `web/` into an MCP client~~ ✅ Lead done (`c3249ef`, E2E 28/28)
2. ✅ Re-ran `python -X utf8 -m pytest tests/ -q` (70 passed)
3. ✅ Public repo pushed: https://github.com/Fu93/shared-equipment-rescue
4. ✅ Screenshots retaken: `python -X utf8 tools/shoot_screenshots.py` → `web/_shot_1..6.png` (one per frame in the table above, gitignored)
5. Record (script in the table above) → upload to YouTube as public **[only a human can do this]**
6. Fill in Devpost: intro, Alexa+ primary track, AWS Builder checked, link the repo + the video **[only a human can do this]**
7. 10/22: rehearse the full flow once; 10/23: buffer only

**TODO for the author:** "Partner" is in the original. This translation does not say whether a human teammate must be added on the Devpost form.

**TODO for the author:** step 2's "70 passed" is the checklist's recorded result, not a count measured for this change.

**TODO for the author:** step 4 says the screenshots written for the recording scratch are `web/_shot_1..6.png` and are gitignored. The README also shows committed copies under `docs/screenshots/`. The original checklist does not mention `docs/screenshots/`.

---

## 5. Scoring map / 評分對照

### Original

## 5. 評分對照

| 評分項目 | 現況 |
|---|---|
| Tech Implementation | ✅ 進階：真 elicitation 協定＋冪等交易＋引擎回歸測試 |
| Design | ✅ web 確認卡＋掩碼視圖＋即時 MCP dev log 已落地 |
| Potential Impact | ✅ 真實場景：設備故障全天重排 |
| Idea Quality | ✅ 規則引擎守門＋LLM 只做敘事，可避免幻覺排程 |

### English

## 5. Scoring map

| Criterion | Status recorded in the original |
|---|---|
| Tech Implementation | ✅ Advanced: real elicitation protocol + idempotent transactions + engine regression tests |
| Design | ✅ Web confirmation card + masked view + live MCP dev log are in place |
| Potential Impact | ✅ A real situation: rescheduling a full day after an equipment outage |
| Idea Quality | ✅ The rules engine guards the writes and the LLM only narrates, which can avoid hallucinated schedules |

These are the original's own scores. This translation does not re-judge them.

---

## 6. Last reminders / 最後提醒

### Original

## 6. 最後提醒

- 任何數字都**不要**在錄影時現場算——照 web E2E 的 PASS 清單口播（28 條）。
- Windows 一律 `python -X utf8`；兩個服務器走不同終端（8765 MCP / 8080 web）。
- **repo 已經在 GitHub 公開**：https://github.com/Fu93/shared-equipment-rescue （Devpost 直接貼這個網址）。
- 錄影前先 `python -X utf8 tools/shoot_screenshots.py` 重拍截圖，確保素材與當前 UI 一致。
- 影片與 Devpost 是**僅剩兩項**，其他全部完成。

### English

## 6. Last reminders

- Do **not** calculate any number live during the recording — speak the web E2E PASS list (28 items).
- On Windows, always use `python -X utf8`. The two servers run in different terminals (8765 MCP / 8080 web).
- **The repo is already public on GitHub:** https://github.com/Fu93/shared-equipment-rescue (paste this URL straight into Devpost).
- Before recording, rerun `python -X utf8 tools/shoot_screenshots.py` so the frames match the current UI.
- The video and Devpost are **the only two items left**. Everything else is done.

**TODO for the author:** "the only two items left" and "everything else is done" are the original's claim on the day it was written. The video and Devpost rows in section 1 are still unchecked in that original.

---

### Original title line

# ✅ Amazon Build, Ship, Shape Hackathon — 提交檢查清單

### English

# Amazon Build, Ship, Shape Hackathon — submission checklist
