# 053 · Validation report

## Candidate identity

- stacked base / HEAD：`67483ab7d769fc4a2c01736d638c34bf9ee0e66f`
- base tree：`1fe7692f1d8053a290b8e667799af54db8354dc4`
- dependency：Draft PR #80 / `codex/052-material-profile-template-binding`
- branch：`codex/053-parsed-document-contract`
- predecessor tree：`4e44a06a779ac6a028d6f180358072a3fcb0fdd3`
- corrective temp index：
  `/private/tmp/053-parsed-document-contract-corrective-final-20260801.index`
- state：`CORRECTIVE SUCCESSOR FROZEN / UNCOMMITTED`

## Evidence

- baseline 052 focused：`15 passed in 0.90s`
- 053 module RED：`1 failed`，原因为模块不存在；最小 module 后 `1 passed`
- 053 document/manifest focused GREEN：`6 passed in 0.57s`
- 052 + 053 non-policy focused regression：`21 passed, 1 deselected in 0.39s`
- 053 document/manifest Ruff：`PASS`
- 053 document/manifest strict mypy（2 files）：`PASS`
- 053 quality policy RED：`6 passed, 1 failed`；唯一失败为旧 052
  `MaterialProfile` 尚无 exact policy，`evaluate_parse_quality` 未实现
- 052 successor parser policy：exact commit/tree 已消费
- reviewer RED B1：`table_grid` 只有 page Evidence 且零 table/cell 时错误计为
  satisfied，断言失败；missing subject refs 先被 Pydantic raw rejection，不能进入
  typed policy decision。
- reviewer RED B2：缺失 receipt 抛 raw `AttributeError`；同 profile id 的缩窄
  required-capabilities receipt 可将不足 manifest 变为 ADMIT。
- corrective focused final：`13 passed in 0.25s`；B1 只对 052 当前 capability
  families 做 bounded structure-shape gate，B2 只接受 052 validated
  `MaterialProfileResolution`。
- C0 + 052 + 053 bounded regression：`141 passed in 2.29s`
- W1/source revision bounded regression：`112 passed in 21.87s`

## Gates

- corrective focused/static：`PASS`（Ruff 与 strict mypy 2 files）
- OpenSpec 053 strict：`PASS`（telemetry DNS noise after exit 0）
- quality focused/static：`PASS`
- diff-check / strict 7 paths / real index empty：`PASS`
- production import scope：`PASS`（零 network/DB/provider/WeKnora import）
- private-path scan：只有测试对 `/private/tmp/source.pdf` 的 negative assertion
- high-signal secret scan：`PASS`
- provider/model/live/PostgreSQL/WeKnora：`NOT RUN / OUT OF SCOPE`
- commit/push/PR：`NOT RUN / NOT AUTHORIZED`

本报告只在命令实际完成后更新。不得把 fixture 合同写成真实 parser admission、
三 PDF complete、S0-Q PASS、Golden 变更或 Release ready。
