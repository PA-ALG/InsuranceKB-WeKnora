# OpenSpec 107 · Section-anchor readiness injection

## Why

OpenSpec 103 and 104 stop honestly at `TERMS_SECTION_BINDING_UNAVAILABLE`. OpenSpec 106
is the sole owner of native terms-section anchor extraction. This change supplies only the
mechanical seam that replays a frozen 106 evidence envelope through the already-frozen 103,
102/086, 096 and 104/099 contracts.

## What changes

- add one task-local immutable evidence view and a narrow 106 provider Protocol;
- recompute source, parser, artifact, ParsedDocument/ParseManifest, marker, reading-order,
  ancestry, outline and anchor-interval custody before invoking 103;
- turn the verified 103/086/096 terms receipt into the exact 104 binding seam and call actual
  104/098/099 only in the explicit TEST_ONLY future-complete path;
- keep the current formal path at `SECTION_ANCHOR_EVIDENCE_UNAVAILABLE`, with zero downstream
  calls, until 106 has a frozen actual implementation and fixture.

## Non-goals

No section recognition, Markdown inference, adjacent-page inference, relation algorithm,
parser, capture, credential, provider, database, WeKnora, Golden, Release, workflow or shared
schema change. This change does not modify 103/104 or any other frozen dependency.
