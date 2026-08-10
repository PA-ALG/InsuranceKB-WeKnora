"""Pure sealed-Candidate to medical Schema Wiki release compiler."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Protocol

from pydantic import ValidationError

from insurance_harness.compiler.evidence_verifier import (
    FreeformEvidenceBindingReceiptV1,
    FreeformEvidenceV1,
    FreeformFieldOutputV1,
)
from insurance_harness.knowledge_compiler.medical_schema_pack_596_1 import (
    MEDICAL_VERSION_ID,
    MedicalSchemaPackError,
    make_initial_medical_domain_596_1,
    make_initial_medical_entity_596_1,
    make_initial_medical_entity_version_596_1,
    make_initial_medical_taxonomy_596_1,
    make_medical_schema_pack_596_1,
    validate_initial_medical_authority_596_1,
    validate_medical_schema_pack_596_1,
)
from insurance_harness.knowledge_compiler.schema_first_contracts import (
    APPROVED_ORDERED_FIELD_IDS,
    APPROVED_PRODUCT_VERSION_ID,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    CitationMemberBindingV1,
    CitationTargetV1,
    KnowledgeWikiReleaseV1,
    SchemaFieldPageV1,
    SchemaWikiContractError,
    SchemaWikiMemberV1,
    SchemaWikiReviewBundleV1,
    schema_wiki_manifest_digest,
    schema_wiki_sha256,
    validate_citation_target,
    validate_knowledge_wiki_release,
    validate_schema_wiki_review_bundle,
)

if TYPE_CHECKING:
    from insurance_harness.goldenset.expert_golden_admission_596_2 import (
        Schema67CandidateV2,
    )

SCHEMA_WIKI_REVIEW_POLICY_SHA256: Final[str] = schema_wiki_sha256(
    "schema-wiki-review-policy.v1",
    {
        "policy": "named-human-complete-manifest-review",
        "product_version_id": APPROVED_PRODUCT_VERSION_ID,
        "partial_activation": False,
    },
)


class SchemaWikiCompilationError(ValueError):
    """Typed, privacy-safe medical release compilation failure."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class CitationAuthority5961Port(Protocol):
    """Trusted exact-revision join supplied outside the pure compiler."""

    def resolve(
        self,
        *,
        output: FreeformFieldOutputV1,
        evidence_receipt: FreeformEvidenceBindingReceiptV1,
        entity_version_id: str,
    ) -> tuple[CitationTargetV1, ...]: ...


