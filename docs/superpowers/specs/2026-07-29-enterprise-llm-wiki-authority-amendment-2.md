# Enterprise LLM Wiki Authority Amendment 2

> 日期：2026-07-29
> 状态：`APPROVED GOVERNANCE AMENDMENT / IMPLEMENTATION NOT STARTED`
> 修订对象：OpenSpec 033 与 2026-07-24 生产架构设计中的 serving authority、
> Projector、P11/P12 和交付顺序
> 配套 ADR：
> `2026-07-29-weknora-sole-serving-active-release-authority-adr.md`

## 1. 修订结论

本修订取代以下旧执行方向：

```text
PostgreSQL Space.active_release_id + activation_epoch
→ Outbox
→ wiki_projector
→ WeKnora fenced managed-page projection
```

新的目标方向是：

```text
Harness Candidate + ReviewDecision + PublishAuthorization
→ WeKnora preparation
→ WeKnora atomic activation/CAS
→ WeKnora sole serving Active Head
→ pinned page/payload/retrieval
```

Harness 不保存第二个 serving Active Head。跨系统发布、不可变物化、digest、
幂等、CAS 和 receipt 仍然必须实现；被取消的是双 Active、长期 freshness、
迟到投影写和两个 serving authority 之间的 reconciliation。

## 2. 当前状态与目标状态必须分开

当前仓库尚未实现目标 Release Kernel。旧 018
`current_release / ReleaseSnapshot / SnapshotReader / publisher /
reconciliation` 代码与迁移仍存在，但没有注册进 P3 Worker 的生产 Handler。
它们只保留作审计和定向移植输入，不构成当前线上 serving authority。

当前运行态命名为 `NO_PRODUCTION_ACTIVE_RELEASE`。旧 publisher 的公开导出和
测试覆盖不改变该状态；在目标 Kernel 与正式 principal/ACL/Artifact 门禁闭合前，
不得把其接入生产 Handler。S0-R 仅能在隔离测试 Space/凭据下产生
`EXPERIMENTAL` 证据，不能直接升级为 `ACTIVE`。

治理文档可以立即冻结目标方向，但不得把目标设计写成已实现能力。

## 3. 能力处置

| 档位 | 能力 |
|---|---|
| KEEP | Job Store、Outbox、API/Worker Shell、W1、Source lifecycle、Canonical Envelope、Capacity、ProductVersion Resolver、TemplatePackage、弱模型边界 |
| REWIRE ON DEMAND | 首个纵切实际调用的 SourceRevision、Evidence/Review、Space binding 和 Release client 入口 |
| SUPERSEDE / FREEZE | 旧 `current_release` pointer、SnapshotReader serving 语义、逐页补偿、reconciliation、managed-page epoch high-watermark |
| DEFER | ChangeProposal、Proposal Edit UX、完整修改历史、Feedback Flywheel、Concept/Sense、machine_auto |
| DELETE LATER | P12 双系统 Projector 能力；替代合同冻结前不删除或改名 `wiki_projector` principal |

通过 S0-R/S0-Q 后也只改接第一个真实纵切调用的入口。旧 publisher、reader、
表和 migration 可以继续冻结留存；物理清理是 MVP 后独立任务。

## 4. 043 处置

OpenSpec 043 保留以下安全合同：

- P3-derived Space 与 fail-closed principal；
- append-only binding version 与 current epoch；
- RAW/Wiki ACL 等价、跨 Space 拒绝；
- stale/ABA/concurrency 防护；
- 认证、adapter 或事务失败零写。

043 当前的 `wiki_projector`、单 RAW/Wiki binding 和旧投影语义不得原样进入实现。
状态改为：

```text
SPEC-ONLY / REQUIRES AMENDMENT AFTER S0-R
```

S0-R 编码前必须在其独立 OpenSpec 中冻结暂定最小发布 principal、单值
`raw_kb_id`/`release_managed_wiki_kb_id` binding、`PublishAuthorization`
canonical bytes/nonce/校验顺序/失败零写及最小 read/ACL 协议。S0-R 通过后才把
验证过的合同写入 043 Amendment；失败则废止该暂定合同。MVP 使用单 RAW KB +
单 release-managed Wiki KB；未来多 RAW 必须另开 ADR/OpenSpec/migration，
企业 cardinality 保持可演进。

## 5. 045 处置

045 的身份与状态分开记录：

- upstream capability：`80a5003cc99a427098afe184eee6601916d3d156`；
- image build source：`a8bf55ae18441abd380e594afba5000c51cc9633`；
- current main：`529d72c994369750b26e352a70fd6284e8b0fd9d`；
- source adoption、legacy `000066` bridge、trusted images 和 digest pin：
  `COMPLETE`；
- Full Artifact/W1 runtime probes：`OPEN`；
- `source_reader` authority：`BLOCKED`。

不再比较 `v0.7.1` 与 `80a5003` 以重新选择版本。下一步只填已采用
`80a5003` 的 Release capability gap matrix。

## 6. S0-Q 输入纪律

S0-Q 不接正式 Release，但输入必须来自：

- 当前 `80a5003` WeKnora 的冻结解析输出与 W1 Revision Manifest；或
- 身份、digest、页码、表格结构和解析版本完全冻结的等价制品。

禁止先把 PDF 人工整理成干净 Markdown 再测抽取。候选区域定位、复杂表格和
Evidence 锚定属于 S0-Q 必须保留的真实难度。

## 7. 唯一执行顺序

```text
Mission 0 治理纠偏
├── 80a5003 Release capability gap matrix → S0-R
└── S0-Q 立即并行
           ↓
S0-R PASS AND S0-Q PASS
           ↓
MVP 纵向闭环
           ↓
按需改接线；legacy 物理清理后置
```

不存在前置的全量 legacy 重接线 Mission。S0-R 是两工作日证伪窗口，不是生产
Kernel 交付期限；S0-Q 是窄切片可行性，不是质量批准。

S0-R Mission Card 必须在计时前冻结 exact fork 路径、表/索引、migration、
read surface、升级责任和验证命令预算；超出任一预算即输出
`RELEASE_PATH_NOT_FEASIBLE`。最小 fixture 必须用 R0(A/B/C) →
R1(A 更新/B 删除/C 不变/D 新增)、同 base 双 Candidate 竞争、preparation/
index/CAS/receipt 失败注入、并发 pinned/current read，以及两个 principal 下的
ACL shrink 证明集合级原子性与权限收缩。单页成功 Demo 不得判定 feasible。

## 8. MVP 前十条合同的最小解释

“关闭合同”不等于建设十套企业平台：

- retention/legal erasure 在 MVP 可采用明确的 fail-closed serviceability、
  rollbackability 与 tombstone 规则，不建设完整运营系统；
- canonical serialization 只实现 Python/Go 共用 vectors 和必要 adapter，不建设
  通用序列化平台；
- 多 RAW KB、完整修改历史、machine_auto 和企业规模能力继续后置。

每个 MVP PR 必须交付一个可演示的纵向用户价值，不能按 Source、Schema、审核、
发布等横向层依次建设完整框架。

## 9. 本修订不授权

- 任何功能代码或 migration；
- S0-R/S0-Q 实现；
- P2d/043 实现；
- principal 删除、改名或扩权；
- legacy 表、migration 或历史代码清理；
- 将 WeKnora 单页历史解释为整版 Release；
- 将镜像 digest pin 解释为 Full Artifact closure。
