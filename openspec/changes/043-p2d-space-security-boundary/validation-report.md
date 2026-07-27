# 043 Validation Report

> 状态：spec-only candidate；implementation、migration 与 PostgreSQL 16
> acceptance 均未运行。最终 local candidate tree 由于本文件自引用，由
> 交接消息在最后一次门禁后报告。

## Candidate identity

- Required base / actual base:
  `40f3ae9e4b41fab51566c438da08c57d80e3089b`
- Branch: `codex/043-p2d-space-security-boundary-spec`
- Worktree label: `.worktrees/043-p2d-space-security-boundary-spec`
- Scope: OpenSpec/plan/README only; zero production code, zero migration file.

## Authority reading

- Fully read: repo `AGENTS.md`/`CLAUDE.md`; approved production architecture;
  north-star; HANDOFF current block; control board; active execution plan;
  amendment; OpenSpec 033/C0/P3; legacy asset disposition; current
  KnowledgeSpace/scope and 027 model gate contracts; W0/W1 ACL evidence.
- Dependency finding: OpenSpec 039 P3 implementation/ACL-inspection authority
  are not in main. Current P1 only exposes a mutating `heartbeat`, not the
  read-only active-fence verifier required for authorization-failure zero-write.
  P2d implementation remains explicitly blocked on both owners; this spec does
  not pretend either dependency is met.
- Current ACL finding: W0 proves WeKnora ACL granularity is KB whitelist ×
  capability and no Source/knowledge ACL exists. P2d therefore freezes
  `acl_scope_unsupported` for any future narrower Source/File ACL and excludes
  per-Claim visibility.

## Spec-only evidence

- Reservation order: OpenSpec README changed to reserve 043 before the 043
  directory existed; command evidence printed
  `043_DIRECTORY_ABSENT_AFTER_RESERVATION`.
- Migration custody: README reserves id 0016 for P2d, but no migration file is
  created; future down_revision must use implementation-time main single head.
- Selected design: append-only binding/profile versions + Space current
  pointers/epochs + one Space row serialization boundary.
- Rejected alternatives: mutable JSON on Space, external-only authority, and
  per-Claim ACL propagation.

## Review findings

- Independent Spec initial: `1C/4I/1M`, NOT APPROVED. Corrected:
  live WeKnora ACL/freshness pre-call recheck; explicit P3 ACL-inspection
  authority blocker; durable receipts for no-op/deactivate; opaque verified
  security-adapter attestations; P2d-only read guard with P11/P9/P13 endpoint
  enforcement deferred; closed state_reason mapping.
- Spec corrective: `0C/1I/0M`. The remaining finding showed a constructible
  `ClaimedJob` snapshot could outlive its P1 lease. Corrected by requiring a
  P1-owned read-only active-fence verifier over current generation/`running`/
  attempt/DB-clock-unexpired lease immediately before dispatch, plus reclaim/
  expiry interleavings.
- Current owner audit: found the draft still allowed mutating
  `JobStore.heartbeat` as that verifier and lacked an exact API/principal/Worker
  operation matrix. Corrected with P2D.13: exact role/Worker authority, handler-
  before-auth prohibition, failure zero-write/zero-transport, explicit
  non-active-observation separation, and a new P1 read-only dependency blocker.
  A second audit closed no-op/deactivate cross-actor replay by binding mutation
  request hashes and receipts to an exact P3 actor/P1 Worker authority snapshot.
- Spec final: **`0C/0I/0M`**.
- Independent Plan initial: `0C/2I/0M`. Corrected to an exact 14-path,
  checkbox-sized RED→GREEN plan with PG RED nodes alongside each transaction
  task and removed the conditional `model_policy` edit.
- Plan corrective: `0C/2I/1M`. Corrected untracked-file/LOC custody using
  intent-to-add + tracked/untracked union, added the explicit PG no-op/
  deactivate receipt replay node, and replaced broad selectors with exact node
  ids plus exact JUnit guards.
- Plan final: **`0C/0I/0M`**.
- C/I/M self-review: **`0C/0I/0M`**.

## Current finding classification

- **BLOCKER (closed in this spec):** three—missing API/principal/Worker operation
  matrix; mutating heartbeat accepted as an authorization verifier; mutation
  idempotency not bound to the exact actor/Worker authority.
- **BLOCKER (implementation preconditions, intentionally open):** P3
  implementation plus P3-owned ACL-inspection authority, and a P1-owned public
  read-only active-fence verifier. These block production implementation, not
  this spec-only delivery.
- **BACKLOG:** none added by this Mission Card.
- **REJECTED:** per-Claim visibility propagation, a third service principal,
  P2d-owned job/fence implementation, provider/DLP/KMS platform work, endpoint
  implementation, historical cleanup, and Tencent/WeKnora upstream debt.

## Gates

- Strict OpenSpec final post-report rerun: **PASS**, exit 0. The CLI emitted
  best-effort PostHog network-flush noise only after reporting
  `Change '043-p2d-space-security-boundary' is valid`; validation did not fail.
- Exact scope: **PASS**, six documentation paths only: OpenSpec README, 043
  proposal/tasks/spec/validation report, and one future implementation plan.
  No runtime path and no `0016` migration file exists.
- `git diff --check`: **PASS**. Real index empty: **PASS**.
- High-confidence private-key/credential/JWT/credential-URI/value scan and
  conflict-marker scan: **PASS**, six paths / zero findings.
- UTF-8 validity, LF-only line endings and final LF: **PASS**, six paths.
- Final candidate was frozen through a temporary index; its exact tree hash and
  path list are reported externally after the last gate to avoid
  validation-report self-reference.
- Feature/full/provider/model/live/PostgreSQL 16: **NOT RUN by mission**.
- PG16 acceptance remains a future implementation requirement, not a
  spec-lane PASS claim.

## Scope exclusions confirmed

Provider implementation, per-Claim ACL, DLP/KMS platform, P11 managed-page
patch, Candidate/promotion implementation, historical cleanup, and
Tencent/WeKnora upstream debt are explicitly excluded.
