from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import BaseModel

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    EvidenceLocatorSnapshotV1,
    FreeformDocumentBindingV1,
    FreeformEvidenceBindingReceiptV1,
    FreeformEvidenceV1,
    FreeformFieldOutputV1,
)
from insurance_harness.goldenset.expert_golden_admission_596_2 import (
    Schema67CandidateV2,
)
from insurance_harness.knowledge_compiler import schema_wiki_release_596_1
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    CitationBBoxV1,
    CitationTargetV1,
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


@dataclass(frozen=True, slots=True)
class _SelfIssuedCandidate:
    contract: str = "schema67-candidate.v2"
    product_version_id: str = "596-1"
    candidate_sha256: str = "a" * 64


class _FailIfCalledCitationAuthority:
    def resolve(
        self,
        *,
        output: FreeformFieldOutputV1,
        evidence_receipt: FreeformEvidenceBindingReceiptV1,
        entity_version_id: str,
    ) -> tuple[CitationTargetV1, ...]:
        del output, evidence_receipt, entity_version_id
        raise AssertionError("citation authority must not run for an unsealed Candidate")


@dataclass(frozen=True, slots=True)
class _ExactCitationAuthority:
    expected: tuple[CitationTargetV1, ...]
    returned: tuple[CitationTargetV1, ...] | None = None

    def resolve(
        self,
        *,
        output: FreeformFieldOutputV1,
        evidence_receipt: FreeformEvidenceBindingReceiptV1,
        entity_version_id: str,
    ) -> tuple[CitationTargetV1, ...]:
        assert output.field_id == evidence_receipt.field_id
        assert entity_version_id == "ping-an-e-sheng-bao@596-1"
        resolved = self.expected if self.returned is None else self.returned
        if resolved != self.expected:
            raise ValueError("trusted revision join rejected foreign citation")
        return resolved


class _SyntheticTrustedCitationAuthority:
    _ROLE_BY_SOURCE = {
        "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc": (
            "terms",
            "f987fc16-222a-4246-8ca0-22c1a81dd6d9",
        ),
        "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279": (
            "brochure",
            "1265a343-c408-4620-8eed-c4f6a2adadc2",
        ),
        "7b35fa3b0e1820860dafc2fec9858949d387f2aab19006d3d3e02b92e0bb75fb": (
            "rate_table",
            "32402c40-6131-4049-8080-cc5b68188cd3",
        ),
    }
    def resolve(
        self,
        *,
        output: FreeformFieldOutputV1,
        evidence_receipt: FreeformEvidenceBindingReceiptV1,
        entity_version_id: str,
    ) -> tuple[CitationTargetV1, ...]:
        assert output.evidence == evidence_receipt.evidence
        assert entity_version_id == "ping-an-e-sheng-bao@596-1"
        citations: list[CitationTargetV1] = []
        for evidence in output.evidence:
            role, knowledge_id = self._ROLE_BY_SOURCE[evidence.source_sha256]
            identity = _sha(
                "|".join(
                    (
                        output.field_id,
                        role,
                        evidence.source_revision_id,
                        evidence.locator.subject_ref,
                        evidence.quote_snapshot_sha256,
                    )
                )
            )
            payload = {
                "contract": "citation-target.v1",
                "citation_id": f"citation-{identity[:24]}",
                "source_role": role,
                "space_id": "space-596-1",
                "entity_version_id": entity_version_id,
                "knowledge_id": knowledge_id,
                "chunk_id": f"chunk-{identity[24:48]}",
                "source_revision_id": evidence.source_revision_id,
                "parse_attempt_id": evidence.parse_attempt_id,
                "parsed_document_sha256": evidence.parsed_document_hash,
                "parse_manifest_sha256": evidence.parse_manifest_hash,
                "page_number": evidence.page_number,
                "locator_ref": evidence.locator.subject_ref,
                "bbox": CitationBBoxV1(
                    coordinate_system="pdf_points",
                    page_width=600,
                    page_height=800,
                    x0=100,
                    y0=120,
                    x1=360,
                    y1=180,
                ),
                "quote_snapshot": evidence.quote_snapshot,
                "quote_sha256": schema_wiki_sha256(
                    "schema-wiki-text.v1", {"text": evidence.quote_snapshot}
                ),
                "content_snapshot_sha256": (
                    evidence.locator.content_snapshot_sha256
                ),
                "logical_member_ref": f"field:{output.field_id}",
            }
            citations.append(
                CitationTargetV1.model_validate(
                    {
                        **payload,
                        "citation_sha256": schema_wiki_sha256(
                            "citation-target.v1", payload
                        ),
                    }
                )
            )
        return tuple(citations)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sealed[ModelT: BaseModel](
    model: type[ModelT], object_type: str, hash_field: str, **payload: object
) -> ModelT:
    return model.model_validate(
        {
            **payload,
            hash_field: schema_wiki_sha256(object_type, payload),
        }
    )


