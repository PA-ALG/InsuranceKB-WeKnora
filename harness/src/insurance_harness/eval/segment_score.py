"""Segment selection scoring against Golden v2 (S4d Spec §3.5, S4e Spec §3.2).

Golden v2 stores evidence as page quotes with the segment id they were labelled on. A Golden
quote is taken by that id while the segment still holds exactly the quoted text, and otherwise
mapped onto the current segments like predicted evidence, ignoring whitespace and width. A quote
that maps to no segment (missing, ambiguous, or cited against another document fingerprint) is
counted, never guessed. A passage repeated word for word in another document is the same evidence
(user ruling 2026-10-15), so a segment and its copies credit each other. Values are scored
separately by the S2c semantic path.

usage: python -m insurance_harness.eval.segment_score --run-root <dir> --products <id>...
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from insurance_harness.catalog.trust_policy import load_trust_policy
from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.eval.product_sources import (
    check_product_id,
    source_directory,
    trusted_source_pages,
)
from insurance_harness.eval.segment_rules import (
    RuledSource,
    ScoringRules,
    load_scoring_rules,
    neutral_segments,
)
from insurance_harness.evidence.quote_verification import Digest, NonBlank, VerifiedQuote
from insurance_harness.evidence.segments import SegmentedSource, same_text

State = Literal["present", "absent_explicitly", "unknown"]
COMPLETE_RECALL = 0.8
GOLDEN_DIR = Path("dataset/golden/v2")


class GoldenV2Evidence(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    document: NonBlank
    document_sha256: Digest
    page: int = Field(ge=1)
    quote: NonBlank
    segment_id: NonBlank | None  # the id at annotation time; used while it still holds the quote


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
    unmapped_predicted_quotes: int  # evidence of scored predictions that maps to no segment
    copy_credits: tuple[int, int]  # (Golden segments, selected segments) credited via a copy


def score_selection(
    source: SegmentedSource,
    golden: GoldenV2,
    predicted: Sequence[FieldResult],
    *,
    rules: ScoringRules | None = None,
) -> SelectionReport:
    """Per present Golden field: recall over Golden segments and precision over selected ones.

    A Golden segment counts as found when it or one of its copies is selected; a selected
    segment counts as right when it or one of its copies is in Golden. Without rules this is the
    S4e scoring; with rules (S12a) copies fold further and neutral segments leave both sides.
    """
    ruled = RuledSource(source, rules) if rules is not None else None
    copies = ruled.copies if ruled is not None else source.copies
    by_key: dict[str, FieldResult] = {}
    for result in predicted:
        if by_key.setdefault(result.field_key, result) is not result:
            raise ValueError(f"duplicate prediction for {result.field_key}")
    fingerprints = {(p.document, p.page): p.document_sha256.lower() for p in source.pages}

    def segments(quote: GoldenV2Evidence | VerifiedQuote, field_key: str) -> set[str]:
        if not _trusted_document(source, field_key, quote.document):
            return set()
        if fingerprints.get((quote.document, quote.page)) != quote.document_sha256.lower():
            return set()
        recorded = quote.segment_id if isinstance(quote, GoldenV2Evidence) else None
        return source.locate(quote.document, quote.page, quote.quote, recorded)

    scored: list[FieldSelection] = []
    agree = unmapped = unmapped_predicted = copied_gold = copied_chosen = 0
    for field in golden.fields:
        guess = by_key.get(field.field_key)
        state: State | Literal["missing"] = guess.state if guess is not None else "missing"
        # Three-state agreement; a missing prediction counts as unknown, nothing else is merged.
        agree += field.state == state or (field.state == "unknown" and state == "missing")
        located = [segments(quote, field.field_key) for quote in field.evidence]
        unmapped += sum(1 for ids in located if not ids)
        if field.state != "present":
            continue
        gold = {sid for ids in located for sid in ids}
        chosen: set[str] = set()
        if guess is not None and guess.state == "present":
            recorded = _recorded_selection(source, guess)
            if recorded is not None:
                chosen = recorded
            else:
                for quote in guess.evidence:
                    ids = segments(quote, field.field_key)
                    unmapped_predicted += not ids
                    chosen |= ids
        neutral = set()
        if ruled is not None:
            neutral = neutral_segments(ruled, field.field_key, gold, ruled.rules)
        required, counted = gold - neutral, chosen - neutral
        found = {sid for sid in required if sid in chosen or copies(sid) & chosen}
        right = {sid for sid in counted if sid in gold or copies(sid) & gold}
        copied_gold += len(found - chosen)
        copied_chosen += len(right - gold)
        recall = len(found) / len(required) if required else None
        precision = len(right) / len(counted) if required and counted else None
        scored.append(FieldSelection(field.field_key, field.state, state, recall, precision))

    return _summary(
        scored,
        state_agreement=(agree, len(golden.fields)),
        unmapped_golden_quotes=unmapped,
        unmapped_predicted_quotes=unmapped_predicted,
        copy_credits=(copied_gold, copied_chosen),
    )


def _trusted_document(source: SegmentedSource, field_key: str, document: str) -> bool:
    role = source.header_role(document)
    return role is None or field_key in load_trust_policy().header_fields(role)


def _recorded_selection(source: SegmentedSource, result: FieldResult) -> set[str] | None:
    """The run's own segment ids, trusted only while they cut the saved evidence (S4f).

    Document, fingerprint and page must match exactly; the text may differ only in whitespace
    and width, the same rule Golden segment ids follow (page text keeps CRLF since S4c-1).
    """
    if not result.segment_ids:
        return None
    if any(not _trusted_document(source, result.field_key, q.document) for q in result.evidence):
        return None
    ids, dropped = source.resolve(result.segment_ids)
    if dropped or ids != result.segment_ids:
        return None
    cut = source.evidence(ids)
    if len(cut) != len(result.evidence) or not all(
        _place(a) == _place(b) and same_text(a.quote, b.quote)
        for a, b in zip(cut, result.evidence, strict=True)
    ):
        return None
    return set(ids)


def _place(quote: VerifiedQuote) -> tuple[str, str, int]:
    return quote.document, quote.document_sha256.lower(), quote.page


def pool(reports: Sequence[SelectionReport]) -> SelectionReport:
    """Several products as one report: means over all their present fields, counts summed."""
    return _summary(
        [field for report in reports for field in report.fields],
        state_agreement=(
            sum(r.state_agreement[0] for r in reports),
            sum(r.state_agreement[1] for r in reports),
        ),
        unmapped_golden_quotes=sum(r.unmapped_golden_quotes for r in reports),
        unmapped_predicted_quotes=sum(r.unmapped_predicted_quotes for r in reports),
        copy_credits=(
            sum(r.copy_credits[0] for r in reports),
            sum(r.copy_credits[1] for r in reports),
        ),
    )


def _summary(
    scored: Sequence[FieldSelection],
    *,
    state_agreement: tuple[int, int],
    unmapped_golden_quotes: int,
    unmapped_predicted_quotes: int,
    copy_credits: tuple[int, int],
) -> SelectionReport:
    recalls = [f.recall for f in scored if f.recall is not None]
    precisions = [f.precision for f in scored if f.precision is not None]
    return SelectionReport(
        fields=tuple(scored),
        recall_mean=fmean(recalls) if recalls else None,
        precision_mean=fmean(precisions) if precisions else None,
        complete_at_08=sum(1 for value in recalls if value >= COMPLETE_RECALL),
        state_agreement=state_agreement,
        unmapped_golden_quotes=unmapped_golden_quotes,
        unmapped_predicted_quotes=unmapped_predicted_quotes,
        copy_credits=copy_credits,
    )


def _line(label: str, report: SelectionReport, tag: str = "legacy") -> str:
    def mean(value: float | None) -> str:
        return "-" if value is None else f"{value:.3f}"

    scored = sum(1 for f in report.fields if f.recall is not None)
    agree, total = report.state_agreement
    return (
        f"{label}: [{tag}] recall {mean(report.recall_mean)} "
        f"precision {mean(report.precision_mean)} "
        f"recall>=0.8 {report.complete_at_08}/{scored} states {agree}/{total} "
        f"unmapped golden {report.unmapped_golden_quotes} predicted "
        f"{report.unmapped_predicted_quotes} copy credits {report.copy_credits[0]}/"
        f"{report.copy_credits[1]}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[4])
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--products", nargs="+", required=True)
    parser.add_argument("--legacy", action="store_true", help="score without the S12a rules")
    args = parser.parse_args(argv)
    rules = None if args.legacy else load_scoring_rules()
    tag = "legacy" if rules is None else f"rules {rules.version}"
    reports = []
    for product in args.products:
        check_product_id(product)
        output = CompileOutput.model_validate_json(
            (args.run_root / product / "output.json").read_text(encoding="utf-8")
        )
        pages = trusted_source_pages(source_directory(args.repo, product))
        source = SegmentedSource(pages.evidence, table_headers=pages.table_headers)
        golden = load_golden_v2(args.repo / GOLDEN_DIR / f"{product}.json")
        reports.append(score_selection(source, golden, output.fields, rules=rules))
        print(_line(product, reports[-1], tag))
    print(_line("pooled", pool(reports), tag))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
