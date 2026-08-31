"""Offline, privacy-safe report compiler for one frozen Schema67 candidate.

This task-local boundary performs no I/O. It consumes the exact Mission 119
candidate, the eight production task executions, and only Lane C's sealed gate.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Final, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    FreeformEvidenceBindingReceiptV1,
    FreeformFieldOutputV1,
)
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    ORDERED_FIELD_IDS,
    Schema67CandidateV2,
    Schema67ReportGateV1,
    validate_schema67_candidate_v2,
    validate_schema67_report_gate,
)
from insurance_harness.knowledge_compiler.deepseek_locator_extractor_596_1 import (
    DeepSeekExecutionReceiptV1,
    DeepSeekTaskExecutionV1,
    Schema67BatchExecutionReceiptV1,
    Schema67BatchExecutionV1,
    _is_single_pass_mvp_operational_tuple,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitTreeSha1 = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
ReasonCode = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")]
SourceRole = Literal["terms", "brochure", "rate_table"]
TriState = Literal["present", "absent_explicitly", "unknown"]
Evidence057Status = Literal["PASS", "BLOCKED", "NOT_REQUIRED"]
SemanticGateStatus = Literal["PASS", "FAIL", "PENDING"]
ReportStatus = Literal["READY", "PENDING", "BLOCKED"]

_REPORT_OBJECT_TYPE: Final[str] = "schema67-candidate-report.v2"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class Schema67CandidateReportError(ValueError):
    """Typed fail-closed result for malformed candidate/report composition."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_reasons(values: tuple[str, ...]) -> bool:
    return values == tuple(sorted(values)) and len(values) == len(set(values))


class Schema67EvidenceReportV1(_FrozenModel):
    source_role: SourceRole
    source_sha256: Sha256Hex
    page_number: Annotated[StrictInt, Field(gt=0)]
    locator_kind: Literal["page", "block", "table", "cell"]
    locator_ref_sha256: Sha256Hex
    quote_sha256: Sha256Hex


class Schema67CandidateFieldReportV1(_FrozenModel):
    ordinal: Annotated[StrictInt, Field(ge=1, le=67)]
    field_id: StrictStr
    state: TriState
    value_sha256: Sha256Hex | None
    evidence_count: Annotated[StrictInt, Field(ge=0)]
    evidence: tuple[Schema67EvidenceReportV1, ...]
    evidence_057_status: Evidence057Status
    semantic_correctness: SemanticGateStatus
    semantic_completeness: SemanticGateStatus
    state_consistent: StrictBool | None
    review_item_reason_codes: tuple[ReasonCode, ...]
    evidence_receipt_sha256: Sha256Hex
    semantic_decision_receipt_sha256: Sha256Hex | None


class Schema67StateCountsV1(_FrozenModel):
    present: Annotated[StrictInt, Field(ge=0)]
    absent_explicitly: Annotated[StrictInt, Field(ge=0)]
    unknown: Annotated[StrictInt, Field(ge=0)]

    @model_validator(mode="after")
    def require_exact67(self) -> Self:
        if self.present + self.absent_explicitly + self.unknown != 67:
            raise ValueError("state_counts_invalid")
        return self


class Schema67BudgetReportV1(_FrozenModel):
    task_count: Literal[8]
    locator_calls: Literal[0]
    extractor_calls: Annotated[StrictInt, Field(ge=8, le=9)]
    provider_calls: Annotated[StrictInt, Field(ge=8, le=10)]
    transport_retries: Literal[0, 1]
    response_contract_repairs: Literal[0, 1]
    evidence_repairs: Literal[0, 1]
    repair_calls: Annotated[StrictInt, Field(ge=0, le=2)]
    prior_provider_calls: Literal[2] | None = None
    cumulative_provider_calls: Literal[10] | None = None

    @model_validator(mode="after")
    def require_shared_extra_budget(self) -> Self:
        extras = self.transport_retries + self.response_contract_repairs + self.evidence_repairs
        operational_payload: dict[str, object] = {
            "task_count": self.task_count,
            "provider_calls": self.provider_calls,
            "extractor_calls": self.extractor_calls,
            "locator_calls": self.locator_calls,
            "transport_retries": self.transport_retries,
            "response_contract_repairs": self.response_contract_repairs,
            "evidence_repairs": self.evidence_repairs,
            "repair_calls": self.repair_calls,
        }
        expected_cumulative = (
            (2, 10) if _is_single_pass_mvp_operational_tuple(operational_payload) else (None, None)
        )
        if (
            extras > 2
            or self.extractor_calls != self.task_count + self.transport_retries
            or self.repair_calls != self.response_contract_repairs + self.evidence_repairs
            or self.provider_calls != self.task_count + extras
            or (
                self.prior_provider_calls,
                self.cumulative_provider_calls,
            )
            != expected_cumulative
        ):
            raise ValueError("report_budget_invalid")
        return self


