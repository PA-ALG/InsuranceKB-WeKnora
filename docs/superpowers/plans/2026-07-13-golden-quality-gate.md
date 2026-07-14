# Golden Quality Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement OpenSpec 019 as deterministic, fixture-tested software for portable Golden releases, immutable baseline approvals, field QualityProfiles and conservative merge automation.

**Architecture:** Move the WIP-only assembly logic into the `goldenset` package, separate metric artifacts from approvals, then inject one fail-closed QualityGate into every automatic merge path. Real two-product annotation and 13-product model runs remain in OpenSpec 020 and consume these APIs.

**Tech Stack:** Python 3.12, Pydantic v2, existing goldenset evaluator, SQLAlchemy knowledge merge, pytest fixtures/replay, Ruff, mypy.

**Spec:** `openspec/changes/019-golden-quality-gate/specs/quality-gate.md`

**Repository rule:** AI workers do not commit or push. Human checkpoints replace plan commit steps.

---

## File map

**Create**

- `harness/src/insurance_harness/goldenset/assemble.py` — portable WIP-to-release conversion.
- `harness/src/insurance_harness/goldenset/validate.py` — expected-products/disputed/completeness/self-eval validator.
- `harness/src/insurance_harness/goldenset/artifacts.py` — immutable baseline fingerprint/artifact/approval models.
- `harness/src/insurance_harness/goldenset/quality.py` — field metric aggregation and QualityProfile.
- `harness/src/insurance_harness/goldenset/regression.py` — global/field regression comparison and approval gate.
- `harness/src/insurance_harness/knowledge/quality_gate.py` — online eligibility decision.
- `harness/tests/test_goldenset_assemble_019.py`
- `harness/tests/test_goldenset_artifacts_019.py`
- `harness/tests/test_goldenset_quality_019.py`
- `harness/tests/test_knowledge_quality_gate_019.py`
- `openspec/changes/019-golden-quality-gate/validation-report.md`

**Modify**

- `harness/src/insurance_harness/goldenset/release.py` — manifest hashes/annotator aggregation without changing immutable-release behavior.
- `harness/src/insurance_harness/goldenset/eval.py` — expose reusable per-field observations if needed; preserve v1/v2 scoring semantics.
- `harness/src/insurance_harness/knowledge/models.py` — default supersede false.
- `harness/src/insurance_harness/knowledge/merge.py` — one QualityGate call for add/enrich/supersede.
- `harness/tests/test_knowledge_merge.py` — update unsafe default expectations.
- `dataset/goldenset/wip-gs-v0.1/assemble_release.py` — thin compatibility wrapper or deprecation message; no absolute path.
- `dataset/goldenset/wip-gs-v0.1/provenance.json` — reviewed per-product fallback provenance for legacy raw rows that lack model/time fields.
- Goldenset/knowledge READMEs, 019 tasks, HANDOFF and docs 05/13/16/20.

---

### Task 1: Portable assembler with mixed annotator provenance

**Files:**

- Create: `harness/tests/test_goldenset_assemble_019.py`
- Create: `harness/src/insurance_harness/goldenset/assemble.py`
- Modify: `harness/src/insurance_harness/goldenset/release.py`
- Modify: `dataset/goldenset/wip-gs-v0.1/assemble_release.py`

- [ ] **Step 1: Write RED Q1.1/Q1.2 tests**

Build a temporary WIP with two products: one record already has `annotator_model/created_at`, another omits them and receives a product-specific provenance mapping. Assert existing provenance is never overwritten and any missing model/time mapping is an error.

```python
result = assemble_workspace(
    workspace=wip,
    dataset_root=dataset,
    schema_dir=schema,
    expected_manifest=expected,
    provenance_by_product={
        "P2": {
            "annotator_model": "provider/model-b@2026-07-13",
            "created_at": "2026-07-13T10:00:00+08:00",
            "basis": "fixture",
        }
    },
    output_dir=out,
    dry_run=True,
)
assert result.records_by_annotator == {
    "provider/model-a@2026-07-01": 1,
    "provider/model-b@2026-07-13": 1,
}
```

