# WeKnora `80a5003` Continuous Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Adopt exact Tencent WeKnora snapshot `80a5003cc99a427098afe184eee6601916d3d156` without data loss, preserve/replay W1, ship Wiki page history/diff/manual-edit/revert, and leave a repeatable guarded path for later upstream identities.

**Architecture:** Merge the exact official snapshot as vendor history, keep official migrations byte-exact, and run W1 from an independent enterprise migration source/state table after a fail-closed legacy-`000066` bridge. A deterministic adoption planner turns one approved upstream identity into migration/path/schema collision evidence and a replayable W1 patch bundle. Code adoption and trusted artifact/cutover are separate PR checkpoints.

**Tech Stack:** Go 1.24, PostgreSQL 16/17, `golang-migrate` v4.19.1, Python 3.12 + pytest/Pydantic, Vue 3/TypeScript `node --test`, GitHub Actions, Docker Buildx, OCI provenance/SBOM/attestations.

---

## Scope and execution rules

- Authoritative spec:
  `openspec/changes/045-weknora-80a5003-continuous-adoption/specs/weknora-continuous-adoption/spec.md`.
- Exact upstream:
  commit `80a5003cc99a427098afe184eee6601916d3d156`,
  tree `18fcf68e7a008ce69929e32233f0b6914040c223`,
  release ancestor `v0.7.1@c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb`.
- Do not replace the target with mutable `main`; a new target requires an explicit
  target-manifest change and fresh collision report.
- Keep source-merge and deployed-runtime baselines distinct. The source merge uses
  the true project-head/target Git merge-base; runtime upgrade evidence uses the
  verified source-lock commit. Neither may be substituted for the other.
- Do not touch real/live databases in the Code PR. PostgreSQL tests use disposable
  databases only.
- Do not run provider/full/load suites. Use focused Go/frontend/Python/OpenSpec and
  PostgreSQL matrix tests.
- The Artifact PR starts only after the Code PR is merged and independently approved.
- W1/P11/P13/P14 remain the only approved fork identities. This plan replays W1 and
  the existing log-redaction security patch only.
- Do not create a project-owned official-chain `000076` bridge. The approved
  permanent solution is enterprise `000001` plus the transactional legacy
  compatibility bridge and independent ledger.
- AI writer sessions do not stage, commit or push. Each task ends with a verified
  diff/evidence checkpoint; the human/total-control lane creates the Code and
  Artifact PR integration commits after exact-scope review.

## File map

### Project-owned adoption control

- Create `deploy/upstream/weknora-adoption-target.json` — exact requested upstream
  identity, ancestor and required capability commits.
- Create `deploy/upstream/weknora-adoption-report.json` — deterministic generated
  project merge-base, runtime baseline, official migration/checksum, schema-object
  and patch-overlap evidence.
- Create `deploy/upstream/weknora-enterprise-schema-objects.yaml` — W1-owned columns,
  tables, constraints and indexes used by semantic collision checks.
- Create `harness/scripts/prepare_weknora_adoption.py` — one guarded planning/bundle
  command for this and later upgrades.
- Create `harness/tests/test_prepare_weknora_adoption_045.py` — unit/fixture tests for
  identity resolution, mutable-ref rejection, collision detection and deterministic
  output.
- Create `deploy/patches/w1-revision-manifest-80a5003.patch` — generated binary-safe
  replay delta from exact upstream target to approved W1 runtime surface.
- Modify `deploy/patches/enterprise-llm-wiki-patch-inventory.yaml` — target baseline,
  exact W1 path list/checksums, collision verdict and compatibility tests.

### Migration ownership and startup truth

- Create `migrations/enterprise/versioned/000001_knowledge_revision_manifest.up.sql`.
- Create `migrations/enterprise/versioned/000001_knowledge_revision_manifest.down.sql`.
- Create `deploy/patches/legacy-migrations/w1-000066/manifest.json`.
- Create `deploy/patches/legacy-migrations/w1-000066/000066_knowledge_revision_manifest.up.sql`.
- Create `deploy/patches/legacy-migrations/w1-000066/000066_knowledge_revision_manifest.down.sql`.
- Create `internal/database/adoption_state.go` — pure fingerprint/classifier/checkpoint
  types.
- Create `internal/database/adoption_state_test.go`.
- Create `internal/database/enterprise_migration.go` — PostgreSQL preflight, bridge,
  official→enterprise orchestration and capability probe.
- Create `internal/database/enterprise_migration_postgres_test.go`.
- Modify `internal/database/migration.go` — reusable migrator construction and two
  structured ledger caches; remove automatic dirty-state forcing from startup.
- Modify `internal/container/container.go` — migration failure returns an error; when
  auto-migrate is disabled, read-only adoption verification is still mandatory.
- Modify `cmd/server/main.go`; create `cmd/server/migration_cli.go` and focused tests
  — expose `WeKnora migration up|status` as the executable boundary over the shared
  orchestrator, without starting the HTTP server.
- Modify `internal/handler/system.go` and its focused tests — separate redacted
  official/enterprise migration status and W1 capability.
- Modify `scripts/migrate.sh` — call the same orchestrator for `up/status`, never print
  DB URL/password, and never auto-force.

### Upstream source and W1 replay

