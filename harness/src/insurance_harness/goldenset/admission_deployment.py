"""Crash-safe, zero-inference Bailian deployment creation control.

The controller owns the provider request shape, persists a send-intent before the
only permitted POST, and reconciles every ambiguous outcome.  Raw provider bytes,
credentials, and caller-selected URLs never enter its durable artifacts.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Protocol, Self, cast
from urllib.parse import quote

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from insurance_harness.goldenset.admission_budget import (
    BudgetLedger,
    BudgetLedgerError,
    InfrastructureCleanupBinding,
    InfrastructureCreatePermit,
    InfrastructureReserveSnapshot,
)
from insurance_harness.goldenset.admission_infrastructure import (
    AuthorizationVerificationError,
    DeploymentCleanupAuthorization,
    DeploymentReceipt,
    DeploymentReceiptContent,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    VerifiedReconciledDeploymentReceipt,
    deployment_receipt_content_digest,
    infrastructure_authorization_digest,
    verify_cleanup_authorization,
    verify_provisioning_authorization,
    verify_reconciled_deployment_receipt,
)
from insurance_harness.goldenset.admission_models import (
    TrustedAuthority,
    canonical_json_bytes,
)

BAILIAN_DEPLOYMENT_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/deployments"
_PRODUCTION_RUN_ROOT = Path("/var/lib/insurancekb/run-admission/deployments")
_STRONG_BASE = "qwen3.7-plus-2026-05-26"
_WEAK_BASE = "deepseek-v4-flash"
_ALLOWED_BASES = frozenset({_STRONG_BASE, _WEAK_BASE})
_REQUEST_PLAN: Literal["ptu_v2"] = "ptu_v2"
_RECEIPT_PLAN: Literal["ptu"] = "ptu"
_INPUT_TPM: Literal[10_000] = 10_000
_OUTPUT_TPM: Literal[1_000] = 1_000
_REGION: Literal["cn-beijing"] = "cn-beijing"
_PAYMENT_TYPE: Literal["postpaid"] = "postpaid"
_MAX_CONTROL_RESPONSE_BYTES = 256 * 1024
_MAX_ARTIFACT_BYTES = 256 * 1024
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_MARKER_DOMAIN = b"insurancekb.run-admission.deployment-marker.v1\0"
_SUFFIX_DOMAIN = b"insurancekb.run-admission.deployment-suffix.v1\0"
_WORKSPACE_EVIDENCE_DOMAIN = b"insurancekb.run-admission.workspace-evidence.v1\0"
_REMOTE_MANIFEST_DOMAIN = b"insurancekb.run-admission.remote-manifest.v1\0"
_CLEANUP_RECEIPT_DOMAIN = b"insurancekb.run-admission.cleanup-receipt.v1\0"
_IDEMPOTENCY_DOMAIN = b"insurancekb.run-admission.deployment-idempotency.v1\0"
_SAFE_PROVIDER_ID = re.compile(r"^[A-Za-z0-9._:@+-]{1,512}$")

type NonBlankStr = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
]
type Sha256Digest = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type JournalState = Literal[
    "authorized", "reserved", "prepared", "reconciled", "created", "receipted"
]


class DeploymentControlBlocked(RuntimeError):
    """A stable fail-closed provider-control decision."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DeploymentProviderConflict(RuntimeError):
    """The provider returned a deployment-name/idempotency conflict."""


class DeploymentTransportError(RuntimeError):
    """A bounded control-plane request did not produce trusted bytes."""


