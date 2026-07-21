"""Shared source-bridge scenarios and validation helpers for OpenSpec 017."""

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.compiler.models import RunManifest
from insurance_harness.config import HarnessSettings
from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.knowledge.models import SourceImportContext, SourceImportIdentity
from insurance_harness.schemas.models import FieldSpec, ProductLineSchema, SchemaRegistry
from insurance_harness.sources import WeKnoraDocumentSource
from insurance_harness.sources.models import (
    ProcessedAtOrdering,
    SourceChunk,
    SourceDocument,
    SourceRevision,
    SourceScope,
    source_ordering_identity_token,
)

_REQUIRED_LIVE_VARIABLES = (
    "HARNESS_LIVE_BASE_URL",
    "HARNESS_LIVE_API_KEY",
    "HARNESS_LIVE_DB_URL",
    "HARNESS_LIVE_SPACE_ID",
    "HARNESS_LIVE_KNOWLEDGE_ID",
    "HARNESS_LIVE_PARSER_FINGERPRINT",
)
_LIVE_LINE_KEY = "live-source-bridge"
_LIVE_FIELD_ID = "live_source_fact"


@dataclass(frozen=True, slots=True)
class _LiveConfig:
    base_url: str
    api_key: str = field(repr=False)
    db_url: str = field(repr=False)
    space_id: str
    knowledge_id: str
    parser_fingerprint: str


@dataclass(frozen=True, slots=True)
class _EvidenceAnchor:
    page: int
    quote: str


class _ScriptedEvidenceClient:
    """Deterministic compiler client; it never reads model credentials or the network."""

    def __init__(self, anchor: _EvidenceAnchor) -> None:
        self._anchor = anchor
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        del system, user
        self.calls += 1
        return json.dumps(
            [
                {
                    "field_id": _LIVE_FIELD_ID,
                    "value": "live-source-bridge-verified",
                    "tri_state": "present",
                    "evidence": [
                        {"page": self._anchor.page, "quote": self._anchor.quote}
                    ],
                }
            ],
            ensure_ascii=False,
            sort_keys=True,
        )


def _live_config(environment: Mapping[str, str]) -> _LiveConfig:
    values = {name: environment.get(name, "").strip() for name in _REQUIRED_LIVE_VARIABLES}
    missing = [name for name in _REQUIRED_LIVE_VARIABLES if not values[name]]
    if missing:
        pytest.skip(f"missing live prerequisite variable(s): {', '.join(missing)}")
    db_url = values["HARNESS_LIVE_DB_URL"]
    if make_url(db_url).get_backend_name() != "postgresql":
        raise ValueError("HARNESS_LIVE_DB_URL must use PostgreSQL")
    return _LiveConfig(
        base_url=values["HARNESS_LIVE_BASE_URL"],
        api_key=values["HARNESS_LIVE_API_KEY"],
        db_url=db_url,
        space_id=values["HARNESS_LIVE_SPACE_ID"],
        knowledge_id=values["HARNESS_LIVE_KNOWLEDGE_ID"],
        parser_fingerprint=values["HARNESS_LIVE_PARSER_FINGERPRINT"],
    )


