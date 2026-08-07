# 108 · Legacy Fixture Marker-Envelope Compatibility

## Goal

Synchronize the frozen 086 and 092 test fixtures with the mandatory 091 marker
provenance envelope now enforced by 102/083. The fixtures must enter their
original relation and admission assertions without weakening any production
validation or changing the expected business result.

## Frozen evidence

- Authoritative main: `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`.
- Stacked 105 candidate tree: `860b3499d4c42a0262b2d732749f0ab55d0a75ff`.
- Bounded integration RED: 22 failures and one pass across the frozen 086/092
  modules. All 22 stop at `CAPTURE_MARKER_ENVELOPE_INVALID` before their prior
  assertion.
- Affected fixture factories are `_capture` in
  `test_mineru_cross_page_binding_596_1_086.py` and `_capture` in
  `test_relation_bound_admission_596_1_092.py`.

## Design

1. A test-only helper accepts explicit marker declarations: kind, source, page,
   node type, local index, native member and structural path.
2. It computes the exact 091 structural-path, marker-evidence and provenance
   replay preimages/hashes, updates the existing 062 ambiguous observations,
   and reseals the capture identity.
3. Terms and rate fixtures call the helper explicitly and select the existing
   102 marker-preserving replay mode at each 086/092 relation call. Brochure
   fixtures remain marker-free by contract. Zero-marker and invalid-marker cases
   still carry a real envelope and then exercise their original typed outcome.
4. No production source, default injection, fallback, authority bypass or
   relation inference is introduced.

If these canonical fixtures reveal a new production defect after the 091 front
door, 108 stops and reports that defect instead of changing production.

## Non-goals

No 102/105 production change, parser/capture execution, provider/model/Golden,
DB/PG/WeKnora, endpoint inference, generic fixture framework, commit, push or PR.

## Path budget

Eight paths: registry, four OpenSpec108 files, one task-local test helper, and
the two existing 086/092 test modules.
