"""OpenSpec 018 T5: frozen plan executor and strict Wiki ownership."""

import asyncio
from typing import Any

import pytest

from insurance_harness.adapters.weknora import (
    WeKnoraClientError,
    WeKnoraTransientError,
    WeKnoraWikiPage,
)
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge import RenderedPage
from insurance_harness.knowledge.release_plan import (
    LegacyPageOwnership,
    PageOwnershipCollision,
    PublishAction,
    PublishPlan,
    ReleasePlanExecutor,
)
from tests.support.release_018 import release_scope


class _MemoryWiki:
    def __init__(self) -> None:
        self.pages: dict[tuple[str, str], WeKnoraWikiPage] = {}
        self.calls: list[tuple[str, str, str]] = []
        self.response_loss_slug: str | None = None
        self.in_flight = 0
        self.max_in_flight = 0
        self.delay = False
        self.readback_snapshot_id: str | None = None

    async def _probe(self) -> None:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        if self.delay:
            await asyncio.sleep(0.005)
        self.in_flight -= 1

    async def get_wiki_page(self, kb_id: str, slug: str) -> WeKnoraWikiPage:
        self.calls.append(("get", kb_id, slug))
        await self._probe()
        page = self.pages.get((kb_id, slug))
        if page is None:
            raise WeKnoraClientError(404, "missing")
        return page

    async def create_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        self.calls.append(("create", kb_id, page.slug))
        await self._probe()
        self.pages[(kb_id, page.slug)] = self._stored(page)
        if page.slug == self.response_loss_slug:
            raise WeKnoraTransientError("response lost")
        return page

    async def update_wiki_page(
        self, kb_id: str, page: WeKnoraWikiPage
    ) -> WeKnoraWikiPage:
        self.calls.append(("update", kb_id, page.slug))
        await self._probe()
        self.pages[(kb_id, page.slug)] = self._stored(page)
        return page

    def _stored(self, page: WeKnoraWikiPage) -> WeKnoraWikiPage:
        if self.readback_snapshot_id is None:
            return page
        metadata = dict(page.page_metadata or {})
        metadata["snapshot_id"] = self.readback_snapshot_id
        return page.model_copy(update={"page_metadata": metadata})

    async def delete_wiki_page(self, kb_id: str, slug: str) -> None:
        self.calls.append(("delete", kb_id, slug))
        await self._probe()
        self.pages.pop((kb_id, slug), None)


def _page(
    scope: KnowledgeScope,
    *,
    slug: str = "product/A/V1/overview",
    snapshot_id: str = "snapshot-1",
) -> RenderedPage:
    return RenderedPage(
        slug=slug,
        title="产品A",
        content="# 产品A",
        page_metadata={
            "managed_by": "insurance-harness",
            "space_id": scope.space_id,
            "snapshot_id": snapshot_id,
        },
    )


def _plan(*actions: PublishAction, target: str = "snapshot-1") -> PublishPlan:
    return PublishPlan(
        base_snapshot_id=None,
        target_snapshot_id=target,
        actions=actions,
        compensation_actions=(),
    )


def test_r3_3_publish_plan_digest_is_canonical_and_order_sensitive(
    kb_session: Any,
) -> None:
    scope = release_scope(kb_session)
    action_a = PublishAction(kind="upsert", slug="a", page=_page(scope, slug="a"))
    action_b = PublishAction(kind="delete", slug="b")
    plan = _plan(action_a, action_b)

    assert len(plan.digest) == 64
    assert plan.digest == PublishPlan.model_validate(
        plan.model_dump(mode="json")
    ).digest
    assert plan.digest != _plan(action_b, action_a).digest
    with pytest.raises(ValueError):
        PublishAction(kind="upsert", slug="a")


async def test_r3_4_executor_create_update_delete404_and_attempt_callbacks(
    kb_session: Any,
) -> None:
    scope = release_scope(kb_session)
    wiki = _MemoryWiki()
    executor = ReleasePlanExecutor(wiki)
    existing = _page(scope, slug="existing")
    wiki.pages[(scope.wiki_kb_id, "existing")] = WeKnoraWikiPage(
        **existing.model_dump(mode="python")
    )
    started: list[int] = []
    finished: list[tuple[int, bool | None, str | None]] = []

    results = await executor.execute(
        scope,
        _plan(
            PublishAction(kind="upsert", slug="new", page=_page(scope, slug="new")),
            PublishAction(kind="upsert", slug="existing", page=existing),
            PublishAction(kind="delete", slug="missing"),
        ),
        attempt_started=lambda action_no, _action: started.append(action_no),
        attempt_finished=lambda action_no, _action, created_new, error: finished.append(
            (action_no, created_new, error)
        ),
    )

    assert started == [0, 1, 2]
    assert finished == [(0, True, None), (1, False, None), (2, False, None)]
    assert [result.created_new for result in results] == [True, False, False]
    assert ("create", scope.wiki_kb_id, "new") in wiki.calls
    assert ("update", scope.wiki_kb_id, "existing") in wiki.calls
    assert ("delete", scope.wiki_kb_id, "missing") not in wiki.calls


