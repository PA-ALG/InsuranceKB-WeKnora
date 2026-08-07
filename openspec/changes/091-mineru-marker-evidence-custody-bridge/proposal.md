# 091 · MinerU marker evidence custody bridge

## Status

`STABLE INTEGRATION CANDIDATE / PROVIDER NOT RUN`

## Approved dependency stack

091 is an integration candidate over these exact identities, in order:

1. authoritative main `31d815cbc29dc9fb2ce53db2dcbfbd606b8761ff`;
2. Draft PR #115 / OpenSpec082 head `836151c8de5407cebef674780de93d822654e5da`;
3. Draft PR #116 / OpenSpec083 head `96d7e02c08f89d4fcaad629b2e8cc8e41dcf7e37`;
4. OpenSpec089 candidate tree `70d32f09069571a8bc8cb9fa8774ea700e2134ad`.

The integration worktree consumes those frozen inputs without changing any
owner worktree. It does not imply that either Draft PR or 089 has merged.

## Goal

Carry 089's typed MinerU 3.4.4 marker companion from the same ZIP/native member
through the Go v2 private capture artifact, then make the existing 083 bytes-only
Python intake replay and expose that companion to the later 086 matcher.

## Design

The Go reader computes legacy 062 facts and 089 marker provenance together from
one bounded ZIP byte slice. Terms and rate custody require both envelopes and
mechanically bind their shared source, parser/version, raw ZIP and native-member
identities. The capture identity additionally binds the 062 projection digest and
089 replay digest. Brochure continues to omit both cross-page envelopes.

The Python 083 intake uses closed Pydantic DTOs (`extra=forbid`), independently
recomputes every marker item hash and the replay digest using the exact Go
preimages, checks pairwise custody against the legacy facts, and includes both
envelope digests in each intake digest and the ordered bundle digest.

## Boundary

The bridge exposes marker kind, page index, structural-path hash, node type,
local index and custody hashes only. It carries no source/target endpoint,
relation, body, Markdown/HTML, bbox inference, local path, vendor URL, secret or
ADMIT claim. It does not modify 086/084/087/090 and performs no provider, Golden,
DB, WeKnora, live or full operation.

## Implementation plan

1. Add focused Go and Python tests first and observe failures for the absent
   capture/intake marker seam.
2. Extend the same-read Go metadata path and capture identity minimally.
3. Extend the closed 083 DTO/replay/digests minimally.
4. Run focused plus bounded 062/082/083/089 regressions, static/OpenSpec/privacy
   gates, then freeze one exact integration tree without commit or push.
