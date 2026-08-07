"""Provider-free compatibility rehearsal for the pending 596-1 integration stack.

The module owns no dependency authority. Its narrow ports make the unmerged 091, 096,
095/087 and 094 boundaries explicit while verifying only byte hashes, predecessor
bindings, endpoint existence and zero external effects.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

ArtifactRole = Literal["terms", "brochure", "rate_table"]
EndpointKind = Literal["block", "table"]
RelationKind = Literal["section", "table"]

_ROLES: tuple[ArtifactRole, ...] = ("terms", "brochure", "rate_table")
_SOURCE_SHA256_BY_ROLE: dict[str, str] = {
    "terms": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    "brochure": "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    "rate_table": "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
}
_SAFE_REASON = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_HEX = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class BoundProof:
    """Opaque canonical bytes plus their dependency-owned digest."""

    preimage: bytes
    sha256: str


_INVALID_PROOF = BoundProof(preimage=b"", sha256="")


@dataclass(frozen=True)
class EndpointFact:
    role: str
    kind: str
    element_id: str
    page_index: int


@dataclass(frozen=True)
class ArtifactFact:
    role: str
    source_sha256: str
    artifact_sha256: str
    endpoints: tuple[EndpointFact, ...]


@dataclass(frozen=True)
class RelationBinding:
    kind: str
    source: EndpointFact
    target: EndpointFact


@dataclass(frozen=True)
class RehearsalRequest:
    product_version: str
    ordered_source_sha256_by_role: Mapping[str, str]


@dataclass(frozen=True)
class _EffectFields:
    provider_calls: int = 0
    model_calls: int = 0
    golden_reads: int = 0
    db_writes: int = 0
    pg_writes: int = 0
    weknora_writes: int = 0
    live_calls: int = 0
    retry_count: int = 0
    fallback_count: int = 0


@dataclass(frozen=True)
class CaptureResult(_EffectFields):
    status: str = ""
    reason_code: str = ""
    proof: BoundProof = _INVALID_PROOF
    artifacts: tuple[ArtifactFact, ...] = ()


@dataclass(frozen=True)
class Custody091Result(_EffectFields):
    status: str = ""
    reason_code: str = ""
    proof: BoundProof = _INVALID_PROOF
    capture_receipt_sha256: str = ""
    artifacts: tuple[ArtifactFact, ...] = ()


@dataclass(frozen=True)
class Relation096Result(_EffectFields):
    status: str = ""
    reason_code: str = ""
    proof: BoundProof = _INVALID_PROOF
    custody_receipt_sha256: str = ""
    manifest: BoundProof = _INVALID_PROOF
    decision: BoundProof = _INVALID_PROOF
    bindings: tuple[RelationBinding, ...] = ()


@dataclass(frozen=True)
class Wiring095087Result(_EffectFields):
    status: str = ""
    reason_code: str = ""
    proof: BoundProof = _INVALID_PROOF
    relation_receipt_sha256: str = ""
    relation_manifest_sha256: str = ""
    relation_decision_sha256: str = ""


@dataclass(frozen=True)
class Wrapper094Result(_EffectFields):
    status: str = ""
    reason_code: str = ""
    proof: BoundProof = _INVALID_PROOF
    wiring_receipt_sha256: str = ""


class SyntheticCapturePort(Protocol):
    def __call__(self, request: RehearsalRequest) -> CaptureResult: ...


class Custody091Port(Protocol):
    def __call__(self, capture: CaptureResult) -> Custody091Result: ...


class Relation096Port(Protocol):
    def __call__(self, custody: Custody091Result) -> Relation096Result: ...


class Wiring095087Port(Protocol):
    def __call__(
        self, custody: Custody091Result, relation: Relation096Result
    ) -> Wiring095087Result: ...


class Wrapper094Port(Protocol):
    def __call__(self, wiring: Wiring095087Result) -> Wrapper094Result: ...


@dataclass(frozen=True)
class RehearsalDependencies:
    capture_executor: SyntheticCapturePort
    custody_091: Custody091Port
    relation_096: Relation096Port
    wiring_095_087: Wiring095087Port
    wrapper_094: Wrapper094Port


@dataclass(frozen=True)
class RehearsalResult:
    status: str
    reason_code: str
    chain_digest_sha256: str | None = None
    invocation_counts: Mapping[str, int] | None = None
    provider_calls: int = 0
    model_calls: int = 0
    golden_reads: int = 0
    db_writes: int = 0
    pg_writes: int = 0
    weknora_writes: int = 0
    live_calls: int = 0

    def __post_init__(self) -> None:
        if self.invocation_counts is None:
            object.__setattr__(
                self,
                "invocation_counts",
                {
                    "capture": 0,
                    "custody_091": 0,
                    "relation_096": 0,
                    "wiring_095_087": 0,
                    "wrapper_094": 0,
                },
            )


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _HEX for character in value)
    )


def _proof_is_valid(proof: object) -> bool:
    return (
        type(proof) is BoundProof
        and type(proof.preimage) is bytes
        and _is_sha256(proof.sha256)
        and hashlib.sha256(proof.preimage).hexdigest() == proof.sha256
    )


def _safe_reason_code(value: object) -> bool:
    return type(value) is str and _SAFE_REASON.fullmatch(value) is not None


def _effects_are_zero(result: object) -> bool:
    return all(
        type(getattr(result, field)) is int and getattr(result, field) == 0
        for field in (
            "provider_calls",
            "model_calls",
            "golden_reads",
            "db_writes",
            "pg_writes",
            "weknora_writes",
            "live_calls",
            "retry_count",
            "fallback_count",
        )
    )


def _initial_counts() -> dict[str, int]:
    return {
        "capture": 0,
        "custody_091": 0,
        "relation_096": 0,
        "wiring_095_087": 0,
        "wrapper_094": 0,
    }


def _blocked(reason_code: str, counts: Mapping[str, int]) -> RehearsalResult:
    safe_reason = reason_code if _safe_reason_code(reason_code) else "DEPENDENCY_RESULT_BLOCKED"
    return RehearsalResult(
        status=safe_reason,
        reason_code=safe_reason,
        invocation_counts=dict(counts),
    )


def _request_is_exact(request: object) -> bool:
    if type(request) is not RehearsalRequest or request.product_version != "596-1":
        return False
    mapping = request.ordered_source_sha256_by_role
    return (
        type(mapping) is dict
        and tuple(mapping) == _ROLES
        and mapping == _SOURCE_SHA256_BY_ROLE
    )


def _endpoint_is_valid(endpoint: object, role: str) -> bool:
    return (
        type(endpoint) is EndpointFact
        and endpoint.role == role
        and endpoint.kind in ("block", "table")
        and type(endpoint.element_id) is str
        and bool(endpoint.element_id)
        and "\n" not in endpoint.element_id
        and type(endpoint.page_index) is int
        and endpoint.page_index >= 0
    )


def _artifacts_are_exact(artifacts: object) -> bool:
    if type(artifacts) is not tuple or tuple(item.role for item in artifacts) != _ROLES:
        return False
    seen: set[tuple[str, str, str, int]] = set()
    for artifact in artifacts:
        if (
            type(artifact) is not ArtifactFact
            or artifact.source_sha256 != _SOURCE_SHA256_BY_ROLE[artifact.role]
            or not _is_sha256(artifact.artifact_sha256)
            or type(artifact.endpoints) is not tuple
        ):
            return False
        for endpoint in artifact.endpoints:
            if not _endpoint_is_valid(endpoint, artifact.role):
                return False
            identity = (
                endpoint.role,
                endpoint.kind,
                endpoint.element_id,
                endpoint.page_index,
            )
            if identity in seen:
                return False
            seen.add(identity)
    return True


def _stage_proof_is_valid(result: object) -> bool:
    return (
        _safe_reason_code(getattr(result, "status", None))
        and _safe_reason_code(getattr(result, "reason_code", None))
        and _proof_is_valid(getattr(result, "proof", None))
    )


def _relation_bindings_are_exact(
    bindings: object, artifacts: tuple[ArtifactFact, ...]
) -> bool:
    if type(bindings) is not tuple or len(bindings) != 2:
        return False
    expected = (("section", "terms", "block"), ("table", "rate_table", "table"))
    available = {
        (endpoint.role, endpoint.kind, endpoint.element_id, endpoint.page_index)
        for artifact in artifacts
        for endpoint in artifact.endpoints
    }
    for binding, (relation_kind, role, endpoint_kind) in zip(bindings, expected, strict=True):
        if (
            type(binding) is not RelationBinding
            or binding.kind != relation_kind
            or binding.source.role != role
            or binding.target.role != role
            or binding.source.kind != endpoint_kind
            or binding.target.kind != endpoint_kind
            or binding.source.page_index == binding.target.page_index
            or binding.source == binding.target
            or (
                binding.source.role,
                binding.source.kind,
                binding.source.element_id,
                binding.source.page_index,
            )
            not in available
            or (
                binding.target.role,
                binding.target.kind,
                binding.target.element_id,
                binding.target.page_index,
            )
            not in available
        ):
            return False
    return True


def _chain_digest(
    custody: Custody091Result,
    relation: Relation096Result,
    wiring: Wiring095087Result,
    wrapper: Wrapper094Result,
) -> str:
    payload = json.dumps(
        {
            "custody_091_receipt_sha256": custody.proof.sha256,
            "relation_096_decision_sha256": relation.decision.sha256,
            "relation_096_manifest_sha256": relation.manifest.sha256,
            "relation_096_receipt_sha256": relation.proof.sha256,
            "wiring_095_087_receipt_sha256": wiring.proof.sha256,
            "wrapper_094_receipt_sha256": wrapper.proof.sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def run_no_provider_full_synthetic_rehearsal(
    request: RehearsalRequest, dependencies: RehearsalDependencies
) -> RehearsalResult:
    """Replay the provider-free synthetic dependency chain exactly once."""

    counts = _initial_counts()
    if not _request_is_exact(request):
        return _blocked("INPUT_CONTRACT_BLOCKED", counts)

    try:
        capture = dependencies.capture_executor(request)
    except Exception:
        return _blocked("DEPENDENCY_EXCEPTION_BLOCKED", counts)
    counts["capture"] = 1
    if not _effects_are_zero(capture):
        return _blocked("EXTERNAL_EFFECT_CONTRACT_VIOLATION", counts)
    if not _stage_proof_is_valid(capture):
        return _blocked("DEPENDENCY_CUSTODY_BLOCKED", counts)
    if capture.status != "CAPTURE_FIXTURE_READY":
        return _blocked(capture.reason_code, counts)
    if not _artifacts_are_exact(capture.artifacts):
        return _blocked("CAPTURE_IDENTITY_BLOCKED", counts)

    try:
        custody = dependencies.custody_091(capture)
    except Exception:
        return _blocked("DEPENDENCY_EXCEPTION_BLOCKED", counts)
    counts["custody_091"] = 1
    if not _effects_are_zero(custody):
        return _blocked("EXTERNAL_EFFECT_CONTRACT_VIOLATION", counts)
    if not _stage_proof_is_valid(custody):
        return _blocked("DEPENDENCY_CUSTODY_BLOCKED", counts)
    if custody.status != "CUSTODY_091_VERIFIED":
        return _blocked(custody.reason_code, counts)
    if (
        custody.capture_receipt_sha256 != capture.proof.sha256
        or custody.artifacts != capture.artifacts
    ):
        return _blocked("DEPENDENCY_CUSTODY_BLOCKED", counts)

    try:
        relation = dependencies.relation_096(custody)
    except Exception:
        return _blocked("DEPENDENCY_EXCEPTION_BLOCKED", counts)
    counts["relation_096"] = 1
    if (
        not _stage_proof_is_valid(relation)
        or not _proof_is_valid(relation.manifest)
        or not _proof_is_valid(relation.decision)
    ):
        return _blocked("DEPENDENCY_CUSTODY_BLOCKED", counts)
    if not _effects_are_zero(relation):
        return _blocked("EXTERNAL_EFFECT_CONTRACT_VIOLATION", counts)
    if relation.custody_receipt_sha256 != custody.proof.sha256:
        return _blocked("DEPENDENCY_CUSTODY_BLOCKED", counts)
    if relation.status == "BLOCKED_ON_CROSS_PAGE_BINDING":
        return _blocked(relation.reason_code, counts)
    if relation.status != "RELATION_096_VERIFIED":
        return _blocked(relation.reason_code, counts)
    if not _relation_bindings_are_exact(relation.bindings, custody.artifacts):
        return _blocked("CROSS_PAGE_ENDPOINT_CONTRACT_BLOCKED", counts)

    try:
        wiring = dependencies.wiring_095_087(custody, relation)
    except Exception:
        return _blocked("DEPENDENCY_EXCEPTION_BLOCKED", counts)
    counts["wiring_095_087"] = 1
    if not _effects_are_zero(wiring):
        return _blocked("EXTERNAL_EFFECT_CONTRACT_VIOLATION", counts)
    if not _stage_proof_is_valid(wiring):
        return _blocked("DEPENDENCY_CUSTODY_BLOCKED", counts)
    if (
        wiring.relation_receipt_sha256 != relation.proof.sha256
        or wiring.relation_manifest_sha256 != relation.manifest.sha256
        or wiring.relation_decision_sha256 != relation.decision.sha256
    ):
        return _blocked("DEPENDENCY_CUSTODY_BLOCKED", counts)
    if wiring.status != "WIRING_095_087_VERIFIED":
        return _blocked(wiring.reason_code, counts)

    try:
        wrapper = dependencies.wrapper_094(wiring)
    except Exception:
        return _blocked("DEPENDENCY_EXCEPTION_BLOCKED", counts)
    counts["wrapper_094"] = 1
    if not _effects_are_zero(wrapper):
        return _blocked("EXTERNAL_EFFECT_CONTRACT_VIOLATION", counts)
    if not _stage_proof_is_valid(wrapper):
        return _blocked("DEPENDENCY_CUSTODY_BLOCKED", counts)
    if wrapper.wiring_receipt_sha256 != wiring.proof.sha256:
        return _blocked("DEPENDENCY_CUSTODY_BLOCKED", counts)
    if wrapper.status != "WRAPPER_094_VERIFIED":
        return _blocked(wrapper.reason_code, counts)

    return RehearsalResult(
        status="SYNTHETIC_VERTICAL_REHEARSAL_VERIFIED",
        reason_code="SYNTHETIC_VERTICAL_REHEARSAL_VERIFIED",
        chain_digest_sha256=_chain_digest(custody, relation, wiring, wrapper),
        invocation_counts=dict(counts),
    )
