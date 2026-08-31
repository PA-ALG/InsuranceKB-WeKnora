"""Pure G1 compiler for entity-scoped FieldAssertion page manifests."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Annotated, Literal, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.canonical import canonical_hash
from insurance_harness.compiler.evidence_verifier import (
    FreeformEvidenceBindingReceiptV1,
    FreeformFieldOutputV1,
)
from insurance_harness.knowledge_compiler.schema_wiki_candidate_evidence_join_596_1 import (
    Schema67CandidateEvidenceAuthorityV1,
)
from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    CitationBBoxV1,
    schema_wiki_sha256,
)

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[StrictStr, StringConstraints(min_length=1, max_length=512)]
NonBlank = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=8192, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
TriState = Literal["present", "absent_explicitly", "unknown"]
UnknownReason = Literal["FIELD_UNKNOWN", "NOT_COVERED_BY_CURRENT_SOURCE_MATERIALS"]
PageKind = Literal["overview", "section", "field", "free_wiki"]


class EntityPageGraphError(ValueError):
    """Stable fail-closed error for actual-input or manifest drift."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


def sha256_hex(data: bytes) -> str:
    """Return the external file SHA-256 used by the frozen input authority."""

    return hashlib.sha256(data).hexdigest()


def _payload(model: BaseModel, hash_field: str) -> dict[str, object]:
    return model.model_dump(
        mode="python",
        round_trip=True,
        warnings=False,
        exclude={hash_field},
        exclude_computed_fields=True,
    )


def _hash_matches(model: BaseModel, hash_field: str) -> bool:
    values = model.model_dump(mode="python", round_trip=True, warnings=False)
    contract = cast(str, values["contract"])
    stored_hash = cast(str, values[hash_field])
    return stored_hash == schema_wiki_sha256(contract, _payload(model, hash_field))


class PresentationFieldV1(_FrozenModel):
    field_key: Identifier
    short_title: NonBlank


class PresentationSectionV1(_FrozenModel):
    section_key: Identifier
    display_name: NonBlank
    fields: tuple[PresentationFieldV1, ...]

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        keys = tuple(item.field_key for item in self.fields)
        if not keys or len(keys) != len(set(keys)):
            raise ValueError("section fields must be a non-empty unique order")
        return self


class PresentationProfileV1(_FrozenModel):
    contract: Literal["presentation-profile.v1"]
    profile_id: Identifier
    profile_version: Identifier
    schema_pack_id: Identifier
    schema_version: Identifier
    schema_pack_sha256: Sha256Hex
    sections: tuple[PresentationSectionV1, ...]
    profile_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_profile(self) -> Self:
        section_keys = tuple(item.section_key for item in self.sections)
        field_keys = tuple(field.field_key for section in self.sections for field in section.fields)
        if (
            not section_keys
            or len(section_keys) != len(set(section_keys))
            or not field_keys
            or len(field_keys) != len(set(field_keys))
            or not _hash_matches(self, "profile_sha256")
        ):
            raise ValueError("presentation profile topology or hash is invalid")
        return self

    @property
    def ordered_field_keys(self) -> tuple[str, ...]:
        return tuple(field.field_key for section in self.sections for field in section.fields)


class ManifestSourceAuthorityV1(_FrozenModel):
    source_role: Identifier
    source_sha256: Sha256Hex
    knowledge_id: Identifier
    resource_id: Identifier
    revision_source_id: Identifier
    evidence_parse_attempt_id: Identifier
    weknora_parse_attempt: Annotated[StrictInt, Field(gt=0)]
    parsed_document_sha256: Sha256Hex
    parse_manifest_sha256: Sha256Hex
    source_receipt_sha256: Sha256Hex


class ActualInputFilesV1(_FrozenModel):
    bundle_manifest_contract: Identifier
    bundle_manifest_sha256: Sha256Hex
    bundle_manifest_file_sha256: Sha256Hex
    preview_contract: Identifier
    preview_sha256: Sha256Hex
    preview_file_sha256: Sha256Hex
    profile_file_sha256: Sha256Hex


class ManifestInputAuthorityV1(_FrozenModel):
    candidate_contract: Identifier
    candidate_sha256: Sha256Hex
    candidate_file_sha256: Sha256Hex
    product_version_id: Identifier
    claim_set_sha256: Sha256Hex
    evidence_receipt_set_sha256: Sha256Hex
    evidence_authority_contract: Identifier
    evidence_authority_sha256: Sha256Hex
    evidence_authority_file_sha256: Sha256Hex
    source_authorities: tuple[ManifestSourceAuthorityV1, ...]
    actual_files: ActualInputFilesV1


class EntityPageCompileContextV1(_FrozenModel):
    release_id: Identifier
    activation_epoch: Annotated[StrictInt, Field(gt=0)]
    space_id: Identifier
    wiki_kb_id: Identifier
    entity_id: Identifier
    entity_version_id: Identifier
    display_name: NonBlank
    classification_display_name: NonBlank
    expected_candidate_sha256: Sha256Hex | None = None
    expected_candidate_file_sha256: Sha256Hex | None = None
    expected_claim_set_sha256: Sha256Hex | None = None
    expected_evidence_receipt_set_sha256: Sha256Hex | None = None
    expected_evidence_authority_sha256: Sha256Hex | None = None
    expected_evidence_authority_file_sha256: Sha256Hex | None = None
    expected_bundle_manifest_sha256: Sha256Hex | None = None
    expected_bundle_manifest_file_sha256: Sha256Hex | None = None
    expected_preview_sha256: Sha256Hex | None = None
    expected_preview_file_sha256: Sha256Hex | None = None
    expected_profile_sha256: Sha256Hex | None = None
    expected_profile_file_sha256: Sha256Hex | None = None


