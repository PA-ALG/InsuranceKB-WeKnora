from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    _call_terminal,
    _failed_call_terminal,
)
from insurance_harness.model_policy import (
    ModelCallRequest,
    ModelIdentity,
    ModelPermitView,
    PolicyReceipt,
)
from insurance_harness.model_policy.g3_bounded_gateway import (
    G3_LEDGER_ROOT,
    G3BoundedRouteConfig,
    G3LedgerDenied,
    _fixed_openai_compatible_dispatch,
    _read_successful_g3_stage_call,
    _reopen_completed_g3_call,
    _reservation_snapshot,
    _write_exclusive,
    reserve_g3_call,
    validate_g3_route,
)
from insurance_harness.model_policy.models import _model_permit_view_digest
from insurance_harness.run_admission.g3_models import (
    G3ArtifactRefV1,
    G3BoundedAdmissionPlanV1,
    G3CallTerminalReceiptV1,
    G3CostAuditV1,
    G3DispositionCountsV1,
    G3PreparedReceiptV1,
    G3ProviderResponseMetaV1,
    G3ProviderUsageV1,
    G3StageLedgerBindingV1,
    G3StageTerminalReceiptV1,
    G3StartedReceiptV1,
    G3UsageTotalsV1,
    canonical_g3_hash,
    canonical_json,
)
from tests.test_run_admission_g3_bounded_830 import H, _hashed, valid_c_plan


def test_route_is_https_exact_and_redirect_free() -> None:
    route = G3BoundedRouteConfig(
        endpoint_origin="https://dashscope.aliyuncs.com",
        endpoint_path="/compatible-mode/v1/chat/completions",
        timeout_seconds=30,
        follow_redirects=False,
    )
    assert validate_g3_route(route) == route
    for origin in (
        "http://dashscope.aliyuncs.com",
        "https://user@dashscope.aliyuncs.com",
        "https://dashscope.aliyuncs.com?x=1",
    ):
        with pytest.raises(G3LedgerDenied):
            validate_g3_route(route.model_copy(update={"endpoint_origin": origin}))
    with pytest.raises(ValueError):
        G3BoundedRouteConfig(
            endpoint_origin="https://dashscope.aliyuncs.com",
            endpoint_path="/chat/completions",
            timeout_seconds=30,
            follow_redirects=False,
        )


def test_factory_has_no_path_sink_callback_client_or_target_injection() -> None:
    from insurance_harness.model_policy.g3_bounded_gateway import (
        build_g3_bounded_model_client,
    )

    parameters = set(inspect.signature(build_g3_bounded_model_client).parameters)
    assert not parameters & {
        "path",
        "root",
        "ledger_root",
        "sink",
        "callback",
        "client",
        "target",
        "transport",
    }
    assert G3_LEDGER_ROOT == "/var/lib/insurancekb/g3-bounded-execution-ledger/v1"


def _write_started_and_success(call_dir: Path, plan_call: object) -> None:
    call = plan_call
    started0 = G3StartedReceiptV1(
        contract="g3-started-receipt.830.v1",
        prepared_receipt_sha256="a" * 64,
        started_at=datetime.now(UTC),
        monotonic_start_ns=1,
        call_consumed=True,
        receipt_sha256=H,
    )
    started = started0.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-started-receipt.830.v1", started0, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        call_dir / "started.json",
        canonical_json(started.model_dump(mode="json", round_trip=True)),
    )
    reservation = __import__(
        "insurance_harness.run_admission.g3_models",
        fromlist=["G3CallReservationV1"],
    ).G3CallReservationV1.model_validate_json((call_dir / "reservation.json").read_bytes())
    cost = G3CostAuditV1(
        status="NOT_MEASURED",
        currency=None,
        amount_minor_units=None,
        rate_card_sha256=None,
        provider_cost_receipt_sha256=None,
        reason_code="NO_FROZEN_RATE_CARD",
    )
    terminal0 = G3CallTerminalReceiptV1(
        contract="g3-call-terminal-receipt.830.v1",
        chain_id="chain-1",
        stage="C_CLASSIFY",
        call_id=call.call_id,
        ordinal=call.ordinal,
        run_id="run-1",
        run_revision="rev-1",
        admission_artifact_digest="8" * 64,
        verified_binding_digest="7" * 64,
        call_reservation_receipt_sha256=reservation.receipt_sha256,
        policy_receipt_sha256="6" * 64,
        identity=ModelIdentity.model_validate(call.identity.model_dump()),
        endpoint_origin=call.endpoint_origin,
        endpoint_path="/compatible-mode/v1/chat/completions",
        request_body_sha256=call.request_body_sha256,
        request_bytes=call.request_bytes,
        response_meta=G3ProviderResponseMetaV1(
            http_status=200,
            content_type="application/json",
            provider_request_id="request-1",
            canonical_headers_sha256="5" * 64,
        ),
        response_body_sha256="4" * 64,
        response_bytes=2,
        semantic_content_sha256="3" * 64,
        projection_sha256="2" * 64,
        provider_usage=G3ProviderUsageV1(
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
            usage_verified=True,
        ),
        cost_audit=cost,
        started_receipt_sha256=started.receipt_sha256,
        started_at=started.started_at,
        ended_at=datetime.now(UTC),
        duration_ms=0,
        status="SUCCESS",
        reason_code="SUCCESS",
        retry_count=0,
        receipt_sha256=H,
    )
    terminal = terminal0.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-call-terminal-receipt.830.v1", terminal0, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        call_dir / "call-terminal.json",
        canonical_json(terminal.model_dump(mode="json", round_trip=True)),
    )


