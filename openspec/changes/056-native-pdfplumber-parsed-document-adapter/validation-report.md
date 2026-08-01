# 056 Validation Report

## 当前状态

`STACKED GREEN / FROZEN FOR DELTA-ONLY REVIEW`

## 身份

- initial base: `711372b26f6e0a32b646f461b329b9bd53b4b302`；
- first stacked base: `74f741027b7225426ab76e3580a517bbe4197f0c`；
- current authoritative base/HEAD:
  `16ae691d7c4c1edfc4857b55b50d3c18c97e7f9b`；
- 053 reviewed candidate tree:
  `4e44a06a779ac6a028d6f180358072a3fcb0fdd3`，现由 stacked commit 提供；
- 053 Stage0 evidence artifact SHA-256:
  `2ec124ac759f6d1eda714c49460466f3b0dbdf91e77d779266ac58bdce7501a6`；
- 056 未读取或复制未提交的 053 working tree。

## RED → bounded GREEN

- initial focused RED：collection 失败，`ImportError: cannot import name
  'native_pdfplumber'`；证明 056 能力不存在，不是 fixture 假失败；
- B1/B2 corrective 后、stack 前，pure-facts focused：
  `7 passed, 1 deselected`；
- 原生事实已覆盖 exact bytes/source SHA、page/word/table/cell bbox、row/column、
  空 cell 不猜 span、原文/合成 secret/绝对路径/未知 vendor key 不输出；
- B1 RED 证明非零 native `Page.bbox=(10,20,110,220)` 曾被归零；GREEN 直接保留
  exact `Page.bbox`，不再用 width/height 重造；
- B2 RED 证明 word 曾被错误铸成 `block_locators` Evidence；GREEN 只保留
  `word_locators`，并将 `block_locators` 明确列为 unsupported；
- merged ambiguity RED：含 empty slot 的 native table 仍输出了硬编码 `1×1`
  cell，`2 failed`；GREEN 保留 table identity/shape，只桥接完整 grid 的原生
  `1×1` cells，并将文档级 `table_grid` 保守标为 unsupported，定向 `2 passed`；
- `merged_cells`、`header_hierarchy`、`cross_page_sections`、
  `cross_page_tables` 保持 explicit unsupported；
- formal bridge RED：3 个用例因缺少 `build_parsed_document_v1` 失败；GREEN：
  `3 passed, 7 deselected`，caller 身份漂移 fail closed，缺 block capability 由
  053 quality gate 返回 `ESCALATE` 或 `BLOCK + ReviewItem`；
- 完整 056 focused：`12 passed`；052/053/056 聚合回归：`54 passed`。

## Static / OpenSpec

- Ruff（source + focused test）：PASS；
- strict mypy（source + focused test）：PASS；
- `openspec validate 056-native-pdfplumber-parsed-document-adapter --strict`：PASS；
- final successor temp-index identity 在文档冻结后生成并随 review handoff 报告；
- exact scope 为八路径（七个 056 功能/规格路径 + README 053 状态机械同步），
  all `100644`；
- diff-check、exact scope、private/secret scan：PASS；
- real Git index：empty。

## NOT RUN / BLOCKED

- Golden、LLM/provider、live、DB/PostgreSQL、WeKnora、full：`NOT RUN`；
- 未执行 parser fallback；缺 required capability 不被冒充为 `ADMIT`。

## 诚实交付边界

056 只完成 native/pdfplumber 的 task-local adapter 与 053 quality-gate bridge；它不
选择升级 parser、不声明 596-1 三 PDF production admission，也不构成通用 adapter
平台。
