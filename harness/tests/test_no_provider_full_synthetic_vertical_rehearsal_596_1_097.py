from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

import pytest

from insurance_harness.knowledge_compiler import (
    no_provider_full_synthetic_vertical_rehearsal_596_1 as subject,
)

ArtifactFact = subject.ArtifactFact
BoundProof = subject.BoundProof
CaptureResult = subject.CaptureResult
Custody091Result = subject.Custody091Result
EndpointFact = subject.EndpointFact
RehearsalDependencies = subject.RehearsalDependencies
Relation096Result = subject.Relation096Result
RelationBinding = subject.RelationBinding
RehearsalRequest = subject.RehearsalRequest
Wiring095087Result = subject.Wiring095087Result
Wrapper094Result = subject.Wrapper094Result
run_no_provider_full_synthetic_rehearsal = subject.run_no_provider_full_synthetic_rehearsal

_SOURCE_BY_ROLE = {
    "terms": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
    "brochure": "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    "rate_table": "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
}


def _proof(label: str, **bindings: str) -> BoundProof:
    payload = json.dumps(
        {"label": label, **bindings}, sort_keys=True, separators=(",", ":")
    ).encode()
    return BoundProof(preimage=payload, sha256=hashlib.sha256(payload).hexdigest())


_TERMS_ENDPOINTS = (
    EndpointFact(role="terms", kind="block", element_id="terms-block-17", page_index=16),
    EndpointFact(role="terms", kind="block", element_id="terms-block-18", page_index=17),
)
_RATE_ENDPOINTS = (
    EndpointFact(role="rate_table", kind="table", element_id="rate-table-1", page_index=0),
    EndpointFact(role="rate_table", kind="table", element_id="rate-table-2", page_index=1),
)
_ARTIFACTS = tuple(
    ArtifactFact(
        role=role,
        source_sha256=_SOURCE_BY_ROLE[role],
        artifact_sha256=hashlib.sha256(f"synthetic-{role}".encode()).hexdigest(),
        endpoints=(
            _TERMS_ENDPOINTS
            if role == "terms"
            else _RATE_ENDPOINTS
            if role == "rate_table"
            else (
                EndpointFact(
                    role="brochure",
                    kind="block",
                    element_id="brochure-block-1",
                    page_index=0,
                ),
            )
        ),
    )
    for role in ("terms", "brochure", "rate_table")
)
_SINGLE_ENDPOINT_ARTIFACTS = tuple(
    replace(
        artifact,
        endpoints=(artifact.endpoints[:1] if artifact.role != "brochure" else artifact.endpoints),
    )
    for artifact in _ARTIFACTS
)


def _relation_bindings() -> tuple[RelationBinding, ...]:
    return (
        RelationBinding(kind="section", source=_TERMS_ENDPOINTS[0], target=_TERMS_ENDPOINTS[1]),
        RelationBinding(kind="table", source=_RATE_ENDPOINTS[0], target=_RATE_ENDPOINTS[1]),
    )


@dataclass
class _Capture:
    status: str = "CAPTURE_FIXTURE_READY"
    reason_code: str = "CAPTURE_FIXTURE_READY"
    artifacts: tuple[ArtifactFact, ...] = _ARTIFACTS
    calls: list[RehearsalRequest] = field(default_factory=list)

    def __call__(self, request: RehearsalRequest) -> CaptureResult:
        self.calls.append(request)
        proof = _proof("capture", product_version=request.product_version)
        return CaptureResult(
            status=self.status,
            reason_code=self.reason_code,
            proof=proof,
            artifacts=self.artifacts,
            provider_calls=0,
            model_calls=0,
            golden_reads=0,
            db_writes=0,
            pg_writes=0,
            weknora_writes=0,
            live_calls=0,
            retry_count=0,
            fallback_count=0,
        )


@dataclass
class _Custody:
    status: str = "CUSTODY_091_VERIFIED"
    reason_code: str = "CUSTODY_091_VERIFIED"
    calls: list[CaptureResult] = field(default_factory=list)

    def __call__(self, capture: CaptureResult) -> Custody091Result:
        self.calls.append(capture)
        proof = _proof("custody-091", capture_receipt_sha256=capture.proof.sha256)
        return Custody091Result(
            status=self.status,
            reason_code=self.reason_code,
            proof=proof,
            capture_receipt_sha256=capture.proof.sha256,
            artifacts=capture.artifacts,
        )


