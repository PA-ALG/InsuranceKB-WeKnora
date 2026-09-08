from __future__ import annotations

import base64
import hashlib
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.model_policy import AdmissionPolicyDenied, ModelIdentity
from insurance_harness.run_admission.g3_models import (
    G3ArtifactRefV1,
    G3AuthorizedMaterialV1,
    G3BoundedAdmissionPlanV1,
    G3CallPlanV1,
    G3ChainManifestV1,
    G3ChainStageV1,
    G3DelegatedStageSignerV1,
    G3DispositionCountsV1,
    G3FailurePolicyV1,
    G3LedgerPolicyV1,
    G3ModelProcessingAuthorizationV1,
    G3ProtocolSeedLockV1,
    G3RequestManifestV1,
    G3RoutingLockV1,
    G3SchemaArtifactV1,
    G3SchemaLockV1,
    G3StageCapsV1,
    G3StageDispatchLockV1,
    G3StageEligibilityLockV1,
    G3StageProvenanceLockV1,
    G3StageRightsLockV1,
    G3TemplateLockV1,
    canonical_g3_hash,
    canonical_json,
    g3_coverage_gap_codes,
)
from insurance_harness.run_admission.models import (
    ResourceCaps,
    canonical_model_identities_hash,
    canonical_model_plan_hash,
)
from insurance_harness.run_admission.profiles.g3_bounded_execution import (
    validate_g3_bounded_plan,
)

H = "0" * 64


def _identity() -> ModelIdentity:
    return ModelIdentity(
        provider="bailian",
        deployment_id="qwen3.5-plus-2026-04-20",
        family="qwen",
        role="classify",
        policy_version="830-g3-bounded-v1",
    )


def _call() -> G3CallPlanV1:
    return G3CallPlanV1(
        call_id="c-001",
        ordinal=0,
        stage="C_CLASSIFY",
        window_id="w-001",
        material_ids=("m-001",),
        input_context_sha256=H,
        endpoint_origin="https://dashscope.aliyuncs.com",
        endpoint_path="/compatible-mode/v1/chat/completions",
        identity=_identity(),
        response_mode="json_object",
        request_body_sha256=H,
        request_bytes=12,
        input_token_estimate=3,
        input_token_ceiling=10,
        output_token_ceiling=20,
        timeout_seconds=30,
    )


def _hashed(model: type[Any], domain: str, field: str, **values: object) -> Any:
    provisional = model(**values, **{field: H})
    return provisional.model_copy(update={field: canonical_g3_hash(domain, provisional, field)})


