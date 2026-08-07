"""Structural-only section-anchor authority for the 596-1 terms bridge."""

from __future__ import annotations

import hashlib
from typing import Annotated, Any, Literal, Never, Self

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
from insurance_harness.compiler.parsed_documents import (
    ParseBlockV1,
    ParsedDocumentV1,
    ParseManifestV1,
)
from insurance_harness.knowledge_compiler.marker_authority_envelope_596_1 import (
    MarkerAuthorityEnvelopeV1,
    MarkerAuthorityV1,
    MarkerSourceAuthorityV1,
    recompute_marker_authority_envelope_sha256,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    NativeCrossPageMarkerProvenanceV1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    _replay_intake as _replay_intake,
)
from insurance_harness.knowledge_compiler.terms_section_endpoint_pair_bridge_596_1 import (
    SectionBlockEndpointV1,
    TermsSectionMarkerAuthorityEvidenceV1,
    TermsSectionMarkerAuthorityRequestV1,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]

_CONTRACT = "mineru-native-section-anchor-evidence-596-1.v1"
_STRUCTURAL_TYPES = frozenset({"title", "section"})
_EXCLUDED_TYPES = frozenset({"header", "footer", "page_header", "page_footer", "page_number"})
_CONTENT_TYPES = frozenset(
    {"text", "table", "image", "chart", "equation", "code", "list", "aside_text", "page_footnote"}
)
_SECTION_SOURCE_SHA256 = frozenset(
    {
        "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
        "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
    }
)


class SectionAnchorEvidenceError(ValueError):
    """Fixed-code failure that never echoes native content."""

    def __init__(self, status: Literal["BLOCKED", "NOT_AVAILABLE"], reason_code: str) -> None:
        self.status = status
        self.reason_code = reason_code
        super().__init__(f"{status}:{reason_code}")

    def __repr__(self) -> str:
        return f"SectionAnchorEvidenceError({self.status!r}, {self.reason_code!r})"


def _fail(status: Literal["BLOCKED", "NOT_AVAILABLE"], reason: str) -> Never:
    raise SectionAnchorEvidenceError(status, reason)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class TermsSectionMarkerRelationGroupV1(_FrozenModel):
    contract: Literal["terms-section-marker-relation-group-596-1.v1"]
    source_page_index: NonNegativeInt
    source_block_index: NonNegativeInt
    source_structural_path: StrictStr = Field(pattern=r"^p[0-9]+/b[0-9]+$")
    source_marker_count: PositiveInt
    source_marker_structural_paths: tuple[StrictStr, ...] = Field(min_length=1)
    source_marker_structural_path_sha256: tuple[Sha256Hex, ...] = Field(min_length=1)
    source_marker_evidence_sha256: tuple[Sha256Hex, ...] = Field(min_length=1)
    source_node_preimage_sha256: Sha256Hex
    target_page_index: NonNegativeInt
    target_block_index: NonNegativeInt
    target_structural_path: StrictStr = Field(pattern=r"^p[0-9]+/b[0-9]+$")
    target_marker_evidence_sha256: Sha256Hex
    target_node_preimage_sha256: Sha256Hex
    section_ancestor_node_sha256: tuple[Sha256Hex, ...] = Field(min_length=1)
    relation_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_relation(self) -> Self:
        if (
            self.target_page_index != self.source_page_index + 1
            or self.source_structural_path
            != f"p{self.source_page_index}/b{self.source_block_index}"
            or self.target_structural_path
            != f"p{self.target_page_index}/b{self.target_block_index}"
            or self.source_marker_count != len(self.source_marker_structural_paths)
            or self.source_marker_count
            != len(self.source_marker_structural_path_sha256)
            or self.source_marker_count != len(self.source_marker_evidence_sha256)
            or len(set(self.source_marker_structural_paths))
            != self.source_marker_count
            or any(
                not path.startswith(self.source_structural_path + "/")
                for path in self.source_marker_structural_paths
            )
        ):
            raise ValueError("section marker relation group invalid")
        expected = canonical_hash(
            self.contract,
            self.model_dump(mode="json", exclude={"relation_digest_sha256"}),
        )
        if self.relation_digest_sha256 != expected:
            raise ValueError("section marker relation digest invalid")
        return self


def _native_path_key(value: str) -> tuple[int, ...]:
    parts = value.split("/")
    numbers = [int(parts[0][1:]), int(parts[1][1:])]
    numbers.extend(int(parts[index]) for index in range(3, len(parts), 2))
    return tuple(numbers)


