"""Crash-safe, zero-inference Bailian deployment creation control.

The controller owns the provider request shape, persists a send-intent before the
only permitted POST, and reconciles every ambiguous outcome.  Raw provider bytes,
credentials, and caller-selected URLs never enter its durable artifacts.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import threading
import weakref
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, Never, Protocol, Self, SupportsIndex, cast
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
    VerifiedFinalTopology,
    VerifiedInfrastructureProviderCapCapability,
    VerifiedTopologyProviderCapCapability,
)
from insurance_harness.goldenset.admission_infrastructure import (
    _PRODUCTION_CAPABILITY_SEAL,
    AuthorizationVerificationError,
    DeploymentCleanupAuthorization,
    DeploymentCleanupAuthorizationPayload,
    DeploymentReceipt,
    DeploymentReceiptContent,
    ExistingDeploymentAdoptionAuthorization,
    ExistingDeploymentAdoptionAuthorizationPayload,
    ProvisioningAuthorization,
    ProvisioningAuthorizationPayload,
    VerifiedDeploymentTransportIdentity,
    VerifiedReconciledDeploymentReceipt,
    _issue_verified_reconciled_receipt_for_testing,
    _register_verified_reconciled_receipt_capability,
    _require_verified_deployment_transport_identity_for_testing,
    cleanup_authorization_digest,
    credential_ref_for_api_key,
    deployment_receipt_content_digest,
    deployment_reconciliation_digest,
    infrastructure_authorization_digest,
    issue_verified_deployment_transport_identity,
    issue_verified_topology_deployment_transport_identity,
    require_verified_deployment_transport_identity,
    verify_adoption_authorization,
    verify_cleanup_authorization,
    verify_provisioning_authorization,
)
from insurance_harness.goldenset.admission_models import (
    RunAdmissionPlanPayload,
    TrustedAuthority,
    canonical_json_bytes,
)

BAILIAN_DEPLOYMENT_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/deployments"
_PRODUCTION_RUN_ROOT = Path("/var/lib/insurancekb/run-admission/deployments")
_PRODUCTION_BUDGET_LEDGER_PATH = Path("/var/lib/insurancekb/run-admission/budget.sqlite3")
_PRODUCTION_API_KEY_ENV = "HARNESS_DASHSCOPE_API_KEY"
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
_MAX_CLEANUP_JOURNAL_ARTIFACTS = 64
_PRIVATE_DIRECTORY_MODE = 0o700
_PRIVATE_FILE_MODE = 0o600
_MARKER_DOMAIN = b"insurancekb.run-admission.deployment-marker.v1\0"
_SUFFIX_DOMAIN = b"insurancekb.run-admission.deployment-suffix.v1\0"
_WORKSPACE_EVIDENCE_DOMAIN = b"insurancekb.run-admission.workspace-evidence.v1\0"
_REMOTE_MANIFEST_DOMAIN = b"insurancekb.run-admission.remote-manifest.v1\0"
_IDEMPOTENCY_DOMAIN = b"insurancekb.run-admission.deployment-idempotency.v1\0"
_TOPOLOGY_OBSERVATION_BATCH_DOMAIN = (
    b"insurancekb.run-admission.topology-reconciliation-observation-batch.v1\0"
)
_CLEANUP_TRANSPORT_IDENTITY_DOMAIN = (
    b"insurancekb.run-admission.cleanup-transport-identity.v1\0"
)
_CLEANUP_DELETE_INTENT_DOMAIN = (
    b"insurancekb.run-admission.cleanup-delete-intent.v1\0"
)
_CLEANUP_DELETE_ATTEMPT_DOMAIN = (
    b"insurancekb.run-admission.cleanup-delete-attempt.v1\0"
)
_CLEANUP_DELETE_ATTEMPT_PROOF_DOMAIN = (
    b"insurancekb.run-admission.cleanup-delete-attempt-proof.v1\0"
)
_CLEANUP_RECEIPT_DOMAIN = b"insurancekb.run-admission.cleanup-receipt.v1\0"
_CLEANUP_RESOURCE_DOMAIN = b"insurancekb.run-admission.cleanup-resource.v1\0"
_CLEANUP_OBSERVATION_KEY_DOMAIN = (
    b"insurancekb.run-admission.cleanup-observation-key.v1\0"
)
_CLEANUP_OBSERVATION_PROOF_DOMAIN = (
    b"insurancekb.run-admission.cleanup-observation-proof.v1\0"
)
_TESTING_CLEANUP_OBSERVATION_KEY = b"test-only-cleanup-observation-key-v1"
_RECONCILIATION_FRESHNESS = timedelta(minutes=5)
_TESTING_MODE_SENTINEL = object()
_SAFE_PROVIDER_ID = re.compile(r"^[A-Za-z0-9._:@+-]{1,512}$")

type NonBlankStr = Annotated[
    StrictStr, StringConstraints(strip_whitespace=True, min_length=1, max_length=512)
]
type Sha256Digest = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
type OwnershipNonce = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
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
    ownership_nonce: OwnershipNonce
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
    ownership_nonce: OwnershipNonce
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
    version: Literal[2] = 2
    run_identity: NonBlankStr
    operation_id: NonBlankStr
    infrastructure_reserve_id: NonBlankStr
    authorization_digest: Sha256Digest
    ownership_nonce: OwnershipNonce
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
            "created": frozenset({("authorized", "reserved", "prepared", "created")}),
            "reconciled": frozenset({("authorized", "reserved", "prepared", "reconciled")}),
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


class DeploymentReconciliationEvidenceV1(_ImmutableModel):
    """Immutable provider provenance published beside one ownership receipt."""

    version: Literal["insurancekb.run-admission.deployment-reconciliation-evidence.v1"]
    issuer: Literal["bailian-deployment-controller-v1"]
    transport_identity_digest: Sha256Digest
    run_identity: NonBlankStr
    purpose: NonBlankStr
    scope: NonBlankStr
    receipt: DeploymentReceipt
    remote_manifest: ProviderDeploymentManifest
    receipt_digest: Sha256Digest
    operation_id: NonBlankStr
    reserve_id: NonBlankStr
    workspace_ref: NonBlankStr
    project_ref: NonBlankStr
    credential_ref: NonBlankStr
    provider_cap_evidence_digest: Sha256Digest
    provider_cap_approval_digest: Sha256Digest
    remote_manifest_digest: Sha256Digest
    observed_at: datetime
    expires_at: datetime
    reconciliation_digest: Sha256Digest

    @model_validator(mode="after")
    def require_exact_reconciliation_evidence(
        self,
    ) -> DeploymentReconciliationEvidenceV1:
        content = self.receipt.content
        manifest = self.remote_manifest
        if (
            self.receipt.content_digest != deployment_receipt_content_digest(content)
            or self.receipt_digest != self.receipt.content_digest
            or self.operation_id != content.operation_id
            or self.reserve_id != content.infrastructure_reserve_id
            or self.workspace_ref != content.workspace_ref
            or self.project_ref != content.project_ref
            or self.credential_ref != content.credential_ref
            or self.remote_manifest_digest != _remote_manifest_digest(self.remote_manifest)
            or self.remote_manifest_digest != content.remote_manifest_digest
            or content.deployed_model != manifest.deployed_model
            or content.base_model != manifest.base_model
            or content.receipt_plan != manifest.plan
            or content.input_tpm != manifest.input_tpm
            or content.output_tpm != manifest.output_tpm
            or content.gmt_create != manifest.gmt_create
            or content.gmt_modified != manifest.gmt_modified
            or content.workspace_ref != manifest.workspace_ref
            or content.operation_marker != manifest.operation_marker
            or content.deployment_suffix != manifest.deployment_suffix
        ):
            raise ValueError("reconciliation evidence does not match receipt and manifest")
        expected_digest = deployment_reconciliation_digest(
            issuer=self.issuer,
            transport_identity_digest=self.transport_identity_digest,
            run_identity=self.run_identity,
            purpose=self.purpose,
            scope=self.scope,
            receipt_digest=self.receipt_digest,
            operation_id=self.operation_id,
            reserve_id=self.reserve_id,
            workspace_ref=self.workspace_ref,
            project_ref=self.project_ref,
            credential_ref=self.credential_ref,
            provider_cap_evidence_digest=self.provider_cap_evidence_digest,
            provider_cap_approval_digest=self.provider_cap_approval_digest,
            remote_manifest_digest=self.remote_manifest_digest,
            observed_at=self.observed_at,
            expires_at=self.expires_at,
        )
        if self.reconciliation_digest != expected_digest:
            raise ValueError("reconciliation evidence digest mismatch")
        return self


class DeploymentControlResult(_ImmutableModel):
    receipt: DeploymentReceipt
    receipt_capability: VerifiedReconciledDeploymentReceipt
    remote_manifest_digest: Sha256Digest
    receipt_path: Path
    journal_path: Path


class DeploymentAdoptionResult(_ImmutableModel):
    receipt: DeploymentReceipt
    receipt_capability: VerifiedReconciledDeploymentReceipt
    remote_manifest_digest: Sha256Digest
    receipt_path: Path


class CleanupDeleteIntent(_ImmutableModel):
    version: Literal[1] = 1
    binding: InfrastructureCleanupBinding
    authorization: DeploymentCleanupAuthorization
    authorization_digest: Sha256Digest
    authorization_issued_at: datetime

    @field_validator("authorization_issued_at")
    @classmethod
    def require_aware_start(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cleanup delete start must include a timezone")
        return value


class CleanupDeleteIntentSlot(_ImmutableModel):
    version: Literal[1] = 1
    intent: CleanupDeleteIntent
    intent_digest: Sha256Digest

    @model_validator(mode="after")
    def require_matching_intent_digest(self) -> CleanupDeleteIntentSlot:
        expected = hashlib.sha256(
            _CLEANUP_DELETE_INTENT_DOMAIN + canonical_json_bytes(self.intent)
        ).hexdigest()
        if self.intent_digest != expected:
            raise ValueError("cleanup delete intent slot digest mismatch")
        return self


class DurableDeleteAttemptEvidence(_ImmutableModel):
    version: Literal[1] = 1
    binding: InfrastructureCleanupBinding
    intent_digest: Sha256Digest
    cleanup_authorization_digest: Sha256Digest
    cleanup_transport_identity_digest: Sha256Digest
    attempted_at: datetime
    outcome_class: Literal["accepted"] = "accepted"
    attempt_proof: Sha256Digest

    @field_validator("attempted_at")
    @classmethod
    def require_aware_attempt_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cleanup delete attempt time must include a timezone")
        return value


@dataclass(frozen=True, slots=True, init=False)
class _VerifiedDeleteAttemptSnapshot:
    """Controller-local capability for an exact paired intent/attempt snapshot."""

    intent_slot: CleanupDeleteIntentSlot
    attempt: DurableDeleteAttemptEvidence
    attempt_digest: Sha256Digest
    slot_index: int
    _seal: object

    def __copy__(self) -> Never:
        raise TypeError("verified cleanup attempt snapshots cannot be copied")

    def __deepcopy__(self, memo: object) -> Never:
        raise TypeError("verified cleanup attempt snapshots cannot be copied")

    def __reduce__(self) -> Never:
        raise TypeError("verified cleanup attempt snapshots cannot be serialized")

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        raise TypeError("verified cleanup attempt snapshots cannot be serialized")


class CleanupReceipt(_ImmutableModel):
    version: Literal[1] = 1
    binding: InfrastructureCleanupBinding
    cleanup_authorization_digest: Sha256Digest
    causal_delete_attempt_digest: Sha256Digest | None
    terminal_state: Literal["absent_404", "already_absent_404"]
    observed_at: datetime
    cleanup_transport_identity_digest: Sha256Digest
    observation_proof: Sha256Digest
    billing_stop_verified: Literal[True] = True

    @field_validator("observed_at")
    @classmethod
    def require_aware_observation(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("cleanup observation must include a timezone")
        return value

    @model_validator(mode="after")
    def require_causal_delete_for_deleted_state(self) -> CleanupReceipt:
        if (self.terminal_state == "absent_404") != (
            self.causal_delete_attempt_digest is not None
        ):
            raise ValueError("cleanup terminal state has invalid delete causality")
        return self


class CleanupControlResult(_ImmutableModel):
    receipt: CleanupReceipt
    receipt_path: Path
    journal_path: Path | None


class CleanupTerminalJournal(_ImmutableModel):
    version: Literal[1] = 1
    binding: InfrastructureCleanupBinding
    receipt: CleanupReceipt
    receipt_digest: Sha256Digest
    causal_intent_snapshot: CleanupDeleteIntentSlot | None = None
    causal_attempt_snapshot: DurableDeleteAttemptEvidence | None = None

    @model_validator(mode="after")
    def require_matching_terminal_receipt(self) -> CleanupTerminalJournal:
        expected = hashlib.sha256(
            _CLEANUP_RECEIPT_DOMAIN + canonical_json_bytes(self.receipt)
        ).hexdigest()
        if self.receipt.binding != self.binding or self.receipt_digest != expected:
            raise ValueError("cleanup terminal journal receipt mismatch")
        snapshots_present = (
            self.causal_intent_snapshot is not None
            and self.causal_attempt_snapshot is not None
        )
        if snapshots_present != (
            self.receipt.causal_delete_attempt_digest is not None
        ) or (self.causal_intent_snapshot is None) != (
            self.causal_attempt_snapshot is None
        ):
            raise ValueError("cleanup terminal journal causality snapshot mismatch")
        if snapshots_present:
            assert self.causal_intent_snapshot is not None
            assert self.causal_attempt_snapshot is not None
            attempt_bytes = canonical_json_bytes(self.causal_attempt_snapshot)
            attempt_digest = hashlib.sha256(
                _CLEANUP_DELETE_ATTEMPT_DOMAIN + attempt_bytes
            ).hexdigest()
            if (
                self.causal_intent_snapshot.intent.binding != self.binding
                or self.causal_attempt_snapshot.binding != self.binding
                or self.causal_attempt_snapshot.intent_digest
                != self.causal_intent_snapshot.intent_digest
                or self.causal_attempt_snapshot.cleanup_authorization_digest
                != self.causal_intent_snapshot.intent.authorization_digest
                or attempt_digest != self.receipt.causal_delete_attempt_digest
            ):
                raise ValueError("cleanup terminal journal causal evidence mismatch")
        return self


def _cleanup_observation_bytes(
    *,
    binding: InfrastructureCleanupBinding,
    cleanup_authorization_digest: str,
    causal_delete_attempt_digest: str | None,
    terminal_state: Literal["absent_404", "already_absent_404"],
    observed_at: datetime,
    cleanup_transport_identity_digest: str,
    causal_intent_snapshot: CleanupDeleteIntentSlot | None,
    causal_attempt_snapshot: DurableDeleteAttemptEvidence | None,
) -> bytes:
    return canonical_json_bytes(
        {
            "billing_stop_verified": True,
            "binding": binding,
            "causal_delete_attempt_digest": causal_delete_attempt_digest,
            "causal_intent_snapshot": causal_intent_snapshot,
            "causal_attempt_snapshot": causal_attempt_snapshot,
            "cleanup_authorization_digest": cleanup_authorization_digest,
            "cleanup_transport_identity_digest": cleanup_transport_identity_digest,
            "observed_at": observed_at,
            "terminal_state": terminal_state,
            "version": 1,
        }
    )


def _cleanup_resource_digest(binding: InfrastructureCleanupBinding) -> str:
    return hashlib.sha256(
        _CLEANUP_RESOURCE_DOMAIN + canonical_json_bytes(binding)
    ).hexdigest()


def _cleanup_delete_attempt_bytes(
    *,
    binding: InfrastructureCleanupBinding,
    intent_digest: str,
    cleanup_authorization_digest: str,
    cleanup_transport_identity_digest: str,
    attempted_at: datetime,
) -> bytes:
    return canonical_json_bytes(
        {
            "attempted_at": attempted_at,
            "binding": binding,
            "cleanup_authorization_digest": cleanup_authorization_digest,
            "cleanup_transport_identity_digest": cleanup_transport_identity_digest,
            "intent_digest": intent_digest,
            "outcome_class": "accepted",
            "version": 1,
        }
    )


class _CleanupObservationAuthenticator:
    """Machine-local proof issuer; raw key material is never serialized."""

    __slots__ = ("__weakref__",)

    def __init__(self) -> None:
        raise TypeError("cleanup observation authenticators are issuer-created")

    @classmethod
    def for_production(cls, api_key: str) -> _CleanupObservationAuthenticator:
        if not isinstance(api_key, str) or not api_key:
            raise ValueError("cleanup observation key source is invalid")
        instance = object.__new__(cls)
        _CLEANUP_OBSERVATION_AUTHENTICATOR_REGISTRY.register(
            instance,
            hmac.new(
                api_key.encode("utf-8"),
                _CLEANUP_OBSERVATION_KEY_DOMAIN,
                hashlib.sha256,
            ).digest(),
        )
        return instance

    @classmethod
    def for_testing(cls) -> _CleanupObservationAuthenticator:
        instance = object.__new__(cls)
        _CLEANUP_OBSERVATION_AUTHENTICATOR_REGISTRY.register(
            instance,
            hmac.new(
                _TESTING_CLEANUP_OBSERVATION_KEY,
                _CLEANUP_OBSERVATION_KEY_DOMAIN,
                hashlib.sha256,
            ).digest(),
        )
        return instance

    def proof(self, observation: bytes) -> str:
        return hmac.new(
            _CLEANUP_OBSERVATION_AUTHENTICATOR_REGISTRY.require(self),
            _CLEANUP_OBSERVATION_PROOF_DOMAIN + observation,
            hashlib.sha256,
        ).hexdigest()

    def require(self, observation: bytes, proof: str) -> None:
        expected = self.proof(observation)
        if not hmac.compare_digest(expected, proof):
            raise DeploymentControlBlocked(
                "cleanup_receipt_invalid",
                "terminal cleanup observation proof is invalid",
            )

    def attempt_proof(self, attempt: bytes) -> str:
        return hmac.new(
            _CLEANUP_OBSERVATION_AUTHENTICATOR_REGISTRY.require(self),
            _CLEANUP_DELETE_ATTEMPT_PROOF_DOMAIN + attempt,
            hashlib.sha256,
        ).hexdigest()

    def require_attempt(self, attempt: bytes, proof: str) -> None:
        expected = self.attempt_proof(attempt)
        if not hmac.compare_digest(expected, proof):
            raise DeploymentControlBlocked(
                "cleanup_attempt_invalid",
                "completed cleanup attempt proof is invalid",
            )

    def __copy__(self) -> None:
        raise TypeError("cleanup observation authenticators cannot be copied")

    def __deepcopy__(self, memo: object) -> None:
        raise TypeError("cleanup observation authenticators cannot be copied")

    def __reduce__(self) -> Never:
        raise TypeError("cleanup observation authenticators cannot be serialized")

    def __reduce_ex__(self, protocol: SupportsIndex) -> Never:
        raise TypeError("cleanup observation authenticators cannot be serialized")


class _CleanupObservationAuthenticatorRegistry:
    """PID-bound issuer registry with no reverse strong reference to capabilities."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pid = os.getpid()
        self._keys: weakref.WeakKeyDictionary[
            _CleanupObservationAuthenticator,
            bytes,
        ] = weakref.WeakKeyDictionary()

    def _reset_after_fork(self) -> None:
        pid = os.getpid()
        if pid != self._pid:
            self._pid = pid
            self._keys = weakref.WeakKeyDictionary()

    def register(
        self,
        authenticator: _CleanupObservationAuthenticator,
        key: bytes,
    ) -> None:
        with self._lock:
            self._reset_after_fork()
            self._keys[authenticator] = bytes(key)

    def require(self, authenticator: object) -> bytes:
        with self._lock:
            self._reset_after_fork()
            if type(authenticator) is not _CleanupObservationAuthenticator:
                raise DeploymentControlBlocked(
                    "cleanup_receipt_invalid",
                    "terminal cleanup observation authenticator is invalid",
                )
            key = self._keys.get(authenticator)
            if key is None:
                raise DeploymentControlBlocked(
                    "cleanup_receipt_invalid",
                    "terminal cleanup observation authenticator is unregistered",
                )
            return key


