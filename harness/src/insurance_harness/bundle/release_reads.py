"""Wire models for fixed-version release reads."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ReleaseHeader(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    id: str = Field(min_length=1)
    epoch: int = Field(ge=1)
    base_release_id: str = ""
    candidate_id: str = ""
    decision_digest: str = ""
    retired_at: str | None = None


class FixedHeader(ReleaseHeader):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    base_release_id: str
    candidate_id: str
    decision_digest: str

    @property
    def identity(self) -> tuple[str, int, str, str, str]:
        return self.id, self.epoch, self.base_release_id, self.candidate_id, self.decision_digest


class ReleaseMember(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    kind: str
    logical_slug: str
    member_digest: str
    payload: Any = None
    evidence_refs: list[str] = Field(default_factory=list)
    access_scope: str = ""


class MemberIndexRow(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    logical_slug: str = Field(min_length=1)
    member_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: str = Field(min_length=1)
    subject_ref: str = ""
    logical_key: str = ""
    entity_id: str = ""


class MemberIndex(FixedHeader):
    members: list[MemberIndexRow] = Field(max_length=20000)


class MemberLookup(FixedHeader):
    members: list[ReleaseMember] = Field(max_length=256)
    missing: list[str] = Field(max_length=256)
