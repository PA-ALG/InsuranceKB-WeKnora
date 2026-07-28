# 039 任务（P3 API/Worker 壳；小 PR；先冻结 Contract Card 再写代码）

## Contract Card

### 单一职责与非目标

单一领域不变量：**同一 wheel 的 API/Worker 两角色在多副本下的身份、
就绪、配置与停机全部 fail closed——principal 不被 caller 放大、readiness
不撒谎、shutdown 不静默丢失在飞 lease、必填配置缺失不启动**。P3 只拥有
`service_shell` 进程壳（入口、配置、principal 模型、探针、drain、Worker
主循环骨架、观测端点），零表、零迁移。非目标（proposal「不做什么」全文
有效）：业务 handler、WeKnora 调用、身份联邦/ACL 对账（P2d/P11/P13）、
P1 语义复制、metrics 平台、限流/预算（CAP0/P4b）、TLS/部署编排（P15）、
动态拓扑与通用 DAG/DSL。存量资产（24 号处置清单）：`db` 包 `base/scope`
按「复用」行继续作 DB 层；`workbench` 的 FastAPI auth 模式仅作冻结审计
参考，不复用代码路径；不新增对冻结审计包的 import。

### 读写权威、事务边界与幂等键

- P3 无自有表；唯一 DB 写路径 = 调用 P1 JobStore 存储层 API（Worker：
  claim/heartbeat/typed 完成；API：enqueue——本 change 内无调用方，仅
  纯净性合同）；绝不直接读写 `wiki_jobs`/`wiki_outbox_events` 行。
- readiness 检查 = 只读（连通性查询 + Alembic revision 读取），零写。
- 观测端点 = 只读映射 P1.9 指标查询，遵守 P1.8 Space scope。
- principal 铸造/校验、能力检查各有唯一入口；配置在启动时一次性加载
  校验，运行中只读。
- 幂等语义全部继承 P1：claim 单领取 = P1.2，完成至多一次 = P1.5/P1.3，
  被放弃任务收敛 = P1.10。P3 不铸造新幂等键。

### 状态机

进程生命周期（两角色同构）：

```text
starting → serving → draining → terminated
    └→ refused（必填配置缺失/非法、配置交叉校验失败：非零码拒绝启动）
```

- readiness 是探针输出不是状态：`starting` 恒 not ready；`serving` 由
  真实 DB + migration head 检查决定；`draining` 恒 not ready。
- `serving → draining` 由 SIGTERM/SIGINT 触发；`draining → terminated`
  受配置 deadline 有界；重复信号立即 terminated。
- Worker 内任务状态机唯一归 P1（八状态封闭枚举）；P3 只调用其 typed
  转换，不新增状态、不本地缓存状态。

### 威胁矩阵

| 威胁 | P3 冻结的处理 |
|---|---|
| principal 权限混淆（服务↔人类、caller 自报 space_id/user_id、未知角色） | 封闭枚举 + 唯一铸造入口 fail closed；服务 principal 类型上不可持有人类角色/superadmin 能力；scope 只从认证绑定推导，自报标识零权限效果 |
| shutdown 丢失 lease/双结果 | 信号后零新 claim；deadline 内完成正常提交；超时任务停 heartbeat 交 P1 过期回收 + 更高 generation 接管；shell 无第二提交路径，恰好一份领域结果（P1.5/P1.10） |
| readiness 对 migration 状态撒谎 | readiness = 真实 DB 连通 + Alembic head 相等；mismatch/超时/首检未过/draining 一律 not ready；无硬编码 ready、缓存受配置新鲜度窗口约束 |
| 配置注入/密钥泄漏 | 单一 `WIKI_` 前缀 typed 模型；必填缺失非零码拒启动；secret 脱敏于 repr/日志/错误/响应；数值全部来自配置并做交叉校验（heartbeat < lease） |
| 多副本重复消费/迟到写 | 不做进程内协调，正确性全部押 P1：SKIP LOCKED 单领取 + generation fencing；P3 验收只断言「经 P1 合同收敛」 |
| API 请求内偷跑 durable 工作 | 请求生命周期零 durable background task；durable 工作只能经 P1 enqueue 事务表达；claim/heartbeat/完成调用面只存在于 Worker 角色 |
| 跨 Space 指标泄漏 | 观测端点按 P3.2 绑定授权：per-Space 需该 Space `space_admin`，全局聚合独立端点仅 `super_admin`，其余 typed 拒绝零数据；响应只含聚合值 |
| 未注册 job_type 静默丢失 | 记 typed `retryable`（`unknown_job_type`）经 P1 按 `max_attempts` 路由；不伪装成功、不丢弃、不停留 running |

