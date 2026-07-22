"""OpenSpec 020 D1.5: fresh process-only canary authorization."""

from __future__ import annotations

import base64
import inspect
import sqlite3
from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.goldenset.admission import (
    ArtifactEvidenceInspectionError,
    ExecutionAuthorizationValidationError,
    ExecutionTarget,
    InitialExecutionAuthorization,
    ProductionAdmissionEvaluator,
    ReviewedExecutionAuthorization,
    RunAdmissionDocument,
    RuntimeAdmissionDecision,
    canary_review_capability_digest,
    execution_plan_hash,
)
from insurance_harness.goldenset.admission_budget import (
    BudgetAmounts,
    BudgetContract,
    BudgetLedger,
    ProductReserve,
    ProviderSpendCapAttestation,
    RequestReserve,
    RoleRate,
    budget_account_identity,
    budget_contract_hash,
    model_role_budget_identity_hash,
    role_rate_cost,
    role_rate_digest,
)
from insurance_harness.goldenset.admission_identity import (
    IdentityInspectionRequest,
    IdentityInspectionResult,
    identity_contract_hash,
)
from insurance_harness.goldenset.admission_models import (
    AdmissionDerivedState,
    BudgetApprovalEntry,
    BudgetApprovalEnvelope,
    BudgetApprovalPayload,
    CanaryReviewApprovalEnvelope,
    CanaryReviewApprovalPayload,
    CanaryReviewArtifactEvidence,
    ModelRolePlan,
    ProductInputPlan,
    ProvenanceApprovalEnvelope,
    ProvenanceApprovalPayload,
    RunAdmissionPlan,
    RunAdmissionPlanPayload,
    approval_signed_bytes,
    plan_payload_hash,
)
from insurance_harness.goldenset.admission_probe import ProbeRequest, ProbeResult

_NOW = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
_REVISION = "f" * 40
_FIRST = "平安爱满分（2026）两全保险"
_SECOND = "平安附加（2026）意外伤害保险"
_CANARY_TARGET = ExecutionTarget(stage="annotation", product_id=_FIRST)
_SECOND_TARGET = ExecutionTarget(stage="annotation", product_id=_SECOND)
_REQUEST_MAX = BudgetAmounts(
    input_tokens=1_000,
    output_tokens=500,
    cost_minor_units=20,
)
_PRODUCT_MAX = BudgetAmounts(
    input_tokens=2_000,
    output_tokens=1_000,
    cost_minor_units=40,
)


