"""Source lifecycle ordering, decisions, and scoped persistence (OpenSpec 021)."""

import hashlib
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator
from sqlalchemy import select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from insurance_harness.db.base import utcnow
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation, require_current_scope
from insurance_harness.knowledge.models import SourceImportIdentity
from insurance_harness.knowledge.source_aggregates import (
    validate_retract_tombstone as validate_retract_tombstone,
)
from insurance_harness.knowledge.source_aggregates import (
    validate_source_change_set_aggregate as validate_source_change_set_aggregate,
)
from insurance_harness.knowledge.source_keys import (
    derive_retract_event_key as derive_retract_event_key,
)
from insurance_harness.knowledge.tables import (
    ChangeItem,
    ChangeSet,
    Claim,
    ClaimEvidence,
    SourceEvent,
    SourceHead,
    SourceLifecycleBackfillIssue,
)
from insurance_harness.sources import (
    GenerationOrdering,
    ProcessedAtOrdering,
    SourceOrdering,
)

LifecycleState = Literal["active", "deleted"]
LifecycleDecision = Literal[
    "accepted_create",
    "accepted_advance",
    "accepted_delete",
    "accepted_reactivate",
    "idempotent",
    "stale",
    "blocked_deleted",
]
LifecycleBusinessIntent = Literal[
    "create_active",
    "reuse",
    "audit_noop",
    "create_tombstone",
    "advance_active",
    "reactivate",
]
EventAggregateKind = Literal["source_revision", "tombstone"]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class SourceLifecycleError(ValueError):
    """A lifecycle request cannot be persisted without violating its contract."""


class SourceLifecycleBlocked(SourceLifecycleError):
    """Normal lifecycle processing is blocked by an unresolved durable issue."""


class SourceLifecycleContention(SourceLifecycleError):
    """The bounded create/CAS retry budget was exhausted."""


class _RetryLifecycleAttempt(RuntimeError):
    """Internal sentinel that rolls back one nested attempt before rereading."""

    def __init__(self, initial_conflict: IntegrityError | None = None) -> None:
        super().__init__("retry source lifecycle attempt")
        self.initial_conflict = initial_conflict


class EventLinks(BaseModel):
    """Business aggregate links written once with the append-only event."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )

    aggregate_kind: EventAggregateKind | None = None
    change_set_id: str | None = None
    tombstone_change_item_id: str | None = None

    @field_validator("change_set_id", "tombstone_change_item_id")
    @classmethod
    def _validate_optional_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if type(value) is not str or value != value.strip() or not value or len(value) > 36:
            raise ValueError("event link identity is invalid")
        return value

    @model_validator(mode="after")
    def _validate_tombstone_parent(self) -> "EventLinks":
        if (self.change_set_id is None) != (self.aggregate_kind is None):
            raise ValueError("linked event requires an aggregate kind")
        if self.tombstone_change_item_id is not None and self.change_set_id is None:
            raise ValueError("tombstone link requires a change set")
        if (
            self.tombstone_change_item_id is not None
            and self.aggregate_kind != "tombstone"
        ):
            raise ValueError("tombstone item requires a tombstone aggregate")
        return self


class LifecycleBusinessOutcome(BaseModel):
    """Strict callback result: caller payload plus immutable event link identities."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
        arbitrary_types_allowed=True,
    )

    payload: Any
    aggregate_kind: EventAggregateKind | None = None
    change_set_id: str | None = None
    tombstone_change_item_id: str | None = None

    @model_validator(mode="after")
    def _validate_links(self) -> "LifecycleBusinessOutcome":
        EventLinks(
            aggregate_kind=self.aggregate_kind,
            change_set_id=self.change_set_id,
            tombstone_change_item_id=self.tombstone_change_item_id,
        )
        return self

    @property
    def links(self) -> EventLinks:
        return EventLinks(
            aggregate_kind=self.aggregate_kind,
            change_set_id=self.change_set_id,
            tombstone_change_item_id=self.tombstone_change_item_id,
        )


