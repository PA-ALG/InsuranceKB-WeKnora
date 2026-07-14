"""OpenSpec 016 S4: WeKnora read boundaries and scope audit data."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest
import respx
from pydantic import ValidationError

from insurance_harness.adapters.weknora import WeKnoraClient
from insurance_harness.adapters.weknora.models import WeKnoraChunk, WeKnoraKnowledge
from insurance_harness.db.scope import KnowledgeScope, ScopeViolation
from tests.conftest import BASE_URL

KID = "knowledge-016"
KNOWLEDGE_URL = f"{BASE_URL}/api/v1/knowledge/{KID}"
CHUNKS_URL = f"{BASE_URL}/api/v1/chunks/{KID}"


def _scope(
    bound_scope: Callable[..., KnowledgeScope],
    *,
    tenant_id: str = "tenant-016",
    raw_kb_id: str = "raw-016",
) -> KnowledgeScope:
    return bound_scope(
        tenant_id=tenant_id,
        raw_kb_id=raw_kb_id,
        wiki_kb_id="wiki-016",
    )


def _knowledge(*, tenant_id: object = "tenant-016", kb_id: object = "raw-016") -> dict[str, Any]:
    return {
        "id": KID,
        "tenant_id": tenant_id,
        "knowledge_base_id": kb_id,
        "parse_status": "completed",
    }


@respx.mock
@pytest.mark.parametrize(
    ("tenant_id", "kb_id"),
    [
        ("tenant-other", "raw-016"),
        ("tenant-016", "raw-other"),
        ("tenant-016", "wiki-016"),
        (None, "raw-016"),
        ("tenant-016", None),
    ],
)
async def test_s4_2_get_knowledge_fails_closed_on_response_scope_mismatch(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
    tenant_id: object,
    kb_id: object,
) -> None:
    scope = _scope(bound_scope)
    route = respx.get(KNOWLEDGE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": _knowledge(tenant_id=tenant_id, kb_id=kb_id)},
        )
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await client.get_knowledge(scope, KID)

    assert route.call_count == 1


@respx.mock
async def test_s4_2_numeric_response_tenant_matches_string_scope(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = _scope(bound_scope, tenant_id="101")
    respx.get(KNOWLEDGE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": _knowledge(tenant_id=101)},
        )
    )

    knowledge = await client.get_knowledge(scope, KID)

    assert knowledge.id == KID


@respx.mock
async def test_rh4_2_metadata_numeric_knowledge_base_id_fails_closed(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = _scope(bound_scope, tenant_id="5", raw_kb_id="5")
    route = respx.get(KNOWLEDGE_URL).mock(
        return_value=httpx.Response(
            200,
            json={"data": _knowledge(tenant_id=5, kb_id=5)},
        )
    )

    with pytest.raises(ScopeViolation) as error:
        await client.get_knowledge(scope, KID)

    assert str(error.value) == "scope mismatch"
    assert repr(error.value) == "ScopeViolation('scope mismatch')"
    assert route.call_count == 1


@respx.mock
async def test_s4_2_get_knowledge_rejects_wrong_response_id(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = _scope(bound_scope)
    response = _knowledge()
    response["id"] = "knowledge-other"
    route = respx.get(KNOWLEDGE_URL).mock(
        return_value=httpx.Response(200, json={"data": response})
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await client.get_knowledge(scope, KID)

    assert route.call_count == 1


@respx.mock
async def test_s4_2_wait_for_parsed_stops_after_first_scope_mismatch(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = _scope(bound_scope)
    route = respx.get(KNOWLEDGE_URL).mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": {
                        **_knowledge(tenant_id="tenant-other"),
                        "parse_status": "processing",
                    }
                },
            ),
            httpx.Response(200, json={"data": _knowledge()}),
        ]
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await client.wait_for_parsed(scope, KID)

    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize("field", ["space_id", "tenant_id", "raw_kb_id", "wiki_kb_id"])
async def test_s4_1_incomplete_scope_is_rejected_before_http_request(
    client: WeKnoraClient,
    field: str,
) -> None:
    values = {
        "space_id": "space-016",
        "tenant_id": "tenant-016",
        "raw_kb_id": "raw-016",
        "wiki_kb_id": "wiki-016",
    }
    values[field] = ""
    forged = KnowledgeScope.model_construct(
        space_id=values["space_id"],
        tenant_id=values["tenant_id"],
        raw_kb_id=values["raw_kb_id"],
        wiki_kb_id=values["wiki_kb_id"],
    )
    route = respx.get(KNOWLEDGE_URL).mock(
        return_value=httpx.Response(200, json={"data": _knowledge()})
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await client.get_knowledge(forged, KID)

    assert route.call_count == 0


@respx.mock
@pytest.mark.parametrize("constructor", ["validate", "construct"])
async def test_s4_1_complete_forged_scope_is_rejected_before_http_request(
    client: WeKnoraClient,
    constructor: str,
) -> None:
    values = {
        "space_id": "missing-space",
        "tenant_id": "tenant-016",
        "raw_kb_id": "raw-016",
        "wiki_kb_id": "wiki-016",
    }
    if constructor == "validate":
        forged = KnowledgeScope(**values)
    else:
        forged = KnowledgeScope.model_construct(
            space_id=values["space_id"],
            tenant_id=values["tenant_id"],
            raw_kb_id=values["raw_kb_id"],
            wiki_kb_id=values["wiki_kb_id"],
        )
    route = respx.get(KNOWLEDGE_URL).mock(
        return_value=httpx.Response(200, json={"data": _knowledge()})
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await client.get_knowledge(forged, KID)

    assert route.call_count == 0


@respx.mock
async def test_s4_1_modified_model_copy_loses_scope_attestation_before_http(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = _scope(bound_scope)
    forged = scope.model_copy(update={"raw_kb_id": "raw-forged"})
    route = respx.get(KNOWLEDGE_URL).mock(
        return_value=httpx.Response(200, json={"data": _knowledge(kb_id="raw-forged")})
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await client.get_knowledge(forged, KID)

    assert route.call_count == 0


@respx.mock
@pytest.mark.parametrize(
    "chunk",
    [
        {
            "id": "chunk-1",
            "tenant_id": "tenant-other",
            "knowledge_id": KID,
            "knowledge_base_id": "raw-016",
        },
        {
            "id": "chunk-1",
            "tenant_id": "tenant-016",
            "knowledge_id": "knowledge-other",
            "knowledge_base_id": "raw-016",
        },
        {
            "id": "chunk-1",
            "tenant_id": "tenant-016",
            "knowledge_id": KID,
            "knowledge_base_id": "raw-other",
        },
        {"id": "chunk-1", "knowledge_id": KID, "knowledge_base_id": "raw-016"},
        {"id": "chunk-1", "tenant_id": "tenant-016", "knowledge_id": KID},
    ],
)
async def test_s4_2_list_chunks_fails_closed_on_cross_scope_or_missing_fields(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
    chunk: dict[str, object],
) -> None:
    scope = _scope(bound_scope)
    route = respx.get(CHUNKS_URL).mock(
        return_value=httpx.Response(200, json={"data": [chunk]})
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await client.list_chunks(scope, KID)

    assert route.call_count == 1


@respx.mock
async def test_rh4_2_chunk_numeric_knowledge_base_id_fails_closed(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = _scope(bound_scope, tenant_id="5", raw_kb_id="5")
    route = respx.get(CHUNKS_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "chunk-1",
                        "tenant_id": 5,
                        "knowledge_id": KID,
                        "knowledge_base_id": 5,
                    }
                ]
            },
        )
    )

    with pytest.raises(ScopeViolation) as error:
        await client.list_chunks(scope, KID)

    assert str(error.value) == "scope mismatch"
    assert repr(error.value) == "ScopeViolation('scope mismatch')"
    assert route.call_count == 1


@pytest.mark.parametrize(
    ("model", "field"),
    [
        (WeKnoraKnowledge, "tenant_id"),
        (WeKnoraKnowledge, "knowledge_base_id"),
        (WeKnoraChunk, "tenant_id"),
        (WeKnoraChunk, "knowledge_id"),
        (WeKnoraChunk, "knowledge_base_id"),
    ],
)
@pytest.mark.parametrize("invalid", [True, 1.0])
def test_s4_2_identity_models_reject_bool_and_float(
    model: type[WeKnoraKnowledge] | type[WeKnoraChunk],
    field: str,
    invalid: object,
) -> None:
    payload: dict[str, object] = {
        "id": KID,
        "tenant_id": "tenant-016",
        "knowledge_id": KID,
        "knowledge_base_id": "raw-016",
    }
    payload[field] = invalid

    with pytest.raises(ValidationError):
        model.model_validate(payload)


@respx.mock
async def test_s4_2_malformed_identity_error_does_not_leak_payload(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = _scope(bound_scope)
    response = _knowledge()
    response["tenant_id"] = {"api_key": "leak-me"}
    respx.get(KNOWLEDGE_URL).mock(
        return_value=httpx.Response(200, json={"data": response})
    )

    with pytest.raises(ScopeViolation) as error:
        await client.get_knowledge(scope, KID)

    assert str(error.value) == "scope mismatch"
    assert repr(error.value) == "ScopeViolation('scope mismatch')"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert "leak-me" not in str(error.value)
    assert "leak-me" not in repr(error.value)


@respx.mock
@pytest.mark.parametrize("page_size", [True, 0, -1, "1"])
async def test_s4_1_list_chunks_rejects_invalid_page_size_before_http(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
    page_size: object,
) -> None:
    scope = _scope(bound_scope)
    route = respx.get(CHUNKS_URL).mock(
        side_effect=[
            httpx.Response(200, json={"data": []}),
            RuntimeError("invalid page size reached a second request"),
        ]
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        await client.list_chunks(scope, KID, page_size=page_size)  # type: ignore[arg-type]

    assert route.call_count == 0


@respx.mock
@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"data": {"items": []}},
        {"items": []},
        "not-a-list",
        ["not-an-object"],
        [{"id": "chunk-1", "tenant_id": {"api_key": "leak-me"}}],
    ],
)
async def test_s4_2_list_chunks_rejects_unknown_or_malformed_payload(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
    payload: object,
) -> None:
    scope = _scope(bound_scope)
    respx.get(CHUNKS_URL).mock(
        return_value=httpx.Response(200, json={"data": payload})
    )

    with pytest.raises(ScopeViolation) as error:
        await client.list_chunks(scope, KID)

    assert str(error.value) == "scope mismatch"
    assert repr(error.value) == "ScopeViolation('scope mismatch')"
    assert error.value.__cause__ is None
    assert error.value.__context__ is None
    assert "leak-me" not in str(error.value)
    assert "leak-me" not in repr(error.value)


@respx.mock
async def test_s4_2_list_chunks_accepts_explicit_nested_data_list(
    client: WeKnoraClient,
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    scope = _scope(bound_scope)
    chunk = {
        "id": "chunk-1",
        "tenant_id": "tenant-016",
        "knowledge_id": KID,
        "knowledge_base_id": "raw-016",
    }
    respx.get(CHUNKS_URL).mock(
        return_value=httpx.Response(200, json={"data": {"data": [chunk]}})
    )

    chunks = await client.list_chunks(scope, KID)

    assert [item.id for item in chunks] == ["chunk-1"]


def test_s4_3_scope_log_context_has_ids_only(
    bound_scope: Callable[..., KnowledgeScope],
) -> None:
    from insurance_harness.adapters.weknora.scope import scope_log_context

    scope = _scope(bound_scope)
    context = scope_log_context(scope)

    assert context == {
        "space_id": scope.space_id,
        "tenant_id": "tenant-016",
        "raw_kb_id": "raw-016",
    }
    serialized = repr(context).lower()
    assert "api_key" not in serialized
    assert "token" not in serialized
    assert "secret" not in serialized
    assert "wiki-016" not in serialized


def test_s4_3_scope_log_context_rejects_forged_scope() -> None:
    from insurance_harness.adapters.weknora.scope import scope_log_context

    forged = KnowledgeScope.model_construct(
        space_id="space-016",
        tenant_id="",
        raw_kb_id="raw-016",
        wiki_kb_id="wiki-016",
        api_key="must-never-serialize",
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        scope_log_context(forged)


def test_s4_1_scope_guard_hides_missing_model_construct_fields() -> None:
    from insurance_harness.adapters.weknora.scope import scope_log_context

    forged = KnowledgeScope.model_construct(
        space_id="space-016",
        tenant_id="tenant-016",
        raw_kb_id="raw-016",
    )

    with pytest.raises(ScopeViolation, match="^scope mismatch$"):
        scope_log_context(forged)
