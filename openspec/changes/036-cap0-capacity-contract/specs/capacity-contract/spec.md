# 036 CAP0 Capacity Contract 验收规格

## ADDED Requirements

### Requirement: CAP0.1 版本化不可变 CapacityProfile 与内容寻址

系统 SHALL 提供 frozen 的 `CapacityProfileV1`（pydantic `frozen=True`、
`extra="forbid"`），字段为：`contract`（必填 literal
`"cap0-capacity-profile/v1"`，文件缺失即拒绝）、`profile_version`（整数
≥ 1）、`deployment_id`（匹配 `^[a-z0-9][a-z0-9._-]{0,63}$`）与三个可选
证据档 `launch` / `contracted_forecast` / `stress_breakpoint`。系统 SHALL
提供 `capacity_profile_hash(profile) -> str`：以 C0
`canonical_hash(object_type="capacity-profile", payload)` 计算，payload 为
模型的确定性 python dump。同一抽象内容 SHALL 与构造顺序、进程无关地得到
同一 64 位小写 hex hash；任一字段内容变化 SHALL 得到不同 hash。已构造的
Profile SHALL 拒绝字段赋值；内容修改 SHALL 通过铸造新 `profile_version`
与新 hash 表达，SHALL NOT 原地重写历史版本。`object_type` SHALL 固定为
常量 `"capacity-profile"`。

#### Scenario: 内容寻址稳定

- **WHEN** 独立构造两份字段完全相同的 Profile 并分别求 hash
- **THEN** 两个 hash 相等且为 64 位小写 hex

#### Scenario: 内容变化换 hash

- **WHEN** 仅把某一容量数值 +1 后重新构造并求 hash
- **THEN** hash 与原 Profile 不同

#### Scenario: 冻结拒绝赋值

- **WHEN** 对已构造 Profile 的任意字段赋值
- **THEN** 以 typed 错误拒绝，原值不变

#### Scenario: Decimal 规范化继承 C0

- **WHEN** 分别以 `Decimal("3.5")` 与 `Decimal("3.50")` 填同一放大率字段
  构造两份 Profile
- **THEN** 两份 Profile 的 hash 相等（定点规范化由 C0 编码层完成）

### Requirement: CAP0.2 §5.1 八项上线输入为 typed 必填字段

`CapacityInputsV1` SHALL 以八个必填 typed 子模型逐项覆盖 033 §5.1 上线
输入清单，SHALL NOT 为任何数值提供默认值或兜底常量：

1. `space_sources`：`space_count`（≥1）、`active_sources_per_space`、
   `retained_sources_per_space`、`peak_source_revisions_per_day_per_space`；
2. `document_shape`：`avg_document_bytes`、`p95_document_bytes`、
   `avg_chunks_per_document`、`p95_chunks_per_document`（chunk/record 数）；
3. `revision_amplification`：`claims_per_source_revision`、
   `relations_per_source_revision`、`provenance_anchors_per_source_revision`；
4. `evidence_fragment_limits`：`max_logical_bytes_per_fragment`（≥1）、
   `max_postgres_inline_bytes_per_fragment`；
5. `release_retention`：`retained_release_count`、`pages_per_release`、
   `blocks_per_page`、`release_retention_days`（≥1）、
   `artifact_retention_days`（≥1）；
6. `candidate_review`：`changed_claims_per_candidate`、
   `changed_pages_per_candidate`、`changed_bytes_per_candidate`、
   `max_manifest_bytes`（≥1）、`review_queue_slo_hours`（≥1）；
7. `active_query`：`sustained_qps`、`burst_qps`、`p95_response_bytes`、
   `p95_latency_ms`（≥1）；
8. `worker_provider`：`worker_concurrency`（≥1）、`provider_concurrency`
   （≥1）、`max_queue_backlog`、`recovery_sla_hours`（≥1）。

