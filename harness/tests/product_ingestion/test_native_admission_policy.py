"""Admission-only upgrades cannot invalidate or widen other model calls."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from insurance_harness.product_ingestion.configuration import ProductRuntimeSettings
from insurance_harness.product_ingestion.discovery import DEPENDENCY_DISCOVERY_REVIEW_PROMPT
from insurance_harness.product_ingestion.native_admission_contract import (
    NATIVE_ADMISSION_DEPENDENCY_PROMPT,
)
from insurance_harness.product_ingestion.native_admission_wire import WIRE_PROMPT, WIRE_PROTOCOL
from tests.product_ingestion.test_native_runtime import native_settings
from tests.product_ingestion.test_pipeline_runtime import _base_snapshot_with_navigation, _sha


def policy_payload(tmp_path: Path) -> dict:
    _, parent = _base_snapshot_with_navigation()
    shell = native_settings(tmp_path, parent)
    data = json.loads(shell.product_ingestion_runtime_json.get_secret_value())
    binding = data["bindings"][0]
    binding["native_discovery"]["dependency_policy"] = "candidate-dependencies.830.v1"
    template = next(
        t for t in binding["model"]["templates"] if t["purpose"] == "g3-native-admission"
    )
    template["prompt_sha256"] = _sha(NATIVE_ADMISSION_DEPENDENCY_PROMPT)
    binding["model"]["templates"].append(
        {
            **template,
            "template_id": "g3-dependency-discovery-review",
            "role": "verify",
            "purpose": "g3-dependency-discovery-review",
            "prompt_sha256": _sha(DEPENDENCY_DISCOVERY_REVIEW_PROMPT),
        }
    )
    return data


def add_override(data: dict) -> None:
    binding = data["bindings"][0]
    template = next(
        t for t in binding["model"]["templates"] if t["purpose"] == "g3-native-admission"
    )
    binding["native_admission"] = {
        "protocol": WIRE_PROTOCOL,
        "template": {
            **template,
            "template_id": "admission-v3",
            "purpose": "g3-native-admission-v3",
            "prompt_sha256": _sha(WIRE_PROMPT),
        },
    }


def test_admission_override_keeps_base_policy_and_only_replaces_admission(tmp_path: Path) -> None:
    data = policy_payload(tmp_path)
    old = ProductRuntimeSettings.model_validate_json(json.dumps(data)).bindings[0]
    add_override(data)
    current = ProductRuntimeSettings.model_validate_json(json.dumps(data)).bindings[0]
    assert current.model == old.model
    assert current.model.policy_sha256 == old.model.policy_sha256
    assert current.native_discovery == old.native_discovery
    from insurance_harness.product_ingestion.native_admission_policy import resolve_admission_policy

    resolved = resolve_admission_policy(
        current.model, current.native_discovery.dependency_policy, current.native_admission
    )
    assert resolved.settings.policy_sha256 != old.model.policy_sha256
    assert resolved.settings.api_key == old.model.api_key
    assert resolved.settings.endpoint == old.model.endpoint
    assert resolved.template.purpose == "g3-native-admission-v3"
    assert resolved.settings.model_dump(exclude={"templates"}) == old.model.model_dump(
        exclude={"templates"}
    )
    assert [t for t in resolved.settings.templates if t != resolved.template] == [
        t for t in old.model.templates if t.purpose != "g3-native-admission"
    ]


@pytest.mark.parametrize(
    "fault", ["prompt", "purpose", "role", "collision", "dependency", "endpoint"]
)
def test_admission_override_rejects_unauthorized_binding(tmp_path: Path, fault: str) -> None:
    data = policy_payload(tmp_path)
    add_override(data)
    binding = data["bindings"][0]
    override = binding["native_admission"]
    if fault == "prompt":
        override["template"]["prompt_sha256"] = "0" * 64
    elif fault == "purpose":
        override["template"]["purpose"] = "g3-native-admission"
    elif fault == "role":
        override["template"]["role"] = "verify"
    elif fault == "collision":
        override["template"]["template_id"] = binding["model"]["field_template_id"]
    elif fault == "dependency":
        binding["native_discovery"] = None
    else:
        override["endpoint"] = "https://unauthorized.invalid"
    with pytest.raises(ValueError):
        ProductRuntimeSettings.model_validate_json(json.dumps(data))


def test_old_admission_execution_cannot_satisfy_complete_checkpoint() -> None:
    from insurance_harness.product_ingestion.checkpoints import CURRENT_ARTIFACT_CONTRACTS

    assert CURRENT_ARTIFACT_CONTRACTS["native_admission_execution"] == (
        "product-native_admission_execution.v2",
        "2",
    )


@pytest.mark.parametrize(
    "fault",
    [
        "wire_protocol",
        "model_policy_sha256",
        "template_id",
        "prompt_sha256",
        "input_sha256",
        "operation_key",
        "request_sha256",
        "raw_sha256",
        "model_call_id",
        "contract",
        "call_raw",
        "call_request",
        "call_diagnostic",
        "call_state",
        "call_input",
        "context",
    ],
)
def test_complete_admission_execution_rejects_changed_custody(fault: str) -> None:
    from insurance_harness.product_ingestion.native_admission_policy import (
        AdmissionPolicy,
        validate_admission_execution,
    )
    from insurance_harness.product_ingestion.stages import json_bytes
    from tests.product_ingestion.test_discovery_replay_custody import _parent_call, _service

    prompt = b"fixture admission"
    service = _service(role="extract", purpose="g3-native-admission-v3", prompt=prompt)
    policy = AdmissionPolicy(
        service.configuration.model, service.configuration.model.templates[0], prompt, WIRE_PROTOCOL
    )
    content = json_bytes({"wire_protocol": WIRE_PROTOCOL})
    call = _parent_call(
        stage_key="discovery",
        operation="native-admission-" + _sha(content),
        content=content,
        prompt=prompt,
        raw=b"provider raw",
    )
    call.diagnostic = None
    receipt = {
        "contract": "native-admission-execution-receipt.830.v2",
        **policy.identity(),
        "input_sha256": call.input_sha256,
        "operation_key": call.operation_key,
        "request_sha256": call.request_sha256,
        "raw_sha256": call.raw_sha256,
        "model_call_id": call.call_id,
    }
    validate_admission_execution(policy, receipt, content, call)
    if fault == "call_raw":
        call.raw += b"changed"
    elif fault == "call_request":
        call.request_bytes += b"changed"
    elif fault == "call_diagnostic":
        call.diagnostic = "interrupted"
    elif fault == "call_state":
        call.state = "interrupted"
    elif fault == "call_input":
        call.input_sha256 = "0" * 64
    elif fault == "context":
        content = json_bytes({"wire_protocol": WIRE_PROTOCOL, "tampered": True})
    else:
        receipt[fault] = "changed"
    with pytest.raises(ValueError):
        validate_admission_execution(policy, receipt, content, call)
