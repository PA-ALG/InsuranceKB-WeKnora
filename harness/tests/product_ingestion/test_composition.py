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
            settings=settings(tmp_path).model_copy(
                update={"product_ingestion_enabled": False}
            ),
            lifecycle=Lifecycle(),
            session_factory=session_factory,
        )
        assert plain._registry.handlers == {}
    finally:
        engine.dispose()
