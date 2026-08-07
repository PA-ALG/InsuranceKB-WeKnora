"""OpenSpec102 marker-preserving 086 intake replay compatibility."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any, cast

import pytest

import insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 as binding_module
from insurance_harness.compiler.parsed_documents import (
    CapabilityEvidenceV1,
    CellLocatorV1,
    PageLocatorV1,
    ParseAttemptV1,
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
from insurance_harness.knowledge_compiler.marker_endpoint_pair_bridge_596_1 import (
    MarkerEndpointPairBridgeError,
    derive_marker_endpoint_pair_input_596_1,
)
from insurance_harness.knowledge_compiler.marker_preserving_intake_replay_596_1 import (
    derive_marker_preserving_rate_entry_596_1,
)
from insurance_harness.knowledge_compiler.mineru_capture_intake_596_1 import (
    MinerUCaptureBundle5961V1,
    intake_mineru_capture_bundle_596_1,
)
from insurance_harness.knowledge_compiler.mineru_cross_page_binding_596_1 import (
    CrossPageBindingError,
    derive_cross_page_relation_596_1,
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


def _go_path(source: str, path: str) -> str:
    return _sha(f"mineru-cross-page-marker-path.v1\0{source}\0{NATIVE_MEMBER}\0{path}")


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


def _structure(*, pages: int = 2, header: str = "header") -> dict[str, object]:
    page_rows = [
        {
            "page_id": f"page-{page:04d}",
            "page_number": page,
            "content_hash": _sha(f"page-content-{page}"),
            "structure_hash": _sha(f"page-structure-{page}"),
        }
        for page in range(1, pages + 1)
    ]
    tables: list[dict[str, object]] = []
    cells: list[dict[str, object]] = []
    for index, page in enumerate(range(1, pages + 1)):
        table_id = f"table-{index:06d}"
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
                "row_span": 1,
                "column_span": 2,
                "bbox": ["10", "20", "90", "30"],
                "content_hash": _sha(header),
                "structure_hash": _sha("header-structure"),
            }
        )
    return {
        "contract": "mineru-native-structure.v1",
        "source_schema": "mineru.content-list.pipeline.v1",
        "parser_model": "pipeline",
        "source_sha256": RATE_SHA,
        "raw_sha256": RAW_HASH,
        "pages": page_rows,
        "blocks": [],
        "tables": tables,
        "cells": cells,
        "unsupported": ["cross_page_tables"],
    }


def _cross_page(source: str, paths: tuple[tuple[str, str], ...]) -> dict[str, object]:
    members = [{"category": "middle_json", "size": 17, "sha256": "3" * 64}]
    observations = sorted(
        _sha(f"mineru-cross-page-ambiguous.v1\0{source}\0{kind}\0{path}") for kind, path in paths
    )
    value: dict[str, object] = {
        "contract": "mineru-native-cross-page-facts.v1",
        "status": "NATIVE_CROSS_PAGE_FACT_AMBIGUOUS",
        "required_capability": "cross_page_tables",
        "source_sha256": source,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": NATIVE_MEMBER,
        "member_inventory_sha256": _sha(_compact(members)),
        "projection_sha256": "",
        "relation_count": 0,
        "ambiguous_marker_count": len(paths),
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


def _marker(source: str, paths: tuple[tuple[str, str], ...]) -> dict[str, object]:
    markers: list[dict[str, object]] = []
    for kind, path in paths:
        parts = path.split("/")
        item: dict[str, object] = {
            "marker_kind": kind,
            "page_index": int(parts[0][1:]),
            "structural_path": path,
            "structural_path_sha256": _go_path(source, path),
            "node_type": "table",
            "local_index": int(parts[-1].removeprefix("b")),
            "marker_sha256": "",
        }
        item["marker_sha256"] = _domain(
            "mineru-cross-page-marker-evidence.v1",
            {
                "contract": "mineru-native-cross-page-marker-provenance.v1",
                "source_sha256": source,
                "parser_model": "pipeline",
                "mineru_version": "3.4.4",
                "native_member_sha256": NATIVE_MEMBER,
                **{
                    key: item[key]
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
        markers.append(item)
    markers.sort(
        key=lambda item: (
            cast(int, item["page_index"]),
            cast(str, item["structural_path_sha256"]),
            cast(str, item["marker_kind"]),
        )
    )
    value: dict[str, object] = {
        "contract": "mineru-native-cross-page-marker-provenance.v1",
        "source_sha256": source,
        "parser_model": "pipeline",
        "mineru_version": "3.4.4",
        "raw_zip_sha256": "1" * 64,
        "native_member_sha256": NATIVE_MEMBER,
        "marker_count": len(markers),
        "markers": markers,
    }
    value["replay_digest_sha256"] = _domain("mineru-cross-page-marker-provenance-replay.v1", value)
    return value


def _capture(
    source: str,
    *,
    structure: dict[str, object] | None = None,
    markers: tuple[tuple[str, str], ...] = (),
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
    if source == RATE_SHA:
        facts = _cross_page(source, markers)
        marker = _marker(source, markers)
        payload["cross_page_facts"] = facts
        payload["cross_page_marker_provenance"] = marker
    elif source == TERMS_SHA:
        # Terms is required by 083 but intentionally has a native-absent
        # envelope; 098 only derives the rate-table input.
        facts = _cross_page(source, ())
        facts["required_capability"] = "cross_page_sections"
        facts["status"] = "NATIVE_CROSS_PAGE_FACT_ABSENT"
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
        payload["cross_page_facts"] = facts
        payload["cross_page_marker_provenance"] = _marker(source, ())
    capture = {
        "contract": payload["contract"],
        "source_sha256": source,
        "attempt": payload["attempt"],
        "parser_config_sha256": parser["config_sha256"],
        "raw_structure_sha256": RAW_HASH,
        "sanitized_structure_sha256": payload["sanitized_structure_sha256"],
        "content_snapshot_sha256": payload["content_snapshot_sha256"],
    }
    if source != BROCHURE_SHA:
        facts = cast(dict[str, object], payload["cross_page_facts"])
        marker = cast(dict[str, object], payload["cross_page_marker_provenance"])
        capture["cross_page_projection_sha256"] = facts["projection_sha256"]
        capture["marker_provenance_replay_sha256"] = marker["replay_digest_sha256"]
    payload["capture_identity_sha256"] = _sha(_compact(capture))
    return _compact(payload) + b"\n"


def _bbox(value: object) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    row = cast(list[str], value)
    return tuple(Decimal(item) for item in row)  # type: ignore[return-value]


def _document_manifest(
    structure: dict[str, object],
) -> tuple[ParsedDocumentV1, ParseManifestV1]:
    parser = _parser()
    subject = ParseSubjectV1(
        space_id="space-596-1",
        source_id="source-rate",
        source_revision_id="revision-rate",
        product_version_id="596-1",
        material_profile_id="material-profile-rate-596-1",
        material_profile_binding_hash="a" * 64,
        source_sha256=RATE_SHA,
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
    table_rows = cast(list[dict[str, Any]], structure["tables"])
    cell_rows = cast(list[dict[str, Any]], structure["cells"])
    pages = tuple(
        ParsePageV1(
            page_id=cast(str, row["page_id"]),
            order_index=index,
            locator=PageLocatorV1(page_number=cast(int, row["page_number"])),
            content_hash=cast(str, row["content_hash"]),
            structure_hash=cast(str, row["structure_hash"]),
        )
        for index, row in enumerate(page_rows)
    )
    tables = tuple(
        ParseTableV1(
            table_id=cast(str, row["table_id"]),
            order_index=cast(int, row["order_index"]),
            locator=TableLocatorV1(
                page_number=cast(int, row["page_number"]),
                table_index=cast(int, row["table_index"]),
                bbox=_bbox(row["bbox"]),
            ),
            content_hash=cast(str, row["content_hash"]),
            structure_hash=cast(str, row["structure_hash"]),
            row_count=cast(int, row["row_count"]),
            column_count=cast(int, row["column_count"]),
            header_cell_ids=tuple(cast(list[str], row["header_cell_ids"])),
            continuation_table_ids=(),
        )
        for row in table_rows
    )
    cells = tuple(
        ParseCellV1(
            cell_id=cast(str, row["cell_id"]),
            order_index=cast(int, row["order_index"]),
            table_id=cast(str, row["table_id"]),
            locator=CellLocatorV1(
                page_number=cast(int, row["page_number"]),
                table_id=cast(str, row["table_id"]),
                row_index=cast(int, row["row_index"]),
                column_index=cast(int, row["column_index"]),
                row_span=cast(int, row["row_span"]),
                column_span=cast(int, row["column_span"]),
                bbox=_bbox(row["bbox"]),
            ),
            content_hash=cast(str, row["content_hash"]),
            structure_hash=cast(str, row["structure_hash"]),
        )
        for row in cell_rows
    )
    table_ids = tuple(table.table_id for table in tables)
    cell_ids = tuple(cell.cell_id for cell in cells)
    evidence = (
        CapabilityEvidenceV1(
            capability="ordered_pages", subject_refs=tuple(page.page_id for page in pages)
        ),
        CapabilityEvidenceV1(capability="table_grid", subject_refs=table_ids + cell_ids),
        CapabilityEvidenceV1(capability="cell_locators", subject_refs=cell_ids),
        CapabilityEvidenceV1(capability="row_column_indices", subject_refs=cell_ids),
        CapabilityEvidenceV1(capability="header_hierarchy", subject_refs=table_ids + cell_ids),
    )
    unsupported = (
        UnsupportedParseFactV1(
            capability="cross_page_tables",
            reason_code="native_relation_not_available",
            subject_refs=table_ids,
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
        blocks=(),
        tables=tables,
        cells=cells,
        capability_evidence=evidence,
        warnings=(),
        unsupported=unsupported,
    )
    required = (
        "ordered_pages",
        "table_grid",
        "cell_locators",
        "row_column_indices",
        "header_hierarchy",
        "cross_page_tables",
    )
    manifest = ParseManifestV1(
        contract="parse-manifest.v1",
        subject=subject,
        parser=parser_identity,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        document_hash=document.document_hash,
        ordered_page_ids=tuple(page.page_id for page in pages),
        ordered_block_ids=(),
        ordered_table_ids=table_ids,
        ordered_cell_ids=cell_ids,
        element_counts=ParseElementCountsV1(
            pages=len(pages), blocks=0, tables=len(tables), cells=len(cells)
        ),
        required_capabilities=required,
        satisfied_capabilities=required[:-1],
        unsatisfied_capabilities=("cross_page_tables",),
        capability_evidence=evidence,
        warnings=(),
        unsupported=unsupported,
    )
    return document, manifest


def _case(
    *,
    structure: dict[str, object] | None = None,
    markers: tuple[tuple[str, str], ...] = (("cross_page", "p0/b0"),),
) -> tuple[MinerUCaptureBundle5961V1, ParsedDocumentV1, ParseManifestV1]:
    native = structure or _structure()
    bundle = intake_mineru_capture_bundle_596_1(
        (
            _capture(TERMS_SHA),
            _capture(BROCHURE_SHA),
            _capture(RATE_SHA, structure=native, markers=markers),
        )
    )
    document, manifest = _document_manifest(native)
    return bundle, document, manifest



def test_marker_drop_red_and_preserving_seam_reaches_096_entry() -> None:
    bundle, document, manifest = _case()
    pair = derive_marker_endpoint_pair_input_596_1(bundle, document, manifest)

    with pytest.raises(CrossPageBindingError, match="INTAKE_REPLAY_FAILED"):
        derive_cross_page_relation_596_1(bundle, document, manifest, marker_replay=pair)

    entry = derive_marker_preserving_rate_entry_596_1(
        bundle, document, manifest, pair
    )
    assert entry.receipt_role == "rate_table"
    assert entry.binding.status == "DERIVED_STRUCTURAL_BINDING_VERIFIED"
    assert entry.binding.intake_bundle_digest_sha256 == bundle.bundle_digest_sha256
    assert entry.marker_provenance_digest_sha256 == (
        bundle.sources[2].marker_provenance_digest_sha256
    )
    rendered = entry.model_dump_json()
    assert "ADMIT" not in rendered
    assert "READY" not in rendered
    assert '"provenance":"NATIVE' not in rendered


def test_opt_in_replays_exact_single_and_multiple_marker_envelopes() -> None:
    single, _, _ = _case()
    replayed = binding_module._replay_intake(  # noqa: SLF001
        single, preserve_marker_envelope=True
    )
    assert replayed == single
    rate_marker = single.sources[2].evidence.cross_page_marker_provenance
    assert rate_marker is not None
    preserved = json.loads(
        binding_module._compact_capture(  # noqa: SLF001
            single.sources[2].evidence, preserve_marker_envelope=True
        )
    )["cross_page_marker_provenance"]
    assert preserved == rate_marker.model_dump(mode="json")
    assert "cross_page_marker_provenance" not in json.loads(
        binding_module._compact_capture(single.sources[2].evidence)  # noqa: SLF001
    )

    multiple, _, _ = _case(
        markers=(("cross_page", "p0/b0"), ("lines_deleted", "p1/b0"))
    )
    assert binding_module._replay_intake(  # noqa: SLF001
        multiple, preserve_marker_envelope=True
    ) == multiple
    with pytest.raises(MarkerEndpointPairBridgeError, match="LINES_DELETED"):
        derive_marker_endpoint_pair_input_596_1(*_case(
            markers=(("cross_page", "p0/b0"), ("lines_deleted", "p1/b0"))
        ))


def test_marker_duplicate_order_unknown_and_identity_drift_fail_closed() -> None:
    bundle, document, manifest = _case()
    pair = derive_marker_endpoint_pair_input_596_1(bundle, document, manifest)
    rate = bundle.sources[2]
    provenance = rate.evidence.cross_page_marker_provenance
    assert provenance is not None
    marker = provenance.markers[0]

    changed_markers = (
        (marker, marker),
        (marker.model_copy(update={"marker_kind": "unknown"}),),
        (marker.model_copy(update={"node_type": "section"}),),
        (marker.model_copy(update={"local_index": 1}),),
        (marker.model_copy(update={"structural_path_sha256": "0" * 64}),),
    )
    for markers in changed_markers:
        changed_provenance = provenance.model_copy(
            update={"marker_count": len(markers), "markers": markers}
        )
        changed_evidence = rate.evidence.model_copy(
            update={"cross_page_marker_provenance": changed_provenance}
        )
        changed_rate = rate.model_copy(update={"evidence": changed_evidence})
        changed_bundle = bundle.model_copy(
            update={"sources": (bundle.sources[0], bundle.sources[1], changed_rate)}
        )
        with pytest.raises((CrossPageBindingError, ValueError)):
            derive_marker_preserving_rate_entry_596_1(
                changed_bundle, document, manifest, pair
            )

    for field, value in (
        ("source_sha256", "0" * 64),
        ("raw_zip_sha256", "0" * 64),
        ("native_member_sha256", "0" * 64),
        ("parser_model", "drift"),
        ("mineru_version", "0.0.0"),
    ):
        changed_provenance = provenance.model_copy(update={field: value})
        changed_evidence = rate.evidence.model_copy(
            update={"cross_page_marker_provenance": changed_provenance}
        )
        changed_rate = rate.model_copy(update={"evidence": changed_evidence})
        changed_bundle = bundle.model_copy(
            update={"sources": (bundle.sources[0], bundle.sources[1], changed_rate)}
        )
        with pytest.raises((CrossPageBindingError, ValueError)):
            derive_marker_preserving_rate_entry_596_1(
                changed_bundle, document, manifest, pair
            )

    ordered, _, _ = _case(
        markers=(("cross_page", "p0/b0"), ("lines_deleted", "p1/b0"))
    )
    ordered_rate = ordered.sources[2]
    ordered_provenance = ordered_rate.evidence.cross_page_marker_provenance
    assert ordered_provenance is not None
    reversed_provenance = ordered_provenance.model_copy(
        update={"markers": tuple(reversed(ordered_provenance.markers))}
    )
    reversed_evidence = ordered_rate.evidence.model_copy(
        update={"cross_page_marker_provenance": reversed_provenance}
    )
    reversed_rate = ordered_rate.model_copy(update={"evidence": reversed_evidence})
    reversed_bundle = ordered.model_copy(
        update={"sources": (ordered.sources[0], ordered.sources[1], reversed_rate)}
    )
    with pytest.raises(CrossPageBindingError, match="INTAKE_REPLAY_FAILED"):
        binding_module._replay_intake(  # noqa: SLF001
            reversed_bundle, preserve_marker_envelope=True
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_sha256", "0" * 64),
        ("raw_zip_sha256", "0" * 64),
        ("native_member_sha256", "0" * 64),
        ("parser_model", "drift"),
        ("mineru_version", "0.0.0"),
        ("marker_structural_path", "p9/b9"),
        ("marker_evidence_sha256", "0" * 64),
        ("marker_provenance_replay_sha256", "0" * 64),
    ],
)
def test_endpoint_pair_custody_drift_is_recomputed(
    field: str, value: object
) -> None:
    bundle, document, manifest = _case()
    pair = derive_marker_endpoint_pair_input_596_1(bundle, document, manifest)
    forged = pair.model_copy(update={field: value})
    with pytest.raises(ValueError):
        derive_marker_preserving_rate_entry_596_1(
            bundle, document, manifest, forged
        )


def test_legacy_no_marker_is_not_auto_filled() -> None:
    bundle, _, _ = _case()
    brochure = bundle.sources[1].evidence
    assert binding_module._compact_capture(  # noqa: SLF001
        brochure, preserve_marker_envelope=True
    ) == binding_module._compact_capture(brochure)  # noqa: SLF001

    terms = bundle.sources[0]
    missing = terms.evidence.model_copy(
        update={"cross_page_marker_provenance": None}
    )
    missing_item = terms.model_copy(update={"evidence": missing})
    missing_bundle = bundle.model_copy(
        update={"sources": (missing_item, bundle.sources[1], bundle.sources[2])}
    )
    with pytest.raises(CrossPageBindingError, match="INTAKE_REPLAY_FAILED"):
        binding_module._replay_intake(  # noqa: SLF001
            missing_bundle, preserve_marker_envelope=True
        )


def test_section_and_current_lines_deleted_remain_unavailable() -> None:
    with pytest.raises(
        MarkerEndpointPairBridgeError, match="SECTION_ENDPOINT_RULE_NOT_AVAILABLE"
    ) as section:
        derive_marker_endpoint_pair_input_596_1(*_case(), relation_kind="section")
    assert section.value.status == "NOT_AVAILABLE"

    with pytest.raises(
        MarkerEndpointPairBridgeError, match="LINES_DELETED_NOT_RELATION_AUTHORITY"
    ) as lines:
        derive_marker_endpoint_pair_input_596_1(
            *_case(markers=(("cross_page", "p0/b0"), ("lines_deleted", "p1/b0")))
        )
    assert lines.value.status == "BLOCKED"