class _PassingIdentityInspector:
    def inspect(self, _request: IdentityInspectionRequest) -> IdentityInspectionResult:
        return IdentityInspectionResult(
            evaluated_revision=_REVISION,
            product_digests={_FIRST: "1" * 64, _SECOND: "2" * 64},
            shared_input_digest="3" * 64,
            execution_surface_digest="4" * 64,
            blockers=(),
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


class _ReviewSource:
    def __init__(self) -> None:
        self.envelope: CanaryReviewApprovalEnvelope | None = None
        self.error: Exception | None = None

    def __call__(self) -> CanaryReviewApprovalEnvelope | None:
        if self.error is not None:
            raise self.error
        return self.envelope


class _ArtifactInspector:
    def __init__(self, evidence: CanaryReviewArtifactEvidence) -> None:
        self.evidence = evidence
        self.error: Exception | None = None
        self.calls = 0
        self.on_inspect: Callable[[], None] | None = None

    def inspect(
        self,
        *,
        execution_plan_hash: str,
        canary_target: ExecutionTarget,
    ) -> CanaryReviewArtifactEvidence:
        assert len(execution_plan_hash) == 64
        assert canary_target == _CANARY_TARGET
        self.calls += 1
        if self.on_inspect is not None:
            self.on_inspect()
        if self.error is not None:
            raise self.error
        return self.evidence


class _MutableClock:
    def __init__(self, current: datetime = _NOW) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def _roles() -> dict[str, ModelRolePlan]:
    return {
        role: ModelRolePlan(
            provider="bailian",
            model_id=f"{role}-deployment",
            expected_model_revision="2026-07-20T09:00:00Z",
            protocol="https",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            provider_policy="bailian-deployment-detail-v1",
            credential_env_name="HARNESS_DASHSCOPE_API_KEY",
        )
        for role in ("annotator", "weak_extractor", "judge")
    }


def _identity_request(*, include_first: bool = True) -> IdentityInspectionRequest:
    product_ids = (_FIRST, _SECOND) if include_first else (_SECOND,)
    products = tuple(
        ProductInputPlan(
            product_id=product_id,
            line_key="endowment" if product_id == _FIRST else "accident",
            pdf_digests={"source.pdf": "5" * 64},
            product_meta_digest="6" * 64,
            fields_digest="7" * 64,
            consumed_input_digests={},
        )
        for product_id in product_ids
    )
    return IdentityInspectionRequest(
        required_dependency_revisions={},
        source_products_root="dataset/shouxian_product",
        golden_products_root="dataset/goldenset/wip-gs-v0.1",
        products=products,
        shared_input_digests={},
        execution_surface_digests={},
        historical_product_ids=(),
        historical_provenance=(),
    )


def _contract(roles: dict[str, ModelRolePlan]) -> BudgetContract:
    return BudgetContract(
        currency="CNY",
        price_snapshot_id="canary-price-v1",
        price_observed_at=_NOW - timedelta(minutes=1),
        price_expires_at=_NOW + timedelta(hours=1),
        ceiling=BudgetAmounts(
            input_tokens=10_000,
            output_tokens=5_000,
            cost_minor_units=200,
        ),
        role_rates={
            role: RoleRate(
                model_role_identity_hash=model_role_budget_identity_hash(role_plan),
                input_cost_per_million_minor_units=10,
                output_cost_per_million_minor_units=20,
            )
            for role, role_plan in roles.items()
        },
        provider_attestation=ProviderSpendCapAttestation(
            provider="bailian",
            workspace_ref="goldenset-production",
            project_ref="sha256:" + "8" * 64,
            credential_ref="sha256:" + "9" * 64,
            max_cost_minor_units=200,
            observed_at=_NOW - timedelta(minutes=1),
            expires_at=_NOW + timedelta(hours=1),
            evidence_digest="a" * 64,
        ),
        product_reserves=tuple(
            ProductReserve(
                stage="annotation",
                product_id=product_id,
                maximum=_PRODUCT_MAX,
                request_reserves=(
                    RequestReserve(
                        request_unit=f"{index}" * 64,
                        role="annotator",
                        maximum=_REQUEST_MAX,
                    ),
                ),
            )
            for index, product_id in (("b", _FIRST), ("c", _SECOND))
        ),
    )


def _document(
    provenance_key: Ed25519PrivateKey,
    budget_key: Ed25519PrivateKey,
    *,
    include_first: bool = True,
) -> RunAdmissionDocument:
    roles = _roles()
    identity = _identity_request(include_first=include_first)
    contract = _contract(roles)
    payload = RunAdmissionPlanPayload(
        run_identity="gs-v0.1-run-001",
        purpose="gs-v0.1-baseline",
        model_roles=roles,
        identity_contract_hash=identity_contract_hash(identity),
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
    provenance = ProvenanceApprovalEnvelope(
        domain="provenance",
        key_id="provenance-key",
        payload=provenance_payload,
        signature=base64.b64encode(
            provenance_key.sign(approval_signed_bytes("provenance", provenance_payload))
        ).decode("ascii"),
    )
    budget = BudgetApprovalEnvelope(
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
            approval_envelopes=(provenance, budget),
        ),
        identity_request=identity,
        budget_contract=contract,
    )


def _artifacts() -> CanaryReviewArtifactEvidence:
    return CanaryReviewArtifactEvidence(
        checkpoint_digest="d" * 64,
        manifest_digest="e" * 64,
        golden_digest="f" * 64,
        quote_verification_digest="0" * 64,
        disputed_quality_digest="1" * 64,
        disputed_count=1,
        record_count=100,
        quality_threshold_version="golden-v0.1-thresholds-v1",
    )


def _evaluator(
    provenance_key: Ed25519PrivateKey,
    budget_key: Ed25519PrivateKey,
    review_key: Ed25519PrivateKey,
    source: _ReviewSource,
    artifacts: _ArtifactInspector,
    *,
    now: datetime = _NOW,
    clock: Callable[[], datetime] | None = None,
) -> ProductionAdmissionEvaluator:
    return ProductionAdmissionEvaluator._for_testing(
        identity_inspector=_PassingIdentityInspector(),
        provider_probe=_PassingProbe(),
        trusted_public_keys={
            "provenance-key": provenance_key.public_key(),
            "budget-key": budget_key.public_key(),
            "review-key": review_key.public_key(),
        },
        probe=True,
        clock=clock or (lambda: now),
        runtime_capability_ready=True,
        canary_review_source=source,
        artifact_evidence_inspector=artifacts,
        allowed_canary_review_roles=frozenset({"canary_review_approver"}),
    )


def _settle_canary(
    evaluator: ProductionAdmissionEvaluator,
    document: RunAdmissionDocument,
    ledger: BudgetLedger,
) -> None:
    initial = evaluator.evaluate_execution(document, ledger)
    assert initial.authorization is not None
    account_id = budget_account_identity(
        document.plan.payload.run_identity,
        document.plan.payload.purpose,
    )
    ledger.reserve_product(account_id, "annotation", _FIRST, _PRODUCT_MAX)
    permit = ledger.claim_attempt(
        account_id,
        "annotation",
        _FIRST,
        "b" * 64,
        1,
        "canary-owner",
        _REQUEST_MAX,
    )
    assert permit is not None
    rate = document.budget_contract.role_rates["annotator"]  # type: ignore[union-attr]
    actual = BudgetAmounts(
        input_tokens=100,
        output_tokens=50,
        cost_minor_units=role_rate_cost(rate, input_tokens=100, output_tokens=50),
    )
    ledger.record_terminal(
        permit,
        actual=actual,
        response_digest="2" * 64,
        usage_verified=True,
    )
    ledger.settle_product(account_id, "annotation", _FIRST)


def _review_payload(
    document: RunAdmissionDocument,
    ledger: BudgetLedger,
    initial: RuntimeAdmissionDecision,
    **overrides: object,
) -> CanaryReviewApprovalPayload:
    account_id = budget_account_identity(
        document.plan.payload.run_identity,
        document.plan.payload.purpose,
    )
    account = ledger.account_snapshot(account_id)
    settlement = ledger.product_settlement_snapshot(account_id, "annotation", _FIRST)
    usage = settlement.reservation_actual
    assert document.budget_contract is not None
    values: dict[str, object] = {
        "plan_payload_hash": plan_payload_hash(document.plan),
        "run_identity": document.plan.payload.run_identity,
        "purpose": document.plan.payload.purpose,
        "scope": "canary-review:gs-v0.1",
        "approver_identity": "review-owner@example.com",
        "approver_role": "canary_review_approver",
        "issued_at": _NOW - timedelta(minutes=1),
        "expires_at": _NOW + timedelta(minutes=30),
        "review_decision": "approved",
        "granted_targets": ({"stage": "annotation", "product_id": _SECOND},),
        "execution_plan_hash": execution_plan_hash(document),
        "evaluated_revision": initial.result.evaluated_revision,
        "runtime_capability_version": initial.result.runtime_capability_version,
        "canary_target": {"stage": "annotation", "product_id": _FIRST},
        "budget_account_identity": account_id,
        "budget_revision": account.revision,
        "budget_approval_digest": account.approval_digest,
        "settlement_snapshot_digest": ledger.product_settlement_snapshot_digest(settlement),
        "artifacts": _artifacts(),
        "provider_usage": {
            "role": "annotator",
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_minor_units": usage.cost_minor_units,
            "role_rate_digest": role_rate_digest(document.budget_contract.role_rates["annotator"]),
        },
    }
    values.update(overrides)
    return CanaryReviewApprovalPayload.model_validate(values)


def _signed_review(
    review_key: Ed25519PrivateKey,
    payload: CanaryReviewApprovalPayload,
) -> CanaryReviewApprovalEnvelope:
    return CanaryReviewApprovalEnvelope(
        domain="canary-review",
        key_id="review-key",
        payload=payload,
        signature=base64.b64encode(
            review_key.sign(approval_signed_bytes("canary-review", payload))
        ).decode("ascii"),
    )


def _setup(
    tmp_path: Path,
) -> tuple[
    RunAdmissionDocument,
    BudgetLedger,
    ProductionAdmissionEvaluator,
    _ReviewSource,
    _ArtifactInspector,
    Ed25519PrivateKey,
]:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    review_key = Ed25519PrivateKey.generate()
    source = _ReviewSource()
    artifacts = _ArtifactInspector(_artifacts())
    evaluator = _evaluator(provenance_key, budget_key, review_key, source, artifacts)
    document = _document(provenance_key, budget_key)
    ledger = BudgetLedger._for_testing(
        tmp_path / "budget.sqlite3",
        clock=lambda: _NOW,
    )
    _settle_canary(evaluator, document, ledger)
    return document, ledger, evaluator, source, artifacts, review_key


def test_d1_5_execution_authorization_is_process_only_and_not_in_result(
    tmp_path: Path,
) -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    review_key = Ed25519PrivateKey.generate()
    source = _ReviewSource()
    inspector = _ArtifactInspector(_artifacts())
    document = _document(provenance_key, budget_key)
    evaluator = _evaluator(provenance_key, budget_key, review_key, source, inspector)

    decision = evaluator.evaluate_execution(
        document, BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: _NOW)
    )

    assert isinstance(decision, RuntimeAdmissionDecision)
    assert decision.result.state == "READY"
    assert decision.account is not None
    assert decision.authorization == InitialExecutionAuthorization(
        targets=(_CANARY_TARGET,),
        account_id=decision.account.account_id,
        account_revision=decision.account.revision,
        account_approval_digest=decision.account.approval_digest,
        execution_plan_hash=execution_plan_hash(document),
        evaluated_at=_NOW,
        expires_at=_NOW + timedelta(minutes=5),
    )
    assert "authorization" not in decision.result.model_dump(mode="json")
    assert not hasattr(decision, "model_dump")
    assert not hasattr(decision.authorization, "model_dump")
    with pytest.raises(FrozenInstanceError):
        decision.authorization.targets = ()  # type: ignore[misc]


