"""Read a discovery knowledge base's native Wiki pages over WeKnora's versioned REST (S6c §3.3).

The discovery base is unmanaged, so its native Wiki read routes are open to the API key. Each
read is a single request; failures stop with a stable code and never fall back.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from insurance_harness.compilers.wiki_pages.members import NativeChunk, NativePage

PAGE_SIZE = 100
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class NativeWikiError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class NativeWikiReader:
    def __init__(
        self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL:
            raise NativeWikiError("INVALID_REQUEST") from None
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or not api_key.strip()
        ):
            raise NativeWikiError("INVALID_REQUEST")
        self._base_url = str(url).rstrip("/")
        self._api_key = api_key
        self._transport = transport

    def pages(self, kb_id: str) -> list[NativePage]:
        """Every page of the knowledge base with the text of the chunks it cites, in order."""
        if not _IDENTIFIER.fullmatch(kb_id):
            raise NativeWikiError("INVALID_REQUEST")
        rows: list[dict[str, Any]] = []
        with self._client() as client:
            page = 1
            while True:
                body = self._get(
                    client,
                    f"/api/v1/knowledgebase/{kb_id}/wiki/pages",
                    {"page": page, "page_size": PAGE_SIZE},
                )
                batch = body.get("pages") if isinstance(body, dict) else None
                total_pages = body.get("total_pages") if isinstance(body, dict) else None
                if not isinstance(batch, list) or not isinstance(total_pages, int):
                    raise NativeWikiError("NATIVE_WIKI_UNREADABLE")
                rows.extend(row for row in batch if isinstance(row, dict))
                if page >= total_pages:
                    break
                page += 1
            return [self._page(client, row) for row in rows]

    def _page(self, client: httpx.Client, row: dict[str, Any]) -> NativePage:
        chunks = []
        for chunk_id in row.get("chunk_refs") or []:
            if not isinstance(chunk_id, str) or not _IDENTIFIER.fullmatch(chunk_id):
                raise NativeWikiError("NATIVE_WIKI_UNREADABLE")
            body = self._get(client, f"/api/v1/chunks/by-id/{chunk_id}", None)
            data = body.get("data") if isinstance(body, dict) else None
            content = data.get("content") if isinstance(data, dict) else None
            if not isinstance(content, str):
                raise NativeWikiError("NATIVE_WIKI_UNREADABLE")
            chunks.append(NativeChunk(content=content))
        try:
            return NativePage.model_validate(
                {
                    **row,
                    "aliases": row.get("aliases") or [],
                    "summary": row.get("summary") or "",
                    "chunks": chunks,
                }
            )
        except ValueError:
            raise NativeWikiError("NATIVE_WIKI_UNREADABLE") from None

    def _client(self) -> httpx.Client:
        return httpx.Client(
            transport=self._transport, timeout=30.0, follow_redirects=False, trust_env=False
        )

    def _get(self, client: httpx.Client, path: str, params: dict[str, Any] | None) -> Any:
        try:
            response = client.get(
                self._base_url + path, params=params, headers={"X-API-Key": self._api_key}
            )
        except httpx.HTTPError:
            raise NativeWikiError("NATIVE_WIKI_UNAVAILABLE") from None
        if response.status_code != 200:
            raise NativeWikiError("NATIVE_WIKI_UNAVAILABLE")
        try:
            return response.json()
        except ValueError:
            raise NativeWikiError("NATIVE_WIKI_UNREADABLE") from None
