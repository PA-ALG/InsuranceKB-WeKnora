"""Task-local dual-map authority wiring for the 596-1 actual execution seam."""

from __future__ import annotations

import importlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, cast

from pydantic import ValidationError

from insurance_harness.compiler.material_profiles import MaterialProfileResolution
from insurance_harness.knowledge_compiler.actual_dependency_wiring_596_1 import (
    RelationAuthorityAdapterPort,
    ValidatedRelationAdmissionInputsPort,
    run_actual_dependency_wiring_with_relation_authority_596_1,
)
from insurance_harness.knowledge_compiler.marker_authority_envelope_596_1 import (
    MarkerAuthorityEnvelopeV1,
    MarkerAuthorityExportError,
    export_marker_authority_envelope_596_1,
    recompute_marker_authority_envelope_sha256,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
)
from insurance_harness.knowledge_compiler.private_artifact_admission_runner_596_1 import (
    PrivateAdmissionRunnerResult,
    PrivateArtifactPaths,
)
from insurance_harness.knowledge_compiler.relation_bound_admission_596_1 import (
    SourceAdmissionAuthorityV1,
    TypedMarkerEndpointMapV1,
)
from insurance_harness.knowledge_compiler.relation_receipt_authority_adapter_596_1 import (
    RelationReceiptAuthorityAdapterError,
    ValidatedRelationAdmissionInputs5961V1,
    validate_relation_receipt_authority_inputs_with_marker_map_builder_596_1,
)
from insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1 import (
    DerivedRelationReceipt5961V1,
)

_TERMS_MODULE = (
    "insurance_harness.knowledge_compiler.terms_section_endpoint_pair_bridge_596_1"
)
_TERMS_SYMBOL = "replay_terms_section_092_marker_map_596_1"
_RATE_MODULE = "insurance_harness.knowledge_compiler.marker_endpoint_pair_bridge_596_1"
_RATE_SYMBOL = "replay_rate_table_092_marker_map_596_1"
_HEX = frozenset("0123456789abcdef")

WiringStatus = Literal[
    "TERMS_SECTION_BINDING_UNAVAILABLE",
    "DEPENDENCY_UNAVAILABLE",
    "BLOCKED_ON_CROSS_PAGE_BINDING",
    "COMPOSITION_SEAM_VERIFIED",
]


@dataclass(frozen=True, slots=True)
class DualMapActualWiringInputs5961V1:
    """Exact external authorities consumed by the task-local composer."""

    paths: object = field(repr=False)
    source_authorities: tuple[object, ...] = field(repr=False)
    material_profile_resolutions: tuple[object, ...] = field(repr=False)
    rate_table_replay: object = field(repr=False)
    terms_section_replay: object = field(repr=False)


@dataclass(frozen=True, slots=True)
class DualMapActualWiringResultV1:
    status: WiringStatus
    common_receipt_digest_sha256: str | None = None
    provider_calls: Literal[0] = 0
    golden_reads: Literal[0] = 0

    def to_wire(self) -> dict[str, object]:
        return {
            "common_receipt_digest_sha256": self.common_receipt_digest_sha256,
            "golden_reads": self.golden_reads,
            "provider_calls": self.provider_calls,
            "status": self.status,
        }


class MarkerAuthorityExportPort(Protocol):
    def __call__(self, paths: tuple[Path, Path, Path]) -> MarkerAuthorityEnvelopeV1: ...


class MarkerMapReplayPort(Protocol):
    def __call__(
        self,
        *,
        envelope: MarkerAuthorityEnvelopeV1,
        bundle: MinerUCaptureBundle5961V1,
        receipt: DerivedRelationReceipt5961V1,
        replay: object,
    ) -> TypedMarkerEndpointMapV1: ...


class AuthorityValidatorPort(Protocol):
    def __call__(
        self,
        receipt_bytes: bytes,
        *,
        capture_payloads: tuple[bytes, bytes, bytes] | object,
        source_authorities: tuple[SourceAdmissionAuthorityV1, ...] | object,
        material_profile_resolutions: tuple[MaterialProfileResolution, ...] | object,
        marker_map_builder: Callable[..., object],
    ) -> ValidatedRelationAdmissionInputs5961V1: ...


class ActualExecutionPort(Protocol):
    def __call__(
        self,
        paths: PrivateArtifactPaths,
        *,
        validate_relation_authority: RelationAuthorityAdapterPort,
    ) -> PrivateAdmissionRunnerResult: ...


