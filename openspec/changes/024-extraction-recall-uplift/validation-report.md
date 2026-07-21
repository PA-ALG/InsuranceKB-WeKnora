# 024 验收报告（当前权威版本，2026-07-21）

> 本报告只陈述 PR #13 当前实现和 fresh 验证。历史返工经过留在 git/PR 评论，不在现行验收正文叠加旧口径。

## 1. 结论与证明力边界

024 的软件合同已实现：25 条归因工单的机制覆盖、prompt 变体、schema 驱动补漏、值粒度指引、弱值/兼容性双侧护栏，以及可穿过 `pred.jsonl` 交付边界的调用审计。

本 change 没有执行真实模型，也没有改动前的不可变 raw response 集，因此：

- **可以证明**：路由/触发/模板选择、解析、回验、预算、失败语义、producer 归因、序列化和配置边界符合规格；
- **不能证明**：真实召回或值粒度得到提升；
- **不能证明**：相同真实录制在 base SHA 与 candidate SHA 间分数不下降。

后两项仍是 020 D4/D4b 的未完成任务。synthetic probe 的 1.0 只表示其机制预言机成立，不是 before/after 质量结论。

## 2. 当前实现

### 2.1 Durable 预算与 attempt 事实账本

每个 run 在 `run_dir/llm-attempts.sqlite` 建立独立 SQLite 账本：

- `llm_attempts`：每次真实出站调用一条，`(run_id, attempt_id)` 唯一，记录 stage、prompt version、request key、outcome 与 budget scope；
- `llm_attempt_fields`：一次批调用关联全部字段，finalize 可按 field 聚合成功、失败、重试和落选历史；
- `llm_budget_policies`：冻结该 run 的 gapfill 上限，resume 改变有限值或有限/无限模式会 fail-closed；
- `llm_variant_assignments`：assignment 独立于候选成功与否持久化。

`reserve()` 使用 `BEGIN IMMEDIATE`，在 `ModelClient.complete()` 之前提交。hard crash 留下的 `reserved` 记录保守计入预算；没有 provider idempotency key 时不自动重发未知请求。`PipelineState.gapfill_calls_used` 仅是投影，不是预算权威。旧 checkpoint 若声称已消费预算而 ledger 无记录，也会 fail-closed。

### 2.2 Producer 与最终审计

`call_and_parse()` 返回结构化的 parsed items、producing attempt ID 和本次 attempt IDs。由此固定以下语义：

- transport failure/cancelled 在异常逃逸前已留痕；parse retry 成功时 retry 是 producer；
- 混合批次中，首轮已接受字段保留首轮 producer，只有真正被 validation retry 改写的字段指向 retry；
- extract、gapfill、vote、judge 的落选调用不会因 candidate merge 丢失；
- vote 仅确证时保留原 producer/origin，改写值时才指向胜出 vote attempt；judge 显式返回 attempt ID，不使用并发不安全的共享 `last_attempt`；
- finalize 从 durable field ledger 重建 `attempts[]`，并从 winner stage 派生 `winning_origin`、从 winner 派生 `prompt_variant_used`；winner 不属于该字段 attempts 时 fail-closed。

最终 `PredRecord.extraction_audit` 保持历史 JSONL 向后兼容；fastpath 的 winner 为 null。

### 2.3 配置入口

- `PipelineConfig`、`AssignmentPolicy`、`PromptVariant`、`VariantRegistry` 均 `extra="forbid"`；预算、enabled、seed 使用 strict 类型；
- experiment ID 在校验前 strip，启用时不得为空；CLI 拒绝空白 ID 和无 ID 的非零 seed；
- requiredness/必填的非法值或语义冲突带文件与字段定位抛 `SchemaLoadError`；
- `extract` 与 `extract-replay` 共用 builder，并暴露 `--gapfill-max-calls`、`--experiment-id`、`--experiment-seed`。

## 3. 工单与变体覆盖

- 归因工单：25 条（24 extract_empty + 1 prompt 域 routing_miss），机制用例覆盖 25/25；
- treatment 精确注册：16 个去重字段，其中 10 个长文本字段带原文粒度指引；
- `default@v1`：control 或未注册字段的默认补漏模板；
- `targeted@v1`：treatment 注册字段的定向短答/粒度指引；
- 首轮抽取两臂均使用相同 baseline prompt，实验差异只在 eligible gapfill 模板；实际调用与 assignment 分开审计。

## 4. Fresh 验证

基线是在 PR #13 原 head 合并 `origin/main@cfefcc9b` 后、功能修改前取得：Ruff PASS，mypy 257 files，deterministic `1978 passed / 30 deselected`。

最终提交前结果：

| 门禁 | 结果 |
|---|---|
| Ruff | `All checks passed!` |
| mypy strict | `Success: no issues found in 260 source files` |
| 024 focused | `99 passed` |
| deterministic | `2000 passed / 30 deselected` |
| OpenSpec | `openspec validate 024-extraction-recall-uplift --strict` → valid（遥测域名不可达的 flush 警告不影响 exit 0/校验结果） |

关键反例覆盖：hard-crash reservation reopen、resume 预算策略篡改、top-N/并发/parse retry/零预算、transport failure、同 request 多 attempt、跨 run replay ID、混合批 producer、extract→gapfill→vote 完整历史、vote 确证、assignment 独立持久化、最终 pred 与 durable ledger 一致、未知/宽松配置拒绝，以及 production/replay CLI 旧程序化 Namespace 兼容。

GitHub `deterministic`、`integration-postgres`、`wheel-smoke` 仍以 PR #13 精确 head 的 required checks 为合并权威；本报告不把旧 SHA 的绿灯挪用为新 SHA 证据。

## 5. 020 交接

020 D4 A/B 应从每条 pred 的 `extraction_audit.variant_assignment` 分臂，并以 `attempts[]`、`winning_attempt_id`、`prompt_variant_used` 验证实际 treatment 暴露；不得再读取旧的内部 `candidate.metadata["prompt_variant"]` 口径。

020 D4b 必须以同一批不可变 raw responses 分别在 base SHA 与 candidate SHA 重放，再比较 approved BaselineArtifact/QualityProfile。该任务在 020 tasks 中保持 `[ ]`，024 合入不会自动完成它。

## 6. 已知边界

1. Provider 当前不提供 idempotency key；进程在出站后硬崩时只能把 `reserved` 视为结果未知并保守计费，不能既保证硬上限又盲目重发。
2. SQLite ledger 是 run-dir 本地持久化组件，不是业务数据库迁移；run 目录必须位于可持久化文件系统。
3. 本 change 未执行 live 模型、未生成真实 uplift、未完成 020 D4/D4b。
