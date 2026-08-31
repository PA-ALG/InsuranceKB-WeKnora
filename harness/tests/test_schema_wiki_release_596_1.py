from __future__ import annotations

import copy
import gc
import hashlib
import inspect
import json
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import cast

import pytest

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    FreeformFieldOutputV1,
)
from insurance_harness.compiler.parsed_documents import (
    ParseQualityDecisionV1,
    ParseQualityMeasuredFactsV1,
)
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    EvidenceReplayCaseV1,
    Schema67CandidateV2,
)
from insurance_harness.goldenset.schema67_reviewed_golden_successor_596_1 import (
    Schema67ReviewedGoldenSuccessor5961V1,
    load_schema67_reviewed_golden_successor_596_1,
)
from insurance_harness.knowledge_compiler import (
    schema_wiki_candidate_evidence_join_596_1 as candidate_evidence_join,
)
from insurance_harness.knowledge_compiler import (
    schema_wiki_release_596_1,
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
    Schema67CitationAuthorityJoinReceiptV1,
    build_schema67_candidate_evidence_authority_596_1,
    knowledge_revision_source_id,
    live_revision_source_receipt_sha256,
    validate_schema67_candidate_evidence_authority_596_1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    KnowledgeWikiReleaseV1,
    SchemaFieldPageV1,
    SchemaRootPageV1,
    SchemaSectionPageV1,
    SchemaWikiContractError,
    schema_wiki_sha256,
    validate_knowledge_wiki_release,
)
from insurance_harness.knowledge_compiler.schema_wiki_release_596_1 import (
    SchemaWikiCompilationError,
    build_schema_field_page_596_1,
    build_schema_wiki_review_bundle_596_1,
    compile_schema_wiki_release_596_1,
)
from insurance_harness.knowledge_compiler.vertical_falsification import (
    AdmittedParseArtifactV1,
)


@dataclass(frozen=True, slots=True)
class _SelfIssuedCandidate:
    contract: str = "schema67-candidate.v2"
    product_version_id: str = "596-1"
    candidate_sha256: str = "a" * 64


_REPO = Path(__file__).parents[2]
_COMPLETE67 = (
    _REPO
    / "dataset/goldenset-drafts/schema67-reviewed-golden-successor-596-1/golden67-successor.json"
)
_OLD60 = _REPO / "dataset/goldenset/gs-s0q-596-v1/596.jsonl"
_LATEST71 = _REPO / "dataset/goldenset-drafts/esheng-zunxiang-v0/annotations.jsonl"
_GENERIC_UNKNOWN_REASON = "FIELD_UNKNOWN"
_NOT_COVERED_REASON = "NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _complete67() -> Schema67ReviewedGoldenSuccessor5961V1:
    return load_schema67_reviewed_golden_successor_596_1(
        _COMPLETE67.read_bytes(),
        old60_bytes=_OLD60.read_bytes(),
        latest71_bytes=_LATEST71.read_bytes(),
    )


def _coverage_field_ids() -> frozenset[str]:
    return frozenset(row.field_id for row in _complete67().fields if row.unknown_reason is not None)


def _compile_complete67(
    *,
    candidate: Schema67CandidateV2,
    authority: Schema67CandidateEvidenceAuthorityV1,
) -> KnowledgeWikiReleaseV1:
    return schema_wiki_release_596_1.compile_complete67_schema_wiki_release_dry_run_596_1(
        candidate=candidate,
        evidence_authority=authority,
        complete67_payload=_COMPLETE67.read_bytes(),
        old60_bytes=_OLD60.read_bytes(),
        latest71_bytes=_LATEST71.read_bytes(),
    )


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


