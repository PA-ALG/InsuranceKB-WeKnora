"""Discovery replay accounting verifies persisted parent calls and child receipts."""

from __future__ import annotations

# ruff: noqa: F811 -- imported pytest fixtures
import hashlib
import json
import typing

import pytest

from insurance_harness.product_ingestion import discovery
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.stages import artifact, json_bytes
from insurance_harness.product_ingestion.tables import ProductRun
from tests.product_ingestion.test_artifacts import _scope, _start_stage, api, factory  # noqa: F401


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _settle(
    artifacts: typing.Any,
    products: typing.Any,
    jobs: typing.Any,
    run: typing.Any,
    running: typing.Any,
    stage_key: str,
    drafts: typing.Any = (),
) -> None:
    writes = (
        artifacts.prepare_artifact_writes(
            scope=_scope(),
            run_id=run.run_id,
            stage_key=stage_key,
            job_id=running.id,
            generation=running.lease_generation,
            drafts=tuple(drafts),
        )
        if drafts
        else ()
    )
    stage = products.list_stages(scope=_scope(), run_id=run.run_id)[0]
    settlement = products.prepare_stage_settlement(
        scope=_scope(),
        run_id=run.run_id,
        stage_id=stage.stage_id,
        job_id=running.id,
        generation=running.lease_generation,
        state=ProductRunState.SUCCEEDED,
    )
    jobs.report_success(
        space_id=_scope().space_id,
        job_id=running.id,
        generation=running.lease_generation,
        domain_writes=writes + settlement.domain_writes,
        events=settlement.events,
    )


def _record_parent_call(
    api: typing.Any,
    factory: typing.Any,
    *,
    stage_key: str,
    operation: str,
    context: typing.Any,
    prompt: typing.Any,
    raw: bytes,
    call_id: str,
) -> typing.Any:
    artifacts, products, jobs, parent, running = _start_stage(
        api,
        factory,
        run_key="metrics-parent-" + call_id,
        stage_key=stage_key,
    )
    artifacts.reserve_stage_call(
        scope=_scope(),
        run_id=parent.run_id,
        stage_key=stage_key,
        operation_key=operation,
        dependency_sha256="a" * 64,
        job_id=running.id,
        generation=running.lease_generation,
        attempt=running.attempt,
        call_id=call_id,
        input_sha256=_digest(context),
        model_policy_sha256="b" * 64,
        prompt_policy_sha256=_digest(prompt),
    )
    request = b'{"provider":"fixture"}'
    artifacts.begin_stage_call(
        scope=_scope(),
        call_id=call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=_digest(request),
        request_bytes=request,
    )
    artifacts.record_stage_call_result(
        scope=_scope(),
        call_id=call_id,
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=_digest(request),
        raw=raw,
        diagnostic=None,
        usage={"input_tokens": 7, "output_tokens": 3},
    )
    _settle(artifacts, products, jobs, parent, running, stage_key)
    return parent


def _child(
    api: typing.Any,
    factory: typing.Any,
    *,
    stage_key: str,
    parent_run_id: typing.Any,
    run_key: typing.Any,
) -> tuple[typing.Any, ...]:
    artifacts, products, jobs, child, running = _start_stage(
        api,
        factory,
        run_key=run_key,
        stage_key=stage_key,
    )
    with factory() as session, session.begin():
        session.get(ProductRun, child.run_id).retry_of_run_id = parent_run_id
    return artifacts, products, jobs, child, running


def _rule(kind: str, key: str, value: typing.Any) -> typing.Any:
    return artifact(kind, key, json_bytes(value), "a" * 64)


def test_generation_replay_counts_real_parent_once_with_persisted_receipt(
    api: typing.Any, factory: typing.Any
) -> None:
    context = {"window": "same original source"}
    content = json_bytes(context)
    raw = b'{"choices": []}'
    operation = "independent-discovery-window-" + "c" * 64
    parent = _record_parent_call(
        api,
        factory,
        stage_key="discovery",
        operation=operation,
        context=content,
        prompt=discovery.INDEPENDENT_DISCOVERY_PROMPT,
        raw=raw,
        call_id="metrics-generation-call",
    )
    artifacts, products, jobs, child, running = _child(
        api,
        factory,
        stage_key="discovery",
        parent_run_id=parent.run_id,
        run_key="metrics-child-generation",
    )
    receipt = {
        "contract": "product-discovery-window-replay-receipt.830.v1",
        "replayed_from_run_id": parent.run_id,
        "source_call_id": "metrics-generation-call",
        "source_raw_sha256": _digest(raw),
        "source_stage_key": "discovery",
        "source_operation_key": operation,
        "source_input_sha256": _digest(content),
        "source_prompt_sha256": _digest(discovery.INDEPENDENT_DISCOVERY_PROMPT),
    }
    drafts = (
        _rule("discovery_context", "entity:window", context),
        _rule("discovery_window_replay_receipt", "entity:window", receipt),
    )
    _settle(artifacts, products, jobs, child, running, "discovery", drafts)
    metrics = artifacts.get_stage_call_metrics(scope=_scope(), run_id=child.run_id)
    assert metrics.model_call_count == 0
    assert metrics.reused_model_call_count == 1
    assert metrics.reused_usage == {"input_tokens": 7, "output_tokens": 3}
    assert artifacts.get_stage_call_metrics(scope=_scope(), run_id=child.run_id) == metrics


