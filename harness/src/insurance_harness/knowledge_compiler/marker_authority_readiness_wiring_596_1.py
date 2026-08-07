"""Pure 101 -> 098 -> 099 wiring for the bounded 596-1 capture gate."""

from __future__ import annotations

import hashlib
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.parsed_documents import ParsedDocumentV1, ParseManifestV1
from insurance_harness.knowledge_compiler.bounded_real_capture_readiness_596_1 import (
    DEPENDENCY_ORDER,
    BoundProof,
    DependencyEvidence,
    FrozenDependencyIdentity,
    ReadinessBundle,
    ReadinessResult,
    evaluate_test_only_future_readiness,
)
from insurance_harness.knowledge_compiler.marker_authority_envelope_596_1 import (
    MarkerAuthorityEnvelopeV1,
    MarkerSourceAuthorityV1,
    recompute_marker_authority_envelope_sha256,
)
from insurance_harness.knowledge_compiler.marker_endpoint_pair_bridge_596_1 import (
    MarkerEndpointPairBridgeError,
    MarkerEndpointPairInputV1,
    derive_marker_endpoint_pair_input_596_1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    MinerUCaptureIntakeItem5961V1,
)

_TEST_EVIDENCE_CLASS = "TEST_ONLY_COMPLETE_FIXTURE"
_SOURCE_ORDER = ("terms", "brochure", "rate")


@dataclass(frozen=True)
class TermsSectionBindingEvidenceV1:
    evidence_class: str
    contract_id: str
    contract_version: str
    implementation_blob_sha256: str
    api_schema_sha256: str
    source_sha256: str
    marker_authority_envelope_sha256: str
    canonical_preimage: BoundProof
    receipt: BoundProof
    context_sha256: str
    policy_sha256: str
    replay_sha256: str
    status: str


@dataclass(frozen=True)
class FutureReadinessInputsV1:
    bundle: ReadinessBundle
    authority: tuple[FrozenDependencyIdentity, ...]


@runtime_checkable
class TermsSectionBindingProtocol(Protocol):
    def bind_terms_section(
        self, envelope: MarkerAuthorityEnvelopeV1
    ) -> TermsSectionBindingEvidenceV1: ...


@runtime_checkable
class FutureReadinessProtocol(Protocol):
    def load_test_only_readiness_inputs(self) -> FutureReadinessInputsV1: ...


@dataclass(frozen=True)
class MarkerAuthorityReadinessResultV1:
    status: str
    reason_code: str
    evidence_class: str
    capture_authorized: bool
    marker_authority_envelope_sha256: str | None = None
    endpoint_replay_sha256: str | None = None
    readiness: ReadinessResult | None = None


def _result(
    reason: str,
    *,
    evidence_class: str = "BLOCKED",
    envelope_sha256: str | None = None,
    endpoint_sha256: str | None = None,
    readiness: ReadinessResult | None = None,
) -> MarkerAuthorityReadinessResultV1:
    return MarkerAuthorityReadinessResultV1(
        status=reason,
        reason_code=reason,
        evidence_class=evidence_class,
        capture_authorized=False,
        marker_authority_envelope_sha256=envelope_sha256,
        endpoint_replay_sha256=endpoint_sha256,
        readiness=readiness,
    )


def _is_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _proof(value: object) -> BoundProof:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return BoundProof(preimage=encoded, sha256=hashlib.sha256(encoded).hexdigest())


def _proof_valid(value: object) -> bool:
    return (
        type(value) is BoundProof
        and type(value.preimage) is bytes
        and _is_sha256(value.sha256)
        and hashlib.sha256(value.preimage).hexdigest() == value.sha256
    )


def _go_domain_hash(domain: str, value: object | str) -> str:
    material = value if isinstance(value, str) else _compact(value).decode()
    return hashlib.sha256(domain.encode() + b"\0" + material.encode()).hexdigest()


