# 079 · Fair Experiment Executable Bridge

## Why

074 已经冻结 exact 596-1 weak/strong pair，066/071 已经提供唯一 Golden
scoring 前门，但两者之间仍缺少一条可执行的、非 test callback 的桥：
transport 必须在显式 opaque authorization 下依次提交两臂，返回内容寻址的
execution receipt，桥必须重放冻结和 receipt 后才能让调用者读取 Golden。

## What Changes

- 增加一个 task-local public transport `Protocol` 和公开两阶段 API：
  `execute_and_freeze(...)` 及 `score_frozen_experiment(...)`；
- 直接调用 074 `run_596_1_fair_rerun`，严格 weak → strong，各一次，零
  retry/fallback/route/prompt tuning；
- 验证 transport 回执对 shared composition/task plan/model/prompt/budget/
  candidate frozen output 的绑定；
- 验证 074 frozen pair 后，用现有 `freeze_arm_output` 将 weak 从 074
  `baseline` 机械重冻结为 066 要求的 `candidate`，strong 保持 074 candidate；
- transport 原样提供外部签发的 public `StrongExecutionReceiptV1`；079 从不生成
  或重建其 preimage，并在读取真实 Golden 前仅通过 public 066 comparison 校验；
- secret/authorization 只作 transport 的 opaque 参数，不进入 DTO/hash/log/result。

## Non-goals

- 不实现 provider adapter，不调用模型，不读取真实 Golden 值；
- 不修改或复制 066/071/074 DTO、hash 或 scorer；
- 不建实验、agent、workflow、router、registry 或持久化平台；
- 不增加 retry、fallback、第三模型、parser 改动或 production strong 路径；
- 不写 DB、PostgreSQL、WeKnora、Golden、Release 或 migration。

## Dependency and path budget

Exact base/HEAD is `1e04a0b2f531aed53f60ca7286217069763ba19a`. Strictly seven
paths: registry, four OpenSpec079 documents, one task-local module and one focused test.
080/081 are registered only; this change SHALL NOT create their directories.