class PersistedLifecycleResult(BaseModel):
    """Durable coordinator result after its nested savepoint has succeeded."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )

    decision: LifecycleDecision
    business_intent: LifecycleBusinessIntent
    head_changed: bool
    head: "LifecycleHeadIdentity"
    event_id: str
    links: EventLinks
    business_payload: Any = None


LifecycleBusinessCallback = Callable[
    [Session, "LifecycleDecisionResult"],
    LifecycleBusinessOutcome,
]


class LifecycleHeadIdentity(BaseModel):
    """Strict pure projection of the durable lifecycle head."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )

    source_revision: str
    ordering: SourceOrdering
    state: LifecycleState
    version: Annotated[StrictInt, Field(ge=1)]

    @model_validator(mode="before")
    @classmethod
    def _revalidate_nested_ordering(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        normalized = dict(value)
        ordering = normalized.get("ordering")
        if isinstance(ordering, (ProcessedAtOrdering, GenerationOrdering)):
            normalized["ordering"] = ordering.model_dump(mode="python")
        return normalized

    @field_validator("source_revision")
    @classmethod
    def _strict_revision(cls, value: str) -> str:
        normalized = value.lower()
        if _SHA256_RE.fullmatch(normalized) is None:
            raise ValueError("source revision must be SHA-256")
        return normalized


class BackfillResolutionResult(BaseModel):
    """Stable identity of one durable, idempotent backfill resolution."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )

    issue_id: str
    head_id: str
    event_id: str
    head: LifecycleHeadIdentity
    links: EventLinks


class LifecycleDecisionResult(BaseModel):
    """Side-effect-free state-machine result consumed by persistence in Task 4B."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        revalidate_instances="always",
    )

    decision: LifecycleDecision
    next_head: LifecycleHeadIdentity
    business_intent: LifecycleBusinessIntent
    head_changed: bool

    @model_validator(mode="after")
    def _validate_decision_contract(self) -> "LifecycleDecisionResult":
        contracts: dict[
            LifecycleDecision,
            tuple[
                LifecycleBusinessIntent,
                bool,
                LifecycleState | None,
                Literal["any", "one", "at_least_two"],
            ],
        ] = {
            "accepted_create": ("create_active", True, "active", "one"),
            "accepted_advance": (
                "advance_active",
                True,
                "active",
                "at_least_two",
            ),
            "accepted_delete": ("create_tombstone", True, "deleted", "any"),
            "accepted_reactivate": (
                "reactivate",
                True,
                "active",
                "at_least_two",
            ),
            "idempotent": ("reuse", False, None, "any"),
            "stale": ("audit_noop", False, None, "any"),
            "blocked_deleted": ("audit_noop", False, "deleted", "any"),
        }
        expected_intent, expected_changed, expected_state, version_rule = contracts[
            self.decision
        ]
        invalid = (
            self.business_intent != expected_intent
            or self.head_changed is not expected_changed
            or (expected_state is not None and self.next_head.state != expected_state)
            or (version_rule == "one" and self.next_head.version != 1)
            or (version_rule == "at_least_two" and self.next_head.version < 2)
        )
        if invalid:
            raise ValueError("lifecycle decision result is inconsistent")
        return self


def _deep_validate_head(head: LifecycleHeadIdentity) -> LifecycleHeadIdentity:
    if not isinstance(head, LifecycleHeadIdentity):
        raise ValueError("head must be a LifecycleHeadIdentity")
    return LifecycleHeadIdentity.model_validate(head.model_dump(mode="python"))


def _deep_validate_incoming(incoming: SourceImportIdentity) -> SourceImportIdentity:
    if not isinstance(incoming, SourceImportIdentity):
        raise ValueError("incoming must be a SourceImportIdentity")
    return SourceImportIdentity.model_validate(incoming.model_dump(mode="python"))


def _validate_desired_state(desired_state: LifecycleState) -> LifecycleState:
    if type(desired_state) is not str or desired_state not in ("active", "deleted"):
        raise ValueError("desired state must be active or deleted")
    return desired_state


def _changed_result(
    *,
    previous: LifecycleHeadIdentity | None,
    incoming: SourceImportIdentity,
    state: LifecycleState,
    decision: LifecycleDecision,
    business_intent: LifecycleBusinessIntent,
) -> LifecycleDecisionResult:
    next_head = LifecycleHeadIdentity(
        source_revision=incoming.source_revision,
        ordering=incoming.ordering,
        state=state,
        version=1 if previous is None else previous.version + 1,
    )
    return LifecycleDecisionResult(
        decision=decision,
        next_head=next_head,
        business_intent=business_intent,
        head_changed=True,
    )


def _unchanged_result(
    *,
    head: LifecycleHeadIdentity,
    decision: LifecycleDecision,
    business_intent: LifecycleBusinessIntent,
) -> LifecycleDecisionResult:
    return LifecycleDecisionResult(
        decision=decision,
        next_head=head,
        business_intent=business_intent,
        head_changed=False,
    )


