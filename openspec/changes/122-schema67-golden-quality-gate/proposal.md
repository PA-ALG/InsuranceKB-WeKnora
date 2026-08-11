# 122 · Schema67 596-1 Golden Quality Gate

## Goal

Freeze a product-specific canonical Golden Set and semantic admission contract for the
67-field Ping An eShengBao medical-insurance Candidate. The gate runs after a new concrete
sealed Candidate exists and before any Schema Wiki Draft or review dossier can be created.

Current semantic quality is `INCONCLUSIVE`. The provider-zero `45/1/21` fixture is contract
evidence only. The previous official exact8 run failed and produced no Candidate; this
change does not rerun or reinterpret it.

## Scope

- One closed `Schema67GoldenSet5961V1` with exactly the ordered medical 67 fields.
- Per-field tri-state, accepted values/normalization, exact committed source revision,
  page/locator/quote and optional typed bbox authority.
- Two independent named-human annotation passes, named adjudication and immutable
  whole-batch Golden custody.
- Deterministic metric definitions, denominators, small-sample reporting, thresholds and
  STOP rules.
- A future candidate-bound PASS-only quality receipt inserted between Candidate creation
  and Schema Wiki Draft creation.
- One preparation-pinned evaluation review bundle containing the signed PASS receipt, the
  redacted public aggregate and the private ordered-67 dossier. The bundle is stored only
  inside the existing canonical Schema Wiki preparation custody/manifest; it adds no
  table, Head, CAS or serving authority.
- Read-only, preparation/evaluation-pinned summary, dossier and Evidence-preview routes.
  The summary is aggregate-only but remains a human-JWT Admin/Owner preparation surface;
  the dossier additionally requires the authenticated named reviewer. Both traverse the
  existing Wiki/RAW dual ACL and release seal.

## Authority boundaries

- The canonical Golden is independent human authority. The evaluated model cannot create
  or adjudicate its own Golden.
- The existing CandidateV2 wire remains unchanged.
- A quality receipt cannot approve a Candidate; it only proves the frozen quality gate
  outcome. Existing named-human release review and separate publish authorization remain
  mandatory.
- The evaluation review surface cannot approve, review, publish or activate anything.
  Its `public` aggregate means redacted content, not anonymous or Viewer access to a
  pre-activation preparation.
- Generic Material Wiki content and provider-zero fixtures cannot supply Golden answers,
  Evidence or quality metrics.
- The gate is specific to product version `596-1`; it is not a general evaluation platform
  or model admission service.

## Current delivery boundary

This successor is a plan/OpenSpec-only review-surface contract over the already frozen
corrective evaluator. It performs no provider, Golden generation/scoring, database,
WeKnora, migration, Draft, review, activation or deployment action and does not implement
the HTTP surface.
