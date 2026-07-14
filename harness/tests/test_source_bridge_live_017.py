"""Real source-bridge endpoint E2E for OpenSpec 017 T8."""

import hashlib
import os
import tempfile
import uuid
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from sqlalchemy import select

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.compiler.pipeline import ExtractionPipeline, PipelineConfig
from insurance_harness.config import HarnessSettings
from insurance_harness.db.base import make_engine, make_session_factory
from insurance_harness.db.scope import load_scope
from insurance_harness.goldenset.normalize import quote_in_page
from insurance_harness.knowledge.importer import import_pred_jsonl
from insurance_harness.knowledge.models import MergePolicy
from insurance_harness.knowledge.tables import Claim, ClaimEvidence
from insurance_harness.sources import WeKnoraSourceRequest
from insurance_harness.sources.lineage import match_quote_to_chunks
from tests.support.source_bridge import (
    _LIVE_LINE_KEY,
    _live_config,
    _live_registry,
    _register_client_cleanup,
    _register_engine_cleanup,
    _register_session_cleanup,
    _ScriptedEvidenceClient,
    _seed_live_product,
    _select_evidence_anchor,
    _source,
    _source_context_from_manifest,
    _without_whitespace,
)


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
