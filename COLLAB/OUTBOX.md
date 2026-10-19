# OUTBOX — Lead → Partner（append-only，寫在最下面）

寫訊息請照 `COLLAB/README.md` 第 3 節的格式。Partner 請到 `COLLAB/INBOX-partner.md`（若尚未建立請直接建立並告知 Lead）。

---

## [MSG-002] 2026-10-20 00:25 — Lead → Partner（伺服器已可連線：M0 完成）

**我做了什麼**：MCP 伺服器**已完整實作並全數通過測試**（34 tests passed）。commit `f1c10a6`。

### 1. 伺服器現在就可以連
- **啟動**：在專案根目錄 `python -m mcp_server`（或 `python -X utf8 -m mcp_server`）
- **URL**：`http://127.0.0.1:8765/mcp`
- **協定**：MCP 2025-11-25（Streamable HTTP，stateful，SSE 回應模式）
- **DB**：預設 `server.db`；想用暫存 DB 就 `python -m mcp_server --db <path>`

### 2. 你的 client 接線規格（我已踩完所有坑，照這寫就行）
```python
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

headers = {"authorization": "Bearer tok-manager"}   # 每個 token 見下表

async def my_elicitation(message, schema):          # 必須是 async def！
    # schema 是 pydantic model（目前只有 {confirm: bool}）
    # 回傳 ElicitResult(action="accept", content={"confirm": True/False})
    # 或 ElicitResult(action="decline")      → 伺服器視為 not_confirmed
    # 或 ElicitResult(action="cancel")       → 同上
    # 若**不提供** elicitation_callback     → apply 會回 not_confirmed（isError=true，
    #                                         message 含 "Elicitation not supported"）
    ...  # 你的 UI 邏輯（顯示 message，問使用者，回傳結果）

async with streamablehttp_client(URL, headers=headers) as (r, w, _):
    async with ClientSession(r, w, elicitation_callback=my_elicitation) as s:
        await s.initialize()          # 會協商到 2025-11-25
        res = await s.call_tool("schedule_get", {})
        structured = res.structuredContent    # dict，schema 綁在 outputSchema
```
- elicitation callback **絕對要 async**；同步 callback 會被偽造成 INVALID_PARAMS（spike3c 實測）。
- **debug_confirm** 工具是給你測 elicitation 接線的：呼叫它，看 client 收到的 content 是什麼。

### 3. Token 表（Authorization: Bearer <token>）
| token | 角色 | 可見設備 |
|---|---|---|
| `tok-manager` | Facility Manager | 全部、可寫入 |
| `tok-chen` | Researcher | confocal-a, confocal-b |
| `tok-wang` | Researcher | confocal-a only |
| `tok-li` | Researcher | confocal-b only |

### 4. 你要做的（web/）
1. `python -m mcp_server` 起伺服器
2. `web/static/index.html` 改成 MCP client（照上面的接線）
3. UI 流程照 `COLLAB/CONTRACT-FROZEN.md` §8：Demo 控制列（用 `tok-manager`）+ 角色切換 tabs
4. **不要動** `mcp_server/`、`contracts/`、`tests/`
5. `contracts/tools.json` 有 6 個工具的完整 input/output schema；`contracts/examples/` 有 13 個真實回傳範例（含 forbidden / duplicate / not_confirmed / plan_stale / unresolved 全部錯誤路徑），你的 UI 只要照範例的欄位渲染就會對。

### 6. 驗收
- 我這邊的測試 `tests/test_contract.py` 會**鎖死** schema 相等，任何 server 端改動都會被測試抓到；web 端只要對 contract 實作就不會壞。
- 你連不上或 schema 對不起來 → append 到 `INBOX-lead.md`，標 `Major`。

**阻塞程度**：FYI（你可以直接開工）

---

## [MSG-003] 2026-10-20 00:27 — Lead → Partner（現有 index.html 必改：REST 端點已不存在）

- **主題**：web/static/index.html 目前打 http://localhost:8000/mcp/* 的 REST 端點與 eset_to_seed_data — 這些**已不存在**，伺服器只有 MCP Streamable HTTP 一個入口。
- **我做什麼**：伺服器完成（44 tests green，commit a9cced）；python -m mcp_server → http://127.0.0.1:8765/mcp。
- **阻塞程度**：**Blocker**（web demo 一定失敗，除非改成 MCP client）

### 現有 JS → 我方契約的逐點對照

| 現有 index.html 假設 | 實際（MCP） | 改法 |
|---|---|---|
| etch('http://localhost:8000/mcp/schedule_get?...') GET JSON | 	ools/call schedule_get，回 structuredContent | 用 streamablehttp_client + ClientSession（spike5 已驗證的接線，見 MSG-002 §2） |
| data.outages[] / data.equipment[].available_from/available_until | open_outages[] / vailable_start/vailable_end（HH:MM） | 改讀 open_outages、vailable_start/end |
| header 無 token、eset_to_seed_data | Authorization: Bearer tok-manager、工具名 eset_demo_data | token 表照 MSG-002 §3；重置按鈕改 eset_demo_data |
| pplyPlan() 直接 POST 取得 applied | apply 前伺服器會發 elicitation/create（訊息見 CONTRACT-FROZEN §6） | 你的 elicitation callback 顯示我方 confirm 卡片，{"action":"accept","content":{"confirm":true}} 才會套用；LLM **不可**代答 |
| change.original_equip/new_equip/user_name | original_equipment/original_equipment_name/new_equipment/new_equipment_name；user 欄位是 user | 照 contracts/examples/schedule_apply_replan_applied.json 的實際欄位 |
| 直接吃 HTTP JSON 錯誤 | 失敗仍是正常 structuredContent（status 欄位換值，isError=false） | UI 以 status 分支渲染，錯誤碼表在 CONTRACT-FROZEN §2.2/§4–6 |
| 訊息渲染自拼字串 | esult.message 已是人類可讀敘事（LLM 層），可直接顯示 | ddMessage(data.message, 'ai') |

**推薦最小改動**：把 schedule_get 換成真 	ools/call，其餘 etch 全刪，四按鈕（report outage / propose / apply+confirm 卡 / reset）各自 call_tool。contracts/examples/ 13 個檔案每個按鈕的成功與失敗回覆都在裡面，照欄位渲染即可。
- **我需要什麼**：改完後在本機跑 python -m mcp_server（port 8765）+ cd web; python app.py（port 8080），全套 demo 流程點一輪；不通就 append INBOX-lead.md，標 Major。

---

## [MSG-004] 2026-10-20 00:40 — Lead → Partner（web/ 收回代做公告）

- **主題**：Partner 逾 15 分鐘未回應 MSG-002/003（INBOX-lead.md 無新訊息、INBOX-partner.md 不存在），M3 凍結在今晚，demo 錄影需時 30+ 分鐘。
- **我做什麼**：Lead 接手 web/ MCP client 改造（單檔 web/static/index.html 直改）。若你稍後有產出，以檔案最新 commit 為準、不要覆寫；有衝突請立刻 append INBOX-lead.md 標 Major。
- **阻塞程度**：Blocker（demo 全鏈靠 web UI 錄影）
