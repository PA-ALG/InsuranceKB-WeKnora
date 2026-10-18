"""The versioned spot-check policy: how much of what went live unattended people re-check (RV4).

Blueprint §6.3: content published as machine review is sampled after release by risk and field, and
the verdicts calibrate the thresholds. Rates, minimums, target precision and must-check fields are
data, versioned like the review policy (hard boundary 8). A pack without its own rule uses the
default one.
"""

from __future__ import annotations

import json
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
)

NonBlank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]
# Strict: a JSON boolean is not a rate or a target (true would silently become 1.0).
Rate = Annotated[float, Field(strict=True, ge=0.0, le=1.0, allow_inf_nan=False)]
Target = Annotated[float, Field(strict=True, gt=0.0, le=1.0, allow_inf_nan=False)]


class SpotCheckPolicyError(ValueError):
    """A fixed code, never file content or a local path."""

    code = "SPOT_CHECK_POLICY_INVALID"


class PackRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rate: Rate
    minimum: Annotated[int, Field(strict=True, ge=0)]
    target: Target
    must_check: list[NonBlank] = Field(default_factory=list)

    @field_validator("must_check")
    @classmethod
    def unique(cls, keys: list[str]) -> list[str]:
        if len(set(keys)) != len(keys):
            raise ValueError("a must-check field is listed once")
        return keys


class SpotCheckPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: NonBlank
    default: PackRule
    packs: dict[NonBlank, PackRule] = Field(default_factory=dict)

    def for_pack(self, pack_id: str) -> PackRule:
        return self.packs.get(pack_id, self.default)


def load_spot_check_policy(path: str | Path | None = None) -> SpotCheckPolicy:
    """Read a policy file; None reads the policy shipped with this package."""
    try:
        if path is None:
            text = files(__package__).joinpath("spot_check_policy.json").read_text(encoding="utf-8")
        else:
            text = Path(path).read_text(encoding="utf-8")
        data = json.loads(text)
        if isinstance(data, dict):
            data.pop("basis", None)  # provenance for maintainers; not part of the policy
        return SpotCheckPolicy.model_validate(data)
    except (OSError, ValueError, ValidationError):
        raise SpotCheckPolicyError(SpotCheckPolicyError.code) from None
