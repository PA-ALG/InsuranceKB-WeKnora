"""Index authorized recorded native calls; the existing journal remains authoritative."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from insurance_harness.product_ingestion.artifact_models import StageCallSnapshot
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.discovery_stage import verify_recorded_discovery_call
from insurance_harness.product_ingestion.model_execution import matches_recorded_stage_request
from insurance_harness.product_ingestion.model_settings import (
    ModelTemplatePolicy,
    ProductModelSettings,
)
from insurance_harness.product_ingestion.models import ProductRunSnapshot, ProductScope

NativeReplayIndex = Mapping[str, tuple[StageCallSnapshot, ...]]


async def read_native_replay_calls(
    artifacts: ProductArtifactStore,
    scope: ProductScope,
    run: ProductRunSnapshot,
) -> NativeReplayIndex:
    if not run.retry_of_run_id:
        return {}
    direct, authorized = await asyncio.gather(
        asyncio.to_thread(artifacts.list_stage_calls, scope=scope, run_id=run.retry_of_run_id),
        asyncio.to_thread(
            artifacts.read_checkpoint_stage_calls,
            scope=scope,
            run_id=run.run_id,
            stage_key="discovery",
        ),
    )
    calls: dict[tuple[str, str], StageCallSnapshot] = {}
    for row in (*direct, *authorized):
        identity = (row.run_id, row.call_id)
        if identity in calls and calls[identity] != row:
            raise ValueError("native replay call identity duplicated with changed content")
        calls[identity] = row
    index: dict[str, list[StageCallSnapshot]] = {}
    for row in calls.values():
        if row.stage_key == "discovery":
            index.setdefault(row.operation_key, []).append(row)
    return {key: tuple(rows) for key, rows in index.items()}


def select_native_replay_call(
    index: NativeReplayIndex,
    *,
    operation: str,
    input_hash: str,
    settings: ProductModelSettings,
    scope: ProductScope,
    content: bytes,
    prompt: bytes,
    template: ModelTemplatePolicy,
) -> StageCallSnapshot | None:
    compatible = []
    for row in index.get(operation, ()):
        checked = verify_recorded_discovery_call(
            row,
            run_id=row.run_id,
            stage_key="discovery",
            operation=operation,
            input_sha256=input_hash,
            prompt_sha256=template.prompt_sha256,
        )
        if checked is not None and matches_recorded_stage_request(
            checked,
            settings,
            scope=scope,
            content=content,
            prompt=prompt,
            template_id=template.template_id,
        ):
            compatible.append(checked)
    if not compatible:
        return None

    # A known HTTP failure may have been retried in a later ancestor. Prefer
    # the latest complete matching result; unknown sends above still block.
    def order(row: StageCallSnapshot) -> tuple[str, str]:
        instant = row.recorded_at or row.dispatched_at
        return (instant.isoformat() if instant is not None else "", row.call_id)

    return max(compatible, key=order)
