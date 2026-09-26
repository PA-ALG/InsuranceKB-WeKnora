"""Current-document extraction cannot receive historical matching hints."""

# ruff: noqa: F811
from __future__ import annotations

import json
import typing

from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_routing import catalog  # noqa: F401
from tests.product_ingestion.test_source_geometry import native_snapshot
from tests.product_ingestion.test_stages import stage_runtime  # noqa: F401


def test_identity_context_contains_only_source_inputs(snapshot: typing.Any) -> None:  # noqa: F811
    from insurance_harness.product_ingestion.identity import (
        build_current_corpus,
        build_identity_context,
    )
    from insurance_harness.product_ingestion.source_geometry import project_native_pages

    scope, body, *_ = snapshot
    body["receipt"]["manifest_algorithm"] = "weknora.chunk_manifest.v1"
    decoded = native_snapshot(snapshot)
    corpus = build_current_corpus(
        scope, {"knowledge": decoded}, declared_by="platform-upload-receipt"
    )
    context = build_identity_context(
        corpus,
        project_native_pages(decoded, material_id="knowledge"),
        allowed_material_roles=("terms",),
        allowed_taxonomy_labels=("endowment_insurance",),
    )
    assert context["contract"] == "product-identity-source-context.830.v2"
    assert "existing_entities" not in context
    assert context["materials"][0]["blocks"][0]["evidence_locator_refs"]
    assert "null" in context["instructions"]["optional_identity"]
    assert json.loads(json.dumps(context))["response_schema"]


def test_old_identity_context_cannot_be_replayed_or_redispatched(
    stage_runtime: typing.Any, monkeypatch: typing.Any
) -> None:
    import asyncio
    import hashlib

    import pytest

    from tests.product_ingestion import test_identity_recovery as recovery
    from tests.product_ingestion.test_identity_replay_fencing import child_identity

    old_context = json.loads(recovery.CONTENT)
    old_context.update(
        contract="g3-c-classify-prompt-context.830.v1",
        existing_entities=[{"product_code": "HISTORY_ONLY"}],
    )
    old_raw = json.dumps(old_context, sort_keys=True, separators=(",", ":")).encode()
    original_args = recovery.call_args

    def old_args(*args: typing.Any, **kwargs: typing.Any) -> typing.Any:
        kwargs["content"] = old_raw
        return original_args(*args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(recovery, "call_args", old_args)
        origin_generator = typing.cast(typing.Any, recovery.recorded_origin).__wrapped__(
            stage_runtime
        )
        origin = next(origin_generator)
    scope, _, artifacts, child, job, boundary = child_identity(stage_runtime, origin)
    new_context = {k: v for k, v in old_context.items() if k != "existing_entities"}
    new_context["contract"] = "product-identity-source-context.830.v2"
    new_raw = json.dumps(new_context, sort_keys=True, separators=(",", ":")).encode()
    args = original_args(artifacts, scope, child, job, content=new_raw)
    assert args["input_sha256"] == hashlib.sha256(new_raw).hexdigest()
    with pytest.raises(ValueError, match="recorded identity request or model policy changed"):
        asyncio.run(boundary.replay_stage_call(**args))
    assert len(origin[4]) == 1
    assert not artifacts.list_stage_calls(scope=scope, run_id=child.run_id)
    next(origin_generator, None)
