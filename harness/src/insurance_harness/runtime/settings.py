"""Package-local immutable resource caps for the OpenSpec 028 runtime."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from insurance_harness.runtime.models import _ImmutableModel

WorkerCount = Annotated[int, Field(strict=True, ge=2, le=4)]
AttemptCount = Annotated[int, Field(strict=True, ge=1, le=8)]
TimeoutSeconds = Annotated[int, Field(strict=True, ge=1, le=3600)]
AttemptTokenCap = Annotated[int, Field(strict=True, ge=1, le=65536)]
JobTokenCap = Annotated[int, Field(strict=True, ge=1, le=524288)]


class RuntimeSettings(_ImmutableModel):
    """Non-authority caps injected by a future composition root."""

    worker_count: WorkerCount
    max_attempts_per_stage: AttemptCount
    stage_timeout_seconds: TimeoutSeconds
    max_tokens_per_attempt: AttemptTokenCap
    max_tokens_per_job: JobTokenCap

    @model_validator(mode="after")
    def require_job_cap_to_cover_attempt(self) -> RuntimeSettings:
        if self.max_tokens_per_job < self.max_tokens_per_attempt:
            raise ValueError("job token cap must cover one attempt")
        if self.max_tokens_per_job > (
            self.max_attempts_per_stage * self.max_tokens_per_attempt
        ):
            raise ValueError("job token cap exceeds attempt budget")
        return self