class ExactCitationV1(_FrozenModel):
    contract: Literal["entity-page-exact-citation.830.g1.v1"]
    citation_id: Identifier
    join_receipt_sha256: Sha256Hex
    evidence_receipt_sha256: Sha256Hex
    source_role: Identifier
    source_sha256: Sha256Hex
    source_revision_id: Identifier
    knowledge_id: Identifier
    chunk_id: Identifier
    parse_attempt_id: Identifier
    parsed_document_sha256: Sha256Hex
    parse_manifest_sha256: Sha256Hex
    page_number: Annotated[StrictInt, Field(gt=0)]
    locator_kind: Identifier
    locator_ref: Identifier
    locator_content_sha256: Sha256Hex
    bbox: CitationBBoxV1
    quote_snapshot: NonBlank
    quote_sha256: Sha256Hex
    citation_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_citation(self) -> Self:
        if self.quote_sha256 != schema_wiki_sha256(
            "schema-wiki-text.v1", {"text": self.quote_snapshot}
        ) or not _hash_matches(self, "citation_sha256"):
            raise ValueError("exact citation hash is invalid")
        return self


class FieldAssertionInputV1(_FrozenModel):
    field_key: Identifier
    state: TriState
    value_snapshot: NonBlank | None
    unknown_reason: UnknownReason | None
    source_typed_reason: NonBlank | None
    evidence_receipt_sha256s: tuple[Sha256Hex, ...]
    citations: tuple[ExactCitationV1, ...]

    @model_validator(mode="after")
    def validate_tri_state(self) -> Self:
        receipt_ids = self.evidence_receipt_sha256s
        citation_ids = tuple(item.citation_sha256 for item in self.citations)
        if len(receipt_ids) != len(set(receipt_ids)) or len(citation_ids) != len(set(citation_ids)):
            raise ValueError("duplicate FieldAssertion evidence identity")
        if self.state == "unknown":
            valid = (
                self.value_snapshot is None
                and self.unknown_reason is not None
                and self.source_typed_reason is not None
                and not receipt_ids
                and not self.citations
            )
        else:
            valid = (
                self.value_snapshot is not None
                and self.unknown_reason is None
                and self.source_typed_reason is None
                and bool(receipt_ids)
                and bool(self.citations)
                and all(item.evidence_receipt_sha256 in receipt_ids for item in self.citations)
            )
        if not valid:
            raise ValueError("FieldAssertion tri-state shape is invalid")
        return self


class FieldAssertionReferenceV1(_FrozenModel):
    field_key: Identifier
    page_id: Identifier
    source_release_id: Identifier
    source_candidate_sha256: Sha256Hex
    product_version_id: Identifier
    claim_sha256: Sha256Hex
    evidence_receipt_sha256s: tuple[Sha256Hex, ...]
    citation_sha256s: tuple[Sha256Hex, ...]


class EntityOverviewPayloadV1(_FrozenModel):
    contract: Literal["entity-overview-page.830.g1.v1"]
    entity_id: Identifier
    entity_version_id: Identifier
    ordered_section_page_ids: tuple[Identifier, ...]
    field_assertions: tuple[FieldAssertionReferenceV1, ...]


class EntitySectionPayloadV1(_FrozenModel):
    contract: Literal["entity-section-page.830.g1.v1"]
    section_key: Identifier
    field_assertions: tuple[FieldAssertionReferenceV1, ...]


class FieldAssertionPayloadV1(_FrozenModel):
    contract: Literal["field-assertion-page.830.g1.v1"]
    field_key: Identifier
    reference: FieldAssertionReferenceV1
    state: TriState
    value_snapshot: NonBlank | None
    display_value: NonBlank | None
    unknown_reason: UnknownReason | None
    source_typed_reason: NonBlank | None
    citations: tuple[ExactCitationV1, ...]

    @model_validator(mode="after")
    def validate_payload(self) -> Self:
        if self.reference.field_key != self.field_key:
            raise ValueError("FieldAssertion reference mismatch")
        if self.reference.claim_sha256 != field_claim_sha256(
            source_release_id=self.reference.source_release_id,
            source_candidate_sha256=self.reference.source_candidate_sha256,
            product_version_id=self.reference.product_version_id,
            field_id=self.field_key,
            state=self.state,
            value_snapshot=self.value_snapshot,
        ):
            raise ValueError("FieldAssertion claim hash mismatch")
        citation_sha256s = tuple(item.citation_sha256 for item in self.citations)
        evidence_receipt_sha256s = tuple(
            dict.fromkeys(item.evidence_receipt_sha256 for item in self.citations)
        )
        if (
            self.reference.citation_sha256s != citation_sha256s
            or self.reference.evidence_receipt_sha256s != evidence_receipt_sha256s
        ):
            raise ValueError("FieldAssertion evidence reference mismatch")
        if self.state == "unknown":
            valid = (
                self.value_snapshot is None
                and self.display_value is None
                and self.unknown_reason is not None
                and self.source_typed_reason is not None
                and not self.citations
            )
        else:
            valid = (
                self.value_snapshot is not None
                and self.display_value == self.value_snapshot
                and self.unknown_reason is None
                and self.source_typed_reason is None
                and bool(self.citations)
            )
        if not valid:
            raise ValueError("FieldAssertion payload state mismatch")
        return self


class EmptyFreeWikiPayloadV1(_FrozenModel):
    contract: Literal["empty-free-wiki-page.830.g1.v1"]
    items: tuple[dict[str, object], ...]

    @model_validator(mode="after")
    def validate_empty(self) -> Self:
        if self.items:
            raise ValueError("G1 free_wiki must remain empty")
        return self


EntityPagePayloadV1 = Annotated[
    EntityOverviewPayloadV1
    | EntitySectionPayloadV1
    | FieldAssertionPayloadV1
    | EmptyFreeWikiPayloadV1,
    Field(discriminator="contract"),
]


