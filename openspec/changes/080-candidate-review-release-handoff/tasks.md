# 080 · Implementation Tasks

## T1 · Contract

- [x] Freeze the one-Candidate, three-projection authority boundary.
- [x] Freeze preparation-only authority and explicit human-decision absence.
- [x] Keep the registry and upstream 059/076/077 paths out of scope.

## T2 · Focused RED

- [x] Prove the missing task-local handoff module.
- [x] Cover the synthetic happy path and deterministic replay.
- [x] Cover Candidate, Evidence/FieldFact, ChangeSet, manifest/member, policy and scope drift.
- [x] Prove failure returns no partial output and imports no external-operation surface.

## T3 · Minimal GREEN

- [x] Compose the existing 076 and 077 builders without duplicating their validators.
- [x] Build one immutable 059 preparation-input vector with no human authority.
- [x] Cross-validate all three projections and freeze one domain hash.

## T4 · Verification and freeze

- [x] Focused 080 and bounded 057/058/059/076/077 tests.
- [x] Ruff, strict mypy, OpenSpec strict, diff-check, exact-six-path and privacy gates.
- [x] Freeze an exact candidate tree without commit, push or PR.

## Stop conditions

- Original 057 locator custody or complete 076 base authority is unavailable.
- A decision/signature/Ready/Release/Head or external operation would be required.
- Any seventh owner path is required.
