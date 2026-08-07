"""OpenSpec 086: honest task-local derived structural cross-page binding."""

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
    CellLocatorV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParseBlockV1,
    ParseCellV1,
    ParsedDocumentV1,
    ParseElementCountsV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    ParseTableV1,
    TableLocatorV1,
    UnsupportedParseFactV1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    CrossPageBindingError,
    CrossPageMarkerReplayRequestV1,
    CrossPageRelationBindingV1,
    CrossPageTypedMarkerEvidenceV1,
    derive_cross_page_relation_596_1,
    replay_cross_page_relation_binding_v1,
)
from tests._mineru_marker_envelope_fixture_108 import (
    MarkerFixtureV1,
    attach_marker_envelope_108,
)

TERMS_SHA = "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"
BROCHURE_SHA = "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"
RATE_SHA = "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb"
RAW_HASH = "4" * 64


class _TypedMarkerAuthority:
    def __init__(
        self,
        *,
        relation_kind: str = "table",
        marker_kind: str = "cross_page",
        source_endpoint_id: str = "table-000000",
        source_page_number: int = 1,
        target_endpoint_id: str = "table-000001",
        target_page_number: int = 2,
        marker_structural_path: str = "p0/b0",
        mutation: dict[str, object] | None = None,
    ) -> None:
        self.relation_kind = relation_kind
        self.marker_kind = marker_kind
        self.source_endpoint_id = source_endpoint_id
        self.source_page_number = source_page_number
        self.target_endpoint_id = target_endpoint_id
        self.target_page_number = target_page_number
        self.marker_structural_path = marker_structural_path
        self.mutation = mutation or {}

    def replay_typed_cross_page_marker(
        self,
        request: CrossPageMarkerReplayRequestV1,
    ) -> CrossPageTypedMarkerEvidenceV1:
        values: dict[str, object] = {
            "contract": "cross-page-typed-marker-evidence.v1",
            "authority": "future-089-typed-marker-replay",
            "request_digest_sha256": request.request_digest_sha256,
            "marker_kind": self.marker_kind,
            "relation_kind": self.relation_kind,
            "marker_structural_path": self.marker_structural_path,
            "marker_path_sha256": canonical_hash(
                "mineru-native-structural-path.v1", self.marker_structural_path
            ),
            "source_endpoint_id": self.source_endpoint_id,
            "source_page_number": self.source_page_number,
            "source_endpoint_path_sha256": _sha("native-source-path"),
            "target_endpoint_id": self.target_endpoint_id,
            "target_page_number": self.target_page_number,
            "target_endpoint_path_sha256": _sha("native-target-path"),
            "evidence_digest_sha256": "0" * 64,
        }
        values.update(self.mutation)
        values["evidence_digest_sha256"] = canonical_hash(
            "cross-page-typed-marker-evidence.v1",
            {key: value for key, value in values.items() if key != "evidence_digest_sha256"},
        )
        return CrossPageTypedMarkerEvidenceV1.model_validate(values)


