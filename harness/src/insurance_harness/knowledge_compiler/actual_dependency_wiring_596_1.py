"""Actual public-dependency wiring for the task-local 087 private runner.

The module owns composition only. It deliberately delegates all byte parsing to 091/083,
all relation-receipt and binding replay to 096/086, and all rate-role mapping and admission
to 092. The separately owned 096 dependency is resolved lazily so its absence is a typed,
pre-I/O result instead of an import-time failure.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from dataclasses import dataclass
from typing import Protocol, cast

from insurance_harness.compiler import native_mineru_cloud
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    replay_cross_page_relation_binding_v1,
)
from insurance_harness.knowledge_compiler.private_artifact_admission_runner_596_1 import (
    PrivateAdmissionRunnerResult,
    PrivateArtifactPaths,
    _blocked,
    _emit,
    _is_sha256,
    _parse_cli,
    _read_exact_inputs,
)
from insurance_harness.knowledge_compiler.relation_bound_admission_596_1 import (
    assemble_relation_bound_admission_596_1,
)

_096_MODULE = "insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1"
_096_VALIDATOR = "replay_relation_receipt_596_1"


class IntakeBundlePort(Protocol):
    def __call__(
        self, payloads: tuple[bytes, bytes, bytes]
    ) -> MinerUCaptureBundle5961V1: ...


class RelationBindingReplayPort(Protocol):
    def __call__(self, binding: object) -> object: ...


class ValidatedRelationAdmissionInputsPort(Protocol):
    @property
    def status(self) -> str: ...

    @property
    def bundle_digest_sha256(self) -> str: ...

    @property
    def source_authorities(self) -> tuple[object, ...]: ...

    @property
    def material_profile_resolutions(self) -> tuple[object, ...]: ...

    @property
    def marker_endpoint_mappings(self) -> tuple[object, ...]: ...

    @property
    def relation_binding_provider(self) -> object: ...


class RelationReceiptValidatorPort(Protocol):
    def __call__(
        self,
        receipt_bytes: bytes,
        *,
        bundle: MinerUCaptureBundle5961V1,
        relation_binding_replay: RelationBindingReplayPort,
    ) -> ValidatedRelationAdmissionInputsPort: ...


class RelationAuthorityAdapterPort(Protocol):
    def __call__(
        self,
        receipt_bytes: bytes,
        *,
        capture_payloads: tuple[bytes, bytes, bytes],
        bundle: MinerUCaptureBundle5961V1,
        relation_binding_replay: RelationBindingReplayPort,
    ) -> ValidatedRelationAdmissionInputsPort: ...


class RelationBoundAdmissionResultPort(Protocol):
    @property
    def status(self) -> str: ...

    @property
    def integration_digest_sha256(self) -> str | None: ...

    @property
    def provider_calls(self) -> int: ...

    @property
    def golden_reads(self) -> int: ...


class AdmissionAssemblerPort(Protocol):
    def __call__(
        self,
        *,
        bundle: object,
        source_authorities: tuple[object, ...],
        material_profile_resolutions: tuple[object, ...],
        marker_endpoint_mappings: tuple[object, ...],
        relation_binding_provider: object,
        trusted_builder: object,
    ) -> RelationBoundAdmissionResultPort: ...


@dataclass(frozen=True, slots=True)
class _ActualDependencies:
    intake_bundle: IntakeBundlePort
    validate_relation_receipt: RelationReceiptValidatorPort
    relation_binding_replay: RelationBindingReplayPort
    assemble_admission: AdmissionAssemblerPort
    trusted_builder: object


@dataclass(frozen=True, slots=True)
class _ExecutionDependencies:
    intake_bundle: IntakeBundlePort
    relation_binding_replay: RelationBindingReplayPort
    assemble_admission: AdmissionAssemblerPort
    trusted_builder: object


def _signature_matches(
    value: object,
    expected: tuple[tuple[str, inspect._ParameterKind], ...],
) -> bool:
    if not callable(value):
        return False
    try:
        parameters = tuple(inspect.signature(value).parameters.values())
    except (TypeError, ValueError):
        return False
    return tuple((item.name, item.kind) for item in parameters) == expected


def _dependency_signatures_are_compatible(dependencies: _ActualDependencies) -> bool:
    return (
        _signature_matches(
            dependencies.intake_bundle,
            (("payloads", inspect.Parameter.POSITIONAL_OR_KEYWORD),),
        )
        and _signature_matches(
            dependencies.validate_relation_receipt,
            (
                ("receipt_bytes", inspect.Parameter.POSITIONAL_OR_KEYWORD),
                ("bundle", inspect.Parameter.KEYWORD_ONLY),
                ("relation_binding_replay", inspect.Parameter.KEYWORD_ONLY),
            ),
        )
        and _signature_matches(
            dependencies.relation_binding_replay,
            (("binding", inspect.Parameter.POSITIONAL_OR_KEYWORD),),
        )
        and _signature_matches(
            dependencies.assemble_admission,
            tuple(
                (name, inspect.Parameter.KEYWORD_ONLY)
                for name in (
                    "bundle",
                    "source_authorities",
                    "material_profile_resolutions",
                    "marker_endpoint_mappings",
                    "relation_binding_provider",
                    "trusted_builder",
                )
            ),
        )
    )


def _resolve_dependencies() -> _ActualDependencies | None:
    try:
        relation_module = importlib.import_module(_096_MODULE)
        relation_validator = getattr(relation_module, _096_VALIDATOR)
        if not callable(relation_validator):
            return None
        execution = _resolve_execution_dependencies()
        if execution is None:
            return None
        dependencies = _ActualDependencies(
            intake_bundle=execution.intake_bundle,
            validate_relation_receipt=relation_validator,
            relation_binding_replay=execution.relation_binding_replay,
            assemble_admission=execution.assemble_admission,
            trusted_builder=execution.trusted_builder,
        )
    except (AttributeError, ImportError, RuntimeError, TypeError, ValueError):
        return None
    return dependencies if _dependency_signatures_are_compatible(dependencies) else None


def _resolve_execution_dependencies() -> _ExecutionDependencies | None:
    """Resolve the stable non-receipt public graph used by both actual entry points."""

    dependencies = _ExecutionDependencies(
        intake_bundle=intake_mineru_capture_bundle_596_1,
        relation_binding_replay=cast(
            RelationBindingReplayPort, replay_cross_page_relation_binding_v1
        ),
        assemble_admission=cast(
            AdmissionAssemblerPort, assemble_relation_bound_admission_596_1
        ),
        trusted_builder=native_mineru_cloud.build_mineru_parsed_document_v1,
    )
    compatible = (
        _signature_matches(
            dependencies.intake_bundle,
            (("payloads", inspect.Parameter.POSITIONAL_OR_KEYWORD),),
        )
        and _signature_matches(
            dependencies.relation_binding_replay,
            (("binding", inspect.Parameter.POSITIONAL_OR_KEYWORD),),
        )
        and _signature_matches(
            dependencies.assemble_admission,
            tuple(
                (name, inspect.Parameter.KEYWORD_ONLY)
                for name in (
                    "bundle",
                    "source_authorities",
                    "material_profile_resolutions",
                    "marker_endpoint_mappings",
                    "relation_binding_provider",
                    "trusted_builder",
                )
            ),
        )
    )
    return dependencies if compatible else None


def _validated_relation_inputs(
    value: ValidatedRelationAdmissionInputsPort,
    *,
    expected_bundle_digest_sha256: str,
) -> tuple[
    tuple[object, ...],
    tuple[object, ...],
    tuple[object, ...],
    object,
] | PrivateAdmissionRunnerResult:
    try:
        status = value.status
        if status == "DEPENDENCY_UNAVAILABLE":
            return _blocked("DEPENDENCY_UNAVAILABLE")
        if status == "BLOCKED_ON_CROSS_PAGE_BINDING":
            return _blocked("BLOCKED_ON_CROSS_PAGE_BINDING")
        if (
            status != "VALIDATED"
            or value.bundle_digest_sha256 != expected_bundle_digest_sha256
            or not _is_sha256(value.bundle_digest_sha256)
            or type(value.source_authorities) is not tuple
            or len(value.source_authorities) != 3
            or type(value.material_profile_resolutions) is not tuple
            or len(value.material_profile_resolutions) != 3
            or type(value.marker_endpoint_mappings) is not tuple
            or len(value.marker_endpoint_mappings) < 2
            or not callable(value.relation_binding_provider)
        ):
            return _blocked("RELATION_VALIDATION_BLOCKED")
        return (
            value.source_authorities,
            value.material_profile_resolutions,
            value.marker_endpoint_mappings,
            value.relation_binding_provider,
        )
    except (AttributeError, TypeError, ValueError):
        return _blocked("RELATION_VALIDATION_BLOCKED")


def _validated_admission(
    result: RelationBoundAdmissionResultPort,
) -> PrivateAdmissionRunnerResult:
    try:
        if (
            type(result.provider_calls) is not int
            or type(result.golden_reads) is not int
            or result.provider_calls != 0
            or result.golden_reads != 0
        ):
            return _blocked("EXTERNAL_EFFECT_CONTRACT_VIOLATION")
        if result.status == "BLOCKED_ON_RELATION_BINDING":
            return _blocked("BLOCKED_ON_CROSS_PAGE_BINDING")
        if (
            result.status != "READY_FOR_QUALITY_FALSIFICATION"
            or not _is_sha256(result.integration_digest_sha256)
        ):
            return _blocked("ADMISSION_BLOCKED")
        return PrivateAdmissionRunnerResult(
            status="COMPOSITION_SEAM_VERIFIED",
            common_receipt_digest_sha256=result.integration_digest_sha256,
        )
    except (AttributeError, TypeError, ValueError):
        return _blocked("ADMISSION_BLOCKED")


def _run_actual_dependency_wiring_with_authority_596_1(
    paths: PrivateArtifactPaths,
    *,
    dependencies: _ExecutionDependencies,
    validate_relation_authority: RelationAuthorityAdapterPort,
) -> PrivateAdmissionRunnerResult:
    try:
        payloads = _read_exact_inputs(paths)
    except Exception:
        return _blocked("INPUT_CONTRACT_BLOCKED")
    try:
        bundle = dependencies.intake_bundle(
            (payloads["terms"], payloads["brochure"], payloads["rate_table"])
        )
        if type(bundle) is not MinerUCaptureBundle5961V1:
            return _blocked("INTAKE_VALIDATION_BLOCKED")
    except Exception:
        return _blocked("INTAKE_VALIDATION_BLOCKED")
    try:
        capture_payloads = (
            payloads["terms"],
            payloads["brochure"],
            payloads["rate_table"],
        )
        relation = validate_relation_authority(
            payloads["relation_receipt"],
            capture_payloads=capture_payloads,
            bundle=bundle,
            relation_binding_replay=dependencies.relation_binding_replay,
        )
    except Exception:
        return _blocked("RELATION_VALIDATION_BLOCKED")
    relation_inputs = _validated_relation_inputs(
        relation,
        expected_bundle_digest_sha256=bundle.bundle_digest_sha256,
    )
    if isinstance(relation_inputs, PrivateAdmissionRunnerResult):
        return relation_inputs
    authorities, resolutions, marker_maps, relation_provider = relation_inputs
    try:
        admitted = dependencies.assemble_admission(
            bundle=bundle,
            source_authorities=authorities,
            material_profile_resolutions=resolutions,
            marker_endpoint_mappings=marker_maps,
            relation_binding_provider=relation_provider,
            trusted_builder=dependencies.trusted_builder,
        )
    except Exception:
        return _blocked("ADMISSION_BLOCKED")
    return _validated_admission(admitted)


def run_actual_dependency_wiring_with_relation_authority_596_1(
    paths: PrivateArtifactPaths,
    *,
    validate_relation_authority: RelationAuthorityAdapterPort,
) -> PrivateAdmissionRunnerResult:
    """Preserve the 095/087 boundary while accepting one exact 100 authority adapter."""

    try:
        parameters = tuple(inspect.signature(validate_relation_authority).parameters.values())
        expected = (
            ("receipt_bytes", inspect.Parameter.POSITIONAL_OR_KEYWORD),
            ("capture_payloads", inspect.Parameter.KEYWORD_ONLY),
            ("bundle", inspect.Parameter.KEYWORD_ONLY),
            ("relation_binding_replay", inspect.Parameter.KEYWORD_ONLY),
        )
        if tuple((item.name, item.kind) for item in parameters) != expected:
            return _blocked("DEPENDENCY_UNAVAILABLE")
    except (TypeError, ValueError):
        return _blocked("DEPENDENCY_UNAVAILABLE")
    dependencies = _resolve_execution_dependencies()
    if dependencies is None:
        return _blocked("DEPENDENCY_UNAVAILABLE")
    return _run_actual_dependency_wiring_with_authority_596_1(
        paths,
        dependencies=dependencies,
        validate_relation_authority=validate_relation_authority,
    )


def run_actual_dependency_wiring_596_1(
    paths: PrivateArtifactPaths,
) -> PrivateAdmissionRunnerResult:
    """Run the original exact public composition graph, or fail closed."""

    dependencies = _resolve_dependencies()
    if dependencies is None:
        return _blocked("DEPENDENCY_UNAVAILABLE")

    def legacy_authority(
        receipt_bytes: bytes,
        *,
        capture_payloads: tuple[bytes, bytes, bytes],
        bundle: MinerUCaptureBundle5961V1,
        relation_binding_replay: RelationBindingReplayPort,
    ) -> ValidatedRelationAdmissionInputsPort:
        del capture_payloads
        return dependencies.validate_relation_receipt(
            receipt_bytes,
            bundle=bundle,
            relation_binding_replay=relation_binding_replay,
        )

    return _run_actual_dependency_wiring_with_authority_596_1(
        paths,
        dependencies=_ExecutionDependencies(
            intake_bundle=dependencies.intake_bundle,
            relation_binding_replay=dependencies.relation_binding_replay,
            assemble_admission=dependencies.assemble_admission,
            trusted_builder=dependencies.trusted_builder,
        ),
        validate_relation_authority=legacy_authority,
    )


def main(argv: tuple[str, ...] | None = None) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    paths = _parse_cli(arguments)
    if paths is None:
        result = _blocked("INPUT_CONTRACT_BLOCKED")
    else:
        result = run_actual_dependency_wiring_596_1(paths)
    _emit(result)
    return 0 if result.status == "COMPOSITION_SEAM_VERIFIED" else 2


__all__ = [
    "RelationAuthorityAdapterPort",
    "ValidatedRelationAdmissionInputsPort",
    "run_actual_dependency_wiring_596_1",
    "run_actual_dependency_wiring_with_relation_authority_596_1",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