@dataclass(frozen=True, slots=True)
class _DualMapDependencies:
    export_marker_authority: MarkerAuthorityExportPort
    replay_terms_section_map: MarkerMapReplayPort
    replay_rate_table_map: MarkerMapReplayPort
    validate_relation_authority: AuthorityValidatorPort
    run_actual_execution: ActualExecutionPort


@dataclass(frozen=True, slots=True)
class _DependencyResolution:
    dependencies: _DualMapDependencies | None
    unavailable_status: Literal[
        "TERMS_SECTION_BINDING_UNAVAILABLE", "DEPENDENCY_UNAVAILABLE"
    ] = "DEPENDENCY_UNAVAILABLE"


class _DependencyCallError(ValueError):
    """Fixed, detail-free boundary for task-local dependency ports."""


def _call_dependency[T](call: Callable[[], T]) -> T:
    try:
        return call()
    except Exception:
        raise _DependencyCallError from None


def _is_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(item in _HEX for item in value)


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


def _resolve_symbol(module_name: str, symbol_name: str) -> object | None:
    try:
        module = importlib.import_module(module_name)
        return cast(object, getattr(module, symbol_name))
    except (AttributeError, ImportError, RuntimeError, TypeError, ValueError):
        return None


def _resolve_exact_103_terms_port() -> object | None:
    return _resolve_symbol(_TERMS_MODULE, _TERMS_SYMBOL)


def _resolve_dependencies() -> _DependencyResolution:
    terms = _resolve_exact_103_terms_port()
    map_signature = tuple(
        (name, inspect.Parameter.KEYWORD_ONLY)
        for name in ("envelope", "bundle", "receipt", "replay")
    )
    if not _signature_matches(terms, map_signature):
        return _DependencyResolution(
            dependencies=None,
            unavailable_status="TERMS_SECTION_BINDING_UNAVAILABLE",
        )
    rate = _resolve_symbol(_RATE_MODULE, _RATE_SYMBOL)
    dependencies = _DualMapDependencies(
        export_marker_authority=export_marker_authority_envelope_596_1,
        replay_terms_section_map=cast(MarkerMapReplayPort, terms),
        replay_rate_table_map=cast(MarkerMapReplayPort, rate),
        validate_relation_authority=cast(
            AuthorityValidatorPort,
            validate_relation_receipt_authority_inputs_with_marker_map_builder_596_1,
        ),
        run_actual_execution=run_actual_dependency_wiring_with_relation_authority_596_1,
    )
    compatible = (
        _signature_matches(
            dependencies.export_marker_authority,
            (("paths", inspect.Parameter.POSITIONAL_OR_KEYWORD),),
        )
        and _signature_matches(dependencies.replay_rate_table_map, map_signature)
        and _signature_matches(
            dependencies.validate_relation_authority,
            (
                ("receipt_bytes", inspect.Parameter.POSITIONAL_OR_KEYWORD),
                ("capture_payloads", inspect.Parameter.KEYWORD_ONLY),
                ("source_authorities", inspect.Parameter.KEYWORD_ONLY),
                ("material_profile_resolutions", inspect.Parameter.KEYWORD_ONLY),
                ("marker_map_builder", inspect.Parameter.KEYWORD_ONLY),
            ),
        )
        and _signature_matches(
            dependencies.run_actual_execution,
            (
                ("paths", inspect.Parameter.POSITIONAL_OR_KEYWORD),
                ("validate_relation_authority", inspect.Parameter.KEYWORD_ONLY),
            ),
        )
    )
    return _DependencyResolution(dependencies=dependencies if compatible else None)


def _blocked(status: WiringStatus) -> DualMapActualWiringResultV1:
    return DualMapActualWiringResultV1(status=status)


def _validated_envelope(
    dependencies: _DualMapDependencies,
    paths: PrivateArtifactPaths,
) -> MarkerAuthorityEnvelopeV1:
    envelope = MarkerAuthorityEnvelopeV1.model_validate(
        _call_dependency(
            lambda: dependencies.export_marker_authority(
                (paths.terms, paths.brochure, paths.rate_table)
            )
        )
    )
    if (
        envelope.relation_authority != "UNBOUND"
        or envelope.envelope_sha256
        != recompute_marker_authority_envelope_sha256(envelope)
        or tuple(source.role for source in envelope.marker_sources) != ("terms", "rate")
        or envelope.marker_sources[0].source_sha256 != envelope.bundle_preimage.source_sha256[0]
        or envelope.marker_sources[1].source_sha256 != envelope.bundle_preimage.source_sha256[2]
    ):
        raise ValueError
    return envelope