def _source_authority_valid(source: MarkerSourceAuthorityV1) -> bool:
    if source.relation_authority != "UNBOUND" or not source.markers:
        return False
    capture = source.capture_identity_preimage
    capture_wire = {
        "contract": capture.contract,
        "source_sha256": capture.source_sha256,
        "attempt": {
            "attempt_number": capture.attempt_number,
            "attempt_role": capture.attempt_role,
            "generation": capture.generation,
        },
        "parser_config_sha256": capture.parser_config_sha256,
        "raw_structure_sha256": capture.raw_structure_sha256,
        "sanitized_structure_sha256": capture.sanitized_structure_sha256,
        "content_snapshot_sha256": capture.content_snapshot_sha256,
        "cross_page_projection_sha256": capture.cross_page_projection_sha256,
        "marker_provenance_replay_sha256": capture.marker_provenance_replay_sha256,
    }
    if hashlib.sha256(_compact(capture_wire)).hexdigest() != source.capture_identity_sha256:
        return False
    replay_markers: list[dict[str, object]] = []
    for marker in source.markers:
        path = marker.structural_path_preimage
        if (
            path.source_sha256 != source.source_sha256
            or path.native_member_sha256 != source.native_member.sha256
            or marker.structural_path_sha256
            != _go_domain_hash(
                path.contract,
                f"{path.source_sha256}\0{path.native_member_sha256}\0{path.structural_path}",
            )
            or marker.node_identity_sha256
            != canonical_hash(
                marker.node_identity_preimage.contract,
                marker.node_identity_preimage.model_dump(mode="json"),
            )
            or marker.marker_preimage.source_sha256 != source.source_sha256
            or marker.marker_preimage.native_member_sha256 != source.native_member.sha256
            or marker.marker_sha256
            != _go_domain_hash(
                "mineru-cross-page-marker-evidence.v1",
                marker.marker_preimage.model_dump(mode="json"),
            )
        ):
            return False
        replay_markers.append(
            {
                "marker_kind": marker.marker_kind,
                "page_index": marker.page_index,
                "structural_path": marker.structural_path_preimage.structural_path,
                "structural_path_sha256": marker.structural_path_sha256,
                "node_type": marker.node_type,
                "local_index": marker.local_index,
                "marker_sha256": marker.marker_sha256,
            }
        )
    replay = source.marker_replay_preimage
    replay_wire = {
        "contract": replay.contract,
        "source_sha256": replay.source_sha256,
        "parser_model": replay.parser_model,
        "mineru_version": replay.mineru_version,
        "raw_zip_sha256": replay.raw_zip_sha256,
        "native_member_sha256": replay.native_member_sha256,
        "marker_count": replay.marker_count,
        "markers": replay_markers,
    }
    if replay.native_hierarchy_replay_sha256 is not None:
        replay_wire["native_hierarchy_replay_sha256"] = (
            replay.native_hierarchy_replay_sha256
        )
    if (
        replay.marker_count != len(source.markers)
        or source.marker_replay_digest_sha256
        != _go_domain_hash("mineru-cross-page-marker-provenance-replay.v1", replay_wire)
        or source.source_authority_sha256
        != canonical_hash(
            source.source_authority_preimage.contract,
            source.source_authority_preimage.model_dump(mode="json"),
        )
        or source.source_authority_preimage.marker_sha256
        != tuple(marker.marker_sha256 for marker in source.markers)
    ):
        return False
    return True


def _validated_authority(
    value: object,
) -> MarkerAuthorityEnvelopeV1 | None:
    if type(value) is not MarkerAuthorityEnvelopeV1:
        return None
    try:
        envelope = MarkerAuthorityEnvelopeV1.model_validate(value)
    except (TypeError, ValidationError, ValueError):
        return None
    if (
        envelope.contract != "mineru-marker-authority-envelope-596-1.v1"
        or envelope.product_version != "596-1"
        or envelope.source_order != _SOURCE_ORDER
        or envelope.bundle_preimage.roles != _SOURCE_ORDER
        or envelope.relation_authority != "UNBOUND"
        or tuple(source.role for source in envelope.marker_sources) != ("terms", "rate")
        or not all(_source_authority_valid(source) for source in envelope.marker_sources)
    ):
        return None
    bundle_preimage = envelope.bundle_preimage
    bundle_digest = canonical_hash(
        "mineru-capture-bundle-596-1.v1",
        {
            "contract": bundle_preimage.contract,
            "sources": [
                {
                    "role": role,
                    "source_sha256": source_sha,
                    "capture_identity_sha256": capture_sha,
                    "intake_digest_sha256": intake_sha,
                }
                for role, source_sha, capture_sha, intake_sha in zip(
                    bundle_preimage.roles,
                    bundle_preimage.source_sha256,
                    bundle_preimage.capture_identity_sha256,
                    bundle_preimage.intake_digest_sha256,
                    strict=True,
                )
            ],
        },
    )
    expected_envelope_preimage = {
        "contract": envelope.contract,
        "product_version": envelope.product_version,
        "source_order": envelope.source_order,
        "bundle_digest_sha256": envelope.bundle_digest_sha256,
        "marker_source_authority_sha256": tuple(
            source.source_authority_sha256 for source in envelope.marker_sources
        ),
        "relation_authority": "UNBOUND",
    }
    if (
        bundle_digest != envelope.bundle_digest_sha256
        or envelope.envelope_preimage.model_dump(mode="python") != expected_envelope_preimage
        or recompute_marker_authority_envelope_sha256(envelope) != envelope.envelope_sha256
    ):
        return None
    return envelope


