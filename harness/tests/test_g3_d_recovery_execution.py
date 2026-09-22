# Partial test doubles isolate the stated boundary; admission is tested separately.
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
    validate_batch_candidate,
)
from insurance_harness.knowledge_compiler.g3_d_projection_reuse import (
    G3DProjectionReuseEntryV1,
    G3DProjectionReuseManifestV1,
)
from insurance_harness.knowledge_compiler.g3_field_tasks import adapt_catalog_field_tasks
from insurance_harness.run_admission.g3_models import (
    G3BoundedAdmissionPlanV1,
    G3CallPlanV1,
    G3ProviderUsageV1,
)


def test_recovery_only_plans_fields_not_already_evidenced() -> None:
    from insurance_harness.knowledge_compiler import g3_d_recovery_execution as recovery

    request = validate_batch_candidate(
        (
            Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    ).request
    tasks = adapt_catalog_field_tasks(request)
    grouped: dict[str, list[str]] = {}
    for task in tasks:
        grouped.setdefault(task.entity_id, []).append(task.field_key)
    target = max(grouped, key=lambda key: len(grouped[key]))
    missing = set(sorted(grouped[target])[:5])
    entries = tuple(
        entry
        for entity, keys in sorted(grouped.items())
        for entry in (
            _projection_entry(
                entity, tuple(key for key in sorted(keys) if entity != target or key not in missing)
            ),
            _projection_entry(entity, synthesis=True),
        )
    )
    manifest = _projection_manifest(request.request_sha256, entries)
    windows = recovery.derive_recovery_windows(request, manifest)
    assert len(windows) == 1
    import re

    assert re.fullmatch(r"window_[0-9a-f]{64}", windows[0]["window_id"])
    assert set(windows[0]["field_keys"]) == missing
    assert windows[0]["entity_id"] == target
    forged = _projection_entry(target, ("not_in_schema",))
    with pytest.raises(ValueError):
        recovery.derive_recovery_windows(
            request, _projection_manifest(request.request_sha256, (*entries, forged))
        )


def test_runtime_dispatches_only_the_bound_recovery_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime
    from insurance_harness.knowledge_compiler import g3_d_recovery_execution as recovery

    window = {"window_id": "recovery-1", "material_ids": ("m17",)}
    prepared = SimpleNamespace(projection_reuse=object(), recovery_windows=(window,))
    call = SimpleNamespace(window_id="recovery-1", material_ids=("m17",))
    sentinel = object()
    monkeypatch.setattr(recovery, "project_recovery_response", lambda raw, request, exact: sentinel)
    assert (
        runtime._prepared_gemini_d_window_output(
            raw=b"{}",
            request=cast(BatchConceptCompileRequest830G3V1, object()),
            call=cast(G3CallPlanV1, call),
            prepared=cast(runtime.G3StageExecutionContext, prepared),
        )
        is sentinel
    )
    call.material_ids = ("foreign",)
    with pytest.raises(ValueError, match="binding"):
        runtime._prepared_gemini_d_window_output(
            raw=b"{}",
            request=cast(BatchConceptCompileRequest830G3V1, object()),
            call=cast(G3CallPlanV1, call),
            prepared=cast(runtime.G3StageExecutionContext, prepared),
        )


def test_runtime_recovery_aggregation_records_valid_compile_output() -> None:
    from datetime import UTC, datetime

    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime
    from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
        validate_delta_output,
    )

    candidate = validate_batch_candidate(
        (
            Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    )
    output = candidate.model_compile_result.output
    reused = output.model_copy(
        update={
            "fields": output.fields[:-5],
            "pages": (),
            "definitions": (),
            "audit": (),
        }
    )
    synthesis = output.model_copy(update={"fields": ()})
    new = output.model_copy(
        update={
            "fields": output.fields[-5:],
            "pages": (),
            "definitions": (),
            "audit": (),
        }
    )
    prepared = SimpleNamespace(projection_reuse=object(), reused_outputs=(reused, synthesis))
    result = runtime._finalize_gemini_d_compile_windows(
        request=candidate.request,
        outputs=[new],
        plan=cast(G3BoundedAdmissionPlanV1, SimpleNamespace(run_id="recovery-test")),
        admission_digest="a" * 64,
        call_dir="unused",
        call_terminals=(),
        started_at=datetime.now(UTC),
        prepared=cast(runtime.G3StageExecutionContext, prepared),
    )
    assert result.execution.implementation == "g3-gemini-d-recovery-aggregate.830.v1"
    validate_delta_output(candidate.request, result)


def _projection_entry(
    entity_id: str,
    field_keys: Sequence[str] = (),
    *,
    synthesis: bool = False,
    call_id: str = "test-call",
) -> G3DProjectionReuseEntryV1:
    from insurance_harness.knowledge_compiler.g3_d_projection_reuse import (
        G3DProjectionReuseEntryV1,
    )

    return G3DProjectionReuseEntryV1(
        origin_call_id=call_id,
        field_keys=tuple(sorted(field_keys)),
        include_synthesis=synthesis,
        origin_window_id="window_" + "1" * 64,
        entity_id=entity_id,
        task_sha256s=tuple("1" * 64 for _ in field_keys),
        entity_scope_sha256="1" * 64,
        origin_chain_manifest_hash="1" * 64,
        origin_parent_authorization_digest="1" * 64,
        origin_request_body_sha256="1" * 64,
        origin_response_body_sha256="1" * 64,
        origin_terminal_receipt_sha256="1" * 64,
        origin_terminal_status="SUCCESS",
        origin_projection_sha256="1" * 64,
        current_projection_sha256="1" * 64,
        observed_usage=G3ProviderUsageV1(
            prompt_tokens=1, completion_tokens=1, total_tokens=2, usage_verified=True
        ),
        input_token_ceiling=10,
        output_token_ceiling=10,
        anomaly_codes=(),
    )


def _projection_manifest(
    current_hash: str, entries: Sequence[G3DProjectionReuseEntryV1], *, origin: str = "2"
) -> G3DProjectionReuseManifestV1:
    from insurance_harness.knowledge_compiler.batch_canonical_830_g3 import batch_sha256_830_g3
    from insurance_harness.knowledge_compiler.g3_d_projection_reuse import (
        VALIDATOR_VERSION,
        G3DProjectionReuseManifestV1,
    )

    value: dict[str, Any] = dict(
        contract="g3-d-projection-reuse.830.v1",
        current_request_sha256=current_hash,
        origin_admission_digest=origin * 64,
        origin_request_sha256=origin * 64,
        validator_version=VALIDATOR_VERSION,
        validator_sha256="3" * 64,
        entries=tuple(entries),
    )
    value["manifest_sha256"] = batch_sha256_830_g3(value["contract"], value)
    return G3DProjectionReuseManifestV1.model_validate(value)


def test_normalize_projection_reuse_accepts_single_and_multiple_typed_manifests() -> None:
    from insurance_harness.knowledge_compiler import g3_d_recovery_execution as recovery

    first = _projection_manifest("1" * 64, [_projection_entry("entity", ["a"])])
    second = _projection_manifest("1" * 64, [_projection_entry("entity", ["b"])], origin="4")
    assert recovery.normalize_projection_reuse(first) == (first,)
    assert recovery.normalize_projection_reuse(first.model_dump()) == (first,)
    assert recovery.normalize_projection_reuse([first, second.model_dump()]) == (first, second)
    assert recovery.normalize_projection_reuse((first, second)) == (first, second)


def test_normalize_projection_reuse_rejects_empty_duplicate_and_mixed_requests() -> None:
    from insurance_harness.knowledge_compiler import g3_d_recovery_execution as recovery

    first = _projection_manifest("1" * 64, [_projection_entry("entity", ["a"])])
    foreign = _projection_manifest("9" * 64, [_projection_entry("entity", ["b"])], origin="4")
    for value in (None, [], (), [first, first], [first, first.model_dump()], [first, foreign]):
        with pytest.raises(ValueError):
            recovery.normalize_projection_reuse(value)


def test_multi_origin_recovery_union_covers_all_tasks_without_reextracting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime
    from insurance_harness.knowledge_compiler import g3_d_recovery_execution as recovery

    request = cast(
        BatchConceptCompileRequest830G3V1,
        SimpleNamespace(
            request_sha256="1" * 64, entity_bindings=(SimpleNamespace(entity_id="entity"),)
        ),
    )
    monkeypatch.setattr(
        recovery,
        "adapt_catalog_field_tasks",
        lambda request: tuple(
            SimpleNamespace(entity_id="entity", field_key=key) for key in ("old", "repair")
        ),
    )
    monkeypatch.setattr(
        runtime,
        "derive_gemini_d_compile_windows",
        lambda request: ({"kind": "ENTITY_SYNTHESIS", "entity_id": "entity"},),
    )
    first = _projection_manifest(
        "1" * 64,
        [_projection_entry("entity", ["old"]), _projection_entry("entity", synthesis=True)],
    )
    second = _projection_manifest("1" * 64, [_projection_entry("entity", ["repair"])], origin="4")
    assert recovery.derive_recovery_windows(request, [first, second]) == ()
    duplicate_field = _projection_manifest(
        "1" * 64, [_projection_entry("entity", ["old"])], origin="4"
    )
    duplicate_synth = _projection_manifest(
        "1" * 64, [_projection_entry("entity", synthesis=True)], origin="4"
    )
    for other in (duplicate_field, duplicate_synth):
        with pytest.raises(ValueError, match="duplicat"):
            recovery.derive_recovery_windows(request, [first, other])
    with pytest.raises(ValueError, match="request"):
        recovery.derive_recovery_windows(
            request, _projection_manifest("9" * 64, [_projection_entry("entity", ["old"])])
        )
