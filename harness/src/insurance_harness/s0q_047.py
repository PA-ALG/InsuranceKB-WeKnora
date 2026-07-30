"""Bounded OpenSpec 047 S0-Q falsification helpers."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any, Literal

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
    return bundle
