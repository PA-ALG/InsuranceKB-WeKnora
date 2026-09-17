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
    import hashlib

    return SimpleNamespace(
        policy_sha256=digest,
        field_template_id="extract",
        scope=None,
        model="gemini-3.7-flash-medium",
        max_request_bytes=2_000_000,
        template=lambda _: SimpleNamespace(
            prompt_sha256=hashlib.sha256(module().FIELD_PROMPT).hexdigest(),
            max_context_bytes=1_000_000,
            max_output_tokens=16384,
        ),
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
        "checkpoint",
        "preparation",
        "identity",
        "field_plan",
        "extract",
        "synthesis",
        "discovery",
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
@pytest.mark.parametrize("workflow_version", [2, 3])
async def test_compiler_work_does_not_block_worker_heartbeat(
    compile_request, monkeypatch, workflow_version
):
    import asyncio
    import hashlib
    import sys
    import time
    from types import ModuleType

    from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
    from insurance_harness.product_ingestion import (
        discovery_stage,
        field_validation,
        platform,
        stages,
    )
    from insurance_harness.product_ingestion.stages import StageOutput, json_bytes

    api = module()

    async def discovery(**kwargs):
        assert workflow_version == 2, "schema synthesis invoked discovery"
        assert kwargs["field_delta"] == {"fixture": True}
        assert kwargs["processing_recovery"] is False
        return StageOutput()

    monkeypatch.setattr(discovery_stage, "run_discovery_stage", discovery)
    monkeypatch.setattr(stages, "read_source_snapshots", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        field_validation,
        "validate_field_attempts",
        lambda **kwargs: field_validation.FieldValidationReport(
            source_snapshot_digests={},
            input_digests={},
            changes={},
            counts={"verified": 0, "not_provided": 0, "extraction_failed": 0},
        ),
    )
    monkeypatch.setattr(platform, "verify_signed_snapshot", lambda *_args, **_kwargs: {})
    adapter = ModuleType("insurance_harness.product_ingestion.compilation")

    def project(**_kwargs):
        time.sleep(0.1)
        return (
            SimpleNamespace(model_dump_json=lambda: '{"fixture":true}')
            if workflow_version == 3
            else {"fixture": True}
        )

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
    scope = SimpleNamespace(space_id="space")
    context = SimpleNamespace(
        catalog=compile_request.catalog,
        resolution_policy_json=json_bytes(compile_request.resolution_inputs.policy),
        bindings={
            "space": SimpleNamespace(
                scope=scope,
                configuration=SimpleNamespace(
                    model=SimpleNamespace(templates=(template,)), source_public_keys={}
                ),
            )
        },
        store=SimpleNamespace(
            list_original_field_attempts=lambda **_: (),
            processing_recovery_plan=lambda **_: None,
            checkpoint_plan=lambda **_: None,
        ),
        artifacts=SimpleNamespace(
            get_effective_artifact=lambda **_: SimpleNamespace(
                payload=b'{"current_entity_ids":["fixture-entity"]}'
            )
        ),
    )
    ports = api.build_product_pipeline(context)
    ticks = []

    async def heartbeat():
        await asyncio.sleep(0.02)
        ticks.append(1)

    monitor = asyncio.create_task(heartbeat())
    await ports.stage_handlers["synthesis"](
        scope,
        SimpleNamespace(run_id="run", workflow_version=workflow_version),
        SimpleNamespace(dependency_sha256="a" * 64),
        None,
    )
    observed = len(ticks)
    await monitor
    assert observed == 1, "synchronous compiler work prevented the lease heartbeat from running"


@pytest.mark.parametrize("limit", ["context", "envelope"])
def test_field_plan_splits_actual_requests_to_configured_capacity(
    compile_request, monkeypatch, limit
):
    import hashlib

    from insurance_harness.knowledge_compiler.g3_field_tasks import (
        FieldTaskV1,
        adapt_catalog_field_tasks,
    )
    from insurance_harness.product_ingestion.extraction import render_window_request
    from insurance_harness.product_ingestion.model_execution import _template_and_request

    api = module()
    tasks = adapt_catalog_field_tasks(compile_request)[:3]
    monkeypatch.setattr(api, "adapt_catalog_field_tasks", lambda _: tasks)
    settings = policy()
    template = settings.template(settings.field_template_id)
    settings.template = lambda _: template
    base = compile_request.base_request

    def rendered(selected):
        return render_window_request(
            selected,
            base.sources,
            tenant_id=base.tenant_id,
            space_id=base.space_id,
            raw_kb_id=base.raw_kb_id,
        )

    def prepared(content):
        return _template_and_request(
            settings,
            scope=settings.scope,
            content=content,
            input_sha256=hashlib.sha256(content).hexdigest(),
            prompt=api.FIELD_PROMPT,
            template_id=settings.field_template_id,
        )[1]

    singles = [rendered((task,)) for task in tasks]
    if limit == "context":
        template.max_context_bytes = max(map(len, singles)) + 1
        assert len(rendered(tasks)) > template.max_context_bytes
    else:
        settings.max_request_bytes = (
            max(len(prepared(content).request_bytes) for content in singles) + 1
        )
        with pytest.raises(Exception, match="request capacity exceeded"):
            prepared(rendered(tasks))
    windows = api.build_field_windows(
        compile_request, product_identity_sha256="c" * 64, model_settings=settings
    )
    assert len(windows) > 1
    planned = [row for window in windows for row in window.tasks]
    assert sorted(row.task_sha256 for row in planned) == sorted(task.task_sha256 for task in tasks)
    for window in windows:
        content = rendered(
            tuple(FieldTaskV1.model_validate(row.task_payload) for row in window.tasks)
        )
        prepared(content)
    roomy = api.build_field_windows(
        compile_request, product_identity_sha256="c" * 64, model_settings=policy()
    )
    assert {row.task_sha256: row.cache_identity for row in planned} == {
        row.task_sha256: row.cache_identity for window in roomy for row in window.tasks
    }


def test_field_plan_does_not_swallow_noncapacity_policy_error(compile_request, monkeypatch):
    from insurance_harness.knowledge_compiler.g3_field_tasks import adapt_catalog_field_tasks
    from insurance_harness.product_ingestion.model_execution import ModelPolicyDenied

    api = module()
    monkeypatch.setattr(
        api, "adapt_catalog_field_tasks", lambda _: adapt_catalog_field_tasks(compile_request)[:2]
    )
    settings = policy()
    template = settings.template("extract")
    template.prompt_sha256 = "0" * 64
    settings.template = lambda _: template
    with pytest.raises(ModelPolicyDenied, match="template mismatch"):
        api.build_field_windows(
            compile_request, product_identity_sha256="c" * 64, model_settings=settings
        )


def test_single_field_over_capacity_fails_without_increasing_limit(compile_request, monkeypatch):
    from insurance_harness.knowledge_compiler.g3_field_tasks import adapt_catalog_field_tasks
    from insurance_harness.product_ingestion.model_execution import ModelPolicyDenied

    api = module()
    only = adapt_catalog_field_tasks(compile_request)[:1]
    monkeypatch.setattr(api, "adapt_catalog_field_tasks", lambda _: only)
    settings = policy()
    template = settings.template("extract")
    template.max_context_bytes = 1
    settings.template = lambda _: template
    with pytest.raises(ModelPolicyDenied, match="context capacity exceeded"):
        api.build_field_windows(
            compile_request, product_identity_sha256="c" * 64, model_settings=settings
        )
    assert template.max_context_bytes == 1
