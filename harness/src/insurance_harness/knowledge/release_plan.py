"""Frozen release plans and ownership-safe Wiki execution (OpenSpec 018)."""

import asyncio
import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol
from weakref import WeakKeyDictionary

from pydantic import BaseModel, ConfigDict, model_validator

from insurance_harness.adapters.weknora.errors import WeKnoraClientError
from insurance_harness.adapters.weknora.models import WeKnoraWikiPage
from insurance_harness.adapters.weknora.scope import require_bound_scope
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge.pages import RenderedPage


class PageOwnershipCollision(RuntimeError):
    """A release action would overwrite or delete a page it does not own."""


class WikiWriteVerificationError(RuntimeError):
    """The remote page readback does not match the frozen target metadata."""

    def __init__(self, *, created_new: bool) -> None:
        super().__init__("wiki write verification failed")
        self.created_new = created_new


class StagingCapabilityRequired(PermissionError):
    """A legacy Wiki executor lacks an exact opaque staging/test capability."""


_STAGING_CAPABILITY_MARKER = object()


class _StagingCapability:
    __slots__ = ("_marker", "_scopes")

    _marker: object
    _scopes: frozenset[tuple[str, str]]

    def __init__(
        self,
        marker: object,
        scopes: frozenset[tuple[str, str]],
    ) -> None:
        if marker is not _STAGING_CAPABILITY_MARKER or not scopes:
            raise StagingCapabilityRequired("staging capability is required")
        object.__setattr__(self, "_marker", marker)
        object.__setattr__(self, "_scopes", scopes)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise StagingCapabilityRequired("staging capability is immutable")


def _issue_test_staging_capability(
    *scopes: KnowledgeScope,
) -> _StagingCapability:
    """Issue an exact capability only for explicit 018 test/staging scopes."""

    if not scopes:
        raise StagingCapabilityRequired("staging capability is required")
    identities: set[tuple[str, str]] = set()
    for scope in scopes:
        require_bound_scope(scope)
        identities.add((scope.space_id, scope.wiki_kb_id))
    return _StagingCapability(
        _STAGING_CAPABILITY_MARKER,
        frozenset(identities),
    )


def _require_staging_capability(
    capability: object,
    scope: KnowledgeScope | None = None,
) -> _StagingCapability:
    if (
        not isinstance(capability, _StagingCapability)
        or capability._marker is not _STAGING_CAPABILITY_MARKER
    ):
        raise StagingCapabilityRequired("staging capability is required")
    if scope is not None:
        require_bound_scope(scope)
        if (scope.space_id, scope.wiki_kb_id) not in capability._scopes:
            raise StagingCapabilityRequired("staging capability scope mismatch")
    return capability


class PublishAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["upsert", "delete"]
    slug: str
    page: RenderedPage | None = None

    @model_validator(mode="after")
    def _validate_shape(self) -> "PublishAction":
        if not self.slug.strip():
            raise ValueError("publish action slug is unavailable")
        if self.kind == "upsert" and (
            self.page is None or self.page.slug != self.slug
        ):
            raise ValueError("upsert action requires its matching page")
        if self.kind == "delete" and self.page is not None:
            raise ValueError("delete action cannot carry a page")
        return self


class PublishPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_snapshot_id: str | None
    target_snapshot_id: str
    actions: tuple[PublishAction, ...]
    compensation_actions: tuple[PublishAction, ...]

    @model_validator(mode="after")
    def _validate_identity(self) -> "PublishPlan":
        if not self.target_snapshot_id.strip():
            raise ValueError("publish plan target is unavailable")
        for actions in (self.actions, self.compensation_actions):
            slugs = [action.slug for action in actions]
            if len(slugs) != len(set(slugs)):
                raise ValueError("publish plan contains duplicate slugs")
        return self

    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def digest(self) -> str:
        payload = self.model_dump(mode="json")
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LegacyPageOwnership(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str
    slugs: frozenset[str]


class ActionExecution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_no: int
    kind: Literal["upsert", "delete"]
    slug: str
    created_new: bool | None


class WikiPageClient(Protocol):
    async def get_wiki_page(self, kb_id: str, slug: str) -> WeKnoraWikiPage: ...

    async def create_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage: ...

    async def update_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage: ...

    async def delete_wiki_page(self, kb_id: str, slug: str) -> None: ...


AttemptStarted = Callable[[int, PublishAction], Awaitable[None] | None]
AttemptFinished = Callable[
    [int, PublishAction, bool | None, str | None], Awaitable[None] | None
]


async def _callback(callback: Callable[..., Any] | None, *args: Any) -> None:
    if callback is None:
        return
    result = callback(*args)
    if inspect.isawaitable(result):
        await result


def _wiki_page(page: RenderedPage) -> WeKnoraWikiPage:
    return WeKnoraWikiPage(
        slug=page.slug,
        title=page.title,
        status="published",
        content=page.content,
        source_refs=page.source_refs,
        chunk_refs=page.chunk_refs,
        page_metadata=page.page_metadata,
    )


def _is_owned(
    remote: WeKnoraWikiPage,
    scope: KnowledgeScope,
    legacy_ownership: LegacyPageOwnership | None,
) -> bool:
    metadata = remote.page_metadata or {}
    if metadata.get("managed_by") == "insurance-harness":
        snapshot_id = metadata.get("snapshot_id")
        return (
            metadata.get("space_id") == scope.space_id
            and isinstance(snapshot_id, str)
            and bool(snapshot_id.strip())
        )
    return bool(
        legacy_ownership is not None
        and remote.slug in legacy_ownership.slugs
        and metadata.get("snapshot_id") == legacy_ownership.snapshot_id
    )


class ReleasePlanExecutor:
    """Execute one plan at a time per Space while allowing cross-Space work."""

    _locks: WeakKeyDictionary[
        object, dict[asyncio.AbstractEventLoop, dict[str, asyncio.Lock]]
    ] = WeakKeyDictionary()

    def __init__(
        self,
        client: WikiPageClient,
        *,
        lock_namespace: object | None = None,
        staging_capability: object | None = None,
    ) -> None:
        self._staging_capability = _require_staging_capability(staging_capability)
        self._client = client
        self._lock_namespace = lock_namespace or self

    def _space_lock(self, space_id: str) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        loops = self._locks.setdefault(self._lock_namespace, {})
        space_locks = loops.setdefault(loop, {})
        lock = space_locks.get(space_id)
        if lock is None:
            lock = asyncio.Lock()
            space_locks[space_id] = lock
        return lock

    def space_lock(self, scope: KnowledgeScope) -> asyncio.Lock:
        """Return the process-local lock shared by this Engine and Space."""
        _require_staging_capability(self._staging_capability, scope)
        return self._space_lock(scope.space_id)

    async def execute(
        self,
        scope: KnowledgeScope,
        plan: PublishPlan,
        *,
        attempt_started: AttemptStarted | None = None,
        attempt_finished: AttemptFinished | None = None,
        legacy_ownership: LegacyPageOwnership | None = None,
    ) -> tuple[ActionExecution, ...]:
        _require_staging_capability(self._staging_capability, scope)
        async with self.space_lock(scope):
            return await self._execute_locked(
                scope,
                plan,
                attempt_started=attempt_started,
                attempt_finished=attempt_finished,
                legacy_ownership=legacy_ownership,
            )

    async def _execute_locked(
        self,
        scope: KnowledgeScope,
        plan: PublishPlan,
        *,
        attempt_started: AttemptStarted | None = None,
        attempt_finished: AttemptFinished | None = None,
        legacy_ownership: LegacyPageOwnership | None = None,
    ) -> tuple[ActionExecution, ...]:
        """Execute while the caller holds this executor's Space lock."""
        _require_staging_capability(self._staging_capability, scope)
        results: list[ActionExecution] = []
        for action_no, action in enumerate(plan.actions):
            await _callback(attempt_started, action_no, action)
            created_new: bool | None = None
            try:
                created_new = await self._execute_action(
                    scope, action, legacy_ownership
                )
            except BaseException as exc:
                if isinstance(exc, WikiWriteVerificationError):
                    created_new = exc.created_new
                await _callback(
                    attempt_finished,
                    action_no,
                    action,
                    created_new,
                    str(exc),
                )
                raise
            await _callback(
                attempt_finished,
                action_no,
                action,
                created_new,
                None,
            )
            results.append(
                ActionExecution(
                    action_no=action_no,
                    kind=action.kind,
                    slug=action.slug,
                    created_new=created_new,
                )
            )
        return tuple(results)

    async def _execute_action(
        self,
        scope: KnowledgeScope,
        action: PublishAction,
        legacy_ownership: LegacyPageOwnership | None,
    ) -> bool | None:
        try:
            remote = await self._client.get_wiki_page(
                scope.wiki_kb_id, action.slug
            )
        except WeKnoraClientError as exc:
            if exc.status_code != 404:
                raise
            if action.kind == "delete":
                return False
            assert action.page is not None
            await self._client.create_wiki_page(
                scope.wiki_kb_id, _wiki_page(action.page)
            )
            await self._verify_upsert(
                scope,
                action.page,
                created_new=True,
                legacy_ownership=legacy_ownership,
            )
            return True

        if not _is_owned(remote, scope, legacy_ownership):
            raise PageOwnershipCollision("page ownership collision")
        if action.kind == "delete":
            await self._client.delete_wiki_page(scope.wiki_kb_id, action.slug)
            return False
        assert action.page is not None
        await self._client.update_wiki_page(
            scope.wiki_kb_id, _wiki_page(action.page)
        )
        await self._verify_upsert(
            scope,
            action.page,
            created_new=False,
            legacy_ownership=legacy_ownership,
        )
        return False

    async def _verify_upsert(
        self,
        scope: KnowledgeScope,
        page: RenderedPage,
        *,
        created_new: bool,
        legacy_ownership: LegacyPageOwnership | None,
    ) -> None:
        try:
            remote = await self._client.get_wiki_page(
                scope.wiki_kb_id, page.slug
            )
        except BaseException as exc:
            raise WikiWriteVerificationError(created_new=created_new) from exc
        expected = page.page_metadata or {}
        actual = remote.page_metadata or {}
        expected_snapshot_id = expected.get("snapshot_id")
        legacy_replay = bool(
            isinstance(expected_snapshot_id, str)
            and legacy_ownership is not None
            and expected_snapshot_id == legacy_ownership.snapshot_id
            and page.slug in legacy_ownership.slugs
        )
        if (
            not isinstance(expected_snapshot_id, str)
            or not expected_snapshot_id.strip()
            or actual.get("snapshot_id") != expected_snapshot_id
            or (
                not legacy_replay
                and (
                    actual.get("managed_by") != "insurance-harness"
                    or actual.get("space_id") != scope.space_id
                )
            )
        ):
            raise WikiWriteVerificationError(created_new=created_new)