def group_terms_cross_page_markers_596_1(
    provenance: NativeCrossPageMarkerProvenanceV1,
) -> tuple[TermsSectionMarkerRelationGroupV1, ...]:
    """Bind nested cross-page markers to next-page deletion placeholders and section ancestry."""

    if (
        not isinstance(provenance, NativeCrossPageMarkerProvenanceV1)
        or provenance.source_sha256 not in _SECTION_SOURCE_SHA256
        or provenance.parser_model != "pipeline"
        or provenance.mineru_version != "3.4.4"
        or provenance.marker_count != len(provenance.markers)
        or provenance.native_hierarchy_provenance is None
        or provenance.native_hierarchy_provenance.status
        != "NATIVE_HIERARCHY_PROVENANCE_CAPTURED"
    ):
        _fail("BLOCKED", "SECTION_MARKER_AUTHORITY_INVALID")
    hierarchy = provenance.native_hierarchy_provenance
    nodes = tuple(sorted(hierarchy.nodes, key=lambda node: node.reading_order))
    nodes_by_path = {node.structural_path: node for node in nodes}
    if len(nodes_by_path) != len(nodes):
        _fail("BLOCKED", "SECTION_NATIVE_READING_ORDER_INVALID")

    ancestry_by_path: dict[str, tuple[str, ...]] = {}
    stack: list[tuple[int, str]] = []
    for node in nodes:
        if node.text_level is not None or node.node_type in _STRUCTURAL_TYPES:
            level = node.text_level or 1
            stack = [item for item in stack if item[0] < level]
            stack.append((level, node.node_preimage_sha256))
        ancestry_by_path[node.structural_path] = tuple(item[1] for item in stack)

    source_groups: dict[str, list[Any]] = {}
    targets: dict[int, list[Any]] = {}
    for marker in provenance.markers:
        path = marker.structural_path
        if path is None:
            _fail("BLOCKED", "SECTION_MARKER_PATH_INVALID")
        parts = path.split("/")
        top_path = "/".join(parts[:2])
        if marker.marker_kind == "cross_page":
            if marker.node_type != "text" or len(parts) == 2:
                _fail("BLOCKED", "SECTION_MARKER_PATH_INVALID")
            source_groups.setdefault(top_path, []).append(marker)
        else:
            if marker.node_type != "text" or path != top_path:
                _fail("BLOCKED", "SECTION_TARGET_MARKER_INVALID")
            targets.setdefault(marker.page_index, []).append(marker)
    if not source_groups:
        _fail("NOT_AVAILABLE", "SECTION_ANCHOR_NOT_AVAILABLE")

    relations: list[TermsSectionMarkerRelationGroupV1] = []
    used_targets: set[str] = set()
    for source_path in sorted(source_groups, key=_native_path_key):
        source_node = nodes_by_path.get(source_path)
        markers = tuple(
            sorted(
                source_groups[source_path],
                key=lambda marker: _native_path_key(marker.structural_path or ""),
            )
        )
        if source_node is None or any(
            marker.page_index != source_node.page_index for marker in markers
        ):
            _fail("BLOCKED", "SECTION_MARKER_NODE_DRIFT")
        target_rows = tuple(targets.get(source_node.page_index + 1, ()))
        if len(target_rows) != 1:
            _fail("BLOCKED", "SECTION_TARGET_MARKER_INVALID")
        target_marker = target_rows[0]
        target_path = target_marker.structural_path
        target_node = nodes_by_path.get(target_path or "")
        if target_node is None or target_path is None:
            _fail("BLOCKED", "SECTION_TARGET_MARKER_INVALID")
        source_ancestry = ancestry_by_path.get(source_path, ())
        target_ancestry = ancestry_by_path.get(target_path, ())
        if not source_ancestry or source_ancestry != target_ancestry:
            _fail("NOT_AVAILABLE", "SECTION_BOUNDARY_INTERVENES")
        used_targets.add(target_marker.marker_sha256)
        values: dict[str, object] = {
            "contract": "terms-section-marker-relation-group-596-1.v1",
            "source_page_index": source_node.page_index,
            "source_block_index": source_node.local_index,
            "source_structural_path": source_path,
            "source_marker_count": len(markers),
            "source_marker_structural_paths": tuple(
                marker.structural_path for marker in markers
            ),
            "source_marker_structural_path_sha256": tuple(
                marker.structural_path_sha256 for marker in markers
            ),
            "source_marker_evidence_sha256": tuple(
                marker.marker_sha256 for marker in markers
            ),
            "source_node_preimage_sha256": source_node.node_preimage_sha256,
            "target_page_index": target_node.page_index,
            "target_block_index": target_node.local_index,
            "target_structural_path": target_path,
            "target_marker_evidence_sha256": target_marker.marker_sha256,
            "target_node_preimage_sha256": target_node.node_preimage_sha256,
            "section_ancestor_node_sha256": source_ancestry,
        }
        relations.append(
            TermsSectionMarkerRelationGroupV1.model_validate(
                {
                    **values,
                    "relation_digest_sha256": canonical_hash(
                        "terms-section-marker-relation-group-596-1.v1", values
                    ),
                }
            )
        )
    all_targets = {
        marker.marker_sha256 for rows in targets.values() for marker in rows
    }
    if used_targets != all_targets:
        _fail("BLOCKED", "SECTION_TARGET_MARKER_INVALID")
    return tuple(relations)


class NativeNodePreimageV1(_FrozenModel):
    contract: Literal["mineru-native-section-node.v1"]
    source_sha256: Sha256Hex
    native_member_sha256: Sha256Hex
    page_index: NonNegativeInt
    local_index: NonNegativeInt
    structural_path_sha256: Sha256Hex
    node_type: StrictStr = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    text_level: PositiveInt | None
    node_class: Literal["ANCHOR", "CONTENT", "EXCLUDED"]


