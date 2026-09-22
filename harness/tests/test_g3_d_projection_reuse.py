from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_json_bytes_830_g3
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCandidateBundle830G3V1,
    BatchConceptCompileRequest830G3V1,
)
from insurance_harness.knowledge_compiler.g3_field_tasks import FieldTaskV1


def module() -> ModuleType:
    return importlib.import_module("insurance_harness.knowledge_compiler.g3_d_projection_reuse")


def test_selection_rejects_ambiguous_or_duplicate_targets() -> None:
    cls = module().G3DProjectionSelectionV1
    for fields, synthesis in (((), False), (("x", "x"), False), (("x",), True)):
        with pytest.raises(ValueError):
            cls(origin_call_id="call", field_keys=fields, include_synthesis=synthesis)
    assert cls(origin_call_id="call", field_keys=("x",)).field_keys == ("x",)


def test_manifest_rejects_rehashed_invented_empty_evidence() -> None:
    mod = module()
    payload = dict(
        contract="g3-d-projection-reuse.830.v1",
        current_request_sha256="1" * 64,
        origin_admission_digest="2" * 64,
        origin_request_sha256="3" * 64,
        validator_version=mod.VALIDATOR_VERSION,
        validator_sha256=mod.validator_sha256(),
        entries=(),
    )
    from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_sha256_830_g3

    payload["manifest_sha256"] = batch_sha256_830_g3(payload["contract"], payload)
    with pytest.raises(ValueError):
        mod.G3DProjectionReuseManifestV1.model_validate(payload)


