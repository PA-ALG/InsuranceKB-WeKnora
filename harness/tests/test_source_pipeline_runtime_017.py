"""Runtime, artifact and configuration contracts for source pipelines."""

import asyncio
import json
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import MethodType

import pytest
from pydantic import ValidationError

import insurance_harness.compiler.pipeline as pipeline_module
from insurance_harness.compiler.models import (
    DocPayload,
    FieldCandidate,
    PredRecord,
    RunManifest,
)
from insurance_harness.compiler.pipeline import ExtractionPipeline, PipelineConfig
from insurance_harness.compiler.sections import family_fingerprint, split_sections
from insurance_harness.compiler.templates import ExtractionTemplate, TemplateRegistry
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.sources import DirectorySourceRequest, MaterializedBatch, SourceScope
from tests.support.source_pipeline import (
    REGISTRY,
    ConcurrentSource,
    NoModelCalls,
    TrackingSource,
    assert_no_committed_artifacts,
    source_document,
)


@pytest.mark.parametrize(
    ("scoped", "expected_mode"),
    [
        (True, "weknora"),
        (False, "directory_replay"),
    ],
)
def test_rh3_1_pipeline_emits_explicit_weknora_and_directory_source_modes(
    scoped: bool,
    expected_mode: str,
) -> None:
    candidate = FieldCandidate(
        field_id="waiting_period",
        field_name="waiting_period",
        group="basic_info",
        doc="policy.pdf",
        tri_state="unknown",
    )
    manifest = RunManifest(
        run_id="rh3-source-mode",
        product_dir="/runtime-only",
        schema_version="v1.1+rh3",
        space_id="space-rh3" if scoped else "",
        tenant_id="tenant-rh3" if scoped else "",
        raw_kb_id="raw-rh3" if scoped else "",
    )

    record = pipeline_module._to_pred(  # noqa: SLF001 - pipeline artifact contract
        candidate,
        {"product_id": "PRODUCT-RH3", "product_name": "RH3 product"},
        "test-model",
        manifest,
        datetime(2026, 7, 14, tzinfo=UTC),
    )

    assert record.source_mode == expected_mode
    legacy_payload = record.model_dump(mode="json")
    legacy_payload.pop("source_mode", None)
    assert PredRecord.model_validate(legacy_payload).source_mode == "legacy"


async def test_node_load_consumes_source_documents_without_glob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text(
        json.dumps({"planCode": "SOURCE01"}), encoding="utf-8"
    )

    def reject_glob(self: Path, pattern: str) -> list[Path]:
        del self, pattern
        raise AssertionError("compiler load must not discover files")

    monkeypatch.setattr(Path, "glob", reject_glob)
    document = source_document()
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=TrackingSource(document, tmp_path / "unused-runtime.pdf"),
    )

    loaded = await pipeline._node_load(  # noqa: SLF001 - node boundary contract
        {
            "product_dir": str(product_dir),
            "run_id": "source-load",
            "line_key": "t",
            "source_documents": [document.model_dump(mode="json")],
        }
    )

    assert loaded["docs"] == [
        DocPayload(doc="policy.pdf", pages=list(document.pages)).model_dump(mode="json")
    ]
    assert set(loaded["docs"][0]) == {"doc", "pages", "sections", "by_group", "family_id"}
    entry = loaded["manifest"]["docs"][0]
    assert entry["source_id"] == document.source_id
    assert entry["knowledge_id"] is None
    assert entry["source_revision"] == document.source_revision.value
    assert entry["ordering"] == document.source_revision.ordering.model_dump(mode="json")
    assert entry["file_hash"] == document.source_revision.file_hash
    assert entry["original_digest"] == document.original_digest
    assert entry["parser_fingerprint"] == document.source_revision.parser_fingerprint


