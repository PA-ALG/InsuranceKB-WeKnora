# PostgreSQL Embeddings Forward Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair a PostgreSQL retrieval database whose official ledger advanced while `public.embeddings` remained absent.

**Architecture:** Add one project-owned migration to the existing enterprise ledger, leaving the frozen official migration chain untouched. Recreate only the accumulated production embeddings schema, guard it with the existing `app.skip_embedding` session contract, and prove it against an isolated ParadeDB PostgreSQL database.

**Tech Stack:** PostgreSQL 17 / ParadeDB, golang-migrate, GORM, pgvector-go, Go tests, OpenSpec.

---

### Task 1: Freeze contract and reproduce the defect

**Files:**
- Modify: `internal/database/legacy_w1_bridge_test.go`

- [x] Add a test-only DSN guard requiring the exact isolated database name `weknora_embeddings_repair_test` before any mutation.
- [x] Build official schema through version 75 with `app.skip_embedding=true`, and enterprise schema through the predecessor head.
- [x] Assert official ledger is clean/current and `to_regclass('public.embeddings')` is null.
- [x] Run the canonical migration path with `app.skip_embedding=false` and assert the table exists.
- [x] Run the focused node and capture the expected RED: the table remains absent because no forward repair exists.

### Task 2: Implement the minimal forward migration

**Files:**
- Create: `migrations/enterprise/versioned/000003_embeddings_forward_repair.up.sql`
- Create: `migrations/enterprise/versioned/000003_embeddings_forward_repair.down.sql`
- Modify: `internal/database/enterprise_migration.go`
- Modify: `internal/database/legacy_w1_bridge.go`
- Modify: `internal/database/legacy_w1_bridge_test.go`

- [x] Set packaged enterprise head to 3 and update existing exact-head test expectations.
- [x] Admit clean enterprise predecessor 2 only at the frozen official head so the
      new forward migration remains reachable without weakening earlier-origin checks.
- [x] In up SQL, return without schema creation when `app.skip_embedding=true`.
- [x] Otherwise create required extensions, accumulated table columns and exact existing indexes using idempotent DDL.
- [x] Validate an existing table's finite current column/type/index contract before
      constructing the enterprise migrator; reject partial tables without ledger advance.
- [x] Make down an explicit no-op so a historical/preexisting embeddings table can never be dropped.
- [x] Re-run the RED node and confirm GREEN.

### Task 3: Prove losslessness and production repository compatibility

**Files:**
- Modify: `internal/database/legacy_w1_bridge_test.go`

- [x] Add subtests for skip mode, healthy table plus sentinel row, partial-table fail-closed,
      down/up preservation, and repeated canonical migration execution.
- [x] Construct the public production PostgreSQL retrieve repository on a GORM transaction.
- [x] BatchSave one synthetic 1024-dimensional vector, assert success inside the transaction, roll back, and assert zero persisted synthetic rows.
- [x] Run all focused migration nodes against the isolated ParadeDB container.

### Task 4: Verify and freeze

**Files:**
- Modify: `openspec/changes/050-postgres-embeddings-forward-repair/tasks.md`
- Modify: `openspec/changes/050-postgres-embeddings-forward-repair/validation-report.md`

- [x] Run `go test ./internal/database -run 'EmbeddingsForwardRepair|PostgresLegacyW1MigrationMatrix' -count=1` with the isolated test DSN.
- [x] Run related non-PostgreSQL deterministic tests.
- [x] Run `gofmt`, focused static checks, `openspec validate 050-postgres-embeddings-forward-repair --strict`, and `git diff --check`.
- [x] Verify exact eleven-path scope, no secrets/private paths, no runtime database/provider/PDF writes, and freeze the candidate without commit/push/PR.
