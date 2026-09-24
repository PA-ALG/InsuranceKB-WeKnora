"""Native admission uses the existing durable executor and exact parent custody."""

from __future__ import annotations

import hashlib
import importlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from insurance_harness.product_ingestion.artifact_models import ArtifactOrigin
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.native_admission import (
    native_admission_prompt,
    render_native_admission_context,
)
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_discovery_replay_custody import _parent_call, _service
from tests.product_ingestion.test_native_admission import context, inputs, project, response

pytest_plugins = ("tests.product_ingestion.test_discovery",)


@pytest.mark.parametrize("dependencies", [False, True])
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    [
        "new",
        "parent",
        "ancestor",
        "unknown",
        "bad_semantics",
        "changed_knowledge",
        "changed_contract",
    ],
)
async def test_admission_call_custody_and_failure_preservation(
    case: Any, mode: str, dependencies: bool
) -> None:
    if mode == "changed_contract" and not dependencies:
        pytest.skip("member contract guidance is v2 only")
    request, entity, snapshot, source = values = inputs(case)
    scope = ProductScope(
        tenant_id=str(request.base_request.tenant_id),
        space_id=request.base_request.space_id,
        raw_knowledge_base_id=request.base_request.raw_kb_id,
        wiki_knowledge_base_id=request.base_request.wiki_kb_id,
    )
    policy = "candidate-dependencies.830.v1" if dependencies else None
    prompt = native_admission_prompt(policy)
    ctx = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy=policy,
        isolation_enabled=dependencies,
    )
    ctx["max_context_bytes"] = 300000
    content = json_bytes(ctx)
    payload = response(ctx)
    if dependencies:
        payload["contract"] = "native-knowledge-admission.830.v2"
        for row in payload["decisions"]:
            row["depends_on"] = []
    if mode == "bad_semantics":
        del payload["pages"][0]["content_provenance"]
    raw = json_bytes({"choices": [{"message": {"content": json.dumps(payload)}}]})
    service = _service(
        role="extract",
        purpose="g3-native-admission",
        prompt=prompt,
        new_raw=raw
        if mode in {"new", "bad_semantics", "changed_knowledge", "changed_contract"}
        else None,
    )
    service.configuration.model.scope = scope
    recorded_content = content
    if mode == "changed_contract":
        old_context = dict(ctx)
        old_context.pop("member_contract", None)
        recorded_content = json_bytes(old_context)
    record = _parent_call(
        stage_key="discovery",
        operation="native-admission-" + hashlib.sha256(recorded_content).hexdigest(),
        content=recorded_content,
        prompt=prompt,
        raw=raw,
    )
    record.diagnostic = None
    if mode == "ancestor":
        record.run_id = "ancestor-run"
    if mode == "unknown":
        record.state = "interrupted"
        record.raw = None
    records = (
        [record] if mode in {"parent", "unknown", "changed_knowledge", "changed_contract"} else []
    )
    if mode == "changed_knowledge":
        existing = project(values, context(values), response(context(values))).output.pages[0]
        existing = existing.model_copy(update={"stable_key": "existing-guide"})
        request = request.model_copy(
            update={
                "base_request": request.base_request.model_copy(
                    update={"existing_pages": (existing,)}
                )
            }
        )
        assert context((request, entity, snapshot, source)) != context(values)
    module = importlib.import_module("insurance_harness.product_ingestion.native_admission_stage")
    outcome = await module.run_native_admission_window(
        service=service,
        artifacts=SimpleNamespace(
            list_stage_calls=lambda **kw: records,
            read_checkpoint_stage_calls=lambda **kw: [record] if mode == "ancestor" else [],
        ),
        scope=scope,
        run=SimpleNamespace(
            run_id="child",
            retry_of_run_id=("parent-run" if records or mode == "ancestor" else None),
        ),
        stage=SimpleNamespace(dependency_sha256="f" * 64),
        job=SimpleNamespace(),
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy=policy,
        isolation_enabled=dependencies,
    )
    assert len(service.model_executor.calls) == (
        1 if mode in {"new", "bad_semantics", "changed_knowledge", "changed_contract"} else 0
    )
    assert (outcome.projection is not None) == (
        mode in {"new", "parent", "ancestor", "changed_knowledge", "changed_contract"}
    )
    assert bool(outcome.failure) == (mode in {"unknown", "bad_semantics"})
    drafts = {row.artifact_kind: row for row in outcome.drafts}
    assert "native_admission_context" in drafts
    if mode == "unknown":
        assert "native_admission_response" not in drafts
    else:
        response_draft = drafts["native_admission_response"]
        assert response_draft.origin == (
            ArtifactOrigin.RULE if mode in {"parent", "ancestor"} else ArtifactOrigin.MODEL
        )
        assert response_draft.origin_call_id == (
            None if mode in {"parent", "ancestor"} else "child-call"
        )
        proof = json.loads(drafts["native_admission_execution"].payload)
        assert proof["raw_sha256"] == hashlib.sha256(raw).hexdigest()
        assert proof["replayed_from_run_id"] == (
            "ancestor-run" if mode == "ancestor" else "parent-run" if mode == "parent" else None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["offset", "reference", "orphan"])
