# 16 · Enterprise LLM Wiki 近期生产 Roadmap

> [!WARNING]
> **2026-07-29 路线修订**：以下旧 D0/Milestone DAG 保留作历史规划，不再授权
> PostgreSQL Active + WeKnora Projector。当前唯一顺序为 Mission 0 →
> `80a5003` capability gap/S0-Q → S0-R → 双 PASS → MVP 纵切。详见
> [Authority Amendment 2](../superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md)。
>
> 状态：用户于 2026-07-26 书面批准生产架构重置；D0 实施中。除 D0 文档外，
> 本路线所有功能、migration、provider 运行和上线能力均为
> `planned / not implemented`。

## 1. 唯一入口 DAG

```text
D0 → {C0, W0}
C0 → CAP0
then Milestone A → Milestone B → Milestone C
```

- **D0 Production Architecture Reset**：治理文档、边界、patch inventory。
- **C0 Canonical Envelope**：唯一跨语言 canonical bytes/hash 规范与 vectors。
- **W0 Revision Contract Spike**：只读证明 WeKnora lifecycle/revision 合同；
  证据不足才触发 W1。
- **CAP0 Capacity Contract**：在 C0 后冻结版本化 CapacityProfile 和真实
  launch/forecast/breakpoint 证据。

## 2. Milestone A — Semantic Core

目标：证明 WeKnora exact SourceRevision 可以稳定形成有 provenance、identity、
applicability、conflict 和 security boundary 的知识 IR。

主要小 PR：

- P1 Job + Outbox
- P2a Evidence + Provenance
- P2d Space Security Boundary
- P3 API/Worker 壳
- P4a Source Inbox、P4b Microbatch、P4c Revision Capture
- P5a0 Entity Resolution、P5a1 SchemaVersion、P5a2 Assertion Identity
- P5b1 Extraction、P5b2 Conflict/Retraction
- G0a Golden Product Contract、G0s Semantic Core Check

完成 Milestone A 不表示已发布生产 Wiki。

## 3. Milestone B — Governed Active Release

> **HISTORY-ONLY**：本节原目标中的 PostgreSQL 原子 Active 已被 Amendment 2
> 取代。目标态改为 Harness 授权、WeKnora 原子激活唯一 serving Head，并通过
> 固定 Release 查询和回滚。

主要小 PR：

- P2b Wiki Release Store
- P2c Review + Quality Policy Store
- P6a WikiPageRevision Compiler
- P6b CandidateRelease Assembly
- P7 ReviewPolicy
- P8 ReleaseService
- P9a Active Query API
- G0b Core Acceptance

关键结果：四种 ReviewPolicy、不可变 Candidate/Decision/Release、
`active_release_id + activation_epoch` CAS、Outbox、同 Release Query。

## 4. Milestone C — WeKnora Production Experience

目标：完成 WeKnora managed Wiki 投影、证据与审核体验、Proposal 编辑、ACL、
恢复演练和生产切换。

主要小 PR：

- P9b Thin MCP Adapter（按发布画像启用）
- P10 ChangeProposal
- P11 managed-page fencing
- P12 Projector
- P13 Evidence + Review UX
- P14 Proposal Edit UX
- P15 Production Cutover
- G0v Version Acceptance（有真实第二版本资料时）

## 5. 并行与串行原则

- D0 完成后 C0 与 W0 可并行。
- CAP0 只在 C0 合同可用后启动。
- migration lane 严格串行；每个 PR 最多一个 migration，并从执行时真实
  Alembic head 占号。
- WeKnora patch 只允许 W1/P11/P13/P14。
- 一个 PR 只交付一个领域不变量；通常 10–15 个逻辑文件，超出需要 reviewer
  对原子事务作出明确裁决。
- PostgreSQL 权威与 WeKnora 投影分离，MCP 不阻塞基础 Wiki/API 上线画像。

## 6. 容量与样本口径

Golden Product、文档数、产品数、Worker 数、attempt 数和并发只属于版本化
fixture、EvaluationProtocol 或 CapacityProfile。它们可以用于某次验收，但不
构成产品硬上限，也不得替代真实 launch 容量证据。

## 7. 阶段门

每个 PR 必须先冻结 Contract Card、路径预算、事务/authority、状态机、威胁
矩阵和关键 RED。Spec/Quality C/I=0、对应门禁和 exact-SHA CI 通过后才可合入。
任何阶段不得用完成基础设施数量替代可演示的用户结果或知识质量证据。
