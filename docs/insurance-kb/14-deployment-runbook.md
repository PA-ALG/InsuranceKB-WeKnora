# 14 · 生产部署与联调 Runbook

> [!WARNING]
> **SUPERSEDED / HISTORY-ONLY — NOT EXECUTABLE（2026-07-29）**
>
> 本章的 PostgreSQL Active→Outbox→Projector 拓扑已被
> [`Authority Amendment 2`](../superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md)
> 取代，不再授权实施。当前只允许 Mission 0 后的 S0-R/S0-Q 证伪；正式部署
> Runbook 必须等载体、权限、激活与 Artifact 合同冻结后另行修订。以下正文保留
> 作历史验收清单，不表示 API、Worker、表、migration、WeKnora patch 或上线
> 环境已经实现。
>
> 当前权威：
> [`Sole Serving Active Authority ADR`](../superpowers/specs/2026-07-29-weknora-sole-serving-active-release-authority-adr.md)
> 与 [`Authority Amendment 2`](../superpowers/specs/2026-07-29-enterprise-llm-wiki-authority-amendment-2.md)。

## 1. 目标拓扑

```text
用户 / connector
  → WeKnora upload / parse / OCR / Source
  → versioned REST + Source lifecycle adapter
  → LLM Wiki API / Worker
  → shared PostgreSQL
       ├─ fixed job state / lease / Outbox
       ├─ Claim / Relation / Evidence / Conflict
       ├─ Candidate / ReviewDecision
       └─ immutable WikiRelease + active_release_id / activation_epoch
  → fenced WeKnora managed Wiki projection
  → Active Query API
  → optional thin MCP consumer adapter
```

WeKnora 与 LLM Wiki 不共享数据库、Redis/Asynq 或内部队列。API 和 Worker 使用
同一 Python wheel、不同进程角色，可横向扩容。近期只承诺单地域、多实例和共享
PostgreSQL，不承诺多地域 active-active。

## 2. Serving 与发布

- 应用知识权威是 PostgreSQL Active WikiRelease。
- promotion 在一个事务中重验 Candidate、Decision、base release/epoch、
  ReviewPolicy、binding/security 与自动审核资格，创建不可变 Release，CAS
  更新 active pointer/epoch，并写 Outbox。
- 同一 Space 的 Candidate、策略切换和 promotion 串行；不同 Space 可并行。
- CAS loser 整体回滚，再由 fresh 事务 stale/requeue；旧 Decision 不复用。
- Worker 与 Projector 是 at-least-once，以稳定幂等键、fencing 和
  reconciliation 收敛。
- WeKnora managed Wiki 是可重建投影。投影失败影响 freshness，不改变
  Active Release。

## 3. WeKnora 集成与 patch budget

Harness 只消费版本化 REST 和 Source lifecycle event。当前没有可靠 webhook
时，可由低并发 polling adapter 生成内部事件，但 reconciliation 始终保留。
MCP 只映射 Active Query，不用于 Source 写入、投影或内部 control plane。

唯一允许的 planned WeKnora patch：

| Patch | 用途 | 当前状态 |
|---|---|---|
| W1 | W0 证明不足时补最小 revision/lifecycle manifest API | planned，条件触发 |
| P11 | managed-page activation-epoch fencing 与 RAW ACL read guard | planned |
| P13 | Evidence 下钻与 CandidateRelease 批量审核 UX | planned |
| P14 | managed Wiki 编辑转 ChangeProposal UX | planned |

实际路径和上游基线以
`deploy/patches/enterprise-llm-wiki-patch-inventory.yaml` 为准。D0 不产生
WeKnora patch。

## 4. 审核与查询

每个 Space 配置不可变、版本化 ReviewPolicy：

- `machine_auto`
- `human_batch`
- `hybrid`
- `trusted_import`

自动发布要求 exact QualityProfileApproval、AutomationScope、run fingerprint、
covered capabilities 和 CompilationSecurityProfile。缺失、撤销、漂移或绝对
安全阻断确定性回落 `human_batch`。

Active Query 在请求开始时固定一个 `release_id`。页面、Claim、Relation、
Evidence 与引用必须来自同一 Release。没有已发布知识时返回
`insufficient/needs_qualification`；原始资料只进入证据核查、审核和补编。

## 5. 配置与容量

部署前必须由 CAP0 冻结版本化 CapacityProfile，至少包含 Space、Source、
revision、文档字节/chunk、Evidence、Candidate、Query QPS、Worker/provider
并发、队列和恢复 SLA。

具体资料数量、每批文档数、Worker 数或并发值只可作为某一 fixture、launch
profile 或环境配置；它们不是产品硬上限。超限任务进入持久队列或明确 blocked，
不能被丢弃或无限创建协程。

## 6. 分阶段上线门

```text
D0 → {C0, W0}
C0 → CAP0
then Milestone A → Milestone B → Milestone C
```

- Milestone A 证明 exact SourceRevision 能形成有 provenance、identity、
  applicability 和 conflict 的语义知识。
- Milestone B 证明四种审核策略、PostgreSQL 原子发布、固定版本查询和回滚。
- Milestone C 证明 WeKnora fenced projection、Evidence/Proposal UX、ACL、
  恢复演练和生产切换。

当前只有 D0 文档阶段在执行，其他全部为 `planned / not implemented`。

## 7. 最终生产证据

P15 至少需要以下带时间、版本和结果的证据：

1. PostgreSQL HA/PITR/restore；
2. artifact digest/integrity；
3. credential rotation/revocation；
4. dead-letter replay 与 Outbox reconciliation；
5. Worker/数据库故障和积压恢复；
6. launch CapacityProfile；
7. Golden Product 的 approved QualityProfile；
8. Active Query 同 Release、ACL 和 rollback；
9. P11/P12 managed-page fencing 与 freshness；
10. 选定消费画像的真实 E2E。

本次 D0 不运行或声称上述证据。