- Merge all official vendor paths from exact `80a5003`; do not hand-pick commits.
- Keep `migrations/versioned/000066_expand_knowledge_span_name.*` through official
  `000075_wiki_page_revisions.*` byte-equal to the target.
- Replay the W1 paths listed by
  `deploy/patches/enterprise-llm-wiki-patch-inventory.yaml`; the target router path is
  `internal/router/routes_knowledge.go`, not the pre-target monolithic `router.go`.
- Preserve official Wiki revision paths, including:
  `internal/application/repository/wiki_page.go`,
  `internal/application/service/wiki_page.go`,
  `internal/handler/wiki_page.go`,
  `internal/types/wiki_page.go`,
  `frontend/src/api/wiki/index.ts`,
  `frontend/src/utils/wikiLineDiff.ts`,
  `frontend/src/views/knowledge/wiki/WikiBrowser.vue`, and
  `frontend/src/views/knowledge/wiki/WikiRevisionDrawer.vue`.

### CI, artifacts and cutover

- Create `.github/workflows/weknora-adoption-ci.yml` — target identity/collision,
  focused Go/frontend and disposable PostgreSQL matrix gates.
- Upgrade `deploy/local-live/weknora-app-source.lock.json` to schema v2 in the Code
  PR: exact upstream identity, ordered W1/redaction patches and three image
  definitions, but no runtime digest/cutover claim.
- Modify `harness/scripts/verify_weknora_app_source.py` and
  `harness/tests/test_local_live_supply_chain_023.py` for schema v2 and ordered patch
  verification.
- Modify `.github/workflows/weknora-app-local-live-image.yml` to build/attest exact
  app, frontend and docreader images from one verified target checkout in the Code
  PR, so the trusted main-only workflow exists before artifact dispatch.
- Modify `deploy/local-live/images.lock` and
  `deploy/local-live/docker-compose.weknora.override.yml` only after exact artifact
  digests exist.
- Create `harness/scripts/verify_weknora_upgrade_clone.py` and
  `harness/tests/test_verify_weknora_upgrade_clone_045.py` for four-origin backup-clone
  evidence and secret-redacted receipts.
- Update `HANDOFF.md`, `docs/insurance-kb/23-mvp-control-board.md`,
  OpenSpec 045 tasks and validation report at the final exact identity.

---

## Code PR

### Task 1: Build the guarded upstream adoption planner

**Files:**
- Create: `deploy/upstream/weknora-adoption-target.json`
- Create: `deploy/upstream/weknora-enterprise-schema-objects.yaml`
- Create: `harness/scripts/prepare_weknora_adoption.py`
- Test: `harness/tests/test_prepare_weknora_adoption_045.py`

- [ ] **Step 1: Write target-manifest parser RED tests**

Test these inputs:

```python
TARGET = {
    "schema_version": 1,
    "repository": "https://github.com/Tencent/WeKnora.git",
    "commit": "80a5003cc99a427098afe184eee6601916d3d156",
    "tree": "18fcf68e7a008ce69929e32233f0b6914040c223",
    "release_ancestor": {
        "tag": "v0.7.1",
        "commit": "c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb",
    },
    "required_capability_commits": [
        "80a5003cc99a427098afe184eee6601916d3d156"
    ],
    "official_migration_head": 75,
}
```

Assert full 40-hex commit/tree, exact Tencent HTTPS repository, one exact release
ancestor, unique capability-commit list, and rejection of `main`, `master`, short
SHA, unknown fields and path traversal.

- [ ] **Step 2: Run the parser test and verify RED**

Run:

```bash
uv run --project harness pytest -q \
  harness/tests/test_prepare_weknora_adoption_045.py::test_target_manifest_is_strict
```

Expected: FAIL because `prepare_weknora_adoption.py` does not exist.

- [ ] **Step 3: Implement strict immutable identity types**

Implement frozen dataclasses/Pydantic-free parsing with closed key sets:

```python
@dataclass(frozen=True)
class TargetIdentity:
    repository: str
    commit: str
    tree: str
    release_tag: str
    release_commit: str
    required_capability_commits: tuple[str, ...]
    official_migration_head: int
```

The CLI SHALL accept `plan --target-manifest ... --project-checkout ...
--target-checkout ... --runtime-source-lock ... --output ...`.
Both checkouts must be clean; the target checkout must have exact HEAD/tree, the
reviewed origin and all required ancestors. The runtime lock must independently
resolve its exact commit/tree and need not be an ancestor of project HEAD.

- [ ] **Step 4: Run parser tests GREEN**

Run the same pytest node. Expected: `1 passed`.

- [ ] **Step 5: Write collision/report/bundle RED tests**

Use synthetic Git repositories and migration fixtures. Assert the report contains:

```json
{
  "target": {"commit": "...", "tree": "..."},
  "project_source": {
    "head": "...",
    "tree": "...",
    "merge_base": "..."
  },
  "runtime_source": {"commit": "...", "tree": "..."},
  "official_migrations": [{"version": 66, "name": "...", "sha256": "..."}],
  "enterprise_migrations": [{"version": 1, "name": "...", "sha256": "..."}],
  "migration_number_collisions": [],
  "schema_object_overlaps": [],
  "patch_path_overlaps": [],
  "verdict": "pass"
}
```

