"""Receipt-chain fixture shared with test_expert_golden_admission_596_2_119.

The candidate-batch tests of this file left with knowledge_compiler.candidate_batches in
S7a; only the verification receipt chain that the 119 admission tests reuse remains.
"""

from __future__ import annotations

from insurance_harness.compiler.evidence_verifier import VerificationBatchV1
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

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_E = "e" * 64
HASH_F = "f" * 64


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
