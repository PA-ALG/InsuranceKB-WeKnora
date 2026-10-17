from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from typing import Any, cast

import pytest

from insurance_harness.canonical import canonical_hash
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


def _sha(value: str | bytes) -> str:
    payload = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
