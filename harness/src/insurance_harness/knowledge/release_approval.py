"""Exact ReleaseManifest persistence and named-human approval (OpenSpec 029 RA2)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from insurance_harness.db.base import utcnow
from insurance_harness.db.scope import KnowledgeScope, require_current_scope
from insurance_harness.knowledge.release_manifest import (
    ReleaseManifest,
    ReleaseManifestBuildError,
    ReleaseManifestIntegrityError,
    build_release_manifest_from_snapshot,
    verify_release_manifest,
)
from insurance_harness.knowledge.tables import ReleaseApproval, ReleaseManifestRecord

type EffectiveReleaseActorType = Literal["human", "principal"]


class ReleaseManifestPersistenceError(ValueError):
    """A manifest cannot be stored as the exact authority for its snapshot."""


class ReleaseApprovalError(ValueError):
    """The requested approval cannot bind the persisted exact manifest."""


class ReleaseAuthorizationError(ReleaseApprovalError):
    """The injected authority did not attest this exact named-human request."""


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    """Complete decision returned by an external Space authorization authority."""

    outcome: Literal["authorized", "denied"]
    space_id: str
    actor: str
    actor_type: str
    role: str
    manifest_hash: str
    authorization_receipt: str


class ReleaseAuthorizer(Protocol):
    """Injected authorization boundary; the release service never guesses roles."""

    def authorize(
        self,
        *,
        space_id: str,
        actor: str,
        actor_type: str,
        role: str,
        manifest_hash: str,
        authorization_receipt: str,
    ) -> AuthorizationDecision: ...


def _insert_if_absent(
    session: Session,
    table: Any,
    values: dict[str, object],
    *,
    conflict_columns: tuple[str, ...],
) -> bool:
    """Issue one atomic, transaction-owned insert for supported production dialects."""

    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        inserted_id = session.scalar(
            sqlite_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=conflict_columns)
            .returning(table.c.id)
        )
    elif dialect == "postgresql":
        inserted_id = session.scalar(
            postgresql_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=conflict_columns)
            .returning(table.c.id)
        )
    else:
        raise RuntimeError(f"unsupported release authority dialect: {dialect}")
    return inserted_id is not None


def _canonical_payload(manifest: ReleaseManifest) -> dict[str, object]:
    payload = manifest.model_dump(mode="json")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    restored = ReleaseManifest.model_validate_json(encoded)
    if restored != manifest:
        raise ReleaseManifestPersistenceError("manifest canonical JSON roundtrip failed")
    return restored.model_dump(mode="json")


def _rebuild_exact_manifest(
    session: Session,
    scope: KnowledgeScope,
    manifest: ReleaseManifest,
) -> ReleaseManifest:
    try:
        rebuilt = build_release_manifest_from_snapshot(
            session,
            scope,
            snapshot_id=manifest.snapshot_id,
            schema_version=manifest.schema_version,
            template_hashes=manifest.template_hashes,
            model_plan_hash=manifest.model_plan_hash,
        )
    except (ReleaseManifestBuildError, ReleaseManifestIntegrityError, ValidationError) as exc:
        raise ReleaseManifestPersistenceError(
            "manifest does not match the frozen snapshot"
        ) from exc
    if rebuilt != manifest:
        raise ReleaseManifestPersistenceError("manifest does not match the frozen snapshot")
    return rebuilt


def persist_release_manifest(
    session: Session,
    scope: KnowledgeScope,
    manifest: ReleaseManifest,
) -> ReleaseManifestRecord:
    """Flush one verified canonical manifest without owning the caller transaction."""

    require_current_scope(session, scope)
    if manifest.space_id != scope.space_id:
        raise ReleaseManifestPersistenceError("manifest scope mismatch")
    try:
        verify_release_manifest(manifest)
        payload = _canonical_payload(manifest)
    except (ReleaseManifestIntegrityError, ValidationError, TypeError, ValueError) as exc:
        raise ReleaseManifestPersistenceError("manifest integrity validation failed") from exc
    _rebuild_exact_manifest(session, scope, manifest)

    existing = session.scalar(
        select(ReleaseManifestRecord).where(
            ReleaseManifestRecord.space_id == scope.space_id,
            ReleaseManifestRecord.snapshot_id == manifest.snapshot_id,
        )
    )
    if existing is not None:
        if existing.manifest_hash != manifest.manifest_sha256 or existing.payload != payload:
            raise ReleaseManifestPersistenceError(
                "snapshot is already bound to a different manifest"
            )
        return existing

    now = utcnow()
    _insert_if_absent(
        session,
        ReleaseManifestRecord.__table__,
        {
            "id": str(uuid.uuid4()),
            "space_id": scope.space_id,
            "snapshot_id": manifest.snapshot_id,
            "manifest_hash": manifest.manifest_sha256,
            "payload": payload,
            "created_at": now,
            "updated_at": now,
        },
        conflict_columns=("space_id", "snapshot_id"),
    )
    winner = session.scalar(
        select(ReleaseManifestRecord).where(
            ReleaseManifestRecord.space_id == scope.space_id,
            ReleaseManifestRecord.snapshot_id == manifest.snapshot_id,
        )
    )
    if (
        winner is not None
        and winner.manifest_hash == manifest.manifest_sha256
        and winner.payload == payload
    ):
        return winner
    raise ReleaseManifestPersistenceError(
        "snapshot is already bound to a different manifest"
    )


def _load_exact_manifest(
    session: Session,
    scope: KnowledgeScope,
    *,
    snapshot_id: str,
    manifest_hash: str,
) -> ReleaseManifest:
    record = session.scalar(
        select(ReleaseManifestRecord).where(
            ReleaseManifestRecord.space_id == scope.space_id,
            ReleaseManifestRecord.snapshot_id == snapshot_id,
        )
    )
    if record is None or record.manifest_hash != manifest_hash:
        raise ReleaseApprovalError("approval requires the persisted exact manifest")
    try:
        manifest = ReleaseManifest.model_validate_json(
            json.dumps(
                record.payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )
        verify_release_manifest(manifest)
    except (ValidationError, ReleaseManifestIntegrityError) as exc:
        raise ReleaseApprovalError("persisted manifest integrity failure") from exc
    if (
        manifest.space_id != scope.space_id
        or manifest.snapshot_id != snapshot_id
        or manifest.manifest_sha256 != manifest_hash
    ):
        raise ReleaseApprovalError("approval requires the persisted exact manifest")
    try:
        _rebuild_exact_manifest(session, scope, manifest)
    except ReleaseManifestPersistenceError as exc:
        raise ReleaseApprovalError("frozen projection drifted after manifest creation") from exc
    return manifest


def _valid_attestation_text(value: str) -> bool:
    return bool(value and value == value.strip())


class ReleaseApprovalService:
    """Approve an exact persisted manifest; never promote or own transactions."""

    def __init__(self, session: Session, authorizer: ReleaseAuthorizer) -> None:
        self._session = session
        self._authorizer = authorizer

    def approve(
        self,
        scope: KnowledgeScope,
        *,
        snapshot_id: str,
        manifest_hash: str,
        actor: str,
        actor_type: str,
        authorization_receipt: str,
        reason: str,
    ) -> ReleaseApproval:
        require_current_scope(self._session, scope)
        if actor_type not in {"human", "principal"}:
            raise ReleaseAuthorizationError("release approval requires a human principal")
        if not all(
            _valid_attestation_text(value)
            for value in (actor, authorization_receipt, reason)
        ):
            raise ReleaseApprovalError("approval attestation is incomplete")
        _load_exact_manifest(
            self._session,
            scope,
            snapshot_id=snapshot_id,
            manifest_hash=manifest_hash,
        )

        try:
            decision = self._authorizer.authorize(
                space_id=scope.space_id,
                actor=actor,
                actor_type=actor_type,
                role="release_approver",
                manifest_hash=manifest_hash,
                authorization_receipt=authorization_receipt,
            )
        except Exception as exc:
            raise ReleaseAuthorizationError("release authorization unavailable") from exc
        if decision.outcome != "authorized":
            raise ReleaseAuthorizationError("release authorization denied")
        if decision.space_id != scope.space_id:
            raise ReleaseAuthorizationError("authorization scope mismatch")
        if decision.actor != actor or decision.actor_type != actor_type:
            raise ReleaseAuthorizationError("authorization actor mismatch")
        if decision.role != "release_approver":
            raise ReleaseAuthorizationError("authorization role mismatch")
        if decision.manifest_hash != manifest_hash:
            raise ReleaseAuthorizationError("authorization manifest mismatch")
        if decision.authorization_receipt != authorization_receipt:
            raise ReleaseAuthorizationError("authorization receipt mismatch")

        existing = self._session.scalar(
            select(ReleaseApproval).where(
                ReleaseApproval.space_id == scope.space_id,
                ReleaseApproval.manifest_hash == manifest_hash,
            )
        )
        if existing is not None:
            if (
                existing.snapshot_id == snapshot_id
                and existing.actor == actor
                and existing.actor_type == actor_type
                and existing.role == "release_approver"
                and existing.authorization_receipt == authorization_receipt
                and existing.reason == reason
            ):
                return existing
            raise ReleaseApprovalError("manifest is already approved by another attestation")

        now = utcnow()
        _insert_if_absent(
            self._session,
            ReleaseApproval.__table__,
            {
                "id": str(uuid.uuid4()),
                "space_id": scope.space_id,
                "snapshot_id": snapshot_id,
                "manifest_hash": manifest_hash,
                "actor": actor,
                "actor_type": actor_type,
                "role": "release_approver",
                "authorization_receipt": authorization_receipt,
                "reason": reason,
                "approved_at": now,
                "created_at": now,
            },
            conflict_columns=("space_id", "manifest_hash"),
        )
        winner = self._session.scalar(
            select(ReleaseApproval).where(
                ReleaseApproval.space_id == scope.space_id,
                ReleaseApproval.manifest_hash == manifest_hash,
            )
        )
        if winner is not None and (
            winner.snapshot_id == snapshot_id
            and winner.actor == actor
            and winner.actor_type == actor_type
            and winner.role == "release_approver"
            and winner.authorization_receipt == authorization_receipt
            and winner.reason == reason
        ):
            return winner
        raise ReleaseApprovalError(
            "manifest is already approved by another attestation"
        )


__all__ = [
    "AuthorizationDecision",
    "EffectiveReleaseActorType",
    "ReleaseApprovalError",
    "ReleaseApprovalService",
    "ReleaseAuthorizationError",
    "ReleaseAuthorizer",
    "ReleaseManifestPersistenceError",
    "persist_release_manifest",
]
