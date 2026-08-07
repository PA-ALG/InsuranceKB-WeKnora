"""Task-local 596-1 derived structural cross-page relation binding."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Any, Final, Literal, Never, Protocol, Self

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
    ParseTableV1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    CaptureIntakeError,
    MinerUCaptureBundle5961V1,
    MinerUCaptureEvidenceV2,
    intake_mineru_capture_bundle_596_1,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[StrictInt, Field(gt=0)]

_RATE_SHA: Final = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"
_POLICY: Final = {
    "contract": "mineru-derived-cross-page-policy.v1",
    "relation_kinds": ["section", "table"],
    "native_observation_count": 1,
    "typed_marker_authority": "future-089-typed-marker-replay",
    "marker_kind": "cross_page",
    "page_delta": 1,
    "column_count": "exact",
    "header_coverage": "complete-non-overlapping",
    "header_content_structure_span": "exact",
    "candidate_cardinality": 1,
    "section_endpoint_mapping": "typed-marker-exact-block-refs",
    "marker_absent_table_fallback": "unique-adjacent-two-leading-row-grid-signature",
    "text_semantics": "forbidden",
}
POLICY_SHA256: Final = canonical_hash("mineru-derived-cross-page-policy.v1", _POLICY)


class CrossPageBindingError(ValueError):
    """Fixed-code failure with no untrusted material in its representation."""

    def __init__(self, status: Literal["BLOCKED", "NOT_AVAILABLE"], reason_code: str) -> None:
        self.status = status
        self.reason_code = reason_code
        super().__init__(f"{status}:{reason_code}")

    def __repr__(self) -> str:
        return f"CrossPageBindingError({self.status!r}, {self.reason_code!r})"


def _fail(status: Literal["BLOCKED", "NOT_AVAILABLE"], reason: str) -> Never:
    raise CrossPageBindingError(status, reason)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class CrossPageEndpointV1(_FrozenModel):
    endpoint_kind: Literal["table", "block"]
    endpoint_id: StrictStr = Field(min_length=1)
    page_number: PositiveInt
    endpoint_fact_digest_sha256: Sha256Hex
    locator_digest_sha256: Sha256Hex


class CrossPageRelationBindingV1(_FrozenModel):
    contract: Literal["cross-page-relation-binding.v1"]
    status: Literal["DERIVED_STRUCTURAL_BINDING_VERIFIED"]
    provenance: Literal["DERIVED_STRUCTURAL_RELATION"] = "DERIVED_STRUCTURAL_RELATION"
    relation_kind: Literal["table", "section"]
    source_sha256: Sha256Hex
    parser_identity_sha256: Sha256Hex
    parser_config_sha256: Sha256Hex
    intake_bundle_digest_sha256: Sha256Hex
    intake_item_digest_sha256: Sha256Hex
    capture_identity_sha256: Sha256Hex
    raw_structure_sha256: Sha256Hex
    artifact_sha256: Sha256Hex
    cross_page_facts_digest_sha256: Sha256Hex
    parsed_document_hash: Sha256Hex
    parse_manifest_hash: Sha256Hex
    native_projection_sha256: Sha256Hex
    native_observation_sha256: Sha256Hex
    typed_marker_evidence_digest_sha256: Sha256Hex
    marker_path_sha256: Sha256Hex
    policy_sha256: Sha256Hex
    source_endpoint: CrossPageEndpointV1
    target_endpoint: CrossPageEndpointV1
    replay_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _ordered_distinct_endpoints(self) -> Self:
        if self.source_endpoint.endpoint_id == self.target_endpoint.endpoint_id:
            raise ValueError("derived endpoints must be distinct")
        expected_kind = "table" if self.relation_kind == "table" else "block"
        if (
            self.source_endpoint.endpoint_kind != expected_kind
            or self.target_endpoint.endpoint_kind != expected_kind
            or self.source_endpoint.page_number == self.target_endpoint.page_number
            or (
                self.relation_kind == "table"
                and self.target_endpoint.page_number != self.source_endpoint.page_number + 1
            )
        ):
            raise ValueError("derived endpoint kind or pages are invalid")
        return self


class CrossPageMarkerReplayRequestV1(_FrozenModel):
    contract: Literal["cross-page-marker-replay-request.v1"]
    source_sha256: Sha256Hex
    parser_model: Literal["pipeline"]
    mineru_version: Literal["3.4.4"]
    raw_zip_sha256: Sha256Hex
    native_member_sha256: Sha256Hex
    member_inventory_sha256: Sha256Hex
    native_projection_sha256: Sha256Hex
    native_observation_sha256: Sha256Hex
    cross_page_facts_digest_sha256: Sha256Hex
    relation_kind: Literal["table", "section"]
    request_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _replay_request_digest(self) -> Self:
        expected = canonical_hash(
            "cross-page-marker-replay-request.v1",
            self.model_dump(mode="python", exclude={"request_digest_sha256"}),
        )
        if self.request_digest_sha256 != expected:
            raise ValueError("marker replay request digest mismatch")
        return self


class CrossPageTypedMarkerEvidenceV1(_FrozenModel):
    contract: Literal["cross-page-typed-marker-evidence.v1"]
    authority: Literal["future-089-typed-marker-replay"]
    request_digest_sha256: Sha256Hex
    marker_kind: Literal["cross_page", "lines_deleted"]
    relation_kind: Literal["table", "section"]
    marker_structural_path: StrictStr = Field(min_length=1, repr=False, exclude=True)
    marker_path_sha256: Sha256Hex
    source_endpoint_id: StrictStr = Field(min_length=1)
    source_page_number: PositiveInt
    source_endpoint_path_sha256: Sha256Hex
    target_endpoint_id: StrictStr = Field(min_length=1)
    target_page_number: PositiveInt
    target_endpoint_path_sha256: Sha256Hex
    evidence_digest_sha256: Sha256Hex

    @model_validator(mode="after")
    def _replay_evidence_digest(self) -> Self:
        if (
            not self.marker_structural_path.startswith("p")
            or any(value in self.marker_structural_path for value in ("..", "\\", "//"))
            or self.marker_path_sha256
            != canonical_hash("mineru-native-structural-path.v1", self.marker_structural_path)
        ):
            raise ValueError("typed marker path is invalid")
        preimage = {
            "contract": self.contract,
            "authority": self.authority,
            "request_digest_sha256": self.request_digest_sha256,
            "marker_kind": self.marker_kind,
            "relation_kind": self.relation_kind,
            "marker_structural_path": self.marker_structural_path,
            "marker_path_sha256": self.marker_path_sha256,
            "source_endpoint_id": self.source_endpoint_id,
            "source_page_number": self.source_page_number,
            "source_endpoint_path_sha256": self.source_endpoint_path_sha256,
            "target_endpoint_id": self.target_endpoint_id,
            "target_page_number": self.target_page_number,
            "target_endpoint_path_sha256": self.target_endpoint_path_sha256,
        }
        if self.evidence_digest_sha256 != canonical_hash(
            "cross-page-typed-marker-evidence.v1", preimage
        ):
            raise ValueError("typed marker evidence digest mismatch")
        return self


class CrossPageTypedMarkerReplayProtocol(Protocol):
    def replay_typed_cross_page_marker(
        self,
        request: CrossPageMarkerReplayRequestV1,
    ) -> CrossPageTypedMarkerEvidenceV1 | None: ...


def _compact_capture(
    evidence: MinerUCaptureEvidenceV2,
    *,
    preserve_marker_envelope: bool = False,
) -> bytes:
    """Recreate a bytes payload while retaining the exact captured structure bytes."""

    marker = "__OPEN_SPEC_086_EXACT_STRUCTURE_BYTES__"
    try:
        structure: dict[str, Any] = json.loads(evidence.sanitized_structure)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        _fail("BLOCKED", "INTAKE_REPLAY_FAILED")
    payload: dict[str, Any] = {
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
    if preserve_marker_envelope and evidence.cross_page_marker_provenance is not None:
        payload["cross_page_marker_provenance"] = (
            evidence.cross_page_marker_provenance.model_dump(mode="json")
        )
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    placeholder = json.dumps(marker).encode()
    if encoded.count(placeholder) != 1 or not isinstance(structure, dict):
        _fail("BLOCKED", "INTAKE_REPLAY_FAILED")
    return encoded.replace(placeholder, evidence.sanitized_structure) + b"\n"


def _replay_intake(
    bundle: MinerUCaptureBundle5961V1,
    *,
    preserve_marker_envelope: bool = False,
) -> MinerUCaptureBundle5961V1:
    try:
        supplied = MinerUCaptureBundle5961V1.model_validate(bundle)
        replayed = intake_mineru_capture_bundle_596_1(
            tuple(  # type: ignore[arg-type]
                _compact_capture(
                    item.evidence,
                    preserve_marker_envelope=preserve_marker_envelope,
                )
                for item in supplied.sources
            )
        )
    except (ValidationError, CaptureIntakeError, TypeError, ValueError):
        _fail("BLOCKED", "INTAKE_REPLAY_FAILED")
    if replayed != supplied:
        _fail("BLOCKED", "INTAKE_REPLAY_FAILED")
    return replayed


def _bbox(values: tuple[Decimal, Decimal, Decimal, Decimal]) -> list[str]:
    return [str(value) for value in values]


def _structure_from_document(document: ParsedDocumentV1) -> dict[str, object]:
    return {
        "contract": "mineru-native-structure.v1",
        "source_schema": "mineru.content-list.pipeline.v1",
        "parser_model": "pipeline",
        "source_sha256": document.subject.source_sha256,
        "raw_sha256": document.subject.raw_artifact_hash,
        "pages": [
            {
                "page_id": item.page_id,
                "page_number": item.locator.page_number,
                "content_hash": item.content_hash,
                "structure_hash": item.structure_hash,
            }
            for item in document.pages
        ],
        "blocks": [
            {
                "block_id": item.block_id,
                "order_index": item.order_index,
                "page_number": item.locator.page_number,
                "block_index": item.locator.block_index,
                "bbox": _bbox(item.locator.bbox),
                "content_hash": item.content_hash,
                "structure_hash": item.structure_hash,
            }
            for item in document.blocks
        ],
        "tables": [
            {
                "table_id": item.table_id,
                "order_index": item.order_index,
                "page_number": item.locator.page_number,
                "table_index": item.locator.table_index,
                "bbox": _bbox(item.locator.bbox),
                "content_hash": item.content_hash,
                "structure_hash": item.structure_hash,
                "row_count": item.row_count,
                "column_count": item.column_count,
                "header_cell_ids": list(item.header_cell_ids),
            }
            for item in document.tables
        ],
        "cells": [
            {
                "cell_id": item.cell_id,
                "order_index": item.order_index,
                "table_id": item.table_id,
                "page_number": item.locator.page_number,
                "row_index": item.locator.row_index,
                "column_index": item.locator.column_index,
                "row_span": item.locator.row_span,
                "column_span": item.locator.column_span,
                "bbox": _bbox(item.locator.bbox),
                "content_hash": item.content_hash,
                "structure_hash": item.structure_hash,
            }
            for item in document.cells
        ],
        "unsupported": [item.capability for item in document.unsupported],
    }


def _validate_document_manifest(
    evidence: MinerUCaptureEvidenceV2,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    *,
    expected_source_sha256: str,
    relation_kind: Literal["table", "section"],
) -> tuple[ParsedDocumentV1, ParseManifestV1]:
    try:
        doc = ParsedDocumentV1.model_validate(document)
        man = ParseManifestV1.model_validate(manifest)
        structure = json.loads(evidence.sanitized_structure)
    except (ValidationError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
        _fail("BLOCKED", "STRUCTURAL_CUSTODY_INVALID")
    replayed_structure = _structure_from_document(doc)
    structure_for_replay: dict[str, Any] = dict(structure)
    replayed_for_compare: dict[str, Any] = dict(replayed_structure)
    if relation_kind == "table":
        candidates: list[tuple[ParseTableV1, ParseTableV1]] = []
        for source_table in doc.tables:
            source_signature = _leading_rows_signature(doc, source_table)
            if source_signature is None:
                continue
            for target_table in doc.tables:
                if (
                    target_table.locator.page_number
                    == source_table.locator.page_number + 1
                    and target_table.column_count == source_table.column_count
                    and _leading_rows_signature(doc, target_table) == source_signature
                ):
                    candidates.append((source_table, target_table))
        allowed_derived_headers = (
            {table.table_id for table in candidates[0]} if len(candidates) == 1 else set()
        )
        replayed_tables = {
            table["table_id"]: table for table in replayed_for_compare["tables"]
        }
        adjusted_tables: list[dict[str, object]] = []
        for table in structure_for_replay["tables"]:
            replayed_table = replayed_tables[table["table_id"]]
            if (
                table["table_id"] in allowed_derived_headers
                and not table["header_cell_ids"]
                and replayed_table["header_cell_ids"]
            ):
                table = {
                    **table,
                    "header_cell_ids": replayed_table["header_cell_ids"],
                }
            adjusted_tables.append(table)
        structure_for_replay["tables"] = adjusted_tables
    structure_for_replay["unsupported"] = sorted(structure_for_replay["unsupported"])
    replayed_for_compare["unsupported"] = sorted(replayed_for_compare["unsupported"])
    if (
        doc.subject.source_sha256 != expected_source_sha256
        or doc.subject.raw_artifact_hash != evidence.raw_structure_sha256
        or doc.parser.parser_id != "mineru-cloud-pipeline"
        or doc.parser.parser_config_hash != evidence.parser.config_sha256
        or doc.attempt.attempt_number != 2
        or doc.attempt.attempt_role != "bounded_upgrade"
        or doc.attempt.generation != 0
        or not doc.snapshot.pagination_complete
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
        or structure_for_replay != replayed_for_compare
    ):
        _fail("BLOCKED", "STRUCTURAL_CUSTODY_INVALID")
    expected_inventory = (
        tuple(item.page_id for item in doc.pages),
        tuple(item.block_id for item in doc.blocks),
        tuple(item.table_id for item in doc.tables),
        tuple(item.cell_id for item in doc.cells),
    )
    manifest_inventory = (
        man.ordered_page_ids,
        man.ordered_block_ids,
        man.ordered_table_ids,
        man.ordered_cell_ids,
    )
    if (
        man.subject != doc.subject
        or man.parser != doc.parser
        or man.attempt != doc.attempt
        or man.snapshot != doc.snapshot
        or man.document_hash != doc.document_hash
        or manifest_inventory != expected_inventory
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
    ):
        _fail("BLOCKED", "MANIFEST_REPLAY_FAILED")
    required = (
        {"table_grid", "cell_locators", "row_column_indices", "header_hierarchy"}
        if relation_kind == "table"
        else {"block_locators"}
    )
    cross_page_capability = (
        "cross_page_tables" if relation_kind == "table" else "cross_page_sections"
    )
    parser_unsupported = {item.capability for item in man.unsupported}
    if (
        not required <= set(man.satisfied_capabilities)
        or cross_page_capability not in parser_unsupported
    ):
        _fail("BLOCKED", "STRUCTURAL_CAPABILITY_INVALID")
    return doc, man


def _header_signature(
    document: ParsedDocumentV1,
    table: ParseTableV1,
) -> tuple[tuple[object, ...], ...] | None:
    cells = {item.cell_id: item for item in document.cells}
    headers = [cells[item] for item in table.header_cell_ids]
    if not headers or any(item.locator.row_index != 0 for item in headers):
        return None
    occupied: list[int] = []
    signature: list[tuple[object, ...]] = []
    for item in sorted(headers, key=lambda value: value.locator.column_index):
        locator = item.locator
        occupied.extend(range(locator.column_index, locator.column_index + locator.column_span))
        signature.append(
            (
                locator.column_index,
                locator.row_span,
                locator.column_span,
                item.content_hash,
                item.structure_hash,
            )
        )
    if sorted(occupied) != list(range(table.column_count)) or len(occupied) != len(set(occupied)):
        return None
    return tuple(signature)


def _leading_rows_signature(
    document: ParsedDocumentV1,
    table: ParseTableV1,
) -> tuple[tuple[object, ...], ...] | None:
    """Return an exact two-row grid signature without interpreting cell text."""

    if table.row_count < 2:
        return None
    cells = tuple(
        item
        for item in document.cells
        if item.table_id == table.table_id and item.locator.row_index < 2
    )
    occupied: set[tuple[int, int]] = set()
    signature: list[tuple[object, ...]] = []
    for item in sorted(
        cells,
        key=lambda value: (value.locator.row_index, value.locator.column_index),
    ):
        locator = item.locator
        for row_index in range(locator.row_index, min(2, locator.row_index + locator.row_span)):
            for column_index in range(
                locator.column_index, locator.column_index + locator.column_span
            ):
                position = (row_index, column_index)
                if position in occupied:
                    return None
                occupied.add(position)
        signature.append(
            (
                locator.row_index,
                locator.column_index,
                locator.row_span,
                locator.column_span,
                item.content_hash,
            )
        )
    expected = {
        (row_index, column_index)
        for row_index in range(2)
        for column_index in range(table.column_count)
    }
    return tuple(signature) if occupied == expected else None


def _endpoint(
    document: ParsedDocumentV1,
    table: ParseTableV1,
    *,
    signature: tuple[tuple[object, ...], ...] | None = None,
) -> CrossPageEndpointV1:
    signature = signature or _header_signature(document, table)
    if signature is None:
        _fail("BLOCKED", "TABLE_HEADER_INCOMPLETE")
    return CrossPageEndpointV1(
        endpoint_kind="table",
        endpoint_id=table.table_id,
        page_number=table.locator.page_number,
        endpoint_fact_digest_sha256=canonical_hash(
            "table-endpoint-facts.v1",
            {
                "table_id": table.table_id,
                "content_hash": table.content_hash,
                "structure_hash": table.structure_hash,
                "header": signature,
            },
        ),
        locator_digest_sha256=canonical_hash(
            "table-grid-shape.v1",
            {
                "row_count": table.row_count,
                "column_count": table.column_count,
                "header": signature,
            },
        ),
    )


def _block_endpoint(block: ParseBlockV1) -> CrossPageEndpointV1:
    return CrossPageEndpointV1(
        endpoint_kind="block",
        endpoint_id=block.block_id,
        page_number=block.locator.page_number,
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


def _binding_digest(binding: CrossPageRelationBindingV1) -> str:
    return canonical_hash(
        "cross-page-relation-binding.v1",
        binding.model_dump(mode="python", exclude={"replay_digest_sha256"}),
    )


def replay_cross_page_relation_binding_v1(
    binding: CrossPageRelationBindingV1,
) -> CrossPageRelationBindingV1:
    try:
        checked = CrossPageRelationBindingV1.model_validate(binding)
    except ValidationError:
        _fail("BLOCKED", "BINDING_SHAPE_INVALID")
    if checked.policy_sha256 != POLICY_SHA256 or checked.replay_digest_sha256 != _binding_digest(
        checked
    ):
        _fail("BLOCKED", "BINDING_REPLAY_INVALID")
    return checked


def _marker_request(
    *,
    source_sha256: str,
    cross_page_facts_digest_sha256: str,
    relation_kind: Literal["table", "section"],
    facts: Any,
) -> CrossPageMarkerReplayRequestV1:
    if facts.native_member_sha256 is None:
        _fail("BLOCKED", "NATIVE_OBSERVATION_INVALID")
    values = {
        "contract": "cross-page-marker-replay-request.v1",
        "source_sha256": source_sha256,
        "parser_model": facts.parser_model,
        "mineru_version": facts.mineru_version,
        "raw_zip_sha256": facts.raw_zip_sha256,
        "native_member_sha256": facts.native_member_sha256,
        "member_inventory_sha256": facts.member_inventory_sha256,
        "native_projection_sha256": facts.projection_sha256,
        "native_observation_sha256": facts.ambiguous_observation_hashes[0],
        "cross_page_facts_digest_sha256": cross_page_facts_digest_sha256,
        "relation_kind": relation_kind,
    }
    return CrossPageMarkerReplayRequestV1(
        **values,
        request_digest_sha256=canonical_hash("cross-page-marker-replay-request.v1", values),
    )


def _replay_marker(
    replay: CrossPageTypedMarkerReplayProtocol,
    request: CrossPageMarkerReplayRequestV1,
) -> CrossPageTypedMarkerEvidenceV1:
    try:
        supplied = replay.replay_typed_cross_page_marker(request)
        marker = CrossPageTypedMarkerEvidenceV1.model_validate(supplied)
    except (AttributeError, TypeError, ValidationError, ValueError):
        _fail("BLOCKED", "TYPED_MARKER_REPLAY_INVALID")
    expected_observation = _sha256(
        (
            "mineru-cross-page-ambiguous.v1\0"
            f"{request.source_sha256}\0{marker.marker_kind}\0"
            f"{marker.marker_structural_path}"
        ).encode()
    )
    if (
        marker.request_digest_sha256 != request.request_digest_sha256
        or marker.relation_kind != request.relation_kind
        or marker.marker_kind != "cross_page"
        or expected_observation != request.native_observation_sha256
    ):
        _fail("BLOCKED", "TYPED_MARKER_REPLAY_INVALID")
    return marker


def derive_cross_page_relation_596_1(
    bundle: MinerUCaptureBundle5961V1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    *,
    relation_kind: Literal["table", "section"] = "table",
    marker_replay: CrossPageTypedMarkerReplayProtocol | None = None,
    preserve_marker_envelope: bool = False,
) -> CrossPageRelationBindingV1:
    """Derive one structural relation without upgrading native marker authority."""

    intake = (
        _replay_intake(bundle, preserve_marker_envelope=True)
        if preserve_marker_envelope
        else _replay_intake(bundle)
    )
    if relation_kind == "section" and marker_replay is None:
        _fail("NOT_AVAILABLE", "SECTION_ENDPOINT_PROOF_NOT_AVAILABLE")
    item = intake.sources[2 if relation_kind == "table" else 0]
    doc, man = _validate_document_manifest(
        item.evidence,
        document,
        manifest,
        expected_source_sha256=item.source_sha256,
        relation_kind=relation_kind,
    )
    facts = item.evidence.cross_page_facts
    expected_capability = "cross_page_tables" if relation_kind == "table" else "cross_page_sections"
    if facts is None or facts.status == "NATIVE_CROSS_PAGE_FACT_NOT_AVAILABLE":
        _fail("NOT_AVAILABLE", "NATIVE_OBSERVATION_NOT_AVAILABLE")
    marker_absent_table = (
        relation_kind == "table"
        and marker_replay is None
        and facts.status == "NATIVE_CROSS_PAGE_FACT_ABSENT"
        and facts.required_capability == expected_capability
        and facts.relation_count == 0
        and not facts.relations
        and facts.ambiguous_marker_count == 0
        and not facts.ambiguous_observation_hashes
    )
    if not marker_absent_table and (
        facts.status != "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS"
        or facts.required_capability != expected_capability
        or facts.relation_count != 0
        or facts.relations
        or facts.ambiguous_marker_count != 1
        or len(facts.ambiguous_observation_hashes) != 1
    ):
        _fail("BLOCKED", "NATIVE_OBSERVATION_AMBIGUOUS")
    candidates: list[
        tuple[
            ParseTableV1,
            ParseTableV1,
            tuple[tuple[object, ...], ...],
        ]
    ] = []
    if relation_kind == "table":
        for source in doc.tables:
            source_header = (
                _leading_rows_signature(doc, source)
                if marker_absent_table
                else _header_signature(doc, source)
            )
            if source_header is None:
                continue
            for target in doc.tables:
                if target.locator.page_number != source.locator.page_number + 1:
                    continue
                target_header = (
                    _leading_rows_signature(doc, target)
                    if marker_absent_table
                    else _header_signature(doc, target)
                )
                if source.column_count == target.column_count and source_header == target_header:
                    candidates.append((source, target, source_header))
        if not candidates:
            _fail("NOT_AVAILABLE", "UNIQUE_TABLE_ENDPOINTS_NOT_AVAILABLE")
        if len(candidates) != 1:
            _fail("BLOCKED", "TABLE_ENDPOINTS_AMBIGUOUS")
    if marker_replay is None and not marker_absent_table:
        # 062 deliberately hashes cross_page=true and lines_deleted=true into
        # one unlabelled collection. A typed replay authority is mandatory.
        _fail("NOT_AVAILABLE", "NATIVE_MARKER_KIND_UNBOUND")
    if item.cross_page_facts_digest_sha256 is None:
        _fail("BLOCKED", "NATIVE_OBSERVATION_INVALID")
    if marker_absent_table:
        source_table, target_table, leading_rows = candidates[0]
        derived_preimage = {
            "contract": "unique-repeated-leading-table-grid.v1",
            "source_sha256": item.source_sha256,
            "raw_structure_sha256": item.evidence.raw_structure_sha256,
            "artifact_sha256": item.evidence.sanitized_structure_sha256,
            "source_table_id": source_table.table_id,
            "source_page_number": source_table.locator.page_number,
            "target_table_id": target_table.table_id,
            "target_page_number": target_table.locator.page_number,
            "column_count": source_table.column_count,
            "leading_rows": leading_rows,
        }
        native_observation_sha256 = canonical_hash(
            "unique-repeated-leading-table-grid.v1", derived_preimage
        )
        typed_marker_evidence_digest_sha256 = canonical_hash(
            "derived-table-grid-evidence.v1", derived_preimage
        )
        marker_path_sha256 = canonical_hash(
            "derived-table-grid-path.v1",
            {
                "source": (
                    source_table.locator.page_number,
                    source_table.locator.table_index,
                ),
                "target": (
                    target_table.locator.page_number,
                    target_table.locator.table_index,
                ),
            },
        )
        source_endpoint = _endpoint(doc, source_table, signature=leading_rows)
        target_endpoint = _endpoint(doc, target_table, signature=leading_rows)
    else:
        if marker_replay is None:
            _fail("NOT_AVAILABLE", "NATIVE_MARKER_KIND_UNBOUND")
        request = _marker_request(
            source_sha256=item.source_sha256,
            cross_page_facts_digest_sha256=item.cross_page_facts_digest_sha256,
            relation_kind=relation_kind,
            facts=facts,
        )
        marker = _replay_marker(marker_replay, request)
        native_observation_sha256 = facts.ambiguous_observation_hashes[0]
        typed_marker_evidence_digest_sha256 = marker.evidence_digest_sha256
        marker_path_sha256 = marker.marker_path_sha256
    if relation_kind == "table" and not marker_absent_table:
        source_table, target_table, _ = candidates[0]
        if (
            marker.source_endpoint_id != source_table.table_id
            or marker.source_page_number != source_table.locator.page_number
            or marker.target_endpoint_id != target_table.table_id
            or marker.target_page_number != target_table.locator.page_number
        ):
            _fail("BLOCKED", "TYPED_MARKER_ENDPOINT_DRIFT")
        source_endpoint = _endpoint(doc, source_table)
        target_endpoint = _endpoint(doc, target_table)
    elif relation_kind == "section":
        blocks = {block.block_id: block for block in doc.blocks}
        source_block = blocks.get(marker.source_endpoint_id)
        target_block = blocks.get(marker.target_endpoint_id)
        if (
            source_block is None
            or target_block is None
            or source_block.locator.page_number != marker.source_page_number
            or target_block.locator.page_number != marker.target_page_number
            or source_block.locator.page_number == target_block.locator.page_number
        ):
            _fail("BLOCKED", "TYPED_MARKER_ENDPOINT_DRIFT")
        source_endpoint = _block_endpoint(source_block)
        target_endpoint = _block_endpoint(target_block)
    parser_identity = canonical_hash("parser-identity.v1", doc.parser.model_dump(mode="python"))
    values = {
        "contract": "cross-page-relation-binding.v1",
        "status": "DERIVED_STRUCTURAL_BINDING_VERIFIED",
        "provenance": "DERIVED_STRUCTURAL_RELATION",
        "relation_kind": relation_kind,
        "source_sha256": item.source_sha256,
        "parser_identity_sha256": parser_identity,
        "parser_config_sha256": doc.parser.parser_config_hash,
        "intake_bundle_digest_sha256": intake.bundle_digest_sha256,
        "intake_item_digest_sha256": item.intake_digest_sha256,
        "capture_identity_sha256": item.capture_identity_sha256,
        "raw_structure_sha256": item.evidence.raw_structure_sha256,
        "artifact_sha256": item.evidence.sanitized_structure_sha256,
        "cross_page_facts_digest_sha256": item.cross_page_facts_digest_sha256,
        "parsed_document_hash": doc.document_hash,
        "parse_manifest_hash": man.manifest_hash,
        "native_projection_sha256": facts.projection_sha256,
        "native_observation_sha256": native_observation_sha256,
        "typed_marker_evidence_digest_sha256": typed_marker_evidence_digest_sha256,
        "marker_path_sha256": marker_path_sha256,
        "policy_sha256": POLICY_SHA256,
        "source_endpoint": source_endpoint,
        "target_endpoint": target_endpoint,
        "replay_digest_sha256": "0" * 64,
    }
    provisional = CrossPageRelationBindingV1.model_validate(values)
    binding = provisional.model_copy(update={"replay_digest_sha256": _binding_digest(provisional)})
    return replay_cross_page_relation_binding_v1(binding)


__all__ = [
    "CrossPageBindingError",
    "CrossPageMarkerReplayRequestV1",
    "CrossPageRelationBindingV1",
    "CrossPageTypedMarkerEvidenceV1",
    "CrossPageTypedMarkerReplayProtocol",
    "derive_cross_page_relation_596_1",
    "replay_cross_page_relation_binding_v1",
]
