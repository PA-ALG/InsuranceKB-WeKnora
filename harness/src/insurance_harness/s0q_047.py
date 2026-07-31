"""Bounded OpenSpec 047 S0-Q falsification helpers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import asdict
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeInt,
    PositiveInt,
    ValidationError,
    field_validator,
    model_validator,
)

from insurance_harness.adapters.weknora.admin_client import (
    AdminSession,
    TenantAPIKey,
    W1ChunkListing,
    W1RevisionDescriptor,
)
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.sources.models import (
    GenerationOrdering,
    SourceChunk,
    SourceDocument,
    SourceRevision,
)
from insurance_harness.sources.protocol import MaterializedBatch

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UNKNOWN_IDENTITY = "unknown"


class S0QErrorBucket(StrEnum):
    INPUT_INTEGRITY = "input_integrity"
    CANDIDATE_REGION = "candidate_region"
    PRODUCT_VERSION = "product_version"
    EXTRACTION = "extraction"
    NORMALIZATION = "normalization"
    COMPARATOR = "comparator"
    EVIDENCE_VERIFIER = "evidence_verifier"
    ABSTENTION = "abstention"


class S0QBlockedOnInput(ValueError):
    """Typed fail-closed result before provider admission."""

    status = "BLOCKED_ON_INPUT"

    def __init__(self, reason: str, *, bucket: S0QErrorBucket) -> None:
        self.reason = reason
        self.bucket = bucket
        super().__init__(f"{self.status}: {reason}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON-compatible value with stable mapping order."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _nonempty(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be empty")
    return value


def _sha256(value: str) -> str:
    if _SHA256_RE.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 digest")
    return value


class FrozenParserIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    app_version: str
    app_commit: str
    docreader: str
    parser_engine: str
    chunk_size: PositiveInt
    chunk_overlap: NonNegativeInt
    separators_digest: str
    chunker_config_digest: str
    embedding_model_id: str

    _text = field_validator(
        "app_version",
        "app_commit",
        "docreader",
        "parser_engine",
        "embedding_model_id",
    )(_nonempty)
    _digest = field_validator(
        "separators_digest",
        "chunker_config_digest",
    )(_sha256)


class FrozenW1Manifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm: Literal["weknora.chunk_manifest.v1"]
    digest: str
    chunk_count: NonNegativeInt

    _digest = field_validator("digest")(_sha256)


class FrozenW1Chunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    knowledge_id: str
    parse_attempt: PositiveInt
    chunk_index: NonNegativeInt
    content: str
    start_at: NonNegativeInt
    end_at: NonNegativeInt
    page_number: PositiveInt
    structural_type: Literal["text", "table", "mixed", "unknown"]

    _identity = field_validator("id", "knowledge_id")(_nonempty)

    @model_validator(mode="after")
    def _ordered_offsets(self) -> FrozenW1Chunk:
        if self.start_at > self.end_at:
            raise ValueError("chunk offsets are reversed")
        return self


class FrozenW1Anchor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page_number: PositiveInt
    chunk_id: str
    quote: str
    structural_type: Literal["text", "table", "mixed"]

    _text = field_validator("chunk_id", "quote")(_nonempty)


def recompute_w1_manifest(
    knowledge_id: str,
    parse_attempt: int,
    chunks: tuple[FrozenW1Chunk, ...],
) -> str:
    input_bytes = bytearray()
    input_bytes.extend(b"weknora.chunk_manifest\nv1\n")
    input_bytes.extend(knowledge_id.encode("utf-8"))
    input_bytes.extend(b"\n")
    input_bytes.extend(str(parse_attempt).encode("ascii"))
    input_bytes.extend(b"\n")
    input_bytes.extend(str(len(chunks)).encode("ascii"))
    input_bytes.extend(b"\n")
    for chunk in chunks:
        content_digest = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        input_bytes.extend(
            (
                f"{chunk.chunk_index}:{chunk.id}:{content_digest}\n"
            ).encode()
        )
    return hashlib.sha256(input_bytes).hexdigest()


class FrozenW1Bundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_kind: Literal["weknora_w1_exact_revision"]
    capture_state: Literal["completed"]
    text_origin: Literal["w1_exact_attempt_chunks"]
    source_path: str
    source_bytes: PositiveInt
    source_sha256: str
    knowledge_id: str
    parse_attempt: PositiveInt
    parser_identity: FrozenParserIdentity
    completed_at: str
    manifest: FrozenW1Manifest
    chunks: tuple[FrozenW1Chunk, ...] = Field(min_length=1)
    anchors: tuple[FrozenW1Anchor, ...] = Field(min_length=1)
    bundle_digest: str = ""

    _identity = field_validator(
        "source_path",
        "knowledge_id",
        "completed_at",
    )(_nonempty)
    _source_digest = field_validator("source_sha256")(_sha256)

    @model_validator(mode="after")
    def _validate_bundle(self) -> FrozenW1Bundle:
        indexes = [chunk.chunk_index for chunk in self.chunks]
        if indexes != sorted(indexes) or len(indexes) != len(set(indexes)):
            raise ValueError("chunk order must be strict ascending")
        if any(
            chunk.knowledge_id != self.knowledge_id
            or chunk.parse_attempt != self.parse_attempt
            for chunk in self.chunks
        ):
            raise ValueError("chunk identity does not match exact revision")
        page_numbers = [chunk.page_number for chunk in self.chunks]
        if page_numbers != sorted(page_numbers):
            raise ValueError("chunk page order must be nondecreasing")
        if self.manifest.chunk_count != len(self.chunks):
            raise ValueError("manifest chunk count does not match chunks")
        if (
            recompute_w1_manifest(
                self.knowledge_id,
                self.parse_attempt,
                self.chunks,
            )
            != self.manifest.digest
        ):
            raise ValueError("manifest digest does not match chunks")

        chunks_by_id = {chunk.id: chunk for chunk in self.chunks}
        if len(chunks_by_id) != len(self.chunks):
            raise ValueError("chunk identities must be unique")
        for anchor in self.anchors:
            chunk = chunks_by_id.get(anchor.chunk_id)
            if (
                chunk is None
                or chunk.page_number != anchor.page_number
                or anchor.quote not in chunk.content
                or (
                    anchor.structural_type == "table"
                    and chunk.structural_type not in {"table", "mixed"}
                )
                or (
                    anchor.structural_type == "text"
                    and chunk.structural_type not in {"text", "mixed"}
                )
            ):
                raise ValueError("anchor does not match frozen chunk content")

        canonical = self.model_dump(
            mode="json",
            exclude={"bundle_digest"},
        )
        expected_digest = canonical_sha256(canonical)
        if self.bundle_digest and self.bundle_digest != expected_digest:
            raise ValueError("bundle digest does not match canonical content")
        object.__setattr__(self, "bundle_digest", expected_digest)
        return self


def _validation_reason(error: ValidationError) -> str:
    locations = [tuple(item["loc"]) for item in error.errors()]
    if any(location and location[0] == "parser_identity" for location in locations):
        return "parser identity is incomplete"
    messages = " ".join(item["msg"] for item in error.errors())
    for marker in (
        "manifest digest",
        "chunk order",
        "chunk page order",
        "anchor",
        "bundle digest",
    ):
        if marker in messages:
            return messages
    return f"bundle schema is invalid: {messages}"


def admit_frozen_w1_bundle(
    payload: Any,
    *,
    expected_source_path: str,
    expected_source_sha256: str,
    required_table_page: int | None = None,
) -> FrozenW1Bundle:
    try:
        bundle = FrozenW1Bundle.model_validate(payload)
    except ValidationError as exc:
        raise S0QBlockedOnInput(
            _validation_reason(exc),
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        ) from None

    if (
        bundle.source_path != expected_source_path
        or bundle.source_sha256 != expected_source_sha256
    ):
        raise S0QBlockedOnInput(
            "source identity does not match the Mission Card",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    identity_values = (
        bundle.parser_identity.app_version,
        bundle.parser_identity.app_commit,
        bundle.parser_identity.docreader,
        bundle.parser_identity.parser_engine,
        bundle.parser_identity.embedding_model_id,
    )
    if any(value == _UNKNOWN_IDENTITY for value in identity_values):
        raise S0QBlockedOnInput(
            "parser identity contains an unknown component",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    if required_table_page is not None and not any(
        anchor.page_number == required_table_page
        and anchor.structural_type in {"table", "mixed"}
        for anchor in bundle.anchors
    ):
        raise S0QBlockedOnInput(
            f"required table anchor is missing for page {required_table_page}",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    if required_table_page is not None:
        raise S0QBlockedOnInput(
            "W1 exact revision does not bind a table structure digest",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    return bundle


class FrozenW1SourceRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_paths: tuple[Path, ...] = Field(min_length=2, max_length=2)

    @field_validator("bundle_paths")
    @classmethod
    def _unique_json_paths(cls, value: tuple[Path, ...]) -> tuple[Path, ...]:
        if (
            len(value) != len(set(value))
            or any(path.suffix.lower() != ".json" for path in value)
        ):
            raise ValueError("bundle_paths must be unique JSON files")
        return value


class FrozenW1DocumentSource:
    """Offline source backed only by admitted W1 exact-attempt bundles."""

    def __init__(
        self,
        *,
        expected_sources: Mapping[str, str],
        required_table_pages: Mapping[str, int | None],
    ) -> None:
        self._expected_sources = dict(expected_sources)
        self._required_table_pages = dict(required_table_pages)
        if (
            len(self._expected_sources) != 2
            or set(self._required_table_pages) != set(self._expected_sources)
            or sum(
                page is not None
                for page in self._required_table_pages.values()
            )
            != 1
            or any(
                not path
                or _SHA256_RE.fullmatch(digest) is None
                for path, digest in self._expected_sources.items()
            )
        ):
            raise ValueError(
                "invalid frozen W1 source admission profile: exactly one "
                "complex-table source is required"
            )

    @asynccontextmanager
    async def materialize(
        self,
        request: FrozenW1SourceRequest,
    ) -> AsyncIterator[MaterializedBatch]:
        documents: list[SourceDocument] = []
        local_paths: dict[str, Path] = {}
        seen_sources: set[str] = set()
        for bundle_path in request.bundle_paths:
            try:
                payload = json.loads(bundle_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                raise S0QBlockedOnInput(
                    "frozen bundle file is unreadable",
                    bucket=S0QErrorBucket.INPUT_INTEGRITY,
                ) from None
            source_path = (
                payload.get("source_path")
                if isinstance(payload, Mapping)
                else None
            )
            if (
                not isinstance(source_path, str)
                or source_path in seen_sources
                or source_path not in self._expected_sources
            ):
                raise S0QBlockedOnInput(
                    "frozen bundle source is outside the admitted input set",
                    bucket=S0QErrorBucket.INPUT_INTEGRITY,
                )
            bundle = admit_frozen_w1_bundle(
                payload,
                expected_source_path=source_path,
                expected_source_sha256=self._expected_sources[source_path],
                required_table_page=self._required_table_pages[source_path],
            )
            document = _source_document(bundle)
            documents.append(document)
            local_paths[document.source_id] = bundle_path
            seen_sources.add(source_path)
        if seen_sources != set(self._expected_sources):
            raise S0QBlockedOnInput(
                "frozen bundle set does not contain the exact two sources",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )
        yield MaterializedBatch(
            documents=tuple(documents),
            local_paths=local_paths,
        )


def _source_document(bundle: FrozenW1Bundle) -> SourceDocument:
    page_content: dict[int, list[str]] = {}
    chunks: list[SourceChunk] = []
    for chunk in bundle.chunks:
        page_content.setdefault(chunk.page_number, []).append(chunk.content)
        chunks.append(
            SourceChunk(
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                start_at=chunk.start_at,
                end_at=chunk.end_at,
                content=chunk.content,
                content_hash=hashlib.sha256(chunk.content.encode()).hexdigest(),
                metadata={
                    "w1_knowledge_id": bundle.knowledge_id,
                    "parse_attempt": bundle.parse_attempt,
                    "page_number": chunk.page_number,
                    "structural_type": chunk.structural_type,
                },
            )
        )
    max_page = max(page_content)
    pages = tuple(
        PageText(
            page_no=page_number,
            text="\n".join(page_content.get(page_number, ())),
        )
        for page_number in range(1, max_page + 1)
    )
    parser_fingerprint = canonical_sha256(bundle.parser_identity)
    source_revision = SourceRevision(
        file_hash=bundle.source_sha256,
        ordering=GenerationOrdering(value=bundle.parse_attempt),
        parser_fingerprint=parser_fingerprint,
    )
    file_name = Path(bundle.source_path).name
    return SourceDocument(
        source_id=(
            f"weknora-w1:{bundle.knowledge_id}:"
            f"{bundle.parse_attempt}:{bundle.bundle_digest}"
        ),
        scope=None,
        knowledge_id=None,
        raw_kb_id=None,
        title=Path(file_name).stem,
        file_name=file_name,
        file_type="pdf",
        source_revision=source_revision,
        original_digest=bundle.source_sha256,
        pages=pages,
        chunks=tuple(chunks),
    )


class S0QCaptureSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_path: str
    source_bytes: PositiveInt
    source_sha256: str
    artifact_name: Literal["terms-w1.json", "brochure-w1.json"]
    required_anchor_page: PositiveInt
    required_anchor_quote: str
    required_anchor_structural_type: Literal["text", "table"]

    _text = field_validator("source_path", "required_anchor_quote")(_nonempty)
    _digest = field_validator("source_sha256")(_sha256)

    @model_validator(mode="after")
    def _safe_relative_path(self) -> S0QCaptureSource:
        path = Path(self.source_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("capture source path must be repository-relative")
        return self


class S0QCaptureClient(Protocol):
    async def create_knowledge_base(
        self,
        credential: AdminSession,
        documented_payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    async def create_tenant_api_key(
        self,
        session: AdminSession,
        *,
        tenant_id: int,
        name: str,
        knowledge_base_ids: tuple[str, ...],
    ) -> TenantAPIKey: ...

    async def upload_file(
        self,
        api_key: Any,
        kb_id: str,
        path: Path,
        *,
        metadata: dict[str, str],
    ) -> dict[str, Any]: ...

    async def get_knowledge(
        self,
        api_key: Any,
        knowledge_id: str,
    ) -> dict[str, Any]: ...

    async def get_knowledge_revision(
        self,
        api_key: Any,
        knowledge_id: str,
    ) -> W1RevisionDescriptor: ...

    async def list_knowledge_revision_chunks(
        self,
        api_key: Any,
        knowledge_id: str,
        *,
        parse_attempt: int,
        page_size: int,
    ) -> W1ChunkListing: ...

    async def delete_tenant_api_key(
        self,
        session: AdminSession,
        *,
        tenant_id: int,
        key_id: int,
    ) -> None: ...

    async def delete_knowledge_base(
        self,
        credential: AdminSession,
        kb_id: str,
    ) -> None: ...


_EXISTING_GET_ALLOWLIST = (
    "knowledge_get",
    "revision_get",
    "revision_chunks_get",
)
_LOCATOR_FIELD_NAMES = frozenset(
    {
        "bbox",
        "block",
        "block_id",
        "block_index",
        "cell",
        "cell_id",
        "chunk_type",
        "column",
        "element_type",
        "locator",
        "page",
        "page_no",
        "page_number",
        "row",
        "span",
        "structural_type",
        "table",
        "table_cell",
        "table_id",
    }
)
_SAFE_SHAPE_KEYS = frozenset(
    {
        *_LOCATOR_FIELD_NAMES,
        "cell",
        "cells",
        "chunk_index",
        "content",
        "cross-page",
        "cross_page",
        "file_sha256",
        "header",
        "headers",
        "id",
        "knowledge_base_id",
        "knowledge_id",
        "labels",
        "metadata",
        "parse_attempt",
        "parse_status",
        "rows",
        "space_id",
        "spans",
        "tenant_id",
        "current_parse_attempt",
    }
)


class S0QExistingScope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    tenant_id: PositiveInt
    space_id: str
    raw_kb_id: str

    _identity = field_validator("space_id", "raw_kb_id")(_nonempty)


class S0QExistingSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_path: str
    source_bytes: PositiveInt
    source_sha256: str
    knowledge_id: str

    _identity = field_validator("source_path", "knowledge_id")(_nonempty)
    _digest = field_validator("source_sha256")(_sha256)

    @model_validator(mode="after")
    def _safe_relative_path(self) -> S0QExistingSource:
        path = Path(self.source_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("existing source path must be repository-relative")
        return self


class S0QExistingReadClient(Protocol):
    method_allowlist: tuple[str, ...]
    bound_scope: S0QExistingScope

    async def get_knowledge(
        self,
        api_key: Any,
        knowledge_id: str,
    ) -> dict[str, Any]: ...

    async def get_knowledge_revision(
        self,
        api_key: Any,
        knowledge_id: str,
    ) -> W1RevisionDescriptor: ...

    async def list_knowledge_revision_chunks(
        self,
        api_key: Any,
        knowledge_id: str,
        *,
        parse_attempt: int,
        page_size: int,
    ) -> W1ChunkListing: ...


def _shape_rows(value: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    pending: list[tuple[str, Any]] = [("$", value)]
    while pending:
        path, current = pending.pop()
        if len(rows) + len(pending) > 2048:
            raise S0QBlockedOnInput(
                "response shape exceeds the bounded evidence budget",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )
        if isinstance(current, Mapping):
            if not all(isinstance(key, str) for key in current):
                raise S0QBlockedOnInput(
                    "response shape contains a non-string key",
                    bucket=S0QErrorBucket.INPUT_INTEGRITY,
                )
            rows.append({"path": path, "type": "object"})
            safe_keys = sorted(
                (key for key in current if key in _SAFE_SHAPE_KEYS),
                reverse=True,
            )
            unknown_values = [
                item for key, item in current.items() if key not in _SAFE_SHAPE_KEYS
            ]
            if unknown_values:
                unknown_types = sorted(
                    {
                        "object"
                        if isinstance(item, Mapping)
                        else "array"
                        if isinstance(item, (list, tuple))
                        else "null"
                        if item is None
                        else "bool"
                        if type(item) is bool
                        else "int"
                        if type(item) is int
                        else "float"
                        if type(item) is float
                        else "string"
                        if type(item) is str
                        else "unsupported"
                        for item in unknown_values
                    }
                )
                rows.append(
                    {
                        "path": f"{path}.<unknown>",
                        "type": (
                            f"members:{len(unknown_values)}:"
                            f"{','.join(unknown_types)}"
                        ),
                    }
                )
            for key in safe_keys:
                pending.append((f"{path}.{key}", current[key]))
        elif isinstance(current, (list, tuple)):
            rows.append({"path": path, "type": "array"})
            for index, item in reversed(tuple(enumerate(current))):
                pending.append((f"{path}[][{index}]", item))
        else:
            scalar_type = (
                "null"
                if current is None
                else "bool"
                if type(current) is bool
                else "int"
                if type(current) is int
                else "float"
                if type(current) is float
                else "string"
                if type(current) is str
                else "unsupported"
            )
            if scalar_type == "unsupported":
                raise S0QBlockedOnInput(
                    "response shape contains a non-JSON scalar",
                    bucket=S0QErrorBucket.INPUT_INTEGRITY,
                )
            rows.append({"path": path, "type": scalar_type})
    return sorted(rows, key=lambda row: (row["path"], row["type"]))


def _shape_evidence(
    knowledge: Mapping[str, Any],
    chunks: tuple[Mapping[str, Any], ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    knowledge_rows = _shape_rows(knowledge)
    chunk_rows = _shape_rows(chunks)
    all_rows = [*knowledge_rows, *chunk_rows]
    locator_rows = [
        row
        for row in all_rows
        if row["path"].rsplit(".", 1)[-1].split("[", 1)[0]
        in _LOCATOR_FIELD_NAMES
    ]
    metadata_rows = [
        row
        for row in all_rows
        if ".metadata" in row["path"] or ".labels" in row["path"]
    ]
    return (
        {
            "status": (
                "PRESENT_UNBOUND" if locator_rows else "ABSENT_INSUFFICIENT"
            ),
            "field_shape": locator_rows,
            "shape_digest": canonical_sha256(locator_rows),
        },
        {
            "field_shape": metadata_rows,
            "shape_digest": canonical_sha256(metadata_rows),
        },
    )


def _existing_manifest_digest(
    *,
    knowledge_id: str,
    parse_attempt: int,
    chunks: tuple[Mapping[str, Any], ...],
) -> str:
    lines = [
        "weknora.chunk_manifest",
        "v1",
        knowledge_id,
        str(parse_attempt),
        str(len(chunks)),
    ]
    previous_index = -1
    seen_ids: set[str] = set()
    for item in chunks:
        chunk_id = item.get("id")
        chunk_index = item.get("chunk_index")
        content = item.get("content")
        if (
            not isinstance(chunk_id, str)
            or not chunk_id
            or chunk_id in seen_ids
            or item.get("knowledge_id") != knowledge_id
            or item.get("parse_attempt") != parse_attempt
            or type(chunk_index) is not int
            or chunk_index != previous_index + 1
            or not isinstance(content, str)
        ):
            raise S0QBlockedOnInput(
                "revision chunks contain mixed attempt or incomplete identity",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )
        seen_ids.add(chunk_id)
        previous_index = chunk_index
        lines.append(
            f"{chunk_index}:{chunk_id}:"
            f"{hashlib.sha256(content.encode('utf-8')).hexdigest()}"
        )
    return hashlib.sha256(("\n".join(lines) + "\n").encode()).hexdigest()


def _validate_existing_knowledge(
    knowledge: Mapping[str, Any],
    *,
    scope: S0QExistingScope,
    source: S0QExistingSource,
) -> int:
    attempt = knowledge.get("current_parse_attempt")
    if (
        knowledge.get("id") != source.knowledge_id
        or knowledge.get("tenant_id") != scope.tenant_id
        or knowledge.get("knowledge_base_id") != scope.raw_kb_id
        or knowledge.get("parse_status") != "completed"
    ):
        raise S0QBlockedOnInput(
            "existing source scope drift",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    if knowledge.get("file_sha256") != source.source_sha256:
        raise S0QBlockedOnInput(
            "existing source SHA drift",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    if type(attempt) is not int or attempt < 1:
        raise S0QBlockedOnInput(
            "existing source current attempt is invalid",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    return attempt


def _knowledge_fence(
    knowledge: Mapping[str, Any],
) -> tuple[Any, ...]:
    return tuple(
        knowledge.get(key)
        for key in (
            "id",
            "tenant_id",
            "knowledge_base_id",
            "parse_status",
            "current_parse_attempt",
            "file_sha256",
        )
    )


def _validate_existing_revision(
    descriptor: W1RevisionDescriptor,
    *,
    source: S0QExistingSource,
    attempt: int,
) -> None:
    if (
        descriptor.knowledge_id != source.knowledge_id
        or descriptor.parse_attempt != attempt
        or descriptor.file_digest.algorithm != "sha256"
        or descriptor.file_digest.value != source.source_sha256
        or descriptor.chunk_manifest.algorithm
        != "weknora.chunk_manifest.v1"
    ):
        raise S0QBlockedOnInput(
            "existing revision identity drift",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )


async def capture_existing_w1_evidence(
    *,
    client: S0QExistingReadClient,
    api_key: Any,
    scope: S0QExistingScope,
    sources: tuple[S0QExistingSource, ...],
) -> dict[str, Any]:
    if (
        client.method_allowlist != _EXISTING_GET_ALLOWLIST
        or client.bound_scope != scope
    ):
        raise S0QBlockedOnInput(
            "capture-existing GET-only method allowlist or scope drift",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    if (
        len(sources) != 2
        or len({source.knowledge_id for source in sources}) != 2
        or len({source.source_path for source in sources}) != 2
        or len({source.source_sha256 for source in sources}) != 2
    ):
        raise S0QBlockedOnInput(
            "capture-existing requires exactly two distinct frozen sources",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )

    preflight: list[
        tuple[
            S0QExistingSource,
            Mapping[str, Any],
            int,
            W1RevisionDescriptor,
        ]
    ] = []
    for source in sources:
        before = await client.get_knowledge(api_key, source.knowledge_id)
        attempt = _validate_existing_knowledge(
            before,
            scope=scope,
            source=source,
        )
        descriptor = await client.get_knowledge_revision(
            api_key,
            source.knowledge_id,
        )
        _validate_existing_revision(
            descriptor,
            source=source,
            attempt=attempt,
        )
        preflight.append((source, before, attempt, descriptor))

    body_rows: list[
        tuple[
            S0QExistingSource,
            Mapping[str, Any],
            int,
            W1RevisionDescriptor,
            tuple[Mapping[str, Any], ...],
            str,
        ]
    ] = []
    for pre_source, pre_knowledge, pre_attempt, pre_descriptor in preflight:
        listing = await client.list_knowledge_revision_chunks(
            api_key,
            pre_source.knowledge_id,
            parse_attempt=pre_attempt,
            page_size=100,
        )
        if (
            listing.total != pre_descriptor.chunk_manifest.chunk_count
            or listing.revision.knowledge_id != pre_source.knowledge_id
            or listing.revision.parse_attempt != pre_attempt
            or listing.revision.chunk_count != listing.total
        ):
            raise S0QBlockedOnInput(
                "existing revision identity drift",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )
        chunks = tuple(listing.items)
        text_manifest_digest = _existing_manifest_digest(
            knowledge_id=pre_source.knowledge_id,
            parse_attempt=pre_attempt,
            chunks=chunks,
        )
        if (
            pre_descriptor.chunk_manifest.digest != text_manifest_digest
            or listing.revision.manifest_digest != text_manifest_digest
        ):
            raise S0QBlockedOnInput(
                "existing revision manifest drift",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )
        body_rows.append(
            (
                pre_source,
                pre_knowledge,
                pre_attempt,
                pre_descriptor,
                chunks,
                text_manifest_digest,
            )
        )

    for (
        post_source,
        pre_knowledge,
        pre_attempt,
        pre_descriptor,
        _,
        _,
    ) in body_rows:
        post_descriptor = await client.get_knowledge_revision(
            api_key,
            post_source.knowledge_id,
        )
        after = await client.get_knowledge(api_key, post_source.knowledge_id)
        after_attempt = _validate_existing_knowledge(
            after,
            scope=scope,
            source=post_source,
        )
        if after_attempt != pre_attempt:
            raise S0QBlockedOnInput(
                "existing source attempt drift",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )
        if _knowledge_fence(after) != _knowledge_fence(pre_knowledge):
            raise S0QBlockedOnInput(
                "existing source identity drift",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )
        if post_descriptor != pre_descriptor:
            raise S0QBlockedOnInput(
                "existing revision descriptor drift",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )

    evidence_sources: list[dict[str, Any]] = []
    for (
        evidence_source,
        evidence_knowledge,
        evidence_attempt,
        evidence_descriptor,
        evidence_chunks,
        evidence_manifest_digest,
    ) in body_rows:
        structure, metadata = _shape_evidence(
            evidence_knowledge,
            evidence_chunks,
        )
        knowledge_shape = _shape_rows(evidence_knowledge)
        chunk_shape = _shape_rows(evidence_chunks)
        parser_identity = asdict(evidence_descriptor.parser_identity)
        if any(
            isinstance(value, str) and Path(value).is_absolute()
            for value in parser_identity.values()
        ):
            raise S0QBlockedOnInput(
                "parser identity exposes an absolute path",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )
        evidence_sources.append(
            {
                "source_path": evidence_source.source_path,
                "source_bytes": evidence_source.source_bytes,
                "source_sha256": evidence_source.source_sha256,
                "knowledge_id": evidence_source.knowledge_id,
                "current_parse_attempt": evidence_attempt,
                "parser_identity": parser_identity,
                "revision_manifest": asdict(
                    evidence_descriptor.chunk_manifest
                ),
                "text_manifest": {
                    "algorithm": "weknora.chunk_manifest.v1",
                    "digest": evidence_manifest_digest,
                    "chunk_count": len(evidence_chunks),
                },
                "knowledge_shape": knowledge_shape,
                "knowledge_shape_digest": canonical_sha256(knowledge_shape),
                "chunk_shape": chunk_shape,
                "chunk_shape_digest": canonical_sha256(chunk_shape),
                "structure_evidence": structure,
                "metadata_evidence": metadata,
            }
        )

    body = {
        "artifact_kind": "s0q_047_existing_source_evidence",
        "status": "W1_STRUCTURE_EVIDENCE_INSUFFICIENT",
        "scope": scope.model_dump(mode="json"),
        "client_method_allowlist": list(_EXISTING_GET_ALLOWLIST),
        "sources": evidence_sources,
        "admitted_bundle": None,
        "revision_or_manifest_writes": 0,
        "harness_model_provider_calls": 0,
    }
    return {**body, "report_digest": canonical_sha256(body)}


def _capture_preflight(
    *,
    source_root: Path,
    sources: tuple[S0QCaptureSource, ...],
    scratch_kb_payload: Mapping[str, Any],
) -> None:
    if (
        len(sources) != 2
        or {source.artifact_name for source in sources}
        != {"terms-w1.json", "brochure-w1.json"}
        or len({source.source_path for source in sources}) != 2
    ):
        raise S0QBlockedOnInput(
            "capture requires exactly the approved two-source profile",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    scratch_name = scratch_kb_payload.get("name")
    if (
        not isinstance(scratch_name, str)
        or not scratch_name.startswith("insurancekb-s0q-047-scratch-")
    ):
        raise S0QBlockedOnInput(
            "scratch knowledge-base identity is invalid",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    for source in sources:
        path = source_root / source.source_path
        try:
            content = path.read_bytes()
        except OSError:
            raise S0QBlockedOnInput(
                f"source is unreadable: {source.source_path}",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            ) from None
        if (
            len(content) != source.source_bytes
            or hashlib.sha256(content).hexdigest() != source.source_sha256
        ):
            raise S0QBlockedOnInput(
                f"source identity mismatch: {source.source_path}",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )


async def _wait_for_completed_knowledge(
    *,
    client: S0QCaptureClient,
    api_key: Any,
    knowledge_id: str,
    expected_sha256: str,
    poll_attempts: int,
    poll_interval_seconds: float,
) -> None:
    for poll in range(poll_attempts):
        knowledge = await client.get_knowledge(api_key, knowledge_id)
        status = knowledge.get("parse_status")
        if status == "completed":
            if knowledge.get("file_sha256") != expected_sha256:
                raise S0QBlockedOnInput(
                    "completed knowledge source digest does not match upload",
                    bucket=S0QErrorBucket.INPUT_INTEGRITY,
                )
            return
        if status in {"failed", "cancelled"}:
            raise S0QBlockedOnInput(
                f"WeKnora parsing ended with status {status}",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )
        if poll + 1 < poll_attempts and poll_interval_seconds > 0:
            await asyncio.sleep(poll_interval_seconds)
    raise S0QBlockedOnInput(
        "WeKnora parsing did not complete within the frozen poll budget",
        bucket=S0QErrorBucket.INPUT_INTEGRITY,
    )


def _page_number(item: Mapping[str, Any]) -> int:
    metadata = item.get("metadata")
    documents: tuple[Mapping[str, Any], ...] = (
        (metadata, item)
        if isinstance(metadata, Mapping)
        else (item,)
    )
    for document in documents:
        for key in ("page_number", "page_no", "page"):
            value = document.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                return value
    raise S0QBlockedOnInput(
        "W1 chunk page identity is not exposed",
        bucket=S0QErrorBucket.INPUT_INTEGRITY,
    )


def _structural_type(item: Mapping[str, Any]) -> str:
    metadata = item.get("metadata")
    documents: tuple[Mapping[str, Any], ...] = (
        (metadata, item)
        if isinstance(metadata, Mapping)
        else (item,)
    )
    for document in documents:
        for key in ("structural_type", "element_type", "type", "chunk_type"):
            value = document.get(key)
            if not isinstance(value, str):
                continue
            normalized = value.casefold()
            if "table" in normalized:
                return "table"
            if normalized in {"text", "paragraph"}:
                return "text"
    return "unknown"


def _capture_chunk(
    item: Mapping[str, Any],
    *,
    knowledge_id: str,
    parse_attempt: int,
) -> dict[str, Any]:
    chunk_id = item.get("id")
    chunk_index = item.get("chunk_index")
    content = item.get("content")
    start_at = item.get("start_at")
    end_at = item.get("end_at")
    if (
        not isinstance(chunk_id, str)
        or not chunk_id
        or item.get("knowledge_id") != knowledge_id
        or item.get("parse_attempt") != parse_attempt
        or not isinstance(chunk_index, int)
        or isinstance(chunk_index, bool)
        or chunk_index < 0
        or not isinstance(content, str)
        or not isinstance(start_at, int)
        or isinstance(start_at, bool)
        or start_at < 0
        or not isinstance(end_at, int)
        or isinstance(end_at, bool)
        or end_at < start_at
    ):
        raise S0QBlockedOnInput(
            "W1 chunk identity is incomplete",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    return {
        "id": chunk_id,
        "knowledge_id": knowledge_id,
        "parse_attempt": parse_attempt,
        "chunk_index": chunk_index,
        "content": content,
        "start_at": start_at,
        "end_at": end_at,
        "page_number": _page_number(item),
        "structural_type": _structural_type(item),
    }


def _capture_bundle(
    *,
    source: S0QCaptureSource,
    descriptor: W1RevisionDescriptor,
    listing: W1ChunkListing,
) -> FrozenW1Bundle:
    if (
        descriptor.file_digest.value != source.source_sha256
        or listing.revision.knowledge_id != descriptor.knowledge_id
        or listing.revision.parse_attempt != descriptor.parse_attempt
        or listing.revision.manifest_digest
        != descriptor.chunk_manifest.digest
        or listing.revision.chunk_count
        != descriptor.chunk_manifest.chunk_count
    ):
        raise S0QBlockedOnInput(
            "W1 descriptor and exact-attempt chunks disagree",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    chunks = tuple(
        _capture_chunk(
            item,
            knowledge_id=descriptor.knowledge_id,
            parse_attempt=descriptor.parse_attempt,
        )
        for item in listing.items
    )
    matching = [
        chunk
        for chunk in chunks
        if chunk["page_number"] == source.required_anchor_page
        and source.required_anchor_quote in chunk["content"]
    ]
    if not matching:
        raise S0QBlockedOnInput(
            f"required anchor quote is absent on page {source.required_anchor_page}",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    anchor_chunk = matching[0]
    if (
        source.required_anchor_structural_type == "table"
        and anchor_chunk["structural_type"] not in {"table", "mixed"}
    ):
        raise S0QBlockedOnInput(
            f"required table structure is not exposed on page "
            f"{source.required_anchor_page}",
            bucket=S0QErrorBucket.INPUT_INTEGRITY,
        )
    payload = {
        "artifact_kind": "weknora_w1_exact_revision",
        "capture_state": "completed",
        "text_origin": "w1_exact_attempt_chunks",
        "source_path": source.source_path,
        "source_bytes": source.source_bytes,
        "source_sha256": source.source_sha256,
        "knowledge_id": descriptor.knowledge_id,
        "parse_attempt": descriptor.parse_attempt,
        "parser_identity": asdict(descriptor.parser_identity),
        "completed_at": descriptor.completed_at,
        "manifest": asdict(descriptor.chunk_manifest),
        "chunks": chunks,
        "anchors": (
            {
                "page_number": source.required_anchor_page,
                "chunk_id": anchor_chunk["id"],
                "quote": source.required_anchor_quote,
                "structural_type": source.required_anchor_structural_type,
            },
        ),
    }
    return admit_frozen_w1_bundle(
        payload,
        expected_source_path=source.source_path,
        expected_source_sha256=source.source_sha256,
        required_table_page=(
            source.required_anchor_page
            if source.required_anchor_structural_type == "table"
            else None
        ),
    )


def _atomic_write_json(path: Path, value: Any) -> None:
    payload = canonical_json_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def write_s0q_capture_report(
    output_dir: Path,
    report: Mapping[str, Any],
) -> None:
    _atomic_write_json(output_dir / "input-capture-report.json", report)


def write_s0q_existing_evidence(
    output_dir: Path,
    report: Mapping[str, Any],
) -> None:
    _atomic_write_json(output_dir / "existing-source-evidence.json", report)


async def capture_s0q_w1_inputs(
    *,
    client: S0QCaptureClient,
    session: AdminSession,
    source_root: Path,
    output_dir: Path,
    sources: tuple[S0QCaptureSource, ...],
    scratch_kb_payload: dict[str, Any],
    poll_attempts: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    if (
        not isinstance(poll_attempts, int)
        or isinstance(poll_attempts, bool)
        or poll_attempts < 1
        or not isinstance(poll_interval_seconds, (int, float))
        or isinstance(poll_interval_seconds, bool)
        or poll_interval_seconds < 0
    ):
        raise ValueError("invalid capture poll budget")

    status = "ADMITTED"
    reason = ""
    bucket = ""
    scratch_kb_id: str | None = None
    scratch_key: TenantAPIKey | None = None
    knowledge_ids: list[str] = []
    bundles: dict[str, FrozenW1Bundle] = {}
    cleanup = {
        "api_key": "not_created",
        "knowledge_base": "not_created",
    }
    try:
        _capture_preflight(
            source_root=source_root,
            sources=sources,
            scratch_kb_payload=scratch_kb_payload,
        )
        created = await client.create_knowledge_base(
            session,
            scratch_kb_payload,
        )
        raw_kb_id = created.get("id")
        if not isinstance(raw_kb_id, str) or not raw_kb_id:
            raise S0QBlockedOnInput(
                "scratch knowledge-base response has no exact identity",
                bucket=S0QErrorBucket.INPUT_INTEGRITY,
            )
        scratch_kb_id = raw_kb_id
        scratch_key = await client.create_tenant_api_key(
            session,
            tenant_id=session.tenant_id,
            name="insurancekb-s0q-047-scratch-key",
            knowledge_base_ids=(scratch_kb_id,),
        )
        for source in sources:
            source_path = source_root / source.source_path
            upload = await client.upload_file(
                scratch_key.token,
                scratch_kb_id,
                source_path,
                metadata={
                    "owner": "s0q-047",
                    "sha256": source.source_sha256,
                },
            )
            knowledge_id = upload.get("id")
            if not isinstance(knowledge_id, str) or not knowledge_id:
                raise S0QBlockedOnInput(
                    "knowledge upload response has no exact identity",
                    bucket=S0QErrorBucket.INPUT_INTEGRITY,
                )
            knowledge_ids.append(knowledge_id)
            await _wait_for_completed_knowledge(
                client=client,
                api_key=scratch_key.token,
                knowledge_id=knowledge_id,
                expected_sha256=source.source_sha256,
                poll_attempts=poll_attempts,
                poll_interval_seconds=float(poll_interval_seconds),
            )
            descriptor = await client.get_knowledge_revision(
                scratch_key.token,
                knowledge_id,
            )
            listing = await client.list_knowledge_revision_chunks(
                scratch_key.token,
                knowledge_id,
                parse_attempt=descriptor.parse_attempt,
                page_size=100,
            )
            bundles[source.artifact_name] = _capture_bundle(
                source=source,
                descriptor=descriptor,
                listing=listing,
            )
    except S0QBlockedOnInput as exc:
        status = exc.status
        reason = exc.reason
        bucket = exc.bucket.value
    except Exception as exc:
        status = "BLOCKED_ON_INPUT"
        reason = f"capture failed closed at {type(exc).__name__}"
        bucket = S0QErrorBucket.INPUT_INTEGRITY.value
    finally:
        if scratch_key is not None:
            try:
                await client.delete_tenant_api_key(
                    session,
                    tenant_id=session.tenant_id,
                    key_id=scratch_key.id,
                )
                cleanup["api_key"] = "deleted"
            except Exception:
                cleanup["api_key"] = "delete_failed"
        if scratch_kb_id is not None:
            try:
                await client.delete_knowledge_base(session, scratch_kb_id)
                cleanup["knowledge_base"] = "deleted"
            except Exception:
                cleanup["knowledge_base"] = "delete_failed"

    if "delete_failed" in cleanup.values():
        status = "BLOCKED_ON_INPUT"
        reason = "scratch cleanup failed"
        bucket = S0QErrorBucket.INPUT_INTEGRITY.value
    if status == "ADMITTED" and len(bundles) != len(sources):
        status = "BLOCKED_ON_INPUT"
        reason = "capture did not produce the exact two-bundle set"
        bucket = S0QErrorBucket.INPUT_INTEGRITY.value

    manifest: dict[str, Any] | None = None
    if status == "ADMITTED":
        for name, bundle in bundles.items():
            _atomic_write_json(
                output_dir / name,
                bundle.model_dump(mode="json"),
            )
        manifest_body = {
            "artifact_kind": "s0q_047_input_manifest",
            "sources": [
                {
                    "artifact_name": source.artifact_name,
                    "source_path": source.source_path,
                    "source_sha256": source.source_sha256,
                    "bundle_digest": bundles[source.artifact_name].bundle_digest,
                }
                for source in sources
            ],
        }
        manifest = {
            **manifest_body,
            "manifest_digest": canonical_sha256(manifest_body),
        }
        _atomic_write_json(output_dir / "input-manifest.json", manifest)

    report = {
        "artifact_kind": "s0q_047_input_capture_report",
        "status": status,
        "bucket": bucket,
        "reason": reason,
        "scratch": {
            "knowledge_base_id": scratch_kb_id,
            "knowledge_ids": knowledge_ids,
            "cleanup": cleanup,
        },
        "input_manifest_digest": (
            manifest["manifest_digest"] if manifest is not None else None
        ),
        "harness_model_provider_calls": 0,
    }
    write_s0q_capture_report(output_dir, report)
    return report