@pytest.fixture(scope="module")
def request_fixture() -> BatchConceptCandidateBundle830G3V1:
    from pathlib import Path

    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        validate_batch_candidate,
    )

    return validate_batch_candidate(
        (
            Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    )


def _setup(
    monkeypatch: pytest.MonkeyPatch, candidate: BatchConceptCandidateBundle830G3V1
) -> tuple[ModuleType, BatchConceptCompileRequest830G3V1, list[str], list[dict[str, object]]]:
    import json
    from types import SimpleNamespace

    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime
    from insurance_harness.run_admission.g3_models import G3ProviderUsageV1, canonical_json
    from tests.test_g3_bounded_model_execution_830 import _gemini_compile_reference_wire

    mod = module()
    request = candidate.request
    window = next(
        w for w in runtime.derive_gemini_d_compile_windows(request) if w["kind"] == "FIELDS"
    )
    wire = json.loads(_gemini_compile_reference_wire(candidate))
    wire["fields"] = [row for row in wire["fields"] if row["field_ref"] in window["field_refs"]]
    wire["definitions"], wire["pages"] = [], []
    raw = canonical_json(wire)
    call = SimpleNamespace(
        call_id="old-call",
        window_id=window["window_id"],
        material_ids=tuple(window["material_ids"]),
        request_body_sha256="4" * 64,
        input_token_ceiling=100,
        output_token_ceiling=16384,
    )
    plan = SimpleNamespace(
        request_manifest=SimpleNamespace(calls=(call,)),
        chain_manifest_hash="5" * 64,
        parent_authorization_digest="6" * 64,
    )
    recorded = SimpleNamespace(
        semantic_bytes=raw,
        response_bytes=raw,
        terminal=SimpleNamespace(receipt_sha256="7" * 64, status="FAILED"),
        observed_usage=G3ProviderUsageV1(
            prompt_tokens=90, completion_tokens=16558, total_tokens=16648, usage_verified=True
        ),
        anomaly_codes=("OUTPUT_TOKEN_CAP_EXCEEDED",),
    )
    monkeypatch.setattr(mod, "_load_origin", lambda *args: (plan, request))
    reads = []

    def read(**kwargs: object) -> SimpleNamespace:
        reads.append(kwargs)
        return recorded

    monkeypatch.setattr(mod.gateway, "read_g3_recorded_call", read)
    fields = sorted(
        row["field_key"]
        for row in runtime._g3_d_field_targets(request, runtime._g3_d_entity_refs(request))
        if row["field_ref"] in window["field_refs"]
    )
    return mod, request, fields, reads


def test_projection_reopens_failed_evidence_and_deduplicates_usage(
    monkeypatch: pytest.MonkeyPatch, request_fixture: BatchConceptCandidateBundle830G3V1
) -> None:
    mod, request, fields, reads = _setup(monkeypatch, request_fixture)
    selections = tuple(
        mod.G3DProjectionSelectionV1(origin_call_id="old-call", field_keys=(key,))
        for key in fields[:2]
    )
    manifest = mod.build_d_projection_reuse_manifest(
        origin_request=request,
        current_request=request,
        origin_admission_digest="2" * 64,
        selections=selections,
    )
    result = mod.validate_d_projection_reuse(manifest, current_request=request)
    assert len(reads) == 2  # One read per build/reopen, despite two projections of one call.
    assert sum(len(o.fields) for o in result.outputs) == 2
    assert result.origin_call_count == 1
    assert result.historical_usage.completion_tokens == 16558
    assert result.historical_usage.successful_usage_records == 0
    assert result.anomaly_codes == ("OUTPUT_TOKEN_CAP_EXCEEDED",)
    assert {e.origin_terminal_status for e in manifest.entries} == {"FAILED"}
    assert len(result.reused_task_sha256s) == 2
    from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_sha256_830_g3

    payload = manifest.model_dump(exclude={"manifest_sha256"})
    payload["entries"][0]["current_projection_sha256"] = "9" * 64
    payload["manifest_sha256"] = batch_sha256_830_g3(payload["contract"], payload)
    with pytest.raises(ValueError, match="evidence/projection mismatch"):
        mod.validate_d_projection_reuse(payload, current_request=request)


def test_projection_rejects_duplicate_and_changed_task(
    monkeypatch: pytest.MonkeyPatch, request_fixture: BatchConceptCandidateBundle830G3V1
) -> None:
    mod, request, fields, _ = _setup(monkeypatch, request_fixture)
    selection = mod.G3DProjectionSelectionV1(origin_call_id="old-call", field_keys=(fields[0],))
    with pytest.raises(ValueError, match="duplicate"):
        mod.build_d_projection_reuse_manifest(
            origin_request=request,
            current_request=request,
            origin_admission_digest="2" * 64,
            selections=(selection, selection),
        )
    original = mod.adapt_catalog_field_tasks
    calls = 0

    def tasks(value: BatchConceptCompileRequest830G3V1) -> tuple[FieldTaskV1, ...]:
        nonlocal calls
        calls += 1
        rows = original(value)
        return (
            rows
            if calls == 1
            else tuple(row.model_copy(update={"task_sha256": "9" * 64}) for row in rows)
        )

    monkeypatch.setattr(mod, "adapt_catalog_field_tasks", tasks)
    with pytest.raises(ValueError, match="FieldTask dependency changed"):
        mod.build_d_projection_reuse_manifest(
            origin_request=request,
            current_request=request,
            origin_admission_digest="2" * 64,
            selections=(selection,),
        )


def test_origin_loader_rejects_invalid_root_signature_before_using_historical_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from insurance_harness.run_admission import g3_trust_policy as trust
    from insurance_harness.run_admission.profiles import g3_bounded_execution as profile

    mod = module()
    parent = SimpleNamespace(payload="historical-parent")
    plan = SimpleNamespace(parent_authorization_digest="3" * 64)
    approval = SimpleNamespace(payload=plan)
    reads = []

    def read(path: Path, model: type[BaseModel], digest: str | None = None) -> SimpleNamespace:
        reads.append(path.name)
        return approval if path.name == "approval-envelope.json" else parent

    def invalid(policy: object, envelope: object) -> None:
        assert envelope is parent
        raise ValueError("invalid historical root signature")

    monkeypatch.setattr(mod, "_read", read)
    monkeypatch.setattr(profile, "validate_g3_bounded_plan", lambda value: value)
    monkeypatch.setattr(trust, "load_g3_root_trust_policy", lambda: "trusted-root")
    monkeypatch.setattr(trust, "verify_parent_authorization", invalid)
    with pytest.raises(ValueError, match="invalid historical root signature"):
        mod._load_origin("2" * 64, "/unused")
    assert reads == ["approval-envelope.json", "model-processing-authorization.json"]


def _setup_recovery_origin(
    monkeypatch: pytest.MonkeyPatch, candidate: BatchConceptCandidateBundle830G3V1
) -> tuple[
    ModuleType,
    BatchConceptCompileRequest830G3V1,
    list[str],
    list[dict[str, object]],
    SimpleNamespace,
    SimpleNamespace,
    dict[str, Any],
    dict[str, Any],
]:
    import hashlib
    import json

    from insurance_harness.knowledge_compiler.g3_d_recovery_execution import render_recovery_context
    from insurance_harness.knowledge_compiler.g3_field_task_recovery import (
        _identity,
        derive_g3_field_recovery_window,
    )
    from insurance_harness.run_admission.g3_models import canonical_json

    mod, request, fields, reads = _setup(monkeypatch, candidate)
    plan, _ = mod._load_origin("origin")
    call = plan.request_manifest.calls[0]
    recorded = mod.gateway.read_g3_recorded_call()
    reads.clear()
    source_wire = json.loads(recorded.semantic_bytes)
    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime

    target_map = {
        row["field_ref"]: row
        for row in runtime._g3_d_field_targets(request, runtime._g3_d_entity_refs(request))
    }
    selected_rows = source_wire["fields"][:2]
    selected_keys = sorted(target_map[row["field_ref"]]["field_key"] for row in selected_rows)
    entity_id = target_map[selected_rows[0]["field_ref"]]["entity_id"]
    window = derive_g3_field_recovery_window(request, entity_id=entity_id, field_keys=selected_keys)
    context = json.loads(
        batch_json_bytes_830_g3(render_recovery_context(_identity(), request, window))
    )
    body = {
        "messages": [
            {"role": "system", "content": "signed old instructions"},
            {"role": "user", "content": canonical_json(context).decode()},
        ]
    }
    recorded.request_bytes = canonical_json(body)
    call.request_body_sha256 = hashlib.sha256(recorded.request_bytes).hexdigest()
    call.request_bytes = len(recorded.request_bytes)
    call.window_id = window["window_id"]
    call.material_ids = tuple(window["material_ids"])
    source_wire["fields"] = selected_rows
    recorded.semantic_bytes = canonical_json(source_wire)
    recorded.response_bytes = recorded.semantic_bytes
    return mod, request, selected_keys, reads, call, recorded, body, context


def test_repair_origin_reuses_signed_exact_subset_without_recursive_manifest_validation(
    monkeypatch: pytest.MonkeyPatch, request_fixture: BatchConceptCandidateBundle830G3V1
) -> None:
    mod, request, keys, reads, call, recorded, body, context = _setup_recovery_origin(
        monkeypatch, request_fixture
    )
    manifest = mod.build_d_projection_reuse_manifest(
        origin_request=request,
        current_request=request,
        origin_admission_digest="2" * 64,
        selections=(
            mod.G3DProjectionSelectionV1(origin_call_id=call.call_id, field_keys=(keys[0],)),
        ),
    )
    result = mod.validate_d_projection_reuse(manifest, current_request=request)
    assert len(result.outputs[0].fields) == 1
    assert result.outputs[0].fields[0].field_key == keys[0]
    assert manifest.entries[0].origin_window_id == call.window_id
    assert len(reads) == 2


@pytest.mark.parametrize("mutation", ["window", "offered_span"])
def test_repair_origin_rejects_forged_window_or_source_scope(
    monkeypatch: pytest.MonkeyPatch,
    request_fixture: BatchConceptCandidateBundle830G3V1,
    mutation: str,
) -> None:
    import hashlib

    from insurance_harness.run_admission.g3_models import canonical_json

    mod, request, keys, reads, call, recorded, body, context = _setup_recovery_origin(
        monkeypatch, request_fixture
    )
    if mutation == "window":
        context["window"]["window_id"] = call.window_id = "window_" + "9" * 64
    else:
        context["source_options"][0]["spans"][0]["quote"] += "forged source text"
    body["messages"][1]["content"] = canonical_json(context).decode()
    recorded.request_bytes = canonical_json(body)
    call.request_body_sha256 = hashlib.sha256(recorded.request_bytes).hexdigest()
    call.request_bytes = len(recorded.request_bytes)
    with pytest.raises(ValueError, match="recovery"):
        mod.build_d_projection_reuse_manifest(
            origin_request=request,
            current_request=request,
            origin_admission_digest="2" * 64,
            selections=(
                mod.G3DProjectionSelectionV1(origin_call_id=call.call_id, field_keys=(keys[0],)),
            ),
        )


def test_repair_origin_keeps_selected_quote_inside_original_offered_spans(
    monkeypatch: pytest.MonkeyPatch, request_fixture: BatchConceptCandidateBundle830G3V1
) -> None:
    import json

    from insurance_harness.run_admission.g3_models import canonical_json

    mod, request, keys, reads, call, recorded, body, context = _setup_recovery_origin(
        monkeypatch, request_fixture
    )
    wire = json.loads(recorded.semantic_bytes)
    row = wire["fields"][0]
    row.update(
        state="present",
        value="invented",
        unknown_reason=None,
        evidence=[
            {
                "source_ref": context["source_options"][0]["source_ref"],
                "quote": "quote that was never offered",
            }
        ],
    )
    recorded.semantic_bytes = canonical_json(wire)
    selected_key = next(
        t["field_key"] for t in context["field_targets"] if t["field_ref"] == row["field_ref"]
    )
    with pytest.raises(ValueError, match="offered"):
        mod.build_d_projection_reuse_manifest(
            origin_request=request,
            current_request=request,
            origin_admission_digest="2" * 64,
            selections=(
                mod.G3DProjectionSelectionV1(
                    origin_call_id=call.call_id, field_keys=(selected_key,)
                ),
            ),
        )
