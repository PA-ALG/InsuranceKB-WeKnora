"""Single fail-closed evaluator for production model identities."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime

from .admission import (
    IssuedModelPermit,
    VerifiedAdmission,
    _is_issued_model_permit,
    _is_verified_admission,
    _issue_model_permit,
)
from .models import (
    IdentityKey,
    ModelCallContext,
    ModelIdentity,
    ModelPermitView,
    PolicyReceipt,
)

_APPROVED_FAMILIES = frozenset({"minimax", "qwen", "qwen-vl"})
_STRONG_MODEL_MARKERS = frozenset(
    {
        "claude",
        "deepseek",
        "gemini",
        "gpt-4",
        "gpt-5",
        "opus",
        "sonnet",
    }
)
_ROLLING_MARKERS = frozenset(
    {"latest", "rolling", "current", "default", "auto", "stable", "blue", "green", "canary"}
)
_UNVERSIONED_ALIASES = frozenset(
    {
        "minimax",
        "qwen",
        "qwen3",
        "qwen-vl",
    }
)


class ModelPolicyDenied(PermissionError):
    """Typed policy refusal with a stable, secret-free reason code."""

    _MESSAGES = {
        "strong_model": "production model identity is outside the weak-model boundary",
        "family_not_approved": "production model family is not approved",
        "invalid_identity": "production model identity is invalid",
        "invalid_call_context": "production model call context is invalid",
        "invalid_verified_admission": "verified admission capability is invalid",
        "rolling_identity": "production model identity is not immutable",
        "identity_not_approved": "production model identity is not approved",
    }

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(self._MESSAGES.get(reason_code, "production model policy denied"))


class ProductionModelPolicy:
    """Evaluate identities against one constructor-injected exact approval set."""

    __slots__ = ("_approved_identity_keys",)

    def __init__(self, approved_identity_keys: Iterable[IdentityKey]) -> None:
        self._approved_identity_keys = frozenset(approved_identity_keys)

    @property
    def approved_identity_keys(self) -> frozenset[IdentityKey]:
        return self._approved_identity_keys

    def evaluate(self, identity: ModelIdentity) -> ModelIdentity:
        """Return an approved identity or raise a stable typed refusal."""

        try:
            validated = ModelIdentity.model_validate(
                identity.model_dump(mode="python", round_trip=True, warnings=False)
            )
        except (AttributeError, TypeError, ValueError):
            raise ModelPolicyDenied("invalid_identity") from None

        deployment = validated.deployment_id.casefold()
        if validated.family not in _APPROVED_FAMILIES:
            raise ModelPolicyDenied("family_not_approved")
        if any(marker in deployment for marker in _STRONG_MODEL_MARKERS):
            raise ModelPolicyDenied("strong_model")

        tokens = frozenset(filter(None, re.split(r"[^a-z0-9]+", deployment)))
        if deployment in _UNVERSIONED_ALIASES or tokens.intersection(_ROLLING_MARKERS):
            raise ModelPolicyDenied("rolling_identity")

        if validated.identity_key not in self._approved_identity_keys:
            raise ModelPolicyDenied("identity_not_approved")

        return validated

    def evaluate_call(
        self,
        verified_admission: VerifiedAdmission,
        context: ModelCallContext,
        /,
    ) -> PolicyDecision:
        """Evaluate one exact call scope and issue authority only on full match."""

        evaluated_at = datetime.now(UTC)
        if not _is_verified_admission(verified_admission):
            raise ModelPolicyDenied("invalid_verified_admission")
        try:
            context = ModelCallContext.model_validate(
                context.model_dump(mode="python", round_trip=True, warnings=False)
            )
        except (AttributeError, TypeError, ValueError):
            raise ModelPolicyDenied("invalid_call_context") from None

        binding = verified_admission.binding
        request = verified_admission.request
        mismatch_checks = (
            (context.purpose, binding.actual_purpose, "purpose_mismatch"),
            (
                context.run_schema_version,
                binding.actual_run_schema_version,
                "run_schema_version_mismatch",
            ),
            (context.space_id, binding.actual_space_id, "space_id_mismatch"),
            (context.run_id, binding.actual_run_id, "run_id_mismatch"),
            (
                context.run_revision,
                binding.actual_run_revision,
                "run_revision_mismatch",
            ),
            (
                context.admission_hash,
                binding.actual_admission_artifact_digest,
                "admission_artifact_digest_mismatch",
            ),
            (
                context.verified_binding_digest,
                verified_admission.verified_binding_digest,
                "verified_binding_digest_mismatch",
            ),
            (
                context.model_plan_hash,
                binding.actual_model_plan_hash,
                "model_plan_hash_mismatch",
            ),
        )
        for candidate, approved, reason_code in mismatch_checks:
            if candidate != approved:
                return self._deny(
                    verified_admission,
                    context,
                    reason_code=reason_code,
                    evaluated_at=evaluated_at,
                )
        if binding.actual_expires_at <= evaluated_at:
            return self._deny(
                verified_admission,
                context,
                reason_code="admission_expired",
                evaluated_at=evaluated_at,
            )
        if context.template_hash not in binding.approved_template_hashes:
            return self._deny(
                verified_admission,
                context,
                reason_code="template_not_approved",
                evaluated_at=evaluated_at,
            )
        try:
            identity = self.evaluate(context.identity)
        except ModelPolicyDenied as denied:
            return self._deny(
                verified_admission,
                context,
                reason_code=denied.reason_code,
                evaluated_at=evaluated_at,
            )
        if identity not in binding.approved_identities:
            return self._deny(
                verified_admission,
                context,
                reason_code="identity_not_admission_approved",
                evaluated_at=evaluated_at,
            )

        permit_view = ModelPermitView(
            identity=identity,
            purpose=context.purpose,
            run_schema_version=context.run_schema_version,
            space_id=context.space_id,
            run_id=context.run_id,
            run_revision=context.run_revision,
            admission_hash=context.admission_hash,
            verified_binding_digest=verified_admission.verified_binding_digest,
            template_hash=context.template_hash,
            model_plan_hash=context.model_plan_hash,
            call_scope_hash=context.call_scope_hash,
            expires_at=binding.actual_expires_at,
        )
        issued_permit = _issue_model_permit(
            permit_view,
            verified_admission,
            issued_at=evaluated_at,
        )
        permit_digest = _permit_view_digest(permit_view)
        receipt = PolicyReceipt(
            decision="ALLOW",
            reason_code="policy_allowed",
            identity_key=identity.identity_key,
            purpose=context.purpose,
            run_schema_version=context.run_schema_version,
            space_id=context.space_id,
            run_id=context.run_id,
            run_revision=context.run_revision,
            admission_hash=context.admission_hash,
            request_digest=request.request_digest,
            binding_digest=binding.binding_digest,
            verified_binding_digest=verified_admission.verified_binding_digest,
            template_hash=context.template_hash,
            model_plan_hash=context.model_plan_hash,
            call_scope_hash=context.call_scope_hash,
            permit_digest=permit_digest,
            permit_view=permit_view,
            evaluated_at=evaluated_at,
        )
        return PolicyDecision(receipt, issued_permit)

    @staticmethod
    def _deny(
        verified_admission: VerifiedAdmission,
        context: ModelCallContext,
        *,
        reason_code: str,
        evaluated_at: datetime,
    ) -> PolicyDecision:
        binding = verified_admission.binding
        receipt = PolicyReceipt(
            decision="DENY",
            reason_code=reason_code,
            identity_key=context.identity.identity_key,
            purpose=context.purpose,
            run_schema_version=context.run_schema_version,
            space_id=context.space_id,
            run_id=context.run_id,
            run_revision=context.run_revision,
            admission_hash=context.admission_hash,
            request_digest=verified_admission.request.request_digest,
            binding_digest=binding.binding_digest,
            verified_binding_digest=verified_admission.verified_binding_digest,
            template_hash=context.template_hash,
            model_plan_hash=context.model_plan_hash,
            call_scope_hash=context.call_scope_hash,
            evaluated_at=evaluated_at,
        )
        return PolicyDecision(receipt, None)


_PERMIT_VIEW_DIGEST_DOMAIN = b"insurancekb.model-policy.permit-view.v1\0"


def _permit_view_digest(view: ModelPermitView) -> str:
    encoded = json.dumps(
        view.model_dump(mode="json", round_trip=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(_PERMIT_VIEW_DIGEST_DOMAIN + encoded).hexdigest()


def _permit_matches_call_context(
    permit: object,
    verified_admission: VerifiedAdmission,
    context: ModelCallContext,
) -> bool:
    """Recheck the complete issued scope before Task 4 delegates transport."""

    if not _is_issued_model_permit(permit) or not _is_verified_admission(
        verified_admission
    ):
        return False
    if not isinstance(permit, IssuedModelPermit):
        return False
    try:
        validated_context = ModelCallContext.model_validate(
            context.model_dump(mode="python", round_trip=True, warnings=False)
        )
    except Exception:
        return False
    view: ModelPermitView = permit.view
    return (
        view.identity == validated_context.identity
        and view.purpose == validated_context.purpose
        and view.run_schema_version == validated_context.run_schema_version
        and view.space_id == validated_context.space_id
        and view.run_id == validated_context.run_id
        and view.run_revision == validated_context.run_revision
        and view.admission_hash == validated_context.admission_hash
        and view.verified_binding_digest == validated_context.verified_binding_digest
        and view.template_hash == validated_context.template_hash
        and view.model_plan_hash == validated_context.model_plan_hash
        and view.call_scope_hash == validated_context.call_scope_hash
        and view.verified_binding_digest == verified_admission.verified_binding_digest
    )


class PolicyDecision:
    """Result object whose receipt is public data and permit stays package-internal."""

    __slots__ = ("_issued_permit", "receipt")

    def __init__(
        self,
        receipt: PolicyReceipt,
        issued_permit: IssuedModelPermit | None,
    ) -> None:
        self.receipt = receipt
        self._issued_permit = issued_permit

    @property
    def allowed(self) -> bool:
        return self.receipt.decision == "ALLOW" and _is_issued_model_permit(
            self._issued_permit
        )
