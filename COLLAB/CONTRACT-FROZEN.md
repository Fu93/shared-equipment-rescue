# 凍結契約 v1（2026-10-19 23:35，Lead 發布）

> **範圍之後的擴增（v2，2026-10-20）**：本契約凍結時是 6 個工具；實作階段為補完
> 問責故事新增了 `schedule_audit_get` 與 `verify_audit_chain`（現為 8 個工具），
> 並以 `web/app.py` 同源代理取代原規劃的 `web/agent.py` 分層，multipart 細節以
> `contracts/tools.json` + `tests/test_contract.py` 為準。凍結的 schema 值未變。
>
> **這份文件是 `web/` 必須對上的介面。** 機器可讀版本：`contracts/tools.json`；
> 完整範例回傳：`contracts/examples/`。三者由 `tests/test_contract.py` 強制一致。
>
> **凍結規則**：欄位名稱、型別、`status` 列舉值不再單方面變更。要改，Lead 會在
> `COLLAB/OUTBOX.md` 公告新版本號並同步更新 `contracts/examples/`。

---

## 0. 連線資訊（本機開發）

| 項目 | 值 |
|---|---|
| MCP 伺服器 | `http://127.0.0.1:8765/mcp`（Streamable HTTP） |
| 傳輸路徑 | `/mcp`（GET 開 SSE、POST 送 JSON-RPC、DELETE 關閉 session） |
| protocolVersion | 伺服器宣告 `2025-11-25`（SDK `mcp==1.30.0` 的 `LATEST_PROTOCOL_VERSION`） |
| 認證 | `Authorization: Bearer <token>`，**由 HTTP 標頭判斷操作者** |
| 時區 | `Europe/London`。2026-10-20 為 BST，偏移 `+01:00` |
| 示範日 | `2026-10-20` |

### 示範 token（不是真實登入，README 會寫明）

| Token | user_id | 名稱 | 角色 | 可用設備 |
|---|---|---|---|---|
| `tok-manager` | `user-manager` | Facility Manager | `manager` | confocal-a, confocal-b |
| `tok-chen` | `user-chen` | Chen | `researcher` | confocal-a, confocal-b |
| `tok-wang` | `user-wang` | Wang | `researcher` | confocal-a |
| `tok-li` | `user-li` | Li | `researcher` | confocal-b |

> **注意**：計畫 §8 要求帳號切換有「Facility manager、Chen、Li、Wang」四個身分，
> 而 §3 的表格把 Chen 放在兩台設備上、Li 只在 B、Wang 只在 A。因此存在一個獨立的
> `user-manager` 帳號，Chen 是 researcher。這是對 §3 + §8 的合併解讀，已寫進 README 限制段。

---

## 1. 工具清單

| 工具 | 用途 | 誰能呼叫 |
|---|---|---|
| `schedule_get` | 讀取某單位某天排程 | 任何人（依角色遮罩） |
| `equipment_report_outage` | 記錄故障、標記受影響預約 | 僅 `manager` |
| `schedule_propose_replan` | 產生並保存重排方案（不改預約） | 僅 `manager` |
| `schedule_apply_replan` | elicitation 確認後套用方案 | 僅 `manager` |
| `reset_demo_data` | 還原示範初始狀態（錄影用） | 僅 `manager` |
| `debug_confirm` | M0 驗證用：只發 elicitation 並回傳結果 | 任何人 |

> 前四個是計畫 §5 的正式工具。`reset_demo_data` 是 §8「重置」按鈕的必要後端，
> `debug_confirm` 是 §6 明訂的第一天驗證工具。兩者皆標記為 demo-only。

---

## 2. 全域約定

### 2.1 時間

**所有時間欄位一律是帶時區偏移的 ISO 8601 字串**，例如 `2026-10-20T11:15:00+01:00`。

