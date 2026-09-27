"""Multiwindow closure must keep explicit local-to-formal identity bindings."""

from __future__ import annotations

from typing import Any, cast

import pytest

from insurance_harness.jobs.models import JobSnapshot
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import free_page_id
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.composition import ProductScopeServices
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductScope,
    StageSnapshot,
)
from insurance_harness.product_ingestion.native_admission_context import (
    render_native_admission_context,
)
from tests.product_ingestion.test_native_dependency_selection import dependency_case, project

pytest_plugins = ("tests.product_ingestion.test_discovery",)


def test_nonisolating_projection_retains_complete_dependency_domain(case: Any) -> None:
    request, entity, snapshot, source, _, payload = dependency_case(case)
    context = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy="candidate-dependencies.830.v1",
        isolation_enabled=False,
    )
    projection = project((request, entity, snapshot, source, context, payload))
    assert projection.dependency_selection is None
    domain = getattr(projection, "dependency_domain", None)
    assert domain is not None, "nonisolating window discarded its validated dependency domain"
    assert domain["contract"] == "native-window-dependency-domain.830.v1"
    assert domain["admission_context"] == context
    assert domain["retained_candidates"] == ["c2"]
    assert {row["member_ref"] for row in domain["members"]} == {"b", "c"}
    assert {row["member_id"] for row in domain["members"]} == {
        free_page_id(page) for page in projection.output.pages
    }
    assert {row["candidate_ref"] for row in domain["review_bindings"]} == {"c1", "c2", "c3"}


def windows(case: Any, mode: str = "independent") -> tuple[list[Any], list[Any]]:
    snapshots, projections = [], []
    for index in range(2):
        request, entity, snapshot, source, _, payload = dependency_case(case)
        snapshot = snapshot.model_copy(
            update={
                "snapshot_sha256": str(index + 1) * 64,
                "window_count": 2,
                "windows": [snapshot.windows[0].model_copy(update={"window_id": index})],
            }
        )
        for page in payload["pages"]:
            page["stable_key"] += (
                "-shared" if mode in {"shared", "conflict"} else f"-window-{index}"
            )
        if index == 1 and mode == "shared":
            payload["decisions"][1]["depends_on"] = ["c1"]
        if index == 1 and mode == "conflict":
            payload["pages"][0]["title"] += "不同内容"
        if mode == "empty":
            payload["pages"], payload["definitions"] = [], []
            for decision in payload["decisions"]:
                decision.update(decision="REJECT", member_refs=[], depends_on=[])
        context = render_native_admission_context(
            request=request,
            entity_id=entity,
            snapshot=snapshot,
            source=source,
            dependency_policy="candidate-dependencies.830.v1",
            isolation_enabled=False,
        )
        snapshots.append(snapshot)
        projections.append(project((request, entity, snapshot, source, context, payload)))
    return snapshots, projections


def test_empty_windows_keep_complete_audit_without_inventing_members(case: Any) -> None:
    from insurance_harness.product_ingestion.native_dependency_aggregate import (
        aggregate_native_dependencies,
        validate_aggregate_selection,
    )

    snapshots, projections = windows(case, "empty")
    outcome = aggregate_native_dependencies(snapshots=snapshots, projections=projections)
    assert not outcome.output.pages and not outcome.output.definitions
    assert not outcome.selection["retained_candidates"]
    assert outcome.pending_candidate_count == 6
    validate_aggregate_selection(outcome.selection, outcome.output)


def test_multiple_local_refs_are_namespaced_and_independent_members_survive(case: Any) -> None:
    from insurance_harness.product_ingestion.native_dependency_aggregate import (
        aggregate_native_dependencies,
        validate_aggregate_selection,
    )

    snapshots, projections = windows(case)
    outcome = aggregate_native_dependencies(snapshots=snapshots, projections=projections)
    assert {p.stable_key for p in outcome.output.pages} == {
        "dependency-b-window-0",
        "dependency-b-window-1",
    }
    assert len(outcome.selection["retained_candidates"]) == 2
    assert len(set(outcome.selection["retained_candidates"])) == 2
    assert outcome.pending_candidate_count == 4
    validate_aggregate_selection(outcome.selection, outcome.output)


def test_shared_formal_member_propagates_failure_across_windows(case: Any) -> None:
    from insurance_harness.product_ingestion.native_dependency_aggregate import (
        aggregate_native_dependencies,
    )

    snapshots, projections = windows(case, "shared")
    result = aggregate_native_dependencies(snapshots=snapshots, projections=projections)
    assert not result.output.pages
    assert result.pending_candidate_count == 6


