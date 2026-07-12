"""WeKnora 发布器（change 007；specs K5.2~K5.4）。

published Claims → 产品限定页 → adapters/weknora 写 wiki 页（slug 串行化由客户端保证）。
每次发布记录 ReleaseSnapshot（冻结 (claim_id, revision_no) + 物化渲染产物）并移动
current_release 指针；回滚 = 按快照重发布 + 指针回切 + rollback ChangeSet 留痕（03 §5.2）。
"""

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.adapters.weknora.errors import WeKnoraClientError
from insurance_harness.adapters.weknora.models import WeKnoraWikiPage
from insurance_harness.db.base import utcnow
from insurance_harness.db.models import InsuranceProduct, ProductVersion
from insurance_harness.knowledge.pages import (
    RenderedPage,
    build_page_claims,
    render_product_page,
)
from insurance_harness.knowledge.tables import (
    ChangeSet,
    Claim,
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


async def _upsert_page(client: WeKnoraClient, kb_id: str, page: RenderedPage) -> None:
    """已存在 → update，404 → create（上游 last-write-wins，客户端 slug 串行化兜底）。"""
    wiki_page = _page_to_wiki(page)
    try:
        await client.get_wiki_page(kb_id, page.slug)
    except WeKnoraClientError as exc:
        if exc.status_code != 404:
            raise
        await client.create_wiki_page(kb_id, wiki_page)
        return
    await client.update_wiki_page(kb_id, wiki_page)


def _move_pointer(session: Session, snapshot_id: str) -> None:
    pointer = session.get(CurrentRelease, "current")
    if pointer is None:
        session.add(CurrentRelease(id="current", snapshot_id=snapshot_id))
    else:
        pointer.snapshot_id = snapshot_id
    session.flush()


def current_snapshot_id(session: Session) -> str | None:
    pointer = session.get(CurrentRelease, "current")
    return pointer.snapshot_id if pointer else None


async def publish_product_version(
    session: Session,
    client: WeKnoraClient,
    kb_id: str,
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
    version = session.get(ProductVersion, product_version_id)
    if version is None:
        raise KeyError(f"product_version {product_version_id} 不存在")
    product = session.get(InsuranceProduct, version.product_id)
    assert product is not None

    snapshot = ReleaseSnapshot(label=label, published_by=published_by, notes=notes)
    session.add(snapshot)
    session.flush()

    views = build_page_claims(
        session,
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
        snapshot_id=snapshot.id,
        schema_version=schema_version,
    )

    for view in views:
        claim = session.get(Claim, view.claim_id)
        assert claim is not None
        session.add(
            SnapshotClaim(
                snapshot_id=snapshot.id, claim_id=claim.id, revision_no=claim.current_revision
            )
        )
    snapshot.rendered_pages = [page.model_dump(mode="json")]
    _move_pointer(session, snapshot.id)
    session.flush()

    await _upsert_page(client, kb_id, page)
    return PublishResult(snapshot_id=snapshot.id, snapshot_label=snapshot.label, pages=[page])


async def rollback_to_snapshot(
    session: Session,
    client: WeKnoraClient,
    kb_id: str,
    *,
    snapshot_id: str,
    actor: str = "publisher",
    reason: str = "rollback",
) -> RollbackResult:
    """回滚 = 按快照物化产物重发布 + 指针回切 + rollback ChangeSet 留痕（K5.4）。"""
    snapshot = session.get(ReleaseSnapshot, snapshot_id)
    if snapshot is None:
        raise KeyError(f"snapshot {snapshot_id} 不存在")
    pages = [
        RenderedPage.model_validate(raw) for raw in (snapshot.rendered_pages or [])
    ]
    change_set = ChangeSet(
        source_kind="rollback",
        knowledge_ids=None,
        external_record_id=None,
        source_revision=None,
        status="applied",
        created_by=actor,
    )
    session.add(change_set)
    _move_pointer(session, snapshot.id)
    session.flush()

    for page in pages:
        await _upsert_page(client, kb_id, page)
    return RollbackResult(
        snapshot_id=snapshot.id, change_set_id=change_set.id, pages=pages
    )


def snapshot_claim_set(session: Session, snapshot_id: str) -> list[tuple[str, int]]:
    rows = session.execute(
        select(SnapshotClaim).where(SnapshotClaim.snapshot_id == snapshot_id)
    ).scalars()
    return [(r.claim_id, r.revision_no) for r in rows]


def default_snapshot_label(session: Session) -> str:
    """如 2026-07-15-r1（03 §5.2 示例）；同日多次发布递增 rN。"""
    today = utcnow().date().isoformat()
    existing = session.execute(
        select(ReleaseSnapshot.label).where(ReleaseSnapshot.label.like(f"{today}-r%"))
    ).scalars().all()
    return f"{today}-r{len(existing) + 1}"
