"""Explicit conversions from archived annotations and compiler candidates."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from insurance_harness.eval.catalog import Catalog
from insurance_harness.eval.golden import GoldenEvidence, GoldenItem, Prediction, State

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class _Input(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class _LegacyEvidence(_Input):
    page: int
    quote: str


class _LegacyRecord(_Input):
    product_id: Identifier
    product_name: Identifier
    doc: Identifier
    field_name: str
    tri_state: State
    value: str | None
    evidence: list[_LegacyEvidence]
    reasoning: str | None = None
    note: str | None = None


class _Binding(_Input):
    entity_id: Identifier
    display_name: Identifier
    schema_pack_id: Identifier


class _Request(_Input):
    entity_bindings: list[_Binding]


class _CandidateField(_Input):
    entity_id: Identifier
    field_key: Identifier
    state: State
    value: str | None
    evidence: list[dict[str, Any]] = []

    @model_validator(mode="after")
    def validate_unknown_evidence(self) -> Self:
        if self.state == "unknown" and self.evidence:
            raise ValueError("unknown requires no evidence")
        return self


class _Output(_Input):
    fields: list[_CandidateField]


class _CompileResult(_Input):
    output: _Output


class _Candidate(_Input):
    request: _Request
    compile_result: _CompileResult


@dataclass(frozen=True)
class LegacyConversion:
    items: list[GoldenItem]
    unmapped: list[str]


def _document_path(root: Path, product_name: str, document: str) -> Path:
    # Check both components, so an absolute child cannot discard the dataset root.
    for component in (product_name, document):
        if Path(component).is_absolute() or ".." in Path(component).parts:
            raise ValueError("document path must be relative and remain inside the dataset")
    path = (root / product_name / document).resolve()
    if not path.is_relative_to(root):
        raise ValueError("document path is outside the dataset")
    return path


def golden_from_legacy(
    path: str | Path,
    catalog: Catalog,
    pack_display_name: str,
    dataset_root: str | Path,
) -> LegacyConversion:
    """Match exact titles, hash actual evidence files, and retain legacy provenance."""
    source = Path(path)
    root = Path(dataset_root).resolve()
    pack_id = catalog.pack_id(pack_display_name)
    items: list[GoldenItem] = []
    unmapped: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    hashes: dict[Path, str] = {}
    for line_number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = _LegacyRecord.model_validate(json.loads(line))
            field_key = catalog.field_key(pack_id, record.field_name)
            document = _document_path(root, record.product_name, record.doc)
            evidence: list[GoldenEvidence] = []
            if record.evidence:
                if document not in hashes:
                    hashes[document] = hashlib.sha256(document.read_bytes()).hexdigest()
                evidence = [GoldenEvidence(
                    document=record.doc, document_sha256=hashes[document],
                    page=entry.page, quote=entry.quote,
                ) for entry in record.evidence]
            note_parts = [text for text in (record.note, record.reasoning) if text]
            value = record.value
            if record.tri_state == "absent_explicitly":
                if value is not None:
                    note_parts.append(f"Legacy absent value: {value}")
                value = None
            # Validate even unmapped records, but never emit an invented field key.
            item = GoldenItem(
                pack_id=pack_id, product_id=record.product_id,
                field_key=field_key if field_key is not None else record.field_name,
                state=record.tri_state, value=value, evidence=evidence,
                judged_by=f"legacy:{source.parent.name}", note="\n".join(note_parts) or None,
            )
            if field_key is None:
                unmapped.append(record.field_name)
                continue
            if item.identity in seen:
                raise ValueError(f"duplicate golden identity: {item.identity}")
            seen.add(item.identity)
            items.append(item)
        except ValueError as exc:
            raise ValueError(f"invalid legacy record at line {line_number}: {exc}") from exc
    return LegacyConversion(items=items, unmapped=unmapped)


def _normalize_name(name: str) -> str:
    return "".join(name.split())


def _product_map(product_id_by_name: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, product_id in product_id_by_name.items():
        if not isinstance(name, str) or not _normalize_name(name):
            raise ValueError("product registration requires a nonblank name")
        if not isinstance(product_id, str) or not product_id.strip():
            raise ValueError("product registration requires a nonblank product ID")
        key = _normalize_name(name)
        if key in normalized and normalized[key] != product_id.strip():
            raise ValueError(f"conflicting normalized product name: {name}")
        normalized[key] = product_id.strip()
    return normalized


def predictions_from_candidate(
    candidate: object, product_id_by_name: Mapping[str, str],
) -> list[Prediction]:
    """Resolve every binding before producing canonical pack/product predictions."""
    data = _Candidate.model_validate(candidate)
    products = _product_map(product_id_by_name)
    bindings: dict[str, _Binding] = {}
    names: set[str] = set()
    unknown: list[str] = []
    for binding in data.request.entity_bindings:
        name = _normalize_name(binding.display_name)
        if binding.entity_id in bindings or name in names:
            raise ValueError(f"duplicate candidate entity binding: {binding.display_name}")
        bindings[binding.entity_id] = binding
        names.add(name)
        if name not in products:
            unknown.append(binding.display_name)
    if unknown:
        raise ValueError(f"unregistered product names: {', '.join(unknown)}")
    predictions: list[Prediction] = []
    seen: set[tuple[str, str, str]] = set()
    for field in data.compile_result.output.fields:
        if field.entity_id not in bindings:
            raise ValueError(f"unknown candidate entity_id: {field.entity_id}")
        binding = bindings[field.entity_id]
        prediction = Prediction(
            pack_id=binding.schema_pack_id,
            product_id=products[_normalize_name(binding.display_name)],
            field_key=field.field_key, state=field.state,
            # Archived compiler output can retain the negative statement as an absent value.
            value=None if field.state == "absent_explicitly" else field.value,
        )
        if prediction.identity in seen:
            raise ValueError(f"duplicate prediction identity: {prediction.identity}")
        seen.add(prediction.identity)
        predictions.append(prediction)
    return predictions
