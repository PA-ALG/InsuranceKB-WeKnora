"""Deterministic field-local native-PDF selections for EC-01 C3."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from typing import Annotated, Final, Literal, Self, cast

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
from insurance_harness.compiler import evidence_verifier
from insurance_harness.compiler.evidence_verifier import (
    EvidenceLocatorSnapshotV1,
    FreeformEvidenceV1,
    FreeformFieldOutputV1,
)
from insurance_harness.compiler.extraction_tasks import MaterialRole
from insurance_harness.compiler.native_pdfplumber import (
    NativeBBox,
    NativePdfPageProjection815V1,
    NativePdfSelectionProjection815V1,
    NativeTableSlice815V1,
    NativeTextSpan815V1,
    _canonical_number,
)
from insurance_harness.compiler.parsed_documents import (
    ParsedDocumentV1,
    ParseManifestV1,
    ParseQualityDecisionV1,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    FieldContractSetV1,
    FieldContractV1,
)
from insurance_harness.knowledge_compiler.vertical_falsification import (
    AdmittedParseArtifactV1,
)

SelectionType815 = Literal["TEXT_SPAN", "TABLE_SLICE"]
DisplayPolicy815 = Literal["EXACT_SHORT", "EXTRACTIVE_LONG"]

_CATALOG_CONTRACT: Final[Literal["schema67-native-pdf-selection-catalog.815.v1"]] = (
    "schema67-native-pdf-selection-catalog.815.v1"
)
_ROLE_ORDER: Final[tuple[MaterialRole, ...]] = ("terms", "brochure", "rate_table")
_MAX_SELECTIONS_PER_FIELD: Final[int] = 12
_MAX_TABLE_SELECTIONS_PER_FIELD: Final[int] = 2
_MAX_PROVIDER_SELECTION_BYTES_PER_FIELD_815: Final[int] = 16_384
_VALUE_PART_SEPARATOR_815: Final[str] = "\N{LINE SEPARATOR}"
_NUMERIC_PATTERN: Final[re.Pattern[str]] = re.compile(r"\d+(?:\.\d+)?%?")
_RETRIEVAL_PARTICLE_PATTERN_815: Final[re.Pattern[str]] = re.compile(
    "|".join(
        sorted(
            (
                "是否",
                "不得",
                "必须",
                "可以",
                "上述",
                "以上",
                "以下",
                "对应",
                "相关",
                "的",
                "和",
                "或",
                "与",
                "及",
                "等",
                "应",
                "如",
                "按",
                "从",
                "在",
                "对",
                "为",
                "须",
                "其",
                "该",
                "此",
                "所",
                "只",
                "仅",
                "并",
                "但",
                "且",
                "由",
                "向",
            ),
            key=len,
            reverse=True,
        )
    )
)
_RETRIEVAL_STOP_TERMS_815: Final[frozenset[str]] = frozenset(
    {
        "本合同",
        "被保险人",
        "投保人",
        "保险",
        "合同",
        "约定",
        "规定",
        "其他",
        "相关",
        "内容",
        "方式",
        "范围",
        "条件",
        "费用",
        "保险金",
        "完整",
        "列示",
        "适用",
        "记录",
        "产品条款",
        "产品说明书",
    }
)
_EXTRACTIVE_LONG_FIELD_IDS_815: Final[frozenset[str]] = frozenset(
    {
        "entry_age_range",
        "insured_eligibility",
        "health_declaration_requirements",
        "surrender_and_cancellation_terms",
        "coverage_and_renewal_terms",
        "post_discontinuation_renewal_arrangement",
        "coverage_responsibilities",
        "exclusions",
        "pre_existing_condition_rules",
        "out_of_hospital_special_drug_coverage",
        "indemnity_principle",
        "deductible_rules",
        "outpatient_inpatient_scope",
        "reimbursable_expense_scope",
        "reimbursement_rate_rules",
        "eligible_hospital_scope",
        "claim_application_deadline_and_documents",
        "policyholder_rights",
    }
)
_CLAUSE_START_815: Final[re.Pattern[str]] = re.compile(
    r"^\s*(\d+\.\d+(?:\.\d+)*)\s+\S"
)
_INTEGER_LIST_ITEM_START_815: Final[re.Pattern[str]] = re.compile(
    r"^\s*(?P<ordinal>[1-9]\d?)\.\s+\S"
)
_TOC_LINE_815: Final[re.Pattern[str]] = re.compile(
    r"(?:\.{3,}|…{2,}|·{3,})\s*\d+(?:\.\d+)*\s*$"
)
_PAGE_NUMBER_TAIL_FRACTION_815: Final[Decimal] = Decimal("0.85")
_CLAUSE_VERTICAL_GAP_MULTIPLIER_815: Final[Decimal] = Decimal("1.5")
_PARAGRAPH_WRAP_RIGHT_FRACTION_815: Final[Decimal] = Decimal("0.8")
_HEADING_TERMINAL_PUNCTUATION_815: Final[frozenset[str]] = frozenset(
    "，。；;：:、,.!?！？"
)

NonBlankStr815 = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex815 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonNegativeInt815 = Annotated[StrictInt, Field(ge=0)]
PositiveInt815 = Annotated[StrictInt, Field(gt=0)]


class _FrozenModel815(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class NativePdfSelectionError815(ValueError):
    """Typed provider-free catalog validation failure."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True, slots=True)
class _AdmittedSourceIdentityProjection815:
    role: MaterialRole
    document_hash: str
    manifest_hash: str
    decision_hash: str


class ModelFieldSelection815V1(_FrozenModel815):
    field_id: NonBlankStr815
    state: Literal["present", "absent_explicitly", "unknown"]
    selection_ids: tuple[NonBlankStr815, ...]
    value_part_ids: tuple[NonBlankStr815, ...] = ()
    typed_reason: Literal["ANSWER_NOT_FOUND"] | None

    @model_validator(mode="after")
    def require_exact_state_shape(self) -> Self:
        if len(self.selection_ids) != len(set(self.selection_ids)) or len(
            self.value_part_ids
        ) != len(set(self.value_part_ids)):
            raise ValueError("selection and value-part ids must be unique")
        if self.state == "unknown":
            if (
                self.selection_ids
                or self.value_part_ids
                or self.typed_reason != "ANSWER_NOT_FOUND"
            ):
                raise ValueError("unknown selection shape invalid")
        elif not self.selection_ids or self.typed_reason is not None:
            raise ValueError("known selection shape invalid")
        return self


class ModelTaskSelectionResponse815V1(_FrozenModel815):
    task_key: NonBlankStr815
    fields: tuple[ModelFieldSelection815V1, ...]


class CoordinateEvidence815V1(_FrozenModel815):
    field_id: NonBlankStr815
    source_revision_id: NonBlankStr815
    source_role: MaterialRole
    original_file_sha256: Sha256Hex815
    parse_manifest_sha256: Sha256Hex815
    selection_id: NonBlankStr815
    selection_type: Literal["TEXT_SPAN", "TABLE_SLICE"]
    page_number: PositiveInt815
    page_text_char_start: NonNegativeInt815 | None
    page_text_char_end: PositiveInt815 | None
    coordinate_space: Literal["PDF_POINTS_TOP_LEFT_V1"]
    page_width_points: NonBlankStr815
    page_height_points: NonBlankStr815
    bbox: NativeBBox
    rects: tuple[NativeBBox, ...]
    quote: Annotated[StrictStr, Field(min_length=1, max_length=4096)]
    quote_sha256: Sha256Hex815
    block_id: NonBlankStr815 | None = None
    span_id: NonBlankStr815 | None = None
    table_slice_id: NonBlankStr815 | None = None
    table_id: NonBlankStr815 | None = None
    cell_ids: tuple[NonBlankStr815, ...] = ()

    @model_validator(mode="after")
    def require_exact_coordinate_shape(self) -> Self:
        if (
            self.quote_sha256 != hashlib.sha256(self.quote.encode()).hexdigest()
            or not self.rects
            or self.bbox != _union_native_bbox_815(self.rects)
        ):
            raise ValueError("coordinate Evidence hash or bbox mismatch")
        text_shape = (
            self.page_text_char_start is not None
            and self.page_text_char_end is not None
            and self.page_text_char_start < self.page_text_char_end
            and self.block_id is not None
            and self.span_id is not None
            and self.table_slice_id is None
            and self.table_id is None
            and not self.cell_ids
        )
        table_shape = (
            self.page_text_char_start is None
            and self.page_text_char_end is None
            and self.block_id is None
            and self.span_id is None
            and self.table_slice_id is not None
            and self.table_id is not None
            and bool(self.cell_ids)
            and len(self.cell_ids) == len(set(self.cell_ids))
        )
        if (self.selection_type == "TEXT_SPAN") != text_shape or (
            self.selection_type == "TABLE_SLICE"
        ) != table_shape:
            raise ValueError("coordinate Evidence selection shape mismatch")
        return self

    def recomputed_coordinate_evidence_sha256(self) -> str:
        return canonical_hash(
            "schema67-coordinate-evidence.815.v1",
            self.model_dump(mode="python"),
        )


class CoordinateEvidenceCompanion815V1(_FrozenModel815):
    contract: Literal["schema67-coordinate-evidence-companion.815.v1"]
    candidate_sha256: Sha256Hex815
    provider_visible_field_ids: tuple[NonBlankStr815, ...]
    coordinate_rows: tuple[CoordinateEvidence815V1, ...]
    selection_catalog_sha256: Sha256Hex815
    parse_manifest_sha256s: tuple[Sha256Hex815, ...]
    companion_sha256: Sha256Hex815

    @model_validator(mode="after")
    def require_exact_companion_hash(self) -> Self:
        if (
            not self.provider_visible_field_ids
            or len(self.provider_visible_field_ids)
            != len(set(self.provider_visible_field_ids))
            or len(self.parse_manifest_sha256s)
            != len(set(self.parse_manifest_sha256s))
            or self.companion_sha256 != self.recomputed_companion_sha256()
        ):
            raise ValueError("coordinate Evidence companion invalid")
        order = {field_id: index for index, field_id in enumerate(self.provider_visible_field_ids)}
        if any(row.field_id not in order for row in self.coordinate_rows) or tuple(
            order[row.field_id] for row in self.coordinate_rows
        ) != tuple(sorted(order[row.field_id] for row in self.coordinate_rows)):
            raise ValueError("coordinate Evidence companion field order invalid")
        return self

    def recomputed_companion_sha256(self) -> str:
        payload = self.model_dump(mode="python", exclude={"companion_sha256"})
        return canonical_hash("schema67-coordinate-evidence-companion.815.v1", payload)