async def test_run_rematerializes_and_holds_runtime_paths_for_the_whole_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text(
        json.dumps({"planCode": "SOURCE01"}), encoding="utf-8"
    )
    runtime_path = tmp_path / "must-never-be-serialized.pdf"
    source = TrackingSource(source_document(), runtime_path)
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=source,
    )
    original_finalize = pipeline._node_finalize  # noqa: SLF001

    async def assert_active_during_finalize(
        self: ExtractionPipeline, state: pipeline_module.PipelineState
    ) -> dict[str, object]:
        del self
        assert source.active
        assert runtime_path.is_file()
        return await original_finalize(state)

    monkeypatch.setattr(
        pipeline,
        "_node_finalize",
        MethodType(assert_active_during_finalize, pipeline),
    )
    request = DirectorySourceRequest(product_dir=product_dir)

    first = await pipeline.run(
        product_dir=product_dir,
        run_dir=tmp_path / "run-1",
        line_key="t",
        source_request=request,
    )
    second = await pipeline.run(
        product_dir=product_dir,
        run_dir=tmp_path / "run-2",
        line_key="t",
        source_request=request,
    )

    assert source.materializations == 2
    assert source.active is False
    assert not runtime_path.exists()
    serialized = (
        first.manifest_path.read_bytes()
        + (tmp_path / "run-1" / "checkpoint.sqlite").read_bytes()
        + second.manifest_path.read_bytes()
    )
    assert str(runtime_path).encode() not in serialized


async def test_scoped_source_document_stays_runtime_attested_through_load(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = bound_scope(
        tenant_id="tenant-pipeline",
        raw_kb_id="raw-pipeline",
        wiki_kb_id="wiki-pipeline",
    )
    source_scope = SourceScope.from_knowledge_scope(scope)
    document = source_document().model_copy(
        update={
            "source_id": "knowledge-1",
            "scope": source_scope,
            "knowledge_id": "knowledge-1",
            "raw_kb_id": "raw-pipeline",
        }
    )
    source = TrackingSource(document, tmp_path / "runtime.pdf")
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=source,
        scope=scope,
    )

    result = await pipeline.run(
        product_dir=product_dir,
        run_dir=tmp_path / "run-scoped-source",
        line_key="t",
        source_request=DirectorySourceRequest(product_dir=product_dir),
    )

    assert result.manifest.space_id == scope.space_id
    assert result.manifest.docs[0].knowledge_id == "knowledge-1"


async def test_scoped_pipeline_rejects_unscoped_document_before_graph_and_cleans_batch(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = bound_scope(
        tenant_id="tenant-no-directory",
        raw_kb_id="raw-no-directory",
        wiki_kb_id="wiki-no-directory",
    )
    runtime_path = tmp_path / "unscoped-runtime.pdf"
    source = TrackingSource(source_document(), runtime_path)
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=source,
        scope=scope,
    )
    monkeypatch.setattr(
        pipeline,
        "_build",
        lambda checkpointer: pytest.fail("scope mismatch must reject before graph build"),
    )
    product_dir = tmp_path / "product"
    product_dir.mkdir()

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=tmp_path / "run-rejected-unscoped",
            line_key="t",
            source_request=DirectorySourceRequest(product_dir=product_dir),
        )

    assert source.materializations == 1
    assert source.active is False
    assert not runtime_path.exists()


async def test_unscoped_pipeline_rejects_scoped_document_before_graph_and_cleans_batch(
    tmp_path: Path,
    bound_scope: Callable[..., KnowledgeScope],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scope = bound_scope(
        tenant_id="tenant-scoped-source",
        raw_kb_id="raw-scoped-source",
        wiki_kb_id="wiki-scoped-source",
    )
    document = source_document().model_copy(
        update={
            "source_id": "knowledge-scoped",
            "scope": SourceScope.from_knowledge_scope(scope),
            "knowledge_id": "knowledge-scoped",
            "raw_kb_id": scope.raw_kb_id,
        }
    )
    runtime_path = tmp_path / "scoped-runtime.pdf"
    source = TrackingSource(document, runtime_path)
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=source,
    )
    monkeypatch.setattr(
        pipeline,
        "_build",
        lambda checkpointer: pytest.fail("scope mismatch must reject before graph build"),
    )
    product_dir = tmp_path / "product"
    product_dir.mkdir()

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=tmp_path / "run-rejected-scoped",
            line_key="t",
            source_request=DirectorySourceRequest(product_dir=product_dir),
        )

    assert source.materializations == 1
    assert source.active is False
    assert not runtime_path.exists()


async def test_graph_failure_cleans_materialized_batch(tmp_path: Path) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    runtime_path = tmp_path / "failure-runtime.pdf"
    source = TrackingSource(source_document(), runtime_path)
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=source,
    )

    with pytest.raises(RuntimeError, match="注入失败"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=tmp_path / "run-failure",
            line_key="t",
            source_request=DirectorySourceRequest(product_dir=product_dir),
            fail_nodes=["split_route"],
        )

    assert source.active is False
    assert not runtime_path.exists()


