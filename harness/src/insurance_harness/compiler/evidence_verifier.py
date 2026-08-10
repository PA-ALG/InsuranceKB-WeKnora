"""Deterministic Evidence verification and one bounded repair for OpenSpec 057.

This module is a pure domain boundary. It consumes the parser-neutral 053
contract, performs no I/O, and deliberately does not import the mutable 054
attempt/receipt implementation.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import date
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
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.extraction_receipts import (
    AttemptReceiptV1,
    ReceiptChainV1,
)
from insurance_harness.compiler.parsed_documents import (
    ParsedDocumentV1,
    ParseManifestV1,
)

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=4096, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]


def _reject_float(value: object) -> object:
    if isinstance(value, float):
        raise ValueError("binary float is forbidden; use a decimal string or integer")
    return value


CanonicalDecimal = Annotated[Decimal, BeforeValidator(_reject_float)]
TriState = Literal["present", "absent_explicitly", "unknown"]
LocatorKind = Literal["page", "block", "table", "cell"]
ValueKind = Literal[
    "number",
    "number_unit",
    "enum",
    "date",
    "range",
    "arithmetic",
]
VerificationStatus = Literal["PASS", "FAIL", "GAP"]
RepairOutcome = Literal["COMPLETE", "REPAIR", "EXHAUSTED"]

VERIFICATION_BATCH_OBJECT_TYPE: Final[str] = "evidence-verification-batch.v1"
TARGETED_REPAIR_PLAN_OBJECT_TYPE: Final[str] = "targeted-repair-plan.v1"
REPAIR_RESOLUTION_OBJECT_TYPE: Final[str] = "targeted-repair-resolution.v1"
FREEFORM_EVIDENCE_BINDING_OBJECT_TYPE: Final[str] = (
    "freeform-arm-evidence-binding-receipt.v1"
)
SIGNED_DECIMAL_PATTERN: Final[str] = r"[+-]?\d+(?:\.\d+)?"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class VerifierContractError(ValueError):
    """Typed failure for malformed verifier or repair composition."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_tuple(values: tuple[str, ...], *, allow_empty: bool = False) -> bool:
    return (
        (allow_empty or bool(values))
        and values == tuple(sorted(values))
        and len(values) == len(set(values))
    )


class CandidateValueV1(_FrozenModel):
    """A fixed union expressed as one bounded DTO, not a dynamic rule language."""

    kind: ValueKind
    number: CanonicalDecimal | None = None
    unit: NonBlankStr | None = None
    enum_value: NonBlankStr | None = None
    date_value: NonBlankStr | None = None
    lower: CanonicalDecimal | None = None
    upper: CanonicalDecimal | None = None
    operator: Literal["sum", "difference"] | None = None
    operands: tuple[CanonicalDecimal, ...] = ()
    result: CanonicalDecimal | None = None

    @model_validator(mode="after")
    def require_exact_variant_shape(self) -> Self:
        present = {
            "number": self.number is not None,
            "unit": self.unit is not None,
            "enum_value": self.enum_value is not None,
            "date_value": self.date_value is not None,
            "lower": self.lower is not None,
            "upper": self.upper is not None,
            "operator": self.operator is not None,
            "operands": bool(self.operands),
            "result": self.result is not None,
        }
        allowed: dict[ValueKind, frozenset[str]] = {
            "number": frozenset({"number"}),
            "number_unit": frozenset({"number", "unit"}),
            "enum": frozenset({"enum_value"}),
            "date": frozenset({"date_value"}),
            "range": frozenset({"lower", "upper"}),
            "arithmetic": frozenset({"operator", "operands", "result"}),
        }
        actual = frozenset(name for name, included in present.items() if included)
        if actual != allowed[self.kind]:
            raise ValueError("invalid_candidate_value_shape")
        if self.kind == "arithmetic" and len(self.operands) < 2:
            raise ValueError("arithmetic requires at least two operands")
        return self


