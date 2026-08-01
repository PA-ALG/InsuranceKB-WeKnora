# 058 · Incremental ChangeSet, conflict, and retraction

## Status

`IMPLEMENTATION IN PROGRESS / PURE DOMAIN / UNCOMMITTED`

058 is Child E of the approved 051 compiler DAG. It turns exact verified fact
fixtures and an exact baseline into one immutable, content-addressed ChangeSet
draft. It does not read a database, mutate a Claim, create a Candidate/Release,
or grant review or serving authority.

## User value

A new SourceRevision must affect only the exact field scopes it actually
changes. The compiler needs a deterministic explanation for adding facts,
enriching equal facts with evidence, superseding a lower/older authority,
surfacing unresolved conflicts, and proposing a narrowly proven retraction.

## Scope

- exact field scope: Space, ProductVersion, subject, field, business-time
  interval, region, channel, population, and normalized conditions;
- exact source/material authority and reliable time joined to the existing 052
  catalog, MaterialProfileResolution, binding hash, and task-local source
  revision registration receipt;
- five actions: `add | enrich | supersede | conflict | retract`;
- affected-only compilation and C0 canonical hashes;
- retraction only from explicit complete-scope and exclusive-support proof;
- typed fail-closed behavior for cross-scope, malformed, missing, or ambiguous
  inputs.
- strict revalidation at compilation entry and an import-light knowledge facade
  so the pure compiler does not load ORM/publisher infrastructure.

## Exact path budget

Exactly ten paths:

1. `openspec/changes/README.md`
2. this proposal
3. `tasks.md`
4. `validation-report.md`
5. `specs/incremental-changeset-conflict-retraction/spec.md`
6. `harness/src/insurance_harness/knowledge/source_authority.py`
7. `harness/src/insurance_harness/knowledge/incremental_changes.py`
8. `harness/src/insurance_harness/knowledge/retractions.py`
9. `harness/src/insurance_harness/knowledge/__init__.py`
10. `harness/tests/test_incremental_changes_058.py`

An eleventh path is a hard stop and requires Total Control to redraw the
Mission. Future README conflicts are mechanical registry reconciliation only.

## Non-goals

- migration, ORM, DB/session, queue, worker, provider/model, live, or WeKnora;
- mutation of legacy Claim/ChangeSet tables or reuse of their serving semantics;
- CandidateRelease, ReviewDecision, PublishAuthorization, Release, or Wiki output;
- a generic rule/comparator/authority platform;
- 054/056/057 implementation, Golden data, or legacy cleanup.
