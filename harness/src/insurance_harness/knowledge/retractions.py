"""Explicit exclusive-support retraction proof for OpenSpec 058."""

from __future__ import annotations

from typing import Annotated, Final, Literal, Protocol, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictStr,
    StringConstraints,
    computed_field,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.knowledge.source_authority import (
    FactScopeV1,
    SourceAuthorityV1,
    _resolved_identity,
    compare_source_authority,
)

NonBlankStr = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=512, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
RetractionReason = Literal[
    "source_revision_replaced",
    "source_withdrawn",
    "business_retraction",
]

RETRACTION_PROOF_OBJECT_TYPE: Final[str] = "incremental-retraction-proof.v1"
class _FieldAuthority(Protocol):
    primary_role: Literal["terms", "brochure", "rate_table"]
    support_roles: tuple[Literal["terms", "brochure", "rate_table"], ...]


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


class RetractionContractError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class RetractionProofV1(_FrozenModel):
    scope: FactScopeV1
    old_source_revision_id: NonBlankStr
    replacement_authority: SourceAuthorityV1
    complete_scope: Literal[True]
    explicitly_absent: Literal[True]
    evidence_hash: Sha256Hex
    reason_code: RetractionReason

    @model_validator(mode="before")
    @classmethod
    def require_resolved_old_revision(cls, value: object) -> object:
        if isinstance(value, dict):
            old_revision = value.get("old_source_revision_id")
            if isinstance(old_revision, str):
                _resolved_identity(old_revision)
        return value

    @model_validator(mode="after")
    def require_distinct_replacement(self) -> Self:
        if self.old_source_revision_id == self.replacement_authority.source_revision_id:
            raise ValueError("replacement_revision_must_differ")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def proof_hash(self) -> str:
        payload = self.model_dump(mode="python", exclude={"proof_hash"})
        return canonical_hash(RETRACTION_PROOF_OBJECT_TYPE, payload)


def require_exclusive_retraction(
    proof: RetractionProofV1,
    *,
    baseline_scope: FactScopeV1,
    baseline_authority: SourceAuthorityV1,
    supporting_source_revision_ids: tuple[str, ...],
    field_authority: _FieldAuthority,
) -> None:
    """Fail closed unless one exact predecessor is the sole support."""

    proof = RetractionProofV1.model_validate(proof)
    if proof.scope != baseline_scope:
        raise RetractionContractError("retraction_scope_mismatch")
    if (
        supporting_source_revision_ids != (proof.old_source_revision_id,)
        or baseline_authority.source_revision_id != proof.old_source_revision_id
    ):
        raise RetractionContractError("retraction_not_exclusive")
    try:
        relation = compare_source_authority(
            proof.replacement_authority,
            baseline_authority,
            field_authority=field_authority,
        )
    except ValueError as error:
        raise RetractionContractError("retraction_authority_mismatch") from error
    if relation != "higher":
        raise RetractionContractError("retraction_authority_not_newer")


__all__ = [
    "RETRACTION_PROOF_OBJECT_TYPE",
    "RetractionContractError",
    "RetractionProofV1",
    "require_exclusive_retraction",
]
