# 018 增量设计

权威设计：`docs/insurance-kb/20-enterprise-runtime-foundation.md` §5～6。

## SnapshotFact

SnapshotFact 使用可索引列保存 product_version/predicate/effective dates，值与 Evidence 使用 JSON 冻结。`SnapshotClaim` 保留用于兼容审计，但在线 Reader 不依赖 mutable Claim/Evidence。

发布构建器在 snapshot=building 时从当前待发布 Claim 集复制 SnapshotFact，再以这些事实生成 rendered pages。状态转为 published 后，服务不提供更新方法；数据库触发器是否加入由实现阶段根据 SQLite 测试兼容性裁决，至少保证应用层不可改。

## 外部一致性

PostgreSQL 与 WeKnora HTTP 无法组成原子事务，因此定义明确的 saga：

1. DB 构建 snapshot/facts/pages 和完整 PublishPlan，提交为 building；plan 同时描述目标写集和基于 current snapshot 的补偿；
2. 标记 publishing，逐页幂等 upsert 并记录 attempt；
3. 全成功后单 DB 事务标记 published 并移动 pointer；
4. 失败则标 failed、pointer 不动；可用同一 plan retry；放弃时 reconciliation 重放 current 页面，并删除该失败 plan 触及但 current 不拥有的全部 Harness managed slug。

Publisher 只管理带 Harness page metadata 的 slug；遇到同名非 Harness 页面先报 collision。这样补偿无需保存和恢复不受 Harness 管理的任意第三方内容。

这保证 Harness/MCP 真相不前移；WeKnora 短暂半发布通过补偿恢复，不把分布式非原子性伪装成强事务。

## Reader 与回退

SnapshotReader 是稳定接口，013 只做协议包装。Reader 以 typed coverage gap 表示“无发布/无产品/无字段/日期无匹配”；raw fallback policy 只能消费这些 gap，并保留 unreviewed 标记。
