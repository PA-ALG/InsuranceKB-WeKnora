from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    EvidenceLocatorSnapshotV1,
    FreeformDocumentBindingV1,
    FreeformEvidenceBindingReceiptV1,
    FreeformEvidenceV1,
    FreeformFieldOutputV1,
)
from insurance_harness.goldenset import expert_golden_admission_596_2 as admission_119
from insurance_harness.goldenset import (
    schema67_semantic_comparator_596_2 as comparator_119,
)
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    ORDERED_FIELD_IDS,
    EvidenceReplayCaseV1,
    Schema67CandidateV2,
    candidate_evidence_bundle_sha256,
    load_schema67_candidate_v2,
)
from insurance_harness.knowledge_compiler import deepseek_locator_extractor_596_1 as deepseek
from insurance_harness.knowledge_compiler.deepseek_locator_extractor_596_1 import (
    LOCATOR_SELECTION_POLICY_SHA256,
    DeepSeekTaskExecutionV1,
)
from insurance_harness.knowledge_compiler.schema67_candidate_report_596_1 import (
    Schema67BudgetReportV1,
    Schema67CandidateReportError,
    Schema67CandidateReportV1,
    compile_schema67_candidate_report,
    render_private_schema67_candidate_report,
    render_public_schema67_candidate_report,
)
from tests.test_expert_golden_admission_596_2_119 import (
    NOW as _LANE_C_NOW,
)
from tests.test_expert_golden_admission_596_2_119 import (
    _approved_cases as _lane_c_approved_cases,
)
from tests.test_expert_golden_admission_596_2_119 import (
    _authority_snapshot as _lane_c_authority_snapshot,
)
from tests.test_expert_golden_admission_596_2_119 import (
    _candidate_v2 as _lane_c_candidate_v2,
)
from tests.test_expert_golden_admission_596_2_119 import (
    _document as _lane_c_document,
)
from tests.test_expert_golden_admission_596_2_119 import (
    _receipt as _lane_c_receipt,
)
from tests.test_expert_golden_admission_596_2_119 import (
    _trusted_candidate_v2_preparation as _lane_c_trusted_candidate_v2_preparation,
)

TERMS_SHA = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
BROCHURE_SHA = "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
RATE_SHA = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"
TREE_SHA = "bf38d51bef0b6d1ae119bb0535e8ff0dc9463c53"


def _sha(value: str | bytes) -> str:
    payload = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _evidence(field_id: str, *, quote: str) -> FreeformEvidenceV1:
    content = f"prefix {quote} suffix"
    return FreeformEvidenceV1(
        field_id=field_id,
        source_sha256=TERMS_SHA,
        source_revision_id="terms-revision-1",
        parse_attempt_id="terms-attempt-2",
        parsed_document_hash="4" * 64,
        parse_manifest_hash="5" * 64,
        page_number=7,
        block_id="terms-block-7-2",
        locator=EvidenceLocatorSnapshotV1(
            subject_type="block",
            subject_ref="terms-block-7-2",
            page_number=7,
            parent_refs=("terms-page-7",),
            content_snapshot=content,
            content_snapshot_sha256=_sha(content),
        ),
        quote_snapshot=quote,
        quote_snapshot_sha256=_sha(quote),
    )


def _receipt(output: FreeformFieldOutputV1) -> FreeformEvidenceBindingReceiptV1:
    documents = (
        ()
        if output.state == "unknown"
        else (
            FreeformDocumentBindingV1(
                source_id="terms-source",
                source_revision_id="terms-revision-1",
                source_sha256=TERMS_SHA,
                parse_attempt_id="terms-attempt-2",
                parsed_document_hash="4" * 64,
                parse_manifest_hash="5" * 64,
            ),
        )
    )
    payload = {
        "contract": "freeform-arm-evidence-binding-receipt.v1",
        "product_version_id": output.product_version_id,
        "field_id": output.field_id,
        "state": output.state,
        "value_snapshot": output.value_snapshot,
        "documents": tuple(item.model_dump(mode="python") for item in documents),
        "evidence": tuple(item.model_dump(mode="python") for item in output.evidence),
    }
    return FreeformEvidenceBindingReceiptV1(
        contract="freeform-arm-evidence-binding-receipt.v1",
        product_version_id=output.product_version_id,
        field_id=output.field_id,
        state=output.state,
        value_snapshot=output.value_snapshot,
        documents=documents,
        evidence=output.evidence,
        receipt_hash=canonical_hash("freeform-arm-evidence-binding-receipt.v1", payload),
    )


