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
from insurance_harness.product_ingestion.discovery_stage import (
    require_discovery_template,
    verify_recorded_discovery_call,
)
from insurance_harness.product_ingestion.model_execution import (
    ConfiguredFieldTransport,
    ModelPolicyDenied,
    matches_recorded_stage_request,
)
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductScope,
    StageSnapshot,
)
from insurance_harness.product_ingestion.native_admission import (
    NATIVE_ADMISSION_PROMPT,
    NativeAdmissionProjection,
    project_native_admission_response,
    render_native_admission_context,
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
) -> NativeAdmissionWindowOutcome:
    """Consume verified snapshots; stage owner persists these returned artifacts.

    Provider raw is durably recorded by the shared executor before projection.
    A received but semantically invalid response remains auditable and pending;
    this adapter never sends a repair call or authorizes publication.
    """
    settings = service.configuration.model
    base = request.base_request
    expected_scope = ProductScope(
        tenant_id=str(base.tenant_id),
        space_id=base.space_id,
        raw_knowledge_base_id=base.raw_kb_id,
        wiki_knowledge_base_id=base.wiki_kb_id,
    )
    if scope != settings.scope or scope != expected_scope:
        raise ValueError("native admission execution scope mismatch")
    template = require_discovery_template(
        settings, "extract", "g3-native-admission", NATIVE_ADMISSION_PROMPT
    )
    context = await asyncio.to_thread(
        render_native_admission_context,
        request=request,
        entity_id=entity_id,
        snapshot=snapshot,
        source=source,
        max_context_bytes=template.max_context_bytes,
    )
    content = json_bytes(context)
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
            )
        )

    keep("native_admission_context", content)
    try:
        parent_calls = (
            await asyncio.to_thread(
                artifacts.list_stage_calls, scope=scope, run_id=run.retry_of_run_id
            )
            if run.retry_of_run_id
            else ()
        )
        prior = [
            row
            for row in parent_calls
            if row.stage_key == "discovery" and row.operation_key == operation
        ]
        if len(prior) > 1:
            raise ValueError("native admission parent call duplicated")
        replayed = None
        if prior:
            assert run.retry_of_run_id is not None
            replayed = verify_recorded_discovery_call(
                prior[0],
                run_id=run.retry_of_run_id,
                stage_key="discovery",
                operation=operation,
                input_sha256=input_hash,
                prompt_sha256=template.prompt_sha256,
            )
            if replayed is not None and not matches_recorded_stage_request(
                replayed,
                settings,
                scope=scope,
                content=content,
                prompt=NATIVE_ADMISSION_PROMPT,
                template_id=template.template_id,
            ):
                replayed = None
        if replayed is not None:
            raw, call_id = replayed.raw, replayed.call_id
        else:
            result = await service.model_executor.execute_stage_call(
                store=artifacts,
                scope=scope,
                run_id=run.run_id,
                job=job,
                stage_key="discovery",
                operation_key=operation,
                dependency_sha256=stage.dependency_sha256,
                input_sha256=input_hash,
                content=content,
                prompt=NATIVE_ADMISSION_PROMPT,
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
        assert raw is not None
        keep(
            "native_admission_execution",
            json_bytes(
                {
                    "contract": "native-admission-execution-receipt.830.v1",
                    "operation_key": operation,
                    "input_sha256": input_hash,
                    "model_call_id": call_id,
                    "raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "replayed_from_run_id": run.retry_of_run_id if replayed is not None else None,
                }
            ),
        )
        decoded = ConfiguredFieldTransport.decode_response(raw)
        keep("native_admission_response", decoded, call_id=call_id if replayed is None else None)
        projection = await asyncio.to_thread(
            project_native_admission_response,
            raw=decoded,
            request=request,
            entity_id=entity_id,
            snapshot=snapshot,
            source=source,
            context=context,
        )
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
                    "contract": "native-admission-projection.830.v1",
                    "output": projection.output,
                    "decisions": projection.response.decisions,
                    "dispositions": projection.dispositions,
                    "locations": located.locations,
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
