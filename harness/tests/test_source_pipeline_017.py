"""Compiler integration contracts for the immutable source bridge."""

import argparse
import asyncio
import json
import os
import shutil
import stat
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

import insurance_harness.compiler.pipeline as pipeline_module
from insurance_harness.compiler import cli as compiler_cli
from insurance_harness.compiler.judge import JudgeDispatcher
from insurance_harness.compiler.models import DocPayload, RunManifest
from insurance_harness.compiler.pipeline import ExtractionPipeline, PipelineConfig
from insurance_harness.compiler.sections import family_fingerprint, split_sections
from insurance_harness.compiler.templates import ExtractionTemplate, TemplateRegistry
from insurance_harness.config import HarnessSettings
from insurance_harness.db import Base, make_engine
from insurance_harness.db.models import KnowledgeSpace
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation, is_database_bound_scope
from insurance_harness.goldenset.pdf import PageText
from insurance_harness.schemas import FieldSpec, ProductLineSchema, SchemaRegistry
from insurance_harness.sources import (
    DirectorySourceRequest,
    MaterializedBatch,
    SourceDocument,
    SourceRevision,
    SourceScope,
)

REGISTRY = SchemaRegistry(
    version="v1.1+source-pipeline",
    lines={"t": ProductLineSchema(line_key="t", sheet_name="test", fields=())},
    glossary=(),
)
MODEL_REGISTRY = SchemaRegistry(
    version="v1.1+source-resume",
    lines={
        "t": ProductLineSchema(
            line_key="t",
            sheet_name="test",
            fields=(FieldSpec(name="犹豫期", field_id="hesitation_period", source_sheet="t"),),
        )
    },
    glossary=(),
)


class _NoModelCalls:
    async def complete(self, system: str, user: str) -> str:
        del system, user
        pytest.fail("load must not call a model")


class _CountingModel:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, system: str, user: str) -> str:
        del system, user
        self.calls += 1
        return json.dumps(
            [
                {
                    "field_id": "hesitation_period",
                    "value": None,
                    "tri_state": "unknown",
                    "evidence": [],
                }
            ]
        )


class _BlockingModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def complete(self, system: str, user: str) -> str:
        del system, user
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class _TrackingSource:
    def __init__(self, document: SourceDocument, runtime_path: Path) -> None:
        self.document = document
        self.runtime_path = runtime_path
        self.materializations = 0
        self.active = False

    @asynccontextmanager
    async def materialize(
        self, request: DirectorySourceRequest
    ) -> AsyncIterator[MaterializedBatch]:
        del request
        self.materializations += 1
        self.runtime_path.write_bytes(b"runtime-only-source")
        self.active = True
        try:
            yield MaterializedBatch(
                documents=(self.document,),
                local_paths={self.document.source_id: self.runtime_path},
            )
        finally:
            self.active = False
            self.runtime_path.unlink(missing_ok=True)


class _ConcurrentSource:
    def __init__(self, document: SourceDocument) -> None:
        self.document = document
        self.entered = 0
        self.both_entered = asyncio.Event()

    @asynccontextmanager
    async def materialize(
        self, request: DirectorySourceRequest
    ) -> AsyncIterator[MaterializedBatch]:
        runtime_path = request.product_dir / "runtime-only.pdf"
        runtime_path.write_bytes(b"runtime")
        self.entered += 1
        if self.entered == 2:
            self.both_entered.set()
        await self.both_entered.wait()
        try:
            yield MaterializedBatch(
                documents=(self.document,),
                local_paths={self.document.source_id: runtime_path},
            )
        finally:
            runtime_path.unlink(missing_ok=True)


