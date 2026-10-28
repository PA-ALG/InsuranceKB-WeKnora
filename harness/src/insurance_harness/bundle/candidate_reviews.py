"""Responses of the platform's candidate review routes for a service key (RV6e).

The detail is what the review page shows for one candidate: its bundle members with their
payloads, its removals and its review points. A machine caller checks this content before it
closes review points, so the parse is strict and slugs must be unique.
"""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Response(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)


class BundleMember(_Response):
    kind: str
    logical_slug: str = Field(min_length=1)
    member_digest: str = Field(min_length=1)
    payload: Any = None
    evidence_refs: list[str] = Field(default_factory=list)
    access_scope: str = ""


class PointVerdict(_Response):
    outcome: str
    reason: str
    subject: str
    created_at: str


class ReviewPoint(_Response):
    slug: str = Field(min_length=1)
    kind: str
    status: str
    decision: PointVerdict | None = None
    release_id: str | None = None
    blocker: str = ""


class CandidateDetail(_Response):
    candidate_id: str = Field(min_length=1)
    status: str
    base_release_id: str = ""
    head_release_id: str | None = None
    blocker: str = ""
    point_count: int = Field(ge=0)
    pending_points: int = Field(ge=0)
    bundle_members: list[BundleMember]
    bundle_removals: list[str]
    points: list[ReviewPoint]

    @field_validator("bundle_members", "bundle_removals", mode="before")
    @classmethod
    def _omitted_lists_are_empty(cls, value: object) -> object:
        # The platform writes a list the submitted bundle omitted as null.
        return [] if value is None else value

    @model_validator(mode="after")
    def _unique_slugs(self) -> Self:
        for slugs in (
            [m.logical_slug for m in self.bundle_members],
            [p.slug for p in self.points],
        ):
            if len(set(slugs)) != len(slugs):
                raise ValueError("duplicate slug")
        return self
