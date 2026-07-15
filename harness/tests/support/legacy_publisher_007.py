"""Private characterization harness for the retired 007 caller-Session API."""

import uuid

from pydantic import ValidationError
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.db.base import utcnow
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from insurance_harness.knowledge.pages import (
    RenderedPage,
    build_page_claims,
    render_product_page,
)
from insurance_harness.knowledge.publisher import (
    PublishResult,
    RollbackResult,
    _move_pointer,
    _require_label_available,
    _require_scoped_product_version,
    _require_scoped_snapshot,
    _snapshot_claims_for_publish,
    _upsert_page,
    _validate_publish_metadata,
    _validate_rollback_metadata,
    _validate_rollback_pages,
    _validate_scope,
)
from insurance_harness.knowledge.tables import (
    ChangeSet,
    ReleaseSnapshot,
    SnapshotClaim,
)
from insurance_harness.schemas import SchemaRegistry


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