Assert semantic overlap blocks even when official/enterprise numbers differ, W1 paths
changed by upstream require explicit verdict, JSON is byte-deterministic, and a
bundle generated from registered paths applies cleanly to the exact target and
reproduces the reviewed project-tree checksums.
Also assert that a runtime source-lock commit which is a target ancestor but not a
project-head ancestor produces two separate source deltas and is never reported as
the Git merge-base.

- [ ] **Step 6: Run collision tests RED**

Run:

```bash
uv run --project harness pytest -q \
  harness/tests/test_prepare_weknora_adoption_045.py -k 'collision or deterministic'
```

Expected: FAIL on missing inventory/report functions.

- [ ] **Step 7: Implement migration/path/schema inventories**

Parse official and enterprise filename/version/checksum inventories. For schema SQL,
extract only reviewed `CREATE/ALTER/DROP TABLE|COLUMN|INDEX|CONSTRAINT` identifiers;
unknown dynamic SQL must yield `manual_review_required`, never a false pass. Intersect
both `git diff --name-only <true-project-merge-base>..<target>` and
`git diff --name-only <runtime-source-lock>..<target>` with registered W1/redaction
paths, and report the two results separately.
Implement bundle creation and verification in the same module: it may include only
registered W1 paths, emits a binary-safe patch plus checksum receipt, applies only to
an exact clean target checkout, and fails on any extra/missing/path-drift result.

- [ ] **Step 8: Add convenient future-upgrade commands**

Support:

```bash
uv run --project harness python harness/scripts/prepare_weknora_adoption.py \
  discover --channel latest-stable

uv run --project harness python harness/scripts/prepare_weknora_adoption.py \
  discover --channel mainline-head

uv run --project harness python harness/scripts/prepare_weknora_adoption.py \
  plan --target-manifest deploy/upstream/weknora-adoption-target.json \
  --project-checkout /path/to/project-checkout \
  --target-checkout /path/to/exact-upstream-checkout \
  --runtime-source-lock deploy/local-live/weknora-app-source.lock.json \
  --output deploy/upstream/weknora-adoption-report.json

uv run --project harness python harness/scripts/prepare_weknora_adoption.py \
  bundle --target-manifest deploy/upstream/weknora-adoption-target.json \
  --checkout /path/to/exact-upstream-checkout \
  --project-tree /path/to/reviewed-project-tree \
  --inventory deploy/patches/enterprise-llm-wiki-patch-inventory.yaml \
  --output deploy/patches/w1-revision-manifest-80a5003.patch \
  --receipt deploy/upstream/weknora-w1-bundle-receipt.json

uv run --project harness python harness/scripts/prepare_weknora_adoption.py \
  verify-bundle --target-manifest deploy/upstream/weknora-adoption-target.json \
  --checkout /path/to/exact-upstream-checkout \
  --inventory deploy/patches/enterprise-llm-wiki-patch-inventory.yaml \
  --bundle deploy/patches/w1-revision-manifest-80a5003.patch \
  --receipt deploy/upstream/weknora-w1-bundle-receipt.json
```

`discover` is read-only and prints a resolved tag/commit/tree proposal. The only
channels are `latest-stable` and `mainline-head`; both resolve the observed ref to a
full immutable commit/tree, and neither stores the mutable ref in the target
manifest. It SHALL NOT edit locks or adopt anything. `plan` accepts only the
committed exact identity. `bundle` and `verify-bundle` are deterministic
target-agnostic operations; the output filename may contain the approved target
short SHA, but behavior comes from the manifest and inventory rather than
`80a5003`-specific code.

- [ ] **Step 9: Run all planner tests GREEN**

Run:

```bash
uv run --project harness pytest -q \
  harness/tests/test_prepare_weknora_adoption_045.py
uv run --project harness ruff check \
  harness/scripts/prepare_weknora_adoption.py \
  harness/tests/test_prepare_weknora_adoption_045.py
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 10: Record the planner checkpoint**

Verify the exact diff contains only planner inputs, implementation and tests. Record
the test output and hand the uncommitted checkpoint to total control; do not stage,
commit or push.

### Task 2: Merge exact upstream history and freeze official inventory

**Files:**
- Modify: official vendor paths from true merge-base
  `b4b63a0c1f60718aa496df5ecf3a61a347da3d06` to target
  `80a5003cc99a427098afe184eee6601916d3d156`
- Create: `deploy/upstream/weknora-adoption-report.json`
- Modify: `deploy/patches/enterprise-llm-wiki-patch-inventory.yaml`

- [ ] **Step 1: Recheck identities before merge**

Run:

```bash
git fetch https://github.com/Tencent/WeKnora.git \
  80a5003cc99a427098afe184eee6601916d3d156
git cat-file -e 80a5003cc99a427098afe184eee6601916d3d156^{commit}
git show -s --format=%T 80a5003cc99a427098afe184eee6601916d3d156
```

Expected tree:
`18fcf68e7a008ce69929e32233f0b6914040c223`.

- [ ] **Step 2: Generate the pre-merge report**

Checkout exact target in a temporary clean worktree and run the planner. Expected:
official head 75; the known project/upstream `000066` conflict is reported; W1
overlapping paths require replay review; project merge-base is
`b4b63a0c1f60718aa496df5ecf3a61a347da3d06`; runtime baseline remains exact
`5eefa70e6fc8f9ec27958779f91ece6cf685598c`; and the two deltas are not conflated.

- [ ] **Step 3: Hand exact-target merge to the human/total-control boundary**

The AI writer SHALL stop with a clean worktree and provide the frozen target
identity and expected conflict set. The human/total-control lane then performs and
records the real merge commit:

```bash
git merge --no-ff \
  80a5003cc99a427098afe184eee6601916d3d156
