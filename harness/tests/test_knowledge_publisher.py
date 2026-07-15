"""K5.2~K5.5：WeKnora 发布器（respx 全 mock，无 live 实例）。"""

import json
import os
import uuid

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.orm import Session

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.config import HarnessSettings
from insurance_harness.db.scope import KnowledgeScope
from insurance_harness.knowledge import (
    MergeEngine,
    MergePolicy,
    ProposedClaim,
    ProposedEvidence,
    current_snapshot_id,
    publish_product_version,
    rollback_to_snapshot,
    snapshot_claim_set,
)
from insurance_harness.knowledge.tables import ChangeSet, ReleaseSnapshot
from tests.conftest import BASE_URL
from tests.kbhelpers import green_gate, seed_bound_scope, seed_product
from tests.support.live import AsyncCleanup, run_cleanups_preserving_failure

KB = "kb-wiki"
WIKI = f"{BASE_URL}/api/v1/knowledgebase/{KB}/wiki"


def _scope(session: Session, *, wiki_kb_id: str = KB) -> KnowledgeScope:
    return seed_bound_scope(
        session,
        tenant_id=f"tenant-{uuid.uuid4().hex}",
        raw_kb_id=f"raw-{uuid.uuid4().hex}",
        wiki_kb_id=wiki_kb_id,
    )


def _publish_claims(
    session: Session,
    scope: KnowledgeScope,
    version_id: str,
    *values: tuple[str, str, str],
) -> None:
    gate, fp = green_gate([predicate for predicate, _name, _value in values])
    engine = MergeEngine(
        session,
        scope=scope,
        policy=MergePolicy(auto_apply_add=True),
        quality_gate=gate,
        run_fingerprint=fp,
    )
    change_set, _ = engine.open_change_set(source_kind="document")
    engine.apply_batch(
        change_set,
        [
            ProposedClaim(
                space_id=scope.space_id,
                product_version_id=version_id,
                predicate=predicate,
                field_name=name,
                value_state="present",
                value=value,
                confidence=0.9,
                evidence=[
                    ProposedEvidence(
                        knowledge_id="k-brochure", doc_title="产品说明书",
                        quote=f"{name}证据", page=3, doc_role="official_desc",
                        authority_level=2,
                    )
                ],
            )
            for predicate, name, value in values
        ],
    )


def _page_resp(body: bytes | None = None) -> httpx.Response:
    payload = json.loads(body) if body else {"slug": "x"}
    return httpx.Response(200, json={"data": {**payload, "id": "p-1"}, "success": True})


@respx.mock
async def test_k5_3_publish_creates_page_and_snapshot(
    kb_session: Session, client: WeKnoraClient
) -> None:
    scope = _scope(kb_session)
    product, version = seed_product(kb_session, scope=scope)
    _publish_claims(kb_session, scope, version.id, ("waiting_period", "等待期", "90天"))
    slug = f"product/{product.product_code}/{version.version_label}/overview"

    respx.get(f"{WIKI}/pages/{slug}").mock(return_value=httpx.Response(404, text="not found"))
    create = respx.post(f"{WIKI}/pages").mock(
        side_effect=lambda request: _page_resp(request.content)
    )
    result = await publish_product_version(
        kb_session, client, scope, product_version_id=version.id, label="2026-07-12-r1"
    )
    assert create.called
    sent = json.loads(create.calls[0].request.content)
    assert sent["slug"] == slug and sent["status"] == "published"
    assert sent["page_metadata"]["snapshot_id"] == result.snapshot_id

    snapshot = kb_session.get(ReleaseSnapshot, result.snapshot_id)
    assert snapshot is not None and snapshot.label == "2026-07-12-r1"
    assert snapshot.rendered_pages  # 物化渲染产物
    claim_set = snapshot_claim_set(kb_session, scope, result.snapshot_id)
    assert len(claim_set) == 1 and claim_set[0][1] >= 1  # (claim_id, revision_no) 冻结
    assert current_snapshot_id(kb_session, scope) == result.snapshot_id  # 指针移动


@respx.mock
async def test_k5_3_second_publish_updates_existing_slug(
    kb_session: Session, client: WeKnoraClient
) -> None:
    scope = _scope(kb_session)
    product, version = seed_product(kb_session, scope=scope)
    _publish_claims(kb_session, scope, version.id, ("waiting_period", "等待期", "90天"))
    slug = f"product/{product.product_code}/{version.version_label}/overview"

    respx.get(f"{WIKI}/pages/{slug}").mock(return_value=_page_resp())
    update = respx.put(f"{WIKI}/pages/{slug}").mock(
        side_effect=lambda request: _page_resp(request.content)
    )
    result = await publish_product_version(
        kb_session, client, scope, product_version_id=version.id, label="r2"
    )
    assert update.called  # 已存在 → update，不 create
    assert current_snapshot_id(kb_session, scope) == result.snapshot_id


