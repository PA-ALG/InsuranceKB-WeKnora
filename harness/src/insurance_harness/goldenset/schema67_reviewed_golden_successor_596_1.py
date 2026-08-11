"""Canonical reviewed-data successor for product 596-1 medical Schema67.

This module does not create a final approved Golden.  It preserves the exact 51
directly projected reviewed rows and closes the remaining 16 Schema67 fields as
reviewed ``unknown`` because the current three source materials do not cover them.
It emits an unsigned whole-batch payload without inventing a value, Evidence, page,
timestamp, key, signature, or approval receipt.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, Final, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.goldenset.schema67_human_annotation_kit_596_1 import (
    AnnotationMappingDecisionV1,
    build_schema67_human_annotation_kit_596_1,
)
from insurance_harness.knowledge_compiler.medical_schema_pack_596_1 import (
    make_medical_schema_pack_596_1,
)

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
NonBlankStr = Annotated[str, StringConstraints(min_length=1, max_length=2048)]
TriState = Literal["present", "absent_explicitly", "unknown"]
MappingAction = Literal["reuse", "rename", "split", "merge", "new", "N-A"]
ReviewStatus = Literal["REVIEWED", "PENDING_RESIDUAL"]
ResidualReason = Literal[
    "TRI_STATE_CONFLICT",
    "MULTI_SOURCE_MERGE_REQUIRES_CANONICAL_DECISION",
    "LATEST_REVIEWED_SOURCE_MISSING",
]
UnknownReason = Literal["NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS"]

_CONTRACT: Final[Literal["schema67-reviewed-golden-successor-596-1.v1"]] = (
    "schema67-reviewed-golden-successor-596-1.v1"
)
_OLD60_SHA256: Final[str] = "562c37c7cf262e2e78f0b3ca4b7de4b0dab2f407d3cd7318a8a69b5dca33d8fb"
_LATEST71_SHA256: Final[str] = "25c62051d04c8bd56f3770e77d071ae18945daee5dce6b8fb584937555260be4"
_LATEST71_REPORT_SHA256: Final[str] = (
    "4dde5c35e311af3ce4a0c01e2309ff65e872de77ee4cff0762dc951c42c00e73"
)
_OLD60_APPROVAL_SHA256: Final[str] = (
    "484fdb78bdc73109bccd4d771e41089574b26f28c1992b67b2114524a515c868"
)
_USER_REVIEW_FACT_REF: Final[str] = "user-authority:2026-08-11:latest71-human-review-completed"
_USER_REVIEWER_FACT_REF: Final[str] = (
    "user-authority:2026-08-11:latest71-reviewed-by-linyao-confirmed-by-workspace-owner-houjing"
)
_COVERAGE_GAP_SOURCE_SHA256: Final[str] = (
    "e58d0ffdc7e0c16d98df13f1be51b5d747bf81102f0e35f01612a969c2164506"
)
_COVERAGE_GAP_MANIFEST_EXTERNAL_SHA256: Final[str] = (
    "2e98c5e45f9c4447b61e9b0055f12774062a8ce2e96e6f48ed59156d4a11acf2"
)
_COVERAGE_GAP_MANIFEST_SELF_SHA256: Final[str] = (
    "9071fe763efd18aea7afca22d3dfe2d7911067237c118999744e72cfeceda70d"
)
_NOT_COVERED_FIELD_IDS: Final[tuple[str, ...]] = (
    "product_type",
    "marketing_tagline",
    "product_overview",
    "health_declaration_requirements",
    "eligible_occupation_classes",
    "premium_grace_period",
    "guaranteed_renewal_status",
    "premium_adjustment_rules",
    "direct_billing_and_advance_payment_rules",
    "eligible_service_packages",
    "tax_qualified_status",
    "tax_benefit_rules",
    "objection_handling_scripts",
    "product_faq",
    "four_step_sales_script",
    "sales_pitch_script",
)


class Schema67ReviewedGoldenSuccessorError(ValueError):
    """Stable fail-closed error for the reviewed Schema67 successor."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _ClosedModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class ReviewedSourceIdentityV1(_ClosedModel):
    source_id: NonBlankStr
    sha256: Sha256Hex
    row_count: int = Field(ge=1)
    authority_level: Literal["HUMAN_APPROVED_S0_Q_MIGRATION_INPUT", "HUMAN_REVIEWED_SOURCE"]
    annotator_model_id: NonBlankStr
    approval_receipt_sha256: Sha256Hex | None = None


class ReviewAttestationSourceV1(_ClosedModel):
    source_kind: Literal[
        "REVIEWED_DATASET_BYTES",
        "DETERMINISTIC_VERIFICATION_REPORT",
        "USER_AUTHORITY_FACT",
    ]
    reference: NonBlankStr
    sha256: Sha256Hex | None = None