@pytest.mark.parametrize(
    "field",
    (
        pytest.param("account_id", id="account-id"),
        pytest.param("account_revision", id="account-revision"),
        pytest.param("account_approval_digest", id="approval-digest"),
    ),
)
def test_d1_5_initial_authorization_must_match_runtime_account_snapshot(
    tmp_path: Path,
    field: str,
) -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    review_key = Ed25519PrivateKey.generate()
    document = _document(provenance_key, budget_key)
    evaluator = _evaluator(
        provenance_key,
        budget_key,
        review_key,
        _ReviewSource(),
        _ArtifactInspector(_artifacts()),
    )
    decision = evaluator.evaluate_execution(
        document,
        BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: _NOW),
    )
    assert isinstance(decision.authorization, InitialExecutionAuthorization)
    assert decision.account is not None
    if field == "account_id":
        mismatched = replace(decision.authorization, account_id="9" * 64)
    elif field == "account_revision":
        mismatched = replace(decision.authorization, account_revision=2)
    else:
        assert field == "account_approval_digest"
        mismatched = replace(
            decision.authorization,
            account_approval_digest="9" * 64,
        )

    with pytest.raises(ValueError, match="initial authorization account"):
        RuntimeAdmissionDecision(
            result=decision.result,
            authorization=mismatched,
            account=decision.account,
        )


