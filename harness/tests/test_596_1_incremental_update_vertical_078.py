"""OpenSpec 078: deterministic synthetic 596-1 incremental vertical."""

import hashlib
import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

import insurance_harness.knowledge_compiler.incremental_update_596_1 as incremental_module
from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    CandidateValueV1,
    EvidenceLocatorSnapshotV1,
    EvidenceSnapshotV1,
    EvidenceSupportScopeV1,
    FieldCandidateV1,
    FieldRuleV1,
    VerificationBatchV1,
    value_snapshot,
    verify_evidence_batch,
)
from insurance_harness.compiler.extraction_receipts import (
    FieldOutcomeV1,
    ReceiptChainV1,
    build_attempt_receipt,
    build_initial_attempt,
)
from insurance_harness.compiler.extraction_tasks import (
    ArtifactRefV1,
    AttemptBudgetV1,
    ParsedArtifactAdmissionPort,
    build_extraction_task,
    build_extraction_task_profile,
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
    ParsedDocumentV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParseQualityDecisionV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    ParseTableV1,
    TableLocatorV1,
    build_parse_manifest,
    evaluate_parse_quality,
)
from insurance_harness.knowledge_compiler.candidate_batches import (
    FactVerificationLinkV1,
    HumanBatchPolicyV1,
)
from insurance_harness.knowledge_compiler.incremental_changes import VerifiedFactV1
from insurance_harness.knowledge_compiler.incremental_update_596_1 import (
    IncrementalUpdateFixtureError,
    IncrementalUpdatePreimageV1,
    IncrementalUpdateReceiptV1,
    RetractionVerificationLinkV1,
    run_incremental_update_fixture,
)
from insurance_harness.knowledge_compiler.retractions import RetractionProofV1
from insurance_harness.knowledge_compiler.source_authority import (
    FactScopeV1,
    MaterialBindingReceiptV1,
    SourceAuthorityV1,
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

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "incremental_update_596_1_078.json"
CATALOG_PATH = Path(__file__).parent / "fixtures" / "material_profile_596_1_052.json"
HASH_A = "a" * 64
VALUE_OBJECT_TYPE = "s0q-5961-synthetic-value.v1"
EVIDENCE_OBJECT_TYPE = "s0q-5961-synthetic-evidence.v1"


class _MemoryTemplateCatalog:
    def __init__(self, entry: TemplateCatalogEntry) -> None:
        self.entry = entry

    def get_approved(self, scope: TemplateScope) -> TemplateCatalogEntry | None:
        return self.entry if scope == self.entry.version.scope else None


@lru_cache(maxsize=1)
def _catalog() -> MaterialProfileCatalog:
    return load_material_profile_catalog(CATALOG_PATH)


@lru_cache(maxsize=1)
def _template_catalog() -> _MemoryTemplateCatalog:
    return _build_template_catalog(_catalog())


def _build_template_catalog(catalog: MaterialProfileCatalog) -> _MemoryTemplateCatalog:
    scope = TemplateScope(space_id="space-078-fixture", level="global")
    content = TemplatePackageContent(
        schema_version=catalog.schema_binding.schema_version,
        field_groups=(
            FieldGroup(
                group_id="synthetic-596-1-all-fields",
                field_ids=catalog.schema_binding.field_ids,
                evidence_roles=("terms", "brochure", "rate_table"),
            ),
        ),
        role_prompts={"extract": "synthetic fixture only"},
        validators=(
            ValidatorRef(
                validator_id="synthetic-078-validator",
                validator_version="v1",
                config_hash=HASH_A,
            ),
        ),
        evidence_policy=EvidencePolicy(
            require_quote=True,
            require_locator=True,
            minimum_sources=1,
        ),
        attempt_limits={"extract": 1},
        golden_slice_ref="synthetic-no-golden-values",
        provenance=(
            ProvenanceReceipt(
                migration_id="MIG-078-synthetic",
                source_repository="silvielala412-lab/LLM-wiki-black",
                source_branch="feature/product-catalog-domain",
                source_commit="6a8a1d98de405b6a2837090ee2d43769b4c89be7",
                source_path="frontend/src/lib/product-catalog-modules.ts",
                source_language="typescript",
                rights_status="project-owned",
                accepted_behavior="synthetic 4 affected plus 56 unchanged partition",
                rejected_behavior="real product truth or Golden expected answers",
                python_target=(
                    "harness/src/insurance_harness/knowledge_compiler/incremental_update_596_1.py"
                ),
                translation_method="behavior_port_with_characterization_tests",
                characterization_tests=(
                    "harness/tests/test_596_1_incremental_update_vertical_078.py",
                ),
            ),
        ),
    )
    version = TemplateVersion.from_content(
        package_id="synthetic-596-1-template",
        version_id="078-v1",
        scope=scope,
        content=content,
    )
    return _MemoryTemplateCatalog(
        TemplateCatalogEntry(
            version=version,
            approval=TemplateApproval(
                approval_id="synthetic-078-approval",
                package_id=version.package_id,
                version_id=version.version_id,
                scope=scope,
                content_hash=version.content_hash,
                state="approved",
            ),
        )
    )


@lru_cache(maxsize=1)
def _resolutions() -> tuple[MaterialProfileResolution, ...]:
    catalog = _catalog()
    return tuple(
        resolve_material_profile(
            catalog,
            _template_catalog(),
            MaterialProfileResolutionRequest(
                space_id="space-078-fixture",
                product_code="596",
                product_version="596-1",
                schema_version=catalog.schema_binding.schema_version,
                schema_field_ids=catalog.schema_binding.field_ids,
                source=profile.source,
                classified_material_role=profile.material_role,
            ),
        )
        for profile in catalog.profiles
    )


def _resolution(role: str) -> MaterialProfileResolution:
    return next(item for item in _resolutions() if item.profile.material_role == role)


def _synthetic_hash(object_type: str, **payload: str) -> str:
    return canonical_hash(object_type, payload)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _quote(field_id: str, revision: str, tag: str) -> str:
    return f"synthetic-evidence:{field_id}:{revision}:{tag}"


def _evidence_hash(field_id: str, revision: str, tag: str) -> str:
    return _synthetic_hash(
        EVIDENCE_OBJECT_TYPE,
        field_id=field_id,
        source_revision_id=revision,
        quote_sha256=_hash_text(_quote(field_id, revision, tag)),
    )


def _scope(field_id: str) -> FactScopeV1:
    return FactScopeV1(
        space_id="space-078-fixture",
        product_version_id="596-1",
        subject_id="product:596-1:synthetic-fixture",
        field_id=field_id,
        valid_from="2026-01-01T00:00:00.000000Z",
        valid_through=None,
        region="CN",
        channel="all-approved-channels",
        population="eligible-insured",
        conditions=("plan=synthetic-standard",),
    )


def _authority(
    resolution: MaterialProfileResolution,
    revision: str,
    reliable_at: str,
) -> SourceAuthorityV1:
    return SourceAuthorityV1(
        source_id=resolution.profile.source.sha256,
        source_revision_id=revision,
        material_role=resolution.profile.material_role,
        binding=MaterialBindingReceiptV1(
            catalog_hash=resolution.catalog_hash,
            binding_hash=resolution.binding_hash,
            space_id="space-078-fixture",
            product_version_id="596-1",
            source_id=resolution.profile.source.sha256,
            source_revision_id=revision,
            material_role=resolution.profile.material_role,
        ),
        reliable_at=reliable_at,
    )


def _fact(
    *,
    field_id: str,
    tag: str,
    resolution: MaterialProfileResolution,
    revision: str,
    reliable_at: str,
) -> VerifiedFactV1:
    return VerifiedFactV1(
        scope=_scope(field_id),
        state="known",
        value_hash=_synthetic_hash(VALUE_OBJECT_TYPE, field_id=field_id, tag=tag),
        authority=_authority(resolution, revision, reliable_at),
        evidence_hashes=(_evidence_hash(field_id, revision, tag),),
        supporting_source_revision_ids=(revision,),
    )


def _fact_inputs() -> tuple[
    tuple[VerifiedFactV1, ...],
    tuple[VerifiedFactV1, ...],
    tuple[RetractionProofV1, ...],
    dict[str, str],
]:
    payload = _fixture_payload()
    fields = cast(list[str], payload["field_ids"])
    scenarios = {
        cast(str, item["field_id"]): item
        for item in cast(list[dict[str, object]], payload["affected"])
    }
    by_role = {item.profile.material_role: item for item in _resolutions()}
    baseline: list[VerifiedFactV1] = []
    candidates: list[VerifiedFactV1] = []
    tags: dict[str, str] = {}
    old_time = "2026-01-01T00:00:00.000000Z"
    new_time = "2026-02-01T00:00:00.000000Z"
    for field_id in fields:
        scenario = scenarios.get(field_id)
        if scenario is None:
            role = _catalog().authority_for(field_id).primary_role
            tag = f"synthetic-unchanged-{field_id}"
            fact = _fact(
                field_id=field_id,
                tag=tag,
                resolution=by_role[role],
                revision=f"revision-078-{role}-unchanged",
                reliable_at=old_time,
            )
            baseline.append(fact)
            tags[fact.fact_hash] = tag
            continue
        action = cast(str, scenario["action"])
        baseline_role = "brochure" if action == "supersede" else "terms"
        baseline_tag = cast(str, scenario["baseline_value_tag"])
        prior = _fact(
            field_id=field_id,
            tag=baseline_tag,
            resolution=_resolution(baseline_role),
            revision=f"revision-078-{baseline_role}-old",
            reliable_at=old_time,
        )
        baseline.append(prior)
        tags[prior.fact_hash] = baseline_tag
        if action != "retract":
            candidate_tag = cast(str, scenario["candidate_value_tag"])
            incoming = _fact(
                field_id=field_id,
                tag=candidate_tag,
                resolution=by_role["terms"],
                revision="revision-078-terms-new",
                reliable_at=old_time if action == "conflict" else new_time,
            )
            candidates.append(incoming)
            tags[incoming.fact_hash] = candidate_tag
    retract_field = "zh_f32c510a5e"
    proof = RetractionProofV1(
        scope=_scope(retract_field),
        old_source_revision_id="revision-078-terms-old",
        replacement_authority=_authority(by_role["terms"], "revision-078-terms-new", new_time),
        complete_scope=True,
        explicitly_absent=True,
        evidence_hash=_synthetic_hash(
            "s0q-5961-explicit-absence.v1",
            field_id=retract_field,
            source_revision_id="revision-078-terms-new",
        ),
        reason_code="source_revision_replaced",
    )
    return (
        tuple(sorted(baseline, key=lambda item: item.fact_hash)),
        tuple(sorted(candidates, key=lambda item: item.fact_hash)),
        (proof,),
        tags,
    )


@dataclass(frozen=True)
class _Bundle:
    document: ParsedDocumentV1
    manifest: ParseManifestV1
    quality: ParseQualityDecisionV1
    content_by_field: Mapping[str, str]
    block_by_field: Mapping[str, ParseBlockV1]


def _parsed_bundle(
    resolution: MaterialProfileResolution,
    facts: tuple[VerifiedFactV1, ...],
    tags: Mapping[str, str],
) -> _Bundle:
    revision = facts[0].authority.source_revision_id
    page_count = 2 if "cross_page_sections" in resolution.profile.required_parse_capabilities else 1
    pages = tuple(
        ParsePageV1(
            page_id=f"page:{revision}:{number}",
            order_index=number - 1,
            locator=PageLocatorV1(page_number=number),
            content_hash=_synthetic_hash(
                "s0q-5961-page-content.v1", revision=revision, page=str(number)
            ),
            structure_hash=_synthetic_hash(
                "s0q-5961-page-structure.v1", revision=revision, page=str(number)
            ),
        )
        for number in range(1, page_count + 1)
    )
    facts = tuple(sorted(facts, key=lambda item: item.scope.field_id))
    content_by_field = {
        fact.scope.field_id: _quote(fact.scope.field_id, revision, tags[fact.fact_hash])
        for fact in facts
    }
    if revision == "revision-078-terms-new":
        content_by_field["zh_f32c510a5e"] = "synthetic-explicit-absence"
    ordered_content = tuple(sorted(content_by_field.items()))
    blocks = tuple(
        ParseBlockV1(
            block_id=f"block:{revision}:{field_id}",
            order_index=index,
            locator=BlockLocatorV1(
                page_number=(index % page_count) + 1,
                bbox=(Decimal("0"), Decimal("0"), Decimal("100"), Decimal("20")),
                block_index=index,
            ),
            content_hash=_hash_text(content),
            structure_hash=_synthetic_hash(
                "s0q-5961-block-structure.v1",
                revision=revision,
                field_id=field_id,
            ),
        )
        for index, (field_id, content) in enumerate(ordered_content)
    )
    table_id = f"table:{revision}:0"
    cell_id = f"cell:{revision}:0:0"
    tables = (
        ParseTableV1(
            table_id=table_id,
            order_index=0,
            locator=TableLocatorV1(
                page_number=1,
                bbox=(Decimal("0"), Decimal("20"), Decimal("100"), Decimal("80")),
                table_index=0,
            ),
            content_hash=_synthetic_hash("s0q-5961-table-content.v1", revision=revision),
            structure_hash=_synthetic_hash("s0q-5961-table-structure.v1", revision=revision),
            row_count=1,
            column_count=1,
            header_cell_ids=(cell_id,),
            continuation_table_ids=(),
        ),
    )
    cells = (
        ParseCellV1(
            cell_id=cell_id,
            order_index=0,
            table_id=table_id,
            locator=CellLocatorV1(
                page_number=1,
                bbox=(Decimal("0"), Decimal("20"), Decimal("100"), Decimal("80")),
                table_id=table_id,
                row_index=0,
                column_index=0,
                row_span=1,
                column_span=1,
            ),
            content_hash=_synthetic_hash("s0q-5961-cell-content.v1", revision=revision),
            structure_hash=_synthetic_hash("s0q-5961-cell-structure.v1", revision=revision),
        ),
    )
    capability_evidence: list[CapabilityEvidenceV1] = []
    for capability in resolution.profile.required_parse_capabilities:
        if capability == "ordered_pages":
            refs = tuple(item.page_id for item in pages)
        elif capability in {"block_locators", "cross_page_sections"}:
            refs = tuple(item.block_id for item in blocks)
        elif capability == "table_grid":
            refs = (table_id, cell_id)
        elif capability == "cell_locators":
            refs = (cell_id,)
        else:
            raise AssertionError(capability)
        capability_evidence.append(CapabilityEvidenceV1(capability=capability, subject_refs=refs))
    document = ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=ParseSubjectV1(
            space_id="space-078-fixture",
            source_id=resolution.profile.source.sha256,
            source_revision_id=revision,
            product_version_id="596-1",
            material_profile_id=resolution.profile.profile_id,
            material_profile_binding_hash=resolution.binding_hash,
            source_sha256=resolution.profile.source.sha256,
            raw_artifact_hash=_synthetic_hash("s0q-5961-raw-artifact.v1", revision=revision),
            canonical_envelope_hash=_synthetic_hash(
                "s0q-5961-canonical-envelope.v1", revision=revision
            ),
        ),
        parser=ParserIdentityV1(
            parser_id="synthetic-078-parser",
            parser_profile_ref=resolution.parse_policy_receipt.default_parser_profile_ref,
            parser_build_id="synthetic-078-build-v1",
            parser_config_hash=_synthetic_hash("s0q-5961-parser-config.v1", revision=revision),
        ),
        attempt=ParseAttemptV1(
            attempt_id=f"attempt:{revision}:1",
            attempt_number=1,
            attempt_role="default",
            generation=1,
        ),
        snapshot=ParseSnapshotV1(
            snapshot_id=f"snapshot:{revision}:1",
            snapshot_generation=1,
            pagination_complete=True,
            concurrent_mutation_fence_hash=_synthetic_hash(
                "s0q-5961-snapshot-fence.v1", revision=revision
            ),
        ),
        output_facts=ParseOutputFactsV1(
            privacy_policy_ref=resolution.parse_policy_receipt.privacy_policy_ref,
            output_policy_ref=resolution.parse_policy_receipt.output_policy_ref,
            body_text_included=False,
            secrets_included=False,
            absolute_paths_included=False,
            unknown_vendor_fields_included=False,
        ),
        pages=pages,
        blocks=blocks,
        tables=tables,
        cells=cells,
        capability_evidence=tuple(capability_evidence),
        warnings=(),
        unsupported=(),
    )
    manifest = build_parse_manifest(document, resolution.profile)
    quality = evaluate_parse_quality(
        document=document,
        manifest=manifest,
        material_profile_resolution=resolution,
    )
    assert quality.decision == "ADMIT"
    return _Bundle(
        document=document,
        manifest=manifest,
        quality=quality,
        content_by_field=content_by_field,
        block_by_field={
            field_id: block
            for (field_id, _), block in zip(ordered_content, blocks, strict=True)
        },
    )


