"""Pure semantic admission of verified native candidates, never another discovery.

Callers verify signed snapshots before entering this adapter. No model, storage,
PDF locator or publication effects occur here; final review remains independent.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from insurance_harness.knowledge_compiler.batch_concept_compile_830_g3 import (
    BatchConceptCompileRequest830G3V1,
    compile_request_hash_g3,
)
from insurance_harness.knowledge_compiler.concept_compile_830_g2 import (
    AuditDisposition,
    CompileOutput,
    free_page_id,
)
from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import (
    ConceptDefinition,
    Evidence,
    FreeWikiPage,
    evidence_for,
)
from insurance_harness.product_ingestion.extraction import decode_model_json
from insurance_harness.product_ingestion.native_admission_context import (
    render_native_admission_context,
    resolve_native_window_sources,
)
from insurance_harness.product_ingestion.native_admission_contract import (
    NATIVE_DEPENDENCY_POLICY,
    NativeAdmissionResponse,
    NativeAdmissionResponseV2,
    NativeDefinition,
    NativePage,
    _Member,
)
from insurance_harness.product_ingestion.native_discovery import NativeDiscoverySnapshot
from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot
from insurance_harness.product_ingestion.stages import json_bytes


@dataclass(frozen=True, slots=True)
class NativeAdmissionProjection:
    output: CompileOutput
    response: NativeAdmissionResponse | NativeAdmissionResponseV2
    dispositions: tuple[dict[str, Any], ...]
    context: bytes
    raw: bytes
    isolated_candidates: tuple[dict[str, Any], ...] = ()
    dependency_selection: dict[str, Any] | None = None
    dependency_unavailable_count: int = 0


def project_native_admission_response(
    *,
    raw: bytes,
    request: BatchConceptCompileRequest830G3V1,
    entity_id: str,
    snapshot: NativeDiscoverySnapshot,
    source: DecodedSourceSnapshot,
    context: dict[str, Any],
) -> NativeAdmissionProjection:
    expected = render_native_admission_context(
        request=request,
        entity_id=entity_id,
        snapshot=snapshot,
        source=source,
        max_context_bytes=context["max_context_bytes"],
        dependency_policy=context.get("dependency_policy"),
        isolation_enabled=context.get("isolation_enabled", False),
        relation_capability=context.get("relation_capability"),
    )
    if json_bytes(expected) != json_bytes(context):
        raise ValueError("native admission context mismatch")
    from insurance_harness.product_ingestion.native_relation_admission import (
        admission_response,
        bind_relation_page,
    )

    response = (
        admission_response(decode_model_json(raw), context)
        if context.get("dependency_policy") is not None
        else NativeAdmissionResponse.model_validate(decode_model_json(raw))
    )
    rows: tuple[NativeDefinition | NativePage, ...] = (*response.definitions, *response.pages)
    by_ref = {row.member_ref: row for row in rows}
    if len(by_ref) != len(rows):
        raise ValueError("native admission member reference duplicated")
    old_definitions = {row.concept_id: row for row in request.base_request.existing_definitions}
    old_pages = {
        free_page_id(row): row
        for row in request.base_request.existing_pages
        if row.entity_id == entity_id
    }
    existing = {**old_definitions, **old_pages}
    # The verified context also offers the current product entity. Referencing
    # it is audit-only; NEW/UPDATE still use the editable member map above.
    reference_targets = {*existing, entity_id}
    revisions = {
        row["concept_id"]: row["revision_sha256"]
        for row in context["existing_knowledge"]["definitions"]
    } | {row["page_id"]: row["revision_sha256"] for row in context["existing_knowledge"]["pages"]}
    blocks = resolve_native_window_sources(request, entity_id, snapshot, source)
    offered = {f"s{i + 1}": block for i, block in enumerate(blocks)}
    definitions: list[ConceptDefinition] = []
    pages: list[FreeWikiPage] = []
    audit: list[AuditDisposition] = []
    projected: dict[str, ConceptDefinition | FreeWikiPage] = {}
    concept_refs = {identity: identity for identity in old_definitions}
    definitions_by_ref = dict(old_definitions)

    def evidence_for_row(row: _Member) -> tuple[Evidence, ...]:
        result = []
        for e in row.evidence:
            block = offered.get(e.source_ref)
            if block is None or block.text[e.start : e.start + len(e.quote)] != e.quote:
                raise ValueError("native admission original quote/offset mismatch")
            result.append(evidence_for(block, e.start, e.start + len(e.quote)))
        return tuple(result)

    def retain(row: _Member, member: ConceptDefinition | FreeWikiPage, identity: str) -> None:
        old = existing.get(identity)
        if isinstance(old, FreeWikiPage) and isinstance(member, FreeWikiPage):
            from insurance_harness.knowledge_compiler.product_concept_relation import (
                validate_relation_update,
            )

            validate_relation_update(old, member)
        if row.action == "UPDATE":
            if (
                not context["knowledge_updates_enabled"]
                or old is None
                or old == member
                or row.expected_revision_sha256 != revisions.get(identity)
                or isinstance(old, ConceptDefinition)
                and old.origin != "MODEL_COMPILE"
                or isinstance(old, FreeWikiPage)
                and (
                    not isinstance(member, FreeWikiPage)
                    or old.entity_version != member.entity_version
                )
            ):
                raise ValueError("native admission update target/revision invalid")
        elif old is not None or row.expected_revision_sha256 is not None:
            raise ValueError("native admission new identity collides with existing knowledge")
        # A field title/alias is not its meaning. Admission and independent
        # review compare the complete Schema descriptions and member content;
        # this projector enforces identities, provenance and the field-free DTO.
        if identity in {a.key for a in audit}:
            raise ValueError("native admission duplicate projected identity")
        projected[row.member_ref] = member
        audit.append(
            AuditDisposition(
                key=identity,
                disposition="update" if row.action == "UPDATE" else "new_page",
                reason=row.audit_reason,
            )
        )

    for row in response.definitions:
        if row.member_ref in concept_refs:
            raise ValueError("native admission concept reference collision")
        member = ConceptDefinition(
            space_id=request.base_request.space_id,
            canonical_key=row.canonical_key,
            sense_key=row.sense_key,
            title=row.title,
            body=row.body,
            aliases=row.aliases,
            evidence=evidence_for_row(row),
            content_provenance=row.content_provenance,
            origin="MODEL_COMPILE",
        )
        retain(row, member, member.concept_id)
        definitions.append(member)
        concept_refs[row.member_ref] = member.concept_id
        definitions_by_ref[row.member_ref] = member
        if member.concept_id in definitions_by_ref:
            definitions_by_ref[member.concept_id] = member
    for page_row in response.pages:
        if not set(page_row.concept_refs) <= concept_refs.keys():
            raise ValueError("native admission foreign concept reference")
        relation_fields = bind_relation_page(
            page_row,
            space_id=request.base_request.space_id,
            entity_id=entity_id,
            definitions_by_ref=definitions_by_ref,
        )
        page = FreeWikiPage(
            space_id=request.base_request.space_id,
            entity_id=entity_id,
            entity_version=context["entity"]["entity_version"],
            **{"stable_key": page_row.stable_key, **relation_fields},
            title=page_row.title,
            body=page_row.body,
            concept_ids=tuple(concept_refs[ref] for ref in page_row.concept_refs),
            conditions=page_row.conditions,
            exceptions=page_row.exceptions,
            valid_time=page_row.valid_time,
            evidence=evidence_for_row(page_row),
            content_provenance=page_row.content_provenance,
        )
        retain(page_row, page, free_page_id(page))
        pages.append(page)
    if not {row.concept_id for row in definitions} <= {
        identity for page in pages for identity in page.concept_ids
    }:
        raise ValueError("native admission definition lacks page use")
    candidates = {row["candidate_ref"]: row for row in context["native_candidates"]}
    decisions = {row.candidate_ref: row for row in response.decisions}
    if len(decisions) != len(response.decisions) or set(decisions) != set(candidates):
        raise ValueError("native admission candidate coverage mismatch")
    covered: set[str] = set()
    dispositions: list[dict[str, Any]] = []
    for decision in response.decisions:
        native = candidates[decision.candidate_ref]
        if decision.decision == "REFERENCE" and decision.existing_target == entity_id:
            if native["kind"] != "entity" or native["name"] != context["entity"]["display_name"]:
                raise ValueError("native admission current entity candidate identity mismatch")
        refs = decision.member_refs
        if len(set(refs)) != len(refs) or not set(refs) <= by_ref.keys():
            raise ValueError("native admission decision member mismatch")
        if decision.decision in {"NEW", "UPDATE"}:
            if not refs or decision.existing_target is not None:
                raise ValueError("native admission promoted decision invalid")
            updates = any(by_ref[ref].action == "UPDATE" for ref in refs)
            if updates != (decision.decision == "UPDATE"):
                raise ValueError("native admission action mismatch")
            covered.update(refs)
        elif (
            refs
            or (
                decision.decision == "REFERENCE"
                and decision.existing_target not in reference_targets
            )
            or (decision.decision != "REFERENCE" and decision.existing_target is not None)
        ):
            raise ValueError("native admission audit-only decision invalid")
        for ref in refs or (None,):
            promoted_member = projected[ref] if ref is not None else None
            selections = (
                [e.model_dump(mode="json", exclude={"start"}) for e in by_ref[ref].evidence]
                if ref
                else []
            )
            dispositions.append(
                {
                    "candidate_id": snapshot.snapshot_sha256
                    + ":"
                    + decision.candidate_ref
                    + ":"
                    + (ref or "audit"),
                    "disposition": by_ref[ref].action if ref is not None else decision.decision,
                    "member_id": (
                        promoted_member.concept_id
                        if isinstance(promoted_member, ConceptDefinition)
                        else free_page_id(promoted_member)
                    )
                    if promoted_member
                    else None,
                    "text": promoted_member.body
                    if promoted_member
                    else "\n".join([native["name"], native["description"], native["details"]]),
                    "evidence": selections,
                    "reason": decision.reason,
                    "business_use": decision.reason,
                    "existing_target": decision.existing_target,
                    "native_content_origin": "MODEL_GENERATED",
                }
            )
    if covered != set(by_ref):
        raise ValueError("native admission unbound promoted member")
    isolated: tuple[dict[str, Any], ...] = ()
    selection = None
    unavailable_count = 0
    if isinstance(response, NativeAdmissionResponseV2):
        from insurance_harness.product_ingestion.native_dependency_selection import (
            select_native_dependencies,
        )

        kept, isolated, edges = select_native_dependencies(response, projected)
        unavailable_count = len(isolated)
    if isinstance(response, NativeAdmissionResponseV2) and context["isolation_enabled"]:
        retained_refs = {
            ref for d in response.decisions if d.candidate_ref in kept for ref in d.member_refs
        }
        retained_ids = {
            member.concept_id if isinstance(member, ConceptDefinition) else free_page_id(member)
            for ref, member in projected.items()
            if ref in retained_refs
        }
        retained_dispositions = {
            snapshot.snapshot_sha256 + ":" + d.candidate_ref + ":" + (ref or "audit")
            for d in response.decisions
            if d.candidate_ref in kept
            for ref in d.member_refs or (None,)
        }
        definitions = [d for d in definitions if d.concept_id in retained_ids]
        pages = [p for p in pages if free_page_id(p) in retained_ids]
        audit = [a for a in audit if a.key in retained_ids]
        dispositions = [d for d in dispositions if d["candidate_id"] in retained_dispositions]
        selection = {
            "contract": "native-dependency-selection.830.v1",
            "dependency_policy": NATIVE_DEPENDENCY_POLICY,
            "request_hash": compile_request_hash_g3(request.base_request),
            "admission_context": context,
            "admission_context_sha256": hashlib.sha256(json_bytes(context)).hexdigest(),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "native_snapshot_sha256": snapshot.snapshot_sha256,
            "entity_id": entity_id,
            "windows": [row.model_dump(mode="json") for row in snapshot.windows],
            "response": response.model_dump(mode="json"),
            "effective_dependencies": edges,
            "retained_candidates": sorted(kept),
            "retained_member_refs": sorted(retained_refs),
            "retained_member_ids": sorted(retained_ids),
            "isolated_candidates": list(isolated),
            "isolated_member_refs": sorted(set(projected) - retained_refs),
        }
        selection["selection_sha256"] = hashlib.sha256(json_bytes(selection)).hexdigest()
    else:
        isolated = ()
    output = CompileOutput(
        request_hash=compile_request_hash_g3(request.base_request),
        fields=(),
        definitions=tuple(sorted(definitions, key=lambda row: row.concept_id)),
        pages=tuple(sorted(pages, key=lambda row: (row.entity_id, row.stable_key))),
        audit=tuple(sorted(audit, key=lambda row: row.key)),
        transformation="SYNTHESIZE" if rows else "EXTRACT",
    )
    return NativeAdmissionProjection(
        output,
        response,
        tuple(dispositions),
        json_bytes(context),
        raw,
        isolated,
        selection,
        unavailable_count,
    )
