"""Shared builders for the OpenSpec 017 source-pipeline tests."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest

from insurance_harness.goldenset.pdf import PageText
from insurance_harness.schemas import FieldSpec, ProductLineSchema, SchemaRegistry
from insurance_harness.sources import (
    DirectorySourceRequest,
    MaterializedBatch,
    SourceDocument,
    SourceRevision,
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
            fields=(
                FieldSpec(
                    name="犹豫期",
                    field_id="hesitation_period",
                    source_sheet="t",
                ),
            ),
        )
    },
    glossary=(),
)


class NoModelCalls:
    async def complete(self, system: str, user: str) -> str:
        del system, user
        pytest.fail("load must not call a model")


class CountingModel:
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


class BlockingModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def complete(self, system: str, user: str) -> str:
        del system, user
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


class TrackingSource:
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


class ConcurrentSource:
    def __init__(self, document: SourceDocument) -> None:
        self.document = document
        self.entered = 0
        self.both_entered = asyncio.Event()

    @asynccontextmanager
    async def materialize(
        self, request: DirectorySourceRequest
    ) -> AsyncIterator[MaterializedBatch]:
        runtime_path = request.product_dir / "runtime-only.pdf"
        try:
            runtime_path.write_bytes(b"runtime")
            self.entered += 1
            if self.entered == 2:
                self.both_entered.set()
            await self.both_entered.wait()
            yield MaterializedBatch(
                documents=(self.document,),
                local_paths={self.document.source_id: runtime_path},
            )
        finally:
            runtime_path.unlink(missing_ok=True)


def source_document() -> SourceDocument:
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


def assert_no_committed_artifacts(*run_dirs: Path) -> None:
    artifact_names = (
        "pred.jsonl",
        "manifest.json",
        "judge-queue.jsonl",
        "dead-letters.jsonl",
    )
    assert not any(
        (run_dir / name).exists()
        for run_dir in run_dirs
        for name in artifact_names
    )
