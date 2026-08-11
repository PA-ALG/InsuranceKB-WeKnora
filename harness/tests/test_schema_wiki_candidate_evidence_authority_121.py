from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass
from decimal import Decimal

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    EvidenceLocatorSnapshotV1,
    FreeformDocumentBindingV1,
    FreeformEvidenceBindingReceiptV1,
    FreeformEvidenceV1,
    FreeformFieldOutputV1,
)
from insurance_harness.knowledge_compiler.schema_wiki_candidate_evidence_join_596_1 import (
    COORDINATE_POLICY_SHA256,
    CandidateEvidenceAuthorityError,
    LiveRevisionSourceReceiptV1,
    knowledge_revision_source_id,
    live_revision_source_receipt_sha256,
    normalize_mineru_bbox_596_1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    CitationBBoxV1,
    CitationTargetV1,
    schema_wiki_sha256,
)
from insurance_harness.knowledge_compiler.schema_wiki_release_596_1 import (
    build_schema_field_page_596_1,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _known_field() -> tuple[
    FreeformFieldOutputV1,
    FreeformEvidenceBindingReceiptV1,
]:
    field_id = "product_code"
    quote = "approved synthetic quote"
    content = f"prefix {quote} suffix"
    source_sha256 = "1" * 64
    parsed_document_sha256 = "2" * 64
    parse_manifest_sha256 = "3" * 64
    evidence = FreeformEvidenceV1(
        field_id=field_id,
        source_sha256=source_sha256,
        source_revision_id="revision-2",
        parse_attempt_id="attempt-2",
        parsed_document_hash=parsed_document_sha256,
        parse_manifest_hash=parse_manifest_sha256,
        page_number=12,
        block_id="block-page-12",
        locator=EvidenceLocatorSnapshotV1(
            subject_type="block",
            subject_ref="block-page-12",
            page_number=12,
            parent_refs=("page-12",),
            content_snapshot=content,
            content_snapshot_sha256=_sha(content),
        ),
        quote_snapshot=quote,
        quote_snapshot_sha256=_sha(quote),
    )
    output = FreeformFieldOutputV1(
        product_version_id="596-1",
        field_id=field_id,
        state="present",
        value_snapshot="P000001",
        evidence=(evidence,),
    )
    document = FreeformDocumentBindingV1(
        source_id="terms-source",
        source_revision_id=evidence.source_revision_id,
        source_sha256=source_sha256,
        parse_attempt_id=evidence.parse_attempt_id,
        parsed_document_hash=parsed_document_sha256,
        parse_manifest_hash=parse_manifest_sha256,
    )
    receipt_payload = {
        "contract": "freeform-arm-evidence-binding-receipt.v1",
        "product_version_id": output.product_version_id,
        "field_id": output.field_id,
        "state": output.state,
        "value_snapshot": output.value_snapshot,
        "documents": (document.model_dump(mode="python"),),
        "evidence": (evidence.model_dump(mode="python"),),
    }
    receipt = FreeformEvidenceBindingReceiptV1.model_validate(
        {
            **receipt_payload,
            "receipt_hash": canonical_hash(
                "freeform-arm-evidence-binding-receipt.v1", receipt_payload
            ),
        }
    )
    return output, receipt


def _caller_selected_citation(
    *,
    output: FreeformFieldOutputV1,
    bbox: CitationBBoxV1,
) -> CitationTargetV1:
    evidence = output.evidence[0]
    payload = {
        "contract": "citation-target.v1",
        "citation_id": "citation-caller-selected",
        "source_role": "terms",
        "space_id": "space-caller-selected",
        "entity_version_id": "ping-an-e-sheng-bao@596-1",
        "knowledge_id": "knowledge-caller-selected",
        "chunk_id": "chunk-caller-selected",
        "source_revision_id": evidence.source_revision_id,
        "parse_attempt_id": evidence.parse_attempt_id,
        "parsed_document_sha256": evidence.parsed_document_hash,
        "parse_manifest_sha256": evidence.parse_manifest_hash,
        "page_number": evidence.page_number,
        "locator_ref": evidence.locator.subject_ref,
        "bbox": bbox,
        "quote_snapshot": evidence.quote_snapshot,
        "quote_sha256": schema_wiki_sha256(
            "schema-wiki-text.v1", {"text": evidence.quote_snapshot}
        ),
        "content_snapshot_sha256": evidence.locator.content_snapshot_sha256,
        "logical_member_ref": f"field:{output.field_id}",
    }
    return CitationTargetV1.model_validate(
        {
            **payload,
            "citation_sha256": schema_wiki_sha256("citation-target.v1", payload),
        }
    )


@dataclass(frozen=True, slots=True)
class _CallerSelectedAuthority:
    citation: CitationTargetV1

    def resolve(
        self,
        *,
        output: FreeformFieldOutputV1,
        evidence_receipt: FreeformEvidenceBindingReceiptV1,
        entity_version_id: str,
    ) -> tuple[CitationTargetV1, ...]:
        del output, evidence_receipt, entity_version_id
        return (self.citation,)


@pytest.mark.parametrize(
    "bbox",
    [
        CitationBBoxV1(
            coordinate_system="pdf_points",
            page_width=600,
            page_height=800,
            x0=10,
            y0=20,
            x1=300,
            y1=400,
        ),
        CitationBBoxV1(
            coordinate_system="normalized_0_1e6",
            page_width=1_000_000,
            page_height=1_000_000,
            x0=10_000,
            y0=20_000,
            x1=300_000,
            y1=400_000,
        ),
    ],
)
def test_caller_selected_live_revision_chunk_and_bbox_require_sealed_join_receipt(
    bbox: CitationBBoxV1,
) -> None:
    """A self-consistent caller Port is not live revision/bbox authority."""
    output, receipt = _known_field()
    citation = _caller_selected_citation(output=output, bbox=bbox)

    with pytest.raises(TypeError):
        build_schema_field_page_596_1(
            output=output,
            evidence_receipt=receipt,
            citation_authority=_CallerSelectedAuthority(citation),  # type: ignore[call-arg]
        )


def test_live_revision_receipt_matches_exact_go_length_delimited_vector() -> None:
    source_id = knowledge_revision_source_id(
        tenant_id=10003,
        knowledge_id="knowledge-596-1",
        weknora_parse_attempt=2,
        resource_id="resource-source-596-1",
        file_sha256="a" * 64,
        size=4096,
        mime_type="application/pdf",
    )
    payload = {
        "contract": "live-revision-source-receipt.v1",
        "revision_source_id": source_id,
        "tenant_id": 10003,
        "space_id": "space-596-1",
        "raw_kb_id": "raw-596-1",
        "wiki_kb_id": "wiki-596-1",
        "knowledge_id": "knowledge-596-1",
        "evidence_parse_attempt_id": "capture-attempt-8",
        "weknora_parse_attempt": 2,
        "resource_id": "resource-source-596-1",
        "file_sha256": "a" * 64,
        "size": 4096,
        "mime_type": "application/pdf",
        "page_count": 39,
        "parsed_document_sha256": "b" * 64,
        "parse_manifest_sha256": "c" * 64,
        "weknora_manifest_algorithm": "weknora.chunk_manifest.v1",
        "weknora_manifest_digest": "d" * 64,
        "weknora_chunk_count": 162,
    }
    receipt = LiveRevisionSourceReceiptV1.model_validate(
        {
            **payload,
            "source_receipt_sha256": live_revision_source_receipt_sha256(payload),
        }
    )

    assert source_id == "a2fcf7b660b3e92535582ef47d7ddcd4a87ed6c0db2336e77cf64db7a7f5d908"
    assert (
        receipt.source_receipt_sha256
        == "3b38e914df2375489ba2a06a710a689be0a71e813437604007235741533423f6"
    )
    assert COORDINATE_POLICY_SHA256 == (
        "fd86399f644e6703e847686080f42799dca5376cdfb96e04fd49e6fa3b97c9ae"
    )
    mutated_digests = set()
    for field, replacement in (
        ("file_sha256", "e" * 64),
        ("parsed_document_sha256", "e" * 64),
        ("parse_manifest_sha256", "e" * 64),
        ("weknora_manifest_digest", "e" * 64),
        ("evidence_parse_attempt_id", "capture-attempt-9"),
        ("weknora_parse_attempt", 3),
    ):
        mutated = {**payload, field: replacement}
        mutated_digests.add(live_revision_source_receipt_sha256(mutated))
    assert len(mutated_digests) == 6
    assert receipt.source_receipt_sha256 not in mutated_digests


def test_citation_join_receipt_matches_frozen_go_canonical_vector() -> None:
    live_payload = {
        "contract": "live-revision-source-receipt.v1",
        "revision_source_id": "0" * 64,
        "tenant_id": 10003,
        "space_id": "space-596-1",
        "raw_kb_id": "raw-kb-596-1",
        "wiki_kb_id": "wiki-kb-596-1",
        "knowledge_id": "knowledge-terms-596-1",
        "evidence_parse_attempt_id": "evidence-attempt-01",
        "weknora_parse_attempt": 2,
        "resource_id": "resource-terms-596-1",
        "file_sha256": "c" * 64,
        "size": 4096,
        "mime_type": "application/pdf",
        "page_count": 39,
        "parsed_document_sha256": "d" * 64,
        "parse_manifest_sha256": "e" * 64,
        "weknora_manifest_algorithm": "weknora.chunk_manifest.v1",
        "weknora_manifest_digest": "7" * 64,
        "weknora_chunk_count": 162,
    }
    live_payload["source_receipt_sha256"] = live_revision_source_receipt_sha256(
        live_payload
    )
    payload = {
        "contract": "schema67-citation-authority-join-receipt.v1",
        "candidate_sha256": "a" * 64,
        "field_id": "coverage_scope",
        "source_role": "terms",
        "evidence_receipt_sha256": "b" * 64,
        "source_sha256": "c" * 64,
        "parsed_document_sha256": "d" * 64,
        "parse_manifest_sha256": "e" * 64,
        "evidence_parse_attempt_id": "evidence-attempt-01",
        "locator_kind": "block",
        "locator_ref": "block-terms-coverage_scope",
        "native_page_index": 11,
        "page_number": 12,
        "locator_content_sha256": "f" * 64,
        "quote_sha256": "1" * 64,
        "capture_identity_sha256": "2" * 64,
        "raw_structure_sha256": "3" * 64,
        "sanitized_structure_sha256": "4" * 64,
        "parser_identity_sha256": "5" * 64,
        "coordinate_policy_sha256": "6" * 64,
        "source_coordinate_space": (
            "mineru_content_list_normalized_0_1000_top_left.v1"
        ),
        "target_coordinate_space": "normalized_0_1e6",
        "origin": "top_left",
        "source_bbox_preimage": ("100", "200", "800", "900"),
        "normalized_bbox": {
            "coordinate_system": "normalized_0_1e6",
            "page_width": 1_000_000,
            "page_height": 1_000_000,
            "x0": 100_000,
            "y0": 200_000,
            "x1": 800_000,
            "y1": 900_000,
        },
        "page_width": 1_000_000,
        "page_height": 1_000_000,
        "rotation_degrees": 0,
        "highlight_precision": "block_exact",
        "tenant_id": 10003,
        "space_id": "space-596-1",
        "raw_kb_id": "raw-kb-596-1",
        "knowledge_id": "knowledge-terms-596-1",
        "weknora_parse_attempt": 2,
        "file_sha256": "c" * 64,
        "weknora_manifest_algorithm": "weknora.chunk_manifest.v1",
        "weknora_manifest_digest": "7" * 64,
        "chunk_id": "chunk-terms-12",
        "chunk_index": 37,
        "chunk_content_sha256": "8" * 64,
        "quote_occurrence_start": 120,
        "quote_occurrence_end": 168,
        "quote_occurrence_count": 1,
        "join_policy_sha256": "9" * 64,
        "live_revision_source_receipt": live_payload,
        "live_revision_source_receipt_sha256": live_payload[
            "source_receipt_sha256"
        ],
    }

    assert schema_wiki_sha256(
        "schema67-citation-authority-join-receipt.v1", payload
    ) == "91cfeec949019e30843c0b384c4420b5eb50db70017a3718cdc741fe71bf2928"


@pytest.mark.parametrize(
    ("role", "page_number", "page_count"),
    [("terms", 12, 39), ("brochure", 27, 27)],
)
def test_coordinate_receipt_exactly_scales_existing_terms_and_brochure_pages(
    role: str,
    page_number: int,
    page_count: int,
) -> None:
    del role
    preimage, bbox = normalize_mineru_bbox_596_1(
        bbox=(Decimal("100"), Decimal("200"), Decimal("800"), Decimal("900")),
        page_number=page_number,
        page_count=page_count,
    )

    assert preimage == ("100", "200", "800", "900")
    assert bbox.coordinate_system == "normalized_0_1e6"
    assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == (
        100_000,
        200_000,
        800_000,
        900_000,
    )


def test_rate_page_27_is_typed_out_of_range_instead_of_guessed() -> None:
    with pytest.raises(CandidateEvidenceAuthorityError, match="PAGE_OUT_OF_RANGE"):
        normalize_mineru_bbox_596_1(
            bbox=(Decimal("100"), Decimal("200"), Decimal("800"), Decimal("900")),
            page_number=27,
            page_count=2,
        )


def test_release_compiler_exposes_no_caller_selected_citation_authority_port() -> None:
    assert "citation_authority" not in inspect.signature(
        build_schema_field_page_596_1
    ).parameters
