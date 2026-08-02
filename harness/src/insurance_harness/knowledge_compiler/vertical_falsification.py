"""Dependency gate for the OpenSpec 061 596-1 falsification run."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from importlib import import_module
from importlib.util import find_spec
from typing import Final, Literal, cast

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.material_profiles import MaterialProfileResolution
from insurance_harness.compiler.parsed_documents import (
    ParsedDocumentV1,
    ParseManifestV1,
    ParseQualityDecisionV1,
)

ARM_OUTPUT_OBJECT_TYPE: Final[str] = "vertical-falsification-arm-output.v1"
APPROVED_CRITICAL18_SHA256: Final[str] = (
    "12b648d509c53b7ce1659abbf95811d437c3d22f729d46a58545f47e09bee344"
)
APPROVED_CRITICAL18_FIELDS: Final[
    tuple[tuple[Literal["P0", "P1"], str, str], ...]
] = (
    ("P0", "clause_version", "条款版本标识"),
    ("P0", "reduced_paid_up", "减额缴清"),
    ("P0", "reinstatement", "复效条款"),
    ("P0", "zh_0b3894ed2a", "产品类型"),
    ("P0", "zh_74aa1b9c93", "保证续保"),
    ("P0", "zh_d62301d84c", "宽限期"),
    ("P0", "zh_e1bea0527a", "特殊免责"),
    ("P1", "claim_filing_requirements", "理赔申请时效与申请材料"),
    ("P1", "exclusions_official", "责任免除"),
    ("P1", "external_drug_coverage", "外购药/特药责任"),
    ("P1", "waiting_period_claim_handling", "等待期内出险处理"),
    ("P1", "zh_09a5d9e54e", "保什么"),
    ("P1", "zh_3a3e6520a3", "给付限额"),
    ("P1", "zh_3d8424595d", "报销比例"),
    ("P1", "zh_4a789b1d6f", "报销范围"),
    ("P1", "zh_7d7fe38f09", "癌症医疗"),
    ("P1", "zh_7fe8603c08", "费用"),
    ("P1", "zh_f32c510a5e", "医院范围"),
)
APPROVED_CRITICAL18_FIELD_IDS: Final[tuple[str, ...]] = tuple(
    field_id for _priority, field_id, _field_name in APPROVED_CRITICAL18_FIELDS
)
APPROVED_ARM_PROFILE_SHA256: Final[str] = (
    "c64ce6227b714fb9a47fe2c15cd51349df4fccc8770fb95442aed86061f39fe3"
)
APPROVED_SEMANTIC_MODEL_ID: Final[str] = "DeepSeek V4 Flash"
APPROVED_SEMANTIC_API_BASE: Final[str] = "https://api.deepseek.com/v1"
APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256: Final[str] = (
    "accb987b2f4944ae652eba5d24e0dc2c27d2b502c3af452cd78b2cddbd1e187e"
)
APPROVED_PROMPT_IDENTITY_SHA256: Final[str] = (
    "c27cabbf154dfb91eea75f937ce96e21a42cf5305654683f04e3cd051aacbe75"
)
APPROVED_BUDGET_IDENTITY_SHA256: Final[str] = (
    "8d473c0010312d6fe0d9aef422f6952b63db679d41d7e8ec12b2962dff6e2f26"
)
APPROVED_NORMALIZER_IDENTITY_SHA256: Final[str] = (
    "37b021c6e2b43786528ca9d148a911c85e89286f0fdd3d5e6ac7158c46b611d6"
)
APPROVED_COMPARATOR_IDENTITY_SHA256: Final[str] = (
    "d8e5317bac4cee381a91c04c3e675cb8ae69610eb825f1cf5e86d222729945c1"
)
APPROVED_BASELINE_PARSER_IDENTITY_SHA256: Final[str] = (
    "af128bc04ce9d5f5996f0171d8238acd52e3c704ab71ad28fbce6b4fae043bfe"
)
APPROVED_CANDIDATE_PARSER_IDENTITY_SHA256: Final[str] = (
    "dadc77bf96d6e443d2785709513c302adb89a89c02f058b7982f558c3795445e"
)
APPROVED_PRODUCT_VERSION_ID: Final[str] = "596-1"
APPROVED_SCHEMA_VERSION: Final[str] = "v1.1+b31a411c621c"
APPROVED_SCHEMA_REGISTRY_SHA256: Final[str] = (
    "5d222c68f228d57c9061fc329f85a26191f6c847f7122f221e6aff92147b9db5"
)
APPROVED_GOLDEN_RELEASE_SHA256: Final[str] = (
    "fca06f988bf0310d12a0f6f8d0703a9476c54a5405676fb1a9b3476f91ec21d0"
)
APPROVED_GOLDEN_ARTIFACT_SHA256: Final[str] = (
    "83032da028ef227071fddac0ed422cbb9d1c2cc31e195972f9878a67d95b44ca"
)
APPROVED_GOLDEN_APPROVAL_SUBJECT_SHA256: Final[str] = (
    "6feb2acf4be1ab5ce075b662bc9c9a40024038ca2324b893d3f31b1384f7674b"
)
APPROVED_GOLDEN_596_JSONL_SHA256: Final[str] = (
    "562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb"
)
APPROVED_EVALUATOR_IDENTITY_SHA256: Final[str] = (
    "f842050a0e444e38c93104bd2220419db7d16d74ee0149c4b4ade9af0cb967f0"
)
ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID: Final[str] = (
    "061_three_admitted_parse_artifacts.v1"
)
APPROVED_MATERIAL_PROFILE_CATALOG_SHA256: Final[str] = (
    "32651266dcef2c6597b35911906b3d64408bc9c0cabe2db52472f836d519d019"
)
EXPECTED_596_1_PARSE_SOURCES: Final[
    tuple[tuple[Literal["terms", "brochure", "rate_table"], str, str], ...]
] = (
    (
        "terms",
        "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
        "596-1-terms-v1",
    ),
    (
        "brochure",
        "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
        "596-1-brochure-v1",
    ),
    (
        "rate_table",
        "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
        "596-1-rate-table-v1",
    ),
)
EXPECTED_596_1_REQUIRED_CAPABILITIES: Final[
    dict[Literal["terms", "brochure", "rate_table"], tuple[str, ...]]
] = {
    "terms": (
        "ordered_pages",
        "block_locators",
        "cross_page_sections",
        "table_grid",
        "cell_locators",
    ),
    "brochure": (
        "ordered_pages",
        "block_locators",
        "table_grid",
        "cell_locators",
    ),
    "rate_table": (
        "ordered_pages",
        "table_grid",
        "header_hierarchy",
        "row_column_indices",
        "cell_locators",
        "merged_cells",
        "cross_page_tables",
    ),
}
APPROVED_596_1_SOURCE_SHA256: Final[tuple[str, str, str]] = (
    EXPECTED_596_1_PARSE_SOURCES[0][1],
    EXPECTED_596_1_PARSE_SOURCES[1][1],
    EXPECTED_596_1_PARSE_SOURCES[2][1],
)
APPROVED_SCHEMA60_FIELD_IDS: Final[tuple[str, ...]] = (
    "zh_fd9a0b9fa3",
    "zh_1a3227c6ce",
    "zh_8bd90889d3",
    "zh_f1de0de938",
    "zh_ad4a95859a",
    "zh_0b3894ed2a",
    "zh_789479e2d4",
    "zh_346f0dac8c",
    "zh_5162df17d8",
    "zh_67ee7025ef",
    "zh_89e518b987",
    "zh_6a3bd6cdbf",
    "zh_a271d96039",
    "zh_f8cc996739",
    "zh_14b93ce275",
    "zh_17a83223e4",
    "zh_313cabffd8",
    "zh_f558f0a88f",
    "zh_d62301d84c",
    "zh_540e1969e3",
    "zh_0c5a8e59e2",
    "zh_7598a3116c",
    "zh_1a5675a37a",
    "zh_c4f4b0d48a",
    "zh_7fe8603c08",
    "zh_b7ceabc3c0",
    "zh_17e15e0c5a",
    "zh_a17bd1c3f3",
    "zh_dcae594f8b",
    "zh_23a2625781",
    "zh_7bf05bc576",
    "zh_1ec5e3f2cc",
    "zh_b4b770e114",
    "regulatory_filing_no",
    "clause_version",
    "clause_effective_date",
    "exclusions_official",
    "waiting_period_claim_handling",
    "reinstatement",
    "claim_filing_requirements",
    "reduced_paid_up",
    "zh_7d7fe38f09",
    "zh_09a5d9e54e",
    "zh_58d313ee26",
    "zh_74aa1b9c93",
    "zh_ca6e0226c2",
    "zh_2df7d6256c",
    "zh_c588207763",
    "zh_0612362268",
    "zh_c5187f228e",
    "zh_74fd5a9469",
    "zh_3a3e6520a3",
    "zh_4a789b1d6f",
    "zh_3d8424595d",
    "zh_f32c510a5e",
    "zh_e1bea0527a",
    "zh_52548821b9",
    "pre_existing_conditions",
    "external_drug_coverage",
    "discontinuation_renewal",
)
APPROVED_RATE_FIELD_IDS: Final[tuple[str, str]] = (
    "zh_7fe8603c08",
    "zh_c588207763",
)


def _approved_critical18_payload() -> dict[str, object]:
    return {
        "contract": "critical18-candidate.v1",
        "schema_version": "v1.1+b31a411c621c",
        "source": "golden-maintenance-frozen-p0-7-p1-11-allowlist",
        "fields": tuple(
            {
                "priority": priority,
                "field_id": field_id,
                "field_name": field_name,
            }
            for priority, field_id, field_name in APPROVED_CRITICAL18_FIELDS
        ),
    }


def _approved_parser_payload(
    arm: Literal["baseline", "candidate"],
) -> dict[str, object]:
    if arm == "baseline":
        return {
            "arm": "baseline",
            "parser_engine": "pdfplumber",
            "parser_profile_ref": "approved-parser-profile:parser-neutral-default.v1",
            "attempt_number": 1,
            "attempt_role": "default",
            "adapter_module": "insurance_harness.compiler.native_pdfplumber",
            "adapter_blob_git_sha1": "d158d000191aadcc5428a986f08b37df821450a4",
            "builder": "build_parsed_document_v1",
        }
    return {
        "arm": "candidate",
        "parser_engine": "mineru-cloud-pipeline",
        "parser_profile_ref": (
            "approved-parser-profile:parser-neutral-bounded-upgrade.v1"
        ),
        "attempt_number": 2,
        "attempt_role": "bounded_upgrade",
        "adapter_module": "insurance_harness.compiler.native_mineru_cloud",
        "adapter_blob_git_sha1": "2c2fc16a60d2d7b7cbe9e28df989af3dd742a19d",
        "source_schema": "mineru.content-list.pipeline.v1",
        "sanitized_contract": "mineru-native-structure.v1",
        "builder": "build_mineru_parsed_document_v1",
    }


def _approved_arm_profile_payload() -> dict[str, object]:
    return {
        "contract": "061-arm-profile-candidate.v1",
        "authority_base": "1a8e36e032512e77474c83efbe1a97ed1c183b30",
        "invariant": "parser_artifact_is_only_arm_variable",
        "semantic_extraction": {
            "model": "deepseek-v4-flash",
            "endpoint": APPROVED_SEMANTIC_API_BASE,
            "protocol": "openai_compatible",
            "credential_status": "PRESENT_BY_STRICT_LOADER",
        },
        "arms": [
            _approved_parser_payload("baseline"),
            _approved_parser_payload("candidate"),
        ],
        "excluded": {
            "qwen3_7_plus": ["semantic_arm", "model_judge", "fallback"],
            "allowed_only": "separately-approved-local-vlm-parser-upgrade",
        },
    }


def _approved_component_payloads() -> dict[str, tuple[str, dict[str, object]]]:
    return {
        "model": (
            "vertical-falsification-semantic-model.v1",
            {
                "model": "deepseek-v4-flash",
                "endpoint": APPROVED_SEMANTIC_API_BASE,
                "protocol": "openai_compatible",
            },
        ),
        "prompt": (
            "vertical-falsification-prompt.v1",
            {
                "contract": "596-1-schema60-ten-task-extraction.v1",
                "task_count": 10,
                "golden_blind": True,
            },
        ),
        "budget": (
            "vertical-falsification-budget.v1",
            {
                "baseline_provider_max": 6,
                "candidate_main_max": 8,
                "candidate_repair_max": 4,
                "total_hard_cap": 18,
                "fallback_calls": 0,
                "retry_calls": 0,
            },
        ),
        "normalizer": (
            "vertical-falsification-normalizer.v1",
            {
                "contract": "identity-string-normalizer.v1",
                "operation": "preserve-exact-value-snapshot",
            },
        ),
        "comparator": (
            "vertical-falsification-comparator.v1",
            {
                "contract": "exact-state-value-comparator.v1",
                "operation": "exact-tri-state-and-value-snapshot-equality",
            },
        ),
        "baseline_parser": (
            "vertical-falsification-parser-identity.v1",
            _approved_parser_payload("baseline"),
        ),
        "candidate_parser": (
            "vertical-falsification-parser-identity.v1",
            _approved_parser_payload("candidate"),
        ),
    }


def _approved_evaluator_payload() -> dict[str, object]:
    return {
        "contract": "vertical-falsification-scorer.v1",
        "schema_version": APPROVED_SCHEMA_VERSION,
        "schema_registry_sha256": APPROVED_SCHEMA_REGISTRY_SHA256,
        "critical18_sha256": APPROVED_CRITICAL18_SHA256,
        "normalizer_identity_sha256": APPROVED_NORMALIZER_IDENTITY_SHA256,
        "comparator_identity_sha256": APPROVED_COMPARATOR_IDENTITY_SHA256,
        "candidate_gates": {
            "critical_semantic_errors": 0,
            "hallucinations": 0,
            "tri_state_minimum": 57,
            "normalized_value_minimum_percent": 95,
            "critical_known_evidence_percent": 100,
            "overall_known_evidence_minimum_percent": 95,
            "rate_locator_complete": True,
        },
    }


if (
    canonical_hash("critical18-candidate.v1", _approved_critical18_payload())
    != APPROVED_CRITICAL18_SHA256
):  # pragma: no cover - import-time custody assertion
    raise RuntimeError("approved critical18 canonical identity drifted")

if (
    canonical_hash(
        "vertical-falsification-arm-profile.v1",
        _approved_arm_profile_payload(),
    )
    != APPROVED_ARM_PROFILE_SHA256
):  # pragma: no cover - import-time custody assertion
    raise RuntimeError("approved arm profile canonical identity drifted")

_EXPECTED_COMPONENT_HASHES: Final[dict[str, str]] = {
    "model": APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256,
    "prompt": APPROVED_PROMPT_IDENTITY_SHA256,
    "budget": APPROVED_BUDGET_IDENTITY_SHA256,
    "normalizer": APPROVED_NORMALIZER_IDENTITY_SHA256,
    "comparator": APPROVED_COMPARATOR_IDENTITY_SHA256,
    "baseline_parser": APPROVED_BASELINE_PARSER_IDENTITY_SHA256,
    "candidate_parser": APPROVED_CANDIDATE_PARSER_IDENTITY_SHA256,
}
if any(
    canonical_hash(domain, payload) != _EXPECTED_COMPONENT_HASHES[name]
    for name, (domain, payload) in _approved_component_payloads().items()
):  # pragma: no cover - import-time custody assertion
    raise RuntimeError("approved arm component canonical identity drifted")

if (
    canonical_hash(
        "vertical-falsification-evaluator.v1",
        _approved_evaluator_payload(),
    )
    != APPROVED_EVALUATOR_IDENTITY_SHA256
):  # pragma: no cover - import-time custody assertion
    raise RuntimeError("approved evaluator canonical identity drifted")

if (
    len(APPROVED_SCHEMA60_FIELD_IDS) != 60
    or len(set(APPROVED_SCHEMA60_FIELD_IDS)) != 60
    or not set(APPROVED_CRITICAL18_FIELD_IDS).issubset(APPROVED_SCHEMA60_FIELD_IDS)
    or not set(APPROVED_RATE_FIELD_IDS).issubset(APPROVED_SCHEMA60_FIELD_IDS)
):  # pragma: no cover - import-time custody assertion
    raise RuntimeError("approved Schema60 field identity drifted")


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and value == value.lower() and all(
        character in "0123456789abcdef" for character in value
    )


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


@dataclass(frozen=True, slots=True)
class RequiredPublicContract:
    """One upstream public seam; this carries no replacement DTO or authority."""

    contract_id: str
    module: str
    symbols: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedPublicContract:
    """One immutable capture of an untrusted module's required exports."""

    contract_id: str
    exports: tuple[tuple[str, object], ...]

    def get(self, name: str) -> object | None:
        return next(
            (value for export_name, value in self.exports if export_name == name),
            None,
        )


