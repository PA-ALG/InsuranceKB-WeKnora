"""OpenSpec 059: deterministic fixture Candidate and human-batch envelope."""

from __future__ import annotations

import json
from typing import Literal

import pytest
from pydantic import ValidationError

from insurance_harness.compiler.evidence_verifier import (
    EvidenceReviewItemV1,
    FieldVerificationV1,
    GapV1,
    RepairResolutionV1,
    VerificationBatchV1,
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
    ExtractionInputRefsV1,
    build_extraction_task,
    build_extraction_task_profile,
)
from insurance_harness.compiler.material_profiles import (
    MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
    ApprovedParsePolicy,
    FieldAuthority,
    MaterialProfile,
    ParsePolicyReceipt,
    SourceDocumentIdentity,
)
from insurance_harness.knowledge_compiler.candidate_batches import (
    CandidateAssemblyError,
    CandidateAssemblyV1,
    FactVerificationLinkV1,
    HumanBatchPolicyV1,
    HumanBatchV1,
    build_fixture_candidate_batch,
)
from insurance_harness.knowledge_compiler.incremental_changes import (
    ChangeItemDraftV1,
    ChangeSetDraftV1,
    VerifiedFactV1,
)
from insurance_harness.knowledge_compiler.source_authority import (
    FactScopeV1,
    MaterialBindingReceiptV1,
    SourceAuthorityV1,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64
FIELD_CONFLICT = "zh_conflict"
FIELD_ADD = "zh_add"
FIELD_REPAIR = "zh_repair"


def _scope(field_id: str, *, space_id: str = "space-059") -> FactScopeV1:
    return FactScopeV1(
        space_id=space_id,
        product_version_id="596-1",
        subject_id="product:596-1",
        field_id=field_id,
        valid_from="2026-01-01T00:00:00.000000Z",
        valid_through=None,
        region="CN",
        channel="all-approved-channels",
        population="eligible-insured",
        conditions=("plan=standard",),
    )


def _authority(revision: str, source_hash: str, reliable_at: str) -> SourceAuthorityV1:
    binding = MaterialBindingReceiptV1(
        catalog_hash=HASH_A,
        binding_hash=HASH_B,
        space_id="space-059",
        product_version_id="596-1",
        source_id=source_hash,
        source_revision_id=revision,
        material_role="terms",
    )
    return SourceAuthorityV1(
        source_id=source_hash,
        source_revision_id=revision,
        material_role="terms",
        binding=binding,
        reliable_at=reliable_at,
    )


def _fact(
    field_id: str,
    *,
    revision: str,
    source_hash: str,
    value_hash: str,
    evidence_hash: str,
    reliable_at: str,
) -> VerifiedFactV1:
    return VerifiedFactV1(
        scope=_scope(field_id),
        state="known",
        value_hash=value_hash,
        authority=_authority(revision, source_hash, reliable_at),
        evidence_hashes=(evidence_hash,),
        supporting_source_revision_ids=(revision,),
    )


def _verification(
    field_id: str,
    *,
    revision: str,
    candidate_snapshot_hash: str,
    status: Literal["PASS", "FAIL"] = "PASS",
) -> VerificationBatchV1:
    reason_codes = () if status == "PASS" else ("repair_exhausted",)
    return VerificationBatchV1(
        contract="evidence-verification-batch.v1",
        product_version_id="596-1",
        source_revision_id=revision,
        parse_attempt_id=f"attempt:{revision}",
        parsed_document_hash=HASH_D,
        parse_manifest_hash=HASH_E,
        results=(
            FieldVerificationV1(
                field_id=field_id,
                status=status,
                reason_codes=reason_codes,
                candidate_snapshot_hash=candidate_snapshot_hash,
            ),
        ),
    )


def _receipt_chain(
    verification: VerificationBatchV1,
    *,
    space_id: str = "space-059",
    schema_hash: str = HASH_E,
) -> ReceiptChainV1:
    field_ids = tuple(result.field_id for result in verification.results)
    budget = AttemptBudgetV1(
        max_fields=len(field_ids),
        max_total_attempts=2,
        max_targeted_repairs=1,
    )
    material_profile = MaterialProfile(
        profile_id="profile-terms-596-1",
        material_role="terms",
        source=SourceDocumentIdentity(
            name="terms.pdf",
            path="dataset/596-1/terms.pdf",
            size=1024,
            sha256=HASH_A,
        ),
        document_type_id="insurance-terms",
        required_parse_capabilities=("ordered_pages",),
        parse_policy=ApprovedParsePolicy(
            policy_id="policy-059",
            policy_version="v1",
            material_profile_id="profile-terms-596-1",
            default_parser_profile_ref=(
                "approved-parser-profile:parser-neutral-default.v1"
            ),
            bounded_upgrade_profile_ref=(
                "approved-parser-profile:parser-neutral-upgrade.v1"
            ),
            upgrade_trigger_conditions=("required_capability_missing",),
            max_parser_attempts=2,
            privacy_policy_ref="privacy-policy:internal.v1",
            output_policy_ref="output-policy:internal.v1",
        ),
    )
    parse_policy_receipt = ParsePolicyReceipt.model_validate(
        {
            **material_profile.parse_policy.model_dump(mode="python"),
            "required_parse_capabilities": (
                material_profile.required_parse_capabilities
            ),
        }
    )
    profile = build_extraction_task_profile(
        material_profile=material_profile,
        material_profile_binding_hash=HASH_B,
        parse_policy_receipt=parse_policy_receipt,
        field_authority=FieldAuthority(
            authority_class="contract_fact",
            primary_role="terms",
            support_roles=(),
            field_ids=field_ids,
        ),
        attempt_budget=budget,
    )
    task = build_extraction_task(
        space_id=space_id,
        product_version_id=verification.product_version_id,
        source_revision_id=verification.source_revision_id,
        material_role="terms",
        module_id="fixture-candidate",
        risk_partition_id="contract-facts",
        field_ids=field_ids,
        input_refs=ExtractionInputRefsV1(
            source_revision=ArtifactRefV1(
                object_type="source-revision.v1", artifact_hash=HASH_A
            ),
            material_profile=ArtifactRefV1(
                object_type=MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
                artifact_hash=HASH_B,
            ),
            resolved_template=ArtifactRefV1(
                object_type="resolved-template.v1", artifact_hash=HASH_C
            ),
            schema_contract=ArtifactRefV1(
                object_type="schema-contract.v1", artifact_hash=schema_hash
            ),
            parsed_document=ArtifactRefV1(
                object_type="parsed-document.v1",
                artifact_hash=verification.parsed_document_hash,
            ),
            parse_manifest=ArtifactRefV1(
                object_type="parse-manifest.v1",
                artifact_hash=verification.parse_manifest_hash,
            ),
            parse_quality_decision=ArtifactRefV1(
                object_type="parse-quality-decision.v1", artifact_hash=HASH_F
            ),
        ),
        budget=budget,
        task_profile=profile,
    )
    attempt = build_initial_attempt(task)
    outcomes = tuple(
        FieldOutcomeV1(
            field_id=result.field_id,
            status="candidate" if result.status == "PASS" else "unknown",
            candidate_ref=(
                ArtifactRefV1(
                    object_type="verified-field-candidate.v1",
                    artifact_hash=result.candidate_snapshot_hash,
                )
                if result.status == "PASS"
                else None
            ),
            reason_code=None if result.status == "PASS" else result.reason_codes[0],
        )
        for result in verification.results
    )
    completed = all(result.status == "PASS" for result in verification.results)
    receipt = build_attempt_receipt(
        attempt,
        field_outcomes=outcomes,
        outcome="completed" if completed else "insufficient",
        reason_code=None if completed else "verification_fields_unresolved",
    )
    return ReceiptChainV1(task=task, task_hash=task.task_hash, receipts=(receipt,))


def _fixture(
    *,
    schema_hash: str = HASH_E,
) -> tuple[
    ChangeSetDraftV1,
    tuple[VerifiedFactV1, ...],
    tuple[VerificationBatchV1, ...],
    tuple[ReceiptChainV1, ...],
    tuple[FactVerificationLinkV1, ...],
    tuple[RepairResolutionV1, ...],
]:
    prior = _fact(
        FIELD_CONFLICT,
        revision="revision-old",
        source_hash=HASH_A,
        value_hash=HASH_A,
        evidence_hash=HASH_B,
        reliable_at="2026-01-01T00:00:00.000000Z",
    )
    incoming = _fact(
        FIELD_CONFLICT,
        revision="revision-new",
        source_hash=HASH_C,
        value_hash=HASH_C,
        evidence_hash=HASH_C,
        reliable_at="2026-01-01T00:00:00.000000Z",
    )
    added = _fact(
        FIELD_ADD,
        revision="revision-new",
        source_hash=HASH_C,
        value_hash=HASH_D,
        evidence_hash=HASH_D,
        reliable_at="2026-01-01T00:00:00.000000Z",
    )
    conflict = ChangeItemDraftV1(
        action="conflict",
        scope=incoming.scope,
        incoming_fact_hash=incoming.fact_hash,
        prior_fact_hashes=(prior.fact_hash,),
        evidence_hashes=(HASH_B, HASH_C),
        reason="unresolved authority conflict",
    )
    add = ChangeItemDraftV1(
        action="add",
        scope=added.scope,
        incoming_fact_hash=added.fact_hash,
        evidence_hashes=(HASH_D,),
        reason="new verified fact",
    )
    items = tuple(sorted((conflict, add), key=lambda item: (item.scope.scope_hash, item.item_hash)))
    change_set = ChangeSetDraftV1(
        space_id="space-059",
        product_version_id="596-1",
        authority_policy_hash=HASH_A,
        input_hash=HASH_F,
        items=items,
    )
    receipt_specs = (
        (prior, HASH_A),
        (incoming, HASH_B),
        (added, HASH_C),
    )
    verifications = tuple(
        _verification(
            fact.scope.field_id,
            revision=fact.authority.source_revision_id,
            candidate_snapshot_hash=candidate_hash,
        )
        for fact, candidate_hash in receipt_specs
    )
    links = tuple(
        FactVerificationLinkV1(
            fact_hash=fact.fact_hash,
            verification_hash=verification.verification_hash,
            field_id=fact.scope.field_id,
            candidate_snapshot_hash=candidate_hash,
        )
        for (fact, candidate_hash), verification in zip(
            receipt_specs, verifications, strict=True
        )
    )
    repair_verification = VerificationBatchV1(
        contract="evidence-verification-batch.v1",
        product_version_id="596-1",
        source_revision_id="revision-repair",
        parse_attempt_id="attempt:revision-repair",
        parsed_document_hash=HASH_D,
        parse_manifest_hash=HASH_E,
        results=(
            FieldVerificationV1(
                field_id=FIELD_ADD,
                status="PASS",
                reason_codes=(),
                candidate_snapshot_hash=HASH_D,
            ),
            FieldVerificationV1(
                field_id=FIELD_REPAIR,
                status="FAIL",
                reason_codes=("repair_exhausted",),
                candidate_snapshot_hash=HASH_F,
            ),
        ),
    )
    repair = RepairResolutionV1(
        contract="targeted-repair-resolution.v1",
        parent_verification_hash=repair_verification.verification_hash,
        repair_plan_hash=HASH_F,
        results=repair_verification.results,
        gaps=(GapV1(field_id=FIELD_REPAIR, reason_codes=("repair_exhausted",)),),
        review_items=(
            EvidenceReviewItemV1(
                field_id=FIELD_REPAIR,
                reason_code="repair_exhausted",
                parent_verification_hash=repair_verification.verification_hash,
            ),
        ),
    )
    return (
        change_set,
        (prior, incoming, added),
        (*verifications, repair_verification),
        tuple(
            _receipt_chain(verification, schema_hash=schema_hash)
            for verification in (*verifications, repair_verification)
        ),
        links,
        (repair,),
    )


def _build(
    *,
    schema_hash: str = HASH_E,
    reorder: bool = False,
) -> CandidateAssemblyV1:
    change_set, facts, verifications, chains, links, repairs = _fixture(
        schema_hash=schema_hash
    )
    if reorder:
        facts = tuple(reversed(facts))
        verifications = tuple(reversed(verifications))
        chains = tuple(reversed(chains))
        links = tuple(reversed(links))
    return build_fixture_candidate_batch(
        change_set=change_set,
        facts=facts,
        verification_batches=verifications,
        receipt_chains=chains,
        fact_verification_links=links,
        repair_resolutions=repairs,
        review_policy=HumanBatchPolicyV1(
            policy_id="human-batch-fixture-v1",
            high_risk_field_ids=(FIELD_ADD,),
        ),
    )


def test_real_058_contract_builds_stable_candidate_and_human_batch() -> None:
    left = _build()
    right = _build(reorder=True)

    assert left == right
    assert left.candidate.candidate_hash == right.candidate.candidate_hash
    assert left.human_batch.batch_hash == right.human_batch.batch_hash
    assert left.candidate.change_set.contract_version == "058.v1"
    assert left.candidate.change_set.object_type == "incremental_change_set.v1"
    assert left.candidate.space_id == "space-059"
    assert left.candidate.product_version_id == "596-1"
    assert left.candidate.schema_contract == ArtifactRefV1(
        object_type="schema-contract.v1", artifact_hash=HASH_E
    )
    assert left.candidate.source_revision_ids == (
        "revision-new",
        "revision-old",
        "revision-repair",
    )


def test_conflict_retains_all_competing_facts_and_evidence() -> None:
    assembled = _build()
    conflict_change = next(
        item for item in assembled.candidate.changes if item.item.action == "conflict"
    )
    conflict_review = next(
        item for item in assembled.human_batch.items if "conflict" in item.reasons
    )

    assert conflict_change.incoming_fact is not None
    assert len(conflict_change.prior_facts) == 1
    assert conflict_review.fact_hashes == tuple(
        sorted(
            (
                conflict_change.incoming_fact.fact_hash,
                conflict_change.prior_facts[0].fact_hash,
            )
        )
    )
    assert conflict_review.evidence_hashes == (HASH_B, HASH_C)


def test_batch_contains_conflict_high_risk_and_repair_needed_without_decision() -> None:
    assembled = _build()
    by_field = {item.field_id: item for item in assembled.human_batch.items}

    assert by_field[FIELD_CONFLICT].reasons == ("conflict",)
    assert by_field[FIELD_ADD].reasons == ("high_risk",)
    assert by_field[FIELD_REPAIR].reasons == ("repair_needed",)
    dumped = json.dumps(assembled.model_dump(mode="json"), sort_keys=True)
    for forbidden in ("approved", "decision", "release_id", "active_head"):
        assert f'"{forbidden}"' not in dumped
    assert assembled.human_batch.authority == "NONE_REQUIRES_NAMED_HUMAN"


def test_aggregate_rejects_direct_human_batch_membership_omission() -> None:
    assembled = _build()
    empty_batch = HumanBatchV1(
        candidate_hash=assembled.candidate.candidate_hash,
        review_policy=assembled.human_batch.review_policy,
        items=(),
    )

    with pytest.raises(
        ValidationError, match="human_batch_required_membership_mismatch"
    ):
        CandidateAssemblyV1(
            candidate=assembled.candidate,
            human_batch=empty_batch,
        )

    with pytest.raises(
        ValidationError, match="human_batch_required_membership_mismatch"
    ):
        assembled.model_copy(update={"human_batch": empty_batch})


def test_aggregate_rejects_weakened_conflict_evidence_custody() -> None:
    assembled = _build()
    conflict = next(
        item for item in assembled.human_batch.items if "conflict" in item.reasons
    )
    weakened = conflict.model_copy(update={"evidence_hashes": (HASH_B,)})
    weakened_batch = HumanBatchV1(
        candidate_hash=assembled.candidate.candidate_hash,
        review_policy=assembled.human_batch.review_policy,
        items=tuple(
            weakened if item == conflict else item
            for item in assembled.human_batch.items
        ),
    )

    with pytest.raises(
        ValidationError, match="human_batch_required_membership_mismatch"
    ):
        CandidateAssemblyV1(
            candidate=assembled.candidate,
            human_batch=weakened_batch,
        )

    conflict_change = next(
        item for item in assembled.candidate.changes if item.item.action == "conflict"
    )
    with pytest.raises(ValidationError, match="prior_fact_membership_mismatch"):
        conflict_change.model_copy(update={"prior_facts": ()})


def test_aggregate_rejects_repair_only_source_membership_drift() -> None:
    assembled = _build()

    with pytest.raises(
        ValidationError, match="candidate_source_revision_membership_mismatch"
    ):
        assembled.candidate.model_copy(
            update={"source_revision_ids": ("revision-new", "revision-old")}
        )


def test_candidate_and_batch_hashes_are_byte_mutation_sensitive() -> None:
    baseline = _build(schema_hash=HASH_E)
    mutated = _build(schema_hash=("e" * 63) + "f")

    assert baseline.candidate.candidate_hash != mutated.candidate.candidate_hash
    assert baseline.human_batch.batch_hash != mutated.human_batch.batch_hash


def test_exact_054_authority_rejects_foreign_space_or_schema() -> None:
    change_set, facts, verifications, chains, links, repairs = _fixture()
    policy = HumanBatchPolicyV1(
        policy_id="human-batch-fixture-v1",
        high_risk_field_ids=(FIELD_ADD,),
    )
    foreign_space = _receipt_chain(verifications[0], space_id="space-foreign")
    with pytest.raises(CandidateAssemblyError, match="candidate_identity_mismatch"):
        build_fixture_candidate_batch(
            change_set=change_set,
            facts=facts,
            verification_batches=verifications,
            receipt_chains=(foreign_space, *chains[1:]),
            fact_verification_links=links,
            repair_resolutions=repairs,
            review_policy=policy,
        )

    foreign_schema = _receipt_chain(verifications[0], schema_hash=HASH_F)
    with pytest.raises(CandidateAssemblyError, match="candidate_identity_mismatch"):
        build_fixture_candidate_batch(
            change_set=change_set,
            facts=facts,
            verification_batches=verifications,
            receipt_chains=(foreign_schema, *chains[1:]),
            fact_verification_links=links,
            repair_resolutions=repairs,
            review_policy=policy,
        )


def test_repair_review_result_requires_exact_unique_bijection() -> None:
    change_set, facts, verifications, chains, links, repairs = _fixture()
    duplicate = repairs[0].model_copy(update={"repair_plan_hash": HASH_A})

    with pytest.raises(CandidateAssemblyError, match="candidate_identity_mismatch"):
        build_fixture_candidate_batch(
            change_set=change_set,
            facts=facts,
            verification_batches=verifications,
            receipt_chains=chains,
            fact_verification_links=links,
            repair_resolutions=(*repairs, duplicate),
            review_policy=HumanBatchPolicyV1(
                policy_id="human-batch-fixture-v1",
                high_risk_field_ids=(FIELD_ADD,),
            ),
        )


def test_repair_cannot_rewrite_parent_pass_into_a_self_consistent_failure() -> None:
    assembled = _build()
    candidate = assembled.candidate
    repair = candidate.repair_resolutions[0]
    parent = next(
        item
        for item in candidate.verification_batches
        if item.verification_hash == repair.parent_verification_hash
    )
    parent_pass = next(item for item in parent.results if item.status == "PASS")
    forged_failure = parent_pass.model_copy(
        update={"status": "FAIL", "reason_codes": ("forged_failure",)}
    )
    forged_results = tuple(
        forged_failure if item.field_id == parent_pass.field_id else item
        for item in repair.results
    )
    forged_gaps = tuple(
        sorted(
            (
                *repair.gaps,
                GapV1(
                    field_id=parent_pass.field_id,
                    reason_codes=("forged_failure",),
                ),
            ),
            key=lambda item: item.field_id,
        )
    )
    forged_reviews = tuple(
        sorted(
            (
                *repair.review_items,
                EvidenceReviewItemV1(
                    field_id=parent_pass.field_id,
                    reason_code="forged_failure",
                    parent_verification_hash=parent.verification_hash,
                ),
            ),
            key=lambda item: item.field_id,
        )
    )
    forged_repair = repair.model_copy(
        update={
            "results": forged_results,
            "gaps": forged_gaps,
            "review_items": forged_reviews,
        }
    )
    candidate_payload = candidate.model_dump(
        mode="python", exclude_computed_fields=True
    )
    candidate_payload["repair_resolutions"] = (forged_repair,)

    with pytest.raises(ValidationError, match="repair_parent_pass_result_drift"):
        type(candidate).model_validate(candidate_payload)
    with pytest.raises(ValidationError, match="repair_parent_pass_result_drift"):
        candidate.model_copy(update={"repair_resolutions": (forged_repair,)})


def test_missing_or_ambiguous_fact_receipt_fails_closed() -> None:
    change_set, facts, verifications, chains, links, repairs = _fixture()
    policy = HumanBatchPolicyV1(
        policy_id="human-batch-fixture-v1",
        high_risk_field_ids=(FIELD_ADD,),
    )
    with pytest.raises(CandidateAssemblyError, match="fact_receipt_bijection_mismatch"):
        build_fixture_candidate_batch(
            change_set=change_set,
            facts=facts,
            verification_batches=verifications,
            receipt_chains=chains,
            fact_verification_links=links[:-1],
            repair_resolutions=repairs,
            review_policy=policy,
        )
    with pytest.raises(CandidateAssemblyError, match="duplicate_verification_receipt"):
        build_fixture_candidate_batch(
            change_set=change_set,
            facts=facts,
            verification_batches=(*verifications, verifications[0]),
            receipt_chains=chains,
            fact_verification_links=links,
            repair_resolutions=repairs,
            review_policy=policy,
        )


def test_cross_scope_or_nonpassing_receipt_fails_closed() -> None:
    change_set, facts, verifications, chains, links, repairs = _fixture()
    policy = HumanBatchPolicyV1(
        policy_id="human-batch-fixture-v1",
        high_risk_field_ids=(FIELD_ADD,),
    )
    foreign = verifications[0].model_copy(update={"product_version_id": "596-2"})
    foreign_link = links[0].model_copy(
        update={"verification_hash": foreign.verification_hash}
    )
    with pytest.raises(CandidateAssemblyError, match="verification_scope_mismatch"):
        build_fixture_candidate_batch(
            change_set=change_set,
            facts=facts,
            verification_batches=(foreign, *verifications[1:]),
            receipt_chains=chains,
            fact_verification_links=(foreign_link, *links[1:]),
            repair_resolutions=repairs,
            review_policy=policy,
        )
    failed = _verification(
        facts[0].scope.field_id,
        revision=facts[0].authority.source_revision_id,
        candidate_snapshot_hash=links[0].candidate_snapshot_hash,
        status="FAIL",
    )
    failed_link = links[0].model_copy(
        update={"verification_hash": failed.verification_hash}
    )
    with pytest.raises(CandidateAssemblyError, match="fact_receipt_not_verified"):
        build_fixture_candidate_batch(
            change_set=change_set,
            facts=facts,
            verification_batches=(failed, *verifications[1:]),
            receipt_chains=chains,
            fact_verification_links=(failed_link, *links[1:]),
            repair_resolutions=repairs,
            review_policy=policy,
        )


def test_058_model_copy_scope_bypass_is_revalidated() -> None:
    change_set, facts, verifications, chains, links, repairs = _fixture()
    forged_scope = facts[0].scope.model_copy(update={"space_id": "space-foreign"})
    forged = facts[0].model_copy(update={"scope": forged_scope})
    with pytest.raises(CandidateAssemblyError, match="change_fact_membership_mismatch"):
        build_fixture_candidate_batch(
            change_set=change_set,
            facts=(forged, *facts[1:]),
            verification_batches=verifications,
            receipt_chains=chains,
            fact_verification_links=links,
            repair_resolutions=repairs,
            review_policy=HumanBatchPolicyV1(
                policy_id="human-batch-fixture-v1",
                high_risk_field_ids=(FIELD_ADD,),
            ),
        )


def test_review_policy_is_exact_and_cannot_reference_unaffected_fields() -> None:
    with pytest.raises(ValidationError):
        HumanBatchPolicyV1(
            policy_id="human-batch-fixture-v1",
            high_risk_field_ids=(FIELD_ADD, FIELD_ADD),
        )
    change_set, facts, verifications, chains, links, repairs = _fixture()
    with pytest.raises(CandidateAssemblyError, match="high_risk_field_not_affected"):
        build_fixture_candidate_batch(
            change_set=change_set,
            facts=facts,
            verification_batches=verifications,
            receipt_chains=chains,
            fact_verification_links=links,
            repair_resolutions=repairs,
            review_policy=HumanBatchPolicyV1(
                policy_id="human-batch-fixture-v1",
                high_risk_field_ids=("zh_unaffected",),
            ),
        )
