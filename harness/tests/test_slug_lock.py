"""S2.5 同 slug 并发写串行化（P-1 乐观锁补丁前的客户端侧保护）。"""

import asyncio

import httpx

from insurance_harness.adapters.weknora import WeKnoraClient, WeKnoraWikiPage
from insurance_harness.config import HarnessSettings
from tests.conftest import BASE_URL

KB = "kb-1"


class _OverlapProbe:
    """异步 handler：记录同时在途的请求数上限。"""

    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0
        self.count = 0

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        self.count += 1
        await asyncio.sleep(0.005)  # 制造重叠窗口
        self.in_flight -= 1
        return httpx.Response(
            200, json={"data": {"slug": "entity/x", "title": "X"}, "success": True}
        )


def _probe_client(settings: HarnessSettings, probe: _OverlapProbe) -> WeKnoraClient:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(probe), base_url=BASE_URL)
    return WeKnoraClient(settings, http_client=http_client)


async def test_s2_5_same_slug_writes_are_serialized(settings: HarnessSettings) -> None:
    probe = _OverlapProbe()
    client = _probe_client(settings, probe)
    page = WeKnoraWikiPage(slug="entity/x", title="X")
    await asyncio.gather(*(client.update_wiki_page(KB, page) for _ in range(10)))
    assert probe.count == 10
    assert probe.max_in_flight == 1, "同 slug 的写必须串行（S2.5）"
    await client.aclose()


async def test_s2_5_different_slugs_may_run_concurrently(settings: HarnessSettings) -> None:
    probe = _OverlapProbe()
    client = _probe_client(settings, probe)
    pages = [WeKnoraWikiPage(slug=f"entity/p-{i}", title="X") for i in range(10)]
    await asyncio.gather(*(client.update_wiki_page(KB, p) for p in pages))
    assert probe.count == 10
    assert probe.max_in_flight > 1, "不同 slug 不应被同一把锁串行化"
    await client.aclose()