def _fields() -> tuple[FreeformFieldOutputV1, ...]:
    values: list[FreeformFieldOutputV1] = []
    for index, field_id in enumerate(ORDERED_FIELD_IDS):
        if index == 0:
            values.append(
                FreeformFieldOutputV1(
                    product_version_id="596-1",
                    field_id=field_id,
                    state="present",
                    value_snapshot="敏感原值 /synthetic/private.pdf",
                    evidence=(_evidence(field_id, quote="条款明确载明产品代码"),),
                )
            )
        elif index == 1:
            values.append(
                FreeformFieldOutputV1(
                    product_version_id="596-1",
                    field_id=field_id,
                    state="absent_explicitly",
                    value_snapshot="不适用",
                    evidence=(_evidence(field_id, quote="原文明示不适用"),),
                )
            )
        else:
            values.append(
                FreeformFieldOutputV1(
                    product_version_id="596-1",
                    field_id=field_id,
                    state="unknown",
                    value_snapshot=None,
                    evidence=(),
                )
            )
    return tuple(values)


def _candidate_wire() -> dict[str, Any]:
    built = _lane_c_candidate_v2(_lane_c_approved_cases())
    payload = json.loads(
        json.dumps(
            built.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    assert type(payload) is dict
    return cast(dict[str, Any], payload)


def _candidate() -> Schema67CandidateV2:
    built = _lane_c_candidate_v2(_lane_c_approved_cases())
    payload = _candidate_wire()
    field_contracts, execution_plan, role_inputs = _lane_c_trusted_candidate_v2_preparation()
    candidate = load_schema67_candidate_v2(
        payload,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        role_inputs=role_inputs,
    )
    assert type(candidate) is Schema67CandidateV2
    assert candidate.candidate_sha256 == built.candidate_sha256
    return candidate


def _demoted_candidate() -> Schema67CandidateV2:
    built = _lane_c_candidate_v2(_lane_c_approved_cases(), single_pass_demotion=True)
    payload = json.loads(
        json.dumps(
            built.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    field_contracts, execution_plan, role_inputs = _lane_c_trusted_candidate_v2_preparation()
    return load_schema67_candidate_v2(
        payload,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        role_inputs=role_inputs,
    )


def _rehash_candidate_wire(payload: dict[str, Any]) -> None:
    payload["candidate_sha256"] = canonical_hash(
        "schema67-candidate.v2",
        {key: value for key, value in payload.items() if key != "candidate_sha256"},
    )


def _rewrite_first_field_prompt_authority(payload: dict[str, Any]) -> None:
    tasks = cast(list[dict[str, Any]], payload["prepared_tasks"])
    task = tasks[0]
    prompt = cast(list[dict[str, Any]], task["field_prompts"])[0]
    contract = cast(dict[str, Any], prompt["contract"])
    contract["description"] = f"{contract['description']} attacker-selected"
    contract["field_contract_sha256"] = canonical_hash(
        "schema67-field-contract.v1",
        {key: value for key, value in contract.items() if key != "field_contract_sha256"},
    )
    prompt["prompt_payload_sha256"] = canonical_hash(
        "schema67-deepseek-field-prompt.v1",
        {
            "field_id": contract["field_id"],
            "description": contract["description"],
            "value_shape": contract["value_shape"],
            "formation_modes": contract["formation_modes"],
            "source_roles": contract["source_roles"],
            "evidence_required": contract["evidence_required"],
            "output_state_policy": contract["output_state_policy"],
            "hardness": contract["hardness"],
            "field_contract_sha256": contract["field_contract_sha256"],
        },
    )
    task["provider_task_sha256"] = canonical_hash(
        "schema67-deepseek-provider-task.v1",
        {
            "execution_plan_sha256": task["execution_plan_sha256"],
            "task_slice_sha256": task["task_slice_sha256"],
            "source_task_hashes": tuple(
                item["task_hash"] for item in cast(list[dict[str, Any]], task["source_tasks"])
            ),
            "locator_selection_policy_sha256": LOCATOR_SELECTION_POLICY_SHA256,
            "field_prompt_authorities": tuple(cast(list[dict[str, Any]], task["field_prompts"])),
        },
    )
    task["provider_attempt_sha256"] = canonical_hash(
        "schema67-deepseek-provider-attempt.v1",
        {
            "provider_task_sha256": task["provider_task_sha256"],
            "source_attempt_hashes": tuple(
                item["attempt_hash"]
                for item in cast(list[dict[str, Any]], task["initial_attempts"])
            ),
        },
    )

    batch_execution = cast(dict[str, Any], payload["batch_execution"])
    execution = cast(list[dict[str, Any]], batch_execution["executions"])[0]
    initial = cast(dict[str, Any], execution["initial"])
    initial["task_id"] = task["provider_task_sha256"]
    initial["attempt_hash"] = task["provider_attempt_sha256"]
    initial["bound_attempt_hash"] = canonical_hash(
        "schema67-deepseek-bound-attempt.v1",
        {
            "task_id": initial["task_id"],
            "attempt_hash": initial["attempt_hash"],
            "execution_plan_sha256": initial["execution_plan_sha256"],
            "task_slice_sha256": initial["task_slice_sha256"],
            "output_hashes": tuple(
                canonical_hash("schema67-deepseek-field-output.v1", item)
                for item in cast(list[dict[str, Any]], initial["outputs"])
            ),
            "evidence_receipt_hashes": tuple(
                item["receipt_hash"]
                for item in cast(list[dict[str, Any]], initial["evidence_receipts"])
            ),
            "verification_hashes": tuple(
                canonical_hash("evidence-verification-batch.v1", item)
                for item in cast(list[dict[str, Any]], initial["verification_batches"])
            ),
            "receipt_chain_hashes": tuple(
                tuple(
                    receipt_item["receipt_hash"]
                    for receipt_item in cast(list[dict[str, Any]], chain["receipts"])
                )
                for chain in cast(list[dict[str, Any]], initial["receipt_chains"])
            ),
        },
    )
    receipt = cast(dict[str, Any], execution["receipt"])
    receipt["task_id"] = task["provider_task_sha256"]
    receipt["attempt_hash"] = task["provider_attempt_sha256"]
    receipt["initial_bound_attempt_hash"] = initial["bound_attempt_hash"]
    receipt["receipt_hash"] = canonical_hash(
        deepseek._EXECUTION_RECEIPT_OBJECT_TYPE,
        {key: value for key, value in receipt.items() if key != "receipt_hash"},
    )
    batch_receipt = cast(dict[str, Any], batch_execution["receipt"])
    task_receipt_hashes = cast(list[str], batch_receipt["task_receipt_hashes"])
    task_receipt_hashes[0] = receipt["receipt_hash"]
    batch_receipt["batch_receipt_sha256"] = deepseek._batch_receipt_sha256(
        {key: value for key, value in batch_receipt.items() if key != "batch_receipt_sha256"}
    )
    payload["batch_receipt"] = copy.deepcopy(batch_receipt)
    _rehash_candidate_wire(payload)


def _approved_reference() -> comparator_119.ApprovedSchema67ReferenceV1:
    return comparator_119.load_total_control_approved_schema67_reference(
        receipt=_lane_c_receipt(),
        observed_at=_LANE_C_NOW,
    )


def _candidate_evidence_cases(
    candidate: Schema67CandidateV2,
) -> tuple[EvidenceReplayCaseV1, ...]:
    fields_by_id = {item.field_id: item for item in candidate.fields}
    approved = tuple(
        item
        for item in _lane_c_approved_cases()
        if fields_by_id[item.field_output.field_id].state != "unknown"
    )
    document_seed, manifest_seed, _texts = _lane_c_document()
    changed = tuple(
        item
        for item in candidate.fields
        if item.state != "unknown"
        and any(
            evidence.parsed_document_hash != document_seed.document_hash
            for evidence in item.evidence
        )
    )
    if not changed:
        return approved
    assert len(changed) == 1
    output = changed[0]
    assert len(output.evidence) == 1
    evidence = output.evidence[0]
    target_block = document_seed.blocks[0].model_copy(
        update={
            "block_id": evidence.locator.subject_ref,
            "content_hash": _sha(evidence.locator.content_snapshot),
        }
    )
    document = type(document_seed).model_validate(
        {
            **document_seed.model_dump(mode="python", exclude={"document_hash"}),
            "blocks": (
                target_block.model_dump(mode="python"),
                *(item.model_dump(mode="python") for item in document_seed.blocks[1:]),
            ),
        }
    )
    manifest = type(manifest_seed).model_validate(
        {
            **manifest_seed.model_dump(mode="python", exclude={"manifest_hash"}),
            "document_hash": document.document_hash,
            "ordered_block_ids": tuple(item.block_id for item in document.blocks),
        }
    )
    assert evidence.parsed_document_hash == document.document_hash
    assert evidence.parse_manifest_hash == manifest.manifest_hash
    replacement = EvidenceReplayCaseV1(
        case_id=f"{output.field_id}:dual-repair-final",
        field_output=output,
        documents=(document,),
        manifests=(manifest,),
    )
    return tuple(
        sorted(
            (item for item in approved if item.field_output.field_id != output.field_id),
            key=lambda item: item.case_id,
        )
    ) + (replacement,)


def _sealed_gate(
    monkeypatch: pytest.MonkeyPatch,
    candidate: Schema67CandidateV2,
) -> admission_119.Schema67ReportGateV1:
    del monkeypatch
    cases = _candidate_evidence_cases(candidate)
    reference = _approved_reference()
    comparator = comparator_119.make_deterministic_schema67_semantic_comparator(reference=reference)
    return admission_119.make_total_control_schema67_report_gate(
        snapshot=_lane_c_authority_snapshot(),
        candidate=candidate,
        evidence_cases=cases,
        frozen_candidate_bundle_sha256=candidate_evidence_bundle_sha256(candidate.fields, cases),
        receipt=_lane_c_receipt(),
        observed_at=_LANE_C_NOW,
        comparator=comparator,
    )


@pytest.mark.parametrize(
    ("mutation", "reason_code"),
    (
        ("task_key", "CANDIDATE_V2_CUSTODY_INVALID"),
        ("field_prompt_authority", "CANDIDATE_TASK_CUSTODY_INVALID"),
    ),
)
def test_loader_rejects_self_rehashed_prepared_task_authority_before_report(
    mutation: str,
    reason_code: str,
) -> None:
    payload = _candidate_wire()
    if mutation == "task_key":
        tasks = cast(list[dict[str, Any]], payload["prepared_tasks"])
        tasks[0]["task_key"] = "attacker-selected-task-key"
        _rehash_candidate_wire(payload)
    else:
        _rewrite_first_field_prompt_authority(payload)

    field_contracts, execution_plan, role_inputs = _lane_c_trusted_candidate_v2_preparation()
    with pytest.raises(
        admission_119.LaneCReportGateError,
        match=reason_code,
    ):
        load_schema67_candidate_v2(
            payload,
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            role_inputs=role_inputs,
        )


def test_twenty_one_unknown_fields_are_pending_and_never_publishable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    reference = _approved_reference()
    gate = _sealed_gate(monkeypatch, candidate)

    report = compile_schema67_candidate_report(
        candidate=candidate,
        gate=gate,
    )

    assert sum(field.expected_state == "present" for field in reference.fields) == 45
    assert sum(field.expected_state == "absent_explicitly" for field in reference.fields) == 1
    assert sum(field.expected_state == "unknown" for field in reference.fields) == 21
    assert sum(len(field.reference_evidence_branch_sha256s) for field in reference.fields) == 94
    assert report.status == "BLOCKED"
    assert report.wiki_admission_allowed is False
    assert report.publishable_field_count == 0
    assert report.counts.present == 45
    assert report.counts.absent_explicitly == 1
    assert report.counts.unknown == 21
    assert gate.semantic_eval_allowed is True
    assert gate.wiki_admission_allowed is False
    unknown = tuple(item for item in report.fields if item.state == "unknown")
    known = tuple(item for item in report.fields if item.state != "unknown")
    assert len(unknown) == 21
    assert all(item.evidence_057_status == "NOT_REQUIRED" for item in unknown)
    assert all(item.semantic_correctness == "PENDING" for item in unknown)
    assert all(item.semantic_completeness == "PENDING" for item in unknown)
    assert all(item.review_item_reason_codes == ("SEMANTIC_UNKNOWN_PENDING",) for item in unknown)
    assert all(item.evidence_057_status == "PASS" for item in known)
    assert any(item.semantic_correctness == "FAIL" for item in known)


def test_dual_repair_candidate_round_trips_into_comparator_and_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built = _lane_c_candidate_v2(_lane_c_approved_cases(), dual_repair=True)
    payload = json.loads(
        json.dumps(
            built.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    field_contracts, execution_plan, role_inputs = _lane_c_trusted_candidate_v2_preparation()
    loaded = load_schema67_candidate_v2(
        payload,
        field_contracts=field_contracts,
        execution_plan=execution_plan,
        role_inputs=role_inputs,
    )
    gate = _sealed_gate(monkeypatch, loaded)
    report = compile_schema67_candidate_report(candidate=loaded, gate=gate)
    reference = _approved_reference()

    assert loaded.candidate_sha256 == built.candidate_sha256
    assert len(loaded.batch_execution.executions) == 8
    assert loaded.batch_receipt.provider_calls == 10
    assert loaded.batch_receipt.response_contract_repairs == 1
    assert loaded.batch_receipt.evidence_repairs == 1
    assert loaded.batch_execution.executions[0].response_contract_repair is not None
    assert loaded.batch_execution.executions[0].evidence_repair is not None
    assert report.counts.present == 45
    assert report.counts.absent_explicitly == 1
    assert report.counts.unknown == 21
    assert sum(len(item.reference_evidence_branch_sha256s) for item in reference.fields) == 94
    assert report.wiki_admission_allowed is False
    assert report.publishable_field_count == 0
    assert all(
        item.review_item_reason_codes == ("SEMANTIC_UNKNOWN_PENDING",)
        for item in report.fields
        if item.state == "unknown"
    )
    candidate_evidence_wire = json.dumps(
        [
            item.model_dump(mode="json")
            for item in (evidence for field in loaded.fields for evidence in field.evidence)
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert "locator_slot" not in candidate_evidence_wire


@pytest.mark.parametrize(
    ("extractor_calls", "repair_calls"),
    ((8, 1), (9, 2)),
)
def test_report_budget_replays_shared_extra_kinds_not_only_total(
    extractor_calls: int,
    repair_calls: int,
) -> None:
    with pytest.raises(ValueError, match="report_budget_invalid"):
        Schema67BudgetReportV1(
            task_count=8,
            locator_calls=0,
            extractor_calls=extractor_calls,
            provider_calls=10,
            transport_retries=0,
            response_contract_repairs=1,
            evidence_repairs=1,
            repair_calls=repair_calls,
        )


def test_single_pass_demotion_report_binds_budget_projection_and_privacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _demoted_candidate()
    gate = _sealed_gate(monkeypatch, candidate)

    report = compile_schema67_candidate_report(candidate=candidate, gate=gate)
    public = render_public_schema67_candidate_report(
        candidate=candidate,
        gate=gate,
        report=report,
    )
    private = render_private_schema67_candidate_report(
        candidate=candidate,
        gate=gate,
        report=report,
        include_raw_values=True,
    )

    demoted_field_ids = tuple(
        field_id
        for field_id in ORDERED_FIELD_IDS
        if any(
            execution.receipt.evidence_demotion is not None
            and field_id in execution.receipt.evidence_demotion.demoted_field_ids
            for execution in candidate.batch_execution.executions
        )
    )
    assert report.demoted_field_count == len(demoted_field_ids) == 2
    assert report.demoted_field_ids == demoted_field_ids
    assert report.budget.model_dump(mode="python") == {
        "task_count": 8,
        "locator_calls": 0,
        "extractor_calls": 8,
        "provider_calls": 8,
        "transport_retries": 0,
        "response_contract_repairs": 0,
        "evidence_repairs": 0,
        "repair_calls": 0,
        "prior_provider_calls": 2,
        "cumulative_provider_calls": 10,
    }
    report_fields = {item.field_id: item for item in report.fields}
    assert all(
        report_fields[field_id].state == "unknown"
        and report_fields[field_id].value_sha256 is None
        and report_fields[field_id].evidence_count == 0
        and report_fields[field_id].review_item_reason_codes == ("EVIDENCE_NONPASS_DEMOTED",)
        for field_id in demoted_field_ids
    )
    assert report.wiki_admission_allowed is False
    assert report.publishable_field_count == 0

    sensitive_values = tuple(
        value
        for execution in candidate.batch_execution.executions
        for item in execution.initial_outputs
        if item.field_id in demoted_field_ids
        for value in (
            item.value_snapshot,
            *(evidence.quote_snapshot for evidence in item.evidence),
            *(evidence.locator.subject_ref for evidence in item.evidence),
            *(evidence.block_id for evidence in item.evidence),
        )
        if value is not None
    ) + tuple(
        value
        for task in candidate.prepared_tasks
        for source_task in task.source_tasks
        for value in (
            source_task.source_revision_id,
            source_task.task_profile.material_profile.source.path,
        )
    )
    for rendered in (public.decode("utf-8"), private.decode("utf-8")):
        assert all(value not in rendered for value in sensitive_values)
    private_payload = json.loads(private)
    private_values = {
        item["field_id"]: item["value_snapshot"] for item in private_payload["raw_values"]
    }
    assert all(private_values[field_id] is None for field_id in demoted_field_ids)

    swapped_values = report.model_dump(mode="python", exclude={"report_sha256"})
    swapped_values["demoted_field_ids"] = tuple(reversed(report.demoted_field_ids))
    with pytest.raises(ValueError, match="candidate_report_invalid"):
        Schema67CandidateReportV1.model_validate(
            {
                **swapped_values,
                "report_sha256": canonical_hash("schema67-candidate-report.v2", swapped_values),
            }
        )


def test_demoted_report_dto_rejects_self_rehashed_legacy_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _demoted_candidate()
    gate = _sealed_gate(monkeypatch, candidate)
    report = compile_schema67_candidate_report(candidate=candidate, gate=gate)
    values = report.model_dump(mode="python", exclude={"report_sha256"})
    budget = cast(dict[str, Any], values["budget"])
    budget["prior_provider_calls"] = None
    budget["cumulative_provider_calls"] = None

    with pytest.raises(ValueError, match="report_budget_invalid"):
        Schema67CandidateReportV1.model_validate(
            {
                **values,
                "report_sha256": canonical_hash("schema67-candidate-report.v2", values),
            }
        )


def test_all_pass_current_report_dto_rejects_self_rehashed_legacy_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    gate = _sealed_gate(monkeypatch, candidate)
    report = compile_schema67_candidate_report(candidate=candidate, gate=gate)
    assert report.demoted_field_count == 0
    assert report.demoted_field_ids == ()
    values = report.model_dump(mode="python", exclude={"report_sha256"})
    budget = cast(dict[str, Any], values["budget"])
    assert (
        budget["prior_provider_calls"],
        budget["cumulative_provider_calls"],
    ) == (2, 10)
    budget["prior_provider_calls"] = None
    budget["cumulative_provider_calls"] = None

    with pytest.raises(ValueError, match="report_budget_invalid"):
        Schema67CandidateReportV1.model_validate(
            {
                **values,
                "report_sha256": canonical_hash("schema67-candidate-report.v2", values),
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("task_count", 7),
        ("locator_calls", 1),
        ("extractor_calls", 9),
        ("provider_calls", 9),
        ("transport_retries", 1),
        ("response_contract_repairs", 1),
        ("evidence_repairs", 1),
        ("repair_calls", 1),
        ("prior_provider_calls", None),
        ("cumulative_provider_calls", None),
    ),
)
def test_single_pass_budget_report_rejects_each_drift(
    field: str,
    value: int | None,
) -> None:
    exact: dict[str, object] = {
        "task_count": 8,
        "locator_calls": 0,
        "extractor_calls": 8,
        "provider_calls": 8,
        "transport_retries": 0,
        "response_contract_repairs": 0,
        "evidence_repairs": 0,
        "repair_calls": 0,
        "prior_provider_calls": 2,
        "cumulative_provider_calls": 10,
    }
    exact[field] = value
    with pytest.raises(ValueError):
        Schema67BudgetReportV1.model_validate(exact)


@pytest.mark.parametrize(
    "mutation",
    ("response_trace", "evidence_plan", "task_receipt", "candidate"),
)
def test_dual_repair_candidate_drift_fails_closed_before_report(
    mutation: str,
) -> None:
    payload = json.loads(
        json.dumps(
            _lane_c_candidate_v2(_lane_c_approved_cases(), dual_repair=True).model_dump(
                mode="json"
            ),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    execution = cast(
        list[dict[str, Any]],
        cast(dict[str, Any], payload["batch_execution"])["executions"],
    )[0]
    if mutation == "response_trace":
        cast(dict[str, Any], execution["response_contract_repair"])["resolution_hash"] = "f" * 64
        _rehash_candidate_wire(payload)
    elif mutation == "evidence_plan":
        cast(dict[str, Any], cast(dict[str, Any], execution["evidence_repair"])["repair_plan"])[
            "field_ids"
        ] = ["foreign-field"]
        _rehash_candidate_wire(payload)
    elif mutation == "task_receipt":
        cast(dict[str, Any], execution["receipt"])["receipt_hash"] = "f" * 64
        _rehash_candidate_wire(payload)
    else:
        payload["candidate_sha256"] = "f" * 64

    field_contracts, execution_plan, role_inputs = _lane_c_trusted_candidate_v2_preparation()
    with pytest.raises(admission_119.LaneCReportGateError):
        load_schema67_candidate_v2(
            payload,
            field_contracts=field_contracts,
            execution_plan=execution_plan,
            role_inputs=role_inputs,
        )


def test_report_integration_rejects_reference_and_receipt_drift() -> None:
    receipt = _lane_c_receipt()
    foreign_receipt = replace(receipt, approved_by="foreign")
    with pytest.raises(
        comparator_119.Schema67SemanticComparatorError,
        match="REFERENCE_RECEIPT_INVALID",
    ):
        comparator_119.load_total_control_approved_schema67_reference(
            receipt=foreign_receipt,
            observed_at=_LANE_C_NOW,
        )

    reference = _approved_reference()
    object.__setattr__(reference.fields[0], "allowed_rendering_sha256s", ("f" * 64,))
    with pytest.raises(
        comparator_119.Schema67SemanticComparatorError,
        match="REFERENCE_AUTHORITY_INVALID",
    ):
        comparator_119.make_deterministic_schema67_semantic_comparator(reference=reference)


def test_public_self_hashed_pass_gate_cannot_replace_lane_c_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    sealed = _sealed_gate(monkeypatch, candidate)
    forged = SimpleNamespace(
        **{
            **admission_119._schema67_report_gate_payload(sealed),
            "status": "READY",
            "wiki_admission_allowed": True,
            "publishable_field_ids": ORDERED_FIELD_IDS,
            "gate_receipt_sha256": _sha("caller-self-hashed-pass"),
        }
    )

    with pytest.raises(Schema67CandidateReportError) as caught:
        compile_schema67_candidate_report(
            candidate=candidate,
            gate=cast(Any, forged),
        )
    assert caught.value.reason_code == "GATE_INVALID"


def test_rehashed_ready_report_cannot_bypass_candidate_and_gate_at_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    gate = _sealed_gate(monkeypatch, candidate)
    report = compile_schema67_candidate_report(candidate=candidate, gate=gate)
    forged_payload = report.model_dump(mode="python", exclude={"report_sha256"})
    forged_payload.update(
        {
            "status": "READY",
            "wiki_admission_allowed": True,
            "publishable_field_count": 67,
        }
    )
    forged = Schema67CandidateReportV1.model_validate(
        {
            **forged_payload,
            "report_sha256": canonical_hash("schema67-candidate-report.v2", forged_payload),
        }
    )

    with pytest.raises(Schema67CandidateReportError):
        render_public_schema67_candidate_report(
            candidate=candidate,
            gate=gate,
            report=forged,
        )
    with pytest.raises(Schema67CandidateReportError):
        render_private_schema67_candidate_report(
            candidate=candidate,
            gate=gate,
            report=forged,
            include_raw_values=True,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "task_order",
        "batch_receipt",
        "final_outputs",
        "candidate_hash",
        "candidate_task_provenance",
    ),
)
def test_exact8_task_and_ordered67_custody_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    candidate = _candidate()
    batch = candidate.batch_execution
    gate = _sealed_gate(monkeypatch, candidate)
    if mutation == "task_order":
        object.__setattr__(
            batch,
            "executions",
            tuple(reversed(batch.executions)),
        )
    elif mutation == "batch_receipt":
        object.__setattr__(
            batch,
            "receipt",
            batch.receipt.model_copy(update={"batch_receipt_sha256": "f" * 64}),
        )
    elif mutation == "final_outputs":
        original = batch.executions[0]
        forged = object.__new__(DeepSeekTaskExecutionV1)
        object.__setattr__(forged, "initial", original.initial)
        object.__setattr__(forged, "initial_outputs", original.initial_outputs)
        object.__setattr__(forged, "final_outputs", tuple(reversed(original.final_outputs)))
        object.__setattr__(forged, "evidence_receipts", original.evidence_receipts)
        object.__setattr__(forged, "response_contract_repair", original.response_contract_repair)
        object.__setattr__(forged, "evidence_repair", original.evidence_repair)
        object.__setattr__(forged, "receipt", original.receipt)
        object.__setattr__(batch, "executions", (forged, *batch.executions[1:]))
    elif mutation == "candidate_hash":
        object.__setattr__(candidate, "candidate_sha256", "f" * 64)
    else:
        object.__setattr__(
            candidate,
            "prepared_tasks",
            tuple(reversed(candidate.prepared_tasks)),
        )

    with pytest.raises(Schema67CandidateReportError) as caught:
        compile_schema67_candidate_report(
            candidate=candidate,
            gate=gate,
        )
    assert caught.value.reason_code in {
        "CANDIDATE_INVALID",
        "BATCH_EXECUTION_INVALID",
        "CANDIDATE_EXECUTION_MISMATCH",
    }


def test_report_binds_linyao_gate_057_and_semantic_receipts_without_raw_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    batch = candidate.batch_execution
    gate = _sealed_gate(monkeypatch, candidate)

    first = compile_schema67_candidate_report(
        candidate=candidate,
        gate=gate,
    )
    second = compile_schema67_candidate_report(
        candidate=candidate,
        gate=gate,
    )
    public = render_public_schema67_candidate_report(
        candidate=candidate,
        gate=gate,
        report=first,
    )
    decoded = json.loads(public)

    assert first == second
    assert first.approved_by == "linyao"
    assert first.reference_receipt_sha256 == gate.reference_receipt_sha256
    assert first.comparator_authority_sha256 == gate.comparator_authority_sha256
    assert first.semantic_evaluation_receipt_sha256 == (gate.semantic_evaluation_receipt_sha256)
    assert first.task_final_outputs_sha256 == tuple(
        item.receipt.final_outputs_sha256 for item in batch.executions
    )
    assert first.fields[0].semantic_decision_receipt_sha256 == (
        gate.rows[0].semantic_decision_receipt_sha256
    )
    assert decoded["report_sha256"] == first.report_sha256
    forbidden_values = tuple(
        item.value_snapshot for item in candidate.fields if item.value_snapshot is not None
    )
    forbidden_quotes = tuple(
        evidence.quote_snapshot for item in candidate.fields for evidence in item.evidence
    )
    for forbidden in (*forbidden_values, *forbidden_quotes):
        assert forbidden not in public.decode("utf-8")


def test_private_renderer_requires_explicit_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    gate = _sealed_gate(monkeypatch, candidate)
    report = compile_schema67_candidate_report(
        candidate=candidate,
        gate=gate,
    )
    with pytest.raises(Schema67CandidateReportError) as caught:
        render_private_schema67_candidate_report(
            candidate=candidate,
            gate=gate,
            report=report,
            include_raw_values=False,  # type: ignore[arg-type]
        )
    assert caught.value.reason_code == "PRIVATE_RENDER_NOT_AUTHORIZED"

    private = render_private_schema67_candidate_report(
        candidate=candidate,
        gate=gate,
        report=report,
        include_raw_values=True,
    )
    known_value = next(
        item.value_snapshot for item in candidate.fields if item.value_snapshot is not None
    )
    known_quote = next(
        evidence.quote_snapshot for item in candidate.fields for evidence in item.evidence
    )
    assert known_value in private.decode("utf-8")
    assert known_quote not in private.decode("utf-8")


def test_absent_requires_evidence_before_gate_composition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    gate = _sealed_gate(monkeypatch, candidate)
    absent = next(item for item in candidate.fields if item.state == "absent_explicitly")
    object.__setattr__(absent, "evidence", ())

    with pytest.raises(Schema67CandidateReportError) as caught:
        compile_schema67_candidate_report(
            candidate=candidate,
            gate=gate,
        )
    assert caught.value.reason_code == "CANDIDATE_INVALID"


def test_lane_c_gate_replace_even_with_rehashed_rows_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _candidate()
    gate = _sealed_gate(monkeypatch, candidate)
    forged_rows = tuple(
        replace(
            row,
            correctness="PASS",
            completeness="PASS",
            review_reason_codes=(),
        )
        for row in gate.rows
    )
    payload = {
        **admission_119._schema67_report_gate_payload(gate),
        "status": "READY",
        "rows": tuple(admission_119._schema67_report_gate_row_payload(row) for row in forged_rows),
        "wiki_admission_allowed": True,
        "publishable_field_ids": ORDERED_FIELD_IDS,
    }
    with pytest.raises(ValueError, match="LANE_C_REPORT_GATE_SEAL_INVALID"):
        replace(
            gate,
            status="READY",
            rows=forged_rows,
            wiki_admission_allowed=True,
            publishable_field_ids=ORDERED_FIELD_IDS,
            gate_receipt_sha256=canonical_hash("schema67-lane-c-report-gate.v1", payload),
        )
