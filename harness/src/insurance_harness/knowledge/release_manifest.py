"""Complete deterministic ReleaseManifest contracts (OpenSpec 029 RA1)."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    ValidationError,
    field_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.knowledge.tables import ReleaseSnapshot, SnapshotFact

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_ARTIFACT_FIELDS = (
    ("facts", "facts_digest"),
    ("rendered_pages", "rendered_pages_digest"),
    ("directory_entries", "directory_digest"),
    ("relationships", "relationships_digest"),
)


class ReleaseManifestIntegrityError(ValueError):
    """A manifest no longer matches its canonical artifact or outer hashes."""


class ReleaseManifestBuildError(ValueError):
    """A frozen, scoped snapshot cannot produce a complete manifest."""


def _canonical_json_bytes(value: JsonValue | dict[str, Any] | list[Any]) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ReleaseManifestIntegrityError("artifact is not canonical JSON") from exc
    return encoded.encode("utf-8")


def _sha256(value: JsonValue | dict[str, Any] | list[Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _valid_sha256(value: str) -> str:
    if _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError("must be a lowercase SHA-256")
    return value


def _canonical_items(
    items: Iterable[Mapping[str, JsonValue]],
) -> tuple[dict[str, JsonValue], ...]:
    copied = [copy.deepcopy(dict(item)) for item in items]
    try:
        return tuple(sorted(copied, key=_canonical_json_bytes))
    except ReleaseManifestIntegrityError as exc:
        raise ValueError("artifact item must be canonical JSON") from exc


class ArtifactDigest(BaseModel):
    """Count and SHA-256 of one explicit canonical JSON artifact array."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    count: int = Field(ge=0)
    sha256: str

    _validate_sha256 = field_validator("sha256")(_valid_sha256)


class ReleaseManifest(BaseModel):
    """Immutable hash envelope over every MVP serving artifact group."""

    model_config = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")

    schema_version: str
    space_id: str
    snapshot_id: str
    read_model_version: int = Field(gt=0)
    template_hashes: tuple[str, ...]
    model_plan_hash: str
    facts: tuple[dict[str, JsonValue], ...]
    facts_digest: ArtifactDigest
    rendered_pages: tuple[dict[str, JsonValue], ...]
    rendered_pages_digest: ArtifactDigest
    directory_entries: tuple[dict[str, JsonValue], ...]
    directory_digest: ArtifactDigest
    relationships: tuple[dict[str, JsonValue], ...]
    relationships_digest: ArtifactDigest
    manifest_sha256: str

    @field_validator("schema_version", "space_id", "snapshot_id")
    @classmethod
    def _validate_identity(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("release identity must be non-empty canonical text")
        return value

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


def _digest(items: Sequence[dict[str, JsonValue]]) -> ArtifactDigest:
    return ArtifactDigest(count=len(items), sha256=_sha256(list(items)))


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
    facts: Iterable[Mapping[str, JsonValue]],
    rendered_pages: Iterable[Mapping[str, JsonValue]],
    directory_entries: Iterable[Mapping[str, JsonValue]],
    relationships: Iterable[Mapping[str, JsonValue]],
) -> ReleaseManifest:
    """Canonicalize four complete artifact groups and bind their full payload hash."""

    canonical_facts = _canonical_items(facts)
    canonical_pages = _canonical_items(rendered_pages)
    canonical_directory = _canonical_items(directory_entries)
    canonical_relationships = _canonical_items(relationships)
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


def verify_release_manifest(manifest: ReleaseManifest) -> None:
    """Recompute item order, counts, group hashes and outer hash or fail closed."""

    try:
        validated = ReleaseManifest.model_validate(manifest.model_dump(mode="python"))
    except ValidationError as exc:
        raise ReleaseManifestIntegrityError("manifest schema is invalid") from exc
    for items_field, digest_field in _ARTIFACT_FIELDS:
        items = getattr(validated, items_field)
        digest = getattr(validated, digest_field)
        try:
            canonical = _canonical_items(items)
        except ValueError as exc:
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


def _snapshot_fact_item(fact: SnapshotFact) -> dict[str, JsonValue]:
    return {
        "space_id": fact.space_id,
        "snapshot_id": fact.snapshot_id,
        "claim_id": fact.claim_id,
        "revision_no": fact.revision_no,
        "product_id": fact.product_id,
        "product_version_id": fact.product_version_id,
        "product_code": fact.product_code,
        "product_name": fact.product_name,
        "version_label": fact.version_label,
        "predicate": fact.predicate,
        "field_name": fact.field_name,
        "field_group": fact.field_group,
        "value_state": fact.value_state,
        "value": copy.deepcopy(fact.value),
        "effective_from": fact.effective_from.isoformat() if fact.effective_from else None,
        "effective_to": fact.effective_to.isoformat() if fact.effective_to else None,
        "confidence": fact.confidence,
        "schema_version": fact.schema_version,
        "evidence": cast(JsonValue, copy.deepcopy(fact.evidence)),
    }


