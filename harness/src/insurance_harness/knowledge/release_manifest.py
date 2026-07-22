"""Complete deterministic ReleaseManifest contracts (OpenSpec 029 RA1)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    ValidationError,
    field_validator,
)
from sqlalchemy import select
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.knowledge.tables import ReleaseSnapshot, SnapshotFact

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ReleaseManifestIntegrityError(ValueError):
    """A manifest no longer matches its canonical artifact or outer hashes."""


class ReleaseManifestBuildError(ValueError):
    """A frozen, scoped snapshot cannot produce a complete manifest."""


FrozenJsonScalar = str | int | float | bool | None


class FrozenJsonObject(Mapping[str, "FrozenJsonValue"]):
    """Read-only JSON object whose descendants are recursively immutable."""

    __slots__ = ("_items", "_values")

    def __init__(self, values: Mapping[str, FrozenJsonValue]) -> None:
        self._items = tuple(sorted(values))
        self._values = MappingProxyType({key: values[key] for key in self._items})

    def __getitem__(self, key: str) -> FrozenJsonValue:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:
        return repr(_thaw_json(self))

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Mapping):
            return dict(self.items()) == dict(other.items())
        return False


FrozenJsonValue = FrozenJsonScalar | tuple["FrozenJsonValue", ...] | FrozenJsonObject


def _freeze_json(value: object) -> FrozenJsonValue:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, FrozenJsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            frozen[key] = _freeze_json(item)
        return FrozenJsonObject(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError("value must be canonical JSON")


def _thaw_json(value: FrozenJsonValue) -> Any:
    if isinstance(value, FrozenJsonObject):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


ImmutableJson = Annotated[
    Any,
    BeforeValidator(_freeze_json),
    PlainSerializer(_thaw_json, return_type=Any, when_used="always"),
]


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        strict=True,
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        arbitrary_types_allowed=True,
    )


def _canonical_text(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("identity must be non-empty canonical text")
    return value


def _valid_sha256(value: str) -> str:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("must be a lowercase SHA-256")
    return value


class CanonicalEvidence(_StrictFrozenModel):
    """Complete frozen 018 document evidence carried into the manifest."""

    id: str
    claim_id: str
    knowledge_id: str
    doc_title: str
    chunk_id: str | None
    quote: str
    page: int | None
    section: str | None
    table_ref: str | None
    timestamp_ms: int | None
    authority_level: int
    doc_role: str
    extraction_method: str
    extracted_at: datetime
    raw_kb_id: str
    source_revision: str
    file_hash: str
    original_digest: str
    parser_version: str
    chunk_hash: str | None
    lineage_status: Literal["linked", "page_only", "ambiguous"]
    stale_at: datetime | None
    created_at: datetime
    updated_at: datetime

    _validate_required_text = field_validator(
        "id",
        "claim_id",
        "knowledge_id",
        "doc_title",
        "quote",
        "doc_role",
        "extraction_method",
        "raw_kb_id",
        "source_revision",
        "file_hash",
        "original_digest",
        "parser_version",
    )(_canonical_text)

    @field_validator(
        "extracted_at", "created_at", "updated_at", "stale_at", mode="after"
    )
    @classmethod
    def _normalize_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("evidence datetime must be timezone-aware")
        return value.astimezone(UTC)


class CanonicalSnapshotFact(_StrictFrozenModel):
    """Complete frozen SnapshotFact, including required frozen Evidence."""

    space_id: str
    snapshot_id: str
    claim_id: str
    revision_no: int = Field(gt=0)
    product_id: str
    product_version_id: str
    product_code: str
    product_name: str
    version_label: str
    predicate: str
    field_name: str
    field_group: str
    value_state: Literal["present", "absent_explicitly", "unknown"]
    value: ImmutableJson
    effective_from: date | None
    effective_to: date | None
    confidence: float = Field(ge=0.0, le=1.0)
    schema_version: str
    evidence: tuple[CanonicalEvidence, ...] = Field(min_length=1)

    _validate_required_text = field_validator(
        "space_id",
        "snapshot_id",
        "claim_id",
        "product_id",
        "product_version_id",
        "product_code",
        "product_name",
        "version_label",
        "predicate",
        "field_name",
        "field_group",
        "schema_version",
    )(_canonical_text)

    @field_validator("evidence", mode="after")
    @classmethod
    def _canonical_evidence_order(
        cls,
        value: tuple[CanonicalEvidence, ...],
    ) -> tuple[CanonicalEvidence, ...]:
        identities = tuple(item.id for item in value)
        if len(set(identities)) != len(identities):
            raise ValueError("evidence identities must be unique")
        return tuple(
            sorted(
                value,
                key=lambda item: (
                    item.raw_kb_id,
                    item.knowledge_id,
                    item.source_revision,
                    item.file_hash,
                    item.chunk_id or "",
                    item.id,
                ),
            )
        )


class CanonicalPageEntityIds(_StrictFrozenModel):
    product_id: str
    product_version_id: str

    _validate_identity = field_validator("product_id", "product_version_id")(
        _canonical_text
    )


class CanonicalPageMetadata(_StrictFrozenModel):
    entity_ids: CanonicalPageEntityIds
    snapshot_id: str
    claim_ids: tuple[str, ...] = Field(min_length=1)
    compiled_at: str
    harness_version: str
    schema_version: str
    managed_by: Literal["insurance-harness"]
    space_id: str
    schema_versions: tuple[str, ...] = Field(min_length=1)

    _validate_identity = field_validator(
        "snapshot_id",
        "compiled_at",
        "harness_version",
        "schema_version",
        "space_id",
    )(_canonical_text)

    @field_validator("claim_ids", "schema_versions")
    @classmethod
    def _validate_unique_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            _canonical_text(item)
        if len(set(value)) != len(value):
            raise ValueError("values must be unique")
        return value


class CanonicalPage(_StrictFrozenModel):
    slug: str
    title: str
    content: str
    source_refs: tuple[str, ...]
    chunk_refs: tuple[str, ...]
    page_metadata: CanonicalPageMetadata

    _validate_identity = field_validator("slug", "title")(_canonical_text)


class CanonicalDirectoryEntry(_StrictFrozenModel):
    product_id: str
    product_version_id: str
    product_code: str
    product_name: str
    version_label: str
    page_slugs: tuple[str, ...]

    _validate_identity = field_validator(
        "product_id",
        "product_version_id",
        "product_code",
        "product_name",
        "version_label",
    )(_canonical_text)


class CanonicalRelationship(_StrictFrozenModel):
    from_type: Literal["product_version", "page"]
    from_id: str
    relationship: Literal["renders", "contains_claim"]
    to_type: Literal["page", "claim"]
    to_id: str

    _validate_identity = field_validator("from_id", "to_id")(_canonical_text)


CanonicalArtifact = (
    CanonicalSnapshotFact | CanonicalPage | CanonicalDirectoryEntry | CanonicalRelationship
)


class ArtifactDigest(_StrictFrozenModel):
    """Count and SHA-256 of one explicit canonical JSON artifact array."""

    count: int = Field(ge=0)
    sha256: str

    _validate_sha256 = field_validator("sha256")(_valid_sha256)


class ReleaseManifest(_StrictFrozenModel):
    """Immutable hash envelope over every MVP serving artifact group."""

    schema_version: str
    space_id: str
    snapshot_id: str
    read_model_version: int = Field(gt=0)
    template_hashes: tuple[str, ...] = Field(min_length=1)
    model_plan_hash: str
    facts: tuple[CanonicalSnapshotFact, ...]
    facts_digest: ArtifactDigest
    rendered_pages: tuple[CanonicalPage, ...]
    rendered_pages_digest: ArtifactDigest
    directory_entries: tuple[CanonicalDirectoryEntry, ...]
    directory_digest: ArtifactDigest
    relationships: tuple[CanonicalRelationship, ...]
    relationships_digest: ArtifactDigest
    manifest_sha256: str

    _validate_identity = field_validator("schema_version", "space_id", "snapshot_id")(
        _canonical_text
    )

    @field_validator("template_hashes")
    @classmethod
    def _validate_template_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            _valid_sha256(item)
        if tuple(sorted(value)) != value or len(set(value)) != len(value):
            raise ValueError("template hashes must be unique canonical order")
        return value

    _validate_model_plan_hash = field_validator("model_plan_hash")(_valid_sha256)
    _validate_manifest_sha256 = field_validator("manifest_sha256")(_valid_sha256)


def _json_ready(value: object) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, FrozenJsonObject):
        return _thaw_json(value)
    if isinstance(value, tuple):
        return [_json_ready(item) for item in value]
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _canonical_json_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            _json_ready(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReleaseManifestIntegrityError("artifact is not canonical JSON") from exc
    return encoded.encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_models[ArtifactModel: _StrictFrozenModel](
    items: Iterable[Mapping[str, object] | ArtifactModel],
    model: type[ArtifactModel],
) -> tuple[ArtifactModel, ...]:
    validated: list[ArtifactModel] = []
    for item in items:
        value: object = item
        if isinstance(item, BaseModel):
            value = item.model_dump(mode="python")
        validated.append(model.model_validate(value))
    return tuple(sorted(validated, key=_canonical_json_bytes))


def _digest(items: Sequence[CanonicalArtifact]) -> ArtifactDigest:
    return ArtifactDigest(count=len(items), sha256=_sha256(items))


def _manifest_payload(manifest: ReleaseManifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json", exclude={"manifest_sha256"})


def build_release_manifest(
    *,
    schema_version: str,
    space_id: str,
    snapshot_id: str,
    read_model_version: int,
    template_hashes: Iterable[str],
    model_plan_hash: str,
    facts: Iterable[Mapping[str, object] | CanonicalSnapshotFact],
    rendered_pages: Iterable[Mapping[str, object] | CanonicalPage],
    directory_entries: Iterable[Mapping[str, object] | CanonicalDirectoryEntry],
    relationships: Iterable[Mapping[str, object] | CanonicalRelationship],
) -> ReleaseManifest:
    """Validate and bind four complete, typed canonical artifact groups."""

    canonical_facts = _canonical_models(facts, CanonicalSnapshotFact)
    canonical_pages = _canonical_models(rendered_pages, CanonicalPage)
    canonical_directory = _canonical_models(directory_entries, CanonicalDirectoryEntry)
    canonical_relationships = _canonical_models(relationships, CanonicalRelationship)
    common: dict[str, Any] = {
        "schema_version": schema_version,
        "space_id": space_id,
        "snapshot_id": snapshot_id,
        "read_model_version": read_model_version,
        "template_hashes": tuple(sorted(template_hashes)),
        "model_plan_hash": model_plan_hash,
        "facts": canonical_facts,
        "facts_digest": _digest(canonical_facts),
        "rendered_pages": canonical_pages,
        "rendered_pages_digest": _digest(canonical_pages),
        "directory_entries": canonical_directory,
        "directory_digest": _digest(canonical_directory),
        "relationships": canonical_relationships,
        "relationships_digest": _digest(canonical_relationships),
    }
    provisional = ReleaseManifest(manifest_sha256="0" * 64, **common)
    return ReleaseManifest(manifest_sha256=_sha256(_manifest_payload(provisional)), **common)


_ARTIFACT_FIELDS = (
    ("facts", "facts_digest", CanonicalSnapshotFact),
    ("rendered_pages", "rendered_pages_digest", CanonicalPage),
    ("directory_entries", "directory_digest", CanonicalDirectoryEntry),
    ("relationships", "relationships_digest", CanonicalRelationship),
)


def verify_release_manifest(manifest: ReleaseManifest) -> None:
    """Recompute typed items, counts, group hashes and outer hash or fail closed."""

    try:
        validated = ReleaseManifest.model_validate(manifest.model_dump(mode="python"))
    except ValidationError as exc:
        raise ReleaseManifestIntegrityError("manifest schema is invalid") from exc
    for items_field, digest_field, model in _ARTIFACT_FIELDS:
        items = getattr(validated, items_field)
        digest = getattr(validated, digest_field)
        try:
            canonical = _canonical_models(items, model)
        except ValidationError as exc:
            raise ReleaseManifestIntegrityError(f"{items_field} is invalid") from exc
        if items != canonical:
            raise ReleaseManifestIntegrityError(f"{items_field} is not canonical")
        expected = _digest(items)
        if digest != expected:
            raise ReleaseManifestIntegrityError(
                f"{items_field}/{digest_field} mismatch"
            )
    if validated.manifest_sha256 != _sha256(_manifest_payload(validated)):
        raise ReleaseManifestIntegrityError("manifest_sha256 mismatch")


def _snapshot_fact_item(fact: RowMapping) -> dict[str, object]:
    evidence = tuple(
        CanonicalEvidence.model_validate_json(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
        for item in fact["evidence"]
    )
    return {
        "space_id": fact["space_id"],
        "snapshot_id": fact["snapshot_id"],
        "claim_id": fact["claim_id"],
        "revision_no": fact["revision_no"],
        "product_id": fact["product_id"],
        "product_version_id": fact["product_version_id"],
        "product_code": fact["product_code"],
        "product_name": fact["product_name"],
        "version_label": fact["version_label"],
        "predicate": fact["predicate"],
        "field_name": fact["field_name"],
        "field_group": fact["field_group"],
        "value_state": fact["value_state"],
        "value": fact["value"],
        "effective_from": fact["effective_from"],
        "effective_to": fact["effective_to"],
        "confidence": fact["confidence"],
        "schema_version": fact["schema_version"],
        "evidence": evidence,
    }


def _page_item(page: Mapping[str, object]) -> dict[str, object]:
    result = dict(page)
    for field in ("source_refs", "chunk_refs"):
        value = result.get(field)
        if isinstance(value, list):
            result[field] = tuple(value)
    metadata = result.get("page_metadata")
    if isinstance(metadata, Mapping):
        metadata_copy = dict(metadata)
        claim_ids = metadata_copy.get("claim_ids")
        if not isinstance(claim_ids, list) or not claim_ids or any(
            not isinstance(claim_id, str) or not claim_id for claim_id in claim_ids
        ):
            raise ReleaseManifestBuildError("frozen rendered page claims are invalid")
        if len(set(claim_ids)) != len(claim_ids):
            raise ReleaseManifestBuildError("frozen rendered page claims are invalid")
        for field in ("claim_ids", "schema_versions"):
            value = metadata_copy.get(field)
            if isinstance(value, list):
                metadata_copy[field] = tuple(value)
        result["page_metadata"] = metadata_copy
    return result


def _derive_directory_and_relationships(
    facts: Sequence[CanonicalSnapshotFact],
    pages: Sequence[CanonicalPage],
    *,
    scope: KnowledgeScope,
    snapshot_id: str,
    schema_version: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    product_rows: dict[tuple[str, str], dict[str, object]] = {}
    product_claims: dict[tuple[str, str], set[str]] = {}
    for fact in facts:
        if fact.space_id != scope.space_id or fact.snapshot_id != snapshot_id:
            raise ReleaseManifestBuildError("frozen fact identity is invalid")
        for evidence in fact.evidence:
            if evidence.claim_id != fact.claim_id:
                raise ReleaseManifestBuildError("frozen evidence claim mismatch")
            if evidence.raw_kb_id != scope.raw_kb_id:
                raise ReleaseManifestBuildError("frozen evidence scope mismatch")
            if evidence.stale_at is not None:
                raise ReleaseManifestBuildError("frozen evidence stale state is invalid")
            linked = evidence.lineage_status == "linked"
            if linked and (evidence.chunk_id is None or evidence.chunk_hash is None):
                raise ReleaseManifestBuildError("frozen evidence lineage shape is invalid")
            if not linked and (
                evidence.chunk_id is not None or evidence.chunk_hash is not None
            ):
                raise ReleaseManifestBuildError("frozen evidence lineage shape is invalid")
        key = (fact.product_id, fact.product_version_id)
        identity: dict[str, object] = {
            "product_id": fact.product_id,
            "product_version_id": fact.product_version_id,
            "product_code": fact.product_code,
            "product_name": fact.product_name,
            "version_label": fact.version_label,
        }
        prior = product_rows.get(key)
        if prior is not None and prior != identity:
            raise ReleaseManifestBuildError("frozen fact product identity is inconsistent")
        product_rows[key] = identity
        product_claims.setdefault(key, set()).add(fact.claim_id)

    page_slugs: dict[tuple[str, str], list[str]] = {key: [] for key in product_rows}
    covered_claims: dict[tuple[str, str], set[str]] = {key: set() for key in product_rows}
    relationships: list[dict[str, object]] = []
    seen_page_slugs: set[str] = set()
    for page in pages:
        metadata = page.page_metadata
        if page.slug in seen_page_slugs:
            raise ReleaseManifestBuildError("duplicate page slug in frozen projection")
        seen_page_slugs.add(page.slug)
        if metadata.space_id != scope.space_id or metadata.snapshot_id != snapshot_id:
            raise ReleaseManifestBuildError("frozen page identity is invalid")
        if (
            metadata.schema_version != schema_version
            or metadata.schema_versions != (schema_version,)
        ):
            raise ReleaseManifestBuildError("frozen page schema identity is invalid")
        key = (metadata.entity_ids.product_id, metadata.entity_ids.product_version_id)
        if key not in product_rows:
            raise ReleaseManifestBuildError("frozen page has no matching fact identity")
        claim_ids = metadata.claim_ids
        if not claim_ids or len(set(claim_ids)) != len(claim_ids):
            raise ReleaseManifestBuildError("frozen rendered page claims are invalid")
        claims = set(claim_ids)
        if not claims <= product_claims[key]:
            raise ReleaseManifestBuildError("frozen page claim closure is invalid")
        if covered_claims[key] & claims:
            raise ReleaseManifestBuildError("frozen page claim closure is invalid")
        covered_claims[key].update(claims)
        page_slugs[key].append(page.slug)
        relationships.append(
            {
                "from_type": "product_version",
                "from_id": key[1],
                "relationship": "renders",
                "to_type": "page",
                "to_id": page.slug,
            }
        )
        relationships.extend(
            {
                "from_type": "page",
                "from_id": page.slug,
                "relationship": "contains_claim",
                "to_type": "claim",
                "to_id": claim_id,
            }
            for claim_id in claim_ids
        )

    for key, slugs in page_slugs.items():
        if slugs and covered_claims[key] != product_claims[key]:
            raise ReleaseManifestBuildError("frozen page claim closure is incomplete")

    directory = [
        row | {"page_slugs": tuple(sorted(page_slugs[key]))}
        for key, row in product_rows.items()
    ]
    return directory, relationships


def _has_dirty_frozen_projection(session: Session) -> bool:
    for collection in (session.new, session.dirty, session.deleted):
        for candidate in collection:
            if isinstance(candidate, (ReleaseSnapshot, SnapshotFact)):
                return True
    return False


def build_release_manifest_from_snapshot(
    session: Session,
    scope: KnowledgeScope,
    *,
    snapshot_id: str,
    schema_version: str,
    template_hashes: Iterable[str],
    model_plan_hash: str,
) -> ReleaseManifest:
    """Build only from an attested frozen 018 projection, never mutable Claims."""

    require_current_scope(session, scope)
    if _has_dirty_frozen_projection(session):
        raise ReleaseManifestBuildError("dirty frozen projection cannot be signed")
    snapshot_table = ReleaseSnapshot.__table__
    fact_table = SnapshotFact.__table__
    with session.no_autoflush:
        snapshot = session.execute(
            select(snapshot_table).where(
                snapshot_table.c.id == snapshot_id,
                snapshot_table.c.space_id == scope.space_id,
            )
        ).mappings().one_or_none()
    if snapshot is None:
        raise ReleaseManifestBuildError("snapshot unavailable")
    if snapshot["status"] not in {"building", "published"}:
        raise ReleaseManifestBuildError("snapshot projection is not signable")
    if snapshot["projection_frozen_at"] is None:
        raise ReleaseManifestBuildError("snapshot projection is not frozen")
    if snapshot["rendered_pages"] is None:
        raise ReleaseManifestBuildError("snapshot rendered pages are unavailable")

    with session.no_autoflush:
        rows = list(
            session.execute(
                select(fact_table).where(
                    fact_table.c.space_id == scope.space_id,
                    fact_table.c.snapshot_id == snapshot["id"],
                )
            ).mappings()
        )
    if any(row["schema_version"] != schema_version for row in rows):
        raise ReleaseManifestBuildError("snapshot schema identity mismatch")
    try:
        facts = _canonical_models(
            (_snapshot_fact_item(row) for row in rows), CanonicalSnapshotFact
        )
        pages = _canonical_models(
            (_page_item(page) for page in snapshot["rendered_pages"]), CanonicalPage
        )
    except ValidationError as exc:
        raise ReleaseManifestBuildError("frozen snapshot artifact is invalid") from exc
    directory, relationships = _derive_directory_and_relationships(
        facts,
        pages,
        scope=scope,
        snapshot_id=snapshot["id"],
        schema_version=schema_version,
    )
    return build_release_manifest(
        schema_version=schema_version,
        space_id=scope.space_id,
        snapshot_id=snapshot["id"],
        read_model_version=snapshot["read_model_version"],
        template_hashes=template_hashes,
        model_plan_hash=model_plan_hash,
        facts=facts,
        rendered_pages=pages,
        directory_entries=directory,
        relationships=relationships,
    )
