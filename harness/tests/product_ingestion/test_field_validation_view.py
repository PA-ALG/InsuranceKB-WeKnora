from __future__ import annotations

# ruff: noqa: F811
import importlib
import typing
from datetime import UTC, datetime

import pytest

from insurance_harness.knowledge_compiler.g3_field_tasks import FieldTaskEvidenceResultV1
from insurance_harness.product_ingestion.models import (
    FieldAttemptSnapshot,
    FieldCacheIdentity,
    FieldOutcomeKind,
    SourceDependency,
)
from tests.product_ingestion.test_extraction import tasks
from tests.product_ingestion.test_field_page_validation import evidence_for
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_source_geometry import native_snapshot


def implementation() -> typing.Any:
    try:
        return importlib.import_module("insurance_harness.product_ingestion.field_validation")
    except ModuleNotFoundError:
        pytest.fail("field location validation is not persisted as an effective field view")


def example(snapshot: typing.Any) -> tuple[typing.Any, ...]:
    decoded = native_snapshot(snapshot)
    task = tasks(decoded.blocks[0], keys=("benefit",))[0]
    value = FieldTaskEvidenceResultV1.create(
        task=task,
        state="present",
        value="保留原值",
        evidence=(evidence_for(decoded),),
        concept_ids=(),
        conditions=(),
        exceptions=(),
        valid_time="",
        source_blocks=decoded.blocks,
    )
    row = FieldAttemptSnapshot(
        attempt_id="attempt",
        run_id="original",
        window_id="window",
        call_id="call",
        entity_id=task.entity_id,
        field_key=task.field_key,
        task_sha256=task.task_sha256,
        cache_identity=FieldCacheIdentity(
            product_identity_sha256="a" * 64,
            entity_id=task.entity_id,
            field_key=task.field_key,
            source_dependencies=(
                SourceDependency(
                    source_revision_id=decoded.blocks[0].revision_id,
                    source_sha256=decoded.blocks[0].source_hash,
                ),
            ),
            schema_adapter_id="schema",
            schema_adapter_sha256="b" * 64,
            schema_version="1",
        ),
        validation_version="old",
        model_policy_sha256="c" * 64,
        prompt_policy_sha256="d" * 64,
        outcome=FieldOutcomeKind.VERIFIED,
        reason="VALIDATED",
        validated_result=value.model_dump(mode="json"),
        raw_ref="raw-original",
        attempt=1,
        created_at=datetime.now(UTC),
        reused_from_attempt_id=None,
    )
    return decoded, task, row


def test_effective_view_preserves_raw_and_value_and_survives_serialization(
    snapshot: typing.Any,
) -> None:
    m = implementation()
    decoded, task, row = example(snapshot)
    before = row.model_dump_json()
    report = m.validate_field_attempts(
        tasks=(task,), attempts=(row,), snapshots={decoded.blocks[0].knowledge_id: decoded}
    )
    loaded = m.FieldValidationReport.model_validate_json(report.model_dump_json())
    effective = m.apply_field_validation((row,), loaded)[0]
    assert effective.validated_result["value"] == "保留原值"
    assert len(effective.validated_result["evidence"]) == 2
    assert effective.raw_ref == row.raw_ref and row.model_dump_json() == before
    assert loaded.counts == {"verified": 1, "not_provided": 0, "extraction_failed": 0}
    changed = row.model_copy(update={"raw_ref": "different-response"})
    with pytest.raises(ValueError, match="validation input changed"):
        m.apply_field_validation((changed,), loaded)


def test_bad_location_is_one_failed_field_without_value_or_raw_loss(snapshot: typing.Any) -> None:
    import json
    from dataclasses import replace

    m = implementation()
    decoded, task, row = example(snapshot)
    native = json.loads(decoded.native_bytes)
    native["pages"][0]["bboxes"] = native["pages"][0]["bboxes"][1:]
    decoded = replace(decoded, native_bytes=json.dumps(native).encode())
    report = m.validate_field_attempts(
        tasks=(task,), attempts=(row,), snapshots={decoded.blocks[0].knowledge_id: decoded}
    )
    effective = m.apply_field_validation((row,), report)[0]
    assert effective.outcome is FieldOutcomeKind.EXTRACTION_FAILED
    assert (
        effective.validated_result is None
        and effective.reason == "EVIDENCE_CHARACTER_LOCATION_MISSING"
    )
    assert effective.raw_ref == "raw-original" and row.outcome is FieldOutcomeKind.VERIFIED
    assert report.counts == {"verified": 0, "not_provided": 0, "extraction_failed": 1}
