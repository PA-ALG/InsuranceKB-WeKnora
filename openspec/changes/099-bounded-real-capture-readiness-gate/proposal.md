# 099 · Bounded Real-capture Readiness Gate

## Goal

Provide one task-local, read-only and fail-closed gate before total control may request
one bounded real MinerU capture. The gate verifies that the exact public stack
`091 → 098 → 086 → 096 → 095/087 → 094` has frozen implementation and API authority,
safe three-source custody and one-shot wrapper policy. It never executes capture or
reads a credential.

## Current expected terminal

Current main does not contain frozen public authority for the first dependency, 091.
The formal gate therefore returns `FROZEN_DEPENDENCY_AUTHORITY_UNAVAILABLE_091` before
examining caller evidence. Synthetic 097 evidence is not authority. A separate explicit
`TEST_ONLY` fixture proves the future complete branch is mechanically reachable but
cannot authorize capture.

## Non-goals

No capture, credential access, provider/model, Golden, DB, PostgreSQL, WeKnora, live,
full or external write. No deployment workflow, dependency implementation, relation
inference, mutable discovery scan or generic readiness platform.
