from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from insurance_harness.compiler import native_mineru_cloud
from insurance_harness.knowledge_compiler import actual_dependency_wiring_596_1 as subject
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    replay_cross_page_relation_binding_v1,
)
from insurance_harness.knowledge_compiler.private_artifact_admission_runner_596_1 import (
    PrivateArtifactPaths,
)
from insurance_harness.knowledge_compiler.relation_bound_admission_596_1 import (
    assemble_relation_bound_admission_596_1,
)

_A = "a" * 64
_B = "b" * 64


@dataclass(frozen=True)
class _Source:
    role: str


@dataclass(frozen=True)
class _RelationInputs:
    status: str = "VALIDATED"
    bundle_digest_sha256: str = _A
    source_authorities: tuple[object, ...] = (object(), object(), object())
    material_profile_resolutions: tuple[object, ...] = (object(), object(), object())
    marker_endpoint_mappings: tuple[object, ...] = (object(), object())
    relation_binding_provider: object = lambda *args, **kwargs: (args, kwargs)


@dataclass(frozen=True)
class _Admission:
    status: str
    integration_digest_sha256: str | None = None
    provider_calls: int = 0
    golden_reads: int = 0


def _private_file(path: Path, value: bytes) -> Path:
    path.write_bytes(value)
    path.chmod(0o600)
    return path


def _paths(tmp_path: Path) -> PrivateArtifactPaths:
    return PrivateArtifactPaths(
        terms=_private_file(tmp_path / "terms.custody", b"terms"),
        brochure=_private_file(tmp_path / "brochure.custody", b"brochure"),
        rate_table=_private_file(tmp_path / "rate.custody", b"rate"),
        relation_receipt=_private_file(tmp_path / "relation.receipt", b"relation"),
    )


