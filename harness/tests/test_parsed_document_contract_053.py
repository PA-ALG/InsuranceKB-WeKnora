"""OpenSpec 053: parser-neutral parsed-document contract."""

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

import insurance_harness.compiler.parsed_documents as parsed_documents
from insurance_harness.compiler.material_profiles import (
    ApprovedParsePolicy,
    MaterialProfile,
    MaterialProfileResolution,
    MaterialProfileResolutionRequest,
    SourceDocumentIdentity,
    load_material_profile_catalog_data,
    resolve_material_profile,
)
from insurance_harness.compiler.parsed_documents import (
    BlockLocatorV1,
    CapabilityEvidenceV1,
    CellLocatorV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParseBlockV1,
    ParseCellV1,
    ParsedDocumentV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    ParseTableV1,
    TableLocatorV1,
    UnsupportedParseFactV1,
    build_parse_manifest,
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

MODULE_PATH = (
    Path(__file__).parents[1]
    / "src"
    / "insurance_harness"
    / "compiler"
    / "parsed_documents.py"
)
MATERIAL_PROFILE_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "material_profile_596_1_052.json"
)
_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64
_HASH_D = "d" * 64
_DEFAULT_PARSER = "approved-parser-profile:parser-neutral-default.v1"
_UPGRADE_PARSER = "approved-parser-profile:parser-neutral-bounded-upgrade.v1"
_PRIVACY_POLICY = "privacy-policy:source-revision-private-processing.v1"
_OUTPUT_POLICY = "output-policy:parsed-artifact-internal-only.v1"


class _OneEntryTemplateCatalog:
    def __init__(self, entry: TemplateCatalogEntry) -> None:
        self._entry = entry

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        return self._entry if scope == self._entry.version.scope else None


def _resolution(
    *capabilities: str,
    with_upgrade: bool = True,
) -> MaterialProfileResolution:
    raw = json.loads(MATERIAL_PROFILE_FIXTURE_PATH.read_text(encoding="utf-8"))
    terms = raw["profiles"][0]
    terms["required_parse_capabilities"] = list(capabilities)
    if not with_upgrade:
        policy = terms["parse_policy"]
        policy["bounded_upgrade_profile_ref"] = None
        policy["upgrade_trigger_conditions"] = []
        policy["max_parser_attempts"] = 1
    catalog = load_material_profile_catalog_data(raw)
    profile = catalog.profiles[0]
    scope = TemplateScope(space_id="space-053", level="global")
    content = TemplatePackageContent(
        schema_version="v1.1+b31a411c621c",
        field_groups=(
            FieldGroup(
                group_id="group-053",
                field_ids=(catalog.schema_binding.field_ids[0],),
                evidence_roles=("terms",),
            ),
        ),
        role_prompts={"extract": "extract-053"},
        validators=(
            ValidatorRef(
                validator_id="validator-053",
                validator_version="v1",
                config_hash=_HASH_A,
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
                migration_id="MIG-053-test",
                source_repository="silvielala412-lab/LLM-wiki-black",
                source_branch="feature/product-catalog-domain",
                source_commit="6a8a1d98de405b6a2837090ee2d43769b4c89be7",
                source_path="frontend/src/lib/product-catalog-modules.ts",
                source_language="typescript",
                rights_status="project-owned",
                accepted_behavior="exact material profile binding",
                rejected_behavior="caller supplied parser policy",
                python_target=(
                    "harness/src/insurance_harness/compiler/parsed_documents.py"
                ),
                translation_method="behavior_port_with_characterization_tests",
                characterization_tests=(
                    "harness/tests/test_parsed_document_contract_053.py",
                ),
            ),
        ),
    )
    version = TemplateVersion.from_content(
        package_id="life-template-package",
        version_id="053-test-v1",
        scope=scope,
        content=content,
    )
    template_catalog = _OneEntryTemplateCatalog(
        TemplateCatalogEntry(
            version=version,
            approval=TemplateApproval(
                approval_id="approval-053",
                package_id=version.package_id,
                version_id=version.version_id,
                scope=scope,
                content_hash=version.content_hash,
                state="approved",
            ),
        )
    )
    request = MaterialProfileResolutionRequest(
        space_id="space-053",
        product_code=catalog.product.product_code,
        product_version=catalog.product.product_version,
        schema_version=catalog.schema_binding.schema_version,
        schema_field_ids=catalog.schema_binding.field_ids,
        source=profile.source,
        classified_material_role="terms",
    )
    return resolve_material_profile(catalog, template_catalog, request)