def valid_c_plan(*, call_count: int = 1) -> G3BoundedAdmissionPlanV1:
    identity = _identity()
    calls = tuple(
        _call().model_copy(
            update={
                "call_id": f"c-{ordinal + 1:03d}",
                "ordinal": ordinal,
                "window_id": f"w-{ordinal + 1:03d}",
                "material_ids": (f"m-{ordinal + 1:03d}",),
                "request_body_sha256": str(ordinal + 1) * 64,
            }
        )
        for ordinal in range(call_count)
    )
    manifest = _hashed(
        G3RequestManifestV1,
        "g3-request-manifest.830.v1",
        "manifest_hash",
        contract="g3-request-manifest.830.v1",
        stage="C_CLASSIFY",
        chain_id="chain-1",
        calls=calls,
    )
    failure = G3FailurePolicyV1(
        policy_version="g3-chain-failure-policy.830.v1",
        retry_limit=0,
        worker_limit=1,
        incomplete_reservation_action="PERMANENTLY_CONSUME_AND_STOP_STAGE",
        started_without_terminal_action="PERMANENT_OUTCOME_UNKNOWN_STOP_CHAIN",
        call_failure_action="STOP_CHAIN",
        c_execution_failure_action="STOP_BEFORE_RESOLVE",
        c_coverage_gap_action="MARK_DOD_GAP_CONTINUE_ELIGIBLE_AUTOMATIC_CHILDREN",
        d_compile_failure_action="STOP_BEFORE_REVIEW",
        d_review_failure_action="STOP_BEFORE_CANDIDATE",
    )
    ledger = G3LedgerPolicyV1(
        protocol_version="g3-cross-process-ledger.830.v1",
        root_path="/var/lib/insurancekb/g3-bounded-execution-ledger/v1",
        owner_rule="LEAF_OWNER_EQUALS_EFFECTIVE_SERVICE_UID",
        root_mode="0700",
        stage_binding_mode="ONE_ADMISSION_DIGEST_PER_CHAIN_STAGE_O_EXCL",
        call_reservation_mode="ATOMIC_MKDIR_AND_O_EXCL_RECORD",
        duplicate_action="DENY_HTTP_ZERO",
        malformed_ledger_action="PERMANENTLY_CONSUME_AND_DENY_HTTP_ZERO",
    )
    c_input = sum(call.input_token_ceiling for call in calls)
    c_output = sum(call.output_token_ceiling for call in calls)
    c_time = sum(call.timeout_seconds for call in calls)
    stages = (
        G3ChainStageV1(
            stage="C_CLASSIFY",
            purpose="g3-batch-resolution",
            run_schema_version="830-g3-v1",
            role="classify",
            max_calls=call_count,
            input_token_ceiling=c_input,
            output_token_ceiling=c_output,
            time_limit_seconds=c_time,
        ),
        G3ChainStageV1(
            stage="D_COMPILE",
            purpose="g3-batch-concept-compile",
            run_schema_version="830-g3-d-compile-v1",
            role="extract",
            max_calls=1,
            input_token_ceiling=10,
            output_token_ceiling=20,
            time_limit_seconds=30,
        ),
        G3ChainStageV1(
            stage="D_REVIEW",
            purpose="g3-batch-concept-review",
            run_schema_version="830-g3-d-review-v1",
            role="verify",
            max_calls=1,
            input_token_ceiling=10,
            output_token_ceiling=20,
            time_limit_seconds=30,
        ),
    )
    chain = _hashed(
        G3ChainManifestV1,
        "g3-bounded-chain.830.v1",
        "chain_manifest_hash",
        contract="g3-bounded-chain.830.v1",
        chain_id="chain-1",
        clean_integration_sha="a" * 40,
        stages=stages,
        max_calls=call_count + 2,
        total_input_token_ceiling=c_input + 20,
        total_output_token_ceiling=c_output + 40,
        total_time_limit_seconds=c_time + 60,
        retry_limit=0,
        worker_limit=1,
        derivation_rules_version="g3-c-to-d-derivation.830.v1",
        prompt_render_rules_version="g3-prompt-render.830.v1",
        schema_derivation_version="g3-schema-derivation.830.v1",
        failure_policy=failure,
        ledger_policy=ledger,
    )
    request_refs = tuple(
        G3ArtifactRefV1(
            contract="g3-http-request-body.830.v1",
            artifact_ref=(
                "/var/lib/insurancekb/run-admission/sha256/"
                f"{call.request_body_sha256}/request-body.json"
            ),
            sha256=call.request_body_sha256,
            bytes=call.request_bytes,
        )
        for call in calls
    )
    eligibility = _hashed(
        G3StageEligibilityLockV1,
        "g3-stage-eligibility.830.v1",
        "eligibility_hash",
        contract="g3-stage-eligibility.830.v1",
        stage="C_CLASSIFY",
        input_artifacts=request_refs,
        checks=(),
        eligible_subject_ids=tuple(call.material_ids[0] for call in calls),
    )
    seed = _hashed(
        G3ProtocolSeedLockV1,
        "g3-protocol-seed.830.v1",
        "golden_slice_hash",
        contract="g3-protocol-seed.830.v1",
        seed_artifact=G3ArtifactRefV1(
            contract="g3-protocol-seed-data.830.v1",
            artifact_ref="/var/lib/insurancekb/run-admission/sha256/" + "e" * 64 + "/seed.json",
            sha256="e" * 64,
            bytes=1,
        ),
        denominator_material_ids=tuple(call.material_ids[0] for call in calls),
        expected_coverage_codes=("CREATE", "MATCH", "MULTI", "NEEDS_CONFIRM", "QUARANTINE"),
        quality_authority=False,
    )
    schema = _hashed(
        G3SchemaLockV1,
        "g3-stage-schema-set.830.v1",
        "schema_hash",
        contract="g3-stage-schema-set.830.v1",
        artifacts=(
            G3SchemaArtifactV1(
                stage="C_CLASSIFY",
                direction="response",
                enforcing_module="harness/src/insurance_harness/run_admission/g3_models.py",
                enforcing_module_sha256="f" * 64,
                canonical_schema_sha256="d" * 64,
            ),
        ),
    )
    template_values = {
        "contract": "g3-stage-template-lock.830.v1",
        "stage": "C_CLASSIFY",
        "path": "harness/src/insurance_harness/knowledge_compiler/prompts/g3_c_classify_v1.txt",
        "raw_sha256": "b" * 64,
        "prompt_version": "g3-c-classify-v1",
        "render_rules_version": "g3-prompt-render.830.v1",
    }
    approved_template = hashlib.sha256(
        b"g3-approved-template.830.v1\0" + canonical_json(template_values)
    ).hexdigest()
    template = _hashed(
        G3TemplateLockV1,
        "g3-stage-template-lock.830.v1",
        "template_lock_hash",
        **template_values,
        approved_template_hash=approved_template,
    )
    routing = _hashed(
        G3RoutingLockV1,
        "g3-stage-routing.830.v1",
        "routing_policy_hash",
        contract="g3-stage-routing.830.v1",
        stage="C_CLASSIFY",
        purpose="g3-batch-resolution",
        run_schema_version="830-g3-v1",
        role="classify",
        identity=identity,
        endpoint_origin="https://dashscope.aliyuncs.com",
        endpoint_path="/compatible-mode/v1/chat/completions",
        temperature_micros=0,
        thinking=False,
        response_format="json_object",
        timeout_seconds=30,
        follow_redirects=False,
        fallback_limit=0,
        retry_limit=0,
        template_hash=approved_template,
        schema_hash=schema.schema_hash,
    )
    dispatch = _hashed(
        G3StageDispatchLockV1,
        "g3-stage-dispatch.830.v1",
        "structured_dispatch_hash",
        contract="g3-stage-dispatch.830.v1",
        stage="C_CLASSIFY",
        calls=calls,
        opaque_block_map_sha256="c" * 64,
        input_context_sha256=H,
        schema_hash=schema.schema_hash,
        template_hash=approved_template,
    )
    caps = _hashed(
        G3StageCapsV1,
        "g3-stage-caps.830.v1",
        "caps_sha256",
        contract="g3-stage-caps.830.v1",
        stage="C_CLASSIFY",
        worker_limit=1,
        call_limit=call_count,
        attempts_per_call=1,
        retry_limit=0,
        input_token_ceiling=c_input,
        output_token_ceiling=c_output,
        time_limit_seconds=c_time,
    )
    parent_digest = "9" * 64
    expiry = datetime.now(UTC) + timedelta(hours=1)
    rights = _hashed(
        G3StageRightsLockV1,
        "g3-external-send-rights.830.v1",
        "rights_hash",
        contract="g3-external-send-rights.830.v1",
        parent_authorization_digest=parent_digest,
        stage="C_CLASSIFY",
        purpose="g3-batch-resolution",
        run_schema_version="830-g3-v1",
        role="classify",
        provider=identity.provider,
        endpoint_origin="https://dashscope.aliyuncs.com",
        endpoint_path="/compatible-mode/v1/chat/completions",
        deployment_id=identity.deployment_id,
        call_ids=tuple(call.call_id for call in calls),
        window_ids=tuple(call.window_id for call in calls if call.window_id is not None),
        artifacts=request_refs,
        material_or_derivation_ids=tuple(call.material_ids[0] for call in calls),
        data_categories=("C_W1_SOURCE",),
        call_limit=call_count,
        input_token_ceiling=c_input,
        output_token_ceiling=c_output,
        time_limit_seconds=c_time,
        expires_at=expiry,
        retry_limit=0,
    )
    provenance = _hashed(
        G3StageProvenanceLockV1,
        "g3-stage-provenance.830.v1",
        "provenance_hash",
        contract="g3-stage-provenance.830.v1",
        stage="C_CLASSIFY",
        artifacts=request_refs,
        prior_terminal_receipt_sha256=None,
    )
    resource = ResourceCaps(
        worker_limit=1,
        attempt_limit=call_count,
        time_limit_seconds=c_time,
        token_limit=c_input + c_output,
    )
    return validate_g3_bounded_plan(
        G3BoundedAdmissionPlanV1(
            contract="g3-bounded-admission-plan.830.v1",
            stage="C_CLASSIFY",
            purpose="g3-batch-resolution",
            run_schema_version="830-g3-v1",
            run_id="run-1",
            run_revision="rev-1",
            space_id="space-1",
            chain_id="chain-1",
            chain_manifest=chain,
            chain_manifest_hash=chain.chain_manifest_hash,
            parent_authorization_digest=parent_digest,
            prior_terminal_receipt_sha256=None,
            derived_stage_receipt=None,
            request_manifest=manifest,
            manifest_hash=manifest.manifest_hash,
            eligibility_lock=eligibility,
            eligibility_hash=eligibility.eligibility_hash,
            protocol_seed_lock=seed,
            golden_slice_hash=seed.golden_slice_hash,
            routing_lock=routing,
            routing_policy_hash=routing.routing_policy_hash,
            schema_lock=schema,
            schema_hash=schema.schema_hash,
            template_lock=template,
            template_lock_hash=template.template_lock_hash,
            approved_template_hashes=(approved_template,),
            dispatch_lock=dispatch,
            structured_dispatch_hash=dispatch.structured_dispatch_hash,
            approved_identities=(identity,),
            model_plan_hash=canonical_model_plan_hash((identity,)),
            deployment_roles_hash=canonical_model_identities_hash((identity,)),
            stage_caps=caps,
            resource_caps=resource,
            resource_caps_hash=resource.digest,
            rights_lock=rights,
            rights_hash=rights.rights_hash,
            provenance_lock=provenance,
            provenance_hash=provenance.provenance_hash,
            clean_integration_sha="a" * 40,
            expires_at=expiry,
        )
    )


