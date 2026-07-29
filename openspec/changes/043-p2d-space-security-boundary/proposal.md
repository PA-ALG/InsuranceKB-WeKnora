# 043 · P2d Space Boundary Foundation

## 状态

`SPEC-ONLY / REQUIRES AMENDMENT AFTER S0-R`

本 change 只冻结 Space 边界的最小实现合同，不表示 P2d 已实现，也不授权生产
代码或 migration。实现须另获 Mission Card，并从当时最新 main 开始。

2026-07-29 Authority Amendment 2 保留本 change 的 Space、principal
fail-closed、binding epoch、ACL、跨 Space 拒绝、ABA/concurrency 与失败零写
合同；当前 `wiki_projector`、单 RAW/Wiki projection binding 和旧发布语义不得
原样进入实现。S0-R PASS 后必须用已验证的发布 principal、MVP binding 与
Release 协议修订本 change，预留 migration 0016 在此之前不得创建。

MVP 暂定 `1 Space = 1 RAW KB + 1 release-managed Wiki KB`。这是 MVP profile，
不是永久企业 cardinality。

## 用户价值

一个 LLM Wiki Space 只能绑定同一租户下、ACL 等价的 RAW KB 与 managed Wiki
KB。调用者不能靠自报 `space_id`、角色或跨 Space 对象让知识、ACL 状态或
current pointer 串域。

## 本 Change 冻结什么

1. **P3-derived scope**：P2d 只消费 P3 铸造的 human principal、角色与 derived
   Space scope；不复制身份、角色或 credential。
2. **ACL 等价准入**：RAW/Wiki KB 的 tenant、KB identity 与当前 ACL 经稳定
   读取和版本化 canonical mapping 后必须等价，才可形成 `active` binding。
3. **不可变 binding 版本**：每次有效 admit/reconcile/rebind/disable 产生
   append-only `KnowledgeSpaceBindingVersion`；Space 只以
   `current_binding_id + binding_epoch` 指向 current。
4. **持续 fail closed**：ACL mismatch、ACL 粒度不受支持、读取不可证明或
   binding disabled 均不得授予 current read authority。
5. **事务与隔离**：current pointer/epoch 切换按 exact Space 串行、CAS；
   cross-Space reference 与 stale expected pointer/epoch 均 typed 拒绝。
6. **失败零写**：未认证、权限不足、跨 Space、ACL adapter/DB 失败发生时，
   binding version、pointer、epoch、业务表和外部 transport 全部不变。

## 前置依赖

P3 Draft PR #58 已提供 principal、角色、derived Space guard 和 service
principal scope，但当前 039 public contract 不提供读取 RAW/Wiki 两端 ACL 的
least-privilege authority。P2d 实现开始前，须先由独立小 Mission 冻结并合入
该 P3-owned ACL inspection contract（或等价 authenticated human
delegation）。不得为此发明第三个 service principal，也不得由 P2d 持有
自建 admin credential。

## 明确移出本 Change

以下均为后续 `BACKLOG / NEW MISSION CARD`，不占 043 实现验收：

- `CompilationSecurityProfileVersion`、DLP/KMS、provider/model allowlist、
  residency、retention、renderer、logging 与 attestation；
- provider pre-call gate、P1 active-fence verifier、provider dispatch
  authorization 和旧 027 cutover；
- Candidate/Decision/promotion security snapshot；
- 通用 ACL 平台、逐 Source/File/Claim/Page ACL、P3 第三 principal；
- P3/P1 实现、P3 API、P1 Job Store、Release、Query、MCP、UI；
- 真实 WeKnora patch、provider/live 调用和历史路线清理。

## 未来实现预算

未来实现仍是一个 P2d 基础边界 PR：最多一个 migration，目标不超过 12 个
logical paths，并须用 PostgreSQL 16 覆盖 migration、并发 CAS、cross-Space、
immutability 和失败零写。超过预算或需要上述后续领域时停止并拆新 Mission，
不得把功能重新塞回 043。
