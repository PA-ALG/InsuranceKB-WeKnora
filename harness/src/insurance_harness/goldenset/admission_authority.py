"""Offline approval authority and protected signing-material storage.

This module never enrolls trust and never executes a run.  It deliberately keeps
private keys and unsigned staging material outside the repository while allowing
the final, public approval envelope to be version controlled.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)
from pydantic import BaseModel, StrictStr, StringConstraints

from insurance_harness.goldenset.admission_infrastructure import (
    PRICING_EVIDENCE_DOMAIN,
    PROVIDER_CAP_DOMAIN,
    PROVISIONING_AUTHORIZATION_DOMAIN,
    PricingEvidenceApproval,
    PricingEvidenceApprovalPayload,
    ProviderCapApproval,
    ProviderCapApprovalPayload,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    authorization_signed_bytes,
    pricing_evidence_signed_bytes,
    provider_cap_signed_bytes,
)
from insurance_harness.goldenset.admission_models import (
    ApprovalDomain,
    ApprovalVerificationError,
    BudgetApprovalEnvelope,
    BudgetApprovalPayload,
    CanaryReviewApprovalEnvelope,
    CanaryReviewApprovalPayload,
    ProvenanceApprovalEnvelope,
    ProvenanceApprovalPayload,
    TrustedAuthority,
    TrustedKeyPolicy,
    VerifiableApprovalEnvelope,
    approval_signed_bytes,
    canonical_json_bytes,
    verify_approval_envelope,
)

type NonBlankStr = Annotated[StrictStr, StringConstraints(strip_whitespace=True, min_length=1)]
type OperationalApprovalDomain = Literal[
    "insurancekb.run-admission.provisioning.v1",
    "insurancekb.run-admission.pricing.v1",
    "insurancekb.run-admission.provider-cap.v1",
]
type OfflineApprovalDomain = ApprovalDomain | OperationalApprovalDomain
type OperationalApprovalEnvelope = (
    ProvisioningAuthorization | PricingEvidenceApproval | ProviderCapApproval
)
type OfflineApprovalEnvelope = VerifiableApprovalEnvelope | OperationalApprovalEnvelope

_MAX_PRIVATE_KEY_BYTES = 4096
_MAX_RENDERED_APPROVAL_BYTES = 1024 * 1024
_PRIVATE_FILE_MODE = 0o600


class AuthorityPathError(PermissionError):
    """A private key or staging path does not meet the offline safety contract."""


@dataclass(frozen=True, slots=True)
class PublicKeyDescriptor:
    """Public metadata returned by key generation; it contains no private bytes."""

    key_id: str
    public_key: str
    fingerprint: str
    private_device: int
    private_inode: int


class _RenderedApproval(BaseModel):
    model_config = {"frozen": True, "extra": "forbid"}

    version: Literal["insurancekb.run-admission.unsigned.v1"]
    domain: OfflineApprovalDomain
    key_id: NonBlankStr
    payload: dict[str, object]


def _repository_and_parent(
    path: Path,
    *,
    repo_root: Path,
) -> tuple[Path, Path]:
    if not path.is_absolute():
        raise AuthorityPathError("authority paths must be absolute")
    repository = repo_root.resolve(strict=True)
    lexical_parent = path.parent.absolute()
    if lexical_parent == repository or lexical_parent.is_relative_to(repository):
        raise AuthorityPathError("private and staging material must be outside repository")
    try:
        parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise AuthorityPathError("authority parent directory is unavailable") from exc
    if parent != lexical_parent:
        raise AuthorityPathError("authority path contains a symlink parent")
    if parent == repository or parent.is_relative_to(repository):
        raise AuthorityPathError("private and staging material must be outside repository")
    return repository, parent


def _open_parent(path: Path, *, require_private: bool) -> int:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise AuthorityPathError("platform lacks safe nofollow directory traversal")
    parts = path.parent.parts
    if not parts or parts[0] != os.sep or ".." in parts:
        raise AuthorityPathError("authority path is invalid")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    descriptor = os.open(os.sep, flags)
    try:
        for component in parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise AuthorityPathError("authority parent has unsafe owner or type")
        if require_private and stat.S_IMODE(metadata.st_mode) & 0o077:
            raise AuthorityPathError("authority parent must not be accessible by group or other")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _require_private_inode(metadata: os.stat_result, *, maximum: int) -> None:
    if not stat.S_ISREG(metadata.st_mode):
        raise AuthorityPathError("signing material is not a regular file")
    if metadata.st_uid != os.geteuid():
        raise AuthorityPathError("signing material has unsafe owner")
    if stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE:
        raise AuthorityPathError("signing material must use mode 0600")
    if metadata.st_nlink != 1:
        raise AuthorityPathError("signing material must have exactly one link")
    if metadata.st_size <= 0 or metadata.st_size > maximum:
        raise AuthorityPathError("signing material size is invalid")


def _create_private_file(path: Path, payload: bytes) -> os.stat_result:
    if not payload:
        raise ValueError("private material must not be empty")
    parent_fd = _open_parent(path, require_private=True)
    descriptor = -1
    created = False
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(
            path.name,
            flags,
            _PRIVATE_FILE_MODE,
            dir_fd=parent_fd,
        )
        created = True
        os.fchmod(descriptor, _PRIVATE_FILE_MODE)
        opened = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_inode(opened, named):
            raise AuthorityPathError("signing material changed while being created")
        if opened.st_uid != os.geteuid() or stat.S_IMODE(opened.st_mode) != 0o600:
            raise AuthorityPathError("signing material has unsafe owner or mode")
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        final = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_inode(final, named) or final.st_nlink != 1:
            raise AuthorityPathError("signing material changed while being written")
        os.fsync(parent_fd)
        return final
    except Exception:
        if created:
            try:
                os.unlink(path.name, dir_fd=parent_fd)
            except OSError:
                pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def _read_private_file(path: Path, *, maximum: int) -> bytes:
    parent_fd = _open_parent(path, require_private=True)
    descriptor = -1
    try:
        descriptor = os.open(
            path.name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        _require_private_inode(opened, maximum=maximum)
        named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_inode(opened, named):
            raise AuthorityPathError("signing material changed while being opened")
        chunks: list[bytes] = []
        consumed = 0
        while consumed <= maximum:
            chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - consumed))
            if not chunk:
                break
            chunks.append(chunk)
            consumed += len(chunk)
        if consumed > maximum:
            raise AuthorityPathError("signing material size exceeds limit")
        final = os.fstat(descriptor)
        named = os.stat(path.name, dir_fd=parent_fd, follow_symlinks=False)
        if not _same_inode(opened, final) or not _same_inode(final, named):
            raise AuthorityPathError("signing material changed while being read")
        return b"".join(chunks)
    except AuthorityPathError:
        raise
    except OSError as exc:
        raise AuthorityPathError("signing material could not be opened safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def read_bounded_public_file(path: Path, *, maximum: int) -> bytes:
    """Read a public file once through one stable, bounded descriptor."""

    if maximum < 0:
        raise ValueError("maximum must be non-negative")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_size > maximum:
            raise ValueError("public input size or type is invalid")
        chunks: list[bytes] = []
        consumed = 0
        while consumed <= maximum:
            chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - consumed))
            if not chunk:
                break
            chunks.append(chunk)
            consumed += len(chunk)
        if consumed > maximum:
            raise ValueError("public input size exceeds limit")
        final = os.fstat(descriptor)
        if not _same_inode(opened, final):
            raise ValueError("public input descriptor changed while being read")
        return b"".join(chunks)
    except OSError as exc:
        raise ValueError("public input could not be opened safely") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _unlink_named_inode(
    parent_fd: int,
    name: str,
    expected: os.stat_result,
) -> bool:
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    if not _same_inode(named, expected):
        return False
    os.unlink(name, dir_fd=parent_fd)
    return True


def _atomic_public_output(path: Path, payload: bytes) -> None:
    if not path.is_absolute() or not path.parent.exists():
        raise AuthorityPathError("public output requires an existing absolute parent")
    parent_fd = _open_parent(path, require_private=False)
    temporary = f".{path.name}.{secrets.token_hex(12)}.tmp"
    descriptor = -1
    created: os.stat_result | None = None
    linked = False
    completed = False
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_fd,
        )
        written = 0
        while written < len(payload):
            written += os.write(descriptor, payload[written:])
        os.fsync(descriptor)
        created = os.fstat(descriptor)
        os.close(descriptor)
        descriptor = -1
        os.link(
            temporary,
            path.name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
            follow_symlinks=False,
        )
        linked = True
        os.unlink(temporary, dir_fd=parent_fd)
        os.fsync(parent_fd)
        completed = True
    except FileExistsError:
        raise
    except OSError as exc:
        destination_removed = True
        if linked and created is not None:
            try:
                destination_removed = _unlink_named_inode(
                    parent_fd,
                    path.name,
                    created,
                )
            except OSError:
                destination_removed = False
        if not destination_removed:
            raise AuthorityPathError("public output rollback is ambiguous") from exc
        raise AuthorityPathError("public output could not be installed atomically") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not completed and created is not None:
            try:
                _unlink_named_inode(parent_fd, temporary, created)
            except OSError:
                pass
        os.close(parent_fd)


def generate_offline_key(
    *,
    private_path: Path,
    repo_root: Path,
) -> PublicKeyDescriptor:
    """Create a new Ed25519 key outside the repository without enrolling trust."""

    _repository_and_parent(private_path, repo_root=repo_root)
    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes_raw()
    encoded_private = base64.b64encode(private_bytes) + b"\n"
    private_metadata = _create_private_file(private_path, encoded_private)
    public_bytes = private_key.public_key().public_bytes_raw()
    fingerprint = hashlib.sha256(public_bytes).hexdigest()
    return PublicKeyDescriptor(
        key_id=f"ed25519:{fingerprint}",
        public_key=base64.b64encode(public_bytes).decode("ascii"),
        fingerprint=fingerprint,
        private_device=private_metadata.st_dev,
        private_inode=private_metadata.st_ino,
    )


def remove_generated_private_key(
    *,
    private_path: Path,
    descriptor: PublicKeyDescriptor,
) -> None:
    """Remove only the exact private-key inode created for ``descriptor``."""

    parent_fd = _open_parent(private_path, require_private=True)
    try:
        try:
            named = os.stat(
                private_path.name,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            return
        if (named.st_dev, named.st_ino) != (
            descriptor.private_device,
            descriptor.private_inode,
        ):
            return
        _unlink_named_inode(parent_fd, private_path.name, named)
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def write_public_key_descriptor(*, descriptor: PublicKeyDescriptor, output_path: Path) -> None:
    """Atomically install public key metadata without printing it."""

    _atomic_public_output(
        output_path,
        canonical_json_bytes(
            {
                "key_id": descriptor.key_id,
                "public_key": descriptor.public_key,
                "fingerprint": descriptor.fingerprint,
            }
        )
        + b"\n",
    )


def render_unsigned_approval(
    *,
    domain: OfflineApprovalDomain,
    key_id: str,
    payload: BaseModel,
    output_path: Path,
    repo_root: Path,
) -> None:
    """Install canonical unsigned staging bytes outside the repository."""

    _repository_and_parent(output_path, repo_root=repo_root)
    validated_payload = _validate_payload(domain, payload)
    rendered = _RenderedApproval(
        version="insurancekb.run-admission.unsigned.v1",
        domain=domain,
        key_id=key_id,
        payload=validated_payload.model_dump(mode="json"),
    )
    _create_private_file(output_path, canonical_json_bytes(rendered) + b"\n")


def _load_private_key(path: Path) -> Ed25519PrivateKey:
    encoded = _read_private_file(path, maximum=_MAX_PRIVATE_KEY_BYTES).strip()
    try:
        private_bytes = base64.b64decode(encoded, validate=True)
        if base64.b64encode(private_bytes) != encoded:
            raise ValueError("noncanonical private key")
        return Ed25519PrivateKey.from_private_bytes(private_bytes)
    except (binascii.Error, ValueError) as exc:
        raise AuthorityPathError("private key encoding is invalid") from exc


def _validate_payload(
    domain: OfflineApprovalDomain,
    payload: BaseModel | dict[str, object],
) -> BaseModel:
    raw = (
        payload.model_dump(mode="python", round_trip=True)
        if isinstance(payload, BaseModel)
        else payload
    )
    if domain == "budget":
        return BudgetApprovalPayload.model_validate(raw)
    if domain == "provenance":
        return ProvenanceApprovalPayload.model_validate(raw)
    if domain == "canary-review":
        return CanaryReviewApprovalPayload.model_validate(raw)
    if domain == PROVISIONING_AUTHORIZATION_DOMAIN:
        return ProvisioningAuthorizationPayload.model_validate(raw)
    if domain == PRICING_EVIDENCE_DOMAIN:
        return PricingEvidenceApprovalPayload.model_validate(raw)
    if domain == PROVIDER_CAP_DOMAIN:
        return ProviderCapApprovalPayload.model_validate(raw)
    raise ValueError("approval domain is unsupported")


def _signed_bytes(domain: OfflineApprovalDomain, payload: BaseModel) -> bytes:
    if domain in {"budget", "provenance", "canary-review"}:
        return approval_signed_bytes(domain, payload)
    if domain == PROVISIONING_AUTHORIZATION_DOMAIN:
        if not isinstance(payload, ProvisioningAuthorizationPayload):
            raise TypeError("provisioning domain requires provisioning payload")
        return authorization_signed_bytes(domain, payload)
    if domain == PRICING_EVIDENCE_DOMAIN:
        if not isinstance(payload, PricingEvidenceApprovalPayload):
            raise TypeError("pricing domain requires pricing payload")
        return pricing_evidence_signed_bytes(payload)
    if domain == PROVIDER_CAP_DOMAIN:
        if not isinstance(payload, ProviderCapApprovalPayload):
            raise TypeError("provider-cap domain requires provider-cap payload")
        return provider_cap_signed_bytes(payload)
    raise ValueError("approval domain is unsupported")


def _build_envelope(
    rendered: _RenderedApproval,
    signature: str,
) -> OfflineApprovalEnvelope:
    payload = _validate_payload(rendered.domain, rendered.payload)
    values = {
        "domain": rendered.domain,
        "key_id": rendered.key_id,
        "payload": payload,
        "signature": signature,
    }
    if rendered.domain == "budget":
        return BudgetApprovalEnvelope.model_validate(values)
    if rendered.domain == "provenance":
        return ProvenanceApprovalEnvelope.model_validate(values)
    if rendered.domain == "canary-review":
        return CanaryReviewApprovalEnvelope.model_validate(values)
    if rendered.domain == PROVISIONING_AUTHORIZATION_DOMAIN:
        return ProvisioningAuthorization.model_validate(values)
    if rendered.domain == PRICING_EVIDENCE_DOMAIN:
        return PricingEvidenceApproval.model_validate(values)
    if rendered.domain == PROVIDER_CAP_DOMAIN:
        return ProviderCapApproval.model_validate(values)
    raise ValueError("approval domain is unsupported")


def sign_rendered_approval(
    *,
    rendered_path: Path,
    private_key_path: Path,
    output_path: Path,
    repo_root: Path,
) -> OfflineApprovalEnvelope:
    """Sign existing canonical staging bytes and atomically install a public envelope."""

    _repository_and_parent(rendered_path, repo_root=repo_root)
    _repository_and_parent(private_key_path, repo_root=repo_root)
    rendered_bytes = _read_private_file(
        rendered_path,
        maximum=_MAX_RENDERED_APPROVAL_BYTES,
    )
    try:
        raw = json.loads(rendered_bytes)
        rendered = _RenderedApproval.model_validate(raw)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise AuthorityPathError("rendered approval is invalid") from exc
    if canonical_json_bytes(rendered) + b"\n" != rendered_bytes:
        raise AuthorityPathError("rendered approval is not canonical")
    private_key = _load_private_key(private_key_path)
    public_fingerprint = hashlib.sha256(private_key.public_key().public_bytes_raw()).hexdigest()
    if rendered.key_id != f"ed25519:{public_fingerprint}":
        raise AuthorityPathError("rendered approval key id does not match private key")
    validated_payload = _validate_payload(rendered.domain, rendered.payload)
    signature = base64.b64encode(
        private_key.sign(_signed_bytes(rendered.domain, validated_payload))
    ).decode("ascii")
    envelope = _build_envelope(rendered, signature)
    _atomic_public_output(output_path, canonical_json_bytes(envelope) + b"\n")
    return envelope


def load_public_envelope(path: Path) -> OfflineApprovalEnvelope:
    """Load a bounded public envelope for offline verification."""

    try:
        payload = read_bounded_public_file(
            path,
            maximum=_MAX_RENDERED_APPROVAL_BYTES,
        )
        if not payload:
            raise ValueError("public approval envelope size or type is invalid")
        raw = json.loads(payload)
        domain = raw.get("domain") if isinstance(raw, dict) else None
        if domain == "budget":
            return BudgetApprovalEnvelope.model_validate(raw)
        if domain == "provenance":
            return ProvenanceApprovalEnvelope.model_validate(raw)
        if domain == "canary-review":
            return CanaryReviewApprovalEnvelope.model_validate(raw)
        if domain == PROVISIONING_AUTHORIZATION_DOMAIN:
            return ProvisioningAuthorization.model_validate(raw)
        if domain == PRICING_EVIDENCE_DOMAIN:
            return PricingEvidenceApproval.model_validate(raw)
        if domain == PROVIDER_CAP_DOMAIN:
            return ProviderCapApproval.model_validate(raw)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError("public approval envelope is invalid") from exc
    raise ValueError("public approval envelope domain is unsupported")


def verify_offline_envelope(
    *,
    envelope_path: Path,
    trusted_public_keys: Mapping[str, TrustedAuthority],
    allowed_roles_by_domain: Mapping[OfflineApprovalDomain, frozenset[str]],
    now: datetime,
) -> None:
    """Verify a public envelope against explicit offline policy inputs."""

    envelope = load_public_envelope(envelope_path)
    allowed_roles = allowed_roles_by_domain.get(envelope.domain, frozenset())
    if isinstance(
        envelope,
        (
            BudgetApprovalEnvelope,
            ProvenanceApprovalEnvelope,
            CanaryReviewApprovalEnvelope,
        ),
    ):
        legacy_payload = envelope.payload
        verify_approval_envelope(
            envelope,
            expected_domain=envelope.domain,
            expected_plan_payload_hash=legacy_payload.plan_payload_hash,
            expected_run_identity=legacy_payload.run_identity,
            expected_purpose=legacy_payload.purpose,
            expected_scope=legacy_payload.scope,
            trusted_public_keys=trusted_public_keys,
            allowed_roles=allowed_roles,
            now=now,
        )
        return

    operational_payload = envelope.payload
    if operational_payload.approver_role not in allowed_roles:
        raise ApprovalVerificationError(
            "approver role is not authorized for this operational domain"
        )
    if now.tzinfo is None or now.utcoffset() is None:
        raise ApprovalVerificationError("verification time must include a timezone")
    if now < operational_payload.issued_at or now >= operational_payload.expires_at:
        raise ApprovalVerificationError("operational approval is outside its validity window")
    authority = trusted_public_keys.get(envelope.key_id)
    if not isinstance(authority, TrustedKeyPolicy):
        raise ApprovalVerificationError("operational approval requires an exact trusted key policy")
    if (
        authority.key_id != envelope.key_id
        or authority.approver_identity != operational_payload.approver_identity
        or envelope.domain not in authority.domains
        or operational_payload.scope not in authority.scopes
        or operational_payload.approver_role not in authority.roles
    ):
        raise ApprovalVerificationError("operational approval violates trusted key policy")
    try:
        signature = base64.b64decode(envelope.signature, validate=True)
        if base64.b64encode(signature).decode("ascii") != envelope.signature:
            raise ApprovalVerificationError(
                "operational approval signature encoding is noncanonical"
            )
        authority.public_key.verify(
            signature,
            _signed_bytes(envelope.domain, operational_payload),
        )
    except ApprovalVerificationError:
        raise
    except (binascii.Error, InvalidSignature, ValueError) as exc:
        raise ApprovalVerificationError("operational approval signature is invalid") from exc


__all__ = [
    "AuthorityPathError",
    "OfflineApprovalDomain",
    "PublicKeyDescriptor",
    "generate_offline_key",
    "read_bounded_public_file",
    "remove_generated_private_key",
    "render_unsigned_approval",
    "sign_rendered_approval",
    "verify_offline_envelope",
    "write_public_key_descriptor",
]