def _dependencies(
    calls: list[str],
    *,
    relation: _RelationInputs | None = None,
    admission: _Admission | None = None,
) -> subject._ActualDependencies:
    exact_bundle = MinerUCaptureBundle5961V1.model_construct(
        contract="mineru-capture-intake-596-1.v1",
        sources=(_Source("terms"), _Source("brochure"), _Source("rate")),
        bundle_digest_sha256=_A,
    )
    exact_relation = relation or _RelationInputs()
    exact_admission = admission or _Admission(
        "READY_FOR_QUALITY_FALSIFICATION", integration_digest_sha256=_B
    )

    def intake(payloads: tuple[bytes, bytes, bytes]) -> MinerUCaptureBundle5961V1:
        calls.append("intake")
        assert payloads == (b"terms", b"brochure", b"rate")
        return exact_bundle

    def replay(binding: object) -> object:
        calls.append("unexpected-replay")
        return binding

    def validate_relation(
        receipt_bytes: bytes,
        *,
        bundle: MinerUCaptureBundle5961V1,
        relation_binding_replay: Callable[[object], object],
    ) -> subject.ValidatedRelationAdmissionInputsPort:
        calls.append("relation")
        assert receipt_bytes == b"relation"
        assert bundle is exact_bundle
        assert relation_binding_replay is replay
        return cast(subject.ValidatedRelationAdmissionInputsPort, exact_relation)

    def assemble(**values: object) -> subject.RelationBoundAdmissionResultPort:
        calls.append("admission")
        assert values["bundle"] is exact_bundle
        assert values["source_authorities"] is exact_relation.source_authorities
        assert (
            values["material_profile_resolutions"]
            is exact_relation.material_profile_resolutions
        )
        assert values["marker_endpoint_mappings"] is exact_relation.marker_endpoint_mappings
        assert values["relation_binding_provider"] is exact_relation.relation_binding_provider
        assert values["trusted_builder"] is _trusted_builder
        assert tuple(item.role for item in exact_bundle.sources) == (
            "terms",
            "brochure",
            "rate",
        )
        return cast(subject.RelationBoundAdmissionResultPort, exact_admission)

    def _trusted_builder(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("synthetic seam must not invoke the trusted builder directly")

    return subject._ActualDependencies(
        intake_bundle=intake,
        validate_relation_receipt=validate_relation,
        relation_binding_replay=replay,
        assemble_admission=assemble,
        trusted_builder=_trusted_builder,
    )


def test_missing_096_dependency_blocks_before_file_io(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    opened: list[object] = []
    monkeypatch.setattr(subject, "_resolve_dependencies", lambda: None)
    monkeypatch.setattr(subject, "_read_exact_inputs", lambda paths: opened.append(paths))

    result = subject.run_actual_dependency_wiring_596_1(
        PrivateArtifactPaths(
            terms=tmp_path / "missing-terms",
            brochure=tmp_path / "missing-brochure",
            rate_table=tmp_path / "missing-rate",
            relation_receipt=tmp_path / "missing-relation",
        )
    )

    assert result.status == "DEPENDENCY_UNAVAILABLE"
    assert result.artifacts == ()
    assert result.common_receipt_digest_sha256 is None
    assert opened == []


def test_frozen_096_public_replay_signature_is_not_a_bytes_to_092_adapter(
    tmp_path: Path,
) -> None:
    """The exact 096 candidate accepts a DTO only and supplies no 092 authorities."""

    assert subject._096_MODULE.endswith("relation_receipt_bridge_596_1")
    assert subject._096_VALIDATOR == "replay_relation_receipt_596_1"
    assert subject._resolve_dependencies() is None
    result = subject.run_actual_dependency_wiring_596_1(
        PrivateArtifactPaths(
            terms=tmp_path / "unopened-terms",
            brochure=tmp_path / "unopened-brochure",
            rate_table=tmp_path / "unopened-rate",
            relation_receipt=tmp_path / "unopened-relation",
        )
    )
    assert result.status == "DEPENDENCY_UNAVAILABLE"
    assert result.artifacts == ()


def test_exact_public_call_graph_reaches_composition_only_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(subject, "_resolve_dependencies", lambda: _dependencies(calls))

    result = subject.run_actual_dependency_wiring_596_1(_paths(tmp_path))

    assert calls == ["intake", "relation", "admission"]
    assert result.status == "COMPOSITION_SEAM_VERIFIED"
    assert result.common_receipt_digest_sha256 == _B
    assert result.artifacts == ()
    assert result.provider_calls == 0
    assert result.golden_reads == 0
    assert "READY" not in json.dumps(result.to_wire())
    assert "ADMIT" not in json.dumps(result.to_wire())


@pytest.mark.parametrize("mutation", ["mode", "symlink", "duplicate"])
def test_087_private_boundary_blocks_before_dependency_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation: str
) -> None:
    paths = _paths(tmp_path)
    if mutation == "mode":
        paths.brochure.chmod(0o640)
    elif mutation == "symlink":
        replacement = tmp_path / "linked-relation"
        paths.relation_receipt.rename(replacement)
        paths.relation_receipt.symlink_to(replacement)
    else:
        paths = PrivateArtifactPaths(
            terms=paths.terms,
            brochure=paths.brochure,
            rate_table=paths.rate_table,
            relation_receipt=paths.terms,
        )
    calls: list[str] = []
    monkeypatch.setattr(subject, "_resolve_dependencies", lambda: _dependencies(calls))

    result = subject.run_actual_dependency_wiring_596_1(paths)

    assert result.status == "INPUT_CONTRACT_BLOCKED"
    assert calls == []
    assert result.common_receipt_digest_sha256 is None


def test_relation_bundle_identity_drift_blocks_before_092(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        subject,
        "_resolve_dependencies",
        lambda: _dependencies(calls, relation=_RelationInputs(bundle_digest_sha256=_B)),
    )

    result = subject.run_actual_dependency_wiring_596_1(_paths(tmp_path))

    assert calls == ["intake", "relation"]
    assert result.status == "RELATION_VALIDATION_BLOCKED"
    assert result.common_receipt_digest_sha256 is None


def test_reordered_capture_paths_fail_at_exact_083_bundle_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _paths(tmp_path)
    reordered = PrivateArtifactPaths(
        terms=paths.brochure,
        brochure=paths.terms,
        rate_table=paths.rate_table,
        relation_receipt=paths.relation_receipt,
    )
    calls: list[str] = []
    monkeypatch.setattr(subject, "_resolve_dependencies", lambda: _dependencies(calls))

    result = subject.run_actual_dependency_wiring_596_1(reordered)

    assert calls == ["intake"]
    assert result.status == "INTAKE_VALIDATION_BLOCKED"
    assert result.common_receipt_digest_sha256 is None


def test_malformed_intake_dto_is_typed_and_never_reaches_relation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []

    def malformed_intake(payloads: tuple[bytes, bytes, bytes]) -> MinerUCaptureBundle5961V1:
        calls.append("intake")
        assert payloads == (b"terms", b"brochure", b"rate")
        return cast(MinerUCaptureBundle5961V1, object())

    dependencies = _dependencies(calls)
    monkeypatch.setattr(
        subject,
        "_resolve_dependencies",
        lambda: subject._ActualDependencies(
            intake_bundle=malformed_intake,
            validate_relation_receipt=dependencies.validate_relation_receipt,
            relation_binding_replay=dependencies.relation_binding_replay,
            assemble_admission=dependencies.assemble_admission,
            trusted_builder=dependencies.trusted_builder,
        ),
    )

    result = subject.run_actual_dependency_wiring_596_1(_paths(tmp_path))

    assert calls == ["intake"]
    assert result.status == "INTAKE_VALIDATION_BLOCKED"
    assert result.common_receipt_digest_sha256 is None


def test_cross_page_block_is_propagated_without_partial_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        subject,
        "_resolve_dependencies",
        lambda: _dependencies(
            calls,
            relation=_RelationInputs(status="BLOCKED_ON_CROSS_PAGE_BINDING"),
        ),
    )

    result = subject.run_actual_dependency_wiring_596_1(_paths(tmp_path))

    assert calls == ["intake", "relation"]
    assert result.status == "BLOCKED_ON_CROSS_PAGE_BINDING"
    assert result.artifacts == ()
    assert result.common_receipt_digest_sha256 is None