_CLEANUP_OBSERVATION_AUTHENTICATOR_REGISTRY = (
    _CleanupObservationAuthenticatorRegistry()
)


@dataclass(frozen=True, slots=True, init=False, weakref_slot=True)
class _CleanupTransportIdentity:
    """Issuer-private non-secret credential identity for cost-reducing cleanup."""

    provider: str
    endpoint: str
    workspace_ref: str
    project_ref: str
    credential_ref: str
    credential_fingerprint: str
    identity_digest: str
    _seal: object


class _CleanupTransportIdentityRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pid = os.getpid()
        self._nonce = secrets.token_bytes(32)
        self._entries: dict[
            int,
            tuple[weakref.ReferenceType[_CleanupTransportIdentity], bytes],
        ] = {}

    def _reset_after_fork(self) -> None:
        if os.getpid() != self._pid:
            self._entries.clear()
            self._pid = os.getpid()
            self._nonce = secrets.token_bytes(32)

    def register(self, identity: _CleanupTransportIdentity, snapshot: bytes) -> None:
        with self._lock:
            self._reset_after_fork()
            key = id(identity)

            def discard(
                reference: weakref.ReferenceType[_CleanupTransportIdentity],
            ) -> None:
                with self._lock:
                    current = self._entries.get(key)
                    if current is not None and current[0] is reference:
                        self._entries.pop(key, None)

            reference = weakref.ref(identity, discard)
            digest = hmac.new(
                self._nonce,
                _CLEANUP_TRANSPORT_IDENTITY_DOMAIN + snapshot,
                hashlib.sha256,
            ).digest()
            self._entries[key] = (reference, digest)

    def require(self, identity: _CleanupTransportIdentity, snapshot: bytes) -> None:
        with self._lock:
            self._reset_after_fork()
            current = self._entries.get(id(identity))
            expected = hmac.new(
                self._nonce,
                _CLEANUP_TRANSPORT_IDENTITY_DOMAIN + snapshot,
                hashlib.sha256,
            ).digest()
            if (
                current is None
                or current[0]() is not identity
                or not hmac.compare_digest(current[1], expected)
            ):
                raise DeploymentControlBlocked(
                    "cleanup_transport_identity_invalid",
                    "issuer-private cleanup transport identity is unavailable or drifted",
                )


_CLEANUP_TRANSPORT_IDENTITY_REGISTRY = _CleanupTransportIdentityRegistry()
_CLEANUP_TRANSPORT_IDENTITY_SEAL = object()


def _cleanup_transport_identity_snapshot(identity: _CleanupTransportIdentity) -> bytes:
    return canonical_json_bytes(
        {
            "credential_fingerprint": identity.credential_fingerprint,
            "credential_ref": identity.credential_ref,
            "endpoint": identity.endpoint,
            "identity_digest": identity.identity_digest,
            "project_ref": identity.project_ref,
            "provider": identity.provider,
            "workspace_ref": identity.workspace_ref,
        }
    )


def _issue_cleanup_transport_identity(
    *,
    api_key: str,
    binding: InfrastructureCleanupBinding,
) -> _CleanupTransportIdentity:
    credential_ref = credential_ref_for_api_key(api_key)
    if credential_ref != binding.credential_ref:
        raise ValueError("Bailian API key does not match durable cleanup ownership")
    facts = {
        "credential_fingerprint": credential_ref.removeprefix("sha256:"),
        "credential_ref": binding.credential_ref,
        "endpoint": BAILIAN_DEPLOYMENT_ENDPOINT,
        "project_ref": binding.project_ref,
        "provider": "bailian",
        "workspace_ref": binding.workspace_ref,
    }
    digest = hashlib.sha256(
        _CLEANUP_TRANSPORT_IDENTITY_DOMAIN + canonical_json_bytes(facts)
    ).hexdigest()
    identity = object.__new__(_CleanupTransportIdentity)
    for name, value in {**facts, "identity_digest": digest}.items():
        object.__setattr__(identity, name, value)
    object.__setattr__(identity, "_seal", _CLEANUP_TRANSPORT_IDENTITY_SEAL)
    _CLEANUP_TRANSPORT_IDENTITY_REGISTRY.register(
        identity,
        _cleanup_transport_identity_snapshot(identity),
    )
    return identity


def _require_cleanup_transport_identity(
    identity: object,
) -> _CleanupTransportIdentity:
    if (
        type(identity) is not _CleanupTransportIdentity
        or identity._seal is not _CLEANUP_TRANSPORT_IDENTITY_SEAL
    ):
        raise DeploymentControlBlocked(
            "cleanup_transport_identity_invalid",
            "issuer-private cleanup transport identity is required",
        )
    _CLEANUP_TRANSPORT_IDENTITY_REGISTRY.require(
        identity,
        _cleanup_transport_identity_snapshot(identity),
    )
    return identity


class _ControllerRemoteReceiptObservation:
    """Fresh provider-detail observation produced only inside receipt finalization."""

    receipt: DeploymentReceipt
    remote_manifest: ProviderDeploymentManifest
    transport_identity: VerifiedDeploymentTransportIdentity
    run_identity: str
    purpose: str
    scope: str
    remote_manifest_digest: str
    observed_at: datetime
    expires_at: datetime
    authorization: ProvisioningAuthorization | ExistingDeploymentAdoptionAuthorization
    permit: InfrastructureCreatePermit | None
    trusted_authorities: Mapping[str, TrustedAuthority]
    _seal: object

    __slots__ = (
        "receipt",
        "remote_manifest",
        "transport_identity",
        "run_identity",
        "purpose",
        "scope",
        "remote_manifest_digest",
        "observed_at",
        "expires_at",
        "authorization",
        "permit",
        "trusted_authorities",
        "_seal",
    )

    def __init__(self) -> None:
        raise TypeError("controller remote observations cannot be caller-constructed")


class _ControllerReceiptPublicationProof:
    """Unforgeable-by-API proof of exact durable controller publication."""

    evidence: DeploymentReconciliationEvidenceV1
    receipt_artifact_bytes: bytes
    reconciliation_evidence_bytes: bytes
    transport_identity: VerifiedDeploymentTransportIdentity
    transport_identity_digest: str
    remote_manifest_digest: str
    run_identity: str
    purpose: str
    scope: str
    observed_at: datetime
    expires_at: datetime
    authorization: ProvisioningAuthorization | ExistingDeploymentAdoptionAuthorization
    permit: InfrastructureCreatePermit | None
    trusted_authorities: Mapping[str, TrustedAuthority]
    _seal: object

    __slots__ = (
        "evidence",
        "receipt_artifact_bytes",
        "reconciliation_evidence_bytes",
        "transport_identity",
        "transport_identity_digest",
        "remote_manifest_digest",
        "run_identity",
        "purpose",
        "scope",
        "observed_at",
        "expires_at",
        "authorization",
        "permit",
        "trusted_authorities",
        "_seal",
    )

    def __init__(self) -> None:
        raise TypeError("controller receipt publication proofs cannot be caller-constructed")


class TopologyReconciliationTargetV1(_ImmutableModel):
    boundary: Literal["strong", "weak"]
    receipt: DeploymentReceipt
    expected_remote_manifest: ProviderDeploymentManifest
    roles: tuple[Literal["annotator", "extractor", "judge"], ...]

    @model_validator(mode="after")
    def require_exact_boundary_evidence(self) -> TopologyReconciliationTargetV1:
        required_roles = ("annotator", "judge") if self.boundary == "strong" else ("extractor",)
        content = self.receipt.content
        manifest = self.expected_remote_manifest
        if self.roles != required_roles:
            raise ValueError("topology boundary roles are not canonical")
        if (
            content.deployed_model != manifest.deployed_model
            or content.base_model != manifest.base_model
            or content.receipt_plan != manifest.plan
            or content.input_tpm != manifest.input_tpm
            or content.output_tpm != manifest.output_tpm
            or content.gmt_create != manifest.gmt_create
            or content.gmt_modified != manifest.gmt_modified
            or content.workspace_ref != manifest.workspace_ref
            or content.operation_marker != manifest.operation_marker
            or content.deployment_suffix != manifest.deployment_suffix
            or content.remote_manifest_digest != _remote_manifest_digest(manifest)
        ):
            raise ValueError("topology target receipt does not match full manifest")
        return self


class TopologyReconciliationObservationBatchV1(_ImmutableModel):
    version: Literal["insurancekb.run-admission.topology-reconciliation-observation-batch.v1"]
    issuer: Literal["bailian-deployment-controller-v1"]
    run_identity: NonBlankStr
    purpose: NonBlankStr
    scope: NonBlankStr
    topology_digest: Sha256Digest
    plan_payload_hash: Sha256Digest
    provider_cap_evidence_digest: Sha256Digest
    provider_cap_approval_digest: Sha256Digest
    transport_identity_digest: Sha256Digest
    strong: TopologyReconciliationTargetV1
    weak: TopologyReconciliationTargetV1
    observed_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def require_complete_fresh_batch(self) -> TopologyReconciliationObservationBatchV1:
        if self.strong.boundary != "strong" or self.weak.boundary != "weak":
            raise ValueError("topology observation batch requires strong and weak boundaries")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("topology observation time must include a timezone")
        if self.expires_at <= self.observed_at:
            raise ValueError("topology observation expiry must follow observation")
        return self


class TopologyReconciliationObservationBatchArtifact(_ImmutableModel):
    batch: TopologyReconciliationObservationBatchV1
    batch_digest: Sha256Digest
    artifact_path: Path


class InfrastructureReserveReader(Protocol):
    def infrastructure_reserve(self, reserve_id: str) -> InfrastructureReserveSnapshot: ...


class InfrastructureCleanupBindingReader(Protocol):
    def infrastructure_cleanup_binding(
        self,
        reserve_id: str,
    ) -> InfrastructureCleanupBinding: ...


class DeploymentControlTransport(Protocol):
    endpoint: str
    identity: VerifiedDeploymentTransportIdentity

    def list_deployments(self, *, marker: str, suffix: str) -> bytes: ...

    def create_deployment(self, *, request_body: bytes, idempotency_key: str) -> bytes: ...

    def deployment_detail(self, *, deployed_model: str) -> bytes: ...


class DeploymentCleanupTransport(Protocol):
    endpoint: str
    identity: VerifiedDeploymentTransportIdentity

    def deployment_detail(self, *, deployed_model: str) -> bytes: ...

    def delete_deployment(self, *, deployed_model: str) -> bytes: ...


def _canonical_operation_bytes(
    run_identity: str,
    operation_id: str,
    ownership_nonce: str,
) -> bytes:
    return canonical_json_bytes(
        {
            "operation_id": operation_id,
            "ownership_nonce": ownership_nonce,
            "run_identity": run_identity,
        }
    )


def deterministic_operation_marker(
    run_identity: str,
    operation_id: str,
    ownership_nonce: str,
) -> str:
    digest = hashlib.sha256(
        _MARKER_DOMAIN + _canonical_operation_bytes(run_identity, operation_id, ownership_nonce)
    ).hexdigest()
    return f"ikb031-{digest[:24]}"


def deterministic_deployment_suffix(
    run_identity: str,
    operation_id: str,
    ownership_nonce: str,
) -> str:
    digest = hashlib.sha256(
        _SUFFIX_DOMAIN + _canonical_operation_bytes(run_identity, operation_id, ownership_nonce)
    ).hexdigest()
    return f"031-{digest[:16]}"


def _idempotency_key(run_identity: str, operation_id: str, ownership_nonce: str) -> str:
    return hashlib.sha256(
        _IDEMPOTENCY_DOMAIN
        + _canonical_operation_bytes(run_identity, operation_id, ownership_nonce)
    ).hexdigest()


def transport_workspace_evidence_digest(
    identity: VerifiedDeploymentTransportIdentity,
) -> str:
    return hashlib.sha256(
        _WORKSPACE_EVIDENCE_DOMAIN
        + canonical_json_bytes(
            {
                "credential_ref": identity.credential_ref,
                "project_ref": identity.project_ref,
                "workspace_ref": identity.workspace_ref,
            }
        )
    ).hexdigest()


