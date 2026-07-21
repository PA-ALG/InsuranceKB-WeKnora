"""OpenSpec 017 B4: deterministic quote-to-chunk lineage."""

import hashlib
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

import insurance_harness.compiler.pipeline as pipeline_module
from insurance_harness.compiler.models import (
    DocManifestEntry,
    FieldCandidate,
    PredRecord,
    RunManifest,
)
from insurance_harness.compiler.pipeline import ExtractionPipeline
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.goldenset.records import Evidence
from insurance_harness.schemas import FieldSpec, ProductLineSchema, SchemaRegistry
from insurance_harness.sources.lineage import LineageResult, match_quote_to_chunks
from insurance_harness.sources.models import (
    ProcessedAtOrdering,
    SourceChunk,
    SourceDocument,
    SourceRevision,
    SourceScope,
)
from insurance_harness.sources.protocol import MaterializedBatch

_FIELD = FieldSpec(name="等待期", field_id="waiting_period", source_sheet="t")
_REGISTRY = SchemaRegistry(
    version="v1.1+lineage",
    lines={
        "t": ProductLineSchema(
            line_key="t",
            sheet_name="lineage",
            fields=(_FIELD,),
        )
    },
    glossary=(),
)


class _NoModelCalls:
    async def complete(self, system: str, user: str) -> str:
        del system, user
        pytest.fail("lineage finalize must not call a model")


class _PublicRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str


class _PublicRunSource:
    def __init__(self, document: SourceDocument, runtime_path: Path) -> None:
        self.document = document
        self.runtime_path = runtime_path
        self.materializations = 0
        self.active = False

    @asynccontextmanager
    async def materialize(
        self,
        request: _PublicRunRequest,
    ) -> AsyncIterator[MaterializedBatch]:
        assert request.request_id == "public-run-lineage"
        self.materializations += 1
        self.runtime_path.write_bytes(b"runtime-only")
        self.active = True
        try:
            yield MaterializedBatch(
                documents=(self.document,),
                local_paths={self.document.source_id: self.runtime_path},
            )
        finally:
            self.active = False
            self.runtime_path.unlink(missing_ok=True)


class _PublicRunClient:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        del system, user
        self.calls += 1
        return json.dumps(
            [
                {
                    "field_id": "waiting_period",
                    "value": "90天",
                    "tri_state": "present",
                    "evidence": [{"page": 1, "quote": "等待期为90天"}],
                }
            ],
            ensure_ascii=False,
        )


def _chunk(
    chunk_id: str,
    content: str,
    *,
    chunk_index: int | None = None,
    start_at: int | None = None,
    end_at: int | None = None,
) -> SourceChunk:
    return SourceChunk(
        chunk_id=chunk_id,
        chunk_index=chunk_index,
        start_at=start_at,
        end_at=end_at,
        content=content,
    )