@respx.mock
async def test_k5_4_rollback_republishes_snapshot_and_leaves_trace(
    kb_session: Session, client: WeKnoraClient
) -> None:
    scope = _scope(kb_session)
    product, version = seed_product(kb_session, scope=scope)
    _publish_claims(kb_session, scope, version.id, ("waiting_period", "等待期", "90天"))
    slug = f"product/{product.product_code}/{version.version_label}/overview"

    respx.get(f"{WIKI}/pages/{slug}").mock(return_value=_page_resp())
    update = respx.put(f"{WIKI}/pages/{slug}").mock(
        side_effect=lambda request: _page_resp(request.content)
    )
    first = await publish_product_version(
        kb_session, client, scope, product_version_id=version.id, label="r1"
    )
    second = await publish_product_version(
        kb_session, client, scope, product_version_id=version.id, label="r2"
    )
    assert current_snapshot_id(kb_session, scope) == second.snapshot_id

    result = await rollback_to_snapshot(
        kb_session, client, scope, snapshot_id=first.snapshot_id, actor="operator"
    )
    assert current_snapshot_id(kb_session, scope) == first.snapshot_id  # 指针回切
    # 回滚重发布的内容与快照物化产物逐字一致
    last_sent = json.loads(update.calls[-1].request.content)
    assert last_sent["content"] == first.pages[0].content
    assert result.pages[0].page_metadata["snapshot_id"] == first.snapshot_id
    # rollback ChangeSet 留痕（回滚本身可审计）
    rollback_sets = kb_session.execute(
        select(ChangeSet).where(
            ChangeSet.space_id == scope.space_id,
            ChangeSet.source_kind == "rollback",
        )
    ).scalars().all()
    assert len(rollback_sets) == 1 and rollback_sets[0].created_by == "operator"


# --- K5.5：live 契约用例（无实例时跳过；遗留清单项，运行 `uv run pytest -m live`） ---

_LIVE_REQUIRED = ("HARNESS_LIVE_BASE_URL", "HARNESS_LIVE_API_KEY", "HARNESS_LIVE_KB_ID")


@pytest.mark.live
async def test_k5_5_live_publish_and_rollback_roundtrip(kb_session: Session) -> None:
    if any(not os.environ.get(k) for k in _LIVE_REQUIRED):
        pytest.skip(f"缺 live 环境变量：{_LIVE_REQUIRED}")
    settings = HarnessSettings(
        weknora_base_url=os.environ["HARNESS_LIVE_BASE_URL"],
        weknora_api_key=os.environ["HARNESS_LIVE_API_KEY"],
    )
    kb_id = os.environ["HARNESS_LIVE_KB_ID"]
    live_client = WeKnoraClient(settings)
    cleanup_slug: str | None = None
    primary_error: BaseException | None = None
    try:
        scope = _scope(kb_session, wiki_kb_id=kb_id)
        product, version = seed_product(
            kb_session,
            scope=scope,
            code=f"LIVE{uuid.uuid4().hex[:6]}",
            version_label="live",
        )
        _publish_claims(
            kb_session,
            scope,
            version.id,
            ("waiting_period", "等待期", "90天"),
        )
        cleanup_slug = f"product/{product.product_code}/{version.version_label}/overview"
        first = await publish_product_version(
            kb_session, live_client, scope,
            product_version_id=version.id, label=f"live-{uuid.uuid4().hex[:8]}",
        )
        assert first.pages[0].slug == cleanup_slug
        fetched = await live_client.get_wiki_page(scope.wiki_kb_id, first.pages[0].slug)
        assert fetched.content == first.pages[0].content
        rollback = await rollback_to_snapshot(
            kb_session, live_client, scope, snapshot_id=first.snapshot_id
        )
        refetched = await live_client.get_wiki_page(
            scope.wiki_kb_id, rollback.pages[0].slug
        )
        assert refetched.content == first.pages[0].content
    except BaseException as error:
        primary_error = error
        raise
    finally:
        cleanups: list[AsyncCleanup] = [live_client.aclose]
        if cleanup_slug is not None:
            registered_slug = cleanup_slug

            async def delete_registered_page() -> None:
                await live_client.delete_wiki_page(kb_id, registered_slug)

            cleanups.insert(0, delete_registered_page)
        await run_cleanups_preserving_failure(
            cleanups,
            primary_error=primary_error,
        )
