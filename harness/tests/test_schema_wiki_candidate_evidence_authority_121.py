from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest

from insurance_harness.compiler.evidence_verifier import (
    EvidenceLocatorSnapshotV1,
    FreeformEvidenceV1,
)
from insurance_harness.knowledge_compiler import (
    schema_wiki_candidate_evidence_join_596_1 as candidate_evidence_join,
)
from insurance_harness.knowledge_compiler.schema67_native_pdf_selection_815 import (
    CoordinateEvidence815V1,
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
    schema_wiki_sha256,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


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
    live_payload["source_receipt_sha256"] = live_revision_source_receipt_sha256(live_payload)
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
        "source_coordinate_space": ("mineru_content_list_normalized_0_1000_top_left.v1"),
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
        "live_revision_source_receipt_sha256": live_payload["source_receipt_sha256"],
    }

    assert (
        schema_wiki_sha256("schema67-citation-authority-join-receipt.v1", payload)
        == "91cfeec949019e30843c0b384c4420b5eb50db70017a3718cdc741fe71bf2928"
    )


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


def test_native_pdf_points_use_frozen_page_dimensions_and_go_half_up_rounding() -> None:
    normalizer = getattr(
        candidate_evidence_join,
        "normalize_native_pdf_bbox_815",
        None,
    )
    assert normalizer is not None, "native PDF coordinate normalizer is missing"

    preimage, bbox = normalizer(
        bbox=("61.2", "79.2", "306", "396"),
        page_number=1,
        page_count=1,
        page_width_points="612",
        page_height_points="792",
    )

    assert preimage == ("100", "100", "500", "500")
    assert bbox.coordinate_system == "normalized_0_1e6"
    assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == (
        100_000,
        100_000,
        500_000,
        500_000,
    )

    _, half_up = normalizer(
        bbox=("0.000001", "0", "1", "1"),
        page_number=1,
        page_count=1,
        page_width_points="2",
        page_height_points="2",
    )
    assert half_up.x0 == 1


@pytest.mark.parametrize(
    ("bbox", "page_number", "page_count", "width", "height", "reason"),
    [
        (("0", "0", "1", "1"), 1, 1, "0", "792", "COORDINATE_AUTHORITY_INVALID"),
        (("0", "0", "613", "1"), 1, 1, "612", "792", "COORDINATE_AUTHORITY_INVALID"),
        (("1", "0", "1", "1"), 1, 1, "612", "792", "COORDINATE_AUTHORITY_INVALID"),
        (("2", "0", "1", "1"), 1, 1, "612", "792", "COORDINATE_AUTHORITY_INVALID"),
        (("0", "2", "1", "1"), 1, 1, "612", "792", "COORDINATE_AUTHORITY_INVALID"),
        (("0", "0", "1", "1"), 2, 1, "612", "792", "PAGE_OUT_OF_RANGE"),
    ],
)
def test_native_pdf_points_fail_closed_without_valid_frozen_page_authority(
    bbox: tuple[str, str, str, str],
    page_number: int,
    page_count: int,
    width: str,
    height: str,
    reason: str,
) -> None:
    normalizer = getattr(
        candidate_evidence_join,
        "normalize_native_pdf_bbox_815",
        None,
    )
    assert normalizer is not None, "native PDF coordinate normalizer is missing"

    with pytest.raises(CandidateEvidenceAuthorityError, match=reason):
        normalizer(
            bbox=bbox,
            page_number=page_number,
            page_count=page_count,
            page_width_points=width,
            page_height_points=height,
        )


def test_native_pdf_table_slice_binds_each_cell_to_its_exact_rect_and_quote() -> None:
    quote = "covered\N{LINE SEPARATOR}not covered"
    row = CoordinateEvidence815V1(
        field_id="coverage_summary",
        source_revision_id="revision-table",
        source_role="rate_table",
        original_file_sha256="1" * 64,
        parse_manifest_sha256="2" * 64,
        selection_id="selection-table",
        selection_type="TABLE_SLICE",
        page_number=2,
        page_text_char_start=None,
        page_text_char_end=None,
        coordinate_space="PDF_POINTS_TOP_LEFT_V1",
        page_width_points="100",
        page_height_points="100",
        bbox=("0", "0", "20", "10"),
        rects=(("0", "0", "10", "10"), ("10", "0", "20", "10")),
        quote=quote,
        quote_sha256=_sha(quote),
        table_slice_id="slice-table",
        table_id="table-1",
        cell_ids=("cell-1", "cell-2"),
    )
    cell_quote = "not covered"
    cell_content = f"prefix {cell_quote} suffix"
    evidence = FreeformEvidenceV1(
        field_id="coverage_summary",
        source_sha256="1" * 64,
        source_revision_id="revision-table",
        parse_attempt_id="attempt-table",
        parsed_document_hash="3" * 64,
        parse_manifest_hash="4" * 64,
        page_number=2,
        table_id="table-1",
        cell_id="cell-2",
        row_index=0,
        column_index=1,
        row_span=1,
        column_span=1,
        locator=EvidenceLocatorSnapshotV1(
            subject_type="cell",
            subject_ref="cell-2",
            page_number=2,
            parent_refs=("table-1",),
            content_snapshot=cell_content,
            content_snapshot_sha256=_sha(cell_content),
        ),
        quote_snapshot=cell_quote,
        quote_snapshot_sha256=_sha(cell_quote),
    )

    assert candidate_evidence_join._native_coordinate_bbox_for_evidence(
        row=row,
        field_id=evidence.field_id,
        role="rate_table",
        evidence=evidence,
        locator_kind="cell",
        locator_ref="cell-2",
        artifact_bbox=("10", "0", "20", "10"),
        coordinate_manifest_sha256="2" * 64,
    ) == ("10", "0", "20", "10")