def _source_matches_intake(
    authority: MarkerSourceAuthorityV1, item: MinerUCaptureIntakeItem5961V1
) -> bool:
    provenance = item.evidence.cross_page_marker_provenance
    facts = item.evidence.cross_page_facts
    if provenance is None or facts is None or facts.native_member_sha256 is None:
        return False
    marker_rows = tuple(
        (
            marker.marker_kind,
            marker.page_index,
            marker.node_type,
            marker.local_index,
            marker.structural_path_sha256,
            marker.marker_sha256,
        )
        for marker in provenance.markers
    )
    authority_rows = tuple(
        (
            marker.marker_kind,
            marker.page_index,
            marker.node_type,
            marker.local_index,
            marker.structural_path_sha256,
            marker.marker_sha256,
        )
        for marker in authority.markers
    )
    return (
        item.role == authority.role
        and item.source_sha256 == authority.source_sha256
        and item.capture_identity_sha256 == authority.capture_identity_sha256
        and item.intake_digest_sha256 == authority.source_authority_preimage.intake_digest_sha256
        and item.evidence.parser.config_sha256 == authority.parser_config_sha256
        and provenance.parser_model == authority.parser_model
        and provenance.mineru_version == authority.mineru_version
        and provenance.raw_zip_sha256 == authority.raw_zip.sha256
        and provenance.native_member_sha256 == authority.native_member.sha256
        and provenance.replay_digest_sha256 == authority.marker_replay_digest_sha256
        and item.cross_page_facts_digest_sha256
        == authority.source_authority_preimage.cross_page_facts_digest_sha256
        and item.marker_provenance_digest_sha256
        == authority.source_authority_preimage.marker_provenance_digest_sha256
        and marker_rows == authority_rows
    )


def _authority_matches_intake(
    envelope: MarkerAuthorityEnvelopeV1, value: object
) -> MinerUCaptureBundle5961V1 | None:
    if type(value) is not MinerUCaptureBundle5961V1:
        return None
    try:
        bundle = MinerUCaptureBundle5961V1.model_validate(value)
    except (TypeError, ValidationError, ValueError):
        return None
    preimage = envelope.bundle_preimage
    if (
        tuple(source.role for source in bundle.sources) != _SOURCE_ORDER
        or tuple(source.source_sha256 for source in bundle.sources) != preimage.source_sha256
        or tuple(source.capture_identity_sha256 for source in bundle.sources)
        != preimage.capture_identity_sha256
        or tuple(source.intake_digest_sha256 for source in bundle.sources)
        != preimage.intake_digest_sha256
        or bundle.bundle_digest_sha256 != envelope.bundle_digest_sha256
        or not _source_matches_intake(envelope.marker_sources[0], bundle.sources[0])
        or not _source_matches_intake(envelope.marker_sources[1], bundle.sources[2])
    ):
        return None
    return bundle


def _terms_binding_valid(
    value: object, envelope: MarkerAuthorityEnvelopeV1
) -> TermsSectionBindingEvidenceV1 | None:
    if type(value) is not TermsSectionBindingEvidenceV1:
        return None
    if (
        value.evidence_class != _TEST_EVIDENCE_CLASS
        or value.contract_id != "terms-section-binding-596-1.v1"
        or value.contract_version != "v1"
        or value.source_sha256 != envelope.marker_sources[0].source_sha256
        or value.marker_authority_envelope_sha256 != envelope.envelope_sha256
        or value.status != "TERMS_SECTION_BINDING_VERIFIED"
        or not _proof_valid(value.canonical_preimage)
        or not _proof_valid(value.receipt)
        or not all(
            _is_sha256(item)
            for item in (
                value.implementation_blob_sha256,
                value.api_schema_sha256,
                value.context_sha256,
                value.policy_sha256,
                value.replay_sha256,
            )
        )
        or envelope.envelope_sha256.encode() not in value.canonical_preimage.preimage
    ):
        return None
    return value


