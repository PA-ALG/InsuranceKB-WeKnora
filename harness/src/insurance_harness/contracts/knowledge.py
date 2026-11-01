"""Knowledge and source contracts from blueprint §5.1 and S3a §8."""

from __future__ import annotations

import hashlib
import unicodedata
from datetime import date
from typing import TYPE_CHECKING, Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_serializer,
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
    StrictStr
    | StrictInt
    | Annotated[StrictFloat, Field(allow_inf_nan=False)]
    | StrictBool
    | list[StrictStr]
    | None
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
    # S11c: the platform locates a slide's text, not its shapes (S11b), so shape_id is optional.
    LocatorKind.PPTX_SHAPE: ("slide",),
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
    cell_range: (
        Annotated[
            str, StringConstraints(pattern=r"^\$?[A-Z]+\$?[1-9][0-9]*(:\$?[A-Z]+\$?[1-9][0-9]*)?$")
        ]
        | None
    ) = None
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


DateText = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
SUPERSEDES = "supersedes"


class ProductLifecycle(ContractModel):
    """A filed version's sale period from the pinned product repository (PV-0 appendix A §1.2).

    Not a claim's business effective period: the end of sale never ends a policy's terms. The
    sale status is derived when read (appendix A §3.2), never stored.
    """

    sale_start: DateText | None = None
    sale_end: DateText | None = None
    source_status: Literal["on_sale", "discontinued"] | None = None
    basis_commit: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")] | None = None
    basis_date: DateText | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> Self:
        for text in (self.sale_start, self.sale_end, self.basis_date):
            if text is not None:
                date.fromisoformat(text)  # an impossible calendar day raises ValueError
        if self.sale_start and self.sale_end and self.sale_start >= self.sale_end:
            raise ValueError("a sale period must end after it starts")
        return self


class ProductFamily(ContractModel):
    """The brand family a version belongs to: grouping only, never an attribution anchor."""

    key: NonBlank
    display_name: NonBlank


class Entity(ContractModel):
    entity_id: NonBlank
    entity_type: NonBlank
    names: list[NonBlank] = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    identifiers: dict[str, str] = Field(default_factory=dict)
    classification_labels: list[str] = Field(default_factory=list)
    owner_module: NonBlank
    lifecycle: ProductLifecycle | None = None
    product_family: ProductFamily | None = None

    @model_serializer(mode="wrap")
    def omit_absent_version_data(self, handler: SerializerFunctionWrapHandler) -> Any:
        # Absent version data is not serialized, so every existing entity keeps its digest.
        data = handler(self)
        if isinstance(data, dict):
            for key in ("lifecycle", "product_family"):
                if data.get(key) is None:
                    data.pop(key, None)
        return data


def supersedes_relation_id(newer: str, older: str) -> str:
    """The deterministic id of the relation saying `newer` replaces `older` (PV-4 Spec §1.3)."""
    if not newer.strip() or not older.strip() or newer == older or "/" in newer + older:
        raise ValueError("supersedes needs two different entity ids without '/'")
    return f"{SUPERSEDES}/{newer}/{older}"


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


class ProfileField(ContractModel):
    field_key: NonBlank
    short_title: NonBlank
    # S3e: the schema's definition and category, shown on concept pages; absent in older releases.
    description: str | None = None
    schema_category: str | None = None


class ProfileSection(ContractModel):
    section_key: NonBlank
    display_name: NonBlank
    fields: list[ProfileField] = Field(min_length=1)


class PresentationProfile(ContractModel):
    """A pack's display groups and field order, published with the release it renders.

    Readers show an entity with the profile whose classification_labels meet the entity's,
    so each field and section appears once and the labels say which entities it serves.
    """

    profile_id: NonBlank
    profile_version: NonBlank
    profile_sha256: Sha256
    schema_pack_id: NonBlank
    display_name: str | None = None  # S3e: the pack's display name
    classification_labels: list[NonBlank] = Field(min_length=1)
    sections: list[ProfileSection] = Field(min_length=1)

    @model_validator(mode="after")
    def keys_are_unique(self) -> Self:
        sections = [section.section_key for section in self.sections]
        fields = [field.field_key for section in self.sections for field in section.fields]
        if len(set(sections)) != len(sections) or len(set(fields)) != len(fields):
            raise ValueError("section and field keys must be unique within a profile")
        return self


class NavigationGroup(ContractModel):
    group_key: NonBlank
    display_name: NonBlank
    classification_labels: list[NonBlank] = Field(default_factory=list)


