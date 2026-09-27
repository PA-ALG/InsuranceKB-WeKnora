"""Independent G3 root of trust and delegated stage verification."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal, Self

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import StrictStr, StringConstraints, model_validator

from insurance_harness.model_policy import AdmissionPolicyDenied

from . import trust_policy
from .g3_models import (
    G3BoundedApprovalEnvelopeV1,
    G3ModelProcessingAuthorizationEnvelopeV1,
    _G3Model,
    parent_authorization_signed_bytes,
    stage_approval_signed_bytes,
)

NonBlankStr = Annotated[StrictStr, StringConstraints(min_length=1, max_length=1024)]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
G3_ROOT_POLICY_PATH = Path("/etc/insurancekb/run-admission/g3-bounded-root-policy.json")
_ROOT_DIR = G3_ROOT_POLICY_PATH.parent


class G3TrustedApproverV1(_G3Model):
    key_id: NonBlankStr
    public_key_b64: NonBlankStr
    public_key_fingerprint: Sha256Hex
    human_identity: NonBlankStr
    role: Literal["g3-model-processing-authorization-approver"]
    signature_domain: Literal["insurancekb.run-admission.g3-model-processing-authorization.v1"]
    allowed_space_ids: tuple[NonBlankStr, ...]
    allowed_parent_contracts: tuple[Literal["g3-model-processing-authorization.830.v1"], ...]

    @model_validator(mode="after")
    def validate_authority(self) -> Self:
        try:
            raw = base64.b64decode(self.public_key_b64, validate=True)
            Ed25519PublicKey.from_public_bytes(raw)
        except Exception:
            raise ValueError("invalid G3 trusted key") from None
        if len(raw) != 32 or base64.b64encode(raw).decode() != self.public_key_b64:
            raise ValueError("noncanonical G3 trusted key")
        if hashlib.sha256(raw).hexdigest() != self.public_key_fingerprint:
            raise ValueError("G3 trusted key fingerprint mismatch")
        if not self.allowed_space_ids or len(set(self.allowed_space_ids)) != len(
            self.allowed_space_ids
        ):
            raise ValueError("invalid G3 trusted space scope")
        if self.allowed_space_ids != tuple(sorted(self.allowed_space_ids)):
            raise ValueError("G3 trusted space scope is not sorted")
        if self.allowed_parent_contracts != ("g3-model-processing-authorization.830.v1",):
            raise ValueError("invalid G3 parent contract scope")
        return self

    @property
    def public_key(self) -> Ed25519PublicKey:
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(self.public_key_b64))


class G3RootTrustPolicyV1(_G3Model):
    schema_version: Literal["insurancekb.g3-bounded-run-admission-root-policy.v1"]
    approvers: tuple[G3TrustedApproverV1, ...]

    @model_validator(mode="after")
    def validate_approvers(self) -> Self:
        keys = tuple((a.key_id, a.public_key_fingerprint) for a in self.approvers)
        if not keys or len(set(keys)) != len(keys) or keys != tuple(sorted(keys)):
            raise ValueError("G3 approvers must be sorted and unique")
        return self


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_g3_root_trust_policy() -> G3RootTrustPolicyV1:
    try:
        raw = trust_policy._read_root_protected_file(
            G3_ROOT_POLICY_PATH,
            root=_ROOT_DIR,
            max_bytes=256 * 1024,
            reason_code="invalid_g3_root_policy",
        )
        value = json.loads(raw, object_pairs_hook=_reject_duplicates)
        return G3RootTrustPolicyV1.model_validate(value)
    except AdmissionPolicyDenied:
        raise
    except Exception:
        raise AdmissionPolicyDenied("invalid_g3_root_policy") from None


def verify_parent_authorization(
    policy: G3RootTrustPolicyV1,
    envelope: G3ModelProcessingAuthorizationEnvelopeV1,
) -> G3TrustedApproverV1:
    matches = tuple(
        a
        for a in policy.approvers
        if (a.key_id, a.public_key_fingerprint, a.human_identity)
        == (envelope.key_id, envelope.public_key_fingerprint, envelope.human_identity)
    )
    if len(matches) != 1:
        raise AdmissionPolicyDenied("untrusted_g3_parent_key")
    approver = matches[0]
    if envelope.payload.space_id not in approver.allowed_space_ids:
        raise AdmissionPolicyDenied("g3_parent_scope_mismatch")
    try:
        signature = base64.b64decode(envelope.signature_b64, validate=True)
        approver.public_key.verify(signature, parent_authorization_signed_bytes(envelope))
    except (InvalidSignature, TypeError, ValueError):
        raise AdmissionPolicyDenied("invalid_g3_parent_signature") from None
    return approver


def verify_delegated_stage_signature(
    parent: G3ModelProcessingAuthorizationEnvelopeV1,
    stage: G3BoundedApprovalEnvelopeV1,
) -> None:
    signer = parent.payload.delegated_stage_signer
    if (
        stage.stage_signer_key_id != signer.key_id
        or stage.stage_signer_public_key_fingerprint != signer.public_key_fingerprint
    ):
        raise AdmissionPolicyDenied("g3_stage_signer_mismatch")
    try:
        key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(signer.public_key_b64, validate=True)
        )
        key.verify(
            base64.b64decode(stage.signature_b64, validate=True), stage_approval_signed_bytes(stage)
        )
    except (InvalidSignature, TypeError, ValueError):
        raise AdmissionPolicyDenied("invalid_g3_stage_signature") from None


__all__ = [
    "G3RootTrustPolicyV1",
    "G3TrustedApproverV1",
    "G3_ROOT_POLICY_PATH",
    "load_g3_root_trust_policy",
    "verify_delegated_stage_signature",
    "verify_parent_authorization",
]
