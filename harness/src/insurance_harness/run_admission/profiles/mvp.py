"""Code-owned identity and role contract of the OpenSpec 030 MVP profile."""

from __future__ import annotations

from insurance_harness.model_policy import (
    AdmissionPolicyDenied,
    ModelPolicyDenied,
    ProductionModelPolicy,
)

from ..models import MvpAdmissionPlan

MVP_PURPOSE = "enterprise-wiki-mvp"
MVP_RUN_SCHEMA_VERSION = "enterprise-wiki-mvp.v1"
MVP_SIGNATURE_DOMAIN = "insurancekb.run-admission.enterprise-wiki-mvp.v1"
MVP_MODEL_ROLES = frozenset({"classify", "extract", "gap", "verify", "consensus"})


def validate_mvp_plan(plan: MvpAdmissionPlan) -> MvpAdmissionPlan:
    """Apply code-owned profile constraints after generic DTO validation."""

    if (plan.purpose, plan.run_schema_version) != (
        MVP_PURPOSE,
        MVP_RUN_SCHEMA_VERSION,
    ):
        raise AdmissionPolicyDenied("artifact_profile_mismatch")
    roles = {identity.role for identity in plan.approved_identities}
    if roles != MVP_MODEL_ROLES:
        raise AdmissionPolicyDenied("profile_roles_mismatch")
    if len(plan.approved_identities) != len(MVP_MODEL_ROLES):
        raise AdmissionPolicyDenied("profile_roles_mismatch")
    try:
        policy = ProductionModelPolicy(
            identity.identity_key for identity in plan.approved_identities
        )
        tuple(policy.evaluate(identity) for identity in plan.approved_identities)
    except ModelPolicyDenied as exc:
        reason = (
            "rolling_model_identity"
            if exc.reason_code == "rolling_identity"
            else f"model_identity_{exc.reason_code}"
        )
        raise AdmissionPolicyDenied(reason) from None
    return plan


__all__ = [
    "MVP_MODEL_ROLES",
    "MVP_PURPOSE",
    "MVP_RUN_SCHEMA_VERSION",
    "MVP_SIGNATURE_DOMAIN",
    "validate_mvp_plan",
]
