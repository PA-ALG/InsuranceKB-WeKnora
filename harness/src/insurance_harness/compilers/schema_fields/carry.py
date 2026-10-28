"""Reviewed evidence a recompile hands to step two (S12c-4 Spec §2).

Step one is not deterministic: a recompile can miss a segment that the published, reviewed value
cites, and step two then writes a value without that content (#404). A recompile therefore carries
the quotes of this product's published present claims, but only when every quote cites a material
of this compile with the same knowledge, parse attempt and file fingerprint. Only quotes travel,
never the old value; the engine locates them in this compile's segments and step two decides.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import ValidationError

from insurance_harness.bundle.client import PlatformClient, Release
from insurance_harness.contracts.enums import ClaimState, LocatorKind
from insurance_harness.contracts.knowledge import Claim
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.source_ref import SourceRevision
from insurance_harness.ingest.source_map import API_KEY_ENV, BASE_URL_ENV

_SOURCE_REF = re.compile(r"source:v1:([^:\s]+):([1-9][0-9]*):([a-fA-F0-9]{64})")


@dataclass(frozen=True)
class CarriedQuote:
    """One reviewed quote, addressed in this compile's terms (document name and page)."""

    document: str
    page: int
    quote: str


@dataclass(frozen=True)
class Carry:
    """What one product's recompile carries, by field key, and the release it came from."""

    release_id: str
    quotes: Mapping[str, tuple[CarriedQuote, ...]] = field(default_factory=dict)

    @property
    def digest(self) -> str | None:
        """Identity of the carried input; None when nothing is carried (S12c-4 Spec §2.4)."""
        if not self.quotes:
            return None
        canonical = json.dumps(
            {key: [[q.document, q.page, q.quote] for q in quotes]
             for key, quotes in sorted(self.quotes.items())},
            ensure_ascii=False, separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CarryRequest:
    """A compile asked to carry reviewed evidence from this Active release (None: none yet)."""

    release: Release | None


def active_carry(space_id: str) -> CarryRequest:
    """Read the Space's Active release once through the existing read route."""
    client = PlatformClient(os.environ[BASE_URL_ENV], os.environ[API_KEY_ENV])
    return CarryRequest(client.active(space_id))


def carry_for(
    request: CarryRequest,
    entity_id: str,
    revisions: Mapping[str, SourceRevision] | None,
    pages: Sequence[PageText],
    headers: Mapping[str, Sequence[PageText]] | None,
) -> Carry | None:
    """The quotes this product's recompile may carry, or None when there is no Active release."""
    if revisions is None:
        raise ValueError("carrying reviewed evidence needs fixed source revisions")
    if request.release is None:
        return None
    documents: dict[tuple[str, int, str], str] = {}
    for page in [*pages, *(page for group in (headers or {}).values() for page in group)]:
        revision = revisions.get(page.document)
        if revision is not None:
            identity = (revision.knowledge_id, revision.parse_attempt, page.document_sha256.lower())
            documents[identity] = page.document
    quotes: dict[str, tuple[CarriedQuote, ...]] = {}
    for member in request.release.members:
        if member.kind != "claim" or not isinstance(member.payload, dict):
            continue
        if member.payload.get("subject_ref") != entity_id:
            continue
        try:
            claim = Claim.model_validate(member.payload)
        except ValidationError:
            continue  # an older contract cannot be read reliably: carry nothing for it
        carried = _carried(claim, documents)
        if carried and claim.predicate not in quotes:
            quotes[claim.predicate] = carried
    return Carry(request.release.id, quotes)


def _carried(
    claim: Claim, documents: Mapping[tuple[str, int, str], str],
) -> tuple[CarriedQuote, ...]:
    """All of a present claim's quotes, or nothing when any one is not a quote of this compile."""
    if claim.state != ClaimState.PRESENT or not claim.evidence:
        return ()
    out: list[CarriedQuote] = []
    for evidence in claim.evidence:
        found = _SOURCE_REF.fullmatch(evidence.source_ref)
        if (
            evidence.locator.kind != LocatorKind.PDF_TEXT_SPAN
            or evidence.locator.page is None
            or found is None
            or found[3].lower() != evidence.file_sha256.lower()
        ):
            return ()
        document = documents.get((found[1], int(found[2]), found[3].lower()))
        if document is None:
            return ()
        out.append(CarriedQuote(document, evidence.locator.page, evidence.quote))
    return tuple(out)
