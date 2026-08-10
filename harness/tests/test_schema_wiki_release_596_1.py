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
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    CitationBBoxV1,
    CitationMemberBindingV1,
    CitationTargetV1,
    EntityIdentityV1,
    EntityVersionV1,
    KnowledgeDomainV1,
    KnowledgeWikiReleaseV1,
    SchemaFieldPageV1,
    SchemaPackV1,
    SchemaSectionV1,
    SchemaWikiMemberV1,
    SchemaWikiReviewBundleV1,
    TaxonomyNodeV1,
    TaxonomySnapshotV1,
    schema_wiki_manifest_digest,
    schema_wiki_sha256,
    validate_schema_wiki_review_bundle,
)
from insurance_harness.knowledge_compiler.schema_wiki_release_596_1 import (
    SchemaWikiCompilationError,
    build_schema_field_page_596_1,
    build_schema_wiki_review_bundle_596_1,
    compile_schema_wiki_release_596_1,
    require_manifest_bound_review_596_1,
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


def _member(
    *,
    member_ref: str,
    member_kind: str,
    payload_sha256: str,
    section_id: str | None = None,
    field_id: str | None = None,
) -> SchemaWikiMemberV1:
    return _sealed(
        SchemaWikiMemberV1,
        "schema-wiki-member.v1",
        "member_digest",
        contract="schema-wiki-member.v1",
        member_ref=member_ref,
        member_kind=member_kind,
        section_id=section_id,
        field_id=field_id,
        payload_sha256=payload_sha256,
    )


def _review_release() -> KnowledgeWikiReleaseV1:
    _, receipt, citation = _known()
    field_page = build_schema_field_page_596_1(
        output=_known()[0],
        evidence_receipt=receipt,
        citation_authority=_ExactCitationAuthority((citation,)),
    )
    domain = _sealed(
        KnowledgeDomainV1,
        "knowledge-domain.v1",
        "domain_sha256",
        contract="knowledge-domain.v1",
        domain_id="medical-insurance",
        display_name="医疗险",
    )
    pack = _sealed(
        SchemaPackV1,
        "schema-pack.v1",
        "schema_pack_sha256",
        contract="schema-pack.v1",
        schema_pack_id="medical-schema67.v1",
        schema_version="v1",
        domain_id=domain.domain_id,
        ordered_field_ids=("product_code",),
        sections=(
            SchemaSectionV1(
                section_id="product-overview",
                display_name="产品概览",
                ordered_field_ids=("product_code",),
            ),
        ),
    )
    taxonomy = _sealed(
        TaxonomySnapshotV1,
        "taxonomy-snapshot.v1",
        "taxonomy_sha256",
        contract="taxonomy-snapshot.v1",
        domain_id=domain.domain_id,
        taxonomy_version="medical-taxonomy.v1",
        previous_snapshot_sha256=None,
        nodes=(
            TaxonomyNodeV1(
                node_id="medical-product",
                parent_node_id=None,
                node_kind="category",
                slug="medical-product",
                stable_entity_id=None,
                position=0,
            ),
            TaxonomyNodeV1(
                node_id="ping-an-e-sheng-bao",
                parent_node_id="medical-product",
                node_kind="entity",
                slug="ping-an-e-sheng-bao",
                stable_entity_id="ping-an-e-sheng-bao",
                position=0,
            ),
        ),
        redirects=(),
    )
    entity = EntityIdentityV1(
        domain_id=domain.domain_id,
        entity_id="ping-an-e-sheng-bao",
    )
    version = EntityVersionV1(
        entity_id=entity.entity_id,
        version_id="ping-an-e-sheng-bao@596-1",
        product_version_id="596-1",
    )
    members = (
        _member(
            member_ref=f"root:{version.version_id}",
            member_kind="root",
            payload_sha256=_sha("root-payload"),
        ),
        _member(
            member_ref="section:product-overview",
            member_kind="section",
            section_id="product-overview",
            payload_sha256=_sha("section-payload"),
        ),
        _member(
            member_ref="field:product_code",
            member_kind="field",
            section_id="product-overview",
            field_id="product_code",
            payload_sha256=field_page.field_page_sha256,
        ),
    )
    field_member = members[-1]
    binding = _sealed(
        CitationMemberBindingV1,
        "citation-member-binding.v1",
        "binding_sha256",
        contract="citation-member-binding.v1",
        citation_sha256=citation.citation_sha256,
        logical_member_ref=citation.logical_member_ref,
        member_digest=field_member.member_digest,
    )
    payload = {
        "contract": "knowledge-wiki-release.v1",
        "release_state": "draft",
        "domain": domain,
        "taxonomy": taxonomy,
        "schema_pack": pack,
        "entity": entity,
        "entity_version": version,
        "candidate_sha256": "a" * 64,
        "review_policy_sha256": "b" * 64,
        "members": members,
        "citation_bindings": (binding,),
        "manifest_digest": schema_wiki_manifest_digest(members, (binding,)),
    }
    return _sealed(
        KnowledgeWikiReleaseV1,
        "knowledge-wiki-release.v1",
        "release_sha256",
        **payload,
    )


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


def test_review_bundle_binds_manifest_members_and_named_human_handoff() -> None:
    release = _review_release()

    bundle = build_schema_wiki_review_bundle_596_1(release=release)

    assert type(bundle) is SchemaWikiReviewBundleV1
    assert bundle.manifest_digest == release.manifest_digest
    assert bundle.release_sha256 == release.release_sha256
    assert validate_schema_wiki_review_bundle(bundle, release) == bundle
    assert (
        require_manifest_bound_review_596_1(
            release=release,
            review_bundle=bundle,
            human_batch_hash=bundle.review_bundle_sha256,
            ready_receipt_digest=bundle.review_bundle_sha256,
        )
        == bundle
    )


@pytest.mark.parametrize("drift", ["human_batch", "ready_receipt", "manifest"])
def test_review_bundle_rejects_reused_decision_or_manifest_drift(drift: str) -> None:
    release = _review_release()
    bundle = build_schema_wiki_review_bundle_596_1(release=release)
    human_batch_hash = bundle.review_bundle_sha256
    ready_receipt_digest = bundle.review_bundle_sha256
    if drift == "human_batch":
        human_batch_hash = "f" * 64
    elif drift == "ready_receipt":
        ready_receipt_digest = "f" * 64
    else:
        release = release.model_copy(update={"manifest_digest": "f" * 64})

    with pytest.raises(SchemaWikiCompilationError):
        require_manifest_bound_review_596_1(
            release=release,
            review_bundle=bundle,
            human_batch_hash=human_batch_hash,
            ready_receipt_digest=ready_receipt_digest,
        )


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
        build_schema_wiki_review_bundle_596_1(release=release), release
    )

    vector_path = (
        Path(__file__).parents[2]
        / "internal/application/service/testdata/schema_wiki_release_596_1_vector.json"
    )
    assert json.loads(vector_path.read_text(encoding="utf-8")) == release.model_dump(
        mode="json"
    )
