"""Root-protected trust policy for OpenSpec 030 human admission approval."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Annotated, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import StrictStr, StringConstraints, model_validator

from insurance_harness.model_policy import AdmissionPolicyDenied

from .models import (
    ApprovalEnvelope,
    _FrozenModel,
    approval_signed_bytes,
)

_ROOT_TRUST_POLICY_PATH = Path("/etc/insurancekb/run-admission/root-policy.json")
_ROOT_TRUST_POLICY_DIR = Path("/etc/insurancekb/run-admission")
_ROOT_OWNER_UID = 0
_MAX_POLICY_BYTES = 256 * 1024
_APPROVER_ROLE = "mvp-run-admission-approver"

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]
Sha256Hex = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("duplicate JSON key")
        value[key] = item
    return value


class TrustedApprover(_FrozenModel):
    key_id: NonBlankStr
    public_key_b64: NonBlankStr
    public_key_fingerprint: Sha256Hex
    human_identity: NonBlankStr
    approver_role: Literal["mvp-run-admission-approver"]
    signature_domain: NonBlankStr
    allowed_purposes: tuple[NonBlankStr, ...]
    allowed_run_schema_versions: tuple[NonBlankStr, ...]
    allowed_space_ids: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def validate_key_and_scopes(self) -> TrustedApprover:
        try:
            public_bytes = base64.b64decode(self.public_key_b64, validate=True)
            Ed25519PublicKey.from_public_bytes(public_bytes)
        except Exception:
            raise ValueError("trusted key must be a canonical Ed25519 public key") from None
        if base64.b64encode(public_bytes).decode("ascii") != self.public_key_b64:
            raise ValueError("trusted public key encoding is non-canonical")
        if hashlib.sha256(public_bytes).hexdigest() != self.public_key_fingerprint:
            raise ValueError("trusted public key fingerprint mismatch")
        for field_name in (
            "allowed_purposes",
            "allowed_run_schema_versions",
            "allowed_space_ids",
        ):
            values = tuple(getattr(self, field_name))
            if not values or len(values) != len(set(values)):
                raise ValueError(f"{field_name} must be non-empty and unique")
            object.__setattr__(self, field_name, tuple(sorted(values)))
        return self

    @property
    def public_key(self) -> Ed25519PublicKey:
        return Ed25519PublicKey.from_public_bytes(
            base64.b64decode(self.public_key_b64, validate=True)
        )


class RootTrustPolicy(_FrozenModel):
    schema_version: Literal["insurancekb.run-admission-root-policy.v1"]
    approvers: tuple[TrustedApprover, ...]

    @model_validator(mode="after")
    def require_unique_authority_bindings(self) -> RootTrustPolicy:
        approvers = tuple(
            sorted(
                self.approvers,
                key=lambda item: (item.key_id, item.public_key_fingerprint),
            )
        )
        identities = {(item.key_id, item.public_key_fingerprint) for item in approvers}
        if not approvers or len(identities) != len(approvers):
            raise ValueError("root policy approvers must be non-empty and unique")
        object.__setattr__(self, "approvers", approvers)
        return self

    def resolve(self, envelope: ApprovalEnvelope) -> TrustedApprover:
        matches = tuple(
            item
            for item in self.approvers
            if item.key_id == envelope.key_id
            and item.public_key_fingerprint == envelope.public_key_fingerprint
        )
        if len(matches) != 1:
            raise AdmissionPolicyDenied("untrusted_approval_key")
        return matches[0]


def _read_root_protected_file(
    path: Path,
    *,
    root: Path,
    max_bytes: int,
    reason_code: str,
) -> bytes:
    """Read one file beneath a fixed root after fail-closed custody checks."""

    try:
        if not path.is_absolute() or not root.is_absolute():
            raise ValueError
        relative = path.relative_to(root)
        if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError
        resolved_root = root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        if resolved_path == resolved_root or not resolved_path.is_relative_to(resolved_root):
            raise ValueError
        directories = (root,) + tuple(
            root.joinpath(*relative.parts[:index]) for index in range(1, len(relative.parts))
        )
        for cursor in directories:
            info = cursor.stat(follow_symlinks=False)
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != _ROOT_OWNER_UID
                or info.st_mode & 0o022
                or cursor.is_symlink()
            ):
                raise ValueError
        info = path.stat(follow_symlinks=False)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != _ROOT_OWNER_UID
            or info.st_mode & 0o022
            or path.is_symlink()
        ):
            raise ValueError
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                or opened.st_uid != _ROOT_OWNER_UID
                or opened.st_mode & 0o022
                or not stat.S_ISREG(opened.st_mode)
            ):
                raise ValueError
            payload = os.read(descriptor, max_bytes + 1)
        finally:
            os.close(descriptor)
        if not payload or len(payload) > max_bytes:
            raise ValueError
        return payload
    except (OSError, RuntimeError, ValueError):
        raise AdmissionPolicyDenied(reason_code) from None


def load_root_trust_policy() -> RootTrustPolicy:
    """Load the single fixed deployment policy; callers cannot override its path."""

    try:
        payload = _read_root_protected_file(
            _ROOT_TRUST_POLICY_PATH,
            root=_ROOT_TRUST_POLICY_DIR,
            max_bytes=_MAX_POLICY_BYTES,
            reason_code="root_trust_policy_unavailable",
        )
        raw = json.loads(payload, object_pairs_hook=_reject_duplicate_keys)
        return RootTrustPolicy.model_validate(raw)
    except AdmissionPolicyDenied:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        raise AdmissionPolicyDenied("root_trust_policy_unavailable") from None


def verify_human_approval(
    policy: RootTrustPolicy,
    envelope: ApprovalEnvelope,
) -> TrustedApprover:
    """Verify exact policy scope and the domain-separated human signature."""

    approver = policy.resolve(envelope)
    if envelope.human_identity != approver.human_identity:
        raise AdmissionPolicyDenied("approver_identity_mismatch")
    if envelope.approver_role != approver.approver_role or (
        envelope.approver_role != _APPROVER_ROLE
    ):
        raise AdmissionPolicyDenied("approver_role_mismatch")
    if envelope.signature_domain != approver.signature_domain:
        raise AdmissionPolicyDenied("approval_domain_mismatch")
    payload = envelope.payload
    if payload.purpose not in approver.allowed_purposes:
        raise AdmissionPolicyDenied("approval_purpose_not_allowed")
    if payload.run_schema_version not in approver.allowed_run_schema_versions:
        raise AdmissionPolicyDenied("approval_schema_not_allowed")
    if payload.space_id not in approver.allowed_space_ids:
        raise AdmissionPolicyDenied("approval_space_not_allowed")
    try:
        signature = base64.b64decode(envelope.signature_b64, validate=True)
        approver.public_key.verify(signature, approval_signed_bytes(envelope))
    except InvalidSignature:
        raise AdmissionPolicyDenied("invalid_approval_signature") from None
    except (TypeError, ValueError):
        raise AdmissionPolicyDenied("invalid_approval_signature") from None
    return approver


__all__ = ["RootTrustPolicy", "TrustedApprover", "load_root_trust_policy"]
