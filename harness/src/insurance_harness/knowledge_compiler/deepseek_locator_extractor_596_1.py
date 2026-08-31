"""Task-local deterministic-locator-to-DeepSeek-extractor compiler for Mission 119.

The orchestration is deliberately narrow: it maps Lane A role subsets into exact 054
tasks, selects only caller-frozen canonical locators, and delegates Evidence/receipt
authority to Lane C, 057, and 054.  The legacy 069 bridge remains explicit.  This
module never reads configuration files or calls a fallback model.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Annotated, Final, Literal, Protocol, Self, cast

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
    ApprovedLocatorSetV1,
    EvidenceReviewItemV1,
    FieldCandidateV1,
    FieldRuleV1,
    FieldVerificationV1,
    FreeformEvidenceBindingReceiptV1,
    FreeformEvidenceV1,
    FreeformFieldOutputV1,
    GapV1,
    RepairBudgetV1,
    RepairResolutionV1,
    TargetedRepairPlanV1,
    VerificationBatchV1,
    apply_targeted_repair,
    bind_054_attempt_receipt,
    bind_freeform_arm_evidence,
    plan_targeted_repair,
)
from insurance_harness.compiler.extraction_receipts import (
    AttemptRequestV1,
    FieldOutcomeV1,
    ReceiptChainV1,
    build_attempt_receipt,
    build_initial_attempt,
    build_targeted_repair,
)
from insurance_harness.compiler.extraction_tasks import (
    ArtifactRefV1,
    AttemptBudgetV1,
    ExtractionInputRefsV1,
    ExtractionTaskProfileV1,
    ExtractionTaskV1,
    MaterialRole,
    ParsedArtifactAdmissionPort,
    build_extraction_task,
    build_extraction_task_profile,
)
from insurance_harness.compiler.llm import (
    ModelClient,
    OpenAICompatClient,
    TruncatedOutputError,
    openai_compat_request_bytes,
)
from insurance_harness.compiler.material_profiles import (
    FieldAuthority,
    MaterialProfileResolution,
)
from insurance_harness.compiler.native_pdfplumber import (
    NativePdfSelectionProjection815V1,
)
from insurance_harness.compiler.parsed_documents import (
    ParsedDocumentV1,
    ParseManifestV1,
    ParseQualityDecisionV1,
)
from insurance_harness.knowledge_compiler import semantic_input_binding as semantic
from insurance_harness.knowledge_compiler.relation_bound_admission_596_1 import (
    RelationBoundAdmissionResultV1,
    SourceAdmissionAuthorityV1,
    Trusted090RelationInputV1,
)
from insurance_harness.knowledge_compiler.schema67_native_pdf_selection_815 import (
    FieldSelectionCatalog815V1,
    NativePdfSelectionError815,
    Schema67SelectionCatalog815V1,
    _selection_prompt_payload_815,
    hydrate_model_selection_response_815,
    require_model_selection_response_815,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_BY,
    APPROVED_ORDERED_FIELD_IDS,
    APPROVED_SCHEMA_ROWS_SHA256,
    APPROVED_WORKBOOK_SHA256,
    FieldContractSetV1,
    FieldContractV1,
)
from insurance_harness.knowledge_compiler.semantic_input_binding import (
    BoundSemanticAttemptV1,
    ComposedSemanticTaskV1,
    SemanticExecutionIdentityV1,
    SemanticInputCompositionV1,
)
from insurance_harness.knowledge_compiler.vertical_falsification import (
    AdmittedParseArtifactV1,
    admit_596_1_vertical_falsification,
)
from insurance_harness.live_env.config import ModelProfile
from insurance_harness.model_policy import ModelIdentity, ProductionModelPolicy


@dataclass(frozen=True)
class _ExtractorStringConstraint:
    min_length: int
    max_length: int
    pattern: str
    single_line: bool
    allow_crlf: bool
    allow_leading_or_trailing_whitespace: bool

    def visible_contract(self) -> dict[str, object]:
        return {
            "type": "nonblank_string",
            "min_length": self.min_length,
            "max_length": self.max_length,
            "single_line": self.single_line,
            "allow_crlf": self.allow_crlf,
            "allow_leading_or_trailing_whitespace": (self.allow_leading_or_trailing_whitespace),
        }


_EXTRACTOR_STRING_CONSTRAINT: Final = _ExtractorStringConstraint(
    min_length=1,
    max_length=512,
    pattern=r"^\S(?:[^\r\n]*\S)?$",
    single_line=True,
    allow_crlf=False,
    allow_leading_or_trailing_whitespace=False,
)
NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(
        min_length=_EXTRACTOR_STRING_CONSTRAINT.min_length,
        max_length=_EXTRACTOR_STRING_CONSTRAINT.max_length,
        pattern=_EXTRACTOR_STRING_CONSTRAINT.pattern,
    ),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
LocatorKind = Literal["page", "block", "table", "cell"]

DEEPSEEK_PROVIDER: Final[str] = "deepseek"
DEEPSEEK_PROTOCOL: Final[str] = "openai_compatible"
DEEPSEEK_MODEL: Final[str] = "deepseek-v4-flash"
DEEPSEEK_BASE_URL: Final[str] = "https://api.deepseek.com/v1"
DEEPSEEK_POLICY_VERSION: Final[str] = "schema67-deepseek-v1"
DEEPSEEK_TEMPERATURE: Final[float] = 0.0
DEEPSEEK_MAX_TOKENS: Final[int] = 8192
DEEPSEEK_TIMEOUT_S: Final[float] = 180.0
DEEPSEEK_THINKING: Final[Literal["disabled"]] = "disabled"
DEEPSEEK_RESPONSE_FORMAT: Final[Literal["json_object"]] = "json_object"
DEEPSEEK_MAX_REQUEST_BYTES: Final[int] = 128 * 1024
SCHEMA67_WORKBOOK_SHA256: Final[str] = APPROVED_WORKBOOK_SHA256
SCHEMA67_APPROVED_BY: Final[str] = APPROVED_BY
_RESPONSE_CONTRACT_REPAIR_POLICY_PAYLOAD: Final[dict[str, object]] = {
    "failed_field_ids": "code_owned_contract_order_unique",
    "failed_field_content": "field_id_only",
    "forbidden_failure_content": (
        "locator_ref",
        "quote_snapshot",
        "raw_response",
    ),
    "repair_authority": "unchanged",
    "max_repairs": 1,
}
_RESPONSE_CONTRACT_REPAIR_POLICY_SHA256: Final[str] = canonical_hash(
    "schema67-response-contract-repair-policy.v2",
    _RESPONSE_CONTRACT_REPAIR_POLICY_PAYLOAD,
)
_LOCATOR_SLOT_POLICY_OBJECT_TYPE: Final[str] = "schema67-locator-slot-policy.v1"
_LOCATOR_SLOT_AUTHORITY_OBJECT_TYPE: Final[str] = "schema67-locator-slot-authority.v1"
LOCATOR_SLOT_POLICY_SHA256: Final[str] = canonical_hash(
    _LOCATOR_SLOT_POLICY_OBJECT_TYPE,
    {
        "scope": "task_global",
        "slot_format": "slot-%04d",
        "catalog_order": "locator_ref_lexicographic",
        "catalog_content": "single_copy",
        "field_role_membership": "exact",
        "collision_policy": "reject",
        "model_visible_authority": "slot_only",
        "code_owned_mapping": "field_role_slot_to_locator_ref",
    },
)
DEEPSEEK_MODEL_IDENTITY: Final[ModelIdentity] = ModelIdentity(
    provider=DEEPSEEK_PROVIDER,
    deployment_id=DEEPSEEK_MODEL,
    family="deepseek",
    role="extract",
    policy_version=DEEPSEEK_POLICY_VERSION,
)
DEEPSEEK_EXECUTION_IDENTITY_SHA256: Final[str] = canonical_hash(
    "schema67-deepseek-execution-identity.v1",
    {
        "provider": DEEPSEEK_PROVIDER,
        "protocol": DEEPSEEK_PROTOCOL,
        "base_url": DEEPSEEK_BASE_URL,
        "model": DEEPSEEK_MODEL,
        "family": "deepseek",
        "role": "extract",
        "policy_version": DEEPSEEK_POLICY_VERSION,
        "temperature": "0.0",
        "max_tokens": DEEPSEEK_MAX_TOKENS,
        "timeout_s": "180.0",
        "thinking": {"type": DEEPSEEK_THINKING},
        "response_format": {"type": DEEPSEEK_RESPONSE_FORMAT},
        "response_contract_repair_policy_sha256": (_RESPONSE_CONTRACT_REPAIR_POLICY_SHA256),
        "locator_slot_policy_sha256": LOCATOR_SLOT_POLICY_SHA256,
        "grouped_targeted_repair_policy": {
            "max_shared_extra_calls": 8,
            "max_transport_retries": 1,
            "max_response_contract_repairs": 1,
            "max_evidence_repairs": 8,
            "evidence_partition": "original_task_group",
            "max_one_evidence_repair_per_task_group": True,
        },
    },
)
DEEPSEEK_NORMALIZER_IDENTITY_SHA256: Final[str] = canonical_hash(
    "schema67-deepseek-normalizer-identity.v1",
    {"field_output_contract": "freeform-field-output.v1", "version": 1},
)
_FIELD_PROMPT_OBJECT_TYPE: Final[str] = "schema67-deepseek-field-prompt.v1"
_TASK_SLICE_OBJECT_TYPE: Final[str] = "schema67-deepseek-task-slice.v1"
_EXECUTION_PLAN_OBJECT_TYPE: Final[str] = "schema67-deepseek-execution-plan.v2"
_NATIVE_PDF_EXECUTION_PROJECTION_OBJECT_TYPE: Final[str] = (
    "schema67-native-pdf-execution-projection.815.v1"
)
_PROVIDER_TASK_OBJECT_TYPE: Final[str] = "schema67-deepseek-provider-task.v1"
_PROVIDER_ATTEMPT_OBJECT_TYPE: Final[str] = "schema67-deepseek-provider-attempt.v1"
_BATCH_BUDGET_OBJECT_TYPE: Final[str] = "schema67-deepseek-batch-budget.v2"
_EXECUTION_RECEIPT_OBJECT_TYPE: Final[str] = "deepseek-evidence-compiler-596-1.v2"
_BATCH_RECEIPT_OBJECT_TYPE: Final[str] = "schema67-deepseek-batch-receipt.v2"
_EVIDENCE_DEMOTION_RECEIPT_OBJECT_TYPE: Final[str] = "schema67-evidence-demotion-receipt.v1"
_PASS_PRESERVATION_OBJECT_TYPE: Final[str] = "schema67-evidence-demotion-pass-preservation.v1"
_PRIOR_PROVIDER_LEDGER_EXTERNAL_SHA256: Final[str] = (
    "20208d33cfbbeb825ab8ee88d406e9e07010b1fde99612145d340dc81fac0d03"
)
_PRIOR_PROVIDER_LEDGER_INTERNAL_SHA256: Final[str] = (
    "507411396195ea2aa66f304e9de1809863205671d5bc75b97b09802530cd65c3"
)
_EVIDENCE_DEMOTION_POLICY_SHA256: Final[str] = canonical_hash(
    "schema67-evidence-demotion-policy.v1",
    {
        "authority": "complete_code_owned_initial_verification_batches",
        "scope": "contract_order_any_non_pass_union",
        "multi_source": "any_non_pass_demotes_whole_field",
        "final_state": "unknown_null_empty_evidence",
        "final_evidence_receipt": "code_owned_empty",
        "pass_outputs_and_receipts": "byte_identical",
        "provider_retry": 0,
        "response_contract_repair": 0,
        "evidence_repair": 0,
    },
)
_LOCATOR_SELECTION_POLICY_OBJECT_TYPE: Final[str] = (
    "schema67-deterministic-locator-selection-policy.v1"
)
_LOCATOR_AUTHORITY_OBJECT_TYPE: Final[str] = "schema67-deterministic-locator-authority.v1"
_LOCATOR_SELECTION_OBJECT_TYPE: Final[str] = "schema67-deterministic-locator-selection.v1"
LOCATOR_SELECTION_POLICY_SHA256: Final[str] = canonical_hash(
    _LOCATOR_SELECTION_POLICY_OBJECT_TYPE,
    {
        "algorithm_version": "schema67-contract-lexical-locator-v3",
        "source": "field-contract-plus-mineru-locators",
        "contract_terms": (
            "field_name",
            "description",
            "category",
            "value_shape_raw",
            "source_authority_raw",
            "formation_raw",
        ),
        "normalization": "str.casefold",
        "unicode_sequence_regex": r"[\u3400-\u9fff]+",
        "whole_sequence_min_chars": 2,
        "whole_sequence_max_chars": 12,
        "ngram_widths": (2, 3, 4),
        "ascii_token_regex": r"[a-z0-9_]{3,}",
        "stoplist": (
            "产品",
            "信息",
            "内容",
            "相关",
            "情况",
            "是否",
            "说明",
            "要求",
            "规则",
            "保险",
        ),
        "score": ("term_length_squared", "field_name_exact_bonus:100"),
        "tie_break": ("score_desc", "input_ordinal_asc"),
        "input_order": "mineru_canonical_ordinal",
        "output_order": "locator_ref_lexicographic",
        "all_locators_threshold": 24,
        "ranked_match_limit": 8,
        "neighbor_offsets": (-1, 0, 1),
        "fallback_max_content_chars": 40,
        "fallback_max_locators": 24,
        "golden_reads": 0,
        "model_calls": 0,
    },
)


class DeepSeekCompilerError(ValueError):
    """Secret-free fail-closed error emitted before any fallback or persistence."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _LocatorMembershipFailure(DeepSeekCompilerError):
    """Code-owned field IDs for a locator-membership failure, never model content."""

    def __init__(
        self,
        failed_field_ids: tuple[str, ...],
        *,
        duplicate_locator_field_ids: tuple[str, ...] = (),
    ) -> None:
        if not failed_field_ids or len(failed_field_ids) != len(set(failed_field_ids)):
            raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
        if len(duplicate_locator_field_ids) != len(set(duplicate_locator_field_ids)):
            raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
        self.failed_field_ids = failed_field_ids
        self.duplicate_locator_field_ids = duplicate_locator_field_ids
        super().__init__("EXTRACTOR_LOCATOR_NOT_ALLOWED_INVALID")


ResponseDecodeFailureCode = Literal["MODEL_CONTENT_EMPTY", "MODEL_JSON_INVALID"]
RepairableExtractorResponseFailureCode = Literal[
    "TOP_LEVEL_SHAPE",
    "FIELD_ITEM_SHAPE",
    "FIELD_COUNT_OR_SET",
    "FIELD_ORDER",
    "FORCED_UNKNOWN",
    "STRING_CONSTRAINT",
    "LOCATOR_NOT_ALLOWED",
]
ResponseContractRepairFailureCode = Literal[
    "MODEL_CONTENT_EMPTY",
    "MODEL_JSON_INVALID",
    "TOP_LEVEL_SHAPE",
    "FIELD_ITEM_SHAPE",
    "FIELD_COUNT_OR_SET",
    "FIELD_ORDER",
    "FORCED_UNKNOWN",
    "STRING_CONSTRAINT",
    "LOCATOR_NOT_ALLOWED",
]
ExtractorResponseFailureCode = Literal[
    "TOP_LEVEL_SHAPE",
    "FIELD_ITEM_SHAPE",
    "FIELD_COUNT_OR_SET",
    "FIELD_ORDER",
    "FORCED_UNKNOWN",
    "STRING_CONSTRAINT",
    "LOCATOR_NOT_ALLOWED",
    "CODE_OWNED_AUTHORITY_MISMATCH",
]
TargetedRepairKind = Literal["none", "response_contract", "evidence"]
_RESPONSE_DECODE_REPAIRABLE_CODES: Final[frozenset[str]] = frozenset(
    {"MODEL_CONTENT_EMPTY", "MODEL_JSON_INVALID"}
)
_RESPONSE_CONTRACT_REPAIRABLE_CODES: Final[frozenset[str]] = frozenset(
    {
        "EXTRACTOR_TOP_LEVEL_SHAPE_INVALID",
        "EXTRACTOR_FIELD_ITEM_SHAPE_INVALID",
        "EXTRACTOR_FIELD_COUNT_OR_SET_INVALID",
        "EXTRACTOR_FIELD_ORDER_INVALID",
        "EXTRACTOR_FORCED_UNKNOWN_INVALID",
        "EXTRACTOR_STRING_CONSTRAINT_INVALID",
        "EXTRACTOR_LOCATOR_NOT_ALLOWED_INVALID",
    }
)


def _response_failure_code(reason_code: str) -> RepairableExtractorResponseFailureCode:
    prefix = "EXTRACTOR_"
    suffix = "_INVALID"
    if not (reason_code.startswith(prefix) and reason_code.endswith(suffix)):
        raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
    code = reason_code[len(prefix) : -len(suffix)]
    if code not in {
        "TOP_LEVEL_SHAPE",
        "FIELD_ITEM_SHAPE",
        "FIELD_COUNT_OR_SET",
        "FIELD_ORDER",
        "FORCED_UNKNOWN",
        "STRING_CONSTRAINT",
        "LOCATOR_NOT_ALLOWED",
    }:
        raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
    return cast(RepairableExtractorResponseFailureCode, code)


class _ModelResponseDecodeFailure(DeepSeekCompilerError):
    """A fixed decode category plus the failed response digest, never its content."""

    def __init__(self, reason_code: ResponseDecodeFailureCode, response_sha256: str) -> None:
        self.response_sha256 = response_sha256
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class CanonicalLocatorInputV1(_FrozenModel):
    locator_ref: NonBlankStr
    locator_kind: LocatorKind
    page_number: Annotated[StrictInt, Field(gt=0)]
    parent_refs: tuple[NonBlankStr, ...]
    content_snapshot: NonBlankStr = Field(repr=False)
    content_snapshot_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_snapshot(self) -> Self:
        if self.content_snapshot_sha256 != _sha256_text(self.content_snapshot):
            raise ValueError("locator_snapshot_hash_mismatch")
        if len(self.parent_refs) != len(set(self.parent_refs)):
            raise ValueError("locator_parent_refs_invalid")
        return self


class Schema67CapturedContentV1(_FrozenModel):
    """Whole-document capture content; it grants no caller-selected locator authority."""

    role: MaterialRole
    source_sha256: Sha256Hex
    capture_identity_sha256: Sha256Hex
    raw_structure_sha256: Sha256Hex
    sanitized_structure_sha256: Sha256Hex
    content_snapshot: StrictStr = Field(min_length=1, max_length=16_000_000, repr=False)
    content_snapshot_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_capture_snapshot(self) -> Self:
        if self.content_snapshot_sha256 != _sha256_text(self.content_snapshot):
            raise ValueError("capture_content_snapshot_hash_mismatch")
        return self


class _ExtractorEvidenceSelectionV1(_FrozenModel):
    """The model selects only code-owned locator authority and a literal quote."""

    locator_ref: NonBlankStr
    quote_snapshot: NonBlankStr


class _LocatorSlotCatalogEntryV1(_FrozenModel):
    """One task-global opaque slot; raw locator identity remains code-only."""

    slot: NonBlankStr
    locator_kind: LocatorKind
    page_number: Annotated[StrictInt, Field(ge=1)]
    content_snapshot: StrictStr = Field(min_length=1, max_length=16_000_000, repr=False)
    content_snapshot_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_content_hash(self) -> Self:
        if self.content_snapshot_sha256 != _sha256_text(self.content_snapshot):
            raise ValueError("locator_slot_content_hash_mismatch")
        return self


class _FieldRoleSlotsV1(_FrozenModel):
    source_role: MaterialRole
    allowed_slots: tuple[NonBlankStr, ...]

    @model_validator(mode="after")
    def require_unique_slots(self) -> Self:
        if not self.allowed_slots or len(self.allowed_slots) != len(set(self.allowed_slots)):
            raise ValueError("field_role_slots_invalid")
        return self


class _FieldLocatorSlotsV1(_FrozenModel):
    field_id: NonBlankStr
    sources: tuple[_FieldRoleSlotsV1, ...]

    @model_validator(mode="after")
    def require_unique_roles(self) -> Self:
        roles = tuple(item.source_role for item in self.sources)
        if len(roles) != len(set(roles)):
            raise ValueError("field_locator_roles_invalid")
        return self


@dataclass(frozen=True, slots=True)
class _LocatorSlotAuthorityV1:
    """Immutable model view plus the complete code-only slot-to-locator mapping."""

    task_id: str
    attempt_hash: str
    catalog: tuple[_LocatorSlotCatalogEntryV1, ...]
    field_locator_slots: tuple[_FieldLocatorSlotsV1, ...]
    code_mapping: tuple[tuple[str, MaterialRole, str, str], ...]
    authority_sha256: str

    def model_payload(self) -> dict[str, object]:
        return {
            "locator_slot_policy_sha256": LOCATOR_SLOT_POLICY_SHA256,
            "locator_slot_authority_sha256": self.authority_sha256,
            "locator_slot_catalog": tuple(item.model_dump(mode="python") for item in self.catalog),
            "field_locator_slots": tuple(
                item.model_dump(mode="python") for item in self.field_locator_slots
            ),
        }


class _ExtractorFieldSelectionV1(_FrozenModel):
    """Semantic-only model output; all parse/source custody is hydrated in code."""

    field_id: NonBlankStr
    state: Literal["present", "absent_explicitly", "unknown"]
    value_snapshot: NonBlankStr | None
    evidence: tuple[_ExtractorEvidenceSelectionV1, ...]

    @model_validator(mode="after")
    def require_semantic_only_shape(self) -> Self:
        if self.state == "unknown":
            if self.value_snapshot is not None or self.evidence:
                raise ValueError("unknown extractor field cannot carry value or Evidence")
        elif self.value_snapshot is None or not self.evidence:
            raise ValueError("known extractor field requires value and Evidence")
        keys = tuple((item.locator_ref, item.quote_snapshot) for item in self.evidence)
        if len(keys) != len(set(keys)):
            raise ValueError("extractor Evidence must be unique")
        return self


@dataclass(frozen=True, slots=True)
class Schema67PreparedExecutionInputsV1:
    role_inputs: tuple[Schema67RoleTaskInputV1, ...] = field(repr=False)
    locators_by_task: tuple[tuple[CanonicalLocatorInputV1, ...], ...] = field(repr=False)
    preparation_sha256: str


def _snapshot_candidates(content_snapshot: str) -> set[str]:
    """Enumerate deterministic Markdown projections; hashes decide exact membership."""

    candidates: set[str] = {content_snapshot, content_snapshot.strip()}
    lines = content_snapshot.splitlines()
    for value in (*lines, *re.split(r"\n\s*\n", content_snapshot)):
        stripped = value.strip()
        if not stripped:
            continue
        candidates.update(
            {
                stripped,
                html.unescape(stripped),
                re.sub(r"^#{1,6}\s+", "", stripped),
                re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", stripped),
                re.sub(r"[*_`]+", "", stripped),
            }
        )
    for start in range(len(lines)):
        for width in range(2, min(12, len(lines) - start) + 1):
            value = "\n".join(lines[start : start + width]).strip()
            if value:
                candidates.add(value)
    return {value for value in candidates if value}


def recover_exact_mineru_block_locators(
    *,
    admitted_source: AdmittedParseArtifactV1,
    content_snapshot: str,
) -> tuple[CanonicalLocatorInputV1, ...]:
    """Recover only cryptographically exact block plaintext from a captured snapshot."""

    document = admitted_source.document
    if (
        document.parser.parser_id != "mineru-cloud-pipeline"
        or document.parser.parser_build_id != "NewMinerUCloudReader/mineru-native-structure.v1"
        or not content_snapshot
    ):
        raise DeepSeekCompilerError("MINERU_LOCATOR_PREIMAGE_UNAVAILABLE")
    preimages = {
        evidence_verifier._mineru_snapshot_hash("block", value): value
        for value in _snapshot_candidates(content_snapshot)
    }
    recovered: list[CanonicalLocatorInputV1] = []
    for block in document.blocks:
        content = preimages.get(block.content_hash)
        if content is None or "\n" in content or "\r" in content or len(content) > 512:
            continue
        fact = evidence_verifier._locator_fact(document, block.block_id)
        if fact is None:
            continue
        kind, page_number, parent_refs, parsed_hash = fact
        if kind != "block" or parsed_hash != block.content_hash:
            continue
        recovered.append(
            CanonicalLocatorInputV1(
                locator_ref=block.block_id,
                locator_kind="block",
                page_number=page_number,
                parent_refs=parent_refs,
                content_snapshot=content,
                content_snapshot_sha256=_sha256_text(content),
            )
        )
    if not recovered:
        raise DeepSeekCompilerError("MINERU_LOCATOR_PREIMAGE_UNAVAILABLE")
    return tuple(recovered)


def _contract_lexical_terms(contract: FieldContractV1) -> tuple[str, ...]:
    source = " ".join(
        value
        for value in (
            contract.field_name,
            contract.description,
            contract.category,
            contract.value_shape_raw,
            contract.source_authority_raw,
            contract.formation_raw,
        )
        if value is not None
    ).casefold()
    terms: set[str] = set()
    for sequence in re.findall(r"[\u3400-\u9fff]+", source):
        if 2 <= len(sequence) <= 12:
            terms.add(sequence)
        for width in (2, 3, 4):
            terms.update(
                sequence[index : index + width]
                for index in range(max(0, len(sequence) - width + 1))
            )
    terms.update(re.findall(r"[a-z0-9_]{3,}", source))
    stop = {"产品", "信息", "内容", "相关", "情况", "是否", "说明", "要求", "规则", "保险"}
    return tuple(sorted(terms - stop, key=lambda value: (-len(value), value)))


def select_contract_locator_refs(
    *,
    contract: FieldContractV1,
    locators: Sequence[CanonicalLocatorInputV1],
) -> tuple[str, ...]:
    """Bound one field to exact source blocks using contract text only, never Golden data."""

    exact = tuple(locators)
    if len(exact) <= 24:
        return tuple(sorted(item.locator_ref for item in exact))
    terms = _contract_lexical_terms(contract)
    ranked: list[tuple[int, int, int]] = []
    for index, locator in enumerate(exact):
        content = locator.content_snapshot.casefold()
        score = sum(len(term) ** 2 for term in terms if term in content)
        if contract.field_name.casefold() in content:
            score += 100
        if score:
            ranked.append((score, -index, index))
    ranked.sort(reverse=True)
    selected: set[int] = set()
    for _score, _reverse_index, index in ranked[:8]:
        selected.update(
            candidate for candidate in (index - 1, index, index + 1) if 0 <= candidate < len(exact)
        )
    if not selected:
        selected.update(
            index for index, locator in enumerate(exact) if len(locator.content_snapshot) <= 40
        )
        selected = set(sorted(selected)[:24])
    return tuple(sorted(exact[index].locator_ref for index in selected))


def _deepseek_request_bytes(*, system: str, user: str) -> bytes:
    return openai_compat_request_bytes(
        model=DEEPSEEK_MODEL,
        temperature=DEEPSEEK_TEMPERATURE,
        max_tokens=DEEPSEEK_MAX_TOKENS,
        system=system,
        user=user,
        thinking=DEEPSEEK_THINKING,
        response_format=DEEPSEEK_RESPONSE_FORMAT,
    )


def _require_request_size(*, system: str, user: str) -> None:
    body = _deepseek_request_bytes(system=system, user=user)
    if len(body) > DEEPSEEK_MAX_REQUEST_BYTES:
        raise DeepSeekCompilerError("MODEL_REQUEST_TOO_LARGE")


def _request_sha256(*, system: str, user: str) -> str:
    return hashlib.sha256(_deepseek_request_bytes(system=system, user=user)).hexdigest()


def _field_prompt_payload(contract: FieldContractV1) -> dict[str, object]:
    return {
        "field_id": contract.field_id,
        "field_name": contract.field_name,
        "category": contract.category,
        "description": contract.description,
        "value_shape_raw": contract.value_shape_raw,
        "source_authority_raw": contract.source_authority_raw,
        "formation_raw": contract.formation_raw,
        "value_shape": contract.value_shape,
        "formation_modes": contract.formation_modes,
        "source_roles": contract.source_roles,
        "source_guidance_roles": _source_guidance_roles(contract),
        "evidence_required": contract.evidence_required,
        "output_state_policy": contract.output_state_policy,
        "hardness": contract.hardness.model_dump(mode="python"),
        "field_contract_sha256": contract.field_contract_sha256,
    }


def _request_field_contract_payload(
    item: DeepSeekFieldPromptInputV1,
) -> dict[str, object]:
    """Project one prompt contract in task order, including approved raw guidance."""

    return {
        "field_id": item.field_id,
        "category": item.contract.category,
        "field_name": item.contract.field_name,
        "value_shape_raw": item.contract.value_shape_raw,
        "source_authority_raw": item.contract.source_authority_raw,
        "formation_raw": item.contract.formation_raw,
        "field_contract_sha256": item.contract.field_contract_sha256,
        "prompt_payload_sha256": item.prompt_payload_sha256,
        "contract": _field_prompt_payload(item.contract),
    }


_SOURCE_GUIDANCE_ROLE_MARKERS: Final[tuple[tuple[MaterialRole, tuple[str, ...]], ...]] = (
    ("terms", ("产品条款",)),
    (
        "brochure",
        (
            "产品说明书",
            "培训材料",
            "销售逻辑",
            "产品宣传海报",
            "产品Q&A",
            "产品常见问题",
            "产品组合销售方案",
            "服务手册",
            "权益规则",
            "理赔服务指引",
            "异议处理",
        ),
    ),
    (
        "rate_table",
        (
            "投保规则",
            "核保规则",
            "产品保全",
            "销售规则",
            "投保页面",
        ),
    ),
)


def _source_guidance_roles(contract: FieldContractV1) -> tuple[MaterialRole, ...]:
    """Interpret approved prose as a narrowing hint, never as source authority."""

    raw = contract.source_authority_raw
    return tuple(
        role
        for role, markers in _SOURCE_GUIDANCE_ROLE_MARKERS
        if any(marker in raw for marker in markers)
    )


def _prompt_source_roles(contract: FieldContractV1) -> tuple[MaterialRole, ...]:
    authorized = set(contract.source_roles)
    return tuple(role for role in _source_guidance_roles(contract) if role in authorized)


UnknownReviewReason = Literal[
    "SOURCE_GUIDANCE_ROLE_INTERSECTION_EMPTY",
    "SOURCE_LOCATOR_UNAVAILABLE",
]


class DeepSeekFieldPromptInputV1(_FrozenModel):
    """Prompt projection of one exact Lane A contract plus admitted locators."""

    contract: FieldContractV1 = Field(repr=False)
    prompt_payload_sha256: Sha256Hex
    allowed_locator_refs: tuple[NonBlankStr, ...]
    source_locator_refs: tuple[tuple[MaterialRole, tuple[NonBlankStr, ...]], ...] = ()
    requires_unknown_review: bool = False
    unknown_reason_code: UnknownReviewReason | None = None

    @property
    def field_id(self) -> str:
        return self.contract.field_id

    @model_validator(mode="after")
    def require_exact_prompt_projection(self) -> Self:
        exact = FieldContractV1.model_validate(
            self.contract.model_dump(mode="python", round_trip=True)
        )
        expected_roles = _prompt_source_roles(exact)
        missing_locator = any(not refs for _, refs in self.source_locator_refs)
        expected_reason: UnknownReviewReason | None = (
            "SOURCE_GUIDANCE_ROLE_INTERSECTION_EMPTY"
            if not expected_roles
            else "SOURCE_LOCATOR_UNAVAILABLE"
            if missing_locator
            else None
        )
        if (
            exact != self.contract
            or self.prompt_payload_sha256
            != canonical_hash(_FIELD_PROMPT_OBJECT_TYPE, _field_prompt_payload(exact))
            or self.allowed_locator_refs != tuple(sorted(self.allowed_locator_refs))
            or len(self.allowed_locator_refs) != len(set(self.allowed_locator_refs))
            or tuple(item[0] for item in self.source_locator_refs) != expected_roles
            or any(
                refs != tuple(sorted(refs)) or len(refs) != len(set(refs))
                for _, refs in self.source_locator_refs
            )
            or sum(len(refs) for _, refs in self.source_locator_refs)
            != len({ref for _, refs in self.source_locator_refs for ref in refs})
            or self.requires_unknown_review != (expected_reason is not None)
            or self.unknown_reason_code != expected_reason
            or self.allowed_locator_refs
            != tuple(sorted({ref for _, refs in self.source_locator_refs for ref in refs}))
        ):
            raise ValueError("field_prompt_invalid")
        return self


class Schema67TaskSliceV1(_FrozenModel):
    task_key: NonBlankStr
    task_kind: Literal["material", "synthesis"]
    material_roles: tuple[MaterialRole, ...]
    field_ids: tuple[NonBlankStr, ...]
    task_slice_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_bounded_exact_slice(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"task_slice_sha256"})
        if (
            not self.field_ids
            or len(self.field_ids) > 9
            or len(self.field_ids) != len(set(self.field_ids))
            or not self.material_roles
            or len(self.material_roles) != len(set(self.material_roles))
            or (self.task_kind == "material" and len(self.material_roles) != 1)
            or (self.task_kind == "synthesis" and len(self.material_roles) < 2)
            or self.task_slice_sha256 != canonical_hash(_TASK_SLICE_OBJECT_TYPE, payload)
        ):
            raise ValueError("task_slice_invalid")
        return self


class Schema67BatchBudgetPolicyV1(_FrozenModel):
    max_main_tasks: Literal[8] = 8
    max_provider_calls: Literal[16] = 16
    max_transport_retries: Literal[1] = 1
    max_shared_extra_calls: Literal[8] = 8
    max_response_contract_repairs: Literal[1] = 1
    max_evidence_repairs: Literal[8] = 8
    budget_identity_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_budget_identity(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"budget_identity_sha256"})
        if self.budget_identity_sha256 != canonical_hash(_BATCH_BUDGET_OBJECT_TYPE, payload):
            raise ValueError("batch_budget_identity_mismatch")
        return self


