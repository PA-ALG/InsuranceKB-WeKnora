"""OpenSpec074: one fair weak/strong rerun contract for Product 596-1."""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler import extraction_receipts as extraction_receipts
from insurance_harness.compiler import extraction_tasks as extraction_tasks
from insurance_harness.compiler import material_profiles
from insurance_harness.knowledge_compiler import field_contracts_596_1 as contracts
from insurance_harness.knowledge_compiler import semantic_input_binding as semantic
from insurance_harness.knowledge_compiler import vertical_falsification as vf
from insurance_harness.knowledge_compiler import weak_strong_ceiling as ceiling
from insurance_harness.knowledge_compiler.fair_rerun_596_1 import (
    FairRerunResultV1,
    run_596_1_fair_rerun,
)

NOW = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
CATALOG_PATH = Path(__file__).parent / "fixtures/material_profile_596_1_052.json"
PRIVATE_KEY = Ed25519PrivateKey.generate()
AUTHORITY = contracts.NamedHumanAuthorityV1(
    principal_id="human:596-1-field-contract-owner",
    display_name="596-1 field contract owner",
    signer_key_id="human-field-contract-key-2026-08",
    public_key=PRIVATE_KEY.public_key(),
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _request() -> contracts.FieldContractAuthorityRequestV1:
    return contracts.FieldContractAuthorityRequestV1(
        field_contracts_sha256=contracts.EXACT8_FIELD_CONTRACTS_SHA256,
        decision_package_sha256=contracts.DECISION_PACKAGE_SHA256,
        pending_resolution_sha256=_sha("074-resolution"),
        provenance=contracts.ConversationProvenanceV1(
            source_thread_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
            conversation_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
            user_approval_ref="user-message:074-fair-rerun",
        ),
    )


def _receipt(
    request: contracts.FieldContractAuthorityRequestV1,
) -> contracts.FieldContractUserReceiptV1:
    unsigned = contracts.FieldContractUserReceiptV1(
        contract_id=contracts.FIELD_CONTRACT_USER_RECEIPT_ID,
        issued_by="total-control",
        actor_type="human",
        principal_id=AUTHORITY.principal_id,
        approved_by=AUTHORITY.display_name,
        action="approve",
        subject_sha256=contracts.field_contract_authority_subject_sha256(request),
        field_contracts_sha256=request.field_contracts_sha256,
        decision_package_sha256=request.decision_package_sha256,
        pending_resolution_sha256=request.pending_resolution_sha256,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=5),
        provenance=request.provenance,
        signer_key_id=AUTHORITY.signer_key_id,
        signature_b64="",
        receipt_sha256="",
    )
    signature = base64.b64encode(
        PRIVATE_KEY.sign(contracts.field_contract_receipt_signing_bytes(unsigned))
    ).decode("ascii")
    signed = replace(unsigned, signature_b64=signature)
    return replace(
        signed,
        receipt_sha256=contracts.field_contract_receipt_sha256(signed),
    )


def _execution_identity(*, weak: bool) -> semantic.SemanticExecutionIdentityV1:
    return semantic.SemanticExecutionIdentityV1(
        model_id=(vf.APPROVED_SEMANTIC_MODEL_ID if weak else ceiling.STRONG_MODEL_ID),
        model_identity_sha256=(
            vf.APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256
            if weak
            else ceiling.APPROVED_STRONG_MODEL_IDENTITY_SHA256
        ),
        prompt_contract_id="596-1-shared-semantic-prompt.v1",
        prompt_template_sha256=vf.APPROVED_PROMPT_IDENTITY_SHA256,
        budget_identity_sha256=vf.APPROVED_BUDGET_IDENTITY_SHA256,
        normalizer_identity_sha256=vf.APPROVED_NORMALIZER_IDENTITY_SHA256,
        output_contract_id="freeform-arm-evidence-binding-receipt.v1",
        output_contract_identity_sha256=_sha("069-output-contract"),
    )


MaterialRole = Literal["terms", "brochure", "rate_table"]


def _approved_task_rows() -> tuple[dict[str, object], ...]:
    payload = ceiling._approved_task_plan_payload()
    return cast(tuple[dict[str, object], ...], payload["tasks"])