@dataclass
class _Relation:
    blocked: bool = False
    calls: list[Custody091Result] = field(default_factory=list)

    def __call__(self, custody: Custody091Result) -> Relation096Result:
        self.calls.append(custody)
        manifest = _proof("relation-manifest", custody_receipt_sha256=custody.proof.sha256)
        decision = _proof("relation-decision", manifest_sha256=manifest.sha256)
        proof = _proof(
            "relation-096",
            custody_receipt_sha256=custody.proof.sha256,
            manifest_sha256=manifest.sha256,
            decision_sha256=decision.sha256,
        )
        if self.blocked:
            return Relation096Result(
                status="BLOCKED_ON_CROSS_PAGE_BINDING",
                reason_code="BLOCKED_ON_CROSS_PAGE_BINDING",
                proof=proof,
                custody_receipt_sha256=custody.proof.sha256,
                manifest=manifest,
                decision=decision,
                bindings=(),
            )
        return Relation096Result(
            status="RELATION_096_VERIFIED",
            reason_code="RELATION_096_VERIFIED",
            proof=proof,
            custody_receipt_sha256=custody.proof.sha256,
            manifest=manifest,
            decision=decision,
            bindings=_relation_bindings(),
        )


@dataclass
class _Wiring:
    status: str = "WIRING_095_087_VERIFIED"
    reason_code: str = "WIRING_095_087_VERIFIED"
    calls: list[tuple[Custody091Result, Relation096Result]] = field(default_factory=list)

    def __call__(
        self, custody: Custody091Result, relation: Relation096Result
    ) -> Wiring095087Result:
        self.calls.append((custody, relation))
        proof = _proof(
            "wiring-095-087",
            relation_receipt_sha256=relation.proof.sha256,
            manifest_sha256=relation.manifest.sha256,
            decision_sha256=relation.decision.sha256,
        )
        return Wiring095087Result(
            status=self.status,
            reason_code=self.reason_code,
            proof=proof,
            relation_receipt_sha256=relation.proof.sha256,
            relation_manifest_sha256=relation.manifest.sha256,
            relation_decision_sha256=relation.decision.sha256,
        )


@dataclass
class _Wrapper:
    status: str = "WRAPPER_094_VERIFIED"
    reason_code: str = "WRAPPER_094_VERIFIED"
    calls: list[Wiring095087Result] = field(default_factory=list)

    def __call__(self, wiring: Wiring095087Result) -> Wrapper094Result:
        self.calls.append(wiring)
        proof = _proof("wrapper-094", wiring_receipt_sha256=wiring.proof.sha256)
        return Wrapper094Result(
            status=self.status,
            reason_code=self.reason_code,
            proof=proof,
            wiring_receipt_sha256=wiring.proof.sha256,
            provider_calls=0,
            model_calls=0,
            golden_reads=0,
            db_writes=0,
            pg_writes=0,
            weknora_writes=0,
            live_calls=0,
            retry_count=0,
            fallback_count=0,
        )


class _FailingPort(Protocol):
    status: str
    reason_code: str


class _CallRecorder(Protocol):
    @property
    def calls(self) -> Sequence[object]: ...


def _call_count(port: _CallRecorder) -> int:
    return len(port.calls)


def _deps(
    *, blocked_relation: bool = False
) -> tuple[
    RehearsalDependencies,
    tuple[_Capture, _Custody, _Relation, _Wiring, _Wrapper],
]:
    capture = _Capture(
        artifacts=_SINGLE_ENDPOINT_ARTIFACTS if blocked_relation else _ARTIFACTS
    )
    ports = (capture, _Custody(), _Relation(blocked=blocked_relation), _Wiring(), _Wrapper())
    return RehearsalDependencies(*ports), ports


def _request() -> RehearsalRequest:
    return RehearsalRequest(product_version="596-1", ordered_source_sha256_by_role=_SOURCE_BY_ROLE)


def test_current_single_endpoint_fact_stays_blocked_without_inference() -> None:
    deps, ports = _deps(blocked_relation=True)

    result = run_no_provider_full_synthetic_rehearsal(_request(), deps)

    assert result.status == result.reason_code == "BLOCKED_ON_CROSS_PAGE_BINDING"
    assert result.chain_digest_sha256 is None
    assert [_call_count(port) for port in ports] == [1, 1, 1, 0, 0]
    assert result.provider_calls == result.model_calls == result.golden_reads == 0