class ReadingOrderIntervalV1(_FrozenModel):
    contract: Literal["mineru-native-section-reading-order.v1"]
    source_node_sha256: Sha256Hex
    target_node_sha256: Sha256Hex
    ordered_node_sha256: tuple[Sha256Hex, ...] = Field(min_length=2)
    page_delta: Literal[1]
    target_is_next_page_first_content: Literal[True]
    no_new_section_boundary: Literal[True]
    interval_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_interval(self) -> Self:
        preimage = self.model_dump(mode="json", exclude={"interval_sha256"})
        if self.interval_sha256 != canonical_hash(self.contract, preimage):
            raise ValueError("section interval digest")
        return self


class SectionAnchorEvidenceV1(_FrozenModel):
    contract: Literal["mineru-native-section-anchor-evidence-596-1.v1"]
    status: Literal["SECTION_ANCHOR_EVIDENCE_VERIFIED"]
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
    marker_envelope_sha256: Sha256Hex
    marker_source_authority_sha256: Sha256Hex
    marker_evidence_sha256: Sha256Hex
    marker_page_index: NonNegativeInt
    marker_node_type: Literal["text"]
    marker_local_index: NonNegativeInt
    marker_structural_path_sha256: Sha256Hex
    parsed_document_sha256: Sha256Hex
    parse_manifest_sha256: Sha256Hex
    source_endpoint: SectionBlockEndpointV1
    target_endpoint: SectionBlockEndpointV1
    anchor_nodes: tuple[NativeNodePreimageV1, ...] = Field(min_length=1)
    anchor_node_sha256: tuple[Sha256Hex, ...] = Field(min_length=1)
    section_ancestry_sha256: Sha256Hex
    outline_anchor_sha256: Sha256Hex
    interval: ReadingOrderIntervalV1
    evidence_preimage_sha256: Sha256Hex
    evidence_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_evidence(self) -> Self:
        node_hashes = tuple(
            canonical_hash(node.contract, node.model_dump(mode="json"))
            for node in self.anchor_nodes
        )
        preimage = self.model_dump(
            mode="json",
            exclude={"evidence_preimage_sha256", "evidence_digest_sha256"},
        )
        if (
            node_hashes != self.anchor_node_sha256
            or self.section_ancestry_sha256
            != canonical_hash("terms-section-ancestry.v1", node_hashes)
            or self.outline_anchor_sha256
            != canonical_hash("terms-section-outline-anchor.v1", node_hashes)
            or self.evidence_preimage_sha256
            != canonical_hash(f"{self.contract}.preimage", preimage)
        ):
            raise ValueError("section anchor preimage")
        if self.evidence_digest_sha256 != canonical_hash(
            self.contract,
            self.model_dump(mode="json", exclude={"evidence_digest_sha256"}),
        ):
            raise ValueError("section anchor evidence digest")
        return self


class SectionAnchorAuthorityV1(_FrozenModel):
    contract: Literal["mineru-native-section-anchor-authority-596-1.v1"]
    evidence: SectionAnchorEvidenceV1
    authority_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_authority(self) -> Self:
        if self.authority_digest_sha256 != canonical_hash(
            self.contract, self.evidence.model_dump(mode="json")
        ):
            raise ValueError("section anchor authority digest")
        return self

    def replay_terms_section_authority(
        self, request: TermsSectionMarkerAuthorityRequestV1
    ) -> TermsSectionMarkerAuthorityEvidenceV1:
        try:
            request = TermsSectionMarkerAuthorityRequestV1.model_validate(request)
        except ValidationError:
            _fail("BLOCKED", "SECTION_AUTHORITY_REQUEST_INVALID")
        evidence = self.evidence
        expected = {
            "source_sha256": evidence.source_sha256,
            "parser_identity_sha256": evidence.parser_identity_sha256,
            "parser_config_sha256": evidence.parser_config_sha256,
            "intake_bundle_digest_sha256": evidence.intake_bundle_digest_sha256,
            "intake_item_digest_sha256": evidence.intake_item_digest_sha256,
            "capture_identity_sha256": evidence.capture_identity_sha256,
            "raw_structure_sha256": evidence.raw_structure_sha256,
            "sanitized_structure_sha256": evidence.sanitized_structure_sha256,
            "raw_zip_sha256": evidence.raw_zip_sha256,
            "native_member_sha256": evidence.native_member_sha256,
            "member_inventory_sha256": evidence.member_inventory_sha256,
            "native_projection_sha256": evidence.native_projection_sha256,
            "native_observation_sha256": evidence.native_observation_sha256,
            "cross_page_facts_digest_sha256": evidence.cross_page_facts_digest_sha256,
            "marker_provenance_digest_sha256": evidence.marker_provenance_digest_sha256,
            "marker_provenance_replay_sha256": evidence.marker_provenance_replay_sha256,
            "marker_evidence_sha256": evidence.marker_evidence_sha256,
            "marker_page_index": evidence.marker_page_index,
            "marker_node_type": evidence.marker_node_type,
            "marker_local_index": evidence.marker_local_index,
            "marker_structural_path_sha256": evidence.marker_structural_path_sha256,
            "source_endpoint": evidence.source_endpoint,
            "target_endpoint": evidence.target_endpoint,
        }
        if any(getattr(request, key) != value for key, value in expected.items()):
            _fail("BLOCKED", "SECTION_AUTHORITY_REQUEST_DRIFT")
        values: dict[str, object] = {
            "contract": "terms-section-marker-authority-evidence.v1",
            "authority_contract": "marker-authority-envelope.v1",
            "authority_version_sha256": self.authority_digest_sha256,
            "request_digest_sha256": request.request_digest_sha256,
            "marker_kind": "cross_page",
            "relation_kind": "section",
            "source_endpoint_id": request.source_endpoint.endpoint_id,
            "source_page_number": request.source_endpoint.page_number,
            "source_endpoint_path_sha256": request.source_endpoint.locator_digest_sha256,
            "target_endpoint_id": request.target_endpoint.endpoint_id,
            "target_page_number": request.target_endpoint.page_number,
            "target_endpoint_path_sha256": request.target_endpoint.locator_digest_sha256,
            "source_section_ancestry_node_hashes": evidence.anchor_node_sha256,
            "target_section_ancestry_node_hashes": evidence.anchor_node_sha256,
            "section_ancestry_sha256": evidence.section_ancestry_sha256,
            "source_outline_anchor_node_hashes": evidence.anchor_node_sha256,
            "target_outline_anchor_node_hashes": evidence.anchor_node_sha256,
            "outline_anchor_sha256": evidence.outline_anchor_sha256,
            "target_starts_new_heading": False,
        }
        authority_preimage = {
            key: values[key]
            for key in (
                "authority_contract",
                "authority_version_sha256",
                "request_digest_sha256",
                "marker_kind",
                "relation_kind",
                "source_endpoint_id",
                "source_page_number",
                "source_endpoint_path_sha256",
                "target_endpoint_id",
                "target_page_number",
                "target_endpoint_path_sha256",
                "source_section_ancestry_node_hashes",
                "target_section_ancestry_node_hashes",
                "source_outline_anchor_node_hashes",
                "target_outline_anchor_node_hashes",
                "target_starts_new_heading",
            )
        }
        values["authority_preimage_sha256"] = canonical_hash(
            "terms-section-marker-authority-preimage.v1", authority_preimage
        )
        return TermsSectionMarkerAuthorityEvidenceV1.model_validate(
            {
                **values,
                "evidence_digest_sha256": canonical_hash(
                    "terms-section-marker-authority-evidence.v1", values
                ),
            }
        )


