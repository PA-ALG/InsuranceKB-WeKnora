from __future__ import annotations

# ruff: noqa: F811 -- imported pytest fixtures.
import asyncio
import hashlib
import importlib
import json
import typing
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from insurance_harness.db.base import Base
from insurance_harness.jobs import ClaimedJob, JobState, JobStore, NonRetryableJobError
from insurance_harness.product_ingestion import artifact_tables, tables  # noqa: F401
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.progression import ProductProgression
from insurance_harness.product_ingestion.store import ProductIngestionStore
from insurance_harness.service_shell.config import ShellSettings
from insurance_harness.service_shell.health import Lifecycle
from insurance_harness.service_shell.worker import HandlerRegistry, WorkerLoop
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_routing import catalog  # noqa: F401


def module() -> typing.Any:
    try:
        return importlib.import_module("insurance_harness.product_ingestion.stages")
    except ModuleNotFoundError:
        pytest.fail("platform upload/source/routing stages are not registered")


@pytest.fixture
def stage_runtime(tmp_path: typing.Any, snapshot: typing.Any, catalog: typing.Any) -> typing.Any:
    scope, body, sign, keys = snapshot
    engine = create_engine(
        f"sqlite:///{tmp_path}/stages.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = ShellSettings(
        postgres_dsn=SecretStr("postgresql://fixture/fixture"),
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

        async def lookup_upload(
            self, _scope: object, run_id: object, ordinal: int
        ) -> None | dict[str, typing.Any]:
            if not self.ready:
                return None
            return {
                "knowledge_id": f"knowledge-{ordinal}",
                "file_name": ("保险条款.pdf", "产品说明书.pdf", "费率表.pdf")[ordinal],
                "parse_status": "failed" if self.failed else "completed",
                "parse_attempt": 1,
            }

        async def capture_source(
            self, _scope: object, knowledge_id: str, attempt: int
        ) -> typing.Any:
            self.calls += 1
            ordinal = int(knowledge_id.rsplit("-", 1)[1])
            changed = json.loads(json.dumps(body))
            changed["receipt"].update(
                knowledge_id=knowledge_id,
                revision_source_id=hashlib.sha256(knowledge_id.encode()).hexdigest(),
                parse_attempt=attempt,
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

        async def get_reparse_receipt(
            self, _scope: object, _run_id: object, _ordinal: object, _recovery_key: object
        ) -> None:
            return None

        async def reparse_upload(
            self,
            _scope: object,
            _run_id: object,
            ordinal: int,
            _expected_parse_attempt: object,
            _recovery_key: object,
            _deadline: object,
        ) -> None:
            raise NonRetryableJobError(
                "SOURCE_PARSE_FAILED:" + ("保险条款.pdf", "产品说明书.pdf", "费率表.pdf")[ordinal]
            )

    platform = Platform()

    def worker(now: typing.Any = None) -> WorkerLoop:
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

    def execute(run: typing.Any, now: typing.Any = None) -> typing.Any:
        progress.advance(scope, run.run_id)
        claim = jobs.claim(space_ids=(scope.space_id,), worker_id="worker")
        assert isinstance(claim, ClaimedJob)
        asyncio.run(worker(now).process_job(claim.job))
        return jobs.get_job(space_id=scope.space_id, job_id=claim.job.id)

    yield scope, store, artifacts, platform, execute
    engine.dispose()


def test_one_failed_source_requests_only_its_bound_reparse(stage_runtime: typing.Any) -> None:
    scope, store, _artifacts, platform, execute = stage_runtime
    original_lookup = platform.lookup_upload
    reparses = []
    recovered = False

    async def lookup(_scope: typing.Any, run_id: str, ordinal: int) -> typing.Any:
        item = await original_lookup(_scope, run_id, ordinal)
        if ordinal == 2:
            item["parse_attempt"] = 2 if recovered else 1
            item["parse_status"] = "completed" if recovered else "failed"
        return item

    async def reparse(
        _scope: object,
        run_id: str,
        ordinal: int,
        expected_parse_attempt: int,
        recovery_key: str,
        deadline: datetime,
    ) -> dict[str, typing.Any]:
        nonlocal recovered
        reparses.append((run_id, ordinal, expected_parse_attempt, recovery_key))
        recovered = True
        return {
            "contract": "g3-platform-bound-reparse.830.v1",
            "run_id": run_id,
            "ordinal": ordinal,
            "knowledge_id": "knowledge-2",
            "expected_parse_attempt": 1,
            "parse_attempt": 2,
            "recovery_key": recovery_key,
            "deadline_at": deadline.isoformat(),
            "dispatch_state": "enqueued",
            "queue_task_id": "task-2",
            "parse_status": "processing",
        }

    platform.lookup_upload = lookup
    platform.reparse_upload = reparse

    async def no_receipt(*_args: object, **_kwargs: object) -> None:
        return None

    platform.get_reparse_receipt = no_receipt
    run = store.create_run(
        scope=scope, idempotency_key="single-source-reparse", expected_upload_count=3
    )
    assert execute(run).state is JobState.SUCCEEDED  # uploads
    source = execute(run)
    assert source.state is JobState.RETRY_WAIT
    assert len(reparses) == 1
    assert reparses[0][:3] == (run.run_id, 2, 1)
    assert len(reparses[0][3]) == 64
    assert platform.calls == 0


def test_source_failure_persists_successful_sibling_processing_calls(
    stage_runtime: typing.Any,
) -> None:
    from tests.product_ingestion.test_processing_receipts import receipt, sealed

    scope, store, artifacts, platform, execute = stage_runtime
    original_lookup = platform.lookup_upload

    def processing(ordinal: int) -> typing.Any:
        value = receipt()
        value["knowledge_id"] = f"knowledge-{ordinal}"
        value["parse_attempt"] = 1
        value["calls"] = [
            {
                "contract": "knowledge-model-dispatch-receipt.830.v1",
                "dispatch_id": f"call-{ordinal}",
                "operation": "embedding",
                "purpose": "document_embedding",
                "model_id": "embed",
                "model_name": "qwen",
                "request_sha256": "b" * 64,
                "transport_retry_index": 0,
                "state": "RECORDED",
                "outcome": "HTTP_RESPONSE",
                "http_status": 200,
                "started_at_unix_ms": 1000,
                "finished_at_unix_ms": 1020,
                "duration_ms": 20,
            }
        ]
        value["counts"]["attempts"] = 1
        value["counts"]["confirmed"] = 1
        return sealed(value)

    async def lookup(_scope: typing.Any, run_id: str, ordinal: int) -> typing.Any:
        item = await original_lookup(_scope, run_id, ordinal)
        item["processing_receipt"] = processing(ordinal) if ordinal < 2 else None
        item["processing_receipt_parse_attempt"] = 1 if ordinal < 2 else None
        if ordinal == 2:
            item["parse_status"] = "failed"
        return item

    async def no_receipt(*_args: object) -> None:
        return None

    async def reparse(
        _scope: object,
        run_id: str,
        ordinal: int,
        attempt: int,
        key: str,
        deadline: datetime,
    ) -> dict[str, typing.Any]:
        return {
            "contract": "g3-platform-bound-reparse.830.v1",
            "run_id": run_id,
            "ordinal": ordinal,
            "knowledge_id": "knowledge-2",
            "expected_parse_attempt": attempt,
            "parse_attempt": attempt + 1,
            "recovery_key": key,
            "deadline_at": deadline.isoformat().replace("+00:00", "Z"),
            "dispatch_state": "enqueued",
            "queue_task_id": "task-2",
            "parse_status": "processing",
        }

    platform.lookup_upload = lookup
    platform.get_reparse_receipt = no_receipt
    platform.reparse_upload = reparse
    run = store.create_run(
        scope=scope, idempotency_key="source-accounting", expected_upload_count=3
    )
    assert execute(run).state is JobState.SUCCEEDED
    assert execute(run).state is JobState.RETRY_WAIT
    records = artifacts.list_artifacts(
        scope=scope, run_id=run.run_id, artifact_kind="source_processing_attempt"
    )
    assert len(records) == 2
    assert sum(json.loads(row.payload)["counts"]["attempts"] for row in records) == 2


def test_platform_stages_attach_three_originals_route_and_keep_signed_sources(
    stage_runtime: typing.Any,
) -> None:
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


def test_missing_upload_releases_worker_and_deadline_is_terminal(stage_runtime: typing.Any) -> None:
    scope, store, _artifacts, platform, execute = stage_runtime
    platform.ready = False
    run = store.create_run(scope=scope, idempotency_key="late", expected_upload_count=3)
    assert execute(run).state is JobState.RETRY_WAIT
    late = store.create_run(scope=scope, idempotency_key="expired", expected_upload_count=3)
    job = execute(late, now=lambda: late.upload_deadline_at + timedelta(seconds=1))
    assert job.state is JobState.DEAD_LETTER
    assert "UPLOAD_DEADLINE_EXCEEDED" in job.error_summary
    assert platform.calls == 0


def test_routing_defers_product_version_judgement_to_identity_model(
    stage_runtime: typing.Any,
) -> None:
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


def test_parser_failure_finishes_source_stage_without_snapshot_call(
    stage_runtime: typing.Any,
) -> None:
    scope, store, _artifacts, platform, execute = stage_runtime
    platform.failed = True
    run = store.create_run(scope=scope, idempotency_key="parse-failed", expected_upload_count=3)
    assert execute(run).state is JobState.SUCCEEDED
    job = execute(run)
    assert job.state is JobState.DEAD_LETTER
    assert "SOURCE_PARSE_FAILED" in job.error_summary
    assert platform.calls == 0
