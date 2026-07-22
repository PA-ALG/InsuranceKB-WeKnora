"""Approved ReleaseManifest activation and logical rollback (OpenSpec 029 RA3/RA5)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from insurance_harness.db.base import utcnow
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation, require_current_scope
from insurance_harness.knowledge.release_manifest import (
    ReleaseManifest,
    ReleaseManifestBuildError,
    ReleaseManifestIntegrityError,
    build_release_manifest_from_snapshot,
    verify_release_manifest,
)
from insurance_harness.knowledge.tables import (
    CurrentRelease,
    ReleaseActivationAudit,
    ReleaseAlert,
    ReleaseApproval,
    ReleaseManifestRecord,
)

type ReleaseAction = Literal["promote", "rollback"]
type ReleaseAuthorityFailureCode = Literal[
    "scope_mismatch",
    "invalid_request",
    "stale_current_release",
    "manifest_missing",
    "manifest_mismatch",
    "manifest_tamper",
    "approval_missing",
    "rollback_target_not_activated",
]


@dataclass(frozen=True, slots=True)
class ReleaseActivationSuccess:
    action: ReleaseAction
    previous_snapshot_id: str | None
    snapshot_id: str
    manifest_hash: str
    audit_id: str


@dataclass(frozen=True, slots=True)
class ReleaseActivationFailure:
    code: ReleaseAuthorityFailureCode
    current_snapshot_id: str | None
    alert_id: str | None = None


type ReleaseActivationResult = ReleaseActivationSuccess | ReleaseActivationFailure


def _load_manifest(record: ReleaseManifestRecord) -> ReleaseManifest:
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
    return manifest


def _rebuild_manifest(
    session: Session,
    scope: KnowledgeScope,
    manifest: ReleaseManifest,
) -> ReleaseManifest:
    return build_release_manifest_from_snapshot(
        session,
        scope,
        snapshot_id=manifest.snapshot_id,
        schema_version=manifest.schema_version,
        template_hashes=manifest.template_hashes,
        model_plan_hash=manifest.model_plan_hash,
    )


def _cas_current_release(
    session: Session,
    *,
    space_id: str,
    expected_snapshot_id: str | None,
    target_snapshot_id: str,
) -> bool:
    now = utcnow()
    if expected_snapshot_id is None:
        values = {
            "space_id": space_id,
            "id": "current",
            "snapshot_id": target_snapshot_id,
            "created_at": now,
            "updated_at": now,
        }
        dialect = session.get_bind().dialect.name
        if dialect == "sqlite":
            inserted = session.scalar(
                sqlite_insert(CurrentRelease)
                .values(**values)
                .on_conflict_do_nothing(index_elements=("space_id",))
                .returning(CurrentRelease.space_id)
            )
        elif dialect == "postgresql":
            inserted = session.scalar(
                postgresql_insert(CurrentRelease)
                .values(**values)
                .on_conflict_do_nothing(index_elements=("space_id",))
                .returning(CurrentRelease.space_id)
            )
        else:
            raise RuntimeError(f"unsupported release authority dialect: {dialect}")
        return inserted is not None

    updated = session.scalar(
        update(CurrentRelease)
        .where(
            CurrentRelease.space_id == space_id,
            CurrentRelease.snapshot_id == expected_snapshot_id,
        )
        .values(snapshot_id=target_snapshot_id, updated_at=now)
        .returning(CurrentRelease.space_id)
    )
    return updated is not None


class ReleaseAuthorityService:
    """Move CurrentRelease only through explicit exact-approved CAS operations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def promote(
        self,
        scope: KnowledgeScope,
        *,
        snapshot_id: str,
        manifest_hash: str,
        expected_current_snapshot_id: str | None,
        reason: str,
    ) -> ReleaseActivationResult:
        return self._activate(
            "promote",
            scope,
            snapshot_id=snapshot_id,
            manifest_hash=manifest_hash,
            expected_current_snapshot_id=expected_current_snapshot_id,
            reason=reason,
        )

    def rollback(
        self,
        scope: KnowledgeScope,
        *,
        snapshot_id: str,
        manifest_hash: str,
        expected_current_snapshot_id: str | None,
        reason: str,
    ) -> ReleaseActivationResult:
        return self._activate(
            "rollback",
            scope,
            snapshot_id=snapshot_id,
            manifest_hash=manifest_hash,
            expected_current_snapshot_id=expected_current_snapshot_id,
            reason=reason,
        )

    def _activate(
        self,
        action: ReleaseAction,
        scope: KnowledgeScope,
        *,
        snapshot_id: str,
        manifest_hash: str,
        expected_current_snapshot_id: str | None,
        reason: str,
    ) -> ReleaseActivationResult:
        try:
            require_current_scope(self._session, scope)
        except ScopeViolation:
            return ReleaseActivationFailure(
                code="scope_mismatch",
                current_snapshot_id=None,
            )
        if not snapshot_id or not manifest_hash or not reason or reason != reason.strip():
            return ReleaseActivationFailure(
                code="invalid_request",
                current_snapshot_id=None,
            )

        current_snapshot_id = self._session.scalar(
            select(CurrentRelease.snapshot_id).where(
                CurrentRelease.space_id == scope.space_id
            )
        )
        if current_snapshot_id != expected_current_snapshot_id:
            return ReleaseActivationFailure(
                code="stale_current_release",
                current_snapshot_id=current_snapshot_id,
            )

        record = self._session.scalar(
            select(ReleaseManifestRecord).where(
                ReleaseManifestRecord.space_id == scope.space_id,
                ReleaseManifestRecord.snapshot_id == snapshot_id,
            )
        )
        if record is None:
            return ReleaseActivationFailure(
                code="manifest_missing",
                current_snapshot_id=current_snapshot_id,
            )
        if record.manifest_hash != manifest_hash:
            return ReleaseActivationFailure(
                code="manifest_mismatch",
                current_snapshot_id=current_snapshot_id,
            )

        try:
            manifest = _load_manifest(record)
            if (
                manifest.space_id != scope.space_id
                or manifest.snapshot_id != snapshot_id
                or manifest.manifest_sha256 != manifest_hash
                or _rebuild_manifest(self._session, scope, manifest) != manifest
            ):
                raise ReleaseManifestIntegrityError("persisted manifest identity drift")
        except (
            ValidationError,
            ReleaseManifestBuildError,
            ReleaseManifestIntegrityError,
            TypeError,
            ValueError,
        ):
            alert = ReleaseAlert(
                space_id=scope.space_id,
                snapshot_id=snapshot_id,
                manifest_hash=manifest_hash,
                code="manifest_tamper",
                severity="critical",
                safe_details={"action": action, "stage": "manifest_verification"},
            )
            self._session.add(alert)
            self._session.flush()
            return ReleaseActivationFailure(
                code="manifest_tamper",
                current_snapshot_id=current_snapshot_id,
                alert_id=alert.id,
            )

        approval = self._session.scalar(
            select(ReleaseApproval).where(
                ReleaseApproval.space_id == scope.space_id,
                ReleaseApproval.snapshot_id == snapshot_id,
                ReleaseApproval.manifest_hash == manifest_hash,
            )
        )
        if (
            approval is None
            or approval.actor_type not in {"human", "principal"}
            or approval.role != "release_approver"
        ):
            return ReleaseActivationFailure(
                code="approval_missing",
                current_snapshot_id=current_snapshot_id,
            )

        if action == "rollback" and self._session.scalar(
            select(ReleaseActivationAudit.id)
            .where(
                ReleaseActivationAudit.space_id == scope.space_id,
                ReleaseActivationAudit.target_snapshot_id == snapshot_id,
                ReleaseActivationAudit.manifest_hash == manifest_hash,
                ReleaseActivationAudit.kind.in_(("promote", "rollback")),
            )
            .limit(1)
        ) is None:
            return ReleaseActivationFailure(
                code="rollback_target_not_activated",
                current_snapshot_id=current_snapshot_id,
            )

        if not _cas_current_release(
            self._session,
            space_id=scope.space_id,
            expected_snapshot_id=expected_current_snapshot_id,
            target_snapshot_id=snapshot_id,
        ):
            observed = self._session.scalar(
                select(CurrentRelease.snapshot_id).where(
                    CurrentRelease.space_id == scope.space_id
                )
            )
            return ReleaseActivationFailure(
                code="stale_current_release",
                current_snapshot_id=observed,
            )

        audit = ReleaseActivationAudit(
            space_id=scope.space_id,
            kind=action,
            from_snapshot_id=current_snapshot_id,
            target_snapshot_id=snapshot_id,
            manifest_hash=manifest_hash,
            approval_id=approval.id,
            actor=approval.actor,
            reason=reason,
        )
        self._session.add(audit)
        self._session.flush()
        return ReleaseActivationSuccess(
            action=action,
            previous_snapshot_id=current_snapshot_id,
            snapshot_id=snapshot_id,
            manifest_hash=manifest_hash,
            audit_id=audit.id,
        )


__all__ = [
    "ReleaseAction",
    "ReleaseActivationFailure",
    "ReleaseActivationResult",
    "ReleaseActivationSuccess",
    "ReleaseAuthorityFailureCode",
    "ReleaseAuthorityService",
]
