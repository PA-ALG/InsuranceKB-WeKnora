"""Execute one native admission window through the existing model-call journal."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from insurance_harness.jobs import JobSnapshot
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
)
from insurance_harness.product_ingestion.artifact_models import ArtifactDraft, ArtifactOrigin
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.checkpoints import CURRENT_ARTIFACT_CONTRACTS
from insurance_harness.product_ingestion.model_execution import (
    ConfiguredFieldTransport,
    ModelPolicyDenied,
)
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductScope,
    StageSnapshot,
)
from insurance_harness.product_ingestion.native_admission import (
    NativeAdmissionProjection,
)
from insurance_harness.product_ingestion.native_admission_context import (
    render_native_admission_context,
)
from insurance_harness.product_ingestion.native_admission_policy import resolve_admission_policy
from insurance_harness.product_ingestion.native_admission_preflight import (
    preflight_native_admission_response,
)
from insurance_harness.product_ingestion.native_admission_wire import render_wire_context
from insurance_harness.product_ingestion.native_call_replay import (
    NativeReplayIndex,
    read_native_replay_calls,
    select_native_replay_call,
)
from insurance_harness.product_ingestion.native_discovery import NativeDiscoverySnapshot
from insurance_harness.product_ingestion.native_evidence import locate_native_evidence
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot
from insurance_harness.product_ingestion.stages import artifact, json_bytes

if TYPE_CHECKING:
    from insurance_harness.product_ingestion.composition import ProductScopeServices


@dataclass(frozen=True, slots=True)
class NativeAdmissionWindowOutcome:
    projection: NativeAdmissionProjection | None
    drafts: tuple[ArtifactDraft, ...]
    failure: str | None


async def run_native_admission_window(
    *,
    service: ProductScopeServices,
    artifacts: ProductArtifactStore,
    scope: ProductScope,
    run: ProductRunSnapshot,
    stage: StageSnapshot,
    job: JobSnapshot,
    request: BatchConceptCompileRequest830G3V1,
    entity_id: str,
    snapshot: NativeDiscoverySnapshot,
    source: DecodedSourceSnapshot,
    replay_calls: NativeReplayIndex | None = None,
    dependency_policy: str | None = None,
    isolation_enabled: bool = False,
) -> NativeAdmissionWindowOutcome:
    """Consume verified snapshots; stage owner persists these returned artifacts.

    Provider raw is durably recorded by the shared executor before projection.
    A received but semantically invalid response remains auditable and pending;
    this adapter never sends a repair call or authorizes publication.
    """
    policy = resolve_admission_policy(
        service.configuration.model,
        dependency_policy,
        getattr(service.configuration, "native_admission", None),
    )
    settings, prompt, template = policy.settings, policy.prompt, policy.template
    executor = service.native_admission_executor if policy.wire_protocol else service.model_executor
    if executor is None:
        raise ValueError("native admission executor is not configured")
    base = request.base_request
    expected_scope = ProductScope(
        tenant_id=str(base.tenant_id),
        space_id=base.space_id,
        raw_knowledge_base_id=base.raw_kb_id,
        wiki_knowledge_base_id=base.wiki_kb_id,
    )
    if scope != settings.scope or scope != expected_scope:
        raise ValueError("native admission execution scope mismatch")
    from insurance_harness.product_ingestion.native_relation_admission import RELATION_CAPABILITY
    from insurance_harness.product_ingestion.native_relation_wire import (
        RELATION_WIRE_PROTOCOL,
        render_relation_wire_context,
    )

    relation_enabled = policy.wire_protocol == RELATION_WIRE_PROTOCOL
    context = await asyncio.to_thread(
        render_native_admission_context,
        request=request,
        entity_id=entity_id,
        snapshot=snapshot,
        source=source,
        max_context_bytes=template.max_context_bytes,
        dependency_policy=dependency_policy,
        isolation_enabled=isolation_enabled,
        relation_capability=RELATION_CAPABILITY if relation_enabled else None,
    )
    wire_context = (
        render_relation_wire_context(context)
        if relation_enabled
        else render_wire_context(context)
        if policy.wire_protocol
        else context
    )
    content = json_bytes(wire_context)
    input_hash = hashlib.sha256(content).hexdigest()
    operation = "native-admission-" + input_hash
    drafts: list[ArtifactDraft] = []

    def keep(kind: str, payload: bytes, *, call_id: str | None = None) -> None:
        drafts.append(
            artifact(
                kind,
                input_hash,
                payload,
                stage.dependency_sha256,
                origin=ArtifactOrigin.MODEL if call_id else ArtifactOrigin.RULE,
                call_id=call_id,
                contract_version=CURRENT_ARTIFACT_CONTRACTS.get(kind, (None, "1"))[1],
            )
        )

    keep("native_admission_context", content)
    try:
        replay_calls = (
            await read_native_replay_calls(artifacts, scope, run)
            if replay_calls is None
            else replay_calls
        )
        replayed = select_native_replay_call(
            replay_calls,
            operation=operation,
            input_hash=input_hash,
            settings=settings,
            scope=scope,
            content=content,
            prompt=prompt,
            template=template,
        )
        if replayed is not None:
            raw, call_id = replayed.raw, replayed.call_id
            request_hash = replayed.request_sha256
        else:
            result = await executor.execute_stage_call(
                store=artifacts,
                scope=scope,
                run_id=run.run_id,
                job=job,
                stage_key="discovery",
                operation_key=operation,
                dependency_sha256=stage.dependency_sha256,
                input_sha256=input_hash,
                content=content,
                prompt=prompt,
                template_id=template.template_id,
            )
            if (
                result.state != "recorded"
                or result.raw is None
                or result.diagnostic
                or result.policy_receipt is None
            ):
                raise ValueError(
                    "native admission call incomplete: " + (result.diagnostic or result.state)
                )
            raw, call_id = result.raw, result.call_id
            request_hash = result.execution_receipt.request_sha256
        assert raw is not None
        keep(
            "native_admission_execution",
            json_bytes(
                {
                    "contract": "native-admission-execution-receipt.830.v2",
                    **policy.identity(),
                    "operation_key": operation,
                    "input_sha256": input_hash,
                    "model_call_id": call_id,
                    "raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "request_sha256": request_hash,
                    "replayed_from_run_id": replayed.run_id if replayed is not None else None,
                }
            ),
        )
        decoded = ConfiguredFieldTransport.decode_response(raw)
        keep("native_admission_response", decoded, call_id=call_id if replayed is None else None)
        preflight = await asyncio.to_thread(
            preflight_native_admission_response,
            raw=decoded,
            request=request,
            entity_id=entity_id,
            snapshot=snapshot,
            source=source,
            context=context,
            wire_protocol=policy.wire_protocol,
            )
        keep("native_admission_preflight", json_bytes(preflight.receipt))
        keep("native_admission_canonical_response", preflight.canonical)
        if preflight.projection is None:
            raise ValueError(preflight.failure or "native admission preflight rejected")
        projection = preflight.projection
        located = await asyncio.to_thread(
            locate_native_evidence,
            projection.output,
            {snapshot.knowledge_id: source},
        )
        projection = replace(projection, output=located.output)
        keep(
            "native_admission_projection",
            json_bytes(
                {
                    "contract": "native-admission-projection.830.v2",
                    "preflight_sha256": hashlib.sha256(json_bytes(preflight.receipt)).hexdigest(),
                    "output": projection.output,
                    "decisions": projection.response.decisions,
                    "dispositions": projection.dispositions,
                    "locations": located.locations,
                    **(
                        {"dependency_selection": projection.dependency_selection}
                        if projection.dependency_selection is not None
                        else {}
                    ),
                }
            ),
        )
        return NativeAdmissionWindowOutcome(projection, tuple(drafts), None)
    except (ValueError, ModelPolicyDenied) as exc:
        keep(
            "native_admission_failure",
            json_bytes(
                {
                    "contract": "native-admission-failure.830.v1",
                    "detail": str(exc),
                }
            ),
        )
        return NativeAdmissionWindowOutcome(None, tuple(drafts), str(exc))
