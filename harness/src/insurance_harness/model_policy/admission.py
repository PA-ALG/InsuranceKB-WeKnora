"""Frozen admission DTOs and opaque in-process authority capabilities."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Literal, Protocol, SupportsIndex

from pydantic import AwareDatetime, TypeAdapter, field_validator, model_validator

from .models import (
    CleanIntegrationSha,
    ModelIdentity,
    ModelPermitView,
    NonBlankStr,
    Sha256Hex,
    _ImmutableModel,
)

_REQUEST_DIGEST_DOMAIN = b"insurancekb.model-policy.admission-request.v1\0"
_BINDING_DIGEST_DOMAIN = b"insurancekb.model-policy.admission-binding.v1\0"
_VERIFIED_DIGEST_DOMAIN = b"insurancekb.model-policy.verified-admission.v1\0"
_PROCESS_SEAL = object()
_AWARE_DATETIME = TypeAdapter(AwareDatetime)


def _canonical_digest(domain: bytes, value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(domain + encoded).hexdigest()


def _revalidate[ModelT: _ImmutableModel](
    model_type: type[ModelT],
    value: object,
) -> ModelT:
    """Rebuild a DTO from raw fields so model_construct cannot cross the boundary."""

    try:
        if not isinstance(value, _ImmutableModel):
            raise TypeError
        payload = value.model_dump(mode="python", round_trip=True, warnings=False)
        return model_type.model_validate(payload)
    except Exception:
        raise ValueError("invalid model-policy DTO") from None


def _stored_equals_validated(stored: object, validated: _ImmutableModel) -> bool:
    return type(stored) is type(validated) and stored == validated


class StrictAdmissionRequestBinding(_ImmutableModel):
    """Caller-declared expected identity; every value is independently mandatory."""

    expected_purpose: NonBlankStr
    expected_run_schema_version: NonBlankStr
    expected_run_id: NonBlankStr
    expected_run_revision: NonBlankStr
    expected_space_id: NonBlankStr
    expected_admission_artifact_ref: NonBlankStr
    expected_admission_artifact_digest: Sha256Hex
    expected_manifest_hash: Sha256Hex
    expected_eligibility_hash: Sha256Hex
    expected_golden_slice_hash: Sha256Hex
    expected_routing_policy_hash: Sha256Hex
    expected_schema_hash: Sha256Hex
    expected_template_lock_hash: Sha256Hex
    expected_structured_dispatch_hash: Sha256Hex
    expected_model_plan_hash: Sha256Hex
    expected_deployment_roles_hash: Sha256Hex
    expected_resource_caps_hash: Sha256Hex
    expected_rights_hash: Sha256Hex
    expected_provenance_hash: Sha256Hex
    expected_clean_integration_sha: CleanIntegrationSha

    @property
    def request_digest(self) -> str:
        return _canonical_digest(
            _REQUEST_DIGEST_DOMAIN,
            self.model_dump(mode="json", round_trip=True),
        )


class AdmissionBinding(_ImmutableModel):
    """Serializable actual admission facts; READY data alone is not authority."""

    actual_purpose: NonBlankStr
    actual_run_schema_version: NonBlankStr
    actual_run_id: NonBlankStr
    actual_run_revision: NonBlankStr
    actual_space_id: NonBlankStr
    actual_admission_artifact_ref: NonBlankStr
    actual_admission_artifact_digest: Sha256Hex
    actual_manifest_hash: Sha256Hex
    actual_eligibility_hash: Sha256Hex
    actual_golden_slice_hash: Sha256Hex
    actual_routing_policy_hash: Sha256Hex
    actual_schema_hash: Sha256Hex
    actual_template_lock_hash: Sha256Hex
    actual_structured_dispatch_hash: Sha256Hex
    actual_model_plan_hash: Sha256Hex
    actual_deployment_roles_hash: Sha256Hex
    actual_resource_caps_hash: Sha256Hex
    actual_rights_hash: Sha256Hex
    actual_provenance_hash: Sha256Hex
    actual_clean_integration_sha: CleanIntegrationSha
    actual_state: Literal["READY", "BLOCKED"]
    actual_expires_at: AwareDatetime
    approved_identities: tuple[ModelIdentity, ...]
    approved_template_hashes: tuple[Sha256Hex, ...]

    @model_validator(mode="after")
    def require_one_exact_identity_per_role(self) -> AdmissionBinding:
        try:
            identities = tuple(
                ModelIdentity.model_validate(
                    identity.model_dump(mode="python", round_trip=True, warnings=False)
                )
                for identity in self.approved_identities
            )
        except Exception:
            raise ValueError("approved model identities must be valid") from None

        roles = tuple(identity.role for identity in identities)
        if len(set(roles)) != len(roles):
            raise ValueError("approved model identity roles must be unique")
        templates = tuple(self.approved_template_hashes)
        if len(set(templates)) != len(templates):
            raise ValueError("approved template hashes must be unique")

        object.__setattr__(
            self,
            "approved_identities",
            tuple(sorted(identities, key=lambda identity: identity.identity_key)),
        )
        object.__setattr__(self, "approved_template_hashes", tuple(sorted(templates)))
        object.__setattr__(self, "actual_expires_at", self.actual_expires_at.astimezone(UTC))
        return self

    @property
    def binding_digest(self) -> str:
        return _canonical_digest(
            _BINDING_DIGEST_DOMAIN,
            self.model_dump(mode="json", round_trip=True),
        )


def _verified_digest(
    request: StrictAdmissionRequestBinding,
    binding: AdmissionBinding,
) -> str:
    return _canonical_digest(
        _VERIFIED_DIGEST_DOMAIN,
        {
            "request": request.model_dump(mode="json", round_trip=True),
            "binding": binding.model_dump(mode="json", round_trip=True),
        },
    )


class AdmissionVerificationReceipt(_ImmutableModel):
    """Serializable verification evidence that carries no process authority."""

    verifier_id: NonBlankStr
    verifier_version: NonBlankStr
    verified_at: AwareDatetime
    request_digest: Sha256Hex
    binding_digest: Sha256Hex
    verified_binding_digest: Sha256Hex

    @field_validator("verified_at", mode="after")
    @classmethod
    def normalize_verified_at_to_utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(UTC)


class VerifiedAdmission:
    """Opaque process-local proof returned only by a trusted admission verifier."""

    __slots__ = ("_binding", "_receipt", "_request", "_seal")
    _binding: AdmissionBinding
    _receipt: AdmissionVerificationReceipt
    _request: StrictAdmissionRequestBinding
    _seal: object

    def __new__(
        cls,
        *_args: object,
        _seal: object | None = None,
        **_kwargs: object,
    ) -> VerifiedAdmission:
        if cls is not VerifiedAdmission or _seal is not _PROCESS_SEAL:
            raise TypeError("VerifiedAdmission cannot be constructed by callers")
        return super().__new__(cls)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("VerifiedAdmission is immutable")

    def __copy__(self) -> VerifiedAdmission:
        raise TypeError("VerifiedAdmission cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> VerifiedAdmission:
        raise TypeError("VerifiedAdmission cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("VerifiedAdmission cannot be serialized")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> tuple[object, ...]:
        raise TypeError("VerifiedAdmission cannot be serialized")

    @property
    def request(self) -> StrictAdmissionRequestBinding:
        return self._request

    @property
    def binding(self) -> AdmissionBinding:
        return self._binding

    @property
    def verified_binding_digest(self) -> str:
        return self._receipt.verified_binding_digest

    @property
    def receipt(self) -> AdmissionVerificationReceipt:
        return self._receipt


class AdmissionVerifier(Protocol):
    """Port implemented by a later task's canonical admission adapter."""

    def verify(self, request: StrictAdmissionRequestBinding, /) -> VerifiedAdmission: ...