def _identity_payload(
    *, space_id: str, entity_id: str, page_kind: PageKind, stable_key: str
) -> dict[str, str]:
    return {
        "space_id": space_id,
        "entity_id": entity_id,
        "page_kind": page_kind,
        "stable_key": stable_key,
    }


def _namespace(*, space_id: str, entity_id: str, page_kind: PageKind, stable_key: str) -> str:
    kind = "free-wiki" if page_kind == "free_wiki" else page_kind
    return f"urn:jlx:wiki:{space_id}:entity:{entity_id}:{kind}:{stable_key}"


def _route(*, wiki_kb_id: str, entity_id: str, page_kind: PageKind, stable_key: str) -> str:
    base = f"/platform/knowledge-bases/{wiki_kb_id}/schema-wiki/entities/{entity_id}"
    if page_kind == "overview":
        return f"{base}/overview"
    if page_kind == "section":
        return f"{base}/sections/{stable_key}"
    if page_kind == "field":
        return f"{base}/fields/{stable_key}"
    return f"{base}/free-wiki"


class EntityPageMemberV1(_FrozenModel):
    contract: Literal["entity-page-member.830.g1.v1"]
    page_id: Identifier
    namespace: Identifier
    route: Identifier
    page_kind: PageKind
    stable_key: Identifier
    short_title: NonBlank
    space_id: Identifier
    wiki_kb_id: Identifier
    entity_id: Identifier
    release_id: Identifier
    candidate_sha256: Sha256Hex
    claim_set_sha256: Sha256Hex
    evidence_authority_sha256: Sha256Hex
    schema_pack_sha256: Sha256Hex
    profile_sha256: Sha256Hex
    payload: EntityPagePayloadV1
    payload_sha256: Sha256Hex
    member_digest: Sha256Hex

    @model_validator(mode="after")
    def validate_member(self) -> Self:
        identity = _identity_payload(
            space_id=self.space_id,
            entity_id=self.entity_id,
            page_kind=self.page_kind,
            stable_key=self.stable_key,
        )
        expected_page_id = "page_" + schema_wiki_sha256("entity-page-identity.830.g1.v1", identity)
        expected_payload_hash = schema_wiki_sha256(self.payload.contract, self.payload)
        if (
            self.page_id != expected_page_id
            or self.namespace
            != _namespace(
                space_id=self.space_id,
                entity_id=self.entity_id,
                page_kind=self.page_kind,
                stable_key=self.stable_key,
            )
            or self.route
            != _route(
                wiki_kb_id=self.wiki_kb_id,
                entity_id=self.entity_id,
                page_kind=self.page_kind,
                stable_key=self.stable_key,
            )
            or self.payload_sha256 != expected_payload_hash
            or not _hash_matches(self, "member_digest")
        ):
            raise ValueError("entity page member identity or hash mismatch")
        return self


class EntityPageAuthorityV1(_FrozenModel):
    serving_authority: Literal["WEKNORA"] = "WEKNORA"
    harness_role: Literal["OFFLINE_PURE_COMPILER"] = "OFFLINE_PURE_COMPILER"
    per_page_activation_allowed: Literal[False] = False
    rendered_content_authoritative: Literal[False] = False
    database_access_required: Literal[False] = False
    network_access_required: Literal[False] = False
    provider_model_access_required: Literal[False] = False


class TriStateDistributionV1(_FrozenModel):
    present: Annotated[StrictInt, Field(ge=0)]
    absent_explicitly: Annotated[StrictInt, Field(ge=0)]
    unknown: Annotated[StrictInt, Field(ge=0)]