八项中任何一项整体缺失或其任一叶子字段缺失 SHALL 拒绝构造；未知字段
SHALL 拒绝（`extra="forbid"`）。

#### Scenario: 缺失任一维度拒绝

- **WHEN** 分别删去八项中的任意一项后构造 `CapacityInputsV1`
- **THEN** 每次构造均以 typed 校验错误拒绝，不产生部分对象

#### Scenario: 未知字段拒绝

- **WHEN** 输入含未在合同中声明的字段（任意层级）
- **THEN** 构造以 typed 校验错误拒绝

### Requirement: CAP0.3 三档证据结构

每个证据档 SHALL 为 `CapacityEvidenceTierV1`，字段全部必填（除
`space_overrides` 默认为空映射）：`inputs`（`CapacityInputsV1`）、
`workloads`（`CapacityWorkloadsV1`，内含 `stock_backfill` 槽位）、
`source_kind`（封闭 `declared | measured`）、`source_ref`（非空来源出处，
纯空白拒绝）、`measured_at`（tz-aware datetime，naive 拒绝）、
`applicable_release_profile`（非空发布画像名）。`stress_breakpoint` 档
SHALL 要求 `source_kind = "measured"`：申报出来的 breakpoint 属于 033
§5.1 禁止的无工作负载假设，SHALL 拒绝构造。

#### Scenario: naive measured_at 拒绝

- **WHEN** 证据档的 `measured_at` 无时区信息
- **THEN** 构造以 typed 校验错误拒绝

#### Scenario: 申报式 stress_breakpoint 拒绝

- **WHEN** `stress_breakpoint` 档的 `source_kind = "declared"`
- **THEN** Profile 构造以 typed 校验错误拒绝

#### Scenario: 空来源出处拒绝

- **WHEN** `source_ref` 为空串或纯空白
- **THEN** 构造以 typed 校验错误拒绝

### Requirement: CAP0.4 档位门禁语义（D-2026-07-26-1）

系统 SHALL 提供
`evaluate_capacity_evidence(profile, release_profile) -> CapacityEvidenceEvaluation`，
其中 `ReleaseProfileV1` 必填 `name` 与
`declares_customer_growth_commitment`（无默认值）。结果 SHALL 为 frozen
typed 对象：`state`（封闭
`SUFFICIENT_FOR_DESIGN | SUFFICIENT_FOR_LAUNCH | INSUFFICIENT_CAPACITY_EVIDENCE`）、
`design_unblocked`、`launch_unblocked`、`reasons`（封闭 reason code 元组）、
`stress_breakpoint_recorded`。语义 SHALL 为：

1. `launch` 档存在、`applicable_release_profile` 与所评发布画像一致且
   `source_kind = "declared"` 时，state ≥ `SUFFICIENT_FOR_DESIGN`，
   `design_unblocked = true`（P2a/P2b 放行前置），`launch_unblocked =
   false`，reasons 含 `launch_declared_only`；
2. 同上但 `source_kind = "measured"`，且（发布画像声明客户增长承诺时）
   `contracted_forecast` 档存在并匹配画像，state =
   `SUFFICIENT_FOR_LAUNCH`，`launch_unblocked = true`（P15 前置）；
3. `contracted_forecast` SHALL 只在
   `declares_customer_growth_commitment = true` 时参与判定；其缺失或画像
   不匹配 SHALL 只阻断 launch（reasons 含 `contracted_forecast_missing`
   或 `contracted_forecast_release_profile_mismatch`），SHALL NOT 降级
   design；
4. `stress_breakpoint` SHALL NOT 参与任何阻断，只在存在且画像匹配时把
   `stress_breakpoint_recorded` 置 true（默认只形成扩容证据）；
5. `reasons` SHALL 非空当且仅当 state ≠ `SUFFICIENT_FOR_LAUNCH`，且只取
   封闭集合 `launch_tier_absent | launch_release_profile_mismatch |
   launch_declared_only | contracted_forecast_missing |
   contracted_forecast_release_profile_mismatch`。

