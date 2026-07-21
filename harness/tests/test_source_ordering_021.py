"""L1 ordering contracts for OpenSpec 021 source-aware identities."""

import hashlib
import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

import insurance_harness.compiler.pipeline as pipeline_module
from insurance_harness.compiler.models import DocManifestEntry
from insurance_harness.db.scope import ScopeViolation
from insurance_harness.knowledge.models import SourceImportContext, SourceImportIdentity
from insurance_harness.sources import (
    GenerationOrdering,
    ProcessedAtOrdering,
    SourceOrdering,
    SourceRevision,
)

_ORDERING_ADAPTER: TypeAdapter[SourceOrdering] = TypeAdapter(SourceOrdering)


def test_l1_source_revision_schema_requires_explicit_ordering() -> None:
    required = SourceRevision.model_json_schema().get("required", [])

    assert "ordering" in required


def test_l1_source_revision_rejects_payload_without_any_ordering() -> None:
    with pytest.raises(ValidationError, match="ordering"):
        SourceRevision(  # type: ignore[call-arg]
            file_hash="a" * 32,
            parser_fingerprint="pdfplumber@0.11:text-v1",
        )


def test_l1_processed_at_ordering_normalizes_equivalent_offsets() -> None:
    shanghai = _ORDERING_ADAPTER.validate_python(
        {
            "kind": "processed_at",
            "value": datetime(
                2026,
                7,
                19,
                16,
                30,
                tzinfo=timezone(timedelta(hours=8)),
            ),
        }
    )
    utc = _ORDERING_ADAPTER.validate_python(
        {
            "kind": "processed_at",
            "value": datetime(2026, 7, 19, 8, 30, tzinfo=UTC),
        }
    )

    assert isinstance(shanghai, ProcessedAtOrdering)
    assert shanghai == utc
    assert shanghai.value == datetime(2026, 7, 19, 8, 30, tzinfo=UTC)


def test_l1_processed_at_ordering_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        _ORDERING_ADAPTER.validate_python(
            {
                "kind": "processed_at",
                "value": datetime(2026, 7, 19, 8, 30),
            }
        )


@pytest.mark.parametrize("value", [-1, True, 1.0, "1"])
def test_l1_generation_ordering_requires_non_negative_strict_integer(
    value: Any,
) -> None:
    with pytest.raises(ValidationError):
        _ORDERING_ADAPTER.validate_python({"kind": "generation", "value": value})

    valid = _ORDERING_ADAPTER.validate_python({"kind": "generation", "value": 0})
    assert isinstance(valid, GenerationOrdering)
    assert valid.value == 0


def test_l1_source_revision_keeps_processed_at_hash_compatibility() -> None:
    legacy = SourceRevision(  # type: ignore[call-arg]
        file_hash="a" * 32,
        processed_at=datetime(2026, 7, 19, 8, 30, tzinfo=UTC),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )
    explicit = SourceRevision(
        file_hash="a" * 32,
        ordering=ProcessedAtOrdering(
            value=datetime(
                2026,
                7,
                19,
                16,
                30,
                tzinfo=timezone(timedelta(hours=8)),
            )
        ),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )

    assert legacy.value == explicit.value
    assert legacy.processed_at == explicit.processed_at == datetime(
        2026, 7, 19, 8, 30, tzinfo=UTC
    )
    assert legacy.ordering == explicit.ordering


def test_l1_generation_has_a_distinct_stable_revision_canonical_input() -> None:
    first = SourceRevision(
        file_hash="a" * 32,
        ordering=GenerationOrdering(value=7),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )
    replay = SourceRevision.model_validate(first.model_dump(mode="python"))
    processed = SourceRevision(
        file_hash="a" * 32,
        ordering=ProcessedAtOrdering(
            value=datetime(1970, 1, 1, 0, 0, 7, tzinfo=UTC)
        ),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )

    assert first == replay
    assert first.value != processed.value
    assert first.processed_at is None