```

No AI writer runs this command because even `--no-commit` populates the index.
Resolve only changed-in-both paths. For official migration history, keep target
`000066_expand_knowledge_span_name` through `000075_wiki_page_revisions`.
For registered W1 runtime overlaps, resolve this merge checkpoint to the exact
upstream target bytes; do not hand-combine W1 during the vendor merge. Replay the W1
contract deliberately in Tasks 3–7 before the Code PR can be approved.
Resolve `internal/middleware/logger.go` and its test to target bytes at this vendor
checkpoint as well; the existing registered model-debug redaction patch is replayed
and re-verified separately in Task 7. Preserve the project README only as an explicit
project-owned merge resolution.
Resume AI implementation only from the clean, exact merge commit after total-control
identity/scope readback.

- [ ] **Step 4: Verify vendor identity**

Generate a path report separating:

1. byte-equal official target paths;
2. registered project-owned W1 paths;
3. registered model-debug redaction paths;
4. project-only Harness/OpenSpec/deploy paths.

Any additional category is BLOCKER.

- [ ] **Step 5: Record the exact upstream merge checkpoint**

Record the merge parents, target tree and four-category path report from the clean
human/total-control merge checkpoint. Do not stage, commit or push.

### Task 3: Relocate W1 migration and preserve legacy identity

**Files:**
- Create: `migrations/enterprise/versioned/000001_knowledge_revision_manifest.up.sql`
- Create: `migrations/enterprise/versioned/000001_knowledge_revision_manifest.down.sql`
- Create: `deploy/patches/legacy-migrations/w1-000066/manifest.json`
- Create: legacy up/down SQL paths listed in the file map
- Test: `internal/database/adoption_state_test.go`
- Modify: `deploy/patches/enterprise-llm-wiki-patch-inventory.yaml`

- [ ] **Step 1: Write legacy-byte/checksum RED test**

Assert the legacy fixture bytes equal the historical W1 `000066` blobs from commit
`caf05facd729712a2fd74396029b5708d1d8a932`, manifest records original paths and
SHA-256, active official directory contains target `000066` only, and enterprise
`000001` has W1 semantics.

- [ ] **Step 2: Run RED**

Run:

```bash
go test ./internal/database -run TestW1LegacyMigrationIdentity -count=1
```

Expected: FAIL because fixture/enterprise files are missing.

- [ ] **Step 3: Add byte-identical legacy fixture and enterprise migration**

Copy historical W1 up/down bytes without semantic edits. Enterprise `000001` may add
an enterprise-specific notice only if the SQL checksum contract records it as a new
active migration; W1 table/column/index semantics must remain identical.

- [ ] **Step 4: Run GREEN and static collision planner**

Expected: legacy identity test passes; report shows official 66 and enterprise 1 use
different ledgers and flags no numeric collision.

- [ ] **Step 5: Record the migration-ownership checkpoint**

Record exact paths and checksums and hand the uncommitted checkpoint to total
control; do not stage, commit or push.

### Task 4: Implement the pure adoption-state classifier

**Files:**
- Create: `internal/database/adoption_state.go`
- Modify: `internal/database/adoption_state_test.go`

- [ ] **Step 1: Write table-driven RED tests**

Cover:

```go
const (
    StatePre66                    AdoptionState = "pre_66"
    StateUpstream66Plus           AdoptionState = "upstream_66_plus"
    StateLegacyW166               AdoptionState = "legacy_w1_66"
    StateFreshTarget              AdoptionState = "fresh_target"
    StateBridgedLegacyW166        AdoptionState = "bridged_legacy_w1_66"
    StateAdoptedW1PendingProbe    AdoptionState = "adopted_w1_pending_probe"
)
```

Also cover dirty official/enterprise ledgers, partial W1, version/schema mismatch,
unknown constraint/index and observed head not equal to the supplied target
migration contract. For this target the supplied official head is 75, but the
classifier test must also pass with a synthetic later head without code changes.
Assert typed failure and `WritesAllowed=false`.

- [ ] **Step 2: Run RED**

```bash
go test ./internal/database -run TestClassifyAdoptionState -count=1
```

- [ ] **Step 3: Implement a pure closed classifier**

Use value types only; no DB calls:

```go
type AdoptionFingerprint struct {
    Official LedgerFingerprint
    Enterprise LedgerFingerprint
    SpanNameVarcharLength int
    W1 W1SchemaFingerprint
    IsFreshFixture bool // tests only; production action must not depend on row counts
}

