"""Full cross-language Candidate vector, explicitly synthetic, never a model receipt."""

from __future__ import annotations

import gzip
import hashlib
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as c
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    AuditDisposition,
    ExecutionRecord,
    ReviewOutput,
    ReviewResult,
    free_page_id,
)
from insurance_harness.knowledge_compiler.knowledge_quality import QUALITY_POLICY
from tests.test_provenance_quality_policy import score

FIXTURES = Path(__file__).parent / "fixtures/batch_concept_compile_830_g3"


def quality_bundle() -> Any:
    original = c.validate_batch_candidate(
        gzip.decompress((FIXTURES / "content-provenance-candidate.json.gz").read_bytes())
    )
    payload = original.request.model_dump(mode="json", exclude={"request_sha256"})
    payload.pop("knowledge_update_policy", None)
    payload["quality_policy"] = QUALITY_POLICY
    payload["request_sha256"] = c._batch_sha256(original.request.contract, payload)
    request = c.BatchConceptCompileRequest830G3V1.model_validate(payload)
    previous = original.model_compile_result.output
    definitions = tuple(
        row.model_copy(update={"canonical_key": row.canonical_key + "-quality"})
        for row in previous.definitions
    )
    mapping = {
        old.concept_id: new.concept_id
        for old, new in zip(previous.definitions, definitions, strict=True)
    }
    pages = tuple(
        row.model_copy(
            update={
                "stable_key": row.stable_key + "-quality",
                "concept_ids": tuple(
                    sorted({*mapping.values(), *(mapping.get(key, key) for key in row.concept_ids)})
                ),
            }
        )
        for row in previous.pages
    )
    audit = tuple(row for row in previous.audit if row.disposition != "update") + tuple(
        AuditDisposition(key=key, disposition="new_page", reason="SYNTHETIC_QUALITY_FIXTURE")
        for key in (*mapping.values(), *(free_page_id(row) for row in pages))
    )
    output = previous.model_copy(
        update={"definitions": definitions, "pages": pages, "audit": audit}
    )
    delta = c.record_model_compile(
        request,
        output,
        run_id="quality-synthetic-compile",
        implementation="synthetic-quality-fixture",
        raw=c._canonical_json(output),
    )
    final = c.compose_batch_output(request, delta)
    composed = c.record_composed_output(request, delta, final, run_id="quality-synthetic-compose")
    members = {row.concept_id: row for row in final.definitions} | {
        free_page_id(row): row for row in final.pages
    }
    scores = {
        key: score(71 if not members[key].evidence else 100, 0 if not members[key].evidence else 20)
        for key in c.changed_knowledge_member_ids(request, final)
    }
    reviewed = ReviewOutput(
        request_hash=c.compile_request_hash_g3(request.base_request),
        output_hash=c.compile_output_hash_g3(final),
        decision="PASS",
        page_scores=scores,
        reasons=("SYNTHETIC_PROTOCOL_FIXTURE_NOT_MODEL_REVIEW",),
    )
    raw = c._canonical_json(reviewed)
    review = ReviewResult(
        output=reviewed,
        execution=ExecutionRecord(
            run_id="quality-synthetic-review",
            implementation="synthetic-quality-review",
            context_hash=c._batch_sha256(
                "batch-concept-review-context.830.g3.v1", c.review_context_g3(request, final)
            ),
            raw_output=raw,
            raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
        ),
    )
    return c.assemble_candidate_bundle(
        request, delta, composed, review, c.knowledge_admission_g3(request, final, reviewed)
    )


def test_quality_candidate_matches_shared_vector() -> None:
    bundle = quality_bundle()
    assert bundle.request.knowledge_update_policy is None
    assert not bundle.admission.pending_page_ids
    raw = gzip.decompress((FIXTURES / "quality-policy-candidate.json.gz").read_bytes())
    assert raw == c._canonical_json(bundle).encode()
    assert c.validate_batch_candidate(raw) == bundle


@pytest.mark.parametrize("mode", ["missing", "extra", "stale_pending", "source_score"])
def test_fully_rehashed_candidate_cannot_bypass_quality(mode: str) -> None:
    bundle = quality_bundle()
    checked = bundle.review_result.output
    scores = dict(checked.page_scores)
    key = next(key for key, value in scores.items() if value.evidence_quality == 0)
    admission = bundle.admission
    if mode == "missing":
        scores.pop(key)
    if mode == "extra":
        scores["unrelated"] = score(80)
    if mode == "source_score":
        scores[key] = score(80, 20)
    if mode == "stale_pending":
        admission = admission.model_copy(update={"pending_page_ids": (key,)})
    checked = checked.model_copy(update={"page_scores": scores})
    raw = c._canonical_json(checked)
    review = bundle.review_result.model_copy(
        update={
            "output": checked,
            "execution": bundle.review_result.execution.model_copy(
                update={
                    "raw_output": raw,
                    "raw_output_hash": hashlib.sha256(raw.encode()).hexdigest(),
                }
            ),
        }
    )
    with pytest.raises(ValueError):
        c.assemble_candidate_bundle(
            bundle.request, bundle.model_compile_result, bundle.compile_result, review, admission
        )
