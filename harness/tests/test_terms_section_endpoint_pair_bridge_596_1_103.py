"""OpenSpec 103: terms-section structural endpoint-pair bridge."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.parsed_documents import (
    BlockLocatorV1,
    CapabilityEvidenceV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParseBlockV1,
    ParsedDocumentV1,
    ParseElementCountsV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    UnsupportedParseFactV1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.terms_section_endpoint_pair_bridge_596_1 import (
    SectionEndpointPairReplayV1,
    TermsSectionEndpointBridgeError,
    TermsSectionMarkerAuthorityEvidenceV1,
    TermsSectionMarkerAuthorityRequestV1,
    derive_terms_section_binding_596_1,
    derive_terms_section_endpoint_pair_596_1,
    derive_terms_section_receipt_entry_596_1,
)

TERMS_SHA = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
BROCHURE_SHA = "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
RATE_SHA = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"
RAW_HASH = "4" * 64
NATIVE_MEMBER = "2" * 64


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _domain(domain: str, value: object) -> str:
    return _sha(domain.encode() + b"\0" + _compact(value))


def _parser() -> dict[str, object]:
    value: dict[str, object] = {
        "engine": "mineru_cloud",
        "implementation": "NewMinerUCloudReader",
        "native_structure_schema": "mineru-native-structure.v1",
        "model": "pipeline",
        "formula": True,
        "table": True,
        "ocr": True,
        "language": "ch",
        "config_sha256": "",
    }
    value["config_sha256"] = _sha(b"mineru-capture-config.v1\0" + _compact(value))
    return value


def _structure(
    *, source: str = TERMS_SHA, decoy: bool = False, target_page: int = 2
) -> dict[str, object]:
    blocks = [
        {
            "block_id": "block-source",
            "order_index": 0,
            "page_number": 1,
            "block_index": 0,
            "bbox": ["10", "20", "90", "80"],
            "content_hash": _sha("source-content"),
            "structure_hash": _sha("source-structure"),
        },
        {
            "block_id": "block-target",
            "order_index": 1,
            "page_number": target_page,
            "block_index": 0,
            "bbox": ["10", "20", "90", "80"],
            "content_hash": _sha("target-content"),
            "structure_hash": _sha("target-structure"),
        },
    ]
    if decoy:
        blocks.append(
            {
                "block_id": "block-decoy",
                "order_index": 2,
                "page_number": target_page,
                "block_index": 1,
                "bbox": ["10", "90", "90", "120"],
                "content_hash": _sha("decoy-content"),
                "structure_hash": _sha("decoy-structure"),
            }
        )
    return {
        "contract": "mineru-native-structure.v1",
        "source_schema": "mineru.content-list.pipeline.v1",
        "parser_model": "pipeline",
        "source_sha256": source,
        "raw_sha256": RAW_HASH,
        "pages": [
            {
                "page_id": f"page-{page:04d}",
                "page_number": page,
                "content_hash": _sha(f"page-content-{page}"),
                "structure_hash": _sha(f"page-structure-{page}"),
            }
            for page in range(1, target_page + 1)
        ],
        "blocks": blocks,
        "tables": [],
        "cells": [],
        "unsupported": ["cross_page_sections"],
    }


def _cross_page(source: str, *, role: str, kinds: tuple[str, ...]) -> dict[str, object]:
    paths = tuple((kind, "p0/b0") for kind in kinds)
    members = [{"category": "middle_json", "size": 17, "sha256": "3" * 64}]
    observations = sorted(
        _sha(f"mineru-cross-page-ambiguous.v1\0{source}\0{kind}\0{path}")
        for kind, path in paths
    )
    value: dict[str, object] = {
        "contract": "mineru-native-cross-page-facts.v1",
        "status": (
            "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS"
            if kinds
            else "NATIVE_CROSS_PAGE_FACT_ABSENT"
        ),
        "required_capability": "cross_page_sections" if role == "terms" else "cross_page_tables",
        "source_sha256": source,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": NATIVE_MEMBER,
        "member_inventory_sha256": _sha(_compact(members)),
        "projection_sha256": "",
        "relation_count": 0,
        "ambiguous_marker_count": len(kinds),
        "ambiguous_observation_hashes": observations,
        "members": members,
        "relations": [],
    }
    projection = {
        key: value[key]
        for key in (
            "contract",
            "status",
            "required_capability",
            "source_sha256",
            "parser_model",
            "mineru_version",
            "relation_count",
            "ambiguous_marker_count",
            "ambiguous_observation_hashes",
            "relations",
        )
    }
    value["projection_sha256"] = _sha(_compact(projection))
    return value


def _markers(source: str, *, node_type: str, kinds: tuple[str, ...]) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for kind in kinds:
        path = "p0/b0"
        row: dict[str, object] = {
            "marker_kind": kind,
            "page_index": 0,
            "structural_path": path,
            "structural_path_sha256": _sha(
                f"mineru-cross-page-marker-path.v1\0{source}\0{NATIVE_MEMBER}\0{path}"
            ),
            "node_type": node_type,
            "local_index": 0,
            "marker_sha256": "",
        }
        row["marker_sha256"] = _domain(
            "mineru-cross-page-marker-evidence.v1",
            {
                "contract": "mineru-native-cross-page-marker-provenance.v1",
                "source_sha256": source,
                "parser_model": "pipeline",
                "mineru_version": "3.4.4",
                "native_member_sha256": NATIVE_MEMBER,
                **{
                    key: row[key]
                    for key in (
                        "marker_kind",
                        "page_index",
                        "structural_path_sha256",
                        "node_type",
                        "local_index",
                    )
                },
            },
        )
        rows.append(row)
    rows.sort(
        key=lambda row: (
            cast(str, row["structural_path_sha256"]),
            cast(str, row["marker_kind"]),
        )
    )
    value: dict[str, object] = {
        "contract": "mineru-native-cross-page-marker-provenance.v1",
        "source_sha256": source,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": NATIVE_MEMBER,
        "marker_count": len(rows),
        "markers": rows,
    }
    value["replay_digest_sha256"] = _domain(
        "mineru-cross-page-marker-provenance-replay.v1", value
    )
    return value


def _capture(
    source: str,
    *,
    role: str,
    structure: dict[str, object] | None = None,
    kinds: tuple[str, ...] = (),
) -> bytes:
    parser = _parser()
    body = structure or {"pages": [{"page_index": 0, "blocks": []}]}
    payload: dict[str, object] = {
        "contract": "mineru-semantic-content-custody.v2",
        "source_sha256": source,
        "attempt": {"attempt_number": 2, "attempt_role": "bounded_upgrade", "generation": 0},
        "raw_structure_sha256": RAW_HASH,
        "sanitized_structure_sha256": _sha(_compact(body)),
        "sanitized_structure": body,
        "content_snapshot_sha256": _sha("safe snapshot"),
        "content_snapshot": "safe snapshot",
        "capture_identity_sha256": "",
        "parser": parser,
        "calls": {"allocation_post": 1, "upload_put": 1, "status_get": 3, "zip_get": 1},
        "latency_milliseconds": 25,
        "status": "completed",
    }
    if role != "brochure":
        payload["cross_page_facts"] = _cross_page(source, role=role, kinds=kinds)
        payload["cross_page_marker_provenance"] = _markers(
            source, node_type="text" if role == "terms" else "table", kinds=kinds
        )
    capture = {
        "contract": payload["contract"],
        "source_sha256": source,
        "attempt": payload["attempt"],
        "parser_config_sha256": parser["config_sha256"],
        "raw_structure_sha256": RAW_HASH,
        "sanitized_structure_sha256": payload["sanitized_structure_sha256"],
        "content_snapshot_sha256": payload["content_snapshot_sha256"],
    }
    if role != "brochure":
        facts = cast(dict[str, object], payload["cross_page_facts"])
        markers = cast(dict[str, object], payload["cross_page_marker_provenance"])
        capture["cross_page_projection_sha256"] = facts["projection_sha256"]
        capture["marker_provenance_replay_sha256"] = markers["replay_digest_sha256"]
    payload["capture_identity_sha256"] = _sha(_compact(capture))
    return _compact(payload) + b"\n"


def _bbox(value: object) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    values = cast(list[str], value)
    return tuple(Decimal(item) for item in values)  # type: ignore[return-value]


def _document_manifest(
    structure: dict[str, object],
) -> tuple[ParsedDocumentV1, ParseManifestV1]:
    parser = _parser()
    subject = ParseSubjectV1(
        space_id="space-596-1",
        source_id="source-terms",
        source_revision_id="revision-terms",
        product_version_id="596-1",
        material_profile_id="material-profile-terms-596-1",
        material_profile_binding_hash="a" * 64,
        source_sha256=TERMS_SHA,
        raw_artifact_hash=RAW_HASH,
        canonical_envelope_hash="b" * 64,
    )
    parser_identity = ParserIdentityV1(
        parser_id="mineru-cloud-pipeline",
        parser_profile_ref="approved-parser-profile:parser-neutral-bounded-upgrade.v1",
        parser_build_id="mineru-3.4.4-pipeline",
        parser_config_hash=cast(str, parser["config_sha256"]),
    )
    attempt = ParseAttemptV1(
        attempt_id="attempt-terms-2",
        attempt_number=2,
        attempt_role="bounded_upgrade",
        generation=0,
    )
    snapshot = ParseSnapshotV1(
        snapshot_id="snapshot-terms",
        snapshot_generation=0,
        pagination_complete=True,
        concurrent_mutation_fence_hash="c" * 64,
    )
    output = ParseOutputFactsV1(
        privacy_policy_ref="privacy-policy:s0q-private.v1",
        output_policy_ref="output-policy:structure-only.v1",
        body_text_included=False,
        secrets_included=False,
        absolute_paths_included=False,
        unknown_vendor_fields_included=False,
    )
    pages = tuple(
        ParsePageV1(
            page_id=cast(str, row["page_id"]),
            order_index=index,
            locator=PageLocatorV1(page_number=cast(int, row["page_number"])),
            content_hash=cast(str, row["content_hash"]),
            structure_hash=cast(str, row["structure_hash"]),
        )
        for index, row in enumerate(cast(list[dict[str, Any]], structure["pages"]))
    )
    blocks = tuple(
        ParseBlockV1(
            block_id=cast(str, row["block_id"]),
            order_index=cast(int, row["order_index"]),
            locator=BlockLocatorV1(
                page_number=cast(int, row["page_number"]),
                block_index=cast(int, row["block_index"]),
                bbox=_bbox(row["bbox"]),
            ),
            content_hash=cast(str, row["content_hash"]),
            structure_hash=cast(str, row["structure_hash"]),
        )
        for row in cast(list[dict[str, Any]], structure["blocks"])
    )
    block_ids = tuple(block.block_id for block in blocks)
    evidence = (
        CapabilityEvidenceV1(
            capability="ordered_pages", subject_refs=tuple(page.page_id for page in pages)
        ),
        CapabilityEvidenceV1(capability="block_locators", subject_refs=block_ids),
    )
    unsupported = (
        UnsupportedParseFactV1(
            capability="cross_page_sections",
            reason_code="native_relation_not_available",
            subject_refs=block_ids,
        ),
    )
    document = ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=subject,
        parser=parser_identity,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        pages=pages,
        blocks=blocks,
        tables=(),
        cells=(),
        capability_evidence=evidence,
        warnings=(),
        unsupported=unsupported,
    )
    required = ("ordered_pages", "block_locators", "cross_page_sections")
    manifest = ParseManifestV1(
        contract="parse-manifest.v1",
        subject=subject,
        parser=parser_identity,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        document_hash=document.document_hash,
        ordered_page_ids=tuple(page.page_id for page in pages),
        ordered_block_ids=block_ids,
        ordered_table_ids=(),
        ordered_cell_ids=(),
        element_counts=ParseElementCountsV1(
            pages=len(pages), blocks=len(blocks), tables=0, cells=0
        ),
        required_capabilities=required,
        satisfied_capabilities=required[:-1],
        unsatisfied_capabilities=("cross_page_sections",),
        capability_evidence=evidence,
        warnings=(),
        unsupported=unsupported,
    )
    return document, manifest


def _case(
    *,
    decoy: bool = False,
    target_page: int = 2,
    kinds: tuple[str, ...] = ("cross_page",),
) -> tuple[
    MinerUCaptureBundle5961V1, ParsedDocumentV1, ParseManifestV1
]:
    structure = _structure(decoy=decoy, target_page=target_page)
    bundle = intake_mineru_capture_bundle_596_1(
        (
            _capture(TERMS_SHA, role="terms", structure=structure, kinds=kinds),
            _capture(BROCHURE_SHA, role="brochure"),
            _capture(RATE_SHA, role="rate"),
        )
    )
    document, manifest = _document_manifest(structure)
    return bundle, document, manifest


class _Authority:
    def __init__(self, *, mutation: str | None = None) -> None:
        self.mutation = mutation

    def replay_terms_section_authority(
        self, request: TermsSectionMarkerAuthorityRequestV1
    ) -> TermsSectionMarkerAuthorityEvidenceV1:
        ancestry = (_sha("outline-root"), _sha("section-7"))
        anchors = (_sha("heading-anchor-7"),)
        values: dict[str, object] = {
            "contract": "terms-section-marker-authority-evidence.v1",
            "authority_contract": "marker-authority-envelope.v1",
            "authority_version_sha256": _sha("authority-v1"),
            "request_digest_sha256": request.request_digest_sha256,
            "marker_kind": "cross_page",
            "relation_kind": "section",
            "source_endpoint_id": request.source_endpoint.endpoint_id,
            "source_page_number": request.source_endpoint.page_number,
            "source_endpoint_path_sha256": request.source_endpoint.locator_digest_sha256,
            "target_endpoint_id": request.target_endpoint.endpoint_id,
            "target_page_number": request.target_endpoint.page_number,
            "target_endpoint_path_sha256": request.target_endpoint.locator_digest_sha256,
            "source_section_ancestry_node_hashes": ancestry,
            "target_section_ancestry_node_hashes": ancestry,
            "section_ancestry_sha256": canonical_hash("terms-section-ancestry.v1", ancestry),
            "source_outline_anchor_node_hashes": anchors,
            "target_outline_anchor_node_hashes": anchors,
            "outline_anchor_sha256": canonical_hash(
                "terms-section-outline-anchor.v1", anchors
            ),
            "target_starts_new_heading": False,
        }
        if self.mutation == "target":
            values["target_endpoint_id"] = "foreign-block"
        elif self.mutation == "heading":
            values["target_starts_new_heading"] = True
        elif self.mutation == "request":
            values["request_digest_sha256"] = "0" * 64
        elif self.mutation == "ancestry":
            values["target_section_ancestry_node_hashes"] = (_sha("foreign-section"),)
        authority_preimage = {
            key: values[key]
            for key in (
                "authority_contract",
                "authority_version_sha256",
                "request_digest_sha256",
                "marker_kind",
                "relation_kind",
                "source_endpoint_id",
                "source_page_number",
                "source_endpoint_path_sha256",
                "target_endpoint_id",
                "target_page_number",
                "target_endpoint_path_sha256",
                "source_section_ancestry_node_hashes",
                "target_section_ancestry_node_hashes",
                "source_outline_anchor_node_hashes",
                "target_outline_anchor_node_hashes",
                "target_starts_new_heading",
            )
        }
        values["authority_preimage_sha256"] = canonical_hash(
            "terms-section-marker-authority-preimage.v1", authority_preimage
        )
        values["evidence_digest_sha256"] = canonical_hash(
            "terms-section-marker-authority-evidence.v1", values
        )
        return TermsSectionMarkerAuthorityEvidenceV1.model_validate(values)


def test_current_terms_without_section_anchor_is_honestly_not_available() -> None:
    with pytest.raises(
        TermsSectionEndpointBridgeError, match="SECTION_ANCHOR_NOT_AVAILABLE"
    ) as caught:
        derive_terms_section_endpoint_pair_596_1(*_case(), authority=None)
    assert caught.value.status == "NOT_AVAILABLE"


def test_future_authority_replays_through_102_086_and_096_entry() -> None:
    case = _case(decoy=True)
    pair = derive_terms_section_endpoint_pair_596_1(*case, _Authority())
    binding = derive_terms_section_binding_596_1(*case, _Authority())
    entry = derive_terms_section_receipt_entry_596_1(*case, _Authority())

    assert isinstance(pair, SectionEndpointPairReplayV1)
    assert pair.source_endpoint.endpoint_id == "block-source"
    assert pair.target_endpoint.endpoint_id == "block-target"
    assert binding.status == "DERIVED_STRUCTURAL_BINDING_VERIFIED"
    assert binding.relation_kind == "section"
    assert entry.receipt_role == "terms"
    assert entry.binding == binding
    assert all(token not in pair.model_dump_json() for token in ("NATIVE", "ADMIT", "READY"))


@pytest.mark.parametrize("mutation", ["target", "heading", "request", "ancestry"])
def test_authority_endpoint_heading_and_request_drift_fail_closed(mutation: str) -> None:
    with pytest.raises((TermsSectionEndpointBridgeError, ValueError)):
        derive_terms_section_endpoint_pair_596_1(*_case(), _Authority(mutation=mutation))


def test_lines_deleted_and_marker_cardinality_never_become_section_relation() -> None:
    for kinds in (("lines_deleted",), ("cross_page", "lines_deleted")):
        with pytest.raises(TermsSectionEndpointBridgeError):
            derive_terms_section_endpoint_pair_596_1(*_case(kinds=kinds), _Authority())

    with pytest.raises(ValueError):
        _case(kinds=("unknown",))


def test_page_node_local_index_member_source_parser_and_hash_drift_fail_closed() -> None:
    bundle, document, manifest = _case()
    item = bundle.sources[0]
    provenance = item.evidence.cross_page_marker_provenance
    assert provenance is not None
    marker = provenance.markers[0]
    marker_mutations = (
        marker.model_copy(update={"page_index": 1}),
        marker.model_copy(update={"node_type": "table"}),
        marker.model_copy(update={"local_index": 1}),
        marker.model_copy(update={"structural_path_sha256": "0" * 64}),
        marker.model_copy(update={"marker_sha256": "0" * 64}),
    )
    for changed in marker_mutations:
        changed_provenance = provenance.model_copy(update={"markers": (changed,)})
        changed_item = item.model_copy(
            update={
                "evidence": item.evidence.model_copy(
                    update={"cross_page_marker_provenance": changed_provenance}
                )
            }
        )
        changed_bundle = bundle.model_copy(
            update={"sources": (changed_item, bundle.sources[1], bundle.sources[2])}
        )
        with pytest.raises(TermsSectionEndpointBridgeError):
            derive_terms_section_endpoint_pair_596_1(
                changed_bundle, document, manifest, _Authority()
            )

    for field, value in (
        ("raw_zip_sha256", "0" * 64),
        ("native_member_sha256", "0" * 64),
        ("parser_model", "drift"),
        ("mineru_version", "drift"),
    ):
        changed_provenance = provenance.model_copy(update={field: value})
        changed_item = item.model_copy(
            update={
                "evidence": item.evidence.model_copy(
                    update={"cross_page_marker_provenance": changed_provenance}
                )
            }
        )
        changed_bundle = bundle.model_copy(
            update={"sources": (changed_item, bundle.sources[1], bundle.sources[2])}
        )
        with pytest.raises(TermsSectionEndpointBridgeError):
            derive_terms_section_endpoint_pair_596_1(
                changed_bundle, document, manifest, _Authority()
            )

    for changed_document, changed_manifest in (
        (
            document.model_copy(
                update={
                    "parser": document.parser.model_copy(
                        update={"parser_config_hash": "0" * 64}
                    )
                }
            ),
            manifest,
        ),
        (document, manifest.model_copy(update={"document_hash": "0" * 64})),
        (
            document.model_copy(
                update={
                    "subject": document.subject.model_copy(
                        update={"source_sha256": "0" * 64}
                    )
                }
            ),
            manifest,
        ),
    ):
        with pytest.raises(TermsSectionEndpointBridgeError):
            derive_terms_section_endpoint_pair_596_1(
                bundle, changed_document, changed_manifest, _Authority()
            )


def test_wrong_first_block_two_page_distance_and_missing_capability_fail_closed() -> None:
    bundle, document, manifest = _case(decoy=True)
    changed_blocks = tuple(
        block.model_copy(
            update={
                "locator": block.locator.model_copy(update={"page_number": 1})
            }
        )
        if block.block_id == "block-target"
        else block
        for block in document.blocks
    )
    with pytest.raises(TermsSectionEndpointBridgeError):
        derive_terms_section_endpoint_pair_596_1(
            bundle,
            document.model_copy(update={"blocks": changed_blocks}),
            manifest,
            _Authority(),
        )

    evidence = tuple(
        row.model_copy(update={"subject_refs": ("block-source",)})
        if row.capability == "block_locators"
        else row
        for row in document.capability_evidence
    )
    with pytest.raises(TermsSectionEndpointBridgeError):
        derive_terms_section_endpoint_pair_596_1(
            bundle,
            document.model_copy(update={"capability_evidence": evidence}),
            manifest,
            _Authority(),
        )

    with pytest.raises(
        TermsSectionEndpointBridgeError, match="SECTION_TARGET_ENDPOINT_NOT_AVAILABLE"
    ):
        derive_terms_section_endpoint_pair_596_1(
            *_case(target_page=3), _Authority()
        )


def test_pair_is_deterministic_and_privacy_safe() -> None:
    first = derive_terms_section_endpoint_pair_596_1(*_case(), _Authority())
    second = derive_terms_section_endpoint_pair_596_1(*_case(), _Authority())
    assert first == second
    rendered = repr(first) + first.model_dump_json()
    assert "safe snapshot" not in rendered
    assert "/Users/" not in rendered
    assert "https://" not in rendered
