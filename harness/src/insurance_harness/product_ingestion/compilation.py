"""Pure compiler adapter for durable platform product artifacts."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from insurance_harness.knowledge_compiler import batch_concept_compile_830_g3 as compiler
from insurance_harness.knowledge_compiler import batch_entity_resolution_830_g3 as resolver
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    AuditDisposition,
    CompileOutput,
    CompileRequest,
    CompileResult,
    ExecutionRecord,
    HumanBatchAdmission,
    ReviewOutput,
    ReviewResult,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    FieldAssertion,
    SourceBlock,
)
from insurance_harness.knowledge_compiler.g3_field_tasks import (
    FieldTaskEvidenceResultV1,
    adapt_catalog_field_tasks,
)
from insurance_harness.product_ingestion.models import FieldOutcomeKind, ProductScope

_BASE_CONTRACT = "g3-platform-base-snapshot.830.v1"
_PROJECTION_CONTRACT = "g3-platform-published-projection.830.v1"
_PROJECTION_ORIGIN = "published-batch-read-projection.830.g3.v2"


def _value(row: object, name: str) -> Any:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _scope(scope: ProductScope) -> dict[str, object]:
    try:
        tenant_id = int(scope.tenant_id)
    except (TypeError, ValueError):
        raise ValueError("platform scope tenant is invalid") from None
    if str(tenant_id) != scope.tenant_id or tenant_id < 1:
        raise ValueError("platform scope tenant is invalid")
    return {
        "tenant_id": tenant_id,
        "space_id": scope.space_id,
        "raw_kb_id": scope.raw_knowledge_base_id,
        "wiki_kb_id": scope.wiki_knowledge_base_id,
    }


def _published_base(
    *, scope: ProductScope, base_body: Mapping[str, Any]
) -> tuple[Mapping[str, Any], tuple[compiler.EntityCompileBinding830G3V1, ...]]:
    if not isinstance(base_body, Mapping):
        raise ValueError("published base body is invalid")
    projection = base_body.get("published_projection")
    if (
        base_body.get("contract") != _BASE_CONTRACT
        or base_body.get("scope") != _scope(scope)
        or not isinstance(projection, Mapping)
        or base_body.get("published_projection_contract") != _PROJECTION_CONTRACT
        or projection.get("contract") != _PROJECTION_CONTRACT
        or projection.get("origin_contract") != _PROJECTION_ORIGIN
        or projection.get("candidate_hash") != base_body.get("candidate_sha256")
    ):
        raise ValueError("published base identity is invalid")
    try:
        release_id = base_body["release_id"]
        epoch = base_body["activation_epoch"]
        snapshot_sha256 = base_body["snapshot_sha256"]
        manifest_digest = base_body["manifest_digest"]
        bindings = tuple(
            compiler.EntityCompileBinding830G3V1.model_validate(row)
            for row in projection["entity_bindings"]
        )
        versions = dict(projection["entity_versions"])
        page_members = tuple(projection["page_members"])
        members = tuple(base_body["members"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("published base structure is invalid") from None
    expected_versions = {row.entity_id: row.entity_version for row in bindings}
    if (
        not isinstance(release_id, str)
        or not release_id
        or type(epoch) is not int
        or epoch < 1
        or not isinstance(snapshot_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", snapshot_sha256) is None
        or not isinstance(manifest_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", manifest_digest) is None
        or tuple(row.entity_id for row in bindings) != tuple(sorted(expected_versions))
        or len(expected_versions) != len(bindings)
        or versions != expected_versions
    ):
        raise ValueError("published base binding is invalid")
    expected_members = tuple(
        {
            "kind": row["kind"] if isinstance(row, Mapping) else row.kind,
            "logical_slug": (row["member_id"] if isinstance(row, Mapping) else row.member_id),
            "revision_id": base_body["candidate_sha256"],
            "member_digest": compiler._batch_sha256("batch-concept-member.830.g3.v1", row),
        }
        for row in page_members
    )
    normalized_members = tuple(dict(row) for row in members if isinstance(row, Mapping))
    if (
        not expected_members
        or len(normalized_members) != len(members)
        or normalized_members != expected_members
    ):
        raise ValueError("published base members are invalid")
    return projection, bindings


def build_existing_snapshot(
    *,
    scope: ProductScope,
    base_body: Mapping[str, Any],
    policy: resolver.BatchResolutionPolicyV1,
) -> resolver.ExistingEntitySnapshotV1:
    """Derive resolver identities from one already verified current-Head snapshot."""

    policy = resolver.BatchResolutionPolicyV1.model_validate(policy)
    _projection, bindings = _published_base(scope=scope, base_body=base_body)
    entities = tuple(
        resolver.ExistingEntityV1(
            entity_id=row.entity_id,
            entity_version=row.entity_version,
            product_id=None,
            product_version_id=None,
            issuer=row.issuer,
            name=row.display_name,
            product_code=row.product_code,
            version_label=row.version_label,
            filing_or_registration=resolver.VersionAnchorV1(
                kind=row.version_anchor.kind,
                value=row.version_anchor.observed_value,
            ),
            approved_aliases=(),
            identity_evidence_sha256s=tuple(
                sorted({item.evidence.quote_hash for item in row.resolution_evidence})
            ),
        )
        for row in bindings
    )
    payload: dict[str, object] = {
        "contract": "existing-entities.830.g3.v1",
        **_scope(scope),
        "base_release_id": base_body["release_id"],
        "base_activation_epoch": base_body["activation_epoch"],
        "head_receipt_sha256": base_body["snapshot_sha256"],
        "resolver_version": resolver.COMPILER_VERSION_V2,
        "resolver_policy_sha256": policy.policy_sha256,
        "entities": entities,
    }
    return resolver.ExistingEntitySnapshotV1.model_validate(
        {
            **payload,
            "snapshot_sha256": compiler._batch_sha256("existing-entities.830.g3.v1", payload),
        }
    )


# Go's published read DTO may encode empty slices as null. Adapt only these
# optional collection slots after signature/member verification; original signed
# dictionaries, scalar nulls and required evidence remain untouched.
_PUBLISHED_EMPTY_COLLECTIONS = {
    "definitions": ("aliases",),
    "fields": ("evidence", "concept_ids", "conditions", "exceptions"),
    "pages": ("concept_ids", "conditions", "exceptions"),
}


def published_compile_members(projection: Mapping[str, Any], kind: str) -> tuple:
    keys = _PUBLISHED_EMPTY_COLLECTIONS[kind]
    return tuple(
        {**row, **{key: () for key in keys if key in row and row[key] is None}}
        if isinstance(row, Mapping)
        else row
        for row in projection.get(kind, ())
    )


def build_platform_compile_request(
    *,
    scope: ProductScope,
    base_body: Mapping[str, Any],
    catalog_json: bytes,
    profile_confirmation_json: bytes,
    corpus: resolver.BatchCorpusV1,
    proposals: resolver.ProposalBatchV1,
    policy: resolver.BatchResolutionPolicyV1,
    resolution: resolver.BatchEntityResolutionV1,
    selected_refs: tuple[tuple[str, str], ...],
    refresh_fields: tuple[Mapping[str, str], ...] = (),
) -> compiler.BatchConceptCompileRequest830G3V1:
    """Build the exact parent carry plus current-C request; old C is never replayed."""

    projection, parent_bindings = _published_base(scope=scope, base_body=base_body)
    corpus = resolver.BatchCorpusV1.model_validate(corpus)
    proposals = resolver.ProposalBatchV1.model_validate(proposals)
    policy = resolver.BatchResolutionPolicyV1.model_validate(policy)
    resolution = resolver.BatchEntityResolutionV1.model_validate(resolution)
    if selected_refs != tuple(sorted(set(selected_refs))) or any(
        type(row) is not tuple
        or len(row) != 2
        or not all(isinstance(item, str) and item for item in row)
        for row in selected_refs
    ):
        raise ValueError("selected resolution refs must be sorted unique pairs")
    catalog = compiler.validate_catalog(catalog_json)
    catalog_identity = projection.get("catalog")
    if catalog_identity != {
        "catalog_id": catalog.catalog_id,
        "catalog_version": catalog.catalog_version,
        "catalog_sha256": catalog.catalog_sha256,
    }:
        raise ValueError("published base catalog changed")
    current_bindings = compiler._build_entity_bindings(
        catalog=catalog,
        proposals=proposals,
        resolution=resolution,
        selected_decision_refs=selected_refs,
    )
    merged = {row.entity_id: row for row in parent_bindings}
    merged.update({row.entity_id: row for row in current_bindings})
    bindings = tuple(merged[key] for key in sorted(merged))

    sources: dict[tuple[str, str], SourceBlock] = {}
    for raw in (
        *projection.get("sources", ()),
        *(block for entry in corpus.entries for block in entry.blocks),
    ):
        block = SourceBlock.model_validate(raw)
        key = (block.revision_id, block.block_id)
        previous = sources.get(key)
        if previous is not None and previous != block:
            raise ValueError("published and current source blocks conflict")
        sources[key] = block
    if not sources:
        raise ValueError("platform compile requires source blocks")
    entity_versions = {row.entity_id: row.entity_version for row in bindings}
    required_fields = {row.entity_id: row.required_fields for row in bindings}
    request_identity = compiler._batch_sha256(
        "platform-product-compile-request.830.g3.v1",
        {
            "base_snapshot_sha256": base_body["snapshot_sha256"],
            "corpus_sha256": corpus.corpus_sha256,
            "proposals_sha256": proposals.proposals_sha256,
            "resolution_sha256": resolution.batch_sha256,
            "selected_refs": selected_refs,
            "refresh_fields": refresh_fields,
        },
    )
    base_request = CompileRequest(
        request_id="product-ingestion-" + request_identity,
        **_scope(scope),
        policy_identity="g3-resolution-policy:" + policy.policy_sha256,
        sources=tuple(sources[key] for key in sorted(sources)),
        required_fields=required_fields,
        existing_definitions=published_compile_members(projection, "definitions"),
        existing_fields=published_compile_members(projection, "fields"),
        existing_pages=published_compile_members(projection, "pages"),
        existing_entity_versions=dict(projection["entity_versions"]),
        entity_versions=entity_versions,
        schema_identity=(
            f"catalog:{catalog.catalog_id}@{catalog.catalog_version}#{catalog.catalog_sha256}"
        ),
        profile_identity=compiler._profile_set_identity(bindings),
        purpose="Platform product ingestion from signed source and published base custody",
        budget_identity="platform-persisted-field-artifacts.830.g3.v1",
        base_release_id=base_body["release_id"],
        base_activation_epoch=base_body["activation_epoch"],
    )
    published_payload: dict[str, object] = {
        "contract": "published-base-binding.830.g3.v1",
        "release_id": base_body["release_id"],
        "activation_epoch": base_body["activation_epoch"],
        "candidate_sha256": base_body["candidate_sha256"],
        "manifest_digest": base_body["manifest_digest"],
        "entity_bindings": parent_bindings,
    }
    published = compiler.PublishedBaseBinding830G3V1.model_validate(
        {
            **published_payload,
            "binding_sha256": compiler._batch_sha256(
                "published-base-binding.830.g3.v1", published_payload
            ),
        }
    )
    existing = build_existing_snapshot(scope=scope, base_body=base_body, policy=policy)
    return compiler.build_batch_compile_request(
        base_request=base_request,
        catalog_json=catalog_json,
        profile_confirmation_json=profile_confirmation_json,
        corpus=corpus,
        proposals=proposals,
        existing_entities=existing,
        policy=policy,
        resolution=resolution,
        selected_decision_refs=selected_refs,
        published_base=published,
        refresh_fields=refresh_fields,
    )


def _field_result(
    *,
    request: compiler.BatchConceptCompileRequest830G3V1,
    task,
    attempt: object,
) -> tuple[FieldAssertion, str]:
    if (
        _value(attempt, "entity_id") != task.entity_id
        or _value(attempt, "field_key") != task.field_key
        or _value(attempt, "task_sha256") != task.task_sha256
        or not isinstance(_value(attempt, "raw_ref"), str)
        or not _value(attempt, "raw_ref")
    ):
        raise ValueError("field attempt task identity mismatch")
    outcome = _value(attempt, "outcome")
    outcome = outcome.value if isinstance(outcome, FieldOutcomeKind) else outcome
    raw_result = _value(attempt, "validated_result")
    if outcome in {FieldOutcomeKind.VERIFIED.value, FieldOutcomeKind.NOT_PROVIDED.value}:
        try:
            result = FieldTaskEvidenceResultV1.model_validate(raw_result)
            checked = FieldTaskEvidenceResultV1.create(
                task=task,
                state=result.state,
                value=result.value,
                evidence=result.evidence,
                unknown_reason=result.unknown_reason,
                concept_ids=result.concept_ids,
                conditions=result.conditions,
                exceptions=result.exceptions,
                valid_time=result.valid_time,
                source_blocks=request.base_request.sources,
            )
        except (TypeError, ValueError):
            raise ValueError("validated field attempt is invalid") from None
        if checked != result or (outcome == FieldOutcomeKind.NOT_PROVIDED.value) != (
            result.state == "unknown"
        ):
            raise ValueError("validated field attempt outcome mismatch")
        reason = (
            "VALIDATED_NOT_PROVIDED" if result.state == "unknown" else "VALIDATED_FIELD_ARTIFACT"
        )
        return (
            FieldAssertion(
                space_id=request.base_request.space_id,
                entity_id=task.entity_id,
                field_key=task.field_key,
                entity_version=task.entity_version,
                state=result.state,
                value=result.value,
                attempted=True,
                unknown_reason=result.unknown_reason,
                evidence=result.evidence,
                concept_ids=result.concept_ids,
                conditions=result.conditions,
                exceptions=result.exceptions,
                valid_time=result.valid_time,
            ),
            reason,
        )
    reason = _value(attempt, "reason")
    if (
        outcome != FieldOutcomeKind.EXTRACTION_FAILED.value
        or raw_result is not None
        or not isinstance(reason, str)
        or not reason
        or reason != reason.strip()
    ):
        raise ValueError("failed field attempt is invalid")
    unknown_reason = "EXTRACTION_FAILED:" + reason
    return (
        FieldAssertion(
            space_id=request.base_request.space_id,
            entity_id=task.entity_id,
            field_key=task.field_key,
            entity_version=task.entity_version,
            state="unknown",
            value=None,
            attempted=True,
            unknown_reason=unknown_reason,
        ),
        unknown_reason,
    )


def project_field_attempts(
    *,
    request: compiler.BatchConceptCompileRequest830G3V1,
    attempts: Sequence[object],
    run_id: str,
) -> CompileResult:
    """Project terminal field artifacts; ordinary failures remain explicit unknowns."""

    request = compiler.BatchConceptCompileRequest830G3V1.model_validate(request)
    tasks = adapt_catalog_field_tasks(request)
    by_key: dict[tuple[str, str], object] = {}
    for attempt in attempts:
        key = (_value(attempt, "entity_id"), _value(attempt, "field_key"))
        if key in by_key:
            raise ValueError("field attempts contain duplicate task")
        by_key[key] = attempt
    expected = {(task.entity_id, task.field_key) for task in tasks}
    if set(by_key) != expected:
        raise ValueError("field attempt task coverage mismatch")
    fields: list[FieldAssertion] = []
    audit: list[AuditDisposition] = []
    for task in tasks:
        field, reason = _field_result(
            request=request, task=task, attempt=by_key[(task.entity_id, task.field_key)]
        )
        fields.append(field)
        audit.append(
            AuditDisposition(
                key=field.assertion_id,
                disposition="field_rule",
                reason=reason,
            )
        )
    output = CompileOutput(
        request_hash=compiler.compile_request_hash_g3(request.base_request),
        fields=tuple(sorted(fields, key=lambda row: (row.entity_id, row.field_key))),
        audit=tuple(sorted(audit, key=lambda row: row.key)),
        transformation="EXTRACT",
    )
    return compiler.record_model_compile(
        request,
        output,
        run_id=run_id,
        implementation="platform-field-artifact-projector.830.g3.v1",
        raw=compiler._canonical_json(output),
    )


def _derived_run_id(run_id: str, stage: str) -> str:
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("platform run id is invalid")
    return "product-" + stage + "-" + hashlib.sha256(run_id.encode()).hexdigest()[:32]


def published_navigation_assignments(
    base_body: dict,
) -> tuple[compiler.NavigationAssignment830G3V1, ...]:
    """Read verified projection navigation, including Go's optional null slice."""
    rows = base_body["published_projection"].get("navigation_assignments")
    if rows is None:
        return ()
    return tuple(compiler.NavigationAssignment830G3V1.model_validate(row) for row in rows)


