# 056 · Native pdfplumber adapter tasks

## Task 1: Stage 0 规格与身份

- [x] 从 authoritative main `711372b26f6e0a32b646f461b329b9bd53b4b302`
  建立 clean 独立 worktree/branch。
- [x] 先 ff-only stack 到 053 PR head，再在 053 合入后 ff-only 更新到 authoritative
  main `16ae691d7c4c1edfc4857b55b50d3c18c97e7f9b`。
- [x] 只读核验 051、052 与 053 frozen candidate tree
  `4e44a06a779ac6a028d6f180358072a3fcb0fdd3`，不复制其 DTO/hash。
- [x] 冻结七路径预算、显式 unsupported 与 053 阶段门。

## Task 2: RED before pure facts GREEN

- [x] 先写 fixture/focused RED，证明模块缺失并记录真实失败。
- [x] 最小实现 exact-bytes native facts：page/bbox/word/table/cell/row/column。
- [x] 证明原文、secret、绝对路径与未知 vendor key 不进入输出；空 cell 不生成
  推断 cell/span。
- [x] 已证明 source SHA 漂移、无效 bbox 与不规则 table typed fail closed；页序由
  本模块按 current PDF page order 构造，不接 caller page number。

## Task 3: 053 dependency RED

- [x] 保留正式 `ParsedDocumentV1` adapter RED，且失败原因只能是 053 production
  contract 尚未进入本 branch。
- [x] 收到总控给出的 053 exact commit 后，ff-only stack；未整文件复制 053。
- [x] 使用 053 原生 DTO/builder/evaluator 完成唯一 bridge；缺 required capability
  交给 053 `ESCALATE/BLOCK + ReviewItem`，不调用 fallback parser。
- [x] 以 RED 固定 merged ambiguity：含空槽的 native table 不桥接任何不可证明
  cell/span，完整 grid 仍桥接原生 `1×1` cells；`table_grid` 缺口交 053 质量门。

## Task 4: Stage 0 gates

- [x] focused pure facts、B1/B2、merged ambiguity corrective 与正式 bridge GREEN；
- [x] Ruff、strict mypy、OpenSpec strict、diff-check、exact scope、
  private/secret 已通过；
- [x] 冻结 stacked successor temp-index candidate，交 delta-only review；
- [ ] 不 commit/push/PR，不运行 Golden/LLM/provider/live/DB/WeKnora/full。
