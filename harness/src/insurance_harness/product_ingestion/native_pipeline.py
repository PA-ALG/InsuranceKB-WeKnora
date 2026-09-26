"""Compose the native candidate and admission ports into the existing discovery stage."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from insurance_harness.jobs import JobSnapshot
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
    compile_request_hash_g3,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    CompileOutput,
    free_page_id,
)
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.configuration import LoadedProductBinding
from insurance_harness.product_ingestion.discovery import build_discovery_exclusion_index
from insurance_harness.product_ingestion.model_execution import ModelPolicyDenied
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductRunState,
    ProductScope,
    StageSnapshot,
)
from insurance_harness.product_ingestion.native_admission import NativeAdmissionProjection
from insurance_harness.product_ingestion.native_admission_stage import run_native_admission_window
from insurance_harness.product_ingestion.native_call_replay import read_native_replay_calls
from insurance_harness.product_ingestion.native_dependency_aggregate import (
    aggregate_native_dependencies,
)
from insurance_harness.product_ingestion.native_discovery_stage import collect_native_discovery
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot
from insurance_harness.product_ingestion.stages import StageOutput, artifact, json_bytes

if TYPE_CHECKING:
    from insurance_harness.product_ingestion.composition import ProductScopeServices


def native_discovery_policy(configuration: LoadedProductBinding) -> dict[str, Any] | None:
    settings = configuration.native_discovery
    if settings is None:
        return None
    return {
        "contract": "native-discovery-policy.830.v1",
        "scope": configuration.scope.model_dump(mode="json"),
        "settings": settings.model_dump(mode="json"),
        "model_policy_sha256": configuration.model.policy_sha256,
    }


def validate_native_discovery_policy(
    expected: dict[str, Any] | None,
    saved: bytes | None,
) -> None:
    if expected is None and saved is None:
        return
    if expected is None or saved is None or json_bytes(json.loads(saved)) != json_bytes(expected):
        raise ValueError("NATIVE_DISCOVERY_POLICY_CHANGED")


async def run_native_discovery_stage(
    *,
    service: ProductScopeServices,
    artifacts: ProductArtifactStore,
    scope: ProductScope,
    run: ProductRunSnapshot,
    stage: StageSnapshot,
    job: JobSnapshot,
    request: BatchConceptCompileRequest830G3V1,
    sources: Mapping[str, DecodedSourceSnapshot],
) -> StageOutput:
    settings = service.configuration.native_discovery
    if settings is None:
        raise ValueError("native discovery is not configured")
    expected_update = "explicit-same-identity.830.v1" if settings.allow_knowledge_updates else None
    if request.knowledge_update_policy != expected_update:
        raise ValueError("native admission update policy binding changed")
    material_sources: dict[str, set[str]] = {}
    for entry in request.resolution_inputs.corpus.entries:
        for block in entry.blocks:
            material_sources.setdefault(block.knowledge_id, set()).add(entry.material_id)
    if not material_sources or not material_sources.keys() <= sources.keys():
        raise ValueError("native discovery current source set incomplete")
    replay_calls = await read_native_replay_calls(artifacts, scope, run)
    collection = await collect_native_discovery(
        service=service,
        artifacts=artifacts,
        scope=scope,
        run=run,
        stage=stage,
        job=job,
        sources=tuple(sources[key] for key in sorted(material_sources)),
        language=settings.language,
        granularity=settings.granularity,
        purpose=settings.purpose,
        replay_calls=replay_calls,
    )
    drafts = list(collection.drafts)
    bound = {m for b in request.entity_bindings for m in b.source_material_ids}
    unbound = sorted({e.material_id for e in request.resolution_inputs.corpus.entries} - bound)
    failures: list[dict[str, Any]] = [
        {
            "knowledge_id": f.knowledge_id,
            "window_id": f.window_id,
            "phase": f.phase,
            "detail": f.detail,
        }
        for f in collection.failures
    ]
    definitions: dict[str, Any] = {}
    pages: dict[str, Any] = {}
    audit: dict[str, Any] = {}
    dispositions: list[dict[str, Any]] = []
    source_options: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    counts = {
        "proposed_new": 0,
        "duplicate": 0,
        "update_proposal": 0,
        "rejected": 0,
        "published": 0,
    }
    unresolved = False
    dependency_policy = getattr(settings, "dependency_policy", None)
    admission_groups = sum(
        1
        for snap in collection.snapshots
        if snap.candidates
        for binding in request.entity_bindings
        if set(binding.source_material_ids) & material_sources[snap.knowledge_id]
    )
    isolation_enabled = bool(
        dependency_policy
        and collection.complete
        and not failures
        and not unbound
        and admission_groups == 1
        and len(collection.snapshots) == 1
        and len(collection.snapshots[0].windows) == 1
    )
    aggregate_eligible = bool(
        dependency_policy
        and collection.complete
        and not failures
        and not unbound
        and len(collection.snapshots) > 1
        and admission_groups > 0
    )
    projections: list[NativeAdmissionProjection] = []
    selection = None
    pending_count = 0
    for snapshot in collection.snapshots:
        entities = [
            b
            for b in request.entity_bindings
            if set(b.source_material_ids) & material_sources[snapshot.knowledge_id]
        ]
        for binding in sorted(entities, key=lambda row: row.entity_id):
            if not snapshot.candidates:
                continue
            try:
                outcome = await run_native_admission_window(
                    service=service,
                    artifacts=artifacts,
                    scope=scope,
                    run=run,
                    stage=stage,
                    job=job,
                    request=request,
                    entity_id=binding.entity_id,
                    snapshot=snapshot,
                    source=sources[snapshot.knowledge_id],
                    replay_calls=replay_calls,
                    dependency_policy=dependency_policy,
                    isolation_enabled=isolation_enabled,
                )
            except (ValueError, ModelPolicyDenied) as exc:
                failures.append(
                    {
                        "knowledge_id": snapshot.knowledge_id,
                        "window_id": snapshot.windows[0].window_id,
                        "entity_id": binding.entity_id,
                        "phase": "admission-preflight",
                        "detail": str(exc),
                    }
                )
                continue
            drafts.extend(outcome.drafts)
            if outcome.projection is None:
                failures.append(
                    {
                        "knowledge_id": snapshot.knowledge_id,
                        "window_id": snapshot.windows[0].window_id,
                        "entity_id": binding.entity_id,
                        "phase": "admission",
                        "detail": outcome.failure,
                    }
                )
                continue
            projection = outcome.projection
            projections.append(projection)
            if isolation_enabled:
                if projection.dependency_selection is None:
                    raise ValueError("native dependency selection missing")
                selection = projection.dependency_selection
                pending_count += len(projection.isolated_candidates)
            else:
                pending_count += (
                    projection.dependency_unavailable_count
                    if dependency_policy
                    else sum(
                        d.decision in {"PENDING", "REQUIRES_ENTITY_RESOLUTION"}
                        for d in projection.response.decisions
                    )
                )
            prefix = (
                hashlib.sha256(
                    json_bytes(
                        [
                            binding.entity_id,
                            snapshot.snapshot_sha256,
                        ]
                    )
                ).hexdigest()
                + ":"
            )
            context = json.loads(projection.context)
            for option in context["source_options"]:
                source_options.append({**option, "source_ref": prefix + option["source_ref"]})
            for row in projection.dispositions:
                dispositions.append(
                    {
                        **row,
                        "candidate_id": prefix + row["candidate_id"],
                        "evidence": [
                            {**e, "source_ref": prefix + e["source_ref"]} for e in row["evidence"]
                        ],
                    }
                )
            for decision in projection.response.decisions:
                key = {
                    "NEW": "proposed_new",
                    "UPDATE": "update_proposal",
                    "REFERENCE": "duplicate",
                    "REJECT": "rejected",
                }.get(decision.decision)
                if key:
                    counts[key] += 1
                unresolved |= decision.decision in {"PENDING", "REQUIRES_ENTITY_RESOLUTION"}
            for identity, member, target in (
                *((m.concept_id, m, definitions) for m in projection.output.definitions),
                *((free_page_id(m), m, pages) for m in projection.output.pages),
                *((m.key, m, audit) for m in projection.output.audit),
            ):
                if identity in target and target[identity] != member:
                    failures.append(
                        {
                            "phase": "composition",
                            "detail": "NATIVE_MEMBER_CONFLICT",
                            "member_id": identity,
                        }
                    )
                target[identity] = member
            receipts.append(
                {
                    "entity_id": binding.entity_id,
                    "native_snapshot_sha256": snapshot.snapshot_sha256,
                    "admission_context_sha256": hashlib.sha256(projection.context).hexdigest(),
                }
            )
    if aggregate_eligible and not failures:
        try:
            aggregate = await asyncio.to_thread(
                aggregate_native_dependencies,
                snapshots=collection.snapshots,
                projections=projections,
            )
            definitions = {row.concept_id: row for row in aggregate.output.definitions}
            pages = {free_page_id(row): row for row in aggregate.output.pages}
            audit = {row.key: row for row in aggregate.output.audit}
            dispositions = [
                row for row in dispositions if row["candidate_id"] in aggregate.retained_review_ids
            ]
            selection = aggregate.selection
            pending_count = aggregate.pending_candidate_count
        except ValueError as exc:
            failures.append({"phase": "dependency-aggregate", "detail": str(exc)})
    unresolved |= pending_count > 0
    complete = collection.complete and not failures and not unbound and not unresolved
    # Retain a subset only after its complete dependency domain has been validated.
    if not complete and not (
        (isolation_enabled or aggregate_eligible) and selection is not None and not failures
    ):
        definitions, pages, audit = {}, {}, {}
        dispositions, source_options = [], []
    output = CompileOutput(
        request_hash=compile_request_hash_g3(request.base_request),
        fields=(),
        definitions=tuple(definitions[key] for key in sorted(definitions)),
        pages=tuple(sorted(pages.values(), key=lambda row: (row.entity_id, row.stable_key))),
        audit=tuple(audit[key] for key in sorted(audit)),
        transformation="SYNTHESIZE" if pages or definitions else "EXTRACT",
    )
    indexes = await asyncio.to_thread(
        lambda: {
            b.entity_id: build_discovery_exclusion_index(request, b.entity_id)
            for b in request.entity_bindings
        }
    )
    executions = [
        json.loads(d.payload)
        for d in drafts
        if d.artifact_kind
        in {
            "native_discovery_execution",
            "native_admission_execution",
        }
    ]
    total = sum(len(b.text) for key in material_sources for b in sources[key].blocks)
    state = (
        "FAILED"
        if failures or not collection.complete
        else "PENDING"
        if unbound or unresolved or pages or definitions
        else "EMPTY"
    )
    summary = {
        "state": state,
        "reused": any(e["replayed_from_run_id"] for e in executions),
        "reason_codes": [
            "NATIVE_DISCOVERY_FAILED"
            if state == "FAILED"
            else "NATIVE_DISCOVERY_PENDING"
            if state == "PENDING"
            else "DISCOVERY_EMPTY"
        ],
        "call_ids": sorted(
            {e["model_call_id"] for e in executions if not e["replayed_from_run_id"]}
        ),
        "counts": counts,
        "accepted_member_count": 0,
        # A failed/unknown native attempt does not establish how many characters
        # the provider actually received. Keep unknown coverage absent, not zero.
        "coverage": {
            "offered_chars": total,
            "omitted_chars": 0,
            "material_count": len(material_sources),
            "complete": collection.complete,
        }
        if collection.complete
        else None,
        "native_coverage": {
            "complete": complete,
            "completed_windows": len(collection.snapshots),
            "failures": failures,
            "unbound_material_ids": unbound,
        },
    }
    if dependency_policy:
        summary.update(dependency_policy=dependency_policy, pending_candidate_count=pending_count)
    candidates = {
        "contract": "product-discovery-candidates.830.v1",
        "output": output,
        "dispositions": dispositions,
        "sources": source_options,
        "window_receipts": receipts,
        "producer_policy": settings.policy,
        "exclusion_index_sha256": hashlib.sha256(json_bytes(indexes)).hexdigest(),
    }
    if selection is not None:
        candidates["dependency_selection"] = selection
        drafts.append(
            artifact(
                "native_dependency_aggregate"
                if selection["contract"] == "native-dependency-selection.830.v2"
                else "native_dependency_selection",
                "product",
                json_bytes(selection),
                stage.dependency_sha256,
            )
        )
    for kind, value in (
        ("discovery_candidates", candidates),
        (
            "discovery_delta",
            {"contract": "product-discovery-delta.830.v1", "output": output, "reviewed": False},
        ),
        ("discovery_summary", summary),
    ):
        drafts.append(artifact(kind, "product", json_bytes(value), stage.dependency_sha256))
    return StageOutput(
        tuple(drafts),
        state=(
            ProductRunState.SUCCEEDED
            if complete and not unresolved
            else ProductRunState.PARTIAL_SUCCESS
        ),
    )
