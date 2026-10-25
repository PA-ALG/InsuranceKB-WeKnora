"""The parsed materials of a RAW knowledge base, from WeKnora's native listing (S5b-2 Spec §2.2).

The listing is read whole, oldest first, and checked against the total it reports: a listing that
changes or lies while it is read fails as a whole, so attribution never runs on part of it.
"""

import json
import re
from typing import Annotated

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

PAGE_SIZE = 100  # the platform's largest page
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]
_Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class RawSourcesError(ValueError):
    """A caller-safe code, without response content or transport diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class RawSource(BaseModel):
    """One parsed material: the fixed revision attribution and compiling read."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    knowledge_id: _Identifier
    parse_attempt: int = Field(ge=1)
    file_name: str = Field(min_length=1)
    sha256: _Digest


class _Item(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    parse_status: str
    current_parse_attempt: int = 0
    file_name: str = ""
    file_sha256: str = ""


class _Page(BaseModel):
    model_config = ConfigDict(extra="ignore")
    success: bool
    data: list[_Item]
    total: int = Field(ge=0)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


class RawSources:
    """Reads one RAW knowledge base's listing through the platform's REST API."""

    def __init__(
        self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None
    ) -> None:
        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL:
            raise RawSourcesError("INVALID_REQUEST") from None
        if (
            url.scheme not in {"http", "https"}
            or not url.host
            or url.userinfo
            or url.query
            or url.fragment
            or not api_key.strip()
        ):
            raise RawSourcesError("INVALID_REQUEST")
        self._base_url = str(url).rstrip("/")
        self._api_key = api_key
        self._transport = transport

    def completed(self, raw_kb_id: str) -> list[RawSource]:
        """Every material whose parse completed, or an error for the whole listing."""
        if not isinstance(raw_kb_id, str) or not _IDENTIFIER.fullmatch(raw_kb_id):
            raise RawSourcesError("INVALID_REQUEST")
        items = self._all(f"{self._base_url}/api/v1/knowledge-bases/{raw_kb_id}/knowledge")
        if len({item.id for item in items}) != len(items):
            raise RawSourcesError("RAW_LISTING_INVALID")
        try:
            return [
                RawSource(
                    knowledge_id=item.id,
                    parse_attempt=item.current_parse_attempt,
                    file_name=item.file_name,
                    sha256=item.file_sha256,
                )
                for item in items
                if item.parse_status == "completed"
            ]
        except ValidationError:
            raise RawSourcesError("RAW_LISTING_INVALID") from None

    def _all(self, url: str) -> list[_Item]:
        items: list[_Item] = []
        total: int | None = None
        page = 1
        with httpx.Client(
            transport=self._transport, timeout=30.0, follow_redirects=False, trust_env=False
        ) as client:
            while total is None or len(items) < total:
                params: dict[str, str | int] = {
                    "page": page,
                    "page_size": PAGE_SIZE,
                    "sort_by": "created_at",
                    "sort_order": "asc",
                }
                try:
                    response = client.get(url, params=params, headers={"X-API-Key": self._api_key})
                except httpx.HTTPError:
                    raise RawSourcesError("RAW_LISTING_UNAVAILABLE") from None
                if response.status_code != 200:
                    raise RawSourcesError("RAW_LISTING_UNAVAILABLE")
                try:
                    body = _Page.model_validate(
                        json.loads(
                            response.content.decode("utf-8"), object_pairs_hook=_unique_object
                        )
                    )
                except (ValueError, UnicodeError, ValidationError, RecursionError):
                    raise RawSourcesError("RAW_LISTING_INVALID") from None
                if not body.success or (total is not None and body.total != total):
                    raise RawSourcesError("RAW_LISTING_INVALID")
                total = body.total
                if not body.data:
                    break
                items.extend(body.data)
                page += 1
        if len(items) != total:
            raise RawSourcesError("RAW_LISTING_INVALID")
        return items
