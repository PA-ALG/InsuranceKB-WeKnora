"""G3 admission uses applicable dimensions without changing raw model scores."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    CompileOutput,
    ReviewOutput,
    ValueScore,
    free_page_id,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import FreeWikiPage
from tests.test_knowledge_content_provenance import page

POLICY = "provenance-applicable-score.830.v1"


@pytest.fixture(scope="module")
def compile_request() -> Any:
    path = Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
    return compiler.validate_batch_candidate(path.read_bytes()).request


def score(total: int, evidence: int = 0) -> ValueScore:
    remaining = total - evidence
    values = {"evidence_quality": evidence}
    for key, maximum in (
        ("business_value", 25),
        ("reuse", 20),
        ("definability", 15),
        ("novel_identity", 10),
        ("name_stability", 10),
    ):
        values[key] = min(remaining, maximum)
        remaining -= values[key]
    assert remaining == 0
    return ValueScore(**values)


def admission_case(request: Any, total: int, policy: str | None = POLICY) -> tuple[Any, ...]:
    current = request.model_copy(update={"quality_policy": policy})
    member = FreeWikiPage.model_validate(page())
    output = CompileOutput(
        request_hash="a" * 64, fields=(), pages=(member,), transformation="SYNTHESIZE"
    )
    key = free_page_id(member)
    review = ReviewOutput(
        request_hash="a" * 64,
        output_hash="b" * 64,
        decision="PASS",
        page_scores={key: score(total)},
    )
    return current, output, review, key


@pytest.mark.parametrize("total,pending", [(48, True), (63, True), (64, False), (71, False)])
def test_generated_admission_uses_applicable_eighty_points(
    compile_request: Any, total: int, pending: bool
) -> None:
    current, output, review, key = admission_case(compile_request, total)
    result = compiler.knowledge_admission_g3(current, output, review)
    assert result.pending_page_ids == ((key,) if pending else ())
    assert review.page_scores[key].total == total


def test_generated_below_sixty_percent_is_rejected(compile_request: Any) -> None:
    current, output, review, _ = admission_case(compile_request, 47)
    with pytest.raises(ValueError, match="PAGE_ADMISSION_REJECTED"):
        compiler.knowledge_admission_g3(current, output, review)


def test_legacy_seventy_one_remains_pending(compile_request: Any) -> None:
    current, output, review, key = admission_case(compile_request, 71, None)
    assert compiler.knowledge_admission_g3(current, output, review).pending_page_ids == (key,)


def test_generated_cannot_claim_evidence_points(compile_request: Any) -> None:
    current, output, review, key = admission_case(compile_request, 80)
    review = review.model_copy(update={"page_scores": {key: score(80, 20)}})
    with pytest.raises(ValueError):
        compiler.knowledge_admission_g3(current, output, review)


def test_new_policy_rejects_extra_scores_without_update_policy(compile_request: Any) -> None:
    current, output, review, _ = admission_case(compile_request, 80)
    assert current.knowledge_update_policy is None
    review = review.model_copy(
        update={"page_scores": {**review.page_scores, "unrelated": score(80)}}
    )
    with pytest.raises(ValueError, match="COVERAGE_MISMATCH"):
        compiler.knowledge_admission_g3(current, output, review)


@pytest.mark.parametrize("value", [None, "", "unknown-policy"])
def test_invalid_policy_is_rejected(compile_request: Any, value: Any) -> None:
    payload = compile_request.model_dump(mode="json")
    payload["quality_policy"] = value
    payload["request_sha256"] = compiler._batch_sha256(
        compile_request.contract, {k: v for k, v in payload.items() if k != "request_sha256"}
    )
    with pytest.raises(ValueError):
        compiler.BatchConceptCompileRequest830G3V1.model_validate(payload)


def test_policy_is_hashed_and_omission_preserves_legacy(compile_request: Any) -> None:
    legacy = compile_request.model_dump(mode="json")
    assert "quality_policy" not in legacy
    payload = {**legacy, "quality_policy": POLICY}
    payload["request_sha256"] = compiler._batch_sha256(
        compile_request.contract, {k: v for k, v in payload.items() if k != "request_sha256"}
    )
    current = compiler.BatchConceptCompileRequest830G3V1.model_validate(payload)
    assert current.request_sha256 != compile_request.request_sha256
    assert current.model_dump(mode="json")["quality_policy"] == POLICY
    assert compiler.BatchConceptCompileRequest830G3V1.model_validate(current) == current


@pytest.mark.parametrize(
    "total,expected",
    [(47, "REJECTED"), (48, "PENDING"), (63, "PENDING"), (64, "ACCEPTED"), (71, "ACCEPTED")],
)
def test_independent_review_agrees_with_admission(total: int, expected: str) -> None:
    from insurance_harness.product_ingestion.discovery_stage import _validated_independent_review

    member = page()
    context = {
        "contract": "product-discovery-review-context.830.v5",
        "quality_policy": POLICY,
        "request_hash": "a" * 64,
        "review_member_ids": ["member"],
        "dispositions": [],
        "candidate_members": [
            {**member, "member_id": "member", "rendered_content": member["body"]}
        ],
    }
    raw = {
        "contract": "product-discovery-review.830.v1",
        "review": {
            "request_hash": "a" * 64,
            "output_hash": "b" * 64,
            "decision": "PASS",
            "page_scores": {"member": score(total).model_dump()},
        },
        "disposition_checks": [],
    }
    assert (
        _validated_independent_review(raw, context=context, final_composed_output_hash="b" * 64)[2]
        == expected
    )


@pytest.mark.parametrize("decision,expected", [("REJECT", "REJECTED"), ("NEEDS_HUMAN", "PENDING")])
def test_model_decision_takes_precedence(decision: str, expected: str) -> None:
    from insurance_harness.product_ingestion.discovery_stage import _validated_independent_review

    member = page()
    context = {
        "contract": "product-discovery-review-context.830.v5",
        "quality_policy": POLICY,
        "request_hash": "a" * 64,
        "review_member_ids": ["member"],
        "dispositions": [],
        "candidate_members": [
            {**member, "member_id": "member", "rendered_content": member["body"]}
        ],
    }
    raw = {
        "contract": "product-discovery-review.830.v1",
        "review": {
            "request_hash": "a" * 64,
            "output_hash": "b" * 64,
            "decision": decision,
            "page_scores": {"member": score(80).model_dump()},
        },
        "disposition_checks": [],
    }
    assert (
        _validated_independent_review(raw, context=context, final_composed_output_hash="b" * 64)[2]
        == expected
    )


@pytest.mark.parametrize(
    "vector",
    __import__("json").loads(
        (
            Path(__file__).parent
            / "fixtures/batch_concept_compile_830_g3/quality-policy-vectors.json"
        ).read_text()
    ),
    ids=lambda row: row["name"],
)
def test_shared_quality_vectors(vector: Any) -> None:
    from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
        KnowledgeContentProvenance,
    )
    from insurance_harness.knowledge_compiler.knowledge_quality import (
        QualityContent,
        qualify_knowledge,
    )

    content = QualityContent(
        vector["content"],
        len(vector["evidence"]),
        KnowledgeContentProvenance.model_validate(vector["provenance"])
        if vector["provenance"] is not None
        else None,
    )
    if vector["error"]:
        with pytest.raises(ValueError):
            qualify_knowledge(
                vector["policy"] or None, content, ValueScore.model_validate(vector["score"])
            )
    else:
        result = qualify_knowledge(
            vector["policy"] or None, content, ValueScore.model_validate(vector["score"])
        )
        assert (result.applicable_max, result.band, result.raw_total) == (
            vector["maximum"],
            vector["band"],
            sum(vector["score"].values()),
        )


def test_legacy_model_display_omits_new_policy(compile_request: Any) -> None:
    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as bounded

    _sources, _refs, keys = bounded._g3_d_source_index(compile_request)
    value = bounded._g3_d_display_context(compile_request, keys)
    assert isinstance(value["semantic_request"], dict)
    assert "quality_policy" not in value["semantic_request"]
