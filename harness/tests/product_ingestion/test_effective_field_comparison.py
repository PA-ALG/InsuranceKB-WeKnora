"""Current field values, not Schema names, ground native comparison input."""

from __future__ import annotations

import importlib
from copy import deepcopy
from typing import Any, cast

import pytest

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.native_admission import (
    project_native_admission_response,
)
from insurance_harness.product_ingestion.native_admission_context import (
    render_native_admission_context,
)
from insurance_harness.product_ingestion.stages import json_bytes
from tests.product_ingestion.test_native_admission import inputs, response

pytest_plugins = ("tests.product_ingestion.test_discovery",)


def view(request: Any, entity: str, fields: Any) -> Any:
    module = importlib.import_module("insurance_harness.product_ingestion.field_comparison")
    return module.build_effective_field_view(request, entity, fields)


def test_view_preserves_effective_values_and_omits_evidence_payload(case: Any) -> None:
    request, delta, entity = case
    fields = compiler.compose_batch_output(request, delta).fields
    result = view(request, entity, fields)
    expected = sorted((f for f in fields if f.entity_id == entity), key=lambda f: f.field_key)
    assert len(result["fields"]) == len(expected)
    for row, field in zip(result["fields"], expected, strict=True):
        for key in (
            "field_key",
            "state",
            "value",
            "attempted",
            "unknown_reason",
            "conditions",
            "exceptions",
            "valid_time",
            "concept_ids",
        ):
            assert row[key] == field.model_dump(mode="json")[key]
        assert len(row["revision_sha256"]) == 64
        assert "evidence" not in row and "quote" not in row
    assert result["entity_id"] == entity
    assert "request_hash" not in result and "field_delta_hash" not in result
    # Unrelated entity changes do not alter the semantic comparison input.
    unrelated = next(f for f in fields if f.entity_id != entity)
    changed = tuple(
        f.model_copy(update={"valid_time": "unrelated"}) if f == unrelated else f for f in fields
    )
    assert view(request, entity, changed) == result


@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "wrong_version", "wrong_space", "unknown_key"]
)
def test_field_view_rejects_incomplete_or_foreign_sets(case: Any, fault: str) -> None:
    request, delta, entity = case
    fields = list(compiler.compose_batch_output(request, delta).fields)
    index = next(i for i, f in enumerate(fields) if f.entity_id == entity)
    if fault == "missing":
        fields.pop(index)
    elif fault == "duplicate":
        fields.append(fields[index])
    else:
        key = {
            "wrong_version": "entity_version",
            "wrong_space": "space_id",
            "unknown_key": "field_key",
        }[fault]
        fields[index] = fields[index].model_copy(update={key: "other"})
    with pytest.raises(ValueError):
        view(request, entity, fields)


@pytest.mark.parametrize("reason", ["材料未提供", "EXTRACTION_FAILED:INVALID_MODEL_OUTPUT"])
def test_unknown_reason_is_preserved_and_not_claimed_as_coverage(case: Any, reason: str) -> None:
    request, delta, entity = case
    fields = list(compiler.compose_batch_output(request, delta).fields)
    index = next(i for i, f in enumerate(fields) if f.entity_id == entity)
    fields[index] = fields[index].model_copy(
        update={"state": "unknown", "value": None, "evidence": (), "unknown_reason": reason}
    )
    result = view(request, entity, fields)
    row = next(f for f in result["fields"] if f["field_key"] == fields[index].field_key)
    assert row["state"] == "unknown" and row["value"] is None
    assert row["unknown_reason"] == reason
    assert "unknown" in " ".join(result["comparison_rules"])


def test_native_admission_binds_actual_fields_and_rejects_tampering(case: Any) -> None:
    request, entity, snapshot, source = inputs(case)
    fields = compiler.compose_batch_output(request, case[1]).fields
    kwargs = dict(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy="candidate-dependencies.830.v1",
        effective_fields=fields,
    )
    context = render_native_admission_context(**kwargs)
    assert context["existing_knowledge"]["effective_fields"] == view(request, entity, fields)
    payload = response(context)
    payload["contract"] = "native-knowledge-admission.830.v2"
    for row in payload["decisions"]:
        row["depends_on"] = []
    project_native_admission_response(
        raw=json_bytes(payload),
        context=context,
        **{k: v for k, v in kwargs.items() if k != "dependency_policy"},
    )
    changed = deepcopy(context)
    changed["existing_knowledge"]["effective_fields"]["fields"][0]["value"] = "invented"
    with pytest.raises(ValueError, match="context mismatch"):
        project_native_admission_response(
            raw=json_bytes(payload),
            context=changed,
            **{k: v for k, v in kwargs.items() if k != "dependency_policy"},
        )
    with pytest.raises(ValueError, match="context mismatch"):
        project_native_admission_response(
            raw=json_bytes(payload),
            request=request,
            entity_id=entity,
            snapshot=snapshot,
            source=source,
            context=context,
        )


