# 073 · 596-1 Exact8 Field Contracts

## Why

596-1 的下一步语义执行需要一个极窄的 exact8 字段合同边界。其中四项已有
052 来源权威且无需新业务裁决；另四项仍需用户对已冻结决策包做精确
确认。任何模型或服务不得在该确认之前代填选项。

## What Changes

- 冻结 exact8 有序字段、字段名和 052 来源权威；
- 仅将 `clause_version`、`zh_1ec5e3f2cc`、`zh_3d8424595d`、
  `zh_f32c510a5e` 标记为无需用户决策的已冻结合同；
- 将其余四项保持为 `NONE_PENDING_USER_CONFIRMATION`，且精确绑定决策包
  SHA-256；
- 增加一个仅验证外部具名用户回执的纯合同门。缺失或漂移时返回
  `BLOCKED_ON_FIELD_CONTRACT_AUTHORITY` 且 `provider_calls=0`。

## Non-goals

- 不预填决策包任何选项，不读模型答案或 Golden 值；
- 不修改全局 Schema、069、071、072、scorer、runner 或 parser；
- 不签发用户回执，不做 provider、Release、DB 或 WeKnora 操作；
- 不建通用审批平台或字段合同 registry。

## Path budget

Strictly seven paths: registry; four OpenSpec073 documents; one task-local module;
one focused test. An eighth path stops the mission.
