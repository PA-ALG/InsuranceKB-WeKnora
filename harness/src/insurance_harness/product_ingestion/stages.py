"""Platform-owned short upload/source/routing jobs and atomic checkpoint adapter."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from insurance_harness.jobs import NonRetryableJobError, RetryableJobError
from insurance_harness.knowledge_compiler.schema_pack_catalog_830_g3 import (
    SchemaPackCatalogV1,
)
from insurance_harness.product_ingestion.artifact_models import (
    ArtifactDraft,
    ArtifactOrigin,
)
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.identity import prepare_identity_routing
from insurance_harness.product_ingestion.models import (
    OriginalKnowledgeRef,
    ProductRunState,
    ProductScope,
)
from insurance_harness.product_ingestion.platform import decode_source_snapshot
from insurance_harness.product_ingestion.processing_receipts import processing_summary
from insurance_harness.product_ingestion.store import (
    ProductIngestionStore,
    needs_confirmation_error,
)
from insurance_harness.product_ingestion.upload_resolution import lookup_material
from insurance_harness.service_shell.worker import HandlerRegistry, HandlerResult


def json_bytes(value) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=lambda item: item.model_dump(mode="json"),
    ).encode()


def artifact(
    kind,
    key,
    payload,
    dependency_sha256,
    *,
    origin=ArtifactOrigin.RULE,
    call_id=None,
    contract_version="1",
):
    return ArtifactDraft(
        artifact_kind=kind,
        artifact_key=key,
        contract_name=f"product-{kind}.v{contract_version}",
        contract_version=contract_version,
        dependency_sha256=dependency_sha256,
        payload=payload,
        payload_sha256=hashlib.sha256(payload).hexdigest(),
        origin=origin,
        origin_call_id=call_id,
    )


@dataclass(frozen=True)
class StageOutput:
    drafts: tuple[ArtifactDraft, ...] = ()
    state: ProductRunState = ProductRunState.SUCCEEDED


class SourcePlatform(Protocol):
    async def lookup_upload(
        self, scope: ProductScope, run_id: str, ordinal: int
    ) -> dict | None: ...
    async def lookup_file_by_sha256(
        self, scope: ProductScope, sha256: str, *, knowledge_id: str | None = None
    ) -> dict | None: ...

    async def capture_source(
        self, scope: ProductScope, knowledge_id: str, attempt: int
    ) -> bytes: ...

    async def get_reparse_receipt(
        self, scope: ProductScope, run_id: str, ordinal: int, recovery_key: str
    ) -> dict | None: ...

    async def reparse_upload(
        self,
        scope: ProductScope,
        run_id: str,
        ordinal: int,
        expected_parse_attempt: int,
        recovery_key: str,
        deadline_at: datetime,
    ) -> dict: ...


def register_stage_handlers(
    registry: HandlerRegistry,
    *,
    store: ProductIngestionStore,
    artifacts: ProductArtifactStore,
    scopes: Mapping[str, ProductScope],
    handlers: Mapping[str, Callable[..., Awaitable[StageOutput]]],
):
    for name, execute in handlers.items():

        async def handle(job, name=name, execute=execute):
            scope = scopes.get(job.space_id)
            if scope is None or job.payload.get("stage_key") != name:
                raise NonRetryableJobError("PRODUCT_STAGE_SCOPE_MISMATCH")
            run_id = job.payload["run_id"]
            run = store.get_run(scope=scope, run_id=run_id)
            stage = next(
                (
                    row
                    for row in store.list_stages(scope=scope, run_id=run_id)
                    if row.stage_key == name and row.job_id == job.id
                ),
                None,
            )
            if stage is None:
                raise NonRetryableJobError("PRODUCT_STAGE_BINDING_MISSING")
            result = await execute(scope, run, stage, job)
            writes = (
                await asyncio.to_thread(
                    artifacts.prepare_artifact_writes,
                    scope=scope,
                    run_id=run_id,
                    stage_key=name,
                    job_id=job.id,
                    generation=job.lease_generation,
                    drafts=result.drafts,
                )
                if result.drafts
                else ()
            )
            settled = store.prepare_stage_settlement(
                scope=scope,
                run_id=run_id,
                stage_id=stage.stage_id,
                job_id=job.id,
                generation=job.lease_generation,
                state=result.state,
            )
            return HandlerResult(
                domain_writes=(*writes, *settled.domain_writes), events=settled.events
            )

        registry.register(f"product_stage_{name}", handle)


def read_source_snapshots(artifacts, scope, run_id, *, public_keys):
    rows = artifacts.list_effective_artifacts(
        scope=scope, run_id=run_id, artifact_kind="source_snapshot"
    )
    result = {}
    for row in rows:
        # Expected identity is the immutable artifact key, never a model value.
        envelope = json.loads(row.payload)
        receipt = envelope["snapshot"]["receipt"]
        result[row.artifact_key] = decode_source_snapshot(
            row.payload,
            scope=scope,
            knowledge_id=row.artifact_key,
            parse_attempt=receipt["parse_attempt"],
            public_keys=public_keys,
        )
    return result


async def load_source_blocks(artifacts, scope, run_id, *, public_keys):
    def load():
        return tuple(
            block
            for source in read_source_snapshots(
                artifacts, scope, run_id, public_keys=public_keys
            ).values()
            for block in source.blocks
        )

    return await asyncio.to_thread(load)


def register_source_stages(
    registry,
    *,
    store,
    artifacts,
    scopes,
    platform: SourcePlatform,
    public_keys: Mapping[str, Ed25519PublicKey],
    catalog: SchemaPackCatalogV1,
    now=lambda: datetime.now(UTC),
):
    async def uploads(scope, run, stage, job):
        store.processing_recovery_plan(scope=scope, run_id=run.run_id)
        if run.uploads_sealed_at is not None:
            return StageOutput()
        if now() >= run.upload_deadline_at:
            raise NonRetryableJobError("UPLOAD_DEADLINE_EXCEEDED")
        manifest = store.get_upload_manifest(scope=scope, run_id=run.run_id)
        attached = {row.upload_ordinal for row in run.materials}
        missing = False
        for ordinal in range(run.expected_upload_count):
            if ordinal in attached:
                continue
            item = await lookup_material(platform, scope, run.run_id, ordinal, manifest)
            if item is None:
                missing = True
                continue
            run = store.attach_original(
                scope=scope,
                run_id=run.run_id,
                expected_version=run.version,
                original=OriginalKnowledgeRef(
                    knowledge_id=item["knowledge_id"],
                    original_filename=(
                        manifest.materials[ordinal].original_filename
                        if manifest is not None
                        else item["file_name"]
                    ),
                    upload_ordinal=ordinal,
                ),
            )
        if missing:
            raise RetryableJobError("WAITING_FOR_ORIGINAL_UPLOADS")
        store.seal_uploads(scope=scope, run_id=run.run_id, expected_version=run.version)
        return StageOutput()

    async def sources(scope, run, stage, job):
        recovery = store.processing_recovery_plan(scope=scope, run_id=run.run_id)
        if now() >= run.source_deadline_at:
            raise NonRetryableJobError("SOURCE_PARSE_DEADLINE_EXCEEDED")
        prior = {}
        reuse_sealed = recovery is not None and recovery.mode in {
            "REUSE_SEALED_SOURCES",
            "REPLAY_RECORDED_IDENTITY",
        }
        if run.retry_of_run_id and (recovery is None or reuse_sealed):
            prior = {
                row.artifact_key: row
                for row in await asyncio.to_thread(
                    artifacts.list_artifacts,
                    scope=scope,
                    run_id=run.retry_of_run_id,
                    artifact_kind="source_snapshot",
                )
            }
        if reuse_sealed:
            expected = {
                item.knowledge_id: item.payload_sha256 for item in recovery.source_snapshots
            }
            if set(prior) != set(expected) or any(
                hashlib.sha256(row.payload).hexdigest() != expected[key]
                or row.payload_sha256 != expected[key]
                for key, row in prior.items()
            ):
                raise NonRetryableJobError("RECOVERY_SOURCE_CHECKPOINT_CHANGED")
        drafts = []
        processing = []
        # Resolve all parse states first; do not capture a partial group while
        # a known sibling has failed. Existing platform source cache is durable.
        current = []
        lookup_run = run
        while lookup_run.retry_of_run_id:
            lookup_run = store.get_run(scope=scope, run_id=lookup_run.retry_of_run_id)
        if recovery is not None and lookup_run.run_id != recovery.upload_run_id:
            raise NonRetryableJobError("RECOVERY_UPLOAD_BINDING_CHANGED")
        manifest = store.get_upload_manifest(scope=scope, run_id=run.run_id)
        for material in run.materials:
            item = await lookup_material(
                platform,
                scope,
                lookup_run.run_id,
                material.upload_ordinal,
                manifest,
                knowledge_id=material.knowledge_id,
            )
            if item is None or item["knowledge_id"] != material.knowledge_id:
                raise NonRetryableJobError("ORIGINAL_UPLOAD_BINDING_CHANGED")
            native_receipt = item.get("processing_receipt")
            if native_receipt is not None:
                if item.get("processing_receipt_parse_attempt") != item["parse_attempt"]:
                    raise NonRetryableJobError("SOURCE_PROCESSING_RECEIPT_ATTEMPT_CHANGED")
                await asyncio.to_thread(
                    artifacts.record_source_processing_attempt,
                    scope=scope,
                    run_id=run.run_id,
                    stage=stage,
                    job=job,
                    knowledge_id=material.knowledge_id,
                    parse_attempt=item["parse_attempt"],
                    receipt=native_receipt,
                )
            current.append((material, item))
        for material, item in current:
            source_run_id = item.get("original_upload_run_id", lookup_run.run_id)
            source_ordinal = item.get("original_upload_ordinal", material.upload_ordinal)
            if item["parse_status"] in {"failed", "error"} and (
                not source_run_id or type(source_ordinal) is not int or source_ordinal < 0
            ):
                raise NonRetryableJobError("SOURCE_REPARSE_BINDING_UNAVAILABLE")
            recovery_key = hashlib.sha256(
                (
                    f"product-source-reparse.830.v1\0{scope.tenant_id}\0{scope.space_id}\0"
                    f"{run.run_id}\0{source_run_id}\0{source_ordinal}"
                ).encode()
            ).hexdigest()
            receipt = (
                await platform.get_reparse_receipt(
                    scope, source_run_id, source_ordinal, recovery_key
                )
                if item["parse_status"] in {"failed", "error"}
                else None
            )
            if receipt is not None:
                try:
                    receipt_deadline = datetime.fromisoformat(
                        receipt["deadline_at"].replace("Z", "+00:00")
                    )
                except (KeyError, TypeError, ValueError):
                    raise NonRetryableJobError("REPARSE_RECEIPT_BINDING_CHANGED") from None
                if (
                    receipt.get("contract") != "g3-platform-bound-reparse.830.v1"
                    or receipt.get("run_id") != source_run_id
                    or receipt.get("ordinal") != source_ordinal
                    or receipt.get("knowledge_id") != material.knowledge_id
                    or receipt.get("recovery_key") != recovery_key
                    or type(receipt.get("expected_parse_attempt")) is not int
                    or receipt.get("parse_attempt") != receipt["expected_parse_attempt"] + 1
                    or item["parse_attempt"]
                    not in {receipt["expected_parse_attempt"], receipt["parse_attempt"]}
                    or receipt_deadline.tzinfo is None
                    or receipt_deadline != run.source_deadline_at
                ):
                    raise NonRetryableJobError("REPARSE_RECEIPT_BINDING_CHANGED")
                if receipt["dispatch_state"] in {"unknown", "interrupted"}:
                    raise needs_confirmation_error("REPARSE_DISPATCH_UNKNOWN")
                if receipt["dispatch_state"] == "failed":
                    raise NonRetryableJobError("SOURCE_REPARSE_FAILED")
            if item["parse_status"] in {"failed", "error"}:
                if receipt is None:
                    receipt = await platform.reparse_upload(
                        scope,
                        source_run_id,
                        source_ordinal,
                        item["parse_attempt"],
                        recovery_key,
                        run.source_deadline_at,
                    )
                    if (
                        receipt.get("contract") != "g3-platform-bound-reparse.830.v1"
                        or receipt.get("run_id") != source_run_id
                        or receipt.get("ordinal") != source_ordinal
                        or receipt.get("knowledge_id") != material.knowledge_id
                        or receipt.get("expected_parse_attempt") != item["parse_attempt"]
                        or receipt.get("parse_attempt") != item["parse_attempt"] + 1
                        or receipt.get("recovery_key") != recovery_key
                        or datetime.fromisoformat(receipt["deadline_at"].replace("Z", "+00:00"))
                        != run.source_deadline_at
                    ):
                        raise NonRetryableJobError("REPARSE_RECEIPT_BINDING_CHANGED")
                if receipt["dispatch_state"] in {"unknown", "interrupted"}:
                    raise needs_confirmation_error("REPARSE_DISPATCH_UNKNOWN")
                if receipt["dispatch_state"] == "failed":
                    raise NonRetryableJobError("SOURCE_REPARSE_FAILED")
                raise RetryableJobError("WAITING_FOR_SOURCE_REPARSE")
            if item["parse_status"] != "completed":
                if recovery is not None:
                    raise NonRetryableJobError("RECOVERY_SOURCE_NOT_COMPLETED")
                raise RetryableJobError("WAITING_FOR_SOURCE_PARSE")
        for material, item in current:
            saved = prior.get(material.knowledge_id)
            if saved is not None:
                raw = saved.payload
            else:
                raw = await platform.capture_source(
                    scope, material.knowledge_id, item["parse_attempt"]
                )
            try:
                decoded = await asyncio.to_thread(
                    decode_source_snapshot,
                    raw,
                    scope=scope,
                    knowledge_id=material.knowledge_id,
                    parse_attempt=item["parse_attempt"],
                    public_keys=public_keys,
                )
            except ValueError:
                if recovery is not None:
                    raise NonRetryableJobError("RECOVERY_SOURCE_CHECKPOINT_INVALID") from None
                raise

            processing.append(
                (
                    material.knowledge_id,
                    decoded.snapshot.get("processing_receipt"),
                    saved is not None or recovery is not None,
                )
            )
            if material.source is not None and (
                decoded.snapshot["receipt"]["revision_source_id"],
                decoded.snapshot["receipt"]["file_sha256"],
            ) != (material.source.source_revision_id, material.source.source_sha256):
                raise needs_confirmation_error("SOURCE_REVISION_CHANGED")
            drafts.append(
                artifact(
                    "source_snapshot",
                    material.knowledge_id,
                    raw,
                    stage.dependency_sha256,
                    origin=ArtifactOrigin.PLATFORM_SOURCE,
                )
            )
        drafts.append(
            artifact(
                "source_processing_summary",
                "product",
                json_bytes(processing_summary(processing)),
                stage.dependency_sha256,
                origin=ArtifactOrigin.PLATFORM_SOURCE,
            )
        )
        return StageOutput(tuple(drafts))

    async def routing(scope, run, stage, job):
        snapshots = await asyncio.to_thread(
            read_source_snapshots, artifacts, scope, run.run_id, public_keys=public_keys
        )
        if set(snapshots) != {row.knowledge_id for row in run.materials}:
            raise NonRetryableJobError("SOURCE_CHECKPOINT_SET_MISMATCH")
        if any(not source.blocks for source in snapshots.values()):
            raise needs_confirmation_error("FIRST_PAGE_PRODUCT_NAME_UNAVAILABLE")
        try:
            payload = prepare_identity_routing(snapshots, run.materials, catalog)
        except ValueError as error:
            raise needs_confirmation_error(str(error)) from error

        return StageOutput(
            (artifact("routing", "product", json_bytes(payload), stage.dependency_sha256),)
        )

    register_stage_handlers(
        registry,
        store=store,
        artifacts=artifacts,
        scopes=scopes,
        handlers={"uploads": uploads, "source": sources, "routing": routing},
    )
