"""Single fail-closed evaluator for production model identities and call authority."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import SupportsIndex, cast
from weakref import WeakKeyDictionary

from pydantic import AwareDatetime, TypeAdapter

from .admission import (
    AdmissionBinding,
    AdmissionVerificationReceipt,
    IssuedModelPermit,
    StrictAdmissionRequestBinding,
    VerifiedAdmission,
    _issue_model_permit,
    _permit_authority_snapshot,
    _verified_authority_snapshot,
)
from .models import (
    IdentityKey,
    ModelCallContext,
    ModelIdentity,
    ModelPermitView,
    PolicyReasonCode,
    PolicyReceipt,
    _model_permit_view_digest,
    _normalize_identity_keys,
)

_APPROVED_FAMILIES = frozenset({"minimax", "qwen", "qwen-vl"})
_TRUSTED_PROVIDER_FAMILY_KEYS = frozenset(
    ("bailian", family) for family in _APPROVED_FAMILIES
)
_TRUSTED_DEPLOYMENT_NAMESPACES = (
    ("bailian", "qwenvl", "qwen-vl"),
    ("bailian", "minimax", "minimax"),
    ("bailian", "qwen", "qwen"),
)
_STRONG_MODEL_MARKERS = frozenset(
    {
        "claude",
        "deepseek",
        "gemini",
        "gpt4",
        "gpt-4",
        "gpt5",
        "gpt-5",
        "opus",
        "sonnet",
    }
)
_STRONG_MODEL_TOKENS = frozenset({"o1", "o3", "o4"})
_NORMALIZED_STRONG_MODEL_MARKERS = frozenset(
    {"claude", "deepseek", "gemini", "gpt4", "gpt5", "o1", "o3", "o4"}
)
_ROLLING_MARKERS = frozenset(
    {"latest", "rolling", "current", "default", "auto", "stable", "blue", "green", "canary"}
)
_UNVERSIONED_ALIASES = frozenset({"minimax", "qwen", "qwen3", "qwen-vl"})
_IMMUTABLE_VERSION_MARKERS = (
    re.compile(r"(?:^|[._-])20[0-9]{6}(?:$|[._-])"),
    re.compile(
        r"(?:^|[._-])20[0-9]{2}[._-](?:0[1-9]|1[0-2])"
        r"[._-](?:0[1-9]|[12][0-9]|3[01])(?:$|[._-])"
    ),
    re.compile(r"(?:^|[._-])2[0-9](?:0[1-9]|1[0-2])(?:$|[._-])"),
    re.compile(r"(?:^|[._-])sha256[._-][0-9a-f]{8,64}(?:$|[._-])"),
)
_POLICY_DIGEST_DOMAIN = b"insurancekb.model-policy.approved-identities.v2\0"
_CONTEXT_DIGEST_DOMAIN = b"insurancekb.model-policy.call-context.v1\0"
_DENY_SCOPE_DIGEST_DOMAIN = b"insurancekb.model-policy.deny-receipt-scope.v1\0"
_DECISION_CONSTRUCTION_SEAL = object()
_AWARE_DATETIME = TypeAdapter(AwareDatetime)
_AUTHORITY_PID = os.getpid()
_AUTHORITY_NONCE = secrets.token_bytes(32)


def _canonical_digest(domain: bytes, value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(domain + encoded).hexdigest()


def _approved_keys_digest(keys: frozenset[IdentityKey]) -> str:
    return _canonical_digest(_POLICY_DIGEST_DOMAIN, sorted(keys))


def _call_context_digest(context: ModelCallContext) -> str:
    return _canonical_digest(
        _CONTEXT_DIGEST_DOMAIN,
        context.model_dump(mode="json", round_trip=True),
    )


def _deny_scope_digest(
    request: StrictAdmissionRequestBinding,
    binding: AdmissionBinding,
    identity: ModelIdentity,
    template_hash: str,
) -> str:
    """Create a readable DENY scope from trusted admission facts only."""

    return _canonical_digest(
        _DENY_SCOPE_DIGEST_DOMAIN,
        {
            "request_digest": request.request_digest,
            "binding_digest": binding.binding_digest,
            "identity_key": identity.identity_key,
            "template_hash": template_hash,
        },
    )


class ModelPolicyDenied(PermissionError):
    """Typed policy refusal with a stable, secret-free reason code."""

    _MESSAGES = {
        "strong_model": "production model identity is outside the weak-model boundary",
        "provider_not_approved": "production model provider is not code-owned",
        "family_not_approved": "production model family is not approved",
        "invalid_identity": "production model identity is invalid",
        "invalid_call_context": "production model call context is invalid",
        "invalid_verified_admission": "verified admission capability is invalid",
        "invalid_production_policy": "production model policy is unavailable",
        "rolling_identity": "production model identity is not immutable",
        "identity_not_approved": "production model identity is not approved",
    }

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(self._MESSAGES.get(reason_code, "production model policy denied"))


@dataclass(frozen=True, slots=True)
class _PolicyState:
    approved_identity_keys: frozenset[IdentityKey]
    policy_snapshot_digest: str
    pid: int
    process_nonce: bytes


_POLICY_STATES: WeakKeyDictionary[object, _PolicyState] = WeakKeyDictionary()
_POLICY_LOCK = RLock()


class ProductionModelPolicy:
    """Immutable identity policy backed by a process-local canonical snapshot."""

    __slots__ = ("__weakref__",)

    def __init__(self, approved_identity_keys: Iterable[IdentityKey]) -> None:
        keys = _normalize_identity_keys(approved_identity_keys)
        state = _PolicyState(
            approved_identity_keys=keys,
            policy_snapshot_digest=_approved_keys_digest(keys),
            pid=_AUTHORITY_PID,
            process_nonce=_AUTHORITY_NONCE,
        )
        with _POLICY_LOCK:
            if self in _POLICY_STATES:
                raise TypeError("ProductionModelPolicy is already initialized")
            _POLICY_STATES[self] = state

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("ProductionModelPolicy is immutable")

    def __copy__(self) -> ProductionModelPolicy:
        raise TypeError("ProductionModelPolicy cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> ProductionModelPolicy:
        raise TypeError("ProductionModelPolicy cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("ProductionModelPolicy cannot be serialized")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> tuple[object, ...]:
        raise TypeError("ProductionModelPolicy cannot be serialized")

    @property
    def approved_identity_keys(self) -> frozenset[IdentityKey]:
        state = _get_policy_state(self)
        if state is None:
            raise ModelPolicyDenied("invalid_production_policy")
        return state.approved_identity_keys

    @property
    def policy_snapshot_digest(self) -> str:
        state = _get_policy_state(self)
        if state is None:
            raise ModelPolicyDenied("invalid_production_policy")
        return state.policy_snapshot_digest

    def evaluate(self, identity: ModelIdentity) -> ModelIdentity:
        state = _get_policy_state(self)
        if state is None:
            raise ModelPolicyDenied("invalid_production_policy")
        return _evaluate_identity(identity, state.approved_identity_keys)

    def _evaluate_call(
        self,
        verified_admission: VerifiedAdmission,
        context: ModelCallContext,
        /,
    ) -> _PolicyDecision:
        state = _get_policy_state(self)
        if state is None:
            raise ModelPolicyDenied("invalid_production_policy")
        return _evaluate_call_with_snapshot(
            state,
            verified_admission,
            context,
        )


def _get_policy_state(value: object) -> _PolicyState | None:
    if not isinstance(value, ProductionModelPolicy):
        return None
    with _POLICY_LOCK:
        state = _POLICY_STATES.get(value)
        if (
            state is None
            or state.pid != _AUTHORITY_PID
            or state.process_nonce != _AUTHORITY_NONCE
            or os.getpid() != _AUTHORITY_PID
        ):
            return None
        return state


def _evaluate_identity(
    identity: ModelIdentity,
    approved_identity_keys: frozenset[IdentityKey],
) -> ModelIdentity:
    validated = _validate_production_identity_declaration(identity)
    if validated.identity_key not in approved_identity_keys:
        raise ModelPolicyDenied("identity_not_approved")
    return validated


def _validate_production_identity_declaration(
    identity: ModelIdentity,
) -> ModelIdentity:
    """Validate weak-model shape without granting deployment approval."""

    try:
        validated = ModelIdentity.model_validate(
            identity.model_dump(mode="python", round_trip=True, warnings=False)
        )
    except (AttributeError, TypeError, ValueError):
        raise ModelPolicyDenied("invalid_identity") from None
    if not any(
        provider == validated.provider
        for provider, _family in _TRUSTED_PROVIDER_FAMILY_KEYS
    ):
        raise ModelPolicyDenied("provider_not_approved")
    if (validated.provider, validated.family) not in _TRUSTED_PROVIDER_FAMILY_KEYS:
        raise ModelPolicyDenied("family_not_approved")
    deployment = validated.deployment_id.casefold()
    normalized_deployment = re.sub(r"[^a-z0-9]+", "", deployment)
    if any(marker in deployment for marker in _STRONG_MODEL_MARKERS) or any(
        marker in normalized_deployment for marker in _NORMALIZED_STRONG_MODEL_MARKERS
    ):
        raise ModelPolicyDenied("strong_model")
    tokens = frozenset(filter(None, re.split(r"[^a-z0-9]+", deployment)))
    if tokens.intersection(_STRONG_MODEL_TOKENS):
        raise ModelPolicyDenied("strong_model")
    if deployment in _UNVERSIONED_ALIASES or tokens.intersection(_ROLLING_MARKERS):
        raise ModelPolicyDenied("rolling_identity")
    resolved_family = next(
        (
            family
            for provider, prefix, family in _TRUSTED_DEPLOYMENT_NAMESPACES
            if provider == validated.provider
            and normalized_deployment.startswith(prefix)
        ),
        None,
    )
    if resolved_family != validated.family:
        raise ModelPolicyDenied("invalid_identity")
    if not any(pattern.search(deployment) for pattern in _IMMUTABLE_VERSION_MARKERS):
        raise ModelPolicyDenied("rolling_identity")
    return validated


def _evaluate_call_with_snapshot(
    policy_state: _PolicyState,
    verified_admission: VerifiedAdmission,
    context: ModelCallContext,
) -> _PolicyDecision:
    evaluated_at = datetime.now(UTC)
    verified_snapshot = _verified_authority_snapshot(verified_admission)
    if verified_snapshot is None:
        raise ModelPolicyDenied("invalid_verified_admission")
    request, binding, verification_receipt = verified_snapshot
    try:
        context = ModelCallContext.model_validate(
            context.model_dump(mode="python", round_trip=True, warnings=False)
        )
    except (AttributeError, TypeError, ValueError):
        raise ModelPolicyDenied("invalid_call_context") from None

    mismatch_checks: tuple[tuple[object, object, PolicyReasonCode], ...] = (
        (context.purpose, binding.actual_purpose, "purpose_mismatch"),
        (
            context.run_schema_version,
            binding.actual_run_schema_version,
            "run_schema_version_mismatch",
        ),
        (context.space_id, binding.actual_space_id, "space_id_mismatch"),
        (context.run_id, binding.actual_run_id, "run_id_mismatch"),
        (context.run_revision, binding.actual_run_revision, "run_revision_mismatch"),
        (
            context.admission_hash,
            binding.actual_admission_artifact_digest,
            "admission_artifact_digest_mismatch",
        ),
        (
            context.verified_binding_digest,
            verification_receipt.verified_binding_digest,
            "verified_binding_digest_mismatch",
        ),
        (
            context.model_plan_hash,
            binding.actual_model_plan_hash,
            "model_plan_hash_mismatch",
        ),
    )
    for candidate, approved, reason_code in mismatch_checks:
        if candidate != approved:
            return _deny(
                policy_state,
                verified_admission,
                request,
                binding,
                verification_receipt,
                context,
                reason_code=reason_code,
                evaluated_at=evaluated_at,
            )
    if binding.actual_expires_at <= evaluated_at:
        return _deny(
            policy_state,
            verified_admission,
            request,
            binding,
            verification_receipt,
            context,
            reason_code="admission_expired",
            evaluated_at=evaluated_at,
        )
    if context.template_hash not in binding.approved_template_hashes:
        return _deny(
            policy_state,
            verified_admission,
            request,
            binding,
            verification_receipt,
            context,
            reason_code="template_not_approved",
            evaluated_at=evaluated_at,
        )
    try:
        identity = _evaluate_identity(
            context.identity,
            policy_state.approved_identity_keys,
        )
    except ModelPolicyDenied as denied:
        return _deny(
            policy_state,
            verified_admission,
            request,
            binding,
            verification_receipt,
            context,
            reason_code=cast(PolicyReasonCode, denied.reason_code),
            evaluated_at=evaluated_at,
        )
    if identity not in binding.approved_identities:
        return _deny(
            policy_state,
            verified_admission,
            request,
            binding,
            verification_receipt,
            context,
            reason_code="identity_not_admission_approved",
            evaluated_at=evaluated_at,
        )

    permit_view = ModelPermitView(
        identity=identity,
        purpose=binding.actual_purpose,
        run_schema_version=binding.actual_run_schema_version,
        space_id=binding.actual_space_id,
        run_id=binding.actual_run_id,
        run_revision=binding.actual_run_revision,
        admission_hash=binding.actual_admission_artifact_digest,
        verified_binding_digest=verification_receipt.verified_binding_digest,
        template_hash=context.template_hash,
        model_plan_hash=binding.actual_model_plan_hash,
        policy_snapshot_digest=policy_state.policy_snapshot_digest,
        call_scope_hash=context.call_scope_hash,
        expires_at=binding.actual_expires_at,
    )
    issued_permit = _issue_model_permit(
        permit_view,
        verified_admission,
        issued_at=evaluated_at,
    )
    receipt = PolicyReceipt(
        decision="ALLOW",
        reason_code="policy_allowed",
        identity_key=identity.identity_key,
        purpose=binding.actual_purpose,
        run_schema_version=binding.actual_run_schema_version,
        space_id=binding.actual_space_id,
        run_id=binding.actual_run_id,
        run_revision=binding.actual_run_revision,
        admission_hash=binding.actual_admission_artifact_digest,
        request_digest=request.request_digest,
        binding_digest=binding.binding_digest,
        verified_binding_digest=verification_receipt.verified_binding_digest,
        template_hash=context.template_hash,
        model_plan_hash=binding.actual_model_plan_hash,
        call_scope_hash=context.call_scope_hash,
        attempted_context_digest=_call_context_digest(context),
        policy_snapshot_digest=policy_state.policy_snapshot_digest,
        permit_digest=_model_permit_view_digest(permit_view),
        permit_view=permit_view,
        evaluated_at=evaluated_at,
    )
    return _issue_policy_decision(
        receipt,
        issued_permit,
        verified_admission,
        context,
        policy_state.policy_snapshot_digest,
    )


def _trusted_identity(
    binding_identities: tuple[ModelIdentity, ...],
    attempted: ModelIdentity,
) -> ModelIdentity:
    return next(
        (identity for identity in binding_identities if identity.role == attempted.role),
        binding_identities[0],
    )


def _deny(
    policy_state: _PolicyState,
    verified_admission: VerifiedAdmission,
    request: StrictAdmissionRequestBinding,
    binding: AdmissionBinding,
    verification_receipt: AdmissionVerificationReceipt,
    context: ModelCallContext,
    *,
    reason_code: PolicyReasonCode,
    evaluated_at: datetime,
) -> _PolicyDecision:
    identity = _trusted_identity(binding.approved_identities, context.identity)
    template_hash = (
        context.template_hash
        if context.template_hash in binding.approved_template_hashes
        else binding.approved_template_hashes[0]
    )
    receipt = PolicyReceipt(
        decision="DENY",
        reason_code=reason_code,
        identity_key=identity.identity_key,
        purpose=binding.actual_purpose,
        run_schema_version=binding.actual_run_schema_version,
        space_id=binding.actual_space_id,
        run_id=binding.actual_run_id,
        run_revision=binding.actual_run_revision,
        admission_hash=binding.actual_admission_artifact_digest,
        request_digest=request.request_digest,
        binding_digest=binding.binding_digest,
        verified_binding_digest=verification_receipt.verified_binding_digest,
        template_hash=template_hash,
        model_plan_hash=binding.actual_model_plan_hash,
        call_scope_hash=_deny_scope_digest(request, binding, identity, template_hash),
        attempted_context_digest=_call_context_digest(context),
        policy_snapshot_digest=policy_state.policy_snapshot_digest,
        evaluated_at=evaluated_at,
    )
    return _issue_policy_decision(
        receipt,
        None,
        verified_admission,
        context,
        policy_state.policy_snapshot_digest,
    )


def _permit_view_digest(view: ModelPermitView) -> str:
    """Backward-compatible package-private alias for tests and Task 4."""

    return _model_permit_view_digest(view)


def _normalize_checked_at(value: datetime | None) -> datetime | None:
    candidate: object = datetime.now(UTC) if value is None else value
    try:
        return _AWARE_DATETIME.validate_python(candidate).astimezone(UTC)
    except Exception:
        return None


def _permit_matches_call_context(
    permit: object,
    verified_admission: VerifiedAdmission,
    context: ModelCallContext,
    *,
    _checked_at: datetime | None = None,
    _expected_policy_snapshot_digest: str | None = None,
) -> bool:
    """Compare canonical registry snapshots immediately before transport."""

    checked_at = _normalize_checked_at(_checked_at)
    if checked_at is None:
        return False
    try:
        validated_context = ModelCallContext.model_validate(
            context.model_dump(mode="python", round_trip=True, warnings=False)
        )
    except Exception:
        return False
    snapshot = _permit_authority_snapshot(permit)
    if snapshot is None:
        return False
    view, _issued_at, issued_for = snapshot
    return (
        issued_for is verified_admission
        and view.expires_at > checked_at
        and _view_matches_context(view, validated_context)
        and (
            _expected_policy_snapshot_digest is None
            or view.policy_snapshot_digest == _expected_policy_snapshot_digest
        )
    )


def _view_matches_context(view: ModelPermitView, context: ModelCallContext) -> bool:
    return (
        view.identity == context.identity
        and view.purpose == context.purpose
        and view.run_schema_version == context.run_schema_version
        and view.space_id == context.space_id
        and view.run_id == context.run_id
        and view.run_revision == context.run_revision
        and view.admission_hash == context.admission_hash
        and view.verified_binding_digest == context.verified_binding_digest
        and view.template_hash == context.template_hash
        and view.model_plan_hash == context.model_plan_hash
        and view.call_scope_hash == context.call_scope_hash
    )


@dataclass(frozen=True, slots=True)
class _DecisionState:
    receipt_json: str
    context_json: str
    permit: IssuedModelPermit | None
    verified_admission: VerifiedAdmission
    policy_snapshot_digest: str
    pid: int
    process_nonce: bytes


_DECISION_STATES: WeakKeyDictionary[object, _DecisionState] = WeakKeyDictionary()
_DECISION_LOCK = RLock()


class _PolicyDecision:
    """Sealed package-local handle; all authority lives in the weak registry."""

    __slots__ = ("__weakref__",)

    def __new__(
        cls,
        *_args: object,
        _seal: object | None = None,
        **_kwargs: object,
    ) -> _PolicyDecision:
        if cls is not _PolicyDecision or _seal is not _DECISION_CONSTRUCTION_SEAL:
            raise TypeError("policy decisions are issued only by canonical policy")
        return super().__new__(cls)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("policy decisions are immutable")

    def __copy__(self) -> _PolicyDecision:
        raise TypeError("policy decisions cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> _PolicyDecision:
        raise TypeError("policy decisions cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("policy decisions cannot be serialized")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> tuple[object, ...]:
        raise TypeError("policy decisions cannot be serialized")

    @property
    def receipt(self) -> PolicyReceipt:
        state = _get_decision_state(self)
        if state is None:
            raise TypeError("policy decision authority is unavailable")
        return PolicyReceipt.model_validate_json(state.receipt_json)


def _get_decision_state(value: object) -> _DecisionState | None:
    if not isinstance(value, _PolicyDecision):
        return None
    with _DECISION_LOCK:
        state = _DECISION_STATES.get(value)
        if (
            state is None
            or state.pid != _AUTHORITY_PID
            or state.process_nonce != _AUTHORITY_NONCE
            or os.getpid() != _AUTHORITY_PID
        ):
            return None
        return state


def _issue_policy_decision(
    receipt: PolicyReceipt,
    permit: IssuedModelPermit | None,
    verified_admission: VerifiedAdmission,
    context: ModelCallContext,
    policy_snapshot_digest: str,
) -> _PolicyDecision:
    try:
        validated_receipt = PolicyReceipt.model_validate(
            receipt.model_dump(mode="python", round_trip=True, warnings=False)
        )
        validated_context = ModelCallContext.model_validate(
            context.model_dump(mode="python", round_trip=True, warnings=False)
        )
    except Exception:
        raise ValueError("invalid policy decision components") from None
    state = _DecisionState(
        receipt_json=validated_receipt.model_dump_json(),
        context_json=validated_context.model_dump_json(),
        permit=permit,
        verified_admission=verified_admission,
        policy_snapshot_digest=policy_snapshot_digest,
        pid=_AUTHORITY_PID,
        process_nonce=_AUTHORITY_NONCE,
    )
    if not _decision_state_is_coherent(state):
        raise ValueError("policy decision components do not match")
    decision = _PolicyDecision.__new__(
        _PolicyDecision,
        _seal=_DECISION_CONSTRUCTION_SEAL,
    )
    with _DECISION_LOCK:
        _DECISION_STATES[decision] = state
    return decision


def _decision_state_is_coherent(state: _DecisionState) -> bool:
    try:
        receipt = PolicyReceipt.model_validate_json(state.receipt_json)
        context = ModelCallContext.model_validate_json(state.context_json)
    except Exception:
        return False
    verified_snapshot = _verified_authority_snapshot(state.verified_admission)
    if verified_snapshot is None:
        return False
    request, binding, verification_receipt = verified_snapshot
    trusted_identity = _trusted_identity(binding.approved_identities, context.identity)
    trusted_template = (
        context.template_hash
        if context.template_hash in binding.approved_template_hashes
        else binding.approved_template_hashes[0]
    )
    common = (
        receipt.request_digest == request.request_digest
        and receipt.binding_digest == binding.binding_digest
        and receipt.verified_binding_digest == verification_receipt.verified_binding_digest
        and receipt.attempted_context_digest == _call_context_digest(context)
        and receipt.policy_snapshot_digest == state.policy_snapshot_digest
    )
    if not common:
        return False
    if receipt.decision == "DENY":
        return (
            state.permit is None
            and receipt.identity_key == trusted_identity.identity_key
            and receipt.purpose == binding.actual_purpose
            and receipt.run_schema_version == binding.actual_run_schema_version
            and receipt.space_id == binding.actual_space_id
            and receipt.run_id == binding.actual_run_id
            and receipt.run_revision == binding.actual_run_revision
            and receipt.admission_hash == binding.actual_admission_artifact_digest
            and receipt.template_hash == trusted_template
            and receipt.model_plan_hash == binding.actual_model_plan_hash
            and receipt.call_scope_hash
            == _deny_scope_digest(request, binding, trusted_identity, trusted_template)
        )
    permit_snapshot = _permit_authority_snapshot(state.permit)
    if permit_snapshot is None:
        return False
    view, issued_at, issued_for = permit_snapshot
    return (
        issued_for is state.verified_admission
        and receipt.permit_view == view
        and receipt.permit_digest == _model_permit_view_digest(view)
        and receipt.evaluated_at == issued_at
        and view.policy_snapshot_digest == state.policy_snapshot_digest
        and _view_matches_context(view, context)
    )


def _is_policy_decision(value: object) -> bool:
    state = _get_decision_state(value)
    if state is None:
        return False
    with _DECISION_LOCK:
        return _decision_state_is_coherent(state)


def _decision_authorizes_call(
    decision: object,
    verified_admission: VerifiedAdmission,
    context: ModelCallContext,
    *,
    _checked_at: datetime | None = None,
    _expected_policy_snapshot_digest: str | None = None,
) -> bool:
    """Atomically consume canonical decision/permit snapshots for authorization."""

    with _DECISION_LOCK:
        state = _get_decision_state(decision)
        if state is None or state.verified_admission is not verified_admission:
            return False
        if (
            _expected_policy_snapshot_digest is not None
            and state.policy_snapshot_digest != _expected_policy_snapshot_digest
        ):
            return False
        if not _decision_state_is_coherent(state):
            return False
        receipt = PolicyReceipt.model_validate_json(state.receipt_json)
        if receipt.decision != "ALLOW" or state.permit is None:
            return False
        return _permit_matches_call_context(
            state.permit,
            verified_admission,
            context,
            _checked_at=_checked_at,
            _expected_policy_snapshot_digest=state.policy_snapshot_digest,
        )


def _reset_policy_authority_after_fork() -> None:
    global _AUTHORITY_NONCE, _AUTHORITY_PID
    global _DECISION_LOCK, _DECISION_STATES, _POLICY_LOCK, _POLICY_STATES
    _POLICY_LOCK = RLock()
    _DECISION_LOCK = RLock()
    _POLICY_STATES = WeakKeyDictionary()
    _DECISION_STATES = WeakKeyDictionary()
    _AUTHORITY_PID = os.getpid()
    _AUTHORITY_NONCE = secrets.token_bytes(32)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_policy_authority_after_fork)
