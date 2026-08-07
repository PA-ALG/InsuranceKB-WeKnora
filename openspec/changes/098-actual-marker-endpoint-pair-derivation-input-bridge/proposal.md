# 098 · Actual Marker Endpoint-Pair Derivation Input Bridge

## Goal

Close one narrow input gap between the same-read 091/083 MinerU custody and the
frozen 086 derived-binding evaluator. The bridge mechanically maps one typed
`cross_page` source observation to an actual canonical source node, enumerates
only policy-compatible canonical targets, and exposes a replay object that 086
must still validate. It does not issue a relation, receipt, ADMIT or READY.

## Design

- consume only the exact 083 intake bundle, 091 marker custody and 053 canonical
  ParsedDocument/ParseManifest facts;
- replay the 091 marker kind/page/node/local-index/native-member identity and
  reconstruct only its deterministic top-level structural-path preimage;
- map the source observation to exactly one canonical endpoint;
- for tables, enumerate only adjacent-page targets with exact column count and
  complete non-overlapping header cell content/structure/span identity, using
  the frozen 086 policy and requiring cardinality one;
- retain every structural fact, endpoint digest, custody hash, policy hash and
  replay preimage in one immutable task-local input DTO;
- convert that DTO into the frozen 086 typed-marker replay protocol; 086 remains
  the sole authority that emits `DERIVED_STRUCTURAL_BINDING_VERIFIED`;
- return typed `BLOCKED` for zero/multiple candidates or any custody drift and
  typed `NOT_AVAILABLE` where current section facts lack explicit endpoint refs.

The current 091/083 fixture remains an honest negative when it has a
`lines_deleted` observation beside `cross_page`, or lacks a replayable structural
path. The frozen 086 predecessor also reconstructs 083 bytes without the newer
091 marker companion, so its public evaluator currently returns
`INTAKE_REPLAY_FAILED` before consulting this bridge. A future-complete fixture
therefore proves the mechanical table path through the remaining frozen 086
evaluator and a 096 receipt entry behind exactly one marker-preserving replay
seam. 098 neither patches nor conceals that downstream compatibility blocker.

## Non-goals

No text/Markdown semantics, fuzzy similarity, header approximation, filesystem
path hash, model/provider/Golden, DB/PG/WeKnora, relation receipt publication,
parser ADMIT, READY, generic table matcher, migration, signature or queue.

## Path budget

Exactly seven 098-owned paths: registry, four OpenSpec files, one task-local
module and one focused test. Frozen 083/086/091/096 files remain byte-unchanged.
