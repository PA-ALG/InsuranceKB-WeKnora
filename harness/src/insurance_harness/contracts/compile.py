"""Harness compilation and governance contracts; not Release members."""

from typing import Self

from pydantic import Field, model_validator

from insurance_harness.contracts.enums import (
    CompileStatus,
    CompileTaskKind,
    GapStatus,
    GapTrigger,
    ReviewKind,
    ReviewStatus,
    TextOrigin,
)
from insurance_harness.contracts.knowledge import (
    Claim,
    ContractModel,
    Locator,
    NonBlank,
    NonNegativeInt,
    PositiveInt,
    Relation,
    Sha256,
)


class Block(ContractModel):
    block_id: str
    start: NonNegativeInt
    end: NonNegativeInt
    locator: Locator

    @model_validator(mode="after")
    def validate_offsets(self) -> Self:
        if self.end < self.start:
            raise ValueError("end must be greater than or equal to start")
        return self


class PageText(ContractModel):
    source_revision_id: NonBlank
    parse_artifact_digest: Sha256
    document_role: NonBlank
    page_number: PositiveInt
    text: str
    text_origin: TextOrigin
    blocks: list[Block] = Field(default_factory=list)


class CompileTask(ContractModel):
    task_key: NonBlank
    kind: CompileTaskKind
    entity_version: NonBlank
    material_set: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    config_ref: NonBlank
    budget: NonNegativeInt = 0


class CompileResult(ContractModel):
    task_key: NonBlank
    status: CompileStatus
    claims: list[Claim] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
    call_receipts: list[str] = Field(default_factory=list)


class GapTask(ContractModel):
    gap_id: NonBlank
    target: NonBlank
    trigger: GapTrigger
    search_scope: list[str] = Field(default_factory=list)
    attempts: list[str] = Field(default_factory=list)
    status: GapStatus = GapStatus.OPEN


class ReviewItem(ContractModel):
    item_id: NonBlank
    kind: ReviewKind
    target: NonBlank
    evidence: list[str] = Field(default_factory=list)
    status: ReviewStatus = ReviewStatus.OPEN
    resolution_candidate: str | None = None
