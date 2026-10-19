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
