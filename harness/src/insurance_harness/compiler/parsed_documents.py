"""Parser-neutral document and manifest contracts for OpenSpec 053.

The models in this module carry identities, structure, locators, and hashes. They
do not carry source text and do not select or invoke a parser.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Annotated, Final, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    computed_field,
    field_validator,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.material_profiles import (
    MaterialProfile,
    MaterialProfileResolution,
    OutputPolicyRef,
    ParsePolicyReceipt,
    ParserProfileRef,
    PrivacyPolicyRef,
    UpgradeTriggerCondition,
)

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(gt=0)]


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("binary float is forbidden; use a decimal string or integer")
    return value


CanonicalDecimal = Annotated[Decimal, BeforeValidator(_reject_float)]
BBox = tuple[CanonicalDecimal, CanonicalDecimal, CanonicalDecimal, CanonicalDecimal]
AttemptRole = Literal["default", "bounded_upgrade"]
QualityDecision = Literal["ADMIT", "ESCALATE", "BLOCK"]
QualityReason = Literal[
    "identity_revision_parser_drift",
    "manifest_digest_or_count_mismatch",
    "locator_invalid_or_required_structure_missing",
    "table_grid_or_span_incomplete",
    "unsupported_material_or_parser_profile",
    "privacy_or_output_policy_violation",
]

PARSED_DOCUMENT_OBJECT_TYPE: Final[str] = "parsed-document.v1"
PARSE_MANIFEST_OBJECT_TYPE: Final[str] = "parse-manifest.v1"
PARSE_QUALITY_DECISION_OBJECT_TYPE: Final[str] = "parse-quality-decision.v1"
PARSE_QUALITY_THRESHOLD_VERSION: Final[
    Literal["parse-quality-structural.v1"]
] = "parse-quality-structural.v1"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class ParseContractError(ValueError):
    """Typed failure for an inadmissible parsed-document contract."""

    def __init__(
        self,
        reason_code: str,
        *,
        unsatisfied_capabilities: tuple[str, ...] = (),
    ) -> None:
        self.reason_code = reason_code
        self.unsatisfied_capabilities = unsatisfied_capabilities
        super().__init__(reason_code)


class ParseSubjectV1(_FrozenModel):
    space_id: NonBlankStr
    source_id: NonBlankStr
    source_revision_id: NonBlankStr
    product_version_id: NonBlankStr
    material_profile_id: NonBlankStr
    material_profile_binding_hash: Sha256Hex
    source_sha256: Sha256Hex
    raw_artifact_hash: Sha256Hex
    canonical_envelope_hash: Sha256Hex


class ParserIdentityV1(_FrozenModel):
    parser_id: NonBlankStr
    parser_profile_ref: ParserProfileRef
    parser_build_id: NonBlankStr
    parser_config_hash: Sha256Hex


class ParseAttemptV1(_FrozenModel):
    attempt_id: NonBlankStr
    attempt_number: Literal[1, 2]
    attempt_role: AttemptRole
    generation: NonNegativeInt

    @model_validator(mode="after")
    def require_bounded_role_order(self) -> Self:
        expected: dict[int, AttemptRole] = {1: "default", 2: "bounded_upgrade"}
        if self.attempt_role != expected[self.attempt_number]:
            raise ValueError("parse attempt role does not match bounded attempt order")
        return self


class PageLocatorV1(_FrozenModel):
    page_number: PositiveInt


class _BBoxLocator(PageLocatorV1):
    bbox: BBox

    @field_validator("bbox")
    @classmethod
    def require_non_empty_bbox(cls, value: BBox) -> BBox:
        left, top, right, bottom = value
        if right <= left or bottom <= top:
            raise ValueError("bbox must have positive width and height")
        return value


class BlockLocatorV1(_BBoxLocator):
    block_index: NonNegativeInt


class TableLocatorV1(_BBoxLocator):
    table_index: NonNegativeInt


class CellLocatorV1(_BBoxLocator):
    table_id: NonBlankStr
    row_index: NonNegativeInt
    column_index: NonNegativeInt
    row_span: PositiveInt
    column_span: PositiveInt


class ParsePageV1(_FrozenModel):
    page_id: NonBlankStr
    order_index: NonNegativeInt
    locator: PageLocatorV1
    content_hash: Sha256Hex
    structure_hash: Sha256Hex


class ParseBlockV1(_FrozenModel):
    block_id: NonBlankStr
    order_index: NonNegativeInt
    locator: BlockLocatorV1
    content_hash: Sha256Hex
    structure_hash: Sha256Hex


class ParseTableV1(_FrozenModel):
    table_id: NonBlankStr
    order_index: NonNegativeInt
    locator: TableLocatorV1
    content_hash: Sha256Hex
    structure_hash: Sha256Hex
    row_count: PositiveInt
    column_count: PositiveInt
    header_cell_ids: tuple[NonBlankStr, ...]
    continuation_table_ids: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def require_unique_structure_refs(self) -> Self:
        if len(self.header_cell_ids) != len(set(self.header_cell_ids)):
            raise ValueError("table header cell ids must be unique")
        if len(self.continuation_table_ids) != len(set(self.continuation_table_ids)):
            raise ValueError("continuation table ids must be unique")
        if self.table_id in self.continuation_table_ids:
            raise ValueError("table cannot continue into itself")
        return self


class ParseCellV1(_FrozenModel):
    cell_id: NonBlankStr
    order_index: NonNegativeInt
    table_id: NonBlankStr
    locator: CellLocatorV1
    content_hash: Sha256Hex
    structure_hash: Sha256Hex

    @model_validator(mode="after")
    def require_locator_table_identity(self) -> Self:
        if self.table_id != self.locator.table_id:
            raise ValueError("cell table identity does not match locator")
        return self


class CapabilityEvidenceV1(_FrozenModel):
    capability: NonBlankStr
    subject_refs: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def require_unique_subject_refs(self) -> Self:
        if not self.subject_refs or len(self.subject_refs) != len(set(self.subject_refs)):
            raise ValueError("capability evidence refs must be non-empty and unique")
        return self


class ParseWarningV1(_FrozenModel):
    warning_code: NonBlankStr
    subject_refs: tuple[NonBlankStr, ...] = ()


class UnsupportedParseFactV1(_FrozenModel):
    capability: NonBlankStr
    reason_code: NonBlankStr
    subject_refs: tuple[NonBlankStr, ...] = ()


class ParseSnapshotV1(_FrozenModel):
    snapshot_id: NonBlankStr
    snapshot_generation: NonNegativeInt
    pagination_complete: bool
    concurrent_mutation_fence_hash: Sha256Hex


class ParseOutputFactsV1(_FrozenModel):
    privacy_policy_ref: PrivacyPolicyRef
    output_policy_ref: OutputPolicyRef
    body_text_included: bool
    secrets_included: bool
    absolute_paths_included: bool
    unknown_vendor_fields_included: bool


def _ids(values: Iterable[tuple[str, int]]) -> tuple[str, ...]:
    pairs = tuple(values)
    if tuple(index for _, index in pairs) != tuple(range(len(pairs))):
        raise ValueError("ordered structure indices must be contiguous from zero")
    identifiers = tuple(identifier for identifier, _ in pairs)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("ordered structure identifiers must be unique")
    return identifiers


class ParsedDocumentV1(_FrozenModel):
    contract: Literal["parsed-document.v1"]
    subject: ParseSubjectV1
    parser: ParserIdentityV1
    attempt: ParseAttemptV1
    snapshot: ParseSnapshotV1
    output_facts: ParseOutputFactsV1
    pages: tuple[ParsePageV1, ...]
    blocks: tuple[ParseBlockV1, ...]
    tables: tuple[ParseTableV1, ...]
    cells: tuple[ParseCellV1, ...]
    capability_evidence: tuple[CapabilityEvidenceV1, ...]
    warnings: tuple[ParseWarningV1, ...]
    unsupported: tuple[UnsupportedParseFactV1, ...]

    @model_validator(mode="after")
    def require_closed_ordered_structure(self) -> Self:  # noqa: C901
        page_ids = _ids((item.page_id, item.order_index) for item in self.pages)
        block_ids = _ids((item.block_id, item.order_index) for item in self.blocks)
        table_ids = _ids((item.table_id, item.order_index) for item in self.tables)
        cell_ids = _ids((item.cell_id, item.order_index) for item in self.cells)
        if tuple(page.locator.page_number for page in self.pages) != tuple(
            range(1, len(self.pages) + 1)
        ):
            raise ValueError("ordered structure page numbers must be contiguous from one")
        page_numbers = {page.locator.page_number for page in self.pages}
        if any(item.locator.page_number not in page_numbers for item in self.blocks):
            raise ValueError("block locator references an unknown page")
        if any(item.locator.page_number not in page_numbers for item in self.tables):
            raise ValueError("table locator references an unknown page")
        if any(item.locator.page_number not in page_numbers for item in self.cells):
            raise ValueError("cell locator references an unknown page")
        if any(item.table_id not in table_ids for item in self.cells):
            raise ValueError("cell references an unknown table")
        tables_by_id = {item.table_id: item for item in self.tables}
        cells_by_id = {item.cell_id: item for item in self.cells}
        for cell in self.cells:
            table = tables_by_id[cell.table_id]
            locator = cell.locator
            if (
                locator.row_index + locator.row_span > table.row_count
                or locator.column_index + locator.column_span > table.column_count
            ):
                raise ValueError("cell locator exceeds table bounds")
        for table in self.tables:
            if any(
                cell_id not in cells_by_id
                or cells_by_id[cell_id].table_id != table.table_id
                for cell_id in table.header_cell_ids
            ):
                raise ValueError("table header references an unknown cell")
            if any(
                table_id not in tables_by_id
                for table_id in table.continuation_table_ids
            ):
                raise ValueError("table continuation references an unknown table")
        all_refs = set(page_ids + block_ids + table_ids + cell_ids)
        capabilities = tuple(item.capability for item in self.capability_evidence)
        unsupported = tuple(item.capability for item in self.unsupported)
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("capability evidence must be unique")
        if len(unsupported) != len(set(unsupported)):
            raise ValueError("unsupported capabilities must be unique")
        if set(capabilities) & set(unsupported):
            raise ValueError("a capability cannot be both evidenced and unsupported")
        referenced_groups = (
            tuple(item.subject_refs for item in self.warnings)
            + tuple(item.subject_refs for item in self.unsupported)
        )
        if any(
            reference not in all_refs
            for references in referenced_groups
            for reference in references
        ):
            raise ValueError("unknown subject ref in parsed document")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def document_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"document_hash"})
        return canonical_hash(PARSED_DOCUMENT_OBJECT_TYPE, payload)


class ParseElementCountsV1(_FrozenModel):
    pages: NonNegativeInt
    blocks: NonNegativeInt
    tables: NonNegativeInt
    cells: NonNegativeInt


class ParseManifestV1(_FrozenModel):
    contract: Literal["parse-manifest.v1"]
    subject: ParseSubjectV1
    parser: ParserIdentityV1
    attempt: ParseAttemptV1
    snapshot: ParseSnapshotV1
    output_facts: ParseOutputFactsV1
    document_hash: Sha256Hex
    ordered_page_ids: tuple[NonBlankStr, ...]
    ordered_block_ids: tuple[NonBlankStr, ...]
    ordered_table_ids: tuple[NonBlankStr, ...]
    ordered_cell_ids: tuple[NonBlankStr, ...]
    element_counts: ParseElementCountsV1
    required_capabilities: tuple[NonBlankStr, ...]
    satisfied_capabilities: tuple[NonBlankStr, ...]
    unsatisfied_capabilities: tuple[NonBlankStr, ...]
    capability_evidence: tuple[CapabilityEvidenceV1, ...]
    warnings: tuple[ParseWarningV1, ...]
    unsupported: tuple[UnsupportedParseFactV1, ...]

    @model_validator(mode="after")
    def require_complete_inventory(self) -> Self:
        inventories = (
            (self.ordered_page_ids, self.element_counts.pages),
            (self.ordered_block_ids, self.element_counts.blocks),
            (self.ordered_table_ids, self.element_counts.tables),
            (self.ordered_cell_ids, self.element_counts.cells),
        )
        if any(
            len(items) != count or len(items) != len(set(items))
            for items, count in inventories
        ):
            raise ValueError("manifest digest or count mismatch")
        required = self.required_capabilities
        if not required or len(required) != len(set(required)):
            raise ValueError("required capabilities must be non-empty and unique")
        expected_unsatisfied = tuple(
            item for item in required if item not in self.satisfied_capabilities
        )
        if self.unsatisfied_capabilities != expected_unsatisfied:
            raise ValueError("manifest capability partition mismatch")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def manifest_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"manifest_hash"})
        return canonical_hash(PARSE_MANIFEST_OBJECT_TYPE, payload)


def _capability_evidence_is_structural(
    document: ParsedDocumentV1,
    evidence: CapabilityEvidenceV1,
) -> bool:
    """Validate only the capability families frozen by OpenSpec 052."""

    refs = set(evidence.subject_refs)
    pages = {item.page_id: item for item in document.pages}
    blocks = {item.block_id: item for item in document.blocks}
    tables = {item.table_id: item for item in document.tables}
    cells = {item.cell_id: item for item in document.cells}

    if evidence.capability == "ordered_pages":
        return bool(pages) and refs == set(pages)
    if evidence.capability == "block_locators":
        return bool(refs) and refs <= set(blocks)
    if evidence.capability == "cross_page_sections":
        return refs <= set(blocks) and len(
            {blocks[ref].locator.page_number for ref in refs}
        ) >= 2
    if evidence.capability == "table_grid":
        table_refs = refs & set(tables)
        cell_refs = refs & set(cells)
        return (
            bool(table_refs)
            and bool(cell_refs)
            and refs == table_refs | cell_refs
            and all(cells[ref].table_id in table_refs for ref in cell_refs)
        )
    if evidence.capability in {"cell_locators", "row_column_indices"}:
        return bool(refs) and refs <= set(cells)
    if evidence.capability == "header_hierarchy":
        table_refs = refs & set(tables)
        cell_refs = refs & set(cells)
        return (
            bool(table_refs)
            and bool(cell_refs)
            and refs == table_refs | cell_refs
            and all(
                any(cell_id in cell_refs for cell_id in tables[ref].header_cell_ids)
                for ref in table_refs
            )
        )
    if evidence.capability == "merged_cells":
        return bool(refs) and refs <= set(cells) and any(
            cells[ref].locator.row_span > 1
            or cells[ref].locator.column_span > 1
            for ref in refs
        )
    if evidence.capability == "cross_page_tables":
        return (
            len(refs) >= 2
            and refs <= set(tables)
            and len({tables[ref].locator.page_number for ref in refs}) >= 2
            and any(
                continuation in refs
                for ref in refs
                for continuation in tables[ref].continuation_table_ids
            )
        )
    return False


def _manifest_from_required_capabilities(
    document: ParsedDocumentV1,
    required: tuple[str, ...],
) -> ParseManifestV1:
    evidence_by_capability = {
        item.capability: item for item in document.capability_evidence
    }
    evidenced = tuple(
        capability
        for capability in required
        if (evidence := evidence_by_capability.get(capability)) is not None
        and _capability_evidence_is_structural(document, evidence)
    )
    unsatisfied = tuple(item for item in required if item not in evidenced)
    return ParseManifestV1(
        contract="parse-manifest.v1",
        subject=document.subject,
        parser=document.parser,
        attempt=document.attempt,
        snapshot=document.snapshot,
        output_facts=document.output_facts,
        document_hash=document.document_hash,
        ordered_page_ids=tuple(item.page_id for item in document.pages),
        ordered_block_ids=tuple(item.block_id for item in document.blocks),
        ordered_table_ids=tuple(item.table_id for item in document.tables),
        ordered_cell_ids=tuple(item.cell_id for item in document.cells),
        element_counts=ParseElementCountsV1(
            pages=len(document.pages),
            blocks=len(document.blocks),
            tables=len(document.tables),
            cells=len(document.cells),
        ),
        required_capabilities=required,
        satisfied_capabilities=evidenced,
        unsatisfied_capabilities=unsatisfied,
        capability_evidence=document.capability_evidence,
        warnings=document.warnings,
        unsupported=document.unsupported,
    )


def build_parse_manifest(
    document: ParsedDocumentV1,
    material_profile: MaterialProfile,
) -> ParseManifestV1:
    """Build a deterministic manifest, preserving insufficiency for quality review."""

    if document.subject.material_profile_id != material_profile.profile_id:
        raise ParseContractError("material_profile_identity_mismatch")
    if document.subject.source_sha256 != material_profile.source.sha256:
        raise ParseContractError("source_identity_mismatch")
    return _manifest_from_required_capabilities(
        document,
        material_profile.required_parse_capabilities,
    )


class ParseQualityMeasuredFactsV1(_FrozenModel):
    threshold_version: Literal["parse-quality-structural.v1"]
    required_capabilities: tuple[NonBlankStr, ...]
    satisfied_capabilities: tuple[NonBlankStr, ...]
    unsatisfied_capabilities: tuple[NonBlankStr, ...]
    trigger_conditions: tuple[UpgradeTriggerCondition, ...]
    attempts_exhausted: bool


class ParseQualityReviewItemV1(_FrozenModel):
    review_type: Literal["parse_quality"] = "parse_quality"
    reason_code: QualityReason
    material_profile_id: NonBlankStr
    source_revision_id: NonBlankStr
    attempt_id: NonBlankStr
    manifest_hash: Sha256Hex


class ParseQualityDecisionV1(_FrozenModel):
    contract: Literal["parse-quality-decision.v1"]
    subject: ParseSubjectV1
    manifest_hash: Sha256Hex
    parse_policy_receipt: ParsePolicyReceipt | None
    measured_facts: ParseQualityMeasuredFactsV1
    decision: QualityDecision
    reason_codes: tuple[QualityReason, ...]
    admitted_attempt_id: NonBlankStr | None
    next_parser_profile_ref: ParserProfileRef | None
    review_item: ParseQualityReviewItemV1 | None

    @model_validator(mode="after")
    def require_decision_shape(self) -> Self:
        if self.decision == "ADMIT":
            valid = (
                not self.reason_codes
                and self.admitted_attempt_id is not None
                and self.next_parser_profile_ref is None
                and self.review_item is None
            )
        elif self.decision == "ESCALATE":
            valid = (
                bool(self.reason_codes)
                and self.admitted_attempt_id is None
                and self.next_parser_profile_ref is not None
                and self.review_item is None
            )
        else:
            valid = (
                bool(self.reason_codes)
                and self.admitted_attempt_id is None
                and self.next_parser_profile_ref is None
                and self.review_item is not None
            )
        if not valid or len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("invalid parse quality decision shape")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def decision_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"decision_hash"})
        return canonical_hash(PARSE_QUALITY_DECISION_OBJECT_TYPE, payload)


def _measured_facts(
    manifest: ParseManifestV1,
    receipt: ParsePolicyReceipt | None,
    *,
    trigger_conditions: tuple[UpgradeTriggerCondition, ...] = (),
    attempt_number: int,
) -> ParseQualityMeasuredFactsV1:
    return ParseQualityMeasuredFactsV1(
        threshold_version=PARSE_QUALITY_THRESHOLD_VERSION,
        required_capabilities=manifest.required_capabilities,
        satisfied_capabilities=manifest.satisfied_capabilities,
        unsatisfied_capabilities=manifest.unsatisfied_capabilities,
        trigger_conditions=trigger_conditions,
        attempts_exhausted=(
            receipt is None or attempt_number >= receipt.max_parser_attempts
        ),
    )


def _quality_decision(
    *,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    receipt: ParsePolicyReceipt | None,
    decision: QualityDecision,
    reason_codes: tuple[QualityReason, ...],
    trigger_conditions: tuple[UpgradeTriggerCondition, ...] = (),
) -> ParseQualityDecisionV1:
    review_item = None
    if decision == "BLOCK":
        review_item = ParseQualityReviewItemV1(
            reason_code=reason_codes[0],
            material_profile_id=document.subject.material_profile_id,
            source_revision_id=document.subject.source_revision_id,
            attempt_id=document.attempt.attempt_id,
            manifest_hash=manifest.manifest_hash,
        )
    return ParseQualityDecisionV1(
        contract="parse-quality-decision.v1",
        subject=document.subject,
        manifest_hash=manifest.manifest_hash,
        parse_policy_receipt=receipt,
        measured_facts=_measured_facts(
            manifest,
            receipt,
            trigger_conditions=trigger_conditions,
            attempt_number=document.attempt.attempt_number,
        ),
        decision=decision,
        reason_codes=reason_codes,
        admitted_attempt_id=(
            document.attempt.attempt_id if decision == "ADMIT" else None
        ),
        next_parser_profile_ref=(
            receipt.bounded_upgrade_profile_ref
            if decision == "ESCALATE" and receipt is not None
            else None
        ),
        review_item=review_item,
    )


def evaluate_parse_quality(
    *,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    material_profile_resolution: MaterialProfileResolution | None,
) -> ParseQualityDecisionV1:
    """Make one pure decision from an exact OpenSpec 052 binding authority."""

    resolution = None
    if material_profile_resolution is not None:
        try:
            resolution = MaterialProfileResolution.model_validate(
                material_profile_resolution
            )
        except ValidationError:
            resolution = None
    if resolution is None:
        return _quality_decision(
            document=document,
            manifest=manifest,
            receipt=None,
            decision="BLOCK",
            reason_codes=("unsupported_material_or_parser_profile",),
        )

    receipt = resolution.parse_policy_receipt
    if (
        document.subject.material_profile_id != receipt.material_profile_id
        or document.subject.material_profile_id != resolution.profile.profile_id
        or document.subject.material_profile_binding_hash != resolution.binding_hash
        or document.subject.space_id != resolution.request.space_id
        or document.subject.product_version_id != resolution.request.product_version
        or document.subject.source_sha256 != resolution.profile.source.sha256
        or resolution.request.source != resolution.profile.source
        or manifest.required_capabilities != receipt.required_parse_capabilities
    ):
        return _quality_decision(
            document=document,
            manifest=manifest,
            receipt=receipt,
            decision="BLOCK",
            reason_codes=("unsupported_material_or_parser_profile",),
        )

    expected_parser = (
        receipt.default_parser_profile_ref
        if document.attempt.attempt_number == 1
        else receipt.bounded_upgrade_profile_ref
    )
    if expected_parser is None or document.parser.parser_profile_ref != expected_parser:
        return _quality_decision(
            document=document,
            manifest=manifest,
            receipt=receipt,
            decision="BLOCK",
            reason_codes=("unsupported_material_or_parser_profile",),
        )

    outputs = (document.output_facts, manifest.output_facts)
    if any(
        output.privacy_policy_ref != receipt.privacy_policy_ref
        or output.output_policy_ref != receipt.output_policy_ref
        or output.body_text_included
        or output.secrets_included
        or output.absolute_paths_included
        or output.unknown_vendor_fields_included
        for output in outputs
    ):
        return _quality_decision(
            document=document,
            manifest=manifest,
            receipt=receipt,
            decision="BLOCK",
            reason_codes=("privacy_or_output_policy_violation",),
        )

    if (
        manifest.subject != document.subject
        or manifest.parser != document.parser
        or manifest.attempt != document.attempt
        or manifest.snapshot != document.snapshot
    ):
        return _quality_decision(
            document=document,
            manifest=manifest,
            receipt=receipt,
            decision="BLOCK",
            reason_codes=("identity_revision_parser_drift",),
        )

    expected = _manifest_from_required_capabilities(
        document,
        receipt.required_parse_capabilities,
    )
    if manifest != expected or not document.snapshot.pagination_complete:
        trigger: tuple[UpgradeTriggerCondition, ...] = (
            "manifest_digest_or_count_mismatch",
        )
        if (
            document.attempt.attempt_number == 1
            and receipt.bounded_upgrade_profile_ref is not None
            and trigger[0] in receipt.upgrade_trigger_conditions
        ):
            return _quality_decision(
                document=document,
                manifest=manifest,
                receipt=receipt,
                decision="ESCALATE",
                reason_codes=("manifest_digest_or_count_mismatch",),
                trigger_conditions=trigger,
            )
        return _quality_decision(
            document=document,
            manifest=manifest,
            receipt=receipt,
            decision="BLOCK",
            reason_codes=("manifest_digest_or_count_mismatch",),
            trigger_conditions=trigger,
        )

    if manifest.unsatisfied_capabilities:
        reason: QualityReason = (
            "table_grid_or_span_incomplete"
            if any(
                capability
                in {
                    "table_grid",
                    "header_hierarchy",
                    "row_column_indices",
                    "merged_cells",
                    "cross_page_tables",
                }
                for capability in manifest.unsatisfied_capabilities
            )
            else "locator_invalid_or_required_structure_missing"
        )
        trigger = ("required_capability_missing",)
        may_escalate = (
            document.attempt.attempt_number == 1
            and receipt.bounded_upgrade_profile_ref is not None
            and receipt.max_parser_attempts == 2
            and trigger[0] in receipt.upgrade_trigger_conditions
        )
        return _quality_decision(
            document=document,
            manifest=manifest,
            receipt=receipt,
            decision="ESCALATE" if may_escalate else "BLOCK",
            reason_codes=(reason,),
            trigger_conditions=trigger,
        )

    return _quality_decision(
        document=document,
        manifest=manifest,
        receipt=receipt,
        decision="ADMIT",
        reason_codes=(),
    )
