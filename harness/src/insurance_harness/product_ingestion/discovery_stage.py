"""Durable optional discovery beside the required-field pipeline.

Model transport, generation, review and audit are separate immutable records.
Only a wholly accepted group changes the compiled delta. Field-only retries do
not redispatch discovery; publication still uses the platform's normal gates.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from insurance_harness.jobs.models import JobSnapshot
from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
    compile_request_hash_g3,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileResult
from insurance_harness.product_ingestion.artifact_models import ArtifactDraft, StageCallSnapshot
from insurance_harness.product_ingestion.artifacts import ProductArtifactStore
from insurance_harness.product_ingestion.discovery import DiscoveryReview
from insurance_harness.product_ingestion.model_settings import (
    ModelTemplatePolicy,
    ProductModelSettings,
)
from insurance_harness.product_ingestion.models import (
    ProductRunSnapshot,
    ProductScope,
    StageSnapshot,
)

if TYPE_CHECKING:
    from insurance_harness.product_ingestion.composition import ProductScopeServices

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    AuditDisposition,
    CompileOutput,
    ExecutionRecord,
    ReviewOutput,
    ReviewResult,
    free_page_id,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    ConceptDefinition,
    FreeWikiPage,
)
from insurance_harness.product_ingestion.artifact_models import ArtifactOrigin
from insurance_harness.product_ingestion.checkpoints import CURRENT_ARTIFACT_CONTRACTS
from insurance_harness.product_ingestion.compilation import _derived_run_id
from insurance_harness.product_ingestion.discovery import (
    DISCOVERY_PROMPT,
    DISCOVERY_REVIEW_PROMPT,
    INDEPENDENT_DISCOVERY_PROMPT,
    INDEPENDENT_DISCOVERY_REVIEW_PROMPT,
    build_discovery_exclusion_index,
    independent_discovery_window_audits,
    project_discovery_response,
    project_discovery_review,
    project_independent_discovery_response,
    render_discovery_context,
    render_discovery_review_context,
    render_independent_discovery_contexts,
    render_independent_discovery_review_context,
)
from insurance_harness.product_ingestion.extraction import _json
from insurance_harness.product_ingestion.model_execution import (
    ConfiguredFieldTransport,
    ModelPolicyDenied,
    matches_recorded_stage_request,
)
from insurance_harness.product_ingestion.models import ProductRunState
from insurance_harness.product_ingestion.stages import StageOutput, artifact, json_bytes
from insurance_harness.product_ingestion.store import needs_confirmation_error


@dataclass(frozen=True, slots=True)
class IndependentDiscoveryFinalOutcome:
    reviewed_output: CompileOutput
    decision: str
    review_output: ReviewOutput | None
    review_context_sha256: str | None
    review_raw_sha256: str | None
    drafts: tuple[ArtifactDraft, ...]
    summary: dict[str, Any]
    replayed_call: StageCallSnapshot | None = None


def _verified_parent_discovery_call(
    row: StageCallSnapshot,
    *,
    run_id: str,
    stage_key: str,
    operation: str,
    input_sha256: str,
    prompt_sha256: str,
) -> StageCallSnapshot | None:
    """Reopen an exact recorded parent call; a dispatch with unknown outcome is never resent."""
    if (
        row.run_id != run_id
        or row.stage_key != stage_key
        or row.operation_key != operation
        or row.input_sha256 != input_sha256
        or row.prompt_policy_sha256 != prompt_sha256
    ):
        raise ValueError("DISCOVERY_REPLAY_BINDING_MISMATCH")
    if row.dispatched_at is None:
        return None
    state = row.state.value if hasattr(row.state, "value") else row.state
    if state != "recorded" or row.raw is None:
        raise ValueError("DISCOVERY_REPLAY_OUTCOME_UNKNOWN")
    if row.raw_sha256 != hashlib.sha256(row.raw).hexdigest():
        raise ValueError("DISCOVERY_REPLAY_RAW_MISMATCH")
    diagnostic = getattr(row, "diagnostic", None)
    if diagnostic == "provider_http_status":
        # The recorded HTTP response proves this attempt finished, but is not
        # a successful model result to replay into a child recovery.
        return None
    if diagnostic:
        raise ValueError("DISCOVERY_REPLAY_OUTCOME_UNKNOWN")
    return row


def _validated_independent_review(
    decoded: object, *, context: dict[str, Any], final_composed_output_hash: str
) -> tuple[DiscoveryReview, ReviewOutput, str]:
    """Validate the same semantic review before replay and after a new call."""
    from insurance_harness.product_ingestion.discovery import DiscoveryReview

    if not isinstance(decoded, dict):
        raise ValueError("discovery review response must be an object")
    checked = DiscoveryReview.model_validate(decoded)
    review_output = checked.review
    if (review_output.request_hash, review_output.output_hash) != (
        context["request_hash"],
        final_composed_output_hash,
    ):
        raise ValueError("discovery review binding mismatch")
    if set(review_output.page_scores) != set(context["review_member_ids"]):
        raise ValueError("discovery review score coverage mismatch")
    expected_ids = {row["candidate_id"] for row in context["dispositions"]}
    ids = [row.candidate_id for row in checked.disposition_checks]
    if len(ids) != len(set(ids)) or set(ids) != expected_ids:
        raise ValueError("discovery review disposition coverage mismatch")
    checks = {row.decision for row in checked.disposition_checks}
    scores = [score.total for score in review_output.page_scores.values()]
    if (
        review_output.decision == "REJECT"
        or "REJECT" in checks
        or any(score < 60 for score in scores)
    ):
        decision = "REJECTED"
    elif (
        review_output.decision == "NEEDS_HUMAN"
        or "NEEDS_HUMAN" in checks
        or any(score < 80 for score in scores)
    ):
        decision = "PENDING"
    else:
        decision = "ACCEPTED"
    return checked, review_output, decision


async def run_independent_discovery_final_review(
    *,
    service: ProductScopeServices,
    artifacts: ProductArtifactStore,
    scope: ProductScope,
    run: ProductRunSnapshot,
    stage: StageSnapshot,
    job: JobSnapshot,
    request: BatchConceptCompileRequest830G3V1,
    discovery_candidates: dict[str, Any],
    final_composed_output: CompileOutput,
    final_composed_output_hash: str,
    exclusion_index: dict[str, Any] | None = None,
    entity_id: str | None = None,
    processing_recovery: bool = False,
) -> IndependentDiscoveryFinalOutcome:
    """Review the whole free group against the real final hash; admit all or none."""
    del processing_recovery
    request_hash = compile_request_hash_g3(request.base_request)
    empty = CompileOutput(request_hash=request_hash, fields=())
    candidate_output = CompileOutput.model_validate(discovery_candidates["output"])
    if candidate_output.fields or candidate_output.request_hash != request_hash:
        raise ValueError("independent discovery delta is invalid")
    if exclusion_index is None:
        exclusion_index = (
            build_discovery_exclusion_index(request, entity_id)
            if entity_id is not None
            else {
                row.entity_id: build_discovery_exclusion_index(request, row.entity_id)
                for row in request.entity_bindings
            }
        )
    drafts = []
    summary = _summary()
    summary["final_composed_output_hash"] = final_composed_output_hash
    summary["candidate_member_count"] = len(candidate_output.definitions) + len(
        candidate_output.pages
    )
    review_output = None
    review_context_sha256 = None
    review_raw_sha256 = None
    replayed_call = None
    reviewed = empty
    decision = "EMPTY" if not summary["candidate_member_count"] else "FAILED"

    def keep(kind: str, value: object, *, call_id: str | None = None) -> None:
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

    if summary["candidate_member_count"]:
        try:
            settings = service.configuration.model
            template = _template(
                settings,
                "verify",
                "g3-independent-discovery-review",
                INDEPENDENT_DISCOVERY_REVIEW_PROMPT,
            )
            context = await asyncio.to_thread(
                render_independent_discovery_review_context,
                request=request,
                entity_id=entity_id,
                exclusion_index=exclusion_index,
                discovery_candidates=discovery_candidates,
                final_composed_output=final_composed_output,
                final_composed_output_hash=final_composed_output_hash,
                max_context_bytes=template.max_context_bytes,
            )
            content = json_bytes(context)
            review_context_sha256 = hashlib.sha256(content).hexdigest()
            keep("discovery_review_context", context)
            operation = "independent-discovery-final-review-" + final_composed_output_hash
            prior_call = None
            if run.retry_of_run_id and hasattr(artifacts, "list_stage_calls"):
                for recorded_call in artifacts.list_stage_calls(
                    scope=scope, run_id=run.retry_of_run_id
                ):
                    if (
                        recorded_call.stage_key == "compilation"
                        and recorded_call.operation_key == operation
                        and recorded_call.input_sha256 == review_context_sha256
                    ):
                        prior_call = recorded_call
                        break
            if prior_call is not None:
                assert run.retry_of_run_id is not None
                replayed_call = _verified_parent_discovery_call(
                    prior_call,
                    run_id=run.retry_of_run_id,
                    stage_key="compilation",
                    operation=operation,
                    input_sha256=review_context_sha256,
                    prompt_sha256=template.prompt_sha256,
                )
            if replayed_call is not None and not matches_recorded_stage_request(
                replayed_call,
                settings,
                scope=scope,
                content=content,
                prompt=INDEPENDENT_DISCOVERY_REVIEW_PROMPT,
                template_id=template.template_id,
            ):
                replayed_call = None
            parent_decoded = None
            parent_review = None
            if replayed_call is not None:
                assert replayed_call.raw is not None
                try:
                    parent_decoded = _json(
                        ConfiguredFieldTransport.decode_response(replayed_call.raw)
                    )
                    parent_review = _validated_independent_review(
                        parent_decoded,
                        context=context,
                        final_composed_output_hash=final_composed_output_hash,
                    )
                except (TypeError, ValueError):
                    replayed_call = None
            if replayed_call is not None:
                assert replayed_call.raw is not None
                assert parent_review is not None
                raw_provider = replayed_call.raw
                call_id = replayed_call.call_id
                summary["reused"] = True
                summary["reused_from_run_id"] = run.retry_of_run_id
            else:
                result = await service.model_executor.execute_stage_call(
                    store=artifacts,
                    scope=scope,
                    run_id=run.run_id,
                    job=job,
                    stage_key="compilation",
                    operation_key=operation,
                    dependency_sha256=stage.dependency_sha256,
                    input_sha256=review_context_sha256,
                    content=content,
                    prompt=INDEPENDENT_DISCOVERY_REVIEW_PROMPT,
                    template_id=template.template_id,
                )
                call_id = result.call_id
                if (
                    result.state != "recorded"
                    or result.raw is None
                    or result.diagnostic
                    or result.policy_receipt is None
                ):
                    raise ValueError(
                        "discovery review model call failed: " + (result.diagnostic or result.state)
                    )
                raw_provider = result.raw
            summary["call_ids"].append(call_id)
            decoded = (
                parent_decoded
                if replayed_call is not None
                else _json(ConfiguredFieldTransport.decode_response(raw_provider))
            )
            raw = json_bytes(decoded)
            review_raw_sha256 = hashlib.sha256(raw).hexdigest()
            keep(
                "discovery_review_response",
                json.loads(raw),
                call_id=None if replayed_call is not None else call_id,
            )
            if replayed_call is not None:
                assert parent_review is not None
                checked, review_output, decision = parent_review
            else:
                checked, review_output, decision = _validated_independent_review(
                    decoded, context=context, final_composed_output_hash=final_composed_output_hash
                )
            if decision == "ACCEPTED":
                reviewed = candidate_output
            keep(
                "discovery_review_proof",
                {
                    "contract": "product-discovery-review-proof.830.v1",
                    "decision": decision,
                    "final_composed_output_hash": final_composed_output_hash,
                    "actual_review_context_sha256": review_context_sha256,
                    "actual_review_raw_sha256": review_raw_sha256,
                    "model_call_id": call_id,
                    "replayed_from_run_id": (
                        run.retry_of_run_id if replayed_call is not None else None
                    ),
                    "source_call_id": call_id if replayed_call is not None else None,
                    "source_raw_sha256": (
                        replayed_call.raw_sha256 if replayed_call is not None else None
                    ),
                    "review": review_output,
                    "disposition_checks": checked.disposition_checks,
                },
                call_id=None if replayed_call is not None else call_id,
            )
        except (TypeError, ValueError, ModelPolicyDenied) as exc:
            summary["failure_detail"] = str(exc)
            decision = "FAILED"
    summary["state"] = decision
    summary["reason_codes"] = ["DISCOVERY_" + decision]
    summary["accepted_member_count"] = len(reviewed.definitions) + len(reviewed.pages)
    keep(
        "reviewed_discovery_delta",
        {
            "contract": "product-reviewed-discovery-delta.830.v1",
            "output": reviewed,
            "reviewed": decision == "ACCEPTED",
        },
    )
    keep("discovery_final_summary", summary)
    return IndependentDiscoveryFinalOutcome(
        reviewed,
        decision,
        review_output,
        review_context_sha256,
        review_raw_sha256,
        tuple(drafts),
        summary,
        replayed_call,
    )


async def _run_entity_discovery_generation_stage(
    *,
    service: ProductScopeServices,
    artifacts: ProductArtifactStore,
    scope: ProductScope,
    run: ProductRunSnapshot,
    stage: StageSnapshot,
    job: JobSnapshot,
    request: BatchConceptCompileRequest830G3V1,
    entity_id: str,
    exclusion_index: dict[str, Any],
    processing_recovery: bool = False,
) -> StageOutput:
    """Separate v3 source task; field extraction output is never an input."""
    drafts = []
    summary = _summary()
    summary["state"] = "GENERATING"
    summary["exclusion_index_sha256"] = hashlib.sha256(json_bytes(exclusion_index)).hexdigest()
    empty_output: dict[str, Any] = {
        "request_hash": compile_request_hash_g3(request.base_request),
        "definitions": [],
        "fields": [],
        "pages": [],
        "audit": [],
        "transformation": "EXTRACT",
    }
    candidate_output = empty_output
    candidate_dispositions = []
    candidate_sources = []
    receipts = []

    def keep(kind: str, value: object, *, key: str = "product", call_id: str | None = None) -> None:
        drafts.append(
            artifact(
                kind,
                key,
                json_bytes(value),
                stage.dependency_sha256,
                origin=ArtifactOrigin.MODEL if call_id else ArtifactOrigin.RULE,
                call_id=call_id,
                contract_version=CURRENT_ARTIFACT_CONTRACTS.get(kind, (None, "1"))[1],
            )
        )

    binding = next(row for row in request.entity_bindings if row.entity_id == entity_id)
    current_materials = {entry.material_id for entry in request.resolution_inputs.corpus.entries}
    if not current_materials.intersection(binding.source_material_ids):
        summary.update(
            state="EMPTY",
            reason_codes=["NO_CURRENT_BOUND_MATERIAL"],
            coverage={
                "total_chars": 0,
                "offered_chars": 0,
                "validated_chars": 0,
                "omitted_chars": 0,
                "processed_chars": 0,
                "window_count": 0,
                "sent_window_count": 0,
                "processed_window_count": 0,
                "replayed_chars": 0,
                "complete": True,
            },
        )
        keep(
            "discovery_candidates",
            {
                "contract": "product-discovery-candidates.830.v1",
                "output": empty_output,
                "dispositions": [],
                "sources": [],
                "exclusion_index_sha256": summary["exclusion_index_sha256"],
                "window_receipts": [],
            },
        )
        keep(
            "discovery_delta",
            {
                "contract": "product-discovery-delta.830.v1",
                "output": empty_output,
                "reviewed": False,
            },
        )
        keep("discovery_summary", summary)
        return StageOutput(tuple(drafts), state=ProductRunState.SUCCEEDED)

    try:
        settings = service.configuration.model
        template = _template(
            settings, "extract", "g3-independent-discovery", INDEPENDENT_DISCOVERY_PROMPT
        )
        contexts = await asyncio.to_thread(
            render_independent_discovery_contexts,
            request=request,
            entity_id=entity_id,
            exclusion_index=exclusion_index,
            max_context_bytes=template.max_context_bytes,
        )
        audit_windows = await asyncio.to_thread(
            independent_discovery_window_audits, request, entity_id, contexts
        )
        total_chars = audit_windows[0]["coverage"]["total_chars"] if audit_windows else 0
        summary["coverage"] = {
            "total_chars": total_chars,
            "offered_chars": 0,
            "validated_chars": 0,
            "omitted_chars": total_chars,
            "processed_chars": 0,
            "window_count": len(contexts),
            "sent_window_count": 0,
            "processed_window_count": 0,
            "replayed_chars": 0,
            "complete": False,
        }
        pages: dict[str, FreeWikiPage] = {}
        definitions: dict[str, ConceptDefinition] = {}
        audit_rows: dict[str, AuditDisposition] = {}
        for context, window_audit in zip(contexts, audit_windows, strict=True):
            window_id = context["window"]["window_id"]
            operation = (
                "independent-discovery-window-"
                + hashlib.sha256(json_bytes([entity_id, window_id])).hexdigest()
            )
            raw_context = json_bytes(context)
            input_sha = hashlib.sha256(raw_context).hexdigest()
            artifact_key = entity_id + ":" + window_id
            keep("discovery_context", context, key=artifact_key)
            keep("discovery_window_audit", window_audit, key=artifact_key)
            prior_call = None
            if run.retry_of_run_id and hasattr(artifacts, "list_stage_calls"):
                for recorded_call in artifacts.list_stage_calls(
                    scope=scope, run_id=run.retry_of_run_id
                ):
                    if (
                        recorded_call.stage_key == "discovery"
                        and recorded_call.operation_key == operation
                        and recorded_call.input_sha256 == input_sha
                    ):
                        prior_call = recorded_call
                        break
            replayed_call = None
            if prior_call is not None:
                assert run.retry_of_run_id is not None
                replayed_call = _verified_parent_discovery_call(
                    prior_call,
                    run_id=run.retry_of_run_id,
                    stage_key="discovery",
                    operation=operation,
                    input_sha256=input_sha,
                    prompt_sha256=template.prompt_sha256,
                )
            if replayed_call is not None and not matches_recorded_stage_request(
                replayed_call,
                settings,
                scope=scope,
                content=raw_context,
                prompt=INDEPENDENT_DISCOVERY_PROMPT,
                template_id=template.template_id,
            ):
                replayed_call = None
            parent_decoded = None
            parent_candidate = None
            if replayed_call is not None:
                assert replayed_call.raw is not None
                try:
                    parent_decoded = _json(
                        ConfiguredFieldTransport.decode_response(replayed_call.raw)
                    )
                    if not isinstance(parent_decoded, dict):
                        raise ValueError("discovery generation response must be an object")
                    parent_candidate = await asyncio.to_thread(
                        project_independent_discovery_response,
                        raw=json_bytes(parent_decoded),
                        request=request,
                        entity_id=entity_id,
                        exclusion_index=exclusion_index,
                        context=context,
                        audit=window_audit,
                    )
                except (TypeError, ValueError):
                    replayed_call = None
            if replayed_call is not None:
                assert replayed_call.raw is not None
                raw_response = replayed_call.raw
                call_id = replayed_call.call_id
                summary["reused"] = True
                summary["reused_from_run_id"] = run.retry_of_run_id
                summary["coverage"]["replayed_chars"] += window_audit["coverage"]["offered_chars"]
                keep(
                    "discovery_window_replay_receipt",
                    {
                        "contract": "product-discovery-window-replay-receipt.830.v1",
                        "replayed_from_run_id": run.retry_of_run_id,
                        "source_call_id": replayed_call.call_id,
                        "source_raw_sha256": replayed_call.raw_sha256,
                        "source_stage_key": replayed_call.stage_key,
                        "source_operation_key": replayed_call.operation_key,
                        "source_input_sha256": replayed_call.input_sha256,
                        "source_prompt_sha256": replayed_call.prompt_policy_sha256,
                    },
                    key=artifact_key,
                )
            else:
                result = await service.model_executor.execute_stage_call(
                    store=artifacts,
                    scope=scope,
                    run_id=run.run_id,
                    job=job,
                    stage_key="discovery",
                    operation_key=operation,
                    dependency_sha256=stage.dependency_sha256,
                    input_sha256=input_sha,
                    content=raw_context,
                    prompt=INDEPENDENT_DISCOVERY_PROMPT,
                    template_id=template.template_id,
                )
                call_id = result.call_id
                if result.policy_receipt is not None:
                    summary["coverage"]["offered_chars"] += window_audit["coverage"][
                        "offered_chars"
                    ]
                    summary["coverage"]["sent_window_count"] += 1
                    summary["coverage"]["omitted_chars"] = (
                        total_chars - summary["coverage"]["offered_chars"]
                    )
                if (
                    result.state != "recorded"
                    or result.raw is None
                    or result.diagnostic
                    or result.policy_receipt is None
                ):
                    raise ValueError(
                        "discovery model call failed: " + (result.diagnostic or result.state)
                    )
                raw_response = result.raw
            if replayed_call is not None:
                summary["coverage"]["offered_chars"] += window_audit["coverage"]["offered_chars"]
                summary["coverage"]["sent_window_count"] += 1
                summary["coverage"]["omitted_chars"] = (
                    total_chars - summary["coverage"]["offered_chars"]
                )
            summary["call_ids"].append(call_id)
            decoded = (
                parent_decoded
                if replayed_call is not None
                else _json(ConfiguredFieldTransport.decode_response(raw_response))
            )
            if not isinstance(decoded, dict):
                raise ValueError("discovery generation response must be an object")
            raw = json_bytes(decoded)
            keep(
                "discovery_response",
                json.loads(raw),
                key=artifact_key,
                call_id=None if replayed_call is not None else call_id,
            )
            candidate = (
                parent_candidate
                if replayed_call is not None
                else await asyncio.to_thread(
                    project_independent_discovery_response,
                    raw=raw,
                    request=request,
                    entity_id=entity_id,
                    exclusion_index=exclusion_index,
                    context=context,
                    audit=window_audit,
                )
            )
            assert candidate is not None
            keep(
                "discovery_proposal",
                candidate.proposal,
                key=artifact_key,
                call_id=None if replayed_call is not None else call_id,
            )
            for page in candidate.output.pages:
                identity = free_page_id(page)
                if identity in pages and pages[identity] != page:
                    raise ValueError("conflicting discovery page across windows")
                pages[identity] = page
            for definition in candidate.output.definitions:
                if (
                    definition.concept_id in definitions
                    and definitions[definition.concept_id] != definition
                ):
                    raise ValueError("conflicting discovery concept across windows")
                definitions[definition.concept_id] = definition
            for audit_row in candidate.output.audit:
                if audit_row.key in audit_rows and audit_rows[audit_row.key] != audit_row:
                    raise ValueError("conflicting discovery disposition across windows")
                audit_rows[audit_row.key] = audit_row
            for disposition in candidate.proposal.dispositions:
                item = disposition.model_dump(mode="json")
                if disposition.member_ref is not None:
                    proposal_pages = {
                        row.page_ref: free_page_id(projected)
                        for row, projected in zip(
                            candidate.proposal.proposal.pages,
                            candidate.output.pages,
                            strict=True,
                        )
                    }
                    proposal_definitions = {
                        row.definition_ref: projected.concept_id
                        for row, projected in zip(
                            candidate.proposal.proposal.definitions,
                            candidate.output.definitions,
                            strict=True,
                        )
                    }
                    item["member_id"] = {**proposal_pages, **proposal_definitions}[
                        disposition.member_ref
                    ]
                item["candidate_id"] = entity_id + ":" + window_id + ":" + item["candidate_id"]
                for evidence in item["evidence"]:
                    evidence["source_ref"] = (
                        entity_id + ":" + window_id + ":" + evidence["source_ref"]
                    )
                candidate_dispositions.append(item)
                summary["counts"][
                    disposition.disposition.lower()
                    if disposition.disposition != "REJECT"
                    else "rejected"
                ] += 1
            cited = {
                (e["source_ref"], e["quote"])
                for row in candidate_dispositions[-len(candidate.proposal.dispositions) :]
                for e in row["evidence"]
            }
            for option in context["source_options"]:
                source_ref = entity_id + ":" + window_id + ":" + option["source_ref"]
                spans = [
                    span
                    for span in option["spans"]
                    if any(ref == source_ref and quote in span["quote"] for ref, quote in cited)
                ]
                if spans:
                    candidate_sources.append({"source_ref": source_ref, "spans": spans})
            receipts.append(
                {
                    "entity_id": entity_id,
                    "window_id": window_id,
                    "input_sha256": input_sha,
                    "raw_sha256": hashlib.sha256(raw).hexdigest(),
                    "call_id": call_id,
                    "replayed_from_run_id": (
                        run.retry_of_run_id if replayed_call is not None else None
                    ),
                    "source_call_id": call_id if replayed_call is not None else None,
                    "source_raw_sha256": (
                        replayed_call.raw_sha256 if replayed_call is not None else None
                    ),
                }
            )
            summary["coverage"]["processed_chars"] += window_audit["coverage"]["offered_chars"]
            summary["coverage"]["validated_chars"] = summary["coverage"]["processed_chars"]
            summary["coverage"]["processed_window_count"] += 1
        from insurance_harness.knowledge_compiler.concept_compile_830_g2 import CompileOutput

        free_output = CompileOutput(
            request_hash=empty_output["request_hash"],
            definitions=tuple(sorted(definitions.values(), key=lambda row: row.concept_id)),
            fields=(),
            pages=tuple(sorted(pages.values(), key=free_page_id)),
            audit=tuple(sorted(audit_rows.values(), key=lambda row: row.key)),
            transformation="SYNTHESIZE" if pages or definitions else "EXTRACT",
        )
        candidate_output = free_output.model_dump(mode="json")
        summary["coverage"]["complete"] = summary["coverage"]["processed_chars"] == total_chars
        if not summary["coverage"]["complete"]:
            raise ValueError("discovery source coverage incomplete")
        summary["state"] = "GENERATED" if pages or definitions else "EMPTY"
        summary["reason_codes"] = ["DISCOVERY_" + summary["state"]]
    except (TypeError, ValueError, ModelPolicyDenied) as exc:
        summary["state"] = "FAILED"
        summary["reason_codes"] = ["DISCOVERY_GENERATION_FAILED"]
        summary["failure_detail"] = str(exc)
        candidate_output = empty_output
        candidate_dispositions = []
        candidate_sources = []
    candidates = {
        "contract": "product-discovery-candidates.830.v1",
        "output": candidate_output,
        "dispositions": candidate_dispositions,
        "sources": candidate_sources,
        "exclusion_index_sha256": summary["exclusion_index_sha256"],
        "window_receipts": receipts,
    }
    keep("discovery_candidates", candidates)
    keep(
        "discovery_delta",
        {
            "contract": "product-discovery-delta.830.v1",
            "output": candidate_output,
            "reviewed": False,
        },
    )
    keep("discovery_summary", summary)
    state = (
        ProductRunState.SUCCEEDED
        if summary["state"] in {"GENERATED", "EMPTY"}
        else ProductRunState.PARTIAL_SUCCESS
    )
    return StageOutput(tuple(drafts), state=state)


async def run_discovery_generation_stage(
    *,
    service: ProductScopeServices,
    artifacts: ProductArtifactStore,
    scope: ProductScope,
    run: ProductRunSnapshot,
    stage: StageSnapshot,
    job: JobSnapshot,
    request: BatchConceptCompileRequest830G3V1,
    entity_id: str | None = None,
    exclusion_index: dict[str, Any] | None = None,
    base: dict[str, Any] | None = None,
    processing_recovery: bool = False,
) -> StageOutput:
    """One durable discovery task covers every bound entity and original source span."""
    del base
    if entity_id is not None:
        return await _run_entity_discovery_generation_stage(
            service=service,
            artifacts=artifacts,
            scope=scope,
            run=run,
            stage=stage,
            job=job,
            request=request,
            entity_id=entity_id,
            exclusion_index=exclusion_index or build_discovery_exclusion_index(request, entity_id),
            processing_recovery=processing_recovery,
        )
    outputs = []
    all_drafts: list[ArtifactDraft] = []
    for binding in sorted(request.entity_bindings, key=lambda row: row.entity_id):
        index = (
            exclusion_index[binding.entity_id]
            if exclusion_index is not None
            else build_discovery_exclusion_index(request, binding.entity_id)
        )
        output = await _run_entity_discovery_generation_stage(
            service=service,
            artifacts=artifacts,
            scope=scope,
            run=run,
            stage=stage,
            job=job,
            request=request,
            entity_id=binding.entity_id,
            exclusion_index=index,
            processing_recovery=processing_recovery,
        )
        outputs.append(output)
        all_drafts.extend(row for row in output.drafts if row.artifact_key != "product")
    if not outputs:
        raise ValueError("discovery has no entity bindings")
    product_rows = [
        {
            row.artifact_kind: json.loads(row.payload)
            for row in output.drafts
            if row.artifact_key == "product"
        }
        for output in outputs
    ]
    summaries = [rows["discovery_summary"] for rows in product_rows]
    all_successful = all(row["state"] in {"GENERATED", "EMPTY"} for row in summaries)
    bound_materials = {
        material_id
        for binding in request.entity_bindings
        for material_id in binding.source_material_ids
    }
    unbound_materials = sorted(
        {entry.material_id for entry in request.resolution_inputs.corpus.entries} - bound_materials
    )
    request_hash = compile_request_hash_g3(request.base_request)
    definitions: dict[str, dict[str, Any]] = {}
    pages: dict[str, dict[str, Any]] = {}
    audit_rows: dict[str, dict[str, Any]] = {}
    dispositions = []
    sources = []
    receipts = []
    if all_successful:
        for rows in product_rows:
            output = rows["discovery_delta"]["output"]
            for row in output["definitions"]:
                key = ConceptDefinition.model_validate(row).concept_id
                if key in definitions and definitions[key] != row:
                    all_successful = False
                definitions[key] = row
            for row in output["pages"]:
                key = free_page_id(FreeWikiPage.model_validate(row))
                if key in pages and pages[key] != row:
                    all_successful = False
                pages[key] = row
            for row in output["audit"]:
                key = row["key"]
                if key in audit_rows and audit_rows[key] != row:
                    all_successful = False
                audit_rows[key] = row
            candidates = rows["discovery_candidates"]
            dispositions.extend(candidates["dispositions"])
            sources.extend(candidates["sources"])
            receipts.extend(candidates["window_receipts"])
    if not all_successful or unbound_materials:
        definitions, pages, audit_rows = {}, {}, {}
        dispositions, sources = [], []
    free_output = {
        "request_hash": request_hash,
        "definitions": sorted(
            definitions.values(),
            key=lambda row: ConceptDefinition.model_validate(row).concept_id,
        ),
        "fields": [],
        "pages": sorted(pages.values(), key=lambda row: (row["entity_id"], row["stable_key"])),
        "audit": sorted(audit_rows.values(), key=lambda row: row["key"]),
        "transformation": "SYNTHESIZE" if pages or definitions else "EXTRACT",
    }
    unbound_chars = sum(
        len(block.text)
        for entry in request.resolution_inputs.corpus.entries
        if entry.material_id in unbound_materials
        for block in entry.blocks
    )
    total_chars = (
        sum(row["coverage"]["total_chars"] for row in summaries if row["coverage"]) + unbound_chars
    )
    offered_chars = sum(row["coverage"]["offered_chars"] for row in summaries if row["coverage"])
    validated_chars = sum(
        row["coverage"]["processed_chars"] for row in summaries if row["coverage"]
    )
    coverage = {
        "total_chars": total_chars,
        "offered_chars": offered_chars,
        "validated_chars": validated_chars,
        "omitted_chars": total_chars - offered_chars,
        "sent_window_count": sum(
            row["coverage"]["sent_window_count"] for row in summaries if row["coverage"]
        ),
        "processed_window_count": sum(
            row["coverage"]["processed_window_count"] for row in summaries if row["coverage"]
        ),
        "replayed_chars": sum(
            row["coverage"]["replayed_chars"] for row in summaries if row["coverage"]
        ),
        "material_count": len(request.resolution_inputs.corpus.entries),
        "entities": [
            {"entity_id": binding.entity_id, **(row["coverage"] or {})}
            for binding, row in zip(
                sorted(request.entity_bindings, key=lambda item: item.entity_id),
                summaries,
                strict=True,
            )
        ],
        "complete": (
            not unbound_materials
            and all(row["coverage"] and row["coverage"]["complete"] for row in summaries)
        ),
        "unbound_material_ids": unbound_materials,
    }
    summary = _summary()
    overall_state = (
        "FAILED"
        if not all_successful
        else "PENDING"
        if unbound_materials
        else "PENDING"
        if pages or definitions
        else "EMPTY"
    )
    summary.update(
        state=overall_state,
        reason_codes=[
            "DISCOVERY_UNBOUND_MATERIAL"
            if unbound_materials
            else "DISCOVERY_GENERATED_PENDING_REVIEW"
            if all_successful and (pages or definitions)
            else "DISCOVERY_EMPTY"
            if all_successful
            else "DISCOVERY_GENERATION_FAILED"
        ],
        call_ids=[call_id for row in summaries for call_id in row["call_ids"]],
        reused=any(row["reused"] for row in summaries),
        reused_from_run_id=(
            run.retry_of_run_id if any(row["reused"] for row in summaries) else None
        ),
        coverage=coverage,
        entity_summaries=summaries,
    )
    for key in summary["counts"]:
        summary["counts"][key] = sum(row["counts"][key] for row in summaries)
    candidates = {
        "contract": "product-discovery-candidates.830.v1",
        "output": free_output,
        "dispositions": dispositions,
        "sources": sources,
        "window_receipts": receipts,
        "exclusion_index_sha256": hashlib.sha256(
            json_bytes(
                exclusion_index
                or {
                    row.entity_id: build_discovery_exclusion_index(request, row.entity_id)
                    for row in request.entity_bindings
                }
            )
        ).hexdigest(),
    }
    for kind, value in (
        ("discovery_candidates", candidates),
        (
            "discovery_delta",
            {
                "contract": "product-discovery-delta.830.v1",
                "output": free_output,
                "reviewed": False,
            },
        ),
        ("discovery_summary", summary),
    ):
        all_drafts.append(
            artifact(
                kind,
                "product",
                json_bytes(value),
                stage.dependency_sha256,
                origin=ArtifactOrigin.RULE,
                contract_version=CURRENT_ARTIFACT_CONTRACTS.get(kind, (None, "1"))[1],
            )
        )
    return StageOutput(
        tuple(all_drafts),
        state=(
            ProductRunState.SUCCEEDED
            if all_successful and not unbound_materials
            else ProductRunState.PARTIAL_SUCCESS
        ),
    )


def _template(
    settings: ProductModelSettings, role: str, purpose: str, prompt: bytes
) -> ModelTemplatePolicy:
    matches = [row for row in settings.templates if row.role == role and row.purpose == purpose]
    if len(matches) != 1 or matches[0].prompt_sha256 != hashlib.sha256(prompt).hexdigest():
        raise ModelPolicyDenied("discovery template is missing or changed")
    return matches[0]


def _summary() -> dict[str, Any]:
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


def _unchanged_sources(request: BatchConceptCompileRequest830G3V1, base: dict[str, Any]) -> bool:
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
    service: ProductScopeServices,
    artifacts: ProductArtifactStore,
    scope: ProductScope,
    run: ProductRunSnapshot,
    stage: StageSnapshot,
    job: JobSnapshot,
    request: BatchConceptCompileRequest830G3V1,
    field_delta: CompileResult,
    entity_id: str,
    base: dict[str, Any],
    processing_recovery: bool = False,
) -> StageOutput:
    drafts = []
    summary = _summary()
    delta = field_delta

    def keep(kind: str, value: object, *, call_id: str | None = None, key: str = "product") -> None:
        drafts.append(
            artifact(
                kind,
                key,
                json_bytes(value),
                stage.dependency_sha256,
                origin=ArtifactOrigin.MODEL if call_id else ArtifactOrigin.RULE,
                call_id=call_id,
                contract_version=CURRENT_ARTIFACT_CONTRACTS.get(kind, (None, "1"))[1],
            )
        )

    async def call(
        operation: str, content: object, prompt: bytes, template: ModelTemplatePolicy
    ) -> tuple[bytes, str]:
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
        reuse_prior = False
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
                prior_calls = (
                    artifacts.list_stage_calls(scope=scope, run_id=run.retry_of_run_id)
                    if hasattr(artifacts, "list_stage_calls")
                    else ()
                )
                discovery_calls = tuple(
                    row
                    for row in prior_calls
                    if row.stage_key == "synthesis" and "discovery" in row.operation_key
                )
                replan = (
                    summary.get("state") == "FAILED"
                    and not summary.get("call_ids")
                    and not discovery_calls
                    and (
                        summary.get("dispatch_state") == "NOT_DISPATCHED"
                        or summary.get("failure_detail") == "discovery context budget exceeded"
                    )
                )
                if replan:
                    summary = _summary()
                    summary["reason_codes"] = ["PRIOR_DISCOVERY_PREDISPATCH_REPLAN"]
                else:
                    reuse_prior = True
                if reuse_prior and summary["state"] == "ACCEPTED":
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
                if reuse_prior:
                    summary.update(reused=True, reused_from_run_id=run.retry_of_run_id, call_ids=[])
                    # These members belong to the inherited published base, not new output.
                    summary["accepted_member_count"] = 0
                    summary["counts"]["published"] = 0
            else:
                summary["reason_codes"] = ["PRIOR_DISCOVERY_NOT_EXECUTED"]
        if not reuse_prior and _unchanged_sources(request, base):
            summary["reason_codes"] = ["NO_CHANGED_SOURCE"]
        elif not reuse_prior:
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