def _receipt_payload(
    *,
    output: FreeformFieldOutputV1,
    documents: tuple[FreeformDocumentBindingV1, ...],
) -> dict[str, object]:
    return {
        "contract": "freeform-arm-evidence-binding-receipt.v1",
        "product_version_id": output.product_version_id,
        "field_id": output.field_id,
        "state": output.state,
        "value_snapshot": output.value_snapshot,
        "documents": tuple(item.model_dump(mode="python") for item in documents),
        "evidence": tuple(item.model_dump(mode="python") for item in output.evidence),
    }


def _unknown() -> tuple[FreeformFieldOutputV1, FreeformEvidenceBindingReceiptV1]:
    output = FreeformFieldOutputV1(
        product_version_id="596-1",
        field_id="sales_end_date",
        state="unknown",
        value_snapshot=None,
        evidence=(),
    )
    payload = _receipt_payload(output=output, documents=())
    return output, FreeformEvidenceBindingReceiptV1.model_validate(
        {
            **payload,
            "receipt_hash": canonical_hash(
                "freeform-arm-evidence-binding-receipt.v1", payload
            ),
        }
    )


def _known() -> tuple[
    FreeformFieldOutputV1,
    FreeformEvidenceBindingReceiptV1,
    CitationTargetV1,
]:
    field_id = "product_code"
    quote = "条款明确载明产品代码。"
    content = f"前文 {quote} 后文"
    source_sha256 = "8" * 64
    revision_id = "terms-revision-attempt-2"
    attempt_id = "terms-attempt-2"
    document_sha256 = "4" * 64
    manifest_sha256 = "5" * 64
    evidence = FreeformEvidenceV1(
        field_id=field_id,
        source_sha256=source_sha256,
        source_revision_id=revision_id,
        parse_attempt_id=attempt_id,
        parsed_document_hash=document_sha256,
        parse_manifest_hash=manifest_sha256,
        page_number=12,
        block_id="block-12-3",
        locator=EvidenceLocatorSnapshotV1(
            subject_type="block",
            subject_ref="block-12-3",
            page_number=12,
            parent_refs=("page-12",),
            content_snapshot=content,
            content_snapshot_sha256=_sha(content),
        ),
        quote_snapshot=quote,
        quote_snapshot_sha256=_sha(quote),
    )
    output = FreeformFieldOutputV1(
        product_version_id="596-1",
        field_id=field_id,
        state="present",
        value_snapshot="P000001",
        evidence=(evidence,),
    )
    document = FreeformDocumentBindingV1(
        source_id="terms-source",
        source_revision_id=revision_id,
        source_sha256=source_sha256,
        parse_attempt_id=attempt_id,
        parsed_document_hash=document_sha256,
        parse_manifest_hash=manifest_sha256,
    )
    receipt_payload = _receipt_payload(output=output, documents=(document,))
    receipt = FreeformEvidenceBindingReceiptV1.model_validate(
        {
            **receipt_payload,
            "receipt_hash": canonical_hash(
                "freeform-arm-evidence-binding-receipt.v1", receipt_payload
            ),
        }
    )
    bbox = CitationBBoxV1(
        coordinate_system="pdf_points",
        page_width=600,
        page_height=800,
        x0=100,
        y0=120,
        x1=360,
        y1=180,
    )
    citation_payload = {
        "contract": "citation-target.v1",
        "citation_id": "citation-product-code-terms",
        "source_role": "terms",
        "space_id": "space-596-1",
        "entity_version_id": "ping-an-e-sheng-bao@596-1",
        "knowledge_id": "f987fc16-222a-4246-8ca0-22c1a81dd6d9",
        "chunk_id": "chunk-terms-12-3",
        "source_revision_id": revision_id,
        "parse_attempt_id": attempt_id,
        "parsed_document_sha256": document_sha256,
        "parse_manifest_sha256": manifest_sha256,
        "page_number": 12,
        "locator_ref": "block-12-3",
        "bbox": bbox,
        "quote_snapshot": quote,
        "quote_sha256": schema_wiki_sha256(
            "schema-wiki-text.v1", {"text": quote}
        ),
        "content_snapshot_sha256": _sha(content),
        "logical_member_ref": f"field:{field_id}",
    }
    citation = CitationTargetV1.model_validate(
        {
            **citation_payload,
            "citation_sha256": schema_wiki_sha256(
                "citation-target.v1", citation_payload
            ),
        }
    )
    return output, receipt, citation


