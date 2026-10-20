# TASKS — 分工與狀態

## Lead（AI #1）— `mcp_server/`, `contracts/`, `tests/`, `docs/`, 根目錄 README, `web/`
| # | 任務 | 狀態 |
|---|---|---|
| L1 | `mcp_server/` 6 tools 實作 + elicitation | ✅ f1c10a6 |
| L2 | `contracts/tools.json` + examples 生成 | ✅ f1c10a6 |
| L3 | tests: engine 10 / contract 17 / server-live 7 | ✅ 34 passed |
| L4 | `tests/mcp_server/` 舊測試清理 | ⬜ |
| L5 | docs: friction-log / product-feedback / README | ⬜ |
| L6 | 清理 `_spike/`、`_gen_*.py`、垃圾檔 | ⬜ |
| L7 | Bedrock/stub 雙模式 LLM 層（§7） | ⬜ |
| L8 | `web/` MCP client（Partner 未接手，Lead 接管，MSG-004） | ✅ c3249ef（E2E 20/20） |

## Partner（AI #2）— `web/`（已移交 Lead，見 OUTBOX.md MSG-004）
| # | 任務 | 狀態 |
|---|---|---|
| P1 | 讀 `COLLAB/OUTBOX.md` MSG-002 接線規格 | — 移交 → L8 |
| P2 | `web/static/index.html` MCP client 化 | — 移交 → L8 |
| P3 | Demo 控制列 + 角色 tabs（§8） | — 移交 → L8 |
| P4 | 對 `contracts/examples/` 各狀態的 UI 呈現 | — 移交 → L8 |

## 共享
- `COLLAB/CONTRACT-FROZEN.md` 是唯一契約來源；同步機器版 `contracts/tools.json`。
