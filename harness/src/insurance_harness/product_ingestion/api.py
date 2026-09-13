"""Versioned platform-to-platform product admission and safe status surface."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Annotated

from fastapi import APIRouter, FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.jobs.errors import SpaceScopeError
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.progression import admit_uploads
from insurance_harness.product_ingestion.store import ProductIngestionStore
from insurance_harness.service_shell.apps import PrincipalDependency
from insurance_harness.service_shell.principal import (
    AuthorizationError,
    ServiceCapability,
    require_service_capability,
)


class CreateRun(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    idempotency_key: str = Field(min_length=1, max_length=160)
    expected_upload_count: int = Field(ge=1)


class RetryFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    field_keys: list[str] = Field(min_length=1)


def install_product_api(
    app: FastAPI,
    *,
    store: ProductIngestionStore,
    artifacts: ProductArtifactStore,
    scopes: Mapping[str, ProductScope],
    max_upload_files: int,
) -> None:
    """Mount only when composition explicitly enables the configured service.

    Scope comes from platform configuration, never a request body's tenant or KB.
    The existing provider authenticates a service principal; browser JWTs are
    checked by the WeKnora gateway, and are not reinterpreted here as system keys.
    """
    if not scopes or max_upload_files < 1:
        raise ValueError("product ingestion needs exact scopes and capacity")
    router = APIRouter(prefix="/product-ingestion/v1/spaces/{space_id}/runs")

    def authorize(space_id, principal, *, write=False):
        require_service_capability(
            principal,
            space_id=space_id,
            capability=(
                ServiceCapability.MANAGE_PRODUCT_INGESTION
                if write
                else ServiceCapability.READ_PRODUCT_INGESTION
            ),
        )
        scope = scopes.get(space_id)
        if scope is None:
            raise AuthorizationError("product_scope_unconfigured")
        return scope

    def read_payload(scope, run_id):
        try:
            run = store.get_run(scope=scope, run_id=run_id)
            stages = store.list_status_stages(scope=scope, run_id=run_id)
            fields = store.list_field_attempts(scope=scope, run_id=run_id)
        except SpaceScopeError as error:
            raise HTTPException(404, "product_run_not_found") from error
        payload = run.model_dump(mode="json")
        stage_metrics = artifacts.get_stage_call_metrics(scope=scope, run_id=run_id)
        payload["model_call_count"] = (
            sum(row.model_call_count for row in stages if row.stage_key == "extract")
            + stage_metrics.model_call_count
        )
        payload["semantic_model_call_count"] = payload["model_call_count"]
        payload["source_model_call_count"] = None
        payload["model_call_count_complete"] = False
        summaries = artifacts.list_artifacts(
            scope=scope, run_id=run_id, artifact_kind="source_processing_summary"
        )
        if summaries:
            summary = json.loads(summaries[0].payload)
            payload["source_processing"] = {
                **summary,
                "materials": [
                    {
                        **row,
                        "file_name": next(
                            (
                                item.original_filename
                                for item in run.materials
                                if item.knowledge_id == row["knowledge_id"]
                            ),
                            None,
                        ),
                    }
                    for row in summary["materials"]
                ],
            }
            payload["source_model_call_count"] = summary["model_call_count"]
            payload["recorded_source_model_call_count"] = summary["recorded_model_call_count"]
            payload["model_call_count"] += summary["recorded_model_call_count"]
            payload["model_call_count_complete"] = (
                run.finished_at is not None
                and summary["model_call_count_complete"]
                and stage_metrics.unsettled_call_count == 0
                and store.unsettled_dispatch_count(scope=scope, run_id=run_id) == 0
            )
        for key, value in stage_metrics.usage.items():
            payload["usage"][key] = payload["usage"].get(key, 0) + value
        payload["wiki_knowledge_base_id"] = scope.wiki_knowledge_base_id
        payload["counts"] = {
            key: payload[key] for key in ("success_count", "missing_count", "failure_count")
        }
        payload["stages"] = [
            {**row.model_dump(mode="json"), "name": row.stage_key} for row in stages
        ]
        payload["stage"] = next((row.stage_key for row in stages if row.finished_at is None), None)
        payload["reason"] = run.terminal_reason
        # Raw model bytes and unvalidated field values never enter the normal status response.
        payload["fields"] = [
            {
                "field_key": row.field_key,
                "outcome": row.outcome.value,
                "reason": row.reason,
                "attempt": row.attempt,
            }
            for row in fields
        ]
        return {"success": True, "data": payload}

    @router.post("", status_code=201)
    def create(space_id: str, request: CreateRun, principal: PrincipalDependency):
        scope = authorize(space_id, principal, write=True)
        if request.expected_upload_count > max_upload_files:
            raise HTTPException(422, "upload_capacity_exceeded")
        try:
            run = store.create_run(
                scope=scope,
                idempotency_key=request.idempotency_key,
                expected_upload_count=request.expected_upload_count,
            )
            # Idempotent admission, never inline parsing/extraction/publication.
            admit_uploads(store, scope, run.run_id)
        except ValueError as error:
            raise HTTPException(409, "product_run_conflict") from error
        return read_payload(scope, run.run_id)

    @router.get("")
    def listing(
        space_id: str,
        principal: PrincipalDependency,
        limit: Annotated[int, Query(ge=1, le=100)] = 30,
    ):
        scope = authorize(space_id, principal)
        return {
            "success": True,
            "data": {
                "runs": [
                    read_payload(scope, run.run_id)["data"]
                    for run in store.list_runs(scope=scope, limit=limit)
                ]
            },
        }

    @router.get("/{run_id}")
    def read(space_id: str, run_id: str, principal: PrincipalDependency):
        return read_payload(authorize(space_id, principal), run_id)

    @router.post("/{run_id}/retry-fields", status_code=201)
    def retry(space_id: str, run_id: str, request: RetryFields, principal: PrincipalDependency):
        scope = authorize(space_id, principal, write=True)
        if len(request.field_keys) != len(set(request.field_keys)):
            raise HTTPException(422, "duplicate_field_keys")
        try:
            rows = store.list_field_attempts(
                scope=scope, run_id=run_id, field_keys=request.field_keys
            )
            latest = {row.field_key: row for row in rows}
            if set(latest) != set(request.field_keys) or any(
                row.outcome.value != "extraction_failed" for row in latest.values()
            ):
                raise HTTPException(409, "only_failed_fields_can_be_retried")
            attempt_ids = sorted(row.attempt_id for row in latest.values())
            key = hashlib.sha256(json.dumps(attempt_ids).encode()).hexdigest()
            run = store.retry_fields(
                scope=scope,
                run_id=run_id,
                failed_attempt_ids=attempt_ids,
                idempotency_key="field-retry:" + key,
            )
            admit_uploads(store, scope, run.run_id)
        except SpaceScopeError as error:
            raise HTTPException(404, "product_run_not_found") from error
        except ValueError as error:
            raise HTTPException(409, "product_retry_conflict") from error
        return read_payload(scope, run.run_id)

    app.include_router(router)
