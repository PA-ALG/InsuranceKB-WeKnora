"""The existing final review must see generated/source-supported boundaries."""

from __future__ import annotations

from typing import Any, cast

import pytest

from insurance_harness.jobs.models import JobSnapshot
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import compile_output_hash_g3
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    FreeWikiPage,
    free_page_content,
)
from insurance_harness.product_ingestion import discovery
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.composition import ProductScopeServices
from insurance_harness.product_ingestion.models import ProductRunSnapshot, StageSnapshot
from tests.product_ingestion.test_discovery_local_dependencies import _review_case

pytest_plugins = ("tests.product_ingestion.test_discovery",)


def review_case(case: Any, *, pure: bool = False) -> tuple[Any, ...]:
    request, entity, page, output, candidates = _review_case(case)
    value = page.model_dump(mode="json")
    if pure:
        value["evidence"] = []
        value["body"] = "可先按办理目的整理资料，便于理解。"
    content = free_page_content(FreeWikiPage.model_validate(value)) if not pure else value["body"]
    value["content_provenance"] = {
        "contract": "knowledge-content-provenance.830.v1",
        "segments": [
            {
                "text": content,
                "origin": "MODEL_GENERATED" if pure else "SOURCE_SUPPORTED",
                "evidence_indexes": [] if pure else list(range(len(page.evidence))),
            }
        ],
    }
    if not pure:
        value["body"] += "\n可按办理目的整理资料。"
        value["content_provenance"]["segments"] = [
            {
                "text": page.body,
                "origin": "SOURCE_SUPPORTED",
                "evidence_indexes": list(range(len(page.evidence))),
            },
            {
                "text": "\n可按办理目的整理资料。",
                "origin": "MODEL_GENERATED",
                "evidence_indexes": [],
            },
        ]
    page = FreeWikiPage.model_validate(value)
    output = output.model_copy(update={"pages": (page,), "transformation": "SYNTHESIZE"})
    candidates["output"] = output.model_dump(mode="json")
    if pure:
        candidates["dispositions"][0]["evidence"] = []
        candidates["sources"] = []
    return request, entity, page, output, candidates


def render(values: tuple[Any, ...], **kwargs: Any) -> dict[str, Any]:
    request, entity, _page, output, candidates = values
    return discovery.render_independent_discovery_review_context(
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
        discovery_candidates=candidates,
        final_composed_output=output,
        final_composed_output_hash=compile_output_hash_g3(output),
        **kwargs,
    )


@pytest.mark.parametrize("pure", [False, True])
def test_review_exposes_exact_content_provenance_and_verified_evidence(
    case: Any, pure: bool
) -> None:
    values = review_case(case, pure=pure)
    context = render(values)
    page = values[2]
    assert context["contract"] == "product-discovery-review-context.830.v5"
    member = context["candidate_members"][0]
    assert member["content_provenance"] == page.content_provenance.model_dump(mode="json")
    assert member["rendered_content"] == free_page_content(page)
    assert [e["quote"] for e in member["evidence"]] == [e.quote for e in page.evidence]
    assert [e["evidence_index"] for e in member["evidence"]] == list(range(len(page.evidence)))
    assert bool(context["candidate_source_options"]) != pure


@pytest.mark.parametrize("version", ["v3", "v4"])
def test_provenance_cannot_be_hidden_by_legacy_review(case: Any, version: str) -> None:
    with pytest.raises(ValueError, match="provenance requires"):
        render(review_case(case), context_version="product-discovery-review-context.830." + version)


