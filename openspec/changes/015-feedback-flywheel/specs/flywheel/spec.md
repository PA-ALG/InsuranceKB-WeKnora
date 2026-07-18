# 015 反馈飞轮验收规格

> 三版（2026-07-18）：codex 接管 PR #18 后按企业多实例/多租户不变量收口。条款号沿用 F 系（F1~F4）。
> 相对一版（light）的实质变更：F1.1 拆分为「离线 trace 源+游标」与「Langfuse 直连（gated，生产者合同前置）」；
> F1.3 脱敏上移为构造边界；F2.1 观察队列须可消费；F3.1 TopN 输出脱敏问题、闭环周期落地；
> F3.3 dry-run 收紧为零写入/零 schema 变更、缺配置 fail-closed；`--apply` 的
> observation/gap/checkpoint 改由 Space-scoped 数据库单事务持久化，文件不再充当状态真相源。

## ADDED Requirements

### Requirement: F1.1a 离线 trace 源与增量游标

飞轮 SHALL 支持离线 JSONL trace 源（每行一条归一化 `Trace`）；增量处理 SHALL 以 `(timestamp, trace_id)` 游标为界——timestamp SHALL 解析为 timezone-aware UTC 参与排序（无时区视为 UTC），SHALL NOT 以裸字符串比较时序；同批内同 `trace_id` SHALL 去重（保留最新时间戳一条）；游标 SHALL 单调不回退。游标 SHALL 由数据库按 `(space_id, source_id)` 持久化，SHALL NOT 使用调用方可误复用的无 Space 文件作为真相源；推进语义与 observation/gap 写入的原子性见 F3.3。

#### Scenario: 游标增量与重跑幂等

- **WHEN** 一批 trace 处理完成并推进游标后，同批 trace 再次输入
- **THEN** 数据库游标过滤后零新 trace，observation 不重复、缺口 hit_count 不再累计

#### Scenario: 混合时区正确排序

- **WHEN** 同批含 `+08:00` 偏移与 `Z` 后缀且实际时刻交错的 trace
- **THEN** 按 UTC 实际时刻排序与过滤，游标编码为 UTC 归一化形式

#### Scenario: 同批重复 trace 只计一次

- **WHEN** 同一 `trace_id` 在同批出现两次
- **THEN** 只处理一条（最新时间戳），对应缺口 hit_count 恰为 1

### Requirement: F1.1b Langfuse 直连（gated：生产者合同前置）

Langfuse 直连拉取 SHALL 以 **WeKnora 实际生产者合同**为准——本仓库 `internal/tracing/langfuse` 的根 trace 无 Input、Output 仅 `{"status": ...}`，问答在 `chat.completion(.stream)` 子 observation、检索在 `retrieve` span；因此直连 SHALL 按 traceId 组装根 trace + child observations + named scores（消费 observations API 与 `meta` 分页游标），只接收问答类 trace，从最终 completion 提取问答，分数按命名 score 分别映射，SHALL NOT 假设根 trace 顶层携带 `input/output/source_refs/score/annotation`。「无引用」识别 SHALL 绑定真实 citation 合同（trace 内脱敏 citation 摘要或经 WeKnora REST 关联，二选一经 SDD 裁决）；合同落地并有 sanitized fixture 验证前，直连模式 SHALL NOT 提供（fail-closed，不得基于虚构字段归一化）。分页 SHALL 完整消费、对 429/5xx 有上限退避。

#### Scenario: 合同就绪前直连不可用

- **WHEN** 生产者合同 fixture 与 citation 合同裁决尚未落地
- **THEN** 飞轮不提供 Langfuse 直连路径（CLI 无该模式、无消费虚构字段的归一化代码），离线 JSONL 为唯一 trace 源

### Requirement: F1.2 四类信号识别（纯规则、可配置）

识别器 SHALL 为纯规则零模型：无引用回答（实质回答且零 `source_refs`；拒答不算）、低置信/拒答（话术模式表 + score 阈值）、负反馈（score/annotation）、空知识（对齐实体查无 published Claim，经注入式 `claim_lookup`）；每类 SHALL 可独立启停，关闭的识别器即使命中也不产出。

#### Scenario: 识别正确且拒答不误报编造

- **WHEN** 一条拒答话术回答（零引用）进入识别
- **THEN** 产出 low_confidence_refusal 而非 no_citation

#### Scenario: 关闭的识别器被抑制

- **WHEN** `no_citation=False` 且回答满足无引用特征
- **THEN** 不产出 no_citation 信号

### Requirement: F1.3 PII 脱敏为构造边界

问题文本脱敏（手机号/证件号/保单号遮蔽、业务数字保留）SHALL 施加在 `Trace` **构造边界**（模型校验器）——任何入口（离线 JSONL、直接构造、未来直连）产出的 `Trace.question` SHALL 已脱敏，SHALL NOT 依赖某个 adapter 的调用约定；持久化 payload 的实际消费点 SHALL 幂等再脱敏，以防内部误用 `model_construct/model_copy` 绕过模型校验；原文不落任何持久化产物，只留 trace_id 回指。

#### Scenario: 全部入口一致脱敏