type AdoptionTarget struct {
    OfficialHead uint
    OfficialChecksums map[uint][32]byte
    EnterpriseHead uint
    EnterpriseChecksums map[uint][32]byte
}
```

Production classification must select actions from ledgers/schema, not business row
counts. `ClassifyAdoptionState(target AdoptionTarget, observed
AdoptionFingerprint)` receives the expected heads/checksums derived from the
embedded official and enterprise migration sources; the planner report must match
that same inventory before build. `fresh_target` and an existing database at the
supplied official head may share the same action. No migration version is hard-coded
in classifier logic.

- [ ] **Step 4: Run GREEN**

Run the node twice with `-count=20` to catch map/order nondeterminism.

- [ ] **Step 5: Record the classifier checkpoint**

Record exact paths and repeated test output and hand the uncommitted checkpoint to
total control; do not stage, commit or push.

### Task 5: Implement PostgreSQL bridge and two-ledger orchestrator

**Files:**
- Create: `internal/database/enterprise_migration.go`
- Create: `internal/database/enterprise_migration_postgres_test.go`
- Modify: `internal/database/migration.go`

- [ ] **Step 1: Write disposable PostgreSQL RED matrix**

Use `WEKNORA_ADOPTION_TEST_POSTGRES_URL`; require one unique disposable database per
test, not only a schema/search_path override, because the official chain installs
database-level extensions. Configure `options=-c app.skip_embedding=true` so plain
PostgreSQL 16 is sufficient.
Seed and test:

- existing pre-66;
- existing official 66+;
- legacy W1 66 with revision rows;
- fresh official head 75;
- bridge checkpoint restart;
- final-migration checkpoint restart;
- dirty/partial/unknown;
- two concurrent orchestrators.

Record before/after row counts and canonical data digests. Unknown/dirty/partial must
have byte-equivalent schema/data/ledger snapshots.

- [ ] **Step 2: Run RED**

```bash
WEKNORA_ADOPTION_TEST_POSTGRES_URL="$TEST_URL" \
  go test ./internal/database -run TestAdoptionPostgres -count=1 -v
```

Expected: FAIL because orchestration is missing. If the URL is absent, the test must
skip locally but CI must assert `skipped=0`.

- [ ] **Step 3: Implement exact schema fingerprint reads**

Read `schema_migrations`, `enterprise_schema_migrations`, `information_schema.columns`,
`pg_constraint` and `pg_indexes`. Canonicalize sorted definitions before hashing.
Never log DSN, row data or credentials.
This preflight SHALL use raw read-only SQL before constructing
`postgres.WithInstance`: that constructor may create its migration table, so using
it to classify dirty/partial/unknown state or `AUTO_MIGRATE=false` would violate the
zero-write contract.

- [ ] **Step 4: Implement the transactional legacy bridge**

Within one SQL transaction:

```sql
SELECT pg_advisory_xact_lock($1);
-- re-read exact fingerprint
ALTER TABLE knowledge_processing_spans
    ALTER COLUMN name TYPE VARCHAR(255);
CREATE TABLE enterprise_schema_migrations (
    version BIGINT NOT NULL PRIMARY KEY,
    dirty BOOLEAN NOT NULL
);
INSERT INTO enterprise_schema_migrations(version, dirty) VALUES (1, FALSE);
```

Before the write, verify complete legacy W1 fingerprint and official ledger 66 clean.
After the write, verify `bridged_legacy_w1_66`; otherwise rollback.

- [ ] **Step 5: Implement official→enterprise migration order**

Create the enterprise driver with:

```go
postgres.WithInstance(sqlDB, &postgres.Config{
    MigrationsTable: "enterprise_schema_migrations",
})
```

Run official source first, enterprise source second, then W1 structural capability
probe. Construct either migration driver only after the raw-SQL preflight has
selected a supported write action. Remove automatic `Force()` recovery from normal
startup paths.

- [ ] **Step 6: Prove crash-resume and concurrency GREEN**

Run:

```bash
WEKNORA_ADOPTION_TEST_POSTGRES_URL="$TEST_URL" \
  go test ./internal/database -run TestAdoptionPostgres -count=5 -v
```

Expected: all matrix cases pass, no skips in CI, one writer, identical final digests.
CI SHALL inspect structured `go test -json` output and assert `skipped=0`; an exit-0
test command alone is insufficient.

- [ ] **Step 7: Record the migrator checkpoint**

Record exact paths, PostgreSQL matrix receipt and zero-skip count and hand the
uncommitted checkpoint to total control; do not stage, commit or push.

### Task 6: Make startup/readiness and migration CLI truthful

**Files:**
- Modify: `internal/container/container.go`
- Modify: `internal/database/migration.go`
- Modify: `cmd/server/main.go`
- Create: `cmd/server/migration_cli.go`
- Create/Modify: focused tests in `cmd/server`
- Modify: `internal/handler/system.go`
- Create/Modify: focused tests beside those packages
- Modify: `scripts/migrate.sh`

- [ ] **Step 1: Write startup RED tests**

Assert:

- on the PostgreSQL production profile, migration error returns from container
  creation instead of logging and continuing;
- on PostgreSQL, `AUTO_MIGRATE=false` runs read-only adoption verification and
  rejects incomplete official/enterprise/W1 state;
- `AUTO_RECOVER_DIRTY` cannot cause startup `Force`;
- post-migration model/storage hooks run only after both ledgers and W1 probe pass.
- on SQLite, startup retains the official single-ledger migration behavior and does
  not require `enterprise_schema_migrations` or claim W1 certification.

- [ ] **Step 2: Run RED**

```bash
go test ./internal/container ./internal/database ./internal/handler \
  -run 'Migration|Adoption|SystemInfo' -count=1
