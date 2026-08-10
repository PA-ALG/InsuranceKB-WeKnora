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
from collections.abc import Sequence
from dataclasses import dataclass, field
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
    FieldCandidateV1,
    FieldRuleV1,
    FreeformEvidenceBindingReceiptV1,
    FreeformEvidenceV1,
    FreeformFieldOutputV1,
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
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_BY,
    APPROVED_ORDERED_FIELD_IDS,
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
        "response_contract_repair_policy_sha256": (
            _RESPONSE_CONTRACT_REPAIR_POLICY_SHA256
        ),
        "locator_slot_policy_sha256": LOCATOR_SLOT_POLICY_SHA256,
        "fixed_dual_repair_policy": {
            "max_shared_extra_calls": 2,
            "max_transport_retries": 1,
            "max_response_contract_repairs": 1,
            "max_evidence_repairs": 1,
            "allowed_pairs": (
                "retry+response_contract_repair",
                "retry+evidence_repair",
                "response_contract_repair+evidence_repair",
            ),
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
_PROVIDER_TASK_OBJECT_TYPE: Final[str] = "schema67-deepseek-provider-task.v1"
_PROVIDER_ATTEMPT_OBJECT_TYPE: Final[str] = "schema67-deepseek-provider-attempt.v1"
_BATCH_BUDGET_OBJECT_TYPE: Final[str] = "schema67-deepseek-batch-budget.v2"
_EXECUTION_RECEIPT_OBJECT_TYPE: Final[str] = "deepseek-evidence-compiler-596-1.v2"
_BATCH_RECEIPT_OBJECT_TYPE: Final[str] = "schema67-deepseek-batch-receipt.v2"
_EVIDENCE_DEMOTION_RECEIPT_OBJECT_TYPE: Final[str] = (
    "schema67-evidence-demotion-receipt.v1"
)
_PASS_PRESERVATION_OBJECT_TYPE: Final[str] = (
    "schema67-evidence-demotion-pass-preservation.v1"
)
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
        "algorithm_version": "schema67-contract-lexical-locator-v2",
        "source": "field-contract-plus-mineru-locators",
        "contract_terms": ("field_name", "description", "category"),
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

    def __init__(self, failed_field_ids: tuple[str, ...]) -> None:
        if not failed_field_ids or len(failed_field_ids) != len(set(failed_field_ids)):
            raise DeepSeekCompilerError(
                "EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID"
            )
        self.failed_field_ids = failed_field_ids
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
            "locator_slot_catalog": tuple(
                item.model_dump(mode="python") for item in self.catalog
            ),
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
    source = " ".join((contract.field_name, contract.description, contract.category)).casefold()
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
        "description": contract.description,
        "value_shape": contract.value_shape,
        "formation_modes": contract.formation_modes,
        "source_roles": contract.source_roles,
        "evidence_required": contract.evidence_required,
        "output_state_policy": contract.output_state_policy,
        "hardness": contract.hardness.model_dump(mode="python"),
        "field_contract_sha256": contract.field_contract_sha256,
    }