def _union_native_bbox_815(rects: tuple[NativeBBox, ...]) -> NativeBBox:
    if not rects:
        raise ValueError("coordinate Evidence requires rects")
    return (
        _canonical_number(min(Decimal(item[0]) for item in rects)),
        _canonical_number(min(Decimal(item[1]) for item in rects)),
        _canonical_number(max(Decimal(item[2]) for item in rects)),
        _canonical_number(max(Decimal(item[3]) for item in rects)),
    )


@dataclass(frozen=True, slots=True)
class NativePdfValuePart815V1:
    value_part_id: str
    subject_ids: tuple[str, ...]
    exact_text_parts: tuple[str, ...]
    value_part_sha256: str

    def recomputed_value_part_sha256(self) -> str:
        return canonical_hash(
            "schema67-native-pdf-value-part.815.v1",
            {
                "subject_ids": self.subject_ids,
                "exact_text_parts": self.exact_text_parts,
            },
        )


@dataclass(frozen=True, slots=True)
class NativePdfSelection815V1:
    selection_id: str
    selection_type: SelectionType815
    field_id: str
    source_role: MaterialRole
    source_revision_id: str
    parse_manifest_sha256: str
    subject_ids: tuple[str, ...]
    page_numbers: tuple[int, ...]
    exact_text_parts: tuple[str, ...]
    display_policy: DisplayPolicy815
    value_parts: tuple[NativePdfValuePart815V1, ...]
    selection_sha256: str

    def recomputed_selection_sha256(self) -> str:
        return canonical_hash(
            "schema67-native-pdf-selection.815.v1",
            {
                "selection_type": self.selection_type,
                "field_id": self.field_id,
                "source_role": self.source_role,
                "source_revision_id": self.source_revision_id,
                "parse_manifest_sha256": self.parse_manifest_sha256,
                "subject_ids": self.subject_ids,
                "page_numbers": self.page_numbers,
                "exact_text_parts": self.exact_text_parts,
                "display_policy": self.display_policy,
                "value_parts": tuple(asdict(item) for item in self.value_parts),
            },
        )


def _selection_prompt_payload_815(
    selection: NativePdfSelection815V1,
) -> dict[str, object]:
    """Return the one closed provider-visible representation of a selection."""

    return {
        "selection_id": selection.selection_id,
        "selection_type": selection.selection_type,
        "source_role": selection.source_role,
        "source_revision_id": selection.source_revision_id,
        "parse_manifest_sha256": selection.parse_manifest_sha256,
        "page_numbers": selection.page_numbers,
        "display_policy": selection.display_policy,
        "value_parts": tuple(
            {
                "value_part_id": part.value_part_id,
                "exact_text_parts": part.exact_text_parts,
                "value_part_sha256": part.value_part_sha256,
            }
            for part in selection.value_parts
        ),
        "selection_sha256": selection.selection_sha256,
    }