def _verification_chain(
    fact: VerifiedFactV1,
    tag: str,
    resolution: MaterialProfileResolution,
    bundle: _Bundle,
) -> tuple[FieldCandidateV1, VerificationBatchV1, ReceiptChainV1, FactVerificationLinkV1]:
    block = bundle.block_by_field[fact.scope.field_id]
    content = bundle.content_by_field[fact.scope.field_id]
    value = CandidateValueV1(kind="enum", enum_value=tag)
    snapshot = value_snapshot(value)
    candidate = FieldCandidateV1(
        field_id=fact.scope.field_id,
        product_version_id="596-1",
        subject_id="product:596-1:synthetic-fixture",
        condition_ids=fact.scope.conditions,
        tri_state="present",
        value=value,
        evidence=(
            EvidenceSnapshotV1(
                field_id=fact.scope.field_id,
                product_version_id="596-1",
                source_revision_id=fact.authority.source_revision_id,
                parse_attempt_id=bundle.document.attempt.attempt_id,
                parsed_document_hash=bundle.document.document_hash,
                parse_manifest_hash=bundle.manifest.manifest_hash,
                locator=EvidenceLocatorSnapshotV1(
                    subject_type="block",
                    subject_ref=block.block_id,
                    page_number=block.locator.page_number,
                    parent_refs=(
                        next(
                            page.page_id
                            for page in bundle.document.pages
                            if page.locator.page_number == block.locator.page_number
                        ),
                    ),
                    content_snapshot=content,
                    content_snapshot_sha256=_hash_text(content),
                ),
                quote_snapshot=tag,
                quote_snapshot_sha256=_hash_text(tag),
                value_snapshot=snapshot,
                value_snapshot_sha256=_hash_text(snapshot),
                support_scope=EvidenceSupportScopeV1(
                    product_version_id="596-1",
                    subject_id="product:596-1:synthetic-fixture",
                    condition_ids=fact.scope.conditions,
                ),
            ),
        ),
    )
    verification = verify_evidence_batch(
        document=bundle.document,
        manifest=bundle.manifest,
        candidates=(candidate,),
        rules=(
            FieldRuleV1(
                field_id=fact.scope.field_id,
                value_kind="enum",
                allowed_values=(tag,),
                allow_absent=False,
            ),
        ),
    )
    budget = AttemptBudgetV1(max_fields=1, max_total_attempts=2, max_targeted_repairs=1)
    profile = build_extraction_task_profile(
        material_profile=resolution.profile,
        material_profile_binding_hash=resolution.binding_hash,
        parse_policy_receipt=resolution.parse_policy_receipt,
        field_authority=_catalog().authority_for(fact.scope.field_id),
        attempt_budget=budget,
    )
    refs = ParsedArtifactAdmissionPort().admitted_input_refs(
        task_profile=profile,
        space_id="space-078-fixture",
        product_version_id="596-1",
        source_revision_id=fact.authority.source_revision_id,
        source_revision=ArtifactRefV1(
            object_type="source-revision.v1",
            artifact_hash=_synthetic_hash(
                "s0q-5961-source-revision.v1",
                revision=fact.authority.source_revision_id,
            ),
        ),
        resolved_template=ArtifactRefV1(
            object_type="resolved-template.v1",
            artifact_hash=resolution.resolved_template.content_hash,
        ),
        schema_contract=ArtifactRefV1(
            object_type="schema-contract.v1",
            artifact_hash=_synthetic_hash(
                "s0q-5961-schema-contract.v1",
                schema_version="v1.1+b31a411c621c",
                field_count="60",
            ),
        ),
        document=bundle.document,
        manifest=bundle.manifest,
        quality_decision=bundle.quality,
    )
    task = build_extraction_task(
        space_id="space-078-fixture",
        product_version_id="596-1",
        source_revision_id=fact.authority.source_revision_id,
        material_role=resolution.profile.material_role,
        module_id="078-synthetic-incremental-update",
        risk_partition_id=f"field:{fact.scope.field_id}",
        field_ids=(fact.scope.field_id,),
        input_refs=refs,
        budget=budget,
        task_profile=profile,
    )
    attempt = build_initial_attempt(task)
    verified = verification.results[0]
    receipt = build_attempt_receipt(
        attempt,
        field_outcomes=(
            FieldOutcomeV1(
                field_id=fact.scope.field_id,
                status="candidate",
                candidate_ref=ArtifactRefV1(
                    object_type="verified-field-candidate.v1",
                    artifact_hash=verified.candidate_snapshot_hash,
                ),
                reason_code=None,
            ),
        ),
        outcome="completed",
        reason_code=None,
    )
    chain = ReceiptChainV1(task=task, task_hash=task.task_hash, receipts=(receipt,))
    link = FactVerificationLinkV1(
        fact_hash=fact.fact_hash,
        verification_hash=verification.verification_hash,
        field_id=fact.scope.field_id,
        candidate_snapshot_hash=verified.candidate_snapshot_hash,
    )
    return candidate, verification, chain, link