def _plan_with_real_request(body: bytes) -> G3BoundedAdmissionPlanV1:
    base = valid_c_plan()
    old_call = base.request_manifest.calls[0]
    digest = hashlib.sha256(body).hexdigest()
    call = old_call.model_copy(
        update={"request_body_sha256": digest, "request_bytes": len(body)}
    )
    manifest = _hashed(
        type(base.request_manifest),
        "g3-request-manifest.830.v1",
        "manifest_hash",
        contract=base.request_manifest.contract,
        stage=base.stage,
        chain_id=base.chain_id,
        calls=(call,),
    )

    def updated_refs(rows: tuple[G3ArtifactRefV1, ...]) -> tuple[G3ArtifactRefV1, ...]:
        return tuple(
            row.model_copy(
                update={
                    "artifact_ref": (
                        "/var/lib/insurancekb/run-admission/sha256/"
                        f"{digest}/request-body.json"
                    ),
                    "sha256": digest,
                    "bytes": len(body),
                }
            )
            for row in rows
        )

    eligibility = _hashed(
        type(base.eligibility_lock),
        "g3-stage-eligibility.830.v1",
        "eligibility_hash",
        **base.eligibility_lock.model_dump(
            mode="python", round_trip=True, exclude={"input_artifacts", "eligibility_hash"}
        ),
        input_artifacts=updated_refs(base.eligibility_lock.input_artifacts),
    )
    dispatch = _hashed(
        type(base.dispatch_lock),
        "g3-stage-dispatch.830.v1",
        "structured_dispatch_hash",
        **base.dispatch_lock.model_dump(
            mode="python", round_trip=True, exclude={"calls", "structured_dispatch_hash"}
        ),
        calls=(call,),
    )
    rights = _hashed(
        type(base.rights_lock),
        "g3-external-send-rights.830.v1",
        "rights_hash",
        **base.rights_lock.model_dump(
            mode="python", round_trip=True, exclude={"artifacts", "rights_hash"}
        ),
        artifacts=updated_refs(base.rights_lock.artifacts),
    )
    provenance = _hashed(
        type(base.provenance_lock),
        "g3-stage-provenance.830.v1",
        "provenance_hash",
        **base.provenance_lock.model_dump(
            mode="python", round_trip=True, exclude={"artifacts", "provenance_hash"}
        ),
        artifacts=updated_refs(base.provenance_lock.artifacts),
    )
    return base.model_copy(
        update={
            "request_manifest": manifest,
            "manifest_hash": manifest.manifest_hash,
            "eligibility_lock": eligibility,
            "eligibility_hash": eligibility.eligibility_hash,
            "dispatch_lock": dispatch,
            "structured_dispatch_hash": dispatch.structured_dispatch_hash,
            "rights_lock": rights,
            "rights_hash": rights.rights_hash,
            "provenance_lock": provenance,
            "provenance_hash": provenance.provenance_hash,
        }
    )