def _bbox(
    left: int, top: int, right: int, bottom: int
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    return Decimal(left), Decimal(top), Decimal(right), Decimal(bottom)


def _profile(
    *capabilities: str,
    with_upgrade: bool = True,
) -> MaterialProfile:
    upgrade = _UPGRADE_PARSER if with_upgrade else None
    return MaterialProfile(
        profile_id="profile-terms-596-1",
        material_role="terms",
        source=SourceDocumentIdentity(
            name="terms.pdf",
            path="dataset/terms.pdf",
            size=101,
            sha256=_HASH_A,
        ),
        document_type_id="insurance-terms",
        required_parse_capabilities=capabilities,
        parse_policy=ApprovedParsePolicy(
            policy_id="profile-terms-approved-parse-policy",
            policy_version="v1",
            material_profile_id="profile-terms-596-1",
            default_parser_profile_ref=_DEFAULT_PARSER,
            bounded_upgrade_profile_ref=upgrade,
            upgrade_trigger_conditions=("required_capability_missing",)
            if with_upgrade
            else (),
            max_parser_attempts=2 if with_upgrade else 1,
            privacy_policy_ref=_PRIVACY_POLICY,
            output_policy_ref=_OUTPUT_POLICY,
        ),
    )


def _document(
    *,
    attempt_number: Literal[1, 2] = 1,
    attempt_role: Literal["default", "bounded_upgrade"] = "default",
    parser_profile_ref: str = _DEFAULT_PARSER,
    material_profile_resolution: MaterialProfileResolution | None = None,
) -> ParsedDocumentV1:
    resolution = material_profile_resolution
    return ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=ParseSubjectV1(
            space_id="space-053",
            source_id="source-terms",
            source_revision_id="revision-1",
            product_version_id=(
                resolution.request.product_version if resolution else "596-1"
            ),
            material_profile_id=(
                resolution.profile.profile_id if resolution else "profile-terms-596-1"
            ),
            material_profile_binding_hash=(
                resolution.binding_hash if resolution else _HASH_B
            ),
            source_sha256=(resolution.profile.source.sha256 if resolution else _HASH_A),
            raw_artifact_hash=_HASH_C,
            canonical_envelope_hash=_HASH_D,
        ),
        parser=ParserIdentityV1(
            parser_id="parser-neutral-fixture",
            parser_profile_ref=parser_profile_ref,
            parser_build_id="build-v1",
            parser_config_hash=_HASH_B,
        ),
        attempt=ParseAttemptV1(
            attempt_id="attempt-default",
            attempt_number=attempt_number,
            attempt_role=attempt_role,
            generation=7,
        ),
        snapshot=ParseSnapshotV1(
            snapshot_id="snapshot-1",
            snapshot_generation=11,
            pagination_complete=True,
            concurrent_mutation_fence_hash=_HASH_D,
        ),
        output_facts=ParseOutputFactsV1(
            privacy_policy_ref=_PRIVACY_POLICY,
            output_policy_ref=_OUTPUT_POLICY,
            body_text_included=False,
            secrets_included=False,
            absolute_paths_included=False,
            unknown_vendor_fields_included=False,
        ),
        pages=(
            ParsePageV1(
                page_id="page-1",
                order_index=0,
                locator=PageLocatorV1(page_number=1),
                content_hash=_HASH_A,
                structure_hash=_HASH_B,
            ),
        ),
        blocks=(
            ParseBlockV1(
                block_id="block-1",
                order_index=0,
                locator=BlockLocatorV1(
                    page_number=1,
                    block_index=0,
                    bbox=_bbox(10, 20, 300, 80),
                ),
                content_hash=_HASH_A,
                structure_hash=_HASH_B,
            ),
        ),
        tables=(
            ParseTableV1(
                table_id="table-1",
                order_index=0,
                locator=TableLocatorV1(
                    page_number=1,
                    table_index=0,
                    bbox=_bbox(10, 100, 500, 400),
                ),
                content_hash=_HASH_A,
                structure_hash=_HASH_B,
                row_count=1,
                column_count=1,
                header_cell_ids=("cell-1",),
                continuation_table_ids=(),
            ),
        ),
        cells=(
            ParseCellV1(
                cell_id="cell-1",
                order_index=0,
                table_id="table-1",
                locator=CellLocatorV1(
                    page_number=1,
                    table_id="table-1",
                    row_index=0,
                    column_index=0,
                    row_span=1,
                    column_span=1,
                    bbox=_bbox(10, 100, 200, 140),
                ),
                content_hash=_HASH_C,
                structure_hash=_HASH_D,
            ),
        ),
        capability_evidence=(
            CapabilityEvidenceV1(
                capability="ordered_pages",
                subject_refs=("page-1",),
            ),
            CapabilityEvidenceV1(
                capability="table_grid",
                subject_refs=("table-1", "cell-1"),
            ),
        ),
        warnings=(),
        unsupported=(),
    )


