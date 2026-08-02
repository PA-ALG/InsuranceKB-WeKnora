"""OpenSpec 069: shared MinerU semantic-task composer for Product 596-1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Literal

import pytest

import insurance_harness.knowledge_compiler.semantic_input_binding as semantic_module
import insurance_harness.knowledge_compiler.weak_strong_ceiling as ceiling_module
from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    ApprovedLocatorSetV1,
    EvidenceLocatorSnapshotV1,
    FreeformEvidenceV1,
    FreeformFieldOutputV1,
    RepairBudgetV1,
    TargetedRepairPlanV1,
    VerificationBatchV1,
    bind_freeform_arm_evidence,
    plan_targeted_repair,
)
from insurance_harness.compiler.material_profiles import (
    MaterialProfileCatalog,
    MaterialProfileResolution,
    MaterialProfileResolutionRequest,
    load_material_profile_catalog,
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
    ParseOutputFactsV1,
    ParsePageV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    ParseTableV1,
    TableLocatorV1,
    build_parse_manifest,
    evaluate_parse_quality,
)
from insurance_harness.knowledge_compiler.semantic_input_binding import (
    BoundSemanticAttemptV1,
    MinerUSemanticCustodyV2,
    SemanticBindingContractError,
    SemanticExecutionIdentityV1,
    SemanticRepairBundleV1,
    SemanticSourceInputV1,
    bind_596_1_semantic_response,
    build_596_1_shared_task_blueprint,
    build_596_1_targeted_repairs,
    compose_596_1_semantic_inputs,
)
from insurance_harness.knowledge_compiler.vertical_falsification import (
    APPROVED_RATE_FIELD_IDS,
    APPROVED_SCHEMA60_FIELD_IDS,
    AdmittedParseArtifactV1,
    VerticalFalsificationAdmission,
    admit_596_1_vertical_falsification,
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

CATALOG_PATH = Path(__file__).parent / "fixtures/material_profile_596_1_052.json"
GOLDEN_PATH = (
    Path(__file__).parents[2] / "dataset/goldenset/gs-s0q-596-v1/596.jsonl"
)
SOURCE_REBOUND_FIELDS = frozenset(
    {
        "zh_0c5a8e59e2",
        "zh_14b93ce275",
        "zh_17a83223e4",
        "zh_f8cc996739",
        "zh_fd9a0b9fa3",
    }
)
_REAL_061_ADMISSION = admit_596_1_vertical_falsification


@pytest.fixture(autouse=True)
def _future_061_admission_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate the approved 061 receipt while 060 cross-page admission is pending."""

    def admit(
        *, admitted_parse_artifacts: tuple[AdmittedParseArtifactV1, ...], **_: object
    ) -> VerticalFalsificationAdmission:
        payload = tuple(
            (
                item.role,
                item.source_sha256,
                item.artifact_sha256,
                item.manifest_sha256,
                item.decision_sha256,
            )
            for item in admitted_parse_artifacts
        )
        return VerticalFalsificationAdmission(
            status="READY_FOR_QUALITY_FALSIFICATION",
            missing_contracts=(),
            receipt_digest_sha256=_digest(json.dumps(payload, separators=(",", ":"))),
        )

    monkeypatch.setattr(semantic_module, "admit_596_1_vertical_falsification", admit)


class _GlobalTemplateCatalog:
    def __init__(self, entry: TemplateCatalogEntry) -> None:
        self._entry = entry

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        return self._entry if scope == self._entry.version.scope else None


def _catalog_and_resolutions() -> tuple[
    MaterialProfileCatalog,
    tuple[MaterialProfileResolution, ...],
]:
    catalog = load_material_profile_catalog(CATALOG_PATH)
    scope = TemplateScope(space_id="space-069", level="global")
    content = TemplatePackageContent(
        schema_version=catalog.schema_binding.schema_version,
        field_groups=(
            FieldGroup(
                group_id="schema60",
                field_ids=catalog.schema_binding.field_ids,
                evidence_roles=("terms", "brochure", "rate_table"),
            ),
        ),
        role_prompts={"extract": "596-1 shared semantic input"},
        validators=(
            ValidatorRef(
                validator_id="069-evidence-binding",
                validator_version="v1",
                config_hash="1" * 64,
            ),
        ),
        evidence_policy=EvidencePolicy(
            require_quote=True,
            require_locator=True,
            minimum_sources=1,
        ),
        attempt_limits={"extract": 2},
        golden_slice_ref="gs-s0q-596-v1",
        provenance=(
            ProvenanceReceipt(
                migration_id="MIG-069-test",
                source_repository="silvielala412-lab/LLM-wiki-black",
                source_branch="feature/product-catalog-domain",
                source_commit="6a8a1d98de405b6a2837090ee2d43769b4c89be7",
                source_path="frontend/src/lib/product-catalog-modules.ts",
                source_language="typescript",
                rights_status="project-owned",
                accepted_behavior="shared MinerU semantic task blueprint",
                rejected_behavior="parser or model execution",
                python_target=(
                    "harness/src/insurance_harness/knowledge_compiler/semantic_input_binding.py"
                ),
                translation_method="behavior_port_with_characterization_tests",
                characterization_tests=("harness/tests/test_596_1_semantic_input_binding_069.py",),
            ),
        ),
    )
    version = TemplateVersion.from_content(
        package_id="596-1-global-template",
        version_id="069-v1",
        scope=scope,
        content=content,
    )
    templates = _GlobalTemplateCatalog(
        TemplateCatalogEntry(
            version=version,
            approval=TemplateApproval(
                approval_id="approval-069",
                package_id=version.package_id,
                version_id=version.version_id,
                scope=scope,
                content_hash=version.content_hash,
                state="approved",
            ),
        )
    )
    profiles = {item.material_role: item for item in catalog.profiles}
    resolutions = tuple(
        resolve_material_profile(
            catalog,
            templates,
            MaterialProfileResolutionRequest(
                space_id="space-069",
                product_code=catalog.product.product_code,
                product_version=catalog.product.product_version,
                schema_version=catalog.schema_binding.schema_version,
                schema_field_ids=catalog.schema_binding.field_ids,
                source=profiles[role].source,
                classified_material_role=role,
            ),
        )
        for role in ("terms", "brochure", "rate_table")
    )
    return catalog, resolutions


