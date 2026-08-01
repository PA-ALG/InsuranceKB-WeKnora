"""OpenSpec 054: pure bounded extraction task/attempt/receipt contract."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.extraction_receipts import (
    EXTRACTION_ATTEMPT_OBJECT_TYPE,
    AttemptReceiptV1,
    AttemptRequestV1,
    FieldOutcomeV1,
    ReceiptChainV1,
    ReceiptContractError,
    build_attempt_receipt,
    build_initial_attempt,
    build_targeted_repair,
)
from insurance_harness.compiler.extraction_tasks import (
    ArtifactRefV1,
    AttemptBudgetV1,
    ExtractionAdmissionError,
    ExtractionInputRefsV1,
    ExtractionTaskProfileV1,
    ExtractionTaskV1,
    MaterialRole,
    ParsedArtifactAdmissionPort,
    build_extraction_task,
    build_extraction_task_profile,
)
from insurance_harness.compiler.material_profiles import (
    MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
    ApprovedParsePolicy,
    AuthorityClass,
    FieldAuthority,
    MaterialProfile,
    ParsePolicyReceipt,
    SourceDocumentIdentity,
)
from insurance_harness.compiler.parsed_documents import (
    CapabilityEvidenceV1,
    PageLocatorV1,
    ParseAttemptV1,
    ParsedDocumentV1,
    ParseManifestV1,
    ParseOutputFactsV1,
    ParsePageV1,
    ParseQualityDecisionV1,
    ParseQualityMeasuredFactsV1,
    ParserIdentityV1,
    ParseSnapshotV1,
    ParseSubjectV1,
    build_parse_manifest,
)

SOURCE_ROOT = Path(__file__).parents[1] / "src" / "insurance_harness" / "compiler"
TASK_MODULE = SOURCE_ROOT / "extraction_tasks.py"
RECEIPT_MODULE = SOURCE_ROOT / "extraction_receipts.py"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _ref(object_type: str, artifact_hash: str = HASH_A) -> ArtifactRefV1:
    return ArtifactRefV1(object_type=object_type, artifact_hash=artifact_hash)


def _inputs() -> ExtractionInputRefsV1:
    return ExtractionInputRefsV1(
        source_revision=_ref("source-revision.v1", HASH_A),
        material_profile=_ref(MATERIAL_PROFILE_BINDING_OBJECT_TYPE, HASH_B),
        resolved_template=_ref("resolved-template.v1", HASH_C),
        schema_contract=_ref("schema-contract.v1", "d" * 64),
        parsed_document=_ref("parsed-document.v1", "e" * 64),
        parse_manifest=_ref("parse-manifest.v1", "f" * 64),
        parse_quality_decision=_ref("parse-quality-decision.v1", "1" * 64),
    )


def _material_profile(material_role: MaterialRole) -> MaterialProfile:
    profile_id = f"596-1-{material_role}-v1"
    policy = ApprovedParsePolicy(
        policy_id=f"596-1-{material_role}-approved-parse-policy",
        policy_version="v1",
        material_profile_id=profile_id,
        default_parser_profile_ref="approved-parser-profile:parser-neutral-default.v1",
        bounded_upgrade_profile_ref=(
            "approved-parser-profile:parser-neutral-bounded-upgrade.v1"
        ),
        upgrade_trigger_conditions=("required_capability_missing",),
        max_parser_attempts=2,
        privacy_policy_ref="privacy-policy:source-revision-private-processing.v1",
        output_policy_ref="output-policy:parsed-artifact-internal-only.v1",
    )
    return MaterialProfile(
        profile_id=profile_id,
        material_role=material_role,
        source=SourceDocumentIdentity(
            name=f"{material_role}.pdf",
            path=f"dataset/596-1/{material_role}.pdf",
            size=1024,
            sha256=HASH_A,
        ),
        document_type_id=f"596-1-{material_role}",
        required_parse_capabilities=("ordered_pages", "block_locators"),
        parse_policy=policy,
    )


def _field_authority(
    material_role: MaterialRole,
    field_ids: tuple[str, ...],
) -> FieldAuthority:
    authority_class: AuthorityClass
    if material_role == "terms":
        authority_class = "contract_fact"
    elif material_role == "brochure":
        authority_class = "brochure_fact"
    else:
        authority_class = "rate_numeric"
    return FieldAuthority(
        authority_class=authority_class,
        primary_role=material_role,
        support_roles=(),
        field_ids=field_ids,
    )


def _task_profile(
    *,
    material_role: MaterialRole,
    field_ids: tuple[str, ...],
    budget: AttemptBudgetV1,
) -> ExtractionTaskProfileV1:
    material_profile = _material_profile(material_role)
    receipt = ParsePolicyReceipt.model_validate(
        {
            **material_profile.parse_policy.model_dump(mode="python"),
            "required_parse_capabilities": (
                material_profile.required_parse_capabilities
            ),
        }
    )
    result = build_extraction_task_profile(
        material_profile=material_profile,
        material_profile_binding_hash=HASH_B,
        parse_policy_receipt=receipt,
        field_authority=_field_authority(material_role, field_ids),
        attempt_budget=budget,
    )
    return result


def _task(
    *,
    space_id: str = "space-054",
    product_version_id: str = "596-1",
    source_revision_id: str = "revision-terms-v1",
    material_role: MaterialRole = "terms",
    module_id: str = "coverage-benefits",
    risk_partition_id: str = "contract-facts",
    field_ids: tuple[str, ...] = (
        "benefit_name",
        "coverage_scope",
        "waiting_period",
    ),
    input_refs: ExtractionInputRefsV1 | None = None,
    budget: AttemptBudgetV1 | None = None,
) -> ExtractionTaskV1:
    actual_budget = budget or AttemptBudgetV1(
        max_fields=3,
        max_total_attempts=2,
        max_targeted_repairs=1,
    )
    return build_extraction_task(
        space_id=space_id,
        product_version_id=product_version_id,
        source_revision_id=source_revision_id,
        material_role=material_role,
        module_id=module_id,
        risk_partition_id=risk_partition_id,
        field_ids=field_ids,
        input_refs=input_refs or _inputs(),
        budget=actual_budget,
        task_profile=_task_profile(
            material_role=material_role,
            field_ids=field_ids,
            budget=actual_budget,
        ),
    )


def _candidate(field_id: str) -> FieldOutcomeV1:
    return FieldOutcomeV1(
        field_id=field_id,
        status="candidate",
        candidate_ref=_ref("field-candidate.v1", field_id[0].encode().hex().ljust(64, "0")),
        reason_code=None,
    )


def _unknown(field_id: str, reason: str = "evidence_insufficient") -> FieldOutcomeV1:
    return FieldOutcomeV1(
        field_id=field_id,
        status="unknown",
        candidate_ref=None,
        reason_code=reason,
    )


def _initial_attempt_for_fields(
    task: ExtractionTaskV1,
    field_ids: tuple[str, ...],
) -> AttemptRequestV1:
    payload = {
        "task_hash": task.task_hash,
        "attempt_number": 1,
        "purpose": "initial",
        "field_ids": field_ids,
        "parent_receipt_hash": None,
    }
    return AttemptRequestV1.model_validate(
        {
            **payload,
            "attempt_hash": canonical_hash(EXTRACTION_ATTEMPT_OBJECT_TYPE, payload),
        }
    )


def test_task_identity_is_material_module_risk_scoped_and_canonical() -> None:
    task = _task()
    assert task == _task()
    assert len(task.task_hash) == 64
    assert task.task_hash != _task(module_id="exclusions").task_hash
    assert task.task_hash != _task(risk_partition_id="rate-risk").task_hash
    assert task.task_hash != _task(material_role="brochure").task_hash

    for field_ids in (
        ("coverage_scope", "benefit_name", "waiting_period"),
        ("benefit_name", "benefit_name"),
        ("benefit_name", "coverage_scope", "waiting_period", "extra"),
    ):
        with pytest.raises(ValidationError):
            _task(field_ids=field_ids)
    with pytest.raises(ValidationError):
        _task(module_id="*")
    with pytest.raises(ValidationError):
        _task(risk_partition_id="all")
    with pytest.raises(ValidationError):
        _task(space_id="")
    with pytest.raises(ValidationError, match="invalid_task_identity"):
        _task(space_id="space-*")
    with pytest.raises(ValidationError, match="invalid_task_identity"):
        _task(module_id="coverage-*")
    with pytest.raises(ValidationError, match="invalid_task_identity"):
        _task(risk_partition_id="risk-?")
    with pytest.raises(ValidationError, match="invalid_task_identity"):
        _task(product_version_id="version-all")
    for object_type in (
        "golden-record.v1",
        "provider-result.v1",
        "prior-prediction.v1",
        "release.v1",
        "approval-record.v1",
    ):
        with pytest.raises(ValidationError):
            ArtifactRefV1(object_type=object_type, artifact_hash=HASH_A)


def test_attempt_budget_and_initial_attempt_are_explicit() -> None:
    for values in (
        {"max_fields": 3, "max_total_attempts": 2, "max_targeted_repairs": 0},
        {"max_fields": 3, "max_total_attempts": 1, "max_targeted_repairs": 1},
        {"max_fields": 3, "max_total_attempts": 3, "max_targeted_repairs": 2},
    ):
        with pytest.raises(ValidationError):
            AttemptBudgetV1.model_validate(values)

    task = _task()
    attempt = build_initial_attempt(task)
    assert attempt.task_hash == task.task_hash
    assert attempt.attempt_number == 1
    assert attempt.purpose == "initial"
    assert attempt.field_ids == task.field_ids
    assert len(attempt.attempt_hash) == 64


def test_stage2_profile_binds_052_policy_authority_and_budget() -> None:
    task = _task()
    profile = task.task_profile
    assert profile.material_profile.profile_id == "596-1-terms-v1"
    assert profile.material_profile_binding_hash == HASH_B
    assert profile.parse_policy_receipt.max_parser_attempts == 2
    assert profile.parse_policy_receipt.required_parse_capabilities == (
        "ordered_pages",
        "block_locators",
    )
    assert profile.field_authority.authority_class == "contract_fact"
    assert profile.authority_mode == "primary"
    assert profile.attempt_budget == task.budget
    assert len(profile.profile_hash) == 64
    assert profile == _task().task_profile


def test_stage2_profile_rejects_policy_authority_budget_and_binding_drift() -> None:
    profile = _material_profile("terms")
    receipt = ParsePolicyReceipt.model_validate(
        {
            **profile.parse_policy.model_dump(mode="python"),
            "required_parse_capabilities": profile.required_parse_capabilities,
        }
    )
    authority = _field_authority(
        "terms", ("benefit_name", "coverage_scope", "waiting_period")
    )
    budget = AttemptBudgetV1(
        max_fields=3,
        max_total_attempts=2,
        max_targeted_repairs=1,
    )
    with pytest.raises(ValidationError):
        build_extraction_task_profile(
            material_profile=profile,
            material_profile_binding_hash=HASH_B,
            parse_policy_receipt=receipt.model_copy(update={"policy_version": "v2"}),
            field_authority=authority,
            attempt_budget=budget,
        )
    with pytest.raises(ValidationError):
        build_extraction_task_profile(
            material_profile=profile,
            material_profile_binding_hash=HASH_B,
            parse_policy_receipt=receipt,
            field_authority=FieldAuthority(
                authority_class="brochure_fact",
                primary_role="brochure",
                support_roles=(),
                field_ids=("benefit_name",),
            ),
            attempt_budget=budget,
        )
    with pytest.raises(ValidationError):
        build_extraction_task_profile(
            material_profile=profile,
            material_profile_binding_hash=HASH_B,
            parse_policy_receipt=receipt,
            field_authority=authority,
            attempt_budget=AttemptBudgetV1(
                max_fields=3,
                max_total_attempts=1,
                max_targeted_repairs=0,
            ),
        )

    with pytest.raises(ValidationError):
        _task(input_refs=_inputs().model_copy(
            update={"material_profile": _ref("material-profile.v1", HASH_C)}
        ))
    with pytest.raises(ValidationError):
        _task(
            input_refs=_inputs().model_copy(
                update={"material_profile": _ref("material-profile.v1", HASH_B)}
            )
        )


def _admitted_parse_artifacts(
    task_profile: ExtractionTaskProfileV1,
    *,
    attempt_number: Literal[1, 2] = 1,
    parser_profile_ref: str | None = None,
    privacy_policy_ref: str | None = None,
    output_policy_ref: str | None = None,
    pagination_complete: bool = True,
) -> tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1]:
    profile = task_profile.material_profile
    attempt_role: Literal["default", "bounded_upgrade"] = (
        "default" if attempt_number == 1 else "bounded_upgrade"
    )
    expected_parser_profile = (
        profile.parse_policy.default_parser_profile_ref
        if attempt_number == 1
        else profile.parse_policy.bounded_upgrade_profile_ref
    )
    assert expected_parser_profile is not None
    document = ParsedDocumentV1(
        contract="parsed-document.v1",
        subject=ParseSubjectV1(
            space_id="space-054",
            source_id="source-terms",
            source_revision_id="revision-terms-v1",
            product_version_id="596-1",
            material_profile_id=profile.profile_id,
            material_profile_binding_hash=task_profile.material_profile_binding_hash,
            source_sha256=profile.source.sha256,
            raw_artifact_hash=HASH_C,
            canonical_envelope_hash="d" * 64,
        ),
        parser=ParserIdentityV1(
            parser_id="parser-neutral-fixture",
            parser_profile_ref=parser_profile_ref or expected_parser_profile,
            parser_build_id="build-v1",
            parser_config_hash=HASH_B,
        ),
        attempt=ParseAttemptV1(
            attempt_id=f"parse-attempt-{attempt_number}",
            attempt_number=attempt_number,
            attempt_role=attempt_role,
            generation=attempt_number,
        ),
        snapshot=ParseSnapshotV1(
            snapshot_id="snapshot-1",
            snapshot_generation=1,
            pagination_complete=pagination_complete,
            concurrent_mutation_fence_hash="d" * 64,
        ),
        output_facts=ParseOutputFactsV1(
            privacy_policy_ref=(
                privacy_policy_ref or profile.parse_policy.privacy_policy_ref
            ),
            output_policy_ref=(
                output_policy_ref or profile.parse_policy.output_policy_ref
            ),
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
                content_hash=HASH_A,
                structure_hash=HASH_B,
            ),
        ),
        blocks=(),
        tables=(),
        cells=(),
        capability_evidence=(
            CapabilityEvidenceV1(
                capability="ordered_pages",
                subject_refs=("page-1",),
            ),
        ),
        warnings=(),
        unsupported=(),
    )
    manifest = build_parse_manifest(document, profile)
    decision = ParseQualityDecisionV1(
        contract="parse-quality-decision.v1",
        subject=document.subject,
        manifest_hash=manifest.manifest_hash,
        parse_policy_receipt=task_profile.parse_policy_receipt,
        measured_facts=ParseQualityMeasuredFactsV1(
            threshold_version="parse-quality-structural.v1",
            required_capabilities=manifest.required_capabilities,
            satisfied_capabilities=manifest.satisfied_capabilities,
            unsatisfied_capabilities=manifest.unsatisfied_capabilities,
            trigger_conditions=(),
            attempts_exhausted=(
                attempt_number >= task_profile.parse_policy_receipt.max_parser_attempts
            ),
        ),
        decision="ADMIT",
        reason_codes=(),
        admitted_attempt_id=document.attempt.attempt_id,
        next_parser_profile_ref=None,
        review_item=None,
    )
    assert decision.decision == "ADMIT"
    return document, manifest, decision


def _stage3_task_profile() -> ExtractionTaskProfileV1:
    material_profile = _material_profile("terms").model_copy(
        update={"required_parse_capabilities": ("ordered_pages",)}
    )
    material_profile = MaterialProfile.model_validate(
        material_profile.model_dump(mode="python")
    )
    receipt = ParsePolicyReceipt.model_validate(
        {
            **material_profile.parse_policy.model_dump(mode="python"),
            "required_parse_capabilities": ("ordered_pages",),
        }
    )
    return build_extraction_task_profile(
        material_profile=material_profile,
        material_profile_binding_hash=HASH_B,
        parse_policy_receipt=receipt,
        field_authority=_field_authority("terms", ("benefit_name",)),
        attempt_budget=AttemptBudgetV1(
            max_fields=1,
            max_total_attempts=2,
            max_targeted_repairs=1,
        ),
    )


def _admit_stage3(
    task_profile: ExtractionTaskProfileV1,
    artifacts: tuple[ParsedDocumentV1, ParseManifestV1, ParseQualityDecisionV1],
) -> ExtractionInputRefsV1:
    document, manifest, decision = artifacts
    return ParsedArtifactAdmissionPort().admitted_input_refs(
        task_profile=task_profile,
        space_id="space-054",
        product_version_id="596-1",
        source_revision_id="revision-terms-v1",
        source_revision=_ref("source-revision.v1", HASH_A),
        resolved_template=_ref("resolved-template.v1", HASH_C),
        schema_contract=_ref("schema-contract.v1", "d" * 64),
        document=document,
        manifest=manifest,
        quality_decision=decision,
    )


@pytest.mark.parametrize(
    ("attempt_number", "parser_profile_ref"),
    (
        (1, "approved-parser-profile:parser-neutral-bounded-upgrade.v1"),
        (2, "approved-parser-profile:parser-neutral-default.v1"),
    ),
)
def test_stage3_rejects_parser_profile_not_approved_for_attempt(
    attempt_number: Literal[1, 2],
    parser_profile_ref: str,
) -> None:
    task_profile = _stage3_task_profile()
    artifacts = _admitted_parse_artifacts(
        task_profile,
        attempt_number=attempt_number,
        parser_profile_ref=parser_profile_ref,
    )

    with pytest.raises(
        ExtractionAdmissionError,
        match="parse_artifact_admission_mismatch",
    ):
        _admit_stage3(task_profile, artifacts)


@pytest.mark.parametrize(
    ("privacy_policy_ref", "output_policy_ref"),
    (
        ("privacy-policy:unapproved.v1", None),
        (None, "output-policy:unapproved.v1"),
    ),
)
def test_stage3_rejects_privacy_or_output_policy_drift(
    privacy_policy_ref: str | None,
    output_policy_ref: str | None,
) -> None:
    task_profile = _stage3_task_profile()
    artifacts = _admitted_parse_artifacts(
        task_profile,
        privacy_policy_ref=privacy_policy_ref,
        output_policy_ref=output_policy_ref,
    )

    with pytest.raises(
        ExtractionAdmissionError,
        match="parse_artifact_admission_mismatch",
    ):
        _admit_stage3(task_profile, artifacts)


def test_stage3_rejects_incomplete_snapshot() -> None:
    task_profile = _stage3_task_profile()
    artifacts = _admitted_parse_artifacts(
        task_profile,
        pagination_complete=False,
    )

    with pytest.raises(
        ExtractionAdmissionError,
        match="parse_artifact_admission_mismatch",
    ):
        _admit_stage3(task_profile, artifacts)


def test_stage3_port_consumes_exact_admitted_053_dtos_without_mirroring() -> None:
    task_profile = _stage3_task_profile()
    document, manifest, decision = _admitted_parse_artifacts(task_profile)
    port = ParsedArtifactAdmissionPort()
    refs = port.admitted_input_refs(
        task_profile=task_profile,
        space_id="space-054",
        product_version_id="596-1",
        source_revision_id="revision-terms-v1",
        source_revision=_ref("source-revision.v1", HASH_A),
        resolved_template=_ref("resolved-template.v1", HASH_C),
        schema_contract=_ref("schema-contract.v1", "d" * 64),
        document=document,
        manifest=manifest,
        quality_decision=decision,
    )
    assert refs.parsed_document.artifact_hash == document.document_hash
    assert refs.parse_manifest.artifact_hash == manifest.manifest_hash
    assert refs.parse_quality_decision.artifact_hash == decision.decision_hash

    with pytest.raises(ValueError, match="parse_artifact_admission_mismatch"):
        port.admitted_input_refs(
            task_profile=task_profile,
            space_id="space-054",
            product_version_id="596-1",
            source_revision_id="revision-terms-v1",
            source_revision=_ref("source-revision.v1", HASH_A),
            resolved_template=_ref("resolved-template.v1", HASH_C),
            schema_contract=_ref("schema-contract.v1", "d" * 64),
            document=document,
            manifest=manifest,
            quality_decision=decision.model_copy(update={"manifest_hash": HASH_C}),
        )

    source = TASK_MODULE.read_text(encoding="utf-8")
    assert "insurance_harness.compiler.parsed_documents" in source
    for forbidden_definition in (
        "class ParsedDocumentV1",
        "class ParseManifestV1",
        "class ParseQualityDecisionV1",
    ):
        assert forbidden_definition not in source


def test_receipt_requires_complete_typed_field_outcomes() -> None:
    attempt = build_initial_attempt(_task())
    outcomes = (
        _candidate("benefit_name"),
        _unknown("coverage_scope"),
        _unknown("waiting_period"),
    )
    receipt = build_attempt_receipt(
        attempt,
        field_outcomes=outcomes,
        outcome="insufficient",
        reason_code="two_fields_unresolved",
    )
    assert receipt.attempted_fields == attempt.field_ids
    assert tuple(item.field_id for item in receipt.field_outcomes) == attempt.field_ids

    with pytest.raises((ValidationError, ReceiptContractError)):
        build_attempt_receipt(
            attempt,
            field_outcomes=outcomes[:-1],
            outcome="insufficient",
            reason_code="missing_field",
        )


def test_initial_receipt_must_cover_the_exact_task_field_partition() -> None:
    task = _task()
    partial_attempt = _initial_attempt_for_fields(task, task.field_ids[:2])
    partial_receipt = build_attempt_receipt(
        partial_attempt,
        field_outcomes=tuple(_unknown(field_id) for field_id in task.field_ids[:2]),
        outcome="insufficient",
        reason_code="partial_initial_attempt",
    )
    with pytest.raises(ValidationError, match="initial_receipt_fields_mismatch"):
        ReceiptChainV1(
            task=task,
            task_hash=task.task_hash,
            receipts=(partial_receipt,),
        )
    with pytest.raises(ValidationError):
        FieldOutcomeV1(
            field_id="coverage_scope",
            status="candidate",
            candidate_ref=None,
            reason_code=None,
        )
    with pytest.raises(ValidationError):
        FieldOutcomeV1(
            field_id="coverage_scope",
            status="unknown",
            candidate_ref=_ref("field-candidate.v1"),
            reason_code="should_not_have_candidate",
        )


def test_receipt_hash_round_trip_and_extra_fields_fail_closed() -> None:
    attempt = build_initial_attempt(_task())
    receipt = build_attempt_receipt(
        attempt,
        field_outcomes=tuple(_candidate(field_id) for field_id in attempt.field_ids),
        outcome="completed",
        reason_code=None,
    )
    assert AttemptReceiptV1.model_validate_json(receipt.model_dump_json()) == receipt

    raw = json.loads(receipt.model_dump_json())
    raw["receipt_hash"] = HASH_B
    with pytest.raises(ValidationError):
        AttemptReceiptV1.model_validate(raw)
    raw = json.loads(receipt.model_dump_json())
    raw["unexpected"] = "authority"
    with pytest.raises(ValidationError):
        AttemptReceiptV1.model_validate(raw)
    with pytest.raises(ValidationError):
        ExtractionTaskV1.model_validate(
            {**_task().model_dump(mode="python"), "task_hash": HASH_C}
        )


def test_targeted_repair_is_exact_unresolved_subset_and_only_once() -> None:
    task = _task()
    initial = build_initial_attempt(task)
    initial_receipt = build_attempt_receipt(
        initial,
        field_outcomes=(
            _candidate("benefit_name"),
            _unknown("coverage_scope"),
            _unknown("waiting_period", "locator_missing"),
        ),
        outcome="insufficient",
        reason_code="repairable_fields_remain",
    )
    chain = ReceiptChainV1(
        task=task,
        task_hash=task.task_hash,
        receipts=(initial_receipt,),
    )
    repair = build_targeted_repair(task, chain)
    assert repair.attempt_number == 2
    assert repair.purpose == "targeted_repair"
    assert repair.field_ids == ("coverage_scope", "waiting_period")

    repair_receipt = build_attempt_receipt(
        repair,
        field_outcomes=tuple(_candidate(field_id) for field_id in repair.field_ids),
        outcome="completed",
        reason_code=None,
    )
    closed_chain = ReceiptChainV1(
        task=task,
        task_hash=task.task_hash,
        receipts=(initial_receipt, repair_receipt),
    )
    with pytest.raises(ReceiptContractError, match="repair_budget_exhausted"):
        build_targeted_repair(task, closed_chain)

    completed_initial = build_attempt_receipt(
        initial,
        field_outcomes=tuple(_candidate(field_id) for field_id in initial.field_ids),
        outcome="completed",
        reason_code=None,
    )
    with pytest.raises(ReceiptContractError, match="no_unresolved_fields"):
        build_targeted_repair(
            task,
            ReceiptChainV1(
                task=task,
                task_hash=task.task_hash,
                receipts=(completed_initial,),
            ),
        )


def test_targeted_repair_identity_binds_exact_parent_receipt_hash() -> None:
    task = _task()
    initial = build_initial_attempt(task)
    outcomes = (
        _candidate("benefit_name"),
        _unknown("coverage_scope"),
        _unknown("waiting_period"),
    )
    first = build_attempt_receipt(
        initial,
        field_outcomes=outcomes,
        outcome="insufficient",
        reason_code="first_observation",
    )
    second = build_attempt_receipt(
        initial,
        field_outcomes=outcomes,
        outcome="insufficient",
        reason_code="independent_observation",
    )
    assert first.receipt_hash != second.receipt_hash

    first_repair = build_targeted_repair(
        task,
        ReceiptChainV1(task=task, task_hash=task.task_hash, receipts=(first,)),
    )
    second_repair = build_targeted_repair(
        task,
        ReceiptChainV1(task=task, task_hash=task.task_hash, receipts=(second,)),
    )
    assert first_repair.field_ids == second_repair.field_ids
    assert first_repair.parent_receipt_hash == first.receipt_hash
    assert second_repair.parent_receipt_hash == second.receipt_hash
    assert first_repair.attempt_hash != second_repair.attempt_hash


def test_cross_task_attempt_and_receipt_drift_is_rejected() -> None:
    task = _task()
    foreign_task = _task(module_id="foreign-module")
    initial = build_initial_attempt(task)
    receipt = build_attempt_receipt(
        initial,
        field_outcomes=tuple(_candidate(field_id) for field_id in initial.field_ids),
        outcome="completed",
        reason_code=None,
    )
    with pytest.raises(ValidationError):
        ReceiptChainV1(
            task=foreign_task,
            task_hash=foreign_task.task_hash,
            receipts=(receipt,),
        )
    with pytest.raises(ValidationError):
        initial.__class__.model_validate(
            {**initial.model_dump(mode="python"), "attempt_hash": HASH_C}
        )


def test_failure_receipts_have_no_candidate_or_success_default() -> None:
    attempt = build_initial_attempt(_task())
    failed = tuple(
        FieldOutcomeV1(
            field_id=field_id,
            status="failed",
            candidate_ref=None,
            reason_code="provider_result_invalid",
        )
        for field_id in attempt.field_ids
    )
    receipt = build_attempt_receipt(
        attempt,
        field_outcomes=failed,
        outcome="failed",
        reason_code="attempt_failed",
    )
    assert all(item.candidate_ref is None for item in receipt.field_outcomes)
    with pytest.raises((ValidationError, ReceiptContractError)):
        build_attempt_receipt(
            attempt,
            field_outcomes=failed,
            outcome="failed",
            reason_code=None,
        )
    with pytest.raises((ValidationError, ReceiptContractError)):
        build_attempt_receipt(
            attempt,
            field_outcomes=failed,
            outcome="completed",
            reason_code=None,
        )


def test_modules_are_pure_and_import_only_the_exact_053_contract_not_io() -> None:
    forbidden_roots = {
        "asyncio",
        "httpx",
        "os",
        "pathlib",
        "requests",
        "socket",
        "sqlite3",
        "subprocess",
    }
    for module_path in (TASK_MODULE, RECEIPT_MODULE):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module or ""
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        )
        assert not {name.split(".")[0] for name in imports} & forbidden_roots
        assert all("goldenset" not in name for name in imports)
        if module_path == TASK_MODULE:
            assert "insurance_harness.compiler.parsed_documents" in imports
        else:
            assert all("parsed_document" not in name for name in imports)
