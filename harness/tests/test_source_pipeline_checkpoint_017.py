"""Checkpoint and run-lock contracts for source pipelines."""

import asyncio
import json
import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path
from types import MethodType

import pytest

import insurance_harness.compiler.pipeline as pipeline_module
from insurance_harness.compiler.judge import JudgeDispatcher
from insurance_harness.compiler.models import RunManifest
from insurance_harness.compiler.pipeline import ExtractionPipeline
from insurance_harness.db.scope import ScopeViolation
from insurance_harness.schemas import ProductLineSchema, SchemaRegistry
from insurance_harness.sources import (
    DirectorySourceRequest,
    ProcessedAtOrdering,
    SourceRevision,
)
from tests.support.source_pipeline import (
    MODEL_REGISTRY,
    REGISTRY,
    CountingModel,
    NoModelCalls,
    TrackingSource,
    assert_no_committed_artifacts,
    source_document,
)


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
    source = TrackingSource(source_document(), runtime_path)
    client = CountingModel()
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
                    ordering=ProcessedAtOrdering(
                        value=datetime(1970, 1, 1, tzinfo=UTC)
                    ),
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
    source = TrackingSource(source_document(), tmp_path / "runtime.pdf")
    client = CountingModel()
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
    source = TrackingSource(source_document(), tmp_path / "runtime.pdf")
    pipeline = ExtractionPipeline(
        client=CountingModel(),
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
    source = TrackingSource(source_document(), tmp_path / "runtime.pdf")
    pipeline = ExtractionPipeline(
        client=CountingModel(),
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


async def test_resume_rejects_checkpoint_from_a_different_run_directory_pre_model(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text(
        json.dumps({"planCode": "SOURCE01"}), encoding="utf-8"
    )
    source = TrackingSource(source_document(), tmp_path / "runtime.pdf")
    client = CountingModel()
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
    assert_no_committed_artifacts(old_run_dir, new_run_dir)


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
    source = TrackingSource(source_document(), tmp_path / "runtime.pdf")
    client = CountingModel()
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
        JudgeDispatcher(mode="gateway", client=CountingModel())
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
    assert_no_committed_artifacts(run_dir)


async def test_non_resume_rejects_reusing_existing_thread_state_pre_model(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    source = TrackingSource(source_document(), tmp_path / "runtime.pdf")
    client = CountingModel()
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
    assert_no_committed_artifacts(run_dir)


async def test_resume_without_checkpoint_state_fails_closed_pre_model(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    source = TrackingSource(source_document(), tmp_path / "runtime.pdf")
    client = CountingModel()
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
    assert_no_committed_artifacts(run_dir)


async def test_completed_run_rejects_alternate_fresh_checkpoint_pre_source(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "completed-run"
    first_source = TrackingSource(source_document(), tmp_path / "first-runtime.pdf")
    first = ExtractionPipeline(
        client=NoModelCalls(),
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
    rejected_source = TrackingSource(
        source_document(), tmp_path / "rejected-runtime.pdf"
    )
    rejected = ExtractionPipeline(
        client=NoModelCalls(),
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
    source = TrackingSource(source_document(), tmp_path / "runtime.pdf")
    client = CountingModel()
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
    assert_no_committed_artifacts(run_dir)


async def test_concurrent_fresh_writers_are_serialized_by_run_directory(
    tmp_path: Path,
) -> None:
    product_dir = tmp_path / "product"
    product_dir.mkdir()
    (product_dir / "product_meta.json").write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "concurrent-run"
    request = DirectorySourceRequest(product_dir=product_dir)
    first_source = TrackingSource(source_document(), tmp_path / "runtime-first.pdf")
    second_source = TrackingSource(source_document(), tmp_path / "runtime-second.pdf")
    first = ExtractionPipeline(
        client=NoModelCalls(),
        registry=REGISTRY,
        model_id="no-model",
        source=first_source,
    )
    second = ExtractionPipeline(
        client=NoModelCalls(),
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

    verification_source = TrackingSource(
        source_document(), tmp_path / "runtime-verification.pdf"
    )
    verified = await ExtractionPipeline(
        client=NoModelCalls(),
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

    def tracked_open(
        path: str | Path,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        file_descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
        if Path(path).name == ".run.lock":
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