def _selection_prompt_byte_size_815(selection: NativePdfSelection815V1) -> int:
    return len(
        json.dumps(
            _selection_prompt_payload_815(selection),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


@dataclass(frozen=True, slots=True)
class FieldSelectionCatalog815V1:
    field_id: str
    allowed_source_roles: tuple[MaterialRole, ...]
    selections: tuple[NativePdfSelection815V1, ...]
    retrieval_policy_sha256: str
    catalog_sha256: str

    def recomputed_catalog_sha256(self) -> str:
        return canonical_hash(
            "schema67-field-selection-catalog.815.v1",
            {
                "field_id": self.field_id,
                "allowed_source_roles": self.allowed_source_roles,
                "selections": tuple(asdict(item) for item in self.selections),
                "retrieval_policy_sha256": self.retrieval_policy_sha256,
            },
        )


@dataclass(frozen=True, slots=True)
class Schema67SelectionCatalog815V1:
    contract: Literal["schema67-native-pdf-selection-catalog.815.v1"]
    provider_visible_field_ids: tuple[str, ...]
    fields: tuple[FieldSelectionCatalog815V1, ...]
    catalog_sha256: str

    def recomputed_catalog_sha256(self) -> str:
        return canonical_hash(
            "schema67-selection-catalog.815.v1",
            {
                "contract": self.contract,
                "provider_visible_field_ids": self.provider_visible_field_ids,
                "fields": tuple(asdict(item) for item in self.fields),
            },
        )

    def require_field(self, field_id: str) -> FieldSelectionCatalog815V1:
        matches = tuple(item for item in self.fields if item.field_id == field_id)
        if len(matches) != 1:
            raise NativePdfSelectionError815("FIELD_SELECTION_CATALOG_NOT_FOUND")
        return matches[0]


@dataclass(frozen=True, slots=True)
class _RankedSelection815:
    content_priority: int
    score: int
    role_order: int
    first_page: int
    first_order: tuple[int, ...]
    selection: NativePdfSelection815V1


@dataclass(frozen=True, slots=True)
class _RetrievalIntent815:
    term: str
    weight: int
    dimension: str
    negative: bool


@dataclass(frozen=True, slots=True)
class _CompleteClauseGroup815:
    spans: tuple[NativeTextSpan815V1, ...]
    ranking_context: str | None
    content_priority: int


def _normalize_retrieval_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(
        chr(ord(character) + 32) if "A" <= character <= "Z" else character
        for character in normalized
    )


def _retrieval_concepts_815(value: str) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    normalized = _normalize_retrieval_text(value)
    for run in re.findall(
        r"[\u3400-\u9fff]+|[a-z][a-z\-]{2,}|\d+(?:\.\d+)?%?", normalized
    ):
        pieces = (
            (run,)
            if not re.match(r"[\u3400-\u9fff]", run)
            else tuple(re.split(_RETRIEVAL_PARTICLE_PATTERN_815, run))
        )
        for piece in pieces:
            for concept in re.split(r"包含|包括|涉及|属于|用于|针对|分别记录", piece):
                term = concept.strip()
                if (
                    (2 <= len(term) <= 12 or _NUMERIC_PATTERN.fullmatch(term))
                    and term not in _RETRIEVAL_STOP_TERMS_815
                    and term not in seen
                ):
                    seen.add(term)
                    ordered.append(term)
    return tuple(ordered)


def _retrieval_intents_815(
    *,
    contract: FieldContractV1,
    corpus_pages: tuple[str, ...],
) -> tuple[_RetrievalIntent815, ...]:
    intents: dict[tuple[str, str, bool], _RetrievalIntent815] = {}

    def add(term: str, *, weight: int, dimension: str, negative: bool = False) -> None:
        normalized = _normalize_retrieval_text(term.strip())
        if (
            len(normalized) < 2
            or normalized in _RETRIEVAL_STOP_TERMS_815
            or _NUMERIC_PATTERN.fullmatch(normalized)
        ):
            return
        key = (normalized, dimension, negative)
        previous = intents.get(key)
        if previous is None or previous.weight < weight:
            intents[key] = _RetrievalIntent815(
                term=normalized,
                weight=weight,
                dimension=dimension,
                negative=negative,
            )

    add(contract.field_name, weight=12, dimension="field_name")
    for part in re.split(r"[/、（）()与和及]", contract.field_name):
        if part.strip() and part.strip() != contract.field_name:
            add(part, weight=9, dimension="field_name")

    negative_clauses = tuple(
        match.group("body")
        for match in re.finditer(
            r"不(?:应)?与(?P<body>[^。；;]+?)重复",
            contract.description,
        )
    )
    positive_description = re.sub(
        r"不(?:应)?与[^。；;]+?重复",
        "",
        contract.description,
    )
    for index, segment in enumerate(
        item.strip()
        for item in re.split(r"[。；;，,、]", positive_description)
        if item.strip()
    ):
        dimension = f"description-{index + 1}"
        for term in _retrieval_concepts_815(segment):
            add(term, weight=6, dimension=dimension)
    for index, clause in enumerate(negative_clauses):
        for term in _retrieval_concepts_815(clause):
            add(term, weight=8, dimension=f"negative-{index + 1}", negative=True)
    if contract.value_shape_raw:
        for term in _retrieval_concepts_815(contract.value_shape_raw):
            add(term, weight=8, dimension="value_shape")

    total_pages = max(1, len(corpus_pages))
    ceiling = max(2, (total_pages * 2) // 3)
    for seed in tuple(intents.values()):
        if not re.fullmatch(r"[\u3400-\u9fff]+", seed.term) or len(seed.term) < 3:
            continue
        for index in range(len(seed.term) - 1):
            morpheme = seed.term[index : index + 2]
            if morpheme in _RETRIEVAL_STOP_TERMS_815:
                continue
            seen_pages = sum(morpheme in page for page in corpus_pages)
            if seen_pages == 0 or seen_pages > ceiling:
                continue
            add(
                morpheme,
                weight=max(2, seed.weight // 2),
                dimension=seed.dimension,
                negative=seed.negative,
            )
    return tuple(
        sorted(
            intents.values(),
            key=lambda item: (
                item.negative,
                -item.weight,
                item.dimension,
                item.term,
            ),
        )
    )


def _intent_page_frequencies_815(
    *,
    intents: tuple[_RetrievalIntent815, ...],
    corpus_pages: tuple[str, ...],
) -> dict[str, int]:
    return {
        term: sum(term in page for page in corpus_pages)
        for term in dict.fromkeys(item.term for item in intents)
    }


def _normalized_span_text_815(value: NativeTextSpan815V1) -> str:
    return unicodedata.normalize("NFKC", value.exact_text)


def _is_clause_start_815(value: NativeTextSpan815V1) -> bool:
    return _CLAUSE_START_815.match(_normalized_span_text_815(value)) is not None


def _is_toc_line_815(value: NativeTextSpan815V1) -> bool:
    return _TOC_LINE_815.search(_normalized_span_text_815(value)) is not None


def _is_section_icon_start_815(value: NativeTextSpan815V1) -> bool:
    text = value.exact_text.lstrip()
    if len(text) < 2 or text[1:].strip() == "":
        return False
    return (
        "\ue000" <= text[0] <= "\uf8ff"
        or "\u2460" <= text[0] <= "\u24ff"
        or "\u25a0" <= text[0] <= "\u27bf"
    )


def _span_top_815(value: NativeTextSpan815V1) -> Decimal:
    return min(Decimal(rect[1]) for rect in value.rects)


def _span_bottom_815(value: NativeTextSpan815V1) -> Decimal:
    return max(Decimal(rect[3]) for rect in value.rects)


def _span_left_815(value: NativeTextSpan815V1) -> Decimal:
    return min(Decimal(rect[0]) for rect in value.rects)


def _span_right_815(value: NativeTextSpan815V1) -> Decimal:
    return max(Decimal(rect[2]) for rect in value.rects)


def _span_line_height_815(value: NativeTextSpan815V1) -> Decimal:
    return max(Decimal(rect[3]) - Decimal(rect[1]) for rect in value.rects)


def _is_page_number_line_815(
    value: NativeTextSpan815V1, page: NativePdfPageProjection815V1
) -> bool:
    return (
        _normalized_span_text_815(value).strip().isdecimal()
        and _span_top_815(value)
        >= Decimal(page.page_height_points) * _PAGE_NUMBER_TAIL_FRACTION_815
    )


def _has_positive_area_overlap_815(left: NativeBBox, right: NativeBBox) -> bool:
    return (
        min(Decimal(left[2]), Decimal(right[2])) > max(Decimal(left[0]), Decimal(right[0]))
        and min(Decimal(left[3]), Decimal(right[3])) > max(Decimal(left[1]), Decimal(right[1]))
    )


def _is_table_overlap_line_815(
    value: NativeTextSpan815V1, page: NativePdfPageProjection815V1
) -> bool:
    return any(
        _has_positive_area_overlap_815(rect, cell.bbox)
        for rect in value.rects
        for cell in page.cells
    )


def _is_clause_eligible_815(
    value: NativeTextSpan815V1, page: NativePdfPageProjection815V1
) -> bool:
    return (
        bool(_normalized_span_text_815(value).strip())
        and not _is_toc_line_815(value)
        and not _is_page_number_line_815(value, page)
        and not _is_table_overlap_line_815(value, page)
    )


def _is_uniconed_section_context_815(value: NativeTextSpan815V1) -> bool:
    """Recognize uniconed context without turning it into a clause boundary."""

    text = _normalized_span_text_815(value).strip()
    return bool(text) and text[-1] not in _HEADING_TERMINAL_PUNCTUATION_815


def _eligible_page_line_height_815(page: NativePdfPageProjection815V1) -> Decimal:
    heights = sorted(
        _span_line_height_815(value)
        for value in page.spans
        if _is_clause_eligible_815(value, page)
    )
    if len(heights) >= 3:
        middle = len(heights) // 2
        if len(heights) % 2:
            return heights[middle]
        return (heights[middle - 1] + heights[middle]) / Decimal(2)
    if heights:
        return max(heights)
    return Decimal(0)


def _contiguous_clause_groups_815(
    page: NativePdfPageProjection815V1,
) -> tuple[tuple[NativeTextSpan815V1, ...], ...]:
    """Return complete same-page clauses using only frozen span text and geometry."""

    ordered = tuple(sorted(page.spans, key=lambda value: (value.char_start, value.char_end)))
    eligible_height = _eligible_page_line_height_815(page)
    groups: list[tuple[NativeTextSpan815V1, ...]] = []
    for start_index, start in enumerate(ordered):
        if not _is_clause_start_815(start) or not _is_clause_eligible_815(start, page):
            continue
        group = [start]
        current = start
        for candidate in ordered[start_index + 1 :]:
            if (
                candidate.char_start != current.char_end + 1
                or _span_top_815(candidate) < _span_top_815(current)
                or _span_top_815(candidate) - _span_bottom_815(current)
                > _CLAUSE_VERTICAL_GAP_MULTIPLIER_815 * eligible_height
                or _is_clause_start_815(candidate)
                or _is_section_icon_start_815(candidate)
                or not _is_clause_eligible_815(candidate, page)
            ):
                break
            group.append(candidate)
            current = candidate
        groups.append(tuple(group))
    return tuple(groups)


def _contiguous_paragraph_groups_815(
    page: NativePdfPageProjection815V1,
    *,
    clause_span_ids: frozenset[str],
) -> tuple[tuple[NativeTextSpan815V1, ...], ...]:
    """Return wrapped non-heading paragraphs without crossing native boundaries."""

    ordered = tuple(sorted(page.spans, key=lambda value: (value.char_start, value.char_end)))
    eligible_height = _eligible_page_line_height_815(page)
    maximum_gap = _CLAUSE_VERTICAL_GAP_MULTIPLIER_815 * eligible_height
    groups: list[tuple[NativeTextSpan815V1, ...]] = []
    for start_index, start in enumerate(ordered):
        if (
            start.span_id in clause_span_ids
            or _is_clause_start_815(start)
            or _is_section_icon_start_815(start)
            or not _is_clause_eligible_815(start, page)
        ):
            continue
        previous = ordered[start_index - 1] if start_index else None
        if (
            previous is not None
            and previous.span_id not in clause_span_ids
            and _is_clause_eligible_815(previous, page)
            and _span_top_815(start) >= _span_top_815(previous)
            and _span_top_815(start) - _span_bottom_815(previous) <= maximum_gap
        ):
            continue
        group = [start]
        current = start
        for candidate in ordered[start_index + 1 :]:
            if (
                candidate.span_id in clause_span_ids
                or candidate.char_start != current.char_end + 1
                or _span_top_815(candidate) < _span_top_815(current)
                or _span_top_815(candidate) - _span_bottom_815(current) > maximum_gap
                or _span_left_815(candidate) != _span_left_815(current)
                or _is_clause_start_815(candidate)
                or _is_section_icon_start_815(candidate)
                or not _is_clause_eligible_815(candidate, page)
                or _span_right_815(current)
                < Decimal(page.page_width_points) * _PARAGRAPH_WRAP_RIGHT_FRACTION_815
            ):
                break
            group.append(candidate)
            current = candidate
        if len(group) > 1:
            groups.append(tuple(group))
    return tuple(groups)


def _integer_list_item_ordinal_815(value: NativeTextSpan815V1) -> int | None:
    match = _INTEGER_LIST_ITEM_START_815.match(_normalized_span_text_815(value))
    return int(match.group("ordinal")) if match is not None else None


def _contiguous_integer_list_item_groups_815(
    page: NativePdfPageProjection815V1,
    *,
    existing_groups: tuple[tuple[NativeTextSpan815V1, ...], ...],
) -> tuple[tuple[NativeTextSpan815V1, ...], ...]:
    """Bind unclaimed same-page runs of consecutive integer list items."""

    ordered = tuple(sorted(page.spans, key=lambda value: (value.char_start, value.char_end)))
    existing_span_ids = frozenset(
        span.span_id for group in existing_groups for span in group
    )
    starts = tuple(
        (index, span, ordinal)
        for index, span in enumerate(ordered)
        if (ordinal := _integer_list_item_ordinal_815(span)) is not None
        and _is_clause_eligible_815(span, page)
    )
    if not starts:
        return ()

    eligible_height = _eligible_page_line_height_815(page)
    maximum_gap = _CLAUSE_VERTICAL_GAP_MULTIPLIER_815 * eligible_height
    runs: list[list[tuple[int, NativeTextSpan815V1, int]]] = []
    current_run = [starts[0]]
    for item in starts[1:]:
        previous_position = current_run[-1][0]
        interval = ordered[previous_position : item[0] + 1]
        crosses_structural_boundary = any(
            _is_clause_start_815(span)
            or _is_section_icon_start_815(span)
            or not _is_clause_eligible_815(span, page)
            for span in interval[1:-1]
        )
        crosses_geometry_boundary = any(
            following.char_start != previous.char_end + 1
            or _span_top_815(following) < _span_top_815(previous)
            or _span_top_815(following) - _span_bottom_815(previous) > maximum_gap
            for previous, following in zip(interval[:-1], interval[1:], strict=True)
        )
        if (
            item[2] == current_run[-1][2] + 1
            and not crosses_structural_boundary
            and not crosses_geometry_boundary
        ):
            current_run.append(item)
        else:
            runs.append(current_run)
            current_run = [item]
    runs.append(current_run)

    next_start_by_id = {
        span.span_id: starts[index + 1][1].span_id
        for index, (_position, span, _ordinal) in enumerate(starts[:-1])
    }
    groups: list[tuple[NativeTextSpan815V1, ...]] = []
    for run in runs:
        if len(run) < 2 or any(
            span.span_id in existing_span_ids for _index, span, _ordinal in run
        ):
            continue
        for start_index, start, _ordinal in run:
            next_start_id = next_start_by_id.get(start.span_id)
            group = [start]
            current = start
            for candidate in ordered[start_index + 1 :]:
                if (
                    candidate.span_id == next_start_id
                    or _integer_list_item_ordinal_815(candidate) is not None
                    or candidate.span_id in existing_span_ids
                    or candidate.char_start != current.char_end + 1
                    or _span_top_815(candidate) < _span_top_815(current)
                    or _span_top_815(candidate) - _span_bottom_815(current) > maximum_gap
                    or _is_clause_start_815(candidate)
                    or _is_section_icon_start_815(candidate)
                    or not _is_clause_eligible_815(candidate, page)
                    or _span_right_815(current)
                    < Decimal(page.page_width_points)
                    * _PARAGRAPH_WRAP_RIGHT_FRACTION_815
                ):
                    break
                group.append(candidate)
                current = candidate
            groups.append(tuple(group))
    return tuple(groups)


def _is_context_chain_link_815(
    previous: NativeTextSpan815V1,
    following: NativeTextSpan815V1,
    page: NativePdfPageProjection815V1,
    eligible_line_height: Decimal,
) -> bool:
    return (
        _is_clause_eligible_815(previous, page)
        and _is_clause_eligible_815(following, page)
        and not _is_clause_start_815(previous)
        and following.char_start == previous.char_end + 1
        and _span_top_815(following) >= _span_top_815(previous)
        and _span_top_815(following) - _span_bottom_815(previous)
        <= _CLAUSE_VERTICAL_GAP_MULTIPLIER_815 * eligible_line_height
    )


def _complete_clause_groups_815(
    page: NativePdfPageProjection815V1,
) -> tuple[_CompleteClauseGroup815, ...]:
    """Bind complete clauses and wrapped paragraphs to frozen native spans."""

    ordered = tuple(sorted(page.spans, key=lambda value: (value.char_start, value.char_end)))
    eligible_height = _eligible_page_line_height_815(page)
    positions = {value.span_id: index for index, value in enumerate(ordered)}
    clause_groups = _contiguous_clause_groups_815(page)
    clause_span_ids = frozenset(
        value.span_id for spans in clause_groups for value in spans
    )
    existing_groups = (
        *clause_groups,
        *_contiguous_paragraph_groups_815(
            page,
            clause_span_ids=clause_span_ids,
        ),
    )
    integer_groups = _contiguous_integer_list_item_groups_815(
        page,
        existing_groups=existing_groups,
    )
    integer_group_subject_ids = frozenset(
        tuple(span.span_id for span in spans) for spans in integer_groups
    )
    source_groups = tuple(
        sorted(
            (
                *existing_groups,
                *integer_groups,
            ),
            key=lambda spans: (spans[0].char_start, spans[-1].char_end),
        )
    )
    groups: list[_CompleteClauseGroup815] = []
    prior_group_span_ids: set[str] = set()
    for spans in source_groups:
        context: str | None = None
        following = spans[0]
        for previous in reversed(ordered[: positions[spans[0].span_id]]):
            if previous.span_id in prior_group_span_ids or not _is_context_chain_link_815(
                previous, following, page, eligible_height
            ):
                break
            if _is_section_icon_start_815(previous) or _is_uniconed_section_context_815(
                previous
            ):
                context = previous.exact_text
                break
            following = previous
        groups.append(
            _CompleteClauseGroup815(
                spans=spans,
                ranking_context=context,
                content_priority=(
                    1
                    if tuple(span.span_id for span in spans)
                    in integer_group_subject_ids
                    else 0
                ),
            )
        )
        prior_group_span_ids.update(value.span_id for value in spans)
    return tuple(groups)


def _selection(
    *,
    selection_type: SelectionType815,
    field_id: str,
    source: NativePdfSelectionProjection815V1,
    subject_ids: tuple[str, ...],
    page_numbers: tuple[int, ...],
    exact_text_parts: tuple[str, ...],
    value_part_groups: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...],
) -> NativePdfSelection815V1:
    value_parts = tuple(
        _value_part(subject_ids=part_subject_ids, exact_text_parts=part_text_parts)
        for part_subject_ids, part_text_parts in value_part_groups
    )
    provisional = NativePdfSelection815V1(
        selection_id="",
        selection_type=selection_type,
        field_id=field_id,
        source_role=source.source_role,
        source_revision_id=source.source_revision_id,
        parse_manifest_sha256=source.parse_manifest_sha256,
        subject_ids=subject_ids,
        page_numbers=page_numbers,
        exact_text_parts=exact_text_parts,
        display_policy=_display_policy_815(field_id),
        value_parts=value_parts,
        selection_sha256="",
    )
    digest = provisional.recomputed_selection_sha256()
    return replace(
        provisional,
        selection_id=f"selection-{digest}",
        selection_sha256=digest,
    )


def _display_policy_815(field_id: str) -> DisplayPolicy815:
    return "EXTRACTIVE_LONG" if field_id in _EXTRACTIVE_LONG_FIELD_IDS_815 else "EXACT_SHORT"


def _value_part(
    *,
    subject_ids: tuple[str, ...],
    exact_text_parts: tuple[str, ...],
) -> NativePdfValuePart815V1:
    provisional = NativePdfValuePart815V1(
        value_part_id="",
        subject_ids=subject_ids,
        exact_text_parts=exact_text_parts,
        value_part_sha256="",
    )
    digest = provisional.recomputed_value_part_sha256()
    return replace(
        provisional,
        value_part_id=f"value-part-{digest}",
        value_part_sha256=digest,
    )


def _text_value_part_groups_815(
    spans: tuple[NativeTextSpan815V1, ...],
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """Partition a complete group only at native sentence/list boundaries."""

    groups: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    subject_ids: list[str] = []
    texts: list[str] = []
    for span in spans:
        subject_ids.append(span.span_id)
        texts.append(span.exact_text)
        stripped = span.exact_text.rstrip()
        if stripped.endswith(("：", ":")):
            continue
        if stripped.endswith(("。", "！", "？", "；", ";")):
            groups.append((tuple(subject_ids), tuple(texts)))
            subject_ids = []
            texts = []
    if subject_ids:
        groups.append((tuple(subject_ids), tuple(texts)))
    return tuple(groups)


def _score(
    *,
    intents: tuple[_RetrievalIntent815, ...],
    page_frequencies: dict[str, int],
    corpus_page_count: int,
    exact_text_parts: tuple[str, ...],
) -> int:
    source_text = _normalize_retrieval_text("\n".join(exact_text_parts))
    score = 0
    matched_dimensions: set[str] = set()
    positive_match = False
    for intent in intents:
        if intent.term not in source_text:
            continue
        specificity = 1 + (
            max(0, corpus_page_count - page_frequencies.get(intent.term, 0)) * 4
        ) // max(1, corpus_page_count)
        contribution = intent.weight * specificity
        if intent.negative:
            score -= contribution * 2
            continue
        positive_match = True
        score += contribution
        matched_dimensions.add(intent.dimension)
    if not positive_match:
        return 0
    return score + len(matched_dimensions) * 20


def _table_slice_is_contextual(value: NativeTableSlice815V1) -> bool:
    parts = tuple(part for part in value.exact_text_parts if part)
    return (
        len(parts) >= 4
        and len(value.ordered_cell_ids) == len(parts)
        and any(character.isalpha() for part in parts[:2] for character in part)
        and any(character.isalpha() for part in parts[2:] for character in part)
    )


def _rank_span(
    *,
    contract: FieldContractV1,
    intents: tuple[_RetrievalIntent815, ...],
    page_frequencies: dict[str, int],
    corpus_page_count: int,
    source: NativePdfSelectionProjection815V1,
    value: NativeTextSpan815V1,
) -> _RankedSelection815 | None:
    score = _score(
        intents=intents,
        page_frequencies=page_frequencies,
        corpus_page_count=corpus_page_count,
        exact_text_parts=(value.exact_text,),
    )
    if score <= 0:
        return None
    selection = _selection(
        selection_type="TEXT_SPAN",
        field_id=contract.field_id,
        source=source,
        subject_ids=(value.span_id,),
        page_numbers=(value.page_number,),
        exact_text_parts=(value.exact_text,),
        value_part_groups=(((value.span_id,), (value.exact_text,)),),
    )
    return _RankedSelection815(
        content_priority=(
            4
            if _is_toc_line_815(value)
            else 2
            if _normalized_span_text_815(value).startswith(("这部分讲的是", "本部分讲的是"))
            else 3
        ),
        score=score,
        role_order=_ROLE_ORDER.index(source.source_role),
        first_page=value.page_number,
        first_order=(value.char_start, value.char_end),
        selection=selection,
    )


def _rank_clause_group_815(
    *,
    contract: FieldContractV1,
    intents: tuple[_RetrievalIntent815, ...],
    page_frequencies: dict[str, int],
    corpus_page_count: int,
    source: NativePdfSelectionProjection815V1,
    value: _CompleteClauseGroup815,
) -> _RankedSelection815 | None:
    if value.content_priority == 1:
        return None
    values = value.spans
    ranking_parts = (
        (value.ranking_context, *tuple(item.exact_text for item in values))
        if value.ranking_context is not None
        else tuple(item.exact_text for item in values)
    )
    score = _score(
        intents=intents,
        page_frequencies=page_frequencies,
        corpus_page_count=corpus_page_count,
        exact_text_parts=ranking_parts,
    )
    if score <= 0:
        return None
    selection = _selection(
        selection_type="TEXT_SPAN",
        field_id=contract.field_id,
        source=source,
        subject_ids=tuple(value.span_id for value in values),
        page_numbers=(values[0].page_number,),
        exact_text_parts=tuple(value.exact_text for value in values),
        value_part_groups=_text_value_part_groups_815(values),
    )
    return _RankedSelection815(
        content_priority=value.content_priority,
        score=score,
        role_order=_ROLE_ORDER.index(source.source_role),
        first_page=values[0].page_number,
        first_order=(values[0].char_start, values[-1].char_end),
        selection=selection,
    )


def _rank_table_slice(
    *,
    contract: FieldContractV1,
    intents: tuple[_RetrievalIntent815, ...],
    page_frequencies: dict[str, int],
    corpus_page_count: int,
    source: NativePdfSelectionProjection815V1,
    value: NativeTableSlice815V1,
    first_cell_order: tuple[int, int],
) -> _RankedSelection815 | None:
    if not _table_slice_is_contextual(value) or any(
        "\r" in item or "\n" in item for item in value.exact_text_parts
    ):
        return None
    score = _score(
        intents=intents,
        page_frequencies=page_frequencies,
        corpus_page_count=corpus_page_count,
        exact_text_parts=value.exact_text_parts,
    )
    if score <= 0:
        return None
    if _NUMERIC_PATTERN.search("\n".join(value.exact_text_parts)):
        score += 1
    selection = _selection(
        selection_type="TABLE_SLICE",
        field_id=contract.field_id,
        source=source,
        subject_ids=value.ordered_cell_ids,
        page_numbers=value.page_numbers,
        exact_text_parts=value.exact_text_parts,
        value_part_groups=((value.ordered_cell_ids, value.exact_text_parts),),
    )
    return _RankedSelection815(
        content_priority=1,
        score=score,
        role_order=_ROLE_ORDER.index(source.source_role),
        first_page=value.page_numbers[0],
        first_order=first_cell_order,
        selection=selection,
    )


def _ranked_source_selections(
    *,
    contract: FieldContractV1,
    intents: tuple[_RetrievalIntent815, ...],
    page_frequencies: dict[str, int],
    corpus_page_count: int,
    source: NativePdfSelectionProjection815V1,
    clause_groups_by_page: tuple[tuple[_CompleteClauseGroup815, ...], ...],
) -> tuple[_RankedSelection815, ...]:
    if len(clause_groups_by_page) != len(source.pages):
        raise NativePdfSelectionError815("SOURCE_PROJECTION_INVALID")
    ranked: list[_RankedSelection815] = []
    for page, clause_groups in zip(source.pages, clause_groups_by_page, strict=True):
        if page.page_text_sha256 != hashlib.sha256(
            page.canonical_page_text.encode()
        ).hexdigest():
            raise NativePdfSelectionError815("SOURCE_PROJECTION_INVALID")
        for span in page.spans:
            if (
                span.page_number != page.page_number
                or page.canonical_page_text[span.char_start : span.char_end]
                != span.exact_text
                or span.text_sha256
                != hashlib.sha256(span.exact_text.encode()).hexdigest()
            ):
                raise NativePdfSelectionError815("SOURCE_PROJECTION_INVALID")
        cells = {cell.cell_id: cell for cell in page.cells}
        if len(cells) != len(page.cells):
            raise NativePdfSelectionError815("SOURCE_PROJECTION_INVALID")
        clause_member_ids = {
            value.span_id
            for group in clause_groups
            if group.content_priority != 1
            for value in group.spans
        }
        for group in clause_groups:
            item = _rank_clause_group_815(
                contract=contract,
                intents=intents,
                page_frequencies=page_frequencies,
                corpus_page_count=corpus_page_count,
                source=source,
                value=group,
            )
            if item is not None:
                ranked.append(item)
        for span in page.spans:
            if span.span_id in clause_member_ids:
                continue
            item = _rank_span(
                contract=contract,
                intents=intents,
                page_frequencies=page_frequencies,
                corpus_page_count=corpus_page_count,
                source=source,
                value=span,
            )
            if item is not None:
                ranked.append(item)
        for table_slice in page.table_slices:
            try:
                slice_cells = tuple(cells[cell_id] for cell_id in table_slice.ordered_cell_ids)
            except KeyError:
                raise NativePdfSelectionError815("SOURCE_PROJECTION_INVALID") from None
            if (
                not slice_cells
                or table_slice.page_numbers != (page.page_number,)
                or any(cell.table_id != table_slice.table_id for cell in slice_cells)
                or tuple(cell.exact_text for cell in slice_cells if cell.exact_text)
                != table_slice.exact_text_parts
            ):
                raise NativePdfSelectionError815("SOURCE_PROJECTION_INVALID")
            item = _rank_table_slice(
                contract=contract,
                intents=intents,
                page_frequencies=page_frequencies,
                corpus_page_count=corpus_page_count,
                source=source,
                value=table_slice,
                first_cell_order=(slice_cells[0].row_index, slice_cells[0].column_index),
            )
            if item is not None:
                ranked.append(item)
    return tuple(ranked)


def _validate_inputs(
    *,
    field_contracts: FieldContractSetV1,
    provider_visible_field_ids: tuple[str, ...],
    available_source_roles: tuple[MaterialRole, ...],
    source_projections: tuple[NativePdfSelectionProjection815V1, ...],
) -> tuple[FieldContractSetV1, tuple[NativePdfSelectionProjection815V1, ...]]:
    try:
        exact = FieldContractSetV1.model_validate(
            field_contracts.model_dump(mode="python", round_trip=True)
        )
    except (AttributeError, TypeError, ValueError):
        raise NativePdfSelectionError815("FIELD_SELECTION_INPUT_INVALID") from None
    if (
        type(provider_visible_field_ids) is not tuple
        or type(available_source_roles) is not tuple
        or type(source_projections) is not tuple
        or available_source_roles
        != tuple(role for role in _ROLE_ORDER if role in available_source_roles)
        or len(available_source_roles) != len(set(available_source_roles))
        or tuple(item.source_role for item in source_projections)
        != available_source_roles
    ):
        raise NativePdfSelectionError815("FIELD_SELECTION_INPUT_INVALID")
    available = frozenset(available_source_roles)
    expected_visible = tuple(
        contract.field_id
        for contract in exact.contracts
        if contract.formation_modes == ("source_extract",)
        and any(role in available for role in contract.source_roles)
    )
    if provider_visible_field_ids != expected_visible:
        raise NativePdfSelectionError815("FIELD_SELECTION_INPUT_INVALID")
    for source in source_projections:
        if (
            type(source) is not NativePdfSelectionProjection815V1
            or source.parse_manifest_sha256 != source.recomputed_manifest_sha256()
        ):
            raise NativePdfSelectionError815("SOURCE_PROJECTION_INVALID")
    return exact, source_projections


def _field_catalog(
    *,
    contract: FieldContractV1,
    available_source_roles: tuple[MaterialRole, ...],
    source_projections: tuple[NativePdfSelectionProjection815V1, ...],
    source_clause_groups: dict[
        MaterialRole, tuple[tuple[_CompleteClauseGroup815, ...], ...]
    ],
) -> FieldSelectionCatalog815V1:
    allowed_roles = cast(
        tuple[MaterialRole, ...],
        tuple(
            role
            for role in _ROLE_ORDER
            if role in available_source_roles and role in contract.source_roles
        ),
    )
    corpus_pages = tuple(
        _normalize_retrieval_text(page.canonical_page_text)
        for source in source_projections
        if source.source_role in allowed_roles
        for page in source.pages
    )
    intents = _retrieval_intents_815(
        contract=contract,
        corpus_pages=corpus_pages,
    )
    page_frequencies = _intent_page_frequencies_815(
        intents=intents,
        corpus_pages=corpus_pages,
    )
    retrieval_policy_sha256 = canonical_hash(
        "schema67-native-pdf-retrieval-policy.815.v2",
        {
            "contract_sha256": contract.field_contract_sha256,
            "intents": tuple(asdict(item) for item in intents),
            "page_frequencies": tuple(
                (term, page_frequencies[term]) for term in sorted(page_frequencies)
            ),
            "corpus_page_count": len(corpus_pages),
            "allowed_source_roles": allowed_roles,
            "normalization": "NFKC_ASCII_LOWER_V1",
            "score": (
                "WEIGHTED_SCHEMA_INTENT_DIMENSION_CORPUS_SPECIFICITY_"
                "COMPLETE_CLAUSE_CONTEXT_V3"
            ),
            "sort": "CONTENT_PRIORITY_SCORE_ROLE_PAGE_RANGE_SELECTION_ID_V2",
            "max_selections": _MAX_SELECTIONS_PER_FIELD,
            "max_table_selections": _MAX_TABLE_SELECTIONS_PER_FIELD,
            "max_provider_selection_bytes_per_field": (
                _MAX_PROVIDER_SELECTION_BYTES_PER_FIELD_815
            ),
        },
    )
    ranked = tuple(
        item
        for source in source_projections
        if source.source_role in allowed_roles
        for item in _ranked_source_selections(
            contract=contract,
            intents=intents,
            page_frequencies=page_frequencies,
            corpus_page_count=max(1, len(corpus_pages)),
            source=source,
            clause_groups_by_page=source_clause_groups[source.source_role],
        )
    )
    ordered = sorted(
        ranked,
        key=lambda item: (
            item.content_priority,
            -item.score,
            item.role_order,
            item.first_page,
            item.first_order,
            item.selection.selection_id,
        ),
    )
    selected: list[NativePdfSelection815V1] = []
    selected_prompt_bytes = 0
    table_count = 0
    for item in ordered:
        if len(selected) >= _MAX_SELECTIONS_PER_FIELD:
            break
        selection_prompt_bytes = _selection_prompt_byte_size_815(item.selection)
        if (
            selected_prompt_bytes + selection_prompt_bytes
            > _MAX_PROVIDER_SELECTION_BYTES_PER_FIELD_815
        ):
            continue
        if item.selection.selection_type == "TABLE_SLICE":
            if table_count >= _MAX_TABLE_SELECTIONS_PER_FIELD:
                continue
            table_count += 1
        selected.append(item.selection)
        selected_prompt_bytes += selection_prompt_bytes
    provisional = FieldSelectionCatalog815V1(
        field_id=contract.field_id,
        allowed_source_roles=allowed_roles,
        selections=tuple(selected),
        retrieval_policy_sha256=retrieval_policy_sha256,
        catalog_sha256="",
    )
    return replace(
        provisional,
        catalog_sha256=provisional.recomputed_catalog_sha256(),
    )


def build_field_selection_catalogs_815(
    *,
    field_contracts: FieldContractSetV1,
    provider_visible_field_ids: tuple[str, ...],
    available_source_roles: tuple[MaterialRole, ...],
    source_projections: tuple[NativePdfSelectionProjection815V1, ...],
) -> Schema67SelectionCatalog815V1:
    """Build bounded native-PDF selections without importing the DeepSeek owner."""

    exact, sources = _validate_inputs(
        field_contracts=field_contracts,
        provider_visible_field_ids=provider_visible_field_ids,
        available_source_roles=available_source_roles,
        source_projections=source_projections,
    )
    contracts_by_id = {item.field_id: item for item in exact.contracts}
    source_clause_groups = {
        source.source_role: tuple(
            _complete_clause_groups_815(page) for page in source.pages
        )
        for source in sources
    }
    fields = tuple(
        _field_catalog(
            contract=contracts_by_id[field_id],
            available_source_roles=available_source_roles,
            source_projections=sources,
            source_clause_groups=source_clause_groups,
        )
        for field_id in provider_visible_field_ids
    )
    provisional = Schema67SelectionCatalog815V1(
        contract=_CATALOG_CONTRACT,
        provider_visible_field_ids=provider_visible_field_ids,
        fields=fields,
        catalog_sha256="",
    )
    return replace(
        provisional,
        catalog_sha256=provisional.recomputed_catalog_sha256(),
    )


def _require_exact_field_catalogs_815(
    value: tuple[FieldSelectionCatalog815V1, ...],
) -> tuple[FieldSelectionCatalog815V1, ...]:
    if (
        type(value) is not tuple
        or not value
        or len({item.field_id for item in value}) != len(value)
    ):
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    for field_catalog in value:
        if (
            type(field_catalog) is not FieldSelectionCatalog815V1
            or field_catalog.catalog_sha256
            != field_catalog.recomputed_catalog_sha256()
            or len({item.selection_id for item in field_catalog.selections})
            != len(field_catalog.selections)
            or any(
                item.field_id != field_catalog.field_id
                or item.source_role not in field_catalog.allowed_source_roles
                or item.display_policy != _display_policy_815(item.field_id)
                or not item.subject_ids
                or len(item.subject_ids) != len(item.exact_text_parts)
                or not item.page_numbers
                or (
                    item.selection_type == "TEXT_SPAN"
                    and len(item.page_numbers) != 1
                )
                or (
                    item.selection_type == "TABLE_SLICE"
                    and len(item.page_numbers) != len(set(item.page_numbers))
                )
                or not item.value_parts
                or tuple(
                    subject_id
                    for part in item.value_parts
                    for subject_id in part.subject_ids
                )
                != item.subject_ids
                or tuple(
                    text
                    for part in item.value_parts
                    for text in part.exact_text_parts
                )
                != item.exact_text_parts
                or len({part.value_part_id for part in item.value_parts})
                != len(item.value_parts)
                or any(
                    part.value_part_sha256
                    != part.recomputed_value_part_sha256()
                    or part.value_part_id != f"value-part-{part.value_part_sha256}"
                    or not part.subject_ids
                    or len(part.subject_ids) != len(part.exact_text_parts)
                    for part in item.value_parts
                )
                or item.selection_sha256 != item.recomputed_selection_sha256()
                or item.selection_id != f"selection-{item.selection_sha256}"
                for item in field_catalog.selections
            )
        ):
            raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    return value


def require_model_selection_response_815(
    value: object,
    *,
    task_key: str,
    field_catalogs: tuple[FieldSelectionCatalog815V1, ...],
) -> ModelTaskSelectionResponse815V1:
    """Require the closed model response without accepting source content."""

    exact_catalogs = _require_exact_field_catalogs_815(field_catalogs)
    try:
        exact = ModelTaskSelectionResponse815V1.model_validate(value)
    except (TypeError, ValueError, ValidationError):
        raise NativePdfSelectionError815("SELECTION_RESPONSE_SHAPE_INVALID") from None
    if (
        exact.task_key != task_key
        or tuple(item.field_id for item in exact.fields)
        != tuple(item.field_id for item in exact_catalogs)
    ):
        raise NativePdfSelectionError815("SELECTION_RESPONSE_SHAPE_INVALID")
    return exact


def _require_projection_sources_815(
    *,
    source_projections: tuple[NativePdfSelectionProjection815V1, ...],
    admitted_sources: tuple[AdmittedParseArtifactV1, ...],
) -> tuple[
    dict[MaterialRole, NativePdfSelectionProjection815V1],
    dict[MaterialRole, AdmittedParseArtifactV1],
    dict[MaterialRole, _AdmittedSourceIdentityProjection815],
]:
    if (
        type(source_projections) is not tuple
        or type(admitted_sources) is not tuple
        or len({item.source_role for item in source_projections})
        != len(source_projections)
        or len({item.role for item in admitted_sources}) != len(admitted_sources)
    ):
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    projections: dict[MaterialRole, NativePdfSelectionProjection815V1] = {}
    for projection_item in source_projections:
        if (
            type(projection_item) is not NativePdfSelectionProjection815V1
            or projection_item.parse_manifest_sha256
            != projection_item.recomputed_manifest_sha256()
        ):
            raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
        projections[projection_item.source_role] = projection_item
    exact_sources, exact_identities = _revalidate_admitted_sources_815(
        admitted_sources
    )
    if (
        len(exact_sources) != len(exact_identities)
        or tuple(item.role for item in exact_sources)
        != tuple(item.role for item in exact_identities)
        or len({item.role for item in exact_identities}) != len(exact_identities)
    ):
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    admitted: dict[MaterialRole, AdmittedParseArtifactV1] = {}
    identities: dict[MaterialRole, _AdmittedSourceIdentityProjection815] = {}
    for admitted_item, identity in zip(exact_sources, exact_identities, strict=True):
        document = admitted_item.document
        manifest = admitted_item.manifest
        decision = admitted_item.decision
        if (
            admitted_item.role != identity.role
            or admitted_item.source_sha256 != document.subject.source_sha256
            or admitted_item.artifact_sha256 != identity.document_hash
            or admitted_item.manifest_sha256 != identity.manifest_hash
            or admitted_item.decision_sha256 != identity.decision_hash
            or manifest.document_hash != identity.document_hash
            or decision.manifest_hash != identity.manifest_hash
            or decision.decision != "ADMIT"
            or decision.admitted_attempt_id != document.attempt.attempt_id
            or document.subject != manifest.subject
            or document.subject != decision.subject
            or document.parser != manifest.parser
            or document.attempt != manifest.attempt
            or document.snapshot != manifest.snapshot
            or document.output_facts != manifest.output_facts
        ):
            raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
        admitted[admitted_item.role] = admitted_item
        identities[identity.role] = identity
    return projections, admitted, identities


def _revalidate_admitted_sources_815(
    admitted_sources: tuple[AdmittedParseArtifactV1, ...],
) -> tuple[
    tuple[AdmittedParseArtifactV1, ...],
    tuple[_AdmittedSourceIdentityProjection815, ...],
]:
    if type(admitted_sources) is not tuple:
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    exact_sources: list[AdmittedParseArtifactV1] = []
    identities: list[_AdmittedSourceIdentityProjection815] = []
    for admitted_item in admitted_sources:
        try:
            document = ParsedDocumentV1.model_validate(
                admitted_item.document.model_dump(
                    mode="python", exclude={"document_hash"}
                )
            )
            manifest = ParseManifestV1.model_validate(
                admitted_item.manifest.model_dump(
                    mode="python", exclude={"manifest_hash"}
                )
            )
            decision = ParseQualityDecisionV1.model_validate(
                admitted_item.decision.model_dump(
                    mode="python", exclude={"decision_hash"}
                )
            )
            document_hash = document.document_hash
            manifest_hash = manifest.manifest_hash
            decision_hash = decision.decision_hash
        except (AttributeError, TypeError, ValueError, ValidationError):
            raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID") from None
        if (
            document != admitted_item.document
            or manifest != admitted_item.manifest
            or decision != admitted_item.decision
            or admitted_item.source_sha256 != document.subject.source_sha256
            or admitted_item.artifact_sha256 != document_hash
            or admitted_item.manifest_sha256 != manifest_hash
            or admitted_item.decision_sha256 != decision_hash
            or manifest.document_hash != document_hash
            or decision.manifest_hash != manifest_hash
            or decision.decision != "ADMIT"
            or decision.admitted_attempt_id != document.attempt.attempt_id
            or document.subject != manifest.subject
            or document.subject != decision.subject
            or document.parser != manifest.parser
            or document.attempt != manifest.attempt
            or document.snapshot != manifest.snapshot
            or document.output_facts != manifest.output_facts
        ):
            raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
        exact_source = replace(
            admitted_item,
            document=document,
            manifest=manifest,
            decision=decision,
        )
        exact_sources.append(exact_source)
        identities.append(
            _AdmittedSourceIdentityProjection815(
                role=admitted_item.role,
                document_hash=document_hash,
                manifest_hash=manifest_hash,
                decision_hash=decision_hash,
            )
        )
    return tuple(exact_sources), tuple(identities)


def _freeform_evidence_815(
    *,
    field_id: str,
    source: AdmittedParseArtifactV1,
    subject_ref: str,
    quote: str,
) -> FreeformEvidenceV1:
    fact = evidence_verifier._locator_fact(source.document, subject_ref)
    if fact is None:
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    kind, page_number, parent_refs, content_hash = fact
    quote_sha256 = hashlib.sha256(quote.encode()).hexdigest()
    if not evidence_verifier._content_snapshot_matches(
        document=source.document,
        kind=kind,
        content_snapshot=quote,
        content_snapshot_sha256=quote_sha256,
        parsed_content_hash=content_hash,
    ):
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    cell = next(
        (item for item in source.document.cells if item.cell_id == subject_ref),
        None,
    )
    return FreeformEvidenceV1(
        field_id=field_id,
        source_sha256=source.document.subject.source_sha256,
        source_revision_id=source.document.subject.source_revision_id,
        parse_attempt_id=source.document.attempt.attempt_id,
        parsed_document_hash=source.artifact_sha256,
        parse_manifest_hash=source.manifest_sha256,
        page_number=page_number,
        block_id=subject_ref if kind == "block" else None,
        table_id=cell.table_id if cell is not None else None,
        cell_id=cell.cell_id if cell is not None else None,
        row_index=cell.locator.row_index if cell is not None else None,
        column_index=cell.locator.column_index if cell is not None else None,
        row_span=cell.locator.row_span if cell is not None else None,
        column_span=cell.locator.column_span if cell is not None else None,
        locator=EvidenceLocatorSnapshotV1(
            subject_type=kind,
            subject_ref=subject_ref,
            page_number=page_number,
            parent_refs=parent_refs,
            content_snapshot=quote,
            content_snapshot_sha256=quote_sha256,
        ),
        quote_snapshot=quote,
        quote_snapshot_sha256=quote_sha256,
    )


def _coordinate_child_selection_id_815(
    *,
    parent_selection_id: str,
    field_id: str,
    ordinal: int,
    span: NativeTextSpan815V1,
) -> str:
    return "selection-" + canonical_hash(
        "schema67-coordinate-child-selection.815.v1",
        {
            "parent_selection_id": parent_selection_id,
            "field_id": field_id,
            "ordinal": ordinal,
            "span_id": span.span_id,
            "page_number": span.page_number,
            "char_start": span.char_start,
            "char_end": span.char_end,
            "quote_sha256": span.text_sha256,
        },
    )


def _span_words_match_rects_815(
    page: NativePdfPageProjection815V1,
    span: NativeTextSpan815V1,
) -> bool:
    words = tuple(
        word
        for word in page.words
        if span.char_start <= word.char_start and word.char_end <= span.char_end
    )
    if (
        not words
        or any(
            word.char_start < span.char_start < word.char_end
            or word.char_start < span.char_end < word.char_end
            for word in page.words
        )
    ):
        return False
    cursor = span.char_start
    for ordinal, word in enumerate(words):
        if (
            word.char_start != cursor
            or word.char_start >= word.char_end
            or page.canonical_page_text[word.char_start : word.char_end] != word.text
        ):
            return False
        cursor = word.char_end + (1 if ordinal < len(words) - 1 else 0)
    return (
        cursor == span.char_end
        and span.exact_text == " ".join(word.text for word in words)
        and span.rects == (_union_native_bbox_815(tuple(word.bbox for word in words)),)
    )


def _span_selection_hydration_815(
    *,
    field_id: str,
    selection: NativePdfSelection815V1,
    projection: NativePdfSelectionProjection815V1,
    source: AdmittedParseArtifactV1,
) -> tuple[
    str,
    tuple[FreeformEvidenceV1, ...],
    tuple[CoordinateEvidence815V1, ...],
    tuple[int, ...],
]:
    if (
        not selection.subject_ids
        or len(selection.subject_ids) != len(set(selection.subject_ids))
        or len(selection.page_numbers) != 1
        or len(selection.exact_text_parts) != len(selection.subject_ids)
    ):
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    spans_by_id: dict[str, tuple[NativePdfPageProjection815V1, NativeTextSpan815V1]] = {}
    for page in projection.pages:
        for span in page.spans:
            if span.span_id in spans_by_id:
                raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
            spans_by_id[span.span_id] = (page, span)
    try:
        matches = tuple(spans_by_id[item] for item in selection.subject_ids)
    except KeyError:
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID") from None
    pages = tuple(item[0] for item in matches)
    spans = tuple(item[1] for item in matches)
    page = pages[0]
    if (
        any(item is not page for item in pages)
        or selection.page_numbers != (page.page_number,)
        or selection.exact_text_parts != tuple(item.exact_text for item in spans)
        or any(
            item.page_number != page.page_number
            or page.canonical_page_text[item.char_start : item.char_end]
            != item.exact_text
            or item.text_sha256 != hashlib.sha256(item.exact_text.encode()).hexdigest()
            or not _span_words_match_rects_815(page, item)
            for item in spans
        )
    ):
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    if len(spans) > 1 and not any(
        tuple(item.span_id for item in group.spans) == selection.subject_ids
        for group in _complete_clause_groups_815(page)
    ):
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    evidence = tuple(
        _freeform_evidence_815(
            field_id=field_id,
            source=source,
            subject_ref=span.parent_block_id,
            quote=span.exact_text,
        )
        for span in spans
    )
    coordinates = tuple(
        CoordinateEvidence815V1(
            field_id=field_id,
            source_revision_id=projection.source_revision_id,
            source_role=projection.source_role,
            original_file_sha256=projection.original_file_sha256,
            parse_manifest_sha256=projection.parse_manifest_sha256,
            selection_id=(
                selection.selection_id
                if len(spans) == 1
                else _coordinate_child_selection_id_815(
                    parent_selection_id=selection.selection_id,
                    field_id=field_id,
                    ordinal=ordinal,
                    span=span,
                )
            ),
            selection_type="TEXT_SPAN",
            page_number=span.page_number,
            page_text_char_start=span.char_start,
            page_text_char_end=span.char_end,
            coordinate_space=projection.coordinate_space,
            page_width_points=page.page_width_points,
            page_height_points=page.page_height_points,
            bbox=_union_native_bbox_815(span.rects),
            rects=span.rects,
            quote=span.exact_text,
            quote_sha256=span.text_sha256,
            block_id=span.parent_block_id,
            span_id=span.span_id,
        )
        for ordinal, span in enumerate(spans)
    )
    return (
        _VALUE_PART_SEPARATOR_815.join(item.exact_text for item in spans),
        evidence,
        coordinates,
        (
            _ROLE_ORDER.index(projection.source_role),
            spans[0].page_number,
            spans[0].char_start,
            spans[-1].char_end,
        ),
    )


def _table_selection_hydration_815(
    *,
    field_id: str,
    selection: NativePdfSelection815V1,
    projection: NativePdfSelectionProjection815V1,
    source: AdmittedParseArtifactV1,
) -> tuple[
    str,
    tuple[FreeformEvidenceV1, ...],
    tuple[CoordinateEvidence815V1, ...],
    tuple[int, ...],
]:
    matches = tuple(
        (page, item)
        for page in projection.pages
        for item in page.table_slices
        if item.table_slice_id == selection.selection_id.removeprefix("selection-")
        or item.ordered_cell_ids == selection.subject_ids
    )
    exact = tuple(
        (page, item)
        for page, item in matches
        if item.ordered_cell_ids == selection.subject_ids
        and item.page_numbers == selection.page_numbers
        and item.exact_text_parts == selection.exact_text_parts
    )
    if len(exact) != 1:
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    page, table_slice = exact[0]
    cells_by_id = {item.cell_id: item for item in page.cells}
    try:
        cells = tuple(cells_by_id[item] for item in table_slice.ordered_cell_ids)
    except KeyError:
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID") from None
    if (
        not cells
        or any(item.table_id != table_slice.table_id for item in cells)
        or tuple(item.exact_text for item in cells) != table_slice.exact_text_parts
    ):
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    evidence = tuple(
        sorted(
            (
                _freeform_evidence_815(
                    field_id=field_id,
                    source=source,
                    subject_ref=cell.cell_id,
                    quote=cell.exact_text,
                )
                for cell in cells
            ),
            key=evidence_verifier._freeform_evidence_key,
        )
    )
    value = _VALUE_PART_SEPARATOR_815.join(table_slice.exact_text_parts)
    rects = tuple(item.bbox for item in cells)
    coordinate = CoordinateEvidence815V1(
        field_id=field_id,
        source_revision_id=projection.source_revision_id,
        source_role=projection.source_role,
        original_file_sha256=projection.original_file_sha256,
        parse_manifest_sha256=projection.parse_manifest_sha256,
        selection_id=selection.selection_id,
        selection_type="TABLE_SLICE",
        page_number=page.page_number,
        page_text_char_start=None,
        page_text_char_end=None,
        coordinate_space=projection.coordinate_space,
        page_width_points=page.page_width_points,
        page_height_points=page.page_height_points,
        bbox=_union_native_bbox_815(rects),
        rects=rects,
        quote=value,
        quote_sha256=hashlib.sha256(value.encode()).hexdigest(),
        table_slice_id=table_slice.table_slice_id,
        table_id=table_slice.table_id,
        cell_ids=table_slice.ordered_cell_ids,
    )
    first = cells[0]
    return (
        value,
        evidence,
        (coordinate,),
        (
            _ROLE_ORDER.index(projection.source_role),
            page.page_number,
            first.row_index,
            first.column_index,
        ),
    )


def _narrow_selection_hydration_to_value_parts_815(
    *,
    selection: NativePdfSelection815V1,
    evidence: tuple[FreeformEvidenceV1, ...],
    coordinates: tuple[CoordinateEvidence815V1, ...],
    selected_parts: tuple[NativePdfValuePart815V1, ...],
) -> tuple[tuple[FreeformEvidenceV1, ...], tuple[CoordinateEvidence815V1, ...]]:
    selected_subject_ids = tuple(
        subject_id for part in selected_parts for subject_id in part.subject_ids
    )
    if not selected_subject_ids or any(
        part not in selection.value_parts for part in selected_parts
    ):
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    if selection.selection_type == "TEXT_SPAN":
        if (
            len(evidence) != len(selection.subject_ids)
            or len(coordinates) != len(selection.subject_ids)
            or tuple(item.span_id for item in coordinates) != selection.subject_ids
        ):
            raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
        evidence_by_subject = dict(zip(selection.subject_ids, evidence, strict=True))
        coordinates_by_subject = {
            cast(str, item.span_id): item for item in coordinates
        }
        try:
            return (
                tuple(evidence_by_subject[item] for item in selected_subject_ids),
                tuple(coordinates_by_subject[item] for item in selected_subject_ids),
            )
        except KeyError:
            raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID") from None
    if selected_subject_ids != selection.subject_ids:
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    return evidence, coordinates


def hydrate_model_selection_response_815(
    *,
    response: ModelTaskSelectionResponse815V1,
    field_catalogs: tuple[FieldSelectionCatalog815V1, ...],
    source_projections: tuple[NativePdfSelectionProjection815V1, ...],
    admitted_sources: tuple[AdmittedParseArtifactV1, ...],
) -> tuple[
    tuple[FreeformFieldOutputV1, ...],
    tuple[CoordinateEvidence815V1, ...],
    tuple[tuple[str, Literal["ANSWER_NOT_FOUND", "SOURCE_LOCATION_UNRESOLVED"]], ...],
]:
    """Hydrate only code-issued selections; invalid membership is field-local UNKNOWN."""

    exact_catalogs = _require_exact_field_catalogs_815(field_catalogs)
    try:
        exact_response = ModelTaskSelectionResponse815V1.model_validate(
            response.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise NativePdfSelectionError815("SELECTION_RESPONSE_SHAPE_INVALID") from None
    if tuple(item.field_id for item in exact_response.fields) != tuple(
        item.field_id for item in exact_catalogs
    ):
        raise NativePdfSelectionError815("SELECTION_RESPONSE_SHAPE_INVALID")
    projections, admitted, identities = _require_projection_sources_815(
        source_projections=source_projections,
        admitted_sources=admitted_sources,
    )
    outputs: list[FreeformFieldOutputV1] = []
    coordinate_rows: list[CoordinateEvidence815V1] = []
    reasons: list[tuple[str, Literal["ANSWER_NOT_FOUND", "SOURCE_LOCATION_UNRESOLVED"]]] = []
    for field_response, field_catalog in zip(
        exact_response.fields, exact_catalogs, strict=True
    ):
        if field_response.state == "unknown":
            outputs.append(
                FreeformFieldOutputV1(
                    product_version_id="596-1",
                    field_id=field_response.field_id,
                    state="unknown",
                    value_snapshot=None,
                    evidence=(),
                )
            )
            reasons.append((field_response.field_id, "ANSWER_NOT_FOUND"))
            continue
        selections_by_id = {item.selection_id: item for item in field_catalog.selections}
        if any(item not in selections_by_id for item in field_response.selection_ids):
            outputs.append(
                FreeformFieldOutputV1(
                    product_version_id="596-1",
                    field_id=field_response.field_id,
                    state="unknown",
                    value_snapshot=None,
                    evidence=(),
                )
            )
            reasons.append((field_response.field_id, "SOURCE_LOCATION_UNRESOLVED"))
            continue
        selected = tuple(selections_by_id[item] for item in field_response.selection_ids)
        if not field_response.value_part_ids and any(
            item.display_policy == "EXACT_SHORT" for item in selected
        ) and (len(selected) != 1 or len(selected[0].value_parts) != 1):
            outputs.append(
                FreeformFieldOutputV1(
                    product_version_id="596-1",
                    field_id=field_response.field_id,
                    state="unknown",
                    value_snapshot=None,
                    evidence=(),
                )
            )
            reasons.append((field_response.field_id, "SOURCE_LOCATION_UNRESOLVED"))
            continue
        hydrated: list[
            tuple[
                NativePdfSelection815V1,
                str,
                tuple[FreeformEvidenceV1, ...],
                tuple[CoordinateEvidence815V1, ...],
                tuple[int, ...],
            ]
        ] = []
        product_version_id: str | None = None
        selection_unresolved = False
        for selection_id in field_response.selection_ids:
            selection = selections_by_id[selection_id]
            projection = projections.get(selection.source_role)
            source = admitted.get(selection.source_role)
            source_identity = identities.get(selection.source_role)
            if source is not None:
                product_version_id = source.document.subject.product_version_id
            if (
                projection is None
                or source is None
                or source_identity is None
                or projection.source_revision_id != selection.source_revision_id
                or projection.parse_manifest_sha256 != selection.parse_manifest_sha256
                or projection.source_revision_id
                != source.document.subject.source_revision_id
                or projection.original_file_sha256 != source.document.subject.source_sha256
            ):
                selection_unresolved = True
                break
            try:
                item = (
                    _span_selection_hydration_815(
                        field_id=field_response.field_id,
                        selection=selection,
                        projection=projection,
                        source=source,
                    )
                    if selection.selection_type == "TEXT_SPAN"
                    else _table_selection_hydration_815(
                        field_id=field_response.field_id,
                        selection=selection,
                        projection=projection,
                        source=source,
                    )
                )
            except NativePdfSelectionError815:
                selection_unresolved = True
                break
            hydrated.append((selection, *item))
        if selection_unresolved:
            outputs.append(
                FreeformFieldOutputV1(
                    product_version_id=product_version_id or "596-1",
                    field_id=field_response.field_id,
                    state="unknown",
                    value_snapshot=None,
                    evidence=(),
                )
            )
            reasons.append((field_response.field_id, "SOURCE_LOCATION_UNRESOLVED"))
            continue
        if product_version_id is None:
            raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
        hydrated.sort(key=lambda item: item[4])
        canonical_parts = tuple(
            part
            for selection, _value, _evidence, _coordinates, _order in hydrated
            for part in selection.value_parts
        )
        requested_part_ids = set(field_response.value_part_ids)
        if field_response.value_part_ids:
            selected_parts = tuple(
                item for item in canonical_parts if item.value_part_id in requested_part_ids
            )
            if tuple(item.value_part_id for item in selected_parts) != (
                field_response.value_part_ids
            ):
                outputs.append(
                    FreeformFieldOutputV1(
                        product_version_id=product_version_id,
                        field_id=field_response.field_id,
                        state="unknown",
                        value_snapshot=None,
                        evidence=(),
                    )
                )
                reasons.append((field_response.field_id, "SOURCE_LOCATION_UNRESOLVED"))
                continue
            value_snapshot = _VALUE_PART_SEPARATOR_815.join(
                text for part in selected_parts for text in part.exact_text_parts
            )
        else:
            value_snapshot = _VALUE_PART_SEPARATOR_815.join(item[1] for item in hydrated)
        narrowed_evidence: list[FreeformEvidenceV1] = []
        narrowed_coordinates: list[CoordinateEvidence815V1] = []
        narrowing_unresolved = False
        for (
            selection,
            _value,
            selection_evidence,
            selection_coordinates,
            _order,
        ) in hydrated:
            if not field_response.value_part_ids:
                narrowed_evidence.extend(selection_evidence)
                narrowed_coordinates.extend(selection_coordinates)
                continue
            selection_parts = tuple(
                part
                for part in selection.value_parts
                if part.value_part_id in requested_part_ids
            )
            if not selection_parts:
                continue
            try:
                exact_evidence, exact_coordinates = (
                    _narrow_selection_hydration_to_value_parts_815(
                        selection=selection,
                        evidence=selection_evidence,
                        coordinates=selection_coordinates,
                        selected_parts=selection_parts,
                    )
                )
            except NativePdfSelectionError815:
                narrowing_unresolved = True
                break
            narrowed_evidence.extend(exact_evidence)
            narrowed_coordinates.extend(exact_coordinates)
        if narrowing_unresolved:
            outputs.append(
                FreeformFieldOutputV1(
                    product_version_id=product_version_id,
                    field_id=field_response.field_id,
                    state="unknown",
                    value_snapshot=None,
                    evidence=(),
                )
            )
            reasons.append((field_response.field_id, "SOURCE_LOCATION_UNRESOLVED"))
            continue
        canonical_evidence = sorted(
            narrowed_evidence,
            key=evidence_verifier._freeform_evidence_key,
        )
        evidence_keys: set[tuple[str, ...]] = set()
        evidence_rows: list[FreeformEvidenceV1] = []
        for evidence in canonical_evidence:
            key = evidence_verifier._freeform_evidence_key(evidence)
            if key in evidence_keys:
                continue
            evidence_keys.add(key)
            evidence_rows.append(evidence)
        evidences = tuple(evidence_rows)
        outputs.append(
            FreeformFieldOutputV1(
                product_version_id=product_version_id,
                field_id=field_response.field_id,
                state=field_response.state,
                value_snapshot=value_snapshot,
                evidence=evidences,
            )
        )
        coordinate_rows.extend(narrowed_coordinates)
    return tuple(outputs), tuple(coordinate_rows), tuple(reasons)


def make_coordinate_evidence_companion_815(
    *,
    candidate_sha256: str,
    selection_catalog: Schema67SelectionCatalog815V1,
    source_projections: tuple[NativePdfSelectionProjection815V1, ...],
    coordinate_rows: tuple[CoordinateEvidence815V1, ...],
) -> CoordinateEvidenceCompanion815V1:
    """Freeze coordinate Evidence beside, never inside, the existing Candidate."""

    if (
        selection_catalog.catalog_sha256
        != selection_catalog.recomputed_catalog_sha256()
        or tuple(item.field_id for item in selection_catalog.fields)
        != selection_catalog.provider_visible_field_ids
    ):
        raise NativePdfSelectionError815("SELECTION_AUTHORITY_INVALID")
    _require_projection_sources_815(
        source_projections=source_projections,
        admitted_sources=(),
    )
    parse_manifest_sha256s = tuple(
        item.parse_manifest_sha256 for item in source_projections
    )
    payload = {
        "contract": "schema67-coordinate-evidence-companion.815.v1",
        "candidate_sha256": candidate_sha256,
        "provider_visible_field_ids": selection_catalog.provider_visible_field_ids,
        "coordinate_rows": tuple(
            item.model_dump(mode="python") for item in coordinate_rows
        ),
        "selection_catalog_sha256": selection_catalog.catalog_sha256,
        "parse_manifest_sha256s": parse_manifest_sha256s,
    }
    return CoordinateEvidenceCompanion815V1(
        contract="schema67-coordinate-evidence-companion.815.v1",
        candidate_sha256=candidate_sha256,
        provider_visible_field_ids=selection_catalog.provider_visible_field_ids,
        coordinate_rows=coordinate_rows,
        selection_catalog_sha256=selection_catalog.catalog_sha256,
        parse_manifest_sha256s=parse_manifest_sha256s,
        companion_sha256=canonical_hash(
            "schema67-coordinate-evidence-companion.815.v1",
            payload,
        ),
    )


__all__ = [
    "CoordinateEvidence815V1",
    "CoordinateEvidenceCompanion815V1",
    "FieldSelectionCatalog815V1",
    "ModelFieldSelection815V1",
    "ModelTaskSelectionResponse815V1",
    "NativePdfSelection815V1",
    "NativePdfSelectionError815",
    "Schema67SelectionCatalog815V1",
    "SelectionType815",
    "build_field_selection_catalogs_815",
    "hydrate_model_selection_response_815",
    "make_coordinate_evidence_companion_815",
    "require_model_selection_response_815",
]