class EntityPageManifestV1(_FrozenModel):
    contract: Literal["entity-page-manifest.830.g1.v1"]
    release_id: Identifier
    activation_epoch: Annotated[StrictInt, Field(gt=0)]
    space_id: Identifier
    wiki_kb_id: Identifier
    entity_id: Identifier
    entity_version_id: Identifier
    display_name: NonBlank
    classification_display_name: NonBlank
    profile: PresentationProfileV1
    input_authority: ManifestInputAuthorityV1
    authority: EntityPageAuthorityV1
    members: tuple[EntityPageMemberV1, ...]
    section_count: Annotated[StrictInt, Field(gt=0)]
    field_assertion_count: Annotated[StrictInt, Field(gt=0)]
    state_distribution: TriStateDistributionV1
    field_assertion_page_ids: tuple[Identifier, ...]
    free_wiki_empty: Literal[True]
    manifest_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_manifest(self) -> Self:
        expected_order: list[tuple[str, str]] = [("overview", "overview")]
        expected_order.extend(("section", item.section_key) for item in self.profile.sections)
        expected_order.extend(("field", item) for item in self.profile.ordered_field_keys)
        expected_order.append(("free_wiki", "free-wiki"))
        actual_order = [(item.page_kind, item.stable_key) for item in self.members]
        field_members = [item for item in self.members if item.page_kind == "field"]
        field_payloads = tuple(
            cast(FieldAssertionPayloadV1, item.payload) for item in field_members
        )
        canonical_reference_by_field = {
            item.stable_key: payload.reference
            for item, payload in zip(field_members, field_payloads, strict=True)
        }
        expected_overview_references = tuple(
            canonical_reference_by_field.get(field_key)
            for field_key in self.profile.ordered_field_keys
        )
        section_members = [item for item in self.members if item.page_kind == "section"]
        expected_section_page_ids = tuple(item.page_id for item in section_members)
        overview_members = [item for item in self.members if item.page_kind == "overview"]
        overview_topology_valid = len(overview_members) == 1 and isinstance(
            overview_members[0].payload, EntityOverviewPayloadV1
        )
        if overview_topology_valid:
            overview_payload = cast(EntityOverviewPayloadV1, overview_members[0].payload)
            overview_topology_valid = (
                overview_payload.entity_id == self.entity_id
                and overview_payload.entity_version_id == self.entity_version_id
                and overview_payload.ordered_section_page_ids == expected_section_page_ids
                and overview_payload.field_assertions == expected_overview_references
            )
        section_topology_valid = len(section_members) == len(self.profile.sections) and all(
            isinstance(member.payload, EntitySectionPayloadV1)
            and member.stable_key == section.section_key
            and member.payload.section_key == member.stable_key
            and member.payload.field_assertions
            == tuple(canonical_reference_by_field.get(field.field_key) for field in section.fields)
            for member, section in zip(section_members, self.profile.sections, strict=True)
        )
        field_topology_valid = len(field_payloads) == len(self.profile.ordered_field_keys) and all(
            member.stable_key == payload.field_key and payload.reference.page_id == member.page_id
            for member, payload in zip(field_members, field_payloads, strict=True)
        )
        page_ids = tuple(item.page_id for item in self.members)
        field_ids = tuple(item.page_id for item in field_members)
        state_counts = Counter(
            cast(FieldAssertionPayloadV1, item.payload).state for item in field_members
        )
        common_valid = all(
            (
                item.release_id,
                item.space_id,
                item.wiki_kb_id,
                item.entity_id,
                item.candidate_sha256,
                item.claim_set_sha256,
                item.evidence_authority_sha256,
                item.schema_pack_sha256,
                item.profile_sha256,
            )
            == (
                self.release_id,
                self.space_id,
                self.wiki_kb_id,
                self.entity_id,
                self.input_authority.candidate_sha256,
                self.input_authority.claim_set_sha256,
                self.input_authority.evidence_authority_sha256,
                self.profile.schema_pack_sha256,
                self.profile.profile_sha256,
            )
            for item in self.members
        )
        references = tuple(
            reference
            for item in self.members
            for reference in (
                item.payload.field_assertions
                if isinstance(item.payload, (EntityOverviewPayloadV1, EntitySectionPayloadV1))
                else (item.payload.reference,)
                if isinstance(item.payload, FieldAssertionPayloadV1)
                else ()
            )
        )
        reference_authority_valid = all(
            (
                item.source_release_id,
                item.source_candidate_sha256,
                item.product_version_id,
            )
            == (
                self.release_id,
                self.input_authority.candidate_sha256,
                self.input_authority.product_version_id,
            )
            for item in references
        )
        source_authority_keys = tuple(
            (
                item.source_role,
                item.source_sha256,
                item.knowledge_id,
                item.revision_source_id,
                item.evidence_parse_attempt_id,
                item.parsed_document_sha256,
                item.parse_manifest_sha256,
            )
            for item in self.input_authority.source_authorities
        )
        source_authority_key_set = set(source_authority_keys)
        citation_authority_keys = tuple(
            (
                citation.source_role,
                citation.source_sha256,
                citation.knowledge_id,
                citation.source_revision_id,
                citation.parse_attempt_id,
                citation.parsed_document_sha256,
                citation.parse_manifest_sha256,
            )
            for payload in field_payloads
            for citation in payload.citations
        )
        citation_source_authority_valid = len(source_authority_keys) == len(
            source_authority_key_set
        ) and all(item in source_authority_key_set for item in citation_authority_keys)
        if (
            actual_order != expected_order
            or len(page_ids) != len(set(page_ids))
            or self.section_count != len(self.profile.sections)
            or self.field_assertion_count != len(self.profile.ordered_field_keys)
            or field_ids != self.field_assertion_page_ids
            or self.state_distribution.model_dump(mode="python")
            != {
                "present": state_counts["present"],
                "absent_explicitly": state_counts["absent_explicitly"],
                "unknown": state_counts["unknown"],
            }
            or not common_valid
            or not reference_authority_valid
            or not citation_source_authority_valid
            or not overview_topology_valid
            or not section_topology_valid
            or not field_topology_valid
            or not _hash_matches(self, "manifest_sha256")
        ):
            raise ValueError("entity page manifest closure or hash mismatch")
        return self


def claim_input_set_sha256(
    *,
    candidate_sha256: str,
    product_version_id: str,
    assertions: Sequence[FieldAssertionInputV1],
) -> str:
    payload = {
        "contract": "g1-claim-input-set.v1",
        "candidate_sha256": candidate_sha256,
        "product_version_id": product_version_id,
        "claims": tuple(
            {
                "field_id": item.field_key,
                "state": item.state,
                "value_snapshot": item.value_snapshot,
            }
            for item in assertions
        ),
    }
    return schema_wiki_sha256("g1-claim-input-set.v1", payload)


def field_claim_sha256(
    *,
    source_release_id: str,
    source_candidate_sha256: str,
    product_version_id: str,
    field_id: str,
    state: TriState,
    value_snapshot: str | None,
) -> str:
    """Digest one frozen release/candidate/product field assertion claim."""

    return schema_wiki_sha256(
        "field-assertion-claim.830.g1.v1",
        {
            "source_release_id": source_release_id,
            "source_candidate_sha256": source_candidate_sha256,
            "product_version_id": product_version_id,
            "field_id": field_id,
            "state": state,
            "value_snapshot": value_snapshot,
        },
    )


def _page_id(*, context: EntityPageCompileContextV1, page_kind: PageKind, stable_key: str) -> str:
    return "page_" + schema_wiki_sha256(
        "entity-page-identity.830.g1.v1",
        _identity_payload(
            space_id=context.space_id,
            entity_id=context.entity_id,
            page_kind=page_kind,
            stable_key=stable_key,
        ),
    )


