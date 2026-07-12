# 014 · 批量并发调度与批次控制台（master plan P0.5 / S4）

> 状态：提案（2026-07-12）。实现交其他模型（遗留 B16）。设计权威：master plan P0.5（原则全部保留，落点从 Go/asynq 移到 Harness——02 §6 映射）、04 §限流分片、08 选型（起步 Postgres SKIP LOCKED，上量 arq/Redis）。

## 为什么做

当前管道单产品串行（004 的 run 粒度）。业务方需求⑦是"成百上千文档同时上传的高效加工 + 冲突/合并处理"；千份规模下需要分片并发、限流、失败隔离与可观测。

## 做什么

1. **任务模型**：batch → document_task → stage_task 三级（Postgres 表，`SELECT … FOR UPDATE SKIP LOCKED` 领取；worker = `python -m insurance_harness.worker`，可横向多进程）；
2. **流程固定**（master plan P0.5-1 原文保留）：并行解析等待/抽取 → **按 `tenant+KB+product_id+product_version` 分片 merge**（同分片串行化：Postgres advisory lock——同时解决 007 多实例发布的 slug 竞争，14 §6 风险 2）→ ChangeSet → 批次 finalize；
3. **五级限流**：全局/租户/KB/产品/模型 provider 并发上限（令牌桶，配置化）；排队原因可查询；
4. **失败治理**：stage 级重试（复用 004 退避）+ 批次级死信汇总 + 取消未开始任务 + 重放用原 schema/prompt/模型快照（run manifest 已有）；
5. **批次控制台 API**（008 工作台加第五页的数据源）：吞吐、分片状态、处理中/重试/死信计数、pending_judge、预估成本（token 计数聚合）；
6. **延迟结果保护**：慢 worker 完成时目标 Claim 已被新版本更新 → 重新比较不得覆盖（乐观校验，master plan P0.5-1 原文）。

## 验收

夹具级：100 个模拟 document_task（Replay 模型）多 worker 并发——同产品串行/异产品并行断言、单任务失败不阻塞批次、kill 一个 worker 任务被他人接管（SKIP LOCKED 语义）、限流生效（provider 并发不超限）、控制台 API 数字与实际一致、延迟覆盖被拒。零真实模型调用；门禁全绿。

## 不做什么

Redis/arq 升级（接口抽象预留，量级触发再换）、K8s 弹性（部署侧后续）、跨机分布式追踪（Langfuse 关联已够用）。
