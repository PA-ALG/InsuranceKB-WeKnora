# 037 · W0 WeKnora Revision Contract Spike

> 状态：Wave 1 实施中（总控窗口，2026-07-27）。授权：23 号控制板 §8
> D-2026-07-26-5；依赖：D0。权威：033 §4.4 与 §16 W0 行、23 号 §3 W0
> 任务卡、D-2026-07-26-4（spike 问题按"直接产出 W1 API 规格草案"设计）。

## 为什么做

P4a（Source Inbox）与 P4c（Revision Capture）的合同不能建立在设计假设上。
033 §4.4 已指出：本地 WeKnora 的 trace `attempt` 是观测量而非 chunk
revision token，通用 chunk API 无 attempt 字段，重解析会删除并重建同一
knowledge 的 chunks。W0 必须用当前跟版基线上的**可复现实验证据**分别冻结
`SourceLifecycleContract` 与 `RevisionManifestContract`，只允许两个结论：
现有公开 API 充分，或触发最小 W1（并直接给出 W1 API 规格草案）。

## 本 Change 做什么（只读 spike，非功能 patch）

- 在 023 已验收的本机 live 环境（127.0.0.1:8080 六服务）上执行 §T 的
  probe 清单；spike 允许在该本地环境创建/重解析/删除**自有 scratch
  knowledge**，不触碰任何既有数据，不打印任何凭据；
- 产出 `artifacts/w0-evidence-report.md`：每个 probe 的请求形状（脱敏）、
  观察结果、可复现步骤与结论；
- 产出两份合同裁决（sufficient / insufficient per contract）；任一
  insufficient 时附 `artifacts/w1-api-draft.md`（最小版本化
  lifecycle/manifest API 草案，满足 033 §4.4 第 2 项字段清单）。

## 不做什么

- 不改 WeKnora Go 代码、不加 webhook、不读共享 DB/Redis/Asynq；
- 不写 Harness 功能代码/迁移；
- 不把时间戳、最终 M2 相等或客户端重试当作原子合同证明；
- 台账 037 行已由 PR #36/#38 占号，本 change 不重复改 README。

## 影响面

evidence report 直接决定 P4a/P4c 是否解除 blocked 以及是否启动 W1 实现
窗口；不影响任何运行代码。
