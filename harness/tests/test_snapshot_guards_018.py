"""OpenSpec 018 T1c: database-enforced release immutability guards."""

from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.db.base import Base, utcnow
from insurance_harness.db.models import InsuranceProduct, KnowledgeSpace, ProductVersion
from insurance_harness.knowledge.tables import (
    Claim,
    ClaimRevision,
    CurrentRelease,
    ReleaseOperation,
    ReleaseSnapshot,
    SnapshotFact,
)


def _seed_product(session: Session) -> tuple[str, str, str]:
    space = KnowledgeSpace(
        id="space-1",
        tenant_id="tenant-1",
        raw_kb_id="raw-1",
        wiki_kb_id="wiki-1",
        name="Space",
        binding_status="bound",
    )
    product = InsuranceProduct(
        id="product-1",
        space_id=space.id,
        product_code="P001",
        canonical_name="产品一",
        category="life",
        status="在售",
        meta=None,
    )
    version = ProductVersion(
        id="version-1",
        space_id=space.id,
        product_id=product.id,
        version_label="V1",
        channels=None,
        regions=None,
    )
    session.add(space)
    session.flush()
    session.add(product)
    session.flush()
    session.add(version)
    session.flush()
    return space.id, product.id, version.id


def _claim(session: Session, *, claim_id: str, version_id: str) -> Claim:
    claim = Claim(
        id=claim_id,
        space_id="space-1",
        product_version_id=version_id,
        predicate="waiting_period",
        value_state="present",
        value={"text": claim_id},
        status="published",
        confidence=0.9,
        schema_version="v1",
        current_revision=1,
    )
    session.add(claim)
    session.flush()
    session.add(
        ClaimRevision(
            id=f"revision-{claim_id}",
            claim_id=claim.id,
            revision_no=1,
            before=None,
            after={"value": claim.value},
            actor="test",
        )
    )
    session.flush()
    return claim


def _fact(
    *,
    fact_id: str,
    snapshot_id: str,
    claim_id: str,
    product_id: str,
    version_id: str,
) -> SnapshotFact:
    return SnapshotFact(
        id=fact_id,
        space_id="space-1",
        snapshot_id=snapshot_id,
        claim_id=claim_id,
        revision_no=1,
        product_id=product_id,
        product_version_id=version_id,
        product_code="P001",
        product_name="产品一",
        version_label="V1",
        predicate="waiting_period",
        field_name="等待期",
        field_group="coverage",
        value_state="present",
        value={"text": claim_id},
        confidence=0.9,
        schema_version="v1",
        evidence=[],
    )


def _snapshot(
    snapshot_id: str,
    *,
    status: str,
    space_id: str = "space-1",
    read_model_version: int = 1,
    frozen_at: datetime | None = None,
) -> ReleaseSnapshot:
    return ReleaseSnapshot(
        id=snapshot_id,
        space_id=space_id,
        label=snapshot_id,
        rendered_pages=[],
        status=status,
        read_model_version=read_model_version,
        projection_frozen_at=frozen_at,
        published_at=utcnow() if status == "published" else None,
        published_by="test",
    )


def test_r1_2_snapshot_fact_rejects_update_and_delete_before_freeze(
    kb_session: Session,
) -> None:
    _, product_id, version_id = _seed_product(kb_session)
    _claim(kb_session, claim_id="claim-1", version_id=version_id)
    kb_session.add(_snapshot("snapshot-building", status="building"))
    kb_session.flush()
    kb_session.add(
        _fact(
            fact_id="fact-1",
            snapshot_id="snapshot-building",
            claim_id="claim-1",
            product_id=product_id,
            version_id=version_id,
        )
    )
    kb_session.commit()

    with pytest.raises(IntegrityError, match="snapshot facts are immutable"):
        kb_session.execute(text("UPDATE snapshot_facts SET confidence=0.1 WHERE id='fact-1'"))
    kb_session.rollback()

    with pytest.raises(IntegrityError, match="snapshot facts are immutable"):
        kb_session.execute(text("DELETE FROM snapshot_facts WHERE id='fact-1'"))
    kb_session.rollback()


def test_r1_2_projection_freeze_rejects_late_fact_and_page_changes(
    kb_session: Session,
) -> None:
    _, product_id, version_id = _seed_product(kb_session)
    _claim(kb_session, claim_id="claim-1", version_id=version_id)
    _claim(kb_session, claim_id="claim-2", version_id=version_id)
    snapshot = _snapshot("snapshot-building", status="building")
    kb_session.add(snapshot)
    kb_session.flush()
    kb_session.add(
        _fact(
            fact_id="fact-1",
            snapshot_id=snapshot.id,
            claim_id="claim-1",
            product_id=product_id,
            version_id=version_id,
        )
    )
    kb_session.flush()
    snapshot.projection_frozen_at = utcnow()
    kb_session.commit()

    kb_session.add(
        _fact(
            fact_id="fact-2",
            snapshot_id=snapshot.id,
            claim_id="claim-2",
            product_id=product_id,
            version_id=version_id,
        )
    )
    with pytest.raises(IntegrityError, match="snapshot projection is frozen"):
        kb_session.commit()
    kb_session.rollback()

    with pytest.raises(IntegrityError, match="snapshot projection is frozen"):
        kb_session.execute(
            text(
                "UPDATE release_snapshots "
                'SET rendered_pages=\'[{"slug":"changed"}]\' '
                "WHERE id='snapshot-building'"
            )
        )
    kb_session.rollback()


