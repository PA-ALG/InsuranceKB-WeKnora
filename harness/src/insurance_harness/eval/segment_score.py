"""Segment selection scoring against Golden v2 (S4d Spec §3.5).

Golden v2 stores evidence as page quotes, not segment ids, so it survives changes to the
segmentation rules: Golden quotes and predicted evidence are both mapped onto the current
segments, ignoring whitespace and width. A Golden quote that maps to no segment (missing,
ambiguous, or cited against another document fingerprint) is counted, never guessed.
Values are scored separately by the S2c semantic path.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from insurance_harness.compilers.schema_fields.engine import FieldResult
from insurance_harness.evidence.quote_verification import Digest, NonBlank, VerifiedQuote
from insurance_harness.evidence.segments import SegmentedSource

State = Literal["present", "absent_explicitly", "unknown"]
COMPLETE_RECALL = 0.8


class GoldenV2Evidence(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    document: NonBlank
    document_sha256: Digest
    page: int = Field(ge=1)
    quote: NonBlank
    segment_id: NonBlank | None  # the id at annotation time; scoring re-maps the quote


class GoldenV2Field(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    field_key: NonBlank
    state: State
    value: str | None
    reason: str
    evidence: tuple[GoldenV2Evidence, ...]

    @model_validator(mode="after")
    def _value_and_evidence_fit_state(self) -> Self:
        if self.state == "present":
            fits = bool(self.value and self.value.strip()) and bool(self.evidence)
        else:
            fits = self.value is None and bool(self.evidence) == (self.state != "unknown")
        if not fits:
            raise ValueError(f"{self.field_key}: value or evidence does not fit {self.state}")
        return self


class GoldenV2(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    product_id: NonBlank
    cards_version: NonBlank
    fields: tuple[GoldenV2Field, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_field_keys(self) -> Self:
        keys = [field.field_key for field in self.fields]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate field_key in Golden v2")
        return self


def load_golden_v2(path: Path) -> GoldenV2:
    """One product's Golden v2 file; any read, JSON or shape problem is a ValueError."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read Golden v2 file {path.name}") from exc
    return GoldenV2.model_validate_json(text)


@dataclass(frozen=True)
class FieldSelection:
    field_key: str
    golden_state: State
    predicted_state: State | Literal["missing"]
    recall: float | None  # None only when no Golden quote maps to a current segment
    precision: float | None  # None unless the prediction is present and selects segments


@dataclass(frozen=True)
class SelectionReport:
    fields: tuple[FieldSelection, ...]
    recall_mean: float | None
    precision_mean: float | None
    complete_at_08: int
    state_agreement: tuple[int, int]
    unmapped_golden_quotes: int


def score_selection(
    source: SegmentedSource, golden: GoldenV2, predicted: Sequence[FieldResult]
) -> SelectionReport:
    """Per present Golden field: recall |E∩G|/|G| and precision |E∩G|/|E| over segment ids."""
    by_key: dict[str, FieldResult] = {}
    for result in predicted:
        if by_key.setdefault(result.field_key, result) is not result:
            raise ValueError(f"duplicate prediction for {result.field_key}")
    fingerprints = {(p.document, p.page): p.document_sha256.lower() for p in source.pages}

    def segments(quote: GoldenV2Evidence | VerifiedQuote) -> set[str]:
        if fingerprints.get((quote.document, quote.page)) != quote.document_sha256.lower():
            return set()
        return source.locate(quote.document, quote.page, quote.quote)

    scored: list[FieldSelection] = []
    agree = unmapped = 0
    for field in golden.fields:
        guess = by_key.get(field.field_key)
        state: State | Literal["missing"] = guess.state if guess is not None else "missing"
        # Three-state agreement; a missing prediction counts as unknown, nothing else is merged.
        agree += field.state == state or (field.state == "unknown" and state == "missing")
        located = [segments(quote) for quote in field.evidence]
        unmapped += sum(1 for ids in located if not ids)
        if field.state != "present":
            continue
        gold = {sid for ids in located for sid in ids}
        chosen = (
            {sid for quote in guess.evidence for sid in segments(quote)}
            if guess is not None and guess.state == "present"
            else set()
        )
        hit = len(gold & chosen)
        recall = hit / len(gold) if gold else None
        precision = hit / len(chosen) if gold and chosen else None
        scored.append(FieldSelection(field.field_key, field.state, state, recall, precision))

    recalls = [f.recall for f in scored if f.recall is not None]
    precisions = [f.precision for f in scored if f.precision is not None]
    return SelectionReport(
        fields=tuple(scored),
        recall_mean=fmean(recalls) if recalls else None,
        precision_mean=fmean(precisions) if precisions else None,
        complete_at_08=sum(1 for value in recalls if value >= COMPLETE_RECALL),
        state_agreement=(agree, len(golden.fields)),
        unmapped_golden_quotes=unmapped,
    )