class DeepSeekFieldPromptInputV1(_FrozenModel):
    """Prompt projection of one exact Lane A contract plus admitted locators."""

    contract: FieldContractV1 = Field(repr=False)
    prompt_payload_sha256: Sha256Hex
    allowed_locator_refs: tuple[NonBlankStr, ...]
    source_locator_refs: tuple[tuple[MaterialRole, tuple[NonBlankStr, ...]], ...] = ()
    requires_unknown_review: bool = False

    @property
    def field_id(self) -> str:
        return self.contract.field_id

    @model_validator(mode="after")
    def require_exact_prompt_projection(self) -> Self:
        exact = FieldContractV1.model_validate(
            self.contract.model_dump(mode="python", round_trip=True)
        )
        if (
            exact != self.contract
            or self.prompt_payload_sha256
            != canonical_hash(_FIELD_PROMPT_OBJECT_TYPE, _field_prompt_payload(exact))
            or self.allowed_locator_refs != tuple(sorted(self.allowed_locator_refs))
            or len(self.allowed_locator_refs) != len(set(self.allowed_locator_refs))
            or tuple(item[0] for item in self.source_locator_refs)
            != tuple(
                role
                for role in ("terms", "brochure", "rate_table")
                if role in self.contract.source_roles
            )
            or any(
                refs != tuple(sorted(refs)) or len(refs) != len(set(refs))
                for _, refs in self.source_locator_refs
            )
            or sum(len(refs) for _, refs in self.source_locator_refs)
            != len({ref for _, refs in self.source_locator_refs for ref in refs})
            or self.requires_unknown_review != any(not refs for _, refs in self.source_locator_refs)
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
            or len(self.field_ids) > 8
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
    max_provider_calls: Literal[10] = 10
    max_transport_retries: Literal[1] = 1
    max_shared_extra_calls: Literal[2] = 2
    max_response_contract_repairs: Literal[1] = 1
    max_evidence_repairs: Literal[1] = 1
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
        "max_provider_calls": 10,
        "max_transport_retries": 1,
        "max_shared_extra_calls": 2,
        "max_response_contract_repairs": 1,
        "max_evidence_repairs": 1,
    }
    return Schema67BatchBudgetPolicyV1(
        max_main_tasks=8,
        max_transport_retries=1,
        max_shared_extra_calls=2,
        max_response_contract_repairs=1,
        max_evidence_repairs=1,
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
            or self.field_ids != tuple(sorted(self.field_ids))
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
            self.response_contract_repair_policy_sha256
            != _RESPONSE_CONTRACT_REPAIR_POLICY_SHA256
            or not _ordered_unique_subset(self.failed_field_ids, self.field_ids)
            or (self.failure_code == "LOCATOR_NOT_ALLOWED")
            != bool(self.failed_field_ids)
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
            or any(
                item.status != "PASS" for item in self.verifier_resolution.results
            )
            or self.verifier_resolution.gaps
            or self.verifier_resolution.review_items
        ):
            raise ValueError("evidence_repair_resolution_invalid")
        payload = {
            "contract": self.contract,
            "kind": self.kind,
            "repair_request_sha256": self.repair_request_sha256,
            "accepted_response_sha256": self.accepted_response_sha256,
            "repair_plan_sha256": self.repair_plan_sha256,
            "parent_bound_attempt_hash": self.parent_bound_attempt_hash,
            "repair_plan": self.repair_plan.model_dump(
                mode="python", exclude={"plan_hash"}
            ),
            "verifier_resolution": self.verifier_resolution.model_dump(
                mode="python", exclude={"resolution_hash"}
            ),
        }
        if self.trace_hash != canonical_hash(
            "schema67-evidence-repair-trace.v2", payload
        ):
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
        if (
            len(self.repair_field_ids) != self.repair_field_count
            or len(self.repair_field_ids) != len(set(self.repair_field_ids))
        ):
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
        "repair_plan": repair.repair_plan.model_dump(
            mode="python", exclude={"plan_hash"}
        ),
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
            "summary_hash": canonical_hash(
                "schema67-evidence-repair-receipt-summary.v2", values
            ),
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
            or self.receipt_hash
            != canonical_hash(_EVIDENCE_DEMOTION_RECEIPT_OBJECT_TYPE, payload)
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
        extras = (
            self.transport_retries
            + self.response_contract_repairs
            + self.evidence_repairs
        )
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
                and not _ordered_unique_subset(
                    self.evidence_repair_summary.repair_field_ids,
                    self.field_ids,
                )
            )
            or (
                self.evidence_repair_summary is not None
                and self.evidence_repair_summary.repair_field_count
                > len(self.field_ids)
            )
            or self.locator_calls + self.extractor_calls + self.repair_calls
            != self.total_calls
            or self.total_calls != 1 + extras
            or extras > 2
            or self.locator_calls != 0
            or self.extractor_calls < 1
            or self.repair_calls
            < self.response_contract_repairs + self.evidence_repairs
            or self.extractor_calls - 1 + self.repair_calls
            - self.response_contract_repairs - self.evidence_repairs
            != self.transport_retries
            or (self.response_contract_repair is None)
            != (self.response_contract_repairs == 0)
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
            response_repair.parent_extractor_request_sha256
            != self.extractor_request_sha256
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
                checked_response_repair = (
                    ResponseContractRepairResolutionV2.model_validate(
                        self.response_contract_repair.model_dump(mode="python")
                    )
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
            or self.receipt.field_ids
            != tuple(item.field_id for item in self.initial_outputs)
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
                    or receipt_by_field[field_id].field_id
                    != final_by_field[field_id].field_id
                    or receipt_by_field[field_id].state != final_by_field[field_id].state
                    or receipt_by_field[field_id].value_snapshot
                    != final_by_field[field_id].value_snapshot
                    or receipt_by_field[field_id].evidence
                    != final_by_field[field_id].evidence
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
            matching_batches = tuple(
                item
                for item in self.initial.verification_batches
                if item.verification_hash == plan.parent_verification_hash
            )
            if len(matching_batches) != 1:
                raise ValueError("deepseek_evidence_repair_custody_mismatch")
            initial_results = matching_batches[0].results
            unresolved_fields = tuple(
                item.field_id for item in initial_results if item.status != "PASS"
            )
            repaired_results = evidence_repair.verifier_resolution.results
            if (
                tuple(item.field_id for item in initial_results)
                != tuple(sorted(self.receipt.field_ids))
                or plan.field_ids != unresolved_fields
                or tuple(item.field_id for item in repaired_results)
                != tuple(item.field_id for item in initial_results)
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
    evidence_repairs: Literal[0, 1]
    repair_calls: Annotated[StrictInt, Field(ge=0, le=2)]
    provider_calls: Annotated[StrictInt, Field(ge=1, le=10)]
    prior_provider_calls: Literal[2] | None = None
    cumulative_provider_calls: Literal[10] | None = None
    task_receipt_hashes: tuple[Sha256Hex, ...]
    batch_receipt_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_batch_receipt(self) -> Self:
        payload = self.model_dump(mode="python", exclude={"batch_receipt_sha256"})
        extras = (
            self.transport_retries
            + self.response_contract_repairs
            + self.evidence_repairs
        )
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
            or extras > 2
            or cumulative_values != ((2, 10) if single_pass_mvp else (None, None))
            or self.batch_receipt_sha256
            != _batch_receipt_sha256(payload)
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

    @property
    def identity_sha256(self) -> str:
        return _batch_budget_policy().budget_identity_sha256

    def start_task(self) -> None:
        if self.task_count >= 8:
            raise DeepSeekCompilerError("BATCH_MAIN_TASK_BUDGET_EXHAUSTED")
        self.task_count += 1

    def record_call(self, stage: Literal["extractor", "repair"]) -> None:
        if self.extractor_calls + self.repair_calls >= 10:
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

    @property
    def extra_calls(self) -> int:
        return (
            self.transport_retries
            + self.response_contract_repairs
            + self.evidence_repairs
        )


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
        or budget.repair_calls != sum(item.receipt.repair_calls for item in exact_executions)
        or budget.transport_retries
        != sum(item.receipt.transport_retries for item in exact_executions)
        or budget.response_contract_repairs
        != sum(item.receipt.response_contract_repairs for item in exact_executions)
        or budget.evidence_repairs
        != sum(item.receipt.evidence_repairs for item in exact_executions)
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
    already_unknown = {
        item.field_id for item in initial.outputs if item.state == "unknown"
    }
    seen: set[str] = set()
    nonpass: set[str] = set()
    for batch, chain in zip(
        initial.verification_batches, initial.receipt_chains, strict=True
    ):
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
    if seen != allowed:
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
    demoted_field_ids = _verification_nonpass_scope(initial, field_ids)
    if not demoted_field_ids:
        return initial_outputs, initial.evidence_receipts, None
    demoted = set(demoted_field_ids)
    final_outputs = tuple(
        item.model_copy(
            update={"state": "unknown", "value_snapshot": None, "evidence": ()}
        )
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
        "final_evidence_receipt_hashes": tuple(
            item.receipt_hash for item in final_receipts
        ),
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
            "receipt_hash": canonical_hash(
                _EVIDENCE_DEMOTION_RECEIPT_OBJECT_TYPE, values
            ),
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
    slices: list[Schema67TaskSliceV1] = []
    for role in supported:
        fields = material_fields[role]
        for offset in range(0, len(fields), 8):
            chunk = tuple(fields[offset : offset + 8])
            slices.append(
                _task_slice(
                    task_key=f"{role}-{offset // 8 + 1:02d}",
                    task_kind="material",
                    material_roles=(role,),
                    field_ids=chunk,
                )
            )
    if multi_fields:
        slices.append(
            _task_slice(
                task_key="multi-source-01",
                task_kind="synthesis",
                material_roles=tuple(role for role in supported if role in multi_roles),
                field_ids=tuple(multi_fields),
            )
        )
    budget = _batch_budget_policy()
    payload = {
        "contract_set_sha256": exact.contract_set_sha256,
        "task_slices": tuple(item.model_dump(mode="python") for item in slices),
        "deferred_unknown_field_ids": tuple(deferred),
        "batch_budget": budget.model_dump(mode="python"),
    }
    try:
        return Schema67ExecutionPlanV1(
            contract_set_sha256=exact.contract_set_sha256,
            task_slices=tuple(slices),
            deferred_unknown_field_ids=tuple(deferred),
            batch_budget=budget,
            execution_plan_sha256=canonical_hash(_EXECUTION_PLAN_OBJECT_TYPE, payload),
        )
    except ValueError:
        raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID") from None


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
    expected_plan = build_schema67_execution_plan(exact_set)
    if plan != expected_plan:
        raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID")
    executable = tuple(field_id for item in plan.task_slices for field_id in item.field_ids)
    deferred = plan.deferred_unknown_field_ids
    ordered = APPROVED_ORDERED_FIELD_IDS
    contract_by_id = {item.field_id: item for item in exact_set.contracts}
    combined = set(executable) | set(deferred)
    if (
        len(plan.task_slices) > plan.batch_budget.max_main_tasks
        or len(executable) != len(set(executable))
        or len(deferred) != len(set(deferred))
        or set(executable).intersection(deferred)
        or combined != set(ordered)
        or tuple(item for item in ordered if item in deferred) != deferred
        or any(
            set(contract_by_id[field_id].source_roles).intersection(
                {"terms", "brochure", "rate_table"}
            )
            for field_id in deferred
        )
    ):
        raise DeepSeekCompilerError("SCHEMA67_FIELD_PARTITION_INVALID")
    try:
        inputs = tuple(role_inputs)
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
            prompts = tuple(
                DeepSeekFieldPromptInputV1(
                    contract=contract_by_id[field_id],
                    prompt_payload_sha256=canonical_hash(
                        _FIELD_PROMPT_OBJECT_TYPE,
                        _field_prompt_payload(contract_by_id[field_id]),
                    ),
                    allowed_locator_refs=tuple(
                        sorted(
                            {ref for refs in allowed_by_field[field_id].values() for ref in refs}
                        )
                    ),
                    source_locator_refs=tuple(
                        (
                            role,
                            allowed_by_field[field_id].get(role, ()),
                        )
                        for role in ("terms", "brochure", "rate_table")
                        if role in contract_by_id[field_id].source_roles
                    ),
                    requires_unknown_review=any(
                        not allowed_by_field[field_id].get(role, ())
                        for role in ("terms", "brochure", "rate_table")
                        if role in contract_by_id[field_id].source_roles
                    ),
                )
                for field_id in task_slice.field_ids
            )
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
            sources.append(
                _FieldRoleSlotsV1(source_role=source_role, allowed_slots=slots)
            )
            mapping.extend(
                (contract.field_id, source_role, slot_by_ref[ref], ref) for ref in refs
            )
        if not sources and not contract.requires_unknown_review:
            raise DeepSeekCompilerError("LOCATOR_SLOT_AUTHORITY_INVALID")
        field_rows.append(
            _FieldLocatorSlotsV1(field_id=contract.field_id, sources=tuple(sources))
        )
    authority_payload = {
        "task_id": port.task_id,
        "attempt_hash": port.attempt_hash,
        "policy_sha256": LOCATOR_SLOT_POLICY_SHA256,
        "catalog": tuple(item.model_dump(mode="python") for item in catalog),
        "field_locator_slots": tuple(
            item.model_dump(mode="python") for item in field_rows
        ),
        "code_mapping": tuple(mapping),
    }
    authority = _LocatorSlotAuthorityV1(
        task_id=port.task_id,
        attempt_hash=port.attempt_hash,
        catalog=catalog,
        field_locator_slots=tuple(field_rows),
        code_mapping=tuple(mapping),
        authority_sha256=canonical_hash(
            _LOCATOR_SLOT_AUTHORITY_OBJECT_TYPE, authority_payload
        ),
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
    for contract, field_row in zip(
        contracts, authority.field_locator_slots, strict=True
    ):
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
                if item is None or catalog_item is None or not (
                    catalog_item.locator_kind == item.locator_kind
                    and catalog_item.page_number == item.page_number
                    and catalog_item.content_snapshot == item.content_snapshot
                    and catalog_item.content_snapshot_sha256
                    == item.content_snapshot_sha256
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
            raise _ModelResponseDecodeFailure(
                immediate_reason_code, _sha256_text(output)
            )
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
) -> tuple[_ExtractorFieldSelectionV1, ...]:
    if type(payload) is not dict or set(payload) != {"fields"}:
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
        if len(evidence_keys) != len(set(evidence_keys)):
            raise DeepSeekCompilerError("EXTRACTOR_FIELD_ITEM_SHAPE_INVALID")
        required_roles = {
            role for role, refs in contract.source_locator_refs if refs
        }
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
            tuple(field_id for field_id in expected_field_ids if field_id in failed_field_ids)
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
            locator_ref
            for _role, refs in contract.source_locator_refs
            for locator_ref in refs
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
                raise DeepSeekCompilerError(
                    "EXTRACTOR_CODE_OWNED_AUTHORITY_MISMATCH_INVALID"
                )
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
) -> dict[str, object]:
    field_ids = tuple(item.field_id for item in contracts)
    return {
        "output_contract": "schema67-semantic-field-selection.v2",
        "top_level": {
            "required_keys": ("fields",),
            "additional_properties": False,
        },
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
                "constraint": ("nonblank_literal_substring_after_exact_057_normalization"),
                **_EXTRACTOR_STRING_CONSTRAINT.visible_contract(),
            },
            "uniqueness": "unique_source_role_locator_slot_quote_snapshot_triples",
        },
        "present_value_057_support": {
            "state": "present",
            "normalization": "existing_057_nfkc_whitespace_punctuation_case",
            "value_quote_relation": (
                "value_snapshot_normalized_equals_at_least_one_complete_quote_snapshot"
            ),
            "required_source_roles": "all_contract_required_roles",
            "locator_authority": "same_field_field_locator_slots_only",
            "quote_authority": "literal_replay_not_semantic_paraphrase",
        },
        "forced_unknown_field_ids": tuple(
            item.field_id for item in contracts if item.requires_unknown_review
        ),
        "response_skeleton": {
            "fields": tuple(
                {
                    "field_id": field_id,
                    "state": "unknown",
                    "value_snapshot": None,
                    "evidence": (),
                }
                for field_id in field_ids
            )
        },
        "response_skeleton_usage": (
            "copy_every_row_exactly_once_in_order; skeleton_is_shape_only; "
            "replace_state_value_and_evidence_only_when_selected_locator_text_supports_it"
        ),
    }


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
    _single_pass_mvp: bool = False,
) -> DeepSeekTaskExecutionV1:
    """Execute one pre-admitted task; tests inject a fake transport, never a provider."""

    contracts, exact_locators = _preflight(
        profile=profile,
        policy=policy,
        port=port,
        field_contracts=field_contracts,
        locators=locators,
    )
    budget = _Budget()
    exact_batch_budget = batch_budget or Schema67BatchBudgetV1()
    if (execution_plan_sha256 is None) != (task_slice_sha256 is None):
        raise DeepSeekCompilerError("BATCH_EXECUTION_IDENTITY_INVALID")
    exact_batch_budget.start_task()
    contract_payload = tuple(
        {
            "field_id": item.field_id,
            "field_contract_sha256": item.contract.field_contract_sha256,
            "prompt_payload_sha256": item.prompt_payload_sha256,
            "contract": _field_prompt_payload(item.contract),
        }
        for item in contracts
    )
    selection, locator_authority_sha256, locator_selection_sha256 = (
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
    extractor_payload = {
        "task_id": port.task_id,
        "attempt_hash": port.attempt_hash,
        "arm_blueprint_hash": port.arm_blueprint_hash,
        "model_identity_sha256": port.model_identity_sha256,
        "normalizer_identity_sha256": port.normalizer_identity_sha256,
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
        ),
    }
    extractor_user = _canonical_bytes(extractor_payload).decode("utf-8")
    extractor_system = (
        "DeepSeek Extractor: return only the JSON object shaped by "
        "response_contract.response_skeleton, without Markdown, explanation, or metadata. "
        "Copy every field row exactly once in response_contract.fields.field_order and "
        "always include field_id, state, value_snapshot, and evidence. Use state unknown "
        "with value_snapshot null and evidence [] when the selected locator text does not "
        "support a value, or when field_id is forced unknown. For present or "
        "absent_explicitly, provide a nonblank value_snapshot and at least one unique "
        "Evidence item for every required source role; each locator_slot must appear "
        "under that exact field and source_role in field_locator_slots. The field_id, "
        "value_snapshot, source_role, locator_slot, and quote_snapshot strings must each "
        "be a single line between "
        f"{_EXTRACTOR_STRING_CONSTRAINT.min_length} and "
        f"{_EXTRACTOR_STRING_CONSTRAINT.max_length} characters, must not contain CR or "
        "LF, and must not have leading or trailing whitespace. "
        "Each quote_snapshot must be a "
        "nonblank literal substring of that slot's catalog content_snapshot after exact 057 "
        "normalization (NFKC, whitespace, listed punctuation, and case only), never a "
        "semantic paraphrase. For state present, the present value_snapshot must be "
        "exactly equal after the same 057 normalization to at least one quote_snapshot "
        "from that field's field_locator_slots authority. When repair_kind is "
        "response_contract, regenerate the whole "
        "object from the unchanged authority and correct the fixed reason_code without "
        "requesting or reconstructing the prior response. Never invent locator authority "
        "or add keys."
    )
    extractor_request_sha = _request_sha256(system=extractor_system, user=extractor_user)
    _require_request_size(system=extractor_system, user=extractor_user)
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
            "response_contract_repair_policy_sha256": (
                _RESPONSE_CONTRACT_REPAIR_POLICY_SHA256
            ),
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
        initial = port.bind_initial(initial_binding_bytes)
    except Exception:
        raise DeepSeekCompilerError("EVIDENCE_BINDING_FAILED") from None

    final_outputs = initial_outputs
    evidence_receipts = tuple(getattr(initial, "evidence_receipts", ()))
    evidence_demotion: EvidenceDemotionReceiptV1 | None = None
    if _single_pass_mvp:
        if not isinstance(initial, Schema67BoundAttemptV1):
            raise DeepSeekCompilerError("EVIDENCE_DEMOTION_AUTHORITY_INVALID")
        try:
            final_outputs, evidence_receipts, evidence_demotion = (
                _demote_initial_nonpass(initial, initial_outputs)
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise DeepSeekCompilerError("EVIDENCE_DEMOTION_AUTHORITY_INVALID") from None
        repair = None
    else:
        repair = port.prepare_repair(
            initial,
            tuple((item.field_id, item.allowed_locator_refs) for item in contracts),
        )
        if (
            repair is None
            and response_contract_repair is None
            and isinstance(initial, Schema67BoundAttemptV1)
        ):
            try:
                final_outputs, evidence_receipts, evidence_demotion = (
                    _demote_initial_nonpass(initial, initial_outputs)
                )
            except (KeyError, TypeError, ValueError, ValidationError):
                raise DeepSeekCompilerError(
                    "EVIDENCE_DEMOTION_AUTHORITY_INVALID"
                ) from None
    if repair is not None:
        exact_batch_budget.claim_repair("evidence")
        repair_payload = {
            **extractor_payload,
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
                                for mapped_field, mapped_role, slot, locator_ref
                                in slot_authority.code_mapping
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
            "response_contract": _extractor_response_contract(
                contracts=tuple(item for item in contracts if item.field_id in repair.field_ids),
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
            repaired = port.bind_repair(repair_binding_bytes, repair)
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
        matching_initial_verifications = (
            tuple(
                item
                for item in repair.initial.verification_batches
                if item.verification_hash == repair_plan.parent_verification_hash
            )
            if isinstance(repair.initial, Schema67BoundAttemptV1)
            else ()
        )
        initial_verification = (
            matching_initial_verifications[0]
            if len(matching_initial_verifications) == 1
            else None
        )
        if (
            repair_plan.plan_hash != repair.repair_plan_hash
            or verifier_resolution.repair_plan_hash != repair_plan.plan_hash
            or any(item.status != "PASS" for item in verifier_resolution.results)
            or verifier_resolution.gaps
            or verifier_resolution.review_items
            or (
                initial_verification is None
                and tuple(item.field_id for item in verifier_resolution.results)
                != repair_plan.field_ids
            )
            or (
                initial_verification is not None
                and (
                    repair_plan.field_ids
                    != tuple(
                        item.field_id
                        for item in initial_verification.results
                        if item.status != "PASS"
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
        repaired_by_field = {item.field_id: item for item in repair_outputs}
        final_outputs = tuple(
            repaired_by_field.get(item.field_id, item) for item in initial_outputs
        )
        evidence_repair_values = {
            "contract": "schema67-evidence-repair-trace.v2",
            "kind": "evidence_repair",
            "repair_request_sha256": _request_sha256(
                system=extractor_system, user=repair_user
            ),
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
        "response_contract_repair_policy_sha256": (
            _RESPONSE_CONTRACT_REPAIR_POLICY_SHA256
        ),
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
            None
            if evidence_demotion is None
            else evidence_demotion.model_dump(mode="python")
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


def _exact_schema67_admitted_sources(
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
        except (AttributeError, TypeError, ValueError, ValidationError):
            raise DeepSeekCompilerError("SCHEMA67_ADMITTED_SOURCE_INVALID") from None
        if (
            item.source_sha256 != document.subject.source_sha256
            or item.artifact_sha256 != document.document_hash
            or item.manifest_sha256 != manifest.manifest_hash
            or item.decision_sha256 != decision.decision_hash
            or manifest.document_hash != document.document_hash
            or decision.manifest_hash != manifest.manifest_hash
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
            AdmittedParseArtifactV1(
                role=item.role,
                source_sha256=item.source_sha256,
                artifact_sha256=item.artifact_sha256,
                document=document,
                manifest=manifest,
                decision=decision,
                manifest_sha256=item.manifest_sha256,
                decision_sha256=item.decision_sha256,
                sanitized_structure=item.sanitized_structure,
                raw_structure_sha256=item.raw_structure_sha256,
                sanitized_structure_sha256=item.sanitized_structure_sha256,
                capture_identity_sha256=item.capture_identity_sha256,
                content_snapshot_sha256=item.content_snapshot_sha256,
                material_profile_resolution=item.material_profile_resolution,
                trusted_relation_bindings=item.trusted_relation_bindings,
            )
        )
    if tuple(item.role for item in exact) != ("terms", "brochure", "rate_table"):
        raise DeepSeekCompilerError("SCHEMA67_ADMITTED_SOURCE_INVALID")
    return tuple(exact)


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
        self, outputs: tuple[FreeformFieldOutputV1, ...]
    ) -> tuple[
        tuple[FreeformEvidenceBindingReceiptV1, ...],
        tuple[VerificationBatchV1, ...],
        tuple[ReceiptChainV1, ...],
    ]:
        sources = self._source_by_role()
        prompt_by_field = {item.field_id: item for item in self.prepared.field_prompts}
        receipts: list[FreeformEvidenceBindingReceiptV1] = []
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
            if output.state != "unknown" and set(evidence_roles) != set(expected_roles):
                raise DeepSeekCompilerError("EVIDENCE_BINDING_FAILED")
            used = tuple(
                sorted(
                    (sources[role] for role in evidence_roles),
                    key=lambda item: item.document.subject.source_revision_id,
                )
            )
            receipts.append(
                bind_freeform_arm_evidence(
                    field_output=output,
                    documents=tuple(item.document for item in used),
                    manifests=tuple(item.manifest for item in used),
                )
            )

        batches: list[VerificationBatchV1] = []
        chains: list[ReceiptChainV1] = []
        output_by_field = {item.field_id: item for item in outputs}
        for task, attempt in zip(
            self.prepared.source_tasks, self.prepared.initial_attempts, strict=True
        ):
            source = next(
                item
                for item in self.admitted_sources
                if item.document.subject.source_revision_id == task.source_revision_id
            )
            scoped_outputs: list[FreeformFieldOutputV1] = []
            for field_id in task.field_ids:
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
            batch = evidence_verifier.verify_evidence_batch(
                document=source.document,
                manifest=source.manifest,
                candidates=tuple(item[0] for item in candidate_rules),
                rules=tuple(item[1] for item in candidate_rules),
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
                task=task,
                task_hash=task.task_hash,
                receipts=(attempt_receipt,),
            )
            bind_054_attempt_receipt(chain=chain, verification=batch)
            batches.append(batch)
            chains.append(chain)
        return tuple(receipts), tuple(batches), tuple(chains)

    def bind_initial(self, response_json: bytes) -> Schema67BoundAttemptV1:
        outputs = self._outputs(response_json, self.field_ids)
        receipts, batches, chains = self._bind_outputs(outputs)
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

    def prepare_repair(
        self,
        initial: BoundSemanticAttemptV1 | Schema67BoundAttemptV1,
        locator_refs: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> DeepSeekRepairRequestV1 | None:
        if not isinstance(initial, Schema67BoundAttemptV1) or self.prepared.task_kind != "material":
            return None
        matching_batches = tuple(
            batch
            for batch in initial.verification_batches
            if any(item.status != "PASS" for item in batch.results)
        )
        if len(matching_batches) != 1:
            raise DeepSeekCompilerError("EVIDENCE_REPAIR_FAILED")
        batch = matching_batches[0]
        unresolved = tuple(item.field_id for item in batch.results if item.status != "PASS")
        if not unresolved:
            return None
        selected = dict(locator_refs)
        if any(not selected.get(item) for item in unresolved):
            return None
        approved = tuple(
            ApprovedLocatorSetV1(field_id=item, locator_refs=selected[item]) for item in unresolved
        )
        decision = plan_targeted_repair(
            batch,
            approved_locators=approved,
            budget=RepairBudgetV1(max_targeted_repairs=1),
            repairs_used=0,
        )
        if decision.plan is None:
            return None
        attempt = build_targeted_repair(self.prepared.source_tasks[0], initial.receipt_chains[0])
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
        self, response_json: bytes, request: DeepSeekRepairRequestV1
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
        source = self.admitted_sources[0]
        candidate_rules = tuple(semantic._verification_candidate_and_rule(item) for item in outputs)
        resolution = apply_targeted_repair(
            document=source.document,
            manifest=source.manifest,
            initial=initial_batch,
            plan=request.locator_plan,
            repaired_candidates=tuple(item[0] for item in candidate_rules),
            rules=tuple(item[1] for item in candidate_rules),
        )
        receipts = tuple(
            bind_freeform_arm_evidence(
                field_output=output,
                documents=() if output.state == "unknown" else (source.document,),
                manifests=() if output.state == "unknown" else (source.manifest,),
            )
            for output in outputs
        )
        repaired_results = {item.field_id: item for item in resolution.results}
        repaired_batch = initial_batch.model_copy(
            update={"results": tuple(repaired_results[field_id] for field_id in request.field_ids)}
        )
        outcomes = tuple(
            FieldOutcomeV1(
                field_id=field_id,
                status=("candidate" if repaired_results[field_id].status == "PASS" else "unknown"),
                candidate_ref=(
                    ArtifactRefV1(
                        object_type="verified-field-candidate.v1",
                        artifact_hash=repaired_results[field_id].candidate_snapshot_hash,
                    )
                    if repaired_results[field_id].status == "PASS"
                    else None
                ),
                reason_code=(
                    None
                    if repaired_results[field_id].status == "PASS"
                    else repaired_results[field_id].reason_codes[0]
                ),
            )
            for field_id in request.field_ids
        )
        all_candidate = all(item.status == "candidate" for item in outcomes)
        receipt = build_attempt_receipt(
            request.attempt,
            field_outcomes=outcomes,
            outcome="completed" if all_candidate else "insufficient",
            reason_code=None if all_candidate else "evidence_insufficient",
        )
        old_chain = request.initial.receipt_chains[0]
        chain = ReceiptChainV1(
            task=old_chain.task,
            task_hash=old_chain.task_hash,
            receipts=(*old_chain.receipts, receipt),
        )
        bind_054_attempt_receipt(chain=chain, verification=repaired_batch)
        return Schema67RepairBindingV1(
            resolution=resolution,
            outputs=outputs,
            evidence_receipts=receipts,
            verification_batches=(repaired_batch,),
            receipt_chains=(chain,),
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
                != source.document.document_hash
                or authority.input_refs.parse_manifest.artifact_hash
                != source.manifest.manifest_hash
                or authority.input_refs.parse_quality_decision.artifact_hash
                != source.decision.decision_hash
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
) -> Schema67BatchExecutionV1:
    """Execute the one exact Schema67 batch with a code-owned shared budget."""

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
    budget = Schema67BatchBudgetV1()
    executions: list[DeepSeekTaskExecutionV1] = []
    for task, port, locators in zip(prepared, ports, locator_groups, strict=True):
        try:
            source_tasks = tuple(
                ExtractionTaskV1.model_validate(item) for item in task.source_tasks
            )
            initial_attempts = tuple(
                AttemptRequestV1.model_validate(item) for item in task.initial_attempts
            )
            prompts = tuple(
                DeepSeekFieldPromptInputV1.model_validate(item) for item in task.field_prompts
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
        executions.append(
            await _run_deepseek_task(
                profile=profile,
                policy=policy,
                transport=transport,
                port=port,
                field_contracts=prompts,
                locators=locators,
                batch_budget=budget,
                execution_plan_sha256=execution_plan.execution_plan_sha256,
                task_slice_sha256=task.task_slice_sha256,
                _single_pass_mvp=_single_pass_mvp,
            )
        )
    batch_receipt = build_schema67_batch_receipt(
        execution_plan=execution_plan,
        prepared_tasks=prepared,
        budget=budget,
        executions=tuple(executions),
        _single_pass_mvp=_single_pass_mvp,
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
    "Schema67PreparedTaskV1",
    "Schema67RoleTaskInputV1",
    "Schema67TaskSliceV1",
    "SCHEMA67_APPROVED_BY",
    "SCHEMA67_WORKBOOK_SHA256",
    "build_schema67_batch_receipt",
    "build_schema67_execution_plan",
    "compile_schema67_deepseek_task",
    "prepare_schema67_deepseek_tasks",
    "prepare_schema67_real_execution_inputs",
    "recover_exact_mineru_block_locators",
    "select_contract_locator_refs",
]
