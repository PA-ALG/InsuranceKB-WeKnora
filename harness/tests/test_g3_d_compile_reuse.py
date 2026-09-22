# Partial test doubles isolate the stated boundary; admission is tested separately.
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    validate_batch_candidate,
)
from insurance_harness.run_admission.g3_models import G3BoundedAdmissionPlanV1


def test_compile_reuse_binds_actual_results_and_rejects_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.knowledge_compiler import g3_d_compile_reuse as reuse

    candidate = validate_batch_candidate(
        (
            Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    )
    loaded = SimpleNamespace(
        request=candidate.request,
        model_result=candidate.model_compile_result,
        final_result=candidate.compile_result,
        terminal_sha256="b" * 64,
    )
    monkeypatch.setattr(reuse, "_load_successful_compile", lambda *args, **kwargs: loaded)
    receipt = reuse.build_compile_result_reuse(origin_admission_digest="a" * 64)
    reuse.validate_compile_result_reuse(
        receipt,
        request=candidate.request,
        model_result=candidate.model_compile_result,
        final_result=candidate.compile_result,
    )
    with pytest.raises(ValueError, match="binding"):
        reuse.validate_compile_result_reuse(
            receipt,
            request=candidate.request.model_copy(update={"request_sha256": "c" * 64}),
            model_result=candidate.model_compile_result,
            final_result=candidate.compile_result,
        )
    changed = candidate.model_compile_result.model_copy(
        update={
            "execution": candidate.model_compile_result.execution.model_copy(
                update={"run_id": "changed"}
            )
        }
    )
    with pytest.raises(ValueError, match="binding"):
        reuse.validate_compile_result_reuse(
            receipt,
            request=candidate.request,
            model_result=changed,
            final_result=candidate.compile_result,
        )


def test_review_runtime_reopens_compile_reuse_and_rejects_wrong_prior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime
    from insurance_harness.knowledge_compiler import g3_d_compile_reuse as reuse
    from insurance_harness.run_admission.g3_models import canonical_json

    candidate = validate_batch_candidate(
        (
            Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    )
    completed = SimpleNamespace(
        request=candidate.request,
        model_result=candidate.model_compile_result,
        final_result=candidate.compile_result,
        terminal_sha256="b" * 64,
    )
    monkeypatch.setattr(reuse, "_load_successful_compile", lambda *args, **kwargs: completed)
    receipt = reuse.build_compile_result_reuse(origin_admission_digest="a" * 64)
    artifacts = {
        contract: [canonical_json(value.model_dump(mode="json", round_trip=True))]
        for contract, value in (
            (receipt.contract, receipt),
            (candidate.request.contract, candidate.request),
            ("g3-d-model-compile-result.830.v1", candidate.model_compile_result),
            ("g3-d-final-compile-result.830.v1", candidate.compile_result),
        )
    }
    plan = SimpleNamespace(stage="D_REVIEW", prior_terminal_receipt_sha256="b" * 64)
    runtime._validate_g3_prior_stage_results(cast(G3BoundedAdmissionPlanV1, plan), artifacts)
    plan.prior_terminal_receipt_sha256 = "c" * 64
    with pytest.raises(ValueError, match="prior"):
        runtime._validate_g3_prior_stage_results(cast(G3BoundedAdmissionPlanV1, plan), artifacts)
    plan.stage = "D_COMPILE"
    with pytest.raises(ValueError, match="review"):
        runtime._validate_g3_prior_stage_results(cast(G3BoundedAdmissionPlanV1, plan), artifacts)