async def test_graph_cancellation_cleans_materialized_batch(tmp_path: Path) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    runtime_path = tmp_path / "cancel-runtime.pdf"
    source = TrackingSource(source_document(), runtime_path)
    started = asyncio.Event()
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=source,
    )

    async def block_finalize(
        self: ExtractionPipeline, state: dict[str, object]
    ) -> dict[str, object]:
        del self, state
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    pipeline._node_finalize = MethodType(block_finalize, pipeline)  # type: ignore[method-assign]  # noqa: SLF001
    task = asyncio.create_task(
        pipeline.run(
            product_dir=product_dir,
            run_dir=tmp_path / "run-cancel",
            line_key="t",
            source_request=DirectorySourceRequest(product_dir=product_dir),
        )
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    assert source.active and runtime_path.exists()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert source.active is False
    assert not runtime_path.exists()


@pytest.mark.parametrize("failure_kind", ["stage_write", "replace"])
async def test_artifact_commit_failure_leaves_no_partial_outputs_or_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    run_dir = tmp_path / f"run-atomic-{failure_kind}"
    source = TrackingSource(source_document(), tmp_path / "runtime.pdf")
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=source,
    )
    if failure_kind == "stage_write":
        original_write_text = Path.write_text

        def fail_staged_queue_write(
            self: Path,
            data: str,
            encoding: str | None = None,
            errors: str | None = None,
            newline: str | None = None,
        ) -> int:
            if self.name == "judge-queue.jsonl":
                raise OSError("injected stage write failure")
            return original_write_text(
                self,
                data,
                encoding=encoding,
                errors=errors,
                newline=newline,
            )

        monkeypatch.setattr(Path, "write_text", fail_staged_queue_write)
        expected = "injected stage write failure"
    else:
        replace_calls = 0
        original_replace = os.replace

        def fail_second_replace(
            source_path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            destination_path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        ) -> None:
            nonlocal replace_calls
            replace_calls += 1
            if replace_calls == 2:
                raise OSError("injected replace failure")
            original_replace(source_path, destination_path)

        monkeypatch.setattr(os, "replace", fail_second_replace)
        expected = "injected replace failure"

    with pytest.raises(OSError, match=expected):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            source_request=DirectorySourceRequest(product_dir=product_dir),
        )

    assert_no_committed_artifacts(run_dir)
    assert not list(run_dir.glob(".artifacts-*.staging"))

    escaped_name = {
        "stage_write": "judge-queue.jsonl",
        "replace": "dead-letters.jsonl",
    }[failure_kind]
    escaped_artifact = run_dir / escaped_name
    escaped_artifact.write_bytes(b"unexpected")
    with pytest.raises(AssertionError):
        assert_no_committed_artifacts(run_dir)
    escaped_artifact.unlink()


async def test_run_requires_manifest_commit_marker_before_reading_artifacts(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "run-missing-commit-marker"
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=TrackingSource(source_document(), tmp_path / "runtime.pdf"),
    )
    original_finalize = pipeline._node_finalize  # noqa: SLF001

    async def remove_commit_marker(
        self: ExtractionPipeline, state: dict[str, object]
    ) -> dict[str, object]:
        del self
        result = await original_finalize(state)  # type: ignore[arg-type]
        (run_dir / "manifest.json").unlink()
        return result

    pipeline._node_finalize = MethodType(  # type: ignore[method-assign]  # noqa: SLF001
        remove_commit_marker, pipeline
    )

    with pytest.raises(ScopeViolation, match="^artifact commit mismatch$"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            source_request=DirectorySourceRequest(product_dir=product_dir),
        )


