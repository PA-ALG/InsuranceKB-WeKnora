"""WeKnora 发布器（changes 007/016；specs K5.2~K5.4、S1/S2/S4）。

published Claims → 产品限定页 → adapters/weknora 写 wiki 页（slug 串行化由客户端保证）。
每次发布记录 ReleaseSnapshot（冻结 (claim_id, revision_no) + 物化渲染产物）并移动
current_release 指针；回滚 = 按快照重发布 + 指针回切 + rollback ChangeSet 留痕（03 §5.2）。
"""

import uuid

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.adapters.weknora.errors import WeKnoraClientError
from insurance_harness.adapters.weknora.models import WeKnoraWikiPage
from insurance_harness.db.base import utcnow
from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.db.scope import (
    KnowledgeScope,
    ScopeViolation,
    require_current_scope,
)
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


class PublishResult(BaseModel):
    snapshot_id: str
    snapshot_label: str
    pages: list[RenderedPage] = Field(default_factory=list)


class RollbackResult(BaseModel):
    snapshot_id: str
    change_set_id: str
    pages: list[RenderedPage] = Field(default_factory=list)


def _page_to_wiki(page: RenderedPage) -> WeKnoraWikiPage:
    return WeKnoraWikiPage(
        slug=page.slug,
        title=page.title,
        status="published",  # 只发布 published；候选/草稿不出 Harness（03 §7）
        content=page.content,
        source_refs=page.source_refs,
        chunk_refs=page.chunk_refs,
        page_metadata=page.page_metadata,
    )


async def _upsert_page(
    client: WeKnoraClient,
    scope: KnowledgeScope,
    page: RenderedPage,
) -> None:
    """已存在 → update，404 → create（上游 last-write-wins，客户端 slug 串行化兜底）。"""
    wiki_page = _page_to_wiki(page)
    try:
        await client.get_wiki_page(scope.wiki_kb_id, page.slug)
    except WeKnoraClientError as exc:
        if exc.status_code != 404:
            raise
        await client.create_wiki_page(scope.wiki_kb_id, wiki_page)
        return
    await client.update_wiki_page(scope.wiki_kb_id, wiki_page)


def _validate_scope(session: Session, scope: KnowledgeScope) -> None:
    require_current_scope(session, scope)


def _require_scoped_product_version(
    session: Session,
    scope: KnowledgeScope,
    product_version_id: str,
) -> tuple[ProductVersion, InsuranceProduct]:
    row = session.execute(
        select(ProductVersion, InsuranceProduct)
        .join(
            InsuranceProduct,
            (InsuranceProduct.id == ProductVersion.product_id)
            & (InsuranceProduct.space_id == ProductVersion.space_id),
        )
        .where(
            ProductVersion.id == product_version_id,
            ProductVersion.space_id == scope.space_id,
            InsuranceProduct.space_id == scope.space_id,
        )
    ).one_or_none()
    if row is None:
        raise ScopeViolation("scope mismatch")
    return row[0], row[1]


def _require_scoped_snapshot(
    session: Session,
    scope: KnowledgeScope,
    snapshot_id: str,
) -> ReleaseSnapshot:
    snapshot = session.execute(
        select(ReleaseSnapshot).where(
            ReleaseSnapshot.id == snapshot_id,
            ReleaseSnapshot.space_id == scope.space_id,
        )
    ).scalar_one_or_none()
    if snapshot is None:
        raise ScopeViolation("scope mismatch")
    return snapshot


