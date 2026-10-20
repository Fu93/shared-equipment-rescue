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

## Lead（全案接手 — Partner 退出，2026-10-20 人類指示；採 Phase 1→2→3 順序，凍結線 20:00 前完成）
| # | 任務 | 狀態 |
|---|---|---|
| P1–P4 | web MCP client 首版 | — 移交完成（Lead 先做了 L8 首版） |
| T-A1 | Phase 1 後端：錯誤處理/日誌/性能/單元測試（禁改引擎行為+reply 措辭） | ⬜ |
| T-B1 | Phase 2 前端：UX/動畫/響應式/視覺回饋（禁改斷言錨點文字） | ⬜ |
| T-C1 | Phase 3 核心：重排算法/拒絕理由/持久化驗證（若改 reply body → 必須 regen contracts+examples 並跑全套） | ⬜ |

## 回歸閘門（Partner 每個 Phase 提交前必跑，全綠才准 commit）
1. `python -X utf8 -m pytest tests/ -q` → 44 passed
2. `python -X utf8 tools/final_e2e.py` → ALL PASS (19)
3. `git status` → contracts/examples 無非預期 diff（regen 例外：E2E 文字變更時需同步 regen）

## 人類（僅人類可做）
| # | 任務 | 狀態 |
|---|---|---|
| H1 | Demo 影片 <3:00（腳本在 SUBMISSION_CHECKLIST §2，對映 web `_shot_1..6.png`） | ⬜ |
| H2 | Devpost 提交（Alexa+ 主賽道＋AWS Builder 勾選，連 repo＋影片） | ⬜ |

## 共享
- `COLLAB/CONTRACT-FROZEN.md` 是唯一契約來源；同步機器版 `contracts/tools.json`（regen 幂等已驗證）。