def _ordering_relation(
    head: LifecycleHeadIdentity,
    incoming: SourceImportIdentity,
) -> Literal["older", "equal", "newer"]:
    current = head.ordering
    candidate = incoming.ordering
    if current.kind != candidate.kind:
        raise ValueError("source ordering kind cannot change")

    same_ordering = current == candidate
    if head.source_revision == incoming.source_revision and not same_ordering:
        raise ValueError("source revision cannot map to different ordering values")
    if same_ordering and head.source_revision != incoming.source_revision:
        raise ValueError("source ordering collision maps to different revisions")
    if same_ordering:
        return "equal"

    if isinstance(current, ProcessedAtOrdering):
        if not isinstance(candidate, ProcessedAtOrdering):
            raise ValueError("source ordering kind cannot change")
        return "older" if candidate.value < current.value else "newer"
    if not isinstance(candidate, GenerationOrdering):
        raise ValueError("source ordering kind cannot change")
    return "older" if candidate.value < current.value else "newer"


def decide_source_lifecycle(
    head: LifecycleHeadIdentity | None,
    incoming: SourceImportIdentity,
    desired_state: LifecycleState,
) -> LifecycleDecisionResult:
    """Evaluate the exhaustive L3 matrix using only typed source ordering values."""

    desired = _validate_desired_state(desired_state)
    candidate = _deep_validate_incoming(incoming)
    current = None if head is None else _deep_validate_head(head)

    if current is None:
        if desired == "active":
            return _changed_result(
                previous=None,
                incoming=candidate,
                state="active",
                decision="accepted_create",
                business_intent="create_active",
            )
        return _changed_result(
            previous=None,
            incoming=candidate,
            state="deleted",
            decision="accepted_delete",
            business_intent="create_tombstone",
        )

    relation = _ordering_relation(current, candidate)
    if relation == "older":
        return _unchanged_result(
            head=current,
            decision="stale",
            business_intent="audit_noop",
        )

    if current.state == "active":
        if relation == "equal" and desired == "active":
            return _unchanged_result(
                head=current,
                decision="idempotent",
                business_intent="reuse",
            )
        if desired == "deleted":
            return _changed_result(
                previous=current,
                incoming=candidate,
                state="deleted",
                decision="accepted_delete",
                business_intent="create_tombstone",
            )
        return _changed_result(
            previous=current,
            incoming=candidate,
            state="active",
            decision="accepted_advance",
            business_intent="advance_active",
        )

    if relation == "equal":
        if desired == "active":
            return _unchanged_result(
                head=current,
                decision="blocked_deleted",
                business_intent="audit_noop",
            )
        return _unchanged_result(
            head=current,
            decision="idempotent",
            business_intent="reuse",
        )
    if desired == "active":
        return _changed_result(
            previous=current,
            incoming=candidate,
            state="active",
            decision="accepted_reactivate",
            business_intent="reactivate",
        )
    return _changed_result(
        previous=current,
        incoming=candidate,
        state="deleted",
        decision="accepted_delete",
        business_intent="create_tombstone",
    )


def source_lifecycle_lock_key(space_id: str, knowledge_id: str) -> int:
    """Derive the stable PostgreSQL signed-int64 lock key for one full source key."""

    if (
        type(space_id) is not str
        or type(knowledge_id) is not str
        or not space_id
        or not knowledge_id
    ):
        raise ValueError("source lock identity is invalid")
    space = space_id.encode("utf-8")
    knowledge = knowledge_id.encode("utf-8")
    payload = b"insurancekb-source-lifecycle-021\x00"
    payload += len(space).to_bytes(4, "big") + space
    payload += len(knowledge).to_bytes(4, "big") + knowledge
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big", signed=True)


def _validate_audit_value(value: str | None, *, field: str, limit: int) -> str | None:
    if value is None and field == "causation_id":
        return None
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
    ):
        raise ValueError(f"{field} is invalid")
    return value


def _ordering_columns(
    ordering: SourceOrdering,
) -> tuple[str, datetime | None, int | None]:
    if isinstance(ordering, ProcessedAtOrdering):
        return ordering.kind, ordering.value, None
    return ordering.kind, None, ordering.value