def test_review_uses_same_fields_and_rejects_stale_admission_comparison(case: Any) -> None:
    from insurance_harness.product_ingestion import discovery
    from insurance_harness.product_ingestion.discovery_composition import merge_discovery_delta
    from tests.product_ingestion.test_native_dependency_selection import dependency_case

    request, entity, snapshot, source, _, payload = dependency_case(case)
    fields = compiler.compose_batch_output(request, case[1]).fields
    context = render_native_admission_context(
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        dependency_policy="candidate-dependencies.830.v1",
        isolation_enabled=True,
        effective_fields=fields,
    )
    result = project_native_admission_response(
        raw=json_bytes(payload),
        request=request,
        entity_id=entity,
        snapshot=snapshot,
        source=source,
        context=context,
        effective_fields=fields,
    )
    candidates = dict(
        output=result.output.model_dump(mode="json"),
        sources=context["source_options"],
        dispositions=result.dispositions,
        dependency_selection=result.dependency_selection,
    )
    joined = merge_discovery_delta(
        request=request, field_delta=case[1], free_output=result.output, run_id="field-view-test"
    )
    output = compiler.compose_batch_output(request, joined)

    def render(final: Any) -> Any:
        return discovery.render_independent_discovery_review_context(
            request=request,
            entity_id=entity,
            exclusion_index=discovery.build_discovery_exclusion_index(request, entity),
            discovery_candidates=candidates,
            final_composed_output=final,
            final_composed_output_hash=compiler.compile_output_hash_g3(final),
            max_context_bytes=300000,
        )

    reviewed = render(output)
    assert (
        reviewed["existing_knowledge"]["effective_fields"]
        == context["existing_knowledge"]["effective_fields"]
    )
    old = next(f for f in fields if f.entity_id == entity)
    changed = output.model_copy(
        update={
            "fields": tuple(
                f.model_copy(update={"valid_time": "changed"}) if f == old else f
                for f in output.fields
            )
        }
    )
    with pytest.raises(ValueError, match="field comparison"):
        render(changed)


def test_incremental_refresh_uses_composed_delta_and_keeps_inherited_fields() -> None:
    from tests.product_ingestion.test_compilation import candidates

    parent, child = candidates()
    request = child.request
    final = compiler.compose_batch_output(request, child.model_compile_result)
    assert request.refresh_fields
    refresh_keys = {(r.entity_id, r.field_key) for r in request.refresh_fields}
    delta = {(f.entity_id, f.field_key): f for f in child.model_compile_result.output.fields}
    inherited = {(f.entity_id, f.field_key): f for f in compiler.aligned_existing_fields(request)}
    assert not refresh_keys & inherited.keys()
    for binding in request.entity_bindings:
        result = view(request, binding.entity_id, final.fields)
        for row in result["fields"]:
            key = (binding.entity_id, row["field_key"])
            source = delta.get(key, inherited.get(key))
            assert source is not None
            assert row["value"] == source.value
            assert row["unknown_reason"] == source.unknown_reason
    assert refresh_keys <= delta.keys()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["original", "prior_rebase", "mixed"])
async def test_checkpoint_reads_request_and_delta_from_same_generation(
    case: Any, mode: str
) -> None:
    from types import SimpleNamespace

    from insurance_harness.product_ingestion import checkpoint_validation
    from tests.product_ingestion.test_compilation import candidates

    _, prior = candidates()
    original_request, original_delta, entity = case
    seen = []

    class Artifacts:
        def read_checkpoint_artifact(self, **kwargs: Any) -> Any:
            seen.append(("original", kwargs["artifact_kind"]))
            value = (
                original_request if kwargs["artifact_kind"] == "compile_request" else original_delta
            )
            return SimpleNamespace(payload=value.model_dump_json().encode())

        def read_prior_rebase_artifact(self, **kwargs: Any) -> Any:
            seen.append(("prior", kwargs["artifact_kind"]))
            if kwargs["artifact_kind"] == "rebased_compile_request":
                value = original_request if mode == "mixed" else prior.request
            else:
                value = prior.model_compile_result
            return SimpleNamespace(payload=value.model_dump_json().encode())

    if mode == "mixed":
        with pytest.raises(ValueError):
            await checkpoint_validation._checkpoint_effective_fields(
                artifacts=cast(ProductArtifactStore, Artifacts()),
                scope=cast(ProductScope, object()),
                run_id="recovery",
                has_prior_rebase=mode != "original",
            )
    else:
        request, fields = await checkpoint_validation._checkpoint_effective_fields(
            artifacts=cast(ProductArtifactStore, Artifacts()),
            scope=cast(ProductScope, object()),
            run_id="recovery",
            has_prior_rebase=mode != "original",
        )
        expected = original_request if mode == "original" else prior.request
        assert request == expected
        assert fields
        assert {source for source, _ in seen} == {"original" if mode == "original" else "prior"}
        assert len(seen) == 2


@pytest.mark.parametrize("fault", ["none", "stale", "missing"])
def test_multwindow_review_checks_every_field_generation(case: Any, fault: str) -> None:
    from insurance_harness.product_ingestion.field_comparison import verified_review_field_view

    request, delta, entity = case
    fields = compiler.compose_batch_output(request, delta).fields
    expected = view(request, entity, fields)
    contexts = [{"existing_knowledge": {"effective_fields": deepcopy(expected)}} for _ in range(2)]
    if fault == "stale":
        contexts[1]["existing_knowledge"]["effective_fields"]["fields"][0]["valid_time"] = "changed"
    if fault == "missing":
        contexts[1]["existing_knowledge"].pop("effective_fields")
    selection = {
        "contract": "native-dependency-selection.830.v2",
        "entity_id": entity,
        "domains": [{"domain": {"admission_context": context}} for context in contexts],
    }
    if fault == "none":
        assert verified_review_field_view(request, entity, fields, selection) == expected
    else:
        with pytest.raises(ValueError, match="field comparison"):
            verified_review_field_view(request, entity, fields, selection)
