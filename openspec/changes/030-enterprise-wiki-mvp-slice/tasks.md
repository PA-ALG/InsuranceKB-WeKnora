# 030 任务（I0a 数据 + I0b admission profile + I1 集成；除窄 admission profile 外不修功能域）

## I0 · Day 1 可并行

- [ ] T1 创建 23-entry manifest：20 个现有文件 exact path/hash + 3 个 fixture provenance/hash；5 个 product_meta 明确 registration-only/`claim_evidence_eligible=false`；冻结 5 product/version ids 与预期分类
- [ ] T2 创建受控 mixed-product、update/conflict、FAQ JSON fixtures；fixture 只表达验收行为，不污染 production dataset
- [ ] T3 027 合入后写 RED 并实现最小 parameterized run-admission core + 代码固定 MVP profile：只允许登记的 `purpose + run_schema_version + roles`；root-protected trust policy 把 key id/fingerprint 固定绑定真人 identity、approver role、domain、purpose/schema、Space；domain-separated 签名绑定 exact 23-entry/run/Space/Golden/routing/template/structured-dispatch/model/caps/provenance/clean-integration-SHA/expiry；实现 027 AdmissionVerifier，逐字段比较并经受控 issuer 返回 opaque VerifiedAdmission/full digest；显式拒绝自报 identity/role、cross-Space/profile/domain replay、手工 READY/custom verifier、任意 CLI/YAML profile/schema/role、020 evaluator/artifact、缺 expected identity、request drift、YAML 自报 READY 与 trust override；签名 envelope/request 存仓外内容寻址目录，不修改 020 canonical 工件，READY 前零模型
- [ ] T4 创建小 Golden Slice 与字段映射，覆盖高风险字段、三态、Evidence、冲突和结构化 locator

## I1 · 等 S/K/M 合入

- [ ] T5 写 MVP1/MVP2 contract tests：输入漂移、父 intake → 按产品/模板确定性子 job 扇出、歧义 unassigned 隔离、产品归属、模板 hash、跨产品污染
- [ ] T6 写 MVP3/MVP4 tests：precision/recall 计算、批准 Claim Evidence=100%、`product_meta` 注册且零 Claim/Evidence、FAQ raw 暂存、已登记 FAQ fact_assertions 全治理链
- [ ] T7 写 MVP5 tests：update/conflict、Alert、attempt exhaustion、CurrentRelease 不提前移动
- [ ] T8 写 MVP6 tests：manifest approval、人类 Reader/MCP 同 snapshot/hash、A→B→A 零模型回滚
- [ ] T9 写 MVP7 restart/idempotency tests；失败注入只放 integration suite
- [ ] T10 admission READY 后只用 028 TR8 exact `run-manifest --request ... --output-dir ...` 处理一次真实 23-entry slice；5 个 product_meta 只注册，18 个 knowledge-eligible inputs 按适用路径处理；exit 0 只产 sealed compilation manifest 且 CurrentRelease 不变。随后按 029 RA7 exact 命令消费该 bundle：真人填写并应用全部 review decisions→build candidate→另一授权真人填写 exact manifest hash/expected current 并 approve→CAS promote→Human/MCP serving proof→最后 seal final artifact manifest。不得另写编译 runner、调用模型作治理决定、默认批准或扩 scope；exit 2/3 与等待/拒绝/失败均诚实留证
- [ ] T11 输出 validation report：质量指标、逐故事证据、NOT RUN、七段时间、剩余缺口和 M2 重估
- [ ] T12 独立 spec/quality review；功能 finding 退回 S/K/M Owner；总体规划窗口最终放行