def test_l1_same_revision_with_different_ordering_fails_closed() -> None:
    first = SourceRevision(
        file_hash="a" * 32,
        ordering=GenerationOrdering(value=7),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )

    with pytest.raises(ValidationError, match="source revision mismatch"):
        SourceRevision(
            file_hash="a" * 32,
            ordering=GenerationOrdering(value=8),
            parser_fingerprint="pdfplumber@0.11:text-v1",
            value=first.value,
        )


def _identity_for_revision(revision: SourceRevision) -> SourceImportIdentity:
    return SourceImportIdentity(
        knowledge_id="knowledge-1",
        raw_kb_id="raw-1",
        source_revision=revision.value,
        ordering=revision.ordering,
        file_hash=revision.file_hash,
        original_digest="b" * 64,
        parser_version=revision.parser_fingerprint,
    )


def test_l1_same_source_rejects_ordering_kind_mixing() -> None:
    processed = SourceRevision(
        file_hash="a" * 32,
        ordering=ProcessedAtOrdering(
            value=datetime(2026, 7, 19, 8, 30, tzinfo=UTC)
        ),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )
    generated = SourceRevision(
        file_hash="c" * 32,
        ordering=GenerationOrdering(value=8),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )

    with pytest.raises(ValidationError, match="ordering kind"):
        SourceImportContext(
            space_id="space-1",
            tenant_id="tenant-1",
            raw_kb_id="raw-1",
            documents={
                "processed.pdf": _identity_for_revision(processed),
                "generated.pdf": _identity_for_revision(generated),
            },
        )


def test_l1_same_source_rejects_same_ordering_for_different_revision() -> None:
    first = SourceRevision(
        file_hash="a" * 32,
        ordering=ProcessedAtOrdering(
            value=datetime(2026, 7, 19, 8, 30, tzinfo=UTC)
        ),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )
    collision = SourceRevision(
        file_hash="c" * 32,
        ordering=ProcessedAtOrdering(
            value=datetime(2026, 7, 19, 8, 30, tzinfo=UTC)
        ),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )

    with pytest.raises(ValidationError, match="ordering collision"):
        SourceImportContext(
            space_id="space-1",
            tenant_id="tenant-1",
            raw_kb_id="raw-1",
            documents={
                "first.pdf": _identity_for_revision(first),
                "collision.pdf": _identity_for_revision(collision),
            },
        )


def test_l1_manifest_and_import_identity_require_and_preserve_ordering() -> None:
    ordering = GenerationOrdering(value=11)
    revision = SourceRevision(
        file_hash="a" * 32,
        ordering=ordering,
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )
    manifest = DocManifestEntry(
        doc="policy.pdf",
        source_id="knowledge-1",
        knowledge_id="knowledge-1",
        source_revision=revision.value,
        ordering=revision.ordering,
        file_hash=revision.file_hash,
        original_digest="b" * 64,
        parser_fingerprint=revision.parser_fingerprint,
    )
    identity = SourceImportIdentity(
        knowledge_id="knowledge-1",
        raw_kb_id="raw-1",
        source_revision=manifest.source_revision,
        ordering=manifest.ordering,
        file_hash=manifest.file_hash,
        original_digest=manifest.original_digest,
        parser_version=manifest.parser_fingerprint,
    )

    assert identity.ordering == manifest.ordering == revision.ordering

    with pytest.raises(ValidationError, match="ordering"):
        SourceImportIdentity(  # type: ignore[call-arg]
            knowledge_id="knowledge-1",
            raw_kb_id="raw-1",
            source_revision=revision.value,
            file_hash=revision.file_hash,
            original_digest="b" * 64,
            parser_version=revision.parser_fingerprint,
        )


