"""Closed validator for the three G3 bounded execution stages."""

from __future__ import annotations

import re

from insurance_harness.run_admission.models import (
    canonical_model_identities_hash,
    canonical_model_plan_hash,
)

from ..g3_models import (
    G3BoundedAdmissionPlanV1,
    G3ModelProcessingAuthorizationV1,
    canonical_g3_hash,
    canonical_json,
)

G3_STAGE_PROFILES = {
    "C_CLASSIFY": ("g3-batch-resolution", "830-g3-v1", "classify"),
    "D_COMPILE": ("g3-batch-concept-compile", "830-g3-d-compile-v1", "extract"),
    "D_REVIEW": ("g3-batch-concept-review", "830-g3-d-review-v1", "verify"),
}


def _is_supported_g3_route(plan: G3BoundedAdmissionPlanV1) -> bool:
    identity = plan.routing_lock.identity
    route = (plan.routing_lock.endpoint_origin, plan.routing_lock.endpoint_path)
    if identity.provider == "bailian" and identity.family == "qwen":
        return route == (
            "https://dashscope.aliyuncs.com",
            "/compatible-mode/v1/chat/completions",
        )
    return (
        identity.provider,
        identity.family,
        identity.deployment_id,
        identity.policy_version,
        identity.role,
        plan.routing_lock.thinking,
        route,
    ) == (
        "g3-user-gateway",
        "gemini",
        "gemini-3.7-flash-medium",
        "g3-user-gemini-gateway-v1",
        G3_STAGE_PROFILES[plan.stage][2],
        True,
        ("http://8.148.158.241:3131", "/v1/chat/completions"),
    )


def _is_windowed_gemini_d(plan: G3BoundedAdmissionPlanV1) -> bool:
    identity = plan.approved_identities[0]
    expected_role = {
        "D_COMPILE": "extract",
        "D_REVIEW": "verify",
    }.get(plan.stage)
    exact_identity = expected_role is not None and (
        identity.provider,
        identity.family,
        identity.deployment_id,
        identity.policy_version,
        identity.role,
    ) == (
        "g3-user-gateway",
        "gemini",
        "gemini-3.7-flash-medium",
        "g3-user-gemini-gateway-v1",
        expected_role,
    )
    return exact_identity and all(
        call.window_id is not None
        and re.fullmatch(r"window_[0-9a-f]{64}", call.window_id) is not None
        and bool(call.material_ids)
        for call in plan.request_manifest.calls
    )


