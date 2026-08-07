# 102 · 086 Marker-Preserving Intake Replay Seam

## Goal

Close one mechanical compatibility gap: the frozen 086 private replay rebuilds
an otherwise valid 083/091 capture without its typed marker provenance envelope,
so the public evaluator stops at `INTAKE_REPLAY_FAILED` before validating the
098 endpoint-pair replay. 102 adds an explicit opt-in replay seam which preserves
and revalidates that envelope. It does not change relation policy or authority.

## Design

- keep the existing 086 replay mode byte-compatible and default;
- in the 102-only mode, serialize the exact typed marker envelope already held
  by the validated intake evidence and feed the rebuilt bytes back through the
  public 083 intake validator;
- trust no caller-supplied marker or digest: 083/091 revalidation and the frozen
  086 typed replay remain authoritative;
- pass a revalidated 098 `MarkerEndpointPairInputV1` to the unchanged 086
  evaluator and expose the resulting binding as a 096-compatible receipt entry;
- retain typed blocking for legacy no-marker input, `lines_deleted`, section
  evidence, zero/multiple candidates, unknown marker kinds and all identity drift.

Current real evidence remains blocked when it lacks a unique structural rule.
The synthetic complete fixture proves only the future mechanical composition.

## Non-goals

No new relation rules, NATIVE/ADMIT/READY claim, endpoint inference, parser,
provider/model/Golden, filesystem, credential, DB/PG/WeKnora, migration,
signature, receipt publication or generic replay framework.

## Path budget

Eight paths: registry, four OpenSpec files, one task-local adapter, one focused
test, and the smallest opt-in delta to the frozen 086 replay implementation.
