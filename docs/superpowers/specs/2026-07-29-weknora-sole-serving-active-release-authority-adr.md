# ADR · Sole Serving Active Release Authority

> 日期：2026-07-29
> 决策：`D-2026-07-29-1`
> 状态：`ACCEPTED_CONDITIONALLY`
> 适用范围：Enterprise LLM Wiki 的线上 serving Release 权威
> 上位输入：`jlx_enterprise_llm_wiki_complete_728_v3.md`

## 决策

正式线上知识只能有一个 serving Active Release authority。Harness 与
WeKnora 不得同时保存可独立决定线上版本的 Active Head。

当前选择 WeKnora 承载唯一 serving Active Head，状态为
`ACCEPTED_CONDITIONALLY`：

- WeKnora 负责当前 Active Release、原子激活、pinned read、当前 ACL 与回滚；
- Harness 负责寿险语义编译、Claim/Relation/Evidence、Candidate、ReviewPolicy、
  ReviewDecision 与 PublishAuthorization；
- Harness 可以保存不可变 Candidate、决策、命令和回执，但不得把本地
  `current_release` 或 receipt 镜像作为第二个线上 Head；
- 正式页面和 Agent payload 必须使用同一 WeKnora `release_id`；
- 未发布 Source/chunk 只能用于 Evidence、审核和补编，不能作为正式答案旁路。

这里的“sole authority”只指 serving Active Release，不取消 Harness 的语义、
审核与发布授权权威。

## 为什么

读取、ACL、Wiki UI、检索与 Agent 平台均在 WeKnora。把唯一 serving Head 放在
读取侧，使跨系统复杂度集中在低频发布路径，避免每次读取承担双 Head、freshness、
双 ACL 和 reconciliation。

本决策不声称 Release Kernel 已实现。WeKnora 作为载体必须通过能力缺口核对和
S0-R 证伪窗口。

## 当前运行过渡态

当前状态固定为：

```text
NO_PRODUCTION_ACTIVE_RELEASE
```

目标 Release Kernel 尚未实现。P3 生产 Worker 使用空业务 Handler registry；
旧 `ReleasePublisher`、SnapshotReader 和 `current_release` 虽保留公开导出与
测试覆盖，但没有生产运行时调用方，只作审计和定向移植输入。

S0-R 只能使用隔离的测试 Space 与专用凭据，成功后最多把已验证路径标为
`EXPERIMENTAL`。只有后续独立 OpenSpec 冻结正式协议、Space/principal/ACL
合同、完整验收与 Artifact/runtime 门禁后，才允许声明
`ACTIVE`；Mission 0 文档不得提前改变运行态。

## 条件与证伪

以下任一条件成立，必须重新评估单一 authority 的承载位置：

1. 无法以有界 patch 实现整版 manifest、pinned read 或 release-aware retrieval；
2. S0-R 无法证明原子激活、幂等、并发单赢家或防旁路写；
3. Release Kernel 必须侵入寿险领域语义或持续修改大量上游核心路径；
4. 后续升级在同一区域反复产生不可接受的合并和 migration 成本。

回退只重新选择单一载体，不恢复 Harness Active + WeKnora Active 双权威。

## S0-R 裁决窗口

S0-R 是输入就绪后的两工作日证伪窗口，不是生产级 Release Kernel 的交付承诺。
开工前必须以独立 OpenSpec/Mission Card 冻结测试 Space、KB、fixture、环境、
权限、暂定最小协议及可核验预算。预算至少列出 exact fork 路径、表/索引、
migration、read surface、升级责任和允许的验证命令；任一维度超出即终止并输出
`RELEASE_PATH_NOT_FEASIBLE`，不得在计时中无界扩面。计时开始后只允许两个
终态：

- `RELEASE_PATH_FEASIBLE`：最小目标路径跑通，并列出正式实现剩余工作、patch
  面积、migration 面积和升级责任；
- `RELEASE_PATH_NOT_FEASIBLE`：指出载体、检索、权限或跟版成本中不成立的条件。

不得以“尚未完成”为理由无限延期，也不得把旁路 Demo 当作可行性证据。S0-R
通过只提升载体可行性状态，不等于生产 Kernel、MVP 或 Artifact 完成。

最小有效 fixture 必须验证**集合级原子性**而非单页写通：

- R0 包含 A/B/C；R1 同时更新 A、删除 B、保持 C、增加 D；
- 从同一 base 构造两个不同 Candidate 并发竞争，只有一个可激活；
- 在 preparation、index、CAS、receipt 边界注入有界失败，并在激活前后并发
  pinned/current read；
- 任何读取只能看到完整 R0 或完整 R1，不得看到成员混版；
- 当前 ACL 至少含两个 principal，并对 pinned 内容验证一次 ACL shrink；
- 普通 PUT/DELETE 不能修改 release-managed 内容，Harness 不能形成第二 Head。

S0-R 编码前的独立 OpenSpec 还必须冻结暂定 `PublishAuthorization` 字段、
canonical bytes、nonce、校验顺序、失败零写，以及最小 pinned/current/
release-aware read 与 ACL 场景。它们是待证伪协议，不是本 ADR 已批准的生产
实现。

## MVP cardinality

MVP profile 固定：

```text
1 Space = 1 RAW KB + 1 release-managed Wiki KB
```

这是 MVP cardinality，不是永久企业不变量。当前不建设 RAW KB 数组或多 KB ACL
聚合。MVP 绑定模型必须使用单值 `raw_kb_id` 与单值
`release_managed_wiki_kb_id`；企业版出现真实多 RAW KB 需求后，必须通过新的
ADR、OpenSpec 与显式 migration 扩展。

## 正式页面编辑

上游 `80a5003` 的单页 history/diff/manual edit/revert 是已采用的平台能力，但
不等于整版 Release 或正式知识编辑闭环：

- 普通、非 release-managed Wiki 页面可以使用上游单页能力；
- release-managed 页面在 MVP 中拒绝普通 PUT/DELETE；
- 正式知识修改后续必须形成 Proposal → Candidate → Review → 新 Release；
- ChangeProposal 与 Proposal Edit UX 继续后置。

## 当前身份与状态

- 上游功能基线：
  `80a5003cc99a427098afe184eee6601916d3d156`；
- trusted image 构建源码：
  `a8bf55ae18441abd380e594afba5000c51cc9633`，已包含 `80a5003`；
- Mission 0 基线 main：
  `529d72c994369750b26e352a70fd6284e8b0fd9d`；
- app/frontend/docreader 已固定 immutable digest；
- Full Artifact/W1 runtime probes 与 `source_reader` authority 仍未闭合。

不得把 current main、image build source 和 upstream capability commit 混写为同一
身份。

## 明确非目标

- 不实现 Release Kernel、S0-R、S0-Q 或 MVP；
- 不修改 principal、功能代码、workflow、deployment lock 或 migration；
- 不删除旧 018 表、代码、migration 或历史数据；
- 不重做已经完成的 `80a5003` 版本选择；
- 不建设通用发布平台、通用 schema planner 或多 KB ACL 框架。
