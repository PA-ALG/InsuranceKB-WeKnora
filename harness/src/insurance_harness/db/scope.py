"""Database-bound KnowledgeSpace value object and fail-closed loader."""

import unicodedata
import weakref
from typing import Any

from pydantic import BaseModel, ConfigDict, PrivateAttr
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import or_, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, SessionTransaction

from insurance_harness.db.models import KnowledgeSpace


class _DatabaseScopeSentinel:
    """A private, deep-copy-stable marker represented by its class identity."""


_DATABASE_SCOPE_SENTINEL = _DatabaseScopeSentinel
_PENDING_BIND_TRANSACTIONS_KEY = "insurance_harness.scope.pending_bind_transactions"
_ScopeValues = tuple[str, str, str, str]
_ScopeAttestation = tuple[
    object,
    weakref.ReferenceType[Engine],
    str,
    str,
    str,
    str,
]


class KnowledgeScope(BaseModel):
    """Immutable external bindings for one persisted KnowledgeSpace."""

    model_config = ConfigDict(frozen=True)

    space_id: str
    tenant_id: str
    raw_kb_id: str
    wiki_kb_id: str
    _database_attestation: _ScopeAttestation | None = PrivateAttr(default=None)

    def __eq__(self, other: Any) -> bool:
        """Private loader provenance is not part of value-object equality."""
        if not isinstance(other, KnowledgeScope):
            return NotImplemented
        return _scope_values(self) == _scope_values(other)


class UnboundKnowledgeSpace(LookupError):
    """The requested ID does not resolve to a complete, bound space."""

    def __init__(self, space_id: str) -> None:
        super().__init__("knowledge space is unavailable")


class ScopeViolation(ValueError):
    """A supplied object does not belong to the requested knowledge scope."""


class ScopeBindingError(ValueError):
    """An administrative binding request could not be applied safely."""


def load_scope(session: Session, space_id: str) -> KnowledgeScope:
    """Load a complete bound scope, hiding whether a rejected ID exists."""
    values = _read_bound_scope_values(session, space_id)
    if values is None:
        raise UnboundKnowledgeSpace(space_id)
    scope = KnowledgeScope(
        space_id=values[0],
        tenant_id=values[1],
        raw_kb_id=values[2],
        wiki_kb_id=values[3],
    )
    scope._database_attestation = (
        _DATABASE_SCOPE_SENTINEL,
        weakref.ref(_database_bind_identity(session)),
        scope.space_id,
        scope.tenant_id,
        scope.raw_kb_id,
        scope.wiki_kb_id,
    )
    return scope


