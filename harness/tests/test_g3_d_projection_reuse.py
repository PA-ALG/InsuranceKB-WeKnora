from __future__ import annotations

import importlib

import pytest


def module():
    return importlib.import_module("insurance_harness.knowledge_compiler.g3_d_projection_reuse")


def test_selection_rejects_ambiguous_or_duplicate_targets():
    cls = module().G3DProjectionSelectionV1
    for fields, synthesis in (((), False), (("x", "x"), False), (("x",), True)):
        with pytest.raises(ValueError):
            cls(origin_call_id="call", field_keys=fields, include_synthesis=synthesis)
    assert cls(origin_call_id="call", field_keys=("x",)).field_keys == ("x",)


def test_manifest_rejects_rehashed_invented_empty_evidence():
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
def request_fixture():
    from pathlib import Path

    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        validate_batch_candidate,
    )

    return validate_batch_candidate(
        (
            Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    )


def _setup(monkeypatch, candidate):
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

    def read(**kwargs):
        reads.append(kwargs)
        return recorded

    monkeypatch.setattr(mod.gateway, "read_g3_recorded_call", read)
    fields = sorted(
        row["field_key"]
        for row in runtime._g3_d_field_targets(request, runtime._g3_d_entity_refs(request))
        if row["field_ref"] in window["field_refs"]
    )
    return mod, request, fields, reads


def test_projection_reopens_failed_evidence_and_deduplicates_usage(monkeypatch, request_fixture):
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


def test_projection_rejects_duplicate_and_changed_task(monkeypatch, request_fixture):
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

    def tasks(value):
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


def test_origin_loader_rejects_invalid_root_signature_before_using_historical_request(monkeypatch):
    from types import SimpleNamespace

    from insurance_harness.run_admission import g3_trust_policy as trust
    from insurance_harness.run_admission.profiles import g3_bounded_execution as profile

    mod = module()
    parent = SimpleNamespace(payload="historical-parent")
    plan = SimpleNamespace(parent_authorization_digest="3" * 64)
    approval = SimpleNamespace(payload=plan)
    reads = []

    def read(path, model, digest=None):
        reads.append(path.name)
        return approval if path.name == "approval-envelope.json" else parent

    def invalid(policy, envelope):
        assert envelope is parent
        raise ValueError("invalid historical root signature")

    monkeypatch.setattr(mod, "_read", read)
    monkeypatch.setattr(profile, "validate_g3_bounded_plan", lambda value: value)
    monkeypatch.setattr(trust, "load_g3_root_trust_policy", lambda: "trusted-root")
    monkeypatch.setattr(trust, "verify_parent_authorization", invalid)
    with pytest.raises(ValueError, match="invalid historical root signature"):
        mod._load_origin("2" * 64, "/unused")
    assert reads == ["approval-envelope.json", "model-processing-authorization.json"]