@pytest.mark.parametrize(
    "ownership", ["third_party", "wrong_space", "missing_snapshot"]
)
async def test_r4_4_executor_rejects_unowned_page_before_mutation(
    kb_session: Any,
    ownership: str,
) -> None:
    scope = release_scope(kb_session)
    wiki = _MemoryWiki()
    if ownership == "third_party":
        metadata = {"owner": "third-party"}
    elif ownership == "wrong_space":
        metadata = {"managed_by": "insurance-harness", "space_id": "other-space"}
    else:
        metadata = {
            "managed_by": "insurance-harness",
            "space_id": scope.space_id,
        }
    wiki.pages[(scope.wiki_kb_id, "shared")] = WeKnoraWikiPage(
        slug="shared", page_metadata=metadata
    )

    with pytest.raises(PageOwnershipCollision, match="page ownership collision"):
        await ReleasePlanExecutor(wiki).execute(
            scope,
            _plan(
                PublishAction(
                    kind="upsert", slug="shared", page=_page(scope, slug="shared")
                )
            ),
        )

    assert [call[0] for call in wiki.calls] == ["get"]


async def test_r3_5_upsert_readback_must_match_target_snapshot_metadata(
    kb_session: Any,
) -> None:
    scope = release_scope(kb_session)
    wiki = _MemoryWiki()
    wiki.readback_snapshot_id = "silently-wrong"
    finished: list[tuple[bool | None, str | None]] = []

    with pytest.raises(RuntimeError, match="wiki write verification failed"):
        await ReleasePlanExecutor(wiki).execute(
            scope,
            _plan(
                PublishAction(
                    kind="upsert",
                    slug="new",
                    page=_page(scope, slug="new", snapshot_id="snapshot-1"),
                )
            ),
            attempt_finished=lambda _number, _action, created_new, error: finished.append(
                (created_new, error)
            ),
        )

    assert finished == [(True, "wiki write verification failed")]
    assert [call[0] for call in wiki.calls] == ["get", "create", "get"]


async def test_r4_4_executor_adopts_only_exact_legacy_dual_match(
    kb_session: Any,
) -> None:
    scope = release_scope(kb_session)
    wiki = _MemoryWiki()
    wiki.pages[(scope.wiki_kb_id, "legacy")] = WeKnoraWikiPage(
        slug="legacy", page_metadata={"snapshot_id": "legacy-1"}
    )
    adoption = LegacyPageOwnership(
        snapshot_id="legacy-1", slugs=frozenset({"legacy"})
    )

    await ReleasePlanExecutor(wiki).execute(
        scope,
        _plan(
            PublishAction(
                kind="upsert", slug="legacy", page=_page(scope, slug="legacy")
            )
        ),
        legacy_ownership=adoption,
    )
    assert ("update", scope.wiki_kb_id, "legacy") in wiki.calls

    wiki.calls.clear()
    wiki.pages[(scope.wiki_kb_id, "other")] = WeKnoraWikiPage(
        slug="other", page_metadata={"snapshot_id": "legacy-1"}
    )
    with pytest.raises(PageOwnershipCollision):
        await ReleasePlanExecutor(wiki).execute(
            scope,
            _plan(
                PublishAction(
                    kind="upsert", slug="other", page=_page(scope, slug="other")
                )
            ),
            legacy_ownership=adoption,
        )


async def test_r3_4_response_loss_reports_unknown_creation_state(
    kb_session: Any,
) -> None:
    scope = release_scope(kb_session)
    wiki = _MemoryWiki()
    wiki.response_loss_slug = "new"
    finished: list[tuple[bool | None, str | None]] = []

    with pytest.raises(WeKnoraTransientError, match="response lost"):
        await ReleasePlanExecutor(wiki).execute(
            scope,
            _plan(
                PublishAction(
                    kind="upsert", slug="new", page=_page(scope, slug="new")
                )
            ),
            attempt_finished=lambda _number, _action, created_new, error: finished.append(
                (created_new, error)
            ),
        )

    assert finished == [(None, "response lost")]
    assert (scope.wiki_kb_id, "new") in wiki.pages


async def test_r4_5_executor_serializes_same_space_but_not_different_spaces(
    kb_session: Any,
) -> None:
    scope_a = release_scope(kb_session, "a")
    scope_b = release_scope(kb_session, "b")
    wiki = _MemoryWiki()
    wiki.delay = True
    executor = ReleasePlanExecutor(wiki)

    def plan_for(scope: KnowledgeScope, slug: str) -> PublishPlan:
        return _plan(
            PublishAction(kind="upsert", slug=slug, page=_page(scope, slug=slug)),
            target=f"snapshot-{slug}",
        )

    await asyncio.gather(
        executor.execute(scope_a, plan_for(scope_a, "a-1")),
        executor.execute(scope_a, plan_for(scope_a, "a-2")),
    )
    assert wiki.max_in_flight == 1

    wiki.max_in_flight = 0
    await asyncio.gather(
        executor.execute(scope_a, plan_for(scope_a, "a-3")),
        executor.execute(scope_b, plan_for(scope_b, "b-1")),
    )
    assert wiki.max_in_flight > 1
