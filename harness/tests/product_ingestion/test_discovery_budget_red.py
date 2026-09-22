"""Recovery contracts for the independent source discovery windows."""

from __future__ import annotations

import hashlib
import json
import typing
from types import SimpleNamespace

import pytest

from insurance_harness.jobs.models import JobSnapshot
from insurance_harness.product_ingestion import discovery, discovery_stage
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.composition import ProductScopeServices
from insurance_harness.product_ingestion.discovery_stage import run_discovery_generation_stage
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductScope,
    StageSnapshot,
)
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_independent_discovery import _proposal

pytest_plugins = ("tests.product_ingestion.test_discovery",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "recorded, diagnostic",
    [
        (True, None),
        (False, None),
        (True, "provider failure"),
    ],
)
async def test_recovery_replays_recorded_window_and_never_resends_unknown(
    case: typing.Any,
    recorded: typing.Any,
    diagnostic: typing.Any,
) -> None:
    request, _delta, entity_id = case
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    context = discovery.render_independent_discovery_contexts(
        request=request,
        entity_id=entity_id,
        exclusion_index=index,
        max_context_bytes=100_000,
    )[0]
    payload = json_bytes(context)
    response = json_bytes(_proposal(context)).decode()
    raw = json_bytes({"choices": [{"message": {"content": response}}]})
    operation = (
        "independent-discovery-window-"
        + hashlib.sha256(json_bytes([entity_id, context["window"]["window_id"]])).hexdigest()
    )
    call = SimpleNamespace(
        run_id="prior",
        stage_key="discovery",
        operation_key=operation,
        input_sha256=hashlib.sha256(payload).hexdigest(),
        prompt_policy_sha256=hashlib.sha256(discovery.INDEPENDENT_DISCOVERY_PROMPT).hexdigest(),
        dispatched_at=object(),
        state="recorded" if recorded else "dispatched",
        raw=raw if recorded else None,
        raw_sha256=hashlib.sha256(raw).hexdigest() if recorded else None,
        call_id="prior-window-call",
        diagnostic=diagnostic,
    )

    class NoResend:
        async def execute_stage_call(self, **_kwargs: object) -> None:
            pytest.fail("recorded or unknown prior window must not redispatch")

    template = SimpleNamespace(
        role="extract",
        purpose="g3-independent-discovery",
        prompt_sha256=hashlib.sha256(discovery.INDEPENDENT_DISCOVERY_PROMPT).hexdigest(),
        max_context_bytes=100_000,
        template_id="independent-discovery",
    )
    result = await run_discovery_generation_stage(
        service=typing.cast(
            ProductScopeServices,
            SimpleNamespace(
                configuration=SimpleNamespace(model=SimpleNamespace(templates=[template])),
                model_executor=NoResend(),
            ),
        ),
        artifacts=typing.cast(
            ProductArtifactStore,
            SimpleNamespace(list_stage_calls=lambda **_kwargs: (call,)),
        ),
        scope=typing.cast(ProductScope, None),
        run=typing.cast(
            ProductRunSnapshot, SimpleNamespace(run_id="retry", retry_of_run_id="prior")
        ),
        stage=typing.cast(StageSnapshot, SimpleNamespace(dependency_sha256="b" * 64)),
        job=typing.cast(JobSnapshot, object()),
        request=request,
        entity_id=entity_id,
        exclusion_index=index,
    )
    summary = json.loads(
        next(row.payload for row in result.drafts if row.artifact_kind == "discovery_summary")
    )
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
async def test_nonobject_generation_is_optional_failure_not_stage_dead_letter(
    case: typing.Any, semantic: typing.Any
) -> None:
    request, _delta, entity_id = case
    index = discovery.build_discovery_exclusion_index(request, entity_id)

    class MalformedExecutor:
        async def execute_stage_call(self, **_kwargs: object) -> SimpleNamespace:
            raw = json_bytes({"choices": [{"message": {"content": semantic}}]})
            return SimpleNamespace(
                state="recorded",
                raw=raw,
                call_id="malformed-call",
                diagnostic=None,
                policy_receipt=object(),
            )

    template = SimpleNamespace(
        role="extract",
        purpose="g3-independent-discovery",
        prompt_sha256=hashlib.sha256(discovery.INDEPENDENT_DISCOVERY_PROMPT).hexdigest(),
        max_context_bytes=100_000,
        template_id="independent-discovery",
    )
    result = await run_discovery_generation_stage(
        service=typing.cast(
            ProductScopeServices,
            SimpleNamespace(
                configuration=SimpleNamespace(model=SimpleNamespace(templates=[template])),
                model_executor=MalformedExecutor(),
            ),
        ),
        artifacts=typing.cast(
            ProductArtifactStore, SimpleNamespace(list_stage_calls=lambda **_kwargs: ())
        ),
        scope=typing.cast(ProductScope, None),
        run=typing.cast(
            ProductRunSnapshot,
            SimpleNamespace(run_id="malformed", retry_of_run_id=None),
        ),
        stage=typing.cast(StageSnapshot, SimpleNamespace(dependency_sha256="b" * 64)),
        job=typing.cast(JobSnapshot, object()),
        request=request,
        entity_id=entity_id,
        exclusion_index=index,
    )
    drafts = {
        row.artifact_kind: json.loads(row.payload)
        for row in result.drafts
        if row.artifact_key == "product"
    }
    assert drafts["discovery_summary"]["state"] == "FAILED"
    assert drafts["discovery_delta"]["output"]["pages"] == []
    assert drafts["discovery_summary"]["call_ids"] == ["malformed-call"]