Also assert no absolute source path is serialized into the output manifest.

- [ ] **Step 2: Run RED**

Run: `cd harness && uv run pytest tests/test_goldenset_assemble_019.py -q`

Expected: assembler API missing.

- [ ] **Step 3: Implement minimal assembler**

Expose a typed `AssembleResult`; reuse `GoldenRecord`, quote verification, meta comparison and `build_release`. Accept all paths as parameters. If raw records omit provenance, require `provenance_by_product` with both model and time; do not use a module constant or `datetime.now()` fallback.

- [ ] **Step 4: Run GREEN**

Run: `cd harness && uv run pytest tests/test_goldenset_assemble_019.py tests/test_goldenset_release_eval.py -q`

Expected: pass.

- [ ] **Step 5: Build and review the legacy provenance map**

For each existing `golden.jsonl`, obtain the first repository record time with:

Run: `git log --follow --format=%cI -- dataset/goldenset/wip-gs-v0.1/<product>/golden.jsonl | tail -n 1`

Write `provenance.json` keyed by product with the recorded annotator from HANDOFF, that timestamp, and `basis="git_first_commit_time"`. A human owner reviews the map before it is used. The two missing products remain absent until 020 supplies their actual provenance.

- [ ] **Step 6: Replace the WIP script safely**

Make `assemble_release.py` parse explicit CLI paths and call the package API. A dry-run against the real WIP must not modify files:

Run: `cd harness && uv run python -m insurance_harness.goldenset.assemble --workspace ../dataset/goldenset/wip-gs-v0.1 --dataset-root ../dataset/shouxian_product --schema-dir ../docs/insurance-kb/schema-baseline --expected-manifest ../dataset/goldenset/wip-gs-v0.1/manifest.json --provenance ../dataset/goldenset/wip-gs-v0.1/provenance.json --output /private/tmp/gs-v0.1-dry-run --dry-run`

Expected: reports 11 completed and 2 missing; writes nothing.

- [ ] **Step 7: Static checks and human checkpoint**

Run targeted Ruff/mypy; record the provenance decision in tasks; human commits.

---

### Task 2: Release validator and self-eval gate

**Files:**

- Modify: `harness/tests/test_goldenset_assemble_019.py`
- Create: `harness/src/insurance_harness/goldenset/validate.py`
- Modify: `harness/src/insurance_harness/goldenset/assemble.py`

- [ ] **Step 1: Write one RED test per Q1.3/Q1.4 failure**

Cover missing expected product, disputed rate > threshold, missing extractable field, ignored non-extractable field, failed self-eval and existing output directory.

- [ ] **Step 2: Run RED**

Run: `cd harness && uv run pytest tests/test_goldenset_assemble_019.py -q`

Expected: validator functions missing.

- [ ] **Step 3: Implement validator**

```python
class ReleaseValidation(BaseModel):
    valid: bool
    product_errors: dict[str, list[str]]
    self_eval: dict[str, float]

def validate_release_input(
    records: list[GoldenRecord],
    *,
    expected_products: dict[str, set[str]],
    max_disputed_rate: float = 0.05,
) -> ReleaseValidation: ...
```

Use the existing evaluator for self-eval; do not duplicate its metric semantics.

- [ ] **Step 4: Run GREEN and regression**

Run: `cd harness && uv run pytest tests/test_goldenset_assemble_019.py tests/test_goldenset_release_eval.py tests/test_eval_v2_keypoints.py -q`

Expected: pass.

- [ ] **Step 5: Human checkpoint**

Document that software validation passing is not equivalent to 020 completing the real release; human commits.

---

### Task 3: Immutable baseline artifact, approval and regression gate

**Files:**

- Create: `harness/tests/test_goldenset_artifacts_019.py`
- Create: `harness/src/insurance_harness/goldenset/artifacts.py`
- Create: `harness/src/insurance_harness/goldenset/regression.py`

- [ ] **Step 1: Write RED Q2 tests**

Define a required per-product artifact record and remove each field in a parametrized RED test:

