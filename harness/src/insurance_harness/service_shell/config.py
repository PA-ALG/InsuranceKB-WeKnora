"""Single typed `WIKI_` configuration authority for both P3 process roles."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any, cast

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from insurance_harness.jobs import JobRuntimeConfig


class ShellConfigError(Exception):
    """Sanitized aggregate startup refusal; values are deliberately omitted."""

    code = "invalid_shell_config"

    def __init__(self, keys: tuple[str, ...]) -> None:
        self.keys = tuple(sorted(set(keys)))
        super().__init__("invalid or missing configuration keys: " + ", ".join(self.keys))


class ShellSettings(BaseSettings):
    """Immutable configuration shared by `wiki-api` and `wiki-worker`."""

    model_config = SettingsConfigDict(
        env_prefix="WIKI_",
        env_file=None,
        extra="ignore",
        frozen=True,
    )

    postgres_dsn: SecretStr
    principal_records_json: SecretStr = SecretStr("{}")
    principal_space_ids: tuple[str, ...] = ()
    worker_id: str | None = None
    worker_space_ids: tuple[str, ...] = ()
    worker_local_concurrency: int = Field(default=1, ge=1)
    claim_poll_interval_seconds: float = Field(default=1.0, gt=0)
    heartbeat_interval_seconds: float = Field(default=10.0, gt=0)
    lease_seconds: float = Field(default=30.0, gt=0)
    transient_backoff_seconds: tuple[float, ...] = (0.25, 1.0, 5.0)
    job_max_attempts: int = Field(default=3, ge=1)
    job_backoff_seconds: tuple[float, ...] = (1.0, 5.0, 30.0)
    job_per_space_concurrency_limit: int = Field(default=8, ge=1)
    job_global_concurrency_limit: int = Field(default=32, ge=1)
    job_maintenance_batch_size: int = Field(default=128, ge=1)
    readiness_timeout_seconds: float = Field(default=2.0, gt=0)
    readiness_freshness_seconds: float = Field(default=1.0, ge=0)
    drain_deadline_seconds: float = Field(default=30.0, gt=0)
    total_shutdown_timeout_seconds: float = Field(default=35.0, gt=0)
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    worker_probe_host: str = "0.0.0.0"
    worker_probe_port: int = Field(default=8001, ge=1, le=65535)

    @field_validator("postgres_dsn")
    @classmethod
    def validate_postgres_dsn(cls, value: SecretStr) -> SecretStr:
        dsn = value.get_secret_value()
        if not (
            dsn.startswith("postgresql+psycopg://")
            or dsn.startswith("postgresql://")
        ):
            raise ValueError("postgres_dsn must use PostgreSQL")
        return value

    @model_validator(mode="after")
    def validate_cross_field_contracts(self) -> ShellSettings:
        if self.heartbeat_interval_seconds >= self.lease_seconds:
            raise ValueError(
                "heartbeat_interval_seconds must be strictly less than lease_seconds"
            )
        if self.total_shutdown_timeout_seconds < self.drain_deadline_seconds:
            raise ValueError(
                "total_shutdown_timeout_seconds must be >= drain_deadline_seconds"
            )
        if not self.transient_backoff_seconds or any(
            delay <= 0 for delay in self.transient_backoff_seconds
        ):
            raise ValueError("transient_backoff_seconds entries must be > 0")
        if not self.job_backoff_seconds or any(
            delay < 0 for delay in self.job_backoff_seconds
        ):
            raise ValueError("job_backoff_seconds entries must be >= 0")
        if self.worker_id is not None and (
            not self.worker_id or "\x00" in self.worker_id
        ):
            raise ValueError("worker_id must be non-empty and contain no NUL")
        if any(not space_id or "\x00" in space_id for space_id in self.principal_space_ids):
            raise ValueError(
                "principal_space_ids entries must be non-empty and contain no NUL"
            )
        if any(not space_id or "\x00" in space_id for space_id in self.worker_space_ids):
            raise ValueError("worker_space_ids entries must be non-empty and contain no NUL")
        return self

    def principal_records(self) -> Mapping[str, Mapping[str, Any]]:
        """Parse secret static bindings without ever embedding their values in errors."""
        try:
            value = json.loads(self.principal_records_json.get_secret_value())
            if not isinstance(value, dict):
                raise TypeError
            records: dict[str, Mapping[str, Any]] = {}
            for credential, record in value.items():
                if not isinstance(credential, str) or not isinstance(record, dict):
                    raise TypeError
                records[credential] = record
            return records
        except (json.JSONDecodeError, TypeError, ValueError) as error:
            raise ShellConfigError(("principal_records_json",)) from error

    def job_runtime_config(self) -> JobRuntimeConfig:
        """Build the P1 configuration without duplicating any P1 transition logic."""
        return JobRuntimeConfig(
            lease_seconds=self.lease_seconds,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            max_attempts=self.job_max_attempts,
            backoff_seconds=self.job_backoff_seconds,
            per_space_concurrency_limit=self.job_per_space_concurrency_limit,
            global_concurrency_limit=self.job_global_concurrency_limit,
            maintenance_batch_size=self.job_maintenance_batch_size,
        )


def load_settings() -> ShellSettings:
    """Load the one environment-backed model and sanitize aggregate validation output."""
    try:
        settings_loader = cast(Callable[[], ShellSettings], ShellSettings)
        return settings_loader()
    except ValidationError as error:
        keys: list[str] = []
        for item in error.errors(include_input=False):
            location = item.get("loc", ())
            if location:
                keys.append(str(location[0]))
            else:
                message = str(item.get("msg", ""))
                for field in ShellSettings.model_fields:
                    if field in message:
                        keys.append(field)
        raise ShellConfigError(tuple(keys or ("shell_settings",))) from error
