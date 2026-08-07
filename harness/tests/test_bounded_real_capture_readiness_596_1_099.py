from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import replace

import pytest

from insurance_harness.knowledge_compiler import bounded_real_capture_readiness_596_1 as subject


def _proof(label: str, **bindings: str) -> subject.BoundProof:
    payload = json.dumps(
        {"label": label, **bindings}, sort_keys=True, separators=(",", ":")
    ).encode()
    return subject.BoundProof(payload, hashlib.sha256(payload).hexdigest())


def _hash(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _authority() -> tuple[subject.FrozenDependencyIdentity, ...]:
    return tuple(
        subject.FrozenDependencyIdentity(
            dependency_id=dependency_id,
            contract_id=f"test-only-{dependency_id}.v1",
            contract_version="v1",
            implementation_blob_sha256=_hash(f"blob-{dependency_id}"),
            api_schema_sha256=_hash(f"schema-{dependency_id}"),
            canonical_preimage_sha256=_proof(f"canonical-{dependency_id}").sha256,
            context_sha256=_hash(f"context-{dependency_id}"),
            policy_sha256=_hash(f"policy-{dependency_id}"),
            replay_sha256=_hash(f"replay-{dependency_id}"),
        )
        for dependency_id in subject.DEPENDENCY_ORDER
    )


def _artifacts() -> tuple[subject.PrivateArtifactEvidence, ...]:
    return tuple(
        subject.PrivateArtifactEvidence(
            role=role,
            source_sha256=subject.SOURCE_SHA256_BY_ROLE[role],
            outer_sha256=_hash(f"outer-{role}"),
            path_identity_sha256=_hash(f"path-{role}"),
            file_mode=0o600,
            parent_mode=0o700,
            is_regular=True,
            is_symlink=False,
        )
        for role in subject.ROLE_ORDER
    )


def _dependencies(
    *,
    evidence_class: str = "TEST_ONLY_COMPLETE_FIXTURE",
    endpoint_state: str = "COMPLETE_ENDPOINT_PAIR_VERIFIED",
) -> tuple[subject.DependencyEvidence, ...]:
    authority = _authority()
    prior_receipt: str | None = None
    evidence: list[subject.DependencyEvidence] = []
    for identity in authority:
        canonical = _proof(f"canonical-{identity.dependency_id}")
        receipt = _proof(
            f"receipt-{identity.dependency_id}",
            predecessor_receipt_sha256=prior_receipt or "ROOT",
        )
        evidence.append(
            subject.DependencyEvidence(
                dependency_id=identity.dependency_id,
                evidence_class=evidence_class,
                adapter_present=True,
                contract_id=identity.contract_id,
                contract_version=identity.contract_version,
                implementation_blob_sha256=identity.implementation_blob_sha256,
                api_schema_sha256=identity.api_schema_sha256,
                canonical_preimage=canonical,
                receipt=receipt,
                predecessor_receipt_sha256=prior_receipt,
                context_sha256=identity.context_sha256,
                policy_sha256=identity.policy_sha256,
                replay_sha256=identity.replay_sha256,
                ordered_roles=subject.ROLE_ORDER,
                endpoint_state=(
                    endpoint_state
                    if identity.dependency_id == "098"
                    else "NOT_APPLICABLE"
                ),
                endpoint_derivation_input_sha256=(
                    prior_receipt if identity.dependency_id == "098" else None
                ),
                binding_state=(
                    "VERIFIED_BINDING" if identity.dependency_id == "086" else "NOT_APPLICABLE"
                ),
                relation_state=(
                    "VERIFIED_RELATION_RECEIPT"
                    if identity.dependency_id == "096"
                    else "NOT_APPLICABLE"
                ),
                dependency_map=(
                    ("091", "098", "086", "096", "087")
                    if identity.dependency_id == "095_087"
                    else ()
                ),
                wrapper_invocation_cap=1,
                retry_budget=0,
                fallback_enabled=False,
                external_effects=0,
            )
        )
        prior_receipt = receipt.sha256
    return tuple(evidence)


def _bundle(
    *,
    dependencies: tuple[subject.DependencyEvidence, ...] | None = None,
    artifacts: tuple[subject.PrivateArtifactEvidence, ...] | None = None,
) -> subject.ReadinessBundle:
    return subject.ReadinessBundle(
        product_version="596-1",
        artifacts=artifacts or _artifacts(),
        dependencies=dependencies or _dependencies(),
    )


def test_current_formal_gate_blocks_on_earliest_unfrozen_public_authority() -> None:
    result = subject.evaluate_bounded_capture_readiness(_bundle())

    assert result.status == "FROZEN_DEPENDENCY_AUTHORITY_UNAVAILABLE_091"
    assert result.reason_code == result.status
    assert result.evidence_class == "BLOCKED"
    assert result.capture_authorized is False
    assert result.evaluated_dependencies == ()


@pytest.mark.parametrize("evidence_class", ["PROTOCOL_FAKE", "SYNTHETIC_ONLY"])
def test_fake_or_synthetic_evidence_never_opens_formal_gate(evidence_class: str) -> None:
    dependencies = _dependencies(evidence_class=evidence_class)

    result = subject.evaluate_test_only_future_readiness(
        _bundle(dependencies=dependencies), _authority()
    )

    assert result.status == "DEPENDENCY_EVIDENCE_CLASS_BLOCKED_091"
    assert result.capture_authorized is False


def test_complete_future_fixture_is_mechanically_ready_but_test_only() -> None:
    result = subject.evaluate_test_only_future_readiness(_bundle(), _authority())

    assert result.status == "READY_FOR_ONE_BOUNDED_CAPTURE"
    assert result.reason_code == result.status
    assert result.evidence_class == "TEST_ONLY"
    assert result.capture_authorized is False
    assert result.evaluated_dependencies == subject.DEPENDENCY_ORDER
    assert len(result.dependency_identities) == 6
    encoded = json.dumps(result.to_wire(), sort_keys=True)
    assert "/" not in encoded
    assert "credential" not in encoded.lower()
    assert "body" not in encoded.lower()


def test_old_single_endpoint_marker_stays_blocked_before_086() -> None:
    dependencies = _dependencies(endpoint_state="SINGLE_ENDPOINT_ONLY")

    result = subject.evaluate_test_only_future_readiness(
        _bundle(dependencies=dependencies), _authority()
    )

    assert result.status == "BLOCKED_ON_CROSS_PAGE_BINDING"
    assert result.evaluated_dependencies == ("091", "098")
    assert result.capture_authorized is False


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda item: replace(item, implementation_blob_sha256="f" * 64),
            "DEPENDENCY_IDENTITY_DRIFT_096",
        ),
        (
            lambda item: replace(item, api_schema_sha256="f" * 64),
            "DEPENDENCY_IDENTITY_DRIFT_096",
        ),
        (
            lambda item: replace(item, context_sha256="f" * 64),
            "DEPENDENCY_CONTEXT_DRIFT_096",
        ),
        (
            lambda item: replace(item, policy_sha256="f" * 64),
            "DEPENDENCY_POLICY_DRIFT_096",
        ),
        (
            lambda item: replace(item, replay_sha256="f" * 64),
            "DEPENDENCY_REPLAY_DRIFT_096",
        ),
        (
            lambda item: replace(item, predecessor_receipt_sha256="f" * 64),
            "DEPENDENCY_PREDECESSOR_DRIFT_096",
        ),
    ],
)
def test_dependency_identity_and_context_drift_fail_at_exact_boundary(
    mutate: Callable[[subject.DependencyEvidence], subject.DependencyEvidence],
    reason: str,
) -> None:
    dependencies = list(_dependencies())
    dependencies[3] = mutate(dependencies[3])

    result = subject.evaluate_test_only_future_readiness(
        _bundle(dependencies=tuple(dependencies)), _authority()
    )

    assert result.status == reason
    assert result.evaluated_dependencies == ("091", "098", "086", "096")


