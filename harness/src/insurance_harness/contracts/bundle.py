"""Versioned, domain-independent candidate envelopes for the platform."""

from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field, StringConstraints

from insurance_harness.contracts.enums import Origin, ReviewMode
from insurance_harness.contracts.knowledge import ContractModel, NonBlank, NonNegativeInt, Sha256

CONTRACT_VERSION = "1"


class BundleMember(ContractModel):
    kind: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    logical_slug: NonBlank
    payload: dict[str, Any]
    member_digest: Sha256
    evidence_refs: list[str] = Field(default_factory=list)
    access_scope: NonBlank


class ReviewPlan(ContractModel):
    mode: ReviewMode
    policy_ref: str | None = None
    sample_size: NonNegativeInt | None = None


class CandidateBundle(ContractModel):
    contract_version: Literal["1"]
    base_release_id: NonBlank | None = None
    base_epoch: NonNegativeInt | None = None
    origin: Origin
    members: list[BundleMember] = Field(default_factory=list)
    removals: list[str] = Field(default_factory=list)
    review_plan: list[ReviewPlan] = Field(default_factory=list)
    compiler_identity: NonBlank

    if TYPE_CHECKING:
        # Widen only the static signature; preserve Pydantic's runtime validation.
        def __init__(self, **data: Any) -> None: ...
