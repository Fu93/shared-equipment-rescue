# ✅ Amazon Build, Ship, Shape Hackathon — 提交檢查清單

> **截止**：2026-10-23 12:00 太平洋時間 = 20:00 倫敦時間。
> **本清單以 2026-10-20 服務器實況為準**（commit `552c471`，44 tests green + 19/19 E2E）。

## 1. 必交項目

| 項目 | 狀態 | 證據 / 位置 |
|---|---|---|
| GitHub repo（公開） | ✅ | `shared-equipment-rescue`，MIT license |
| README | ✅ | 英文，安裝/架構/demo皆有；`python -m mcp_server` 一行啟動 |
| **MCP 伺服器** | ✅ | `mcp_server/`，`mcp==1.30.0`，Streamable HTTP，`2025-11-25` |
| 工具（≥4） | ✅ | 6 個：`schedule_get`、`equipment_report_outage`、`schedule_propose_replan`、`schedule_apply_replan`、`reset_demo_data`、`debug_confirm` |
| **Elicitation** | ✅ | **真協定**：`schedule_apply_replan` 伺服器端 `ctx.elicit()`，拒絕→`not_confirmed` 無副作用；`debug_confirm` 客戶端接線驗證工具 |
| 狀態持久化 | ✅ | SQLite＋單調 `schedule_version`＋audit `change_log` |
| 權限 | ✅ | Header-only auth（`tok-manager/chen/wang/li`），researcher 掩碼視圖有測試鎖 |
| Product Feedback | ✅ | `docs/product-feedback.md` |
| Friction Log | ✅ | `docs/friction-log.md`（7 條） |
| **Demo 影片 <3:00** | ⬜ 未拍 | 腳本見下 |
| **Devpost 提交** | ⬜ 未填 | 主賽道 Alexa+；AWS Builder 勾選 |
| web/ MCP client | ⬜ **Blocker** | Partner 待改（`COLLAB/OUTBOX.md` MSG-002/003 有逐行對照） |

## 2. 影片腳本（2:30–2:50，對照 `_final_e2e.py` 的 19 個 PASS）

| 時間 | 畫面 | 旁白 |
|---|---|---|
| 0:00–0:15 | `python -m mcp_server` + GUI 初始時間軸 | 「六個預約、兩台共焦顯微鏡，MCP 2025-11-25 伺服器已上線」 |
| 0:15–0:40 | manager 回報 Confocal A 10:00–16:00 故障 | 「一次寫入：B2/B4 被標記 blocked、版本跳到 2、audit log 記錄」 |
| 0:40–1:20 | propose：卡片顯示 B2→B 11:15–12:15、B4→A 16:00–17:00 | 「引擎 15 分鐘網格、FIFO 按截止、避開 Li 不可動的 B3、15 分鐘緩衝；機器可讀 reasons」 |
| 1:20–1:45 | **摩擦亮點**：提前到 09:15 会撞 Wang 自己的預約 → 顯示 per-equipment `earliest_possible` 診斷 | 「不可解時不說 impossible——告訴你 deadline 需放寬到 12:15」 |
| 1:45–2:10 | **elicitation 確認卡**（先按取消→什麼都沒變；再按確認→applied） | 「人類在環：MCP elicitation，拒絕零副作用，冪等 already_applied」 |
| 2:10–2:30 | 角色切換：Li 的視圖（自己 2 筆＋他人 Occupied 掩碼） | 「Header-only auth，權限在伺服器強制」 |
| 2:30–2:50 | 架構＋雙模式 LLM | 「Bedrock Converse 有憑證走真模型；無憑證走 scripted fallback——demo 不依賴雲端」 |

## 3. AWS Builder 挑戰符合

- [x] Bedrock 雙模式整合（`mcp_server/llm.py`：`Converse`＋scripted fallback，`SER_LLM_MODE`）
- [x] §7 六條禁令寫進 system prompt，測試鎖死措辭
- [x] 文件：README 段落＋friction log
- [ ] 錄影時旁白點名 Bedrock 回退設計

## 4. 收尾順序（今晚 M3 凍結前）

1. **Partner**：`web/` 改 MCP client（MSG-003 對照表）；不通則 Lead 收尾
2. 重跑 `python -X utf8 -m pytest tests/ -q`（44）＋ `python -X utf8 _final_e2e.py`（19/19）
3. 錄影（腳本上表）→ 上傳 YouTube 公開
4. Devpost 填寫：intro、Alexa+ 主賽道、AWS Builder 勾選、連 repo＋影片
5. 10/22 全流程彩排一次；10/23 只做緩衝

## 5. 評分對照

| 評分項目 | 現況 |
|---|---|
| Tech Implementation | ✅ 進階：真 elicitation 協定＋冪等交易＋引擎回歸測試 |
| Design | ⬜ 取決於 web/ 收尾（confirm 卡＋掩碼視圖是亮點） |
| Potential Impact | ✅ 真實場景：設備故障全天重排 |
| Idea Quality | ✅ 規則引擎守門＋LLM 只做敘事，可避免幻覺排程 |

## 6. 最後提醒

- 任何數字都**不要**在錄影時現場算——照 `_final_e2e.py` 的 PASS 清單口播。
- Windows 一律 `python -X utf8`；兩個服務器走不同終端（8765 MCP / 8080 web）。
- 影片與 Devpost 是**僅剩兩項**，其他全部完成。
