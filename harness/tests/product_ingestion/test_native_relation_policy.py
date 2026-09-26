"""Explicit relation admission policy and normal stage identity."""

import hashlib
import json
from typing import Any

import pytest

from insurance_harness.product_ingestion.configuration import ProductRuntimeSettings
from insurance_harness.product_ingestion.native_relation_wire import (
    RELATION_WIRE_PROMPT,
    RELATION_WIRE_PROTOCOL,
    RELATION_WIRE_PURPOSE,
)
from tests.product_ingestion.test_native_admission_policy import add_override, policy_payload

pytest_plugins = ("tests.product_ingestion.test_discovery",)


def relation_policy(tmp_path: Any) -> dict:
    data = policy_payload(tmp_path)
    add_override(data)
    binding = data["bindings"][0]
    override = binding["native_admission"]
    override["protocol"] = RELATION_WIRE_PROTOCOL
    override["template"].update(
        template_id="admission-v4",
        purpose=RELATION_WIRE_PURPOSE,
        prompt_sha256=hashlib.sha256(RELATION_WIRE_PROMPT).hexdigest(),
    )
    from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput
    from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import FreeWikiPage
    from insurance_harness.product_ingestion.discovery import independent_discovery_review_policy

    # Use a typed candidate to resolve the configured normal-review purpose.
    from tests.test_product_concept_relation import relation_case

    _, _, page = relation_case()
    output = CompileOutput(
        request_hash="a" * 64,
        fields=(),
        definitions=(),
        pages=(FreeWikiPage.model_validate(page),),
        audit=(),
        transformation="SYNTHESIZE",
    )
    purpose, prompt = independent_discovery_review_policy(output, dependency_selection=True)
    binding["model"]["templates"].append(
        {
            **override["template"],
            "template_id": "relation-review",
            "role": "verify",
            "purpose": purpose,
            "prompt_sha256": hashlib.sha256(prompt).hexdigest(),
        }
    )
    return data