def test_d1_5_review_dependencies_are_not_public_constructor_inputs() -> None:
    public_parameters = inspect.signature(ProductionAdmissionEvaluator).parameters
    assert "canary_review_source" not in public_parameters
    assert "artifact_evidence_inspector" not in public_parameters
    assert "allowed_canary_review_roles" not in public_parameters

    private_parameters = inspect.signature(
        ProductionAdmissionEvaluator._for_production_canary
    ).parameters
    assert "canary_review_source" in private_parameters
    assert "artifact_evidence_inspector" in private_parameters
    assert "allowed_canary_review_roles" in private_parameters


def test_d1_5_process_authorization_variants_are_strict_and_disjoint() -> None:
    with pytest.raises(ValueError, match="first canary"):
        InitialExecutionAuthorization(
            targets=(_SECOND_TARGET,),
            account_id="0" * 64,
            account_revision=1,
            account_approval_digest="1" * 64,
            execution_plan_hash="2" * 64,
            evaluated_at=_NOW,
            expires_at=_NOW + timedelta(minutes=1),
        )
    with pytest.raises(ValueError, match="digest"):
        ReviewedExecutionAuthorization(
            targets=(_SECOND_TARGET,),
            capability_digest="0" * 64,
            account_id="not-a-digest",
            settlement_snapshot_digest="1" * 64,
            artifact_evidence=_artifacts(),
            execution_plan_hash="2" * 64,
            evaluated_at=_NOW,
            expires_at=_NOW + timedelta(minutes=1),
        )