@lru_cache(maxsize=1)
def _candidate_and_authority() -> tuple[
    Schema67CandidateV2,
    Schema67CandidateEvidenceAuthorityV1,
]:
    from tests.test_expert_golden_admission_596_2_119 import (
        _approved_cases,
        _candidate_v2,
    )

    coverage_ids = _coverage_field_ids()
    cases = tuple(
        case for case in _approved_cases() if case.field_output.field_id not in coverage_ids
    )
    candidate = _candidate_v2(cases)
    return _candidate_and_authority_from_cases(candidate, cases)


def _candidate_with_foreign_coverage_state() -> tuple[
    Schema67CandidateV2,
    Schema67CandidateEvidenceAuthorityV1,
]:
    from tests.test_expert_golden_admission_596_2_119 import (
        _approved_cases,
        _candidate_v2,
    )

    cases = _approved_cases()
    candidate = _candidate_v2(cases)
    return _candidate_and_authority_from_cases(candidate, cases)


def _candidate_and_authority_from_cases(
    candidate: Schema67CandidateV2,
    cases: tuple[EvidenceReplayCaseV1, ...],
) -> tuple[Schema67CandidateV2, Schema67CandidateEvidenceAuthorityV1]:
    artifacts, receipts, chunks = _authority_inputs_from_cases(candidate, cases)
    authority = build_schema67_candidate_evidence_authority_596_1(
        candidate=candidate,
        admitted_parse_artifacts=artifacts,
        live_source_receipts=receipts,
        chunk_authorities=chunks,
    )
    return candidate, authority


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


def _fully_rehashed_authority_join_mutation(
    authority: Schema67CandidateEvidenceAuthorityV1,
    *,
    index: int,
    field: str,
    value: object,
) -> Schema67CandidateEvidenceAuthorityV1:
    joins = list(authority.join_receipts)
    payload = joins[index].model_dump(mode="python", exclude={"receipt_sha256"})
    payload[field] = value
    if field == "page_number":
        assert type(value) is int
        payload["native_page_index"] = value - 1
    joins[index] = Schema67CitationAuthorityJoinReceiptV1.model_validate(
        {
            **payload,
            "receipt_sha256": schema_wiki_sha256(
                "schema67-citation-authority-join-receipt.v1", payload
            ),
        }
    )
    authority_payload = authority.model_dump(mode="python", exclude={"authority_sha256"})
    authority_payload["join_receipts"] = tuple(joins)
    return authority.model_copy(
        update={
            "join_receipts": tuple(joins),
            "authority_sha256": schema_wiki_sha256(
                "schema67-candidate-evidence-authority.v1", authority_payload
            ),
        }
    )


@pytest.mark.parametrize("candidate", [None, _SelfIssuedCandidate(), object()])
def test_compile_requires_concrete_freshly_replayed_schema67_candidate(
    candidate: object,
) -> None:
    with pytest.raises(SchemaWikiCompilationError) as caught:
        compile_schema_wiki_release_596_1(
            candidate=candidate,
            evidence_authority=object(),  # type: ignore[arg-type]
        )

    assert caught.value.reason_code == "SCHEMA_WIKI_COMPILATION_NOT_COMPLETE"


def test_missing_candidate_never_requests_generic_wiki_fallback() -> None:
    with pytest.raises(SchemaWikiCompilationError) as caught:
        compile_schema_wiki_release_596_1(
            candidate=None,
            evidence_authority=object(),  # type: ignore[arg-type]
        )

    assert caught.value.reason_code == "SCHEMA_WIKI_COMPILATION_NOT_COMPLETE"
    assert not hasattr(caught.value, "generic_wiki")


def test_known_field_page_binds_057_receipt_and_exact_revision_citation() -> None:
    candidate, authority = _candidate_and_authority()
    output = next(item for item in candidate.fields if item.field_id == "product_code")
    receipt = next(item for item in candidate.evidence_receipts if item.field_id == output.field_id)

    page = build_schema_field_page_596_1(
        candidate=candidate,
        output=output,
        evidence_receipt=receipt,
        evidence_authority=authority,
    )

    assert type(page) is SchemaFieldPageV1
    assert page.state == "present"
    assert page.evidence_receipt_sha256s == (receipt.receipt_hash,)
    assert len(page.citations) == len(output.evidence)
    assert all(
        citation.source_revision_id == evidence.source_revision_id
        and citation.parse_attempt_id == evidence.parse_attempt_id
        and citation.locator_ref == evidence.locator.subject_ref
        and citation.bbox.coordinate_system == "normalized_0_1e6"
        for citation, evidence in zip(page.citations, output.evidence, strict=True)
    )


