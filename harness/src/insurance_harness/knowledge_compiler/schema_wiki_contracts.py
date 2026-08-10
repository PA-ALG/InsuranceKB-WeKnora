"""Canonical, domain-neutral contracts for a release-pinned Schema Wiki."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Annotated, Final, Literal, Self

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

Sha256Hex = Annotated[StrictStr, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=256, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]
NonBlankText = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=4096, pattern=r"^\S(?:[^\r\n]*\S)?$"),
]

_HASH_PREFIX: Final[bytes] = b"schema-wiki-canonical.v1\x00"


class SchemaWikiContractError(ValueError):
    """Stable typed failure for the shared Schema Wiki boundary."""

    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")


def _has_disallowed_control(value: str) -> bool:
    return any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)


def _json_tree(value: object) -> object:
    if isinstance(value, BaseModel):
        return _json_tree(
            value.model_dump(
                mode="python",
                round_trip=True,
                warnings=False,
                exclude_computed_fields=True,
            )
        )
    if type(value) is str:
        if unicodedata.normalize("NFC", value) != value:
            raise ValueError("Schema Wiki text must be NFC")
        if _has_disallowed_control(value):
            raise ValueError("Schema Wiki text must not contain control characters")
        return value
    if value is None or type(value) in (int, bool):
        return value
    if type(value) is float:
        raise TypeError("binary floats are not canonical Schema Wiki values")
    if isinstance(value, tuple | list):
        return [_json_tree(item) for item in value]
    if isinstance(value, Mapping):
        tree: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("canonical Schema Wiki map keys must be strings")
            tree[key] = _json_tree(item)
        return tree
    raise TypeError(f"unsupported canonical Schema Wiki type: {type(value).__name__}")


def schema_wiki_canonical_bytes(object_type: str, payload: object) -> bytes:
    """Return the exact Python/Go shared hash preimage."""

    if not object_type or _has_disallowed_control(object_type):
        raise ValueError("invalid Schema Wiki object type")
    encoded = json.dumps(
        _json_tree(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _HASH_PREFIX + object_type.encode("ascii") + b"\x00" + encoded


def schema_wiki_sha256(object_type: str, payload: object) -> str:
    return hashlib.sha256(schema_wiki_canonical_bytes(object_type, payload)).hexdigest()


def _payload(model: BaseModel, hash_field: str) -> dict[str, object]:
    return model.model_dump(
        mode="python",
        round_trip=True,
        warnings=False,
        exclude={hash_field},
        exclude_computed_fields=True,
    )


def _hash_matches(model: BaseModel, object_type: str, hash_field: str) -> bool:
    return bool(
        getattr(model, hash_field)
        == schema_wiki_sha256(object_type, _payload(model, hash_field))
    )


class KnowledgeDomainV1(_FrozenModel):
    contract: Literal["knowledge-domain.v1"]
    domain_id: Identifier
    display_name: NonBlankText
    domain_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if not _hash_matches(self, self.contract, "domain_sha256"):
            raise ValueError("domain_sha256 mismatch")
        return self


class TaxonomyNodeV1(_FrozenModel):
    node_id: Identifier
    parent_node_id: Identifier | None
    node_kind: Literal["category", "entity"]
    slug: Identifier
    stable_entity_id: Identifier | None
    position: Annotated[StrictInt, Field(ge=0)]

    @model_validator(mode="after")
    def validate_shape(self) -> Self:
        if (self.node_kind == "entity") != (self.stable_entity_id is not None):
            raise ValueError("taxonomy entity identity mismatch")
        return self


class TaxonomyRedirectV1(_FrozenModel):
    from_path: Identifier
    to_path: Identifier
    stable_entity_id: Identifier

    @model_validator(mode="after")
    def validate_redirect(self) -> Self:
        if self.from_path == self.to_path:
            raise ValueError("taxonomy redirect must change path")
        return self


class TaxonomySnapshotV1(_FrozenModel):
    contract: Literal["taxonomy-snapshot.v1"]
    domain_id: Identifier
    taxonomy_version: Identifier
    previous_snapshot_sha256: Sha256Hex | None
    nodes: tuple[TaxonomyNodeV1, ...]
    redirects: tuple[TaxonomyRedirectV1, ...]
    taxonomy_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        _validate_taxonomy_graph(self.nodes, self.redirects)
        if not _hash_matches(self, self.contract, "taxonomy_sha256"):
            raise ValueError("taxonomy_sha256 mismatch")
        return self


class SchemaSectionV1(_FrozenModel):
    section_id: Identifier
    display_name: NonBlankText
    ordered_field_ids: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        if not self.ordered_field_ids or len(set(self.ordered_field_ids)) != len(
            self.ordered_field_ids
        ):
            raise ValueError("section field order is empty or duplicated")
        return self


class SchemaPackV1(_FrozenModel):
    contract: Literal["schema-pack.v1"]
    schema_pack_id: Identifier
    schema_version: Identifier
    domain_id: Identifier
    ordered_field_ids: tuple[Identifier, ...]
    sections: tuple[SchemaSectionV1, ...]
    schema_pack_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_pack(self) -> Self:
        _validate_schema_pack_topology(self)
        if not _hash_matches(self, self.contract, "schema_pack_sha256"):
            raise ValueError("schema_pack_sha256 mismatch")
        return self


class EntityIdentityV1(_FrozenModel):
    domain_id: Identifier
    entity_id: Identifier


class EntityVersionV1(_FrozenModel):
    entity_id: Identifier
    version_id: Identifier
    product_version_id: Identifier


class CitationBBoxV1(_FrozenModel):
    coordinate_system: Literal["pdf_points", "normalized_0_1e6"]
    page_width: Annotated[StrictInt, Field(gt=0)]
    page_height: Annotated[StrictInt, Field(gt=0)]
    x0: Annotated[StrictInt, Field(ge=0)]
    y0: Annotated[StrictInt, Field(ge=0)]
    x1: Annotated[StrictInt, Field(gt=0)]
    y1: Annotated[StrictInt, Field(gt=0)]

    @model_validator(mode="after")
    def validate_bbox(self) -> Self:
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            raise ValueError("degenerate citation bbox")
        if self.x1 > self.page_width or self.y1 > self.page_height:
            raise ValueError("citation bbox exceeds page")
        if (
            self.x0 == 0
            and self.y0 == 0
            and self.x1 == self.page_width
            and self.y1 == self.page_height
        ):
            raise ValueError("full-page citation bbox is forbidden")
        return self


class CitationTargetV1(_FrozenModel):
    contract: Literal["citation-target.v1"]
    citation_id: Identifier
    source_role: Identifier
    space_id: Identifier
    entity_version_id: Identifier
    knowledge_id: Identifier
    chunk_id: Identifier
    source_revision_id: Identifier
    parse_attempt_id: Identifier
    parsed_document_sha256: Sha256Hex
    parse_manifest_sha256: Sha256Hex
    page_number: Annotated[StrictInt, Field(gt=0)]
    locator_ref: Identifier
    bbox: CitationBBoxV1
    quote_snapshot: NonBlankText
    quote_sha256: Sha256Hex
    content_snapshot_sha256: Sha256Hex
    logical_member_ref: Identifier
    citation_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_citation(self) -> Self:
        if self.quote_sha256 != schema_wiki_sha256(
            "schema-wiki-text.v1", {"text": self.quote_snapshot}
        ):
            raise ValueError("quote_sha256 mismatch")
        if not _hash_matches(self, self.contract, "citation_sha256"):
            raise ValueError("citation_sha256 mismatch")
        return self


class SchemaFieldPageV1(_FrozenModel):
    contract: Literal["schema-field-page.v1"]
    field_id: Identifier
    state: Literal["present", "absent_explicitly", "unknown"]
    value_snapshot: NonBlankText | None
    citations: tuple[CitationTargetV1, ...]
    evidence_receipt_sha256s: tuple[Sha256Hex, ...]
    review_item_reason: Identifier | None
    field_page_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_tri_state(self) -> Self:
        hashes = tuple(item.citation_sha256 for item in self.citations)
        if len(set(hashes)) != len(hashes):
            raise ValueError("duplicate field citations")
        if len(set(self.evidence_receipt_sha256s)) != len(
            self.evidence_receipt_sha256s
        ):
            raise ValueError("duplicate Evidence receipt identities")
        if self.state in {"present", "absent_explicitly"}:
            if (
                self.value_snapshot is None
                or not self.citations
                or not self.evidence_receipt_sha256s
                or self.review_item_reason is not None
            ):
                raise ValueError("known field requires value and citation without ReviewItem")
        elif (
            self.value_snapshot is not None
            or self.citations
            or self.evidence_receipt_sha256s
            or self.review_item_reason != "FIELD_UNKNOWN"
        ):
            raise ValueError("unknown field must be value/Evidence-free and reviewable")
        if not _hash_matches(self, self.contract, "field_page_sha256"):
            raise ValueError("field_page_sha256 mismatch")
        return self


class SchemaRootPageV1(_FrozenModel):
    contract: Literal["schema-root-page.v1"]
    domain_id: Identifier
    domain_sha256: Sha256Hex
    schema_pack_id: Identifier
    schema_version: Identifier
    schema_pack_sha256: Sha256Hex
    entity_id: Identifier
    entity_version_id: Identifier
    product_version_id: Identifier
    taxonomy_version: Identifier
    taxonomy_sha256: Sha256Hex
    product_display_name: NonBlankText
    ordered_section_ids: tuple[Identifier, ...]
    root_page_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if not self.ordered_section_ids or len(set(self.ordered_section_ids)) != len(
            self.ordered_section_ids
        ):
            raise ValueError("root section order is empty or duplicated")
        if not _hash_matches(self, self.contract, "root_page_sha256"):
            raise ValueError("root_page_sha256 mismatch")
        return self


class SchemaSectionPageV1(_FrozenModel):
    contract: Literal["schema-section-page.v1"]
    domain_id: Identifier
    domain_sha256: Sha256Hex
    schema_pack_id: Identifier
    schema_version: Identifier
    schema_pack_sha256: Sha256Hex
    entity_id: Identifier
    entity_version_id: Identifier
    product_version_id: Identifier
    taxonomy_version: Identifier
    taxonomy_sha256: Sha256Hex
    section_id: Identifier
    display_name: NonBlankText
    ordered_field_ids: tuple[Identifier, ...]
    section_page_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_page(self) -> Self:
        if not self.ordered_field_ids or len(set(self.ordered_field_ids)) != len(
            self.ordered_field_ids
        ):
            raise ValueError("section field order is empty or duplicated")
        if not _hash_matches(self, self.contract, "section_page_sha256"):
            raise ValueError("section_page_sha256 mismatch")
        return self


SchemaWikiPageV1 = Annotated[
    SchemaRootPageV1 | SchemaSectionPageV1 | SchemaFieldPageV1,
    Field(discriminator="contract"),
]


class SchemaWikiMemberV1(_FrozenModel):
    contract: Literal["schema-wiki-member.v1"]
    member_ref: Identifier
    member_kind: Literal["root", "section", "field"]
    section_id: Identifier | None
    field_id: Identifier | None
    payload: SchemaWikiPageV1
    payload_sha256: Sha256Hex
    member_digest: Sha256Hex

    @model_validator(mode="after")
    def validate_member(self) -> Self:
        if self.member_kind == "root":
            valid_shape = self.section_id is None and self.field_id is None
        elif self.member_kind == "section":
            valid_shape = self.section_id is not None and self.field_id is None
        else:
            valid_shape = self.section_id is not None and self.field_id is not None
        if not valid_shape:
            raise ValueError("member kind/identity mismatch")
        payload_shape_valid = (
            self.member_kind == "root"
            and isinstance(self.payload, SchemaRootPageV1)
            and self.payload_sha256 == self.payload.root_page_sha256
        ) or (
            self.member_kind == "section"
            and isinstance(self.payload, SchemaSectionPageV1)
            and self.payload.section_id == self.section_id
            and self.payload_sha256 == self.payload.section_page_sha256
        ) or (
            self.member_kind == "field"
            and isinstance(self.payload, SchemaFieldPageV1)
            and self.payload.field_id == self.field_id
            and self.payload_sha256 == self.payload.field_page_sha256
        )
        if not payload_shape_valid:
            raise ValueError("member payload identity mismatch")
        if not _hash_matches(self, self.contract, "member_digest"):
            raise ValueError("member_digest mismatch")
        return self


class CitationMemberBindingV1(_FrozenModel):
    contract: Literal["citation-member-binding.v1"]
    citation_sha256: Sha256Hex
    logical_member_ref: Identifier
    member_digest: Sha256Hex
    binding_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_binding(self) -> Self:
        if not _hash_matches(self, self.contract, "binding_sha256"):
            raise ValueError("binding_sha256 mismatch")
        return self


class KnowledgeWikiReleaseV1(_FrozenModel):
    contract: Literal["knowledge-wiki-release.v1"]
    release_state: Literal["draft"]
    domain: KnowledgeDomainV1
    taxonomy: TaxonomySnapshotV1
    schema_pack: SchemaPackV1
    entity: EntityIdentityV1
    entity_version: EntityVersionV1
    candidate_sha256: Sha256Hex
    review_policy_sha256: Sha256Hex
    members: tuple[SchemaWikiMemberV1, ...]
    citation_bindings: tuple[CitationMemberBindingV1, ...]
    manifest_digest: Sha256Hex
    release_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if not _hash_matches(self, self.contract, "release_sha256"):
            raise ValueError("release_sha256 mismatch")
        return self


class SchemaWikiReviewBundleV1(_FrozenModel):
    contract: Literal["schema-wiki-review-bundle.v1"]
    candidate_sha256: Sha256Hex
    release_sha256: Sha256Hex
    manifest_digest: Sha256Hex
    ordered_member_digests: tuple[Sha256Hex, ...]
    ordered_binding_sha256s: tuple[Sha256Hex, ...]
    review_policy_sha256: Sha256Hex
    domain_sha256: Sha256Hex
    taxonomy_sha256: Sha256Hex
    schema_pack_sha256: Sha256Hex
    entity_id: Identifier
    version_id: Identifier
    review_bundle_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_hash(self) -> Self:
        if not _hash_matches(self, self.contract, "review_bundle_sha256"):
            raise ValueError("review_bundle_sha256 mismatch")
        return self


def _validate_taxonomy_graph(
    nodes: Sequence[TaxonomyNodeV1], redirects: Sequence[TaxonomyRedirectV1]
) -> None:
    if not nodes:
        raise ValueError("taxonomy must not be empty")
    ids = [node.node_id for node in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate taxonomy node")
    by_id = {node.node_id: node for node in nodes}
    roots = [node for node in nodes if node.parent_node_id is None]
    if not roots:
        raise ValueError("taxonomy requires a root")
    for node in nodes:
        if node.parent_node_id is not None and node.parent_node_id not in by_id:
            raise ValueError("orphan taxonomy node")
        seen: set[str] = set()
        cursor: TaxonomyNodeV1 | None = node
        while cursor is not None:
            if cursor.node_id in seen:
                raise ValueError("taxonomy cycle")
            seen.add(cursor.node_id)
            cursor = by_id.get(cursor.parent_node_id) if cursor.parent_node_id else None
    from_paths = [row.from_path for row in redirects]
    if len(from_paths) != len(set(from_paths)):
        raise ValueError("duplicate taxonomy redirect")
    entity_ids = {
        node.stable_entity_id for node in nodes if node.stable_entity_id is not None
    }
    if any(row.stable_entity_id not in entity_ids for row in redirects):
        raise ValueError("taxonomy redirect targets a foreign entity")


def _validate_schema_pack_topology(pack: SchemaPackV1) -> None:
    if not pack.ordered_field_ids or not pack.sections:
        raise ValueError("schema pack topology is empty")
    section_ids = [section.section_id for section in pack.sections]
    if len(section_ids) != len(set(section_ids)):
        raise ValueError("duplicate schema section")
    if len(pack.ordered_field_ids) != len(set(pack.ordered_field_ids)):
        raise ValueError("duplicate schema field")
    flattened = tuple(
        field_id for section in pack.sections for field_id in section.ordered_field_ids
    )
    if flattened != pack.ordered_field_ids:
        raise ValueError("schema fields are not an exact ordered partition")


def _fresh[ModelT: BaseModel](model: ModelT, reason: str) -> ModelT:
    try:
        validated = type(model).model_validate(
            model.model_dump(
                mode="python",
                round_trip=True,
                warnings=False,
                exclude_computed_fields=True,
            )
        )
    except (ValidationError, TypeError, ValueError):
        raise SchemaWikiContractError(reason) from None
    if validated != model:
        raise SchemaWikiContractError(reason)
    return validated


def validate_taxonomy_snapshot(
    snapshot: TaxonomySnapshotV1, *, previous: TaxonomySnapshotV1 | None = None
) -> TaxonomySnapshotV1:
    current = _fresh(snapshot, "TAXONOMY_INVALID")
    if previous is None:
        return current
    prior = _fresh(previous, "TAXONOMY_INVALID")
    if current.previous_snapshot_sha256 != prior.taxonomy_sha256:
        raise SchemaWikiContractError("TAXONOMY_PREDECESSOR_INVALID")
    old_entities = {
        node.stable_entity_id: node
        for node in prior.nodes
        if node.stable_entity_id is not None
    }
    new_entities = {
        node.stable_entity_id: node
        for node in current.nodes
        if node.stable_entity_id is not None
    }
    if set(old_entities) != set(new_entities):
        raise SchemaWikiContractError("STABLE_ENTITY_IDENTITY_INVALID")
    changed = {
        entity_id
        for entity_id, old in old_entities.items()
        if new_entities[entity_id].parent_node_id != old.parent_node_id
    }
    redirected = {row.stable_entity_id for row in current.redirects}
    if not changed.issubset(redirected):
        raise SchemaWikiContractError("TAXONOMY_REDIRECT_INVALID")
    return current


def validate_schema_pack(pack: SchemaPackV1) -> SchemaPackV1:
    try:
        current = _fresh(pack, "SCHEMA_PACK_TOPOLOGY_INVALID")
        _validate_schema_pack_topology(current)
        return current
    except SchemaWikiContractError:
        raise
    except (TypeError, ValueError, ValidationError):
        raise SchemaWikiContractError("SCHEMA_PACK_TOPOLOGY_INVALID") from None


def validate_citation_target(
    citation: CitationTargetV1,
    *,
    expected_space_id: str,
    expected_entity_version_id: str,
    expected_knowledge_id: str,
    expected_chunk_id: str,
    expected_source_revision_id: str,
    expected_parse_attempt_id: str,
    expected_parsed_document_sha256: str,
    expected_parse_manifest_sha256: str,
    expected_page_number: int,
    expected_locator_ref: str,
    expected_quote_snapshot: str,
    expected_content_snapshot_sha256: str,
) -> CitationTargetV1:
    current = _fresh(citation, "CITATION_TARGET_INVALID")
    actual = (
        current.space_id,
        current.entity_version_id,
        current.knowledge_id,
        current.chunk_id,
        current.source_revision_id,
        current.parse_attempt_id,
        current.parsed_document_sha256,
        current.parse_manifest_sha256,
        current.page_number,
        current.locator_ref,
        current.quote_snapshot,
        current.content_snapshot_sha256,
    )
    expected = (
        expected_space_id,
        expected_entity_version_id,
        expected_knowledge_id,
        expected_chunk_id,
        expected_source_revision_id,
        expected_parse_attempt_id,
        expected_parsed_document_sha256,
        expected_parse_manifest_sha256,
        expected_page_number,
        expected_locator_ref,
        expected_quote_snapshot,
        expected_content_snapshot_sha256,
    )
    if actual != expected:
        raise SchemaWikiContractError("CITATION_AUTHORITY_DRIFT")
    return current


def schema_wiki_manifest_digest(
    members: Sequence[SchemaWikiMemberV1],
    bindings: Sequence[CitationMemberBindingV1],
) -> str:
    """Bind the exact ordered immutable manifest independently of its release shell."""

    return schema_wiki_sha256(
        "schema-wiki-manifest.v1",
        {
            "members": tuple(members),
            "citation_bindings": tuple(bindings),
        },
    )


def _expected_members(pack: SchemaPackV1, entity_version: EntityVersionV1) -> tuple[
    tuple[str, str, str | None, str | None], ...
]:
    rows: list[tuple[str, str, str | None, str | None]] = [
        (f"root:{entity_version.version_id}", "root", None, None)
    ]
    rows.extend(
        (f"section:{section.section_id}", "section", section.section_id, None)
        for section in pack.sections
    )
    section_by_field = {
        field_id: section.section_id
        for section in pack.sections
        for field_id in section.ordered_field_ids
    }
    rows.extend(
        (f"field:{field_id}", "field", section_by_field[field_id], field_id)
        for field_id in pack.ordered_field_ids
    )
    return tuple(rows)


def validate_knowledge_wiki_release(
    release: KnowledgeWikiReleaseV1, pack: SchemaPackV1
) -> KnowledgeWikiReleaseV1:
    current_pack = validate_schema_pack(pack)
    current = _fresh(release, "RELEASE_CUSTODY_INVALID")
    if current.release_state != "draft":
        raise SchemaWikiContractError("DRAFT_AUTHORITY_INVALID")
    if current.schema_pack != current_pack:
        raise SchemaWikiContractError("SCHEMA_PACK_BINDING_INVALID")
    if not (
        current.domain.domain_id
        == current.taxonomy.domain_id
        == current.schema_pack.domain_id
        == current.entity.domain_id
    ):
        raise SchemaWikiContractError("DOMAIN_BINDING_INVALID")
    if current.entity_version.entity_id != current.entity.entity_id:
        raise SchemaWikiContractError("ENTITY_VERSION_BINDING_INVALID")
    taxonomy_entities = {
        node.stable_entity_id
        for node in current.taxonomy.nodes
        if node.stable_entity_id is not None
    }
    if current.entity.entity_id not in taxonomy_entities:
        raise SchemaWikiContractError("ENTITY_TAXONOMY_BINDING_INVALID")

    expected = _expected_members(current_pack, current.entity_version)
    actual = tuple(
        (row.member_ref, row.member_kind, row.section_id, row.field_id)
        for row in current.members
    )
    if actual != expected:
        raise SchemaWikiContractError("MEMBER_ORDER_INVALID")
    digests = tuple(row.member_digest for row in current.members)
    if len(set(digests)) != len(digests):
        raise SchemaWikiContractError("MEMBER_DIGEST_DUPLICATE")
    members_by_ref = {row.member_ref: row for row in current.members}
    root_payload = current.members[0].payload
    root_expected = (
        current.domain.domain_id,
        current.domain.domain_sha256,
        current.schema_pack.schema_pack_id,
        current.schema_pack.schema_version,
        current.schema_pack.schema_pack_sha256,
        current.entity.entity_id,
        current.entity_version.version_id,
        current.entity_version.product_version_id,
        current.taxonomy.taxonomy_version,
        current.taxonomy.taxonomy_sha256,
        tuple(section.section_id for section in current.schema_pack.sections),
    )
    if not isinstance(root_payload, SchemaRootPageV1) or (
        root_payload.domain_id,
        root_payload.domain_sha256,
        root_payload.schema_pack_id,
        root_payload.schema_version,
        root_payload.schema_pack_sha256,
        root_payload.entity_id,
        root_payload.entity_version_id,
        root_payload.product_version_id,
        root_payload.taxonomy_version,
        root_payload.taxonomy_sha256,
        root_payload.ordered_section_ids,
    ) != root_expected:
        raise SchemaWikiContractError("ROOT_PAYLOAD_BINDING_INVALID")
    for index, section in enumerate(current.schema_pack.sections, start=1):
        section_payload = current.members[index].payload
        if not isinstance(section_payload, SchemaSectionPageV1) or (
            section_payload.domain_id,
            section_payload.domain_sha256,
            section_payload.schema_pack_id,
            section_payload.schema_version,
            section_payload.schema_pack_sha256,
            section_payload.entity_id,
            section_payload.entity_version_id,
            section_payload.product_version_id,
            section_payload.taxonomy_version,
            section_payload.taxonomy_sha256,
            section_payload.section_id,
            section_payload.display_name,
            section_payload.ordered_field_ids,
        ) != (
            current.domain.domain_id,
            current.domain.domain_sha256,
            current.schema_pack.schema_pack_id,
            current.schema_pack.schema_version,
            current.schema_pack.schema_pack_sha256,
            current.entity.entity_id,
            current.entity_version.version_id,
            current.entity_version.product_version_id,
            current.taxonomy.taxonomy_version,
            current.taxonomy.taxonomy_sha256,
            section.section_id,
            section.display_name,
            section.ordered_field_ids,
        ):
            raise SchemaWikiContractError("SECTION_PAYLOAD_BINDING_INVALID")
    binding_order = tuple(
        (row.logical_member_ref, row.citation_sha256)
        for row in current.citation_bindings
    )
    if binding_order != tuple(sorted(binding_order)):
        raise SchemaWikiContractError("CITATION_BINDING_ORDER_INVALID")
    if len({row.citation_sha256 for row in current.citation_bindings}) != len(
        current.citation_bindings
    ):
        raise SchemaWikiContractError("CITATION_BINDING_DUPLICATE")
    payload_citations: list[tuple[str, str]] = []
    for member in current.members:
        if not isinstance(member.payload, SchemaFieldPageV1):
            continue
        for citation in member.payload.citations:
            if (
                citation.logical_member_ref != member.member_ref
                or citation.entity_version_id != current.entity_version.version_id
            ):
                raise SchemaWikiContractError("FIELD_PAYLOAD_CITATION_INVALID")
            payload_citations.append((member.member_ref, citation.citation_sha256))
    if tuple(sorted(payload_citations)) != binding_order:
        raise SchemaWikiContractError("CITATION_PAYLOAD_CLOSURE_INVALID")
    for binding in current.citation_bindings:
        bound_member = members_by_ref.get(binding.logical_member_ref)
        if bound_member is None or bound_member.member_digest != binding.member_digest:
            raise SchemaWikiContractError("CITATION_MEMBER_BINDING_INVALID")
    if current.manifest_digest != schema_wiki_manifest_digest(
        current.members, current.citation_bindings
    ):
        raise SchemaWikiContractError("MANIFEST_DIGEST_INVALID")
    return current


def validate_schema_wiki_review_bundle(
    bundle: SchemaWikiReviewBundleV1, release: KnowledgeWikiReleaseV1
) -> SchemaWikiReviewBundleV1:
    current_release = validate_knowledge_wiki_release(release, release.schema_pack)
    current = _fresh(bundle, "REVIEW_BUNDLE_INVALID")
    expected = (
        current_release.candidate_sha256,
        current_release.release_sha256,
        current_release.manifest_digest,
        tuple(row.member_digest for row in current_release.members),
        tuple(row.binding_sha256 for row in current_release.citation_bindings),
        current_release.review_policy_sha256,
        current_release.domain.domain_sha256,
        current_release.taxonomy.taxonomy_sha256,
        current_release.schema_pack.schema_pack_sha256,
        current_release.entity.entity_id,
        current_release.entity_version.version_id,
    )
    actual = (
        current.candidate_sha256,
        current.release_sha256,
        current.manifest_digest,
        current.ordered_member_digests,
        current.ordered_binding_sha256s,
        current.review_policy_sha256,
        current.domain_sha256,
        current.taxonomy_sha256,
        current.schema_pack_sha256,
        current.entity_id,
        current.version_id,
    )
    if actual != expected:
        raise SchemaWikiContractError("REVIEW_BUNDLE_INVALID")
    return current


__all__ = [
    "CitationBBoxV1",
    "CitationMemberBindingV1",
    "CitationTargetV1",
    "EntityIdentityV1",
    "EntityVersionV1",
    "KnowledgeDomainV1",
    "KnowledgeWikiReleaseV1",
    "SchemaFieldPageV1",
    "SchemaPackV1",
    "SchemaRootPageV1",
    "SchemaSectionV1",
    "SchemaSectionPageV1",
    "SchemaWikiContractError",
    "SchemaWikiMemberV1",
    "SchemaWikiReviewBundleV1",
    "TaxonomyNodeV1",
    "TaxonomyRedirectV1",
    "TaxonomySnapshotV1",
    "schema_wiki_canonical_bytes",
    "schema_wiki_manifest_digest",
    "schema_wiki_sha256",
    "validate_citation_target",
    "validate_knowledge_wiki_release",
    "validate_schema_pack",
    "validate_schema_wiki_review_bundle",
    "validate_taxonomy_snapshot",
]
