"""Native opt-in through the durable worker; all external ports are local fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from insurance_harness.db.base import Base, make_session_factory
from insurance_harness.jobs import JobStore
from insurance_harness.product_ingestion.discovery import PROVENANCE_DISCOVERY_REVIEW_PROMPT
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.native_admission_contract import (
    NATIVE_ADMISSION_PROMPT,
)
from insurance_harness.product_ingestion.native_discovery import NATIVE_DISCOVERY_EXECUTION_PROMPT
from insurance_harness.product_ingestion.platform import platform_snapshot_payload_sha256
from insurance_harness.product_ingestion.progression import admit_uploads
from tests.product_ingestion.test_pipeline_runtime import (
    SCOPE,
    FixtureModel,
    FixturePlatform,
    _base_snapshot_with_navigation,
    _compose,
    _finish,
    _json,
    _published_snapshot,
    _settings,
    _sha,
    _signed,
    _source_snapshot,
    _sqlite_engine,
)


def native_settings(tmp_path: Path, parent: Any) -> Any:
    settings = _settings(tmp_path, parent)
    data = json.loads(settings.product_ingestion_runtime_json.get_secret_value())
    binding = data["bindings"][0]
    binding["native_discovery"] = dict(
        policy="native-candidates.830.v1",
        language="Chinese",
        granularity="standard",
        purpose="材料知识发现",
        allow_knowledge_updates=True,
    )
    for role, purpose, prompt in (
        ("extract", "g3-native-discovery", NATIVE_DISCOVERY_EXECUTION_PROMPT),
        ("extract", "g3-native-admission", NATIVE_ADMISSION_PROMPT),
        ("verify", "g3-provenance-discovery-review", PROVENANCE_DISCOVERY_REVIEW_PROMPT),
    ):
        binding["model"]["templates"].append(
            dict(
                template_id=purpose,
                role=role,
                purpose=purpose,
                run_schema_version="830-g3-v1",
                prompt_sha256=_sha(prompt),
                max_context_bytes=8 * 1024 * 1024,
                max_output_tokens=8192,
            )
        )
    return settings.model_copy(
        update={"product_ingestion_runtime_json": SecretStr(_json(data).decode())}
    )


class NativeModel(FixtureModel):
    def __init__(self) -> None:
        super().__init__()
        self.native_requests: list[dict[str, Any]] = []
        self.admission_requests: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        envelope = json.loads(request.content)
        content = json.loads(envelope["messages"][-1]["content"])
        if content.get("contract") == "native-knowledge-admission-context.830.v1":
            self.admission_requests.append(content)
            semantic = {
                "contract": "native-knowledge-admission.830.v1",
                "definitions": [],
                "pages": [],
                "decisions": [
                    {
                        "candidate_ref": row["candidate_ref"],
                        "decision": "REJECT",
                        "member_refs": [],
                        "existing_target": None,
                        "reason": "无独立知识用途",
                    }
                    for row in content["native_candidates"]
                ],
            }
            return httpx.Response(
                200, json={"choices": [{"message": {"content": _json(semantic).decode()}}]}
            )
        if content.get("contract") != "native-discovery-execution.830.v1":
            return super().__call__(request)
        self.native_requests.append(content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"entities":[],"concepts":[]}'}}]}
        )


class NativePort:
    fail = True

    async def __call__(self, scope: Any, knowledge_id: str, attempt: int, payload: bytes) -> bytes:
        request = json.loads(payload)
        phase = request["phase"]
        ordinal = int(knowledge_id.rsplit("-", 1)[1])
        if self.fail and ordinal == 1 and phase == "snapshot":
            raise ValueError("fixture sibling snapshot failure")
        source = _source_snapshot(ordinal)["snapshot"]
        prompt = ("discover" if phase == "plan" else "cite") + ":" + knowledge_id
        body = dict(
            scope=source["scope"],
            knowledge_id=knowledge_id,
            parse_attempt=attempt,
            source_snapshot_sha256=source["snapshot_sha256"],
            policy_sha256="a" * 64,
            request_sha256=platform_snapshot_payload_sha256(request["contract"], request),
            phase=phase,
            window_count=1,
            windows=[
                dict(
                    window_id=0,
                    chunk_ids=[source["chunks"][0]["id"]],
                    prompt=prompt,
                    prompt_sha256=_sha(prompt.encode()),
                )
            ],
            candidates=[
                dict(
                    content_origin="MODEL_GENERATED",
                    kind="concept",
                    name="测试候选",
                    slug="concept/test",
                    aliases=[],
                    description="待判断的候选",
                    details="补充文本",
                    source_chunks=[],
                    has_source_chunks=False,
                )
            ]
            if phase == "snapshot" and ordinal == 0
            else [],
            discovery_raw_sha256=_sha(request["discovery_raw"].encode()) if phase != "plan" else "",
            citation_raw_sha256=_sha(request["citation_raw"].encode())
            if phase == "snapshot"
            else "",
        )
        return _json(
            _signed("native-discovery" if phase == "snapshot" else "native-discovery-plan", body)
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("policy_drift", [False, True])
async def test_three_generation_native_recovery_keeps_original_calls_and_update_policy(
    tmp_path: Path,
    policy_drift: bool,
) -> None:
    base, parent = _base_snapshot_with_navigation()
    settings = native_settings(tmp_path, parent)
    engine = _sqlite_engine(tmp_path / "native.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model, native = FixturePlatform(base), NativeModel(), NativePort()
    runtime, context, client = await _compose(settings, factory, platform, model)
    context.bindings[SCOPE.space_id].platform.native_discovery = native
    try:
        origin = context.store.create_run(
            scope=SCOPE, idempotency_key="native-origin", expected_upload_count=3
        )
        admit_uploads(context.store, SCOPE, origin.run_id)
        first = await _finish(runtime, context, jobs, origin.run_id)
        assert len(model.native_requests) == 6, (first.terminal_reason, runtime.issues)
        assert len(model.admission_requests) == 1
        assert first.state is ProductRunState.PARTIAL_SUCCESS
        saved = context.artifacts.get_artifact(
            scope=SCOPE,
            run_id=origin.run_id,
            artifact_kind="compile_request",
            artifact_key="product",
        )
        assert (
            json.loads(saved.payload)["knowledge_update_policy"] == "explicit-same-identity.830.v1"
        )
        child = context.store.retry_processing(
            scope=SCOPE, run_id=origin.run_id, expected_version=first.version
        )
        if policy_drift:
            await runtime.close()
            await client.aclose()
            updated = json.loads(settings.product_ingestion_runtime_json.get_secret_value())
            updated["bindings"][0]["native_discovery"]["purpose"] = "changed-purpose"
            settings = settings.model_copy(
                update={"product_ingestion_runtime_json": SecretStr(_json(updated).decode())}
            )
            runtime, context, client = await _compose(settings, factory, platform, model)
            context.bindings[SCOPE.space_id].platform.native_discovery = native
        second = await _finish(runtime, context, jobs, child.run_id)
        if policy_drift:
            assert second.state is ProductRunState.NEEDS_CONFIRMATION
            assert second.terminal_reason == "CHECKPOINT_COMPILE_INPUT_INVALID"
            assert len(model.native_requests) == 6
            assert len(model.admission_requests) == 1
            return
        assert second.state is ProductRunState.PARTIAL_SUCCESS, (
            second.terminal_reason,
            runtime.issues,
        )
        assert len(model.native_requests) == 6
        assert len(model.admission_requests) == 1
        assert not [
            c
            for c in context.artifacts.list_stage_calls(scope=SCOPE, run_id=child.run_id)
            if c.stage_key == "discovery"
        ]
        # An unrelated new head reprojects against current inputs. Identical semantic
        # admission context can reuse raw; the old compiled output is never reused.
        platform.base = _published_snapshot(
            parent, release_id="native-unrelated-head", activation_epoch=10
        )
        platform.current = dict(release_id="native-unrelated-head", activation_epoch=10)
        native.fail = False
        grandchild = context.store.retry_processing(
            scope=SCOPE, run_id=child.run_id, expected_version=second.version
        )
        plan = context.store.checkpoint_plan(scope=SCOPE, run_id=grandchild.run_id)
        assert (
            len([c for c in plan.audited_calls if c.run_id == origin.run_id and c.kind == "stage"])
            >= 6
        )
        third = await _finish(runtime, context, jobs, grandchild.run_id)
        assert third.state in {ProductRunState.SUCCEEDED, ProductRunState.PARTIAL_SUCCESS}, (
            third.terminal_reason,
            runtime.issues,
        )
        assert len(model.native_requests) == 6
        assert len(model.admission_requests) == 1
        rebased = context.artifacts.get_rebased_artifact(
            scope=SCOPE, run_id=grandchild.run_id, artifact_kind="rebased_compile_request"
        )
        assert (
            json.loads(rebased.payload)["knowledge_update_policy"]
            == "explicit-same-identity.830.v1"
        )
        summary = context.artifacts.get_artifact(
            scope=SCOPE,
            run_id=grandchild.run_id,
            artifact_kind="discovery_summary",
            artifact_key="product",
        )
        assert json.loads(summary.payload)["state"] == "EMPTY"
        receipts = context.artifacts.list_effective_artifacts(
            scope=SCOPE, run_id=grandchild.run_id, artifact_kind="native_discovery_execution"
        )
        assert len(receipts) == 6
        assert {json.loads(r.payload)["replayed_from_run_id"] for r in receipts} == {origin.run_id}
    finally:
        await runtime.close()
        await client.aclose()
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("later_compilation_failure", [False, True])
@pytest.mark.parametrize("wire_upgrade", [False, True])
async def test_member_guidance_upgrade_reuses_source_fields_and_native_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    later_compilation_failure: bool,
    wire_upgrade: bool,
) -> None:
    from insurance_harness.product_ingestion import compilation, native_admission_stage
    from insurance_harness.product_ingestion.discovery import DEPENDENCY_DISCOVERY_REVIEW_PROMPT

    base, parent = _base_snapshot_with_navigation()
    settings = native_settings(tmp_path, parent)
    data = json.loads(settings.product_ingestion_runtime_json.get_secret_value())
    binding = data["bindings"][0]
    binding["native_discovery"]["dependency_policy"] = "candidate-dependencies.830.v1"
    for template in binding["model"]["templates"]:
        if template["purpose"] == "g3-native-admission":
            # Approved v2 system prompt from 37ae768ba; context guidance must not
            # silently require a new global policy or repeat successful work.
            template["prompt_sha256"] = (
                "1c051df03d2a7753213eb1829becf894ddcb054c30688eed217ccd6afd07c965"
            )
    binding["model"]["templates"].append(
        dict(
            template_id="g3-dependency-discovery-review",
            role="verify",
            purpose="g3-dependency-discovery-review",
            run_schema_version="830-g3-v1",
            prompt_sha256=_sha(DEPENDENCY_DISCOVERY_REVIEW_PROMPT),
            max_context_bytes=8 * 1024 * 1024,
            max_output_tokens=8192,
        )
    )
    settings = settings.model_copy(
        update={
            "product_ingestion_runtime_json": SecretStr(_json(data).decode()),
        }
    )

    class MemberModel(NativeModel):
        def __call__(self, request: httpx.Request) -> httpx.Response:
            envelope = json.loads(request.content)
            content = json.loads(envelope["messages"][-1]["content"])
            if content.get("contract") in {
                "native-knowledge-admission-context.830.v2",
                "native-knowledge-admission-context.830.v3",
            }:
                self.admission_requests.append(content)
                semantic = {
                    "contract": content["contract"].replace("-context", ""),
                    "definitions": [],
                    "pages": [],
                    "decisions": [
                        {
                            "candidate_ref": row["candidate_ref"],
                            "decision": "REJECT",
                            "member_refs": [],
                            "existing_target": None,
                            "reason": "无独立用途",
                            "depends_on": [],
                        }
                        for row in content["native_candidates"]
                    ],
                }
                return httpx.Response(
                    200, json={"choices": [{"message": {"content": _json(semantic).decode()}}]}
                )
            return super().__call__(request)

    engine = _sqlite_engine(tmp_path / "member-guidance.db")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    jobs = JobStore(factory, settings.job_runtime_config())
    platform, model, native = FixturePlatform(base), MemberModel(), NativePort()
    runtime, context, client = await _compose(settings, factory, platform, model)
    context.bindings[SCOPE.space_id].platform.native_discovery = native
    current_render = native_admission_stage.render_native_admission_context
    assemble = compilation.assemble_platform_candidate

    def fail_compilation(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("fixture compilation failure after failed admission")

    def previous_context(**kwargs: Any) -> Any:
        value = current_render(**kwargs)
        value.pop("member_contract", None)
        return value

    try:
        # A recorded response from the old input survives a failed discovery.
        # The current strict projector rejects the old context; no permissive
        # production path or business result is fabricated for this fixture.
        monkeypatch.setattr(
            native_admission_stage, "render_native_admission_context", previous_context
        )
        if later_compilation_failure:
            monkeypatch.setattr(compilation, "assemble_platform_candidate", fail_compilation)
        origin = context.store.create_run(
            scope=SCOPE, idempotency_key="member-old", expected_upload_count=3
        )
        admit_uploads(context.store, SCOPE, origin.run_id)
        first = await _finish(runtime, context, jobs, origin.run_id)
        expected = (
            ProductRunState.FAILED if later_compilation_failure else ProductRunState.PARTIAL_SUCCESS
        )
        assert first.state is expected, (
            first.terminal_reason,
            runtime.issues,
        )
        assert len(model.native_requests) == 6 and len(model.admission_requests) == 1
        counts = (platform.source_captures, len(model.identity_requests), len(model.field_requests))
        monkeypatch.setattr(
            native_admission_stage, "render_native_admission_context", current_render
        )
        monkeypatch.setattr(compilation, "assemble_platform_candidate", assemble)
        native.fail = False
        if wire_upgrade:
            from tests.product_ingestion.test_native_admission_policy import add_override

            await runtime.close()
            await client.aclose()
            add_override(data)
            settings = settings.model_copy(update={
                "product_ingestion_runtime_json": SecretStr(_json(data).decode()),
            })
            runtime, context, client = await _compose(settings, factory, platform, model)
            service = context.bindings[SCOPE.space_id]
            service.platform.native_discovery = native
            service.native_admission_executor._client = client
            monkeypatch.setattr(compilation, "assemble_platform_candidate", fail_compilation)
        child = context.store.retry_processing(
            scope=SCOPE, run_id=origin.run_id, expected_version=first.version
        )
        plan = context.store.checkpoint_plan(scope=SCOPE, run_id=child.run_id)
        assert plan.resume_stage == "discovery"
        assert plan.failed_discovery_artifact.artifact_kind == "discovery_summary"
        second = await _finish(runtime, context, jobs, child.run_id)
        assert second.state in (
            {ProductRunState.FAILED} if wire_upgrade
            else {ProductRunState.SUCCEEDED, ProductRunState.PARTIAL_SUCCESS}
        ), (
            second.terminal_reason,
            runtime.issues,
        )
        assert counts == (
            platform.source_captures,
            len(model.identity_requests),
            len(model.field_requests),
        )
        assert len(model.native_requests) == 6
        assert len(model.admission_requests) == 2
        assert "member_contract" not in model.admission_requests[0]
        assert "member_contract" in model.admission_requests[1]
        if wire_upgrade:
            assert model.admission_requests[1]["contract"].endswith(".v3")
        calls = context.artifacts.list_stage_calls(scope=SCOPE, run_id=child.run_id)
        discovery_calls = [c for c in calls if c.stage_key == "discovery"]
        assert len(discovery_calls) == 1
        new = discovery_calls[0]
        assert new.operation_key.startswith("native-admission-")
        assert new.request_sha256 == _sha(new.request_bytes)
        assert new.raw_sha256 == _sha(new.raw)
        assert new.input_sha256 == _sha(_json(model.admission_requests[1]))
        receipts = context.artifacts.list_effective_artifacts(
            scope=SCOPE, run_id=child.run_id, artifact_kind="native_discovery_execution"
        )
        assert len(receipts) == 6
        assert {json.loads(r.payload)["replayed_from_run_id"] for r in receipts} == {origin.run_id}
        if wire_upgrade:
            from dataclasses import replace
            from types import MappingProxyType

            from insurance_harness.product_ingestion.checkpoint_validation import (
                CheckpointValidationError,
                validate_checkpoint,
            )

            monkeypatch.setattr(compilation, "assemble_platform_candidate", assemble)
            grandchild = context.store.retry_processing(
                scope=SCOPE, run_id=child.run_id, expected_version=second.version,
            )
            plan = context.store.checkpoint_plan(scope=SCOPE, run_id=grandchild.run_id)
            assert plan.resume_stage == "compilation"
            checkpoint = context.store.list_stages(scope=SCOPE, run_id=grandchild.run_id)[0]
            await validate_checkpoint(context, SCOPE, grandchild, checkpoint)
            service = context.bindings[SCOPE.space_id]
            override = service.configuration.native_admission
            for changed_override in (None, override.model_copy(update={
                "template": override.template.model_copy(update={
                    "max_output_tokens": 8193,
                }),
            })):
                changed_settings = service.configuration.settings.model_copy(update={
                    "native_admission": changed_override,
                })
                changed_service = replace(service, configuration=replace(
                    service.configuration, settings=changed_settings,
                ))
                changed_context = replace(context, bindings=MappingProxyType({
                    SCOPE.space_id: changed_service,
                }))
                with pytest.raises(CheckpointValidationError):
                    await validate_checkpoint(changed_context, SCOPE, grandchild, checkpoint)
            third = await _finish(runtime, context, jobs, grandchild.run_id)
            assert third.state in {ProductRunState.SUCCEEDED, ProductRunState.PARTIAL_SUCCESS}
            assert len(model.native_requests) == 6 and len(model.admission_requests) == 2
    finally:
        await runtime.close()
        await client.aclose()
        engine.dispose()