def _sha(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def _compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def _bbox(value: object) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    values = cast(list[str], value)
    assert len(values) == 4
    return (
        Decimal(values[0]),
        Decimal(values[1]),
        Decimal(values[2]),
        Decimal(values[3]),
    )


def _parser() -> dict[str, object]:
    parser: dict[str, object] = {
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
    parser["config_sha256"] = _sha(b"mineru-capture-config.v1\0" + _compact(parser))
    return parser


def _cross_page(
    source: str,
    capability: str,
    *,
    markers: int,
    marker_kind: str = "cross_page",
) -> dict[str, object]:
    members = [{"category": "middle_json", "size": 17, "sha256": "3" * 64}]
    observations = sorted(
        _sha(f"mineru-cross-page-ambiguous.v1\0{source}\0{marker_kind}\0p{index}/b0")
        for index in range(markers)
    )
    status = "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS" if markers else "NATIVE_CROSS_PAGE_FACT_ABSENT"
    facts: dict[str, object] = {
        "contract": "mineru-native-cross-page-facts.v1",
        "status": status,
        "required_capability": capability,
        "source_sha256": source,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": "2" * 64,
        "member_inventory_sha256": _sha(_compact(members)),
        "projection_sha256": "",
        "relation_count": 0,
        "ambiguous_marker_count": markers,
        "ambiguous_observation_hashes": observations,
        "members": members,
        "relations": [],
    }
    projection = {
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
    facts["projection_sha256"] = _sha(_compact(projection))
    return facts


def _rate_structure(*, pairs: int = 1, incompatible: bool = False) -> dict[str, object]:
    page_count = pairs + 1
    pages = [
        {
            "page_id": f"page-{page:04d}",
            "page_number": page,
            "content_hash": _sha(f"page-content-{page}"),
            "structure_hash": _sha(f"page-structure-{page}"),
        }
        for page in range(1, page_count + 1)
    ]
    tables: list[dict[str, object]] = []
    cells: list[dict[str, object]] = []
    for index, page in enumerate(range(1, page_count + 1)):
        table_id = f"table-{index:06d}"
        header_hash = _sha("different-header") if incompatible and index == 1 else _sha("header")
        cell_id = f"cell-{index:06d}"
        tables.append(
            {
                "table_id": table_id,
                "order_index": index,
                "page_number": page,
                "table_index": 0,
                "bbox": ["10", "20", "90", "80"],
                "content_hash": _sha(f"table-content-{index}"),
                "structure_hash": _sha(f"table-structure-{index}"),
                "row_count": 2,
                "column_count": 2,
                "header_cell_ids": [cell_id],
            }
        )
        cells.append(
            {
                "cell_id": cell_id,
                "order_index": index,
                "table_id": table_id,
                "page_number": page,
                "row_index": 0,
                "column_index": 0,
                "row_span": 2,
                "column_span": 2,
                "bbox": ["10", "20", "90", "30"],
                "content_hash": header_hash,
                "structure_hash": _sha("header-structure"),
            }
        )
    return {
        "contract": "mineru-native-structure.v1",
        "source_schema": "mineru.content-list.pipeline.v1",
        "parser_model": "pipeline",
        "source_sha256": RATE_SHA,
        "raw_sha256": RAW_HASH,
        "pages": pages,
        "blocks": [],
        "tables": tables,
        "cells": cells,
        "unsupported": ["cross_page_tables"],
    }


def _section_structure() -> dict[str, object]:
    return {
        "contract": "mineru-native-structure.v1",
        "source_schema": "mineru.content-list.pipeline.v1",
        "parser_model": "pipeline",
        "source_sha256": TERMS_SHA,
        "raw_sha256": RAW_HASH,
        "pages": [
            {
                "page_id": f"page-{page:04d}",
                "page_number": page,
                "content_hash": _sha(f"terms-page-content-{page}"),
                "structure_hash": _sha(f"terms-page-structure-{page}"),
            }
            for page in (1, 2)
        ],
        "blocks": [
            {
                "block_id": f"block-{index:06d}",
                "order_index": index,
                "page_number": page,
                "block_index": 0,
                "bbox": ["10", "20", "90", "80"],
                "content_hash": _sha(f"terms-block-content-{index}"),
                "structure_hash": _sha(f"terms-block-structure-{index}"),
            }
            for index, page in enumerate((1, 2))
        ],
        "tables": [],
        "cells": [],
        "unsupported": ["cross_page_sections"],
    }


def _capture(
    source: str,
    *,
    structure: dict[str, object] | None = None,
    markers: int = 0,
    marker_kind: str = "cross_page",
) -> bytes:
    parser = _parser()
    body = structure or {"pages": [{"page_index": 0, "blocks": []}]}
    content = "safe snapshot"
    payload: dict[str, object] = {
        "contract": "mineru-semantic-content-custody.v2",
        "source_sha256": source,
        "attempt": {"attempt_number": 2, "attempt_role": "bounded_upgrade", "generation": 0},
        "raw_structure_sha256": RAW_HASH,
        "sanitized_structure_sha256": _sha(_compact(body)),
        "sanitized_structure": body,
        "content_snapshot_sha256": _sha(content),
        "content_snapshot": content,
        "capture_identity_sha256": "",
        "parser": parser,
        "calls": {"allocation_post": 1, "upload_put": 1, "status_get": 3, "zip_get": 1},
        "latency_milliseconds": 25,
        "status": "completed",
    }
    payload["capture_identity_sha256"] = _sha(
        _compact(
            {
                "contract": payload["contract"],
                "source_sha256": source,
                "attempt": payload["attempt"],
                "parser_config_sha256": parser["config_sha256"],
                "raw_structure_sha256": RAW_HASH,
                "sanitized_structure_sha256": payload["sanitized_structure_sha256"],
                "content_snapshot_sha256": payload["content_snapshot_sha256"],
            }
        )
    )
    if source == TERMS_SHA:
        payload["cross_page_facts"] = _cross_page(
            source,
            "cross_page_sections",
            markers=markers,
            marker_kind=marker_kind,
        )
    elif source == RATE_SHA:
        payload["cross_page_facts"] = _cross_page(
            source,
            "cross_page_tables",
            markers=markers,
            marker_kind=marker_kind,
        )
    if source in {TERMS_SHA, RATE_SHA}:
        node_type = "text" if source == TERMS_SHA else "table"
        return attach_marker_envelope_108(
            payload,
            markers=tuple(
                MarkerFixtureV1(
                    marker_kind=marker_kind,
                    page_index=index,
                    structural_path=f"p{index}/b0",
                    node_type=node_type,
                    local_index=0,
                )
                for index in range(markers)
            ),
        )
    return _compact(payload) + b"\n"


def _document_manifest(
    structure: dict[str, object],
    *,
    source_sha256: str = RATE_SHA,
    relation_kind: str = "table",
) -> tuple[ParsedDocumentV1, ParseManifestV1]:
    parser = _parser()
    subject = ParseSubjectV1(
        space_id="space-596-1",
        source_id=f"source-{relation_kind}",
        source_revision_id=f"revision-{relation_kind}",
        product_version_id="596-1",
        material_profile_id=f"material-profile-{relation_kind}-596-1",
        material_profile_binding_hash="a" * 64,
        source_sha256=source_sha256,
        raw_artifact_hash=RAW_HASH,
        canonical_envelope_hash="b" * 64,
    )
    parser_identity = ParserIdentityV1(
        parser_id="mineru-cloud-pipeline",
        parser_profile_ref="approved-parser-profile:parser-neutral-bounded-upgrade.v1",
        parser_build_id="mineru-3.4.4-pipeline",
        parser_config_hash=str(parser["config_sha256"]),
    )
    attempt = ParseAttemptV1(
        attempt_id="attempt-rate-2",
        attempt_number=2,
        attempt_role="bounded_upgrade",
        generation=0,
    )
    snapshot = ParseSnapshotV1(
        snapshot_id="snapshot-rate",
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
    page_rows = cast(list[dict[str, Any]], structure["pages"])
    block_rows = cast(list[dict[str, Any]], structure["blocks"])
    table_rows = cast(list[dict[str, Any]], structure["tables"])
    cell_rows = cast(list[dict[str, Any]], structure["cells"])
    pages = tuple(
        ParsePageV1(
            page_id=str(item["page_id"]),
            order_index=index,
            locator=PageLocatorV1(page_number=int(item["page_number"])),
            content_hash=str(item["content_hash"]),
            structure_hash=str(item["structure_hash"]),
        )
        for index, item in enumerate(page_rows)
    )
    blocks = tuple(
        ParseBlockV1(
            block_id=str(item["block_id"]),
            order_index=int(item["order_index"]),
            locator=BlockLocatorV1(
                page_number=int(item["page_number"]),
                block_index=int(item["block_index"]),
                bbox=_bbox(item["bbox"]),
            ),
            content_hash=str(item["content_hash"]),
            structure_hash=str(item["structure_hash"]),
        )
        for item in block_rows
    )
    tables = tuple(
        ParseTableV1(
            table_id=str(item["table_id"]),
            order_index=int(item["order_index"]),
            locator=TableLocatorV1(
                page_number=int(item["page_number"]),
                table_index=int(item["table_index"]),
                bbox=_bbox(item["bbox"]),
            ),
            content_hash=str(item["content_hash"]),
            structure_hash=str(item["structure_hash"]),
            row_count=int(item["row_count"]),
            column_count=int(item["column_count"]),
            header_cell_ids=tuple(cast(list[str], item["header_cell_ids"])),
            continuation_table_ids=(),
        )
        for item in table_rows
    )
    cells = tuple(
        ParseCellV1(
            cell_id=str(item["cell_id"]),
            order_index=int(item["order_index"]),
            table_id=str(item["table_id"]),
            locator=CellLocatorV1(
                page_number=int(item["page_number"]),
                table_id=str(item["table_id"]),
                row_index=int(item["row_index"]),
                column_index=int(item["column_index"]),
                row_span=int(item["row_span"]),
                column_span=int(item["column_span"]),
                bbox=_bbox(item["bbox"]),
            ),
            content_hash=str(item["content_hash"]),
            structure_hash=str(item["structure_hash"]),
        )
        for item in cell_rows
    )
    table_ids = tuple(item.table_id for item in tables)
    cell_ids = tuple(item.cell_id for item in cells)
    block_ids = tuple(item.block_id for item in blocks)
    ordered_pages = CapabilityEvidenceV1(
        capability="ordered_pages",
        subject_refs=tuple(item.page_id for item in pages),
    )
    evidence = (
        (
            ordered_pages,
            CapabilityEvidenceV1(capability="table_grid", subject_refs=table_ids + cell_ids),
            CapabilityEvidenceV1(capability="cell_locators", subject_refs=cell_ids),
            CapabilityEvidenceV1(capability="row_column_indices", subject_refs=cell_ids),
            CapabilityEvidenceV1(capability="header_hierarchy", subject_refs=table_ids + cell_ids),
        )
        if relation_kind == "table"
        else (
            ordered_pages,
            CapabilityEvidenceV1(capability="block_locators", subject_refs=block_ids),
        )
    )
    relation_capability = "cross_page_tables" if relation_kind == "table" else "cross_page_sections"
    relation_refs = table_ids if relation_kind == "table" else block_ids
    unsupported = (
        UnsupportedParseFactV1(
            capability=relation_capability,
            reason_code="native_relation_not_available",
            subject_refs=relation_refs,
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
        tables=tables,
        cells=cells,
        capability_evidence=evidence,
        warnings=(),
        unsupported=unsupported,
    )
    required = (
        (
            "ordered_pages",
            "table_grid",
            "cell_locators",
            "row_column_indices",
            "header_hierarchy",
            "cross_page_tables",
        )
        if relation_kind == "table"
        else ("ordered_pages", "block_locators", "cross_page_sections")
    )
    manifest = ParseManifestV1(
        contract="parse-manifest.v1",
        subject=subject,
        parser=parser_identity,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        document_hash=document.document_hash,
        ordered_page_ids=tuple(item.page_id for item in pages),
        ordered_block_ids=block_ids,
        ordered_table_ids=table_ids,
        ordered_cell_ids=cell_ids,
        element_counts=ParseElementCountsV1(
            pages=len(pages), blocks=len(blocks), tables=len(tables), cells=len(cells)
        ),
        required_capabilities=required,
        satisfied_capabilities=required[:-1],
        unsatisfied_capabilities=(relation_capability,),
        capability_evidence=evidence,
        warnings=(),
        unsupported=unsupported,
    )
    return document, manifest


def _case(
    *, pairs: int = 1, incompatible: bool = False, markers: int = 1
) -> tuple[MinerUCaptureBundle5961V1, ParsedDocumentV1, ParseManifestV1]:
    structure = _rate_structure(pairs=pairs, incompatible=incompatible)
    bundle = intake_mineru_capture_bundle_596_1(
        (
            _capture(TERMS_SHA),
            _capture(BROCHURE_SHA),
            _capture(RATE_SHA, structure=structure, markers=markers),
        )
    )
    document, manifest = _document_manifest(structure)
    return bundle, document, manifest


def _section_case() -> tuple[MinerUCaptureBundle5961V1, ParsedDocumentV1, ParseManifestV1]:
    structure = _section_structure()
    bundle = intake_mineru_capture_bundle_596_1(
        (
            _capture(TERMS_SHA, structure=structure, markers=1),
            _capture(BROCHURE_SHA),
            _capture(RATE_SHA, markers=0),
        )
    )
    document, manifest = _document_manifest(
        structure,
        source_sha256=TERMS_SHA,
        relation_kind="section",
    )
    return bundle, document, manifest


def test_unique_structural_pair_cannot_upgrade_an_unlabelled_native_marker() -> None:
    bundle, document, manifest = _case()
    with pytest.raises(CrossPageBindingError, match="NATIVE_MARKER_KIND_UNBOUND") as caught:
        derive_cross_page_relation_596_1(
            bundle, document, manifest, preserve_marker_envelope=True
        )
    assert caught.value.status == "NOT_AVAILABLE"
    assert CrossPageRelationBindingV1.model_fields["provenance"].default == (
        "DERIVED_STRUCTURAL_RELATION"
    )


def test_future_089_typed_table_marker_closes_the_mechanical_binding() -> None:
    binding = derive_cross_page_relation_596_1(
        *_case(),
        marker_replay=_TypedMarkerAuthority(),
        preserve_marker_envelope=True,
    )

    assert binding.status == "DERIVED_STRUCTURAL_BINDING_VERIFIED"
    assert binding.provenance == "DERIVED_STRUCTURAL_RELATION"
    assert binding.relation_kind == "table"
    assert binding.source_endpoint.endpoint_id == "table-000000"
    assert binding.target_endpoint.endpoint_id == "table-000001"
    assert binding.source_endpoint.page_number == 1
    assert binding.target_endpoint.page_number == 2
    assert replay_cross_page_relation_binding_v1(binding) == binding
    serialized = binding.model_dump_json()
    assert '"status":"NATIVE' not in serialized
    assert "ADMIT" not in serialized and "READY" not in serialized


def test_unique_repeated_header_grid_derives_rate_relation_without_native_marker() -> None:
    binding = derive_cross_page_relation_596_1(
        *_case(markers=0),
        preserve_marker_envelope=True,
    )

    assert binding.status == "DERIVED_STRUCTURAL_BINDING_VERIFIED"
    assert binding.relation_kind == "table"
    assert binding.source_endpoint.endpoint_id == "table-000000"
    assert binding.target_endpoint.endpoint_id == "table-000001"
    assert binding.source_endpoint.page_number == 1
    assert binding.target_endpoint.page_number == 2
    assert replay_cross_page_relation_binding_v1(binding) == binding


def test_future_089_typed_section_marker_maps_only_real_cross_page_blocks() -> None:
    authority = _TypedMarkerAuthority(
        relation_kind="section",
        source_endpoint_id="block-000000",
        source_page_number=1,
        target_endpoint_id="block-000001",
        target_page_number=2,
    )
    binding = derive_cross_page_relation_596_1(
        *_section_case(),
        relation_kind="section",
        marker_replay=authority,
        preserve_marker_envelope=True,
    )

    assert binding.status == "DERIVED_STRUCTURAL_BINDING_VERIFIED"
    assert binding.relation_kind == "section"
    assert binding.source_endpoint.endpoint_kind == "block"
    assert binding.target_endpoint.endpoint_kind == "block"

    with pytest.raises(CrossPageBindingError):
        derive_cross_page_relation_596_1(
            *_section_case(),
            relation_kind="section",
            marker_replay=_TypedMarkerAuthority(
                relation_kind="section",
                source_endpoint_id="block-foreign",
                source_page_number=1,
                target_endpoint_id="block-000001",
                target_page_number=2,
            ),
            preserve_marker_envelope=True,
        )


@pytest.mark.parametrize(
    "authority",
    [
        _TypedMarkerAuthority(marker_kind="lines_deleted"),
        _TypedMarkerAuthority(source_endpoint_id="table-foreign"),
        _TypedMarkerAuthority(source_page_number=2),
        _TypedMarkerAuthority(target_page_number=3),
        _TypedMarkerAuthority(marker_structural_path="p9/b0"),
        _TypedMarkerAuthority(mutation={"request_digest_sha256": "0" * 64}),
    ],
)
def test_future_marker_kind_path_page_hash_and_endpoint_drift_fail_closed(
    authority: _TypedMarkerAuthority,
) -> None:
    with pytest.raises(CrossPageBindingError):
        derive_cross_page_relation_596_1(
            *_case(), marker_replay=authority, preserve_marker_envelope=True
        )


def test_section_and_incompatible_table_facts_are_not_available() -> None:
    bundle, document, manifest = _case()
    with pytest.raises(
        CrossPageBindingError,
        match="SECTION_ENDPOINT_PROOF_NOT_AVAILABLE",
    ) as section:
        derive_cross_page_relation_596_1(
            bundle,
            document,
            manifest,
            relation_kind="section",
            preserve_marker_envelope=True,
        )
    assert section.value.status == "NOT_AVAILABLE"
    with pytest.raises(CrossPageBindingError) as caught:
        derive_cross_page_relation_596_1(
            *_case(incompatible=True), preserve_marker_envelope=True
        )
    assert caught.value.status == "NOT_AVAILABLE"


def test_multiple_markers_or_compatible_pairs_block_zero_binding() -> None:
    for case in (_case(markers=2), _case(pairs=2)):
        with pytest.raises(CrossPageBindingError) as caught:
            derive_cross_page_relation_596_1(*case, preserve_marker_envelope=True)
        assert caught.value.status == "BLOCKED"


def test_typed_lines_deleted_marker_cannot_impersonate_cross_page() -> None:
    structure = _rate_structure()
    bundle = intake_mineru_capture_bundle_596_1(
        (
            _capture(TERMS_SHA),
            _capture(BROCHURE_SHA),
            _capture(
                RATE_SHA,
                structure=structure,
                markers=1,
                marker_kind="lines_deleted",
            ),
        )
    )
    document, manifest = _document_manifest(structure)
    with pytest.raises(CrossPageBindingError, match="TYPED_MARKER_REPLAY_INVALID"):
        derive_cross_page_relation_596_1(
            bundle,
            document,
            manifest,
            marker_replay=_TypedMarkerAuthority(marker_kind="lines_deleted"),
            preserve_marker_envelope=True,
        )


def test_input_artifact_parser_manifest_and_model_construct_drift_fail_closed() -> None:
    bundle, document, manifest = _case()
    corruptions = (
        (bundle.model_copy(update={"bundle_digest_sha256": "0" * 64}), document, manifest),
        (
            bundle,
            document.model_copy(
                update={
                    "parser": document.parser.model_copy(update={"parser_config_hash": "0" * 64})
                }
            ),
            manifest,
        ),
        (bundle, document, manifest.model_copy(update={"document_hash": "0" * 64})),
        (bundle, document.model_copy(update={"tables": ()}), manifest),
    )
    for args in corruptions:
        with pytest.raises(CrossPageBindingError) as caught:
            derive_cross_page_relation_596_1(*args, preserve_marker_envelope=True)
        assert caught.value.status == "BLOCKED"


def test_caller_constructed_binding_cannot_bypass_replay() -> None:
    forged = CrossPageRelationBindingV1.model_construct(
        contract="cross-page-relation-binding.v1",
        provenance="DERIVED_STRUCTURAL_RELATION",
        relation_kind="table",
        source_sha256="0" * 64,
        replay_digest_sha256="0" * 64,
    )
    with pytest.raises(CrossPageBindingError):
        replay_cross_page_relation_binding_v1(forged)


def test_error_and_dto_representations_contain_no_capture_body() -> None:
    bundle, document, manifest = _case(incompatible=True)
    with pytest.raises(CrossPageBindingError) as caught:
        derive_cross_page_relation_596_1(
            bundle, document, manifest, preserve_marker_envelope=True
        )
    assert "safe snapshot" not in repr(caught.value)
    assert "safe snapshot" not in str(caught.value)
    assert "safe snapshot" not in repr(bundle)
    assert CrossPageRelationBindingV1.model_fields["provenance"].default == (
        "DERIVED_STRUCTURAL_RELATION"
    )