def test_request_manifest_hash_is_exact_and_tamper_evident() -> None:
    provisional = G3RequestManifestV1(
        contract="g3-request-manifest.830.v1",
        stage="C_CLASSIFY",
        chain_id="chain-1",
        calls=(_call(),),
        manifest_hash=H,
    )
    digest = canonical_g3_hash("g3-request-manifest.830.v1", provisional, "manifest_hash")
    manifest = provisional.model_copy(update={"manifest_hash": digest})
    assert manifest.manifest_hash == canonical_g3_hash(
        "g3-request-manifest.830.v1", manifest, "manifest_hash"
    )
    tampered_call = _call().model_copy(update={"request_bytes": 13})
    with pytest.raises(ValidationError, match="manifest_hash mismatch"):
        manifest.model_copy(update={"calls": (tampered_call,)})


def test_complete_plan_closes_every_mandatory_hash_and_projection() -> None:
    plan = valid_c_plan(call_count=2)
    assert plan.manifest_hash == canonical_g3_hash(
        "g3-request-manifest.830.v1", plan.request_manifest, "manifest_hash"
    )
    with pytest.raises(ValueError, match="rights_hash mismatch"):
        validate_g3_bounded_plan(
            plan.model_copy(
                update={
                    "rights_lock": plan.rights_lock.model_copy(
                        update={"input_token_ceiling": plan.rights_lock.input_token_ceiling + 1}
                    )
                }
            )
        )


