"""Frozen admission DTOs and opaque in-process authority capabilities."""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Protocol, SupportsIndex

from pydantic import AwareDatetime, model_validator

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


def _canonical_digest(domain: bytes, value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(domain + encoded).hexdigest()


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
        roles = tuple(identity.role for identity in self.approved_identities)
        if len(set(roles)) != len(roles):
            raise ValueError("approved model identity roles must be unique")
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


def _request_matches_binding(
    request: StrictAdmissionRequestBinding,
    binding: AdmissionBinding,
) -> bool:
    expected = request.model_dump(mode="python", round_trip=True)
    actual = binding.model_dump(mode="python", round_trip=True)
    return all(
        actual.get(f"actual_{name.removeprefix('expected_')}") == value
        for name, value in expected.items()
    )


def _issue_verified_admission(
    request: StrictAdmissionRequestBinding,
    binding: AdmissionBinding,
    *,
    verifier_id: str,
    verifier_version: str,
    verified_at: AwareDatetime,
) -> VerifiedAdmission:
    """Internal composition hook; no public verifier implementation is provided here."""

    if (
        binding.actual_state != "READY"
        or not binding.approved_identities
        or not binding.approved_template_hashes
        or not _request_matches_binding(request, binding)
    ):
        raise ValueError("admission request does not match READY binding")
    verified_binding_digest = _verified_digest(request, binding)
    receipt = AdmissionVerificationReceipt(
        verifier_id=verifier_id,
        verifier_version=verifier_version,
        verified_at=verified_at,
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
        return (
            value._seal is _PROCESS_SEAL
            and type(value._request) is StrictAdmissionRequestBinding
            and type(value._binding) is AdmissionBinding
            and type(value._receipt) is AdmissionVerificationReceipt
            and value._binding.actual_state == "READY"
            and bool(value._binding.approved_identities)
            and bool(value._binding.approved_template_hashes)
            and _request_matches_binding(value._request, value._binding)
            and value._receipt.request_digest == value._request.request_digest
            and value._receipt.binding_digest == value._binding.binding_digest
            and value._receipt.verified_binding_digest
            == _verified_digest(value._request, value._binding)
        )
    except (AttributeError, TypeError, ValueError):
        return False


class IssuedModelPermit:
    """Opaque process-local model-call authority; its public view is only a receipt."""

    __slots__ = ("_seal", "_verified_admission", "_view")
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
) -> IssuedModelPermit:
    """Internal composition hook; gateway/call-scope evaluation belongs to later tasks."""

    if not _is_verified_admission(verified) or not _view_matches_verified(view, verified):
        raise ValueError("permit view does not match verified admission")
    capability = IssuedModelPermit.__new__(IssuedModelPermit, _seal=_PROCESS_SEAL)
    object.__setattr__(capability, "_view", view)
    object.__setattr__(capability, "_verified_admission", verified)
    object.__setattr__(capability, "_seal", _PROCESS_SEAL)
    return capability


def _is_issued_model_permit(value: object) -> bool:
    if not isinstance(value, IssuedModelPermit):
        return False
    try:
        return (
            value._seal is _PROCESS_SEAL
            and type(value._view) is ModelPermitView
            and _is_verified_admission(value._verified_admission)
            and _view_matches_verified(value._view, value._verified_admission)
        )
    except (AttributeError, TypeError, ValueError):
        return False