def _report_payload(report: Schema67CandidateReportV1) -> dict[str, object]:
    return report.model_dump(mode="python", exclude={"report_sha256"})


class Schema67CandidateReportV1(_FrozenModel):
    contract: Literal["schema67-candidate-report.v2"]
    status: ReportStatus
    reason_codes: tuple[ReasonCode, ...]
    approved_by: Literal["linyao"]
    candidate_sha256: Sha256Hex
    candidate_tree_sha1: GitTreeSha1
    model_identity_sha256: Sha256Hex
    batch_receipt_sha256: Sha256Hex
    gate_receipt_sha256: Sha256Hex
    task_receipt_hashes: tuple[Sha256Hex, ...]
    task_final_outputs_sha256: tuple[Sha256Hex, ...]
    evidence_receipt_hashes: tuple[Sha256Hex, ...]
    lane_c_candidate_evidence_receipt_hashes: tuple[Sha256Hex, ...]
    live_evidence_receipt_hashes: tuple[Sha256Hex, ...]
    reference_bundle_sha256: Sha256Hex
    reference_subject_sha256: Sha256Hex
    reference_receipt_sha256: Sha256Hex
    comparator_authority_sha256: Sha256Hex
    semantic_decision_receipt_hashes: tuple[Sha256Hex, ...]
    semantic_evaluation_receipt_sha256: Sha256Hex
    wiki_admission_allowed: StrictBool
    publishable_field_count: Annotated[StrictInt, Field(ge=0, le=67)]
    demoted_field_count: Annotated[StrictInt, Field(ge=0, le=67)]
    demoted_field_ids: tuple[StrictStr, ...]
    counts: Schema67StateCountsV1
    budget: Schema67BudgetReportV1
    fields: tuple[Schema67CandidateFieldReportV1, ...]
    report_sha256: Sha256Hex

    @model_validator(mode="after")
    def require_exact_report(self) -> Self:
        ready_shape = self.wiki_admission_allowed and self.publishable_field_count == 67
        non_ready_shape = not self.wiki_admission_allowed and self.publishable_field_count == 0
        demoted = set(self.demoted_field_ids)
        fields_by_id = {item.field_id: item for item in self.fields}
        if (
            tuple(item.field_id for item in self.fields) != ORDERED_FIELD_IDS
            or len(self.task_receipt_hashes) != 8
            or len(self.task_final_outputs_sha256) != 8
            or not _canonical_reasons(self.reason_codes)
            or self.demoted_field_count != len(self.demoted_field_ids)
            or len(demoted) != len(self.demoted_field_ids)
            or self.demoted_field_ids
            != tuple(field_id for field_id in ORDERED_FIELD_IDS if field_id in demoted)
            or any(
                fields_by_id[field_id].state != "unknown"
                or fields_by_id[field_id].review_item_reason_codes != ("EVIDENCE_NONPASS_DEMOTED",)
                for field_id in self.demoted_field_ids
            )
            or (
                bool(self.demoted_field_ids)
                and (
                    self.budget.task_count,
                    self.budget.locator_calls,
                    self.budget.extractor_calls,
                    self.budget.provider_calls,
                    self.budget.transport_retries,
                    self.budget.response_contract_repairs,
                    self.budget.evidence_repairs,
                    self.budget.repair_calls,
                    self.budget.prior_provider_calls,
                    self.budget.cumulative_provider_calls,
                )
                != (8, 0, 8, 8, 0, 0, 0, 0, 2, 10)
            )
            or (bool(self.demoted_field_ids) and self.status == "READY")
            or (self.status == "READY" and not ready_shape)
            or (self.status != "READY" and not non_ready_shape)
            or self.report_sha256 != canonical_hash(_REPORT_OBJECT_TYPE, _report_payload(self))
        ):
            raise ValueError("candidate_report_invalid")
        return self