- **WHEN** 含手机号的 trace 分别经 JSONL 反序列化与直接模型构造进入
- **THEN** 两条路径的 `question` 均不含原号码，非 PII 业务数字保留

#### Scenario: 内部绕过模型校验仍不落原文

- **WHEN** 内部调用方误用无校验构造方式生成含手机号的 Trace 并进入 pull
- **THEN** evaluation、观察队列与 gap 样例均不含原号码

### Requirement: F2.1 实体对齐 fail-safe 与可消费观察队列

对齐 SHALL 复用 003 路由器（question 当单页文档路由）；candidates 仅含 exact/alias；**全部 actionable 命中唯一产品才对齐**，≥2 个不同产品或零命中 → 不对齐（跨层唯一，红队定案）；字段级先剔除已命中产品名/别名表面串再匹配注入词表；概念级候 009。有信号但未对齐的 trace SHALL 进入**可消费的观察队列**——每条含 trace_id、脱敏问题、信号类型与未对齐原因（零命中/多产品歧义），SHALL NOT 只留计数丢弃明细；队列 SHALL 持久化在 `flywheel_observations`，所有查询强制带 Space，跨 Space 不可见；队列不开单。

#### Scenario: 跨层歧义 fail-safe

- **WHEN** 问题同时命中产品 A 全名（exact）与产品 B 别名（alias）
- **THEN** 不对齐（进观察队列），不误挂任一产品

#### Scenario: 观察队列保留可消费明细

- **WHEN** 一条含信号但对齐不到产品的 trace 完成处理
- **THEN** 该 Space 的观察队列可查询该条的 trace_id、脱敏问题、信号类型与原因；另一 Space 查询不可见

### Requirement: F2.2 缺口聚合（稳定 ID、去重计数、最近样例）

缺口稳定 ID SHALL 由对齐粒度派生（同粒度必同 key）；同一缺口重复触发 SHALL 只累计 hit_count 与**最近** trace 样例（≤5 条，新样例替换最旧），不重复开单；同一 `trace_id` 对同一缺口 SHALL NOT 重复累计 hit_count；样例 SHALL 含脱敏问题文本（供 TopN 报表）。

#### Scenario: 最近样例滚动替换

- **WHEN** 同一缺口被 7 条不同 trace 依次触发
- **THEN** hit_count=7 且样例为最近 5 条（最早 2 条被替换）

#### Scenario: 重复 trace 不重复计数

- **WHEN** 同一 trace_id 对同一缺口触发两次
- **THEN** hit_count 恰为 1

### Requirement: F2.3 resolve→reopened

已 resolve 的缺口再次触发 SHALL 状态转 reopened（知识补了还答不好=新问题），保留 first_seen 不重置。

#### Scenario: reopen 保留首见时间

- **WHEN** resolved 缺口被新 trace 触发
- **THEN** 状态为 reopened 且 first_seen 为最初触发时间

### Requirement: F2.4 ReviewItem 投影（gated：knowledge 域 subject 形态）

缺口落地 ReviewItem(type=knowledge_gap) SHALL 为 knowledge 域投影（飞轮聚合为真相源、投影只引用）。当前 `resolve_review` 的 approve/reject 路径强制取得 ChangeItem 并执行 Claim 变更；knowledge_gap 的“补材料重编/人工补录/标记库外问题”既没有 ChangeItem，也没有动作状态机。该动作合同及 Space-scoped subject 引用经独立 SDD 定稿前，SHALL NOT 创建一个可展示却在点击 approve/reject 时失败的假工单；`--open-tickets` SHALL 在一切 I/O 前受阻非零退出（见 F3.3）。

#### Scenario: 投影未就位不假装开单

- **WHEN** subject 形态尚未协商落地时请求开单
- **THEN** 显式受阻退出，零 ReviewItem 写入

### Requirement: F3.1 周期报表

报表 SHALL 含：分状态计数（open/reopened/resolved）、相对上一状态快照的新增数、TopN 答不上问题（按 hit_count 降序，**输出脱敏问题样例**而非仅内部 key）、缺口→闭环平均周期（基于 first_seen/resolved_at，无已闭环缺口时显式为空不虚报）、按产品分布；空知识识别未激活（未接 claim 源或已配置关闭）时报表 SHALL 自陈覆盖面。

#### Scenario: TopN 输出人类可读问题

- **WHEN** 报表生成时缺口带脱敏问题样例
- **THEN** TopN 行含脱敏问题文本 + 命中数（内部 gap_key 可附带但不是唯一标识信息）

#### Scenario: 闭环周期可复算

- **WHEN** 存在 resolved 缺口（first_seen 与 resolved_at 齐备）
- **THEN** 平均闭环周期 = 各缺口 (resolved_at − first_seen) 的均值，可由输入复算

### Requirement: F3.2 与 011 健康度报告合流（gated）

健康度报告 SHALL 含飞轮小节（供给侧巡检 + 需求侧反馈同页）；候 011 报告框架（PR #12）合入后实施。

#### Scenario: 合流后同页呈现

- **WHEN** 011 框架合入且飞轮小节接线
- **THEN** 健康度报告单页同时含巡检与飞轮缺口摘要