def _blueprint(*, weak: bool) -> semantic.SharedSemanticTaskPlanV1:
    catalog = material_profiles.load_material_profile_catalog(CATALOG_PATH)
    profiles = {item.material_role: item for item in catalog.profiles}
    execution = _execution_identity(weak=weak)
    bindings = {
        role: _sha(f"074-material-profile-binding-{role}")
        for role in semantic.EXPECTED_ROLES
    }
    tasks: list[semantic.SharedSemanticTaskBlueprintV1] = []
    for row in _approved_task_rows():
        role = cast(MaterialRole, row["material_role"])
        fields = cast(tuple[str, ...], row["field_ids"])
        payload = {
            **row,
            "material_profile_id": profiles[role].profile_id,
            "material_profile_binding_hash": bindings[role],
            "resolved_template_content_hash": _sha(f"074-template-{role}"),
            "material_profile_catalog_hash": vf.APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
            "schema_sha256": vf.APPROVED_SCHEMA_REGISTRY_SHA256,
            "model_id": execution.model_id,
            "model_identity_sha256": execution.model_identity_sha256,
            "prompt_identity_sha256": vf.APPROVED_PROMPT_IDENTITY_SHA256,
            "budget_identity_sha256": execution.budget_identity_sha256,
            "normalizer_identity_sha256": execution.normalizer_identity_sha256,
            "output_contract_identity_sha256": execution.output_contract_identity_sha256,
        }
        assert fields == tuple(sorted(fields))
        tasks.append(
            semantic.SharedSemanticTaskBlueprintV1.model_validate(
                {
                    **payload,
                    "task_hash": canonical_hash(
                        semantic.TASK_BLUEPRINT_OBJECT_TYPE, payload
                    ),
                }
            )
        )
    task_tuple = tuple(tasks)
    resolution_hashes = cast(
        tuple[str, str, str],
        tuple(bindings[role] for role in semantic.EXPECTED_ROLES),
    )
    payload = {
        "contract": semantic.SHARED_BLUEPRINT_CONTRACT,
        "product_version_id": vf.APPROVED_PRODUCT_VERSION_ID,
        "schema_version": vf.APPROVED_SCHEMA_VERSION,
        "schema_sha256": vf.APPROVED_SCHEMA_REGISTRY_SHA256,
        "source_sha256": vf.APPROVED_596_1_SOURCE_SHA256,
        "material_profile_catalog_hash": vf.APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
        "resolution_binding_hashes": resolution_hashes,
        "execution_identity": execution.model_dump(mode="python"),
        "tasks": tuple(item.model_dump(mode="python") for item in task_tuple),
    }
    return semantic.SharedSemanticTaskPlanV1.model_validate(
        {
            **payload,
            "blueprint_hash": canonical_hash(
                semantic.SHARED_BLUEPRINT_OBJECT_TYPE, payload
            ),
        }
    )


def _source_bindings() -> tuple[
    semantic.SemanticSourceBindingV1,
    semantic.SemanticSourceBindingV1,
    semantic.SemanticSourceBindingV1,
]:
    sources = []
    for role, source_sha256 in zip(
        semantic.EXPECTED_ROLES, vf.APPROVED_596_1_SOURCE_SHA256, strict=True
    ):
        content = f"074 isolated {role} semantic snapshot"
        sources.append(
            semantic.SemanticSourceBindingV1(
                material_role=role,
                source_revision_id=f"074-source-revision-{role}",
                parse_attempt_id=f"074-parse-attempt-{role}",
                source_sha256=source_sha256,
                document_hash=_sha(f"074-document-{role}"),
                manifest_hash=_sha(f"074-manifest-{role}"),
                quality_decision_hash=_sha(f"074-quality-{role}"),
                capture_identity_sha256=_sha(f"074-capture-{role}"),
                content_snapshot_sha256=hashlib.sha256(content.encode()).hexdigest(),
                content_snapshot=content,
            )
        )
    return cast(
        tuple[
            semantic.SemanticSourceBindingV1,
            semantic.SemanticSourceBindingV1,
            semantic.SemanticSourceBindingV1,
        ],
        tuple(sources),
    )


def _artifact_ref(task_id: str, object_type: str) -> extraction_tasks.ArtifactRefV1:
    return extraction_tasks.ArtifactRefV1(
        object_type=object_type,
        artifact_hash=_sha(f"074-{task_id}-{object_type}"),
    )


