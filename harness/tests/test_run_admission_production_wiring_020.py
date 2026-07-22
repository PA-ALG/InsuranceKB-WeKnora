"""OpenSpec 020 D1.5 production entrypoint wiring contracts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn, Protocol, cast

import pytest

from insurance_harness.compiler.models import BaselineAdmissionIdentity, RunManifest
from insurance_harness.compiler.pipeline import RunResult, run_settlement_guard
from insurance_harness.goldenset import admission as admission_module
from insurance_harness.goldenset import run_020
from insurance_harness.goldenset.admission import (
    AdmissionResult,
    ArtifactEvidenceInspectionError,
    InitialExecutionAuthorization,
    ProductionAdmissionEvaluator,
    ReviewedExecutionAuthorization,
    RunAdmissionDocument,
    RuntimeAdmissionDecision,
)
from insurance_harness.goldenset.admission_artifacts import (
    CanaryArtifactBundle,
    CanaryReviewCandidate,
)
from insurance_harness.goldenset.admission_budget import (
    BudgetLedger,
    BudgetLedgerError,
    ProductSettlementSnapshot,
)
from insurance_harness.goldenset.admission_models import CanaryReviewArtifactEvidence
from insurance_harness.goldenset.admission_runtime import (
    AdmissionBlockedError,
    AdmissionPausedError,
)

_FIRST_CANARY = "平安爱满分（2026）两全保险"
_SECOND_CANARY = "平安附加（2026）意外伤害保险"
_PLAN_HASH = "a" * 64


def test_d1_3c_d1_5_production_runtime_capability_is_code_attested() -> None:
    assert admission_module._PRODUCTION_RUNTIME_CAPABILITY_READY is True
    assert (
        admission_module._RUNTIME_CAPABILITY_VERSION
        == "budget-ledger-v3-canary-v1"
    )


class _ProductionArtifactCommitter(Protocol):
    def __call__(
        self,
        *,
        document: RunAdmissionDocument,
        command: str,
        product_id: str,
        execution_result: object,
        configuration: object,
    ) -> None: ...


class _ProductionCandidateBuilder(Protocol):
    def __call__(
        self,
        *,
        document: RunAdmissionDocument,
        ledger: BudgetLedger,
        execution_decision: RuntimeAdmissionDecision,
        configuration: object,
    ) -> CanaryReviewCandidate: ...


class _ProductionCandidatePersister(Protocol):
    def __call__(
        self,
        *,
        candidate: object,
        configuration: object,
    ) -> None: ...


class _ProductionCandidateResumer(Protocol):
    def __call__(
        self,
        *,
        product_id: str,
        document: RunAdmissionDocument,
        evaluator: ProductionAdmissionEvaluator,
        ledger: BudgetLedger,
        configuration: object,
        candidate_admission_boundary: object,
    ) -> bool: ...


class _RecordingArtifactStore:
    def __init__(self) -> None:
        self.writes: list[tuple[str, object]] = []
        self.annotation_writes: list[tuple[str, str, object]] = []
        self.candidate_writes: list[CanaryReviewCandidate] = []

    def write_first_canary(
        self,
        *,
        execution_plan_hash: str,
        bundle: object,
    ) -> object:
        self.writes.append((execution_plan_hash, bundle))
        return object()

    def write_annotation_bundle(
        self,
        *,
        execution_plan_hash: str,
        product_id: str,
        bundle: object,
    ) -> object:
        self.annotation_writes.append((execution_plan_hash, product_id, bundle))
        return object()

    def write_candidate(self, candidate: CanaryReviewCandidate) -> Path:
        self.candidate_writes.append(candidate)
        return Path("canary-review-candidate.json")


def _bundle() -> CanaryArtifactBundle:
    return CanaryArtifactBundle(
        checkpoint=b"checkpoint",
        manifest=b"manifest",
        golden=b"golden",
        quote_verification=b"quote-verification",
        disputed_quality=b"disputed-quality",
        disputed_count=0,
        record_count=1,
        quality_threshold_version="gs-v0.1",
    )


def _configuration(tmp_path: Path) -> run_020._ProductionConfiguration:
    return run_020._ProductionConfiguration(
        repo_root=tmp_path / "repo",
        plan_path=tmp_path / "plan.yaml",
        trust_path=tmp_path / "trust.yaml",
        review_inbox=tmp_path / "review-inbox",
        ledger_path=tmp_path / "budget.sqlite3",
        session_root=tmp_path / "sessions",
        run_root=tmp_path / "runs",
        probe=True,
    )


def _install_annotation_commit_validation(
    *,
    monkeypatch: pytest.MonkeyPatch,
    configuration: run_020._ProductionConfiguration,
    document: RunAdmissionDocument,
    product_id: str,
    bundle: CanaryArtifactBundle,
) -> list[dict[str, object]]:
    source_bytes = b"signed-pdf"
    inputs = SimpleNamespace(
        repo_root=configuration.repo_root,
        product_dir=configuration.repo_root / "source" / product_id,
        source_files=(("terms.pdf", source_bytes),),
    )
    snapshot = SimpleNamespace(
        product_dir=configuration.run_root / "snapshot" / product_id,
    )
    cache_dir = configuration.run_root / "annotation-cache" / _PLAN_HASH
    calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        run_020,
        "_load_annotation_inputs",
        lambda **_kwargs: inputs,
        raising=False,
    )
    monkeypatch.setattr(
        run_020,
        "_private_annotation_snapshot",
        lambda **_kwargs: snapshot,
    )
    monkeypatch.setattr(
        run_020,
        "_private_annotation_cache",
        lambda **_kwargs: cache_dir,
    )

    def validate(**kwargs: object) -> CanaryArtifactBundle:
        calls.append(kwargs)
        return bundle

    monkeypatch.setattr(run_020, "validate_annotation_bundle", validate, raising=False)
    return calls


def _resume_document() -> RunAdmissionDocument:
    return cast(
        RunAdmissionDocument,
        SimpleNamespace(
            plan=SimpleNamespace(
                payload=SimpleNamespace(run_identity="run-020", purpose="canary")
            )
        ),
    )


def _committer() -> _ProductionArtifactCommitter:
    return cast(_ProductionArtifactCommitter, run_020._commit_execution_artifact)


def _candidate_builder() -> _ProductionCandidateBuilder:
    return cast(_ProductionCandidateBuilder, run_020._build_annotation_candidate)


def _candidate_persister() -> _ProductionCandidatePersister:
    return cast(
        _ProductionCandidatePersister,
        run_020._persist_annotation_candidate,
    )


def _candidate_resumer() -> _ProductionCandidateResumer:
    return cast(
        _ProductionCandidateResumer,
        run_020._resume_annotation_candidate_fail_closed,
    )


def _candidate_boundary(**kwargs: object) -> RuntimeAdmissionDecision:
    return run_020._fresh_initial_candidate_decision(
        document=cast(RunAdmissionDocument, kwargs["document"]),
        evaluator=cast(ProductionAdmissionEvaluator, kwargs["evaluator"]),
        ledger=cast(BudgetLedger, kwargs["ledger"]),
    )


def test_d1_5_production_dependencies_hold_pipeline_lock_through_settlement() -> None:
    dependencies = run_020._production_ready_dependencies()

    assert dependencies.baseline_settlement_guard is run_settlement_guard
    assert dependencies.operational_finalizer is run_020._finalize_operational_admission
    assert (
        dependencies.candidate_admission_boundary
        is run_020._evaluate_candidate_with_operational_postcheck
    )


def test_o8_t9_18_production_candidate_boundary_blocks_before_build_and_persist(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = _resume_document()
    ledger = cast(BudgetLedger, object())
    decision = _fresh_decision()
    evaluator_impl = _ResumeEvaluator(decision)
    evaluator = cast(ProductionAdmissionEvaluator, evaluator_impl)
    events: list[str] = []

    class _PostcheckFailureFinalizer:
        def __init__(
            self,
            *,
            ledger: BudgetLedger,
            evaluator: ProductionAdmissionEvaluator,
        ) -> None:
            assert ledger is globals_ledger
            assert evaluator is globals_evaluator
            events.append("finalizer_constructed")

        def evaluate_with_fresh_topology_postcheck(
            self,
            _document: RunAdmissionDocument,
            *,
            expected_scope: str,
            evaluation: Callable[[], RuntimeAdmissionDecision],
        ) -> RuntimeAdmissionDecision:
            assert expected_scope == "goldenset-production"
            events.append("fresh_postcheck")
            evaluation()
            raise BudgetLedgerError("post-evaluator durable reload failed")

    globals_ledger = ledger
    globals_evaluator = evaluator
    monkeypatch.setattr(
        run_020,
        "OperationalAdmissionFinalizer",
        _PostcheckFailureFinalizer,
    )
    dependencies = run_020._production_ready_dependencies()

    def forbidden_builder(**_kwargs: object) -> CanaryReviewCandidate:
        events.append("candidate_write")
        raise AssertionError("candidate build ran after topology reload failure")

    def forbidden_persister(**_kwargs: object) -> None:
        events.append("candidate_write")
        raise AssertionError("candidate persist ran after topology reload failure")

    with pytest.raises(
        AdmissionPausedError, match="^operational_finalization_blocked$"
    ):
        run_020._build_and_persist_annotation_candidate_after_postcheck(
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            configuration=_configuration(tmp_path),
            candidate_admission_boundary=(
                dependencies.candidate_admission_boundary
            ),
            candidate_builder=forbidden_builder,
            candidate_persister=forbidden_persister,
        )

    assert evaluator_impl.calls == [(document, ledger)]
    assert events == ["finalizer_constructed", "fresh_postcheck"]


def _fresh_decision() -> RuntimeAdmissionDecision:
    authorization = object.__new__(InitialExecutionAuthorization)
    decision = object.__new__(RuntimeAdmissionDecision)
    object.__setattr__(decision, "result", SimpleNamespace(state="READY"))
    object.__setattr__(decision, "authorization", authorization)
    object.__setattr__(decision, "account", object())
    return decision


def _reviewed_decision() -> RuntimeAdmissionDecision:
    authorization = object.__new__(ReviewedExecutionAuthorization)
    decision = object.__new__(RuntimeAdmissionDecision)
    object.__setattr__(
        decision,
        "result",
        AdmissionResult(
            state="READY",
            plan_payload_hash="a" * 64,
            evaluated_revision="f" * 40,
            evaluated_at=datetime(2026, 7, 20, tzinfo=UTC),
            checker_version="020.1",
            runtime_capability_version="budget-ledger-v3-canary-v1",
            checks=(),
            blockers=(),
        ),
    )
    object.__setattr__(decision, "authorization", authorization)
    object.__setattr__(decision, "account", object())
    return decision


class _ResumeLedger:
    def __init__(self, reservation_state: str | None) -> None:
        self.reservation_state = reservation_state
        self.snapshot_calls: list[tuple[str, str, str]] = []
        self.settle_calls = 0

    def product_settlement_snapshot(
        self,
        account_id: str,
        stage: str,
        product_id: str,
    ) -> ProductSettlementSnapshot:
        self.snapshot_calls.append((account_id, stage, product_id))
        if self.reservation_state is None:
            raise BudgetLedgerError("product reservation not found")
        return ProductSettlementSnapshot.model_construct(
            account_id=account_id,
            budget_revision=1,
            approval_digest="b" * 64,
            stage=stage,
            product_id=product_id,
            reservation_state=self.reservation_state,
            reservation_maximum=object(),
            reservation_actual=object(),
            attempts=(),
        )

    def settle_product(self, *_args: object, **_kwargs: object) -> None:
        self.settle_calls += 1
        raise AssertionError("candidate resume must not create a new settlement")


class _ResumeArtifactStore:
    def __init__(self, state: str) -> None:
        self.state = state
        self.inspect_calls: list[tuple[str, str, str]] = []

    def inspect(self, *, execution_plan_hash: str, canary_target: object) -> object:
        self.inspect_calls.append(
            (
                execution_plan_hash,
                str(canary_target.stage),  # type: ignore[attr-defined]
                str(canary_target.product_id),  # type: ignore[attr-defined]
            )
        )
        if self.state == "missing":
            raise ArtifactEvidenceInspectionError("canary artifact bundle is missing")
        if self.state == "drift":
            raise ArtifactEvidenceInspectionError("canary evidence index identity drifted")
        return CanaryReviewArtifactEvidence(
            checkpoint_digest="1" * 64,
            manifest_digest="2" * 64,
            golden_digest="3" * 64,
            quote_verification_digest="4" * 64,
            disputed_quality_digest="5" * 64,
            disputed_count=0,
            record_count=1,
            quality_threshold_version="gs-v0.1",
        )

    def inspect_optional(
        self,
        *,
        execution_plan_hash: str,
        canary_target: object,
    ) -> object | None:
        try:
            return self.inspect(
                execution_plan_hash=execution_plan_hash,
                canary_target=canary_target,
            )
        except ArtifactEvidenceInspectionError:
            if self.state == "missing":
                return None
            raise


class _ResumeEvaluator:
    def __init__(self, decision: RuntimeAdmissionDecision) -> None:
        self.decision = decision
        self.calls: list[tuple[RunAdmissionDocument, BudgetLedger]] = []

    def evaluate_execution(
        self,
        document: RunAdmissionDocument,
        ledger: BudgetLedger,
    ) -> RuntimeAdmissionDecision:
        self.calls.append((document, ledger))
        return self.decision


def test_d1_5_production_evaluator_uses_review_aware_factory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configuration = _configuration(tmp_path)
    trusted_keys = cast(dict[str, object], {"deployment-key": object()})
    budget_roles = frozenset({"budget-approver"})
    provenance_roles = frozenset({"provenance-approver"})
    review_roles = frozenset({"canary-reviewer"})
    artifact_store = object()
    captured: dict[str, object] = {}

    def deployment_configuration() -> tuple[
        dict[str, object],
        frozenset[str],
        frozenset[str],
        frozenset[str],
    ]:
        return trusted_keys, budget_roles, provenance_roles, review_roles

    def deployment_review_loader() -> None:
        return None

    def production_factory(
        cls: type[ProductionAdmissionEvaluator],
        /,
        **kwargs: object,
    ) -> ProductionAdmissionEvaluator:
        captured["cls"] = cls
        captured.update(kwargs)
        return cast(ProductionAdmissionEvaluator, captured)

    def forbid_public_constructor(
        self: ProductionAdmissionEvaluator,
        **_kwargs: object,
    ) -> None:
        del self
        raise AssertionError("public evaluator constructor bypasses canary review")

    monkeypatch.setattr(
        run_020,
        "_load_deployment_approval_configuration",
        deployment_configuration,
    )
    monkeypatch.setattr(
        run_020,
        "_load_deployment_canary_review_approval",
        deployment_review_loader,
        raising=False,
    )
    monkeypatch.setattr(
        run_020,
        "CanaryArtifactStore",
        lambda: artifact_store,
        raising=False,
    )
    monkeypatch.setattr(
        ProductionAdmissionEvaluator,
        "_for_production_canary",
        classmethod(production_factory),
    )
    monkeypatch.setattr(
        ProductionAdmissionEvaluator,
        "__init__",
        forbid_public_constructor,
    )

    evaluator = run_020._build_production_evaluator(configuration)

    assert cast(object, evaluator) is captured
    assert captured == {
        "cls": ProductionAdmissionEvaluator,
        "repo_root": configuration.repo_root,
        "trusted_public_keys": trusted_keys,
        "allowed_budget_roles": budget_roles,
        "allowed_provenance_roles": provenance_roles,
        "allowed_canary_review_roles": review_roles,
        "canary_review_source": deployment_review_loader,
        "artifact_evidence_inspector": artifact_store,
        "probe": True,
    }


def test_d1_5_annotation_committer_hashes_document_and_writes_exact_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = cast(RunAdmissionDocument, object())
    configuration = _configuration(tmp_path)
    artifact = _bundle()
    store = _RecordingArtifactStore()
    hashed: list[RunAdmissionDocument] = []

    def plan_hash(value: RunAdmissionDocument) -> str:
        hashed.append(value)
        return _PLAN_HASH

    monkeypatch.setattr(run_020, "execution_plan_hash", plan_hash)
    validation_calls = _install_annotation_commit_validation(
        monkeypatch=monkeypatch,
        configuration=configuration,
        document=document,
        product_id=_FIRST_CANARY,
        bundle=artifact,
    )
    monkeypatch.setattr(
        run_020,
        "CanaryArtifactStore",
        lambda: store,
        raising=False,
    )

    _committer()(
        document=document,
        command="annotate-canary",
        product_id=_FIRST_CANARY,
        execution_result=artifact,
        configuration=configuration,
    )

    assert hashed == [document]
    assert len(validation_calls) == 1
    assert validation_calls[0]["document"] is document
    assert validation_calls[0]["configuration"] is configuration
    assert validation_calls[0]["product_id"] == _FIRST_CANARY
    assert validation_calls[0]["bundle"] is artifact
    assert validation_calls[0]["execution_plan_hash"] == _PLAN_HASH
    assert callable(validation_calls[0]["page_loader"])
    assert store.writes == [(_PLAN_HASH, artifact)]


def test_d1_5_second_annotation_committer_uses_target_aware_durable_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = cast(RunAdmissionDocument, object())
    configuration = _configuration(tmp_path)
    artifact = _bundle()
    store = _RecordingArtifactStore()
    monkeypatch.setattr(run_020, "execution_plan_hash", lambda _value: _PLAN_HASH)
    validation_calls = _install_annotation_commit_validation(
        monkeypatch=monkeypatch,
        configuration=configuration,
        document=document,
        product_id=_SECOND_CANARY,
        bundle=artifact,
    )
    monkeypatch.setattr(
        run_020,
        "CanaryArtifactStore",
        lambda: store,
        raising=False,
    )

    _committer()(
        document=document,
        command="annotate-canary",
        product_id=_SECOND_CANARY,
        execution_result=artifact,
        configuration=configuration,
    )

    assert store.writes == []
    assert len(validation_calls) == 1
    assert store.annotation_writes == [(_PLAN_HASH, _SECOND_CANARY, artifact)]


def test_d1_5_annotation_committer_persists_nothing_when_semantic_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = cast(RunAdmissionDocument, object())
    configuration = _configuration(tmp_path)
    artifact = _bundle()
    store = _RecordingArtifactStore()
    monkeypatch.setattr(run_020, "execution_plan_hash", lambda _value: _PLAN_HASH)
    _install_annotation_commit_validation(
        monkeypatch=monkeypatch,
        configuration=configuration,
        document=document,
        product_id=_FIRST_CANARY,
        bundle=artifact,
    )

    def reject(**_kwargs: object) -> CanaryArtifactBundle:
        raise AdmissionPausedError("canary_artifact_commit_invalid")

    monkeypatch.setattr(run_020, "validate_annotation_bundle", reject, raising=False)
    monkeypatch.setattr(run_020, "CanaryArtifactStore", lambda: store, raising=False)

    with pytest.raises(AdmissionPausedError, match="^canary_artifact_commit_invalid$"):
        _committer()(
            document=document,
            command="annotate-canary",
            product_id=_FIRST_CANARY,
            execution_result=artifact,
            configuration=configuration,
        )

    assert store.writes == []
    assert store.annotation_writes == []


@pytest.mark.parametrize(
    ("command", "product_id", "execution_result"),
    [
        ("unknown", _FIRST_CANARY, _bundle()),
        ("annotate-canary", "wrong-product", _bundle()),
        ("annotate-canary", _FIRST_CANARY, object()),
    ],
)
def test_d1_5_annotation_committer_rejects_non_canary_inputs_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    command: str,
    product_id: str,
    execution_result: object,
) -> None:
    document = cast(RunAdmissionDocument, object())
    configuration = _configuration(tmp_path)
    store = _RecordingArtifactStore()
    monkeypatch.setattr(run_020, "execution_plan_hash", lambda _value: _PLAN_HASH)
    monkeypatch.setattr(
        run_020,
        "CanaryArtifactStore",
        lambda: store,
        raising=False,
    )

    with pytest.raises(AdmissionPausedError, match="^canary_artifact_commit_invalid$"):
        _committer()(
            document=document,
            command=command,
            product_id=product_id,
            execution_result=execution_result,
            configuration=configuration,
        )

    assert store.writes == []
    assert store.annotation_writes == []


@pytest.mark.parametrize(
    ("validator_drift", "forged_run_identity"),
    [(False, False), (True, False), (False, True)],
)
def test_d1_5_baseline_committer_rechecks_typed_durable_result_before_settlement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    validator_drift: bool,
    forged_run_identity: bool,
) -> None:
    target_digest = run_020._baseline_target_digest(_SECOND_CANARY)
    run_id = "forged-target" if forged_run_identity else target_digest
    product_dir = (
        tmp_path
        / "runs"
        / "baseline-input-snapshots"
        / _PLAN_HASH
        / ("b" * 64)
        / "product"
    )
    run_dir = tmp_path / "runs" / _PLAN_HASH / run_id
    admission_identity = BaselineAdmissionIdentity(
        format="insurancekb.baseline-admission-identity.v1",
        execution_plan_hash=_PLAN_HASH,
        parser_fingerprint="1" * 64,
        pdf_digests={"terms.pdf": "2" * 64},
        product_meta_digest="3" * 64,
        fields_digest="4" * 64,
        consumed_input_digests={"golden.jsonl": "5" * 64},
        shared_input_digests={"schema.yaml": "6" * 64},
        extractor_model_id="weak-deployment",
        judge_model_id="judge-deployment",
        schema_version="v1.1",
        template_registry_version="templates-v1",
    )
    manifest = RunManifest(
        run_id=run_id,
        run_dir=str(run_dir),
        checkpoint_path=str(run_dir / "checkpoint.sqlite3"),
        product_dir=str(product_dir),
        product_id="1814",
        product_name=_SECOND_CANARY,
        line_key="accident",
        schema_version="v1.1",
        model_id="weak-deployment",
        judge_mode="gateway",
        template_registry_version="templates-v1",
        baseline_admission=admission_identity,
    )
    result = RunResult(
        manifest=manifest,
        pred_path=run_dir / "pred.jsonl",
        manifest_path=run_dir / "manifest.json",
        judge_queue_path=run_dir / "judge-queue.jsonl",
    )
    document = cast(
        RunAdmissionDocument,
        SimpleNamespace(
            identity_request=SimpleNamespace(
                products=(
                        SimpleNamespace(
                            product_id=_SECOND_CANARY,
                            line_key="accident",
                            pdf_digests={"terms.pdf": "2" * 64},
                            product_meta_digest="3" * 64,
                            fields_digest="4" * 64,
                            consumed_input_digests={"golden.jsonl": "5" * 64},
                        ),
                    ),
                    shared_input_digests={"schema.yaml": "6" * 64},
                ),
            plan=SimpleNamespace(
                payload=SimpleNamespace(
                    model_roles={
                            "weak_extractor": SimpleNamespace(
                                model_id="weak-deployment"
                            ),
                            "judge": SimpleNamespace(model_id="judge-deployment"),
                    }
                )
            ),
        ),
    )
    configuration = _configuration(tmp_path)
    validator_calls: list[dict[str, object]] = []

    def validate(**kwargs: object) -> RunResult:
        validator_calls.append(kwargs)
        if validator_drift:
            raise AdmissionPausedError("baseline_artifact_content_mismatch")
        return result

    monkeypatch.setattr(run_020, "validate_baseline_result", validate)
    monkeypatch.setattr(run_020, "execution_plan_hash", lambda _value: _PLAN_HASH)

    if forged_run_identity:
        with pytest.raises(
            AdmissionPausedError,
            match="^baseline_artifact_commit_invalid$",
        ):
            _committer()(
                document=document,
                command="baseline-product",
                product_id=_SECOND_CANARY,
                execution_result=result,
                configuration=configuration,
            )
    elif validator_drift:
        with pytest.raises(
            AdmissionPausedError,
            match="^baseline_artifact_content_mismatch$",
        ):
            _committer()(
                document=document,
                command="baseline-product",
                product_id=_SECOND_CANARY,
                execution_result=result,
                configuration=configuration,
            )
    else:
        _committer()(
            document=document,
            command="baseline-product",
            product_id=_SECOND_CANARY,
            execution_result=result,
            configuration=configuration,
        )

    expected_calls = [] if forged_run_identity else [
        {
            "result": result,
            "run_root": tmp_path / "runs",
            "expected_source_root": product_dir.parent,
            "expected_product_dir": product_dir,
            "expected_run_id": target_digest,
            "expected_run_dir": run_dir,
            "expected_product_id": "1814",
            "expected_product_name": _SECOND_CANARY,
            "expected_line_key": "accident",
            "expected_schema_version": "v1.1",
            "expected_model_id": "weak-deployment",
            "expected_judge_mode": "gateway",
            "expected_admission_identity": admission_identity,
        }
    ]
    assert validator_calls == expected_calls


def test_d1_5_candidate_builder_forwards_fresh_decision_to_shared_deriver(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = cast(RunAdmissionDocument, object())
    ledger = cast(BudgetLedger, object())
    decision = _fresh_decision()
    configuration = _configuration(tmp_path)
    store = _RecordingArtifactStore()
    candidate = object.__new__(CanaryReviewCandidate)
    captured: dict[str, object] = {}

    def derive(**kwargs: object) -> CanaryReviewCandidate:
        captured.update(kwargs)
        return candidate

    monkeypatch.setattr(
        run_020,
        "CanaryArtifactStore",
        lambda: store,
        raising=False,
    )
    monkeypatch.setattr(
        run_020,
        "build_canary_review_candidate",
        derive,
        raising=False,
    )

    result = _candidate_builder()(
        document=document,
        ledger=ledger,
        execution_decision=decision,
        configuration=configuration,
    )

    assert result is candidate
    assert captured == {
        "document": document,
        "admission": decision,
        "ledger": ledger,
        "artifact_inspector": store,
    }


def test_d1_5_candidate_persister_writes_only_typed_candidate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configuration = _configuration(tmp_path)
    candidate = object.__new__(CanaryReviewCandidate)
    store = _RecordingArtifactStore()
    monkeypatch.setattr(
        run_020,
        "CanaryArtifactStore",
        lambda: store,
        raising=False,
    )

    _candidate_persister()(candidate=candidate, configuration=configuration)

    assert store.candidate_writes == [candidate]


def test_d1_5_candidate_persister_rejects_untyped_payload_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configuration = _configuration(tmp_path)
    store = _RecordingArtifactStore()
    monkeypatch.setattr(
        run_020,
        "CanaryArtifactStore",
        lambda: store,
        raising=False,
    )

    with pytest.raises(AdmissionPausedError, match="^canary_candidate_persist_invalid$"):
        _candidate_persister()(candidate=object(), configuration=configuration)

    assert store.candidate_writes == []


def test_d1_5_candidate_resumer_returns_false_only_when_state_is_fully_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = _resume_document()
    configuration = _configuration(tmp_path)
    ledger_impl = _ResumeLedger(None)
    ledger = cast(BudgetLedger, ledger_impl)
    store = _ResumeArtifactStore("missing")
    evaluator_impl = _ResumeEvaluator(_fresh_decision())
    evaluator = cast(ProductionAdmissionEvaluator, evaluator_impl)
    monkeypatch.setattr(run_020, "execution_plan_hash", lambda _value: _PLAN_HASH)
    monkeypatch.setattr(
        run_020,
        "budget_account_identity",
        lambda _run, _purpose: "c" * 64,
    )
    monkeypatch.setattr(
        run_020,
        "CanaryArtifactStore",
        lambda: store,
        raising=False,
    )
    monkeypatch.setattr(
        run_020,
        "_build_annotation_candidate",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("empty resume state must not build a candidate")
        ),
    )
    monkeypatch.setattr(
        run_020,
        "_persist_annotation_candidate",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("empty resume state must not persist a candidate")
        ),
    )

    resumed = _candidate_resumer()(
        product_id=_FIRST_CANARY,
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        configuration=configuration,
        candidate_admission_boundary=_candidate_boundary,
    )

    assert resumed is False
    assert ledger_impl.snapshot_calls == [("c" * 64, "annotation", _FIRST_CANARY)]
    assert store.inspect_calls == [(_PLAN_HASH, "annotation", _FIRST_CANARY)]
    assert evaluator_impl.calls == []
    assert ledger_impl.settle_calls == 0


def test_d1_5_candidate_resumer_revalidates_then_builds_and_persists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = _resume_document()
    configuration = _configuration(tmp_path)
    ledger_impl = _ResumeLedger("settled")
    ledger = cast(BudgetLedger, ledger_impl)
    store = _ResumeArtifactStore("exact")
    decision = _fresh_decision()
    evaluator_impl = _ResumeEvaluator(decision)
    evaluator = cast(ProductionAdmissionEvaluator, evaluator_impl)
    candidate = object.__new__(CanaryReviewCandidate)
    builder_calls: list[dict[str, object]] = []
    persister_calls: list[dict[str, object]] = []

    def build(**kwargs: object) -> CanaryReviewCandidate:
        builder_calls.append(kwargs)
        return candidate

    def persist(**kwargs: object) -> None:
        persister_calls.append(kwargs)

    monkeypatch.setattr(run_020, "execution_plan_hash", lambda _value: _PLAN_HASH)
    monkeypatch.setattr(
        run_020,
        "budget_account_identity",
        lambda _run, _purpose: "c" * 64,
    )
    monkeypatch.setattr(
        run_020,
        "CanaryArtifactStore",
        lambda: store,
        raising=False,
    )
    monkeypatch.setattr(run_020, "_build_annotation_candidate", build)
    monkeypatch.setattr(run_020, "_persist_annotation_candidate", persist)

    resumed = _candidate_resumer()(
        product_id=_FIRST_CANARY,
        document=document,
        evaluator=evaluator,
        ledger=ledger,
        configuration=configuration,
        candidate_admission_boundary=_candidate_boundary,
    )

    assert resumed is True
    assert evaluator_impl.calls == [(document, ledger)]
    assert builder_calls == [
        {
            "document": document,
            "ledger": ledger,
            "execution_decision": decision,
            "configuration": configuration,
        }
    ]
    assert persister_calls == [
        {"candidate": candidate, "configuration": configuration}
    ]
    assert ledger_impl.settle_calls == 0


def test_o8_t9_18_resume_candidate_evaluator_drift_blocks_before_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = _resume_document()
    configuration = _configuration(tmp_path)
    ledger_impl = _ResumeLedger("settled")
    ledger = cast(BudgetLedger, ledger_impl)
    store = _ResumeArtifactStore("exact")
    evaluator_impl = _ResumeEvaluator(_fresh_decision())
    evaluator = cast(ProductionAdmissionEvaluator, evaluator_impl)
    post_resume_calls: list[dict[str, object]] = []

    def candidate_admission_boundary(**kwargs: object) -> NoReturn:
        cast(ProductionAdmissionEvaluator, kwargs["evaluator"]).evaluate_execution(
            cast(RunAdmissionDocument, kwargs["document"]),
            cast(BudgetLedger, kwargs["ledger"]),
        )
        raise AdmissionPausedError("operational_finalization_blocked")

    monkeypatch.setattr(run_020, "execution_plan_hash", lambda _value: _PLAN_HASH)
    monkeypatch.setattr(
        run_020,
        "budget_account_identity",
        lambda _run, _purpose: "c" * 64,
    )
    monkeypatch.setattr(run_020, "CanaryArtifactStore", lambda: store)
    monkeypatch.setattr(
        run_020,
        "_build_annotation_candidate",
        lambda **kwargs: post_resume_calls.append(kwargs),
    )
    monkeypatch.setattr(
        run_020,
        "_persist_annotation_candidate",
        lambda **kwargs: post_resume_calls.append(kwargs),
    )

    with pytest.raises(
        AdmissionPausedError, match="operational_finalization_blocked"
    ):
        _candidate_resumer()(
            product_id=_FIRST_CANARY,
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            configuration=configuration,
            candidate_admission_boundary=candidate_admission_boundary,
        )

    assert evaluator_impl.calls == [(document, ledger)]
    assert post_resume_calls == []
    assert ledger_impl.settle_calls == 0


@pytest.mark.parametrize(
    ("reservation_state", "artifact_state", "non_initial"),
    [
        ("settled", "missing", False),
        ("settled", "drift", False),
        (None, "exact", False),
        ("settled", "exact", True),
    ],
)
def test_d1_5_candidate_resumer_rejects_ambiguous_or_unauthorized_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    reservation_state: str | None,
    artifact_state: str,
    non_initial: bool,
) -> None:
    document = _resume_document()
    configuration = _configuration(tmp_path)
    ledger_impl = _ResumeLedger(reservation_state)
    ledger = cast(BudgetLedger, ledger_impl)
    store = _ResumeArtifactStore(artifact_state)
    decision = _reviewed_decision() if non_initial else _fresh_decision()
    evaluator_impl = _ResumeEvaluator(decision)
    evaluator = cast(ProductionAdmissionEvaluator, evaluator_impl)
    post_resume_calls: list[dict[str, object]] = []
    monkeypatch.setattr(run_020, "execution_plan_hash", lambda _value: _PLAN_HASH)
    monkeypatch.setattr(
        run_020,
        "budget_account_identity",
        lambda _run, _purpose: "c" * 64,
    )
    monkeypatch.setattr(
        run_020,
        "CanaryArtifactStore",
        lambda: store,
        raising=False,
    )
    monkeypatch.setattr(
        run_020,
        "_build_annotation_candidate",
        lambda **kwargs: post_resume_calls.append(kwargs),
    )
    monkeypatch.setattr(
        run_020,
        "_persist_annotation_candidate",
        lambda **kwargs: post_resume_calls.append(kwargs),
    )

    expected_error: type[AdmissionPausedError] | type[AdmissionBlockedError] = (
        AdmissionBlockedError if non_initial else AdmissionPausedError
    )
    with pytest.raises(expected_error) as caught:
        _candidate_resumer()(
            product_id=_FIRST_CANARY,
            document=document,
            evaluator=evaluator,
            ledger=ledger,
            configuration=configuration,
            candidate_admission_boundary=_candidate_boundary,
        )

    if non_initial:
        assert isinstance(caught.value, AdmissionBlockedError)
        assert caught.value.result.state == "BLOCKED"
        assert caught.value.result.blockers[0].code == "candidate_authorization_invalid"
    else:
        assert isinstance(caught.value, AdmissionPausedError)
        assert caught.value.code == "candidate_resume_state_unsafe"

    assert post_resume_calls == []
    assert ledger_impl.settle_calls == 0
    expected_evaluations = 1 if non_initial else 0
    assert len(evaluator_impl.calls) == expected_evaluations
