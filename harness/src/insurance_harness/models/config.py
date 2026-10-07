"""Strict, immutable stage policy; credentials stay outside configuration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from .errors import ModelConfigError

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class StageModelConfig(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="forbid", strict=True, allow_inf_nan=False, hide_input_in_errors=True,
    )

    stage: NonBlank
    provider: NonBlank
    base_url: str
    model: NonBlank
    api_key_env: str
    max_tokens: int = Field(gt=0)
    temperature: float = Field(default=0.0, ge=0, le=2)
    timeout_s: float = Field(default=180.0, gt=0)
    max_attempts: int = Field(default=3, ge=1, le=5)
    max_input_chars: int | None = Field(default=None, gt=0)
    thinking: Literal["enabled", "disabled"] | None = None
    response_format: Literal["json_object"] | None = None
    policy_version: NonBlank

    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        try:
            url = httpx.URL(value)
        except httpx.InvalidURL:
            raise ValueError("invalid endpoint") from None
        if (
            url.scheme != "https" or not url.host or url.userinfo or url.query or url.fragment
            or any(char.isspace() for char in value)
        ):
            raise ValueError("endpoint must be credential-free HTTPS")
        return value

    @field_validator("api_key_env")
    @classmethod
    def validate_env_name(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", value):
            raise ValueError("invalid environment variable name")
        return value


class _StageFile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    stages: list[StageModelConfig]


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def load_stage_config(path: Path, stage: str) -> StageModelConfig:
    """Validate the whole file, including unselected stages; never echo its contents."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
        entries = _StageFile.model_validate(raw).stages
        by_stage = {entry.stage: entry for entry in entries}
        if len(by_stage) != len(entries) or stage not in by_stage:
            raise ValueError("stage selection is not unique")
    except (OSError, ValueError):
        raise ModelConfigError("config_error") from None
    return by_stage[stage]