class AdmissionPolicyDenied(ValueError):
    """Stable, secret-free refusal raised at the admission capability boundary."""

    _MESSAGES = {
        "admission_not_ready": "admission binding is not READY",
        "admission_roles_missing": "READY admission has no approved model roles",
        "admission_templates_missing": "READY admission has no approved templates",
        "admission_expired": "admission binding is expired",
        "invalid_admission_request": "strict admission request is invalid",
        "invalid_admission_binding": "admission binding is invalid",
        "invalid_verified_admission": "verified admission capability is invalid",
        "unknown_admission_profile": "admission purpose/schema profile is not registered",
    }

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(self._MESSAGES.get(reason_code, "admission binding mismatch"))


def _request_binding_mismatch_reason(
    request: StrictAdmissionRequestBinding,
    binding: AdmissionBinding,
) -> str | None:
    expected = request.model_dump(mode="python", round_trip=True)
    actual = binding.model_dump(mode="python", round_trip=True)
    for name, value in expected.items():
        field = name.removeprefix("expected_")
        if actual.get(f"actual_{field}") != value:
            return f"{field}_mismatch"
    return None


def _request_matches_binding(
    request: StrictAdmissionRequestBinding,
    binding: AdmissionBinding,
) -> bool:
    return _request_binding_mismatch_reason(request, binding) is None