def test_parsed_document_contract_module_exists() -> None:
    assert importlib.util.find_spec(
        "insurance_harness.compiler.parsed_documents"
    ) is not None
    assert MODULE_PATH.is_file()


def test_document_and_manifest_bind_exact_identity_and_structure() -> None:
    document = _document()
    manifest = build_parse_manifest(
        document,
        _profile("ordered_pages", "table_grid"),
    )

    assert manifest.contract == "parse-manifest.v1"
    assert manifest.subject == document.subject
    assert manifest.parser == document.parser
    assert manifest.attempt == document.attempt
    assert manifest.snapshot == document.snapshot
    assert manifest.output_facts == document.output_facts
    assert manifest.document_hash == document.document_hash
    assert manifest.ordered_page_ids == ("page-1",)
    assert manifest.ordered_block_ids == ("block-1",)
    assert manifest.ordered_table_ids == ("table-1",)
    assert manifest.ordered_cell_ids == ("cell-1",)
    assert manifest.element_counts.model_dump(mode="python") == {
        "pages": 1,
        "blocks": 1,
        "tables": 1,
        "cells": 1,
    }
    assert manifest.satisfied_capabilities == ("ordered_pages", "table_grid")
    assert manifest.capability_evidence == document.capability_evidence
    assert manifest.warnings == document.warnings
    assert manifest.unsupported == document.unsupported
    assert len(manifest.manifest_hash) == 64
    assert manifest == build_parse_manifest(
        document,
        _profile("ordered_pages", "table_grid"),
    )


def test_structure_is_ordered_unique_and_referentially_closed() -> None:
    document = _document()

    with pytest.raises(ValidationError, match="ordered structure"):
        ParsedDocumentV1.model_validate(
            document.model_copy(
                update={
                    "pages": (
                        ParsePageV1(
                            page_id="page-1",
                            order_index=1,
                            locator=PageLocatorV1(page_number=1),
                            content_hash=_HASH_A,
                            structure_hash=_HASH_B,
                        ),
                    )
                }
            ).model_dump(mode="python", exclude_computed_fields=True)
        )

    with pytest.raises(ValidationError, match="table bounds"):
        ParsedDocumentV1.model_validate(
            document.model_copy(
                update={
                    "cells": (
                        document.cells[0].model_copy(
                            update={
                                "locator": document.cells[0].locator.model_copy(
                                    update={"row_index": 1}
                                )
                            }
                        ),
                    )
                }
            ).model_dump(mode="python", exclude_computed_fields=True)
        )


