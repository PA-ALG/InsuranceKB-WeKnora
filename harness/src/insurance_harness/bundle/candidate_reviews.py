"""Responses of the platform's candidate review routes for a service key (RV6d, RV7).

The queue lists pending candidates with their sizes; the preview groups a candidate's slugs
against the current Head. Neither carries member content: a service key cannot read what a
pending candidate proposes.
"""

from pydantic import BaseModel, ConfigDict, Field


class _Response(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)


class ReviewItem(_Response):
    """One candidate of a Space's review queue, as the service key sees it."""

    candidate_id: str = Field(min_length=1)
    subjects: list[str]
    point_count: int = Field(ge=0)
    pending_points: int = Field(ge=0)
    status: str
    members: int = Field(default=0, ge=0)
    removals: int = Field(default=0, ge=0)
    base_release_id: str = ""


class PreviewDelta(_Response):
    """Slugs of the resulting release, sorted; untouched Head members count as unchanged."""

    added: list[str]
    changed: list[str]
    removed: list[str]
    unchanged: list[str]


class CandidatePreview(_Response):
    candidate_id: str = Field(min_length=1)
    base_release_id: str
    head_release_id: str
    needs_rebase: bool
    delta: PreviewDelta