def validate_g3_bounded_plan(plan: G3BoundedAdmissionPlanV1) -> G3BoundedAdmissionPlanV1:
    try:
        current = G3BoundedAdmissionPlanV1.model_validate(
            plan.model_dump(mode="python", round_trip=True, warnings=False)
        )
        purpose, schema, role = G3_STAGE_PROFILES[current.stage]
        if (current.purpose, current.run_schema_version) != (purpose, schema):
            raise ValueError("stage profile mismatch")
        if len(current.approved_identities) != 1 or current.approved_identities[0].role != role:
            raise ValueError("stage identity mismatch")
        if current.request_manifest.stage != current.stage:
            raise ValueError("request stage mismatch")
        if (
            current.chain_id != current.chain_manifest.chain_id
            or current.chain_id != current.request_manifest.chain_id
            or current.clean_integration_sha != current.chain_manifest.clean_integration_sha
            or current.eligibility_lock.stage != current.stage
            or current.routing_lock.stage != current.stage
            or current.template_lock.stage != current.stage
            or current.dispatch_lock.stage != current.stage
            or current.stage_caps.stage != current.stage
            or current.rights_lock.stage != current.stage
            or current.provenance_lock.stage != current.stage
        ):
            raise ValueError("stage identity projection mismatch")
        if current.manifest_hash != current.request_manifest.manifest_hash:
            raise ValueError("manifest projection mismatch")
        if current.manifest_hash != canonical_g3_hash(
            "g3-request-manifest.830.v1", current.request_manifest, "manifest_hash"
        ):
            raise ValueError("manifest hash mismatch")
        hash_checks = (
            (
                current.chain_manifest_hash,
                canonical_g3_hash(
                    "g3-bounded-chain.830.v1",
                    current.chain_manifest,
                    "chain_manifest_hash",
                ),
            ),
            (
                current.eligibility_hash,
                canonical_g3_hash(
                    "g3-stage-eligibility.830.v1",
                    current.eligibility_lock,
                    "eligibility_hash",
                ),
            ),
            (
                current.golden_slice_hash,
                canonical_g3_hash(
                    "g3-protocol-seed.830.v1",
                    current.protocol_seed_lock,
                    "golden_slice_hash",
                ),
            ),
            (
                current.routing_policy_hash,
                canonical_g3_hash(
                    "g3-stage-routing.830.v1",
                    current.routing_lock,
                    "routing_policy_hash",
                ),
            ),
            (
                current.schema_hash,
                canonical_g3_hash(
                    "g3-stage-schema-set.830.v1",
                    current.schema_lock,
                    "schema_hash",
                ),
            ),
            (
                current.template_lock_hash,
                canonical_g3_hash(
                    "g3-stage-template-lock.830.v1",
                    current.template_lock,
                    "template_lock_hash",
                ),
            ),
            (
                current.structured_dispatch_hash,
                canonical_g3_hash(
                    "g3-stage-dispatch.830.v1",
                    current.dispatch_lock,
                    "structured_dispatch_hash",
                ),
            ),
            (
                current.stage_caps.caps_sha256,
                canonical_g3_hash("g3-stage-caps.830.v1", current.stage_caps, "caps_sha256"),
            ),
            (
                current.rights_hash,
                canonical_g3_hash(
                    "g3-external-send-rights.830.v1",
                    current.rights_lock,
                    "rights_hash",
                ),
            ),
            (
                current.provenance_hash,
                canonical_g3_hash(
                    "g3-stage-provenance.830.v1",
                    current.provenance_lock,
                    "provenance_hash",
                ),
            ),
        )
        if any(actual != expected for actual, expected in hash_checks):
            raise ValueError("mandatory G3 hash mismatch")
        approved_template = {
            key: value
            for key, value in current.template_lock.model_dump(mode="json").items()
            if key
            in {
                "contract",
                "stage",
                "path",
                "raw_sha256",
                "prompt_version",
                "render_rules_version",
            }
        }
        import hashlib

        expected_approved_template_hash = hashlib.sha256(
            b"g3-approved-template.830.v1\0" + canonical_json(approved_template)
        ).hexdigest()
        if current.template_lock.approved_template_hash != expected_approved_template_hash:
            raise ValueError("approved template hash mismatch")
        pairs = (
            (current.chain_manifest_hash, current.chain_manifest.chain_manifest_hash),
            (current.eligibility_hash, current.eligibility_lock.eligibility_hash),
            (current.golden_slice_hash, current.protocol_seed_lock.golden_slice_hash),
            (current.routing_policy_hash, current.routing_lock.routing_policy_hash),
            (current.schema_hash, current.schema_lock.schema_hash),
            (current.template_lock_hash, current.template_lock.template_lock_hash),
            (current.structured_dispatch_hash, current.dispatch_lock.structured_dispatch_hash),
            (current.rights_hash, current.rights_lock.rights_hash),
            (current.provenance_hash, current.provenance_lock.provenance_hash),
        )
        if any(left != right for left, right in pairs):
            raise ValueError("lock projection mismatch")
        if current.approved_template_hashes != (current.template_lock.approved_template_hash,):
            raise ValueError("template approval mismatch")
        if current.model_plan_hash != canonical_model_plan_hash(current.approved_identities):
            raise ValueError("model plan mismatch")
        if current.deployment_roles_hash != canonical_model_identities_hash(
            current.approved_identities
        ):
            raise ValueError("deployment roles mismatch")
        if current.resource_caps_hash != current.resource_caps.digest:
            raise ValueError("resource caps mismatch")
        expected_resource = (
            current.chain_manifest.worker_limit,
            len(current.request_manifest.calls),
            sum(call.timeout_seconds for call in current.request_manifest.calls),
            sum(
                call.input_token_ceiling + call.output_token_ceiling
                for call in current.request_manifest.calls
            ),
        )
        if (
            current.resource_caps.worker_limit,
            current.resource_caps.attempt_limit,
            current.resource_caps.time_limit_seconds,
            current.resource_caps.token_limit,
        ) != expected_resource:
            raise ValueError("resource caps projection mismatch")
        if (
            current.stage_caps.worker_limit != current.chain_manifest.worker_limit
            or current.chain_manifest.failure_policy.worker_limit
            != current.chain_manifest.worker_limit
        ):
            raise ValueError("worker policy projection mismatch")
        calls = current.request_manifest.calls
        if current.stage == "C_CLASSIFY":
            if (
                current.prior_terminal_receipt_sha256 is not None
                or current.derived_stage_receipt is not None
            ):
                raise ValueError("C cannot have prior receipt")
        elif (
            current.prior_terminal_receipt_sha256 is None
            or current.derived_stage_receipt is None
            or current.derived_stage_receipt.prior_terminal_receipt_sha256
            != current.prior_terminal_receipt_sha256
            or current.derived_stage_receipt.derived_request_manifest_hash != current.manifest_hash
        ):
            raise ValueError("D requires exact prior derivation")
        if current.derived_stage_receipt is not None:
            if current.derived_stage_receipt.receipt_sha256 != canonical_g3_hash(
                "g3-derived-stage-receipt.830.v1",
                current.derived_stage_receipt,
                "receipt_sha256",
            ):
                raise ValueError("derived stage receipt hash mismatch")
        windowed_gemini_d = _is_windowed_gemini_d(current)
        if current.stage != "C_CLASSIFY" and not windowed_gemini_d and len(calls) != 1:
            raise ValueError("D stages require exactly one call")
        if windowed_gemini_d and any(
            call.window_id is None
            or re.fullmatch(r"window_[0-9a-f]{64}", call.window_id) is None
            or not call.material_ids
            for call in calls
        ):
            raise ValueError("Gemini D windowed call shape mismatch")
        if current.stage_caps.call_limit != len(calls):
            raise ValueError("stage call cap mismatch")
        chain_rows = tuple(
            row for row in current.chain_manifest.stages if row.stage == current.stage
        )
        if len(chain_rows) != 1:
            raise ValueError("stage is absent from chain manifest")
        chain_row = chain_rows[0]
        actual_input = sum(call.input_token_ceiling for call in calls)
        actual_output = sum(call.output_token_ceiling for call in calls)
        actual_time = sum(call.timeout_seconds for call in calls)
        chain_identity = (
            chain_row.purpose,
            chain_row.run_schema_version,
            chain_row.role,
        )
        if chain_identity != (
            current.purpose,
            current.run_schema_version,
            role,
        ):
            raise ValueError("chain stage projection mismatch")
        actual_caps = (len(calls), actual_input, actual_output, actual_time)
        chain_caps = (
            chain_row.max_calls,
            chain_row.input_token_ceiling,
            chain_row.output_token_ceiling,
            chain_row.time_limit_seconds,
        )
        if (
            any(actual > capacity for actual, capacity in zip(actual_caps, chain_caps, strict=True))
            if windowed_gemini_d
            else actual_caps != chain_caps
        ):
            raise ValueError("chain stage projection mismatch")
        if (
            current.stage_caps.input_token_ceiling != actual_input
            or current.stage_caps.output_token_ceiling != actual_output
            or current.stage_caps.time_limit_seconds != actual_time
            or current.rights_lock.parent_authorization_digest
            != current.parent_authorization_digest
            or current.rights_lock.stage != current.stage
            or current.rights_lock.call_ids != tuple(sorted(call.call_id for call in calls))
            or current.rights_lock.window_ids
            != tuple(sorted(call.window_id for call in calls if call.window_id is not None))
            or current.rights_lock.call_limit != len(calls)
            or current.rights_lock.input_token_ceiling != actual_input
            or current.rights_lock.output_token_ceiling != actual_output
            or current.rights_lock.time_limit_seconds != actual_time
            or current.rights_lock.purpose != current.purpose
            or current.rights_lock.run_schema_version != current.run_schema_version
            or current.rights_lock.role != role
            or current.rights_lock.provider != current.approved_identities[0].provider
            or current.rights_lock.deployment_id != current.approved_identities[0].deployment_id
            or current.rights_lock.endpoint_origin != current.routing_lock.endpoint_origin
            or current.rights_lock.endpoint_path != current.routing_lock.endpoint_path
            or current.rights_lock.expires_at != current.expires_at
            or current.provenance_lock.stage != current.stage
            or current.provenance_lock.prior_terminal_receipt_sha256
            != current.prior_terminal_receipt_sha256
        ):
            raise ValueError("stage rights/provenance projection mismatch")
        if windowed_gemini_d and current.rights_lock.material_or_derivation_ids != tuple(
            sorted(
                {
                    material_id
                    for call in calls
                    for material_id in call.material_ids
                }
            )
        ):
            raise ValueError("Gemini D material rights mismatch")
        if (
            current.routing_lock.stage != current.stage
            or current.routing_lock.purpose != current.purpose
            or current.routing_lock.run_schema_version != current.run_schema_version
            or current.routing_lock.role != role
            or current.routing_lock.identity != current.approved_identities[0]
            or current.routing_lock.template_hash != current.template_lock.approved_template_hash
            or current.routing_lock.schema_hash != current.schema_hash
            or current.routing_lock.response_format != "json_object"
            or not _is_supported_g3_route(current)
            or any(
                call.identity != current.routing_lock.identity
                or call.endpoint_origin != current.routing_lock.endpoint_origin
                or call.endpoint_path != current.routing_lock.endpoint_path
                or call.response_mode != current.routing_lock.response_format
                or call.timeout_seconds != current.routing_lock.timeout_seconds
                for call in calls
            )
            or current.dispatch_lock.calls != calls
            or current.dispatch_lock.schema_hash != current.schema_hash
            or current.dispatch_lock.template_hash != current.template_lock.approved_template_hash
        ):
            raise ValueError("stage routing/dispatch mismatch")
        if current.stage == "C_CLASSIFY" and current.dispatch_lock.opaque_block_map_sha256 is None:
            raise ValueError("C requires opaque block map")
        if (
            current.stage != "C_CLASSIFY"
            and current.dispatch_lock.opaque_block_map_sha256 is not None
        ):
            raise ValueError("D cannot carry opaque block map")
        request_refs = tuple(
            ref
            for ref in current.eligibility_lock.input_artifacts
            if ref.contract == "g3-http-request-body.830.v1"
        )
        if not (
            request_refs
            == tuple(
                ref
                for ref in current.provenance_lock.artifacts
                if ref.contract == "g3-http-request-body.830.v1"
            )
            == tuple(
                ref
                for ref in current.rights_lock.artifacts
                if ref.contract == "g3-http-request-body.830.v1"
            )
        ) or tuple(sorted((ref.sha256, ref.bytes) for ref in request_refs)) != tuple(sorted(
            (call.request_body_sha256, call.request_bytes) for call in calls
        )):
            raise ValueError("request artifact projection mismatch")
        return current
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ValueError("invalid G3 bounded admission plan") from None


