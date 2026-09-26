"""Persistent worker: two native windows, bounded review, restart and publication.

HTTP/native ports are signed local fixtures, not live business evidence.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from insurance_harness.db.base import Base, make_session_factory
from insurance_harness.jobs import JobStore
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.platform import platform_snapshot_payload_sha256
from insurance_harness.product_ingestion.progression import admit_uploads
from tests.product_ingestion.test_native_admission import response as admitted
from tests.product_ingestion.test_native_admission_policy import policy_payload
from tests.product_ingestion.test_native_relation_policy import relation_policy
from tests.product_ingestion.test_native_runtime import NativeModel, native_settings
from tests.product_ingestion.test_pipeline_runtime import (
    SCOPE,
    TITLE,
    FixturePlatform,
    _base_snapshot_with_navigation,
    _compose,
    _finish,
    _json,
    _sha,
    _signed,
    _sqlite_engine,
    _step,
)


class MultiwindowPlatform(FixturePlatform):
    fail_preparation = True

    def __init__(self, base: Any, *, audit_only: bool = False) -> None:
        super().__init__(base)
        self.audit_only = audit_only
        source = deepcopy(self.sources[0]["snapshot"])
        source.pop("contract")
        source.pop("snapshot_sha256")
        text = source["chunks"][0]["content"]
        split = text.index("\n") + 1
        source["chunks"], source["chunk_page_mappings"] = [], []
        for index, (start, end) in enumerate(((0, split), (split, len(text)))):
            chunk_id = f"block-0-{index}"
            source["chunks"].append(
                dict(
                    id=chunk_id,
                    index=index,
                    content=text[start:end],
                    content_sha256=_sha(text[start:end].encode()),
                )
            )
            source["chunk_page_mappings"].append(
                dict(
                    chunk_id=chunk_id,
                    status="EXACT_BLOCK",
                    source_page_number=1,
                    block_global_start=start,
                    block_global_end=end,
                    page_spans=[
                        dict(
                            page_number=1,
                            block_codepoint_start=0,
                            block_codepoint_end=end - start,
                            global_codepoint_start=start,
                            global_codepoint_end=end,
                        )
                    ],
                )
            )
        source["receipt"]["chunk_count"] = 2
        self.sources = (_signed("source", source), *self.sources[1:])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.fail_preparation and request.url.path.endswith("/platform/preparations"):
            return httpx.Response(
                400, json={"success": False, "error": "fixture preparation failure"}
            )
        return super().__call__(request)

    async def native(self, scope: Any, knowledge_id: str, attempt: int, payload: bytes) -> bytes:
        request = json.loads(payload)
        phase, window_id = request["phase"], request["window_id"]
        source = self.sources[0]["snapshot"]
        windows = []
        for index, chunk in enumerate(source["chunks"]):
            if phase != "plan" and index != window_id:
                continue
            prompt = ("discover" if phase == "plan" else "cite") + f":{index}"
            windows.append(
                dict(
                    window_id=index,
                    chunk_ids=[chunk["id"]],
                    prompt=prompt,
                    prompt_sha256=_sha(prompt.encode()),
                )
            )
        body = dict(
            scope=source["scope"],
            knowledge_id=knowledge_id,
            parse_attempt=attempt,
            source_snapshot_sha256=source["snapshot_sha256"],
            policy_sha256="a" * 64,
            request_sha256=platform_snapshot_payload_sha256(request["contract"], request),
            phase=phase,
            window_count=2,
            windows=windows,
            candidates=[
                dict(
                    content_origin="MODEL_GENERATED",
                    kind="concept",
                    name=f"流程{window_id}",
                    slug=f"concept/process-{window_id}",
                    aliases=[],
                    description="阅读流程",
                    details="补充文本",
                    source_chunks=[],
                    has_source_chunks=False,
                )
            ]
            if phase == "snapshot"
            else [],
            discovery_raw_sha256=_sha(request["discovery_raw"].encode()) if phase != "plan" else "",
            citation_raw_sha256=_sha(request["citation_raw"].encode())
            if phase == "snapshot"
            else "",
        )
        if self.audit_only and phase == "snapshot" and window_id == 0:
            body["candidates"].append(
                dict(
                    content_origin="MODEL_GENERATED",
                    kind="entity",
                    name=TITLE,
                    slug="entity/current-product",
                    aliases=[],
                    description="已有产品",
                    details="已有主体",
                    source_chunks=[],
                    has_source_chunks=False,
                )
            )
        return _json(
            _signed("native-discovery" if phase == "snapshot" else "native-discovery-plan", body)
        )


class MultiwindowModel(NativeModel):
    def __init__(self, *, audit_only: bool = False) -> None:
        super().__init__()
        self.audit_only = audit_only
        self.reviews: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        context = json.loads(json.loads(request.content)["messages"][-1]["content"])
        if context.get("contract") in {
            "native-knowledge-admission-context.830.v2",
            "native-knowledge-admission-context.830.v4",
        }:
            self.admission_requests.append(context)
            assert context["isolation_enabled"] is False
            result = admitted(context)
            result["contract"] = "native-knowledge-admission.830.v2"
            result["pages"][0]["stable_key"] = f"runtime-process-{len(self.admission_requests)}"
            result["decisions"][0]["depends_on"] = []
            if self.audit_only and len(context["native_candidates"]) == 2:
                result["decisions"].append(
                    dict(
                        candidate_ref="c2",
                        decision="REFERENCE",
                        member_refs=[],
                        existing_target=context["entity"]["entity_id"],
                        reason="已有产品",
                        depends_on=[],
                    )
                )
            if context["contract"] == "native-knowledge-admission-context.830.v4":
                result["contract"] = "native-knowledge-admission.830.v4"
                page = result["pages"][0]
                page.pop("evidence")
                for segment in page["content_provenance"]["segments"]:
                    segment.pop("evidence_indexes")
                    segment["evidence_refs"] = []
        elif context.get("contract") == "product-discovery-review-context.830.v10":
            self.reviews.append(context)
            scores = {
                key: dict(
                    business_value=25,
                    reuse=20,
                    evidence_quality=0,
                    definability=15,
                    novel_identity=10,
                    name_stability=10,
                )
                for key in context["review_member_ids"]
            }
            if len(self.reviews) == 1 and not self.audit_only:
                scores[next(iter(scores))]["business_value"] = 0
            result = dict(
                contract="product-discovery-review.830.v1",
                review=dict(
                    contract="concept-review-output.830.g2.v1",
                    request_hash=context["request_hash"],
                    output_hash=context["output_hash"],
                    decision="PASS",
                    reasons=["fixture"],
                    page_scores=scores,
                ),
                disposition_checks=[
                    dict(candidate_id=row["candidate_id"], decision="ACCEPT", reason="fixture")
                    for row in context["dispositions"]
                ],
            )
            if self.audit_only and len(self.reviews) == 1:
                rejected = next(
                    row["candidate_id"]
                    for row in context["dispositions"]
                    if row["member_id"] is None
                )
                next(
                    row for row in result["disposition_checks"] if row["candidate_id"] == rejected
                )["decision"] = "REJECT"
        else:
            return super().__call__(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(result)}}]})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "crash_point", ["after_first", "after_both", "v4", "audit_first", "audit_both"]
)
async def test_multiwindow_worker_restarts_without_resending_and_publishes_survivor(
    tmp_path: Path, crash_point: str
) -> None:
    base, parent = _base_snapshot_with_navigation()
    settings = native_settings(tmp_path, parent).model_copy(
        update={
            "product_ingestion_runtime_json": SecretStr(
                json.dumps(
                    relation_policy(tmp_path) if crash_point == "v4" else policy_payload(tmp_path)
                )
            )
        }
    )
    engine = _sqlite_engine(tmp_path / "multiwindow.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    audit_only = crash_point.startswith("audit_")
    platform, model = (
        MultiwindowPlatform(base, audit_only=audit_only),
        MultiwindowModel(audit_only=audit_only),
    )
    runtime, context, client = await _compose(settings, factory, platform, model)
    context.bindings[SCOPE.space_id].platform.native_discovery = platform.native
    if context.bindings[SCOPE.space_id].native_admission_executor is not None:
        context.bindings[SCOPE.space_id].native_admission_executor._client = client
    origin = context.store.create_run(
        scope=SCOPE, idempotency_key="multiwindow", expected_upload_count=1
    )
    admit_uploads(context.store, SCOPE, origin.run_id)
    prepare = context.artifacts.prepare_artifact_writes
    crashed = False

    def crash(**kwargs: Any) -> Any:
        nonlocal crashed
        if not crashed and any(
            row.artifact_kind == "native_review_pruning" for row in kwargs["drafts"]
        ):
            crashed = True
            raise RuntimeError("fixture crash after both durable review calls")
        return prepare(**kwargs)

    if crash_point in {"after_both", "v4", "audit_both"}:
        context.artifacts.prepare_artifact_writes = crash
    else:
        executor = context.bindings[SCOPE.space_id].model_executor
        execute = executor.execute_stage_call

        async def crash_after_first(**kwargs: Any) -> Any:
            nonlocal crashed
            result = await execute(**kwargs)
            if not crashed and kwargs.get("stage_key") == "compilation":
                crashed = True
                raise RuntimeError("fixture crash after first durable review")
            return result

        executor.execute_stage_call = crash_after_first
    try:
        for _ in range(40):
            await _step(runtime, jobs)
            if crashed:
                break
        assert crashed, (runtime.issues, context.store.get_run(scope=SCOPE, run_id=origin.run_id))
        assert len(model.reviews) == (1 if crash_point in {"after_first", "audit_first"} else 2)
        await runtime.close()
        await client.aclose()
        runtime, context, client = await _compose(settings, factory, platform, model)
        context.bindings[SCOPE.space_id].platform.native_discovery = platform.native
        if context.bindings[SCOPE.space_id].native_admission_executor is not None:
            context.bindings[SCOPE.space_id].native_admission_executor._client = client
        first = await _finish(runtime, context, jobs, origin.run_id)
        assert len(model.reviews) == 2, "restart resent recorded reviews"
        assert len(model.admission_requests) == 2
        summary = json.loads(
            context.artifacts.get_effective_artifact(
                scope=SCOPE, run_id=origin.run_id, artifact_kind="discovery_final_summary"
            ).payload
        )
        assert summary["state"] == "ACCEPTED", summary
        assert summary["pending_candidate_count"] == 1
        platform.fail_preparation = False
        child = context.store.retry_processing(
            scope=SCOPE, run_id=first.run_id, expected_version=first.version
        )
        terminal = await _finish(runtime, context, jobs, child.run_id)
        assert terminal.state in {ProductRunState.SUCCEEDED, ProductRunState.PARTIAL_SUCCESS}, (
            terminal.terminal_reason,
            runtime.issues,
        )
        assert len(model.reviews) == len(model.admission_requests) == 2
        assert platform.activations == 1
        new_pages = [
            page
            for page in platform.candidate.compile_result.output.pages
            if page.stable_key.startswith("runtime-process-")
        ]
        assert len(new_pages) == (2 if audit_only else 1)
        if audit_only:
            assert model.reviews[0]["output_hash"] == model.reviews[1]["output_hash"]
            assert model.reviews[0]["dispositions"] != model.reviews[1]["dispositions"]
    finally:
        await runtime.close()
        await client.aclose()
        engine.dispose()
