"""Validate recovery dependencies and prepare one atomic checkpoint output.

This read/compute boundary owns source, policy and published-base compatibility.
It never dispatches model calls, commits artifacts, or advances a business job.
The existing stage adapter remains the sole owner of fenced persistence.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from enum import StrEnum
from typing import TYPE_CHECKING

from insurance_harness.jobs import NonRetryableJobError
from insurance_harness.knowledge_compiler import (
    batch_concept_compile_830_g3 as compiler,
)
from insurance_harness.knowledge_compiler import (
    batch_entity_resolution_830_g3 as resolver,
)
from insurance_harness.product_ingestion.artifact_models import ArtifactDraft, ArtifactOrigin
from insurance_harness.product_ingestion.checkpoints import RECEIPT_KIND
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductScope,
    StageSnapshot,
)
from insurance_harness.product_ingestion.platform import (
    decode_source_snapshot,
    verify_signed_snapshot,
)
from insurance_harness.product_ingestion.stages import StageOutput, artifact, json_bytes

if TYPE_CHECKING:
    from insurance_harness.product_ingestion.composition import ProductCompositionContext


class CheckpointFailureReason(StrEnum):
    PLAN = "CHECKPOINT_PLAN_INVALID"
    LOCAL_PROOF = "CHECKPOINT_LOCAL_PROOF_INVALID"
    SOURCE_BINDING = "CHECKPOINT_SOURCE_BINDING_INVALID"
    SOURCE_SNAPSHOT = "CHECKPOINT_SOURCE_SNAPSHOT_INVALID"
    BASE = "CHECKPOINT_BASE_INVALID"
    BASE_WORKFLOW = "CHECKPOINT_BASE_CHANGED_UNSUPPORTED_WORKFLOW"
    COMPILE_INPUT = "CHECKPOINT_COMPILE_INPUT_INVALID"
    REBASE = "CHECKPOINT_REBASE_INVALID"
    RECEIPT = "CHECKPOINT_RECEIPT_INVALID"


class CheckpointValidationError(ValueError):
    def __init__(self, reason: CheckpointFailureReason):
        self.reason = reason
        super().__init__(reason.value)


async def validate_checkpoint(
    context: ProductCompositionContext,
    scope: ProductScope,
    run: ProductRunSnapshot,
    stage: StageSnapshot,
) -> StageOutput:
    """Return immutable drafts after full dependency validation; perform no writes."""
    service = context.bindings[scope.space_id]
    if service.scope != scope:
        raise NonRetryableJobError("PRODUCT_PIPELINE_SCOPE_MISMATCH")
    store, artifacts = context.store, context.artifacts
    policy = resolver.BatchResolutionPolicyV1.model_validate_json(context.resolution_policy_json)
    reason = CheckpointFailureReason.PLAN
    try:
        plan = await asyncio.to_thread(store.checkpoint_plan, scope=scope, run_id=run.run_id)
        if plan is None:
            raise ValueError("checkpoint plan missing")
        reason = CheckpointFailureReason.LOCAL_PROOF
        receipt = await asyncio.to_thread(
            artifacts.verify_checkpoint, scope=scope, run_id=run.run_id
        )
        from insurance_harness.product_ingestion.upload_resolution import lookup_material

        reason = CheckpointFailureReason.SOURCE_BINDING
        manifest = await asyncio.to_thread(
            store.get_upload_manifest, scope=scope, run_id=run.run_id
        )
        for material in plan.materials:
            reason = CheckpointFailureReason.SOURCE_BINDING
            item = await lookup_material(
                service.platform,
                scope,
                plan.upload_run_id,
                material.upload_ordinal,
                manifest,
                knowledge_id=material.knowledge_id,
            )
            if (
                item is None
                or item["knowledge_id"] != material.knowledge_id
                or item["parse_status"] != "completed"
            ):
                raise ValueError("current source identity is unavailable")
            if "source" in {row.stage_key for row in plan.reused_stages}:
                reason = CheckpointFailureReason.SOURCE_SNAPSHOT
                saved = await asyncio.to_thread(
                    artifacts.read_checkpoint_artifact,
                    scope=scope,
                    run_id=run.run_id,
                    artifact_kind="source_snapshot",
                    artifact_key=material.knowledge_id,
                )
                decoded = await asyncio.to_thread(
                    decode_source_snapshot,
                    saved.payload,
                    scope=scope,
                    knowledge_id=material.knowledge_id,
                    parse_attempt=item["parse_attempt"],
                    public_keys=service.configuration.source_public_keys,
                )
                if material.source is not None and (
                    decoded.snapshot["receipt"]["revision_source_id"],
                    decoded.snapshot["receipt"]["file_sha256"],
                ) != (
                    material.source.source_revision_id,
                    material.source.file_sha256,
                ):
                    raise ValueError("source revision changed")
                del saved, decoded
        reason = CheckpointFailureReason.BASE
        if any(ref.artifact_kind == "base_snapshot" for ref in plan.artifacts):
            saved = await asyncio.to_thread(
                artifacts.read_checkpoint_artifact,
                scope=scope,
                run_id=run.run_id,
                artifact_kind="base_snapshot",
            )
            base = await asyncio.to_thread(
                verify_signed_snapshot,
                saved.payload,
                kind="base",
                scope=scope,
                public_keys=service.configuration.source_public_keys,
            )
            if plan.prior_rebase_artifacts:
                prior = await asyncio.to_thread(
                    artifacts.read_prior_rebase_artifact,
                    scope=scope, run_id=run.run_id,
                    artifact_kind="rebased_base_snapshot",
                )
                base = await asyncio.to_thread(
                    verify_signed_snapshot, prior.payload, kind="base", scope=scope,
                    public_keys=service.configuration.source_public_keys,
                )
            current = await service.platform.current(scope)
            base_changed = (base["release_id"], base["activation_epoch"]) != (
                current["release_id"],
                current["activation_epoch"],
            )
            if base_changed and not plan.supports_rebase:
                raise CheckpointValidationError(CheckpointFailureReason.BASE_WORKFLOW)
        else:
            base_changed = False
        reason = CheckpointFailureReason.COMPILE_INPUT
        if any(ref.artifact_kind == "compile_request" for ref in plan.artifacts):
            saved = await asyncio.to_thread(
                artifacts.read_checkpoint_artifact,
                scope=scope,
                run_id=run.run_id,
                artifact_kind="compile_request",
            )
            request = await asyncio.to_thread(
                compiler.BatchConceptCompileRequest830G3V1.model_validate_json,
                saved.payload,
            )
            if request.catalog != context.catalog or request.resolution_inputs.policy != policy:
                raise ValueError("Catalog or Schema changed")
        reason = CheckpointFailureReason.REBASE
        drafts: list[ArtifactDraft] = []
        if base_changed or plan.prior_rebase_artifacts:
            from insurance_harness.product_ingestion.checkpoint_rebase import (
                rebase_checkpoint_inputs,
            )

            if base_changed:
                await asyncio.to_thread(
                    artifacts.verify_discarded_stage_calls,
                    scope=scope, run_id=run.run_id,
                    stage_keys={"discovery", "compilation"},
                )
            disposition = await asyncio.to_thread(
                artifacts.read_checkpoint_discovery_disposition,
                scope=scope, run_id=run.run_id,
            )

            current_raw = await service.platform.base_snapshot(
                scope, current["release_id"], current["activation_epoch"]
            )
            current_base = await asyncio.to_thread(
                verify_signed_snapshot, current_raw, kind="base", scope=scope,
                public_keys=service.configuration.source_public_keys,
            )
            if (current_base["release_id"], current_base["activation_epoch"]) != (
                current["release_id"], current["activation_epoch"]
            ):
                raise ValueError("published base changed during recovery")
            inputs = {}
            for kind in ("identity", "compile_request", "field_validation"):
                if plan.prior_rebase_artifacts and kind in {"identity", "compile_request"}:
                    inputs[kind] = await asyncio.to_thread(
                        artifacts.read_prior_rebase_artifact,
                        scope=scope, run_id=run.run_id,
                        artifact_kind="rebased_" + kind,
                    )
                else:
                    inputs[kind] = await asyncio.to_thread(
                        artifacts.read_checkpoint_artifact,
                        scope=scope, run_id=run.run_id, artifact_kind=kind,
                    )
            attempts = await asyncio.to_thread(
                artifacts.read_checkpoint_field_attempts,
                scope=scope, run_id=run.run_id,
            )
            rebased = await asyncio.to_thread(
                rebase_checkpoint_inputs,
                scope=scope, base_body=current_base, base_raw=current_raw,
                catalog_json=context.catalog_json,
                profile_confirmation_json=context.profile_confirmation_json,
                policy=policy, identity_payload=inputs["identity"].payload,
                original_request=inputs["compile_request"].payload,
                original_attempts=attempts,
                original_field_validation=inputs["field_validation"].payload,
                run_id=run.run_id,
            )
            drafts.extend(
                artifact(
                    kind, "product", payload, stage.dependency_sha256,
                    origin=(
                        ArtifactOrigin.PLATFORM_SOURCE
                        if kind == "rebased_base_snapshot" else ArtifactOrigin.RULE
                    ),
                )
                for kind, payload in rebased.items()
            )
            if disposition is not None:
                prior_disposition = json.loads(disposition.payload)
                summary = prior_disposition.get(
                    "original_summary", prior_disposition
                )
                original_artifact_id = prior_disposition.get(
                    "original_artifact_id", disposition.artifact_id
                )
                original_payload_sha256 = prior_disposition.get(
                    "original_payload_sha256", disposition.payload_sha256
                )
                drafts.append(artifact(
                    "rebased_discovery_disposition", "product",
                    json_bytes({
                        "contract": "product-rebased-discovery-disposition.830.v1",
                        "state": summary["state"],
                        "reason_codes": summary.get("reason_codes", ()),
                        "original_artifact_id": original_artifact_id,
                        "original_payload_sha256": original_payload_sha256,
                        "original_output_hash": summary.get("final_composed_output_hash"),
                        "original_summary": summary,
                        "rebased_request_sha256": hashlib.sha256(
                            rebased["rebased_compile_request"]
                        ).hexdigest(),
                    }),
                    stage.dependency_sha256,
                ))
                effective_keys = tuple(
                    row.stage_key for row in plan.reused_stages
                    if row.stage_key != "compilation"
                )
                receipt = await asyncio.to_thread(
                    artifacts.verify_checkpoint, scope=scope, run_id=run.run_id,
                    effective_stage_keys=effective_keys,
                )
            elif base_changed and plan.field_only_rebase:
                receipt = await asyncio.to_thread(
                    artifacts.verify_checkpoint, scope=scope, run_id=run.run_id,
                    effective_stage_keys=tuple(
                        row.stage_key for row in plan.reused_stages
                        if row.stage_key in {
                            "uploads", "source", "routing", "identity",
                            "field_plan", "extract", "synthesis",
                        }
                    ),
                )
            elif base_changed and "discovery" in {
                row.stage_key for row in plan.reused_stages
            }:
                receipt = await asyncio.to_thread(
                    artifacts.verify_checkpoint, scope=scope, run_id=run.run_id,
                    effective_stage_keys=tuple(
                        row.stage_key for row in plan.reused_stages
                        if row.stage_key in {
                            "uploads", "source", "routing", "identity",
                            "field_plan", "extract", "synthesis",
                        }
                    ),
                )
            receipt = receipt.model_copy(update={
                "rebased_base_sha256": hashlib.sha256(current_raw).hexdigest(),
                "rebased_discovery_disposition_sha256": next(
                    (
                        draft.payload_sha256 for draft in drafts
                        if draft.artifact_kind == "rebased_discovery_disposition"
                    ),
                    None,
                ),
            })
        reason = CheckpointFailureReason.RECEIPT
        drafts.append(
            artifact(
                RECEIPT_KIND,
                "product",
                receipt.encoded(),
                stage.dependency_sha256,
                contract_version=(
                    plan.contract_version
                    if plan.contract_version in {"3", "4", "5", "6", "7"}
                    else "1"
                ),
            )
        )
        return StageOutput(tuple(drafts))
    except CheckpointValidationError:
        raise
    except ValueError:
        raise CheckpointValidationError(reason) from None
