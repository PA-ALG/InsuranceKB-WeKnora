"""Read and verify immutable page text from WeKnora's captured parse artifact.

Office captures (S11b) also return each page's located blocks; such a document's pages become
OfficePageText, re-checked against their text (S11c Spec §2.1). Whether a document is Office is
decided by the presence of the `blocks` key on any page, never by whether a list is empty, so
Office text cannot pass as PDF text (review R1 on #479). PDF pages carry no blocks key and become
PageText exactly as before.
"""

import hashlib
import json
import re
from typing import Annotated, Literal

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from insurance_harness.contracts.enums import LocatorKind
from insurance_harness.contracts.knowledge import Locator
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.evidence.office_pages import (
    OFFICE_LOCATOR_FIELDS,
    OfficeBlock,
    OfficePageText,
    check_office_document,
)

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
_NonBlank = Annotated[str, StringConstraints(pattern=r"\S")]
_ERROR_CODES = frozenset({
    "INVALID_REQUEST", "SOURCE_NOT_FOUND", "PARSE_ARTIFACT_NOT_CAPTURED",
    "PARSE_ARTIFACT_INTEGRITY", "SOURCE_UNAVAILABLE", "RELEASE_ACCESS_DENIED",
    "SERVICE_UNAVAILABLE", "INTERNAL_ERROR",
})


class SourcePagesError(ValueError):
    """A caller-safe code, without response content or transport diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code if code in _ERROR_CODES else "SOURCE_UNAVAILABLE"
        super().__init__(self.code)


class _BlockLocator(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    kind: Literal["PPTX_SHAPE", "DOCX_BLOCK", "XLSX_CELL_RANGE"]
    slide: int | None = Field(default=None, ge=1)
    block_index: int | None = Field(default=None, ge=0)
    sheet: str | None = None
    cell_range: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _own_fields_only(cls, data: object) -> object:
        """Exactly the kind's keys, none of them null: an explicit null or another kind's key is
        refused here, before conversion could drop it as if it were omitted (review R2)."""
        if isinstance(data, dict):
            kind = data.get("kind")
            fields = OFFICE_LOCATOR_FIELDS.get(LocatorKind(kind)) if isinstance(kind, str) else None
            if (
                fields is None
                or set(data) != {"kind", *fields}
                or any(value is None for value in data.values())
            ):
                raise ValueError("a locator with fields outside its kind")
        return data


class _Block(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    block_id: _NonBlank
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    locator: _BlockLocator


class _Page(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    page_number: int = Field(ge=1)
    text: str
    page_text_sha256: _Digest
    blocks: list[_Block] = Field(default_factory=list)  # Office pages only; omitted when empty


class _PageSet(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    knowledge_id: str
    parse_attempt: int = Field(ge=1)
    document: _NonBlank
    document_sha256: _Digest
    parser_identity_sha256: _Digest
    native_sha256: _Digest
    pages: list[_Page] = Field(min_length=1)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite JSON number")


def _json(response: httpx.Response) -> object:
    return json.loads(
        response.content.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )


class WeKnoraSourcePages:
    """One read per request, with a single explicit conversion to compiler pages."""

    def __init__(
        self, base_url: str, api_key: str, transport: httpx.BaseTransport | None = None,
    ) -> None:
        try:
            url = httpx.URL(base_url)
        except httpx.InvalidURL:
            raise SourcePagesError("INVALID_REQUEST") from None
        if (url.scheme not in {"http", "https"} or not url.host or url.userinfo
                or url.query or url.fragment or not api_key.strip()):
            raise SourcePagesError("INVALID_REQUEST")
        self._base_url = str(url).rstrip("/")
        self._api_key = api_key
        self._transport = transport

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        if (any(not isinstance(part, str) or not _IDENTIFIER.fullmatch(part)
                for part in (space_id, knowledge_id))
                or type(attempt) is not int or not 0 < attempt < 2**63):
            raise SourcePagesError("INVALID_REQUEST")
        url = (
            f"{self._base_url}/api/v1/enterprise/spaces/{space_id}"
            f"/sources/{knowledge_id}/attempts/{attempt}/pages"
        )
        try:
            with httpx.Client(
                transport=self._transport, timeout=30.0, follow_redirects=False, trust_env=False,
            ) as client:
                response = client.get(url, headers={"X-API-Key": self._api_key})
        except httpx.HTTPError:
            raise SourcePagesError("SOURCE_UNAVAILABLE") from None
        if response.status_code != 200:
            code = "SOURCE_UNAVAILABLE"
            try:
                body = _json(response)
                if isinstance(body, dict) and isinstance(body.get("code"), str):
                    code = body["code"]
            except (ValueError, UnicodeError, RecursionError):
                pass
            raise SourcePagesError(code)
        try:
            result = _PageSet.model_validate(_json(response))
            if result.knowledge_id != knowledge_id or result.parse_attempt != attempt:
                raise ValueError("source revision mismatch")
            for number, page in enumerate(result.pages, 1):
                if (page.page_number != number
                        or hashlib.sha256(page.text.encode("utf-8")).hexdigest()
                        != page.page_text_sha256):
                    raise ValueError("page integrity mismatch")
            if not any("blocks" in page.model_fields_set for page in result.pages):
                return [
                    PageText(result.document, result.document_sha256, page.page_number, page.text)
                    for page in result.pages
                ]
            return _office_pages(result)
        except (ValueError, UnicodeError, ValidationError, RecursionError):
            raise SourcePagesError("PARSE_ARTIFACT_INTEGRITY") from None


def _office_pages(result: _PageSet) -> list[PageText]:
    """Every page of a document with blocks, each checked against its text (ValueError)."""
    office: list[OfficePageText] = []
    for page in result.pages:
        if len({block.block_id for block in page.blocks}) != len(page.blocks):
            raise ValueError("duplicate block id")
        blocks = tuple(
            OfficeBlock(
                start=block.start,
                end=block.end,
                locator=Locator(**block.locator.model_dump(exclude_unset=True)),
            )
            for block in page.blocks
        )
        office.append(
            OfficePageText(
                result.document, result.document_sha256, page.page_number, page.text, blocks
            )
        )
    check_office_document(office)
    return list(office)