def test_same_formal_member_with_different_content_is_a_conflict(case: Any) -> None:
    from insurance_harness.product_ingestion.native_dependency_aggregate import (
        aggregate_native_dependencies,
    )

    snapshots, projections = windows(case, "conflict")
    with pytest.raises(ValueError, match="formal member content conflict"):
        aggregate_native_dependencies(snapshots=snapshots, projections=projections)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "source", "owner", "content", "mapping"])
def test_aggregate_rejects_incomplete_or_tampered_bindings(case: Any, fault: str) -> None:
    import hashlib
    from copy import deepcopy
    from dataclasses import replace

    from insurance_harness.product_ingestion.native_dependency_aggregate import (
        aggregate_native_dependencies,
    )
    from insurance_harness.product_ingestion.stages import json_bytes

    snapshots, projections = windows(case)
    if fault == "missing":
        snapshots = snapshots[:1]
    elif fault == "duplicate":
        snapshots[1] = snapshots[0]
    elif fault == "source":
        snapshots[1] = snapshots[1].model_copy(update={"source_snapshot_sha256": "f" * 64})
    else:
        domain = deepcopy(projections[1].dependency_domain)
        if fault == "owner":
            domain["entity_id"] = "other"
        elif fault == "content":
            output = projections[1].output
            page = output.pages[0].model_copy(update={"title": "tampered"})
            projections[1] = replace(
                projections[1],
                output=output.model_copy(update={"pages": (page, *output.pages[1:])}),
            )
        else:
            rows = domain["members"]
            rows[0]["member_id"], rows[1]["member_id"] = rows[1]["member_id"], rows[0]["member_id"]
            ids = {row["member_ref"]: row["member_id"] for row in rows}
            for row in domain["review_bindings"]:
                row["member_id"] = ids.get(row["member_ref"])
        domain["domain_sha256"] = hashlib.sha256(
            json_bytes({k: v for k, v in domain.items() if k != "domain_sha256"})
        ).hexdigest()
        projections[1] = replace(projections[1], dependency_domain=domain)
    with pytest.raises(ValueError):
        aggregate_native_dependencies(snapshots=snapshots, projections=projections)


@pytest.mark.asyncio
async def test_normal_coordinator_aggregates_without_changing_admission_input(
    case: Any, monkeypatch: Any
) -> None:
    import json
    from types import SimpleNamespace

    from insurance_harness.product_ingestion import native_pipeline
    from insurance_harness.product_ingestion.native_admission_stage import (
        NativeAdmissionWindowOutcome,
    )
    from insurance_harness.product_ingestion.native_discovery_stage import NativeDiscoveryCollection

    snapshots, projections = windows(case)
    request, _, _, source, _, _ = dependency_case(case)
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
    seen = []

    async def collect(**kwargs: Any) -> Any:
        return NativeDiscoveryCollection(True, tuple(snapshots), (), ())

    async def admit(**kwargs: Any) -> Any:
        assert kwargs["isolation_enabled"] is False
        window_id = kwargs["snapshot"].windows[0].window_id
        seen.append(window_id)
        return NativeAdmissionWindowOutcome(projections[window_id], (), None)

    monkeypatch.setattr(native_pipeline, "collect_native_discovery", collect)
    monkeypatch.setattr(native_pipeline, "run_native_admission_window", admit)
    settings = SimpleNamespace(
        policy="native-candidates.830.v1",
        dependency_policy="candidate-dependencies.830.v1",
        language="zh-CN",
        granularity="exhaustive",
        purpose="",
        allow_knowledge_updates=False,
    )
    result = await native_pipeline.run_native_discovery_stage(
        service=cast(
            ProductScopeServices,
            SimpleNamespace(configuration=SimpleNamespace(native_discovery=settings)),
        ),
        artifacts=cast(ProductArtifactStore, SimpleNamespace()),
        scope=cast(ProductScope, SimpleNamespace()),
        run=cast(ProductRunSnapshot, SimpleNamespace(run_id="run", retry_of_run_id=None)),
        stage=cast(StageSnapshot, SimpleNamespace(dependency_sha256="a" * 64)),
        job=cast(JobSnapshot, SimpleNamespace()),
        request=request,
        sources={snapshots[0].knowledge_id: source},
    )
    rows = {
        row.artifact_kind: json.loads(row.payload)
        for row in result.drafts
        if row.artifact_key == "product"
    }
    assert seen == [0, 1]
    assert len(rows["discovery_candidates"]["output"]["pages"]) == 2
    assert (
        rows["discovery_candidates"]["dependency_selection"]["contract"]
        == "native-dependency-selection.830.v2"
    )
    assert rows["discovery_summary"]["pending_candidate_count"] == 4
    assert "native_dependency_aggregate" in rows