def _member(
    *,
    context: EntityPageCompileContextV1,
    profile: PresentationProfileV1,
    input_authority: ManifestInputAuthorityV1,
    page_kind: PageKind,
    stable_key: str,
    short_title: str,
    payload: EntityPagePayloadV1,
) -> EntityPageMemberV1:
    payload_sha256 = schema_wiki_sha256(payload.contract, payload)
    row = {
        "contract": "entity-page-member.830.g1.v1",
        "page_id": _page_id(context=context, page_kind=page_kind, stable_key=stable_key),
        "namespace": _namespace(
            space_id=context.space_id,
            entity_id=context.entity_id,
            page_kind=page_kind,
            stable_key=stable_key,
        ),
        "route": _route(
            wiki_kb_id=context.wiki_kb_id,
            entity_id=context.entity_id,
            page_kind=page_kind,
            stable_key=stable_key,
        ),
        "page_kind": page_kind,
        "stable_key": stable_key,
        "short_title": short_title,
        "space_id": context.space_id,
        "wiki_kb_id": context.wiki_kb_id,
        "entity_id": context.entity_id,
        "release_id": context.release_id,
        "candidate_sha256": input_authority.candidate_sha256,
        "claim_set_sha256": input_authority.claim_set_sha256,
        "evidence_authority_sha256": input_authority.evidence_authority_sha256,
        "schema_pack_sha256": profile.schema_pack_sha256,
        "profile_sha256": profile.profile_sha256,
        "payload": payload,
        "payload_sha256": payload_sha256,
    }
    return EntityPageMemberV1.model_validate(
        {
            **row,
            "member_digest": schema_wiki_sha256("entity-page-member.830.g1.v1", row),
        }
    )


def compile_entity_page_manifest(
    *,
    context: EntityPageCompileContextV1,
    profile: PresentationProfileV1,
    input_authority: ManifestInputAuthorityV1,
    assertions: Sequence[FieldAssertionInputV1],
) -> EntityPageManifestV1:
    """Compile one deterministic graph without IO, serving state, or side effects."""

    exact_assertions = tuple(
        FieldAssertionInputV1.model_validate(item.model_dump(mode="python")) for item in assertions
    )
    if tuple(
        item.field_key for item in exact_assertions
    ) != profile.ordered_field_keys or input_authority.claim_set_sha256 != claim_input_set_sha256(
        candidate_sha256=input_authority.candidate_sha256,
        product_version_id=input_authority.product_version_id,
        assertions=exact_assertions,
    ):
        raise EntityPageGraphError("FIELD_ASSERTION_INPUT_INVALID")

    section_page_ids = tuple(
        _page_id(context=context, page_kind="section", stable_key=item.section_key)
        for item in profile.sections
    )
    references = tuple(
        FieldAssertionReferenceV1(
            field_key=item.field_key,
            page_id=_page_id(context=context, page_kind="field", stable_key=item.field_key),
            source_release_id=context.release_id,
            source_candidate_sha256=input_authority.candidate_sha256,
            product_version_id=input_authority.product_version_id,
            claim_sha256=field_claim_sha256(
                source_release_id=context.release_id,
                source_candidate_sha256=input_authority.candidate_sha256,
                product_version_id=input_authority.product_version_id,
                field_id=item.field_key,
                state=item.state,
                value_snapshot=item.value_snapshot,
            ),
            evidence_receipt_sha256s=item.evidence_receipt_sha256s,
            citation_sha256s=tuple(citation.citation_sha256 for citation in item.citations),
        )
        for item in exact_assertions
    )
    reference_by_field = {item.field_key: item for item in references}
    input_by_field = {item.field_key: item for item in exact_assertions}

    members: list[EntityPageMemberV1] = [
        _member(
            context=context,
            profile=profile,
            input_authority=input_authority,
            page_kind="overview",
            stable_key="overview",
            short_title=context.display_name,
            payload=EntityOverviewPayloadV1(
                contract="entity-overview-page.830.g1.v1",
                entity_id=context.entity_id,
                entity_version_id=context.entity_version_id,
                ordered_section_page_ids=section_page_ids,
                field_assertions=references,
            ),
        )
    ]
    members.extend(
        _member(
            context=context,
            profile=profile,
            input_authority=input_authority,
            page_kind="section",
            stable_key=section.section_key,
            short_title=section.display_name,
            payload=EntitySectionPayloadV1(
                contract="entity-section-page.830.g1.v1",
                section_key=section.section_key,
                field_assertions=tuple(
                    reference_by_field[item.field_key] for item in section.fields
                ),
            ),
        )
        for section in profile.sections
    )
    short_title_by_field = {
        item.field_key: item.short_title for section in profile.sections for item in section.fields
    }
    members.extend(
        _member(
            context=context,
            profile=profile,
            input_authority=input_authority,
            page_kind="field",
            stable_key=field_key,
            short_title=short_title_by_field[field_key],
            payload=FieldAssertionPayloadV1(
                contract="field-assertion-page.830.g1.v1",
                field_key=field_key,
                reference=reference_by_field[field_key],
                state=input_by_field[field_key].state,
                value_snapshot=input_by_field[field_key].value_snapshot,
                display_value=input_by_field[field_key].value_snapshot,
                unknown_reason=input_by_field[field_key].unknown_reason,
                source_typed_reason=input_by_field[field_key].source_typed_reason,
                citations=input_by_field[field_key].citations,
            ),
        )
        for field_key in profile.ordered_field_keys
    )
    members.append(
        _member(
            context=context,
            profile=profile,
            input_authority=input_authority,
            page_kind="free_wiki",
            stable_key="free-wiki",
            short_title="自由知识",
            payload=EmptyFreeWikiPayloadV1(contract="empty-free-wiki-page.830.g1.v1", items=()),
        )
    )
    counts = Counter(item.state for item in exact_assertions)
    manifest_payload = {
        "contract": "entity-page-manifest.830.g1.v1",
        "release_id": context.release_id,
        "activation_epoch": context.activation_epoch,
        "space_id": context.space_id,
        "wiki_kb_id": context.wiki_kb_id,
        "entity_id": context.entity_id,
        "entity_version_id": context.entity_version_id,
        "display_name": context.display_name,
        "classification_display_name": context.classification_display_name,
        "profile": profile,
        "input_authority": input_authority,
        "authority": EntityPageAuthorityV1(),
        "members": tuple(members),
        "section_count": len(profile.sections),
        "field_assertion_count": len(exact_assertions),
        "state_distribution": TriStateDistributionV1(
            present=counts["present"],
            absent_explicitly=counts["absent_explicitly"],
            unknown=counts["unknown"],
        ),
        "field_assertion_page_ids": tuple(
            item.page_id for item in members if item.page_kind == "field"
        ),
        "free_wiki_empty": True,
    }
    return EntityPageManifestV1.model_validate(
        {
            **manifest_payload,
            "manifest_sha256": schema_wiki_sha256(
                "entity-page-manifest.830.g1.v1", manifest_payload
            ),
        }
    )


