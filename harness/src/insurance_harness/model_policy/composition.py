"""Sealed production composition for canonical admission and model policy."""

from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module
from typing import cast

from .admission import (
    AdmissionPolicyDenied,
    AdmissionVerifier,
    StrictAdmissionRequestBinding,
    VerifiedAdmission,
    _is_verified_admission,
)
from .models import IdentityKey, ModelCallContext
from .policy import ProductionModelPolicy, _PolicyDecision

_COMPOSITION_SEAL = object()
_CANONICAL_ADMISSION_MODULE = "insurance_harness.run_admission.evaluator"
_CANONICAL_SELECTOR_NAME = "select_canonical_admission_verifier"


class ProductionModelComposition:
    """Fixed canonical verifier bridge and policy with no caller override ports."""

    __slots__ = ("_policy",)
    _policy: ProductionModelPolicy

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
        verifier = _select_canonical_admission_verifier(
            validated.expected_purpose,
            validated.expected_run_schema_version,
        )
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

    def _evaluate_for_guard(
        self,
        verified_admission: VerifiedAdmission,
        context: ModelCallContext,
        /,
    ) -> _PolicyDecision:
        """Package-local hook for the future canonical guarded client only."""

        return self._policy._evaluate_call(verified_admission, context)


def _build_production_model_composition(
    *,
    approved_identity_keys: Iterable[IdentityKey],
) -> ProductionModelComposition:
    """Assemble policy only; verifier selection always follows the fixed bridge."""

    composition = ProductionModelComposition.__new__(
        ProductionModelComposition,
        _seal=_COMPOSITION_SEAL,
    )
    object.__setattr__(
        composition,
        "_policy",
        ProductionModelPolicy(approved_identity_keys),
    )
    return composition


def _select_canonical_admission_verifier(
    purpose: str,
    run_schema_version: str,
    /,
) -> AdmissionVerifier:
    """Call the single code-owned 030 selector; no object can be caller-injected."""

    try:
        module = import_module(_CANONICAL_ADMISSION_MODULE)
    except ModuleNotFoundError:
        raise AdmissionPolicyDenied("canonical_verifier_unavailable") from None
    selector = getattr(module, _CANONICAL_SELECTOR_NAME, None)
    if not callable(selector):
        raise AdmissionPolicyDenied("canonical_verifier_unavailable")
    try:
        verifier = selector(purpose, run_schema_version)
    except AdmissionPolicyDenied:
        raise
    except LookupError:
        raise AdmissionPolicyDenied("unknown_admission_profile") from None
    except Exception:
        raise AdmissionPolicyDenied("canonical_verifier_unavailable") from None
    if not callable(getattr(verifier, "verify", None)):
        raise AdmissionPolicyDenied("canonical_verifier_unavailable")
    return cast(AdmissionVerifier, verifier)