def aggregated_candidates(case: Any) -> tuple[Any, str, Any, dict[str, Any]]:
    import hashlib
    import json

    from insurance_harness.product_ingestion.native_dependency_aggregate import (
        aggregate_native_dependencies,
    )
    from insurance_harness.product_ingestion.stages import json_bytes

    snapshots, projections = windows(case)
    request, entity = dependency_case(case)[:2]
    result = aggregate_native_dependencies(snapshots=snapshots, projections=projections)
    sources: list[dict[str, Any]] = []
    dispositions: list[dict[str, Any]] = []
    for snapshot, projection in zip(snapshots, projections, strict=True):
        prefix = hashlib.sha256(json_bytes([entity, snapshot.snapshot_sha256])).hexdigest() + ":"
        sources.extend(
            {**r, "source_ref": prefix + r["source_ref"]}
            for r in json.loads(projection.context)["source_options"]
        )
        for row in projection.dispositions:
            candidate_id = prefix + row["candidate_id"]
            if candidate_id in result.retained_review_ids:
                dispositions.append(
                    {
                        **row,
                        "candidate_id": candidate_id,
                        "evidence": [
                            {**e, "source_ref": prefix + e["source_ref"]} for e in row["evidence"]
                        ],
                    }
                )
    return (
        request,
        entity,
        result.output,
        {
            "output": result.output.model_dump(mode="json"),
            "sources": sources,
            "dispositions": dispositions,
            "dependency_selection": result.selection,
        },
    )


def test_v10_review_validates_aggregate_and_keeps_only_compact_graph(case: Any) -> None:
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        compile_output_hash_g3,
    )
    from insurance_harness.product_ingestion.discovery import (
        build_discovery_exclusion_index,
        render_independent_discovery_review_context,
    )
    from insurance_harness.product_ingestion.native_dependency_selection import (
        resolve_native_review_entity,
    )

    request, entity, output, candidates = aggregated_candidates(case)
    assert (
        resolve_native_review_entity(
            request=request, candidate_output=output, selection=candidates["dependency_selection"]
        )
        == entity
    )
    context = render_independent_discovery_review_context(
        request=request,
        entity_id=entity,
        exclusion_index=build_discovery_exclusion_index(request, entity),
        discovery_candidates=candidates,
        final_composed_output=output,
        final_composed_output_hash=compile_output_hash_g3(output),
    )
    assert context["contract"] == "product-discovery-review-context.830.v10"
    assert (
        context["dependency_selection"]["selection_sha256"]
        == candidates["dependency_selection"]["selection_sha256"]
    )
    assert "domains" not in context["dependency_selection"]
    assert len(context["review_member_ids"]) == 2
    assert all(row["content_provenance"] for row in context["candidate_members"])


def test_v10_does_not_send_unreferenced_isolated_window_text(case: Any) -> None:
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        compile_output_hash_g3,
    )
    from insurance_harness.product_ingestion.discovery import (
        build_discovery_exclusion_index,
        render_independent_discovery_review_context,
    )

    request, entity, output, candidates = aggregated_candidates(case)
    needed = candidates["sources"][0]
    candidates["dispositions"][0]["evidence"] = [
        {"source_ref": needed["source_ref"], "quote": needed["spans"][0]["quote"]}
    ]
    candidates["sources"].append(
        {
            "source_ref": "isolated-source",
            "spans": [{"start": 0, "end": 290000, "quote": "x" * 290000}],
        }
    )
    context = render_independent_discovery_review_context(
        request=request,
        entity_id=entity,
        exclusion_index=build_discovery_exclusion_index(request, entity),
        discovery_candidates=candidates,
        final_composed_output=output,
        final_composed_output_hash=compile_output_hash_g3(output),
        max_context_bytes=300000,
    )
    required = {e["source_ref"] for row in candidates["dispositions"] for e in row["evidence"]}
    assert {row["source_ref"] for row in context["source_options"]} == required
    assert "isolated-source" not in str(context)
