# 089 · MinerU typed cross-page marker provenance

## Status

`IMPLEMENTATION IN PROGRESS / PROVIDER NOT RUN`

## Goal

Close the exact `NATIVE_MARKER_KIND_UNBOUND` gap left by 062/086. Preserve the
existing `mineru-native-cross-page-facts.v1` JSON and semantic hash unchanged,
while adding one task-local companion contract that proves whether each native
MinerU 3.4.4 marker was `cross_page` or `lines_deleted` and where it occurred in
the exact `middle.json` structure.

## Design

The companion is reconstructed only from the same exact raw ZIP and unique
`*_middle.json` member already validated by 062. Each marker binds:

- exact source SHA, raw ZIP SHA, native member SHA, parser model and MinerU version;
- exact marker kind, zero-based page index, node type and local structural index;
- a domain-separated hash of the structural path and an item digest;
- one deterministic envelope replay digest.

The public companion contains no raw structural path, node content, Markdown,
HTML, bbox, filename, URL, secret or machine-local path. Replay recomputes the
companion from the raw ZIP; a self-consistent caller-authored replacement is not
authority.

## Boundary

089 does not generate a source/target endpoint, a cross-page relation, ADMIT or
parser-routing decision. It only restores the typed marker provenance needed by
086 before 086 applies its own unique-candidate matching. Unknown marker kinds,
duplicate marker identities and any custody drift fail closed.

## Path budget

Exactly seven paths: this registry row, four OpenSpec089 files, the existing 062
projector, and one new focused Go test. No 083/084/086/090, provider, Golden, DB,
WeKnora, live or full-lane change.
