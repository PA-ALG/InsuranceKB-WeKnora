"""The explicit native route covers windows once and preserves unsuccessful work."""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

from insurance_harness.product_ingestion.configuration import NativeDiscoverySettings
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.native_admission_stage import NativeAdmissionWindowOutcome
from insurance_harness.product_ingestion.native_discovery_stage import (
    NativeDiscoveryCollection,
    NativeDiscoveryFailure,
)
from insurance_harness.product_ingestion.stages import artifact, json_bytes
from tests.product_ingestion.test_native_admission import context, inputs, project, response

pytest_plugins = ("tests.product_ingestion.test_discovery",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "complete",
        "partial",
        "empty",
        "admission_failed",
        "preflight_failed",
        "PENDING",
        "REQUIRES_ENTITY_RESOLUTION",
    ],
)
async def test_native_stage_keeps_coverage_and_does_not_run_another_discovery(
    case: Any,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    request, entity, snapshot, source = inputs(case)
    block = source.blocks[0]
    entry = next(e for e in request.resolution_inputs.corpus.entries if block in e.blocks)
    # Keep one material's exact blocks for a bounded coordinator fixture.
    corpus = request.resolution_inputs.corpus.model_copy(update={"entries": (entry,)})
    request = request.model_copy(
        update={
            "resolution_inputs": request.resolution_inputs.model_copy(update={"corpus": corpus})
        }
    )
    values = (request, entity, snapshot, source)
    ctx = context(values)
    projection = project(values, ctx, response(ctx))
    if mode in {"PENDING", "REQUIRES_ENTITY_RESOLUTION"}:
        from insurance_harness.product_ingestion.native_admission_contract import (
            NativeAdmissionDecision,
        )

        projection = replace(
            projection,
            response=projection.response.model_copy(
                update={
                    "decisions": (
                        *projection.response.decisions,
                        NativeAdmissionDecision(
                            candidate_ref="c2",
                            decision=mode,
                            member_refs=(),
                            existing_target=None,
                            reason="待确定的必要依赖",
                        ),
                    ),
                }
            ),
        )
    if mode == "empty":
        snapshot = snapshot.model_copy(update={"candidates": ()})
    calls = {"collect": 0, "admit": 0}
    saved = artifact("native_candidate_snapshot", "fixture-window", b"saved", "a" * 64)

    async def collect(**kwargs: Any) -> NativeDiscoveryCollection:
        calls["collect"] += 1
        assert len(kwargs["sources"]) == 1
        return NativeDiscoveryCollection(
            mode != "partial",
            (snapshot,),
            (NativeDiscoveryFailure(block.knowledge_id, 1, "cite", "fixture-failed"),)
            if mode == "partial"
            else (),
            (saved,),
        )

    async def admit(**kwargs: Any) -> NativeAdmissionWindowOutcome:
        calls["admit"] += 1
        assert kwargs["entity_id"] == entity
        if mode == "preflight_failed":
            raise ValueError("fixture admission context too large")
        return NativeAdmissionWindowOutcome(
            None if mode == "admission_failed" else projection,
            (),
            "fixture-admission-failed" if mode == "admission_failed" else None,
        )

    module = importlib.import_module("insurance_harness.product_ingestion.native_pipeline")
    monkeypatch.setattr(module, "collect_native_discovery", collect)
    monkeypatch.setattr(module, "run_native_admission_window", admit)
    config = SimpleNamespace(
        native_discovery=NativeDiscoverySettings(
            policy="native-candidates.830.v1",
            language="zh-CN",
            granularity="standard",
            purpose="阅读",
        )
    )
    result = await module.run_native_discovery_stage(
        service=SimpleNamespace(configuration=config),
        artifacts=SimpleNamespace(),
        scope=SimpleNamespace(),
        run=SimpleNamespace(run_id="run", retry_of_run_id=None),
        stage=SimpleNamespace(dependency_sha256="a" * 64),
        job=SimpleNamespace(),
        request=request,
        sources={block.knowledge_id: source},
    )
    assert calls == {"collect": 1, "admit": 0 if mode == "empty" else 1}
    assert saved in result.drafts
    rows = {
        row.artifact_kind: json.loads(row.payload)
        for row in result.drafts
        if row.artifact_key == "product"
    }
    assert bool(rows["discovery_candidates"]["output"]["pages"]) == (mode == "complete")
    assert rows["discovery_candidates"]["output"]["fields"] == []
    assert result.state == (
        ProductRunState.SUCCEEDED
        if mode in {"complete", "empty"}
        else ProductRunState.PARTIAL_SUCCESS
    )
    assert rows["discovery_summary"]["native_coverage"]["complete"] == (
        mode in {"complete", "empty"}
    )
    if mode == "partial":
        assert rows["discovery_summary"]["coverage"] is None
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput
    from insurance_harness.product_ingestion.api import (
        _discovery_summary_projection,
        combine_discovery_summaries,
    )
    from insurance_harness.product_ingestion.discovery_stage import (
        run_independent_discovery_final_review,
    )

    shown = _discovery_summary_projection(json_bytes(rows["discovery_summary"]))
    assert shown["reason_codes"] != ["DISCOVERY_SUMMARY_INVALID"]
    if mode in {"PENDING", "REQUIRES_ENTITY_RESOLUTION"}:
        assert shown["state"] == "PENDING"
        empty = CompileOutput.model_validate(rows["discovery_candidates"]["output"])
        assert not empty.pages and not empty.definitions
        final = await run_independent_discovery_final_review(
            service=SimpleNamespace(),
            artifacts=SimpleNamespace(),
            scope=SimpleNamespace(),
            run=SimpleNamespace(),
            stage=SimpleNamespace(dependency_sha256="a" * 64),
            job=SimpleNamespace(),
            request=request,
            discovery_candidates=rows["discovery_candidates"],
            final_composed_output=empty,
            final_composed_output_hash="b" * 64,
        )
        assert final.decision == "EMPTY"  # No model call or accepted free members.
        combined = combine_discovery_summaries(
            json_bytes(rows["discovery_summary"]), json_bytes(final.summary)
        )
        assert _discovery_summary_projection(combined)["state"] == "PENDING"


def test_native_policy_change_cannot_reuse_an_old_task() -> None:
    module = importlib.import_module("insurance_harness.product_ingestion.native_pipeline")
    config = SimpleNamespace(
        native_discovery=NativeDiscoverySettings(
            policy="native-candidates.830.v1",
            language="zh-CN",
            granularity="standard",
            purpose="阅读",
        ),
        model=SimpleNamespace(policy_sha256="a" * 64),
        scope=SimpleNamespace(model_dump=lambda **kw: {"space_id": "space"}),
    )
    policy = module.native_discovery_policy(config)
    module.validate_native_discovery_policy(policy, json_bytes(policy))
    with pytest.raises(ValueError):
        module.validate_native_discovery_policy(policy, None)
    with pytest.raises(ValueError):
        module.validate_native_discovery_policy(None, json_bytes(policy))
    changed = {**policy, "model_policy_sha256": "b" * 64}
    with pytest.raises(ValueError):
        module.validate_native_discovery_policy(policy, json_bytes(changed))
    module.validate_native_discovery_policy(None, None)
