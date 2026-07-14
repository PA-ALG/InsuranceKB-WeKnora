"""Deterministic source-bridge contracts for OpenSpec 017 T8."""

import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from insurance_harness.compiler.models import DocManifestEntry, RunManifest
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.goldenset.normalize import quote_in_page
from insurance_harness.sources.lineage import match_quote_to_chunks
from tests.support.source_bridge import (
    _EvidenceAnchor,
    _live_config,
    _register_client_cleanup,
    _register_engine_cleanup,
    _register_session_cleanup,
    _ScriptedEvidenceClient,
    _seed_live_product,
    _select_evidence_anchor,
    _source_context_from_manifest,
    _source_document,
    _valid_live_environment,
)


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