@pytest.mark.asyncio
async def test_predispatch_entity_failure_aggregates_partial_without_dead_letter(
    case: typing.Any,
) -> None:
    request, _delta, _entity_id = case
    result = await run_discovery_generation_stage(
        service=typing.cast(
            ProductScopeServices,
            SimpleNamespace(
                configuration=SimpleNamespace(model=SimpleNamespace(templates=[])),
                model_executor=None,
            ),
        ),
        artifacts=typing.cast(
            ProductArtifactStore, SimpleNamespace(list_stage_calls=lambda **_kwargs: ())
        ),
        scope=typing.cast(ProductScope, None),
        run=typing.cast(
            ProductRunSnapshot,
            SimpleNamespace(run_id="no-template", retry_of_run_id=None),
        ),
        stage=typing.cast(StageSnapshot, SimpleNamespace(dependency_sha256="b" * 64)),
        job=typing.cast(JobSnapshot, object()),
        request=request,
    )
    summary = json.loads(
        next(
            row.payload
            for row in result.drafts
            if row.artifact_kind == "discovery_summary" and row.artifact_key == "product"
        )
    )
    assert summary["state"] == "FAILED"
    assert summary["coverage"]["complete"] is False
    assert summary["call_ids"] == []


@pytest.mark.asyncio
async def test_base_only_entity_has_zero_current_windows_not_generation_failure(
    case: typing.Any,
) -> None:
    request, _delta, entity_id = case
    request = request.model_copy(
        update={"resolution_inputs": SimpleNamespace(corpus=SimpleNamespace(entries=[]))}
    )
    index = discovery.build_discovery_exclusion_index(request, entity_id)
    result = await run_discovery_generation_stage(
        service=typing.cast(
            ProductScopeServices,
            SimpleNamespace(configuration=SimpleNamespace(model=None), model_executor=None),
        ),
        artifacts=typing.cast(
            ProductArtifactStore, SimpleNamespace(list_stage_calls=lambda **_kwargs: ())
        ),
        scope=typing.cast(ProductScope, None),
        run=typing.cast(
            ProductRunSnapshot,
            SimpleNamespace(run_id="base-only", retry_of_run_id=None),
        ),
        stage=typing.cast(StageSnapshot, SimpleNamespace(dependency_sha256="b" * 64)),
        job=typing.cast(JobSnapshot, object()),
        request=request,
        entity_id=entity_id,
        exclusion_index=index,
    )
    summary = json.loads(
        next(row.payload for row in result.drafts if row.artifact_kind == "discovery_summary")
    )
    assert summary["state"] == "EMPTY"
    assert summary["coverage"]["complete"] is True
    assert summary["coverage"]["window_count"] == 0


