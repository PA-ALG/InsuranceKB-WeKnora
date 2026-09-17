"""Cross-run discovery replay stays a rule artifact under the child job fence."""

from __future__ import annotations

# ruff: noqa: F811 -- imported pytest fixtures
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput
from insurance_harness.product_ingestion import discovery
from insurance_harness.product_ingestion.artifact_models import ArtifactOrigin
from insurance_harness.product_ingestion.discovery_stage import (
    run_discovery_generation_stage,
    run_independent_discovery_final_review,
)
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_artifacts import _scope, _start_stage, api, factory  # noqa: F401
from tests.product_ingestion.test_independent_discovery import _proposal

pytest_plugins = ("tests.product_ingestion.test_discovery",)


def _parent_call(*, stage_key, operation, content, prompt, raw):
    return SimpleNamespace(
        run_id="parent-run", stage_key=stage_key, operation_key=operation,
        input_sha256=hashlib.sha256(content).hexdigest(),
        prompt_policy_sha256=hashlib.sha256(prompt).hexdigest(),
        state="recorded", dispatched_at=datetime.now(UTC), raw=raw,
        raw_sha256=hashlib.sha256(raw).hexdigest(), call_id="parent-call",
    )


def _service(*, role, purpose, prompt):
    class NoResend:
        async def execute_stage_call(self, **kwargs):
            raise AssertionError("recorded parent response must not be sent again")

    template = SimpleNamespace(
        role=role, purpose=purpose,
        prompt_sha256=hashlib.sha256(prompt).hexdigest(),
        max_context_bytes=300_000, template_id="fixture-independent",
    )
    return SimpleNamespace(
        configuration=SimpleNamespace(model=SimpleNamespace(templates=[template])),
        model_executor=NoResend(),
    )


def _settle_child(*, artifacts, products, jobs, child, running, stage_key, drafts):
    assert all(draft.origin is ArtifactOrigin.RULE for draft in drafts)
    assert all(draft.origin_call_id is None for draft in drafts)
    writes = artifacts.prepare_artifact_writes(
        scope=_scope(), run_id=child.run_id, stage_key=stage_key,
        job_id=running.id, generation=running.lease_generation, drafts=tuple(drafts),
    )
    stage = products.list_stages(scope=_scope(), run_id=child.run_id)[0]
    settlement = products.prepare_stage_settlement(
        scope=_scope(), run_id=child.run_id, stage_id=stage.stage_id,
        job_id=running.id, generation=running.lease_generation,
        state=ProductRunState.SUCCEEDED,
    )
    jobs.report_success(
        space_id=_scope().space_id, job_id=running.id,
        generation=running.lease_generation,
        domain_writes=writes + settlement.domain_writes,
        events=settlement.events,
    )
    assert products.list_stages(scope=_scope(), run_id=child.run_id)[0].state == "succeeded"


@pytest.mark.asyncio
async def test_recorded_generation_replay_settles_child_without_foreign_model_origin(
    case, api, factory,
):
    request, _field_delta, entity_id = case
    artifacts, products, jobs, child, running = _start_stage(
        api, factory, run_key="discovery-child", stage_key="discovery"
    )
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    context = discovery.render_independent_discovery_contexts(
        request=request, entity_id=entity_id, exclusion_index=index,
        max_context_bytes=300_000,
    )[0]
    window_id = context["window"]["window_id"]
    operation = "independent-discovery-window-" + hashlib.sha256(
        json_bytes([entity_id, window_id])
    ).hexdigest()
    response = _proposal(context)
    raw = json.dumps({"choices": [{"message": {"content": json.dumps(response)}}]}).encode()
    parent = _parent_call(
        stage_key="discovery", operation=operation, content=json_bytes(context),
        prompt=discovery.INDEPENDENT_DISCOVERY_PROMPT, raw=raw,
    )
    artifacts.list_stage_calls = lambda **kwargs: (parent,)
    output = await run_discovery_generation_stage(
        service=_service(
            role="extract", purpose="g3-independent-discovery",
            prompt=discovery.INDEPENDENT_DISCOVERY_PROMPT,
        ),
        artifacts=artifacts, scope=_scope(),
        run=SimpleNamespace(run_id=child.run_id, retry_of_run_id="parent-run"),
        stage=products.list_stages(scope=_scope(), run_id=child.run_id)[0],
        job=running, request=request, entity_id=entity_id, exclusion_index=index,
    )
    assert any(row.artifact_kind == "discovery_window_replay_receipt" for row in output.drafts)
    _settle_child(
        artifacts=artifacts, products=products, jobs=jobs,
        child=child, running=running, stage_key="discovery", drafts=output.drafts,
    )