def value_snapshot(value: CandidateValueV1 | None) -> str:
    """Return the canonical immutable value snapshot carried by Evidence."""

    if value is None:
        return "null"
    return json.dumps(
        value.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class EvidenceLocatorSnapshotV1(_FrozenModel):
    subject_type: LocatorKind
    subject_ref: NonBlankStr
    page_number: Annotated[StrictInt, Field(gt=0)]
    parent_refs: tuple[NonBlankStr, ...]
    content_snapshot: NonBlankStr
    content_snapshot_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_content_snapshot_hash(self) -> Self:
        if self.content_snapshot_sha256 != _sha256_text(self.content_snapshot):
            raise ValueError("content_snapshot_hash_mismatch")
        if len(self.parent_refs) != len(set(self.parent_refs)):
            raise ValueError("locator parent refs must be unique")
        return self


class EvidenceSupportScopeV1(_FrozenModel):
    product_version_id: NonBlankStr
    subject_id: NonBlankStr
    condition_ids: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def require_canonical_conditions(self) -> Self:
        if not _canonical_tuple(self.condition_ids, allow_empty=True):
            raise ValueError("condition ids must be canonical and unique")
        return self


class EvidenceSnapshotV1(_FrozenModel):
    field_id: NonBlankStr
    product_version_id: NonBlankStr
    source_revision_id: NonBlankStr
    parse_attempt_id: NonBlankStr
    parsed_document_hash: Sha256Hex
    parse_manifest_hash: Sha256Hex
    locator: EvidenceLocatorSnapshotV1
    quote_snapshot: NonBlankStr
    quote_snapshot_sha256: Sha256Hex
    value_snapshot: NonBlankStr
    value_snapshot_sha256: Sha256Hex
    support_scope: EvidenceSupportScopeV1

    @model_validator(mode="after")
    def require_snapshot_hashes(self) -> Self:
        if self.quote_snapshot_sha256 != _sha256_text(self.quote_snapshot):
            raise ValueError("quote_snapshot_hash_mismatch")
        if self.value_snapshot_sha256 != _sha256_text(self.value_snapshot):
            raise ValueError("value_snapshot_hash_mismatch")
        return self


class FreeformEvidenceV1(_FrozenModel):
    """Mechanical Evidence custody for a freeform field value.

    The value itself is intentionally absent from this DTO: 057 proves that the
    quote belongs to an exact parsed locator, while 061 owns semantic scoring.
    """

    field_id: NonBlankStr
    source_sha256: Sha256Hex
    source_revision_id: NonBlankStr
    parse_attempt_id: NonBlankStr
    parsed_document_hash: Sha256Hex
    parse_manifest_hash: Sha256Hex
    page_number: Annotated[StrictInt, Field(gt=0)]
    block_id: NonBlankStr | None = None
    table_id: NonBlankStr | None = None
    cell_id: NonBlankStr | None = None
    row_index: NonNegativeInt | None = None
    column_index: NonNegativeInt | None = None
    header_snapshot: NonBlankStr | None = None
    row_span: Annotated[StrictInt, Field(gt=0)] | None = None
    column_span: Annotated[StrictInt, Field(gt=0)] | None = None
    locator: EvidenceLocatorSnapshotV1
    quote_snapshot: NonBlankStr
    quote_snapshot_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_quote_snapshot_hash(self) -> Self:
        if self.quote_snapshot_sha256 != _sha256_text(self.quote_snapshot):
            raise ValueError("quote_snapshot_hash_mismatch")
        cell_shape = (
            self.table_id,
            self.row_index,
            self.column_index,
            self.row_span,
            self.column_span,
        )
        if self.cell_id is not None and any(item is None for item in cell_shape):
            raise ValueError("cell Evidence requires complete table coordinates")
        if self.cell_id is None and any(item is not None for item in cell_shape[1:]):
            raise ValueError("cell coordinates require a cell Evidence declaration")
        if self.header_snapshot is not None and self.table_id is None:
            raise ValueError("header snapshot requires a table Evidence declaration")
        return self


def _freeform_evidence_key(item: FreeformEvidenceV1) -> tuple[str, ...]:
    def optional_int(value: int | None) -> str:
        return "" if value is None else f"{value:020d}"

    return (
        item.source_revision_id,
        item.parse_attempt_id,
        item.parsed_document_hash,
        item.parse_manifest_hash,
        item.source_sha256,
        f"{item.page_number:020d}",
        item.block_id or "",
        item.table_id or "",
        item.cell_id or "",
        optional_int(item.row_index),
        optional_int(item.column_index),
        item.header_snapshot or "",
        optional_int(item.row_span),
        optional_int(item.column_span),
        item.locator.subject_type,
        item.locator.subject_ref,
        item.quote_snapshot_sha256,
    )


class FreeformFieldOutputV1(_FrozenModel):
    product_version_id: NonBlankStr
    field_id: NonBlankStr
    state: TriState
    value_snapshot: NonBlankStr | None
    evidence: tuple[FreeformEvidenceV1, ...]

    @model_validator(mode="after")
    def require_exact_field_shape(self) -> Self:
        if self.state == "unknown":
            if self.value_snapshot is not None or self.evidence:
                raise ValueError("unknown freeform field cannot carry value or Evidence")
            return self
        if self.value_snapshot is None or not self.evidence:
            raise ValueError("known freeform field requires value and Evidence")
        if any(item.field_id != self.field_id for item in self.evidence):
            raise ValueError("freeform Evidence field mismatch")
        keys = tuple(_freeform_evidence_key(item) for item in self.evidence)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("freeform Evidence must be canonical and unique")
        return self


class FreeformDocumentBindingV1(_FrozenModel):
    source_id: NonBlankStr
    source_revision_id: NonBlankStr
    source_sha256: Sha256Hex
    parse_attempt_id: NonBlankStr
    parsed_document_hash: Sha256Hex
    parse_manifest_hash: Sha256Hex


def _freeform_document_key(item: FreeformDocumentBindingV1) -> tuple[str, ...]:
    return (
        item.source_revision_id,
        item.parse_attempt_id,
        item.parsed_document_hash,
        item.parse_manifest_hash,
    )


def _freeform_receipt_payload(
    *,
    contract: str,
    product_version_id: str,
    field_id: str,
    state: TriState,
    value_snapshot: str | None,
    documents: tuple[FreeformDocumentBindingV1, ...],
    evidence: tuple[FreeformEvidenceV1, ...],
) -> dict[str, object]:
    return {
        "contract": contract,
        "product_version_id": product_version_id,
        "field_id": field_id,
        "state": state,
        "value_snapshot": value_snapshot,
        "documents": tuple(item.model_dump(mode="python") for item in documents),
        "evidence": tuple(item.model_dump(mode="python") for item in evidence),
    }


class FreeformEvidenceBindingReceiptV1(_FrozenModel):
    contract: Literal["freeform-arm-evidence-binding-receipt.v1"]
    product_version_id: NonBlankStr
    field_id: NonBlankStr
    state: TriState
    value_snapshot: NonBlankStr | None
    documents: tuple[FreeformDocumentBindingV1, ...]
    evidence: tuple[FreeformEvidenceV1, ...]
    receipt_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_receipt_hash(self) -> Self:
        evidence_keys = tuple(_freeform_evidence_key(item) for item in self.evidence)
        document_keys = tuple(_freeform_document_key(item) for item in self.documents)
        evidence_members = {item[:4] for item in evidence_keys}
        if self.state == "unknown":
            if self.value_snapshot is not None or self.evidence or self.documents:
                raise ValueError("unknown freeform receipt cannot carry custody")
        elif (
            self.value_snapshot is None
            or not self.evidence
            or not self.documents
            or any(item.field_id != self.field_id for item in self.evidence)
            or evidence_keys != tuple(sorted(evidence_keys))
            or len(evidence_keys) != len(set(evidence_keys))
            or document_keys != tuple(sorted(document_keys))
            or len(document_keys) != len(set(document_keys))
            or evidence_members != set(document_keys)
        ):
            raise ValueError("freeform receipt custody mismatch")
        expected = canonical_hash(
            FREEFORM_EVIDENCE_BINDING_OBJECT_TYPE,
            _freeform_receipt_payload(
                contract=self.contract,
                product_version_id=self.product_version_id,
                field_id=self.field_id,
                state=self.state,
                value_snapshot=self.value_snapshot,
                documents=self.documents,
                evidence=self.evidence,
            ),
        )
        if self.receipt_hash != expected:
            raise ValueError("freeform_receipt_hash_mismatch")
        return self


class FieldCandidateV1(_FrozenModel):
    field_id: NonBlankStr
    product_version_id: NonBlankStr
    subject_id: NonBlankStr
    condition_ids: tuple[NonBlankStr, ...]
    tri_state: TriState
    value: CandidateValueV1 | None
    evidence: tuple[EvidenceSnapshotV1, ...]

    @model_validator(mode="after")
    def require_tri_state_shape(self) -> Self:
        if not _canonical_tuple(self.condition_ids, allow_empty=True):
            raise ValueError("condition ids must be canonical and unique")
        if self.tri_state == "present" and self.value is None:
            raise ValueError("present candidate requires a value")
        if self.tri_state != "present" and self.value is not None:
            raise ValueError("non-present candidate cannot carry a value")
        if self.tri_state == "unknown" and self.evidence:
            raise ValueError("unknown candidate cannot carry Evidence")
        if len({item.locator.subject_ref for item in self.evidence}) != len(self.evidence):
            raise ValueError("Evidence locator refs must be unique")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def candidate_snapshot_hash(self) -> str:
        return canonical_hash(
            "verified-field-candidate.v1",
            self.model_dump(mode="python", exclude={"candidate_snapshot_hash"}),
        )


class FieldRuleV1(_FrozenModel):
    field_id: NonBlankStr
    value_kind: ValueKind
    expected_unit: NonBlankStr | None = None
    allowed_values: tuple[NonBlankStr, ...] = ()
    minimum: CanonicalDecimal | None = None
    maximum: CanonicalDecimal | None = None
    absence_markers: tuple[NonBlankStr, ...] = ()
    allow_absent: bool

    @model_validator(mode="after")
    def require_bounded_rule_shape(self) -> Self:
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("invalid rule bounds")
        if self.value_kind == "number_unit" and self.expected_unit is None:
            raise ValueError("number_unit rule requires expected_unit")
        if self.value_kind != "number_unit" and self.expected_unit is not None:
            raise ValueError("expected_unit only applies to number_unit")
        if self.value_kind == "enum":
            if not _canonical_tuple(self.allowed_values):
                raise ValueError("enum rule requires canonical allowed values")
        elif self.allowed_values:
            raise ValueError("allowed_values only apply to enum")
        if self.allow_absent:
            if not _canonical_tuple(self.absence_markers):
                raise ValueError("allowed absence requires canonical explicit markers")
        elif self.absence_markers:
            raise ValueError("absence markers require allow_absent")
        return self


class FieldVerificationV1(_FrozenModel):
    field_id: NonBlankStr
    status: VerificationStatus
    reason_codes: tuple[NonBlankStr, ...]
    candidate_snapshot_hash: Sha256Hex

    @model_validator(mode="after")
    def require_typed_status(self) -> Self:
        if (self.status == "PASS") != (not self.reason_codes):
            raise ValueError("verification status/reason mismatch")
        return self


class VerificationBatchV1(_FrozenModel):
    contract: Literal["evidence-verification-batch.v1"]
    product_version_id: NonBlankStr
    source_revision_id: NonBlankStr
    parse_attempt_id: NonBlankStr
    parsed_document_hash: Sha256Hex
    parse_manifest_hash: Sha256Hex
    results: tuple[FieldVerificationV1, ...]

    @model_validator(mode="after")
    def require_canonical_result_fields(self) -> Self:
        fields = tuple(item.field_id for item in self.results)
        if not _canonical_tuple(fields):
            raise ValueError("verification results must be canonical and unique")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def verification_hash(self) -> str:
        return canonical_hash(
            VERIFICATION_BATCH_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"verification_hash"}),
        )