def test_required_capability_is_evidence_backed_or_fails_closed() -> None:
    profile = _profile("ordered_pages", "cross_page_tables")
    manifest = build_parse_manifest(_document(), profile)
    assert manifest.required_capabilities == (
        "ordered_pages",
        "cross_page_tables",
    )
    assert manifest.unsatisfied_capabilities == ("cross_page_tables",)

    unsupported = _document().model_copy(
        update={
            "unsupported": (
                UnsupportedParseFactV1(
                    capability="cross_page_tables",
                    reason_code="parser_did_not_emit_cross_page_linkage",
                    subject_refs=("table-1",),
                ),
            )
        }
    )
    unsupported_manifest = build_parse_manifest(
        ParsedDocumentV1.model_validate(
            unsupported.model_dump(mode="python", exclude_computed_fields=True)
        ),
        _profile("cross_page_tables"),
    )
    assert unsupported_manifest.unsatisfied_capabilities == ("cross_page_tables",)
    assert unsupported_manifest.unsupported[0].capability == "cross_page_tables"


def test_contract_rejects_payload_text_paths_and_invalid_locators() -> None:
    with pytest.raises(ValidationError):
        ParseBlockV1.model_validate(
            {
                "block_id": "block-1",
                "order_index": 0,
                "locator": {
                    "page_number": 1,
                    "block_index": 0,
                    "bbox": [1, 2, 3, 4],
                },
                "content_hash": _HASH_A,
                "structure_hash": _HASH_B,
                "text": "raw document body must not enter this contract",
            }
        )

    with pytest.raises(ValidationError):
        ParseSubjectV1.model_validate(
            {
                **_document().subject.model_dump(mode="python"),
                "runtime_path": "/private/tmp/source.pdf",
            }
        )

    with pytest.raises(ValidationError, match="bbox"):
        CellLocatorV1(
            page_number=1,
            table_id="table-1",
            row_index=0,
            column_index=0,
            row_span=1,
            column_span=1,
            bbox=_bbox(10, 20, 10, 30),
        )


def test_locators_accept_fractional_parser_neutral_coordinates() -> None:
    locator = BlockLocatorV1.model_validate(
        {
            "page_number": 1,
            "block_index": 0,
            "bbox": ("-0.25", "1.5", "42.75", "99.125"),
        }
    )

    assert locator.bbox == (
        Decimal("-0.25"),
        Decimal("1.5"),
        Decimal("42.75"),
        Decimal("99.125"),
    )

    with pytest.raises(ValidationError, match="binary float"):
        BlockLocatorV1.model_validate(
            {
                "page_number": 1,
                "block_index": 0,
                "bbox": (-0.25, 1.5, 42.75, 99.125),
            }
        )


def test_quality_default_admits_and_exact_missing_trigger_escalates() -> None:
    admitted_resolution = _resolution("ordered_pages", "table_grid")
    document = _document(material_profile_resolution=admitted_resolution)
    admitted = parsed_documents.evaluate_parse_quality(
        document=document,
        manifest=build_parse_manifest(document, admitted_resolution.profile),
        material_profile_resolution=admitted_resolution,
    )
    assert admitted.decision == "ADMIT"
    assert admitted.admitted_attempt_id == document.attempt.attempt_id
    assert admitted.next_parser_profile_ref is None
    assert admitted.review_item is None

    missing_resolution = _resolution("ordered_pages", "cross_page_tables")
    missing_document = _document(material_profile_resolution=missing_resolution)
    escalated = parsed_documents.evaluate_parse_quality(
        document=missing_document,
        manifest=build_parse_manifest(missing_document, missing_resolution.profile),
        material_profile_resolution=missing_resolution,
    )
    assert escalated.decision == "ESCALATE"
    assert escalated.next_parser_profile_ref == _UPGRADE_PARSER
    assert escalated.admitted_attempt_id is None
    assert escalated.review_item is None
    assert escalated.reason_codes == ("table_grid_or_span_incomplete",)
    assert escalated.measured_facts.trigger_conditions == (
        "required_capability_missing",
    )


