# COLLAB — 兩個 agent 的合作介面（請先讀這一頁）

這一頁是 **Lead（成員 A：`mcp_server/`、`tests/`、`contracts/`、`docs/`）** 與
**Partner（成員 B：`web/`）** 之間唯一的溝通管道。我們在同一個工作目錄、同一個檔案系統上工作。

> 如果你正在讀這一頁而且你負責 `web/`：請先讀
> [`CONTRACT-FROZEN.md`](CONTRACT-FROZEN.md)，那是你的 `web/` 必須對上的介面。
> 有話要說請寫進 [`INBOX-lead.md`](INBOX-lead.md)（append，不要覆蓋）。

---

## 1. 誰負責哪些目錄（不要跨線寫檔）

| 角色 | 擁有目錄 | 不要碰 |
|---|---|---|
| **Lead（A）** | `mcp_server/`、`tests/`、`contracts/`、`docs/`、`pytest.ini`、`requirements.txt` | `web/` |
| **Partner（B）** | `web/` | `mcp_server/`、`tests/`、`contracts/`、`docs/` |
| 共同 | `README.md`、`LICENSE` | 改之前先在 `INBOX-lead.md` 講一聲 |

跨線需要改別人的檔案時：**寫訊息到 `INBOX-lead.md` 或 `COLLAB/OUTBOX.md`，不要直接改**。
這樣才不會兩邊同時覆寫同一個檔案造成內容遺失。

## 2. 檔案用途

| 檔案 | 用途 | 誰寫 |
|---|---|---|
| `COLLAB/README.md` | 這一頁，規則 | Lead（少改） |
| `COLLAB/CONTRACT-FROZEN.md` | **凍結契約摘要**：工具名稱、輸入輸出、錯誤碼、事件格式 | Lead |
| `contracts/tools.json` | 機器可讀的 `inputSchema`／`outputSchema`（單一真相來源） | Lead |
| `contracts/examples/*.json` | 正常案例、找不到案例的**完整範例回傳**，可直接拿去開發 | Lead |
| `COLLAB/INBOX-lead.md` | **Partner → Lead** 的訊息（append-only） | Partner |
| `COLLAB/OUTBOX.md` | **Lead → Partner** 的訊息與要求（append-only） | Lead |
| `COLLAB/STATUS.md` | 目前建置狀態、測試結果、已知阻塞 | Lead（每次跑完測試更新） |
| `COLLAB/TASKS.md` | 任務看板（誰做什麼、狀態） | 兩人都可 append |

## 3. 協議（很短）

1. **契約先行。** `contracts/` 凍結後，任何欄位變更都要 Lead 在 `OUTBOX.md` 公告並更新範例。
   不要單方面改欄位名或型別。
2. **一小步一交付。** 每次改完在自己的目錄內自測；`main` 隨時都要能啟動。
3. **卡住超過一小時就寫訊息。** 不要默默猜。
4. **訊息格式**（append 到 INBOX/OUTBOX）：

```markdown
## [MSG-007] 2026-10-19 23:40 — Partner → Lead
- **主題**：`schedule_propose_replan` 的 `unresolved[].earliest_possible` 少了欄位
- **我做什麼**：
- **我需要什麼**：（具體，例如「請新增 `equipment_name` 欄位，或告訴我用 `equipment_id` 對照」）
- **阻塞程度**：Blocker / Major / Minor / 只是告知
```

5. **不要刪別人的訊息**，只在下面 append。

## 4. 現在的狀態

看 [`STATUS.md`](STATUS.md)（Lead 每次跑完測試就更新）與 [`TASKS.md`](TASKS.md)。

## 5. 目前的硬性事實（已在本機驗證）

- Python `3.12.10`；`mcp` SDK `1.30.0`、`fastmcp` `4.1.1` 已安裝在系統 Python。
- SDK 宣告 `LATEST_PROTOCOL_VERSION = "2025-11-25"` → 符合比賽要求的 ≥ 2025-11-25。
- `zoneinfo.ZoneInfo("Europe/London")` 可用（本機有 tzdata）。
- 本機**沒有** AWS 憑證、沒有 `~/.aws`。所以 `web/agent.py` 必須支援兩種模式：
  有 Bedrock 憑證走 Bedrock，沒有就走 scripted stub（見 `CONTRACT-FROZEN.md` 第 7 節）。
