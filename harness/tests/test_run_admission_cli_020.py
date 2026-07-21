"""OpenSpec 020 D1.4/D1.5: derived admission results and redacted CLI artifacts."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pytest import MonkeyPatch

import insurance_harness.goldenset.admission_cli as admission_cli_module
from insurance_harness.goldenset.admission import (
    AdmissionCheck,
    AdmissionResult,
    RunAdmissionDocument,
    derive_admission_result,
    required_admission_check_names,
)
from insurance_harness.goldenset.admission_cli import (
    AdmissionDocumentEvaluator,
    AdmissionEvaluator,
    main,
    run_check,
    run_document_check,
)
from insurance_harness.goldenset.admission_identity import IdentityInspectionRequest
from insurance_harness.goldenset.admission_models import (
    AdmissionDerivedState,
    ModelRolePlan,
    RunAdmissionPlan,
    RunAdmissionPlanPayload,
)

_NOW = datetime(2026, 7, 19, 10, 0, tzinfo=UTC)


def _plan(*, stored_state: str | None = None) -> RunAdmissionPlan:
    roles = {
        role: ModelRolePlan(
            provider="bailian",
            model_id=f"{role}-deployment",
            expected_model_revision="2026-07-19T09:00:00Z",
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        )
        for role in ("annotator", "weak_extractor", "judge")
    }
    derived = None
    if stored_state is not None:
        derived = AdmissionDerivedState(state=stored_state, blockers=())  # type: ignore[arg-type]
    return RunAdmissionPlan(
        payload=RunAdmissionPlanPayload(
            run_identity="gs-v0.1-run-001",
            purpose="gs-v0.1-baseline",
            model_roles=roles,
            budget_contract_hash="a" * 64,
        ),
        derived_state=derived,
    )


def _checks(*, failing: str | None = None) -> tuple[AdmissionCheck, ...]:
    return tuple(
        AdmissionCheck(
            name=name,
            passed=name != failing,
            blocker_code=None if name != failing else "check_failed",
            observed_at=_NOW,
            expires_at=_NOW + timedelta(hours=1),
        )
        for name in sorted(required_admission_check_names())
    )


def _evaluator(
    checks: tuple[AdmissionCheck, ...],
    *,
    revision: str = "f" * 40,
) -> AdmissionEvaluator:
    def evaluate(plan: RunAdmissionPlan) -> AdmissionResult:
        return derive_admission_result(
            plan=plan,
            checks=checks,
            evaluated_revision=revision,
            evaluated_at=_NOW,
            checker_version="020.1",
            runtime_capability_version="budget-ledger-v1",
        )

    return evaluate


def _write_plan(path: Path, plan: RunAdmissionPlan) -> None:
    path.write_text(
        yaml.safe_dump(plan.model_dump(mode="json"), allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )


def _document() -> RunAdmissionDocument:
    return RunAdmissionDocument(
        plan=_plan(),
        identity_request=IdentityInspectionRequest(
            required_dependency_revisions={},
            source_products_root="dataset/shouxian_product",
            golden_products_root="dataset/goldenset/wip-gs-v0.1",
            products=(),
            shared_input_digests={},
            execution_surface_digests={},
            historical_product_ids=(),
            historical_provenance=(),
        ),
    )


def test_d1_4_well_formed_blocked_plan_writes_json_markdown_and_exit_2(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.yaml"
    result_path = tmp_path / "result.json"
    report_path = tmp_path / "report.md"
    _write_plan(plan_path, _plan())

    exit_code = run_check(
        plan_path=plan_path,
        result_json=result_path,
        report_md=report_path,
        evaluator=_evaluator(_checks(failing="provider_probe:judge")),
    )

    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert exit_code == 2
    assert payload["state"] == "BLOCKED"
    assert payload["blockers"] == [
        {"check": "provider_probe:judge", "code": "check_failed"}
    ]
    assert "# Run admission: BLOCKED" in report_path.read_text(encoding="utf-8")


def test_d1_4_invalid_plan_or_checker_error_exits_1_without_ready_artifact(
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "invalid.yaml"
    invalid.write_text("payload: []\n", encoding="utf-8")
    result_path = tmp_path / "result.json"
    report_path = tmp_path / "report.md"

    assert run_check(
        plan_path=invalid,
        result_json=result_path,
        report_md=report_path,
        evaluator=_evaluator(_checks()),
    ) == 1
    assert not result_path.exists()
    assert not report_path.exists()

    valid = tmp_path / "valid.yaml"
    _write_plan(valid, _plan())

    def broken(_plan: RunAdmissionPlan) -> AdmissionResult:
        raise RuntimeError("provider-body-secret")

    assert run_check(
        plan_path=valid,
        result_json=result_path,
        report_md=report_path,
        evaluator=broken,
    ) == 1
    assert not result_path.exists()
    assert not report_path.exists()


def test_d1_4_ready_requires_every_check_and_exit_0(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    _write_plan(plan_path, _plan())
    result_path = tmp_path / "result.json"
    report_path = tmp_path / "report.md"

    assert run_check(
        plan_path=plan_path,
        result_json=result_path,
        report_md=report_path,
        evaluator=_evaluator(_checks()),
    ) == 0
    assert json.loads(result_path.read_text(encoding="utf-8"))["state"] == "READY"

    missing_check = _checks()[:-1]
    blocked = derive_admission_result(
        plan=_plan(),
        checks=missing_check,
        evaluated_revision="f" * 40,
        evaluated_at=_NOW,
        checker_version="020.1",
        runtime_capability_version="budget-ledger-v1",
    )
    assert blocked.state == "BLOCKED"
    assert any(blocker.code == "required_check_missing" for blocker in blocked.blockers)


def test_d1_4_outputs_never_contain_secret_body_or_absolute_path(
    tmp_path: Path,
) -> None:
    secret = "provider-body-secret"
    absolute = "/Users/operator/private/repo"
    plan_path = tmp_path / "plan.yaml"
    plan = _plan()
    values = plan.model_dump(mode="python")
    values["observations"] = [
        {"name": "untrusted", "observed_at": _NOW, "value": f"{secret}:{absolute}"}
    ]
    _write_plan(plan_path, RunAdmissionPlan.model_validate(values))
    result_path = tmp_path / "result.json"
    report_path = tmp_path / "report.md"

    assert run_check(
        plan_path=plan_path,
        result_json=result_path,
        report_md=report_path,
        evaluator=_evaluator(_checks(failing="identity"), revision="a" * 40),
    ) == 2
    rendered = result_path.read_text(encoding="utf-8") + report_path.read_text(
        encoding="utf-8"
    )
    assert secret not in rendered
    assert absolute not in rendered
    assert str(tmp_path) not in rendered


def test_d1_5_tampered_stored_ready_or_blockers_are_ignored() -> None:
    stored_ready = _plan(stored_state="READY")
    result = derive_admission_result(
        plan=stored_ready,
        checks=_checks(failing="budget_approval"),
        evaluated_revision="f" * 40,
        evaluated_at=_NOW,
        checker_version="020.1",
        runtime_capability_version="budget-ledger-v1",
    )
    assert result.state == "BLOCKED"
    assert result.blockers[0].check == "budget_approval"


def test_d1_5_expired_or_drifted_observation_rederives_blocked() -> None:
    checks = list(_checks())
    checks[0] = checks[0].model_copy(update={"expires_at": _NOW})
    result = derive_admission_result(
        plan=_plan(stored_state="READY"),
        checks=tuple(checks),
        evaluated_revision="f" * 40,
        evaluated_at=_NOW,
        checker_version="020.1",
        runtime_capability_version="budget-ledger-v1",
    )
    assert result.state == "BLOCKED"
    assert result.blockers[0].code == "observation_expired"


def test_d1_4_duplicate_or_unknown_checks_fail_closed() -> None:
    checks = _checks()
    duplicate = derive_admission_result(
        plan=_plan(),
        checks=(*checks, checks[0]),
        evaluated_revision="f" * 40,
        evaluated_at=_NOW,
        checker_version="020.1",
        runtime_capability_version="budget-ledger-v1",
    )
    assert any(blocker.code == "duplicate_check" for blocker in duplicate.blockers)

    unexpected = AdmissionCheck(
        name="caller_supplied_ready",
        passed=True,
        observed_at=_NOW,
        expires_at=_NOW + timedelta(hours=1),
    )
    result = derive_admission_result(
        plan=_plan(),
        checks=(*checks, unexpected),
        evaluated_revision="f" * 40,
        evaluated_at=_NOW,
        checker_version="020.1",
        runtime_capability_version="budget-ledger-v1",
    )
    assert result.state == "BLOCKED"
    assert result.blockers[-1].code == "unexpected_check"


def test_d1_4_result_commit_failure_leaves_no_partial_ready_artifact(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    plan_path = tmp_path / "plan.yaml"
    result_path = tmp_path / "result.json"
    report_path = tmp_path / "report.md"
    _write_plan(plan_path, _plan())
    real_replace = os.replace

    def fail_result_replace(source: Path, destination: Path) -> None:
        if destination == result_path:
            raise OSError("injected result commit failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_result_replace)
    assert run_check(
        plan_path=plan_path,
        result_json=result_path,
        report_md=report_path,
        evaluator=_evaluator(_checks()),
    ) == 1
    assert not result_path.exists()
    assert not report_path.exists()


def test_d1_4_full_document_writer_uses_canonical_json(tmp_path: Path) -> None:
    document = _document()
    plan_path = tmp_path / "document.yaml"
    plan_path.write_text(
        yaml.safe_dump(document.model_dump(mode="json"), sort_keys=True),
        encoding="utf-8",
    )
    result_path = tmp_path / "result.json"
    report_path = tmp_path / "report.md"

    def evaluate(candidate: RunAdmissionDocument) -> AdmissionResult:
        return _evaluator(_checks())(candidate.plan)

    evaluator: AdmissionDocumentEvaluator = evaluate
    assert run_document_check(
        plan_path=plan_path,
        result_json=result_path,
        report_md=report_path,
        evaluator=evaluator,
    ) == 0
    rendered = result_path.read_text(encoding="utf-8")
    assert rendered.count("\n") == 1
    assert rendered.startswith('{"blockers":[]')
    digest = hashlib.sha256(rendered.rstrip("\n").encode("utf-8")).hexdigest()
    assert f"Canonical JSON commit marker: `{digest}`" in report_path.read_text(
        encoding="utf-8"
    )


def test_d1_4_module_cli_rejects_absolute_plan_without_artifacts(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "document.yaml"
    plan_path.write_text("plan: invalid\n", encoding="utf-8")
    result_path = tmp_path / "result.json"
    report_path = tmp_path / "report.md"

    assert main(
        [
            "check",
            "--plan",
            str(plan_path),
            "--repo-root",
            str(tmp_path),
            "--result-json",
            str(result_path),
            "--report-md",
            str(report_path),
        ]
    ) == 1
    assert not result_path.exists()
    assert not report_path.exists()


def test_d1_4_current_thirteen_product_plan_generates_static_blocked_artifact(
    tmp_path: Path,
) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    relative_plan = Path(
        "openspec/changes/020-golden-v01-baseline-run/run-admission.yaml"
    )
    result_path = tmp_path / "result.json"
    report_path = tmp_path / "report.md"

    assert main(
        [
            "check",
            "--plan",
            relative_plan.as_posix(),
            "--repo-root",
            str(repo_root),
            "--result-json",
            str(result_path),
            "--report-md",
            str(report_path),
        ]
    ) == 2
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    rendered = result_path.read_text(encoding="utf-8") + report_path.read_text(
        encoding="utf-8"
    )
    assert payload["state"] == "BLOCKED"
    assert len(payload["evidence"]["identity"]["product_digests"]) == 13
    assert not any(probe["verified"] for probe in payload["evidence"]["probes"])
    assert str(repo_root) not in rendered


def test_d1_4_output_alias_cannot_delete_plan_or_merge_artifacts(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "plan.yaml"
    report_path = tmp_path / "report.md"
    _write_plan(plan_path, _plan())
    original = plan_path.read_bytes()

    assert run_check(
        plan_path=plan_path,
        result_json=plan_path,
        report_md=report_path,
        evaluator=_evaluator(_checks()),
    ) == 1
    assert plan_path.read_bytes() == original
    assert not report_path.exists()

    shared_output = tmp_path / "shared.out"
    assert run_check(
        plan_path=plan_path,
        result_json=shared_output,
        report_md=shared_output,
        evaluator=_evaluator(_checks()),
    ) == 1
    assert not shared_output.exists()


def test_d1_1d_duplicate_yaml_keys_are_rejected_not_last_wins(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "duplicate.yaml"
    serialized = yaml.safe_dump(
        _plan().model_dump(mode="json"), allow_unicode=True, sort_keys=True
    )
    run_identity_line = "  run_identity: gs-v0.1-run-001\n"
    assert run_identity_line in serialized
    plan_path.write_text(
        serialized.replace(
            run_identity_line,
            run_identity_line + run_identity_line,
            1,
        ),
        encoding="utf-8",
    )
    result_path = tmp_path / "result.json"
    report_path = tmp_path / "report.md"

    assert run_check(
        plan_path=plan_path,
        result_json=result_path,
        report_md=report_path,
        evaluator=_evaluator(_checks()),
    ) == 1
    assert not result_path.exists()
    assert not report_path.exists()


def test_d1_1d_run_cli_cannot_supply_its_own_trust_store(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result_path = tmp_path / "result.json"
    report_path = tmp_path / "report.md"
    fake_trust = tmp_path / "self-authorized.yaml"
    fake_trust.write_text(
        "public_keys: {}\nbudget_roles: [budget_approver]\n"
        "provenance_roles: [provenance_approver]\n",
        encoding="utf-8",
    )

    assert main(
        [
            "check",
            "--plan",
            "openspec/changes/020-golden-v01-baseline-run/run-admission.yaml",
            "--repo-root",
            str(repo_root),
            "--trusted-keys",
            str(fake_trust),
            "--result-json",
            str(result_path),
            "--report-md",
            str(report_path),
        ]
    ) == 1
    assert not result_path.exists()
    assert not report_path.exists()


def test_d1_1d_deployment_trust_store_rejects_unprotected_file(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    trust_path = tmp_path / "trust.yaml"
    trust_path.write_text(
        "public_keys: {}\nbudget_roles: []\nprovenance_roles: []\n",
        encoding="utf-8",
    )
    trust_path.chmod(0o666)
    monkeypatch.setattr(
        admission_cli_module,
        "_DEPLOYMENT_TRUST_PATH",
        trust_path,
    )

    with pytest.raises(PermissionError):
        admission_cli_module._load_deployment_approval_configuration()