class GapV1(_FrozenModel):
    field_id: NonBlankStr
    reason_codes: tuple[NonBlankStr, ...]


class EvidenceReviewItemV1(_FrozenModel):
    review_type: Literal["evidence_verification"] = "evidence_verification"
    field_id: NonBlankStr
    reason_code: NonBlankStr
    parent_verification_hash: Sha256Hex


class RepairBudgetV1(_FrozenModel):
    max_targeted_repairs: Literal[0, 1]


class ApprovedLocatorSetV1(_FrozenModel):
    field_id: NonBlankStr
    locator_refs: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def require_canonical_locator_refs(self) -> Self:
        if not _canonical_tuple(self.locator_refs):
            raise ValueError("approved locator refs must be canonical and unique")
        return self


class TargetedRepairPlanV1(_FrozenModel):
    contract: Literal["targeted-repair-plan.v1"]
    parent_verification_hash: Sha256Hex
    repair_number: Literal[1]
    field_ids: tuple[NonBlankStr, ...]
    approved_locators: tuple[ApprovedLocatorSetV1, ...]

    @model_validator(mode="after")
    def require_exact_locator_bijection(self) -> Self:
        fields = tuple(item.field_id for item in self.approved_locators)
        if not _canonical_tuple(self.field_ids) or fields != self.field_ids:
            raise ValueError("repair locator/field bijection mismatch")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def plan_hash(self) -> str:
        return canonical_hash(
            TARGETED_REPAIR_PLAN_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"plan_hash"}),
        )


class TargetedRepairDecisionV1(_FrozenModel):
    outcome: RepairOutcome
    plan: TargetedRepairPlanV1 | None
    gaps: tuple[GapV1, ...]
    review_items: tuple[EvidenceReviewItemV1, ...]

    @model_validator(mode="after")
    def require_decision_shape(self) -> Self:
        if self.outcome == "REPAIR":
            if self.plan is None or self.gaps or self.review_items:
                raise ValueError("invalid repair decision")
        elif self.plan is not None:
            raise ValueError("terminal repair decision cannot carry plan")
        return self


