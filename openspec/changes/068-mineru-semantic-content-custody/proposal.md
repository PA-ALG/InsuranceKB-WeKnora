# 068 · MinerU semantic content custody

## Status

`STABLE CANDIDATE / PROVIDER NOT RUN / EXTERNAL REVIEW PENDING`

## User value

The existing MinerU capture freezes a sanitized native-structure sidecar but discards the text
returned by the same provider read. A later 596-1 prompt therefore cannot bind its candidate arm
to an exact parser text snapshot. This change extends that one capture boundary so structure and
text are atomically custodied together without another provider call.

## Bounded design

- The existing capture performs exactly one `Read`; its `NativeStructure` and `MarkdownContent`
  become one private `mineru-semantic-content-custody.v2` JSON artifact.
- The v2 artifact binds source, parser/model/config, raw and sanitized structure hashes, sanitized
  structure, content snapshot, and the SHA-256 of the exact snapshot bytes. The request and
  artifact also bind the approved 596-1 parse identity `2/bounded_upgrade/generation=0`; one
  deterministic capture-identity hash covers that identity plus source/parser/structure/content
  hashes.
- The existing 596-1 runner preflights all three frozen PDFs, then captures terms, brochure, and
  rate sequentially exactly once each.
- Publication remains mode `0600`, atomic, and no-replace beneath a caller-created new direct
  child of `/private/tmp`; stdout contains only masked role, relative artifact name, and artifact
  byte hash.
- Both semantic text and sanitized structure reject POSIX, macOS volume, Windows drive, and UNC
  absolute paths before publication without treating ordinary slash separators or HTTP(S) text as
  filesystem paths.

## Non-goals

No provider execution, parser algorithm change, public DTO, DB, WeKnora API, Golden, 061/065/067,
retry, fallback, parallel capture, admission, or general custody platform. README registration is
left untouched because 067 owns the registry concurrently.

## Path budget and stop condition

Exactly eight paths are allowed: the existing capture implementation/test, the existing 596-1
runner implementation/test, and these four OpenSpec files. A ninth path or public DTO redesign
requires stopping for total-control review.