def test_v4_configuration_selects_distinct_relation_policy(tmp_path: Any) -> None:
    from insurance_harness.product_ingestion.native_admission_policy import resolve_admission_policy

    data = relation_policy(tmp_path)
    binding = ProductRuntimeSettings.model_validate_json(json.dumps(data)).bindings[0]
    policy = resolve_admission_policy(
        binding.model, binding.native_discovery.dependency_policy, binding.native_admission
    )
    assert policy.wire_protocol == RELATION_WIRE_PROTOCOL
    assert policy.prompt == RELATION_WIRE_PROMPT
    assert policy.template.purpose == RELATION_WIRE_PURPOSE


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["new", "parent", "policy_changed", "unknown"])
async def test_v4_stage_binds_wire_receipts_and_nonempty_relation(
    case: Any, tmp_path: Any, mode: str
) -> None:
    from types import SimpleNamespace

    from insurance_harness.product_ingestion.models import ProductScope
    from insurance_harness.product_ingestion.native_admission_stage import (
        run_native_admission_window,
    )
    from insurance_harness.product_ingestion.stages import json_bytes
    from tests.product_ingestion.test_discovery_replay_custody import _service
    from tests.product_ingestion.test_native_admission_stage import _with_geometry
    from tests.product_ingestion.test_native_relation_admission import relation_sample

    request, entity, snapshot, source, _, payload = relation_sample(case)
    source = _with_geometry(source)
    binding = ProductRuntimeSettings.model_validate_json(
        json.dumps(relation_policy(tmp_path))
    ).bindings[0]
    scope = ProductScope(
        tenant_id=str(request.base_request.tenant_id),
        space_id=request.base_request.space_id,
        raw_knowledge_base_id=request.base_request.raw_kb_id,
        wiki_knowledge_base_id=request.base_request.wiki_kb_id,
    )
    decoded = json_bytes(payload)
    raw = json_bytes({"choices": [{"message": {"content": decoded.decode()}}]})
    service = _service(
        role="extract", purpose=RELATION_WIRE_PURPOSE, prompt=RELATION_WIRE_PROMPT, new_raw=raw
    )
    service.configuration.model = binding.model.model_copy(update={"scope": scope})
    service.configuration.native_admission = binding.native_admission
    service.native_admission_executor = service.model_executor
    from insurance_harness.product_ingestion.model_execution import prepare_configured_model_request
    from insurance_harness.product_ingestion.native_admission_context import (
        render_native_admission_context,
    )
    from insurance_harness.product_ingestion.native_admission_policy import resolve_admission_policy
    from insurance_harness.product_ingestion.native_relation_wire import (
        render_relation_wire_context,
    )
    from tests.product_ingestion.test_discovery_replay_custody import _parent_call

    policy = resolve_admission_policy(
        service.configuration.model, "candidate-dependencies.830.v1", binding.native_admission
    )
    ctx = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy="candidate-dependencies.830.v1",
        isolation_enabled=True,
        relation_capability="product-concept-relation.830.v1",
        max_context_bytes=policy.template.max_context_bytes,
    )
    content = json_bytes(render_relation_wire_context(ctx))
    recorded = _parent_call(
        stage_key="discovery",
        operation="native-admission-" + hashlib.sha256(content).hexdigest(),
        content=content,
        prompt=RELATION_WIRE_PROMPT,
        raw=raw,
    )
    prepared = prepare_configured_model_request(
        policy.settings,
        scope=scope,
        content=content,
        prompt=RELATION_WIRE_PROMPT,
        template_id=policy.template.template_id,
    )
    recorded.request_bytes, recorded.request_sha256 = (
        prepared.request_bytes,
        prepared.request_sha256,
    )
    recorded.model_policy_sha256 = (
        "0" * 64 if mode == "policy_changed" else policy.settings.policy_sha256
    )
    recorded.diagnostic = None
    if mode == "unknown":
        recorded.state, recorded.raw = "interrupted", None
    artifacts = SimpleNamespace(
        list_stage_calls=lambda **kw: [recorded], read_checkpoint_stage_calls=lambda **kw: []
    )
    outcome = await run_native_admission_window(
        service=service,
        artifacts=artifacts,
        scope=scope,
        run=SimpleNamespace(
            run_id="relation-wire", retry_of_run_id=None if mode == "new" else "parent-run"
        ),
        stage=SimpleNamespace(dependency_sha256="f" * 64),
        job=SimpleNamespace(),
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy="candidate-dependencies.830.v1",
        isolation_enabled=True,
    )
    assert len(service.native_admission_executor.calls) == (
        1 if mode in {"new", "policy_changed"} else 0
    )
    if mode == "unknown":
        assert outcome.failure and outcome.projection is None
        return
    assert outcome.failure is None
    assert outcome.projection.output.pages[0].business_relation is not None
    drafts = {row.artifact_kind: row for row in outcome.drafts}
    assert drafts["native_admission_response"].payload == decoded
    ctx = json.loads(drafts["native_admission_context"].payload)
    assert ctx["wire_protocol"] == RELATION_WIRE_PROTOCOL
    expansion = json.loads(drafts["native_admission_preflight"].payload)["wire_expansion"]
    assert expansion["wire_value_sha256"] == hashlib.sha256(decoded).hexdigest()
    assert (
        expansion["wire_context_sha256"]
        == hashlib.sha256(drafts["native_admission_context"].payload).hexdigest()
    )
    execution = json.loads(drafts["native_admission_execution"].payload)
    assert execution["wire_protocol"] == RELATION_WIRE_PROTOCOL
    assert execution["raw_sha256"] == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("fault", ["missing_review", "coverage"])
def test_relation_configuration_rejects_incomplete_review_contract(
    tmp_path: Any, fault: str
) -> None:
    data = relation_policy(tmp_path)
    if fault == "coverage":
        data["bindings"][0]["native_coverage_review"] = {
            "protocol": "native-coverage-review.830.v4"
        }
    else:
        binding = data["bindings"][0]
        binding["model"]["templates"] = [
            t
            for t in binding["model"]["templates"]
            if t["purpose"] != "g3-relation-discovery-review"
        ]
    with pytest.raises(ValueError):
        ProductRuntimeSettings.model_validate_json(json.dumps(data))
