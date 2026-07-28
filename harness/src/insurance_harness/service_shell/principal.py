"""Fail-closed principals and the single authorization surface for OpenSpec 039."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class AuthenticationError(Exception):
    """A credential cannot mint a principal; messages never contain credential values."""

    code = "authentication_failed"


class AuthorizationError(Exception):
    """A valid principal does not have the requested scope or capability."""

    code = "authorization_failed"


class HumanRole(StrEnum):
    """The closed human role vocabulary from architecture 033 §13."""

    VIEWER = "viewer"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    SPACE_ADMIN = "space_admin"
    SUPER_ADMIN = "super_admin"


class ServiceKind(StrEnum):
    """The only service-principal identities in the MVP."""

    SOURCE_READER = "source_reader"
    WIKI_PROJECTOR = "wiki_projector"


class ServiceCapability(StrEnum):
    """Closed service capabilities; they are deliberately not human roles."""

    READ_RAW_KNOWLEDGE = "read_raw_knowledge"
    PROJECT_MANAGED_PAGE = "project_managed_page"


_CAPABILITIES_BY_SERVICE: Mapping[ServiceKind, frozenset[ServiceCapability]] = {
    ServiceKind.SOURCE_READER: frozenset({ServiceCapability.READ_RAW_KNOWLEDGE}),
    ServiceKind.WIKI_PROJECTOR: frozenset({ServiceCapability.PROJECT_MANAGED_PAGE}),
}


class HumanPrincipal(BaseModel):
    """Immutable authenticated human with roles bound to explicit Spaces."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["human"] = "human"
    subject_id: str = Field(min_length=1)
    bindings: Mapping[str, frozenset[HumanRole]]

    @model_validator(mode="after")
    def validate_bindings(self) -> HumanPrincipal:
        if not self.bindings:
            raise ValueError("bindings must not be empty")
        for space_id, roles in self.bindings.items():
            if not space_id or "\x00" in space_id:
                raise ValueError("binding Space ids must be non-empty and contain no NUL")
            if not roles:
                raise ValueError("each binding must contain at least one role")
        object.__setattr__(
            self,
            "bindings",
            MappingProxyType(dict(self.bindings)),
        )
        return self


class ServicePrincipal(BaseModel):
    """Immutable scoped service identity that cannot carry human-role bindings."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["service"] = "service"
    service: ServiceKind
    space_ids: frozenset[str] = Field(min_length=1)
    capabilities: frozenset[ServiceCapability] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_scope_and_capabilities(self) -> ServicePrincipal:
        if any(not space_id or "\x00" in space_id for space_id in self.space_ids):
            raise ValueError("service Space ids must be non-empty and contain no NUL")
        allowed = _CAPABILITIES_BY_SERVICE[self.service]
        if not self.capabilities <= allowed:
            raise ValueError(f"capabilities are invalid for {self.service.value}")
        return self


Principal = HumanPrincipal | ServicePrincipal


class StaticPrincipalProvider:
    """MVP credential provider; `authenticate` is the single principal minting entry."""

    def __init__(
        self,
        records: Mapping[str, Mapping[str, Any]],
        *,
        known_space_ids: frozenset[str],
    ) -> None:
        self._records = deepcopy(
            {credential: dict(record) for credential, record in records.items()}
        )
        self._known_space_ids = frozenset(known_space_ids)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(credential_count={len(self._records)})"

    def authenticate(self, credential: str | None) -> Principal:
        """Mint a current principal from provider-owned bindings, never caller claims."""
        if (
            credential is None
            or not credential
            or credential != credential.strip()
            or any(character.isspace() for character in credential)
        ):
            raise AuthenticationError("invalid_credential")
        record = self._records.get(credential)
        if record is None:
            raise AuthenticationError("invalid_credential")
        try:
            kind = record.get("kind")
            if kind == "human":
                human = HumanPrincipal.model_validate(record)
                principal: Principal = human
                spaces = frozenset(human.bindings)
            elif kind == "service":
                service = ServicePrincipal.model_validate(record)
                principal = service
                spaces = service.space_ids
            else:
                raise ValueError("unknown principal kind")
            if not spaces <= self._known_space_ids:
                raise ValueError("unknown Space binding")
            return principal
        except (ValidationError, ValueError, TypeError) as error:
            raise AuthenticationError("invalid_principal_binding") from error


def require_space_role(
    principal: Principal,
    *,
    space_id: str,
    allowed_roles: frozenset[HumanRole],
) -> frozenset[HumanRole]:
    """Authorize one Space from authenticated bindings; caller claims are irrelevant."""
    if not isinstance(principal, HumanPrincipal):
        raise AuthorizationError("human_principal_required")
    super_admin_roles = next(
        (
            roles
            for roles in principal.bindings.values()
            if HumanRole.SUPER_ADMIN in roles
        ),
        None,
    )
    if super_admin_roles is not None:
        return super_admin_roles
    roles = principal.bindings.get(space_id)
    if roles is None:
        raise AuthorizationError("space_scope_forbidden")
    if roles.isdisjoint(allowed_roles):
        raise AuthorizationError("human_role_forbidden")
    return roles


def require_service_capability(
    principal: Principal,
    *,
    space_id: str,
    capability: ServiceCapability,
) -> None:
    """Authorize one scoped service capability through the only capability guard."""
    if not isinstance(principal, ServicePrincipal):
        raise AuthorizationError("service_principal_required")
    if space_id not in principal.space_ids:
        raise AuthorizationError("space_scope_forbidden")
    if capability not in principal.capabilities:
        raise AuthorizationError("service_capability_forbidden")


def require_super_admin(principal: Principal) -> None:
    """Authorize the explicitly global observation surface."""
    if not isinstance(principal, HumanPrincipal):
        raise AuthorizationError("human_principal_required")
    if not any(
        HumanRole.SUPER_ADMIN in roles for roles in principal.bindings.values()
    ):
        raise AuthorizationError("super_admin_required")
