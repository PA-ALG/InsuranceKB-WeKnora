"""Sales-method signals of one material, block by block (SK-1 Spec §3.2).

Independent of `role_of()`: a material's role is recognised from its name and opening as before;
method signals are looked for in every block of every page, with the S4d/S11c segmentation run on
this one material, so a block ID (`P<page>S<n>`) names the same text for the same source revision.
The decision is deterministic and the words are data (catalog/sales_taxonomy.json): a material is a
method material when its blocks show at least `min_signals` different signal words. Its scope labels
are every insurance category (and the general scope) whose words appear in any of its blocks, each
with the blocks and words that show it: applicability tags the machine assigns, not product facts.
Nothing here reads a platform or calls a model.
"""

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from insurance_harness.catalog.sales_taxonomy import SalesTaxonomy, fold, load_sales_taxonomy
from insurance_harness.evidence.quote_verification import PageTextLike
from insurance_harness.evidence.segments import SegmentedSource

BLOCK_SCHEME: Literal["segments.v1"] = "segments.v1"  # the segmentation that numbers blocks
Block = Annotated[str, StringConstraints(pattern=r"^P[1-9][0-9]*S[1-9][0-9]*$")]
Label = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]*(:[a-z][a-z_]*)?$")]


class LabelHit(BaseModel):
    """One scope label the taxonomy found, with its evidence: the blocks and the words."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    label: Label
    block_ids: tuple[Block, ...] = Field(min_length=1)
    words: tuple[str, ...] = Field(min_length=1)


class MethodHits(BaseModel):
    """What one material shows: the blocks and words that make it a method material."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    block_ids: tuple[str, ...] = Field(min_length=1)
    signals: tuple[str, ...] = Field(min_length=1)
    label_hits: tuple[LabelHit, ...]  # sorted by label
    taxonomy_version: str = Field(min_length=1)

    @property
    def labels(self) -> tuple[str, ...]:
        """The labels the machine assigns; empty when a person has to choose (Spec §3.2)."""
        return tuple(hit.label for hit in self.label_hits)

    @property
    def evidence_digest(self) -> str:
        """The evidence the labels are decided on; another digest is another question."""
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
    signals = [(word, fold(word)) for word in taxonomy.method_signals]
    terms = [
        (term.label, [(word, fold(word)) for word in term.words])
        for term in (*taxonomy.insurance_categories, taxonomy.general)
    ]
    blocks: list[str] = []
    found: set[str] = set()
    label_blocks: dict[str, list[str]] = defaultdict(list)
    label_words: dict[str, set[str]] = defaultdict(set)
    for segment in source.segments:
        text, block = fold(segment.text), segment.id.removeprefix(prefix)
        hit = {word for word, folded in signals if folded in text}
        if hit:
            blocks.append(block)
            found |= hit
        for label, words in terms:
            named = {word for word, folded in words if folded in text}
            if named:
                label_blocks[label].append(block)
                label_words[label] |= named
    if len(found) < taxonomy.min_signals:
        return None
    return MethodHits(
        block_ids=tuple(dict.fromkeys(blocks)),
        signals=tuple(sorted(found)),
        label_hits=tuple(
            LabelHit(
                label=label,
                block_ids=tuple(dict.fromkeys(label_blocks[label])),
                words=tuple(sorted(label_words[label])),
            )
            for label in sorted(label_blocks)
        ),
        taxonomy_version=taxonomy.version,
    )