def test_092_relation_block_is_stably_mapped_to_cross_page_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        subject,
        "_resolve_dependencies",
        lambda: _dependencies(calls, admission=_Admission("BLOCKED_ON_RELATION_BINDING")),
    )

    result = subject.run_actual_dependency_wiring_596_1(_paths(tmp_path))

    assert calls == ["intake", "relation", "admission"]
    assert result.status == "BLOCKED_ON_CROSS_PAGE_BINDING"
    assert result.common_receipt_digest_sha256 is None


@pytest.mark.parametrize("stage", ["intake", "relation", "admission"])
def test_dependency_exceptions_are_sanitized(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stage: str
) -> None:
    calls: list[str] = []
    dependencies = _dependencies(calls)

    def fail(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise RuntimeError("SECRET sk-proj-leak https://private.invalid /private/hidden")

    if stage == "intake":
        dependencies = subject._ActualDependencies(
            intake_bundle=cast(subject.IntakeBundlePort, fail),
            validate_relation_receipt=dependencies.validate_relation_receipt,
            relation_binding_replay=dependencies.relation_binding_replay,
            assemble_admission=dependencies.assemble_admission,
            trusted_builder=dependencies.trusted_builder,
        )
        expected = "INTAKE_VALIDATION_BLOCKED"
    elif stage == "relation":
        dependencies = subject._ActualDependencies(
            intake_bundle=dependencies.intake_bundle,
            validate_relation_receipt=cast(subject.RelationReceiptValidatorPort, fail),
            relation_binding_replay=dependencies.relation_binding_replay,
            assemble_admission=dependencies.assemble_admission,
            trusted_builder=dependencies.trusted_builder,
        )
        expected = "RELATION_VALIDATION_BLOCKED"
    else:
        dependencies = subject._ActualDependencies(
            intake_bundle=dependencies.intake_bundle,
            validate_relation_receipt=dependencies.validate_relation_receipt,
            relation_binding_replay=dependencies.relation_binding_replay,
            assemble_admission=cast(subject.AdmissionAssemblerPort, fail),
            trusted_builder=dependencies.trusted_builder,
        )
        expected = "ADMISSION_BLOCKED"
    monkeypatch.setattr(subject, "_resolve_dependencies", lambda: dependencies)

    result = subject.run_actual_dependency_wiring_596_1(_paths(tmp_path))
    wire = json.dumps(result.to_wire(), sort_keys=True)

    assert result.status == expected
    assert result.common_receipt_digest_sha256 is None
    assert "SECRET" not in wire
    assert "https" not in wire
    assert "/private" not in wire


def test_nonzero_external_counter_blocks_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        subject,
        "_resolve_dependencies",
        lambda: _dependencies(
            calls,
            admission=_Admission(
                "READY_FOR_QUALITY_FALSIFICATION",
                integration_digest_sha256=_B,
                provider_calls=1,
            ),
        ),
    )

    result = subject.run_actual_dependency_wiring_596_1(_paths(tmp_path))

    assert result.status == "EXTERNAL_EFFECT_CONTRACT_VIOLATION"
    assert result.common_receipt_digest_sha256 is None


