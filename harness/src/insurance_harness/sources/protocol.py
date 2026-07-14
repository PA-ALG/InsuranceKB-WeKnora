"""Document source protocol and all-or-nothing materialization runtime types."""

import hashlib
import json
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Protocol, TypeVar, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import SourceDocument


class MaterializationStage(StrEnum):
    DISCOVERY = "discovery"
    METADATA = "metadata"
    PARSE_STATE = "parse_state"
    DOWNLOAD = "download"
    INTEGRITY = "integrity"
    PAGE_PARSE = "page_parse"
    CHUNKS = "chunks"


class SourceMaterializationError(Exception):
    """Fail-closed materialization error with a reproducible dead-letter identity."""

    def __init__(
        self,
        message: str,
        *,
        stage: MaterializationStage,
        space_id: str | None = None,
        knowledge_id: str | None = None,
        source_id: str | None = None,
        source_revision: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.space_id = space_id
        self.knowledge_id = knowledge_id
        self.source_id = source_id
        self.source_revision = source_revision
        canonical = json.dumps(
            {
                "knowledge_id": knowledge_id,
                "revision": source_revision,
                "source_id": None if knowledge_id is not None else source_id,
                "space_id": space_id,
                "stage": stage.value,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        self.dead_letter_key = hashlib.sha256(canonical).hexdigest()


class MaterializedBatch(BaseModel):
    """Runtime pairing; local paths are immutable and never serialized."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    documents: tuple[SourceDocument, ...] = Field(min_length=1)
    local_paths: Mapping[str, Path] = Field(exclude=True)

    @field_validator("local_paths", mode="after")
    @classmethod
    def _freeze_paths(cls, value: Mapping[str, Path]) -> Mapping[str, Path]:
        return cast(Mapping[str, Path], MappingProxyType(dict(value)))

    @model_validator(mode="after")
    def _validate_path_identity(self) -> "MaterializedBatch":
        source_ids = [document.source_id for document in self.documents]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("documents contain duplicate source_id values")
        if set(self.local_paths) != set(source_ids):
            raise ValueError("local_paths keys must exactly match document source_id values")
        return self


RequestT = TypeVar("RequestT", bound=BaseModel, contravariant=True)


@runtime_checkable
class DocumentSource(Protocol[RequestT]):
    """A source yielding a complete runtime batch through an async context."""

    def materialize(
        self,
        request: RequestT,
    ) -> AbstractAsyncContextManager[MaterializedBatch]: ...
