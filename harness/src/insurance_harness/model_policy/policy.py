"""Single fail-closed evaluator for production model identities."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .models import IdentityKey, ModelIdentity

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

        deployment = identity.deployment_id.casefold()
        if identity.family not in _APPROVED_FAMILIES:
            raise ModelPolicyDenied("family_not_approved")
        if any(marker in deployment for marker in _STRONG_MODEL_MARKERS):
            raise ModelPolicyDenied("strong_model")

        tokens = frozenset(filter(None, re.split(r"[^a-z0-9]+", deployment)))
        if deployment in _UNVERSIONED_ALIASES or tokens.intersection(_ROLLING_MARKERS):
            raise ModelPolicyDenied("rolling_identity")

        if identity.identity_key not in self._approved_identity_keys:
            raise ModelPolicyDenied("identity_not_approved")

        return identity