def _absence_verification_chain(
    resolution: MaterialProfileResolution,
    bundle: _Bundle,
) -> tuple[FieldCandidateV1, VerificationBatchV1, ReceiptChainV1]:
    field_id = "zh_f32c510a5e"
    revision = "revision-078-terms-new"
    marker = "synthetic-explicit-absence"
    block = bundle.block_by_field[field_id]
    conditions = _scope(field_id).conditions
    value_wire = value_snapshot(None)
    candidate = FieldCandidateV1(
        field_id=field_id,
        product_version_id="596-1",
        subject_id="product:596-1:synthetic-fixture",
        condition_ids=conditions,
        tri_state="absent_explicitly",
        value=None,
        evidence=(
            EvidenceSnapshotV1(
                field_id=field_id,
                product_version_id="596-1",
                source_revision_id=revision,
                parse_attempt_id=bundle.document.attempt.attempt_id,
                parsed_document_hash=bundle.document.document_hash,
                parse_manifest_hash=bundle.manifest.manifest_hash,
                locator=EvidenceLocatorSnapshotV1(
                    subject_type="block",
                    subject_ref=block.block_id,
                    page_number=block.locator.page_number,
                    parent_refs=(
                        next(
                            page.page_id
                            for page in bundle.document.pages
                            if page.locator.page_number == block.locator.page_number
                        ),
                    ),
                    content_snapshot=marker,
                    content_snapshot_sha256=_hash_text(marker),
                ),
                quote_snapshot=marker,
                quote_snapshot_sha256=_hash_text(marker),
                value_snapshot=value_wire,
                value_snapshot_sha256=_hash_text(value_wire),
                support_scope=EvidenceSupportScopeV1(
                    product_version_id="596-1",
                    subject_id="product:596-1:synthetic-fixture",
                    condition_ids=conditions,
                ),
            ),
        ),
    )
    verification = verify_evidence_batch(
        document=bundle.document,
        manifest=bundle.manifest,
        candidates=(candidate,),
        rules=(
            FieldRuleV1(
                field_id=field_id,
                value_kind="enum",
                allowed_values=(marker,),
                absence_markers=(marker,),
                allow_absent=True,
            ),
        ),
    )
    budget = AttemptBudgetV1(max_fields=1, max_total_attempts=2, max_targeted_repairs=1)
    profile = build_extraction_task_profile(
        material_profile=resolution.profile,
        material_profile_binding_hash=resolution.binding_hash,
        parse_policy_receipt=resolution.parse_policy_receipt,
        field_authority=_catalog().authority_for(field_id),
        attempt_budget=budget,
    )
    refs = ParsedArtifactAdmissionPort().admitted_input_refs(
        task_profile=profile,
        space_id="space-078-fixture",
        product_version_id="596-1",
        source_revision_id=revision,
        source_revision=ArtifactRefV1(
            object_type="source-revision.v1",
            artifact_hash=_synthetic_hash("s0q-5961-source-revision.v1", revision=revision),
        ),
        resolved_template=ArtifactRefV1(
            object_type="resolved-template.v1",
            artifact_hash=resolution.resolved_template.content_hash,
        ),
        schema_contract=ArtifactRefV1(
            object_type="schema-contract.v1",
            artifact_hash=_synthetic_hash(
                "s0q-5961-schema-contract.v1",
                schema_version="v1.1+b31a411c621c",
                field_count="60",
            ),
        ),
        document=bundle.document,
        manifest=bundle.manifest,
        quality_decision=bundle.quality,
    )
    task = build_extraction_task(
        space_id="space-078-fixture",
        product_version_id="596-1",
        source_revision_id=revision,
        material_role=resolution.profile.material_role,
        module_id="078-synthetic-incremental-update",
        risk_partition_id=f"field:{field_id}:explicit-absence",
        field_ids=(field_id,),
        input_refs=refs,
        budget=budget,
        task_profile=profile,
    )
    attempt = build_initial_attempt(task)
    receipt = build_attempt_receipt(
        attempt,
        field_outcomes=(
            FieldOutcomeV1(
                field_id=field_id,
                status="candidate",
                candidate_ref=ArtifactRefV1(
                    object_type="verified-field-candidate.v1",
                    artifact_hash=candidate.candidate_snapshot_hash,
                ),
                reason_code=None,
            ),
        ),
        outcome="completed",
        reason_code=None,
    )
    chain = ReceiptChainV1(task=task, task_hash=task.task_hash, receipts=(receipt,))
    return candidate, verification, chain


