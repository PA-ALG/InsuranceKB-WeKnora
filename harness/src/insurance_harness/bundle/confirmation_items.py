"""The S5b-3a confirmation items as the platform client sends and reads them.

Titles, details and option labels are the submitter's opaque text; the platform keeps one item per
(subject, revision, content), appends answers and closes an item once.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Response(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)


class ConfirmationOption(_Response):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)


class ConfirmationInput(BaseModel):
    """One question for a person as the submitter words it (S5b-3a)."""

    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    subject: str
    revision: str
    title: str
    detail: str
    options: list[ConfirmationOption]


class ConfirmationAnswer(_Response):
    id: str = Field(min_length=1)
    item_id: str
    option_key: str
    note: str = ""
    answerer: str
    answered_at: str


class ConfirmationClosure(_Response):
    reason: Literal["applied", "obsolete"]
    answer_id: str | None = None
    closed_by: str
    closed_at: str


class ConfirmationItem(_Response):
    """A stored confirmation item with its latest answer and its closure, if any."""

    id: str = Field(min_length=1)
    space_id: str
    subject: str
    revision: str
    content_digest: str
    title: str
    detail: str
    options: list[ConfirmationOption]
    created_by: str
    created_at: str
    answer: ConfirmationAnswer | None = None
    closure: ConfirmationClosure | None = None
