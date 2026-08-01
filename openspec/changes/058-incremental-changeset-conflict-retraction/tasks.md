# 058 implementation plan

> **For agentic workers:** execute inline in this isolated worktree with strict
> TDD. No commit/push/PR before an exact frozen candidate is independently
> reviewed.

**Goal:** deterministically compile affected verified facts into an immutable
ChangeSet draft with explicit authority, conflict, and retraction custody.

**Architecture:** `source_authority.py` owns exact scope/source DTOs and the
finite authority comparison. `incremental_changes.py` owns immutable fact,
ChangeItem, and ChangeSet DTOs plus the five-way compiler. `retractions.py`
admits only explicit complete-scope/exclusive-support proofs. Existing C0
`canonical_hash` is the only hashing primitive.

## T1 — Identity and OpenSpec

- [x] Verify exact initial main `16ae691d...`, open PRs, empty 058 registry
      slot, clean isolated branch, and no overlapping owner; then preserve WIP
      and fast-forward first to `b3c4a7c...` and finally to authoritative main
      `8f2f933c...` after PR #85/057 merged.
- [x] Freeze exact ten paths, pure-domain scope, and non-goals.
- [x] Record clean bounded C0+052+053 baseline: 79 passed.

## T2 — Focused RED

- [x] Add RED for stable hashes and each `add/enrich/supersede/conflict/retract`
      action.
- [x] Add RED for field/material/source/ProductVersion/scope/time authority,
      affected-only output, and cross-scope fail closed.
- [x] Add RED proving missing or `unknown` never retracts and only an explicit
      complete-scope/exclusive-support proof can propose retract.
- [x] Run the exact focused file and record failures caused by missing 058
      modules, not fixture errors.

## T3 — Minimal GREEN

- [x] Add frozen extra-forbid DTOs and exact canonical payloads.
- [x] Implement the finite authority comparison: primary material outranks
      support; equal material authority requires strictly newer reliable time;
      unresolved different values become conflict.
- [x] Compile only candidate/retraction scopes; preserve all unaffected facts.
- [x] Derive retract only when the baseline fact has exactly one supporting
      source revision and the explicit proof binds that source and exact scope.
- [x] Expose the small pure surface only from explicit
      `knowledge_compiler` submodules; do not alter or widen a package facade.

## T4 — Verification and freeze

- [x] Run focused 058 plus bounded C0/052/053 compatibility.
- [x] Run Ruff and strict mypy on the three production modules and focused test.
- [x] Validate OpenSpec058 strictly; run diff-check, exact10 scope, private and
      secret scans.
- [x] Freeze an independent temp-index tree with real index empty.
- [x] Do not commit, push, create PR, run full/provider/live/DB/PG/WeKnora.

## T5 — Corrective successor

- [x] RED caller-declared authority, cross-registration, strict hash/identity,
      mixed-baseline, model-copy, empty-root hash, and isolated-import failures.
- [x] Join every authority to one exact 052 catalog + MaterialProfileResolution
      set and source-revision binding receipt; remove caller-owned FieldAuthority.
- [x] Revalidate every fact/proof, fix mixed-baseline classification, and bind
      root Space/ProductVersion into the deterministic input hash.
- [x] Keep the legacy knowledge package API unchanged, place 058 under the pure
      `knowledge_compiler` namespace, and prove isolated import does not load
      SQLAlchemy/models/publisher.
- [x] Run focused/C0/052/053 after the final main replay, Ruff, strict mypy
      including the focused test, OpenSpec/diff/exact10/private/secret; freeze a
      new temp-index tree.
- [x] RED and reject case-insensitive whole-token `all`/`any`/`unknown` across
      root, scope, binding, authority/support, and retraction identities while
      preserving legitimate composite values.
- [x] Require every `known` or `unknown` observation to bind a non-empty support
      set containing its exact authority source revision; revalidate copy bypasses.