def _issue_verified_admission(
    request: StrictAdmissionRequestBinding,
    binding: AdmissionBinding,
    *,
    verifier_id: str,
    verifier_version: str,
    verified_at: AwareDatetime,
) -> VerifiedAdmission:
    """Internal composition hook; no public verifier implementation is provided here."""

    try:
        request = _revalidate(StrictAdmissionRequestBinding, request)
    except ValueError:
        raise AdmissionPolicyDenied("invalid_admission_request") from None
    try:
        binding = _revalidate(AdmissionBinding, binding)
    except ValueError:
        raise AdmissionPolicyDenied("invalid_admission_binding") from None
    try:
        normalized_verified_at = _AWARE_DATETIME.validate_python(verified_at).astimezone(UTC)
    except Exception:
        raise ValueError("verification time must be timezone-aware") from None

    if binding.actual_state != "READY":
        raise AdmissionPolicyDenied("admission_not_ready")
    if not binding.approved_identities:
        raise AdmissionPolicyDenied("admission_roles_missing")
    if not binding.approved_template_hashes:
        raise AdmissionPolicyDenied("admission_templates_missing")
    mismatch = _request_binding_mismatch_reason(request, binding)
    if mismatch is not None:
        raise AdmissionPolicyDenied(mismatch)
    if binding.actual_expires_at <= normalized_verified_at:
        raise AdmissionPolicyDenied("admission_expired")
    verified_binding_digest = _verified_digest(request, binding)
    receipt = AdmissionVerificationReceipt(
        verifier_id=verifier_id,
        verifier_version=verifier_version,
        verified_at=normalized_verified_at,
        request_digest=request.request_digest,
        binding_digest=binding.binding_digest,
        verified_binding_digest=verified_binding_digest,
    )
    capability = VerifiedAdmission.__new__(VerifiedAdmission, _seal=_PROCESS_SEAL)
    object.__setattr__(capability, "_request", request)
    object.__setattr__(capability, "_binding", binding)
    object.__setattr__(capability, "_receipt", receipt)
    object.__setattr__(capability, "_seal", _PROCESS_SEAL)
    return capability


def _is_verified_admission(value: object) -> bool:
    if not isinstance(value, VerifiedAdmission):
        return False
    try:
        request = _revalidate(StrictAdmissionRequestBinding, value._request)
        binding = _revalidate(AdmissionBinding, value._binding)
        receipt = _revalidate(AdmissionVerificationReceipt, value._receipt)
        return (
            value._seal is _PROCESS_SEAL
            and _stored_equals_validated(value._request, request)
            and _stored_equals_validated(value._binding, binding)
            and _stored_equals_validated(value._receipt, receipt)
            and binding.actual_state == "READY"
            and bool(binding.approved_identities)
            and bool(binding.approved_template_hashes)
            and binding.actual_expires_at > receipt.verified_at
            and _request_matches_binding(request, binding)
            and receipt.request_digest == request.request_digest
            and receipt.binding_digest == binding.binding_digest
            and receipt.verified_binding_digest == _verified_digest(request, binding)
        )
    except Exception:
        return False