class Schema67ReviewMetadataV1(_ClosedModel):
    contract: Literal["schema67-human-review-metadata-596-1.v1"]
    annotator_model_id: Literal["claude-fable-5"]
    source_review_status: Literal["COMPLETED"]
    reviewed_by: Literal["linyao"]
    reviewed_at: None = None
    approval_receipt_sha256: None = None
    attestation_sources: tuple[ReviewAttestationSourceV1, ...]

    @model_validator(mode="after")
    def _validate_attestations(self) -> Schema67ReviewMetadataV1:
        if tuple(item.source_kind for item in self.attestation_sources) != (
            "REVIEWED_DATASET_BYTES",
            "DETERMINISTIC_VERIFICATION_REPORT",
            "USER_AUTHORITY_FACT",
            "USER_AUTHORITY_FACT",
        ):
            raise ValueError("SCHEMA67_REVIEW_ATTESTATION_INVALID")
        if self.attestation_sources[-1].sha256 is not None:
            raise ValueError("SCHEMA67_REVIEW_ATTESTATION_INVALID")
        return self


class Schema67SuccessorMappingV1(_ClosedModel):
    mapping_id: NonBlankStr
    source_dataset: Literal["old60", "latest71"]
    source_field_id: NonBlankStr | None
    source_display_name: NonBlankStr | None
    target_field_ids: tuple[NonBlankStr, ...]
    action: MappingAction
    authority_level: Literal["HUMAN_APPROVED_S0_Q_MIGRATION_INPUT", "HUMAN_REVIEWED_SOURCE"]
    migration_status: Literal["PROPOSED_MIGRATION", "REVIEWED_SOURCE"]
    source_state: TriState | None
    source_risk_level: Literal["low", "medium", "high"] | None
    mandatory_review_flag: bool
    tri_state_conflict: bool


class Schema67SuccessorEvidenceV1(_ClosedModel):
    source_role: Literal["terms", "brochure", "rate"]
    document_name: Literal["保险条款.pdf", "产品说明书.pdf", "费率表.pdf"]
    knowledge_id: NonBlankStr
    parse_attempt: int = Field(ge=1)
    file_sha256: Sha256Hex
    page: int = Field(ge=1)
    quote: NonBlankStr
    quote_sha256: Sha256Hex
    bbox: None = None
    coordinate_space: None = None
    bbox_status: Literal["PENDING_CAPTURE"] = "PENDING_CAPTURE"
    evidence_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_evidence_hash(self) -> Schema67SuccessorEvidenceV1:
        if self.quote_sha256 != hashlib.sha256(self.quote.encode("utf-8")).hexdigest():
            raise ValueError("SCHEMA67_SUCCESSOR_QUOTE_HASH_INVALID")
        if self.evidence_sha256 != _evidence_sha256(self):
            raise ValueError("SCHEMA67_SUCCESSOR_EVIDENCE_HASH_INVALID")
        return self


class Schema67SuccessorFieldV1(_ClosedModel):
    ordinal: int = Field(ge=1, le=67)
    field_id: NonBlankStr
    section_id: NonBlankStr
    review_status: ReviewStatus
    residual_reason: ResidualReason | None
    unknown_reason: UnknownReason | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    mapping_action: MappingAction
    source_field_ids: tuple[NonBlankStr, ...]
    source_record_sha256: Sha256Hex | None
    source_record_sha256s: tuple[Sha256Hex, ...]
    annotator_model_id: Literal["claude-fable-5"]
    state: TriState | None
    value: str | None
    confidence: Literal["low", "medium", "high"] | None
    risk_level: Literal["low", "medium", "high"] | None
    reasoning: str | None
    flags: tuple[str, ...]
    evidence: tuple[Schema67SuccessorEvidenceV1, ...]
    field_metadata_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_state_and_hash(self) -> Schema67SuccessorFieldV1:
        reviewed = self.review_status == "REVIEWED"
        if reviewed:
            if self.residual_reason is not None or self.state is None:
                raise ValueError("SCHEMA67_SUCCESSOR_REVIEWED_FIELD_INVALID")
            if self.unknown_reason is None and (
                len(self.source_field_ids) != 1
                or len(self.source_record_sha256s) != 1
                or self.source_record_sha256 != self.source_record_sha256s[0]
                or self.mapping_action not in {"reuse", "rename"}
            ):
                raise ValueError("SCHEMA67_SUCCESSOR_REVIEWED_FIELD_INVALID")
            if self.unknown_reason is not None and self.state != "unknown":
                raise ValueError("SCHEMA67_SUCCESSOR_REVIEWED_FIELD_INVALID")
            if self.state == "present" and (self.value is None or not self.evidence):
                raise ValueError("SCHEMA67_SUCCESSOR_REVIEWED_FIELD_INVALID")
            if self.state == "absent_explicitly" and (self.value is not None or not self.evidence):
                raise ValueError("SCHEMA67_SUCCESSOR_REVIEWED_FIELD_INVALID")
            if self.state == "unknown" and (self.value is not None or self.evidence):
                raise ValueError("SCHEMA67_SUCCESSOR_REVIEWED_FIELD_INVALID")
        elif (
            self.residual_reason is None
            or self.unknown_reason is not None
            or self.state is not None
            or self.value is not None
            or self.evidence
        ):
            raise ValueError("SCHEMA67_SUCCESSOR_PENDING_FIELD_INVALID")
        if self.field_metadata_sha256 != _field_metadata_sha256(self):
            raise ValueError("SCHEMA67_SUCCESSOR_FIELD_HASH_INVALID")
        return self


