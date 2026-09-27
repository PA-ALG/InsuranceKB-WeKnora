"""Synthetic v4 admission → v9 review → existing complete candidate protocol.

No provider or semantic-quality claim is made by this software test.
"""

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from insurance_harness.jobs.models import JobSnapshot
from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.composition import ProductScopeServices
from insurance_harness.product_ingestion.discovery import (
    build_discovery_exclusion_index,
    render_independent_discovery_review_context,
)
from insurance_harness.product_ingestion.discovery_composition import (
    compose_discovery_review,
    merge_discovery_delta,
)
from insurance_harness.product_ingestion.discovery_stage import (
    run_independent_discovery_final_review,
)
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductScope,
    StageSnapshot,
)
from insurance_harness.product_ingestion.native_admission_context import (
    render_native_admission_context,
)
from insurance_harness.product_ingestion.relation_review import (
    RELATION_REVIEW_PROMPT,
    RELATION_REVIEW_PURPOSE,
)
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_discovery_replay_custody import _parent_call, _service
from tests.product_ingestion.test_native_admission import inputs
from tests.product_ingestion.test_native_relation_admission import (
    CAPABILITY,
    relation_sample,
    run_relation,
)

pytest_plugins = ("tests.product_ingestion.test_discovery",)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["new", "parent", "stale_context", "unknown"])
async def test_normal_relation_reaches_full_candidate_and_reuses_exact_review(
    case: Any, mode: str
) -> None:
    _, _, _, _, _, payload = relation_sample(case)
    request, entity, snapshot, source = inputs(case)
    ctx = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy="candidate-dependencies.830.v1",
        isolation_enabled=True,
        relation_capability=CAPABILITY,
    )
    for row in (*payload["definitions"], *payload["pages"]):
        row["body"] = source.blocks[0].text
        row["content_provenance"]["segments"][0]["text"] = row["body"]
    admission = run_relation((request, entity, snapshot, source, ctx, payload))
    assert admission.failure is None
    free = admission.projection.output
    merged = merge_discovery_delta(
        request=request, field_delta=case[1], free_output=free, run_id="relation"
    )
    final = compiler.compose_batch_output(request, merged)
    final_hash = compiler.compile_output_hash_g3(final)
    candidates = {
        "output": free.model_dump(mode="json"),
        "sources": ctx["source_options"],
        "dispositions": admission.projection.dispositions,
        "dependency_selection": admission.projection.dependency_selection,
    }
    index = build_discovery_exclusion_index(request, entity)
    context = render_independent_discovery_review_context(
        request=request,
        entity_id=entity,
        exclusion_index=index,
        discovery_candidates=candidates,
        final_composed_output=final,
        final_composed_output_hash=final_hash,
        max_context_bytes=300000,
    )
    score = dict(
        business_value=25,
        reuse=20,
        evidence_quality=20,
        definability=15,
        novel_identity=10,
        name_stability=10,
    )
    response = {
        "contract": "product-discovery-review.830.v1",
        "review": {
            "contract": "concept-review-output.830.g2.v1",
            "request_hash": context["request_hash"],
            "output_hash": final_hash,
            "decision": "PASS",
            "reasons": ["synthetic protocol fixture"],
            "page_scores": {key: score for key in context["review_member_ids"]},
        },
        "disposition_checks": [
            {
                "candidate_id": row["candidate_id"],
                "decision": "ACCEPT",
                "reason": "synthetic protocol fixture",
            }
            for row in context["dispositions"]
        ],
    }
    raw = json_bytes({"choices": [{"message": {"content": json.dumps(response)}}]})
    service = _service(
        role="verify",
        purpose=RELATION_REVIEW_PURPOSE,
        prompt=RELATION_REVIEW_PROMPT,
        new_raw=raw if mode in {"new", "stale_context"} else None,
    )
    scope = ProductScope(
        tenant_id=str(request.base_request.tenant_id),
        space_id=request.base_request.space_id,
        raw_knowledge_base_id=request.base_request.raw_kb_id,
        wiki_knowledge_base_id=request.base_request.wiki_kb_id,
    )
    service.configuration.model.scope = scope
    prior_context = dict(context)
    if mode == "stale_context":
        prior_context["relation_predicates"] = {"benefit_reduced_by_advance_payment": "changed"}
    prior = _parent_call(
        stage_key="compilation",
        operation="independent-discovery-final-review-" + final_hash,
        content=json_bytes(prior_context),
        prompt=RELATION_REVIEW_PROMPT,
        raw=raw,
    )
    prior.diagnostic = None
    if mode == "unknown":
        prior.state = "dispatched"
    outcome = await run_independent_discovery_final_review(
        service=cast(ProductScopeServices, service),
        artifacts=cast(
            ProductArtifactStore, SimpleNamespace(list_stage_calls=lambda **kw: [prior])
        ),
        scope=scope,
        run=cast(
            ProductRunSnapshot,
            SimpleNamespace(
                run_id="review-child", retry_of_run_id=None if mode == "new" else "parent-run"
            ),
        ),
        stage=cast(StageSnapshot, SimpleNamespace(dependency_sha256="f" * 64)),
        job=cast(JobSnapshot, SimpleNamespace()),
        request=request,
        discovery_candidates=candidates,
        final_composed_output=final,
        final_composed_output_hash=final_hash,
        exclusion_index=index,
        entity_id=entity,
    )
    assert len(service.model_executor.calls) == (1 if mode in {"new", "stale_context"} else 0)
    if mode == "unknown":
        assert outcome.decision == "FAILED"
        return
    assert outcome.decision == "ACCEPTED", outcome.summary
    review = compose_discovery_review(
        request=request,
        final_output=final,
        free_output=free,
        outcome=outcome,
        run_id="review-child",
    )
    compiled = compiler.record_composed_output(request, merged, final, run_id="relation-final")
    bundle = compiler.assemble_candidate_bundle(
        request,
        merged,
        compiled,
        review,
        compiler.knowledge_admission_g3(request, final, review.output),
    )
    assert compiler.validate_batch_candidate(compiler._canonical_json(bundle).encode()) == bundle
    members = [m for m in bundle.page_manifest.members if m.payload.get("business_relation")]
    assert len(members) == 1
    assert members[0].member_id in bundle.review_result.output.page_scores
    assert outcome.summary["reused"] is (mode == "parent")
