from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from test_configuration import settings

from insurance_harness.db.base import Base, make_engine, make_session_factory
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.stages import StageOutput
from insurance_harness.service_shell.config import ShellConfigError
from insurance_harness.service_shell.health import Lifecycle


def pipeline_ports(context, *, omitted: str | None = None):
    from insurance_harness.product_ingestion.composition import ProductPipelinePorts

    names = {
        "identity",
        "field_plan",
        "extract",
        "synthesis",
        "discovery",
        "compilation",
        "preparation",
        "review",
        "publish",
        "verify",
    }

    async def stage(*_args):
        return StageOutput(state=ProductRunState.SUCCEEDED)

    return ProductPipelinePorts(
        stage_handlers={name: stage for name in names if name != omitted},
        read_window_plan=lambda _scope, _run_id: (),
        field_prompt=lambda _scope: b"field prompt",
    )


def runtime(tmp_path: Path, factory=pipeline_ports):
    from insurance_harness.product_ingestion.composition import compose_product_worker

    engine = make_engine(f"sqlite:///{tmp_path}/composition.db")
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    lifecycle = Lifecycle()
    result = compose_product_worker(
        settings=settings(tmp_path),
        lifecycle=lifecycle,
        session_factory=session_factory,
        pipeline_factory=factory,
    )
    return engine, session_factory, lifecycle, result


def test_composition_registers_complete_product_runtime_against_one_database(
    tmp_path: Path,
) -> None:
    engine, session_factory, _lifecycle, result = runtime(tmp_path)
    try:
        assert set(result.registry.handlers) == {
            "product_stage_uploads",
            "product_stage_source",
            "product_stage_routing",
            "product_stage_identity",
            "product_stage_field_plan",
            "product_stage_extract",
            "product_stage_synthesis",
            "product_stage_discovery",
            "product_stage_compilation",
            "product_stage_preparation",
            "product_stage_review",
            "product_stage_publish",
            "product_stage_verify",
            "product_extraction_window",
            "product_ingestion_root",
        }
        assert result.session_factory is session_factory
        assert result.issues == ()
    finally:
        asyncio.run(result.close())
        engine.dispose()


def test_composition_refuses_enabled_runtime_with_any_missing_real_stage(
    tmp_path: Path,
) -> None:
    with pytest.raises(ShellConfigError) as caught:
        runtime(tmp_path, lambda context: pipeline_ports(context, omitted="review"))
    assert caught.value.keys == ("product_ingestion_pipeline",)


@pytest.mark.asyncio
async def test_composed_runtime_starts_pump_and_closes_platform_on_drain(
    tmp_path: Path,
) -> None:
    engine, _session_factory, lifecycle, result = runtime(tmp_path)
    pump_calls = 0

    async def pump_run(observed: Lifecycle) -> None:
        nonlocal pump_calls
        assert observed is lifecycle
        pump_calls += 1
        observed.begin_drain()

    result.pump.run = pump_run
    lifecycle.mark_serving()
    try:
        await asyncio.wait_for(result.run(), timeout=2)
        assert pump_calls == 1
        assert all(client.client.is_closed for client in result.platform_clients)
    finally:
        await result.close()
        engine.dispose()


def test_cli_enabled_worker_requires_real_pipeline_factory_and_disabled_is_unchanged(
    tmp_path: Path,
) -> None:
    from insurance_harness.service_shell import cli

    engine = make_engine(f"sqlite:///{tmp_path}/cli.db")
    Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)
    try:
        with pytest.raises(ShellConfigError) as caught:
            cli.build_worker_loop(
                settings=settings(tmp_path),
                lifecycle=Lifecycle(),
                session_factory=session_factory,
                product_pipeline_factory=None,
            )
        assert caught.value.keys == ("product_ingestion_pipeline",)
        plain = cli.build_worker_loop(
            settings=settings(tmp_path).model_copy(update={"product_ingestion_enabled": False}),
            lifecycle=Lifecycle(),
            session_factory=session_factory,
        )
        assert plain._registry.handlers == {}
    finally:
        engine.dispose()


def test_window_plan_identity_uses_current_scope_and_metadata_only():
    from types import SimpleNamespace

    from insurance_harness.product_ingestion.composition import _scoped_window_plan_identity
    from insurance_harness.product_ingestion.models import ProductScope

    scope = ProductScope(
        tenant_id="1", space_id="s", raw_knowledge_base_id="r", wiki_knowledge_base_id="w"
    )
    refs = [SimpleNamespace(artifact_key="product", artifact_id="sealed-1")]
    calls = []

    def metadata(**kw):
        calls.append(kw)
        return tuple(refs)

    reader = _scoped_window_plan_identity(
        SimpleNamespace(list_effective_artifact_references=metadata),
        {"s": SimpleNamespace(scope=scope)},
    )
    assert reader(scope, "run")[0].artifact_id == "sealed-1"
    assert calls == [dict(scope=scope, run_id="run", artifact_kind="field_plan")]
    with pytest.raises(ValueError, match="outside configured"):
        reader(scope.model_copy(update={"tenant_id": "2"}), "run")
    assert len(calls) == 1
    refs.clear()
    with pytest.raises(ValueError, match="unique authorized"):
        reader(scope, "run")


@pytest.mark.asyncio
async def test_duplicate_material_resolution_through_production_scope_adapter():
    import json
    from types import SimpleNamespace

    import httpx

    from insurance_harness.product_ingestion.composition import _ScopedPlatform
    from insurance_harness.product_ingestion.upload_manifest import UploadManifest
    from insurance_harness.product_ingestion.upload_resolution import lookup_material
    from tests.product_ingestion.test_platform_client import client
    from tests.product_ingestion.test_upload_manifest_admission import manifest

    seen = []
    sha = "0" * 63 + "1"

    def respond(request):
        seen.append(request)
        if "/platform/uploads/" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json={"success": True, "data": {
            "contract": "g3-platform-file-fingerprint.830.v1",
            "knowledge_id": "existing",
            "file_name": "old.pdf",
            "file_sha256": sha,
            "file_size": 4,
            "type": "file",
            "parse_attempt": 1,
            "parse_status": "completed",
            "original_upload_run_id": "old-run",
            "original_upload_ordinal": 2,
        }})

    platform, scope = client(respond)
    scoped = _ScopedPlatform({scope.space_id: SimpleNamespace(scope=scope, platform=platform)})
    admitted = UploadManifest.model_validate_json(json.dumps(manifest()))
    try:
        for knowledge_id in (None, "existing"):
            result = await lookup_material(
                scoped, scope, "new-run", 0, admitted, knowledge_id=knowledge_id
            )
            assert result["knowledge_id"] == "existing"
            assert result["original_upload_run_id"] == "old-run"
            assert result["original_upload_ordinal"] == 2
        assert len(seen) == 4
        assert seen[-1].url.params["knowledge_id"] == "existing"
        with pytest.raises(ValueError, match="outside configured"):
            await lookup_material(
                scoped, scope.model_copy(update={"tenant_id": "other"}), "new-run", 0, admitted
            )
        assert len(seen) == 4
        assert all(request.method == "GET" for request in seen)
    finally:
        await platform.close()
