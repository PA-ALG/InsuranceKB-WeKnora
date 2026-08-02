# 066 · Implementation Plan

> Mission 已批准。实现基于 PR #96 exact head `8ee9af53...`，稳定 checkpoint
> 前不 commit/push/PR。

## T1 · Contract and RED

- [x] 冻结 provider-free、strict six-path 和 067 stacked dependency。
- [x] 写 RED：比较 API 缺失；任一 output/hash/shared identity/model identity 漂移
  必须在首次 scorer/Golden 前 fail closed。

## T2 · Frozen custody and exact parity

- [x] 同时重放两份 `FrozenArmOutputV1` hash。
- [x] 除 model id/base/hash 外，Product、三份 MinerU artifact receipt、Schema60、
  十任务 profile、prompt、normalizer、comparator、budget、parser 必须 exact equal。
- [x] 弱臂只接受 `DeepSeek V4 Flash`；强臂只接受 exact `gpt-5.6-sol`。
- [x] 强臂必须消费外部执行阶段提供的 canonical receipt，精确绑定 offline
  Codex execution surface、run/input/task/prompt/budget/model/output identity；缺失、
  placeholder、foreign 或伪 hash 在 scorer/Golden 前阻断。
- [x] 从 069 冻结模型中立的 ordered 8 semantic + 2 deterministic-rate
  Schema60 分区 preimage，并要求两臂 `arm_profile_sha256` 等于其批准 hash。

## T3 · Public scorer reuse and answer-safe delta

- [x] 两份 output 都通过 pre-Golden gate 后，分别调用 067 public scorer。
- [x] 输出 exact60 answer-safe correctness delta、聚合 delta 和 C0 receipt。
- [x] 任何 067 blocked/Golden invalid 保守返回 typed block，不复制评分逻辑。

## T4 · Verification and freeze

- [x] focused + bounded 061/067、Ruff、strict mypy、OpenSpec strict、diff/scope/
  private/secret/UTF-8-LF。
- [x] 冻结 exact six-path candidate；provider/Golden/live/PG/WeKnora/full NOT RUN。

## Stop conditions

- 067 public scorer 无法分别评分两份 FrozenArmOutput；
- 需要修改 067、068、069 或第七路径；
- 需要从输出值反推 Golden、模型 judge 或生产授权。