```

- [ ] **Step 3: Return migration errors and cache two statuses**

For PostgreSQL, replace the warning/continue branch in
`internal/container/container.go` with an error return and cache structured,
redacted status:

```go
type AdoptionStatus struct {
    OfficialVersion uint
    OfficialDirty bool
    EnterpriseVersion uint
    EnterpriseDirty bool
    W1Capable bool
    ErrorCode string
}
```

Expose stable error codes, never raw DSN/driver errors.
Branch on the configured database profile before invoking adoption verification;
SQLite continues through the official upstream migration path and reports W1 as
uncertified/not-applicable rather than failed.

- [ ] **Step 4: Add an executable migration command over the shared orchestrator**

Add `WeKnora migration up|status` handling in `cmd/server` before HTTP/container
startup. `cmd/server/migration_cli.go` SHALL parse only those closed subcommands,
construct the redacted database configuration, invoke the same
`internal/database` orchestrator/status API as startup, print structured redacted
status, and return a non-zero exit code on any failed/incomplete state.

`scripts/migrate.sh up/status` SHALL resolve an explicit `WEKNORA_BIN` (defaulting to
the project-built `WeKnora` binary) and call that command; it must not call an
internal Go function or require a Go toolchain in the runtime image. Delete all
`echo DB_URL` / `echo DB_PASSWORD`. Keep manual `force/goto` visibly official-only
and never invoke them from startup or upgrade automation.

- [ ] **Step 5: Run GREEN and secret-output assertion**

```bash
go test ./cmd/server ./internal/container ./internal/database ./internal/handler \
  -run 'Migration|Adoption|SystemInfo' -count=1
rg -n 'echo .*DB_(URL|PASSWORD)' scripts/migrate.sh
```

Expected: tests pass; `rg` returns no matches.

- [ ] **Step 6: Record the startup/readiness checkpoint**

Record exact paths, focused test output and secret-output scan and hand the
uncommitted checkpoint to total control; do not stage, commit or push.

### Task 7: Replay W1 and the registered redaction patch on `80a5003`

**Files:**
- Modify: exact W1 paths in
  `deploy/patches/enterprise-llm-wiki-patch-inventory.yaml`
- Create: `deploy/patches/w1-revision-manifest-80a5003.patch`
- Modify: W1 Go/test paths after exact upstream merge
- Modify: `deploy/local-live/patches/model-debug-access-log-redaction.patch`
- Modify: `internal/middleware/logger.go` and its focused test only as produced by
  the already-approved redaction patch replay

- [ ] **Step 1: Run W1 focused tests before replay**

Expected: RED compile/test failures reveal upstream path/API changes; record exact
failures. Do not “fix” official Wiki revision behavior.

- [ ] **Step 2: Replay W1 by contract, not by old-file copy**

Preserve 038 W1.1–W1.7: attempt allocation/fencing, immutable manifest, typed
revision/chunk endpoints, digest and ACL. Adapt route registration to target
`internal/router/routes_knowledge.go`. Keep official `000075` Wiki revision domain
separate from W1 knowledge parse revisions.

- [ ] **Step 3: Run W1 Go contract suite**

```bash
go test ./internal/application/repository \
  ./internal/application/service ./internal/handler ./internal/router \
  ./internal/types -run 'Revision|ParseAttempt|Manifest' -count=1
```

Expected: PASS.

- [ ] **Step 4: Run W1 PostgreSQL contract**

Run targeted migration/concurrency/atomicity tests on disposable PostgreSQL with
`skipped=0`.

- [ ] **Step 5: Generate and verify patch bundle through the guarded tool**

Run the Task 1 `bundle` command against the reviewed project tree, then run
`verify-bundle` on a second clean exact-target checkout. Compare every patched
runtime file checksum against the Code PR tree. Any extra/missing path is BLOCKER;
manual patch assembly is forbidden.

- [ ] **Step 6: Rebase and verify the existing redaction patch**

Regenerate the existing model-debug redaction patch against exact target context,
apply it after W1 on a clean target checkout, and run its existing R3.3 focused
tests. It remains one existing security patch identity; no logger refactor or new
security feature is allowed.

- [ ] **Step 7: Update inventory/report and record the W1 checkpoint**

Regenerate the deterministic report and bundle receipt, record exact paths and W1
test evidence, and hand the uncommitted checkpoint to total control; do not stage,
commit or push.

### Task 8: Verify official Wiki history/diff/manual-edit/revert

**Files:**
- Preserve official target Wiki revision production paths byte-equal unless a
  documented W1 merge overlap requires a minimal resolution
- Add only focused regression tests if upstream tests do not cover U1.10

- [ ] **Step 1: Run official backend Wiki revision tests**

```bash
go test ./internal/application/repository \
  ./internal/application/service ./internal/handler \
  -run 'WikiPageRevision|RevisionHistory|Revert|ManualEdit' -count=1
