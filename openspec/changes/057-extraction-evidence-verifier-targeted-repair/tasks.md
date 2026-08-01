# 057 · Implementation Plan

> **For agentic workers:** Mission 已获批准。严格在隔离 worktree 内执行
> RED→GREEN；稳定 checkpoint 前不 commit/push/PR。

## Task 1 · 身份与 OpenSpec

- [x] 从已合入 053 的 main 创建 clean branch，并在 054/056 合入后
  ff-only 到 authoritative main
  `b3c4a7c661e5c7a61c82b5bc55e79ad580f928df`。
- [x] 阅读 AGENTS、ADR/Amendment、JLX/HANDOFF 及 051/052/053；只读核对
  054 candidate seam，不复制其 DTO/hash。
- [x] 占用 057，冻结七路径、stacked dependency、非目标与验收。

## Task 2 · Evidence verifier RED→GREEN

- [x] 先写 RED：exact ProductVersion/SourceRevision/attempt/document/manifest、
  page/block/table/cell 类型与父链、content/quote/value snapshot。
- [x] 先写 RED：quote 命中但主语/条件/版本不支持必须失败。
- [x] 实现最小 frozen/extra-forbid DTO 与确定性 verifier，运行 focused
  至 GREEN。

## Task 3 · 有界值规则与 tri-state

- [x] 以 RED 覆盖 numeric/unit/enum/date/range/arithmetic 表格值；不接受
  binary float 或 LLM judge。
- [x] 以 RED 证明 `unknown` 为 typed Gap，`absent_explicitly` 需要
  exact Evidence，两者不得混同。
- [x] 实现最小固定 rule families，禁止 registry/plugin/DSL 平台化。
- [x] 复现并关闭数值/单位/枚举/日期/范围 substring 旁路、range
  上下界漏检，以及无明确 marker 的伪 absence。
- [x] 以三个独立 RED 关闭正数、数值+单位、range 忽略负号的左边界
  旁路，并保留合法负数 exact atom 正例。

## Task 4 · Targeted repair 与 054 seam

- [x] 以 RED 证明 repair 只接失败字段、已批准 locator 和一次
  预算；已通过字段不可进入 repair。
- [x] 实现一次修复合并与耗尽后 typed Gap/ReviewItem。
- [x] 复现并关闭 repair initial/current identity 漂移、手工 plan
  缺项/额外项及不存在 locator 的绕行；拒绝前保持 passed snapshot 不变。
- [x] 在 054 合入后把唯一 seam RED 转为 GREEN：直接消费
  `ReceiptChainV1`/`AttemptReceiptV1`，不复制 DTO/hash 或授予 authority。

## Task 5 · 验证与冻结

- [x] 运行 057 focused、053 相关回归、Ruff、strict mypy、OpenSpec
  strict、diff/scope/private/secret/UTF-8-LF。
- [x] 冻结 exact seven-path temp-index tree，real index 保持 empty，如实报告
  054 exact DTO seam GREEN 及 NOT RUN。
- [ ] 等待独立 Spec/Quality/Delivery 复审；owner 不 commit/push/PR。