@pytest.mark.parametrize(
    ("case", "quote", "chunks", "status", "chunk_id"),
    [
        (
            "whitespace is removed on both sides",
            "等待期 为\n90 天",
            (_chunk("c-whitespace", "本合同等待期为 90\u3000天。"),),
            "linked",
            "c-whitespace",
        ),
        (
            "exact unique containment",
            "等待期为90天",
            (_chunk("c-before", "无关"), _chunk("c-linked", "本合同等待期为90天。")),
            "linked",
            "c-linked",
        ),
        (
            "zero normalized containment",
            "等待期为180天",
            (_chunk("c-zero", "本合同等待期为90天。"),),
            "page_only",
            None,
        ),
        (
            "two different matching chunks",
            "等待期为90天",
            (
                _chunk("c-first", "本合同等待期为90天。"),
                _chunk("c-second", "等待期为90天，详见条款。"),
            ),
            "ambiguous",
            None,
        ),
        (
            "duplicate chunk content remains ambiguous",
            "等待期为90天",
            (
                _chunk("c-copy-1", "本合同等待期为90天。"),
                _chunk("c-copy-2", "本合同等待期为90天。"),
            ),
            "ambiguous",
            None,
        ),
        (
            "empty quote never links",
            " \n\t\u3000",
            (_chunk("c-empty", ""), _chunk("c-text", "任意文本")),
            "page_only",
            None,
        ),
        (
            "case is preserved",
            "Waiting Period",
            (_chunk("c-case", "waiting period is 90 days"),),
            "page_only",
            None,
        ),
        (
            "unicode compatibility forms are preserved",
            "Ａ计划",
            (_chunk("c-unicode", "A计划"),),
            "page_only",
            None,
        ),
        (
            "punctuation is preserved",
            "责任，免除",
            (_chunk("c-punctuation", "责任,免除"),),
            "page_only",
            None,
        ),
    ],
)
def test_quote_to_chunk_mapping_is_exact_after_whitespace_normalization(
    case: str,
    quote: str,
    chunks: tuple[SourceChunk, ...],
    status: str,
    chunk_id: str | None,
) -> None:
    del case

    result = match_quote_to_chunks(quote, chunks)

    assert result.lineage_status == status
    assert result.chunk_id == chunk_id
    expected_hash = (
        None
        if chunk_id is None
        else hashlib.sha256(
            next(chunk.content for chunk in chunks if chunk.chunk_id == chunk_id).encode(
                "utf-8"
            )
        ).hexdigest()
    )
    assert result.chunk_hash == expected_hash


def test_chunk_hash_is_sha256_of_exact_utf8_content_and_is_deterministic() -> None:
    chunk = _chunk("c-hash", " 责任，免除\nＡBC ")
    expected = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()

    first = match_quote_to_chunks("责任，免除 ＡBC", (chunk,))
    second = match_quote_to_chunks("责任，免除 ＡBC", (chunk,))

    assert first == second
    assert first.chunk_hash == expected
    assert len(first.chunk_hash or "") == 64


def test_lineage_result_is_frozen_strict_and_json_serializable() -> None:
    result = match_quote_to_chunks("可回链", (_chunk("c-1", "文本可回链。"),))

    assert LineageResult.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError, match="frozen"):
        result.chunk_id = "forged"
    with pytest.raises(ValidationError):
        LineageResult.model_validate(
            {
                "lineage_status": "linked",
                "chunk_id": "c-1",
                "chunk_hash": "a" * 64,
                "extra": "forbidden",
            }
        )
    with pytest.raises(ValidationError, match="linked"):
        LineageResult(lineage_status="page_only", chunk_id="forged-partial-link")


def test_lineage_mapper_has_no_page_input_or_output_and_ignores_offsets() -> None:
    misleading = _chunk(
        "c-offsets",
        "原文引文",
        chunk_index=999,
        start_at=1_000_000,
        end_at=1_000_004,
    )

    result = match_quote_to_chunks("原文引文", (misleading,))

    assert result.lineage_status == "linked"
    assert "page" not in type(result).model_fields
    assert result.model_dump() == {
        "lineage_status": "linked",
        "chunk_id": "c-offsets",
        "chunk_hash": hashlib.sha256("原文引文".encode()).hexdigest(),
    }


def test_evidence_audit_fields_are_optional_and_legacy_construction_still_works() -> None:
    evidence = Evidence(page=1, quote="等待期为90天")

    assert evidence.model_dump(exclude_none=True) == {
        "page": 1,
        "quote": "等待期为90天",
    }
    assert {
        "knowledge_id",
        "raw_kb_id",
        "source_revision",
        "file_hash",
        "original_digest",
        "parser_version",
        "chunk_id",
        "chunk_hash",
        "lineage_status",
    }.issubset(Evidence.model_fields)


