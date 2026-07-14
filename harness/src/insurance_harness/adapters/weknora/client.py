"""WeKnora REST 客户端。

要点（specs S2.2~S2.7；设计 001）：
- 鉴权：``X-API-Key`` 头；响应统一解包 ``{"data": ..., "success": true}``；
- 408/429/5xx/网络错误经 tenacity 指数退避重试，其他 4xx 为永久失败；
- wiki 写入按 ``(kb_id, slug)`` 串行化（S2.5）——上游 PUT 是 last-write-wins、
  无乐观锁（P-1 补丁前的客户端侧规避，docs/insurance-kb/02 §4.2）；
- 每个调用包一层 tracing span（S2.7，无 Langfuse 时 no-op）。
"""

import asyncio
import hashlib
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from pydantic import ValidationError
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from insurance_harness.adapters.weknora.errors import (
    WeKnoraClientError,
    WeKnoraDownloadTooLarge,
    WeKnoraIntegrityError,
    WeKnoraPaginationLimit,
    WeKnoraParseFailed,
    WeKnoraTransientError,
)
from insurance_harness.adapters.weknora.models import (
    DownloadedKnowledge,
    WeKnoraChunk,
    WeKnoraKnowledge,
    WeKnoraWikiFolder,
    WeKnoraWikiPage,
    normalize_safe_knowledge_id,
)
from insurance_harness.adapters.weknora.scope import (
    require_bound_scope,
    require_chunk_scope,
    require_knowledge_scope,
)
from insurance_harness.adapters.weknora.tracing import Tracer, build_tracer
from insurance_harness.config import HarnessSettings
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation

_TERMINAL_FAILED = ("failed", "cancelled")
_TRANSIENT_HTTP_STATUSES = (408, 429)
_IDEMPOTENT_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


