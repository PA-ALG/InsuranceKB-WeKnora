"""The changes of one compile that an independent judge decides (RV7 Spec §2.1, §2.3).

Claims are rebuilt exactly as publishing builds them and compared with the Active release by the
real change rules; only changes that would replace or add published content are judged. Each point
carries the content fingerprint the judge saw, so publishing can refuse a compile that changed
after judging.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from insurance_harness.bundle.client import Release
from insurance_harness.changes.decision import decide_changes
from insurance_harness.changes.options import registry_inputs
from insurance_harness.changes.sources import publication_entries
from insurance_harness.changes.types import ChangeSet, Verdict
from insurance_harness.compilers.schema_fields.claims import claims_from, require_cards_version
from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.contracts.knowledge import Claim
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.segments import SegmentedSource
from insurance_harness.ingest.source_map import PageReader, SourceEntry, load_trusted_pages

JUDGED = frozenset({Verdict.UPGRADE, Verdict.ADD, Verdict.FILL, Verdict.SUPERSEDE})


class JudgeBatchError(ValueError):
    """A batch step cannot continue; the code is stable and carries no input text."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Quote(_Strict):
    document: str
    page: int | None
    quote: str


class Shown(_Strict):
    """A value as the judge sees it."""

    state: str
    value: object = None
    evidence: list[Quote]


class ChangePoint(_Strict):
    slug: str
    field_key: str
    change: str
    live: Shown | None
    new: Shown
    content: str  # fingerprint of state, value and cited quotes


class ProductChanges(_Strict):
    product: str
    name: str
    pack: str
    space_id: str
    counts: dict[str, int]
    points: list[ChangePoint]


@dataclass(frozen=True)
class Rebuilt:
    """A product's compile rebuilt as publishing would, with its change set against Active."""

    output: CompileOutput
    name: str
    pack: str
    space_id: str
    entries: list[SourceEntry]
    changes: ChangeSet


def content_of(claim: Claim) -> str:
    """What the judge decided on: never review labels, timestamps or revision numbers."""
    quotes = sorted((item.source_ref, item.quote_sha256.lower()) for item in claim.evidence)
    return json.dumps([claim.state.value, claim.value, quotes], ensure_ascii=False, sort_keys=True)


def rebuild(
    product: str,
    *,
    registry: Path,
    compile_root: Path,
    reader: PageReader,
    active: Release | None,
) -> Rebuilt:
    try:
        output = CompileOutput.model_validate_json(
            (compile_root / product / "output.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, ValidationError):
        raise JudgeBatchError("OUTPUT_UNREADABLE") from None
    source_map, facts = registry_inputs(registry, [product])
    name, pack = facts[product]
    if output.entity_id != product or output.pack_id != pack:
        raise JudgeBatchError("OUTPUT_MISMATCH")
    require_cards_version(output)
    entries = publication_entries(source_map.products[product], output.materials)
    pages, sources = load_trusted_pages(reader, source_map.space_id, entries)
    incoming = claims_from(
        output, SegmentedSource(pages.evidence, table_headers=pages.table_headers), sources
    )
    changes = decide_changes(active, product, incoming, {entry.knowledge_id for entry in entries})
    return Rebuilt(output, name, pack, source_map.space_id, entries, changes)


def material_pages(
    reader: PageReader, space_id: str, entries: list[SourceEntry]
) -> dict[str, list[PageText]]:
    """Every page of every current material, keyed by knowledge id, for the judge to read."""
    return {
        entry.knowledge_id: reader.pages(space_id, entry.knowledge_id, entry.parse_attempt)
        for entry in entries
    }


def _shown(claim: Claim, documents: dict[str, str]) -> Shown:
    quotes = [
        Quote(
            document=documents.get(item.source_ref.split(":")[2], "unknown"),
            page=item.locator.page,
            quote=item.quote,
        )
        for item in claim.evidence
    ]
    return Shown(state=claim.state.value, value=claim.value, evidence=quotes)


def live_claim(active: Release | None, slug: str | None) -> Claim | None:
    if active is None or slug is None:
        return None
    for member in active.members:
        if member.logical_slug == slug and member.kind == "claim":
            try:
                return Claim.model_validate(member.payload)
            except ValidationError:
                raise JudgeBatchError("ACTIVE_CLAIM_INVALID") from None
    return None


def product_changes(
    rebuilt: Rebuilt, active: Release | None, pages: dict[str, list[PageText]]
) -> ProductChanges:
    documents = {kid: rows[0].document for kid, rows in pages.items() if rows}
    members = {claim.logical_key: claim for claim in rebuilt.changes.members}
    counts: dict[str, int] = {}
    points = []
    for item in rebuilt.changes.items:
        counts[item.verdict.value] = counts.get(item.verdict.value, 0) + 1
        if item.verdict not in JUDGED:
            continue
        new = members[item.logical_key]
        old = live_claim(active, item.base_slug) if item.verdict != Verdict.ADD else None
        points.append(
            ChangePoint(
                slug=item.logical_key,
                field_key=new.predicate,
                change=item.verdict.value,
                live=None if old is None else _shown(old, documents),
                new=_shown(new, documents),
                content=content_of(new),
            )
        )
    return ProductChanges(
        product=rebuilt.output.entity_id,
        name=rebuilt.name,
        pack=rebuilt.pack,
        space_id=rebuilt.space_id,
        counts=counts,
        points=points,
    )