def test_d1_5_initial_canary_requires_typed_identity_product(tmp_path: Path) -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    review_key = Ed25519PrivateKey.generate()
    source = _ReviewSource()
    inspector = _ArtifactInspector(_artifacts())
    document = _document(provenance_key, budget_key, include_first=False)
    evaluator = _evaluator(provenance_key, budget_key, review_key, source, inspector)

    decision = evaluator.evaluate_execution(
        document, BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: _NOW)
    )

    assert decision.result.state == "BLOCKED"
    assert decision.authorization is None
    assert decision.account is not None
    assert any(
        blocker.code == "initial_canary_identity_missing" for blocker in decision.result.blockers
    )


def test_d1_5_initial_authorization_rechecks_base_expiry_at_final_clock(
    tmp_path: Path,
) -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    review_key = Ed25519PrivateKey.generate()
    source = _ReviewSource()
    ticks = iter((_NOW, _NOW, _NOW + timedelta(minutes=6)))
    evaluator = _evaluator(
        provenance_key,
        budget_key,
        review_key,
        source,
        _ArtifactInspector(_artifacts()),
        clock=lambda: next(ticks),
    )

    decision = evaluator.evaluate_execution(
        _document(provenance_key, budget_key),
        BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: _NOW),
    )

    assert decision.result.state == "BLOCKED"
    assert decision.authorization is None
    assert decision.account is not None
    assert any(
        blocker.code == "execution_authorization_expired" for blocker in decision.result.blockers
    )


def test_d1_5_revalidate_initial_authorization_rechecks_time_and_plan(
    tmp_path: Path,
) -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    review_key = Ed25519PrivateKey.generate()
    clock = _MutableClock()
    document = _document(provenance_key, budget_key)
    evaluator = _evaluator(
        provenance_key,
        budget_key,
        review_key,
        _ReviewSource(),
        _ArtifactInspector(_artifacts()),
        clock=clock,
    )
    decision = evaluator.evaluate_execution(
        document,
        BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: _NOW),
    )
    assert isinstance(decision.authorization, InitialExecutionAuthorization)
    authorization = decision.authorization

    evaluator.revalidate_initial_authorization(document, authorization)

    changed_identity = document.identity_request.model_copy(
        update={"source_products_root": "dataset/changed"}
    )
    with pytest.raises(ExecutionAuthorizationValidationError, match="plan drifted"):
        evaluator.revalidate_initial_authorization(
            document.model_copy(update={"identity_request": changed_identity}),
            authorization,
        )

    clock.current = authorization.evaluated_at - timedelta(microseconds=1)
    with pytest.raises(ExecutionAuthorizationValidationError, match="backwards"):
        evaluator.revalidate_initial_authorization(document, authorization)

    clock.current = authorization.expires_at
    with pytest.raises(ExecutionAuthorizationValidationError, match="expired"):
        evaluator.revalidate_initial_authorization(document, authorization)


def test_d1_5_valid_review_grants_only_second_annotation(tmp_path: Path) -> None:
    document, ledger, evaluator, source, artifacts, review_key = _setup(tmp_path)
    initial = evaluator.evaluate_execution(document, ledger)
    payload = _review_payload(document, ledger, initial)
    envelope = _signed_review(review_key, payload)
    source.envelope = envelope

    decision = evaluator.evaluate_execution(document, ledger)

    assert decision.result.state == "READY"
    assert decision.authorization == ReviewedExecutionAuthorization(
        targets=(_SECOND_TARGET,),
        capability_digest=canary_review_capability_digest(envelope),
        account_id=payload.budget_account_identity,
        settlement_snapshot_digest=payload.settlement_snapshot_digest,
        artifact_evidence=payload.artifacts,
        execution_plan_hash=payload.execution_plan_hash,
        evaluated_at=_NOW,
        expires_at=_NOW + timedelta(minutes=5),
    )
    assert decision.account is not None
    assert decision.account.account_id == payload.budget_account_identity
    assert artifacts.calls == 1
    with pytest.raises(ValueError, match="account"):
        RuntimeAdmissionDecision(
            result=decision.result,
            authorization=decision.authorization,
            account=decision.account.model_copy(update={"account_id": "9" * 64}),
        )