def test_request_body_rerender_is_byte_exact_and_model_bound() -> None:
    from insurance_harness.compiler.llm import openai_compat_request_bytes
    from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
        g3_openai_request_bytes,
    )
    from insurance_harness.run_admission.evaluator import _rerender_g3_request

    plan = valid_c_plan()
    call = plan.request_manifest.calls[0]
    body = g3_openai_request_bytes(
        plan=plan,
        call=call,
        system="system fixture",
        user="user fixture",
    )
    rerendered = _rerender_g3_request(
        body, plan, call, system="system fixture", user="user fixture"
    )
    assert b'"enable_thinking":false' in rerendered
    assert b'"thinking"' not in rerendered
    with pytest.raises(AdmissionPolicyDenied):
        _rerender_g3_request(
            body, plan, call, system="system fixture", user="unauthorized extra text"
        )
    legacy = openai_compat_request_bytes(
        model=call.identity.deployment_id,
        temperature=0.0,
        max_tokens=20,
        system="system fixture",
        user="user fixture",
        thinking="disabled",
        response_format="json_object",
    )
    with pytest.raises(AdmissionPolicyDenied):
        _rerender_g3_request(
            legacy, plan, call, system="system fixture", user="user fixture"
        )
    tampered = body.replace(
        plan.approved_identities[0].deployment_id.encode(), b"qwen3.5-plus-2026-04-21"
    )
    with pytest.raises(AdmissionPolicyDenied):
        _rerender_g3_request(
            tampered, plan, call, system="system fixture", user="user fixture"
        )