def test_preimage_hash_drift_and_missing_adapter_fail_closed() -> None:
    dependencies = list(_dependencies())
    dependencies[0] = replace(
        dependencies[0],
        canonical_preimage=replace(dependencies[0].canonical_preimage, sha256="f" * 64),
    )
    drift = subject.evaluate_test_only_future_readiness(
        _bundle(dependencies=tuple(dependencies)), _authority()
    )
    assert drift.status == "DEPENDENCY_PREIMAGE_DRIFT_091"

    dependencies = list(_dependencies())
    dependencies[0] = replace(dependencies[0], adapter_present=False)
    missing = subject.evaluate_test_only_future_readiness(
        _bundle(dependencies=tuple(dependencies)), _authority()
    )
    assert missing.status == "DEPENDENCY_IMPLEMENTATION_UNAVAILABLE_091"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda item: replace(item, file_mode=0o644),
        lambda item: replace(item, parent_mode=0o755),
        lambda item: replace(item, is_regular=False),
        lambda item: replace(item, is_symlink=True),
    ],
)
def test_artifact_permission_or_type_drift_blocks_before_dependencies(
    mutate: Callable[[subject.PrivateArtifactEvidence], subject.PrivateArtifactEvidence],
) -> None:
    artifacts = list(_artifacts())
    artifacts[0] = mutate(artifacts[0])

    result = subject.evaluate_test_only_future_readiness(
        _bundle(artifacts=tuple(artifacts)), _authority()
    )

    assert result.status == "PRIVATE_ARTIFACT_ACCESS_BLOCKED"
    assert result.evaluated_dependencies == ()


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda item: replace(item, wrapper_invocation_cap=2),
            "WRAPPER_POLICY_BLOCKED_094",
        ),
        (lambda item: replace(item, retry_budget=1), "WRAPPER_POLICY_BLOCKED_094"),
        (
            lambda item: replace(item, fallback_enabled=True),
            "WRAPPER_POLICY_BLOCKED_094",
        ),
        (
            lambda item: replace(item, external_effects=1),
            "EXTERNAL_EFFECT_CONTRACT_VIOLATION",
        ),
    ],
)
def test_wrapper_policy_or_external_effect_drift_blocks(
    mutate: Callable[[subject.DependencyEvidence], subject.DependencyEvidence],
    expected: str,
) -> None:
    dependencies = list(_dependencies())
    dependencies[-1] = mutate(dependencies[-1])

    result = subject.evaluate_test_only_future_readiness(
        _bundle(dependencies=tuple(dependencies)), _authority()
    )

    assert result.status == expected
    assert result.capture_authorized is False