```python
class BaselineProductArtifacts(BaseModel):
    run_manifest_sha256: str
    pred_sha256: str
    dead_letter_sha256: str
    dead_letter_count: int
    judge_queue_sha256: str
    judge_queue_count: int
    judgements_sha256: str
    resolved_judgement_count: int
    keypoints_status: Literal["complete", "pending"]
    keypoints_sha256: str | None
    keypoints_pending_count: int
    eval_report_sha256: str
    unresolved_judge_count: int
    unresolved_dead_letter_count: int
```

Test that approval rejects: missing run manifest, pred, dead letter, judge queue, judgements, keypoints status, or eval report; inconsistent queue/resolved/unresolved counts; pending keypoints without a positive pending count; and omitted unresolved counts. Also test deterministic fingerprint, separate immutable approval, and a second approval creating a new record instead of mutating the first. Add Q3.3/Q4.6 tests where a candidate regression lists every failed metric and cannot be approved.

```python
fingerprint = BaselineFingerprint(
    git_sha="abc123",
    schema_version="v1.1+schema",
    model_id="provider/model@rev",
    prompt_version="p4",
    template_profile="none",
    source_profile="directory-v1",
    golden_manifest_sha256="deadbeef",
)
artifact = build_baseline_artifact(fingerprint=fingerprint, products=products)
regression = compare_baselines(current=approved_current, candidate=artifact, thresholds=thresholds)
assert regression.failures == []
assert approve(artifact, actor="owner-a", regression=regression).artifact_sha256 == artifact.sha256
```

- [ ] **Step 2: Run RED**

Run: `cd harness && uv run pytest tests/test_goldenset_artifacts_019.py -q`

Expected: module missing.

- [ ] **Step 3: Implement Pydantic models and canonical hashing**

Serialize with sorted keys and compact separators before sha256. Approval contains artifact hash, actor, timestamp and notes but does not rewrite the metrics artifact. `compare_baselines()` evaluates configured global micro/macro F1, hallucination, evidence and unresolved-count thresholds plus field thresholds, returning every failure as `{metric, baseline, candidate, allowed}`. `approve()` rejects any result with failures.

- [ ] **Step 4: Run GREEN and static checks**

Run tests, Ruff and mypy for artifacts/regression; expected pass.

- [ ] **Step 5: Human checkpoint**

Record artifact format/version in tasks; human commits.

---

### Task 4: Field QualityProfile generation and staleness

**Files:**

- Create: `harness/tests/test_goldenset_quality_019.py`
- Create: `harness/src/insurance_harness/goldenset/quality.py`
- Modify: `harness/src/insurance_harness/goldenset/eval.py` only if a reusable observation helper is required.

- [ ] **Step 1: Write RED Q3 tests**

Use a small golden/pred fixture to assert per-field support, value accuracy, tri-state confusion, hallucination rate and evidence accuracy. Test stale profile for every fingerprint dimension and golden manifest hash.

- [ ] **Step 2: Run RED**

Run: `cd harness && uv run pytest tests/test_goldenset_quality_019.py -q`

Expected: profile API missing.

- [ ] **Step 3: Implement observations and profile**

```python
class FieldQuality(BaseModel):
    support: int
    value_accuracy: float
    tri_state_confusion: dict[str, int]
    hallucination_rate: float
    evidence_accuracy: float

class QualityProfile(BaseModel):
    profile_version: str
    artifact_sha256: str
    baseline_approval_sha256: str
    fingerprint: BaselineFingerprint
    fields: dict[str, FieldQuality]
```

Require an approved baseline as input, set an explicit profile format version, and link its approval hash. Reuse normalization/evidence helpers from eval. If eval must expose observations, preserve `evaluate()` outputs exactly and add regression tests before refactoring.

- [ ] **Step 4: Run GREEN and evaluator regression**

Run: `cd harness && uv run pytest tests/test_goldenset_quality_019.py tests/test_goldenset_release_eval.py tests/test_eval_v2_keypoints.py -q`

Expected: pass.

