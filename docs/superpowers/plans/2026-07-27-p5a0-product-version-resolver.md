# P5a0+ ProductVersion Resolver Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** deterministically bind a document or section to one exact persisted
`ProductVersion` without allowing similar names, generated aliases, or model
output to mint identity.

**Architecture:** add a scoped, read-only resolver beside the existing
product-level routing code. It reads the existing `InsuranceProduct`,
`ProductVersion`, and `ProductAlias` tables, evaluates exact anchors in a fixed
order, returns an immutable content-addressed decision, and raises a typed
quarantine result whenever identity is not unique. The existing registration
service performs one narrow lifecycle action: on creation only, it copies the
same version directory's filing/registration value into
`ProductVersion.terms_revision`; it never rewrites an existing version.
Fragment bindings are pure inheritance from an already resolved
document/section decision.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2, C0
`CanonicalEnvelopeV1`, pytest, OpenSpec.

---

## Contract Card

- **Business value:** prevent knowledge from different product versions or
  similarly named products being compiled into the same Wiki identity.
- **Authority:** an attested `KnowledgeScope` plus existing product/version
  master data. Only exact `ProductVersion.terms_revision` anchors, exact
  product code/name that leave one version, or the content-addressed
  `manual/manual` alias allowlist policy may resolve. Product-root filing
  fields and all auto aliases remain non-authoritative for version identity.
- **Owner:** one writer; one migration-free PR.
- **Path budget:** new OpenSpec 041, this plan, one resolver module, one narrow
  registration fill, one package export, one focused test module, and one
  read-only fixture.
- **Non-goals:** new tables/migrations, receipt persistence, APIs/UI, generic
  entity registry, negative memory, fuzzy/embedding/LLM identity, historical
  cleanup, upstream Tencent work.
- **Stop conditions:** version filing/registration cannot map uniquely through
  existing `ProductVersion.terms_revision`, a new persistence table is needed,
  any forbidden shared path is required, or the change exceeds the small-PR
  boundary.

## Task 1: Freeze the OpenSpec contract

**Files:**
- Create: `openspec/changes/041-p5a0-product-version-resolver/proposal.md`
- Create: `openspec/changes/041-p5a0-product-version-resolver/tasks.md`
- Create:
  `openspec/changes/041-p5a0-product-version-resolver/specs/product-version-resolver/spec.md`
- Create:
  `openspec/changes/041-p5a0-product-version-resolver/validation-report.md`

- [ ] Define exact anchor priority and typed quarantine reasons.
- [ ] Define C0-backed resolver policy/result hashes and complete basis.
- [ ] Define fragment inheritance and non-authority candidate signals.
- [ ] Freeze the path budget and forbidden paths.

## Task 2: RED tests

**Files:**
- Create: `harness/tests/fixtures/product_version_resolver_041.json`
- Create: `harness/tests/test_product_version_resolver_041.py`
- Create: `harness/tests/test_product_version_registration_041.py`

- [ ] Prove 1072-1 and 1072-4 resolve to distinct exact versions.
- [ ] Prove name collision, conflicting anchors, cross-Space, missing version,
      and ambiguous same-name cases quarantine without guessing.
- [ ] Prove every auto alias, including auto `registration_no`, and product-root
      `filing_no` cannot mint version identity; approved manual aliases may
      resolve only when unique.
- [ ] Prove master-data constraints only reject candidates.
- [ ] Prove fragments inherit the parent decision without invoking a resolver.
- [ ] Prove resolver/result hashes are deterministic and tamper-sensitive.
- [ ] Prove new-version registration prefers filing, falls back to registration
      only when filing is absent, never rewrites an existing anchor, and never
      backfills a historical null.
- [ ] Run the focused test and record the expected import/contract failure.

## Task 3: Minimal GREEN implementation

**Files:**
- Create:
  `harness/src/insurance_harness/product/version_resolver.py`
- Modify: `harness/src/insurance_harness/product/register.py`
- Modify: `harness/src/insurance_harness/product/__init__.py`

- [ ] Implement immutable request/result/basis/fragment DTOs and typed
      quarantine.
- [ ] Load only the attested Space's products, versions, and approved aliases.
- [ ] Resolve exact version filing/registration before exact code/name, then
      approved alias; reject all contradictions and non-unique outcomes.
- [ ] Fill `terms_revision` from the same version directory's ProductMeta
      filing number (or registration number only when filing is absent) only
      when a new ProductVersion is registered; never rewrite or backfill an
      existing version.
- [ ] Use C0 `canonical_hash` for policy and result identities.

## Task 4: Verify and deliver

- [ ] Run focused resolver/product/scope/canonical tests.
- [ ] Run Ruff and strict mypy on the changed Python paths.
- [ ] Run strict OpenSpec validation, diff-check, scope, private-path, and
      secret scans.
- [ ] Confirm no migration, provider, model, live, PostgreSQL, or forbidden
      path entered the diff.
- [ ] Update tasks and validation report with fresh evidence.
- [ ] Commit, push, and open a Draft PR; do not mark Ready or merge.