def test_quality_blocks_without_upgrade_and_stops_after_second_attempt() -> None:
    no_upgrade = _resolution("cross_page_tables", with_upgrade=False)
    document = _document(material_profile_resolution=no_upgrade)
    blocked = parsed_documents.evaluate_parse_quality(
        document=document,
        manifest=build_parse_manifest(document, no_upgrade.profile),
        material_profile_resolution=no_upgrade,
    )
    assert blocked.decision == "BLOCK"
    assert blocked.review_item is not None
    assert blocked.next_parser_profile_ref is None

    second_resolution = _resolution("cross_page_tables")
    second = _document(
        attempt_number=2,
        attempt_role="bounded_upgrade",
        parser_profile_ref=_UPGRADE_PARSER,
        material_profile_resolution=second_resolution,
    )
    exhausted = parsed_documents.evaluate_parse_quality(
        document=second,
        manifest=build_parse_manifest(second, second_resolution.profile),
        material_profile_resolution=second_resolution,
    )
    assert exhausted.decision == "BLOCK"
    assert exhausted.review_item is not None
    assert exhausted.next_parser_profile_ref is None
    assert exhausted.measured_facts.attempts_exhausted is True

    with pytest.raises(ValidationError, match="1 or 2"):
        ParseAttemptV1.model_validate(
            {
                "attempt_id": "attempt-third",
                "attempt_number": 3,
                "attempt_role": "bounded_upgrade",
                "generation": 8,
            }
        )


def test_quality_blocks_manifest_drift_and_privacy_output_violation() -> None:
    resolution = _resolution("ordered_pages", "table_grid", with_upgrade=False)
    document = _document(material_profile_resolution=resolution)
    profile = resolution.profile
    manifest = build_parse_manifest(document, profile)
    drifted = manifest.model_copy(update={"ordered_page_ids": ("forged-page",)})
    drift = parsed_documents.evaluate_parse_quality(
        document=document,
        manifest=drifted,
        material_profile_resolution=resolution,
    )
    assert drift.decision == "BLOCK"
    assert drift.reason_codes == ("manifest_digest_or_count_mismatch",)

    unsafe_document = document.model_copy(
        update={
            "output_facts": document.output_facts.model_copy(
                update={"body_text_included": True}
            )
        }
    )
    unsafe_document = ParsedDocumentV1.model_validate(
        unsafe_document.model_dump(mode="python", exclude_computed_fields=True)
    )
    privacy = parsed_documents.evaluate_parse_quality(
        document=unsafe_document,
        manifest=build_parse_manifest(unsafe_document, profile),
        material_profile_resolution=resolution,
    )
    assert privacy.decision == "BLOCK"
    assert privacy.reason_codes == ("privacy_or_output_policy_violation",)
    assert privacy.review_item is not None

    unsafe_manifest = manifest.model_copy(
        update={
            "output_facts": manifest.output_facts.model_copy(
                update={"secrets_included": True}
            )
        }
    )
    manifest_privacy = parsed_documents.evaluate_parse_quality(
        document=document,
        manifest=unsafe_manifest,
        material_profile_resolution=resolution,
    )
    assert manifest_privacy.reason_codes == (
        "privacy_or_output_policy_violation",
    )