- [ ] **Step 5: Human checkpoint**

Record whether evidence accuracy is page-level or quote-level; human commits.

---

### Task 5: Fail-closed QualityGate in every merge automation path

**Files:**

- Create: `harness/tests/test_knowledge_quality_gate_019.py`
- Create: `harness/src/insurance_harness/knowledge/quality_gate.py`
- Modify: `harness/src/insurance_harness/knowledge/models.py`
- Modify: `harness/src/insurance_harness/knowledge/merge.py`
- Modify: `harness/tests/test_knowledge_merge.py`

- [ ] **Step 1: Write RED Q4.1 test for the unsafe default**

```python
def test_q4_1_supersede_default_is_manual_review() -> None:
    assert MergePolicy().auto_apply_supersede_low_risk is False
```

Run it and confirm it fails because the current default is True.

- [ ] **Step 2: Change only the default and run GREEN**

Modify one line in `knowledge/models.py`, then run the single test. Expected: pass. Run existing merge tests and update only tests that intentionally relied on the unsafe default by passing an explicit policy.

- [ ] **Step 3: Write RED gate decision tests**

Cover approved eligible low-risk, high-risk rejection, pending_judge rejection, missing/stale/unapproved profile, profile-version mismatch, approval-hash mismatch, support/accuracy/hallucination/evidence threshold failures, and readable reasons.

- [ ] **Step 4: Implement the pure QualityGate**

```python
class QualityDecision(BaseModel):
    eligible: bool
    reason: str
    observed: FieldQuality | None = None

class QualityGate:
    def decide(
        self,
        *,
        field_id: str,
        risk: str,
        action: str,
        pending_judge: bool,
        fingerprint: BaselineFingerprint,
    ) -> QualityDecision: ...
```

Defaults: support 10, value accuracy 0.98, hallucination 0.01, evidence 1.0.

- [ ] **Step 5: Write RED MergeEngine integration tests**

For add, enrich and supersede independently, prove `auto_apply_*` true is insufficient without an eligible gate decision; ineligible candidates produce ReviewItem rather than being dropped. Add a Q4.6 test proving a regression-failed candidate artifact cannot receive approval and therefore cannot produce an eligible gate.

- [ ] **Step 6: Inject the gate minimally**

Add `quality_gate` and run fingerprint to MergeEngine. Centralize the decision in one helper called by all three auto paths. Do not add profile loading or filesystem IO to the merge loop; inject a preloaded gate.

- [ ] **Step 7: Run GREEN and knowledge regression**

Run: `cd harness && uv run pytest tests/test_knowledge_quality_gate_019.py tests/test_knowledge_merge.py tests/test_knowledge_e2e.py -q`

Expected: pass.

- [ ] **Step 8: Static checks and human checkpoint**

Run targeted Ruff/mypy; record threshold and fail-closed decisions; human commits.

---

### Task 6: Full verification and handoff to OpenSpec 020

**Files:**

- Create: `openspec/changes/019-golden-quality-gate/validation-report.md`
- Modify: 019 tasks, Golden/knowledge READMEs, docs 05/13/16/20 and HANDOFF.

- [ ] **Step 1: Run 019 targeted tests**

Run: `cd harness && uv run pytest tests/test_goldenset_assemble_019.py tests/test_goldenset_artifacts_019.py tests/test_goldenset_quality_019.py tests/test_knowledge_quality_gate_019.py -q`

Expected: pass.

- [ ] **Step 2: Run clean full gates**

Run Ruff `--no-cache`, mypy `--no-incremental`, and all non-live pytest. Expected: all pass.

- [ ] **Step 3: Dry-run the real WIP without model calls**

Run the portable assembler with the full explicit command from Task 1 Step 6. Expected: deterministic 11 complete/2 missing report, no output release and zero network/model calls.

- [ ] **Step 4: Write validation report and 020 readiness handoff**

Map Q1～Q5 to tests. Explicitly state that real gs-v0.1 and baseline remain pending under 020. Update HANDOFF with the exact 020 next command prerequisites; human owner commits.
