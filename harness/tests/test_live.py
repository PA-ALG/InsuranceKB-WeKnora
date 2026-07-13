"""S3.2 live 契约测试：against 真实 WeKnora 测试实例（版本列车升级门禁，docs 02 §8）。

需要环境变量：HARNESS_LIVE_BASE_URL / HARNESS_LIVE_API_KEY / HARNESS_LIVE_KB_ID。
缺任一则跳过。运行：``uv run pytest -m live``。
"""

import os
import uuid

import pytest

from insurance_harness.adapters.weknora import WeKnoraClient, WeKnoraWikiPage
from insurance_harness.config import HarnessSettings

pytestmark = pytest.mark.live

_REQUIRED = ("HARNESS_LIVE_BASE_URL", "HARNESS_LIVE_API_KEY", "HARNESS_LIVE_KB_ID")


def _live_settings() -> HarnessSettings | None:
    if any(not os.environ.get(k) for k in _REQUIRED):
        return None
    return HarnessSettings(
        weknora_base_url=os.environ["HARNESS_LIVE_BASE_URL"],
        weknora_api_key=os.environ["HARNESS_LIVE_API_KEY"],
    )


@pytest.fixture
def live() -> HarnessSettings:
    settings = _live_settings()
    if settings is None:
        pytest.skip(f"缺 live 环境变量：{_REQUIRED}")
    return settings


async def test_live_wiki_page_crud_roundtrip(live: HarnessSettings) -> None:
    kb_id = os.environ["HARNESS_LIVE_KB_ID"]
    client = WeKnoraClient(live)
    slug = f"harness-contract-test/{uuid.uuid4().hex[:8]}"
    page = WeKnoraWikiPage(
        slug=slug,
        title="契约测试页（可删除）",
        page_type="entity",
        content="insurance-harness live contract test",
        source_refs=[],
        chunk_refs=[],
        page_metadata={"harness_contract_test": True},
    )
    try:
        created = await client.create_wiki_page(kb_id, page)
        assert created.slug == slug
        fetched = await client.get_wiki_page(kb_id, slug)
        assert fetched.title == page.title
    finally:
        try:
            await client.delete_wiki_page(kb_id, slug)
        finally:
            await client.aclose()


async def test_live_knowledge_endpoint_shape(live: HarnessSettings) -> None:
    knowledge_id = os.environ.get("HARNESS_LIVE_KNOWLEDGE_ID")
    if not knowledge_id:
        pytest.skip("未设置 HARNESS_LIVE_KNOWLEDGE_ID")
    client = WeKnoraClient(live)
    try:
        knowledge = await client.get_knowledge(knowledge_id)
        assert knowledge.id == knowledge_id
        assert knowledge.parse_status  # 契约：字段存在
    finally:
        await client.aclose()