@pytest.mark.parametrize(
    "quality_evidence",
    (
        pytest.param(
            _artifacts().model_copy(
                update={"quality_threshold_version": "uncontrolled-thresholds-v2"}
            ),
            id="threshold-version",
        ),
        pytest.param(
            _artifacts().model_copy(update={"disputed_count": 1, "record_count": 19}),
            id="one-of-nineteen",
        ),
    ),
)
def test_d1_5_matching_signed_and_observed_quality_ineligible_review_blocks(
    tmp_path: Path,
    quality_evidence: CanaryReviewArtifactEvidence,
) -> None:
    document, ledger, evaluator, source, artifacts, review_key = _setup(tmp_path)
    initial = evaluator.evaluate_execution(document, ledger)
    artifacts.evidence = quality_evidence
    payload = _review_payload(
        document,
        ledger,
        initial,
        artifacts=quality_evidence,
    )
    source.envelope = _signed_review(review_key, payload)

    decision = evaluator.evaluate_execution(document, ledger)

    assert artifacts.evidence == payload.artifacts
    assert decision.result.state == "BLOCKED"
    assert decision.authorization is None
    assert any(
        blocker.code == "canary_review_quality_ineligible" for blocker in decision.result.blockers
    )


def test_d1_5_matching_quality_at_exact_five_percent_can_continue(
    tmp_path: Path,
) -> None:
    document, ledger, evaluator, source, artifacts, review_key = _setup(tmp_path)
    initial = evaluator.evaluate_execution(document, ledger)
    boundary = _artifacts().model_copy(update={"disputed_count": 1, "record_count": 20})
    artifacts.evidence = boundary
    payload = _review_payload(document, ledger, initial, artifacts=boundary)
    source.envelope = _signed_review(review_key, payload)

    decision = evaluator.evaluate_execution(document, ledger)

    assert artifacts.evidence == payload.artifacts
    assert decision.result.state == "READY"
    assert isinstance(decision.authorization, ReviewedExecutionAuthorization)


def test_d1_5_review_authorization_keeps_signed_digest_across_later_drift(
    tmp_path: Path,
) -> None:
    document, ledger, evaluator, source, _artifacts_inspector, review_key = _setup(tmp_path)
    initial = evaluator.evaluate_execution(document, ledger)
    payload = _review_payload(document, ledger, initial)
    source.envelope = _signed_review(review_key, payload)

    decision = evaluator.evaluate_execution(document, ledger)
    assert isinstance(decision.authorization, ReviewedExecutionAuthorization)
    signed_digest = decision.authorization.settlement_snapshot_digest
    assert signed_digest == payload.settlement_snapshot_digest

    with sqlite3.connect(tmp_path / "budget.sqlite3") as connection:
        connection.execute(
            "UPDATE request_attempts SET response_digest=? WHERE product_id=?",
            ("7" * 64, _FIRST),
        )
    account_id = budget_account_identity(
        document.plan.payload.run_identity,
        document.plan.payload.purpose,
    )
    fresh = ledger.product_settlement_snapshot_digest(
        ledger.product_settlement_snapshot(account_id, "annotation", _FIRST)
    )

    assert fresh != signed_digest
    assert decision.authorization.settlement_snapshot_digest == signed_digest
    with pytest.raises(FrozenInstanceError):
        decision.authorization.settlement_snapshot_digest = fresh  # type: ignore[misc]