class Schema67SuccessorSummaryV1(_ClosedModel):
    contract: Literal["schema67-reviewed-golden-successor-summary-596-1.v1"]
    field_count: Literal[67]
    reviewed_field_count: Literal[67]
    pending_residual_field_count: Literal[0]
    human_annotation_zero: Literal[False]
    review_completed: Literal[True]
    authority_metadata_complete: Literal[False]
    whole_batch_signature_present: Literal[False]
    evaluator_formal_conclusion_allowed: Literal[False]


class Schema67WholeBatchReadyToSignV1(_ClosedModel):
    contract: Literal["schema67-reviewed-golden-whole-batch-ready-to-sign-596-1.v1"]
    status: Literal["READY_TO_SIGN"]
    product_version_id: Literal["596-1"]
    schema_pack_id: Literal["medical-schema67.v1"]
    schema_pack_sha256: Sha256Hex
    golden_set_sha256: Sha256Hex
    reviewed_field_count: Literal[67]
    residual_pending_field_ids: tuple[NonBlankStr, ...]
    reviewed_by: Literal["linyao"]
    reviewed_at: None = None
    key_id: None = None
    signature: None = None
    approval_receipt_sha256: None = None
    signing_payload_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_payload_hash(self) -> Schema67WholeBatchReadyToSignV1:
        if self.signing_payload_sha256 != _ready_to_sign_sha256(self):
            raise ValueError("SCHEMA67_SUCCESSOR_SIGNING_PAYLOAD_INVALID")
        return self


class Schema67ReviewedGoldenSuccessor5961V1(_ClosedModel):
    contract: Literal["schema67-reviewed-golden-successor-596-1.v1"]
    source_review_status: Literal["COMPLETED"]
    schema67_mapping_status: Literal["COMPLETE_67"]
    golden_admission_status: Literal["BLOCKED_RECEIPT_UNVERIFIED"]
    product_version_id: Literal["596-1"]
    schema_pack_id: Literal["medical-schema67.v1"]
    schema_pack_sha256: Sha256Hex
    ordered_field_ids: tuple[NonBlankStr, ...]
    old60_input: ReviewedSourceIdentityV1
    latest71_input: ReviewedSourceIdentityV1
    review_metadata: Schema67ReviewMetadataV1
    old60_mappings: tuple[Schema67SuccessorMappingV1, ...]
    latest71_mappings: tuple[Schema67SuccessorMappingV1, ...]
    fields: tuple[Schema67SuccessorFieldV1, ...]
    residual_pending_field_ids: tuple[NonBlankStr, ...]
    summary: Schema67SuccessorSummaryV1
    ready_to_sign: Schema67WholeBatchReadyToSignV1
    golden_set_sha256: Sha256Hex

    @model_validator(mode="after")
    def _validate_topology_and_hash(self) -> Schema67ReviewedGoldenSuccessor5961V1:
        if (
            len(self.ordered_field_ids) != 67
            or len(set(self.ordered_field_ids)) != 67
            or tuple(row.field_id for row in self.fields) != self.ordered_field_ids
            or tuple(row.ordinal for row in self.fields) != tuple(range(1, 68))
            or any(row.review_status != "REVIEWED" for row in self.fields)
            or any(row.residual_reason is not None for row in self.fields)
            or self.residual_pending_field_ids
            or tuple(row.field_id for row in self.fields if row.unknown_reason is not None)
            != _NOT_COVERED_FIELD_IDS
            or self.ready_to_sign.residual_pending_field_ids != self.residual_pending_field_ids
            or self.ready_to_sign.golden_set_sha256 != self.golden_set_sha256
        ):
            raise ValueError("SCHEMA67_SUCCESSOR_TOPOLOGY_INVALID")
        if self.golden_set_sha256 != schema67_reviewed_golden_successor_sha256(self):
            raise ValueError("SCHEMA67_SUCCESSOR_HASH_INVALID")
        return self


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError("SCHEMA67_SUCCESSOR_CANONICAL_VALUE_INVALID")


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _domain_hash(domain: str, value: object) -> str:
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + _canonical_json_bytes(value)).hexdigest()