class RepairResolutionV1(_FrozenModel):
    contract: Literal["targeted-repair-resolution.v1"]
    parent_verification_hash: Sha256Hex
    repair_plan_hash: Sha256Hex
    results: tuple[FieldVerificationV1, ...]
    gaps: tuple[GapV1, ...]
    review_items: tuple[EvidenceReviewItemV1, ...]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def resolution_hash(self) -> str:
        return canonical_hash(
            REPAIR_RESOLUTION_OBJECT_TYPE,
            self.model_dump(mode="python", exclude={"resolution_hash"}),
        )


def bind_054_attempt_receipt(
    *,
    chain: ReceiptChainV1,
    verification: VerificationBatchV1,
) -> AttemptReceiptV1:
    """Bind one exact 054 receipt to 057 verification without minting authority."""

    task = chain.task
    receipt = chain.receipts[-1]
    results = verification.results
    if (
        task.product_version_id != verification.product_version_id
        or task.source_revision_id != verification.source_revision_id
        or task.input_refs.parsed_document.object_type != "parsed-document.v1"
        or task.input_refs.parsed_document.artifact_hash
        != verification.parsed_document_hash
        or task.input_refs.parse_manifest.object_type != "parse-manifest.v1"
        or task.input_refs.parse_manifest.artifact_hash != verification.parse_manifest_hash
        or receipt.attempted_fields != tuple(item.field_id for item in results)
    ):
        raise VerifierContractError("verification_receipt_binding_mismatch")
    for outcome, result in zip(receipt.field_outcomes, results, strict=True):
        if result.status == "PASS":
            if (
                outcome.status != "candidate"
                or outcome.candidate_ref is None
                or outcome.candidate_ref.artifact_hash
                != result.candidate_snapshot_hash
            ):
                raise VerifierContractError("verification_receipt_binding_mismatch")
        elif (
            outcome.status == "candidate"
            or outcome.candidate_ref is not None
            or outcome.reason_code != result.reason_codes[0]
        ):
            raise VerifierContractError("verification_receipt_binding_mismatch")
    return receipt


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.translate(
        {
            ord("。"): ".",
            ord("、"): ",",
            ord("“"): '"',
            ord("”"): '"',
            ord("—"): "-",
            ord("【"): "[",
            ord("】"): "]",
        }
    ).casefold()


def _quote_occurs(quote: str, content: str) -> bool:
    normalized = _normalize_text(quote)
    return bool(normalized) and normalized in _normalize_text(content)


def _document_manifest_match(document: ParsedDocumentV1, manifest: ParseManifestV1) -> bool:
    return (
        manifest.subject == document.subject
        and manifest.parser == document.parser
        and manifest.attempt == document.attempt
        and manifest.snapshot == document.snapshot
        and manifest.document_hash == document.document_hash
    )


def _locator_fact(
    document: ParsedDocumentV1, subject_ref: str
) -> tuple[LocatorKind, int, tuple[str, ...], str] | None:
    page_id_by_number = {item.locator.page_number: item.page_id for item in document.pages}
    for page in document.pages:
        if page.page_id == subject_ref:
            return "page", page.locator.page_number, (), page.content_hash
    for block in document.blocks:
        if block.block_id == subject_ref:
            page_id = page_id_by_number[block.locator.page_number]
            return "block", block.locator.page_number, (page_id,), block.content_hash
    for table in document.tables:
        if table.table_id == subject_ref:
            page_id = page_id_by_number[table.locator.page_number]
            return "table", table.locator.page_number, (page_id,), table.content_hash
    for cell in document.cells:
        if cell.cell_id == subject_ref:
            page_id = page_id_by_number[cell.locator.page_number]
            return (
                "cell",
                cell.locator.page_number,
                (page_id, cell.table_id),
                cell.content_hash,
            )
    return None


def _mineru_snapshot_hash(kind: LocatorKind, content: str) -> str | None:
    domain = "block-content" if kind == "block" else "cell-content" if kind == "cell" else None
    if domain is None:
        return None
    digest = hashlib.sha256()
    digest.update(f"mineru-060:{domain}".encode())
    digest.update(b"\0")
    digest.update(content.encode())
    return digest.hexdigest()


def _content_snapshot_matches(
    *,
    document: ParsedDocumentV1,
    kind: LocatorKind,
    content_snapshot: str,
    content_snapshot_sha256: str,
    parsed_content_hash: str,
) -> bool:
    """Replay parser-owned content hashes without weakening plaintext custody."""

    if _sha256_text(content_snapshot) != content_snapshot_sha256:
        return False
    is_exact_mineru = (
        document.parser.parser_id == "mineru-cloud-pipeline"
        and document.parser.parser_build_id
        == "NewMinerUCloudReader/mineru-native-structure.v1"
    )
    if is_exact_mineru:
        return _mineru_snapshot_hash(kind, content_snapshot) == parsed_content_hash
    return content_snapshot_sha256 == parsed_content_hash


def _validate_freeform_field_output(value: FreeformFieldOutputV1) -> FreeformFieldOutputV1:
    try:
        return FreeformFieldOutputV1.model_validate(value.model_dump(mode="python"))
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise VerifierContractError("freeform_field_output_invalid") from None


def _validate_parsed_pair(
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
) -> tuple[ParsedDocumentV1, ParseManifestV1]:
    try:
        exact_document = ParsedDocumentV1.model_validate(
            document.model_dump(mode="python", exclude={"document_hash"})
        )
        exact_manifest = ParseManifestV1.model_validate(
            manifest.model_dump(mode="python", exclude={"manifest_hash"})
        )
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise VerifierContractError("freeform_parsed_pair_invalid") from None
    if not _document_manifest_match(exact_document, exact_manifest):
        raise VerifierContractError("freeform_document_manifest_mismatch")
    return exact_document, exact_manifest


