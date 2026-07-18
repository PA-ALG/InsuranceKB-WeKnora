# 015 反馈飞轮 · 验证报告

> 三版（2026-07-18，codex 接管 PR #18）：以本版替换二版的文件态结论。文件
> cursor/gap/observation 不能构成多实例原子真相源；本版以迁移 0012 的 Space-scoped
> 数据库 unit-of-work 收口。旧设计与返工经过仍保留在 `tasks.md` 裁决 10～15。

范围：F1.1a 离线增量、F1.2/F1.3、F2.1～F2.3、F3.1、F3.3 与 F4。F1.1b
Langfuse 直连、F2.4 ReviewItem 投影、F3.2 健康度合流继续 gated；未虚报为完成。

## 1. 最终门禁

| 门禁 | 结果 |
|---|---|
| `openspec validate 015-feedback-flywheel --strict` | PASS，`Change '015-feedback-flywheel' is valid` |
| `ruff check .` | PASS，All checks passed |
| `mypy src tests` | PASS，238 source files |
| `pytest -m "not live and not integration_postgres" -q` | PASS，1681 passed / 9 deselected |
| PostgreSQL 16 `pytest -m integration_postgres` | PASS，4 passed / 1686 deselected；JUnit `tests=4 skipped=0` |
| WeKnora live | NOT RUN；本变更无 WeKnora REST/模型调用，Langfuse 直连仍 gated |

PostgreSQL 证据来自本机独立端口、tmpfs 数据盘的 PostgreSQL 16，四节点包含 008、017、
018 与本变更的双会话同源并发。合并资格仍以新 SHA 的 GitHub deterministic 与
integration-postgres CI 为准；本机结果不冒充 exact-SHA CI。

## 2. 条款到测试的溯源

| 条款/不变量 | 主要测试 |
|---|---|
| F1.1a UTC 游标、批内去重、重跑幂等 | `test_f1_1*`、`test_f1_1a*`；`test_f3_3_apply_persists_all_three_tables_and_retry_is_exactly_once` |
| F1.2 四类信号与独立启停 | `test_f1_2_*`；`test_f3_3_preview_is_read_only_and_real_published_claim_suppresses_empty_signal` |
| F1.3 构造边界与消费点纵深脱敏 | `test_f1_3_*`、`test_f1_3_trace_question_redacted_at_construction`、`test_f1_3_pull_redacts_question_again_at_persistence_boundary` |
| F2.1 fail-safe 对齐与可消费队列 | `test_f2_1_*`、`test_f2_1_pull_observations_carry_consumable_details`、`test_f2_1_same_source_is_isolated_across_spaces_and_queue_query_is_scoped` |
| F2.2 稳定 key、去重计数、最近五条 | `test_f2_2_*` |
| F2.3 resolve→reopened | `test_f2_3_*` |
| F3.1 状态、TopN、周期、产品分布 | `test_f3_1_*` |
| F3.3 每条 fresh trace 的不可变台账 | `test_f3_3_pull_emits_one_immutable_evaluation_per_fresh_trace` |
| F3.3 迁移 0012 / Space FK | `test_f3_3_0012_creates_space_scoped_flywheel_tables`、`_rejects_cross_space_observation_gap_reference` |
| F3.3 downgrade 安全 | `test_f3_3_0012_chain_downgrade_preflights_0003_before_any_ddl`、`_downgrade_refuses_to_drop_durable_state` |
| F3.3 原子失败/健康重试 | `test_f3_3_apply_failure_rolls_back_all_state_and_healthy_retry_counts_once` |
| F3.3 dry-run / DB apply / fail-closed | `test_f3_3_cli_*`（10 例） |
| F3.3 PostgreSQL 并发 exactly-once | `test_f3_3_live_postgresql_two_sessions_apply_same_trace_exactly_once` |
| F4 lane 不可静默漏跑 | `test_p0_4_three_collections_are_disjoint_exhaustive_and_precise`、`test_p0_2_explicit_postgres_without_url_fails_instead_of_skipping` |

## 3. 企业不变量的实现证据

### 3.1 数据库是真相源

