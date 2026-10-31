"""Versioned field adoption of restricted materials (blueprint §7.3, S4j Spec §3.2).

A header rule lets a non-evidence role's header block serve its fields (a rate table's header for
the payment term). A scoped rule (S11c Spec §2.4) lets a non-evidence role's whole text serve only
its fields (sales and training materials for the sales-type fields). Either way the role serves
no other field, at compile and at publish.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from importlib.resources import files
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.evidence.quote_verification import PageTextLike
from insurance_harness.identity.material_roles import (
    document_roles,
    evidence_pages,
    load_material_roles,
)

NonBlank = Annotated[str, StringConstraints(pattern=r"\S")]


class TrustPolicyError(ValueError):
    """A stable code, without policy content or a local path."""

    def __init__(self) -> None:
        self.code = "TRUST_POLICY_INVALID"
        super().__init__(self.code)


class HeaderRule(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    role: NonBlank
    fields: tuple[NonBlank, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_fields(self) -> "HeaderRule":
        if len(set(self.fields)) != len(self.fields):
            raise ValueError("duplicate field")
        return self


class TrustPolicy(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    version: NonBlank
    header_rules: tuple[HeaderRule, ...]
    scoped_rules: tuple[HeaderRule, ...] = ()

    @model_validator(mode="after")
    def _restricted_roles(self) -> "TrustPolicy":
        eligible = {r.role for r in load_material_roles().roles if not r.evidence}
        roles = self.restricted_roles()
        if len(set(roles)) != len(roles) or not set(roles) <= eligible:
            raise ValueError("restricted roles must be unique non-evidence roles")
        return self

    def header_fields(self, role: str) -> frozenset[str]:
        return frozenset(f for r in self.header_rules if r.role == role for f in r.fields)

    def header_roles(self) -> frozenset[str]:
        return frozenset(r.role for r in self.header_rules)

    def scoped_roles(self) -> frozenset[str]:
        return frozenset(r.role for r in self.scoped_rules)

    def restricted_roles(self) -> tuple[str, ...]:
        """Every restricted role, header roles first, in policy order."""
        return tuple(r.role for r in (*self.header_rules, *self.scoped_rules))

    def restricted_fields(self, role: str) -> frozenset[str]:
        """The fields a restricted role may serve, by its header or its scoped rule."""
        rules = (*self.header_rules, *self.scoped_rules)
        return frozenset(f for r in rules if r.role == role for f in r.fields)


def parse_trust_policy(text: str) -> TrustPolicy:
    try:
        return TrustPolicy.model_validate_json(text)
    except (ValidationError, ValueError) as error:
        raise TrustPolicyError() from error


@lru_cache(maxsize=1)
def load_trust_policy() -> TrustPolicy:
    try:
        return parse_trust_policy(
            files(__package__).joinpath("trust_policy.json").read_text(encoding="utf-8")
        )
    except OSError as error:
        raise TrustPolicyError() from error


@dataclass(frozen=True)
class TrustedPages[P]:
    evidence: list[P]
    # Restricted pages by role: header roles (clipped to their header block when segmented) and
    # scoped roles (segmented whole); each serves only its role's fields.
    table_headers: dict[str, list[P]]
    # Each read document's effective role (recorded or inferred), for output identity (S5b-6).
    roles: dict[str, str] = field(default_factory=dict)


def trusted_pages[P: PageTextLike](
    pages: Sequence[P], recorded: Mapping[str, str] | None = None
) -> TrustedPages[P]:
    """Whole evidence plus separately bounded restricted inputs, without rewriting pages.

    `recorded` maps a document to its registry-recorded role, which wins over inference (S5b-6).
    """
    evidence = evidence_pages(pages, recorded)  # validates every material, incl. excluded ones
    roles = document_roles(pages, recorded)
    policy = load_trust_policy()
    headers = {
        role: [p for p in pages if roles[p.document] == role]
        for role in policy.restricted_roles()
        if role in roles.values()
    }
    resolved = {document: role for document, role in roles.items() if role is not None}
    return TrustedPages(evidence, headers, resolved)
