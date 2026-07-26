# 039 · P3 API/Worker 壳

> 状态：📋 规格起草（spec-only；worktree `ikb-p3`）。实现窗口按 035
> tasks 的冻结口径等待 P1 实现合入 main 后开工，「P3 及后续消费方 PR
> 不得提前开工接线」。评审分级按 23 号控制板 §8 D-2026-07-26-2：P3 =
> 单独立评审 + 自动门禁。
>
> 权威设计源：
> `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
> §5（最小生产拓扑：API 与 Worker 同 wheel 不同进程角色）、§6.2（并发
> 模型）、§12（任务运行时，P3 作为消费方）、§13（权限与安全：五个领域
> 角色与 `source_reader`/`wiki_projector` service principals）、§16 P3
> 行、§16.2（principal、领域角色和 scoped service principals 归 P3）、
> §18（Contract Card），以及修正案
> `2026-07-27-enterprise-llm-wiki-knowledge-compilation-amendment.md`
> §7 关键路径（`P1 → P3 → P2d、P5a0+、P5a2 → P5b0`）。本 change 不复制、
> 不修改、不重新解释该设计；语义冲突时以 033/修正案为准。

## 为什么做

033 §16 DAG 把 P3 放在 P1 之后的扇出点：P2a/P2c/P2d、P5a0/P5a1、P4a 与
P11 都直接依赖 P3 的进程壳与 principal 合同（§16 DAG、§16.2）。没有 P3，
每个后续消费方 PR 都要自行发明进程启动、健康申报、停机和身份语义——
恰是 033 要终结的补丁循环。P1 已冻结任务存储合同（OpenSpec 035，规格
已合入），但没有任何进程消费它；P3 交付第一个真实消费者（Worker 主循环）
与第一个生产 HTTP 面（探针 + 观测），同时把「principal、领域角色和
scoped service principals」这一 §16.2 明文归属 P3 的所有权落为可测试
合同。

## 本 Change 做什么

按 033 §16 P3 行的单一职责——「同 wheel 两角色、健康检查、配置和优雅
停止」——冻结以下合同并交付其实现规格（见 `specs/service-shell/spec.md`）：

- 同一 wheel 两个 console 入口 `wiki-api`/`wiki-worker`，共享配置加载与
  领域代码；API 不运行 claim 循环，Worker 只暴露探针不持用户会话；多副本
  并发启动零副本间协调（只依赖 PostgreSQL，033 §6.2）；
- typed principal 模型：人类角色封闭枚举
  `viewer | editor | reviewer | space_admin | super_admin` + 服务
  principal 封闭枚举 `source_reader | wiki_projector`；唯一铸造/校验
  入口 fail closed（无匿名默认、未知角色拒绝）；不信任 caller 自报
  `space_id`/`user_id`，scope 只从认证绑定推导；
- scoped service principals：封闭能力集（source_reader 只读 Source 面、
  wiki_projector 只投影 managed-page conditional 面），不可持有
  superadmin 或人类角色能力；MVP 绑定来自配置/静态 provider，零持久表；
- liveness 与 readiness 严格分离：liveness 无外部依赖；readiness =
  真实 DB 连通 + Alembic migration head 相等检查，检查失败/超时/未完成
  首检一律 not ready（readiness 不撒谎）；
- 优雅停止：信号后立即 not ready、API drain 在飞请求；Worker 零新
  claim、在飞任务 deadline 内完成则正常提交、超时任务停 heartbeat 交由
  P1 lease 过期 + 更高 generation 接管（P1.10），全程恰好一份领域结果；
- 配置合同：单一 `WIKI_` 前缀 typed 配置，必填缺失启动即拒（列出缺失
  键）；全部运行数值来自配置（heartbeat 间隔必须严格小于 lease 有效期，
  启动校验）；secret 不进日志/repr/错误/响应；
- Worker 主循环 = P1 store claim/heartbeat/typed 完成的唯一消费路径；
  本地在飞并发来自配置；空 handler registry（业务 handler 归 P4a+），
  未注册 job_type 记 typed `retryable`（`unknown_job_type`）不伪装成功；
  空队列按配置间隔轮询、瞬时错误有界退避不退出；
- API 请求生命周期纯净：请求内零 durable background task，durable 工作
  只能经 P1 enqueue 事务表达；
- 只读观测端点映射 P1.9 指标查询：per-Space 指标要求该 Space
  `space_admin`（或 `super_admin`），全局聚合为显式独立端点仅限
  `super_admin`，其余 fail closed 零数据；
- 零 Alembic 迁移、零表变更。

## 不做什么（非目标）

以下明确不属于 P3，出现在计划或 diff 中即 scope 违规（依据 033 §16 P3
「不包含」列与 §16.2 所有权）：

- 任何业务 handler（Source Inbox/Capture/抽取/编译/发布归
  P4a/P4c/P5b1/P6a/P8）；P3 的 handler registry 交付为空；
- 任何 WeKnora 调用——`source_reader`/`wiki_projector` 的真实 WeKnora
  客户端与调用路径归 P4a/P4c/P12；P3 只冻结身份/scope 模型；
- WeKnora 身份联邦、ACL digest 对账与 KnowledgeSpaceBinding admission
  （P2d；P11/P13 消费）；
- principal 持久化表或任何迁移——身份 MVP 用配置/静态 provider，
  binding/ACL 状态所有权在 P2d（033 §16.2）；
- 业务查询/页面/MCP（P9a/P9b/P13）、Proposal（P10）、审核与策略求值
  （P7）；
- P1 语义的复制或修改：状态机、claim、fencing、限额、Outbox dispatcher
  全部归 P1；P3 只调用其存储层 API；受治理的终态 replay 同样维持 P1
  非目标；
- metrics 平台、第二存储、后台聚合、tracing/dashboard 建设；
- 限流、token/成本预算（CAP0/P4b）；TLS/ingress/部署编排与 HA 演练
  （P15）；
- 动态 worker 拓扑、通用 DAG/DSL（033 §12「近期不实现」）。

## 影响面

- 本阶段（spec-only）只新增 `openspec/changes/039-p3-api-worker-shell/`
  并在 `openspec/changes/README.md` 注册表占号：039 = p3-api-worker-shell；
  038 = g0a-annotation-subsystem（G0a 规格在 sibling PR #42 draft 起草，
  按 035 先例一并登记避免注册表合并冲突）。不修改 033/修正案的任何文件，
  不写功能代码、迁移或测试。
- 实现 PR 的文件域：harness 新 `service_shell` 包（config、principal、
  health、lifecycle/drain、worker loop、API app + 观测端点、cli 入口）+
  `pyproject.toml` 的 `[project.scripts]` 两个入口 + tests；复用既有
  fastapi/uvicorn 依赖，不新增运行时依赖；零迁移；不触碰 WeKnora fork、
  frontend、遗留领域包（`db.base/scope` 按 24 号处置清单复用）。
- 观测端点只读消费 P1.9 查询；per-Space/全局并发上限、backoff、
  max_attempts 等语义不变，仍由 P1 store 唯一强制。

## 依赖与后续

- 依赖：P1（OpenSpec 035）。P1 规格已合入（PR #38）；其实现在
  `ikb-p1-impl` worktree 进行中（迁移占号 0015）。P3 实现的 store 接线
  与 `integration_postgres` 验收必须等待 P1 实现合入 main；本规格只
  引用 035 冻结的存储层合同，不假设其实现细节。
- 后续：按 033 §16 DAG 与修正案 §7，P2a（C0+P3+CAP0）、P2c/P2d（C0+P3）、
  P5a0/P5a1（P3）、P4a（P2d+P3+SourceLifecycleContract）在 P3 之后解锁；
  P11 依赖 P3 principal 与 P2d binding/ACL 合同（§16.2）。业务 handler
  由各消费方 PR 经 registry 显式注册；readiness 的 migration head 期望值
  随各消费方迁移自然演进，不需 P3 改动。
