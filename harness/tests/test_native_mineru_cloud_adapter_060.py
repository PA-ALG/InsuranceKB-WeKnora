"""OpenSpec 060: sanitized MinerU native structure bridges only through 053."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.compiler.material_profiles import (
    MaterialProfileResolution,
    MaterialProfileResolutionRequest,
    load_material_profile_catalog_data,
    resolve_material_profile,
)
from insurance_harness.compiler.native_mineru_cloud import (
    NativeMinerUStructureError,
    build_mineru_parsed_document_v1,
)
from insurance_harness.compiler.parsed_documents import (
    ParseAttemptV1,
    ParseOutputFactsV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
)
from insurance_harness.template_packages import (
    EvidencePolicy,
    FieldGroup,
    ProvenanceReceipt,
    TemplateApproval,
    TemplateCatalogEntry,
    TemplatePackageContent,
    TemplateScope,
    TemplateVersion,
    ValidatorRef,
)

CATALOG_FIXTURE = Path(__file__).parent / "fixtures/material_profile_596_1_052.json"
UPGRADE_PARSER = "approved-parser-profile:parser-neutral-bounded-upgrade.v1"
CONFIG_HASH = "a" * 64
RAW_HASH = "b" * 64


class _OneEntryTemplateCatalog:
    def __init__(self, entry: TemplateCatalogEntry) -> None:
        self._entry = entry

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        return self._entry if scope == self._entry.version.scope else None


def _resolution(
    required_parse_capabilities: list[str] | None = None,
) -> MaterialProfileResolution:
    raw = json.loads(CATALOG_FIXTURE.read_text(encoding="utf-8"))
    rate_profile = raw["profiles"][2]
    rate_profile["required_parse_capabilities"] = (
        required_parse_capabilities
        if required_parse_capabilities is not None
        else [
            "ordered_pages",
            "block_locators",
            "table_grid",
            "cell_locators",
            "row_column_indices",
            "merged_cells",
            "header_hierarchy",
        ]
    )
    catalog = load_material_profile_catalog_data(raw)
    profile = catalog.profiles[2]
    scope = TemplateScope(space_id="space-060", level="global")
    content = TemplatePackageContent(
        schema_version=catalog.schema_binding.schema_version,
        field_groups=(
            FieldGroup(
                group_id="group-060",
                field_ids=(catalog.schema_binding.field_ids[0],),
                evidence_roles=("rate_table",),
            ),
        ),
        role_prompts={"extract": "extract-060"},
        validators=(
            ValidatorRef(
                validator_id="validator-060",
                validator_version="v1",
                config_hash="1" * 64,
            ),
        ),
        evidence_policy=EvidencePolicy(
            require_quote=True,
            require_locator=True,
            minimum_sources=1,
        ),
        attempt_limits={"extract": 1},
        golden_slice_ref="gs-s0q-596-v1",
        provenance=(
                ProvenanceReceipt(
                    migration_id="MIG-060-test",
                    source_repository="silvielala412-lab/LLM-wiki-black",
                    source_branch="feature/product-catalog-domain",
                    source_commit="6a8a1d98de405b6a2837090ee2d43769b4c89be7",
                    source_path="frontend/src/lib/product-catalog-modules.ts",
                    source_language="typescript",
                    rights_status="project-owned",
                    accepted_behavior="approved 060 test template binding",
                    rejected_behavior="caller-selected parser authority",
                python_target=(
                    "harness/src/insurance_harness/compiler/native_mineru_cloud.py"
                ),
                    translation_method="behavior_port_with_characterization_tests",
                characterization_tests=(
                    "harness/tests/test_native_mineru_cloud_adapter_060.py",
                ),
            ),
        ),
    )
    version = TemplateVersion.from_content(
        package_id="life-template-package",
        version_id="060-test-v1",
        scope=scope,
        content=content,
    )
    template_catalog = _OneEntryTemplateCatalog(
        TemplateCatalogEntry(
            version=version,
            approval=TemplateApproval(
                approval_id="approval-060",
                package_id=version.package_id,
                version_id=version.version_id,
                scope=scope,
                content_hash=version.content_hash,
                state="approved",
            ),
        )
    )
    return resolve_material_profile(
        catalog,
        template_catalog,
        MaterialProfileResolutionRequest(
            space_id="space-060",
            product_code=catalog.product.product_code,
            product_version=catalog.product.product_version,
            schema_version=catalog.schema_binding.schema_version,
            schema_field_ids=catalog.schema_binding.field_ids,
            source=profile.source,
            classified_material_role="rate_table",
        ),
    )


def _sidecar(source_sha256: str) -> bytes:
    def digest(label: str) -> str:
        return hashlib.sha256(label.encode()).hexdigest()

    payload: dict[str, Any] = {
        "contract": "mineru-native-structure.v1",
        "source_schema": "mineru.content-list.pipeline.v1",
        "parser_model": "pipeline",
        "source_sha256": source_sha256,
        "raw_sha256": RAW_HASH,
        "pages": [
            {
                "page_id": "page-0001",
                "page_number": 1,
                "content_hash": digest("page-content"),
                "structure_hash": digest("page-structure"),
            }
        ],
        "blocks": [
            {
                "block_id": "block-000000",
                "order_index": 0,
                "page_number": 1,
                "block_index": 0,
                "bbox": ["20", "30", "800", "110"],
                "content_hash": digest("block-content"),
                "structure_hash": digest("block-structure"),
            }
        ],
        "tables": [
            {
                "table_id": "table-000000",
                "order_index": 0,
                "page_number": 1,
                "table_index": 0,
                "bbox": ["30", "140", "900", "700"],
                "content_hash": digest("table-content"),
                "structure_hash": digest("table-structure"),
                "row_count": 2,
                "column_count": 3,
                "header_cell_ids": ["cell-000000"],
            }
        ],
        "cells": [
            {
                "cell_id": "cell-000000",
                "order_index": 0,
                "table_id": "table-000000",
                "page_number": 1,
                "row_index": 0,
                "column_index": 0,
                "row_span": 2,
                "column_span": 1,
                "bbox": ["30", "140", "900", "700"],
                "content_hash": digest("cell-a"),
                "structure_hash": digest("cell-a-structure"),
            },
            {
                "cell_id": "cell-000001",
                "order_index": 1,
                "table_id": "table-000000",
                "page_number": 1,
                "row_index": 0,
                "column_index": 1,
                "row_span": 1,
                "column_span": 2,
                "bbox": ["30", "140", "900", "700"],
                "content_hash": digest("cell-b"),
                "structure_hash": digest("cell-b-structure"),
            },
            {
                "cell_id": "cell-000002",
                "order_index": 2,
                "table_id": "table-000000",
                "page_number": 1,
                "row_index": 1,
                "column_index": 1,
                "row_span": 1,
                "column_span": 1,
                "bbox": ["30", "140", "900", "700"],
                "content_hash": digest("cell-c"),
                "structure_hash": digest("cell-c-structure"),
            },
            {
                "cell_id": "cell-000003",
                "order_index": 3,
                "table_id": "table-000000",
                "page_number": 1,
                "row_index": 1,
                "column_index": 2,
                "row_span": 1,
                "column_span": 1,
                "bbox": ["30", "140", "900", "700"],
                "content_hash": digest("cell-d"),
                "structure_hash": digest("cell-d-structure"),
            },
        ],
        "unsupported": ["cross_page_sections", "cross_page_tables"],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _context(
    required_parse_capabilities: list[str] | None = None,
) -> tuple[
    ParseSubjectV1,
    ParserIdentityV1,
    ParseAttemptV1,
    ParseSnapshotV1,
    ParseOutputFactsV1,
    MaterialProfileResolution,
]:
    resolution = _resolution(required_parse_capabilities)
    subject = ParseSubjectV1(
        space_id="space-060",
        source_id="source-060",
        source_revision_id="revision-060",
        product_version_id=resolution.request.product_version,
        material_profile_id=resolution.profile.profile_id,
        material_profile_binding_hash=resolution.binding_hash,
        source_sha256=resolution.profile.source.sha256,
        raw_artifact_hash=RAW_HASH,
        canonical_envelope_hash="d" * 64,
    )
    return (
        subject,
        ParserIdentityV1(
            parser_id="mineru-cloud-pipeline",
            parser_profile_ref=UPGRADE_PARSER,
            parser_build_id="mineru-pipeline-test-build",
            parser_config_hash=CONFIG_HASH,
        ),
        ParseAttemptV1(
            attempt_id="attempt-060",
            attempt_number=2,
            attempt_role="bounded_upgrade",
            generation=1,
        ),
        ParseSnapshotV1(
            snapshot_id="snapshot-060",
            snapshot_generation=1,
            pagination_complete=True,
            concurrent_mutation_fence_hash="e" * 64,
        ),
        ParseOutputFactsV1(
            privacy_policy_ref=resolution.parse_policy_receipt.privacy_policy_ref,
            output_policy_ref=resolution.parse_policy_receipt.output_policy_ref,
            body_text_included=False,
            secrets_included=False,
            absolute_paths_included=False,
            unknown_vendor_fields_included=False,
        ),
        resolution,
    )


def test_native_mineru_sidecar_reaches_only_the_053_bounded_gate() -> None:
    subject, parser, attempt, snapshot, output, resolution = _context()
    sidecar = _sidecar(subject.source_sha256)
    document, manifest, decision = build_mineru_parsed_document_v1(
        sidecar,
        expected_raw_sha256=RAW_HASH,
        expected_sanitized_sha256=hashlib.sha256(sidecar).hexdigest(),
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        material_profile_resolution=resolution,
    )

    assert document.contract == "parsed-document.v1"
    assert len(document.pages) == 1
    assert len(document.blocks) == 1
    assert len(document.tables) == 1


def test_native_mineru_unique_span_fragment_is_audited_without_erasing_proven_grid() -> None:
    subject, parser, attempt, snapshot, output, resolution = _context()
    payload = json.loads(_sidecar(subject.source_sha256))
    payload["unsupported"].append("table_cell_fragment_merged_to_unique_span")
    sidecar = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    document, manifest, decision = build_mineru_parsed_document_v1(
        sidecar,
        expected_raw_sha256=RAW_HASH,
        expected_sanitized_sha256=hashlib.sha256(sidecar).hexdigest(),
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        material_profile_resolution=resolution,
    )

    assert decision.decision == "ADMIT"
    assert "table_grid" in manifest.satisfied_capabilities
    assert any(
        item.warning_code == "table_cell_fragment_merged_to_unique_span"
        for item in document.warnings
    )
    assert any(
        item.capability == "table_cell_fragment_merged_to_unique_span"
        for item in document.unsupported
    )
    assert len(document.cells) == 4
    assert document.cells[0].locator.row_span == 2
    assert document.cells[1].locator.column_span == 2
    assert manifest.manifest_hash == decision.manifest_hash
    assert decision.decision == "ADMIT"
    assert decision.admitted_attempt_id == attempt.attempt_id


def test_native_mineru_sidecar_fails_closed_on_missing_or_malformed_structure() -> None:
    subject, parser, attempt, snapshot, output, resolution = _context()
    unsafe_payloads = (
        b"# markdown is not native structure",
        b'{"contract":"mineru-native-structure.v1","pages":[]}',
        _sidecar(subject.source_sha256).replace(b'"row_span":2', b'"row_span":0'),
    )
    for payload in unsafe_payloads:
        with pytest.raises(NativeMinerUStructureError):
            build_mineru_parsed_document_v1(
                payload,
                expected_raw_sha256=RAW_HASH,
                expected_sanitized_sha256=hashlib.sha256(payload).hexdigest(),
                subject=subject,
                parser=parser,
                attempt=attempt,
                snapshot=snapshot,
                output_facts=output,
                material_profile_resolution=resolution,
            )

    sidecar = _sidecar(subject.source_sha256)
    with pytest.raises(
        NativeMinerUStructureError, match="sanitized_structure_digest_mismatch"
    ):
        build_mineru_parsed_document_v1(
            sidecar,
            expected_raw_sha256=RAW_HASH,
            expected_sanitized_sha256="f" * 64,
            subject=subject,
            parser=parser,
            attempt=attempt,
            snapshot=snapshot,
            output_facts=output,
            material_profile_resolution=resolution,
        )


def test_native_mineru_sidecar_binds_the_raw_artifact_to_the_subject() -> None:
    subject, parser, attempt, snapshot, output, resolution = _context()
    sidecar = _sidecar(subject.source_sha256)
    mismatched_subject = subject.model_copy(update={"raw_artifact_hash": "c" * 64})
    with pytest.raises(NativeMinerUStructureError, match="native_artifact_digest_mismatch"):
        build_mineru_parsed_document_v1(
            sidecar,
            expected_raw_sha256=RAW_HASH,
            expected_sanitized_sha256=hashlib.sha256(sidecar).hexdigest(),
            subject=mismatched_subject,
            parser=parser,
            attempt=attempt,
            snapshot=snapshot,
            output_facts=output,
            material_profile_resolution=resolution,
        )


@pytest.mark.parametrize(
    ("mutate", "reason"),
    (
        (
            lambda payload: payload["blocks"][0].update({"page_number": 2}),
            "invalid_native_relationship",
        ),
        (
            lambda payload: payload["cells"][0].update(
                {"bbox": ["31", "140", "900", "700"]}
            ),
            "invalid_native_relationship",
        ),
        (
            lambda payload: payload["cells"][2].update({"column_index": 2}),
            "invalid_native_relationship",
        ),
        (
            lambda payload: payload["tables"][0].update(
                {"header_cell_ids": ["unknown-cell"]}
            ),
            "invalid_native_relationship",
        ),
    ),
)
def test_native_mineru_sidecar_revalidates_relationships(
    mutate: Any, reason: str
) -> None:
    subject, parser, attempt, snapshot, output, resolution = _context()
    payload = json.loads(_sidecar(subject.source_sha256))
    mutate(payload)
    sidecar = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(NativeMinerUStructureError, match=reason):
        build_mineru_parsed_document_v1(
            sidecar,
            expected_raw_sha256=RAW_HASH,
            expected_sanitized_sha256=hashlib.sha256(sidecar).hexdigest(),
            subject=subject,
            parser=parser,
            attempt=attempt,
            snapshot=snapshot,
            output_facts=output,
            material_profile_resolution=resolution,
        )


def test_native_mineru_unproven_table_grid_reaches_053_block_and_review() -> None:
    subject, parser, attempt, snapshot, output, resolution = _context()
    payload = json.loads(_sidecar(subject.source_sha256))
    payload["tables"] = []
    payload["cells"] = []
    payload["unsupported"] = [
        "table_grid",
        "cell_locators",
        "row_column_indices",
        "merged_cells",
        "header_hierarchy",
        "cross_page_sections",
        "cross_page_tables",
    ]
    sidecar = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    document, manifest, decision = build_mineru_parsed_document_v1(
        sidecar,
        expected_raw_sha256=RAW_HASH,
        expected_sanitized_sha256=hashlib.sha256(sidecar).hexdigest(),
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        material_profile_resolution=resolution,
    )
    assert not document.tables and not document.cells
    assert "table_grid" in manifest.unsatisfied_capabilities
    assert decision.decision == "BLOCK"
    assert decision.review_item is not None


@pytest.mark.parametrize(
    ("target", "bbox"),
    (
        ("block", ["-1", "0", "1001", "1"]),
        ("table", ["0", "0", "1001", "1"]),
        ("cell", ["0", "-1", "1", "1001"]),
    ),
)
def test_native_mineru_out_of_range_bbox_reaches_053_block_and_review(
    target: str, bbox: list[str]
) -> None:
    subject, parser, attempt, snapshot, output, resolution = _context()
    payload = json.loads(_sidecar(subject.source_sha256))
    if target == "block":
        payload["blocks"][0]["bbox"] = bbox
    elif target == "table":
        payload["tables"][0]["bbox"] = bbox
        for cell in payload["cells"]:
            cell["bbox"] = bbox
    else:
        payload["cells"][0]["bbox"] = bbox
    sidecar = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    document, manifest, decision = build_mineru_parsed_document_v1(
        sidecar,
        expected_raw_sha256=RAW_HASH,
        expected_sanitized_sha256=hashlib.sha256(sidecar).hexdigest(),
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        material_profile_resolution=resolution,
    )

    assert decision.decision == "BLOCK"
    assert decision.review_item is not None
    assert decision.admitted_attempt_id is None
    assert decision.reason_codes == ("locator_invalid_or_required_structure_missing",)
    assert any(
        unsupported.capability == "native_structure_invalid"
        for unsupported in document.unsupported
    )
    if target == "block":
        assert not document.blocks
        assert "block_locators" in manifest.unsatisfied_capabilities
    else:
        assert not document.tables
        assert not document.cells
        assert "table_grid" in manifest.unsatisfied_capabilities


def test_native_mineru_bbox_accepts_exact_native_range_boundaries() -> None:
    subject, parser, attempt, snapshot, output, resolution = _context()
    payload = json.loads(_sidecar(subject.source_sha256))
    boundary = ["0", "0", "1000", "1000"]
    payload["blocks"][0]["bbox"] = boundary
    payload["tables"][0]["bbox"] = boundary
    for cell in payload["cells"]:
        cell["bbox"] = boundary
    sidecar = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    document, _, decision = build_mineru_parsed_document_v1(
        sidecar,
        expected_raw_sha256=RAW_HASH,
        expected_sanitized_sha256=hashlib.sha256(sidecar).hexdigest(),
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        material_profile_resolution=resolution,
    )

    assert decision.decision == "ADMIT"
    assert document.blocks[0].locator.bbox == tuple(Decimal(item) for item in boundary)


def test_native_mineru_invalid_bbox_blocks_without_profile_locator_requirement() -> None:
    subject, parser, attempt, snapshot, output, resolution = _context(
        ["ordered_pages"]
    )
    payload = json.loads(_sidecar(subject.source_sha256))
    payload["blocks"][0]["bbox"] = ["-1", "0", "1001", "1"]
    sidecar = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    document, _, decision = build_mineru_parsed_document_v1(
        sidecar,
        expected_raw_sha256=RAW_HASH,
        expected_sanitized_sha256=hashlib.sha256(sidecar).hexdigest(),
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        material_profile_resolution=resolution,
    )

    assert not document.blocks
    assert any(
        warning.warning_code == "native_structure_invalid"
        for warning in document.warnings
    )
    assert decision.decision == "BLOCK"
    assert decision.review_item is not None
    assert decision.admitted_attempt_id is None


def test_native_mineru_explicit_invalid_observation_blocks_without_locators() -> None:
    subject, parser, attempt, snapshot, output, resolution = _context(
        ["ordered_pages"]
    )
    payload = json.loads(_sidecar(subject.source_sha256))
    payload["blocks"] = []
    payload["tables"] = []
    payload["cells"] = []
    payload["unsupported"].append("native_structure_invalid")
    sidecar = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    document, _, decision = build_mineru_parsed_document_v1(
        sidecar,
        expected_raw_sha256=RAW_HASH,
        expected_sanitized_sha256=hashlib.sha256(sidecar).hexdigest(),
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        material_profile_resolution=resolution,
    )

    assert not document.blocks and not document.tables and not document.cells
    assert decision.decision == "BLOCK"
    assert decision.review_item is not None
    assert decision.admitted_attempt_id is None
    assert decision.reason_codes == ("locator_invalid_or_required_structure_missing",)
    assert any(
        unsupported.capability == "native_structure_invalid"
        for unsupported in document.unsupported
    )


def test_native_mineru_mixed_valid_and_ambiguous_tables_still_reaches_review() -> None:
    subject, parser, attempt, snapshot, output, resolution = _context()
    payload = json.loads(_sidecar(subject.source_sha256))
    payload["unsupported"] = [
        "table_grid",
        "cell_locators",
        "row_column_indices",
        "merged_cells",
        "header_hierarchy",
        "cross_page_sections",
        "cross_page_tables",
    ]
    sidecar = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    document, manifest, decision = build_mineru_parsed_document_v1(
        sidecar,
        expected_raw_sha256=RAW_HASH,
        expected_sanitized_sha256=hashlib.sha256(sidecar).hexdigest(),
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        material_profile_resolution=resolution,
    )
    assert document.tables and document.cells
    assert "table_grid" in manifest.unsatisfied_capabilities
    assert decision.decision == "BLOCK"
    assert decision.review_item is not None

    mismatched_subject = subject.model_copy(update={"source_sha256": "f" * 64})
    with pytest.raises(NativeMinerUStructureError, match="source_identity_mismatch"):
        build_mineru_parsed_document_v1(
            sidecar,
            expected_raw_sha256=RAW_HASH,
            expected_sanitized_sha256=hashlib.sha256(sidecar).hexdigest(),
            subject=mismatched_subject,
            parser=parser,
            attempt=attempt,
            snapshot=snapshot,
            output_facts=output,
            material_profile_resolution=resolution,
        )