def _source_document() -> SourceDocument:
    return SourceDocument(
        source_id="replay:product/policy.pdf",
        scope=None,
        knowledge_id=None,
        raw_kb_id=None,
        title="Policy",
        file_name="policy.pdf",
        file_type="application/pdf",
        source_revision=SourceRevision(
            file_hash="a" * 64,
            processed_at=datetime(1970, 1, 1, tzinfo=UTC),
            parser_fingerprint="fixture-parser-v1",
        ),
        original_digest="b" * 64,
        pages=(PageText(page_no=1, text="policy source text"),),
        chunks=(),
    )


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
    document = _source_document()
    pipeline = ExtractionPipeline(
        client=_NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=_TrackingSource(document, tmp_path / "unused-runtime.pdf"),
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
    source = _TrackingSource(_source_document(), runtime_path)
    pipeline = ExtractionPipeline(
        client=_NoModelCalls(),
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


@pytest.mark.parametrize("changed_field", ["source_revision", "original_digest"])
async def test_resume_rejects_source_identity_drift_before_model_calls(
    tmp_path: Path,
    changed_field: str,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text(
        json.dumps({"planCode": "SOURCE01"}), encoding="utf-8"
    )
    runtime_path = tmp_path / "runtime.pdf"
    source = _TrackingSource(_source_document(), runtime_path)
    client = _CountingModel()
    pipeline = ExtractionPipeline(
        client=client,
        registry=MODEL_REGISTRY,
        model_id="counting",
        source=source,
    )
    request = DirectorySourceRequest(product_dir=product_dir)
    run_dir = tmp_path / f"run-{changed_field}"

    with pytest.raises(RuntimeError, match="注入失败"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            source_request=request,
            fail_nodes=["extract"],
        )
    assert client.calls == 0

    if changed_field == "source_revision":
        source.document = source.document.model_copy(
            update={
                "source_revision": SourceRevision(
                    file_hash="c" * 64,
                    processed_at=datetime(1970, 1, 1, tzinfo=UTC),
                    parser_fingerprint="fixture-parser-v1",
                )
            }
        )
    else:
        source.document = source.document.model_copy(update={"original_digest": "d" * 64})

    with pytest.raises(ScopeViolation, match="^source identity mismatch$"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            source_request=request,
            resume=True,
            state_patch={"fail_nodes": []},
        )

    assert source.materializations == 2
    assert client.calls == 0


async def test_resume_rejects_patched_checkpoint_source_before_model_calls(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    source = _TrackingSource(_source_document(), tmp_path / "runtime.pdf")
    client = _CountingModel()
    pipeline = ExtractionPipeline(
        client=client,
        registry=MODEL_REGISTRY,
        model_id="counting",
        source=source,
    )
    request = DirectorySourceRequest(product_dir=product_dir)
    run_dir = tmp_path / "run-patched-source"
    with pytest.raises(RuntimeError, match="注入失败"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            source_request=request,
            fail_nodes=["extract"],
        )
    forged = source.document.model_copy(update={"original_digest": "e" * 64})

    with pytest.raises(ScopeViolation, match="^state patch mismatch$"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            source_request=request,
            resume=True,
            state_patch={
                "fail_nodes": [],
                "source_documents": [forged.model_dump(mode="json")],
            },
        )

    assert client.calls == 0


@pytest.mark.parametrize("patch_key", ["source_documents", "runtime_paths"])
async def test_resume_rejects_non_allowlisted_patch_before_checkpoint_write(
    tmp_path: Path,
    patch_key: str,
) -> None:
    marker = f"temporary-path-marker-{patch_key}"
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    source = _TrackingSource(_source_document(), tmp_path / "runtime.pdf")
    pipeline = ExtractionPipeline(
        client=_CountingModel(),
        registry=MODEL_REGISTRY,
        model_id="counting",
        source=source,
    )
    request = DirectorySourceRequest(product_dir=product_dir)
    run_dir = tmp_path / f"run-rejected-{patch_key}"
    with pytest.raises(RuntimeError, match="注入失败"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            source_request=request,
            fail_nodes=["extract"],
        )
    source_dump = source.document.model_dump(mode="json")
    source_dump["temporary_path"] = marker
    patch_value: object = (
        [source_dump] if patch_key == "source_documents" else {"source": marker}
    )

    with pytest.raises(ScopeViolation, match="^state patch mismatch$"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            source_request=request,
            resume=True,
            state_patch={patch_key: patch_value},
        )

    assert marker.encode() not in (run_dir / "checkpoint.sqlite").read_bytes()


async def test_resume_rejects_unknown_fail_node_before_checkpoint_write(
    tmp_path: Path,
) -> None:
    marker = "temporary-path-marker-unknown-node"
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    source = _TrackingSource(_source_document(), tmp_path / "runtime.pdf")
    pipeline = ExtractionPipeline(
        client=_CountingModel(),
        registry=MODEL_REGISTRY,
        model_id="counting",
        source=source,
    )
    request = DirectorySourceRequest(product_dir=product_dir)
    run_dir = tmp_path / "run-rejected-fail-node"
    with pytest.raises(RuntimeError, match="注入失败"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            source_request=request,
            fail_nodes=["extract"],
        )

    with pytest.raises(ScopeViolation, match="^state patch mismatch$"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            line_key="t",
            source_request=request,
            resume=True,
            state_patch={"fail_nodes": ["extract", marker]},
        )

    assert marker.encode() not in (run_dir / "checkpoint.sqlite").read_bytes()


def _assert_no_committed_artifacts(*run_dirs: Path) -> None:
    artifact_names = (
        "pred.jsonl",
        "manifest.json",
        "judge-queue.jsonl",
        "dead-letters.jsonl",
    )
    assert not any((run_dir / name).exists() for run_dir in run_dirs for name in artifact_names)


async def test_resume_rejects_checkpoint_from_a_different_run_directory_pre_model(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text(
        json.dumps({"planCode": "SOURCE01"}), encoding="utf-8"
    )
    source = _TrackingSource(_source_document(), tmp_path / "runtime.pdf")
    client = _CountingModel()
    pipeline = ExtractionPipeline(
        client=client,
        registry=MODEL_REGISTRY,
        model_id="baseline-model",
        source=source,
    )
    request = DirectorySourceRequest(product_dir=product_dir)
    checkpoint_path = tmp_path / "shared-checkpoint.sqlite"
    old_run_dir = tmp_path / "run-old"
    new_run_dir = tmp_path / "run-new"
    with pytest.raises(RuntimeError, match="注入失败"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=old_run_dir,
            checkpoint_path=checkpoint_path,
            thread_id="shared-run",
            line_key="t",
            source_request=request,
            fail_nodes=["extract"],
        )

    with pytest.raises(ScopeViolation, match="^run identity mismatch$"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=new_run_dir,
            checkpoint_path=checkpoint_path,
            thread_id="shared-run",
            line_key="t",
            source_request=request,
            resume=True,
            state_patch={"fail_nodes": []},
        )

    assert client.calls == 0
    _assert_no_committed_artifacts(old_run_dir, new_run_dir)


@pytest.mark.parametrize(
    "changed_field",
    ["product", "model", "schema", "line", "judge", "prompt"],
)
async def test_resume_rejects_checkpoint_execution_identity_drift_pre_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed_field: str,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    source = _TrackingSource(_source_document(), tmp_path / "runtime.pdf")
    client = _CountingModel()
    line_registry = SchemaRegistry(
        version=MODEL_REGISTRY.version,
        lines={
            "t": MODEL_REGISTRY.line("t"),
            "u": ProductLineSchema(
                line_key="u", sheet_name="other", fields=MODEL_REGISTRY.line("t").fields
            ),
        },
        glossary=(),
    )
    baseline_registry = line_registry if changed_field == "line" else MODEL_REGISTRY
    baseline = ExtractionPipeline(
        client=client,
        registry=baseline_registry,
        model_id="baseline-model",
        source=source,
    )
    request = DirectorySourceRequest(product_dir=product_dir)
    run_dir = tmp_path / f"run-identity-{changed_field}"
    checkpoint_path = tmp_path / f"checkpoint-{changed_field}.sqlite"
    with pytest.raises(RuntimeError, match="注入失败"):
        await baseline.run(
            product_dir=product_dir,
            product_id="PRODUCT-A",
            product_name="Product A",
            run_dir=run_dir,
            checkpoint_path=checkpoint_path,
            thread_id="shared-identity",
            line_key="t",
            source_request=request,
            fail_nodes=["extract"],
        )
    changed_registry = baseline_registry
    if changed_field == "schema":
        changed_registry = SchemaRegistry(
            version="changed-schema-version",
            lines={"t": MODEL_REGISTRY.line("t")},
            glossary=(),
        )
    changed_model_id = "changed-model" if changed_field == "model" else "baseline-model"
    changed_judge = (
        JudgeDispatcher(mode="gateway", client=_CountingModel())
        if changed_field == "judge"
        else None
    )
    if changed_field == "prompt":
        monkeypatch.setattr(pipeline_module, "PROMPT_VERSION", "changed-prompt-version")
    resumed = ExtractionPipeline(
        client=client,
        registry=changed_registry,
        model_id=changed_model_id,
        source=source,
        judge=changed_judge,
    )

    with pytest.raises(ScopeViolation, match="^run identity mismatch$"):
        await resumed.run(
            product_dir=product_dir,
            product_id="PRODUCT-B" if changed_field == "product" else "PRODUCT-A",
            product_name="Product B" if changed_field == "product" else "Product A",
            run_dir=run_dir,
            checkpoint_path=checkpoint_path,
            thread_id="shared-identity",
            line_key="u" if changed_field == "line" else "t",
            source_request=request,
            resume=True,
            state_patch={"fail_nodes": []},
        )

    assert client.calls == 0
    _assert_no_committed_artifacts(run_dir)


async def test_non_resume_rejects_reusing_existing_thread_state_pre_model(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    source = _TrackingSource(_source_document(), tmp_path / "runtime.pdf")
    client = _CountingModel()
    pipeline = ExtractionPipeline(
        client=client,
        registry=MODEL_REGISTRY,
        model_id="baseline-model",
        source=source,
    )
    request = DirectorySourceRequest(product_dir=product_dir)
    run_dir = tmp_path / "run-non-resume-reuse"
    with pytest.raises(RuntimeError, match="注入失败"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            thread_id="shared-thread",
            line_key="t",
            source_request=request,
            fail_nodes=["extract"],
        )

    with pytest.raises(ScopeViolation, match="^run identity mismatch$"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            thread_id="shared-thread",
            line_key="t",
            source_request=request,
            resume=False,
        )

    assert client.calls == 0
    _assert_no_committed_artifacts(run_dir)


async def test_resume_without_checkpoint_state_fails_closed_pre_model(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    source = _TrackingSource(_source_document(), tmp_path / "runtime.pdf")
    client = _CountingModel()
    pipeline = ExtractionPipeline(
        client=client,
        registry=MODEL_REGISTRY,
        model_id="baseline-model",
        source=source,
    )
    run_dir = tmp_path / "run-empty-resume"

    with pytest.raises(ScopeViolation, match="^run identity mismatch$"):
        await pipeline.run(
            product_dir=product_dir,
            run_dir=run_dir,
            thread_id="missing-thread",
            line_key="t",
            source_request=DirectorySourceRequest(product_dir=product_dir),
            resume=True,
        )

    assert client.calls == 0
    _assert_no_committed_artifacts(run_dir)


async def test_completed_run_rejects_alternate_fresh_checkpoint_pre_source(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "completed-run"
    first_source = _TrackingSource(_source_document(), tmp_path / "first-runtime.pdf")
    first = ExtractionPipeline(
        client=_NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=first_source,
    )
    request = DirectorySourceRequest(product_dir=product_dir)
    await first.run(
        product_dir=product_dir,
        run_dir=run_dir,
        line_key="t",
        source_request=request,
    )
    artifact_names = (
        "pred.jsonl",
        "manifest.json",
        "judge-queue.jsonl",
        "dead-letters.jsonl",
    )
    committed = {name: (run_dir / name).read_bytes() for name in artifact_names}
    alternate_checkpoint = tmp_path / "alternate-empty.sqlite"
    rejected_source = _TrackingSource(
        _source_document(), tmp_path / "rejected-runtime.pdf"
    )
    rejected = ExtractionPipeline(
        client=_NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=rejected_source,
    )

    with pytest.raises(ScopeViolation, match="^run identity mismatch$"):
        await rejected.run(
            product_dir=product_dir,
            run_dir=run_dir,
            checkpoint_path=alternate_checkpoint,
            line_key="t",
            source_request=request,
            resume=False,
        )

    assert rejected_source.materializations == 0
    assert rejected_source.active is False
    assert not rejected_source.runtime_path.exists()
    assert not alternate_checkpoint.exists()
    assert committed == {name: (run_dir / name).read_bytes() for name in artifact_names}


async def test_resume_rejects_copied_checkpoint_at_a_different_path_pre_model(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "run-checkpoint-drift"
    original_checkpoint = tmp_path / "original.sqlite"
    copied_checkpoint = tmp_path / "copied.sqlite"
    source = _TrackingSource(_source_document(), tmp_path / "runtime.pdf")
    client = _CountingModel()
    first = ExtractionPipeline(
        client=client,
        registry=MODEL_REGISTRY,
        model_id="counting",
        source=source,
    )
    request = DirectorySourceRequest(product_dir=product_dir)
    with pytest.raises(RuntimeError, match="注入失败"):
        await first.run(
            product_dir=product_dir,
            run_dir=run_dir,
            checkpoint_path=original_checkpoint,
            thread_id="checkpoint-drift",
            line_key="t",
            source_request=request,
            fail_nodes=["extract"],
        )
    shutil.copy2(original_checkpoint, copied_checkpoint)

    with pytest.raises(ScopeViolation, match="^run identity mismatch$"):
        await first.run(
            product_dir=product_dir,
            run_dir=run_dir,
            checkpoint_path=copied_checkpoint,
            thread_id="checkpoint-drift",
            line_key="t",
            source_request=request,
            resume=True,
            state_patch={"fail_nodes": []},
        )

    assert client.calls == 0
    assert source.active is False
    assert not source.runtime_path.exists()
    _assert_no_committed_artifacts(run_dir)


async def test_concurrent_fresh_writers_are_serialized_by_run_directory(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "concurrent-run"
    request = DirectorySourceRequest(product_dir=product_dir)
    first_source = _TrackingSource(_source_document(), tmp_path / "runtime-first.pdf")
    second_source = _TrackingSource(_source_document(), tmp_path / "runtime-second.pdf")
    first = ExtractionPipeline(
        client=_NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=first_source,
    )
    second = ExtractionPipeline(
        client=_NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=second_source,
    )
    reached_finalize = asyncio.Event()
    release_finalize = asyncio.Event()
    original_finalize = first._node_finalize  # noqa: SLF001

    async def pause_first_finalize(
        self: ExtractionPipeline, state: dict[str, object]
    ) -> dict[str, object]:
        del self
        reached_finalize.set()
        await release_finalize.wait()
        return await original_finalize(state)  # type: ignore[arg-type]

    first._node_finalize = MethodType(  # type: ignore[method-assign]  # noqa: SLF001
        pause_first_finalize, first
    )
    first_task = asyncio.create_task(
        first.run(
            product_dir=product_dir,
            run_dir=run_dir,
            thread_id="concurrent-run",
            line_key="t",
            source_request=request,
        )
    )
    await asyncio.wait_for(reached_finalize.wait(), timeout=1)
    assert first_source.active
    second_task = asyncio.create_task(
        second.run(
            product_dir=product_dir,
            run_dir=run_dir,
            thread_id="concurrent-run",
            line_key="t",
            source_request=request,
        )
    )
    await asyncio.sleep(0.05)
    second_entered_before_first_commit = second_source.materializations > 0
    release_finalize.set()
    first_result, second_result = await asyncio.gather(
        first_task, second_task, return_exceptions=True
    )

    assert not isinstance(first_result, BaseException)
    assert isinstance(second_result, ScopeViolation)
    assert str(second_result) == "run identity mismatch"
    assert second_entered_before_first_commit is False
    assert first_source.active is False and second_source.active is False
    assert not first_source.runtime_path.exists()
    assert not second_source.runtime_path.exists()
    lock_path = run_dir / ".run.lock"
    assert lock_path.exists()
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600

    verification_source = _TrackingSource(
        _source_document(), tmp_path / "runtime-verification.pdf"
    )
    verified = await ExtractionPipeline(
        client=_NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=verification_source,
    ).run(
        product_dir=product_dir,
        run_dir=run_dir,
        thread_id="concurrent-run",
        line_key="t",
        source_request=request,
        resume=True,
    )
    committed_manifest = RunManifest.model_validate_json(
        (run_dir / "manifest.json").read_text(encoding="utf-8")
    )
    assert verified.manifest == committed_manifest
    assert verification_source.active is False
    assert not verification_source.runtime_path.exists()


async def test_cancelling_run_lock_waiter_closes_its_file_descriptor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "lock-cancellation"
    run_dir.mkdir()
    opened: list[int] = []
    closed: list[int] = []
    original_open = os.open
    original_close = os.close

    def tracked_open(path: object, flags: int, mode: int = 0o777) -> int:
        file_descriptor = original_open(path, flags, mode)  # type: ignore[arg-type]
        if Path(path).name == ".run.lock":  # type: ignore[arg-type]
            opened.append(file_descriptor)
        return file_descriptor

    def tracked_close(file_descriptor: int) -> None:
        if file_descriptor in opened:
            closed.append(file_descriptor)
        original_close(file_descriptor)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    holder_acquired = asyncio.Event()
    release_holder = asyncio.Event()
    waiter_entered = asyncio.Event()

    async def hold_lock() -> None:
        async with pipeline_module._exclusive_run_directory(run_dir):  # noqa: SLF001
            holder_acquired.set()
            await release_holder.wait()

    async def wait_for_lock() -> None:
        async with pipeline_module._exclusive_run_directory(run_dir):  # noqa: SLF001
            waiter_entered.set()

    holder = asyncio.create_task(hold_lock())
    await asyncio.wait_for(holder_acquired.wait(), timeout=1)
    waiter = asyncio.create_task(wait_for_lock())
    async with asyncio.timeout(1):
        while len(opened) < 2:
            await asyncio.sleep(0.001)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(waiter, timeout=0.2)
    assert not waiter_entered.is_set()
    assert opened[1] in closed
    assert opened[0] not in closed

    release_holder.set()
    await asyncio.wait_for(holder, timeout=1)
    assert opened[0] in closed


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
    document = _source_document().model_copy(
        update={
            "source_id": "knowledge-1",
            "scope": source_scope,
            "knowledge_id": "knowledge-1",
            "raw_kb_id": "raw-pipeline",
        }
    )
    source = _TrackingSource(document, tmp_path / "runtime.pdf")
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    pipeline = ExtractionPipeline(
        client=_NoModelCalls(),
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
    source = _TrackingSource(_source_document(), runtime_path)
    pipeline = ExtractionPipeline(
        client=_NoModelCalls(),
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
    document = _source_document().model_copy(
        update={
            "source_id": "knowledge-scoped",
            "scope": SourceScope.from_knowledge_scope(scope),
            "knowledge_id": "knowledge-scoped",
            "raw_kb_id": scope.raw_kb_id,
        }
    )
    runtime_path = tmp_path / "scoped-runtime.pdf"
    source = _TrackingSource(document, runtime_path)
    pipeline = ExtractionPipeline(
        client=_NoModelCalls(),
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
    source = _TrackingSource(_source_document(), runtime_path)
    pipeline = ExtractionPipeline(
        client=_NoModelCalls(),
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
    source = _TrackingSource(_source_document(), runtime_path)
    started = asyncio.Event()
    pipeline = ExtractionPipeline(
        client=_NoModelCalls(),
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
    source = _TrackingSource(_source_document(), tmp_path / "runtime.pdf")
    pipeline = ExtractionPipeline(
        client=_NoModelCalls(),
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

    _assert_no_committed_artifacts(run_dir)
    assert not list(run_dir.glob(".artifacts-*.staging"))


async def test_run_requires_manifest_commit_marker_before_reading_artifacts(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "run-missing-commit-marker"
    pipeline = ExtractionPipeline(
        client=_NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=_TrackingSource(_source_document(), tmp_path / "runtime.pdf"),
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
    document = _source_document()
    source = _TrackingSource(document, runtime_path)
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
        client=_NoModelCalls(),
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
    document = _source_document()
    source = _ConcurrentSource(document)
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
        client=_NoModelCalls(),
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
    document = _source_document()
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
        client=_NoModelCalls(),
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


@pytest.mark.parametrize("command", ["extract", "extract-replay"])
def test_cli_rejects_zero_concurrency_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    async def reject_dispatch(args: object) -> int:
        del args
        pytest.fail("zero concurrency must fail during argument parsing")

    monkeypatch.setattr(compiler_cli, "_cmd_extract", reject_dispatch)
    monkeypatch.setattr(compiler_cli, "_cmd_extract_replay", reject_dispatch)
    if command == "extract":
        argv = [
            "extract",
            "--source",
            "weknora",
            "--space-id",
            "space-1",
            "--parser-fingerprint",
            "parser-v1",
            "--knowledge-id",
            "knowledge-1",
            "--product-id",
            "PRODUCT01",
            "--product-name",
            "Product One",
            "--run-dir",
            str(tmp_path / "run"),
            "--concurrency",
            "0",
        ]
    else:
        argv = [
            "extract-replay",
            str(tmp_path / "product"),
            "--replay-identity",
            "fixture-1",
            "--parser-fingerprint",
            "parser-v1",
            "--run-dir",
            str(tmp_path / "run"),
            "--concurrency",
            "0",
        ]

    with pytest.raises(SystemExit) as error:
        compiler_cli.main(argv)
    assert error.value.code == 2


def test_production_extract_requires_and_dispatches_explicit_weknora_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[argparse.Namespace] = []

    async def fake_extract(args: argparse.Namespace) -> int:
        captured.append(args)
        return 0

    monkeypatch.setattr(compiler_cli, "_cmd_extract", fake_extract)
    assert (
        compiler_cli.main(
            [
                "extract",
                "--source",
                "weknora",
                "--space-id",
                "space-1",
                "--parser-fingerprint",
                "pdfplumber@0.11:text-v1",
                "--knowledge-id",
                "knowledge-1",
                "--product-id",
                "PRODUCT01",
                "--product-name",
                "Product One",
                "--db-url",
                "sqlite:///scope.db",
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )
        == 0
    )

    assert len(captured) == 1
    args = captured[0]
    assert args.source == "weknora"
    assert args.knowledge_ids == ["knowledge-1"]
    assert not hasattr(args, "product_dir")


def test_extract_replay_is_the_only_cli_command_with_directory_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_dir = tmp_path / "product"
    captured: list[argparse.Namespace] = []

    async def fake_replay(args: argparse.Namespace) -> int:
        captured.append(args)
        return 0

    monkeypatch.setattr(compiler_cli, "_cmd_extract_replay", fake_replay, raising=False)
    assert (
        compiler_cli.main(
            [
                "extract-replay",
                str(product_dir),
                "--replay-identity",
                "golden:product-1",
                "--parser-fingerprint",
                "fixture-parser-v1",
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )
        == 0
    )

    assert len(captured) == 1
    args = captured[0]
    assert args.product_dir == product_dir
    assert args.replay_identity == "golden:product-1"
    assert not hasattr(args, "source")
    assert not hasattr(args, "space_id")


def test_extract_replay_constructs_only_directory_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    captured: dict[str, object] = {}

    class FakeDirectorySource:
        def __init__(self, **kwargs: object) -> None:
            captured["source_kwargs"] = kwargs

    class FakePipeline:
        def __init__(self, **kwargs: object) -> None:
            captured["pipeline_kwargs"] = kwargs

        async def run(self, **kwargs: object) -> SimpleNamespace:
            captured["run_kwargs"] = kwargs
            run_dir = kwargs["run_dir"]
            assert isinstance(run_dir, Path)
            return SimpleNamespace(
                manifest=RunManifest(run_id="replay", product_dir=str(product_dir)),
                records=[],
                pred_path=run_dir / "pred.jsonl",
            )

    monkeypatch.setattr(
        compiler_cli, "DirectoryDocumentSource", FakeDirectorySource, raising=False
    )
    monkeypatch.setattr(compiler_cli, "ExtractionPipeline", FakePipeline)
    monkeypatch.setattr(compiler_cli, "load_settings", lambda: SimpleNamespace(
        judge_mode="claude-session", table_provider="pdfplumber"
    ))
    monkeypatch.setattr(compiler_cli, "build_client", lambda *args: (_NoModelCalls(), "replay"))
    monkeypatch.setattr(compiler_cli, "load_schema_registry", lambda _: REGISTRY)
    monkeypatch.setattr(
        compiler_cli,
        "load_template_registry",
        lambda _: TemplateRegistry(version="tpl-v1+empty", templates=()),
    )
    monkeypatch.setattr(compiler_cli, "select_table_provider", lambda _: None)

    assert (
        compiler_cli.main(
            [
                "extract-replay",
                str(product_dir),
                "--replay-identity",
                "golden:product-1",
                "--parser-fingerprint",
                "fixture-parser-v1",
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )
        == 0
    )

    assert captured["source_kwargs"] == {
        "replay_identity": "golden:product-1",
        "parser_fingerprint": "fixture-parser-v1",
    }
    pipeline_kwargs = captured["pipeline_kwargs"]
    assert isinstance(pipeline_kwargs, dict)
    assert isinstance(pipeline_kwargs["source"], FakeDirectorySource)
    assert pipeline_kwargs.get("scope") is None
    run_kwargs = captured["run_kwargs"]
    assert isinstance(run_kwargs, dict)
    assert run_kwargs["product_dir"] == product_dir
    assert run_kwargs["source_request"] == DirectorySourceRequest(product_dir=product_dir)


def test_production_extract_loads_bound_scope_and_passes_all_source_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_url = f"sqlite:///{tmp_path}/scope.db"
    seed_engine = make_engine(db_url)
    Base.metadata.create_all(seed_engine)
    with Session(seed_engine) as session:
        session.add(
            KnowledgeSpace(
                id="space-1",
                name="Production",
                tenant_id="tenant-1",
                raw_kb_id="raw-1",
                wiki_kb_id="wiki-1",
                binding_status="bound",
            )
        )
        session.commit()
    seed_engine.dispose()
    settings = HarnessSettings(
        weknora_base_url="https://weknora.invalid",
        weknora_api_key="secret",
        db_url=db_url,
        source_max_documents_per_batch=3,
        source_max_batch_bytes=4_000,
        source_max_batch_pages=50,
        source_max_batch_chunks=600,
    )
    captured: dict[str, object] = {}

    class TrackingSession:
        def __init__(self, engine: object) -> None:
            self._session = Session(engine)  # type: ignore[arg-type]

        def __enter__(self) -> Session:
            captured["session_active"] = True
            return self._session

        def __exit__(self, *args: object) -> None:
            del args
            self._session.close()
            captured["session_active"] = False

    class FakeWeKnoraClient:
        def __init__(self, client_settings: HarnessSettings) -> None:
            assert client_settings is settings
            captured["client"] = self

        async def aclose(self) -> None:
            captured["client_closed"] = True

    class FakeWeKnoraSource:
        def __init__(self, **kwargs: object) -> None:
            captured["source_kwargs"] = kwargs
            self.scope = kwargs["scope"]

    class RejectDirectorySource:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            pytest.fail("production extract must not construct DirectoryDocumentSource")

    class FakePipeline:
        def __init__(self, **kwargs: object) -> None:
            captured["pipeline_kwargs"] = kwargs

        async def run(self, **kwargs: object) -> SimpleNamespace:
            captured["run_kwargs"] = kwargs
            assert captured["session_active"] is False
            pipeline_kwargs = captured["pipeline_kwargs"]
            assert isinstance(pipeline_kwargs, dict)
            scope = pipeline_kwargs["scope"]
            assert is_database_bound_scope(scope)
            run_dir = kwargs["run_dir"]
            assert isinstance(run_dir, Path)
            return SimpleNamespace(
                manifest=RunManifest(run_id="production", product_dir=""),
                records=[],
                pred_path=run_dir / "pred.jsonl",
            )

    monkeypatch.setattr(compiler_cli, "load_settings", lambda **_: settings)
    monkeypatch.setattr(compiler_cli, "build_client", lambda *args: (_NoModelCalls(), "replay"))
    monkeypatch.setattr(compiler_cli, "load_schema_registry", lambda _: REGISTRY)
    monkeypatch.setattr(
        compiler_cli,
        "load_template_registry",
        lambda _: TemplateRegistry(version="tpl-v1+empty", templates=()),
    )
    monkeypatch.setattr(compiler_cli, "select_table_provider", lambda _: None)
    monkeypatch.setattr(compiler_cli, "Session", TrackingSession)
    monkeypatch.setattr(compiler_cli, "WeKnoraClient", FakeWeKnoraClient, raising=False)
    monkeypatch.setattr(
        compiler_cli, "WeKnoraDocumentSource", FakeWeKnoraSource, raising=False
    )
    monkeypatch.setattr(compiler_cli, "DirectoryDocumentSource", RejectDirectorySource)
    monkeypatch.setattr(compiler_cli, "ExtractionPipeline", FakePipeline)

    assert (
        compiler_cli.main(
            [
                "extract",
                "--source",
                "weknora",
                "--space-id",
                "space-1",
                "--parser-fingerprint",
                "parser-v1",
                "--knowledge-id",
                "knowledge-1",
                "--knowledge-id",
                "knowledge-2",
                "--product-id",
                "PRODUCT01",
                "--product-name",
                "Product One",
                "--db-url",
                db_url,
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )
        == 0
    )

    source_kwargs = captured["source_kwargs"]
    assert isinstance(source_kwargs, dict)
    assert source_kwargs["client"] is captured["client"]
    assert source_kwargs["parser_fingerprint"] == "parser-v1"
    assert source_kwargs["source_max_documents_per_batch"] == 3
    assert source_kwargs["source_max_batch_bytes"] == 4_000
    assert source_kwargs["source_max_batch_pages"] == 50
    assert source_kwargs["source_max_batch_chunks"] == 600
    run_kwargs = captured["run_kwargs"]
    assert isinstance(run_kwargs, dict)
    assert run_kwargs["product_dir"] is None
    assert run_kwargs["product_id"] == "PRODUCT01"
    assert run_kwargs["product_name"] == "Product One"
    assert run_kwargs["source_request"].knowledge_ids == (
        "knowledge-1",
        "knowledge-2",
    )
    assert captured["client_closed"] is True


@pytest.mark.parametrize(
    "failure_stage",
    [
        "schema",
        "judge_constructor",
        "engine_constructor",
        "weknora_constructor",
        "scope",
        "source_constructor",
        "pipeline_constructor",
        "run",
        "source_aclose",
        "judge_aclose",
    ],
)
async def test_production_extract_attempts_all_registered_resource_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    events: list[str] = []
    resources: list[str] = []

    class ClosableModel:
        def __init__(self, name: str) -> None:
            self.name = name
            resources.append(name)

        async def complete(self, system: str, user: str) -> str:
            del system, user
            return "[]"

        async def aclose(self) -> None:
            events.append(f"close:{self.name}")
            if failure_stage == f"{self.name}_aclose":
                raise RuntimeError(f"boom:{failure_stage}")

    class FakeEngine:
        def __init__(self) -> None:
            events.append("create:engine")

        def dispose(self) -> None:
            events.append("dispose:engine")

    class FakeSession:
        def __init__(self, engine: object) -> None:
            del engine

        def __enter__(self) -> object:
            return object()

        def __exit__(self, *args: object) -> None:
            del args

    class FakeSource:
        pass

    class FakePipeline:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            if failure_stage == "pipeline_constructor":
                raise RuntimeError(f"boom:{failure_stage}")

        async def run(self, **kwargs: object) -> SimpleNamespace:
            if failure_stage == "run":
                raise RuntimeError(f"boom:{failure_stage}")
            run_dir = kwargs["run_dir"]
            assert isinstance(run_dir, Path)
            return SimpleNamespace(
                manifest=RunManifest(run_id="production", product_dir=""),
                records=[],
                pred_path=run_dir / "pred.jsonl",
            )

    settings = HarnessSettings(
        weknora_base_url="https://weknora.invalid",
        weknora_api_key="secret",
        db_url="sqlite:///unused.db",
        llm_base_url="https://llm.invalid",
        llm_api_key="secret",
        llm_model_judge_fallback="judge-model",
        judge_mode="gateway",
    )
    model_client = ClosableModel("model")

    def load_registry(_: object) -> SchemaRegistry:
        if failure_stage == "schema":
            raise RuntimeError(f"boom:{failure_stage}")
        return REGISTRY

    def make_judge_client(**kwargs: object) -> ClosableModel:
        del kwargs
        if failure_stage == "judge_constructor":
            raise RuntimeError(f"boom:{failure_stage}")
        return ClosableModel("judge")

    def make_fake_engine(_: str) -> FakeEngine:
        if failure_stage == "engine_constructor":
            raise RuntimeError(f"boom:{failure_stage}")
        return FakeEngine()

    def make_source_client(_: HarnessSettings) -> ClosableModel:
        if failure_stage == "weknora_constructor":
            raise RuntimeError(f"boom:{failure_stage}")
        return ClosableModel("source")

    def load_fake_scope(session: object, space_id: str) -> object:
        del session, space_id
        if failure_stage == "scope":
            raise RuntimeError(f"boom:{failure_stage}")
        return object()

    def make_document_source(**kwargs: object) -> FakeSource:
        del kwargs
        if failure_stage == "source_constructor":
            raise RuntimeError(f"boom:{failure_stage}")
        return FakeSource()

    monkeypatch.setattr(compiler_cli, "load_settings", lambda **_: settings)
    monkeypatch.setattr(
        compiler_cli, "build_client", lambda *args: (model_client, "model")
    )
    monkeypatch.setattr(compiler_cli, "load_schema_registry", load_registry)
    monkeypatch.setattr(compiler_cli, "OpenAICompatClient", make_judge_client)
    monkeypatch.setattr(
        compiler_cli,
        "load_template_registry",
        lambda _: TemplateRegistry(version="tpl-v1+empty", templates=()),
    )
    monkeypatch.setattr(compiler_cli, "make_engine", make_fake_engine)
    monkeypatch.setattr(compiler_cli, "WeKnoraClient", make_source_client)
    monkeypatch.setattr(compiler_cli, "Session", FakeSession)
    monkeypatch.setattr(compiler_cli, "load_scope", load_fake_scope)
    monkeypatch.setattr(compiler_cli, "WeKnoraDocumentSource", make_document_source)
    monkeypatch.setattr(compiler_cli, "ExtractionPipeline", FakePipeline)
    monkeypatch.setattr(compiler_cli, "select_table_provider", lambda _: None)
    args = argparse.Namespace(
        replay_dir=None,
        model=None,
        schema_dir=tmp_path / "schema",
        templates_dir=None,
        db_url=None,
        space_id="space-1",
        parser_fingerprint="parser-v1",
        concurrency=1,
        product_id="PRODUCT01",
        product_name="Product One",
        run_dir=tmp_path / "run",
        knowledge_ids=["knowledge-1"],
        line_key="t",
        resume=False,
    )

    with pytest.raises(RuntimeError, match=rf"^boom:{failure_stage}$"):
        await compiler_cli._cmd_extract(args)  # noqa: SLF001

    for resource in resources:
        assert f"close:{resource}" in events
    if "create:engine" in events:
        assert "dispose:engine" in events


@pytest.mark.parametrize(
    "failure_stage",
    [
        "schema",
        "judge_constructor",
        "source_constructor",
        "pipeline_constructor",
        "run",
        "judge_aclose",
    ],
)
async def test_replay_extract_attempts_all_registered_resource_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    events: list[str] = []
    resources: list[str] = []

    class ClosableModel:
        def __init__(self, name: str) -> None:
            self.name = name
            resources.append(name)

        async def complete(self, system: str, user: str) -> str:
            del system, user
            return "[]"

        async def aclose(self) -> None:
            events.append(f"close:{self.name}")
            if failure_stage == f"{self.name}_aclose":
                raise RuntimeError(f"boom:{failure_stage}")

    class FakeDirectorySource:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            if failure_stage == "source_constructor":
                raise RuntimeError(f"boom:{failure_stage}")

    class FakePipeline:
        def __init__(self, **kwargs: object) -> None:
            del kwargs
            if failure_stage == "pipeline_constructor":
                raise RuntimeError(f"boom:{failure_stage}")

        async def run(self, **kwargs: object) -> SimpleNamespace:
            if failure_stage == "run":
                raise RuntimeError(f"boom:{failure_stage}")
            run_dir = kwargs["run_dir"]
            assert isinstance(run_dir, Path)
            return SimpleNamespace(
                manifest=RunManifest(run_id="replay", product_dir=str(tmp_path)),
                records=[],
                pred_path=run_dir / "pred.jsonl",
            )

    settings = HarnessSettings(
        weknora_base_url="https://unused.invalid",
        weknora_api_key="unused",
        llm_base_url="https://llm.invalid",
        llm_api_key="secret",
        llm_model_judge_fallback="judge-model",
        judge_mode="gateway",
    )
    model_client = ClosableModel("model")

    def load_registry(_: object) -> SchemaRegistry:
        if failure_stage == "schema":
            raise RuntimeError(f"boom:{failure_stage}")
        return REGISTRY

    def make_judge_client(**kwargs: object) -> ClosableModel:
        del kwargs
        if failure_stage == "judge_constructor":
            raise RuntimeError(f"boom:{failure_stage}")
        return ClosableModel("judge")

    monkeypatch.setattr(compiler_cli, "load_settings", lambda: settings)
    monkeypatch.setattr(
        compiler_cli, "build_client", lambda *args: (model_client, "model")
    )
    monkeypatch.setattr(compiler_cli, "load_schema_registry", load_registry)
    monkeypatch.setattr(compiler_cli, "OpenAICompatClient", make_judge_client)
    monkeypatch.setattr(
        compiler_cli,
        "load_template_registry",
        lambda _: TemplateRegistry(version="tpl-v1+empty", templates=()),
    )
    monkeypatch.setattr(compiler_cli, "DirectoryDocumentSource", FakeDirectorySource)
    monkeypatch.setattr(compiler_cli, "ExtractionPipeline", FakePipeline)
    monkeypatch.setattr(compiler_cli, "select_table_provider", lambda _: None)
    args = argparse.Namespace(
        replay_dir=None,
        model=None,
        schema_dir=tmp_path / "schema",
        templates_dir=None,
        replay_identity="fixture-1",
        parser_fingerprint="parser-v1",
        concurrency=1,
        product_dir=tmp_path / "product",
        run_dir=tmp_path / "run",
        line_key="t",
        resume=False,
    )

    with pytest.raises(RuntimeError, match=rf"^boom:{failure_stage}$"):
        await compiler_cli._cmd_extract_replay(args)  # noqa: SLF001

    for resource in resources:
        assert f"close:{resource}" in events


@pytest.mark.parametrize(
    "omitted_flag",
    ["--source", "--space-id", "--parser-fingerprint", "--knowledge-id"],
)
def test_production_extract_missing_source_identity_never_dispatches_or_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    omitted_flag: str,
) -> None:
    argv = [
        "extract",
        "--source",
        "weknora",
        "--space-id",
        "space-1",
        "--parser-fingerprint",
        "parser-v1",
        "--knowledge-id",
        "knowledge-1",
        "--product-id",
        "PRODUCT01",
        "--product-name",
        "Product One",
        "--db-url",
        "sqlite:///scope.db",
        "--run-dir",
        str(tmp_path / "run"),
    ]
    index = argv.index(omitted_flag)
    del argv[index : index + 2]

    async def reject_dispatch(args: object) -> int:
        del args
        pytest.fail("invalid production arguments must not dispatch")

    monkeypatch.setattr(compiler_cli, "_cmd_extract", reject_dispatch)
    with pytest.raises(SystemExit) as caught:
        compiler_cli.main(argv)

    assert caught.value.code == 2


def test_production_extract_rejects_directory_source_value(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        compiler_cli.main(
            [
                "extract",
                "--source",
                "directory",
                "--space-id",
                "space-1",
                "--parser-fingerprint",
                "parser-v1",
                "--knowledge-id",
                "knowledge-1",
                "--product-id",
                "PRODUCT01",
                "--product-name",
                "Product One",
                "--run-dir",
                str(tmp_path / "run"),
            ]
        )

    assert caught.value.code == 2
