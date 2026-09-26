"""Explicit dependencies isolate only affected candidates before final review."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from insurance_harness.product_ingestion.native_admission import (
    project_native_admission_response,
)
from insurance_harness.product_ingestion.native_admission_context import (
    render_native_admission_context,
)
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_native_admission import inputs, response

pytest_plugins = ("tests.product_ingestion.test_discovery",)
POLICY = "candidate-dependencies.830.v1"


def dependency_case(case: Any) -> tuple[Any, ...]:
    request, entity, snapshot, source = inputs(case)
    candidate = snapshot.candidates[0]
    snapshot = snapshot.model_copy(
        update={
            "candidates": [
                candidate.model_copy(update={"name": name, "slug": "concept/" + name})
                for name in ("uncertain", "independent", "dependent")
            ]
        }
    )
    ctx = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy=POLICY,
        isolation_enabled=True,
    )
    payload = response(ctx)
    original = payload["pages"][0]
    payload["contract"] = "native-knowledge-admission.830.v2"
    payload["pages"] = []
    for ref in ("b", "c"):
        page = deepcopy(original)
        page.update(member_ref=ref, stable_key="dependency-" + ref)
        payload["pages"].append(page)
    payload["decisions"] = [
        {
            "candidate_ref": "c1",
            "decision": "PENDING",
            "member_refs": [],
            "existing_target": None,
            "reason": "主体未决",
            "depends_on": [],
        },
        {
            "candidate_ref": "c2",
            "decision": "NEW",
            "member_refs": ["b"],
            "existing_target": None,
            "reason": "独立阅读用途",
            "depends_on": [],
        },
        {
            "candidate_ref": "c3",
            "decision": "NEW",
            "member_refs": ["c"],
            "existing_target": None,
            "reason": "需要主体确认",
            "depends_on": ["c1"],
        },
    ]
    return request, entity, snapshot, source, ctx, payload


def project(values: tuple[Any, ...]) -> Any:
    request, entity, snapshot, source, ctx, payload = values
    return project_native_admission_response(
        raw=json_bytes(payload),
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        context=ctx,
    )


def test_unresolved_candidate_does_not_discard_independent_knowledge(case: Any) -> None:
    values = dependency_case(case)
    projected = project(values)
    assert [p.stable_key for p in projected.output.pages] == ["dependency-b"]
    assert {r["candidate_ref"] for r in projected.isolated_candidates} == {"c1", "c3"}
    assert {r["member_id"] for r in projected.dispositions} == {projected.output.audit[0].key}
    assert projected.raw == json_bytes(values[-1])
    assert len(projected.response.decisions) == 3


@pytest.mark.parametrize("fault", ["missing", "unknown", "duplicate", "self"])
def test_dependencies_must_be_explicit_and_bound(case: Any, fault: str) -> None:
    values = dependency_case(case)
    decision = values[-1]["decisions"][1]
    if fault == "missing":
        del decision["depends_on"]
    else:
        decision["depends_on"] = {
            "unknown": ["other-window:c1"],
            "duplicate": ["c1", "c1"],
            "self": ["c2"],
        }[fault]
    with pytest.raises(ValueError):
        project(values)


@pytest.mark.parametrize("blocked", [False, True])
def test_dependency_cycle_is_preserved_or_isolated_as_a_whole(case: Any, blocked: bool) -> None:
    values = dependency_case(case)
    payload = values[-1]
    payload["decisions"][0].update(decision="REJECT")
    payload["decisions"][1]["depends_on"] = ["c3"]
    payload["decisions"][2]["depends_on"] = ["c2", "c1"] if blocked else ["c2"]
    assert len(project(values).output.pages) == (0 if blocked else 2)


def test_shared_member_propagates_an_unresolved_dependency(case: Any) -> None:
    values = dependency_case(case)
    payload = values[-1]
    payload["pages"] = payload["pages"][:1]
    payload["decisions"][2]["member_refs"] = ["b"]
    assert not project(values).output.pages


def test_legacy_context_and_response_do_not_claim_dependency_independence(case: Any) -> None:
    request, entity, snapshot, source, _, payload = dependency_case(case)
    ctx = render_native_admission_context(
        request=request, entity_id=entity, snapshot=snapshot, source=source
    )
    assert ctx["contract"] == "native-knowledge-admission-context.830.v1"
    assert "dependency_policy" not in ctx
    payload["contract"] = "native-knowledge-admission.830.v1"
    for row in payload["decisions"]:
        del row["depends_on"]
    result = project((request, entity, snapshot, source, ctx, payload))
    assert len(result.output.pages) == 2
    assert not result.isolated_candidates


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["single", "failed", "multiple", "rejected_prerequisite"])
async def test_coordinator_keeps_selected_candidates_but_fences_unknown_windows(
    case: Any,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    import json
    from types import SimpleNamespace

    from insurance_harness.product_ingestion import native_pipeline
    from insurance_harness.product_ingestion.native_admission_stage import (
        NativeAdmissionWindowOutcome,
    )
    from insurance_harness.product_ingestion.native_discovery_stage import (
        NativeDiscoveryCollection,
        NativeDiscoveryFailure,
    )

    request, entity, snapshot, source, _, payload = dependency_case(case)
    entry = next(
        e for e in request.resolution_inputs.corpus.entries if source.blocks[0] in e.blocks
    )
    request = request.model_copy(
        update={
            "resolution_inputs": request.resolution_inputs.model_copy(
                update={
                    "corpus": request.resolution_inputs.corpus.model_copy(
                        update={"entries": (entry,)}
                    )
                }
            )
        }
    )

    if mode == "rejected_prerequisite":
        payload["decisions"][0]["decision"] = "REJECT"

    async def collect(**kwargs: Any) -> Any:
        return NativeDiscoveryCollection(
            mode != "failed",
            (snapshot, snapshot) if mode in {"multiple", "rejected_prerequisite"} else (snapshot,),
            (NativeDiscoveryFailure(snapshot.knowledge_id, 1, "cite", "unknown"),)
            if mode == "failed"
            else (),
            (),
        )

    async def admit(**kwargs: Any) -> Any:
        assert kwargs["isolation_enabled"] is (mode == "single")
        ctx = render_native_admission_context(
            request=request,
            entity_id=entity,
            snapshot=snapshot,
            source=source,
            dependency_policy=kwargs["dependency_policy"],
            isolation_enabled=kwargs["isolation_enabled"],
        )
        return NativeAdmissionWindowOutcome(
            project((request, entity, snapshot, source, ctx, payload)), (), None
        )

    monkeypatch.setattr(native_pipeline, "collect_native_discovery", collect)
    monkeypatch.setattr(native_pipeline, "run_native_admission_window", admit)
    settings = SimpleNamespace(
        policy="native-candidates.830.v1",
        dependency_policy=POLICY,
        language="zh-CN",
        granularity="exhaustive",
        purpose="",
        allow_knowledge_updates=False,
    )
    result = await native_pipeline.run_native_discovery_stage(
        service=SimpleNamespace(configuration=SimpleNamespace(native_discovery=settings)),
        artifacts=SimpleNamespace(),
        scope=SimpleNamespace(),
        run=SimpleNamespace(run_id="run", retry_of_run_id=None),
        stage=SimpleNamespace(dependency_sha256="a" * 64),
        job=SimpleNamespace(),
        request=request,
        sources={snapshot.knowledge_id: source},
    )
    rows = {
        a.artifact_kind: json.loads(a.payload) for a in result.drafts if a.artifact_key == "product"
    }
    assert bool(rows["discovery_candidates"]["output"]["pages"]) is (mode == "single")
    assert rows["discovery_summary"]["state"] == ("FAILED" if mode == "failed" else "PENDING")
    assert rows["discovery_summary"]["pending_candidate_count"] >= 1
    assert not rows["discovery_summary"]["native_coverage"]["complete"]
    if mode == "single":
        assert len(rows["discovery_candidates"]["dependency_selection"]["isolated_candidates"]) == 2
        assert "native_dependency_selection" in rows


def test_partial_review_acceptance_keeps_unresolved_status_visible() -> None:
    import json

    from insurance_harness.product_ingestion.api import combine_discovery_summaries

    result = json.loads(
        combine_discovery_summaries(
            json_bytes(
                {
                    "state": "PENDING",
                    "dependency_policy": POLICY,
                    "pending_candidate_count": 2,
                    "reason_codes": ["NATIVE_DISCOVERY_PENDING"],
                    "accepted_member_count": 0,
                }
            ),
            json_bytes(
                {
                    "state": "ACCEPTED",
                    "reason_codes": ["DISCOVERY_ACCEPTED"],
                    "accepted_member_count": 1,
                }
            ),
        )
    )
    assert result["state"] == "PENDING"
    assert "NATIVE_CANDIDATES_ISOLATED" in result["reason_codes"]
    assert result["accepted_member_count"] == 1


def test_dependency_policy_is_explicit_and_omitted_for_legacy_configuration() -> None:
    from insurance_harness.product_ingestion.configuration import NativeDiscoverySettings

    values = dict(
        policy="native-candidates.830.v1", language="zh-CN", granularity="standard", purpose=""
    )
    assert "dependency_policy" not in NativeDiscoverySettings(**values).model_dump()
    assert NativeDiscoverySettings(**values, dependency_policy=POLICY).dependency_policy == POLICY
    with pytest.raises(ValueError):
        NativeDiscoverySettings(**values, dependency_policy="unversioned")


def test_selection_requires_whole_run_eligibility(case: Any) -> None:
    request, entity, snapshot, source, _, payload = dependency_case(case)
    ctx = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy=POLICY,
    )
    assert ctx["isolation_enabled"] is False
    result = project((request, entity, snapshot, source, ctx, payload))
    assert len(result.output.pages) == 2
    assert result.dependency_selection is None


def test_review_sees_full_selection_and_rejects_changed_receipt(case: Any) -> None:
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        compile_output_hash_g3,
    )
    from insurance_harness.product_ingestion.discovery import (
        build_discovery_exclusion_index,
        independent_discovery_review_policy,
        render_independent_discovery_review_context,
    )

    values = dependency_case(case)
    request, entity = values[:2]
    result = project(values)
    candidates = {
        "output": result.output.model_dump(mode="json"),
        "sources": values[-2]["source_options"],
        "dispositions": result.dispositions,
        "dependency_selection": result.dependency_selection,
    }

    def render(**extra: Any) -> Any:
        return render_independent_discovery_review_context(
            request=request,
            entity_id=entity,
            exclusion_index=build_discovery_exclusion_index(request, entity),
            discovery_candidates=candidates,
            final_composed_output=result.output,
            final_composed_output_hash=compile_output_hash_g3(result.output),
            **extra,
        )

    context = render()
    assert context["contract"] == "product-discovery-review-context.830.v6"
    receipt = context["dependency_selection"]
    assert len(receipt["response"]["decisions"]) == 3
    assert receipt["retained_candidates"] == ["c2"]
    assert receipt["admission_context"]["native_candidates"][0]["name"] == "uncertain"
    assert (
        independent_discovery_review_policy(result.output, dependency_selection=True)[0]
        == "g3-dependency-discovery-review"
    )
    with pytest.raises(ValueError):
        render(context_version="product-discovery-review-context.830.v5")
    candidates["dependency_selection"]["retained_candidates"] = ["c3"]
    with pytest.raises(ValueError):
        render()


@pytest.mark.parametrize("verified", [False, True])
def test_partial_publication_is_only_confirmed_by_exact_release(verified: bool) -> None:
    from insurance_harness.product_ingestion.api import _discovery_summary_projection

    raw = json_bytes(
        {
            "state": "PENDING",
            "dependency_policy": POLICY,
            "pending_candidate_count": 2,
            "reused": False,
            "reason_codes": ["NATIVE_CANDIDATES_ISOLATED"],
            "accepted_member_count": 1,
            "coverage": None,
            "counts": {
                "proposed_new": 2,
                "duplicate": 0,
                "update_proposal": 0,
                "rejected": 0,
                "published": 0,
            },
        }
    )
    view = _discovery_summary_projection(raw, publication_verified=verified)
    assert view["state"] == "PENDING"
    assert view["accepted_member_count"] == 1
    assert view["counts"]["published"] == int(verified)
    assert view["published_confirmed"] is verified


@pytest.mark.parametrize("mode", ["healthy", "definition_blocked", "orphan", "shared_owner"])
def test_structural_dependencies_reach_fixed_point(case: Any, mode: str) -> None:
    values = dependency_case(case)
    payload = values[-1]
    template = deepcopy(payload["pages"][0])
    for key in ("stable_key", "concept_refs", "conditions", "exceptions", "valid_time"):
        template.pop(key)
    template.update(member_ref="d", canonical_key="reading-order", sense_key="general", aliases=[])
    payload["definitions"] = [template]
    payload["pages"][0]["concept_refs"] = ["d"]
    payload["decisions"][1]["member_refs"] = ["b", "d"]
    payload["decisions"][2]["depends_on"] = []
    if mode == "definition_blocked":
        payload["decisions"][1]["depends_on"] = ["c1"]
        payload["pages"][1]["concept_refs"] = ["d"]
    elif mode == "orphan":
        payload["decisions"][1]["member_refs"] = ["d"]
        payload["decisions"][2]["member_refs"] = ["b", "c"]
        payload["decisions"][2]["depends_on"] = ["c1"]
    elif mode == "shared_owner":
        payload["decisions"][2]["member_refs"].append("d")
        payload["decisions"][2]["depends_on"] = ["c1"]
    result = project(values)
    assert bool(result.output.definitions) is (mode == "healthy")
    assert len(result.output.pages) == (2 if mode == "healthy" else 0)
    payload["decisions"].reverse()
    reordered = project(values)
    assert result.output == reordered.output
    assert result.isolated_candidates == reordered.isolated_candidates
    assert (
        result.dependency_selection["effective_dependencies"]
        == reordered.dependency_selection["effective_dependencies"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "new",
        "replay",
        "old_prompt",
        "reject_dependency",
        "pending_dependency",
        "auto_scope",
        "wide_parent",
        "scope_conflict",
    ],
)
async def test_final_review_binds_complete_plan_and_selected_final_hash(
    case: Any, mode: str
) -> None:
    import json
    from types import SimpleNamespace

    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        compile_output_hash_g3,
    )
    from insurance_harness.product_ingestion import discovery
    from insurance_harness.product_ingestion.discovery_composition import compose_discovery_review
    from insurance_harness.product_ingestion.discovery_stage import (
        run_independent_discovery_final_review,
    )
    from tests.product_ingestion.test_discovery_replay_custody import _parent_call, _service

    values = dependency_case(case)
    request, entity = values[:2]
    result = project(values)
    output = result.output
    candidates = {
        "output": output.model_dump(mode="json"),
        "sources": values[-2]["source_options"],
        "dispositions": result.dispositions,
        "dependency_selection": result.dependency_selection,
    }
    context = discovery.render_independent_discovery_review_context(
        request=request,
        entity_id=entity,
        exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
        discovery_candidates=candidates,
        final_composed_output=output,
        final_composed_output_hash=compile_output_hash_g3(output),
        max_context_bytes=300000,
    )
    decision = {"reject_dependency": "REJECT", "pending_dependency": "NEEDS_HUMAN"}.get(
        mode, "ACCEPT"
    )
    response = {
        "contract": "product-discovery-review.830.v1",
        "review": {
            "request_hash": context["request_hash"],
            "output_hash": context["output_hash"],
            "decision": "PASS",
            "reasons": [],
            "page_scores": {
                identity: dict(
                    business_value=25,
                    reuse=20,
                    evidence_quality=0,
                    definability=15,
                    novel_identity=10,
                    name_stability=10,
                )
                for identity in context["review_member_ids"]
            },
        },
        "disposition_checks": [
            {
                "candidate_id": r["candidate_id"],
                "decision": decision,
                "reason": "dependency assessment",
            }
            for r in result.dispositions
        ],
    }
    raw = json_bytes({"choices": [{"message": {"content": json.dumps(response)}}]})
    prompt = discovery.DEPENDENCY_DISCOVERY_REVIEW_PROMPT
    service = _service(
        role="verify", purpose="g3-dependency-discovery-review", prompt=prompt, new_raw=raw
    )
    record = _parent_call(
        stage_key="compilation",
        operation="independent-discovery-final-review-" + context["output_hash"],
        content=json_bytes(context),
        prompt=discovery.PROVENANCE_DISCOVERY_REVIEW_PROMPT if mode == "old_prompt" else prompt,
        raw=raw,
    )
    record.diagnostic = None
    if mode == "wide_parent":
        wide_context = discovery.render_independent_discovery_review_context(
            request=request,
            entity_id=None,
            exclusion_index={
                b.entity_id: discovery.build_discovery_exclusion_index(request, b.entity_id)
                for b in request.entity_bindings
            },
            discovery_candidates=candidates,
            final_composed_output=output,
            final_composed_output_hash=context["output_hash"],
            max_context_bytes=300000,
        )
        record = _parent_call(
            stage_key="compilation",
            operation="independent-discovery-final-review-" + context["output_hash"],
            content=json_bytes(wide_context),
            prompt=prompt,
            raw=raw,
        )
        record.diagnostic = None
    parent = mode in {"replay", "old_prompt", "wide_parent"}
    outcome = await run_independent_discovery_final_review(
        service=service,
        artifacts=SimpleNamespace(list_stage_calls=lambda **kw: [record] if parent else []),
        scope=service.configuration.model.scope,
        run=SimpleNamespace(run_id="child", retry_of_run_id="parent-run" if parent else None),
        stage=SimpleNamespace(dependency_sha256="b" * 64),
        job=object(),
        request=request,
        discovery_candidates=candidates,
        final_composed_output=output,
        final_composed_output_hash=context["output_hash"],
        entity_id=(
            "other"
            if mode == "scope_conflict"
            else None
            if mode in {"auto_scope", "wide_parent"}
            else entity
        ),
    )
    assert outcome.decision == {
        "old_prompt": "FAILED",
        "scope_conflict": "FAILED",
        "reject_dependency": "REJECTED",
        "pending_dependency": "PENDING",
    }.get(mode, "ACCEPTED"), outcome.summary
    if mode == "scope_conflict":
        assert not service.model_executor.calls
    if outcome.decision == "ACCEPTED":
        compose_discovery_review(
            request=request,
            final_output=output,
            free_output=output,
            outcome=outcome,
            run_id="child",
        )
        assert len(service.model_executor.calls) == (0 if mode == "replay" else 1)
        if service.model_executor.calls:
            sent = json.loads(service.model_executor.calls[0]["content"])
            assert sent == context
            assert sent["dependency_selection"] == result.dependency_selection
            assert sent["existing_knowledge"]["definitions"]
            assert sent["exclusion_index"]["existing_concepts"]
    else:
        with pytest.raises(ValueError):
            compose_discovery_review(
                request=request,
                final_output=output,
                free_output=output,
                outcome=outcome,
                run_id="child",
            )


def test_failed_update_keeps_previous_page_in_final_composition(case: Any) -> None:
    from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput
    from insurance_harness.product_ingestion.discovery_composition import merge_discovery_delta
    from tests.test_batch_concept_compile_830_g3_incremental import PORTABLE_PARENT, _published_base

    request, entity, snapshot, source, ctx, payload = dependency_case(case)
    prior_values = (request, entity, snapshot, source, ctx, deepcopy(payload))
    prior_values[-1]["decisions"][2]["depends_on"] = []
    old = next(p for p in project(prior_values).output.pages if p.stable_key == "dependency-c")
    base = _published_base(compiler, PORTABLE_PARENT)
    request = request.model_copy(
        update={
            "knowledge_update_policy": "explicit-same-identity.830.v1",
            "unknown_field_key_alignments": (),
            "base_request": base.model_copy(update={"existing_pages": (*base.existing_pages, old)}),
        }
    )
    ctx = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy=POLICY,
        isolation_enabled=True,
    )
    page = payload["pages"][1]
    page.update(
        action="UPDATE",
        expected_revision_sha256=next(
            p["revision_sha256"]
            for p in ctx["existing_knowledge"]["pages"]
            if p["stable_key"] == old.stable_key
        ),
        body="重新编写的资料说明。",
    )
    page["content_provenance"]["segments"][0]["text"] = page["body"]
    payload["decisions"][2]["decision"] = "UPDATE"
    result = project((request, entity, snapshot, source, ctx, payload))
    field_output = CompileOutput(
        request_hash=compiler.compile_request_hash_g3(request.base_request), fields=()
    )
    field_delta = compiler.record_model_compile(
        request,
        field_output,
        run_id="fields",
        implementation="test",
        raw=json_bytes(field_output).decode(),
    )
    merged = merge_discovery_delta(
        request=request,
        field_delta=field_delta,
        free_output=result.output,
        run_id="isolated-update",
    )
    final = compiler.compose_batch_output(request, merged)
    assert old in final.pages
    assert any(p.stable_key == "dependency-b" for p in final.pages)
    assert not any(p.body == page["body"] for p in final.pages)


@pytest.mark.parametrize(
    "fault",
    [
        "healthy",
        "receipt",
        "selected_entity",
        "missing_owner",
        "context_entity",
        "context_version",
        "page_entity",
        "page_version",
        "mixed_pages",
        "explicit_entity",
        "unbound",
        "duplicate_binding",
    ],
)
def test_native_review_scope_rejects_inconsistent_ownership(case: Any, fault: str) -> None:
    import hashlib

    from insurance_harness.product_ingestion import native_dependency_selection as selection_api

    values = dependency_case(case)
    request, entity = values[:2]
    result = project(values)
    selection = deepcopy(result.dependency_selection)
    output = result.output
    explicit = None
    if fault == "receipt":
        selection["selection_sha256"] = "0" * 64
    elif fault == "selected_entity":
        selection["entity_id"] = "other"
    elif fault == "missing_owner":
        selection["admission_context"].pop("entity")
        selection["admission_context_sha256"] = hashlib.sha256(
            json_bytes(selection["admission_context"])
        ).hexdigest()
    elif fault in {"context_entity", "context_version"}:
        key = "entity_id" if fault == "context_entity" else "entity_version"
        selection["admission_context"]["entity"][key] = "other"
        selection["admission_context_sha256"] = hashlib.sha256(
            json_bytes(selection["admission_context"])
        ).hexdigest()
    elif fault in {"page_entity", "page_version", "mixed_pages"}:
        key = "entity_version" if fault == "page_version" else "entity_id"
        pages = (output.pages[0].model_copy(update={key: "other"}),)
        if fault == "mixed_pages":
            pages = (*output.pages, *pages)
        output = output.model_copy(update={"pages": pages})
        from insurance_harness.knowledge_compiler.concept_compile_830_g2 import free_page_id

        selection["retained_member_ids"] = [free_page_id(page) for page in output.pages]
    elif fault == "explicit_entity":
        explicit = "other"
    elif fault == "unbound":
        request = request.model_copy(
            update={
                "entity_bindings": tuple(
                    b for b in request.entity_bindings if b.entity_id != entity
                )
            }
        )
    elif fault == "duplicate_binding":
        binding = next(b for b in request.entity_bindings if b.entity_id == entity)
        request = request.model_copy(
            update={"entity_bindings": (*request.entity_bindings, binding)}
        )
    if fault != "receipt":
        selection["selection_sha256"] = hashlib.sha256(
            json_bytes({k: v for k, v in selection.items() if k != "selection_sha256"})
        ).hexdigest()
    kwargs = dict(request=request, candidate_output=output, selection=selection, entity_id=explicit)
    if fault == "healthy":
        assert selection_api.resolve_native_review_entity(**kwargs) == entity
    else:
        with pytest.raises(ValueError):
            selection_api.resolve_native_review_entity(**kwargs)
