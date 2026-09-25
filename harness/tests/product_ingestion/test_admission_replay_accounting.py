"""Persisted v2 admission replay is readable without trusting forged receipts."""

from __future__ import annotations

# ruff: noqa: F811 -- imported pytest fixtures
from typing import Any

import pytest

from insurance_harness.product_ingestion.native_admission_wire import WIRE_PROMPT, WIRE_PROTOCOL
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_artifacts import _scope, _start_stage, api, factory  # noqa: F401
from tests.product_ingestion.test_discovery_replay_metrics import _child, _digest, _rule, _settle


@pytest.mark.parametrize(
    "tamper",
    [
        None,
        "contract",
        "wire_protocol",
        "prompt_sha256",
        "request_sha256",
        "model_policy_sha256",
        "request_content",
    ],
)
def test_v2_admission_replay_metrics(api: Any, factory: Any, tamper: str | None) -> None:
    context = {"wire_protocol": WIRE_PROTOCOL, "dependency_policy": "candidate-dependencies.830.v1"}
    content = json_bytes(context)
    request = json_bytes(
        {
            "messages": [
                {"role": "system", "content": WIRE_PROMPT.decode()},
                {
                    "role": "user",
                    "content": content.decode() if tamper != "request_content" else "{}",
                },
            ]
        }
    )
    operation = "native-admission-" + _digest(content)
    artifacts, products, jobs, parent, running = _start_stage(
        api, factory, run_key="v2-parent", stage_key="discovery"
    )
    artifacts.reserve_stage_call(
        scope=_scope(),
        run_id=parent.run_id,
        stage_key="discovery",
        operation_key=operation,
        dependency_sha256="a" * 64,
        job_id=running.id,
        generation=running.lease_generation,
        attempt=running.attempt,
        call_id="v2-call",
        input_sha256=_digest(content),
        model_policy_sha256="b" * 64,
        prompt_policy_sha256=_digest(WIRE_PROMPT),
    )
    artifacts.begin_stage_call(
        scope=_scope(),
        call_id="v2-call",
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=_digest(request),
        request_bytes=request,
    )
    raw = b'{"choices":[]}'
    artifacts.record_stage_call_result(
        scope=_scope(),
        call_id="v2-call",
        job_id=running.id,
        generation=running.lease_generation,
        request_sha256=_digest(request),
        raw=raw,
        diagnostic=None,
        usage={"input_tokens": 7, "output_tokens": 3},
    )
    _settle(artifacts, products, jobs, parent, running, "discovery")
    artifacts, products, jobs, child, running = _child(
        api, factory, stage_key="discovery", parent_run_id=parent.run_id, run_key="v2-child"
    )
    proof = {
        "contract": "native-admission-execution-receipt.830.v2",
        "wire_protocol": WIRE_PROTOCOL,
        "template_id": "admission-wire",
        "prompt_sha256": _digest(WIRE_PROMPT),
        "model_policy_sha256": "b" * 64,
        "operation_key": operation,
        "input_sha256": _digest(content),
        "model_call_id": "v2-call",
        "raw_sha256": _digest(raw),
        "request_sha256": _digest(request),
        "replayed_from_run_id": parent.run_id,
    }
    if tamper and tamper != "request_content":
        proof[tamper] = "invalid"
    _settle(
        artifacts,
        products,
        jobs,
        child,
        running,
        "discovery",
        (
            _rule("native_admission_context", "window", context),
            _rule("native_admission_execution", "window", proof),
        ),
    )
    if tamper:
        with pytest.raises(ValueError):
            artifacts.get_stage_call_metrics(scope=_scope(), run_id=child.run_id)
    else:
        metrics = artifacts.get_stage_call_metrics(scope=_scope(), run_id=child.run_id)
        assert metrics.reused_model_call_count == 1
        assert metrics.model_call_count == 0
        assert metrics.reused_usage == {"input_tokens": 7, "output_tokens": 3}
        assert artifacts.get_stage_call_metrics(scope=_scope(), run_id=child.run_id) == metrics
