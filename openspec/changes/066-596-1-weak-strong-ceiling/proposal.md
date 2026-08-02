# 066 · 596-1 Weak/Strong Ceiling Comparison

## 状态

`STABLE CANDIDATE / PROVIDER NOT RUN / GOLDEN NOT READ BY OWNER`

## 业务目标

在同一份已准入 MinerU artifact、Schema60 和十任务语义合同上，离线比较固定弱
模型 `DeepSeek V4 Flash` 与固定强模型 `gpt-5.6-sol` 的质量上限。比较只消费两份
已经冻结的 `FrozenArmOutputV1`，复用 067 的单臂 Golden scorer，回答“弱模型 +
Harness 与强模型天花板还差多少”，而不是让强模型成为生产 judge 或 fallback。

## 单一职责

- Golden 前同时验证两份 output hash 和共享非模型身份；
- 强制弱模型 exact identity，并要求强臂消费执行阶段外部提供、内容寻址的
  `StrongExecutionReceiptV1`；其他 artifact/Schema/task-plan/prompt/normalizer/
  budget/receipt 身份完全一致；
- 将 069 冻结的模型中立 8 个语义任务 + 2 个确定性费率任务、Schema60 字段
  分区固化为 066 的 approved task-plan preimage；两臂共同改成任意相同 hash
  仍 fail closed；
- 分别调用 067 的 `score_admitted_frozen_arm`；
- 输出不含 Golden 答案的逐字段 correctness delta、聚合 delta 和 C0 receipt。

## 非目标

- 不调用 provider、模型、Golden loader、数据库、PostgreSQL、WeKnora 或 live；
- 不让 GPT 充当 judge、fallback、自动 repair、生产模型、Release 或 Active Head
  authority；
- 不修改 067 scorer、068/069、Golden、parser、Schema 或任务计划；
- 不建立通用 benchmark、榜单、模型 registry、路由器或评测平台。

## 路径预算

严格六路径：本 change 的 proposal/tasks/validation/spec 四件、一个 task-local
模块和一个 focused test。README 已由 067 登记 066，本 change 不修改 README。