async def test_fastpath_uses_the_run_owned_source_id_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    runtime_path = tmp_path / "materialized" / "runtime-policy.pdf"
    runtime_path.parent.mkdir()
    document = source_document()
    source = TrackingSource(document, runtime_path)
    family_id = family_fingerprint(split_sections(document.pages))
    templates = TemplateRegistry(
        version="tpl-v1+source-path",
        templates=(
            ExtractionTemplate(
                template_id="tpl-source-path",
                family_id=family_id,
                doc=document.file_name,
                status="published",
            ),
        ),
    )
    seen_paths: list[Path | None] = []

    def capture_fastpath(*args: object, **kwargs: object) -> list[object]:
        del args
        path = kwargs.get("pdf_path")
        assert path is None or isinstance(path, Path)
        seen_paths.append(path)
        return []

    monkeypatch.setattr(pipeline_module, "run_fastpath", capture_fastpath)
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=source,
        template_registry=templates,
    )

    await pipeline.run(
        product_dir=product_dir,
        run_dir=tmp_path / "run-fastpath",
        line_key="t",
        source_request=DirectorySourceRequest(product_dir=product_dir),
    )

    assert seen_paths == [runtime_path]
    assert seen_paths[0] != product_dir / document.file_name


async def test_concurrent_runs_on_one_pipeline_keep_runtime_paths_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = source_document()

    cancel_product_dir = tmp_path / "cancel-product"
    cancel_product_dir.mkdir()
    cancel_source = ConcurrentSource(document)
    cancel_context = cancel_source.materialize(
        DirectorySourceRequest(product_dir=cancel_product_dir)
    )
    enter_task = asyncio.create_task(cancel_context.__aenter__())
    await asyncio.sleep(0)
    cancelled_runtime_path = cancel_product_dir / "runtime-only.pdf"
    assert cancelled_runtime_path.exists()
    enter_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await enter_task
    assert not cancelled_runtime_path.exists()

    source = ConcurrentSource(document)
    templates = TemplateRegistry(
        version="tpl-v1+concurrent-source-path",
        templates=(
            ExtractionTemplate(
                template_id="tpl-concurrent-source-path",
                family_id=family_fingerprint(split_sections(document.pages)),
                doc=document.file_name,
                status="published",
            ),
        ),
    )
    seen_paths: list[Path] = []

    def capture_fastpath(*args: object, **kwargs: object) -> list[object]:
        del args
        path = kwargs["pdf_path"]
        assert isinstance(path, Path)
        seen_paths.append(path)
        return []

    monkeypatch.setattr(pipeline_module, "run_fastpath", capture_fastpath)
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=source,
        template_registry=templates,
    )
    product_dirs = (tmp_path / "product-a", tmp_path / "product-b")
    for product_dir in product_dirs:
        product_dir.mkdir()
        (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")

    await asyncio.gather(
        *(
            pipeline.run(
                product_dir=product_dir,
                run_dir=tmp_path / f"run-{product_dir.name}",
                line_key="t",
                source_request=DirectorySourceRequest(product_dir=product_dir),
            )
            for product_dir in product_dirs
        )
    )

    assert set(seen_paths) == {
        product_dirs[0] / "runtime-only.pdf",
        product_dirs[1] / "runtime-only.pdf",
    }


async def test_duplicate_file_names_fail_closed_before_graph(tmp_path: Path) -> None:
    document = source_document()
    duplicate = document.model_copy(update={"source_id": "replay:product-2/policy.pdf"})

    class DuplicateSource:
        @asynccontextmanager
        async def materialize(
            self, request: DirectorySourceRequest
        ) -> AsyncIterator[MaterializedBatch]:
            yield MaterializedBatch(
                documents=(document, duplicate),
                local_paths={
                    document.source_id: request.product_dir / "one.pdf",
                    duplicate.source_id: request.product_dir / "two.pdf",
                },
            )

    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    pipeline = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=DuplicateSource(),
    )

    with pytest.raises(ScopeViolation, match="^source identity mismatch$"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=tmp_path / "run-duplicate",
            line_key="t",
            source_request=DirectorySourceRequest(product_dir=product_dir),
        )


@pytest.mark.parametrize(
    "field",
    [
        "max_fields_per_call",
        "window_chars",
        "section_target_chars",
        "transport_attempts",
        "gapfill_top_n",
        "concurrency",
    ],
)
@pytest.mark.parametrize("invalid", [False, 0, -1, 1.5])
def test_pipeline_config_requires_strict_positive_integer_counts(
    field: str,
    invalid: object,
) -> None:
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate({field: invalid})


@pytest.mark.parametrize("invalid", [True, -0.1, float("inf"), float("-inf"), float("nan")])
def test_pipeline_config_requires_finite_nonnegative_backoff(invalid: object) -> None:
    with pytest.raises(ValidationError):
        PipelineConfig.model_validate({"backoff_base_s": invalid})
