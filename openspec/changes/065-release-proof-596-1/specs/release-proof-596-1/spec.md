# 596-1 Release proof runner specification

## ADDED Requirements

### Requirement: RPR1 external authority and exact identity only

The runner SHALL accept caller-supplied canonical human decision and publish/revert authorization
bytes plus exact lowercase SHA-256 values for candidate, human batch, review policy, release,
artifact and human receipt. Before any Release method it SHALL verify hash shape, closed canonical
envelopes, signatures and every action/scope/preparation/nonce/expected-Head binding. Immediately
after `Prepare` and before activation
it SHALL compare the 059-computed immutable manifest digest with the exact preparation manifest.
The supplied release/artifact hashes are the upstream 049 Golden identity and SHALL be bound into
the proof receipt without being reinterpreted as a 059 Wiki manifest/member digest. The runner SHALL
NOT mint, sign, default, repair or infer any human decision or authorization.

#### Scenario: authority or hash is absent or malformed

- **WHEN** any required authority envelope is absent or any declared hash is not exact lowercase
  SHA-256
- **THEN** the run fails typed before any prepare, activate, revert or read call

### Requirement: RPR2 exact Release and CAS sequence

The runner SHALL use the existing 059 service/repository semantics to execute Head
`none -> R0/e1 -> R1/e2 -> R0/e3`. Every real activation and revert SHALL bind the exact observed
expected release and epoch. Because external PostgreSQL is outside this run, bounded concurrency
falsification SHALL use one task-local deterministic CAS fake with both contenders at one barrier.
It SHALL produce exactly one winner and one typed conflict, and the proof receipt SHALL state
`DETERMINISTIC_CONCURRENCY_PROOF_NOT_PG`. The existing 059 service/repository SHALL separately execute
the real revert and prove R0/e3 plus five-table custody. PostgreSQL concurrency remains a later
external proof and SHALL NOT be inferred from this run.

#### Scenario: stale or concurrent contender

- **WHEN** two operations use the same expected Head or one uses a stale Head
- **THEN** the deterministic proof has one winner/one typed loser, the real 059 revert advances once,
  and real Release/member counts remain unchanged

### Requirement: RPR3 pinned reads and current ACL

The runner SHALL begin one opaque pinned read at request start. That pin SHALL continue reading its
immutable Release after Head advances, while every read SHALL recheck current dual ACL and deny
immediately after ACL shrink.

#### Scenario: Head changes and ACL shrinks

- **WHEN** a read is pinned at R0, Head advances to R1, and then the caller loses current access
- **THEN** the pin still identifies R0 but the next read is denied without falling through to R1

### Requirement: RPR4 immutable same-scope revert and rollback

Revert SHALL CAS Head only to an existing immutable historical Release in the same exact scope,
increment epoch once, and create no Release or member. Injected activate/revert transaction faults
SHALL roll back Head, Release, member and receipt changes without a half-write.

#### Scenario: revert R1 to R0

- **WHEN** a valid revert authorization binds R1/e2 and historical R0
- **THEN** Head becomes R0/e3 while Release/member counts remain unchanged and one immutable revert
  receipt records the transition

### Requirement: RPR5 privacy-safe C0 proof receipt

The runner SHALL emit a closed proof receipt that binds every injected input hash, the four Head
observations (`none/e0`, `R0/e1`, `R1/e2`, `R0/e3`), operation results and initial/after-R1/
after-revert/after-rollback table counts. Its fixed scalar/map/list subset SHALL use
CanonicalEnvelopeV1 domain separation and SHALL be checked against an independent frozen Go fixture;
065 SHALL NOT create a general Go canonicalization package. The receipt SHALL omit content, payload,
secret, raw signatures and complete principal/tenant/Space/KB identifiers.

#### Scenario: stable proof

- **WHEN** the same inputs and deterministic transaction observations are supplied twice
- **THEN** canonical receipt bytes and the C0 digest are byte-for-byte identical; changing any
  bound hash or count changes the digest

### Requirement: RPR6 bounded task-local delivery

065 SHALL change at most six task-local documentation/command/test paths and SHALL not modify the
production 059 API, handler, repository, types, migration, router or signing configuration. It
SHALL not run provider, live, external PG, WeKnora or full tests.

#### Scenario: production change is required

- **WHEN** implementation cannot satisfy RPR1-RPR5 through the merged 059 public surface
- **THEN** work stops with a blocker instead of expanding the change