#### Scenario: 申报只解锁设计不解锁上线

- **WHEN** `launch` 档 `source_kind = "declared"` 且画像匹配
- **THEN** state 为 `SUFFICIENT_FOR_DESIGN`，`design_unblocked` 为 true，
  `launch_unblocked` 为 false，reasons 为 `("launch_declared_only",)`

#### Scenario: 实测解锁上线

- **WHEN** `launch` 档 `source_kind = "measured"`、画像匹配且该画像未声明
  增长承诺
- **THEN** state 为 `SUFFICIENT_FOR_LAUNCH`，`launch_unblocked` 为 true，
  reasons 为空

#### Scenario: 承诺画像缺 forecast 只阻断上线

- **WHEN** `launch` 档已实测且画像匹配，发布画像声明增长承诺，但
  `contracted_forecast` 档缺失
- **THEN** state 为 `SUFFICIENT_FOR_DESIGN`，`design_unblocked` 为 true，
  `launch_unblocked` 为 false，reasons 含 `contracted_forecast_missing`

#### Scenario: breakpoint 不参与阻断

- **WHEN** 仅缺 `stress_breakpoint` 档、其余满足实测上线条件
- **THEN** state 仍为 `SUFFICIENT_FOR_LAUNCH`，
  `stress_breakpoint_recorded` 为 false

### Requirement: CAP0.5 INSUFFICIENT_CAPACITY_EVIDENCE fail closed

state SHALL 在 `launch` 档缺失或其 `applicable_release_profile` 与所评
发布画像不一致时为 `INSUFFICIENT_CAPACITY_EVIDENCE`，`design_unblocked` 与
`launch_unblocked` SHALL 均为 false，reasons 含 `launch_tier_absent` 或
`launch_release_profile_mismatch`。库 SHALL NOT 提供任何预填数值、示例
Profile 常量或"固定倍数"兜底：合同内所有容量数值字段均无默认值，档内
输入不可部分构造，缺输入的唯一表达是整档缺失 + evaluator 的
INSUFFICIENT 状态。

#### Scenario: 缺 launch 档

- **WHEN** Profile 三档全缺，对任意发布画像求值
- **THEN** state 为 `INSUFFICIENT_CAPACITY_EVIDENCE`，两个 unblocked 均为
  false，reasons 含 `launch_tier_absent`

#### Scenario: 画像不匹配 fail closed

- **WHEN** `launch` 档为画像 A 实测填写，但对画像 B 求值
- **THEN** state 为 `INSUFFICIENT_CAPACITY_EVIDENCE`，reasons 含
  `launch_release_profile_mismatch`

### Requirement: CAP0.6 stock_backfill 存量回填负载原型

`StockBackfillWorkloadV1`（2026-07-27 裁决新增）SHALL 为 frozen typed
模型：`document_count`（存量文档总数）、`total_text_fragments`（存量
文本片段总数，FAQ/chunk 等）、`total_bytes`（存量总字节）、
`target_completion_window_days`（≥1）、`review_throughput_docs_per_day`
（审核吞吐假设）。字段 SHALL 只做非负与一致性校验、不设数量级上限
（除 C0 安全整数域）：2026-07-27 口头申报口径——数千份 PDF/PPT 文档 +
几十万文本片段——SHALL 可直接表达。`launch` 档 SHALL 必含
`workloads.stock_backfill`：零回填 SHALL 以显式 `document_count = 0`
申报，槽位缺失即拒绝（缺失 ≠ 零，对齐 `unknown ≠ absent_explicitly`）。
`document_count > 0` 时 SHALL 满足
`review_throughput_docs_per_day × target_completion_window_days ≥
document_count`，否则以不可行回填计划拒绝构造——申报一个算术上不可能
完成的计划等价于无工作负载假设。`contracted_forecast` 与
`stress_breakpoint` 档的 `stock_backfill` 槽位 MAY 为空（回填是上线一次性
负载）。