def validate_g3_parent_scope(
    parent: G3ModelProcessingAuthorizationV1,
    plan: G3BoundedAdmissionPlanV1,
) -> None:
    """Prove that one fully formed stage plan is inside the signed parent scope."""

    current = validate_g3_bounded_plan(plan)
    identity = current.approved_identities[0]
    if (
        parent.chain_manifest != current.chain_manifest
        or parent.chain_manifest_hash != current.chain_manifest_hash
        or parent.space_id != current.space_id
        or current.expires_at > parent.expires_at
        or current.rights_lock.expires_at > parent.expires_at
        or parent.provider != identity.provider
        or parent.deployment_id != identity.deployment_id
        or parent.family != identity.family
        or parent.policy_version != identity.policy_version
        or parent.endpoint_origin != current.routing_lock.endpoint_origin
        or current.rights_lock.provider != parent.provider
        or current.rights_lock.endpoint_origin != parent.endpoint_origin
        or current.rights_lock.deployment_id != parent.deployment_id
        or current.stage not in parent.allowed_stages
        or identity.role not in parent.allowed_roles
        or any(
            category not in parent.allowed_derived_data_categories
            for category in current.rights_lock.data_categories
        )
        or current.stage_caps.call_limit > parent.max_calls
        or current.stage_caps.input_token_ceiling > parent.total_input_token_ceiling
        or current.stage_caps.output_token_ceiling > parent.total_output_token_ceiling
        or current.stage_caps.time_limit_seconds > parent.total_time_limit_seconds
    ):
        raise ValueError("stage plan exceeds parent scope")
    if current.stage == "C_CLASSIFY":
        material_ids = tuple(
            sorted(
                {
                    material_id
                    for call in current.request_manifest.calls
                    for material_id in call.material_ids
                }
            )
        )
        authorized_ids = tuple(material.material_id for material in parent.c_materials)
        authorized_hashes = {
            digest
            for material in parent.c_materials
            for digest in (
                material.corpus_entry_sha256,
                material.source_revision_receipt_sha256,
                material.w1_sha256,
                material.native_page_map_sha256,
            )
        }
        stage_hashes = {artifact.sha256 for artifact in current.eligibility_lock.input_artifacts}
        stage_hashes.update(
            digest for check in current.eligibility_lock.checks for digest in check.input_sha256s
        )
        if (
            parent.c_request_manifest_hash != current.manifest_hash
            or material_ids != authorized_ids
            or current.rights_lock.material_or_derivation_ids != authorized_ids
            or not authorized_hashes.issubset(stage_hashes)
            or parent.c_prompt_preview_sha256 not in stage_hashes
        ):
            raise ValueError("C stage does not bind the authorized materials and preview")
    elif (
        current.derived_stage_receipt is None
        or current.derived_stage_receipt.parent_authorization_digest
        != current.parent_authorization_digest
        or current.derived_stage_receipt.derivation_rules_version != parent.derivation_rules_version
    ):
        raise ValueError("D stage derivation exceeds parent scope")


__all__ = [
    "G3_STAGE_PROFILES",
    "validate_g3_bounded_plan",
    "validate_g3_parent_scope",
]