REQUIRED_PUBLIC_CONTRACTS: Final[tuple[RequiredPublicContract, ...]] = (
    RequiredPublicContract(
        contract_id="060_mineru_canonical_structure_adapter.v1",
        module="insurance_harness.compiler.native_mineru_cloud",
        symbols=(
            "NativeMinerUStructureError",
            "ParsedDocumentV1",
            "ParseManifestV1",
            "ParseQualityDecisionV1",
            "build_mineru_parsed_document_v1",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class AdmittedParseArtifactV1:
    """Immutable 060 custody intake for one exact 596-1 source artifact."""

    role: Literal["terms", "brochure", "rate_table"]
    source_sha256: str
    artifact_sha256: str
    document: ParsedDocumentV1
    manifest: ParseManifestV1
    decision: ParseQualityDecisionV1
    manifest_sha256: str
    decision_sha256: str
    sanitized_structure: bytes | None = field(default=None, repr=False)
    raw_structure_sha256: str | None = None
    sanitized_structure_sha256: str | None = None
    material_profile_resolution: MaterialProfileResolution | None = field(
        default=None,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class VerticalFalsificationAdmission:
    """Non-terminal admission result emitted before any evaluation-side access."""

    status: Literal[
        "BLOCKED_ON_REQUIRED_CONTRACTS", "READY_FOR_QUALITY_FALSIFICATION"
    ]
    missing_contracts: tuple[str, ...]
    provider_calls: Literal[0] = 0
    golden_reads: Literal[0] = 0
    terminal_outcome: None = None
    receipt_digest_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class CallBudgetLedgerV1:
    """Deterministic counters for the one approved 596-1 experiment."""

    baseline_calls: int
    candidate_main_calls: int
    candidate_repair_calls: int
    fallback_calls: int = 0
    retry_calls: int = 0

    def __post_init__(self) -> None:
        values = (
            self.baseline_calls,
            self.candidate_main_calls,
            self.candidate_repair_calls,
            self.fallback_calls,
            self.retry_calls,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("call budget counters must be finite non-negative integers")

    @property
    def total_calls(self) -> int:
        return (
            self.baseline_calls
            + self.candidate_main_calls
            + self.candidate_repair_calls
            + self.fallback_calls
            + self.retry_calls
        )


@dataclass(frozen=True, slots=True)
class BudgetDecisionV1:
    status: Literal["WITHIN_BUDGET", "MVP_VERTICAL_SLICE_NO_GO"]
    reason_codes: tuple[str, ...]
    total_calls: int


@dataclass(frozen=True, slots=True)
class ArmInputIdentityV1:
    """Exact immutable inputs; parser may differ between comparison arms."""

    product_version_id: str
    source_sha256: tuple[str, str, str]
    schema_version: str
    schema_sha256: str
    parser_identity_sha256: str
    model_identity_sha256: str
    semantic_model_id: str
    semantic_api_base: str
    prompt_identity_sha256: str
    budget_identity_sha256: str
    normalizer_identity_sha256: str
    comparator_identity_sha256: str
    arm_profile_sha256: str
    parse_artifact_receipt_digest_sha256: str
    parser_id: str
    parser_mode: str
    parser_attempt: int

    def __post_init__(self) -> None:
        if not self.product_version_id.strip() or not self.schema_version.strip():
            raise ValueError("product and Schema identities are required")
        hashes = (
            *self.source_sha256,
            self.schema_sha256,
            self.parser_identity_sha256,
            self.model_identity_sha256,
            self.prompt_identity_sha256,
            self.budget_identity_sha256,
            self.normalizer_identity_sha256,
            self.comparator_identity_sha256,
            self.arm_profile_sha256,
            self.parse_artifact_receipt_digest_sha256,
        )
        if len(set(self.source_sha256)) != 3 or not all(map(_is_sha256, hashes)):
            raise ValueError("arm input identities must bind three unique SHA256 sources")
        if (
            not self.semantic_model_id.strip()
            or not self.semantic_api_base.strip()
            or not self.parser_id.strip()
            or not self.parser_mode.strip()
            or self.parser_attempt < 1
        ):
            raise ValueError("arm execution profile identity is incomplete")


@dataclass(frozen=True, slots=True)
class EvidenceLocatorV1:
    source_sha256: str
    quote_snapshot: str
    page_number: int | None = None
    block_id: str | None = None
    table_id: str | None = None
    cell_id: str | None = None
    row_index: int | None = None
    column_index: int | None = None
    header_snapshot: str | None = None
    row_span: int | None = None
    column_span: int | None = None

    def __post_init__(self) -> None:
        if not _is_sha256(self.source_sha256) or not self.quote_snapshot.strip():
            raise ValueError("Evidence must bind source SHA and a non-empty quote snapshot")
        if self.page_number is not None and self.page_number < 1:
            raise ValueError("Evidence page number must be positive")
        if any(
            value is not None and not value.strip()
            for value in (self.block_id, self.table_id, self.cell_id, self.header_snapshot)
        ):
            raise ValueError("Evidence structure locator strings must be non-blank")
        if any(
            value is not None and value < 0
            for value in (self.row_index, self.column_index)
        ):
            raise ValueError("Evidence structure locator indexes must be non-negative")
        if any(
            value is not None and value < 1
            for value in (self.row_span, self.column_span)
        ):
            raise ValueError("Evidence structure locator spans must be positive")


@dataclass(frozen=True, slots=True)
class ArmFieldOutputV1:
    field_id: str
    state: Literal["present", "absent_explicitly", "unknown"]
    value_snapshot: str | None
    evidence: tuple[EvidenceLocatorV1, ...] = ()

    def __post_init__(self) -> None:
        if not self.field_id.strip():
            raise ValueError("field id is required")
        if self.state != "unknown" and (
            self.value_snapshot is None or not self.value_snapshot.strip()
        ):
            raise ValueError("known fields require a value snapshot")
        if self.state == "unknown" and self.value_snapshot is not None:
            raise ValueError("unknown fields cannot carry a value")


@dataclass(frozen=True, slots=True)
class FrozenArmOutputV1:
    arm: Literal["baseline", "candidate"]
    identity: ArmInputIdentityV1
    fields: tuple[ArmFieldOutputV1, ...]
    output_hash: str


@dataclass(frozen=True, slots=True)
class GoldenFieldV1:
    field_id: str
    expected_state: Literal["present", "absent_explicitly", "unknown"]
    expected_value: str | None
    critical: Literal["P0", "P1"] | None
    rate: bool = False

    def __post_init__(self) -> None:
        if not self.field_id.strip():
            raise ValueError("Golden field id is required")
        if self.expected_state != "unknown" and (
            self.expected_value is None or not self.expected_value.strip()
        ):
            raise ValueError("known Golden fields require an expected value")
        if self.expected_state == "unknown" and self.expected_value is not None:
            raise ValueError("unknown Golden fields cannot carry a value")


@dataclass(frozen=True, slots=True)
class GoldenSetV1:
    """Internally parsed, exact-byte-bound 049 scoring oracle."""

    product_version_id: str
    schema_version: str
    schema_sha256: str
    source_sha256: tuple[str, str, str]
    release_hash: str
    artifact_hash: str
    approval_subject_hash: str
    golden_596_jsonl_sha256: str
    golden_content_digest_sha256: str
    critical18_contract_id: str
    critical18_contract_sha256: str
    fields: tuple[GoldenFieldV1, ...]

    def __post_init__(self) -> None:
        if (
            not self.product_version_id.strip()
            or not self.schema_version.strip()
            or not _is_sha256(self.schema_sha256)
            or len(set(self.source_sha256)) != 3
            or not all(map(_is_sha256, self.source_sha256))
            or not _is_sha256(self.release_hash)
            or not _is_sha256(self.artifact_hash)
            or not _is_sha256(self.approval_subject_hash)
            or not _is_sha256(self.golden_596_jsonl_sha256)
            or not _is_sha256(self.golden_content_digest_sha256)
            or not self.critical18_contract_id.strip()
            or not _is_sha256(self.critical18_contract_sha256)
        ):
            raise ValueError("Golden identity is incomplete")


_GOLDEN_RECORD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "product_id",
        "product_name",
        "doc",
        "field_id",
        "field_name",
        "value",
        "tri_state",
        "evidence",
        "disputed",
        "disputed_reason",
        "reasoning",
        "annotator_model",
        "schema_version",
        "created_at",
    }
)
_GOLDEN_EVIDENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "page",
        "quote",
        "knowledge_id",
        "raw_kb_id",
        "source_revision",
        "file_hash",
        "original_digest",
        "parser_version",
        "chunk_id",
        "chunk_hash",
        "lineage_status",
    }
)
_GOLDEN_DOCUMENT_NAMES: Final[frozenset[str]] = frozenset(
    {"保险条款.pdf", "产品说明书.pdf", "费率表.pdf"}
)


def _parse_approved_golden_bytes(
    golden_596_jsonl_bytes: object,
) -> GoldenSetV1 | None:
    """Strictly parse only the exact approved 049 596.jsonl bytes."""

    if not isinstance(golden_596_jsonl_bytes, bytes):
        return None
    if _sha256_bytes(golden_596_jsonl_bytes) != APPROVED_GOLDEN_596_JSONL_SHA256:
        return None
    try:
        text = golden_596_jsonl_bytes.decode("utf-8", errors="strict")
        lines = text.splitlines()
        if len(lines) != 60 or any(not line for line in lines):
            return None
        records = tuple(
            cast(dict[str, object], json.loads(line)) for line in lines
        )
        by_field_id: dict[
            str,
            tuple[
                Literal["present", "absent_explicitly", "unknown"],
                str | None,
            ],
        ] = {}
        for record in records:
            if set(record) != _GOLDEN_RECORD_KEYS:
                return None
            field_id = record["field_id"]
            field_name = record["field_name"]
            product_name = record["product_name"]
            document_name = record["doc"]
            reasoning = record["reasoning"]
            created_at = record["created_at"]
            if (
                record["product_id"] != "596"
                or record["schema_version"] != APPROVED_SCHEMA_VERSION
                or record["annotator_model"] != "gpt-5.6-sol"
                or record["disputed"] is not False
                or record["disputed_reason"] is not None
                or not isinstance(field_id, str)
                or not field_id.strip()
                or not isinstance(field_name, str)
                or not field_name.strip()
                or not isinstance(product_name, str)
                or not product_name.strip()
                or document_name not in _GOLDEN_DOCUMENT_NAMES
                or not isinstance(reasoning, str)
                or not reasoning.strip()
                or not isinstance(created_at, str)
                or not created_at.strip()
                or field_id in by_field_id
            ):
                return None
            raw_state = record["tri_state"]
            if raw_state == "present":
                state: Literal["present", "absent_explicitly", "unknown"] = (
                    "present"
                )
            elif raw_state == "absent_explicitly":
                state = "absent_explicitly"
            elif raw_state == "unknown":
                state = "unknown"
            else:
                return None
            raw_value = record["value"]
            if state != "unknown":
                if not isinstance(raw_value, str) or not raw_value.strip():
                    return None
                value: str | None = raw_value
            else:
                if raw_value is not None:
                    return None
                value = None
            raw_evidence = record["evidence"]
            if not isinstance(raw_evidence, list):
                return None
            for raw_item in raw_evidence:
                if not isinstance(raw_item, dict):
                    return None
                item = cast(dict[str, object], raw_item)
                if set(item) != _GOLDEN_EVIDENCE_KEYS:
                    return None
                page = item["page"]
                quote = item["quote"]
                if (
                    type(page) is not int
                    or page < 1
                    or not isinstance(quote, str)
                    or not quote.strip()
                    or any(
                        item[key] is not None
                        for key in _GOLDEN_EVIDENCE_KEYS - {"page", "quote"}
                    )
                ):
                    return None
            if state == "unknown" and raw_evidence:
                return None
            by_field_id[field_id] = (state, value)
        if set(by_field_id) != set(APPROVED_SCHEMA60_FIELD_IDS):
            return None
        critical_priorities: dict[str, Literal["P0", "P1"]] = {
            field_id: priority
            for priority, field_id, _field_name in APPROVED_CRITICAL18_FIELDS
        }
        fields = tuple(
            GoldenFieldV1(
                field_id=field_id,
                expected_state=by_field_id[field_id][0],
                expected_value=by_field_id[field_id][1],
                critical=critical_priorities.get(field_id),
                rate=field_id in APPROVED_RATE_FIELD_IDS,
            )
            for field_id in APPROVED_SCHEMA60_FIELD_IDS
        )
        content_digest = canonical_hash(
            "golden-049-596-content.v1",
            {"records": records},
        )
        return GoldenSetV1(
            product_version_id=APPROVED_PRODUCT_VERSION_ID,
            schema_version=APPROVED_SCHEMA_VERSION,
            schema_sha256=APPROVED_SCHEMA_REGISTRY_SHA256,
            source_sha256=APPROVED_596_1_SOURCE_SHA256,
            release_hash=APPROVED_GOLDEN_RELEASE_SHA256,
            artifact_hash=APPROVED_GOLDEN_ARTIFACT_SHA256,
            approval_subject_hash=APPROVED_GOLDEN_APPROVAL_SUBJECT_SHA256,
            golden_596_jsonl_sha256=APPROVED_GOLDEN_596_JSONL_SHA256,
            golden_content_digest_sha256=content_digest,
            critical18_contract_id="critical18-candidate.v1",
            critical18_contract_sha256=APPROVED_CRITICAL18_SHA256,
            fields=fields,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


@dataclass(frozen=True, slots=True)
class ArmQualityMetricsV1:
    denominator: int
    critical_denominator: int
    tri_state_correct: int
    normalized_value_denominator: int
    normalized_value_correct: int
    abstentions: int
    misses: int
    hallucinations: int
    wrong_values: int
    exact_field_correct: int
    known_denominator: int
    known_with_evidence: int
    critical_known_denominator: int
    critical_known_with_evidence: int
    critical_silent_errors: int
    critical_semantic_errors: int
    tri_state_correct_basis_points: int
    normalized_value_correct_basis_points: int
    abstention_basis_points: int
    known_evidence_basis_points: int


@dataclass(frozen=True, slots=True)
class ArmFieldCorrectnessV1:
    """Answer-free per-field facts produced by the approved Golden comparator."""

    field_id: str
    critical_priority: Literal["P0", "P1"] | None
    rate_field: bool
    tri_state_correct: bool
    exact_field_correct: bool
    known_evidence_present: bool
    rate_locator_complete: bool | None


@dataclass(frozen=True, slots=True)
class _FieldEvaluation:
    field_id: str
    critical_priority: Literal["P0", "P1"] | None
    rate_field: bool
    tri_state_correct: bool
    normalized_value_evaluated: bool
    normalized_value_correct: bool | None
    exact_field_correct: bool
    abstention: bool
    miss: bool
    hallucination: bool
    wrong_value: bool
    known_evidence_present: bool
    rate_locator_complete: bool | None


@dataclass(frozen=True, slots=True)
class AdmittedFrozenArmScoreV1:
    """One admitted MinerU arm scored without disclosing Golden answers."""

    status: Literal[
        "SCORED",
        "BLOCKED_ON_REQUIRED_CONTRACTS",
        "GOLDEN_INVALID",
    ]
    reason_codes: tuple[str, ...]
    metrics: ArmQualityMetricsV1
    field_correctness: tuple[ArmFieldCorrectnessV1, ...]
    output_hash: str | None
    arm_identity: ArmInputIdentityV1 | None
    admission_receipt_digest_sha256: str | None
    golden_content_digest_sha256: str | None
    golden_release_hash: str = APPROVED_GOLDEN_RELEASE_SHA256
    golden_artifact_hash: str = APPROVED_GOLDEN_ARTIFACT_SHA256
    golden_approval_subject_hash: str = APPROVED_GOLDEN_APPROVAL_SUBJECT_SHA256
    golden_596_jsonl_sha256: str = APPROVED_GOLDEN_596_JSONL_SHA256
    evaluator_identity_sha256: str = APPROVED_EVALUATOR_IDENTITY_SHA256
    score_receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        payload = {
            "status": self.status,
            "reason_codes": self.reason_codes,
            "metrics": asdict(self.metrics),
            "field_correctness": tuple(
                asdict(item) for item in self.field_correctness
            ),
            "output_hash": self.output_hash,
            "arm_identity": (
                None if self.arm_identity is None else asdict(self.arm_identity)
            ),
            "admission_receipt_digest_sha256": (
                self.admission_receipt_digest_sha256
            ),
            "golden_release_hash": self.golden_release_hash,
            "golden_artifact_hash": self.golden_artifact_hash,
            "golden_approval_subject_hash": self.golden_approval_subject_hash,
            "golden_596_jsonl_sha256": self.golden_596_jsonl_sha256,
            "golden_content_digest_sha256": self.golden_content_digest_sha256,
            "evaluator_identity_sha256": self.evaluator_identity_sha256,
        }
        object.__setattr__(
            self,
            "score_receipt_hash",
            canonical_hash("admitted-frozen-arm-score.v1", payload),
        )


@dataclass(frozen=True, slots=True)
class VerticalFalsificationDecisionV1:
    terminal_outcome: Literal[
        "QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE",
        "MVP_VERTICAL_SLICE_NO_GO",
    ]
    reason_codes: tuple[str, ...]
    baseline_metrics: ArmQualityMetricsV1
    candidate_metrics: ArmQualityMetricsV1
    budget: BudgetDecisionV1
    baseline_output_hash: str | None
    candidate_output_hash: str | None
    golden_release_hash: str
    golden_artifact_hash: str
    golden_approval_subject_hash: str
    golden_596_jsonl_sha256: str
    golden_content_digest_sha256: str | None
    admission_receipt_digest_sha256: str | None
    evaluator_identity_sha256: str
    score_receipt_hash: str = field(init=False)

    def __post_init__(self) -> None:
        optional_hashes = (
            self.baseline_output_hash,
            self.candidate_output_hash,
            self.golden_content_digest_sha256,
            self.admission_receipt_digest_sha256,
        )
        required_hashes = (
            self.golden_release_hash,
            self.golden_artifact_hash,
            self.golden_approval_subject_hash,
            self.golden_596_jsonl_sha256,
            self.evaluator_identity_sha256,
        )
        if not all(value is None or _is_sha256(value) for value in optional_hashes):
            raise ValueError("score receipt arm hashes are invalid")
        if not all(_is_sha256(value) for value in required_hashes):
            raise ValueError("score receipt authority hashes are invalid")
        payload = {
            "terminal_outcome": self.terminal_outcome,
            "reason_codes": self.reason_codes,
            "baseline_metrics": asdict(self.baseline_metrics),
            "candidate_metrics": asdict(self.candidate_metrics),
            "budget": asdict(self.budget),
            "baseline_output_hash": self.baseline_output_hash,
            "candidate_output_hash": self.candidate_output_hash,
            "golden_release_hash": self.golden_release_hash,
            "golden_artifact_hash": self.golden_artifact_hash,
            "golden_approval_subject_hash": self.golden_approval_subject_hash,
            "golden_596_jsonl_sha256": self.golden_596_jsonl_sha256,
            "golden_content_digest_sha256": self.golden_content_digest_sha256,
            "admission_receipt_digest_sha256": (
                self.admission_receipt_digest_sha256
            ),
            "evaluator_identity_sha256": self.evaluator_identity_sha256,
        }
        object.__setattr__(
            self,
            "score_receipt_hash",
            canonical_hash("vertical-falsification-score-receipt.v1", payload),
        )


def _empty_quality_metrics() -> ArmQualityMetricsV1:
    return ArmQualityMetricsV1(
        denominator=0,
        critical_denominator=0,
        tri_state_correct=0,
        normalized_value_denominator=0,
        normalized_value_correct=0,
        abstentions=0,
        misses=0,
        hallucinations=0,
        wrong_values=0,
        exact_field_correct=0,
        known_denominator=0,
        known_with_evidence=0,
        critical_known_denominator=0,
        critical_known_with_evidence=0,
        critical_silent_errors=0,
        critical_semantic_errors=0,
        tri_state_correct_basis_points=0,
        normalized_value_correct_basis_points=0,
        abstention_basis_points=0,
        known_evidence_basis_points=0,
    )


def _arm_output_payload(
    *,
    arm: Literal["baseline", "candidate"],
    identity: ArmInputIdentityV1,
    fields: tuple[ArmFieldOutputV1, ...],
) -> dict[str, object]:
    return {
        "arm": arm,
        "identity": {
            "product_version_id": identity.product_version_id,
            "source_sha256": identity.source_sha256,
            "schema_version": identity.schema_version,
            "schema_sha256": identity.schema_sha256,
            "parser_identity_sha256": identity.parser_identity_sha256,
            "model_identity_sha256": identity.model_identity_sha256,
            "semantic_model_id": identity.semantic_model_id,
            "semantic_api_base": identity.semantic_api_base,
            "prompt_identity_sha256": identity.prompt_identity_sha256,
            "budget_identity_sha256": identity.budget_identity_sha256,
            "normalizer_identity_sha256": identity.normalizer_identity_sha256,
            "comparator_identity_sha256": identity.comparator_identity_sha256,
            "arm_profile_sha256": identity.arm_profile_sha256,
            "parse_artifact_receipt_digest_sha256": (
                identity.parse_artifact_receipt_digest_sha256
            ),
            "parser_id": identity.parser_id,
            "parser_mode": identity.parser_mode,
            "parser_attempt": identity.parser_attempt,
        },
        "fields": tuple(
            {
                "field_id": field.field_id,
                "state": field.state,
                "value_snapshot": field.value_snapshot,
                "evidence": tuple(
                    {
                        "source_sha256": item.source_sha256,
                        "quote_snapshot": item.quote_snapshot,
                        "page_number": item.page_number,
                        "block_id": item.block_id,
                        "table_id": item.table_id,
                        "cell_id": item.cell_id,
                        "row_index": item.row_index,
                        "column_index": item.column_index,
                        "header_snapshot": item.header_snapshot,
                        "row_span": item.row_span,
                        "column_span": item.column_span,
                    }
                    for item in field.evidence
                ),
            }
            for field in fields
        ),
    }


def freeze_arm_output(
    *,
    arm: Literal["baseline", "candidate"],
    identity: ArmInputIdentityV1,
    fields: tuple[ArmFieldOutputV1, ...],
) -> FrozenArmOutputV1:
    """Freeze one complete arm before any caller may inject Golden values."""

    payload = _arm_output_payload(arm=arm, identity=identity, fields=fields)
    return FrozenArmOutputV1(
        arm=arm,
        identity=identity,
        fields=fields,
        output_hash=canonical_hash(ARM_OUTPUT_OBJECT_TYPE, payload),
    )


def verify_arm_output_hash(output: FrozenArmOutputV1) -> bool:
    payload = _arm_output_payload(
        arm=output.arm,
        identity=output.identity,
        fields=output.fields,
    )
    return _is_sha256(output.output_hash) and output.output_hash == canonical_hash(
        ARM_OUTPUT_OBJECT_TYPE,
        payload,
    )


def _shared_arm_identity(identity: ArmInputIdentityV1) -> tuple[object, ...]:
    return (
        identity.product_version_id,
        identity.source_sha256,
        identity.schema_version,
        identity.schema_sha256,
        identity.model_identity_sha256,
        identity.semantic_model_id,
        identity.semantic_api_base,
        identity.prompt_identity_sha256,
        identity.budget_identity_sha256,
        identity.normalizer_identity_sha256,
        identity.comparator_identity_sha256,
        identity.arm_profile_sha256,
        identity.parse_artifact_receipt_digest_sha256,
    )


def _arm_profile_matches(
    baseline: ArmInputIdentityV1,
    candidate: ArmInputIdentityV1,
) -> bool:
    return (
        baseline.arm_profile_sha256 == APPROVED_ARM_PROFILE_SHA256
        and candidate.arm_profile_sha256 == APPROVED_ARM_PROFILE_SHA256
        and baseline.semantic_model_id == APPROVED_SEMANTIC_MODEL_ID
        and candidate.semantic_model_id == APPROVED_SEMANTIC_MODEL_ID
        and baseline.semantic_api_base == APPROVED_SEMANTIC_API_BASE
        and candidate.semantic_api_base == APPROVED_SEMANTIC_API_BASE
        and (baseline.parser_id, baseline.parser_mode, baseline.parser_attempt)
        == ("pdfplumber", "default", 1)
        and baseline.parser_identity_sha256
        == APPROVED_BASELINE_PARSER_IDENTITY_SHA256
        and (candidate.parser_id, candidate.parser_mode, candidate.parser_attempt)
        == ("mineru-cloud-pipeline", "bounded_upgrade", 2)
        and candidate.parser_identity_sha256
        == APPROVED_CANDIDATE_PARSER_IDENTITY_SHA256
    )


def _approved_arm_component_matches(identity: ArmInputIdentityV1) -> bool:
    return (
        identity.arm_profile_sha256 == APPROVED_ARM_PROFILE_SHA256
        and identity.model_identity_sha256
        == APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256
        and identity.prompt_identity_sha256 == APPROVED_PROMPT_IDENTITY_SHA256
        and identity.budget_identity_sha256 == APPROVED_BUDGET_IDENTITY_SHA256
        and identity.normalizer_identity_sha256
        == APPROVED_NORMALIZER_IDENTITY_SHA256
        and identity.comparator_identity_sha256
        == APPROVED_COMPARATOR_IDENTITY_SHA256
    )


def _approved_arm_authority_matches(identity: ArmInputIdentityV1) -> bool:
    return (
        identity.product_version_id == APPROVED_PRODUCT_VERSION_ID
        and identity.source_sha256 == APPROVED_596_1_SOURCE_SHA256
        and identity.schema_version == APPROVED_SCHEMA_VERSION
        and identity.schema_sha256 == APPROVED_SCHEMA_REGISTRY_SHA256
        and identity.semantic_model_id == APPROVED_SEMANTIC_MODEL_ID
        and identity.semantic_api_base == APPROVED_SEMANTIC_API_BASE
    )


def _field_map(
    fields: tuple[ArmFieldOutputV1, ...],
) -> dict[str, ArmFieldOutputV1]:
    return {field.field_id: field for field in fields}


def _field_set_reasons(
    *,
    label: str,
    fields: tuple[ArmFieldOutputV1, ...],
    expected_ids: tuple[str, ...],
) -> list[str]:
    actual_ids = tuple(field.field_id for field in fields)
    if len(actual_ids) != 60 or len(set(actual_ids)) != 60:
        return [f"{label}_FIELD_SET_NOT_EXACT_60"]
    if set(actual_ids) != set(expected_ids):
        return [f"{label}_FIELD_IDENTITY_MISMATCH"]
    return []


def _field_evaluations(
    *,
    output: FrozenArmOutputV1 | None,
    golden: GoldenSetV1,
) -> tuple[_FieldEvaluation, ...]:
    outputs = {} if output is None else _field_map(output.fields)
    evaluations: list[_FieldEvaluation] = []
    for expected in golden.fields:
        actual = outputs.get(expected.field_id)
        state_matches = actual is not None and actual.state == expected.expected_state
        exact_matches = bool(
            actual is not None
            and state_matches
            and actual.value_snapshot == expected.expected_value
        )
        value_evaluated = expected.expected_state == "present"
        value_matches = (
            bool(
                actual is not None
                and actual.state == "present"
                and actual.value_snapshot == expected.expected_value
            )
            if value_evaluated
            else None
        )
        has_bound_evidence = bool(
            actual
            and actual.state != "unknown"
            and actual.evidence
            and output is not None
            and all(
                evidence.source_sha256 in output.identity.source_sha256
                for evidence in actual.evidence
            )
        )
        rate_locator_complete = (
            bool(
                actual
                and actual.evidence
                and all(_rate_locator_complete(item) for item in actual.evidence)
            )
            if expected.rate
            else None
        )
        evaluations.append(
            _FieldEvaluation(
                field_id=expected.field_id,
                critical_priority=expected.critical,
                rate_field=expected.rate,
                tri_state_correct=state_matches,
                normalized_value_evaluated=value_evaluated,
                normalized_value_correct=value_matches,
                exact_field_correct=exact_matches,
                abstention=actual is None or actual.state == "unknown",
                miss=(
                    expected.expected_state != "unknown"
                    and (actual is None or actual.state == "unknown")
                ),
                hallucination=(
                    expected.expected_state == "unknown"
                    and actual is not None
                    and actual.state != "unknown"
                ),
                wrong_value=bool(
                    value_evaluated
                    and actual is not None
                    and actual.state == "present"
                    and not value_matches
                ),
                known_evidence_present=has_bound_evidence,
                rate_locator_complete=rate_locator_complete,
            )
        )
    return tuple(evaluations)


def _quality_metrics(
    *,
    output: FrozenArmOutputV1 | None,
    golden: GoldenSetV1,
) -> ArmQualityMetricsV1:
    known = tuple(field for field in golden.fields if field.expected_state != "unknown")
    critical_known = tuple(field for field in known if field.critical is not None)
    evaluations = _field_evaluations(output=output, golden=golden)

    def _basis_points(numerator: int, denominator: int) -> int:
        return 0 if denominator == 0 else numerator * 10_000 // denominator

    tri_state_correct = sum(item.tri_state_correct for item in evaluations)
    normalized_value_denominator = sum(
        item.normalized_value_evaluated for item in evaluations
    )
    normalized_value_correct = sum(
        item.normalized_value_correct is True for item in evaluations
    )
    abstentions = sum(item.abstention for item in evaluations)
    misses = sum(item.miss for item in evaluations)
    hallucinations = sum(item.hallucination for item in evaluations)
    wrong_values = sum(item.wrong_value for item in evaluations)
    exact_field_correct = sum(item.exact_field_correct for item in evaluations)
    silent_errors = sum(
        item.critical_priority is not None
        and not item.abstention
        and not item.exact_field_correct
        for item in evaluations
    )
    critical_semantic_errors = sum(
        item.critical_priority is not None and not item.exact_field_correct
        for item in evaluations
    )
    known_with_evidence = sum(
        item.known_evidence_present
        for item, expected in zip(evaluations, golden.fields, strict=True)
        if expected.expected_state != "unknown"
    )

    return ArmQualityMetricsV1(
        denominator=len(golden.fields),
        critical_denominator=sum(field.critical is not None for field in golden.fields),
        tri_state_correct=tri_state_correct,
        normalized_value_denominator=normalized_value_denominator,
        normalized_value_correct=normalized_value_correct,
        abstentions=abstentions,
        misses=misses,
        hallucinations=hallucinations,
        wrong_values=wrong_values,
        exact_field_correct=exact_field_correct,
        known_denominator=len(known),
        known_with_evidence=known_with_evidence,
        critical_known_denominator=len(critical_known),
        critical_known_with_evidence=sum(
            item.known_evidence_present
            for item, expected in zip(evaluations, golden.fields, strict=True)
            if expected.expected_state != "unknown" and expected.critical is not None
        ),
        critical_silent_errors=silent_errors,
        critical_semantic_errors=critical_semantic_errors,
        tri_state_correct_basis_points=_basis_points(
            tri_state_correct, len(golden.fields)
        ),
        normalized_value_correct_basis_points=_basis_points(
            normalized_value_correct, normalized_value_denominator
        ),
        abstention_basis_points=_basis_points(abstentions, len(golden.fields)),
        known_evidence_basis_points=_basis_points(
            known_with_evidence, len(known)
        ),
    )


def _rate_locator_complete(evidence: EvidenceLocatorV1) -> bool:
    return (
        evidence.page_number is not None
        and bool(evidence.table_id and evidence.table_id.strip())
        and bool(evidence.cell_id and evidence.cell_id.strip())
        and evidence.row_index is not None
        and evidence.row_index >= 0
        and evidence.column_index is not None
        and evidence.column_index >= 0
        and bool(evidence.header_snapshot and evidence.header_snapshot.strip())
        and evidence.row_span is not None
        and evidence.row_span >= 1
        and evidence.column_span is not None
        and evidence.column_span >= 1
    )


def _absolute_gate_reasons(
    *,
    output: FrozenArmOutputV1,
    golden: GoldenSetV1,
    metrics: ArmQualityMetricsV1,
) -> list[str]:
    reasons: list[str] = []
    if metrics.critical_silent_errors:
        reasons.append("CRITICAL_SILENT_ERROR")
    if metrics.critical_semantic_errors:
        reasons.append("CRITICAL_SEMANTIC_ERROR")
    if metrics.hallucinations:
        reasons.append("CANDIDATE_HALLUCINATION")
    if metrics.tri_state_correct < 57:
        reasons.append("TRI_STATE_CORRECTNESS_BELOW_57_OF_60")
    if (
        metrics.normalized_value_denominator == 0
        or metrics.normalized_value_correct * 100
        < metrics.normalized_value_denominator * 95
    ):
        reasons.append("NORMALIZED_VALUE_CORRECTNESS_BELOW_95")
    if metrics.critical_known_with_evidence != metrics.critical_known_denominator:
        reasons.append("CRITICAL_KNOWN_EVIDENCE_INCOMPLETE")
    if (
        metrics.known_denominator == 0
        or metrics.known_with_evidence * 100 < metrics.known_denominator * 95
    ):
        reasons.append("OVERALL_KNOWN_EVIDENCE_BELOW_95")

    output_fields = _field_map(output.fields)
    for expected in golden.fields:
        if expected.field_id not in APPROVED_RATE_FIELD_IDS:
            continue
        actual = output_fields.get(expected.field_id)
        if actual is None or not actual.evidence or not all(
            _rate_locator_complete(evidence) for evidence in actual.evidence
        ):
            reasons.append("RATE_EVIDENCE_LOCATOR_INCOMPLETE")
            break
    return reasons


def _is_plain_nonblank(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def _is_valid_arm_identity(identity: object) -> bool:
    if type(identity) is not ArmInputIdentityV1:
        return False
    try:
        sources = identity.source_sha256
        if (
            type(sources) is not tuple
            or len(sources) != 3
            or not all(type(value) is str and _is_sha256(value) for value in sources)
            or len(set(sources)) != 3
        ):
            return False
        hashes = (
            identity.schema_sha256,
            identity.parser_identity_sha256,
            identity.model_identity_sha256,
            identity.prompt_identity_sha256,
            identity.budget_identity_sha256,
            identity.normalizer_identity_sha256,
            identity.comparator_identity_sha256,
            identity.arm_profile_sha256,
            identity.parse_artifact_receipt_digest_sha256,
        )
        return (
            _is_plain_nonblank(identity.product_version_id)
            and all(type(value) is str and _is_sha256(value) for value in hashes)
            and _is_plain_nonblank(identity.schema_version)
            and _is_plain_nonblank(identity.semantic_model_id)
            and _is_plain_nonblank(identity.semantic_api_base)
            and _is_plain_nonblank(identity.parser_id)
            and _is_plain_nonblank(identity.parser_mode)
            and type(identity.parser_attempt) is int
            and identity.parser_attempt >= 1
        )
    except AttributeError:
        return False


def _is_optional_plain_string(value: object) -> bool:
    return value is None or (type(value) is str and bool(value.strip()))


def _is_optional_bounded_int(
    value: object,
    *,
    minimum: int,
) -> bool:
    return value is None or (type(value) is int and value >= minimum)


def _is_valid_evidence_locator(evidence: object) -> bool:
    if type(evidence) is not EvidenceLocatorV1:
        return False
    try:
        return (
            type(evidence.source_sha256) is str
            and _is_sha256(evidence.source_sha256)
            and _is_plain_nonblank(evidence.quote_snapshot)
            and _is_optional_bounded_int(evidence.page_number, minimum=1)
            and all(
                _is_optional_plain_string(value)
                for value in (
                    evidence.block_id,
                    evidence.table_id,
                    evidence.cell_id,
                    evidence.header_snapshot,
                )
            )
            and _is_optional_bounded_int(evidence.row_index, minimum=0)
            and _is_optional_bounded_int(evidence.column_index, minimum=0)
            and _is_optional_bounded_int(evidence.row_span, minimum=1)
            and _is_optional_bounded_int(evidence.column_span, minimum=1)
        )
    except AttributeError:
        return False


def _is_valid_arm_field(field_output: object) -> bool:
    if type(field_output) is not ArmFieldOutputV1:
        return False
    try:
        if (
            not _is_plain_nonblank(field_output.field_id)
            or type(field_output.state) is not str
            or field_output.state
            not in ("present", "absent_explicitly", "unknown")
            or type(field_output.evidence) is not tuple
            or not all(
                _is_valid_evidence_locator(evidence)
                for evidence in field_output.evidence
            )
        ):
            return False
        if field_output.state == "unknown":
            return field_output.value_snapshot is None
        return _is_plain_nonblank(field_output.value_snapshot)
    except AttributeError:
        return False


def _validated_frozen_arm_output(value: object) -> FrozenArmOutputV1 | None:
    if type(value) is not FrozenArmOutputV1:
        return None
    try:
        if (
            type(value.arm) is not str
            or value.arm not in ("baseline", "candidate")
            or not _is_valid_arm_identity(value.identity)
            or type(value.fields) is not tuple
            or not all(_is_valid_arm_field(item) for item in value.fields)
            or type(value.output_hash) is not str
            or not _is_sha256(value.output_hash)
        ):
            return None
    except AttributeError:
        return None
    return value


def _safe_frozen_output_hash(value: object) -> str | None:
    if type(value) is not FrozenArmOutputV1:
        return None
    try:
        output_hash = value.output_hash
    except AttributeError:
        return None
    return output_hash if type(output_hash) is str and _is_sha256(output_hash) else None


def _score_admitted_frozen_outputs(
    *,
    baseline_output: object,
    candidate_output: object,
    golden: GoldenSetV1,
    ledger: CallBudgetLedgerV1,
    admission_receipt_digest_sha256: str,
) -> VerticalFalsificationDecisionV1:
    """Internal deterministic scorer after admission and Golden byte custody."""

    reasons: list[str] = []
    baseline = baseline_output if isinstance(baseline_output, FrozenArmOutputV1) else None
    candidate = (
        candidate_output if isinstance(candidate_output, FrozenArmOutputV1) else None
    )
    if baseline is None or candidate is None:
        reasons.append("ARM_OUTPUT_NOT_FROZEN")
    if baseline is not None and not verify_arm_output_hash(baseline):
        reasons.append("BASELINE_OUTPUT_HASH_MISMATCH")
    if candidate is not None and not verify_arm_output_hash(candidate):
        reasons.append("CANDIDATE_OUTPUT_HASH_MISMATCH")
    if (
        baseline is not None
        and candidate is not None
        and (
            not _is_sha256(admission_receipt_digest_sha256)
            or baseline.identity.parse_artifact_receipt_digest_sha256
            != admission_receipt_digest_sha256
            or candidate.identity.parse_artifact_receipt_digest_sha256
            != admission_receipt_digest_sha256
        )
    ):
        reasons.append("PARSE_ARTIFACT_RECEIPT_BINDING_MISMATCH")

    budget = check_call_budget(ledger)
    reasons.extend(budget.reason_codes)
    if baseline is None or candidate is None or any(
        reason.endswith("OUTPUT_HASH_MISMATCH") for reason in reasons
    ):
        empty_metrics = _empty_quality_metrics()
        return VerticalFalsificationDecisionV1(
            terminal_outcome="MVP_VERTICAL_SLICE_NO_GO",
            reason_codes=tuple(dict.fromkeys(reasons)),
            baseline_metrics=empty_metrics,
            candidate_metrics=empty_metrics,
            budget=budget,
            baseline_output_hash=(
                None if baseline is None else baseline.output_hash
            ),
            candidate_output_hash=(
                None if candidate is None else candidate.output_hash
            ),
            golden_release_hash=APPROVED_GOLDEN_RELEASE_SHA256,
            golden_artifact_hash=APPROVED_GOLDEN_ARTIFACT_SHA256,
            golden_approval_subject_hash=APPROVED_GOLDEN_APPROVAL_SUBJECT_SHA256,
            golden_596_jsonl_sha256=APPROVED_GOLDEN_596_JSONL_SHA256,
            golden_content_digest_sha256=None,
            admission_receipt_digest_sha256=admission_receipt_digest_sha256,
            evaluator_identity_sha256=APPROVED_EVALUATOR_IDENTITY_SHA256,
        )

    golden_ids = tuple(field.field_id for field in golden.fields)
    if len(golden_ids) != 60 or len(set(golden_ids)) != 60:
        reasons.append("GOLDEN_FIELD_SET_NOT_EXACT_60")
    if golden_ids != APPROVED_SCHEMA60_FIELD_IDS:
        reasons.append("SCHEMA60_FIELD_IDENTITY_MISMATCH")
    if any(
        field.rate != (field.field_id in APPROVED_RATE_FIELD_IDS)
        for field in golden.fields
    ):
        reasons.append("RATE_FIELD_AUTHORITY_MISMATCH")
    if (
        golden.product_version_id != APPROVED_PRODUCT_VERSION_ID
        or golden.schema_version != APPROVED_SCHEMA_VERSION
        or golden.schema_sha256 != APPROVED_SCHEMA_REGISTRY_SHA256
        or golden.source_sha256 != APPROVED_596_1_SOURCE_SHA256
        or golden.release_hash != APPROVED_GOLDEN_RELEASE_SHA256
        or golden.artifact_hash != APPROVED_GOLDEN_ARTIFACT_SHA256
        or golden.approval_subject_hash
        != APPROVED_GOLDEN_APPROVAL_SUBJECT_SHA256
        or golden.golden_596_jsonl_sha256
        != APPROVED_GOLDEN_596_JSONL_SHA256
        or not _is_sha256(golden.golden_content_digest_sha256)
    ):
        reasons.append("GOLDEN_AUTHORITY_MISMATCH")
    critical_fields = {
        field.field_id: field.critical
        for field in golden.fields
        if field.critical is not None
    }
    expected_critical_fields = {
        field_id: priority
        for priority, field_id, _field_name in APPROVED_CRITICAL18_FIELDS
    }
    if (
        golden.critical18_contract_id != "critical18-candidate.v1"
        or golden.critical18_contract_sha256 != APPROVED_CRITICAL18_SHA256
        or critical_fields != expected_critical_fields
    ):
        reasons.append("CRITICAL18_CONTRACT_MISMATCH")

    if baseline is not None:
        if tuple(field.field_id for field in baseline.fields) != (
            APPROVED_SCHEMA60_FIELD_IDS
        ):
            reasons.append("SCHEMA60_FIELD_IDENTITY_MISMATCH")
        reasons.extend(
            _field_set_reasons(
                label="BASELINE",
                fields=baseline.fields,
                expected_ids=golden_ids,
            )
        )
    if candidate is not None:
        if tuple(field.field_id for field in candidate.fields) != (
            APPROVED_SCHEMA60_FIELD_IDS
        ):
            reasons.append("SCHEMA60_FIELD_IDENTITY_MISMATCH")
        reasons.extend(
            _field_set_reasons(
                label="CANDIDATE",
                fields=candidate.fields,
                expected_ids=golden_ids,
            )
        )

    if baseline is not None and candidate is not None:
        if baseline.arm != "baseline" or candidate.arm != "candidate":
            reasons.append("ARM_ROLE_MISMATCH")
        if _shared_arm_identity(baseline.identity) != _shared_arm_identity(
            candidate.identity
        ):
            reasons.append("ARM_INPUT_IDENTITY_MISMATCH")
        if not _arm_profile_matches(baseline.identity, candidate.identity):
            reasons.append("ARM_PROFILE_MISMATCH")
        if (
            not _approved_arm_component_matches(baseline.identity)
            or not _approved_arm_component_matches(candidate.identity)
        ):
            reasons.append("ARM_PROFILE_COMPONENT_MISMATCH")
        if (
            not _approved_arm_authority_matches(baseline.identity)
            or not _approved_arm_authority_matches(candidate.identity)
            or golden.product_version_id != APPROVED_PRODUCT_VERSION_ID
            or golden.schema_version != APPROVED_SCHEMA_VERSION
            or golden.schema_sha256 != APPROVED_SCHEMA_REGISTRY_SHA256
        ):
            reasons.append("ARM_AUTHORITY_MISMATCH")
        if (
            candidate.identity.product_version_id != golden.product_version_id
            or candidate.identity.schema_version != golden.schema_version
            or candidate.identity.schema_sha256 != golden.schema_sha256
        ):
            reasons.append("GOLDEN_IDENTITY_MISMATCH")

    baseline_metrics = _quality_metrics(output=baseline, golden=golden)
    candidate_metrics = _quality_metrics(output=candidate, golden=golden)
    reasons.extend(
        _absolute_gate_reasons(
            output=candidate,
            golden=golden,
            metrics=candidate_metrics,
        )
    )

    canonical_reasons = tuple(dict.fromkeys(reasons))
    return VerticalFalsificationDecisionV1(
        terminal_outcome=(
            "MVP_VERTICAL_SLICE_NO_GO"
            if canonical_reasons
            else "QUALITY_GATES_PASS_PENDING_HUMAN_RELEASE"
        ),
        reason_codes=canonical_reasons,
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
        budget=budget,
        baseline_output_hash=baseline.output_hash,
        candidate_output_hash=candidate.output_hash,
        golden_release_hash=golden.release_hash,
        golden_artifact_hash=golden.artifact_hash,
        golden_approval_subject_hash=golden.approval_subject_hash,
        golden_596_jsonl_sha256=golden.golden_596_jsonl_sha256,
        golden_content_digest_sha256=golden.golden_content_digest_sha256,
        admission_receipt_digest_sha256=admission_receipt_digest_sha256,
        evaluator_identity_sha256=APPROVED_EVALUATOR_IDENTITY_SHA256,
    )


def _blocked_score_decision(
    *,
    reason_codes: tuple[str, ...],
    baseline_output: object,
    candidate_output: object,
    ledger: CallBudgetLedgerV1,
    admission_receipt_digest_sha256: str | None = None,
) -> VerticalFalsificationDecisionV1:
    baseline_hash = (
        baseline_output.output_hash
        if isinstance(baseline_output, FrozenArmOutputV1)
        and _is_sha256(baseline_output.output_hash)
        else None
    )
    candidate_hash = (
        candidate_output.output_hash
        if isinstance(candidate_output, FrozenArmOutputV1)
        and _is_sha256(candidate_output.output_hash)
        else None
    )
    return VerticalFalsificationDecisionV1(
        terminal_outcome="MVP_VERTICAL_SLICE_NO_GO",
        reason_codes=reason_codes,
        baseline_metrics=_empty_quality_metrics(),
        candidate_metrics=_empty_quality_metrics(),
        budget=check_call_budget(ledger),
        baseline_output_hash=baseline_hash,
        candidate_output_hash=candidate_hash,
        golden_release_hash=APPROVED_GOLDEN_RELEASE_SHA256,
        golden_artifact_hash=APPROVED_GOLDEN_ARTIFACT_SHA256,
        golden_approval_subject_hash=APPROVED_GOLDEN_APPROVAL_SUBJECT_SHA256,
        golden_596_jsonl_sha256=APPROVED_GOLDEN_596_JSONL_SHA256,
        golden_content_digest_sha256=None,
        admission_receipt_digest_sha256=admission_receipt_digest_sha256,
        evaluator_identity_sha256=APPROVED_EVALUATOR_IDENTITY_SHA256,
    )


def score_vertical_falsification(
    *,
    baseline_output: object,
    candidate_output: object,
    golden_596_jsonl_bytes: object,
    admitted_parse_artifacts: tuple[AdmittedParseArtifactV1, ...],
    ledger: CallBudgetLedgerV1,
) -> VerticalFalsificationDecisionV1:
    """Public scorer: replay admission before any exact Golden byte access."""

    admission = admit_596_1_vertical_falsification(
        admitted_parse_artifacts=admitted_parse_artifacts,
    )
    if (
        admission.status != "READY_FOR_QUALITY_FALSIFICATION"
        or admission.receipt_digest_sha256 is None
    ):
        return _blocked_score_decision(
            reason_codes=("PARSE_ARTIFACTS_NOT_ADMITTED",),
            baseline_output=baseline_output,
            candidate_output=candidate_output,
            ledger=ledger,
        )
    admission_digest = admission.receipt_digest_sha256
    if (
        not isinstance(baseline_output, FrozenArmOutputV1)
        or not isinstance(candidate_output, FrozenArmOutputV1)
        or not verify_arm_output_hash(baseline_output)
        or not verify_arm_output_hash(candidate_output)
        or baseline_output.identity.parse_artifact_receipt_digest_sha256
        != admission_digest
        or candidate_output.identity.parse_artifact_receipt_digest_sha256
        != admission_digest
    ):
        return _blocked_score_decision(
            reason_codes=("PARSE_ARTIFACT_RECEIPT_BINDING_MISMATCH",),
            baseline_output=baseline_output,
            candidate_output=candidate_output,
            ledger=ledger,
            admission_receipt_digest_sha256=admission_digest,
        )
    golden = _parse_approved_golden_bytes(golden_596_jsonl_bytes)
    if golden is None:
        return _blocked_score_decision(
            reason_codes=("GOLDEN_596_BYTES_INVALID",),
            baseline_output=baseline_output,
            candidate_output=candidate_output,
            ledger=ledger,
            admission_receipt_digest_sha256=admission_digest,
        )
    return _score_admitted_frozen_outputs(
        baseline_output=baseline_output,
        candidate_output=candidate_output,
        golden=golden,
        ledger=ledger,
        admission_receipt_digest_sha256=admission_digest,
    )


def score_admitted_frozen_arm(
    *,
    arm_output: object,
    golden_596_jsonl_bytes: object,
    admitted_parse_artifacts: tuple[AdmittedParseArtifactV1, ...],
) -> AdmittedFrozenArmScoreV1:
    """Score one MinerU arm through the exact admission and Golden custody gates."""

    admission = admit_596_1_vertical_falsification(
        admitted_parse_artifacts=admitted_parse_artifacts,
    )
    admission_digest = admission.receipt_digest_sha256
    if (
        admission.status != "READY_FOR_QUALITY_FALSIFICATION"
        or not _is_sha256(admission_digest)
    ):
        return AdmittedFrozenArmScoreV1(
            status="BLOCKED_ON_REQUIRED_CONTRACTS",
            reason_codes=("PARSE_ARTIFACTS_NOT_ADMITTED",),
            metrics=_empty_quality_metrics(),
            field_correctness=(),
            output_hash=None,
            arm_identity=None,
            admission_receipt_digest_sha256=(
                admission_digest if _is_sha256(admission_digest) else None
            ),
            golden_content_digest_sha256=None,
        )

    output = _validated_frozen_arm_output(arm_output)
    if output is None:
        return AdmittedFrozenArmScoreV1(
            status="BLOCKED_ON_REQUIRED_CONTRACTS",
            reason_codes=("ARM_OUTPUT_MALFORMED",),
            metrics=_empty_quality_metrics(),
            field_correctness=(),
            output_hash=_safe_frozen_output_hash(arm_output),
            arm_identity=None,
            admission_receipt_digest_sha256=admission_digest,
            golden_content_digest_sha256=None,
        )

    reasons: list[str] = []
    if not verify_arm_output_hash(output):
        reasons.append("ARM_OUTPUT_HASH_MISMATCH")
    else:
        identity = output.identity
        if output.arm != "candidate":
            reasons.append("ARM_ROLE_MISMATCH")
        if (
            identity.product_version_id != APPROVED_PRODUCT_VERSION_ID
            or identity.source_sha256 != APPROVED_596_1_SOURCE_SHA256
            or identity.schema_version != APPROVED_SCHEMA_VERSION
            or identity.schema_sha256 != APPROVED_SCHEMA_REGISTRY_SHA256
        ):
            reasons.append("ARM_AUTHORITY_MISMATCH")
        if (
            identity.parser_identity_sha256
            != APPROVED_CANDIDATE_PARSER_IDENTITY_SHA256
            or (identity.parser_id, identity.parser_mode, identity.parser_attempt)
            != ("mineru-cloud-pipeline", "bounded_upgrade", 2)
        ):
            reasons.append("MINERU_PARSER_IDENTITY_MISMATCH")
        if (
            identity.prompt_identity_sha256 != APPROVED_PROMPT_IDENTITY_SHA256
            or identity.budget_identity_sha256 != APPROVED_BUDGET_IDENTITY_SHA256
            or identity.normalizer_identity_sha256
            != APPROVED_NORMALIZER_IDENTITY_SHA256
            or identity.comparator_identity_sha256
            != APPROVED_COMPARATOR_IDENTITY_SHA256
        ):
            reasons.append("ARM_NON_MODEL_COMPONENT_MISMATCH")
        if identity.parse_artifact_receipt_digest_sha256 != admission_digest:
            reasons.append("PARSE_ARTIFACT_RECEIPT_BINDING_MISMATCH")
        if tuple(field.field_id for field in output.fields) != (
            APPROVED_SCHEMA60_FIELD_IDS
        ):
            reasons.append("SCHEMA60_FIELD_IDENTITY_MISMATCH")

    if reasons:
        return AdmittedFrozenArmScoreV1(
            status="BLOCKED_ON_REQUIRED_CONTRACTS",
            reason_codes=tuple(dict.fromkeys(reasons)),
            metrics=_empty_quality_metrics(),
            field_correctness=(),
            output_hash=None if output is None else output.output_hash,
            arm_identity=None if output is None else output.identity,
            admission_receipt_digest_sha256=admission_digest,
            golden_content_digest_sha256=None,
        )

    golden = _parse_approved_golden_bytes(golden_596_jsonl_bytes)
    if golden is None:
        return AdmittedFrozenArmScoreV1(
            status="GOLDEN_INVALID",
            reason_codes=("GOLDEN_596_BYTES_INVALID",),
            metrics=_empty_quality_metrics(),
            field_correctness=(),
            output_hash=output.output_hash,
            arm_identity=output.identity,
            admission_receipt_digest_sha256=admission_digest,
            golden_content_digest_sha256=None,
        )

    evaluations = _field_evaluations(output=output, golden=golden)
    metrics = _quality_metrics(output=output, golden=golden)
    gate_reasons = _absolute_gate_reasons(
        output=output,
        golden=golden,
        metrics=metrics,
    )
    return AdmittedFrozenArmScoreV1(
        status="SCORED",
        reason_codes=tuple(gate_reasons),
        metrics=metrics,
        field_correctness=tuple(
            ArmFieldCorrectnessV1(
                field_id=item.field_id,
                critical_priority=item.critical_priority,
                rate_field=item.rate_field,
                tri_state_correct=item.tri_state_correct,
                exact_field_correct=item.exact_field_correct,
                known_evidence_present=item.known_evidence_present,
                rate_locator_complete=item.rate_locator_complete,
            )
            for item in evaluations
        ),
        output_hash=output.output_hash,
        arm_identity=output.identity,
        admission_receipt_digest_sha256=admission_digest,
        golden_content_digest_sha256=golden.golden_content_digest_sha256,
    )


def check_call_budget(ledger: CallBudgetLedgerV1) -> BudgetDecisionV1:
    """Apply the frozen 6 + 8 + 4 limits without fallback or extra retry."""

    reasons: list[str] = []
    if ledger.baseline_calls > 6:
        reasons.append("BASELINE_CALL_BUDGET_EXCEEDED")
    if ledger.candidate_main_calls > 8:
        reasons.append("CANDIDATE_MAIN_CALL_BUDGET_EXCEEDED")
    if ledger.candidate_repair_calls > 4:
        reasons.append("CANDIDATE_REPAIR_CALL_BUDGET_EXCEEDED")
    if ledger.fallback_calls:
        reasons.append("FALLBACK_CALL_FORBIDDEN")
    if ledger.retry_calls:
        reasons.append("EXTRA_RETRY_FORBIDDEN")
    if ledger.total_calls > 18:
        reasons.append("TOTAL_CALL_BUDGET_EXCEEDED")
    return BudgetDecisionV1(
        status="MVP_VERTICAL_SLICE_NO_GO" if reasons else "WITHIN_BUDGET",
        reason_codes=tuple(reasons),
        total_calls=ledger.total_calls,
    )


def _load_contract(
    requirement: RequiredPublicContract,
) -> ResolvedPublicContract | None:
    try:
        if find_spec(requirement.module) is None:
            return None
        module = import_module(requirement.module)
        exports = tuple(
            (symbol, getattr(module, symbol)) for symbol in requirement.symbols
        )
        builder = next(
            (
                value
                for symbol, value in exports
                if symbol == "build_mineru_parsed_document_v1"
            ),
            None,
        )
        captured = dict(exports)
        native_error = captured.get("NativeMinerUStructureError")
        if (
            not callable(builder)
            or captured.get("ParsedDocumentV1") is not ParsedDocumentV1
            or captured.get("ParseManifestV1") is not ParseManifestV1
            or captured.get("ParseQualityDecisionV1") is not ParseQualityDecisionV1
            or not isinstance(native_error, type)
            or not issubclass(native_error, Exception)
        ):
            return None
    except Exception:
        # Contract discovery is an untrusted dependency boundary. Process-control
        # exceptions still propagate because they do not inherit from Exception.
        return None
    return ResolvedPublicContract(
        contract_id=requirement.contract_id,
        exports=exports,
    )


def _admitted_parse_artifact_digest(
    receipts: tuple[AdmittedParseArtifactV1, ...],
    *,
    native_mineru: ResolvedPublicContract,
) -> str | None:
    if len(receipts) != len(EXPECTED_596_1_PARSE_SOURCES):
        return None
    builder = native_mineru.get("build_mineru_parsed_document_v1")
    if not callable(builder):
        return None
    bindings: list[dict[str, object]] = []
    for receipt, (expected_role, expected_source, expected_profile) in zip(
        receipts,
        EXPECTED_596_1_PARSE_SOURCES,
        strict=True,
    ):
        if not isinstance(receipt, AdmittedParseArtifactV1):
            return None
        try:
            document = ParsedDocumentV1.model_validate(receipt.document)
            manifest = ParseManifestV1.model_validate(receipt.manifest)
            decision = ParseQualityDecisionV1.model_validate(receipt.decision)
            resolution = MaterialProfileResolution.model_validate(
                receipt.material_profile_resolution
            )
        except Exception:
            return None
        if (
            not isinstance(receipt.sanitized_structure, bytes)
            or not isinstance(resolution, MaterialProfileResolution)
            or receipt.raw_structure_sha256 is None
            or receipt.sanitized_structure_sha256 is None
            or not _is_sha256(receipt.raw_structure_sha256)
            or not _is_sha256(receipt.sanitized_structure_sha256)
        ):
            return None
        try:
            receipt_mismatch = (
                receipt.role != expected_role
            or receipt.source_sha256 != expected_source
            or not all(
                _is_sha256(value)
                for value in (
                    receipt.source_sha256,
                    receipt.artifact_sha256,
                    receipt.manifest_sha256,
                    receipt.decision_sha256,
                )
            )
            or document.document_hash != receipt.artifact_sha256
            or manifest.document_hash != receipt.artifact_sha256
            or manifest.manifest_hash != receipt.manifest_sha256
            or decision.manifest_hash != receipt.manifest_sha256
            or decision.decision_hash != receipt.decision_sha256
            or document.subject != manifest.subject
            or document.subject != decision.subject
            or document.parser != manifest.parser
            or document.attempt != manifest.attempt
            or document.snapshot != manifest.snapshot
            or document.output_facts != manifest.output_facts
            or document.subject.product_version_id != "596-1"
            or document.subject.material_profile_id != expected_profile
            or document.subject.source_sha256 != expected_source
            or document.subject.material_profile_binding_hash
            != resolution.binding_hash
            or resolution.profile.profile_id != expected_profile
            or resolution.profile.material_role != expected_role
            or resolution.profile.source.sha256 != expected_source
            or resolution.catalog_hash
            != APPROVED_MATERIAL_PROFILE_CATALOG_SHA256
            or resolution.profile.required_parse_capabilities
            != EXPECTED_596_1_REQUIRED_CAPABILITIES[expected_role]
            or resolution.parse_policy_receipt.required_parse_capabilities
            != EXPECTED_596_1_REQUIRED_CAPABILITIES[expected_role]
            or resolution.request.space_id != document.subject.space_id
            or resolution.request.product_version
            != document.subject.product_version_id
            or resolution.request.source != resolution.profile.source
            or decision.decision != "ADMIT"
            or decision.admitted_attempt_id != document.attempt.attempt_id
            or bool(decision.reason_codes)
            or bool(manifest.unsatisfied_capabilities)
            or decision.measured_facts.required_capabilities
            != manifest.required_capabilities
            or decision.measured_facts.satisfied_capabilities
            != manifest.satisfied_capabilities
            or decision.measured_facts.unsatisfied_capabilities
            != manifest.unsatisfied_capabilities
            )
        except Exception:
            return None
        if receipt_mismatch:
            return None
        try:
            replayed_document, replayed_manifest, replayed_decision = (
                builder(
                    receipt.sanitized_structure,
                    expected_raw_sha256=receipt.raw_structure_sha256,
                    expected_sanitized_sha256=receipt.sanitized_structure_sha256,
                    subject=document.subject,
                    parser=document.parser,
                    attempt=document.attempt,
                    snapshot=document.snapshot,
                    output_facts=document.output_facts,
                    material_profile_resolution=resolution,
                )
            )
            replayed_document = ParsedDocumentV1.model_validate(replayed_document)
            replayed_manifest = ParseManifestV1.model_validate(replayed_manifest)
            replayed_decision = ParseQualityDecisionV1.model_validate(replayed_decision)
        except Exception:
            return None
        if (
            replayed_document != document
            or replayed_manifest != manifest
            or replayed_decision != decision
            or replayed_document.document_hash != receipt.artifact_sha256
            or replayed_manifest.manifest_hash != receipt.manifest_sha256
            or replayed_decision.decision_hash != receipt.decision_sha256
            or replayed_decision.decision != "ADMIT"
        ):
            return None
        bindings.append(
            {
                "role": receipt.role,
                "source_sha256": receipt.source_sha256,
                "document_hash": receipt.artifact_sha256,
                "manifest_hash": receipt.manifest_sha256,
                "decision_hash": receipt.decision_sha256,
                "raw_structure_sha256": receipt.raw_structure_sha256,
                "sanitized_structure_sha256": receipt.sanitized_structure_sha256,
                "sanitized_bytes_sha256": _sha256_bytes(
                    receipt.sanitized_structure
                ),
                "material_profile_binding_hash": resolution.binding_hash,
                "material_profile_catalog_hash": resolution.catalog_hash,
            }
        )
    return canonical_hash(
        "admission-061-parse-artifact-receipts.v1",
        {"product_version_id": "596-1", "receipts": tuple(bindings)},
    )


def admit_596_1_vertical_falsification(
    *,
    admitted_parse_artifacts: tuple[AdmittedParseArtifactV1, ...] = (),
    admitted_parse_artifact_sha256: tuple[str, ...] = (),
) -> VerticalFalsificationAdmission:
    """Fail closed before Provider or Golden access until quality inputs exist."""

    resolved_contracts = tuple(
        (requirement, _load_contract(requirement))
        for requirement in REQUIRED_PUBLIC_CONTRACTS
    )
    missing = tuple(
        requirement.contract_id
        for requirement, module in resolved_contracts
        if module is None
    )
    native_mineru = resolved_contracts[0][1]
    receipt_digest = (
        None
        if admitted_parse_artifact_sha256 or native_mineru is None
        else _admitted_parse_artifact_digest(
            admitted_parse_artifacts,
            native_mineru=native_mineru,
        )
    )
    if receipt_digest is None:
        missing = (*missing, ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID)
    if missing:
        return VerticalFalsificationAdmission(
            status="BLOCKED_ON_REQUIRED_CONTRACTS",
            missing_contracts=missing,
        )
    return VerticalFalsificationAdmission(
        status="READY_FOR_QUALITY_FALSIFICATION",
        missing_contracts=(),
        receipt_digest_sha256=receipt_digest,
    )


__all__ = [
    "ADMITTED_PARSE_ARTIFACTS_CONTRACT_ID",
    "AdmittedParseArtifactV1",
    "AdmittedFrozenArmScoreV1",
    "APPROVED_ARM_PROFILE_SHA256",
    "APPROVED_CRITICAL18_FIELDS",
    "APPROVED_CRITICAL18_FIELD_IDS",
    "APPROVED_CRITICAL18_SHA256",
    "ArmFieldOutputV1",
    "ArmFieldCorrectnessV1",
    "ArmInputIdentityV1",
    "ArmQualityMetricsV1",
    "BudgetDecisionV1",
    "CallBudgetLedgerV1",
    "EvidenceLocatorV1",
    "FrozenArmOutputV1",
    "REQUIRED_PUBLIC_CONTRACTS",
    "RequiredPublicContract",
    "VerticalFalsificationAdmission",
    "VerticalFalsificationDecisionV1",
    "admit_596_1_vertical_falsification",
    "check_call_budget",
    "freeze_arm_output",
    "score_vertical_falsification",
    "score_admitted_frozen_arm",
    "verify_arm_output_hash",
]