def _complete_successful_stage(
    root: Path,
) -> tuple[
    G3BoundedAdmissionPlanV1,
    G3CallTerminalReceiptV1,
    bytes,
    bytes,
    Path,
]:
    body = b'{"ok":true}\n'
    plan = _plan_with_real_request(body)
    call = plan.request_manifest.calls[0]
    capability = reserve_g3_call(
        plan=plan, call=call, admission_artifact_digest="8" * 64
    )
    snapshot = _reservation_snapshot(capability)
    assert snapshot is not None
    call_dir = Path(str(snapshot[2]))
    reservation = snapshot[4]
    prepared0 = G3PreparedReceiptV1(
        contract="g3-prepared-receipt.830.v1",
        chain_id=plan.chain_id,
        stage=plan.stage,
        call_id=call.call_id,
        ordinal=call.ordinal,
        admission_artifact_digest="8" * 64,
        verified_binding_digest="7" * 64,
        call_reservation_receipt_sha256=reservation.receipt_sha256,
        request_body_sha256=call.request_body_sha256,
        request_bytes=call.request_bytes,
        input_token_estimate=call.input_token_estimate,
        input_token_ceiling=call.input_token_ceiling,
        output_token_ceiling=call.output_token_ceiling,
        timeout_seconds=call.timeout_seconds,
        reserved_chain_budget=snapshot[5],
        prepared_at=datetime.now(UTC),
        receipt_sha256=H,
    )
    prepared = prepared0.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-prepared-receipt.830.v1", prepared0, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        call_dir / "prepared.json",
        canonical_json(prepared.model_dump(mode="json", round_trip=True)),
    )
    started0 = G3StartedReceiptV1(
        contract="g3-started-receipt.830.v1",
        prepared_receipt_sha256=prepared.receipt_sha256,
        started_at=datetime.now(UTC),
        monotonic_start_ns=1,
        call_consumed=True,
        receipt_sha256=H,
    )
    started = started0.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-started-receipt.830.v1", started0, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        call_dir / "started.json",
        canonical_json(started.model_dump(mode="json", round_trip=True)),
    )
    view = ModelPermitView(
        identity=call.identity,
        purpose=plan.purpose,
        run_schema_version=plan.run_schema_version,
        space_id=plan.space_id,
        run_id=plan.run_id,
        run_revision=plan.run_revision,
        admission_hash="8" * 64,
        verified_binding_digest="7" * 64,
        template_hash=plan.template_lock.approved_template_hash,
        model_plan_hash=plan.model_plan_hash,
        policy_snapshot_digest="6" * 64,
        call_scope_hash="5" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    policy = PolicyReceipt(
        decision="ALLOW",
        reason_code="policy_allowed",
        identity_key=call.identity.identity_key,
        purpose=plan.purpose,
        run_schema_version=plan.run_schema_version,
        space_id=plan.space_id,
        run_id=plan.run_id,
        run_revision=plan.run_revision,
        admission_hash="8" * 64,
        request_digest="4" * 64,
        binding_digest="3" * 64,
        verified_binding_digest="7" * 64,
        template_hash=plan.template_lock.approved_template_hash,
        model_plan_hash=plan.model_plan_hash,
        call_scope_hash="5" * 64,
        attempted_context_digest="2" * 64,
        policy_snapshot_digest="6" * 64,
        permit_digest=_model_permit_view_digest(view),
        permit_view=view,
        evaluated_at=datetime.now(UTC),
    )
    policy_bytes = policy.model_dump_json().encode()
    semantic_bytes = b'{"result":"fixture"}'
    response_bytes = b'{"choices":[{"message":{"content":"fixture"}}]}'
    _write_exclusive(call_dir / "policy-receipt.json", policy_bytes)
    _write_exclusive(call_dir / "request-body.private.json", body)
    _write_exclusive(call_dir / "response-body.private.json", response_bytes)
    _write_exclusive(call_dir / "semantic-content.private.json", semantic_bytes)
    cost = G3CostAuditV1(
        status="NOT_MEASURED",
        currency=None,
        amount_minor_units=None,
        rate_card_sha256=None,
        provider_cost_receipt_sha256=None,
        reason_code="NO_FROZEN_RATE_CARD",
    )
    terminal0 = G3CallTerminalReceiptV1(
        contract="g3-call-terminal-receipt.830.v1",
        chain_id=plan.chain_id,
        stage=plan.stage,
        call_id=call.call_id,
        ordinal=call.ordinal,
        run_id=plan.run_id,
        run_revision=plan.run_revision,
        admission_artifact_digest="8" * 64,
        verified_binding_digest="7" * 64,
        call_reservation_receipt_sha256=reservation.receipt_sha256,
        policy_receipt_sha256=hashlib.sha256(policy_bytes).hexdigest(),
        identity=call.identity,
        endpoint_origin=call.endpoint_origin,
        endpoint_path=call.endpoint_path,
        request_body_sha256=call.request_body_sha256,
        request_bytes=call.request_bytes,
        response_meta=G3ProviderResponseMetaV1(
            http_status=200,
            content_type="application/json",
            provider_request_id="fixture-request",
            canonical_headers_sha256="4" * 64,
        ),
        response_body_sha256=hashlib.sha256(response_bytes).hexdigest(),
        response_bytes=len(response_bytes),
        semantic_content_sha256=hashlib.sha256(semantic_bytes).hexdigest(),
        projection_sha256="2" * 64,
        provider_usage=G3ProviderUsageV1(
            prompt_tokens=1, completion_tokens=1, total_tokens=2, usage_verified=True
        ),
        cost_audit=cost,
        started_receipt_sha256=started.receipt_sha256,
        started_at=started.started_at,
        ended_at=datetime.now(UTC),
        duration_ms=0,
        status="SUCCESS",
        reason_code="SUCCESS",
        retry_count=0,
        receipt_sha256=H,
    )
    terminal = terminal0.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-call-terminal-receipt.830.v1", terminal0, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        call_dir / "call-terminal.json",
        canonical_json(terminal.model_dump(mode="json", round_trip=True)),
    )
    chain_dir = call_dir.parents[1]
    binding = G3StageLedgerBindingV1.model_validate_json(
        (chain_dir / "stage-bindings" / f"{plan.stage}.json").read_bytes()
    )
    stage0 = G3StageTerminalReceiptV1(
        contract="g3-stage-terminal-receipt.830.v1",
        chain_id=plan.chain_id,
        stage=plan.stage,
        parent_authorization_digest=plan.parent_authorization_digest,
        admission_artifact_digest="8" * 64,
        prior_terminal_receipt_sha256=plan.prior_terminal_receipt_sha256,
        stage_binding_receipt_sha256=binding.receipt_sha256,
        call_terminal_sha256s=(terminal.receipt_sha256,),
        stage_output_sha256="1" * 64,
        disposition_counts=G3DispositionCountsV1(
            MATCH=1, CREATE=0, MULTI=0, NEEDS_CONFIRM=0, QUARANTINE=0
        ),
        coverage_gap_codes=(),
        calls_consumed=1,
        provider_usage_total=G3UsageTotalsV1(
            successful_usage_records=1,
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        ),
        cost_audit=cost,
        started_at=started.started_at,
        ended_at=datetime.now(UTC),
        status="SUCCESS",
        receipt_sha256=H,
    )
    stage = stage0.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-stage-terminal-receipt.830.v1", stage0, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        chain_dir / "stage-terminals" / f"{plan.stage}.json",
        canonical_json(stage.model_dump(mode="json", round_trip=True)),
    )
    return plan, terminal, semantic_bytes, policy_bytes, call_dir


