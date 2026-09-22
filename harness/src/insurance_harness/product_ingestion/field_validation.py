"""Durable derived field validation; original extraction attempts remain immutable."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import Evidence, SourceBlock
from insurance_harness.knowledge_compiler.g3_field_tasks import (
    FieldTaskEvidenceResultV1,
    FieldTaskV1,
)
from insurance_harness.product_ingestion.checkpoints import field_digest
from insurance_harness.product_ingestion.models import FieldAttemptSnapshot, FieldOutcomeKind
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot
from insurance_harness.product_ingestion.source_geometry import (
    prepare_evidence_locations,
    project_evidence_locations,
)


class FieldValidationChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    original_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_ref: str
    outcome: FieldOutcomeKind
    reason: str
    validated_result: dict[str, Any] | None
    mappings: tuple[dict[str, Any], ...] = ()


class FieldValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract: Literal["product-field-validation.v1"] = "product-field-validation.v1"
    source_snapshot_digests: dict[str, str]
    input_digests: dict[str, str]
    counts: dict[str, int]
    changes: dict[str, FieldValidationChange]


def apply_field_validation(
    attempts: tuple[FieldAttemptSnapshot, ...], report: FieldValidationReport
) -> tuple[FieldAttemptSnapshot, ...]:
    """One effective view for compilation, display, counting and field retry."""
    if set(report.input_digests) != {row.attempt_id for row in attempts} or not (
        set(report.changes) <= set(report.input_digests)
    ):
        raise ValueError("field validation input coverage changed")
    result: list[FieldAttemptSnapshot] = []
    for row in attempts:
        if report.input_digests.get(row.attempt_id) != field_digest(row):
            raise ValueError("field validation input changed")
        change = report.changes.get(row.attempt_id)
        if change is None:
            result.append(row)
            continue
        if change.original_digest != field_digest(row) or change.raw_ref != row.raw_ref:
            raise ValueError("field validation input changed")
        if change.outcome is FieldOutcomeKind.EXTRACTION_FAILED:
            if change.validated_result is not None or not change.reason:
                raise ValueError("invalid field validation failure")
        elif change.outcome is not FieldOutcomeKind.VERIFIED or change.validated_result is None:
            raise ValueError("invalid field validation result")
        result.append(
            row.model_copy(
                update={
                    "outcome": change.outcome,
                    "reason": change.reason,
                    "validated_result": change.validated_result,
                }
            )
        )
    counts = {kind.value: sum(row.outcome is kind for row in result) for kind in FieldOutcomeKind}
    if counts != report.counts:
        raise ValueError("field validation counts mismatch")
    return tuple(result)


def validate_field_attempts(
    *,
    tasks: tuple[FieldTaskV1, ...],
    attempts: tuple[FieldAttemptSnapshot, ...],
    snapshots: dict[str, DecodedSourceSnapshot],
) -> FieldValidationReport:
    """Validate current fields against already authenticated parser snapshots.

    Source authentication happens at the existing snapshot boundary. A malformed
    native artifact is a source failure; an unlocatable ordinary field is a
    field failure and cannot carry a value into the compiled release.
    """
    by_task = {(t.entity_id, t.field_key): t for t in tasks}
    if len(by_task) != len(tasks) or set(by_task) != {(r.entity_id, r.field_key) for r in attempts}:
        raise ValueError("field validation task coverage mismatch")
    changes: dict[str, FieldValidationChange] = {}
    source_digests: dict[str, str] = {}
    evidence_by_source: dict[str, list[Evidence]] = {}
    for row in attempts:
        if row.outcome is FieldOutcomeKind.VERIFIED:
            result = FieldTaskEvidenceResultV1.model_validate(row.validated_result)
            if hashlib.sha256(result.canonical_bytes()).hexdigest() != result.result_sha256:
                raise ValueError("field validation original result hash mismatch")
            for evidence in result.evidence:
                evidence_by_source.setdefault(evidence.knowledge_id, []).append(evidence)
    if not set(evidence_by_source) <= snapshots.keys():
        raise ValueError("field validation source snapshot missing")
    indexes = {
        knowledge: prepare_evidence_locations(snapshots[knowledge], evidence)
        for knowledge, evidence in evidence_by_source.items()
    }
    for row in attempts:
        if row.outcome is not FieldOutcomeKind.VERIFIED:
            continue
        task = by_task[(row.entity_id, row.field_key)]
        original = FieldTaskEvidenceResultV1.model_validate(row.validated_result)
        if task.task_sha256 != row.task_sha256 or original.task_sha256 != row.task_sha256:
            raise ValueError("field validation task identity mismatch")
        parts: list[Evidence] = []
        mappings: list[dict[str, Any]] = []
        source_blocks: list[SourceBlock] = []
        reason: str | None = None
        for evidence in original.evidence:
            decoded = snapshots.get(evidence.knowledge_id)
            if decoded is None:
                raise ValueError("field validation source snapshot missing")
            source_digests[evidence.knowledge_id] = decoded.snapshot["snapshot_sha256"]
            source_blocks.extend(decoded.blocks)
            try:
                fragments, mapping = project_evidence_locations(
                    evidence, decoded, page_index=indexes[evidence.knowledge_id]
                )
            except ValueError as error:
                if not str(error).startswith("EVIDENCE_"):
                    raise
                reason = str(error)
                break
            for part in fragments:
                if part not in parts:
                    parts.append(part)
            mappings.append(mapping)
        if reason:
            changes[row.attempt_id] = FieldValidationChange(
                original_digest=field_digest(row),
                raw_ref=row.raw_ref,
                outcome=FieldOutcomeKind.EXTRACTION_FAILED,
                reason=reason,
                validated_result=None,
                mappings=tuple(mappings),
            )
            continue
        # Reuse the exact task/source/value validator rather than forging a
        # result hash after changing evidence locations.
        checked = FieldTaskEvidenceResultV1.create(
            task=task,
            state=original.state,
            value=original.value,
            evidence=tuple(parts),
            concept_ids=original.concept_ids,
            conditions=original.conditions,
            exceptions=original.exceptions,
            valid_time=original.valid_time,
            unknown_reason=original.unknown_reason,
            source_blocks=tuple(
                dict(((b.revision_id, b.block_id), b) for b in source_blocks).values()
            ),
        )
        if checked != original:
            changes[row.attempt_id] = FieldValidationChange(
                original_digest=field_digest(row),
                raw_ref=row.raw_ref,
                outcome=FieldOutcomeKind.VERIFIED,
                reason="VALIDATED_PAGE_LOCATIONS",
                validated_result=checked.model_dump(mode="json"),
                mappings=tuple(mappings),
            )
    counts = Counter(r.outcome.value for r in attempts)
    by_id = {r.attempt_id: r for r in attempts}
    if len(by_id) != len(attempts):
        raise ValueError("field validation duplicate attempt")
    for identifier, change in changes.items():
        counts[by_id[identifier].outcome.value] -= 1
        counts[change.outcome.value] += 1
    return FieldValidationReport(
        source_snapshot_digests=source_digests,
        input_digests={r.attempt_id: field_digest(r) for r in attempts},
        counts={kind.value: counts[kind.value] for kind in FieldOutcomeKind},
        changes=changes,
    )