def _module_blob_sha256(value: Callable[..., Any] | type[Any]) -> str:
    source = inspect.getsourcefile(value)
    if source is None:
        raise ValueError("module source unavailable")
    return hashlib.sha256(Path(source).read_bytes()).hexdigest()


def _schema_sha256(model: type[object]) -> str:
    schema = model.model_json_schema()  # type: ignore[attr-defined]
    return hashlib.sha256(
        json.dumps(schema, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _actual_evidence(
    envelope: MarkerAuthorityEnvelopeV1,
    terms: TermsSectionBindingEvidenceV1,
    endpoint: MarkerEndpointPairInputV1,
) -> tuple[DependencyEvidence, DependencyEvidence]:
    marker_canonical = _proof(
        {
            "contract": envelope.contract,
            "envelope_preimage": envelope.envelope_preimage.model_dump(mode="json"),
            "envelope_sha256": envelope.envelope_sha256,
            "terms_binding_receipt_sha256": terms.receipt.sha256,
        }
    )
    marker_receipt = _proof(
        {
            "contract": "marker-authority-readiness-wiring-091.v1",
            "canonical_preimage_sha256": marker_canonical.sha256,
            "terms_binding_receipt_sha256": terms.receipt.sha256,
        }
    )
    marker_evidence = DependencyEvidence(
        dependency_id="091",
        evidence_class=_TEST_EVIDENCE_CLASS,
        adapter_present=True,
        contract_id=envelope.contract,
        contract_version="v1",
        implementation_blob_sha256=_module_blob_sha256(MarkerAuthorityEnvelopeV1),
        api_schema_sha256=_schema_sha256(MarkerAuthorityEnvelopeV1),
        canonical_preimage=marker_canonical,
        receipt=marker_receipt,
        predecessor_receipt_sha256=None,
        context_sha256=envelope.bundle_digest_sha256,
        policy_sha256=terms.policy_sha256,
        replay_sha256=envelope.envelope_sha256,
        ordered_roles=("terms", "brochure", "rate_table"),
        endpoint_state="NOT_APPLICABLE",
        endpoint_derivation_input_sha256=None,
        binding_state="NOT_APPLICABLE",
        relation_state="NOT_APPLICABLE",
        dependency_map=(),
        wrapper_invocation_cap=1,
        retry_budget=0,
        fallback_enabled=False,
        external_effects=0,
    )
    endpoint_canonical = _proof(
        {
            "contract": endpoint.contract,
            "endpoint_replay": endpoint.model_dump(mode="json"),
            "marker_authority_receipt_sha256": marker_receipt.sha256,
        }
    )
    endpoint_receipt = _proof(
        {
            "contract": "marker-authority-readiness-wiring-098.v1",
            "canonical_preimage_sha256": endpoint_canonical.sha256,
            "predecessor_receipt_sha256": marker_receipt.sha256,
        }
    )
    endpoint_evidence = DependencyEvidence(
        dependency_id="098",
        evidence_class=_TEST_EVIDENCE_CLASS,
        adapter_present=True,
        contract_id=endpoint.contract,
        contract_version="v1",
        implementation_blob_sha256=_module_blob_sha256(MarkerEndpointPairInputV1),
        api_schema_sha256=_schema_sha256(MarkerEndpointPairInputV1),
        canonical_preimage=endpoint_canonical,
        receipt=endpoint_receipt,
        predecessor_receipt_sha256=marker_receipt.sha256,
        context_sha256=canonical_hash(
            "marker-authority-endpoint-context.v1",
            {
                "envelope_sha256": envelope.envelope_sha256,
                "endpoint_replay_sha256": endpoint.replay_digest_sha256,
            },
        ),
        policy_sha256=endpoint.policy_sha256,
        replay_sha256=endpoint.replay_digest_sha256,
        ordered_roles=("terms", "brochure", "rate_table"),
        endpoint_state="COMPLETE_ENDPOINT_PAIR_VERIFIED",
        endpoint_derivation_input_sha256=marker_receipt.sha256,
        binding_state="NOT_APPLICABLE",
        relation_state="NOT_APPLICABLE",
        dependency_map=(),
        wrapper_invocation_cap=1,
        retry_budget=0,
        fallback_enabled=False,
        external_effects=0,
    )
    return marker_evidence, endpoint_evidence


def _identity(evidence: DependencyEvidence) -> FrozenDependencyIdentity:
    return FrozenDependencyIdentity(
        dependency_id=evidence.dependency_id,
        contract_id=evidence.contract_id,
        contract_version=evidence.contract_version,
        implementation_blob_sha256=evidence.implementation_blob_sha256,
        api_schema_sha256=evidence.api_schema_sha256,
        canonical_preimage_sha256=evidence.canonical_preimage.sha256,
        context_sha256=evidence.context_sha256,
        policy_sha256=evidence.policy_sha256,
        replay_sha256=evidence.replay_sha256,
    )


def _rechain(
    dependencies: tuple[DependencyEvidence, ...], predecessor: str
) -> tuple[DependencyEvidence, ...]:
    result: list[DependencyEvidence] = []
    current = predecessor
    for evidence in dependencies:
        receipt = _proof(
            {
                "contract": "marker-authority-readiness-downstream-replay.v1",
                "dependency_id": evidence.dependency_id,
                "original_receipt_sha256": evidence.receipt.sha256,
                "predecessor_receipt_sha256": current,
            }
        )
        result.append(
            replace(
                evidence,
                predecessor_receipt_sha256=current,
                receipt=receipt,
                endpoint_derivation_input_sha256=(
                    current if evidence.dependency_id == "098" else None
                ),
            )
        )
        current = receipt.sha256
    return tuple(result)


def _endpoint_matches_authority(
    endpoint: MarkerEndpointPairInputV1,
    envelope: MarkerAuthorityEnvelopeV1,
    bundle: MinerUCaptureBundle5961V1,
) -> bool:
    source = envelope.marker_sources[1]
    item = bundle.sources[2]
    provenance = item.evidence.cross_page_marker_provenance
    hierarchy = provenance.native_hierarchy_provenance if provenance is not None else None
    marker = source.markers[0] if len(source.markers) == 1 else None
    return (
        marker is not None
        and endpoint.source_sha256 == source.source_sha256
        and endpoint.parser_model == source.parser_model
        and endpoint.mineru_version == source.mineru_version
        and endpoint.parser_config_sha256 == source.parser_config_sha256
        and endpoint.intake_bundle_digest_sha256 == envelope.bundle_digest_sha256
        and endpoint.intake_item_digest_sha256 == item.intake_digest_sha256
        and endpoint.capture_identity_sha256 == source.capture_identity_sha256
        and endpoint.raw_structure_sha256 == source.capture_identity_preimage.raw_structure_sha256
        and endpoint.sanitized_structure_sha256
        == source.capture_identity_preimage.sanitized_structure_sha256
        and endpoint.raw_zip_sha256 == source.raw_zip.sha256
        and endpoint.native_member_sha256 == source.native_member.sha256
        and endpoint.cross_page_facts_digest_sha256
        == source.source_authority_preimage.cross_page_facts_digest_sha256
        and endpoint.marker_provenance_digest_sha256
        == source.source_authority_preimage.marker_provenance_digest_sha256
        and endpoint.marker_provenance_replay_sha256 == source.marker_replay_digest_sha256
        and endpoint.native_hierarchy_replay_sha256
        == (hierarchy.replay_digest_sha256 if hierarchy is not None else None)
        and endpoint.marker_kind == marker.marker_kind
        and endpoint.marker_page_index == marker.page_index
        and endpoint.marker_node_type == marker.node_type
        and endpoint.marker_local_index == marker.local_index
        and endpoint.marker_structural_path == marker.structural_path_preimage.structural_path
        and endpoint.marker_structural_path_sha256_091 == marker.structural_path_sha256
        and endpoint.marker_evidence_sha256 == marker.marker_sha256
    )


def evaluate_marker_authority_readiness_596_1(
    marker_authority: object,
) -> MarkerAuthorityReadinessResultV1:
    """Evaluate the current formal seam; 103 authority is intentionally absent."""

    envelope = _validated_authority(marker_authority)
    if envelope is None:
        return _result("MARKER_AUTHORITY_INVALID")
    return _result(
        "TERMS_SECTION_BINDING_UNAVAILABLE",
        envelope_sha256=envelope.envelope_sha256,
    )


def evaluate_test_only_future_marker_authority_readiness_596_1(
    marker_authority: object,
    intake_bundle: object,
    rate_document: object,
    rate_manifest: object,
    *,
    terms_binding: TermsSectionBindingProtocol,
    future_dependencies: FutureReadinessProtocol,
) -> MarkerAuthorityReadinessResultV1:
    """Prove future mechanical completeness without granting capture authority."""

    envelope = _validated_authority(marker_authority)
    if envelope is None:
        return _result("MARKER_AUTHORITY_INVALID")
    if not isinstance(terms_binding, TermsSectionBindingProtocol):
        return _result(
            "TERMS_SECTION_BINDING_UNAVAILABLE",
            envelope_sha256=envelope.envelope_sha256,
        )
    try:
        terms_value = terms_binding.bind_terms_section(envelope)
    except (TypeError, ValueError):
        return _result("TERMS_SECTION_BINDING_INVALID", envelope_sha256=envelope.envelope_sha256)
    if type(terms_value) is TermsSectionBindingEvidenceV1 and (
        terms_value.evidence_class != _TEST_EVIDENCE_CLASS
    ):
        return _result(
            "TERMS_SECTION_BINDING_EVIDENCE_CLASS_BLOCKED",
            envelope_sha256=envelope.envelope_sha256,
        )
    terms = _terms_binding_valid(terms_value, envelope)
    if terms is None:
        return _result("TERMS_SECTION_BINDING_INVALID", envelope_sha256=envelope.envelope_sha256)
    bundle = _authority_matches_intake(envelope, intake_bundle)
    if bundle is None:
        return _result("MARKER_AUTHORITY_INTAKE_DRIFT", envelope_sha256=envelope.envelope_sha256)
    try:
        document = ParsedDocumentV1.model_validate(rate_document)
        manifest = ParseManifestV1.model_validate(rate_manifest)
        endpoint = MarkerEndpointPairInputV1.model_validate(
            derive_marker_endpoint_pair_input_596_1(bundle, document, manifest)
        )
    except (MarkerEndpointPairBridgeError, TypeError, ValidationError, ValueError):
        return _result("ENDPOINT_PAIR_REPLAY_BLOCKED", envelope_sha256=envelope.envelope_sha256)
    if not _endpoint_matches_authority(endpoint, envelope, bundle):
        return _result("ENDPOINT_PAIR_AUTHORITY_DRIFT", envelope_sha256=envelope.envelope_sha256)
    if not isinstance(future_dependencies, FutureReadinessProtocol):
        return _result(
            "FUTURE_DEPENDENCY_PROTOCOL_UNAVAILABLE",
            envelope_sha256=envelope.envelope_sha256,
            endpoint_sha256=endpoint.replay_digest_sha256,
        )
    try:
        future = future_dependencies.load_test_only_readiness_inputs()
    except (TypeError, ValueError):
        return _result(
            "FUTURE_DEPENDENCY_INPUT_INVALID",
            envelope_sha256=envelope.envelope_sha256,
            endpoint_sha256=endpoint.replay_digest_sha256,
        )
    if (
        type(future) is not FutureReadinessInputsV1
        or type(future.bundle) is not ReadinessBundle
        or type(future.authority) is not tuple
        or tuple(item.dependency_id for item in future.bundle.dependencies) != DEPENDENCY_ORDER
        or tuple(item.dependency_id for item in future.authority) != DEPENDENCY_ORDER
    ):
        return _result(
            "FUTURE_DEPENDENCY_INPUT_INVALID",
            envelope_sha256=envelope.envelope_sha256,
            endpoint_sha256=endpoint.replay_digest_sha256,
        )
    marker_evidence, endpoint_evidence = _actual_evidence(envelope, terms, endpoint)
    downstream = _rechain(future.bundle.dependencies[2:], endpoint_evidence.receipt.sha256)
    dependencies = (marker_evidence, endpoint_evidence, *downstream)
    authority = (
        _identity(marker_evidence),
        _identity(endpoint_evidence),
        *future.authority[2:],
    )
    readiness = evaluate_test_only_future_readiness(
        replace(future.bundle, dependencies=dependencies), authority
    )
    return _result(
        readiness.reason_code,
        evidence_class=readiness.evidence_class,
        envelope_sha256=envelope.envelope_sha256,
        endpoint_sha256=endpoint.replay_digest_sha256,
        readiness=readiness,
    )


__all__ = [
    "FutureReadinessInputsV1",
    "FutureReadinessProtocol",
    "MarkerAuthorityReadinessResultV1",
    "TermsSectionBindingEvidenceV1",
    "TermsSectionBindingProtocol",
    "evaluate_marker_authority_readiness_596_1",
    "evaluate_test_only_future_marker_authority_readiness_596_1",
]