#### Scenario: launch 档缺 stock_backfill 拒绝

- **WHEN** `launch` 档的 `workloads.stock_backfill` 缺失
- **THEN** Profile 构造以 typed 校验错误拒绝

#### Scenario: 申报规模可直接表达

- **WHEN** 以 `document_count = 3000`、`total_text_fragments = 300000`、
  窗口 60 天、审核吞吐 60 篇/日构造（60 × 60 = 3600 ≥ 3000）
- **THEN** 构造成功并参与内容 hash

#### Scenario: 不可行回填计划拒绝

- **WHEN** `document_count = 3000`、`review_throughput_docs_per_day = 10`、
  `target_completion_window_days = 60`
- **THEN** 构造以 typed 校验错误拒绝（10 × 60 < 3000）

#### Scenario: 显式零回填受理

- **WHEN** `document_count = 0` 且其余字段合法
- **THEN** 构造成功；该申报参与内容 hash

### Requirement: CAP0.7 部署级作用域与可选 per-Space override

`CapacityProfileV1` SHALL 为部署级合同（绑定 `deployment_id`）。每个证据
档 MAY 携带 `space_overrides`：`space_id →
CapacitySpaceOverrideV1` 映射，key SHALL 匹配
`^[a-z0-9][a-z0-9._-]{0,63}$`。override 的八项维度与 `stock_backfill`
字段 SHALL 全部可选：某维度存在即整体替换该 Space 的该维度，缺失即显式
继承部署级数值。全部字段皆空的 override SHALL 拒绝（无信息量的 override
不得进入合同）。override SHALL 参与内容 hash；其内部数值 SHALL 服从与
部署级完全相同的校验规则。

#### Scenario: 全空 override 拒绝

- **WHEN** 某 Space 的 override 所有字段均缺失
- **THEN** 构造以 typed 校验错误拒绝

#### Scenario: 部分 override 受理并参与 hash

- **WHEN** 某 Space 仅覆盖 `document_shape` 一项，其余继承
- **THEN** 构造成功，且该 Profile 的 hash 与无 override 版本不同

#### Scenario: 非法 space key 拒绝

- **WHEN** override key 为空串、含大写或以 `$` 开头
- **THEN** 构造以 typed 校验错误拒绝

### Requirement: CAP0.8 数值校验规则

所有计数/字节/时长字段 SHALL 为整数且 `0 ≤ v ≤ 2^53−1`（C0 安全整数域，
超界在模型层拒绝而非 hash 时才失败）；比率与 QPS 字段 SHALL 为
`Decimal`，受理 `int | str | Decimal`，二进制 `float` 在任何数值字段
SHALL 拒绝（与 C0.3 对齐，binary float 不得参与 identity）。跨字段规则
SHALL 为：`p95_document_bytes ≥ avg_document_bytes`、
`p95_chunks_per_document ≥ avg_chunks_per_document`、
`burst_qps ≥ sustained_qps`、
`max_postgres_inline_bytes_per_fragment ≤ max_logical_bytes_per_fragment`。
违反任一规则 SHALL 以 typed 校验错误拒绝构造。

#### Scenario: 负数拒绝

- **WHEN** 任一计数字段为负
- **THEN** 构造以 typed 校验错误拒绝

#### Scenario: float 拒绝而十进制字符串受理

- **WHEN** 放大率分别以 `3.5`（float）与 `"3.5"`（str）填写
- **THEN** float 拒绝且错误信息指向 float 禁用；字符串构造成功且值为
  `Decimal("3.5")`

#### Scenario: p95 小于均值拒绝

- **WHEN** `p95_document_bytes < avg_document_bytes`
- **THEN** 构造以 typed 校验错误拒绝

#### Scenario: 超安全整数拒绝

- **WHEN** 任一整数字段为 `2^53`
- **THEN** 构造在模型层以 typed 校验错误拒绝

