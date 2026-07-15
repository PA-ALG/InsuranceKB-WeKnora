"""Pointer-only SnapshotFact reader with typed coverage gaps (OpenSpec 018)."""

import copy
from collections.abc import Callable
from datetime import date
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    require_current_scope,
)
from insurance_harness.knowledge.snapshots import FrozenEvidence, SnapshotFactView
from insurance_harness.knowledge.tables import (
    CurrentRelease,
    ReleaseSnapshot,
    SnapshotFact,
)

CoverageGapCode = Literal[
    "no_release",
    "legacy_release",
    "product_not_found",
    "predicate_not_found",
    "effective_date_miss",
]


class SnapshotReadError(RuntimeError):
    """A current version-1 snapshot is internally incomplete or malformed."""


class SnapshotFactsResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    facts: tuple[SnapshotFactView, ...]


class CoverageGap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: CoverageGapCode
    snapshot_id: str | None


def _fact_view(row: SnapshotFact) -> SnapshotFactView:
    if not isinstance(row.evidence, list):
        raise SnapshotReadError("snapshot evidence is unavailable")
    try:
        evidence = tuple(
            FrozenEvidence.model_validate(item) for item in row.evidence
        )
        return SnapshotFactView(
            space_id=row.space_id,
            snapshot_id=row.snapshot_id,
            claim_id=row.claim_id,
            revision_no=row.revision_no,
            product_id=row.product_id,
            product_version_id=row.product_version_id,
            product_code=row.product_code,
            product_name=row.product_name,
            version_label=row.version_label,
            predicate=row.predicate,
            field_name=row.field_name,
            field_group=row.field_group,
            value_state=cast(
                Literal["present", "absent_explicitly"], row.value_state
            ),
            value=copy.deepcopy(row.value),
            effective_from=row.effective_from,
            effective_to=row.effective_to,
            confidence=row.confidence,
            schema_version=row.schema_version,
            evidence=evidence,
        )
    except ValidationError as exc:
        raise SnapshotReadError("snapshot fact is unavailable") from exc


def _sort_key(
    fact: SnapshotFactView,
) -> tuple[str, str, str, date, date, str, int]:
    return (
        fact.product_id,
        fact.product_version_id,
        fact.predicate,
        fact.effective_from or date.min,
        fact.effective_to or date.max,
        fact.claim_id,
        fact.revision_no,
    )


class SnapshotReader:
    """Open a short-lived Session and read only the current frozen projection."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    @staticmethod
    def _require_product_owner(
        session: Session,
        scope: KnowledgeScope,
        *,
        product_id: str | None,
        product_version_id: str | None,
    ) -> None:
        if product_id is not None:
            owned_product = session.scalar(
                select(InsuranceProduct.id).where(
                    InsuranceProduct.id == product_id,
                    InsuranceProduct.space_id == scope.space_id,
                )
            )
            if owned_product is None:
                raise ScopeViolation("scope mismatch")
        if product_version_id is not None:
            owned_version = session.scalar(
                select(ProductVersion.id).where(
                    ProductVersion.id == product_version_id,
                    ProductVersion.space_id == scope.space_id,
                )
            )
            if owned_version is None:
                raise ScopeViolation("scope mismatch")

    def current(
        self,
        scope: KnowledgeScope,
        *,
        product_id: str | None = None,
        product_version_id: str | None = None,
        predicate: str | None = None,
        effective_on: date | None = None,
    ) -> SnapshotFactsResult | CoverageGap:
        with self._session_factory() as session:
            require_current_scope(session, scope)
            snapshot_id = session.scalar(
                select(CurrentRelease.snapshot_id).where(
                    CurrentRelease.space_id == scope.space_id
                )
            )
            if snapshot_id is None:
                return CoverageGap(code="no_release", snapshot_id=None)
            snapshot = session.scalar(
                select(ReleaseSnapshot).where(
                    ReleaseSnapshot.id == snapshot_id,
                    ReleaseSnapshot.space_id == scope.space_id,
                )
            )
            if snapshot is None or snapshot.status != "published":
                raise ScopeViolation("scope mismatch")
            if snapshot.read_model_version == 0:
                return CoverageGap(
                    code="legacy_release", snapshot_id=snapshot.id
                )
            if (
                snapshot.read_model_version != 1
                or snapshot.projection_frozen_at is None
            ):
                raise SnapshotReadError("current snapshot is unavailable")

            self._require_product_owner(
                session,
                scope,
                product_id=product_id,
                product_version_id=product_version_id,
            )
            rows = session.scalars(
                select(SnapshotFact).where(
                    SnapshotFact.space_id == scope.space_id,
                    SnapshotFact.snapshot_id == snapshot.id,
                )
            )
            facts = sorted((_fact_view(row) for row in rows), key=_sort_key)
            if product_id is not None:
                facts = [fact for fact in facts if fact.product_id == product_id]
            if product_version_id is not None:
                facts = [
                    fact
                    for fact in facts
                    if fact.product_version_id == product_version_id
                ]
            if not facts:
                return CoverageGap(
                    code="product_not_found", snapshot_id=snapshot.id
                )
            if predicate is not None:
                facts = [fact for fact in facts if fact.predicate == predicate]
                if not facts:
                    return CoverageGap(
                        code="predicate_not_found", snapshot_id=snapshot.id
                    )
            if effective_on is not None:
                facts = [
                    fact
                    for fact in facts
                    if (
                        fact.effective_from is None
                        or fact.effective_from <= effective_on
                    )
                    and (
                        fact.effective_to is None
                        or effective_on <= fact.effective_to
                    )
                ]
                if not facts:
                    return CoverageGap(
                        code="effective_date_miss", snapshot_id=snapshot.id
                    )
            return SnapshotFactsResult(
                snapshot_id=snapshot.id,
                facts=tuple(sorted(facts, key=_sort_key)),
            )