```

- [ ] **Step 2: Run official line-diff frontend test**

```bash
npm --prefix frontend ci
npm --prefix frontend test -- wikiLineDiff
npm --prefix frontend run type-check
```

Expected: diff tests and type-check pass.

- [ ] **Step 3: Add missing U1.10 RED tests only if necessary**

Required behavior:

- successful manual save creates a revision with source attribution;
- stale optimistic-lock save conflicts and writes nothing;
- diff matches two selected revisions;
- revert creates a new current revision without deleting history;
- unauthorized history/diff/edit/revert is denied with zero writes.

- [ ] **Step 4: Run GREEN and ordinary Wiki non-regression**

Run focused wiki repository/service/handler/router tests. Do not add Harness Release,
P11 fencing or P14 ChangeProposal behavior.

- [ ] **Step 5: Record only actual test/merge resolutions**

If files changed, record exact paths and focused evidence and hand the uncommitted
checkpoint to total control; do not stage, commit or push.

### Task 9: Add adoption CI and prepare the Code PR

**Files:**
- Create: `.github/workflows/weknora-adoption-ci.yml`
- Modify: OpenSpec 045 tasks/validation report

- [ ] **Step 1: Add path-scoped CI**

CI jobs:

1. identity/report/patch-bundle verification;
2. focused Go W1 + Wiki revision tests;
3. frontend line-diff/type-check;
4. PostgreSQL 16 four-origin/crash/concurrency matrix with `skipped=0`;
5. strict OpenSpec and diff-check.

- [ ] **Step 2: Run the exact local non-live gates**

```bash
uv run --project harness pytest -q \
  harness/tests/test_prepare_weknora_adoption_045.py
go test ./internal/database ./internal/container ./internal/handler -count=1
openspec validate 045-weknora-80a5003-continuous-adoption --strict
git diff --check
```

- [ ] **Step 3: Verify scope**

Classify every diff path as official vendor, W1 adoption, W1 functional replay,
test/CI or OpenSpec evidence. Reject a sixth category.

- [ ] **Step 4: Review the code/migration slice before trusted workflow bootstrap**

Require no code/migration/W1 blocker before adding the source-lock/workflow slice.
This is not final Code PR approval and does not create an artifact conclusion.

- [ ] **Step 5: Keep runtime status truthful**

Use `CODE CANDIDATE / RUNTIME NOT ADOPTED`; do not update runtime image locks.

### Task 10: Upgrade source lock to ordered patches and three images

**Files:**
- Modify: `deploy/local-live/weknora-app-source.lock.json`
- Modify: `harness/scripts/verify_weknora_app_source.py`
- Modify: `harness/tests/test_local_live_supply_chain_023.py`

- [ ] **Step 1: Write schema-v2 RED tests**

Require:

```json
{
  "schema_version": 2,
  "upstream": {"commit": "80a5003...", "tree": "18fcf68e..."},
  "patches": [
    {"id": "W1", "path": "...", "sha256": "..."},
    {"id": "model-debug-redaction", "path": "...", "sha256": "..."}
  ],
  "images": {
    "app": {"repository": "...", "dockerfile": {"path": "...", "sha256": "..."}},
    "frontend": {"repository": "...", "dockerfile": {"path": "...", "sha256": "..."}},
    "docreader": {"repository": "...", "dockerfile": {"path": "...", "sha256": "..."}}
  }
}
```

Reject unordered/duplicate patch IDs, unknown keys, mutable tags, wrong tree,
unreviewed repository and missing Dockerfile hashes.

- [ ] **Step 2: Run RED**

```bash
uv run --project harness pytest -q \
  harness/tests/test_local_live_supply_chain_023.py
```

- [ ] **Step 3: Implement schema v2 and ordered patch verification**

Verify every patch checksum and `git apply --check`; apply order is W1 then redaction.
After application, verify the generated W1 bundle against the reviewed final runtime
tree receipt.

- [ ] **Step 4: Run GREEN/Ruff**

Expected: supply-chain tests pass with no secret/private path output.

- [ ] **Step 5: Record the source-lock checkpoint**

Record exact paths, lock/patch identities and focused evidence and hand the
uncommitted checkpoint to total control; do not stage, commit or push.

### Task 11: Prepare the trusted app/frontend/docreader build workflow

**Files:**
- Modify: `.github/workflows/weknora-app-local-live-image.yml`
- Modify: supply-chain workflow assertions

- [ ] **Step 1: Write workflow RED assertions**

Assert one exact upstream checkout, ordered patch application, three pinned
Dockerfiles, three GHCR repositories, Buildx provenance/SBOM and three attestations.
No caller-controlled repository/commit/platform and no secrets beyond `github.token`.

- [ ] **Step 2: Run RED**

Run the focused supply-chain workflow test. Expected: FAIL because workflow builds
only app.

- [ ] **Step 3: Extend trusted workflow**

Build:

- app from `docker/Dockerfile.app`;
- frontend from `frontend/Dockerfile` with `frontend/` context;
- docreader from `docker/Dockerfile.docreader`.

All labels SHALL include the same upstream commit/tree and ordered patch-set digest.
Run W1 Go tests and frontend `wikiLineDiff` test before image build.

- [ ] **Step 4: Run workflow static tests GREEN**

- [ ] **Step 5: Run final independent Code PR review**

Require Spec, Migration/Data Safety, W1 compatibility and Quality/Delivery approval;
BLOCKER=0 and exact-head CI terminal green.

- [ ] **Step 6: Merge Code PR before dispatch**

The workflow remains `main`-only. The human/total-control lane performs Code PR
integration after approval; AI sessions do not commit, push, Ready or merge. Do not
dispatch an unmerged privileged workflow.

- [ ] **Step 7: Mark the post-merge state truthfully**

Use `CODE MERGED / RUNTIME NOT ADOPTED`; source lock and workflow are trusted, but
runtime image locks still point to the old digests.

---

## Artifact PR

### Task 12: Run trusted build and record immutable subjects

**Files:**
- Modify after successful workflow:
  `deploy/local-live/images.lock`
- Modify after successful workflow:
  `deploy/local-live/docker-compose.weknora.override.yml`

- [ ] **Step 1: Dispatch exact-main workflow**

Record run ID, exact main SHA and all three subject digests.

- [ ] **Step 2: Verify provenance/SBOM/attestations**

For each image, verify repository, source commit/tree, patch-set digest, platform and
subject digest. Any mismatch blocks lock update.

- [ ] **Step 3: Update immutable locks**

Pin all three images by digest. Never use a floating tag.

- [ ] **Step 4: Verify Compose equals images.lock**

Run focused supply-chain tests. Expected: exact string equality for app/frontend/
docreader.

### Task 13: Automate four-origin backup-clone verification

**Files:**
- Create: `harness/scripts/verify_weknora_upgrade_clone.py`
- Create: `harness/tests/test_verify_weknora_upgrade_clone_045.py`

- [ ] **Step 1: Write safety RED tests**

The script SHALL:

- read DSN from a named environment variable only;
- reject default/current production DB names;
- require an explicit clone marker;
- never print credentials;
- run read-only preflight before any mutation;
- emit canonical JSON receipts with only schema/data digests and counts.

- [ ] **Step 2: Run RED**

```bash
uv run --project harness pytest -q \
  harness/tests/test_verify_weknora_upgrade_clone_045.py
