# 067 · Implementation Plan

> Mission 已获批准。唯一 Owner 在 exact main `414e0384...` 的 clean worktree
> 执行 RED→GREEN；稳定 checkpoint 前不 commit/push/PR。

## Task 1 · Contract and API RED

- [x] 占用 OpenSpec067，冻结严格七路径、公开 API、数据最小化与非目标。
- [x] 写 focused RED，证明公共单臂 scorer/receipt 尚不存在。
- [x] 最小公开 DTO 与 fail-closed API 转 GREEN。

## Task 2 · Admission and non-model authority

- [x] Golden 前调用 061 real admission；block/hash/receipt/authority drift 零 Golden parse。
- [x] 只接受 candidate MinerU parser、exact Product/source/Schema/prompt/budget/
  normalizer/comparator 与 exact60 order。
- [x] semantic model id/base/hash 只进入 output/score receipt，不与 DeepSeek 常量比较。

## Task 3 · Existing deterministic scorer reuse

- [x] 复用现有 Golden parser、field comparison、metrics、rate/critical/value 和
  absolute gate rules，禁止第二份评分逻辑漂移。
- [x] 输出 exact60 correctness flags，不含 expected state/value 或 Golden reasoning。
- [x] model identity mutation只改变 receipt，不改变同一字段输出产生的 metrics。

## Task 4 · Verification and freeze

- [x] focused 067、exact four-file bounded、Ruff、strict mypy、OpenSpec strict、diff/scope/
  private/secret/UTF-8-LF。
- [x] 冻结 exact seven-path temp-index candidate；不 commit/push/PR。

## Corrective · External review closure

- [x] 移除逐字段 `normalized_value_evaluated/normalized_value_correct`，内部聚合保持不变。
- [x] admission 非 READY 立即短路；READY 后显式验证嵌套 arm DTO，畸形对象零 Golden parse。
- [x] 只回显合法 SHA256 output hash；非法 identity/field/hash 返回 typed block。
