"""Durable optional discovery beside the required-field pipeline.

Model transport, generation, review and audit are separate immutable records.
Only a wholly accepted group changes the compiled delta. Field-only retries do
not redispatch discovery; publication still uses the platform's normal gates.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    ExecutionRecord,
    ReviewResult,
)
from insurance_harness.product_ingestion.artifact_models import ArtifactOrigin
from insurance_harness.product_ingestion.checkpoints import CURRENT_ARTIFACT_CONTRACTS
from insurance_harness.product_ingestion.compilation import _derived_run_id
from insurance_harness.product_ingestion.discovery import (
    DISCOVERY_PROMPT,
    DISCOVERY_REVIEW_PROMPT,
    project_discovery_response,
    project_discovery_review,
    render_discovery_context,
    render_discovery_review_context,
)
from insurance_harness.product_ingestion.extraction import _json
from insurance_harness.product_ingestion.model_execution import (
    ConfiguredFieldTransport,
    ModelPolicyDenied,
)
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.stages import StageOutput, artifact, json_bytes
from insurance_harness.product_ingestion.store import needs_confirmation_error


def _template(settings, role, purpose, prompt):
    matches = [row for row in settings.templates if row.role == role and row.purpose == purpose]
    if len(matches) != 1 or matches[0].prompt_sha256 != hashlib.sha256(prompt).hexdigest():
        raise ModelPolicyDenied("discovery template is missing or changed")
    return matches[0]


def _summary():
    return {
        "state": "NOT_EXECUTED",
        "reused": False,
        "reused_from_run_id": None,
        "reason_codes": [],
        "call_ids": [],
        "accepted_member_count": 0,
        "counts": {
            "proposed_new": 0,
            "duplicate": 0,
            "update_proposal": 0,
            "rejected": 0,
            "published": 0,
        },
        "coverage": None,
    }


def _unchanged_sources(request, base):
    # Compare exact identities, Schema versions, text and evidence geometry.
    prior_bindings = {
        row["entity_id"]: row for row in base["published_projection"].get("entity_bindings", ())
    }
    if any(
        prior_bindings.get(row.entity_id) != row.model_dump(mode="json")
        for row in request.entity_bindings
    ):
        return False
    previous = {
        (row["revision_id"], row["block_id"]): row
        for row in base["published_projection"].get("sources", ())
    }
    blocks = [block for entry in request.resolution_inputs.corpus.entries for block in entry.blocks]
    return bool(blocks) and all(
        previous.get((block.revision_id, block.block_id)) == block.model_dump(mode="json")
        for block in blocks
    )


async def run_discovery_stage(
    *,
    service,
    artifacts,
    scope,
    run,
    stage,
    job,
    request,
    field_delta,
    entity_id,
    base,
    processing_recovery=False,
):
    drafts = []
    summary = _summary()
    delta = field_delta

    def keep(kind, value, *, call_id=None):
        drafts.append(
            artifact(
                kind,
                "product",
                json_bytes(value),
                stage.dependency_sha256,
                origin=ArtifactOrigin.MODEL if call_id else ArtifactOrigin.RULE,
                call_id=call_id,
                contract_version=CURRENT_ARTIFACT_CONTRACTS.get(kind, (None, "1"))[1],
            )
        )

    async def call(operation, content, prompt, template):
        raw_context = json_bytes(content)
        result = await service.model_executor.execute_stage_call(
            store=artifacts,
            scope=scope,
            run_id=run.run_id,
            job=job,
            stage_key="synthesis",
            operation_key=operation,
            dependency_sha256=stage.dependency_sha256,
            input_sha256=hashlib.sha256(raw_context).hexdigest(),
            content=raw_context,
            prompt=prompt,
            template_id=template.template_id,
        )
        summary["call_ids"].append(result.call_id)
        if (
            result.state != "recorded"
            or result.raw is None
            or result.diagnostic
            or result.policy_receipt is None
        ):
            raise ValueError("discovery model call failed: " + (result.diagnostic or result.state))
        semantic = json_bytes(_json(ConfiguredFieldTransport.decode_response(result.raw)))
        return semantic, result.call_id

    phase = "GENERATION"
    try:
        if run.retry_of_run_id:
            read_prior = (
                artifacts.list_effective_artifacts
                if processing_recovery
                else artifacts.list_artifacts
            )
            prior = read_prior(
                scope=scope, run_id=run.retry_of_run_id, artifact_kind="discovery_summary"
            )
            if prior:
                summary = json.loads(prior[0].payload)
                if summary["state"] == "ACCEPTED":
                    origin = summary.get("discovery_origin_run_id") or run.retry_of_run_id
                    prior_delta = json.loads(
                        artifacts.get_artifact(
                            scope=scope,
                            run_id=origin,
                            artifact_kind="compile_delta",
                            artifact_key="product",
                        ).payload
                    )["output"]
                    expected = [
                        (kind, json_bytes(row))
                        for kind in ("pages", "definitions")
                        for row in prior_delta[kind]
                    ]
                    published = {
                        (kind, json_bytes(row))
                        for kind in ("pages", "definitions")
                        for row in base["published_projection"].get(kind, ())
                    }
                    if not expected or not set(expected) <= published:
                        if not processing_recovery:
                            raise needs_confirmation_error("DISCOVERY_RESULT_NOT_IN_PUBLISHED_BASE")
                        # The recorded group remains auditable at its origin.
                        # Changed field dependencies cannot inherit its review.
                        summary["state"] = "PENDING"
                        summary["reason_codes"] = ["DISCOVERY_REVALIDATION_REQUIRED"]
                    summary["discovery_origin_run_id"] = origin
                summary.update(reused=True, reused_from_run_id=run.retry_of_run_id, call_ids=[])
                # These members belong to the inherited published base, not new output.
                summary["accepted_member_count"] = 0
                summary["counts"]["published"] = 0
            else:
                summary["reason_codes"] = ["PRIOR_DISCOVERY_NOT_EXECUTED"]
        elif _unchanged_sources(request, base):
            summary["reason_codes"] = ["NO_CHANGED_SOURCE"]
        else:
            settings = service.configuration.model
            generation_template = _template(
                settings, "extract", "g3-open-discovery", DISCOVERY_PROMPT
            )
            review_template = _template(
                settings, "verify", "g3-open-discovery-review", DISCOVERY_REVIEW_PROMPT
            )
            generation = await asyncio.to_thread(
                render_discovery_context,
                request=request,
                field_delta=field_delta,
                entity_id=entity_id,
                max_context_bytes=generation_template.max_context_bytes,
            )
            summary["coverage"] = generation["coverage"]
            keep("discovery_context", generation)
            raw, generation_call = await call(
                "current-product-discovery", generation, DISCOVERY_PROMPT, generation_template
            )
            keep("discovery_response", json.loads(raw), call_id=generation_call)
            projection = await asyncio.to_thread(
                project_discovery_response,
                raw=raw,
                request=request,
                field_delta=field_delta,
                context=generation,
                run_id=_derived_run_id(run.run_id, "discovery-compile"),
            )
            for disposition in projection.proposal.dispositions:
                summary["counts"][
                    disposition.disposition.lower()
                    if disposition.disposition != "REJECT"
                    else "rejected"
                ] += 1
            keep("discovery_proposal", projection.proposal, call_id=generation_call)
            phase = "REVIEW"
            review_context = await asyncio.to_thread(
                render_discovery_review_context,
                request=request,
                field_delta=field_delta,
                projection=projection,
                context=generation,
                max_context_bytes=review_template.max_context_bytes,
            )
            keep("discovery_review_context", review_context)
            raw_review, review_call = await call(
                "current-product-discovery-review",
                review_context,
                DISCOVERY_REVIEW_PROMPT,
                review_template,
            )
            keep("discovery_review_response", json.loads(raw_review), call_id=review_call)
            decision = await asyncio.to_thread(
                project_discovery_review,
                raw=raw_review,
                request=request,
                projection=projection,
                context=review_context,
            )
            summary["state"] = decision.state
            # Free-form model reasons stay in raw/audit; API gets stable machine codes.
            summary["reason_codes"] = ["DISCOVERY_" + decision.state]
            if "EXISTING_KNOWLEDGE_UPDATE_ADAPTER_REQUIRED" in decision.reasons:
                summary["reason_codes"].append("EXISTING_KNOWLEDGE_UPDATE_ADAPTER_REQUIRED")
            keep(
                "discovery_disposition",
                {
                    "state": decision.state,
                    "reasons": decision.reasons,
                    "disposition_checks": decision.disposition_checks,
                    "raw_sha256": decision.raw_sha256,
                    "context_sha256": decision.context_sha256,
                },
                call_id=review_call,
            )
            if decision.state == "ACCEPTED":
                # The canonical inner ReviewOutput is a checked semantic projection;
                # the actual untouched envelope remains attached to the recorded call.
                raw_output = compiler._canonical_json(decision.review)
                review = ReviewResult(
                    output=decision.review,
                    execution=ExecutionRecord(
                        run_id=_derived_run_id(run.run_id, "discovery-review"),
                        implementation="platform-independent-discovery-review.830.g3.v1",
                        context_hash=compiler._batch_sha256(
                            "batch-concept-review-context.830.g3.v1",
                            compiler.review_context_g3(request, projection.composed_output),
                        ),
                        raw_output=raw_output,
                        raw_output_hash=hashlib.sha256(raw_output.encode()).hexdigest(),
                    ),
                )
                keep("discovery_review", review, call_id=review_call)
                delta = projection.merged_delta
                summary["accepted_member_count"] = len(projection.new_output.pages) + len(
                    projection.new_output.definitions
                )
                summary["discovery_origin_run_id"] = run.run_id
    except (ValueError, ModelPolicyDenied) as exc:
        summary["state"] = "FAILED"
        summary["reason_codes"] = ["DISCOVERY_" + phase + "_FAILED"]
        summary["failure_detail"] = str(exc)
        # No second model call to repair ordinary content and no partial group admission.
        delta = field_delta

    keep("discovery_summary", summary)
    keep("compile_delta", delta)
    state = (
        ProductRunState.PARTIAL_SUCCESS
        if summary["state"] in {"FAILED", "PENDING", "REJECTED", "NOT_EXECUTED"}
        else ProductRunState.SUCCEEDED
    )
    return StageOutput(tuple(drafts), state=state)