@lru_cache(maxsize=1)
def _preimage() -> IncrementalUpdatePreimageV1:
    baseline, candidates, proofs, tags = _fact_inputs()
    affected_fields = {
        "clause_version",
        "zh_1ec5e3f2cc",
        "zh_3d8424595d",
        "zh_f32c510a5e",
    }
    facts = tuple(
        sorted(
            (fact for fact in (*baseline, *candidates) if fact.scope.field_id in affected_fields),
            key=lambda item: item.fact_hash,
        )
    )
    grouped: dict[tuple[str, str], list[VerifiedFactV1]] = {}
    for fact in facts:
        grouped.setdefault(
            (fact.authority.material_role, fact.authority.source_revision_id), []
        ).append(fact)
    bundles = {
        key: _parsed_bundle(_resolution(key[0]), tuple(group), tags)
        for key, group in grouped.items()
    }
    verifications: list[VerificationBatchV1] = []
    chains: list[ReceiptChainV1] = []
    links: list[FactVerificationLinkV1] = []
    field_candidates: list[FieldCandidateV1] = []
    for fact in facts:
        key = (fact.authority.material_role, fact.authority.source_revision_id)
        candidate, verification, chain, link = _verification_chain(
            fact, tags[fact.fact_hash], _resolution(key[0]), bundles[key]
        )
        field_candidates.append(candidate)
        verifications.append(verification)
        chains.append(chain)
        links.append(link)
    terms_new_bundle = bundles[("terms", "revision-078-terms-new")]
    absence_candidate, absence_verification, absence_chain = _absence_verification_chain(
        _resolution("terms"), terms_new_bundle
    )
    field_candidates.append(absence_candidate)
    verifications.append(absence_verification)
    chains.append(absence_chain)
    known_candidates_by_scope = {
        (item.field_id, item.evidence[0].source_revision_id): item
        for item in field_candidates
        if item.tri_state == "present"
    }
    fact_hash_replacements: dict[str, str] = {}

    def bind_fact_evidence(fact: VerifiedFactV1) -> VerifiedFactV1:
        candidate = known_candidates_by_scope.get(
            (fact.scope.field_id, fact.authority.source_revision_id)
        )
        if candidate is None:
            return fact
        bound = VerifiedFactV1.model_validate(
            {
                **fact.model_dump(mode="python", exclude_computed_fields=True),
                "evidence_hashes": (
                    canonical_hash(
                        "s0q-5961-known-evidence-snapshot.v1",
                        candidate.evidence[0].model_dump(mode="python"),
                    ),
                ),
            }
        )
        fact_hash_replacements[fact.fact_hash] = bound.fact_hash
        return bound

    baseline = tuple(
        sorted((bind_fact_evidence(item) for item in baseline), key=lambda x: x.fact_hash)
    )
    candidates = tuple(
        sorted((bind_fact_evidence(item) for item in candidates), key=lambda x: x.fact_hash)
    )
    links = [
        item.model_copy(
            update={"fact_hash": fact_hash_replacements.get(item.fact_hash, item.fact_hash)}
        )
        for item in links
    ]
    absence_evidence_hash = canonical_hash(
        "s0q-5961-explicit-absence-evidence.v1",
        absence_candidate.evidence[0].model_dump(mode="python"),
    )
    proof = RetractionProofV1.model_validate(
        {
            **proofs[0].model_dump(mode="python", exclude_computed_fields=True),
            "evidence_hash": absence_evidence_hash,
        }
    )
    retraction_link = RetractionVerificationLinkV1(
        field_id="zh_f32c510a5e",
        proof_hash=proof.proof_hash,
        evidence_hash=absence_evidence_hash,
        candidate_snapshot_hash=absence_candidate.candidate_snapshot_hash,
        verification_hash=absence_verification.verification_hash,
        task_hash=absence_chain.task_hash,
        receipt_hash=absence_chain.receipts[-1].receipt_hash,
    )
    return IncrementalUpdatePreimageV1(
        contract="596-1-incremental-update-preimage.v1",
        baseline_facts=baseline,
        baseline_fact_hashes=tuple(sorted(item.fact_hash for item in baseline)),
        candidate_facts=candidates,
        retraction_proofs=(proof,),
        parsed_documents=tuple(bundle.document for bundle in bundles.values()),
        parse_manifests=tuple(bundle.manifest for bundle in bundles.values()),
        parse_quality_decisions=tuple(bundle.quality for bundle in bundles.values()),
        field_candidates=tuple(field_candidates),
        verification_batches=tuple(verifications),
        receipt_chains=tuple(chains),
        fact_verification_links=tuple(links),
        retraction_verification_link=retraction_link,
        repair_resolutions=(),
        review_policy=HumanBatchPolicyV1(
            policy_id="078-synthetic-review-policy-v1",
            high_risk_field_ids=("zh_f32c510a5e",),
        ),
    )