@pytest.mark.parametrize("candidate", [None, _SelfIssuedCandidate(), object()])
def test_compile_requires_concrete_freshly_replayed_schema67_candidate(
    candidate: object,
) -> None:
    with pytest.raises(SchemaWikiCompilationError) as caught:
        compile_schema_wiki_release_596_1(
            candidate=candidate,
            citation_authority=_FailIfCalledCitationAuthority(),
        )

    assert caught.value.reason_code == "SCHEMA_WIKI_COMPILATION_NOT_COMPLETE"


def test_missing_candidate_never_requests_generic_wiki_fallback() -> None:
    authority = _FailIfCalledCitationAuthority()

    with pytest.raises(SchemaWikiCompilationError) as caught:
        compile_schema_wiki_release_596_1(
            candidate=None,
            citation_authority=authority,
        )

    assert caught.value.reason_code == "SCHEMA_WIKI_COMPILATION_NOT_COMPLETE"
    assert not hasattr(caught.value, "generic_wiki")


def test_known_field_page_binds_057_receipt_and_exact_revision_citation() -> None:
    output, receipt, citation = _known()

    page = build_schema_field_page_596_1(
        output=output,
        evidence_receipt=receipt,
        citation_authority=_ExactCitationAuthority((citation,)),
    )

    assert type(page) is SchemaFieldPageV1
    assert page.state == "present"
    assert page.evidence_receipt_sha256s == (receipt.receipt_hash,)
    assert page.citations == (citation,)


def test_unknown_field_page_has_no_value_receipt_or_citation() -> None:
    output, receipt = _unknown()

    page = build_schema_field_page_596_1(
        output=output,
        evidence_receipt=receipt,
        citation_authority=_FailIfCalledCitationAuthority(),
    )

    assert page.state == "unknown"
    assert page.value_snapshot is None
    assert page.evidence_receipt_sha256s == ()
    assert page.citations == ()
    assert page.review_item_reason == "FIELD_UNKNOWN"


@pytest.mark.parametrize(
    ("field", "foreign"),
    [
        ("source_revision_id", "foreign-revision"),
        ("parse_attempt_id", "foreign-attempt"),
        ("chunk_id", "foreign-chunk"),
        ("page_number", 27),
        ("locator_ref", "foreign-block"),
    ],
)
def test_known_field_page_rejects_foreign_citation_custody(
    field: str, foreign: object
) -> None:
    output, receipt, citation = _known()
    payload = citation.model_dump(mode="python", exclude={"citation_sha256"})
    payload[field] = foreign
    forged = CitationTargetV1.model_construct(
        **payload,
        citation_sha256=schema_wiki_sha256("citation-target.v1", payload),
    )

    with pytest.raises(SchemaWikiCompilationError):
        build_schema_field_page_596_1(
            output=output,
            evidence_receipt=receipt,
            citation_authority=_ExactCitationAuthority(
                expected=(citation,), returned=(forged,)
            ),
        )


def test_unknown_field_rejects_forged_evidence_and_cannot_express_a_citation() -> None:
    output, receipt = _unknown()
    known_output, known_receipt, _ = _known()

    with pytest.raises(SchemaWikiCompilationError):
        build_schema_field_page_596_1(
            output=output,
            evidence_receipt=known_receipt,
            citation_authority=_FailIfCalledCitationAuthority(),
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
            output=forged_unknown,
            evidence_receipt=receipt,
            citation_authority=_FailIfCalledCitationAuthority(),
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
    from tests.test_expert_golden_admission_596_2_119 import (
        _approved_cases,
        _candidate_v2,
    )

    candidate = _candidate_v2(_approved_cases())
    release = compile_schema_wiki_release_596_1(
        candidate=candidate,
        citation_authority=_SyntheticTrustedCitationAuthority(),
    )

    assert type(release) is KnowledgeWikiReleaseV1
    assert release.candidate_sha256 == candidate.candidate_sha256
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
    assert json.loads(vector_path.read_text(encoding="utf-8")) == release.model_dump(
        mode="json"
    )


def _real_candidate_and_release() -> tuple[
    Schema67CandidateV2, KnowledgeWikiReleaseV1
]:
    from tests.test_expert_golden_admission_596_2_119 import (
        _approved_cases,
        _candidate_v2,
    )

    candidate = _candidate_v2(_approved_cases())
    release = compile_schema_wiki_release_596_1(
        candidate=candidate,
        citation_authority=_SyntheticTrustedCitationAuthority(),
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
            output=output,
            evidence_receipt=receipt,
            citation_authority=_SyntheticTrustedCitationAuthority(),
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