- `flywheel_checkpoints`：`(space_id, source_id)` 唯一；游标仅在本批 observation/gap
  flush 成功后更新。
- `flywheel_observations`：每条 fresh trace 都落 processed ledger（含无信号 trace）；
  `(space_id, source_id, trace_id)` 唯一。
- `knowledge_gaps`：`(space_id, gap_key)` 唯一；保存计数、最近样例与生命周期。
- observation→gap 与 gap/observation→product 均使用含 Space 的复合外键，数据库层拒绝
  跨 Space 引用。

### 3.2 原子 exactly-once

`apply_pull` 不提交事务；调用方拥有 outer transaction。服务先验证 loader-attested
`KnowledgeScope`，锁 KnowledgeSpace 行（gap 跨 source 聚合，所以锁粒度是 Space），再读
checkpoint/gap、计算、写 gap/processed ledger，最后推进 checkpoint。任意 flush 异常向上
传播，由 caller rollback 三表。故障注入证明 gap 已 flush 后 ledger 失败仍三表为零，健康
重试只计一次；PostgreSQL 两会话证明并发结果等价于串行执行。

### 3.3 空知识读取真实 Claim

CLI/仓储路径始终注入 Space-scoped published Claim 查询；产品粒度连接
`ProductVersion.product_id`，字段粒度再约束 `Claim.predicate`，概念粒度约束
`Claim.concept_id`。另一 Space 的 Claim 不参与判断。只有识别器开启且该查询已接入时报告
`empty_knowledge_active=true`。

### 3.4 dry-run 与 CLI

CLI 必填稳定 `--source-id`；dry-run 只读已部署 schema，不创建 DB、不迁移、不写三表。
`--apply` 才开启 caller-owned transaction。旧 `--cursor-file/--gaps-file/
--observations-out` 状态输入已删除；未来文件导出只能由 DB 派生。`--open-tickets` 在任何
文件/DB I/O 前 rc=2，避免创建能展示却不能处理的假工单。

## 4. downgrade 链级安全补强

新增 0012 后，全仓首次回归抓到 6 个历史 016 用例失败：`head→0002` 会先执行 0012
downgrade 的 DDL，之后 0003 才拒绝多 Space/全局 key 冲突；SQLite 已发生部分 schema
变化。修复不是放宽旧测试，而是在 0012 的首个 DDL 前镜像 0003/0005 的下游兼容性
预检，并拒绝删除任何非空飞轮真相表。Alembic env 同步注册 flywheel ORM，使
`alembic check` 不再把三表误报为待删除。

## 5. 诚实 gated 边界

| 能力 | 状态与理由 |
|---|---|
| F1.1b Langfuse 直连 | 未做。WeKnora 根 trace 不携带 Q/A；须先完成 child observation、named score、分页/退避与 citation 合同的 SDD + sanitized fixture。 |
| F2.4 ReviewItem 投影 | 未做。现有 approve/reject resolver 强制 ChangeItem 并执行 Claim 变更；knowledge_gap 动作状态机未定义，不能创建假工单。 |
| F2.1 concept 对齐 | 候 009 词表；当前 product/field 已实现。 |
| F3.2 健康度合流 | 候 011 报告框架。 |

这些 gated 项不阻塞本轮 DB durable foundation，但不得在 PR 标题/描述中宣称已交付。

## 6. 本轮教训

1. 单机原子替换文件不等于企业多实例事务；先写 cursor 后写 gap 会永久漏数，且文件路径
   不携 Space 身份。持久化不变量必须从故障点和并发点推导，而非从“能保存”推导。
2. 新 Alembic head 必须继承所有下游 downgrade preflight；只测 `0012→0005` 不足以证明
   `head→old` 安全。全仓门禁抓到的 6 个失败是有效安全回归，已转为本 change 的显式测试。
3. 外部 ReviewItem/Langfuse 合同不成熟时继续 gated，比为了“功能完整”虚构可用路径更可靠。
4. Pydantic 构造校验不是持久化 sink 的唯一安全边界；`model_construct/model_copy` 可绕过 validator，敏感文本应在实际消费点幂等规范化。
