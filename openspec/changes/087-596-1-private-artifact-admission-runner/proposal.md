# 087 · 596-1 Private Artifact Admission Runner

## Goal

Provide one task-local command that safely opens exactly three existing private MinerU custody
artifacts in `terms -> brochure -> rate_table` order plus one future 086 relation receipt,
delegates content authority to 083/086 validators, delegates admission to 084, and emits one
privacy-safe typed JSON result.

## Scope

- require four distinct regular files with exact mode `0600`, opened no-follow;
- call the intake validator exactly once per fixed role and the relation validator exactly once;
- pass validated DTOs and relation bindings to the admission assembler exactly once, without
  parsing raw JSON/structure or recomputing artifact hashes;
- emit only fixed status, safe role/contract/hash identities and a common receipt digest;
- preserve `BLOCKED_ON_CROSS_PAGE_BINDING` exactly and expose no partial brochure receipt;
- map a synthetic successful composition to `COMPOSITION_SEAM_VERIFIED`, never current-runtime
  READY or production authority.

## Non-goals

No capture, provider/model/Golden, database, WeKnora, Release, retry, fallback, raw JSON parser,
hash implementation, artifact publication, generic workflow framework or real MinerU READY
claim. 083/084/086 implementations remain separately owned.

## Path budget

Exactly seven paths: registry, four OpenSpec087 files, one task-local runner and one focused
test. No overlap with 083/084/086 implementation paths.