def _evidence_sha256(value: Schema67SuccessorEvidenceV1 | Mapping[str, object]) -> str:
    payload = (
        value.model_dump(mode="json", exclude={"evidence_sha256"})
        if isinstance(value, BaseModel)
        else {key: item for key, item in value.items() if key != "evidence_sha256"}
    )
    return _domain_hash("schema67-reviewed-golden-evidence-596-1.v1", payload)


def _field_metadata_sha256(value: Schema67SuccessorFieldV1 | Mapping[str, object]) -> str:
    payload = (
        value.model_dump(mode="json", exclude={"field_metadata_sha256"})
        if isinstance(value, BaseModel)
        else {key: item for key, item in value.items() if key != "field_metadata_sha256"}
    )
    return _domain_hash("schema67-reviewed-golden-field-596-1.v1", payload)


def _ready_to_sign_sha256(
    value: Schema67WholeBatchReadyToSignV1 | Mapping[str, object],
) -> str:
    payload = (
        value.model_dump(mode="json", exclude={"signing_payload_sha256"})
        if isinstance(value, BaseModel)
        else {key: item for key, item in value.items() if key != "signing_payload_sha256"}
    )
    return _domain_hash("schema67-reviewed-golden-ready-to-sign-596-1.v1", payload)


def schema67_reviewed_golden_successor_sha256(
    value: Schema67ReviewedGoldenSuccessor5961V1 | Mapping[str, object],
) -> str:
    if isinstance(value, BaseModel):
        payload = value.model_dump(mode="json", exclude={"golden_set_sha256", "ready_to_sign"})
    else:
        payload = {
            key: item
            for key, item in value.items()
            if key not in {"golden_set_sha256", "ready_to_sign"}
        }
    return _domain_hash(_CONTRACT, payload)


def canonical_schema67_reviewed_golden_successor_bytes(
    successor: Schema67ReviewedGoldenSuccessor5961V1,
) -> bytes:
    return _canonical_json_bytes(successor.model_dump(mode="json")) + b"\n"


def _sealed_artifact_payload(
    *, contract: str, payload: Mapping[str, object], hash_field: str
) -> bytes:
    body = {"contract": contract, **payload}
    body[hash_field] = _domain_hash(contract, body)
    return _canonical_json_bytes(body) + b"\n"