def test_unknown_field_page_has_no_value_receipt_or_citation() -> None:
    candidate, authority = _candidate_and_authority()
    output = next(item for item in candidate.fields if item.field_id == "sales_end_date")
    receipt = next(item for item in candidate.evidence_receipts if item.field_id == output.field_id)

    page = build_schema_field_page_596_1(
        candidate=candidate,
        output=output,
        evidence_receipt=receipt,
        evidence_authority=authority,
    )

    assert page.state == "unknown"
    assert page.value_snapshot is None
    assert page.evidence_receipt_sha256s == ()
    assert page.citations == ()
    assert page.review_item_reason == "FIELD_UNKNOWN"
    assert page.unknown_reason == _GENERIC_UNKNOWN_REASON


def test_complete67_unverified_dry_run_compiles_exact75_without_authority_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate, authority = _candidate_and_authority()
    successor = _complete67()
    compile_dry_run = getattr(
        schema_wiki_release_596_1,
        "compile_complete67_schema_wiki_release_dry_run_596_1",
        None,
    )
    assert callable(compile_dry_run), "COMPLETE67 dry-run compiler is missing"
    assert tuple(inspect.signature(compile_dry_run).parameters) == (
        "candidate",
        "evidence_authority",
        "complete67_payload",
        "old60_bytes",
        "latest71_bytes",
    )
    authority_calls = 0

    def forbidden_receipt_authority(*args: object, **kwargs: object) -> object:
        nonlocal authority_calls
        authority_calls += 1
        raise AssertionError((args, kwargs))

    monkeypatch.setattr(
        schema_wiki_release_596_1,
        "validate_schema67_golden_quality_gate_receipt_596_1",
        forbidden_receipt_authority,
    )
    release = _compile_complete67(candidate=candidate, authority=authority)

    assert successor.golden_admission_status == "BLOCKED_RECEIPT_UNVERIFIED"
    assert authority_calls == 0
    assert len(release.members) == 75
    assert tuple(member.member_kind for member in release.members) == (
        "root",
        *("section" for _ in range(7)),
        *("field" for _ in range(67)),
    )
    assert all(
        member.member_ref.startswith(("root:", "section:", "field:")) for member in release.members
    )
    fields = {item.field_id: item for item in candidate.fields}
    pages = {
        member.field_id: member.payload
        for member in release.members
        if member.member_kind == "field"
    }
    coverage_ids = tuple(row.field_id for row in successor.fields if row.unknown_reason is not None)
    assert len(coverage_ids) == 16
    assert all(fields[field_id].state == "unknown" for field_id in coverage_ids)
    for row in successor.fields:
        page = pages[row.field_id]
        assert isinstance(page, SchemaFieldPageV1)
        if row.field_id in coverage_ids:
            assert page.state == "unknown"
            assert page.value_snapshot is None
            assert page.citations == ()
            assert page.evidence_receipt_sha256s == ()
            assert page.review_item_reason == "FIELD_UNKNOWN"
            assert page.unknown_reason == _NOT_COVERED_REASON
        else:
            candidate_field = fields[row.field_id]
            assert page.state == candidate_field.state
            assert page.value_snapshot == candidate_field.value_snapshot
            assert len(page.citations) == len(candidate_field.evidence)
            if candidate_field.state == "unknown":
                assert page.unknown_reason == _GENERIC_UNKNOWN_REASON