### Requirement: F3.3 CLI 与 durable unit-of-work（dry-run 零副作用、Space 隔离、原子 exactly-once）

`flywheel pull` SHALL 要求稳定 `source_id`，默认 dry-run：**零状态写入**——不建/写游标、缺口或观察文件，不写数据库，SHALL NOT 执行 schema 迁移（迁移属部署流程；schema 缺失/过旧 → 非零退出诚实报错）；只从已部署数据库读取该 `(space_id, source_id)` 的 checkpoint、该 Space 的 gap 状态、产品索引与 published Claim 覆盖。缺 DB 配置 SHALL fail-closed 非零退出，SHALL NOT 静默回退本地 SQLite。受阻/无效能力参数（`--open-tickets`）SHALL 在任何文件/DB/网络 I/O 之前校验并立即非零退出。

`--apply` SHALL 以数据库为唯一状态真相源，并在迁移 **0012** 的三表持久化：

- `flywheel_checkpoints`：`(space_id, source_id)` 唯一，保存已完成批次的游标；
- `flywheel_observations`：保存该源每条已处理 trace 的脱敏问题、信号、对齐结果/原因与可选 gap 引用，`(space_id, source_id, trace_id)` 唯一作为 processed ledger；
- `knowledge_gaps`：`(space_id, gap_key)` 唯一，保存对齐粒度、hit_count、最近样例、first_seen/last_seen/resolved_at/status。

一次 apply SHALL 在同一 caller-owned 数据库事务、同一 Space/source 串行边界内完成：读取并锁定状态 → 计算 → 同批写 observations/upsert gaps（实现可为满足引用完整性先 flush gap 主键）→ 最后推进 checkpoint。任一持久化失败 SHALL abort 整个 unit-of-work，三表零部分提交；SHALL NOT 在 failed transaction 内继续或单独推进 checkpoint。健康事务重试同批 SHALL 业务 exactly-once（observation 不重复、gap hit_count 恰增一次、checkpoint 单调）。所有表及服务查询 SHALL 强制 Space；相同 source_id 在不同 Space 的状态完全隔离。文件导出若后续提供只能是数据库只读派生物，SHALL NOT 反向充当 checkpoint/gap/queue 状态输入。

空知识识别在 CLI 数据库路径 SHALL 注入真实的 Space-scoped published Claim 查询：产品粒度查该产品任一已发布 Claim，字段粒度同时约束 predicate；另一 Space 的 Claim 不得让本 Space 被误判为已有知识。仅当识别器开启且该查询已接入时，报表才可声明 `empty_knowledge_active=true`。

#### Scenario: dry-run 前后零状态变化

- **WHEN** 对全新路径执行 dry-run（含 space 不存在的失败路径）
- **THEN** 无新建数据库文件、无 schema 变更、三张飞轮表零写入

#### Scenario: 缺配置 fail-closed

- **WHEN** 未提供 `--db-url` 且环境无 `HARNESS_DB_URL`
- **THEN** 非零退出并明示缺配置，不回退本地 SQLite

#### Scenario: 受阻参数前置校验

- **WHEN** 以 `--open-tickets` 调用而投影未就位
- **THEN** 在读文件/连 DB 之前立即非零退出（rc=2）

#### Scenario: --apply 闭环跨周期累计

- **WHEN** 第一轮 `--apply` 提交数据库状态，第二轮以同一 Space/source 处理新 trace
- **THEN** 同缺口 hit_count 跨轮累计、resolved 后再触发报 reopened、游标续位

#### Scenario: apply 中途失败零部分提交且重试恰一次

- **WHEN** observation 已暂存后、gap 或 checkpoint 写入前注入持久化失败
- **THEN** 整个事务回滚，三表均无该批副作用；健康事务重试后 observation 恰一条、hit_count 恰增一次、checkpoint 才推进

#### Scenario: 相同 source_id 跨 Space 完全隔离

- **WHEN** Space A 已处理 source `langfuse-export`，Space B 用相同 source_id 处理自己的批次
- **THEN** B 不读取 A 的 checkpoint/gap/observation，两个 Space 各自从自身状态推进

#### Scenario: CLI 空知识查询读取真实 published Claim

- **WHEN** 问题对齐到产品/字段且 CLI 运行于数据库路径
- **THEN** 只以当前 Space 下对应产品版本的 published Claim 判断是否空知识，并在报表诚实标注该识别器已激活

### Requirement: F4 验收

夹具 trace SHALL 覆盖：四类信号各 ≥2、含 PII 需脱敏、对齐不到实体各路径；断言识别正确、聚合幂等、观察队列不误开单、脱敏全入口生效、游标增量与重跑幂等；数据库验收 SHALL 覆盖 SQLite 迁移/Space FK/事务故障注入，以及真实 PostgreSQL 双会话同源并发（无环境时明确 NOT RUN，CI 必须 tests>0/skipped=0）；全程零模型调用；门禁全绿不破坏既有测试。

#### Scenario: 零模型调用

- **WHEN** 全部飞轮测试运行
- **THEN** 无任何真实模型/网络调用（确定性纯规则）
