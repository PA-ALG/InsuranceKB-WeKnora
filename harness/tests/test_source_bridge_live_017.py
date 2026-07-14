"""OpenSpec 017 T8 live source-bridge E2E and deterministic contracts."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.compiler.models import DocManifestEntry, RunManifest
from insurance_harness.compiler.pipeline import ExtractionPipeline, PipelineConfig
from insurance_harness.config import HarnessSettings
from insurance_harness.db.base import make_engine, make_session_factory
from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation, load_scope
from insurance_harness.goldenset.normalize import quote_in_page
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.knowledge.importer import import_pred_jsonl
from insurance_harness.knowledge.models import (
    MergePolicy,
    SourceImportContext,
    SourceImportIdentity,
)
from insurance_harness.knowledge.tables import Claim, ClaimEvidence
from insurance_harness.schemas.models import FieldSpec, ProductLineSchema, SchemaRegistry
from insurance_harness.sources import WeKnoraDocumentSource, WeKnoraSourceRequest
from insurance_harness.sources.lineage import match_quote_to_chunks
from insurance_harness.sources.models import (
    SourceChunk,
    SourceDocument,
    SourceRevision,
    SourceScope,
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
            document.source_revision.file_hash,
            document.original_digest,
            document.source_revision.parser_fingerprint,
        )
        manifest_identity = (
            entry.source_id,
            entry.knowledge_id,
            entry.source_revision,
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


def test_live_prerequisite_gate_names_every_missing_variable_contract() -> None:
    with pytest.raises(pytest.skip.Exception) as skipped:
        _live_config({})

    assert str(skipped.value) == (
        "missing live prerequisite variable(s): "
        "HARNESS_LIVE_BASE_URL, HARNESS_LIVE_API_KEY, HARNESS_LIVE_DB_URL, "
        "HARNESS_LIVE_SPACE_ID, HARNESS_LIVE_KNOWLEDGE_ID, "
        "HARNESS_LIVE_PARSER_FINGERPRINT"
    )


def test_live_prerequisite_gate_rejects_sqlite_and_redacts_secret_contract() -> None:
    environment = _valid_live_environment()
    config = _live_config(environment)

    assert config.knowledge_id == "knowledge-live"
    assert "secret-live-key" not in repr(config)
    assert "db-password-sentinel" not in repr(config)

    environment["HARNESS_LIVE_DB_URL"] = (
        "mysql+pymysql://harness:db-password-sentinel@db/harness"
    )
    with pytest.raises(
        ValueError,
        match="HARNESS_LIVE_DB_URL must use PostgreSQL",
    ) as rejected:
        _live_config(environment)
    assert "secret-live-key" not in str(rejected.value)
    assert "db-password-sentinel" not in str(rejected.value)


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
            processed_at=datetime(2026, 7, 14, tzinfo=UTC),
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


def test_anchor_selection_is_page_backed_and_uniquely_chunk_linked_contract(
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-live-contract",
        raw_kb_id="raw-live-contract",
        wiki_kb_id="wiki-live-contract",
    )
    document = _source_document(scope)

    anchor = _select_evidence_anchor(document)

    assert quote_in_page(anchor.quote, document.pages[anchor.page - 1].text)
    lineage = match_quote_to_chunks(anchor.quote, document.chunks)
    assert lineage.lineage_status == "linked"
    assert lineage.chunk_id == "chunk-linked"


def test_anchor_selection_rejects_source_without_chunks_contract(
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-no-chunks-contract",
        raw_kb_id="raw-no-chunks-contract",
        wiki_kb_id="wiki-no-chunks-contract",
    )
    document = _source_document(scope).model_copy(update={"chunks": ()})

    with pytest.raises(ValueError, match="uniquely linked page-backed evidence"):
        _select_evidence_anchor(document)


def test_anchor_selection_rejects_source_without_unique_chunk_contract(
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-ambiguous-contract",
        raw_kb_id="raw-ambiguous-contract",
        wiki_kb_id="wiki-ambiguous-contract",
    )
    document = _source_document(scope)
    duplicate = document.chunks[0].model_copy(update={"chunk_id": "chunk-duplicate"})
    ambiguous = document.model_copy(update={"chunks": (document.chunks[0], duplicate)})

    with pytest.raises(ValueError, match="uniquely linked page-backed evidence"):
        _select_evidence_anchor(ambiguous)


def test_manifest_to_import_context_preserves_bridge_identity_contract(
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-manifest-contract",
        raw_kb_id="raw-manifest-contract",
        wiki_kb_id="wiki-manifest-contract",
    )
    document = _source_document(scope)
    entry = DocManifestEntry(
        doc=document.file_name,
        source_id=document.source_id,
        knowledge_id=document.knowledge_id,
        source_revision=document.source_revision.value,
        file_hash=document.source_revision.file_hash,
        original_digest=document.original_digest,
        parser_fingerprint=document.source_revision.parser_fingerprint,
    )
    manifest = RunManifest(
        run_id="live-contract",
        product_dir="",
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        docs=[entry],
    )

    context = _source_context_from_manifest(scope, manifest, (document,))

    assert context.space_id == scope.space_id
    assert context.tenant_id == scope.tenant_id
    assert context.raw_kb_id == scope.raw_kb_id
    assert context.documents[document.file_name].model_dump() == {
        "knowledge_id": document.knowledge_id,
        "raw_kb_id": scope.raw_kb_id,
        "source_revision": document.source_revision.value,
        "file_hash": document.source_revision.file_hash,
        "original_digest": document.original_digest,
        "parser_version": document.source_revision.parser_fingerprint,
    }

    mismatched = manifest.model_copy(update={"raw_kb_id": "wrong-raw-kb"})
    with pytest.raises(ScopeViolation, match="scope mismatch"):
        _source_context_from_manifest(scope, mismatched, (document,))


def test_manifest_context_rejects_duplicate_and_non_bijective_docs_contract(
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-manifest-bijection",
        raw_kb_id="raw-manifest-bijection",
        wiki_kb_id="wiki-manifest-bijection",
    )
    document = _source_document(scope)
    entry = DocManifestEntry(
        doc=document.file_name,
        source_id=document.source_id,
        knowledge_id=document.knowledge_id,
        source_revision=document.source_revision.value,
        file_hash=document.source_revision.file_hash,
        original_digest=document.original_digest,
        parser_fingerprint=document.source_revision.parser_fingerprint,
    )
    manifest = RunManifest(
        run_id="live-contract-bijection",
        product_dir="",
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        docs=[entry, entry.model_copy()],
    )

    with pytest.raises(ScopeViolation, match="source identity mismatch"):
        _source_context_from_manifest(scope, manifest, (document,))

    wrong_doc = entry.model_copy(update={"doc": "other.pdf"})
    non_bijective = manifest.model_copy(update={"docs": [wrong_doc]})
    with pytest.raises(ScopeViolation, match="source identity mismatch"):
        _source_context_from_manifest(scope, non_bijective, (document,))


def test_manifest_context_rejects_self_consistent_forged_identity_contract(
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-manifest-forged",
        raw_kb_id="raw-manifest-forged",
        wiki_kb_id="wiki-manifest-forged",
    )
    document = _source_document(scope)
    forged_entry = DocManifestEntry(
        doc=document.file_name,
        source_id="forged-source",
        knowledge_id="forged-knowledge",
        source_revision="c" * 64,
        file_hash="d" * 32,
        original_digest="e" * 64,
        parser_fingerprint="forged-parser@1",
    )
    manifest = RunManifest(
        run_id="live-contract-forged",
        product_dir="",
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        docs=[forged_entry],
    )

    with pytest.raises(ScopeViolation, match="source identity mismatch"):
        _source_context_from_manifest(scope, manifest, (document,))


def test_live_import_product_seed_flushes_parent_before_version_contract(
    session: Session,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-product-contract",
        raw_kb_id="raw-product-contract",
        wiki_kb_id="wiki-product-contract",
    )

    product, version = _seed_live_product(session, scope, "contract1234")

    assert product.id
    assert version.id
    assert version.product_id == product.id
    assert product.space_id == version.space_id == scope.space_id


def test_sources_public_package_imports_before_compiler_contract() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import insurance_harness.sources as sources; "
                "from insurance_harness.compiler import ExtractionPipeline, PipelineConfig; "
                "assert sources.DocumentSource; "
                "assert ExtractionPipeline and PipelineConfig"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert probe.returncode == 0, probe.stderr


async def test_injected_failure_cleans_live_resources_and_temp_paths_contract() -> None:
    events: list[str] = []
    run_root: Path | None = None
    materialized_path: Path | None = None

    def dispose_engine() -> None:
        events.append("engine")

    def close_session() -> None:
        events.append("session")

    def rollback() -> None:
        events.append("rollback")

    async def close_client() -> None:
        events.append("client")

    with pytest.raises(RuntimeError, match="injected live failure"):
        async with AsyncExitStack() as resources:
            _register_engine_cleanup(resources, dispose_engine)
            _register_session_cleanup(resources, rollback, close_session)
            _register_client_cleanup(resources, close_client)
            with tempfile.TemporaryDirectory(
                prefix="insurancekb-live-017-cleanup-"
            ) as temp_dir:
                run_root = Path(temp_dir)
                materialized_path = run_root / "materialized-source.pdf"
                materialized_path.write_bytes(b"temporary source")
                (run_root / "run").mkdir()
                try:
                    raise RuntimeError("injected live failure")
                finally:
                    materialized_path.unlink(missing_ok=True)
                    events.append("materialized")

    assert events == ["materialized", "client", "rollback", "session", "engine"]
    assert materialized_path is not None and not materialized_path.exists()
    assert run_root is not None and not run_root.exists()


async def test_scripted_model_is_deterministic_and_credential_free_contract() -> None:
    anchor = _EvidenceAnchor(page=2, quote="可验证的真实引文")
    client = _ScriptedEvidenceClient(anchor)

    first = await client.complete("ignored system", "ignored user")
    second = await client.complete("another system", "another user")

    assert first == second
    assert json.loads(first) == [
        {
            "field_id": "live_source_fact",
            "value": "live-source-bridge-verified",
            "tri_state": "present",
            "evidence": [{"page": 2, "quote": "可验证的真实引文"}],
        }
    ]
    assert client.calls == 2


@pytest.mark.live
async def test_live_source_bridge_compiler_import_evidence_backlink() -> None:
    """Consume one real parsed knowledge and roll back all Harness DB test writes.

    The current adapter has no upload API, so this test intentionally exercises the
    accepted existing-knowledge branch. ``wait_for_parsed`` still polls the real
    endpoint and materialization downloads the real PDF and lists its real chunks.
    """
    config = _live_config(os.environ)
    settings = HarnessSettings(
        weknora_base_url=config.base_url,
        weknora_api_key=config.api_key,
    )
    engine = make_engine(config.db_url)
    async with AsyncExitStack() as resources:
        _register_engine_cleanup(resources, engine.dispose)
        if engine.dialect.name != "postgresql":
            raise AssertionError("live source bridge requires PostgreSQL")
        session = make_session_factory(engine)()
        _register_session_cleanup(resources, session.rollback, session.close)
        client = WeKnoraClient(settings, harness_job_id="source-bridge-live-017")
        _register_client_cleanup(resources, client.aclose)
        materialized_paths: tuple[Path, ...] = ()
        run_root: Path | None = None

        scope = load_scope(session, config.space_id)
        parsed = await client.wait_for_parsed(scope, config.knowledge_id)
        assert parsed.id == config.knowledge_id
        assert parsed.parse_status.strip().lower() == "completed"

        source = _source(client, scope, config, settings)
        request = WeKnoraSourceRequest(knowledge_ids=(config.knowledge_id,))
        async with source.materialize(request) as preview:
            assert len(preview.documents) == 1
            document = preview.documents[0]
            assert document.knowledge_id == config.knowledge_id
            assert document.raw_kb_id == scope.raw_kb_id
            anchor = _select_evidence_anchor(document)
            materialized_paths = tuple(preview.local_paths.values())
            assert materialized_paths
            assert all(path.is_file() for path in materialized_paths)
        assert all(not path.exists() for path in materialized_paths)

        suffix = uuid.uuid4().hex[:12]
        product, version = _seed_live_product(session, scope, suffix)

        scripted_client = _ScriptedEvidenceClient(anchor)
        pipeline = ExtractionPipeline(
            client=scripted_client,
            registry=_live_registry(),
            model_id="scripted-source-bridge-live-017",
            source=source,
            scope=scope,
            config=PipelineConfig(
                concurrency=1,
                transport_attempts=1,
                backoff_base_s=0.0,
            ),
        )
        with tempfile.TemporaryDirectory(prefix="insurancekb-live-017-") as temp_dir:
            run_root = Path(temp_dir)
            result = await pipeline.run(
                run_dir=run_root / "run",
                source_request=request,
                product_id=product.product_code,
                product_name=product.canonical_name,
                line_key=_LIVE_LINE_KEY,
                thread_id=f"live-017-{suffix}",
            )
            assert scripted_client.calls > 0
            assert len(result.records) == 1
            record = result.records[0]
            assert record.tri_state == "present"
            assert len(record.evidence) == 1

            source_context = _source_context_from_manifest(
                scope,
                result.manifest,
                (document,),
            )
            report = import_pred_jsonl(
                session,
                result.pred_path,
                scope=scope,
                product_id=product.product_code,
                product_version_id=version.id,
                source_context=source_context,
                policy=MergePolicy(auto_apply_add=True),
                created_by="source-bridge-live-017",
            )
            assert report.imported == 1
            session.flush()

            rows = list(
                session.scalars(
                    select(ClaimEvidence)
                    .join(Claim, Claim.id == ClaimEvidence.claim_id)
                    .where(
                        Claim.space_id == scope.space_id,
                        Claim.product_version_id == version.id,
                        ClaimEvidence.knowledge_id == config.knowledge_id,
                    )
                )
            )
            assert len(rows) == 1
            evidence = rows[0]
            assert evidence.knowledge_id == document.knowledge_id == config.knowledge_id
            assert evidence.raw_kb_id == document.raw_kb_id == scope.raw_kb_id
            assert evidence.source_revision == document.source_revision.value
            assert evidence.file_hash == document.source_revision.file_hash
            assert evidence.original_digest == document.original_digest
            assert evidence.parser_version == document.source_revision.parser_fingerprint
            assert evidence.page == anchor.page
            assert evidence.quote == anchor.quote
            assert quote_in_page(anchor.quote, document.pages[anchor.page - 1].text)

            lineage = match_quote_to_chunks(anchor.quote, document.chunks)
            assert lineage.lineage_status == "linked"
            assert evidence.lineage_status == "linked"
            matching_chunks = [
                chunk
                for chunk in document.chunks
                if _without_whitespace(anchor.quote)
                in _without_whitespace(chunk.content)
            ]
            assert len(matching_chunks) == 1
            linked_chunk = matching_chunks[0]
            assert evidence.chunk_id == lineage.chunk_id == linked_chunk.chunk_id
            assert evidence.chunk_hash == lineage.chunk_hash == hashlib.sha256(
                linked_chunk.content.encode("utf-8")
            ).hexdigest()
        assert run_root is not None and not run_root.exists()
