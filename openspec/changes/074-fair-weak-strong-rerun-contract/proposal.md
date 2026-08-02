# 074 · Fair Weak/Strong Rerun Contract

## Why

596-1 已有 069/072 的 exact Schema60 task composition、071 的弱臂 authority、
066 的 strong `UNADMITTED_RAW` comparison，以及 073 的 exact8 人工回执门。真正调用
两臂之前仍需要一个很薄的、任务本地的公平性边界，确保两次调用只差模型身份，并且
任何 Golden 内容都不能在两臂输出完成冻结之前进入流程。

## What Changes

- 消费 069/072 的同一三 PDF semantic composition 和 073 的 exact user receipt；
- 固定 DeepSeek V4 Flash → gpt-5.6-sol 顺序，各臂最多调用一次，零 retry、fallback
  或自动路由；
- 复核 exact Schema60/task plan、parser receipt、prompt、budget、normalizer 与 output
  contract 在双臂间一致；
- 用现有 `freeze_arm_output` 先冻结并校验两臂完整 60 行，再签发只表示
  `OUTPUTS_FROZEN_FOR_049_SCORING` 的 task-local receipt；
- 明确弱臂后续沿用 071 authority，强臂只能是 `UNADMITTED_RAW`。

## Non-goals

- 不调用 provider，不读取 049 Golden，不评分或自动调 prompt；
- 不重复实现 069 composer、071 scorer、073 receipt verifier 或 066 comparison；
- 不实现 provider adapter、模型路由、fallback、持久调度器或评测平台；
- 不写 DB、WeKnora、Release、Golden、migration 或公共 API。

## Dependency and path budget

This change is stacked on Draft PR #105 exact 073 head. Strictly seven paths:
registry, four OpenSpec074 documents, one task-local module, and one focused test.
An eighth path stops the mission.