def assemble_platform_candidate(
    *,
    request: compiler.BatchConceptCompileRequest830G3V1,
    delta: CompileResult,
    run_id: str,
    independent_review: ReviewResult | None = None,
    navigation_assignments: tuple[compiler.NavigationAssignment830G3V1, ...] = (),
) -> compiler.BatchConceptCandidateBundle830G3V1:
    """Reuse field validation; novel free members additionally require independent review."""

    request = compiler.BatchConceptCompileRequest830G3V1.model_validate(request)
    delta = CompileResult.model_validate(delta)
    compiler.validate_delta_output(request, delta)
    output = compiler.compose_batch_output(request, delta)
    from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
        _g3_human_admission,
        _g3_novel_page_ids,
    )

    novel_members = _g3_novel_page_ids(request, output)
    if novel_members and (
        independent_review is None
        or independent_review.execution.implementation
        not in {
            "platform-independent-discovery-review.830.g3.v1",
            "platform-combined-field-discovery-review.830.g3.v1",
        }
    ):
        raise ValueError("INDEPENDENT_DISCOVERY_REVIEW_REQUIRED")
    composed = compiler.record_composed_output(
        request,
        delta,
        output,
        run_id=_derived_run_id(run_id, "carry"),
    )
    review_output = ReviewOutput(
        request_hash=compiler.compile_request_hash_g3(request.base_request),
        output_hash=compiler.compile_output_hash_g3(output),
        decision="PASS",
        reasons=("PLATFORM_STRUCTURAL_EVIDENCE_VALIDATED",),
        page_scores={},
    )
    raw = compiler._canonical_json(review_output)
    rule_review = ReviewResult(
        output=review_output,
        execution=ExecutionRecord(
            run_id=_derived_run_id(run_id, "structural-review"),
            implementation="platform-structural-evidence-review.830.g3.v1",
            context_hash=compiler._batch_sha256(
                "batch-concept-review-context.830.g3.v1",
                compiler.review_context_g3(request, output),
            ),
            raw_output=raw,
            raw_output_hash=hashlib.sha256(raw.encode()).hexdigest(),
        ),
    )
    review = independent_review if independent_review is not None else rule_review
    admission = (
        _g3_human_admission(request, output, review.output)
        if novel_members
        else HumanBatchAdmission(
            contract="concept-admission.830.g2.v1",
            status="NEEDS_HUMAN",
            pending_page_ids=(),
        )
    )
    candidate = compiler.assemble_candidate_bundle(
        request,
        delta,
        composed,
        review,
        admission,
        navigation_assignments=navigation_assignments,
    )
    compiler.validate_candidate_bundle(candidate)
    return candidate