class TermsSectionAnchorRelationV1(_FrozenModel):
    """One recomputable section continuation derived from native MinerU structure."""

    contract: Literal["terms-section-anchor-relation-596-1.v1"]
    marker_group: TermsSectionMarkerRelationGroupV1
    source_endpoint: SectionBlockEndpointV1
    target_endpoint: SectionBlockEndpointV1
    relation_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_relation(self) -> Self:
        group = self.marker_group
        if (
            self.source_endpoint.page_number != group.source_page_index + 1
            or self.source_endpoint.block_index != group.source_block_index
            or self.target_endpoint.page_number != group.target_page_index + 1
            or self.target_endpoint.block_index != group.target_block_index
            or self.target_endpoint.order_index <= self.source_endpoint.order_index
        ):
            raise ValueError("section anchor endpoint mapping invalid")
        expected = canonical_hash(
            self.contract,
            self.model_dump(mode="json", exclude={"relation_digest_sha256"}),
        )
        if self.relation_digest_sha256 != expected:
            raise ValueError("section anchor relation digest invalid")
        return self


class TermsSectionAnchorAuthorityCollectionV1(_FrozenModel):
    """Ordered 0..N-capable authority; a concrete admitted artifact must contain >=1."""

    contract: Literal["terms-section-anchor-authority-collection-596-1.v1"]
    status: Literal["SECTION_ANCHOR_RELATIONS_VERIFIED"]
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
    cross_page_facts_digest_sha256: Sha256Hex
    marker_provenance_digest_sha256: Sha256Hex
    marker_provenance_replay_sha256: Sha256Hex
    marker_envelope_sha256: Sha256Hex
    marker_source_authority_sha256: Sha256Hex
    parsed_document_sha256: Sha256Hex
    parse_manifest_sha256: Sha256Hex
    relations: tuple[TermsSectionAnchorRelationV1, ...] = Field(min_length=1)
    authority_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_collection(self) -> Self:
        order = tuple(
            (
                row.marker_group.source_page_index,
                row.marker_group.source_block_index,
                row.marker_group.target_page_index,
                row.marker_group.target_block_index,
            )
            for row in self.relations
        )
        if order != tuple(sorted(order)) or len(set(order)) != len(order):
            raise ValueError("section anchor relation order invalid")
        expected = canonical_hash(
            self.contract,
            self.model_dump(mode="json", exclude={"authority_digest_sha256"}),
        )
        if self.authority_digest_sha256 != expected:
            raise ValueError("section anchor authority collection digest invalid")
        return self


class _NativeNode:
    def __init__(self, *, page: int, index: int, node_type: str, level: int | None) -> None:
        self.page = page
        self.index = index
        self.node_type = node_type
        self.level = level

    @property
    def path(self) -> str:
        return f"p{self.page}/b{self.index}"


def _path_hash(source: str, member: str, path: str) -> str:
    return hashlib.sha256(
        f"mineru-cross-page-marker-path.v1\0{source}\0{member}\0{path}".encode()
    ).hexdigest()