def _head_identity(session: Session, row: SourceHead) -> LifecycleHeadIdentity:
    if row.ordering_kind == "processed_at":
        value = row.ordering_processed_at
        if value is not None and value.tzinfo is None:
            if session.get_bind().dialect.name != "sqlite":
                raise SourceLifecycleError("persisted source ordering is invalid")
            value = value.replace(tzinfo=UTC)
        ordering: SourceOrdering = ProcessedAtOrdering(value=value)  # type: ignore[arg-type]
    elif row.ordering_kind == "generation":
        ordering = GenerationOrdering(value=row.ordering_generation)  # type: ignore[arg-type]
    else:
        raise SourceLifecycleError("persisted source ordering is invalid")
    try:
        return LifecycleHeadIdentity(
            source_revision=row.head_revision,
            ordering=ordering,
            state=cast(LifecycleState, row.state),
            version=row.version,
        )
    except ValueError as exc:
        raise SourceLifecycleError("persisted source head is invalid") from exc


def _head_snapshot(head: LifecycleHeadIdentity | None) -> dict[str, Any] | None:
    if head is None:
        return None
    return head.model_dump(mode="json")


def _deep_validate_business_outcome(
    outcome: LifecycleBusinessOutcome,
) -> LifecycleBusinessOutcome:
    if not isinstance(outcome, LifecycleBusinessOutcome):
        raise SourceLifecycleError(
            "business callback must return LifecycleBusinessOutcome"
        )
    try:
        return LifecycleBusinessOutcome.model_validate(
            outcome.model_dump(mode="python")
        )
    except ValueError as exc:
        raise SourceLifecycleError("business callback returned invalid outcome") from exc


def _validate_scoped_event_links(
    session: Session,
    scope: KnowledgeScope,
    incoming: SourceImportIdentity,
    desired_state: LifecycleState,
    decision: LifecycleDecision,
    links: EventLinks,
) -> None:
    if links.change_set_id is None:
        return
    change_set = session.scalar(
        select(ChangeSet).where(
            ChangeSet.id == links.change_set_id,
            ChangeSet.space_id == scope.space_id,
        )
    )
    if (
        change_set is None
        or change_set.knowledge_ids != [incoming.knowledge_id]
    ):
        raise ScopeViolation("source lifecycle aggregate mismatch")
    if links.aggregate_kind == "source_revision":
        valid_aggregate = (
            change_set.source_kind in ("document", "recompile")
            and change_set.external_record_id == incoming.knowledge_id
            and change_set.source_revision == incoming.source_revision
        )
    elif links.aggregate_kind == "tombstone":
        valid_aggregate = (
            desired_state == "deleted"
            and decision in ("accepted_delete", "idempotent")
            and change_set.source_kind == "document"
            and change_set.status == "applied"
            and change_set.external_record_id == incoming.knowledge_id
            and change_set.source_revision
            == derive_retract_event_key(
                incoming.knowledge_id,
                incoming.source_revision,
            )
        )
    else:
        valid_aggregate = False
    if not valid_aggregate:
        raise ScopeViolation("source lifecycle aggregate mismatch")
    if links.aggregate_kind == "source_revision":
        validate_source_change_set_aggregate(
            session,
            scope,
            incoming,
            change_set,
            allowed_source_kinds=("document", "recompile"),
        )
    else:
        validate_retract_tombstone(
            session,
            scope,
            change_set,
            knowledge_id=incoming.knowledge_id,
        )
    if links.tombstone_change_item_id is None:
        return
    item = session.scalar(
        select(ChangeItem).where(
            ChangeItem.id == links.tombstone_change_item_id,
            ChangeItem.change_set_id == change_set.id,
        )
    )
    if item is None:
        raise ScopeViolation("source lifecycle aggregate mismatch")
    if item.action != "retract":
        raise ScopeViolation("source lifecycle aggregate mismatch")


def _acquire_source_lock(
    session: Session,
    *,
    space_id: str,
    knowledge_id: str,
) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": source_lifecycle_lock_key(space_id, knowledge_id)},
    )