def bind_space(
    session: Session,
    space_id: str,
    *,
    tenant_id: str,
    raw_kb_id: str,
    wiki_kb_id: str,
) -> None:
    """Stage an atomic binding inside a clean caller-owned outer transaction."""
    outer_transaction = session.get_transaction()
    if not _valid_identifier(space_id, max_length=36) or not all(
        _valid_identifier(value, max_length=255)
        for value in (tenant_id, raw_kb_id, wiki_kb_id)
    ):
        raise ScopeBindingError("knowledge space binding failed")
    if (
        not session.is_active
        or outer_transaction is None
        or not outer_transaction.is_active
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise ScopeBindingError("knowledge space binding failed")

    integrity_failed = False
    try:
        with session.begin_nested():
            row = session.scalar(
                select(KnowledgeSpace)
                .where(KnowledgeSpace.id == space_id)
                .with_for_update()
            )
            if row is None or row.binding_status != "unbound":
                raise ScopeBindingError("knowledge space binding failed")
            if row.tenant_id is not None or row.raw_kb_id is not None or row.wiki_kb_id is not None:
                raise ScopeBindingError("knowledge space binding failed")

            conflict = session.scalar(
                select(KnowledgeSpace.id)
                .where(
                    KnowledgeSpace.id != space_id,
                    KnowledgeSpace.tenant_id == tenant_id,
                    or_(
                        KnowledgeSpace.raw_kb_id == raw_kb_id,
                        KnowledgeSpace.wiki_kb_id == wiki_kb_id,
                    ),
                )
                .limit(1)
            )
            if conflict is not None:
                raise ScopeBindingError("knowledge space binding failed")

            row.tenant_id = tenant_id
            row.raw_kb_id = raw_kb_id
            row.wiki_kb_id = wiki_kb_id
            row.binding_status = "bound"
            session.flush()
    except IntegrityError:
        integrity_failed = True

    if integrity_failed:
        raise ScopeBindingError("knowledge space binding failed")
    _record_pending_bind(session, space_id, outer_transaction)


def is_database_bound_scope(scope: object) -> bool:
    """Return whether scope provenance and current values match a successful DB load."""
    if not isinstance(scope, KnowledgeScope):
        return False
    attestation = getattr(scope, "_database_attestation", None)
    if not isinstance(attestation, tuple) or len(attestation) != 6:
        return False
    engine_reference = attestation[1]
    if not isinstance(engine_reference, weakref.ReferenceType):
        return False
    engine = engine_reference()
    return (
        attestation[0] is _DATABASE_SCOPE_SENTINEL
        and isinstance(engine, Engine)
        and attestation[2:] == _scope_values(scope)
    )


def require_current_scope(session: Session, scope: KnowledgeScope) -> None:
    """Require a loader-attested scope issued by this Session's Engine.

    The Engine identity is deliberately process-local and private. A serialized scope
    or one loaded through another Engine must be reloaded against the current DB bind.
    """
    if not is_database_bound_scope(scope):
        raise ScopeViolation("scope mismatch")
    attestation = scope._database_attestation
    if (
        attestation is None
        or attestation[1]() is not _database_bind_identity(session)
    ):
        raise ScopeViolation("scope mismatch")
    values = _read_bound_scope_values(session, scope.space_id)
    if values is None or values != _scope_values(scope):
        raise ScopeViolation("scope mismatch")


def _scope_values(scope: KnowledgeScope) -> tuple[object, object, object, object]:
    return (
        getattr(scope, "space_id", None),
        getattr(scope, "tenant_id", None),
        getattr(scope, "raw_kb_id", None),
        getattr(scope, "wiki_kb_id", None),
    )


def _database_bind_identity(session: Session) -> Engine:
    bind = session.get_bind(mapper=KnowledgeSpace)
    return bind.engine if isinstance(bind, Connection) else bind


def _read_bound_scope_values(session: Session, space_id: str) -> _ScopeValues | None:
    """Read persisted columns without identity-map reads or an ORM autoflush."""
    if _has_pending_space_state(session, space_id) or _has_active_bind_marker(
        session, space_id
    ):
        return None
    with session.no_autoflush:
        row = session.execute(
            select(
                KnowledgeSpace.id,
                KnowledgeSpace.binding_status,
                KnowledgeSpace.tenant_id,
                KnowledgeSpace.raw_kb_id,
                KnowledgeSpace.wiki_kb_id,
            ).where(KnowledgeSpace.id == space_id)
        ).one_or_none()
    if (
        row is None
        or row.binding_status != "bound"
        or not row.tenant_id
        or not row.raw_kb_id
        or not row.wiki_kb_id
    ):
        return None
    return (
        row.id,
        row.tenant_id,
        row.raw_kb_id,
        row.wiki_kb_id,
    )


def _has_pending_space_state(session: Session, space_id: str) -> bool:
    for collection in (session.new, session.dirty, session.deleted):
        for candidate in collection:
            if not isinstance(candidate, KnowledgeSpace):
                continue
            state = sa_inspect(candidate)
            identity_id = state.identity[0] if state.identity else None
            current_id = state.dict.get("id")
            if space_id == identity_id or space_id == current_id:
                return True
    return False


def _record_pending_bind(
    session: Session,
    space_id: str,
    transaction: SessionTransaction,
) -> None:
    markers = session.info.get(_PENDING_BIND_TRANSACTIONS_KEY)
    if not isinstance(markers, dict):
        markers = {}
        session.info[_PENDING_BIND_TRANSACTIONS_KEY] = markers
    markers[space_id] = transaction


def _has_active_bind_marker(session: Session, space_id: str) -> bool:
    markers = session.info.get(_PENDING_BIND_TRANSACTIONS_KEY)
    if not isinstance(markers, dict):
        return False
    transaction = markers.get(space_id)
    if isinstance(transaction, SessionTransaction) and transaction.is_active:
        return True
    markers.pop(space_id, None)
    if not markers:
        session.info.pop(_PENDING_BIND_TRANSACTIONS_KEY, None)
    return False


def _valid_identifier(value: object, *, max_length: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= max_length
        and not any(unicodedata.category(character).startswith("C") for character in value)
    )
