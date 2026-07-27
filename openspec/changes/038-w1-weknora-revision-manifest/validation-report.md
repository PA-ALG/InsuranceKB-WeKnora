# 038 W1 WeKnora Revision Manifest · Validation Report

## Candidate identity

- Branch: `codex/038-w1-revision-manifest`
- Base commit: `3f8aa56cf49cf390dd3e3bbc214cd3d6985331af`
- Base tree: `8ce3a698f71351492dc139c9bbbc00b4e2acce5a`
- Validation cutoff: `2026-07-27T10:47:12Z`
- Delivery state: implementation complete locally; commit/push/Draft PR pending

This change owns one invariant only: a served document-text chunk page is bound
to one database-authoritative completed parse attempt and immutable manifest,
or the REST API returns a typed 409/410/404. It does not add a second parser,
historical chunk retention, webhook, shared Harness storage, Redis/Asynq
coupling, insurance domain logic, or P11/P13/P14 behavior.

## RED evidence retained

The implementation followed RED → GREEN on the contract edges that were absent
from the baseline:

1. uppercase SHA-256 was initially accepted by `RevisionCommitBinding.Valid`;
2. revision state/chunk repository tests initially failed to compile because
   `GetRevisionState`, `GetRevision`, and `ListRevisionChunks` did not exist;
3. handler tests initially failed to compile because both revision REST
   handlers did not exist;
4. worker-effective parser/chunker identity test initially failed because
   `refreshRevisionBinding` did not exist;
5. manual rebuild attempt propagation test initially failed because
   `stampParseAttempt` did not exist;
6. independent review exposed a file-less URL/file_url reparse fence gap:
   RED tests did not compile until `DocumentProcessPayload.ParseAttempt` and
   `revisionPayloadMatchesKnowledge` existed; matching attempt is now accepted,
   stale attempt rejected, and legacy payloads remain limited to attempt zero;
7. independent review exposed an error-contract mismatch for live chunk-count
   drift; the handler RED fixed the behavior as
   `409 revision_manifest_incomplete`, and the OpenSpec now registers that
   sixth stable code instead of leaving an implementation-only branch.

All corresponding tests are GREEN in the focused and race-enabled gate below.

## Contract results

| Contract | Result | Evidence |
|---|---|---|
| monotonic allocation + pending in one transaction | PASS | repository allocation, concurrent allocation, rollback and old-chunk preservation tests |
| allocation before destructive cleanup | PASS | production reparse/manual-update order plus allocation-failure preservation test |
| exact file SHA-256 without changing MD5 semantics | PASS | upload test checks both known MD5 and SHA-256 vectors; legacy reparse streams stored bytes before allocation |
| worker-effective parser/chunker identity | PASS | binding is refreshed after the worker resolves actual effective config |
| stable production build identity | PASS | existing release Version/Commit inputs are additionally injected into revision service via `scripts/get_version.sh` |
| direct completed + final subtask completed transaction | PASS | direct and `FinalizeSubtaskRevision` repository tests |
| stale attempt fencing / failed-cancelled zero revision | PASS | typed stale and terminal-state tests, with zero partial revision writes |
| immutable ordered manifest | PASS | language-neutral digest vectors, duplicate/ordering rejection, and post-commit chunk-drift detection |
| revision REST 200/409/410/404 | PASS | descriptor/reason matrix, tombstone, never-existed and ACL tests |
| exact-attempt chunk paging | PASS | filtering/order/pagination/manifest binding and before/after state checks |
| file-less URL/file_url reparse fence | PASS | payload carries the allocated DB attempt independently of tracing/revision binding; matching/stale/legacy guard tests |
| manifest-count drift fail closed | PASS | stable `409 revision_manifest_incomplete` is specified and covered by a handler contract test |
| W0 T4 deterministic reparse/delete interleaving | PASS | three-page walk stops with typed 410; no mixed-attempt page or silent completion |
| legacy JSON compatibility | PASS | zero-valued `current_parse_attempt`, `file_sha256`, and `parse_attempt` remain serialized |
| migration contract | PASS | one `000066` up/down pair; columns, composite primary key, live-text unique index and down path asserted |

## Upstream compatibility matrix

- Pinned upstream baseline remains
  `5eefa70e6fc8f9ec27958779f91ece6cf685598c`.
- App version/commit use the repository's existing build injection; local test
  builds may report explicit `unknown`, never an omitted or empty field.
- Docreader version remains explicit `unknown` because the current Go/Docreader
  boundary exposes no stable runtime version. Parser engine, effective chunker
  configuration/digests and embedding model identity remain deterministic and
  non-empty.
- Existing knowledge/chunk response fields are unchanged; W1 only adds visible
  zero-compatible fields and two retrieve-capability routes.
- W1 is a project-owned thin adapter. No Tencent upstream issue was opened and
  no general upstream maintenance debt is included.
- PR #53 head observed during validation:
  `f8bb24c7059a54b1b73166a7cdc38cde75d7f13d`; its Harness/shared-document paths
  do not overlap this implementation.

## Fresh verification

PASS:

```text
go test -race ./internal/types ./internal/application/repository \
  ./internal/application/service ./internal/handler ./internal/router \
  ./migrations/versioned -run <038 focused contract regex> -count=1

go vet ./internal/types ./internal/application/repository \
  ./internal/application/service ./internal/handler ./internal/router \
  ./migrations/versioned

bash -n scripts/get_version.sh
DO_NOT_TRACK=1 openspec validate 038-w1-weknora-revision-manifest --strict
git diff --check
```

The focused race gate passed in all six packages. OpenSpec reported:
`Change '038-w1-weknora-revision-manifest' is valid`.

The first independent review of candidate tree `6a38054b4e4dbcc8af29f0de5f39b325dab6d573`
reported Spec `C0/I1/M0` and Quality/Security `C0/I1/M1`. The two Important
findings were the file-less reparse fence and the unregistered manifest
integrity code described above; the Minor was a document EOF diff-check issue.
This is the single corrective round allowed by the Mission Card. Fresh review
of corrected tree `7040cab4cda4002343649013087bccfc39f9764b` returned Spec
`C0/I0/M0 Approved YES` and Quality/Security `C0/I0/M0 Approved YES`; no
earlier approval was reused.

An exploratory broader package run was not used as completion evidence:
`internal/application/service` reached a sandbox-denied local listener test,
and an unrelated tenant parser configuration handler test returned 400. Neither
test or owned production path is changed by 038. The authorized Mission Card
requires the focused gate above, not a full repository run.

## NOT RUN / BLOCKED

- Full repository test suite: **NOT RUN** (explicit Mission Card boundary).
- Real PostgreSQL migration/integration: **NOT RUN**.
- Provider/model/WeKnora live: **NOT RUN**.
- W0 wall-clock live replay: **NOT RUN**; deterministic Go interleaving is
  GREEN, but live evidence must be collected only in the controlled lane.
- Shared closeout documents (`HANDOFF.md`, control board, OpenSpec README):
  **BLOCKED from this PR by scope** and intentionally unchanged.

No software BLOCKER remains for creating a Draft PR. Real PostgreSQL/live
evidence and post-merge shared-document closeout remain explicit follow-ups;
they do not authorize Ready or merge in this change.
