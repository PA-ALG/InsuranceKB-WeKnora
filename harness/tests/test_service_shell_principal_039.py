from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from insurance_harness.service_shell.principal import (
    AuthenticationError,
    AuthorizationError,
    HumanPrincipal,
    HumanRole,
    ServiceCapability,
    ServiceKind,
    ServicePrincipal,
    StaticPrincipalProvider,
    require_service_capability,
    require_space_role,
)


def _provider() -> StaticPrincipalProvider:
    return StaticPrincipalProvider(
        {
            "human-secret": {
                "kind": "human",
                "subject_id": "user-1",
                "bindings": {
                    "space-a": ["viewer", "space_admin"],
                    "space-b": ["editor"],
                },
            },
            "reader-secret": {
                "kind": "service",
                "service": "source_reader",
                "space_ids": ["space-a"],
                "capabilities": ["read_raw_knowledge"],
            },
            "projector-secret": {
                "kind": "service",
                "service": "wiki_projector",
                "space_ids": ["space-b"],
                "capabilities": ["project_managed_page"],
            },
        },
        known_space_ids=frozenset({"space-a", "space-b"}),
    )


def test_t1_principal_enums_are_closed() -> None:
    assert {role.value for role in HumanRole} == {
        "viewer",
        "editor",
        "reviewer",
        "space_admin",
        "super_admin",
    }
    assert {kind.value for kind in ServiceKind} == {"source_reader", "wiki_projector"}
    assert {capability.value for capability in ServiceCapability} == {
        "read_raw_knowledge",
        "project_managed_page",
    }
    with pytest.raises(ValueError):
        HumanRole("owner")
    with pytest.raises(ValueError):
        ServiceKind("admin_bot")


@pytest.mark.parametrize("credential", [None, "", "unknown-secret", "bad\ncredential"])
def test_t1_missing_unknown_and_malformed_credentials_fail_closed(
    credential: str | None,
) -> None:
    with pytest.raises(AuthenticationError) as caught:
        _provider().authenticate(credential)
    if credential:
        assert credential not in str(caught.value)


def test_t1_no_anonymous_default_and_unknown_role_fails_closed() -> None:
    with pytest.raises(AuthenticationError):
        StaticPrincipalProvider(
            {},
            known_space_ids=frozenset(),
        ).authenticate(None)

    provider = StaticPrincipalProvider(
        {
            "credential": {
                "kind": "human",
                "subject_id": "user-1",
                "bindings": {"space-a": ["owner"]},
            }
        },
        known_space_ids=frozenset({"space-a"}),
    )
    with pytest.raises(AuthenticationError, match="invalid_principal_binding"):
        provider.authenticate("credential")


def test_t1_static_provider_requires_an_independent_known_space_authority() -> None:
    with pytest.raises(TypeError):
        cast(Any, StaticPrincipalProvider)({})


def test_t1_static_provider_deep_snapshots_caller_owned_records() -> None:
    caller_bindings = {"space-a": ["viewer"]}
    records: dict[str, dict[str, Any]] = {
        "credential": {
            "kind": "human",
            "subject_id": "user-1",
            "bindings": caller_bindings,
        }
    }
    provider = StaticPrincipalProvider(
        records,
        known_space_ids=frozenset({"space-a", "space-b"}),
    )

    caller_bindings["space-b"] = ["super_admin"]
    principal = provider.authenticate("credential")

    assert isinstance(principal, HumanPrincipal)
    assert frozenset(principal.bindings) == frozenset({"space-a"})
    with pytest.raises(AuthorizationError, match="space_scope_forbidden"):
        require_space_role(
            principal,
            space_id="space-b",
            allowed_roles=frozenset({HumanRole.SUPER_ADMIN}),
        )


def test_t1_minted_human_principal_bindings_are_deeply_immutable() -> None:
    principal = _provider().authenticate("human-secret")
    assert isinstance(principal, HumanPrincipal)

    with pytest.raises(TypeError):
        cast(dict[str, frozenset[HumanRole]], principal.bindings)["space-c"] = (
            frozenset({HumanRole.SUPER_ADMIN})
        )

    with pytest.raises(AuthorizationError, match="space_scope_forbidden"):
        require_space_role(
            principal,
            space_id="space-c",
            allowed_roles=frozenset({HumanRole.SUPER_ADMIN}),
        )


def test_t1_scope_and_identity_come_only_from_authenticated_binding() -> None:
    principal = _provider().authenticate("human-secret")
    assert isinstance(principal, HumanPrincipal)
    assert principal.subject_id == "user-1"
    assert require_space_role(
        principal,
        space_id="space-a",
        allowed_roles=frozenset({HumanRole.SPACE_ADMIN}),
    ) == frozenset({HumanRole.VIEWER, HumanRole.SPACE_ADMIN})

    # A caller-reported user/Space is not an input to minting or authorization.
    with pytest.raises(AuthorizationError, match="space_scope_forbidden"):
        require_space_role(
            principal,
            space_id="space-c",
            allowed_roles=frozenset({HumanRole.SPACE_ADMIN}),
        )
    assert principal.subject_id != "caller-reported-admin"


def test_t1_service_principals_are_scoped_and_capabilities_do_not_cross() -> None:
    reader = _provider().authenticate("reader-secret")
    projector = _provider().authenticate("projector-secret")
    assert isinstance(reader, ServicePrincipal)
    assert isinstance(projector, ServicePrincipal)
    require_service_capability(
        reader,
        space_id="space-a",
        capability=ServiceCapability.READ_RAW_KNOWLEDGE,
    )
    require_service_capability(
        projector,
        space_id="space-b",
        capability=ServiceCapability.PROJECT_MANAGED_PAGE,
    )
    with pytest.raises(AuthorizationError, match="service_capability_forbidden"):
        require_service_capability(
            reader,
            space_id="space-a",
            capability=ServiceCapability.PROJECT_MANAGED_PAGE,
        )
    with pytest.raises(AuthorizationError, match="service_capability_forbidden"):
        require_service_capability(
            projector,
            space_id="space-b",
            capability=ServiceCapability.READ_RAW_KNOWLEDGE,
        )
    with pytest.raises(AuthorizationError, match="human_principal_required"):
        require_space_role(
            reader,
            space_id="space-a",
            allowed_roles=frozenset({HumanRole.VIEWER}),
        )


def test_t1_service_principal_cannot_hold_human_roles_or_cross_capabilities() -> None:
    with pytest.raises(ValidationError):
        ServicePrincipal.model_validate(
            {
                "kind": "service",
                "service": "source_reader",
                "space_ids": ["space-a"],
                "capabilities": ["read_raw_knowledge"],
                "bindings": {"space-a": ["super_admin"]},
            }
        )
    with pytest.raises(ValidationError, match="capabilities"):
        ServicePrincipal.model_validate(
            {
                "kind": "service",
                "service": "source_reader",
                "space_ids": ["space-a"],
                "capabilities": ["project_managed_page"],
            }
        )