def test_legacy_review_remains_byte_identical(case: Any) -> None:
    values = _review_case(case)
    assert render(values) == render(
        values, context_version="product-discovery-review-context.830.v4"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", [False, True])
@pytest.mark.parametrize("evidence_score", [0, 20])
@pytest.mark.parametrize("disposition_decision", ["ACCEPT", "REJECT", "NEEDS_HUMAN"])
async def test_final_review_uses_authorized_provenance_policy_and_honest_score(
    case: Any,
    parent: bool,
    evidence_score: int,
    disposition_decision: str,
) -> None:
    import json
    from types import SimpleNamespace

    from insurance_harness.product_ingestion.discovery_composition import compose_discovery_review
    from insurance_harness.product_ingestion.discovery_stage import (
        run_independent_discovery_final_review,
    )
    from insurance_harness.product_ingestion.stages import json_bytes
    from tests.product_ingestion.test_discovery_replay_custody import _parent_call, _service

    values = review_case(case, pure=True)
    request, entity, _page, output, candidates = values
    if disposition_decision != "ACCEPT":
        # A field value dressed up with a new article title still needs a
        # semantic reviewer decision; successful projection is not authority.
        value = next(
            f.value for f in case[1].output.fields if f.entity_id == entity and f.value is not None
        )
        page_data = _page.model_dump(mode="json")
        page_data.update(title="产品信息阅读指引", body=value)
        page_data["content_provenance"]["segments"][0]["text"] = value
        page = FreeWikiPage.model_validate(page_data)
        output = output.model_copy(update={"pages": (page,)})
        candidates["output"] = output.model_dump(mode="json")
        candidates["dispositions"][0]["text"] = value
        values = request, entity, page, output, candidates
    context = render(values, max_context_bytes=300000)
    score = dict(
        business_value=25,
        reuse=20,
        evidence_quality=evidence_score,
        definability=15,
        novel_identity=10,
        name_stability=10,
    )
    response = {
        "contract": "product-discovery-review.830.v1",
        "review": {
            "request_hash": context["request_hash"],
            "output_hash": context["output_hash"],
            "decision": "PASS",
            "reasons": [],
            "page_scores": {identity: score for identity in context["review_member_ids"]},
        },
        "disposition_checks": [
            {
                "candidate_id": row["candidate_id"],
                "decision": disposition_decision,
                "reason": "Useful supplementary explanation"
                if disposition_decision == "ACCEPT"
                else "The proposed explanation restates a Schema field; no independent meaning.",
            }
            for row in candidates["dispositions"]
        ],
    }
    raw = json_bytes({"choices": [{"message": {"content": json.dumps(response)}}]})
    service = _service(
        role="verify",
        purpose="g3-provenance-discovery-review",
        prompt=discovery.PROVENANCE_DISCOVERY_REVIEW_PROMPT,
        new_raw=raw,
    )
    record = _parent_call(
        stage_key="compilation",
        operation="independent-discovery-final-review-" + context["output_hash"],
        content=json_bytes(context),
        prompt=discovery.PROVENANCE_DISCOVERY_REVIEW_PROMPT,
        raw=raw,
    )
    record.diagnostic = None
    outcome = await run_independent_discovery_final_review(
        service=cast(ProductScopeServices, service),
        artifacts=cast(
            ProductArtifactStore,
            SimpleNamespace(list_stage_calls=lambda **kwargs: [record] if parent else []),
        ),
        scope=service.configuration.model.scope,
        run=cast(
            ProductRunSnapshot,
            SimpleNamespace(run_id="child", retry_of_run_id="parent-run" if parent else None),
        ),
        stage=cast(StageSnapshot, SimpleNamespace(dependency_sha256="b" * 64)),
        job=cast(JobSnapshot, object()),
        request=request,
        discovery_candidates=candidates,
        final_composed_output=output,
        final_composed_output_hash=context["output_hash"],
        entity_id=entity,
    )
    if evidence_score:
        assert outcome.decision == "FAILED"
        assert "evidence score" in outcome.summary["failure_detail"]
    elif disposition_decision != "ACCEPT":
        assert outcome.decision == ("REJECTED" if disposition_decision == "REJECT" else "PENDING")
        with pytest.raises(ValueError, match="not accepted as an exact group"):
            compose_discovery_review(
                request=request,
                final_output=output,
                free_output=output,
                outcome=outcome,
                run_id="child",
            )
    else:
        assert outcome.decision == "ACCEPTED", outcome.summary
        compose_discovery_review(
            request=request,
            final_output=output,
            free_output=output,
            outcome=outcome,
            run_id="child",
        )
        assert len(service.model_executor.calls) == (0 if parent else 1)
        if not parent:
            assert (
                service.model_executor.calls[0]["prompt"]
                == discovery.PROVENANCE_DISCOVERY_REVIEW_PROMPT
            )
