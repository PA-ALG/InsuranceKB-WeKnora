"""Recovery contracts for the independent source discovery windows."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from insurance_harness.product_ingestion import discovery
from insurance_harness.product_ingestion.discovery_stage import run_discovery_generation_stage
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_independent_discovery import _proposal

pytest_plugins = ("tests.product_ingestion.test_discovery",)


@pytest.mark.asyncio
@pytest.mark.parametrize("recorded, diagnostic", [
    (True, None), (False, None), (True, "provider failure"),
])
async def test_recovery_replays_recorded_window_and_never_resends_unknown(
    case, recorded, diagnostic,
):
    request, _delta, entity_id = case
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    context = discovery.render_independent_discovery_contexts(
        request=request, entity_id=entity_id, exclusion_index=index,
        max_context_bytes=100_000,
    )[0]
    payload = json_bytes(context)
    response = json_bytes(_proposal(context)).decode()
    raw = json_bytes({"choices": [{"message": {"content": response}}]})
    operation = "independent-discovery-window-" + hashlib.sha256(json_bytes([
        entity_id, context["window"]["window_id"]
    ])).hexdigest()
    call = SimpleNamespace(
        run_id="prior",
        stage_key="discovery",
        operation_key=operation,
        input_sha256=hashlib.sha256(payload).hexdigest(),
        prompt_policy_sha256=hashlib.sha256(discovery.INDEPENDENT_DISCOVERY_PROMPT).hexdigest(),
        dispatched_at=object(), state="recorded" if recorded else "dispatched",
        raw=raw if recorded else None,
        raw_sha256=hashlib.sha256(raw).hexdigest() if recorded else None,
        call_id="prior-window-call",
        diagnostic=diagnostic,
    )

    class NoResend:
        async def execute_stage_call(self, **_kwargs):
            pytest.fail("recorded or unknown prior window must not redispatch")

    template = SimpleNamespace(
        role="extract", purpose="g3-independent-discovery",
        prompt_sha256=hashlib.sha256(discovery.INDEPENDENT_DISCOVERY_PROMPT).hexdigest(),
        max_context_bytes=100_000, template_id="independent-discovery",
    )
    result = await run_discovery_generation_stage(
        service=SimpleNamespace(
            configuration=SimpleNamespace(model=SimpleNamespace(templates=[template])),
            model_executor=NoResend(),
        ),
        artifacts=SimpleNamespace(list_stage_calls=lambda **_kwargs: (call,)),
        scope=None, run=SimpleNamespace(run_id="retry", retry_of_run_id="prior"),
        stage=SimpleNamespace(dependency_sha256="b" * 64), job=object(),
        request=request, entity_id=entity_id, exclusion_index=index,
    )
    summary = json.loads(next(
        row.payload for row in result.drafts
        if row.artifact_kind == "discovery_summary"
    ))
    if recorded and not diagnostic:
        assert summary["state"] == "GENERATED"
        assert summary["reused"] is True
        assert summary["call_ids"] == ["prior-window-call"]
    else:
        assert summary["state"] == "FAILED"
        assert "OUTCOME_UNKNOWN" in summary["failure_detail"]
        assert summary["call_ids"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("semantic", [None, []])
async def test_nonobject_generation_is_optional_failure_not_stage_dead_letter(case, semantic):
    request, _delta, entity_id = case
    index = discovery.build_discovery_exclusion_index(request, entity_id)

    class MalformedExecutor:
        async def execute_stage_call(self, **_kwargs):
            raw = json_bytes({"choices": [{"message": {"content": semantic}}]})
            return SimpleNamespace(state="recorded", raw=raw, call_id="malformed-call",
                                   diagnostic=None, policy_receipt=object())

    template = SimpleNamespace(
        role="extract", purpose="g3-independent-discovery",
        prompt_sha256=hashlib.sha256(discovery.INDEPENDENT_DISCOVERY_PROMPT).hexdigest(),
        max_context_bytes=100_000, template_id="independent-discovery",
    )
    result = await run_discovery_generation_stage(
        service=SimpleNamespace(
            configuration=SimpleNamespace(model=SimpleNamespace(templates=[template])),
            model_executor=MalformedExecutor(),
        ),
        artifacts=SimpleNamespace(list_stage_calls=lambda **_kwargs: ()),
        scope=None, run=SimpleNamespace(run_id="malformed", retry_of_run_id=None),
        stage=SimpleNamespace(dependency_sha256="b" * 64), job=object(),
        request=request, entity_id=entity_id, exclusion_index=index,
    )
    drafts = {row.artifact_kind: json.loads(row.payload) for row in result.drafts
              if row.artifact_key == "product"}
    assert drafts["discovery_summary"]["state"] == "FAILED"
    assert drafts["discovery_delta"]["output"]["pages"] == []
    assert drafts["discovery_summary"]["call_ids"] == ["malformed-call"]


@pytest.mark.asyncio
async def test_predispatch_entity_failure_aggregates_partial_without_dead_letter(case):
    request, _delta, _entity_id = case
    result = await run_discovery_generation_stage(
        service=SimpleNamespace(
            configuration=SimpleNamespace(model=SimpleNamespace(templates=[])),
            model_executor=None,
        ),
        artifacts=SimpleNamespace(list_stage_calls=lambda **_kwargs: ()),
        scope=None, run=SimpleNamespace(run_id="no-template", retry_of_run_id=None),
        stage=SimpleNamespace(dependency_sha256="b" * 64), job=object(),
        request=request,
    )
    summary = json.loads(next(
        row.payload for row in result.drafts
        if row.artifact_kind == "discovery_summary" and row.artifact_key == "product"
    ))
    assert summary["state"] == "FAILED"
    assert summary["coverage"]["complete"] is False
    assert summary["call_ids"] == []


@pytest.mark.asyncio
async def test_base_only_entity_has_zero_current_windows_not_generation_failure(case):
    request, _delta, entity_id = case
    request = request.model_copy(update={
        "resolution_inputs": SimpleNamespace(corpus=SimpleNamespace(entries=[]))
    })
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    result = await run_discovery_generation_stage(
        service=SimpleNamespace(configuration=SimpleNamespace(model=None), model_executor=None),
        artifacts=SimpleNamespace(list_stage_calls=lambda **_kwargs: ()),
        scope=None, run=SimpleNamespace(run_id="base-only", retry_of_run_id=None),
        stage=SimpleNamespace(dependency_sha256="b" * 64), job=object(),
        request=request, entity_id=entity_id, exclusion_index=index,
    )
    summary = json.loads(next(
        row.payload for row in result.drafts
        if row.artifact_kind == "discovery_summary"
    ))
    assert summary["state"] == "EMPTY"
    assert summary["coverage"]["complete"] is True
    assert summary["coverage"]["window_count"] == 0
