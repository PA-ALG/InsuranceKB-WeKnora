"""WeKnora source transport: chunk offsets, safe identities and SourceRevision metadata."""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import ValidationError

from insurance_harness.adapters.weknora import (
    WeKnoraChunk,
    WeKnoraClient,
    WeKnoraKnowledge,
)
from insurance_harness.config import HarnessSettings
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from tests.conftest import BASE_URL
from tests.ingest.weknora_source.helpers import (
    BODY,
    KID,
    MD5,
    META_URL,
    _chunk,
    _knowledge,
    _metadata,
    _source_client,
)


@pytest.mark.parametrize("field", ["chunk_index", "start_at", "end_at"])
@pytest.mark.parametrize("invalid", [True, "1", 1.0, -1])
def test_chunk_offsets_require_non_negative_strict_integers(
    field: str,
    invalid: object,
) -> None:
    with pytest.raises(ValidationError):
        WeKnoraChunk.model_validate(_chunk(0, **{field: invalid}))


def test_chunk_offsets_allow_none_but_reject_reversed_range() -> None:
    compatible = WeKnoraChunk.model_validate(
        _chunk(0, chunk_index=None, start_at=None, end_at=None)
    )
    assert compatible.chunk_index is None
    assert compatible.start_at is None
    assert compatible.end_at is None

    with pytest.raises(ValidationError, match="start_at"):
        WeKnoraChunk.model_validate(_chunk(0, start_at=20, end_at=19))


@pytest.mark.parametrize(
    "knowledge_id",
    ["../wiki", "x?admin=true", "x/y", "x#frag", "x" * 129],
)
@pytest.mark.parametrize("operation", ["metadata", "download", "chunks"])
@respx.mock
async def test_unsafe_knowledge_id_fails_before_any_http_request(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
    knowledge_id: str,
    operation: str,
) -> None:
    with pytest.raises(ScopeViolation, match="scope mismatch"):
        if operation == "metadata":
            await client.get_knowledge(adapter_scope, knowledge_id)
        elif operation == "download":
            async with client.download_knowledge(
                adapter_scope,
                _knowledge(id=knowledge_id),
            ):
                pytest.fail("unsafe download identity must not yield")
        else:
            await client.list_chunks(adapter_scope, knowledge_id)

    assert len(respx.calls) == 0


@respx.mock
async def test_numeric_metadata_identity_normalizes_to_safe_download_path(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
) -> None:
    client = _source_client(settings, tmp_path)
    metadata_url = f"{BASE_URL}/api/v1/knowledge/123"
    download_url = f"{metadata_url}/download"
    respx.get(metadata_url).mock(
        return_value=httpx.Response(
            200,
            json={"data": _metadata(id=123)},
        )
    )
    download_route = respx.get(download_url).mock(
        return_value=httpx.Response(200, content=BODY)
    )
    try:
        knowledge = await client.get_knowledge(adapter_scope, "123")
        assert knowledge.id == 123

        async with client.download_knowledge(adapter_scope, knowledge) as downloaded:
            assert downloaded.path.read_bytes() == BODY

        assert download_route.call_count == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize("unsafe_id", [True, -1])
@respx.mock
async def test_non_path_safe_numeric_metadata_identity_fails_before_download_http(
    settings: HarnessSettings,
    adapter_scope: KnowledgeScope,
    tmp_path: Path,
    unsafe_id: object,
) -> None:
    client = _source_client(settings, tmp_path)
    values = _knowledge().model_dump()
    values["id"] = unsafe_id
    knowledge = WeKnoraKnowledge.model_construct(**values)
    try:
        with pytest.raises(ScopeViolation, match="scope mismatch"):
            async with client.download_knowledge(adapter_scope, knowledge):
                pytest.fail("unsafe numeric identity must not yield")

        assert len(respx.calls) == 0
    finally:
        await client.aclose()


@respx.mock
async def test_b1_1_metadata_consumes_source_revision_fields(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
) -> None:
    respx.get(META_URL).mock(
        return_value=httpx.Response(200, json={"success": True, "data": _metadata()})
    )

    knowledge = await client.get_knowledge(adapter_scope, KID)

    assert knowledge.file_name == "terms.pdf"
    assert knowledge.file_type == "pdf"
    assert knowledge.file_size == len(BODY)
    assert knowledge.file_hash == MD5
    assert knowledge.processed_at == datetime(2026, 7, 13, 8, 30, tzinfo=UTC)
    assert knowledge.updated_at == datetime(2026, 7, 13, 8, 31, tzinfo=UTC)


@pytest.mark.parametrize("field", ["processed_at", "updated_at"])
@respx.mock
async def test_b1_1_naive_source_timestamp_fails_closed(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
    field: str,
) -> None:
    respx.get(META_URL).mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": _metadata(**{field: "2026-07-13T08:30:00"})},
        )
    )

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        await client.get_knowledge(adapter_scope, KID)


@pytest.mark.parametrize(
    "overrides",
    [
        {"file_size": -1},
        {"file_size": True},
        {"file_size": "25"},
        {"file_hash": "not-an-md5"},
    ],
)
@respx.mock
async def test_b1_1_malformed_file_identity_fails_closed(
    client: WeKnoraClient,
    adapter_scope: KnowledgeScope,
    overrides: dict[str, object],
) -> None:
    respx.get(META_URL).mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": _metadata(**overrides)},
        )
    )

    with pytest.raises(ScopeViolation, match="scope mismatch"):
        await client.get_knowledge(adapter_scope, KID)
