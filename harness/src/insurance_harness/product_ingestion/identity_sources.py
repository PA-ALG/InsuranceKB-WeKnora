"""Identity-only physical page offers; canonical source blocks remain immutable.

G3 native page projections describe one physical page and cannot stand in for a
cross-page source view. This module owns that distinction and its locator custody.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from insurance_harness.knowledge_compiler.batch_entity_resolution_830_g3 import (
    BatchCorpusV1,
    MaterialProposalV1,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import Evidence, SourceBlock
from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    G3SemanticLocatorV1,
    _c_eligible_source_locators,
    _c_locator_ref,
    _c_source_locators,
)
from insurance_harness.knowledge_compiler.semantic_proposals import (
    assemble_source_proposals,
    resolve_source_references,
)
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot
from insurance_harness.product_ingestion.source_geometry import (
    prepare_evidence_locations,
    project_evidence_locations,
    project_native_pages,
)

_LEGAL_COMPANY = re.compile(r"[\u4e00-\u9fff]{2,40}保险(?:股份有限公司|有限责任公司|有限公司)")


@dataclass(frozen=True)
class IdentitySourcePageView:
    material_id: str
    source: SourceBlock
    actual_page_number: int
    source_range: tuple[int, int]
    opaque_block_ref: str


@dataclass(frozen=True)
class IdentityLocatorOffer:
    material_id: str
    locator: G3SemanticLocatorV1
    evidence: Evidence
    actual_page_number: int


@dataclass(frozen=True)
class PreparedIdentitySources:
    corpus: BatchCorpusV1
    context_bytes: bytes
    offers: tuple[IdentityLocatorOffer, ...]
    allowed_material_roles: tuple[str, ...]
    allowed_taxonomy_labels: tuple[str, ...]

    @property
    def context(self) -> dict[str, Any]:
        # Callers can add routing metadata without mutating the frozen offer set.
        return cast(dict[str, Any], json.loads(self.context_bytes))


def _evidence(source: SourceBlock, locator: G3SemanticLocatorV1) -> Evidence:
    return Evidence(
        **source.model_dump(exclude={"text"}),
        start=locator.start,
        end=locator.end,
        quote=locator.quote,
        quote_hash=hashlib.sha256(locator.quote.encode()).hexdigest(),
    )


def _extra_view(decoded: DecodedSourceSnapshot, material_id: str) -> IdentitySourcePageView | None:
    sources = {s.block_id: s for s in decoded.blocks}
    candidates: list[tuple[tuple[int, int, str], IdentitySourcePageView]] = []
    for mapping in decoded.snapshot["chunk_page_mappings"]:
        source = sources.get(mapping["chunk_id"])
        if source is None:
            continue
        for span in mapping["page_spans"]:
            number = span["page_number"]
            if not 1 < number <= 3 or number == source.page_number:
                continue
            start, end = span["block_codepoint_start"], span["block_codepoint_end"]
            match = _LEGAL_COMPANY.search(source.text[start:end])
            if match is None:
                continue
            identity = {
                "material_id": material_id,
                "revision_id": source.revision_id,
                "block_id": source.block_id,
                "actual_page_number": number,
                "source_range": [start, end],
            }
            ref = hashlib.sha256(
                b"identity-source-view.830.v1\0"
                + json.dumps(
                    identity,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            candidates.append(
                (
                    (number, span["global_codepoint_start"] + match.start(), source.block_id),
                    IdentitySourcePageView(material_id, source, number, (start, end), ref),
                )
            )
    return min(candidates, key=lambda row: row[0])[1] if candidates else None


def prepare_identity_sources(
    corpus: BatchCorpusV1,
    snapshots: Mapping[str, DecodedSourceSnapshot],
    *,
    allowed_material_roles: tuple[str, ...],
    allowed_taxonomy_labels: tuple[str, ...],
    **routing_options: Any,
) -> PreparedIdentitySources:
    from insurance_harness.product_ingestion.identity import (
        build_identity_context,
        select_identity_block_ids,
    )

    expected_scope = {
        name: getattr(corpus, name)
        for name in (
            "tenant_id",
            "space_id",
            "raw_kb_id",
            "wiki_kb_id",
        )
    }
    if set(snapshots) != {entry.material_id for entry in corpus.entries}:
        raise ValueError("identity source custody material set mismatch")
    for entry in corpus.entries:
        decoded = snapshots[entry.material_id]
        body = decoded.snapshot
        if (
            body["scope"] != expected_scope
            or body["receipt"]["knowledge_id"] != entry.material_id
            or type(entry.receipt).model_validate(body["receipt"]) != entry.receipt
            or body["native_capture_sha256"] != entry.native_capture_sha256
            or body["parser_identity_sha256"] != entry.parser_identity_sha256
            or body["snapshot_sha256"] != entry.provenance.acquisition_receipt_sha256
            or hashlib.sha256(decoded.native_bytes).hexdigest() != entry.native_capture_sha256
            or entry.blocks
            != tuple(sorted(decoded.blocks, key=lambda row: (row.revision_id, row.block_id)))
        ):
            raise ValueError("identity source custody mismatch")

    pages = tuple(
        page
        for material_id, decoded in sorted(snapshots.items())
        for page in project_native_pages(
            decoded,
            material_id=material_id,
            selected_block_ids=select_identity_block_ids(decoded),
        )
    )
    context = build_identity_context(
        corpus,
        pages,
        snapshots=snapshots,
        allowed_material_roles=allowed_material_roles,
        allowed_taxonomy_labels=allowed_taxonomy_labels,
        **routing_options,
    )
    page_by_ref = {page.block_ref: page for page in pages}
    offers: list[IdentityLocatorOffer] = []
    seen_blocks: set[str] = set()
    seen_locators: set[str] = set()
    for entry, material in zip(corpus.entries, context["materials"], strict=True):
        material_id = entry.material_id
        decoded = snapshots[material_id]
        if material["material_id"] != material_id or entry.blocks != tuple(
            sorted(decoded.blocks, key=lambda row: (row.revision_id, row.block_id))
        ):
            raise ValueError("identity view corpus source mismatch")
        sources = {(s.revision_id, s.block_id): s for s in entry.blocks}
        extra = None
        if not any(_LEGAL_COMPANY.search(block["text"]) for block in material["blocks"]):
            extra = _extra_view(decoded, material_id)
        blocks = material["blocks"]
        candidates: list[tuple[dict[str, Any], SourceBlock, tuple[G3SemanticLocatorV1, ...]]] = []
        for block in blocks:
            page = page_by_ref[block["block_ref"]]
            source = sources[(page.revision_id, page.block_id)]
            offered = {row["locator_ref"] for row in block["evidence_locator_refs"]}
            locators = tuple(
                loc
                for loc in _c_eligible_source_locators(page, source)
                if _c_locator_ref(loc) in offered
            )
            candidates.append((block, source, locators))
        if extra is not None:
            # Replace a generic auxiliary company mention; the bounded contract
            # permits all page-one fragments and just one later issuer fragment.
            candidates = [row for row in candidates if row[0]["page_number"] == 1]
            start, end = extra.source_range
            locators = tuple(
                loc.model_copy(update={"start": loc.start + start, "end": loc.end + start})
                for loc in _c_source_locators(extra.opaque_block_ref, extra.source.text[start:end])
            )
            block = {
                "block_ref": extra.opaque_block_ref,
                "text": extra.source.text[start:end],
                "source_ranges": [[start, end]],
                "page_number": extra.actual_page_number,
                "evidence_locator_refs": [],
            }
            candidates.append((block, extra.source, locators))
            context["contract"] = "product-identity-source-context.830.v3"
        all_evidence = tuple(
            _evidence(source, loc) for _, source, locs in candidates for loc in locs
        )
        index = prepare_evidence_locations(decoded, all_evidence)
        for block, source, locators in candidates:
            if block["block_ref"] in seen_blocks:
                raise ValueError("duplicate identity block ref")
            seen_blocks.add(block["block_ref"])
            accepted = []
            for locator in locators:
                evidence = _evidence(source, locator)
                pieces, audit = project_evidence_locations(evidence, decoded, page_index=index)
                if pieces != (evidence,) or [r["actual_page_number"] for r in audit["parts"]] != [
                    block["page_number"]
                ]:
                    raise ValueError("identity locator physical page mismatch")
                ref = _c_locator_ref(locator)
                if ref in seen_locators:
                    raise ValueError("duplicate identity locator ref")
                seen_locators.add(ref)
                offers.append(
                    IdentityLocatorOffer(material_id, locator, evidence, block["page_number"])
                )
                accepted.append({"locator_ref": ref, "quote": locator.quote})
            block["evidence_locator_refs"] = accepted
        material["blocks"] = [row[0] for row in candidates]
    return PreparedIdentitySources(
        corpus,
        json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(),
        tuple(offers),
        allowed_material_roles,
        allowed_taxonomy_labels,
    )


def assemble_identity_response(
    raw: bytes,
    prepared: PreparedIdentitySources,
    *,
    model_request_sha256: str,
) -> tuple[MaterialProposalV1, ...]:
    from insurance_harness.product_ingestion.identity import validate_identity_offered_response

    validate_identity_offered_response(raw, prepared.context)
    catalog: dict[tuple[str, str], G3SemanticLocatorV1] = {}
    evidence_by_locator: dict[tuple[str, str], IdentityLocatorOffer] = {}
    for offer in prepared.offers:
        key = (offer.material_id, _c_locator_ref(offer.locator))
        if key in catalog:
            raise ValueError("duplicate identity locator ref")
        catalog[key] = offer.locator
        evidence_by_locator[key] = offer
    requested = tuple(entry.material_id for entry in prepared.corpus.entries)
    response = resolve_source_references(raw, requested_material_ids=requested, locators=catalog)

    def resolve(material_id: str, locator: G3SemanticLocatorV1) -> Evidence:
        offer = evidence_by_locator.get((material_id, _c_locator_ref(locator)))
        if offer is None or offer.locator != locator:
            raise ValueError("unknown or foreign identity locator")
        return offer.evidence

    return assemble_source_proposals(
        response=response,
        corpus=prepared.corpus,
        requested_material_ids=requested,
        allowed_material_roles=prepared.allowed_material_roles,
        allowed_taxonomy_labels=prepared.allowed_taxonomy_labels,
        model_request_sha256=model_request_sha256,
        resolve_evidence=resolve,
    )
