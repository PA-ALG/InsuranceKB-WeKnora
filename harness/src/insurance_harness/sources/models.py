"""Immutable, serializable source DTOs (OpenSpec 017 B2)."""

import hashlib
import hmac
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC
from types import MappingProxyType
from typing import Any, cast

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    is_database_bound_scope,
)
from insurance_harness.goldenset.pdf import PageText

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_SCOPE_CONTEXT_KEY = "insurance_harness_source_scope_attestation"
_SOURCE_SCOPE_TOKEN = object()


def _non_empty(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value must not be empty")
    return normalized


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("metadata object keys must be strings")
            frozen[key] = _freeze_json(item)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("metadata numbers must be finite")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"metadata value is not JSON-serializable: {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


class SourceScope(BaseModel):
    """Serializable projection of an attested runtime scope."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    space_id: str
    tenant_id: str
    raw_kb_id: str
    wiki_kb_id: str

    _validate_identifiers = field_validator(
        "space_id", "tenant_id", "raw_kb_id", "wiki_kb_id"
    )(_non_empty)

    @model_validator(mode="before")
    @classmethod
    def _require_attested_factory(cls, value: Any, info: ValidationInfo) -> Any:
        context = info.context or {}
        if context.get(_SOURCE_SCOPE_CONTEXT_KEY) is not _SOURCE_SCOPE_TOKEN:
            raise ValueError("SourceScope requires an attested KnowledgeScope")
        return value

    @classmethod
    def from_knowledge_scope(cls, scope: KnowledgeScope) -> "SourceScope":
        """Project a database-attested 016 capability into serializable audit IDs."""
        if not is_database_bound_scope(scope):
            raise ScopeViolation("scope mismatch")
        return cls.model_validate(
            {
                "space_id": scope.space_id,
                "tenant_id": scope.tenant_id,
                "raw_kb_id": scope.raw_kb_id,
                "wiki_kb_id": scope.wiki_kb_id,
            },
            context={_SOURCE_SCOPE_CONTEXT_KEY: _SOURCE_SCOPE_TOKEN},
        )


class SourceRevision(BaseModel):
    """Canonical source revision derived exclusively from its three inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_hash: str
    processed_at: AwareDatetime
    parser_fingerprint: str
    value: str = ""

    _validate_components = field_validator("file_hash", "parser_fingerprint")(_non_empty)

    @model_validator(mode="after")
    def _normalize_and_derive(self) -> "SourceRevision":
        processed_at = self.processed_at.astimezone(UTC)
        canonical = json.dumps(
            {
                "file_hash": self.file_hash,
                "parser_fingerprint": self.parser_fingerprint,
                "processed_at": processed_at.isoformat().replace("+00:00", "Z"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        expected = hashlib.sha256(canonical).hexdigest()
        if self.value and not hmac.compare_digest(self.value, expected):
            raise ValueError("source revision mismatch")
        object.__setattr__(self, "processed_at", processed_at)
        object.__setattr__(self, "value", expected)
        return self


class SourceChunk(BaseModel):
    """Immutable upstream chunk with recursively frozen metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    chunk_index: StrictInt | None = None
    start_at: StrictInt | None = None
    end_at: StrictInt | None = None
    content: str
    content_hash: str = ""
    metadata: Mapping[str, Any] = Field(default_factory=dict)

    _validate_chunk_id = field_validator("chunk_id")(_non_empty)

    @field_validator("chunk_index", "start_at", "end_at")
    @classmethod
    def _non_negative_offsets(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("chunk offsets must be non-negative")
        return value

    @model_validator(mode="after")
    def _ordered_offsets(self) -> "SourceChunk":
        if (
            self.start_at is not None
            and self.end_at is not None
            and self.start_at > self.end_at
        ):
            raise ValueError("start_at must not exceed end_at")
        return self

    @field_validator("metadata", mode="before")
    @classmethod
    def _validate_metadata_input(cls, value: Any) -> Any:
        return _freeze_json(value)

    @field_validator("metadata", mode="after")
    @classmethod
    def _freeze_metadata(cls, value: Mapping[str, Any]) -> Mapping[str, Any]:
        return cast(Mapping[str, Any], _freeze_json(value))

    @field_serializer("metadata")
    def _serialize_metadata(self, value: Mapping[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], _thaw_json(value))


class SourceDocument(BaseModel):
    """Complete immutable source identity, pages and chunks; never a local path."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    scope: SourceScope | None
    knowledge_id: str | None
    raw_kb_id: str | None
    title: str
    file_name: str
    file_type: str
    source_revision: SourceRevision
    original_digest: str
    pages: tuple[PageText, ...] = Field(min_length=1)
    chunks: tuple[SourceChunk, ...] = ()

    _validate_source_id = field_validator("source_id", "file_name", "file_type")(_non_empty)

    @field_validator("original_digest")
    @classmethod
    def _validate_original_digest(cls, value: str) -> str:
        normalized = value.lower()
        if _SHA256_RE.fullmatch(normalized) is None:
            raise ValueError("original_digest must be a SHA-256 hex digest")
        return normalized

    @model_validator(mode="after")
    def _validate_scope_identity(self) -> "SourceDocument":
        page_numbers = [page.page_no for page in self.pages]
        if any(type(number) is not int for number in page_numbers) or page_numbers != list(
            range(1, len(self.pages) + 1)
        ):
            raise ValueError("pages must use contiguous one-based page numbers")
        chunk_ids = [chunk.chunk_id for chunk in self.chunks]
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("chunks contain duplicate chunk_id values")
        if self.scope is None:
            if self.knowledge_id is not None or self.raw_kb_id is not None:
                raise ValueError("unscoped source cannot carry WeKnora identity")
        elif (
            not self.knowledge_id
            or not self.raw_kb_id
            or self.raw_kb_id != self.scope.raw_kb_id
        ):
            raise ValueError("scoped source identity mismatch")
        return self
