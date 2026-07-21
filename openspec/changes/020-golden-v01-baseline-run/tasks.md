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

状态：T1 软件准入闭环完成；当前权威工件为零模型 `BLOCKED`。T2～T7 未运行，T8 最终收尾未完成；在 021、输入/执行面身份、历史 provenance、签名审批、模型身份/probe 与预算账户全部通过前不得触发真实模型调用。

## T1 裁决记录（2026-07-20）

- 准入与执行共享同一 evaluator、canonical identity、签名/有效期和 durable budget contract；不存在 force bypass。
- annotation 执行前使用内容寻址的 schema/product/shared-input snapshot，提交前按快照与 PDF exact bytes 重渲染并语义等值校验。
- baseline checkpoint 只接受单链接 exact bytes，拒绝 WAL/SHM，并通过 SQLite deserialize 在内存校验；validation 到 settlement 始终持有同一 run lock。
- 产品授权缺失或 fresh candidate 非 READY 返回类型化 `BLOCKED`/退出码 2；evaluator、I/O 或资源状态不明确则暂停，不得猜测为可执行。
- 当前 `run-admission.json` 的 capability 为 `budget-ledger-v3-canary-v1`，所有 provider probe 均为 `not_attempted`，模型调用、token 与费用均为 0。