def _load_scoped_head(
    session: Session,
    scope: KnowledgeScope,
    knowledge_id: str,
) -> SourceHead | None:
    row = session.scalar(
        select(SourceHead)
        .where(
            SourceHead.space_id == scope.space_id,
            SourceHead.knowledge_id == knowledge_id,
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    if row is not None and (
        row.tenant_id != scope.tenant_id or row.raw_kb_id != scope.raw_kb_id
    ):
        raise ScopeViolation("source lifecycle scope mismatch")
    return row


def _block_open_backfill_issue(
    session: Session,
    scope: KnowledgeScope,
    knowledge_id: str,
) -> None:
    issue = session.scalar(
        select(SourceLifecycleBackfillIssue)
        .where(
            SourceLifecycleBackfillIssue.space_id == scope.space_id,
            SourceLifecycleBackfillIssue.knowledge_id == knowledge_id,
            SourceLifecycleBackfillIssue.status == "open",
        )
        .with_for_update()
    )
    if issue is None:
        return
    if issue.tenant_id != scope.tenant_id or issue.raw_kb_id != scope.raw_kb_id:
        raise ScopeViolation("source lifecycle scope mismatch")
    raise SourceLifecycleBlocked("source lifecycle backfill issue is open")


def _is_initial_head_unique_conflict(error: IntegrityError) -> bool:
    diagnostic = getattr(error.orig, "diag", None)
    constraint = getattr(diagnostic, "constraint_name", None)
    if constraint in {
        "uq_source_heads_space_knowledge",
        "uq_source_heads_scoped_source",
    }:
        return True
    message = str(error.orig).lower()
    return (
        "unique constraint failed: source_heads.space_id, "
        "source_heads.knowledge_id"
    ) in message or (
        "unique constraint failed: source_heads.space_id, "
        "source_heads.tenant_id, source_heads.raw_kb_id, "
        "source_heads.knowledge_id"
    ) in message


def _insert_initial_head(
    session: Session,
    head: SourceHead,
) -> IntegrityError | None:
    """Insert the first head behind a narrow savepoint; conflict means reread."""

    try:
        with session.begin_nested():
            session.add(head)
            session.flush()
    except IntegrityError as exc:
        if not _is_initial_head_unique_conflict(exc):
            raise
        return exc
    return None


def _cas_existing_head(
    session: Session,
    head: SourceHead,
    *,
    expected_version: int,
    next_head: LifecycleHeadIdentity,
    actor: str,
    updated_at: datetime,
) -> bool:
    """Advance an existing head only if its durable version is still current."""

    ordering_kind, processed_at, generation = _ordering_columns(next_head.ordering)
    result = session.execute(
        update(SourceHead)
        .where(
            SourceHead.id == head.id,
            SourceHead.space_id == head.space_id,
            SourceHead.knowledge_id == head.knowledge_id,
            SourceHead.version == expected_version,
        )
        .values(
            head_revision=next_head.source_revision,
            ordering_kind=ordering_kind,
            ordering_processed_at=processed_at,
            ordering_generation=generation,
            state=next_head.state,
            version=next_head.version,
            actor=actor,
            head_updated_at=updated_at,
        )
        .execution_options(synchronize_session=False)
    )
    assert isinstance(result, CursorResult)
    return result.rowcount == 1


def _coordinate_persistence_attempt(
    session: Session,
    scope: KnowledgeScope,
    candidate: SourceImportIdentity,
    desired: LifecycleState,
    *,
    actor: str,
    causation_id: str | None = None,
    apply_business: LifecycleBusinessCallback | None = None,
) -> PersistedLifecycleResult:
    _acquire_source_lock(
        session,
        space_id=scope.space_id,
        knowledge_id=candidate.knowledge_id,
    )
    _block_open_backfill_issue(
        session,
        scope,
        candidate.knowledge_id,
    )
    head_row = _load_scoped_head(
        session,
        scope,
        candidate.knowledge_id,
    )
    before = None if head_row is None else _head_identity(session, head_row)
    decision = decide_source_lifecycle(before, candidate, desired)
    requires_tombstone = desired == "deleted" and decision.decision in (
        "accepted_delete",
        "idempotent",
    )
    if requires_tombstone and apply_business is None:
        raise SourceLifecycleError(
            "accepted delete requires a tombstone business aggregate"
        )
    ordering_kind, processed_at, generation = _ordering_columns(
        decision.next_head.ordering
    )
    initial = head_row is None

    if head_row is None:
        head_row = SourceHead(
            space_id=scope.space_id,
            tenant_id=scope.tenant_id,
            raw_kb_id=scope.raw_kb_id,
            knowledge_id=candidate.knowledge_id,
            head_revision=decision.next_head.source_revision,
            ordering_kind=ordering_kind,
            ordering_processed_at=processed_at,
            ordering_generation=generation,
            state=decision.next_head.state,
            version=decision.next_head.version,
            last_event_id=None,
            actor=actor,
            head_updated_at=utcnow(),
        )
        initial_conflict = _insert_initial_head(session, head_row)
        if initial_conflict is not None:
            raise _RetryLifecycleAttempt(initial_conflict)
    elif decision.head_changed:
        assert before is not None
        if not _cas_existing_head(
            session,
            head_row,
            expected_version=before.version,
            next_head=decision.next_head,
            actor=actor,
            updated_at=utcnow(),
        ):
            raise _RetryLifecycleAttempt
        session.expire(head_row)
        session.refresh(head_row)

    business_outcome = LifecycleBusinessOutcome(payload=None)
    if apply_business is not None and decision.business_intent != "audit_noop":
        business_outcome = _deep_validate_business_outcome(
            apply_business(session, decision)
        )
        session.flush()
        if requires_tombstone and (
            business_outcome.aggregate_kind != "tombstone"
            or business_outcome.change_set_id is None
        ):
            raise SourceLifecycleError(
                "accepted delete requires a tombstone business aggregate"
            )
        _validate_scoped_event_links(
            session,
            scope,
            candidate,
            desired,
            decision.decision,
            business_outcome.links,
        )
    links = business_outcome.links

    event_row = SourceEvent(
        space_id=scope.space_id,
        tenant_id=scope.tenant_id,
        raw_kb_id=scope.raw_kb_id,
        knowledge_id=candidate.knowledge_id,
        input_revision=candidate.source_revision,
        ordering_kind=candidate.ordering.kind,
        ordering_processed_at=(
            candidate.ordering.value
            if isinstance(candidate.ordering, ProcessedAtOrdering)
            else None
        ),
        ordering_generation=(
            candidate.ordering.value
            if isinstance(candidate.ordering, GenerationOrdering)
            else None
        ),
        desired_state=desired,
        decision=decision.decision,
        before_head=_head_snapshot(before),
        after_head=_head_snapshot(decision.next_head),
        causation_id=causation_id,
        actor=actor,
        change_set_id=links.change_set_id,
        tombstone_change_item_id=links.tombstone_change_item_id,
    )
    session.add(event_row)
    session.flush()

    if decision.head_changed:
        head_row.last_event_id = event_row.id
        head_row.actor = actor
        head_row.head_updated_at = utcnow()
        session.flush()
        if not initial:
            session.refresh(head_row)

    return PersistedLifecycleResult(
        decision=decision.decision,
        business_intent=decision.business_intent,
        head_changed=decision.head_changed,
        head=decision.next_head,
        event_id=event_row.id,
        links=links,
        business_payload=business_outcome.payload,
    )


def coordinate_source_lifecycle(
    session: Session,
    scope: KnowledgeScope,
    incoming: SourceImportIdentity,
    desired_state: LifecycleState,
    *,
    actor: str,
    causation_id: str | None = None,
    apply_business: LifecycleBusinessCallback | None = None,
) -> PersistedLifecycleResult:
    """Persist one scoped lifecycle decision without owning the outer transaction."""

    candidate = _deep_validate_incoming(incoming)
    desired = _validate_desired_state(desired_state)
    validated_actor = _validate_audit_value(actor, field="actor", limit=128)
    validated_causation = _validate_audit_value(
        causation_id, field="causation_id", limit=255
    )
    assert validated_actor is not None
    if candidate.raw_kb_id != getattr(scope, "raw_kb_id", None):
        raise ScopeViolation("source lifecycle scope mismatch")
    if apply_business is not None and not callable(apply_business):
        raise ValueError("apply_business must be callable")

    require_current_scope(session, scope)
    initial_conflicts: list[IntegrityError] = []
    for _attempt in range(3):
        try:
            with session.begin_nested():
                return _coordinate_persistence_attempt(
                    session,
                    scope,
                    candidate,
                    desired,
                    actor=validated_actor,
                    causation_id=validated_causation,
                    apply_business=apply_business,
                )
        except _RetryLifecycleAttempt as retry:
            if retry.initial_conflict is not None:
                initial_conflicts.append(retry.initial_conflict)
            continue
    if len(initial_conflicts) == 3:
        raise initial_conflicts[-1]
    raise SourceLifecycleContention("source lifecycle retry budget exhausted")


def _stale_backfill_incompatible_evidence(
    session: Session,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
) -> int:
    target_ids = (
        select(ClaimEvidence.id)
        .join(Claim, Claim.id == ClaimEvidence.claim_id)
        .where(
            Claim.space_id == scope.space_id,
            ClaimEvidence.knowledge_id == identity.knowledge_id,
            ClaimEvidence.raw_kb_id == scope.raw_kb_id,
            ClaimEvidence.lineage_status.is_not(None),
            ClaimEvidence.source_revision.is_not(None),
            ClaimEvidence.source_revision != identity.source_revision,
            ClaimEvidence.stale_at.is_(None),
        )
    )
    result = cast(
        CursorResult[Any],
        session.execute(
            update(ClaimEvidence)
            .where(
                ClaimEvidence.id.in_(target_ids),
                ClaimEvidence.stale_at.is_(None),
            )
            .values(stale_at=utcnow())
            .execution_options(synchronize_session="fetch")
        ),
    )
    return result.rowcount or 0


def _apply_backfill_resolution_business(
    session: Session,
    decision: LifecycleDecisionResult,
    *,
    scope: KnowledgeScope,
    identity: SourceImportIdentity,
    desired_state: LifecycleState,
    actor: str,
) -> LifecycleBusinessOutcome:
    if desired_state == "active":
        return LifecycleBusinessOutcome(
            payload={
                "stale_count": _stale_backfill_incompatible_evidence(
                    session,
                    scope,
                    identity,
                )
            }
        )
    from insurance_harness.knowledge.merge import apply_source_aware_retract

    return apply_source_aware_retract(
        session,
        scope,
        identity,
        decision,
        created_by=actor,
    )


def _normalized_resolution_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _head_is_not_before(
    current: LifecycleHeadIdentity,
    resolution: LifecycleHeadIdentity,
) -> bool:
    if current.version < resolution.version:
        return False
    if isinstance(current.ordering, ProcessedAtOrdering) and isinstance(
        resolution.ordering,
        ProcessedAtOrdering,
    ):
        return current.ordering.value >= resolution.ordering.value
    if isinstance(current.ordering, GenerationOrdering) and isinstance(
        resolution.ordering,
        GenerationOrdering,
    ):
        return current.ordering.value >= resolution.ordering.value
    return False


def _require_exact_resolved_issue(
    issue: SourceLifecycleBackfillIssue,
    identity: SourceImportIdentity,
    desired_state: LifecycleState,
    *,
    actor: str,
    reason: str,
) -> None:
    ordering_kind, processed_at, generation = _ordering_columns(identity.ordering)
    exact = (
        issue.status == "resolved"
        and issue.knowledge_id == identity.knowledge_id
        and issue.resolved_revision == identity.source_revision
        and issue.resolved_ordering_kind == ordering_kind
        and _normalized_resolution_datetime(issue.resolved_processed_at)
        == _normalized_resolution_datetime(processed_at)
        and issue.resolved_generation == generation
        and issue.expected_state == desired_state
        and issue.resolved_by == actor
        and issue.resolution_reason == reason
        and issue.resolved_at is not None
    )
    if not exact:
        raise ScopeViolation("source lifecycle backfill resolution conflict")


def _backfill_resolution_result(
    session: Session,
    scope: KnowledgeScope,
    issue: SourceLifecycleBackfillIssue,
    identity: SourceImportIdentity,
    desired_state: LifecycleState,
    *,
    actor: str,
    reason: str,
) -> BackfillResolutionResult:
    _require_exact_resolved_issue(
        issue,
        identity,
        desired_state,
        actor=actor,
        reason=reason,
    )
    head_row = _load_scoped_head(session, scope, identity.knowledge_id)
    events = list(
        session.scalars(
            select(SourceEvent).where(
                SourceEvent.space_id == scope.space_id,
                SourceEvent.knowledge_id == identity.knowledge_id,
                SourceEvent.causation_id == f"backfill:{issue.id}",
            )
        )
    )
    if head_row is None or len(events) != 1:
        raise ScopeViolation("source lifecycle backfill resolution conflict")
    event = events[0]
    expected_decision: LifecycleDecision = (
        "accepted_create" if desired_state == "active" else "accepted_delete"
    )
    try:
        resolution_head = LifecycleHeadIdentity.model_validate(event.after_head)
    except ValueError as exc:
        raise ScopeViolation(
            "source lifecycle backfill resolution conflict"
        ) from exc
    current_head = _head_identity(session, head_row)
    current_not_before = _head_is_not_before(current_head, resolution_head)
    if (
        event.before_head is not None
        or event.input_revision != identity.source_revision
        or event.desired_state != desired_state
        or event.decision != expected_decision
        or event.actor != actor
        or resolution_head.source_revision != identity.source_revision
        or resolution_head.ordering != identity.ordering
        or resolution_head.state != desired_state
        or resolution_head.version != 1
        or not current_not_before
    ):
        raise ScopeViolation("source lifecycle backfill resolution conflict")
    if event.change_set_id is None:
        links = EventLinks()
    else:
        links = EventLinks(
            aggregate_kind=(
                "tombstone" if desired_state == "deleted" else "source_revision"
            ),
            change_set_id=event.change_set_id,
            tombstone_change_item_id=event.tombstone_change_item_id,
        )
    _validate_scoped_event_links(
        session,
        scope,
        identity,
        desired_state,
        expected_decision,
        links,
    )
    if desired_state == "deleted" and links.aggregate_kind != "tombstone":
        raise ScopeViolation("source lifecycle backfill resolution conflict")
    return BackfillResolutionResult(
        issue_id=issue.id,
        head_id=head_row.id,
        event_id=event.id,
        head=resolution_head,
        links=links,
    )


def resolve_source_lifecycle_backfill_issue(
    session: Session,
    scope: KnowledgeScope,
    *,
    issue_id: str,
    identity: SourceImportIdentity,
    desired_state: LifecycleState,
    actor: str,
    reason: str,
) -> BackfillResolutionResult:
    """Resolve one open ambiguity and create its authoritative first lifecycle event."""

    candidate = _deep_validate_incoming(identity)
    desired = _validate_desired_state(desired_state)
    validated_issue_id = _validate_audit_value(issue_id, field="issue_id", limit=36)
    validated_actor = _validate_audit_value(actor, field="actor", limit=128)
    validated_reason = _validate_audit_value(reason, field="reason", limit=2000)
    assert validated_issue_id is not None
    assert validated_actor is not None
    assert validated_reason is not None
    if candidate.raw_kb_id != scope.raw_kb_id:
        raise ScopeViolation("source lifecycle scope mismatch")
    require_current_scope(session, scope)

    with session.begin_nested():
        _acquire_source_lock(
            session,
            space_id=scope.space_id,
            knowledge_id=candidate.knowledge_id,
        )
        issue = session.scalar(
            select(SourceLifecycleBackfillIssue)
            .where(
                SourceLifecycleBackfillIssue.id == validated_issue_id,
                SourceLifecycleBackfillIssue.space_id == scope.space_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
        if issue is None:
            raise ScopeViolation("source lifecycle backfill issue is unavailable")
        if (
            issue.tenant_id != scope.tenant_id
            or issue.raw_kb_id != scope.raw_kb_id
            or issue.knowledge_id != candidate.knowledge_id
        ):
            raise ScopeViolation("source lifecycle scope mismatch")
        if issue.status == "resolved":
            return _backfill_resolution_result(
                session,
                scope,
                issue,
                candidate,
                desired,
                actor=validated_actor,
                reason=validated_reason,
            )
        if issue.status != "open":
            raise ScopeViolation("source lifecycle backfill resolution conflict")
        if _load_scoped_head(session, scope, candidate.knowledge_id) is not None:
            raise ScopeViolation("source lifecycle backfill resolution requires no head")

        ordering_kind, processed_at, generation = _ordering_columns(
            candidate.ordering
        )
        issue.status = "resolved"
        issue.resolved_revision = candidate.source_revision
        issue.resolved_ordering_kind = ordering_kind
        issue.resolved_processed_at = processed_at
        issue.resolved_generation = generation
        issue.expected_state = desired
        issue.resolved_by = validated_actor
        issue.resolution_reason = validated_reason
        issue.resolved_at = utcnow()
        session.flush()

        coordinate_source_lifecycle(
            session,
            scope,
            candidate,
            desired,
            actor=validated_actor,
            causation_id=f"backfill:{issue.id}",
            apply_business=lambda callback_session, decision: (
                _apply_backfill_resolution_business(
                    callback_session,
                    decision,
                    scope=scope,
                    identity=candidate,
                    desired_state=desired,
                    actor=validated_actor,
                )
            ),
        )
        return _backfill_resolution_result(
            session,
            scope,
            issue,
            candidate,
            desired,
            actor=validated_actor,
            reason=validated_reason,
        )
