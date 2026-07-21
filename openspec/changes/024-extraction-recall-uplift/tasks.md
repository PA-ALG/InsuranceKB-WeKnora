# 024 任务（当前权威状态，2026-07-21）

> PR #13 软件收口完成后方可合并。零真实模型调用的测试只证明机制、审计和护栏；真实召回改善及同录制集非退化仍由 020 D4/D4b 证明。

- [x] T1 将 005 的 24 条 extract_empty + 1 条 prompt 域工单固化为机制合同用例（E1）
- [x] T2 实现单一变体注册表、确定性选择、默认回落和版本标识（E2）
- [x] T3 实现 schema 驱动的定向补漏、source pointer 检索、evidence 回验和真实调用预算（E3）
- [x] T4 将字段级值粒度指引接入 treatment 变体，保持 pred/eval 契约不变（E4）
- [x] T5 建立 synthetic 后处理机制探针及 request-key/manifest 钉桩（E5；不冒充真实非退化证据）
- [x] T6 实现弱值清洗、引用指针和字段-值兼容性双侧护栏（E6）
- [x] T7 将 assignment、实际 prompt、完整 attempt 链、producer 和 winning origin 落入最终 pred（E7）
- [x] T8 以 run-scoped `llm-attempts.sqlite` 替换 node-local 预算/审计权威：出站前事务预留、崩溃后预算不复活、失败/重试/落选调用不丢失
- [x] T9 修正 producer 归因：parse retry、混合批次 validation retry、gapfill、vote 确证/改写、judge 并发均指向真实产生者
- [x] T10 配置 fail-closed：未知 Pydantic 键、匿名实验、requiredness 别名冲突均拒绝；production/replay CLI 暴露预算和 experiment ID/seed
- [x] T11 重写 proposal/spec/tasks/validation-report/HANDOFF、注册表和 PR 描述，使当前口径唯一且 020 D4b 保持未完成

集成门禁不是 024 软件任务：PR #13 只能在最新精确 head 的 GitHub `deterministic`、`integration-postgres`、`wheel-smoke` 全绿后合并；实时状态以 GitHub 为权威，不回填易陈旧的 checkbox。

## 关键裁决

1. **预算权威**：LangGraph checkpoint 只能证明已完成节点，不能证明已发出的外部请求；因此预算 reservation 必须在独立 SQLite 事务中先于 `ModelClient.complete()` 提交。未知结果保守计费，保证硬上限。
2. **审计权威**：candidate metadata 会被批处理和 merge 淘汰，不能承担完整事实链；finalize 按 field 从 ledger 重建 attempts，metadata 只保留 producer 等决策信息。
3. **调用身份**：attempt ID 为 run 内单调、回放确定性的调用 ID；request key 只表示内容身份，不能充当重试调用 ID。SQLite 主键以 `(run_id, attempt_id)` 隔离运行。
4. **producer 语义**：产生最终值的调用才是 winner。vote 只确证时保留原 producer；vote/judge 真正改写值时才成为 producer。`winning_origin` 和 `prompt_variant_used` 均由 winner 派生。
5. **实验归属**：assignment 属于 eligible population，不属于成功候选；因此在调用前独立持久化，失败或没有候选值也不能丢。
6. **证明力边界**：synthetic fixture 验证链路，不验证模型能力。020 D4b 的 differential replay 仍是未完成任务，不得因 024 软件合入而勾选。
