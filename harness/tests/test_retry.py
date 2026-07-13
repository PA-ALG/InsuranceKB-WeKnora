"""S2.6 重试语义：5xx/超时指数退避；4xx 不重试。"""

import httpx
import pytest
import respx

from insurance_harness.adapters.weknora import (
    WeKnoraClient,
    WeKnoraClientError,
    WeKnoraTransientError,
)
from tests.conftest import BASE_URL

URL = f"{BASE_URL}/api/v1/knowledge/k-1"
OK = httpx.Response(
    200, json={"data": {"id": "k-1", "parse_status": "completed"}, "success": True}
)


@respx.mock
async def test_s2_6_retries_5xx_then_succeeds(client: WeKnoraClient) -> None:
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(500), httpx.Response(503), OK]
    )
    knowledge = await client.get_knowledge("k-1")
    assert knowledge.parse_status == "completed"
    assert route.call_count == 3  # retry_max_attempts=3


@respx.mock
async def test_s2_6_gives_up_after_max_attempts(client: WeKnoraClient) -> None:
    route = respx.get(URL).mock(return_value=httpx.Response(502))
    with pytest.raises(WeKnoraTransientError):
        await client.get_knowledge("k-1")
    assert route.call_count == 3


@respx.mock
async def test_s2_6_retries_transport_timeout(client: WeKnoraClient) -> None:
    route = respx.get(URL).mock(
        side_effect=[httpx.ConnectTimeout("boom"), OK]
    )
    knowledge = await client.get_knowledge("k-1")
    assert knowledge.id == "k-1"
    assert route.call_count == 2


@respx.mock
async def test_s2_6_4xx_no_retry_and_preserves_body(client: WeKnoraClient) -> None:
    route = respx.get(URL).mock(
        return_value=httpx.Response(404, json={"success": False, "message": "not found"})
    )
    with pytest.raises(WeKnoraClientError) as exc:
        await client.get_knowledge("k-1")
    assert route.call_count == 1, "4xx 不得重试"
    assert exc.value.status_code == 404
    assert "not found" in exc.value.body