### Requirement: CAP0.9 loader fail closed

`load_capacity_profile(path) -> CapacityProfileV1` SHALL 只受理
`.yaml/.yml/.json` 文件；一切非法输入 SHALL 以 typed
`CapacityContractError` 拒绝，reason SHALL 取封闭集合
`profile_file_not_found | profile_file_unreadable |
unsupported_profile_format | profile_parse_error |
profile_root_not_mapping | invalid_profile`，SHALL NOT 产生部分 Profile、
SHALL NOT 以默认值补缺。同一逻辑内容经 YAML 与 JSON 装载 SHALL 得到相同
`capacity_profile_hash`。除读取 profile 文件与写问卷文件外，capacity 包
SHALL 无 I/O、无 DB、无迁移、无网络。

#### Scenario: YAML 与 JSON 同 hash

- **WHEN** 同一逻辑 Profile 分别写成 YAML 与 JSON 并装载
- **THEN** 两次装载的 `capacity_profile_hash` 相等

#### Scenario: 未知扩展名拒绝

- **WHEN** 装载 `.toml` 路径
- **THEN** 以 `unsupported_profile_format` 拒绝

#### Scenario: YAML 浮点拒绝并指引改写

- **WHEN** YAML 中比率写为未加引号的 `3.5`（解析为 float）
- **THEN** 以 `invalid_profile` 拒绝且错误信息包含 float 禁用与改写为
  字符串的指引

#### Scenario: 文件缺失拒绝

- **WHEN** 装载不存在的路径
- **THEN** 以 `profile_file_not_found` 拒绝

### Requirement: CAP0.10 八项问卷交付物

`generate_launch_questionnaire() -> str` SHALL 确定性生成中文问卷
markdown：申报头（`deployment_id`、`applicable_release_profile`、增长
承诺勾选、`source_kind`、`measured_at`、`source_ref`）；§5.1 八项逐项
一节，每节含说明（该项驱动哪些容量决策）、示例与空白填写槽位，示例旁
SHALL 显式声明示例数值不是产品上限也不是默认值；第九节 `stock_backfill`
（五字段 + 可行性约束说明与已申报数示算）；以及 declared/measured 语义
与 `INSUFFICIENT_CAPACITY_EVIDENCE`/P2a/P2b 不放行后果的说明。每个填写
槽位 SHALL 标注对应的合同字段路径，保证回收后可无歧义机器录入。问卷
SHALL 把 2026-07-27 口头申报的两项（约 3000 份 PDF/PPT 文档、约 30 万
文本片段，含区间）作为预填呈现并留确认/修正槽位，业务方只需修正而非
从零填写；其余项 SHALL 保持空白槽位。
`write_launch_questionnaire(path)` SHALL 把 generator 输出原样写入。仓库
`docs/insurance-kb/cap0-launch-questionnaire.md` SHALL 与 generator 输出
逐字节一致（防漂移测试锁定）。

#### Scenario: 八项与 stock_backfill 全出现

- **WHEN** 生成问卷
- **THEN** 文本包含八项各自的节标题与全部叶子字段路径、`stock_backfill`
  五字段、`INSUFFICIENT_CAPACITY_EVIDENCE` 与 declared/measured 说明

#### Scenario: 已申报两项预填

- **WHEN** 生成问卷
- **THEN** `stock_backfill.document_count` 与
  `stock_backfill.total_text_fragments` 槽位含「已申报（2026-07-27
  口头）」预填与区间（1000–5000、100000–500000），并标注请确认或修正

#### Scenario: 仓库问卷零漂移

- **WHEN** 比较 `docs/insurance-kb/cap0-launch-questionnaire.md` 与
  `generate_launch_questionnaire()` 输出
- **THEN** 逐字节一致

#### Scenario: 写出即生成内容

- **WHEN** `write_launch_questionnaire(tmp_path)` 后读回文件
- **THEN** 内容与 `generate_launch_questionnaire()` 相等
