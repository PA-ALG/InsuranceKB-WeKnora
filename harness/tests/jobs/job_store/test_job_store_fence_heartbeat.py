"""JobStore（SQLite）：只读 active fence 校验与租约心跳。"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from insurance_harness.jobs import (
    IllegalTransitionError,
    InvalidJobInputError,
    JobSnapshot,
    JobState,
    JobStore,
    LeaseExpiredError,
    SpaceScopeError,
    StaleGenerationError,
)
from insurance_harness.jobs.tables import WikiOutboxEvent
from tests.jobs.job_store.helpers import SessionFactory, _claimed, force_expire, make_store


def outbox_count(factory: SessionFactory) -> int:
    with factory() as session:
        return int(session.scalar(select(func.count()).select_from(WikiOutboxEvent)) or 0)


def _running(store: JobStore, space_id: str = "space-a") -> JobSnapshot:
    store.enqueue(space_id=space_id, job_type="compile", idempotency_key="active-fence")
    claimed = _claimed(store, space_id)
    return store.start(
        space_id=space_id,
        job_id=claimed.id,
        generation=claimed.lease_generation,
    )


def test_p1_13_verify_active_fence_returns_current_snapshot_without_writes(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    running = _running(store)
    before = store.get_job(space_id="space-a", job_id=running.id)
    before_outbox = outbox_count(factory)

    verified = store.verify_active_fence(
        space_id="space-a",
        job_id=running.id,
        generation=running.lease_generation,
        attempt=running.attempt,
    )

    assert verified == before
    assert store.get_job(space_id="space-a", job_id=running.id) == before
    assert outbox_count(factory) == before_outbox


def test_p1_13_verify_active_fence_rejects_scope_and_non_running_without_writes(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="active-fence")
    leased = _claimed(store, "space-a")
    before = store.get_job(space_id="space-a", job_id=leased.id)

    with pytest.raises(SpaceScopeError):
        store.verify_active_fence(
            space_id="space-b",
            job_id=leased.id,
            generation=leased.lease_generation,
            attempt=leased.attempt,
        )
    with pytest.raises(IllegalTransitionError):
        store.verify_active_fence(
            space_id="space-a",
            job_id=leased.id,
            generation=leased.lease_generation,
            attempt=leased.attempt,
        )

    assert store.get_job(space_id="space-a", job_id=leased.id) == before
    assert outbox_count(factory) == 0


def test_p1_13_verify_active_fence_rejects_stale_or_wrong_attempt_without_writes(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    running = _running(store)
    before = store.get_job(space_id="space-a", job_id=running.id)

    with pytest.raises(StaleGenerationError):
        store.verify_active_fence(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation - 1,
            attempt=running.attempt,
        )
    with pytest.raises(InvalidJobInputError):
        store.verify_active_fence(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation,
            attempt=running.attempt + 1,
        )

    assert store.get_job(space_id="space-a", job_id=running.id) == before
    assert outbox_count(factory) == 0


def test_p1_13_verify_active_fence_rejects_expired_lease_without_writes(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    running = _running(store)
    force_expire(factory, running.id)
    before = store.get_job(space_id="space-a", job_id=running.id)

    with pytest.raises(LeaseExpiredError):
        store.verify_active_fence(
            space_id="space-a",
            job_id=running.id,
            generation=running.lease_generation,
            attempt=running.attempt,
        )

    assert store.get_job(space_id="space-a", job_id=running.id) == before
    assert outbox_count(factory) == 0


def test_p1_3_heartbeat_extends_lease_only_by_configured_duration(
    factory: SessionFactory,
) -> None:
    short = make_store(factory, lease_seconds=300.0)
    longer = make_store(factory, lease_seconds=600.0)
    short.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    claimed = _claimed(short, "space-a")
    assert claimed.lease_expires_at is not None

    extended = longer.heartbeat(
        space_id="space-a", job_id=claimed.id, generation=claimed.lease_generation
    )

    assert extended.lease_expires_at is not None
    assert extended.lease_expires_at > claimed.lease_expires_at
    assert extended.state is JobState.LEASED


def test_p1_3_heartbeat_with_stale_generation_is_rejected_with_zero_changes(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1")
    claimed = _claimed(store, "space-a")

    with pytest.raises(StaleGenerationError):
        store.heartbeat(space_id="space-a", job_id=claimed.id, generation=0)

    unchanged = store.get_job(space_id="space-a", job_id=claimed.id)
    assert unchanged.lease_expires_at == claimed.lease_expires_at
    assert unchanged.state is JobState.LEASED


def test_p1_3_heartbeat_outside_leased_running_or_space_is_rejected(
    factory: SessionFactory,
) -> None:
    store = make_store(factory)
    queued = store.enqueue(space_id="space-a", job_type="compile", idempotency_key="job-1").job

    with pytest.raises(IllegalTransitionError):
        store.heartbeat(space_id="space-a", job_id=queued.id, generation=0)
    with pytest.raises(SpaceScopeError):
        store.heartbeat(space_id="space-b", job_id=queued.id, generation=0)
    assert store.get_job(space_id="space-a", job_id=queued.id).state is JobState.QUEUED
