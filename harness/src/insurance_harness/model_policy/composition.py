"""Sealed production composition for canonical admission and model policy."""

from __future__ import annotations

import os
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import import_module
from threading import RLock
from typing import Literal, cast
from weakref import WeakKeyDictionary

from .admission import (
    AdmissionPolicyDenied,
    AdmissionVerifier,
    StrictAdmissionRequestBinding,
    VerifiedAdmission,
    _is_verified_admission,
    _verified_authority_snapshot,
)
from .models import IdentityKey, ModelCallContext, ModelIdentity, _normalize_identity_keys
from .policy import (
    ProductionModelPolicy,
    _PolicyDecision,
    _validate_production_identity_declaration,
)

_COMPOSITION_SEAL = object()
_CANONICAL_ADMISSION_MODULE = "insurance_harness.run_admission.evaluator"
_CANONICAL_SELECTOR_NAME = "select_canonical_admission_verifier"
_AUTHORITY_PID = os.getpid()
_AUTHORITY_NONCE = secrets.token_bytes(32)


@dataclass(frozen=True, slots=True)
class _CompositionState:
    approved_identity_keys: frozenset[IdentityKey]
    model_plan_hash: str | None
    profile: Literal["production"] | None
    pid: int
    process_nonce: bytes


_COMPOSITION_STATES: WeakKeyDictionary[object, _CompositionState] = WeakKeyDictionary()
_COMPOSITION_LOCK = RLock()


class ProductionModelComposition:
    """Fixed canonical verifier bridge and policy with no caller override ports."""

    __slots__ = ("__weakref__",)

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

        if _get_composition_state(self) is None:
            raise AdmissionPolicyDenied("invalid_production_composition")
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

        state = _get_composition_state(self)
        if state is None or state.profile != "production" or state.model_plan_hash is None:
            raise AdmissionPolicyDenied("invalid_production_composition")
        verified_snapshot = _verified_authority_snapshot(verified_admission)
        if verified_snapshot is None:
            raise AdmissionPolicyDenied("invalid_verified_admission")
        _request, binding, _receipt = verified_snapshot
        if binding.actual_model_plan_hash != state.model_plan_hash:
            raise AdmissionPolicyDenied("model_plan_hash_mismatch")
        try:
            current_keys = _normalize_identity_keys(
                _validate_production_identity_declaration(identity).identity_key
                for identity in binding.approved_identities
            )
        except (AttributeError, TypeError, ValueError):
            raise AdmissionPolicyDenied("production_identity_mismatch") from None
        if current_keys != state.approved_identity_keys:
            raise AdmissionPolicyDenied("production_identity_mismatch")
        policy = ProductionModelPolicy(state.approved_identity_keys)
        return policy._evaluate_call(verified_admission, context)


def _new_composition(state: _CompositionState) -> ProductionModelComposition:
    composition = ProductionModelComposition.__new__(
        ProductionModelComposition,
        _seal=_COMPOSITION_SEAL,
    )
    with _COMPOSITION_LOCK:
        _COMPOSITION_STATES[composition] = state
    return composition


def _build_production_model_composition() -> ProductionModelComposition:
    """Build a verifier-only composition with no model-call authority."""

    return _new_composition(
        _CompositionState(
            approved_identity_keys=frozenset(),
            model_plan_hash=None,
            profile=None,
            pid=_AUTHORITY_PID,
            process_nonce=_AUTHORITY_NONCE,
        )
    )


def _bind_verified_production_model_composition(
    verified_admission: VerifiedAdmission,
    *,
    expected_identities: Iterable[ModelIdentity],
    expected_model_plan_hash: str,
) -> ProductionModelComposition:
    """Bind model-call authority only to canonical admission-approved identities."""

    verified_snapshot = _verified_authority_snapshot(verified_admission)
    if verified_snapshot is None:
        raise AdmissionPolicyDenied("invalid_verified_admission")
    request, binding, _receipt = verified_snapshot
    try:
        expected_keys = _normalize_identity_keys(
            _validate_production_identity_declaration(
                ModelIdentity.model_validate(
                    identity.model_dump(mode="python", round_trip=True, warnings=False)
                )
            ).identity_key
            for identity in expected_identities
        )
        actual_keys = _normalize_identity_keys(
            _validate_production_identity_declaration(identity).identity_key
            for identity in binding.approved_identities
        )
    except (AttributeError, TypeError, ValueError):
        raise AdmissionPolicyDenied("production_identity_mismatch") from None
    if expected_keys != actual_keys:
        raise AdmissionPolicyDenied("production_identity_mismatch")
    if (
        expected_model_plan_hash != request.expected_model_plan_hash
        or expected_model_plan_hash != binding.actual_model_plan_hash
    ):
        raise AdmissionPolicyDenied("model_plan_hash_mismatch")
    return _new_composition(
        _CompositionState(
            approved_identity_keys=actual_keys,
            model_plan_hash=binding.actual_model_plan_hash,
            profile="production",
            pid=_AUTHORITY_PID,
            process_nonce=_AUTHORITY_NONCE,
        )
    )


def _get_composition_state(value: object) -> _CompositionState | None:
    if not isinstance(value, ProductionModelComposition):
        return None
    with _COMPOSITION_LOCK:
        state = _COMPOSITION_STATES.get(value)
        if (
            state is None
            or state.pid != _AUTHORITY_PID
            or state.process_nonce != _AUTHORITY_NONCE
            or os.getpid() != _AUTHORITY_PID
        ):
            return None
        return state


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


def _reset_composition_authority_after_fork() -> None:
    global _AUTHORITY_NONCE, _AUTHORITY_PID
    global _COMPOSITION_LOCK, _COMPOSITION_STATES
    _COMPOSITION_LOCK = RLock()
    _COMPOSITION_STATES = WeakKeyDictionary()
    _AUTHORITY_PID = os.getpid()
    _AUTHORITY_NONCE = secrets.token_bytes(32)


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_composition_authority_after_fork)