def _decode_object(data: bytes, reason: str) -> dict[str, object]:
    try:
        decoded = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise EntityPageGraphError(reason) from None
    if type(decoded) is not dict:
        raise EntityPageGraphError(reason)
    return cast(dict[str, object], decoded)


def _expect(actual: object, expected: object | None, reason: str) -> None:
    if expected is not None and actual != expected:
        raise EntityPageGraphError(reason)


def _manifest_member_hash(manifest: Mapping[str, object], name: str) -> str | None:
    members = manifest.get("members")
    if type(members) is not list:
        return None
    matches = [
        item.get("sha256") for item in members if type(item) is dict and item.get("name") == name
    ]
    return cast(str | None, matches[0] if len(matches) == 1 else None)


def _actual_assertions(
    *,
    candidate: Mapping[str, object],
    authority: Schema67CandidateEvidenceAuthorityV1,
    preview: Mapping[str, object],
) -> tuple[FieldAssertionInputV1, ...]:
    fields_wire = candidate.get("fields")
    receipts_wire = candidate.get("evidence_receipts")
    preview_fields_wire = preview.get("fields")
    if (
        type(fields_wire) is not list
        or type(receipts_wire) is not list
        or type(preview_fields_wire) is not list
    ):
        raise EntityPageGraphError("ACTUAL_CANDIDATE_INVALID")
    try:
        fields = tuple(FreeformFieldOutputV1.model_validate(item) for item in fields_wire)
        receipts = tuple(
            FreeformEvidenceBindingReceiptV1.model_validate(item) for item in receipts_wire
        )
    except (TypeError, ValueError, ValidationError):
        raise EntityPageGraphError("ACTUAL_CANDIDATE_INVALID") from None
    joins = iter(authority.join_receipts)
    assertions: list[FieldAssertionInputV1] = []
    for field, receipt, preview_field in zip(fields, receipts, preview_fields_wire, strict=True):
        if type(preview_field) is not dict:
            raise EntityPageGraphError("ACTUAL_PREVIEW_INVALID")
        preview_state = preview_field.get("state")
        if preview_state == "absent":
            preview_state = "absent_explicitly"
        source_typed_reason = preview_field.get("typed_reason")
        if (
            preview_field.get("field_id") != field.field_id
            or preview_state != field.state
            or preview_field.get("value_snapshot") != field.value_snapshot
            or (
                field.state == "unknown"
                and (type(source_typed_reason) is not str or not source_typed_reason)
            )
            or (field.state != "unknown" and source_typed_reason is not None)
        ):
            raise EntityPageGraphError("ACTUAL_PREVIEW_INVALID")
        if (
            receipt.field_id != field.field_id
            or receipt.state != field.state
            or receipt.value_snapshot != field.value_snapshot
            or receipt.evidence != field.evidence
        ):
            raise EntityPageGraphError("ACTUAL_EVIDENCE_BINDING_INVALID")
        citations: list[ExactCitationV1] = []
        for evidence in field.evidence:
            try:
                join = next(joins)
            except StopIteration:
                raise EntityPageGraphError("ACTUAL_EVIDENCE_AUTHORITY_INVALID") from None
            quote_sha256 = schema_wiki_sha256(
                "schema-wiki-text.v1", {"text": evidence.quote_snapshot}
            )
            if (
                join.candidate_sha256 != authority.candidate_sha256
                or join.field_id != field.field_id
                or join.evidence_receipt_sha256 != receipt.receipt_hash
                or join.source_sha256 != evidence.source_sha256
                or join.parsed_document_sha256 != evidence.parsed_document_hash
                or join.parse_manifest_sha256 != evidence.parse_manifest_hash
                or join.evidence_parse_attempt_id != evidence.parse_attempt_id
                or join.locator_ref != evidence.locator.subject_ref
                or join.page_number != evidence.page_number
                or join.locator_content_sha256 != evidence.locator.content_snapshot_sha256
                or join.quote_sha256 != quote_sha256
                or join.live_revision_source_receipt.revision_source_id
                != evidence.source_revision_id
            ):
                raise EntityPageGraphError("ACTUAL_EVIDENCE_AUTHORITY_INVALID")
            citation_payload = {
                "contract": "entity-page-exact-citation.830.g1.v1",
                "citation_id": f"citation_{join.receipt_sha256}",
                "join_receipt_sha256": join.receipt_sha256,
                "evidence_receipt_sha256": receipt.receipt_hash,
                "source_role": join.source_role,
                "source_sha256": join.source_sha256,
                "source_revision_id": evidence.source_revision_id,
                "knowledge_id": join.knowledge_id,
                "chunk_id": join.chunk_id,
                "parse_attempt_id": join.evidence_parse_attempt_id,
                "parsed_document_sha256": join.parsed_document_sha256,
                "parse_manifest_sha256": join.parse_manifest_sha256,
                "page_number": join.page_number,
                "locator_kind": join.locator_kind,
                "locator_ref": join.locator_ref,
                "locator_content_sha256": join.locator_content_sha256,
                "bbox": join.normalized_bbox,
                "quote_snapshot": evidence.quote_snapshot,
                "quote_sha256": quote_sha256,
            }
            citations.append(
                ExactCitationV1.model_validate(
                    {
                        **citation_payload,
                        "citation_sha256": schema_wiki_sha256(
                            "entity-page-exact-citation.830.g1.v1",
                            citation_payload,
                        ),
                    }
                )
            )
        assertions.append(
            FieldAssertionInputV1(
                field_key=field.field_id,
                state=field.state,
                value_snapshot=field.value_snapshot,
                unknown_reason="FIELD_UNKNOWN" if field.state == "unknown" else None,
                source_typed_reason=cast(str, source_typed_reason)
                if field.state == "unknown"
                else None,
                evidence_receipt_sha256s=(receipt.receipt_hash,)
                if field.state != "unknown"
                else (),
                citations=tuple(citations),
            )
        )
    try:
        next(joins)
    except StopIteration:
        return tuple(assertions)
    raise EntityPageGraphError("ACTUAL_EVIDENCE_AUTHORITY_INVALID")


