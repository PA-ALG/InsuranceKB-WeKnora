# 030 任务（I0 数据 + I1 集成；不修功能域）

## I0 · Day 1 可并行

- [ ] T1 创建 23-source manifest：20 个现有文件 exact path/hash + 3 个 fixture provenance/hash；冻结 5 product/version ids 与预期分类
- [ ] T2 创建受控 mixed-product、update/conflict、FAQ JSON fixtures；fixture 只表达验收行为，不污染 production dataset
- [ ] T3 建独立 MVP admission plan/artifacts；只复用 admission API，不修改 020 canonical 工件；READY 前零模型
- [ ] T4 创建小 Golden Slice 与字段映射，覆盖高风险字段、三态、Evidence、冲突和结构化 locator

## I1 · 等 S/K/M 合入

- [ ] T5 写 MVP1/MVP2 contract tests：输入漂移、产品归属、模板 hash、跨产品污染
- [ ] T6 写 MVP3/MVP4 tests：precision/recall 计算、批准 Claim Evidence=100%、JSON/FAQ 全治理链
- [ ] T7 写 MVP5 tests：update/conflict、Alert、attempt exhaustion、CurrentRelease 不提前移动
- [ ] T8 写 MVP6 tests：manifest approval、人类 Reader/MCP 同 snapshot/hash、A→B→A 零模型回滚
- [ ] T9 写 MVP7 restart/idempotency tests；失败注入只放 integration suite
- [ ] T10 admission READY 后只用 028 TR8 exact `run-manifest --request ... --output-dir ...` 编译一次真实 23-source slice；exit 0 只产 sealed compilation manifest 且 CurrentRelease 不变。随后按 029 RA7 exact 命令消费该 bundle：真人填写并应用全部 review decisions→build candidate→另一授权真人填写 exact manifest hash/expected current 并 approve→CAS promote→Human/MCP serving proof→最后 seal final artifact manifest。不得另写编译 runner、调用模型作治理决定、默认批准或扩 scope；exit 2/3 与等待/拒绝/失败均诚实留证
- [ ] T11 输出 validation report：质量指标、逐故事证据、NOT RUN、七段时间、剩余缺口和 M2 重估
- [ ] T12 独立 spec/quality review；功能 finding 退回 S/K/M Owner；总体规划窗口最终放行