class DeploymentNotFound(RuntimeError):
    """A deployment detail probe authoritatively returned HTTP 404."""


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def copy(
        self,
        *,
        include: object = None,
        exclude: object = None,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        raise TypeError("copy() is disabled; use validated model_copy()")

    def model_copy(
        self,
        *,
        update: Mapping[str, object] | None = None,
        deep: bool = False,
    ) -> Self:
        if update is None:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class BailianDeploymentRequest(_ImmutableModel):
    """The complete code-owned provider mutation payload."""

    base_model: Literal["qwen3.7-plus-2026-05-26", "deepseek-v4-flash"]
    workspace_ref: NonBlankStr
    region: Literal["cn-beijing"]
    plan: Literal["ptu_v2"]
    input_tpm_quota: Literal[10_000]
    output_tpm_quota: Literal[1_000]
    payment_type: Literal["postpaid"]
    operation_marker: Annotated[StrictStr, StringConstraints(pattern=r"^ikb031-[0-9a-f]{24}$")]
    deployment_suffix: Annotated[StrictStr, StringConstraints(pattern=r"^031-[0-9a-f]{16}$")]

    @field_validator("workspace_ref")
    @classmethod
    def require_safe_workspace_ref(cls, value: str) -> str:
        _require_safe_provider_id(value, "workspace_ref")
        return value


class ProviderDeploymentManifest(_ImmutableModel):
    """Allowlisted remote facts used for ownership and receipt reconciliation."""

    deployed_model: NonBlankStr
    base_model: Literal["qwen3.7-plus-2026-05-26", "deepseek-v4-flash"]
    plan: Literal["ptu"]
    input_tpm: Literal[10_000]
    output_tpm: Literal[1_000]
    status: Literal["RUNNING"]
    gmt_create: datetime
    gmt_modified: datetime
    workspace_ref: NonBlankStr
    operation_marker: Annotated[StrictStr, StringConstraints(pattern=r"^ikb031-[0-9a-f]{24}$")]
    deployment_suffix: Annotated[StrictStr, StringConstraints(pattern=r"^031-[0-9a-f]{16}$")]

    @field_validator("deployed_model", "workspace_ref")
    @classmethod
    def require_safe_provider_identifiers(cls, value: str) -> str:
        _require_safe_provider_id(value, "provider identifier")
        return value

    @field_validator("gmt_create", "gmt_modified")
    @classmethod
    def require_gmt(cls, value: datetime) -> datetime:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None:
            raise ValueError("provider GMT timestamp must include a timezone")
        if offset.total_seconds() != 0:
            raise ValueError("provider timestamp must be normalized to GMT")
        return value

    @model_validator(mode="after")
    def require_ordered_gmt(self) -> ProviderDeploymentManifest:
        if self.gmt_modified < self.gmt_create:
            raise ValueError("provider gmt_modified precedes gmt_create")
        return self


class _ProviderList(_ImmutableModel):
    items: tuple[ProviderDeploymentManifest, ...]


class DeploymentOperationJournal(_ImmutableModel):
    version: Literal[1] = 1
    run_identity: NonBlankStr
    operation_id: NonBlankStr
    infrastructure_reserve_id: NonBlankStr
    authorization_digest: Sha256Digest
    operation_marker: Annotated[StrictStr, StringConstraints(pattern=r"^ikb031-[0-9a-f]{24}$")]
    deployment_suffix: Annotated[StrictStr, StringConstraints(pattern=r"^031-[0-9a-f]{16}$")]
    state: JournalState
    history: tuple[JournalState, ...]
    send_started: StrictBool = False
    receipt_digest: Sha256Digest | None = None

    @model_validator(mode="after")
    def require_valid_history(self) -> DeploymentOperationJournal:
        allowed_histories: dict[JournalState, frozenset[tuple[JournalState, ...]]] = {
            "authorized": frozenset({("authorized",)}),
            "reserved": frozenset({("authorized", "reserved")}),
            "prepared": frozenset({("authorized", "reserved", "prepared")}),
            "created": frozenset(
                {("authorized", "reserved", "prepared", "created")}
            ),
            "reconciled": frozenset(
                {("authorized", "reserved", "prepared", "reconciled")}
            ),
            "receipted": frozenset(
                {
                    (
                        "authorized",
                        "reserved",
                        "prepared",
                        "created",
                        "receipted",
                    ),
                    (
                        "authorized",
                        "reserved",
                        "prepared",
                        "reconciled",
                        "receipted",
                    ),
                }
            ),
        }
        if self.history not in allowed_histories[self.state]:
            raise ValueError("journal state/history is not a legal transition")
        if self.state in {"created", "reconciled", "receipted"} and not self.send_started:
            raise ValueError("owned or terminal journal requires send_started")
        if self.state in {"authorized", "reserved"} and self.send_started:
            raise ValueError("send_started requires a durable prepared state")
        if self.state == "receipted" and self.receipt_digest is None:
            raise ValueError("receipted journal requires receipt digest")
        if self.state != "receipted" and self.receipt_digest is not None:
            raise ValueError("nonterminal journal cannot bind a receipt")
        return self


class DeploymentReceiptArtifact(_ImmutableModel):
    receipt: DeploymentReceipt
    remote_manifest: ProviderDeploymentManifest
    remote_manifest_digest: Sha256Digest

    @model_validator(mode="after")
    def require_manifest_digest(self) -> DeploymentReceiptArtifact:
        if self.remote_manifest_digest != _remote_manifest_digest(self.remote_manifest):
            raise ValueError("remote manifest digest mismatch")
        if self.receipt.content.remote_manifest_digest != self.remote_manifest_digest:
            raise ValueError("receipt does not bind remote manifest digest")
        return self


class DeploymentControlResult(_ImmutableModel):
    receipt: DeploymentReceipt
    receipt_capability: VerifiedReconciledDeploymentReceipt
    remote_manifest_digest: Sha256Digest
    receipt_path: Path
    journal_path: Path


class CleanupOperationJournal(_ImmutableModel):
    version: Literal[1] = 1
    run_identity: NonBlankStr
    operation_id: NonBlankStr
    reserve_id: NonBlankStr
    receipt_digest: Sha256Digest
    deployed_model: NonBlankStr
    cleanup_authorization_digest: Sha256Digest
    expected_remote_manifest_digest: Sha256Digest
    delete_started: StrictBool
    terminal_receipt_digest: Sha256Digest | None = None


class CleanupReceipt(_ImmutableModel):
    version: Literal[1] = 1
    run_identity: NonBlankStr
    operation_id: NonBlankStr
    reserve_id: NonBlankStr
    receipt_digest: Sha256Digest
    deployed_model: NonBlankStr
    cleanup_authorization_digest: Sha256Digest
    remote_manifest_digest: Sha256Digest
    terminal_state: Literal["absent_404", "already_absent_404"]
    observed_at: datetime
    billing_stop_verified: Literal[True]

    @field_validator("observed_at")
    @classmethod
    def require_aware_observation(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cleanup observation must include a timezone")
        return value


class CleanupControlResult(_ImmutableModel):
    receipt: CleanupReceipt
    receipt_path: Path
    journal_path: Path


class InfrastructureReserveReader(Protocol):
    def infrastructure_reserve(self, reserve_id: str) -> InfrastructureReserveSnapshot: ...

    def infrastructure_cleanup_binding(
        self, reserve_id: str
    ) -> InfrastructureCleanupBinding: ...


class DeploymentControlTransport(Protocol):
    endpoint: str

    def list_deployments(self, *, marker: str, suffix: str) -> bytes: ...

    def create_deployment(self, *, request_body: bytes, idempotency_key: str) -> bytes: ...

    def deployment_detail(self, *, deployed_model: str) -> bytes: ...


class CleanupControlTransport(Protocol):
    endpoint: str

    def deployment_detail(self, *, deployed_model: str) -> bytes: ...

    def delete_deployment(self, *, deployed_model: str) -> bytes: ...


def _canonical_operation_bytes(run_identity: str, operation_id: str) -> bytes:
    return canonical_json_bytes(
        {"operation_id": operation_id, "run_identity": run_identity}
    )


def deterministic_operation_marker(run_identity: str, operation_id: str) -> str:
    digest = hashlib.sha256(
        _MARKER_DOMAIN + _canonical_operation_bytes(run_identity, operation_id)
    ).hexdigest()
    return f"ikb031-{digest[:24]}"


def deterministic_deployment_suffix(run_identity: str, operation_id: str) -> str:
    digest = hashlib.sha256(
        _SUFFIX_DOMAIN + _canonical_operation_bytes(run_identity, operation_id)
    ).hexdigest()
    return f"031-{digest[:16]}"


def _idempotency_key(run_identity: str, operation_id: str) -> str:
    return hashlib.sha256(
        _IDEMPOTENCY_DOMAIN + _canonical_operation_bytes(run_identity, operation_id)
    ).hexdigest()


def _workspace_evidence_digest(payload: ProvisioningAuthorizationPayload) -> str:
    return hashlib.sha256(
        _WORKSPACE_EVIDENCE_DOMAIN
        + canonical_json_bytes(
            {
                "credential_ref": payload.credential_ref,
                "project_ref": payload.project_ref,
                "workspace_ref": payload.workspace_ref,
            }
        )
    ).hexdigest()


def _remote_manifest_digest(manifest: ProviderDeploymentManifest) -> str:
    return hashlib.sha256(
        _REMOTE_MANIFEST_DOMAIN + canonical_json_bytes(manifest)
    ).hexdigest()


def provider_manifest_digest(manifest: ProviderDeploymentManifest) -> str:
    """Public canonical manifest digest used by cleanup authorization."""

    validated = ProviderDeploymentManifest.model_validate(
        manifest.model_dump(mode="python", round_trip=True)
    )
    return _remote_manifest_digest(validated)


def _require_safe_provider_id(value: str, label: str) -> None:
    if not _SAFE_PROVIDER_ID.fullmatch(value) or Path(value).is_absolute():
        raise ValueError(f"{label} is not a safe provider identifier")


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _parse_json_bytes(raw: bytes, *, maximum: int) -> object:
    if not isinstance(raw, bytes) or len(raw) == 0 or len(raw) > maximum:
        raise DeploymentControlBlocked(
            "provider_response_invalid", "provider response is empty or oversized"
        )
    try:
        text = raw.decode("utf-8", errors="strict")
        return json.loads(text, object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise DeploymentControlBlocked(
            "provider_response_invalid", "provider response is malformed"
        ) from exc


def _parse_manifest(raw: bytes) -> ProviderDeploymentManifest:
    try:
        value = _parse_json_bytes(raw, maximum=_MAX_CONTROL_RESPONSE_BYTES)
        if not isinstance(value, dict):
            raise TypeError("manifest must be an object")
        allowlisted = {
            key: value[key]
            for key in (
                "deployed_model",
                "base_model",
                "plan",
                "input_tpm",
                "output_tpm",
                "status",
                "gmt_create",
                "gmt_modified",
                "workspace_ref",
                "operation_marker",
                "deployment_suffix",
            )
        }
        return ProviderDeploymentManifest.model_validate(allowlisted)
    except DeploymentControlBlocked:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise DeploymentControlBlocked(
            "provider_response_invalid", "provider response manifest is invalid"
        ) from exc


def _parse_list(raw: bytes) -> tuple[ProviderDeploymentManifest, ...]:
    try:
        value = _parse_json_bytes(raw, maximum=_MAX_CONTROL_RESPONSE_BYTES)
        if not isinstance(value, dict) or set(value) != {"items"}:
            raise TypeError("list response shape is invalid")
        parsed = _ProviderList.model_validate(value)
        return parsed.items
    except DeploymentControlBlocked:
        raise
    except (TypeError, ValueError) as exc:
        raise DeploymentControlBlocked(
            "provider_response_invalid", "provider list response is invalid"
        ) from exc


class BailianDeploymentHTTPTransport:
    """Fixed-route control-plane HTTP transport; it exposes no inference method."""

    endpoint = BAILIAN_DEPLOYMENT_ENDPOINT

    def __init__(self, *, api_key: str) -> None:
        self._initialize(api_key=api_key, transport=None)

    @classmethod
    def _for_testing(
        cls,
        *,
        api_key: str,
        transport: httpx.BaseTransport,
    ) -> BailianDeploymentHTTPTransport:
        instance = cls.__new__(cls)
        instance._initialize(api_key=api_key, transport=transport)
        return instance

    def _initialize(
        self,
        *,
        api_key: str,
        transport: httpx.BaseTransport | None,
    ) -> None:
        if not isinstance(api_key, str) or not api_key or len(api_key) > 16 * 1024:
            raise ValueError("Bailian API key is missing or oversized")
        client_options: dict[str, Any] = {
            "base_url": BAILIAN_DEPLOYMENT_ENDPOINT,
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Content-Type": "application/json",
            },
            "timeout": httpx.Timeout(15.0),
            "verify": True,
            "follow_redirects": False,
            "trust_env": False,
        }
        if transport is not None:
            client_options["transport"] = transport
        self._client = httpx.Client(**client_options)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BailianDeploymentHTTPTransport:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request_bounded(
        self,
        method: Literal["GET", "POST", "DELETE"],
        url: str,
        *,
        accepted_statuses: frozenset[int],
        params: Mapping[str, str] | None = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        conflict_is_distinct: bool = False,
        not_found_is_distinct: bool = False,
    ) -> bytes:
        try:
            with self._client.stream(
                method,
                url,
                params=params,
                content=content,
                headers=headers,
            ) as response:
                if conflict_is_distinct and response.status_code == 409:
                    raise DeploymentProviderConflict("provider deployment conflict")
                if not_found_is_distinct and response.status_code == 404:
                    raise DeploymentNotFound("provider deployment is absent")
                if response.status_code not in accepted_statuses:
                    raise DeploymentTransportError("provider control request failed")
                encoding = response.headers.get("content-encoding", "identity").lower()
                if encoding not in {"", "identity"}:
                    raise DeploymentTransportError(
                        "compressed provider response is forbidden"
                    )
                body = bytearray()
                for chunk in response.iter_raw():
                    body.extend(chunk)
                    if len(body) > _MAX_CONTROL_RESPONSE_BYTES:
                        raise DeploymentTransportError(
                            "provider response exceeds size limit"
                        )
                return bytes(body)
        except (DeploymentNotFound, DeploymentProviderConflict, DeploymentTransportError):
            raise
        except httpx.RequestError as exc:
            raise DeploymentTransportError("provider control request failed") from exc

    def list_deployments(self, *, marker: str, suffix: str) -> bytes:
        return self._request_bounded(
            "GET",
            BAILIAN_DEPLOYMENT_ENDPOINT,
            accepted_statuses=frozenset({200}),
            params={"operation_marker": marker, "deployment_suffix": suffix},
        )

    def create_deployment(self, *, request_body: bytes, idempotency_key: str) -> bytes:
        return self._request_bounded(
            "POST",
            BAILIAN_DEPLOYMENT_ENDPOINT,
            accepted_statuses=frozenset({200, 201}),
            content=request_body,
            headers={"Idempotency-Key": idempotency_key},
            conflict_is_distinct=True,
        )

    def deployment_detail(self, *, deployed_model: str) -> bytes:
        _require_safe_provider_id(deployed_model, "deployed_model")
        return self._request_bounded(
            "GET",
            f"{BAILIAN_DEPLOYMENT_ENDPOINT}/{quote(deployed_model, safe='')}",
            accepted_statuses=frozenset({200}),
            not_found_is_distinct=True,
        )

    def delete_deployment(self, *, deployed_model: str) -> bytes:
        _require_safe_provider_id(deployed_model, "deployed_model")
        return self._request_bounded(
            "DELETE",
            f"{BAILIAN_DEPLOYMENT_ENDPOINT}/{quote(deployed_model, safe='')}",
            accepted_statuses=frozenset({200, 202, 204}),
            not_found_is_distinct=True,
        )


class _OperationStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._root_fd = self._open_root(self.root)

    def close(self) -> None:
        if self._root_fd >= 0:
            os.close(self._root_fd)
            self._root_fd = -1

    @staticmethod
    def _open_root(root: Path) -> int:
        absolute = Path(os.path.abspath(root))
        try:
            descriptor = os.open(
                absolute,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            metadata = os.fstat(descriptor)
        except OSError as exc:
            raise DeploymentControlBlocked(
                "operation_store_unsafe", "deployment operation root is unavailable"
            ) from exc
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != _PRIVATE_DIRECTORY_MODE
        ):
            os.close(descriptor)
            raise DeploymentControlBlocked(
                "operation_store_unsafe", "deployment operation root is unsafe"
            )
        return descriptor

    @staticmethod
    def _name(domain: bytes, *values: str, suffix: str) -> str:
        digest = hashlib.sha256(
            domain + canonical_json_bytes(tuple(values))
        ).hexdigest()
        return f"{digest}{suffix}"

    def journal_name(self, run_identity: str, operation_id: str) -> str:
        return self._name(
            b"insurancekb.run-admission.deployment-journal-name.v1\0",
            run_identity,
            operation_id,
            suffix=".journal.json",
        )

    def lock_name(self, run_identity: str) -> str:
        return self._name(
            b"insurancekb.run-admission.deployment-run-lock.v1\0",
            run_identity,
            suffix=".run.lock",
        )

    def cleanup_journal_name(self, run_identity: str, operation_id: str) -> str:
        return self._name(
            b"insurancekb.run-admission.cleanup-journal-name.v1\0",
            run_identity,
            operation_id,
            suffix=".cleanup-journal.json",
        )

    @contextmanager
    def run_lock(self, run_identity: str) -> Any:
        name = self.lock_name(run_identity)
        try:
            descriptor = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                _PRIVATE_FILE_MODE,
                dir_fd=self._root_fd,
            )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
                or metadata.st_nlink != 1
            ):
                raise OSError("unsafe run lock")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        except OSError as exc:
            if "descriptor" in locals():
                os.close(descriptor)
            raise DeploymentControlBlocked(
                "operation_lock_unsafe", "deployment run lock is unsafe"
            ) from exc
        try:
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def path(self, name: str) -> Path:
        return self.root / name

    def read(self, name: str) -> bytes | None:
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=self._root_fd,
            )
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe", "deployment artifact cannot be opened"
            ) from exc
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
                or metadata.st_nlink != 1
                or metadata.st_size > _MAX_ARTIFACT_BYTES
            ):
                raise DeploymentControlBlocked(
                    "operation_artifact_unsafe", "deployment artifact is unsafe"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = os.read(descriptor, min(64 * 1024, _MAX_ARTIFACT_BYTES + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                if total > _MAX_ARTIFACT_BYTES:
                    raise DeploymentControlBlocked(
                        "operation_artifact_unsafe", "deployment artifact is oversized"
                    )
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def atomic_write(self, name: str, content: bytes) -> None:
        if not content or len(content) > _MAX_ARTIFACT_BYTES:
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe", "deployment artifact size is invalid"
            )
        temporary = f".{name}.{secrets.token_hex(12)}.tmp"
        descriptor = -1
        staged = True
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                _PRIVATE_FILE_MODE,
                dir_fd=self._root_fd,
            )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != _PRIVATE_FILE_MODE
                or metadata.st_nlink != 1
            ):
                raise OSError("unsafe staging file")
            view = memoryview(content)
            written = 0
            while written < len(view):
                count = os.write(descriptor, view[written:])
                if count <= 0:
                    raise OSError("short artifact write")
                written += count
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(
                temporary,
                name,
                src_dir_fd=self._root_fd,
                dst_dir_fd=self._root_fd,
            )
            staged = False
            os.fsync(self._root_fd)
        except OSError as exc:
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe", "deployment artifact write failed"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if staged:
                try:
                    os.unlink(temporary, dir_fd=self._root_fd)
                except OSError:
                    pass
        if self.read(name) != content:
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe", "deployment artifact readback mismatch"
            )