def _freeform_binding_from_pair(
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
) -> FreeformDocumentBindingV1:
    return FreeformDocumentBindingV1(
        source_id=document.subject.source_id,
        source_revision_id=document.subject.source_revision_id,
        source_sha256=document.subject.source_sha256,
        parse_attempt_id=document.attempt.attempt_id,
        parsed_document_hash=document.document_hash,
        parse_manifest_hash=manifest.manifest_hash,
    )


def _verify_freeform_evidence(
    *,
    evidence: FreeformEvidenceV1,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
) -> None:
    if (
        evidence.source_sha256 != document.subject.source_sha256
        or evidence.source_revision_id != document.subject.source_revision_id
        or evidence.parse_attempt_id != document.attempt.attempt_id
        or evidence.parsed_document_hash != document.document_hash
        or evidence.parse_manifest_hash != manifest.manifest_hash
    ):
        raise VerifierContractError("freeform_evidence_identity_mismatch")
    fact = _locator_fact(document, evidence.locator.subject_ref)
    if fact is None:
        raise VerifierContractError("freeform_locator_not_found")
    kind, page_number, parent_refs, content_hash = fact
    if evidence.locator.subject_type != kind:
        raise VerifierContractError("freeform_locator_kind_mismatch")
    if evidence.locator.page_number != page_number:
        raise VerifierContractError("freeform_locator_page_mismatch")
    if evidence.locator.parent_refs != parent_refs:
        raise VerifierContractError("freeform_locator_parent_mismatch")
    if not _content_snapshot_matches(
        document=document,
        kind=kind,
        content_snapshot=evidence.locator.content_snapshot,
        content_snapshot_sha256=evidence.locator.content_snapshot_sha256,
        parsed_content_hash=content_hash,
    ):
        raise VerifierContractError("freeform_content_snapshot_mismatch")
    if not _quote_occurs(evidence.quote_snapshot, evidence.locator.content_snapshot):
        raise VerifierContractError("freeform_quote_not_found")
    if evidence.page_number != page_number:
        raise VerifierContractError("freeform_arm_locator_mismatch")

    blocks = {item.block_id: item for item in document.blocks}
    tables = {item.table_id: item for item in document.tables}
    cells = {item.cell_id: item for item in document.cells}
    if evidence.block_id is not None:
        block = blocks.get(evidence.block_id)
        if block is None or block.locator.page_number != evidence.page_number:
            raise VerifierContractError("freeform_arm_locator_mismatch")
    if evidence.cell_id is not None:
        cell = cells.get(evidence.cell_id)
        table = tables.get(evidence.table_id or "")
        if (
            cell is None
            or table is None
            or evidence.locator.subject_type != "cell"
            or evidence.locator.subject_ref != cell.cell_id
            or cell.table_id != table.table_id
            or cell.locator.page_number != evidence.page_number
            or table.locator.page_number != evidence.page_number
            or cell.locator.row_index != evidence.row_index
            or cell.locator.column_index != evidence.column_index
            or cell.locator.row_span != evidence.row_span
            or cell.locator.column_span != evidence.column_span
        ):
            raise VerifierContractError("freeform_arm_locator_mismatch")
    elif evidence.table_id is not None:
        table = tables.get(evidence.table_id)
        if (
            table is None
            or table.locator.page_number != evidence.page_number
            or evidence.locator.subject_type != "table"
            or evidence.locator.subject_ref != table.table_id
        ):
            raise VerifierContractError("freeform_arm_locator_mismatch")
    elif evidence.block_id is not None:
        if (
            evidence.locator.subject_type != "block"
            or evidence.locator.subject_ref != evidence.block_id
        ):
            raise VerifierContractError("freeform_arm_locator_mismatch")
    else:
        page_ids = {
            item.locator.page_number: item.page_id for item in document.pages
        }
        if (
            evidence.locator.subject_type != "page"
            or evidence.locator.subject_ref != page_ids.get(evidence.page_number)
        ):
            raise VerifierContractError("freeform_arm_locator_mismatch")

    if evidence.header_snapshot is not None:
        table = tables.get(evidence.table_id or "")
        header_hash = _sha256_text(evidence.header_snapshot)
        if table is None or not any(
            cells[cell_id].content_hash == header_hash
            for cell_id in table.header_cell_ids
            if cell_id in cells
        ):
            raise VerifierContractError("freeform_header_snapshot_mismatch")


def bind_freeform_arm_evidence(
    *,
    field_output: FreeformFieldOutputV1,
    documents: tuple[ParsedDocumentV1, ...],
    manifests: tuple[ParseManifestV1, ...],
) -> FreeformEvidenceBindingReceiptV1:
    """Bind exact parsed custody without judging freeform semantic entailment."""

    output = _validate_freeform_field_output(field_output)
    if output.state == "unknown":
        if documents or manifests:
            raise VerifierContractError("freeform_unknown_custody_forbidden")
        bindings: tuple[FreeformDocumentBindingV1, ...] = ()
    else:
        if not documents or len(documents) != len(manifests):
            raise VerifierContractError("freeform_document_membership_mismatch")
        pairs = tuple(
            _validate_parsed_pair(document, manifest)
            for document, manifest in zip(documents, manifests, strict=True)
        )
        if any(
            document.subject.product_version_id != output.product_version_id
            for document, _ in pairs
        ):
            raise VerifierContractError("freeform_product_version_mismatch")
        bindings = tuple(
            _freeform_binding_from_pair(document, manifest)
            for document, manifest in pairs
        )
        document_keys = tuple(_freeform_document_key(item) for item in bindings)
        if (
            document_keys != tuple(sorted(document_keys))
            or len(document_keys) != len(set(document_keys))
        ):
            raise VerifierContractError("freeform_document_order_invalid")
        pairs_by_key = dict(zip(document_keys, pairs, strict=True))
        evidence_member_keys = {
            (
                item.source_revision_id,
                item.parse_attempt_id,
                item.parsed_document_hash,
                item.parse_manifest_hash,
            )
            for item in output.evidence
        }
        if evidence_member_keys != set(document_keys):
            raise VerifierContractError("freeform_document_membership_mismatch")
        for item in output.evidence:
            member_key = (
                item.source_revision_id,
                item.parse_attempt_id,
                item.parsed_document_hash,
                item.parse_manifest_hash,
            )
            document, manifest = pairs_by_key[member_key]
            _verify_freeform_evidence(
                evidence=item,
                document=document,
                manifest=manifest,
            )

    payload = _freeform_receipt_payload(
        contract=FREEFORM_EVIDENCE_BINDING_OBJECT_TYPE,
        product_version_id=output.product_version_id,
        field_id=output.field_id,
        state=output.state,
        value_snapshot=output.value_snapshot,
        documents=bindings,
        evidence=output.evidence,
    )
    return FreeformEvidenceBindingReceiptV1(
        contract="freeform-arm-evidence-binding-receipt.v1",
        product_version_id=output.product_version_id,
        field_id=output.field_id,
        state=output.state,
        value_snapshot=output.value_snapshot,
        documents=bindings,
        evidence=output.evidence,
        receipt_hash=canonical_hash(FREEFORM_EVIDENCE_BINDING_OBJECT_TYPE, payload),
    )