@lru_cache(maxsize=1)
def _result() -> IncrementalUpdateReceiptV1:
    return run_incremental_update_fixture(
        FIXTURE_PATH,
        material_profile_catalog=_catalog(),
        material_profile_resolutions=_resolutions(),
        preimage=_preimage(),
    )


def _fixture_payload() -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(FIXTURE_PATH.read_text(encoding="utf-8")),
    )


def _write_fixture(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "fixture.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path


def test_task_local_runner_is_the_single_public_entrypoint() -> None:
    assert callable(run_incremental_update_fixture)
    assert FIXTURE_PATH.is_file()


def test_runner_requires_caller_provided_frozen_custody() -> None:
    assert "preimage" in inspect.signature(run_incremental_update_fixture).parameters
    with pytest.raises(
        IncrementalUpdateFixtureError,
        match="INCREMENTAL_CUSTODY_INVALID",
    ):
        run_incremental_update_fixture(
            FIXTURE_PATH,
            material_profile_catalog=_catalog(),
            material_profile_resolutions=_resolutions(),
        )


def test_exact_schema60_authority_is_task_local_and_not_self_consistent_only() -> None:
    assert incremental_module.EXPECTED_SCHEMA60_FIELD_IDS_HASH == (
        "a57d3bddd20e718907d641742b5072cf42845f51f77cd4b0d5d9752a661d0f70"
    )


def test_preimage_requires_exact_057_field_candidate_preimages() -> None:
    assert "field_candidates" in IncrementalUpdatePreimageV1.model_fields
    assert len(_preimage().field_candidates) == 8


def test_retract_requires_an_independent_absence_verification_link() -> None:
    assert "retraction_verification_link" in IncrementalUpdatePreimageV1.model_fields
    assert len(_preimage().verification_batches) == 8
    assert len(_preimage().receipt_chains) == 8


def test_fully_recomputed_schema60_replacement_fails_before_preimage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_payload = _fixture_payload()
    original_field = cast(list[str], fixture_payload["field_ids"])[0]
    replacement_field = "synthetic-recomputed-schema-field"
    fixture_payload["field_ids"] = [
        replacement_field if field_id == original_field else field_id
        for field_id in cast(list[str], fixture_payload["field_ids"])
    ]
    catalog_payload = _catalog().model_dump(
        mode="python", exclude_computed_fields=True
    )
    catalog_payload["schema_binding"]["field_ids"] = tuple(
        cast(list[str], fixture_payload["field_ids"])
    )
    for group in catalog_payload["field_authority_groups"]:
        group["field_ids"] = tuple(
            replacement_field if field_id == original_field else field_id
            for field_id in group["field_ids"]
        )
    catalog = MaterialProfileCatalog.model_validate(catalog_payload)
    template_catalog = _build_template_catalog(catalog)
    resolutions = tuple(
        resolve_material_profile(
            catalog,
            template_catalog,
            MaterialProfileResolutionRequest(
                space_id="space-078-fixture",
                product_code="596",
                product_version="596-1",
                schema_version=catalog.schema_binding.schema_version,
                schema_field_ids=catalog.schema_binding.field_ids,
                source=profile.source,
                classified_material_role=profile.material_role,
            ),
        )
        for profile in catalog.profiles
    )
    monkeypatch.setattr(
        incremental_module,
        "_revalidate_preimage",
        lambda _: (_ for _ in ()).throw(AssertionError("preimage reached")),
    )

    with pytest.raises(
        IncrementalUpdateFixtureError,
        match="SCHEMA60_AUTHORITY_DRIFT",
    ):
        run_incremental_update_fixture(
            _write_fixture(tmp_path, fixture_payload),
            material_profile_catalog=catalog,
            material_profile_resolutions=resolutions,
            preimage=_preimage(),
        )


def test_recomputed_candidate_batch_link_and_receipt_cannot_replace_057_preimage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preimage = _preimage()
    old_link = preimage.fact_verification_links[0]
    old_candidate = next(
        item
        for item in preimage.field_candidates
        if item.candidate_snapshot_hash == old_link.candidate_snapshot_hash
    )
    old_batch = next(
        item
        for item in preimage.verification_batches
        if item.verification_hash == old_link.verification_hash
    )
    document = next(
        item
        for item in preimage.parsed_documents
        if item.document_hash == old_batch.parsed_document_hash
    )
    manifest = next(
        item
        for item in preimage.parse_manifests
        if item.manifest_hash == old_batch.parse_manifest_hash
    )
    assert old_candidate.value is not None
    assert old_candidate.value.enum_value is not None
    old_tag = old_candidate.value.enum_value
    old_evidence = old_candidate.evidence[0]
    replacement_conditions = ("plan=synthetic-standard", "segment=variant")
    replacement_evidence = old_evidence.model_copy(
        update={
            "support_scope": old_evidence.support_scope.model_copy(
                update={"condition_ids": replacement_conditions}
            ),
        }
    )
    replacement_candidate = old_candidate.model_copy(
        update={
            "condition_ids": replacement_conditions,
            "evidence": (replacement_evidence,),
        }
    )
    replacement_batch = verify_evidence_batch(
        document=document,
        manifest=manifest,
        candidates=(replacement_candidate,),
        rules=(
            FieldRuleV1(
                field_id=replacement_candidate.field_id,
                value_kind="enum",
                allowed_values=(old_tag,),
                allow_absent=False,
            ),
        ),
    )
    assert replacement_batch.results[0].status == "PASS"
    old_chain = next(
        item
        for item in preimage.receipt_chains
        if item.task.field_ids == (old_link.field_id,)
        and item.task.source_revision_id == old_batch.source_revision_id
    )
    replacement_receipt = build_attempt_receipt(
        build_initial_attempt(old_chain.task),
        field_outcomes=(
            FieldOutcomeV1(
                field_id=replacement_candidate.field_id,
                status="candidate",
                candidate_ref=ArtifactRefV1(
                    object_type="verified-field-candidate.v1",
                    artifact_hash=replacement_candidate.candidate_snapshot_hash,
                ),
                reason_code=None,
            ),
        ),
        outcome="completed",
        reason_code=None,
    )
    replacement_chain = ReceiptChainV1(
        task=old_chain.task,
        task_hash=old_chain.task_hash,
        receipts=(replacement_receipt,),
    )
    replacement_link = old_link.model_copy(
        update={
            "candidate_snapshot_hash": replacement_candidate.candidate_snapshot_hash,
            "verification_hash": replacement_batch.verification_hash,
        }
    )
    update = {
        "field_candidates": tuple(
            replacement_candidate if item == old_candidate else item
            for item in preimage.field_candidates
        ),
        "verification_batches": tuple(
            replacement_batch if item == old_batch else item
            for item in preimage.verification_batches
        ),
        "receipt_chains": tuple(
            replacement_chain if item == old_chain else item
            for item in preimage.receipt_chains
        ),
        "fact_verification_links": tuple(
            replacement_link if item == old_link else item
            for item in preimage.fact_verification_links
        ),
    }
    monkeypatch.setattr(
        incremental_module,
        "build_fixture_candidate_batch",
        lambda **_: (_ for _ in ()).throw(AssertionError("candidate reached")),
    )

    with pytest.raises(
        IncrementalUpdateFixtureError,
        match="FIELD_CANDIDATE_CUSTODY_DRIFT|VERIFICATION_REPLAY_DRIFT",
    ):
        run_incremental_update_fixture(
            FIXTURE_PATH,
            material_profile_catalog=_catalog(),
            material_profile_resolutions=_resolutions(),
            preimage=preimage.model_copy(update=update),
        )


def test_recomputed_retraction_proof_and_link_cannot_replace_absence_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preimage = _preimage()
    replacement_evidence_hash = "f" * 64
    proof = RetractionProofV1.model_validate(
        {
            **preimage.retraction_proofs[0].model_dump(
                mode="python", exclude_computed_fields=True
            ),
            "evidence_hash": replacement_evidence_hash,
        }
    )
    link = preimage.retraction_verification_link.model_copy(
        update={
            "proof_hash": proof.proof_hash,
            "evidence_hash": replacement_evidence_hash,
        }
    )
    monkeypatch.setattr(
        incremental_module,
        "build_fixture_candidate_batch",
        lambda **_: (_ for _ in ()).throw(AssertionError("candidate reached")),
    )

    with pytest.raises(
        IncrementalUpdateFixtureError,
        match="RETRACTION_EVIDENCE_CUSTODY_DRIFT",
    ):
        run_incremental_update_fixture(
            FIXTURE_PATH,
            material_profile_catalog=_catalog(),
            material_profile_resolutions=_resolutions(),
            preimage=preimage.model_copy(
                update={
                    "retraction_proofs": (proof,),
                    "retraction_verification_link": link,
                }
            ),
        )


def test_exact_four_actions_and_fifty_six_unchanged_are_frozen() -> None:
    result = _result()

    assert result.field_count == 60
    assert result.affected_count == 4
    assert result.unchanged_count == 56
    assert {item.action for item in result.actions} == {
        "enrich",
        "supersede",
        "conflict",
        "retract",
    }
    assert "add" not in {item.action for item in result.actions}
    assert len(result.unchanged_fact_hashes) == 56
    assert result.release_authority == "NONE_FIXTURE_ONLY"


def test_governance_actions_preserve_conflict_and_retraction_history() -> None:
    result = _result()
    by_action = {item.action: item for item in result.actions}

    assert by_action["enrich"].incoming_fact_hash is not None
    assert len(by_action["enrich"].prior_fact_hashes) == 1
    assert len(by_action["enrich"].evidence_hashes) == 2
    assert by_action["supersede"].incoming_fact_hash is not None
    assert len(by_action["supersede"].prior_fact_hashes) == 1
    assert len(by_action["conflict"].prior_fact_hashes) == 1
    assert len(by_action["conflict"].evidence_hashes) == 2
    assert by_action["retract"].incoming_fact_hash is None
    assert len(by_action["retract"].prior_fact_hashes) == 1
    assert by_action["retract"].evidence_hashes == ()
    assert set(result.human_review_field_ids) == {
        by_action["conflict"].field_id,
        by_action["retract"].field_id,
    }


def test_input_order_is_deterministic_and_receipt_is_deeply_immutable() -> None:
    original = _result()
    reordered = run_incremental_update_fixture(
        FIXTURE_PATH,
        material_profile_catalog=_catalog(),
        material_profile_resolutions=tuple(reversed(_resolutions())),
        preimage=_preimage().model_copy(
            update={
                "baseline_facts": tuple(reversed(_preimage().baseline_facts)),
                "baseline_fact_hashes": tuple(reversed(_preimage().baseline_fact_hashes)),
                "candidate_facts": tuple(reversed(_preimage().candidate_facts)),
                "retraction_proofs": tuple(reversed(_preimage().retraction_proofs)),
                "parsed_documents": tuple(reversed(_preimage().parsed_documents)),
                "parse_manifests": tuple(reversed(_preimage().parse_manifests)),
                "parse_quality_decisions": tuple(reversed(_preimage().parse_quality_decisions)),
                "field_candidates": tuple(reversed(_preimage().field_candidates)),
                "verification_batches": tuple(reversed(_preimage().verification_batches)),
                "receipt_chains": tuple(reversed(_preimage().receipt_chains)),
                "fact_verification_links": tuple(reversed(_preimage().fact_verification_links)),
            }
        ),
    )

    assert reordered == original
    assert reordered.receipt_hash == original.receipt_hash
    with pytest.raises(ValidationError):
        original.__setattr__("unchanged_fact_hashes", ())
    mutated = original.model_copy(update={"fixture_hash": "f" * 64})
    assert mutated.receipt_hash != original.receipt_hash


def test_equivalent_affected_order_has_identical_fixture_and_receipt_hash(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    payload["affected"] = list(reversed(cast(list[object], payload["affected"])))

    reordered = run_incremental_update_fixture(
        _write_fixture(tmp_path, payload),
        material_profile_catalog=_catalog(),
        material_profile_resolutions=_resolutions(),
        preimage=_preimage(),
    )

    assert reordered.fixture_hash == _result().fixture_hash
    assert reordered.receipt_hash == _result().receipt_hash


def test_exact_affected_field_action_mapping_cannot_move_as_a_valid_matrix(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    affected = list(cast(list[dict[str, object]], payload["affected"]))
    moved_fields = [item["field_id"] for item in affected[1:]] + [affected[0]["field_id"]]
    payload["affected"] = [
        {**item, "field_id": moved_field}
        for item, moved_field in zip(affected, moved_fields, strict=True)
    ]

    with pytest.raises(
        IncrementalUpdateFixtureError,
        match="INVALID_SYNTHETIC_FIXTURE",
    ):
        run_incremental_update_fixture(
            _write_fixture(tmp_path, payload),
            material_profile_catalog=_catalog(),
            material_profile_resolutions=_resolutions(),
            preimage=_preimage(),
        )


def test_affected_partition_cannot_move_into_an_unchanged_field(
    tmp_path: Path,
) -> None:
    payload = _fixture_payload()
    affected = list(cast(list[dict[str, object]], payload["affected"]))
    fields = cast(list[str], payload["field_ids"])
    unchanged = next(
        field_id
        for field_id in fields
        if field_id not in {cast(str, item["field_id"]) for item in affected}
    )
    payload["affected"] = [{**affected[0], "field_id": unchanged}, *affected[1:]]

    with pytest.raises(
        IncrementalUpdateFixtureError,
        match="INVALID_SYNTHETIC_FIXTURE",
    ):
        run_incremental_update_fixture(
            _write_fixture(tmp_path, payload),
            material_profile_catalog=_catalog(),
            material_profile_resolutions=_resolutions(),
            preimage=_preimage(),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_baseline",
        "extra_baseline",
        "recomputed_baseline_drift",
        "missing_document",
        "extra_document",
        "manifest_drift",
        "missing_quality",
        "missing_verification",
        "missing_chain",
        "missing_link",
    ),
)
def test_caller_custody_missing_extra_or_drift_fails_before_candidate(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    preimage = _preimage()
    update: dict[str, object]
    if mutation == "missing_baseline":
        update = {"baseline_facts": preimage.baseline_facts[:-1]}
    elif mutation == "extra_baseline":
        update = {"baseline_facts": (*preimage.baseline_facts, preimage.baseline_facts[0])}
    elif mutation == "recomputed_baseline_drift":
        first = preimage.baseline_facts[0]
        drifted = VerifiedFactV1.model_validate(
            {
                **first.model_dump(mode="python", exclude_computed_fields=True),
                "value_hash": "f" * 64,
                "evidence_hashes": ("e" * 64,),
            }
        )
        facts = (drifted, *preimage.baseline_facts[1:])
        update = {
            "baseline_facts": facts,
            "baseline_fact_hashes": tuple(sorted(item.fact_hash for item in facts)),
        }
    elif mutation == "missing_document":
        update = {"parsed_documents": preimage.parsed_documents[:-1]}
    elif mutation == "extra_document":
        update = {"parsed_documents": (*preimage.parsed_documents, preimage.parsed_documents[0])}
    elif mutation == "manifest_drift":
        update = {
            "parse_manifests": (
                preimage.parse_manifests[0].model_copy(update={"document_hash": "f" * 64}),
                *preimage.parse_manifests[1:],
            )
        }
    elif mutation == "missing_quality":
        update = {"parse_quality_decisions": preimage.parse_quality_decisions[:-1]}
    elif mutation == "missing_verification":
        update = {"verification_batches": preimage.verification_batches[:-1]}
    elif mutation == "missing_chain":
        update = {"receipt_chains": preimage.receipt_chains[:-1]}
    else:
        update = {"fact_verification_links": preimage.fact_verification_links[:-1]}

    monkeypatch.setattr(
        incremental_module,
        "build_fixture_candidate_batch",
        lambda **_: (_ for _ in ()).throw(AssertionError("candidate reached")),
    )
    with pytest.raises(IncrementalUpdateFixtureError):
        run_incremental_update_fixture(
            FIXTURE_PATH,
            material_profile_catalog=_catalog(),
            material_profile_resolutions=_resolutions(),
            preimage=preimage.model_copy(update=update),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "extra_field",
        "duplicate_field",
        "missing_affected",
        "fifth_change",
        "cross_space",
        "cross_version",
        "subject_drift",
        "unknown_retraction",
        "nonexclusive_retraction",
        "nonsynthetic_value",
    ),
)
def test_fixture_identity_partition_and_retraction_fail_closed(
    tmp_path: Path,
    mutation: str,
) -> None:
    payload = _fixture_payload()
    fields = list(cast(list[str], payload["field_ids"]))
    affected = list(cast(list[dict[str, object]], payload["affected"]))
    if mutation == "extra_field":
        fields.append("synthetic-extra-field")
    elif mutation == "duplicate_field":
        fields[-1] = fields[0]
    elif mutation == "missing_affected":
        affected.pop()
    elif mutation == "fifth_change":
        affected.append(
            {
                "field_id": fields[0],
                "action": "enrich",
                "baseline_value_tag": "synthetic-fifth-old",
                "candidate_value_tag": "synthetic-fifth-old",
                "candidate_state": "known",
            }
        )
    elif mutation == "cross_space":
        payload["space_id"] = "space-foreign"
    elif mutation == "cross_version":
        payload["product_version_id"] = "596-2"
    elif mutation == "subject_drift":
        payload["subject_id"] = "product:foreign"
    elif mutation == "unknown_retraction":
        affected[-1] = {**affected[-1], "candidate_state": "unknown"}
    elif mutation == "nonexclusive_retraction":
        affected[-1] = {**affected[-1], "exclusive_support": False}
    else:
        affected[0] = {**affected[0], "candidate_value_tag": "real-value"}
    payload["field_ids"] = fields
    payload["affected"] = affected

    with pytest.raises(IncrementalUpdateFixtureError, match="INVALID_SYNTHETIC_FIXTURE"):
        run_incremental_update_fixture(
            _write_fixture(tmp_path, payload),
            material_profile_catalog=_catalog(),
            material_profile_resolutions=_resolutions(),
            preimage=_preimage(),
        )


def test_extra_authority_input_is_not_silently_ignored() -> None:
    with pytest.raises(IncrementalUpdateFixtureError, match="AUTHORITY_INPUT_INVALID"):
        run_incremental_update_fixture(
            FIXTURE_PATH,
            material_profile_catalog=_catalog(),
            material_profile_resolutions=(*_resolutions(), object()),  # type: ignore[arg-type]
            preimage=_preimage(),
        )


def test_authority_identity_drift_fails_before_candidate() -> None:
    first, *rest = _resolutions()
    foreign_request = first.request.model_copy(update={"space_id": "space-foreign"})
    foreign = first.model_copy(update={"request": foreign_request})

    with pytest.raises(IncrementalUpdateFixtureError, match="AUTHORITY_INPUT_INVALID"):
        run_incremental_update_fixture(
            FIXTURE_PATH,
            material_profile_catalog=_catalog(),
            material_profile_resolutions=(foreign, *rest),
            preimage=_preimage(),
        )


def test_fixture_and_module_exclude_real_values_and_external_surfaces() -> None:
    fixture_text = FIXTURE_PATH.read_text(encoding="utf-8").casefold()
    module_path = (
        Path(__file__).parents[1]
        / "src"
        / "insurance_harness"
        / "knowledge_compiler"
        / "incremental_update_596_1.py"
    )
    source = module_path.read_text(encoding="utf-8")

    assert "golden" not in fixture_text
    assert "expected_answer" not in fixture_text
    assert "import http" not in source
    assert "import sqlalchemy" not in source
    assert "import requests" not in source
    assert "import os" not in source
    assert "subprocess" not in source
    assert "def _build_fact_inputs" not in source
