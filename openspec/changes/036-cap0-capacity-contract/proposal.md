# 036 · CAP0 Capacity Contract

> 状态：🚧 实施中（Wave 1，总控窗口，2026-07-27）。授权：23 号控制板 §8
> D-2026-07-26-5（主线开发执行模式）；门禁语义：§8 D-2026-07-26-1；
> `stock_backfill` 负载原型：2026-07-27 执行裁决（总控窗口下达，控制板
> §8 补录行随本 PR 评审一并登记）。依赖：C0 已合入（PR #36），本 change
> 以 C0 `canonical_hash` 做 CapacityProfile 内容寻址。
>
> 权威设计源：
> `docs/superpowers/specs/2026-07-24-enterprise-llm-wiki-production-architecture-design.md`
> §5.1（容量包络：八项上线输入、三档证据、`INSUFFICIENT_CAPACITY_EVIDENCE`、
> 容量合同驱动的数据决策）与 §16 CAP0 行。本 change 不复制、不修改、不重新
> 解释该设计；语义冲突时以 033 与 23 号控制板裁决为准。

## 为什么做

033 §16 DAG 把 CAP0 放在关键路径上：`C0 → CAP0`，且
`C0 + P3 + CAP0 → P2a`、`CAP0 + P4a → P4b`、`P2a + P3 + P5a2 + CAP0 → P2b`、
`P2d + P8 + CAP0 → P9a`、`G0b + CAP0 + P9a + P14 → P15`。没有冻结的
CapacityProfile 合同，P2a/P2b 的表和索引合同、P4b 微批参数、P9a 下推
分页和 P15 生产切换都失去数值权威，只能回到"以后再压测"或拍脑袋倍数——
这正是 033 §5.1 明令禁止的。

D-2026-07-26-1 进一步裁定：P2a/P2b 的放行前置是 **CAP0 合同（schema 与
档位语义）冻结 + 一个 `launch` 档由业务方申报填写的已冻结 Profile 版本**；
实测验证与 `INSUFFICIENT_CAPACITY_EVIDENCE` 阻断只作用于 P15。八项上线
输入清单必须在 C0/W0 窗口期内向业务方发出并回收，是 CAP0 的显式交付物。

## 本 Change 做什么

按 033 §16 CAP0 行单一职责——「冻结 versioned CapacityProfile、
launch/contracted_forecast/stress_breakpoint 负载与阻断语义」——交付
（验收规格见 `specs/capacity-contract/spec.md`）：

- **合同 schema**：pydantic frozen `CapacityProfileV1`，八项 §5.1 上线输入
  为 typed 必填字段（无任何默认数值），内容寻址复用 C0
  `canonical_hash(object_type="capacity-profile")`；
- **三档证据**：`launch / contracted_forecast / stress_breakpoint` 每档记录
  inputs、负载原型、`source_kind`（`declared | measured`）、来源出处、
  `measured_at`、适用发布画像；`stress_breakpoint` 只接受实测；
- **门禁语义（D-2026-07-26-1）**：evaluator 返回封闭 typed 状态
  `SUFFICIENT_FOR_DESIGN | SUFFICIENT_FOR_LAUNCH |
  INSUFFICIENT_CAPACITY_EVIDENCE`——申报 launch 解锁 P2a/P2b 设计，实测
  launch（加上发布画像声明承诺时的 contracted_forecast）解锁 P15，缺输入
  一律 fail closed；
- **`stock_backfill` 负载原型（2026-07-27 裁决新增）**：存量回填——上线
  初期一次性批量导入历史文档，字段为文档数、文本片段总数、总字节、目标
  完成窗口、审核吞吐假设；`launch` 档必含（零回填以显式 0 申报）。字段
  只做非负/一致性校验、不设数量级上限（除 C0 安全整数域），可扩展承载
  业务方 2026-07-27 口头申报口径：约 3000 份文档（区间 1000–5000，
  PDF/PPT 混合）+ 约 30 万文本片段（区间 10–50 万），`source_kind=
  declared`（非实测）；
- **loader**：YAML/JSON 装载 + fail-closed 校验（typed
  `CapacityContractError`，封闭 reason code）；
- **八项问卷交付物**：确定性生成中文问卷
  `docs/insurance-kb/cap0-launch-questionnaire.md`（八项 + 存量回填，逐项
  说明/示例/填写槽位），供 C0/W0 窗口期发业务方回收；2026-07-27 口头
  申报的两项（文档数、文本片段数，含区间）以预填呈现，业务方只需确认或
  修正，不必从零填写。

### 作用域裁决：部署级 Profile + 档内可选 per-Space override

CapacityProfile 是**部署级**合同（绑定 `deployment_id`），不是 per-Space
运行时对象。理由：§5.1 八项里 PostgreSQL inline 上限、Release 保留窗口、
Query QPS/延迟目标、Worker/provider 并发与恢复 SLA 都是部署级共享资源
预算；第一项本身就以「每个 Space 的 …」形式内含跨 Space 分布；P2a/P2b
表和索引合同与 P15 生产切换也都是部署级事件。同时，负载确实分化的
Space（如存量回填目标 Space）可在证据档内以可选 `space_overrides` 按维度
覆盖，未覆盖维度显式继承部署级数值——保留 Space 显式性（CLAUDE.md 高频
不变量）而不把八项问卷放大成 N×8 的收集矩阵、不给业务方制造申报负担。

## 不做什么（非目标）

以下明确不属于 CAP0，出现在计划或 diff 中即 scope 违规（依据 033 §5.1
「容量合同只驱动必要的数据决策」与 §16 CAP0「不包含」列）：

- **压测平台**：不建 load-testing 平台/runner；`stress_breakpoint` 只定义
  证据记录合同，实测活动另行组织；
- **分片 / 第二数据库**：不分库、不分片、不引入第二状态数据库；只有
  `contracted_forecast` 或 `stress_breakpoint` 证据证明单 PostgreSQL 不能
  满足已承诺目标时才另立设计（033 §5.1）；
- **拍脑袋倍数**：不提供任何默认数值、示例 Profile 常量或"10x"式放大
  假设；示例数值只出现在问卷说明里并显式声明不是上限/默认值；
- 无领域表、无 Alembic 迁移、无 DB/网络 I/O（仅读 profile 文件、写问卷
  文件）；
- 不实现 P4b/P6b/P9a/P15 侧的容量执行接线（微批、Candidate 分片、下推、
  切换验证归各消费 PR）；不动 WeKnora fork。

## 影响面

- 新增：`harness/src/insurance_harness/capacity/` 包（models / loader /
  evaluator / questionnaire）、`harness/tests/test_capacity_contract_036.py`、
  `docs/insurance-kb/cap0-launch-questionnaire.md`（由 generator 生成并防
  漂移测试锁定）、本 change 三件套 + validation-report、README 台账 036 行
  状态更新；
- 无既有生产代码修改；无迁移；deterministic lane 新增一个测试文件；
- 后续消费者：P2a/P2b（表和索引合同放行）、P4b（微批/吞吐参数）、P6b
  （Candidate 容量分片）、P9a（下推分页预算）、P15（launch 实测验证与
  条件 contracted_forecast 阻断、breakpoint 报告记录）。