def _execution_identity(
    *, model_hash: str = "a" * 64, model_id: str = "model-under-evaluation"
) -> SemanticExecutionIdentityV1:
    return SemanticExecutionIdentityV1(
        model_id=model_id,
        model_identity_sha256=model_hash,
        prompt_contract_id="596-1-shared-semantic-prompt.v1",
        prompt_template_sha256="b" * 64,
        budget_identity_sha256="c" * 64,
        normalizer_identity_sha256="9" * 64,
        output_contract_id="freeform-arm-evidence-binding-receipt.v1",
        output_contract_identity_sha256="d" * 64,
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _custody_bytes(
    *,
    source_sha256: str,
    raw_sha256: str,
    sanitized: bytes,
    content: str,
    config_sha256: str,
) -> bytes:
    sanitized_sha256 = hashlib.sha256(sanitized).hexdigest()
    content_sha256 = _digest(content)
    attempt = {
        "attempt_number": 2,
        "attempt_role": "bounded_upgrade",
        "generation": 0,
    }
    identity = {
        "contract": "mineru-semantic-content-custody.v2",
        "source_sha256": source_sha256,
        "attempt": attempt,
        "parser_config_sha256": config_sha256,
        "raw_structure_sha256": raw_sha256,
        "sanitized_structure_sha256": sanitized_sha256,
        "content_snapshot_sha256": content_sha256,
    }
    payload = {
        "contract": "mineru-semantic-content-custody.v2",
        "source_sha256": source_sha256,
        "attempt": attempt,
        "raw_structure_sha256": raw_sha256,
        "sanitized_structure_sha256": sanitized_sha256,
        "sanitized_structure": json.loads(sanitized),
        "content_snapshot_sha256": content_sha256,
        "content_snapshot": content,
        "capture_identity_sha256": hashlib.sha256(
            json.dumps(identity, separators=(",", ":")).encode()
        ).hexdigest(),
        "parser": {
            "engine": "mineru_cloud",
            "implementation": "NewMinerUCloudReader",
            "native_structure_schema": "mineru-native-structure.v1",
            "model": "pipeline",
            "formula": True,
            "table": True,
            "ocr": True,
            "language": "ch",
            "config_sha256": config_sha256,
        },
        "calls": {
            "allocation_post": 1,
            "upload_put": 1,
            "status_get": 2,
            "zip_get": 1,
        },
        "latency_milliseconds": 100,
        "status": "completed",
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def _admitted_source(
    role: Literal["terms", "brochure", "rate_table"],
    resolution: MaterialProfileResolution,
) -> SemanticSourceInputV1:
    raw_sha256 = _digest(f"raw-{role}")
    config_sha256 = _digest("mineru-config")
    page_texts = (f"{role}第一页明确条款。", f"{role}第二页继续说明。")
    block_texts = (page_texts[0], page_texts[1])
    cell_texts = (f"{role}表头及数值一", f"{role}表头及数值二")
    pages = tuple(
        ParsePageV1(
            page_id=f"{role}-page-{number}",
            order_index=number - 1,
            locator=PageLocatorV1(page_number=number),
            content_hash=_digest(page_texts[number - 1]),
            structure_hash=_digest(f"{role}-page-structure-{number}"),
        )
        for number in (1, 2)
    )
    blocks = tuple(
        ParseBlockV1(
            block_id=f"{role}-block-{number}",
            order_index=number - 1,
            locator=BlockLocatorV1(
                page_number=number,
                block_index=0,
                bbox=(Decimal(0), Decimal(0), Decimal(100), Decimal(100)),
            ),
            content_hash=_digest(block_texts[number - 1]),
            structure_hash=_digest(f"{role}-block-structure-{number}"),
        )
        for number in (1, 2)
    )
    tables = tuple(
        ParseTableV1(
            table_id=f"{role}-table-{number}",
            order_index=number - 1,
            locator=TableLocatorV1(
                page_number=number,
                table_index=0,
                bbox=(Decimal(0), Decimal(0), Decimal(100), Decimal(100)),
            ),
            content_hash=_digest(cell_texts[number - 1]),
            structure_hash=_digest(f"{role}-table-structure-{number}"),
            row_count=2,
            column_count=1,
            header_cell_ids=(f"{role}-cell-{number}",),
            continuation_table_ids=((f"{role}-table-2",) if number == 1 else ()),
        )
        for number in (1, 2)
    )
    cells = tuple(
        ParseCellV1(
            cell_id=f"{role}-cell-{number}",
            order_index=number - 1,
            table_id=f"{role}-table-{number}",
            locator=CellLocatorV1(
                page_number=number,
                table_id=f"{role}-table-{number}",
                row_index=0,
                column_index=0,
                row_span=2,
                column_span=1,
                bbox=(Decimal(0), Decimal(0), Decimal(100), Decimal(100)),
            ),
            content_hash=_digest(cell_texts[number - 1]),
            structure_hash=_digest(f"{role}-cell-structure-{number}"),
        )
        for number in (1, 2)
    )
    refs = {
        "ordered_pages": tuple(item.page_id for item in pages),
        "block_locators": tuple(item.block_id for item in blocks),
        "cross_page_sections": tuple(item.block_id for item in blocks),
        "table_grid": tuple(item.table_id for item in tables)
        + tuple(item.cell_id for item in cells),
        "cell_locators": tuple(item.cell_id for item in cells),
        "header_hierarchy": tuple(item.table_id for item in tables)
        + tuple(item.cell_id for item in cells),
        "row_column_indices": tuple(item.cell_id for item in cells),
        "merged_cells": tuple(item.cell_id for item in cells),
        "cross_page_tables": tuple(item.table_id for item in tables),
    }
    capability_evidence = tuple(
        CapabilityEvidenceV1(capability=item, subject_refs=refs[item])
        for item in resolution.profile.required_parse_capabilities
    )
    sanitized_object = {
        "contract": "mineru-native-structure.v1",
        "source_schema": "mineru.content-list.pipeline.v1",
        "parser_model": "pipeline",
        "source_sha256": resolution.profile.source.sha256,
        "raw_sha256": raw_sha256,
        "pages": [],
        "blocks": [],
        "tables": [],
        "cells": [],
        "unsupported": [],
    }
    sanitized = json.dumps(sanitized_object, ensure_ascii=False, separators=(",", ":")).encode()
    subject = ParseSubjectV1(
        space_id="space-069",
        source_id=f"source-{role}",
        source_revision_id=f"revision-{role}-069",
        product_version_id="596-1",
        material_profile_id=resolution.profile.profile_id,
        material_profile_binding_hash=resolution.binding_hash,
        source_sha256=resolution.profile.source.sha256,
        raw_artifact_hash=raw_sha256,
        canonical_envelope_hash=_digest(f"envelope-{role}"),
    )
    parser = ParserIdentityV1(
        parser_id="mineru-cloud-pipeline",
        parser_profile_ref=resolution.parse_policy_receipt.bounded_upgrade_profile_ref or "missing",
        parser_build_id="mineru-060",
        parser_config_hash=config_sha256,
    )
    attempt = ParseAttemptV1(
        attempt_id=f"attempt-{role}-069",
        attempt_number=2,
        attempt_role="bounded_upgrade",
        generation=0,
    )
    snapshot = ParseSnapshotV1(
        snapshot_id=f"snapshot-{role}-069",
        snapshot_generation=0,
        pagination_complete=True,
        concurrent_mutation_fence_hash=_digest(f"fence-{role}"),
    )
    output = ParseOutputFactsV1(
        privacy_policy_ref=resolution.parse_policy_receipt.privacy_policy_ref,
        output_policy_ref=resolution.parse_policy_receipt.output_policy_ref,
        body_text_included=False,
        secrets_included=False,
        absolute_paths_included=False,
        unknown_vendor_fields_included=False,
    )
    from insurance_harness.compiler.parsed_documents import ParsedDocumentV1

    document = ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=subject,
        parser=parser,
        attempt=attempt,
        snapshot=snapshot,
        output_facts=output,
        pages=pages,
        blocks=blocks,
        tables=tables,
        cells=cells,
        capability_evidence=capability_evidence,
        warnings=(),
        unsupported=(),
    )
    manifest = build_parse_manifest(document, resolution.profile)
    decision = evaluate_parse_quality(
        document=document,
        manifest=manifest,
        material_profile_resolution=resolution,
    )
    assert decision.decision == "ADMIT"
    content = "\n".join(page_texts + block_texts + cell_texts)
    return SemanticSourceInputV1(
        custody_json=_custody_bytes(
            source_sha256=resolution.profile.source.sha256,
            raw_sha256=raw_sha256,
            sanitized=sanitized,
            content=content,
            config_sha256=config_sha256,
        ),
        admitted=AdmittedParseArtifactV1(
            role=role,
            source_sha256=resolution.profile.source.sha256,
            artifact_sha256=document.document_hash,
            document=document,
            manifest=manifest,
            decision=decision,
            manifest_sha256=manifest.manifest_hash,
            decision_sha256=decision.decision_hash,
            sanitized_structure=sanitized,
            raw_structure_sha256=raw_sha256,
            sanitized_structure_sha256=hashlib.sha256(sanitized).hexdigest(),
            material_profile_resolution=resolution,
        ),
    )


def test_shared_blueprint_is_exact_8_plus_2_schema60_bijection() -> None:
    catalog, resolutions = _catalog_and_resolutions()

    blueprint = build_596_1_shared_task_blueprint(
        catalog=catalog,
        resolutions=resolutions,
        execution_identity=_execution_identity(),
    )

    assert len(blueprint.tasks) == 10
    assert [task.task_kind for task in blueprint.tasks].count("semantic") == 8
    assert [task.task_kind for task in blueprint.tasks].count("deterministic_rate") == 2
    field_ids = tuple(field_id for task in blueprint.tasks for field_id in task.field_ids)
    assert len(field_ids) == len(set(field_ids)) == 60
    assert set(field_ids) == set(APPROVED_SCHEMA60_FIELD_IDS)
    assert [task.material_role for task in blueprint.tasks].count("terms") == 4
    assert [task.material_role for task in blueprint.tasks].count("brochure") == 4
    assert [task.material_role for task in blueprint.tasks].count("rate_table") == 2
    assert all(
        task.model_identity_sha256 == blueprint.execution_identity.model_identity_sha256
        and task.output_contract_identity_sha256
        == blueprint.execution_identity.output_contract_identity_sha256
        for task in blueprint.tasks
    )


def test_exact_five_fields_follow_approved_golden_terms_evidence_only() -> None:
    catalog, resolutions = _catalog_and_resolutions()
    blueprint = build_596_1_shared_task_blueprint(
        catalog=catalog,
        resolutions=resolutions,
        execution_identity=_execution_identity(),
    )
    task_by_field = {
        field_id: task for task in blueprint.tasks for field_id in task.field_ids
    }
    golden_rows = {
        row["field_id"]: row
        for row in (
            json.loads(line) for line in GOLDEN_PATH.read_text().splitlines()
        )
        if row["field_id"] in SOURCE_REBOUND_FIELDS
    }

    assert set(golden_rows) == SOURCE_REBOUND_FIELDS
    assert {row["doc"] for row in golden_rows.values()} == {"保险条款.pdf"}
    assert all(row["evidence"] for row in golden_rows.values())
    assert {
        field_id
        for field_id, task in task_by_field.items()
        if task.material_role != catalog.authority_for(field_id).primary_role
    } == SOURCE_REBOUND_FIELDS
    assert all(
        task_by_field[field_id].material_role == "terms"
        and task_by_field[field_id].source_sha256
        == resolutions[0].profile.source.sha256
        and task_by_field[field_id].material_profile_id
        == resolutions[0].profile.profile_id
        for field_id in SOURCE_REBOUND_FIELDS
    )
    assert all(
        task_by_field[field_id].material_role
        == catalog.authority_for(field_id).primary_role
        for field_id in set(APPROVED_SCHEMA60_FIELD_IDS) - SOURCE_REBOUND_FIELDS
    )
    legacy_task_by_field: dict[str, str] = {}
    for role in ("terms", "brochure"):
        legacy_fields = tuple(
            field_id
            for field_id in APPROVED_SCHEMA60_FIELD_IDS
            if catalog.authority_for(field_id).primary_role == role
        )
        quotient, remainder = divmod(len(legacy_fields), 4)
        cursor = 0
        for index in range(4):
            width = quotient + (1 if index < remainder else 0)
            legacy_task_by_field.update(
                {
                    field_id: f"069:596-1-{role}-semantic-{index + 1:02d}"
                    for field_id in legacy_fields[cursor : cursor + width]
                }
            )
            cursor += width
    assert all(
        task_by_field[field_id].task_id == legacy_task_by_field[field_id]
        for field_id in set(APPROVED_SCHEMA60_FIELD_IDS)
        - SOURCE_REBOUND_FIELDS
        - set(APPROVED_RATE_FIELD_IDS)
    )
    mirrored = ceiling_module._approved_task_plan_payload()["tasks"]
    assert isinstance(mirrored, tuple)
    assert tuple(
        (task.task_id, task.material_role, task.field_ids, task.source_sha256)
        for task in blueprint.tasks
    ) == tuple(
        (
            item["task_id"],
            item["material_role"],
            item["field_ids"],
            item["source_sha256"],
        )
        for item in mirrored
    )


def test_model_identity_changes_blueprint_without_changing_task_partition() -> None:
    catalog, resolutions = _catalog_and_resolutions()
    first = build_596_1_shared_task_blueprint(
        catalog=catalog,
        resolutions=resolutions,
        execution_identity=_execution_identity(model_hash="a" * 64),
    )
    second = build_596_1_shared_task_blueprint(
        catalog=catalog,
        resolutions=resolutions,
        execution_identity=_execution_identity(model_hash="e" * 64),
    )

    assert tuple(task.field_ids for task in first.tasks) == tuple(
        task.field_ids for task in second.tasks
    )
    assert first.blueprint_hash != second.blueprint_hash

    renamed = build_596_1_shared_task_blueprint(
        catalog=catalog,
        resolutions=resolutions,
        execution_identity=_execution_identity(model_hash="a" * 64, model_id="other-model"),
    )
    assert first.blueprint_hash != renamed.blueprint_hash
    assert first.tasks[0].task_hash != renamed.tasks[0].task_hash


def test_catalog_or_resolution_identity_drift_fails_closed() -> None:
    catalog, resolutions = _catalog_and_resolutions()
    drifted = catalog.model_copy(
        update={"product": catalog.product.model_copy(update={"product_version": "596-2"})}
    )

    with pytest.raises(SemanticBindingContractError) as caught:
        build_596_1_shared_task_blueprint(
            catalog=drifted,
            resolutions=resolutions,
            execution_identity=_execution_identity(),
        )

    assert caught.value.reason_code == "MATERIAL_AUTHORITY_MISMATCH"


def _composition_inputs() -> tuple[
    MaterialProfileCatalog,
    tuple[SemanticSourceInputV1, SemanticSourceInputV1, SemanticSourceInputV1],
]:
    catalog, resolutions = _catalog_and_resolutions()
    by_role = {item.profile.material_role: item for item in resolutions}
    return catalog, (
        _admitted_source("terms", by_role["terms"]),
        _admitted_source("brochure", by_role["brochure"]),
        _admitted_source("rate_table", by_role["rate_table"]),
    )


def test_composer_binds_same_read_custody_to_054_tasks_and_two_model_arms() -> None:
    catalog, sources = _composition_inputs()
    composition = compose_596_1_semantic_inputs(
        catalog=catalog,
        sources=sources,
        execution_identities=(
            _execution_identity(model_hash="a" * 64),
            _execution_identity(model_hash="e" * 64),
        ),
    )
    assert len(composition.tasks) == 10
    assert sum(item.extraction_task is not None for item in composition.tasks) == 8
    assert sum(item.initial_attempt is not None for item in composition.tasks) == 8
    assert tuple(item.field_ids for item in composition.arm_blueprints[0].tasks) == tuple(
        item.field_ids for item in composition.arm_blueprints[1].tasks
    )
    rebound_tasks = tuple(
        task
        for task in composition.tasks
        if SOURCE_REBOUND_FIELDS.intersection(task.field_ids)
    )
    assert {
        field_id for task in rebound_tasks for field_id in task.field_ids
    }.issuperset(SOURCE_REBOUND_FIELDS)
    assert all(
        task.material_role == "terms"
        and task.extraction_task is not None
        and task.extraction_task.task_profile.material_profile.material_role == "terms"
        and SOURCE_REBOUND_FIELDS.intersection(task.field_ids).issubset(
            task.extraction_task.task_profile.field_authority.field_ids
        )
        and task.extraction_task.task_profile.field_authority.primary_role == "terms"
        for task in rebound_tasks
    )
    assert all(
        item.attempt.attempt_number == 2
        and item.attempt.attempt_role == "bounded_upgrade"
        and item.attempt.generation == 0
        for item in (
            MinerUSemanticCustodyV2.model_validate_json(source.custody_json)
            for source in sources
        )
    )


def test_self_issued_admit_with_empty_structure_cannot_compose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog, sources = _composition_inputs()
    monkeypatch.setattr(
        semantic_module,
        "admit_596_1_vertical_falsification",
        _REAL_061_ADMISSION,
    )

    with pytest.raises(SemanticBindingContractError) as caught:
        compose_596_1_semantic_inputs(
            catalog=catalog,
            sources=sources,
            execution_identities=(
                _execution_identity(model_hash="a" * 64),
                _execution_identity(model_hash="e" * 64),
            ),
        )

    assert caught.value.reason_code == "PARSE_ADMISSION_MISMATCH"

@pytest.mark.parametrize(
    ("path", "value", "reason"),
    (
        (("source_sha256",), "0" * 64, "MINERU_CUSTODY_HASH_MISMATCH"),
        (("attempt", "generation"), 1, "MINERU_CUSTODY_INVALID"),
        (("parser", "config_sha256"), "0" * 64, "MINERU_CUSTODY_HASH_MISMATCH"),
        (("content_snapshot",), "drift", "MINERU_CUSTODY_HASH_MISMATCH"),
    ),
)
def test_custody_identity_or_hash_drift_fails_before_any_task(
    path: tuple[str, ...], value: object, reason: str
) -> None:
    catalog, sources = _composition_inputs()
    payload = json.loads(sources[0].custody_json)
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    drifted = SemanticSourceInputV1(
        custody_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(),
        admitted=sources[0].admitted,
    )

    with pytest.raises(SemanticBindingContractError) as caught:
        compose_596_1_semantic_inputs(
            catalog=catalog,
            sources=(drifted, sources[1], sources[2]),
            execution_identities=(
                _execution_identity(model_hash="a" * 64),
                _execution_identity(model_hash="e" * 64),
            ),
        )

    assert caught.value.reason_code == reason


@pytest.mark.parametrize("identity_field", ("budget_identity_sha256", "normalizer_identity_sha256"))
def test_model_arms_must_share_prompt_budget_normalizer_and_output_contract(
    identity_field: str,
) -> None:
    catalog, sources = _composition_inputs()
    drifted = _execution_identity(model_hash="e" * 64).model_copy(
        update={identity_field: "f" * 64}
    )

    with pytest.raises(SemanticBindingContractError) as caught:
        compose_596_1_semantic_inputs(
            catalog=catalog,
            sources=sources,
            execution_identities=(
                _execution_identity(model_hash="a" * 64),
                drifted,
            ),
        )

    assert caught.value.reason_code == "EXECUTION_CONTRACT_MISMATCH"


def _response_for_task(
    composition: object,
    sources: tuple[SemanticSourceInputV1, SemanticSourceInputV1, SemanticSourceInputV1],
    *,
    task_index: int,
    arm_index: int = 0,
) -> tuple[str, bytes]:
    from insurance_harness.knowledge_compiler.semantic_input_binding import (
        SemanticInputCompositionV1,
    )

    exact = SemanticInputCompositionV1.model_validate(composition)
    task = exact.tasks[task_index]
    arm = exact.arm_blueprints[arm_index]
    source = next(item for item in sources if item.admitted.role == task.material_role)
    document = source.admitted.document
    manifest = source.admitted.manifest
    if task.material_role == "rate_table":
        cell_fact = document.cells[0]
        content = f"{task.material_role}表头及数值一"
        locator = EvidenceLocatorSnapshotV1(
            subject_type="cell",
            subject_ref=cell_fact.cell_id,
            page_number=cell_fact.locator.page_number,
            parent_refs=(document.pages[0].page_id, cell_fact.table_id),
            content_snapshot=content,
            content_snapshot_sha256=_digest(content),
        )
        block_fact = None
    else:
        block_fact = document.blocks[0]
        cell_fact = None
        content = f"{task.material_role}第一页明确条款。"
        locator = EvidenceLocatorSnapshotV1(
            subject_type="block",
            subject_ref=block_fact.block_id,
            page_number=block_fact.locator.page_number,
            parent_refs=(document.pages[0].page_id,),
            content_snapshot=content,
            content_snapshot_sha256=_digest(content),
        )
    outputs = []
    for field_id in task.field_ids:
        evidence = FreeformEvidenceV1(
            field_id=field_id,
            source_sha256=document.subject.source_sha256,
            source_revision_id=document.subject.source_revision_id,
            parse_attempt_id=document.attempt.attempt_id,
            parsed_document_hash=document.document_hash,
            parse_manifest_hash=manifest.manifest_hash,
            page_number=locator.page_number,
            block_id=(locator.subject_ref if locator.subject_type == "block" else None),
            table_id=(cell_fact.table_id if cell_fact is not None else None),
            cell_id=(locator.subject_ref if locator.subject_type == "cell" else None),
            row_index=(cell_fact.locator.row_index if cell_fact is not None else None),
            column_index=(cell_fact.locator.column_index if cell_fact is not None else None),
            header_snapshot=(content if locator.subject_type == "cell" else None),
            row_span=(cell_fact.locator.row_span if cell_fact is not None else None),
            column_span=(cell_fact.locator.column_span if cell_fact is not None else None),
            locator=locator,
            quote_snapshot=content,
            quote_snapshot_sha256=_digest(content),
        )
        outputs.append(
            FreeformFieldOutputV1(
                product_version_id="596-1",
                field_id=field_id,
                state="present",
                value_snapshot=content,
                evidence=(evidence,),
            ).model_dump(mode="json")
        )
    payload = {
        "task_id": task.task_id,
        "attempt_hash": (
            task.initial_attempt.attempt_hash if task.initial_attempt is not None else None
        ),
        "arm_blueprint_hash": arm.blueprint_hash,
        "model_identity_sha256": arm.execution_identity.model_identity_sha256,
        "fields": outputs,
    }
    return task.task_id, json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def test_semantic_and_rate_outputs_reuse_064_exact_locator_and_054_receipt() -> None:
    catalog, sources = _composition_inputs()
    composition = compose_596_1_semantic_inputs(
        catalog=catalog,
        sources=sources,
        execution_identities=(
            _execution_identity(model_hash="a" * 64),
            _execution_identity(model_hash="e" * 64),
        ),
    )
    semantic_id, semantic_json = _response_for_task(composition, sources, task_index=0)
    rate_id, rate_json = _response_for_task(composition, sources, task_index=8)

    semantic = bind_596_1_semantic_response(
        composition=composition,
        task_id=semantic_id,
        response_json=semantic_json,
        admitted_sources=tuple(item.admitted for item in sources),
    )
    rate = bind_596_1_semantic_response(
        composition=composition,
        task_id=rate_id,
        response_json=rate_json,
        admitted_sources=tuple(item.admitted for item in sources),
    )

    assert semantic.receipt_chain is not None
    assert (
        semantic.model_identity_sha256
        == composition.arm_blueprints[0].execution_identity.model_identity_sha256
    )
    assert semantic.arm_blueprint_hash == composition.arm_blueprints[0].blueprint_hash
    assert len(semantic.evidence_receipts) == len(composition.tasks[0].field_ids)
    assert rate.receipt_chain is None
    assert rate.evidence_receipts[0].evidence[0].cell_id is not None


def test_known_output_locator_or_quote_drift_fails_closed() -> None:
    catalog, sources = _composition_inputs()
    composition = compose_596_1_semantic_inputs(
        catalog=catalog,
        sources=sources,
        execution_identities=(
            _execution_identity(model_hash="a" * 64),
            _execution_identity(model_hash="e" * 64),
        ),
    )
    task_id, response = _response_for_task(composition, sources, task_index=0)
    payload = json.loads(response)
    evidence = payload["fields"][0]["evidence"][0]
    evidence["quote_snapshot"] = "不存在的引文"
    evidence["quote_snapshot_sha256"] = _digest("不存在的引文")

    with pytest.raises(SemanticBindingContractError) as caught:
        bind_596_1_semantic_response(
            composition=composition,
            task_id=task_id,
            response_json=json.dumps(payload, ensure_ascii=False).encode(),
            admitted_sources=tuple(item.admitted for item in sources),
        )

    assert caught.value.reason_code == "SEMANTIC_EVIDENCE_MISMATCH"


def test_rate_output_requires_exact_table_cell_locator() -> None:
    catalog, sources = _composition_inputs()
    composition = compose_596_1_semantic_inputs(
        catalog=catalog,
        sources=sources,
        execution_identities=(
            _execution_identity(model_hash="a" * 64),
            _execution_identity(model_hash="e" * 64),
        ),
    )
    task_id, response = _response_for_task(composition, sources, task_index=8)
    payload = json.loads(response)
    evidence = payload["fields"][0]["evidence"][0]
    content = "rate_table第一页明确条款。"
    evidence.update(
        {
            "block_id": "rate_table-block-1",
            "table_id": None,
            "cell_id": None,
            "row_index": None,
            "column_index": None,
            "header_snapshot": None,
            "row_span": None,
            "column_span": None,
            "locator": {
                "subject_type": "block",
                "subject_ref": "rate_table-block-1",
                "page_number": 1,
                "parent_refs": ["rate_table-page-1"],
                "content_snapshot": content,
                "content_snapshot_sha256": _digest(content),
            },
            "quote_snapshot": content,
            "quote_snapshot_sha256": _digest(content),
        }
    )

    with pytest.raises(SemanticBindingContractError) as caught:
        bind_596_1_semantic_response(
            composition=composition,
            task_id=task_id,
            response_json=json.dumps(payload, separators=(",", ":")).encode(),
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_RATE_CELL_EVIDENCE_REQUIRED"


def test_arm_identity_is_not_exchangeable() -> None:
    catalog, sources = _composition_inputs()
    composition = compose_596_1_semantic_inputs(
        catalog=catalog,
        sources=sources,
        execution_identities=(
            _execution_identity(model_hash="a" * 64),
            _execution_identity(model_hash="e" * 64),
        ),
    )
    task_id, response = _response_for_task(composition, sources, task_index=0)
    payload = json.loads(response)
    payload["model_identity_sha256"] = (
        composition.arm_blueprints[1].execution_identity.model_identity_sha256
    )

    with pytest.raises(SemanticBindingContractError) as caught:
        bind_596_1_semantic_response(
            composition=composition,
            task_id=task_id,
            response_json=json.dumps(payload, separators=(",", ":")).encode(),
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_RESPONSE_INVALID"

    bound = bind_596_1_semantic_response(
        composition=composition,
        task_id=task_id,
        response_json=response,
        admitted_sources=tuple(item.admitted for item in sources),
    )
    other = composition.arm_blueprints[1]
    exchanged = bound.model_copy(
        update={
            "model_id": other.execution_identity.model_id,
            "model_identity_sha256": other.execution_identity.model_identity_sha256,
            "arm_blueprint_hash": other.blueprint_hash,
        }
    )
    with pytest.raises(ValueError, match="bound semantic attempt hash mismatch"):
        BoundSemanticAttemptV1.model_validate(
            exchanged.model_dump(exclude_computed_fields=True)
        )


def test_foreign_parse_attempt_and_unknown_cross_product_fail_closed() -> None:
    catalog, sources = _composition_inputs()
    composition = compose_596_1_semantic_inputs(
        catalog=catalog,
        sources=sources,
        execution_identities=(
            _execution_identity(model_hash="a" * 64),
            _execution_identity(model_hash="e" * 64),
        ),
    )
    task_id, response = _response_for_task(composition, sources, task_index=0)
    original = sources[0].admitted
    foreign_document = original.document.model_copy(
        update={
            "attempt": original.document.attempt.model_copy(
                update={"attempt_id": "foreign-attempt-069"}
            )
        }
    )
    profile = original.material_profile_resolution
    assert profile is not None
    foreign_manifest = build_parse_manifest(foreign_document, profile.profile)
    foreign_decision = evaluate_parse_quality(
        document=foreign_document,
        manifest=foreign_manifest,
        material_profile_resolution=profile,
    )
    foreign = replace(
        original,
        document=foreign_document,
        artifact_sha256=foreign_document.document_hash,
        manifest=foreign_manifest,
        manifest_sha256=foreign_manifest.manifest_hash,
        decision=foreign_decision,
        decision_sha256=foreign_decision.decision_hash,
    )
    with pytest.raises(SemanticBindingContractError) as caught:
        bind_596_1_semantic_response(
            composition=composition,
            task_id=task_id,
            response_json=response,
            admitted_sources=(foreign, sources[1].admitted, sources[2].admitted),
        )
    assert caught.value.reason_code == "SEMANTIC_EVIDENCE_MISMATCH"

    payload = json.loads(response)
    payload["fields"][0] = {
        "product_version_id": "596-2",
        "field_id": payload["fields"][0]["field_id"],
        "state": "unknown",
        "value_snapshot": None,
        "evidence": [],
    }
    with pytest.raises(SemanticBindingContractError) as caught:
        bind_596_1_semantic_response(
            composition=composition,
            task_id=task_id,
            response_json=json.dumps(payload, separators=(",", ":")).encode(),
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_RESPONSE_PRODUCT_VERSION_MISMATCH"


def test_composition_revalidates_content_and_binds_exact_source_identity() -> None:
    catalog, sources = _composition_inputs()
    composition = compose_596_1_semantic_inputs(
        catalog=catalog,
        sources=sources,
        execution_identities=(
            _execution_identity(model_hash="a" * 64),
            _execution_identity(model_hash="e" * 64),
        ),
    )
    drifted_source = composition.sources[0].model_copy(update={"content_snapshot": "drift"})
    drifted = composition.model_copy(
        update={"sources": (drifted_source, *composition.sources[1:])}
    )
    with pytest.raises(SemanticBindingContractError) as caught:
        bind_596_1_semantic_response(
            composition=drifted,
            task_id=composition.tasks[0].task_id,
            response_json=_response_for_task(composition, sources, task_index=0)[1],
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_RESPONSE_INVALID"


def test_full_bundle_allows_at_most_four_exact_054_repairs() -> None:
    catalog, sources = _composition_inputs()
    composition = compose_596_1_semantic_inputs(
        catalog=catalog,
        sources=sources,
        execution_identities=(
            _execution_identity(model_hash="a" * 64),
            _execution_identity(model_hash="e" * 64),
        ),
    )
    def bind_all(
        *, unresolved_count: int, arm_index: int = 0
    ) -> tuple[BoundSemanticAttemptV1, ...]:
        bound: list[BoundSemanticAttemptV1] = []
        for index, task in enumerate(composition.tasks[:8]):
            assert task.initial_attempt is not None
            if index < unresolved_count:
                _, normal_response = _response_for_task(
                    composition, sources, task_index=index, arm_index=arm_index
                )
                response = json.loads(normal_response)
                response["fields"][-1] = {
                    "product_version_id": "596-1",
                    "field_id": task.field_ids[-1],
                    "state": "unknown",
                    "value_snapshot": None,
                    "evidence": [],
                }
                response_json = json.dumps(response, separators=(",", ":")).encode()
            else:
                _, response_json = _response_for_task(
                    composition, sources, task_index=index, arm_index=arm_index
                )
            bound.append(
                bind_596_1_semantic_response(
                    composition=composition,
                    task_id=task.task_id,
                    response_json=response_json,
                    admitted_sources=tuple(item.admitted for item in sources),
                )
            )
        return tuple(bound)

    bound = bind_all(unresolved_count=4)
    assert bound[0].receipt_chain is not None
    assert {item.status for item in bound[0].receipt_chain.receipts[0].field_outcomes} == {
        "candidate",
        "unknown",
    }

    def verification_plan(
        item: BoundSemanticAttemptV1,
    ) -> tuple[VerificationBatchV1, TargetedRepairPlanV1]:
        exact = BoundSemanticAttemptV1.model_validate(
            item.model_dump(exclude_computed_fields=True)
        )
        assert exact.receipt_chain is not None
        task = next(value for value in composition.tasks if value.task_id == exact.task_id)
        source = next(value for value in sources if value.admitted.role == task.material_role)
        verification = exact.verification
        assert verification is not None
        fields = tuple(
            item.field_id for item in verification.results if item.status != "PASS"
        )
        decision = plan_targeted_repair(
            verification,
            approved_locators=tuple(
                ApprovedLocatorSetV1(
                    field_id=field_id,
                    locator_refs=(source.admitted.document.blocks[0].block_id,),
                )
                for field_id in fields
            ),
            budget=RepairBudgetV1(max_targeted_repairs=1),
            repairs_used=0,
        )
        assert decision.plan is not None
        return verification, decision.plan

    verification_plans = tuple(verification_plan(item) for item in bound[:4])
    verifications = tuple(item[0] for item in verification_plans)
    plans = tuple(item[1] for item in verification_plans)
    bundle = build_596_1_targeted_repairs(
        composition=composition,
        attempts=bound,
        locator_plans=plans,
        admitted_sources=tuple(item.admitted for item in sources),
    )
    assert isinstance(bundle, SemanticRepairBundleV1)
    assert len(bundle.repairs) == 4
    assert bundle == build_596_1_targeted_repairs(
        composition=composition,
        attempts=bound,
        locator_plans=plans,
        admitted_sources=tuple(item.admitted for item in sources),
    )
    arm1_bound = bind_all(unresolved_count=4, arm_index=1)
    arm1_verification_plans = tuple(
        verification_plan(item) for item in arm1_bound[:4]
    )
    arm1_bundle = build_596_1_targeted_repairs(
        composition=composition,
        attempts=arm1_bound,
        locator_plans=tuple(item[1] for item in arm1_verification_plans),
        admitted_sources=tuple(item.admitted for item in sources),
    )
    assert bundle.arm_blueprint_hash != arm1_bundle.arm_blueprint_hash
    assert bundle.bundle_hash != arm1_bundle.bundle_hash
    over_budget = bind_all(unresolved_count=5)
    with pytest.raises(SemanticBindingContractError) as caught:
        build_596_1_targeted_repairs(
            composition=composition,
            attempts=over_budget,
            locator_plans=tuple(
                verification_plan(item)[1] for item in over_budget[:5]
            ),
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_REPAIR_BUDGET_EXHAUSTED"

    with pytest.raises(SemanticBindingContractError) as caught:
        build_596_1_targeted_repairs(
            composition=composition,
            attempts=(bound[0], *bound[1:7], bound[0]),
            locator_plans=plans,
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_REPAIR_INVALID"

    forged_model_payload = bound[0].model_dump(
        exclude={"bound_attempt_hash"}, exclude_computed_fields=True
    )
    forged_model_payload["model_id"] = "caller-forged-model"
    forged_model_hash_payload = semantic_module._bound_attempt_payload(
        task_id=bound[0].task_id,
        composition_hash=bound[0].composition_hash,
        model_id="caller-forged-model",
        model_identity_sha256=bound[0].model_identity_sha256,
        arm_blueprint_hash=bound[0].arm_blueprint_hash,
        normalizer_identity_sha256=bound[0].normalizer_identity_sha256,
        receipt_chain=bound[0].receipt_chain,
        evidence_receipts=bound[0].evidence_receipts,
        verification=bound[0].verification,
    )
    forged_model = BoundSemanticAttemptV1(
        **forged_model_payload,
        bound_attempt_hash=canonical_hash(
            semantic_module.BOUND_SEMANTIC_ATTEMPT_OBJECT_TYPE,
            forged_model_hash_payload,
        ),
    )
    with pytest.raises(SemanticBindingContractError) as caught:
        build_596_1_targeted_repairs(
            composition=composition,
            attempts=(forged_model, *bound[1:]),
            locator_plans=plans,
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_REPAIR_INVALID"

    missing_payload = bound[0].model_dump(
        exclude={"bound_attempt_hash", "receipt_chain"},
        exclude_computed_fields=True,
    )
    missing_hash_payload = semantic_module._bound_attempt_payload(
        task_id=bound[0].task_id,
        composition_hash=bound[0].composition_hash,
        model_id=bound[0].model_id,
        model_identity_sha256=bound[0].model_identity_sha256,
        arm_blueprint_hash=bound[0].arm_blueprint_hash,
        normalizer_identity_sha256=bound[0].normalizer_identity_sha256,
        receipt_chain=None,
        evidence_receipts=bound[0].evidence_receipts,
        verification=bound[0].verification,
    )
    missing_receipt = BoundSemanticAttemptV1(
        **missing_payload,
        receipt_chain=None,
        bound_attempt_hash=canonical_hash(
            semantic_module.BOUND_SEMANTIC_ATTEMPT_OBJECT_TYPE, missing_hash_payload
        ),
    )
    with pytest.raises(SemanticBindingContractError) as caught:
        build_596_1_targeted_repairs(
            composition=composition,
            attempts=(missing_receipt, *bound[1:]),
            locator_plans=plans,
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_REPAIR_INVALID"

    with pytest.raises(SemanticBindingContractError) as caught:
        build_596_1_targeted_repairs(
            composition=composition,
            attempts=bound[:4],
            locator_plans=plans,
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_REPAIR_INVALID"

    arm1_task_id, arm1_response = _response_for_task(
        composition, sources, task_index=0, arm_index=1
    )
    cross_arm_bound = bind_596_1_semantic_response(
        composition=composition,
        task_id=arm1_task_id,
        response_json=arm1_response,
        admitted_sources=tuple(item.admitted for item in sources),
    )
    with pytest.raises(SemanticBindingContractError) as caught:
        build_596_1_targeted_repairs(
            composition=composition,
            attempts=(cross_arm_bound, *bound[1:]),
            locator_plans=plans[1:],
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_REPAIR_INVALID"

    invalid = plans[0].model_copy(
        update={
            "approved_locators": tuple(
                item.model_copy(update={"locator_refs": ("missing-locator",)})
                for item in plans[0].approved_locators
            )
        }
    )
    with pytest.raises(SemanticBindingContractError) as caught:
        build_596_1_targeted_repairs(
            composition=composition,
            attempts=bound,
            locator_plans=(invalid, *plans[1:]),
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_REPAIR_INVALID"

    contradictory_unknown = bind_freeform_arm_evidence(
        field_output=FreeformFieldOutputV1(
            product_version_id=bound[0].evidence_receipts[0].product_version_id,
            field_id=bound[0].evidence_receipts[0].field_id,
            state="unknown",
            value_snapshot=None,
            evidence=(),
        ),
        documents=(),
        manifests=(),
    )
    contradictory_receipts = (
        contradictory_unknown,
        *bound[0].evidence_receipts[1:],
    )
    contradictory_payload = bound[0].model_dump(
        exclude={"bound_attempt_hash", "evidence_receipts"},
        exclude_computed_fields=True,
    )
    contradictory_hash_payload = semantic_module._bound_attempt_payload(
        task_id=bound[0].task_id,
        composition_hash=bound[0].composition_hash,
        model_id=bound[0].model_id,
        model_identity_sha256=bound[0].model_identity_sha256,
        arm_blueprint_hash=bound[0].arm_blueprint_hash,
        normalizer_identity_sha256=bound[0].normalizer_identity_sha256,
        receipt_chain=bound[0].receipt_chain,
        evidence_receipts=contradictory_receipts,
        verification=bound[0].verification,
    )
    contradictory_bound = BoundSemanticAttemptV1(
        **contradictory_payload,
        evidence_receipts=contradictory_receipts,
        bound_attempt_hash=canonical_hash(
            semantic_module.BOUND_SEMANTIC_ATTEMPT_OBJECT_TYPE,
            contradictory_hash_payload,
        ),
    )
    with pytest.raises(SemanticBindingContractError) as caught:
        build_596_1_targeted_repairs(
            composition=composition,
            attempts=(contradictory_bound, *bound[1:]),
            locator_plans=plans,
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_REPAIR_INVALID"

    forged_verification = VerificationBatchV1(
        contract="evidence-verification-batch.v1",
        product_version_id=verifications[0].product_version_id,
        source_revision_id=verifications[0].source_revision_id,
        parse_attempt_id=verifications[0].parse_attempt_id,
        parsed_document_hash=verifications[0].parsed_document_hash,
        parse_manifest_hash=verifications[0].parse_manifest_hash,
        results=tuple(
            (
                item
                if item.status == "PASS"
                else item.model_copy(update={"reason_codes": ("foreign_failure",)})
            )
            for item in verifications[0].results
        ),
    )
    forged_decision = plan_targeted_repair(
        forged_verification,
        approved_locators=plans[0].approved_locators,
        budget=RepairBudgetV1(max_targeted_repairs=1),
        repairs_used=0,
    )
    assert forged_decision.plan is not None
    forged_bound_payload = bound[0].model_dump(
        exclude={"bound_attempt_hash", "verification"},
        exclude_computed_fields=True,
    )
    forged_bound_hash_payload = semantic_module._bound_attempt_payload(
        task_id=bound[0].task_id,
        composition_hash=bound[0].composition_hash,
        model_id=bound[0].model_id,
        model_identity_sha256=bound[0].model_identity_sha256,
        arm_blueprint_hash=bound[0].arm_blueprint_hash,
        normalizer_identity_sha256=bound[0].normalizer_identity_sha256,
        receipt_chain=bound[0].receipt_chain,
        evidence_receipts=bound[0].evidence_receipts,
        verification=forged_verification,
    )
    forged_bound = BoundSemanticAttemptV1(
        **forged_bound_payload,
        verification=forged_verification,
        bound_attempt_hash=canonical_hash(
            semantic_module.BOUND_SEMANTIC_ATTEMPT_OBJECT_TYPE,
            forged_bound_hash_payload,
        ),
    )
    with pytest.raises(SemanticBindingContractError) as caught:
        build_596_1_targeted_repairs(
            composition=composition,
            attempts=(forged_bound, *bound[1:]),
            locator_plans=(forged_decision.plan, *plans[1:]),
            admitted_sources=tuple(item.admitted for item in sources),
        )
    assert caught.value.reason_code == "SEMANTIC_REPAIR_INVALID"
