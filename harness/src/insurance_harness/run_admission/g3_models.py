"""Strict serializable contracts for G3 bounded model execution."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_serializer,
    model_validator,
)

from insurance_harness.model_policy import ModelIdentity

from .models import ResourceCaps

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonBlankStr = Annotated[StrictStr, StringConstraints(min_length=1, max_length=1024)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
Stage = Literal["C_CLASSIFY", "D_COMPILE", "D_REVIEW"]


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_g3_hash(domain: str, dto: BaseModel, self_field: str) -> str:
    if type(domain) is not str or not domain or "\0" in domain:
        raise ValueError("invalid hash domain")
    if self_field not in type(dto).model_fields:
        raise ValueError("unknown self-hash field")
    payload = dto.model_dump(mode="json", round_trip=True, exclude={self_field})
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + canonical_json(payload)).hexdigest()


def _validate_self_hash(dto: BaseModel, domain: str, field: str) -> None:
    value = getattr(dto, field)
    if value != "0" * 64 and value != canonical_g3_hash(domain, dto, field):
        raise ValueError(f"{field} mismatch")


class _G3Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    def copy(self, **_kwargs: object) -> Self:
        raise TypeError("copy() is disabled; use validated model_copy()")

    def model_copy(self, *, update: Mapping[str, Any] | None = None, deep: bool = False) -> Self:
        del deep
        values = self.model_dump(mode="python", round_trip=True, warnings=False)
        if update:
            values.update(dict(update))
        return type(self).model_validate(values)

    @field_serializer("*", when_used="json")
    def _serialize_datetime(self, value: object) -> object:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return value


def _sorted_unique(values: tuple[str, ...], name: str, *, nonempty: bool = True) -> tuple[str, ...]:
    if (nonempty and not values) or len(set(values)) != len(values):
        raise ValueError(f"{name} must be unique")
    if values != tuple(sorted(values)):
        raise ValueError(f"{name} must be canonically sorted")
    return values


class G3ArtifactRefV1(_G3Model):
    contract: NonBlankStr
    artifact_ref: NonBlankStr
    sha256: Sha256Hex
    bytes: NonNegativeInt


class G3AuthorizedMaterialV1(_G3Model):
    material_id: NonBlankStr
    corpus_entry_sha256: Sha256Hex
    source_revision_receipt_sha256: Sha256Hex
    w1_sha256: Sha256Hex
    native_page_map_sha256: Sha256Hex


class G3DelegatedStageSignerV1(_G3Model):
    key_id: NonBlankStr
    algorithm: Literal["Ed25519"]
    public_key_b64: NonBlankStr
    public_key_fingerprint: Sha256Hex

    @model_validator(mode="after")
    def validate_key(self) -> Self:
        try:
            raw = base64.b64decode(self.public_key_b64, validate=True)
        except Exception:
            raise ValueError("invalid delegated public key") from None
        if len(raw) != 32 or base64.b64encode(raw).decode() != self.public_key_b64:
            raise ValueError("invalid delegated public key")
        if hashlib.sha256(raw).hexdigest() != self.public_key_fingerprint:
            raise ValueError("delegated public key fingerprint mismatch")
        return self


class G3EligibilityCheckV1(_G3Model):
    check_id: NonBlankStr
    check_kind: NonBlankStr
    subject_id: NonBlankStr
    input_sha256s: tuple[Sha256Hex, ...]
    observed_count: NonNegativeInt | None
    required_min: NonNegativeInt | None
    required_max: NonNegativeInt | None
    status: Literal["PASS"]
    reason_code: NonBlankStr

    @model_validator(mode="after")
    def validate_inputs(self) -> Self:
        _sorted_unique(self.input_sha256s, "input_sha256s")
        if (
            self.required_min is not None
            and self.required_max is not None
            and self.required_min > self.required_max
        ):
            raise ValueError("invalid eligibility range")
        return self


class G3FailurePolicyV1(_G3Model):
    policy_version: Literal[
        "g3-chain-failure-policy.830.v1",
        "g3-chain-failure-policy.830.v2",
    ]
    retry_limit: Literal[0]
    worker_limit: Literal[1, 2]
    incomplete_reservation_action: Literal[
        "PERMANENTLY_CONSUME_AND_STOP_STAGE",
        "RESUME_UNSTARTED_CONTINUE_STAGE",
    ]
    started_without_terminal_action: Literal[
        "PERMANENT_OUTCOME_UNKNOWN_STOP_CHAIN",
        "PRESERVE_OUTCOME_UNKNOWN_CONTINUE_STAGE",
    ]
    call_failure_action: Literal["STOP_CHAIN", "CONTINUE_INDEPENDENT_CALLS"]
    c_execution_failure_action: Literal["STOP_BEFORE_RESOLVE"]
    c_coverage_gap_action: Literal["MARK_DOD_GAP_CONTINUE_ELIGIBLE_AUTOMATIC_CHILDREN"]
    d_compile_failure_action: Literal["STOP_BEFORE_REVIEW"]
    d_review_failure_action: Literal["STOP_BEFORE_CANDIDATE"]

    @model_validator(mode="after")
    def validate_versioned_policy(self) -> Self:
        actual = (
            self.worker_limit,
            self.incomplete_reservation_action,
            self.started_without_terminal_action,
            self.call_failure_action,
        )
        expected = {
            "g3-chain-failure-policy.830.v1": (
                1,
                "PERMANENTLY_CONSUME_AND_STOP_STAGE",
                "PERMANENT_OUTCOME_UNKNOWN_STOP_CHAIN",
                "STOP_CHAIN",
            ),
            "g3-chain-failure-policy.830.v2": (
                2,
                "RESUME_UNSTARTED_CONTINUE_STAGE",
                "PRESERVE_OUTCOME_UNKNOWN_CONTINUE_STAGE",
                "CONTINUE_INDEPENDENT_CALLS",
            ),
        }[self.policy_version]
        if actual != expected:
            raise ValueError("failure policy version/semantics mismatch")
        return self


class G3LedgerPolicyV1(_G3Model):
    protocol_version: Literal["g3-cross-process-ledger.830.v1"]
    root_path: Literal["/var/lib/insurancekb/g3-bounded-execution-ledger/v1"]
    owner_rule: Literal["LEAF_OWNER_EQUALS_EFFECTIVE_SERVICE_UID"]
    root_mode: Literal["0700"]
    stage_binding_mode: Literal["ONE_ADMISSION_DIGEST_PER_CHAIN_STAGE_O_EXCL"]
    call_reservation_mode: Literal["ATOMIC_MKDIR_AND_O_EXCL_RECORD"]
    duplicate_action: Literal["DENY_HTTP_ZERO"]
    malformed_ledger_action: Literal["PERMANENTLY_CONSUME_AND_DENY_HTTP_ZERO"]


class G3ChainStageV1(_G3Model):
    stage: Stage
    purpose: NonBlankStr
    run_schema_version: NonBlankStr
    role: Literal["classify", "extract", "verify"]
    max_calls: PositiveInt
    input_token_ceiling: PositiveInt
    output_token_ceiling: PositiveInt
    time_limit_seconds: PositiveInt


class G3ChainManifestV1(_G3Model):
    contract: Literal["g3-bounded-chain.830.v1"]
    chain_id: NonBlankStr
    clean_integration_sha: Annotated[
        StrictStr, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    ]
    stages: tuple[G3ChainStageV1, ...]
    max_calls: PositiveInt
    total_input_token_ceiling: PositiveInt
    total_output_token_ceiling: PositiveInt
    total_time_limit_seconds: PositiveInt
    retry_limit: Literal[0]
    worker_limit: Literal[1, 2]
    derivation_rules_version: Literal["g3-c-to-d-derivation.830.v1"]
    prompt_render_rules_version: NonBlankStr
    schema_derivation_version: NonBlankStr
    failure_policy: G3FailurePolicyV1
    ledger_policy: G3LedgerPolicyV1
    chain_manifest_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_chain(self) -> Self:
        if tuple(stage.stage for stage in self.stages) != ("C_CLASSIFY", "D_COMPILE", "D_REVIEW"):
            raise ValueError("chain stages must be exact and ordered")
        if self.max_calls != sum(stage.max_calls for stage in self.stages):
            raise ValueError("chain call budget mismatch")
        if self.total_input_token_ceiling != sum(s.input_token_ceiling for s in self.stages):
            raise ValueError("chain input budget mismatch")
        if self.total_output_token_ceiling != sum(s.output_token_ceiling for s in self.stages):
            raise ValueError("chain output budget mismatch")
        if self.total_time_limit_seconds != sum(s.time_limit_seconds for s in self.stages):
            raise ValueError("chain time budget mismatch")
        _validate_self_hash(self, "g3-bounded-chain.830.v1", "chain_manifest_hash")
        return self


class G3ModelProcessingAuthorizationV1(_G3Model):
    contract: Literal["g3-model-processing-authorization.830.v1"]
    authorization_id: NonBlankStr
    chain_manifest: G3ChainManifestV1
    chain_manifest_hash: Sha256Hex
    space_id: NonBlankStr
    provider: NonBlankStr
    endpoint_origin: NonBlankStr
    deployment_id: NonBlankStr
    family: NonBlankStr
    policy_version: NonBlankStr
    c_materials: tuple[G3AuthorizedMaterialV1, ...]
    c_request_manifest_hash: Sha256Hex
    c_prompt_preview_sha256: Sha256Hex
    allowed_stages: tuple[Stage, ...]
    allowed_roles: tuple[Literal["classify", "extract", "verify"], ...]
    allowed_derived_data_categories: tuple[NonBlankStr, ...]
    derivation_rules_version: Literal["g3-c-to-d-derivation.830.v1"]
    max_calls: PositiveInt
    total_input_token_ceiling: PositiveInt
    total_output_token_ceiling: PositiveInt
    total_time_limit_seconds: PositiveInt
    retry_limit: Literal[0]
    worker_limit: Literal[1, 2]
    delegated_stage_signer: G3DelegatedStageSignerV1
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.chain_manifest_hash != self.chain_manifest.chain_manifest_hash:
            raise ValueError("chain manifest binding mismatch")
        if self.allowed_stages != ("C_CLASSIFY", "D_COMPILE", "D_REVIEW"):
            raise ValueError("invalid allowed stages")
        if self.allowed_roles != ("classify", "extract", "verify"):
            raise ValueError("invalid allowed roles")
        if tuple(m.material_id for m in self.c_materials) != tuple(
            sorted(m.material_id for m in self.c_materials)
        ) or len({m.material_id for m in self.c_materials}) != len(self.c_materials):
            raise ValueError("materials must be sorted and unique")
        expected_categories = tuple(
            sorted(
                (
                    "C_W1_SOURCE",
                    "C_CATALOG_POLICY_SNAPSHOT",
                    "C_EXISTING_ENTITY_SNAPSHOT",
                    "D_AUTOMATIC_CHILD_SOURCE_CLOSURE",
                    "D_CATALOG_PROFILE_BASE",
                    "D_COMPOSED_CANDIDATE_REVIEW_CONTEXT",
                )
            )
        )
        if self.allowed_derived_data_categories != expected_categories:
            raise ValueError("invalid derived data categories")
        manifest = self.chain_manifest
        if (
            self.max_calls,
            self.total_input_token_ceiling,
            self.total_output_token_ceiling,
            self.total_time_limit_seconds,
            self.retry_limit,
            self.worker_limit,
        ) != (
            manifest.max_calls,
            manifest.total_input_token_ceiling,
            manifest.total_output_token_ceiling,
            manifest.total_time_limit_seconds,
            manifest.retry_limit,
            manifest.worker_limit,
        ):
            raise ValueError("parent budget mismatch")
        return self


class G3ModelProcessingAuthorizationEnvelopeV1(_G3Model):
    schema_version: Literal["insurancekb.g3-model-processing-authorization-envelope.v1"]
    signature_domain: Literal["insurancekb.run-admission.g3-model-processing-authorization.v1"]
    key_id: NonBlankStr
    public_key_fingerprint: Sha256Hex
    human_identity: NonBlankStr
    approver_role: Literal["g3-model-processing-authorization-approver"]
    payload: G3ModelProcessingAuthorizationV1
    signature_b64: Annotated[StrictStr, StringConstraints(min_length=88, max_length=88)]


class G3CallPlanV1(_G3Model):
    call_id: NonBlankStr
    ordinal: NonNegativeInt
    stage: Stage
    window_id: NonBlankStr | None
    material_ids: tuple[NonBlankStr, ...]
    input_context_sha256: Sha256Hex
    endpoint_origin: NonBlankStr
    endpoint_path: Literal[
        "/compatible-mode/v1/chat/completions", "/v1/chat/completions"
    ]
    identity: ModelIdentity
    response_mode: NonBlankStr
    request_body_sha256: Sha256Hex
    request_bytes: PositiveInt
    input_token_estimate: NonNegativeInt
    input_token_ceiling: PositiveInt
    output_token_ceiling: PositiveInt
    timeout_seconds: PositiveInt

    @model_validator(mode="after")
    def validate_stage_shape(self) -> Self:
        _sorted_unique(self.material_ids, "material_ids", nonempty=self.stage == "C_CLASSIFY")
        if self.stage == "C_CLASSIFY":
            if self.window_id is None or not self.material_ids:
                raise ValueError("C call requires window and materials")
        else:
            expected_role = {
                "D_COMPILE": "extract",
                "D_REVIEW": "verify",
            }[self.stage]
            exact_windowed_identity = (
                self.identity.provider,
                self.identity.family,
                self.identity.deployment_id,
                self.identity.policy_version,
                self.identity.role,
            ) == (
                "g3-user-gateway",
                "gemini",
                "gemini-3.7-flash-medium",
                "g3-user-gemini-gateway-v1",
                expected_role,
            )
            old_single_call_shape = self.window_id is None and not self.material_ids
            windowed_shape = (
                exact_windowed_identity
                and self.window_id is not None
                and re.fullmatch(r"window_[0-9a-f]{64}", self.window_id) is not None
                and bool(self.material_ids)
            )
            if not old_single_call_shape and not windowed_shape:
                raise ValueError("D call requires exact legacy or Gemini window shape")
        if self.input_token_estimate > self.input_token_ceiling:
            raise ValueError("input estimate exceeds ceiling")
        return self


class G3RequestManifestV1(_G3Model):
    contract: Literal["g3-request-manifest.830.v1"]
    stage: Stage
    chain_id: NonBlankStr
    calls: tuple[G3CallPlanV1, ...]
    manifest_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_calls(self) -> Self:
        if not self.calls or tuple(c.ordinal for c in self.calls) != tuple(range(len(self.calls))):
            raise ValueError("calls must have contiguous canonical ordinals")
        if any(c.stage != self.stage for c in self.calls):
            raise ValueError("call stage mismatch")
        if len({c.call_id for c in self.calls}) != len(self.calls):
            raise ValueError("duplicate call id")
        _validate_self_hash(self, "g3-request-manifest.830.v1", "manifest_hash")
        return self


class G3StageEligibilityLockV1(_G3Model):
    contract: NonBlankStr
    stage: Stage
    input_artifacts: tuple[G3ArtifactRefV1, ...]
    checks: tuple[G3EligibilityCheckV1, ...]
    eligible_subject_ids: tuple[NonBlankStr, ...]
    eligibility_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_collections(self) -> Self:
        artifact_keys = tuple((a.contract, a.artifact_ref) for a in self.input_artifacts)
        check_ids = tuple(c.check_id for c in self.checks)
        if (
            artifact_keys != tuple(sorted(set(artifact_keys)))
            or check_ids != tuple(sorted(set(check_ids)))
            or self.eligible_subject_ids != tuple(sorted(set(self.eligible_subject_ids)))
        ):
            raise ValueError("eligibility collections are not canonical")
        _validate_self_hash(self, "g3-stage-eligibility.830.v1", "eligibility_hash")
        return self


class G3ProtocolSeedLockV1(_G3Model):
    contract: NonBlankStr
    seed_artifact: G3ArtifactRefV1
    denominator_material_ids: tuple[NonBlankStr, ...]
    expected_coverage_codes: tuple[NonBlankStr, ...]
    quality_authority: Literal[False]
    golden_slice_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_seed(self) -> Self:
        if self.denominator_material_ids != tuple(
            sorted(set(self.denominator_material_ids))
        ) or self.expected_coverage_codes != tuple(sorted(set(self.expected_coverage_codes))):
            raise ValueError("Seed collections are not canonical")
        _validate_self_hash(self, "g3-protocol-seed.830.v1", "golden_slice_hash")
        return self


class G3RoutingLockV1(_G3Model):
    contract: NonBlankStr
    stage: Stage
    purpose: NonBlankStr
    run_schema_version: NonBlankStr
    role: Literal["classify", "extract", "verify"]
    identity: ModelIdentity
    endpoint_origin: NonBlankStr
    endpoint_path: Literal[
        "/compatible-mode/v1/chat/completions", "/v1/chat/completions"
    ]
    temperature_micros: NonNegativeInt
    thinking: StrictBool
    response_format: NonBlankStr
    timeout_seconds: PositiveInt
    follow_redirects: Literal[False]
    fallback_limit: Literal[0]
    retry_limit: Literal[0]
    template_hash: Sha256Hex
    schema_hash: Sha256Hex
    routing_policy_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        _validate_self_hash(self, "g3-stage-routing.830.v1", "routing_policy_hash")
        return self


class G3SchemaArtifactV1(_G3Model):
    stage: Stage
    direction: Literal["request", "response"]
    enforcing_module: NonBlankStr
    enforcing_module_sha256: Sha256Hex
    canonical_schema_sha256: Sha256Hex


class G3SchemaLockV1(_G3Model):
    contract: NonBlankStr
    artifacts: tuple[G3SchemaArtifactV1, ...]
    schema_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_schema(self) -> Self:
        keys = tuple((a.stage, a.direction, a.enforcing_module) for a in self.artifacts)
        if not keys or keys != tuple(sorted(set(keys))):
            raise ValueError("schema artifacts are not canonical")
        _validate_self_hash(self, "g3-stage-schema-set.830.v1", "schema_hash")
        return self


class G3TemplateLockV1(_G3Model):
    contract: NonBlankStr
    stage: Stage
    path: NonBlankStr
    raw_sha256: Sha256Hex
    prompt_version: NonBlankStr
    render_rules_version: NonBlankStr
    approved_template_hash: Sha256Hex
    template_lock_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        _validate_self_hash(self, "g3-stage-template-lock.830.v1", "template_lock_hash")
        return self


class G3StageDispatchLockV1(_G3Model):
    contract: NonBlankStr
    stage: Stage
    calls: tuple[G3CallPlanV1, ...]
    opaque_block_map_sha256: Sha256Hex | None
    input_context_sha256: Sha256Hex
    schema_hash: Sha256Hex
    template_hash: Sha256Hex
    structured_dispatch_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_dispatch(self) -> Self:
        if tuple(call.ordinal for call in self.calls) != tuple(range(len(self.calls))):
            raise ValueError("dispatch calls are not canonical")
        _validate_self_hash(self, "g3-stage-dispatch.830.v1", "structured_dispatch_hash")
        return self


class G3StageCapsV1(_G3Model):
    contract: NonBlankStr
    stage: Stage
    worker_limit: Literal[1, 2]
    call_limit: PositiveInt
    attempts_per_call: Literal[1]
    retry_limit: Literal[0]
    input_token_ceiling: PositiveInt
    output_token_ceiling: PositiveInt
    time_limit_seconds: PositiveInt
    caps_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        _validate_self_hash(self, "g3-stage-caps.830.v1", "caps_sha256")
        return self


class G3StageRightsLockV1(_G3Model):
    contract: NonBlankStr
    parent_authorization_digest: Sha256Hex
    stage: Stage
    purpose: NonBlankStr
    run_schema_version: NonBlankStr
    role: Literal["classify", "extract", "verify"]
    provider: NonBlankStr
    endpoint_origin: NonBlankStr
    endpoint_path: Literal[
        "/compatible-mode/v1/chat/completions", "/v1/chat/completions"
    ]
    deployment_id: NonBlankStr
    call_ids: tuple[NonBlankStr, ...]
    window_ids: tuple[NonBlankStr, ...]
    artifacts: tuple[G3ArtifactRefV1, ...]
    material_or_derivation_ids: tuple[NonBlankStr, ...]
    data_categories: tuple[NonBlankStr, ...]
    call_limit: PositiveInt
    input_token_ceiling: PositiveInt
    output_token_ceiling: PositiveInt
    time_limit_seconds: PositiveInt
    expires_at: AwareDatetime
    retry_limit: Literal[0]
    rights_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_rights(self) -> Self:
        collections = (
            self.call_ids,
            self.window_ids,
            self.material_or_derivation_ids,
            self.data_categories,
        )
        artifact_keys = tuple((a.contract, a.artifact_ref) for a in self.artifacts)
        if any(values != tuple(sorted(set(values))) for values in collections) or (
            artifact_keys != tuple(sorted(set(artifact_keys)))
        ):
            raise ValueError("rights collections are not canonical")
        _validate_self_hash(self, "g3-external-send-rights.830.v1", "rights_hash")
        return self


class G3StageProvenanceLockV1(_G3Model):
    contract: NonBlankStr
    stage: Stage
    artifacts: tuple[G3ArtifactRefV1, ...]
    prior_terminal_receipt_sha256: Sha256Hex | None
    provenance_hash: Sha256Hex

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        keys = tuple((a.contract, a.artifact_ref) for a in self.artifacts)
        if keys != tuple(sorted(set(keys))):
            raise ValueError("provenance artifacts are not canonical")
        _validate_self_hash(self, "g3-stage-provenance.830.v1", "provenance_hash")
        return self


class G3DerivedStageReceiptV1(_G3Model):
    contract: NonBlankStr
    parent_authorization_digest: Sha256Hex
    stage: Literal["D_COMPILE", "D_REVIEW"]
    prior_terminal_receipt_sha256: Sha256Hex
    derivation_rules_version: Literal["g3-c-to-d-derivation.830.v1"]
    input_artifact_sha256s: tuple[Sha256Hex, ...]
    derived_request_manifest_hash: Sha256Hex
    receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.input_artifact_sha256s != tuple(sorted(set(self.input_artifact_sha256s))):
            raise ValueError("derived inputs are not canonical")
        _validate_self_hash(self, "g3-derived-stage-receipt.830.v1", "receipt_sha256")
        return self


class G3BoundedAdmissionPlanV1(_G3Model):
    contract: Literal["g3-bounded-admission-plan.830.v1"]
    stage: Stage
    purpose: NonBlankStr
    run_schema_version: NonBlankStr
    run_id: NonBlankStr
    run_revision: NonBlankStr
    space_id: NonBlankStr
    chain_id: NonBlankStr
    chain_manifest: G3ChainManifestV1
    chain_manifest_hash: Sha256Hex
    parent_authorization_digest: Sha256Hex
    prior_terminal_receipt_sha256: Sha256Hex | None
    derived_stage_receipt: G3DerivedStageReceiptV1 | None
    request_manifest: G3RequestManifestV1
    manifest_hash: Sha256Hex
    eligibility_lock: G3StageEligibilityLockV1
    eligibility_hash: Sha256Hex
    protocol_seed_lock: G3ProtocolSeedLockV1
    golden_slice_hash: Sha256Hex
    routing_lock: G3RoutingLockV1
    routing_policy_hash: Sha256Hex
    schema_lock: G3SchemaLockV1
    schema_hash: Sha256Hex
    template_lock: G3TemplateLockV1
    template_lock_hash: Sha256Hex
    approved_template_hashes: tuple[Sha256Hex, ...]
    dispatch_lock: G3StageDispatchLockV1
    structured_dispatch_hash: Sha256Hex
    approved_identities: tuple[ModelIdentity, ...]
    model_plan_hash: Sha256Hex
    deployment_roles_hash: Sha256Hex
    stage_caps: G3StageCapsV1
    resource_caps: ResourceCaps
    resource_caps_hash: Sha256Hex
    rights_lock: G3StageRightsLockV1
    rights_hash: Sha256Hex
    provenance_lock: G3StageProvenanceLockV1
    provenance_hash: Sha256Hex
    clean_integration_sha: Annotated[
        StrictStr, StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    ]
    expires_at: AwareDatetime


class G3BoundedApprovalEnvelopeV1(_G3Model):
    schema_version: Literal["insurancekb.g3-bounded-run-admission-approval-envelope.v1"]
    signature_domain: Literal["insurancekb.run-admission.g3-bounded-model-execution.v1"]
    parent_authorization_ref: G3ArtifactRefV1
    parent_authorization_digest: Sha256Hex
    stage_signer_key_id: NonBlankStr
    stage_signer_public_key_fingerprint: Sha256Hex
    payload: G3BoundedAdmissionPlanV1
    signature_b64: Annotated[StrictStr, StringConstraints(min_length=88, max_length=88)]


class G3ProviderUsageV1(_G3Model):
    prompt_tokens: NonNegativeInt
    completion_tokens: NonNegativeInt
    total_tokens: NonNegativeInt
    usage_verified: Literal[True]

    @model_validator(mode="after")
    def validate_total(self) -> Self:
        if self.total_tokens != self.prompt_tokens + self.completion_tokens:
            raise ValueError("provider usage total mismatch")
        return self


class G3ProviderResponseMetaV1(_G3Model):
    http_status: NonNegativeInt
    content_type: NonBlankStr
    provider_request_id: NonBlankStr | None
    canonical_headers_sha256: Sha256Hex


class G3ReservedChainBudgetV1(_G3Model):
    calls_reserved: PositiveInt
    input_tokens_reserved: PositiveInt
    output_tokens_reserved: PositiveInt
    time_seconds_reserved: PositiveInt
    calls_remaining_after_reservation: NonNegativeInt
    input_tokens_remaining_after_reservation: NonNegativeInt
    output_tokens_remaining_after_reservation: NonNegativeInt
    time_seconds_remaining_after_reservation: NonNegativeInt


class G3UsageTotalsV1(_G3Model):
    successful_usage_records: NonNegativeInt
    prompt_tokens: NonNegativeInt
    completion_tokens: NonNegativeInt
    total_tokens: NonNegativeInt


class G3DispositionCountsV1(_G3Model):
    MATCH: NonNegativeInt
    CREATE: NonNegativeInt
    MULTI: NonNegativeInt
    NEEDS_CONFIRM: NonNegativeInt
    QUARANTINE: NonNegativeInt


def g3_coverage_gap_codes(counts: G3DispositionCountsV1) -> tuple[str, ...]:
    validated = G3DispositionCountsV1.model_validate(counts.model_dump())
    return tuple(
        f"G3_DOD_COVERAGE_GAP:{name}"
        for name in ("MATCH", "CREATE", "MULTI", "NEEDS_CONFIRM", "QUARANTINE")
        if getattr(validated, name) == 0
    )


class G3CostAuditV1(_G3Model):
    status: Literal["MEASURED", "NOT_MEASURED"]
    currency: Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z]{3}$")] | None
    amount_minor_units: NonNegativeInt | None
    rate_card_sha256: Sha256Hex | None
    provider_cost_receipt_sha256: Sha256Hex | None
    reason_code: (
        Literal["NO_FROZEN_RATE_CARD", "NO_PROVIDER_COST_RECEIPT", "PROVIDER_COST_NOT_RECONCILABLE"]
        | None
    )

    @model_validator(mode="after")
    def validate_cost(self) -> Self:
        if self.status == "MEASURED":
            if (
                any(
                    v is None
                    for v in (
                        self.currency,
                        self.amount_minor_units,
                        self.rate_card_sha256,
                        self.provider_cost_receipt_sha256,
                    )
                )
                or self.reason_code is not None
            ):
                raise ValueError("measured cost is incomplete")
        elif (
            self.currency is not None
            or self.amount_minor_units is not None
            or self.reason_code is None
        ):
            raise ValueError("unmeasured cost is invalid")
        return self


class G3StageLedgerBindingV1(_G3Model):
    contract: NonBlankStr
    chain_manifest_hash: Sha256Hex
    parent_authorization_digest: Sha256Hex
    stage: Stage
    admission_artifact_digest: Sha256Hex
    bound_at: AwareDatetime
    receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        _validate_self_hash(self, "g3-stage-ledger-binding.830.v1", "receipt_sha256")
        return self


class G3CallReservationV1(_G3Model):
    contract: NonBlankStr
    chain_manifest_hash: Sha256Hex
    parent_authorization_digest: Sha256Hex
    stage: Stage
    admission_artifact_digest: Sha256Hex
    call_id: NonBlankStr
    call_id_sha256: Sha256Hex
    ordinal: NonNegativeInt
    reservation_key_sha256: Sha256Hex
    call_limit_reserved: Literal[1]
    input_tokens_reserved: PositiveInt
    output_tokens_reserved: PositiveInt
    time_seconds_reserved: PositiveInt
    stage_binding_receipt_sha256: Sha256Hex
    reserved_at: AwareDatetime
    receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        if self.call_id_sha256 != hashlib.sha256(self.call_id.encode()).hexdigest():
            raise ValueError("call id hash mismatch")
        reservation_key = {
            "chain_manifest_hash": self.chain_manifest_hash,
            "stage": self.stage,
            "admission_artifact_digest": self.admission_artifact_digest,
            "call_id": self.call_id,
            "ordinal": self.ordinal,
        }
        expected_key = hashlib.sha256(
            b"g3-call-reservation-key.830.v1\0" + canonical_json(reservation_key)
        ).hexdigest()
        if self.reservation_key_sha256 != expected_key:
            raise ValueError("reservation key mismatch")
        _validate_self_hash(self, "g3-call-reservation.830.v1", "receipt_sha256")
        return self


class G3PreparedReceiptV1(_G3Model):
    contract: NonBlankStr
    chain_id: NonBlankStr
    stage: Stage
    call_id: NonBlankStr
    ordinal: NonNegativeInt
    admission_artifact_digest: Sha256Hex
    verified_binding_digest: Sha256Hex
    call_reservation_receipt_sha256: Sha256Hex
    request_body_sha256: Sha256Hex
    request_bytes: PositiveInt
    input_token_estimate: NonNegativeInt
    input_token_ceiling: PositiveInt
    output_token_ceiling: PositiveInt
    timeout_seconds: PositiveInt
    reserved_chain_budget: G3ReservedChainBudgetV1
    prepared_at: AwareDatetime
    receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        _validate_self_hash(self, "g3-prepared-receipt.830.v1", "receipt_sha256")
        return self


class G3StartedReceiptV1(_G3Model):
    contract: NonBlankStr
    prepared_receipt_sha256: Sha256Hex
    started_at: AwareDatetime
    monotonic_start_ns: NonNegativeInt
    call_consumed: Literal[True]
    receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_receipt(self) -> Self:
        _validate_self_hash(self, "g3-started-receipt.830.v1", "receipt_sha256")
        return self


class G3CallTerminalReceiptV1(_G3Model):
    contract: NonBlankStr
    chain_id: NonBlankStr
    stage: Stage
    call_id: NonBlankStr
    ordinal: NonNegativeInt
    run_id: NonBlankStr
    run_revision: NonBlankStr
    admission_artifact_digest: Sha256Hex
    verified_binding_digest: Sha256Hex
    call_reservation_receipt_sha256: Sha256Hex
    policy_receipt_sha256: Sha256Hex
    identity: ModelIdentity
    endpoint_origin: NonBlankStr
    endpoint_path: Literal[
        "/compatible-mode/v1/chat/completions", "/v1/chat/completions"
    ]
    request_body_sha256: Sha256Hex
    request_bytes: PositiveInt
    response_meta: G3ProviderResponseMetaV1 | None
    response_body_sha256: Sha256Hex | None
    response_bytes: NonNegativeInt | None
    semantic_content_sha256: Sha256Hex | None
    projection_sha256: Sha256Hex | None
    provider_usage: G3ProviderUsageV1 | None
    cost_audit: G3CostAuditV1
    started_receipt_sha256: Sha256Hex
    started_at: AwareDatetime
    ended_at: AwareDatetime
    duration_ms: NonNegativeInt
    status: Literal["SUCCESS", "FAILED", "OUTCOME_UNKNOWN"]
    reason_code: NonBlankStr
    retry_count: Literal[0]
    receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_terminal(self) -> Self:
        response_fields = (self.response_meta, self.response_body_sha256, self.response_bytes)
        if any(v is not None for v in response_fields) and any(v is None for v in response_fields):
            raise ValueError("complete response metadata must be all present")
        if self.status == "SUCCESS" and any(
            v is None
            for v in (
                *response_fields,
                self.semantic_content_sha256,
                self.projection_sha256,
                self.provider_usage,
            )
        ):
            raise ValueError("successful terminal receipt is incomplete")
        _validate_self_hash(self, "g3-call-terminal-receipt.830.v1", "receipt_sha256")
        return self


class G3StageTerminalReceiptV1(_G3Model):
    contract: NonBlankStr
    chain_id: NonBlankStr
    stage: Stage
    parent_authorization_digest: Sha256Hex
    admission_artifact_digest: Sha256Hex
    prior_terminal_receipt_sha256: Sha256Hex | None
    stage_binding_receipt_sha256: Sha256Hex
    call_terminal_sha256s: tuple[Sha256Hex, ...]
    stage_output_sha256: Sha256Hex | None
    disposition_counts: G3DispositionCountsV1 | None
    coverage_gap_codes: tuple[NonBlankStr, ...]
    calls_consumed: NonNegativeInt
    provider_usage_total: G3UsageTotalsV1
    cost_audit: G3CostAuditV1
    started_at: AwareDatetime
    ended_at: AwareDatetime
    status: Literal["SUCCESS", "FAILED", "OUTCOME_UNKNOWN"]
    receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_terminal(self) -> Self:
        if self.calls_consumed < len(self.call_terminal_sha256s):
            raise ValueError("stage consumed-call count mismatch")
        if self.provider_usage_total.total_tokens != (
            self.provider_usage_total.prompt_tokens + self.provider_usage_total.completion_tokens
        ):
            raise ValueError("stage usage total mismatch")
        if self.stage == "C_CLASSIFY":
            if self.status == "SUCCESS" and self.disposition_counts is None:
                raise ValueError("successful C terminal needs disposition counts")
        elif self.disposition_counts is not None or self.coverage_gap_codes:
            raise ValueError("D terminals cannot carry C disposition data")
        _validate_self_hash(self, "g3-stage-terminal-receipt.830.v1", "receipt_sha256")
        return self


def parent_authorization_signed_bytes(
    envelope: G3ModelProcessingAuthorizationEnvelopeV1,
) -> bytes:
    payload = envelope.model_dump(mode="json", round_trip=True, exclude={"signature_b64"})
    return envelope.signature_domain.encode() + b"\0" + canonical_json(payload)


def stage_approval_signed_bytes(envelope: G3BoundedApprovalEnvelopeV1) -> bytes:
    payload = envelope.model_dump(mode="json", round_trip=True, exclude={"signature_b64"})
    return envelope.signature_domain.encode() + b"\0" + canonical_json(payload)


__all__ = [name for name in tuple(globals()) if name.startswith("G3")] + [
    "canonical_g3_hash",
    "canonical_json",
    "g3_coverage_gap_codes",
    "parent_authorization_signed_bytes",
    "stage_approval_signed_bytes",
]