def _batch_budget_policy() -> Schema67BatchBudgetPolicyV1:
    payload = {
        "max_main_tasks": 8,
        "max_provider_calls": 16,
        "max_transport_retries": 1,
        "max_shared_extra_calls": 8,
        "max_response_contract_repairs": 1,
        "max_evidence_repairs": 8,
    }
    return Schema67BatchBudgetPolicyV1(
        max_main_tasks=8,
        max_transport_retries=1,
        max_shared_extra_calls=8,
        max_response_contract_repairs=1,
        max_evidence_repairs=8,
        budget_identity_sha256=canonical_hash(_BATCH_BUDGET_OBJECT_TYPE, payload),
    )


class Schema67ExecutionPlanV1(_FrozenModel):
    contract_set_sha256: Sha256Hex
    task_slices: tuple[Schema67TaskSliceV1, ...]
    deferred_unknown_field_ids: tuple[NonBlankStr, ...]
    batch_budget: Schema67BatchBudgetPolicyV1
    execution_plan_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_plan_hash(self) -> Self:
        payload = {
            "contract_set_sha256": self.contract_set_sha256,
            "task_slices": tuple(item.model_dump(mode="python") for item in self.task_slices),
            "deferred_unknown_field_ids": self.deferred_unknown_field_ids,
            "batch_budget": self.batch_budget.model_dump(mode="python"),
        }
        if self.execution_plan_sha256 != canonical_hash(_EXECUTION_PLAN_OBJECT_TYPE, payload):
            raise ValueError("execution plan hash mismatch")
        return self


DeferredReason815 = Literal["FORMATION_MODE_DEFERRED", "SOURCE_NOT_AVAILABLE"]


@dataclass(frozen=True, slots=True)
class DeferredFieldDisposition815V1:
    field_id: str
    reason: DeferredReason815


@dataclass(frozen=True, slots=True)
class Schema67NativePdfExecutionProjection815V1:
    contract: Literal["schema67-native-pdf-execution-projection.815.v1"]
    available_source_roles: tuple[MaterialRole, ...]
    execution_plan: Schema67ExecutionPlanV1
    provider_visible_field_ids: tuple[str, ...]
    code_deferred: tuple[DeferredFieldDisposition815V1, ...]
    projection_sha256: str

    @property
    def provider_visible_field_count(self) -> int:
        return len(self.provider_visible_field_ids)

    @property
    def code_deferred_field_ids(self) -> tuple[str, ...]:
        return tuple(item.field_id for item in self.code_deferred)

    @property
    def code_deferred_field_count(self) -> int:
        return len(self.code_deferred)

    @property
    def dispositioned_field_count(self) -> int:
        return self.provider_visible_field_count + self.code_deferred_field_count

    def recomputed_projection_sha256(self) -> str:
        return canonical_hash(
            _NATIVE_PDF_EXECUTION_PROJECTION_OBJECT_TYPE,
            {
                "contract": self.contract,
                "available_source_roles": self.available_source_roles,
                "execution_plan": self.execution_plan.model_dump(mode="python"),
                "provider_visible_field_ids": self.provider_visible_field_ids,
                "code_deferred": tuple(
                    {"field_id": item.field_id, "reason": item.reason}
                    for item in self.code_deferred
                ),
            },
        )


@dataclass(frozen=True, slots=True)
class Schema67RoleTaskInputV1:
    task_key: str
    material_role: MaterialRole
    space_id: str
    product_version_id: str
    source_revision_id: str
    module_id: str
    risk_partition_id: str
    allowed_locator_refs: tuple[tuple[NonBlankStr, tuple[NonBlankStr, ...]], ...] = field(
        repr=False
    )
    input_refs: ExtractionInputRefsV1 = field(repr=False)
    task_profile: ExtractionTaskProfileV1 = field(repr=False)


@dataclass(frozen=True, slots=True)
class Schema67PreparedTaskV1:
    task_key: str
    task_kind: Literal["material", "synthesis"]
    source_tasks: tuple[ExtractionTaskV1, ...]
    initial_attempts: tuple[AttemptRequestV1, ...]
    field_prompts: tuple[DeepSeekFieldPromptInputV1, ...] = field(repr=False)
    provider_task_sha256: str
    provider_attempt_sha256: str
    execution_plan_sha256: str
    task_slice_sha256: str


class Schema67BoundAttemptV1(_FrozenModel):
    """Task-local 054/057 custody for one exact Schema67 provider task."""

    task_id: Sha256Hex
    attempt_hash: Sha256Hex
    execution_plan_sha256: Sha256Hex
    task_slice_sha256: Sha256Hex
    outputs: tuple[FreeformFieldOutputV1, ...] = Field(repr=False)
    evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...]
    verification_batches: tuple[VerificationBatchV1, ...]
    receipt_chains: tuple[ReceiptChainV1, ...]
    bound_attempt_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_bound_attempt(self) -> Self:
        fields = tuple(item.field_id for item in self.outputs)
        payload = {
            "task_id": self.task_id,
            "attempt_hash": self.attempt_hash,
            "execution_plan_sha256": self.execution_plan_sha256,
            "task_slice_sha256": self.task_slice_sha256,
            "output_hashes": tuple(
                canonical_hash("schema67-deepseek-field-output.v1", item.model_dump(mode="python"))
                for item in self.outputs
            ),
            "evidence_receipt_hashes": tuple(item.receipt_hash for item in self.evidence_receipts),
            "verification_hashes": tuple(
                item.verification_hash for item in self.verification_batches
            ),
            "receipt_chain_hashes": tuple(
                tuple(item.receipt_hash for item in chain.receipts) for chain in self.receipt_chains
            ),
        }
        if (
            not fields
            or fields != tuple(item.field_id for item in self.evidence_receipts)
            or len(fields) != len(set(fields))
            or self.bound_attempt_hash
            != canonical_hash("schema67-deepseek-bound-attempt.v1", payload)
        ):
            raise ValueError("schema67_bound_attempt_invalid")
        return self


class Schema67RepairBindingV1(_FrozenModel):
    resolution: RepairResolutionV1
    outputs: tuple[FreeformFieldOutputV1, ...] = Field(repr=False)
    evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...]
    verification_batches: tuple[VerificationBatchV1, ...]
    receipt_chains: tuple[ReceiptChainV1, ...]


class DeepSeekRepairRequestV1(_FrozenModel):
    attempt_hash: Sha256Hex
    repair_plan_hash: Sha256Hex
    parent_bound_attempt_hash: Sha256Hex
    field_ids: tuple[NonBlankStr, ...]
    approved_locators: tuple[tuple[NonBlankStr, tuple[NonBlankStr, ...]], ...]
    attempt: AttemptRequestV1 | None = Field(default=None, repr=False)
    locator_plan: TargetedRepairPlanV1 | None = Field(default=None, repr=False)
    initial: BoundSemanticAttemptV1 | Schema67BoundAttemptV1 | None = Field(
        default=None, repr=False
    )

    @model_validator(mode="after")
    def require_exact_repair_scope(self) -> Self:
        if (
            not self.field_ids
            or len(self.field_ids) != len(set(self.field_ids))
            or tuple(item[0] for item in self.approved_locators) != self.field_ids
            or len(
                {
                    self.attempt is None,
                    self.locator_plan is None,
                    self.initial is None,
                }
            )
            != 1
        ):
            raise ValueError("repair_scope_invalid")
        if self.attempt is not None and (
            self.attempt.attempt_hash != self.attempt_hash
            or self.attempt.field_ids != self.field_ids
            or self.locator_plan is None
            or self.locator_plan.field_ids != self.field_ids
            or self.locator_plan.plan_hash != self.repair_plan_hash
            or self.initial is None
            or self.initial.task_id == ""
            or self.initial.bound_attempt_hash != self.parent_bound_attempt_hash
        ):
            raise ValueError("repair_scope_invalid")
        return self


def _ordered_unique_subset(
    values: tuple[str, ...],
    authority: tuple[str, ...],
) -> bool:
    if not authority or len(authority) != len(set(authority)):
        return False
    selected = set(values)
    return len(values) == len(selected) and values == tuple(
        item for item in authority if item in selected
    )


class ResponseContractRepairResolutionV2(_FrozenModel):
    contract: Literal["schema67-response-contract-repair-resolution.v2"]
    kind: Literal["response_contract_repair"]
    failure_code: ResponseContractRepairFailureCode
    response_contract_repair_policy_sha256: Sha256Hex
    field_ids: tuple[NonBlankStr, ...]
    failed_field_ids: tuple[NonBlankStr, ...]
    parent_extractor_request_sha256: Sha256Hex
    invalid_response_sha256: Sha256Hex
    repair_request_sha256: Sha256Hex
    accepted_response_sha256: Sha256Hex
    resolution_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_resolution_hash(self) -> Self:
        if (
            self.response_contract_repair_policy_sha256 != _RESPONSE_CONTRACT_REPAIR_POLICY_SHA256
            or not _ordered_unique_subset(self.failed_field_ids, self.field_ids)
            or (self.failure_code == "LOCATOR_NOT_ALLOWED") != bool(self.failed_field_ids)
        ):
            raise ValueError("response_contract_repair_resolution_invalid")
        payload = self.model_dump(mode="python", exclude={"resolution_hash"})
        if self.resolution_hash != canonical_hash(
            "schema67-response-contract-repair-resolution.v2", payload
        ):
            raise ValueError("response_contract_repair_resolution_invalid")
        return self


class EvidenceRepairTraceV2(_FrozenModel):
    contract: Literal["schema67-evidence-repair-trace.v2"]
    kind: Literal["evidence_repair"]
    repair_request_sha256: Sha256Hex
    accepted_response_sha256: Sha256Hex
    repair_plan_sha256: Sha256Hex
    parent_bound_attempt_hash: Sha256Hex
    repair_plan: TargetedRepairPlanV1
    verifier_resolution: RepairResolutionV1
    trace_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_resolution_hash(self) -> Self:
        if (
            self.repair_plan.plan_hash != self.repair_plan_sha256
            or self.verifier_resolution.parent_verification_hash
            != self.repair_plan.parent_verification_hash
            or self.verifier_resolution.repair_plan_hash != self.repair_plan_sha256
        ):
            raise ValueError("evidence_repair_resolution_invalid")
        payload = {
            "contract": self.contract,
            "kind": self.kind,
            "repair_request_sha256": self.repair_request_sha256,
            "accepted_response_sha256": self.accepted_response_sha256,
            "repair_plan_sha256": self.repair_plan_sha256,
            "parent_bound_attempt_hash": self.parent_bound_attempt_hash,
            "repair_plan": self.repair_plan.model_dump(mode="python", exclude={"plan_hash"}),
            "verifier_resolution": self.verifier_resolution.model_dump(
                mode="python", exclude={"resolution_hash"}
            ),
        }
        if self.trace_hash != canonical_hash("schema67-evidence-repair-trace.v2", payload):
            raise ValueError("evidence_repair_trace_invalid")
        return self


class EvidenceRepairReceiptSummaryV2(_FrozenModel):
    contract: Literal["schema67-evidence-repair-receipt-summary.v2"]
    kind: Literal["evidence_repair"]
    repair_request_sha256: Sha256Hex
    accepted_response_sha256: Sha256Hex
    repair_plan_sha256: Sha256Hex
    parent_bound_attempt_hash: Sha256Hex
    parent_verification_hash: Sha256Hex
    repair_field_ids: tuple[NonBlankStr, ...]
    repair_field_count: Annotated[StrictInt, Field(ge=1, le=8)]
    verifier_resolution_hash: Sha256Hex
    trace_hash: Sha256Hex
    summary_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_summary(self) -> Self:
        if len(self.repair_field_ids) != self.repair_field_count or len(
            self.repair_field_ids
        ) != len(set(self.repair_field_ids)):
            raise ValueError("evidence_repair_summary_invalid")
        payload = self.model_dump(mode="python", exclude={"summary_hash"})
        if self.summary_hash != canonical_hash(
            "schema67-evidence-repair-receipt-summary.v2", payload
        ):
            raise ValueError("evidence_repair_summary_invalid")
        return self


def _evidence_repair_trace_payload(
    repair: EvidenceRepairTraceV2,
) -> dict[str, object]:
    return {
        "contract": repair.contract,
        "kind": repair.kind,
        "repair_request_sha256": repair.repair_request_sha256,
        "accepted_response_sha256": repair.accepted_response_sha256,
        "repair_plan_sha256": repair.repair_plan_sha256,
        "parent_bound_attempt_hash": repair.parent_bound_attempt_hash,
        "repair_plan": repair.repair_plan.model_dump(mode="python", exclude={"plan_hash"}),
        "verifier_resolution": repair.verifier_resolution.model_dump(
            mode="python", exclude={"resolution_hash"}
        ),
        "trace_hash": repair.trace_hash,
    }


def _evidence_repair_summary(
    trace: EvidenceRepairTraceV2,
) -> EvidenceRepairReceiptSummaryV2:
    values = {
        "contract": "schema67-evidence-repair-receipt-summary.v2",
        "kind": "evidence_repair",
        "repair_request_sha256": trace.repair_request_sha256,
        "accepted_response_sha256": trace.accepted_response_sha256,
        "repair_plan_sha256": trace.repair_plan_sha256,
        "parent_bound_attempt_hash": trace.parent_bound_attempt_hash,
        "parent_verification_hash": trace.repair_plan.parent_verification_hash,
        "repair_field_ids": trace.repair_plan.field_ids,
        "repair_field_count": len(trace.repair_plan.field_ids),
        "verifier_resolution_hash": trace.verifier_resolution.resolution_hash,
        "trace_hash": trace.trace_hash,
    }
    return EvidenceRepairReceiptSummaryV2.model_validate(
        {
            **values,
            "summary_hash": canonical_hash("schema67-evidence-repair-receipt-summary.v2", values),
        }
    )


class EvidenceDemotionReceiptV1(_FrozenModel):
    """Private one-shot receipt for code-owned 057 non-PASS demotion."""

    policy_sha256: Sha256Hex
    parent_bound_attempt_sha256: Sha256Hex
    verification_batch_hashes: tuple[Sha256Hex, ...]
    demoted_field_ids: tuple[NonBlankStr, ...]
    initial_output_sha256: Sha256Hex
    final_output_sha256: Sha256Hex
    final_evidence_receipt_hashes: tuple[Sha256Hex, ...]
    pass_preservation_sha256: Sha256Hex
    receipt_hash: Sha256Hex

    @model_validator(mode="after")
    def require_fixed_policy_and_self_hash(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"receipt_hash"})
        if (
            self.policy_sha256 != _EVIDENCE_DEMOTION_POLICY_SHA256
            or not self.verification_batch_hashes
            or not self.demoted_field_ids
            or len(self.demoted_field_ids) != len(set(self.demoted_field_ids))
            or self.receipt_hash != canonical_hash(_EVIDENCE_DEMOTION_RECEIPT_OBJECT_TYPE, payload)
        ):
            raise ValueError("evidence_demotion_receipt_invalid")
        return self


class DeepSeekExecutionReceiptV1(_FrozenModel):
    contract: Literal["deepseek-task-execution-receipt.v2"]
    model_identity: ModelIdentity
    execution_identity_sha256: Sha256Hex
    batch_budget_identity_sha256: Sha256Hex
    execution_plan_sha256: Sha256Hex | None
    task_slice_sha256: Sha256Hex | None
    schema_workbook_sha256: Literal[
        "808473db9c4d0093bc4ddbe9e11dae6ef6f6c6927aefc6ce6fe65d1a9f56bb29"
    ]
    approved_by: Literal["linyao"]
    task_id: NonBlankStr
    attempt_hash: Sha256Hex
    field_ids: tuple[NonBlankStr, ...]
    field_contracts_sha256: Sha256Hex
    locator_selection_policy_sha256: Sha256Hex
    locator_authority_sha256: Sha256Hex
    locator_selection_sha256: Sha256Hex
    locator_slot_policy_sha256: Sha256Hex
    locator_slot_authority_sha256: Sha256Hex
    response_contract_repair_policy_sha256: Sha256Hex
    extractor_request_sha256: Sha256Hex
    response_contract_repair: ResponseContractRepairResolutionV2 | None
    evidence_repair_summary: EvidenceRepairReceiptSummaryV2 | None
    evidence_demotion: EvidenceDemotionReceiptV1 | None = None
    initial_bound_attempt_hash: Sha256Hex
    initial_outputs_sha256: Sha256Hex
    final_outputs_sha256: Sha256Hex
    evidence_receipt_hashes: tuple[Sha256Hex, ...]
    locator_calls: Literal[0]
    extractor_calls: Annotated[StrictInt, Field(ge=1, le=2)]
    repair_calls: Annotated[StrictInt, Field(ge=0, le=2)]
    transport_retries: Literal[0, 1]
    response_contract_repairs: Literal[0, 1]
    evidence_repairs: Literal[0, 1]
    total_calls: Annotated[StrictInt, Field(ge=1, le=3)]
    receipt_hash: Sha256Hex

    @model_validator(mode="after")
    def require_exact_budget_and_hash(self) -> Self:
        extras = self.transport_retries + self.response_contract_repairs + self.evidence_repairs
        history = (
            self.extractor_calls,
            self.repair_calls,
            self.transport_retries,
            self.response_contract_repairs,
            self.evidence_repairs,
            self.total_calls,
        )
        allowed_histories = {
            (1, 0, 0, 0, 0, 1),
            (2, 0, 1, 0, 0, 2),
            (1, 1, 0, 1, 0, 2),
            (1, 1, 0, 0, 1, 2),
            (2, 1, 1, 1, 0, 3),
            (1, 2, 1, 1, 0, 3),
            (2, 1, 1, 0, 1, 3),
            (1, 2, 1, 0, 1, 3),
            (1, 2, 0, 1, 1, 3),
        }
        if (
            history not in allowed_histories
            or (
                self.evidence_repair_summary is not None
                and (
                    len(self.evidence_repair_summary.repair_field_ids)
                    != len(set(self.evidence_repair_summary.repair_field_ids))
                    or not set(self.evidence_repair_summary.repair_field_ids).issubset(
                        self.field_ids
                    )
                )
            )
            or (
                self.evidence_repair_summary is not None
                and self.evidence_repair_summary.repair_field_count > len(self.field_ids)
            )
            or self.locator_calls + self.extractor_calls + self.repair_calls != self.total_calls
            or self.total_calls != 1 + extras
            or extras > 2
            or self.locator_calls != 0
            or self.extractor_calls < 1
            or self.repair_calls < self.response_contract_repairs + self.evidence_repairs
            or self.extractor_calls
            - 1
            + self.repair_calls
            - self.response_contract_repairs
            - self.evidence_repairs
            != self.transport_retries
            or (self.response_contract_repair is None) != (self.response_contract_repairs == 0)
            or (self.evidence_repair_summary is None) != (self.evidence_repairs == 0)
            or self.execution_identity_sha256 != DEEPSEEK_EXECUTION_IDENTITY_SHA256
            or self.batch_budget_identity_sha256 != _batch_budget_policy().budget_identity_sha256
            or self.model_identity != DEEPSEEK_MODEL_IDENTITY
            or self.locator_selection_policy_sha256 != LOCATOR_SELECTION_POLICY_SHA256
            or self.locator_slot_policy_sha256 != LOCATOR_SLOT_POLICY_SHA256
            or self.response_contract_repair_policy_sha256
            != _RESPONSE_CONTRACT_REPAIR_POLICY_SHA256
            or (self.execution_plan_sha256 is None) != (self.task_slice_sha256 is None)
        ):
            raise ValueError("deepseek_execution_budget_mismatch")
        response_repair = self.response_contract_repair
        decode_repair = response_repair is not None and response_repair.failure_code in (
            _RESPONSE_DECODE_REPAIRABLE_CODES
        )
        if decode_repair and (
            self.extractor_calls,
            self.repair_calls,
            self.transport_retries,
            self.response_contract_repairs,
            self.evidence_repairs,
            self.total_calls,
        ) != (2, 1, 1, 1, 0, 3):
            raise ValueError("deepseek_decode_repair_history_mismatch")
        if response_repair is not None and (
            response_repair.parent_extractor_request_sha256 != self.extractor_request_sha256
            or response_repair.field_ids != self.field_ids
            or response_repair.response_contract_repair_policy_sha256
            != self.response_contract_repair_policy_sha256
        ):
            raise ValueError("deepseek_response_contract_repair_custody_mismatch")
        if self.evidence_repair_summary is not None and (
            self.evidence_repair_summary.parent_bound_attempt_hash
            != self.initial_bound_attempt_hash
        ):
            raise ValueError("deepseek_evidence_repair_custody_mismatch")
        payload = self.model_dump(
            mode="python",
            exclude={
                "receipt_hash": True,
            },
        )
        if self.receipt_hash != canonical_hash(_EXECUTION_RECEIPT_OBJECT_TYPE, payload):
            raise ValueError("deepseek_execution_receipt_hash_mismatch")
        return self


@dataclass(frozen=True, slots=True)
class DeepSeekTaskExecutionV1:
    initial: BoundSemanticAttemptV1 | Schema67BoundAttemptV1 = field(repr=False)
    initial_outputs: tuple[FreeformFieldOutputV1, ...] = field(repr=False)
    final_outputs: tuple[FreeformFieldOutputV1, ...] = field(repr=False)
    evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...] = field(repr=False)
    response_contract_repair: ResponseContractRepairResolutionV2 | None = field(repr=False)
    evidence_repair: EvidenceRepairTraceV2 | None = field(repr=False)
    evidence_demotion: EvidenceDemotionReceiptV1 | None = field(repr=False)
    receipt: DeepSeekExecutionReceiptV1

    def __post_init__(self) -> None:
        checked_response_repair: ResponseContractRepairResolutionV2 | None = None
        checked_evidence_repair: EvidenceRepairTraceV2 | None = None
        checked_evidence_demotion: EvidenceDemotionReceiptV1 | None = None
        try:
            if self.response_contract_repair is not None:
                checked_response_repair = ResponseContractRepairResolutionV2.model_validate(
                    self.response_contract_repair.model_dump(mode="python")
                )
            if self.evidence_repair is not None:
                checked_evidence_repair = EvidenceRepairTraceV2.model_validate(
                    _evidence_repair_trace_payload(self.evidence_repair)
                )
            if self.evidence_demotion is not None:
                checked_evidence_demotion = EvidenceDemotionReceiptV1.model_validate(
                    self.evidence_demotion.model_dump(mode="python")
                )
            checked_receipt = DeepSeekExecutionReceiptV1.model_validate(
                self.receipt.model_dump(mode="python")
            )
        except (AttributeError, TypeError, ValueError, ValidationError):
            raise ValueError("deepseek_task_execution_custody_mismatch") from None
        if (
            checked_response_repair != self.response_contract_repair
            or checked_receipt != self.receipt
            or self.receipt.field_ids != tuple(item.field_id for item in self.initial_outputs)
            or self.receipt.initial_outputs_sha256 != _outputs_sha256(self.initial_outputs)
            or self.receipt.final_outputs_sha256 != _outputs_sha256(self.final_outputs)
            or self.receipt.evidence_receipt_hashes
            != tuple(item.receipt_hash for item in self.evidence_receipts)
            or self.receipt.response_contract_repair != checked_response_repair
            or self.receipt.evidence_repair_summary
            != (
                None
                if checked_evidence_repair is None
                else _evidence_repair_summary(checked_evidence_repair)
            )
            or checked_evidence_repair != self.evidence_repair
            or checked_evidence_demotion != self.evidence_demotion
            or self.receipt.evidence_demotion != checked_evidence_demotion
        ):
            raise ValueError("deepseek_task_execution_custody_mismatch")
        initial_by_field = {item.field_id: item for item in self.initial_outputs}
        final_by_field = {item.field_id: item for item in self.final_outputs}
        receipt_by_field = {item.field_id: item for item in self.evidence_receipts}
        initial_receipts = tuple(getattr(self.initial, "evidence_receipts", ()))
        initial_receipt_by_field = {item.field_id: item for item in initial_receipts}
        if (
            len(initial_by_field) != len(self.initial_outputs)
            or len(final_by_field) != len(self.final_outputs)
            or set(final_by_field) != set(initial_by_field)
            or len(receipt_by_field) != len(self.evidence_receipts)
            or (
                isinstance(self.initial, Schema67BoundAttemptV1)
                and set(receipt_by_field) != set(final_by_field)
            )
            or (
                bool(receipt_by_field)
                and any(
                    receipt_by_field[field_id].product_version_id
                    != final_by_field[field_id].product_version_id
                    or receipt_by_field[field_id].field_id != final_by_field[field_id].field_id
                    or receipt_by_field[field_id].state != final_by_field[field_id].state
                    or receipt_by_field[field_id].value_snapshot
                    != final_by_field[field_id].value_snapshot
                    or receipt_by_field[field_id].evidence != final_by_field[field_id].evidence
                    for field_id in final_by_field
                )
            )
        ):
            raise ValueError("deepseek_task_execution_custody_mismatch")
        evidence_repair = self.evidence_repair
        evidence_demotion = self.evidence_demotion
        expected_demotion: EvidenceDemotionReceiptV1 | None = None
        if (
            isinstance(self.initial, Schema67BoundAttemptV1)
            and self.response_contract_repair is None
            and evidence_repair is None
        ):
            try:
                (
                    expected_outputs,
                    expected_receipts,
                    expected_demotion,
                ) = _demote_initial_nonpass(self.initial, self.initial_outputs)
            except (KeyError, TypeError, ValueError, ValidationError):
                raise ValueError("deepseek_evidence_demotion_custody_mismatch") from None
            if (
                expected_outputs != self.final_outputs
                or expected_receipts != self.evidence_receipts
                or expected_demotion != evidence_demotion
            ):
                raise ValueError("deepseek_evidence_demotion_custody_mismatch")
        if evidence_demotion is not None:
            if (
                not isinstance(self.initial, Schema67BoundAttemptV1)
                or self.response_contract_repair is not None
                or evidence_repair is not None
                or self.receipt.transport_retries != 0
                or self.receipt.response_contract_repairs != 0
                or self.receipt.evidence_repairs != 0
                or self.receipt.repair_calls != 0
            ):
                raise ValueError("deepseek_evidence_demotion_custody_mismatch")
            if expected_demotion is None:
                raise ValueError("deepseek_evidence_demotion_custody_mismatch")
            return
        if evidence_repair is None:
            if (
                self.initial_outputs != self.final_outputs
                or initial_receipts != self.evidence_receipts
            ):
                raise ValueError("deepseek_task_execution_custody_mismatch")
            return
        plan = evidence_repair.repair_plan
        repaired_fields = set(plan.field_ids)
        if isinstance(self.initial, Schema67BoundAttemptV1):
            repaired_results = evidence_repair.verifier_resolution.results
            repaired_result_ids = tuple(item.field_id for item in repaired_results)
            if repaired_result_ids == plan.field_ids:
                try:
                    children = _schema67_repair_children(
                        initial=self.initial,
                        locator_refs=tuple(
                            (item.field_id, item.locator_refs)
                            for item in plan.approved_locators
                        ),
                    )
                    aggregate_parent_hash = _shared_repair_parent_hash(children)
                except (AttributeError, TypeError, ValueError, ValidationError):
                    raise ValueError(
                        "deepseek_evidence_repair_custody_mismatch"
                    ) from None
                unresolved_set = {
                    field_id
                    for child in children
                    for field_id in child.request.field_ids
                }
                unresolved_fields = tuple(
                    field_id
                    for field_id in self.receipt.field_ids
                    if field_id in unresolved_set
                )
                if (
                    not children
                    or aggregate_parent_hash != plan.parent_verification_hash
                    or unresolved_fields != plan.field_ids
                    or any(
                        item.status != "PASS"
                        and final_by_field[item.field_id].state != "unknown"
                        for item in repaired_results
                    )
                ):
                    raise ValueError("deepseek_evidence_repair_custody_mismatch")
            else:
                matching_batches = tuple(
                    item
                    for item in self.initial.verification_batches
                    if item.verification_hash == plan.parent_verification_hash
                )
                if len(matching_batches) != 1:
                    raise ValueError("deepseek_evidence_repair_custody_mismatch")
                initial_results = matching_batches[0].results
                nonpass_fields = {
                    item.field_id for item in initial_results if item.status != "PASS"
                }
                unresolved_fields = tuple(
                    field_id
                    for field_id in self.receipt.field_ids
                    if field_id in nonpass_fields
                    and initial_by_field[field_id].state != "unknown"
                )
                initial_result_ids = tuple(item.field_id for item in initial_results)
                if (
                    not initial_result_ids
                    or len(initial_result_ids) != len(set(initial_result_ids))
                    or not set(initial_result_ids).issubset(self.receipt.field_ids)
                    or plan.field_ids != unresolved_fields
                    or repaired_result_ids != initial_result_ids
                    or any(
                        before != after
                        for before, after in zip(
                            initial_results, repaired_results, strict=True
                        )
                        if before.status == "PASS"
                    )
                ):
                    raise ValueError("deepseek_evidence_repair_custody_mismatch")
        approved_by_field = {
            item.field_id: set(item.locator_refs) for item in plan.approved_locators
        }
        if (
            not repaired_fields.issubset(initial_by_field)
            or any(
                initial_by_field[field_id] != final_by_field[field_id]
                for field_id in initial_by_field
                if field_id not in repaired_fields
            )
            or any(
                initial_receipt_by_field.get(field_id) != receipt_by_field.get(field_id)
                for field_id in initial_by_field
                if field_id not in repaired_fields
            )
            or (
                isinstance(self.initial, Schema67BoundAttemptV1)
                and any(
                    {
                        evidence.locator.subject_ref
                        for evidence in receipt_by_field[field_id].evidence
                    }
                    - approved_by_field[field_id]
                    for field_id in repaired_fields
                )
            )
        ):
            raise ValueError("deepseek_evidence_repair_custody_mismatch")


@dataclass(frozen=True, slots=True)
class Schema67BatchExecutionV1:
    executions: tuple[DeepSeekTaskExecutionV1, ...] = field(repr=False)
    receipt: Schema67BatchExecutionReceiptV1


def _is_single_pass_mvp_operational_tuple(payload: dict[str, object]) -> bool:
    return tuple(
        payload.get(field_name)
        for field_name in (
            "task_count",
            "provider_calls",
            "extractor_calls",
            "locator_calls",
            "transport_retries",
            "response_contract_repairs",
            "evidence_repairs",
            "repair_calls",
        )
    ) == (8, 8, 8, 0, 0, 0, 0, 0)


def _batch_receipt_sha256(payload: dict[str, object]) -> str:
    identity_payload: object = payload
    if _is_single_pass_mvp_operational_tuple(payload):
        identity_payload = {
            "receipt": payload,
            "prior_provider_ledger": {
                "external_sha256": _PRIOR_PROVIDER_LEDGER_EXTERNAL_SHA256,
                "internal_sha256": _PRIOR_PROVIDER_LEDGER_INTERNAL_SHA256,
            },
        }
    return canonical_hash(_BATCH_RECEIPT_OBJECT_TYPE, identity_payload)


class Schema67BatchExecutionReceiptV1(_FrozenModel):
    contract: Literal["schema67-deepseek-batch-receipt.v2"]
    execution_plan_sha256: Sha256Hex
    batch_budget_identity_sha256: Sha256Hex
    task_count: Annotated[StrictInt, Field(ge=1, le=8)]
    locator_calls: Literal[0]
    extractor_calls: Annotated[StrictInt, Field(ge=1, le=9)]
    transport_retries: Literal[0, 1]
    response_contract_repairs: Literal[0, 1]
    evidence_repairs: Annotated[StrictInt, Field(ge=0, le=8)]
    repair_calls: Annotated[StrictInt, Field(ge=0, le=8)]
    provider_calls: Annotated[StrictInt, Field(ge=1, le=16)]
    prior_provider_calls: Literal[2] | None = None
    cumulative_provider_calls: Literal[10] | None = None
    task_receipt_hashes: tuple[Sha256Hex, ...]
    batch_receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_batch_receipt(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"batch_receipt_sha256"})
        extras = self.transport_retries + self.response_contract_repairs + self.evidence_repairs
        cumulative_values = (
            self.prior_provider_calls,
            self.cumulative_provider_calls,
        )
        single_pass_mvp = _is_single_pass_mvp_operational_tuple(payload)
        if (
            self.batch_budget_identity_sha256 != _batch_budget_policy().budget_identity_sha256
            or len(self.task_receipt_hashes) != self.task_count
            or self.locator_calls != 0
            or self.provider_calls != self.extractor_calls + self.repair_calls
            or self.provider_calls != self.task_count + extras
            or extras > 8
            or cumulative_values != ((2, 10) if single_pass_mvp else (None, None))
            or self.batch_receipt_sha256 != _batch_receipt_sha256(payload)
        ):
            raise ValueError("batch_receipt_invalid")
        return self