def _revalidate_candidate(value: Schema67CandidateV2) -> Schema67CandidateV2:
    try:
        return validate_schema67_candidate_v2(value)
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise Schema67CandidateReportError("CANDIDATE_INVALID") from None


def _revalidate_batch_execution(
    value: Schema67BatchExecutionV1,
) -> Schema67BatchExecutionV1:
    try:
        if type(value) is not Schema67BatchExecutionV1 or type(value.executions) is not tuple:
            raise TypeError
        receipt = Schema67BatchExecutionReceiptV1.model_validate(
            value.receipt.model_dump(mode="python", round_trip=True)
        )
        if len(value.executions) != 8:
            raise ValueError
        executions: list[DeepSeekTaskExecutionV1] = []
        for task in value.executions:
            if type(task) is not DeepSeekTaskExecutionV1:
                raise TypeError
            task_receipt = DeepSeekExecutionReceiptV1.model_validate(
                task.receipt.model_dump(mode="python", round_trip=True)
            )
            initial_outputs = tuple(
                FreeformFieldOutputV1.model_validate(
                    item.model_dump(mode="python", round_trip=True)
                )
                for item in task.initial_outputs
            )
            final_outputs = tuple(
                FreeformFieldOutputV1.model_validate(
                    item.model_dump(mode="python", round_trip=True)
                )
                for item in task.final_outputs
            )
            evidence_receipts = tuple(
                FreeformEvidenceBindingReceiptV1.model_validate(
                    item.model_dump(mode="python", round_trip=True)
                )
                for item in task.evidence_receipts
            )
            checked = DeepSeekTaskExecutionV1(
                initial=task.initial,
                initial_outputs=initial_outputs,
                final_outputs=final_outputs,
                evidence_receipts=evidence_receipts,
                response_contract_repair=task.response_contract_repair,
                evidence_repair=task.evidence_repair,
                evidence_demotion=task_receipt.evidence_demotion,
                receipt=task_receipt,
            )
            if task_receipt.execution_plan_sha256 != receipt.execution_plan_sha256:
                raise ValueError
            executions.append(checked)
        exact = tuple(executions)
        task_hashes = tuple(item.receipt.receipt_hash for item in exact)
        task_ids = tuple(item.receipt.task_id for item in exact)
        task_slices = tuple(item.receipt.task_slice_sha256 for item in exact)
        if (
            task_hashes != receipt.task_receipt_hashes
            or len(set(task_hashes)) != 8
            or len(set(task_ids)) != 8
            or any(item is None for item in task_slices)
            or len(set(task_slices)) != 8
            or (
                any(item.receipt.evidence_demotion is not None for item in exact)
                and (
                    receipt.prior_provider_calls,
                    receipt.cumulative_provider_calls,
                )
                != (2, 10)
            )
        ):
            raise ValueError
        return Schema67BatchExecutionV1(executions=exact, receipt=receipt)
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise Schema67CandidateReportError("BATCH_EXECUTION_INVALID") from None


def _revalidate_gate(value: Schema67ReportGateV1) -> Schema67ReportGateV1:
    try:
        return validate_schema67_report_gate(value)
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise Schema67CandidateReportError("GATE_INVALID") from None