def _composed_tasks(
    blueprint: semantic.SharedSemanticTaskPlanV1,
) -> tuple[semantic.ComposedSemanticTaskV1, ...]:
    catalog = material_profiles.load_material_profile_catalog(CATALOG_PATH)
    profiles = {item.material_role: item for item in catalog.profiles}
    role_fields = {
        role: tuple(
            sorted(
                field_id
                for task in blueprint.tasks
                if task.task_kind == "semantic" and task.material_role == role
                for field_id in task.field_ids
            )
        )
        for role in cast(tuple[Literal["terms", "brochure"], ...], ("terms", "brochure"))
    }
    authorities = {
        "terms": material_profiles.FieldAuthority(
            authority_class="contract_fact",
            primary_role="terms",
            support_roles=("brochure",),
            field_ids=role_fields["terms"],
        ),
        "brochure": material_profiles.FieldAuthority(
            authority_class="brochure_fact",
            primary_role="brochure",
            support_roles=("terms",),
            field_ids=role_fields["brochure"],
        ),
    }
    composed = []
    for blueprint_task in blueprint.tasks:
        if blueprint_task.task_kind == "deterministic_rate":
            composed.append(
                semantic.ComposedSemanticTaskV1(
                    task_id=blueprint_task.task_id,
                    task_kind=blueprint_task.task_kind,
                    material_role=blueprint_task.material_role,
                    field_ids=blueprint_task.field_ids,
                    extraction_task=None,
                    initial_attempt=None,
                )
            )
            continue
        role = cast(Literal["terms", "brochure"], blueprint_task.material_role)
        profile = profiles[role]
        receipt = material_profiles.ParsePolicyReceipt.model_validate(
            {
                **profile.parse_policy.model_dump(mode="python"),
                "required_parse_capabilities": profile.required_parse_capabilities,
            }
        )
        budget = extraction_tasks.AttemptBudgetV1(
            max_fields=len(blueprint_task.field_ids),
            max_total_attempts=2,
            max_targeted_repairs=1,
        )
        task_profile = extraction_tasks.build_extraction_task_profile(
            material_profile=profile,
            material_profile_binding_hash=blueprint_task.material_profile_binding_hash,
            parse_policy_receipt=receipt,
            field_authority=authorities[role],
            attempt_budget=budget,
        )

        refs = extraction_tasks.ExtractionInputRefsV1(
            source_revision=_artifact_ref(blueprint_task.task_id, "source-revision.v1"),
            material_profile=extraction_tasks.ArtifactRefV1(
                object_type=material_profiles.MATERIAL_PROFILE_BINDING_OBJECT_TYPE,
                artifact_hash=blueprint_task.material_profile_binding_hash,
            ),
            resolved_template=_artifact_ref(
                blueprint_task.task_id, "resolved-template.v1"
            ),
            schema_contract=_artifact_ref(
                blueprint_task.task_id, "schema-contract.v1"
            ),
            parsed_document=_artifact_ref(
                blueprint_task.task_id, "parsed-document.v1"
            ),
            parse_manifest=_artifact_ref(blueprint_task.task_id, "parse-manifest.v1"),
            parse_quality_decision=_artifact_ref(
                blueprint_task.task_id, "parse-quality-decision.v1"
            ),
        )
        task = extraction_tasks.build_extraction_task(
            space_id="space-074",
            product_version_id=vf.APPROVED_PRODUCT_VERSION_ID,
            source_revision_id=f"074-source-revision-{role}",
            material_role=role,
            module_id=blueprint_task.module_id,
            risk_partition_id=blueprint_task.risk_partition_id,
            field_ids=blueprint_task.field_ids,
            input_refs=refs,
            budget=budget,
            task_profile=task_profile,
        )
        composed.append(
            semantic.ComposedSemanticTaskV1(
                task_id=blueprint_task.task_id,
                task_kind=blueprint_task.task_kind,
                material_role=role,
                field_ids=blueprint_task.field_ids,
                extraction_task=task,
                initial_attempt=extraction_receipts.build_initial_attempt(task),
            )
        )
    return tuple(composed)