def test_l1_checkpoint_revalidation_rejects_ordering_revision_drift() -> None:
    revision = SourceRevision(
        file_hash="a" * 32,
        ordering=ProcessedAtOrdering(
            value=datetime(2026, 7, 19, 8, 30, tzinfo=UTC)
        ),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )
    revision_payload = revision.model_dump(mode="json")
    revision_payload["ordering"] = {"kind": "generation", "value": 9}
    checkpoint_document = {
        "file_name": "policy.pdf",
        "source_id": "knowledge-1",
        "knowledge_id": "knowledge-1",
        "source_revision": revision_payload,
        "original_digest": "b" * 64,
        "scope": None,
    }
    with pytest.raises(ScopeViolation, match="source identity mismatch"):
        pipeline_module._checkpoint_source_identities(  # noqa: SLF001
            [checkpoint_document]
        )


def _unsafe_revision_value(
    ordering: GenerationOrdering | ProcessedAtOrdering,
) -> str:
    if isinstance(ordering, GenerationOrdering):
        payload: dict[str, str | int | bool] = {
            "file_hash": "a" * 32,
            "generation": ordering.value,
            "ordering_kind": ordering.kind,
            "parser_fingerprint": "pdfplumber@0.11:text-v1",
        }
    else:
        payload = {
            "file_hash": "a" * 32,
            "parser_fingerprint": "pdfplumber@0.11:text-v1",
            "processed_at": ordering.value.isoformat().replace("+00:00", "Z"),
        }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def _constructed_revision(
    ordering: GenerationOrdering | ProcessedAtOrdering,
) -> SourceRevision:
    return SourceRevision.model_construct(
        file_hash="a" * 32,
        ordering=ordering,
        processed_at=None,
        parser_fingerprint="pdfplumber@0.11:text-v1",
        value=_unsafe_revision_value(ordering),
    )


@pytest.mark.parametrize(
    "ordering",
    [
        GenerationOrdering.model_construct(value=True),
        ProcessedAtOrdering.model_construct(value=datetime(2026, 7, 19, 8, 30)),
    ],
)
def test_l1_source_revision_revalidates_constructed_ordering(
    ordering: GenerationOrdering | ProcessedAtOrdering,
) -> None:
    with pytest.raises(ValidationError):
        SourceRevision(
            file_hash="a" * 32,
            ordering=ordering,
            parser_fingerprint="pdfplumber@0.11:text-v1",
        )


@pytest.mark.parametrize(
    "ordering",
    [
        GenerationOrdering.model_construct(value=True),
        ProcessedAtOrdering.model_construct(value=datetime(2026, 7, 19, 8, 30)),
    ],
)
def test_l1_source_revision_revalidates_constructed_revision_instance(
    ordering: GenerationOrdering | ProcessedAtOrdering,
) -> None:
    with pytest.raises(ValidationError):
        SourceRevision.model_validate(_constructed_revision(ordering))


@pytest.mark.parametrize(
    "ordering",
    [
        GenerationOrdering.model_construct(value=True),
        ProcessedAtOrdering.model_construct(value=datetime(2026, 7, 19, 8, 30)),
    ],
)
def test_l1_manifest_revalidates_constructed_ordering(
    ordering: GenerationOrdering | ProcessedAtOrdering,
) -> None:
    revision = _constructed_revision(ordering)
    with pytest.raises(ValidationError):
        DocManifestEntry(
            doc="policy.pdf",
            source_id="knowledge-1",
            knowledge_id="knowledge-1",
            source_revision=revision.value,
            ordering=revision.ordering,
            file_hash=revision.file_hash,
            original_digest="b" * 64,
            parser_fingerprint=revision.parser_fingerprint,
        )


@pytest.mark.parametrize(
    "ordering",
    [
        GenerationOrdering.model_construct(value=True),
        ProcessedAtOrdering.model_construct(value=datetime(2026, 7, 19, 8, 30)),
    ],
)
def test_l1_import_identity_revalidates_constructed_ordering(
    ordering: GenerationOrdering | ProcessedAtOrdering,
) -> None:
    revision = _constructed_revision(ordering)
    with pytest.raises(ValidationError):
        SourceImportIdentity(
            knowledge_id="knowledge-1",
            raw_kb_id="raw-1",
            source_revision=revision.value,
            ordering=revision.ordering,
            file_hash=revision.file_hash,
            original_digest="b" * 64,
            parser_version=revision.parser_fingerprint,
        )
