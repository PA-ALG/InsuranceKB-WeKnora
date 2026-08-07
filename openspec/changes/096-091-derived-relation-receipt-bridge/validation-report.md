# 096 Validation Report

Status: `STABLE CANDIDATE / NOT COMMITTED`

- Base/HEAD: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`.
- Stacked identities: 091 tree `405393826eeceb881e1f713cef42069c97e922cf`,
  086 tree `ee48922b0804355b73b52df2e4e9e73d2e03870b`, 092 tree
  `49efbd12084e8069c7a06364ac4835e0bb4e1e86`.
- Actual-interface finding: 091 exposes typed marker node metadata and custody
  hashes, but the current one-node observation does not authorize both endpoints.
  Production derivation must therefore block without writing a receipt.
- Genuine RED: focused collection failed with `ModuleNotFoundError` before the
  task-local bridge existed.
- Focused 096: 20 passed. Bounded 083+096: 86 passed. Frozen 086 public binding
  replay counterexample: 1 passed.
- Targeted Go 091 same-read custody tests: package pass.
- The frozen pre-091 086/092 synthetic fixtures omit the now-required marker
  envelope; their earlier combined stack baseline was 67 passed / 22 failed.
  They are not represented as a current green gate and are not modified by 096.
- Ruff: pass. Strict mypy: 3 files, no issues. OpenSpec 096 strict: valid.
  Diff-check: pass. Exact 096 scope: eight paths. Private/secret scan: pass.
- The current 091 terms evidence remains honestly
  `BLOCKED_ON_CROSS_PAGE_BINDING`; no receipt was written. Synthetic complete
  verified 086 bindings prove exact terms/rate_table receipt replay and private
  atomic no-replace publication without introducing a caller authority API.
- Provider/model/Golden/DB/WeKnora/live/PG/full: NOT RUN / FORBIDDEN.

No NATIVE, ADMIT, READY, commit, push or PR authority is claimed by this candidate.