def replay_freeform_arm_evidence_binding(
    *,
    receipt: FreeformEvidenceBindingReceiptV1,
    documents: tuple[ParsedDocumentV1, ...],
    manifests: tuple[ParseManifestV1, ...],
) -> FreeformEvidenceBindingReceiptV1:
    """Recompute one receipt from its exact field and parsed custody."""

    try:
        payload = _freeform_receipt_payload(
            contract=receipt.contract,
            product_version_id=receipt.product_version_id,
            field_id=receipt.field_id,
            state=receipt.state,
            value_snapshot=receipt.value_snapshot,
            documents=receipt.documents,
            evidence=receipt.evidence,
        )
        expected_hash = canonical_hash(FREEFORM_EVIDENCE_BINDING_OBJECT_TYPE, payload)
    except (AttributeError, TypeError, ValueError):
        raise VerifierContractError("freeform_receipt_invalid") from None
    if receipt.receipt_hash != expected_hash:
        raise VerifierContractError("freeform_receipt_hash_mismatch")
    try:
        exact_receipt = FreeformEvidenceBindingReceiptV1.model_validate(
            receipt.model_dump(mode="python")
        )
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise VerifierContractError("freeform_receipt_invalid") from None
    rebound = bind_freeform_arm_evidence(
        field_output=FreeformFieldOutputV1(
            product_version_id=exact_receipt.product_version_id,
            field_id=exact_receipt.field_id,
            state=exact_receipt.state,
            value_snapshot=exact_receipt.value_snapshot,
            evidence=exact_receipt.evidence,
        ),
        documents=documents,
        manifests=manifests,
    )
    if rebound != exact_receipt:
        raise VerifierContractError("freeform_receipt_binding_mismatch")
    return exact_receipt


def _verify_evidence(
    *,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    candidate: FieldCandidateV1,
    evidence: EvidenceSnapshotV1,
) -> str | None:
    if evidence.field_id != candidate.field_id:
        return "evidence_field_mismatch"
    if (
        evidence.product_version_id != document.subject.product_version_id
        or candidate.product_version_id != document.subject.product_version_id
        or evidence.source_revision_id != document.subject.source_revision_id
        or evidence.parse_attempt_id != document.attempt.attempt_id
        or evidence.parsed_document_hash != document.document_hash
        or evidence.parse_manifest_hash != manifest.manifest_hash
    ):
        return "evidence_identity_mismatch"
    fact = _locator_fact(document, evidence.locator.subject_ref)
    if fact is None:
        return "locator_not_found"
    kind, page_number, parent_refs, content_hash = fact
    if evidence.locator.subject_type != kind:
        return "locator_kind_mismatch"
    if evidence.locator.page_number != page_number:
        return "locator_page_mismatch"
    if evidence.locator.parent_refs != parent_refs:
        return "locator_parent_mismatch"
    if not _content_snapshot_matches(
        document=document,
        kind=kind,
        content_snapshot=evidence.locator.content_snapshot,
        content_snapshot_sha256=evidence.locator.content_snapshot_sha256,
        parsed_content_hash=content_hash,
    ):
        return "content_snapshot_mismatch"
    if not _quote_occurs(evidence.quote_snapshot, evidence.locator.content_snapshot):
        return "quote_not_found"
    expected_snapshot = value_snapshot(candidate.value)
    if evidence.value_snapshot != expected_snapshot:
        return "value_snapshot_mismatch"
    if evidence.support_scope.product_version_id != candidate.product_version_id:
        return "semantic_version_mismatch"
    if evidence.support_scope.subject_id != candidate.subject_id:
        return "semantic_subject_mismatch"
    if evidence.support_scope.condition_ids != candidate.condition_ids:
        return "semantic_condition_mismatch"
    return None


def _value_rule_reason(value: CandidateValueV1, rule: FieldRuleV1) -> str | None:
    if value.kind != rule.value_kind:
        return "value_kind_mismatch"
    if value.kind in {"number", "number_unit"}:
        assert value.number is not None
        if rule.minimum is not None and value.number < rule.minimum:
            return "numeric_out_of_range"
        if rule.maximum is not None and value.number > rule.maximum:
            return "numeric_out_of_range"
        if value.kind == "number_unit" and value.unit != rule.expected_unit:
            return "unit_mismatch"
    elif value.kind == "enum":
        if value.enum_value not in rule.allowed_values:
            return "enum_not_allowed"
    elif value.kind == "date":
        assert value.date_value is not None
        try:
            date.fromisoformat(value.date_value)
        except ValueError:
            return "date_invalid"
    elif value.kind == "range":
        assert value.lower is not None and value.upper is not None
        if value.lower > value.upper:
            return "range_invalid"
        if (
            rule.minimum is not None
            and value.lower < rule.minimum
            or rule.maximum is not None
            and value.upper > rule.maximum
        ):
            return "range_out_of_bounds"
    else:
        assert value.operator is not None and value.result is not None
        expected = (
            sum(value.operands, start=Decimal(0))
            if value.operator == "sum"
            else value.operands[0] - sum(value.operands[1:], start=Decimal(0))
        )
        if value.result != expected:
            return "arithmetic_invalid"
    return None


