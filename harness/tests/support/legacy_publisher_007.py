"""Private characterization harness for the retired 007 caller-Session API."""

import uuid

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.db.base import utcnow
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge.pages import (
    PageClaimView,
    RenderedPage,
    build_page_claims,
    product_page_slug,
    render_product_page,
)
from insurance_harness.knowledge.tables import (
    ChangeSet,
    Claim,
    ClaimEvidence,
    ClaimRevision,
    CurrentRelease,
    ReleaseSnapshot,
    SnapshotClaim,
)
from insurance_harness.schemas import SchemaRegistry
from tests.support.release_publisher_018 import (
    PublishResult,
    RollbackResult,
    _require_label_available,
    _require_scoped_product_version,
    _require_scoped_snapshot,
    _upsert_page,
    _validate_publish_metadata,
    _validate_rollback_metadata,
    _validate_scope,
)


def _snapshot_claims_for_publish(
    session: Session,
    scope: KnowledgeScope,
    product_version_id: str,
    views: list[PageClaimView],
) -> list[Claim]:
    claim_ids = {view.claim_id for view in views}
    if not claim_ids:
        return []
    claims = list(
        session.execute(
            select(Claim).where(
                Claim.space_id == scope.space_id,
                Claim.product_version_id == product_version_id,
                Claim.id.in_(claim_ids),
                Claim.status == "published",
            )
        ).scalars()
    )
    if {claim.id for claim in claims} != claim_ids:
        raise ScopeViolation("scope mismatch")
    view_by_claim = {view.claim_id: view for view in views}
    if any(not view_by_claim[claim.id].evidence for claim in claims):
        raise ScopeViolation("scope mismatch")
    revision_pairs = set(
        session.execute(
            select(ClaimRevision.claim_id, ClaimRevision.revision_no)
            .join(Claim, Claim.id == ClaimRevision.claim_id)
            .where(
                Claim.space_id == scope.space_id,
                ClaimRevision.claim_id.in_(claim_ids),
            )
        ).all()
    )
    if any(
        (claim.id, claim.current_revision) not in revision_pairs for claim in claims
    ):
        raise ScopeViolation("scope mismatch")
    return claims


def _validate_rollback_pages(
    session: Session,
    scope: KnowledgeScope,
    snapshot: ReleaseSnapshot,
    pages: list[RenderedPage],
) -> None:
    frozen_rows = list(
        session.execute(
            select(SnapshotClaim).where(
                SnapshotClaim.space_id == scope.space_id,
                SnapshotClaim.snapshot_id == snapshot.id,
            )
        ).scalars()
    )
    frozen_by_claim = {row.claim_id: row.revision_no for row in frozen_rows}
    claim_ids = set(frozen_by_claim)
    if not pages or not claim_ids:
        raise ScopeViolation("scope mismatch")
    claims = (
        list(
            session.execute(
                select(Claim).where(
                    Claim.space_id == scope.space_id,
                    Claim.id.in_(claim_ids),
                )
            ).scalars()
        )
        if claim_ids
        else []
    )
    if {claim.id for claim in claims} != claim_ids:
        raise ScopeViolation("scope mismatch")

    claims_by_id = {claim.id: claim for claim in claims}
    page_claim_ids: set[str] = set()
    page_slugs: set[str] = set()
    for page in pages:
        if page.slug in page_slugs:
            raise ScopeViolation("scope mismatch")
        page_slugs.add(page.slug)
        metadata = page.page_metadata
        if metadata.get("snapshot_id") != snapshot.id:
            raise ScopeViolation("scope mismatch")
        entity_ids = metadata.get("entity_ids")
        if not isinstance(entity_ids, dict):
            raise ScopeViolation("scope mismatch")
        version_id = entity_ids.get("product_version_id")
        product_id = entity_ids.get("product_id")
        if not isinstance(version_id, str) or not isinstance(product_id, str):
            raise ScopeViolation("scope mismatch")
        version, product = _require_scoped_product_version(session, scope, version_id)
        if product.id != product_id:
            raise ScopeViolation("scope mismatch")
        if page.slug != product_page_slug(product.product_code, version.version_label):
            raise ScopeViolation("scope mismatch")
        raw_claim_ids = metadata.get("claim_ids")
        if not isinstance(raw_claim_ids, list) or not all(
            isinstance(claim_id, str) for claim_id in raw_claim_ids
        ):
            raise ScopeViolation("scope mismatch")
        claim_ids_for_page = set(raw_claim_ids)
        if (
            not claim_ids_for_page
            or len(claim_ids_for_page) != len(raw_claim_ids)
            or page_claim_ids.intersection(claim_ids_for_page)
        ):
            raise ScopeViolation("scope mismatch")
        page_claim_ids.update(claim_ids_for_page)
        for claim_id in claim_ids_for_page:
            claim = claims_by_id.get(claim_id)
            if (
                claim is None
                or claim.space_id != scope.space_id
                or claim.product_version_id != version_id
            ):
                raise ScopeViolation("scope mismatch")

    if page_claim_ids != claim_ids:
        raise ScopeViolation("scope mismatch")
    revision_pairs = (
        set(
            session.execute(
                select(ClaimRevision.claim_id, ClaimRevision.revision_no)
                .join(Claim, Claim.id == ClaimRevision.claim_id)
                .where(
                    Claim.space_id == scope.space_id,
                    ClaimRevision.claim_id.in_(claim_ids),
                )
            ).all()
        )
        if claim_ids
        else set()
    )
    if any(
        (claim_id, revision_no) not in revision_pairs
        for claim_id, revision_no in frozen_by_claim.items()
    ):
        raise ScopeViolation("scope mismatch")
    evidence_claim_ids = (
        set(
            session.execute(
                select(ClaimEvidence.claim_id)
                .join(Claim, Claim.id == ClaimEvidence.claim_id)
                .where(
                    Claim.space_id == scope.space_id,
                    ClaimEvidence.claim_id.in_(claim_ids),
                )
            ).scalars()
        )
        if claim_ids
        else set()
    )
    if evidence_claim_ids != claim_ids:
        raise ScopeViolation("scope mismatch")


