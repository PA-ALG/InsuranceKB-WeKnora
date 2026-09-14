from __future__ import annotations

# ruff: noqa: F811 -- imported pytest fixtures.
import asyncio
import hashlib
import importlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from insurance_harness.db.base import Base
from insurance_harness.jobs import ClaimedJob, JobState, JobStore
from insurance_harness.product_ingestion import artifact_tables, tables  # noqa: F401
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.progression import ProductProgression
from insurance_harness.product_ingestion.store import ProductIngestionStore
from insurance_harness.service_shell.config import ShellSettings
from insurance_harness.service_shell.health import Lifecycle
from insurance_harness.service_shell.worker import HandlerRegistry, WorkerLoop
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_routing import catalog  # noqa: F401


def module():
    try:
        return importlib.import_module("insurance_harness.product_ingestion.stages")
    except ModuleNotFoundError:
        pytest.fail("platform upload/source/routing stages are not registered")


@pytest.fixture
def stage_runtime(tmp_path, snapshot, catalog):
    scope, body, sign, keys = snapshot
    engine = create_engine(
        f"sqlite:///{tmp_path}/stages.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = ShellSettings(
        postgres_dsn="postgresql://fixture/fixture",
        worker_id="worker",
        worker_space_ids=(scope.space_id,),
    )
    jobs = JobStore(factory, settings.job_runtime_config())
    store = ProductIngestionStore(factory, jobs)
    artifacts = ProductArtifactStore(factory, store)

    class Platform:
        ready = True
        conflict = False
        failed = False
        calls = 0

        async def lookup_upload(self, _scope, run_id, ordinal):
            if not self.ready:
                return None
            return {
                "knowledge_id": f"knowledge-{ordinal}",
                "file_name": ("保险条款.pdf", "产品说明书.pdf", "费率表.pdf")[ordinal],
                "parse_status": "failed" if self.failed else "completed",
                "parse_attempt": 1,
            }

        async def capture_source(self, _scope, knowledge_id, attempt):
            self.calls += 1
            ordinal = int(knowledge_id.rsplit("-", 1)[1])
            changed = json.loads(json.dumps(body))
            changed["receipt"].update(
                knowledge_id=knowledge_id,
                revision_source_id=hashlib.sha256(knowledge_id.encode()).hexdigest(),
            )
            # Source title text changes only at the mocked parser boundary.
            text = (
                "平安测试（2026）两全保险"
                if not (self.conflict and ordinal == 2)
                else "平安测试（2025）两全保险"
            )
            text += "\n" + ("保险条款", "产品说明书", "费率表")[ordinal] + "\n"
            changed["markdown"] = text
            changed["chunks"] = [
                {
                    "id": f"block-{ordinal}",
                    "index": 0,
                    "content": text,
                    "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            ]
            changed["receipt"]["chunk_count"] = 1
            changed["chunk_page_mappings"] = [
                {
                    "chunk_id": f"block-{ordinal}",
                    "status": "EXACT_BLOCK",
                    "source_page_number": 1,
                    "block_global_start": 0,
                    "block_global_end": len(text),
                    "page_spans": [
                        {
                            "page_number": 1,
                            "block_codepoint_start": 0,
                            "block_codepoint_end": len(text),
                            "global_codepoint_start": 0,
                            "global_codepoint_end": len(text),
                        }
                    ],
                }
            ]
            return sign(changed)

    platform = Platform()

    def worker(now=None):
        registry = HandlerRegistry()
        module().register_source_stages(
            registry,
            store=store,
            artifacts=artifacts,
            scopes={scope.space_id: scope},
            platform=platform,
            public_keys=keys,
            catalog=catalog,
            now=now or (lambda: datetime.now(UTC)),
        )
        return WorkerLoop(
            store=jobs,
            registry=registry,
            settings=settings,
            lifecycle=Lifecycle(),
            worker_id="worker",
        )

    progress = ProductProgression(store=store, jobs=jobs, read_window_plan=lambda *_: ())

    def execute(run, now=None):
        progress.advance(scope, run.run_id)
        claim = jobs.claim(space_ids=(scope.space_id,), worker_id="worker")
        assert isinstance(claim, ClaimedJob)
        asyncio.run(worker(now).process_job(claim.job))
        return jobs.get_job(space_id=scope.space_id, job_id=claim.job.id)

    yield scope, store, artifacts, platform, execute
    engine.dispose()


def test_platform_stages_attach_three_originals_route_and_keep_signed_sources(stage_runtime):
    scope, store, artifacts, platform, execute = stage_runtime
    run = store.create_run(scope=scope, idempotency_key="three", expected_upload_count=3)
    for _ in range(3):
        assert execute(run).state is JobState.SUCCEEDED
    fresh = store.get_run(scope=scope, run_id=run.run_id)
    assert len(fresh.materials) == 3 and fresh.uploads_sealed_at
    assert all(item.source is None for item in fresh.materials)
    saved = artifacts.list_artifacts(scope=scope, run_id=run.run_id)
    assert len([item for item in saved if item.artifact_kind == "source_snapshot"]) == 3
    routing = next(item for item in saved if item.artifact_kind == "routing")
    assert json.loads(routing.payload)["status"] == "prepared"
    assert len(json.loads(routing.payload)["schema_candidates"]) == 11
    assert platform.calls == 3
    summary = json.loads(
        next(item for item in saved if item.artifact_kind == "source_processing_summary").payload
    )
    assert summary["model_call_count_complete"] is False
    assert all(item["counts"] is None for item in summary["materials"])


def test_missing_upload_releases_worker_and_deadline_is_terminal(stage_runtime):
    scope, store, _artifacts, platform, execute = stage_runtime
    platform.ready = False
    run = store.create_run(scope=scope, idempotency_key="late", expected_upload_count=3)
    assert execute(run).state is JobState.RETRY_WAIT
    late = store.create_run(scope=scope, idempotency_key="expired", expected_upload_count=3)
    job = execute(late, now=lambda: late.upload_deadline_at + timedelta(seconds=1))
    assert job.state is JobState.DEAD_LETTER
    assert "UPLOAD_DEADLINE_EXCEEDED" in job.error_summary
    assert platform.calls == 0


def test_routing_defers_product_version_judgement_to_identity_model(stage_runtime):
    scope, store, artifacts, platform, execute = stage_runtime
    platform.conflict = True
    run = store.create_run(scope=scope, idempotency_key="conflict", expected_upload_count=3)
    assert execute(run).state is JobState.SUCCEEDED
    assert execute(run).state is JobState.SUCCEEDED
    job = execute(run)
    assert job.state is JobState.SUCCEEDED
    assert all(
        row.source is None for row in store.get_run(scope=scope, run_id=run.run_id).materials
    )
    assert (
        len(
            artifacts.list_artifacts(
                scope=scope, run_id=run.run_id, artifact_kind="source_snapshot"
            )
        )
        == 3
    )


def test_parser_failure_finishes_source_stage_without_snapshot_call(stage_runtime):
    scope, store, _artifacts, platform, execute = stage_runtime
    platform.failed = True
    run = store.create_run(scope=scope, idempotency_key="parse-failed", expected_upload_count=3)
    assert execute(run).state is JobState.SUCCEEDED
    job = execute(run)
    assert job.state is JobState.DEAD_LETTER
    assert "SOURCE_PARSE_FAILED" in job.error_summary
    assert platform.calls == 0