def _value_supported_by_quote(value: CandidateValueV1, quote: str) -> bool:
    """Prove the structured value is present in an already-bound quote snapshot."""

    normalized = _normalize_text(quote)
    if value.kind == "number":
        assert value.number is not None
        matches = re.finditer(
            rf"(?<![\d.]){SIGNED_DECIMAL_PATTERN}(?![\d.])",
            normalized,
        )
        return any(Decimal(match.group(0)) == value.number for match in matches)
    elif value.kind == "number_unit":
        assert value.number is not None and value.unit is not None
        pattern = (
            rf"(?<![\d.])(?P<number>{SIGNED_DECIMAL_PATTERN})"
            rf"{re.escape(_normalize_text(value.unit))}(?![\da-z_.])"
        )
        return any(
            Decimal(match.group("number")) == value.number
            for match in re.finditer(pattern, normalized)
        )
    elif value.kind == "enum":
        assert value.enum_value is not None
        return normalized == _normalize_text(value.enum_value)
    elif value.kind == "date":
        assert value.date_value is not None
        pattern = rf"(?<!\d){re.escape(value.date_value)}(?!\d)"
    elif value.kind == "range":
        assert value.lower is not None and value.upper is not None
        pattern = (
            rf"(?<![\d.])(?P<lower>{SIGNED_DECIMAL_PATTERN})\.\."
            rf"(?P<upper>{SIGNED_DECIMAL_PATTERN})(?![\d.])"
        )
        return any(
            Decimal(match.group("lower")) == value.lower
            and Decimal(match.group("upper")) == value.upper
            for match in re.finditer(pattern, normalized)
        )
    else:
        assert value.operator is not None and value.result is not None
        operator = "+" if value.operator == "sum" else "-"
        expected = operator.join(str(item) for item in value.operands) + f"={value.result}"
        pattern = rf"(?<![\d.]){re.escape(expected)}(?![\d.])"
    return re.search(pattern, normalized) is not None


def _explicit_absence_supported(rule: FieldRuleV1, quote: str) -> bool:
    normalized = _normalize_text(quote)
    return any(normalized == _normalize_text(marker) for marker in rule.absence_markers)


def _verify_field(
    *,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    candidate: FieldCandidateV1,
    rule: FieldRuleV1,
) -> FieldVerificationV1:
    if candidate.tri_state == "unknown":
        return FieldVerificationV1(
            field_id=candidate.field_id,
            status="GAP",
            reason_codes=("unknown_value",),
            candidate_snapshot_hash=candidate.candidate_snapshot_hash,
        )
    reason: str | None
    if candidate.tri_state == "absent_explicitly" and not rule.allow_absent:
        reason = "absence_not_allowed"
    elif not candidate.evidence:
        reason = (
            "absence_evidence_missing"
            if candidate.tri_state == "absent_explicitly"
            else "evidence_missing"
        )
    else:
        reason = next(
            (
                found
                for evidence in candidate.evidence
                if (
                    found := _verify_evidence(
                        document=document,
                        manifest=manifest,
                        candidate=candidate,
                        evidence=evidence,
                    )
                )
                is not None
            ),
            None,
        )
        if reason is None:
            if candidate.tri_state == "present":
                assert candidate.value is not None
                reason = _value_rule_reason(candidate.value, rule)
                if reason is None and not any(
                    _value_supported_by_quote(candidate.value, item.quote_snapshot)
                    for item in candidate.evidence
                ):
                    reason = "value_not_supported_by_quote"
            elif not any(
                _explicit_absence_supported(rule, item.quote_snapshot)
                for item in candidate.evidence
            ):
                reason = "absence_semantics_missing"
    return FieldVerificationV1(
        field_id=candidate.field_id,
        status="PASS" if reason is None else "FAIL",
        reason_codes=() if reason is None else (reason,),
        candidate_snapshot_hash=candidate.candidate_snapshot_hash,
    )


def verify_evidence_batch(
    *,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    candidates: tuple[FieldCandidateV1, ...],
    rules: tuple[FieldRuleV1, ...],
) -> VerificationBatchV1:
    """Verify exact evidence and fixed rules without any model or I/O."""

    fields = tuple(item.field_id for item in candidates)
    rule_fields = tuple(item.field_id for item in rules)
    if not _canonical_tuple(fields) or fields != rule_fields:
        raise VerifierContractError("candidate_rule_field_bijection_mismatch")
    if not _document_manifest_match(document, manifest):
        raise VerifierContractError("parsed_document_manifest_mismatch")
    return VerificationBatchV1(
        contract="evidence-verification-batch.v1",
        product_version_id=document.subject.product_version_id,
        source_revision_id=document.subject.source_revision_id,
        parse_attempt_id=document.attempt.attempt_id,
        parsed_document_hash=document.document_hash,
        parse_manifest_hash=manifest.manifest_hash,
        results=tuple(
            _verify_field(
                document=document,
                manifest=manifest,
                candidate=candidate,
                rule=rule,
            )
            for candidate, rule in zip(candidates, rules, strict=True)
        ),
    )


def _terminal_records(
    batch: VerificationBatchV1, *, reason_override: str | None = None
) -> tuple[tuple[GapV1, ...], tuple[EvidenceReviewItemV1, ...]]:
    unresolved = tuple(item for item in batch.results if item.status != "PASS")
    gaps = tuple(
        GapV1(field_id=item.field_id, reason_codes=item.reason_codes) for item in unresolved
    )
    reviews = tuple(
        EvidenceReviewItemV1(
            field_id=item.field_id,
            reason_code=reason_override or item.reason_codes[0],
            parent_verification_hash=batch.verification_hash,
        )
        for item in unresolved
    )
    return gaps, reviews