def _node_class(node_type: str, level: int | None) -> Literal["ANCHOR", "CONTENT", "EXCLUDED"]:
    if node_type in _EXCLUDED_TYPES:
        return "EXCLUDED"
    if node_type in _STRUCTURAL_TYPES or (node_type == "text" and level is not None):
        return "ANCHOR"
    if node_type in _CONTENT_TYPES:
        return "CONTENT"
    _fail("BLOCKED", "SECTION_NATIVE_NODE_TYPE_INVALID")


def _parse_native(item: Any) -> tuple[_NativeNode, ...]:
    provenance = item.evidence.cross_page_marker_provenance
    hierarchy = provenance.native_hierarchy_provenance if provenance is not None else None
    if hierarchy is None or hierarchy.status != "NATIVE_HIERARCHY_PROVENANCE_CAPTURED":
        _fail("NOT_AVAILABLE", "SECTION_ANCHOR_NOT_AVAILABLE")
    nodes = tuple(
        _NativeNode(
            page=node.page_index,
            index=node.local_index,
            node_type=node.node_type,
            level=node.text_level,
        )
        for node in hierarchy.nodes
    )
    if not nodes:
        _fail("NOT_AVAILABLE", "SECTION_ANCHOR_NOT_AVAILABLE")
    return nodes


def _native_preimage(node: _NativeNode, source: str, member: str) -> NativeNodePreimageV1:
    return NativeNodePreimageV1(
        contract="mineru-native-section-node.v1",
        source_sha256=source,
        native_member_sha256=member,
        page_index=node.page,
        local_index=node.index,
        structural_path_sha256=_path_hash(source, member, node.path),
        node_type=node.node_type,
        text_level=node.level,
        node_class=_node_class(node.node_type, node.level),
    )


def _endpoint(block: ParseBlockV1) -> SectionBlockEndpointV1:
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


def _marker_source(
    envelope: MarkerAuthorityEnvelopeV1,
) -> tuple[MarkerSourceAuthorityV1, MarkerAuthorityV1]:
    sources = tuple(source for source in envelope.marker_sources if source.role == "terms")
    if len(sources) != 1:
        _fail("BLOCKED", "SECTION_MARKER_AUTHORITY_INVALID")
    source = sources[0]
    if any(marker.marker_kind == "lines_deleted" for marker in source.markers):
        _fail("BLOCKED", "LINES_DELETED_NOT_SECTION_AUTHORITY")
    markers = tuple(marker for marker in source.markers if marker.marker_kind == "cross_page")
    if len(markers) != 1 or markers[0].node_type != "text":
        _fail("BLOCKED", "SECTION_MARKER_AUTHORITY_INVALID")
    return source, markers[0]


def _replay_document_manifest(
    item: Any, document: ParsedDocumentV1, manifest: ParseManifestV1
) -> tuple[ParsedDocumentV1, ParseManifestV1]:
    try:
        doc = ParsedDocumentV1.model_validate(document)
        man = ParseManifestV1.model_validate(manifest)
    except ValidationError:
        _fail("BLOCKED", "SECTION_CANONICAL_REPLAY_INVALID")
    inventories = (
        tuple(page.page_id for page in doc.pages),
        tuple(block.block_id for block in doc.blocks),
        tuple(table.table_id for table in doc.tables),
        tuple(cell.cell_id for cell in doc.cells),
    )
    if (
        doc.subject.source_sha256 != item.source_sha256
        or doc.subject.raw_artifact_hash != item.evidence.raw_structure_sha256
        or doc.parser.parser_id != "mineru-cloud-pipeline"
        or doc.parser.parser_config_hash != item.evidence.parser.config_sha256
        or (doc.attempt.attempt_number, doc.attempt.attempt_role, doc.attempt.generation)
        != (2, "bounded_upgrade", 0)
        or not doc.snapshot.pagination_complete
        or man.subject != doc.subject
        or man.parser != doc.parser
        or man.attempt != doc.attempt
        or man.snapshot != doc.snapshot
        or man.output_facts != doc.output_facts
        or man.document_hash != doc.document_hash
        or (
            man.ordered_page_ids,
            man.ordered_block_ids,
            man.ordered_table_ids,
            man.ordered_cell_ids,
        )
        != inventories
        or man.element_counts.model_dump()
        != {
            "pages": len(doc.pages),
            "blocks": len(doc.blocks),
            "tables": len(doc.tables),
            "cells": len(doc.cells),
        }
        or man.capability_evidence != doc.capability_evidence
        or man.warnings != doc.warnings
        or man.unsupported != doc.unsupported
        or any(
            (
                facts.body_text_included,
                facts.secrets_included,
                facts.absolute_paths_included,
                facts.unknown_vendor_fields_included,
            )
            != (False, False, False, False)
            for facts in (doc.output_facts, man.output_facts)
        )
    ):
        _fail("BLOCKED", "SECTION_CANONICAL_REPLAY_INVALID")
    return doc, man