def compile_schema67_candidate_report(
    *,
    candidate: Schema67CandidateV2,
    gate: Schema67ReportGateV1,
) -> Schema67CandidateReportV1:
    """Compile one answer-redacted report from exact execution and sealed gate custody."""

    exact_candidate = _revalidate_candidate(candidate)
    exact_batch = _revalidate_batch_execution(exact_candidate.batch_execution)
    exact_gate = _revalidate_gate(gate)
    execution_fields = tuple(
        output for task in exact_batch.executions for output in task.final_outputs
    )
    execution_receipts = tuple(
        receipt for task in exact_batch.executions for receipt in task.evidence_receipts
    )
    executable_field_ids = tuple(
        field_id
        for task_slice in exact_candidate.execution_plan.task_slices
        for field_id in task_slice.field_ids
    )
    candidate_fields_by_id = {item.field_id: item for item in exact_candidate.fields}
    candidate_receipts_by_id = {item.field_id: item for item in exact_candidate.evidence_receipts}
    if (
        exact_batch.receipt != exact_candidate.batch_receipt
        or tuple(item.field_id for item in execution_fields) != executable_field_ids
        or tuple(item.field_id for item in execution_receipts) != executable_field_ids
        or execution_fields
        != tuple(candidate_fields_by_id[field_id] for field_id in executable_field_ids)
        or execution_receipts
        != tuple(candidate_receipts_by_id[field_id] for field_id in executable_field_ids)
    ):
        raise Schema67CandidateReportError("CANDIDATE_EXECUTION_MISMATCH")
    demoted_field_ids_raw = tuple(
        field_id
        for task in exact_batch.executions
        if task.receipt.evidence_demotion is not None
        for field_id in task.receipt.evidence_demotion.demoted_field_ids
    )
    demoted_field_id_set = set(demoted_field_ids_raw)
    demoted_field_ids = tuple(
        field_id for field_id in ORDERED_FIELD_IDS if field_id in demoted_field_id_set
    )
    if (
        len(demoted_field_ids_raw) != len(demoted_field_id_set)
        or set(demoted_field_ids) != demoted_field_id_set
        or any(
            candidate_fields_by_id[field_id].state != "unknown" for field_id in demoted_field_ids
        )
    ):
        raise Schema67CandidateReportError("CANDIDATE_EXECUTION_MISMATCH")
    known_receipt_hashes = tuple(
        receipt.receipt_hash
        for field, receipt in zip(
            exact_candidate.fields,
            exact_candidate.evidence_receipts,
            strict=True,
        )
        if field.state != "unknown"
    )
    if (
        exact_gate.candidate_v2_sha256 != exact_candidate.candidate_sha256
        or exact_gate.accepted_batch_receipt_sha256
        != exact_candidate.batch_receipt.batch_receipt_sha256
        or exact_gate.task_receipt_hashes != exact_candidate.batch_receipt.task_receipt_hashes
        or exact_gate.candidate_evidence_receipt_hashes != known_receipt_hashes
        or tuple(row.field_id for row in exact_gate.rows) != ORDERED_FIELD_IDS
        or tuple(row.state for row in exact_gate.rows)
        != tuple(field.state for field in exact_candidate.fields)
    ):
        raise Schema67CandidateReportError("GATE_CANDIDATE_MISMATCH")

    source_by_hash = {
        item["source_sha256"]: cast(SourceRole, item["role"])
        for item in exact_candidate.source_roles
    }
    field_reports: list[Schema67CandidateFieldReportV1] = []
    reason_codes: set[str] = set()
    counts = {"present": 0, "absent_explicitly": 0, "unknown": 0}
    for ordinal, (field, receipt, row) in enumerate(
        zip(
            exact_candidate.fields,
            exact_candidate.evidence_receipts,
            exact_gate.rows,
            strict=True,
        ),
        start=1,
    ):
        expected_unknown_reason = (
            "EVIDENCE_NONPASS_DEMOTED"
            if field.field_id in demoted_field_id_set
            else "SEMANTIC_UNKNOWN_PENDING"
        )
        if field.state == "unknown" and not (
            row.evidence_057_status == "NOT_REQUIRED"
            and row.correctness == "PENDING"
            and row.completeness == "PENDING"
            and row.review_reason_codes == (expected_unknown_reason,)
            and row.semantic_decision_receipt_sha256 is None
        ):
            raise Schema67CandidateReportError("GATE_FIELD_STATE_MISMATCH")
        if field.state != "unknown" and row.evidence_057_status == "NOT_REQUIRED":
            raise Schema67CandidateReportError("GATE_FIELD_STATE_MISMATCH")
        counts[field.state] += 1
        evidence_reports = tuple(
            Schema67EvidenceReportV1(
                source_role=source_by_hash[evidence.source_sha256],
                source_sha256=evidence.source_sha256,
                page_number=evidence.page_number,
                locator_kind=evidence.locator.subject_type,
                locator_ref_sha256=_sha256_text(evidence.locator.subject_ref),
                quote_sha256=evidence.quote_snapshot_sha256,
            )
            for evidence in field.evidence
        )
        reason_codes.update(row.review_reason_codes)
        field_reports.append(
            Schema67CandidateFieldReportV1(
                ordinal=ordinal,
                field_id=field.field_id,
                state=field.state,
                value_sha256=(
                    None if field.value_snapshot is None else _sha256_text(field.value_snapshot)
                ),
                evidence_count=len(evidence_reports),
                evidence=evidence_reports,
                evidence_057_status=row.evidence_057_status,
                semantic_correctness=row.correctness,
                semantic_completeness=row.completeness,
                state_consistent=row.state_consistent,
                review_item_reason_codes=row.review_reason_codes,
                evidence_receipt_sha256=receipt.receipt_hash,
                semantic_decision_receipt_sha256=(row.semantic_decision_receipt_sha256),
            )
        )

    batch = exact_candidate.batch_receipt
    state_counts = Schema67StateCountsV1(
        present=counts["present"],
        absent_explicitly=counts["absent_explicitly"],
        unknown=counts["unknown"],
    )
    budget = Schema67BudgetReportV1(
        task_count=8,
        locator_calls=batch.locator_calls,
        extractor_calls=batch.extractor_calls,
        provider_calls=batch.provider_calls,
        transport_retries=batch.transport_retries,
        response_contract_repairs=batch.response_contract_repairs,
        evidence_repairs=cast(Literal[0, 1], batch.evidence_repairs),
        repair_calls=batch.repair_calls,
        prior_provider_calls=batch.prior_provider_calls,
        cumulative_provider_calls=batch.cumulative_provider_calls,
    )
    exact_reasons = tuple(sorted(reason_codes))
    exact_fields = tuple(field_reports)
    evidence_receipt_hashes = tuple(item.receipt_hash for item in exact_candidate.evidence_receipts)
    task_final_outputs = tuple(item.receipt.final_outputs_sha256 for item in exact_batch.executions)
    values: dict[str, object] = {
        "contract": _REPORT_OBJECT_TYPE,
        "status": exact_gate.status,
        "reason_codes": exact_reasons,
        "approved_by": "linyao",
        "candidate_sha256": exact_candidate.candidate_sha256,
        "candidate_tree_sha1": exact_candidate.candidate_tree_sha1,
        "model_identity_sha256": exact_candidate.model_identity_sha256,
        "batch_receipt_sha256": batch.batch_receipt_sha256,
        "gate_receipt_sha256": exact_gate.gate_receipt_sha256,
        "task_receipt_hashes": batch.task_receipt_hashes,
        "task_final_outputs_sha256": task_final_outputs,
        "evidence_receipt_hashes": evidence_receipt_hashes,
        "lane_c_candidate_evidence_receipt_hashes": (exact_gate.candidate_evidence_receipt_hashes),
        "live_evidence_receipt_hashes": exact_gate.live_evidence_receipt_hashes,
        "reference_bundle_sha256": exact_gate.reference_bundle_sha256,
        "reference_subject_sha256": exact_gate.reference_subject_sha256,
        "reference_receipt_sha256": exact_gate.reference_receipt_sha256,
        "comparator_authority_sha256": exact_gate.comparator_authority_sha256,
        "semantic_decision_receipt_hashes": (exact_gate.semantic_decision_receipt_hashes),
        "semantic_evaluation_receipt_sha256": (exact_gate.semantic_evaluation_receipt_sha256),
        "wiki_admission_allowed": exact_gate.wiki_admission_allowed,
        "publishable_field_count": len(exact_gate.publishable_field_ids),
        "demoted_field_count": len(demoted_field_ids),
        "demoted_field_ids": demoted_field_ids,
        "counts": state_counts.model_dump(mode="python"),
        "budget": budget.model_dump(mode="python"),
        "fields": tuple(item.model_dump(mode="python") for item in exact_fields),
    }
    try:
        return Schema67CandidateReportV1(
            contract="schema67-candidate-report.v2",
            status=exact_gate.status,
            reason_codes=exact_reasons,
            approved_by="linyao",
            candidate_sha256=exact_candidate.candidate_sha256,
            candidate_tree_sha1=exact_candidate.candidate_tree_sha1,
            model_identity_sha256=exact_candidate.model_identity_sha256,
            batch_receipt_sha256=batch.batch_receipt_sha256,
            gate_receipt_sha256=exact_gate.gate_receipt_sha256,
            task_receipt_hashes=batch.task_receipt_hashes,
            task_final_outputs_sha256=task_final_outputs,
            evidence_receipt_hashes=evidence_receipt_hashes,
            lane_c_candidate_evidence_receipt_hashes=(exact_gate.candidate_evidence_receipt_hashes),
            live_evidence_receipt_hashes=exact_gate.live_evidence_receipt_hashes,
            reference_bundle_sha256=exact_gate.reference_bundle_sha256,
            reference_subject_sha256=exact_gate.reference_subject_sha256,
            reference_receipt_sha256=exact_gate.reference_receipt_sha256,
            comparator_authority_sha256=exact_gate.comparator_authority_sha256,
            semantic_decision_receipt_hashes=(exact_gate.semantic_decision_receipt_hashes),
            semantic_evaluation_receipt_sha256=(exact_gate.semantic_evaluation_receipt_sha256),
            wiki_admission_allowed=exact_gate.wiki_admission_allowed,
            publishable_field_count=len(exact_gate.publishable_field_ids),
            demoted_field_count=len(demoted_field_ids),
            demoted_field_ids=demoted_field_ids,
            counts=state_counts,
            budget=budget,
            fields=exact_fields,
            report_sha256=canonical_hash(_REPORT_OBJECT_TYPE, values),
        )
    except (ValidationError, TypeError, ValueError):
        raise Schema67CandidateReportError("REPORT_COMPILATION_INVALID") from None