def canonical_schema67_reviewed_golden_artifact_files(
    successor: Schema67ReviewedGoldenSuccessor5961V1,
) -> dict[str, bytes]:
    """Return the exact closed artifact set; manifest is built last and is non-circular."""

    old60_mapping = _sealed_artifact_payload(
        contract="schema67-old60-to-67-mapping-596-1.v1",
        payload={
            "source_sha256": successor.old60_input.sha256,
            "target_schema_pack_sha256": successor.schema_pack_sha256,
            "mappings": successor.old60_mappings,
        },
        hash_field="mapping_sha256",
    )
    latest71_mapping = _sealed_artifact_payload(
        contract="schema67-reviewed71-to-67-mapping-596-1.v1",
        payload={
            "source_sha256": successor.latest71_input.sha256,
            "target_schema_pack_sha256": successor.schema_pack_sha256,
            "mappings": successor.latest71_mappings,
        },
        hash_field="mapping_sha256",
    )
    old60_mapping_sha256 = json.loads(old60_mapping)["mapping_sha256"]
    latest71_mapping_sha256 = json.loads(latest71_mapping)["mapping_sha256"]
    schema67_mapping_sha256 = _domain_hash(
        "schema67-reviewed-golden-mapping-authority-596-1.v1",
        {
            "old60_mapping_sha256": old60_mapping_sha256,
            "latest71_mapping_sha256": latest71_mapping_sha256,
        },
    )
    files = {
        "golden67-successor.json": canonical_schema67_reviewed_golden_successor_bytes(successor),
        "mapping-old60-to-schema67.json": old60_mapping,
        "mapping-reviewed71-to-schema67.json": latest71_mapping,
        "review-metadata.json": _sealed_artifact_payload(
            contract="schema67-reviewed-source-authority-metadata-596-1.v1",
            payload={
                "golden_set_sha256": successor.golden_set_sha256,
                "review_metadata": successor.review_metadata,
            },
            hash_field="metadata_sha256",
        ),
        "review-attestation.json": _sealed_artifact_payload(
            contract="schema67-review-attestation-event-596-1.v1",
            payload={
                "source_review_status": successor.source_review_status,
                "reviewer_id": successor.review_metadata.reviewed_by,
                "annotator_model_id": successor.review_metadata.annotator_model_id,
                "reviewed_at": successor.review_metadata.reviewed_at,
                "attestor_id": "workspace-owner-houjing",
                "source_thread_id": "019fda9b-f72b-7661-b88f-f2ae1bb02634",
                "attested_at": "2026-08-11T11:21:07Z",
                "old60_source_sha256": successor.old60_input.sha256,
                "latest71_source_sha256": successor.latest71_input.sha256,
                "schema67_mapping_sha256": schema67_mapping_sha256,
                "golden_set_sha256": successor.golden_set_sha256,
                "schema67_mapping_status": successor.schema67_mapping_status,
                "golden_admission_status": successor.golden_admission_status,
                "receipt_status": "UNVERIFIED",
                "signature": None,
            },
            hash_field="attestation_sha256",
        ),
        "source-coverage-gaps.json": _sealed_artifact_payload(
            contract="schema67-current-source-coverage-gaps-596-1.v1",
            payload={
                "golden_set_sha256": successor.golden_set_sha256,
                "source_artifact_sha256": _COVERAGE_GAP_SOURCE_SHA256,
                "source_manifest_external_sha256": _COVERAGE_GAP_MANIFEST_EXTERNAL_SHA256,
                "source_manifest_self_sha256": _COVERAGE_GAP_MANIFEST_SELF_SHA256,
                "informational_only": True,
                "decision_required": False,
                "publish_blocking": False,
                "field_ids": _NOT_COVERED_FIELD_IDS,
                "rows": tuple(
                    {
                        "ordinal": row.ordinal,
                        "field_id": row.field_id,
                        "state": row.state,
                        "value": row.value,
                        "evidence": row.evidence,
                        "unknown_reason": row.unknown_reason,
                        "page": None,
                        "citation_status": "NOT_APPLICABLE_UNTIL_SOURCE_EXISTS",
                        "bbox": None,
                        "bbox_status": "NOT_APPLICABLE_UNTIL_SOURCE_EXISTS",
                    }
                    for row in successor.fields
                    if row.unknown_reason is not None
                ),
            },
            hash_field="coverage_gap_sha256",
        ),
        "whole-batch-ready-to-sign.json": _canonical_json_bytes(
            successor.ready_to_sign.model_dump(mode="json")
        )
        + b"\n",
    }
    manifest_payload: dict[str, object] = {
        "contract": "schema67-reviewed-golden-successor-manifest-596-1.v1",
        "source_review_status": successor.source_review_status,
        "schema67_mapping_status": successor.schema67_mapping_status,
        "golden_admission_status": successor.golden_admission_status,
        "product_version_id": successor.product_version_id,
        "schema_pack_id": successor.schema_pack_id,
        "schema_pack_sha256": successor.schema_pack_sha256,
        "golden_set_sha256": successor.golden_set_sha256,
        "reviewed_field_count": successor.summary.reviewed_field_count,
        "pending_residual_field_count": successor.summary.pending_residual_field_count,
        "review_completion_fact": True,
        "authority_metadata_complete": False,
        "cryptographic_receipt_signed": False,
        "evaluator_formal_conclusion_allowed": False,
        "files": {
            name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(files.items())
        },
    }
    manifest_payload["manifest_sha256"] = _domain_hash(
        "schema67-reviewed-golden-successor-manifest-596-1.v1", manifest_payload
    )
    files["manifest.json"] = _canonical_json_bytes(manifest_payload) + b"\n"
    return files


def _parse_exact_jsonl(
    payload: bytes, *, expected_sha256: str, expected_count: int
) -> tuple[dict[str, Any], ...]:
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_INPUT_IDENTITY_INVALID")
    try:
        rows = tuple(json.loads(line) for line in payload.splitlines() if line)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_INPUT_INVALID") from None
    if (
        len(rows) != expected_count
        or any(not isinstance(row, dict) for row in rows)
        or len({row.get("field_id") for row in rows}) != expected_count
    ):
        raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_INPUT_INVALID")
    return rows


def _convert_mapping(
    item: AnnotationMappingDecisionV1, *, latest: bool
) -> Schema67SuccessorMappingV1:
    return Schema67SuccessorMappingV1(
        mapping_id=item.mapping_id.replace("draft71:", "latest71:"),
        source_dataset="latest71" if latest else "old60",
        source_field_id=item.source_field_id,
        source_display_name=item.source_display_name,
        target_field_ids=item.target_field_ids,
        action=item.action,
        authority_level=(
            "HUMAN_REVIEWED_SOURCE" if latest else "HUMAN_APPROVED_S0_Q_MIGRATION_INPUT"
        ),
        migration_status="REVIEWED_SOURCE" if latest else "PROPOSED_MIGRATION",
        source_state=item.source_state_suggestion,
        source_risk_level=item.source_risk_level,
        mandatory_review_flag=item.mandatory_human_review,
        tri_state_conflict=item.tri_state_conflict,
    )