def _remote_manifest_digest(manifest: ProviderDeploymentManifest) -> str:
    return hashlib.sha256(_REMOTE_MANIFEST_DOMAIN + canonical_json_bytes(manifest)).hexdigest()


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
                    "ownership_nonce",
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
    identity: VerifiedDeploymentTransportIdentity
    _cleanup_identity: _CleanupTransportIdentity | None = None

    def __init__(self) -> None:
        raise TypeError("production transport is owned by DeploymentController")

    @classmethod
    def _for_production(
        cls,
        *,
        api_key: str,
        provider_capability: object,
    ) -> BailianDeploymentHTTPTransport:
        identity = issue_verified_deployment_transport_identity(
            api_key=api_key,
            provider_capability=provider_capability,
        )
        instance = cls.__new__(cls)
        instance._initialize(
            api_key=api_key,
            identity=identity,
            transport=None,
            testing=False,
        )
        return instance

    @classmethod
    def _for_production_topology(
        cls,
        *,
        api_key: str,
        provider_capability: object,
    ) -> BailianDeploymentHTTPTransport:
        identity = issue_verified_topology_deployment_transport_identity(
            api_key=api_key,
            provider_capability=provider_capability,
        )
        instance = cls.__new__(cls)
        instance._initialize(
            api_key=api_key,
            identity=identity,
            transport=None,
            testing=False,
        )
        return instance

    @classmethod
    def _for_production_cleanup(
        cls,
        *,
        api_key: str,
        binding: InfrastructureCleanupBinding,
    ) -> BailianDeploymentHTTPTransport:
        identity = _issue_cleanup_transport_identity(
            api_key=api_key,
            binding=binding,
        )
        instance = cls.__new__(cls)
        instance._cleanup_identity = identity
        instance._initialize_client(api_key=api_key, transport=None)
        return instance

    @classmethod
    def _for_testing(
        cls,
        *,
        api_key: str,
        identity: VerifiedDeploymentTransportIdentity,
        transport: httpx.BaseTransport,
    ) -> BailianDeploymentHTTPTransport:
        instance = cls.__new__(cls)
        instance._initialize(
            api_key=api_key,
            identity=identity,
            transport=transport,
            testing=True,
        )
        return instance

    def _initialize(
        self,
        *,
        api_key: str,
        identity: VerifiedDeploymentTransportIdentity,
        transport: httpx.BaseTransport | None,
        testing: bool,
    ) -> None:
        if not isinstance(api_key, str) or not api_key or len(api_key) > 16 * 1024:
            raise ValueError("Bailian API key is missing or oversized")
        try:
            verified_identity = (
                _require_verified_deployment_transport_identity_for_testing(identity)
                if testing
                else require_verified_deployment_transport_identity(identity)
            )
        except AuthorizationVerificationError as exc:
            raise ValueError("verified deployment transport identity is required") from exc
        if (
            verified_identity.endpoint != self.endpoint
            or credential_ref_for_api_key(api_key) != verified_identity.credential_ref
        ):
            raise ValueError("Bailian API key does not match verified transport identity")
        self.identity = verified_identity
        self._cleanup_identity = None
        self._initialize_client(api_key=api_key, transport=transport)

    def _initialize_client(
        self,
        *,
        api_key: str,
        transport: httpx.BaseTransport | None,
    ) -> None:
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
        if method not in {"GET", "POST", "DELETE"}:
            raise DeploymentTransportError("B-layer transport method is not permitted")
        cleanup_identity = getattr(self, "_cleanup_identity", None)
        if (method == "DELETE" and cleanup_identity is None) or (
            method == "POST" and cleanup_identity is not None
        ):
            raise DeploymentTransportError("transport method is outside its bound mode")
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
                    raise DeploymentTransportError("compressed provider response is forbidden")
                body = bytearray()
                for chunk in response.iter_raw():
                    body.extend(chunk)
                    if len(body) > _MAX_CONTROL_RESPONSE_BYTES:
                        raise DeploymentTransportError("provider response exceeds size limit")
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
        _require_cleanup_transport_identity(self._cleanup_identity)
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
        digest = hashlib.sha256(domain + canonical_json_bytes(tuple(values))).hexdigest()
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

    def cleanup_intent_name(
        self,
        binding: InfrastructureCleanupBinding,
        slot: int,
    ) -> str:
        if type(slot) is not int or not 0 <= slot < _MAX_CLEANUP_JOURNAL_ARTIFACTS:
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe",
                "cleanup intent slot is unsafe",
            )
        return (
            f"{_cleanup_resource_digest(binding)}.{slot:02d}"
            ".cleanup-delete-intent.slot"
        )

    def cleanup_attempt_name(
        self,
        binding: InfrastructureCleanupBinding,
        slot: int,
    ) -> str:
        if type(slot) is not int or not 0 <= slot < _MAX_CLEANUP_JOURNAL_ARTIFACTS:
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe",
                "cleanup attempt slot is unsafe",
            )
        return (
            f"{_cleanup_resource_digest(binding)}.{slot:02d}"
            ".cleanup-delete-attempt.slot"
        )

    def cleanup_legacy_journal_name(
        self,
        binding: InfrastructureCleanupBinding,
        version: int,
    ) -> str:
        if type(version) is not int or version not in {1, 2}:
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe",
                "legacy cleanup journal version is unsafe",
            )
        return f"{_cleanup_resource_digest(binding)}.v{version}.cleanup-journal.json"

    def cleanup_terminal_journal_name(
        self,
        binding: InfrastructureCleanupBinding,
    ) -> str:
        return self._name(
            b"insurancekb.run-admission.cleanup-terminal-journal-name.v1\0",
            binding.run_identity,
            binding.operation_id,
            binding.reserve_id,
            binding.receipt_digest,
            suffix=".cleanup-terminal-journal.json",
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

    def names_with_suffix(self, suffix: str) -> tuple[str, ...]:
        if not suffix.startswith(".") or "/" in suffix:
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe",
                "deployment artifact suffix is unsafe",
            )
        try:
            names = os.listdir(self._root_fd)
        except OSError as exc:
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe",
                "deployment artifact directory cannot be listed",
            ) from exc
        return tuple(
            sorted(
                name
                for name in names
                if isinstance(name, str)
                and name.endswith(suffix)
                and "/" not in name
                and "\x00" not in name
            )
        )

    def names_with_prefix_and_suffix(
        self,
        prefix: str,
        suffix: str,
    ) -> tuple[str, ...]:
        if re.fullmatch(r"[0-9a-f]{64}\.", prefix) is None:
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe",
                "deployment artifact prefix is unsafe",
            )
        return tuple(
            name
            for name in self.names_with_suffix(suffix)
            if name.startswith(prefix)
        )

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

    def atomic_write_absent_on_failure(
        self,
        name: str,
        content: bytes,
    ) -> tuple[int, int] | None:
        """Publish a new content-addressed artifact or leave no named artifact."""

        existing = self.read(name)
        if existing is not None:
            if existing != content:
                raise DeploymentControlBlocked(
                    "operation_artifact_unsafe",
                    "content-addressed deployment artifact conflicts",
                )
            return None
        if not content or len(content) > _MAX_ARTIFACT_BYTES:
            raise DeploymentControlBlocked(
                "operation_artifact_unsafe", "deployment artifact size is invalid"
            )
        temporary = f".{name}.{secrets.token_hex(12)}.tmp"
        descriptor = -1
        staged = True
        publication_may_exist = False
        staging_identity: tuple[int, int] | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                _PRIVATE_FILE_MODE,
                dir_fd=self._root_fd,
            )
            metadata = os.fstat(descriptor)
            staging_identity = (metadata.st_dev, metadata.st_ino)
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
            publication_may_exist = True
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=self._root_fd,
                    dst_dir_fd=self._root_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                publication_may_exist = False
                os.unlink(temporary, dir_fd=self._root_fd)
                staged = False
                os.fsync(self._root_fd)
                raced = self.read(name)
                if raced != content:
                    raise DeploymentControlBlocked(
                        "operation_artifact_unsafe",
                        "content-addressed deployment artifact conflicts",
                    ) from None
                return None
            os.unlink(temporary, dir_fd=self._root_fd)
            staged = False
            os.fsync(self._root_fd)
        except BaseException as exc:
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except BaseException as cleanup_exc:
                    exc.add_note(
                        "staging descriptor cleanup conflict: "
                        f"{type(cleanup_exc).__name__}"
                    )
                descriptor = -1
            if staged:
                try:
                    os.unlink(temporary, dir_fd=self._root_fd)
                    staged = False
                    os.fsync(self._root_fd)
                except FileNotFoundError:
                    staged = False
                except BaseException as cleanup_exc:
                    exc.add_note(
                        "staging publication cleanup conflict: "
                        f"{type(cleanup_exc).__name__}"
                    )
            if publication_may_exist and staging_identity is not None:
                try:
                    self.remove_if_owned(name, staging_identity)
                except BaseException as cleanup_exc:
                    exc.add_note(
                        "publication cleanup conflict: "
                        f"{type(cleanup_exc).__name__}"
                    )
            if isinstance(exc, OSError):
                raise DeploymentControlBlocked(
                    "operation_artifact_unsafe", "deployment artifact write failed"
                ) from exc
            raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        assert staging_identity is not None
        try:
            if self.read(name) != content:
                raise DeploymentControlBlocked(
                    "operation_artifact_unsafe", "deployment artifact readback mismatch"
                )
        except BaseException as exc:
            try:
                self.remove_if_owned(name, staging_identity)
            except BaseException as cleanup_exc:
                exc.add_note(
                    "publication cleanup conflict: "
                    f"{type(cleanup_exc).__name__}"
                )
            raise
        return staging_identity

    def remove_if_owned(self, name: str, publication_identity: tuple[int, int] | None) -> bool:
        """Durably remove only the inode published by this invocation."""

        if publication_identity is None:
            return False
        quarantine = f".cleanup-{secrets.token_hex(16)}.tmp"
        try:
            # Move the current directory entry first.  The subsequent decision
            # applies to the inode that was atomically moved, never to a path
            # that can be replaced between a stat and an unlink.
            os.rename(
                name,
                quarantine,
                src_dir_fd=self._root_fd,
                dst_dir_fd=self._root_fd,
            )
        except BaseException as exc:
            try:
                os.stat(
                    quarantine,
                    dir_fd=self._root_fd,
                    follow_symlinks=False,
                )
            except OSError:
                if isinstance(exc, OSError):
                    return False
                raise
            try:
                self._resolve_quarantined_entry(
                    name,
                    quarantine,
                    publication_identity,
                )
            except BaseException as cleanup_exc:
                exc.add_note(
                    "quarantine cleanup conflict: "
                    f"{type(cleanup_exc).__name__}"
                )
            raise
        return self._resolve_quarantined_entry(name, quarantine, publication_identity)

    def _resolve_quarantined_entry(
        self,
        name: str,
        quarantine: str,
        publication_identity: tuple[int, int],
    ) -> bool:
        """Resolve a successfully quarantined entry without path-based deletion."""

        try:
            path_metadata = os.stat(
                quarantine,
                dir_fd=self._root_fd,
                follow_symlinks=False,
            )
        except OSError:
            self._restore_or_preserve_quarantined_entry(name, quarantine)
            return False
        if not stat.S_ISREG(path_metadata.st_mode):
            self._restore_or_preserve_quarantined_entry(name, quarantine)
            return False

        descriptor = -1
        try:
            try:
                descriptor = os.open(
                    quarantine,
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=self._root_fd,
                )
            except OSError:
                self._restore_or_preserve_quarantined_entry(name, quarantine)
                return False
            metadata = os.fstat(descriptor)
            owned = (
                stat.S_ISREG(metadata.st_mode)
                and metadata.st_uid == os.geteuid()
                and stat.S_IMODE(metadata.st_mode) == _PRIVATE_FILE_MODE
                and metadata.st_nlink == 1
                and (metadata.st_dev, metadata.st_ino) == publication_identity
            )
            if not owned:
                self._restore_or_preserve_quarantined_entry(name, quarantine)
                return False
            os.unlink(quarantine, dir_fd=self._root_fd)
            os.fsync(self._root_fd)
            return True
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _restore_or_preserve_quarantined_entry(self, name: str, quarantine: str) -> None:
        """Restore a foreign entry, or preserve it under an explicit conflict name."""

        try:
            os.link(
                quarantine,
                name,
                src_dir_fd=self._root_fd,
                dst_dir_fd=self._root_fd,
                follow_symlinks=False,
            )
        except OSError as exc:
            preserved = f".foreign-preserved-{secrets.token_hex(16)}.artifact"
            try:
                os.rename(
                    quarantine,
                    preserved,
                    src_dir_fd=self._root_fd,
                    dst_dir_fd=self._root_fd,
                )
                os.fsync(self._root_fd)
            except OSError as preserve_exc:
                raise DeploymentControlBlocked(
                    "operation_artifact_cleanup_conflict",
                    "foreign cleanup conflict could not be preserved",
                ) from preserve_exc
            raise DeploymentControlBlocked(
                "operation_artifact_cleanup_conflict",
                f"foreign cleanup conflict preserved as {preserved}",
            ) from exc
        os.unlink(quarantine, dir_fd=self._root_fd)
        os.fsync(self._root_fd)


