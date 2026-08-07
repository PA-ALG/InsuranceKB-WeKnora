"""OpenSpec 106: native section-anchor evidence for the terms bridge."""

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
from insurance_harness.knowledge_compiler.marker_authority_envelope_596_1 import (
    MarkerAuthorityEnvelopeV1,
    _build_envelope,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    NativeCrossPageMarkerEvidenceV1,
    NativeCrossPageMarkerProvenanceV1,
    NativeHierarchyNodeV1,
    NativeHierarchyProvenanceV1,
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.mineru_native_section_anchor_evidence_596_1 import (
    SectionAnchorAuthorityV1,
    SectionAnchorEvidenceError,
    derive_section_anchor_authority_596_1,
    group_terms_cross_page_markers_596_1,
)
from insurance_harness.knowledge_compiler.terms_section_endpoint_pair_bridge_596_1 import (
    TermsSectionMarkerAuthorityRequestV1,
)

TERMS = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
BROCHURE = "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
RATE = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"
MEMBER = "2" * 64


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


def _marker(source: str, *, local_index: int, kind: str = "cross_page") -> dict[str, object]:
    path = f"p0/b{local_index}"
    path_hash = _sha(f"mineru-cross-page-marker-path.v1\0{source}\0{MEMBER}\0{path}")
    preimage = {
        "contract": "mineru-native-cross-page-marker-provenance.v1",
        "source_sha256": source,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "native_member_sha256": MEMBER,
        "marker_kind": kind,
        "page_index": 0,
        "structural_path_sha256": path_hash,
        "node_type": "text" if source == TERMS else "table",
        "local_index": local_index,
    }
    return {
        "marker_kind": preimage["marker_kind"],
        "page_index": preimage["page_index"],
        "structural_path": path,
        "structural_path_sha256": preimage["structural_path_sha256"],
        "node_type": preimage["node_type"],
        "local_index": preimage["local_index"],
        "marker_sha256": _domain("mineru-cross-page-marker-evidence.v1", preimage),
    }


def _cross_page(
    source: str,
    *,
    role: str,
    local_index: int,
    structure: dict[str, object],
    kind: str = "cross_page",
) -> tuple[dict[str, object], dict[str, object]]:
    marker = _marker(source, local_index=local_index, kind=kind)
    members = [{"category": "middle_json", "size": 17, "sha256": "3" * 64}]
    facts: dict[str, object] = {
        "contract": "mineru-native-cross-page-facts.v1",
        "status": "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS",
        "required_capability": "cross_page_sections" if role == "terms" else "cross_page_tables",
        "source_sha256": source,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": MEMBER,
        "member_inventory_sha256": _sha(_compact(members)),
        "projection_sha256": "",
        "relation_count": 0,
        "ambiguous_marker_count": 1,
        "ambiguous_observation_hashes": [marker["marker_sha256"]],
        "members": members,
        "relations": [],
    }
    facts["projection_sha256"] = _sha(
        _compact(
            {
                key: facts[key]
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
        )
    )
    provenance: dict[str, object] = {
        "contract": "mineru-native-cross-page-marker-provenance.v1",
        "source_sha256": source,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": MEMBER,
        "marker_count": 1,
        "markers": [marker],
        "native_hierarchy_provenance": _hierarchy(source, structure),
    }
    replay = {
        key: provenance[key]
        for key in (
            "contract",
            "source_sha256",
            "parser_model",
            "mineru_version",
            "raw_zip_sha256",
            "native_member_sha256",
            "marker_count",
            "markers",
        )
    }
    replay["native_hierarchy_replay_sha256"] = cast(
        dict[str, object], provenance["native_hierarchy_provenance"]
    )["replay_digest_sha256"]
    provenance["replay_digest_sha256"] = _domain(
        "mineru-cross-page-marker-provenance-replay.v1", replay
    )
    return facts, provenance


def _hierarchy(source: str, structure: dict[str, object]) -> dict[str, object]:
    nodes: list[dict[str, object]] = []
    hierarchy_count = 0
    pages = cast(list[dict[str, Any]], structure["pdf_info"])
    for page_index, page in enumerate(pages):
        blocks = cast(list[dict[str, Any]], page["para_blocks"])
        for local_index, block in enumerate(blocks):
            path = f"p{page_index}/b{local_index}"
            path_sha = _sha(
                f"mineru-cross-page-marker-path.v1\0{source}\0{MEMBER}\0{path}"
            )
            level = block.get("text_level")
            if level is not None:
                hierarchy_count += 1
            node: dict[str, object] = {
                "page_index": page_index,
                "node_type": block["type"],
                "local_index": local_index,
                "reading_order": len(nodes),
                "structural_path": path,
                "structural_path_sha256": path_sha,
                "bbox_present": False,
                "bbox_sha256": _sha(b"mineru-native-hierarchy-bbox.v1\0null"),
                "text_level": level,
            }
            preimage = {
                "contract": "mineru-native-hierarchy-provenance.v1.node",
                "source_sha256": source,
                "parser_model": "pipeline",
                "mineru_version": "3.4.4",
                "raw_zip_sha256": "1" * 64,
                "native_member_sha256": MEMBER,
                **node,
            }
            node["node_preimage_sha256"] = _domain(
                "mineru-native-hierarchy-node.v1", preimage
            )
            nodes.append(node)
    hierarchy: dict[str, object] = {
        "contract": "mineru-native-hierarchy-provenance.v1",
        "status": (
            "NATIVE_HIERARCHY_PROVENANCE_CAPTURED"
            if hierarchy_count
            else "HIERARCHY_PROVENANCE_NOT_CAPTURED"
        ),
        "source_sha256": source,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": MEMBER,
        "native_member_category": "middle_json",
        "node_count": len(nodes),
        "hierarchy_field_count": hierarchy_count,
        "nodes": nodes,
    }
    hierarchy["replay_digest_sha256"] = _domain(
        "mineru-native-hierarchy-provenance-replay.v1", hierarchy
    )
    return hierarchy


def _structure(*, heading: bool = True, boundary: bool = False, gap: int = 1) -> dict[str, object]:
    page0: list[dict[str, object]] = []
    if heading:
        page0.append({"type": "text", "text_level": 1, "lines": []})
    page0.append({"type": "text", "cross_page": True, "lines": []})
    page1: list[dict[str, object]] = []
    if boundary:
        page1.append({"type": "title", "text_level": 2, "lines": []})
    page1.append({"type": "text", "lines": []})
    pages: list[dict[str, object]] = [
        {"page_idx": 0, "para_blocks": page0},
    ]
    for page in range(1, gap):
        pages.append({"page_idx": page, "para_blocks": [{"type": "header", "lines": []}]})
    pages.append({"page_idx": gap, "para_blocks": page1})
    return {"_backend": "pipeline", "_version_name": "3.4.4", "pdf_info": pages}


def _capture(source: str, role: str, structure: dict[str, object]) -> bytes:
    parser = _parser()
    canonical_structure = {
        "contract": "mineru-native-structure.v1",
        "pages": [],
        "unsupported": [],
    }
    payload: dict[str, object] = {
        "contract": "mineru-semantic-content-custody.v2",
        "source_sha256": source,
        "attempt": {"attempt_number": 2, "attempt_role": "bounded_upgrade", "generation": 0},
        "raw_structure_sha256": "4" * 64,
        "sanitized_structure_sha256": _sha(_compact(canonical_structure)),
        "sanitized_structure": canonical_structure,
        "content_snapshot_sha256": _sha("safe snapshot"),
        "content_snapshot": "safe snapshot",
        "capture_identity_sha256": "",
        "parser": parser,
        "calls": {"allocation_post": 1, "upload_put": 1, "status_get": 3, "zip_get": 1},
        "latency_milliseconds": 25,
        "status": "completed",
    }
    if role != "brochure":
        pages = cast(list[dict[str, Any]], structure["pdf_info"])
        first_blocks = cast(list[dict[str, Any]], pages[0]["para_blocks"])
        local_index = next(
            index for index, block in enumerate(first_blocks) if block.get("cross_page") is True
        )
        facts, provenance = _cross_page(
            source,
            role=role,
            local_index=local_index,
            structure=structure,
        )
        payload["cross_page_facts"] = facts
        payload["cross_page_marker_provenance"] = provenance
    identity: dict[str, object] = {
        "contract": payload["contract"],
        "source_sha256": source,
        "attempt": payload["attempt"],
        "parser_config_sha256": parser["config_sha256"],
        "raw_structure_sha256": payload["raw_structure_sha256"],
        "sanitized_structure_sha256": payload["sanitized_structure_sha256"],
        "content_snapshot_sha256": payload["content_snapshot_sha256"],
    }
    if role != "brochure":
        identity["cross_page_projection_sha256"] = cast(
            dict[str, object], payload["cross_page_facts"]
        )["projection_sha256"]
        identity["marker_provenance_replay_sha256"] = cast(
            dict[str, object], payload["cross_page_marker_provenance"]
        )["replay_digest_sha256"]
    payload["capture_identity_sha256"] = _sha(_compact(identity))
    return _compact(payload) + b"\n"


def _bundle(
    structure: dict[str, object],
) -> tuple[MinerUCaptureBundle5961V1, MarkerAuthorityEnvelopeV1]:
    payloads = (
        _capture(TERMS, "terms", structure),
        _capture(BROCHURE, "brochure", {"pages": [{"page_index": 0, "blocks": []}]}),
        _capture(
            RATE,
            "rate",
            {
                "_backend": "pipeline",
                "_version_name": "3.4.4",
                "pdf_info": [
                    {
                        "page_idx": 0,
                        "para_blocks": [
                            {"type": "header", "lines": []},
                            {"type": "table", "cross_page": True, "lines": []},
                        ],
                    }
                ],
            },
        ),
    )
    return intake_mineru_capture_bundle_596_1(payloads), _build_envelope(payloads)


def _document(structure: dict[str, object]) -> tuple[ParsedDocumentV1, ParseManifestV1]:
    parser = _parser()
    subject = ParseSubjectV1(
        space_id="space-596-1",
        source_id="source-terms",
        source_revision_id="revision-terms",
        product_version_id="596-1",
        material_profile_id="material-profile-terms-596-1",
        material_profile_binding_hash="a" * 64,
        source_sha256=TERMS,
        raw_artifact_hash="4" * 64,
        canonical_envelope_hash="b" * 64,
    )
    parser_identity = ParserIdentityV1(
        parser_id="mineru-cloud-pipeline",
        parser_profile_ref="approved-parser-profile:parser-neutral-bounded-upgrade.v1",
        parser_build_id="mineru-3.4.4-pipeline",
        parser_config_hash=cast(str, parser["config_sha256"]),
    )
    attempt = ParseAttemptV1(
        attempt_id="attempt-terms-2", attempt_number=2, attempt_role="bounded_upgrade", generation=0
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
    native_pages = cast(list[dict[str, Any]], structure["pdf_info"])
    pages = tuple(
        ParsePageV1(
            page_id=f"page-{index + 1}",
            order_index=index,
            locator=PageLocatorV1(page_number=index + 1),
            content_hash=_sha(f"page-content-{index}"),
            structure_hash=_sha(f"page-structure-{index}"),
        )
        for index in range(len(native_pages))
    )
    blocks: list[ParseBlockV1] = []
    order = 0
    for page_index, page in enumerate(native_pages):
        for block_index, row in enumerate(cast(list[dict[str, Any]], page["para_blocks"])):
            node_type = cast(str, row["type"])
            if (
                node_type
                in {
                    "header",
                    "footer",
                    "page_header",
                    "page_footer",
                    "page_number",
                    "title",
                    "section",
                }
                or row.get("text_level") is not None
            ):
                continue
            blocks.append(
                ParseBlockV1(
                    block_id=f"block-{page_index}-{block_index}",
                    order_index=order,
                    locator=BlockLocatorV1(
                        page_number=page_index + 1,
                        block_index=block_index,
                        bbox=(Decimal(1), Decimal(2), Decimal(3), Decimal(4)),
                    ),
                    content_hash=_sha(f"content-{page_index}-{block_index}"),
                    structure_hash=_sha(f"structure-{page_index}-{block_index}"),
                )
            )
            order += 1
    refs = tuple(block.block_id for block in blocks)
    capabilities = (
        CapabilityEvidenceV1(
            capability="ordered_pages", subject_refs=tuple(page.page_id for page in pages)
        ),
        CapabilityEvidenceV1(capability="block_locators", subject_refs=refs),
    )
    unsupported = (
        UnsupportedParseFactV1(
            capability="cross_page_sections",
            reason_code="native_relation_not_available",
            subject_refs=refs,
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
        blocks=tuple(blocks),
        tables=(),
        cells=(),
        capability_evidence=capabilities,
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
        ordered_block_ids=refs,
        ordered_table_ids=(),
        ordered_cell_ids=(),
        element_counts=ParseElementCountsV1(
            pages=len(pages), blocks=len(blocks), tables=0, cells=0
        ),
        required_capabilities=required,
        satisfied_capabilities=required[:-1],
        unsatisfied_capabilities=("cross_page_sections",),
        capability_evidence=capabilities,
        warnings=(),
        unsupported=unsupported,
    )
    return document, manifest


def _case(
    *, heading: bool = True, boundary: bool = False, gap: int = 1
) -> tuple[
    MinerUCaptureBundle5961V1,
    ParsedDocumentV1,
    ParseManifestV1,
    MarkerAuthorityEnvelopeV1,
]:
    structure = _structure(heading=heading, boundary=boundary, gap=gap)
    bundle, envelope = _bundle(structure)
    document, manifest = _document(structure)
    return bundle, document, manifest, envelope


def _request(authority: SectionAnchorAuthorityV1) -> TermsSectionMarkerAuthorityRequestV1:
    evidence = authority.evidence
    values: dict[str, object] = {
        "contract": "terms-section-marker-authority-request.v1",
        "source_sha256": evidence.source_sha256,
        "parser_identity_sha256": evidence.parser_identity_sha256,
        "parser_config_sha256": evidence.parser_config_sha256,
        "intake_bundle_digest_sha256": evidence.intake_bundle_digest_sha256,
        "intake_item_digest_sha256": evidence.intake_item_digest_sha256,
        "capture_identity_sha256": evidence.capture_identity_sha256,
        "raw_structure_sha256": evidence.raw_structure_sha256,
        "sanitized_structure_sha256": evidence.sanitized_structure_sha256,
        "raw_zip_sha256": evidence.raw_zip_sha256,
        "native_member_sha256": evidence.native_member_sha256,
        "member_inventory_sha256": evidence.member_inventory_sha256,
        "native_projection_sha256": cast(
            Any, _bundle(_structure())[0].sources[0].evidence.cross_page_facts
        ).projection_sha256,
        "native_observation_sha256": cast(
            Any, _bundle(_structure())[0].sources[0].evidence.cross_page_facts
        ).ambiguous_observation_hashes[0],
        "cross_page_facts_digest_sha256": evidence.cross_page_facts_digest_sha256,
        "marker_provenance_digest_sha256": evidence.marker_provenance_digest_sha256,
        "marker_provenance_replay_sha256": evidence.marker_provenance_replay_sha256,
        "marker_kind": "cross_page",
        "marker_page_index": 0,
        "marker_node_type": "text",
        "marker_local_index": 1,
        "marker_structural_path": "p0/b1",
        "marker_structural_path_sha256": _sha(
            f"mineru-cross-page-marker-path.v1\0{TERMS}\0{MEMBER}\0p0/b1"
        ),
        "marker_evidence_sha256": evidence.marker_evidence_sha256,
        "source_endpoint": evidence.source_endpoint.model_dump(mode="python"),
        "target_endpoint": evidence.target_endpoint.model_dump(mode="python"),
    }
    return TermsSectionMarkerAuthorityRequestV1.model_validate(
        {
            **values,
            "request_digest_sha256": canonical_hash(
                "terms-section-marker-authority-request.v1", values
            ),
        }
    )


def test_verified_anchor_replays_without_text() -> None:
    bundle, document, manifest, envelope = _case()
    authority = derive_section_anchor_authority_596_1(bundle, document, manifest, envelope)
    replayed = authority.replay_terms_section_authority(_request(authority))
    assert authority.evidence.status == "SECTION_ANCHOR_EVIDENCE_VERIFIED"
    assert (
        replayed.source_section_ancestry_node_hashes == replayed.target_section_ancestry_node_hashes
    )
    wire = authority.model_dump_json()
    assert "safe snapshot" not in wire and "content_snapshot" not in wire


def test_section_anchor_contract_reads_separate_body_free_hierarchy() -> None:
    assert NativeHierarchyNodeV1.model_fields["text_level"].annotation is not None
    assert NativeHierarchyProvenanceV1.model_fields["nodes"].annotation is not None


@pytest.mark.parametrize(
    ("options", "reason"),
    [
        ({"heading": False}, "SECTION_ANCHOR_NOT_AVAILABLE"),
        ({"boundary": True}, "SECTION_BOUNDARY_INTERVENES"),
        ({"gap": 2}, "SECTION_TARGET_NOT_AVAILABLE"),
    ],
)
def test_structural_insufficiency_is_typed(options: dict[str, object], reason: str) -> None:
    bundle, document, manifest, envelope = _case(
        heading=cast(bool, options.get("heading", True)),
        boundary=cast(bool, options.get("boundary", False)),
        gap=cast(int, options.get("gap", 1)),
    )
    with pytest.raises(SectionAnchorEvidenceError, match=reason):
        derive_section_anchor_authority_596_1(bundle, document, manifest, envelope)


def test_header_footer_are_excluded_and_nested_levels_are_bound() -> None:
    structure = _structure()
    pages = cast(list[dict[str, Any]], structure["pdf_info"])
    pages[0]["para_blocks"] = [
        {"type": "text", "text_level": 1, "lines": []},
        {"type": "text", "text_level": 2, "lines": []},
        {"type": "header", "lines": []},
        {"type": "text", "cross_page": True, "lines": []},
    ]
    bundle, envelope = _bundle(structure)
    document, manifest = _document(structure)
    authority = derive_section_anchor_authority_596_1(bundle, document, manifest, envelope)
    assert len(authority.evidence.anchor_nodes) == 2
    assert all(node.node_type != "header" for node in authority.evidence.anchor_nodes)


def test_model_copy_identity_and_request_drift_fail_closed() -> None:
    bundle, document, manifest, envelope = _case()
    authority = derive_section_anchor_authority_596_1(bundle, document, manifest, envelope)
    request = _request(authority)
    forged = request.model_copy(update={"raw_zip_sha256": "f" * 64})
    with pytest.raises(SectionAnchorEvidenceError, match="SECTION_AUTHORITY_REQUEST"):
        authority.replay_terms_section_authority(forged)
    forged_envelope = envelope.model_copy(update={"envelope_sha256": "f" * 64})
    with pytest.raises(SectionAnchorEvidenceError, match="SECTION_CUSTODY_IDENTITY_DRIFT"):
        derive_section_anchor_authority_596_1(bundle, document, manifest, forged_envelope)


def test_lines_deleted_marker_cannot_become_section_authority() -> None:
    bundle, document, manifest, envelope = _case()
    terms = envelope.marker_sources[0]
    forged_marker = terms.markers[0].model_copy(update={"marker_kind": "lines_deleted"})
    forged_terms = terms.model_copy(update={"markers": (*terms.markers, forged_marker)})
    forged = envelope.model_copy(
        update={"marker_sources": (forged_terms, envelope.marker_sources[1])}
    )
    with pytest.raises(
        SectionAnchorEvidenceError, match="LINES_DELETED_NOT_SECTION_AUTHORITY"
    ):
        derive_section_anchor_authority_596_1(bundle, document, manifest, forged)


def test_nested_markers_group_into_three_ordered_section_relations() -> None:
    marker_rows: list[NativeCrossPageMarkerEvidenceV1] = []
    for page, block, count in ((5, 17, 4), (7, 13, 3), (35, 20, 4)):
        for line in range(count):
            path = f"p{page}/b{block}/lines/{line}/spans/0"
            marker_rows.append(
                NativeCrossPageMarkerEvidenceV1.model_construct(
                    marker_kind="cross_page",
                    page_index=page,
                    structural_path=path,
                    structural_path_sha256=_sha(path),
                    node_type="text",
                    local_index=0,
                    marker_sha256=_sha(f"marker:{path}"),
                )
            )
        target_path = f"p{page + 1}/b0"
        marker_rows.append(
            NativeCrossPageMarkerEvidenceV1.model_construct(
                marker_kind="lines_deleted",
                page_index=page + 1,
                structural_path=target_path,
                structural_path_sha256=_sha(target_path),
                node_type="text",
                local_index=0,
                marker_sha256=_sha(f"marker:{target_path}"),
            )
        )
    marker_rows.sort(
        key=lambda item: (
            item.page_index, item.structural_path_sha256, item.marker_kind
        )
    )
    hierarchy_rows: list[NativeHierarchyNodeV1] = []
    for page, block, node_type, level in (
        (0, 0, "title", 1),
        (5, 17, "text", None),
        (6, 0, "text", None),
        (7, 13, "text", None),
        (8, 0, "text", None),
        (34, 1, "title", 2),
        (35, 20, "text", None),
        (36, 0, "text", None),
    ):
        path = f"p{page}/b{block}"
        hierarchy_rows.append(
            NativeHierarchyNodeV1.model_construct(
                page_index=page,
                node_type=node_type,
                local_index=block,
                reading_order=len(hierarchy_rows),
                structural_path=path,
                structural_path_sha256=_sha(path),
                bbox_present=False,
                bbox_sha256=_sha("bbox"),
                text_level=level,
                node_preimage_sha256=_sha(f"node:{path}"),
            )
        )
    hierarchy = NativeHierarchyProvenanceV1.model_construct(
        contract="mineru-native-hierarchy-provenance.v1",
        status="NATIVE_HIERARCHY_PROVENANCE_CAPTURED",
        source_sha256=TERMS,
        parser_model="pipeline",
        mineru_version="3.4.4",
        raw_zip_sha256="1" * 64,
        native_member_sha256=MEMBER,
        native_member_category="middle_json",
        node_count=len(hierarchy_rows),
        hierarchy_field_count=2,
        nodes=tuple(hierarchy_rows),
        replay_digest_sha256="2" * 64,
    )
    provenance = NativeCrossPageMarkerProvenanceV1.model_construct(
        contract="mineru-native-cross-page-marker-provenance.v1",
        source_sha256=TERMS,
        parser_model="pipeline",
        mineru_version="3.4.4",
        raw_zip_sha256="1" * 64,
        native_member_sha256=MEMBER,
        marker_count=len(marker_rows),
        markers=tuple(marker_rows),
        native_hierarchy_provenance=hierarchy,
        replay_digest_sha256="3" * 64,
    )

    groups = group_terms_cross_page_markers_596_1(provenance)

    assert len(groups) == 3
    assert tuple(group.source_marker_count for group in groups) == (4, 3, 4)
    assert tuple(
        (group.source_page_index, group.source_block_index,
         group.target_page_index, group.target_block_index)
        for group in groups
    ) == ((5, 17, 6, 0), (7, 13, 8, 0), (35, 20, 36, 0))
    assert all(group.section_ancestor_node_sha256 for group in groups)