def test_strict_dto_rejects_extra_bool_integer_and_noncanonical_tuple() -> None:
    with pytest.raises(ValidationError):
        G3CallPlanV1.model_validate({**_call().model_dump(), "request_bytes": True})
    with pytest.raises(ValidationError):
        G3CallPlanV1.model_validate({**_call().model_dump(), "unexpected": "x"})
    with pytest.raises(ValidationError):
        G3CallPlanV1.model_validate({**_call().model_dump(), "material_ids": ("z", "a")})


def test_zero_disposition_marks_dod_gap_without_discarding_results() -> None:
    counts = G3DispositionCountsV1(MATCH=2, CREATE=1, MULTI=0, NEEDS_CONFIRM=1, QUARANTINE=0)
    assert g3_coverage_gap_codes(counts) == (
        "G3_DOD_COVERAGE_GAP:MULTI",
        "G3_DOD_COVERAGE_GAP:QUARANTINE",
    )


def test_g3_native_projection_reader_accepts_exact_artifact_above_32_mib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from insurance_harness.run_admission import evaluator, trust_policy

    store = tmp_path / "run-admission"
    store.mkdir(mode=0o700)
    payload = b"n" * (32 * 1024 * 1024 + 1)
    digest = hashlib.sha256(payload).hexdigest()
    directory = store / "sha256" / digest
    directory.mkdir(parents=True, mode=0o700)
    path = directory / "g3-native-page-projections.json"
    path.write_bytes(payload)
    path.chmod(0o600)
    ref = G3ArtifactRefV1(
        contract="g3-native-page-projections.830.v1",
        artifact_ref=str(path),
        sha256=digest,
        bytes=len(payload),
    )
    monkeypatch.setattr(evaluator, "_ADMISSION_STORE_ROOT", store)
    monkeypatch.setattr(trust_policy, "_ROOT_OWNER_UID", os.geteuid())

    assert evaluator._read_g3_artifact(ref) == payload


def test_g3_artifact_reader_keeps_other_limits_hash_and_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from insurance_harness.run_admission import evaluator, trust_policy

    store = tmp_path / "run-admission"
    store.mkdir(mode=0o700)
    monkeypatch.setattr(evaluator, "_ADMISSION_STORE_ROOT", store)
    monkeypatch.setattr(trust_policy, "_ROOT_OWNER_UID", os.geteuid())

    def sparse_ref(*, contract: str, size: int, mode: int = 0o600) -> G3ArtifactRefV1:
        digest = "a" * 64
        directory = store / "sha256" / digest
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        path = directory / (contract + ".json")
        with path.open("wb") as handle:
            handle.truncate(size)
        path.chmod(mode)
        return G3ArtifactRefV1(
            contract=contract,
            artifact_ref=str(path),
            sha256=digest,
            bytes=size,
        )

    with pytest.raises(AdmissionPolicyDenied):
        evaluator._read_g3_artifact(
            sparse_ref(
                contract="g3-native-page-projections.830.v1",
                size=64 * 1024 * 1024 + 1,
            )
        )
    with pytest.raises(AdmissionPolicyDenied):
        evaluator._read_g3_artifact(
            sparse_ref(contract="batch-corpus.830.g3.v1", size=32 * 1024 * 1024 + 1)
        )

    payload = b"exact"
    digest = hashlib.sha256(payload).hexdigest()
    directory = store / "sha256" / digest
    directory.mkdir(parents=True, mode=0o700)
    path = directory / "exact.json"
    path.write_bytes(payload)
    path.chmod(0o600)
    valid = G3ArtifactRefV1(
        contract="g3-native-page-projections.830.v1",
        artifact_ref=str(path),
        sha256=digest,
        bytes=len(payload),
    )
    with pytest.raises(AdmissionPolicyDenied):
        evaluator._read_g3_artifact(valid.model_copy(update={"bytes": len(payload) + 1}))
    path.write_bytes(b"other")
    path.chmod(0o600)
    with pytest.raises(AdmissionPolicyDenied):
        evaluator._read_g3_artifact(valid)
    path.write_bytes(payload)
    path.chmod(0o622)
    with pytest.raises(AdmissionPolicyDenied):
        evaluator._read_g3_artifact(valid)