@pytest.mark.asyncio
async def test_recorded_final_review_replay_settles_child_without_foreign_model_origin(
    case, api, factory,
):
    request, field_delta, entity_id = case
    artifacts, products, jobs, child, running = _start_stage(
        api, factory, run_key="review-child", stage_key="compilation"
    )
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    generation_context = discovery.render_independent_discovery_contexts(
        request=request, entity_id=entity_id, exclusion_index=index,
    )[0]
    candidate = discovery.project_independent_discovery_response(
        raw=discovery._bytes(_proposal(generation_context)), request=request,
        entity_id=entity_id, exclusion_index=index, context=generation_context,
    )
    free_output = candidate.output
    old = field_delta.output
    merged = CompileOutput(
        request_hash=old.request_hash,
        definitions=(*old.definitions, *free_output.definitions), fields=old.fields,
        pages=(*old.pages, *free_output.pages),
        audit=tuple(sorted((*old.audit, *free_output.audit), key=lambda row: row.key)),
        transformation="SYNTHESIZE",
    )
    delta = compiler.record_model_compile(
        request, merged, run_id="review-child",
        implementation="fixture-composed-discovery", raw=compiler._canonical_json(merged),
    )
    final = compiler.compose_batch_output(request, delta)
    final_hash = compiler.compile_output_hash_g3(final)
    candidate_id = generation_context["window"]["window_id"] + ":candidate-process"
    candidates = {
        "output": free_output.model_dump(mode="json"),
        "dispositions": [{
            **_proposal(generation_context)["dispositions"][0],
            "candidate_id": candidate_id,
            "member_id": compiler.free_page_id(free_output.pages[0]),
        }],
        "sources": [{
            "source_ref": generation_context["source_options"][0]["source_ref"],
            "spans": generation_context["source_options"][0]["spans"][:1],
        }],
    }
    context = discovery.render_independent_discovery_review_context(
        request=request, entity_id=entity_id, exclusion_index=index,
        discovery_candidates=candidates, final_composed_output=final,
        final_composed_output_hash=final_hash, max_context_bytes=300_000,
    )
    score = dict(
        business_value=25, reuse=20, evidence_quality=20,
        definability=15, novel_identity=10, name_stability=10,
    )
    response = {
        "contract": "product-discovery-review.830.v1",
        "review": {
            "contract": "concept-review-output.830.g2.v1",
            "request_hash": context["request_hash"], "output_hash": final_hash,
            "decision": "PASS", "reasons": ["Original evidence verified"],
            "page_scores": {key: score for key in context["review_member_ids"]},
        },
        "disposition_checks": [{
            "candidate_id": candidate_id,
            "decision": "ACCEPT", "reason": "Unique useful process",
        }],
    }
    raw = json.dumps({"choices": [{"message": {"content": json.dumps(response)}}]}).encode()
    parent = _parent_call(
        stage_key="compilation",
        operation="independent-discovery-final-review-" + final_hash,
        content=json_bytes(context), prompt=discovery.INDEPENDENT_DISCOVERY_REVIEW_PROMPT,
        raw=raw,
    )
    artifacts.list_stage_calls = lambda **kwargs: (parent,)
    outcome = await run_independent_discovery_final_review(
        service=_service(
            role="verify", purpose="g3-independent-discovery-review",
            prompt=discovery.INDEPENDENT_DISCOVERY_REVIEW_PROMPT,
        ),
        artifacts=artifacts, scope=_scope(),
        run=SimpleNamespace(run_id=child.run_id, retry_of_run_id="parent-run"),
        stage=products.list_stages(scope=_scope(), run_id=child.run_id)[0],
        job=running, request=request, discovery_candidates=candidates,
        final_composed_output=final, final_composed_output_hash=final_hash,
        exclusion_index=index, entity_id=entity_id,
    )
    assert outcome.decision == "ACCEPTED" and outcome.replayed_call is parent
    assert any(row.artifact_kind == "discovery_review_proof" for row in outcome.drafts)
    _settle_child(
        artifacts=artifacts, products=products, jobs=jobs,
        child=child, running=running, stage_key="compilation", drafts=outcome.drafts,
    )
