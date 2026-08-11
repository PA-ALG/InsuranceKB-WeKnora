"""Lane A1 contract tests for the Schema Wiki release foundation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel, ValidationError

from insurance_harness.knowledge_compiler.schema_wiki_contracts import (
    CitationBBoxV1,
    CitationMemberBindingV1,
    CitationTargetV1,
    EntityIdentityV1,
    EntityVersionV1,
    KnowledgeDomainV1,
    KnowledgeWikiReleaseV1,
    Schema67GoldenQualityGateReceiptV1,
    SchemaFieldPageV1,
    SchemaPackV1,
    SchemaRootPageV1,
    SchemaSectionPageV1,
    SchemaSectionV1,
    SchemaWikiContractError,
    SchemaWikiMemberV1,
    SchemaWikiReviewBundleV1,
    TaxonomyNodeV1,
    TaxonomyRedirectV1,
    TaxonomySnapshotV1,
    schema_wiki_canonical_bytes,
    schema_wiki_manifest_digest,
    schema_wiki_sha256,
    validate_citation_target,
    validate_knowledge_wiki_release,
    validate_schema_pack,
    validate_schema_wiki_review_bundle,
    validate_taxonomy_snapshot,
)


def _sha(label: str) -> str:
    return schema_wiki_sha256("schema-wiki-test-label.v1", {"label": label})


def _sealed[ModelT: BaseModel](
    model: type[ModelT], object_type: str, hash_field: str, **payload: object
) -> ModelT:
    return model.model_validate(
        {
            **payload,
            hash_field: schema_wiki_sha256(object_type, payload),
        }
    )


def _domain() -> KnowledgeDomainV1:
    return _sealed(
        KnowledgeDomainV1,
        "knowledge-domain.v1",
        "domain_sha256",
        contract="knowledge-domain.v1",
        domain_id="synthetic-domain",
        display_name="Synthetic Domain",
    )


def _taxonomy(
    *,
    version: str = "taxonomy-v1",
    nodes: tuple[TaxonomyNodeV1, ...] | None = None,
    redirects: tuple[TaxonomyRedirectV1, ...] = (),
    previous_sha256: str | None = None,
) -> TaxonomySnapshotV1:
    chosen_nodes = nodes or (
        TaxonomyNodeV1(
            node_id="category-root",
            parent_node_id=None,
            node_kind="category",
            slug="root",
            stable_entity_id=None,
            position=0,
        ),
        TaxonomyNodeV1(
            node_id="entity-alpha",
            parent_node_id="category-root",
            node_kind="entity",
            slug="alpha",
            stable_entity_id="entity-alpha",
            position=0,
        ),
    )
    payload = {
        "contract": "taxonomy-snapshot.v1",
        "domain_id": "synthetic-domain",
        "taxonomy_version": version,
        "previous_snapshot_sha256": previous_sha256,
        "nodes": chosen_nodes,
        "redirects": redirects,
    }
    return _sealed(
        TaxonomySnapshotV1,
        "taxonomy-snapshot.v1",
        "taxonomy_sha256",
        **payload,
    )


def _pack() -> SchemaPackV1:
    sections = (
        SchemaSectionV1(
            section_id="section-a",
            display_name="Section A",
            ordered_field_ids=("field-a", "field-b"),
        ),
        SchemaSectionV1(
            section_id="section-b",
            display_name="Section B",
            ordered_field_ids=("field-c",),
        ),
    )
    payload = {
        "contract": "schema-pack.v1",
        "schema_pack_id": "synthetic-schema.v1",
        "schema_version": "v1",
        "domain_id": "synthetic-domain",
        "ordered_field_ids": ("field-a", "field-b", "field-c"),
        "sections": sections,
    }
    return _sealed(
        SchemaPackV1,
        "schema-pack.v1",
        "schema_pack_sha256",
        **payload,
    )


def _citation(*, member_ref: str = "field:field-a") -> CitationTargetV1:
    bbox = CitationBBoxV1(
        coordinate_system="pdf_points",
        page_width=600,
        page_height=800,
        x0=100,
        y0=120,
        x1=360,
        y1=180,
    )
    quote = "Synthetic exact quote"
    payload = {
        "contract": "citation-target.v1",
        "citation_id": "citation-a",
        "source_role": "terms",
        "space_id": "space-a",
        "entity_version_id": "entity-alpha@v1",
        "knowledge_id": "knowledge-a",
        "chunk_id": "chunk-a",
        "source_revision_id": "revision-a",
        "parse_attempt_id": "attempt-a",
        "parsed_document_sha256": _sha("document-a"),
        "parse_manifest_sha256": _sha("manifest-a"),
        "page_number": 12,
        "locator_ref": "block-a",
        "bbox": bbox,
        "quote_snapshot": quote,
        "quote_sha256": schema_wiki_sha256("schema-wiki-text.v1", {"text": quote}),
        "content_snapshot_sha256": _sha("content-a"),
        "logical_member_ref": member_ref,
    }
    return _sealed(
        CitationTargetV1,
        "citation-target.v1",
        "citation_sha256",
        **payload,
    )


def _field_page(
    *,
    field_id: str = "field-a",
    state: str = "present",
    citation: CitationTargetV1 | None = None,
) -> SchemaFieldPageV1:
    citations: tuple[CitationTargetV1, ...]
    if state == "present":
        value = "Synthetic value"
        citations = (citation or _citation(),)
        review_reason = None
    elif state == "absent_explicitly":
        value = "Not applicable under the cited clause"
        citations = (citation or _citation(),)
        review_reason = None
    else:
        value = None
        citations = ()
        review_reason = "FIELD_UNKNOWN"
    payload = {
        "contract": "schema-field-page.v1",
        "field_id": field_id,
        "state": state,
        "value_snapshot": value,
        "citations": citations,
        "evidence_receipt_sha256s": (_sha("evidence-receipt-a"),) if state != "unknown" else (),
        "review_item_reason": review_reason,
    }
    return _sealed(
        SchemaFieldPageV1,
        "schema-field-page.v1",
        "field_page_sha256",
        **payload,
    )


def _root_page(pack: SchemaPackV1 | None = None) -> SchemaRootPageV1:
    domain = _domain()
    chosen_pack = pack or _pack()
    taxonomy = _taxonomy()
    payload = {
        "contract": "schema-root-page.v1",
        "domain_id": domain.domain_id,
        "domain_sha256": domain.domain_sha256,
        "schema_pack_id": chosen_pack.schema_pack_id,
        "schema_version": chosen_pack.schema_version,
        "schema_pack_sha256": chosen_pack.schema_pack_sha256,
        "entity_id": "entity-alpha",
        "entity_version_id": "entity-alpha@v1",
        "product_version_id": "product-v1",
        "taxonomy_version": taxonomy.taxonomy_version,
        "taxonomy_sha256": taxonomy.taxonomy_sha256,
        "product_display_name": "Synthetic Product",
        "ordered_section_ids": tuple(row.section_id for row in chosen_pack.sections),
    }
    return _sealed(
        SchemaRootPageV1,
        "schema-root-page.v1",
        "root_page_sha256",
        **payload,
    )


def _section_page(section_id: str, pack: SchemaPackV1 | None = None) -> SchemaSectionPageV1:
    domain = _domain()
    chosen_pack = pack or _pack()
    taxonomy = _taxonomy()
    section = next(row for row in chosen_pack.sections if row.section_id == section_id)
    payload = {
        "contract": "schema-section-page.v1",
        "domain_id": domain.domain_id,
        "domain_sha256": domain.domain_sha256,
        "schema_pack_id": chosen_pack.schema_pack_id,
        "schema_version": chosen_pack.schema_version,
        "schema_pack_sha256": chosen_pack.schema_pack_sha256,
        "entity_id": "entity-alpha",
        "entity_version_id": "entity-alpha@v1",
        "product_version_id": "product-v1",
        "taxonomy_version": taxonomy.taxonomy_version,
        "taxonomy_sha256": taxonomy.taxonomy_sha256,
        "section_id": section.section_id,
        "display_name": section.display_name,
        "ordered_field_ids": section.ordered_field_ids,
    }
    return _sealed(
        SchemaSectionPageV1,
        "schema-section-page.v1",
        "section_page_sha256",
        **payload,
    )


def _member(
    member_ref: str,
    kind: str,
    *,
    section_id: str | None = None,
    field_id: str | None = None,
    payload: SchemaRootPageV1 | SchemaSectionPageV1 | SchemaFieldPageV1 | None = None,
) -> SchemaWikiMemberV1:
    if payload is None:
        if kind == "root":
            payload = _root_page()
        elif kind == "section":
            assert section_id is not None
            payload = _section_page(section_id)
        else:
            assert field_id is not None
            payload = _field_page(
                field_id=field_id,
                state="present" if field_id == "field-a" else "unknown",
                citation=_citation() if field_id == "field-a" else None,
            )
    page = payload
    if isinstance(page, SchemaRootPageV1):
        payload_sha256 = page.root_page_sha256
    elif isinstance(page, SchemaSectionPageV1):
        payload_sha256 = page.section_page_sha256
    else:
        payload_sha256 = page.field_page_sha256
    member_payload = {
        "contract": "schema-wiki-member.v1",
        "member_ref": member_ref,
        "member_kind": kind,
        "section_id": section_id,
        "field_id": field_id,
        "payload": page,
        "payload_sha256": payload_sha256,
    }
    return _sealed(
        SchemaWikiMemberV1,
        "schema-wiki-member.v1",
        "member_digest",
        **member_payload,
    )


def _binding(citation: CitationTargetV1, member: SchemaWikiMemberV1) -> CitationMemberBindingV1:
    payload = {
        "contract": "citation-member-binding.v1",
        "citation_sha256": citation.citation_sha256,
        "logical_member_ref": citation.logical_member_ref,
        "member_digest": member.member_digest,
    }
    return _sealed(
        CitationMemberBindingV1,
        "citation-member-binding.v1",
        "binding_sha256",
        **payload,
    )


def _release(
    *,
    pack: SchemaPackV1 | None = None,
    members: tuple[SchemaWikiMemberV1, ...] | None = None,
    bindings: tuple[CitationMemberBindingV1, ...] | None = None,
    state: str = "draft",
) -> KnowledgeWikiReleaseV1:
    domain = _domain()
    taxonomy = _taxonomy()
    chosen_pack = pack or _pack()
    entity = EntityIdentityV1(
        domain_id=domain.domain_id,
        entity_id="entity-alpha",
    )
    version = EntityVersionV1(
        entity_id=entity.entity_id,
        version_id="entity-alpha@v1",
        product_version_id="product-v1",
    )
    citation = _citation()
    field_page = _field_page(citation=citation)
    chosen_members = members or (
        _member("root:entity-alpha@v1", "root", payload=_root_page(chosen_pack)),
        _member(
            "section:section-a",
            "section",
            section_id="section-a",
            payload=_section_page("section-a", chosen_pack),
        ),
        _member(
            "section:section-b",
            "section",
            section_id="section-b",
            payload=_section_page("section-b", chosen_pack),
        ),
        _member(
            "field:field-a",
            "field",
            section_id="section-a",
            field_id="field-a",
            payload=field_page,
        ),
        _member(
            "field:field-b",
            "field",
            section_id="section-a",
            field_id="field-b",
        ),
        _member(
            "field:field-c",
            "field",
            section_id="section-b",
            field_id="field-c",
        ),
    )
    field_member = next(row for row in chosen_members if row.member_ref == "field:field-a")
    chosen_bindings = bindings if bindings is not None else (_binding(citation, field_member),)
    payload = {
        "contract": "knowledge-wiki-release.v1",
        "release_state": state,
        "domain": domain,
        "taxonomy": taxonomy,
        "schema_pack": chosen_pack,
        "entity": entity,
        "entity_version": version,
        "candidate_sha256": _sha("candidate"),
        "review_policy_sha256": _sha("review-policy"),
        "members": chosen_members,
        "citation_bindings": chosen_bindings,
        "manifest_digest": schema_wiki_manifest_digest(chosen_members, chosen_bindings),
    }
    return _sealed(
        KnowledgeWikiReleaseV1,
        "knowledge-wiki-release.v1",
        "release_sha256",
        **payload,
    )


def _rehashed[ModelT: BaseModel](
    model: ModelT, object_type: str, hash_field: str, **changes: object
) -> ModelT:
    payload: dict[str, object] = {
        key: value for key, value in model.__dict__.items() if key != hash_field
    }
    payload.update(changes)
    values = {
        **payload,
        hash_field: schema_wiki_sha256(object_type, payload),
    }
    return type(model).model_construct(**cast(Any, values))


def _review_bundle(release: KnowledgeWikiReleaseV1) -> SchemaWikiReviewBundleV1:
    quality_payload = {
        "contract": "schema67-golden-quality-gate-receipt.v1",
        "status": "PASS",
        "product_version_id": "596-1",
        "candidate_sha256": release.candidate_sha256,
        "candidate_evidence_authority_sha256": _sha("evidence-authority"),
        "golden_set_sha256": _sha("golden-set"),
        "golden_version": "test.v1",
        "evaluator_identity_sha256": (
            "525f208a404d996caf5f806a9b065ea5af81f0b7d2996b9b50c25e4878400808"
        ),
        "metric_policy_sha256": (
            "5d2ffd2379f9f1902a0ab834de6e1e8e593d400115878b9c565331b121d6f0d7"
        ),
        "ordered_field_decision_sha256s": tuple(_sha(f"field-{index}") for index in range(67)),
        "metric_receipt_sha256s": tuple(_sha(f"metric-{index}") for index in range(15)),
        "private_dossier_sha256": _sha("private-dossier"),
        "public_aggregate_sha256": _sha("public-aggregate"),
        "golden_approval_sha256s": (
            _sha("golden-approval-a"),
            _sha("golden-approval-b"),
        ),
        "signer_key_id": "test-golden-evaluator",
        "signature": "test-only-signature",
    }
    quality = _sealed(
        Schema67GoldenQualityGateReceiptV1,
        "schema67-golden-quality-gate-receipt.v1",
        "receipt_sha256",
        **quality_payload,
    )
    payload = {
        "contract": "schema-wiki-review-bundle.v1",
        "candidate_sha256": release.candidate_sha256,
        "release_sha256": release.release_sha256,
        "manifest_digest": release.manifest_digest,
        "ordered_member_digests": tuple(row.member_digest for row in release.members),
        "ordered_binding_sha256s": tuple(row.binding_sha256 for row in release.citation_bindings),
        "review_policy_sha256": release.review_policy_sha256,
        "domain_sha256": release.domain.domain_sha256,
        "taxonomy_sha256": release.taxonomy.taxonomy_sha256,
        "schema_pack_sha256": release.schema_pack.schema_pack_sha256,
        "entity_id": release.entity.entity_id,
        "version_id": release.entity_version.version_id,
        "quality_gate_receipt": quality,
    }
    return _sealed(
        SchemaWikiReviewBundleV1,
        "schema-wiki-review-bundle.v1",
        "review_bundle_sha256",
        **payload,
    )


def test_models_are_closed_world_and_reject_noncanonical_or_self_rehashed_data() -> None:
    domain = _domain()
    with pytest.raises(ValidationError):
        KnowledgeDomainV1.model_validate({**domain.model_dump(), "extra": "forbidden"})

    release = validate_knowledge_wiki_release(_release(), _pack())
    reversed_members = tuple(reversed(release.members))
    forged = _rehashed(
        release,
        "knowledge-wiki-release.v1",
        "release_sha256",
        members=reversed_members,
    )
    with pytest.raises(SchemaWikiContractError, match="MEMBER_ORDER_INVALID"):
        validate_knowledge_wiki_release(forged, _pack())

    bad_hash = release.model_construct(
        **release.model_dump(mode="python", exclude={"release_sha256"}),
        release_sha256="f" * 64,
    )
    with pytest.raises(SchemaWikiContractError, match="RELEASE_CUSTODY_INVALID"):
        validate_knowledge_wiki_release(bad_hash, _pack())


def test_non_nfc_text_is_not_canonical() -> None:
    payload = {
        "contract": "knowledge-domain.v1",
        "domain_id": "synthetic-domain",
        "display_name": "Cafe\u0301",
    }
    with pytest.raises((ValidationError, ValueError)):
        _sealed(
            KnowledgeDomainV1,
            "knowledge-domain.v1",
            "domain_sha256",
            **payload,
        )


@pytest.mark.parametrize("codepoint", (*range(0x20), 0x7F))
def test_control_characters_are_not_canonical(codepoint: int) -> None:
    with pytest.raises(ValueError, match="control"):
        schema_wiki_canonical_bytes(
            "knowledge-domain.v1",
            {
                "contract": "knowledge-domain.v1",
                "domain_id": "synthetic-domain",
                "display_name": f"医疗险{chr(codepoint)}产品",
            },
        )


def test_normal_nfc_chinese_text_remains_canonical() -> None:
    preimage = schema_wiki_canonical_bytes(
        "knowledge-domain.v1",
        {
            "contract": "knowledge-domain.v1",
            "domain_id": "medical-insurance",
            "display_name": "医疗保险",
        },
    )
    assert "医疗保险".encode() in preimage


@pytest.mark.parametrize("problem", ["cycle", "orphan", "duplicate"])
def test_taxonomy_rejects_cycle_orphan_and_duplicate_nodes(problem: str) -> None:
    root = TaxonomyNodeV1(
        node_id="root",
        parent_node_id=None,
        node_kind="category",
        slug="root",
        stable_entity_id=None,
        position=0,
    )
    entity = TaxonomyNodeV1(
        node_id="entity",
        parent_node_id="root",
        node_kind="entity",
        slug="entity",
        stable_entity_id="entity-alpha",
        position=0,
    )
    nodes: tuple[TaxonomyNodeV1, ...]
    if problem == "cycle":
        nodes = (
            root.model_copy(update={"parent_node_id": "entity"}),
            entity.model_copy(update={"parent_node_id": "root"}),
        )
    elif problem == "orphan":
        nodes = (root, entity.model_copy(update={"parent_node_id": "missing"}))
    else:
        nodes = (root, entity, entity)
    with pytest.raises((ValidationError, SchemaWikiContractError)):
        validate_taxonomy_snapshot(_taxonomy(nodes=nodes))


def test_taxonomy_reparent_preserves_stable_entity_and_emits_redirect() -> None:
    before = validate_taxonomy_snapshot(_taxonomy())
    nodes = (
        TaxonomyNodeV1(
            node_id="category-new",
            parent_node_id=None,
            node_kind="category",
            slug="new-root",
            stable_entity_id=None,
            position=0,
        ),
        TaxonomyNodeV1(
            node_id="entity-alpha",
            parent_node_id="category-new",
            node_kind="entity",
            slug="alpha",
            stable_entity_id="entity-alpha",
            position=0,
        ),
    )
    after = _taxonomy(
        version="taxonomy-v2",
        nodes=nodes,
        redirects=(
            TaxonomyRedirectV1(
                from_path="/root/alpha",
                to_path="/new-root/alpha",
                stable_entity_id="entity-alpha",
            ),
        ),
        previous_sha256=before.taxonomy_sha256,
    )
    validated = validate_taxonomy_snapshot(after, previous=before)
    assert validated.nodes[1].stable_entity_id == "entity-alpha"


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "reordered"])
def test_schema_pack_requires_exact_ordered_field_partition(mutation: str) -> None:
    pack = _pack()
    sections = list(pack.sections)
    if mutation == "missing":
        sections[0] = sections[0].model_copy(update={"ordered_field_ids": ("field-a",)})
    elif mutation == "extra":
        sections[1] = sections[1].model_copy(update={"ordered_field_ids": ("field-c", "foreign")})
    elif mutation == "duplicate":
        sections[1] = sections[1].model_copy(update={"ordered_field_ids": ("field-a",)})
    else:
        sections.reverse()
    forged = _rehashed(
        pack,
        "schema-pack.v1",
        "schema_pack_sha256",
        sections=tuple(sections),
    )
    with pytest.raises(SchemaWikiContractError, match="SCHEMA_PACK_TOPOLOGY_INVALID"):
        validate_schema_pack(forged)


def test_shared_release_topology_is_derived_from_pack_not_medical_cardinality() -> None:
    pack = validate_schema_pack(_pack())
    release = validate_knowledge_wiki_release(_release(), pack)
    assert len(pack.sections) == 2
    assert len(pack.ordered_field_ids) == 3
    assert len(release.members) == 1 + 2 + 3


def test_citation_payload_closure_uses_canonical_key_not_nonlexical_field_order() -> None:
    base = _pack()
    sections = (
        base.sections[0].model_copy(update={"ordered_field_ids": ("field-b", "field-a")}),
        base.sections[1],
    )
    pack_payload = base.model_dump(mode="python", exclude={"schema_pack_sha256"})
    pack_payload["ordered_field_ids"] = ("field-b", "field-a", "field-c")
    pack_payload["sections"] = sections
    pack = _sealed(
        SchemaPackV1,
        "schema-pack.v1",
        "schema_pack_sha256",
        **pack_payload,
    )
    citation_a = _citation(member_ref="field:field-a")
    citation_b = _citation(member_ref="field:field-b")
    members = (
        _member("root:entity-alpha@v1", "root", payload=_root_page(pack)),
        _member(
            "section:section-a",
            "section",
            section_id="section-a",
            payload=_section_page("section-a", pack),
        ),
        _member(
            "section:section-b",
            "section",
            section_id="section-b",
            payload=_section_page("section-b", pack),
        ),
        _member(
            "field:field-b",
            "field",
            section_id="section-a",
            field_id="field-b",
            payload=_field_page(field_id="field-b", citation=citation_b),
        ),
        _member(
            "field:field-a",
            "field",
            section_id="section-a",
            field_id="field-a",
            payload=_field_page(field_id="field-a", citation=citation_a),
        ),
        _member(
            "field:field-c",
            "field",
            section_id="section-b",
            field_id="field-c",
            payload=_field_page(field_id="field-c", state="unknown"),
        ),
    )
    bindings = tuple(
        sorted(
            (
                _binding(citation_a, members[4]),
                _binding(citation_b, members[3]),
            ),
            key=lambda row: (row.logical_member_ref, row.citation_sha256),
        )
    )
    release = _release(pack=pack, members=members, bindings=bindings)

    validated = validate_knowledge_wiki_release(release, pack)
    assert tuple(row.field_id for row in validated.members[3:]) == (
        "field-b",
        "field-a",
        "field-c",
    )
    assert tuple(row.logical_member_ref for row in validated.citation_bindings) == (
        "field:field-a",
        "field:field-b",
    )


@pytest.mark.parametrize(
    ("state", "value", "citations", "review"),
    [
        ("present", None, (_citation(),), None),
        ("present", "value", (), None),
        ("absent_explicitly", "not applicable", (), None),
        ("unknown", "oracle", (), "FIELD_UNKNOWN"),
        ("unknown", None, (_citation(),), "FIELD_UNKNOWN"),
        ("unknown", None, (), None),
    ],
)
def test_field_page_tri_state_rules(
    state: str,
    value: str | None,
    citations: tuple[CitationTargetV1, ...],
    review: str | None,
) -> None:
    payload = {
        "contract": "schema-field-page.v1",
        "field_id": "field-a",
        "state": state,
        "value_snapshot": value,
        "citations": citations,
        "evidence_receipt_sha256s": (_sha("evidence-receipt-a"),) if state != "unknown" else (),
        "review_item_reason": review,
    }
    with pytest.raises(ValidationError):
        _sealed(
            SchemaFieldPageV1,
            "schema-field-page.v1",
            "field_page_sha256",
            **payload,
        )


def test_present_absent_and_unknown_valid_shapes() -> None:
    assert _field_page(state="present").state == "present"
    assert _field_page(state="absent_explicitly").state == "absent_explicitly"
    unknown = _field_page(state="unknown")
    assert unknown.value_snapshot is None
    assert unknown.citations == ()
    assert unknown.evidence_receipt_sha256s == ()


@pytest.mark.parametrize("state", ["present", "absent_explicitly"])
def test_known_field_requires_replayed_057_receipt_identity(state: str) -> None:
    page = _field_page(state=state)
    payload = page.model_dump(mode="python", exclude={"field_page_sha256"})
    payload["evidence_receipt_sha256s"] = ()
    payload["field_page_sha256"] = schema_wiki_sha256("schema-field-page.v1", payload)
    with pytest.raises(ValidationError):
        SchemaFieldPageV1.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("page_number", 0),
        ("page_number", None),
        ("parsed_document_sha256", "f" * 64),
        ("parse_manifest_sha256", "e" * 64),
        ("source_revision_id", "foreign-revision"),
        ("space_id", "foreign-space"),
        ("entity_version_id", "foreign-version"),
        ("chunk_id", "foreign-chunk"),
        ("parse_attempt_id", "foreign-attempt"),
        ("locator_ref", "foreign-locator"),
        ("quote_snapshot", "drifted quote"),
        ("content_snapshot_sha256", "d" * 64),
    ],
)
def test_citation_identity_and_content_drift_fail_closed(field: str, value: object) -> None:
    citation = _citation()
    payload: dict[str, object] = citation.model_dump(mode="python", exclude={"citation_sha256"})
    payload[field] = value
    if field == "quote_snapshot":
        payload["quote_sha256"] = schema_wiki_sha256("schema-wiki-text.v1", {"text": value})
    payload["citation_sha256"] = schema_wiki_sha256("citation-target.v1", payload)
    with pytest.raises((ValidationError, SchemaWikiContractError)):
        changed = CitationTargetV1.model_validate(payload)
        validate_citation_target(
            changed,
            expected_space_id=citation.space_id,
            expected_entity_version_id=citation.entity_version_id,
            expected_knowledge_id=citation.knowledge_id,
            expected_chunk_id=citation.chunk_id,
            expected_source_revision_id=citation.source_revision_id,
            expected_parse_attempt_id=citation.parse_attempt_id,
            expected_parsed_document_sha256=citation.parsed_document_sha256,
            expected_parse_manifest_sha256=citation.parse_manifest_sha256,
            expected_page_number=citation.page_number,
            expected_locator_ref=citation.locator_ref,
            expected_quote_snapshot=citation.quote_snapshot,
            expected_content_snapshot_sha256=citation.content_snapshot_sha256,
        )


@pytest.mark.parametrize(
    "bbox",
    [
        None,
        {
            "coordinate_system": "pdf_points",
            "page_width": 600,
            "page_height": 800,
            "x0": 100,
            "y0": 100,
            "x1": 100,
            "y1": 200,
        },
        {
            "coordinate_system": "pdf_points",
            "page_width": 600,
            "page_height": 800,
            "x0": 0,
            "y0": 0,
            "x1": 600,
            "y1": 800,
        },
        {
            "coordinate_system": "unknown",
            "page_width": 600,
            "page_height": 800,
            "x0": 1,
            "y0": 1,
            "x1": 2,
            "y1": 2,
        },
    ],
)
def test_citation_rejects_missing_degenerate_full_page_or_unknown_bbox(
    bbox: Mapping[str, object] | None,
) -> None:
    citation = _citation()
    payload = citation.model_dump(mode="python", exclude={"citation_sha256"})
    payload["bbox"] = bbox
    payload["citation_sha256"] = schema_wiki_sha256("citation-target.v1", payload)
    with pytest.raises(ValidationError):
        CitationTargetV1.model_validate(payload)


def test_citation_member_binding_is_outside_citation_hash_preimage() -> None:
    citation = _citation()
    member = _member("field:field-a", "field", section_id="section-a", field_id="field-a")
    first = _binding(citation, member)
    changed_member = _member(
        "field:field-a",
        "field",
        section_id="section-a",
        field_id="field-a",
        payload=_field_page(field_id="field-a", state="unknown"),
    )
    second = _binding(citation, changed_member)
    assert first.citation_sha256 == second.citation_sha256 == citation.citation_sha256
    assert first.binding_sha256 != second.binding_sha256


def test_release_members_carry_exact_typed_canonical_payloads() -> None:
    release = validate_knowledge_wiki_release(_release(), _pack())
    assert isinstance(release.members[0].payload, SchemaRootPageV1)
    assert isinstance(release.members[1].payload, SchemaSectionPageV1)
    assert isinstance(release.members[3].payload, SchemaFieldPageV1)
    assert release.members[0].payload_sha256 == release.members[0].payload.root_page_sha256
    assert release.members[1].payload_sha256 == release.members[1].payload.section_page_sha256
    assert release.members[3].payload_sha256 == release.members[3].payload.field_page_sha256


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-payload",
        "descriptor-only",
        "generic-payload",
        "kind-payload-swap",
        "foreign-field",
        "unknown-payload-key",
        "noncanonical-payload",
        "payload-self-hash-drift",
    ],
)
def test_release_rejects_unreviewed_or_drifted_member_payload(
    mutation: str,
) -> None:
    release = _release()
    members = list(release.members)
    target_index = 3
    target = members[target_index]
    target_wire = target.model_dump(mode="python")
    if mutation in {"missing-payload", "descriptor-only"}:
        target_wire.pop("payload")
    elif mutation == "generic-payload":
        target_wire["payload"] = {
            "contract": "generic-wiki-page.v1",
            "body": "caller-selected",
            "page_sha256": _sha("generic-page"),
        }
    elif mutation == "kind-payload-swap":
        target_wire["payload"] = _section_page("section-a").model_dump(mode="python")
    else:
        field_payload = cast(dict[str, object], target_wire["payload"])
        if mutation == "foreign-field":
            field_payload["field_id"] = "field-b"
        elif mutation == "unknown-payload-key":
            field_payload["caller_authority"] = "forbidden"
        elif mutation == "noncanonical-payload":
            field_payload["value_snapshot"] = "Cafe\u0301"
        else:
            field_payload["field_page_sha256"] = "f" * 64
        target_wire["payload"] = field_payload
    if mutation == "noncanonical-payload":
        with pytest.raises((ValidationError, ValueError)):
            SchemaWikiMemberV1.model_validate(target_wire)
        return
    target_wire["payload_sha256"] = cast(dict[str, object], target_wire.get("payload", {})).get(
        "field_page_sha256", target.payload_sha256
    )
    target_wire["member_digest"] = schema_wiki_sha256(
        "schema-wiki-member.v1",
        {key: value for key, value in target_wire.items() if key != "member_digest"},
    )
    members[target_index] = SchemaWikiMemberV1.model_construct(**target_wire)
    forged = _rehashed(
        release,
        "knowledge-wiki-release.v1",
        "release_sha256",
        members=tuple(members),
        manifest_digest=schema_wiki_manifest_digest(tuple(members), release.citation_bindings),
    )
    with pytest.raises((ValidationError, SchemaWikiContractError)):
        validate_knowledge_wiki_release(forged, _pack())


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "generic"])
def test_release_rejects_invalid_member_closure(mutation: str) -> None:
    release = _release()
    members = list(release.members)
    if mutation == "missing":
        members.pop()
    elif mutation == "extra":
        members.append(
            _member(
                "field:foreign",
                "field",
                section_id="section-b",
                field_id="foreign",
            )
        )
    elif mutation == "duplicate":
        members.append(members[-1])
    else:
        generic = SchemaWikiMemberV1.model_construct(
            contract="schema-wiki-member.v1",
            member_ref="generic:page",
            member_kind="generic",
            section_id=None,
            field_id=None,
            payload={"contract": "generic-wiki-page.v1"},
            payload_sha256=_sha("generic"),
            member_digest=_sha("generic-member"),
        )
        members.append(generic)
    forged = _rehashed(
        release,
        "knowledge-wiki-release.v1",
        "release_sha256",
        members=tuple(members),
    )
    with pytest.raises(SchemaWikiContractError):
        validate_knowledge_wiki_release(forged, _pack())


def test_release_is_draft_only_and_cannot_claim_active() -> None:
    with pytest.raises((ValidationError, SchemaWikiContractError)):
        validate_knowledge_wiki_release(_release(state="active"), _pack())


def test_release_manifest_digest_is_independent_and_member_sensitive() -> None:
    release = validate_knowledge_wiki_release(_release(), _pack())
    assert release.manifest_digest != release.release_sha256
    changed = list(release.members)
    root_payload = cast(SchemaRootPageV1, changed[0].payload)
    root_values = root_payload.model_dump(mode="python", exclude={"root_page_sha256"})
    root_values["product_display_name"] = "Mutated product display"
    changed[0] = _member(
        changed[0].member_ref,
        "root",
        payload=_sealed(
            SchemaRootPageV1,
            "schema-root-page.v1",
            "root_page_sha256",
            **root_values,
        ),
    )
    forged = _rehashed(
        release,
        "knowledge-wiki-release.v1",
        "release_sha256",
        members=tuple(changed),
    )
    with pytest.raises(SchemaWikiContractError, match="MANIFEST_DIGEST_INVALID"):
        validate_knowledge_wiki_release(forged, _pack())


@pytest.mark.parametrize(
    "field",
    [
        "candidate_sha256",
        "release_sha256",
        "manifest_digest",
        "ordered_member_digests",
        "ordered_binding_sha256s",
        "review_policy_sha256",
        "taxonomy_sha256",
        "schema_pack_sha256",
        "entity_id",
        "version_id",
    ],
)
def test_review_bundle_binds_complete_manifest_and_authority(field: str) -> None:
    release = validate_knowledge_wiki_release(_release(), _pack())
    bundle = _review_bundle(release)
    changes: dict[str, object]
    if field == "ordered_member_digests":
        changes = {field: tuple(reversed(getattr(bundle, field)))}
    elif field == "ordered_binding_sha256s":
        changes = {field: ("f" * 64,)}
    elif field in {"entity_id", "version_id"}:
        changes = {field: "foreign"}
    else:
        changes = {field: "f" * 64}
    forged = _rehashed(
        bundle,
        "schema-wiki-review-bundle.v1",
        "review_bundle_sha256",
        **changes,
    )
    with pytest.raises(SchemaWikiContractError, match="REVIEW_BUNDLE_INVALID"):
        validate_schema_wiki_review_bundle(forged, release)


def test_python_replays_the_exact_go_contract_vector() -> None:
    path = (
        Path(__file__).parents[2]
        / "internal/application/service/testdata/schema_wiki_contract_vector.json"
    )
    raw = path.read_bytes()
    wire = json.loads(raw)
    assert (
        raw.strip()
        == json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    )
    pack = SchemaPackV1.model_validate(wire["schema_pack"])
    release = KnowledgeWikiReleaseV1.model_validate(wire["release"])
    validate_knowledge_wiki_release(release, pack)
    assert wire["expected"] == {
        "schema_pack_sha256": pack.schema_pack_sha256,
        "taxonomy_sha256": release.taxonomy.taxonomy_sha256,
        "manifest_digest": release.manifest_digest,
        "release_sha256": release.release_sha256,
        "citation_sha256": wire["citations"][0]["citation_sha256"],
        "release_canonical_preimage_hex": schema_wiki_canonical_bytes(
            release.contract,
            release.model_dump(mode="python", exclude={"release_sha256"}),
        ).hex(),
    }
