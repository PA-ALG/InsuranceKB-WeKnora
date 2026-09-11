from pathlib import Path
from types import SimpleNamespace

import pytest

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    validate_batch_candidate,
)
from insurance_harness.knowledge_compiler.g3_field_tasks import adapt_catalog_field_tasks


def test_recovery_only_plans_fields_not_already_evidenced():
    from insurance_harness.knowledge_compiler import g3_d_recovery_execution as recovery

    request = validate_batch_candidate(
        (
            Path(__file__).parent / "fixtures/batch_concept_compile_830_g3/candidate.json"
        ).read_bytes()
    ).request
    tasks = adapt_catalog_field_tasks(request)
    grouped = {}
    for task in tasks:
        grouped.setdefault(task.entity_id, []).append(task.field_key)
    target = max(grouped, key=lambda key: len(grouped[key]))
    missing = set(sorted(grouped[target])[:5])
    entries = tuple(SimpleNamespace(
        entity_id=entity, field_keys=tuple(
            key for key in sorted(keys) if entity != target or key not in missing
        ), include_synthesis=True,
    ) for entity, keys in sorted(grouped.items()))
    windows = recovery.derive_recovery_windows(request, SimpleNamespace(entries=entries))
    assert len(windows) == 1
    import re

    assert re.fullmatch(r"window_[0-9a-f]{64}", windows[0]["window_id"])
    assert set(windows[0]["field_keys"]) == missing
    assert windows[0]["entity_id"] == target
    forged = SimpleNamespace(
        entity_id=target, field_keys=("not_in_schema",), include_synthesis=False
    )
    with pytest.raises(ValueError):
        recovery.derive_recovery_windows(request, SimpleNamespace(entries=(*entries, forged)))


def test_runtime_dispatches_only_the_bound_recovery_window(monkeypatch):
    from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime
    from insurance_harness.knowledge_compiler import g3_d_recovery_execution as recovery

    window = {"window_id": "recovery-1", "material_ids": ("m17",)}
    prepared = SimpleNamespace(projection_reuse=object(), recovery_windows=(window,))
    call = SimpleNamespace(window_id="recovery-1", material_ids=("m17",))
    sentinel = object()
    monkeypatch.setattr(recovery, "project_recovery_response", lambda raw, request, exact: sentinel)
    assert runtime._prepared_gemini_d_window_output(
        raw=b"{}", request=object(), call=call, prepared=prepared,
    ) is sentinel
    call.material_ids = ("foreign",)
    with pytest.raises(ValueError, match="binding"):
        runtime._prepared_gemini_d_window_output(
            raw=b"{}", request=object(), call=call, prepared=prepared,
        )


def test_runtime_recovery_aggregation_records_valid_compile_output():
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
    reused = output.model_copy(update={
        "fields": output.fields[:-5], "pages": (), "definitions": (), "audit": (),
    })
    synthesis = output.model_copy(update={"fields": ()})
    new = output.model_copy(update={
        "fields": output.fields[-5:], "pages": (), "definitions": (), "audit": (),
    })
    prepared = SimpleNamespace(projection_reuse=object(), reused_outputs=(reused, synthesis))
    result = runtime._finalize_gemini_d_compile_windows(
        request=candidate.request, outputs=[new], plan=SimpleNamespace(run_id="recovery-test"),
        admission_digest="a" * 64, call_dir="unused", call_terminals=(),
        started_at=datetime.now(UTC), prepared=prepared,
    )
    assert result.execution.implementation == "g3-gemini-d-recovery-aggregate.830.v1"
    validate_delta_output(candidate.request, result)
