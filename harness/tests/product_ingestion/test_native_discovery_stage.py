"""Signed native windows use the existing persisted model-call port."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import HttpUrl, SecretStr

from insurance_harness.product_ingestion.model_settings import (
    ModelTemplatePolicy,
    ProductModelSettings,
)
from insurance_harness.product_ingestion.native_discovery import NATIVE_DISCOVERY_EXECUTION_PROMPT
from insurance_harness.product_ingestion.platform import (
    DecodedSourceSnapshot,
    platform_snapshot_payload_sha256,
)
from tests.product_ingestion.test_native_discovery import KEY, SCOPE, canonical, signed


class NativePlatform:
    def __init__(self, vector: dict[str, Any]) -> None:
        self.vector = vector
        self.fail_window: int | None = None

    async def native_discovery(
        self, scope: Any, knowledge_id: str, attempt: int, payload: bytes
    ) -> bytes:
        assert scope == SCOPE
        request = json.loads(payload)
        phase = request["phase"]
        if phase == "snapshot" and request["window_id"] == self.fail_window:
            raise ValueError("SYNTHETIC_WINDOW_FAILURE")
        body = deepcopy(
            self.vector["envelopes"][{"plan": 0, "cite": 1, "snapshot": 2}[phase]]["snapshot"]
        )
        body.update(
            knowledge_id=knowledge_id,
            parse_attempt=attempt,
            request_sha256=platform_snapshot_payload_sha256(request["contract"], request),
            window_count=2,
        )
        windows = []
        for i, chunk in enumerate(self.vector["source"]["chunks"]):
            prompt = ("discover" if phase == "plan" else "cite") + ":" + chunk["id"]
            windows.append(
                dict(
                    window_id=i,
                    chunk_ids=[chunk["id"]],
                    prompt=prompt,
                    prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                )
            )
        body["windows"] = windows if phase == "plan" else [windows[request["window_id"]]]
        body["discovery_raw_sha256"] = (
            hashlib.sha256(request["discovery_raw"].encode()).hexdigest() if phase != "plan" else ""
        )
        body["citation_raw_sha256"] = (
            hashlib.sha256(request["citation_raw"].encode()).hexdigest()
            if phase == "snapshot"
            else ""
        )
        if phase == "snapshot":
            for row in body["candidates"]:
                if row["source_chunks"]:
                    row["source_chunks"] = body["windows"][0]["chunk_ids"]
        return signed(body)


class ModelJournal:
    def __init__(self, vector: dict[str, Any]) -> None:
        self.vector = vector
        self.calls: list[dict[str, Any]] = []
        self.records: dict[str, Any] = {}
        self.unknown_prompt: str | None = None

    async def execute_stage_call(self, **kwargs: Any) -> Any:
        prompt = json.loads(kwargs["content"])["prompt"]
        key = kwargs["operation_key"]
        if key in self.records:
            return self.records[key]
        self.calls.append(kwargs)
        if prompt == self.unknown_prompt:
            result = SimpleNamespace(
                state="interrupted",
                raw=None,
                diagnostic="outcome_unknown",
                policy_receipt=None,
                call_id="unknown-call",
            )
        else:
            text = self.vector["requests"][1 if prompt.startswith("discover") else 2][
                "discovery_raw" if prompt.startswith("discover") else "citation_raw"
            ]
            result = SimpleNamespace(
                state="recorded",
                raw=canonical({"choices": [{"message": {"content": text}}]}),
                diagnostic=None,
                policy_receipt=object(),
                call_id="call-" + str(len(self.calls)),
            )
        self.records[key] = result
        return result


@pytest.fixture
def native_runtime() -> tuple[Any, ...]:
    vector = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "internal/application/service/testdata/g3_native_discovery_v1.json"
        ).read_bytes()
    )
    template = ModelTemplatePolicy(
        template_id="native-candidate-v1",
        role="extract",
        purpose="g3-native-discovery",
        run_schema_version="830-g3-v1",
        prompt_sha256=hashlib.sha256(NATIVE_DISCOVERY_EXECUTION_PROMPT).hexdigest(),
        max_context_bytes=100000,
        max_output_tokens=10000,
    )
    settings = ProductModelSettings(
        scope=SCOPE,
        endpoint=HttpUrl("https://fixture.invalid/v1/chat/completions"),
        api_key=SecretStr("synthetic-never-used"),
        model="gemini-3.7-flash-medium",
        policy_version="g3-user-gemini-gateway-v1",
        expires_at=datetime(2100, 1, 1, tzinfo=UTC),
        templates=(template,),
        field_template_id=template.template_id,
        max_request_bytes=200000,
        max_response_bytes=200000,
        timeout_seconds=60.0,
    )
    source = DecodedSourceSnapshot(
        snapshot=vector["source"],
        blocks=(),
        first_page_ranges={},
        unresolved_chunk_ids=(),
        native_bytes=b"",
    )
    platform = NativePlatform(vector)
    model = ModelJournal(vector)
    service = SimpleNamespace(
        configuration=SimpleNamespace(
            model=settings, source_public_keys={"fixture": KEY.public_key()}
        ),
        platform=platform,
        model_executor=model,
    )
    return source, service, SimpleNamespace(list_stage_calls=lambda **kwargs: []), model


async def collect(runtime: tuple[Any, ...], *, retry_of: str | None = None) -> Any:
    from insurance_harness.product_ingestion.native_discovery_stage import collect_native_discovery

    source, service, store, _ = runtime
    return await collect_native_discovery(
        service=service,
        artifacts=store,
        scope=SCOPE,
        run=SimpleNamespace(run_id="run", retry_of_run_id=retry_of),
        stage=SimpleNamespace(dependency_sha256="b" * 64),
        job=SimpleNamespace(id="job", lease_generation=1),
        sources=(source,),
        language="Chinese",
        granularity="standard",
        purpose="帮助理解保险材料",
    )


@pytest.mark.asyncio
async def test_native_stage_collects_every_signed_window_after_persisted_calls(
    native_runtime: tuple[Any, ...],
) -> None:
    result = await collect(native_runtime)
    assert result.complete
    assert [row.windows[0].window_id for row in result.snapshots] == [0, 1]
    assert len(native_runtime[-1].calls) == 4
    assert (
        len([row for row in result.drafts if row.artifact_kind == "native_candidate_snapshot"]) == 2
    )
    assert all(
        row.content_origin == "MODEL_GENERATED"
        for snapshot in result.snapshots
        for row in snapshot.candidates
    )


@pytest.mark.asyncio
async def test_native_stage_keeps_siblings_and_reuses_success_after_projection_failure(
    native_runtime: tuple[Any, ...],
) -> None:
    _, service, _, model = native_runtime
    service.platform.fail_window = 1
    first = await collect(native_runtime)
    assert not first.complete and len(first.snapshots) == 1 and len(first.failures) == 1
    assert len(model.calls) == 4
    service.platform.fail_window = None
    second = await collect(native_runtime)
    assert second.complete and len(second.snapshots) == 2
    assert len(model.calls) == 4


@pytest.mark.asyncio
async def test_native_stage_does_not_resend_unknown_model_attempt(
    native_runtime: tuple[Any, ...],
) -> None:
    model = native_runtime[-1]
    model.unknown_prompt = "discover:block-b"
    result = await collect(native_runtime)
    assert not result.complete and len(result.snapshots) == 1
    assert len(model.calls) == 3
    again = await collect(native_runtime)
    assert not again.complete and len(model.calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("ancestor", [False, True])
async def test_native_stage_revalidates_parent_calls_without_resending(
    native_runtime: tuple[Any, ...],
    ancestor: bool,
) -> None:
    from insurance_harness.product_ingestion.model_execution import ConfiguredModelExecutor

    _, service, store, model = native_runtime
    await collect(native_runtime)
    settings = service.configuration.model
    executor = ConfiguredModelExecutor(settings_provider=lambda: settings)
    transport = executor.field_transport(
        SCOPE, "parent", SimpleNamespace(), prompt=NATIVE_DISCOVERY_EXECUTION_PROMPT
    )
    records = []
    for args in model.calls:
        prepared = transport.prepare(args["content"])
        result = model.records[args["operation_key"]]
        records.append(
            SimpleNamespace(
                run_id="ancestor" if ancestor else "parent",
                stage_key="discovery",
                operation_key=args["operation_key"],
                input_sha256=args["input_sha256"],
                prompt_policy_sha256=hashlib.sha256(NATIVE_DISCOVERY_EXECUTION_PROMPT).hexdigest(),
                model_policy_sha256=settings.policy_sha256,
                request_bytes=prepared.request_bytes,
                request_sha256=prepared.request_sha256,
                raw=result.raw,
                raw_sha256=hashlib.sha256(result.raw).hexdigest(),
                state="recorded",
                diagnostic=None,
                dispatched_at=datetime.now(UTC),
                recorded_at=datetime.now(UTC),
                call_id=result.call_id,
            )
        )
    store.list_stage_calls = lambda **kwargs: [] if ancestor else records
    store.read_checkpoint_stage_calls = lambda **kwargs: records if ancestor else []

    async def forbidden(**kwargs: Any) -> Any:
        raise AssertionError("recorded parent must not be redispatched")

    model.execute_stage_call = forbidden
    outcome = await collect(native_runtime, retry_of="parent")
    assert outcome.complete
    receipts = [
        json.loads(row.payload)
        for row in outcome.drafts
        if row.artifact_kind == "native_discovery_execution"
    ]
    assert len(receipts) == 4 and all(
        row["replayed_from_run_id"] == ("ancestor" if ancestor else "parent") for row in receipts
    )
    records[0].state = "interrupted"
    records[0].raw = None
    failed = await collect(native_runtime, retry_of="parent")
    assert not failed.complete and len(failed.snapshots) == 1
    assert "DISCOVERY_REPLAY_OUTCOME_UNKNOWN" in failed.failures[0].detail


@pytest.mark.asyncio
@pytest.mark.parametrize("context_limit,request_limit", [(4096, 10000), (10000, 4096)])
async def test_native_prompt_budget_includes_worst_case_serialized_envelopes(
    native_runtime: tuple[Any, ...],
    context_limit: int,
    request_limit: int,
) -> None:
    from insurance_harness.product_ingestion.model_execution import ConfiguredModelExecutor
    from insurance_harness.product_ingestion.stages import json_bytes

    source, service, _, _model = native_runtime
    settings = service.configuration.model
    template = settings.templates[0].model_copy(update={"max_context_bytes": context_limit})
    settings = settings.model_copy(
        update={"templates": (template,), "max_request_bytes": request_limit}
    )
    service.configuration.model = settings
    captured = []
    platform_call = service.platform.native_discovery

    async def capture(scope: Any, knowledge_id: str, attempt: int, payload: bytes) -> bytes:
        captured.append(json.loads(payload))
        return await platform_call(scope, knowledge_id, attempt, payload)

    service.platform.native_discovery = capture
    result = await collect(native_runtime)
    assert result.complete
    budget = captured[0]["max_prompt_bytes"]
    transport = ConfiguredModelExecutor(settings_provider=lambda: settings).field_transport(
        SCOPE, "run", SimpleNamespace(), prompt=NATIVE_DISCOVERY_EXECUTION_PROMPT
    )
    for marker in ("\x00", '"', "\\", "\n"):
        prompt = marker * budget
        content = json_bytes(
            dict(
                contract="native-discovery-execution.830.v1",
                source_snapshot_sha256=source.snapshot["snapshot_sha256"],
                policy_sha256="a" * 64,
                phase="discover",
                knowledge_id=source.snapshot["receipt"]["knowledge_id"],
                parse_attempt=source.snapshot["receipt"]["parse_attempt"],
                window_id=len(source.snapshot["chunks"]),
                prompt=prompt,
                prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
            )
        )
        prepared = transport.prepare(content)
        assert len(prepared.semantic_request) <= context_limit
        assert len(prepared.request_bytes) <= request_limit
