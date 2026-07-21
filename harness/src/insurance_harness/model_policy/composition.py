"""Sealed production composition for canonical admission and model policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType

from .admission import (
    AdmissionPolicyDenied,
    AdmissionVerifier,
    StrictAdmissionRequestBinding,
    VerifiedAdmission,
    _is_verified_admission,
)
from .models import IdentityKey, ModelCallContext
from .policy import PolicyDecision, ProductionModelPolicy

type AdmissionProfile = tuple[str, str]
_COMPOSITION_SEAL = object()


class ProductionModelComposition:
    """Code-owned verifier registry and policy with no caller override ports."""

    __slots__ = ("_policy", "_verifiers")
    _policy: ProductionModelPolicy
    _verifiers: Mapping[AdmissionProfile, AdmissionVerifier]

    def __new__(
        cls,
        *_args: object,
        _seal: object | None = None,
        **_kwargs: object,
    ) -> ProductionModelComposition:
        if cls is not ProductionModelComposition or _seal is not _COMPOSITION_SEAL:
            raise TypeError("ProductionModelComposition is built only by composition root")
        return super().__new__(cls)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("ProductionModelComposition is immutable")

    def verify(
        self,
        request: StrictAdmissionRequestBinding,
        /,
    ) -> VerifiedAdmission:
        """Select the exact code-owned verifier using independent expectations."""

        try:
            validated = StrictAdmissionRequestBinding.model_validate(
                request.model_dump(mode="python", round_trip=True, warnings=False)
            )
        except (AttributeError, TypeError, ValueError):
            raise AdmissionPolicyDenied("invalid_admission_request") from None
        profile = (
            validated.expected_purpose,
            validated.expected_run_schema_version,
        )
        verifier = self._verifiers.get(profile)
        if verifier is None:
            raise AdmissionPolicyDenied("unknown_admission_profile")
        try:
            verified = verifier.verify(validated)
        except AdmissionPolicyDenied:
            raise
        except Exception:
            raise AdmissionPolicyDenied("invalid_verified_admission") from None
        if (
            not _is_verified_admission(verified)
            or verified.request != validated
            or verified.request.request_digest != validated.request_digest
        ):
            raise AdmissionPolicyDenied("invalid_verified_admission")
        return verified

    def evaluate(
        self,
        verified_admission: VerifiedAdmission,
        context: ModelCallContext,
        /,
    ) -> PolicyDecision:
        """Evaluate through the single code-owned policy instance."""

        return self._policy.evaluate_call(verified_admission, context)


def _build_production_model_composition(
    *,
    canonical_verifiers: Mapping[AdmissionProfile, AdmissionVerifier],
    approved_identity_keys: Iterable[IdentityKey],
) -> ProductionModelComposition:
    """Non-public assembly hook for the production composition root and tests."""

    normalized: dict[AdmissionProfile, AdmissionVerifier] = {}
    for profile, verifier in canonical_verifiers.items():
        if (
            not isinstance(profile, tuple)
            or len(profile) != 2
            or not all(isinstance(item, str) and item.strip() for item in profile)
            or not callable(getattr(verifier, "verify", None))
        ):
            raise ValueError("invalid canonical admission verifier registration")
        normalized[(profile[0].strip(), profile[1].strip())] = verifier
    composition = ProductionModelComposition.__new__(
        ProductionModelComposition,
        _seal=_COMPOSITION_SEAL,
    )
    object.__setattr__(composition, "_verifiers", MappingProxyType(normalized))
    object.__setattr__(
        composition,
        "_policy",
        ProductionModelPolicy(approved_identity_keys),
    )
    return composition
