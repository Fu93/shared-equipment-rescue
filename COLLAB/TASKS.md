# TASKS — 分工與狀態

## Lead（AI #1）— `mcp_server/`, `contracts/`, `tests/`, `docs/`, 根目錄 README, `web/`, `tools/`
| # | 任務 | 狀態 |
|---|---|---|
| L1 | `mcp_server/` 6 tools 實作 + elicitation | ✅ f1c10a6 |
| L2 | `contracts/tools.json` + examples 生成 | ✅ f1c10a6（moved scripts d997ba1，regen byte-stable） |
| L3 | tests: engine 10 / contract 17 / llm 10 / server 7 | ✅ 44 passed |
| L4 | 舊測試清理 | ✅ 併入 d997ba1（根目錄腳本 → tools/） |
| L5 | docs: friction-log / product-feedback / README | ✅ README 已含 web demo 說明（aac27ef） |
| L6 | 清理暫存檔 | ✅ web/ scratch 清空＋root scripts 歸檔 tools/（d997ba1） |
| L7 | Bedrock/stub 雙模式 LLM 層（§7） | ✅ llm.py（Converse＋scripted fallback，test_llm 10 綠） |
| L8 | `web/` MCP client（Partner 未接手，Lead 接管，MSG-004） | ✅ c3249ef＋ba7e2dc（E2E 20/20） |

## Partner（AI #2）— `web/`（已移交 Lead，見 OUTBOX.md MSG-004/005）
| # | 任務 | 狀態 |
|---|---|---|
| P1–P4 | 全部移交 → L5/L8 | — 移交完成 |

## 人類（僅人類可做）
| # | 任務 | 狀態 |
|---|---|---|
| H1 | Demo 影片 <3:00（腳本在 SUBMISSION_CHECKLIST §2，對映 web `_shot_1..6.png`） | ⬜ |
| H2 | Devpost 提交（Alexa+ 主賽道＋AWS Builder 勾選，連 repo＋影片） | ⬜ |

## 共享
- `COLLAB/CONTRACT-FROZEN.md` 是唯一契約來源；同步機器版 `contracts/tools.json`（regen 幂等已驗證）。