@pytest.mark.parametrize(
    ("overrides", "blocker"),
    [
        ({"review_decision": "rejected", "granted_targets": ()}, "canary_review_rejected"),
        (
            {"granted_targets": ({"stage": "annotation", "product_id": _FIRST},)},
            "canary_review_grants_invalid",
        ),
        (
            {"granted_targets": ({"stage": "baseline", "product_id": _FIRST},)},
            "canary_review_grants_invalid",
        ),
        (
            {
                "granted_targets": (
                    {"stage": "annotation", "product_id": _SECOND},
                    {"stage": "baseline", "product_id": _FIRST},
                )
            },
            "canary_review_grants_invalid",
        ),
        ({"execution_plan_hash": "3" * 64}, "canary_review_execution_plan_mismatch"),
        ({"evaluated_revision": "4" * 40}, "canary_review_revision_mismatch"),
        ({"runtime_capability_version": "attacker-runtime"}, "canary_review_runtime_mismatch"),
        ({"budget_revision": 2}, "canary_review_budget_mismatch"),
        ({"budget_approval_digest": "5" * 64}, "canary_review_budget_mismatch"),
        ({"settlement_snapshot_digest": "6" * 64}, "canary_review_settlement_mismatch"),
    ],
)
def test_d1_5_semantic_invalid_review_blocks_globally_without_fallback(
    tmp_path: Path,
    overrides: dict[str, object],
    blocker: str,
) -> None:
    document, ledger, evaluator, source, _artifacts_inspector, review_key = _setup(tmp_path)
    initial = evaluator.evaluate_execution(document, ledger)
    source.envelope = _signed_review(
        review_key,
        _review_payload(document, ledger, initial, **overrides),
    )

    decision = evaluator.evaluate_execution(document, ledger)

    assert decision.result.state == "BLOCKED"
    assert decision.authorization is None
    assert decision.account is not None
    assert any(item.code == blocker for item in decision.result.blockers)


def test_d1_5_invalid_signature_artifact_or_usage_drift_blocks(
    tmp_path: Path,
) -> None:
    document, ledger, evaluator, source, artifacts, review_key = _setup(tmp_path)
    initial = evaluator.evaluate_execution(document, ledger)
    payload = _review_payload(document, ledger, initial)
    signed = _signed_review(review_key, payload)
    source.envelope = signed.model_copy(update={"signature": "not-base64"})
    assert evaluator.evaluate_execution(document, ledger).authorization is None

    source.envelope = signed
    artifacts.evidence = artifacts.evidence.model_copy(update={"golden_digest": "7" * 64})
    artifact_drift = evaluator.evaluate_execution(document, ledger)
    assert artifact_drift.authorization is None
    assert any(
        item.code == "canary_review_artifact_mismatch" for item in artifact_drift.result.blockers
    )

    artifacts.evidence = _artifacts()
    usage_payload = _review_payload(
        document,
        ledger,
        initial,
        provider_usage={
            **payload.provider_usage.model_dump(mode="python"),
            "input_tokens": payload.provider_usage.input_tokens + 1,
        },
    )
    source.envelope = _signed_review(review_key, usage_payload)
    usage_drift = evaluator.evaluate_execution(document, ledger)
    assert usage_drift.authorization is None
    assert any(item.code == "canary_review_usage_mismatch" for item in usage_drift.result.blockers)


def test_d1_5_role_rate_and_ledger_drift_block_review(tmp_path: Path) -> None:
    document, ledger, evaluator, source, _artifacts_inspector, review_key = _setup(tmp_path)
    initial = evaluator.evaluate_execution(document, ledger)
    payload = _review_payload(document, ledger, initial)
    bad_rate = payload.model_copy(
        update={
            "provider_usage": payload.provider_usage.model_copy(
                update={"role_rate_digest": "8" * 64}
            )
        }
    )
    source.envelope = _signed_review(review_key, bad_rate)
    assert evaluator.evaluate_execution(document, ledger).authorization is None

    source.envelope = _signed_review(review_key, payload)
    account_id = budget_account_identity(
        document.plan.payload.run_identity,
        document.plan.payload.purpose,
    )
    with ledger._mutation() as connection:  # same-process deterministic drift injection
        connection.execute(
            "UPDATE request_attempts SET usage_verified=0 WHERE account_id=?",
            (account_id,),
        )
    drift = evaluator.evaluate_execution(document, ledger)
    assert drift.authorization is None
    assert any(item.code == "canary_review_settlement_ineligible" for item in drift.result.blockers)


def test_d1_5_execution_plan_hash_excludes_approvals_and_derived_state() -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    document = _document(provenance_key, budget_key)
    changed_plan = document.plan.model_copy(
        update={"derived_state": AdmissionDerivedState(state="READY")}
    )

    assert execution_plan_hash(document) == execution_plan_hash(
        document.model_copy(update={"plan": changed_plan})
    )


