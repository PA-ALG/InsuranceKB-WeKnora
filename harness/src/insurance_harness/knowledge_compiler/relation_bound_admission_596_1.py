"""Exact three-source 596-1 relation-bound admission integration.

This module owns orchestration only. 083 owns capture intake, 086 owns derived
relation authority, 090 owns relation-aware 060 construction, and 061 owns the
final replay gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler import native_mineru_cloud
from insurance_harness.compiler.material_profiles import MaterialProfileResolution
from insurance_harness.compiler.parsed_documents import (
    ParseAttemptV1,
    ParsedDocumentV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParseQualityDecisionV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    MinerUCaptureIntakeItem5961V1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    CrossPageRelationBindingV1,
    replay_cross_page_relation_binding_v1,
)
from insurance_harness.knowledge_compiler.vertical_falsification import (
    APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
    EXPECTED_596_1_PARSE_SOURCES,
    AdmittedParseArtifactV1,
    VerticalFalsificationAdmission,
    admit_596_1_vertical_falsification,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonBlank = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
InputRole = Literal["terms", "brochure", "rate"]
ReceiptRole = Literal["terms", "brochure", "rate_table"]
RelationKind = Literal["section", "table"]

_ROLE_MAP: dict[InputRole, ReceiptRole] = {
    "terms": "terms",
    "brochure": "brochure",
    "rate": "rate_table",
}
_PARSER_BUILD_ID = "NewMinerUCloudReader/mineru-native-structure.v1"
_UNRESOLVED = {"all", "any", "unknown", "*"}


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class SourceAdmissionAuthorityV1(_FrozenModel):
    """Caller-supplied, prevalidated runtime identity; never invented here."""

    role: InputRole
    space_id: NonBlank
    source_id: NonBlank
    source_revision_id: NonBlank
    snapshot_id: NonBlank
    snapshot_generation: Literal[0]
    attempt_id: NonBlank
    canonical_envelope_hash: Sha256Hex
    concurrent_mutation_fence_hash: Sha256Hex

    @model_validator(mode="after")
    def _closed_identifiers(self) -> Self:
        values = (
            self.space_id,
            self.source_id,
            self.source_revision_id,
            self.snapshot_id,
            self.attempt_id,
        )
        if any(value.casefold() in _UNRESOLVED for value in values):
            raise ValueError("unresolved authority identity")
        return self


class TypedMarkerNodeV1(_FrozenModel):
    """089 node metadata; the structural-path hash is custody, never endpoint authority."""

    page_index: Annotated[StrictInt, Field(ge=0)]
    node_type: Literal["text", "table"]
    local_index: Annotated[StrictInt, Field(ge=0)]
    structural_path_sha256: Sha256Hex


class TypedMarkerEndpointMapV1(_FrozenModel):
    """A future bridge must provide both nodes; current one-marker 089 stays blocked."""

    contract: Literal["typed-marker-endpoint-map.v1"]
    source_sha256: Sha256Hex
    marker_kind: Literal["cross_page"]
    relation_kind: RelationKind
    source_node: TypedMarkerNodeV1
    target_node: TypedMarkerNodeV1
    replay_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _digest_and_distinct_pages(self) -> Self:
        expected = canonical_hash(
            "typed-marker-endpoint-map.v1",
            self.model_dump(mode="python", exclude={"replay_digest_sha256"}),
        )
        if (
            self.replay_digest_sha256 != expected
            or self.source_node.page_index == self.target_node.page_index
        ):
            raise ValueError("typed marker endpoint map mismatch")
        return self


class Trusted090RelationInputV1(_FrozenModel):
    """The exact task-local projection accepted by the frozen 090 port."""

    contract: Literal["cross-page-relation-binding.v1"]
    relation_id: NonBlank
    relation_kind: Literal["section_continuation", "table_continuation"]
    source_sha256: Sha256Hex
    parser_id: Literal["mineru-cloud-pipeline"]
    parser_build_id: Literal["NewMinerUCloudReader/mineru-native-structure.v1"]
    parser_config_hash: Sha256Hex
    raw_artifact_sha256: Sha256Hex
    sanitized_structure_sha256: Sha256Hex
    material_profile_binding_hash: Sha256Hex
    policy_context_hash: Sha256Hex
    replay_context_hash: Sha256Hex
    endpoint_ids: tuple[NonBlank, NonBlank]
    binding_hash: Sha256Hex

    @model_validator(mode="after")
    def _closed_binding(self) -> Self:
        if self.endpoint_ids[0] == self.endpoint_ids[1] or self.binding_hash != canonical_hash(
            self.contract,
            self.model_dump(mode="python", exclude={"binding_hash"}),
        ):
            raise ValueError("trusted relation binding mismatch")
        return self


class RelationBindingProvider(Protocol):
    def __call__(
        self,
        bundle: MinerUCaptureBundle5961V1,
        document: ParsedDocumentV1,
        manifest: ParseManifestV1,
        *,
        relation_kind: RelationKind,
    ) -> CrossPageRelationBindingV1 | tuple[CrossPageRelationBindingV1, ...]: ...


class Trusted090Builder(Protocol):
    def __call__(
        self,
        sanitized_json: bytes,
        *,
        expected_raw_sha256: str,
        expected_sanitized_sha256: str,
        subject: ParseSubjectV1,
        parser: ParserIdentityV1,
        attempt: ParseAttemptV1,
        snapshot: ParseSnapshotV1,
        output_facts: ParseOutputFactsV1,
        material_profile_resolution: MaterialProfileResolution,
        trusted_relation_bindings: tuple[Trusted090RelationInputV1, ...] = (),
    ) -> tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1]: ...


@dataclass(frozen=True, slots=True)
class RelationBoundAdmissionResultV1:
    status: Literal[
        "READY_FOR_QUALITY_FALSIFICATION",
        "BLOCKED_ON_INTAKE_AUTHORITY",
        "BLOCKED_ON_RELATION_BINDING",
        "BLOCKED_ON_PARSE_ADMISSION",
        "BLOCKED_ON_061_REPLAY",
    ]
    reason_code: str | None = None
    admitted_parse_artifacts: tuple[AdmittedParseArtifactV1, ...] = field(default=(), repr=False)
    admission: VerticalFalsificationAdmission | None = field(default=None, repr=False)
    intake_bundle_digest_sha256: str | None = None
    integration_digest_sha256: str | None = None
    provider_calls: Literal[0] = 0
    golden_reads: Literal[0] = 0


def _blocked(
    status: Literal[
        "BLOCKED_ON_INTAKE_AUTHORITY",
        "BLOCKED_ON_RELATION_BINDING",
        "BLOCKED_ON_PARSE_ADMISSION",
        "BLOCKED_ON_061_REPLAY",
    ],
    reason: str,
) -> RelationBoundAdmissionResultV1:
    return RelationBoundAdmissionResultV1(status=status, reason_code=reason)


def _validated_inputs(
    bundle: MinerUCaptureBundle5961V1,
    authorities: tuple[SourceAdmissionAuthorityV1, ...],
    resolutions: tuple[MaterialProfileResolution, ...],
) -> tuple[
    MinerUCaptureBundle5961V1,
    tuple[SourceAdmissionAuthorityV1, ...],
    tuple[MaterialProfileResolution, ...],
]:
    checked_bundle = MinerUCaptureBundle5961V1.model_validate(bundle)
    checked_authorities = tuple(
        SourceAdmissionAuthorityV1.model_validate(item) for item in authorities
    )
    checked_resolutions = tuple(
        MaterialProfileResolution.model_validate(item) for item in resolutions
    )
    if len(checked_authorities) != 3 or len(checked_resolutions) != 3:
        raise ValueError("exact three source inputs required")
    if tuple(item.role for item in checked_authorities) != ("terms", "brochure", "rate"):
        raise ValueError("source authority order mismatch")
    if len({item.space_id for item in checked_authorities}) != 1:
        raise ValueError("cross-space source authority")
    expected = tuple(
        (role, source, profile) for role, source, profile in EXPECTED_596_1_PARSE_SOURCES
    )
    observed: list[tuple[str, str, str]] = []
    for item, authority, resolution in zip(
        checked_bundle.sources, checked_authorities, checked_resolutions, strict=True
    ):
        role = _ROLE_MAP[authority.role]
        if item.role != authority.role:
            raise ValueError("capture role mismatch")
        if (
            resolution.catalog_hash != APPROVED_MATERIAL_PROFILE_CATALOG_SHA256
            or resolution.profile.material_role != role
            or resolution.request.classified_material_role != role
            or resolution.request.space_id != authority.space_id
            or resolution.request.product_version != "596-1"
            or resolution.profile.source.sha256 != item.source_sha256
            or resolution.request.source != resolution.profile.source
        ):
            raise ValueError("material profile authority mismatch")
        observed.append((role, item.source_sha256, resolution.profile.profile_id))
    if tuple(observed) != expected:
        raise ValueError("approved source profile mismatch")
    return checked_bundle, checked_authorities, checked_resolutions


def _parse_inputs(
    *,
    authority: SourceAdmissionAuthorityV1,
    resolution: MaterialProfileResolution,
    raw_hash: str,
    parser_config_hash: str,
) -> tuple[
    ParseSubjectV1,
    ParserIdentityV1,
    ParseAttemptV1,
    ParseSnapshotV1,
    ParseOutputFactsV1,
]:
    subject = ParseSubjectV1(
        space_id=authority.space_id,
        source_id=authority.source_id,
        source_revision_id=authority.source_revision_id,
        product_version_id="596-1",
        material_profile_id=resolution.profile.profile_id,
        material_profile_binding_hash=resolution.binding_hash,
        source_sha256=resolution.profile.source.sha256,
        raw_artifact_hash=raw_hash,
        canonical_envelope_hash=authority.canonical_envelope_hash,
    )
    parser = ParserIdentityV1(
        parser_id="mineru-cloud-pipeline",
        parser_profile_ref=(
            resolution.parse_policy_receipt.bounded_upgrade_profile_ref
            or _fail_missing_upgrade_profile()
        ),
        parser_build_id=_PARSER_BUILD_ID,
        parser_config_hash=parser_config_hash,
    )
    attempt = ParseAttemptV1(
        attempt_id=authority.attempt_id,
        attempt_number=2,
        attempt_role="bounded_upgrade",
        generation=0,
    )
    snapshot = ParseSnapshotV1(
        snapshot_id=authority.snapshot_id,
        snapshot_generation=authority.snapshot_generation,
        pagination_complete=True,
        concurrent_mutation_fence_hash=authority.concurrent_mutation_fence_hash,
    )
    output = ParseOutputFactsV1(
        privacy_policy_ref=resolution.parse_policy_receipt.privacy_policy_ref,
        output_policy_ref=resolution.parse_policy_receipt.output_policy_ref,
        body_text_included=False,
        secrets_included=False,
        absolute_paths_included=False,
        unknown_vendor_fields_included=False,
    )
    return subject, parser, attempt, snapshot, output


def _validated_output(
    value: object,
) -> tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1]:
    if not isinstance(value, tuple) or len(value) != 3:
        raise ValueError("060 output shape mismatch")
    document = ParsedDocumentV1.model_validate(value[0])
    manifest = ParseManifestV1.model_validate(value[1])
    decision = ParseQualityDecisionV1.model_validate(value[2])
    if (
        manifest.document_hash != document.document_hash
        or decision.manifest_hash != manifest.manifest_hash
        or document.subject != manifest.subject
        or document.subject != decision.subject
    ):
        raise ValueError("060 output identity mismatch")
    return document, manifest, decision


def _translate_relation(
    binding: CrossPageRelationBindingV1,
    *,
    item: MinerUCaptureIntakeItem5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    resolution: MaterialProfileResolution,
    relation_kind: RelationKind,
) -> Trusted090RelationInputV1:
    checked = replay_cross_page_relation_binding_v1(binding)
    evidence = item.evidence
    expected_parser_identity = canonical_hash(
        "parser-identity.v1", document.parser.model_dump(mode="python")
    )
    expected_endpoint_kind = "block" if relation_kind == "section" else "table"
    endpoints = (checked.source_endpoint, checked.target_endpoint)
    ids = (
        {entry.block_id for entry in document.blocks}
        if relation_kind == "section"
        else {entry.table_id for entry in document.tables}
    )
    if (
        checked.relation_kind != relation_kind
        or checked.source_sha256 != item.source_sha256
        or checked.parser_identity_sha256 != expected_parser_identity
        or checked.parser_config_sha256 != document.parser.parser_config_hash
        or checked.intake_item_digest_sha256 != item.intake_digest_sha256
        or checked.capture_identity_sha256 != item.capture_identity_sha256
        or checked.raw_structure_sha256 != evidence.raw_structure_sha256
        or checked.artifact_sha256 != evidence.sanitized_structure_sha256
        or checked.cross_page_facts_digest_sha256 != item.cross_page_facts_digest_sha256
        or checked.parsed_document_hash != document.document_hash
        or checked.parse_manifest_hash != manifest.manifest_hash
        or any(endpoint.endpoint_kind != expected_endpoint_kind for endpoint in endpoints)
        or any(endpoint.endpoint_id not in ids for endpoint in endpoints)
    ):
        raise ValueError("086 relation custody mismatch")
    policy_hash = canonical_hash(
        "cross-page-relation-policy-context.v1",
        {
            "material_profile_binding_hash": resolution.binding_hash,
            "parse_policy_receipt": resolution.parse_policy_receipt.model_dump(mode="python"),
            "output_facts": document.output_facts.model_dump(mode="python"),
        },
    )
    replay_hash = canonical_hash(
        "cross-page-relation-replay-context.v1",
        {
            "subject": document.subject.model_dump(mode="python"),
            "parser": document.parser.model_dump(mode="python"),
            "attempt": document.attempt.model_dump(mode="python"),
            "snapshot": document.snapshot.model_dump(mode="python"),
            "output_facts": document.output_facts.model_dump(mode="python"),
            "raw_artifact_sha256": evidence.raw_structure_sha256,
            "sanitized_structure_sha256": evidence.sanitized_structure_sha256,
        },
    )
    values = {
        "contract": "cross-page-relation-binding.v1",
        "relation_id": checked.replay_digest_sha256,
        "relation_kind": (
            "section_continuation" if relation_kind == "section" else "table_continuation"
        ),
        "source_sha256": item.source_sha256,
        "parser_id": document.parser.parser_id,
        "parser_build_id": document.parser.parser_build_id,
        "parser_config_hash": document.parser.parser_config_hash,
        "raw_artifact_sha256": evidence.raw_structure_sha256,
        "sanitized_structure_sha256": evidence.sanitized_structure_sha256,
        "material_profile_binding_hash": resolution.binding_hash,
        "policy_context_hash": policy_hash,
        "replay_context_hash": replay_hash,
        "endpoint_ids": tuple(endpoint.endpoint_id for endpoint in endpoints),
    }
    return Trusted090RelationInputV1.model_validate(
        {
            **values,
            "binding_hash": canonical_hash("cross-page-relation-binding.v1", values),
        }
    )


def _fail_missing_upgrade_profile() -> str:
    raise ValueError("bounded upgrade parser profile is required")


def _map_marker_endpoints(
    marker_map: TypedMarkerEndpointMapV1,
    *,
    document: ParsedDocumentV1,
    relation_kind: RelationKind,
    source_sha256: str,
) -> tuple[str, str]:
    """Map typed page/node/local-index facts to unique canonical 053 endpoints."""

    checked = TypedMarkerEndpointMapV1.model_validate(marker_map)
    expected_node_type = "text" if relation_kind == "section" else "table"
    if (
        checked.source_sha256 != source_sha256
        or checked.relation_kind != relation_kind
        or checked.source_node.node_type != expected_node_type
        or checked.target_node.node_type != expected_node_type
    ):
        raise ValueError("typed marker identity mismatch")

    def resolve(node: TypedMarkerNodeV1) -> str:
        page_number = node.page_index + 1
        if relation_kind == "section":
            matches = tuple(
                item.block_id
                for item in document.blocks
                if item.locator.page_number == page_number
                and item.locator.block_index == node.local_index
            )
        else:
            matches = tuple(
                item.table_id
                for item in document.tables
                if item.locator.page_number == page_number
                and item.locator.table_index == node.local_index
            )
        if len(matches) != 1:
            raise ValueError("typed marker endpoint is not unique")
        return matches[0]

    return resolve(checked.source_node), resolve(checked.target_node)


def assemble_relation_bound_admission_596_1(
    *,
    bundle: MinerUCaptureBundle5961V1,
    source_authorities: tuple[SourceAdmissionAuthorityV1, ...],
    material_profile_resolutions: tuple[MaterialProfileResolution, ...],
    marker_endpoint_mappings: tuple[TypedMarkerEndpointMapV1, ...],
    relation_binding_provider: RelationBindingProvider,
    trusted_builder: Trusted090Builder,
) -> RelationBoundAdmissionResultV1:
    """Compose exact 083/086/090 inputs and finish only through real 061 replay."""

    try:
        intake, authorities, resolutions = _validated_inputs(
            bundle, source_authorities, material_profile_resolutions
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        return _blocked("BLOCKED_ON_INTAKE_AUTHORITY", "INTAKE_AUTHORITY_MISMATCH")
    if trusted_builder is not native_mineru_cloud.build_mineru_parsed_document_v1:
        return _blocked("BLOCKED_ON_PARSE_ADMISSION", "060_BUILDER_AUTHORITY_MISMATCH")

    try:
        marker_maps = tuple(
            TypedMarkerEndpointMapV1.model_validate(item) for item in marker_endpoint_mappings
        )
        source_order = {item.source_sha256: index for index, item in enumerate(intake.sources)}
        observed_order = tuple(source_order[item.source_sha256] for item in marker_maps)
        if not marker_maps or observed_order != tuple(sorted(observed_order)):
            raise ValueError("marker mapping order mismatch")
    except (TypeError, ValueError, ValidationError):
        return _blocked("BLOCKED_ON_RELATION_BINDING", "089_ENDPOINT_AUTHORITY_INSUFFICIENT")

    receipts: list[AdmittedParseArtifactV1] = []
    relation_inputs: list[Trusted090RelationInputV1] = []
    try:
        for item, authority, resolution in zip(
            intake.sources, authorities, resolutions, strict=True
        ):
            subject, parser, attempt, snapshot, output = _parse_inputs(
                authority=authority,
                resolution=resolution,
                raw_hash=item.evidence.raw_structure_sha256,
                parser_config_hash=item.evidence.parser.config_sha256,
            )
            preliminary = _validated_output(
                trusted_builder(
                    item.evidence.sanitized_structure,
                    expected_raw_sha256=item.evidence.raw_structure_sha256,
                    expected_sanitized_sha256=item.evidence.sanitized_structure_sha256,
                    subject=subject,
                    parser=parser,
                    attempt=attempt,
                    snapshot=snapshot,
                    output_facts=output,
                    material_profile_resolution=resolution,
                )
            )
            bindings: tuple[Trusted090RelationInputV1, ...] = ()
            selected_maps = tuple(
                marker_map
                for marker_map in marker_maps
                if marker_map.source_sha256 == item.source_sha256
            )
            if selected_maps:
                kind: RelationKind = "table" if item.role == "rate" else "section"
                mapped_endpoints = tuple(
                    _map_marker_endpoints(
                        marker_map,
                        document=preliminary[0],
                        relation_kind=kind,
                        source_sha256=item.source_sha256,
                    )
                    for marker_map in selected_maps
                )
                supplied = relation_binding_provider(
                    intake, preliminary[0], preliminary[1], relation_kind=kind
                )
                derived_rows = supplied if isinstance(supplied, tuple) else (supplied,)
                if len(derived_rows) != len(selected_maps):
                    raise ValueError("relation provider cardinality mismatch")
                translated_rows = tuple(
                    _translate_relation(
                        derived,
                        item=item,
                        document=preliminary[0],
                        manifest=preliminary[1],
                        resolution=resolution,
                        relation_kind=kind,
                    )
                    for derived in derived_rows
                )
                if tuple(row.endpoint_ids for row in translated_rows) != mapped_endpoints:
                    raise ValueError("089 to 086 endpoint mapping mismatch")
                bindings = translated_rows
                relation_inputs.extend(translated_rows)
            final = _validated_output(
                trusted_builder(
                    item.evidence.sanitized_structure,
                    expected_raw_sha256=item.evidence.raw_structure_sha256,
                    expected_sanitized_sha256=item.evidence.sanitized_structure_sha256,
                    subject=subject,
                    parser=parser,
                    attempt=attempt,
                    snapshot=snapshot,
                    output_facts=output,
                    material_profile_resolution=resolution,
                    trusted_relation_bindings=bindings,
                )
            )
            document, manifest, decision = final
            if (
                decision.decision != "ADMIT"
                or decision.reason_codes
                or decision.admitted_attempt_id != document.attempt.attempt_id
                or manifest.unsatisfied_capabilities
            ):
                raise ValueError("parse quality did not admit")
            receipts.append(
                AdmittedParseArtifactV1(
                    role=_ROLE_MAP[item.role],
                    source_sha256=item.source_sha256,
                    artifact_sha256=document.document_hash,
                    document=document,
                    manifest=manifest,
                    decision=decision,
                    manifest_sha256=manifest.manifest_hash,
                    decision_sha256=decision.decision_hash,
                    sanitized_structure=item.evidence.sanitized_structure,
                    raw_structure_sha256=item.evidence.raw_structure_sha256,
                    sanitized_structure_sha256=item.evidence.sanitized_structure_sha256,
                    capture_identity_sha256=item.capture_identity_sha256,
                    content_snapshot_sha256=item.evidence.content_snapshot_sha256,
                    material_profile_resolution=resolution,
                    trusted_relation_bindings=bindings,
                )
            )
    except Exception:
        return _blocked("BLOCKED_ON_RELATION_BINDING", "RELATION_OR_090_REPLAY_MISMATCH")

    exact_receipts = tuple(receipts)
    admission = admit_596_1_vertical_falsification(admitted_parse_artifacts=exact_receipts)
    if admission.status != "READY_FOR_QUALITY_FALSIFICATION":
        return _blocked("BLOCKED_ON_061_REPLAY", "061_REPLAY_NOT_READY")
    digest = canonical_hash(
        "relation-bound-admission-596-1.v1",
        {
            "intake_bundle_digest_sha256": intake.bundle_digest_sha256,
            "authority": tuple(item.model_dump(mode="python") for item in authorities),
            "relation_bindings": tuple(item.model_dump(mode="python") for item in relation_inputs),
            "receipt_digest_sha256": admission.receipt_digest_sha256,
        },
    )
    return RelationBoundAdmissionResultV1(
        status="READY_FOR_QUALITY_FALSIFICATION",
        admitted_parse_artifacts=exact_receipts,
        admission=admission,
        intake_bundle_digest_sha256=intake.bundle_digest_sha256,
        integration_digest_sha256=digest,
    )


__all__ = [
    "RelationBoundAdmissionResultV1",
    "SourceAdmissionAuthorityV1",
    "TypedMarkerEndpointMapV1",
    "TypedMarkerNodeV1",
    "Trusted090RelationInputV1",
    "assemble_relation_bound_admission_596_1",
]