class Schema67EvidenceBindingPort(Protocol):
    @property
    def task_id(self) -> str: ...

    @property
    def attempt_hash(self) -> str: ...

    @property
    def field_ids(self) -> tuple[str, ...]: ...

    @property
    def arm_blueprint_hash(self) -> str: ...

    @property
    def model_identity_sha256(self) -> str: ...

    @property
    def normalizer_identity_sha256(self) -> str: ...

    def validate_locators(self, locators: tuple[CanonicalLocatorInputV1, ...]) -> None: ...

    def hydrate_extractor_outputs(
        self,
        *,
        selections: tuple[_ExtractorFieldSelectionV1, ...],
        contracts: tuple[DeepSeekFieldPromptInputV1, ...],
        locators: tuple[CanonicalLocatorInputV1, ...],
    ) -> tuple[FreeformFieldOutputV1, ...]: ...

    def bind_initial(
        self, response_json: bytes
    ) -> BoundSemanticAttemptV1 | Schema67BoundAttemptV1: ...

    def prepare_repair(
        self,
        initial: BoundSemanticAttemptV1 | Schema67BoundAttemptV1,
        locator_refs: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> DeepSeekRepairRequestV1 | None: ...

    def bind_repair(
        self,
        response_json: bytes,
        request: DeepSeekRepairRequestV1,
    ) -> RepairResolutionV1 | Schema67RepairBindingV1: ...


@dataclass(slots=True)
class _Budget:
    calls: int = 0
    retries: int = 0
    locator_calls: int = 0
    extractor_calls: int = 0
    repair_calls: int = 0


@dataclass(slots=True)
class Schema67BatchBudgetV1:
    """One in-memory batch budget; it grants no provider or field authority."""

    task_count: int = 0
    locator_calls: int = 0
    extractor_calls: int = 0
    transport_retries: int = 0
    response_contract_repairs: int = 0
    evidence_repairs: int = 0
    repair_calls: int = 0
    _grouped_evidence_repair_task_indexes: set[int] = field(
        default_factory=set,
        repr=False,
    )

    @property
    def identity_sha256(self) -> str:
        return _batch_budget_policy().budget_identity_sha256

    def start_task(self) -> None:
        if self.task_count >= 8:
            raise DeepSeekCompilerError("BATCH_MAIN_TASK_BUDGET_EXHAUSTED")
        self.task_count += 1

    def record_call(self, stage: Literal["extractor", "repair"]) -> None:
        provider_limit = (
            16 if self._grouped_evidence_repair_task_indexes else 10
        )
        if self.extractor_calls + self.repair_calls >= provider_limit:
            raise DeepSeekCompilerError("BATCH_PROVIDER_CALL_BUDGET_EXHAUSTED")
        if stage == "extractor":
            self.extractor_calls += 1
        else:
            self.repair_calls += 1

    def claim_retry(self) -> None:
        if self.transport_retries >= 1:
            raise DeepSeekCompilerError("BATCH_TRANSPORT_RETRY_EXHAUSTED")
        if self.extra_calls >= 2:
            raise DeepSeekCompilerError("BATCH_EXTRA_CALL_BUDGET_EXHAUSTED")
        self.transport_retries += 1

    def claim_repair(self, kind: Literal["response_contract", "evidence"]) -> None:
        if kind == "response_contract" and self.response_contract_repairs >= 1:
            raise DeepSeekCompilerError("BATCH_RESPONSE_CONTRACT_REPAIR_EXHAUSTED")
        if kind == "evidence" and self.evidence_repairs >= 1:
            raise DeepSeekCompilerError("BATCH_EVIDENCE_REPAIR_EXHAUSTED")
        if self.extra_calls >= 2:
            raise DeepSeekCompilerError("BATCH_EXTRA_CALL_BUDGET_EXHAUSTED")
        if kind == "response_contract":
            self.response_contract_repairs += 1
        else:
            self.evidence_repairs += 1

    def claim_grouped_evidence_repair(self, task_index: int) -> None:
        if (
            type(task_index) is not int
            or task_index < 0
            or task_index >= 8
            or task_index in self._grouped_evidence_repair_task_indexes
            or self.evidence_repairs >= 8
            or self.extra_calls >= 8
        ):
            raise DeepSeekCompilerError("BATCH_EVIDENCE_REPAIR_EXHAUSTED")
        self._grouped_evidence_repair_task_indexes.add(task_index)
        self.evidence_repairs += 1

    @property
    def extra_calls(self) -> int:
        return self.transport_retries + self.response_contract_repairs + self.evidence_repairs


def build_schema67_batch_receipt(
    *,
    execution_plan: Schema67ExecutionPlanV1,
    prepared_tasks: Sequence[Schema67PreparedTaskV1],
    budget: Schema67BatchBudgetV1,
    executions: Sequence[DeepSeekTaskExecutionV1],
    _single_pass_mvp: bool = False,
) -> Schema67BatchExecutionReceiptV1:
    """Bind the eight-task ceiling and the two batch-wide extras after execution."""

    prepared = tuple(prepared_tasks)
    exact_executions = tuple(executions)
    response_repair_calls = {
        item.response_contract_repair.repair_request_sha256
        for item in exact_executions
        if item.response_contract_repair is not None
    }
    evidence_repair_calls = {
        item.evidence_repair.repair_request_sha256
        for item in exact_executions
        if item.evidence_repair is not None
    }
    evidence_repair_task_indexes = {
        index
        for index, item in enumerate(exact_executions)
        if item.evidence_repair is not None
    }
    repair_calls = response_repair_calls | evidence_repair_calls
    if (
        budget.task_count != len(exact_executions)
        or len(prepared) != len(exact_executions)
        or budget.task_count > execution_plan.batch_budget.max_main_tasks
        or budget.extractor_calls + budget.repair_calls
        > execution_plan.batch_budget.max_provider_calls
        or budget.transport_retries > execution_plan.batch_budget.max_transport_retries
        or budget.extra_calls > execution_plan.batch_budget.max_shared_extra_calls
        or budget.response_contract_repairs
        > execution_plan.batch_budget.max_response_contract_repairs
        or budget.evidence_repairs > execution_plan.batch_budget.max_evidence_repairs
        or budget.locator_calls != 0
        or budget.locator_calls != sum(item.receipt.locator_calls for item in exact_executions)
        or budget.extractor_calls != sum(item.receipt.extractor_calls for item in exact_executions)
        or budget.repair_calls != len(repair_calls)
        or budget.transport_retries
        != sum(item.receipt.transport_retries for item in exact_executions)
        or budget.response_contract_repairs != len(response_repair_calls)
        or budget.evidence_repairs != len(evidence_repair_calls)
        or (
            budget._grouped_evidence_repair_task_indexes
            and budget._grouped_evidence_repair_task_indexes
            != evidence_repair_task_indexes
        )
        or any(
            execution.receipt.task_id != task.provider_task_sha256
            or execution.receipt.attempt_hash != task.provider_attempt_sha256
            or execution.receipt.execution_plan_sha256 != execution_plan.execution_plan_sha256
            or execution.receipt.task_slice_sha256 != task.task_slice_sha256
            for task, execution in zip(prepared, exact_executions, strict=True)
        )
        or (
            _single_pass_mvp
            and (
                budget.task_count != 8
                or budget.extractor_calls != 8
                or budget.repair_calls != 0
                or budget.transport_retries != 0
                or budget.response_contract_repairs != 0
                or budget.evidence_repairs != 0
            )
        )
    ):
        raise DeepSeekCompilerError("BATCH_EXECUTION_RECEIPT_INVALID")
    payload: dict[str, object] = {
        "contract": "schema67-deepseek-batch-receipt.v2",
        "execution_plan_sha256": execution_plan.execution_plan_sha256,
        "batch_budget_identity_sha256": budget.identity_sha256,
        "task_count": budget.task_count,
        "locator_calls": budget.locator_calls,
        "extractor_calls": budget.extractor_calls,
        "transport_retries": budget.transport_retries,
        "response_contract_repairs": budget.response_contract_repairs,
        "evidence_repairs": budget.evidence_repairs,
        "repair_calls": budget.repair_calls,
        "provider_calls": budget.extractor_calls + budget.repair_calls,
        "task_receipt_hashes": tuple(item.receipt.receipt_hash for item in exact_executions),
    }
    operational_single_pass_mvp = _is_single_pass_mvp_operational_tuple(payload)
    payload["prior_provider_calls"] = 2 if operational_single_pass_mvp else None
    payload["cumulative_provider_calls"] = 10 if operational_single_pass_mvp else None
    try:
        return Schema67BatchExecutionReceiptV1.model_validate(
            {
                **payload,
                "batch_receipt_sha256": _batch_receipt_sha256(payload),
            }
        )
    except ValueError:
        raise DeepSeekCompilerError("BATCH_EXECUTION_RECEIPT_INVALID") from None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise DeepSeekCompilerError("FIELD_CONTRACT_INVALID") from None


def _outputs_sha256(outputs: Sequence[FreeformFieldOutputV1]) -> str:
    return canonical_hash(
        "schema67-deepseek-field-outputs.v1",
        tuple(item.model_dump(mode="python") for item in outputs),
    )


_SEMANTIC_CLAUSE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[，。；、,;.!?！？：:\n]+")
_SEMANTIC_COMPACT_RE: Final[re.Pattern[str]] = re.compile(r"[^0-9a-z\u3400-\u9fff]+")
_SEMANTIC_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"\d+(?:\.\d+)?%?")
_SEMANTIC_MATERIAL_MARKERS: Final[tuple[str, ...]] = (
    "不超过",
    "不少于",
    "不得",
    "必须",
    "至少",
    "至多",
    "以上",
    "以下",
    "以内",
    "以外",
    "除外",
    "例外",
    "需要",
    "最高",
    "最低",
    "须",
    "仅",
    "限",
    "无",
    "未",
    "且",
    "但",
)
_SEMANTIC_POLARITY_MARKERS: Final[tuple[str, ...]] = (
    "不",
    "未",
    "无",
    "非",
    "勿",
    "禁止",
)
_SEMANTIC_CLAUSE_MARKERS: Final[tuple[str, ...]] = tuple(
    dict.fromkeys((*_SEMANTIC_MATERIAL_MARKERS, *_SEMANTIC_POLARITY_MARKERS))
)
_SEMANTIC_GLOBAL_NEUTRAL_PREFIXES: Final[tuple[str, ...]] = ("", "本合同")
_SEMANTIC_FIELD_NEUTRAL_PREFIXES: Final[dict[str, tuple[str, ...]]] = {
    "entry_age_range": ("被保险人",),
}
_SEMANTIC_NEUTRAL_SUFFIXES: Final[tuple[str, ...]] = ("",)


def _semantic_compact(value: str) -> str:
    return _SEMANTIC_COMPACT_RE.sub("", unicodedata.normalize("NFKC", value).casefold())


def _semantic_marker_multiplicity(value: str) -> tuple[int, ...]:
    return tuple(value.count(marker) for marker in _SEMANTIC_CLAUSE_MARKERS)


def _semantic_clause_uses_only_neutral_wrappers(
    value_clause: str,
    quote_clause: str,
    field_id: str,
) -> bool:
    start = quote_clause.find(value_clause)
    while start >= 0:
        prefix = quote_clause[:start]
        suffix = quote_clause[start + len(value_clause) :]
        if (
            prefix in _SEMANTIC_GLOBAL_NEUTRAL_PREFIXES
            or prefix in _SEMANTIC_FIELD_NEUTRAL_PREFIXES.get(field_id, ())
        ) and suffix in _SEMANTIC_NEUTRAL_SUFFIXES:
            return True
        start = quote_clause.find(value_clause, start + 1)
    return False


def _semantic_clause_material_facts_preserved(
    value_clauses: Sequence[str],
    quote_clauses: Sequence[str],
    field_id: str,
) -> bool:
    if not value_clauses or len(value_clauses) > len(quote_clauses):
        return False
    for quote_offset in range(len(quote_clauses) - len(value_clauses) + 1):
        selected = quote_clauses[quote_offset : quote_offset + len(value_clauses)]
        if all(
            _semantic_clause_uses_only_neutral_wrappers(
                value_clause,
                quote_clause,
                field_id,
            )
            and _semantic_marker_multiplicity(value_clause)
            == _semantic_marker_multiplicity(quote_clause)
            and _SEMANTIC_NUMBER_RE.findall(value_clause)
            == _SEMANTIC_NUMBER_RE.findall(quote_clause)
            for value_clause, quote_clause in zip(value_clauses, selected, strict=True)
        ):
            return True
    return False


def _semantic_freeform_value_supported(output: FreeformFieldOutputV1) -> bool:
    """Accept only source-preserving freeform compression, never arbitrary paraphrase."""

    if output.state != "present" or output.value_snapshot is None:
        return False
    value = unicodedata.normalize("NFKC", output.value_snapshot).casefold()
    value_compact = _semantic_compact(value)
    if not value_compact:
        return False
    value_clauses = tuple(
        compact
        for item in _SEMANTIC_CLAUSE_SPLIT_RE.split(value)
        if (compact := _semantic_compact(item))
    )
    for evidence in output.evidence:
        quote = unicodedata.normalize("NFKC", evidence.quote_snapshot).casefold()
        quote_compact = _semantic_compact(quote)
        quote_clauses = tuple(
            compact
            for item in _SEMANTIC_CLAUSE_SPLIT_RE.split(quote)
            if (compact := _semantic_compact(item))
        )
        material_facts_preserved = _semantic_clause_material_facts_preserved(
            value_clauses,
            quote_clauses,
            output.field_id,
        )
        if value_compact in quote_compact and material_facts_preserved:
            return True
        if (
            len(value_clauses) < 2
            or len(value_compact) * 2 < len(quote_compact)
            or any(item not in quote_compact for item in value_clauses)
            or not material_facts_preserved
        ):
            continue
        return True
    return False


def _accept_freeform_semantic_value(
    batch: VerificationBatchV1,
    outputs: Sequence[FreeformFieldOutputV1],
) -> VerificationBatchV1:
    """Keep 057 Evidence exact and admit only mechanically source-supported values."""

    output_by_field = {item.field_id: item for item in outputs}
    results = tuple(
        type(item).model_validate(
            {
                **item.model_dump(mode="python"),
                "status": "PASS",
                "reason_codes": (),
            }
        )
        if item.reason_codes == ("value_not_supported_by_quote",)
        and _semantic_freeform_value_supported(output_by_field[item.field_id])
        else item
        for item in batch.results
    )
    return batch.model_copy(update={"results": results})


def _repairable_nonpass_fields(
    batch: VerificationBatchV1,
    outputs: Sequence[FreeformFieldOutputV1],
) -> tuple[str, ...]:
    nonpass = {item.field_id for item in batch.results if item.status != "PASS"}
    return tuple(
        item.field_id for item in outputs if item.field_id in nonpass and item.state != "unknown"
    )


def _apply_schema67_targeted_repair(
    *,
    document: ParsedDocumentV1,
    manifest: ParseManifestV1,
    initial: VerificationBatchV1,
    initial_outputs: Sequence[FreeformFieldOutputV1],
    plan: TargetedRepairPlanV1,
    repaired_outputs: tuple[FreeformFieldOutputV1, ...],
    repaired_candidates: tuple[FieldCandidateV1, ...],
    rules: tuple[FieldRuleV1, ...],
) -> RepairResolutionV1:
    """Verify only actionable failures while preserving legal UNKNOWN results."""

    if (
        plan.parent_verification_hash != initial.verification_hash
        or plan.field_ids != _repairable_nonpass_fields(initial, initial_outputs)
        or initial.product_version_id != document.subject.product_version_id
        or initial.source_revision_id != document.subject.source_revision_id
        or initial.parse_attempt_id != document.attempt.attempt_id
        or initial.parsed_document_hash != document.document_hash
        or initial.parse_manifest_hash != manifest.manifest_hash
    ):
        raise ValueError("repair_input_binding_mismatch")
    candidate_fields = tuple(item.field_id for item in repaired_candidates)
    rule_fields = tuple(item.field_id for item in rules)
    if candidate_fields != plan.field_ids or rule_fields != plan.field_ids:
        raise ValueError("repair_field_scope_mismatch")
    approved = {item.field_id: set(item.locator_refs) for item in plan.approved_locators}
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
        raise ValueError("repair_plan_locator_invalid")
    if any(
        evidence.locator.subject_ref not in approved[candidate.field_id]
        for candidate in repaired_candidates
        for evidence in candidate.evidence
    ):
        raise ValueError("repair_locator_not_approved")
    candidate_by_field = {item.field_id: item for item in repaired_candidates}
    rule_by_field = {item.field_id: item for item in rules}
    verification_fields = tuple(
        item.field_id for item in initial.results if item.field_id in candidate_by_field
    )
    if set(verification_fields) != set(plan.field_ids):
        raise ValueError("repair_field_scope_mismatch")
    repaired = _accept_freeform_semantic_value(
        evidence_verifier.verify_evidence_batch(
            document=document,
            manifest=manifest,
            candidates=tuple(candidate_by_field[item] for item in verification_fields),
            rules=tuple(rule_by_field[item] for item in verification_fields),
        ),
        repaired_outputs,
    )
    repaired_by_field = {item.field_id: item for item in repaired.results}
    merged = tuple(repaired_by_field.get(item.field_id, item) for item in initial.results)
    merged_batch = initial.model_copy(update={"results": merged})
    unresolved = tuple(item for item in merged if item.status != "PASS")
    return RepairResolutionV1(
        contract="targeted-repair-resolution.v1",
        parent_verification_hash=initial.verification_hash,
        repair_plan_hash=plan.plan_hash,
        results=merged,
        gaps=tuple(
            GapV1(field_id=item.field_id, reason_codes=item.reason_codes) for item in unresolved
        ),
        review_items=tuple(
            EvidenceReviewItemV1(
                field_id=item.field_id,
                reason_code=item.reason_codes[0],
                parent_verification_hash=merged_batch.verification_hash,
            )
            for item in unresolved
        ),
    )


