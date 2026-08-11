from __future__ import annotations

import copy
import gc
import hashlib
import json
import weakref
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import pytest

from insurance_harness.compiler.evidence_verifier import (
    FreeformFieldOutputV1,
)
from insurance_harness.compiler.parsed_documents import (
    ParseQualityDecisionV1,
    ParseQualityMeasuredFactsV1,
)
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    Schema67CandidateV2,
)
from insurance_harness.knowledge_compiler import (
    schema_wiki_candidate_evidence_join_596_1 as candidate_evidence_join,
)
from insurance_harness.knowledge_compiler import (
    schema_wiki_release_596_1,
)
from insurance_harness.knowledge_compiler.schema_wiki_candidate_evidence_join_596_1 import (
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
    SchemaWikiReviewBundleV1,
    schema_wiki_sha256,
    validate_knowledge_wiki_release,
    validate_schema_wiki_review_bundle,
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


@lru_cache(maxsize=1)
def _candidate_and_authority() -> tuple[
    Schema67CandidateV2,
    Schema67CandidateEvidenceAuthorityV1,
]:
    from tests.test_expert_golden_admission_596_2_119 import (
        _approved_cases,
        _candidate_v2,
    )

    cases = _approved_cases()
    candidate = _candidate_v2(cases)
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
    authority = build_schema67_candidate_evidence_authority_596_1(
        candidate=candidate,
        admitted_parse_artifacts=(artifact,),
        live_source_receipts=receipts,
        chunk_authorities=chunks,
    )
    return candidate, authority


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
    authority_payload = authority.model_dump(
        mode="python", exclude={"authority_sha256"}
    )
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
    receipt = next(
        item for item in candidate.evidence_receipts if item.field_id == output.field_id
    )

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
    receipt = next(
        item for item in candidate.evidence_receipts if item.field_id == output.field_id
    )

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


@pytest.mark.parametrize(
    ("field", "foreign"),
    [
        ("evidence_parse_attempt_id", "foreign-attempt"),
        ("chunk_id", "foreign-chunk"),
        ("page_number", 27),
        ("locator_ref", "foreign-block"),
    ],
)
def test_known_field_page_rejects_foreign_citation_custody(
    field: str, foreign: object
) -> None:
    candidate, authority = _candidate_and_authority()
    output = next(item for item in candidate.fields if item.field_id == "product_code")
    receipt = next(
        item for item in candidate.evidence_receipts if item.field_id == output.field_id
    )
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
    receipt = next(
        item for item in candidate.evidence_receipts if item.field_id == output.field_id
    )
    known_output = next(
        item for item in candidate.fields if item.field_id == "product_code"
    )
    known_receipt = next(
        item
        for item in candidate.evidence_receipts
        if item.field_id == known_output.field_id
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


def test_review_bundle_binds_manifest_members_for_existing_service_review() -> None:
    candidate, release = _real_candidate_and_release()

    bundle = build_schema_wiki_review_bundle_596_1(
        candidate=candidate,
        release=release,
    )

    assert type(bundle) is SchemaWikiReviewBundleV1
    assert bundle.manifest_digest == release.manifest_digest
    assert bundle.release_sha256 == release.release_sha256
    assert validate_schema_wiki_review_bundle(bundle, release) == bundle


def test_lane_b_exposes_no_caller_selected_review_approval_handoff() -> None:
    assert not hasattr(
        schema_wiki_release_596_1,
        "require_manifest_bound_review_596_1",
    )
    assert "require_manifest_bound_review_596_1" not in schema_wiki_release_596_1.__all__


def test_review_bundle_rejects_manifest_drift_before_authority_handoff() -> None:
    candidate, release = _real_candidate_and_release()
    bundle = build_schema_wiki_review_bundle_596_1(
        candidate=candidate,
        release=release,
    )
    forged_release = release.model_copy()
    object.__setattr__(forged_release, "manifest_digest", "f" * 64)

    with pytest.raises(SchemaWikiContractError):
        validate_schema_wiki_review_bundle(bundle, forged_release)


def test_real_factory_sealed_candidate_compiles_exact75_and_matches_vector() -> None:
    candidate, authority = _candidate_and_authority()
    release = compile_schema_wiki_release_596_1(
        candidate=candidate,
        evidence_authority=authority,
    )

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
    assert len(authority.join_receipts) == sum(
        len(field.evidence) for field in candidate.fields
    ) == 111
    assert len(release.members) == 75
    assert tuple(item.member_kind for item in release.members[:8]) == (
        "root",
        *("section" for _ in range(7)),
    )
    assert tuple(item.field_id for item in release.members[8:]) == (
        candidate.ordered_field_ids
    )
    assert validate_schema_wiki_review_bundle(
        build_schema_wiki_review_bundle_596_1(
            candidate=candidate,
            release=release,
        ),
        release,
    )

    vector_path = (
        Path(__file__).parents[2]
        / "internal/application/service/testdata/schema_wiki_release_596_1_vector.json"
    )
    assert json.loads(vector_path.read_text(encoding="utf-8")) == {
        "candidate_evidence_authority": authority.model_dump(mode="json"),
        "release": release.model_dump(mode="json"),
    }


def _real_candidate_and_release() -> tuple[
    Schema67CandidateV2, KnowledgeWikiReleaseV1
]:
    candidate, authority = _candidate_and_authority()
    release = compile_schema_wiki_release_596_1(
        candidate=candidate,
        evidence_authority=authority,
    )
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
        "ordered_section_ids": [
            section.section_id for section in release.schema_pack.sections
        ],
        "root_page_sha256": rows[0]["payload_sha256"],
    }

    assert all(
        isinstance(member.payload, SchemaSectionPageV1)
        for member in release.members[1:8]
    )
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
        for section, row in zip(
            release.schema_pack.sections, rows[1:8], strict=True
        )
    ]
    section_rows = rows[1:8]
    assert [row["payload"] for row in section_rows] == expected_section_payloads

    expected_pages = [
        build_schema_field_page_596_1(
            candidate=candidate,
            output=output,
            evidence_receipt=receipt,
            evidence_authority=authority,
        ).model_dump(mode="json")
        for output, receipt in zip(
            candidate.fields,
            candidate.evidence_receipts,
            strict=True,
        )
    ]
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
            release=generic_valid,
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
            release=foreign,
        )