def _composition() -> semantic.SemanticInputCompositionV1:
    blueprints = (_blueprint(weak=True), _blueprint(weak=False))
    sources = _source_bindings()
    tasks = _composed_tasks(blueprints[0])
    admission_receipt = _sha("074-admission-receipt")
    payload = {
        "contract": "596-1-semantic-input-composition.v1",
        "product_version_id": vf.APPROVED_PRODUCT_VERSION_ID,
        "schema_sha256": vf.APPROVED_SCHEMA_REGISTRY_SHA256,
        "material_profile_catalog_hash": vf.APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
        "admission_receipt_digest_sha256": admission_receipt,
        "arm_blueprint_hashes": tuple(item.blueprint_hash for item in blueprints),
        "sources": tuple(
            item.model_dump(mode="python", exclude={"content_snapshot"})
            for item in sources
        ),
        "task_hashes": tuple(
            item.extraction_task.task_hash if item.extraction_task else item.task_id
            for item in tasks
        ),
    }
    return semantic.SemanticInputCompositionV1(
        contract="596-1-semantic-input-composition.v1",
        product_version_id="596-1",
        schema_sha256=vf.APPROVED_SCHEMA_REGISTRY_SHA256,
        material_profile_catalog_hash=vf.APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
        admission_receipt_digest_sha256=admission_receipt,
        arm_blueprints=blueprints,
        sources=sources,
        tasks=tasks,
        composition_hash=canonical_hash(semantic.SEMANTIC_COMPOSITION_OBJECT_TYPE, payload),
    )


def _arm_identity(
    composition: semantic.SemanticInputCompositionV1, *, weak: bool
) -> vf.ArmInputIdentityV1:
    return vf.ArmInputIdentityV1(
        product_version_id=vf.APPROVED_PRODUCT_VERSION_ID,
        source_sha256=vf.APPROVED_596_1_SOURCE_SHA256,
        schema_version=vf.APPROVED_SCHEMA_VERSION,
        schema_sha256=vf.APPROVED_SCHEMA_REGISTRY_SHA256,
        parser_identity_sha256=_sha("shared-mineru-parser"),
        model_identity_sha256=(
            vf.APPROVED_SEMANTIC_MODEL_IDENTITY_SHA256
            if weak
            else ceiling.APPROVED_STRONG_MODEL_IDENTITY_SHA256
        ),
        semantic_model_id=(
            vf.APPROVED_SEMANTIC_MODEL_ID if weak else ceiling.STRONG_MODEL_ID
        ),
        semantic_api_base=(
            vf.APPROVED_SEMANTIC_API_BASE
            if weak
            else ceiling.STRONG_EXECUTION_SURFACE
        ),
        prompt_identity_sha256=vf.APPROVED_PROMPT_IDENTITY_SHA256,
        budget_identity_sha256=vf.APPROVED_BUDGET_IDENTITY_SHA256,
        normalizer_identity_sha256=vf.APPROVED_NORMALIZER_IDENTITY_SHA256,
        comparator_identity_sha256=vf.APPROVED_COMPARATOR_IDENTITY_SHA256,
        arm_profile_sha256=ceiling.APPROVED_SHARED_TASK_PLAN_SHA256,
        parse_artifact_receipt_digest_sha256=(
            composition.admission_receipt_digest_sha256
        ),
        parser_id="mineru-cloud-pipeline",
        parser_mode="bounded_upgrade",
        parser_attempt=2,
    )


def _fields() -> tuple[vf.ArmFieldOutputV1, ...]:
    return tuple(
        vf.ArmFieldOutputV1(
            field_id=field_id,
            state="unknown",
            value_snapshot=None,
        )
        for field_id in vf.APPROVED_SCHEMA60_FIELD_IDS
    )


def _run(
    *,
    receipt: contracts.FieldContractUserReceiptV1 | None,
    weak_identity: vf.ArmInputIdentityV1 | None = None,
    weak_fields: tuple[vf.ArmFieldOutputV1, ...] | None = None,
    weak_error: bool = False,
    strong_error: bool = False,
) -> tuple[FairRerunResultV1, list[tuple[str, str]]]:
    composition = _composition()
    calls: list[tuple[str, str]] = []

    def weak(
        actual: semantic.SemanticInputCompositionV1,
        _identity: vf.ArmInputIdentityV1,
    ) -> tuple[vf.ArmFieldOutputV1, ...]:
        calls.append(("weak", actual.composition_hash))
        if weak_error:
            raise RuntimeError("secret weak provider error")
        return weak_fields if weak_fields is not None else _fields()

    def strong(
        actual: semantic.SemanticInputCompositionV1,
        _identity: vf.ArmInputIdentityV1,
    ) -> tuple[vf.ArmFieldOutputV1, ...]:
        calls.append(("strong", actual.composition_hash))
        if strong_error:
            raise RuntimeError("secret strong provider error")
        return _fields()

    return (
        run_596_1_fair_rerun(
            composition=composition,
            authority_request=_request(),
            user_receipt=receipt,
            authority=AUTHORITY,
            now=NOW,
            weak_identity=(
                weak_identity
                if weak_identity is not None
                else _arm_identity(composition, weak=True)
            ),
            strong_identity=_arm_identity(composition, weak=False),
            weak_execute=weak,
            strong_execute=strong,
        ),
        calls,
    )


