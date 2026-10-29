"""Reviewed evidence a recompile hands to step two (S12c-4 Spec §2).

Step one is not deterministic: a recompile can miss a segment that the published, reviewed value
cites, and step two then writes a value without that content (#404). A recompile therefore carries
the quotes of this product's published present claims, but only when every quote cites a material
of this compile with the same knowledge, parse attempt and file fingerprint. The engine locates the
quotes in this compile's segments and step two decides. Since S12c-8 the reviewed value of such a
field travels too, as a reference step two may only keep where its segments still support it.
Quotes name the material they cite, so publication planning, which knows only registered
materials, computes the same carry as the compile that later reads the pages.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError

from insurance_harness.bundle.client import PlatformClient, Release
from insurance_harness.contracts.enums import ClaimState, LocatorKind
from insurance_harness.contracts.knowledge import Claim
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV

_SOURCE_REF = re.compile(r"source:v1:([^:\s]+):([1-9][0-9]*):([a-fA-F0-9]{64})")


@dataclass(frozen=True, order=True)
class ReviewedQuote:
    """One reviewed quote: the material it cites (``knowledge:attempt:sha``), page and text."""

    material: str
    page: int
    quote: str


@dataclass(frozen=True)
class CarriedQuote:
    """One reviewed quote, addressed in this compile's terms (document name and page)."""

    document: str
    page: int
    quote: str


@dataclass(frozen=True)
class Carry:
    """What one product's recompile carries, by field key, and the release it came from.

    ``values`` are the published, reviewed values of the fields whose quotes are carried (S12c-8):
    step two sees them as a reference so a recompile does not drop facts its segments still support.
    """

    release_id: str
    quotes: Mapping[str, tuple[ReviewedQuote, ...]] = field(default_factory=dict)
    values: Mapping[str, str] = field(default_factory=dict)

    @property
    def digest(self) -> str | None:
        """Identity of the carried input; None when nothing is carried (S12c-4 Spec §2.4)."""
        if not self.quotes:
            return None
        carried: dict[str, object] = {
            key: [[q.material, q.page, q.quote] for q in quotes]
            for key, quotes in sorted(self.quotes.items())
        }
        if self.values:
            # S12c-8: the reviewed values are carried input too; without them the digest is
            # the S12c-4 one, so a quotes-only carry keeps its identity.
            carried = {"quotes": carried, "values": dict(sorted(self.values.items()))}
        canonical = json.dumps(carried, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CarryRequest:
    """A compile asked to carry reviewed evidence from this Active release (None: none yet)."""

    release: Release | None


def active_carry(space_id: str) -> CarryRequest:
    """Read the Space's Active release once through the existing read route."""
    client = PlatformClient(os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV])
    return CarryRequest(client.active(space_id))


def carry_for(release: Release | None, entity_id: str, materials: Collection[str]) -> Carry | None:
    """The quotes this product's recompile may carry, or None when there is no Active release.

    ``materials`` are the compile's identities as ``CompileOutput.materials`` names them. The
    claims of one field carry the union of their quotes: by logical key, each claim's quotes in
    order, a repeated quote once, so the Active's member order never changes the carry (§2.1).
    """
    if release is None:
        return None
    current = set(materials)
    claims: dict[str, list[tuple[str, tuple[ReviewedQuote, ...]]]] = {}
    texts: dict[str, list[tuple[str, str]]] = {}
    for member in release.members:
        if member.kind != "claim" or not isinstance(member.payload, dict):
            continue
        if member.payload.get("subject_ref") != entity_id:
            continue
        try:
            claim = Claim.model_validate(member.payload)
        except ValidationError:
            continue  # an older contract cannot be read reliably: carry nothing for it
        carried = _carried(claim, current)
        if carried:
            claims.setdefault(claim.predicate, []).append((claim.logical_key, carried))
            texts.setdefault(claim.predicate, []).append((claim.logical_key, _text(claim.value)))
    quotes = {
        key: tuple(dict.fromkeys(quote for _, carried in sorted(found) for quote in carried))
        for key, found in claims.items()
    }
    values = {
        key: "\n".join(text for _, text in sorted(found))
        for key, found in texts.items()
        if all(text for _, text in found)
    }
    return Carry(release.id, quotes, values)


def _text(value: object) -> str:
    """A present claim's value as step two reads it: the text itself, or canonical JSON."""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def located(
    carry: Carry,
    revisions: Mapping[str, SourceRevision],
    pages: Sequence[PageText],
    headers: Mapping[str, Sequence[PageText]] | None,
) -> dict[str, tuple[CarriedQuote, ...]]:
    """The carried quotes by this compile's document names, which the engine locates."""
    documents: dict[str, str] = {}
    for page in [*pages, *(page for group in (headers or {}).values() for page in group)]:
        revision = revisions.get(page.document)
        if revision is not None:
            material = (f"{revision.knowledge_id}:{revision.parse_attempt}:"
                        f"{page.document_sha256.lower()}")
            documents[material] = page.document
    # carry_for kept only quotes of this compile's materials, so every one has a document.
    return {
        key: tuple(CarriedQuote(documents[q.material], q.page, q.quote) for q in quotes)
        for key, quotes in carry.quotes.items()
    }


def _carried(claim: Claim, materials: Collection[str]) -> tuple[ReviewedQuote, ...]:
    """All of a present claim's quotes, or nothing when any one is not a quote of this compile."""
    if claim.state != ClaimState.PRESENT or not claim.evidence:
        return ()
    out: list[ReviewedQuote] = []
    for evidence in claim.evidence:
        found = _SOURCE_REF.fullmatch(evidence.source_ref)
        if (
            evidence.locator.kind != LocatorKind.PDF_TEXT_SPAN
            or evidence.locator.page is None
            or found is None
            or found[3].lower() != evidence.file_sha256.lower()
        ):
            return ()
        material = f"{found[1]}:{int(found[2])}:{found[3].lower()}"
        if material not in materials:
            return ()
        out.append(ReviewedQuote(material, evidence.locator.page, evidence.quote))
    return tuple(out)
