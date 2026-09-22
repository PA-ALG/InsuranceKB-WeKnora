"""Local review reuse preserves original evidence and exact candidate partitions."""

import copy
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime
from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_json_bytes_830_g3
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCandidateBundle830G3V1,
    compile_output_hash_g3,
    validate_batch_candidate,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import ReviewOutput
from insurance_harness.model_policy import ModelIdentity
from insurance_harness.run_admission.g3_models import (
    G3BoundedAdmissionPlanV1,
    G3CallPlanV1,
    G3ProviderUsageV1,
    canonical_json,
)

ReviewCase = tuple[
    BatchConceptCandidateBundle830G3V1,
    ModelIdentity,
    tuple[runtime.G3DReviewWindow, ...],
    tuple[runtime.G3DReviewWindowContext, ...],
]


@pytest.fixture(scope="module")
def review_case() -> ReviewCase:
    candidate = validate_batch_candidate(
        (
            Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    )
    identity = ModelIdentity(
        provider="g3-user-gateway",
        family="gemini",
        deployment_id="gemini-3.7-flash-medium",
        role="verify",
        policy_version="g3-user-gemini-gateway-v1",
    )
    request, output = candidate.request, candidate.compile_result.output
    windows = runtime.derive_gemini_d_review_windows(request, output)
    scope = runtime._g3_review_scope(request, output)
    contexts = tuple(
        runtime._render_g3_bounded_review_context(request, output, w, scope) for w in windows
    )
    return candidate, identity, windows, contexts


def test_review_local_comparison_removes_only_global_bindings(review_case: ReviewCase) -> None:
    from insurance_harness.knowledge_compiler.g3_d_review_reuse import local_review_context

    candidate, _, _, contexts = review_case
    before = contexts[0]
    after = copy.deepcopy(before)
    for key in ("request_sha256", "base_request_hash", "output_hash"):
        after[key] = "f" * 64
    after["window"]["window_id"] = "other-derived-window"
    field_count = after["local_whole_candidate_binding"]["field_count"]
    assert isinstance(field_count, int)
    after["local_whole_candidate_binding"]["field_count"] = field_count + 1
    assert local_review_context(candidate.request, before) == local_review_context(
        candidate.request, after
    )
    for key in (
        "review_instructions",
        "field_descriptors",
        "source_options",
        "candidate_partition",
    ):
        changed: dict[str, Any] = copy.deepcopy(dict(after))
        changed[key] = () if key != "candidate_partition" else {}
        with pytest.raises(ValueError):
            # Invalid or different local content must never compare equal.
            if local_review_context(candidate.request, before) != local_review_context(
                candidate.request, cast(runtime.G3DReviewWindowContext, changed)
            ):
                raise ValueError("local difference")


def test_review_reference_normalization_preserves_scoped_source_and_policy(
    review_case: ReviewCase,
) -> None:
    from insurance_harness.knowledge_compiler.g3_d_review_reuse import local_review_context

    candidate, _, windows, contexts = review_case
    # Isolate request-derived reference changes; full request validation is the admission boundary.
    rebound_request = candidate.request.model_copy(update={"request_sha256": "f" * 64})
    output = candidate.compile_result.output
    rebound_windows = runtime.derive_gemini_d_review_windows(rebound_request, output)
    scope = runtime._g3_review_scope(rebound_request, output)
    for index in (0, len(windows) - 1):
        before = contexts[index]
        target = next(
            w
            for w in rebound_windows
            if w["entity_id"] == windows[index]["entity_id"]
            and w["field_keys"] == windows[index]["field_keys"]
            and w["kind"] == windows[index]["kind"]
            and {scope["targets"][ref]["member_id"] for ref in w["review_refs"]}
            == {row["member_id"] for row in before["review_targets"]}
        )
        after = runtime._render_g3_bounded_review_context(rebound_request, output, target, scope)
        assert local_review_context(candidate.request, before) == local_review_context(
            rebound_request, after
        )
        changed = copy.deepcopy(after)
        changed["source_options"][0]["spans"][0]["quote"] += "forged"
        with pytest.raises(ValueError, match="span"):
            local_review_context(rebound_request, changed)
        changed = copy.deepcopy(after)
        changed["response_schema"]["description"] = "changed review semantics"
        assert local_review_context(candidate.request, before) != local_review_context(
            rebound_request, changed
        )


def fake_origin(
    monkeypatch: pytest.MonkeyPatch, review_case: ReviewCase, *, reject_index: int | None = None
) -> tuple[ModuleType, SimpleNamespace]:
    from insurance_harness.knowledge_compiler import g3_d_review_reuse as reuse

    candidate, identity, windows, contexts = review_case
    prompt = (
        Path(runtime.__file__).parent / "prompts" / runtime.g3_d_template_name("D_REVIEW", identity)
    ).read_bytes()
    route = SimpleNamespace(identity=identity, thinking=True, temperature_micros=0)
    body_plan = SimpleNamespace(routing_lock=route)
    calls, records = [], {}
    targets = {
        row["review_ref"]: row["member_id"]
        for row in runtime._g3_d_review_targets(candidate.request, candidate.compile_result.output)
    }
    for i, (window, context) in enumerate(zip(windows, contexts, strict=True)):
        call = SimpleNamespace(
            call_id=f"review-{i}",
            ordinal=i,
            window_id=window["window_id"],
            material_ids=tuple(window["material_ids"]),
            identity=identity,
            endpoint_origin="http://8.148.158.241:3131",
            endpoint_path="/v1/chat/completions",
            output_token_ceiling=16384,
        )
        raw = canonical_json(
            dict(
                contract="g3-d-review-semantic-references.local.v1",
                decision="REJECT" if i == reject_index else "PASS",
                reasons=[],
                scores=[
                    dict(
                        review_ref=ref,
                        business_value=20,
                        reuse=20,
                        evidence_quality=20,
                        definability=15,
                        novel_identity=10,
                        name_stability=10,
                    )
                    for ref in window["review_refs"]
                ],
            )
        )
        projected = runtime._project_g3_exact_review_response(
            raw, candidate.request, candidate.compile_result.output, window, targets
        )
        record = SimpleNamespace(
            semantic_bytes=raw,
            response_bytes=raw,
            request_bytes=runtime.g3_openai_request_bytes(
                plan=cast(G3BoundedAdmissionPlanV1, body_plan),
                call=cast(G3CallPlanV1, call),
                system=prompt.decode(),
                user=batch_json_bytes_830_g3(context).decode(),
            ),
            terminal=SimpleNamespace(
                status="SUCCESS",
                receipt_sha256=f"{i + 1:064x}",
                projection_sha256=runtime._gemini_d_review_window_projection_hash(
                    window["window_id"], projected
                ),
            ),
            observed_usage=G3ProviderUsageV1(
                prompt_tokens=100, completion_tokens=20, total_tokens=120, usage_verified=True
            ),
        )
        calls.append(call)
        records[call.call_id] = record
    plan = SimpleNamespace(
        routing_lock=route,
        request_manifest=SimpleNamespace(calls=tuple(calls)),
        chain_manifest_hash="b" * 64,
        parent_authorization_digest="c" * 64,
    )
    origin = SimpleNamespace(
        plan=cast(G3BoundedAdmissionPlanV1, plan),
        request=candidate.request,
        output=candidate.compile_result.output,
        terminal=SimpleNamespace(
            status="FAILED" if reject_index is not None else "SUCCESS", receipt_sha256="d" * 64
        ),
        records=records,
    )
    monkeypatch.setattr(reuse, "_load_origin_review", lambda *a, **k: origin)
    return reuse, origin


def test_reuse_skips_reject_and_aggregates_exact_remaining_partition(
    monkeypatch: pytest.MonkeyPatch, review_case: ReviewCase
) -> None:
    reuse, origin = fake_origin(monkeypatch, review_case, reject_index=0)
    candidate, identity, windows, _ = review_case
    manifest = reuse.build_review_result_reuse(
        origin_admission_digest="a" * 64,
        current_request=candidate.request,
        current_output=candidate.compile_result.output,
    )
    assert len(manifest.entries) == len(windows) - 1
    assert manifest.origin_stage_status == "FAILED"
    verified: dict[str, ReviewOutput] = reuse.validate_review_result_reuse(
        manifest,
        current_request=candidate.request,
        current_output=candidate.compile_result.output,
        current_identity=identity,
    )
    remaining = reuse.derive_remaining_review_windows(
        candidate.request, candidate.compile_result.output, manifest
    )
    assert len(remaining) == 1 and remaining[0] == windows[0]
    raw = canonical_json(
        dict(
            contract="g3-d-review-semantic-references.local.v1",
            decision="PASS",
            reasons=[],
            scores=[],
        )
    )
    assert windows[0]["field_keys"]
    new = runtime.project_gemini_d_review_window_response(
        raw, candidate.request, candidate.compile_result.output, windows[0]
    )
    result = reuse.aggregate_reused_review_outputs(
        candidate.request, candidate.compile_result.output, new_outputs=(new,), reused=verified
    )
    assert result.decision == "PASS"
    # Prepare parses the explicit reuse artifact, then Candidate receives complete coverage.
    from datetime import UTC, datetime

    artifacts = {
        contract: [canonical_json(value.model_dump(mode="json", round_trip=True))]
        for contract, value in (
            (manifest.contract, manifest),
            (candidate.request.contract, candidate.request),
            ("g3-d-model-compile-result.830.v1", candidate.model_compile_result),
            ("g3-d-final-compile-result.830.v1", candidate.compile_result),
        )
    }
    seen = []

    def verified_once(*args: object, **kwargs: object) -> dict[str, ReviewOutput]:
        seen.append(kwargs["current_identity"])
        return verified

    monkeypatch.setattr(reuse, "validate_review_result_reuse", verified_once)
    plan = SimpleNamespace(
        stage="D_REVIEW",
        run_id="review-reuse-fixture",
        request_manifest=SimpleNamespace(calls=(SimpleNamespace(identity=identity),)),
    )
    prepared = runtime._parse_g3_stage_artifacts(cast(G3BoundedAdmissionPlanV1, plan), artifacts)
    assert seen == [identity] and prepared.recovery_windows == remaining
    monkeypatch.setattr(runtime, "_failed_stage_terminal", lambda **kwargs: None)
    final_review, rebuilt = runtime._finalize_gemini_d_review_windows(
        request=candidate.request,
        model_compile_result=candidate.model_compile_result,
        final_compile_result=candidate.compile_result,
        outputs=(new,),
        plan=cast(G3BoundedAdmissionPlanV1, plan),
        admission_digest="a" * 64,
        call_dir="unused-fixture",
        call_terminals=(),
        started_at=datetime.now(UTC),
        prepared=prepared,
    )
    assert final_review.output == result
    assert validate_batch_candidate(batch_json_bytes_830_g3(rebuilt)) == rebuilt
    import importlib.util
    import sys

    path = (
        Path(__file__).parents[2]
        / "docs/insurance-kb/evidence/830-g3"
        / "g3_actual_model_plan_materializer_v1.py"
    )
    spec = importlib.util.spec_from_file_location("review_reuse_materializer_fixture", path)
    assert spec is not None and spec.loader is not None
    materializer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = materializer
    spec.loader.exec_module(materializer)
    captured: dict[str, Any] = {}

    def fixed(*args: object, **kwargs: object) -> dict[str, tuple[()]]:
        captured.update(kwargs)
        return {"artifacts": (), "calls": ()}

    monkeypatch.setattr(materializer, "_stage_fixed", fixed)
    monkeypatch.setattr(materializer, "_plan", lambda *a, **k: "fixture-plan")
    call = SimpleNamespace(
        stage="D_REVIEW",
        ordinal=0,
        call_id="new-review",
        window_id=remaining[0]["window_id"],
        material_ids=tuple(remaining[0]["material_ids"]),
    )
    built = materializer.materialize_product_d_inputs(
        options=SimpleNamespace(identities=(SimpleNamespace(stage="D_REVIEW", identity=identity),)),
        chain=None,
        parent=None,
        parent_digest="1" * 64,
        protocol_seed=None,
        request=candidate.request,
        configured=(call,),
        stage="D_REVIEW",
        model_result=candidate.model_compile_result,
        final_result=candidate.compile_result,
        prior_terminal_sha="2" * 64,
        review_reuse=manifest,
    )
    assert built["windows"] == remaining and len(captured["context_raws"]) == 1
    assert manifest.contract in {row[0] for row in captured["typed"]}
    record = origin.records["review-1"]
    original_body = record.request_bytes
    changed_body = runtime._unique_json_bytes(original_body)
    assert isinstance(changed_body, dict)
    messages = changed_body["messages"]
    assert isinstance(messages, list)
    messages[0]["content"] += "changed policy"
    record.request_bytes = canonical_json(changed_body)
    with pytest.raises(ValueError, match="prompt/context"):
        reuse.build_review_result_reuse(
            origin_admission_digest="a" * 64,
            current_request=candidate.request,
            current_output=candidate.compile_result.output,
            origin_call_ids=("review-1",),
        )
    record.request_bytes = original_body
    with pytest.raises(ValueError, match="PASS"):
        reuse.build_review_result_reuse(
            origin_admission_digest="a" * 64,
            current_request=candidate.request,
            current_output=candidate.compile_result.output,
            origin_call_ids=("review-0",),
        )
    with pytest.raises(ValueError, match="duplicat"):
        reuse.derive_remaining_review_windows(
            candidate.request, candidate.compile_result.output, (manifest, manifest)
        )
    with pytest.raises(ValueError, match="count"):
        reuse.aggregate_reused_review_outputs(
            candidate.request, candidate.compile_result.output, new_outputs=(), reused=verified
        )


def test_changed_one_field_reuses_only_unaffected_windows(
    monkeypatch: pytest.MonkeyPatch, review_case: ReviewCase
) -> None:
    reuse, _ = fake_origin(monkeypatch, review_case)
    candidate, identity, windows, _ = review_case
    selected = windows[0]
    key = (selected["entity_id"], selected["field_keys"][0])
    old = candidate.compile_result.output
    changed = old.model_copy(
        update={
            "fields": tuple(
                row.model_copy(update={"valid_time": "changed effective term"})
                if (row.entity_id, row.field_key) == key
                else row
                for row in old.fields
            )
        }
    )
    manifest = reuse.build_review_result_reuse(
        origin_admission_digest="a" * 64, current_request=candidate.request, current_output=changed
    )
    remaining = reuse.derive_remaining_review_windows(candidate.request, changed, manifest)
    assert len(remaining) == 1 and key[1] in remaining[0]["field_keys"]
    outputs = reuse.validate_review_result_reuse(
        manifest,
        current_request=candidate.request,
        current_output=changed,
        current_identity=identity,
    )
    assert all(row.output_hash == compile_output_hash_g3(changed) for row in outputs.values())
    with pytest.raises(ValueError, match="local"):
        reuse.build_review_result_reuse(
            origin_admission_digest="a" * 64,
            current_request=candidate.request,
            current_output=changed,
            origin_call_ids=("review-0",),
        )
    with pytest.raises(ValueError, match="binding"):
        reuse.validate_review_result_reuse(
            manifest,
            current_request=candidate.request,
            current_output=old,
            current_identity=identity,
        )