def test_complete67_dry_run_rejects_known_coverage_field_without_mutating_candidate() -> None:
    candidate, authority = _candidate_with_foreign_coverage_state()
    coverage_ids = _coverage_field_ids()
    original = candidate.model_dump(mode="json")
    assert any(
        field.state != "unknown" for field in candidate.fields if field.field_id in coverage_ids
    )

    with pytest.raises(SchemaWikiCompilationError) as caught:
        _compile_complete67(candidate=candidate, authority=authority)

    assert caught.value.reason_code == "COMPLETE67_CANDIDATE_CUSTODY_INVALID"
    assert candidate.model_dump(mode="json") == original


def test_complete67_dry_run_rejects_unknown_reason_drift_before_compilation() -> None:
    candidate, authority = _candidate_and_authority()
    compile_dry_run = getattr(
        schema_wiki_release_596_1,
        "compile_complete67_schema_wiki_release_dry_run_596_1",
        None,
    )
    assert callable(compile_dry_run), "COMPLETE67 dry-run compiler is missing"
    payload = json.loads(_COMPLETE67.read_bytes())
    row = next(item for item in payload["fields"] if item.get("unknown_reason") is not None)
    row["unknown_reason"] = None

    with pytest.raises(SchemaWikiCompilationError) as caught:
        compile_dry_run(
            candidate=candidate,
            evidence_authority=authority,
            complete67_payload=json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            old60_bytes=_OLD60.read_bytes(),
            latest71_bytes=_LATEST71.read_bytes(),
        )

    assert caught.value.reason_code == "COMPLETE67_AUTHORITY_INVALID"


@pytest.mark.parametrize(
    ("field", "foreign"),
    [
        ("evidence_parse_attempt_id", "foreign-attempt"),
        ("chunk_id", "foreign-chunk"),
        ("page_number", 27),
        ("locator_ref", "foreign-block"),
    ],
)
def test_known_field_page_rejects_foreign_citation_custody(field: str, foreign: object) -> None:
    candidate, authority = _candidate_and_authority()
    output = next(item for item in candidate.fields if item.field_id == "product_code")
    receipt = next(item for item in candidate.evidence_receipts if item.field_id == output.field_id)
    join_index = next(
        index
        for index, item in enumerate(authority.join_receipts)
        if item.field_id == output.field_id
    )
    forged = _fully_rehashed_authority_join_mutation(
        authority,
        index=join_index,
        field=field,
        value=foreign,
    )

    with pytest.raises(SchemaWikiCompilationError):
        build_schema_field_page_596_1(
            candidate=candidate,
            output=output,
            evidence_receipt=receipt,
            evidence_authority=forged,
        )


def test_full_rehash_and_privateattr_reseal_cannot_forge_companion() -> None:
    candidate, authority = _candidate_and_authority()
    forged = _fully_rehashed_authority_join_mutation(
        authority,
        index=0,
        field="chunk_id",
        value="foreign-chunk",
    )
    object.__setattr__(forged, "_seal", getattr(authority, "_seal", object()))
    object.__setattr__(
        forged,
        "_sealed_authority_sha256",
        forged.authority_sha256,
    )

    with pytest.raises(SchemaWikiCompilationError) as caught:
        compile_schema_wiki_release_596_1(
            candidate=candidate,
            evidence_authority=forged,
        )

    assert caught.value.reason_code == "CITATION_AUTHORITY_INVALID"


@pytest.mark.parametrize(
    "clone_kind",
    ["model_copy", "deepcopy", "reparse", "model_construct"],
)
def test_only_exact_factory_instance_is_compiler_authority(clone_kind: str) -> None:
    candidate, authority = _candidate_and_authority()
    payload = authority.model_dump(mode="python")
    if clone_kind == "model_copy":
        clone = authority.model_copy()
    elif clone_kind == "deepcopy":
        clone = copy.deepcopy(authority)
    elif clone_kind == "reparse":
        clone = Schema67CandidateEvidenceAuthorityV1.model_validate(payload)
    else:
        clone = Schema67CandidateEvidenceAuthorityV1.model_construct(**payload)

    with pytest.raises(SchemaWikiCompilationError) as caught:
        compile_schema_wiki_release_596_1(
            candidate=candidate,
            evidence_authority=clone,
        )

    assert caught.value.reason_code == "CITATION_AUTHORITY_INVALID"