class NavigationDomain(ContractModel):
    domain_key: NonBlank
    display_name: NonBlank
    entity_types: list[NonBlank] = Field(min_length=1)
    groups: list[NavigationGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def group_keys_are_unique(self) -> Self:
        keys = [group.group_key for group in self.groups]
        if len(set(keys)) != len(keys):
            raise ValueError("group keys must be unique within a domain")
        return self


def question_term_text(term: str) -> str:
    """A question term exactly as the platform's Go normalizeQuestionTerm compares it (QA3
    Spec §2): NFKC, lower case, without whitespace or punctuation; symbols stay. A term must
    keep at least two characters."""
    folded = unicodedata.normalize("NFKC", term).lower()
    return "".join(
        ch
        for ch in folded
        if not _platform_space(ch) and not unicodedata.category(ch).startswith("P")
    )


def _platform_space(ch: str) -> bool:
    # Go unicode.IsSpace, plus the BOM its normalize also drops. str.isspace differs from it only
    # by the information separators U+001C-U+001F, which Go keeps (checked over every code point).
    return (ch.isspace() and not "\x1c" <= ch <= "\x1f") or ch == "\ufeff"


class NavigationProfile(ContractModel):
    """How readers organise a release's entries (S3e): domains by entity type, then groups by
    classification label. Versioned data published with the release, replaced whole each time.
    """

    navigation_id: NonBlank
    navigation_version: NonBlank
    # S3f-2: the Space's display name and the fields of its product overview, in column order.
    display_name: NonBlank | None = None
    overview_fields: list[NonBlank] = Field(default_factory=list)
    domains: list[NavigationDomain] = Field(min_length=1)
    # QA3: per field key, groups of 1-3 terms; a question asks a field when it contains every
    # term of one group. Absent in navigations published before QA3.
    question_terms: dict[NonBlank, list[list[NonBlank]]] | None = None
    # PV-4b: per question intent, term groups shaped like question_terms. The platform narrows
    # product versions by intent from these alone (Spec PV-4b §4). Absent before PV-4b.
    question_intents: dict[Literal["sales", "service"], list[list[NonBlank]]] | None = None

    @model_validator(mode="after")
    def keys_are_unique(self) -> Self:
        keys = [domain.domain_key for domain in self.domains]
        if len(set(keys)) != len(keys):
            raise ValueError("domain keys must be unique")
        if len(set(self.overview_fields)) != len(self.overview_fields):
            raise ValueError("overview fields must be unique")
        intents = (self.question_intents or {}).values()
        for groups in [*(self.question_terms or {}).values(), *intents]:
            _check_term_groups(groups)
        return self


def _check_term_groups(groups: list[list[str]]) -> None:
    # A group matches when every term occurs, so its order carries nothing: compare sets.
    seen: set[frozenset[str]] = set()
    for group in groups:
        texts = frozenset(question_term_text(term) for term in group)
        if not 1 <= len(group) <= 3 or any(len(text) < 2 for text in texts):
            raise ValueError("a question-term group has 1 to 3 terms of 2+ characters")
        if len(texts) != len(group):
            raise ValueError("a question-term group repeats a term")
        if texts in seen:
            raise ValueError("the term groups of one key must be distinct")
        seen.add(texts)


class ConceptStatement(ContractModel):
    text: NonBlank
    refs: list[NonBlank] = Field(min_length=1)


class ConceptSummary(ContractModel):
    """Model-written reading aid for a field two or more entries state (S3e-3).

    `based_on` holds the member digest of every claim the summary was written from, so a reader
    can tell when one has changed since; each statement cites claims among them.
    """

    concept_key: NonBlank
    title: NonBlank
    definition: NonBlank
    explanation: NonBlank
    statements: list[ConceptStatement] = Field(min_length=1, max_length=6)
    based_on: dict[NonBlank, Sha256] = Field(min_length=1)
    origin: Literal["MODEL_GENERATED"]
    model: NonBlank
    prompt_version: NonBlank

    @model_validator(mode="after")
    def refs_are_in_the_basis(self) -> Self:
        if any(ref not in self.based_on for item in self.statements for ref in item.refs):
            raise ValueError("every statement reference must be among based_on")
        return self


class WikiPage(ContractModel):
    """Model-written reading page from the native Wiki, attached to products (S6c).

    It never states a reviewed product fact: products' facts are claims. Evidence is at most three
    quotes located word for word in the product's own source pages; a page may have none.
    """

    page_key: NonBlank
    entity_refs: list[NonBlank] = Field(min_length=1)
    title: NonBlank
    page_type: Literal["concept", "entity"]
    summary: str = ""
    content: NonBlank
    aliases: list[NonBlank] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list, max_length=3)
    origin: Literal["MODEL_GENERATED"]
    generator: NonBlank
    model: NonBlank
