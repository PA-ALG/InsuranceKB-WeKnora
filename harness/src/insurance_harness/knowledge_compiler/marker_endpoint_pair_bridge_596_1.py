"""Task-local 091 marker to 086 endpoint-pair replay input bridge."""

from __future__ import annotations

import hashlib
import json
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
    ParseCellV1,
    ParsedDocumentV1,
    ParseManifestV1,
    ParseTableV1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    CaptureIntakeError,
    MinerUCaptureBundle5961V1,
    MinerUCaptureEvidenceV2,
    NativeCrossPageMarkerEvidenceV1,
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    POLICY_SHA256,
    CrossPageBindingError,
    CrossPageMarkerReplayRequestV1,
    CrossPageTypedMarkerEvidenceV1,
    replay_cross_page_relation_binding_v1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    _validate_document_manifest as _validate_086_document_manifest,
)
from insurance_harness.knowledge_compiler.relation_bound_admission_596_1 import (
    TypedMarkerEndpointMapV1,
    TypedMarkerNodeV1,
)
from insurance_harness.knowledge_compiler.relation_receipt_bridge_596_1 import (
    DerivedRelationReceipt5961V1,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


class MarkerEndpointPairBridgeError(ValueError):
    """Fixed-code failure that never includes captured or caller material."""

    def __init__(self, status: Literal["BLOCKED", "NOT_AVAILABLE"], reason_code: str) -> None:
        self.status = status
        self.reason_code = reason_code
        super().__init__(f"{status}:{reason_code}")

    def __repr__(self) -> str:
        return f"MarkerEndpointPairBridgeError({self.status!r}, {self.reason_code!r})"


def _fail(status: Literal["BLOCKED", "NOT_AVAILABLE"], reason_code: str) -> Never:
    raise MarkerEndpointPairBridgeError(status, reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class HeaderCellStructuralFactV1(_FrozenModel):
    column_index: NonNegativeInt
    row_span: PositiveInt
    column_span: PositiveInt
    content_hash: Sha256Hex
    structure_hash: Sha256Hex


class TableEndpointCandidateV1(_FrozenModel):
    endpoint_id: StrictStr = Field(min_length=1)
    page_number: PositiveInt
    table_index: NonNegativeInt
    row_count: PositiveInt
    column_count: PositiveInt
    content_hash: Sha256Hex
    structure_hash: Sha256Hex
    header: tuple[HeaderCellStructuralFactV1, ...]
    endpoint_fact_digest_sha256: Sha256Hex
    locator_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_table_facts(self) -> Self:
        occupied: list[int] = []
        for cell in self.header:
            occupied.extend(range(cell.column_index, cell.column_index + cell.column_span))
        if (
            not self.header
            or sorted(occupied) != list(range(self.column_count))
            or len(occupied) != len(set(occupied))
        ):
            raise ValueError("incomplete header facts")
        header = tuple(cell.model_dump(mode="python") for cell in self.header)
        facts = {
            "table_id": self.endpoint_id,
            "content_hash": self.content_hash,
            "structure_hash": self.structure_hash,
            "header": header,
        }
        locator = {
            "row_count": self.row_count,
            "column_count": self.column_count,
            "header": header,
        }
        if self.endpoint_fact_digest_sha256 != canonical_hash(
            "table-endpoint-facts.v1", facts
        ) or self.locator_digest_sha256 != canonical_hash("table-grid-shape.v1", locator):
            raise ValueError("table endpoint digest mismatch")
        return self


class MarkerEndpointPairInputV1(_FrozenModel):
    contract: Literal["marker-endpoint-pair-input-596-1.v1"]
    status: Literal["MARKER_ENDPOINT_PAIR_INPUT_VERIFIED"]
    relation_kind: Literal["table"]
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
    native_hierarchy_replay_sha256: Sha256Hex | None = None
    marker_kind: Literal["cross_page"]
    marker_page_index: NonNegativeInt
    marker_node_type: Literal["table"]
    marker_local_index: NonNegativeInt
    marker_structural_path: StrictStr = Field(min_length=1, repr=False)
    marker_structural_path_sha256_091: Sha256Hex
    marker_path_sha256_086: Sha256Hex
    marker_evidence_sha256: Sha256Hex
    source_endpoint: TableEndpointCandidateV1
    target_endpoint: TableEndpointCandidateV1
    structural_rule_sha256: Sha256Hex
    policy_sha256: Sha256Hex
    replay_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _closed_pair(self) -> Self:
        if (
            self.policy_sha256 != POLICY_SHA256
            or self.target_endpoint.page_number != self.source_endpoint.page_number + 1
            or self.source_endpoint.column_count != self.target_endpoint.column_count
            or self.source_endpoint.header != self.target_endpoint.header
            or self.marker_page_index + 1 != self.source_endpoint.page_number
            or self.marker_local_index != self.source_endpoint.table_index
        ):
            raise ValueError("endpoint pair policy mismatch")
        if self.marker_path_sha256_086 != canonical_hash(
            "mineru-native-structural-path.v1", self.marker_structural_path
        ):
            raise ValueError("086 marker path mismatch")
        marker = {
            "marker_kind": self.marker_kind,
            "page_index": self.marker_page_index,
            "structural_path": self.marker_structural_path,
            "structural_path_sha256": self.marker_structural_path_sha256_091,
            "node_type": self.marker_node_type,
            "local_index": self.marker_local_index,
            "marker_sha256": self.marker_evidence_sha256,
        }
        marker_preimage = {
            "contract": "mineru-native-cross-page-marker-provenance.v1",
            "source_sha256": self.source_sha256,
            "parser_model": self.parser_model,
            "mineru_version": self.mineru_version,
            "native_member_sha256": self.native_member_sha256,
            "marker_kind": self.marker_kind,
            "page_index": self.marker_page_index,
            "structural_path_sha256": self.marker_structural_path_sha256_091,
            "node_type": self.marker_node_type,
            "local_index": self.marker_local_index,
        }
        provenance = {
            "contract": "mineru-native-cross-page-marker-provenance.v1",
            "source_sha256": self.source_sha256,
            "parser_model": self.parser_model,
            "mineru_version": self.mineru_version,
            "raw_zip_sha256": self.raw_zip_sha256,
            "native_member_sha256": self.native_member_sha256,
            "marker_count": 1,
            "markers": [marker],
        }
        if self.native_hierarchy_replay_sha256 is not None:
            provenance["native_hierarchy_replay_sha256"] = (
                self.native_hierarchy_replay_sha256
            )
        if (
            self.marker_structural_path_sha256_091
            != _go_path_sha256(
                self.source_sha256,
                self.native_member_sha256,
                self.marker_structural_path,
            )
            or self.marker_evidence_sha256
            != _go_json_domain_sha256("mineru-cross-page-marker-evidence.v1", marker_preimage)
            or self.marker_provenance_replay_sha256
            != _go_json_domain_sha256(
                "mineru-cross-page-marker-provenance-replay.v1", provenance
            )
            or self.marker_provenance_digest_sha256
            != canonical_hash(
                "mineru-cross-page-marker-provenance-custody.v1",
                {
                    **provenance,
                    "replay_digest_sha256": self.marker_provenance_replay_sha256,
                },
            )
            or self.native_observation_sha256
            != _sha256(
                "mineru-cross-page-ambiguous.v1\0"
                f"{self.source_sha256}\0{self.marker_kind}\0{self.marker_structural_path}"
            )
        ):
            raise ValueError("091 marker custody mismatch")
        rule = {
            "relation_kind": self.relation_kind,
            "page_delta": 1,
            "column_count": "exact",
            "header_coverage": "complete-non-overlapping",
            "header_content_structure_span": "exact",
            "candidate_cardinality": 1,
            "source_endpoint": self.source_endpoint.model_dump(mode="python"),
            "target_endpoint": self.target_endpoint.model_dump(mode="python"),
        }
        if self.structural_rule_sha256 != canonical_hash(
            "marker-endpoint-pair-structural-rule.v1", rule
        ):
            raise ValueError("structural rule digest mismatch")
        expected = canonical_hash(
            "marker-endpoint-pair-input-596-1.v1",
            self.model_dump(mode="python", exclude={"replay_digest_sha256"}),
        )
        if self.replay_digest_sha256 != expected:
            raise ValueError("endpoint pair replay digest mismatch")
        return self

    def replay_typed_cross_page_marker(
        self,
        request: CrossPageMarkerReplayRequestV1,
    ) -> CrossPageTypedMarkerEvidenceV1 | None:
        expected = (
            request.source_sha256 == self.source_sha256
            and request.parser_model == self.parser_model
            and request.mineru_version == self.mineru_version
            and request.raw_zip_sha256 == self.raw_zip_sha256
            and request.native_member_sha256 == self.native_member_sha256
            and request.member_inventory_sha256 == self.member_inventory_sha256
            and request.native_projection_sha256 == self.native_projection_sha256
            and request.native_observation_sha256 == self.native_observation_sha256
            and request.cross_page_facts_digest_sha256 == self.cross_page_facts_digest_sha256
            and request.relation_kind == self.relation_kind
        )
        if not expected:
            return None
        values: dict[str, object] = {
            "contract": "cross-page-typed-marker-evidence.v1",
            "authority": "future-089-typed-marker-replay",
            "request_digest_sha256": request.request_digest_sha256,
            "marker_kind": self.marker_kind,
            "relation_kind": self.relation_kind,
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


def _go_path_sha256(source_sha256: str, native_member_sha256: str, path: str) -> str:
    return _sha256(
        f"mineru-cross-page-marker-path.v1\0{source_sha256}\0{native_member_sha256}\0{path}"
    )


def _go_json_domain_sha256(domain: str, value: object) -> str:
    return hashlib.sha256(
        domain.encode()
        + b"\0"
        + json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def _compact_capture(evidence: MinerUCaptureEvidenceV2) -> bytes:
    marker = "__OPEN_SPEC_098_EXACT_STRUCTURE_BYTES__"
    try:
        structure = json.loads(evidence.sanitized_structure)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        _fail("BLOCKED", "INTAKE_REPLAY_FAILED")
    payload: dict[str, object] = {
        "contract": evidence.contract,
        "source_sha256": evidence.source_sha256,
        "attempt": evidence.attempt.model_dump(mode="json"),
        "raw_structure_sha256": evidence.raw_structure_sha256,
        "sanitized_structure_sha256": evidence.sanitized_structure_sha256,
        "sanitized_structure": marker,
        "content_snapshot_sha256": evidence.content_snapshot_sha256,
        "content_snapshot": evidence.content_snapshot,
        "capture_identity_sha256": evidence.capture_identity_sha256,
        "parser": evidence.parser.model_dump(mode="json"),
        "calls": evidence.calls.model_dump(mode="json"),
        "latency_milliseconds": evidence.latency_milliseconds,
        "status": evidence.status,
    }
    if evidence.cross_page_facts is not None:
        payload["cross_page_facts"] = evidence.cross_page_facts.model_dump(
            mode="json", exclude_none=True
        )
    if evidence.cross_page_marker_provenance is not None:
        payload["cross_page_marker_provenance"] = evidence.cross_page_marker_provenance.model_dump(
            mode="json"
        )
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    placeholder = json.dumps(marker).encode()
    if encoded.count(placeholder) != 1 or not isinstance(structure, dict):
        _fail("BLOCKED", "INTAKE_REPLAY_FAILED")
    return encoded.replace(placeholder, evidence.sanitized_structure) + b"\n"


def _replay_intake(bundle: MinerUCaptureBundle5961V1) -> MinerUCaptureBundle5961V1:
    try:
        supplied = MinerUCaptureBundle5961V1.model_validate(bundle)
        replayed = intake_mineru_capture_bundle_596_1(
            tuple(_compact_capture(item.evidence) for item in supplied.sources)  # type: ignore[arg-type]
        )
    except (CaptureIntakeError, TypeError, ValidationError, ValueError):
        _fail("BLOCKED", "INTAKE_REPLAY_FAILED")
    if replayed != supplied:
        _fail("BLOCKED", "INTAKE_REPLAY_FAILED")
    return replayed


def _header(
    cells: dict[str, ParseCellV1], table: ParseTableV1
) -> tuple[HeaderCellStructuralFactV1, ...] | None:
    try:
        values = tuple(cells[cell_id] for cell_id in table.header_cell_ids)
    except KeyError:
        return None
    if not values or any(cell.locator.row_index != 0 for cell in values):
        return None
    result = tuple(
        HeaderCellStructuralFactV1(
            column_index=cell.locator.column_index,
            row_span=cell.locator.row_span,
            column_span=cell.locator.column_span,
            content_hash=cell.content_hash,
            structure_hash=cell.structure_hash,
        )
        for cell in sorted(values, key=lambda item: item.locator.column_index)
    )
    occupied = [
        column
        for cell in result
        for column in range(cell.column_index, cell.column_index + cell.column_span)
    ]
    if sorted(occupied) != list(range(table.column_count)) or len(occupied) != len(set(occupied)):
        return None
    return result


def _endpoint(
    table: ParseTableV1, header: tuple[HeaderCellStructuralFactV1, ...]
) -> TableEndpointCandidateV1:
    header_values = tuple(cell.model_dump(mode="python") for cell in header)
    return TableEndpointCandidateV1(
        endpoint_id=table.table_id,
        page_number=table.locator.page_number,
        table_index=table.locator.table_index,
        row_count=table.row_count,
        column_count=table.column_count,
        content_hash=table.content_hash,
        structure_hash=table.structure_hash,
        header=header,
        endpoint_fact_digest_sha256=canonical_hash(
            "table-endpoint-facts.v1",
            {
                "table_id": table.table_id,
                "content_hash": table.content_hash,
                "structure_hash": table.structure_hash,
                "header": header_values,
            },
        ),
        locator_digest_sha256=canonical_hash(
            "table-grid-shape.v1",
            {
                "row_count": table.row_count,
                "column_count": table.column_count,
                "header": header_values,
            },
        ),
    )


def _source_marker(
    markers: tuple[NativeCrossPageMarkerEvidenceV1, ...],
) -> NativeCrossPageMarkerEvidenceV1:
    if any(marker.marker_kind == "lines_deleted" for marker in markers):
        _fail("BLOCKED", "LINES_DELETED_NOT_RELATION_AUTHORITY")
    cross_page = tuple(marker for marker in markers if marker.marker_kind == "cross_page")
    if len(cross_page) != 1:
        _fail("BLOCKED", "CROSS_PAGE_SOURCE_MARKER_CARDINALITY_INVALID")
    marker = cross_page[0]
    if marker.node_type != "table":
        _fail("BLOCKED", "MARKER_NODE_TYPE_INVALID")
    return marker


def derive_marker_endpoint_pair_input_596_1(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    *,
    relation_kind: Literal["table", "section"] = "table",
) -> MarkerEndpointPairInputV1:
    """Build one replayable 086 input without issuing a relation or receipt."""

    if relation_kind == "section":
        _fail("NOT_AVAILABLE", "SECTION_ENDPOINT_RULE_NOT_AVAILABLE")
    try:
        intake = _replay_intake(bundle)
        doc = ParsedDocumentV1.model_validate(document)
        man = ParseManifestV1.model_validate(manifest)
        doc, man = _validate_086_document_manifest(
            intake.sources[2].evidence,
            doc,
            man,
            expected_source_sha256=intake.sources[2].source_sha256,
            relation_kind="table",
        )
    except (CrossPageBindingError, TypeError, ValidationError, ValueError):
        _fail("BLOCKED", "INPUT_SHAPE_INVALID")
    item = intake.sources[2]
    facts = item.evidence.cross_page_facts
    provenance = item.evidence.cross_page_marker_provenance
    if (
        item.role != "rate"
        or facts is None
        or provenance is None
        or item.cross_page_facts_digest_sha256 is None
        or item.marker_provenance_digest_sha256 is None
        or facts.status != "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS"
        or facts.required_capability != "cross_page_tables"
        or facts.relation_count != 0
        or facts.relations
        or provenance.marker_count != len(provenance.markers)
        or provenance.marker_count != facts.ambiguous_marker_count
        or provenance.source_sha256 != item.source_sha256
        or provenance.raw_zip_sha256 != facts.raw_zip_sha256
        or provenance.native_member_sha256 != facts.native_member_sha256
        or provenance.parser_model != facts.parser_model
        or provenance.mineru_version != facts.mineru_version
    ):
        _fail("BLOCKED", "MARKER_CUSTODY_INCOMPLETE")
    marker = _source_marker(provenance.markers)
    if facts.ambiguous_marker_count != 1 or len(facts.ambiguous_observation_hashes) != 1:
        _fail("BLOCKED", "MARKER_CUSTODY_INCOMPLETE")
    path = f"p{marker.page_index}/b{marker.local_index}"
    if marker.structural_path_sha256 != _go_path_sha256(
        item.source_sha256, provenance.native_member_sha256, path
    ):
        _fail("BLOCKED", "MARKER_STRUCTURAL_PATH_NOT_REPLAYABLE")
    hierarchy = provenance.native_hierarchy_provenance
    hierarchy_replay_sha256: str | None = None
    if hierarchy is not None:
        matching_nodes = tuple(
            node
            for node in hierarchy.nodes
            if (
                node.page_index == marker.page_index
                and node.local_index == marker.local_index
                and node.node_type == marker.node_type
                and node.structural_path == path
                and node.structural_path_sha256 == marker.structural_path_sha256
            )
        )
        if len(matching_nodes) != 1:
            _fail("BLOCKED", "MARKER_HIERARCHY_NODE_DRIFT")
        hierarchy_replay_sha256 = hierarchy.replay_digest_sha256
    cells = {cell.cell_id: cell for cell in doc.cells}
    pairs: list[
        tuple[
            ParseTableV1,
            tuple[HeaderCellStructuralFactV1, ...],
            ParseTableV1,
            tuple[HeaderCellStructuralFactV1, ...],
        ]
    ] = []
    for source in doc.tables:
        source_header = _header(cells, source)
        if source_header is None:
            continue
        for target in doc.tables:
            target_header = _header(cells, target)
            if (
                target.locator.page_number == source.locator.page_number + 1
                and target_header is not None
                and source.column_count == target.column_count
                and source_header == target_header
            ):
                pairs.append((source, source_header, target, target_header))
    if not pairs:
        _fail("NOT_AVAILABLE", "UNIQUE_TABLE_ENDPOINTS_NOT_AVAILABLE")
    if len(pairs) != 1:
        _fail("BLOCKED", "TABLE_ENDPOINTS_AMBIGUOUS")
    source, source_header, target, target_header = pairs[0]
    if (
        source.locator.page_number != marker.page_index + 1
        or source.locator.table_index != marker.local_index
    ):
        _fail("BLOCKED", "MARKER_SOURCE_ENDPOINT_DRIFT")
    source_endpoint = _endpoint(source, source_header)
    target_endpoint = _endpoint(target, target_header)
    parser_identity_sha256 = canonical_hash(
        "parser-identity.v1", doc.parser.model_dump(mode="python")
    )
    rule = {
        "relation_kind": "table",
        "page_delta": 1,
        "column_count": "exact",
        "header_coverage": "complete-non-overlapping",
        "header_content_structure_span": "exact",
        "candidate_cardinality": 1,
        "source_endpoint": source_endpoint.model_dump(mode="python"),
        "target_endpoint": target_endpoint.model_dump(mode="python"),
    }
    values = {
        "contract": "marker-endpoint-pair-input-596-1.v1",
        "status": "MARKER_ENDPOINT_PAIR_INPUT_VERIFIED",
        "relation_kind": "table",
        "source_sha256": item.source_sha256,
        "parser_model": provenance.parser_model,
        "mineru_version": provenance.mineru_version,
        "parser_identity_sha256": parser_identity_sha256,
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
        "native_hierarchy_replay_sha256": hierarchy_replay_sha256,
        "marker_kind": marker.marker_kind,
        "marker_page_index": marker.page_index,
        "marker_node_type": marker.node_type,
        "marker_local_index": marker.local_index,
        "marker_structural_path": path,
        "marker_structural_path_sha256_091": marker.structural_path_sha256,
        "marker_path_sha256_086": canonical_hash("mineru-native-structural-path.v1", path),
        "marker_evidence_sha256": marker.marker_sha256,
        "source_endpoint": source_endpoint.model_dump(mode="python"),
        "target_endpoint": target_endpoint.model_dump(mode="python"),
        "structural_rule_sha256": canonical_hash("marker-endpoint-pair-structural-rule.v1", rule),
        "policy_sha256": POLICY_SHA256,
    }
    values["replay_digest_sha256"] = canonical_hash("marker-endpoint-pair-input-596-1.v1", values)
    try:
        return MarkerEndpointPairInputV1.model_validate(values)
    except (TypeError, ValidationError, ValueError):
        _fail("BLOCKED", "ENDPOINT_PAIR_INPUT_INVALID")


def build_092_marker_endpoint_mappings_596_1(
    *,
    bundle: MinerUCaptureBundle5961V1,
    receipt: DerivedRelationReceipt5961V1,
) -> tuple[TypedMarkerEndpointMapV1, ...]:
    """Replay every receipt endpoint to its exact native hierarchy node."""

    try:
        checked_bundle = MinerUCaptureBundle5961V1.model_validate(bundle)
        checked_receipt = DerivedRelationReceipt5961V1.model_validate(receipt)
        if checked_receipt.intake_bundle_digest_sha256 != checked_bundle.bundle_digest_sha256:
            raise ValueError
        by_role = {
            "terms": checked_bundle.sources[0],
            "brochure": checked_bundle.sources[1],
            "rate_table": checked_bundle.sources[2],
        }
        mappings: list[TypedMarkerEndpointMapV1] = []
        for entry in checked_receipt.relations:
            item = by_role[entry.receipt_role]
            binding = replay_cross_page_relation_binding_v1(entry.binding)
            kind = binding.relation_kind
            if binding.source_sha256 != item.source_sha256:
                raise ValueError
            structure: dict[str, Any] = json.loads(
                item.evidence.sanitized_structure
            )
            row_name = "blocks" if kind == "section" else "tables"
            id_name = "block_id" if kind == "section" else "table_id"
            index_name = "block_index" if kind == "section" else "table_index"
            expected_type: Literal["text", "table"] = (
                "text" if kind == "section" else "table"
            )

            def node(
                endpoint: Any,
                *,
                structure: dict[str, Any] = structure,
                row_name: str = row_name,
                id_name: str = id_name,
                index_name: str = index_name,
                expected_type: Literal["text", "table"] = expected_type,
                item: Any = item,
            ) -> TypedMarkerNodeV1:
                endpoint_id = endpoint.endpoint_id
                rows = tuple(
                    row
                    for row in structure[row_name]
                    if row[id_name] == endpoint_id
                    and row["page_number"] == endpoint.page_number
                )
                if len(rows) != 1:
                    raise ValueError
                row = rows[0]
                provenance = item.evidence.cross_page_marker_provenance
                hierarchy = (
                    provenance.native_hierarchy_provenance
                    if provenance is not None
                    else None
                )
                if hierarchy is None:
                    raise ValueError
                if expected_type == "table":
                    page_tables = tuple(
                        sorted(
                            (
                                candidate
                                for candidate in hierarchy.nodes
                                if candidate.page_index == row["page_number"] - 1
                                and candidate.node_type == "table"
                            ),
                            key=lambda candidate: candidate.reading_order,
                        )
                    )
                    native = (
                        (page_tables[row[index_name]],)
                        if row[index_name] < len(page_tables)
                        else ()
                    )
                else:
                    native = tuple(
                        candidate
                        for candidate in hierarchy.nodes
                        if candidate.page_index == row["page_number"] - 1
                        and candidate.local_index == row[index_name]
                        and candidate.node_type == expected_type
                    )
                if len(native) != 1:
                    raise ValueError
                return TypedMarkerNodeV1(
                    page_index=native[0].page_index,
                    node_type=expected_type,
                    local_index=row[index_name],
                    structural_path_sha256=native[0].structural_path_sha256,
                )

            values = {
                "contract": "typed-marker-endpoint-map.v1",
                "source_sha256": item.source_sha256,
                "marker_kind": "cross_page",
                "relation_kind": kind,
                "source_node": node(binding.source_endpoint).model_dump(mode="python"),
                "target_node": node(binding.target_endpoint).model_dump(mode="python"),
            }
            mappings.append(
                TypedMarkerEndpointMapV1.model_validate(
                    {
                        **values,
                        "replay_digest_sha256": canonical_hash(
                            "typed-marker-endpoint-map.v1", values
                        ),
                    }
                )
            )
        if not mappings:
            raise ValueError
        return tuple(mappings)
    except (
        AttributeError,
        CrossPageBindingError,
        KeyError,
        TypeError,
        ValidationError,
        ValueError,
        json.JSONDecodeError,
    ):
        _fail("BLOCKED", "MARKER_ENDPOINT_MAPPING_INVALID")


__all__ = [
    "build_092_marker_endpoint_mappings_596_1",
    "MarkerEndpointPairBridgeError",
    "MarkerEndpointPairInputV1",
    "derive_marker_endpoint_pair_input_596_1",
]