def _record_sha256(row: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(row)).hexdigest()


def _source_revision_by_document() -> dict[str, tuple[str, int, str, int, str]]:
    return {
        "保险条款.pdf": (
            "terms",
            2,
            "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
            39,
            "f987fc16-222a-4246-8ca0-22c1a81dd6d9",
        ),
        "产品说明书.pdf": (
            "brochure",
            1,
            "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279",
            27,
            "1265a343-c408-4620-8eed-c4f6a2adadc2",
        ),
        "费率表.pdf": (
            "rate",
            1,
            "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb",
            2,
            "32402c40-6131-4049-8080-cc5b68188cd3",
        ),
    }


def _evidence_rows(row: Mapping[str, Any]) -> tuple[Schema67SuccessorEvidenceV1, ...]:
    output: list[Schema67SuccessorEvidenceV1] = []
    revisions = _source_revision_by_document()
    raw_evidence = row.get("evidence")
    if not isinstance(raw_evidence, list):
        raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_SOURCE_RECORD_INVALID")
    for item in raw_evidence:
        if not isinstance(item, dict):
            raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_SOURCE_RECORD_INVALID")
        document = item.get("doc")
        page = item.get("page")
        quote = item.get("quote")
        if document not in revisions or not isinstance(page, int) or not isinstance(quote, str):
            raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_SOURCE_RECORD_INVALID")
        role, attempt, file_sha256, page_count, knowledge_id = revisions[document]
        if page < 1 or page > page_count or not quote:
            raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_SOURCE_RECORD_INVALID")
        payload: dict[str, object] = {
            "source_role": role,
            "document_name": document,
            "knowledge_id": knowledge_id,
            "parse_attempt": attempt,
            "file_sha256": file_sha256,
            "page": page,
            "quote": quote,
            "quote_sha256": hashlib.sha256(quote.encode("utf-8")).hexdigest(),
            "bbox": None,
            "coordinate_space": None,
            "bbox_status": "PENDING_CAPTURE",
        }
        payload["evidence_sha256"] = _evidence_sha256(payload)
        output.append(Schema67SuccessorEvidenceV1.model_validate(payload))
    return tuple(output)


def _section_by_field() -> dict[str, str]:
    pack = make_medical_schema_pack_596_1()
    return {
        field_id: section.section_id
        for section in pack.sections
        for field_id in section.ordered_field_ids
    }


def _field_rows(
    *,
    mappings: Sequence[Schema67SuccessorMappingV1],
    latest_rows: Mapping[str, Mapping[str, Any]],
    ordered67: tuple[str, ...],
) -> tuple[Schema67SuccessorFieldV1, ...]:
    section_by_field = _section_by_field()
    by_target: dict[str, list[Schema67SuccessorMappingV1]] = {}
    for mapping in mappings:
        for target in mapping.target_field_ids:
            by_target.setdefault(target, []).append(mapping)
    output: list[Schema67SuccessorFieldV1] = []
    for ordinal, field_id in enumerate(ordered67, start=1):
        source_mappings = by_target.get(field_id, [])
        real_sources = [item for item in source_mappings if item.source_field_id is not None]
        if not real_sources:
            status: ReviewStatus = "PENDING_RESIDUAL"
            reason: ResidualReason | None = "LATEST_REVIEWED_SOURCE_MISSING"
            action: MappingAction = "new"
        elif any(item.tri_state_conflict for item in real_sources):
            status = "PENDING_RESIDUAL"
            reason = "TRI_STATE_CONFLICT"
            action = real_sources[0].action
        elif len(real_sources) != 1 or real_sources[0].action == "merge":
            status = "PENDING_RESIDUAL"
            reason = "MULTI_SOURCE_MERGE_REQUIRES_CANONICAL_DECISION"
            action = "merge"
        else:
            status = "REVIEWED"
            reason = None
            action = real_sources[0].action
        source_ids = tuple(
            item.source_field_id for item in real_sources if item.source_field_id is not None
        )
        source_records = tuple(latest_rows[source_id] for source_id in source_ids)
        record_hashes = tuple(_record_sha256(item) for item in source_records)
        source = source_records[0] if len(source_records) == 1 else None
        not_covered = field_id in _NOT_COVERED_FIELD_IDS
        if not_covered:
            status = "REVIEWED"
            reason = None
        reviewed = status == "REVIEWED" and not not_covered
        payload: dict[str, object] = {
            "ordinal": ordinal,
            "field_id": field_id,
            "section_id": section_by_field[field_id],
            "review_status": status,
            "residual_reason": reason,
            "mapping_action": action,
            "source_field_ids": source_ids,
            "source_record_sha256": record_hashes[0] if len(record_hashes) == 1 else None,
            "source_record_sha256s": record_hashes,
            "annotator_model_id": "claude-fable-5",
            "state": "unknown"
            if not_covered
            else source.get("tri_state")
            if reviewed and source
            else None,
            "value": source.get("value") if reviewed and source else None,
            "confidence": source.get("confidence") if reviewed and source else None,
            "risk_level": source.get("risk_level") if source else None,
            "reasoning": source.get("reasoning") if reviewed and source else None,
            "flags": tuple(source.get("flags", ())) if source else (),
            "evidence": _evidence_rows(source) if reviewed and source else (),
        }
        if not_covered:
            payload["unknown_reason"] = "NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS"
        payload["field_metadata_sha256"] = _field_metadata_sha256(payload)
        try:
            output.append(Schema67SuccessorFieldV1.model_validate(payload))
        except (ValidationError, TypeError, ValueError):
            raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_FIELD_INVALID") from None
    return tuple(output)