def _page_identity(page: Mapping[str, JsonValue], snapshot_id: str) -> tuple[str, str, str]:
    slug = page.get("slug")
    metadata = page.get("page_metadata")
    if not isinstance(slug, str) or not slug or not isinstance(metadata, dict):
        raise ReleaseManifestBuildError("frozen rendered page identity is invalid")
    if metadata.get("snapshot_id") != snapshot_id:
        raise ReleaseManifestBuildError("frozen rendered page identity is invalid")
    entity_ids = metadata.get("entity_ids")
    if not isinstance(entity_ids, dict):
        raise ReleaseManifestBuildError("frozen rendered page identity is invalid")
    product_id = entity_ids.get("product_id")
    version_id = entity_ids.get("product_version_id")
    if not isinstance(product_id, str) or not product_id:
        raise ReleaseManifestBuildError("frozen rendered page identity is invalid")
    if not isinstance(version_id, str) or not version_id:
        raise ReleaseManifestBuildError("frozen rendered page identity is invalid")
    return slug, product_id, version_id


def _derive_directory_and_relationships(
    facts: Sequence[dict[str, JsonValue]],
    pages: Sequence[dict[str, JsonValue]],
    snapshot_id: str,
) -> tuple[list[dict[str, JsonValue]], list[dict[str, JsonValue]]]:
    product_rows: dict[tuple[str, str], dict[str, JsonValue]] = {}
    for fact in facts:
        key = (str(fact["product_id"]), str(fact["product_version_id"]))
        identity = {
            "product_id": key[0],
            "product_version_id": key[1],
            "product_code": fact["product_code"],
            "product_name": fact["product_name"],
            "version_label": fact["version_label"],
        }
        prior = product_rows.get(key)
        if prior is not None and prior != identity:
            raise ReleaseManifestBuildError("frozen fact product identity is inconsistent")
        product_rows[key] = identity

    page_slugs: dict[tuple[str, str], list[str]] = {key: [] for key in product_rows}
    relationships: list[dict[str, JsonValue]] = []
    for page in pages:
        slug, product_id, version_id = _page_identity(page, snapshot_id)
        key = (product_id, version_id)
        if key not in product_rows:
            raise ReleaseManifestBuildError("frozen page has no matching fact identity")
        page_slugs[key].append(slug)
        relationships.append(
            {
                "from_type": "product_version",
                "from_id": version_id,
                "relationship": "renders",
                "to_type": "page",
                "to_id": slug,
            }
        )
        metadata = page["page_metadata"]
        assert isinstance(metadata, dict)
        claim_ids = metadata.get("claim_ids", [])
        if not isinstance(claim_ids, list) or any(
            not isinstance(claim_id, str) or not claim_id for claim_id in claim_ids
        ):
            raise ReleaseManifestBuildError("frozen rendered page claims are invalid")
        for claim_id in claim_ids:
            relationships.append(
                {
                    "from_type": "page",
                    "from_id": slug,
                    "relationship": "contains_claim",
                    "to_type": "claim",
                    "to_id": claim_id,
                }
            )

    directory: list[dict[str, JsonValue]] = [
        row | {"page_slugs": cast(JsonValue, sorted(page_slugs[key]))}
        for key, row in product_rows.items()
    ]
    return directory, relationships


def build_release_manifest_from_snapshot(
    session: Session,
    scope: KnowledgeScope,
    *,
    snapshot_id: str,
    schema_version: str,
    template_hashes: Iterable[str],
    model_plan_hash: str,
) -> ReleaseManifest:
    """Build only from a scope-attested frozen 018 projection, never mutable Claims."""

    require_current_scope(session, scope)
    with session.no_autoflush:
        snapshot = session.scalar(
            select(ReleaseSnapshot).where(
                ReleaseSnapshot.id == snapshot_id,
                ReleaseSnapshot.space_id == scope.space_id,
            )
        )
    if snapshot is None:
        raise ReleaseManifestBuildError("snapshot unavailable")
    if snapshot.status != "published" or snapshot.projection_frozen_at is None:
        raise ReleaseManifestBuildError("snapshot projection is not frozen")
    if snapshot.rendered_pages is None:
        raise ReleaseManifestBuildError("snapshot rendered pages are unavailable")

    with session.no_autoflush:
        rows = list(
            session.scalars(
                select(SnapshotFact).where(
                    SnapshotFact.space_id == scope.space_id,
                    SnapshotFact.snapshot_id == snapshot.id,
                )
            )
        )
    if any(row.schema_version != schema_version for row in rows):
        raise ReleaseManifestBuildError("snapshot schema identity mismatch")
    facts = [_snapshot_fact_item(row) for row in rows]
    pages = [copy.deepcopy(page) for page in snapshot.rendered_pages]
    directory, relationships = _derive_directory_and_relationships(
        facts, pages, snapshot.id
    )
    return build_release_manifest(
        schema_version=schema_version,
        space_id=scope.space_id,
        snapshot_id=snapshot.id,
        read_model_version=snapshot.read_model_version,
        template_hashes=template_hashes,
        model_plan_hash=model_plan_hash,
        facts=facts,
        rendered_pages=pages,
        directory_entries=directory,
        relationships=relationships,
    )
