"""The changes of one compile that an independent judge decides (RV7 Spec §2.1, §2.3).

Claims are rebuilt exactly as publishing builds them and compared with the Active release by the
real change rules; only changes that would replace or add published content are judged. Each point
carries the content fingerprints of the new and the live value the judge saw, and each product the
identity of every input the judge relied on (its basis), so publishing can refuse anything that
changed after judging (review R4, R5). What a request shows about each field (its title,
definition, source guidance and card) is bound too, by digest, since a changed definition changes
the question the judge answered.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from insurance_harness.bundle.client import Release
from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.changes.decision import decide_changes
from insurance_harness.changes.options import registry_inputs
from insurance_harness.changes.sources import publication_entries
from insurance_harness.changes.types import ChangeSet, Verdict
from insurance_harness.compilers.schema_fields.cards import card_payload, cards_version
from insurance_harness.compilers.schema_fields.claims import claims_from, require_cards_version
from insurance_harness.compilers.schema_fields.definitions import pack_definitions
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
    file: str | None  # the session file holding the material's text
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
    live_content: str | None  # the same for the live value the judge compared against


class Material(_Strict):
    """One material of the product as the judge reads it; the file name is its identity."""

    knowledge_id: str
    attempt: int
    document: str
    sha256: str
    file: str


class ProductChanges(_Strict):
    product: str
    name: str
    pack: str
    space_id: str
    counts: dict[str, int]
    materials: list[Material]
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
    pages: dict[tuple[str, int], list[PageText]]
    basis: dict[str, Any]


class _Once:
    """Reads each source revision once, so the basis and the claims see the same pages."""

    def __init__(self, reader: PageReader) -> None:
        self._reader = reader
        self.read: dict[tuple[str, int], list[PageText]] = {}

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        key = (knowledge_id, attempt)
        if key not in self.read:
            self.read[key] = self._reader.pages(space_id, knowledge_id, attempt)
        return self.read[key]


def content_of(claim: Claim) -> str:
    """What the judge decided on: never review labels, timestamps or revision numbers."""
    quotes = sorted((item.source_ref, item.quote_sha256.lower()) for item in claim.evidence)
    return json.dumps([claim.state.value, claim.value, quotes], ensure_ascii=False, sort_keys=True)


def basis_of(output: CompileOutput, pages: dict[tuple[str, int], list[PageText]]) -> dict[str, Any]:
    """Every input the judge relied on: all registered materials, cited or not, and the versions
    of the compile and of the cards the judge was shown."""
    return {
        "materials": sorted(
            f"{kid}:{attempt}:{rows[0].document_sha256.lower() if rows else ''}"
            for (kid, attempt), rows in pages.items()
        ),
        "compiled_from": output.materials,
        "cards_version": output.cards_version,
        "value_protocol": output.value_protocol,
        "judge_cards": cards_version(),
    }


def field_context(repo: Path, pack: str, field_keys: Iterable[str]) -> dict[str, dict[str, Any]]:
    """What a request shows the judge about each field, read from the repo's pack catalog."""
    keys = sorted(set(field_keys))
    if not keys:
        return {}
    try:
        catalog = pack_definitions(repo / SCHEMA_PACK_CATALOG, pack, only_source_extractable=False)
    except (OSError, KeyError, ValueError):
        raise JudgeBatchError("PACK_UNKNOWN") from None
    definitions = {item.field_key: item for item in catalog}
    shown: dict[str, dict[str, Any]] = {}
    for key in keys:
        definition = definitions.get(key)
        if definition is None:
            raise JudgeBatchError("FIELD_UNKNOWN")
        shown[key] = {
            "title": definition.short_title,
            "description": definition.description,
            "source_guidance": definition.source_guidance,
            "card": card_payload(definition, examples=False),
        }
    return shown


def field_digests(contexts: dict[str, dict[str, Any]]) -> dict[str, str]:
    return {
        key: hashlib.sha256(
            json.dumps(context, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        for key, context in contexts.items()
    }


def check_fields(repo: Path, pack: str, bound: dict[str, str], field_keys: Iterable[str]) -> None:
    """Every field the approved points rely on is still shown as the judge saw it (review R4)."""
    try:
        now = field_digests(field_context(repo, pack, field_keys))
    except JudgeBatchError:
        raise JudgeBatchError("INPUTS_CHANGED") from None
    if any(bound.get(key) != digest for key, digest in now.items()):
        raise JudgeBatchError("INPUTS_CHANGED")


def rebuild(
    product: str,
    *,
    registry: Path,
    compile_root: Path,
    reader: PageReader,
    active: Release | None,
    basis: dict[str, Any] | None = None,
) -> Rebuilt:
    """Raises INPUTS_CHANGED before building claims when a given basis no longer holds."""
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
    once = _Once(reader)
    for entry in entries:
        once.pages(source_map.space_id, entry.knowledge_id, entry.parse_attempt)
    found = basis_of(output, once.read)
    if basis is not None and found != basis:
        raise JudgeBatchError("INPUTS_CHANGED")
    pages, sources = load_trusted_pages(once, source_map.space_id, entries)
    incoming = claims_from(
        output, SegmentedSource(pages.evidence, table_headers=pages.table_headers), sources
    )
    changes = decide_changes(active, product, incoming, {entry.knowledge_id for entry in entries})
    return Rebuilt(output, name, pack, source_map.space_id, entries, changes, once.read, found)


def materials_of(product: str, pages: dict[tuple[str, int], list[PageText]]) -> list[Material]:
    return [
        Material(
            knowledge_id=kid,
            attempt=attempt,
            document=rows[0].document if rows else "",
            sha256=rows[0].document_sha256.lower() if rows else "",
            file=f"sources/{product}/{kid}-{attempt}.txt",
        )
        for (kid, attempt), rows in sorted(pages.items())
    ]


def _material(source_ref: str, materials: list[Material]) -> Material | None:
    parts = source_ref.split(":")
    if len(parts) != 5 or not parts[3].isdigit():
        return None
    key = (parts[2], int(parts[3]))
    return next((m for m in materials if (m.knowledge_id, m.attempt) == key), None)


def _shown(claim: Claim, materials: list[Material]) -> Shown:
    quotes = []
    for item in claim.evidence:
        material = _material(item.source_ref, materials)
        quotes.append(
            Quote(
                document="unknown" if material is None else material.document,
                file=None if material is None else material.file,
                page=item.locator.page,
                quote=item.quote,
            )
        )
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


def product_changes(rebuilt: Rebuilt, active: Release | None) -> ProductChanges:
    materials = materials_of(rebuilt.output.entity_id, rebuilt.pages)
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
                live=None if old is None else _shown(old, materials),
                new=_shown(new, materials),
                content=content_of(new),
                live_content=None if old is None else content_of(old),
            )
        )
    return ProductChanges(
        product=rebuilt.output.entity_id,
        name=rebuilt.name,
        pack=rebuilt.pack,
        space_id=rebuilt.space_id,
        counts=counts,
        materials=materials,
        points=points,
    )
