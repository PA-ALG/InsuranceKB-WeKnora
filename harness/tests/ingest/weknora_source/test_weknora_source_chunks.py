"""WeKnora source transport: chunk pagination limits and retry rules."""

import httpx
import pytest
import respx

from insurance_harness.adapters.weknora import (
    WeKnoraClient,
    WeKnoraPaginationLimit,
    WeKnoraTransientError,
)
from insurance_harness.config import HarnessSettings
from insurance_harness.db.scope import KnowledgeScope
from tests.conftest import BASE_URL
from tests.ingest.weknora_source.helpers import KID, META_URL, _chunk, _metadata

CHUNKS_URL = f"{BASE_URL}/api/v1/chunks/{KID}"


@pytest.mark.parametrize("failure_status", [408, 429, 503])
@respx.mock
async def test_b1_2_chunks_consume_offsets_metadata_and_restart_whole_pagination(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
    failure_status: int,
) -> None:
    route = respx.get(CHUNKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [_chunk(0), _chunk(1)]}),
            httpx.Response(failure_status, text="retry page two"),
            httpx.Response(200, json={"data": [_chunk(0), _chunk(1)]}),
            httpx.Response(200, json={"data": [_chunk(2)]}),
        ]
    )

    chunks = await client.list_chunks(adapter_scope, KID, page_size=2)

    assert [chunk.id for chunk in chunks] == ["chunk-0", "chunk-1", "chunk-2"]
    assert chunks[0].start_at == 0
    assert chunks[0].end_at == 9
    assert chunks[0].metadata == {"section": "保障责任"}
    assert chunks[0].content_hash == "hash-0"
    assert [call.request.url.params["page"] for call in route.calls] == ["1", "2", "1", "2"]


@respx.mock
async def test_b1_6_chunk_pagination_exhaustion_never_returns_partial_list(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
) -> None:
    route = respx.get(CHUNKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [_chunk(0), _chunk(1)]}),
            httpx.Response(503, text="page two failed"),
        ]
        * 3
    )

    with pytest.raises(WeKnoraTransientError):
        await client.list_chunks(adapter_scope, KID, page_size=2)

    assert route.call_count == 6
    assert [call.request.url.params["page"] for call in route.calls] == [
        "1",
        "2",
        "1",
        "2",
        "1",
        "2",
    ]


@respx.mock
async def test_b1_6_page_size_above_server_cap_still_fetches_every_chunk(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
) -> None:
    route = respx.get(CHUNKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [_chunk(i) for i in range(100)]}),
            httpx.Response(200, json={"data": [_chunk(100)]}),
        ]
    )

    chunks = await client.list_chunks(adapter_scope, KID, page_size=101)

    assert len(chunks) == 101
    assert [call.request.url.params["page_size"] for call in route.calls] == ["100", "100"]


@respx.mock
async def test_b1_6_full_pages_stop_at_configured_page_limit_without_partial_result(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
) -> None:
    configured = settings.model_copy(
        update={"source_max_chunk_pages": 2, "source_max_chunks_per_knowledge": 100}
    )
    client = WeKnoraClient(configured)
    route = respx.get(CHUNKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [_chunk(0), _chunk(1)]}),
            httpx.Response(200, json={"data": [_chunk(2), _chunk(3)]}),
        ]
    )
    try:
        with pytest.raises(WeKnoraPaginationLimit):
            await client.list_chunks(adapter_scope, KID, page_size=2)
        assert route.call_count == 2
    finally:
        await client.aclose()


@respx.mock
async def test_b1_6_chunk_count_limit_fails_without_returning_partial_result(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
) -> None:
    configured = settings.model_copy(
        update={"source_max_chunk_pages": 10, "source_max_chunks_per_knowledge": 3}
    )
    client = WeKnoraClient(configured)
    route = respx.get(CHUNKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": [_chunk(0), _chunk(1)]}),
            httpx.Response(200, json={"data": [_chunk(2), _chunk(3)]}),
        ]
    )
    try:
        with pytest.raises(WeKnoraPaginationLimit):
            await client.list_chunks(adapter_scope, KID, page_size=2)
        assert route.call_count == 2
    finally:
        await client.aclose()


@pytest.mark.parametrize("status", [408, 429, 500, 503])
@respx.mock
async def test_b1_5_idempotent_get_retries_transient_statuses(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
    status: int,
) -> None:
    route = respx.get(META_URL).mock(
        side_effect=[
            httpx.Response(status, text="transient"),
            httpx.Response(200, json={"data": _metadata()}),
        ]
    )

    assert (await client.get_knowledge(adapter_scope, KID)).id == KID
    assert route.call_count == 2


@respx.mock
async def test_non_idempotent_post_is_never_automatically_retried(
    client: WeKnoraClient,
) -> None:
    url = f"{BASE_URL}/api/v1/knowledgebase/wiki-kb/wiki/folders"
    route = respx.post(url).mock(return_value=httpx.Response(503, text="uncertain create"))

    with pytest.raises(WeKnoraTransientError):
        await client.create_wiki_folder("wiki-kb", "保障责任")

    assert route.call_count == 1