### exact 验收测试清单

1. principal 模型：角色/服务枚举封闭；铸造入口对缺失/未知/非法凭据与
   未知角色名 fail closed；无匿名默认 principal（unit）；
2. caller 自报 `space_id`/`user_id` 零权限效果；scope 只从绑定推导；
   绑定外 Space typed 拒绝（unit）；
3. 服务 principal：能力集封闭、跨能力/人类角色/superadmin 构造与调用
   全部 typed 拒绝（unit）；
4. 配置：`WIKI_` 前缀；缺必填非零码拒启动并列出全部缺失键；secret 不进
   repr/日志/错误；两组配置值行为差异断言；heartbeat ≥ lease 组合拒启动
   （unit）；
5. liveness 无外部依赖：DB 不可达时 liveness 通过、readiness not ready
   且带 typed 原因（unit + fake DB 故障）；
6. readiness migration head：head 相等 ready；落后/超前/multi-head/不可
   读 not ready（`migration_head_mismatch`）；首检未过不 ready；draining
   立即 not ready（integration_postgres）；
7. 两入口一 wheel：console scripts 存在且角色互斥（API 无 claim 循环，
   Worker 仅探针面）；≥2+2 副本对同一 PG 并发启动全部 ready
   （integration_postgres）；
8. Worker 主循环：注册测试 handler 后多副本消费，每任务每 generation
   单领取、typed 完成、恰好一份领域结果（依赖 P1 实现；
   integration_postgres）；
9. 未注册 job_type → typed `retryable`（`unknown_job_type`）按
   `max_attempts` 路由，不伪装成功；主循环继续消费
   （integration_postgres）；
10. 本地并发两组配置值生效；空队列退到配置轮询间隔无忙轮询；瞬时 DB
    错误有界退避后恢复、进程不退出（integration_postgres）；
11. 优雅停止：SIGTERM 后零新 claim；deadline 内任务正常提交一份结果；
    超时任务停 heartbeat → P1 过期回收 → 存活实例以更高 generation 接管；
    总退出时间有界；API drain 在飞请求、readiness 即时摘除
    （integration_postgres）；
12. API 纯净性：请求返回后无遗留领域后台任务；API 角色对 store 的调用面
    仅 enqueue + 只读指标（unit/静态断言）；
13. 观测端点：space_admin 读本 Space 与预置分布精确一致；
    viewer/editor/reviewer/服务 principal/未认证/跨 Space 全部 typed
    拒绝零数据；全局聚合仅 super_admin；响应无负载无 secret
    （integration_postgres）；
14. 零迁移守卫：diff 无迁移文件；`alembic heads` 与表集合合入前后不变
    （unit + review checklist）。

`integration_postgres` 项在 PostgreSQL 16 lane 执行（JUnit `skipped=0`）；
默认 deterministic lane 如实记 NOT RUN。P3 不属于 033 §16.2 强制 PG 并发
测试清单，但 6–11/13 依赖真实 PG + P1 实现，故仍走该 lane；P1 实现未合入
main 前 P3 实现不得开工接线（035 tasks 冻结口径）。

### 路径预算

- logical files ≤ 12：生产约 7（`service_shell/` 的 config、principal、
  health、lifecycle、worker_loop、api_app + 观测、cli 入口）+ tests 约 5；
- 生产代码目标 400–600 行；超过约 900 行触发重新切分评审（033 §16.2）；
  单文件 400/700（测试 500/800）行仅作警报线；
- 零 Alembic 迁移、零表；`pyproject.toml` 仅新增 `[project.scripts]` 两
  入口，不新增运行时依赖。

## Tasks

