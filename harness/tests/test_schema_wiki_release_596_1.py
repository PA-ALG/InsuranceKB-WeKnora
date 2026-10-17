from __future__ import annotations

import hashlib
import inspect
from typing import cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.parsed_documents import (
    ParseQualityDecisionV1,
    ParseQualityMeasuredFactsV1,
)
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    EvidenceReplayCaseV1,
    Schema67CandidateV2,
)
from insurance_harness.knowledge_compiler.schema67_native_pdf_selection_815 import (
    CoordinateEvidence815V1,
    CoordinateEvidenceCompanion815V1,
)
from insurance_harness.knowledge_compiler.schema_wiki_candidate_evidence_join_596_1 import (
    CandidateEvidenceAuthorityError,
    LiveChunkAuthorityInputV1,
    LiveRevisionSourceReceiptV1,
    Schema67CandidateEvidenceAuthorityV1,
    build_schema67_candidate_evidence_authority_596_1,
    knowledge_revision_source_id,
    live_revision_source_receipt_sha256,
)
from insurance_harness.knowledge_compiler.vertical_falsification import (
    AdmittedParseArtifactV1,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _live_receipt(
    *,
    source_sha256: str,
    role: str,
    parsed_document_sha256: str,
    parse_manifest_sha256: str,
    evidence_parse_attempt_id: str,
) -> LiveRevisionSourceReceiptV1:
    identities = {
        "terms": (
            "f987fc16-222a-4246-8ca0-22c1a81dd6d9",
            2,
            39,
        ),
        "brochure": (
            "1265a343-c408-4620-8eed-c4f6a2adadc2",
            1,
            27,
        ),
        "rate_table": (
            "32402c40-6131-4049-8080-cc5b68188cd3",
            1,
            2,
        ),
    }
    knowledge_id, attempt, page_count = identities[role]
    resource_id = f"resource-{role}-596-1"
    mime_type = "application/pdf"
    size = 4096 + len(role)
    source_id = knowledge_revision_source_id(
        tenant_id=10003,
        knowledge_id=knowledge_id,
        weknora_parse_attempt=attempt,
        resource_id=resource_id,
        file_sha256=source_sha256,
        size=size,
        mime_type=mime_type,
    )
    payload = {
        "contract": "live-revision-source-receipt.v1",
        "revision_source_id": source_id,
        "tenant_id": 10003,
        "space_id": "space-596-1",
        "raw_kb_id": "raw-kb-596-1",
        "wiki_kb_id": "wiki-kb-596-1",
        "knowledge_id": knowledge_id,
        "evidence_parse_attempt_id": evidence_parse_attempt_id,
        "weknora_parse_attempt": attempt,
        "resource_id": resource_id,
        "file_sha256": source_sha256,
        "size": size,
        "mime_type": mime_type,
        "page_count": page_count,
        "parsed_document_sha256": parsed_document_sha256,
        "parse_manifest_sha256": parse_manifest_sha256,
        "weknora_manifest_algorithm": "weknora.chunk_manifest.v1",
        "weknora_manifest_digest": _sha(f"weknora-manifest-{role}"),
        "weknora_chunk_count": 100 + len(role),
    }
    return LiveRevisionSourceReceiptV1.model_validate(
        {
            **payload,
            "source_receipt_sha256": live_revision_source_receipt_sha256(payload),
        }
    )


def _authority_inputs_from_cases(
    candidate: Schema67CandidateV2,
    cases: tuple[EvidenceReplayCaseV1, ...],
) -> tuple[
    tuple[AdmittedParseArtifactV1, ...],
    tuple[LiveRevisionSourceReceiptV1, ...],
    tuple[LiveChunkAuthorityInputV1, ...],
]:
    document = cases[0].documents[0]
    manifest = cases[0].manifests[0]
    decision = ParseQualityDecisionV1(
        contract="parse-quality-decision.v1",
        subject=document.subject,
        manifest_hash=manifest.manifest_hash,
        parse_policy_receipt=None,
        measured_facts=ParseQualityMeasuredFactsV1(
            threshold_version="parse-quality-structural.v1",
            required_capabilities=manifest.required_capabilities,
            satisfied_capabilities=manifest.satisfied_capabilities,
            unsatisfied_capabilities=manifest.unsatisfied_capabilities,
            trigger_conditions=(),
            attempts_exhausted=True,
        ),
        decision="ADMIT",
        reason_codes=(),
        admitted_attempt_id=document.attempt.attempt_id,
        next_parser_profile_ref=None,
        review_item=None,
    )
    artifact = AdmittedParseArtifactV1(
        role="terms",
        source_sha256=document.subject.source_sha256,
        artifact_sha256=document.document_hash,
        document=document,
        manifest=manifest,
        decision=decision,
        manifest_sha256=manifest.manifest_hash,
        decision_sha256=decision.decision_hash,
        sanitized_structure=b"{}",
        raw_structure_sha256=_sha("raw-structure-terms"),
        sanitized_structure_sha256=hashlib.sha256(b"{}").hexdigest(),
        capture_identity_sha256=_sha("capture-identity-terms"),
        content_snapshot_sha256=_sha("content-snapshot-terms"),
    )
    source_roles = tuple(candidate.source_roles)
    receipts = (
        _live_receipt(
            source_sha256=source_roles[0]["source_sha256"],
            role="terms",
            parsed_document_sha256=document.document_hash,
            parse_manifest_sha256=manifest.manifest_hash,
            evidence_parse_attempt_id=document.attempt.attempt_id,
        ),
        _live_receipt(
            source_sha256=source_roles[1]["source_sha256"],
            role="brochure",
            parsed_document_sha256=_sha("parsed-document-brochure"),
            parse_manifest_sha256=_sha("parse-manifest-brochure"),
            evidence_parse_attempt_id="brochure-attempt-1",
        ),
        _live_receipt(
            source_sha256=source_roles[2]["source_sha256"],
            role="rate_table",
            parsed_document_sha256=_sha("parsed-document-rate"),
            parse_manifest_sha256=_sha("parse-manifest-rate"),
            evidence_parse_attempt_id="rate-attempt-1",
        ),
    )
    unique_evidence = {
        (evidence.locator.subject_ref, evidence.locator.content_snapshot): evidence
        for output in candidate.fields
        for evidence in output.evidence
    }
    chunks = tuple(
        LiveChunkAuthorityInputV1(
            source_role="terms",
            locator_ref=locator_ref,
            chunk_id=f"chunk-terms-{index}",
            chunk_index=index,
            content_snapshot=content,
            chunk_content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
        for index, ((locator_ref, content), _) in enumerate(
            sorted(unique_evidence.items()),
            start=1,
        )
    )
    return (artifact,), receipts, chunks


def _native_coordinate_companion(
    candidate: Schema67CandidateV2,
    artifact: AdmittedParseArtifactV1,
) -> CoordinateEvidenceCompanion815V1:
    assert artifact.raw_structure_sha256 is not None
    blocks = {row.block_id: row for row in artifact.document.blocks}
    rows = tuple(
        CoordinateEvidence815V1(
            field_id=output.field_id,
            source_revision_id=evidence.source_revision_id,
            source_role="terms",
            original_file_sha256=evidence.source_sha256,
            parse_manifest_sha256=artifact.raw_structure_sha256,
            selection_id=f"selection-native-{field_index}-{evidence_index}",
            selection_type="TEXT_SPAN",
            page_number=evidence.page_number,
            page_text_char_start=0,
            page_text_char_end=len(evidence.quote_snapshot),
            coordinate_space="PDF_POINTS_TOP_LEFT_V1",
            page_width_points="1000",
            page_height_points="1000",
            bbox=cast(
                tuple[str, str, str, str],
                tuple(str(value) for value in blocks[evidence.locator.subject_ref].locator.bbox),
            ),
            rects=(
                cast(
                    tuple[str, str, str, str],
                    tuple(
                        str(value) for value in blocks[evidence.locator.subject_ref].locator.bbox
                    ),
                ),
            ),
            quote=evidence.quote_snapshot,
            quote_sha256=hashlib.sha256(evidence.quote_snapshot.encode("utf-8")).hexdigest(),
            block_id=evidence.locator.subject_ref,
            span_id=f"span-native-{field_index}-{evidence_index}",
        )
        for field_index, output in enumerate(candidate.fields)
        for evidence_index, evidence in enumerate(output.evidence)
    )
    payload = {
        "contract": "schema67-coordinate-evidence-companion.815.v1",
        "candidate_sha256": candidate.candidate_sha256,
        "provider_visible_field_ids": tuple(field.field_id for field in candidate.fields),
        "coordinate_rows": tuple(row.model_dump(mode="python") for row in rows),
        "selection_catalog_sha256": _sha("selection-catalog-native-pdf-authority"),
        "parse_manifest_sha256s": (artifact.raw_structure_sha256,),
    }
    return CoordinateEvidenceCompanion815V1.model_validate(
        {
            **payload,
            "companion_sha256": canonical_hash(
                "schema67-coordinate-evidence-companion.815.v1",
                payload,
            ),
        }
    )


def _rehashed_native_coordinate_companion(
    companion: CoordinateEvidenceCompanion815V1,
    **changes: object,
) -> CoordinateEvidenceCompanion815V1:
    payload = companion.model_dump(mode="python", exclude={"companion_sha256"})
    payload.update(changes)
    if "coordinate_rows" in changes:
        rows = cast(tuple[CoordinateEvidence815V1, ...], changes["coordinate_rows"])
        payload["coordinate_rows"] = tuple(row.model_dump(mode="python") for row in rows)
    return CoordinateEvidenceCompanion815V1.model_validate(
        {
            **payload,
            "companion_sha256": canonical_hash(
                "schema67-coordinate-evidence-companion.815.v1",
                payload,
            ),
        }
    )


def test_factory_projects_native_pdf_companion_without_changing_receipt_wire() -> None:
    from tests.test_expert_golden_admission_596_2_119 import (
        _approved_cases,
        _candidate_v2,
    )

    cases = _approved_cases()
    candidate = _candidate_v2(cases)
    artifacts, receipts, chunks = _authority_inputs_from_cases(candidate, cases)
    companion = _native_coordinate_companion(candidate, artifacts[0])

    assert (
        "coordinate_evidence_companion"
        in inspect.signature(build_schema67_candidate_evidence_authority_596_1).parameters
    )
    authority = build_schema67_candidate_evidence_authority_596_1(
        candidate=candidate,
        admitted_parse_artifacts=artifacts,
        live_source_receipts=receipts,
        chunk_authorities=chunks,
        coordinate_evidence_companion=companion,
    )

    row = companion.coordinate_rows[0]
    join = next(
        receipt
        for receipt in authority.join_receipts
        if receipt.field_id == row.field_id and receipt.locator_ref == row.block_id
    )
    assert join.source_coordinate_space == ("mineru_content_list_normalized_0_1000_top_left.v1")
    assert join.source_bbox_preimage == ("0", "0", "1", "1")
    assert (
        join.normalized_bbox.x0,
        join.normalized_bbox.y0,
        join.normalized_bbox.x1,
        join.normalized_bbox.y1,
    ) == (0, 0, 1_000, 1_000)


@pytest.mark.parametrize(
    "mutation",
    ["candidate", "duplicate", "dimensions", "source", "omitted"],
)
def test_factory_rejects_unbound_or_ambiguous_native_pdf_companion(
    mutation: str,
) -> None:
    from tests.test_expert_golden_admission_596_2_119 import (
        _approved_cases,
        _candidate_v2,
    )

    cases = _approved_cases()
    candidate = _candidate_v2(cases)
    artifacts, receipts, chunks = _authority_inputs_from_cases(candidate, cases)
    companion = _native_coordinate_companion(candidate, artifacts[0])
    row = companion.coordinate_rows[0]
    if mutation == "candidate":
        companion = _rehashed_native_coordinate_companion(
            companion,
            candidate_sha256=_sha("foreign-candidate"),
        )
    elif mutation == "duplicate":
        duplicate = row.model_copy(update={"selection_id": "selection-native-duplicate"})
        companion = _rehashed_native_coordinate_companion(
            companion,
            coordinate_rows=(row, duplicate, *companion.coordinate_rows[1:]),
        )
    elif mutation == "dimensions":
        invalid = row.model_copy(update={"page_width_points": "0"})
        companion = _rehashed_native_coordinate_companion(
            companion,
            coordinate_rows=(invalid, *companion.coordinate_rows[1:]),
        )
    elif mutation == "source":
        foreign = row.model_copy(update={"original_file_sha256": _sha("foreign-file")})
        companion = _rehashed_native_coordinate_companion(
            companion,
            coordinate_rows=(foreign, *companion.coordinate_rows[1:]),
        )
    else:
        companion = _rehashed_native_coordinate_companion(
            companion,
            coordinate_rows=companion.coordinate_rows[1:],
        )

    with pytest.raises(
        CandidateEvidenceAuthorityError,
        match="COORDINATE_AUTHORITY_INVALID",
    ):
        build_schema67_candidate_evidence_authority_596_1(
            candidate=candidate,
            admitted_parse_artifacts=artifacts,
            live_source_receipts=receipts,
            chunk_authorities=chunks,
            coordinate_evidence_companion=companion,
        )


def test_factory_provenance_is_not_stored_as_private_model_state() -> None:
    assert "_seal" not in Schema67CandidateEvidenceAuthorityV1.__private_attributes__
    assert (
        "_sealed_authority_sha256"
        not in Schema67CandidateEvidenceAuthorityV1.__private_attributes__
    )
