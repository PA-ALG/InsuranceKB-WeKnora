"""WeKnora REST 客户端。

要点（specs S2.2~S2.7；设计 001）：
- 鉴权：``X-API-Key`` 头；响应统一解包 ``{"data": ..., "success": true}``；
- 5xx/网络错误经 tenacity 指数退避重试（S2.6），4xx 直接抛 ``WeKnoraClientError``；
- wiki 写入按 ``(kb_id, slug)`` 串行化（S2.5）——上游 PUT 是 last-write-wins、
  无乐观锁（P-1 补丁前的客户端侧规避，docs/insurance-kb/02 §4.2）；
- 每个调用包一层 tracing span（S2.7，无 Langfuse 时 no-op）。
"""

import asyncio
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from insurance_harness.adapters.weknora.errors import (
    WeKnoraClientError,
    WeKnoraParseFailed,
    WeKnoraTransientError,
)
from insurance_harness.adapters.weknora.models import (
    WeKnoraChunk,
    WeKnoraKnowledge,
    WeKnoraWikiFolder,
    WeKnoraWikiPage,
)
from insurance_harness.adapters.weknora.tracing import Tracer, build_tracer
from insurance_harness.config import HarnessSettings

_TERMINAL_FAILED = ("failed", "cancelled")


class WeKnoraClient:
    def __init__(
        self,
        settings: HarnessSettings,
        *,
        harness_job_id: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        tracer: Tracer | None = None,
    ) -> None:
        self._settings = settings
        # trust_env=False：Harness 与内网 WeKnora 直连，不受 shell 代理变量（如 ALL_PROXY）干扰
        self._client = http_client or httpx.AsyncClient(
            timeout=settings.http_timeout_s, trust_env=False
        )
        self._client.base_url = httpx.URL(settings.weknora_base_url.rstrip("/"))
        self._client.headers["X-API-Key"] = settings.weknora_api_key
        self._tracer = tracer or build_tracer(settings, harness_job_id)
        self._slug_locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------ http

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """发请求并解包 data；5xx/网络错误指数退避重试，4xx 不重试（S2.6）。"""
        retryer = AsyncRetrying(
            retry=retry_if_exception_type(WeKnoraTransientError),
            stop=stop_after_attempt(self._settings.retry_max_attempts),
            wait=wait_exponential(multiplier=0.05, max=1.0),
            reraise=True,
        )
        with self._tracer.span(f"weknora.{method} {path}"):
            async for attempt in retryer:
                with attempt:
                    return await self._send(method, path, json_body=json_body, params=params)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json_body: Any | None,
        params: dict[str, Any] | None,
    ) -> Any:
        try:
            resp = await self._client.request(method, path, json=json_body, params=params)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise WeKnoraTransientError(str(exc)) from exc
        if resp.status_code >= 500:
            raise WeKnoraTransientError(f"{resp.status_code}: {resp.text}")
        if resp.status_code >= 400:
            raise WeKnoraClientError(resp.status_code, resp.text)
        if not resp.content:
            return None
        payload: Any = resp.json()
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    # ------------------------------------------------------------- knowledge

    async def get_knowledge(self, knowledge_id: str) -> WeKnoraKnowledge:
        data = await self._request("GET", f"/api/v1/knowledge/{knowledge_id}")
        return WeKnoraKnowledge.model_validate(data)

    async def wait_for_parsed(self, knowledge_id: str) -> WeKnoraKnowledge:
        """轮询直到 parse_status=completed（S2.2）。

        failed/cancelled 抛 ``WeKnoraParseFailed``；超过 poll_timeout_s 抛 ``TimeoutError``。
        P-2（解析完成 webhook）补丁合入后本方法改为事件驱动的兜底。
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.poll_timeout_s
        while True:
            knowledge = await self.get_knowledge(knowledge_id)
            if knowledge.parse_status == "completed":
                return knowledge
            if knowledge.parse_status in _TERMINAL_FAILED:
                raise WeKnoraParseFailed(
                    knowledge_id, knowledge.parse_status, knowledge.error_message
                )
            if loop.time() >= deadline:
                raise TimeoutError(
                    f"knowledge {knowledge_id} not parsed within "
                    f"{self._settings.poll_timeout_s}s (last status: {knowledge.parse_status})"
                )
            await asyncio.sleep(self._settings.poll_interval_s)

    # ----------------------------------------------------------------- chunk

    async def list_chunks(self, knowledge_id: str, *, page_size: int = 100) -> list[WeKnoraChunk]:
        """翻页拉全某知识的 chunk（S2.3）。"""
        chunks: list[WeKnoraChunk] = []
        page = 1
        while True:
            data = await self._request(
                "GET",
                f"/api/v1/chunks/{knowledge_id}",
                params={"page": page, "page_size": page_size},
            )
            batch_raw = data.get("data", []) if isinstance(data, dict) else data
            batch = [WeKnoraChunk.model_validate(item) for item in batch_raw or []]
            chunks.extend(batch)
            if len(batch) < page_size:
                return chunks
            page += 1

    # ------------------------------------------------------------------ wiki

    def _wiki_base(self, kb_id: str) -> str:
        return f"/api/v1/knowledgebase/{kb_id}/wiki"

    def _slug_lock(self, kb_id: str, slug: str) -> asyncio.Lock:
        key = (kb_id, slug)
        lock = self._slug_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._slug_locks[key] = lock
        return lock

    async def get_wiki_page(self, kb_id: str, slug: str) -> WeKnoraWikiPage:
        data = await self._request("GET", f"{self._wiki_base(kb_id)}/pages/{slug}")
        return WeKnoraWikiPage.model_validate(data)

    async def create_wiki_page(self, kb_id: str, page: WeKnoraWikiPage) -> WeKnoraWikiPage:
        async with self._slug_lock(kb_id, page.slug):
            data = await self._request(
                "POST",
                f"{self._wiki_base(kb_id)}/pages",
                json_body=_page_payload(page),
            )
        return WeKnoraWikiPage.model_validate(data)

    async def update_wiki_page(self, kb_id: str, page: WeKnoraWikiPage) -> WeKnoraWikiPage:
        """按 slug 覆盖更新。上游为 last-write-wins，故客户端串行化同 slug 写入（S2.5）。"""
        async with self._slug_lock(kb_id, page.slug):
            data = await self._request(
                "PUT",
                f"{self._wiki_base(kb_id)}/pages/{page.slug}",
                json_body=_page_payload(page),
            )
        return WeKnoraWikiPage.model_validate(data)

    async def delete_wiki_page(self, kb_id: str, slug: str) -> None:
        async with self._slug_lock(kb_id, slug):
            await self._request("DELETE", f"{self._wiki_base(kb_id)}/pages/{slug}")

    async def move_wiki_page(self, kb_id: str, slug: str, *, folder_id: str) -> None:
        """移动页面到目标目录。请求体字段为适配层假设，live 契约测试负责校验。"""
        async with self._slug_lock(kb_id, slug):
            await self._request(
                "PUT",
                f"{self._wiki_base(kb_id)}/move-page",
                json_body={"slug": slug, "folder_id": folder_id},
            )

    async def list_wiki_folders(self, kb_id: str) -> list[WeKnoraWikiFolder]:
        data = await self._request("GET", f"{self._wiki_base(kb_id)}/folders")
        items = data.get("data", []) if isinstance(data, dict) else data
        return [WeKnoraWikiFolder.model_validate(item) for item in items or []]

    async def create_wiki_folder(
        self, kb_id: str, name: str, *, parent_id: str = ""
    ) -> WeKnoraWikiFolder:
        data = await self._request(
            "POST",
            f"{self._wiki_base(kb_id)}/folders",
            json_body={"name": name, "parent_id": parent_id},
        )
        return WeKnoraWikiFolder.model_validate(data)


def _page_payload(page: WeKnoraWikiPage) -> dict[str, Any]:
    """序列化写入体：剔除服务端管理的字段，保留 source_refs/chunk_refs/page_metadata。"""
    return page.model_dump(
        mode="json",
        exclude={"id", "version", "in_links", "out_links", "wiki_path"},
        exclude_none=True,
    )