def test_missing_073_receipt_blocks_before_arm_calls() -> None:
    result, calls = _run(receipt=None)

    assert result.status == "BLOCKED_ON_FIELD_CONTRACT_AUTHORITY"
    assert result.reason_codes == ("EXACT_USER_RECEIPT_MISSING",)
    assert result.weak_calls == 0
    assert result.strong_calls == 0
    assert calls == []


def test_exact_contract_calls_weak_then_strong_once_and_freezes_both() -> None:
    request = _request()
    result, calls = _run(receipt=_receipt(request))

    assert [label for label, _hash in calls] == ["weak", "strong"]
    assert calls[0][1] == calls[1][1]
    assert result.status == "OUTPUTS_FROZEN_FOR_049_SCORING"
    assert result.weak_calls == result.strong_calls == 1
    assert result.weak_output is not None and vf.verify_arm_output_hash(result.weak_output)
    assert result.strong_output is not None and vf.verify_arm_output_hash(result.strong_output)
    assert result.weak_score_authority == "SCORED"
    assert result.strong_score_authority == "UNADMITTED_RAW"
    assert result.pair_receipt_sha256 is not None
    assert result.golden_reads == 0


@pytest.mark.parametrize(
    "mutate",
    (
        lambda identity: replace(
            identity, source_sha256=(_sha("a"), _sha("b"), _sha("c"))
        ),
        lambda identity: replace(
            identity, parser_identity_sha256=_sha("another-parser")
        ),
        lambda identity: replace(
            identity, prompt_identity_sha256=_sha("another-prompt")
        ),
        lambda identity: replace(
            identity, budget_identity_sha256=_sha("another-budget")
        ),
        lambda identity: replace(
            identity, normalizer_identity_sha256=_sha("another-normalizer")
        ),
        lambda identity: replace(
            identity, arm_profile_sha256=_sha("another-task-plan")
        ),
    ),
)
def test_shared_identity_drift_blocks_before_calls(
    mutate: Callable[[vf.ArmInputIdentityV1], vf.ArmInputIdentityV1],
) -> None:
    composition = _composition()
    drifted = mutate(_arm_identity(composition, weak=True))
    result, calls = _run(
        receipt=_receipt(_request()),
        weak_identity=drifted,
    )

    assert result.status == "BLOCKED_ON_FAIR_RERUN_CONTRACT"
    assert result.weak_calls == result.strong_calls == 0
    assert calls == []


def test_incomplete_output_blocks_without_strong_or_scoring_authority() -> None:
    result, calls = _run(
        receipt=_receipt(_request()),
        weak_fields=_fields()[:-1],
    )

    assert [label for label, _hash in calls] == ["weak"]
    assert result.status == "BLOCKED_ON_FAIR_RERUN_CONTRACT"
    assert result.reason_codes == ("WEAK_OUTPUT_FIELD_SET_MISMATCH",)
    assert result.pair_receipt_sha256 is None
    assert result.golden_reads == 0


@pytest.mark.parametrize(
    ("weak_error", "strong_error", "expected"),
    ((True, False, ["weak"]), (False, True, ["weak", "strong"])),
)
def test_arm_failure_has_no_retry_fallback_or_scoring_receipt(
    weak_error: bool,
    strong_error: bool,
    expected: list[str],
) -> None:
    result, calls = _run(
        receipt=_receipt(_request()),
        weak_error=weak_error,
        strong_error=strong_error,
    )

    assert [label for label, _hash in calls] == expected
    assert result.status == "ARM_EXECUTION_FAILED"
    expected_reason = (
        ("WEAK_ARM_EXECUTION_FAILED",)
        if weak_error
        else ("STRONG_ARM_EXECUTION_FAILED",)
    )
    assert result.reason_codes == expected_reason
    assert result.pair_receipt_sha256 is None
    assert result.golden_reads == 0
