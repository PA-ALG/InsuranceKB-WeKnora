"""OpenSpec079: executable 074-to-066 fair experiment bridge."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import SecretStr

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler import extraction_receipts as extraction_receipts
from insurance_harness.compiler import extraction_tasks as extraction_tasks
from insurance_harness.compiler import material_profiles
from insurance_harness.knowledge_compiler import field_contracts_596_1 as contracts
from insurance_harness.knowledge_compiler import semantic_input_binding as semantic
from insurance_harness.knowledge_compiler import vertical_falsification as vf
from insurance_harness.knowledge_compiler import weak_strong_ceiling as ceiling
from insurance_harness.knowledge_compiler.fair_experiment_bridge import (
    ArmExecutionSubmissionV1,
    ArmExecutionTransportReceiptV1,
    ArmExecutionTransportResultV1,
    FairExperimentExecutionResultV1,
    SealedFairExperimentV1,
    execute_and_freeze,
    score_frozen_experiment,
    transport_execution_receipt_sha256,
)

NOW = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
CATALOG_PATH = Path(__file__).parent / "fixtures/material_profile_596_1_052.json"
EXPECTED_066_SHARED_INPUT_SHA256 = (
    "01c3b809224a6b508f17d7b6e217a8544b9e794abba42e9d404c541718981aa4"
)
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
        pending_resolution_sha256=_sha("079-resolution"),
        provenance=contracts.ConversationProvenanceV1(
            source_thread_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
            conversation_id="019fa5ea-2507-73a2-acb8-d49030bad2f0",
            user_approval_ref="user-message:079-executable-bridge",
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
    return replace(signed, receipt_sha256=contracts.field_contract_receipt_sha256(signed))


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
        output_contract_identity_sha256=_sha("079-output-contract"),
    )


MaterialRole = Literal["terms", "brochure", "rate_table"]


def _approved_task_rows() -> tuple[dict[str, object], ...]:
    rows = (
        ("terms", "semantic", "terms-semantic-01", (
            "clause_version", "regulatory_filing_no", "zh_0c5a8e59e2",
            "zh_1ec5e3f2cc", "zh_313cabffd8", "zh_a271d96039",
            "zh_b4b770e114", "zh_d62301d84c", "zh_f558f0a88f", "zh_fd9a0b9fa3",
        )),
        ("terms", "semantic", "terms-semantic-02", (
            "claim_filing_requirements", "clause_effective_date", "exclusions_official",
            "reduced_paid_up", "reinstatement", "waiting_period_claim_handling",
            "zh_09a5d9e54e", "zh_14b93ce275", "zh_17a83223e4", "zh_7d7fe38f09",
        )),
        ("terms", "semantic", "terms-semantic-03", (
            "zh_0612362268", "zh_2df7d6256c", "zh_3a3e6520a3", "zh_4a789b1d6f",
            "zh_74aa1b9c93", "zh_74fd5a9469", "zh_c5187f228e", "zh_ca6e0226c2",
        )),
        ("terms", "semantic", "terms-semantic-04", (
            "discontinuation_renewal", "external_drug_coverage", "pre_existing_conditions",
            "zh_3d8424595d", "zh_52548821b9", "zh_e1bea0527a", "zh_f32c510a5e",
            "zh_f8cc996739",
        )),
        ("brochure", "semantic", "brochure-semantic-01", (
            "zh_0b3894ed2a", "zh_1a3227c6ce", "zh_789479e2d4", "zh_8bd90889d3",
            "zh_ad4a95859a", "zh_f1de0de938",
        )),
        ("brochure", "semantic", "brochure-semantic-02", (
            "zh_346f0dac8c", "zh_5162df17d8", "zh_67ee7025ef", "zh_6a3bd6cdbf",
            "zh_89e518b987",
        )),
        ("brochure", "semantic", "brochure-semantic-03", (
            "zh_1a5675a37a", "zh_540e1969e3", "zh_7598a3116c", "zh_b7ceabc3c0",
            "zh_c4f4b0d48a",
        )),
        ("brochure", "semantic", "brochure-semantic-04", (
            "zh_17e15e0c5a", "zh_23a2625781", "zh_58d313ee26", "zh_7bf05bc576",
            "zh_a17bd1c3f3", "zh_dcae594f8b",
        )),
        ("rate_table", "deterministic_rate", "rate-deterministic-01", ("zh_7fe8603c08",)),
        ("rate_table", "deterministic_rate", "rate-deterministic-02", ("zh_c588207763",)),
    )
    result: list[dict[str, object]] = []
    for role, kind, suffix, fields in rows:
        source_index = {"terms": 0, "brochure": 1, "rate_table": 2}[role]
        module_id = f"596-1-{suffix}"
        risk_partition_id = suffix.replace("rate-deterministic", "rate-numeric")
        result.append(
            {
                "task_id": f"069:{module_id}",
                "task_kind": kind,
                "material_role": role,
                "module_id": module_id,
                "risk_partition_id": risk_partition_id,
                "field_ids": fields,
                "source_sha256": vf.APPROVED_596_1_SOURCE_SHA256[source_index],
            }
        )
    return tuple(result)


def _blueprint(*, weak: bool) -> semantic.SharedSemanticTaskPlanV1:
    catalog = material_profiles.load_material_profile_catalog(CATALOG_PATH)
    profiles = {item.material_role: item for item in catalog.profiles}
    execution = _execution_identity(weak=weak)
    bindings = {
        role: _sha(f"079-material-profile-binding-{role}")
        for role in semantic.EXPECTED_ROLES
    }
    tasks: list[semantic.SharedSemanticTaskBlueprintV1] = []
    for row in _approved_task_rows():
        role = cast(MaterialRole, row["material_role"])
        payload = {
            **row,
            "material_profile_id": profiles[role].profile_id,
            "material_profile_binding_hash": bindings[role],
            "resolved_template_content_hash": _sha(f"079-template-{role}"),
            "material_profile_catalog_hash": vf.APPROVED_MATERIAL_PROFILE_CATALOG_SHA256,
            "schema_sha256": vf.APPROVED_SCHEMA_REGISTRY_SHA256,
            "model_id": execution.model_id,
            "model_identity_sha256": execution.model_identity_sha256,
            "prompt_identity_sha256": vf.APPROVED_PROMPT_IDENTITY_SHA256,
            "budget_identity_sha256": execution.budget_identity_sha256,
            "normalizer_identity_sha256": execution.normalizer_identity_sha256,
            "output_contract_identity_sha256": execution.output_contract_identity_sha256,
        }
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
        content = f"079 isolated {role} semantic snapshot"
        sources.append(
            semantic.SemanticSourceBindingV1(
                material_role=role,
                source_revision_id=f"079-source-revision-{role}",
                parse_attempt_id=f"079-parse-attempt-{role}",
                source_sha256=source_sha256,
                document_hash=_sha(f"079-document-{role}"),
                manifest_hash=_sha(f"079-manifest-{role}"),
                quality_decision_hash=_sha(f"079-quality-{role}"),
                capture_identity_sha256=_sha(f"079-capture-{role}"),
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
        artifact_hash=_sha(f"079-{task_id}-{object_type}"),
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
            resolved_template=_artifact_ref(blueprint_task.task_id, "resolved-template.v1"),
            schema_contract=_artifact_ref(blueprint_task.task_id, "schema-contract.v1"),
            parsed_document=_artifact_ref(blueprint_task.task_id, "parsed-document.v1"),
            parse_manifest=_artifact_ref(blueprint_task.task_id, "parse-manifest.v1"),
            parse_quality_decision=_artifact_ref(
                blueprint_task.task_id, "parse-quality-decision.v1"
            ),
        )
        task = extraction_tasks.build_extraction_task(
            space_id="space-079",
            product_version_id=vf.APPROVED_PRODUCT_VERSION_ID,
            source_revision_id=f"079-source-revision-{role}",
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
    admission_receipt = _sha("079-admission-receipt")
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
        parser_identity_sha256=vf.APPROVED_CANDIDATE_PARSER_IDENTITY_SHA256,
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
        parse_artifact_receipt_digest_sha256=composition.admission_receipt_digest_sha256,
        parser_id="mineru-cloud-pipeline",
        parser_mode="bounded_upgrade",
        parser_attempt=2,
    )


def _fields_from_submission(
    submission: ArmExecutionSubmissionV1,
) -> tuple[vf.ArmFieldOutputV1, ...]:
    composition = submission.composition
    assert len(composition.sources) == 3
    assert all(source.content_snapshot for source in composition.sources)
    task_fields = {
        field_id
        for task in composition.arm_blueprints[0].tasks
        for field_id in task.field_ids
    }
    assert task_fields == set(vf.APPROVED_SCHEMA60_FIELD_IDS)
    return tuple(
        vf.ArmFieldOutputV1(field_id=field_id, state="unknown", value_snapshot=None)
        for field_id in vf.APPROVED_SCHEMA60_FIELD_IDS
    )


def _issued_strong_receipt(
    submission: ArmExecutionSubmissionV1,
    output: vf.FrozenArmOutputV1,
) -> ceiling.StrongExecutionReceiptV1:
    payload = {
        "contract_id": ceiling.STRONG_EXECUTION_RECEIPT_CONTRACT,
        "execution_surface": ceiling.STRONG_EXECUTION_SURFACE,
        "model_id": ceiling.STRONG_MODEL_ID,
        "run_identity_sha256": "23" * 32,
        "input_identity_sha256": EXPECTED_066_SHARED_INPUT_SHA256,
        "task_plan_sha256": ceiling.APPROVED_SHARED_TASK_PLAN_SHA256,
        "model_identity_sha256": ceiling.APPROVED_STRONG_MODEL_IDENTITY_SHA256,
        "prompt_identity_sha256": submission.identity.prompt_identity_sha256,
        "budget_identity_sha256": submission.identity.budget_identity_sha256,
        "frozen_output_hash": output.output_hash,
    }
    return ceiling.StrongExecutionReceiptV1(
        **payload,
        receipt_hash=canonical_hash(
            ceiling.STRONG_EXECUTION_RECEIPT_OBJECT_TYPE, payload
        ),
    )


class _FakeTransport:
    def __init__(
        self,
        *,
        fail_role: Literal["weak", "strong"] | None = None,
        incomplete_role: Literal["weak", "strong"] | None = None,
        drift_role: Literal["weak", "strong"] | None = None,
        production_strong: bool = False,
        strong_receipt_mode: Literal["exact", "missing", "drift", "malformed"] = "exact",
    ) -> None:
        self.fail_role = fail_role
        self.incomplete_role = incomplete_role
        self.drift_role = drift_role
        self.production_strong = production_strong
        self.strong_receipt_mode = strong_receipt_mode
        self.calls: list[tuple[str, str, SecretStr]] = []
        self.submissions: list[ArmExecutionSubmissionV1] = []
        self.strong_receipts: list[ceiling.StrongExecutionReceiptV1] = []

    def submit(
        self,
        submission: ArmExecutionSubmissionV1,
        *,
        authorization: SecretStr,
    ) -> ArmExecutionTransportResultV1:
        self.calls.append(
            (submission.role, submission.composition_hash, authorization)
        )
        self.submissions.append(submission)
        if submission.role == self.fail_role:
            raise RuntimeError("provider detail must not escape")
        fields = _fields_from_submission(submission)
        if submission.role == self.incomplete_role:
            fields = fields[:-1]
        candidate = vf.freeze_arm_output(
            arm="candidate",
            identity=submission.identity,
            fields=fields,
        )
        receipt = ArmExecutionTransportReceiptV1(
            contract_id="fair-experiment-arm-execution.v1",
            role=submission.role,
            composition_hash=submission.composition_hash,
            submission_hash=submission.submission_hash,
            input_identity_sha256=submission.input_identity_sha256,
            task_plan_sha256=ceiling.APPROVED_SHARED_TASK_PLAN_SHA256,
            model_id=submission.identity.semantic_model_id,
            model_identity_sha256=submission.identity.model_identity_sha256,
            execution_surface=(
                "production-router"
                if self.production_strong and submission.role == "strong"
                else submission.identity.semantic_api_base
            ),
            prompt_identity_sha256=submission.identity.prompt_identity_sha256,
            budget_identity_sha256=submission.identity.budget_identity_sha256,
            frozen_output_hash=candidate.output_hash,
            run_identity_sha256=("12" if submission.role == "weak" else "23") * 32,
            receipt_hash="",
        )
        receipt = replace(
            receipt,
            receipt_hash=transport_execution_receipt_sha256(receipt),
        )
        if submission.role == self.drift_role:
            receipt = replace(receipt, frozen_output_hash="3" * 64)
        strong_receipt = (
            _issued_strong_receipt(submission, candidate)
            if submission.role == "strong"
            else None
        )
        if self.strong_receipt_mode == "missing":
            strong_receipt = None
        elif self.strong_receipt_mode == "drift" and strong_receipt is not None:
            strong_receipt = replace(strong_receipt, receipt_hash="5" * 64)
        elif self.strong_receipt_mode == "malformed" and strong_receipt is not None:
            strong_receipt = replace(strong_receipt, contract_id=cast(str, object()))
        if strong_receipt is not None:
            self.strong_receipts.append(strong_receipt)
        return ArmExecutionTransportResultV1(
            fields=fields,
            receipt=receipt,
            strong_execution_receipt=strong_receipt,
        )


def _exact_identities() -> tuple[vf.ArmInputIdentityV1, vf.ArmInputIdentityV1]:
    composition = _composition()
    weak = replace(
        _arm_identity(composition, weak=True),
        parser_identity_sha256=vf.APPROVED_CANDIDATE_PARSER_IDENTITY_SHA256,
    )
    strong = replace(
        _arm_identity(composition, weak=False),
        parser_identity_sha256=vf.APPROVED_CANDIDATE_PARSER_IDENTITY_SHA256,
    )
    return weak, strong


def _execute(
    transport: _FakeTransport,
    *,
    authorization: SecretStr | None = None,
    weak_identity: vf.ArmInputIdentityV1 | None = None,
    composition: object | None = None,
) -> FairExperimentExecutionResultV1:
    weak, strong = _exact_identities()
    return execute_and_freeze(
        composition=_composition() if composition is None else composition,
        authority_request=_request(),
        user_receipt=_receipt(_request()),
        authority=AUTHORITY,
        now=NOW,
        weak_identity=weak if weak_identity is None else weak_identity,
        strong_identity=strong,
        transport=transport,
        authorization=(
            SecretStr("079-test-authorization")
            if authorization is None
            else authorization
        ),
    )


def _score_for(output: vf.FrozenArmOutputV1) -> vf.AdmittedFrozenArmScoreV1:
    strong = output.identity.semantic_model_id == ceiling.STRONG_MODEL_ID
    metrics = vf.ArmQualityMetricsV1(
        denominator=60,
        critical_denominator=18,
        tri_state_correct=60,
        normalized_value_denominator=0,
        normalized_value_correct=0,
        abstentions=60,
        misses=0,
        hallucinations=0,
        wrong_values=0,
        exact_field_correct=60,
        known_denominator=0,
        known_with_evidence=0,
        critical_known_denominator=0,
        critical_known_with_evidence=0,
        critical_silent_errors=0,
        critical_semantic_errors=0,
        tri_state_correct_basis_points=10000,
        normalized_value_correct_basis_points=10000,
        abstention_basis_points=10000,
        known_evidence_basis_points=10000,
    )
    correctness = tuple(
        vf.ArmFieldCorrectnessV1(
            field_id=field_id,
            critical_priority=None,
            rate_field=False,
            tri_state_correct=True,
            exact_field_correct=True,
            known_evidence_present=False,
            rate_locator_complete=None,
        )
        for field_id in vf.APPROVED_SCHEMA60_FIELD_IDS
    )
    return vf.AdmittedFrozenArmScoreV1(
        status="UNADMITTED_RAW" if strong else "SCORED",
        reason_codes=(
            ("ARM_PROFILE_MISMATCH", "ARM_AUTHORITY_MISMATCH") if strong else ()
        ),
        metrics=metrics,
        field_correctness=correctness,
        output_hash=output.output_hash,
        arm_identity=output.identity,
        admission_receipt_digest_sha256=(
            output.identity.parse_artifact_receipt_digest_sha256
        ),
        golden_content_digest_sha256="4" * 64,
    )


def test_missing_authorization_or_shared_drift_has_zero_transport_calls() -> None:
    transport = _FakeTransport()
    weak, _strong = _exact_identities()

    missing = execute_and_freeze(
        composition=_composition(),
        authority_request=_request(),
        user_receipt=_receipt(_request()),
        authority=AUTHORITY,
        now=NOW,
        weak_identity=weak,
        strong_identity=_strong,
        transport=transport,
        authorization=None,
    )
    drifted = _execute(
        transport,
        weak_identity=replace(weak, prompt_identity_sha256="5" * 64),
    )

    assert missing.status == "BLOCKED_ON_AUTHORIZATION"
    assert missing.transport_calls == 0 and missing.golden_reads == 0
    assert drifted.status == "BLOCKED_ON_FAIR_RERUN_CONTRACT"
    assert drifted.transport_calls == 0 and drifted.golden_reads == 0
    assert transport.calls == []


def _mutated_composition(
    kind: Literal["source", "task", "prompt", "profile"],
) -> semantic.SemanticInputCompositionV1:
    composition = _composition()
    if kind == "source":
        source = composition.sources[0].model_copy(
            update={"content_snapshot": "mutated source snapshot"}
        )
        return composition.model_copy(
            update={"sources": (source, *composition.sources[1:])}
        )
    if kind == "task":
        task = composition.tasks[0].model_copy(update={"field_ids": ("clause_version",)})
        return composition.model_copy(update={"tasks": (task, *composition.tasks[1:])})
    if kind == "prompt":
        blueprint = composition.arm_blueprints[0]
        execution = blueprint.execution_identity.model_copy(
            update={"prompt_template_sha256": _sha("mutated-prompt")}
        )
        drifted = blueprint.model_copy(update={"execution_identity": execution})
        return composition.model_copy(
            update={"arm_blueprints": (drifted, composition.arm_blueprints[1])}
        )
    return composition.model_copy(
        update={"material_profile_catalog_hash": _sha("mutated-profile")}
    )


@pytest.mark.parametrize("kind", ("source", "task", "prompt", "profile"))
def test_exact_composition_drift_blocks_before_transport_or_golden(
    kind: Literal["source", "task", "prompt", "profile"],
) -> None:
    transport = _FakeTransport()

    result = _execute(transport, composition=_mutated_composition(kind))

    assert result.status == "BLOCKED_ON_FAIR_RERUN_CONTRACT"
    assert result.transport_calls == result.golden_reads == 0
    assert transport.calls == []


def test_missing_external_strong_receipt_never_seals() -> None:
    result = _execute(_FakeTransport(strong_receipt_mode="missing"))

    assert result.status == "BLOCKED_ON_TRANSPORT_RECEIPT"
    assert "STRONG_EXECUTION_RECEIPT_MISSING" in result.reason_codes
    assert result.golden_reads == 0
    assert result.sealed_experiment is None


def test_malformed_scalar_external_receipt_is_typed_transport_block() -> None:
    authorization = SecretStr("079-malformed-receipt-secret")
    transport = _FakeTransport(strong_receipt_mode="malformed")

    result = _execute(transport, authorization=authorization)

    assert result.status == "BLOCKED_ON_TRANSPORT_RECEIPT"
    assert result.reason_codes == ("STRONG_EXECUTION_RECEIPT_MALFORMED",)
    assert result.transport_calls == 2
    assert result.golden_reads == 0
    assert result.sealed_experiment is None
    assert authorization.get_secret_value() not in repr(result)
    assert "CanonicalEncodingError" not in repr(result)


def test_execution_never_calls_private_066_validator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(**_kwargs: object) -> object:
        raise AssertionError("079 must not call private 066 validator")

    monkeypatch.setattr(ceiling, "_validate_strong_execution_receipt", forbidden)

    result = _execute(_FakeTransport())

    assert result.status == "OUTPUTS_SEALED_FOR_066_SCORING"


def test_drifted_external_receipt_is_blocked_by_public_066_before_golden() -> None:
    execution = _execute(_FakeTransport(strong_receipt_mode="drift"))
    sealed = cast(SealedFairExperimentV1, execution.sealed_experiment)
    loads = 0

    class Loader:
        def load(self) -> bytes:
            nonlocal loads
            loads += 1
            return b"must-not-load"

    result = score_frozen_experiment(
        sealed_experiment=sealed,
        golden_loader=Loader(),
        admitted_parse_artifacts=(),
    )

    assert execution.status == "OUTPUTS_SEALED_FOR_066_SCORING"
    assert result.status == "BLOCKED_ON_FROZEN_EXPERIMENT"
    assert result.golden_reads == loads == 0


@pytest.mark.parametrize(
    ("transport", "expected_calls", "reason"),
    (
        (_FakeTransport(drift_role="strong"), ("weak", "strong"), "STRONG_TRANSPORT_RECEIPT_DRIFT"),
        (_FakeTransport(fail_role="weak"), ("weak",), "WEAK_ARM_EXECUTION_FAILED"),
        (_FakeTransport(fail_role="strong"), ("weak", "strong"), "STRONG_ARM_EXECUTION_FAILED"),
        (_FakeTransport(incomplete_role="weak"), ("weak",), "WEAK_OUTPUT_FIELD_SET_MISMATCH"),
        (
            _FakeTransport(production_strong=True),
            ("weak", "strong"),
            "STRONG_TRANSPORT_RECEIPT_DRIFT",
        ),
    ),
)
def test_receipt_drift_arm_failure_and_incomplete_fields_fail_closed(
    transport: _FakeTransport,
    expected_calls: tuple[str, ...],
    reason: str,
) -> None:
    result = _execute(transport)

    assert tuple(item[0] for item in transport.calls) == expected_calls
    assert result.status != "OUTPUTS_SEALED_FOR_066_SCORING"
    assert reason in result.reason_codes
    assert result.sealed_experiment is None
    assert result.golden_reads == 0


def test_fake_transport_runs_weak_then_strong_and_seals_exact_066_inputs() -> None:
    transport = _FakeTransport()
    authorization = SecretStr("079-test-authorization")

    result = _execute(transport, authorization=authorization)

    assert result.status == "OUTPUTS_SEALED_FOR_066_SCORING"
    assert [item[0] for item in transport.calls] == ["weak", "strong"]
    assert all(item[2] is authorization for item in transport.calls)
    assert all(item.composition == _composition() for item in transport.submissions)
    assert all(len(item.composition.sources) == 3 for item in transport.submissions)
    sealed = cast(SealedFairExperimentV1, result.sealed_experiment)
    assert sealed.fair_rerun_result.pair_receipt_sha256 == sealed.pair_receipt_sha256
    assert sealed.strong_execution_receipt is transport.strong_receipts[0]
    assert sealed.weak_output.arm == sealed.strong_output.arm == "candidate"
    assert vf.verify_arm_output_hash(sealed.weak_output)
    assert vf.verify_arm_output_hash(sealed.strong_output)
    assert sealed.weak_074_output_hash != sealed.weak_output.output_hash
    assert sealed.strong_074_output_hash == sealed.strong_output.output_hash
    assert sealed.strong_execution_receipt.frozen_output_hash == sealed.strong_output.output_hash
    assert sealed.strong_output.identity.semantic_api_base == ceiling.STRONG_EXECUTION_SURFACE
    assert sealed.strong_authority == "UNADMITTED_RAW"
    assert result.golden_reads == 0
    assert repr(authorization) not in repr(sealed)


def test_score_loads_golden_only_after_seal_replay_and_calls_066(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _execute(_FakeTransport())
    sealed = cast(SealedFairExperimentV1, execution.sealed_experiment)
    events: list[str] = []

    class Loader:
        def load(self) -> bytes:
            events.append("golden")
            return b"synthetic-not-real-golden"

    def fake_score(**kwargs: object) -> vf.AdmittedFrozenArmScoreV1:
        output = cast(vf.FrozenArmOutputV1, kwargs["arm_output"])
        if kwargs["golden_596_jsonl_bytes"] == b"":
            return replace(
                _score_for(output),
                status="GOLDEN_INVALID",
                reason_codes=("GOLDEN_596_BYTES_INVALID",),
                field_correctness=(),
                golden_content_digest_sha256=None,
            )
        events.append("score")
        return _score_for(output)

    monkeypatch.setattr(vf, "score_admitted_frozen_arm", fake_score)
    result = score_frozen_experiment(
        sealed_experiment=sealed,
        golden_loader=Loader(),
        admitted_parse_artifacts=(),
    )

    assert events == ["golden", "score", "score"]
    assert result.status == "COMPARED"
    assert result.golden_reads == 1
    assert result.comparison is not None
    assert result.comparison.status == "COMPARED"
    assert result.comparison.strong_model is not None
    assert result.comparison.strong_model.api_base == ceiling.STRONG_EXECUTION_SURFACE


def test_public_066_preflight_exception_is_typed_zero_golden_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    execution = _execute(_FakeTransport())
    sealed = cast(SealedFairExperimentV1, execution.sealed_experiment)
    loads = 0

    class Loader:
        def load(self) -> bytes:
            nonlocal loads
            loads += 1
            return b"must-not-load"

    def explode(**_kwargs: object) -> object:
        raise RuntimeError("066 exception detail must not escape")

    monkeypatch.setattr(ceiling, "compare_596_1_weak_strong_ceiling", explode)

    result = score_frozen_experiment(
        sealed_experiment=sealed,
        golden_loader=Loader(),
        admitted_parse_artifacts=(),
    )

    assert result.status == "BLOCKED_ON_FROZEN_EXPERIMENT"
    assert result.reason_codes == ("PUBLIC_066_PREFLIGHT_FAILED",)
    assert result.golden_reads == loads == 0


@pytest.mark.parametrize("mutation", ("output", "pair", "rerun", "receipt", "seal"))
def test_mutated_or_incomplete_seal_never_loads_golden(
    mutation: str,
) -> None:
    execution = _execute(_FakeTransport())
    sealed = cast(SealedFairExperimentV1, execution.sealed_experiment)
    loads = 0

    class Loader:
        def load(self) -> bytes:
            nonlocal loads
            loads += 1
            return b"must-not-load"

    if mutation == "output":
        value: object = replace(
            sealed,
            weak_output=replace(sealed.weak_output, output_hash="6" * 64),
        )
    elif mutation == "pair":
        value = replace(sealed, pair_receipt_sha256="7" * 64)
    elif mutation == "rerun":
        value = replace(
            sealed,
            fair_rerun_result=replace(
                sealed.fair_rerun_result,
                pair_receipt_sha256="7" * 64,
            ),
        )
    elif mutation == "receipt":
        value = replace(
            sealed,
            strong_execution_receipt=replace(
                sealed.strong_execution_receipt,
                frozen_output_hash="8" * 64,
            ),
        )
    else:
        value = replace(sealed, seal_sha256="9" * 64)

    result = score_frozen_experiment(
        sealed_experiment=value,
        golden_loader=Loader(),
        admitted_parse_artifacts=(),
    )

    assert result.status == "BLOCKED_ON_FROZEN_EXPERIMENT"
    assert result.golden_reads == 0
    assert result.comparison is None
    assert loads == 0
