# 020 任务

- [x] T1.1 冻结类型化 admission、三模型角色、受信 provenance/approval、完整输入/execution-surface identity、durable budget reserve、安全 probe 与 runtime 重验条款（D1.1a～D1.5）
- [x] T1.2 先写引用条目号的 RED 测试，覆盖角色/expected revision 漂移/依赖/完整输入与 dirty tree/签名 canonical bytes+domain/scope/run 防重放/凭据/HTTPS+TLS+trust_env=False/规范化 probe+redirect/脱敏/过期/退出码（D1.1a～D1.2b/D1.4）
- [x] T1.3 实现最小 evaluator + CLI，生成 canonical JSON 与 `run-admission.md`；不得调用推理端点，不得信任 result 派生状态（D1.2a/D1.2b/D1.4/D1.5）
- [x] T1.4 实现稳定 run-level 预算账户、链式 ceiling revision、durable reservation/request-attempt owner-CAS ledger 及跨 run replay、部分消费后扩容、两进程单 outbound、release-vs-claim、reserved/settled/released/uncertain 与 pre-send/send/response 崩溃恢复测试（D1.3a～D1.3c）
- [x] T1.5 将同一 evaluator/hash/signature/expiry/digest/reserve contract 接入 T2/T4 入口；每产品前重验且无 force bypass（D1.3b/D1.3c/D1.5）
- [x] T1.6 生成并复核当前零模型 `BLOCKED` 工件；仅在 T1.5 capability 已验收、021 合入且三模型/provenance/预算签名批准、probe 均有效后才允许刷新为 `READY`（D1.1～D1.5）
- [ ] T2 生成两个产品分页工件并完成实际标注、quote 回验与 disputed 修正（D2.1/D2.2）
- [ ] T3 dry-run、发布 gs-v0.1、自评满分、收尾 002 T8/T9（D2.3/D2.4）
- [ ] T4 断点运行 13 产品 baseline，复跑 dead letter（D3.1）
- [ ] T5 完成 judge queue 回写与重新出分（D3.2/D3.3）
- [ ] T6 完成长字段 keypoints 与 before/after 回归（D4.1/D4.2）
- [ ] T7 生成 approved baseline/QualityProfile（D4.3）
- [ ] T8 validation-report、HANDOFF/002/05/13/16/20 对账（D5）
- [ ] D4b（024 R2 让渡承接）differential replay：以同一批不可变 raw responses 对 base SHA 与 candidate SHA 重放评分，建立“后处理改动非退化”真实证据（024 E5 的非退化半条在此完成；synthetic 机制探针不作数）

状态：T1 软件准入闭环已在 021 合入后的基线上复验；当前权威工件为零模型 `BLOCKED`。021 revision/输入执行面指纹已通过；T2～T7 未运行，T8 最终收尾未完成。在剩余历史 provenance/缺失输入、签名审批、模型身份/probe 与预算账户全部通过前不得触发真实模型调用。

## T1 裁决记录（2026-07-20）

- 准入与执行共享同一 evaluator、canonical identity、签名/有效期和 durable budget contract；不存在 force bypass。
- annotation 执行前使用内容寻址的 schema/product/shared-input snapshot，提交前按快照与 PDF exact bytes 重渲染并语义等值校验。
- baseline checkpoint 只接受单链接 exact bytes，拒绝 WAL/SHM，并通过 SQLite deserialize 在内存校验；validation 到 settlement 始终持有同一 run lock。
- 产品授权缺失或 fresh candidate 非 READY 返回类型化 `BLOCKED`/退出码 2；evaluator、I/O 或资源状态不明确则暂停，不得猜测为可执行。
- 当前 `run-admission.json` 的 capability 为 `budget-ledger-v3-canary-v1`，所有 provider probe 均为 `not_attempted`，模型调用、token 与费用均为 0。

## T1 合并前硬化裁决（2026-07-21）

- 删除未完成信任链的 provider `no_usage` authority；release 只允许零 attempt，历史/篡改 `no_usage` 一律按 uncertain/full-reserve 恢复。未来若需要零费用 reconciliation，必须另立 OpenSpec 并同时交付 trust root、签名 schema、受控 loader 与 provider evidence lineage，不能用 caller 自报 proof 授权退款。
- 同 run budget revision 只允许提高 account ceiling；product、exact request、request pool 及其 limits/rates 的增删改均属于新合同，必须拒绝，防止用“扩容”绕过原始签名范围。
- production Bailian 只接受与真实 POST `model` 完全相同的 provider-guaranteed immutable deployment ID；revision-only/可变 alias 只能作为审计观察，不能授权推理。
- 019/021 依赖身份固定为实际 main merge `4d9c84e25bd53f3564631b8f8dc0b1f85e21e55f` / `cfefcc9b3a7d6af0503f3b76cf8ac5a1b6d44b35`，feature head、cherry-equivalent 或“仅为祖先”均不能替代 designated revision。
- canonical 工件采用两阶段提交：先提交代码/source plan，再从 clean code SHA 运行 CLI 生成 JSON/Markdown。当前 evaluated revision=`2169c5821021dfc9513d3cc760dea4fc4e519112`，结果仍为零模型 `BLOCKED`，且已消除 dirty/dependency/identity drift 阻塞。
