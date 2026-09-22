"""Bounded, read-only verification of the just-published product and its evidence."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Sequence
from typing import Any, cast
from urllib.parse import urlencode

from insurance_harness.jobs import NonRetryableJobError
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCandidateBundle830G3V1,
    EntityCompileBinding830G3V1,
    _batch_sha256,
    _without_hash,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileRequest, PageMember
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    Evidence,
    FieldAssertion,
    SourceBlock,
    SourceIdentity,
    verify_evidence,
)
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.platform_client import PlatformClient, _id
from insurance_harness.product_ingestion.signing import canonical


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise NonRetryableJobError(code)


def _equal(left: object, right: object) -> bool:
    # JSON booleans must not compare equal to integer scope/locator identities.
    return canonical(left) == canonical(right)


def _citation_id(candidate_hash: str, member_id: str, evidence: Evidence) -> str:
    # Existing Go concept citation preimage, including every exact location.
    return (
        "citation-"
        + hashlib.sha256(
            canonical(
                [
                    candidate_hash,
                    member_id,
                    evidence.revision_id,
                    evidence.block_id,
                    evidence.page_number,
                    evidence.start,
                    evidence.end,
                    evidence.quote_hash,
                ]
            )
        ).hexdigest()[:24]
    )


def _preview_matches(
    authority: dict[str, Any],
    *,
    scope_wire: dict[str, str | int],
    release_id: str,
    epoch: int,
    candidate_hash: str,
    member_id: str,
    citation_id: str,
    evidence: Evidence,
    source: SourceBlock,
) -> None:
    expected = {
        "release_id": release_id,
        "activation_epoch": epoch,
        "candidate_hash": candidate_hash,
        "member_id": member_id,
        "citation_id": citation_id,
        "scope": scope_wire,
        "source": {k: getattr(evidence, k) for k in SourceIdentity.model_fields},
        "block_id": evidence.block_id,
        "page_number": evidence.page_number,
        "quote_hash": evidence.quote_hash,
    }
    _require(
        all(_equal(authority.get(k), v) for k, v in expected.items()), "VERIFY_CITATION_IDENTITY"
    )
    _require(
        isinstance(authority.get("opaque_token"), str) and bool(authority["opaque_token"]),
        "VERIFY_CITATION_UNAVAILABLE",
    )
    _require(
        type(authority.get("expires_at_unix")) is int
        and authority["expires_at_unix"] > time.time(),
        "VERIFY_CITATION_EXPIRED",
    )
    revision = authority.get("revision_source", {})
    pages = revision.get("page_count")
    _require(
        type(pages) is int and pages > 0 and revision.get("file_sha256") == evidence.source_hash,
        "VERIFY_CITATION_SOURCE",
    )
    bbox = authority.get("bbox", {})
    _require(
        bbox.get("coordinate_space") == "normalized_0_1e6_top_left"
        and all(type(bbox.get(k)) is int for k in ("x0", "y0", "x1", "y1"))
        and 0 <= bbox["x0"] < bbox["x1"] <= 1_000_000
        and 0 <= bbox["y0"] < bbox["y1"] <= 1_000_000,
        "VERIFY_CITATION_GEOMETRY",
    )
    locator = authority.get("source_locator")
    if locator is None:
        # The existing G2 authority proves a unique quote on its actual page.
        # Do not invent a block/global offset for this legitimate older path.
        _require(
            authority.get("contract") == "concept-citation-content-authority.830.g2.v1"
            and 0 < evidence.page_number <= pages,
            "VERIFY_CITATION_LOCATOR",
        )
        return
    expected_locator = {
        "contract": "concept-source-block-locator.830.g3.v1",
        "source_block_sha256": hashlib.sha256(source.text.encode()).hexdigest(),
        "source_page_number": evidence.page_number,
        "start": evidence.start,
        "end": evidence.end,
    }
    _require(
        authority.get("contract") == "concept-citation-content-authority.830.g3.v1"
        and all(_equal(locator.get(k), v) for k, v in expected_locator.items()),
        "VERIFY_CITATION_LOCATOR",
    )
    _require(
        all(
            type(locator.get(k)) is int
            for k in ("block_global_start", "global_start", "global_end", "actual_page_number")
        )
        and locator["block_global_start"] >= 0
        and locator["global_start"] == locator["block_global_start"] + evidence.start
        and locator["global_end"] == locator["block_global_start"] + evidence.end
        and 0 < locator["actual_page_number"] <= pages,
        "VERIFY_CITATION_LOCATOR",
    )


async def verify_published_product(
    *,
    platform: PlatformClient,
    scope: ProductScope,
    receipt: dict[str, Any],
    candidate: BatchConceptCandidateBundle830G3V1,
    current_entity_ids: Sequence[str],
) -> dict[str, Any]:
    """Return a durable PASS report only after exact scoped platform reads.

    Transport failures retain the client's typed retry classification. Other
    mismatches fail the verification job without changing its activation receipt.
    No model calls, mutations, token persistence, or historical-entity traversal.
    """
    try:
        return await _verify(platform, scope, receipt, candidate, current_entity_ids)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise NonRetryableJobError("VERIFY_RESPONSE_INVALID") from None


def _prepare_verification(
    platform: PlatformClient,
    scope: ProductScope,
    receipt: dict[str, Any],
    candidate: BatchConceptCandidateBundle830G3V1,
    current_entity_ids: Sequence[str],
) -> tuple[
    CompileRequest,
    dict[str, str | int],
    str,
    int,
    tuple[str, ...],
    dict[str, EntityCompileBinding830G3V1],
    list[PageMember],
    dict[str, FieldAssertion],
    dict[tuple[str, str], SourceBlock],
]:
    _require(isinstance(candidate, BatchConceptCandidateBundle830G3V1), "VERIFY_CANDIDATE_INVALID")
    base = candidate.request.base_request
    scope_wire: dict[str, str | int] = {
        "tenant_id": int(scope.tenant_id),
        "space_id": scope.space_id,
        "raw_kb_id": scope.raw_knowledge_base_id,
        "wiki_kb_id": scope.wiki_knowledge_base_id,
    }
    _require(
        platform.scope == scope
        and all(
            _equal(getattr(base, k), v) and _equal(receipt.get(k), v) for k, v in scope_wire.items()
        ),
        "VERIFY_SCOPE_MISMATCH",
    )
    release_id = _id(receipt["release_id"])
    epoch = receipt.get("activation_epoch")
    _require(type(epoch) is int and epoch > 0, "VERIFY_RECEIPT_INVALID")
    _require(not isinstance(current_entity_ids, str), "VERIFY_ENTITY_SCOPE_INVALID")
    entities = tuple(sorted(set(current_entity_ids)))
    bindings = {b.entity_id: b for b in candidate.request.entity_bindings}
    _require(bool(entities) and all(e in bindings for e in entities), "VERIFY_ENTITY_SCOPE_INVALID")
    members = [
        m
        for m in candidate.page_manifest.members
        if m.owner_id in entities and m.kind in {"entity_overview", "field_assertion"}
    ]
    fields = {}
    sources = {(s.revision_id, s.block_id): s for s in base.sources}
    for member in members:
        if member.kind != "field_assertion":
            continue
        field = FieldAssertion.model_validate(member.payload)
        _require(
            field.entity_id == member.owner_id and field.space_id == base.space_id,
            "VERIFY_FIELD_SCOPE",
        )
        for evidence in field.evidence:
            try:
                verify_evidence(evidence, base.sources)
            except ValueError:
                raise NonRetryableJobError("VERIFY_SOURCE_MISMATCH") from None
        fields[member.member_id] = field
    # Check immutable typed custody without re-projecting/replaying old models.
    _require(
        candidate.candidate_hash
        == _batch_sha256(candidate.contract, _without_hash(candidate, "candidate_hash")),
        "VERIFY_CANDIDATE_IDENTITY",
    )
    return (
        base,
        scope_wire,
        release_id,
        cast(int, epoch),
        entities,
        bindings,
        members,
        fields,
        sources,
    )


async def _verify(
    platform: PlatformClient,
    scope: ProductScope,
    receipt: dict[str, Any],
    candidate: BatchConceptCandidateBundle830G3V1,
    current_entity_ids: Sequence[str],
) -> dict[str, Any]:
    # Hashing the complete parent and checking current evidence can be substantial;
    # keep the worker's event loop available for durable lease heartbeats.
    (
        base,
        scope_wire,
        release_id,
        epoch,
        entities,
        bindings,
        members,
        fields,
        sources,
    ) = await asyncio.to_thread(
        _prepare_verification, platform, scope, receipt, candidate, current_entity_ids
    )
    expected_current = {"release_id": release_id, "activation_epoch": epoch}
    _require(
        _equal(await platform.current(scope), expected_current), "VERIFY_CURRENT_RELEASE_MISMATCH"
    )
    for entity_id in entities:
        overview = [m for m in members if m.kind == "entity_overview" and m.owner_id == entity_id]
        _require(len(overview) == 1, "VERIFY_ENTITY_OVERVIEW_INVALID")
        query = urlencode({"q": bindings[entity_id].display_name})
        hits = await platform._request(
            scope, "GET", f"/releases/{release_id}/search?{query}", expected_data_type=list
        )
        if hits is None:
            raise NonRetryableJobError("VERIFY_RESPONSE_INVALID")
        _require(
            any(
                isinstance(hit, dict)
                and hit.get("logical_slug") == overview[0].member_id
                and hit.get("kind") == "entity_overview"
                and hit.get("revision_id") == candidate.candidate_hash
                and _equal(hit.get("payload"), overview[0].payload)
                for hit in hits
            ),
            "VERIFY_SEARCH_MISSING",
        )
    citations_checked = 0
    for member in members:
        suffix = f"/schema/concept-pages/{_id(member.member_id)}"
        read = await platform._request(
            scope, "GET", suffix + "?" + urlencode({"release_id": release_id})
        )
        expected = {
            "contract": "concept-page-read.830.g2.v1",
            "read_mode": "pinned",
            "release_id": release_id,
            "activation_epoch": epoch,
            "candidate_hash": candidate.candidate_hash,
            "space_id": base.space_id,
            "raw_kb_id": base.raw_kb_id,
            "wiki_kb_id": base.wiki_kb_id,
            "member": member.model_dump(mode="json"),
        }
        _require(all(_equal(read.get(k), v) for k, v in expected.items()), "VERIFY_PAGE_MISMATCH")
        if member.kind != "field_assertion":
            continue
        field = fields[member.member_id]
        # Exact duplicate evidence shares one citation; distinct offsets never do.
        evidence_by_id = {
            _citation_id(candidate.candidate_hash, member.member_id, e): e for e in field.evidence
        }
        expected_citations: list[dict[str, Any]] = [
            {
                "citation_id": _citation_id(candidate.candidate_hash, member.member_id, e),
                "page_number": e.page_number,
                "quote": e.quote,
            }
            for e in evidence_by_id.values()
        ]
        citations = read.get("citations")
        _require(
            isinstance(citations, list)
            and _equal(
                sorted(citations, key=lambda c: c["citation_id"]),
                sorted(expected_citations, key=lambda c: c["citation_id"]),
            ),
            "VERIFY_CITATION_COVERAGE",
        )
        for cid, evidence in sorted(evidence_by_id.items()):
            authority = await platform._request(
                scope,
                "GET",
                suffix + f"/citations/{_id(cid)}/preview?" + urlencode({"release_id": release_id}),
            )
            _preview_matches(
                authority,
                scope_wire=scope_wire,
                release_id=release_id,
                epoch=epoch,
                candidate_hash=candidate.candidate_hash,
                member_id=member.member_id,
                citation_id=cid,
                evidence=evidence,
                source=sources[evidence.revision_id, evidence.block_id],
            )
            citations_checked += 1
    _require(
        _equal(await platform.current(scope), expected_current), "VERIFY_CURRENT_RELEASE_MISMATCH"
    )
    missing = sum(field.state == "unknown" for field in fields.values())
    return {
        "contract": "platform-published-product-verification.830.v1",
        "status": "PASS",
        **scope_wire,
        **expected_current,
        "candidate_hash": candidate.candidate_hash,
        "entity_ids": list(entities),
        "field_count": len(fields),
        "verified_field_count": len(fields) - missing,
        "missing_field_count": missing,
        "citation_count": citations_checked,
        "member_count": len(members),
        "search_count": len(entities),
    }