class _DownloadIntegrityAttempt(Exception):
    """Internal retry signal; converted after the complete budget is exhausted."""


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
        """发请求并解包 data；只有幂等 HTTP 方法自动重试瞬时错误。"""
        with self._tracer.span(f"weknora.{method} {path}"):
            if method.upper() not in _IDEMPOTENT_HTTP_METHODS:
                return await self._send(
                    method, path, json_body=json_body, params=params
                )
            retryer = self._retryer(WeKnoraTransientError)
            async for attempt in retryer:
                with attempt:
                    return await self._send(method, path, json_body=json_body, params=params)
        raise AssertionError("unreachable")  # pragma: no cover

    def _retryer(self, *exception_types: type[BaseException]) -> AsyncRetrying:
        return AsyncRetrying(
            retry=retry_if_exception_type(exception_types),
            stop=stop_after_attempt(self._settings.retry_max_attempts),
            wait=wait_exponential(multiplier=0.05, max=1.0),
            reraise=True,
        )

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
        if resp.status_code in _TRANSIENT_HTTP_STATUSES or resp.status_code >= 500:
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

    async def get_knowledge(
        self,
        scope: KnowledgeScope,
        knowledge_id: str,
    ) -> WeKnoraKnowledge:
        require_bound_scope(scope)
        knowledge_id = _require_safe_knowledge_id(knowledge_id)
        data = await self._request("GET", f"/api/v1/knowledge/{knowledge_id}")
        knowledge = _parse_knowledge(data)
        if knowledge is None:
            raise ScopeViolation("scope mismatch")
        require_knowledge_scope(scope, knowledge, knowledge_id)
        return knowledge

    async def wait_for_parsed(
        self,
        scope: KnowledgeScope,
        knowledge_id: str,
    ) -> WeKnoraKnowledge:
        """轮询直到 parse_status=completed（S2.2）。

        failed/cancelled 抛 ``WeKnoraParseFailed``；超过 poll_timeout_s 抛 ``TimeoutError``。
        P-2（解析完成 webhook）补丁合入后本方法改为事件驱动的兜底。
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._settings.poll_timeout_s
        while True:
            knowledge = await self.get_knowledge(scope, knowledge_id)
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

    # --------------------------------------------------------------- download

    @asynccontextmanager
    async def download_knowledge(
        self,
        scope: KnowledgeScope,
        knowledge: WeKnoraKnowledge,
    ) -> AsyncIterator[DownloadedKnowledge]:
        """流式下载并校验 WeKnora 原件，context 退出即删除临时文件。

        每个 retry attempt 都重新打开响应并使用新的安全临时文件。截断和
        upstream MD5 不一致会重试；预算耗尽后转为永久完整性错误。
        """
        require_bound_scope(scope)
        knowledge_id = _require_safe_knowledge_id(knowledge.id)
        require_knowledge_scope(scope, knowledge, knowledge_id)
        expected_md5 = knowledge.file_hash.strip().lower()
        if not expected_md5:
            raise WeKnoraIntegrityError("knowledge metadata has no file_hash")
        if (
            knowledge.file_size is not None
            and knowledge.file_size > self._settings.source_max_file_bytes
        ):
            raise WeKnoraDownloadTooLarge(self._settings.source_max_file_bytes)

        retryer = self._retryer(WeKnoraTransientError, _DownloadIntegrityAttempt)
        downloaded: DownloadedKnowledge | None = None
        try:
            with self._tracer.span(f"weknora.GET /api/v1/knowledge/{knowledge_id}/download"):
                async for attempt in retryer:
                    with attempt:
                        downloaded = await self._download_once(knowledge_id, expected_md5)
        except _DownloadIntegrityAttempt as exc:
            raise WeKnoraIntegrityError(str(exc)) from exc
        if downloaded is None:  # pragma: no cover - tenacity either returns or raises
            raise AssertionError("unreachable")
        try:
            yield downloaded
        finally:
            downloaded.path.unlink(missing_ok=True)

    async def _download_once(
        self,
        knowledge_id: str,
        expected_md5: str,
    ) -> DownloadedKnowledge:
        output = tempfile.NamedTemporaryFile(
            mode="wb",
            prefix="insurancekb-source-",
            suffix=".bin",
            dir=self._settings.source_temp_dir,
            delete=False,
        )
        path = Path(output.name)
        try:
            try:
                async with self._client.stream(
                    "GET", f"/api/v1/knowledge/{knowledge_id}/download"
                ) as response:
                    await self._raise_for_stream_status(response)
                    expected_length = _content_length(response)
                    if (
                        expected_length is not None
                        and expected_length > self._settings.source_max_file_bytes
                    ):
                        raise WeKnoraDownloadTooLarge(
                            self._settings.source_max_file_bytes
                        )
                    md5 = hashlib.md5(usedforsecurity=False)
                    sha256 = hashlib.sha256()
                    byte_count = 0
                    # Keep using the descriptor created atomically by NamedTemporaryFile;
                    # closing then reopening by path would introduce a local TOCTOU window.
                    with output:
                        async for chunk in response.aiter_bytes(
                            self._settings.source_download_chunk_bytes
                        ):
                            byte_count += len(chunk)
                            if byte_count > self._settings.source_max_file_bytes:
                                raise WeKnoraDownloadTooLarge(
                                    self._settings.source_max_file_bytes
                                )
                            output.write(chunk)
                            md5.update(chunk)
                            sha256.update(chunk)
                    if expected_length is not None and byte_count != expected_length:
                        raise _DownloadIntegrityAttempt(
                            f"download truncated: expected {expected_length}, got {byte_count}"
                        )
                    actual_md5 = md5.hexdigest()
                    if actual_md5 != expected_md5:
                        raise _DownloadIntegrityAttempt(
                            f"file_hash mismatch: expected {expected_md5}, got {actual_md5}"
                        )
                    return DownloadedKnowledge(
                        path=path,
                        byte_count=byte_count,
                        upstream_md5=actual_md5,
                        original_digest=sha256.hexdigest(),
                    )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                raise WeKnoraTransientError(str(exc)) from exc
        except BaseException:
            output.close()
            path.unlink(missing_ok=True)
            raise

    async def _raise_for_stream_status(self, response: httpx.Response) -> None:
        if (
            response.status_code in _TRANSIENT_HTTP_STATUSES
            or response.status_code >= 500
        ):
            body = (await response.aread()).decode(errors="replace")
            raise WeKnoraTransientError(f"{response.status_code}: {body}")
        if response.status_code >= 400:
            body = (await response.aread()).decode(errors="replace")
            raise WeKnoraClientError(response.status_code, body)

    # ----------------------------------------------------------------- chunk

    async def list_chunks(
        self,
        scope: KnowledgeScope,
        knowledge_id: str,
        *,
        page_size: int = 100,
    ) -> list[WeKnoraChunk]:
        """翻页拉全某知识的 chunk（S2.3）。"""
        require_bound_scope(scope)
        knowledge_id = _require_safe_knowledge_id(knowledge_id)
        if type(page_size) is not int or page_size <= 0:
            raise ScopeViolation("scope mismatch")
        # WeKnora handler clamps values above 100. Mirror that cap locally so
        # the short-page termination check cannot mistake a clamped full page
        # for the end of the result set.
        page_size = min(page_size, 100)
        retryer = self._retryer(WeKnoraTransientError)
        with self._tracer.span(f"weknora.GET /api/v1/chunks/{knowledge_id}"):
            async for attempt in retryer:
                with attempt:
                    return await self._list_chunks_once(
                        scope, knowledge_id, page_size=page_size
                    )
        raise AssertionError("unreachable")  # pragma: no cover

    async def _list_chunks_once(
        self,
        scope: KnowledgeScope,
        knowledge_id: str,
        *,
        page_size: int,
    ) -> list[WeKnoraChunk]:
        chunks: list[WeKnoraChunk] = []
        page = 1
        while True:
            data = await self._send(
                "GET",
                f"/api/v1/chunks/{knowledge_id}",
                json_body=None,
                params={"page": page, "page_size": page_size},
            )
            batch_raw = _chunk_batch_payload(data)
            batch: list[WeKnoraChunk] = []
            for item in batch_raw:
                chunk = _parse_chunk(item)
                if chunk is None:
                    raise ScopeViolation("scope mismatch")
                batch.append(chunk)
            for chunk in batch:
                require_chunk_scope(scope, chunk, knowledge_id)
            if (
                len(chunks) + len(batch)
                > self._settings.source_max_chunks_per_knowledge
            ):
                raise WeKnoraPaginationLimit(
                    "chunk count exceeds configured source limit"
                )
            chunks.extend(batch)
            if len(batch) < page_size:
                return chunks
            if len(chunks) >= self._settings.source_max_chunks_per_knowledge:
                raise WeKnoraPaginationLimit(
                    "chunk count reached configured source limit before a terminal page"
                )
            if page >= self._settings.source_max_chunk_pages:
                raise WeKnoraPaginationLimit(
                    "chunk pages reached configured source limit before a terminal page"
                )
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


def _chunk_batch_payload(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        nested = data.get("data")
        if isinstance(nested, list):
            return nested
    raise ScopeViolation("scope mismatch") from None


def _parse_knowledge(data: Any) -> WeKnoraKnowledge | None:
    try:
        return WeKnoraKnowledge.model_validate(data)
    except (ValidationError, TypeError):
        return None


def _parse_chunk(data: Any) -> WeKnoraChunk | None:
    if not isinstance(data, dict):
        return None
    try:
        return WeKnoraChunk.model_validate(data)
    except (ValidationError, TypeError):
        return None


def _content_length(response: httpx.Response) -> int | None:
    raw = response.headers.get("content-length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise _DownloadIntegrityAttempt("invalid Content-Length") from exc
    if value < 0:
        raise _DownloadIntegrityAttempt("invalid Content-Length")
    return value


def _require_safe_knowledge_id(value: object) -> str:
    normalized = normalize_safe_knowledge_id(value)
    if normalized is None:
        raise ScopeViolation("scope mismatch")
    return normalized