> 計畫 §5.3 的範例寫 `"until": "11:00"`，那是給人看的簡寫。實作統一用完整 ISO 8601，
> 由網頁負責格式化成 `11:15`。這樣 agent、卡片、測試都只有一種解析方式。

### 2.2 每個工具都有 `status`

每個工具都回傳 `structuredContent`，且**一定含 `status` 欄位**。前置條件不成立時
`status` 換成失敗值、**不產生任何副作用**，而 `isError` 保持 `false`，讓 LLM 看到
具體原因而不是例外堆疊。

### 2.3 預約狀態

| 值 | 意義 |
|---|---|
| `confirmed` | 正常預約 |
| `blocked` | 被故障影響，尚未處理 |
| `unresolved` | 方案已確認但仍找不到時段，保留原時段待人工安排 |
| `occupied` | **只有研究人員視角**：別人的預約，時間與設備可見、身分隱藏 |

### 2.4 結構化原因（`Reason`）

所有解釋都用同一種物件，`code` 決定其他欄位：

| `code` | 附加欄位 | 說明 |
|---|---|---|
| `original_slot_in_outage` | `outage_id`, `until` | 原時段落在故障區間 |
| `equipment_down` | `until` | 該設備在該時間不可用 |
| `switched_equipment` | `from`, `to` | 換設備 |
| `stayed_on_original_equipment` | `equipment_id` | 留在原設備 |
| `blocked_by_fixed_booking` | `booking_id`, `until` | 被不可移動的預約擋住，到 `until` 為止 |
| `blocked_by_booking` | `booking_id`, `start`, `end` | 被其他預約擋住 |
| `buffer` | `minutes` | 需要緩衝時間 |
| `user_busy` | `booking_id`, `start`, `end` | 使用者自己的其他預約 |
| `outside_operating_hours` | `opens`, `closes` | 超出開放時段 |
| `deadline_ok` | `end`, `deadline` | 在截止時間內完成 |
| `deadline_missed` | `end`, `deadline` | 超過截止時間 |
| `deadline_would_need` | `at_least` | **只要把截止時間放寬到 `at_least` 就能成立** |
| `no_permission` | `equipment_id` | 使用者無權限 |
| `not_movable` | — | 受影響但不可移動 |
| `no_slot_found` | — | 依目前規則找不到 |

時間型欄位（`until`、`start`、`end`、`opens`、`closes`、`deadline`、`at_least`）都是 ISO 8601。
`minutes` 是整數。`booking_id`、`outage_id`、`equipment_id`、`from`、`to` 是字串。

### 2.5 版本號

`schedule_version` 是單調遞增整數，存在 `meta` 表。**每次寫入加一**：

- `equipment_report_outage` 成功記錄一筆新故障 → `+1`
- `schedule_apply_replan` 成功套用 → `+1`
- `schedule_propose_replan` 只寫 `plans` 表，**不加一**（方案不改排程）
- `reset_demo_data` 回到 `1`

用途：呼叫端看到舊版本時，方案必須作廢重算，避免蓋掉別人的改動。

---

## 3. `schedule_get`

### 輸入

| 欄位 | 型別 | 必填 | 預設 | 說明 |
|---|---|---|---|---|
| `unit_id` | string | 否 | `lab-a` | 管理單位 |
| `date` | string | 否 | `2026-10-20` | `YYYY-MM-DD` |

> 沒有任何參數可以指定操作者身分。

### 輸出

| 欄位 | 型別 | 說明 |
|---|---|---|
| `status` | `"ok"` \| `"forbidden"` \| `"invalid_argument"` | |
| `schedule_version` | integer | |
| `timezone` | string | `Europe/London` |
| `date` | string | |
| `unit_id` | string | |
| `unit_name` | string | |
| `viewer` | object | `{user_id, name, role}` |
| `equipment` | `Equipment[]` | |
| `bookings` | `Booking[]` | 依 `start` 排序 |
| `open_outages` | `Outage[]` | 尚有未解決預約的故障 |
| `pending_plans` | `PendingPlan[]` | `status='proposed'` 的方案 |
| `message` | string \| null | 給 LLM 的一句話摘要 |