def test_quality_blocks_policy_or_parser_identity_mismatch() -> None:
    resolution = _resolution("ordered_pages", "table_grid")
    document = _document(
        parser_profile_ref=_UPGRADE_PARSER,
        material_profile_resolution=resolution,
    )
    profile = resolution.profile
    decision = parsed_documents.evaluate_parse_quality(
        document=document,
        manifest=build_parse_manifest(document, profile),
        material_profile_resolution=resolution,
    )

    assert decision.decision == "BLOCK"
    assert decision.reason_codes == ("unsupported_material_or_parser_profile",)
    assert decision.review_item is not None

    locator_resolution = _resolution("block_locators", with_upgrade=False)
    locator_document = _document(material_profile_resolution=locator_resolution)
    locator = parsed_documents.evaluate_parse_quality(
        document=locator_document,
        manifest=build_parse_manifest(locator_document, locator_resolution.profile),
        material_profile_resolution=locator_resolution,
    )
    assert locator.reason_codes == (
        "locator_invalid_or_required_structure_missing",
    )

    exact_resolution = _resolution("ordered_pages", "table_grid")
    exact_document = _document(material_profile_resolution=exact_resolution)
    foreign_subject = exact_document.subject.model_copy(
        update={"source_revision_id": "revision-foreign"}
    )
    mixed_manifest = build_parse_manifest(
        exact_document, exact_resolution.profile
    ).model_copy(
        update={"subject": foreign_subject}
    )
    identity = parsed_documents.evaluate_parse_quality(
        document=exact_document,
        manifest=mixed_manifest,
        material_profile_resolution=exact_resolution,
    )
    assert identity.reason_codes == ("identity_revision_parser_drift",)


def test_table_grid_page_evidence_cannot_admit_without_table_and_cell() -> None:
    resolution = _resolution("table_grid")
    document = _document(material_profile_resolution=resolution).model_copy(
        update={
            "tables": (),
            "cells": (),
            "capability_evidence": (
                CapabilityEvidenceV1(
                    capability="table_grid",
                    subject_refs=("page-1",),
                ),
            ),
        }
    )
    document = ParsedDocumentV1.model_validate(
        document.model_dump(mode="python", exclude_computed_fields=True)
    )
    profile = resolution.profile
    manifest = build_parse_manifest(document, profile)

    decision = parsed_documents.evaluate_parse_quality(
        document=document,
        manifest=manifest,
        material_profile_resolution=resolution,
    )

    assert manifest.satisfied_capabilities == ()
    assert manifest.unsatisfied_capabilities == ("table_grid",)
    assert decision.decision == "ESCALATE"
    assert decision.reason_codes == ("table_grid_or_span_incomplete",)


def test_missing_capability_subject_refs_fail_closed_through_policy() -> None:
    resolution = _resolution("table_grid")
    document = _document(material_profile_resolution=resolution).model_copy(
        update={
            "capability_evidence": (
                CapabilityEvidenceV1(
                    capability="table_grid",
                    subject_refs=("missing-table", "missing-cell"),
                ),
            ),
        }
    )
    document = ParsedDocumentV1.model_validate(
        document.model_dump(mode="python", exclude_computed_fields=True)
    )
    manifest = build_parse_manifest(document, resolution.profile)

    decision = parsed_documents.evaluate_parse_quality(
        document=document,
        manifest=manifest,
        material_profile_resolution=resolution,
    )

    assert manifest.unsatisfied_capabilities == ("table_grid",)
    assert decision.decision == "ESCALATE"
    assert decision.reason_codes == ("table_grid_or_span_incomplete",)


def test_missing_or_narrowed_policy_authority_blocks_with_review_item() -> None:
    resolution = _resolution("ordered_pages", "table_grid")
    document = _document(material_profile_resolution=resolution)
    full_profile = resolution.profile
    narrowed_profile = full_profile.model_copy(
        update={"required_parse_capabilities": ("ordered_pages",)}
    )
    narrowed_manifest = build_parse_manifest(document, narrowed_profile)
    narrowed_receipt = resolution.parse_policy_receipt.model_copy(
        update={"required_parse_capabilities": ("ordered_pages",)}
    )
    forged_resolution = resolution.model_copy(
        update={"parse_policy_receipt": narrowed_receipt}
    )

    missing = parsed_documents.evaluate_parse_quality(
        document=document,
        manifest=build_parse_manifest(document, full_profile),
        material_profile_resolution=None,
    )
    narrowed = parsed_documents.evaluate_parse_quality(
        document=document,
        manifest=narrowed_manifest,
        material_profile_resolution=forged_resolution,
    )

    for decision in (missing, narrowed):
        assert decision.decision == "BLOCK"
        assert decision.reason_codes == (
            "unsupported_material_or_parser_profile",
        )
        assert decision.review_item is not None
