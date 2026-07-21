# MVP Release Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement OpenSpec 029 so a complete deterministic ReleaseManifest is signed by a named authorized human before the Harness serving pointer can promote or roll back, and expose one approved-snapshot reader for both humans and agents.

**Architecture:** Preserve 018 as the frozen snapshot builder/read-model foundation, add manifest and approval records above it, and make `ApprovedSnapshotReader` the only consumption contract for 013/032. The legacy publisher may continue producing isolated staging snapshots, but production serving actions go only through the new approval service; P-1 WeKnora alias/seal remains deferred.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy/Alembic, PostgreSQL CAS tests, existing `ReleaseSnapshot`/`SnapshotFact`/`CurrentRelease`/`SnapshotReader`.

---

## Authority, dependencies, and boundaries

- Spec: `openspec/changes/029-release-manifest-approval-mvp/` (RA1–RA7).
- Run after 021/018; it may start in parallel with 027 but cannot expose a production release until 027 is verified.
- Risk: **A** (approval, tenant isolation, migration, serving pointer).
- Use @superpowers:test-driven-development for each invariant and @superpowers:verification-before-completion before handoff.
- This session is the K0 owner of `knowledge/` and migration `0013`; no other migration may be authored concurrently.
- Do not implement P-1 namespaces/aliases/GC, UI, MCP handlers, structured-evidence persistence, or a second SnapshotFact table. The public serving DTO must nevertheless reserve the strict structured Evidence branch consumed after 010.
- AI session does not commit/push. Stop at human commit boundaries.

## File map

**Create**

- `harness/src/insurance_harness/knowledge/release_manifest.py` — canonical payload models/builder/hash verification.
- `harness/src/insurance_harness/knowledge/release_approval.py` — authorizer port, named approval, promote/rollback CAS.
- `harness/src/insurance_harness/knowledge/release_cli.py` — governance-only human review/candidate/approval/promote/seal commands; no compilation or model access.
- `harness/src/insurance_harness/knowledge/serving.py` — the one public `ApprovedSnapshotReader`, canonical fact/Evidence DTOs, filter/order rules, and typed failure envelope imported by 013/032.
- `harness/migrations/versions/0013_release_manifest_approval_mvp.py`
- `harness/tests/test_release_manifest_029.py`
- `harness/tests/test_release_approval_029.py`
- `harness/tests/test_release_cli_029.py`
- `harness/tests/test_serving_reader_029.py`
- `harness/tests/test_release_manifest_migration_029.py`
- `openspec/changes/029-release-manifest-approval-mvp/validation-report.md`

**Modify**

- `harness/src/insurance_harness/knowledge/tables.py` — `ReleaseManifest` and append-only `ReleaseApproval`.
- `harness/src/insurance_harness/knowledge/publisher.py` — explicitly expose candidate/staging snapshot path; production serving uses approval service.
- `harness/src/insurance_harness/knowledge/__init__.py` — export only public manifest/approval/serving contracts.
- `harness/migrations/env.py` and `harness/tests/conftest.py` only if metadata import is required.

### Task 1: Freeze manifest schema and canonical hash

- [ ] **Step 1: Write RA1 RED tests**

Cover stable ordering, JSON formatting independence, wrong Space, missing schema/template/model-plan identities, and mutable Claim changes after snapshot freeze. For each of the four serving artifact sets—SnapshotFacts (including Evidence), rendered pages, product-directory entries, and page relationships—mutate, insert, and delete one item and assert the set hash plus outer manifest hash changes. Also forge each count and per-set hash independently and assert verification fails; an empty set is explicit with `count=0` and the canonical `[]` hash, never omitted.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_release_manifest_029.py
```

Expected: FAIL because `release_manifest` is missing.

- [ ] **Step 3: Implement canonical payload models**

Use a strict shape equivalent to:

```python
class ArtifactDigest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    count: int
    sha256: str