**`Equipment`**

| 欄位 | 型別 |
|---|---|
| `id`, `name` | string |
| `available_start`, `available_end` | string，`HH:MM` |
| `buffer_minutes` | integer |
| `outages` | `OutageWindow[]`（`{id, start, end, reason}`） |

**`Booking`**

| 欄位 | 型別 | 說明 |
|---|---|---|
| `id` | string | |
| `user_id` | string \| null | 被遮罩時為 `null` |
| `user` | string | 被遮罩時為 `"Occupied"` |
| `role` | string \| null | |
| `equipment` | string | equipment_id |
| `equipment_name` | string | |
| `start`, `end` | string | 目前（current）起訖 |
| `deadline` | string \| null | 被遮罩時為 `null` |
| `status` | 見 §2.3 | |
| `movable` | boolean | 被遮罩時 `false` |
| `masked` | boolean | 是否為研究人員看到的他人預約 |
| `affected_by_outage` | string \| null | 若受影響，帶該 outage_id |

**`Outage`**

| 欄位 | 型別 |
|---|---|
| `id`, `equipment`, `equipment_name` | string |
| `start`, `end` | string |
| `reason` | string \| null |
| `affected_booking_ids` | string[] |
| `unresolved_booking_ids` | string[] |
| `resolved` | boolean（`unresolved_booking_ids` 為空且無 `blocked`） |

**`PendingPlan`**

| 欄位 | 型別 |
|---|---|
| `plan_id`, `outage_id` | string |
| `based_on_version` | integer |
| `is_complete` | boolean |
| `change_count`, `unresolved_count` | integer |
| `created_at` | string |

### 權限

`manager` 看全部。`researcher` 只看自己的預約；他人預約 `masked=true`、`user="Occupied"`、
`user_id=null`、`role=null`、`deadline=null`、`status="occupied"`、`movable=false`，
但 `id`、`equipment`、`start`、`end` 保留，讓時間軸畫得出來。

---

## 4. `equipment_report_outage`

### 輸入

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `equipment_id` | string | 是 | |
| `start` | string | 是 | ISO 8601，帶時區 |
| `end` | string | 是 | ISO 8601，帶時區 |
| `reason` | string | 否 | |

### 檢查（依序）

1. 操作者是 `manager`，否則 `forbidden`
2. `equipment_id` 存在且屬於操作者所屬單位，否則 `unknown_equipment`
3. `end > start`，否則 `invalid_argument`（`field="end"`）
4. `start` 與 `end` 都落在示範日 `[2026-10-20T00:00, 2026-10-21T00:00)`（Europe/London），否則 `invalid_argument`（`field="start"` 或 `"end"`，附 `message` 說明這是示範限制）
5. 與同一設備**時間重疊**的既有故障 → `duplicate_outage`，回傳既有 `outage_id`，**不加版本**

### 輸出

| 欄位 | 型別 | 說明 |
|---|---|---|
| `status` | `"recorded"` \| `"duplicate_outage"` \| `"forbidden"` \| `"unknown_equipment"` \| `"invalid_argument"` | |
| `outage_id` | string \| null | |
| `equipment` | object \| null | `{id, name, unit_id}` |
| `affected_bookings` | `AffectedBooking[]` | |
| `unaffected_count` | integer | 該設備當天其他預約數 |
| `schedule_version` | integer | 記錄後的版本 |
| `message` | string \| null | |

**`AffectedBooking`**：`{id, user, user_id, start, end, deadline, status}`（複製自原時段，非遮罩）

### 副作用（單一交易）

- 新增 `outages` 一列
- 與故障時間重疊的該設備預約 `status` → `blocked`
- `schedule_version += 1`

---

## 5. `schedule_propose_replan`

### 輸入