def _move_pointer(
    session: Session,
    scope: KnowledgeScope,
    snapshot_id: str,
) -> None:
    pointer = session.get(CurrentRelease, (scope.space_id, "current"))
    if pointer is None:
        session.add(
            CurrentRelease(
                space_id=scope.space_id,
                id="current",
                snapshot_id=snapshot_id,
            )
        )
    else:
        pointer.snapshot_id = snapshot_id


async def legacy_publish_product_version(
    session: Session,
    client: WeKnoraClient,
    scope: KnowledgeScope,
    *,
    product_version_id: str,
    label: str,
    published_by: str = "publisher",
    registry: SchemaRegistry | None = None,
    field_names: dict[str, str] | None = None,
    doc_titles: dict[str, str] | None = None,
    schema_version: str = "",
    notes: str | None = None,
) -> PublishResult:
    """Run the retired behavior only for pre-018 regression characterization."""
    _validate_scope(session, scope)
    _validate_publish_metadata(label, published_by)
    version, product = _require_scoped_product_version(
        session,
        scope,
        product_version_id,
    )
    _require_label_available(session, scope, label)
    snapshot_id = str(uuid.uuid4())

    views = build_page_claims(
        session,
        scope,
        product_version_id,
        registry=registry,
        field_names=field_names,
        doc_titles=doc_titles,
    )
    page = render_product_page(
        views,
        product_code=product.product_code,
        version_label=version.version_label,
        product_name=product.canonical_name,
        product_id=product.id,
        product_version_id=product_version_id,
        snapshot_id=snapshot_id,
        schema_version=schema_version,
    )
    claims = _snapshot_claims_for_publish(
        session,
        scope,
        product_version_id,
        views,
    )
    if not claims:
        raise ScopeViolation("scope mismatch")

    await _upsert_page(client, scope, page)
    now = utcnow()
    snapshot = ReleaseSnapshot(
        id=snapshot_id,
        space_id=scope.space_id,
        label=label,
        published_by=published_by,
        notes=notes,
        rendered_pages=[page.model_dump(mode="json")],
        status="published",
        read_model_version=1,
        projection_frozen_at=now,
        published_at=now,
    )
    session.add(snapshot)
    for claim in claims:
        session.add(
            SnapshotClaim(
                space_id=scope.space_id,
                snapshot_id=snapshot.id,
                claim_id=claim.id,
                revision_no=claim.current_revision,
            )
        )
    _move_pointer(session, scope, snapshot.id)
    session.flush()

    return PublishResult(
        snapshot_id=snapshot.id,
        snapshot_label=snapshot.label,
        pages=[page],
    )


async def legacy_rollback_to_snapshot(
    session: Session,
    client: WeKnoraClient,
    scope: KnowledgeScope,
    *,
    snapshot_id: str,
    actor: str = "publisher",
    reason: str = "rollback",
) -> RollbackResult:
    """Run the retired rollback only for pre-018 regression characterization."""
    _validate_scope(session, scope)
    _validate_rollback_metadata(actor, reason)
    snapshot = _require_scoped_snapshot(session, scope, snapshot_id)
    try:
        pages = [
            RenderedPage.model_validate(raw)
            for raw in (snapshot.rendered_pages or [])
        ]
    except (TypeError, ValidationError) as exc:
        raise ScopeViolation("scope mismatch") from exc
    _validate_rollback_pages(session, scope, snapshot, pages)

    with session.begin_nested():
        change_set = ChangeSet(
            space_id=scope.space_id,
            source_kind="rollback",
            knowledge_ids=None,
            external_record_id=f"{snapshot.id}:{uuid.uuid4().hex}",
            source_revision=reason,
            status="applied",
            created_by=actor,
        )
        session.add(change_set)
        _move_pointer(session, scope, snapshot.id)
        session.flush()

        for page in pages:
            await _upsert_page(client, scope, page)

    return RollbackResult(
        snapshot_id=snapshot.id,
        change_set_id=change_set.id,
        pages=pages,
    )
