"""Execute signed native candidate windows using the existing StageCall journal.

This collector does not admit knowledge or publish pages. Returned drafts join
normal stage persistence; successful provider responses are already durable in
the model executor before any native projection is requested.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from insurance_harness.jobs import JobSnapshot, NonRetryableJobError, RetryableJobError
from insurance_harness.product_ingestion.artifact_models import ArtifactDraft, ArtifactOrigin
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.discovery_stage import (
    require_discovery_template,
)
from insurance_harness.product_ingestion.model_execution import (
    ConfiguredFieldTransport,
    ModelPolicyDenied,
    prepare_configured_model_request,
)
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductScope,
    StageSnapshot,
)
from insurance_harness.product_ingestion.native_call_replay import (
    NativeReplayIndex,
    read_native_replay_calls,
    select_native_replay_call,
)
from insurance_harness.product_ingestion.native_discovery import (
    NATIVE_DISCOVERY_EXECUTION_PROMPT,
    NativeDiscoveryRequest,
    NativeDiscoverySnapshot,
    NativeDiscoveryWindow,
    decode_native_discovery_snapshot,
)
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot
from insurance_harness.product_ingestion.stages import artifact, json_bytes

if TYPE_CHECKING:
    from insurance_harness.product_ingestion.composition import ProductScopeServices


@dataclass(frozen=True, slots=True)
class NativeDiscoveryFailure:
    knowledge_id: str
    window_id: int | None
    phase: str
    detail: str


@dataclass(frozen=True, slots=True)
class NativeDiscoveryCollection:
    complete: bool
    snapshots: tuple[NativeDiscoverySnapshot, ...]
    failures: tuple[NativeDiscoveryFailure, ...]
    drafts: tuple[ArtifactDraft, ...]


def _execution_content(
    *,
    source_sha256: str,
    policy_sha256: str,
    knowledge_id: str,
    parse_attempt: int,
    window_id: int,
    phase: str,
    prompt: str,
) -> bytes:
    return json_bytes(
        dict(
            contract="native-discovery-execution.830.v1",
            source_snapshot_sha256=source_sha256,
            policy_sha256=policy_sha256,
            phase=phase,
            knowledge_id=knowledge_id,
            parse_attempt=parse_attempt,
            window_id=window_id,
            prompt=prompt,
            prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
        )
    )


async def collect_native_discovery(
    *,
    service: ProductScopeServices,
    artifacts: ProductArtifactStore,
    scope: ProductScope,
    run: ProductRunSnapshot,
    stage: StageSnapshot,
    job: JobSnapshot,
    sources: tuple[DecodedSourceSnapshot, ...],
    language: str,
    granularity: Literal["focused", "standard", "exhaustive"],
    purpose: str,
    replay_calls: NativeReplayIndex | None = None,
) -> NativeDiscoveryCollection:
    settings = service.configuration.model
    if settings.scope != scope or not sources:
        raise ValueError("native discovery scope or sources invalid")
    ids = [source.snapshot["receipt"]["knowledge_id"] for source in sources]
    if len(set(ids)) != len(ids):
        raise ValueError("native discovery source identity duplicated")
    template = require_discovery_template(
        settings, "extract", "g3-native-discovery", NATIVE_DISCOVERY_EXECUTION_PROMPT
    )
    replay_calls = (
        await read_native_replay_calls(artifacts, scope, run)
        if replay_calls is None
        else replay_calls
    )
    drafts: list[ArtifactDraft] = []
    snapshots: list[NativeDiscoverySnapshot] = []
    failures: list[NativeDiscoveryFailure] = []
    expected_windows = 0

    def keep(kind: str, identity: object, payload: bytes, *, platform: bool = False) -> None:
        drafts.append(
            artifact(
                kind,
                hashlib.sha256(json_bytes(identity)).hexdigest(),
                payload,
                stage.dependency_sha256,
                origin=ArtifactOrigin.PLATFORM_SOURCE if platform else ArtifactOrigin.RULE,
            )
        )

    async def capture(
        source: DecodedSourceSnapshot,
        request: NativeDiscoveryRequest,
        plan: NativeDiscoverySnapshot | None = None,
        citation_plan: NativeDiscoverySnapshot | None = None,
    ) -> NativeDiscoverySnapshot:
        receipt = source.snapshot["receipt"]
        raw = await service.platform.native_discovery(
            scope, receipt["knowledge_id"], receipt["parse_attempt"], json_bytes(request)
        )
        result = await asyncio.to_thread(
            decode_native_discovery_snapshot,
            raw,
            scope=scope,
            public_keys=service.configuration.source_public_keys,
            source=source,
            request=request,
            plan=plan,
            citation_plan=citation_plan,
        )
        kind = (
            "native_candidate_snapshot" if request.phase == "snapshot" else "native_discovery_plan"
        )
        keep(kind, [receipt["knowledge_id"], request.phase, request.window_id], raw, platform=True)
        return result

    async def call(plan: NativeDiscoverySnapshot, window: NativeDiscoveryWindow, phase: str) -> str:
        content = _execution_content(
            source_sha256=plan.source_snapshot_sha256,
            policy_sha256=plan.policy_sha256,
            phase=phase,
            knowledge_id=plan.knowledge_id,
            parse_attempt=plan.parse_attempt,
            window_id=window.window_id,
            prompt=window.prompt,
        )
        input_hash = hashlib.sha256(content).hexdigest()
        operation = "native-discovery-" + input_hash
        keep("native_discovery_context", operation, content)
        assert replay_calls is not None
        replayed = select_native_replay_call(
            replay_calls,
            operation=operation,
            input_hash=input_hash,
            settings=settings,
            scope=scope,
            content=content,
            prompt=NATIVE_DISCOVERY_EXECUTION_PROMPT,
            template=template,
        )
        if replayed is not None:
            raw = replayed.raw
            call_id = replayed.call_id
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
                prompt=NATIVE_DISCOVERY_EXECUTION_PROMPT,
                template_id=template.template_id,
            )
            if (
                result.state != "recorded"
                or result.raw is None
                or result.diagnostic
                or result.policy_receipt is None
            ):
                raise ValueError(
                    "native discovery model call incomplete: " + (result.diagnostic or result.state)
                )
            raw = result.raw
            call_id = result.call_id
        assert raw is not None
        keep(
            "native_discovery_execution",
            operation,
            json_bytes(
                dict(
                    contract="native-discovery-execution-receipt.830.v1",
                    operation_key=operation,
                    input_sha256=input_hash,
                    model_call_id=call_id,
                    raw_sha256=hashlib.sha256(raw).hexdigest(),
                    replayed_from_run_id=replayed.run_id if replayed is not None else None,
                )
            ),
        )
        return ConfiguredFieldTransport.decode_response(raw).decode("utf-8")

    failure_types = (ValueError, ModelPolicyDenied, RetryableJobError, NonRetryableJobError)
    for source in sources:
        receipt = source.snapshot["receipt"]
        knowledge_id = receipt["knowledge_id"]
        try:
            # Each raw UTF-8 byte expands by at most 6 in JSON content and 7
            # when that JSON is itself a provider message. Measure all fixed
            # overhead with the actual serializer; reserve the largest possible
            # window-id width and phase. Native fixed batches reject oversize
            # plans explicitly rather than truncating source material.
            baseline = prepare_configured_model_request(
                settings,
                scope=scope,
                prompt=NATIVE_DISCOVERY_EXECUTION_PROMPT,
                template_id=template.template_id,
                content=_execution_content(
                    source_sha256=source.snapshot["snapshot_sha256"],
                    policy_sha256="0" * 64,
                    knowledge_id=knowledge_id,
                    parse_attempt=receipt["parse_attempt"],
                    window_id=len(source.snapshot["chunks"]),
                    phase="discover",
                    prompt="",
                ),
            )
            budget = min(
                (template.max_context_bytes - len(baseline.semantic_request)) // 6,
                (settings.max_request_bytes - len(baseline.request_bytes)) // 7,
                2 << 20,
            )
            if budget < 1:
                raise ModelPolicyDenied("native discovery envelope exceeds configured capacity")
            request = NativeDiscoveryRequest(
                source_snapshot_sha256=source.snapshot["snapshot_sha256"],
                phase="plan",
                language=language,
                granularity=granularity,
                purpose=purpose,
                max_prompt_bytes=budget,
            )
            plan = await capture(source, request)
        except failure_types as exc:
            failures.append(NativeDiscoveryFailure(knowledge_id, None, "plan", str(exc)))
            continue
        expected_windows += plan.window_count
        for window in plan.windows:
            phase = "discover"
            try:
                discovery_raw = await call(plan, window, phase)
                phase = "cite-plan"
                cite_request = request.model_copy(
                    update=dict(
                        phase="cite", window_id=window.window_id, discovery_raw=discovery_raw
                    )
                )
                citation_plan = await capture(source, cite_request, plan)
                phase = "cite"
                citation_raw = await call(citation_plan, citation_plan.windows[0], phase)
                phase = "snapshot"
                final_request = cite_request.model_copy(
                    update=dict(phase="snapshot", citation_raw=citation_raw)
                )
                snapshots.append(await capture(source, final_request, plan, citation_plan))
            except failure_types as exc:
                failures.append(
                    NativeDiscoveryFailure(knowledge_id, window.window_id, phase, str(exc))
                )
    complete = not failures and len(snapshots) == expected_windows
    keep(
        "native_discovery_coverage",
        "complete-set",
        json_bytes(
            dict(
                contract="native-discovery-coverage.830.v1",
                complete=complete,
                expected_windows=expected_windows,
                accepted_windows=[
                    dict(
                        knowledge_id=s.knowledge_id,
                        window_id=s.windows[0].window_id,
                        snapshot_sha256=s.snapshot_sha256,
                    )
                    for s in snapshots
                ],
                failures=[
                    dict(
                        knowledge_id=f.knowledge_id,
                        window_id=f.window_id,
                        phase=f.phase,
                        detail=f.detail,
                    )
                    for f in failures
                ],
            )
        ),
    )
    return NativeDiscoveryCollection(complete, tuple(snapshots), tuple(failures), tuple(drafts))
