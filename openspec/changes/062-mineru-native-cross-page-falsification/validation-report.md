# 062 validation report

## Identity

- Base: `80fa4fbb2711503625e1854fd9b2a892e09c94d4`
- Scope ceiling: 9 paths
- Real provider capture: `NOT RUN`

## RED/GREEN evidence

- Initial RED: focused compile failed because the projection/status/target identities did not exist.
- Corrective RED: both section/table boolean-marker fixtures returned PRESENT with synthesized
  adjacent page endpoints and relation hashes; capture evidence reproduced the same violation.
- Corrective GREEN: current `cross_page` and `lines_deleted` booleans both return AMBIGUOUS,
  hashed observation only, `relation_count=0`; clean middle is ABSENT and missing middle is
  NOT_AVAILABLE. Adjacency/header/HTML cannot mint a relation.
- ZIP-boundary RED: symlink and named-pipe members named `result_middle.json` were both
  accepted, and the capture download had no bounded-body helper before projection.
- ZIP-boundary GREEN: only regular files/directories are accepted; capture-only response reads
  stop at the fixed compressed budget plus one byte and reject overflow with a typed error.
- GREEN: 12 top-level affected 061/062 capture/converter tests passed.
- Affected evidence also covers hostile ZIP, privacy, determinism, exact two-source identity,
  converter capture-only seam, atomic no-replace and real blocked-ZIP deadline.
- An exploratory whole-package run was not used as a gate: an unrelated pre-existing
  `httptest` image test could not bind IPv6 inside the sandbox. The approved affected set did
  not require a listener and passed.

## Gates

- Focused Go tests: `PASS`
- Go vet (`internal/infrastructure/docparser`): `PASS`
- OpenSpec 062 strict: `VALID` (telemetry flush was unavailable and non-gating)
- diff-check/exact 9-path scope/private/secret: `PASS`
- full/provider/live/PG/DB/WeKnora/Golden: `NOT RUN`
