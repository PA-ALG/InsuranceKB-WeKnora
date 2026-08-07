# 103 · Terms Section Derived Endpoint-Pair Input Bridge

## Goal

Add the missing terms-side companion to 098. The bridge maps one revalidated
101 terms `cross_page` marker to an exact 053 source block, selects only the
first qualified block on the immediately following physical page, and requires
both endpoints to share a replayable section ancestry/outline anchor supplied
by the narrow 101 authority protocol. The resulting derived input is still
validated by 086 and accepted only as a 096 receipt entry.

## Design

- consume an exact 083 bundle, exact terms ParsedDocument/ParseManifest, and a
  101-compatible marker-authority protocol;
- replay all 083/091 capture, parser, member, marker and envelope identities;
- map the source marker by page/node/local-index to exactly one canonical block;
- select the unique reading-order-first qualified content block on page+1;
- require an authority response binding those actual endpoints to equal,
  non-empty section ancestry and heading-anchor digests whose preimage and
  response hashes are recomputed;
- expose one immutable `SectionEndpointPairReplayV1` implementing the frozen
  086 typed-marker replay protocol;
- invoke the 102 marker-preserving mode, then construct the existing 096 terms
  receipt-entry model in memory.

Current custody has no section ancestry/outline field in 053, so without the
101 anchor response it remains `SECTION_ANCHOR_NOT_AVAILABLE`. A future-complete
fixture proves only the deterministic mechanical route.

## Non-goals

No body/Markdown meaning, heading text similarity, fuzzy score, path hash,
table-rule change, parser/provider/model/Golden, filesystem, credential,
DB/PG/WeKnora, NATIVE/ADMIT/READY, publication, or generic paragraph matcher.

## Path budget

Seven 103-owned paths: registry, four OpenSpec files, one task-local module and
one focused test. Frozen 098/102/100/101 files remain byte-unchanged.