def _render_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _require_exact_report_custody(
    *,
    candidate: Schema67CandidateV2,
    gate: Schema67ReportGateV1,
    report: Schema67CandidateReportV1,
) -> Schema67CandidateReportV1:
    try:
        exact_report = Schema67CandidateReportV1.model_validate(
            report.model_dump(mode="python", round_trip=True)
        )
    except (ValidationError, AttributeError, TypeError, ValueError):
        raise Schema67CandidateReportError("REPORT_INVALID") from None
    expected = compile_schema67_candidate_report(candidate=candidate, gate=gate)
    if exact_report != expected:
        raise Schema67CandidateReportError("REPORT_CUSTODY_MISMATCH")
    return exact_report


def render_public_schema67_candidate_report(
    *,
    candidate: Schema67CandidateV2,
    gate: Schema67ReportGateV1,
    report: Schema67CandidateReportV1,
) -> bytes:
    """Render only hashes and statuses; raw values, quotes, refs and paths are absent."""

    exact = _require_exact_report_custody(
        candidate=candidate,
        gate=gate,
        report=report,
    )
    return _render_json(exact.model_dump(mode="json"))


def render_private_schema67_candidate_report(
    *,
    candidate: Schema67CandidateV2,
    gate: Schema67ReportGateV1,
    report: Schema67CandidateReportV1,
    include_raw_values: Literal[True],
) -> bytes:
    """Render raw values only after an explicit, literal opt-in."""

    if include_raw_values is not True:
        raise Schema67CandidateReportError("PRIVATE_RENDER_NOT_AUTHORIZED")
    exact_report = _require_exact_report_custody(
        candidate=candidate,
        gate=gate,
        report=report,
    )
    exact_candidate = _revalidate_candidate(candidate)
    return _render_json(
        {
            "report": exact_report.model_dump(mode="json"),
            "raw_values": tuple(
                {"field_id": field.field_id, "value_snapshot": field.value_snapshot}
                for field in exact_candidate.fields
            ),
        }
    )


__all__ = [
    "Schema67BudgetReportV1",
    "Schema67CandidateFieldReportV1",
    "Schema67CandidateReportError",
    "Schema67CandidateReportV1",
    "Schema67EvidenceReportV1",
    "Schema67StateCountsV1",
    "compile_schema67_candidate_report",
    "render_private_schema67_candidate_report",
    "render_public_schema67_candidate_report",
]
