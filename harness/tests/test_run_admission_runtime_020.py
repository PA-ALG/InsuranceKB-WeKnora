"""OpenSpec 020 D1.3b/D1.5: admitted model runtime contracts."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset.admission import (
    ProductionAdmissionEvaluator,
    RunAdmissionDocument,
)
from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    ProductReserve,
    ProviderSpendCapAttestation,
    RequestPoolReserve,
    RequestReserve,
    RoleRate,
    SendPermit,
    budget_account_identity,
    budget_contract_hash,
    model_role_budget_identity_hash,
)
from insurance_harness.goldenset.admission_identity import (
    IdentityInspectionBlocker,
    IdentityInspectionRequest,
    IdentityInspectionResult,
    identity_contract_hash,
)
from insurance_harness.goldenset.admission_models import (
    AdmissionDerivedState,
    BudgetApprovalEntry,
    BudgetApprovalEnvelope,
    BudgetApprovalPayload,
    ModelRolePlan,
    ProvenanceApprovalEnvelope,
    ProvenanceApprovalPayload,
    RunAdmissionPlan,
    RunAdmissionPlanPayload,
    approval_signed_bytes,
    plan_payload_hash,
)
from insurance_harness.goldenset.admission_probe import ProbeRequest, ProbeResult
from insurance_harness.goldenset.admission_runtime import (
    AdmissionBlockedError,
    AdmissionPausedError,
    AdmissionRuntimeGuard,
    AdmittedModelClient,
    ApprovedModelResponse,
    ProductAdmission,
    request_unit_fingerprint,
)

_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=UTC)
_SYSTEM = "Extract only supported policy facts."
_USER = "Extract product-01 page-001."
_STAGE = "extraction"
_ROLE: Final[Literal["weak_extractor"]] = "weak_extractor"
_PRODUCTS = ("product-01", "product-02")
_REQUEST_MAXIMUM = BudgetAmounts(
    input_tokens=700,
    output_tokens=300,
    cost_minor_units=80,
)
_PRODUCT_MAXIMUM = BudgetAmounts(
    input_tokens=1_000,
    output_tokens=500,
    cost_minor_units=100,
)


class _MutableIdentityInspector:
    def __init__(self) -> None:
        self.calls = 0
        self.blocked = False

    def inspect(self, _request: IdentityInspectionRequest) -> IdentityInspectionResult:
        self.calls += 1
        blockers = (
            (
                IdentityInspectionBlocker(
                    code="digest_mismatch",
                    message="test-controlled input drift",
                    product_id="product-02",
                ),
            )
            if self.blocked
            else ()
        )
        return IdentityInspectionResult(
            evaluated_revision="f" * 40,
            product_digests={},
            shared_input_digest="a" * 64,
            execution_surface_digest="b" * 64,
            blockers=blockers,
        )


class _PassingProbe:
    def run(self, request: ProbeRequest) -> ProbeResult:
        return ProbeResult(
            role=request.role,
            verified=True,
            provider=request.role_plan.provider,
            model_id=request.role_plan.model_id,
            endpoint_origin="https://dashscope.aliyuncs.com",
            status_class="success",
            latency_ms=1,
            observed_at=_NOW,
            observed_revision=request.role_plan.expected_model_revision,
            observed_deployment_id=request.role_plan.model_id,
        )


class _CountingInvoker:
    def __init__(self, *, response: str = "durable answer") -> None:
        self.calls = 0
        self.response = response
        self.role_plans: list[ModelRolePlan] = []
        self.maximums: list[BudgetAmounts] = []

    def _record(
        self,
        role_plan: ModelRolePlan,
        maximum: BudgetAmounts,
        system: str,
        user: str,
    ) -> None:
        assert (system, user) == (_SYSTEM, _USER)
        assert role_plan.model_id == "weak_extractor-deployment"
        assert maximum.output_tokens == _REQUEST_MAXIMUM.output_tokens
        self.calls += 1
        self.role_plans.append(role_plan)
        self.maximums.append(maximum)

    async def complete(
        self,
        role_plan: ModelRolePlan,
        maximum: BudgetAmounts,
        system: str,
        user: str,
    ) -> ApprovedModelResponse:
        self._record(role_plan, maximum, system, user)
        return ApprovedModelResponse(
            content=self.response,
            input_tokens=0,
            output_tokens=0,
            usage_verified=False,
        )


class _BlockingInvoker(_CountingInvoker):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def complete(
        self,
        role_plan: ModelRolePlan,
        maximum: BudgetAmounts,
        system: str,
        user: str,
    ) -> ApprovedModelResponse:
        self._record(role_plan, maximum, system, user)
        self.started.set()
        await self.release.wait()
        return ApprovedModelResponse(
            content=self.response,
            input_tokens=0,
            output_tokens=0,
            usage_verified=False,
        )


class _FailingInvoker(_CountingInvoker):
    async def complete(
        self,
        role_plan: ModelRolePlan,
        maximum: BudgetAmounts,
        system: str,
        user: str,
    ) -> ApprovedModelResponse:
        self._record(role_plan, maximum, system, user)
        raise RuntimeError("provider outcome is ambiguous")


class _OrderingLedger(BudgetLedger):
    def __init__(self, path: Path, *, response_root: Path) -> None:
        super().__init__(path)
        self.response_root = response_root
        self.terminal_observed_after_durable_response = False

    def record_terminal(
        self,
        permit: SendPermit,
        *,
        actual: BudgetAmounts,
        response_digest: str,
        usage_verified: bool,
        force_overage: bool = False,
    ) -> None:
        attempt = self.attempt_snapshot(permit.key)
        assert attempt.state == "sent"
        durable_files = tuple(path for path in self.response_root.rglob("*") if path.is_file())
        assert durable_files
        assert any(
            hashlib.sha256(path.read_bytes()).hexdigest() == response_digest
            or b"durable answer" in path.read_bytes()
            for path in durable_files
        )
        self.terminal_observed_after_durable_response = True
        super().record_terminal(
            permit,
            actual=actual,
            response_digest=response_digest,
            usage_verified=usage_verified,
            force_overage=force_overage,
        )


def _roles() -> dict[str, ModelRolePlan]:
    return {
        role: ModelRolePlan(
            provider="bailian",
            model_id=f"{role}-deployment",
            expected_model_revision="2026-07-20T08:00:00Z",
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        )
        for role in ("annotator", "weak_extractor", "judge")
    }


def _identity_request() -> IdentityInspectionRequest:
    return IdentityInspectionRequest(
        required_dependency_revisions={},
        source_products_root="dataset/shouxian_product",
        golden_products_root="dataset/goldenset/wip-gs-v0.1",
        products=(),
        shared_input_digests={},
        execution_surface_digests={},
        historical_product_ids=(),
        historical_provenance=(),
    )


def _budget_contract(
    roles: dict[str, ModelRolePlan],
    *,
    use_request_pool: bool = False,
    weak_input_rate: int = 10,
    weak_output_rate: int = 20,
) -> BudgetContract:
    request_unit = request_unit_fingerprint(
        role=_ROLE,
        role_plan=roles[_ROLE],
        system=_SYSTEM,
        user=_USER,
    )
    return BudgetContract(
        currency="CNY",
        price_snapshot_id="runtime-test-price-snapshot",
        price_observed_at=_NOW - timedelta(minutes=1),
        price_expires_at=_NOW + timedelta(hours=1),
        ceiling=BudgetAmounts(
            input_tokens=10_000,
            output_tokens=5_000,
            cost_minor_units=1_000,
        ),
        role_rates={
            role: RoleRate(
                model_role_identity_hash=model_role_budget_identity_hash(role_plan),
                input_cost_per_million_minor_units=(weak_input_rate if role == _ROLE else 10),
                output_cost_per_million_minor_units=(weak_output_rate if role == _ROLE else 20),
            )
            for role, role_plan in roles.items()
        },
        provider_attestation=ProviderSpendCapAttestation(
            provider="bailian",
            project_ref="sha256:" + "c" * 64,
            credential_ref="sha256:" + "d" * 64,
            max_cost_minor_units=900,
            observed_at=_NOW - timedelta(minutes=1),
            expires_at=_NOW + timedelta(hours=1),
            evidence_digest="e" * 64,
        ),
        product_reserves=tuple(
            ProductReserve(
                stage=_STAGE,
                product_id=product_id,
                maximum=_PRODUCT_MAXIMUM,
                request_reserves=(
                    ()
                    if use_request_pool
                    else (
                        RequestReserve(
                            request_unit=request_unit,
                            role=_ROLE,
                            maximum=_REQUEST_MAXIMUM,
                        ),
                    )
                ),
                request_pools=(
                    (
                        RequestPoolReserve(
                            role=_ROLE,
                            max_attempts=1,
                            per_attempt_maximum=_REQUEST_MAXIMUM,
                        ),
                    )
                    if use_request_pool
                    else ()
                ),
            )
            for product_id in _PRODUCTS
        ),
    )


def _signed_document(
    provenance_key: Ed25519PrivateKey,
    budget_key: Ed25519PrivateKey,
    *,
    stored_ready: bool = False,
    use_request_pool: bool = False,
    weak_input_rate: int = 10,
    weak_output_rate: int = 20,
) -> RunAdmissionDocument:
    roles = _roles()
    contract = _budget_contract(
        roles,
        use_request_pool=use_request_pool,
        weak_input_rate=weak_input_rate,
        weak_output_rate=weak_output_rate,
    )
    identity_request = _identity_request()
    payload = RunAdmissionPlanPayload(
        run_identity="gs-v0.1-runtime-test",
        purpose="gs-v0.1-baseline",
        model_roles=roles,
        identity_contract_hash=identity_contract_hash(identity_request),
        budget_contract_hash=budget_contract_hash(contract),
    )
    payload_hash = plan_payload_hash(payload)
    provenance_payload = ProvenanceApprovalPayload(
        plan_payload_hash=payload_hash,
        run_identity=payload.run_identity,
        purpose=payload.purpose,
        scope="provenance:wip-gs-v0.1",
        approver_identity="golden-owner@example.com",
        approver_role="provenance_approver",
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(hours=1),
        product_entries=(),
    )
    ceiling = contract.ceiling
    budget_payload = BudgetApprovalPayload(
        plan_payload_hash=payload_hash,
        run_identity=payload.run_identity,
        purpose=payload.purpose,
        scope="budget:gs-v0.1",
        approver_identity="finance-owner@example.com",
        approver_role="budget_approver",
        issued_at=_NOW - timedelta(minutes=1),
        expires_at=_NOW + timedelta(hours=1),
        budget_entries=(
            BudgetApprovalEntry(
                currency=contract.currency,
                max_input_tokens=ceiling.input_tokens,
                max_output_tokens=ceiling.output_tokens,
                max_cost_minor_units=ceiling.cost_minor_units,
                budget_contract_hash=budget_contract_hash(contract),
            ),
        ),
    )
    provenance_envelope = ProvenanceApprovalEnvelope(
        domain="provenance",
        key_id="provenance-key",
        payload=provenance_payload,
        signature=base64.b64encode(
            provenance_key.sign(approval_signed_bytes("provenance", provenance_payload))
        ).decode("ascii"),
    )
    budget_envelope = BudgetApprovalEnvelope(
        domain="budget",
        key_id="budget-key",
        payload=budget_payload,
        signature=base64.b64encode(
            budget_key.sign(approval_signed_bytes("budget", budget_payload))
        ).decode("ascii"),
    )
    return RunAdmissionDocument(
        plan=RunAdmissionPlan(
            payload=payload,
            approval_envelopes=(provenance_envelope, budget_envelope),
            derived_state=(AdmissionDerivedState(state="READY") if stored_ready else None),
        ),
        identity_request=identity_request,
        budget_contract=contract,
    )


def _runtime(
    tmp_path: Path,
    *,
    inspector: _MutableIdentityInspector | None = None,
    invoker: _CountingInvoker | None = None,
    stored_ready: bool = False,
    ordering_ledger: bool = False,
    use_request_pool: bool = False,
    weak_input_rate: int = 10,
    weak_output_rate: int = 20,
) -> tuple[
    AdmissionRuntimeGuard,
    _MutableIdentityInspector,
    BudgetLedger,
    Path,
    RunAdmissionDocument,
    ProductionAdmissionEvaluator,
]:
    active_inspector = inspector or _MutableIdentityInspector()
    active_invoker = invoker or _CountingInvoker()
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    document = _signed_document(
        provenance_key,
        budget_key,
        stored_ready=stored_ready,
        use_request_pool=use_request_pool,
        weak_input_rate=weak_input_rate,
        weak_output_rate=weak_output_rate,
    )
    evaluator = ProductionAdmissionEvaluator._for_testing(
        identity_inspector=active_inspector,
        provider_probe=_PassingProbe(),
        trusted_public_keys={
            "provenance-key": provenance_key.public_key(),
            "budget-key": budget_key.public_key(),
        },
        probe=True,
        clock=lambda: _NOW,
        runtime_capability_ready=True,
    )
    response_root = tmp_path / "checkpoint" / "responses"
    ledger: BudgetLedger
    if ordering_ledger:
        ledger = _OrderingLedger(
            tmp_path / "budget.sqlite3",
            response_root=response_root,
        )
    else:
        ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    guard = AdmissionRuntimeGuard._for_testing(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=response_root,
        model_invoker=active_invoker,
        enforce_execution_authorization=False,
    )
    return guard, active_inspector, ledger, response_root, document, evaluator


def _client(
    guard: AdmissionRuntimeGuard,
    *,
    product_id: str = "product-01",
) -> AdmittedModelClient:
    product = guard.begin_product(stage=_STAGE, product_id=product_id)
    return product.client(role=_ROLE)


async def test_d1_5_each_product_reruns_evaluator_and_ignores_stored_ready(
    tmp_path: Path,
) -> None:
    guard, inspector, _, _, _, _ = _runtime(tmp_path, stored_ready=True)

    guard.begin_product(stage=_STAGE, product_id="product-01")
    guard.begin_product(stage=_STAGE, product_id="product-02")

    assert inspector.calls == 2


async def test_d1_5_blocked_drift_calls_inner_model_zero_times(
    tmp_path: Path,
) -> None:
    inspector = _MutableIdentityInspector()
    inspector.blocked = True
    invoker = _CountingInvoker()
    guard, _, _, _, _, _ = _runtime(
        tmp_path,
        inspector=inspector,
        invoker=invoker,
        stored_ready=True,
    )

    with pytest.raises(AdmissionBlockedError, match="BLOCKED"):
        _client(guard)

    assert inspector.calls == 1
    assert invoker.calls == 0


async def test_d1_3b_two_workers_make_exactly_one_inner_model_call(
    tmp_path: Path,
) -> None:
    invoker = _BlockingInvoker()
    guard, _, _, _, _, _ = _runtime(tmp_path, invoker=invoker)
    client = _client(guard)
    winner = asyncio.create_task(client.complete(_SYSTEM, _USER))
    await invoker.started.wait()

    with pytest.raises(
        AdmissionPausedError,
        match="request_attempt_not_terminal|non-terminal|in progress",
    ):
        await asyncio.wait_for(client.complete(_SYSTEM, _USER), timeout=1)

    assert invoker.calls == 1
    invoker.release.set()
    assert await winner == "durable answer"
    assert invoker.calls == 1


async def test_d1_3b_terminal_response_is_durable_before_attempt_settlement(
    tmp_path: Path,
) -> None:
    invoker = _CountingInvoker()
    guard, _, ledger, response_root, document, _ = _runtime(
        tmp_path,
        invoker=invoker,
        ordering_ledger=True,
    )

    assert await _client(guard).complete(_SYSTEM, _USER) == "durable answer"

    assert isinstance(ledger, _OrderingLedger)
    assert ledger.terminal_observed_after_durable_response
    assert any(path.is_file() for path in response_root.rglob("*"))
    assert invoker.role_plans == [document.plan.payload.model_roles[_ROLE]]
    assert invoker.maximums == [_REQUEST_MAXIMUM]


async def test_d1_3b_exception_or_ambiguous_crash_recovers_uncertain(
    tmp_path: Path,
) -> None:
    invoker = _FailingInvoker()
    guard, _, ledger, _, document, _ = _runtime(tmp_path, invoker=invoker)
    client = _client(guard)

    with pytest.raises(AdmissionPausedError, match="uncertain|ambiguous"):
        await client.complete(_SYSTEM, _USER)

    account_id = budget_account_identity(
        document.plan.payload.run_identity,
        document.plan.payload.purpose,
    )
    snapshot = ledger.account_snapshot(account_id)
    assert snapshot.uncertain == _REQUEST_MAXIMUM
    assert snapshot.attempt_count == 1
    assert invoker.calls == 1
    with pytest.raises(AdmissionPausedError):
        await client.complete(_SYSTEM, _USER)
    assert invoker.calls == 1


async def test_d1_3b_terminal_response_is_reused_and_digest_verified(
    tmp_path: Path,
) -> None:
    invoker = _CountingInvoker()
    guard, _, _, response_root, _, _ = _runtime(tmp_path, invoker=invoker)
    client = _client(guard)

    assert await client.complete(_SYSTEM, _USER) == "durable answer"
    assert await client.complete(_SYSTEM, _USER) == "durable answer"
    assert invoker.calls == 1

    response_files = tuple(
        path
        for path in response_root.rglob("*")
        if path.is_file() and b"durable answer" in path.read_bytes()
    )
    assert len(response_files) == 1
    response_files[0].write_bytes(b"tampered response")
    with pytest.raises(AdmissionPausedError, match="digest|response"):
        await client.complete(_SYSTEM, _USER)
    assert invoker.calls == 1


async def test_d1_5_dynamic_prompt_claims_signed_role_request_pool(
    tmp_path: Path,
) -> None:
    invoker = _CountingInvoker()
    guard, _, _, _, _, _ = _runtime(
        tmp_path,
        invoker=invoker,
        use_request_pool=True,
    )

    assert await _client(guard).complete(_SYSTEM, _USER) == "durable answer"
    assert invoker.calls == 1


def test_d1_3b_request_unit_fingerprint_binds_full_approved_model_identity() -> None:
    approved = _roles()[_ROLE]
    substituted = approved.model_copy(update={"model_id": "substituted-deployment"})

    approved_fingerprint = request_unit_fingerprint(
        role=_ROLE,
        role_plan=approved,
        system=_SYSTEM,
        user=_USER,
    )
    substituted_fingerprint = request_unit_fingerprint(
        role=_ROLE,
        role_plan=substituted,
        system=_SYSTEM,
        user=_USER,
    )

    assert approved_fingerprint != substituted_fingerprint


async def test_d1_3b_new_guard_explicit_startup_recovery_marks_sent_uncertain(
    tmp_path: Path,
) -> None:
    guard, _, ledger, response_root, document, evaluator = _runtime(tmp_path)
    guard.begin_product(stage=_STAGE, product_id="product-01")
    role_plan = document.plan.payload.model_roles[_ROLE]
    assert isinstance(role_plan, ModelRolePlan)
    request_unit = request_unit_fingerprint(
        role=_ROLE,
        role_plan=role_plan,
        system=_SYSTEM,
        user=_USER,
    )
    account_id = budget_account_identity(
        document.plan.payload.run_identity,
        document.plan.payload.purpose,
    )
    permit = ledger.claim_attempt(
        account_id,
        _STAGE,
        "product-01",
        request_unit,
        1,
        "crashed-owner",
        _REQUEST_MAXIMUM,
    )
    assert permit is not None
    ledger.mark_sent(permit)

    replacement_invoker = _CountingInvoker()
    replacement = AdmissionRuntimeGuard._for_testing(
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        response_root=response_root,
        model_invoker=replacement_invoker,
    )
    assert replacement.recover_incomplete_at_startup() == 1

    recovered = ledger.account_snapshot(account_id)
    assert recovered.uncertain == _REQUEST_MAXIMUM
    with pytest.raises(AdmissionPausedError):
        await _client(replacement).complete(_SYSTEM, _USER)
    assert replacement_invoker.calls == 0


async def test_d1_3b_asyncio_cancellation_marks_attempt_uncertain_and_propagates(
    tmp_path: Path,
) -> None:
    invoker = _BlockingInvoker()
    guard, _, ledger, _, document, _ = _runtime(tmp_path, invoker=invoker)
    client = _client(guard)
    task = asyncio.create_task(client.complete(_SYSTEM, _USER))
    await invoker.started.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    account_id = budget_account_identity(
        document.plan.payload.run_identity,
        document.plan.payload.purpose,
    )
    snapshot = ledger.account_snapshot(account_id)
    assert snapshot.uncertain == _REQUEST_MAXIMUM
    assert invoker.calls == 1
    with pytest.raises(AdmissionPausedError):
        await client.complete(_SYSTEM, _USER)
    assert invoker.calls == 1


def test_d1_5_no_force_or_raw_model_injection_bypass_exists(tmp_path: Path) -> None:
    guard, _, ledger, response_root, document, evaluator = _runtime(tmp_path)
    product = guard.begin_product(stage=_STAGE, product_id="product-01")
    forbidden = {"force", "skip_admission", "ready", "inner", "model_invoker"}
    public_calls = (
        AdmissionRuntimeGuard,
        AdmissionRuntimeGuard.begin_product,
        ProductAdmission,
        type(product).client,
        AdmittedModelClient,
        AdmittedModelClient.complete,
    )

    for public_call in public_calls:
        assert forbidden.isdisjoint(inspect.signature(public_call).parameters)

    with pytest.raises(TypeError):
        inspect.signature(AdmissionRuntimeGuard).bind(
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            response_root=response_root,
            model_invoker=_CountingInvoker(),
        )
    with pytest.raises(TypeError):
        inspect.signature(product.client).bind(
            role=_ROLE,
            inner=_CountingInvoker(),
        )
    with pytest.raises(TypeError):
        inspect.signature(ProductAdmission).bind(
            account=ledger.account_snapshot(
                budget_account_identity(
                    document.plan.payload.run_identity,
                    document.plan.payload.purpose,
                )
            ),
            reserve=document.budget_contract.product_reserves[0]
            if document.budget_contract is not None
            else None,
            ledger=ledger,
            response_root=response_root,
            model_roles=document.plan.payload.model_roles,
            model_invoker=_CountingInvoker(),
        )
