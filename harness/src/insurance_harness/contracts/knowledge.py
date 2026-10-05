"""Knowledge and source contracts from blueprint §5.1 and S3a §8."""

from __future__ import annotations

import hashlib
import unicodedata
from typing import TYPE_CHECKING, Annotated, Any, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from insurance_harness.contracts.enums import (
    ChangedBy,
    ClaimState,
    EvidenceMatch,
    LocatorKind,
    ReviewMode,
    SourceClass,
    UnknownReason,
)

NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]
NonNegativeInt = Annotated[int, Field(ge=0, strict=True)]
PositiveInt = Annotated[int, Field(ge=1, strict=True)]
Coordinate = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
ClaimValue = (
    StrictStr | StrictInt | Annotated[StrictFloat, Field(allow_inf_nan=False)]
    | StrictBool | list[StrictStr] | None
)


class ContractModel(BaseModel):
    """Every boundary rejects undeclared fields and attribute reassignment."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class BoundingBox(ContractModel):
    """Top-left origin; dimensions normalized to the page extent."""

    x: Coordinate
    y: Coordinate
    w: Coordinate
    h: Coordinate


LOCATOR_FIELDS: dict[LocatorKind, tuple[str, ...]] = {
    LocatorKind.PDF_TEXT_SPAN: ("page", "start", "end"),
    LocatorKind.OCR_REGION: ("page", "bbox"),
    LocatorKind.DOCX_BLOCK: ("block_index",),
    LocatorKind.DOCX_TABLE_CELL: ("table_index", "row", "column"),
    LocatorKind.PPTX_SHAPE: ("slide", "shape_id"),
    LocatorKind.XLSX_CELL_RANGE: ("sheet", "cell_range"),
    LocatorKind.CHUNK_SPAN: ("chunk_id", "start", "end"),
    LocatorKind.STRUCTURED_PATH: ("path",),
    LocatorKind.EXPERT_REVISION: ("revision_record_id",),
}


class Locator(ContractModel):
    """Kind-specific required fields with a stable keyword constructor.

    Page/slide indices are one-based; other indices and half-open text offsets
    are zero-based. Text offsets count Unicode code points, not bytes.
    """

    kind: LocatorKind
    page: PositiveInt | None = None
    start: NonNegativeInt | None = None
    end: NonNegativeInt | None = None
    bbox: BoundingBox | None = None
    block_index: NonNegativeInt | None = None
    table_index: NonNegativeInt | None = None
    row: NonNegativeInt | None = None
    column: NonNegativeInt | None = None
    slide: PositiveInt | None = None
    shape_id: NonBlank | None = None
    sheet: NonBlank | None = None
    cell_range: Annotated[
        str, StringConstraints(pattern=r"^\$?[A-Z]+\$?[1-9][0-9]*(:\$?[A-Z]+\$?[1-9][0-9]*)?$")
    ] | None = None
    chunk_id: NonBlank | None = None
    path: Annotated[list[NonBlank], Field(min_length=1)] | None = None
    revision_record_id: NonBlank | None = None

    if TYPE_CHECKING:
        # The public constructor accepts raw wire values, including kind strings.
        # Keep Pydantic's runtime constructor so call-level validation is preserved.
        def __init__(self, **data: Any) -> None: ...

    @model_validator(mode="after")
    def validate_kind(self) -> Self:
        missing = [name for name in LOCATOR_FIELDS[self.kind] if getattr(self, name) is None]
        if missing:
            raise ValueError(f"{self.kind} requires {', '.join(missing)}")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


def quote_digest(data: dict[str, Any]) -> str:
    """Hash NFKC text without whitespace; keep the original quotation intact."""
    normalized = "".join(unicodedata.normalize("NFKC", data["quote"]).split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class Evidence(ContractModel):
    source_ref: NonBlank
    file_sha256: Sha256
    locator: Locator
    quote: NonBlank
    # The validated quote must precede this data-aware factory. Explicit hashes
    # remain authoritative; source/hash verification belongs to the evidence layer.
    quote_sha256: Sha256 = Field(default_factory=quote_digest)
    match: EvidenceMatch = EvidenceMatch.EXACT
    access_scope: NonBlank


class Applicability(ContractModel):
    region: list[str] = Field(default_factory=list)
    channel: list[str] = Field(default_factory=list)
    population: list[str] = Field(default_factory=list)
    scenario: list[str] = Field(default_factory=list)


class Provenance(ContractModel):
    compiler: str = ""
    compiler_version: str = ""
    model: str | None = None
    run_id: str | None = None
    call_receipt_ref: str | None = None


class Maintenance(ContractModel):
    revision_no: NonNegativeInt = 0
    changed_at: str | None = None
    changed_by: ChangedBy = ChangedBy.COMPILE
    reason: str | None = None
    first_release_id: str | None = None
    last_changed_release_id: str | None = None


class Review(ContractModel):
    mode: ReviewMode = ReviewMode.MACHINE
    score: float | None = Field(default=None, allow_inf_nan=False)
    reviewer: str | None = None
    reviewed_at: str | None = None


class Entity(ContractModel):
    entity_id: NonBlank
    entity_type: NonBlank
    names: list[NonBlank] = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    identifiers: dict[str, str] = Field(default_factory=dict)
    classification_labels: list[str] = Field(default_factory=list)
    owner_module: NonBlank


class Claim(ContractModel):
    claim_id: NonBlank
    logical_key: NonBlank
    subject_ref: NonBlank
    product_version_ref: NonBlank | None = None
    predicate: NonBlank
    state: ClaimState
    value: ClaimValue = None
    unit: str | None = None
    applicability: Applicability = Field(default_factory=Applicability)
    effective_from: str | None = None
    effective_to: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    origin: SourceClass
    expert_lock: bool = False
    unknown_reason: UnknownReason | None = None
    review: Review = Field(default_factory=Review)
    maintenance: Maintenance = Field(default_factory=Maintenance)

    @model_validator(mode="after")
    def validate_state(self) -> Self:
        if self.state == ClaimState.PRESENT:
            if self.value is None or (isinstance(self.value, str) and not self.value.strip()):
                raise ValueError("present requires a nonempty value")
            if not any(item.match != EvidenceMatch.FUZZY_REVIEW for item in self.evidence):
                raise ValueError("present requires verified evidence")
        elif self.value is not None:
            raise ValueError("non-present states require value=None")
        if self.state == ClaimState.UNKNOWN:
            if self.evidence or self.unknown_reason is None:
                raise ValueError("unknown requires no evidence and a typed reason")
        elif self.unknown_reason is not None:
            raise ValueError("only unknown may carry unknown_reason")
        if self.state == ClaimState.ABSENT_EXPLICITLY and not self.evidence:
            raise ValueError("absent_explicitly requires evidence")
        return self


class Relation(ContractModel):
    # Python reserves `from`; serialization must still use the blueprint's key.
    model_config = ConfigDict(extra="forbid", frozen=True, serialize_by_alias=True)

    relation_id: NonBlank
    predicate: NonBlank
    from_: NonBlank = Field(alias="from")
    to: NonBlank
    applicability: Applicability = Field(default_factory=Applicability)
    effective_from: str | None = None
    effective_to: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


class QAItem(ContractModel):
    qa_id: NonBlank
    question: NonBlank
    intent: NonBlank
    answer: NonBlank
    supporting_claims: list[str] = Field(default_factory=list)
    related_entities: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class ExpertRevision(ContractModel):
    revision_record_id: NonBlank
    actor: NonBlank
    role: NonBlank
    recorded_at: NonBlank
    target: NonBlank
    before: str | None = None
    after: str | None = None
    reason: str | None = None
    attachments: list[str] = Field(default_factory=list)


class SchemaSnapshot(ContractModel):
    schema_pack_id: NonBlank
    schema_pack_sha256: Sha256
    presentation_profile_ref: NonBlank
    catalog_version: NonBlank
