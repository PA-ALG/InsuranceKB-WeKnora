"""Narrow OpenSpec 060 bridge from sanitized MinerU facts to OpenSpec 053."""

from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal

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
from insurance_harness.compiler.material_profiles import MaterialProfileResolution
from insurance_harness.compiler.parsed_documents import (
    BlockLocatorV1,
    CapabilityEvidenceV1,
    CellLocatorV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParseBlockV1,
    ParseCellV1,
    ParsedDocumentV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParseQualityDecisionV1,
    ParseQualityReviewItemV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    ParseTableV1,
    ParseWarningV1,
    TableLocatorV1,
    UnsupportedParseFactV1,
    build_parse_manifest,
    evaluate_parse_quality,
)

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]
NativeBBox = tuple[StrictStr, StrictStr, StrictStr, StrictStr]


class NativeMinerUStructureError(ValueError):
    """Typed fail-closed rejection of an untrusted or malformed sidecar."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class _Page(_FrozenModel):
    page_id: NonBlankStr
    page_number: PositiveInt
    content_hash: Sha256Hex
    structure_hash: Sha256Hex


class _Block(_FrozenModel):
    block_id: NonBlankStr
    order_index: NonNegativeInt
    page_number: PositiveInt
    block_index: NonNegativeInt
    bbox: NativeBBox
    content_hash: Sha256Hex
    structure_hash: Sha256Hex


class _Table(_FrozenModel):
    table_id: NonBlankStr
    order_index: NonNegativeInt
    page_number: PositiveInt
    table_index: NonNegativeInt
    bbox: NativeBBox
    content_hash: Sha256Hex
    structure_hash: Sha256Hex
    row_count: PositiveInt
    column_count: PositiveInt
    header_cell_ids: tuple[NonBlankStr, ...]


class _Cell(_FrozenModel):
    cell_id: NonBlankStr
    order_index: NonNegativeInt
    table_id: NonBlankStr
    page_number: PositiveInt
    row_index: NonNegativeInt
    column_index: NonNegativeInt
    row_span: PositiveInt
    column_span: PositiveInt
    bbox: NativeBBox
    content_hash: Sha256Hex
    structure_hash: Sha256Hex


class _SanitizedStructure(_FrozenModel):
    contract: Literal["mineru-native-structure.v1"]
    source_schema: Literal["mineru.content-list.pipeline.v1"]
    parser_model: Literal["pipeline"]
    source_sha256: Sha256Hex
    raw_sha256: Sha256Hex
    pages: tuple[_Page, ...]
    blocks: tuple[_Block, ...]
    tables: tuple[_Table, ...]
    cells: tuple[_Cell, ...]
    unsupported: tuple[
        Literal[
            "block_locators",
            "table_grid",
            "cell_locators",
            "row_column_indices",
            "merged_cells",
            "header_hierarchy",
            "cross_page_sections",
            "cross_page_tables",
            "native_structure_invalid",
            "table_cell_fragment_merged_to_unique_span",
        ],
        ...,
    ]

    @model_validator(mode="after")
    def require_closed_native_structure(self) -> _SanitizedStructure:
        if not self.pages or (
            not self.blocks and "native_structure_invalid" not in self.unsupported
        ):
            raise ValueError("native structure is empty")
        if tuple(page.page_number for page in self.pages) != tuple(
            range(1, len(self.pages) + 1)
        ):
            raise ValueError("native pages are not contiguous")
        if tuple(block.order_index for block in self.blocks) != tuple(
            range(len(self.blocks))
        ):
            raise ValueError("native blocks are not contiguous")
        if tuple(table.order_index for table in self.tables) != tuple(
            range(len(self.tables))
        ):
            raise ValueError("native tables are not contiguous")
        if tuple(cell.order_index for cell in self.cells) != tuple(
            range(len(self.cells))
        ):
            raise ValueError("native cells are not contiguous")
        if len(self.unsupported) != len(set(self.unsupported)):
            raise ValueError("native unsupported facts are duplicated")
        return self


def _validate_structure_relationships(structure: _SanitizedStructure) -> None:
    pages = {item.page_number: item for item in structure.pages}
    all_ids = (
        tuple(item.page_id for item in structure.pages)
        + tuple(item.block_id for item in structure.blocks)
        + tuple(item.table_id for item in structure.tables)
        + tuple(item.cell_id for item in structure.cells)
    )
    if len(all_ids) != len(set(all_ids)):
        raise NativeMinerUStructureError("invalid_native_relationship")

    for page_number in pages:
        block_indices = tuple(
            item.block_index
            for item in structure.blocks
            if item.page_number == page_number
        )
        table_indices = tuple(
            item.table_index
            for item in structure.tables
            if item.page_number == page_number
        )
        if block_indices != tuple(range(len(block_indices))) or table_indices != tuple(
            range(len(table_indices))
        ):
            raise NativeMinerUStructureError("invalid_native_relationship")
    if any(item.page_number not in pages for item in structure.blocks):
        raise NativeMinerUStructureError("invalid_native_relationship")
    if any(item.page_number not in pages for item in structure.tables):
        raise NativeMinerUStructureError("invalid_native_relationship")

    tables = {item.table_id: item for item in structure.tables}
    cells_by_table: dict[str, list[_Cell]] = {table_id: [] for table_id in tables}
    for cell in structure.cells:
        table = tables.get(cell.table_id)
        if (
            table is None
            or cell.page_number != table.page_number
            or (
                _bbox_is_valid(cell.bbox)
                and _bbox_is_valid(table.bbox)
                and cell.bbox != table.bbox
            )
        ):
            raise NativeMinerUStructureError("invalid_native_relationship")
        cells_by_table[cell.table_id].append(cell)

    for table_id, table in tables.items():
        cells = cells_by_table[table_id]
        if not cells:
            raise NativeMinerUStructureError("invalid_native_relationship")
        cell_ids = {item.cell_id for item in cells}
        if any(cell_id not in cell_ids for cell_id in table.header_cell_ids):
            raise NativeMinerUStructureError("invalid_native_relationship")
        occupied: set[tuple[int, int]] = set()
        for cell in cells:
            if (
                cell.row_index + cell.row_span > table.row_count
                or cell.column_index + cell.column_span > table.column_count
            ):
                raise NativeMinerUStructureError("invalid_native_relationship")
            for row_index in range(cell.row_index, cell.row_index + cell.row_span):
                for column_index in range(
                    cell.column_index, cell.column_index + cell.column_span
                ):
                    position = (row_index, column_index)
                    if position in occupied:
                        raise NativeMinerUStructureError(
                            "invalid_native_relationship"
                        )
                    occupied.add(position)
        expected = {
            (row_index, column_index)
            for row_index in range(table.row_count)
            for column_index in range(table.column_count)
        }
        if occupied != expected:
            raise NativeMinerUStructureError("invalid_native_relationship")


def _bbox(value: NativeBBox) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    try:
        result = tuple(Decimal(item) for item in value)
    except (InvalidOperation, ValueError) as exc:
        raise NativeMinerUStructureError("invalid_native_bbox") from exc
    if (
        len(result) != 4
        or not all(item.is_finite() for item in result)
        or result[0] < 0
        or result[1] < 0
        or result[2] > 1000
        or result[3] > 1000
        or result[2] <= result[0]
        or result[3] <= result[1]
    ):
        raise NativeMinerUStructureError("invalid_native_bbox")
    return result


def _bbox_is_valid(value: NativeBBox) -> bool:
    try:
        _bbox(value)
    except NativeMinerUStructureError:
        return False
    return True


def _native_leading_rows_signature(
    table: _Table,
    cells: tuple[_Cell, ...],
) -> tuple[tuple[object, ...], ...] | None:
    if table.row_count < 2:
        return None
    selected = tuple(
        cell
        for cell in cells
        if cell.table_id == table.table_id and cell.row_index < 2
    )
    occupied: set[tuple[int, int]] = set()
    signature: list[tuple[object, ...]] = []
    for cell in sorted(selected, key=lambda item: (item.row_index, item.column_index)):
        for row_index in range(cell.row_index, min(2, cell.row_index + cell.row_span)):
            for column_index in range(
                cell.column_index, cell.column_index + cell.column_span
            ):
                position = (row_index, column_index)
                if position in occupied:
                    return None
                occupied.add(position)
        signature.append(
            (
                cell.row_index,
                cell.column_index,
                cell.row_span,
                cell.column_span,
                cell.content_hash,
            )
        )
    expected = {
        (row_index, column_index)
        for row_index in range(2)
        for column_index in range(table.column_count)
    }
    return tuple(signature) if occupied == expected else None


def _load_structure(
    sanitized_json: bytes,
    *,
    expected_raw_sha256: str,
    expected_sanitized_sha256: str,
) -> _SanitizedStructure:
    if hashlib.sha256(sanitized_json).hexdigest() != expected_sanitized_sha256:
        raise NativeMinerUStructureError("sanitized_structure_digest_mismatch")
    try:
        structure = _SanitizedStructure.model_validate_json(sanitized_json)
    except (ValidationError, ValueError, UnicodeError):
        raise NativeMinerUStructureError("invalid_native_structure") from None
    if structure.raw_sha256 != expected_raw_sha256:
        raise NativeMinerUStructureError("native_artifact_digest_mismatch")
    _validate_structure_relationships(structure)
    return structure


def build_mineru_parsed_document_v1(  # noqa: C901
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
    trusted_relation_bindings: tuple[object, ...] = (),
) -> tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1]:
    """Validate one sidecar, construct 053 objects, and run the sole quality gate."""

    try:
        subject = ParseSubjectV1.model_validate(subject)
        parser = ParserIdentityV1.model_validate(parser)
        attempt = ParseAttemptV1.model_validate(attempt)
        snapshot = ParseSnapshotV1.model_validate(snapshot)
        output_facts = ParseOutputFactsV1.model_validate(output_facts)
        material_profile_resolution = MaterialProfileResolution.model_validate(
            material_profile_resolution
        )
    except ValidationError:
        raise NativeMinerUStructureError("bridge_identity_mismatch") from None
    if (
        parser.parser_id != "mineru-cloud-pipeline"
        or attempt.attempt_number != 2
        or attempt.attempt_role != "bounded_upgrade"
    ):
        raise NativeMinerUStructureError("bridge_identity_mismatch")
    structure = _load_structure(
        sanitized_json,
        expected_raw_sha256=expected_raw_sha256,
        expected_sanitized_sha256=expected_sanitized_sha256,
    )
    if subject.raw_artifact_hash != expected_raw_sha256:
        raise NativeMinerUStructureError("native_artifact_digest_mismatch")
    if (
        structure.source_sha256 != subject.source_sha256
        or structure.source_sha256
        != material_profile_resolution.profile.source.sha256
    ):
        raise NativeMinerUStructureError("source_identity_mismatch")

    invalid_block_bbox = any(
        not _bbox_is_valid(item.bbox) for item in structure.blocks
    )
    invalid_table_bbox = any(
        not _bbox_is_valid(item.bbox) for item in structure.tables
    )
    invalid_cell_bbox = any(
        not _bbox_is_valid(item.bbox) for item in structure.cells
    )
    native_structure_invalid = (
        invalid_block_bbox
        or invalid_table_bbox
        or invalid_cell_bbox
        or "native_structure_invalid" in structure.unsupported
    )
    bridge_blocks = () if invalid_block_bbox else structure.blocks
    bridge_tables = (
        () if invalid_table_bbox or invalid_cell_bbox else structure.tables
    )
    bridge_cells = () if invalid_table_bbox or invalid_cell_bbox else structure.cells

    derived_rate_header_ids: dict[str, tuple[str, ...]] = {}
    derived_rate_table_ids: tuple[str, ...] = ()
    if (
        material_profile_resolution.profile.material_role == "rate_table"
        and not invalid_table_bbox
        and not invalid_cell_bbox
    ):
        candidates: list[tuple[_Table, _Table]] = []
        for source_table in bridge_tables:
            source_signature = _native_leading_rows_signature(
                source_table, bridge_cells
            )
            if source_signature is None:
                continue
            for target_table in bridge_tables:
                target_signature = _native_leading_rows_signature(
                    target_table, bridge_cells
                )
                if (
                    target_table.page_number == source_table.page_number + 1
                    and target_table.column_count == source_table.column_count
                    and target_signature == source_signature
                ):
                    candidates.append((source_table, target_table))
        if len(candidates) == 1:
            source_table, target_table = candidates[0]
            derived_rate_table_ids = (source_table.table_id, target_table.table_id)
            for table in candidates[0]:
                derived_rate_header_ids[table.table_id] = tuple(
                    cell.cell_id
                    for cell in bridge_cells
                    if cell.table_id == table.table_id and cell.row_index < 2
                )

    pages = tuple(
        ParsePageV1(
            page_id=item.page_id,
            order_index=index,
            locator=PageLocatorV1(page_number=item.page_number),
            content_hash=item.content_hash,
            structure_hash=item.structure_hash,
        )
        for index, item in enumerate(structure.pages)
    )
    blocks = tuple(
        ParseBlockV1(
            block_id=item.block_id,
            order_index=item.order_index,
            locator=BlockLocatorV1(
                page_number=item.page_number,
                block_index=item.block_index,
                bbox=_bbox(item.bbox),
            ),
            content_hash=item.content_hash,
            structure_hash=item.structure_hash,
        )
        for item in bridge_blocks
    )
    tables = tuple(
        ParseTableV1(
            table_id=item.table_id,
            order_index=item.order_index,
            locator=TableLocatorV1(
                page_number=item.page_number,
                table_index=item.table_index,
                bbox=_bbox(item.bbox),
            ),
            content_hash=item.content_hash,
            structure_hash=item.structure_hash,
            row_count=item.row_count,
            column_count=item.column_count,
            header_cell_ids=(
                item.header_cell_ids
                or derived_rate_header_ids.get(item.table_id, ())
            ),
            continuation_table_ids=(),
        )
        for item in bridge_tables
    )
    cells = tuple(
        ParseCellV1(
            cell_id=item.cell_id,
            order_index=item.order_index,
            table_id=item.table_id,
            locator=CellLocatorV1(
                page_number=item.page_number,
                table_id=item.table_id,
                row_index=item.row_index,
                column_index=item.column_index,
                row_span=item.row_span,
                column_span=item.column_span,
                bbox=_bbox(item.bbox),
            ),
            content_hash=item.content_hash,
            structure_hash=item.structure_hash,
        )
        for item in bridge_cells
    )

    page_ids = tuple(item.page_id for item in pages)
    block_ids = tuple(item.block_id for item in blocks)
    table_ids = tuple(item.table_id for item in tables)
    cell_ids = tuple(item.cell_id for item in cells)
    merged_ids = tuple(
        item.cell_id
        for item in cells
        if item.locator.row_span > 1 or item.locator.column_span > 1
    )
    header_ids = tuple(
        cell_id for table in tables for cell_id in table.header_cell_ids
    )
    unsupported_capabilities = set(structure.unsupported)
    if invalid_block_bbox:
        unsupported_capabilities.update(
            {"block_locators", "native_structure_invalid"}
        )
    if invalid_table_bbox or invalid_cell_bbox:
        unsupported_capabilities.update(
            {
                "table_grid",
                "cell_locators",
                "row_column_indices",
                "merged_cells",
                "header_hierarchy",
                "native_structure_invalid",
            }
        )
    evidence = [
        CapabilityEvidenceV1(capability="ordered_pages", subject_refs=page_ids),
    ]
    if block_ids and "block_locators" not in unsupported_capabilities:
        evidence.append(
            CapabilityEvidenceV1(
                capability="block_locators", subject_refs=block_ids
            )
        )
    if table_ids and cell_ids and "table_grid" not in unsupported_capabilities:
        evidence.append(
            CapabilityEvidenceV1(
                capability="table_grid", subject_refs=table_ids + cell_ids
            )
        )
    if cell_ids and "cell_locators" not in unsupported_capabilities:
        evidence.append(
            CapabilityEvidenceV1(capability="cell_locators", subject_refs=cell_ids)
        )
    if cell_ids and "row_column_indices" not in unsupported_capabilities:
        evidence.append(
            CapabilityEvidenceV1(
                capability="row_column_indices", subject_refs=cell_ids
            )
        )
    if merged_ids and "merged_cells" not in unsupported_capabilities:
        evidence.append(
            CapabilityEvidenceV1(capability="merged_cells", subject_refs=merged_ids)
        )
    if tables and "header_hierarchy" not in unsupported_capabilities and (
        all(table.header_cell_ids for table in tables) or derived_rate_table_ids
    ):
        header_table_ids = (
            derived_rate_table_ids if derived_rate_table_ids else table_ids
        )
        evidence.append(
            CapabilityEvidenceV1(
                capability="header_hierarchy",
                subject_refs=header_table_ids + header_ids,
            )
        )

    try:
        document = ParsedDocumentV1(
            contract="parsed-document.v1",
            subject=subject,
            parser=parser,
            attempt=attempt,
            snapshot=snapshot,
            output_facts=output_facts,
            pages=pages,
            blocks=blocks,
            tables=tables,
            cells=cells,
            capability_evidence=tuple(evidence),
            warnings=tuple(
                warning
                for warning in (
                    ParseWarningV1(
                        warning_code="native_cell_bbox_is_table_scoped",
                        subject_refs=cell_ids,
                    ),
                    (
                        ParseWarningV1(
                            warning_code="native_structure_invalid",
                            subject_refs=page_ids,
                        )
                        if native_structure_invalid
                        else None
                    ),
                    (
                        ParseWarningV1(
                            warning_code="derived_repeated_leading_rows_header_hierarchy",
                            subject_refs=derived_rate_table_ids,
                        )
                        if derived_rate_table_ids
                        else None
                    ),
                    (
                        ParseWarningV1(
                            warning_code="table_cell_fragment_merged_to_unique_span",
                            subject_refs=table_ids,
                        )
                        if "table_cell_fragment_merged_to_unique_span"
                        in unsupported_capabilities
                        else None
                    ),
                )
                if warning is not None
            ),
            unsupported=tuple(
                UnsupportedParseFactV1(
                    capability=capability,
                    reason_code="native_mineru_capability_not_proven",
                    subject_refs=page_ids,
                )
                for capability in sorted(unsupported_capabilities)
            ),
        )
    except ValidationError:
        raise NativeMinerUStructureError("invalid_native_relationship") from None
    if trusted_relation_bindings:
        from insurance_harness.knowledge_compiler.relation_bound_admission_596_1 import (
            Trusted090RelationInputV1,
        )

        try:
            bindings = tuple(
                Trusted090RelationInputV1.model_validate(item)
                for item in trusted_relation_bindings
            )
        except (TypeError, ValidationError, ValueError):
            raise NativeMinerUStructureError("trusted_relation_binding_invalid") from None
        policy_hash = canonical_hash(
            "cross-page-relation-policy-context.v1",
            {
                "material_profile_binding_hash": material_profile_resolution.binding_hash,
                "parse_policy_receipt": (
                    material_profile_resolution.parse_policy_receipt.model_dump(mode="python")
                ),
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
                "raw_artifact_sha256": expected_raw_sha256,
                "sanitized_structure_sha256": expected_sanitized_sha256,
            },
        )
        expected_kind = (
            "section_continuation"
            if material_profile_resolution.profile.material_role in {"terms", "brochure"}
            else "table_continuation"
            if material_profile_resolution.profile.material_role == "rate_table"
            else None
        )
        block_ids_set = set(block_ids)
        table_ids_set = set(table_ids)
        if (
            expected_kind is None
            or len({binding.relation_id for binding in bindings}) != len(bindings)
            or any(
                binding.relation_kind != expected_kind
                or binding.source_sha256 != subject.source_sha256
                or binding.parser_id != parser.parser_id
                or binding.parser_build_id != parser.parser_build_id
                or binding.parser_config_hash != parser.parser_config_hash
                or binding.raw_artifact_sha256 != expected_raw_sha256
                or binding.sanitized_structure_sha256 != expected_sanitized_sha256
                or binding.material_profile_binding_hash
                != material_profile_resolution.binding_hash
                or binding.policy_context_hash != policy_hash
                or binding.replay_context_hash != replay_hash
                for binding in bindings
            )
        ):
            raise NativeMinerUStructureError("trusted_relation_binding_invalid")
        endpoint_inventory = (
            block_ids_set if expected_kind == "section_continuation" else table_ids_set
        )
        if any(
            endpoint not in endpoint_inventory
            for binding in bindings
            for endpoint in binding.endpoint_ids
        ):
            raise NativeMinerUStructureError("trusted_relation_endpoint_invalid")

        capability = (
            "cross_page_sections"
            if expected_kind == "section_continuation"
            else "cross_page_tables"
        )
        endpoint_refs = tuple(
            dict.fromkeys(
                endpoint
                for binding in bindings
                for endpoint in binding.endpoint_ids
            )
        )
        updated_tables = document.tables
        if expected_kind == "table_continuation":
            continuation: dict[str, str] = {}
            for binding in bindings:
                left, right = binding.endpoint_ids
                if left in continuation or right in continuation:
                    raise NativeMinerUStructureError("trusted_relation_endpoint_invalid")
                continuation[left] = right
                continuation[right] = left
            updated_tables = tuple(
                table.model_copy(
                    update={
                        "continuation_table_ids": (
                            (continuation[table.table_id],)
                            if table.table_id in continuation
                            else ()
                        )
                    }
                )
                for table in document.tables
            )
        document = ParsedDocumentV1.model_validate(
            {
                **document.model_dump(mode="python", exclude={"document_hash"}),
                "tables": updated_tables,
                "capability_evidence": (
                    *tuple(
                        row
                        for row in document.capability_evidence
                        if row.capability != capability
                    ),
                    CapabilityEvidenceV1(
                        capability=capability,
                        subject_refs=endpoint_refs,
                    ),
                ),
                "unsupported": tuple(
                    row for row in document.unsupported if row.capability != capability
                ),
            }
        )
    manifest = build_parse_manifest(document, material_profile_resolution.profile)
    decision = evaluate_parse_quality(
        document=document,
        manifest=manifest,
        material_profile_resolution=material_profile_resolution,
    )
    if native_structure_invalid:
        decision = ParseQualityDecisionV1(
            contract="parse-quality-decision.v1",
            subject=document.subject,
            manifest_hash=manifest.manifest_hash,
            parse_policy_receipt=decision.parse_policy_receipt,
            measured_facts=decision.measured_facts,
            decision="BLOCK",
            reason_codes=("locator_invalid_or_required_structure_missing",),
            admitted_attempt_id=None,
            next_parser_profile_ref=None,
            review_item=ParseQualityReviewItemV1(
                reason_code="locator_invalid_or_required_structure_missing",
                material_profile_id=document.subject.material_profile_id,
                source_revision_id=document.subject.source_revision_id,
                attempt_id=document.attempt.attempt_id,
                manifest_hash=manifest.manifest_hash,
            ),
        )
    return document, manifest, decision
