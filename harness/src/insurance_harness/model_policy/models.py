"""Immutable public models for the production model boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictStr, StringConstraints

ModelFamily = Literal["minimax", "qwen", "qwen-vl"]
ModelRole = Literal["classify", "extract", "gap", "verify", "consensus"]
IdentityKey = tuple[str, str, ModelRole, str]

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=256),
]
Sha256Hex = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]


class _ImmutableModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    def copy(
        self,
        *,
        include: object = None,
        exclude: object = None,
        update: dict[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Disable Pydantic's deprecated, unvalidated copy path."""

        raise TypeError("copy() is disabled; use validated model_copy()")

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        """Revalidate every update instead of trusting Pydantic's unchecked copy."""

        if update is None:
            return super().model_copy(deep=deep)
        values = self.model_dump(mode="python", round_trip=True)
        values.update(update)
        return type(self).model_validate(values)


class ModelIdentity(_ImmutableModel):
    provider: NonBlankStr
    deployment_id: NonBlankStr
    family: ModelFamily
    role: ModelRole
    policy_version: NonBlankStr

    @property
    def identity_key(self) -> IdentityKey:
        """Return the exact, stable identity used by the injected approval set."""

        return (self.provider, self.deployment_id, self.role, self.policy_version)


class ModelPermit(_ImmutableModel):
    """Frozen permit shape; admission evaluation is implemented by 027 Task 3."""

    identity: ModelIdentity
    run_id: NonBlankStr
    run_revision: NonBlankStr
    admission_hash: Sha256Hex
    template_hash: Sha256Hex
    model_plan_hash: Sha256Hex
    expires_at: AwareDatetime