def plan_targeted_repair(
    batch: VerificationBatchV1,
    *,
    approved_locators: tuple[ApprovedLocatorSetV1, ...],
    budget: RepairBudgetV1,
    repairs_used: Literal[0, 1],
) -> TargetedRepairDecisionV1:
    unresolved = tuple(item.field_id for item in batch.results if item.status != "PASS")
    if not unresolved:
        return TargetedRepairDecisionV1(outcome="COMPLETE", plan=None, gaps=(), review_items=())
    if budget.max_targeted_repairs == 0 or repairs_used == 1:
        gaps, reviews = _terminal_records(batch, reason_override="repair_budget_exhausted")
        return TargetedRepairDecisionV1(
            outcome="EXHAUSTED", plan=None, gaps=gaps, review_items=reviews
        )
    if tuple(item.field_id for item in approved_locators) != unresolved:
        raise VerifierContractError("repair_locator_field_bijection_mismatch")
    return TargetedRepairDecisionV1(
        outcome="REPAIR",
        plan=TargetedRepairPlanV1(
            contract="targeted-repair-plan.v1",
            parent_verification_hash=batch.verification_hash,
            repair_number=1,
            field_ids=unresolved,
            approved_locators=approved_locators,
        ),
        gaps=(),
        review_items=(),
    )


def apply_targeted_repair(
    *,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    initial: VerificationBatchV1,
    plan: TargetedRepairPlanV1,
    repaired_candidates: tuple[FieldCandidateV1, ...],
    rules: tuple[FieldRuleV1, ...],
) -> RepairResolutionV1:
    """Verify one repair and preserve every initially-passed field verbatim."""

    if plan.parent_verification_hash != initial.verification_hash:
        raise VerifierContractError("repair_parent_verification_mismatch")
    if (
        not _document_manifest_match(document, manifest)
        or initial.product_version_id != document.subject.product_version_id
        or initial.source_revision_id != document.subject.source_revision_id
        or initial.parse_attempt_id != document.attempt.attempt_id
        or initial.parsed_document_hash != document.document_hash
        or initial.parse_manifest_hash != manifest.manifest_hash
    ):
        raise VerifierContractError("repair_input_custody_mismatch")
    unresolved = tuple(item.field_id for item in initial.results if item.status != "PASS")
    if plan.field_ids != unresolved:
        raise VerifierContractError("repair_plan_incomplete")
    document_locator_refs = {
        *(item.page_id for item in document.pages),
        *(item.block_id for item in document.blocks),
        *(item.table_id for item in document.tables),
        *(item.cell_id for item in document.cells),
    }
    if any(
        locator_ref not in document_locator_refs
        for approved_set in plan.approved_locators
        for locator_ref in approved_set.locator_refs
    ):
        raise VerifierContractError("repair_plan_locator_invalid")
    repaired_fields = tuple(item.field_id for item in repaired_candidates)
    if repaired_fields != plan.field_ids:
        raise VerifierContractError("repair_field_scope_mismatch")
    initial_by_field = {item.field_id: item for item in initial.results}
    if any(initial_by_field[field].status == "PASS" for field in repaired_fields):
        raise VerifierContractError("repair_field_scope_mismatch")
    approved = {item.field_id: set(item.locator_refs) for item in plan.approved_locators}
    if any(
        evidence.locator.subject_ref not in approved[candidate.field_id]
        for candidate in repaired_candidates
        for evidence in candidate.evidence
    ):
        raise VerifierContractError("repair_locator_not_approved")
    rule_by_field = {item.field_id: item for item in rules}
    if any(field not in rule_by_field for field in repaired_fields):
        raise VerifierContractError("repair_rule_missing")
    repaired = verify_evidence_batch(
        document=document,
        manifest=manifest,
        candidates=repaired_candidates,
        rules=tuple(rule_by_field[field] for field in repaired_fields),
    )
    repaired_by_field = {item.field_id: item for item in repaired.results}
    merged = tuple(repaired_by_field.get(item.field_id, item) for item in initial.results)
    synthetic_batch = VerificationBatchV1(
        contract="evidence-verification-batch.v1",
        product_version_id=initial.product_version_id,
        source_revision_id=initial.source_revision_id,
        parse_attempt_id=initial.parse_attempt_id,
        parsed_document_hash=initial.parsed_document_hash,
        parse_manifest_hash=initial.parse_manifest_hash,
        results=merged,
    )
    gaps, reviews = _terminal_records(synthetic_batch)
    return RepairResolutionV1(
        contract="targeted-repair-resolution.v1",
        parent_verification_hash=initial.verification_hash,
        repair_plan_hash=plan.plan_hash,
        results=merged,
        gaps=gaps,
        review_items=reviews,
    )


__all__ = [
    "ApprovedLocatorSetV1",
    "CandidateValueV1",
    "EvidenceLocatorSnapshotV1",
    "EvidenceReviewItemV1",
    "EvidenceSnapshotV1",
    "EvidenceSupportScopeV1",
    "FreeformDocumentBindingV1",
    "FreeformEvidenceBindingReceiptV1",
    "FreeformEvidenceV1",
    "FreeformFieldOutputV1",
    "FieldCandidateV1",
    "FieldRuleV1",
    "GapV1",
    "RepairBudgetV1",
    "RepairResolutionV1",
    "TargetedRepairDecisionV1",
    "TargetedRepairPlanV1",
    "VerificationBatchV1",
    "VerifierContractError",
    "apply_targeted_repair",
    "bind_054_attempt_receipt",
    "bind_freeform_arm_evidence",
    "plan_targeted_repair",
    "replay_freeform_arm_evidence_binding",
    "value_snapshot",
    "verify_evidence_batch",
]
