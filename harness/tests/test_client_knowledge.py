"""S2.2 解析状态轮询。"""

import httpx
import pytest
import respx

from insurance_harness.adapters.weknora import WeKnoraClient, WeKnoraParseFailed
from tests.conftest import BASE_URL

KID = "k-001"
URL = f"{BASE_URL}/api/v1/knowledge/{KID}"


def _knowledge(status: str, error: str = "") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": {
                "id": KID,
                "knowledge_base_id": "kb-1",
                "title": "条款.pdf",
                "parse_status": status,
                "error_message": error,
            },
            "success": True,
        },
    )


@respx.mock
async def test_s2_2_wait_for_parsed_polls_until_completed(client: WeKnoraClient) -> None:
    route = respx.get(URL).mock(
        side_effect=[_knowledge("pending"), _knowledge("processing"), _knowledge("completed")]
    )
    knowledge = await client.wait_for_parsed(KID)
    assert knowledge.parse_status == "completed"
    assert route.call_count == 3
    # 鉴权头（S2.1）
    assert route.calls[0].request.headers["X-API-Key"] == "sk-test"


@respx.mock
async def test_s2_2_failed_raises_parse_failed(client: WeKnoraClient) -> None:
    respx.get(URL).mock(side_effect=[_knowledge("failed", "OCR crashed")])
    with pytest.raises(WeKnoraParseFailed) as exc:
        await client.wait_for_parsed(KID)
    assert exc.value.knowledge_id == KID
    assert "OCR crashed" in exc.value.error_message


@respx.mock
async def test_s2_2_timeout_raises_timeout_error(client: WeKnoraClient) -> None:
    respx.get(URL).mock(return_value=_knowledge("processing"))
    with pytest.raises(TimeoutError):
        await client.wait_for_parsed(KID)  # poll_timeout_s=0.5, interval=0.01