严格 TDD：每个任务先落 RED 再实现 GREEN；开工后 15 分钟内必须落下 T1 的
首个 RED，30 分钟内有可核验产物。前置：P1 实现已合入 main（T5 起硬依赖；
T1–T4 可在 P1 合入前以纯 unit 先行，但不得提前接线 store）。

- [x] T1 RED（≤15 分钟）：纯单元测试冻结 principal 模型——人类角色与
  服务 principal 封闭枚举、唯一铸造入口对缺失/未知/非法凭据与未知角色名
  fail closed、无匿名默认、caller 自报 space_id/user_id 零权限效果、
  服务 principal 不可持有人类角色/superadmin、能力集跨界拒绝。
  GREEN：`service_shell` principal 模块（配置/静态 provider 接口化）。
- [x] T2 RED：配置合同——`WIKI_` 前缀、缺必填非零码拒启动并列出缺失键、
  secret 脱敏于 repr/日志/错误、两组配置值行为差异、heartbeat ≥ lease
  交叉校验拒启动。GREEN：typed settings 模块。
- [x] T3 RED：探针语义——liveness 无外部依赖（DB 故障不影响）、readiness
  的 DB 连通 + migration head 相等检查、mismatch/超时/首检未过/draining
  一律 not ready 且带 typed 原因、探针响应无 secret。GREEN：health 模块
  （head 期望值从 wheel 内 Alembic 配置读取）。
- [x] T4 RED：两入口一 wheel——console scripts 存在、角色互斥（API 无
  claim 面、Worker 仅探针面）、app factory 可多实例构造。GREEN：cli 入口
  + `[project.scripts]` + API app factory（仅探针 + 观测路由骨架）。
- [x] T5 RED（integration_postgres；需 P1 实现已合入）：Worker 主循环——
  注册测试 handler 后 ≥2 副本消费恰好单领取单结果；未注册 job_type 记
  typed `retryable`（`unknown_job_type`）按 `max_attempts` 路由不伪装
  成功；本地并发两组配置值生效；空队列退配置轮询间隔；瞬时 DB 错误有界
  退避不退出。GREEN：worker_loop（claim → dispatch → heartbeat → typed
  完成；空 registry + 显式注册扩展点）。
- [x] T6 RED（integration_postgres）：优雅停止——SIGTERM 后零新 claim、
  deadline 内完成正常提交、超时任务停 heartbeat 由第二实例以更高
  generation 接管收敛、readiness 即时 not ready、总退出有界、重复信号
  立即退出。GREEN：lifecycle/drain 模块（API 与 Worker 共用）。
- [x] T7 RED：API 纯净性与观测端点——请求返回后无遗留领域后台任务；
  观测端点授权矩阵（space_admin 本 Space、super_admin 全局、其余含服务
  principal/跨 Space typed 拒绝零数据）；响应与 P1.9 预置分布精确一致且
  无负载无 secret。GREEN：观测端点 + 纯净性守卫。
- [ ] T8 收尾：focused → Ruff/mypy → `openspec validate
  039-p3-api-worker-shell --strict` → PostgreSQL 16 lane 全量
  `integration_postgres`（JUnit `skipped=0`）；零迁移守卫（diff 无迁移、
  `alembic heads` 前后不变）；validation report 如实记录已运行项与
  NOT RUN；更新 README 注册表状态与 HANDOFF 当前状态块。当前 corrective
  working candidate 已完成 principal authority 深快照/深度不可变、
  human/service unknown-Space fail-closed 与组合进程总退出时限的 focused
  和静态门禁；本次未重跑 PostgreSQL，且共享 README/HANDOFF 仍按边界
  延后，因此 T8 保持未勾选。
- [ ] T9 单独立 Spec/质量复审（D-2026-07-26-2：P3 = 单独立评审 + 自动
  门禁）。复审中若出现新的同域基础不变量，按 033 §18 停止补丁循环、回到
  边界设计，不追加状态和异常分支。原 head 的复审证据不冒充本次 security
  corrective exact head；push 后仍需 fresh exact-head 门禁/复核。

完成 T8 前不得宣称 P3 验收达成；P2a/P2c/P2d/P5a0/P5a1 等消费方 PR 不得
提前依赖未合入的壳接线。