def test_registered_instance_rejects_nested_mutation_and_full_rehash() -> None:
    _candidate_and_authority.cache_clear()
    candidate, authority = _candidate_and_authority()
    joins = list(authority.join_receipts)
    join_payload = joins[0].model_dump(mode="python", exclude={"receipt_sha256"})
    join_payload["chunk_id"] = "foreign-chunk"
    joins[0] = Schema67CitationAuthorityJoinReceiptV1.model_validate(
        {
            **join_payload,
            "receipt_sha256": schema_wiki_sha256(
                "schema67-citation-authority-join-receipt.v1",
                join_payload,
            ),
        }
    )
    authority_payload = authority.model_dump(
        mode="python",
        exclude={"authority_sha256"},
    )
    authority_payload["join_receipts"] = tuple(joins)
    object.__setattr__(authority, "join_receipts", tuple(joins))
    object.__setattr__(
        authority,
        "authority_sha256",
        schema_wiki_sha256(
            "schema67-candidate-evidence-authority.v1",
            authority_payload,
        ),
    )

    try:
        with pytest.raises(SchemaWikiCompilationError) as caught:
            compile_schema_wiki_release_596_1(
                candidate=candidate,
                evidence_authority=authority,
            )
        assert caught.value.reason_code == "CITATION_AUTHORITY_INVALID"
    finally:
        _candidate_and_authority.cache_clear()


def test_factory_provenance_is_not_stored_as_private_model_state() -> None:
    assert "_seal" not in Schema67CandidateEvidenceAuthorityV1.__private_attributes__
    assert (
        "_sealed_authority_sha256"
        not in Schema67CandidateEvidenceAuthorityV1.__private_attributes__
    )


def test_factory_registry_entry_is_removed_when_authority_is_collected() -> None:
    _candidate_and_authority.cache_clear()
    _, authority = _candidate_and_authority()
    identity = id(authority)
    authority_ref = weakref.ref(authority)
    assert identity in candidate_evidence_join._FACTORY_AUTHORITY_REGISTRY

    _candidate_and_authority.cache_clear()
    del authority
    gc.collect()

    assert authority_ref() is None
    assert identity not in candidate_evidence_join._FACTORY_AUTHORITY_REGISTRY