@pytest.mark.asyncio
async def test_sent_and_verified_chars_diverge_when_second_window_response_fails(
    case: typing.Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, _delta, entity_id = case
    binding = next(row for row in request.entity_bindings if row.entity_id == entity_id)
    material_id = binding.source_material_ids[0]
    entry = next(
        row for row in request.resolution_inputs.corpus.entries if row.material_id == material_id
    )
    block = entry.blocks[0]
    longer = block.text + "附加原文条件。" * 500
    sources = tuple(
        source.model_copy(update={"text": longer})
        if source.revision_id == block.revision_id and source.block_id == block.block_id
        else source
        for source in request.base_request.sources
    )
    entries = tuple(
        row.model_copy(
            update={
                "blocks": tuple(
                    source.model_copy(update={"text": longer})
                    if source.block_id == block.block_id
                    else source
                    for source in row.blocks
                )
            }
        )
        if row.material_id == material_id
        else row
        for row in request.resolution_inputs.corpus.entries
    )
    request = request.model_copy(
        update={
            "base_request": request.base_request.model_copy(update={"sources": sources}),
            "resolution_inputs": request.resolution_inputs.model_copy(
                update={
                    "corpus": request.resolution_inputs.corpus.model_copy(
                        update={"entries": entries}
                    )
                }
            ),
        }
    )
    original = discovery.render_independent_discovery_contexts

    def two_windows(**kwargs: typing.Any) -> typing.Any:
        kwargs["max_source_chars"] = 2000
        result = original(**kwargs)
        assert len(result) == 2
        return result

    monkeypatch.setattr(discovery_stage, "render_independent_discovery_contexts", two_windows)

    class Executor:
        def __init__(self) -> None:
            self.calls: list[dict[str, typing.Any]] = []

        async def execute_stage_call(self, **kwargs: typing.Any) -> SimpleNamespace:
            self.calls.append(kwargs)
            context = json.loads(kwargs["content"])
            content = (
                json.dumps(_proposal(context)) if len(self.calls) == 1 else "```json\n{broken}\n```"
            )
            return SimpleNamespace(
                state="recorded",
                call_id=f"window-{len(self.calls)}",
                raw=json_bytes({"choices": [{"message": {"content": content}}]}),
                diagnostic=None,
                policy_receipt=object(),
            )

    executor = Executor()
    template = SimpleNamespace(
        role="extract",
        purpose="g3-independent-discovery",
        prompt_sha256=hashlib.sha256(discovery.INDEPENDENT_DISCOVERY_PROMPT).hexdigest(),
        max_context_bytes=100_000,
        template_id="independent-discovery",
    )
    result = await run_discovery_generation_stage(
        service=typing.cast(
            ProductScopeServices,
            SimpleNamespace(
                configuration=SimpleNamespace(model=SimpleNamespace(templates=[template])),
                model_executor=executor,
            ),
        ),
        artifacts=typing.cast(
            ProductArtifactStore, SimpleNamespace(list_stage_calls=lambda **_kwargs: ())
        ),
        scope=typing.cast(ProductScope, None),
        run=typing.cast(
            ProductRunSnapshot,
            SimpleNamespace(run_id="two-windows", retry_of_run_id=None),
        ),
        stage=typing.cast(StageSnapshot, SimpleNamespace(dependency_sha256="b" * 64)),
        job=typing.cast(JobSnapshot, object()),
        request=request,
        entity_id=entity_id,
    )
    summary = json.loads(
        next(
            row.payload
            for row in result.drafts
            if row.artifact_kind == "discovery_summary" and row.artifact_key == "product"
        )
    )
    assert len(executor.calls) == 2
    assert summary["state"] == "FAILED"
    assert summary["coverage"]["offered_chars"] == summary["coverage"]["total_chars"]
    assert summary["coverage"]["validated_chars"] < summary["coverage"]["offered_chars"]
    assert summary["coverage"]["omitted_chars"] == 0
    assert summary["coverage"]["complete"] is False