def _review_metadata() -> Schema67ReviewMetadataV1:
    return Schema67ReviewMetadataV1(
        contract="schema67-human-review-metadata-596-1.v1",
        annotator_model_id="claude-fable-5",
        source_review_status="COMPLETED",
        reviewed_by="linyao",
        attestation_sources=(
            ReviewAttestationSourceV1(
                source_kind="REVIEWED_DATASET_BYTES",
                reference="dataset/goldenset-drafts/esheng-zunxiang-v0/annotations.jsonl",
                sha256=_LATEST71_SHA256,
            ),
            ReviewAttestationSourceV1(
                source_kind="DETERMINISTIC_VERIFICATION_REPORT",
                reference="dataset/goldenset-drafts/esheng-zunxiang-v0/verification-report.md",
                sha256=_LATEST71_REPORT_SHA256,
            ),
            ReviewAttestationSourceV1(
                source_kind="USER_AUTHORITY_FACT",
                reference=_USER_REVIEW_FACT_REF,
            ),
            ReviewAttestationSourceV1(
                source_kind="USER_AUTHORITY_FACT",
                reference=_USER_REVIEWER_FACT_REF,
            ),
        ),
    )


def build_schema67_reviewed_golden_successor_596_1(
    *, old60_bytes: bytes, latest71_bytes: bytes
) -> Schema67ReviewedGoldenSuccessor5961V1:
    old60_rows = _parse_exact_jsonl(old60_bytes, expected_sha256=_OLD60_SHA256, expected_count=60)
    latest71_rows = _parse_exact_jsonl(
        latest71_bytes, expected_sha256=_LATEST71_SHA256, expected_count=71
    )
    if {row.get("annotator_model") for row in latest71_rows} != {"claude-fable-5"}:
        raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_SOURCE_RECORD_INVALID")
    kit = build_schema67_human_annotation_kit_596_1(
        old60_bytes=old60_bytes,
        draft71_bytes=latest71_bytes,
    )
    old60_mappings = tuple(_convert_mapping(item, latest=False) for item in kit.old60_mappings)
    latest71_mappings = tuple(_convert_mapping(item, latest=True) for item in kit.draft71_mappings)
    pack = make_medical_schema_pack_596_1()
    fields = _field_rows(
        mappings=latest71_mappings,
        latest_rows={str(row["field_id"]): row for row in latest71_rows},
        ordered67=pack.ordered_field_ids,
    )
    residual: tuple[str, ...] = ()
    payload: dict[str, object] = {
        "contract": _CONTRACT,
        "source_review_status": "COMPLETED",
        "schema67_mapping_status": "COMPLETE_67",
        "golden_admission_status": "BLOCKED_RECEIPT_UNVERIFIED",
        "product_version_id": "596-1",
        "schema_pack_id": "medical-schema67.v1",
        "schema_pack_sha256": pack.schema_pack_sha256,
        "ordered_field_ids": pack.ordered_field_ids,
        "old60_input": ReviewedSourceIdentityV1(
            source_id="dataset/goldenset/gs-s0q-596-v1/596.jsonl",
            sha256=_OLD60_SHA256,
            row_count=len(old60_rows),
            authority_level="HUMAN_APPROVED_S0_Q_MIGRATION_INPUT",
            annotator_model_id="gpt-5.6-sol",
            approval_receipt_sha256=_OLD60_APPROVAL_SHA256,
        ),
        "latest71_input": ReviewedSourceIdentityV1(
            source_id="dataset/goldenset-drafts/esheng-zunxiang-v0/annotations.jsonl",
            sha256=_LATEST71_SHA256,
            row_count=len(latest71_rows),
            authority_level="HUMAN_REVIEWED_SOURCE",
            annotator_model_id="claude-fable-5",
        ),
        "review_metadata": _review_metadata(),
        "old60_mappings": old60_mappings,
        "latest71_mappings": latest71_mappings,
        "fields": fields,
        "residual_pending_field_ids": residual,
        "summary": Schema67SuccessorSummaryV1(
            contract="schema67-reviewed-golden-successor-summary-596-1.v1",
            field_count=67,
            reviewed_field_count=67,
            pending_residual_field_count=0,
            human_annotation_zero=False,
            review_completed=True,
            authority_metadata_complete=False,
            whole_batch_signature_present=False,
            evaluator_formal_conclusion_allowed=False,
        ),
    }
    payload["golden_set_sha256"] = schema67_reviewed_golden_successor_sha256(payload)
    ready_payload: dict[str, object] = {
        "contract": "schema67-reviewed-golden-whole-batch-ready-to-sign-596-1.v1",
        "status": "READY_TO_SIGN",
        "product_version_id": "596-1",
        "schema_pack_id": "medical-schema67.v1",
        "schema_pack_sha256": pack.schema_pack_sha256,
        "golden_set_sha256": payload["golden_set_sha256"],
        "reviewed_field_count": 67,
        "residual_pending_field_ids": residual,
        "reviewed_by": "linyao",
        "reviewed_at": None,
        "key_id": None,
        "signature": None,
        "approval_receipt_sha256": None,
    }
    ready_payload["signing_payload_sha256"] = _ready_to_sign_sha256(ready_payload)
    payload["ready_to_sign"] = Schema67WholeBatchReadyToSignV1.model_validate(ready_payload)
    try:
        return Schema67ReviewedGoldenSuccessor5961V1.model_validate(payload)
    except (ValidationError, TypeError, ValueError):
        raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_INVALID") from None


