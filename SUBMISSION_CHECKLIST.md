# ✅ Amazon Build, Ship, Shape Hackathon — 提交檢查清單

> **截止**：2026-10-23 12:00 太平洋時間 = 20:00 倫敦時間。
> **本清單以最新實況為準**（2026-10-21：69 tests green；web 瀏覽器 E2E 28/28 PASS（已 mutation 驗證：注入缺陷即失敗）；server CLI E2E 19/19；深度 debug 探針全綠）。

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

## 3. AWS Builder 挑戰符合

- [x] Bedrock 雙模式整合（`mcp_server/llm.py`：`Converse`＋scripted fallback，`SER_LLM_MODE`）
- [x] §7 六條禁令寫進 system prompt，測試鎖死措辭
- [x] 文件：README 段落＋friction log
- [ ] 錄影時旁白點名 Bedrock 回退設計

## 4. 收尾順序

1. ~~Partner / web/ 改 MCP client~~ ✅ Lead 完成（`c3249ef`，E2E 28/28）
2. ✅ 重跑 `python -X utf8 -m pytest tests/ -q`（69 passed）
3. ✅ 公開 repo 已推：https://github.com/Fu93/shared-equipment-rescue
4. ✅ 重拍截圖：`python -X utf8 tools/shoot_screenshots.py` → `web/_shot_1..6.png`（對映上表每一幕，gitignored）
5. 錄影（腳本上表）→ 上傳 YouTube 公開 **[僅人類可做]**
6. Devpost 填寫：intro、Alexa+ 主賽道、AWS Builder 勾選、連 repo＋影片 **[僅人類可做]**
7. 10/22 全流程彩排一次；10/23 只做緩衝

## 5. 評分對照

| 評分項目 | 現況 |
|---|---|
| Tech Implementation | ✅ 進階：真 elicitation 協定＋冪等交易＋引擎回歸測試 |
| Design | ✅ web 確認卡＋掩碼視圖＋即時 MCP dev log 已落地 |
| Potential Impact | ✅ 真實場景：設備故障全天重排 |
| Idea Quality | ✅ 規則引擎守門＋LLM 只做敘事，可避免幻覺排程 |

## 6. 最後提醒

- 任何數字都**不要**在錄影時現場算——照 web E2E 的 PASS 清單口播（28 條）。
- Windows 一律 `python -X utf8`；兩個服務器走不同終端（8765 MCP / 8080 web）。
- **repo 已經在 GitHub 公開**：https://github.com/Fu93/shared-equipment-rescue （Devpost 直接貼這個網址）。
- 錄影前先 `python -X utf8 tools/shoot_screenshots.py` 重拍截圖，確保素材與當前 UI 一致。
- 影片與 Devpost 是**僅剩兩項**，其他全部完成。
