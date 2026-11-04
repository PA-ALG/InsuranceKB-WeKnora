"""The versioned review policy: which packs go live unattended, at which scores (RV1 §3.1).

Product packs require independent scores at their configured thresholds (blueprint §6.3).
SK-5's explicit user calibration admits only the source-supported methods pack without scores;
its dedicated compiler checks evidence and product-information signals. Generic score routing
does not infer eligibility from that list. Both forms of admission remain versioned data.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)

NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
# Strict: a JSON boolean is not a threshold (true would silently become 1.0).
Score = Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)]


class PackThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    default: Score | None = None
    fields: dict[NonBlank, Score] = Field(default_factory=dict)


class ReviewPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: NonBlank
    admitted_packs: list[NonBlank] = Field(default_factory=list)
    source_supported_packs: list[NonBlank] = Field(default_factory=list)
    thresholds: dict[NonBlank, PackThresholds] = Field(default_factory=dict)

    @field_validator("admitted_packs", "source_supported_packs")
    @classmethod
    def no_duplicates(cls, packs: list[str]) -> list[str]:
        if len(set(packs)) != len(packs):
            raise ValueError("a pack is admitted once")
        return packs

    @model_validator(mode="after")
    def source_supported_is_admitted(self) -> ReviewPolicy:
        if not set(self.source_supported_packs) <= set(self.admitted_packs):
            raise ValueError("source-supported packs must be admitted")
        return self

    @property
    def policy_ref(self) -> str:
        return f"review-policy@{self.version}"

    def admitted(self, pack_id: str) -> bool:
        return pack_id in self.admitted_packs

    def threshold(self, pack_id: str, field_key: str) -> float | None:
        """The field's own threshold, else the pack default, else None (not eligible)."""
        pack = self.thresholds.get(pack_id)
        if pack is None:
            return None
        return pack.fields.get(field_key, pack.default)


def load_review_policy(path: str | Path | None = None) -> ReviewPolicy:
    """Read a policy file; None reads the policy shipped with this package."""
    try:
        if path is None:
            text = files(__package__).joinpath("review_policy.json").read_text(encoding="utf-8")
        else:
            text = Path(path).read_text(encoding="utf-8")
        return ReviewPolicy.model_validate_json(text)
    except (OSError, ValidationError) as error:
        raise ValueError("review policy unreadable or malformed") from error