@pytest.mark.parametrize(
    "audit",
    [
        {"knowledge_id": "forged-without-status"},
        {
            "lineage_status": "linked",
            "chunk_id": "missing-hash",
        },
        {
            "lineage_status": "linked",
            "chunk_hash": "a" * 64,
        },
        {
            "lineage_status": "page_only",
            "chunk_id": "forged-page-chunk",
            "chunk_hash": "b" * 64,
        },
        {
            "lineage_status": "ambiguous",
            "chunk_id": "forged-ambiguous-chunk",
            "chunk_hash": "c" * 64,
        },
    ],
)
def test_evidence_rejects_inconsistent_lineage_audit(audit: dict[str, str]) -> None:
    with pytest.raises(ValidationError, match="lineage"):
        Evidence(page=1, quote="原始引文", **audit)  # type: ignore[arg-type]


def _valid_audit(
    *,
    scoped: bool,
    status: str = "page_only",
) -> dict[str, str]:
    audit = {
        "source_revision": "a" * 64,
        "file_hash": "b" * 32,
        "original_digest": "c" * 64,
        "parser_version": "pdfplumber@0.11:text-v1",
        "lineage_status": status,
    }
    if scoped:
        audit.update(
            {
                "knowledge_id": "knowledge-1",
                "raw_kb_id": "raw-kb-1",
            }
        )
    if status == "linked":
        audit.update(
            {
                "chunk_id": "chunk-1",
                "chunk_hash": "d" * 64,
            }
        )
    return audit


@pytest.mark.parametrize(
    "audit",
    [
        {"lineage_status": "page_only"},
        {"lineage_status": "page_only", "source_revision": "a" * 64},
        {
            **_valid_audit(scoped=True),
            "raw_kb_id": None,
        },
        {
            **_valid_audit(scoped=False, status="linked"),
        },
    ],
)
def test_evidence_rejects_status_only_partial_or_unpaired_source_audit(
    audit: dict[str, str | None],
) -> None:
    with pytest.raises(ValidationError, match="lineage"):
        Evidence(page=1, quote="原始引文", **audit)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("knowledge_id", ""),
        ("knowledge_id", " \t"),
        ("raw_kb_id", ""),
        ("parser_version", " \n"),
        ("source_revision", "not-a-sha256"),
        ("file_hash", "f" * 31),
        ("file_hash", "g" * 32),
        ("original_digest", "not-a-sha256"),
        ("chunk_id", ""),
        ("chunk_hash", "not-a-sha256"),
    ],
)
def test_evidence_rejects_empty_identity_and_invalid_audit_hashes(
    field: str,
    invalid: str,
) -> None:
    audit = _valid_audit(scoped=True, status="linked")
    audit[field] = invalid

    with pytest.raises(ValidationError, match="lineage"):
        Evidence(page=1, quote="原始引文", **audit)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "audit",
    [
        _valid_audit(scoped=False),
        _valid_audit(scoped=True),
        _valid_audit(scoped=True, status="ambiguous"),
        _valid_audit(scoped=True, status="linked"),
    ],
)
def test_evidence_accepts_complete_unscoped_and_scoped_audit(
    audit: dict[str, str],
) -> None:
    evidence = Evidence(page=1, quote="原始引文", **audit)  # type: ignore[arg-type]
    assert evidence.lineage_status == audit["lineage_status"]


def test_legacy_evidence_retains_historical_page_and_extra_tolerance() -> None:
    evidence = Evidence.model_validate(
        {"page": 0, "quote": "", "historical_extra": "ignored"}
    )

    assert evidence.page == 0
    assert evidence.quote == ""
    assert evidence.model_dump(exclude_none=True) == {"page": 0, "quote": ""}


def _revision(file_hash: str) -> SourceRevision:
    return SourceRevision(
        file_hash=file_hash,
        ordering=ProcessedAtOrdering(value=datetime(2026, 7, 14, tzinfo=UTC)),
        parser_fingerprint="pdfplumber@0.11:text-v1",
    )


def _manifest_entry(document: SourceDocument) -> DocManifestEntry:
    return DocManifestEntry(
        doc=document.file_name,
        source_id=document.source_id,
        knowledge_id=document.knowledge_id,
        source_revision=document.source_revision.value,
        ordering=document.source_revision.ordering,
        file_hash=document.source_revision.file_hash,
        original_digest=document.original_digest,
        parser_fingerprint=document.source_revision.parser_fingerprint,
    )