```

- [ ] **Step 3: Implement clone verifier**

Support the four origins and the two crash checkpoints. Record backup identity,
before/after digests, official/enterprise ledgers, span type, W1 capability and the
official migration head/checksums expected by the supplied adoption report. For
`80a5003` that includes Wiki revision migration 75; later targets consume their own
report without verifier code changes. The script does not create/drop the source DB.

- [ ] **Step 4: Run disposable PostgreSQL GREEN**

Repeat the legacy bridge/reclaim-sensitive cases at least five times. Expected:
identical final receipts and zero skips.

- [ ] **Step 5: Record the clone-verifier checkpoint**

Record exact paths, safety tests and disposable-PostgreSQL evidence and hand the
uncommitted checkpoint to total control; do not stage, commit or push.

### Task 14: Perform bounded local-live adoption and Wiki feature probe

**Files:**
- Modify: final runtime receipts/validation report only

- [ ] **Step 1: Create and verify a recoverable database backup clone**

Do not use the live database as the first migration target. Verify restore into a
separate clone and run Task 13 against it.

- [ ] **Step 2: Start exact digest-pinned candidate**

Verify app/frontend/docreader report the same upstream source identity and both
migration ledgers are clean.

- [ ] **Step 3: Run bounded W1 live probe**

Verify current revision descriptor, bound chunk pagination, reparse supersession and
delete typed behavior. No provider/full/load expansion.

- [ ] **Step 4: Run bounded Wiki user-flow probe**

On a scratch unmanaged Wiki page:

1. manual edit;
2. history;
3. diff;
4. stale save rejection;
5. revert creating a new revision;
6. unauthorized read/write denial.

Clean only the scratch object created by the probe.

- [ ] **Step 5: Exercise restore path**

Prove the old digest and verified database restore point can be selected without
running destructive official down migration.

### Task 15: Final evidence, review and mainline handoff

**Files:**
- Modify: `openspec/changes/045-weknora-80a5003-continuous-adoption/tasks.md`
- Create/Modify:
  `openspec/changes/045-weknora-80a5003-continuous-adoption/validation-report.md`
- Modify: `HANDOFF.md`
- Modify: `docs/insurance-kb/23-mvp-control-board.md`
- Modify: `openspec/changes/README.md`

- [ ] **Step 1: Record exact identities**

Before final review, update the tracked evidence files with upstream commit/tree,
project Code merged-main identity, Artifact candidate SHA/tree, three image digests,
workflow run IDs, database-clone receipts and exact test counts. Do not attempt to
predict the future Artifact merge commit SHA inside the candidate.

- [ ] **Step 2: State capabilities precisely**

Only after all artifact gates pass:
`80a5003 SNAPSHOT ADOPTED`.
Keep P3 ACL-inspection/P2d blocked unless separately resolved.

- [ ] **Step 3: Run final non-live gates**

```bash
openspec validate 045-weknora-80a5003-continuous-adoption --strict
git diff --check
```

Run focused supply-chain/planner/clone tests and check private/secret/absolute-path
leaks.

- [ ] **Step 4: Independent final review**

Require exact-head Spec, Data Safety, Supply Chain, Quality/Delivery and Mainline/YAGNI
approval. No approval transfers across a head change.

- [ ] **Step 5: Merge and verify final main**

After human/total-control integration, perform a read-only verification that local
main, origin/main and GitHub main match; open PR count is `0`; code/workflow subtree
and final main CI evidence are exact; and the merged tree contains the reviewed
handoff/evidence bytes. Report the final main SHA/tree in the external integration
receipt. Do not modify tracked files after this check.
