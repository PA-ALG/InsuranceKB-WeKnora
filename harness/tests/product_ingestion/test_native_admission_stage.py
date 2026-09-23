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
from insurance_harness.product_ingestion.native_admission import NATIVE_ADMISSION_PROMPT
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_discovery_replay_custody import _parent_call, _service
from tests.product_ingestion.test_native_admission import context, inputs, project, response

pytest_plugins = ("tests.product_ingestion.test_discovery",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["new", "parent", "ancestor", "unknown", "bad_semantics", "changed_knowledge"]
)
async def test_admission_call_custody_and_failure_preservation(case: Any, mode: str) -> None:
    request, entity, snapshot, source = values = inputs(case)
    scope = ProductScope(
        tenant_id=str(request.base_request.tenant_id),
        space_id=request.base_request.space_id,
        raw_knowledge_base_id=request.base_request.raw_kb_id,
        wiki_knowledge_base_id=request.base_request.wiki_kb_id,
    )
    ctx = context(values)
    ctx["max_context_bytes"] = 300000
    content = json_bytes(ctx)
    payload = response(ctx)
    if mode == "bad_semantics":
        del payload["pages"][0]["content_provenance"]
    raw = json_bytes({"choices": [{"message": {"content": json.dumps(payload)}}]})
    service = _service(
        role="extract",
        purpose="g3-native-admission",
        prompt=NATIVE_ADMISSION_PROMPT,
        new_raw=raw if mode in {"new", "bad_semantics", "changed_knowledge"} else None,
    )
    service.configuration.model.scope = scope
    record = _parent_call(
        stage_key="discovery",
        operation="native-admission-" + hashlib.sha256(content).hexdigest(),
        content=content,
        prompt=NATIVE_ADMISSION_PROMPT,
        raw=raw,
    )
    record.diagnostic = None
    if mode == "ancestor":
        record.run_id = "ancestor-run"
    if mode == "unknown":
        record.state = "interrupted"
        record.raw = None
    records = [record] if mode in {"parent", "unknown", "changed_knowledge"} else []
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
    )
    assert len(service.model_executor.calls) == (
        1 if mode in {"new", "bad_semantics", "changed_knowledge"} else 0
    )
    assert (outcome.projection is not None) == (
        mode in {"new", "parent", "ancestor", "changed_knowledge"}
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