def test_d_rejects_native_projection_contract_before_any_artifact_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from insurance_harness.run_admission import evaluator

    base = valid_c_plan()
    public = bytes(32)
    parent = G3ModelProcessingAuthorizationV1(
        contract="g3-model-processing-authorization.830.v1",
        authorization_id="capacity-test",
        chain_manifest=base.chain_manifest,
        chain_manifest_hash=base.chain_manifest_hash,
        space_id=base.space_id,
        provider=base.approved_identities[0].provider,
        endpoint_origin=base.routing_lock.endpoint_origin,
        deployment_id=base.approved_identities[0].deployment_id,
        family=base.approved_identities[0].family,
        policy_version=base.approved_identities[0].policy_version,
        c_materials=(
            G3AuthorizedMaterialV1(
                material_id="m-001",
                corpus_entry_sha256=H,
                source_revision_receipt_sha256=H,
                w1_sha256=H,
                native_page_map_sha256=H,
            ),
        ),
        c_request_manifest_hash=base.manifest_hash,
        c_prompt_preview_sha256=H,
        allowed_stages=("C_CLASSIFY", "D_COMPILE", "D_REVIEW"),
        allowed_roles=("classify", "extract", "verify"),
        allowed_derived_data_categories=tuple(
            sorted(
                (
                    "C_W1_SOURCE",
                    "C_CATALOG_POLICY_SNAPSHOT",
                    "C_EXISTING_ENTITY_SNAPSHOT",
                    "D_AUTOMATIC_CHILD_SOURCE_CLOSURE",
                    "D_CATALOG_PROFILE_BASE",
                    "D_COMPOSED_CANDIDATE_REVIEW_CONTEXT",
                )
            )
        ),
        derivation_rules_version="g3-c-to-d-derivation.830.v1",
        max_calls=base.chain_manifest.max_calls,
        total_input_token_ceiling=base.chain_manifest.total_input_token_ceiling,
        total_output_token_ceiling=base.chain_manifest.total_output_token_ceiling,
        total_time_limit_seconds=base.chain_manifest.total_time_limit_seconds,
        retry_limit=0,
        worker_limit=1,
        delegated_stage_signer=G3DelegatedStageSignerV1(
            key_id="capacity-stage",
            algorithm="Ed25519",
            public_key_b64=base64.b64encode(public).decode(),
            public_key_fingerprint=hashlib.sha256(public).hexdigest(),
        ),
        expires_at=base.expires_at,
    )
    native_ref = G3ArtifactRefV1(
        contract="g3-native-page-projections.830.v1",
        artifact_ref=(
            "/var/lib/insurancekb/run-admission/sha256/" + "b" * 64 + "/native.json"
        ),
        sha256="b" * 64,
        bytes=32 * 1024 * 1024 + 1,
    )
    eligibility = base.eligibility_lock.model_construct(
        **{
            **base.eligibility_lock.model_dump(mode="python"),
            "stage": "D_COMPILE",
            "input_artifacts": (native_ref,),
        }
    )
    plan = G3BoundedAdmissionPlanV1.model_construct(
        **{
            **base.model_dump(mode="python"),
            "stage": "D_COMPILE",
            "eligibility_lock": eligibility,
        }
    )
    reads = 0

    def forbidden_read(_ref: G3ArtifactRefV1) -> bytes:
        nonlocal reads
        reads += 1
        raise AssertionError("D native contract reached artifact reader")

    monkeypatch.setattr(evaluator, "_clean_repository_sha", lambda: base.clean_integration_sha)
    monkeypatch.setattr(evaluator, "_read_g3_artifact", forbidden_read)
    with pytest.raises(AdmissionPolicyDenied):
        evaluator._verify_g3_current_content(plan, parent)
    assert reads == 0