def test_factory_registry_validation_is_thread_safe() -> None:
    candidate, authority = _candidate_and_authority()

    def replay(_: int) -> bool:
        return (
            validate_schema67_candidate_evidence_authority_596_1(
                candidate=candidate,
                authority=authority,
            )
            is authority
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        assert all(executor.map(replay, range(8)))


def test_unknown_field_rejects_forged_evidence_and_cannot_express_a_citation() -> None:
    candidate, authority = _candidate_and_authority()
    output = next(item for item in candidate.fields if item.field_id == "sales_end_date")
    receipt = next(item for item in candidate.evidence_receipts if item.field_id == output.field_id)
    known_output = next(item for item in candidate.fields if item.field_id == "product_code")
    known_receipt = next(
        item for item in candidate.evidence_receipts if item.field_id == known_output.field_id
    )

    with pytest.raises(SchemaWikiCompilationError):
        build_schema_field_page_596_1(
            candidate=candidate,
            output=output,
            evidence_receipt=known_receipt,
            evidence_authority=authority,
        )
    forged_unknown = FreeformFieldOutputV1.model_construct(
        product_version_id=output.product_version_id,
        field_id=output.field_id,
        state="unknown",
        value_snapshot=None,
        evidence=known_output.evidence,
    )
    with pytest.raises(SchemaWikiCompilationError):
        build_schema_field_page_596_1(
            candidate=candidate,
            output=forged_unknown,
            evidence_receipt=receipt,
            evidence_authority=authority,
        )


def test_provider_zero_candidate_cannot_build_a_review_bundle() -> None:
    candidate, authority = _candidate_and_authority()
    release = compile_schema_wiki_release_596_1(
        candidate=candidate,
        evidence_authority=authority,
    )

    with pytest.raises(SchemaWikiCompilationError) as caught:
        build_schema_wiki_review_bundle_596_1(
            candidate=candidate,
            evidence_authority=authority,
            release=release,
            quality_gate_receipt=object(),
        )

    assert caught.value.reason_code == "QUALITY_GATE_RECEIPT_INVALID"


def test_lane_b_exposes_no_caller_selected_review_approval_handoff() -> None:
    assert not hasattr(
        schema_wiki_release_596_1,
        "require_manifest_bound_review_596_1",
    )
    assert "require_manifest_bound_review_596_1" not in schema_wiki_release_596_1.__all__


def test_real_factory_compiles_exact75_and_frozen_vector_remains_reopenable() -> None:
    candidate, authority = _candidate_and_authority()
    release = _compile_complete67(candidate=candidate, authority=authority)

    assert type(release) is KnowledgeWikiReleaseV1
    assert release.candidate_sha256 == candidate.candidate_sha256
    assert tuple(
        (
            row.source_role,
            row.live_revision_source_receipt.page_count,
            row.live_revision_source_receipt.weknora_parse_attempt,
        )
        for row in authority.source_authorities
    ) == (("terms", 39, 2), ("brochure", 27, 1), ("rate_table", 2, 1))
    assert len(authority.join_receipts) == sum(len(field.evidence) for field in candidate.fields)
    assert authority.join_receipts
    assert len(release.members) == 75
    assert tuple(item.member_kind for item in release.members[:8]) == (
        "root",
        *("section" for _ in range(7)),
    )
    assert tuple(item.field_id for item in release.members[8:]) == (candidate.ordered_field_ids)
    vector_path = (
        Path(__file__).parents[2]
        / "internal/application/service/testdata/schema_wiki_release_596_1_vector.json"
    )
    frozen = json.loads(vector_path.read_text(encoding="utf-8"))
    frozen_authority = Schema67CandidateEvidenceAuthorityV1.model_validate(
        frozen["candidate_evidence_authority"]
    )
    frozen_release = KnowledgeWikiReleaseV1.model_validate(frozen["release"])
    assert validate_knowledge_wiki_release(frozen_release, frozen_release.schema_pack)
    assert len(frozen_release.members) == len(release.members) == 75
    assert len(frozen_authority.source_authorities) == len(authority.source_authorities) == 3
    assert frozen_release.contract == release.contract
    assert frozen_authority.contract == authority.contract


def _real_candidate_and_release() -> tuple[Schema67CandidateV2, KnowledgeWikiReleaseV1]:
    candidate, authority = _candidate_and_authority()
    release = _compile_complete67(candidate=candidate, authority=authority)
    return candidate, release


def _rehash_member_payload(member: dict[str, object]) -> None:
    payload = member["payload"]
    assert isinstance(payload, dict)
    payload_contract = payload["contract"]
    assert isinstance(payload_contract, str)
    self_hash_field = {
        "schema-root-page.v1": "root_page_sha256",
        "schema-section-page.v1": "section_page_sha256",
        "schema-field-page.v1": "field_page_sha256",
    }.get(payload_contract)
    if self_hash_field is not None:
        payload[self_hash_field] = schema_wiki_sha256(
            payload_contract,
            {key: value for key, value in payload.items() if key != self_hash_field},
        )
        member["payload_sha256"] = payload[self_hash_field]
    else:
        member["payload_sha256"] = schema_wiki_sha256(payload_contract, payload)
    member["member_digest"] = schema_wiki_sha256(
        "schema-wiki-member.v1",
        {key: value for key, value in member.items() if key != "member_digest"},
    )


def _rehash_release_payload(release: dict[str, object]) -> None:
    members = release["members"]
    bindings = release["citation_bindings"]
    assert isinstance(members, list)
    assert isinstance(bindings, list)
    release["manifest_digest"] = schema_wiki_sha256(
        "schema-wiki-manifest.v1",
        {"members": members, "citation_bindings": bindings},
    )
    release["release_sha256"] = schema_wiki_sha256(
        "knowledge-wiki-release.v1",
        {key: value for key, value in release.items() if key != "release_sha256"},
    )


def test_compiler_carries_exact75_typed_canonical_member_payloads() -> None:
    candidate, release = _real_candidate_and_release()
    _, authority = _candidate_and_authority()
    rows = release.model_dump(mode="json")["members"]

    assert len(rows) == 75
    assert all("payload" in row for row in rows), "descriptor-only members are forbidden"

    assert isinstance(release.members[0].payload, SchemaRootPageV1)
    root = rows[0]["payload"]
    assert root == {
        "contract": "schema-root-page.v1",
        "domain_id": release.domain.domain_id,
        "domain_sha256": release.domain.domain_sha256,
        "schema_pack_id": release.schema_pack.schema_pack_id,
        "schema_version": release.schema_pack.schema_version,
        "schema_pack_sha256": release.schema_pack.schema_pack_sha256,
        "entity_id": release.entity.entity_id,
        "entity_version_id": release.entity_version.version_id,
        "product_version_id": release.entity_version.product_version_id,
        "taxonomy_version": release.taxonomy.taxonomy_version,
        "taxonomy_sha256": release.taxonomy.taxonomy_sha256,
        "product_display_name": "平安e生保（尊享版）医疗保险",
        "ordered_section_ids": [section.section_id for section in release.schema_pack.sections],
        "root_page_sha256": rows[0]["payload_sha256"],
    }

    assert all(isinstance(member.payload, SchemaSectionPageV1) for member in release.members[1:8])
    expected_section_payloads = [
        {
            "contract": "schema-section-page.v1",
            "domain_id": release.domain.domain_id,
            "domain_sha256": release.domain.domain_sha256,
            "schema_pack_id": release.schema_pack.schema_pack_id,
            "schema_version": release.schema_pack.schema_version,
            "schema_pack_sha256": release.schema_pack.schema_pack_sha256,
            "entity_id": release.entity.entity_id,
            "entity_version_id": release.entity_version.version_id,
            "product_version_id": release.entity_version.product_version_id,
            "taxonomy_version": release.taxonomy.taxonomy_version,
            "taxonomy_sha256": release.taxonomy.taxonomy_sha256,
            "section_id": section.section_id,
            "display_name": section.display_name,
            "ordered_field_ids": list(section.ordered_field_ids),
            "section_page_sha256": row["payload_sha256"],
        }
        for section, row in zip(release.schema_pack.sections, rows[1:8], strict=True)
    ]
    section_rows = rows[1:8]
    assert [row["payload"] for row in section_rows] == expected_section_payloads

    coverage_ids = _coverage_field_ids()
    expected_pages = []
    for output, receipt in zip(
        candidate.fields,
        candidate.evidence_receipts,
        strict=True,
    ):
        if output.field_id in coverage_ids:
            payload = {
                "contract": "schema-field-page.v1",
                "field_id": output.field_id,
                "state": "unknown",
                "value_snapshot": None,
                "citations": (),
                "evidence_receipt_sha256s": (),
                "review_item_reason": "FIELD_UNKNOWN",
                "unknown_reason": _NOT_COVERED_REASON,
            }
            expected_pages.append(
                SchemaFieldPageV1.model_validate(
                    {
                        **payload,
                        "field_page_sha256": schema_wiki_sha256(
                            "schema-field-page.v1",
                            payload,
                        ),
                    }
                ).model_dump(mode="json")
            )
        else:
            expected_pages.append(
                build_schema_field_page_596_1(
                    candidate=candidate,
                    output=output,
                    evidence_receipt=receipt,
                    evidence_authority=authority,
                ).model_dump(mode="json")
            )
    field_payloads = [row["payload"] for row in rows[8:]]
    assert field_payloads == expected_pages


def test_descriptor_only_release_is_rejected_even_when_hashes_are_self_consistent() -> None:
    _, release = _real_candidate_and_release()
    descriptor_only = release.model_dump(mode="json")
    for member in descriptor_only["members"]:
        member.pop("payload", None)

    with pytest.raises((SchemaWikiContractError, ValueError)):
        validate_knowledge_wiki_release(
            KnowledgeWikiReleaseV1.model_validate(descriptor_only),
            release.schema_pack,
        )


def test_generic_payload_is_rejected_after_fully_recomputed_release_hashes() -> None:
    _, release = _real_candidate_and_release()
    forged = release.model_dump(mode="json")
    root = forged["members"][0]
    root["payload"] = {
        "contract": "generic-wiki-page.v1",
        "title": "self-issued generic payload",
    }
    _rehash_member_payload(root)
    _rehash_release_payload(forged)

    with pytest.raises((SchemaWikiContractError, ValueError)):
        validate_knowledge_wiki_release(
            KnowledgeWikiReleaseV1.model_validate(forged),
            release.schema_pack,
        )


def test_payload_substitution_is_rejected_after_fully_recomputed_release_hashes() -> None:
    _, release = _real_candidate_and_release()
    forged = release.model_dump(mode="json")
    first, second = forged["members"][1:3]
    assert "payload" in first and "payload" in second, (
        "typed member payloads are required before substitution can be evaluated"
    )
    first["payload"], second["payload"] = second["payload"], first["payload"]
    _rehash_member_payload(first)
    _rehash_member_payload(second)
    _rehash_release_payload(forged)

    with pytest.raises((SchemaWikiContractError, ValueError)):
        validate_knowledge_wiki_release(
            KnowledgeWikiReleaseV1.model_validate(forged),
            release.schema_pack,
        )


def test_medical_root_display_name_is_code_owned_after_full_rehash() -> None:
    candidate, release = _real_candidate_and_release()
    forged = release.model_dump(mode="json")
    root = forged["members"][0]
    root_payload = root["payload"]
    assert isinstance(root_payload, dict)
    root_payload["product_display_name"] = "caller-selected product name"
    _rehash_member_payload(root)
    _rehash_release_payload(forged)
    generic_valid = KnowledgeWikiReleaseV1.model_validate(forged)
    assert validate_knowledge_wiki_release(generic_valid, release.schema_pack)

    with pytest.raises(SchemaWikiCompilationError):
        build_schema_wiki_review_bundle_596_1(
            candidate=candidate,
            evidence_authority=object(),  # type: ignore[arg-type]
            release=generic_valid,
            quality_gate_receipt=object(),
        )


def test_foreign_a1_release_cannot_receive_596_1_review_bundle() -> None:
    candidate, _ = _real_candidate_and_release()
    vector_path = (
        Path(__file__).parents[2]
        / "internal/application/service/testdata/schema_wiki_contract_vector.json"
    )
    vector = json.loads(vector_path.read_text(encoding="utf-8"))
    foreign = KnowledgeWikiReleaseV1.model_validate(vector["release"])
    assert validate_knowledge_wiki_release(foreign, foreign.schema_pack)
    assert foreign.entity_version.product_version_id == "product-v1"
    assert len(foreign.members) == 6

    with pytest.raises(SchemaWikiCompilationError):
        build_schema_wiki_review_bundle_596_1(
            candidate=candidate,
            evidence_authority=object(),  # type: ignore[arg-type]
            release=foreign,
            quality_gate_receipt=object(),
        )