| 欄位 | 型別 | 必填 | 說明 |
|---|---|---|---|
| `outage_id` | string | 是 | |
| `schedule_version` | integer | 是 | 呼叫端看到的版本 |

### 輸出

| 欄位 | 型別 | 說明 |
|---|---|---|
| `status` | `"proposed"` \| `"plan_stale"` \| `"forbidden"` \| `"unknown_outage"` \| `"outage_resolved"` \| `"invalid_argument"` | |
| `plan_id` | string \| null | 失敗時 `null` |
| `outage_id` | string | |
| `based_on_version` | integer \| null | |
| `schedule_version` | integer | **目前**版本 |
| `changes` | `Change[]` | |
| `unresolved` | `Unresolved[]` | |
| `is_complete` | boolean | `unresolved` 為空 |
| `summary` | object | `{affected, rescheduled, unresolved}` |
| `generated_at` | string \| null | |
| `message` | string \| null | |

### 前置條件（依序）

1. `manager`，否則 `forbidden`
2. outage 存在，否則 `unknown_outage`
3. 該 outage 仍有 `blocked` 預約，否則 `outage_resolved`
4. `schedule_version` **等於**目前版本，否則 `plan_stale`（附目前 `schedule_version`，**不建立方案**）

### 冪等

同一 `outage_id` + 同一 `based_on_version` 已存在 `proposed` 方案時，**直接回傳那個方案**
（不新建）。版本前進後，舊的 `proposed` 方案被標為 `stale`。

### `Change`

| 欄位 | 型別 |
|---|---|
| `booking_id`, `user`, `user_id` | string |
| `original_equipment`, `original_equipment_name` | string |
| `original_start`, `original_end` | string |
| `new_equipment`, `new_equipment_name` | string |
| `new_start`, `new_end` | string |
| `reasons` | `Reason[]`（**至少一條**） |

### `Unresolved`

| 欄位 | 型別 |
|---|---|
| `booking_id`, `user`, `user_id` | string |
| `equipment`, `equipment_name` | string（原設備） |
| `original_start`, `original_end` | string |
| `deadline` | string \| null |
| `movable` | boolean（`false` 表示不可移動而被留下） |
| `reasons` | `Reason[]`（**至少一條**） |
| `earliest_possible` | `EarliestPossible[]`（每台有權限的設備一筆） |

### `EarliestPossible`

| 欄位 | 型別 | 說明 |
|---|---|---|
| `equipment_id`, `equipment_name` | string | |
| `status` | `"available_after_deadline"` \| `"unavailable"` \| `"no_permission"` \| `"no_slot_today"` | |
| `earliest_start`, `earliest_finish` | string \| null | `available_after_deadline` 時必定有值 |
| `blockers` | `Reason[]` | 擋住的原因 |
| `would_work_if` | `Reason[]` | 能讓它成立的條件，例如 `deadline_would_need` |

> **計算時機（重要）**：`earliest_possible` 在主方案產生**之後**的第二輪計算，
> 使用**最終**佔用狀況、且**只對該筆預約忽略截止時間**。所以如果 B4 已被移到 16:00，
> B2 在 A 上的最早可行就會是 17:00 之後，而不是 16:00。這是計畫 §5.3
> 「重新搜尋一次」的字面要求，也避免給出與方案矛盾的答案。

---

## 6. `schedule_apply_replan`

### 輸入

| 欄位 | 型別 | 必填 |
|---|---|---|
| `plan_id` | string | 是 |
| `schedule_version` | integer | 是 |

### `status` 與順序

| 順序 | 條件 | `status` | 副作用 |
|---|---|---|---|
| 1 | 非 `manager` | `forbidden` | 無 |
| 2 | plan 不存在 | `unknown_plan` | 無 |
| 3 | plan 已 `applied` | `already_applied` | 無（回傳先前結果） |
| 4 | `schedule_version` ≠ 目前版本，或 plan 的 `based_on_version` ≠ 目前版本，或 plan 已 `stale` | `plan_stale` | 無 |
| 5 | elicitation 未取得 `confirm=true`（拒絕／取消／逾時／不支援） | `not_confirmed` | 無 |
| 6 | 交易失敗 | `apply_failed` | 整筆回滾 |
| 7 | 成功 | `applied` | 見下 |

