# 014 规格（验收条款）

## O1 任务模型与领取

- O1.1 batches / document_tasks / stage_tasks 三级表（Alembic 增量）；worker 以 `SELECT … FOR UPDATE SKIP LOCKED` 领取，多 worker 无重复领取（并发测试断言）；
- O1.2 worker 崩溃（kill -9）后其 in_progress 任务超时回收被他人接管（心跳/租约字段）；
- O1.3 batch 状态机：pending→running→(completed|partial_failed|cancelled)；取消只作用于未开始任务。

## O2 分片与一致性

- O2.1 merge/发布阶段以 `tenant+kb+product_id+product_version` 为分片键，同分片 Postgres advisory lock 串行；异分片并行（断言：同产品两文档的 merge 严格串行、不同产品并行）；
- O2.2 **延迟结果保护**：stage 完成写回时校验目标 Claim 当前 revision 未超过其读取时 revision，否则丢弃并记录 stale_result（不覆盖新版本）；
- O2.3 007 发布器接入同一 advisory lock（多实例发布竞争消除，替换 001 的进程内锁）。

## O3 限流

- O3.1 五级并发上限：全局/租户/KB/产品/模型 provider（配置化令牌桶）；provider 级断言实际并发 ≤ 上限；
- O3.2 排队原因可查询（等哪级配额）。

## O4 失败治理

- O4.1 stage 重试（复用 004 退避）→ 超限入批次死信汇总（按产品/阶段聚合）；单任务失败不阻塞批次其他任务；
- O4.2 死信重放使用原 run manifest 快照（schema/prompt/模型版本一致），重放记录关联原任务；
- O4.3 批量操作默认 dry-run（取消/重放需 --apply）。

## O5 控制台 API

- O5.1 `GET /batches`、`GET /batches/{id}`：吞吐、分片状态分布、处理中/重试/死信/pending_judge 计数、token 消耗聚合、预计剩余；数字与表数据一致（对账测试）；
- O5.2 作为 008 工作台第五页的数据源（本 change 只交付 API）。

## O6 验收

- O6.1 100 个模拟 document_task（Replay 模型）× ≥3 worker：全部终态、无重复处理、同产品串行异产品并行、kill worker 后接管、限流生效、stale_result 被拒、控制台对账一致；
- O6.2 零真实模型调用；门禁全绿。
