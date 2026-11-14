"""Wire models for the platform spot-check endpoints."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Verdict(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    id: str = Field(min_length=1)
    sample_id: str
    outcome: Literal["correct", "incomplete", "wrong"]
    note: str = ""
    reviewer: str
    decided_at: str


class Sample(BaseModel):
    """A spot-check sample of one release member (RV4), with its latest verdict if any."""

    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    id: str = Field(min_length=1)
    space_id: str = Field(min_length=1)
    release_id: str = Field(min_length=1)
    logical_slug: str = Field(min_length=1)
    member_digest: str
    stratum: str
    created_by: str
    created_at: str
    verdict: Verdict | None = None


class Samples(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)

    samples: list[Sample]