def _require_label_available(
    session: Session,
    scope: KnowledgeScope,
    label: str,
) -> None:
    existing = session.execute(
        select(ReleaseSnapshot.id).where(
            ReleaseSnapshot.space_id == scope.space_id,
            ReleaseSnapshot.label == label,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValueError("release label is unavailable")


def _validate_text(value: str, *, max_length: int, error: str) -> None:
    if not value.strip() or len(value) > max_length:
        raise ValueError(error)


def _validate_publish_metadata(label: str, published_by: str) -> None:
    _validate_text(label, max_length=128, error="publish metadata is unavailable")
    _validate_text(
        published_by,
        max_length=128,
        error="publish metadata is unavailable",
    )


def _validate_rollback_metadata(actor: str, reason: str) -> None:
    _validate_text(actor, max_length=128, error="rollback metadata is unavailable")
    _validate_text(reason, max_length=64, error="rollback metadata is unavailable")


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


def current_snapshot_id(session: Session, scope: KnowledgeScope) -> str | None:
    _validate_scope(session, scope)
    pointer = session.get(CurrentRelease, (scope.space_id, "current"))
    if pointer is None:
        return None
    snapshot_id = session.execute(
        select(ReleaseSnapshot.id).where(
            ReleaseSnapshot.space_id == scope.space_id,
            ReleaseSnapshot.id == pointer.snapshot_id,
        )
    ).scalar_one_or_none()
    if snapshot_id is None:
        raise ScopeViolation("scope mismatch")
    return snapshot_id


async def publish_product_version(
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
    """发布 = 生成新快照并移动指针（03 §5.2）；页面写入按 03 §7 契约。"""
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

    snapshot = ReleaseSnapshot(
        id=snapshot_id,
        space_id=scope.space_id,
        label=label,
        published_by=published_by,
        notes=notes,
        rendered_pages=[page.model_dump(mode="json")],
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

    return PublishResult(snapshot_id=snapshot.id, snapshot_label=snapshot.label, pages=[page])


async def rollback_to_snapshot(
    session: Session,
    client: WeKnoraClient,
    scope: KnowledgeScope,
    *,
    snapshot_id: str,
    actor: str = "publisher",
    reason: str = "rollback",
) -> RollbackResult:
    """回滚 = 按快照物化产物重发布 + 指针回切 + rollback ChangeSet 留痕（K5.4）。"""
    _validate_scope(session, scope)
    _validate_rollback_metadata(actor, reason)
    snapshot = _require_scoped_snapshot(session, scope, snapshot_id)
    try:
        pages = [
            RenderedPage.model_validate(raw) for raw in (snapshot.rendered_pages or [])
        ]
    except (TypeError, ValidationError) as exc:
        raise ScopeViolation("scope mismatch") from exc
    _validate_rollback_pages(session, scope, snapshot, pages)

    for page in pages:
        await _upsert_page(client, scope, page)

    change_set = ChangeSet(
        space_id=scope.space_id,
        source_kind="rollback",
        knowledge_ids=None,
        # Keep the target snapshot queryable without making repeat rollback
        # operations collide with the scoped ChangeSet source-key constraint.
        external_record_id=f"{snapshot.id}:{uuid.uuid4().hex}",
        source_revision=reason,
        status="applied",
        created_by=actor,
    )
    session.add(change_set)
    _move_pointer(session, scope, snapshot.id)
    session.flush()

    return RollbackResult(
        snapshot_id=snapshot.id, change_set_id=change_set.id, pages=pages
    )


def snapshot_claim_set(
    session: Session,
    scope: KnowledgeScope,
    snapshot_id: str,
) -> list[tuple[str, int]]:
    _validate_scope(session, scope)
    _require_scoped_snapshot(session, scope, snapshot_id)
    rows = list(
        session.execute(
            select(SnapshotClaim).where(
                SnapshotClaim.space_id == scope.space_id,
                SnapshotClaim.snapshot_id == snapshot_id,
            )
        ).scalars()
    )
    claim_ids = {row.claim_id for row in rows}
    scoped_claim_ids = (
        set(
            session.execute(
                select(Claim.id).where(
                    Claim.space_id == scope.space_id,
                    Claim.id.in_(claim_ids),
                )
            ).scalars()
        )
        if claim_ids
        else set()
    )
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
    if scoped_claim_ids != claim_ids or any(
        (row.claim_id, row.revision_no) not in revision_pairs for row in rows
    ):
        raise ScopeViolation("scope mismatch")
    return [(r.claim_id, r.revision_no) for r in rows]


def default_snapshot_label(session: Session, scope: KnowledgeScope) -> str:
    """如 2026-07-15-r1（03 §5.2 示例）；同日多次发布递增 rN。"""
    _validate_scope(session, scope)
    today = utcnow().date().isoformat()
    existing = session.execute(
        select(ReleaseSnapshot.label).where(
            ReleaseSnapshot.space_id == scope.space_id,
            ReleaseSnapshot.label.like(f"{today}-r%"),
        )
    ).scalars().all()
    revisions = [
        int(label.removeprefix(f"{today}-r"))
        for label in existing
        if label.removeprefix(f"{today}-r").isdigit()
    ]
    return f"{today}-r{max(revisions, default=0) + 1}"
