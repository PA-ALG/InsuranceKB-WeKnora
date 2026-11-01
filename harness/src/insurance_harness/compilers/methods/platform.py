"""The platform calls method discovery makes, over WeKnora's versioned REST API (SK-2b Spec §3, §7).

Download a RAW material's current file, upload a copy into the discovery knowledge base, delete a
copy, and read that base's listing. Each call is a single request with one stable failure code;
none is retried here (the copy run reconciles on its next pass instead of sending again). Response
content and transport diagnostics never leave this module.
"""

import hashlib
import json
import re

import httpx

from insurance_harness.ingest.raw_sources import RawListing, RawSources, RawSourcesError

MAX_COPY_BYTES = 50 * 1024 * 1024  # the platform's upload limit (MAX_FILE_SIZE_MB default)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


class PlatformCallError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _checked(identifier: str) -> str:
    if not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier):
        raise PlatformCallError("INVALID_REQUEST")
    return identifier


class MaterialPlatform:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        max_bytes: int = MAX_COPY_BYTES,
    ) -> None:
        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL:
            raise PlatformCallError("INVALID_REQUEST") from None
        if url.scheme not in {"http", "https"} or not url.host or url.userinfo or not api_key:
            raise PlatformCallError("INVALID_REQUEST")
        self._base_url, self._api_key = str(url).rstrip("/"), api_key
        self._transport, self._max_bytes = transport, max_bytes

    def _client(self) -> httpx.Client:
        return httpx.Client(
            transport=self._transport,
            timeout=120.0,
            follow_redirects=False,
            trust_env=False,
            headers={"X-API-Key": self._api_key},
        )

    def listing(self, kb_id: str) -> RawListing:
        """The discovery base's knowledge items, read whole as a RAW listing is (S5b-2)."""
        try:
            return RawSources(self._base_url, self._api_key, self._transport).listing(kb_id)
        except RawSourcesError as error:
            raise PlatformCallError(error.code) from None

    def download(self, knowledge_id: str) -> bytes:
        """The material's current file, refused past the size limit without reading it all."""
        path = f"/api/v1/knowledge/{_checked(knowledge_id)}/download"
        try:
            with self._client() as client, client.stream("GET", self._base_url + path) as reply:
                if reply.status_code != 200:
                    raise PlatformCallError("SOURCE_UNAVAILABLE")
                length = reply.headers.get("Content-Length")
                if length is not None and length.isdigit() and int(length) > self._max_bytes:
                    raise PlatformCallError("SOURCE_TOO_LARGE")
                data = bytearray()
                for part in reply.iter_bytes():
                    data.extend(part)
                    if len(data) > self._max_bytes:
                        raise PlatformCallError("SOURCE_TOO_LARGE")
                return bytes(data)
        except httpx.HTTPError:
            raise PlatformCallError("SOURCE_UNAVAILABLE") from None

    def upload(self, kb_id: str, file_name: str, data: bytes) -> tuple[str, bool]:
        """The copy's knowledge id, and whether it was created now (#518 R1).

        Both answers carry the whole Knowledge, and either is taken only when it is a knowledge
        item of this base holding exactly these bytes. A duplicate of a file the base already holds
        (409 `duplicate_file`) that cannot be shown to be one is DUPLICATE_UNVERIFIED: never taken
        as the copy, reconciled from the listing on a later run. A new copy that is not one is
        UPLOAD_FAILED.
        """
        path = f"/api/v1/knowledge-bases/{_checked(kb_id)}/knowledge/file"
        try:
            with self._client() as client:
                reply = client.post(self._base_url + path, files={"file": (file_name, data)})
        except httpx.HTTPError:
            raise PlatformCallError("UPLOAD_FAILED") from None
        try:
            body = json.loads(reply.content.decode("utf-8"))
        except (ValueError, UnicodeError):
            raise PlatformCallError("UPLOAD_FAILED") from None
        if not isinstance(body, dict):
            raise PlatformCallError("UPLOAD_FAILED")
        created = reply.status_code == 200 and body.get("success") is True
        duplicate = reply.status_code == 409 and body.get("code") == "duplicate_file"
        if not (created or duplicate):
            raise PlatformCallError("UPLOAD_FAILED")
        item = body.get("data")
        copy_id = item.get("id") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or not isinstance(copy_id, str)
            or not _IDENTIFIER.fullmatch(copy_id)
            or item.get("knowledge_base_id") != kb_id
            or item.get("file_sha256") != hashlib.sha256(data).hexdigest()
        ):
            raise PlatformCallError("UPLOAD_FAILED" if created else "DUPLICATE_UNVERIFIED")
        return copy_id, created

    def delete(self, knowledge_id: str) -> None:
        path = f"/api/v1/knowledge/{_checked(knowledge_id)}"
        try:
            with self._client() as client:
                reply = client.delete(self._base_url + path)
        except httpx.HTTPError:
            raise PlatformCallError("DELETE_FAILED") from None
        if reply.status_code != 200:
            raise PlatformCallError("DELETE_FAILED")
