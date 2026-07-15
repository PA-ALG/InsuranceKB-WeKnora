"""OpenSpec 018 T1a: release read-model ORM contract."""

from sqlalchemy import CheckConstraint, UniqueConstraint

from insurance_harness.knowledge.tables import (
    PublishAttempt,
    ReconciliationJob,
    ReleaseOperation,
    ReleaseSnapshot,
    SnapshotFact,
)


def _columns(model: type[object]) -> set[str]:
    table = model.__table__  # type: ignore[attr-defined]
    return set(table.columns.keys())


def _unique_columns(model: type[object]) -> set[tuple[str, ...]]:
    table = model.__table__  # type: ignore[attr-defined]
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _check_sql(model: type[object]) -> str:
    table = model.__table__  # type: ignore[attr-defined]
    return " ".join(
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    )


def test_r1_1_snapshot_fact_freezes_complete_projection_columns() -> None:
    assert {
        "id",
        "space_id",
        "snapshot_id",
        "claim_id",
        "revision_no",
        "product_id",
        "product_version_id",
        "product_code",
        "product_name",
        "version_label",
        "predicate",
        "field_name",
        "field_group",
        "value_state",
        "value",
        "effective_from",
        "effective_to",
        "confidence",
        "schema_version",
        "evidence",
        "created_at",
        "updated_at",
    } == _columns(SnapshotFact)


def test_r1_3_snapshot_fact_has_scoped_claim_revision_uniqueness() -> None:
    assert (
        "space_id",
        "snapshot_id",
        "claim_id",
        "revision_no",
    ) in _unique_columns(SnapshotFact)


def test_r1_4_release_snapshot_has_lifecycle_and_legacy_version_columns() -> None:
    assert {
        "status",
        "read_model_version",
        "projection_frozen_at",
    } <= _columns(ReleaseSnapshot)
    assert ReleaseSnapshot.__table__.c.published_at.nullable
    lifecycle_sql = _check_sql(ReleaseSnapshot)
    assert all(
        status in lifecycle_sql for status in ("building", "publishing", "published", "failed")
    )


def test_r3_3_release_operation_has_durable_plan_identity_and_lease() -> None:
    assert {
        "id",
        "space_id",
        "kind",
        "status",
        "base_snapshot_id",
        "target_snapshot_id",
        "parent_operation_id",
        "previous_operation_id",
        "publish_plan",
        "plan_digest",
        "plan_frozen_at",
        "retry_no",
        "lease_expires_at",
        "heartbeat_at",
        "actor",
        "reason",
        "created_at",
        "updated_at",
    } == _columns(ReleaseOperation)
    check_sql = _check_sql(ReleaseOperation)
    assert all(kind in check_sql for kind in ("publish", "rollback", "reconcile"))
    assert all(status in check_sql for status in ("building", "running", "succeeded", "failed"))


def test_r3_3_publish_attempt_has_retry_action_and_nullable_creation_state() -> None:
    assert {
        "id",
        "space_id",
        "operation_id",
        "retry_no",
        "action_no",
        "operation",
        "status",
        "error",
        "snapshot_id",
        "slug",
        "created_new",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    } == _columns(PublishAttempt)
    assert PublishAttempt.__table__.c.created_new.nullable
    assert ("space_id", "operation_id", "retry_no", "action_no") in _unique_columns(PublishAttempt)
    check_sql = _check_sql(PublishAttempt)
    assert all(status in check_sql for status in ("started", "succeeded", "failed", "collision"))


def test_r3_4_reconciliation_job_has_unique_failed_source_operation() -> None:
    assert {
        "id",
        "space_id",
        "source_operation_id",
        "source_plan_digest",
        "reconcile_operation_id",
        "status",
        "last_error",
        "created_at",
        "updated_at",
    } == _columns(ReconciliationJob)
    assert ("space_id", "source_operation_id") in _unique_columns(ReconciliationJob)
    check_sql = _check_sql(ReconciliationJob)
    assert all(status in check_sql for status in ("pending", "running", "succeeded", "failed"))