class DeploymentController:
    """Single-operation orchestrator with durable at-most-once POST semantics."""

    def __init__(
        self,
        *,
        reserve_reader: BudgetLedger,
        transport: BailianDeploymentHTTPTransport,
    ) -> None:
        self._initialize(
            run_root=_PRODUCTION_RUN_ROOT,
            reserve_reader=reserve_reader,
            transport=transport,
            clock=lambda: datetime.now(UTC),
        )

    @classmethod
    def _for_testing(
        cls,
        *,
        run_root: Path,
        reserve_reader: InfrastructureReserveReader,
        transport: DeploymentControlTransport,
        clock: Callable[[], datetime],
    ) -> DeploymentController:
        instance = cls.__new__(cls)
        instance._initialize(
            run_root=run_root,
            reserve_reader=reserve_reader,
            transport=transport,
            clock=clock,
        )
        return instance

    def _initialize(
        self,
        *,
        run_root: Path,
        reserve_reader: InfrastructureReserveReader,
        transport: DeploymentControlTransport,
        clock: Callable[[], datetime],
    ) -> None:
        self._reserve_reader = reserve_reader
        self._transport = transport
        self._clock = clock
        self._store = _OperationStore(run_root)

    def __del__(self) -> None:
        store = getattr(self, "_store", None)
        if isinstance(store, _OperationStore):
            store.close()

    def provision(
        self,
        *,
        authorization: ProvisioningAuthorization,
        permit: InfrastructureCreatePermit,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> DeploymentControlResult:
        payload = self._verify_gate(
            authorization=authorization,
            permit=permit,
            trusted_authorities=trusted_authorities,
            now=self._clock(),
        )
        marker = deterministic_operation_marker(payload.run_identity, payload.operation_id)
        suffix = deterministic_deployment_suffix(payload.run_identity, payload.operation_id)
        request = BailianDeploymentRequest(
            base_model=cast(Any, payload.base_model),
            workspace_ref=payload.workspace_ref,
            region=_REGION,
            plan=_REQUEST_PLAN,
            input_tpm_quota=_INPUT_TPM,
            output_tpm_quota=_OUTPUT_TPM,
            payment_type=_PAYMENT_TYPE,
            operation_marker=marker,
            deployment_suffix=suffix,
        )
        authorization_digest = infrastructure_authorization_digest(authorization)
        journal_name = self._store.journal_name(payload.run_identity, payload.operation_id)
        with self._store.run_lock(payload.run_identity):
            # Re-read all durable evidence while holding the run lock.
            self._require_current_reserve(permit)
            journal = self._load_or_create_journal(
                journal_name=journal_name,
                payload=payload,
                authorization_digest=authorization_digest,
                marker=marker,
                suffix=suffix,
            )
            journal = self._advance_to_prepared(journal_name, journal)
            if journal.state == "receipted":
                return self._restore_receipt(journal_name, journal, payload, request)

            manifests = self._listed_manifests(marker=marker, suffix=suffix)
            match = self._select_owned_match(manifests, request=request)
            if match is not None:
                if not journal.send_started:
                    raise DeploymentControlBlocked(
                        "preexisting_collision",
                        "remote deployment predates this operation send intent",
                    )
                journal = self._record_ownership(
                    journal_name, journal, transition="reconciled"
                )
                return self._finish_receipt(journal_name, journal, payload, request, match)

            if journal.send_started:
                raise DeploymentControlBlocked(
                    "provider_outcome_uncertain",
                    "send already started and no deployment can yet be reconciled",
                )

            # A queued operator must not use the caller's earlier wall clock.  Recheck
            # signature freshness, permit freshness, and the ledger row immediately
            # before durably recording the only permitted send attempt.
            self._verify_gate(
                authorization=authorization,
                permit=permit,
                trusted_authorities=trusted_authorities,
                now=self._clock(),
            )
            journal = journal.model_copy(update={"send_started": True})
            self._write_journal(journal_name, journal)  # fsync immediately before POST
            try:
                created = _parse_manifest(
                    self._transport.create_deployment(
                        request_body=canonical_json_bytes(request),
                        idempotency_key=_idempotency_key(
                            payload.run_identity, payload.operation_id
                        ),
                    )
                )
                self._require_exact_manifest(created, request)
                detail = _parse_manifest(
                    self._transport.deployment_detail(
                        deployed_model=created.deployed_model
                    )
                )
                if canonical_json_bytes(detail) != canonical_json_bytes(created):
                    raise DeploymentControlBlocked(
                        "remote_manifest_mismatch",
                        "provider detail does not match create manifest",
                    )
                journal = self._record_ownership(journal_name, journal, transition="created")
                return self._finish_receipt(
                    journal_name, journal, payload, request, detail
                )
            except (
                DeploymentProviderConflict,
                DeploymentTransportError,
                DeploymentControlBlocked,
                TimeoutError,
            ):
                manifests = self._listed_manifests(marker=marker, suffix=suffix)
                match = self._select_owned_match(manifests, request=request)
                if match is None:
                    raise DeploymentControlBlocked(
                        "provider_outcome_uncertain",
                        "provider mutation outcome requires manual reconciliation",
                    ) from None
                journal = self._record_ownership(
                    journal_name, journal, transition="reconciled"
                )
                return self._finish_receipt(
                    journal_name, journal, payload, request, match
                )

    def cleanup(
        self,
        *,
        authorization: DeploymentCleanupAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
        receipt_digest: str,
    ) -> CleanupControlResult:
        """Delete only a durably owned RUNNING PTU under independent authority."""

        self._require_cleanup_endpoint()
        authorization_digest, binding, artifact = self._verify_cleanup_gate(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
            receipt_digest=receipt_digest,
            now=self._clock(),
        )
        journal_name = self._store.cleanup_journal_name(
            binding.run_identity, binding.operation_id
        )
        with self._store.run_lock(binding.run_identity):
            self._require_cleanup_endpoint()
            authorization_digest, binding, artifact = self._verify_cleanup_gate(
                authorization=authorization,
                trusted_authorities=trusted_authorities,
                receipt_digest=receipt_digest,
                now=self._clock(),
            )
            journal = self._load_cleanup_journal(
                journal_name=journal_name,
                binding=binding,
                authorization_digest=authorization_digest,
                manifest_digest=artifact.remote_manifest_digest,
            )
            if journal.terminal_receipt_digest is not None:
                return self._restore_cleanup_receipt(journal_name, journal)

            transport = cast(CleanupControlTransport, self._transport)
            try:
                detail = _parse_manifest(
                    transport.deployment_detail(
                        deployed_model=binding.deployed_model
                    )
                )
            except DeploymentNotFound:
                terminal: Literal["absent_404", "already_absent_404"] = (
                    "absent_404" if journal.delete_started else "already_absent_404"
                )
                return self._finish_cleanup(
                    journal_name=journal_name,
                    journal=journal,
                    binding=binding,
                    authorization_digest=authorization_digest,
                    manifest_digest=artifact.remote_manifest_digest,
                    terminal_state=terminal,
                    observed_at=self._clock(),
                )
            except (DeploymentTransportError, TimeoutError) as exc:
                raise DeploymentControlBlocked(
                    "billing_stop_unverified",
                    "cleanup detail could not prove terminal state",
                ) from exc
            if canonical_json_bytes(detail) != canonical_json_bytes(
                artifact.remote_manifest
            ):
                raise DeploymentControlBlocked(
                    "cleanup_manifest_mismatch",
                    "remote manifest changed before cleanup",
                )
            self._require_cleanup_endpoint()
            if journal.delete_started:
                raise DeploymentControlBlocked(
                    "billing_stop_unverified",
                    "a prior delete attempt remains nonterminal",
                )
            authorization_digest, binding, artifact = self._verify_cleanup_gate(
                authorization=authorization,
                trusted_authorities=trusted_authorities,
                receipt_digest=receipt_digest,
                now=self._clock(),
            )
            if canonical_json_bytes(detail) != canonical_json_bytes(
                artifact.remote_manifest
            ):
                raise DeploymentControlBlocked(
                    "cleanup_manifest_mismatch",
                    "remote manifest changed during cleanup authorization recheck",
                )
            self._require_cleanup_endpoint()
            journal = journal.model_copy(update={"delete_started": True})
            self._store.atomic_write(journal_name, canonical_json_bytes(journal))
            try:
                transport.delete_deployment(deployed_model=binding.deployed_model)
            except (DeploymentNotFound, DeploymentTransportError, TimeoutError):
                pass
            for _ in range(3):
                try:
                    observed = _parse_manifest(
                        transport.deployment_detail(
                            deployed_model=binding.deployed_model
                        )
                    )
                except DeploymentNotFound:
                    return self._finish_cleanup(
                        journal_name=journal_name,
                        journal=journal,
                        binding=binding,
                        authorization_digest=authorization_digest,
                        manifest_digest=artifact.remote_manifest_digest,
                        terminal_state="absent_404",
                        observed_at=self._clock(),
                    )
                except (DeploymentTransportError, TimeoutError) as exc:
                    raise DeploymentControlBlocked(
                        "billing_stop_unverified",
                        "cleanup reconciliation is uncertain",
                    ) from exc
                if canonical_json_bytes(observed) != canonical_json_bytes(
                    artifact.remote_manifest
                ):
                    raise DeploymentControlBlocked(
                        "billing_stop_unverified",
                        "cleanup reconciliation observed a drifted manifest",
                    )
            raise DeploymentControlBlocked(
                "billing_stop_unverified",
                "cleanup did not reach a terminal provider state",
            )

    def _require_cleanup_endpoint(self) -> None:
        if getattr(self._transport, "endpoint", None) != BAILIAN_DEPLOYMENT_ENDPOINT:
            raise DeploymentControlBlocked(
                "provider_endpoint_drift",
                "cleanup provider endpoint differs from fixed Bailian policy",
            )

    def _verify_cleanup_gate(
        self,
        *,
        authorization: DeploymentCleanupAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
        receipt_digest: str,
        now: datetime,
    ) -> tuple[str, InfrastructureCleanupBinding, DeploymentReceiptArtifact]:
        try:
            authorization_digest = verify_cleanup_authorization(
                authorization,
                trusted_authorities=trusted_authorities,
                now=now,
            )
            payload = authorization.payload
            binding = self._reserve_reader.infrastructure_cleanup_binding(
                payload.reserve_id
            )
        except (
            AttributeError,
            AuthorizationVerificationError,
            BudgetLedgerError,
            ValueError,
        ) as exc:
            raise DeploymentControlBlocked(
                "cleanup_authorization_invalid",
                "independent deployment cleanup authorization is invalid",
            ) from exc
        expected_binding = (
            binding.run_identity,
            binding.purpose,
            binding.scope,
            binding.operation_id,
            binding.reserve_id,
            binding.receipt_digest,
            binding.deployed_model,
            binding.workspace_ref,
            binding.project_ref,
            binding.credential_ref,
            binding.cleanup_deadline,
        )
        signed_binding = (
            payload.run_identity,
            payload.purpose,
            payload.scope,
            payload.operation_id,
            payload.reserve_id,
            payload.receipt_digest,
            payload.deployed_model,
            payload.workspace_ref,
            payload.project_ref,
            payload.credential_ref,
            payload.cleanup_deadline,
        )
        if signed_binding != expected_binding or receipt_digest != binding.receipt_digest:
            raise DeploymentControlBlocked(
                "cleanup_authorization_invalid",
                "cleanup authorization does not match durable ownership",
            )
        artifact = self._load_cleanup_source_artifact(binding)
        if (
            artifact.remote_manifest_digest
            != payload.expected_remote_manifest_digest
            or artifact.remote_manifest_digest != binding.remote_manifest_digest
            or artifact.receipt.content.remote_manifest_digest
            != binding.remote_manifest_digest
            or artifact.receipt.content_digest != binding.receipt_digest
            or artifact.receipt.content.deployed_model != binding.deployed_model
            or artifact.receipt.content.operation_id != binding.operation_id
            or artifact.receipt.content.infrastructure_reserve_id != binding.reserve_id
            or artifact.receipt.content.workspace_ref != binding.workspace_ref
            or artifact.receipt.content.project_ref != binding.project_ref
            or artifact.receipt.content.credential_ref != binding.credential_ref
        ):
            raise DeploymentControlBlocked(
                "cleanup_authorization_invalid",
                "cleanup authorization does not match the owned receipt manifest",
            )
        return authorization_digest, binding, artifact

    def _load_cleanup_source_artifact(
        self, binding: InfrastructureCleanupBinding
    ) -> DeploymentReceiptArtifact:
        raw = self._store.read(f"{binding.receipt_digest}.receipt.json")
        if raw is None:
            raise DeploymentControlBlocked(
                "cleanup_receipt_missing", "owned deployment receipt is missing"
            )
        try:
            return DeploymentReceiptArtifact.model_validate(
                _parse_json_bytes(raw, maximum=_MAX_ARTIFACT_BYTES)
            )
        except (DeploymentControlBlocked, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "cleanup_receipt_invalid", "owned deployment receipt is invalid"
            ) from exc

    def _load_cleanup_journal(
        self,
        *,
        journal_name: str,
        binding: InfrastructureCleanupBinding,
        authorization_digest: str,
        manifest_digest: str,
    ) -> CleanupOperationJournal:
        raw = self._store.read(journal_name)
        expected = CleanupOperationJournal(
            run_identity=binding.run_identity,
            operation_id=binding.operation_id,
            reserve_id=binding.reserve_id,
            receipt_digest=binding.receipt_digest,
            deployed_model=binding.deployed_model,
            cleanup_authorization_digest=authorization_digest,
            expected_remote_manifest_digest=manifest_digest,
            delete_started=False,
        )
        if raw is None:
            self._store.atomic_write(journal_name, canonical_json_bytes(expected))
            return expected
        try:
            observed = CleanupOperationJournal.model_validate(
                _parse_json_bytes(raw, maximum=_MAX_ARTIFACT_BYTES)
            )
        except (DeploymentControlBlocked, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "cleanup_journal_invalid", "cleanup journal is invalid"
            ) from exc
        comparable = observed.model_copy(
            update={
                "delete_started": False,
                "terminal_receipt_digest": None,
            }
        )
        if canonical_json_bytes(comparable) != canonical_json_bytes(expected):
            raise DeploymentControlBlocked(
                "cleanup_journal_conflict", "cleanup journal conflicts"
            )
        return observed

    def _finish_cleanup(
        self,
        *,
        journal_name: str,
        journal: CleanupOperationJournal,
        binding: InfrastructureCleanupBinding,
        authorization_digest: str,
        manifest_digest: str,
        terminal_state: Literal["absent_404", "already_absent_404"],
        observed_at: datetime,
    ) -> CleanupControlResult:
        receipt = CleanupReceipt(
            run_identity=binding.run_identity,
            operation_id=binding.operation_id,
            reserve_id=binding.reserve_id,
            receipt_digest=binding.receipt_digest,
            deployed_model=binding.deployed_model,
            cleanup_authorization_digest=authorization_digest,
            remote_manifest_digest=manifest_digest,
            terminal_state=terminal_state,
            observed_at=observed_at,
            billing_stop_verified=True,
        )
        receipt_digest = hashlib.sha256(
            _CLEANUP_RECEIPT_DOMAIN + canonical_json_bytes(receipt)
        ).hexdigest()
        receipt_name = f"{receipt_digest}.cleanup-receipt.json"
        content = canonical_json_bytes(receipt)
        existing = self._store.read(receipt_name)
        if existing is not None and existing != content:
            raise DeploymentControlBlocked(
                "cleanup_receipt_conflict", "cleanup receipt conflicts"
            )
        if existing is None:
            self._store.atomic_write(receipt_name, content)
        terminal = journal.model_copy(
            update={"terminal_receipt_digest": receipt_digest}
        )
        self._store.atomic_write(journal_name, canonical_json_bytes(terminal))
        return CleanupControlResult(
            receipt=receipt,
            receipt_path=self._store.path(receipt_name),
            journal_path=self._store.path(journal_name),
        )

    def _restore_cleanup_receipt(
        self, journal_name: str, journal: CleanupOperationJournal
    ) -> CleanupControlResult:
        assert journal.terminal_receipt_digest is not None
        receipt_name = (
            f"{journal.terminal_receipt_digest}.cleanup-receipt.json"
        )
        raw = self._store.read(receipt_name)
        try:
            if raw is None:
                raise ValueError("missing receipt")
            receipt = CleanupReceipt.model_validate(
                _parse_json_bytes(raw, maximum=_MAX_ARTIFACT_BYTES)
            )
        except (DeploymentControlBlocked, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "cleanup_receipt_invalid", "terminal cleanup receipt is invalid"
            ) from exc
        digest = hashlib.sha256(
            _CLEANUP_RECEIPT_DOMAIN + canonical_json_bytes(receipt)
        ).hexdigest()
        if digest != journal.terminal_receipt_digest:
            raise DeploymentControlBlocked(
                "cleanup_receipt_invalid", "cleanup receipt digest mismatch"
            )
        return CleanupControlResult(
            receipt=receipt,
            receipt_path=self._store.path(receipt_name),
            journal_path=self._store.path(journal_name),
        )

    def _verify_gate(
        self,
        *,
        authorization: ProvisioningAuthorization,
        permit: InfrastructureCreatePermit,
        trusted_authorities: Mapping[str, TrustedAuthority],
        now: datetime,
    ) -> ProvisioningAuthorizationPayload:
        if self._transport.endpoint != BAILIAN_DEPLOYMENT_ENDPOINT:
            raise DeploymentControlBlocked(
                "provider_endpoint_drift", "provider endpoint differs from fixed policy"
            )
        try:
            validated = ProvisioningAuthorization.model_validate(
                authorization.model_dump(mode="python", round_trip=True)
            )
            payload = validated.payload
            if payload.base_model not in _ALLOWED_BASES:
                raise ValueError("base model is outside fixed policy")
            if (
                payload.provider != "bailian"
                or payload.region != _REGION
                or payload.request_plan != _REQUEST_PLAN
                or payload.receipt_plan != _RECEIPT_PLAN
                or payload.input_tpm_quota != _INPUT_TPM
                or payload.output_tpm_quota != _OUTPUT_TPM
            ):
                raise ValueError("deployment policy drift")
            digest = verify_provisioning_authorization(
                validated,
                expected=payload,
                trusted_authorities=trusted_authorities,
                now=now,
            )
            permit.require_fresh(now)
        except (AuthorizationVerificationError, BudgetLedgerError, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "provisioning_gate_rejected", "provisioning authorization is invalid"
            ) from exc
        if (
            permit.operation_id != payload.operation_id
            or permit.reserve.reserve_id != payload.infrastructure_reserve_id
            or permit.reserve.run_identity != payload.run_identity
            or permit.reserve.purpose != payload.purpose
            or permit.reserve.authorization_digest != digest
            or permit.reserve.maximum.cost_minor_units
            != payload.maximum_cost_minor_units
            or permit.reserve.maximum.input_tokens != 0
            or permit.reserve.maximum.output_tokens != 0
        ):
            raise DeploymentControlBlocked(
                "provisioning_permit_mismatch",
                "provisioning permit does not match the signed operation",
            )
        self._require_current_reserve(permit)
        return payload

    def _require_current_reserve(self, permit: InfrastructureCreatePermit) -> None:
        try:
            current = self._reserve_reader.infrastructure_reserve(
                permit.reserve.reserve_id
            )
        except (BudgetLedgerError, RuntimeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "durable_reserve_missing", "durable infrastructure reserve is unavailable"
            ) from exc
        if canonical_json_bytes(current) != canonical_json_bytes(permit.reserve):
            raise DeploymentControlBlocked(
                "durable_reserve_mismatch", "permit does not match durable reserve state"
            )

    def _load_or_create_journal(
        self,
        *,
        journal_name: str,
        payload: ProvisioningAuthorizationPayload,
        authorization_digest: str,
        marker: str,
        suffix: str,
    ) -> DeploymentOperationJournal:
        raw = self._store.read(journal_name)
        if raw is None:
            journal = DeploymentOperationJournal(
                run_identity=payload.run_identity,
                operation_id=payload.operation_id,
                infrastructure_reserve_id=payload.infrastructure_reserve_id,
                authorization_digest=authorization_digest,
                operation_marker=marker,
                deployment_suffix=suffix,
                state="authorized",
                history=("authorized",),
            )
            self._write_journal(journal_name, journal)
            return journal
        try:
            value = _parse_json_bytes(raw, maximum=_MAX_ARTIFACT_BYTES)
            journal = DeploymentOperationJournal.model_validate(value)
        except (DeploymentControlBlocked, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "operation_journal_invalid", "deployment operation journal is invalid"
            ) from exc
        expected = (
            payload.run_identity,
            payload.operation_id,
            payload.infrastructure_reserve_id,
            authorization_digest,
            marker,
            suffix,
        )
        observed = (
            journal.run_identity,
            journal.operation_id,
            journal.infrastructure_reserve_id,
            journal.authorization_digest,
            journal.operation_marker,
            journal.deployment_suffix,
        )
        if observed != expected:
            raise DeploymentControlBlocked(
                "operation_journal_conflict", "deployment operation journal conflicts"
            )
        return journal

    def _advance_to_prepared(
        self, journal_name: str, journal: DeploymentOperationJournal
    ) -> DeploymentOperationJournal:
        if journal.state == "authorized":
            journal = journal.model_copy(
                update={"state": "reserved", "history": (*journal.history, "reserved")}
            )
            self._write_journal(journal_name, journal)
        if journal.state == "reserved":
            journal = journal.model_copy(
                update={"state": "prepared", "history": (*journal.history, "prepared")}
            )
            self._write_journal(journal_name, journal)
        return journal

    def _write_journal(
        self, journal_name: str, journal: DeploymentOperationJournal
    ) -> None:
        self._store.atomic_write(journal_name, canonical_json_bytes(journal))

    def _listed_manifests(
        self, *, marker: str, suffix: str
    ) -> tuple[ProviderDeploymentManifest, ...]:
        try:
            return _parse_list(
                self._transport.list_deployments(marker=marker, suffix=suffix)
            )
        except (DeploymentTransportError, TimeoutError) as exc:
            raise DeploymentControlBlocked(
                "provider_response_invalid", "provider list response is unavailable"
            ) from exc

    @staticmethod
    def _select_owned_match(
        manifests: tuple[ProviderDeploymentManifest, ...],
        *,
        request: BailianDeploymentRequest,
    ) -> ProviderDeploymentManifest | None:
        exact_selector = tuple(
            manifest
            for manifest in manifests
            if manifest.operation_marker == request.operation_marker
            and manifest.deployment_suffix == request.deployment_suffix
        )
        collisions = tuple(
            manifest
            for manifest in manifests
            if (
                manifest.operation_marker == request.operation_marker
                or manifest.deployment_suffix == request.deployment_suffix
            )
            and manifest not in exact_selector
        )
        if collisions:
            raise DeploymentControlBlocked(
                "provider_marker_collision", "foreign provider marker or suffix collision"
            )
        if len(exact_selector) > 1:
            raise DeploymentControlBlocked(
                "provider_multiple_matches", "multiple provider deployments match operation"
            )
        if not exact_selector:
            return None
        match = exact_selector[0]
        DeploymentController._require_exact_manifest(match, request)
        return match

    @staticmethod
    def _require_exact_manifest(
        manifest: ProviderDeploymentManifest,
        request: BailianDeploymentRequest,
    ) -> None:
        expected_deployed_model = f"{request.base_model}-{request.deployment_suffix}"
        if (
            manifest.deployed_model != expected_deployed_model
            or manifest.base_model != request.base_model
            or manifest.plan != _RECEIPT_PLAN
            or manifest.input_tpm != request.input_tpm_quota
            or manifest.output_tpm != request.output_tpm_quota
            or manifest.status != "RUNNING"
            or manifest.workspace_ref != request.workspace_ref
            or manifest.operation_marker != request.operation_marker
            or manifest.deployment_suffix != request.deployment_suffix
        ):
            raise DeploymentControlBlocked(
                "remote_manifest_mismatch", "foreign or drifted provider manifest"
            )

    def _record_ownership(
        self,
        journal_name: str,
        journal: DeploymentOperationJournal,
        *,
        transition: Literal["created", "reconciled"],
    ) -> DeploymentOperationJournal:
        if journal.state in {"created", "reconciled", "receipted"}:
            return journal
        updated = journal.model_copy(
            update={"state": transition, "history": (*journal.history, transition)}
        )
        self._write_journal(journal_name, updated)
        return updated

    def _finish_receipt(
        self,
        journal_name: str,
        journal: DeploymentOperationJournal,
        payload: ProvisioningAuthorizationPayload,
        request: BailianDeploymentRequest,
        manifest: ProviderDeploymentManifest,
    ) -> DeploymentControlResult:
        self._require_exact_manifest(manifest, request)
        detail = _parse_manifest(
            self._transport.deployment_detail(deployed_model=manifest.deployed_model)
        )
        if canonical_json_bytes(detail) != canonical_json_bytes(manifest):
            raise DeploymentControlBlocked(
                "remote_manifest_mismatch", "remote manifest changed before receipt"
            )
        content = DeploymentReceiptContent(
            operation_id=payload.operation_id,
            infrastructure_reserve_id=payload.infrastructure_reserve_id,
            workspace_ref=payload.workspace_ref,
            project_ref=payload.project_ref,
            credential_ref=payload.credential_ref,
            workspace_evidence_digest=_workspace_evidence_digest(payload),
            region=payload.region,
            base_model=payload.base_model,
            deployed_model=detail.deployed_model,
            request_plan=payload.request_plan,
            receipt_plan=detail.plan,
            input_tpm=detail.input_tpm,
            output_tpm=detail.output_tpm,
            gmt_create=detail.gmt_create,
            gmt_modified=detail.gmt_modified,
            cleanup_state="required",
            operation_marker=detail.operation_marker,
            deployment_suffix=detail.deployment_suffix,
            remote_manifest_digest=_remote_manifest_digest(detail),
        )
        receipt = DeploymentReceipt(
            content=content,
            content_digest=deployment_receipt_content_digest(content),
        )
        remote_content = DeploymentReceiptContent.model_validate(
            content.model_dump(mode="python", round_trip=True)
        )
        remote_receipt = DeploymentReceipt(
            content=remote_content,
            content_digest=deployment_receipt_content_digest(remote_content),
        )
        capability = verify_reconciled_deployment_receipt(
            receipt,
            remote_expected=remote_receipt,
        )
        artifact = DeploymentReceiptArtifact(
            receipt=receipt,
            remote_manifest=detail,
            remote_manifest_digest=_remote_manifest_digest(detail),
        )
        receipt_name = f"{receipt.content_digest}.receipt.json"
        artifact_bytes = canonical_json_bytes(artifact)
        existing = self._store.read(receipt_name)
        if existing is not None and existing != artifact_bytes:
            raise DeploymentControlBlocked(
                "receipt_conflict", "content-addressed receipt conflicts"
            )
        if existing is None:
            self._store.atomic_write(receipt_name, artifact_bytes)
        terminal = journal.model_copy(
            update={
                "state": "receipted",
                "history": (*journal.history, "receipted"),
                "receipt_digest": receipt.content_digest,
            }
        )
        self._write_journal(journal_name, terminal)
        return DeploymentControlResult(
            receipt=receipt,
            receipt_capability=capability,
            remote_manifest_digest=artifact.remote_manifest_digest,
            receipt_path=self._store.path(receipt_name),
            journal_path=self._store.path(journal_name),
        )

    def _restore_receipt(
        self,
        journal_name: str,
        journal: DeploymentOperationJournal,
        payload: ProvisioningAuthorizationPayload,
        request: BailianDeploymentRequest,
    ) -> DeploymentControlResult:
        assert journal.receipt_digest is not None
        receipt_name = f"{journal.receipt_digest}.receipt.json"
        raw = self._store.read(receipt_name)
        if raw is None:
            raise DeploymentControlBlocked(
                "receipt_missing", "terminal journal receipt is missing"
            )
        try:
            artifact = DeploymentReceiptArtifact.model_validate(
                _parse_json_bytes(raw, maximum=_MAX_ARTIFACT_BYTES)
            )
        except (DeploymentControlBlocked, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "receipt_invalid", "stored deployment receipt is invalid"
            ) from exc
        if artifact.receipt.content_digest != journal.receipt_digest:
            raise DeploymentControlBlocked(
                "receipt_invalid", "stored receipt does not match journal"
            )
        return self._finish_receipt_from_existing(
            journal_name, journal, payload, request, artifact
        )

    def _finish_receipt_from_existing(
        self,
        journal_name: str,
        journal: DeploymentOperationJournal,
        payload: ProvisioningAuthorizationPayload,
        request: BailianDeploymentRequest,
        artifact: DeploymentReceiptArtifact,
    ) -> DeploymentControlResult:
        self._require_exact_manifest(artifact.remote_manifest, request)
        detail = _parse_manifest(
            self._transport.deployment_detail(
                deployed_model=artifact.remote_manifest.deployed_model
            )
        )
        if canonical_json_bytes(detail) != canonical_json_bytes(
            artifact.remote_manifest
        ):
            raise DeploymentControlBlocked(
                "remote_manifest_mismatch", "remote manifest changed after receipt"
            )
        content = artifact.receipt.content
        expected = DeploymentReceiptContent(
            operation_id=payload.operation_id,
            infrastructure_reserve_id=payload.infrastructure_reserve_id,
            workspace_ref=payload.workspace_ref,
            project_ref=payload.project_ref,
            credential_ref=payload.credential_ref,
            workspace_evidence_digest=_workspace_evidence_digest(payload),
            region=payload.region,
            base_model=detail.base_model,
            deployed_model=detail.deployed_model,
            request_plan=payload.request_plan,
            receipt_plan=detail.plan,
            input_tpm=detail.input_tpm,
            output_tpm=detail.output_tpm,
            gmt_create=detail.gmt_create,
            gmt_modified=detail.gmt_modified,
            cleanup_state="required",
            operation_marker=detail.operation_marker,
            deployment_suffix=detail.deployment_suffix,
            remote_manifest_digest=_remote_manifest_digest(detail),
        )
        if canonical_json_bytes(content) != canonical_json_bytes(expected):
            raise DeploymentControlBlocked(
                "receipt_invalid", "stored receipt no longer matches exact manifest"
            )
        remote_receipt = DeploymentReceipt(
            content=DeploymentReceiptContent.model_validate(
                expected.model_dump(mode="python", round_trip=True)
            ),
            content_digest=deployment_receipt_content_digest(expected),
        )
        capability = verify_reconciled_deployment_receipt(
            artifact.receipt,
            remote_expected=remote_receipt,
        )
        return DeploymentControlResult(
            receipt=artifact.receipt,
            receipt_capability=capability,
            remote_manifest_digest=artifact.remote_manifest_digest,
            receipt_path=self._store.path(f"{journal.receipt_digest}.receipt.json"),
            journal_path=self._store.path(journal_name),
        )


__all__ = [
    "BAILIAN_DEPLOYMENT_ENDPOINT",
    "BailianDeploymentHTTPTransport",
    "BailianDeploymentRequest",
    "DeploymentControlBlocked",
    "DeploymentControlResult",
    "DeploymentController",
    "DeploymentOperationJournal",
    "DeploymentProviderConflict",
    "DeploymentReceiptArtifact",
    "DeploymentTransportError",
    "ProviderDeploymentManifest",
    "deterministic_deployment_suffix",
    "deterministic_operation_marker",
]
