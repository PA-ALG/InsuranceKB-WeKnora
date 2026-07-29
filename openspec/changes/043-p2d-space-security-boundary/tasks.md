# 043 · Tasks（P2d Space Boundary Foundation）

> [!WARNING]
> `SPEC-ONLY / REQUIRES AMENDMENT AFTER S0-R`。以下 Contract Card 保留通用
> Space/ACL/epoch/跨 Space/零写边界，但不授权按旧 `wiki_projector` 或单
> RAW/Wiki projection binding 实现。S0-R PASS 前不得创建 migration 0016。

## Contract Card

### 单一职责

冻结一个 Space 的 P3-derived scope、RAW/Wiki ACL 等价 admission /
reconciliation、不可变 current binding/epoch、跨 Space拒绝和失败零写。

### Authority 与事务

- principal、角色、derived Space 与 ACL inspection authority 归 P3；
- binding version 与 current pointer/epoch 归 P2d；
- PostgreSQL current Space row 是 mutation 串行/CAS 边界；
- WeKnora ACL 只经 P3-approved read authority 观察；
- caller fields、历史 digest、service principal 扩权均不构成 authority。

### 状态

```text
none/current → active | acl_mismatch | acl_scope_unsupported |
               verification_unavailable | disabled
```

只有已授权、可证明 observation 可提交状态；adapter/DB/认证失败零写。

### 主要威胁

| 威胁 | 冻结防线 |
|---|---|
| caller 自报 Space/role | 只消费 P3 principal 与 derived Space |
| RAW/Wiki ACL 不等价 | 稳定双读 + versioned mapping + canonical digest |
| 历史 active/legacy bound 被复用 | current pointer + monotonic epoch |
| stale/ABA/concurrent mutation | Space row lock + expected pointer/epoch CAS |
| cross-Space object/pointer | service exact join + DB composite FK/unique |
| adapter/DB 失败写入半状态 | 单事务 rollback；失败零 version/pointer/epoch |
| P2d 自建 ACL authority | 实现阻断，先完成独立 P3 amendment |

### 非目标

CompilationSecurityProfile、provider/P1 active-fence、DLP/KMS、Candidate/
promotion snapshot、Release/Query、逐 Claim ACL、P3/P1 实现、真实 WeKnora
patch 均移入后续 Mission Card。

### 未来实现预算

- 最多一个 migration，从实现时 actual Alembic head 接续；
- 目标 ≤12 logical paths；
- PostgreSQL 16 覆盖 migration、immutability、CAS concurrency、
  cross-Space 与 failure rollback；
- 超预算或出现后续领域即停机拆分。

## 当前 spec-only 清单

- [x] S1 从 exact
  `origin/main=40f3ae9e4b41fab51566c438da08c57d80e3089b` 创建独立 worktree；
- [x] S2 冻结 P3-derived Space、ACL equivalence、binding/epoch、cross-Space
  与 failure zero-write 合同；
- [x] S3 将 security profile、provider/P1 fence、Candidate/promotion 等移出
  043，记录为后续 Mission；
- [x] S4 记录 P3 ACL inspection authority 是唯一实现前置缺口；
- [x] S5 运行 strict OpenSpec、diff/scope/private/secret 与 UTF-8/LF 门禁；
- [x] S6 更新 validation report 与 corrective 交接证据。

## 未来实现清单（BLOCKED ON P3 ACL INSPECTION AUTHORITY）

- [ ] I0 独立 P3 Mission 冻结并合入 least-privilege ACL inspection authority；
- [ ] I1 获新 Mission Card，从最新 main/actual Alembic head 建独立 worktree；
- [ ] I2 RED：P3 scope、ACL stability/equivalence、cross-Space、zero-write；
- [ ] I3 RED：immutable version、pointer/epoch、no-op 与 CAS concurrency；
- [ ] I4 GREEN：唯一 migration + 最小 P2d binding package；
- [ ] I5 focused/Ruff/mypy/OpenSpec + PostgreSQL 16 `skipped=0`；
- [ ] I6 独立 Spec 与 Quality/Security review 后再决定 Ready。
