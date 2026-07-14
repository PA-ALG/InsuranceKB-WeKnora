"""S2.3 chunk 翻页拉全。"""

import httpx
import respx

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.db.scope import KnowledgeScope
from tests.conftest import BASE_URL

KID = "k-001"
URL = f"{BASE_URL}/api/v1/chunks/{KID}"


def _chunk(i: int) -> dict[str, object]:
    return {
        "id": f"c-{i}",
        "tenant_id": "tenant-1",
        "knowledge_id": KID,
        "knowledge_base_id": "kb-1",
        "content": f"第{i}段",
        "chunk_index": i,
    }


@respx.mock
async def test_s2_3_paginates_until_short_page(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
) -> None:
    page1 = httpx.Response(200, json={"data": [_chunk(0), _chunk(1)], "success": True})
    page2 = httpx.Response(200, json={"data": [_chunk(2)], "success": True})
    route = respx.get(URL).mock(side_effect=[page1, page2])

    chunks = await client.list_chunks(adapter_scope, KID, page_size=2)

    assert [c.id for c in chunks] == ["c-0", "c-1", "c-2"]
    assert chunks[0].content == "第0段"
    assert chunks[2].chunk_index == 2
    assert route.call_count == 2
    assert route.calls[0].request.url.params["page"] == "1"
    assert route.calls[1].request.url.params["page"] == "2"


@respx.mock
async def test_s2_3_empty_knowledge_returns_empty_list(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
) -> None:
    respx.get(URL).mock(return_value=httpx.Response(200, json={"data": [], "success": True}))
    assert await client.list_chunks(adapter_scope, KID) == []