def _compile_actual_815_entity_page_manifest_unchecked(
    *,
    candidate_bytes: bytes,
    evidence_authority_bytes: bytes,
    bundle_manifest_bytes: bytes,
    preview_bytes: bytes,
    profile_bytes: bytes,
    context: EntityPageCompileContextV1,
) -> EntityPageManifestV1:
    """Validate the frozen 815 files and compile their deterministic G1 graph."""

    candidate = _decode_object(candidate_bytes, "ACTUAL_CANDIDATE_INVALID")
    bundle = _decode_object(bundle_manifest_bytes, "ACTUAL_BUNDLE_MANIFEST_INVALID")
    preview = _decode_object(preview_bytes, "ACTUAL_PREVIEW_INVALID")
    candidate_file_sha256 = sha256_hex(candidate_bytes)
    authority_file_sha256 = sha256_hex(evidence_authority_bytes)
    bundle_file_sha256 = sha256_hex(bundle_manifest_bytes)
    preview_file_sha256 = sha256_hex(preview_bytes)
    profile_file_sha256 = sha256_hex(profile_bytes)
    _expect(candidate_file_sha256, context.expected_candidate_file_sha256, "ACTUAL_FILE_HASH_DRIFT")
    _expect(
        authority_file_sha256,
        context.expected_evidence_authority_file_sha256,
        "ACTUAL_FILE_HASH_DRIFT",
    )
    _expect(
        bundle_file_sha256,
        context.expected_bundle_manifest_file_sha256,
        "ACTUAL_FILE_HASH_DRIFT",
    )
    _expect(preview_file_sha256, context.expected_preview_file_sha256, "ACTUAL_FILE_HASH_DRIFT")
    _expect(profile_file_sha256, context.expected_profile_file_sha256, "ACTUAL_FILE_HASH_DRIFT")
    try:
        profile = PresentationProfileV1.model_validate_json(profile_bytes)
        authority = Schema67CandidateEvidenceAuthorityV1.model_validate_json(
            evidence_authority_bytes
        )
    except (TypeError, ValueError, ValidationError):
        raise EntityPageGraphError("ACTUAL_CONTRACT_INVALID") from None

    candidate_sha256 = candidate.get("candidate_sha256")
    if type(candidate_sha256) is not str:
        raise EntityPageGraphError("ACTUAL_CANDIDATE_INVALID")
    candidate_preimage = dict(candidate)
    candidate_preimage.pop("candidate_sha256", None)
    if candidate_sha256 != canonical_hash("schema67-candidate.v2", candidate_preimage):
        raise EntityPageGraphError("ACTUAL_CANDIDATE_INVALID")
    _expect(candidate_sha256, context.expected_candidate_sha256, "ACTUAL_IDENTITY_DRIFT")
    _expect(
        authority.authority_sha256,
        context.expected_evidence_authority_sha256,
        "ACTUAL_IDENTITY_DRIFT",
    )
    _expect(profile.profile_sha256, context.expected_profile_sha256, "ACTUAL_IDENTITY_DRIFT")
    if authority.candidate_sha256 != candidate_sha256:
        raise EntityPageGraphError("ACTUAL_EVIDENCE_AUTHORITY_INVALID")

    assertions = _actual_assertions(candidate=candidate, authority=authority, preview=preview)
    ordered_field_ids = candidate.get("ordered_field_ids")
    product_version_id = candidate.get("product_version_id")
    if (
        type(ordered_field_ids) is not list
        or tuple(ordered_field_ids) != profile.ordered_field_keys
        or tuple(item.field_key for item in assertions) != profile.ordered_field_keys
        or type(product_version_id) is not str
    ):
        raise EntityPageGraphError("ACTUAL_PROFILE_BINDING_INVALID")
    claim_set_sha256 = claim_input_set_sha256(
        candidate_sha256=candidate_sha256,
        product_version_id=product_version_id,
        assertions=assertions,
    )
    receipts_wire = candidate.get("evidence_receipts")
    if type(receipts_wire) is not list:
        raise EntityPageGraphError("ACTUAL_CANDIDATE_INVALID")
    evidence_set_payload = {
        "contract": "g1-evidence-receipt-input-set.v1",
        "candidate_sha256": candidate_sha256,
        "evidence_receipts": tuple(receipts_wire),
    }
    evidence_set_sha256 = schema_wiki_sha256(
        "g1-evidence-receipt-input-set.v1", evidence_set_payload
    )
    _expect(claim_set_sha256, context.expected_claim_set_sha256, "ACTUAL_IDENTITY_DRIFT")
    _expect(
        evidence_set_sha256,
        context.expected_evidence_receipt_set_sha256,
        "ACTUAL_IDENTITY_DRIFT",
    )

    bundle_sha256 = bundle.get("manifest_sha256")
    preview_sha256 = preview.get("preview_sha256")
    _expect(bundle_sha256, context.expected_bundle_manifest_sha256, "ACTUAL_IDENTITY_DRIFT")
    _expect(preview_sha256, context.expected_preview_sha256, "ACTUAL_IDENTITY_DRIFT")
    if (
        bundle.get("candidate_sha256") != candidate_sha256
        or bundle.get("candidate_file_sha256") != candidate_file_sha256
        or bundle.get("candidate_evidence_authority_sha256") != authority.authority_sha256
        or bundle.get("candidate_evidence_authority_file_sha256") != authority_file_sha256
        or _manifest_member_hash(bundle, "formal-candidate.json") != candidate_file_sha256
        or _manifest_member_hash(bundle, "candidate-evidence-authority.json")
        != authority_file_sha256
        or _manifest_member_hash(bundle, "preview.json") != preview_file_sha256
        or preview.get("candidate_sha256") != candidate_sha256
        or tuple(cast(list[object], preview.get("ordered_section_ids")))
        != tuple(item.section_key for item in profile.sections)
    ):
        raise EntityPageGraphError("ACTUAL_BUNDLE_CUSTODY_INVALID")

    product = preview.get("product")
    if type(product) is not dict or (
        product.get("entity_id"),
        product.get("entity_version_id"),
        product.get("product_version_id"),
    ) != (context.entity_id, context.entity_version_id, product_version_id):
        raise EntityPageGraphError("ACTUAL_ENTITY_BINDING_INVALID")
    source_authorities = tuple(
        ManifestSourceAuthorityV1(
            source_role=item.source_role,
            source_sha256=item.source_sha256,
            knowledge_id=item.live_revision_source_receipt.knowledge_id,
            resource_id=item.live_revision_source_receipt.resource_id,
            revision_source_id=item.live_revision_source_receipt.revision_source_id,
            evidence_parse_attempt_id=(item.live_revision_source_receipt.evidence_parse_attempt_id),
            weknora_parse_attempt=item.live_revision_source_receipt.weknora_parse_attempt,
            parsed_document_sha256=(item.live_revision_source_receipt.parsed_document_sha256),
            parse_manifest_sha256=item.live_revision_source_receipt.parse_manifest_sha256,
            source_receipt_sha256=item.live_revision_source_receipt.source_receipt_sha256,
        )
        for item in authority.source_authorities
    )
    input_authority = ManifestInputAuthorityV1(
        candidate_contract=cast(str, candidate.get("contract")),
        candidate_sha256=candidate_sha256,
        candidate_file_sha256=candidate_file_sha256,
        product_version_id=product_version_id,
        claim_set_sha256=claim_set_sha256,
        evidence_receipt_set_sha256=evidence_set_sha256,
        evidence_authority_contract=authority.contract,
        evidence_authority_sha256=authority.authority_sha256,
        evidence_authority_file_sha256=authority_file_sha256,
        source_authorities=source_authorities,
        actual_files=ActualInputFilesV1(
            bundle_manifest_contract=cast(str, bundle.get("contract")),
            bundle_manifest_sha256=cast(str, bundle_sha256),
            bundle_manifest_file_sha256=bundle_file_sha256,
            preview_contract=cast(str, preview.get("contract")),
            preview_sha256=cast(str, preview_sha256),
            preview_file_sha256=preview_file_sha256,
            profile_file_sha256=profile_file_sha256,
        ),
    )
    return compile_entity_page_manifest(
        context=context,
        profile=profile,
        input_authority=input_authority,
        assertions=assertions,
    )