async def test_preflight_preserves_raw_and_audits_full_projection(case: Any, fault: str) -> None:
    from copy import deepcopy

    request, entity, snapshot, source = inputs(case)
    source = _with_geometry(source)
    policy = "candidate-dependencies.830.v1"
    ctx = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy=policy,
        isolation_enabled=True,
        max_context_bytes=300000,
    )
    payload = response(ctx, supported=True)
    payload["contract"] = "native-knowledge-admission.830.v2"
    payload["decisions"][0]["depends_on"] = []
    page = payload["pages"][0]
    page["evidence"][0]["start"] = 1
    if fault != "offset":
        definition = deepcopy(page)
        for key in ("stable_key", "concept_refs", "conditions", "exceptions", "valid_time"):
            del definition[key]
        definition.update(member_ref="d1", canonical_key="reading", sense_key="guide", aliases=[])
        payload["definitions"] = [definition]
        payload["decisions"][0]["member_refs"].append("d1")
        page["concept_refs"] = [] if fault == "orphan" else ["reading"]
    decoded = json_bytes(payload)
    raw = json_bytes({"choices": [{"message": {"content": decoded.decode()}}]})
    prompt = native_admission_prompt(policy)
    service = _service(role="extract", purpose="g3-native-admission", prompt=prompt, new_raw=None)
    scope = ProductScope(
        tenant_id=str(request.base_request.tenant_id),
        space_id=request.base_request.space_id,
        raw_knowledge_base_id=request.base_request.raw_kb_id,
        wiki_knowledge_base_id=request.base_request.wiki_kb_id,
    )
    service.configuration.model.scope = scope
    content = json_bytes(ctx)
    record = _parent_call(
        stage_key="discovery",
        operation="native-admission-" + hashlib.sha256(content).hexdigest(),
        content=content,
        prompt=prompt,
        raw=raw,
    )
    record.diagnostic = None
    module = importlib.import_module("insurance_harness.product_ingestion.native_admission_stage")
    outcome = await module.run_native_admission_window(
        service=service,
        artifacts=SimpleNamespace(
            list_stage_calls=lambda **kw: [record], read_checkpoint_stage_calls=lambda **kw: []
        ),
        scope=scope,
        run=SimpleNamespace(run_id="child", retry_of_run_id="parent-run"),
        stage=SimpleNamespace(dependency_sha256="f" * 64),
        job=SimpleNamespace(),
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy=policy,
        isolation_enabled=True,
    )
    assert service.model_executor.calls == []
    assert (outcome.projection is not None) == (fault != "orphan")
    drafts = {row.artifact_kind: row for row in outcome.drafts}
    assert json.loads(drafts["native_admission_response"].payload) == payload
    audit = drafts["native_admission_preflight"]
    assert audit.origin == ArtifactOrigin.RULE and audit.origin_call_id is None
    receipt = json.loads(audit.payload)
    assert (
        receipt["original_sha256"]
        == hashlib.sha256(drafts["native_admission_response"].payload).hexdigest()
    )
    assert receipt["status"] == ("REJECTED" if fault == "orphan" else "PASS")
    assert len(receipt["changes"]) == {"offset": 1, "reference": 3, "orphan": 2}[fault]
    if fault == "orphan":
        assert "definition lacks page use" in outcome.failure
        assert "native_admission_projection" not in drafts
    else:
        assert drafts["native_admission_projection"].contract_version == "2"
        canonical = drafts["native_admission_canonical_response"]
        assert canonical.origin == ArtifactOrigin.RULE
        assert receipt["canonical_sha256"] == hashlib.sha256(canonical.payload).hexdigest()
        assert outcome.projection.output.pages[0].evidence[0].start == 0