def _verification_nonpass_scope(
    initial: Schema67BoundAttemptV1,
    field_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Derive the only demotion scope from complete code-owned 057 batches."""

    if (
        not initial.verification_batches
        or len(initial.verification_batches) != len(initial.receipt_chains)
        or tuple(item.field_id for item in initial.outputs) != field_ids
        or tuple(item.field_id for item in initial.evidence_receipts) != field_ids
    ):
        raise ValueError("evidence_demotion_scope_invalid")
    allowed = set(field_ids)
    already_unknown = {item.field_id for item in initial.outputs if item.state == "unknown"}
    seen: set[str] = set()
    nonpass: set[str] = set()
    for batch, chain in zip(initial.verification_batches, initial.receipt_chains, strict=True):
        batch_ids = tuple(item.field_id for item in batch.results)
        if (
            not batch_ids
            or len(batch_ids) != len(set(batch_ids))
            or batch_ids != chain.task.field_ids
            or not set(batch_ids).issubset(allowed)
        ):
            raise ValueError("evidence_demotion_scope_invalid")
        try:
            bind_054_attempt_receipt(chain=chain, verification=batch)
        except Exception:
            raise ValueError("evidence_demotion_scope_invalid") from None
        seen.update(batch_ids)
        nonpass.update(
            item.field_id
            for item in batch.results
            if item.status != "PASS" and item.field_id not in already_unknown
        )
    if seen.union(already_unknown) != allowed:
        raise ValueError("evidence_demotion_scope_invalid")
    return tuple(field_id for field_id in field_ids if field_id in nonpass)


def _pass_preservation_sha256(
    *,
    field_ids: tuple[str, ...],
    demoted_field_ids: tuple[str, ...],
    initial_outputs: tuple[FreeformFieldOutputV1, ...],
    final_outputs: tuple[FreeformFieldOutputV1, ...],
    initial_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
    final_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
) -> str:
    demoted = set(demoted_field_ids)
    initial_output_by_id = {item.field_id: item for item in initial_outputs}
    final_output_by_id = {item.field_id: item for item in final_outputs}
    initial_receipt_by_id = {item.field_id: item for item in initial_receipts}
    final_receipt_by_id = {item.field_id: item for item in final_receipts}
    payload = tuple(
        {
            "field_id": field_id,
            "initial_output": initial_output_by_id[field_id].model_dump(mode="python"),
            "final_output": final_output_by_id[field_id].model_dump(mode="python"),
            "initial_evidence_receipt_hash": initial_receipt_by_id[field_id].receipt_hash,
            "final_evidence_receipt_hash": final_receipt_by_id[field_id].receipt_hash,
        }
        for field_id in field_ids
        if field_id not in demoted
    )
    return canonical_hash(_PASS_PRESERVATION_OBJECT_TYPE, payload)


def _demote_initial_nonpass(
    initial: Schema67BoundAttemptV1,
    initial_outputs: tuple[FreeformFieldOutputV1, ...],
) -> tuple[
    tuple[FreeformFieldOutputV1, ...],
    tuple[FreeformEvidenceBindingReceiptV1, ...],
    EvidenceDemotionReceiptV1 | None,
]:
    field_ids = tuple(item.field_id for item in initial_outputs)
    if (
        not initial.verification_batches
        and not initial.receipt_chains
        and all(item.state == "unknown" for item in initial_outputs)
        and tuple(item.field_id for item in initial.evidence_receipts) == field_ids
    ):
        return initial_outputs, initial.evidence_receipts, None
    demoted_field_ids = _verification_nonpass_scope(initial, field_ids)
    if not demoted_field_ids:
        return initial_outputs, initial.evidence_receipts, None
    demoted = set(demoted_field_ids)
    final_outputs = tuple(
        item.model_copy(update={"state": "unknown", "value_snapshot": None, "evidence": ()})
        if item.field_id in demoted
        else item
        for item in initial_outputs
    )
    initial_receipt_by_id = {item.field_id: item for item in initial.evidence_receipts}
    final_receipts = tuple(
        bind_freeform_arm_evidence(
            field_output=item,
            documents=(),
            manifests=(),
        )
        if item.field_id in demoted
        else initial_receipt_by_id[item.field_id]
        for item in final_outputs
    )
    values = {
        "policy_sha256": _EVIDENCE_DEMOTION_POLICY_SHA256,
        "parent_bound_attempt_sha256": initial.bound_attempt_hash,
        "verification_batch_hashes": tuple(
            item.verification_hash for item in initial.verification_batches
        ),
        "demoted_field_ids": demoted_field_ids,
        "initial_output_sha256": _outputs_sha256(initial_outputs),
        "final_output_sha256": _outputs_sha256(final_outputs),
        "final_evidence_receipt_hashes": tuple(item.receipt_hash for item in final_receipts),
        "pass_preservation_sha256": _pass_preservation_sha256(
            field_ids=field_ids,
            demoted_field_ids=demoted_field_ids,
            initial_outputs=initial_outputs,
            final_outputs=final_outputs,
            initial_receipts=initial.evidence_receipts,
            final_receipts=final_receipts,
        ),
    }
    receipt = EvidenceDemotionReceiptV1.model_validate(
        {
            **values,
            "receipt_hash": canonical_hash(_EVIDENCE_DEMOTION_RECEIPT_OBJECT_TYPE, values),
        }
    )
    return final_outputs, final_receipts, receipt


def _select_deepseek_execution_identity(
    candidates: tuple[SemanticExecutionIdentityV1, ...],
) -> SemanticExecutionIdentityV1:
    """Select the one canonical DeepSeek arm; model_id alone grants no authority."""

    matching = tuple(item for item in candidates if item.model_id == DEEPSEEK_MODEL)
    if (
        len(matching) != 1
        or matching[0].model_identity_sha256 != DEEPSEEK_EXECUTION_IDENTITY_SHA256
    ):
        raise DeepSeekCompilerError("SEMANTIC_EXECUTION_IDENTITY_MISMATCH")
    return matching[0]


def _task_slice(
    *,
    task_key: str,
    task_kind: Literal["material", "synthesis"],
    material_roles: tuple[MaterialRole, ...],
    field_ids: tuple[str, ...],
) -> Schema67TaskSliceV1:
    payload = {
        "task_key": task_key,
        "task_kind": task_kind,
        "material_roles": material_roles,
        "field_ids": field_ids,
    }
    return Schema67TaskSliceV1(
        task_key=task_key,
        task_kind=task_kind,
        material_roles=material_roles,
        field_ids=field_ids,
        task_slice_sha256=canonical_hash(_TASK_SLICE_OBJECT_TYPE, payload),
    )


def build_schema67_execution_plan(
    field_contracts: FieldContractSetV1,
) -> Schema67ExecutionPlanV1:
    """Derive the exact bounded provider plan from Lane A authority only."""

    try:
        exact = FieldContractSetV1.model_validate(
            field_contracts.model_dump(mode="python", round_trip=True)
        )
    except (AttributeError, TypeError, ValueError):
        raise DeepSeekCompilerError("SCHEMA67_CONTRACT_SET_INVALID") from None
    supported: tuple[MaterialRole, ...] = ("terms", "brochure", "rate_table")
    material_fields: dict[MaterialRole, list[str]] = {role: [] for role in supported}
    multi_fields: list[str] = []
    multi_roles: set[MaterialRole] = set()
    deferred: list[str] = []
    for contract in exact.contracts:
        roles = tuple(role for role in supported if role in contract.source_roles)
        if not roles:
            deferred.append(contract.field_id)
        elif len(roles) == 1:
            material_fields[roles[0]].append(contract.field_id)
        else:
            multi_fields.append(contract.field_id)
            multi_roles.update(roles)
    slice_values: list[
        tuple[str, Literal["material", "synthesis"], tuple[MaterialRole, ...], list[str]]
    ] = []
    for role in supported:
        fields = material_fields[role]
        for offset in range(0, len(fields), 8):
            slice_values.append(
                (
                    f"{role}-{offset // 8 + 1:02d}",
                    "material",
                    (role,),
                    list(fields[offset : offset + 8]),
                )
            )
    if multi_fields:
        slice_values.append(
            (
                "multi-source-01",
                "synthesis",
                tuple(role for role in supported if role in multi_roles),
                list(multi_fields),
            )
        )
    budget = _batch_budget_policy()
    if len(slice_values) != budget.max_main_tasks:
        raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID")
    field_order = {field_id: index for index, field_id in enumerate(APPROVED_ORDERED_FIELD_IDS)}
    target_order = (
        *(index for index, item in enumerate(slice_values) if len(item[3]) < 8),
        *(index for index, item in enumerate(slice_values) if len(item[3]) >= 8),
    )
    target_cursor = 0
    for field_id in deferred:
        while (
            target_cursor < len(target_order)
            and len(slice_values[target_order[target_cursor]][3]) >= 9
        ):
            target_cursor += 1
        if target_cursor == len(target_order):
            raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID")
        target = target_order[target_cursor]
        slice_values[target][3].append(field_id)
    slices = tuple(
        _task_slice(
            task_key=task_key,
            task_kind=task_kind,
            material_roles=material_roles,
            field_ids=tuple(sorted(field_ids, key=field_order.__getitem__)),
        )
        for task_key, task_kind, material_roles, field_ids in slice_values
    )
    if {len(item.field_ids) for item in slices} - {8, 9}:
        raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID")
    payload = {
        "contract_set_sha256": exact.contract_set_sha256,
        "task_slices": tuple(item.model_dump(mode="python") for item in slices),
        "deferred_unknown_field_ids": (),
        "batch_budget": budget.model_dump(mode="python"),
    }
    try:
        return Schema67ExecutionPlanV1(
            contract_set_sha256=exact.contract_set_sha256,
            task_slices=slices,
            deferred_unknown_field_ids=(),
            batch_budget=budget,
            execution_plan_sha256=canonical_hash(_EXECUTION_PLAN_OBJECT_TYPE, payload),
        )
    except ValueError:
        raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID") from None


def _native_pdf_field_disposition_815(
    contract: FieldContractV1,
    *,
    available_source_roles: frozenset[str],
) -> DeferredReason815 | None:
    if contract.formation_modes != ("source_extract",):
        return "FORMATION_MODE_DEFERRED"
    if not set(contract.source_roles).intersection(available_source_roles):
        return "SOURCE_NOT_AVAILABLE"
    return None


def build_schema67_native_pdf_execution_projection_815(
    *,
    field_contracts: FieldContractSetV1,
    base_execution_plan: Schema67ExecutionPlanV1,
    available_source_roles: tuple[MaterialRole, ...],
) -> Schema67NativePdfExecutionProjection815V1:
    """Project the exact pure-source subset without changing the eight task groups."""

    try:
        exact = FieldContractSetV1.model_validate(
            field_contracts.model_dump(mode="python", round_trip=True)
        )
        base = Schema67ExecutionPlanV1.model_validate(
            base_execution_plan.model_dump(mode="python", round_trip=True)
        )
        supported: tuple[MaterialRole, ...] = ("terms", "brochure", "rate_table")
        if (
            available_source_roles
            != tuple(role for role in supported if role in available_source_roles)
            or len(available_source_roles) != len(set(available_source_roles))
            or base != build_schema67_execution_plan(exact)
        ):
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID") from None

    available = frozenset(available_source_roles)
    by_id = {item.field_id: item for item in exact.contracts}
    dispositions = {
        item.field_id: _native_pdf_field_disposition_815(
            item,
            available_source_roles=available,
        )
        for item in exact.contracts
    }
    provider_visible = tuple(
        item.field_id for item in exact.contracts if dispositions[item.field_id] is None
    )
    deferred = tuple(
        DeferredFieldDisposition815V1(field_id=item.field_id, reason=reason)
        for item in exact.contracts
        if (reason := dispositions[item.field_id]) is not None
    )
    visible_set = set(provider_visible)
    filtered_slices: list[Schema67TaskSliceV1] = []
    for task_slice in base.task_slices:
        field_ids = tuple(
            field_id for field_id in task_slice.field_ids if field_id in visible_set
        )
        if not field_ids:
            raise DeepSeekCompilerError("NATIVE_PDF_SOURCE_EXTRACT_TASK_EMPTY")
        material_roles = tuple(
            role
            for role in task_slice.material_roles
            if role in available
            and any(role in by_id[field_id].source_roles for field_id in field_ids)
        )
        if (
            (task_slice.task_kind == "material" and len(material_roles) != 1)
            or (task_slice.task_kind == "synthesis" and len(material_roles) < 2)
        ):
            raise DeepSeekCompilerError("NATIVE_PDF_SOURCE_EXTRACT_TASK_ROLE_INVALID")
        filtered_slices.append(
            _task_slice(
                task_key=task_slice.task_key,
                task_kind=task_slice.task_kind,
                material_roles=material_roles,
                field_ids=field_ids,
            )
        )
    plan_payload = {
        "contract_set_sha256": exact.contract_set_sha256,
        "task_slices": tuple(item.model_dump(mode="python") for item in filtered_slices),
        "deferred_unknown_field_ids": tuple(item.field_id for item in deferred),
        "batch_budget": base.batch_budget.model_dump(mode="python"),
    }
    try:
        projected_plan = Schema67ExecutionPlanV1(
            contract_set_sha256=exact.contract_set_sha256,
            task_slices=tuple(filtered_slices),
            deferred_unknown_field_ids=tuple(item.field_id for item in deferred),
            batch_budget=base.batch_budget,
            execution_plan_sha256=canonical_hash(
                _EXECUTION_PLAN_OBJECT_TYPE,
                plan_payload,
            ),
        )
    except ValueError:
        raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID") from None
    provisional = Schema67NativePdfExecutionProjection815V1(
        contract="schema67-native-pdf-execution-projection.815.v1",
        available_source_roles=available_source_roles,
        execution_plan=projected_plan,
        provider_visible_field_ids=provider_visible,
        code_deferred=deferred,
        projection_sha256="",
    )
    return replace(
        provisional,
        projection_sha256=provisional.recomputed_projection_sha256(),
    )


def _require_schema67_execution_plan_mode_815(
    *,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    available_source_roles: tuple[MaterialRole, ...],
) -> Literal["LEGACY_FULL", "NATIVE_PDF_SOURCE_EXTRACT"]:
    legacy = build_schema67_execution_plan(field_contracts)
    if execution_plan == legacy:
        return "LEGACY_FULL"
    native = build_schema67_native_pdf_execution_projection_815(
        field_contracts=field_contracts,
        base_execution_plan=legacy,
        available_source_roles=available_source_roles,
    )
    if execution_plan == native.execution_plan:
        return "NATIVE_PDF_SOURCE_EXTRACT"
    raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID")


def prepare_schema67_deepseek_tasks(
    *,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    role_inputs: Sequence[Schema67RoleTaskInputV1],
) -> tuple[Schema67PreparedTaskV1, ...]:
    """Map Lane A role subsets into exact 054 task/attempt identities, provider-free."""

    try:
        exact_set = FieldContractSetV1.model_validate(
            field_contracts.model_dump(mode="python", round_trip=True)
        )
    except (AttributeError, TypeError, ValueError):
        raise DeepSeekCompilerError("SCHEMA67_CONTRACT_SET_INVALID") from None
    try:
        plan = Schema67ExecutionPlanV1.model_validate(
            execution_plan.model_dump(mode="python", round_trip=True)
        )
    except (AttributeError, TypeError, ValueError):
        raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID") from None
    if (
        exact_set.workbook_sha256 != APPROVED_WORKBOOK_SHA256
        or exact_set.workbook_sha256 != SCHEMA67_WORKBOOK_SHA256
        or exact_set.approved_by != APPROVED_BY
        or exact_set.approved_by != SCHEMA67_APPROVED_BY
        or tuple(item.field_id for item in exact_set.contracts) != APPROVED_ORDERED_FIELD_IDS
        or plan.contract_set_sha256 != exact_set.contract_set_sha256
    ):
        raise DeepSeekCompilerError("SCHEMA67_CONTRACT_SET_INVALID")
    try:
        inputs = tuple(role_inputs)
        supported: tuple[MaterialRole, ...] = ("terms", "brochure", "rate_table")
        available_source_roles = tuple(
            role
            for role in supported
            if any(item.material_role == role for item in inputs)
        )
    except (AttributeError, TypeError, ValueError):
        raise DeepSeekCompilerError("SCHEMA67_TASK_AUTHORITY_INVALID") from None
    _require_schema67_execution_plan_mode_815(
        field_contracts=exact_set,
        execution_plan=plan,
        available_source_roles=available_source_roles,
    )
    executable = tuple(field_id for item in plan.task_slices for field_id in item.field_ids)
    deferred = plan.deferred_unknown_field_ids
    ordered = APPROVED_ORDERED_FIELD_IDS
    contract_by_id = {item.field_id: item for item in exact_set.contracts}
    combined = set(executable) | set(deferred)
    if (
        len(plan.task_slices) != plan.batch_budget.max_main_tasks
        or len(executable) != len(set(executable))
        or len(deferred) != len(set(deferred))
        or set(executable).intersection(deferred)
        or combined != set(ordered)
        or tuple(item for item in ordered if item in deferred) != deferred
    ):
        raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID")
    try:
        inputs_by_key: dict[str, list[Schema67RoleTaskInputV1]] = {}
        for item in inputs:
            inputs_by_key.setdefault(item.task_key, []).append(item)
        if set(inputs_by_key) != {item.task_key for item in plan.task_slices}:
            raise ValueError
        prepared: list[Schema67PreparedTaskV1] = []
        for task_slice in plan.task_slices:
            source_inputs = tuple(inputs_by_key[task_slice.task_key])
            if tuple(item.material_role for item in source_inputs) != task_slice.material_roles:
                raise ValueError
            source_tasks: list[ExtractionTaskV1] = []
            source_attempts: list[AttemptRequestV1] = []
            allowed_by_field: dict[str, dict[MaterialRole, tuple[str, ...]]] = {
                field_id: {} for field_id in task_slice.field_ids
            }
            for item in source_inputs:
                applicable = tuple(
                    sorted(
                        field_id
                        for field_id in task_slice.field_ids
                        if item.material_role in contract_by_id[field_id].source_roles
                    )
                )
                profile = ExtractionTaskProfileV1.model_validate(item.task_profile)
                refs = ExtractionInputRefsV1.model_validate(item.input_refs)
                locator_refs = tuple(item.allowed_locator_refs)
                if tuple(field_id for field_id, _ in locator_refs) != applicable:
                    raise ValueError
                for field_id, locator_values in locator_refs:
                    allowed_by_field[field_id][item.material_role] = locator_values
                if (
                    profile.material_profile.material_role != item.material_role
                    or profile.field_authority.field_ids != applicable
                    or profile.attempt_budget.max_fields != len(applicable)
                    or refs.schema_contract.object_type != "schema67-field-contract-set.v1"
                    or refs.schema_contract.artifact_hash != exact_set.contract_set_sha256
                ):
                    raise ValueError
                task = build_extraction_task(
                    space_id=item.space_id,
                    product_version_id=item.product_version_id,
                    source_revision_id=item.source_revision_id,
                    material_role=item.material_role,
                    module_id=item.module_id,
                    risk_partition_id=item.risk_partition_id,
                    field_ids=applicable,
                    input_refs=refs,
                    budget=profile.attempt_budget,
                    task_profile=profile,
                )
                source_tasks.append(task)
                source_attempts.append(build_initial_attempt(task))
            prompts_list: list[DeepSeekFieldPromptInputV1] = []
            for field_id in task_slice.field_ids:
                contract = contract_by_id[field_id]
                prompt_roles = _prompt_source_roles(contract)
                locator_missing = any(
                    not allowed_by_field[field_id].get(role, ()) for role in prompt_roles
                )
                unknown_reason: UnknownReviewReason | None = (
                    "SOURCE_GUIDANCE_ROLE_INTERSECTION_EMPTY"
                    if not prompt_roles
                    else "SOURCE_LOCATOR_UNAVAILABLE"
                    if locator_missing
                    else None
                )
                prompts_list.append(
                    DeepSeekFieldPromptInputV1(
                        contract=contract,
                        prompt_payload_sha256=canonical_hash(
                            _FIELD_PROMPT_OBJECT_TYPE,
                            _field_prompt_payload(contract),
                        ),
                        allowed_locator_refs=tuple(
                            sorted(
                                {
                                    ref
                                    for role in prompt_roles
                                    for ref in allowed_by_field[field_id].get(role, ())
                                }
                            )
                        ),
                        source_locator_refs=tuple(
                            (
                                role,
                                allowed_by_field[field_id].get(role, ()),
                            )
                            for role in prompt_roles
                        ),
                        requires_unknown_review=unknown_reason is not None,
                        unknown_reason_code=unknown_reason,
                    )
                )
            prompts = tuple(prompts_list)
            provider_task_payload = {
                "execution_plan_sha256": plan.execution_plan_sha256,
                "task_slice_sha256": task_slice.task_slice_sha256,
                "source_task_hashes": tuple(item.task_hash for item in source_tasks),
                "locator_selection_policy_sha256": LOCATOR_SELECTION_POLICY_SHA256,
                "field_prompt_authorities": tuple(
                    item.model_dump(mode="python") for item in prompts
                ),
            }
            provider_task_sha256 = canonical_hash(_PROVIDER_TASK_OBJECT_TYPE, provider_task_payload)
            provider_attempt_sha256 = canonical_hash(
                _PROVIDER_ATTEMPT_OBJECT_TYPE,
                {
                    "provider_task_sha256": provider_task_sha256,
                    "source_attempt_hashes": tuple(item.attempt_hash for item in source_attempts),
                },
            )
            prepared.append(
                Schema67PreparedTaskV1(
                    task_key=task_slice.task_key,
                    task_kind=task_slice.task_kind,
                    source_tasks=tuple(source_tasks),
                    initial_attempts=tuple(source_attempts),
                    field_prompts=prompts,
                    provider_task_sha256=provider_task_sha256,
                    provider_attempt_sha256=provider_attempt_sha256,
                    execution_plan_sha256=plan.execution_plan_sha256,
                    task_slice_sha256=task_slice.task_slice_sha256,
                )
            )
    except (AttributeError, TypeError, ValueError):
        raise DeepSeekCompilerError("SCHEMA67_TASK_AUTHORITY_INVALID") from None
    return tuple(prepared)


def _preflight(
    *,
    profile: ModelProfile,
    policy: ProductionModelPolicy,
    port: Schema67EvidenceBindingPort,
    field_contracts: Sequence[DeepSeekFieldPromptInputV1],
    locators: Sequence[CanonicalLocatorInputV1],
) -> tuple[
    tuple[DeepSeekFieldPromptInputV1, ...],
    tuple[CanonicalLocatorInputV1, ...],
]:
    if (
        type(profile) is not ModelProfile
        or profile.provider != DEEPSEEK_PROVIDER
        or profile.protocol != DEEPSEEK_PROTOCOL
        or profile.model != DEEPSEEK_MODEL
        or profile.base_url.rstrip("/") != DEEPSEEK_BASE_URL
        or port.model_identity_sha256 != DEEPSEEK_EXECUTION_IDENTITY_SHA256
    ):
        raise DeepSeekCompilerError("MODEL_AUTHORITY_MISMATCH")
    try:
        if policy.evaluate(DEEPSEEK_MODEL_IDENTITY) != DEEPSEEK_MODEL_IDENTITY:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        raise DeepSeekCompilerError("MODEL_AUTHORITY_MISMATCH") from None
    try:
        exact_contracts = tuple(
            DeepSeekFieldPromptInputV1.model_validate(item.model_dump(mode="python"))
            for item in field_contracts
        )
    except (AttributeError, TypeError, ValueError):
        raise DeepSeekCompilerError("FIELD_CONTRACT_MISMATCH") from None
    try:
        exact_locators = tuple(
            CanonicalLocatorInputV1.model_validate(item.model_dump(mode="python"))
            for item in locators
        )
    except (AttributeError, TypeError, ValueError):
        raise DeepSeekCompilerError("LOCATOR_AUTHORITY_MISMATCH") from None
    if tuple(item.field_id for item in exact_contracts) != port.field_ids:
        raise DeepSeekCompilerError("FIELD_CONTRACT_MISMATCH")
    locator_map = {item.locator_ref: item for item in exact_locators}
    if len(locator_map) != len(exact_locators) or any(
        ref not in locator_map
        for contract in exact_contracts
        for ref in contract.allowed_locator_refs
    ):
        raise DeepSeekCompilerError("LOCATOR_AUTHORITY_MISMATCH")
    try:
        port.validate_locators(exact_locators)
    except Exception:
        raise DeepSeekCompilerError("LOCATOR_AUTHORITY_MISMATCH") from None
    return exact_contracts, exact_locators


def _deterministic_locator_selection(
    *,
    port: Schema67EvidenceBindingPort,
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    locators: tuple[CanonicalLocatorInputV1, ...],
) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], str, str]:
    """Freeze code-owned FieldContract/MinerU locator authority without a model call."""

    ordered_locators = locators
    authority_payload = {
        "task_id": port.task_id,
        "attempt_hash": port.attempt_hash,
        "field_contracts": tuple(
            {
                "field_id": item.field_id,
                "field_contract_sha256": item.contract.field_contract_sha256,
                "prompt_payload_sha256": item.prompt_payload_sha256,
                "source_locator_refs": item.source_locator_refs,
                "requires_unknown_review": item.requires_unknown_review,
                "unknown_reason_code": item.unknown_reason_code,
            }
            for item in contracts
        ),
        "canonical_locators": tuple(
            {
                "ordinal": ordinal,
                "locator_ref": item.locator_ref,
                "locator_kind": item.locator_kind,
                "page_number": item.page_number,
                "parent_refs": item.parent_refs,
                "content_snapshot_sha256": item.content_snapshot_sha256,
            }
            for ordinal, item in enumerate(ordered_locators)
        ),
    }
    authority_sha256 = canonical_hash(
        _LOCATOR_AUTHORITY_OBJECT_TYPE,
        authority_payload,
    )
    selection = tuple((item.field_id, item.allowed_locator_refs) for item in contracts)
    selection_sha256 = canonical_hash(
        _LOCATOR_SELECTION_OBJECT_TYPE,
        {
            "policy_sha256": LOCATOR_SELECTION_POLICY_SHA256,
            "authority_sha256": authority_sha256,
            "selection": selection,
        },
    )
    return selection, authority_sha256, selection_sha256


def _build_locator_slot_authority(
    *,
    port: Schema67EvidenceBindingPort,
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    locators: tuple[CanonicalLocatorInputV1, ...],
) -> _LocatorSlotAuthorityV1:
    """Create one task-global catalog and a complete code-only membership map."""

    locator_by_ref = {item.locator_ref: item for item in locators}
    if len(locator_by_ref) != len(locators):
        raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
    selected_refs = tuple(
        sorted(
            {
                locator_ref
                for contract in contracts
                for _role, refs in contract.source_locator_refs
                for locator_ref in refs
            }
        )
    )
    if any(ref not in locator_by_ref for ref in selected_refs):
        raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
    slot_by_ref = {
        locator_ref: f"slot-{ordinal:04d}"
        for ordinal, locator_ref in enumerate(selected_refs, start=1)
    }
    catalog = tuple(
        _LocatorSlotCatalogEntryV1(
            slot=slot_by_ref[locator_ref],
            locator_kind=locator_by_ref[locator_ref].locator_kind,
            page_number=locator_by_ref[locator_ref].page_number,
            content_snapshot=locator_by_ref[locator_ref].content_snapshot,
            content_snapshot_sha256=locator_by_ref[locator_ref].content_snapshot_sha256,
        )
        for locator_ref in selected_refs
    )
    field_rows: list[_FieldLocatorSlotsV1] = []
    mapping: list[tuple[str, MaterialRole, str, str]] = []
    for contract in contracts:
        sources: list[_FieldRoleSlotsV1] = []
        for source_role, refs in contract.source_locator_refs:
            slots = tuple(slot_by_ref[ref] for ref in refs)
            if not slots:
                continue
            sources.append(_FieldRoleSlotsV1(source_role=source_role, allowed_slots=slots))
            mapping.extend((contract.field_id, source_role, slot_by_ref[ref], ref) for ref in refs)
        if not sources and not contract.requires_unknown_review:
            raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
        field_rows.append(_FieldLocatorSlotsV1(field_id=contract.field_id, sources=tuple(sources)))
    authority_payload = {
        "task_id": port.task_id,
        "attempt_hash": port.attempt_hash,
        "policy_sha256": LOCATOR_SLOT_POLICY_SHA256,
        "catalog": tuple(item.model_dump(mode="python") for item in catalog),
        "field_locator_slots": tuple(item.model_dump(mode="python") for item in field_rows),
        "code_mapping": tuple(mapping),
    }
    authority = _LocatorSlotAuthorityV1(
        task_id=port.task_id,
        attempt_hash=port.attempt_hash,
        catalog=catalog,
        field_locator_slots=tuple(field_rows),
        code_mapping=tuple(mapping),
        authority_sha256=canonical_hash(_LOCATOR_SLOT_AUTHORITY_OBJECT_TYPE, authority_payload),
    )
    _validate_locator_slot_authority(
        authority=authority,
        port=port,
        contracts=contracts,
        locators=locators,
    )
    return authority


def _validate_locator_slot_authority(
    *,
    authority: _LocatorSlotAuthorityV1,
    port: Schema67EvidenceBindingPort,
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    locators: tuple[CanonicalLocatorInputV1, ...],
) -> None:
    """Fail before transport if slot order, collision, membership, or hash drifts."""

    slots = tuple(item.slot for item in authority.catalog)
    if (
        authority.task_id != port.task_id
        or authority.attempt_hash != port.attempt_hash
        or len(slots) != len(set(slots))
        or slots != tuple(f"slot-{index:04d}" for index in range(1, len(slots) + 1))
        or tuple(item.field_id for item in authority.field_locator_slots)
        != tuple(item.field_id for item in contracts)
    ):
        raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
    locator_by_ref = {item.locator_ref: item for item in locators}
    catalog_by_slot = {item.slot: item for item in authority.catalog}
    if len(locator_by_ref) != len(locators) or len(catalog_by_slot) != len(authority.catalog):
        raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
    selected_refs = tuple(
        sorted(
            {
                locator_ref
                for contract in contracts
                for _role, refs in contract.source_locator_refs
                for locator_ref in refs
            }
        )
    )
    if any(ref not in locator_by_ref for ref in selected_refs):
        raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
    canonical_slot_by_ref = {
        locator_ref: f"slot-{ordinal:04d}"
        for ordinal, locator_ref in enumerate(selected_refs, start=1)
    }
    expected_catalog = tuple(
        _LocatorSlotCatalogEntryV1(
            slot=canonical_slot_by_ref[locator_ref],
            locator_kind=locator_by_ref[locator_ref].locator_kind,
            page_number=locator_by_ref[locator_ref].page_number,
            content_snapshot=locator_by_ref[locator_ref].content_snapshot,
            content_snapshot_sha256=locator_by_ref[locator_ref].content_snapshot_sha256,
        )
        for locator_ref in selected_refs
    )
    expected_rows: list[_FieldLocatorSlotsV1] = []
    canonical_mapping: list[tuple[str, MaterialRole, str, str]] = []
    for contract in contracts:
        expected_sources = tuple(
            _FieldRoleSlotsV1(
                source_role=role,
                allowed_slots=tuple(canonical_slot_by_ref[ref] for ref in refs),
            )
            for role, refs in contract.source_locator_refs
            if refs
        )
        if not expected_sources and not contract.requires_unknown_review:
            raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
        expected_rows.append(
            _FieldLocatorSlotsV1(
                field_id=contract.field_id,
                sources=expected_sources,
            )
        )
        canonical_mapping.extend(
            (contract.field_id, role, canonical_slot_by_ref[ref], ref)
            for role, refs in contract.source_locator_refs
            for ref in refs
        )
    if (
        authority.catalog != expected_catalog
        or authority.field_locator_slots != tuple(expected_rows)
        or authority.code_mapping != tuple(canonical_mapping)
    ):
        raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
    expected_mapping: list[tuple[str, MaterialRole, str, str]] = []
    for contract, field_row in zip(contracts, authority.field_locator_slots, strict=True):
        expected_roles = tuple(role for role, refs in contract.source_locator_refs if refs)
        if tuple(item.source_role for item in field_row.sources) != expected_roles:
            raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
        for (role, refs), source_row in zip(
            ((role, refs) for role, refs in contract.source_locator_refs if refs),
            field_row.sources,
            strict=True,
        ):
            if len(refs) != len(source_row.allowed_slots):
                raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
            for ref, slot in zip(refs, source_row.allowed_slots, strict=True):
                item = locator_by_ref.get(ref)
                catalog_item = catalog_by_slot.get(slot)
                if (
                    item is None
                    or catalog_item is None
                    or not (
                        catalog_item.locator_kind == item.locator_kind
                        and catalog_item.page_number == item.page_number
                        and catalog_item.content_snapshot == item.content_snapshot
                        and catalog_item.content_snapshot_sha256 == item.content_snapshot_sha256
                    )
                ):
                    raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
                expected_mapping.append((contract.field_id, role, slot, ref))
    if authority.code_mapping != tuple(expected_mapping):
        raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
    authority_payload = {
        "task_id": authority.task_id,
        "attempt_hash": authority.attempt_hash,
        "policy_sha256": LOCATOR_SLOT_POLICY_SHA256,
        "catalog": tuple(item.model_dump(mode="python") for item in authority.catalog),
        "field_locator_slots": tuple(
            item.model_dump(mode="python") for item in authority.field_locator_slots
        ),
        "code_mapping": authority.code_mapping,
    }
    if authority.authority_sha256 != canonical_hash(
        _LOCATOR_SLOT_AUTHORITY_OBJECT_TYPE, authority_payload
    ):
        raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")


async def _call_json(
    *,
    transport: ModelClient,
    system: str,
    user: str,
    budget: _Budget,
    batch_budget: Schema67BatchBudgetV1,
    stage: Literal["extractor", "repair"],
    allow_retry: bool = True,
) -> tuple[str, object]:
    while True:
        if budget.calls >= 3:
            raise DeepSeekCompilerError("MODEL_CALL_BUDGET_EXHAUSTED")
        budget.calls += 1
        if stage == "extractor":
            budget.extractor_calls += 1
        else:
            budget.repair_calls += 1
        batch_budget.record_call(stage)
        try:
            output = await transport.complete(system, user)
        except TruncatedOutputError:
            output = ""
        except Exception:
            raise DeepSeekCompilerError("MODEL_TRANSPORT_FAILED") from None
        retryable = not output.strip()
        parsed: object | None = None
        if not retryable:
            try:
                parsed = json.loads(output)
            except json.JSONDecodeError:
                retryable = True
        if not retryable:
            return output, parsed
        if not allow_retry:
            immediate_reason_code: ResponseDecodeFailureCode = (
                "MODEL_CONTENT_EMPTY" if not output.strip() else "MODEL_JSON_INVALID"
            )
            raise _ModelResponseDecodeFailure(immediate_reason_code, _sha256_text(output))
        if budget.retries == 1:
            reason_code: ResponseDecodeFailureCode = (
                "MODEL_CONTENT_EMPTY" if not output.strip() else "MODEL_JSON_INVALID"
            )
            raise _ModelResponseDecodeFailure(reason_code, _sha256_text(output))
        batch_budget.claim_retry()
        budget.retries = 1


def _require_extractor_envelope(
    payload: object,
    *,
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    slot_authority: _LocatorSlotAuthorityV1,
    task_key: str | None = None,
) -> tuple[_ExtractorFieldSelectionV1, ...]:
    required_top_level_keys = {"fields"} if task_key is None else {"task_key", "fields"}
    if type(payload) is not dict or set(payload) != required_top_level_keys:
        raise DeepSeekCompilerError("EXTRACTOR_TOP_LEVEL_SHAPE_INVALID")
    if task_key is not None and payload["task_key"] != task_key:
        raise DeepSeekCompilerError("EXTRACTOR_TOP_LEVEL_SHAPE_INVALID")
    raw_fields = payload["fields"]
    if type(raw_fields) is not list:
        raise DeepSeekCompilerError("EXTRACTOR_TOP_LEVEL_SHAPE_INVALID")
    if len(raw_fields) != len(contracts):
        raise DeepSeekCompilerError("EXTRACTOR_FIELD_COUNT_OR_SET_INVALID")
    required_field_keys = {"field_id", "state", "value_snapshot", "evidence"}
    required_evidence_keys = {"source_role", "locator_slot", "quote_snapshot"}
    slot_mapping = {
        (field_id, source_role, slot): locator_ref
        for field_id, source_role, slot, locator_ref in slot_authority.code_mapping
    }
    field_ids: list[str] = []
    failed_field_ids: set[str] = set()
    duplicate_locator_field_ids: set[str] = set()
    normalized_fields: list[dict[str, object]] = []
    for raw_field in raw_fields:
        if type(raw_field) is not dict or set(raw_field) != required_field_keys:
            raise DeepSeekCompilerError("EXTRACTOR_FIELD_ITEM_SHAPE_INVALID")
        field_id = raw_field["field_id"]
        if not _is_extractor_string(field_id):
            raise DeepSeekCompilerError("EXTRACTOR_STRING_CONSTRAINT_INVALID")
        field_ids.append(field_id)
        state = raw_field["state"]
        if state not in {"present", "absent_explicitly", "unknown"}:
            raise DeepSeekCompilerError("EXTRACTOR_FIELD_ITEM_SHAPE_INVALID")
        contract = contracts[len(field_ids) - 1]
        if contract.requires_unknown_review and state != "unknown":
            raise DeepSeekCompilerError("EXTRACTOR_FORCED_UNKNOWN_INVALID")
        raw_evidence = raw_field["evidence"]
        if type(raw_evidence) is not list:
            raise DeepSeekCompilerError("EXTRACTOR_FIELD_ITEM_SHAPE_INVALID")
        if state == "unknown":
            if raw_field["value_snapshot"] is not None or raw_evidence:
                raise DeepSeekCompilerError("EXTRACTOR_FIELD_ITEM_SHAPE_INVALID")
            normalized_fields.append(dict(raw_field))
            continue
        if not _is_extractor_string(raw_field["value_snapshot"]):
            raise DeepSeekCompilerError("EXTRACTOR_STRING_CONSTRAINT_INVALID")
        if not raw_evidence:
            raise DeepSeekCompilerError("EXTRACTOR_FIELD_ITEM_SHAPE_INVALID")
        evidence_keys: list[tuple[str, str, str]] = []
        normalized_evidence: list[dict[str, str]] = []
        for raw_item in raw_evidence:
            if type(raw_item) is not dict or set(raw_item) != required_evidence_keys:
                raise DeepSeekCompilerError("EXTRACTOR_FIELD_ITEM_SHAPE_INVALID")
            source_role = raw_item["source_role"]
            locator_slot = raw_item["locator_slot"]
            quote_snapshot = raw_item["quote_snapshot"]
            if (
                not _is_extractor_string(source_role)
                or not _is_extractor_string(locator_slot)
                or not _is_extractor_string(quote_snapshot)
            ):
                raise DeepSeekCompilerError("EXTRACTOR_STRING_CONSTRAINT_INVALID")
            locator_ref = slot_mapping.get((field_id, source_role, locator_slot))
            if locator_ref is None:
                failed_field_ids.add(field_id)
                continue
            evidence_keys.append((source_role, locator_slot, quote_snapshot))
            normalized_evidence.append(
                {"locator_ref": locator_ref, "quote_snapshot": quote_snapshot}
            )
        normalized_locator_refs = tuple(item["locator_ref"] for item in normalized_evidence)
        if len(normalized_locator_refs) != len(set(normalized_locator_refs)):
            duplicate_locator_field_ids.add(field_id)
        if len(evidence_keys) != len(set(evidence_keys)):
            raise DeepSeekCompilerError("EXTRACTOR_FIELD_ITEM_SHAPE_INVALID")
        required_roles = {role for role, refs in contract.source_locator_refs if refs}
        if {item[0] for item in evidence_keys} != required_roles:
            failed_field_ids.add(field_id)
        normalized_fields.append(
            {
                "field_id": field_id,
                "state": state,
                "value_snapshot": raw_field["value_snapshot"],
                "evidence": normalized_evidence,
            }
        )
    expected_field_ids = tuple(item.field_id for item in contracts)
    if len(field_ids) != len(set(field_ids)) or set(field_ids) != set(expected_field_ids):
        raise DeepSeekCompilerError("EXTRACTOR_FIELD_COUNT_OR_SET_INVALID")
    if tuple(field_ids) != expected_field_ids:
        raise DeepSeekCompilerError("EXTRACTOR_FIELD_ORDER_INVALID")
    if failed_field_ids:
        raise _LocatorMembershipFailure(
            tuple(field_id for field_id in expected_field_ids if field_id in failed_field_ids),
            duplicate_locator_field_ids=tuple(
                field_id
                for field_id in expected_field_ids
                if field_id in duplicate_locator_field_ids
            ),
        )
    try:
        outputs = tuple(
            _ExtractorFieldSelectionV1.model_validate(item) for item in normalized_fields
        )
    except (TypeError, ValueError, ValidationError):
        raise DeepSeekCompilerError("EXTRACTOR_FIELD_ITEM_SHAPE_INVALID") from None
    if any(
        output.state != "unknown"
        for contract, output in zip(contracts, outputs, strict=True)
        if contract.requires_unknown_review
    ):
        raise DeepSeekCompilerError("EXTRACTOR_FORCED_UNKNOWN_INVALID")
    return outputs


def _is_extractor_string(value: object) -> bool:
    return (
        type(value) is str
        and _EXTRACTOR_STRING_CONSTRAINT.min_length
        <= len(value)
        <= _EXTRACTOR_STRING_CONSTRAINT.max_length
        and re.fullmatch(_EXTRACTOR_STRING_CONSTRAINT.pattern, value) is not None
    )


def _failed_locator_membership_field_ids(
    *,
    selections: tuple[_ExtractorFieldSelectionV1, ...],
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    locators: tuple[CanonicalLocatorInputV1, ...],
) -> tuple[str, ...]:
    """Return only contract-ordered field IDs whose selected refs lack authority."""

    locator_refs = {item.locator_ref for item in locators}
    if len(locator_refs) != len(locators):
        raise DeepSeekCompilerError("LOCATOR_AUTHORITY_MISMATCH")
    failed: set[str] = set()
    for selection, contract in zip(selections, contracts, strict=True):
        allowed = {
            locator_ref for _role, refs in contract.source_locator_refs for locator_ref in refs
        }
        if any(
            item.locator_ref not in allowed or item.locator_ref not in locator_refs
            for item in selection.evidence
        ):
            failed.add(contract.field_id)
    return tuple(contract.field_id for contract in contracts if contract.field_id in failed)


def _hydrate_from_code_owned_authority(
    *,
    selections: tuple[_ExtractorFieldSelectionV1, ...],
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    locators: tuple[CanonicalLocatorInputV1, ...],
    sources_by_role: dict[MaterialRole, AdmittedParseArtifactV1],
) -> tuple[FreeformFieldOutputV1, ...]:
    """Replace model locator choices with exact parser/source custody."""

    if tuple(item.field_id for item in selections) != tuple(item.field_id for item in contracts):
        raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
    failed_field_ids = _failed_locator_membership_field_ids(
        selections=selections,
        contracts=contracts,
        locators=locators,
    )
    if failed_field_ids:
        raise _LocatorMembershipFailure(failed_field_ids)
    locator_by_ref = {item.locator_ref: item for item in locators}
    if len(locator_by_ref) != len(locators):
        raise DeepSeekCompilerError("LOCATOR_AUTHORITY_MISMATCH")
    outputs: list[FreeformFieldOutputV1] = []
    for selection, contract in zip(selections, contracts, strict=True):
        if selection.state == "unknown":
            outputs.append(
                FreeformFieldOutputV1(
                    product_version_id="596-1",
                    field_id=selection.field_id,
                    state="unknown",
                    value_snapshot=None,
                    evidence=(),
                )
            )
            continue
        hydrated: list[FreeformEvidenceV1] = []
        for selected in selection.evidence:
            role_matches = tuple(
                role for role, refs in contract.source_locator_refs if selected.locator_ref in refs
            )
            locator = locator_by_ref.get(selected.locator_ref)
            if len(role_matches) > 1:
                raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
            if not role_matches or locator is None:
                raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
            source = sources_by_role.get(role_matches[0])
            if source is None:
                raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
            document = source.document
            manifest = source.manifest
            fact = evidence_verifier._locator_fact(document, selected.locator_ref)
            if fact is None:
                raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
            kind, page_number, parent_refs, content_hash = fact
            if not (
                kind == locator.locator_kind
                and page_number == locator.page_number
                and parent_refs == locator.parent_refs
                and evidence_verifier._content_snapshot_matches(
                    document=document,
                    kind=kind,
                    content_snapshot=locator.content_snapshot,
                    content_snapshot_sha256=locator.content_snapshot_sha256,
                    parsed_content_hash=content_hash,
                )
            ):
                raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
            table_id: str | None = None
            cell_id: str | None = None
            row_index: int | None = None
            column_index: int | None = None
            row_span: int | None = None
            column_span: int | None = None
            if kind == "table":
                table_id = selected.locator_ref
            elif kind == "cell":
                cell = next(
                    (item for item in document.cells if item.cell_id == selected.locator_ref),
                    None,
                )
                if cell is None:
                    raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
                table_id = cell.table_id
                cell_id = cell.cell_id
                row_index = cell.locator.row_index
                column_index = cell.locator.column_index
                row_span = cell.locator.row_span
                column_span = cell.locator.column_span
            hydrated.append(
                FreeformEvidenceV1(
                    field_id=selection.field_id,
                    source_sha256=document.subject.source_sha256,
                    source_revision_id=document.subject.source_revision_id,
                    parse_attempt_id=document.attempt.attempt_id,
                    parsed_document_hash=document.document_hash,
                    parse_manifest_hash=manifest.manifest_hash,
                    page_number=page_number,
                    block_id=selected.locator_ref if kind == "block" else None,
                    table_id=table_id,
                    cell_id=cell_id,
                    row_index=row_index,
                    column_index=column_index,
                    row_span=row_span,
                    column_span=column_span,
                    locator=evidence_verifier.EvidenceLocatorSnapshotV1(
                        subject_type=kind,
                        subject_ref=selected.locator_ref,
                        page_number=page_number,
                        parent_refs=parent_refs,
                        content_snapshot=locator.content_snapshot,
                        content_snapshot_sha256=locator.content_snapshot_sha256,
                    ),
                    quote_snapshot=selected.quote_snapshot,
                    quote_snapshot_sha256=_sha256_text(selected.quote_snapshot),
                )
            )
        hydrated.sort(key=evidence_verifier._freeform_evidence_key)
        try:
            outputs.append(
                FreeformFieldOutputV1(
                    product_version_id="596-1",
                    field_id=selection.field_id,
                    state=selection.state,
                    value_snapshot=selection.value_snapshot,
                    evidence=tuple(hydrated),
                )
            )
        except ValueError:
            raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID") from None
    return tuple(outputs)


def _extractor_response_contract(
    *,
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    task_key: str | None = None,
    exact_literal_quotes: bool = False,
    locator_context_name: Literal[
        "field_locator_slots", "field_local_contexts"
    ] = "field_locator_slots",
) -> dict[str, object]:
    field_ids = tuple(item.field_id for item in contracts)
    top_level: dict[str, object] = {
        "required_keys": ("fields",),
        "additional_properties": False,
    }
    response_skeleton: dict[str, object] = {
        "fields": tuple(
            {
                "field_id": field_id,
                "state": "unknown",
                "value_snapshot": None,
                "evidence": (),
            }
            for field_id in field_ids
        )
    }
    if task_key is not None:
        top_level = {
            "required_keys": ("task_key", "fields"),
            "additional_properties": False,
            "task_key": {"type": "string", "const": task_key},
        }
        response_skeleton = {"task_key": task_key, **response_skeleton}
    return {
        "output_contract": "schema67-semantic-field-selection.v2",
        "top_level": top_level,
        "fields": {
            "type": "array",
            "exact_count": len(field_ids),
            "field_order": field_ids,
            "items": {
                "required_keys": (
                    "field_id",
                    "state",
                    "value_snapshot",
                    "evidence",
                ),
                "additional_properties": False,
                "field_id": _EXTRACTOR_STRING_CONSTRAINT.visible_contract(),
                "state_enum": ("present", "absent_explicitly", "unknown"),
                "state_rules": {
                    "unknown": {"value_snapshot": None, "evidence": ()},
                    "present_or_absent_explicitly": {
                        "value_snapshot": (_EXTRACTOR_STRING_CONSTRAINT.visible_contract()),
                        "evidence": "nonempty_unique_array",
                    },
                },
            },
        },
        "evidence": {
            "required_keys": ("source_role", "locator_slot", "quote_snapshot"),
            "additional_properties": False,
            "source_role": {
                "constraint": "exact_member_of_field_source_roles",
                **_EXTRACTOR_STRING_CONSTRAINT.visible_contract(),
            },
            "locator_slot": {
                "constraint": "exact_member_of_field_role_allowed_slots",
                **_EXTRACTOR_STRING_CONSTRAINT.visible_contract(),
            },
            "quote_snapshot": {
                "constraint": (
                    "exact_utf8_literal_substring_of_original_content_snapshot"
                    if exact_literal_quotes
                    else "nonblank_literal_substring_after_exact_057_normalization"
                ),
                **_EXTRACTOR_STRING_CONSTRAINT.visible_contract(),
            },
            "uniqueness": "unique_source_role_locator_slot_quote_snapshot_triples",
        },
        "present_value_057_support": {
            "state": "present",
            "normalization": (
                "none_for_quote_snapshot"
                if exact_literal_quotes
                else "existing_057_nfkc_whitespace_punctuation_case"
            ),
            "value_quote_relation": (
                "value_snapshot_semantically_equivalent_to_exact_quote;"
                "short_values_prefer_source_wording;long_values_may_faithfully_abbreviate_"
                "without_dropping_conditions_exceptions_or_ranges"
            ),
            "required_source_roles": "all_contract_required_roles",
            "locator_authority": f"same_field_{locator_context_name}_only",
            "quote_authority": "literal_replay_not_semantic_paraphrase",
        },
        "forced_unknown_field_ids": tuple(
            item.field_id for item in contracts if item.requires_unknown_review
        ),
        "forced_unknown_reasons": tuple(
            {
                "field_id": item.field_id,
                "reason_code": item.unknown_reason_code,
            }
            for item in contracts
            if item.requires_unknown_review
        ),
        "response_skeleton": response_skeleton,
        "response_skeleton_usage": (
            "copy_every_row_exactly_once_in_order; skeleton_is_shape_only; "
            "replace_state_value_and_evidence_only_when_selected_locator_text_supports_it"
        ),
    }


def _extractor_system_prompt(
    *,
    task_key_required: bool,
    exact_literal_quotes: bool,
    locator_context_name: Literal[
        "field_locator_slots", "field_local_contexts"
    ] = "field_locator_slots",
) -> str:
    return (
        "DeepSeek Extractor: return only the JSON object shaped by "
        "response_contract.response_skeleton, without Markdown, explanation, or metadata. "
        + (
            "Copy top-level task_key exactly from the request into the response. "
            if task_key_required
            else ""
        )
        + "Copy every field row exactly once in response_contract.fields.field_order and "
        "always include field_id, state, value_snapshot, and evidence. Use state unknown "
        "with value_snapshot null and evidence [] when the selected locator text does not "
        "support a value, or when field_id is forced unknown. For present or "
        "absent_explicitly, provide a nonblank value_snapshot and at least one unique "
        "Evidence item for every required source role; each locator_slot must appear "
        "under that exact field and source_role in "
        f"{locator_context_name}. The field_id, "
        "value_snapshot, source_role, locator_slot, and quote_snapshot strings must each "
        "be a single line between "
        f"{_EXTRACTOR_STRING_CONSTRAINT.min_length} and "
        f"{_EXTRACTOR_STRING_CONSTRAINT.max_length} characters, must not contain CR or "
        "LF, and must not have leading or trailing whitespace. "
        "Each quote_snapshot must be a "
        + (
            "byte-for-byte literal substring of that slot's original catalog "
            "content_snapshot, preserving whitespace, punctuation, case, and footnote "
            "markers, never a normalized or semantic paraphrase. "
            if exact_literal_quotes
            else "nonblank literal substring of that slot's catalog content_snapshot after "
            "exact 057 normalization (NFKC, whitespace, listed punctuation, and case only), "
            "never a semantic paraphrase. "
        )
        + "For state present, value_snapshot must preserve the "
        "same meaning and all material conditions supported by the exact quote_snapshot; "
        "prefer the source wording for short values, while a long value may be faithfully "
        "abbreviated without dropping a condition. When repair_kind is "
        "response_contract, regenerate the whole "
        "object from the unchanged authority and correct the fixed reason_code without "
        "requesting or reconstructing the prior response. Never invent locator authority "
        "or add keys."
    )


@dataclass(frozen=True, slots=True)
class _PreparedExtractorRequest:
    contracts: tuple[DeepSeekFieldPromptInputV1, ...] = field(repr=False)
    locators: tuple[CanonicalLocatorInputV1, ...] = field(repr=False)
    contract_payload: tuple[dict[str, object], ...] = field(repr=False)
    slot_authority: _LocatorSlotAuthorityV1 = field(repr=False)
    locator_authority_sha256: str
    locator_selection_sha256: str
    payload: dict[str, object] = field(repr=False)
    system: str = field(repr=False)
    user: str = field(repr=False)
    request_sha256: str


def _prepare_extractor_request(
    *,
    profile: ModelProfile,
    policy: ProductionModelPolicy,
    port: Schema67EvidenceBindingPort,
    field_contracts: Sequence[DeepSeekFieldPromptInputV1],
    locators: Sequence[CanonicalLocatorInputV1],
    task_key: str | None,
    exact_literal_quotes: bool,
) -> _PreparedExtractorRequest:
    contracts, exact_locators = _preflight(
        profile=profile,
        policy=policy,
        port=port,
        field_contracts=field_contracts,
        locators=locators,
    )
    if task_key is not None and not _is_extractor_string(task_key):
        raise DeepSeekCompilerError("BATCH_EXECUTION_IDENTITY_INVALID")
    contract_payload = tuple(_request_field_contract_payload(item) for item in contracts)
    _selection, locator_authority_sha256, locator_selection_sha256 = (
        _deterministic_locator_selection(
            port=port,
            contracts=contracts,
            locators=exact_locators,
        )
    )
    slot_authority = _build_locator_slot_authority(
        port=port,
        contracts=contracts,
        locators=exact_locators,
    )
    _validate_locator_slot_authority(
        authority=slot_authority,
        port=port,
        contracts=contracts,
        locators=exact_locators,
    )
    extractor_payload: dict[str, object] = {
        "task_id": port.task_id,
        "attempt_hash": port.attempt_hash,
        "arm_blueprint_hash": port.arm_blueprint_hash,
        "model_identity_sha256": port.model_identity_sha256,
        "normalizer_identity_sha256": port.normalizer_identity_sha256,
        "schema_rows_sha256": APPROVED_SCHEMA_ROWS_SHA256,
        "field_contracts": contract_payload,
        "locator_selection_policy_sha256": LOCATOR_SELECTION_POLICY_SHA256,
        "locator_authority_sha256": locator_authority_sha256,
        "locator_selection_sha256": locator_selection_sha256,
        **slot_authority.model_payload(),
        "response_contract_repair_policy_sha256": (
            _RESPONSE_CONTRACT_REPAIR_POLICY_SHA256
        ),
        "response_contract": _extractor_response_contract(
            contracts=contracts,
            task_key=task_key,
            exact_literal_quotes=exact_literal_quotes,
        ),
    }
    if task_key is not None:
        extractor_payload = {"task_key": task_key, **extractor_payload}
    extractor_user = _canonical_bytes(extractor_payload).decode("utf-8")
    extractor_system = _extractor_system_prompt(
        task_key_required=task_key is not None,
        exact_literal_quotes=exact_literal_quotes,
    )
    _require_request_size(system=extractor_system, user=extractor_user)
    return _PreparedExtractorRequest(
        contracts=contracts,
        locators=exact_locators,
        contract_payload=contract_payload,
        slot_authority=slot_authority,
        locator_authority_sha256=locator_authority_sha256,
        locator_selection_sha256=locator_selection_sha256,
        payload=extractor_payload,
        system=extractor_system,
        user=extractor_user,
        request_sha256=_request_sha256(
            system=extractor_system,
            user=extractor_user,
        ),
    )


def _prepare_native_selection_authority_815(
    *,
    profile: ModelProfile,
    policy: ProductionModelPolicy,
    port: Schema67EvidenceBindingPort,
    field_contracts: Sequence[DeepSeekFieldPromptInputV1],
    locators: Sequence[CanonicalLocatorInputV1],
    task_key: str,
) -> _PreparedExtractorRequest:
    """Prepare internal locator identity without rendering the legacy request body."""

    contracts, exact_locators = _preflight(
        profile=profile,
        policy=policy,
        port=port,
        field_contracts=field_contracts,
        locators=locators,
    )
    if not _is_extractor_string(task_key):
        raise DeepSeekCompilerError("BATCH_EXECUTION_IDENTITY_INVALID")
    contract_payload = tuple(_request_field_contract_payload(item) for item in contracts)
    _selection, locator_authority_sha256, locator_selection_sha256 = (
        _deterministic_locator_selection(
            port=port,
            contracts=contracts,
            locators=exact_locators,
        )
    )
    slot_authority = _build_locator_slot_authority(
        port=port,
        contracts=contracts,
        locators=exact_locators,
    )
    _validate_locator_slot_authority(
        authority=slot_authority,
        port=port,
        contracts=contracts,
        locators=exact_locators,
    )
    return _PreparedExtractorRequest(
        contracts=contracts,
        locators=exact_locators,
        contract_payload=contract_payload,
        slot_authority=slot_authority,
        locator_authority_sha256=locator_authority_sha256,
        locator_selection_sha256=locator_selection_sha256,
        payload={
            "task_key": task_key,
            "task_id": port.task_id,
            "attempt_hash": port.attempt_hash,
        },
        system="",
        user="",
        request_sha256="",
    )


def _prepare_native_selection_request_815(
    *,
    prepared_request: _PreparedExtractorRequest,
    task_key: str,
    field_catalogs: tuple[FieldSelectionCatalog815V1, ...],
) -> tuple[str, str, str]:
    if (
        tuple(item.field_id for item in field_catalogs)
        != tuple(item.field_id for item in prepared_request.contracts)
        or any(
            item.catalog_sha256 != item.recomputed_catalog_sha256()
            for item in field_catalogs
        )
    ):
        raise DeepSeekCompilerError("SCHEMA67_SELECTION_AUTHORITY_INVALID")
    payload = {
        "task_key": task_key,
        "task_id": prepared_request.payload["task_id"],
        "attempt_hash": prepared_request.payload["attempt_hash"],
        "schema_rows_sha256": APPROVED_SCHEMA_ROWS_SHA256,
        "field_contracts": prepared_request.contract_payload,
        "field_selection_catalogs": tuple(
            {
                "field_id": item.field_id,
                "allowed_source_roles": item.allowed_source_roles,
                "retrieval_policy_sha256": item.retrieval_policy_sha256,
                "catalog_sha256": item.catalog_sha256,
                "selections": tuple(
                    _selection_prompt_payload_815(selection)
                    for selection in item.selections
                ),
            }
            for item in field_catalogs
        ),
        "response_contract": {
            "contract": "schema67-native-pdf-selection-response.815.v1",
            "top_level_keys": ("task_key", "fields"),
            "field_keys": (
                "field_id",
                "state",
                "selection_ids",
                "value_part_ids",
                "typed_reason",
            ),
            "field_order": tuple(item.field_id for item in field_catalogs),
            "fields_container": {
                "json_type": "array",
                "ordering": "field_order",
                "object_or_map": "forbidden",
            },
            "state_enum": ("present", "absent_explicitly", "unknown"),
            "state_rules": {
                "present": {
                    "selection_ids": "nonempty_code_issued",
                    "value_part_ids": "policy_scoped_code_issued_or_empty",
                    "typed_reason": None,
                },
                "absent_explicitly": {
                    "selection_ids": "nonempty_code_issued",
                    "value_part_ids": "policy_scoped_code_issued_or_empty",
                    "typed_reason": None,
                },
                "unknown": {
                    "selection_ids": (),
                    "value_part_ids": (),
                    "typed_reason": "ANSWER_NOT_FOUND",
                },
            },
            "display_policy_rules": {
                "EXACT_SHORT": (
                    "empty_only_for_single_atomic_group_otherwise_"
                    "ordered_group_owned_value_part_ids"
                ),
                "EXTRACTIVE_LONG": (
                    "ordered_group_owned_value_part_ids_or_empty_full_group_value"
                ),
            },
            "forbidden_model_content": (
                "value_snapshot",
                "quote_snapshot",
                "bbox",
                "offset",
            ),
        },
    }
    system = (
        "Return exactly one compact UTF-8 JSON object with the exact task_key and "
        "fields as an ordered JSON array, never an object or map. Each field state "
        "must be exactly present, absent_explicitly, or unknown; never known. For "
        "present or absent_explicitly, return nonempty code-issued selection_ids and "
        "typed_reason null. EXACT_SHORT permits value_part_ids [] only for one atomic "
        "part; multi-part EXACT_SHORT groups require ordered code-issued value_part_ids. "
        "EXTRACTIVE_LONG permits only ordered code-issued value_part_ids owned by "
        "selected groups, or [] for the complete group. For unknown, return "
        "selection_ids [], value_part_ids [], and typed_reason ANSWER_NOT_FOUND. Select "
        "only code-issued IDs from each "
        "field-local catalog. Do not return source text, values, quotes, coordinates, "
        "Markdown, prefixes, or suffixes."
    )
    user = _canonical_bytes(payload).decode("utf-8")
    _require_request_size(system=system, user=user)
    return system, user, _request_sha256(system=system, user=user)


def _task_native_selection_catalog_815(
    *,
    prompt: DeepSeekFieldPromptInputV1,
    catalog: FieldSelectionCatalog815V1,
) -> FieldSelectionCatalog815V1:
    roles = tuple(role for role, _refs in prompt.source_locator_refs)
    if catalog.field_id != prompt.field_id or not set(roles).issubset(
        catalog.allowed_source_roles
    ):
        raise DeepSeekCompilerError("SCHEMA67_SELECTION_AUTHORITY_INVALID")
    provisional = replace(
        catalog,
        allowed_source_roles=roles,
        selections=tuple(
            item for item in catalog.selections if item.source_role in roles
        ),
        catalog_sha256="",
    )
    return replace(
        provisional,
        catalog_sha256=provisional.recomputed_catalog_sha256(),
    )


async def _run_native_selection_task_815(
    *,
    transport: ModelClient,
    port: _Schema67EvidenceBindingPort,
    prepared_request: _PreparedExtractorRequest,
    field_catalogs: tuple[FieldSelectionCatalog815V1, ...],
    source_projections: tuple[NativePdfSelectionProjection815V1, ...],
    batch_budget: Schema67BatchBudgetV1,
    execution_plan_sha256: str | None,
    task_slice_sha256: str | None,
    task_key: str,
) -> DeepSeekTaskExecutionV1:
    system, user, request_sha256 = _prepare_native_selection_request_815(
        prepared_request=prepared_request,
        task_key=task_key,
        field_catalogs=field_catalogs,
    )
    budget = _Budget()
    batch_budget.start_task()
    try:
        _response_text, response_json = await _call_json(
            transport=transport,
            system=system,
            user=user,
            budget=budget,
            batch_budget=batch_budget,
            stage="extractor",
            allow_retry=False,
        )
        response = require_model_selection_response_815(
            response_json,
            task_key=task_key,
            field_catalogs=field_catalogs,
        )
        outputs, _coordinates, _reasons = hydrate_model_selection_response_815(
            response=response,
            field_catalogs=field_catalogs,
            source_projections=source_projections,
            admitted_sources=port.admitted_sources,
        )
    except NativePdfSelectionError815 as error:
        raise DeepSeekCompilerError(error.reason_code) from None
    try:
        initial = port.bind_native_selection_outputs(outputs, field_catalogs)
    except Exception:
        raise DeepSeekCompilerError("EVIDENCE_BINDING_FAILED") from None
    if initial.verification_batches:
        final_outputs, receipts, evidence_demotion = _demote_initial_nonpass(
            initial,
            outputs,
        )
    else:
        final_outputs = outputs
        receipts = initial.evidence_receipts
        evidence_demotion = None
    receipt_values: dict[str, object] = {
        "contract": "deepseek-task-execution-receipt.v2",
        "model_identity": DEEPSEEK_MODEL_IDENTITY.model_dump(mode="python"),
        "execution_identity_sha256": DEEPSEEK_EXECUTION_IDENTITY_SHA256,
        "batch_budget_identity_sha256": batch_budget.identity_sha256,
        "execution_plan_sha256": execution_plan_sha256,
        "task_slice_sha256": task_slice_sha256,
        "schema_workbook_sha256": SCHEMA67_WORKBOOK_SHA256,
        "approved_by": SCHEMA67_APPROVED_BY,
        "task_id": port.task_id,
        "attempt_hash": port.attempt_hash,
        "field_ids": tuple(item.field_id for item in prepared_request.contracts),
        "field_contracts_sha256": _sha256_text(
            _canonical_bytes(prepared_request.contract_payload).decode("utf-8")
        ),
        "locator_selection_policy_sha256": LOCATOR_SELECTION_POLICY_SHA256,
        "locator_authority_sha256": prepared_request.locator_authority_sha256,
        "locator_selection_sha256": prepared_request.locator_selection_sha256,
        "locator_slot_policy_sha256": LOCATOR_SLOT_POLICY_SHA256,
        "locator_slot_authority_sha256": prepared_request.slot_authority.authority_sha256,
        "response_contract_repair_policy_sha256": (
            _RESPONSE_CONTRACT_REPAIR_POLICY_SHA256
        ),
        "extractor_request_sha256": request_sha256,
        "response_contract_repair": None,
        "evidence_repair_summary": None,
        "evidence_demotion": evidence_demotion,
        "initial_bound_attempt_hash": initial.bound_attempt_hash,
        "initial_outputs_sha256": _outputs_sha256(outputs),
        "final_outputs_sha256": _outputs_sha256(final_outputs),
        "evidence_receipt_hashes": tuple(item.receipt_hash for item in receipts),
        "locator_calls": budget.locator_calls,
        "extractor_calls": budget.extractor_calls,
        "repair_calls": budget.repair_calls,
        "transport_retries": budget.retries,
        "response_contract_repairs": 0,
        "evidence_repairs": 0,
        "total_calls": budget.calls,
    }
    receipt = DeepSeekExecutionReceiptV1.model_validate(
        {
            **receipt_values,
            "receipt_hash": canonical_hash(_EXECUTION_RECEIPT_OBJECT_TYPE, receipt_values),
        }
    )
    return DeepSeekTaskExecutionV1(
        initial=initial,
        initial_outputs=outputs,
        final_outputs=final_outputs,
        evidence_receipts=receipts,
        response_contract_repair=None,
        evidence_repair=None,
        evidence_demotion=evidence_demotion,
        receipt=receipt,
    )


async def _run_deepseek_task(
    *,
    profile: ModelProfile,
    policy: ProductionModelPolicy,
    transport: ModelClient,
    port: Schema67EvidenceBindingPort,
    field_contracts: Sequence[DeepSeekFieldPromptInputV1],
    locators: Sequence[CanonicalLocatorInputV1],
    batch_budget: Schema67BatchBudgetV1 | None = None,
    execution_plan_sha256: str | None = None,
    task_slice_sha256: str | None = None,
    task_key: str | None = None,
    _single_pass_mvp: bool = False,
    _allow_evidence_repair: bool = False,
    _selection_authority: tuple[
        tuple[FieldSelectionCatalog815V1, ...],
        tuple[NativePdfSelectionProjection815V1, ...],
    ]
    | None = None,
) -> DeepSeekTaskExecutionV1:
    """Execute one pre-admitted task; tests inject a fake transport, never a provider."""

    if _selection_authority is not None:
        if (
            not _single_pass_mvp
            or _allow_evidence_repair
            or task_key is None
            or not isinstance(port, _Schema67EvidenceBindingPort)
        ):
            raise DeepSeekCompilerError("SCHEMA67_SELECTION_AUTHORITY_INVALID")
        prepared_request = _prepare_native_selection_authority_815(
            profile=profile,
            policy=policy,
            port=port,
            field_contracts=field_contracts,
            locators=locators,
            task_key=task_key,
        )
        task_catalogs, source_projections = _selection_authority
        return await _run_native_selection_task_815(
            transport=transport,
            port=port,
            prepared_request=prepared_request,
            field_catalogs=task_catalogs,
            source_projections=source_projections,
            batch_budget=batch_budget or Schema67BatchBudgetV1(),
            execution_plan_sha256=execution_plan_sha256,
            task_slice_sha256=task_slice_sha256,
            task_key=task_key,
        )
    prepared_request = _prepare_extractor_request(
        profile=profile,
        policy=policy,
        port=port,
        field_contracts=field_contracts,
        locators=locators,
        task_key=task_key,
        exact_literal_quotes=_single_pass_mvp,
    )
    contracts = prepared_request.contracts
    exact_locators = prepared_request.locators
    contract_payload = prepared_request.contract_payload
    slot_authority = prepared_request.slot_authority
    locator_authority_sha256 = prepared_request.locator_authority_sha256
    locator_selection_sha256 = prepared_request.locator_selection_sha256
    extractor_payload = prepared_request.payload
    extractor_system = prepared_request.system
    extractor_user = prepared_request.user
    extractor_request_sha = prepared_request.request_sha256
    budget = _Budget()
    exact_batch_budget = batch_budget or Schema67BatchBudgetV1()
    if (execution_plan_sha256 is None) != (task_slice_sha256 is None):
        raise DeepSeekCompilerError("BATCH_EXECUTION_IDENTITY_INVALID")
    exact_batch_budget.start_task()
    initial_text: str | None = None
    response_contract_repair: ResponseContractRepairResolutionV2 | None = None
    evidence_repair: EvidenceRepairTraceV2 | None = None
    response_contract_failure_code: ResponseContractRepairFailureCode | None = None
    response_contract_failed_field_ids: tuple[str, ...] = ()
    invalid_response_sha: str | None = None
    accepted_response_sha: str | None = None
    try:
        initial_text, initial_json = await _call_json(
            transport=transport,
            system=extractor_system,
            user=extractor_user,
            budget=budget,
            batch_budget=exact_batch_budget,
            stage="extractor",
            allow_retry=not _single_pass_mvp,
        )
        initial_selections = _require_extractor_envelope(
            initial_json,
            contracts=contracts,
            slot_authority=slot_authority,
            task_key=task_key,
        )
        initial_outputs = port.hydrate_extractor_outputs(
            selections=initial_selections,
            contracts=contracts,
            locators=exact_locators,
        )
    except DeepSeekCompilerError as error:
        if _single_pass_mvp:
            raise
        if isinstance(error, _ModelResponseDecodeFailure):
            if error.reason_code not in _RESPONSE_DECODE_REPAIRABLE_CODES:
                raise
            response_contract_failure_code = cast(
                ResponseContractRepairFailureCode, error.reason_code
            )
            invalid_response_sha = error.response_sha256
        else:
            if error.reason_code not in _RESPONSE_CONTRACT_REPAIRABLE_CODES:
                raise
            if error.reason_code == "EXTRACTOR_LOCATOR_NOT_ALLOWED_INVALID":
                if not isinstance(error, _LocatorMembershipFailure):
                    raise DeepSeekCompilerError(
                        "EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID"
                    ) from None
                response_contract_failed_field_ids = error.failed_field_ids
            if initial_text is None:
                raise DeepSeekCompilerError(
                    "EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID"
                ) from None
            response_contract_failure_code = _response_failure_code(error.reason_code)
            invalid_response_sha = _sha256_text(initial_text)
        exact_batch_budget.claim_repair("response_contract")
        response_contract_repair_payload = {
            **extractor_payload,
            "repair_kind": "response_contract",
            "repair_number": 1,
            "reason_code": response_contract_failure_code,
            "failed_field_ids": response_contract_failed_field_ids,
            "parent_extractor_request_sha256": extractor_request_sha,
            "invalid_response_sha256": invalid_response_sha,
        }
        response_contract_repair_user = _canonical_bytes(response_contract_repair_payload).decode(
            "utf-8"
        )
        _require_request_size(system=extractor_system, user=response_contract_repair_user)
        repair_text, repair_json = await _call_json(
            transport=transport,
            system=extractor_system,
            user=response_contract_repair_user,
            budget=budget,
            batch_budget=exact_batch_budget,
            stage="repair",
        )
        response_contract_repair_request_sha = _request_sha256(
            system=extractor_system, user=response_contract_repair_user
        )
        accepted_response_sha = _sha256_text(repair_text)
        repair_selections = _require_extractor_envelope(
            repair_json,
            contracts=contracts,
            slot_authority=slot_authority,
            task_key=task_key,
        )
        initial_outputs = port.hydrate_extractor_outputs(
            selections=repair_selections,
            contracts=contracts,
            locators=exact_locators,
        )
        response_contract_resolution_values = {
            "contract": "schema67-response-contract-repair-resolution.v2",
            "kind": "response_contract_repair",
            "failure_code": response_contract_failure_code,
            "response_contract_repair_policy_sha256": (_RESPONSE_CONTRACT_REPAIR_POLICY_SHA256),
            "field_ids": tuple(item.field_id for item in contracts),
            "failed_field_ids": response_contract_failed_field_ids,
            "parent_extractor_request_sha256": extractor_request_sha,
            "invalid_response_sha256": invalid_response_sha,
            "repair_request_sha256": response_contract_repair_request_sha,
            "accepted_response_sha256": accepted_response_sha,
        }
        response_contract_repair = ResponseContractRepairResolutionV2.model_validate(
            {
                **response_contract_resolution_values,
                "resolution_hash": canonical_hash(
                    "schema67-response-contract-repair-resolution.v2",
                    response_contract_resolution_values,
                ),
            }
        )
    initial_binding_bytes = _canonical_bytes(
        {
            "task_id": port.task_id,
            "attempt_hash": port.attempt_hash,
            "arm_blueprint_hash": port.arm_blueprint_hash,
            "model_identity_sha256": port.model_identity_sha256,
            "fields": tuple(item.model_dump(mode="python") for item in initial_outputs),
        }
    )
    try:
        initial = (
            port.bind_initial_exact_literal(initial_binding_bytes)
            if _single_pass_mvp and isinstance(port, _Schema67EvidenceBindingPort)
            else port.bind_initial(initial_binding_bytes)
        )
    except Exception:
        raise DeepSeekCompilerError("EVIDENCE_BINDING_FAILED") from None

    final_outputs = initial_outputs
    evidence_receipts = tuple(getattr(initial, "evidence_receipts", ()))
    evidence_demotion: EvidenceDemotionReceiptV1 | None = None
    if _single_pass_mvp and not _allow_evidence_repair:
        if not isinstance(initial, Schema67BoundAttemptV1):
            raise DeepSeekCompilerError("EVIDENCE_DEMOTION_AUTHORITY_INVALID")
        try:
            final_outputs, evidence_receipts, evidence_demotion = _demote_initial_nonpass(
                initial, initial_outputs
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise DeepSeekCompilerError("EVIDENCE_DEMOTION_AUTHORITY_INVALID") from None
        repair = None
    else:
        repair = (
            None
            if isinstance(initial, Schema67BoundAttemptV1)
            and exact_batch_budget.evidence_repairs >= _batch_budget_policy().max_evidence_repairs
            else port.prepare_repair(
                initial,
                tuple((item.field_id, item.allowed_locator_refs) for item in contracts),
            )
        )
        if (
            repair is None
            and response_contract_repair is None
            and isinstance(initial, Schema67BoundAttemptV1)
        ):
            try:
                final_outputs, evidence_receipts, evidence_demotion = _demote_initial_nonpass(
                    initial, initial_outputs
                )
            except (KeyError, TypeError, ValueError, ValidationError):
                raise DeepSeekCompilerError("EVIDENCE_DEMOTION_AUTHORITY_INVALID") from None
    if repair is not None:
        exact_batch_budget.claim_repair("evidence")
        repair_payload = {
            **extractor_payload,
            "repair_kind": "evidence",
            "repair_number": 1,
            "attempt_hash": repair.attempt_hash,
            "field_ids": repair.field_ids,
            "approved_locator_slots": tuple(
                {
                    "field_id": field_id,
                    "source_roles": tuple(
                        {
                            "source_role": role,
                            "allowed_slots": tuple(
                                slot
                                for mapped_field, mapped_role, slot, locator_ref in (
                                    slot_authority.code_mapping
                                )
                                if mapped_field == field_id
                                and mapped_role == role
                                and locator_ref in approved_refs
                            ),
                        }
                        for role, _refs in next(
                            item.source_locator_refs
                            for item in contracts
                            if item.field_id == field_id
                        )
                    ),
                }
                for field_id, approved_refs in repair.approved_locators
            ),
            "parent_bound_attempt_hash": initial.bound_attempt_hash,
            "parent_response_sha256": _sha256_text(initial_text or ""),
            "failure_reasons": tuple(
                {
                    "field_id": item.field_id,
                    "reason_code": item.reason_codes[0],
                }
                for batch in getattr(initial, "verification_batches", ())
                for item in batch.results
                if item.field_id in repair.field_ids and item.status != "PASS"
            ),
            "response_contract": _extractor_response_contract(
                contracts=tuple(item for item in contracts if item.field_id in repair.field_ids),
                task_key=task_key,
                exact_literal_quotes=_single_pass_mvp,
            ),
        }
        repair_user = _canonical_bytes(repair_payload).decode("utf-8")
        _require_request_size(system=extractor_system, user=repair_user)
        repair_text, repair_json = await _call_json(
            transport=transport,
            system=extractor_system,
            user=repair_user,
            budget=budget,
            batch_budget=exact_batch_budget,
            stage="repair",
        )
        repair_selections = _require_extractor_envelope(
            repair_json,
            contracts=tuple(item for item in contracts if item.field_id in repair.field_ids),
            slot_authority=slot_authority,
            task_key=task_key,
        )
        repair_contracts = tuple(item for item in contracts if item.field_id in repair.field_ids)
        repair_outputs = port.hydrate_extractor_outputs(
            selections=repair_selections,
            contracts=repair_contracts,
            locators=exact_locators,
        )
        repair_binding_bytes = _canonical_bytes(
            {
                "task_id": port.task_id,
                "attempt_hash": repair.attempt_hash,
                "arm_blueprint_hash": port.arm_blueprint_hash,
                "model_identity_sha256": port.model_identity_sha256,
                "fields": tuple(item.model_dump(mode="python") for item in repair_outputs),
            }
        )
        try:
            repaired = (
                port.bind_repair_exact_literal(repair_binding_bytes, repair)
                if _single_pass_mvp and isinstance(port, _Schema67EvidenceBindingPort)
                else port.bind_repair(repair_binding_bytes, repair)
            )
        except Exception:
            raise DeepSeekCompilerError("REPAIR_BINDING_FAILED") from None
        if isinstance(repaired, Schema67RepairBindingV1):
            verifier_resolution = repaired.resolution
            evidence_by_field = {item.field_id: item for item in evidence_receipts}
            evidence_by_field.update({item.field_id: item for item in repaired.evidence_receipts})
            evidence_receipts = tuple(
                evidence_by_field[item.field_id]
                for item in initial_outputs
                if item.field_id in evidence_by_field
            )
        else:
            verifier_resolution = repaired
        repair_plan = TargetedRepairPlanV1(
            contract="targeted-repair-plan.v1",
            parent_verification_hash=verifier_resolution.parent_verification_hash,
            repair_number=1,
            field_ids=repair.field_ids,
            approved_locators=tuple(
                ApprovedLocatorSetV1(field_id=field_id, locator_refs=locator_refs)
                for field_id, locator_refs in repair.approved_locators
            ),
        )
        schema67_repair_initial = (
            repair.initial if isinstance(repair.initial, Schema67BoundAttemptV1) else None
        )
        matching_initial_verifications = (
            tuple(
                item
                for item in schema67_repair_initial.verification_batches
                if item.verification_hash == repair_plan.parent_verification_hash
            )
            if schema67_repair_initial is not None
            else ()
        )
        initial_verification = (
            matching_initial_verifications[0] if len(matching_initial_verifications) == 1 else None
        )
        if (
            repair_plan.plan_hash != repair.repair_plan_hash
            or verifier_resolution.repair_plan_hash != repair_plan.plan_hash
            or (
                initial_verification is None
                and tuple(item.field_id for item in verifier_resolution.results)
                != repair_plan.field_ids
            )
            or (
                initial_verification is not None
                and (
                    schema67_repair_initial is None
                    or repair_plan.field_ids
                    != _repairable_nonpass_fields(
                        initial_verification,
                        schema67_repair_initial.outputs,
                    )
                    or tuple(item.field_id for item in verifier_resolution.results)
                    != tuple(item.field_id for item in initial_verification.results)
                    or any(
                        before != after
                        for before, after in zip(
                            initial_verification.results,
                            verifier_resolution.results,
                            strict=True,
                        )
                        if before.status == "PASS"
                    )
                )
            )
        ):
            raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
        repaired_by_field = {
            item.field_id: item
            for item in (
                repaired.outputs
                if isinstance(repaired, Schema67RepairBindingV1)
                else repair_outputs
            )
        }
        final_outputs = tuple(
            repaired_by_field.get(item.field_id, item) for item in initial_outputs
        )
        evidence_repair_values = {
            "contract": "schema67-evidence-repair-trace.v2",
            "kind": "evidence_repair",
            "repair_request_sha256": _request_sha256(system=extractor_system, user=repair_user),
            "accepted_response_sha256": _sha256_text(repair_text),
            "repair_plan_sha256": repair.repair_plan_hash,
            "parent_bound_attempt_hash": repair.parent_bound_attempt_hash,
            "repair_plan": repair_plan.model_dump(mode="python", exclude={"plan_hash"}),
            "verifier_resolution": verifier_resolution.model_dump(
                mode="python", exclude={"resolution_hash"}
            ),
        }
        evidence_repair = EvidenceRepairTraceV2.model_validate(
            {
                **evidence_repair_values,
                "trace_hash": canonical_hash(
                    "schema67-evidence-repair-trace.v2",
                    evidence_repair_values,
                ),
            }
        )

    receipt_values: dict[str, object] = {
        "contract": "deepseek-task-execution-receipt.v2",
        "model_identity": DEEPSEEK_MODEL_IDENTITY.model_dump(mode="python"),
        "execution_identity_sha256": DEEPSEEK_EXECUTION_IDENTITY_SHA256,
        "batch_budget_identity_sha256": exact_batch_budget.identity_sha256,
        "execution_plan_sha256": execution_plan_sha256,
        "task_slice_sha256": task_slice_sha256,
        "schema_workbook_sha256": SCHEMA67_WORKBOOK_SHA256,
        "approved_by": SCHEMA67_APPROVED_BY,
        "task_id": port.task_id,
        "attempt_hash": port.attempt_hash,
        "field_ids": tuple(item.field_id for item in contracts),
        "field_contracts_sha256": _sha256_text(_canonical_bytes(contract_payload).decode("utf-8")),
        "locator_selection_policy_sha256": LOCATOR_SELECTION_POLICY_SHA256,
        "locator_authority_sha256": locator_authority_sha256,
        "locator_selection_sha256": locator_selection_sha256,
        "locator_slot_policy_sha256": LOCATOR_SLOT_POLICY_SHA256,
        "locator_slot_authority_sha256": slot_authority.authority_sha256,
        "response_contract_repair_policy_sha256": (_RESPONSE_CONTRACT_REPAIR_POLICY_SHA256),
        "extractor_request_sha256": extractor_request_sha,
        "response_contract_repair": (
            None
            if response_contract_repair is None
            else response_contract_repair.model_dump(mode="python")
        ),
        "evidence_repair_summary": (
            None
            if evidence_repair is None
            else _evidence_repair_summary(evidence_repair).model_dump(mode="python")
        ),
        "evidence_demotion": (
            None if evidence_demotion is None else evidence_demotion.model_dump(mode="python")
        ),
        "initial_bound_attempt_hash": initial.bound_attempt_hash,
        "initial_outputs_sha256": _outputs_sha256(initial_outputs),
        "final_outputs_sha256": _outputs_sha256(final_outputs),
        "evidence_receipt_hashes": tuple(item.receipt_hash for item in evidence_receipts),
        "locator_calls": budget.locator_calls,
        "extractor_calls": budget.extractor_calls,
        "repair_calls": budget.repair_calls,
        "transport_retries": budget.retries,
        "response_contract_repairs": int(response_contract_repair is not None),
        "evidence_repairs": int(evidence_repair is not None),
        "total_calls": budget.calls,
    }
    receipt = DeepSeekExecutionReceiptV1.model_validate(
        {
            **receipt_values,
            "receipt_hash": canonical_hash(_EXECUTION_RECEIPT_OBJECT_TYPE, receipt_values),
        }
    )
    return DeepSeekTaskExecutionV1(
        initial=initial,
        initial_outputs=initial_outputs,
        final_outputs=final_outputs,
        evidence_receipts=evidence_receipts,
        response_contract_repair=response_contract_repair,
        evidence_repair=evidence_repair,
        evidence_demotion=evidence_demotion,
        receipt=receipt,
    )


def _exact_admitted_sources_815(
    admitted_sources: Sequence[AdmittedParseArtifactV1],
) -> tuple[AdmittedParseArtifactV1, ...]:
    exact: list[AdmittedParseArtifactV1] = []
    for item in admitted_sources:
        try:
            document = ParsedDocumentV1.model_validate(
                item.document.model_dump(mode="python", exclude={"document_hash"})
            )
            manifest = ParseManifestV1.model_validate(
                item.manifest.model_dump(mode="python", exclude={"manifest_hash"})
            )
            decision = ParseQualityDecisionV1.model_validate(
                item.decision.model_dump(mode="python", exclude={"decision_hash"})
            )
            identity = (
                document.document_hash,
                manifest.manifest_hash,
                decision.decision_hash,
            )
        except (AttributeError, TypeError, ValueError, ValidationError):
            raise DeepSeekCompilerError("SCHEMA67_ADMITTED_SOURCE_INVALID") from None
        if (
            document != item.document
            or manifest != item.manifest
            or decision != item.decision
            or item.source_sha256 != document.subject.source_sha256
            or item.artifact_sha256 != identity[0]
            or item.manifest_sha256 != identity[1]
            or item.decision_sha256 != identity[2]
            or manifest.document_hash != identity[0]
            or decision.manifest_hash != identity[1]
            or decision.decision != "ADMIT"
            or decision.admitted_attempt_id != document.attempt.attempt_id
            or document.subject != manifest.subject
            or document.subject != decision.subject
            or document.parser != manifest.parser
            or document.attempt != manifest.attempt
            or document.snapshot != manifest.snapshot
            or document.output_facts != manifest.output_facts
        ):
            raise DeepSeekCompilerError("SCHEMA67_ADMITTED_SOURCE_INVALID")
        exact.append(
            replace(
                item,
                document=document,
                manifest=manifest,
                decision=decision,
            )
        )
    return tuple(exact)


def _exact_schema67_admitted_sources(
    admitted_sources: Sequence[AdmittedParseArtifactV1],
) -> tuple[AdmittedParseArtifactV1, ...]:
    exact = _exact_admitted_sources_815(admitted_sources)
    if tuple(item.role for item in exact) != ("terms", "brochure", "rate_table"):
        raise DeepSeekCompilerError("SCHEMA67_ADMITTED_SOURCE_INVALID")
    return exact


def _schema67_bound_payload(
    *,
    port: _Schema67EvidenceBindingPort,
    outputs: tuple[FreeformFieldOutputV1, ...],
    evidence_receipts: tuple[FreeformEvidenceBindingReceiptV1, ...],
    verification_batches: tuple[VerificationBatchV1, ...],
    receipt_chains: tuple[ReceiptChainV1, ...],
) -> dict[str, object]:
    return {
        "task_id": port.task_id,
        "attempt_hash": port.attempt_hash,
        "execution_plan_sha256": port.prepared.execution_plan_sha256,
        "task_slice_sha256": port.prepared.task_slice_sha256,
        "output_hashes": tuple(
            canonical_hash("schema67-deepseek-field-output.v1", item.model_dump(mode="python"))
            for item in outputs
        ),
        "evidence_receipt_hashes": tuple(item.receipt_hash for item in evidence_receipts),
        "verification_hashes": tuple(item.verification_hash for item in verification_batches),
        "receipt_chain_hashes": tuple(
            tuple(item.receipt_hash for item in chain.receipts) for chain in receipt_chains
        ),
    }


_ADJACENT_FOOTNOTE_MARKERS = frozenset("*†‡※⁰¹²³⁴⁵⁶⁷⁸⁹①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳")


def _has_complete_exact_literal_quote(
    *,
    quote_snapshot: str,
    content_snapshot: str,
) -> bool:
    """Require one exact occurrence that does not truncate an adjacent footnote."""

    offset = content_snapshot.find(quote_snapshot)
    while offset >= 0:
        end = offset + len(quote_snapshot)
        if end == len(content_snapshot) or content_snapshot[end] not in _ADJACENT_FOOTNOTE_MARKERS:
            return True
        offset = content_snapshot.find(quote_snapshot, offset + 1)
    return False


def _require_exact_literal_quote_results(
    batch: VerificationBatchV1,
    outputs: Sequence[FreeformFieldOutputV1],
) -> VerificationBatchV1:
    """Apply the EC-01 literal quote gate without changing value semantics."""

    invalid = {
        output.field_id
        for output in outputs
        if output.state != "unknown"
        and any(
            not _has_complete_exact_literal_quote(
                quote_snapshot=evidence.quote_snapshot,
                content_snapshot=evidence.locator.content_snapshot,
            )
            for evidence in output.evidence
        )
    }
    if not invalid:
        return batch
    results = tuple(
        type(item).model_validate(
            {
                **item.model_dump(mode="python"),
                "status": "FAIL",
                "reason_codes": ("quote_not_found",),
            }
        )
        if item.field_id in invalid
        else item
        for item in batch.results
    )
    return batch.model_copy(update={"results": results})


@dataclass(frozen=True, slots=True)
class _Schema67EvidenceBindingPort:
    prepared: Schema67PreparedTaskV1 = field(repr=False)
    admitted_sources: tuple[AdmittedParseArtifactV1, ...] = field(repr=False)

    @property
    def task_id(self) -> str:
        return self.prepared.provider_task_sha256

    @property
    def attempt_hash(self) -> str:
        return self.prepared.provider_attempt_sha256

    @property
    def field_ids(self) -> tuple[str, ...]:
        return tuple(item.field_id for item in self.prepared.field_prompts)

    @property
    def arm_blueprint_hash(self) -> str:
        return self.prepared.task_slice_sha256

    @property
    def model_identity_sha256(self) -> str:
        return DEEPSEEK_EXECUTION_IDENTITY_SHA256

    @property
    def normalizer_identity_sha256(self) -> str:
        return DEEPSEEK_NORMALIZER_IDENTITY_SHA256

    def _source_by_role(self) -> dict[MaterialRole, AdmittedParseArtifactV1]:
        return {item.role: item for item in self.admitted_sources}

    def validate_locators(self, locators: tuple[CanonicalLocatorInputV1, ...]) -> None:
        documents = tuple(item.document for item in self.admitted_sources)
        for locator in locators:
            matches = []
            for document in documents:
                fact = evidence_verifier._locator_fact(document, locator.locator_ref)
                if fact is None:
                    continue
                kind, page_number, parent_refs, content_hash = fact
                if (
                    kind == locator.locator_kind
                    and page_number == locator.page_number
                    and parent_refs == locator.parent_refs
                    and evidence_verifier._content_snapshot_matches(
                        document=document,
                        kind=kind,
                        content_snapshot=locator.content_snapshot,
                        content_snapshot_sha256=locator.content_snapshot_sha256,
                        parsed_content_hash=content_hash,
                    )
                ):
                    matches.append(document)
            if len(matches) != 1:
                raise DeepSeekCompilerError("LOCATOR_AUTHORITY_MISMATCH")

    def hydrate_extractor_outputs(
        self,
        *,
        selections: tuple[_ExtractorFieldSelectionV1, ...],
        contracts: tuple[DeepSeekFieldPromptInputV1, ...],
        locators: tuple[CanonicalLocatorInputV1, ...],
    ) -> tuple[FreeformFieldOutputV1, ...]:
        return _hydrate_from_code_owned_authority(
            selections=selections,
            contracts=contracts,
            locators=locators,
            sources_by_role=self._source_by_role(),
        )

    def _outputs(
        self, response_json: bytes, field_ids: tuple[str, ...]
    ) -> tuple[FreeformFieldOutputV1, ...]:
        try:
            raw = json.loads(response_json)
            outputs = tuple(FreeformFieldOutputV1.model_validate(item) for item in raw["fields"])
        except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
            raise DeepSeekCompilerError("EVIDENCE_BINDING_FAILED") from None
        if tuple(item.field_id for item in outputs) != field_ids:
            raise DeepSeekCompilerError("EVIDENCE_BINDING_FAILED")
        return outputs

    def _bind_outputs(
        self,
        outputs: tuple[FreeformFieldOutputV1, ...],
        *,
        exact_literal_quotes: bool = False,
        selection_roles_by_field: dict[str, tuple[MaterialRole, ...]] | None = None,
        selection_values_by_field: dict[str, str] | None = None,
    ) -> tuple[
        tuple[FreeformEvidenceBindingReceiptV1, ...],
        tuple[VerificationBatchV1, ...],
        tuple[ReceiptChainV1, ...],
    ]:
        sources = self._source_by_role()
        prompt_by_field = {item.field_id: item for item in self.prepared.field_prompts}
        evidence_roles_by_field: dict[str, tuple[MaterialRole, ...]] = {}
        for output in outputs:
            prompt = prompt_by_field[output.field_id]
            expected_roles = tuple(role for role, _ in prompt.source_locator_refs)
            evidence_roles_list: list[MaterialRole] = []
            for evidence in output.evidence:
                matches = tuple(
                    role
                    for role, refs in prompt.source_locator_refs
                    if evidence.source_revision_id
                    == sources[role].document.subject.source_revision_id
                    and evidence.locator.subject_ref in refs
                )
                if len(matches) != 1:
                    raise DeepSeekCompilerError("EVIDENCE_BINDING_FAILED")
                evidence_roles_list.append(matches[0])
            evidence_roles = tuple(sorted(set(evidence_roles_list)))
            if output.state != "unknown":
                if selection_roles_by_field is None:
                    if set(evidence_roles) != set(expected_roles):
                        raise DeepSeekCompilerError("EVIDENCE_BINDING_FAILED")
                elif (
                    not evidence_roles
                    or not set(evidence_roles).issubset(
                        selection_roles_by_field[output.field_id]
                    )
                ):
                    raise DeepSeekCompilerError("EVIDENCE_BINDING_FAILED")
            evidence_roles_by_field[output.field_id] = evidence_roles

        batches: list[VerificationBatchV1] = []
        chains: list[ReceiptChainV1] = []
        output_by_field = {item.field_id: item for item in outputs}
        for task in self.prepared.source_tasks:
            effective_field_ids = tuple(
                field_id
                for field_id in task.field_ids
                if (
                    task.material_role in evidence_roles_by_field[field_id]
                    if selection_roles_by_field is not None
                    else task.material_role
                    in {
                        role
                        for role, _refs in prompt_by_field[field_id].source_locator_refs
                    }
                )
            )
            if not effective_field_ids:
                continue
            effective_task = build_extraction_task(
                space_id=task.space_id,
                product_version_id=task.product_version_id,
                source_revision_id=task.source_revision_id,
                material_role=task.material_role,
                module_id=task.module_id,
                risk_partition_id=task.risk_partition_id,
                field_ids=effective_field_ids,
                input_refs=task.input_refs,
                budget=task.budget,
                task_profile=task.task_profile,
            )
            attempt = build_initial_attempt(effective_task)
            source = next(
                item
                for item in self.admitted_sources
                if item.document.subject.source_revision_id == task.source_revision_id
            )
            scoped_outputs: list[FreeformFieldOutputV1] = []
            for field_id in effective_field_ids:
                output = output_by_field[field_id]
                scoped_outputs.append(
                    output
                    if output.state == "unknown"
                    else output.model_copy(
                        update={
                            "evidence": tuple(
                                item
                                for item in output.evidence
                                if item.source_revision_id == task.source_revision_id
                            )
                        }
                    )
                )
            candidate_rules = tuple(
                semantic._verification_candidate_and_rule(item) for item in scoped_outputs
            )
            batch = _accept_freeform_semantic_value(
                evidence_verifier.verify_evidence_batch(
                    document=source.document,
                    manifest=source.manifest,
                    candidates=tuple(item[0] for item in candidate_rules),
                    rules=tuple(item[1] for item in candidate_rules),
                ),
                scoped_outputs,
            )
            if selection_values_by_field is not None:
                batch = batch.model_copy(
                    update={
                        "results": tuple(
                            type(item).model_validate(
                                {
                                    **item.model_dump(mode="python"),
                                    "status": "PASS",
                                    "reason_codes": (),
                                }
                            )
                            if item.reason_codes == ("value_not_supported_by_quote",)
                            and selection_values_by_field.get(item.field_id)
                            == output_by_field[item.field_id].value_snapshot
                            else item
                            for item in batch.results
                        )
                    }
                )
            if exact_literal_quotes:
                batch = _require_exact_literal_quote_results(batch, scoped_outputs)
            outcomes = tuple(
                FieldOutcomeV1(
                    field_id=item.field_id,
                    status="candidate" if item.status == "PASS" else "unknown",
                    candidate_ref=(
                        ArtifactRefV1(
                            object_type="verified-field-candidate.v1",
                            artifact_hash=item.candidate_snapshot_hash,
                        )
                        if item.status == "PASS"
                        else None
                    ),
                    reason_code=None if item.status == "PASS" else item.reason_codes[0],
                )
                for item in batch.results
            )
            all_candidate = all(item.status == "candidate" for item in outcomes)
            attempt_receipt = build_attempt_receipt(
                attempt,
                field_outcomes=outcomes,
                outcome="completed" if all_candidate else "insufficient",
                reason_code=None if all_candidate else "evidence_insufficient",
            )
            chain = ReceiptChainV1(
                task=effective_task,
                task_hash=effective_task.task_hash,
                receipts=(attempt_receipt,),
            )
            bind_054_attempt_receipt(chain=chain, verification=batch)
            batches.append(batch)
            chains.append(chain)
        nonpass = {
            item.field_id for batch in batches for item in batch.results if item.status != "PASS"
        }
        receipts: list[FreeformEvidenceBindingReceiptV1] = []
        for output in outputs:
            used = tuple(
                sorted(
                    (sources[role] for role in evidence_roles_by_field[output.field_id]),
                    key=lambda item: item.document.subject.source_revision_id,
                )
            )
            receipt_output = (
                output.model_copy(
                    update={"state": "unknown", "value_snapshot": None, "evidence": ()}
                )
                if output.field_id in nonpass
                else output
            )
            receipts.append(
                bind_freeform_arm_evidence(
                    field_output=receipt_output,
                    documents=()
                    if receipt_output.state == "unknown"
                    else tuple(item.document for item in used),
                    manifests=()
                    if receipt_output.state == "unknown"
                    else tuple(item.manifest for item in used),
                )
            )
        return tuple(receipts), tuple(batches), tuple(chains)

    def bind_native_selection_outputs(
        self,
        outputs: tuple[FreeformFieldOutputV1, ...],
        field_catalogs: tuple[FieldSelectionCatalog815V1, ...],
    ) -> Schema67BoundAttemptV1:
        """Bind code-hydrated native selections through the existing receipt owner."""

        if tuple(item.field_id for item in field_catalogs) != self.field_ids:
            raise DeepSeekCompilerError("EVIDENCE_BINDING_FAILED")
        roles_by_field = {
            item.field_id: item.allowed_source_roles for item in field_catalogs
        }
        values_by_field = {
            item.field_id: item.value_snapshot
            for item in outputs
            if item.value_snapshot is not None
        }
        try:
            exact_port = replace(
                self,
                admitted_sources=_exact_admitted_sources_815(self.admitted_sources),
            )
        except DeepSeekCompilerError:
            raise DeepSeekCompilerError("EVIDENCE_BINDING_FAILED") from None
        receipts, batches, chains = exact_port._bind_outputs(
            outputs,
            exact_literal_quotes=True,
            selection_roles_by_field=roles_by_field,
            selection_values_by_field=values_by_field,
        )
        payload = _schema67_bound_payload(
            port=exact_port,
            outputs=outputs,
            evidence_receipts=receipts,
            verification_batches=batches,
            receipt_chains=chains,
        )
        return Schema67BoundAttemptV1(
            task_id=self.task_id,
            attempt_hash=self.attempt_hash,
            execution_plan_sha256=self.prepared.execution_plan_sha256,
            task_slice_sha256=self.prepared.task_slice_sha256,
            outputs=outputs,
            evidence_receipts=receipts,
            verification_batches=batches,
            receipt_chains=chains,
            bound_attempt_hash=canonical_hash(
                "schema67-deepseek-bound-attempt.v1", payload
            ),
        )

    def _bind_initial(
        self,
        response_json: bytes,
        *,
        exact_literal_quotes: bool,
    ) -> Schema67BoundAttemptV1:
        outputs = self._outputs(response_json, self.field_ids)
        receipts, batches, chains = self._bind_outputs(
            outputs,
            exact_literal_quotes=exact_literal_quotes,
        )
        payload = _schema67_bound_payload(
            port=self,
            outputs=outputs,
            evidence_receipts=receipts,
            verification_batches=batches,
            receipt_chains=chains,
        )
        return Schema67BoundAttemptV1(
            task_id=self.task_id,
            attempt_hash=self.attempt_hash,
            execution_plan_sha256=self.prepared.execution_plan_sha256,
            task_slice_sha256=self.prepared.task_slice_sha256,
            outputs=outputs,
            evidence_receipts=receipts,
            verification_batches=batches,
            receipt_chains=chains,
            bound_attempt_hash=canonical_hash("schema67-deepseek-bound-attempt.v1", payload),
        )

    def bind_initial(self, response_json: bytes) -> Schema67BoundAttemptV1:
        return self._bind_initial(response_json, exact_literal_quotes=False)

    def bind_initial_exact_literal(self, response_json: bytes) -> Schema67BoundAttemptV1:
        return self._bind_initial(response_json, exact_literal_quotes=True)

    def prepare_repair(
        self,
        initial: BoundSemanticAttemptV1 | Schema67BoundAttemptV1,
        locator_refs: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> DeepSeekRepairRequestV1 | None:
        if not isinstance(initial, Schema67BoundAttemptV1):
            return None
        already_unknown = {item.field_id for item in initial.outputs if item.state == "unknown"}
        matching_batches = tuple(
            batch
            for batch in initial.verification_batches
            if any(
                item.status != "PASS" and item.field_id not in already_unknown
                for item in batch.results
            )
        )
        if not matching_batches:
            return None
        # Effective source batches are code-owned projections of the original
        # prepared tasks.  Anchor the repair to the first exact nonpass batch
        # and its matching receipt chain, never to a non-applicable role.
        batch = matching_batches[0]
        nonpass = {
            item.field_id
            for matching in matching_batches
            for item in matching.results
            if item.status != "PASS" and item.field_id not in already_unknown
        }
        unresolved = tuple(
            item.field_id for item in self.prepared.field_prompts if item.field_id in nonpass
        )
        if not unresolved:
            return None
        selected = dict(locator_refs)
        if any(not selected.get(item) for item in unresolved):
            return None
        approved = tuple(
            ApprovedLocatorSetV1(field_id=item, locator_refs=selected[item]) for item in unresolved
        )
        plan = TargetedRepairPlanV1(
            contract="targeted-repair-plan.v1",
            parent_verification_hash=batch.verification_hash,
            repair_number=1,
            field_ids=unresolved,
            approved_locators=approved,
        )
        batch_index = initial.verification_batches.index(batch)
        chain = initial.receipt_chains[batch_index]
        task = chain.task
        if (
            chain.task_hash != task.task_hash
            or len(chain.receipts) != 1
            or task.budget.max_targeted_repairs != 1
            or task.budget.max_total_attempts != 2
        ):
            raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
        attempt_payload = {
            "task_hash": task.task_hash,
            "attempt_number": 2,
            "purpose": "targeted_repair",
            "field_ids": unresolved,
            "parent_receipt_hash": chain.receipts[0].receipt_hash,
        }
        attempt = AttemptRequestV1.model_validate(
            {
                **attempt_payload,
                "attempt_hash": canonical_hash("extraction-attempt.v1", attempt_payload),
            }
        )
        return DeepSeekRepairRequestV1(
            attempt_hash=attempt.attempt_hash,
            repair_plan_hash=plan.plan_hash,
            parent_bound_attempt_hash=initial.bound_attempt_hash,
            field_ids=attempt.field_ids,
            approved_locators=tuple((item.field_id, item.locator_refs) for item in approved),
            attempt=attempt,
            locator_plan=plan,
            initial=initial,
        )

    def _bind_repair(
        self,
        response_json: bytes,
        request: DeepSeekRepairRequestV1,
        *,
        exact_literal_quotes: bool,
    ) -> Schema67RepairBindingV1:
        if (
            not isinstance(request.initial, Schema67BoundAttemptV1)
            or request.attempt is None
            or request.locator_plan is None
            or self.prepared.task_kind != "material"
        ):
            raise DeepSeekCompilerError("REPAIR_BINDING_FAILED")
        outputs = self._outputs(response_json, request.field_ids)
        matching_batches = tuple(
            batch
            for batch in request.initial.verification_batches
            if batch.verification_hash == request.locator_plan.parent_verification_hash
        )
        if len(matching_batches) != 1:
            raise DeepSeekCompilerError("REPAIR_BINDING_FAILED")
        initial_batch = matching_batches[0]
        if set(request.field_ids) == set(self.field_ids):
            receipts, repaired_batches, chains = self._bind_outputs(
                outputs,
                exact_literal_quotes=exact_literal_quotes,
            )
            repaired_by_revision = {item.source_revision_id: item for item in repaired_batches}
            repaired_batch = repaired_by_revision.get(initial_batch.source_revision_id)
            if repaired_batch is None:
                raise DeepSeekCompilerError("REPAIR_BINDING_FAILED")
            all_results_by_field: dict[str, list[FieldVerificationV1]] = {}
            for batch in repaired_batches:
                for item in batch.results:
                    all_results_by_field.setdefault(item.field_id, []).append(item)
            merged_results = tuple(
                next(
                    (
                        item
                        for item in all_results_by_field[initial.field_id]
                        if item.status != "PASS"
                    ),
                    next(
                        item for item in repaired_batch.results if item.field_id == initial.field_id
                    ),
                )
                for initial in initial_batch.results
            )
            merged_batch = initial_batch.model_copy(update={"results": merged_results})
            unresolved = tuple(item for item in merged_results if item.status != "PASS")
            resolution = RepairResolutionV1(
                contract="targeted-repair-resolution.v1",
                parent_verification_hash=initial_batch.verification_hash,
                repair_plan_hash=request.locator_plan.plan_hash,
                results=merged_results,
                gaps=tuple(
                    GapV1(field_id=item.field_id, reason_codes=item.reason_codes)
                    for item in unresolved
                ),
                review_items=tuple(
                    EvidenceReviewItemV1(
                        field_id=item.field_id,
                        reason_code=item.reason_codes[0],
                        parent_verification_hash=merged_batch.verification_hash,
                    )
                    for item in unresolved
                ),
            )
            nonpass = {item.field_id for item in unresolved}
            repaired_outputs = tuple(
                output.model_copy(
                    update={
                        "state": "unknown",
                        "value_snapshot": None,
                        "evidence": (),
                    }
                )
                if output.field_id in nonpass
                else output
                for output in outputs
            )
            receipt_by_field = {item.field_id: item for item in receipts}
            return Schema67RepairBindingV1(
                resolution=resolution,
                outputs=repaired_outputs,
                evidence_receipts=tuple(
                    receipt_by_field[item.field_id] for item in repaired_outputs
                ),
                verification_batches=repaired_batches,
                receipt_chains=chains,
            )
        source = self.admitted_sources[0]
        candidate_rules = tuple(semantic._verification_candidate_and_rule(item) for item in outputs)
        resolution = _apply_schema67_targeted_repair(
            document=source.document,
            manifest=source.manifest,
            initial=initial_batch,
            initial_outputs=request.initial.outputs,
            plan=request.locator_plan,
            repaired_outputs=outputs,
            repaired_candidates=tuple(item[0] for item in candidate_rules),
            rules=tuple(item[1] for item in candidate_rules),
        )
        if exact_literal_quotes:
            literal_batch = _require_exact_literal_quote_results(
                VerificationBatchV1(
                    contract="evidence-verification-batch.v1",
                    product_version_id=initial_batch.product_version_id,
                    source_revision_id=initial_batch.source_revision_id,
                    parse_attempt_id=initial_batch.parse_attempt_id,
                    parsed_document_hash=initial_batch.parsed_document_hash,
                    parse_manifest_hash=initial_batch.parse_manifest_hash,
                    results=resolution.results,
                ),
                outputs,
            )
            gaps, reviews = evidence_verifier._terminal_records(literal_batch)
            resolution = RepairResolutionV1(
                contract="targeted-repair-resolution.v1",
                parent_verification_hash=resolution.parent_verification_hash,
                repair_plan_hash=resolution.repair_plan_hash,
                results=literal_batch.results,
                gaps=gaps,
                review_items=reviews,
            )
        repaired_results = {item.field_id: item for item in resolution.results}
        outputs = tuple(
            output.model_copy(update={"state": "unknown", "value_snapshot": None, "evidence": ()})
            if repaired_results[output.field_id].status != "PASS"
            else output
            for output in outputs
        )
        receipts = tuple(
            bind_freeform_arm_evidence(
                field_output=output,
                documents=() if output.state == "unknown" else (source.document,),
                manifests=() if output.state == "unknown" else (source.manifest,),
            )
            for output in outputs
        )
        repaired_batch = initial_batch.model_copy(update={"results": resolution.results})
        return Schema67RepairBindingV1(
            resolution=resolution,
            outputs=outputs,
            evidence_receipts=receipts,
            verification_batches=(repaired_batch,),
            receipt_chains=request.initial.receipt_chains,
        )

    def bind_repair(
        self, response_json: bytes, request: DeepSeekRepairRequestV1
    ) -> Schema67RepairBindingV1:
        return self._bind_repair(
            response_json,
            request,
            exact_literal_quotes=False,
        )

    def bind_repair_exact_literal(
        self, response_json: bytes, request: DeepSeekRepairRequestV1
    ) -> Schema67RepairBindingV1:
        return self._bind_repair(
            response_json,
            request,
            exact_literal_quotes=True,
        )


def _schema67_binding_ports(
    *,
    prepared_tasks: tuple[Schema67PreparedTaskV1, ...],
    role_inputs: Sequence[Schema67RoleTaskInputV1],
    admitted_sources: Sequence[AdmittedParseArtifactV1],
) -> tuple[_Schema67EvidenceBindingPort, ...]:
    exact_sources = _exact_schema67_admitted_sources(admitted_sources)
    source_by_role = {item.role: item for item in exact_sources}
    inputs = {(item.task_key, item.material_role): item for item in role_inputs}
    ports: list[_Schema67EvidenceBindingPort] = []
    for prepared in prepared_tasks:
        scoped: list[AdmittedParseArtifactV1] = []
        for task in prepared.source_tasks:
            role = task.material_role
            source = source_by_role[role]
            authority = inputs.get((prepared.task_key, role))
            if (
                authority is None
                or task.space_id != source.document.subject.space_id
                or task.product_version_id != source.document.subject.product_version_id
                or task.source_revision_id != source.document.subject.source_revision_id
                or authority.input_refs.parsed_document.artifact_hash
                != source.artifact_sha256
                or authority.input_refs.parse_manifest.artifact_hash
                != source.manifest_sha256
                or authority.input_refs.parse_quality_decision.artifact_hash
                != source.decision_sha256
            ):
                raise DeepSeekCompilerError("SCHEMA67_ADMITTED_SOURCE_INVALID")
            scoped.append(source)
        ports.append(
            _Schema67EvidenceBindingPort(
                prepared=prepared,
                admitted_sources=tuple(scoped),
            )
        )
    return tuple(ports)


def _relation_admitted_sources(
    relation_admission: RelationBoundAdmissionResultV1,
) -> tuple[AdmittedParseArtifactV1, ...]:
    """Replay the exact relation-bound Admission receipt before extraction."""

    if (
        not isinstance(relation_admission, RelationBoundAdmissionResultV1)
        or relation_admission.status != "READY_FOR_QUALITY_FALSIFICATION"
        or relation_admission.admission is None
        or relation_admission.intake_bundle_digest_sha256 is None
        or relation_admission.integration_digest_sha256 is None
        or re.fullmatch(r"[0-9a-f]{64}", relation_admission.intake_bundle_digest_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", relation_admission.integration_digest_sha256) is None
    ):
        raise DeepSeekCompilerError("SCHEMA67_RELATION_ADMISSION_INVALID")
    fresh_admission = admit_596_1_vertical_falsification(
        admitted_parse_artifacts=relation_admission.admitted_parse_artifacts
    )
    if (
        fresh_admission.status != "READY_FOR_QUALITY_FALSIFICATION"
        or fresh_admission.receipt_digest_sha256 is None
        or fresh_admission != relation_admission.admission
    ):
        raise DeepSeekCompilerError("SCHEMA67_RELATION_ADMISSION_INVALID")
    exact_sources = _exact_schema67_admitted_sources(relation_admission.admitted_parse_artifacts)
    if any(source.document.snapshot.snapshot_generation != 0 for source in exact_sources):
        raise DeepSeekCompilerError("SCHEMA67_RELATION_ADMISSION_INVALID")
    authorities = tuple(
        SourceAdmissionAuthorityV1(
            role="rate" if source.role == "rate_table" else source.role,
            space_id=source.document.subject.space_id,
            source_id=source.document.subject.source_id,
            source_revision_id=source.document.subject.source_revision_id,
            snapshot_id=source.document.snapshot.snapshot_id,
            snapshot_generation=cast(Literal[0], source.document.snapshot.snapshot_generation),
            attempt_id=source.document.attempt.attempt_id,
            canonical_envelope_hash=source.document.subject.canonical_envelope_hash,
            concurrent_mutation_fence_hash=(
                source.document.snapshot.concurrent_mutation_fence_hash
            ),
        )
        for source in exact_sources
    )
    relation_bindings = tuple(
        Trusted090RelationInputV1.model_validate(binding).model_dump(mode="python")
        for source in exact_sources
        for binding in source.trusted_relation_bindings
    )
    expected_integration_digest = canonical_hash(
        "relation-bound-admission-596-1.v1",
        {
            "intake_bundle_digest_sha256": (relation_admission.intake_bundle_digest_sha256),
            "authority": tuple(item.model_dump(mode="python") for item in authorities),
            "relation_bindings": relation_bindings,
            "receipt_digest_sha256": fresh_admission.receipt_digest_sha256,
        },
    )
    if expected_integration_digest != relation_admission.integration_digest_sha256:
        raise DeepSeekCompilerError("SCHEMA67_RELATION_ADMISSION_INVALID")
    return exact_sources


def prepare_schema67_real_execution_inputs(
    *,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    relation_admission: RelationBoundAdmissionResultV1,
    captured_contents: Sequence[Schema67CapturedContentV1],
) -> Schema67PreparedExecutionInputsV1:
    """Own real locator recovery, narrowing and 054 input preparation in code."""

    exact_sources = _relation_admitted_sources(relation_admission)
    try:
        exact_captures = tuple(
            Schema67CapturedContentV1.model_validate(item.model_dump(mode="python"))
            for item in captured_contents
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise DeepSeekCompilerError("SCHEMA67_CAPTURE_CONTENT_INVALID") from None
    if tuple(item.role for item in exact_captures) != (
        "terms",
        "brochure",
        "rate_table",
    ) or any(
        capture.source_sha256 != source.source_sha256
        or source.capture_identity_sha256 is None
        or source.content_snapshot_sha256 is None
        or source.raw_structure_sha256 is None
        or source.sanitized_structure_sha256 is None
        or capture.capture_identity_sha256 != source.capture_identity_sha256
        or capture.content_snapshot_sha256 != source.content_snapshot_sha256
        or capture.raw_structure_sha256 != source.raw_structure_sha256
        or capture.sanitized_structure_sha256 != source.sanitized_structure_sha256
        for capture, source in zip(exact_captures, exact_sources, strict=True)
    ):
        raise DeepSeekCompilerError("SCHEMA67_CAPTURE_CONTENT_INVALID")

    source_by_role = {item.role: item for item in exact_sources}
    capture_by_role = {item.role: item for item in exact_captures}
    contract_by_id = {item.field_id: item for item in field_contracts.contracts}
    if field_contracts.contract_set_sha256 != execution_plan.contract_set_sha256 or len(
        contract_by_id
    ) != len(field_contracts.contracts):
        raise DeepSeekCompilerError("SCHEMA67_TASK_AUTHORITY_INVALID")
    locators_by_role: dict[MaterialRole, tuple[CanonicalLocatorInputV1, ...]] = {
        role: recover_exact_mineru_block_locators(
            admitted_source=source_by_role[role],
            content_snapshot=capture_by_role[role].content_snapshot,
        )
        for role in ("terms", "brochure")
    }
    # Rate facts require table/cell coordinates. Until those exact preimages are
    # recovered, block text cannot authorize a known rate value.
    locators_by_role["rate_table"] = ()

    role_inputs: list[Schema67RoleTaskInputV1] = []
    for task_slice in execution_plan.task_slices:
        for role in task_slice.material_roles:
            admitted = source_by_role[role]
            raw_resolution = admitted.material_profile_resolution
            try:
                if not isinstance(raw_resolution, MaterialProfileResolution):
                    raise TypeError
                resolution = MaterialProfileResolution.model_validate(
                    raw_resolution.model_dump(mode="python")
                )
            except (AttributeError, TypeError, ValueError, ValidationError):
                raise DeepSeekCompilerError("SCHEMA67_ADMITTED_SOURCE_INVALID") from None
            field_ids = tuple(
                sorted(
                    field_id
                    for field_id in task_slice.field_ids
                    if role in contract_by_id[field_id].source_roles
                )
            )
            authority_class: Literal["contract_fact", "brochure_fact", "rate_numeric"] = (
                "contract_fact"
                if role == "terms"
                else "brochure_fact"
                if role == "brochure"
                else "rate_numeric"
            )
            task_profile = build_extraction_task_profile(
                material_profile=resolution.profile,
                material_profile_binding_hash=resolution.binding_hash,
                parse_policy_receipt=resolution.parse_policy_receipt,
                field_authority=FieldAuthority(
                    authority_class=authority_class,
                    primary_role=role,
                    support_roles=(),
                    field_ids=field_ids,
                ),
                attempt_budget=AttemptBudgetV1(
                    max_fields=len(field_ids),
                    max_total_attempts=2,
                    max_targeted_repairs=1,
                ),
            )
            input_refs = ParsedArtifactAdmissionPort().admitted_input_refs(
                task_profile=task_profile,
                space_id=admitted.document.subject.space_id,
                product_version_id="596-1",
                source_revision_id=admitted.document.subject.source_revision_id,
                source_revision=ArtifactRefV1(
                    object_type="source-revision.v1",
                    artifact_hash=admitted.document.subject.canonical_envelope_hash,
                ),
                resolved_template=ArtifactRefV1(
                    object_type="resolved-template.v1",
                    artifact_hash=resolution.resolved_template.content_hash,
                ),
                schema_contract=ArtifactRefV1(
                    object_type="schema67-field-contract-set.v1",
                    artifact_hash=field_contracts.contract_set_sha256,
                ),
                document=admitted.document,
                manifest=admitted.manifest,
                quality_decision=admitted.decision,
            )
            role_inputs.append(
                Schema67RoleTaskInputV1(
                    task_key=task_slice.task_key,
                    material_role=role,
                    space_id=admitted.document.subject.space_id,
                    product_version_id="596-1",
                    source_revision_id=admitted.document.subject.source_revision_id,
                    module_id=f"schema67-{task_slice.task_key}-{role}",
                    risk_partition_id=f"schema67-{task_slice.task_key}-{role}-risk",
                    allowed_locator_refs=tuple(
                        (
                            field_id,
                            select_contract_locator_refs(
                                contract=contract_by_id[field_id],
                                locators=locators_by_role[role],
                            ),
                        )
                        for field_id in field_ids
                    ),
                    input_refs=input_refs,
                    task_profile=task_profile,
                )
            )

    exact_role_inputs = tuple(role_inputs)
    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        role_inputs=exact_role_inputs,
    )
    input_by_key = {(item.task_key, item.material_role): item for item in exact_role_inputs}
    locator_groups: list[tuple[CanonicalLocatorInputV1, ...]] = []
    for task in prepared:
        group: list[CanonicalLocatorInputV1] = []
        for source_task in task.source_tasks:
            role = source_task.material_role
            authority = input_by_key[(task.task_key, role)]
            allowed = {
                locator_ref
                for _field_id, locator_refs in authority.allowed_locator_refs
                for locator_ref in locator_refs
            }
            group.extend(
                locator for locator in locators_by_role[role] if locator.locator_ref in allowed
            )
        if len({item.locator_ref for item in group}) != len(group):
            raise DeepSeekCompilerError("SCHEMA67_LOCATOR_DERIVATION_INVALID")
        locator_groups.append(tuple(group))
    exact_groups = tuple(locator_groups)
    preparation_sha256 = canonical_hash(
        "schema67-real-execution-inputs.v1",
        {
            "contract_set_sha256": field_contracts.contract_set_sha256,
            "execution_plan_sha256": execution_plan.execution_plan_sha256,
            "admitted_document_hashes": tuple(
                item.document.document_hash for item in exact_sources
            ),
            "captured_content_hashes": tuple(
                item.content_snapshot_sha256 for item in exact_captures
            ),
            "role_inputs": tuple(
                {
                    "task_key": item.task_key,
                    "material_role": item.material_role,
                    "profile_hash": item.task_profile.profile_hash,
                    "allowed_locator_refs": item.allowed_locator_refs,
                }
                for item in exact_role_inputs
            ),
            "locator_groups": tuple(
                tuple(item.model_dump(mode="python") for item in group) for group in exact_groups
            ),
        },
    )
    return Schema67PreparedExecutionInputsV1(
        role_inputs=exact_role_inputs,
        locators_by_task=exact_groups,
        preparation_sha256=preparation_sha256,
    )


@dataclass(frozen=True, slots=True)
class _SemanticBindingPort5961:
    composition: SemanticInputCompositionV1 = field(repr=False)
    admitted_sources: tuple[AdmittedParseArtifactV1, ...] = field(repr=False)
    task: ComposedSemanticTaskV1 = field(repr=False)
    arm_blueprint_hash: str
    model_identity_sha256: str
    normalizer_identity_sha256: str

    @property
    def task_id(self) -> str:
        return self.task.task_id

    @property
    def attempt_hash(self) -> str:
        if self.task.initial_attempt is None:
            raise DeepSeekCompilerError("TASK_NOT_SEMANTIC")
        return self.task.initial_attempt.attempt_hash

    @property
    def field_ids(self) -> tuple[str, ...]:
        return self.task.field_ids

    def bind_initial(self, response_json: bytes) -> BoundSemanticAttemptV1:
        return semantic.bind_596_1_semantic_response(
            composition=self.composition,
            task_id=self.task_id,
            response_json=response_json,
            admitted_sources=self.admitted_sources,
        )

    def validate_locators(self, locators: tuple[CanonicalLocatorInputV1, ...]) -> None:
        document = self._source().document
        for item in locators:
            fact = evidence_verifier._locator_fact(document, item.locator_ref)
            if fact is None:
                raise DeepSeekCompilerError("LOCATOR_AUTHORITY_MISMATCH")
            kind, page_number, parent_refs, content_hash = fact
            if not (
                kind == item.locator_kind
                and page_number == item.page_number
                and parent_refs == item.parent_refs
                and evidence_verifier._content_snapshot_matches(
                    document=document,
                    kind=kind,
                    content_snapshot=item.content_snapshot,
                    content_snapshot_sha256=item.content_snapshot_sha256,
                    parsed_content_hash=content_hash,
                )
            ):
                raise DeepSeekCompilerError("LOCATOR_AUTHORITY_MISMATCH")

    def hydrate_extractor_outputs(
        self,
        *,
        selections: tuple[_ExtractorFieldSelectionV1, ...],
        contracts: tuple[DeepSeekFieldPromptInputV1, ...],
        locators: tuple[CanonicalLocatorInputV1, ...],
    ) -> tuple[FreeformFieldOutputV1, ...]:
        return _hydrate_from_code_owned_authority(
            selections=selections,
            contracts=contracts,
            locators=locators,
            sources_by_role={self.task.material_role: self._source()},
        )

    def _source(self) -> AdmittedParseArtifactV1:
        return next(item for item in self.admitted_sources if item.role == self.task.material_role)

    def prepare_repair(
        self,
        initial: BoundSemanticAttemptV1 | Schema67BoundAttemptV1,
        locator_refs: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> DeepSeekRepairRequestV1 | None:
        if not isinstance(initial, BoundSemanticAttemptV1):
            return None
        verification = initial.verification
        chain = initial.receipt_chain
        extraction_task = self.task.extraction_task
        if verification is None or chain is None or extraction_task is None:
            return None
        unresolved = tuple(item.field_id for item in verification.results if item.status != "PASS")
        if not unresolved:
            return None
        selected = dict(locator_refs)
        if any(not selected[item] for item in unresolved):
            return None
        approved = tuple(
            ApprovedLocatorSetV1(field_id=item, locator_refs=selected[item]) for item in unresolved
        )
        decision = plan_targeted_repair(
            verification,
            approved_locators=approved,
            budget=RepairBudgetV1(max_targeted_repairs=1),
            repairs_used=0,
        )
        if decision.plan is None:
            return None
        attempt = build_targeted_repair(extraction_task, chain)
        return DeepSeekRepairRequestV1(
            attempt_hash=attempt.attempt_hash,
            repair_plan_hash=decision.plan.plan_hash,
            parent_bound_attempt_hash=initial.bound_attempt_hash,
            field_ids=attempt.field_ids,
            approved_locators=tuple((item.field_id, item.locator_refs) for item in approved),
            attempt=attempt,
            locator_plan=decision.plan,
            initial=initial,
        )

    def bind_repair(
        self,
        response_json: bytes,
        request: DeepSeekRepairRequestV1,
    ) -> RepairResolutionV1:
        if (
            request.locator_plan is None
            or request.attempt is None
            or not isinstance(request.initial, BoundSemanticAttemptV1)
            or request.initial.verification is None
            or request.initial.receipt_chain is None
            or self.task.extraction_task is None
        ):
            raise DeepSeekCompilerError("REPAIR_BINDING_FAILED")
        try:
            raw = json.loads(response_json)
            outputs = tuple(FreeformFieldOutputV1.model_validate(item) for item in raw["fields"])
        except (KeyError, TypeError, ValueError, ValidationError, json.JSONDecodeError):
            raise DeepSeekCompilerError("REPAIR_BINDING_FAILED") from None
        if tuple(item.field_id for item in outputs) != request.field_ids:
            raise DeepSeekCompilerError("REPAIR_BINDING_FAILED")
        source = self._source()
        candidates: list[FieldCandidateV1] = []
        rules: list[FieldRuleV1] = []
        for output in outputs:
            bind_freeform_arm_evidence(
                field_output=output,
                documents=() if output.state == "unknown" else (source.document,),
                manifests=() if output.state == "unknown" else (source.manifest,),
            )
            candidate, rule = semantic._verification_candidate_and_rule(output)
            candidates.append(candidate)
            rules.append(rule)
        resolution = apply_targeted_repair(
            document=source.document,
            manifest=source.manifest,
            initial=request.initial.verification,
            plan=request.locator_plan,
            repaired_candidates=tuple(candidates),
            rules=tuple(rules),
        )
        repaired_results = tuple(
            item for item in resolution.results if item.field_id in request.field_ids
        )
        outcomes = tuple(
            FieldOutcomeV1(
                field_id=item.field_id,
                status="candidate" if item.status == "PASS" else "unknown",
                candidate_ref=(
                    ArtifactRefV1(
                        object_type="verified-field-candidate.v1",
                        artifact_hash=item.candidate_snapshot_hash,
                    )
                    if item.status == "PASS"
                    else None
                ),
                reason_code=None if item.status == "PASS" else item.reason_codes[0],
            )
            for item in repaired_results
        )
        all_candidate = all(item.status == "candidate" for item in outcomes)
        receipt = build_attempt_receipt(
            request.attempt,
            field_outcomes=outcomes,
            outcome="completed" if all_candidate else "insufficient",
            reason_code=None if all_candidate else "evidence_insufficient",
        )
        chain = ReceiptChainV1(
            task=self.task.extraction_task,
            task_hash=self.task.extraction_task.task_hash,
            receipts=(*request.initial.receipt_chain.receipts, receipt),
        )
        repaired_batch = request.initial.verification.model_copy(
            update={"results": repaired_results}
        )
        bind_054_attempt_receipt(chain=chain, verification=repaired_batch)
        return resolution


def _binding_port(
    *,
    composition: SemanticInputCompositionV1,
    task_id: str,
    admitted_sources: tuple[AdmittedParseArtifactV1, ...],
) -> _SemanticBindingPort5961:
    try:
        exact = SemanticInputCompositionV1.model_validate(composition.model_dump(mode="python"))
        admitted_sources = semantic._exact_admitted_sources(exact, admitted_sources)
        task = next(item for item in exact.tasks if item.task_id == task_id)
        execution_identity = _select_deepseek_execution_identity(
            tuple(item.execution_identity for item in exact.arm_blueprints)
        )
        arm = next(
            item for item in exact.arm_blueprints if item.execution_identity == execution_identity
        )
    except DeepSeekCompilerError:
        raise
    except (AttributeError, StopIteration, TypeError, ValueError, ValidationError):
        raise DeepSeekCompilerError("SEMANTIC_INPUT_INVALID") from None
    if task.initial_attempt is None or task.extraction_task is None:
        raise DeepSeekCompilerError("TASK_NOT_SEMANTIC")
    return _SemanticBindingPort5961(
        composition=exact,
        admitted_sources=admitted_sources,
        task=task,
        arm_blueprint_hash=arm.blueprint_hash,
        model_identity_sha256=arm.execution_identity.model_identity_sha256,
        normalizer_identity_sha256=arm.execution_identity.normalizer_identity_sha256,
    )


_SHARED_EVIDENCE_REPAIR_TASK_KEY: Final[str] = "schema67-batch-evidence-repair-01"
_SHARED_REPAIR_PARENT_SET_OBJECT_TYPE: Final[str] = (
    "schema67-repair-parent-verification-set.815.v1"
)


@dataclass(frozen=True, slots=True)
class _Schema67RepairChild:
    request: DeepSeekRepairRequestV1 = field(repr=False)
    source_role: MaterialRole
    source_revision_id: str
    source_task_hash: str
    parent_receipt_hash: str
    parent_verification_hash: str


def _schema67_repair_child_identity(
    child: _Schema67RepairChild,
) -> dict[str, object]:
    return {
        "source_role": child.source_role,
        "source_revision_id": child.source_revision_id,
        "source_task_hash": child.source_task_hash,
        "attempt_hash": child.request.attempt_hash,
        "parent_receipt_hash": child.parent_receipt_hash,
        "parent_verification_hash": child.parent_verification_hash,
        "repair_plan_sha256": child.request.repair_plan_hash,
        "field_ids": child.request.field_ids,
    }


def _scope_authorized_targeted_repair_attempt(
    *,
    authorized: AttemptRequestV1,
    actionable_field_ids: tuple[str, ...],
) -> AttemptRequestV1:
    if actionable_field_ids == authorized.field_ids:
        return authorized
    if (
        not actionable_field_ids
        or len(actionable_field_ids) != len(set(actionable_field_ids))
        or not set(actionable_field_ids).issubset(authorized.field_ids)
    ):
        raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
    payload = {
        "task_hash": authorized.task_hash,
        "attempt_number": authorized.attempt_number,
        "purpose": authorized.purpose,
        "field_ids": actionable_field_ids,
        "parent_receipt_hash": authorized.parent_receipt_hash,
    }
    return AttemptRequestV1.model_validate(
        {
            **payload,
            "attempt_hash": canonical_hash("extraction-attempt.v1", payload),
        }
    )


def _schema67_repair_children(
    *,
    initial: Schema67BoundAttemptV1,
    locator_refs: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[_Schema67RepairChild, ...]:
    if len(initial.verification_batches) != len(initial.receipt_chains):
        raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
    already_unknown = {item.field_id for item in initial.outputs if item.state == "unknown"}
    selected = dict(locator_refs)
    children: list[_Schema67RepairChild] = []
    for batch, chain in zip(
        initial.verification_batches,
        initial.receipt_chains,
        strict=True,
    ):
        task = chain.task
        try:
            bind_054_attempt_receipt(chain=chain, verification=batch)
        except (TypeError, ValueError):
            raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED") from None
        nonpass = {
            item.field_id
            for item in batch.results
            if item.status != "PASS" and item.field_id not in already_unknown
        }
        if not nonpass:
            continue
        try:
            authorized_attempt = build_targeted_repair(task, chain)
        except (TypeError, ValueError):
            raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED") from None
        unresolved = tuple(
            item.field_id for item in initial.outputs if item.field_id in nonpass
        )
        attempt = _scope_authorized_targeted_repair_attempt(
            authorized=authorized_attempt,
            actionable_field_ids=unresolved,
        )
        if any(not selected.get(item) for item in unresolved):
            raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
        approved = tuple(
            ApprovedLocatorSetV1(field_id=item, locator_refs=selected[item])
            for item in unresolved
        )
        plan = TargetedRepairPlanV1(
            contract="targeted-repair-plan.v1",
            parent_verification_hash=batch.verification_hash,
            repair_number=1,
            field_ids=unresolved,
            approved_locators=approved,
        )
        parent_receipt_hash = chain.receipts[0].receipt_hash
        request = DeepSeekRepairRequestV1(
            attempt_hash=attempt.attempt_hash,
            repair_plan_hash=plan.plan_hash,
            parent_bound_attempt_hash=initial.bound_attempt_hash,
            field_ids=unresolved,
            approved_locators=tuple(
                (item.field_id, item.locator_refs) for item in approved
            ),
            attempt=attempt,
            locator_plan=plan,
            initial=initial,
        )
        children.append(
            _Schema67RepairChild(
                request=request,
                source_role=task.material_role,
                source_revision_id=task.source_revision_id,
                source_task_hash=task.task_hash,
                parent_receipt_hash=parent_receipt_hash,
                parent_verification_hash=batch.verification_hash,
            )
        )
    return tuple(children)


def _shared_repair_parent_hash(
    children: tuple[_Schema67RepairChild, ...],
) -> str:
    if not children:
        raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
    if len(children) == 1:
        return children[0].parent_verification_hash
    return canonical_hash(
        _SHARED_REPAIR_PARENT_SET_OBJECT_TYPE,
        tuple(item.parent_verification_hash for item in children),
    )


@dataclass(frozen=True, slots=True)
class _SharedEvidenceRepairTask:
    index: int
    port: _Schema67EvidenceBindingPort = field(repr=False)
    contracts: tuple[DeepSeekFieldPromptInputV1, ...] = field(repr=False)
    locators: tuple[CanonicalLocatorInputV1, ...] = field(repr=False)
    execution: DeepSeekTaskExecutionV1 = field(repr=False)
    children: tuple[_Schema67RepairChild, ...] = field(repr=False)
    repair_plan: TargetedRepairPlanV1 = field(repr=False)


@dataclass(frozen=True, slots=True)
class _SharedEvidenceRepairContext:
    tasks: tuple[_SharedEvidenceRepairTask, ...] = field(repr=False)
    contracts: tuple[DeepSeekFieldPromptInputV1, ...] = field(repr=False)
    slot_authority: _LocatorSlotAuthorityV1 = field(repr=False)
    system: str = field(repr=False)
    user: str = field(repr=False)


def _field_local_repair_contexts(
    *,
    contract_payloads: tuple[dict[str, object], ...],
    failure_reasons: tuple[dict[str, str], ...],
    catalog: tuple[_LocatorSlotCatalogEntryV1, ...],
    field_locator_slots: tuple[_FieldLocatorSlotsV1, ...],
) -> tuple[dict[str, object], ...]:
    if not (
        len(contract_payloads)
        == len(failure_reasons)
        == len(field_locator_slots)
    ):
        raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
    catalog_by_slot = {item.slot: item for item in catalog}
    if len(catalog_by_slot) != len(catalog):
        raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
    contexts: list[dict[str, object]] = []
    for contract_payload, failure_reason, locator_row in zip(
        contract_payloads,
        failure_reasons,
        field_locator_slots,
        strict=True,
    ):
        field_id = contract_payload.get("field_id")
        if (
            not isinstance(field_id, str)
            or failure_reason.get("field_id") != field_id
            or locator_row.field_id != field_id
        ):
            raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
        sources: list[dict[str, object]] = []
        for source in locator_row.sources:
            allowed_locators: list[dict[str, object]] = []
            for slot in source.allowed_slots:
                locator = catalog_by_slot.get(slot)
                if locator is None:
                    raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
                allowed_locators.append(locator.model_dump(mode="python"))
            sources.append(
                {
                    "source_role": source.source_role,
                    "allowed_locators": tuple(allowed_locators),
                }
            )
        contexts.append(
            {
                "field_id": field_id,
                "field_contract": contract_payload,
                "failure_reason": failure_reason,
                "sources": tuple(sources),
            }
        )
    return tuple(contexts)


@dataclass(frozen=True, slots=True)
class _CapturedInitialBatch:
    responses: tuple[str, ...] = field(repr=False)
    request_sha256s: tuple[str, ...]


async def _capture_initial_responses(
    *,
    profile: ModelProfile,
    policy: ProductionModelPolicy,
    transport: ModelClient,
    prepared: tuple[Schema67PreparedTaskV1, ...],
    ports: tuple[_Schema67EvidenceBindingPort, ...],
    locators_by_task: tuple[tuple[CanonicalLocatorInputV1, ...], ...],
) -> _CapturedInitialBatch:
    """Capture exact provider bytes before parsing or Evidence validation."""

    if not (len(prepared) == len(ports) == len(locators_by_task) == 8):
        raise DeepSeekCompilerError("SCHEMA67_BATCH_AUTHORITY_INVALID")
    responses: list[str] = []
    request_sha256s: list[str] = []
    for task, port, locators in zip(
        prepared,
        ports,
        locators_by_task,
        strict=True,
    ):
        request = _prepare_extractor_request(
            profile=profile,
            policy=policy,
            port=port,
            field_contracts=task.field_prompts,
            locators=locators,
            task_key=task.task_key,
            exact_literal_quotes=True,
        )
        response = await transport.complete(request.system, request.user)
        if type(response) is not str:
            raise DeepSeekCompilerError("MODEL_TRANSPORT_FAILED")
        responses.append(response)
        request_sha256s.append(request.request_sha256)
    return _CapturedInitialBatch(
        responses=tuple(responses),
        request_sha256s=tuple(request_sha256s),
    )


def _project_captured_initial_responses(
    *,
    captured: _CapturedInitialBatch,
    prepared: tuple[Schema67PreparedTaskV1, ...],
    ports: tuple[_Schema67EvidenceBindingPort, ...],
    locators_by_task: tuple[tuple[CanonicalLocatorInputV1, ...], ...],
) -> tuple[tuple[str, ...], tuple[str | None, ...]]:
    if not (
        len(captured.responses)
        == len(captured.request_sha256s)
        == len(prepared)
        == len(ports)
        == len(locators_by_task)
        == 8
    ):
        raise DeepSeekCompilerError("SCHEMA67_BATCH_AUTHORITY_INVALID")
    replay_responses: list[str] = []
    failure_codes: list[str | None] = []
    for response, task, port, locators in zip(
        captured.responses,
        prepared,
        ports,
        locators_by_task,
        strict=True,
    ):
        replacement, failure_code = _replace_structurally_invalid_initial_response(
            response_text=response,
            port=port,
            contracts=tuple(task.field_prompts),
            locators=locators,
            task_key=task.task_key,
        )
        replay_responses.append(replacement)
        failure_codes.append(failure_code)
    return tuple(replay_responses), tuple(failure_codes)


class _InitialResponseReplayTransport:
    def __init__(
        self,
        *,
        responses: tuple[str, ...],
        request_sha256s: tuple[str, ...],
    ) -> None:
        if len(responses) != 8 or len(request_sha256s) != 8:
            raise DeepSeekCompilerError("SCHEMA67_MVP_EXACT_EIGHT_TASKS_REQUIRED")
        self._responses = responses
        self._request_sha256s = request_sha256s
        self._index = 0

    @property
    def consumed(self) -> int:
        return self._index

    async def complete(self, system: str, user: str) -> str:
        index = self._index
        if index >= len(self._responses) or _request_sha256(
            system=system,
            user=user,
        ) != self._request_sha256s[index]:
            raise DeepSeekCompilerError("SCHEMA67_TASK_AUTHORITY_INVALID")
        self._index += 1
        return self._responses[index]


def _require_prepared_task_execution_authority(
    *,
    task: Schema67PreparedTaskV1,
    port: _Schema67EvidenceBindingPort,
) -> tuple[DeepSeekFieldPromptInputV1, ...]:
    try:
        source_tasks = tuple(
            ExtractionTaskV1.model_validate(item) for item in task.source_tasks
        )
        initial_attempts = tuple(
            AttemptRequestV1.model_validate(item) for item in task.initial_attempts
        )
        prompts = tuple(
            DeepSeekFieldPromptInputV1.model_validate(item)
            for item in task.field_prompts
        )
    except (AttributeError, TypeError, ValueError):
        raise DeepSeekCompilerError("SCHEMA67_TASK_AUTHORITY_INVALID") from None
    if (
        len(source_tasks) != len(initial_attempts)
        or any(
            attempt != build_initial_attempt(source_task)
            for source_task, attempt in zip(source_tasks, initial_attempts, strict=True)
        )
        or port.task_id != task.provider_task_sha256
        or port.attempt_hash != task.provider_attempt_sha256
        or port.field_ids != tuple(item.field_id for item in prompts)
    ):
        raise DeepSeekCompilerError("SCHEMA67_TASK_AUTHORITY_INVALID")
    return prompts


async def _capture_native_selection_responses_815(
    *,
    profile: ModelProfile,
    policy: ProductionModelPolicy,
    transport: ModelClient,
    prepared: tuple[Schema67PreparedTaskV1, ...],
    ports: tuple[_Schema67EvidenceBindingPort, ...],
    locators_by_task: tuple[tuple[CanonicalLocatorInputV1, ...], ...],
    selection_catalog: Schema67SelectionCatalog815V1,
) -> _CapturedInitialBatch:
    """Capture all native-selection bytes before offline response validation."""

    if not (len(prepared) == len(ports) == len(locators_by_task) == 8):
        raise DeepSeekCompilerError("SCHEMA67_BATCH_AUTHORITY_INVALID")
    requests: list[tuple[str, str, str]] = []
    for task, port, locators in zip(
        prepared,
        ports,
        locators_by_task,
        strict=True,
    ):
        prompts = _require_prepared_task_execution_authority(task=task, port=port)
        prepared_request = _prepare_native_selection_authority_815(
            profile=profile,
            policy=policy,
            port=port,
            field_contracts=prompts,
            locators=locators,
            task_key=task.task_key,
        )
        task_catalogs = tuple(
            _task_native_selection_catalog_815(
                prompt=item,
                catalog=selection_catalog.require_field(item.field_id),
            )
            for item in prompts
        )
        requests.append(
            _prepare_native_selection_request_815(
                prepared_request=prepared_request,
                task_key=task.task_key,
                field_catalogs=task_catalogs,
            )
        )
    responses: list[str] = []
    request_sha256s: list[str] = []
    for system, user, request_sha256 in requests:
        try:
            response = await transport.complete(system, user)
        except TruncatedOutputError:
            raise _ModelResponseDecodeFailure(
                "MODEL_CONTENT_EMPTY",
                _sha256_text(""),
            ) from None
        except Exception:
            raise DeepSeekCompilerError("MODEL_TRANSPORT_FAILED") from None
        if type(response) is not str:
            raise DeepSeekCompilerError("MODEL_TRANSPORT_FAILED")
        responses.append(response)
        request_sha256s.append(request_sha256)
    return _CapturedInitialBatch(
        responses=tuple(responses),
        request_sha256s=tuple(request_sha256s),
    )


_STRUCTURAL_INITIAL_FAILURE_CODES: Final[frozenset[str]] = frozenset(
    {
        "MODEL_JSON_INVALID",
        "EXTRACTOR_TOP_LEVEL_SHAPE_INVALID",
        "EXTRACTOR_FIELD_ITEM_SHAPE_INVALID",
        "EXTRACTOR_STRING_CONSTRAINT_INVALID",
    }
)


def _structural_nonpass_response(
    *,
    port: _Schema67EvidenceBindingPort,
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    locators: tuple[CanonicalLocatorInputV1, ...],
    task_key: str,
) -> str:
    """Build a private nonpass placeholder; it never replaces the retained raw."""

    authority = _build_locator_slot_authority(
        port=port,
        contracts=contracts,
        locators=locators,
    )
    catalog = {item.slot: item for item in authority.catalog}
    rows = {item.field_id: item for item in authority.field_locator_slots}
    fields: list[dict[str, object]] = []
    for contract in contracts:
        if contract.requires_unknown_review:
            fields.append(
                {
                    "field_id": contract.field_id,
                    "state": "unknown",
                    "value_snapshot": None,
                    "evidence": [],
                }
            )
            continue
        evidence: list[dict[str, str]] = []
        for source in rows[contract.field_id].sources:
            slot = source.allowed_slots[0]
            anchor = catalog[slot].content_snapshot[:200].strip()
            nonliteral = f"[invalid-initial-shape]{anchor}"[:512]
            evidence.append(
                {
                    "source_role": source.source_role,
                    "locator_slot": slot,
                    "quote_snapshot": nonliteral,
                }
            )
        fields.append(
            {
                "field_id": contract.field_id,
                "state": "present",
                "value_snapshot": evidence[0]["quote_snapshot"],
                "evidence": evidence,
            }
        )
    return _canonical_bytes({"task_key": task_key, "fields": fields}).decode("utf-8")


def _locator_membership_nonpass_response(
    *,
    response_text: str,
    failed_field_ids: tuple[str, ...],
    port: _Schema67EvidenceBindingPort,
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    locators: tuple[CanonicalLocatorInputV1, ...],
    task_key: str,
) -> str:
    """Project only selected fields to an Evidence-nonpass row."""

    original = json.loads(response_text)
    placeholder = json.loads(
        _structural_nonpass_response(
            port=port,
            contracts=contracts,
            locators=locators,
            task_key=task_key,
        )
    )
    failed = set(failed_field_ids)
    placeholder_by_field = {
        item["field_id"]: item for item in placeholder["fields"]
    }
    fields = tuple(
        placeholder_by_field[item["field_id"]]
        if item["field_id"] in failed
        else item
        for item in original["fields"]
    )
    return _canonical_bytes({"task_key": task_key, "fields": fields}).decode("utf-8")


def _duplicate_evidence_locator_field_ids(
    *,
    selections: tuple[_ExtractorFieldSelectionV1, ...],
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
) -> tuple[str, ...]:
    """Return contract-ordered fields whose Evidence repeats one locator ref."""

    if tuple(item.field_id for item in selections) != tuple(
        item.field_id for item in contracts
    ):
        raise DeepSeekCompilerError("EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID")
    return tuple(
        contract.field_id
        for selection, contract in zip(selections, contracts, strict=True)
        if len(tuple(item.locator_ref for item in selection.evidence))
        != len({item.locator_ref for item in selection.evidence})
    )


def _forced_unknown_invalid_field_ids(
    *,
    payload: object,
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    task_key: str,
) -> tuple[str, ...]:
    """Identify only closed, ordered forced-UNKNOWN rows returned as known."""

    if type(payload) is not dict or set(payload) != {"task_key", "fields"}:
        return ()
    if payload["task_key"] != task_key or type(payload["fields"]) is not list:
        return ()
    raw_fields = payload["fields"]
    if len(raw_fields) != len(contracts):
        return ()
    required_field_keys = {"field_id", "state", "value_snapshot", "evidence"}
    field_ids: list[str] = []
    states: list[str] = []
    for raw_field in raw_fields:
        if type(raw_field) is not dict or set(raw_field) != required_field_keys:
            return ()
        field_id = raw_field["field_id"]
        if not _is_extractor_string(field_id):
            return ()
        field_ids.append(field_id)
        state = raw_field["state"]
        if state not in {"present", "absent_explicitly", "unknown"}:
            return ()
        states.append(state)
    expected_field_ids = tuple(item.field_id for item in contracts)
    if len(field_ids) != len(set(field_ids)) or set(field_ids) != set(expected_field_ids):
        raise DeepSeekCompilerError("EXTRACTOR_FIELD_COUNT_OR_SET_INVALID")
    if tuple(field_ids) != expected_field_ids:
        raise DeepSeekCompilerError("EXTRACTOR_FIELD_ORDER_INVALID")
    return tuple(
        contract.field_id
        for contract, state in zip(contracts, states, strict=True)
        if contract.requires_unknown_review and state != "unknown"
    )


def _replace_structurally_invalid_initial_response(
    *,
    response_text: str,
    port: _Schema67EvidenceBindingPort,
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    locators: tuple[CanonicalLocatorInputV1, ...],
    task_key: str,
) -> tuple[str, str | None]:
    """Defer closed shape and field-scoped locator failures to shared repair."""

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError:
        failure_code = "MODEL_JSON_INVALID"
    else:
        authority = _build_locator_slot_authority(
            port=port,
            contracts=contracts,
            locators=locators,
        )
        forced_unknown_invalid = _forced_unknown_invalid_field_ids(
            payload=payload,
            contracts=contracts,
            task_key=task_key,
        )
        forced_unknown_failure_code: str | None = None
        if forced_unknown_invalid:
            response_text = _locator_membership_nonpass_response(
                response_text=response_text,
                failed_field_ids=forced_unknown_invalid,
                port=port,
                contracts=contracts,
                locators=locators,
                task_key=task_key,
            )
            payload = json.loads(response_text)
            forced_unknown_failure_code = "EXTRACTOR_FORCED_UNKNOWN_INVALID"
        try:
            selections = _require_extractor_envelope(
                payload,
                contracts=contracts,
                slot_authority=authority,
                task_key=task_key,
            )
        except DeepSeekCompilerError as error:
            if isinstance(error, _LocatorMembershipFailure):
                combined_failed_field_ids = set(error.failed_field_ids) | set(
                    error.duplicate_locator_field_ids
                )
                return (
                    _locator_membership_nonpass_response(
                        response_text=response_text,
                        failed_field_ids=tuple(
                            contract.field_id
                            for contract in contracts
                            if contract.field_id in combined_failed_field_ids
                        ),
                        port=port,
                        contracts=contracts,
                        locators=locators,
                        task_key=task_key,
                    ),
                    error.reason_code,
                )
            if error.reason_code not in _STRUCTURAL_INITIAL_FAILURE_CODES:
                raise
            failure_code = error.reason_code
        else:
            duplicate_locator_fields = _duplicate_evidence_locator_field_ids(
                selections=selections,
                contracts=contracts,
            )
            if duplicate_locator_fields:
                return (
                    _locator_membership_nonpass_response(
                        response_text=response_text,
                        failed_field_ids=duplicate_locator_fields,
                        port=port,
                        contracts=contracts,
                        locators=locators,
                        task_key=task_key,
                    ),
                    "EVIDENCE_BINDING_FAILED",
                )
            return response_text, forced_unknown_failure_code
    return (
        _structural_nonpass_response(
            port=port,
            contracts=contracts,
            locators=locators,
            task_key=task_key,
        ),
        failure_code,
    )


def _shared_evidence_repair_slot_authority(
    tasks: tuple[_SharedEvidenceRepairTask, ...],
) -> _LocatorSlotAuthorityV1:
    catalog: list[_LocatorSlotCatalogEntryV1] = []
    rows: list[_FieldLocatorSlotsV1] = []
    mapping: list[tuple[str, MaterialRole, str, str]] = []
    parent_rows: list[dict[str, object]] = []
    for task in tasks:
        authority = _build_locator_slot_authority(
            port=task.port,
            contracts=task.contracts,
            locators=task.locators,
        )
        if tuple(item.field_id for item in task.contracts) != task.repair_plan.field_ids:
            raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
        approved_by_field = {
            item.field_id: item.locator_refs
            for item in task.repair_plan.approved_locators
        }
        full_mapping = {
            (field_id, role, slot): locator_ref
            for field_id, role, slot, locator_ref in authority.code_mapping
        }
        contract_by_field = {item.field_id: item for item in task.contracts}
        source_by_role = task.port._source_by_role()
        initial_refs_by_field_role: dict[
            tuple[str, MaterialRole], tuple[str, ...]
        ] = {}
        for output in task.execution.initial_outputs:
            contract = contract_by_field.get(output.field_id)
            if contract is None:
                continue
            refs_by_role: dict[MaterialRole, list[str]] = {}
            for evidence in output.evidence:
                roles = tuple(
                    role
                    for role, refs in contract.source_locator_refs
                    if evidence.source_revision_id
                    == source_by_role[role].document.subject.source_revision_id
                    and evidence.locator.subject_ref in refs
                )
                if len(roles) != 1:
                    raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
                role = roles[0]
                refs_by_role.setdefault(role, []).append(evidence.locator.subject_ref)
            initial_refs_by_field_role.update(
                {
                    (output.field_id, role): tuple(refs)
                    for role, refs in refs_by_role.items()
                }
            )
        selected_rows: list[tuple[str, tuple[tuple[MaterialRole, str, str], ...]]] = []
        for row in authority.field_locator_slots:
            selected_sources: list[tuple[MaterialRole, str, str]] = []
            for source in row.sources:
                retained_refs = set(
                    initial_refs_by_field_role.get(
                        (row.field_id, source.source_role), ()
                    )
                )
                slot = next(
                    (
                        candidate
                        for candidate in source.allowed_slots
                        if full_mapping.get(
                            (row.field_id, source.source_role, candidate)
                        )
                        in retained_refs
                    ),
                    source.allowed_slots[0],
                )
                locator_ref = full_mapping.get((row.field_id, source.source_role, slot))
                if locator_ref not in approved_by_field.get(row.field_id, ()):
                    raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
                selected_sources.append((source.source_role, slot, locator_ref))
            if not selected_sources:
                raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
            selected_rows.append((row.field_id, tuple(selected_sources)))
        catalog_by_original_slot = {item.slot: item for item in authority.catalog}
        for field_ordinal, (field_id, sources) in enumerate(
            selected_rows,
            start=len(rows) + 1,
        ):
            local_sources: list[_FieldRoleSlotsV1] = []
            for locator_ordinal, (role, original_slot, locator_ref) in enumerate(
                sources,
                start=1,
            ):
                original = catalog_by_original_slot.get(original_slot)
                if original is None:
                    raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
                local_alias = (
                    f"field-{field_ordinal:04d}-locator-{locator_ordinal:04d}"
                )
                catalog.append(
                    _LocatorSlotCatalogEntryV1(
                        slot=local_alias,
                        locator_kind=original.locator_kind,
                        page_number=original.page_number,
                        content_snapshot=original.content_snapshot,
                        content_snapshot_sha256=original.content_snapshot_sha256,
                    )
                )
                local_sources.append(
                    _FieldRoleSlotsV1(
                        source_role=role,
                        allowed_slots=(local_alias,),
                    )
                )
                mapping.append((field_id, role, local_alias, locator_ref))
            rows.append(
                _FieldLocatorSlotsV1(
                    field_id=field_id,
                    sources=tuple(local_sources),
                )
            )
        parent_rows.append(
            {
                "task_index": task.index,
                "task_id": task.port.task_id,
                "attempt_hash": task.port.attempt_hash,
                "repair_plan_sha256": task.repair_plan.plan_hash,
                "children": tuple(
                    _schema67_repair_child_identity(item) for item in task.children
                ),
            }
        )
    task_id = canonical_hash(
        "schema67-shared-evidence-repair-task.v1",
        tuple(parent_rows),
    )
    attempt_hash = canonical_hash(
        "schema67-shared-evidence-repair-attempt.v1",
        tuple(
            {
                "task_id": item["task_id"],
                "attempt_hash": item["attempt_hash"],
                "repair_plan_sha256": item["repair_plan_sha256"],
            }
            for item in parent_rows
        ),
    )
    payload = {
        "task_id": task_id,
        "attempt_hash": attempt_hash,
        "policy_sha256": LOCATOR_SLOT_POLICY_SHA256,
        "catalog": tuple(item.model_dump(mode="python") for item in catalog),
        "field_locator_slots": tuple(item.model_dump(mode="python") for item in rows),
        "code_mapping": tuple(mapping),
    }
    return _LocatorSlotAuthorityV1(
        task_id=task_id,
        attempt_hash=attempt_hash,
        catalog=tuple(catalog),
        field_locator_slots=tuple(rows),
        code_mapping=tuple(mapping),
        authority_sha256=canonical_hash(
            _LOCATOR_SLOT_AUTHORITY_OBJECT_TYPE,
            payload,
        ),
    )


def _prepare_shared_evidence_repair(
    *,
    prepared: tuple[Schema67PreparedTaskV1, ...],
    ports: tuple[_Schema67EvidenceBindingPort, ...],
    locators_by_task: tuple[tuple[CanonicalLocatorInputV1, ...], ...],
    executions: tuple[DeepSeekTaskExecutionV1, ...],
    parent_response_sha256s: tuple[str, ...],
    structural_failure_codes: tuple[str | None, ...] | None = None,
) -> tuple[_SharedEvidenceRepairContext, ...]:
    exact_failure_codes = structural_failure_codes or (None,) * 8
    if not (
        len(prepared)
        == len(ports)
        == len(locators_by_task)
        == len(executions)
        == len(parent_response_sha256s)
        == len(exact_failure_codes)
        == 8
    ):
        raise DeepSeekCompilerError("SCHEMA67_BATCH_AUTHORITY_INVALID")
    tasks: list[_SharedEvidenceRepairTask] = []
    for index, (task, port, locators, execution) in enumerate(
        zip(prepared, ports, locators_by_task, executions, strict=True)
    ):
        contracts = tuple(task.field_prompts)
        if not isinstance(execution.initial, Schema67BoundAttemptV1):
            raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
        children = _schema67_repair_children(
            initial=execution.initial,
            locator_refs=tuple(
                (item.field_id, item.allowed_locator_refs) for item in contracts
            ),
        )
        if not children:
            continue
        unresolved = {
            field_id
            for child in children
            for field_id in child.request.field_ids
        }
        repair_contracts = tuple(
            item for item in contracts if item.field_id in unresolved
        )
        field_ids = tuple(item.field_id for item in repair_contracts)
        if not field_ids or set(field_ids) != unresolved:
            raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
        aggregate_plan = TargetedRepairPlanV1(
            contract="targeted-repair-plan.v1",
            parent_verification_hash=_shared_repair_parent_hash(children),
            repair_number=1,
            field_ids=field_ids,
            approved_locators=tuple(
                ApprovedLocatorSetV1(
                    field_id=item.field_id,
                    locator_refs=item.allowed_locator_refs,
                )
                for item in repair_contracts
            ),
        )
        tasks.append(
            _SharedEvidenceRepairTask(
                index=index,
                port=port,
                contracts=repair_contracts,
                locators=locators,
                execution=execution,
                children=children,
                repair_plan=aggregate_plan,
            )
        )
    contexts: list[_SharedEvidenceRepairContext] = []
    for repair_task in tasks:
        exact_tasks = (repair_task,)
        contracts = repair_task.contracts
        field_ids = tuple(item.field_id for item in contracts)
        slot_authority = _shared_evidence_repair_slot_authority(exact_tasks)
        if not isinstance(repair_task.execution.initial, Schema67BoundAttemptV1):
            raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
        schema_initial = repair_task.execution.initial
        failure_reasons = tuple(
            {
                "field_id": field_id,
                "reason_code": (
                    exact_failure_codes[repair_task.index]
                    or next(
                        item.reason_codes[0]
                        for batch in schema_initial.verification_batches
                        for item in batch.results
                        if item.field_id == field_id and item.status != "PASS"
                    )
                ),
            }
            for field_id in field_ids
        )
        system = _extractor_system_prompt(
            task_key_required=True,
            exact_literal_quotes=True,
            locator_context_name="field_local_contexts",
        )
        contract_payloads = tuple(
            _request_field_contract_payload(item) for item in contracts
        )
        payload = {
            "task_key": _SHARED_EVIDENCE_REPAIR_TASK_KEY,
            "repair_kind": "evidence",
            "repair_number": 1,
            "task_id": slot_authority.task_id,
            "attempt_hash": slot_authority.attempt_hash,
            "model_identity_sha256": DEEPSEEK_EXECUTION_IDENTITY_SHA256,
            "normalizer_identity_sha256": DEEPSEEK_NORMALIZER_IDENTITY_SHA256,
            "schema_rows_sha256": APPROVED_SCHEMA_ROWS_SHA256,
            "locator_slot_policy_sha256": LOCATOR_SLOT_POLICY_SHA256,
            "locator_slot_authority_sha256": slot_authority.authority_sha256,
            "field_local_contexts": _field_local_repair_contexts(
                contract_payloads=contract_payloads,
                failure_reasons=failure_reasons,
                catalog=slot_authority.catalog,
                field_locator_slots=slot_authority.field_locator_slots,
            ),
            "field_ids": field_ids,
            "parent_attempts": tuple(
                {
                    "task_index": repair_task.index,
                    "task_id": repair_task.port.task_id,
                    **_schema67_repair_child_identity(child),
                    "parent_bound_attempt_hash": child.request.parent_bound_attempt_hash,
                    "parent_response_sha256": parent_response_sha256s[
                        repair_task.index
                    ],
                }
                for child in repair_task.children
            ),
            "response_contract": _extractor_response_contract(
                contracts=contracts,
                task_key=_SHARED_EVIDENCE_REPAIR_TASK_KEY,
                exact_literal_quotes=True,
                locator_context_name="field_local_contexts",
            ),
        }
        contexts.append(
            _SharedEvidenceRepairContext(
                tasks=exact_tasks,
                contracts=contracts,
                slot_authority=slot_authority,
                system=system,
                user=_canonical_bytes(payload).decode("utf-8"),
            )
        )
    return tuple(contexts)


def _bind_shared_synthesis_repair(
    *,
    task: _SharedEvidenceRepairTask,
    repair_outputs: tuple[FreeformFieldOutputV1, ...],
) -> Schema67RepairBindingV1:
    if not isinstance(task.execution.initial, Schema67BoundAttemptV1):
        raise DeepSeekCompilerError("REPAIR_BINDING_FAILED")
    repair_by_field = {item.field_id: item for item in repair_outputs}
    if tuple(repair_by_field) != task.repair_plan.field_ids:
        raise DeepSeekCompilerError("REPAIR_BINDING_FAILED")
    complete_outputs = tuple(
        repair_by_field.get(item.field_id, item)
        for item in task.execution.initial_outputs
    )
    try:
        receipts, repaired_batches, chains = task.port._bind_outputs(
            complete_outputs,
            exact_literal_quotes=True,
        )
    except Exception:
        raise DeepSeekCompilerError("REPAIR_BINDING_FAILED") from None
    results_by_field: dict[str, list[FieldVerificationV1]] = {}
    for batch in repaired_batches:
        for result in batch.results:
            if result.field_id in repair_by_field:
                results_by_field.setdefault(result.field_id, []).append(result)
    aggregate_results: list[FieldVerificationV1] = []
    nonpass: set[str] = set()
    for field_id in task.repair_plan.field_ids:
        exact_results = tuple(results_by_field.get(field_id, ()))
        if not exact_results:
            raise DeepSeekCompilerError("REPAIR_BINDING_FAILED")
        selected = next(
            (item for item in exact_results if item.status != "PASS"),
            exact_results[0],
        )
        aggregate_results.append(selected)
        if selected.status != "PASS":
            nonpass.add(field_id)
    final_repair_outputs = tuple(
        item.model_copy(
            update={"state": "unknown", "value_snapshot": None, "evidence": ()}
        )
        if item.field_id in nonpass
        else item
        for item in repair_outputs
    )
    receipt_by_field = {item.field_id: item for item in receipts}
    resolution = RepairResolutionV1(
        contract="targeted-repair-resolution.v1",
        parent_verification_hash=task.repair_plan.parent_verification_hash,
        repair_plan_hash=task.repair_plan.plan_hash,
        results=tuple(aggregate_results),
        gaps=tuple(
            GapV1(field_id=item.field_id, reason_codes=item.reason_codes)
            for item in aggregate_results
            if item.status != "PASS"
        ),
        review_items=tuple(
            EvidenceReviewItemV1(
                field_id=item.field_id,
                reason_code=item.reason_codes[0],
                parent_verification_hash=task.repair_plan.parent_verification_hash,
            )
            for item in aggregate_results
            if item.status != "PASS"
        ),
    )
    return Schema67RepairBindingV1(
        resolution=resolution,
        outputs=final_repair_outputs,
        evidence_receipts=tuple(
            receipt_by_field[item.field_id] for item in final_repair_outputs
        ),
        verification_batches=repaired_batches,
        receipt_chains=chains,
    )


def _shared_repaired_execution(
    *,
    task: _SharedEvidenceRepairTask,
    repair_outputs: tuple[FreeformFieldOutputV1, ...],
    field_failure_reasons: tuple[tuple[str, str], ...],
    repair_request_sha256: str,
    accepted_response_sha256: str,
) -> DeepSeekTaskExecutionV1:
    repair_output_by_field = {item.field_id: item for item in repair_outputs}
    try:
        canonical_repair_outputs = tuple(
            repair_output_by_field[field_id] for field_id in task.repair_plan.field_ids
        )
    except KeyError:
        raise DeepSeekCompilerError("REPAIR_BINDING_FAILED") from None
    if task.port.prepared.task_kind == "material" and len(task.children) == 1:
        request = task.children[0].request
        binding_bytes = _canonical_bytes(
            {
                "task_id": task.port.task_id,
                "attempt_hash": request.attempt_hash,
                "arm_blueprint_hash": task.port.arm_blueprint_hash,
                "model_identity_sha256": task.port.model_identity_sha256,
                "fields": tuple(
                    item.model_dump(mode="python")
                    for item in canonical_repair_outputs
                ),
            }
        )
        try:
            repaired = task.port.bind_repair_exact_literal(binding_bytes, request)
        except Exception:
            raise DeepSeekCompilerError("REPAIR_BINDING_FAILED") from None
    else:
        repaired = _bind_shared_synthesis_repair(
            task=task,
            repair_outputs=canonical_repair_outputs,
        )
    if field_failure_reasons:
        reason_by_field = dict(field_failure_reasons)
        result_field_ids = {item.field_id for item in repaired.resolution.results}
        if (
            len(reason_by_field) != len(field_failure_reasons)
            or not set(reason_by_field).issubset(task.repair_plan.field_ids)
            or not set(reason_by_field).issubset(result_field_ids)
        ):
            raise DeepSeekCompilerError("REPAIR_BINDING_FAILED")
        results = tuple(
            item.model_copy(
                update={"status": "FAIL", "reason_codes": (reason_by_field[item.field_id],)}
            )
            if item.field_id in reason_by_field
            else item
            for item in repaired.resolution.results
        )
        unresolved = tuple(item for item in results if item.status != "PASS")
        repaired = repaired.model_copy(
            update={
                "resolution": RepairResolutionV1(
                    contract="targeted-repair-resolution.v1",
                    parent_verification_hash=(
                        repaired.resolution.parent_verification_hash
                    ),
                    repair_plan_hash=repaired.resolution.repair_plan_hash,
                    results=results,
                    gaps=tuple(
                        GapV1(field_id=item.field_id, reason_codes=item.reason_codes)
                        for item in unresolved
                    ),
                    review_items=tuple(
                        EvidenceReviewItemV1(
                            field_id=item.field_id,
                            reason_code=item.reason_codes[0],
                            parent_verification_hash=(
                                repaired.resolution.parent_verification_hash
                            ),
                        )
                        for item in unresolved
                    ),
                )
            }
        )
    repair_plan = task.repair_plan
    if repaired.resolution.repair_plan_hash != repair_plan.plan_hash:
        raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
    repaired_by_field = {item.field_id: item for item in repaired.outputs}
    final_outputs = tuple(
        repaired_by_field.get(item.field_id, item) for item in task.execution.final_outputs
    )
    evidence_by_field = {item.field_id: item for item in task.execution.evidence_receipts}
    evidence_by_field.update({item.field_id: item for item in repaired.evidence_receipts})
    evidence_receipts = tuple(evidence_by_field[item.field_id] for item in final_outputs)
    trace_values = {
        "contract": "schema67-evidence-repair-trace.v2",
        "kind": "evidence_repair",
        "repair_request_sha256": repair_request_sha256,
        "accepted_response_sha256": accepted_response_sha256,
        "repair_plan_sha256": repair_plan.plan_hash,
        "parent_bound_attempt_hash": task.execution.initial.bound_attempt_hash,
        "repair_plan": repair_plan.model_dump(mode="python", exclude={"plan_hash"}),
        "verifier_resolution": repaired.resolution.model_dump(
            mode="python", exclude={"resolution_hash"}
        ),
    }
    evidence_repair = EvidenceRepairTraceV2.model_validate(
        {
            **trace_values,
            "trace_hash": canonical_hash(
                "schema67-evidence-repair-trace.v2",
                trace_values,
            ),
        }
    )
    receipt_values = task.execution.receipt.model_dump(
        mode="python",
        exclude={"receipt_hash"},
    )
    receipt_values.update(
        {
            "evidence_repair_summary": _evidence_repair_summary(evidence_repair).model_dump(
                mode="python"
            ),
            "evidence_demotion": None,
            "final_outputs_sha256": _outputs_sha256(final_outputs),
            "evidence_receipt_hashes": tuple(item.receipt_hash for item in evidence_receipts),
            "repair_calls": 1,
            "evidence_repairs": 1,
            "total_calls": 2,
        }
    )
    receipt = DeepSeekExecutionReceiptV1.model_validate(
        {
            **receipt_values,
            "receipt_hash": canonical_hash(
                _EXECUTION_RECEIPT_OBJECT_TYPE,
                receipt_values,
            ),
        }
    )
    return DeepSeekTaskExecutionV1(
        initial=task.execution.initial,
        initial_outputs=task.execution.initial_outputs,
        final_outputs=final_outputs,
        evidence_receipts=evidence_receipts,
        response_contract_repair=None,
        evidence_repair=evidence_repair,
        evidence_demotion=None,
        receipt=receipt,
    )


_FIELD_LOCAL_REPAIR_FAILURE_CODES: Final[frozenset[str]] = frozenset(
    {
        "EXTRACTOR_FIELD_ITEM_SHAPE_INVALID",
        "EXTRACTOR_STRING_CONSTRAINT_INVALID",
        "EXTRACTOR_FORCED_UNKNOWN_INVALID",
    }
)


def _unknown_extractor_selection(field_id: str) -> _ExtractorFieldSelectionV1:
    return _ExtractorFieldSelectionV1(
        field_id=field_id,
        state="unknown",
        value_snapshot=None,
        evidence=(),
    )


def _require_shared_repair_envelope(
    payload: object,
    *,
    contracts: tuple[DeepSeekFieldPromptInputV1, ...],
    slot_authority: _LocatorSlotAuthorityV1,
) -> tuple[
    tuple[_ExtractorFieldSelectionV1, ...],
    tuple[tuple[str, str], ...],
]:
    """Keep closed batch identity while projecting only identifiable field failures."""

    if type(payload) is not dict or set(payload) != {"task_key", "fields"}:
        raise DeepSeekCompilerError("EXTRACTOR_TOP_LEVEL_SHAPE_INVALID")
    if payload["task_key"] != _SHARED_EVIDENCE_REPAIR_TASK_KEY:
        raise DeepSeekCompilerError("EXTRACTOR_TOP_LEVEL_SHAPE_INVALID")
    raw_fields = payload["fields"]
    if type(raw_fields) is not list or len(raw_fields) != len(contracts):
        raise DeepSeekCompilerError("EXTRACTOR_FIELD_COUNT_OR_SET_INVALID")
    expected_field_ids = tuple(item.field_id for item in contracts)
    field_ids: list[str] = []
    for raw_field in raw_fields:
        if type(raw_field) is not dict:
            raise DeepSeekCompilerError("EXTRACTOR_FIELD_ITEM_SHAPE_INVALID")
        field_id = raw_field.get("field_id")
        if not _is_extractor_string(field_id):
            raise DeepSeekCompilerError("EXTRACTOR_STRING_CONSTRAINT_INVALID")
        field_ids.append(cast(str, field_id))
    if len(field_ids) != len(set(field_ids)) or set(field_ids) != set(expected_field_ids):
        raise DeepSeekCompilerError("EXTRACTOR_FIELD_COUNT_OR_SET_INVALID")
    if tuple(field_ids) != expected_field_ids:
        raise DeepSeekCompilerError("EXTRACTOR_FIELD_ORDER_INVALID")

    selections: list[_ExtractorFieldSelectionV1] = []
    failures: list[tuple[str, str]] = []
    for raw_field, contract in zip(raw_fields, contracts, strict=True):
        try:
            exact = _require_extractor_envelope(
                {
                    "task_key": _SHARED_EVIDENCE_REPAIR_TASK_KEY,
                    "fields": [raw_field],
                },
                contracts=(contract,),
                slot_authority=slot_authority,
                task_key=_SHARED_EVIDENCE_REPAIR_TASK_KEY,
            )
            if _duplicate_evidence_locator_field_ids(
                selections=exact,
                contracts=(contract,),
            ):
                raise _LocatorMembershipFailure((contract.field_id,))
        except DeepSeekCompilerError as error:
            if not isinstance(error, _LocatorMembershipFailure) and (
                error.reason_code not in _FIELD_LOCAL_REPAIR_FAILURE_CODES
            ):
                raise
            selections.append(_unknown_extractor_selection(contract.field_id))
            failures.append((contract.field_id, error.reason_code))
        else:
            selections.extend(exact)
    return tuple(selections), tuple(failures)


def _apply_shared_evidence_repair(
    *,
    context: _SharedEvidenceRepairContext,
    repair_text: str,
    repair_json: object,
    executions: tuple[DeepSeekTaskExecutionV1, ...],
) -> tuple[DeepSeekTaskExecutionV1, ...]:
    selections, field_failure_reasons = _require_shared_repair_envelope(
        repair_json,
        contracts=context.contracts,
        slot_authority=context.slot_authority,
    )
    selection_by_field = {item.field_id: item for item in selections}
    reason_by_field = dict(field_failure_reasons)
    repair_request_sha256 = _request_sha256(
        system=context.system,
        user=context.user,
    )
    accepted_response_sha256 = _sha256_text(repair_text)
    updated = list(executions)
    for task in context.tasks:
        task_selections = tuple(selection_by_field[item.field_id] for item in task.contracts)
        repair_outputs = task.port.hydrate_extractor_outputs(
            selections=task_selections,
            contracts=task.contracts,
            locators=task.locators,
        )
        updated[task.index] = _shared_repaired_execution(
            task=task,
            repair_outputs=repair_outputs,
            field_failure_reasons=tuple(
                (field_id, reason_by_field[field_id])
                for field_id in task.repair_plan.field_ids
                if field_id in reason_by_field
            ),
            repair_request_sha256=repair_request_sha256,
            accepted_response_sha256=accepted_response_sha256,
        )
    return tuple(updated)


async def _run_schema67_deepseek_batch(
    *,
    profile: ModelProfile,
    policy: ProductionModelPolicy,
    transport: ModelClient,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    role_inputs: Sequence[Schema67RoleTaskInputV1],
    admitted_sources: Sequence[AdmittedParseArtifactV1],
    locators_by_task: Sequence[Sequence[CanonicalLocatorInputV1]],
    _single_pass_mvp: bool = False,
    _allow_evidence_repair: bool = False,
    _selection_authority: tuple[
        Schema67SelectionCatalog815V1,
        tuple[NativePdfSelectionProjection815V1, ...],
    ]
    | None = None,
) -> Schema67BatchExecutionV1:
    """Execute the one exact Schema67 batch with a code-owned shared budget."""

    if _selection_authority is not None:
        selection_catalog, source_projections = _selection_authority
        executable_field_ids = {
            field_id for task in execution_plan.task_slices for field_id in task.field_ids
        }
        expected_field_ids = tuple(
            item.field_id
            for item in field_contracts.contracts
            if item.field_id in executable_field_ids
        )
        if (
            not _single_pass_mvp
            or _allow_evidence_repair
            or selection_catalog.catalog_sha256
            != selection_catalog.recomputed_catalog_sha256()
            or selection_catalog.provider_visible_field_ids != expected_field_ids
            or tuple(item.field_id for item in selection_catalog.fields)
            != expected_field_ids
            or any(
                item.parse_manifest_sha256 != item.recomputed_manifest_sha256()
                for item in source_projections
            )
        ):
            raise DeepSeekCompilerError("SCHEMA67_SELECTION_AUTHORITY_INVALID")

    if _single_pass_mvp and _allow_evidence_repair:
        prepared = prepare_schema67_deepseek_tasks(
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            role_inputs=role_inputs,
        )
        ports = _schema67_binding_ports(
            prepared_tasks=prepared,
            role_inputs=role_inputs,
            admitted_sources=admitted_sources,
        )
        locator_groups = tuple(tuple(item) for item in locators_by_task)
        captured = await _capture_initial_responses(
            profile=profile,
            policy=policy,
            transport=transport,
            prepared=prepared,
            ports=ports,
            locators_by_task=locator_groups,
        )
        replay_responses, structural_failure_codes = (
            _project_captured_initial_responses(
                captured=captured,
                prepared=prepared,
                ports=ports,
                locators_by_task=locator_groups,
            )
        )
        for response_text in captured.responses:
            try:
                response_payload = json.loads(response_text)
            except json.JSONDecodeError:
                continue
            if type(response_payload) is dict and set(response_payload) != {
                "task_key",
                "fields",
            }:
                raise DeepSeekCompilerError("EXTRACTOR_TOP_LEVEL_SHAPE_INVALID")
        replay = _InitialResponseReplayTransport(
            responses=replay_responses,
            request_sha256s=captured.request_sha256s,
        )
        initial_batch = await _run_schema67_deepseek_batch(
            profile=profile,
            policy=policy,
            transport=replay,
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            role_inputs=role_inputs,
            admitted_sources=admitted_sources,
            locators_by_task=locators_by_task,
            _single_pass_mvp=True,
            _allow_evidence_repair=False,
        )
        if len(captured.responses) != 8 or replay.consumed != 8:
            raise DeepSeekCompilerError("SCHEMA67_MVP_EXACT_EIGHT_TASKS_REQUIRED")
        shared_executions = initial_batch.executions
        contexts = _prepare_shared_evidence_repair(
            prepared=prepared,
            ports=ports,
            locators_by_task=locator_groups,
            executions=shared_executions,
            parent_response_sha256s=tuple(
                _sha256_text(item) for item in captured.responses
            ),
            structural_failure_codes=structural_failure_codes,
        )
        budget = Schema67BatchBudgetV1(task_count=8, extractor_calls=8)
        for context in contexts:
            if len(context.tasks) != 1:
                raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
            budget.claim_grouped_evidence_repair(context.tasks[0].index)
            repair_text, repair_json = await _call_json(
                transport=transport,
                system=context.system,
                user=context.user,
                budget=_Budget(),
                batch_budget=budget,
                stage="repair",
                allow_retry=False,
            )
            shared_executions = _apply_shared_evidence_repair(
                context=context,
                repair_text=repair_text,
                repair_json=repair_json,
                executions=shared_executions,
            )
        batch_receipt = build_schema67_batch_receipt(
            execution_plan=execution_plan,
            prepared_tasks=prepared,
            budget=budget,
            executions=shared_executions,
            _single_pass_mvp=False,
        )
        return Schema67BatchExecutionV1(
            executions=shared_executions,
            receipt=batch_receipt,
        )

    prepared = prepare_schema67_deepseek_tasks(
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        role_inputs=role_inputs,
    )
    ports = _schema67_binding_ports(
        prepared_tasks=prepared,
        role_inputs=role_inputs,
        admitted_sources=admitted_sources,
    )
    locator_groups = tuple(tuple(item) for item in locators_by_task)
    if len(prepared) != len(ports) or len(prepared) != len(locator_groups):
        raise DeepSeekCompilerError("SCHEMA67_BATCH_AUTHORITY_INVALID")
    if _single_pass_mvp and len(prepared) != 8:
        raise DeepSeekCompilerError("SCHEMA67_MVP_EXACT_EIGHT_TASKS_REQUIRED")
    execution_transport = transport
    if _selection_authority is not None:
        captured = await _capture_native_selection_responses_815(
            profile=profile,
            policy=policy,
            transport=transport,
            prepared=prepared,
            ports=ports,
            locators_by_task=locator_groups,
            selection_catalog=selection_catalog,
        )
        execution_transport = _InitialResponseReplayTransport(
            responses=captured.responses,
            request_sha256s=captured.request_sha256s,
        )
    budget = Schema67BatchBudgetV1()
    executions: list[DeepSeekTaskExecutionV1] = []
    for task, port, locators in zip(prepared, ports, locator_groups, strict=True):
        prompts = _require_prepared_task_execution_authority(task=task, port=port)
        executions.append(
            await _run_deepseek_task(
                profile=profile,
                policy=policy,
                transport=execution_transport,
                port=port,
                field_contracts=prompts,
                locators=locators,
                batch_budget=budget,
                execution_plan_sha256=execution_plan.execution_plan_sha256,
                task_slice_sha256=task.task_slice_sha256,
                task_key=task.task_key,
                _single_pass_mvp=_single_pass_mvp,
                _allow_evidence_repair=_allow_evidence_repair,
                _selection_authority=(
                    tuple(
                        _task_native_selection_catalog_815(
                            prompt=item,
                            catalog=selection_catalog.require_field(item.field_id),
                        )
                        for item in prompts
                    ),
                    source_projections,
                )
                if _selection_authority is not None
                else None,
            )
        )
    batch_receipt = build_schema67_batch_receipt(
        execution_plan=execution_plan,
        prepared_tasks=prepared,
        budget=budget,
        executions=tuple(executions),
        _single_pass_mvp=_single_pass_mvp and not _allow_evidence_repair,
    )
    return Schema67BatchExecutionV1(executions=tuple(executions), receipt=batch_receipt)


async def compile_schema67_deepseek_task(
    *,
    profile: ModelProfile,
    policy: ProductionModelPolicy,
    field_contracts: FieldContractSetV1,
    execution_plan: Schema67ExecutionPlanV1,
    relation_admission: RelationBoundAdmissionResultV1,
    captured_contents: Sequence[Schema67CapturedContentV1],
) -> Schema67BatchExecutionV1:
    """Execute exact Schema67; code owns source-task and locator derivation."""

    inputs = prepare_schema67_real_execution_inputs(
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        relation_admission=relation_admission,
        captured_contents=captured_contents,
    )

    client = OpenAICompatClient(
        base_url=profile.base_url,
        api_key=profile.api_key.get_secret_value(),
        model=profile.model,
        temperature=DEEPSEEK_TEMPERATURE,
        max_tokens=DEEPSEEK_MAX_TOKENS,
        timeout_s=DEEPSEEK_TIMEOUT_S,
        thinking=DEEPSEEK_THINKING,
        response_format=DEEPSEEK_RESPONSE_FORMAT,
    )
    try:
        return await _run_schema67_deepseek_batch(
            profile=profile,
            policy=policy,
            transport=client,
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            role_inputs=inputs.role_inputs,
            admitted_sources=relation_admission.admitted_parse_artifacts,
            locators_by_task=inputs.locators_by_task,
            _single_pass_mvp=True,
        )
    finally:
        await client.aclose()


__all__ = [
    "CanonicalLocatorInputV1",
    "DeepSeekCompilerError",
    "DeepSeekExecutionReceiptV1",
    "DeepSeekFieldPromptInputV1",
    "DeepSeekTaskExecutionV1",
    "DeferredFieldDisposition815V1",
    "DEEPSEEK_EXECUTION_IDENTITY_SHA256",
    "DEEPSEEK_MAX_REQUEST_BYTES",
    "DEEPSEEK_MODEL_IDENTITY",
    "DEEPSEEK_RESPONSE_FORMAT",
    "DEEPSEEK_THINKING",
    "LOCATOR_SELECTION_POLICY_SHA256",
    "Schema67BatchBudgetV1",
    "Schema67BatchExecutionReceiptV1",
    "Schema67CapturedContentV1",
    "Schema67EvidenceBindingPort",
    "Schema67ExecutionPlanV1",
    "Schema67NativePdfExecutionProjection815V1",
    "Schema67PreparedTaskV1",
    "Schema67RoleTaskInputV1",
    "Schema67TaskSliceV1",
    "SCHEMA67_APPROVED_BY",
    "SCHEMA67_WORKBOOK_SHA256",
    "build_schema67_batch_receipt",
    "build_schema67_execution_plan",
    "build_schema67_native_pdf_execution_projection_815",
    "compile_schema67_deepseek_task",
    "prepare_schema67_deepseek_tasks",
    "prepare_schema67_real_execution_inputs",
    "recover_exact_mineru_block_locators",
    "select_contract_locator_refs",
]