def compile_actual_815_entity_page_manifest(
    *,
    candidate_bytes: bytes,
    evidence_authority_bytes: bytes,
    bundle_manifest_bytes: bytes,
    preview_bytes: bytes,
    profile_bytes: bytes,
    context: EntityPageCompileContextV1,
) -> EntityPageManifestV1:
    """Validate frozen 815 JSON and normalize every drift failure."""

    try:
        return _compile_actual_815_entity_page_manifest_unchecked(
            candidate_bytes=candidate_bytes,
            evidence_authority_bytes=evidence_authority_bytes,
            bundle_manifest_bytes=bundle_manifest_bytes,
            preview_bytes=preview_bytes,
            profile_bytes=profile_bytes,
            context=context,
        )
    except EntityPageGraphError:
        raise
    except (AttributeError, KeyError, TypeError, ValueError, ValidationError):
        raise EntityPageGraphError("ACTUAL_CONTRACT_INVALID") from None


__all__ = [
    "ActualInputFilesV1",
    "EmptyFreeWikiPayloadV1",
    "EntityPageCompileContextV1",
    "EntityPageGraphError",
    "EntityPageManifestV1",
    "ExactCitationV1",
    "FieldAssertionInputV1",
    "FieldAssertionPayloadV1",
    "ManifestInputAuthorityV1",
    "ManifestSourceAuthorityV1",
    "PresentationProfileV1",
    "claim_input_set_sha256",
    "compile_actual_815_entity_page_manifest",
    "compile_entity_page_manifest",
    "field_claim_sha256",
    "sha256_hex",
]
