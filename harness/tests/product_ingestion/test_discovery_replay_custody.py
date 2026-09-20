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


def _service(*, role, purpose, prompt, new_raw=None):
    class Executor:
        def __init__(self):
            self.calls = []

        async def execute_stage_call(self, **kwargs):
            self.calls.append(kwargs)
            if new_raw is None:
                raise AssertionError("valid recorded parent response must not be sent again")
            return SimpleNamespace(
                state="recorded", raw=new_raw, call_id="child-call",
                diagnostic=None, policy_receipt=object(),
            )

    template = SimpleNamespace(
        role=role, purpose=purpose,
        prompt_sha256=hashlib.sha256(prompt).hexdigest(),
        max_context_bytes=300_000, template_id="fixture-independent",
    )
    return SimpleNamespace(
        configuration=SimpleNamespace(model=SimpleNamespace(templates=[template])),
        model_executor=Executor(),
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
@pytest.mark.parametrize("parent_kind", [
    "valid", "fenced", "malformed", "semantic_invalid", "http_error",
    "unknown", "missing_raw", "tampered", "other_diagnostic",
])
async def test_generation_reuses_valid_parent_and_retries_only_received_bad_raw(
    case, api, factory, parent_kind,
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
    valid_raw = json.dumps({
        "choices": [{"message": {"content": json.dumps(response)}}]
    }).encode()
    content = json.dumps(response)
    if parent_kind == "fenced":
        content = "```json\n" + content + "\n```"
    elif parent_kind == "malformed":
        content = "```json\n{broken}\n```"
    elif parent_kind == "semantic_invalid":
        duplicate = _proposal(context, title=index["schema_fields"][0]["short_title"])
        content = json.dumps(duplicate)
    elif parent_kind == "http_error":
        content = json.dumps({"error": "service unavailable"})
    raw = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    parent = _parent_call(
        stage_key="discovery", operation=operation, content=json_bytes(context),
        prompt=discovery.INDEPENDENT_DISCOVERY_PROMPT, raw=raw,
    )
    if parent_kind == "http_error":
        parent.diagnostic = "provider_http_status"
    elif parent_kind == "unknown":
        parent.state = "dispatched"
    elif parent_kind == "missing_raw":
        parent.raw = None
        parent.raw_sha256 = None
        parent.diagnostic = "transport:TimeoutException"
    elif parent_kind == "tampered":
        parent.raw_sha256 = "0" * 64
    elif parent_kind == "other_diagnostic":
        parent.diagnostic = "transport:TimeoutException"
    artifacts.list_stage_calls = lambda **kwargs: (parent,)
    service = _service(
        role="extract", purpose="g3-independent-discovery",
        prompt=discovery.INDEPENDENT_DISCOVERY_PROMPT,
        new_raw=valid_raw,
    )
    output = await run_discovery_generation_stage(
        service=service,
        artifacts=artifacts, scope=_scope(),
        run=SimpleNamespace(run_id=child.run_id, retry_of_run_id="parent-run"),
        stage=products.list_stages(scope=_scope(), run_id=child.run_id)[0],
        job=running, request=request, entity_id=entity_id, exclusion_index=index,
    )
    summary = json.loads(next(row.payload for row in output.drafts
                              if row.artifact_kind == "discovery_summary"))
    if parent_kind in {"unknown", "missing_raw", "tampered", "other_diagnostic"}:
        assert summary["state"] == "FAILED"
        assert service.model_executor.calls == []
        return
    assert summary["state"] == "GENERATED"
    assert len(service.model_executor.calls) == (1 if parent_kind in {
        "malformed", "semantic_invalid", "http_error",
    } else 0)
    assert any(row.artifact_kind == "discovery_window_replay_receipt"
               for row in output.drafts) == (parent_kind in {"valid", "fenced"})
    if parent_kind in {"valid", "fenced"}:
        _settle_child(
            artifacts=artifacts, products=products, jobs=jobs,
            child=child, running=running, stage_key="discovery", drafts=output.drafts,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("parent_kind", [
    "valid", "fenced", "malformed", "semantic_invalid", "http_error",
    "pending", "rejected", "unknown", "missing_raw", "tampered", "other_diagnostic",
])
async def test_final_review_reuses_valid_parent_and_retries_only_received_bad_raw(
    case, api, factory, parent_kind,
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
    valid_raw = json.dumps({
        "choices": [{"message": {"content": json.dumps(response)}}]
    }).encode()
    if parent_kind == "pending":
        response["review"]["decision"] = "NEEDS_HUMAN"
        response["disposition_checks"][0]["decision"] = "NEEDS_HUMAN"
    elif parent_kind == "rejected":
        response["review"]["decision"] = "REJECT"
        response["disposition_checks"][0]["decision"] = "REJECT"
    content = json.dumps(response)
    if parent_kind == "fenced":
        content = "```json\n" + content + "\n```"
    elif parent_kind == "malformed":
        content = "```json\n{broken}\n```"
    elif parent_kind == "semantic_invalid":
        response["review"]["output_hash"] = "0" * 64
        content = json.dumps(response)
    elif parent_kind == "http_error":
        content = json.dumps({"error": "service unavailable"})
    raw = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
    parent = _parent_call(
        stage_key="compilation",
        operation="independent-discovery-final-review-" + final_hash,
        content=json_bytes(context), prompt=discovery.INDEPENDENT_DISCOVERY_REVIEW_PROMPT,
        raw=raw,
    )
    if parent_kind == "http_error":
        parent.diagnostic = "provider_http_status"
    elif parent_kind == "unknown":
        parent.state = "dispatched"
    elif parent_kind == "missing_raw":
        parent.raw = None
        parent.raw_sha256 = None
        parent.diagnostic = "transport:TimeoutException"
    elif parent_kind == "tampered":
        parent.raw_sha256 = "0" * 64
    elif parent_kind == "other_diagnostic":
        parent.diagnostic = "transport:TimeoutException"
    artifacts.list_stage_calls = lambda **kwargs: (parent,)
    service = _service(
        role="verify", purpose="g3-independent-discovery-review",
        prompt=discovery.INDEPENDENT_DISCOVERY_REVIEW_PROMPT,
        new_raw=valid_raw,
    )
    outcome = await run_independent_discovery_final_review(
        service=service,
        artifacts=artifacts, scope=_scope(),
        run=SimpleNamespace(run_id=child.run_id, retry_of_run_id="parent-run"),
        stage=products.list_stages(scope=_scope(), run_id=child.run_id)[0],
        job=running, request=request, discovery_candidates=candidates,
        final_composed_output=final, final_composed_output_hash=final_hash,
        exclusion_index=index, entity_id=entity_id,
    )
    if parent_kind in {"unknown", "missing_raw", "tampered", "other_diagnostic"}:
        assert outcome.decision == "FAILED"
        assert service.model_executor.calls == []
        return
    expected = {
        "pending": "PENDING", "rejected": "REJECTED",
    }.get(parent_kind, "ACCEPTED")
    assert outcome.decision == expected
    assert len(service.model_executor.calls) == (1 if parent_kind in {
        "malformed", "semantic_invalid", "http_error",
    } else 0)
    assert (outcome.replayed_call is parent) == (parent_kind in {
        "valid", "fenced", "pending", "rejected",
    })
    assert any(row.artifact_kind == "discovery_review_proof" for row in outcome.drafts)
    if parent_kind in {"valid", "fenced", "pending", "rejected"}:
        _settle_child(
            artifacts=artifacts, products=products, jobs=jobs,
            child=child, running=running, stage_key="compilation", drafts=outcome.drafts,
        )