def derive_section_anchor_authority_collection_596_1(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    marker_envelope: MarkerAuthorityEnvelopeV1,
    *,
    source_role: Literal["terms", "brochure"] = "terms",
) -> TermsSectionAnchorAuthorityCollectionV1:
    """Derive every native section continuation without collapsing nested markers."""

    try:
        intake = _replay_intake(bundle, preserve_marker_envelope=True)
        envelope = MarkerAuthorityEnvelopeV1.model_validate(marker_envelope)
        source_index = 0 if source_role == "terms" else 1
        item = intake.sources[source_index]
        doc, parsed_manifest = _replay_document_manifest(item, document, manifest)
    except (SectionAnchorEvidenceError, ValidationError, TypeError, ValueError):
        _fail("BLOCKED", "SECTION_INPUT_REPLAY_FAILED")
    if (
        item.role != source_role
        or envelope.bundle_digest_sha256 != intake.bundle_digest_sha256
        or envelope.envelope_sha256 != recompute_marker_authority_envelope_sha256(envelope)
    ):
        _fail("BLOCKED", "SECTION_CUSTODY_IDENTITY_DRIFT")
    marker_sources = tuple(
        source for source in envelope.marker_sources if source.role == source_role
    )
    facts = item.evidence.cross_page_facts
    provenance = item.evidence.cross_page_marker_provenance
    if (
        len(marker_sources) != 1
        or facts is None
        or provenance is None
        or facts.native_member_sha256 is None
        or item.cross_page_facts_digest_sha256 is None
        or item.marker_provenance_digest_sha256 is None
    ):
        _fail("BLOCKED", "SECTION_MARKER_AUTHORITY_INVALID")
    marker_source = marker_sources[0]
    if (
        marker_source.source_sha256 != item.source_sha256
        or marker_source.capture_identity_sha256 != item.capture_identity_sha256
        or marker_source.intake_custody.sha256 != item.intake_digest_sha256
        or marker_source.raw_zip.sha256 != facts.raw_zip_sha256
        or marker_source.native_member.sha256 != facts.native_member_sha256
        or marker_source.marker_replay_digest_sha256 != provenance.replay_digest_sha256
        or marker_source.marker_provenance_custody.sha256
        != item.marker_provenance_digest_sha256
        or marker_source.cross_page_facts_custody.sha256
        != item.cross_page_facts_digest_sha256
        or tuple(marker.marker_sha256 for marker in marker_source.markers)
        != tuple(marker.marker_sha256 for marker in provenance.markers)
        or facts.status != "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS"
        or facts.required_capability != "cross_page_sections"
        or facts.relation_count != 0
        or facts.relations
        or facts.ambiguous_marker_count != provenance.marker_count
        or set(facts.ambiguous_observation_hashes)
        != {
            hashlib.sha256(
                (
                    "mineru-cross-page-ambiguous.v1\0"
                    f"{item.source_sha256}\0{marker.marker_kind}\0"
                    f"{marker.structural_path}"
                ).encode()
            ).hexdigest()
            for marker in provenance.markers
        }
    ):
        _fail("BLOCKED", "SECTION_CUSTODY_IDENTITY_DRIFT")

    groups = group_terms_cross_page_markers_596_1(provenance)
    relations: list[TermsSectionAnchorRelationV1] = []
    for group in groups:
        source_rows = tuple(
            block
            for block in doc.blocks
            if block.locator.page_number == group.source_page_index + 1
            and block.locator.block_index == group.source_block_index
        )
        target_rows = tuple(
            block
            for block in doc.blocks
            if block.locator.page_number == group.target_page_index + 1
            and block.locator.block_index == group.target_block_index
        )
        if len(source_rows) != 1 or len(target_rows) != 1:
            _fail("BLOCKED", "SECTION_CANONICAL_ENDPOINT_INVALID")
        relation_values: dict[str, object] = {
            "contract": "terms-section-anchor-relation-596-1.v1",
            "marker_group": group.model_dump(mode="json"),
            "source_endpoint": _endpoint(source_rows[0]).model_dump(mode="json"),
            "target_endpoint": _endpoint(target_rows[0]).model_dump(mode="json"),
        }
        relations.append(
            TermsSectionAnchorRelationV1.model_validate(
                {
                    **relation_values,
                    "relation_digest_sha256": canonical_hash(
                        "terms-section-anchor-relation-596-1.v1", relation_values
                    ),
                }
            )
        )

    parser_identity = canonical_hash(
        "parser-identity.v1", doc.parser.model_dump(mode="python")
    )
    collection_values: dict[str, object] = {
        "contract": "terms-section-anchor-authority-collection-596-1.v1",
        "status": "SECTION_ANCHOR_RELATIONS_VERIFIED",
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
        "cross_page_facts_digest_sha256": item.cross_page_facts_digest_sha256,
        "marker_provenance_digest_sha256": item.marker_provenance_digest_sha256,
        "marker_provenance_replay_sha256": provenance.replay_digest_sha256,
        "marker_envelope_sha256": envelope.envelope_sha256,
        "marker_source_authority_sha256": marker_source.source_authority_sha256,
        "parsed_document_sha256": doc.document_hash,
        "parse_manifest_sha256": parsed_manifest.manifest_hash,
        "relations": tuple(row.model_dump(mode="json") for row in relations),
    }
    try:
        return TermsSectionAnchorAuthorityCollectionV1.model_validate(
            {
                **collection_values,
                "authority_digest_sha256": canonical_hash(
                    "terms-section-anchor-authority-collection-596-1.v1",
                    collection_values,
                ),
            }
        )
    except (TypeError, ValidationError, ValueError):
        _fail("BLOCKED", "SECTION_AUTHORITY_COLLECTION_INVALID")