def _result_from_actual(value: PrivateAdmissionRunnerResult) -> DualMapActualWiringResultV1:
    try:
        if value.provider_calls != 0 or value.golden_reads != 0:
            return _blocked("BLOCKED_ON_CROSS_PAGE_BINDING")
        if value.status == "COMPOSITION_SEAM_VERIFIED" and _is_sha256(
            value.common_receipt_digest_sha256
        ):
            return DualMapActualWiringResultV1(
                status="COMPOSITION_SEAM_VERIFIED",
                common_receipt_digest_sha256=value.common_receipt_digest_sha256,
            )
        if value.status == "DEPENDENCY_UNAVAILABLE":
            return _blocked("DEPENDENCY_UNAVAILABLE")
        return _blocked("BLOCKED_ON_CROSS_PAGE_BINDING")
    except (AttributeError, TypeError, ValueError):
        return _blocked("BLOCKED_ON_CROSS_PAGE_BINDING")


def run_dual_map_actual_wiring_596_1(
    inputs: DualMapActualWiringInputs5961V1,
) -> DualMapActualWiringResultV1:
    """Compose exact public authorities without parsing or creating authority in 105."""

    resolution = _resolve_dependencies()
    dependencies = resolution.dependencies
    if dependencies is None:
        return _blocked(resolution.unavailable_status)
    try:
        if not isinstance(inputs.paths, PrivateArtifactPaths):
            raise ValueError
        paths = inputs.paths
        envelope = _validated_envelope(dependencies, paths)
        if inputs.rate_table_replay is inputs.terms_section_replay:
            raise ValueError

        def marker_map_builder(
            *,
            bundle: MinerUCaptureBundle5961V1,
            receipt: DerivedRelationReceipt5961V1,
        ) -> tuple[TypedMarkerEndpointMapV1, TypedMarkerEndpointMapV1]:
            checked_bundle = MinerUCaptureBundle5961V1.model_validate(bundle)
            checked_receipt = DerivedRelationReceipt5961V1.model_validate(receipt)
            if checked_bundle.bundle_digest_sha256 != envelope.bundle_digest_sha256:
                raise ValueError
            terms = TypedMarkerEndpointMapV1.model_validate(
                _call_dependency(
                    lambda: dependencies.replay_terms_section_map(
                        envelope=envelope,
                        bundle=checked_bundle,
                        receipt=checked_receipt,
                        replay=inputs.terms_section_replay,
                    )
                )
            )
            rate = TypedMarkerEndpointMapV1.model_validate(
                _call_dependency(
                    lambda: dependencies.replay_rate_table_map(
                        envelope=envelope,
                        bundle=checked_bundle,
                        receipt=checked_receipt,
                        replay=inputs.rate_table_replay,
                    )
                )
            )
            if (
                terms == rate
                or terms.relation_kind != "section"
                or rate.relation_kind != "table"
                or terms.source_sha256 != envelope.marker_sources[0].source_sha256
                or rate.source_sha256 != envelope.marker_sources[1].source_sha256
            ):
                raise ValueError
            return terms, rate

        def authority_adapter(
            receipt_bytes: bytes,
            *,
            capture_payloads: tuple[bytes, bytes, bytes],
            bundle: MinerUCaptureBundle5961V1,
            relation_binding_replay: Callable[[object], object],
        ) -> ValidatedRelationAdmissionInputsPort:
            del relation_binding_replay
            context = _call_dependency(
                lambda: dependencies.validate_relation_authority(
                    receipt_bytes,
                    capture_payloads=capture_payloads,
                    source_authorities=inputs.source_authorities,
                    material_profile_resolutions=inputs.material_profile_resolutions,
                    marker_map_builder=marker_map_builder,
                )
            )
            if context.bundle != bundle or context.bundle.bundle_digest_sha256 != (
                envelope.bundle_digest_sha256
            ):
                raise ValueError
            return context

        actual_result = _call_dependency(
            lambda: dependencies.run_actual_execution(
                paths,
                validate_relation_authority=authority_adapter,
            )
        )
        return _result_from_actual(actual_result)
    except (
        AttributeError,
        _DependencyCallError,
        MarkerAuthorityExportError,
        RelationReceiptAuthorityAdapterError,
        TypeError,
        ValidationError,
        ValueError,
    ):
        return _blocked("BLOCKED_ON_CROSS_PAGE_BINDING")


__all__ = [
    "DualMapActualWiringInputs5961V1",
    "DualMapActualWiringResultV1",
    "run_dual_map_actual_wiring_596_1",
]
