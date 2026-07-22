"""OpenSpec 029 staging candidate and fail-closed production Wiki boundary."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.knowledge.release_manifest import (
    ReleaseManifest,
    ReleaseManifestBuildError,
    build_release_manifest_from_snapshot,
)
from insurance_harness.knowledge.tables import ReleaseSnapshot

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
    "request_production_wiki_publish",
]
