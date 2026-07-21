"""OpenSpec 029 RA2: exact-manifest persistence and named-human approval."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Lock, local
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from insurance_harness.knowledge.pages import render_snapshot_pages
from insurance_harness.knowledge.release_approval import (
    AuthorizationDecision,
    ReleaseApprovalError,
    ReleaseApprovalService,
    ReleaseAuthorizationError,
    ReleaseManifestPersistenceError,
    persist_release_manifest,
)
from insurance_harness.knowledge.release_manifest import (
    ReleaseManifest,
    build_release_manifest_from_snapshot,
)
from insurance_harness.knowledge.snapshots import build_snapshot_facts
from insurance_harness.knowledge.tables import (
    CurrentRelease,
    ReleaseApproval,
    ReleaseManifestRecord,
    ReleaseSnapshot,
    ReviewItem,
    SnapshotFact,
)
from tests.support.release_018 import (
    NOW,
    release_claim,
    release_product,
    release_scope,
)

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64


def _frozen_manifest(session: Session, suffix: str = "approval") -> tuple[Any, ReleaseManifest]:
    scope = release_scope(session, suffix)
    _product, version = release_product(session, scope, code=f"P-{suffix}")
    release_claim(
        session,
        scope,
        version,
        claim_id=f"claim-{suffix}",
        predicate="waiting_period",
    )
    snapshot_id = f"snapshot-{suffix}"
    facts = build_snapshot_facts(session, scope, snapshot_id=snapshot_id)
    pages = [
        page.model_dump(mode="json")
        for page in render_snapshot_pages(
            facts,
            space_id=scope.space_id,
            snapshot_id=snapshot_id,
            compiled_at=NOW,
        )
    ]
    snapshot = ReleaseSnapshot(
        id=snapshot_id,
        space_id=scope.space_id,
        label=snapshot_id,
        rendered_pages=pages,
        status="building",
        read_model_version=1,
        published_by="test",
    )
    session.add(snapshot)
    session.flush()
    for index, fact in enumerate(facts):
        evidence = [item.model_dump(mode="json") for item in fact.evidence]
        for item in evidence:
            for field in ("extracted_at", "created_at", "updated_at"):
                item[field] = NOW.isoformat()
        session.add(
            SnapshotFact(
                id=f"fact-{suffix}-{index}",
                space_id=fact.space_id,
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
                evidence=evidence,
            )
        )
    session.flush()
    snapshot.projection_frozen_at = NOW
    snapshot.status = "published"
    snapshot.published_at = NOW
    session.commit()
    return scope, build_release_manifest_from_snapshot(
        session,
        scope,
        snapshot_id=snapshot_id,
        schema_version="v1.1+release",
        template_hashes=(_A, _B),
        model_plan_hash=_C,
    )


class _Authorizer:
    def __init__(self, decision: AuthorizationDecision | None = None) -> None:
        self.decision = decision
        self.calls: list[dict[str, object]] = []

    def authorize(self, **request: object) -> AuthorizationDecision:
        self.calls.append(request)
        if self.decision is not None:
            return self.decision
        return AuthorizationDecision(
            outcome="authorized",
            space_id=str(request["space_id"]),
            actor=str(request["actor"]),
            actor_type=str(request["actor_type"]),
            role="release_approver",
            manifest_hash=str(request["manifest_hash"]),
            authorization_receipt=str(request["authorization_receipt"]),
        )


def _approve(
    session: Session,
    scope: Any,
    manifest: ReleaseManifest,
    *,
    authorizer: _Authorizer | None = None,
    actor: str = "alice@example.com",
    actor_type: str = "human",
    receipt: str = "iam:release-approver:alice:42",
    reason: str = "reviewed exact release artifacts",
) -> ReleaseApproval:
    return ReleaseApprovalService(session, authorizer or _Authorizer()).approve(
        scope,
        snapshot_id=manifest.snapshot_id,
        manifest_hash=manifest.manifest_sha256,
        actor=actor,
        actor_type=actor_type,
        authorization_receipt=receipt,
        reason=reason,
    )


def test_ra2_manifest_persistence_roundtrips_canonical_payload_and_is_idempotent(
    session: Session,
) -> None:
    scope, manifest = _frozen_manifest(session, "persist")

    first = persist_release_manifest(session, scope, manifest)
    second = persist_release_manifest(session, scope, manifest)

    assert first.id == second.id
    assert first.manifest_hash == manifest.manifest_sha256
    assert ReleaseManifest.model_validate_json(
        json.dumps(first.payload, sort_keys=True, separators=(",", ":"))
    ) == manifest
    assert session.scalar(select(func.count()).select_from(ReleaseManifestRecord)) == 1


def test_ra2_manifest_persistence_rejects_scope_hash_and_snapshot_substitution(
    session: Session,
) -> None:
    scope, manifest = _frozen_manifest(session, "substitution")
    other_scope, _other_manifest = _frozen_manifest(session, "other")
    persist_release_manifest(session, scope, manifest)

    different = build_release_manifest_from_snapshot(
        session,
        scope,
        snapshot_id=manifest.snapshot_id,
        schema_version=manifest.schema_version,
        template_hashes=(_A,),
        model_plan_hash=_C,
    )
    with pytest.raises(ReleaseManifestPersistenceError, match="already bound"):
        persist_release_manifest(session, scope, different)
    with pytest.raises(ReleaseManifestPersistenceError, match="scope"):
        persist_release_manifest(session, other_scope, manifest)
    with pytest.raises(ReleaseManifestPersistenceError, match="integrity"):
        persist_release_manifest(
            session,
            scope,
            manifest.model_copy(update={"manifest_sha256": "0" * 64}),
        )


def test_ra2_authorized_named_human_approves_exact_hash_without_moving_current(
    session: Session,
) -> None:
    scope, manifest = _frozen_manifest(session, "authorized")
    persist_release_manifest(session, scope, manifest)
    session.commit()
    authorizer = _Authorizer()

    approval = _approve(session, scope, manifest, authorizer=authorizer)

    assert approval.actor == "alice@example.com"
    assert approval.actor_type == "human"
    assert approval.role == "release_approver"
    assert approval.manifest_hash == manifest.manifest_sha256
    assert approval.authorization_receipt == "iam:release-approver:alice:42"
    assert authorizer.calls == [
        {
            "space_id": scope.space_id,
            "actor": "alice@example.com",
            "actor_type": "human",
            "role": "release_approver",
            "manifest_hash": manifest.manifest_sha256,
            "authorization_receipt": "iam:release-approver:alice:42",
        }
    ]
    assert session.scalar(select(func.count()).select_from(CurrentRelease)) == 0


@pytest.mark.parametrize("actor_type", ["model", "service"])
def test_ra2_model_or_service_actor_can_never_approve(
    session: Session, actor_type: str
) -> None:
    scope, manifest = _frozen_manifest(session, actor_type)
    persist_release_manifest(session, scope, manifest)
    session.commit()
    authorizer = _Authorizer()

    with pytest.raises(ReleaseAuthorizationError, match="human principal"):
        _approve(session, scope, manifest, authorizer=authorizer, actor_type=actor_type)

    assert authorizer.calls == []
    assert session.scalar(select(func.count()).select_from(ReleaseApproval)) == 0


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"outcome": "denied"}, "denied"),
        ({"space_id": "space-wrong"}, "scope"),
        ({"actor": "mallory@example.com"}, "actor"),
        ({"actor_type": "service"}, "actor"),
        ({"role": "viewer"}, "role"),
        ({"manifest_hash": "0" * 64}, "manifest"),
        ({"authorization_receipt": "wrong-receipt"}, "receipt"),
    ],
)
def test_ra2_authorizer_decision_must_exactly_bind_authority_and_manifest(
    session: Session, change: dict[str, str], message: str
) -> None:
    scope, manifest = _frozen_manifest(session, f"decision-{message}")
    persist_release_manifest(session, scope, manifest)
    session.commit()
    base = AuthorizationDecision(
        outcome="authorized",
        space_id=scope.space_id,
        actor="alice@example.com",
        actor_type="human",
        role="release_approver",
        manifest_hash=manifest.manifest_sha256,
        authorization_receipt="iam:release-approver:alice:42",
    )
    authorizer = _Authorizer(
        replace(base, **change)  # type: ignore[arg-type]  # parametrized invalid decisions
    )

    with pytest.raises(ReleaseAuthorizationError, match=message):
        _approve(session, scope, manifest, authorizer=authorizer)

    assert session.scalar(select(func.count()).select_from(ReleaseApproval)) == 0


def test_ra2_request_hash_substitution_is_rejected_before_authorization(
    session: Session,
) -> None:
    scope, manifest = _frozen_manifest(session, "hash-request")
    persist_release_manifest(session, scope, manifest)
    session.commit()
    authorizer = _Authorizer()

    with pytest.raises(ReleaseApprovalError, match="exact manifest"):
        ReleaseApprovalService(session, authorizer).approve(
            scope,
            snapshot_id=manifest.snapshot_id,
            manifest_hash="0" * 64,
            actor="alice@example.com",
            actor_type="human",
            authorization_receipt="receipt",
            reason="reviewed",
        )

    assert authorizer.calls == []


def test_ra2_approval_rebuilds_and_rejects_frozen_projection_drift(session: Session) -> None:
    scope, manifest = _frozen_manifest(session, "drift")
    persist_release_manifest(session, scope, manifest)
    session.commit()
    session.execute(text("DROP TRIGGER trg_snapshot_facts_update_guard_018"))
    session.execute(
        text("UPDATE snapshot_facts SET value=:value WHERE snapshot_id=:snapshot_id"),
        {"value": '{"text":"tampered"}', "snapshot_id": manifest.snapshot_id},
    )
    session.commit()
    authorizer = _Authorizer()

    with pytest.raises(ReleaseApprovalError, match="drift"):
        _approve(session, scope, manifest, authorizer=authorizer)

    assert authorizer.calls == []


def test_ra2_exact_retry_is_idempotent_but_changed_attestation_is_rejected(
    session: Session,
) -> None:
    scope, manifest = _frozen_manifest(session, "retry")
    persist_release_manifest(session, scope, manifest)
    session.commit()
    service = ReleaseApprovalService(session, _Authorizer())
    request = {
        "snapshot_id": manifest.snapshot_id,
        "manifest_hash": manifest.manifest_sha256,
        "actor": "alice@example.com",
        "actor_type": "principal",
        "authorization_receipt": "receipt-1",
        "reason": "reviewed",
    }

    first = service.approve(scope, **request)
    second = service.approve(scope, **request)
    assert first.id == second.id
    assert session.scalar(select(func.count()).select_from(ReleaseApproval)) == 1

    with pytest.raises(ReleaseApprovalError, match="already approved"):
        service.approve(scope, **(request | {"reason": "different"}))


def test_ra2_service_flushes_but_never_commits_or_rolls_back_caller_transaction(
    session: Session,
) -> None:
    scope, manifest = _frozen_manifest(session, "transaction")
    persist_release_manifest(session, scope, manifest)
    session.commit()

    _approve(session, scope, manifest)
    assert session.in_transaction()
    assert session.scalar(select(func.count()).select_from(ReleaseApproval)) == 1
    session.rollback()

    assert session.scalar(select(func.count()).select_from(ReleaseApproval)) == 0


def test_ra2_public_knowledge_contract_exports_authority_types() -> None:
    from insurance_harness import knowledge

    assert knowledge.AuthorizationDecision is AuthorizationDecision
    assert knowledge.ReleaseApprovalService is ReleaseApprovalService
    assert knowledge.persist_release_manifest is persist_release_manifest


def _hide_first_scalar_for_entity(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    entity: type[object],
) -> None:
    """Model a stale pre-insert read while keeping the DB uniqueness conflict real."""

    original_scalar = session.scalar
    hidden = False

    def stale_scalar(statement: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal hidden
        descriptions = getattr(statement, "column_descriptions", ())
        selected_entity = descriptions[0].get("entity") if descriptions else None
        if selected_entity is entity and not hidden:
            hidden = True
            return None
        return original_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(session, "scalar", stale_scalar)


def _prior_caller_work(session: Session, scope: Any, suffix: str) -> ReviewItem:
    prior = ReviewItem(
        space_id=scope.space_id,
        review_key=f"review-{suffix}",
        type="release",
        subject={"source": "caller"},
        allowed_actions=["approve"],
        status="open",
        risk_level="low",
    )
    session.add(prior)
    session.flush()
    return prior


@pytest.mark.parametrize("same_manifest", [True, False])
def test_ra2_manifest_unique_race_is_domain_safe_and_preserves_outer_transaction(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    same_manifest: bool,
) -> None:
    scope, requested = _frozen_manifest(session, f"manifest-race-{same_manifest}")
    competing = requested
    if not same_manifest:
        competing = build_release_manifest_from_snapshot(
            session,
            scope,
            snapshot_id=requested.snapshot_id,
            schema_version=requested.schema_version,
            template_hashes=(_A,),
            model_plan_hash=_C,
        )
    row = ReleaseManifestRecord(
        space_id=scope.space_id,
        snapshot_id=competing.snapshot_id,
        manifest_hash=competing.manifest_sha256,
        payload=competing.model_dump(mode="json"),
    )
    session.add(row)
    prior = _prior_caller_work(session, scope, f"manifest-{same_manifest}")
    outer = session.get_transaction()
    _hide_first_scalar_for_entity(monkeypatch, session, ReleaseManifestRecord)

    if same_manifest:
        result = persist_release_manifest(session, scope, requested)
        assert result.id == row.id
    else:
        with pytest.raises(ReleaseManifestPersistenceError, match="already bound"):
            persist_release_manifest(session, scope, requested)

    assert session.is_active
    assert session.get_transaction() is outer
    assert session.get(ReviewItem, prior.id) is prior
    prior.risk_level = "high"
    session.flush()
    assert prior.risk_level == "high"


@pytest.mark.parametrize("same_attestation", [True, False])
def test_ra2_approval_unique_race_is_domain_safe_and_preserves_outer_transaction(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    same_attestation: bool,
) -> None:
    scope, manifest = _frozen_manifest(session, f"approval-race-{same_attestation}")
    persist_release_manifest(session, scope, manifest)
    session.commit()
    row = ReleaseApproval(
        space_id=scope.space_id,
        snapshot_id=manifest.snapshot_id,
        manifest_hash=manifest.manifest_sha256,
        actor="alice@example.com",
        actor_type="human",
        role="release_approver",
        authorization_receipt="iam:release-approver:alice:42",
        reason=(
            "reviewed exact release artifacts"
            if same_attestation
            else "a different prior attestation"
        ),
    )
    session.add(row)
    prior = _prior_caller_work(session, scope, f"approval-{same_attestation}")
    outer = session.get_transaction()
    _hide_first_scalar_for_entity(monkeypatch, session, ReleaseApproval)

    if same_attestation:
        result = _approve(session, scope, manifest)
        assert result.id == row.id
    else:
        with pytest.raises(ReleaseApprovalError, match="already approved"):
            _approve(session, scope, manifest)

    assert session.is_active
    assert session.get_transaction() is outer
    assert session.get(ReviewItem, prior.id) is prior
    prior.risk_level = "high"
    session.flush()
    assert prior.risk_level == "high"


@contextmanager
def _block_after_two_approval_prechecks(
    engine: Engine,
) -> Iterator[tuple[Callable[[], None], list[int]]]:
    """Hold each worker after PG determines its first approval precheck result."""

    barrier = Barrier(2)
    state = local()
    hit_lock = Lock()
    connection_hits: list[int] = []

    def arm_current_worker() -> None:
        state.armed = True
        state.blocked = False

    def after_cursor_execute(
        connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if (
            not getattr(state, "armed", False)
            or getattr(state, "blocked", False)
            or " from release_approvals " not in f" {normalized} "
            or "release_approvals.space_id" not in normalized
            or "release_approvals.manifest_hash" not in normalized
        ):
            return
        state.blocked = True
        with hit_lock:
            connection_hits.append(id(connection))
        barrier.wait(timeout=15)

    event.listen(engine, "after_cursor_execute", after_cursor_execute)
    try:
        yield arm_current_worker, connection_hits
    finally:
        event.remove(engine, "after_cursor_execute", after_cursor_execute)


@pytest.mark.integration_postgres
def test_ra2_postgresql_two_sessions_converge_on_exact_manifest_and_approval() -> None:
    raw_url = os.getenv("HARNESS_TEST_POSTGRES_URL")
    if not raw_url:
        pytest.skip("HARNESS_TEST_POSTGRES_URL is required for real PostgreSQL RA2")
    admin_url = make_url(raw_url).set(drivername="postgresql+psycopg")
    if admin_url.get_backend_name() != "postgresql":
        pytest.fail("HARNESS_TEST_POSTGRES_URL must use PostgreSQL")
    database_name = f"ikb_029_race_{uuid.uuid4().hex}"
    connect_args = {
        "connect_timeout": 10,
        "options": "-cstatement_timeout=30000 -clock_timeout=15000",
    }
    admin = create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        connect_args=connect_args,
    )
    engine = None
    database_created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')
        database_created = True
        test_url = admin_url.set(database=database_name).update_query_dict(
            {
                "application_name": "insurancekb_029_race_test",
                "connect_timeout": "10",
                "options": "-cstatement_timeout=30000 -clock_timeout=15000",
            }
        )
        engine = create_engine(test_url, connect_args=connect_args, pool_pre_ping=True)
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.set_main_option(
            "script_location",
            str(Path(__file__).resolve().parents[1] / "migrations"),
        )
        config.set_main_option(
            "sqlalchemy.url",
            test_url.render_as_string(hide_password=False).replace("%", "%%"),
        )
        command.upgrade(config, "head")
        from insurance_harness.db.base import make_session_factory

        factory = make_session_factory(engine)
        with factory() as setup:
            scope, manifest = _frozen_manifest(setup, "postgres-race")
            competing_scope, competing_manifest = _frozen_manifest(
                setup, "postgres-race-competing"
            )
            persist_release_manifest(setup, competing_scope, competing_manifest)
            setup.commit()

        manifest_barrier = Barrier(2)

        def persist_worker() -> str:
            with factory() as worker:
                manifest_barrier.wait(timeout=15)
                record = persist_release_manifest(worker, scope, manifest)
                worker.commit()
                return record.id

        with ThreadPoolExecutor(max_workers=2) as executor:
            manifest_ids = list(executor.map(lambda _index: persist_worker(), range(2)))
        assert len(set(manifest_ids)) == 1

        def approve_worker(index: int, arm_precheck: Callable[[], None]) -> tuple[str, int]:
            with factory() as worker:
                prior = _prior_caller_work(worker, scope, f"pg-same-{index}")
                backend_pid = worker.scalar(text("SELECT pg_backend_pid()"))
                assert isinstance(backend_pid, int)
                arm_precheck()
                approval = _approve(worker, scope, manifest)
                assert worker.get(ReviewItem, prior.id) is prior
                prior.risk_level = "high"
                worker.flush()
                worker.commit()
                return approval.id, backend_pid

        with _block_after_two_approval_prechecks(engine) as (arm_precheck, same_hits):
            with ThreadPoolExecutor(max_workers=2) as executor:
                same_results = list(
                    executor.map(
                        lambda index: approve_worker(index, arm_precheck), range(2)
                    )
                )
        approval_ids = [approval_id for approval_id, _pid in same_results]
        assert len(set(approval_ids)) == 1
        assert len(same_hits) == 2
        assert len({pid for _approval_id, pid in same_results}) == 2

        def competing_approval_worker(
            index: int,
            arm_precheck: Callable[[], None],
        ) -> tuple[str, int, bool]:
            with factory() as worker:
                prior = _prior_caller_work(
                    worker, competing_scope, f"pg-competing-{index}"
                )
                backend_pid = worker.scalar(text("SELECT pg_backend_pid()"))
                assert isinstance(backend_pid, int)
                arm_precheck()
                try:
                    _approve(
                        worker,
                        competing_scope,
                        competing_manifest,
                        reason=f"competing exact attestation {index}",
                    )
                    assert worker.get(ReviewItem, prior.id) is prior
                    prior.risk_level = "high"
                    worker.flush()
                    worker.commit()
                    return "winner", backend_pid, worker.is_active
                except ReleaseApprovalError as exc:
                    assert "already approved" in str(exc)
                    assert worker.get(ReviewItem, prior.id) is prior
                    prior.risk_level = "high"
                    worker.flush()
                    usable = worker.is_active and (
                        worker.scalar(
                            select(func.count()).select_from(ReleaseManifestRecord)
                        )
                        == 2
                    )
                    return "typed_error", backend_pid, usable

        with _block_after_two_approval_prechecks(engine) as (
            arm_competing_precheck,
            competing_hits,
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                competing_results = list(
                    executor.map(
                        lambda index: competing_approval_worker(
                            index, arm_competing_precheck
                        ),
                        range(2),
                    )
                )
        assert sorted(status for status, _pid, _usable in competing_results) == [
            "typed_error",
            "winner",
        ]
        assert len(competing_hits) == 2
        assert len({pid for _status, pid, _usable in competing_results}) == 2
        assert all(usable for _status, _pid, usable in competing_results)
        with factory() as verifier:
            assert verifier.scalar(select(func.count()).select_from(ReleaseManifestRecord)) == 2
            assert verifier.scalar(select(func.count()).select_from(ReleaseApproval)) == 2
    finally:
        if engine is not None:
            engine.dispose()
        if database_created:
            with admin.connect() as connection:
                connection.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname=:name AND pid<>pg_backend_pid()"
                    ),
                    {"name": database_name},
                )
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')
        admin.dispose()