def _without_whitespace(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _select_evidence_anchor(document: SourceDocument) -> _EvidenceAnchor:
    """Require a real page substring that is contained by exactly one real chunk."""
    if not document.chunks:
        raise ValueError("live source has no uniquely linked page-backed evidence")
    page_texts = [(page.page_no, _without_whitespace(page.text)) for page in document.pages]
    chunk_texts = [_without_whitespace(chunk.content) for chunk in document.chunks]
    for size in (64, 48, 32, 24, 16, 12):
        for chunk_text in chunk_texts:
            if len(chunk_text) < size:
                continue
            step = max(1, size // 2)
            last_start = len(chunk_text) - size
            for start in range(0, last_start + 1, step):
                quote = chunk_text[start : start + size]
                page = next(
                    (page_no for page_no, page_text in page_texts if quote in page_text),
                    None,
                )
                if page is None:
                    continue
                if sum(quote in candidate for candidate in chunk_texts) == 1:
                    return _EvidenceAnchor(page=page, quote=quote)
    raise ValueError("live source has no uniquely linked page-backed evidence")


def _source_context_from_manifest(
    scope: KnowledgeScope,
    manifest: RunManifest,
    documents: tuple[SourceDocument, ...],
) -> SourceImportContext:
    if (
        manifest.space_id != scope.space_id
        or manifest.tenant_id != scope.tenant_id
        or manifest.raw_kb_id != scope.raw_kb_id
        or not manifest.docs
        or not documents
    ):
        raise ScopeViolation("scope mismatch")

    entry_names = [entry.doc for entry in manifest.docs]
    document_names = [document.file_name for document in documents]
    if (
        len(entry_names) != len(set(entry_names))
        or len(document_names) != len(set(document_names))
        or set(entry_names) != set(document_names)
    ):
        raise ScopeViolation("source identity mismatch")

    materialized = {document.file_name: document for document in documents}
    identities: dict[str, SourceImportIdentity] = {}
    for entry in manifest.docs:
        document = materialized[entry.doc]
        source_scope = document.scope
        expected_scope = (
            scope.space_id,
            scope.tenant_id,
            scope.raw_kb_id,
            scope.wiki_kb_id,
        )
        actual_scope = (
            None if source_scope is None else source_scope.space_id,
            None if source_scope is None else source_scope.tenant_id,
            document.raw_kb_id,
            None if source_scope is None else source_scope.wiki_kb_id,
        )
        expected_identity = (
            document.source_id,
            document.knowledge_id,
            document.source_revision.value,
            source_ordering_identity_token(document.source_revision.ordering),
            document.source_revision.file_hash,
            document.original_digest,
            document.source_revision.parser_fingerprint,
        )
        manifest_identity = (
            entry.source_id,
            entry.knowledge_id,
            entry.source_revision,
            source_ordering_identity_token(entry.ordering),
            entry.file_hash,
            entry.original_digest,
            entry.parser_fingerprint,
        )
        if (
            actual_scope != expected_scope
            or not document.knowledge_id
            or manifest_identity != expected_identity
        ):
            raise ScopeViolation("source identity mismatch")
        identities[entry.doc] = SourceImportIdentity(
            knowledge_id=document.knowledge_id,
            raw_kb_id=scope.raw_kb_id,
            source_revision=document.source_revision.value,
            ordering=document.source_revision.ordering,
            file_hash=document.source_revision.file_hash,
            original_digest=document.original_digest,
            parser_version=document.source_revision.parser_fingerprint,
        )
    return SourceImportContext(
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        documents=identities,
    )


def _live_registry() -> SchemaRegistry:
    return SchemaRegistry(
        version="v1.1+source-bridge-live-017",
        lines={
            _LIVE_LINE_KEY: ProductLineSchema(
                line_key=_LIVE_LINE_KEY,
                sheet_name="live source bridge",
                fields=(
                    FieldSpec(
                        name="保什么",
                        field_id=_LIVE_FIELD_ID,
                        value_type="long",
                        evidence_required=True,
                        source_sheet="live source bridge",
                    ),
                ),
            )
        },
        glossary=(),
    )


def _source(
    client: WeKnoraClient,
    scope: KnowledgeScope,
    config: _LiveConfig,
    settings: HarnessSettings,
) -> WeKnoraDocumentSource:
    return WeKnoraDocumentSource(
        client,
        scope,
        parser_fingerprint=config.parser_fingerprint,
        source_max_documents_per_batch=settings.source_max_documents_per_batch,
        source_max_batch_bytes=settings.source_max_batch_bytes,
        source_max_batch_pages=settings.source_max_batch_pages,
        source_max_batch_chunks=settings.source_max_batch_chunks,
    )


def _register_engine_cleanup(
    resources: AsyncExitStack,
    dispose_engine: Callable[[], None],
) -> None:
    resources.callback(dispose_engine)


def _register_session_cleanup(
    resources: AsyncExitStack,
    rollback: Callable[[], None],
    close_session: Callable[[], None],
) -> None:
    resources.callback(close_session)
    resources.callback(rollback)


def _register_client_cleanup(
    resources: AsyncExitStack,
    close_client: Callable[[], Awaitable[None]],
) -> None:
    resources.push_async_callback(close_client)


def _seed_live_product(
    session: Session,
    scope: KnowledgeScope,
    suffix: str,
) -> tuple[InsuranceProduct, ProductVersion]:
    product = InsuranceProduct(
        space_id=scope.space_id,
        product_code=f"LIVE017-{suffix}",
        canonical_name=f"Source Bridge Live Contract {suffix}",
        category=_LIVE_LINE_KEY,
        status="test",
        meta={"live_contract": "017"},
    )
    session.add(product)
    session.flush()
    version = ProductVersion(
        space_id=scope.space_id,
        product_id=product.id,
        version_label=f"live-{suffix}",
    )
    session.add(version)
    session.flush()
    return product, version


def _valid_live_environment() -> dict[str, str]:
    return {
        "HARNESS_LIVE_BASE_URL": "https://weknora.example.invalid",
        "HARNESS_LIVE_API_KEY": "secret-live-key",
        "HARNESS_LIVE_DB_URL": (
            "postgresql+psycopg://harness:db-password-sentinel@db/harness"
        ),
        "HARNESS_LIVE_SPACE_ID": "space-live",
        "HARNESS_LIVE_KNOWLEDGE_ID": "knowledge-live",
        "HARNESS_LIVE_PARSER_FINGERPRINT": "pdfplumber@0.11:text-v1",
    }


def _source_document(scope: KnowledgeScope) -> SourceDocument:
    return SourceDocument(
        source_id="knowledge-live",
        scope=SourceScope.from_knowledge_scope(scope),
        knowledge_id="knowledge-live",
        raw_kb_id=scope.raw_kb_id,
        title="Live policy",
        file_name="live-policy.pdf",
        file_type="application/pdf",
        source_revision=SourceRevision(
            file_hash="a" * 32,
            ordering=ProcessedAtOrdering(
                value=datetime(2026, 7, 14, tzinfo=UTC)
            ),
            parser_fingerprint="pdfplumber@0.11:text-v1",
        ),
        original_digest="b" * 64,
        pages=(
            PageText(
                page_no=1,
                text="第一条 保险责任\n唯一证据短语 ABC123，只在这里出现。",
            ),
        ),
        chunks=(
            SourceChunk(
                chunk_id="chunk-linked",
                content="第一条保险责任 唯一证据短语ABC123，只在这里出现。",
            ),
            SourceChunk(chunk_id="chunk-other", content="完全不相关的第二段。"),
        ),
    )
