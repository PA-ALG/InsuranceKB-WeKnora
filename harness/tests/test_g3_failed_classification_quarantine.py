from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runner
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_sha256_830_g3
from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import (
    BatchCorpusV1,
    BatchResolutionPolicyV1,
)
from insurance_harness.run_admission.g3_models import (
    G3BoundedAdmissionPlanV1,
    G3CallTerminalReceiptV1,
    canonical_json,
)

_PACKAGE = Path("/private/tmp/g3-gemini-c-stage-package-05/install/sha256")
_SNAPSHOT = Path("/private/tmp/g3-gemini-run-c-05-chain-snapshot")
_PLAN = (
    _PACKAGE
    / "e2dce64e43b92aa8aa07332a801238103c2055930b4c343bee31caee13aac5ff"
    / "stage-input.json"
)
_CORPUS = (
    _PACKAGE
    / "84d9d20a9d30caf74c72ecfbabf23d497c07adbd613bdbc9d4af9c94574841a1"
    / "batch-corpus.json"
)
_POLICY = (
    _PACKAGE
    / "fd666a5b88022a935ef88638ebc670f09bec31438df399bfa58d7e1232fe24c3"
    / "batch-resolution-policy.json"
)
_ADMISSION = "5951c1cdab6fd63ceffda4432b4b805cea77d542da52efdb05f2c66ade33954e"
_FAILED_CALL = "g3-gemini-actual-05-c-15"
_SUCCESS_CALL = "g3-gemini-actual-05-c-14"


pytestmark = pytest.mark.skipif(
    not all(path.exists() for path in (_PLAN, _CORPUS, _POLICY, _SNAPSHOT)),
    reason="bounded historical C05 evidence is not installed",
)


type QuarantineCase = tuple[
    G3BoundedAdmissionPlanV1,
    BatchCorpusV1,
    BatchResolutionPolicyV1,
    dict[str, G3CallTerminalReceiptV1],
]


@pytest.fixture()
def actual_c05(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> QuarantineCase:
    plan = G3BoundedAdmissionPlanV1.model_validate_json(_PLAN.read_bytes())
    corpus = BatchCorpusV1.model_validate_json(_CORPUS.read_bytes())
    policy = BatchResolutionPolicyV1.model_validate_json(_POLICY.read_bytes())
    ledger = tmp_path / "ledger"
    chain = ledger / "chains" / plan.chain_manifest_hash
    chain.parent.mkdir(parents=True, mode=0o700)
    shutil.copytree(_SNAPSHOT, chain)
    for path in (ledger, *ledger.rglob("*")):
        path.chmod(0o700 if path.is_dir() else 0o600)
    monkeypatch.setattr(
        "insurance_harness.model_policy.g3_bounded_gateway.G3_LEDGER_ROOT", str(ledger)
    )
    terminals = {
        call.call_id: G3CallTerminalReceiptV1.model_validate_json(
            next(
                leaf
                for leaf in chain.glob("calls/*/call-terminal.json")
                if G3CallTerminalReceiptV1.model_validate_json(leaf.read_bytes()).call_id
                == call.call_id
            ).read_bytes()
        )
        for call in plan.request_manifest.calls
    }
    return plan, corpus, policy, terminals


def test_wired_failure_route_materializes_exact_named_quarantine(
    actual_c05: QuarantineCase,
) -> None:
    plan, corpus, policy, terminals = actual_c05
    result = runner._persist_failed_classification_quarantines(
        plan=plan,
        admission_digest=_ADMISSION,
        corpus=corpus,
        policy=policy,
        failed_terminals=(terminals[_FAILED_CALL],),
    )
    decision = result.decisions[0].decision
    assert decision.material_id == "g3-material-21"
    assert decision.disposition == "QUARANTINE"
    assert decision.reason_codes == ("MODEL_RECEIPT_INVALID",)
    assert decision.queue_id == "queue-g3"
    assert decision.queue_owner == "本任务用户（本人）"
    assert (
        result.decisions[0].call_terminal_receipt_sha256 == terminals[_FAILED_CALL].receipt_sha256
    )
    assert terminals[_FAILED_CALL].status == "FAILED"
    persisted = (
        runner._g3_chain_directory(plan)
        / "stage-results/C_CLASSIFY/failed-classification-quarantine.json"
    )
    assert runner._read_secure_exact(persisted) == canonical_json(
        result.model_dump(mode="json", round_trip=True)
    )


def test_failed_classification_quarantine_rejects_wrong_request_and_material(
    actual_c05: QuarantineCase,
) -> None:
    plan, corpus, policy, terminals = actual_c05
    failed = terminals[_FAILED_CALL]
    failed_values = failed.model_dump(mode="python")
    failed_values["request_body_sha256"] = "0" * 64
    wrong_request = G3CallTerminalReceiptV1.model_construct(**failed_values)
    calls = []
    for call in plan.request_manifest.calls:
        if call.call_id == _FAILED_CALL:
            values = call.model_dump(mode="python")
            values["material_ids"] = ("g3-material-19",)
            call = type(call).model_construct(**values)
        calls.append(call)
    manifest_values = plan.request_manifest.model_dump(mode="python")
    manifest_values["calls"] = tuple(calls)
    wrong_manifest = type(plan.request_manifest).model_construct(**manifest_values)
    plan_values = plan.model_dump(mode="python")
    plan_values["request_manifest"] = wrong_manifest
    wrong_material = G3BoundedAdmissionPlanV1.model_construct(**plan_values)
    for changed in (
        wrong_request,
        wrong_material,
    ):
        if isinstance(changed, G3BoundedAdmissionPlanV1):
            changed_plan, changed_terminal = changed, failed
        else:
            changed_plan, changed_terminal = plan, changed
        with pytest.raises(ValueError):
            runner._failed_classification_quarantines(
                admission_digest=_ADMISSION,
                corpus=corpus,
                policy=policy,
                plan=changed_plan,
                failed_terminals=(changed_terminal,),
            )


def test_failed_classification_quarantine_rejects_success_terminal(
    actual_c05: QuarantineCase,
) -> None:
    plan, corpus, policy, terminals = actual_c05
    with pytest.raises(ValueError, match="failed classification terminal"):
        runner._failed_classification_quarantines(
            plan=plan,
            admission_digest=_ADMISSION,
            corpus=corpus,
            policy=policy,
            failed_terminals=(terminals[_SUCCESS_CALL],),
        )


def test_failed_classification_quarantine_rejects_policy_outside_admission(
    actual_c05: QuarantineCase,
) -> None:
    plan, corpus, policy, terminals = actual_c05
    payload = policy.model_dump(mode="python", exclude={"policy_sha256"})
    payload["queue_id"] = "foreign-queue"
    foreign = BatchResolutionPolicyV1.model_validate(
        {
            **payload,
            "policy_sha256": batch_sha256_830_g3(policy.contract, payload),
        }
    )
    with pytest.raises(ValueError, match="admission input"):
        runner._failed_classification_quarantines(
            plan=plan,
            admission_digest=_ADMISSION,
            corpus=corpus,
            policy=foreign,
            failed_terminals=(terminals[_FAILED_CALL],),
        )