class IssuedModelPermit:
    """Opaque process-local model-call authority; its public view is only a receipt."""

    __slots__ = ("_issued_at", "_seal", "_verified_admission", "_view")
    _issued_at: datetime
    _seal: object
    _verified_admission: VerifiedAdmission
    _view: ModelPermitView

    def __new__(
        cls,
        *_args: object,
        _seal: object | None = None,
        **_kwargs: object,
    ) -> IssuedModelPermit:
        if cls is not IssuedModelPermit or _seal is not _PROCESS_SEAL:
            raise TypeError("IssuedModelPermit cannot be constructed by callers")
        return super().__new__(cls)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("IssuedModelPermit is immutable")

    def __copy__(self) -> IssuedModelPermit:
        raise TypeError("IssuedModelPermit cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> IssuedModelPermit:
        raise TypeError("IssuedModelPermit cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("IssuedModelPermit cannot be serialized")

    def __reduce_ex__(self, _protocol: SupportsIndex) -> tuple[object, ...]:
        raise TypeError("IssuedModelPermit cannot be serialized")

    @property
    def view(self) -> ModelPermitView:
        return self._view

    @property
    def issued_at(self) -> datetime:
        return self._issued_at


def _view_matches_verified(view: ModelPermitView, verified: VerifiedAdmission) -> bool:
    binding = verified.binding
    return (
        view.identity in binding.approved_identities
        and view.purpose == binding.actual_purpose
        and view.run_schema_version == binding.actual_run_schema_version
        and view.space_id == binding.actual_space_id
        and view.run_id == binding.actual_run_id
        and view.run_revision == binding.actual_run_revision
        and view.admission_hash == binding.actual_admission_artifact_digest
        and view.verified_binding_digest == verified.verified_binding_digest
        and view.template_hash in binding.approved_template_hashes
        and view.model_plan_hash == binding.actual_model_plan_hash
        and view.expires_at == binding.actual_expires_at
    )


def _issue_model_permit(
    view: ModelPermitView,
    verified: VerifiedAdmission,
    *,
    issued_at: AwareDatetime,
) -> IssuedModelPermit:
    """Internal composition hook; gateway/call-scope evaluation belongs to later tasks."""

    view = _revalidate(ModelPermitView, view)
    try:
        normalized_issued_at = _AWARE_DATETIME.validate_python(issued_at).astimezone(UTC)
    except Exception:
        raise ValueError("permit issuance time must be timezone-aware") from None
    if not _is_verified_admission(verified) or not _view_matches_verified(view, verified):
        raise ValueError("permit view does not match verified admission")
    if view.expires_at <= normalized_issued_at:
        raise ValueError("model permit is expired")
    capability = IssuedModelPermit.__new__(IssuedModelPermit, _seal=_PROCESS_SEAL)
    object.__setattr__(capability, "_view", view)
    object.__setattr__(capability, "_verified_admission", verified)
    object.__setattr__(capability, "_issued_at", normalized_issued_at)
    object.__setattr__(capability, "_seal", _PROCESS_SEAL)
    return capability


def _is_issued_model_permit(value: object) -> bool:
    if not isinstance(value, IssuedModelPermit):
        return False
    try:
        view = _revalidate(ModelPermitView, value._view)
        issued_at = _AWARE_DATETIME.validate_python(value._issued_at).astimezone(UTC)
        return (
            value._seal is _PROCESS_SEAL
            and _stored_equals_validated(value._view, view)
            and value._issued_at.tzinfo is UTC
            and value._issued_at == issued_at
            and view.expires_at > issued_at
            and _is_verified_admission(value._verified_admission)
            and _view_matches_verified(view, value._verified_admission)
        )
    except Exception:
        return False
