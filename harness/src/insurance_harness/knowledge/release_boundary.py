"""OpenSpec 029 staging candidate and fail-closed production Wiki boundary."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.knowledge.pages import render_snapshot_pages
from insurance_harness.knowledge.release_manifest import (
    ReleaseManifest,
    ReleaseManifestBuildError,
    ReleaseManifestIntegrityError,
    build_release_manifest_from_snapshot,
    verify_release_manifest,
)
from insurance_harness.knowledge.snapshots import (
    SnapshotBuildError,
    SnapshotFactView,
    build_snapshot_facts,
)
from insurance_harness.knowledge.tables import (
    Claim,
    ClaimRevision,
    CurrentRelease,
    ReleaseManifestRecord,
    ReleaseSnapshot,
    SnapshotClaim,
    SnapshotFact,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")


class ProductionWikiPublishRequest(_StrictFrozenModel):
    """Fully explicit request identity with no client or execution capability."""

    scope: KnowledgeScope
    snapshot_id: str
    manifest_hash: str
    principal: str
    reason: str

    @field_validator("snapshot_id", "principal", "reason")
    @classmethod
    def _canonical_text(cls, value: str) -> str:
        if not value or value != value.strip():
            raise ValueError("production Wiki request identity must be canonical")
        return value

    @field_validator("manifest_hash")
    @classmethod
    def _exact_manifest_hash(cls, value: str) -> str:
        if _SHA256.fullmatch(value) is None:
            raise ValueError("manifest_hash must be an exact lowercase SHA-256")
        return value


class P1CapabilityMissing(_StrictFrozenModel):
    """Typed terminal block while ordinary-user production Wiki isolation is absent."""

    status: Literal["blocked"] = "blocked"
    code: Literal["p1_capability_missing"] = "p1_capability_missing"


def _normalize_target_facts(
    facts: Iterable[SnapshotFactView],
) -> tuple[SnapshotFactView, ...]:
    normalized_facts = []
    for fact in facts:
        normalized_facts.append(
            fact.model_copy(
                update={
                    "evidence": tuple(
                        evidence.model_copy(
                            update={
                                field: (
                                    getattr(evidence, field).replace(tzinfo=UTC)
                                    if getattr(evidence, field).tzinfo is None
                                    else getattr(evidence, field).astimezone(UTC)
                                )
                                for field in (
                                    "extracted_at",
                                    "created_at",
                                    "updated_at",
                                )
                            }
                        )
                        for evidence in fact.evidence
                    )
                }
            )
        )
    return tuple(normalized_facts)


def canonical_target_facts_hash(facts: Iterable[SnapshotFactView]) -> str:
    """Hash the complete mutable-source projection with normalized UTC evidence."""

    payload = [
        fact.model_dump(mode="json", exclude={"snapshot_id"})
        for fact in _normalize_target_facts(facts)
    ]
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _fact_without_snapshot_id(value: object) -> object:
    if isinstance(value, SnapshotFactView):
        return value.model_dump(mode="json", exclude={"snapshot_id"})
    if isinstance(value, dict):
        return {key: item for key, item in value.items() if key != "snapshot_id"}
    raise ReleaseManifestBuildError("candidate base fact is invalid")


def build_staging_candidate_manifest(
    session: Session,
    scope: KnowledgeScope,
    *,
    snapshot_id: str,
    schema_version: str,
    template_hashes: Iterable[str],
    model_plan_hash: str,
) -> ReleaseManifest:
    """Build a manifest only for an isolated, frozen, still-building snapshot."""

    require_current_scope(session, scope)
    snapshot = session.scalar(
        select(ReleaseSnapshot).where(
            ReleaseSnapshot.space_id == scope.space_id,
            ReleaseSnapshot.id == snapshot_id,
        )
    )
    if (
        snapshot is None
        or snapshot.status != "building"
        or snapshot.projection_frozen_at is None
    ):
        raise ReleaseManifestBuildError("staging candidate is unavailable")
    return build_release_manifest_from_snapshot(
        session,
        scope,
        snapshot_id=snapshot_id,
        schema_version=schema_version,
        template_hashes=template_hashes,
        model_plan_hash=model_plan_hash,
    )


def build_fresh_staging_candidate_manifest(
    session: Session,
    scope: KnowledgeScope,
    *,
    snapshot_id: str,
    compiled_at: str,
    expected_base_snapshot_id: str | None,
    expected_base_manifest_hash: str | None,
    target_claim_revisions: Iterable[tuple[str, int]],
    authorized_change_items: Iterable[tuple[str, str | None]],
    expected_target_facts_hash: str,
    schema_version: str,
    template_hashes: Iterable[str],
    model_plan_hash: str,
) -> ReleaseManifest:
    """Create a fresh DB-only full-Space projection from an exact sealed inventory."""

    require_current_scope(session, scope)
    if session.get(ReleaseSnapshot, snapshot_id) is not None:
        raise ReleaseManifestBuildError("candidate snapshot already exists")
    if session.scalar(
        select(ReleaseSnapshot.id).where(
            ReleaseSnapshot.space_id == scope.space_id,
            ReleaseSnapshot.label == snapshot_id,
        )
    ) is not None:
        raise ReleaseManifestBuildError("candidate snapshot label already exists")
    current_snapshot_id = session.scalar(
        select(CurrentRelease.snapshot_id).where(
            CurrentRelease.space_id == scope.space_id
        )
    )
    if current_snapshot_id != expected_base_snapshot_id:
        raise ReleaseManifestBuildError("candidate base snapshot drifted")
    base_facts: dict[str, object] = {}
    if expected_base_snapshot_id is None:
        if expected_base_manifest_hash is not None:
            raise ReleaseManifestBuildError("candidate base identity is incomplete")
        base_revisions: dict[str, int] = {}
    else:
        record = session.scalar(
            select(ReleaseManifestRecord).where(
                ReleaseManifestRecord.space_id == scope.space_id,
                ReleaseManifestRecord.snapshot_id == expected_base_snapshot_id,
                ReleaseManifestRecord.manifest_hash == expected_base_manifest_hash,
            )
        )
        if record is None:
            raise ReleaseManifestBuildError("candidate base manifest drifted")
        try:
            base_manifest = ReleaseManifest.model_validate_json(
                json.dumps(
                    record.payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
            )
            verify_release_manifest(base_manifest)
        except (
            ValidationError,
            ReleaseManifestIntegrityError,
            TypeError,
            ValueError,
        ) as exc:
            raise ReleaseManifestBuildError("candidate base manifest is invalid") from exc
        if (
            base_manifest.space_id != scope.space_id
            or base_manifest.snapshot_id != expected_base_snapshot_id
            or base_manifest.manifest_sha256 != expected_base_manifest_hash
        ):
            raise ReleaseManifestBuildError("candidate base manifest identity drifted")
        base_rows = tuple(
            session.scalars(
                select(SnapshotFact).where(
                    SnapshotFact.space_id == scope.space_id,
                    SnapshotFact.snapshot_id == expected_base_snapshot_id,
                )
            )
        )
        base_revisions = {row.claim_id: row.revision_no for row in base_rows}
        base_facts = {
            item.claim_id: item.model_dump(mode="json") for item in base_manifest.facts
        }
        if set(base_facts) != set(base_revisions):
            raise ReleaseManifestBuildError("candidate base fact inventory drifted")
    target_pairs = tuple(target_claim_revisions)
    target_revisions = dict(target_pairs)
    if len(target_revisions) != len(target_pairs):
        raise ReleaseManifestBuildError("candidate target inventory is duplicated")
    try:
        frozen_at = datetime.fromisoformat(compiled_at)
    except ValueError as exc:
        raise ReleaseManifestBuildError("candidate compiled_at is invalid") from exc
    if frozen_at.tzinfo is None or frozen_at.utcoffset() is None:
        raise ReleaseManifestBuildError("candidate compiled_at must be timezone-aware")
    frozen_at = frozen_at.astimezone(UTC)
    try:
        facts = build_snapshot_facts(session, scope, snapshot_id=snapshot_id)
    except SnapshotBuildError as exc:
        raise ReleaseManifestBuildError("candidate facts cannot be frozen") from exc
    facts = _normalize_target_facts(facts)
    observed_revisions = {fact.claim_id: fact.revision_no for fact in facts}
    if observed_revisions != target_revisions:
        raise ReleaseManifestBuildError("candidate target claim inventory drifted")
    changed_claim_ids = {
        claim_id
        for claim_id, revision_no in target_revisions.items()
        if base_revisions.get(claim_id) != revision_no
    }
    changed_claim_ids.update(set(base_revisions) - set(target_revisions))
    authorized_pairs = tuple(authorized_change_items)
    authorized_by_id = dict(authorized_pairs)
    if len(authorized_by_id) != len(authorized_pairs):
        raise ReleaseManifestBuildError("candidate change lineage is duplicated")
    if None in authorized_by_id.values() or set(authorized_by_id.values()) != changed_claim_ids:
        raise ReleaseManifestBuildError("candidate change lineage is incomplete")
    for claim_id in changed_claim_ids:
        claim = session.scalar(
            select(Claim).where(Claim.space_id == scope.space_id, Claim.id == claim_id)
        )
        if claim is None:
            raise ReleaseManifestBuildError("candidate changed claim is unavailable")
        revision = session.scalar(
            select(ClaimRevision).where(
                ClaimRevision.claim_id == claim_id,
                ClaimRevision.revision_no == claim.current_revision,
            )
        )
        if (
            revision is None
            or revision.change_item_id not in authorized_by_id
            or authorized_by_id[revision.change_item_id] != claim_id
        ):
            raise ReleaseManifestBuildError("candidate claim lineage is unsealed")
    target_by_claim = {fact.claim_id: fact for fact in facts}
    for claim_id, revision_no in target_revisions.items():
        if base_revisions.get(claim_id) != revision_no:
            continue
        if canonical_target_facts_hash((target_by_claim[claim_id],)) != hashlib.sha256(
            json.dumps(
                [_fact_without_snapshot_id(base_facts[claim_id])],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest():
            raise ReleaseManifestBuildError("candidate same-revision lineage drifted")
    if canonical_target_facts_hash(facts) != expected_target_facts_hash:
        raise ReleaseManifestBuildError("candidate target facts drifted")
    pages = render_snapshot_pages(
        facts,
        space_id=scope.space_id,
        snapshot_id=snapshot_id,
        compiled_at=frozen_at,
    )
    snapshot = ReleaseSnapshot(
        id=snapshot_id,
        space_id=scope.space_id,
        label=snapshot_id,
        rendered_pages=[page.model_dump(mode="json") for page in pages],
        status="building",
        read_model_version=1,
        projection_frozen_at=None,
        published_at=None,
        published_by="release-governance-cli",
    )
    session.add(snapshot)
    session.flush()
    for fact in facts:
        session.add(
            SnapshotClaim(
                space_id=scope.space_id,
                snapshot_id=snapshot_id,
                claim_id=fact.claim_id,
                revision_no=fact.revision_no,
            )
        )
        session.add(
            SnapshotFact(
                space_id=scope.space_id,
                snapshot_id=snapshot_id,
                claim_id=fact.claim_id,
                revision_no=fact.revision_no,
                product_id=fact.product_id,
                product_version_id=fact.product_version_id,
                product_code=fact.product_code,
                product_name=fact.product_name,
                version_label=fact.version_label,
                predicate=fact.predicate,
                field_name=fact.field_name,
                field_group=fact.field_group,
                value_state=fact.value_state,
                value=fact.value,
                effective_from=fact.effective_from,
                effective_to=fact.effective_to,
                confidence=fact.confidence,
                schema_version=fact.schema_version,
                evidence=[item.model_dump(mode="json") for item in fact.evidence],
            )
        )
    session.flush()
    snapshot.projection_frozen_at = frozen_at
    session.flush()
    return build_release_manifest_from_snapshot(
        session,
        scope,
        snapshot_id=snapshot_id,
        schema_version=schema_version,
        template_hashes=template_hashes,
        model_plan_hash=model_plan_hash,
    )


def request_production_wiki_publish(
    request: ProductionWikiPublishRequest,
) -> P1CapabilityMissing:
    """Always block: P-1 ordinary-user production Wiki capability does not exist."""

    del request
    return P1CapabilityMissing()


__all__ = [
    "P1CapabilityMissing",
    "ProductionWikiPublishRequest",
    "build_staging_candidate_manifest",
    "build_fresh_staging_candidate_manifest",
    "request_production_wiki_publish",
]