def _forged_evidence(*, quote: str, page: int = 1) -> Evidence:
    """A shape-valid but wholly untrusted preloaded lineage payload."""
    return Evidence(
        page=page,
        quote=quote,
        knowledge_id="forged-knowledge",
        raw_kb_id="forged-raw-kb",
        source_revision="e" * 64,
        file_hash="f" * 32,
        original_digest="3" * 64,
        parser_version="forged-parser",
        chunk_id="forged-chunk",
        chunk_hash="4" * 64,
        lineage_status="linked",
    )


def _assert_audit_absent(evidence: Evidence) -> None:
    assert evidence.model_dump(exclude={"page", "quote"}, exclude_none=True) == {}


async def _finalize_one_candidate(
    *,
    tmp_path: Path,
    documents: tuple[SourceDocument, ...],
    candidate: FieldCandidate,
    scope: KnowledgeScope | None,
) -> PredRecord:
    pipeline = ExtractionPipeline(
        client=_NoModelCalls(),
        registry=_REGISTRY,
        model_id="no-model",
        source=cast(Any, object()),
        scope=scope,
    )
    manifest = RunManifest(
        run_id="lineage-finalize",
        product_dir="",
        space_id="" if scope is None else scope.space_id,
        tenant_id="" if scope is None else scope.tenant_id,
        raw_kb_id="" if scope is None else scope.raw_kb_id,
        product_id="LINEAGE01",
        product_name="Lineage Product",
        line_key="t",
        schema_version=_REGISTRY.version,
        model_id="no-model",
        docs=[_manifest_entry(document) for document in documents],
    )
    run_dir = tmp_path / "run"

    token = pipeline_module._RUNTIME_SOURCE_DOCUMENTS.set(documents)  # noqa: SLF001
    try:
        await pipeline._node_finalize(  # noqa: SLF001 - final evidence boundary contract
            {
                "run_id": manifest.run_id,
                "run_dir": str(run_dir),
                "product_id": manifest.product_id,
                "product_name": manifest.product_name,
                "line_key": manifest.line_key,
                "source_documents": [
                    document.model_dump(mode="json") for document in documents
                ],
                "candidates": [candidate.model_dump(mode="json")],
                "manifest": manifest.model_dump(mode="json"),
            }
        )
    finally:
        pipeline_module._RUNTIME_SOURCE_DOCUMENTS.reset(token)  # noqa: SLF001

    rows = [
        PredRecord.model_validate_json(line)
        for line in (run_dir / "pred.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    return rows[0]


async def test_pipeline_enriches_only_verified_quotes_from_candidate_document(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-lineage",
        raw_kb_id="raw-lineage",
        wiki_kb_id="wiki-lineage",
    )
    source_scope = SourceScope.from_knowledge_scope(scope)
    revision_a = _revision("a" * 32)
    revision_b = _revision("b" * 32)
    document_a = SourceDocument(
        source_id="knowledge-a",
        scope=source_scope,
        knowledge_id="knowledge-a",
        raw_kb_id=scope.raw_kb_id,
        title="A",
        file_name="a.pdf",
        file_type="application/pdf",
        source_revision=revision_a,
        original_digest="c" * 64,
        pages=(
            PageText(
                page_no=1,
                text="本合同等待期为90天。此句只在另一文档的 chunk 中。",
            ),
        ),
        chunks=(
            _chunk("a-linked", "第一段：本合同等待期为 90 天。"),
            _chunk("a-unverified", "不存在于 PDF 页但存在于本文件 chunk"),
        ),
    )
    document_b = SourceDocument(
        source_id="knowledge-b",
        scope=source_scope,
        knowledge_id="knowledge-b",
        raw_kb_id=scope.raw_kb_id,
        title="B",
        file_name="b.pdf",
        file_type="application/pdf",
        source_revision=revision_b,
        original_digest="d" * 64,
        pages=(PageText(page_no=1, text="另一份文件"),),
        chunks=(
            _chunk("b-cross-doc", "此句只在另一文档的 chunk 中。"),
        ),
    )
    candidate = FieldCandidate(
        field_id=_FIELD.field_id,
        field_name=_FIELD.name,
        group="other",
        doc=document_a.file_name,
        value="90天",
        tri_state="present",
        evidence=[
            Evidence(page=1, quote="本合同等待期为90天"),
            Evidence(page=1, quote="此句只在另一文档的 chunk 中"),
            Evidence(page=1, quote="不存在于 PDF 页但存在于本文件 chunk"),
        ],
    )

    record = await _finalize_one_candidate(
        tmp_path=tmp_path,
        documents=(document_a, document_b),
        candidate=candidate,
        scope=scope,
    )

    linked, cross_doc, unverified = record.evidence
    assert (linked.page, linked.quote) == (1, "本合同等待期为90天")
    assert linked.lineage_status == "linked"
    assert linked.chunk_id == "a-linked"
    assert linked.chunk_hash == hashlib.sha256(
        document_a.chunks[0].content.encode("utf-8")
    ).hexdigest()
    assert {
        linked.knowledge_id,
        cross_doc.knowledge_id,
    } == {document_a.knowledge_id}
    assert linked.raw_kb_id == scope.raw_kb_id
    assert linked.source_revision == revision_a.value
    assert linked.file_hash == revision_a.file_hash
    assert linked.original_digest == document_a.original_digest
    assert linked.parser_version == revision_a.parser_fingerprint

    assert (cross_doc.page, cross_doc.quote) == (
        1,
        "此句只在另一文档的 chunk 中",
    )
    assert cross_doc.lineage_status == "page_only"
    assert cross_doc.chunk_id is None and cross_doc.chunk_hash is None

    assert (unverified.page, unverified.quote) == (
        1,
        "不存在于 PDF 页但存在于本文件 chunk",
    )
    assert unverified.lineage_status is None
    assert unverified.knowledge_id is None
    assert unverified.chunk_id is None and unverified.chunk_hash is None


async def test_finalize_strips_forged_audit_when_candidate_doc_is_not_materialized(
    tmp_path: Path,
) -> None:
    document = SourceDocument(
        source_id="replay:product/policy.pdf",
        scope=None,
        knowledge_id=None,
        raw_kb_id=None,
        title="Policy",
        file_name="policy.pdf",
        file_type="application/pdf",
        source_revision=_revision("5" * 64),
        original_digest="6" * 64,
        pages=(PageText(page_no=1, text="可信 PDF 原文"),),
        chunks=(),
    )
    forged = _forged_evidence(quote="预载引文", page=37)
    candidate = FieldCandidate(
        field_id=_FIELD.field_id,
        field_name=_FIELD.name,
        group="other",
        doc="missing.pdf",
        value="90天",
        tri_state="present",
        evidence=[forged],
    )

    record = await _finalize_one_candidate(
        tmp_path=tmp_path,
        documents=(document,),
        candidate=candidate,
        scope=None,
    )

    assert (record.evidence[0].page, record.evidence[0].quote) == (37, "预载引文")
    _assert_audit_absent(record.evidence[0])


async def test_finalize_strips_forged_audit_when_quote_is_not_pdf_verified(
    tmp_path: Path,
) -> None:
    document = SourceDocument(
        source_id="replay:product/policy.pdf",
        scope=None,
        knowledge_id=None,
        raw_kb_id=None,
        title="Policy",
        file_name="policy.pdf",
        file_type="application/pdf",
        source_revision=_revision("7" * 64),
        original_digest="8" * 64,
        pages=(PageText(page_no=1, text="可信 PDF 原文"),),
        chunks=(_chunk("forged-chunk", "编造引文"),),
    )
    candidate = FieldCandidate(
        field_id=_FIELD.field_id,
        field_name=_FIELD.name,
        group="other",
        doc=document.file_name,
        value="90天",
        tri_state="present",
        evidence=[_forged_evidence(quote="编造引文")],
    )

    record = await _finalize_one_candidate(
        tmp_path=tmp_path,
        documents=(document,),
        candidate=candidate,
        scope=None,
    )

    assert (record.evidence[0].page, record.evidence[0].quote) == (1, "编造引文")
    _assert_audit_absent(record.evidence[0])


async def test_finalize_strips_forged_audit_from_unknown_candidate(
    tmp_path: Path,
) -> None:
    document = SourceDocument(
        source_id="replay:product/policy.pdf",
        scope=None,
        knowledge_id=None,
        raw_kb_id=None,
        title="Policy",
        file_name="policy.pdf",
        file_type="application/pdf",
        source_revision=_revision("9" * 64),
        original_digest="a" * 64,
        pages=(PageText(page_no=1, text="等待期为90天"),),
        chunks=(_chunk("forged-chunk", "等待期为90天"),),
    )
    candidate = FieldCandidate(
        field_id=_FIELD.field_id,
        field_name=_FIELD.name,
        group="other",
        doc=document.file_name,
        tri_state="unknown",
        evidence=[_forged_evidence(quote="等待期为90天")],
    )

    record = await _finalize_one_candidate(
        tmp_path=tmp_path,
        documents=(document,),
        candidate=candidate,
        scope=None,
    )

    assert record.tri_state == "unknown"
    assert (record.evidence[0].page, record.evidence[0].quote) == (
        1,
        "等待期为90天",
    )
    _assert_audit_absent(record.evidence[0])


async def test_unscoped_verified_evidence_rederives_and_clears_forged_identity(
    tmp_path: Path,
) -> None:
    revision = _revision("b" * 64)
    document = SourceDocument(
        source_id="replay:product/policy.pdf",
        scope=None,
        knowledge_id=None,
        raw_kb_id=None,
        title="Policy",
        file_name="policy.pdf",
        file_type="application/pdf",
        source_revision=revision,
        original_digest="c" * 64,
        pages=(PageText(page_no=1, text="等待期为90天"),),
        chunks=(_chunk("forged-chunk", "等待期为90天"),),
    )
    candidate = FieldCandidate(
        field_id=_FIELD.field_id,
        field_name=_FIELD.name,
        group="other",
        doc=document.file_name,
        value="90天",
        tri_state="present",
        evidence=[_forged_evidence(quote="等待期为90天")],
    )

    record = await _finalize_one_candidate(
        tmp_path=tmp_path,
        documents=(document,),
        candidate=candidate,
        scope=None,
    )

    evidence = record.evidence[0]
    assert evidence.knowledge_id is None and evidence.raw_kb_id is None
    assert evidence.chunk_id is None and evidence.chunk_hash is None
    assert evidence.lineage_status == "page_only"
    assert evidence.source_revision == revision.value
    assert evidence.file_hash == revision.file_hash
    assert evidence.original_digest == document.original_digest
    assert evidence.parser_version == revision.parser_fingerprint


async def test_pipeline_unscoped_replay_never_forges_knowledge_or_chunk_identity(
    tmp_path: Path,
) -> None:
    revision = _revision("e" * 64)
    document = SourceDocument(
        source_id="replay:product/policy.pdf",
        scope=None,
        knowledge_id=None,
        raw_kb_id=None,
        title="Policy",
        file_name="policy.pdf",
        file_type="application/pdf",
        source_revision=revision,
        original_digest="f" * 64,
        pages=(PageText(page_no=1, text="等待期为90天"),),
        chunks=(),
    )
    candidate = FieldCandidate(
        field_id=_FIELD.field_id,
        field_name=_FIELD.name,
        group="other",
        doc=document.file_name,
        value="90天",
        tri_state="present",
        evidence=[Evidence(page=1, quote="等待期为90天")],
    )

    record = await _finalize_one_candidate(
        tmp_path=tmp_path,
        documents=(document,),
        candidate=candidate,
        scope=None,
    )

    evidence = record.evidence[0]
    assert evidence.lineage_status == "page_only"
    assert evidence.knowledge_id is None and evidence.raw_kb_id is None
    assert evidence.chunk_id is None and evidence.chunk_hash is None
    assert evidence.source_revision == revision.value
    assert evidence.file_hash == revision.file_hash
    assert evidence.original_digest == document.original_digest
    assert evidence.parser_version == revision.parser_fingerprint


async def test_unknown_candidate_without_evidence_creates_no_lineage(
    tmp_path: Path,
) -> None:
    document = SourceDocument(
        source_id="replay:product/policy.pdf",
        scope=None,
        knowledge_id=None,
        raw_kb_id=None,
        title="Policy",
        file_name="policy.pdf",
        file_type="application/pdf",
        source_revision=_revision("1" * 64),
        original_digest="2" * 64,
        pages=(PageText(page_no=1, text="等待期为90天"),),
        chunks=(_chunk("must-not-attach", "等待期为90天"),),
    )
    candidate = FieldCandidate(
        field_id=_FIELD.field_id,
        field_name=_FIELD.name,
        group="other",
        doc=document.file_name,
        tri_state="unknown",
        evidence=[],
    )

    record = await _finalize_one_candidate(
        tmp_path=tmp_path,
        documents=(document,),
        candidate=candidate,
        scope=None,
    )

    assert record.tri_state == "unknown"
    assert record.evidence == []


async def test_public_run_materializes_scoped_source_and_writes_linked_pred_audit(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-public-run",
        raw_kb_id="raw-public-run",
        wiki_kb_id="wiki-public-run",
    )
    revision = _revision("1" * 32)
    chunk = _chunk(
        "public-run-chunk",
        "第二条 等待期\n本合同等待期为 90 天。",
    )
    document = SourceDocument(
        source_id="public-run-knowledge",
        scope=SourceScope.from_knowledge_scope(scope),
        knowledge_id="public-run-knowledge",
        raw_kb_id=scope.raw_kb_id,
        title="Policy",
        file_name="policy.pdf",
        file_type="application/pdf",
        source_revision=revision,
        original_digest="2" * 64,
        pages=(
            PageText(
                page_no=1,
                text="第二条 等待期\n本合同等待期为90天。",
            ),
        ),
        chunks=(chunk,),
    )
    source = _PublicRunSource(document, tmp_path / "runtime-source.pdf")
    client = _PublicRunClient()
    pipeline = ExtractionPipeline(
        client=client,
        registry=_REGISTRY,
        model_id="scripted-public-run",
        source=source,
        scope=scope,
    )

    result = await pipeline.run(
        run_dir=tmp_path / "run-public-lineage",
        source_request=_PublicRunRequest(request_id="public-run-lineage"),
        product_id="PUBLIC01",
        product_name="Public Run Product",
        line_key="t",
    )

    assert source.materializations == 1
    assert source.active is False
    assert not source.runtime_path.exists()
    assert client.calls > 0
    assert len(result.records) == 1
    record = result.records[0]
    assert record.tri_state == "present"
    assert record.doc == document.file_name
    assert len(record.evidence) == 1
    evidence = record.evidence[0]
    assert (evidence.page, evidence.quote) == (1, "等待期为90天")
    assert evidence.knowledge_id == document.knowledge_id
    assert evidence.raw_kb_id == scope.raw_kb_id
    assert evidence.source_revision == revision.value
    assert evidence.file_hash == revision.file_hash
    assert evidence.original_digest == document.original_digest
    assert evidence.parser_version == revision.parser_fingerprint
    assert evidence.lineage_status == "linked"
    assert evidence.chunk_id == chunk.chunk_id
    assert evidence.chunk_hash == hashlib.sha256(
        chunk.content.encode("utf-8")
    ).hexdigest()
