# 093 · Validation report

Status: `STABLE CANDIDATE / COMPATIBILITY BLOCKED / NOT COMMITTED`

## Identity

- Base/HEAD: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`
- Base tree: `4dac593a13dd9fb26bd2e08f99bc7c544f16b8cb`
- Branch: `codex/093-cross-page-authority-compatibility-replay`
- Scope budget: exact seven paths

## Preflight

- PA-ALG GitHub main matched the base; the 093 branch/path were absent.
- Open PR #115/#116 own 082/083 and do not overlap this task-local path set.
- Frozen 089/086/090 candidates were inspected read-only; none was modified or copied.
- Provider/model/Golden/DB/WeKnora/live/full: `NOT RUN / FORBIDDEN`.

## Evidence

- Initial RED: focused collection failed because the 093 verifier module did not exist.
- Contract RED: 12 focused cases failed before exact bytes/DTO drift attribution existed.
- Cross-language RED: reusing sorted Python mapping order changed the Go replay hash;
  GREEN explicitly rebuilds the Go struct-order marker preimage.
- Fixed vector byte SHA-256:
  `11acd865df279fb999b31d4980689012714afbcab27b1b9cc92e63349ca4fbec`.
- Fixed typed result SHA-256:
  `6f45bdfbdc9268e00b88450d81d8cc37c33d9bc7351281f8bee75b30b87adbe6`.
- Current result: `BLOCKED`; no ADMIT, READY, binding or downstream action exists.
- `089_TO_086`: `MARKER_ENDPOINT_AUTHORITY_NOT_EXPOSED` for terms/rate_table.
- `086_TO_090`: `INJECTION_CONTEXT_NOT_BOUND` for terms/rate_table.
- Unique corrective owner/path: 086 /
  `harness/src/insurance_harness/knowledge_compiler/mineru_cross_page_binding_596_1.py`.
- Focused: `14 passed`; bounded canonical + 093: `113 passed`.
- Ruff exact source/test: `PASS`; strict mypy exact source/test: `PASS`.
- OpenSpec093 strict, diff-check, exact-seven scope, private/secret and real index:
  `PASS`.
- Provider/model/Golden/DB/WeKnora/live/full: `NOT RUN / FORBIDDEN`.
