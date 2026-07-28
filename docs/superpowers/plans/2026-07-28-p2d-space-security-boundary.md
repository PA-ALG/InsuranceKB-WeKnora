# P2d Space Boundary Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans` to
> implement this plan task-by-task.

**Goal:** Implement one Space-scoped RAW/Wiki ACL equivalence boundary with
immutable current binding/epoch and failure-zero-write semantics.

**Architecture:** P2d consumes P3-derived principal/Space and a separately
approved P3 ACL inspection authority. PostgreSQL stores append-only binding
versions and serializes current pointer/epoch changes on the Space row. This
plan does not implement security profiles, provider authorization, P1 fencing
or Candidate/Release integration.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16,
pytest, OpenSpec.

---

## Preconditions

Do not start implementation until all are true:

- P3 implementation is merged;
- a separate P3 Mission has merged the least-privilege RAW/Wiki ACL inspection
  authority or approved authenticated-human delegation;
- a new P2d Mission Card authorizes implementation;
- the worktree starts from fresh `origin/main`;
- the actual Alembic head and available migration id are recorded.

P1 active-fence, provider dispatch and CompilationSecurityProfile are not
preconditions because they are not part of this foundation slice.

## Frozen path budget

The implementation Mission may refine exact names, but must remain within one
migration, one focused P2d package, focused tests and 043 evidence. Target:
≤12 logical paths. A second migration, a provider SDK, P1 jobs changes,
Candidate/Release changes or a 13th path stops the task for a new Mission.

### Task 1: Dependency and RED contract

**Files:**

- Modify: `openspec/changes/043-p2d-space-security-boundary/tasks.md`
- Test: focused P2d deterministic tests chosen by the implementation Mission

- [ ] Verify P3 public imports for principal, derived Space and ACL inspection.
- [ ] Write RED for caller Space/role spoofing and missing inspection authority.
- [ ] Write RED for stable/equivalent ACL admission and non-active outcomes.
- [ ] Write RED for current RAW ACL revocation returning zero payload.
- [ ] Run focused tests and record the expected failures.

### Task 2: Immutable binding schema

**Files:**

- Create: one migration from the actual main head
- Create/Modify: minimal P2d ORM models
- Test: focused migration and schema tests

- [ ] RED append-only version, same-Space pointer and unique current RAW/Wiki
  mapping constraints.
- [ ] RED legacy `bound` remaining unavailable after upgrade.
- [ ] RED UPDATE/DELETE guards and cross-Space direct-SQL attempts.
- [ ] Implement only binding version and current pointer/epoch.
- [ ] Verify upgrade/downgrade policy and single Alembic head in PostgreSQL 16.

### Task 3: Admission and reconciliation transaction

**Files:**

- Create/Modify: minimal P2d binding service and ACL adapter port
- Test: focused domain and PostgreSQL concurrency tests

- [ ] RED two stable reads, canonical ACL equality and identity joins.
- [ ] RED mismatch, unsupported granularity, unavailable observation and
  adapter/runtime failures.
- [ ] RED no-op reconciliation, stale pointer/epoch, ABA and concurrent writers.
- [ ] Implement Space-row lock → authority recheck → ACL observation → immutable
  version → pointer/epoch CAS as one transaction.
- [ ] Prove unauthorized/cross-Space/adapter/DB failures write zero P2d/P1/domain
  rows and perform no mutation transport.

### Task 4: Current read guard

**Files:**

- Create/Modify: minimal read-only current binding guard
- Test: guard plus fake-consumer contract tests

- [ ] RED P3 role + exact Space + active current binding + current RAW ACL.
- [ ] RED revoked RAW ACL, non-active current, stale epoch and cross-Space input.
- [ ] Implement verdict-only guard; no knowledge payload, provider capability or
  durable authorization receipt.
- [ ] Confirm real Query/Wiki/MCP/search/cache wiring remains absent.

### Task 5: Verification and handoff

- [ ] Run focused deterministic tests, Ruff and strict mypy.
- [ ] Run PostgreSQL 16 migration/concurrency suite with `skipped=0`.
- [ ] Run `openspec validate 043-p2d-space-security-boundary --strict`.
- [ ] Run diff-check, exact scope, private/secret and UTF-8/LF scans.
- [ ] Confirm no P1/provider/security-profile/Candidate/Release/WeKnora patch.
- [ ] Obtain independent Spec and Quality/Security approval.
- [ ] Update only 043 tasks/validation evidence authorized by the Mission.