def test_r1_2_frozen_publish_plan_rejects_change_or_unfreeze(
    kb_session: Session,
) -> None:
    _seed_product(kb_session)
    snapshot = _snapshot("snapshot-building", status="building")
    operation = ReleaseOperation(
        id="operation-1",
        space_id="space-1",
        kind="publish",
        status="building",
        target_snapshot_id=snapshot.id,
        publish_plan={"actions": []},
        plan_digest="a" * 64,
        plan_frozen_at=utcnow(),
        retry_no=0,
        actor="test",
    )
    kb_session.add(snapshot)
    kb_session.flush()
    kb_session.add(operation)
    kb_session.commit()

    with pytest.raises(IntegrityError, match="publish plan is frozen"):
        kb_session.execute(
            text("UPDATE release_operations SET publish_plan='{}' WHERE id='operation-1'")
        )
    kb_session.rollback()

    with pytest.raises(IntegrityError, match="publish plan is frozen"):
        kb_session.execute(
            text("UPDATE release_operations SET plan_frozen_at=NULL WHERE id='operation-1'")
        )
    kb_session.rollback()


def test_r6_4_kb_session_enforces_sqlite_foreign_keys(kb_session: Session) -> None:
    assert kb_session.scalar(text("PRAGMA foreign_keys")) == 1
    _seed_product(kb_session)
    space_b = KnowledgeSpace(
        id="space-b",
        tenant_id="tenant-b",
        raw_kb_id="raw-b",
        wiki_kb_id="wiki-b",
        name="Space B",
        binding_status="bound",
    )
    kb_session.add(space_b)
    kb_session.flush()
    kb_session.add(
        _snapshot(
            "snapshot-b",
            space_id=space_b.id,
            status="published",
            frozen_at=utcnow(),
        )
    )
    kb_session.commit()

    kb_session.add(
        ReleaseOperation(
            id="operation-cross-space",
            space_id="space-1",
            kind="rollback",
            status="building",
            target_snapshot_id="snapshot-b",
            retry_no=0,
            actor="test",
        )
    )
    with pytest.raises(IntegrityError):
        kb_session.commit()
    kb_session.rollback()


def test_r2_1_current_pointer_rejects_legacy_failed_and_cross_space_targets(
    kb_session: Session,
) -> None:
    _seed_product(kb_session)
    space_b = KnowledgeSpace(
        id="space-b",
        tenant_id="tenant-b",
        raw_kb_id="raw-b",
        wiki_kb_id="wiki-b",
        name="Space B",
        binding_status="bound",
    )
    kb_session.add(space_b)
    kb_session.flush()
    kb_session.add_all(
        [
            _snapshot("snapshot-current", status="published", frozen_at=utcnow()),
            _snapshot("snapshot-unfrozen", status="published"),
            _snapshot("snapshot-legacy", status="published", read_model_version=0),
            _snapshot("snapshot-failed", status="failed"),
            _snapshot(
                "snapshot-b",
                space_id=space_b.id,
                status="published",
                frozen_at=utcnow(),
            ),
        ]
    )
    kb_session.commit()

    kb_session.add(
        CurrentRelease(
            space_id="space-1",
            id="current",
            snapshot_id="snapshot-b",
        )
    )
    with pytest.raises(IntegrityError, match="current release target is unavailable"):
        kb_session.commit()
    kb_session.rollback()

    kb_session.add(
        CurrentRelease(
            space_id="space-1",
            id="current",
            snapshot_id="snapshot-legacy",
        )
    )
    with pytest.raises(IntegrityError, match="current release target is unavailable"):
        kb_session.commit()
    kb_session.rollback()

    kb_session.add(
        CurrentRelease(
            space_id="space-1",
            id="current",
            snapshot_id="snapshot-unfrozen",
        )
    )
    with pytest.raises(IntegrityError, match="current release target is unavailable"):
        kb_session.commit()
    kb_session.rollback()

    kb_session.add(
        CurrentRelease(
            space_id="space-1",
            id="current",
            snapshot_id="snapshot-current",
        )
    )
    kb_session.commit()

    with pytest.raises(IntegrityError, match="current release target is unavailable"):
        kb_session.execute(
            text(
                "UPDATE current_release SET snapshot_id='snapshot-failed' WHERE space_id='space-1'"
            )
        )
    kb_session.rollback()


def test_r1_2_metadata_create_all_is_idempotent(kb_session: Session) -> None:
    bind = kb_session.get_bind()

    Base.metadata.create_all(bind)
    Base.metadata.create_all(bind)