class ReleaseManifestPayload(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    schema_version: str
    space_id: str
    snapshot_id: str
    read_model_version: int
    template_hashes: tuple[str, ...]
    model_plan_hash: str
    facts: tuple[CanonicalSnapshotFact, ...]
    facts_digest: ArtifactDigest
    rendered_pages: tuple[CanonicalPage, ...]
    rendered_pages_digest: ArtifactDigest
    directory_entries: tuple[CanonicalDirectoryEntry, ...]
    directory_digest: ArtifactDigest
    relationships: tuple[CanonicalRelationship, ...]
    relationships_digest: ArtifactDigest
```

Each digest is recomputed from that artifact tuple's own sorted-key compact UTF-8 canonical JSON and checked against `count`; the outer SHA-256 covers the entire payload including all four item tuples, counts, and hashes. Builder reads only `ReleaseSnapshot`, `SnapshotFact`, and the frozen/derived page, directory, and relationship artifacts belonging to that snapshot. Directory/relationships are deterministically derived once from frozen pages/facts when no separate frozen row exists; they are never reconstructed from mutable Claim or remote WeKnora state. It must not query Claim/ClaimEvidence to fill gaps.

- [ ] **Step 4: Run GREEN**

Run the same command. Expected: PASS in ≤90 seconds.

### Task 2: Persist manifest and approval records

- [ ] **Step 1: Check migration head and acquire G lane**

```bash
cd harness
uv run alembic heads
```

Expected: exactly one head. Set `down_revision` to that head even if its number is greater than `0013`.

- [ ] **Step 2: Write migration/append-only RED tests**

Test unique `(space_id, snapshot_id)`, unique manifest hash in a Space, cross-Space FK protection, immutable canonical payload/hash, approval bound to exact snapshot/hash/actor, and UPDATE/DELETE rejection for approval rows in SQLite and PostgreSQL.

- [ ] **Step 3: Run RED**

```bash
cd harness
uv run pytest -q tests/test_release_manifest_migration_029.py tests/test_release_approval_029.py -k "schema or append or immutable"
```

- [ ] **Step 4: Implement tables and migration**

Minimum approval fields: `id, space_id, snapshot_id, manifest_hash, actor, actor_type, authorization_receipt, reason, approved_at`. `actor_type` accepts only human/principal for an effective approval; model/service values can be retained only as rejected decision receipts outside the effective approval table.

- [ ] **Step 5: Run SQLite GREEN and focused PostgreSQL lane**

```bash
cd harness
uv run pytest -q tests/test_release_manifest_migration_029.py tests/test_release_approval_029.py -k "schema or append or immutable"
uv run pytest -q -m integration_postgres tests/test_release_manifest_migration_029.py tests/test_release_approval_029.py
```

Expected: selected PG tests execute with skipped=0.

### Task 3: Named authorization and exact-hash approval

- [ ] **Step 1: Write RA2 RED tests**

Use an injected `ReleaseAuthorizer` fake. Test authorized named human, unauthorized principal, service/model actor, wrong role receipt, wrong Space, hash substitution, and approval created after manifest drift.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_release_approval_029.py -k "authoriz or actor or hash"
```

- [ ] **Step 3: Implement approval service**

`approve(scope, snapshot_id, manifest_hash, actor, authorization_receipt, reason)` re-builds/verifies manifest inside the same transaction, asks the authorizer, and appends exactly one approval. No boolean `approved=True` flag may live on `ReleaseSnapshot`.

- [ ] **Step 4: Run GREEN**

Expected: PASS; CurrentRelease remains unchanged in every approval-only test.

### Task 4: CAS promote and logical rollback

- [ ] **Step 1: Write RA3/RA5 RED tests**

Cover `expected_current=None`, stale expected current, two concurrent promoters, changed manifest after approval, rollback to approved A, rollback to unapproved/altered snapshot, and provider fake zero calls.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_release_approval_029.py -k "promote or concurrent or rollback or tamper"
```

- [ ] **Step 3: Implement one authority service**

`promote_approved_release` and `rollback_to_approved_release` must in one transaction: attest scope; lock/check current pointer; rebuild manifest; find exact effective approval; compare expected current; update/insert `CurrentRelease`; append an audit result. Rollback calls the same internal CAS routine and never invokes publisher/model.

- [ ] **Step 4: Run GREEN and PostgreSQL concurrency test**

```bash
cd harness
uv run pytest -q tests/test_release_approval_029.py
uv run pytest -q -m integration_postgres tests/test_release_approval_029.py -k "concurrent or cas"
```

Expected: exactly one concurrent winner; loser is a typed stale-CAS result.

### Task 5: Approved serving reader

- [ ] **Step 1: Freeze the exact public serving contract and write RA4 RED tests**

The only public call is:

```python
def read_current(
    self,
    scope: KnowledgeScope,
    *,
    product_id: str | None = None,
    product_version_id: str | None = None,
    predicates: tuple[str, ...] | None = None,
    effective_on: date | None = None,
    claim_id: str | None = None,
) -> ApprovedSnapshotResult | ServingFailure: ...
```

`predicates=None` means all fields; an empty tuple, blanks, or duplicates are invalid requests. Product/version/claim filters are exact and Space-attested. Date filtering is inclusive on `effective_from/effective_to`. Canonical fact order is `(product_id, product_version_id, predicate, effective_from or date.min, effective_to or date.max, claim_id, revision_no)`; Evidence order is the frozen stable source identity followed by evidence id.

`ApprovedSnapshotResult` is frozen and contains `snapshot_id`, `manifest_hash`, `approval_principal`, `approved_at`, `read_model_version`, and `facts`. Every canonical fact contains `claim_id/revision_no`, full product/version identity, predicate/name/group, `value_state/value`, effective interval, confidence, schema version, and an ordered `ServingDocumentEvidence | ServingStructuredEvidence` discriminated union copied from frozen Evidence. The structured branch is reserved now and populated by 010; it has source system/record/revision/locator/hash/mapping version and no page/chunk. The document branch preserves frozen knowledge/source revision, quote, authority, page/chunk fields.

`ServingFailure.code` is one of `no_release/unsupported_read_model/approval_missing/manifest_missing/manifest_mismatch/product_not_found/predicate_not_found/effective_date_miss/claim_not_found/scope_mismatch`; it has optional safe `snapshot_id/manifest_hash`, never facts. Scope mismatch never returns another Space identity. A returned canonical `value_state="unknown"` is a successful fact and remains visible; only a `ServingFailure` coverage code is not-found.

Test all failure codes, approved current, each filter independently and combined (including claim), canonical fact/Evidence order, document/structured Evidence serialization, mutable Claim changed after snapshot, cross-Space non-disclosure, returned manifest hash, and preservation of an approved `unknown` fact.

- [ ] **Step 2: Run RED**

```bash
cd harness
uv run pytest -q tests/test_serving_reader_029.py
```

- [ ] **Step 3: Implement `ApprovedSnapshotReader` and export the DTOs**

It validates `CurrentRelease → ReleaseSnapshot → ReleaseManifest → effective ReleaseApproval`, then delegates once to existing `SnapshotReader.current()` and applies only the frozen public filter/order rules above. It never queries mutable Claim. Export `ApprovedSnapshotReader`, `ApprovedSnapshotResult`, `ServingFailure`, `CanonicalServingFact`, and the two Evidence DTOs from `knowledge.__init__`; 013 and 032 must import these names rather than recreate them.

- [ ] **Step 4: Run GREEN and reader regressions**

```bash
cd harness
uv run pytest -q tests/test_serving_reader_029.py tests/test_snapshot_reader_018.py tests/test_snapshot_facts_018.py
```

Expected: PASS.

### Task 6: Candidate/staging boundary and P-1 fail closed

- [ ] **Step 1: Write RA6 RED tests**

Assert an isolated staging snapshot can be built, but the production serving entrypoint cannot expose it before approval. Assert no code path writes ordinary-user-visible WeKnora Wiki in 029; a production UI publish request returns a typed `P1CapabilityMissing`/blocked result.

- [ ] **Step 2: Make the publisher boundary explicit**

Factor or name the existing snapshot freeze as candidate/staging behavior. Do not rewrite the 018 state machine or break its recovery tests. All new production exports route to approval service; the validation report must label legacy direct publisher behavior staging/test-only.

- [ ] **Step 3: Run release regressions**

```bash
cd harness
uv run pytest -q tests/test_release_manifest_029.py tests/test_release_approval_029.py tests/test_serving_reader_029.py tests/test_publish_state_machine_018.py tests/test_reconcile_018.py tests/test_snapshot_guards_018.py
```

Expected: PASS.

### Task 7: Human-controlled governance CLI and final evidence seal

- [ ] **Step 1: Write RA7 RED tests**

Freeze these governance-only commands:

```text
python -m insurance_harness.knowledge.release_cli apply-review-decisions --request <human-yaml> --compilation-manifest <json> --output <json>
python -m insurance_harness.knowledge.release_cli build-candidate --run-request <yaml> --review-receipt <json> --output-dir <new-dir>
python -m insurance_harness.knowledge.release_cli approve-manifest --request <human-yaml> --manifest <json> --output <json>
python -m insurance_harness.knowledge.release_cli promote-approved --request <human-yaml> --manifest <json> --approval-receipt <json> --output <json>
python -m insurance_harness.knowledge.release_cli seal-run-artifacts --directory <dir> --compilation-manifest <json> --release-proof <json> --serving-proof <json>
```

Test that `release_cli` has no import/call path to `runtime`, any stage plugin, `ModelGateway`, provider, or Node/TS process. It consumes compiler receipts but never compiles. `apply-review-decisions` must reject an absent, generated-default, service/model-authored, stale-version, wrong-Space, or compilation-hash-mismatched request. `build-candidate` must reject mutated compiler artifacts, unresolved/deferred blocking ReviewItems, incomplete ChangeSet coverage, or a review receipt not bound to the exact compilation manifest. `approve-manifest` must reject a missing/defaulted manifest hash, principal, authorization receipt, or expected current. `promote-approved` must reject a stale CAS value or an approval receipt for another manifest. `seal-run-artifacts` must reject a release/serving snapshot or hash mismatch and must write `artifact-manifest.json` last.

- [ ] **Step 2: Implement explicit human input contracts**

`review-decisions.yaml` is authored by a named human after inspecting the real run's ChangeSets/ReviewItems. It binds the full `compilation_manifest_hash` and, for every blocking review item, `review_id`, `expected_version`, explicit `approve/reject` action, named human principal, authorization receipt, and reason. The CLI may validate and apply those choices through the existing review service, but may not infer a choice, fill an actor, turn `defer` into approval, or auto-approve a batch.

`release-approval-request.yaml` is authored by a named release authority **after** inspecting the candidate `release-manifest.json`. It contains the literal 64-hex `manifest_hash`, exact `snapshot_id`, an explicit nullable `expected_current_snapshot_id`, named human principal, authorization receipt, and reason. No command may discover and silently substitute the hash or actor. `approve-manifest` only appends an approval receipt and cannot promote; `promote-approved` revalidates the same request/receipt/manifest and performs the RA3 CAS.

- [ ] **Step 3: Implement candidate and evidence sealing boundaries**

`build-candidate` verifies every compiler-produced file against `compilation-manifest.json`, verifies complete human review receipts, invokes only the existing staging snapshot builder plus RA1 manifest builder, and writes an immutable candidate snapshot plus `release-manifest.json`; `CurrentRelease` stays unchanged. The final seal verifies the original compilation files are unchanged, the release proof points to the current RA3-promoted snapshot/hash, and Human/MCP serving proof points to that same snapshot/hash. It then hashes every preceding compiler, human-input, review, candidate, approval, release, metric, and serving artifact and creates `artifact-manifest.json` with exclusive-create semantics as the last file.

- [ ] **Step 4: Run GREEN and architecture checks**

```bash
cd harness
uv run pytest -q tests/test_release_cli_029.py tests/test_release_manifest_029.py tests/test_release_approval_029.py tests/test_serving_reader_029.py
uv run ruff check src/insurance_harness/knowledge/release_cli.py tests/test_release_cli_029.py
```

Expected: PASS; scripted model/provider call count remains zero and CurrentRelease moves only in the explicit `promote-approved` tests.

### Task 8: Validate and hand off K0

- [ ] **Step 1: Touched-code static checks**

```bash
cd harness
uv run ruff check src/insurance_harness/knowledge tests/test_release_*_029.py tests/test_serving_reader_029.py
uv run mypy src/insurance_harness/knowledge
```

- [ ] **Step 2: Complete validation report**

Record the four artifact counts/hashes plus outer manifest example/hash, mutation matrix, exact serving method/DTO schema, authorization matrix, human review/approval request examples and hashes, CAS/PG proof, compilation-to-final-seal proof, legacy staging boundary, rollback zero-model proof, and `P-1/production WeKnora UI = NOT RUN`.

- [ ] **Step 3: Independent one-pass spec/quality review**

Reviewer checks RA1–RA7, tenant isolation, mutable-read absence, append-only approval, no automated human decision, governance-only CLI imports, final-seal ordering, and concurrency. Maximum two remediation loops.

- [ ] **Step 4: One PR-ready full deterministic run and human commit boundary**

Run full deterministic only after findings close, record seven-stage time, report exact diff/evidence, and stop. Do not commit/push.
