"""Sales-method signals of one material, block by block (SK-1 Spec §3.2).

Independent of `role_of()`: a material's role is recognised from its name and opening as before;
method signals are looked for in every block of every page, with the S4d/S11c segmentation run on
this one material, so a block ID (`P<page>S<n>`) names the same text for the same source revision.
The decision is deterministic and the words are data (catalog/sales_taxonomy.json): a material is a
method material when its blocks show at least `min_signals` different signal words; its insurance
category is the machine's only when the taxonomy hits exactly one category, or only the general
words. Nothing here reads a platform or calls a model.
"""

import hashlib
import json
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.catalog.sales_taxonomy import SalesTaxonomy, fold, load_sales_taxonomy
from insurance_harness.evidence.quote_verification import PageTextLike
from insurance_harness.evidence.segments import SegmentedSource

BLOCK_SCHEME: Literal["segments.v1"] = "segments.v1"  # the segmentation that numbers blocks


class MethodHits(BaseModel):
    """What one material shows: the blocks and words that make it a method material."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    block_ids: tuple[str, ...] = Field(min_length=1)
    signals: tuple[str, ...] = Field(min_length=1)
    category_hits: tuple[str, ...]
    general_hit: bool
    taxonomy_version: str = Field(min_length=1)

    @property
    def evidence_digest(self) -> str:
        """The evidence a scope question is asked on; another digest is another question."""
        payload = {"scheme": BLOCK_SCHEME, **self.model_dump(mode="json")}
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def detect(
    pages: Sequence[PageTextLike], taxonomy: SalesTaxonomy | None = None
) -> MethodHits | None:
    """The method blocks of one material's pages, or None when it is no method material."""
    taxonomy = taxonomy or load_sales_taxonomy()
    if not pages:
        return None
    source = SegmentedSource(pages)
    prefix = next(iter(source.document_ids.values()))
    words = [(word, fold(word)) for word in taxonomy.method_signals]
    blocks: list[str] = []
    found: set[str] = set()
    for segment in source.segments:
        text = fold(segment.text)
        hit = {word for word, folded in words if folded in text}
        if hit:
            blocks.append(segment.id.removeprefix(prefix))
            found |= hit
    if len(found) < taxonomy.min_signals:
        return None
    whole = fold("".join(page.text for page in pages))
    categories = tuple(
        term.label
        for term in taxonomy.insurance_categories
        if any(fold(word) in whole for word in term.words)
    )
    return MethodHits(
        block_ids=tuple(dict.fromkeys(blocks)),
        signals=tuple(sorted(found)),
        category_hits=tuple(sorted(categories)),
        general_hit=any(fold(word) in whole for word in taxonomy.general.words),
        taxonomy_version=taxonomy.version,
    )


def machine_scope(
    hits: MethodHits, taxonomy: SalesTaxonomy | None = None
) -> tuple[str, ...] | None:
    """The labels the machine decides, or None when a person must choose (Spec §3.2)."""
    taxonomy = taxonomy or load_sales_taxonomy()
    if len(hits.category_hits) == 1 and not hits.general_hit:
        return hits.category_hits
    if not hits.category_hits and hits.general_hit:
        return (taxonomy.general.label,)
    return None
