from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from tests.test_g3_field_tasks import _request


def module():
    try:
        return importlib.import_module("insurance_harness.product_ingestion.pipeline")
    except ModuleNotFoundError:
        pytest.fail("permanent platform pipeline is not implemented")


@pytest.fixture(scope="module")
def compile_request():
    return _request()


def policy(digest="a" * 64):
    return SimpleNamespace(
        policy_sha256=digest,
        field_template_id="extract",
        template=lambda _: SimpleNamespace(prompt_sha256="b" * 64),
    )


def test_field_plan_is_bounded_and_uses_only_required_non_carried_fields(compile_request):
    from insurance_harness.knowledge_compiler.g3_field_tasks import adapt_catalog_field_tasks

    expected = adapt_catalog_field_tasks(compile_request)
    windows = module().build_field_windows(
        compile_request, product_identity_sha256="c" * 64, model_settings=policy()
    )
    actual = tuple(task for window in windows for task in window.tasks)
    assert all(0 < len(window.tasks) <= 10 for window in windows)
    assert {(row.entity_id, row.field_key) for row in actual} == {
        (row.entity_id, row.field_key) for row in expected
    }
    assert all(row.task_sha256 == row.task_payload["task_sha256"] for row in actual)


def test_model_policy_change_keeps_business_cache_identity(compile_request):
    first = module().build_field_windows(
        compile_request, product_identity_sha256="c" * 64, model_settings=policy()
    )
    changed = module().build_field_windows(
        compile_request, product_identity_sha256="c" * 64, model_settings=policy("d" * 64)
    )
    assert first[0].dependency_sha256 != changed[0].dependency_sha256
    assert [task.cache_identity.cache_key for window in first for task in window.tasks] == [
        task.cache_identity.cache_key for window in changed for task in window.tasks
    ]


def test_retry_plan_accepts_only_explicit_selected_failed_field_keys(compile_request):
    first = module().build_field_windows(
        compile_request, product_identity_sha256="c" * 64, model_settings=policy()
    )
    selected = {(first[0].tasks[0].entity_id, first[0].tasks[0].field_key)}
    actual = module().build_field_windows(
        compile_request,
        product_identity_sha256="c" * 64,
        model_settings=policy(),
        selected_fields=selected,
    )
    assert {
        (task.entity_id, task.field_key) for window in actual for task in window.tasks
    } == selected


def test_factory_installs_every_real_stage_and_checks_configured_identity_prompt(compile_request):
    import hashlib

    from insurance_harness.product_ingestion.stages import json_bytes

    api = module()
    assert hasattr(api, "build_product_pipeline"), "platform stage factory is missing"
    template = SimpleNamespace(
        template_id="identity",
        role="classify",
        purpose="g3-batch-resolution",
        prompt_sha256=hashlib.sha256(api.IDENTITY_PROMPT).hexdigest(),
    )
    context = SimpleNamespace(
        catalog=compile_request.catalog,
        resolution_policy_json=json_bytes(compile_request.resolution_inputs.policy),
        bindings={
            "space": SimpleNamespace(
                configuration=SimpleNamespace(model=SimpleNamespace(templates=(template,)))
            )
        },
        store=object(),
        artifacts=object(),
    )
    ports = api.build_product_pipeline(context)
    assert set(ports.stage_handlers) == {
        "identity",
        "field_plan",
        "extract",
        "synthesis",
        "compilation",
        "review",
        "publish",
        "verify",
    }
    assert all(callable(handler) for handler in ports.stage_handlers.values())
    assert ports.field_prompt(None) == api.FIELD_PROMPT
    template.prompt_sha256 = "0" * 64
    with pytest.raises(ValueError, match="identity template"):
        api.build_product_pipeline(context)


@pytest.mark.asyncio
async def test_compiler_work_does_not_block_worker_heartbeat(compile_request, monkeypatch):
    import asyncio
    import hashlib
    import sys
    import time
    from types import ModuleType

    from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
    from insurance_harness.product_ingestion.stages import json_bytes

    api = module()
    adapter = ModuleType("insurance_harness.product_ingestion.compilation")

    def project(**_kwargs):
        time.sleep(0.1)
        return {"fixture": True}

    adapter.project_field_attempts = project
    monkeypatch.setitem(sys.modules, adapter.__name__, adapter)
    monkeypatch.setattr(
        compiler.BatchConceptCompileRequest830G3V1,
        "model_validate_json",
        lambda *_args: compile_request,
    )
    template = SimpleNamespace(
        template_id="identity",
        role="classify",
        purpose="g3-batch-resolution",
        prompt_sha256=hashlib.sha256(api.IDENTITY_PROMPT).hexdigest(),
    )
    context = SimpleNamespace(
        catalog=compile_request.catalog,
        resolution_policy_json=json_bytes(compile_request.resolution_inputs.policy),
        bindings={
            "space": SimpleNamespace(
                configuration=SimpleNamespace(model=SimpleNamespace(templates=(template,)))
            )
        },
        store=SimpleNamespace(list_field_attempts=lambda **_: ()),
        artifacts=SimpleNamespace(get_artifact=lambda **_: SimpleNamespace(payload=b"{}")),
    )
    ports = api.build_product_pipeline(context)
    ticks = []

    async def heartbeat():
        await asyncio.sleep(0.02)
        ticks.append(1)

    monitor = asyncio.create_task(heartbeat())
    await ports.stage_handlers["synthesis"](
        None, SimpleNamespace(run_id="run"), SimpleNamespace(dependency_sha256="a" * 64), None
    )
    observed = len(ticks)
    await monitor
    assert observed == 1, "synchronous compiler work prevented the lease heartbeat from running"
