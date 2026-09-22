from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
    aligned_existing_fields,
    validate_batch_candidate,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import evidence_for
from insurance_harness.knowledge_compiler.g3_field_tasks import (
    DiscoveryFieldProposalV1,
    FieldTaskEvidenceResultV1,
    adapt_catalog_field_tasks,
    adapt_discovery_field_tasks,
    batch_field_tasks,
)


def _request() -> BatchConceptCompileRequest830G3V1:
    fixture = Path(__file__).parent / "fixtures" / "batch_concept_compile_830_g3" / "candidate.json"
    return validate_batch_candidate(fixture.read_bytes()).request


def test_catalog_and_schema_less_discovery_share_one_field_task_contract() -> None:
    request = _request()
    carried = {(row.entity_id, row.field_key) for row in aligned_existing_fields(request)}
    tasks = adapt_catalog_field_tasks(request)
    expected = {
        (binding.entity_id, field_key)
        for binding in request.entity_bindings
        for field_key in binding.required_fields
        if (binding.entity_id, field_key) not in carried
    }
    assert {(task.entity_id, task.field_key) for task in tasks} == expected
    assert all(task.adapter_kind == "CATALOG_SCHEMA" for task in tasks)
    assert all(
        task.max_attempts == 1
        and task.allowed_states == ("present", "absent_explicitly", "unknown")
        for task in tasks
    )

    binding = request.entity_bindings[0]
    proposals = (
        DiscoveryFieldProposalV1(
            field_key="waiting_period_exception",
            short_title="等待期例外",
            description="等待期不适用的明确条件",
            value_spec="逐字条件列表",
            source_guidance="条款中的等待期与例外段落",
        ),
    )
    discovered = adapt_discovery_field_tasks(
        entity_id=binding.entity_id,
        entity_version=binding.entity_version,
        material_ids=binding.source_material_ids,
        proposals=proposals,
        discovery_protocol_version="g3-schema-discovery.830.v1",
    )
    assert discovered[0].adapter_kind == "SCHEMALESS_DISCOVERY"
    assert discovered[0].field_key == "waiting_period_exception"
    assert discovered[0].task_sha256 != tasks[0].task_sha256


def test_field_task_batches_are_stable_small_and_source_scoped() -> None:
    tasks = adapt_catalog_field_tasks(_request())
    batches = batch_field_tasks(tasks, max_fields_per_call=10)
    assert batches
    assert all(1 <= len(batch.tasks) <= 10 for batch in batches)
    assert tuple(task.task_sha256 for batch in batches for task in batch.tasks) == tuple(
        task.task_sha256 for task in tasks
    )
    assert all(
        batch.material_ids
        == tuple(sorted({mid for task in batch.tasks for mid in task.material_ids}))
        for batch in batches
    )
    assert batch_field_tasks(tasks, max_fields_per_call=10) == batches


def test_field_task_result_enforces_exact_tristate_and_evidence_scope() -> None:
    request = _request()
    task = adapt_catalog_field_tasks(request)[0]
    source = next(
        entry.blocks[0]
        for entry in request.resolution_inputs.corpus.entries
        if entry.material_id == task.material_ids[0]
    )
    evidence = evidence_for(source, 0, min(8, len(source.text)))
    known = FieldTaskEvidenceResultV1.create(
        task=task,
        state="present",
        value="九十日",
        evidence=(evidence,),
        concept_ids=(),
        conditions=(),
        exceptions=(),
        valid_time="",
        source_blocks=(source,),
    )
    assert known.result_sha256 == hashlib.sha256(known.canonical_bytes()).hexdigest()
    unknown = FieldTaskEvidenceResultV1.create(
        task=task,
        state="unknown",
        value=None,
        evidence=(),
        unknown_reason="NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS",
        concept_ids=(),
        conditions=(),
        exceptions=(),
        valid_time="",
    )
    assert unknown.state == "unknown"
    with pytest.raises(ValueError, match="known field task result"):
        FieldTaskEvidenceResultV1.create(
            task=task,
            state="present",
            value="九十日",
            evidence=(),
            concept_ids=(),
            conditions=(),
            exceptions=(),
            valid_time="",
        )
    with pytest.raises(ValueError, match="source scope"):
        FieldTaskEvidenceResultV1.create(
            task=task,
            state="present",
            value="九十日",
            evidence=(evidence.model_copy(update={"revision_id": "foreign"}),),
            concept_ids=(),
            conditions=(),
            exceptions=(),
            valid_time="",
        )


def test_number_constraint_rejects_nonfinite_values() -> None:
    from insurance_harness.knowledge_compiler.g3_field_tasks import FieldValueConstraintV1

    constraint = FieldValueConstraintV1(kind="NUMBER")
    assert constraint.accepts("1,200.5")
    assert not any(constraint.accepts(value) for value in ("nan", "NaN", "inf", "-Infinity"))


def test_catalog_explicit_product_type_enum_rejects_arbitrary_known_value() -> None:
    request = _request()
    task = next(
        row for row in adapt_catalog_field_tasks(request) if row.field_key == "product_type"
    )
    assert task.value_constraint.kind == "ENUM"
    assert set(task.value_constraint.allowed_values) == {
        "普通型",
        "分红型",
        "万能型",
        "投资连结型",
        "其他",
    }
    source = next(
        entry.blocks[0]
        for entry in request.resolution_inputs.corpus.entries
        if entry.material_id in task.material_ids
    )
    quote = evidence_for(source, 0, min(8, len(source.text)))
    with pytest.raises(ValueError, match="value constraint"):
        FieldTaskEvidenceResultV1.create(
            task=task,
            state="present",
            value="随意值",
            evidence=(quote,),
            concept_ids=(),
            conditions=(),
            exceptions=(),
            valid_time="",
            source_blocks=(source,),
        )


def test_catalog_constraint_preserves_open_and_compound_specs_as_text() -> None:
    from insurance_harness.knowledge_compiler import g3_field_tasks as module

    assert hasattr(module, "catalog_value_constraint"), "no catalog constraint compiler"
    for spec in (
        "按条款说明给付条件",
        "趸缴、1年、5年等",
        "个人代理、银行代理（可多选）",
        "中国大陆、境外；以实际产品为准",
        "含保额、年龄及其他条件",
        "安有医、安有护、居家养老",
        None,
    ):
        assert module.catalog_value_constraint(spec).kind == "TEXT"
    assert module.catalog_value_constraint("是、否").kind == "ENUM"