def test_complete_endpoint_protocol_fixture_reaches_compatibility_only_success() -> None:
    deps, ports = _deps()

    result = run_no_provider_full_synthetic_rehearsal(_request(), deps)

    assert result.status == "SYNTHETIC_VERTICAL_REHEARSAL_VERIFIED"
    assert result.reason_code == "SYNTHETIC_VERTICAL_REHEARSAL_VERIFIED"
    assert result.chain_digest_sha256 is not None
    assert [_call_count(port) for port in ports] == [1, 1, 1, 1, 1]
    assert result.invocation_counts == {
        "capture": 1,
        "custody_091": 1,
        "relation_096": 1,
        "wiring_095_087": 1,
        "wrapper_094": 1,
    }
    assert "READY" not in result.status and "ADMIT" not in result.status


@pytest.mark.parametrize("role", ["terms", "brochure", "rate_table"])
def test_source_identity_drift_stops_before_capture(role: str) -> None:
    deps, ports = _deps()
    sources = dict(_SOURCE_BY_ROLE)
    sources[role] = "f" * 64

    result = run_no_provider_full_synthetic_rehearsal(
        replace(_request(), ordered_source_sha256_by_role=sources), deps
    )

    assert result.status == "INPUT_CONTRACT_BLOCKED"
    assert [_call_count(port) for port in ports] == [0, 0, 0, 0, 0]


def test_reordered_source_mapping_stops_before_capture() -> None:
    deps, ports = _deps()
    reordered = {
        "brochure": _SOURCE_BY_ROLE["brochure"],
        "terms": _SOURCE_BY_ROLE["terms"],
        "rate_table": _SOURCE_BY_ROLE["rate_table"],
    }

    result = run_no_provider_full_synthetic_rehearsal(
        replace(_request(), ordered_source_sha256_by_role=reordered), deps
    )

    assert result.status == "INPUT_CONTRACT_BLOCKED"
    assert [_call_count(port) for port in ports] == [0, 0, 0, 0, 0]


@pytest.mark.parametrize(
    ("stage", "status"),
    [
        ("capture", "CAPTURE_SYNTHETIC_BLOCKED"),
        ("custody", "CUSTODY_091_BLOCKED"),
        ("wiring", "WIRING_095_087_BLOCKED"),
        ("wrapper", "WRAPPER_094_BLOCKED"),
    ],
)
def test_safe_fail_closed_reason_is_preserved_and_later_stages_are_zero(
    stage: str, status: str
) -> None:
    capture, custody, relation, wiring, wrapper = (
        _Capture(),
        _Custody(),
        _Relation(),
        _Wiring(),
        _Wrapper(),
    )
    target: _FailingPort
    if stage == "capture":
        target = capture
    elif stage == "custody":
        target = custody
    elif stage == "wiring":
        target = wiring
    else:
        target = wrapper
    target.status = target.reason_code = status
    deps = RehearsalDependencies(capture, custody, relation, wiring, wrapper)

    result = run_no_provider_full_synthetic_rehearsal(_request(), deps)

    assert result.status == result.reason_code == status
    expected = {
        "capture": [1, 0, 0, 0, 0],
        "custody": [1, 1, 0, 0, 0],
        "wiring": [1, 1, 1, 1, 0],
        "wrapper": [1, 1, 1, 1, 1],
    }[stage]
    assert [
        _call_count(port) for port in (capture, custody, relation, wiring, wrapper)
    ] == expected


def test_recomputed_relation_hash_drift_blocks_before_wiring() -> None:
    class _DriftedRelation(_Relation):
        def __call__(self, custody: Custody091Result) -> Relation096Result:
            result = super().__call__(custody)
            return replace(result, manifest=replace(result.manifest, sha256="f" * 64))

    ports = (_Capture(), _Custody(), _DriftedRelation(), _Wiring(), _Wrapper())
    result = run_no_provider_full_synthetic_rehearsal(
        _request(), RehearsalDependencies(*ports)
    )

    assert result.status == "DEPENDENCY_CUSTODY_BLOCKED"
    assert [_call_count(port) for port in ports] == [1, 1, 1, 0, 0]