### 輸出

| 欄位 | 型別 |
|---|---|
| `status` | 上表 |
| `plan_id`, `outage_id` | string \| null |
| `applied_changes` | `AppliedChange[]` |
| `unresolved` | `Unresolved[]` |
| `new_version` | integer |
| `confirmed_by` | object \| null（`{user_id, name, role}`） |
| `confirmed_at` | string \| null |
| `message` | string \| null |

**`AppliedChange`**：`{booking_id, user, original_equipment, new_equipment, from_start, from_end, to_start, to_end, reasons}`

### 交易內容（單一 `BEGIN IMMEDIATE`）

1. 每筆 change：更新 `bookings.current_start/current_end/equipment_id`、`status='confirmed'`
2. 每筆 change：寫 `change_log`（`before_change`、`after_change` JSON、`confirmed_by`、`confirmed_at`）
3. 每筆 unresolved：`status='unresolved'`（**不動時間**）
4. `plans.status='applied'`、`confirmed_by`、`confirmed_at`
5. `schedule_version += 1`

任何一步拋錯 → 全部回滾，`status="apply_failed"`。

### Elicitation 請求（伺服器 → client）

```json
{
  "method": "elicitation/create",
  "params": {
    "message": "Apply this replan? 2 bookings move, 0 need a slot.",
    "requestedSchema": {
      "type": "object",
      "properties": {
        "confirm": {
          "type": "boolean",
          "title": "Confirm",
          "description": "Apply these changes to the schedule."
        }
      },
      "required": ["confirm"]
    }
  }
}
```

client 回覆：`{"action": "accept", "content": {"confirm": true}}`，
或 `{"action": "decline"}`，或 `{"action": "cancel"}`。

**只有 `action=="accept"` 且 `content.confirm==true` 才算確認。** 其他一律 `not_confirmed`。
`web/` 的 elicitation callback 必須把這個請求推到瀏覽器並等使用者按鈕，**不可由 LLM 代答**。

---

## 7. Bedrock / stub 雙模式（`web/agent.py`）

本機**沒有** AWS 憑證。`agent.py` 必須：

1. `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`（或 `AWS_PROFILE`）存在，且
   `SER_LLM_MODE` 不是 `stub` → 走 Bedrock Converse API。
2. 否則走 `stub`：一份寫死的決策表，把使用者的說法對到工具呼叫序列，
   回覆文字從工具 `structuredContent` 產生。**stub 模式必須能跑完正常案例、
   追問案例、找不到案例、跨對話案例四段流程**。
3. 啟動時把實際模式印在開發者面板與 log，UI 上顯示 `LLM: bedrock` 或 `LLM: stub`。
   README 與影片旁白如實說明。

系統提示至少要含計畫 §7 的六條禁令（不自己算時段、不明確就追問、只有明確確認才 apply、
為什麼只依 `reasons` 回答、不得說 impossible、`speech` 不超過兩句）。

---

## 8. 契約驗證

`tests/test_contract.py` 會：

1. 啟動真的 MCP 伺服器，`initialize` + `tools/list`
2. 斷言協商出的 `protocolVersion == "2025-11-25"`
3. 斷言六個工具的 `inputSchema` 與 `outputSchema` 和 `contracts/tools.json` **完全相等**
4. 斷言每個工具都同時有 `inputSchema` 與 `outputSchema`（非空 `properties`）
5. 對 `contracts/examples/*.json` 逐檔呼叫對應工具，斷言實際 `structuredContent`
   與範例**深度相等**（時間與 id 以外的欄位）

跑法：`python -m pytest -q`