def derive_section_anchor_authority_596_1(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    marker_envelope: MarkerAuthorityEnvelopeV1,
) -> SectionAnchorAuthorityV1:
    """Derive one privacy-safe structural anchor authority for 103."""

    try:
        intake = _replay_intake(bundle, preserve_marker_envelope=True)
        envelope = MarkerAuthorityEnvelopeV1.model_validate(marker_envelope)
        doc, parsed_manifest = _replay_document_manifest(intake.sources[0], document, manifest)
    except (SectionAnchorEvidenceError, ValidationError, TypeError, ValueError):
        _fail("BLOCKED", "SECTION_INPUT_REPLAY_FAILED")
    item = intake.sources[0]
    if (
        item.role != "terms"
        or envelope.bundle_digest_sha256 != intake.bundle_digest_sha256
        or envelope.envelope_sha256 != recompute_marker_authority_envelope_sha256(envelope)
    ):
        _fail("BLOCKED", "SECTION_CUSTODY_IDENTITY_DRIFT")
    marker_source, marker = _marker_source(envelope)
    facts = item.evidence.cross_page_facts
    provenance = item.evidence.cross_page_marker_provenance
    if (
        facts is None
        or provenance is None
        or facts.native_member_sha256 is None
        or item.cross_page_facts_digest_sha256 is None
        or item.marker_provenance_digest_sha256 is None
        or marker_source.source_sha256 != item.source_sha256
        or marker_source.capture_identity_sha256 != item.capture_identity_sha256
        or marker_source.intake_custody.sha256 != item.intake_digest_sha256
        or marker_source.raw_zip.sha256 != facts.raw_zip_sha256
        or marker_source.native_member.sha256 != facts.native_member_sha256
        or marker_source.marker_replay_digest_sha256 != provenance.replay_digest_sha256
        or facts.status != "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS"
        or facts.required_capability != "cross_page_sections"
        or facts.relation_count != 0
        or facts.ambiguous_marker_count != 1
        or len(facts.ambiguous_observation_hashes) != 1
    ):
        _fail("BLOCKED", "SECTION_CUSTODY_IDENTITY_DRIFT")
    nodes = _parse_native(item)
    source_native = tuple(
        node
        for node in nodes
        if node.page == marker.page_index and node.index == marker.local_index
    )
    if (
        len(source_native) != 1
        or marker.structural_path_preimage.structural_path != source_native[0].path
    ):
        _fail("BLOCKED", "SECTION_MARKER_NODE_DRIFT")
    source_native_node = source_native[0]
    if _node_class(source_native_node.node_type, source_native_node.level) != "CONTENT":
        _fail("BLOCKED", "SECTION_MARKER_NODE_INVALID")
    next_page = source_native_node.page + 1
    next_page_nodes = tuple(node for node in nodes if node.page == next_page)
    if not next_page_nodes:
        _fail("NOT_AVAILABLE", "SECTION_TARGET_NOT_AVAILABLE")
    target_candidates = tuple(
        node for node in next_page_nodes if _node_class(node.node_type, node.level) == "CONTENT"
    )
    if not target_candidates:
        _fail("NOT_AVAILABLE", "SECTION_TARGET_NOT_AVAILABLE")
    target_native_node = target_candidates[0]
    source_blocks = tuple(
        block
        for block in doc.blocks
        if block.locator.page_number == source_native_node.page + 1
        and block.locator.block_index == source_native_node.index
    )
    target_blocks = tuple(
        block
        for block in doc.blocks
        if block.locator.page_number == target_native_node.page + 1
        and block.locator.block_index == target_native_node.index
    )
    if len(source_blocks) != 1 or len(target_blocks) != 1:
        _fail("BLOCKED", "SECTION_CANONICAL_ENDPOINT_INVALID")
    source_block, target_block = source_blocks[0], target_blocks[0]
    if target_block.order_index <= source_block.order_index:
        _fail("BLOCKED", "SECTION_CANONICAL_READING_ORDER_INVALID")
    stack: list[_NativeNode] = []
    source_stack: tuple[_NativeNode, ...] | None = None
    target_stack: tuple[_NativeNode, ...] | None = None
    interval_nodes: list[_NativeNode] = []
    started = False
    for node in nodes:
        node_class = _node_class(node.node_type, node.level)
        if node_class == "ANCHOR":
            level = node.level or 1
            stack = [existing for existing in stack if (existing.level or 1) < level]
            stack.append(node)
        if node.page == source_native_node.page and node.index == source_native_node.index:
            source_stack = tuple(stack)
            started = True
        if started:
            interval_nodes.append(node)
        if node.page == target_native_node.page and node.index == target_native_node.index:
            target_stack = tuple(stack)
            break
    if not source_stack:
        _fail("NOT_AVAILABLE", "SECTION_ANCHOR_NOT_AVAILABLE")
    if target_stack is None:
        _fail("BLOCKED", "SECTION_NATIVE_READING_ORDER_INVALID")
    if source_stack != target_stack:
        _fail("NOT_AVAILABLE", "SECTION_BOUNDARY_INTERVENES")
    if any(_node_class(node.node_type, node.level) == "ANCHOR" for node in interval_nodes[1:]):
        _fail("NOT_AVAILABLE", "SECTION_BOUNDARY_INTERVENES")
    member = facts.native_member_sha256
    anchor_preimages = tuple(
        _native_preimage(node, item.source_sha256, member) for node in source_stack
    )
    anchor_hashes = tuple(
        canonical_hash(node.contract, node.model_dump(mode="json")) for node in anchor_preimages
    )
    interval_hashes = tuple(
        canonical_hash(
            "mineru-native-section-reading-node.v1",
            _native_preimage(node, item.source_sha256, member).model_dump(mode="json"),
        )
        for node in interval_nodes
    )
    interval_values: dict[str, object] = {
        "contract": "mineru-native-section-reading-order.v1",
        "source_node_sha256": interval_hashes[0],
        "target_node_sha256": interval_hashes[-1],
        "ordered_node_sha256": interval_hashes,
        "page_delta": 1,
        "target_is_next_page_first_content": True,
        "no_new_section_boundary": True,
    }
    interval = ReadingOrderIntervalV1.model_validate(
        {
            **interval_values,
            "interval_sha256": canonical_hash(
                "mineru-native-section-reading-order.v1", interval_values
            ),
        }
    )
    parser_identity = canonical_hash("parser-identity.v1", doc.parser.model_dump(mode="python"))
    values: dict[str, object] = {
        "contract": _CONTRACT,
        "status": "SECTION_ANCHOR_EVIDENCE_VERIFIED",
        "source_sha256": item.source_sha256,
        "parser_identity_sha256": parser_identity,
        "parser_config_sha256": item.evidence.parser.config_sha256,
        "intake_bundle_digest_sha256": intake.bundle_digest_sha256,
        "intake_item_digest_sha256": item.intake_digest_sha256,
        "capture_identity_sha256": item.capture_identity_sha256,
        "raw_structure_sha256": item.evidence.raw_structure_sha256,
        "sanitized_structure_sha256": item.evidence.sanitized_structure_sha256,
        "raw_zip_sha256": facts.raw_zip_sha256,
        "native_member_sha256": member,
        "member_inventory_sha256": facts.member_inventory_sha256,
        "native_projection_sha256": facts.projection_sha256,
        "native_observation_sha256": facts.ambiguous_observation_hashes[0],
        "cross_page_facts_digest_sha256": item.cross_page_facts_digest_sha256,
        "marker_provenance_digest_sha256": item.marker_provenance_digest_sha256,
        "marker_provenance_replay_sha256": provenance.replay_digest_sha256,
        "marker_envelope_sha256": envelope.envelope_sha256,
        "marker_source_authority_sha256": marker_source.source_authority_sha256,
        "marker_evidence_sha256": marker.marker_sha256,
        "marker_page_index": marker.page_index,
        "marker_node_type": "text",
        "marker_local_index": marker.local_index,
        "marker_structural_path_sha256": marker.structural_path_sha256,
        "parsed_document_sha256": doc.document_hash,
        "parse_manifest_sha256": parsed_manifest.manifest_hash,
        "source_endpoint": _endpoint(source_block),
        "target_endpoint": _endpoint(target_block),
        "anchor_nodes": anchor_preimages,
        "anchor_node_sha256": anchor_hashes,
        "section_ancestry_sha256": canonical_hash("terms-section-ancestry.v1", anchor_hashes),
        "outline_anchor_sha256": canonical_hash("terms-section-outline-anchor.v1", anchor_hashes),
        "interval": interval,
    }
    draft = SectionAnchorEvidenceV1.model_construct(
        **values,  # type: ignore[arg-type]
        evidence_preimage_sha256="0" * 64,
        evidence_digest_sha256="0" * 64,
    )
    preimage = draft.model_dump(
        mode="json", exclude={"evidence_preimage_sha256", "evidence_digest_sha256"}
    )
    values["evidence_preimage_sha256"] = canonical_hash(f"{_CONTRACT}.preimage", preimage)
    draft = SectionAnchorEvidenceV1.model_construct(
        **values,  # type: ignore[arg-type]
        evidence_digest_sha256="0" * 64,
    )
    digest_preimage = draft.model_dump(mode="json", exclude={"evidence_digest_sha256"})
    evidence = SectionAnchorEvidenceV1.model_validate(
        {
            **values,
            "evidence_digest_sha256": canonical_hash(_CONTRACT, digest_preimage),
        }
    )
    authority_values = {
        "contract": "mineru-native-section-anchor-authority-596-1.v1",
        "evidence": evidence.model_dump(mode="python"),
    }
    return SectionAnchorAuthorityV1.model_validate(
        {
            **authority_values,
            "authority_digest_sha256": canonical_hash(
                "mineru-native-section-anchor-authority-596-1.v1",
                evidence.model_dump(mode="json"),
            ),
        }
    )


__all__ = [
    "SectionAnchorAuthorityV1",
    "SectionAnchorEvidenceError",
    "SectionAnchorEvidenceV1",
    "TermsSectionAnchorAuthorityCollectionV1",
    "TermsSectionAnchorRelationV1",
    "TermsSectionMarkerRelationGroupV1",
    "derive_section_anchor_authority_596_1",
    "derive_section_anchor_authority_collection_596_1",
    "group_terms_cross_page_markers_596_1",
]