def test_d1_5_review_source_input_error_is_not_downgraded_to_initial_canary(
    tmp_path: Path,
) -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    review_key = Ed25519PrivateKey.generate()
    source = _ReviewSource()
    source.error = PermissionError("unsafe deployment inbox")
    document = _document(provenance_key, budget_key)
    evaluator = _evaluator(
        provenance_key,
        budget_key,
        review_key,
        source,
        _ArtifactInspector(_artifacts()),
    )

    with pytest.raises(PermissionError, match="unsafe deployment inbox"):
        evaluator.evaluate_execution(
            document, BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: _NOW)
        )


def test_d1_5_artifact_inspection_failure_is_semantic_block(tmp_path: Path) -> None:
    document, ledger, evaluator, source, artifacts, review_key = _setup(tmp_path)
    initial = evaluator.evaluate_execution(document, ledger)
    source.envelope = _signed_review(review_key, _review_payload(document, ledger, initial))
    artifacts.error = ArtifactEvidenceInspectionError("missing content address")

    decision = evaluator.evaluate_execution(document, ledger)

    assert decision.authorization is None
    assert any(
        item.code == "canary_review_artifact_unavailable" for item in decision.result.blockers
    )


def test_d1_5_final_clock_rechecks_review_and_base_expiry(tmp_path: Path) -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    review_key = Ed25519PrivateKey.generate()
    source = _ReviewSource()
    artifacts = _ArtifactInspector(_artifacts())
    clock = _MutableClock()
    evaluator = _evaluator(
        provenance_key,
        budget_key,
        review_key,
        source,
        artifacts,
        clock=clock,
    )
    document = _document(provenance_key, budget_key)
    ledger = BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: _NOW)
    _settle_canary(evaluator, document, ledger)
    initial = evaluator.evaluate_execution(document, ledger)
    payload = _review_payload(
        document,
        ledger,
        initial,
        expires_at=_NOW + timedelta(minutes=1),
    )
    source.envelope = _signed_review(review_key, payload)
    artifacts.on_inspect = lambda: setattr(clock, "current", _NOW + timedelta(minutes=2))

    decision = evaluator.evaluate_execution(document, ledger)

    assert decision.result.state == "BLOCKED"
    assert decision.authorization is None
    assert decision.account is not None
    assert any(blocker.code == "canary_review_invalid" for blocker in decision.result.blockers)


def test_d1_5_revalidate_review_authorization_rechecks_time_plan_and_artifacts(
    tmp_path: Path,
) -> None:
    provenance_key = Ed25519PrivateKey.generate()
    budget_key = Ed25519PrivateKey.generate()
    review_key = Ed25519PrivateKey.generate()
    source = _ReviewSource()
    artifacts = _ArtifactInspector(_artifacts())
    clock = _MutableClock()
    evaluator = _evaluator(
        provenance_key,
        budget_key,
        review_key,
        source,
        artifacts,
        clock=clock,
    )
    document = _document(provenance_key, budget_key)
    ledger = BudgetLedger._for_testing(tmp_path / "budget.sqlite3", clock=lambda: _NOW)
    _settle_canary(evaluator, document, ledger)
    initial = evaluator.evaluate_execution(document, ledger)
    source.envelope = _signed_review(review_key, _review_payload(document, ledger, initial))
    decision = evaluator.evaluate_execution(document, ledger)
    assert isinstance(decision.authorization, ReviewedExecutionAuthorization)
    authorization = decision.authorization

    evaluator.revalidate_review_authorization(document, authorization)

    changed_identity = document.identity_request.model_copy(
        update={"source_products_root": "dataset/changed"}
    )
    with pytest.raises(ExecutionAuthorizationValidationError, match="plan"):
        evaluator.revalidate_review_authorization(
            document.model_copy(update={"identity_request": changed_identity}),
            authorization,
        )

    artifacts.evidence = artifacts.evidence.model_copy(update={"manifest_digest": "8" * 64})
    with pytest.raises(
        ExecutionAuthorizationValidationError,
        match="^reviewed execution authorization artifact drifted$",
    ):
        evaluator.revalidate_review_authorization(document, authorization)
    artifacts.evidence = authorization.artifact_evidence
    clock.current = authorization.evaluated_at - timedelta(microseconds=1)
    with pytest.raises(ExecutionAuthorizationValidationError, match="backwards"):
        evaluator.revalidate_review_authorization(document, authorization)

    clock.current = authorization.expires_at
    with pytest.raises(ExecutionAuthorizationValidationError, match="expired"):
        evaluator.revalidate_review_authorization(document, authorization)