def test_review_replay_counts_real_parent_with_persisted_proof(
    api: typing.Any, factory: typing.Any
) -> None:
    context = {"final_composed_output_hash": "d" * 64}
    content = json_bytes(context)
    raw = json_bytes({"choices": []})
    parent = _record_parent_call(
        api,
        factory,
        stage_key="compilation",
        operation="independent-discovery-final-review-" + "d" * 64,
        context=content,
        prompt=discovery.INDEPENDENT_DISCOVERY_REVIEW_PROMPT,
        raw=raw,
        call_id="metrics-review-call",
    )
    artifacts, products, jobs, child, running = _child(
        api,
        factory,
        stage_key="compilation",
        parent_run_id=parent.run_id,
        run_key="metrics-child-review",
    )
    proof = {
        "contract": "product-discovery-review-proof.830.v1",
        "decision": "ACCEPTED",
        "final_composed_output_hash": "d" * 64,
        "actual_review_context_sha256": _digest(content),
        "actual_review_raw_sha256": _digest(raw),
        "model_call_id": "metrics-review-call",
        "replayed_from_run_id": parent.run_id,
        "source_call_id": "metrics-review-call",
        "source_raw_sha256": _digest(raw),
        "review": {},
        "disposition_checks": [],
    }
    drafts = (
        _rule("discovery_review_context", "product", context),
        _rule("discovery_review_response", "product", {"choices": []}),
        _rule("discovery_review_proof", "product", proof),
    )
    _settle(artifacts, products, jobs, child, running, "compilation", drafts)
    metrics = artifacts.get_stage_call_metrics(scope=_scope(), run_id=child.run_id)
    assert metrics.reused_model_call_count == 1
    assert metrics.reused_usage == {"input_tokens": 7, "output_tokens": 3}


@pytest.mark.parametrize(
    "tamper",
    [
        "source_raw_sha256",
        "source_prompt_sha256",
        "replayed_from_run_id",
    ],
)
def test_generation_replay_rejects_tampered_receipt(
    api: typing.Any, factory: typing.Any, tamper: typing.Any
) -> None:
    content = json_bytes({"window": "source"})
    raw = b'{"choices": []}'
    operation = "independent-discovery-window-" + "c" * 64
    parent = _record_parent_call(
        api,
        factory,
        stage_key="discovery",
        operation=operation,
        context=content,
        prompt=discovery.INDEPENDENT_DISCOVERY_PROMPT,
        raw=raw,
        call_id="metrics-tamper-call",
    )
    artifacts, products, jobs, child, running = _child(
        api,
        factory,
        stage_key="discovery",
        parent_run_id=parent.run_id,
        run_key="metrics-child-tamper",
    )
    receipt = {
        "contract": "product-discovery-window-replay-receipt.830.v1",
        "replayed_from_run_id": parent.run_id,
        "source_call_id": "metrics-tamper-call",
        "source_raw_sha256": _digest(raw),
        "source_stage_key": "discovery",
        "source_operation_key": operation,
        "source_input_sha256": _digest(content),
        "source_prompt_sha256": _digest(discovery.INDEPENDENT_DISCOVERY_PROMPT),
    }
    receipt[tamper] = "0" * 64
    _settle(
        artifacts,
        products,
        jobs,
        child,
        running,
        "discovery",
        (
            _rule("discovery_context", "entity:window", json.loads(content)),
            _rule("discovery_window_replay_receipt", "entity:window", receipt),
        ),
    )
    with pytest.raises(ValueError, match="discovery replay"):
        artifacts.get_stage_call_metrics(scope=_scope(), run_id=child.run_id)


def test_unrelated_rule_artifact_never_counts_as_replay(
    api: typing.Any, factory: typing.Any
) -> None:
    artifacts, products, jobs, run, running = _start_stage(
        api,
        factory,
        run_key="metrics-unrelated",
        stage_key="discovery",
    )
    _settle(
        artifacts,
        products,
        jobs,
        run,
        running,
        "discovery",
        (_rule("discovery_context", "entity:window", {"window": "source"}),),
    )
    assert (
        artifacts.get_stage_call_metrics(
            scope=_scope(),
            run_id=run.run_id,
        ).reused_model_call_count
        == 0
    )