def _tree_snapshot(root: Path) -> tuple[tuple[str, str], ...]:
    return tuple(
        (str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def _child_reserve(root: Path, plan_path: Path, ordinal: int) -> subprocess.CompletedProcess[str]:
    script = (
        "import sys;"
        "from pathlib import Path;"
        "import insurance_harness.model_policy.g3_bounded_gateway as g;"
        "from insurance_harness.run_admission.g3_models import G3BoundedAdmissionPlanV1;"
        "g.G3_LEDGER_ROOT=sys.argv[1];"
        "p=G3BoundedAdmissionPlanV1.model_validate_json(Path(sys.argv[2]).read_bytes());"
        "c=g.reserve_g3_call(plan=p,call=p.request_manifest.calls[int(sys.argv[3])],"
        "admission_artifact_digest='8'*64);"
        "print(g._reservation_snapshot(c)[2])"
    )
    return subprocess.run(
        [sys.executable, "-c", script, str(root), str(plan_path), str(ordinal)],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=False,
    )


def test_new_process_continues_only_after_trusted_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import insurance_harness.model_policy.g3_bounded_gateway as gateway

    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    plan = valid_c_plan(call_count=2)
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(canonical_json(plan.model_dump(mode="json", round_trip=True)))
    capability = reserve_g3_call(
        plan=plan, call=plan.request_manifest.calls[0], admission_artifact_digest="8" * 64
    )
    snapshot = _reservation_snapshot(capability)
    assert snapshot is not None
    _write_started_and_success(Path(str(snapshot[2])), plan.request_manifest.calls[0])
    result = _child_reserve(root, plan_path, 1)
    assert result.returncode == 0, result.stderr


def test_started_without_terminal_is_permanently_denied_in_new_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import insurance_harness.model_policy.g3_bounded_gateway as gateway

    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    plan = valid_c_plan(call_count=2)
    plan_path = tmp_path / "plan.json"
    plan_path.write_bytes(canonical_json(plan.model_dump(mode="json", round_trip=True)))
    capability = reserve_g3_call(
        plan=plan, call=plan.request_manifest.calls[0], admission_artifact_digest="8" * 64
    )
    snapshot = _reservation_snapshot(capability)
    assert snapshot is not None
    call_dir = Path(str(snapshot[2]))
    started0 = G3StartedReceiptV1(
        contract="g3-started-receipt.830.v1",
        prepared_receipt_sha256="a" * 64,
        started_at=datetime.now(UTC),
        monotonic_start_ns=1,
        call_consumed=True,
        receipt_sha256=H,
    )
    started = started0.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-started-receipt.830.v1", started0, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        call_dir / "started.json",
        canonical_json(started.model_dump(mode="json", round_trip=True)),
    )
    with pytest.raises(G3LedgerDenied, match="G3 bounded ledger denied") as unknown:
        _reopen_completed_g3_call(
            plan=plan,
            call=plan.request_manifest.calls[0],
            admission_artifact_digest="8" * 64,
        )
    assert unknown.value.reason_code == "OUTCOME_UNKNOWN"
    result = _child_reserve(root, plan_path, 1)
    assert result.returncode != 0
    assert not tuple((root / "chains" / plan.chain_manifest_hash / "stage-terminals").iterdir())


def test_completed_stage_reader_validates_leaf_without_mutating_ledger(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import insurance_harness.model_policy.g3_bounded_gateway as gateway

    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    plan, terminal, semantic_bytes, policy_bytes, call_dir = _complete_successful_stage(root)
    before = _tree_snapshot(root)

    with pytest.raises(G3LedgerDenied) as recovery_denial:
        _reopen_completed_g3_call(
            plan=plan,
            call=plan.request_manifest.calls[0],
            admission_artifact_digest="8" * 64,
        )
    assert recovery_denial.value.reason_code == "DUPLICATE_OR_LEDGER_CONFLICT"
    assert _read_successful_g3_stage_call(
        plan=plan,
        call=plan.request_manifest.calls[0],
        admission_artifact_digest="8" * 64,
    ) == (terminal, semantic_bytes, policy_bytes, str(call_dir))
    assert _tree_snapshot(root) == before


@pytest.mark.parametrize(
    ("change", "reason"),
    (
        ({"contract": "wrong-stage-terminal"}, "RESERVATION_INCOMPLETE"),
        ({"chain_id": "wrong-chain"}, "RESERVATION_INCOMPLETE"),
        ({"prior_terminal_receipt_sha256": "a" * 64}, "RESERVATION_INCOMPLETE"),
        ({"stage_output_sha256": None}, "RESERVATION_INCOMPLETE"),
        ({"parent_authorization_digest": "a" * 64}, "RESERVATION_INCOMPLETE"),
        ({"admission_artifact_digest": "a" * 64}, "RESERVATION_INCOMPLETE"),
        ({"stage_binding_receipt_sha256": "a" * 64}, "RESERVATION_INCOMPLETE"),
        ({"call_terminal_sha256s": ("a" * 64,)}, "RESERVATION_INCOMPLETE"),
        (
            {"call_terminal_sha256s": ("a" * 64, "b" * 64), "calls_consumed": 2},
            "RESERVATION_INCOMPLETE",
        ),
        ({"calls_consumed": 2}, "RESERVATION_INCOMPLETE"),
        ({"status": "FAILED", "stage_output_sha256": None}, "TERMINAL_FAILED"),
        ({"status": "OUTCOME_UNKNOWN", "stage_output_sha256": None}, "OUTCOME_UNKNOWN"),
    ),
)
def test_completed_stage_reader_rejects_terminal_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    change: dict[str, object],
    reason: str,
) -> None:
    import insurance_harness.model_policy.g3_bounded_gateway as gateway

    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    plan, _terminal, _semantic, _policy, call_dir = _complete_successful_stage(root)
    stage_path = call_dir.parents[1] / "stage-terminals" / f"{plan.stage}.json"
    stage = G3StageTerminalReceiptV1.model_validate_json(stage_path.read_bytes())
    provisional = stage.model_copy(update={**change, "receipt_sha256": H})
    changed = provisional.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-stage-terminal-receipt.830.v1", provisional, "receipt_sha256"
            )
        }
    )
    stage_path.write_bytes(canonical_json(changed.model_dump(mode="json", round_trip=True)))
    stage_path.chmod(0o600)

    with pytest.raises(G3LedgerDenied) as denied:
        _read_successful_g3_stage_call(
            plan=plan,
            call=plan.request_manifest.calls[0],
            admission_artifact_digest="8" * 64,
        )
    assert denied.value.reason_code == reason


