"""S2.4 wiki 页与目录 CRUD；写入体保留 source_refs/chunk_refs/page_metadata。"""

import json

import httpx
import respx

from insurance_harness.adapters.weknora import WeKnoraClient, WeKnoraWikiPage
from tests.conftest import BASE_URL

KB = "kb-1"
WIKI = f"{BASE_URL}/api/v1/knowledgebase/{KB}/wiki"


def _page_resp(payload: dict[str, object]) -> httpx.Response:
    data = {**payload, "id": "p-1", "version": 2}
    return httpx.Response(200, json={"data": data, "success": True})


@respx.mock
async def test_s2_4_create_and_get_roundtrip(client: WeKnoraClient) -> None:
    page = WeKnoraWikiPage(
        slug="entity/online-consult",
        title="在线问诊",
        page_type="entity",
        content="…",
        source_refs=["k-001|产品说明书"],
        chunk_refs=["c-1", "c-2"],
        page_metadata={"product_code": "1847H", "risk_level": "medium"},
    )
    create = respx.post(f"{WIKI}/pages").mock(
        return_value=_page_resp(page.model_dump(mode="json"))
    )
    created = await client.create_wiki_page(KB, page)

    sent = json.loads(create.calls[0].request.content)
    assert sent["slug"] == "entity/online-consult"
    assert sent["source_refs"] == ["k-001|产品说明书"]
    assert sent["chunk_refs"] == ["c-1", "c-2"]
    assert sent["page_metadata"]["product_code"] == "1847H"
    assert "id" not in sent and "version" not in sent  # 服务端管理字段不上送
    assert created.id == "p-1" and created.version == 2

    respx.get(f"{WIKI}/pages/entity/online-consult").mock(
        return_value=_page_resp(page.model_dump(mode="json"))
    )
    fetched = await client.get_wiki_page(KB, "entity/online-consult")
    assert fetched.chunk_refs == ["c-1", "c-2"]
    assert fetched.page_metadata is not None
    assert fetched.page_metadata["risk_level"] == "medium"


@respx.mock
async def test_s2_4_update_delete_move_folders(client: WeKnoraClient) -> None:
    page = WeKnoraWikiPage(slug="entity/x", title="X", content="v2")
    update = respx.put(f"{WIKI}/pages/entity/x").mock(
        return_value=_page_resp(page.model_dump(mode="json"))
    )
    await client.update_wiki_page(KB, page)
    assert json.loads(update.calls[0].request.content)["content"] == "v2"

    delete = respx.delete(f"{WIKI}/pages/entity/x").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await client.delete_wiki_page(KB, "entity/x")
    assert delete.called

    move = respx.put(f"{WIKI}/move-page").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    await client.move_wiki_page(KB, "entity/x", folder_id="f-9")
    assert json.loads(move.calls[0].request.content) == {"slug": "entity/x", "folder_id": "f-9"}

    respx.get(f"{WIKI}/folders").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "f-9", "name": "产品"}], "success": True}
        )
    )
    folders = await client.list_wiki_folders(KB)
    assert folders[0].name == "产品"

    create_folder = respx.post(f"{WIKI}/folders").mock(
        return_value=httpx.Response(
            200, json={"data": {"id": "f-10", "name": "责任", "parent_id": "f-9"}, "success": True}
        )
    )
    folder = await client.create_wiki_folder(KB, "责任", parent_id="f-9")
    assert folder.id == "f-10"
    assert json.loads(create_folder.calls[0].request.content)["parent_id"] == "f-9"
