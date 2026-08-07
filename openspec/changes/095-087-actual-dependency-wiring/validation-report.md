# 095 Validation Report

Status: `STABLE STACKED CANDIDATE / NOT COMMITTED`

- Base/HEAD: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`.
- Frozen dependencies: 087 `cda609d0`, 091 `40539382`, 092 `49efbd12`,
  096 `11867ea8`.
- Exact 096 public replay signature is `(receipt) -> DerivedRelationReceipt5961V1`.
  It neither accepts 0600 receipt bytes nor supplies the source-authority,
  material-profile and marker-map inputs required by 092. The production resolver
  therefore returns `DEPENDENCY_UNAVAILABLE` before file I/O. The focused synthetic
  port proves the complete 083 -> 096/086 -> 092 composition graph without claiming
  real MinerU readiness or inventing authority.
- Provider/model/Golden/DB/WeKnora/live/full/PG: `NOT RUN / FORBIDDEN`.

## Verification

- Genuine RED: the 095 module was absent before implementation; dependency and
  private-file tests then established the pre-I/O and custody boundaries.
- Focused 095: `19 passed`.
- Bounded 087 + 083/091 intake + 096 + 095: `119 passed`.
- Ruff: `PASS`; strict mypy: `2 source files / no issues`.
- `openspec validate 095-087-actual-dependency-wiring --strict`: `valid`.
- Candidate-vs-base `git diff --check`: `PASS`.
- Exact 095-owned scope: seven paths (registry, four OpenSpec documents, adapter,
  focused test). 087/091/092/096 candidate blobs are inherited unchanged.
- Privacy/secret inspection: only the deliberate malicious exception fixture contains
  synthetic secret/URL/path-shaped text; the public result asserts that none survives.
- The local repeat of the inherited Go 091 custody tests and package vet was stopped
  during first-use private-cache compilation with no test output. This is not represented
  as a fresh pass. Frozen 091/096 evidence already records the targeted same-read custody
  package pass; 095 changes no Go path.
- The frozen pre-091 086/092 synthetic fixtures omit the now-required 091 marker
  envelope and have a known upstream `22 failed` baseline. They are not a current 095
  green gate and were not modified to manufacture compatibility.

The exact stacked candidate tree and one-use temp-index SHA are held externally with the
handoff so the candidate does not self-reference its own identity.
