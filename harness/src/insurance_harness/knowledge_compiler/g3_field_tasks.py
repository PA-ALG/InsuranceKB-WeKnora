"""Schema-neutral field extraction tasks for the G3 knowledge compiler."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from datetime import date
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

from .batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
    aligned_existing_fields,
)
from .concept_free_wiki_830_g2 import Evidence, SourceBlock, verify_evidence

Hash = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[StrictStr, StringConstraints(min_length=1, max_length=512)]
FieldKey = Annotated[StrictStr, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")]
FieldState = Literal["present", "absent_explicitly", "unknown"]
ValueKind = Literal["TEXT", "NUMBER", "DATE", "ENUM", "TABLE"]


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: item.model_dump(mode="json", round_trip=True),
    ).encode()


def _hash(contract: str, value: object) -> str:
    return hashlib.sha256(contract.encode("ascii") + b"\0" + _json_bytes(value)).hexdigest()


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class FieldTaskSourceV1(_Frozen):
    contract: Literal["g3-field-task-source.830.v1"] = "g3-field-task-source.830.v1"
    material_id: Name
    revision_id: Name
    block_id: Name
    source_hash: Hash
    parser_identity: Name


class FieldValueConstraintV1(_Frozen):
    contract: Literal["g3-field-value-constraint.830.v1"] = "g3-field-value-constraint.830.v1"
    kind: ValueKind
    allowed_values: tuple[Name, ...] = ()
    declared_value_spec: StrictStr | None = None

    @model_validator(mode="after")
    def validate_constraint(self) -> Self:
        if self.allowed_values != tuple(sorted(set(self.allowed_values))):
            raise ValueError("field constraint values must be canonical unique")
        if (self.kind == "ENUM") != bool(self.allowed_values):
            raise ValueError("ENUM is the only constraint with allowed values")
        return self

    def accepts(self, value: str) -> bool:
        if not value:
            return False
        if self.kind in {"TEXT", "TABLE"}:
            return True
        if self.kind == "ENUM":
            return value in self.allowed_values
        if self.kind == "NUMBER":
            try:
                number = float(value.replace(",", ""))
            except ValueError:
                return False
            return math.isfinite(number)
        try:
            date.fromisoformat(value)
        except ValueError:
            return False
        return True


class FieldTaskV1(_Frozen):
    contract: Literal["g3-field-task.830.v1"] = "g3-field-task.830.v1"
    adapter_kind: Literal["CATALOG_SCHEMA", "SCHEMALESS_DISCOVERY"]
    adapter_version: Name
    entity_id: Name
    entity_version: Name
    field_key: FieldKey
    short_title: Name
    description: StrictStr | None
    source_guidance: StrictStr | None
    value_constraint: FieldValueConstraintV1
    material_ids: tuple[Name, ...]
    allowed_sources: tuple[FieldTaskSourceV1, ...]
    concept_ids: tuple[Name, ...] = ()
    allowed_states: tuple[FieldState, ...] = (
        "present",
        "absent_explicitly",
        "unknown",
    )
    max_attempts: Literal[1] = 1
    task_sha256: Hash

    @model_validator(mode="after")
    def validate_task(self) -> Self:
        if self.material_ids != tuple(sorted(set(self.material_ids))) or not self.material_ids:
            raise ValueError("field task material scope must be canonical nonempty")
        source_keys = tuple(
            (row.material_id, row.revision_id, row.block_id) for row in self.allowed_sources
        )
        if source_keys != tuple(sorted(set(source_keys))):
            raise ValueError("field task source scope must be canonical unique")
        if set(row.material_id for row in self.allowed_sources) - set(self.material_ids):
            raise ValueError("field task source exceeds material scope")
        if self.allowed_states != ("present", "absent_explicitly", "unknown"):
            raise ValueError("field task tri-state contract drift")
        payload = self.model_dump(mode="json", exclude={"task_sha256"})
        if self.task_sha256 != _hash(self.contract, payload):
            raise ValueError("field task hash mismatch")
        return self


class DiscoveryFieldProposalV1(_Frozen):
    contract: Literal["g3-discovery-field-proposal.830.v1"] = "g3-discovery-field-proposal.830.v1"
    field_key: FieldKey
    short_title: Name
    description: StrictStr | None = None
    value_spec: StrictStr | None = None
    source_guidance: StrictStr | None = None
    value_kind: ValueKind = "TEXT"
    allowed_values: tuple[Name, ...] = ()
    concept_ids: tuple[Name, ...] = ()


class FieldTaskBatchV1(_Frozen):
    contract: Literal["g3-field-task-batch.830.v1"] = "g3-field-task-batch.830.v1"
    ordinal: Annotated[StrictInt, Field(ge=0)]
    tasks: tuple[FieldTaskV1, ...] = Field(min_length=1, max_length=10)
    material_ids: tuple[Name, ...]
    batch_sha256: Hash

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        if self.material_ids != tuple(
            sorted({material for task in self.tasks for material in task.material_ids})
        ):
            raise ValueError("field task batch material union mismatch")
        if self.batch_sha256 != _hash(
            self.contract, self.model_dump(mode="json", exclude={"batch_sha256"})
        ):
            raise ValueError("field task batch hash mismatch")
        return self


class FieldTaskEvidenceResultV1(_Frozen):
    contract: Literal["g3-field-task-evidence-result.830.v1"] = (
        "g3-field-task-evidence-result.830.v1"
    )
    task_sha256: Hash
    state: FieldState
    value: StrictStr | None
    evidence: tuple[Evidence, ...]
    unknown_reason: Name | None = None
    concept_ids: tuple[Name, ...]
    conditions: tuple[StrictStr, ...]
    exceptions: tuple[StrictStr, ...]
    valid_time: StrictStr
    result_sha256: Hash

    def canonical_bytes(self) -> bytes:
        return _json_bytes(self.model_dump(mode="json", exclude={"result_sha256"}))

    @classmethod
    def create(
        cls,
        *,
        task: FieldTaskV1,
        state: FieldState,
        value: str | None,
        evidence: tuple[Evidence, ...],
        concept_ids: tuple[str, ...],
        conditions: tuple[str, ...],
        exceptions: tuple[str, ...],
        valid_time: str,
        unknown_reason: str | None = None,
        source_blocks: Sequence[SourceBlock] = (),
    ) -> FieldTaskEvidenceResultV1:
        allowed = {
            (row.revision_id, row.block_id, row.source_hash, row.parser_identity)
            for row in task.allowed_sources
        }
        for item in evidence:
            if (
                item.revision_id,
                item.block_id,
                item.source_hash,
                item.parser_identity,
            ) not in allowed:
                raise ValueError("field task evidence exceeds source scope")
            if source_blocks:
                verify_evidence(item, source_blocks)
        if state in {"present", "absent_explicitly"}:
            if value is None or not evidence or unknown_reason is not None:
                raise ValueError("known field task result requires value and evidence")
            if not task.value_constraint.accepts(value):
                raise ValueError("known field task result violates value constraint")
        elif value is not None or evidence or not unknown_reason:
            raise ValueError("unknown field task result must be empty and reviewable")
        payload: dict[str, object] = {
            "contract": "g3-field-task-evidence-result.830.v1",
            "task_sha256": task.task_sha256,
            "state": state,
            "value": value,
            "evidence": evidence,
            "unknown_reason": unknown_reason,
            "concept_ids": concept_ids,
            "conditions": conditions,
            "exceptions": exceptions,
            "valid_time": valid_time,
        }
        wire = json.loads(_json_bytes(payload))
        return cls.model_validate(
            {**wire, "result_sha256": hashlib.sha256(_json_bytes(wire)).hexdigest()}
        )


def _task(value: dict[str, object]) -> FieldTaskV1:
    payload = {"contract": "g3-field-task.830.v1", **value}
    return FieldTaskV1.model_validate(
        {**payload, "task_sha256": _hash("g3-field-task.830.v1", payload)}
    )


def _source_scope(
    request: BatchConceptCompileRequest830G3V1, material_ids: tuple[str, ...]
) -> tuple[FieldTaskSourceV1, ...]:
    selected = set(material_ids)
    return tuple(
        FieldTaskSourceV1(
            material_id=entry.material_id,
            revision_id=source.revision_id,
            block_id=source.block_id,
            source_hash=source.source_hash,
            parser_identity=source.parser_identity,
        )
        for entry in request.resolution_inputs.corpus.entries
        if entry.material_id in selected
        for source in entry.blocks
    )


def catalog_value_constraint(
    value_spec: str | None,
    *,
    single_valued: bool = False,
) -> FieldValueConstraintV1:
    """Compile only a closed list whose single-value meaning is established.

    The catalog has no cardinality field. A bare list can describe multiple tags,
    so it stays TEXT unless the adapter explicitly identifies a scalar field.
    Boolean yes/no is the only unambiguous default. Values always come from the
    declared spec; open lists, conditions and multiselect annotations stay TEXT.
    """
    spec = "" if value_spec is None else value_spec.strip()
    scalar = single_valued or spec in {"是、否", "否、是"}
    parts = tuple(part.strip() for part in spec.split("、"))
    open_or_compound = any(
        word in spec
        for word in (
            "等",
            "多选",
            "条件",
            "说明",
            "例如",
            "包括",
            "为准",
            "以及",
            "及其他",
        )
    )
    closed = (
        scalar
        and not open_or_compound
        and 2 <= len(parts) <= 32
        and len(set(parts)) == len(parts)
        and all(re.fullmatch(r"[\u3400-\u9fffA-Za-z0-9+_-]{1,24}", part) for part in parts)
    )
    return FieldValueConstraintV1(
        kind="ENUM" if closed else "TEXT",
        allowed_values=tuple(sorted(parts)) if closed else (),
        declared_value_spec=value_spec,
    )


def adapt_catalog_field_tasks(
    request: BatchConceptCompileRequest830G3V1,
) -> tuple[FieldTaskV1, ...]:
    """Adapt only non-carried required fields from the bound Catalog profiles."""

    carried = {(row.entity_id, row.field_key) for row in aligned_existing_fields(request)}
    catalog = {
        (entry.pack.schema_pack_id, entry.pack.schema_version, entry.pack.schema_pack_sha256): entry
        for entry in request.catalog.entries
    }
    rows: list[FieldTaskV1] = []
    for binding in sorted(request.entity_bindings, key=lambda row: row.entity_id):
        entry = catalog.get(
            (binding.schema_pack_id, binding.schema_version, binding.schema_pack_sha256)
        )
        if entry is None:
            raise ValueError("field task catalog binding mismatch")
        definitions = {row.field_key: row for row in entry.pack.fields}
        sources = _source_scope(request, binding.source_material_ids)
        for field_key in sorted(binding.required_fields):
            if (binding.entity_id, field_key) in carried:
                continue
            definition = definitions.get(field_key)
            if definition is None:
                raise ValueError("field task absent from bound Catalog profile")
            rows.append(
                _task(
                    {
                        "adapter_kind": "CATALOG_SCHEMA",
                        "adapter_version": "g3-catalog-field-task.830.v2",
                        "entity_id": binding.entity_id,
                        "entity_version": binding.entity_version,
                        "field_key": field_key,
                        "short_title": definition.short_title,
                        "description": definition.description,
                        "source_guidance": definition.source_guidance,
                        "value_constraint": catalog_value_constraint(
                            definition.value_spec,
                            # This existing catalog field is an explicitly single
                            # product benefit type. Other lists can be multi-valued.
                            single_valued=(
                                definition.field_key == "product_type"
                                and definition.short_title == "产品类型"
                            ),
                        ),
                        "material_ids": binding.source_material_ids,
                        "allowed_sources": sources,
                        "concept_ids": (),
                        "allowed_states": ("present", "absent_explicitly", "unknown"),
                        "max_attempts": 1,
                    }
                )
            )
    return tuple(rows)


def adapt_discovery_field_tasks(
    *,
    entity_id: str,
    entity_version: str,
    material_ids: tuple[str, ...],
    proposals: tuple[DiscoveryFieldProposalV1, ...],
    discovery_protocol_version: str,
    allowed_sources: tuple[FieldTaskSourceV1, ...] = (),
) -> tuple[FieldTaskV1, ...]:
    """Admit schema-less discoveries into the same bounded task/result contract."""

    if len({row.field_key for row in proposals}) != len(proposals):
        raise ValueError("duplicate discovery field proposal")
    return tuple(
        _task(
            {
                "adapter_kind": "SCHEMALESS_DISCOVERY",
                "adapter_version": discovery_protocol_version,
                "entity_id": entity_id,
                "entity_version": entity_version,
                "field_key": row.field_key,
                "short_title": row.short_title,
                "description": row.description,
                "source_guidance": row.source_guidance,
                "value_constraint": FieldValueConstraintV1(
                    kind=row.value_kind,
                    allowed_values=row.allowed_values,
                    declared_value_spec=row.value_spec,
                ),
                "material_ids": material_ids,
                "allowed_sources": allowed_sources,
                "concept_ids": row.concept_ids,
                "allowed_states": ("present", "absent_explicitly", "unknown"),
                "max_attempts": 1,
            }
        )
        for row in sorted(proposals, key=lambda item: item.field_key)
    )


def batch_field_tasks(
    tasks: Sequence[FieldTaskV1], *, max_fields_per_call: int = 10
) -> tuple[FieldTaskBatchV1, ...]:
    if not 1 <= max_fields_per_call <= 10:
        raise ValueError("field task call size must be within 1..10")
    ordered = tuple(sorted(tasks, key=lambda row: (row.entity_id, row.field_key)))
    if len({row.task_sha256 for row in ordered}) != len(ordered):
        raise ValueError("duplicate field task")
    batches: list[FieldTaskBatchV1] = []
    for ordinal, offset in enumerate(range(0, len(ordered), max_fields_per_call)):
        window = ordered[offset : offset + max_fields_per_call]
        payload = {
            "contract": "g3-field-task-batch.830.v1",
            "ordinal": ordinal,
            "tasks": window,
            "material_ids": tuple(
                sorted({material for task in window for material in task.material_ids})
            ),
        }
        wire = json.loads(_json_bytes(payload))
        batches.append(
            FieldTaskBatchV1.model_validate(
                {**wire, "batch_sha256": _hash("g3-field-task-batch.830.v1", wire)}
            )
        )
    return tuple(batches)


__all__ = [
    "DiscoveryFieldProposalV1",
    "FieldTaskBatchV1",
    "FieldTaskEvidenceResultV1",
    "FieldTaskSourceV1",
    "FieldTaskV1",
    "FieldValueConstraintV1",
    "adapt_catalog_field_tasks",
    "adapt_discovery_field_tasks",
    "batch_field_tasks",
    "catalog_value_constraint",
]