def _with_geometry(source: Any) -> Any:
    """Attach complete fixture geometry so the test crosses the real locator."""
    from dataclasses import replace

    block = source.blocks[0]
    text = block.text
    digest = hashlib.sha256(text.encode()).hexdigest()
    page = {
        "page_number": 1,
        "global_codepoint_start": 0,
        "global_codepoint_end": len(text),
        "page_text_sha256": digest,
        "width_points": "100",
        "height_points": "200",
        "bboxes": [
            {
                "global_codepoint_start": i,
                "global_codepoint_end": i + 1,
                "bbox": [1000, 2000, 3000, 4000],
            }
            for i, ch in enumerate(text)
            if not ch.isspace()
        ],
    }
    native = {
        "source_sha256": digest,
        "markdown_sha256": digest,
        "parser_identity_sha256": "b" * 64,
        "pages": [page],
    }
    body = {
        **source.snapshot,
        "receipt": {**source.snapshot["receipt"], "file_sha256": digest},
        "markdown": text,
        "parser_identity_sha256": "b" * 64,
        "chunk_page_mappings": [
            {
                "chunk_id": block.block_id,
                "status": "EXACT_BLOCK",
                "block_global_start": 0,
                "page_spans": [page],
            }
        ],
    }
    return replace(source, snapshot=body, native_bytes=json_bytes(native))


@pytest.mark.asyncio
async def test_v3_stage_keeps_wire_raw_and_projects_nonempty_exact_source(
    case: Any, tmp_path: Any
) -> None:
    from insurance_harness.product_ingestion.configuration import ProductRuntimeSettings
    from insurance_harness.product_ingestion.native_admission_stage import (
        run_native_admission_window,
    )
    from insurance_harness.product_ingestion.native_admission_wire import WIRE_PROMPT, WIRE_PROTOCOL
    from tests.product_ingestion.test_native_admission_policy import add_override, policy_payload
    from tests.product_ingestion.test_native_admission_wire import wire_sample

    request, entity, snapshot, source, _, payload = wire_sample(case)
    source = _with_geometry(source)
    data = policy_payload(tmp_path)
    add_override(data)
    binding = ProductRuntimeSettings.model_validate_json(json.dumps(data)).bindings[0]
    scope = ProductScope(
        tenant_id=str(request.base_request.tenant_id),
        space_id=request.base_request.space_id,
        raw_knowledge_base_id=request.base_request.raw_kb_id,
        wiki_knowledge_base_id=request.base_request.wiki_kb_id,
    )
    decoded = json_bytes(payload)
    raw = json_bytes({"choices": [{"message": {"content": decoded.decode()}}]})
    service = _service(
        role="extract", purpose="g3-native-admission-v3", prompt=WIRE_PROMPT, new_raw=raw
    )
    service.configuration.model = binding.model.model_copy(update={"scope": scope})
    service.configuration.native_admission = binding.native_admission
    service.native_admission_executor = service.model_executor
    outcome = await run_native_admission_window(
        service=service,
        artifacts=SimpleNamespace(),
        scope=scope,
        run=SimpleNamespace(run_id="wire-run", retry_of_run_id=None),
        stage=SimpleNamespace(dependency_sha256="f" * 64),
        job=SimpleNamespace(),
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy="candidate-dependencies.830.v1",
        isolation_enabled=True,
    )
    assert outcome.failure is None
    assert len(outcome.projection.output.pages) == 1
    assert outcome.projection.output.pages[0].evidence[0].quote == source.blocks[0].text
    drafts = {row.artifact_kind: row for row in outcome.drafts}
    assert drafts["native_admission_response"].payload == decoded
    context = json.loads(drafts["native_admission_context"].payload)
    assert context["wire_protocol"] == WIRE_PROTOCOL
    assert context["source_options"][0]["spans"][0]["evidence_ref"] == "s1:1"
    canonical = json.loads(drafts["native_admission_canonical_response"].payload)
    assert canonical["contract"] == "native-knowledge-admission.830.v2"
    execution = json.loads(drafts["native_admission_execution"].payload)
    assert execution["wire_protocol"] == WIRE_PROTOCOL
    assert execution["raw_sha256"] == hashlib.sha256(raw).hexdigest()
    assert execution["raw_sha256"] != hashlib.sha256(decoded).hexdigest()
    assert execution["model_policy_sha256"] != binding.model.policy_sha256
    expansion = json.loads(drafts["native_admission_preflight"].payload)["wire_expansion"]
    assert (
        expansion["wire_context_sha256"]
        == hashlib.sha256(drafts["native_admission_context"].payload).hexdigest()
    )