def _fresh_output(output: FreeformFieldOutputV1) -> FreeformFieldOutputV1:
    try:
        return FreeformFieldOutputV1.model_validate(output.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise SchemaWikiCompilationError("FIELD_OUTPUT_INVALID") from None


def _fresh_receipt(
    receipt: FreeformEvidenceBindingReceiptV1,
) -> FreeformEvidenceBindingReceiptV1:
    try:
        return FreeformEvidenceBindingReceiptV1.model_validate(
            receipt.model_dump(mode="python")
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise SchemaWikiCompilationError("EVIDENCE_RECEIPT_INVALID") from None


def _evidence_identity(item: FreeformEvidenceV1) -> tuple[object, ...]:
    return (
        item.source_revision_id,
        item.parse_attempt_id,
        item.parsed_document_hash,
        item.parse_manifest_hash,
        item.page_number,
        item.locator.subject_ref,
        item.quote_snapshot,
        item.locator.content_snapshot_sha256,
    )


def _citation_identity(item: CitationTargetV1) -> tuple[object, ...]:
    return (
        item.source_revision_id,
        item.parse_attempt_id,
        item.parsed_document_sha256,
        item.parse_manifest_sha256,
        item.page_number,
        item.locator_ref,
        item.quote_snapshot,
        item.content_snapshot_sha256,
    )


def _validate_output_receipt_pair(
    output: FreeformFieldOutputV1,
    receipt: FreeformEvidenceBindingReceiptV1,
) -> None:
    if (
        output.product_version_id != APPROVED_PRODUCT_VERSION_ID
        or receipt.product_version_id != output.product_version_id
        or receipt.field_id != output.field_id
        or receipt.state != output.state
        or receipt.value_snapshot != output.value_snapshot
        or receipt.evidence != output.evidence
    ):
        raise SchemaWikiCompilationError("EVIDENCE_RECEIPT_BINDING_INVALID")


def _resolve_known_citations(
    *,
    output: FreeformFieldOutputV1,
    receipt: FreeformEvidenceBindingReceiptV1,
    citation_authority: CitationAuthority5961Port,
) -> tuple[CitationTargetV1, ...]:
    try:
        citations = citation_authority.resolve(
            output=output,
            evidence_receipt=receipt,
            entity_version_id=MEDICAL_VERSION_ID,
        )
    except Exception:
        raise SchemaWikiCompilationError("CITATION_AUTHORITY_INVALID") from None
    if type(citations) is not tuple or len(citations) != len(output.evidence):
        raise SchemaWikiCompilationError("CITATION_AUTHORITY_INVALID")
    checked: list[CitationTargetV1] = []
    for evidence, citation in zip(output.evidence, citations, strict=True):
        try:
            exact = CitationTargetV1.model_validate(citation.model_dump(mode="python"))
            validate_citation_target(
                exact,
                expected_space_id=exact.space_id,
                expected_entity_version_id=MEDICAL_VERSION_ID,
                expected_knowledge_id=exact.knowledge_id,
                expected_chunk_id=exact.chunk_id,
                expected_source_revision_id=evidence.source_revision_id,
                expected_parse_attempt_id=evidence.parse_attempt_id,
                expected_parsed_document_sha256=evidence.parsed_document_hash,
                expected_parse_manifest_sha256=evidence.parse_manifest_hash,
                expected_page_number=evidence.page_number,
                expected_locator_ref=evidence.locator.subject_ref,
                expected_quote_snapshot=evidence.quote_snapshot,
                expected_content_snapshot_sha256=evidence.locator.content_snapshot_sha256,
            )
        except (AttributeError, TypeError, ValueError, ValidationError, SchemaWikiContractError):
            raise SchemaWikiCompilationError("CITATION_AUTHORITY_INVALID") from None
        if (
            exact.logical_member_ref != f"field:{output.field_id}"
            or _citation_identity(exact) != _evidence_identity(evidence)
        ):
            raise SchemaWikiCompilationError("CITATION_AUTHORITY_INVALID")
        checked.append(exact)
    return tuple(checked)


def build_schema_field_page_596_1(
    *,
    output: FreeformFieldOutputV1,
    evidence_receipt: FreeformEvidenceBindingReceiptV1,
    citation_authority: CitationAuthority5961Port,
) -> SchemaFieldPageV1:
    exact_output = _fresh_output(output)
    exact_receipt = _fresh_receipt(evidence_receipt)
    _validate_output_receipt_pair(exact_output, exact_receipt)
    if exact_output.field_id not in APPROVED_ORDERED_FIELD_IDS:
        raise SchemaWikiCompilationError("FIELD_ID_INVALID")

    if exact_output.state == "unknown":
        citations: tuple[CitationTargetV1, ...] = ()
        receipt_hashes: tuple[str, ...] = ()
        review_reason: str | None = "FIELD_UNKNOWN"
    else:
        citations = _resolve_known_citations(
            output=exact_output,
            receipt=exact_receipt,
            citation_authority=citation_authority,
        )
        receipt_hashes = (exact_receipt.receipt_hash,)
        review_reason = None
    payload = {
        "contract": "schema-field-page.v1",
        "field_id": exact_output.field_id,
        "state": exact_output.state,
        "value_snapshot": exact_output.value_snapshot,
        "citations": citations,
        "evidence_receipt_sha256s": receipt_hashes,
        "review_item_reason": review_reason,
    }
    try:
        return SchemaFieldPageV1.model_validate(
            {
                **payload,
                "field_page_sha256": schema_wiki_sha256(
                    "schema-field-page.v1", payload
                ),
            }
        )
    except (TypeError, ValueError, ValidationError):
        raise SchemaWikiCompilationError("FIELD_PAGE_INVALID") from None


def _member(
    *,
    member_ref: str,
    member_kind: str,
    payload_sha256: str,
    section_id: str | None = None,
    field_id: str | None = None,
) -> SchemaWikiMemberV1:
    payload = {
        "contract": "schema-wiki-member.v1",
        "member_ref": member_ref,
        "member_kind": member_kind,
        "section_id": section_id,
        "field_id": field_id,
        "payload_sha256": payload_sha256,
    }
    return SchemaWikiMemberV1.model_validate(
        {
            **payload,
            "member_digest": schema_wiki_sha256("schema-wiki-member.v1", payload),
        }
    )


def _citation_binding(
    citation: CitationTargetV1, member: SchemaWikiMemberV1
) -> CitationMemberBindingV1:
    payload = {
        "contract": "citation-member-binding.v1",
        "citation_sha256": citation.citation_sha256,
        "logical_member_ref": citation.logical_member_ref,
        "member_digest": member.member_digest,
    }
    return CitationMemberBindingV1.model_validate(
        {
            **payload,
            "binding_sha256": schema_wiki_sha256(
                "citation-member-binding.v1", payload
            ),
        }
    )


def _validate_sealed_candidate(candidate: object) -> Schema67CandidateV2:
    from insurance_harness.goldenset.expert_golden_admission_596_2 import (
        validate_schema67_candidate_v2,
    )

    try:
        exact = validate_schema67_candidate_v2(candidate)
    except Exception:
        raise SchemaWikiCompilationError("SCHEMA_WIKI_COMPILATION_NOT_COMPLETE") from None
    if (
        exact.product_version_id != APPROVED_PRODUCT_VERSION_ID
        or exact.ordered_field_ids != APPROVED_ORDERED_FIELD_IDS
        or tuple(item.field_id for item in exact.fields) != APPROVED_ORDERED_FIELD_IDS
        or tuple(item.field_id for item in exact.evidence_receipts)
        != APPROVED_ORDERED_FIELD_IDS
    ):
        raise SchemaWikiCompilationError("SCHEMA_WIKI_COMPILATION_NOT_COMPLETE")
    return exact


def compile_schema_wiki_release_596_1(
    *,
    candidate: object,
    citation_authority: CitationAuthority5961Port,
) -> KnowledgeWikiReleaseV1:
    exact_candidate = _validate_sealed_candidate(candidate)
    pack = make_medical_schema_pack_596_1()
    domain = make_initial_medical_domain_596_1()
    entity = make_initial_medical_entity_596_1()
    entity_version = make_initial_medical_entity_version_596_1()
    taxonomy = make_initial_medical_taxonomy_596_1()
    try:
        validate_medical_schema_pack_596_1(pack)
        validate_initial_medical_authority_596_1(
            domain=domain,
            entity=entity,
            entity_version=entity_version,
            taxonomy=taxonomy,
        )
    except MedicalSchemaPackError:
        raise SchemaWikiCompilationError("MEDICAL_AUTHORITY_INVALID") from None

    field_pages = tuple(
        build_schema_field_page_596_1(
            output=output,
            evidence_receipt=receipt,
            citation_authority=citation_authority,
        )
        for output, receipt in zip(
            exact_candidate.fields,
            exact_candidate.evidence_receipts,
            strict=True,
        )
    )
    root_payload_sha256 = schema_wiki_sha256(
        "medical-schema-wiki-root-payload.v1",
        {
            "domain": domain,
            "taxonomy": taxonomy,
            "schema_pack": pack,
            "entity": entity,
            "entity_version": entity_version,
            "navigation": tuple(
                {
                    "section_id": section.section_id,
                    "display_name": section.display_name,
                    "ordered_field_ids": section.ordered_field_ids,
                }
                for section in pack.sections
            ),
        },
    )
    members: list[SchemaWikiMemberV1] = [
        _member(
            member_ref=f"root:{entity_version.version_id}",
            member_kind="root",
            payload_sha256=root_payload_sha256,
        )
    ]
    members.extend(
        _member(
            member_ref=f"section:{section.section_id}",
            member_kind="section",
            section_id=section.section_id,
            payload_sha256=schema_wiki_sha256(
                "medical-schema-wiki-section-payload.v1",
                {
                    "section_id": section.section_id,
                    "display_name": section.display_name,
                    "ordered_field_ids": section.ordered_field_ids,
                },
            ),
        )
        for section in pack.sections
    )
    section_by_field = {
        field_id: section.section_id
        for section in pack.sections
        for field_id in section.ordered_field_ids
    }
    field_members: list[SchemaWikiMemberV1] = []
    for page in field_pages:
        field_members.append(
            _member(
                member_ref=f"field:{page.field_id}",
                member_kind="field",
                section_id=section_by_field[page.field_id],
                field_id=page.field_id,
                payload_sha256=page.field_page_sha256,
            )
        )
    members.extend(field_members)
    members_tuple = tuple(members)
    member_by_ref = {item.member_ref: item for item in members_tuple}
    bindings = tuple(
        sorted(
            (
                _citation_binding(citation, member_by_ref[citation.logical_member_ref])
                for page in field_pages
                for citation in page.citations
            ),
            key=lambda row: (row.logical_member_ref, row.citation_sha256),
        )
    )
    payload = {
        "contract": "knowledge-wiki-release.v1",
        "release_state": "draft",
        "domain": domain,
        "taxonomy": taxonomy,
        "schema_pack": pack,
        "entity": entity,
        "entity_version": entity_version,
        "candidate_sha256": exact_candidate.candidate_sha256,
        "review_policy_sha256": SCHEMA_WIKI_REVIEW_POLICY_SHA256,
        "members": members_tuple,
        "citation_bindings": bindings,
        "manifest_digest": schema_wiki_manifest_digest(members_tuple, bindings),
    }
    try:
        release = KnowledgeWikiReleaseV1.model_validate(
            {
                **payload,
                "release_sha256": schema_wiki_sha256(
                    "knowledge-wiki-release.v1", payload
                ),
            }
        )
        return validate_knowledge_wiki_release(release, pack)
    except (KeyError, TypeError, ValueError, ValidationError, SchemaWikiContractError):
        raise SchemaWikiCompilationError("RELEASE_CUSTODY_INVALID") from None


def build_schema_wiki_review_bundle_596_1(
    *, release: KnowledgeWikiReleaseV1
) -> SchemaWikiReviewBundleV1:
    try:
        exact = validate_knowledge_wiki_release(release, release.schema_pack)
        payload = {
            "contract": "schema-wiki-review-bundle.v1",
            "candidate_sha256": exact.candidate_sha256,
            "release_sha256": exact.release_sha256,
            "manifest_digest": exact.manifest_digest,
            "ordered_member_digests": tuple(
                item.member_digest for item in exact.members
            ),
            "ordered_binding_sha256s": tuple(
                item.binding_sha256 for item in exact.citation_bindings
            ),
            "review_policy_sha256": exact.review_policy_sha256,
            "domain_sha256": exact.domain.domain_sha256,
            "taxonomy_sha256": exact.taxonomy.taxonomy_sha256,
            "schema_pack_sha256": exact.schema_pack.schema_pack_sha256,
            "entity_id": exact.entity.entity_id,
            "version_id": exact.entity_version.version_id,
        }
        bundle = SchemaWikiReviewBundleV1.model_validate(
            {
                **payload,
                "review_bundle_sha256": schema_wiki_sha256(
                    "schema-wiki-review-bundle.v1", payload
                ),
            }
        )
        return validate_schema_wiki_review_bundle(bundle, exact)
    except (AttributeError, TypeError, ValueError, ValidationError, SchemaWikiContractError):
        raise SchemaWikiCompilationError("REVIEW_BUNDLE_INVALID") from None


def require_manifest_bound_review_596_1(
    *,
    release: KnowledgeWikiReleaseV1,
    review_bundle: SchemaWikiReviewBundleV1,
    human_batch_hash: str,
    ready_receipt_digest: str,
) -> SchemaWikiReviewBundleV1:
    try:
        exact = validate_schema_wiki_review_bundle(review_bundle, release)
    except (AttributeError, TypeError, ValueError, SchemaWikiContractError):
        raise SchemaWikiCompilationError("REVIEW_BUNDLE_INVALID") from None
    if (
        human_batch_hash != exact.review_bundle_sha256
        or ready_receipt_digest != exact.review_bundle_sha256
    ):
        raise SchemaWikiCompilationError("REVIEW_HANDOFF_INVALID")
    return exact


__all__ = [
    "CitationAuthority5961Port",
    "SCHEMA_WIKI_REVIEW_POLICY_SHA256",
    "SchemaWikiCompilationError",
    "build_schema_field_page_596_1",
    "build_schema_wiki_review_bundle_596_1",
    "compile_schema_wiki_release_596_1",
    "require_manifest_bound_review_596_1",
]
