"""Admission-specific policy selection using the existing model execution contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from insurance_harness.product_ingestion.artifact_models import StageCallSnapshot
from insurance_harness.product_ingestion.discovery_stage import require_discovery_template
from insurance_harness.product_ingestion.model_execution import matches_recorded_stage_request
from insurance_harness.product_ingestion.model_settings import (
    ModelTemplatePolicy,
    ProductModelSettings,
)
from insurance_harness.product_ingestion.native_admission import (
    NATIVE_DEPENDENCY_POLICY,
    native_admission_prompt,
)
from insurance_harness.product_ingestion.native_admission_wire import (
    WIRE_PROMPT,
    WIRE_PROTOCOL,
    WIRE_PURPOSE,
)


class NativeAdmissionSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    protocol: Literal["native-knowledge-admission.830.v3"]
    template: ModelTemplatePolicy


@dataclass(frozen=True, slots=True)
class AdmissionPolicy:
    settings: ProductModelSettings
    template: ModelTemplatePolicy
    prompt: bytes
    wire_protocol: str | None

    def identity(self) -> dict[str, str | None]:
        return {
            "wire_protocol": self.wire_protocol,
            "template_id": self.template.template_id,
            "prompt_sha256": self.template.prompt_sha256,
            "model_policy_sha256": self.settings.policy_sha256,
        }


def resolve_admission_policy(
    base: ProductModelSettings,
    dependency_policy: str | None,
    override: NativeAdmissionSettings | None,
) -> AdmissionPolicy:
    prompt = native_admission_prompt(dependency_policy)
    old = require_discovery_template(base, "extract", "g3-native-admission", prompt)
    if override is None:
        return AdmissionPolicy(base, old, prompt, None)
    if dependency_policy != NATIVE_DEPENDENCY_POLICY or override.protocol != WIRE_PROTOCOL:
        raise ValueError("admission override requires explicit dependency policy")
    template = override.template
    if template.template_id in {row.template_id for row in base.templates}:
        raise ValueError("admission override requires a distinct template identity")
    if template.run_schema_version != old.run_schema_version:
        raise ValueError("admission override cannot change run schema")
    derived = base.model_copy(
        update={
            "templates": tuple(template if row == old else row for row in base.templates),
        }
    )
    selected = require_discovery_template(derived, "extract", WIRE_PURPOSE, WIRE_PROMPT)
    return AdmissionPolicy(derived, selected, WIRE_PROMPT, WIRE_PROTOCOL)


def validate_admission_execution(
    policy: AdmissionPolicy,
    receipt: dict[str, Any],
    content: bytes,
    call: StageCallSnapshot,
) -> None:
    """Revalidate a completed stage against current policy and original call custody."""
    input_hash = hashlib.sha256(content).hexdigest()
    if (
        receipt.get("contract") != "native-admission-execution-receipt.830.v2"
        or any(receipt.get(k) != v for k, v in policy.identity().items())
        or receipt.get("input_sha256") != input_hash
        or receipt.get("operation_key") != "native-admission-" + input_hash
        or receipt.get("model_call_id") != call.call_id
        or receipt.get("request_sha256") != call.request_sha256
        or receipt.get("raw_sha256") != call.raw_sha256
        or call.input_sha256 != input_hash
        or call.operation_key != receipt["operation_key"]
        or call.stage_key != "discovery"
        or call.state != "recorded"
        or call.diagnostic
        or call.raw is None
        or hashlib.sha256(call.raw).hexdigest() != call.raw_sha256
        or json.loads(content).get("wire_protocol") != policy.wire_protocol
        or not matches_recorded_stage_request(
            call,
            settings=policy.settings,
            scope=policy.settings.scope,
            content=content,
            prompt=policy.prompt,
            template_id=policy.template.template_id,
        )
    ):
        raise ValueError("native admission checkpoint execution changed")
