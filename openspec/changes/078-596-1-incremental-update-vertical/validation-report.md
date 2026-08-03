# Validation Report

Status: corrective owner checkpoint; not committed or delivered

## Identity

- Coordination base: `dc80a143ed4f6d315fe775f70eb52c448c95816d`
- Owner branch: `codex/078-596-1-incremental-update-vertical`
- Owner paths: exact seven paths defined by the approved plan

## Evidence

- OpenSpec initial incomplete-spec RED: strict validation rejected the missing
  delta section and scenarios, as required by the approved plan
- Focused module-missing RED: pytest collection failed with
  `ModuleNotFoundError` for the not-yet-created 078 module
- Focused authority-extra RED: the pre-corrective runner silently ignored an
  extra authority object and the exact negative test failed `DID NOT RAISE`
- Independent review reproduced three input-authority blockers in the prior
  tree: movable field/action partition, runner-generated custody/baseline, and
  order-dependent fixture hash. That prior tree is not a delivery candidate.
- Corrective RED: the three direct regressions failed respectively with
  `DID NOT RAISE`, unequal fixture hashes, and a missing public `preimage`
  parameter.
- First corrective GREEN: focused `31 passed`; exact field/action and
  affected-order tests pass.
- Caller-custody mutations cover missing/extra/recomputed baseline facts plus
  missing/extra/drifted 053/054/057 objects, all before Candidate assembly.
- Second adversarial review reproduced three additional recomputed bypasses:
  self-consistent replacement Schema60, replacement 057 candidate with rebuilt
  PASS/link/054 receipt, and replacement retraction proof/link without a bound
  explicit-absence Evidence chain. The predecessor tree is not a delivery
  candidate.
- Second corrective RED: the three regressions failed on the missing exact60
  authority constant, missing `field_candidates`, and missing independent
  `retraction_verification_link`.
- Second corrective GREEN: focused `37 passed`; all three fully recomputed
  substitutions fail before Candidate/HumanBatch while the happy replay passes.
- Bounded 052/053/057/058/059 plus 078 regression: `197 passed`
- Ruff exact source/test: pass
- strict mypy exact source/test: pass
- OpenSpec 078 strict: pass
- diff-check, exact-seven scope, private-path and high-signal secret scans:
  pass
- Provider/model, Golden values, DB/PostgreSQL, WeKnora, Release, live, and
  migration: `NOT RUN / FORBIDDEN`

## Contract Result

- Exact synthetic partition: 60 fields = 4 affected + 56 unchanged
- Exact field/action mapping is frozen; equivalent fixture and preimage order
  produces the same fixture, preimage, and final receipt hashes
- The runner pins the approved ordered Schema60 hash and consumes/replays
  caller-provided 053/054/057 candidate/Evidence custody, baseline hashes,
  candidate facts, and an independently verified explicit-absence retraction
  chain; it does not mint them
- ChangeSet actions: exactly one `enrich`, `supersede`, `conflict`, and
  `retract`; no `add`
- The 56 unchanged fact hashes remain outside ChangeSet, Candidate changes,
  and HumanBatch items
- Conflict retains both facts and Evidence; retract retains its prior fact and
  carries no physical-deletion action
- Candidate/HumanBatch authority remains `NONE_REQUIRES_NAMED_HUMAN`; the 078
  receipt remains fixture-only and grants no Release authority