class DeploymentController:
    """Single-operation orchestrator with durable at-most-once POST semantics."""

    def __init__(self) -> None:
        raise TypeError("use DeploymentController.for_production()")

    @classmethod
    def for_production_cleanup(
        cls,
        *,
        reserve_id: str,
    ) -> DeploymentController:
        """Build the fixed DELETE-only boundary from durable cleanup ownership."""

        api_key = os.environ.get(_PRODUCTION_API_KEY_ENV)
        if not isinstance(api_key, str) or not api_key:
            raise DeploymentControlBlocked(
                "deployment_credential_unavailable",
                "root-owned deployment credential is unavailable",
            )
        transport: BailianDeploymentHTTPTransport | None = None
        instance: DeploymentController | None = None
        try:
            reserve_reader = BudgetLedger(_PRODUCTION_BUDGET_LEDGER_PATH)
            binding = reserve_reader.infrastructure_cleanup_binding(reserve_id)
            observation_authenticator = _CleanupObservationAuthenticator.for_production(
                api_key
            )
            transport = BailianDeploymentHTTPTransport._for_production_cleanup(
                api_key=api_key,
                binding=binding,
            )
            instance = cls.__new__(cls)
            instance._initialize(
                run_root=_PRODUCTION_RUN_ROOT,
                reserve_reader=reserve_reader,
                transport=transport,
                clock=lambda: datetime.now(UTC),
                testing_sentinel=None,
                cleanup_observation_authenticator=observation_authenticator,
            )
            instance._production_cleanup_dependencies = (
                reserve_reader,
                transport,
                binding,
                observation_authenticator,
            )
        except (BudgetLedgerError, OSError, TypeError, ValueError) as exc:
            if instance is not None:
                instance.close()
            elif transport is not None:
                transport.close()
            raise DeploymentControlBlocked(
                "production_cleanup_controller_unavailable",
                "canonical production cleanup controller is unavailable",
            ) from exc
        except BaseException:
            if instance is not None:
                instance.close()
            elif transport is not None:
                transport.close()
            raise
        return instance

    def cleanup(
        self,
        *,
        authorization: DeploymentCleanupAuthorization,
        receipt_digest: str,
    ) -> CleanupControlResult:
        return self._cleanup(
            authorization=authorization,
            trusted_authorities=self._production_operational_authorities(),
            receipt_digest=receipt_digest,
        )

    @classmethod
    def for_production(
        cls,
        *,
        plan: RunAdmissionPlanPayload,
        expected_scope: str,
        reserve_id: str | None = None,
    ) -> DeploymentController:
        """Build the production controller from the fixed deployment boundary."""

        api_key = os.environ.get(_PRODUCTION_API_KEY_ENV)
        if not isinstance(api_key, str) or not api_key:
            raise DeploymentControlBlocked(
                "deployment_credential_unavailable",
                "root-owned deployment credential is unavailable",
            )
        transport: BailianDeploymentHTTPTransport | None = None
        instance: DeploymentController | None = None
        try:
            reserve_reader = BudgetLedger(_PRODUCTION_BUDGET_LEDGER_PATH)
            provider_capability: (
                VerifiedInfrastructureProviderCapCapability
                | VerifiedTopologyProviderCapCapability
            )
            if reserve_id is None:
                _topology, provider_capability, _weak_capability = (
                    cls._fresh_topology_provider_caps(
                        reserve_reader,
                        plan=plan,
                        expected_scope=expected_scope,
                    )
                )
            else:
                provider_capability = (
                    reserve_reader.require_fresh_infrastructure_provider_capability(
                        plan=plan,
                        expected_scope=expected_scope,
                        reserve_id=reserve_id,
                    )
                )
            transport = (
                BailianDeploymentHTTPTransport._for_production_topology(
                    api_key=api_key,
                    provider_capability=provider_capability,
                )
                if reserve_id is None
                else BailianDeploymentHTTPTransport._for_production(
                    api_key=api_key,
                    provider_capability=provider_capability,
                )
            )
            instance = cls.__new__(cls)
            instance._initialize(
                run_root=_PRODUCTION_RUN_ROOT,
                reserve_reader=reserve_reader,
                transport=transport,
                clock=lambda: datetime.now(UTC),
                testing_sentinel=None,
            )
            instance._production_dependencies = (
                reserve_reader,
                transport,
                "topology_refresh" if reserve_id is None else "provisioning",
                plan,
                expected_scope,
                reserve_id,
            )
        except (
            AuthorizationVerificationError,
            BudgetLedgerError,
            OSError,
            TypeError,
            ValueError,
        ) as exc:
            if instance is not None:
                instance.close()
            elif transport is not None:
                transport.close()
            raise DeploymentControlBlocked(
                "production_controller_unavailable",
                "canonical production deployment controller is unavailable",
            ) from exc
        except BaseException:
            if instance is not None:
                instance.close()
            elif transport is not None:
                transport.close()
            raise
        return instance

    @staticmethod
    def _fresh_topology_provider_caps(
        ledger: BudgetLedger,
        *,
        plan: RunAdmissionPlanPayload,
        expected_scope: str,
    ) -> tuple[
        VerifiedFinalTopology,
        VerifiedTopologyProviderCapCapability,
        VerifiedTopologyProviderCapCapability,
    ]:
        topology = ledger.require_fresh_final_topology(
            plan=plan,
            expected_scope=expected_scope,
        )
        strong_cap = ledger.require_fresh_topology_provider_capability(
            plan=plan,
            expected_scope=expected_scope,
            reserve_id=topology.strong.reserve_id,
        )
        weak_cap = ledger.require_fresh_topology_provider_capability(
            plan=plan,
            expected_scope=expected_scope,
            reserve_id=topology.weak.reserve_id,
        )
        topology_cap = (
            topology.provider,
            topology.currency,
            topology.workspace_ref,
            topology.project_ref,
            topology.credential_ref,
            topology.provider_cap_evidence_digest,
            topology.provider_cap_approval_digest,
            topology.provider_cap_coverage,
            topology.provider_cap_max_cost_minor_units,
            topology.provider_cap_expires_at,
        )
        for capability, deployment in (
            (strong_cap, topology.strong),
            (weak_cap, topology.weak),
        ):
            if (
                capability.topology_digest != topology.topology_digest
                or capability.run_identity != topology.run_identity
                or capability.purpose != topology.purpose
                or capability.scope != topology.scope
                or capability.reserve_id != deployment.reserve_id
                or capability.operation_id != deployment.operation_id
                or (
                    capability.provider,
                    capability.currency,
                    capability.workspace_ref,
                    capability.project_ref,
                    capability.credential_ref,
                    capability.evidence_digest,
                    capability.approval_digest,
                    capability.coverage,
                    capability.max_cost_minor_units,
                    capability.expires_at,
                )
                != topology_cap
            ):
                raise BudgetLedgerError(
                    "infrastructure provider cap has drifted from final topology"
                )
        return topology, strong_cap, weak_cap

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
            testing_sentinel=_TESTING_MODE_SENTINEL,
        )
        return instance

    def _initialize(
        self,
        *,
        run_root: Path,
        reserve_reader: InfrastructureReserveReader,
        transport: DeploymentControlTransport,
        clock: Callable[[], datetime],
        testing_sentinel: object | None,
        cleanup_observation_authenticator: _CleanupObservationAuthenticator | None = None,
    ) -> None:
        self._reserve_reader = reserve_reader
        self._transport = transport
        self._cleanup_reserve_reader = cast(
            InfrastructureCleanupBindingReader,
            reserve_reader,
        )
        self._cleanup_transport = cast(DeploymentCleanupTransport, transport)
        self._clock = clock
        self._testing_sentinel = testing_sentinel
        self._cleanup_observation_authenticator = (
            _CleanupObservationAuthenticator.for_testing()
            if testing_sentinel is _TESTING_MODE_SENTINEL
            else cleanup_observation_authenticator
        )
        self._cleanup_attempt_snapshot_seal = object()
        self._remote_observation_seal = object()
        self._receipt_publication_seal = object()
        self._closed = False
        self._production_dependencies: (
            tuple[
                BudgetLedger,
                BailianDeploymentHTTPTransport,
                Literal["provisioning", "topology_refresh"],
                RunAdmissionPlanPayload,
                str,
                str | None,
            ]
            | None
        ) = None
        self._production_cleanup_dependencies: (
            tuple[
                BudgetLedger,
                BailianDeploymentHTTPTransport,
                InfrastructureCleanupBinding,
                _CleanupObservationAuthenticator,
            ]
            | None
        ) = None
        self._store = _OperationStore(run_root)

    def __del__(self) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "_closed", True):
            return
        self._closed = True
        transport = getattr(self, "_transport", None)
        close_transport = getattr(transport, "close", None)
        try:
            if callable(close_transport):
                close_transport()
        finally:
            store = getattr(self, "_store", None)
            if isinstance(store, _OperationStore):
                store.close()

    def __enter__(self) -> DeploymentController:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @staticmethod
    def _production_operational_authorities() -> Mapping[str, TrustedAuthority]:
        try:
            from insurance_harness.goldenset.admission_cli import (
                _load_deployment_approval_configuration,
            )

            authorities, _budget_roles, _provenance_roles, _review_roles = (
                _load_deployment_approval_configuration()
            )
        except (OSError, PermissionError, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "trusted_authority_unavailable",
                "root-owned deployment trust configuration is unavailable",
            ) from exc
        if not authorities:
            raise DeploymentControlBlocked(
                "trusted_authority_unavailable",
                "root-owned deployment trust configuration is unavailable",
            )
        return authorities

    def _require_testing_mode(self) -> None:
        if self._testing_sentinel is not _TESTING_MODE_SENTINEL:
            raise DeploymentControlBlocked(
                "testing_seam_forbidden",
                "private deployment testing seam requires testing mode",
            )

    def _require_production_dependencies(self) -> None:
        owned = self._production_dependencies
        if (
            self._testing_sentinel is _TESTING_MODE_SENTINEL
            or owned is None
            or self._reserve_reader is not owned[0]
            or self._transport is not owned[1]
            or type(self._reserve_reader) is not BudgetLedger
            or type(self._transport) is not BailianDeploymentHTTPTransport
            or self._reserve_reader._db_path != _PRODUCTION_BUDGET_LEDGER_PATH
            or self._store.root != _PRODUCTION_RUN_ROOT
            or (owned[2] == "provisioning") != (owned[5] is not None)
        ):
            raise DeploymentControlBlocked(
                "production_dependency_invalid",
                "canonical production deployment dependencies have drifted",
            )
        try:
            fresh_cap: (
                VerifiedInfrastructureProviderCapCapability
                | VerifiedTopologyProviderCapCapability
            )
            if owned[2] == "provisioning":
                fresh_cap = owned[0].require_fresh_infrastructure_provider_capability(
                    plan=owned[3],
                    expected_scope=owned[4],
                    reserve_id=cast(str, owned[5]),
                )
            else:
                _topology, fresh_cap, _weak_cap = self._fresh_topology_provider_caps(
                    owned[0],
                    plan=owned[3],
                    expected_scope=owned[4],
                )
            identity = require_verified_deployment_transport_identity(owned[1].identity)
        except (AuthorizationVerificationError, BudgetLedgerError, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "production_provider_cap_invalid",
                "fresh root-owned provider cap is unavailable",
            ) from exc
        expected_cap_identity = (
            fresh_cap.provider,
            fresh_cap.currency,
            fresh_cap.workspace_ref,
            fresh_cap.project_ref,
            fresh_cap.credential_ref,
            fresh_cap.evidence_digest,
            fresh_cap.approval_digest,
            fresh_cap.coverage,
            fresh_cap.expires_at,
        )
        observed_cap_identity = (
            identity.provider,
            identity.currency,
            identity.workspace_ref,
            identity.project_ref,
            identity.credential_ref,
            identity.provider_cap_evidence_digest,
            identity.provider_cap_approval_digest,
            identity.coverage,
            identity.expires_at,
        )
        if observed_cap_identity != expected_cap_identity:
            raise DeploymentControlBlocked(
                "production_provider_cap_invalid",
                "deployment transport provider cap no longer matches root evidence",
            )

    def _require_production_mode(
        self,
        expected: Literal["provisioning", "topology_refresh"],
    ) -> None:
        owned = self._production_dependencies
        if owned is None or owned[2] != expected:
            raise DeploymentControlBlocked(
                "production_mode_mismatch",
                "production deployment controller mode does not permit this operation",
            )

    def _require_production_cleanup_dependencies(
        self,
        *,
        reserve_id: str,
    ) -> InfrastructureCleanupBinding:
        owned = self._production_cleanup_dependencies
        if (
            self._testing_sentinel is _TESTING_MODE_SENTINEL
            or owned is None
            or self._reserve_reader is not owned[0]
            or self._transport is not owned[1]
            or self._cleanup_observation_authenticator is not owned[3]
            or type(self._reserve_reader) is not BudgetLedger
            or type(self._transport) is not BailianDeploymentHTTPTransport
            or type(self._cleanup_observation_authenticator)
            is not _CleanupObservationAuthenticator
            or self._reserve_reader._db_path != _PRODUCTION_BUDGET_LEDGER_PATH
            or self._store.root != _PRODUCTION_RUN_ROOT
        ):
            raise DeploymentControlBlocked(
                "production_cleanup_dependency_invalid",
                "canonical production cleanup dependencies have drifted",
            )
        try:
            fresh = owned[0].infrastructure_cleanup_binding(reserve_id)
            identity = _require_cleanup_transport_identity(
                getattr(owned[1], "_cleanup_identity", None)
            )
        except (BudgetLedgerError, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "production_cleanup_ownership_invalid",
                "durable cleanup ownership is unavailable",
            ) from exc
        if (
            fresh != owned[2]
            or identity.endpoint != BAILIAN_DEPLOYMENT_ENDPOINT
            or identity.workspace_ref != fresh.workspace_ref
            or identity.project_ref != fresh.project_ref
            or identity.credential_ref != fresh.credential_ref
        ):
            raise DeploymentControlBlocked(
                "production_cleanup_ownership_invalid",
                "durable cleanup ownership has drifted",
            )
        return fresh

    def _cleanup_transport_digest(self) -> str:
        if self._testing_sentinel is _TESTING_MODE_SENTINEL:
            identity = _require_verified_deployment_transport_identity_for_testing(
                self._transport.identity
            )
            return identity.identity_digest
        owned = self._production_cleanup_dependencies
        if owned is None:
            raise DeploymentControlBlocked(
                "production_cleanup_dependency_invalid",
                "canonical production cleanup dependencies are unavailable",
            )
        return _require_cleanup_transport_identity(
            getattr(owned[1], "_cleanup_identity", None)
        ).identity_digest

    def _require_cleanup_observation_proof(
        self,
        receipt: CleanupReceipt,
        *,
        causal_intent_snapshot: CleanupDeleteIntentSlot | None,
        causal_attempt_snapshot: DurableDeleteAttemptEvidence | None,
    ) -> None:
        authenticator = self._cleanup_observation_authenticator
        if type(authenticator) is not _CleanupObservationAuthenticator:
            raise DeploymentControlBlocked(
                "cleanup_receipt_invalid",
                "terminal cleanup observation authenticator is unavailable",
            )
        if receipt.cleanup_transport_identity_digest != self._cleanup_transport_digest():
            raise DeploymentControlBlocked(
                "cleanup_receipt_invalid",
                "terminal cleanup transport identity has drifted",
            )
        authenticator.require(
            _cleanup_observation_bytes(
                binding=receipt.binding,
                cleanup_authorization_digest=receipt.cleanup_authorization_digest,
                causal_delete_attempt_digest=receipt.causal_delete_attempt_digest,
                terminal_state=receipt.terminal_state,
                observed_at=receipt.observed_at,
                cleanup_transport_identity_digest=(
                    receipt.cleanup_transport_identity_digest
                ),
                causal_intent_snapshot=causal_intent_snapshot,
                causal_attempt_snapshot=causal_attempt_snapshot,
            ),
            receipt.observation_proof,
        )

    def provision(
        self,
        *,
        authorization: ProvisioningAuthorization,
        permit: InfrastructureCreatePermit,
    ) -> DeploymentControlResult:
        self._require_production_dependencies()
        self._require_production_mode("provisioning")
        self._require_production_provisioning_binding(
            authorization=authorization,
            permit=permit,
        )
        return self._provision(
            authorization=authorization,
            permit=permit,
            trusted_authorities=self._production_operational_authorities(),
        )

    def reconcile_existing_adoption(
        self,
        *,
        authorization: ExistingDeploymentAdoptionAuthorization,
    ) -> DeploymentAdoptionResult:
        self._require_production_dependencies()
        self._require_production_mode("provisioning")
        return self._reconcile_existing_adoption(
            authorization=authorization,
            trusted_authorities=self._production_operational_authorities(),
        )

    def _cleanup_for_testing(
        self,
        *,
        authorization: DeploymentCleanupAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
        receipt_digest: str,
    ) -> CleanupControlResult:
        self._require_testing_mode()
        return self._cleanup(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
            receipt_digest=receipt_digest,
        )

    def _cleanup(
        self,
        *,
        authorization: DeploymentCleanupAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
        receipt_digest: str,
    ) -> CleanupControlResult:
        authorization_digest, binding, artifact = self._verify_cleanup_gate(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
            receipt_digest=receipt_digest,
        )
        with self._store.run_lock(binding.run_identity):
            authorization_digest, binding, artifact = self._verify_cleanup_gate(
                authorization=authorization,
                trusted_authorities=trusted_authorities,
                receipt_digest=receipt_digest,
            )
            self._reject_untrusted_legacy_cleanup_journals(binding)
            restored = self._restore_cleanup_terminal(
                binding,
                authorization=authorization,
                trusted_authorities=trusted_authorities,
                receipt_digest=receipt_digest,
            )
            if restored is not None:
                return restored
            intent = CleanupDeleteIntent(
                binding=binding,
                authorization=authorization,
                authorization_digest=authorization_digest,
                authorization_issued_at=authorization.payload.issued_at,
            )
            intent_bytes = canonical_json_bytes(intent)
            intent_digest = hashlib.sha256(
                _CLEANUP_DELETE_INTENT_DOMAIN + intent_bytes
            ).hexdigest()
            intent_slot = CleanupDeleteIntentSlot(
                intent=intent,
                intent_digest=intent_digest,
            )
            intent_slot_bytes = canonical_json_bytes(intent_slot)
            prior_intents, first_empty_slot = self._load_cleanup_delete_intents(
                binding=binding,
                trusted_authorities=trusted_authorities,
            )
            prior_attempts = self._load_cleanup_delete_attempts(
                binding=binding,
                intents=prior_intents,
            )
            existing_intent = next(
                (
                    existing.intent
                    for digest, existing, _slot_index in prior_intents
                    if digest == intent_digest
                ),
                None,
            )
            if existing_intent is None and first_empty_slot is None:
                raise DeploymentControlBlocked(
                    "cleanup_journal_limit_exceeded",
                    "cleanup delete intent slots are full",
                )
            authorization_digest, binding, artifact = self._verify_cleanup_gate(
                authorization=authorization,
                trusted_authorities=trusted_authorities,
                receipt_digest=receipt_digest,
            )
            try:
                observed = _parse_manifest(
                    self._transport.deployment_detail(
                        deployed_model=binding.deployed_model
                    )
                )
            except DeploymentNotFound:
                authorization_digest, binding, _artifact = self._verify_cleanup_gate(
                    authorization=authorization,
                    trusted_authorities=trusted_authorities,
                    receipt_digest=receipt_digest,
                )
                verified_attempt = (
                    self._reload_cleanup_attempt_snapshot(
                        prior_attempts[-1],
                        binding=binding,
                        trusted_authorities=trusted_authorities,
                    )
                    if prior_attempts
                    else None
                )
                return self._publish_cleanup_terminal(
                    binding=binding,
                    authorization_digest=authorization_digest,
                    verified_attempt=verified_attempt,
                    terminal_state=(
                        "absent_404"
                        if prior_attempts
                        else "already_absent_404"
                    ),
                    authorization=authorization,
                    trusted_authorities=trusted_authorities,
                    receipt_digest=receipt_digest,
                )
            except (DeploymentTransportError, TimeoutError) as exc:
                raise DeploymentControlBlocked(
                    "cleanup_remote_unverified",
                    "cleanup detail could not prove the provider state",
                ) from exc
            self._require_cleanup_manifest(observed=observed, artifact=artifact)
            if existing_intent is not None:
                raise DeploymentControlBlocked(
                    "billing_stop_unverified",
                    "this cleanup authorization already has an uncertain delete attempt",
                )
            authorization_digest, binding, artifact = self._verify_cleanup_gate(
                authorization=authorization,
                trusted_authorities=trusted_authorities,
                receipt_digest=receipt_digest,
            )
            self._require_cleanup_manifest(observed=observed, artifact=artifact)
            assert first_empty_slot is not None
            self._store.atomic_write_absent_on_failure(
                self._store.cleanup_intent_name(binding, first_empty_slot),
                intent_slot_bytes,
            )
            authorization_digest, binding, artifact = self._verify_cleanup_gate(
                authorization=authorization,
                trusted_authorities=trusted_authorities,
                receipt_digest=receipt_digest,
            )
            self._require_cleanup_manifest(observed=observed, artifact=artifact)
            completed_attempt: _VerifiedDeleteAttemptSnapshot | None = None
            try:
                self._cleanup_transport.delete_deployment(
                    deployed_model=binding.deployed_model
                )
            except (DeploymentNotFound, DeploymentTransportError, TimeoutError):
                pass
            else:
                attempted_at = self._clock()
                authorization_digest, binding, _artifact = self._verify_cleanup_gate(
                    authorization=authorization,
                    trusted_authorities=trusted_authorities,
                    receipt_digest=receipt_digest,
                )
                completed_attempt = self._publish_completed_delete_attempt(
                    binding=binding,
                    intent_slot=intent_slot,
                    attempted_at=attempted_at,
                    slot_index=first_empty_slot,
                    trusted_authorities=trusted_authorities,
                )
            authorization_digest, binding, _artifact = self._verify_cleanup_gate(
                authorization=authorization,
                trusted_authorities=trusted_authorities,
                receipt_digest=receipt_digest,
            )
            try:
                terminal = _parse_manifest(
                    self._transport.deployment_detail(
                        deployed_model=binding.deployed_model
                    )
                )
            except DeploymentNotFound:
                authorization_digest, binding, _artifact = self._verify_cleanup_gate(
                    authorization=authorization,
                    trusted_authorities=trusted_authorities,
                    receipt_digest=receipt_digest,
                )
                verified_attempt = (
                    self._reload_cleanup_attempt_snapshot(
                        completed_attempt,
                        binding=binding,
                        trusted_authorities=trusted_authorities,
                    )
                    if completed_attempt is not None
                    else None
                )
                return self._publish_cleanup_terminal(
                    binding=binding,
                    authorization_digest=authorization_digest,
                    verified_attempt=verified_attempt,
                    terminal_state=(
                        "absent_404"
                        if completed_attempt is not None
                        else "already_absent_404"
                    ),
                    authorization=authorization,
                    trusted_authorities=trusted_authorities,
                    receipt_digest=receipt_digest,
                )
            except (DeploymentTransportError, TimeoutError) as exc:
                raise DeploymentControlBlocked(
                    "billing_stop_unverified",
                    "cleanup reconciliation is uncertain",
                ) from exc
            self._require_cleanup_manifest(observed=terminal, artifact=artifact)
            raise DeploymentControlBlocked(
                "billing_stop_unverified",
                "cleanup did not reach terminal provider absence",
            )

    def _verify_cleanup_gate(
        self,
        *,
        authorization: DeploymentCleanupAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
        receipt_digest: str,
    ) -> tuple[str, InfrastructureCleanupBinding, DeploymentReceiptArtifact]:
        try:
            if (
                type(authorization) is not DeploymentCleanupAuthorization
                or set(authorization.__dict__) != set(type(authorization).model_fields)
                or type(authorization.payload)
                is not DeploymentCleanupAuthorizationPayload
            ):
                raise TypeError("cleanup authorization type is not exact")
            validated = DeploymentCleanupAuthorization.model_validate(
                authorization.model_dump(mode="python", round_trip=True)
            )
            if canonical_json_bytes(validated) != canonical_json_bytes(authorization):
                raise ValueError("cleanup authorization snapshot changed")
            now = self._clock()
            digest = verify_cleanup_authorization(
                validated,
                trusted_authorities=trusted_authorities,
                now=now,
            )
            payload = validated.payload
            binding = (
                self._require_production_cleanup_dependencies(
                    reserve_id=payload.reserve_id
                )
                if self._testing_sentinel is not _TESTING_MODE_SENTINEL
                else self._cleanup_reserve_reader.infrastructure_cleanup_binding(
                    payload.reserve_id
                )
            )
            if (
                receipt_digest != binding.receipt_digest
                or (
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
                    payload.expected_remote_manifest_digest,
                    payload.cleanup_deadline,
                )
                != (
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
                    binding.remote_manifest_digest,
                    binding.cleanup_deadline,
                )
            ):
                raise ValueError("cleanup authorization does not match durable ownership")
            if self._transport.endpoint != BAILIAN_DEPLOYMENT_ENDPOINT:
                raise ValueError("cleanup endpoint drifted")
            if self._testing_sentinel is _TESTING_MODE_SENTINEL:
                identity = _require_verified_deployment_transport_identity_for_testing(
                    self._transport.identity
                )
                if (
                    identity.workspace_ref,
                    identity.project_ref,
                    identity.credential_ref,
                ) != (
                    binding.workspace_ref,
                    binding.project_ref,
                    binding.credential_ref,
                ):
                    raise ValueError("cleanup transport identity drifted")
            else:
                _require_cleanup_transport_identity(
                    getattr(self._transport, "_cleanup_identity", None)
                )
            artifact = self._load_cleanup_source_artifacts(binding)
        except (
            AttributeError,
            AuthorizationVerificationError,
            BudgetLedgerError,
            TypeError,
            ValueError,
        ) as exc:
            raise DeploymentControlBlocked(
                "cleanup_authorization_invalid",
                "independent deployment cleanup authorization is invalid",
            ) from exc
        return digest, binding, artifact

    def _load_cleanup_source_artifacts(
        self,
        binding: InfrastructureCleanupBinding,
    ) -> DeploymentReceiptArtifact:
        receipt_raw = self._store.read(f"{binding.receipt_digest}.receipt.json")
        reconciliation_raw = self._store.read(
            f"{binding.reconciliation_digest}.receipt-reconciliation.json"
        )
        if receipt_raw is None or reconciliation_raw is None:
            raise ValueError("cleanup ownership artifacts are missing")
        artifact = DeploymentReceiptArtifact.model_validate_json(receipt_raw)
        reconciliation = DeploymentReconciliationEvidenceV1.model_validate_json(
            reconciliation_raw
        )
        if (
            canonical_json_bytes(artifact) != receipt_raw
            or canonical_json_bytes(reconciliation) != reconciliation_raw
            or artifact.receipt.content_digest != binding.receipt_digest
            or artifact.remote_manifest_digest != binding.remote_manifest_digest
            or reconciliation.reconciliation_digest != binding.reconciliation_digest
            or reconciliation.transport_identity_digest
            != binding.transport_identity_digest
            or reconciliation.receipt != artifact.receipt
            or reconciliation.remote_manifest != artifact.remote_manifest
            or reconciliation.run_identity != binding.run_identity
            or reconciliation.purpose != binding.purpose
            or reconciliation.scope != binding.scope
            or reconciliation.operation_id != binding.operation_id
            or reconciliation.reserve_id != binding.reserve_id
            or reconciliation.workspace_ref != binding.workspace_ref
            or reconciliation.project_ref != binding.project_ref
            or reconciliation.credential_ref != binding.credential_ref
            or reconciliation.remote_manifest_digest
            != binding.remote_manifest_digest
        ):
            raise ValueError("cleanup ownership artifacts have drifted")
        return artifact

    def _load_cleanup_delete_intents(
        self,
        *,
        binding: InfrastructureCleanupBinding,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> tuple[tuple[tuple[str, CleanupDeleteIntentSlot, int], ...], int | None]:
        found: list[tuple[str, CleanupDeleteIntentSlot, int]] = []
        first_empty_slot: int | None = None
        for slot_index in range(_MAX_CLEANUP_JOURNAL_ARTIFACTS):
            name = self._store.cleanup_intent_name(binding, slot_index)
            raw = self._store.read(name)
            if raw is None:
                if first_empty_slot is None:
                    first_empty_slot = slot_index
                continue
            try:
                slot = CleanupDeleteIntentSlot.model_validate_json(raw)
                intent = slot.intent
                digest = slot.intent_digest
                if (
                    canonical_json_bytes(slot) != raw
                    or cleanup_authorization_digest(intent.authorization)
                    != intent.authorization_digest
                    or intent.authorization.payload.issued_at
                    != intent.authorization_issued_at
                ):
                    raise ValueError("cleanup delete intent is noncanonical")
                verify_cleanup_authorization(
                    intent.authorization,
                    trusted_authorities=trusted_authorities,
                    now=intent.authorization.payload.issued_at,
                )
            except (AuthorizationVerificationError, TypeError, ValueError) as exc:
                raise DeploymentControlBlocked(
                    "cleanup_journal_invalid",
                    "cleanup delete intent is invalid",
                ) from exc
            same_resource_key = (
                intent.binding.run_identity,
                intent.binding.operation_id,
                intent.binding.reserve_id,
                intent.binding.receipt_digest,
            ) == (
                binding.run_identity,
                binding.operation_id,
                binding.reserve_id,
                binding.receipt_digest,
            )
            if same_resource_key and intent.binding != binding:
                raise DeploymentControlBlocked(
                    "cleanup_journal_conflict",
                    "cleanup delete intent conflicts with durable ownership",
                )
            if intent.binding == binding:
                found.append((digest, slot, slot_index))
        found.sort(
            key=lambda item: (
                item[1].intent.authorization_issued_at,
                item[0],
            )
        )
        return tuple(found), first_empty_slot

    def _load_cleanup_delete_attempts(
        self,
        *,
        binding: InfrastructureCleanupBinding,
        intents: tuple[tuple[str, CleanupDeleteIntentSlot, int], ...],
    ) -> tuple[_VerifiedDeleteAttemptSnapshot, ...]:
        intents_by_slot = {
            slot_index: (intent_digest, intent_slot)
            for intent_digest, intent_slot, slot_index in intents
        }
        found: list[_VerifiedDeleteAttemptSnapshot] = []
        authenticator = self._cleanup_observation_authenticator
        if type(authenticator) is not _CleanupObservationAuthenticator:
            raise DeploymentControlBlocked(
                "cleanup_attempt_invalid",
                "completed cleanup attempt authenticator is unavailable",
            )
        transport_digest = self._cleanup_transport_digest()
        for slot_index in range(_MAX_CLEANUP_JOURNAL_ARTIFACTS):
            raw = self._store.read(
                self._store.cleanup_attempt_name(binding, slot_index)
            )
            if raw is None:
                continue
            try:
                attempt = DurableDeleteAttemptEvidence.model_validate_json(raw)
                paired = intents_by_slot.get(slot_index)
                attempt_bytes = _cleanup_delete_attempt_bytes(
                    binding=attempt.binding,
                    intent_digest=attempt.intent_digest,
                    cleanup_authorization_digest=(
                        attempt.cleanup_authorization_digest
                    ),
                    cleanup_transport_identity_digest=(
                        attempt.cleanup_transport_identity_digest
                    ),
                    attempted_at=attempt.attempted_at,
                )
                if (
                    canonical_json_bytes(attempt) != raw
                    or paired is None
                    or attempt.binding != binding
                    or attempt.intent_digest != paired[0]
                    or attempt.cleanup_authorization_digest
                    != paired[1].intent.authorization_digest
                    or attempt.cleanup_transport_identity_digest != transport_digest
                    or attempt.attempted_at
                    < paired[1].intent.authorization_issued_at
                ):
                    raise ValueError("completed cleanup attempt is not exact")
                authenticator.require_attempt(attempt_bytes, attempt.attempt_proof)
            except (TypeError, ValueError) as exc:
                raise DeploymentControlBlocked(
                    "cleanup_attempt_invalid",
                    "completed cleanup attempt is invalid",
                ) from exc
            digest = hashlib.sha256(
                _CLEANUP_DELETE_ATTEMPT_DOMAIN + raw
            ).hexdigest()
            snapshot = object.__new__(_VerifiedDeleteAttemptSnapshot)
            object.__setattr__(snapshot, "intent_slot", paired[1])
            object.__setattr__(snapshot, "attempt", attempt)
            object.__setattr__(snapshot, "attempt_digest", digest)
            object.__setattr__(snapshot, "slot_index", slot_index)
            object.__setattr__(
                snapshot,
                "_seal",
                self._cleanup_attempt_snapshot_seal,
            )
            found.append(snapshot)
        found.sort(
            key=lambda item: (item.attempt.attempted_at, item.attempt_digest)
        )
        return tuple(found)

    def _verify_cleanup_attempt_evidence(
        self,
        *,
        binding: InfrastructureCleanupBinding,
        intent_slot: CleanupDeleteIntentSlot,
        attempt: DurableDeleteAttemptEvidence,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> str:
        authenticator = self._cleanup_observation_authenticator
        if type(authenticator) is not _CleanupObservationAuthenticator:
            raise DeploymentControlBlocked(
                "cleanup_attempt_invalid",
                "completed cleanup attempt authenticator is unavailable",
            )
        try:
            validated_slot = CleanupDeleteIntentSlot.model_validate(
                intent_slot.model_dump(mode="python", round_trip=True)
            )
            validated_attempt = DurableDeleteAttemptEvidence.model_validate(
                attempt.model_dump(mode="python", round_trip=True)
            )
            intent = validated_slot.intent
            attempt_bytes = _cleanup_delete_attempt_bytes(
                binding=validated_attempt.binding,
                intent_digest=validated_attempt.intent_digest,
                cleanup_authorization_digest=(
                    validated_attempt.cleanup_authorization_digest
                ),
                cleanup_transport_identity_digest=(
                    validated_attempt.cleanup_transport_identity_digest
                ),
                attempted_at=validated_attempt.attempted_at,
            )
            if (
                canonical_json_bytes(validated_slot)
                != canonical_json_bytes(intent_slot)
                or canonical_json_bytes(validated_attempt)
                != canonical_json_bytes(attempt)
                or cleanup_authorization_digest(intent.authorization)
                != intent.authorization_digest
                or intent.authorization.payload.issued_at
                != intent.authorization_issued_at
                or intent.binding != binding
                or validated_attempt.binding != binding
                or validated_attempt.intent_digest != validated_slot.intent_digest
                or validated_attempt.cleanup_authorization_digest
                != intent.authorization_digest
                or validated_attempt.cleanup_transport_identity_digest
                != self._cleanup_transport_digest()
                or validated_attempt.attempted_at
                < intent.authorization_issued_at
            ):
                raise ValueError("completed cleanup attempt is not exact")
            verify_cleanup_authorization(
                intent.authorization,
                trusted_authorities=trusted_authorities,
                now=intent.authorization_issued_at,
            )
            authenticator.require_attempt(
                attempt_bytes,
                validated_attempt.attempt_proof,
            )
        except (
            AttributeError,
            AuthorizationVerificationError,
            TypeError,
            ValueError,
        ) as exc:
            raise DeploymentControlBlocked(
                "cleanup_attempt_invalid",
                "completed cleanup attempt is invalid",
            ) from exc
        return hashlib.sha256(
            _CLEANUP_DELETE_ATTEMPT_DOMAIN
            + canonical_json_bytes(validated_attempt)
        ).hexdigest()

    def _read_cleanup_attempt_snapshot(
        self,
        *,
        binding: InfrastructureCleanupBinding,
        slot_index: int,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> _VerifiedDeleteAttemptSnapshot:
        try:
            intent_raw = self._store.read(
                self._store.cleanup_intent_name(binding, slot_index)
            )
            attempt_raw = self._store.read(
                self._store.cleanup_attempt_name(binding, slot_index)
            )
            if intent_raw is None or attempt_raw is None:
                raise ValueError("paired cleanup attempt artifacts are missing")
            intent_slot = CleanupDeleteIntentSlot.model_validate_json(intent_raw)
            attempt = DurableDeleteAttemptEvidence.model_validate_json(attempt_raw)
            if (
                canonical_json_bytes(intent_slot) != intent_raw
                or canonical_json_bytes(attempt) != attempt_raw
            ):
                raise ValueError("paired cleanup attempt artifacts are noncanonical")
            digest = self._verify_cleanup_attempt_evidence(
                binding=binding,
                intent_slot=intent_slot,
                attempt=attempt,
                trusted_authorities=trusted_authorities,
            )
        except DeploymentControlBlocked:
            raise
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "cleanup_attempt_invalid",
                "paired cleanup attempt artifacts are invalid",
            ) from exc
        snapshot = object.__new__(_VerifiedDeleteAttemptSnapshot)
        object.__setattr__(snapshot, "intent_slot", intent_slot)
        object.__setattr__(snapshot, "attempt", attempt)
        object.__setattr__(snapshot, "attempt_digest", digest)
        object.__setattr__(snapshot, "slot_index", slot_index)
        object.__setattr__(
            snapshot,
            "_seal",
            self._cleanup_attempt_snapshot_seal,
        )
        return snapshot

    def _require_verified_cleanup_attempt_snapshot(
        self,
        snapshot: _VerifiedDeleteAttemptSnapshot,
        *,
        binding: InfrastructureCleanupBinding,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> None:
        if (
            type(snapshot) is not _VerifiedDeleteAttemptSnapshot
            or snapshot._seal is not self._cleanup_attempt_snapshot_seal
            or not 0 <= snapshot.slot_index < _MAX_CLEANUP_JOURNAL_ARTIFACTS
        ):
            raise DeploymentControlBlocked(
                "cleanup_attempt_invalid",
                "verified cleanup attempt snapshot is invalid",
            )
        digest = self._verify_cleanup_attempt_evidence(
            binding=binding,
            intent_slot=snapshot.intent_slot,
            attempt=snapshot.attempt,
            trusted_authorities=trusted_authorities,
        )
        if digest != snapshot.attempt_digest:
            raise DeploymentControlBlocked(
                "cleanup_attempt_invalid",
                "verified cleanup attempt snapshot has drifted",
            )

    def _reload_cleanup_attempt_snapshot(
        self,
        snapshot: _VerifiedDeleteAttemptSnapshot,
        *,
        binding: InfrastructureCleanupBinding,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> _VerifiedDeleteAttemptSnapshot:
        self._require_verified_cleanup_attempt_snapshot(
            snapshot,
            binding=binding,
            trusted_authorities=trusted_authorities,
        )
        fresh = self._read_cleanup_attempt_snapshot(
            binding=binding,
            slot_index=snapshot.slot_index,
            trusted_authorities=trusted_authorities,
        )
        if (
            fresh.intent_slot != snapshot.intent_slot
            or fresh.attempt != snapshot.attempt
            or fresh.attempt_digest != snapshot.attempt_digest
        ):
            raise DeploymentControlBlocked(
                "cleanup_attempt_invalid",
                "paired cleanup attempt snapshot has drifted",
            )
        return fresh

    def _reject_untrusted_legacy_cleanup_journals(
        self,
        binding: InfrastructureCleanupBinding,
    ) -> None:
        for version in (1, 2):
            legacy = self._store.read(
                self._store.cleanup_legacy_journal_name(binding, version)
            )
            if legacy is not None:
                raise DeploymentControlBlocked(
                    "cleanup_journal_legacy_untrusted",
                    "legacy cleanup journal lacks trusted causal authorization evidence",
                )

    @staticmethod
    def _require_cleanup_manifest(
        *,
        observed: ProviderDeploymentManifest,
        artifact: DeploymentReceiptArtifact,
    ) -> None:
        if (
            observed != artifact.remote_manifest
            or observed.status != "RUNNING"
            or _remote_manifest_digest(observed) != artifact.remote_manifest_digest
        ):
            raise DeploymentControlBlocked(
                "cleanup_manifest_mismatch",
                "remote manifest changed before cleanup",
            )

    def _publish_completed_delete_attempt(
        self,
        *,
        binding: InfrastructureCleanupBinding,
        intent_slot: CleanupDeleteIntentSlot,
        attempted_at: datetime,
        slot_index: int,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> _VerifiedDeleteAttemptSnapshot:
        authenticator = self._cleanup_observation_authenticator
        if type(authenticator) is not _CleanupObservationAuthenticator:
            raise DeploymentControlBlocked(
                "cleanup_attempt_invalid",
                "completed cleanup attempt authenticator is unavailable",
            )
        transport_digest = self._cleanup_transport_digest()
        attempt_facts = _cleanup_delete_attempt_bytes(
            binding=binding,
            intent_digest=intent_slot.intent_digest,
            cleanup_authorization_digest=(
                intent_slot.intent.authorization_digest
            ),
            cleanup_transport_identity_digest=transport_digest,
            attempted_at=attempted_at,
        )
        attempt = DurableDeleteAttemptEvidence(
            binding=binding,
            intent_digest=intent_slot.intent_digest,
            cleanup_authorization_digest=(
                intent_slot.intent.authorization_digest
            ),
            cleanup_transport_identity_digest=transport_digest,
            attempted_at=attempted_at,
            attempt_proof=authenticator.attempt_proof(attempt_facts),
        )
        attempt_bytes = canonical_json_bytes(attempt)
        name = self._store.cleanup_attempt_name(binding, slot_index)
        self._store.atomic_write_absent_on_failure(name, attempt_bytes)
        if self._store.read(name) != attempt_bytes:
            raise DeploymentControlBlocked(
                "cleanup_attempt_invalid",
                "completed cleanup attempt readback drifted",
            )
        authenticator.require_attempt(attempt_facts, attempt.attempt_proof)
        snapshot = self._read_cleanup_attempt_snapshot(
            binding=binding,
            slot_index=slot_index,
            trusted_authorities=trusted_authorities,
        )
        if snapshot.intent_slot != intent_slot or snapshot.attempt != attempt:
            raise DeploymentControlBlocked(
                "cleanup_attempt_invalid",
                "completed cleanup attempt readback changed",
            )
        return snapshot

    def _publish_cleanup_terminal(
        self,
        *,
        binding: InfrastructureCleanupBinding,
        authorization_digest: str,
        verified_attempt: _VerifiedDeleteAttemptSnapshot | None,
        terminal_state: Literal["absent_404", "already_absent_404"],
        authorization: DeploymentCleanupAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
        receipt_digest: str,
    ) -> CleanupControlResult:
        if verified_attempt is not None:
            self._require_verified_cleanup_attempt_snapshot(
                verified_attempt,
                binding=binding,
                trusted_authorities=trusted_authorities,
            )
        attempt_digest = (
            verified_attempt.attempt_digest
            if verified_attempt is not None
            else None
        )
        causal_intent_snapshot = (
            verified_attempt.intent_slot
            if verified_attempt is not None
            else None
        )
        causal_attempt_snapshot = (
            verified_attempt.attempt
            if verified_attempt is not None
            else None
        )
        observed_at = self._clock()
        cleanup_transport_identity_digest = self._cleanup_transport_digest()
        authenticator = self._cleanup_observation_authenticator
        if type(authenticator) is not _CleanupObservationAuthenticator:
            raise DeploymentControlBlocked(
                "cleanup_receipt_invalid",
                "terminal cleanup observation authenticator is unavailable",
            )
        observation = _cleanup_observation_bytes(
            binding=binding,
            cleanup_authorization_digest=authorization_digest,
            causal_delete_attempt_digest=attempt_digest,
            terminal_state=terminal_state,
            observed_at=observed_at,
            cleanup_transport_identity_digest=cleanup_transport_identity_digest,
            causal_intent_snapshot=causal_intent_snapshot,
            causal_attempt_snapshot=causal_attempt_snapshot,
        )
        receipt = CleanupReceipt(
            binding=binding,
            cleanup_authorization_digest=authorization_digest,
            causal_delete_attempt_digest=attempt_digest,
            terminal_state=terminal_state,
            observed_at=observed_at,
            cleanup_transport_identity_digest=cleanup_transport_identity_digest,
            observation_proof=authenticator.proof(observation),
        )
        self._require_cleanup_observation_proof(
            receipt,
            causal_intent_snapshot=causal_intent_snapshot,
            causal_attempt_snapshot=causal_attempt_snapshot,
        )
        receipt_bytes = canonical_json_bytes(receipt)
        cleanup_receipt_digest = hashlib.sha256(
            _CLEANUP_RECEIPT_DOMAIN + receipt_bytes
        ).hexdigest()
        terminal = CleanupTerminalJournal(
            binding=binding,
            receipt=receipt,
            receipt_digest=cleanup_receipt_digest,
            causal_intent_snapshot=causal_intent_snapshot,
            causal_attempt_snapshot=causal_attempt_snapshot,
        )
        journal_name = self._store.cleanup_terminal_journal_name(binding)
        journal_bytes = canonical_json_bytes(terminal)
        self._verify_cleanup_gate(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
            receipt_digest=receipt_digest,
        )
        self._store.atomic_write_absent_on_failure(journal_name, journal_bytes)
        receipt_name = f"{cleanup_receipt_digest}.cleanup-receipt.json"
        self._verify_cleanup_gate(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
            receipt_digest=receipt_digest,
        )
        self._store.atomic_write_absent_on_failure(receipt_name, receipt_bytes)
        self._verify_cleanup_gate(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
            receipt_digest=receipt_digest,
        )
        return CleanupControlResult(
            receipt=receipt,
            receipt_path=self._store.path(receipt_name),
            journal_path=self._store.path(journal_name),
        )

    def _restore_cleanup_terminal(
        self,
        binding: InfrastructureCleanupBinding,
        *,
        authorization: DeploymentCleanupAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
        receipt_digest: str,
    ) -> CleanupControlResult | None:
        journal_name = self._store.cleanup_terminal_journal_name(binding)
        raw = self._store.read(journal_name)
        if raw is None:
            return None
        try:
            journal = CleanupTerminalJournal.model_validate_json(raw)
        except ValueError as exc:
            raise DeploymentControlBlocked(
                "cleanup_receipt_invalid",
                "terminal cleanup journal is invalid",
            ) from exc
        if canonical_json_bytes(journal) != raw or journal.binding != binding:
            raise DeploymentControlBlocked(
                "cleanup_receipt_invalid",
                "terminal cleanup journal has drifted",
            )
        self._require_cleanup_observation_proof(
            journal.receipt,
            causal_intent_snapshot=journal.causal_intent_snapshot,
            causal_attempt_snapshot=journal.causal_attempt_snapshot,
        )
        self._verify_cleanup_gate(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
            receipt_digest=receipt_digest,
        )
        if journal.causal_intent_snapshot is not None:
            assert journal.causal_attempt_snapshot is not None
            embedded_digest = self._verify_cleanup_attempt_evidence(
                binding=binding,
                intent_slot=journal.causal_intent_snapshot,
                attempt=journal.causal_attempt_snapshot,
                trusted_authorities=trusted_authorities,
            )
            if embedded_digest != journal.receipt.causal_delete_attempt_digest:
                raise DeploymentControlBlocked(
                    "cleanup_receipt_invalid",
                    "terminal cleanup receipt causal evidence has drifted",
                )
        receipt_bytes = canonical_json_bytes(journal.receipt)
        receipt_name = f"{journal.receipt_digest}.cleanup-receipt.json"
        existing = self._store.read(receipt_name)
        if existing is None:
            self._store.atomic_write_absent_on_failure(receipt_name, receipt_bytes)
        elif existing != receipt_bytes:
            raise DeploymentControlBlocked(
                "cleanup_receipt_invalid",
                "terminal cleanup receipt conflicts",
            )
        if self._store.read(receipt_name) != receipt_bytes:
            raise DeploymentControlBlocked(
                "cleanup_receipt_invalid",
                "terminal cleanup receipt readback drifted",
            )
        self._verify_cleanup_gate(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
            receipt_digest=receipt_digest,
        )
        self._require_cleanup_observation_proof(
            journal.receipt,
            causal_intent_snapshot=journal.causal_intent_snapshot,
            causal_attempt_snapshot=journal.causal_attempt_snapshot,
        )
        return CleanupControlResult(
            receipt=journal.receipt,
            receipt_path=self._store.path(receipt_name),
            journal_path=self._store.path(journal_name),
        )

    def _reconcile_existing_adoption_for_testing(
        self,
        *,
        authorization: ExistingDeploymentAdoptionAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> DeploymentAdoptionResult:
        self._require_testing_mode()
        return self._reconcile_existing_adoption(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
        )

    def _reconcile_existing_adoption(
        self,
        *,
        authorization: ExistingDeploymentAdoptionAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> DeploymentAdoptionResult:
        payload, _identity = self._verify_adoption_gate(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
            now=self._clock(),
        )
        with self._store.run_lock(payload.run_identity):
            if self._testing_sentinel is not _TESTING_MODE_SENTINEL:
                self._require_production_dependencies()
            return self._reconcile_existing_adoption_locked(
                authorization=authorization,
                trusted_authorities=trusted_authorities,
            )

    def _verify_adoption_gate(
        self,
        *,
        authorization: ExistingDeploymentAdoptionAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
        now: datetime,
    ) -> tuple[
        ExistingDeploymentAdoptionAuthorizationPayload,
        VerifiedDeploymentTransportIdentity,
    ]:
        try:
            if type(authorization) is not ExistingDeploymentAdoptionAuthorization:
                raise TypeError("adoption authorization type is not exact")
            candidate_payload = authorization.payload
            if type(candidate_payload) is not ExistingDeploymentAdoptionAuthorizationPayload:
                raise TypeError("adoption authorization payload type is not exact")
            payload_snapshot = {
                name: getattr(candidate_payload, name)
                for name in ExistingDeploymentAdoptionAuthorizationPayload.model_fields
            }
            validated = ExistingDeploymentAdoptionAuthorization.model_validate(
                {
                    "domain": authorization.domain,
                    "key_id": authorization.key_id,
                    "payload": payload_snapshot,
                    "signature": authorization.signature,
                }
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
                raise ValueError("deployment adoption policy drift")
            verify_adoption_authorization(
                validated,
                expected=payload,
                trusted_authorities=trusted_authorities,
                now=now,
            )
            identity = self._verified_transport_identity(payload=payload, now=now)
        except (
            AttributeError,
            AuthorizationVerificationError,
            TypeError,
            ValueError,
        ) as exc:
            raise DeploymentControlBlocked(
                "adoption_gate_rejected",
                "deployment adoption authorization is invalid",
            ) from exc
        return payload, identity

    def _require_fresh_adoption_boundary(
        self,
        *,
        authorization: ExistingDeploymentAdoptionAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> tuple[
        ExistingDeploymentAdoptionAuthorizationPayload,
        VerifiedDeploymentTransportIdentity,
        Mapping[str, TrustedAuthority],
    ]:
        fresh_cap: VerifiedInfrastructureProviderCapCapability | None = None
        if self._testing_sentinel is not _TESTING_MODE_SENTINEL:
            self._require_production_dependencies()
            trusted_authorities = self._production_operational_authorities()
            owned = self._production_dependencies
            if owned is None or owned[2] != "provisioning" or owned[5] is None:
                raise DeploymentControlBlocked(
                    "production_reserve_binding_mismatch",
                    "production adoption requires the fixed reserve cap boundary",
                )
            try:
                fresh_cap = owned[0].require_fresh_infrastructure_provider_capability(
                    plan=owned[3],
                    expected_scope=owned[4],
                    reserve_id=owned[5],
                )
            except (
                AuthorizationVerificationError,
                BudgetLedgerError,
                TypeError,
                ValueError,
            ) as exc:
                raise DeploymentControlBlocked(
                    "adoption_gate_rejected",
                    "root-owned adoption provider cap is stale or invalid",
                ) from exc
        payload, identity = self._verify_adoption_gate(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
            now=self._clock(),
        )
        owned = self._production_dependencies
        if self._testing_sentinel is not _TESTING_MODE_SENTINEL and (
            owned is None
            or owned[2] != "provisioning"
            or payload.run_identity != owned[3].run_identity
            or payload.purpose != owned[3].purpose
            or payload.scope != owned[4]
        ):
            raise DeploymentControlBlocked(
                "production_reserve_binding_mismatch",
                "production adoption does not match the factory run binding",
            )
        if fresh_cap is not None and (
            (
                payload.provider,
                payload.currency,
                payload.workspace_ref,
                payload.project_ref,
                payload.credential_ref,
                payload.provider_cap_evidence_digest,
                payload.provider_cap_approval_digest,
                frozenset(payload.provider_cap_coverage),
                payload.provider_cap_max_cost_minor_units,
                payload.provider_cap_expires_at,
            )
            != (
                fresh_cap.provider,
                fresh_cap.currency,
                fresh_cap.workspace_ref,
                fresh_cap.project_ref,
                fresh_cap.credential_ref,
                fresh_cap.evidence_digest,
                fresh_cap.approval_digest,
                fresh_cap.coverage,
                fresh_cap.max_cost_minor_units,
                fresh_cap.expires_at,
            )
            or payload.maximum_cost_minor_units > fresh_cap.max_cost_minor_units
        ):
            raise DeploymentControlBlocked(
                "adoption_gate_rejected",
                "signed adoption provider cap does not match root-owned evidence",
            )
        return payload, identity, trusted_authorities

    @staticmethod
    def _require_exact_adoption_manifest(
        manifest: ProviderDeploymentManifest,
        payload: ExistingDeploymentAdoptionAuthorizationPayload,
    ) -> None:
        if (
            manifest.deployed_model != payload.deployed_model
            or manifest.deployed_model
            != f"{payload.base_model}-{manifest.deployment_suffix}"
            or manifest.base_model != payload.base_model
            or manifest.plan != payload.receipt_plan
            or manifest.input_tpm != payload.input_tpm_quota
            or manifest.output_tpm != payload.output_tpm_quota
            or manifest.status != "RUNNING"
            or manifest.workspace_ref != payload.workspace_ref
            or manifest.operation_marker
            != deterministic_operation_marker(
                payload.run_identity,
                payload.operation_id,
                manifest.ownership_nonce,
            )
            or manifest.deployment_suffix
            != deterministic_deployment_suffix(
                payload.run_identity,
                payload.operation_id,
                manifest.ownership_nonce,
            )
        ):
            raise DeploymentControlBlocked(
                "adoption_remote_mismatch",
                "adopted deployment does not match the signed provider identity",
            )

    def _reconcile_existing_adoption_locked(
        self,
        *,
        authorization: ExistingDeploymentAdoptionAuthorization,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> DeploymentAdoptionResult:
        payload, identity, trusted_authorities = self._require_fresh_adoption_boundary(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
        )
        try:
            detail = _parse_manifest(
                self._transport.deployment_detail(deployed_model=payload.deployed_model)
            )
        except (DeploymentTransportError, DeploymentNotFound, TimeoutError) as exc:
            raise DeploymentControlBlocked(
                "adoption_remote_unverified",
                "adopted deployment cannot be freshly reconciled",
            ) from exc
        self._require_exact_adoption_manifest(detail, payload)
        observed_at = self._clock()
        payload, identity, trusted_authorities = self._require_fresh_adoption_boundary(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
        )
        manifest_digest = _remote_manifest_digest(detail)
        content = DeploymentReceiptContent(
            operation_id=payload.operation_id,
            infrastructure_reserve_id=payload.infrastructure_reserve_id,
            workspace_ref=identity.workspace_ref,
            project_ref=identity.project_ref,
            credential_ref=identity.credential_ref,
            workspace_evidence_digest=transport_workspace_evidence_digest(identity),
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
            remote_manifest_digest=manifest_digest,
        )
        receipt = DeploymentReceipt(
            content=content,
            content_digest=deployment_receipt_content_digest(content),
        )
        if (
            receipt.content_digest != payload.receipt_digest
            or receipt.content.deployed_model != payload.deployed_model
            or receipt.content.gmt_create != payload.gmt_create
        ):
            raise DeploymentControlBlocked(
                "adoption_receipt_mismatch",
                "fresh provider receipt does not match signed adoption",
            )
        artifact = DeploymentReceiptArtifact(
            receipt=receipt,
            remote_manifest=detail,
            remote_manifest_digest=manifest_digest,
        )
        receipt_name = f"{receipt.content_digest}.receipt.json"
        artifact_bytes = canonical_json_bytes(artifact)
        payload, identity, trusted_authorities = self._require_fresh_adoption_boundary(
            authorization=authorization,
            trusted_authorities=trusted_authorities,
        )
        publication_identity = self._store.atomic_write_absent_on_failure(
            receipt_name,
            artifact_bytes,
        )
        observation = object.__new__(_ControllerRemoteReceiptObservation)
        observation_values: dict[str, object] = {
            "receipt": receipt,
            "remote_manifest": detail,
            "transport_identity": identity,
            "run_identity": payload.run_identity,
            "purpose": payload.purpose,
            "scope": payload.scope,
            "remote_manifest_digest": manifest_digest,
            "observed_at": observed_at,
            "expires_at": min(
                observed_at + _RECONCILIATION_FRESHNESS,
                identity.expires_at,
                payload.expires_at,
            ),
            "authorization": authorization,
            "permit": None,
            "trusted_authorities": dict(trusted_authorities),
            "_seal": self._remote_observation_seal,
        }
        for name, value in observation_values.items():
            object.__setattr__(observation, name, value)
        try:
            capability = self._publish_reconciled_receipt(observation)
        except BaseException as exc:
            try:
                self._store.remove_if_owned(receipt_name, publication_identity)
            except BaseException as cleanup_exc:
                exc.add_note(
                    "adoption receipt cleanup conflict: "
                    f"{type(cleanup_exc).__name__}"
                )
            raise
        return DeploymentAdoptionResult(
            receipt=receipt,
            receipt_capability=capability,
            remote_manifest_digest=manifest_digest,
            receipt_path=self._store.path(receipt_name),
        )

    def _require_production_provisioning_binding(
        self,
        *,
        authorization: ProvisioningAuthorization,
        permit: InfrastructureCreatePermit,
    ) -> None:
        owned = self._production_dependencies
        try:
            validated = ProvisioningAuthorization.model_validate(
                authorization.model_dump(mode="python", round_trip=True)
            )
            payload = validated.payload
            if (
                owned is None
                or owned[2] != "provisioning"
                or owned[5] is None
                or payload.infrastructure_reserve_id != owned[5]
                or payload.run_identity != owned[3].run_identity
                or payload.purpose != owned[3].purpose
                or payload.scope != owned[4]
                or permit.reserve.reserve_id != owned[5]
                or permit.reserve.run_identity != owned[3].run_identity
                or permit.reserve.purpose != owned[3].purpose
                or permit.reserve.operation_id != payload.operation_id
                or permit.operation_id != payload.operation_id
            ):
                raise ValueError("production provisioning binding drifted")
        except (AttributeError, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "production_reserve_binding_mismatch",
                "production provisioning does not match the factory reserve binding",
            ) from exc

    def _provision_for_testing(
        self,
        *,
        authorization: ProvisioningAuthorization,
        permit: InfrastructureCreatePermit,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> DeploymentControlResult:
        self._require_testing_mode()
        return self._provision(
            authorization=authorization,
            permit=permit,
            trusted_authorities=trusted_authorities,
        )

    def _provision(
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
        try:
            identity = (
                _require_verified_deployment_transport_identity_for_testing(
                    self._transport.identity
                )
                if self._testing_sentinel is _TESTING_MODE_SENTINEL
                else require_verified_deployment_transport_identity(self._transport.identity)
            )
        except AuthorizationVerificationError as exc:  # pragma: no cover - gate above
            raise DeploymentControlBlocked(
                "transport_identity_invalid",
                "verified transport identity is unavailable",
            ) from exc
        authorization_digest = infrastructure_authorization_digest(authorization)
        journal_name = self._store.journal_name(payload.run_identity, payload.operation_id)
        with self._store.run_lock(payload.run_identity):
            if self._testing_sentinel is not _TESTING_MODE_SENTINEL:
                self._require_production_dependencies()
            # Re-read authority, authorization and all durable evidence while holding
            # the run lock; a queued operation cannot retain a revoked trust snapshot.
            if self._testing_sentinel is not _TESTING_MODE_SENTINEL:
                trusted_authorities = self._production_operational_authorities()
            payload = self._verify_gate(
                authorization=authorization,
                permit=permit,
                trusted_authorities=trusted_authorities,
                now=self._clock(),
            )
            self._require_current_reserve(permit)
            journal = self._load_or_create_journal(
                journal_name=journal_name,
                payload=payload,
                authorization_digest=authorization_digest,
            )
            request = BailianDeploymentRequest(
                base_model=cast(Any, payload.base_model),
                workspace_ref=identity.workspace_ref,
                region=_REGION,
                plan=_REQUEST_PLAN,
                input_tpm_quota=_INPUT_TPM,
                output_tpm_quota=_OUTPUT_TPM,
                payment_type=_PAYMENT_TYPE,
                ownership_nonce=journal.ownership_nonce,
                operation_marker=journal.operation_marker,
                deployment_suffix=journal.deployment_suffix,
            )
            journal = self._advance_to_prepared(journal_name, journal)
            if journal.state == "receipted":
                return self._restore_receipt(
                    journal_name,
                    journal,
                    payload,
                    request,
                    authorization=authorization,
                    permit=permit,
                    trusted_authorities=trusted_authorities,
                )

            payload, trusted_authorities = self._require_fresh_provisioning_boundary(
                authorization=authorization,
                permit=permit,
                trusted_authorities=trusted_authorities,
            )
            manifests = self._listed_manifests(
                marker=journal.operation_marker,
                suffix=journal.deployment_suffix,
            )
            match = self._select_owned_match(manifests, request=request)
            if match is not None:
                if not journal.send_started:
                    raise DeploymentControlBlocked(
                        "preexisting_collision",
                        "remote deployment predates this operation send intent",
                    )
                journal = self._record_ownership(journal_name, journal, transition="reconciled")
                return self._finish_receipt(
                    journal_name,
                    journal,
                    payload,
                    request,
                    match,
                    authorization=authorization,
                    permit=permit,
                    trusted_authorities=trusted_authorities,
                )

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
            payload, trusted_authorities = self._require_fresh_provisioning_boundary(
                authorization=authorization,
                permit=permit,
                trusted_authorities=trusted_authorities,
            )
            try:
                created = _parse_manifest(
                    self._transport.create_deployment(
                        request_body=canonical_json_bytes(request),
                        idempotency_key=_idempotency_key(
                            payload.run_identity,
                            payload.operation_id,
                            journal.ownership_nonce,
                        ),
                    )
                )
                self._require_exact_manifest(created, request)
                payload, trusted_authorities = self._require_fresh_provisioning_boundary(
                    authorization=authorization,
                    permit=permit,
                    trusted_authorities=trusted_authorities,
                )
                detail = _parse_manifest(
                    self._transport.deployment_detail(deployed_model=created.deployed_model)
                )
                payload, trusted_authorities = self._require_fresh_provisioning_boundary(
                    authorization=authorization,
                    permit=permit,
                    trusted_authorities=trusted_authorities,
                )
                if canonical_json_bytes(detail) != canonical_json_bytes(created):
                    raise DeploymentControlBlocked(
                        "remote_manifest_mismatch",
                        "provider detail does not match create manifest",
                    )
                journal = self._record_ownership(journal_name, journal, transition="created")
                return self._finish_receipt(
                    journal_name,
                    journal,
                    payload,
                    request,
                    detail,
                    authorization=authorization,
                    permit=permit,
                    trusted_authorities=trusted_authorities,
                )
            except (
                DeploymentProviderConflict,
                DeploymentTransportError,
                DeploymentControlBlocked,
                TimeoutError,
            ) as exc:
                if isinstance(exc, DeploymentControlBlocked) and exc.code in {
                    "production_dependency_invalid",
                    "production_provider_cap_invalid",
                    "production_mode_mismatch",
                }:
                    raise
                payload, trusted_authorities = self._require_fresh_provisioning_boundary(
                    authorization=authorization,
                    permit=permit,
                    trusted_authorities=trusted_authorities,
                )
                try:
                    manifests = self._listed_manifests(
                        marker=journal.operation_marker,
                        suffix=journal.deployment_suffix,
                    )
                    match = self._select_owned_match(manifests, request=request)
                except DeploymentControlBlocked:
                    raise DeploymentControlBlocked(
                        "provider_outcome_uncertain",
                        "provider mutation outcome requires manual reconciliation",
                    ) from None
                if match is None:
                    raise DeploymentControlBlocked(
                        "provider_outcome_uncertain",
                        "provider mutation outcome requires manual reconciliation",
                    ) from None
                journal = self._record_ownership(journal_name, journal, transition="reconciled")
                return self._finish_receipt(
                    journal_name,
                    journal,
                    payload,
                    request,
                    match,
                    authorization=authorization,
                    permit=permit,
                    trusted_authorities=trusted_authorities,
                )

    def _require_fresh_provisioning_boundary(
        self,
        *,
        authorization: ProvisioningAuthorization,
        permit: InfrastructureCreatePermit,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> tuple[ProvisioningAuthorizationPayload, Mapping[str, TrustedAuthority]]:
        if self._testing_sentinel is not _TESTING_MODE_SENTINEL:
            self._require_production_dependencies()
            trusted_authorities = self._production_operational_authorities()
        payload = self._verify_gate(
            authorization=authorization,
            permit=permit,
            trusted_authorities=trusted_authorities,
            now=self._clock(),
        )
        self._require_current_reserve(permit)
        return payload, trusted_authorities

    def refresh_topology_reconciliation_batch(
        self,
    ) -> TopologyReconciliationObservationBatchArtifact:
        self._require_production_dependencies()
        self._require_production_mode("topology_refresh")
        topology, strong, weak = self._production_topology_refresh_inputs()
        return self._refresh_topology_reconciliation_batch(
            run_identity=topology.run_identity,
            purpose=topology.purpose,
            scope=topology.scope,
            topology_digest=topology.topology_digest,
            plan_payload_hash=topology.plan_payload_hash,
            provider_cap_evidence_digest=topology.provider_cap_evidence_digest,
            provider_cap_approval_digest=topology.provider_cap_approval_digest,
            strong=strong,
            weak=weak,
        )

    def _production_topology_refresh_inputs(
        self,
    ) -> tuple[
        VerifiedFinalTopology,
        TopologyReconciliationTargetV1,
        TopologyReconciliationTargetV1,
    ]:
        owned = self._production_dependencies
        if owned is None or owned[2] != "topology_refresh":
            raise DeploymentControlBlocked(
                "production_mode_mismatch",
                "production topology refresh dependencies are unavailable",
            )
        try:
            topology, _strong_cap, _weak_cap = self._fresh_topology_provider_caps(
                owned[0],
                plan=owned[3],
                expected_scope=owned[4],
            )
            strong = self._topology_target_from_durable_artifacts(
                topology,
                topology.strong,
                boundary="strong",
            )
            weak = self._topology_target_from_durable_artifacts(
                topology,
                topology.weak,
                boundary="weak",
            )
        except (BudgetLedgerError, DeploymentControlBlocked, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "production_topology_invalid",
                "fresh root-owned topology evidence is unavailable",
            ) from exc
        return topology, strong, weak

    def _topology_target_from_durable_artifacts(
        self,
        topology: VerifiedFinalTopology,
        deployment: object,
        *,
        boundary: Literal["strong", "weak"],
    ) -> TopologyReconciliationTargetV1:
        exact = cast(Any, deployment)
        receipt = exact.receipt
        receipt_bytes = self._store.read(f"{receipt.content_digest}.receipt.json")
        reconciliation_bytes = self._store.read(
            f"{exact.reconciliation_digest}.receipt-reconciliation.json"
        )
        if receipt_bytes is None or reconciliation_bytes is None:
            raise DeploymentControlBlocked(
                "production_topology_artifact_missing",
                "bound topology receipt artifacts are unavailable",
            )
        try:
            receipt_artifact = DeploymentReceiptArtifact.model_validate_json(receipt_bytes)
            reconciliation = DeploymentReconciliationEvidenceV1.model_validate_json(
                reconciliation_bytes
            )
        except ValueError as exc:
            raise DeploymentControlBlocked(
                "production_topology_artifact_invalid",
                "bound topology receipt artifacts are invalid",
            ) from exc
        expected_budget_roles = (
            ("annotator", "judge") if boundary == "strong" else ("weak_extractor",)
        )
        target_roles: tuple[Literal["annotator", "extractor", "judge"], ...] = (
            ("annotator", "judge") if boundary == "strong" else ("extractor",)
        )
        if (
            canonical_json_bytes(receipt_artifact) != receipt_bytes
            or canonical_json_bytes(reconciliation) != reconciliation_bytes
            or receipt_artifact.receipt != receipt
            or reconciliation.receipt != receipt
            or reconciliation.remote_manifest != receipt_artifact.remote_manifest
            or reconciliation.reconciliation_digest != exact.reconciliation_digest
            or receipt_artifact.remote_manifest_digest != exact.remote_manifest_digest
            or reconciliation.run_identity != topology.run_identity
            or reconciliation.purpose != topology.purpose
            or reconciliation.scope != topology.scope
            or reconciliation.provider_cap_evidence_digest
            != topology.provider_cap_evidence_digest
            or reconciliation.provider_cap_approval_digest
            != topology.provider_cap_approval_digest
            or tuple(exact.roles) != expected_budget_roles
        ):
            raise DeploymentControlBlocked(
                "production_topology_artifact_invalid",
                "bound topology receipt artifacts have drifted",
            )
        return TopologyReconciliationTargetV1(
            boundary=boundary,
            receipt=receipt,
            expected_remote_manifest=receipt_artifact.remote_manifest,
            roles=target_roles,
        )

    @staticmethod
    def _topology_refresh_fingerprint(
        topology: VerifiedFinalTopology,
        strong: TopologyReconciliationTargetV1,
        weak: TopologyReconciliationTargetV1,
    ) -> str:
        return hashlib.sha256(
            _TOPOLOGY_OBSERVATION_BATCH_DOMAIN
            + canonical_json_bytes(
                {
                    "plan_payload_hash": topology.plan_payload_hash,
                    "provider_cap_approval_digest": topology.provider_cap_approval_digest,
                    "provider_cap_evidence_digest": topology.provider_cap_evidence_digest,
                    "purpose": topology.purpose,
                    "run_identity": topology.run_identity,
                    "scope": topology.scope,
                    "strong": strong.model_dump(mode="json"),
                    "topology_digest": topology.topology_digest,
                    "weak": weak.model_dump(mode="json"),
                }
            )
        ).hexdigest()

    def _require_fresh_production_topology_refresh(
        self,
        *,
        expected_fingerprint: str,
    ) -> VerifiedFinalTopology:
        self._require_production_dependencies()
        topology, strong, weak = self._production_topology_refresh_inputs()
        if self._topology_refresh_fingerprint(topology, strong, weak) != expected_fingerprint:
            raise DeploymentControlBlocked(
                "production_topology_drift",
                "root-owned topology changed during provider observation",
            )
        return topology

    def _refresh_topology_reconciliation_batch_for_testing(
        self,
        *,
        run_identity: str,
        purpose: str,
        scope: str,
        topology_digest: str,
        plan_payload_hash: str,
        provider_cap_evidence_digest: str,
        provider_cap_approval_digest: str,
        strong: TopologyReconciliationTargetV1,
        weak: TopologyReconciliationTargetV1,
    ) -> TopologyReconciliationObservationBatchArtifact:
        self._require_testing_mode()
        return self._refresh_topology_reconciliation_batch(
            run_identity=run_identity,
            purpose=purpose,
            scope=scope,
            topology_digest=topology_digest,
            plan_payload_hash=plan_payload_hash,
            provider_cap_evidence_digest=provider_cap_evidence_digest,
            provider_cap_approval_digest=provider_cap_approval_digest,
            strong=strong,
            weak=weak,
        )

    def _refresh_topology_reconciliation_batch(
        self,
        *,
        run_identity: str,
        purpose: str,
        scope: str,
        topology_digest: str,
        plan_payload_hash: str,
        provider_cap_evidence_digest: str,
        provider_cap_approval_digest: str,
        strong: TopologyReconciliationTargetV1,
        weak: TopologyReconciliationTargetV1,
    ) -> TopologyReconciliationObservationBatchArtifact:
        try:
            strong_target = TopologyReconciliationTargetV1.model_validate(
                strong.model_dump(mode="python", round_trip=True)
            )
            weak_target = TopologyReconciliationTargetV1.model_validate(
                weak.model_dump(mode="python", round_trip=True)
            )
            if (
                strong_target.boundary != "strong"
                or weak_target.boundary != "weak"
                or strong_target.receipt.content.infrastructure_reserve_id
                == weak_target.receipt.content.infrastructure_reserve_id
                or strong_target.receipt.content.operation_id
                == weak_target.receipt.content.operation_id
                or strong_target.receipt.content.deployed_model
                == weak_target.receipt.content.deployed_model
                or not _SAFE_PROVIDER_ID.fullmatch(run_identity)
                or not purpose
                or not scope
                or not re.fullmatch(r"[0-9a-f]{64}", topology_digest)
                or not re.fullmatch(r"[0-9a-f]{64}", plan_payload_hash)
                or not re.fullmatch(r"[0-9a-f]{64}", provider_cap_evidence_digest)
                or not re.fullmatch(r"[0-9a-f]{64}", provider_cap_approval_digest)
            ):
                raise ValueError("topology refresh request is invalid")
        except (AttributeError, TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "topology_observation_invalid",
                "topology reconciliation request is invalid",
            ) from exc

        with self._store.run_lock(run_identity):
            production_fingerprint: str | None = None
            if self._testing_sentinel is not _TESTING_MODE_SENTINEL:
                self._require_production_dependencies()
                self._require_production_mode("topology_refresh")
                topology, strong_target, weak_target = (
                    self._production_topology_refresh_inputs()
                )
                run_identity = topology.run_identity
                purpose = topology.purpose
                scope = topology.scope
                topology_digest = topology.topology_digest
                plan_payload_hash = topology.plan_payload_hash
                provider_cap_evidence_digest = topology.provider_cap_evidence_digest
                provider_cap_approval_digest = topology.provider_cap_approval_digest
                production_fingerprint = self._topology_refresh_fingerprint(
                    topology,
                    strong_target,
                    weak_target,
                )
            started_at = self._clock()
            identity = self._topology_transport_identity(
                now=started_at,
                topology_digest=topology_digest,
                provider_cap_evidence_digest=provider_cap_evidence_digest,
                provider_cap_approval_digest=provider_cap_approval_digest,
            )
            self._require_target_transport(strong_target, identity)
            self._require_target_transport(weak_target, identity)
            try:
                publication_topology: VerifiedFinalTopology | None = None
                if production_fingerprint is not None:
                    publication_topology = self._require_fresh_production_topology_refresh(
                        expected_fingerprint=production_fingerprint
                    )
                strong_manifest = _parse_manifest(
                    self._transport.deployment_detail(
                        deployed_model=strong_target.receipt.content.deployed_model
                    )
                )
                if canonical_json_bytes(strong_manifest) != canonical_json_bytes(
                    strong_target.expected_remote_manifest
                ):
                    raise DeploymentControlBlocked(
                        "topology_observation_drift",
                        "strong deployment manifest drifted",
                    )
                if production_fingerprint is not None:
                    self._require_fresh_production_topology_refresh(
                        expected_fingerprint=production_fingerprint
                    )
                weak_manifest = _parse_manifest(
                    self._transport.deployment_detail(
                        deployed_model=weak_target.receipt.content.deployed_model
                    )
                )
                if canonical_json_bytes(weak_manifest) != canonical_json_bytes(
                    weak_target.expected_remote_manifest
                ):
                    raise DeploymentControlBlocked(
                        "topology_observation_drift",
                        "weak deployment manifest drifted",
                    )
                if production_fingerprint is not None:
                    self._require_fresh_production_topology_refresh(
                        expected_fingerprint=production_fingerprint
                    )
            except DeploymentControlBlocked:
                raise
            except (DeploymentNotFound, DeploymentTransportError, TimeoutError) as exc:
                raise DeploymentControlBlocked(
                    "topology_observation_failed",
                    "topology deployment observation failed",
                ) from exc

            observed_at = self._clock()
            if production_fingerprint is not None:
                publication_topology = self._require_fresh_production_topology_refresh(
                    expected_fingerprint=production_fingerprint
                )
                if observed_at >= publication_topology.valid_until:
                    raise DeploymentControlBlocked(
                        "production_topology_drift",
                        "root-owned topology expired before observation publication",
                    )
            identity = self._topology_transport_identity(
                now=observed_at,
                topology_digest=topology_digest,
                provider_cap_evidence_digest=provider_cap_evidence_digest,
                provider_cap_approval_digest=provider_cap_approval_digest,
            )
            self._require_target_transport(strong_target, identity)
            self._require_target_transport(weak_target, identity)
            expires_at = min(
                observed_at + _RECONCILIATION_FRESHNESS,
                identity.expires_at,
                *(
                    (publication_topology.valid_until,)
                    if publication_topology is not None
                    else ()
                ),
            )
            batch = TopologyReconciliationObservationBatchV1(
                version=("insurancekb.run-admission.topology-reconciliation-observation-batch.v1"),
                issuer="bailian-deployment-controller-v1",
                run_identity=run_identity,
                purpose=purpose,
                scope=scope,
                topology_digest=topology_digest,
                plan_payload_hash=plan_payload_hash,
                provider_cap_evidence_digest=provider_cap_evidence_digest,
                provider_cap_approval_digest=provider_cap_approval_digest,
                transport_identity_digest=identity.identity_digest,
                strong=strong_target,
                weak=weak_target,
                observed_at=observed_at,
                expires_at=expires_at,
            )
            batch_bytes = canonical_json_bytes(batch)
            batch_digest = hashlib.sha256(
                _TOPOLOGY_OBSERVATION_BATCH_DOMAIN + batch_bytes
            ).hexdigest()
            artifact_name = f"{batch_digest}.topology-observation-batch.json"
            if production_fingerprint is not None:
                self._require_fresh_production_topology_refresh(
                    expected_fingerprint=production_fingerprint
                )
            publication_identity = self._store.atomic_write_absent_on_failure(
                artifact_name,
                batch_bytes,
            )
            try:
                try:
                    raw = self._store.read(artifact_name)
                    restored = TopologyReconciliationObservationBatchV1.model_validate(
                        _parse_json_bytes(raw or b"", maximum=_MAX_ARTIFACT_BYTES)
                    )
                except (DeploymentControlBlocked, TypeError, ValueError) as exc:
                    raise DeploymentControlBlocked(
                        "topology_observation_artifact_invalid",
                        "topology observation artifact readback is invalid",
                    ) from exc
                if canonical_json_bytes(restored) != batch_bytes:
                    raise DeploymentControlBlocked(
                        "topology_observation_artifact_invalid",
                        "topology observation artifact readback drifted",
                    )
                if production_fingerprint is not None:
                    self._require_fresh_production_topology_refresh(
                        expected_fingerprint=production_fingerprint
                    )
            except BaseException as exc:
                try:
                    self._store.remove_if_owned(artifact_name, publication_identity)
                except BaseException as cleanup_exc:
                    exc.add_note(
                        "topology publication cleanup conflict: "
                        f"{type(cleanup_exc).__name__}"
                    )
                raise
            return TopologyReconciliationObservationBatchArtifact(
                batch=restored,
                batch_digest=batch_digest,
                artifact_path=self._store.path(artifact_name),
            )

    def _topology_transport_identity(
        self,
        *,
        now: datetime,
        topology_digest: str,
        provider_cap_evidence_digest: str,
        provider_cap_approval_digest: str,
    ) -> VerifiedDeploymentTransportIdentity:
        try:
            identity = (
                _require_verified_deployment_transport_identity_for_testing(
                    self._transport.identity,
                    now=now,
                )
                if self._testing_sentinel is _TESTING_MODE_SENTINEL
                else require_verified_deployment_transport_identity(
                    self._transport.identity,
                    now=now,
                )
            )
        except AuthorizationVerificationError as exc:
            raise DeploymentControlBlocked(
                "topology_transport_identity_invalid",
                "topology transport identity is unavailable",
            ) from exc
        if (
            self._transport.endpoint != BAILIAN_DEPLOYMENT_ENDPOINT
            or identity.endpoint != BAILIAN_DEPLOYMENT_ENDPOINT
            or identity.topology_digest != topology_digest
            or identity.provider_cap_evidence_digest != provider_cap_evidence_digest
            or identity.provider_cap_approval_digest != provider_cap_approval_digest
        ):
            raise DeploymentControlBlocked(
                "topology_transport_identity_invalid",
                "topology transport identity does not match cap boundary",
            )
        return identity

    @staticmethod
    def _require_target_transport(
        target: TopologyReconciliationTargetV1,
        identity: VerifiedDeploymentTransportIdentity,
    ) -> None:
        content = target.receipt.content
        if (
            content.workspace_ref != identity.workspace_ref
            or content.project_ref != identity.project_ref
            or content.credential_ref != identity.credential_ref
            or content.workspace_evidence_digest != transport_workspace_evidence_digest(identity)
        ):
            raise DeploymentControlBlocked(
                "topology_transport_identity_invalid",
                "topology receipt does not match transport identity",
            )

    def _verify_gate(
        self,
        *,
        authorization: ProvisioningAuthorization,
        permit: InfrastructureCreatePermit,
        trusted_authorities: Mapping[str, TrustedAuthority],
        now: datetime,
    ) -> ProvisioningAuthorizationPayload:
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
            self._verified_transport_identity(payload=payload, now=now)
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
            or permit.reserve.maximum.cost_minor_units != payload.maximum_cost_minor_units
            or permit.reserve.maximum.input_tokens != 0
            or permit.reserve.maximum.output_tokens != 0
        ):
            raise DeploymentControlBlocked(
                "provisioning_permit_mismatch",
                "provisioning permit does not match the signed operation",
            )
        self._require_current_reserve(permit)
        return payload

    def _verified_transport_identity(
        self,
        *,
        payload: (
            ProvisioningAuthorizationPayload
            | ExistingDeploymentAdoptionAuthorizationPayload
        ),
        now: datetime,
    ) -> VerifiedDeploymentTransportIdentity:
        try:
            candidate = getattr(self._transport, "identity", None)
            if self._testing_sentinel is _TESTING_MODE_SENTINEL:
                try:
                    identity = _require_verified_deployment_transport_identity_for_testing(
                        candidate,
                        now=now,
                    )
                except AuthorizationVerificationError:
                    identity = require_verified_deployment_transport_identity(
                        candidate,
                        now=now,
                    )
            else:
                identity = require_verified_deployment_transport_identity(
                    candidate,
                    now=now,
                )
        except AuthorizationVerificationError as exc:
            raise DeploymentControlBlocked(
                "transport_identity_invalid",
                "verified transport identity is unavailable",
            ) from exc
        if (
            self._transport.endpoint != BAILIAN_DEPLOYMENT_ENDPOINT
            or identity.endpoint != BAILIAN_DEPLOYMENT_ENDPOINT
        ):
            raise DeploymentControlBlocked(
                "transport_endpoint_mismatch",
                "deployment transport endpoint is not the fixed Bailian control route",
            )
        expected = (
            payload.provider,
            BAILIAN_DEPLOYMENT_ENDPOINT,
            payload.workspace_ref,
            payload.project_ref,
            payload.credential_ref,
            payload.currency,
            payload.provider_cap_evidence_digest,
            payload.provider_cap_approval_digest,
            frozenset(payload.provider_cap_coverage),
        )
        observed = (
            identity.provider,
            identity.endpoint,
            identity.workspace_ref,
            identity.project_ref,
            identity.credential_ref,
            identity.currency,
            identity.provider_cap_evidence_digest,
            identity.provider_cap_approval_digest,
            identity.coverage,
        )
        if observed != expected:
            raise DeploymentControlBlocked(
                "transport_identity_mismatch",
                "transport identity does not match signed authorization and cap",
            )
        return identity

    def _publish_reconciled_receipt(
        self,
        observation: _ControllerRemoteReceiptObservation,
    ) -> VerifiedReconciledDeploymentReceipt:
        if (
            type(observation) is not _ControllerRemoteReceiptObservation
            or observation._seal is not self._remote_observation_seal
        ):
            raise DeploymentControlBlocked(
                "remote_receipt_observation_invalid",
                "fresh controller-owned provider observation is required",
            )
        self._require_receipt_authority_fresh(observation)
        receipt = observation.receipt
        remote_manifest = observation.remote_manifest
        transport_identity = observation.transport_identity
        run_identity = observation.run_identity
        purpose = observation.purpose
        scope = observation.scope
        remote_manifest_digest = observation.remote_manifest_digest
        observed_at = observation.observed_at
        expires_at = observation.expires_at
        receipt_name = f"{receipt.content_digest}.receipt.json"
        receipt_artifact_bytes = self._store.read(receipt_name)
        if receipt_artifact_bytes is None:
            raise DeploymentControlBlocked(
                "receipt_invalid",
                "immutable receipt artifact is unavailable for reconciliation",
            )
        try:
            receipt_artifact = DeploymentReceiptArtifact.model_validate_json(receipt_artifact_bytes)
        except (TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "receipt_invalid",
                "immutable receipt artifact is unavailable for reconciliation",
            ) from exc
        if (
            canonical_json_bytes(receipt_artifact) != receipt_artifact_bytes
            or receipt_artifact.receipt != receipt
            or receipt_artifact.remote_manifest != remote_manifest
        ):
            raise DeploymentControlBlocked(
                "receipt_invalid",
                "immutable receipt artifact does not match reconciliation",
            )
        self._require_receipt_authority_fresh(observation)
        reconciliation_digest = deployment_reconciliation_digest(
            issuer="bailian-deployment-controller-v1",
            transport_identity_digest=transport_identity.identity_digest,
            run_identity=run_identity,
            purpose=purpose,
            scope=scope,
            receipt_digest=receipt.content_digest,
            operation_id=receipt.content.operation_id,
            reserve_id=receipt.content.infrastructure_reserve_id,
            workspace_ref=transport_identity.workspace_ref,
            project_ref=transport_identity.project_ref,
            credential_ref=transport_identity.credential_ref,
            provider_cap_evidence_digest=(transport_identity.provider_cap_evidence_digest),
            provider_cap_approval_digest=(transport_identity.provider_cap_approval_digest),
            remote_manifest_digest=remote_manifest_digest,
            observed_at=observed_at,
            expires_at=expires_at,
        )
        evidence = DeploymentReconciliationEvidenceV1(
            version=("insurancekb.run-admission.deployment-reconciliation-evidence.v1"),
            issuer="bailian-deployment-controller-v1",
            transport_identity_digest=transport_identity.identity_digest,
            run_identity=run_identity,
            purpose=purpose,
            scope=scope,
            receipt=receipt,
            remote_manifest=remote_manifest,
            receipt_digest=receipt.content_digest,
            operation_id=receipt.content.operation_id,
            reserve_id=receipt.content.infrastructure_reserve_id,
            workspace_ref=transport_identity.workspace_ref,
            project_ref=transport_identity.project_ref,
            credential_ref=transport_identity.credential_ref,
            provider_cap_evidence_digest=(transport_identity.provider_cap_evidence_digest),
            provider_cap_approval_digest=(transport_identity.provider_cap_approval_digest),
            remote_manifest_digest=remote_manifest_digest,
            observed_at=observed_at,
            expires_at=expires_at,
            reconciliation_digest=reconciliation_digest,
        )
        evidence_name = f"{reconciliation_digest}.receipt-reconciliation.json"
        evidence_bytes = canonical_json_bytes(evidence)
        self._require_receipt_authority_fresh(observation)
        publication_identity = self._store.atomic_write_absent_on_failure(
            evidence_name,
            evidence_bytes,
        )
        try:
            reconciliation_readback = self._store.read(evidence_name)
            if reconciliation_readback is None:
                raise DeploymentControlBlocked(
                    "receipt_reconciliation_invalid",
                    "immutable reconciliation evidence is unavailable",
                )
            try:
                verified_evidence = DeploymentReconciliationEvidenceV1.model_validate_json(
                    reconciliation_readback
                )
            except (TypeError, ValueError) as exc:
                raise DeploymentControlBlocked(
                    "receipt_reconciliation_invalid",
                    "immutable reconciliation evidence is invalid",
                ) from exc
            if (
                reconciliation_readback != evidence_bytes
                or canonical_json_bytes(verified_evidence) != reconciliation_readback
                or verified_evidence != evidence
            ):
                raise DeploymentControlBlocked(
                    "receipt_reconciliation_invalid",
                    "immutable reconciliation evidence does not match publication",
                )
            self._require_receipt_authority_fresh(observation)

            proof = object.__new__(_ControllerReceiptPublicationProof)
            proof_values: dict[str, object] = {
                "evidence": verified_evidence,
                "receipt_artifact_bytes": receipt_artifact_bytes,
                "reconciliation_evidence_bytes": reconciliation_readback,
                "transport_identity": transport_identity,
                "transport_identity_digest": transport_identity.identity_digest,
                "remote_manifest_digest": remote_manifest_digest,
                "run_identity": run_identity,
                "purpose": purpose,
                "scope": scope,
                "observed_at": observed_at,
                "expires_at": expires_at,
                "authorization": observation.authorization,
                "permit": observation.permit,
                "trusted_authorities": dict(observation.trusted_authorities),
                "_seal": self._receipt_publication_seal,
            }
            for name, value in proof_values.items():
                object.__setattr__(proof, name, value)
            return self._mint_reconciled_receipt_from_publication(proof)
        except BaseException as exc:
            try:
                self._store.remove_if_owned(evidence_name, publication_identity)
            except BaseException as cleanup_exc:
                exc.add_note(
                    "receipt publication cleanup conflict: "
                    f"{type(cleanup_exc).__name__}"
                )
            raise

    def _mint_reconciled_receipt_from_publication(
        self,
        proof: _ControllerReceiptPublicationProof,
    ) -> VerifiedReconciledDeploymentReceipt:
        if (
            type(proof) is not _ControllerReceiptPublicationProof
            or proof._seal is not self._receipt_publication_seal
        ):
            raise DeploymentControlBlocked(
                "receipt_publication_proof_invalid",
                "controller-owned receipt publication proof is required",
            )
        self._require_receipt_authority_fresh(proof)
        evidence = proof.evidence
        receipt_artifact_bytes = self._store.read(
            f"{evidence.receipt_digest}.receipt.json"
        )
        reconciliation_evidence_bytes = self._store.read(
            f"{evidence.reconciliation_digest}.receipt-reconciliation.json"
        )
        if (
            receipt_artifact_bytes is None
            or reconciliation_evidence_bytes is None
            or receipt_artifact_bytes != proof.receipt_artifact_bytes
            or reconciliation_evidence_bytes != proof.reconciliation_evidence_bytes
        ):
            raise DeploymentControlBlocked(
                "receipt_publication_proof_invalid",
                "authority sink could not reload exact immutable receipt evidence",
            )
        try:
            receipt_artifact = DeploymentReceiptArtifact.model_validate_json(
                receipt_artifact_bytes
            )
            published_evidence = DeploymentReconciliationEvidenceV1.model_validate_json(
                reconciliation_evidence_bytes
            )
        except (TypeError, ValueError) as exc:
            raise DeploymentControlBlocked(
                "receipt_publication_proof_invalid",
                "authority sink reloaded invalid receipt evidence",
            ) from exc
        if (
            canonical_json_bytes(receipt_artifact) != receipt_artifact_bytes
            or canonical_json_bytes(published_evidence)
            != reconciliation_evidence_bytes
            or published_evidence != evidence
            or evidence.receipt != receipt_artifact.receipt
            or evidence.remote_manifest != receipt_artifact.remote_manifest
            or proof.transport_identity.identity_digest != proof.transport_identity_digest
            or evidence.transport_identity_digest != proof.transport_identity_digest
            or evidence.remote_manifest_digest != proof.remote_manifest_digest
            or evidence.run_identity != proof.run_identity
            or evidence.purpose != proof.purpose
            or evidence.scope != proof.scope
            or evidence.observed_at != proof.observed_at
            or evidence.expires_at != proof.expires_at
        ):
            raise DeploymentControlBlocked(
                "receipt_publication_proof_invalid",
                "controller receipt publication proof has drifted",
            )
        self._require_receipt_authority_fresh(proof)
        if self._testing_sentinel is _TESTING_MODE_SENTINEL:
            return _issue_verified_reconciled_receipt_for_testing(
                receipt=evidence.receipt,
                transport_identity=proof.transport_identity,
                run_identity=evidence.run_identity,
                purpose=evidence.purpose,
                scope=evidence.scope,
                remote_manifest_digest=evidence.remote_manifest_digest,
                observed_at=evidence.observed_at,
                expires_at=evidence.expires_at,
            )

        capability = object.__new__(VerifiedReconciledDeploymentReceipt)
        values: dict[str, object] = {
            "receipt": evidence.receipt,
            "reconciliation_digest": evidence.reconciliation_digest,
            "issuer": evidence.issuer,
            "transport_identity_digest": evidence.transport_identity_digest,
            "run_identity": evidence.run_identity,
            "purpose": evidence.purpose,
            "scope": evidence.scope,
            "operation_id": evidence.operation_id,
            "reserve_id": evidence.reserve_id,
            "workspace_ref": evidence.workspace_ref,
            "project_ref": evidence.project_ref,
            "credential_ref": evidence.credential_ref,
            "provider_cap_evidence_digest": evidence.provider_cap_evidence_digest,
            "provider_cap_approval_digest": evidence.provider_cap_approval_digest,
            "remote_manifest_digest": evidence.remote_manifest_digest,
            "observed_at": evidence.observed_at,
            "expires_at": evidence.expires_at,
            "_seal": _PRODUCTION_CAPABILITY_SEAL,
        }
        for name, value in values.items():
            object.__setattr__(capability, name, value)
        _register_verified_reconciled_receipt_capability(capability, testing=False)
        return capability

    def _require_receipt_authority_fresh(
        self,
        authority: _ControllerRemoteReceiptObservation | _ControllerReceiptPublicationProof,
    ) -> None:
        if (
            type(authority.authorization) is ProvisioningAuthorization
            and type(authority.permit) is InfrastructureCreatePermit
        ):
            self._require_fresh_provisioning_boundary(
                authorization=authority.authorization,
                permit=authority.permit,
                trusted_authorities=authority.trusted_authorities,
            )
            return
        if (
            type(authority.authorization) is ExistingDeploymentAdoptionAuthorization
            and authority.permit is None
        ):
            self._require_fresh_adoption_boundary(
                authorization=authority.authorization,
                trusted_authorities=authority.trusted_authorities,
            )
            return
        raise DeploymentControlBlocked(
            "receipt_authority_invalid",
            "receipt publication authority does not match its operation",
        )

    def _require_current_reserve(self, permit: InfrastructureCreatePermit) -> None:
        try:
            current = self._reserve_reader.infrastructure_reserve(permit.reserve.reserve_id)
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
    ) -> DeploymentOperationJournal:
        raw = self._store.read(journal_name)
        if raw is None:
            ownership_nonce = secrets.token_hex(16)
            journal = DeploymentOperationJournal(
                run_identity=payload.run_identity,
                operation_id=payload.operation_id,
                infrastructure_reserve_id=payload.infrastructure_reserve_id,
                authorization_digest=authorization_digest,
                ownership_nonce=ownership_nonce,
                operation_marker=deterministic_operation_marker(
                    payload.run_identity,
                    payload.operation_id,
                    ownership_nonce,
                ),
                deployment_suffix=deterministic_deployment_suffix(
                    payload.run_identity,
                    payload.operation_id,
                    ownership_nonce,
                ),
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
            deterministic_operation_marker(
                payload.run_identity,
                payload.operation_id,
                journal.ownership_nonce,
            ),
            deterministic_deployment_suffix(
                payload.run_identity,
                payload.operation_id,
                journal.ownership_nonce,
            ),
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

    def _write_journal(self, journal_name: str, journal: DeploymentOperationJournal) -> None:
        self._store.atomic_write(journal_name, canonical_json_bytes(journal))

    def _listed_manifests(
        self, *, marker: str, suffix: str
    ) -> tuple[ProviderDeploymentManifest, ...]:
        try:
            return _parse_list(self._transport.list_deployments(marker=marker, suffix=suffix))
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
            or manifest.ownership_nonce != request.ownership_nonce
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
        *,
        authorization: ProvisioningAuthorization,
        permit: InfrastructureCreatePermit,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> DeploymentControlResult:
        self._require_exact_manifest(manifest, request)
        payload, trusted_authorities = self._require_fresh_provisioning_boundary(
            authorization=authorization,
            permit=permit,
            trusted_authorities=trusted_authorities,
        )
        detail = _parse_manifest(
            self._transport.deployment_detail(deployed_model=manifest.deployed_model)
        )
        payload, trusted_authorities = self._require_fresh_provisioning_boundary(
            authorization=authorization,
            permit=permit,
            trusted_authorities=trusted_authorities,
        )
        if canonical_json_bytes(detail) != canonical_json_bytes(manifest):
            raise DeploymentControlBlocked(
                "remote_manifest_mismatch", "remote manifest changed before receipt"
            )
        observed_at = self._clock()
        identity = self._verified_transport_identity(payload=payload, now=observed_at)
        manifest_digest = _remote_manifest_digest(detail)
        content = DeploymentReceiptContent(
            operation_id=payload.operation_id,
            infrastructure_reserve_id=payload.infrastructure_reserve_id,
            workspace_ref=identity.workspace_ref,
            project_ref=identity.project_ref,
            credential_ref=identity.credential_ref,
            workspace_evidence_digest=transport_workspace_evidence_digest(identity),
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
            remote_manifest_digest=manifest_digest,
        )
        receipt = DeploymentReceipt(
            content=content,
            content_digest=deployment_receipt_content_digest(content),
        )
        artifact = DeploymentReceiptArtifact(
            receipt=receipt,
            remote_manifest=detail,
            remote_manifest_digest=manifest_digest,
        )
        receipt_name = f"{receipt.content_digest}.receipt.json"
        artifact_bytes = canonical_json_bytes(artifact)
        existing = self._store.read(receipt_name)
        if existing is not None and existing != artifact_bytes:
            raise DeploymentControlBlocked(
                "receipt_conflict", "content-addressed receipt conflicts"
            )
        if existing is None:
            payload, trusted_authorities = self._require_fresh_provisioning_boundary(
                authorization=authorization,
                permit=permit,
                trusted_authorities=trusted_authorities,
            )
            self._store.atomic_write(receipt_name, artifact_bytes)
        payload, trusted_authorities = self._require_fresh_provisioning_boundary(
            authorization=authorization,
            permit=permit,
            trusted_authorities=trusted_authorities,
        )
        observation = object.__new__(_ControllerRemoteReceiptObservation)
        observation_values: dict[str, object] = {
            "receipt": receipt,
            "remote_manifest": detail,
            "transport_identity": identity,
            "run_identity": payload.run_identity,
            "purpose": payload.purpose,
            "scope": payload.scope,
            "remote_manifest_digest": manifest_digest,
            "observed_at": observed_at,
            "expires_at": min(
                observed_at + _RECONCILIATION_FRESHNESS,
                identity.expires_at,
            ),
            "authorization": authorization,
            "permit": permit,
            "trusted_authorities": dict(trusted_authorities),
            "_seal": self._remote_observation_seal,
        }
        for name, value in observation_values.items():
            object.__setattr__(observation, name, value)
        terminal = journal.model_copy(
            update={
                "state": "receipted",
                "history": (*journal.history, "receipted"),
                "receipt_digest": receipt.content_digest,
            }
        )
        self._write_journal(journal_name, terminal)
        self._require_receipt_authority_fresh(observation)
        capability = self._publish_reconciled_receipt(observation)
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
        *,
        authorization: ProvisioningAuthorization,
        permit: InfrastructureCreatePermit,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> DeploymentControlResult:
        payload, trusted_authorities = self._require_fresh_provisioning_boundary(
            authorization=authorization,
            permit=permit,
            trusted_authorities=trusted_authorities,
        )
        assert journal.receipt_digest is not None
        receipt_name = f"{journal.receipt_digest}.receipt.json"
        raw = self._store.read(receipt_name)
        if raw is None:
            raise DeploymentControlBlocked("receipt_missing", "terminal journal receipt is missing")
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
            journal_name,
            journal,
            payload,
            request,
            artifact,
            authorization=authorization,
            permit=permit,
            trusted_authorities=trusted_authorities,
        )

    def _finish_receipt_from_existing(
        self,
        journal_name: str,
        journal: DeploymentOperationJournal,
        payload: ProvisioningAuthorizationPayload,
        request: BailianDeploymentRequest,
        artifact: DeploymentReceiptArtifact,
        *,
        authorization: ProvisioningAuthorization,
        permit: InfrastructureCreatePermit,
        trusted_authorities: Mapping[str, TrustedAuthority],
    ) -> DeploymentControlResult:
        self._require_exact_manifest(artifact.remote_manifest, request)
        payload, trusted_authorities = self._require_fresh_provisioning_boundary(
            authorization=authorization,
            permit=permit,
            trusted_authorities=trusted_authorities,
        )
        detail = _parse_manifest(
            self._transport.deployment_detail(
                deployed_model=artifact.remote_manifest.deployed_model
            )
        )
        payload, trusted_authorities = self._require_fresh_provisioning_boundary(
            authorization=authorization,
            permit=permit,
            trusted_authorities=trusted_authorities,
        )
        if canonical_json_bytes(detail) != canonical_json_bytes(artifact.remote_manifest):
            raise DeploymentControlBlocked(
                "remote_manifest_mismatch", "remote manifest changed after receipt"
            )
        observed_at = self._clock()
        identity = self._verified_transport_identity(payload=payload, now=observed_at)
        manifest_digest = _remote_manifest_digest(detail)
        content = artifact.receipt.content
        expected = DeploymentReceiptContent(
            operation_id=payload.operation_id,
            infrastructure_reserve_id=payload.infrastructure_reserve_id,
            workspace_ref=identity.workspace_ref,
            project_ref=identity.project_ref,
            credential_ref=identity.credential_ref,
            workspace_evidence_digest=transport_workspace_evidence_digest(identity),
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
            remote_manifest_digest=manifest_digest,
        )
        if canonical_json_bytes(content) != canonical_json_bytes(expected):
            raise DeploymentControlBlocked(
                "receipt_invalid", "stored receipt no longer matches exact manifest"
            )
        observation = object.__new__(_ControllerRemoteReceiptObservation)
        observation_values: dict[str, object] = {
            "receipt": artifact.receipt,
            "remote_manifest": detail,
            "transport_identity": identity,
            "run_identity": payload.run_identity,
            "purpose": payload.purpose,
            "scope": payload.scope,
            "remote_manifest_digest": manifest_digest,
            "observed_at": observed_at,
            "expires_at": min(
                observed_at + _RECONCILIATION_FRESHNESS,
                identity.expires_at,
            ),
            "authorization": authorization,
            "permit": permit,
            "trusted_authorities": dict(trusted_authorities),
            "_seal": self._remote_observation_seal,
        }
        for name, value in observation_values.items():
            object.__setattr__(observation, name, value)
        capability = self._publish_reconciled_receipt(observation)
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
    "DeploymentReconciliationEvidenceV1",
    "DeploymentReceiptArtifact",
    "DeploymentTransportError",
    "ProviderDeploymentManifest",
    "TopologyReconciliationObservationBatchArtifact",
    "TopologyReconciliationObservationBatchV1",
    "TopologyReconciliationTargetV1",
    "deployment_reconciliation_digest",
    "deterministic_deployment_suffix",
    "deterministic_operation_marker",
    "transport_workspace_evidence_digest",
]