def validate_schema67_reviewed_golden_successor_596_1(
    successor: Schema67ReviewedGoldenSuccessor5961V1,
    *,
    old60_bytes: bytes,
    latest71_bytes: bytes,
) -> Schema67ReviewedGoldenSuccessor5961V1:
    try:
        fresh = Schema67ReviewedGoldenSuccessor5961V1.model_validate(
            successor.model_dump(mode="python")
        )
    except (AttributeError, ValidationError, TypeError, ValueError):
        raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_INVALID") from None
    expected = build_schema67_reviewed_golden_successor_596_1(
        old60_bytes=old60_bytes,
        latest71_bytes=latest71_bytes,
    )
    if fresh != successor or fresh != expected:
        raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_AUTHORITY_INVALID")
    return successor


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("duplicate JSON key")
        values[key] = value
    return values


def load_schema67_reviewed_golden_successor_596_1(
    payload: bytes,
    *,
    old60_bytes: bytes,
    latest71_bytes: bytes,
) -> Schema67ReviewedGoldenSuccessor5961V1:
    try:
        decoded = json.loads(payload.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(decoded, dict):
            raise ValueError("root must be an object")
        successor = Schema67ReviewedGoldenSuccessor5961V1.model_validate(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, TypeError, ValueError):
        raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_WIRE_INVALID") from None
    if payload != canonical_schema67_reviewed_golden_successor_bytes(successor):
        raise Schema67ReviewedGoldenSuccessorError("SCHEMA67_SUCCESSOR_WIRE_INVALID")
    return validate_schema67_reviewed_golden_successor_596_1(
        successor,
        old60_bytes=old60_bytes,
        latest71_bytes=latest71_bytes,
    )


__all__ = [
    "ReviewAttestationSourceV1",
    "ReviewedSourceIdentityV1",
    "Schema67ReviewMetadataV1",
    "Schema67ReviewedGoldenSuccessor5961V1",
    "Schema67ReviewedGoldenSuccessorError",
    "Schema67SuccessorEvidenceV1",
    "Schema67SuccessorFieldV1",
    "Schema67SuccessorMappingV1",
    "Schema67SuccessorSummaryV1",
    "Schema67WholeBatchReadyToSignV1",
    "build_schema67_reviewed_golden_successor_596_1",
    "canonical_schema67_reviewed_golden_artifact_files",
    "canonical_schema67_reviewed_golden_successor_bytes",
    "load_schema67_reviewed_golden_successor_596_1",
    "schema67_reviewed_golden_successor_sha256",
    "validate_schema67_reviewed_golden_successor_596_1",
]
