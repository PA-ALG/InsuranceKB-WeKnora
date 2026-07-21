"""OpenSpec 029 RA2: exact-manifest persistence and named-human approval."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import func, select, text
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
    authorizer = _Authorizer(replace(base, **change))

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
