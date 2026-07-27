# 041 Validation Report

## Candidate identity

- Base: `caf05facd729712a2fd74396029b5708d1d8a932`
- Branch: `codex/041-p5a0-product-version-resolver-main-replay`
- Candidate head/tree: final temp-index and commit identities are reported
  outside this self-referential file.

## Evidence

- Baseline focused:
  `uv run pytest -q tests/test_product_routing.py tests/test_scope_product_016.py
  tests/test_canonical_envelope_034.py`
  → `65 passed`
- Source draft custody: base `3f8aa56c`, frozen tree `b40da553`, strict
  10 paths; replay does not mutate that worktree.
- RED 1: resolver module absent → expected collection failure
  `ModuleNotFoundError: insurance_harness.product.version_resolver`.
- RED 2: create-only registration contract → `3 failed` (filing priority,
  registration fallback, initial immutable anchor).
- RED 3: product-root filing / auto registration alias fallback →
  `2 failed, 19 passed`.
- RED 4: unflushed ORM version/alias mutation authority bypass →
  `2 failed`.
- RED 5: unique version anchor + lower-priority same-name ambiguity →
  `1 failed`; both independent reviewers reproduced the same priority defect.
- GREEN focused:
  `uv run pytest -q tests/test_product_version_resolver_041.py
  tests/test_product_version_registration_041.py`
  → `27 passed`.
- Affected product/C0 regression:
  resolver + registration + register/routing/scope/aliases/classify/CLI/DB/C0
  → `116 passed`, two pre-existing SQLite datetime deprecation warnings.
- Static/OpenSpec: full Harness Ruff passed; strict mypy
  `341 source files` passed; strict OpenSpec 041 passed.
- Plan review: initial Spec `0C/2I/0M`, Plan `0C/2I/0M`; after authority,
  lifecycle and RED corrections, Spec/Plan `0C/0I/0M`, approved.
- First whole-candidate review: Spec `0C/1I/0M`, Quality
  `0C/1I/0M`, Security `0C/0I/0M`; both reviews found the same fixed-priority
  bug. Corrective now selects the highest authoritative layer first and uses
  lower layers only for compatible containment or typed conflict.
- Corrective review: Spec `0C/0I/0M`, Quality `0C/0I/0M`, Security
  `0C/0I/0M`; exact implementation tree approved.
- Final temp-index: strict 11 paths, diff-check passed, real index empty,
  working tree equals temp tree; private/secret/CRLF scans and PR #53 path
  overlap all zero.
- Full/provider/model/live/PostgreSQL: **NOT RUN** by Mission Card.

## Findings

- BLOCKER: none at contract review. Existing `ProductVersion.terms_revision`
  provides the required version-anchor slot; product-root filing fields and
  auto aliases are explicitly non-authoritative, so no table or migration is
  needed.
- BACKLOG: persistent EntityResolutionReceipt and historical
  `terms_revision` backfill remain deliberately outside this PR.
- REJECTED: generic entity registry, fuzzy/LLM identity, persistent receipts,
  negative memory, UI/API, historical routing cleanup, upstream Tencent work.