def test_each_predecessor_binding_drift_stops_the_next_stage() -> None:
    class _DriftedCustody(_Custody):
        def __call__(self, capture: CaptureResult) -> Custody091Result:
            return replace(super().__call__(capture), capture_receipt_sha256="f" * 64)

    custody_ports = (_Capture(), _DriftedCustody(), _Relation(), _Wiring(), _Wrapper())
    custody_result = run_no_provider_full_synthetic_rehearsal(
        _request(), RehearsalDependencies(*custody_ports)
    )
    assert custody_result.status == "DEPENDENCY_CUSTODY_BLOCKED"
    assert [_call_count(port) for port in custody_ports] == [1, 1, 0, 0, 0]

    class _DriftedWiring(_Wiring):
        def __call__(
            self, custody: Custody091Result, relation: Relation096Result
        ) -> Wiring095087Result:
            return replace(
                super().__call__(custody, relation),
                relation_decision_sha256="f" * 64,
            )

    wiring_ports = (_Capture(), _Custody(), _Relation(), _DriftedWiring(), _Wrapper())
    wiring_result = run_no_provider_full_synthetic_rehearsal(
        _request(), RehearsalDependencies(*wiring_ports)
    )
    assert wiring_result.status == "DEPENDENCY_CUSTODY_BLOCKED"
    assert [_call_count(port) for port in wiring_ports] == [1, 1, 1, 1, 0]

    class _DriftedWrapper(_Wrapper):
        def __call__(self, wiring: Wiring095087Result) -> Wrapper094Result:
            return replace(super().__call__(wiring), wiring_receipt_sha256="f" * 64)

    wrapper_ports = (_Capture(), _Custody(), _Relation(), _Wiring(), _DriftedWrapper())
    wrapper_result = run_no_provider_full_synthetic_rehearsal(
        _request(), RehearsalDependencies(*wrapper_ports)
    )
    assert wrapper_result.status == "DEPENDENCY_CUSTODY_BLOCKED"
    assert [_call_count(port) for port in wrapper_ports] == [1, 1, 1, 1, 1]


@pytest.mark.parametrize(
    "binding",
    [
        RelationBinding(
            kind="section", source=_TERMS_ENDPOINTS[0], target=_TERMS_ENDPOINTS[0]
        ),
        RelationBinding(
            kind="table",
            source=_RATE_ENDPOINTS[0],
            target=replace(_RATE_ENDPOINTS[1], element_id="foreign-table"),
        ),
        RelationBinding(
            kind="table",
            source=_RATE_ENDPOINTS[0],
            target=replace(_RATE_ENDPOINTS[1], page_index=0),
        ),
    ],
)
def test_endpoint_same_page_or_identity_drift_blocks_without_guessing(
    binding: RelationBinding,
) -> None:
    class _DriftedRelation(_Relation):
        def __call__(self, custody: Custody091Result) -> Relation096Result:
            result = super().__call__(custody)
            bindings = list(result.bindings)
            bindings[0 if binding.kind == "section" else 1] = binding
            return replace(result, bindings=tuple(bindings))

    ports = (_Capture(), _Custody(), _DriftedRelation(), _Wiring(), _Wrapper())
    result = run_no_provider_full_synthetic_rehearsal(
        _request(), RehearsalDependencies(*ports)
    )

    assert result.status == "CROSS_PAGE_ENDPOINT_CONTRACT_BLOCKED"
    assert [_call_count(port) for port in ports] == [1, 1, 1, 0, 0]


def test_external_effect_counter_blocks_success() -> None:
    class _WritingWrapper(_Wrapper):
        def __call__(self, wiring: Wiring095087Result) -> Wrapper094Result:
            return replace(super().__call__(wiring), weknora_writes=1)

    ports = (_Capture(), _Custody(), _Relation(), _Wiring(), _WritingWrapper())
    result = run_no_provider_full_synthetic_rehearsal(
        _request(), RehearsalDependencies(*ports)
    )

    assert result.status == "EXTERNAL_EFFECT_CONTRACT_VIOLATION"
    assert result.chain_digest_sha256 is None


def test_chain_digest_changes_when_a_stage_receipt_changes() -> None:
    deps, _ = _deps()
    first = run_no_provider_full_synthetic_rehearsal(_request(), deps)

    class _DifferentWrapper(_Wrapper):
        def __call__(self, wiring: Wiring095087Result) -> Wrapper094Result:
            result = super().__call__(wiring)
            proof = _proof("wrapper-094-v2", wiring_receipt_sha256=wiring.proof.sha256)
            return replace(result, proof=proof)

    second_deps = RehearsalDependencies(
        _Capture(), _Custody(), _Relation(), _Wiring(), _DifferentWrapper()
    )
    second = run_no_provider_full_synthetic_rehearsal(_request(), second_deps)

    assert first.status == second.status == "SYNTHETIC_VERTICAL_REHEARSAL_VERIFIED"
    assert first.chain_digest_sha256 != second.chain_digest_sha256
