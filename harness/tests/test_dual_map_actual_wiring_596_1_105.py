"""Focused executable contract for OpenSpec105 actual dual-map wiring."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from insurance_harness.knowledge_compiler import actual_dependency_wiring_596_1 as actual
from insurance_harness.knowledge_compiler import dual_map_actual_wiring_596_1 as subject
from insurance_harness.knowledge_compiler.marker_authority_envelope_596_1 import (
    MarkerAuthorityEnvelopeV1,
    export_marker_authority_envelope_596_1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.private_artifact_admission_runner_596_1 import (
    PrivateAdmissionRunnerResult,
    PrivateArtifactPaths,
)
from insurance_harness.knowledge_compiler.relation_bound_admission_596_1 import (
    TypedMarkerEndpointMapV1,
)
from insurance_harness.knowledge_compiler.relation_receipt_authority_adapter_596_1 import (
    validate_relation_receipt_authority_inputs_with_marker_map_builder_596_1,
)
from insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1 import (
    DerivedRelationReceipt5961V1,
)
from tests import test_actual_dependency_wiring_596_1_095 as actual_cases
from tests import test_marker_authority_envelope_596_1_101 as envelope_cases
from tests import test_mineru_capture_intake_596_1_083 as intake_cases
from tests import test_relation_receipt_authority_adapter_596_1_100 as authority_cases


def _private(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    path.chmod(0o600)
    return path


def _fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> tuple[
    subject.DualMapActualWiringInputs5961V1,
    bytes,
    tuple[bytes, bytes, bytes],
    tuple[TypedMarkerEndpointMapV1, TypedMarkerEndpointMapV1],
]:
    captures = tuple(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        for value in (
            envelope_cases._capture(
                envelope_cases.TERMS_SHA, (("cross_page", 0, "text"),)
            ),
            envelope_cases._capture(envelope_cases.BROCHURE_SHA),
            envelope_cases._capture(
                envelope_cases.RATE_SHA, (("cross_page", 0, "table"),)
            ),
        )
    )
    monkeypatch.setattr(intake_cases, "_inputs", lambda: captures)
    receipt, captures, authorities, resolutions = authority_cases._inputs(monkeypatch)
    paths = PrivateArtifactPaths(
        terms=_private(tmp_path / "terms.custody", captures[0]),
        brochure=_private(tmp_path / "brochure.custody", captures[1]),
        rate_table=_private(tmp_path / "rate.custody", captures[2]),
        relation_receipt=_private(tmp_path / "relation.receipt", receipt),
    )
    inputs = subject.DualMapActualWiringInputs5961V1(
        paths=paths,
        source_authorities=authorities,
        material_profile_resolutions=resolutions,
        rate_table_replay=object(),
        terms_section_replay=object(),
    )
    return inputs, receipt, captures, authority_cases._future_marker_maps()


def test_current_missing_103_fails_before_any_actual_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        subject,
        "_resolve_dependencies",
        lambda: subject._DependencyResolution(
            dependencies=None,
            unavailable_status="TERMS_SECTION_BINDING_UNAVAILABLE",
        ),
    )

    result = subject.run_dual_map_actual_wiring_596_1(
        subject.DualMapActualWiringInputs5961V1(
            paths=object(),
            source_authorities=(),
            material_profile_resolutions=(),
            rate_table_replay=object(),
            terms_section_replay=object(),
        )
    )

    assert result.status == "TERMS_SECTION_BINDING_UNAVAILABLE"
    assert result.provider_calls == result.golden_reads == 0
    assert result.common_receipt_digest_sha256 is None


def test_100_narrow_export_retains_real_receipt_and_092_context_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, captures, authorities, resolutions = authority_cases._inputs(monkeypatch)
    maps = authority_cases._future_marker_maps()
    calls: list[str] = []

    def dual_builder(
        *, bundle: MinerUCaptureBundle5961V1, receipt: DerivedRelationReceipt5961V1
    ) -> tuple[TypedMarkerEndpointMapV1, TypedMarkerEndpointMapV1]:
        assert bundle == intake_mineru_capture_bundle_596_1(captures)
        assert receipt.receipt_digest_sha256
        calls.append("dual-map")
        return maps

    context = validate_relation_receipt_authority_inputs_with_marker_map_builder_596_1(
        receipt,
        capture_payloads=captures,
        source_authorities=authorities,
        material_profile_resolutions=resolutions,
        marker_map_builder=dual_builder,
    )

    assert context.status == "VALIDATED"
    assert context.bundle_digest_sha256 == context.bundle.bundle_digest_sha256
    assert context.marker_endpoint_mappings == maps
    assert calls == ["dual-map"]


def test_095_narrow_export_preserves_private_file_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    paths = actual_cases._paths(tmp_path)
    paths.brochure.chmod(0o640)
    calls: list[str] = []
    dependencies = actual_cases._dependencies(calls)
    monkeypatch.setattr(
        actual,
        "_resolve_execution_dependencies",
        lambda: actual._ExecutionDependencies(
            intake_bundle=dependencies.intake_bundle,
            relation_binding_replay=dependencies.relation_binding_replay,
            assemble_admission=dependencies.assemble_admission,
            trusted_builder=dependencies.trusted_builder,
        ),
    )

    def adapter(
        receipt_bytes: bytes,
        *,
        capture_payloads: tuple[bytes, bytes, bytes],
        bundle: MinerUCaptureBundle5961V1,
        relation_binding_replay: Callable[[object], object],
    ) -> actual.ValidatedRelationAdmissionInputsPort:
        del receipt_bytes, capture_payloads, bundle, relation_binding_replay
        calls.append("authority-adapter")
        return cast(actual.ValidatedRelationAdmissionInputsPort, object())

    result = actual.run_actual_dependency_wiring_with_relation_authority_596_1(
        paths,
        validate_relation_authority=adapter,
    )

    assert result.status == "INPUT_CONTRACT_BLOCKED"
    assert result.artifacts == ()
    assert calls == []


def _synthetic_dependencies(
    *,
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    maps: tuple[TypedMarkerEndpointMapV1, TypedMarkerEndpointMapV1],
    captures: tuple[bytes, bytes, bytes],
    expected_inputs: subject.DualMapActualWiringInputs5961V1,
) -> subject._DualMapDependencies:
    bundle = intake_mineru_capture_bundle_596_1(captures)

    def intake(
        payloads: tuple[bytes, bytes, bytes],
    ) -> MinerUCaptureBundle5961V1:
        assert payloads == captures
        return bundle

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
    ) -> actual.RelationBoundAdmissionResultPort:
        del trusted_builder
        calls.append("092")
        assert bundle is not None
        assert source_authorities == expected_inputs.source_authorities
        assert material_profile_resolutions == expected_inputs.material_profile_resolutions
        assert marker_endpoint_mappings == maps
        assert callable(relation_binding_provider)
        return cast(
            actual.RelationBoundAdmissionResultPort,
            actual_cases._Admission(
                "READY_FOR_QUALITY_FALSIFICATION",
                integration_digest_sha256="f" * 64,
            ),
        )

    def trusted_builder(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise AssertionError("synthetic seam never invokes the parser builder directly")

    monkeypatch.setattr(
        actual,
        "_resolve_execution_dependencies",
        lambda: actual._ExecutionDependencies(
            intake_bundle=intake,
            relation_binding_replay=replay,
            assemble_admission=assemble,
            trusted_builder=trusted_builder,
        ),
    )

    def export(paths: tuple[Path, Path, Path]) -> MarkerAuthorityEnvelopeV1:
        calls.append("101")
        return export_marker_authority_envelope_596_1(paths)

    def terms(
        *,
        envelope: MarkerAuthorityEnvelopeV1,
        bundle: MinerUCaptureBundle5961V1,
        receipt: DerivedRelationReceipt5961V1,
        replay: object,
    ) -> TypedMarkerEndpointMapV1:
        calls.append("103")
        assert envelope.bundle_digest_sha256 == bundle.bundle_digest_sha256
        assert receipt.receipt_digest_sha256 and replay is expected_inputs.terms_section_replay
        return maps[0]

    def rate(
        *,
        envelope: MarkerAuthorityEnvelopeV1,
        bundle: MinerUCaptureBundle5961V1,
        receipt: DerivedRelationReceipt5961V1,
        replay: object,
    ) -> TypedMarkerEndpointMapV1:
        calls.append("098")
        assert envelope.bundle_digest_sha256 == bundle.bundle_digest_sha256
        assert receipt.receipt_digest_sha256 and replay is expected_inputs.rate_table_replay
        return maps[1]

    def actual_execution(
        paths: PrivateArtifactPaths,
        *,
        validate_relation_authority: actual.RelationAuthorityAdapterPort,
    ) -> PrivateAdmissionRunnerResult:
        calls.append("095/087")
        return actual.run_actual_dependency_wiring_with_relation_authority_596_1(
            paths,
            validate_relation_authority=validate_relation_authority,
        )

    return subject._DualMapDependencies(
        export_marker_authority=export,
        replay_terms_section_map=terms,
        replay_rate_table_map=rate,
        validate_relation_authority=cast(
            subject.AuthorityValidatorPort,
            validate_relation_receipt_authority_inputs_with_marker_map_builder_596_1,
        ),
        run_actual_execution=actual_execution,
    )


def test_future_complete_protocol_uses_distinct_maps_and_actual_entry_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inputs, _, captures, maps = _fixture(monkeypatch, tmp_path)
    calls: list[str] = []
    dependencies = _synthetic_dependencies(
        monkeypatch=monkeypatch,
        calls=calls,
        maps=maps,
        captures=captures,
        expected_inputs=inputs,
    )
    monkeypatch.setattr(
        subject,
        "_resolve_dependencies",
        lambda: subject._DependencyResolution(dependencies=dependencies),
    )

    result = subject.run_dual_map_actual_wiring_596_1(inputs)

    assert result.status == "COMPOSITION_SEAM_VERIFIED"
    assert result.common_receipt_digest_sha256 == "f" * 64
    assert result.provider_calls == result.golden_reads == 0
    assert calls == ["101", "095/087", "103", "098", "092"]
    assert "ADMIT" not in json.dumps(result.to_wire())
    assert "READY" not in json.dumps(result.to_wire())


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("swapped", "BLOCKED_ON_CROSS_PAGE_BINDING"),
        ("duplicate", "BLOCKED_ON_CROSS_PAGE_BINDING"),
        ("foreign-source", "BLOCKED_ON_CROSS_PAGE_BINDING"),
        ("port-secret", "BLOCKED_ON_CROSS_PAGE_BINDING"),
    ],
)
def test_map_role_source_or_port_drift_stops_without_partial_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
    expected: str,
) -> None:
    inputs, _, captures, maps = _fixture(monkeypatch, tmp_path)
    calls: list[str] = []
    selected = maps
    if mutation == "swapped":
        selected = (maps[1], maps[0])
    elif mutation == "duplicate":
        selected = (maps[1], maps[1])
    elif mutation == "foreign-source":
        values = maps[0].model_dump(mode="python", exclude={"replay_digest_sha256"})
        values["source_sha256"] = "a" * 64
        selected = (
            TypedMarkerEndpointMapV1.model_construct(
                **values,
                replay_digest_sha256=maps[0].replay_digest_sha256,
            ),
            maps[1],
        )
    dependencies = _synthetic_dependencies(
        monkeypatch=monkeypatch,
        calls=calls,
        maps=selected,
        captures=captures,
        expected_inputs=inputs,
    )
    if mutation == "port-secret":
        def broken(**_: object) -> TypedMarkerEndpointMapV1:
            raise RuntimeError("secret=https://provider.invalid /private/raw")

        dependencies = replace(dependencies, replay_terms_section_map=broken)
    monkeypatch.setattr(
        subject,
        "_resolve_dependencies",
        lambda: subject._DependencyResolution(dependencies=dependencies),
    )

    result = subject.run_dual_map_actual_wiring_596_1(inputs)

    assert result.status == expected
    assert result.common_receipt_digest_sha256 is None
    assert result.provider_calls == result.golden_reads == 0
    rendered = f"{result!r} {result.to_wire()}"
    assert all(value not in rendered for value in ("secret", "https://", "/private/"))
    assert calls.count("095/087") == 1
    assert "092" not in calls


def test_production_resolver_rejects_protocol_fake_without_file_reads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    inputs, _, _, _ = _fixture(monkeypatch, tmp_path)
    monkeypatch.setattr(
        subject,
        "_resolve_exact_103_terms_port",
        lambda: (lambda **kwargs: kwargs),
    )
    monkeypatch.setattr(subject, "_signature_matches", lambda *args: False)

    result = subject.run_dual_map_actual_wiring_596_1(inputs)

    assert result.status == "TERMS_SECTION_BINDING_UNAVAILABLE"
    paths = cast(PrivateArtifactPaths, inputs.paths)
    assert all((os.stat(path).st_mode & 0o777) == 0o600 for _, path in paths.ordered())
