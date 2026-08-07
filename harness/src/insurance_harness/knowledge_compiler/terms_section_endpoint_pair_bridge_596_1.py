"""Task-local terms section endpoint-pair derivation for product 596-1."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Annotated, Literal, Never, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.parsed_documents import (
    ParseBlockV1,
    ParsedDocumentV1,
    ParseManifestV1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    NativeCrossPageMarkerEvidenceV1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    POLICY_SHA256,
    CrossPageBindingError,
    CrossPageEndpointV1,
    CrossPageMarkerReplayRequestV1,
    CrossPageRelationBindingV1,
    CrossPageTypedMarkerEvidenceV1,
    derive_cross_page_relation_596_1,
    replay_cross_page_relation_binding_v1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    _replay_intake as _replay_086_intake,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    _validate_document_manifest as _validate_086_document_manifest,
)
from insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1 import (
    RelationReceiptEntry5961V1,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class TermsSectionEndpointBridgeError(ValueError):
    """Privacy-safe, fixed-code failure."""

    def __init__(self, status: Literal["BLOCKED", "NOT_AVAILABLE"], reason_code: str) -> None:
        self.status = status
        self.reason_code = reason_code
        super().__init__(f"{status}:{reason_code}")

    def __repr__(self) -> str:
        return f"TermsSectionEndpointBridgeError({self.status!r}, {self.reason_code!r})"


def _fail(status: Literal["BLOCKED", "NOT_AVAILABLE"], reason_code: str) -> Never:
    raise TermsSectionEndpointBridgeError(status, reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class SectionBlockEndpointV1(_FrozenModel):
    endpoint_id: StrictStr = Field(min_length=1)
    page_number: PositiveInt
    block_index: NonNegativeInt
    order_index: NonNegativeInt
    bbox: tuple[Decimal, Decimal, Decimal, Decimal]
    content_hash: Sha256Hex
    structure_hash: Sha256Hex
    endpoint_fact_digest_sha256: Sha256Hex
    locator_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_endpoint(self) -> Self:
        facts = {
            "block_id": self.endpoint_id,
            "content_hash": self.content_hash,
            "structure_hash": self.structure_hash,
        }
        locator = {
            "page_number": self.page_number,
            "block_index": self.block_index,
            "bbox": self.bbox,
        }
        if self.endpoint_fact_digest_sha256 != canonical_hash(
            "block-endpoint-facts.v1", facts
        ) or self.locator_digest_sha256 != canonical_hash("block-locator.v1", locator):
            raise ValueError("section endpoint digest mismatch")
        return self


class TermsSectionMarkerAuthorityRequestV1(_FrozenModel):
    contract: Literal["terms-section-marker-authority-request.v1"]
    source_sha256: Sha256Hex
    parser_identity_sha256: Sha256Hex
    parser_config_sha256: Sha256Hex
    intake_bundle_digest_sha256: Sha256Hex
    intake_item_digest_sha256: Sha256Hex
    capture_identity_sha256: Sha256Hex
    raw_structure_sha256: Sha256Hex
    sanitized_structure_sha256: Sha256Hex
    raw_zip_sha256: Sha256Hex
    native_member_sha256: Sha256Hex
    member_inventory_sha256: Sha256Hex
    native_projection_sha256: Sha256Hex
    native_observation_sha256: Sha256Hex
    cross_page_facts_digest_sha256: Sha256Hex
    marker_provenance_digest_sha256: Sha256Hex
    marker_provenance_replay_sha256: Sha256Hex
    marker_kind: Literal["cross_page"]
    marker_page_index: NonNegativeInt
    marker_node_type: Literal["text"]
    marker_local_index: NonNegativeInt
    marker_structural_path: StrictStr = Field(min_length=1, repr=False)
    marker_structural_path_sha256: Sha256Hex
    marker_evidence_sha256: Sha256Hex
    source_endpoint: SectionBlockEndpointV1
    target_endpoint: SectionBlockEndpointV1
    request_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_request(self) -> Self:
        if (
            self.marker_structural_path != f"p{self.marker_page_index}/b{self.marker_local_index}"
            or self.marker_page_index + 1 != self.source_endpoint.page_number
            or self.marker_local_index != self.source_endpoint.block_index
            or self.target_endpoint.page_number != self.source_endpoint.page_number + 1
            or self.target_endpoint.order_index <= self.source_endpoint.order_index
        ):
            raise ValueError("section marker endpoint mapping mismatch")
        expected = canonical_hash(
            "terms-section-marker-authority-request.v1",
            self.model_dump(mode="python", exclude={"request_digest_sha256"}),
        )
        if self.request_digest_sha256 != expected:
            raise ValueError("section authority request digest mismatch")
        return self


class TermsSectionMarkerAuthorityEvidenceV1(_FrozenModel):
    contract: Literal["terms-section-marker-authority-evidence.v1"]
    authority_contract: Literal["marker-authority-envelope.v1"]
    authority_version_sha256: Sha256Hex
    request_digest_sha256: Sha256Hex
    marker_kind: Literal["cross_page"]
    relation_kind: Literal["section"]
    source_endpoint_id: StrictStr = Field(min_length=1)
    source_page_number: PositiveInt
    source_endpoint_path_sha256: Sha256Hex
    target_endpoint_id: StrictStr = Field(min_length=1)
    target_page_number: PositiveInt
    target_endpoint_path_sha256: Sha256Hex
    source_section_ancestry_node_hashes: tuple[Sha256Hex, ...]
    target_section_ancestry_node_hashes: tuple[Sha256Hex, ...]
    section_ancestry_sha256: Sha256Hex
    source_outline_anchor_node_hashes: tuple[Sha256Hex, ...]
    target_outline_anchor_node_hashes: tuple[Sha256Hex, ...]
    outline_anchor_sha256: Sha256Hex
    target_starts_new_heading: StrictBool
    authority_preimage_sha256: Sha256Hex
    evidence_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_evidence(self) -> Self:
        authority_preimage = {
            "authority_contract": self.authority_contract,
            "authority_version_sha256": self.authority_version_sha256,
            "request_digest_sha256": self.request_digest_sha256,
            "marker_kind": self.marker_kind,
            "relation_kind": self.relation_kind,
            "source_endpoint_id": self.source_endpoint_id,
            "source_page_number": self.source_page_number,
            "source_endpoint_path_sha256": self.source_endpoint_path_sha256,
            "target_endpoint_id": self.target_endpoint_id,
            "target_page_number": self.target_page_number,
            "target_endpoint_path_sha256": self.target_endpoint_path_sha256,
            "source_section_ancestry_node_hashes": self.source_section_ancestry_node_hashes,
            "target_section_ancestry_node_hashes": self.target_section_ancestry_node_hashes,
            "source_outline_anchor_node_hashes": self.source_outline_anchor_node_hashes,
            "target_outline_anchor_node_hashes": self.target_outline_anchor_node_hashes,
            "target_starts_new_heading": self.target_starts_new_heading,
        }
        if (
            self.target_starts_new_heading
            or not self.source_section_ancestry_node_hashes
            or not self.source_outline_anchor_node_hashes
            or self.source_section_ancestry_node_hashes
            != self.target_section_ancestry_node_hashes
            or self.source_outline_anchor_node_hashes
            != self.target_outline_anchor_node_hashes
            or self.section_ancestry_sha256
            != canonical_hash(
                "terms-section-ancestry.v1", self.source_section_ancestry_node_hashes
            )
            or self.outline_anchor_sha256
            != canonical_hash(
                "terms-section-outline-anchor.v1", self.source_outline_anchor_node_hashes
            )
            or self.authority_preimage_sha256
            != canonical_hash("terms-section-marker-authority-preimage.v1", authority_preimage)
        ):
            raise ValueError("new heading cannot continue the same section")
        expected = canonical_hash(
            "terms-section-marker-authority-evidence.v1",
            self.model_dump(mode="python", exclude={"evidence_digest_sha256"}),
        )
        if self.evidence_digest_sha256 != expected:
            raise ValueError("section authority evidence digest mismatch")
        return self


class MarkerAuthorityEnvelopeV1Protocol(Protocol):
    """Narrow seam for the future frozen 101 authority envelope."""

    def replay_terms_section_authority(
        self, request: TermsSectionMarkerAuthorityRequestV1
    ) -> TermsSectionMarkerAuthorityEvidenceV1 | None: ...


class SectionEndpointPairReplayV1(_FrozenModel):
    contract: Literal["terms-section-endpoint-pair-replay-596-1.v1"]
    status: Literal["SECTION_ENDPOINT_PAIR_INPUT_VERIFIED"]
    relation_kind: Literal["section"]
    source_sha256: Sha256Hex
    parser_model: Literal["pipeline"]
    mineru_version: Literal["3.4.4"]
    parser_identity_sha256: Sha256Hex
    parser_config_sha256: Sha256Hex
    intake_bundle_digest_sha256: Sha256Hex
    intake_item_digest_sha256: Sha256Hex
    capture_identity_sha256: Sha256Hex
    raw_structure_sha256: Sha256Hex
    sanitized_structure_sha256: Sha256Hex
    raw_zip_sha256: Sha256Hex
    native_member_sha256: Sha256Hex
    member_inventory_sha256: Sha256Hex
    native_projection_sha256: Sha256Hex
    native_observation_sha256: Sha256Hex
    cross_page_facts_digest_sha256: Sha256Hex
    marker_provenance_digest_sha256: Sha256Hex
    marker_provenance_replay_sha256: Sha256Hex
    marker_kind: Literal["cross_page"]
    marker_page_index: NonNegativeInt
    marker_node_type: Literal["text"]
    marker_local_index: NonNegativeInt
    marker_structural_path: StrictStr = Field(min_length=1, repr=False)
    marker_structural_path_sha256_101: Sha256Hex
    marker_path_sha256_086: Sha256Hex
    marker_evidence_sha256: Sha256Hex
    source_endpoint: SectionBlockEndpointV1
    target_endpoint: SectionBlockEndpointV1
    section_ancestry_sha256: Sha256Hex
    outline_anchor_sha256: Sha256Hex
    authority_version_sha256: Sha256Hex
    authority_preimage_sha256: Sha256Hex
    authority_evidence_digest_sha256: Sha256Hex
    structural_rule_sha256: Sha256Hex
    policy_sha256: Sha256Hex
    replay_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_pair(self) -> Self:
        rule = {
            "relation_kind": "section",
            "page_delta": 1,
            "target_selection": "next-page-first-qualified-reading-order-block",
            "section_ancestry": self.section_ancestry_sha256,
            "outline_anchor": self.outline_anchor_sha256,
            "candidate_cardinality": 1,
            "source_endpoint": self.source_endpoint.model_dump(mode="python"),
            "target_endpoint": self.target_endpoint.model_dump(mode="python"),
        }
        if (
            self.policy_sha256 != POLICY_SHA256
            or self.marker_structural_path
            != f"p{self.marker_page_index}/b{self.marker_local_index}"
            or self.marker_path_sha256_086
            != canonical_hash("mineru-native-structural-path.v1", self.marker_structural_path)
            or self.target_endpoint.page_number != self.source_endpoint.page_number + 1
            or self.structural_rule_sha256
            != canonical_hash("terms-section-structural-rule.v1", rule)
        ):
            raise ValueError("section endpoint-pair policy mismatch")
        expected = canonical_hash(
            "terms-section-endpoint-pair-replay-596-1.v1",
            self.model_dump(mode="python", exclude={"replay_digest_sha256"}),
        )
        if self.replay_digest_sha256 != expected:
            raise ValueError("section endpoint-pair replay digest mismatch")
        return self

    def replay_typed_cross_page_marker(
        self, request: CrossPageMarkerReplayRequestV1
    ) -> CrossPageTypedMarkerEvidenceV1 | None:
        if not (
            request.source_sha256 == self.source_sha256
            and request.parser_model == self.parser_model
            and request.mineru_version == self.mineru_version
            and request.raw_zip_sha256 == self.raw_zip_sha256
            and request.native_member_sha256 == self.native_member_sha256
            and request.member_inventory_sha256 == self.member_inventory_sha256
            and request.native_projection_sha256 == self.native_projection_sha256
            and request.native_observation_sha256 == self.native_observation_sha256
            and request.cross_page_facts_digest_sha256 == self.cross_page_facts_digest_sha256
            and request.relation_kind == "section"
        ):
            return None
        values: dict[str, object] = {
            "contract": "cross-page-typed-marker-evidence.v1",
            "authority": "future-089-typed-marker-replay",
            "request_digest_sha256": request.request_digest_sha256,
            "marker_kind": "cross_page",
            "relation_kind": "section",
            "marker_structural_path": self.marker_structural_path,
            "marker_path_sha256": self.marker_path_sha256_086,
            "source_endpoint_id": self.source_endpoint.endpoint_id,
            "source_page_number": self.source_endpoint.page_number,
            "source_endpoint_path_sha256": self.source_endpoint.locator_digest_sha256,
            "target_endpoint_id": self.target_endpoint.endpoint_id,
            "target_page_number": self.target_endpoint.page_number,
            "target_endpoint_path_sha256": self.target_endpoint.locator_digest_sha256,
        }
        return CrossPageTypedMarkerEvidenceV1.model_validate(
            {
                **values,
                "evidence_digest_sha256": canonical_hash(
                    "cross-page-typed-marker-evidence.v1", values
                ),
            }
        )


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _go_path_sha256(source_sha256: str, member_sha256: str, path: str) -> str:
    return _sha256(
        f"mineru-cross-page-marker-path.v1\0{source_sha256}\0{member_sha256}\0{path}"
    )


def _block_endpoint(block: ParseBlockV1) -> SectionBlockEndpointV1:
    return SectionBlockEndpointV1(
        endpoint_id=block.block_id,
        page_number=block.locator.page_number,
        block_index=block.locator.block_index,
        order_index=block.order_index,
        bbox=block.locator.bbox,
        content_hash=block.content_hash,
        structure_hash=block.structure_hash,
        endpoint_fact_digest_sha256=canonical_hash(
            "block-endpoint-facts.v1",
            {
                "block_id": block.block_id,
                "content_hash": block.content_hash,
                "structure_hash": block.structure_hash,
            },
        ),
        locator_digest_sha256=canonical_hash(
            "block-locator.v1", block.locator.model_dump(mode="python")
        ),
    )


def _source_marker(
    markers: tuple[NativeCrossPageMarkerEvidenceV1, ...],
) -> NativeCrossPageMarkerEvidenceV1:
    if any(marker.marker_kind == "lines_deleted" for marker in markers):
        _fail("BLOCKED", "LINES_DELETED_NOT_SECTION_AUTHORITY")
    cross_page = tuple(marker for marker in markers if marker.marker_kind == "cross_page")
    if len(cross_page) != 1:
        _fail("BLOCKED", "SECTION_SOURCE_MARKER_CARDINALITY_INVALID")
    marker = cross_page[0]
    if marker.node_type != "text":
        _fail("BLOCKED", "SECTION_MARKER_NODE_TYPE_INVALID")
    return marker


def _subject_refs(
    document: ParsedDocumentV1, capability: str, *, unsupported: bool = False
) -> set[str]:
    rows = document.unsupported if unsupported else document.capability_evidence
    matches = tuple(row for row in rows if row.capability == capability)
    if len(matches) != 1:
        _fail("BLOCKED", "SECTION_CAPABILITY_FACTS_INVALID")
    return set(matches[0].subject_refs)


def derive_terms_section_endpoint_pair_596_1(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    authority: MarkerAuthorityEnvelopeV1Protocol | None,
) -> SectionEndpointPairReplayV1:
    """Derive one section pair only when the external structural anchor replays."""

    try:
        intake = _replay_086_intake(bundle, preserve_marker_envelope=True)
        item = intake.sources[0]
        doc, _ = _validate_086_document_manifest(
            item.evidence,
            ParsedDocumentV1.model_validate(document),
            ParseManifestV1.model_validate(manifest),
            expected_source_sha256=item.source_sha256,
            relation_kind="section",
        )
    except (CrossPageBindingError, TypeError, ValidationError, ValueError):
        _fail("BLOCKED", "SECTION_INPUT_REPLAY_FAILED")
    facts = item.evidence.cross_page_facts
    provenance = item.evidence.cross_page_marker_provenance
    if (
        item.role != "terms"
        or facts is None
        or provenance is None
        or item.cross_page_facts_digest_sha256 is None
        or item.marker_provenance_digest_sha256 is None
        or facts.status != "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS"
        or facts.required_capability != "cross_page_sections"
        or facts.relation_count != 0
        or facts.relations
        or facts.ambiguous_marker_count != 1
        or len(facts.ambiguous_observation_hashes) != 1
        or provenance.marker_count != len(provenance.markers)
        or provenance.marker_count != facts.ambiguous_marker_count
        or provenance.source_sha256 != item.source_sha256
        or provenance.raw_zip_sha256 != facts.raw_zip_sha256
        or provenance.native_member_sha256 != facts.native_member_sha256
        or provenance.parser_model != facts.parser_model
        or provenance.mineru_version != facts.mineru_version
    ):
        _fail("BLOCKED", "SECTION_MARKER_CUSTODY_INCOMPLETE")
    marker = _source_marker(provenance.markers)
    path = f"p{marker.page_index}/b{marker.local_index}"
    if marker.structural_path_sha256 != _go_path_sha256(
        item.source_sha256, provenance.native_member_sha256, path
    ):
        _fail("BLOCKED", "SECTION_MARKER_PATH_DRIFT")

    source_rows = tuple(
        block
        for block in doc.blocks
        if block.locator.page_number == marker.page_index + 1
        and block.locator.block_index == marker.local_index
    )
    if not source_rows:
        _fail("NOT_AVAILABLE", "SECTION_SOURCE_ENDPOINT_NOT_AVAILABLE")
    if len(source_rows) != 1:
        _fail("BLOCKED", "SECTION_SOURCE_ENDPOINT_AMBIGUOUS")
    source = source_rows[0]
    qualified = _subject_refs(doc, "block_locators")
    section_refs = _subject_refs(doc, "cross_page_sections", unsupported=True)
    if source.block_id not in qualified or source.block_id not in section_refs:
        _fail("BLOCKED", "SECTION_SOURCE_CAPABILITY_DRIFT")
    next_page = source.locator.page_number + 1
    target_rows = tuple(
        block
        for block in doc.blocks
        if block.locator.page_number == next_page
        and block.block_id in qualified
        and block.block_id in section_refs
    )
    if not target_rows:
        _fail("NOT_AVAILABLE", "SECTION_TARGET_ENDPOINT_NOT_AVAILABLE")
    first_order = min(block.order_index for block in target_rows)
    first_rows = tuple(block for block in target_rows if block.order_index == first_order)
    if len(first_rows) != 1:
        _fail("BLOCKED", "SECTION_TARGET_ENDPOINT_AMBIGUOUS")
    target = first_rows[0]
    source_endpoint = _block_endpoint(source)
    target_endpoint = _block_endpoint(target)
    parser_identity = canonical_hash("parser-identity.v1", doc.parser.model_dump(mode="python"))
    request_values = {
        "contract": "terms-section-marker-authority-request.v1",
        "source_sha256": item.source_sha256,
        "parser_identity_sha256": parser_identity,
        "parser_config_sha256": item.evidence.parser.config_sha256,
        "intake_bundle_digest_sha256": intake.bundle_digest_sha256,
        "intake_item_digest_sha256": item.intake_digest_sha256,
        "capture_identity_sha256": item.capture_identity_sha256,
        "raw_structure_sha256": item.evidence.raw_structure_sha256,
        "sanitized_structure_sha256": item.evidence.sanitized_structure_sha256,
        "raw_zip_sha256": provenance.raw_zip_sha256,
        "native_member_sha256": provenance.native_member_sha256,
        "member_inventory_sha256": facts.member_inventory_sha256,
        "native_projection_sha256": facts.projection_sha256,
        "native_observation_sha256": facts.ambiguous_observation_hashes[0],
        "cross_page_facts_digest_sha256": item.cross_page_facts_digest_sha256,
        "marker_provenance_digest_sha256": item.marker_provenance_digest_sha256,
        "marker_provenance_replay_sha256": provenance.replay_digest_sha256,
        "marker_kind": "cross_page",
        "marker_page_index": marker.page_index,
        "marker_node_type": "text",
        "marker_local_index": marker.local_index,
        "marker_structural_path": path,
        "marker_structural_path_sha256": marker.structural_path_sha256,
        "marker_evidence_sha256": marker.marker_sha256,
        "source_endpoint": source_endpoint.model_dump(mode="python"),
        "target_endpoint": target_endpoint.model_dump(mode="python"),
    }
    request = TermsSectionMarkerAuthorityRequestV1.model_validate(
        {
            **request_values,
            "request_digest_sha256": canonical_hash(
                "terms-section-marker-authority-request.v1", request_values
            ),
        }
    )
    if authority is None:
        _fail("NOT_AVAILABLE", "SECTION_ANCHOR_NOT_AVAILABLE")
    try:
        evidence = TermsSectionMarkerAuthorityEvidenceV1.model_validate(
            authority.replay_terms_section_authority(request)
        )
    except (AttributeError, TypeError, ValidationError, ValueError):
        _fail("BLOCKED", "SECTION_AUTHORITY_REPLAY_INVALID")
    if (
        evidence.request_digest_sha256 != request.request_digest_sha256
        or evidence.source_endpoint_id != source.block_id
        or evidence.source_page_number != source.locator.page_number
        or evidence.source_endpoint_path_sha256 != source_endpoint.locator_digest_sha256
        or evidence.target_endpoint_id != target.block_id
        or evidence.target_page_number != target.locator.page_number
        or evidence.target_endpoint_path_sha256 != target_endpoint.locator_digest_sha256
    ):
        _fail("BLOCKED", "SECTION_AUTHORITY_ENDPOINT_DRIFT")
    rule = {
        "relation_kind": "section",
        "page_delta": 1,
        "target_selection": "next-page-first-qualified-reading-order-block",
        "section_ancestry": evidence.section_ancestry_sha256,
        "outline_anchor": evidence.outline_anchor_sha256,
        "candidate_cardinality": 1,
        "source_endpoint": source_endpoint.model_dump(mode="python"),
        "target_endpoint": target_endpoint.model_dump(mode="python"),
    }
    values = {
        "contract": "terms-section-endpoint-pair-replay-596-1.v1",
        "status": "SECTION_ENDPOINT_PAIR_INPUT_VERIFIED",
        "relation_kind": "section",
        "source_sha256": item.source_sha256,
        "parser_model": provenance.parser_model,
        "mineru_version": provenance.mineru_version,
        "parser_identity_sha256": parser_identity,
        "parser_config_sha256": item.evidence.parser.config_sha256,
        "intake_bundle_digest_sha256": intake.bundle_digest_sha256,
        "intake_item_digest_sha256": item.intake_digest_sha256,
        "capture_identity_sha256": item.capture_identity_sha256,
        "raw_structure_sha256": item.evidence.raw_structure_sha256,
        "sanitized_structure_sha256": item.evidence.sanitized_structure_sha256,
        "raw_zip_sha256": provenance.raw_zip_sha256,
        "native_member_sha256": provenance.native_member_sha256,
        "member_inventory_sha256": facts.member_inventory_sha256,
        "native_projection_sha256": facts.projection_sha256,
        "native_observation_sha256": facts.ambiguous_observation_hashes[0],
        "cross_page_facts_digest_sha256": item.cross_page_facts_digest_sha256,
        "marker_provenance_digest_sha256": item.marker_provenance_digest_sha256,
        "marker_provenance_replay_sha256": provenance.replay_digest_sha256,
        "marker_kind": "cross_page",
        "marker_page_index": marker.page_index,
        "marker_node_type": "text",
        "marker_local_index": marker.local_index,
        "marker_structural_path": path,
        "marker_structural_path_sha256_101": marker.structural_path_sha256,
        "marker_path_sha256_086": canonical_hash("mineru-native-structural-path.v1", path),
        "marker_evidence_sha256": marker.marker_sha256,
        "source_endpoint": source_endpoint.model_dump(mode="python"),
        "target_endpoint": target_endpoint.model_dump(mode="python"),
        "section_ancestry_sha256": evidence.section_ancestry_sha256,
        "outline_anchor_sha256": evidence.outline_anchor_sha256,
        "authority_version_sha256": evidence.authority_version_sha256,
        "authority_preimage_sha256": evidence.authority_preimage_sha256,
        "authority_evidence_digest_sha256": evidence.evidence_digest_sha256,
        "structural_rule_sha256": canonical_hash("terms-section-structural-rule.v1", rule),
        "policy_sha256": POLICY_SHA256,
    }
    values["replay_digest_sha256"] = canonical_hash(
        "terms-section-endpoint-pair-replay-596-1.v1", values
    )
    try:
        return SectionEndpointPairReplayV1.model_validate(values)
    except (TypeError, ValidationError, ValueError):
        _fail("BLOCKED", "SECTION_ENDPOINT_PAIR_INPUT_INVALID")


def derive_terms_section_binding_596_1(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    authority: MarkerAuthorityEnvelopeV1Protocol,
) -> CrossPageRelationBindingV1:
    pair = derive_terms_section_endpoint_pair_596_1(bundle, document, manifest, authority)
    return derive_cross_page_relation_596_1(
        bundle,
        document,
        manifest,
        relation_kind="section",
        marker_replay=pair,
        preserve_marker_envelope=True,
    )


def derive_terms_section_receipt_entry_596_1(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    authority: MarkerAuthorityEnvelopeV1Protocol,
) -> RelationReceiptEntry5961V1:
    checked = MinerUCaptureBundle5961V1.model_validate(bundle)
    binding = derive_terms_section_binding_596_1(checked, document, manifest, authority)
    terms = checked.sources[0]
    if terms.marker_provenance_digest_sha256 is None:
        _fail("BLOCKED", "SECTION_MARKER_CUSTODY_INCOMPLETE")
    return RelationReceiptEntry5961V1(
        receipt_role="terms",
        intake_item_digest_sha256=terms.intake_digest_sha256,
        capture_identity_sha256=terms.capture_identity_sha256,
        marker_provenance_digest_sha256=terms.marker_provenance_digest_sha256,
        binding=binding,
    )


def derive_terms_section_receipt_entries_596_1(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    authority: object,
    *,
    source_role: Literal["terms", "brochure"] = "terms",
) -> tuple[RelationReceiptEntry5961V1, ...]:
    """Project an ordered native section-authority collection into 096 entries."""

    # The lazy import avoids a module cycle: 106 reuses 103's endpoint DTOs.
    from insurance_harness.knowledge_compiler.mineru_native_section_anchor_evidence_596_1 import (
        TermsSectionAnchorAuthorityCollectionV1,
    )

    try:
        checked_authority = TermsSectionAnchorAuthorityCollectionV1.model_validate(authority)
        intake = _replay_086_intake(bundle, preserve_marker_envelope=True)
        source_index = 0 if source_role == "terms" else 1
        item = intake.sources[source_index]
        doc, checked_manifest = _validate_086_document_manifest(
            item.evidence,
            ParsedDocumentV1.model_validate(document),
            ParseManifestV1.model_validate(manifest),
            expected_source_sha256=item.source_sha256,
            relation_kind="section",
        )
    except (CrossPageBindingError, TypeError, ValidationError, ValueError):
        _fail("BLOCKED", "SECTION_INPUT_REPLAY_FAILED")
    facts = item.evidence.cross_page_facts
    provenance = item.evidence.cross_page_marker_provenance
    parser_identity = canonical_hash(
        "parser-identity.v1", doc.parser.model_dump(mode="python")
    )
    if (
        facts is None
        or provenance is None
        or item.cross_page_facts_digest_sha256 is None
        or item.marker_provenance_digest_sha256 is None
        or checked_authority.source_sha256 != item.source_sha256
        or checked_authority.parser_identity_sha256 != parser_identity
        or checked_authority.parser_config_sha256 != item.evidence.parser.config_sha256
        or checked_authority.intake_bundle_digest_sha256 != intake.bundle_digest_sha256
        or checked_authority.intake_item_digest_sha256 != item.intake_digest_sha256
        or checked_authority.capture_identity_sha256 != item.capture_identity_sha256
        or checked_authority.raw_structure_sha256 != item.evidence.raw_structure_sha256
        or checked_authority.sanitized_structure_sha256
        != item.evidence.sanitized_structure_sha256
        or checked_authority.raw_zip_sha256 != provenance.raw_zip_sha256
        or checked_authority.native_member_sha256 != provenance.native_member_sha256
        or checked_authority.member_inventory_sha256 != facts.member_inventory_sha256
        or checked_authority.native_projection_sha256 != facts.projection_sha256
        or checked_authority.cross_page_facts_digest_sha256
        != item.cross_page_facts_digest_sha256
        or checked_authority.marker_provenance_digest_sha256
        != item.marker_provenance_digest_sha256
        or checked_authority.marker_provenance_replay_sha256
        != provenance.replay_digest_sha256
        or checked_authority.parsed_document_sha256 != doc.document_hash
        or checked_authority.parse_manifest_sha256 != checked_manifest.manifest_hash
    ):
        _fail("BLOCKED", "SECTION_AUTHORITY_COLLECTION_DRIFT")

    marker_hashes = {marker.marker_sha256 for marker in provenance.markers}
    entries: list[RelationReceiptEntry5961V1] = []
    for relation in checked_authority.relations:
        group = relation.marker_group
        native_observation_sha256 = hashlib.sha256(
            (
                "mineru-cross-page-ambiguous.v1\0"
                f"{item.source_sha256}\0cross_page\0"
                f"{group.source_marker_structural_paths[0]}"
            ).encode()
        ).hexdigest()
        if (
            not set(group.source_marker_evidence_sha256) <= marker_hashes
            or group.target_marker_evidence_sha256 not in marker_hashes
            or native_observation_sha256 not in facts.ambiguous_observation_hashes
        ):
            _fail("BLOCKED", "SECTION_AUTHORITY_COLLECTION_DRIFT")
        source = CrossPageEndpointV1(
            endpoint_kind="block",
            endpoint_id=relation.source_endpoint.endpoint_id,
            page_number=relation.source_endpoint.page_number,
            endpoint_fact_digest_sha256=(
                relation.source_endpoint.endpoint_fact_digest_sha256
            ),
            locator_digest_sha256=relation.source_endpoint.locator_digest_sha256,
        )
        target = CrossPageEndpointV1(
            endpoint_kind="block",
            endpoint_id=relation.target_endpoint.endpoint_id,
            page_number=relation.target_endpoint.page_number,
            endpoint_fact_digest_sha256=(
                relation.target_endpoint.endpoint_fact_digest_sha256
            ),
            locator_digest_sha256=relation.target_endpoint.locator_digest_sha256,
        )
        values: dict[str, object] = {
            "contract": "cross-page-relation-binding.v1",
            "status": "DERIVED_STRUCTURAL_BINDING_VERIFIED",
            "provenance": "DERIVED_STRUCTURAL_RELATION",
            "relation_kind": "section",
            "source_sha256": item.source_sha256,
            "parser_identity_sha256": parser_identity,
            "parser_config_sha256": item.evidence.parser.config_sha256,
            "intake_bundle_digest_sha256": intake.bundle_digest_sha256,
            "intake_item_digest_sha256": item.intake_digest_sha256,
            "capture_identity_sha256": item.capture_identity_sha256,
            "raw_structure_sha256": item.evidence.raw_structure_sha256,
            "artifact_sha256": item.evidence.sanitized_structure_sha256,
            "cross_page_facts_digest_sha256": item.cross_page_facts_digest_sha256,
            "parsed_document_hash": doc.document_hash,
            "parse_manifest_hash": checked_manifest.manifest_hash,
            "native_projection_sha256": facts.projection_sha256,
            "native_observation_sha256": native_observation_sha256,
            "typed_marker_evidence_digest_sha256": relation.relation_digest_sha256,
            "marker_path_sha256": canonical_hash(
                "mineru-native-structural-path.v1", group.source_structural_path
            ),
            "policy_sha256": POLICY_SHA256,
            "source_endpoint": source.model_dump(mode="python"),
            "target_endpoint": target.model_dump(mode="python"),
        }
        binding = replay_cross_page_relation_binding_v1(
            CrossPageRelationBindingV1.model_validate(
                {
                    **values,
                    "replay_digest_sha256": canonical_hash(
                        "cross-page-relation-binding.v1", values
                    ),
                }
            )
        )
        entries.append(
            RelationReceiptEntry5961V1(
                receipt_role=source_role,
                intake_item_digest_sha256=item.intake_digest_sha256,
                capture_identity_sha256=item.capture_identity_sha256,
                marker_provenance_digest_sha256=item.marker_provenance_digest_sha256,
                binding=binding,
            )
        )
    return tuple(entries)


__all__ = [
    "MarkerAuthorityEnvelopeV1Protocol",
    "SectionEndpointPairReplayV1",
    "TermsSectionEndpointBridgeError",
    "TermsSectionMarkerAuthorityEvidenceV1",
    "TermsSectionMarkerAuthorityRequestV1",
    "derive_terms_section_binding_596_1",
    "derive_terms_section_endpoint_pair_596_1",
    "derive_terms_section_receipt_entry_596_1",
    "derive_terms_section_receipt_entries_596_1",
]