@pytest.mark.parametrize("wire_change", ("missing", "noncanonical", "bad-self-hash"))
def test_completed_stage_reader_requires_secure_canonical_terminal_wire(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, wire_change: str
) -> None:
    import insurance_harness.model_policy.g3_bounded_gateway as gateway

    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    plan, _terminal, _semantic, _policy, call_dir = _complete_successful_stage(root)
    stage_path = call_dir.parents[1] / "stage-terminals" / f"{plan.stage}.json"
    if wire_change == "missing":
        stage_path.unlink()
    elif wire_change == "noncanonical":
        stage_path.write_bytes(stage_path.read_bytes() + b"\n")
    else:
        stage = G3StageTerminalReceiptV1.model_validate_json(stage_path.read_bytes())
        raw = stage.model_dump(mode="json", round_trip=True)
        raw["receipt_sha256"] = "a" * 64
        stage_path.write_bytes(canonical_json(raw))
    with pytest.raises(G3LedgerDenied) as denied:
        _read_successful_g3_stage_call(
            plan=plan,
            call=plan.request_manifest.calls[0],
            admission_artifact_digest="8" * 64,
        )
    assert denied.value.reason_code == "RESERVATION_INCOMPLETE"


@pytest.mark.parametrize(
    "leaf_name",
    (
        "reservation.json",
        "prepared.json",
        "policy-receipt.json",
        "request-body.private.json",
        "started.json",
        "response-body.private.json",
        "semantic-content.private.json",
        "call-terminal.json",
    ),
)
def test_completed_stage_reader_rejects_missing_leaf_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, leaf_name: str
) -> None:
    import insurance_harness.model_policy.g3_bounded_gateway as gateway

    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    plan, _terminal, _semantic, _policy, call_dir = _complete_successful_stage(root)
    (call_dir / leaf_name).unlink()
    with pytest.raises(G3LedgerDenied) as denied:
        _read_successful_g3_stage_call(
            plan=plan,
            call=plan.request_manifest.calls[0],
            admission_artifact_digest="8" * 64,
        )
    assert denied.value.reason_code == "RESERVATION_INCOMPLETE"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("provider_usage", "expected_denial", "timeout_seconds", "response_delay"),
    (
        ({"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}, None, 30, 0.0),
        (
            {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
            "PROVIDER_USAGE_EXCEEDS_CAP",
            30,
            0.0,
        ),
        ({"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}, "TIMEOUT", 1, 1.1),
    ),
)
async def test_fixed_transport_posts_once_and_started_blocks_replay(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    provider_usage: dict[str, int],
    expected_denial: str | None,
    timeout_seconds: int,
    response_delay: float,
) -> None:
    import insurance_harness.model_policy.g3_bounded_gateway as gateway

    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    monkeypatch.setenv("G3_BOUNDED_MODEL_API_KEY", "test-only")
    plan = valid_c_plan()
    call = plan.request_manifest.calls[0]
    capability = reserve_g3_call(plan=plan, call=call, admission_artifact_digest="8" * 64)
    snapshot = _reservation_snapshot(capability)
    assert snapshot is not None
    call_dir = Path(str(snapshot[2]))
    reservation = snapshot[4]
    budget = snapshot[5]
    body = b'{"messages":[],"model":"fixture"}'
    body_hash = hashlib.sha256(body).hexdigest()
    prepared0 = G3PreparedReceiptV1(
        contract="g3-prepared-receipt.830.v1",
        chain_id=plan.chain_id,
        stage=plan.stage,
        call_id=call.call_id,
        ordinal=call.ordinal,
        admission_artifact_digest="8" * 64,
        verified_binding_digest="7" * 64,
        call_reservation_receipt_sha256=reservation.receipt_sha256,
        request_body_sha256=body_hash,
        request_bytes=len(body),
        input_token_estimate=1,
        input_token_ceiling=10,
        output_token_ceiling=20,
        timeout_seconds=timeout_seconds,
        reserved_chain_budget=budget,
        prepared_at=datetime.now(UTC),
        receipt_sha256=H,
    )
    prepared = prepared0.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-prepared-receipt.830.v1", prepared0, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        call_dir / "prepared.json",
        canonical_json(prepared.model_dump(mode="json", round_trip=True)),
    )
    view = ModelPermitView(
        identity=call.identity,
        purpose=plan.purpose,
        run_schema_version=plan.run_schema_version,
        space_id=plan.space_id,
        run_id=plan.run_id,
        run_revision=plan.run_revision,
        admission_hash="8" * 64,
        verified_binding_digest="7" * 64,
        template_hash=plan.template_lock.approved_template_hash,
        model_plan_hash=plan.model_plan_hash,
        policy_snapshot_digest="6" * 64,
        call_scope_hash="5" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    receipt = PolicyReceipt(
        decision="ALLOW",
        reason_code="policy_allowed",
        identity_key=call.identity.identity_key,
        purpose=plan.purpose,
        run_schema_version=plan.run_schema_version,
        space_id=plan.space_id,
        run_id=plan.run_id,
        run_revision=plan.run_revision,
        admission_hash="8" * 64,
        request_digest="4" * 64,
        binding_digest="3" * 64,
        verified_binding_digest="7" * 64,
        template_hash=plan.template_lock.approved_template_hash,
        model_plan_hash=plan.model_plan_hash,
        call_scope_hash="5" * 64,
        attempted_context_digest="2" * 64,
        policy_snapshot_digest="6" * 64,
        permit_digest=_model_permit_view_digest(view),
        permit_view=view,
        evaluated_at=datetime.now(UTC),
    )
    _write_exclusive(call_dir / "policy-receipt.json", receipt.model_dump_json().encode())
    route = G3BoundedRouteConfig(
        endpoint_origin=call.endpoint_origin,
        endpoint_path="/compatible-mode/v1/chat/completions",
        timeout_seconds=timeout_seconds,
        follow_redirects=False,
        call_directory=str(call_dir),
        request_body_sha256=body_hash,
        prepared_receipt_sha256=prepared.receipt_sha256,
        chain_manifest_hash=plan.chain_manifest_hash,
        stage=plan.stage,
        admission_artifact_digest="8" * 64,
        call_id=call.call_id,
        ordinal=call.ordinal,
        input_token_ceiling=10,
        output_token_ceiling=20,
    )
    transport_attempts: list[httpx.Request] = []

    async def fake_response(_request: httpx.Request) -> httpx.Response:
        transport_attempts.append(_request)
        if response_delay:
            await asyncio.sleep(response_delay)
        return httpx.Response(
            status_code=200,
            headers={"content-type": "application/json", "x-request-id": "fixture-request"},
            json={
                "choices": [
                    {"finish_reason": "stop", "message": {"content": '{"ok":true}'}}
                ],
                "usage": provider_usage,
            },
        )

    posted = respx.post(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    ).mock(side_effect=fake_response)
    request = ModelCallRequest(content=body, rendered_prompt=b"fixture")
    if expected_denial == "TIMEOUT":
        with pytest.raises(TimeoutError):
            await _fixed_openai_compatible_dispatch(
                canonical_json(route.model_dump(mode="json", round_trip=True)),
                call.identity,
                request,
            )
        terminal = _failed_call_terminal(
            plan=plan,
            call=call,
            admission_digest="8" * 64,
            verified_digest="7" * 64,
            call_dir=str(call_dir),
            reservation_capability=capability,
        )
        assert terminal is not None and terminal.status == "OUTCOME_UNKNOWN"
        assert str(call_dir) not in gateway._ACTIVE_SINKS
        with pytest.raises(G3LedgerDenied, match="G3 bounded ledger denied"):
            await _fixed_openai_compatible_dispatch(
                canonical_json(route.model_dump(mode="json", round_trip=True)),
                call.identity,
                request,
            )
        assert len(transport_attempts) == 1
        return
    if expected_denial is not None:
        with pytest.raises(G3LedgerDenied, match="G3 bounded ledger denied") as denied:
            await _fixed_openai_compatible_dispatch(
                canonical_json(route.model_dump(mode="json", round_trip=True)),
                call.identity,
                request,
            )
        assert denied.value.reason_code == expected_denial
        assert posted.call_count == 1
        with pytest.raises(G3LedgerDenied, match="G3 bounded ledger denied"):
            await _fixed_openai_compatible_dispatch(
                canonical_json(route.model_dump(mode="json", round_trip=True)),
                call.identity,
                request,
            )
        assert posted.call_count == 1
        return
    result = await _fixed_openai_compatible_dispatch(
        canonical_json(route.model_dump(mode="json", round_trip=True)),
        call.identity,
        request,
    )
    assert result == '{"ok":true}'
    terminal = _call_terminal(
        plan=plan,
        call=call,
        admission_digest="8" * 64,
        verified_digest="7" * 64,
        call_dir=str(call_dir),
        projection_sha256="2" * 64,
        reservation_capability=capability,
    )
    assert terminal.response_meta is not None and terminal.response_meta.http_status == 200
    assert terminal.provider_usage is not None and terminal.provider_usage.total_tokens == 5
    assert posted.call_count == 1
    with pytest.raises(G3LedgerDenied, match="G3 bounded ledger denied"):
        await _fixed_openai_compatible_dispatch(
            canonical_json(route.model_dump(mode="json", round_trip=True)),
            call.identity,
            request,
        )
    assert posted.call_count == 1


def test_failed_terminal_preserves_complete_response_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import insurance_harness.model_policy.g3_bounded_gateway as gateway

    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    plan = valid_c_plan()
    call = plan.request_manifest.calls[0]
    capability = reserve_g3_call(plan=plan, call=call, admission_artifact_digest="8" * 64)
    snapshot = _reservation_snapshot(capability)
    assert snapshot is not None
    call_dir = Path(str(snapshot[2]))
    reservation = snapshot[4]
    prepared0 = G3PreparedReceiptV1(
        contract="g3-prepared-receipt.830.v1",
        chain_id=plan.chain_id,
        stage=plan.stage,
        call_id=call.call_id,
        ordinal=call.ordinal,
        admission_artifact_digest="8" * 64,
        verified_binding_digest="7" * 64,
        call_reservation_receipt_sha256=reservation.receipt_sha256,
        request_body_sha256=call.request_body_sha256,
        request_bytes=call.request_bytes,
        input_token_estimate=call.input_token_estimate,
        input_token_ceiling=call.input_token_ceiling,
        output_token_ceiling=call.output_token_ceiling,
        timeout_seconds=call.timeout_seconds,
        reserved_chain_budget=snapshot[5],
        prepared_at=datetime.now(UTC),
        receipt_sha256=H,
    )
    prepared = prepared0.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-prepared-receipt.830.v1", prepared0, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        call_dir / "prepared.json",
        canonical_json(prepared.model_dump(mode="json", round_trip=True)),
    )
    started0 = G3StartedReceiptV1(
        contract="g3-started-receipt.830.v1",
        prepared_receipt_sha256=prepared.receipt_sha256,
        started_at=datetime.now(UTC),
        monotonic_start_ns=1,
        call_consumed=True,
        receipt_sha256=H,
    )
    started = started0.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-started-receipt.830.v1", started0, "receipt_sha256"
            )
        }
    )
    _write_exclusive(
        call_dir / "started.json",
        canonical_json(started.model_dump(mode="json", round_trip=True)),
    )
    view = ModelPermitView(
        identity=call.identity,
        purpose=plan.purpose,
        run_schema_version=plan.run_schema_version,
        space_id=plan.space_id,
        run_id=plan.run_id,
        run_revision=plan.run_revision,
        admission_hash="8" * 64,
        verified_binding_digest="7" * 64,
        template_hash=plan.template_lock.approved_template_hash,
        model_plan_hash=plan.model_plan_hash,
        policy_snapshot_digest="6" * 64,
        call_scope_hash="5" * 64,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    receipt = PolicyReceipt(
        decision="ALLOW",
        reason_code="policy_allowed",
        identity_key=call.identity.identity_key,
        purpose=plan.purpose,
        run_schema_version=plan.run_schema_version,
        space_id=plan.space_id,
        run_id=plan.run_id,
        run_revision=plan.run_revision,
        admission_hash="8" * 64,
        request_digest="4" * 64,
        binding_digest="3" * 64,
        verified_binding_digest="7" * 64,
        template_hash=plan.template_lock.approved_template_hash,
        model_plan_hash=plan.model_plan_hash,
        call_scope_hash="5" * 64,
        attempted_context_digest="2" * 64,
        policy_snapshot_digest="6" * 64,
        permit_digest=_model_permit_view_digest(view),
        permit_view=view,
        evaluated_at=datetime.now(UTC),
    )
    policy_bytes = receipt.model_dump_json().encode()
    _write_exclusive(call_dir / "policy-receipt.json", policy_bytes)
    response_bytes = b'{"error":{"message":"invalid fixture"}}'
    _write_exclusive(call_dir / "response-body.private.json", response_bytes)
    response_meta = G3ProviderResponseMetaV1(
        http_status=422,
        content_type="application/json",
        provider_request_id="failed-request",
        canonical_headers_sha256="4" * 64,
    )
    gateway._RESPONSE_AUDIT[str(call_dir)] = (response_meta, None)

    terminal = _failed_call_terminal(
        plan=plan,
        call=call,
        admission_digest="8" * 64,
        verified_digest="7" * 64,
        call_dir=str(call_dir),
        reservation_capability=capability,
    )

    assert terminal is not None
    assert terminal.status == "FAILED"
    assert terminal.response_meta == response_meta
    assert terminal.response_body_sha256 == hashlib.sha256(response_bytes).hexdigest()
    assert terminal.response_bytes == len(response_bytes)
    assert terminal.provider_usage is None
    assert terminal.call_reservation_receipt_sha256 == reservation.receipt_sha256
    with pytest.raises(G3LedgerDenied, match="G3 bounded ledger denied") as failed:
        _reopen_completed_g3_call(
            plan=plan,
            call=call,
            admission_artifact_digest="8" * 64,
        )
    assert failed.value.reason_code == "TERMINAL_FAILED"