def test_cli_rejects_extra_argument_without_resolving_dependencies(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    resolved: list[bool] = []
    monkeypatch.setattr(subject, "_resolve_dependencies", lambda: resolved.append(True))

    exit_code = subject.main(("--unexpected", "value"))
    wire = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert wire["status"] == "INPUT_CONTRACT_BLOCKED"
    assert resolved == []


def test_production_dependency_signature_mismatch_fails_closed() -> None:
    def bad_validator(receipt_bytes: bytes) -> object:
        return receipt_bytes

    def intake(payloads: tuple[bytes, bytes, bytes]) -> MinerUCaptureBundle5961V1:
        return cast(MinerUCaptureBundle5961V1, payloads)

    def replay(binding: object) -> object:
        return binding

    def assemble(
        *,
        bundle: object,
        source_authorities: tuple[object, ...],
        material_profile_resolutions: tuple[object, ...],
        marker_endpoint_mappings: tuple[object, ...],
        relation_binding_provider: object,
        trusted_builder: object,
    ) -> subject.RelationBoundAdmissionResultPort:
        del (
            bundle,
            source_authorities,
            material_profile_resolutions,
            marker_endpoint_mappings,
            relation_binding_provider,
            trusted_builder,
        )
        return cast(subject.RelationBoundAdmissionResultPort, object())

    dependencies = subject._ActualDependencies(
        intake_bundle=intake,
        validate_relation_receipt=cast(subject.RelationReceiptValidatorPort, bad_validator),
        relation_binding_replay=replay,
        assemble_admission=assemble,
        trusted_builder=lambda *args, **kwargs: (args, kwargs),
    )

    assert subject._dependency_signatures_are_compatible(dependencies) is False


def test_current_083_086_092_public_signatures_are_compatible() -> None:
    def validate_relation(
        receipt_bytes: bytes,
        *,
        bundle: MinerUCaptureBundle5961V1,
        relation_binding_replay: subject.RelationBindingReplayPort,
    ) -> subject.ValidatedRelationAdmissionInputsPort:
        del receipt_bytes, bundle, relation_binding_replay
        return cast(subject.ValidatedRelationAdmissionInputsPort, object())

    dependencies = subject._ActualDependencies(
        intake_bundle=intake_mineru_capture_bundle_596_1,
        validate_relation_receipt=validate_relation,
        relation_binding_replay=cast(
            subject.RelationBindingReplayPort, replay_cross_page_relation_binding_v1
        ),
        assemble_admission=cast(
            subject.AdmissionAssemblerPort, assemble_relation_bound_admission_596_1
        ),
        trusted_builder=native_mineru_cloud.build_mineru_parsed_document_v1,
    )

    assert subject._dependency_signatures_are_compatible(dependencies) is True


def test_private_files_remain_exact_mode_after_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    paths = _paths(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(subject, "_resolve_dependencies", lambda: _dependencies(calls))

    result = subject.run_actual_dependency_wiring_596_1(paths)

    assert result.status == "COMPOSITION_SEAM_VERIFIED"
    assert all((os.stat(path).st_mode & 0o777) == 0o600 for _, path in paths.ordered())
