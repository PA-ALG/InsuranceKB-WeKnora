"""Read-only readiness gate before one bounded real 596-1 capture.

This task-local gate owns no dependency implementation and performs no discovery, capture,
credential loading or external I/O. Formal readiness can advance only after code-owned frozen
public dependency identities are populated by a later mechanical integration.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

DependencyId = Literal["091", "098", "086", "096", "095_087", "094"]
ArtifactRole = Literal["terms", "brochure", "rate_table"]

DEPENDENCY_ORDER: tuple[DependencyId, ...] = (
    "091",
    "098",
    "086",
    "096",
    "095_087",
    "094",
)
ROLE_ORDER: tuple[ArtifactRole, ...] = ("terms", "brochure", "rate_table")
SOURCE_SHA256_BY_ROLE: dict[str, str] = {
    "terms": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    "brochure": "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    "rate_table": "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
}

_HEX = frozenset("0123456789abcdef")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_REAL_EVIDENCE_CLASS = "REAL_PUBLIC_ADAPTER"
_TEST_EVIDENCE_CLASS = "TEST_ONLY_COMPLETE_FIXTURE"


@dataclass(frozen=True)
class BoundProof:
    preimage: bytes
    sha256: str


@dataclass(frozen=True)
class FrozenDependencyIdentity:
    dependency_id: str
    contract_id: str
    contract_version: str
    implementation_blob_sha256: str
    api_schema_sha256: str
    canonical_preimage_sha256: str
    context_sha256: str
    policy_sha256: str
    replay_sha256: str


@dataclass(frozen=True)
class PrivateArtifactEvidence:
    role: str
    source_sha256: str
    outer_sha256: str
    path_identity_sha256: str
    file_mode: int
    parent_mode: int
    is_regular: bool
    is_symlink: bool


@dataclass(frozen=True)
class DependencyEvidence:
    dependency_id: str
    evidence_class: str
    adapter_present: bool
    contract_id: str
    contract_version: str
    implementation_blob_sha256: str
    api_schema_sha256: str
    canonical_preimage: BoundProof
    receipt: BoundProof
    predecessor_receipt_sha256: str | None
    context_sha256: str
    policy_sha256: str
    replay_sha256: str
    ordered_roles: tuple[str, ...]
    endpoint_state: str
    endpoint_derivation_input_sha256: str | None
    binding_state: str
    relation_state: str
    dependency_map: tuple[str, ...]
    wrapper_invocation_cap: int
    retry_budget: int
    fallback_enabled: bool
    external_effects: int


@dataclass(frozen=True)
class ReadinessBundle:
    product_version: str
    artifacts: tuple[PrivateArtifactEvidence, ...]
    dependencies: tuple[DependencyEvidence, ...]


@dataclass(frozen=True)
class SafeDependencyIdentity:
    dependency_id: str
    contract_id: str
    contract_version: str
    implementation_blob_sha256: str
    api_schema_sha256: str
    receipt_sha256: str


@dataclass(frozen=True)
class ReadinessResult:
    status: str
    reason_code: str
    evidence_class: str
    capture_authorized: bool
    evaluated_dependencies: tuple[str, ...] = ()
    dependency_identities: tuple[SafeDependencyIdentity, ...] = ()

    def to_wire(self) -> dict[str, object]:
        return {
            "capture_authorized": self.capture_authorized,
            "dependency_identities": [
                {
                    "api_schema_sha256": item.api_schema_sha256,
                    "contract_id": item.contract_id,
                    "contract_version": item.contract_version,
                    "dependency_id": item.dependency_id,
                    "implementation_blob_sha256": item.implementation_blob_sha256,
                    "receipt_sha256": item.receipt_sha256,
                }
                for item in self.dependency_identities
            ],
            "evaluated_dependencies": list(self.evaluated_dependencies),
            "evidence_class": self.evidence_class,
            "reason_code": self.reason_code,
            "status": self.status,
        }


# Intentionally empty on current main. 091 has no merged, independently frozen public
# implementation/API identity. A later dependency-integration change must populate this exact
# tuple from reviewed public candidates; caller input cannot supply formal authority.
CURRENT_FROZEN_DEPENDENCY_AUTHORITY: tuple[FrozenDependencyIdentity, ...] = ()


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _HEX for character in value)
    )


def _proof_is_valid(value: object) -> bool:
    return (
        type(value) is BoundProof
        and type(value.preimage) is bytes
        and _is_sha256(value.sha256)
        and hashlib.sha256(value.preimage).hexdigest() == value.sha256
    )


def _safe_token(value: object) -> bool:
    return type(value) is str and _SAFE_TOKEN.fullmatch(value) is not None


def _blocked(reason: str, evaluated: tuple[str, ...] = ()) -> ReadinessResult:
    safe_reason = reason if _safe_token(reason) else "UNSAFE_DEPENDENCY_RESULT_BLOCKED"
    return ReadinessResult(
        status=safe_reason,
        reason_code=safe_reason,
        evidence_class="BLOCKED",
        capture_authorized=False,
        evaluated_dependencies=evaluated,
    )


def _authority_by_id(
    authority: tuple[FrozenDependencyIdentity, ...],
) -> Mapping[str, FrozenDependencyIdentity] | ReadinessResult:
    if type(authority) is not tuple:
        return _blocked("FROZEN_DEPENDENCY_AUTHORITY_DRIFT_091")
    by_id: dict[str, FrozenDependencyIdentity] = {}
    for identity in authority:
        if type(identity) is not FrozenDependencyIdentity or identity.dependency_id in by_id:
            return _blocked("FROZEN_DEPENDENCY_AUTHORITY_DRIFT_091")
        by_id[identity.dependency_id] = identity
    for dependency_id in DEPENDENCY_ORDER:
        if dependency_id not in by_id:
            return _blocked(f"FROZEN_DEPENDENCY_AUTHORITY_UNAVAILABLE_{dependency_id}")
    if tuple(identity.dependency_id for identity in authority) != DEPENDENCY_ORDER:
        return _blocked("FROZEN_DEPENDENCY_AUTHORITY_ORDER_DRIFT")
    return by_id


def _identity_is_well_formed(identity: FrozenDependencyIdentity) -> bool:
    return (
        identity.dependency_id in DEPENDENCY_ORDER
        and _safe_token(identity.contract_id)
        and _safe_token(identity.contract_version)
        and _is_sha256(identity.implementation_blob_sha256)
        and _is_sha256(identity.api_schema_sha256)
        and _is_sha256(identity.canonical_preimage_sha256)
        and _is_sha256(identity.context_sha256)
        and _is_sha256(identity.policy_sha256)
        and _is_sha256(identity.replay_sha256)
    )


def _artifacts_are_exact(bundle: ReadinessBundle) -> bool:
    if (
        type(bundle.product_version) is not str
        or bundle.product_version != "596-1"
        or type(bundle.artifacts) is not tuple
        or tuple(item.role for item in bundle.artifacts) != ROLE_ORDER
    ):
        return False
    for artifact in bundle.artifacts:
        if (
            type(artifact) is not PrivateArtifactEvidence
            or artifact.source_sha256 != SOURCE_SHA256_BY_ROLE.get(artifact.role)
            or not _is_sha256(artifact.outer_sha256)
            or not _is_sha256(artifact.path_identity_sha256)
            or type(artifact.file_mode) is not int
            or artifact.file_mode != 0o600
            or type(artifact.parent_mode) is not int
            or artifact.parent_mode != 0o700
            or type(artifact.is_regular) is not bool
            or artifact.is_regular is not True
            or type(artifact.is_symlink) is not bool
            or artifact.is_symlink is not False
        ):
            return False
    return True


def _dependency_identity_matches(
    evidence: DependencyEvidence, identity: FrozenDependencyIdentity
) -> str | None:
    if not _identity_is_well_formed(identity):
        return f"FROZEN_DEPENDENCY_AUTHORITY_DRIFT_{identity.dependency_id}"
    if not evidence.adapter_present:
        return f"DEPENDENCY_IMPLEMENTATION_UNAVAILABLE_{identity.dependency_id}"
    if (
        evidence.contract_id != identity.contract_id
        or evidence.contract_version != identity.contract_version
        or evidence.implementation_blob_sha256 != identity.implementation_blob_sha256
        or evidence.api_schema_sha256 != identity.api_schema_sha256
    ):
        return f"DEPENDENCY_IDENTITY_DRIFT_{identity.dependency_id}"
    if (
        not _proof_is_valid(evidence.canonical_preimage)
        or evidence.canonical_preimage.sha256 != identity.canonical_preimage_sha256
        or not _proof_is_valid(evidence.receipt)
    ):
        return f"DEPENDENCY_PREIMAGE_DRIFT_{identity.dependency_id}"
    if evidence.context_sha256 != identity.context_sha256:
        return f"DEPENDENCY_CONTEXT_DRIFT_{identity.dependency_id}"
    if evidence.policy_sha256 != identity.policy_sha256:
        return f"DEPENDENCY_POLICY_DRIFT_{identity.dependency_id}"
    if evidence.replay_sha256 != identity.replay_sha256:
        return f"DEPENDENCY_REPLAY_DRIFT_{identity.dependency_id}"
    return None


def _stage_contract_reason(
    evidence: DependencyEvidence, predecessor_receipt_sha256: str | None
) -> str | None:
    dependency_id = evidence.dependency_id
    if evidence.predecessor_receipt_sha256 != predecessor_receipt_sha256:
        return f"DEPENDENCY_PREDECESSOR_DRIFT_{dependency_id}"
    if evidence.ordered_roles != ROLE_ORDER:
        return f"DEPENDENCY_SOURCE_ORDER_DRIFT_{dependency_id}"
    if type(evidence.external_effects) is not int or evidence.external_effects != 0:
        return "EXTERNAL_EFFECT_CONTRACT_VIOLATION"
    if dependency_id == "098":
        if evidence.endpoint_derivation_input_sha256 != predecessor_receipt_sha256:
            return "DEPENDENCY_PREDECESSOR_DRIFT_098"
        if evidence.endpoint_state in {"SINGLE_ENDPOINT_ONLY", "ENDPOINT_PAIR_MISSING"}:
            return "BLOCKED_ON_CROSS_PAGE_BINDING"
        if evidence.endpoint_state != "COMPLETE_ENDPOINT_PAIR_VERIFIED":
            return "ENDPOINT_DERIVATION_CONTRACT_BLOCKED_098"
    elif dependency_id == "086" and evidence.binding_state != "VERIFIED_BINDING":
        return "BLOCKED_ON_CROSS_PAGE_BINDING"
    elif dependency_id == "096" and evidence.relation_state != "VERIFIED_RELATION_RECEIPT":
        return "BLOCKED_ON_CROSS_PAGE_BINDING"
    elif dependency_id == "095_087" and evidence.dependency_map != (
        "091",
        "098",
        "086",
        "096",
        "087",
    ):
        return "DEPENDENCY_MAP_BLOCKED_095_087"
    elif dependency_id == "094" and (
        type(evidence.wrapper_invocation_cap) is not int
        or evidence.wrapper_invocation_cap != 1
        or type(evidence.retry_budget) is not int
        or evidence.retry_budget != 0
        or type(evidence.fallback_enabled) is not bool
        or evidence.fallback_enabled is not False
    ):
        return "WRAPPER_POLICY_BLOCKED_094"
    return None


def _evaluate(
    bundle: ReadinessBundle,
    authority: tuple[FrozenDependencyIdentity, ...],
    *,
    required_evidence_class: str,
    success_evidence_class: str,
    capture_authorized: bool,
) -> ReadinessResult:
    authority_result = _authority_by_id(authority)
    if isinstance(authority_result, ReadinessResult):
        return authority_result
    if type(bundle) is not ReadinessBundle or not _artifacts_are_exact(bundle):
        return _blocked("PRIVATE_ARTIFACT_ACCESS_BLOCKED")
    if (
        type(bundle.dependencies) is not tuple
        or tuple(item.dependency_id for item in bundle.dependencies) != DEPENDENCY_ORDER
    ):
        return _blocked("DEPENDENCY_ORDER_BLOCKED")

    evaluated: list[str] = []
    summaries: list[SafeDependencyIdentity] = []
    predecessor_receipt_sha256: str | None = None
    for evidence in bundle.dependencies:
        dependency_id = evidence.dependency_id
        evaluated.append(dependency_id)
        if evidence.evidence_class != required_evidence_class:
            return _blocked(
                f"DEPENDENCY_EVIDENCE_CLASS_BLOCKED_{dependency_id}", tuple(evaluated)
            )
        identity = authority_result[dependency_id]
        identity_reason = _dependency_identity_matches(evidence, identity)
        if identity_reason is not None:
            return _blocked(identity_reason, tuple(evaluated))
        stage_reason = _stage_contract_reason(evidence, predecessor_receipt_sha256)
        if stage_reason is not None:
            return _blocked(stage_reason, tuple(evaluated))
        summaries.append(
            SafeDependencyIdentity(
                dependency_id=dependency_id,
                contract_id=identity.contract_id,
                contract_version=identity.contract_version,
                implementation_blob_sha256=identity.implementation_blob_sha256,
                api_schema_sha256=identity.api_schema_sha256,
                receipt_sha256=evidence.receipt.sha256,
            )
        )
        predecessor_receipt_sha256 = evidence.receipt.sha256

    return ReadinessResult(
        status="READY_FOR_ONE_BOUNDED_CAPTURE",
        reason_code="READY_FOR_ONE_BOUNDED_CAPTURE",
        evidence_class=success_evidence_class,
        capture_authorized=capture_authorized,
        evaluated_dependencies=tuple(evaluated),
        dependency_identities=tuple(summaries),
    )


def evaluate_bounded_capture_readiness(bundle: ReadinessBundle) -> ReadinessResult:
    """Evaluate formal readiness against code-owned real public authority only."""

    return _evaluate(
        bundle,
        CURRENT_FROZEN_DEPENDENCY_AUTHORITY,
        required_evidence_class=_REAL_EVIDENCE_CLASS,
        success_evidence_class=_REAL_EVIDENCE_CLASS,
        capture_authorized=True,
    )


def evaluate_test_only_future_readiness(
    bundle: ReadinessBundle,
    test_authority: tuple[FrozenDependencyIdentity, ...],
) -> ReadinessResult:
    """Exercise future completeness without granting capture authority."""

    return _evaluate(
        bundle,
        test_authority,
        required_evidence_class=_TEST_EVIDENCE_CLASS,
        success_evidence_class="TEST_ONLY",
        capture_authorized=False,
    )
