import asyncio
import hashlib
import importlib
import json
import typing
from datetime import UTC, datetime

import httpx
import pytest

from insurance_harness.jobs import NonRetryableJobError, RetryableJobError
from insurance_harness.product_ingestion.models import ProductScope


def test_large_candidate_transfer_uses_existing_scoped_preparation_endpoint() -> None:
    from tests.product_ingestion.test_candidate_transfer import example, wire

    candidate, base = example()
    candidate["raw_response"] = "原始响应" * 800_000
    seen = []

    def respond(request: typing.Any) -> typing.Any:
        seen.append(request)
        return httpx.Response(
            201,
            json={
                "success": True,
                "data": {
                    "tenant_id": 1,
                    "space_id": "space",
                    "raw_kb_id": "raw",
                    "wiki_kb_id": "wiki",
                    "preparation_id": "prep",
                    "status": "draft",
                },
            },
        )

    api, scope = client(respond)
    asyncio.run(api.create_preparation(scope, "prep", wire(candidate), base_body=base))
    assert len(seen) == 1
    assert set(json.loads(seen[0].content)) == {"preparation_id", "transfer"}
    assert len(seen[0].content) < 8 << 20


def module() -> typing.Any:
    try:
        return importlib.import_module("insurance_harness.product_ingestion.platform_client")
    except ModuleNotFoundError:
        pytest.fail("scoped platform REST client is not implemented")


def client(transport: typing.Any, max_bytes: typing.Any = 4096) -> tuple[typing.Any, ...]:
    scope = ProductScope(
        tenant_id="1", space_id="space", raw_knowledge_base_id="raw", wiki_knowledge_base_id="wiki"
    )
    return module().PlatformClient(
        base_url="http://fixture",
        credential="fixture-secret",
        scope=scope,
        timeout_seconds=3,
        max_response_bytes=max_bytes,
        transport=httpx.MockTransport(transport),
    ), scope


def test_upload_lookup_uses_fixed_scope_key_and_validates_binding() -> None:
    seen = []

    def respond(request: typing.Any) -> typing.Any:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "contract": "g3-platform-upload-snapshot.830.v1",
                    "run_id": "run",
                    "ordinal": 0,
                    "knowledge_id": "knowledge",
                    "file_name": "保险条款.pdf",
                    "parse_attempt": 1,
                    "parse_status": "completed",
                },
            },
        )

    api, scope = client(respond)
    result = asyncio.run(api.lookup_upload(scope, "run", 0))
    assert result["knowledge_id"] == "knowledge"
    assert (
        str(seen[0].url)
        == "http://fixture/api/v1/knowledgebase/wiki/wiki/release-scopes/space/raw/raw/platform/uploads/run/0"
    )
    assert seen[0].headers["X-API-Key"] == "fixture-secret"
    with pytest.raises(ValueError):
        asyncio.run(api.lookup_upload(scope.model_copy(update={"space_id": "other"}), "run", 0))
    assert len(seen) == 1


def test_bound_reparse_get_then_post_uses_one_stable_key_and_expected_attempt() -> None:
    seen = []
    key = "a" * 64
    deadline = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)

    def respond(request: typing.Any) -> typing.Any:
        seen.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={"success": False})
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "contract": "g3-platform-bound-reparse.830.v1",
                    "run_id": "run",
                    "ordinal": 2,
                    "knowledge_id": "knowledge",
                    "expected_parse_attempt": 1,
                    "parse_attempt": 2,
                    "recovery_key": key,
                    "deadline_at": "2026-09-16T12:00:00Z",
                    "dispatch_state": "enqueued",
                    "queue_task_id": "task",
                    "parse_status": "processing",
                },
            },
        )

    api, scope = client(respond)
    assert asyncio.run(api.get_reparse_receipt(scope, "run", 2, key)) is None
    result = asyncio.run(api.reparse_upload(scope, "run", 2, 1, key, deadline))
    assert result["parse_attempt"] == 2
    assert seen[0].url.path == seen[1].url.path
    assert str(seen[0].url).endswith("/platform/uploads/run/2/reparse?recovery_key=" + key)
    assert json.loads(seen[1].content) == {
        "expected_parse_attempt": 1,
        "recovery_key": key,
        "deadline_at": "2026-09-16T12:00:00Z",
    }


@pytest.mark.parametrize("status", [302, 503, 403])
def test_no_redirect_or_automatic_retry_and_sanitized_errors(status: typing.Any) -> None:
    seen = []

    def respond(request: typing.Any) -> typing.Any:
        seen.append(request)
        return httpx.Response(
            status, text="fixture-secret private source", headers={"location": "http://other"}
        )

    api, scope = client(respond)
    with pytest.raises((NonRetryableJobError, RetryableJobError)) as caught:
        asyncio.run(api.capture_source(scope, "knowledge", 1))
    assert "fixture-secret" not in str(caught.value)
    assert "private source" not in str(caught.value)
    assert len(seen) == 1


def test_missing_upload_is_pending_but_oversized_or_duplicate_response_is_rejected() -> None:
    api, scope = client(lambda _: httpx.Response(404, json={"success": False}))
    assert asyncio.run(api.lookup_upload(scope, "run", 0)) is None
    for response in (b'{"success":true,"success":false,"data":{}}', b"x" * 5000):
        api, scope = client(lambda _, response=response: httpx.Response(200, content=response))
        with pytest.raises(NonRetryableJobError):
            asyncio.run(api.lookup_upload(scope, "run", 0))


def test_mismatched_upload_binding_is_not_accepted() -> None:
    api, scope = client(
        lambda _: httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "contract": "g3-platform-upload-snapshot.830.v1",
                    "run_id": "other",
                    "ordinal": 0,
                },
            },
        )
    )
    with pytest.raises(ValueError):
        asyncio.run(api.lookup_upload(scope, "run", 0))


def test_release_methods_preserve_signed_bytes_and_bound_preparation_scope() -> None:
    seen = []

    def respond(request: typing.Any) -> typing.Any:
        seen.append(request)
        if request.url.path.endswith("/activate"):
            auth = json.loads(request.content)["authorization"]
            raw = json.dumps(auth, separators=(",", ":")).encode()
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "tenant_id": 1,
                        "space_id": "space",
                        "raw_kb_id": "raw",
                        "wiki_kb_id": "wiki",
                        "nonce": "nonce",
                        "authorization_digest": hashlib.sha256(raw).hexdigest(),
                        "previous_release_id": "parent",
                        "release_id": "new",
                        "activation_epoch": 10,
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "tenant_id": 1,
                    "space_id": "space",
                    "raw_kb_id": "raw",
                    "wiki_kb_id": "wiki",
                    "preparation_id": "prep",
                    "status": "draft",
                },
            },
        )

    api, scope = client(respond)
    assert hasattr(api, "create_preparation"), "platform release REST methods are missing"
    candidate = b'{"fixture":"candidate"}'
    asyncio.run(api.create_preparation(scope, "prep", candidate))
    assert seen[-1].content == b'{"bundle":' + candidate + b',"preparation_id":"prep"}'
    decision = b'{"fixture":"system-decision","signature":"abc"}'
    asyncio.run(api.review_preparation(scope, "prep", decision))
    assert seen[-1].content == decision
    authorization = (
        b'{"expected_activation_epoch":9,"expected_release_id":"parent",'
        b'"nonce":"nonce","signature":"def"}'
    )
    asyncio.run(api.activate(scope, decision, authorization))
    assert (
        seen[-1].content == b'{"authorization":' + authorization + b',"decision":' + decision + b"}"
    )
    assert len(seen) == 3


def test_release_preparation_response_scope_mismatch_is_refused() -> None:
    api, scope = client(
        lambda _: httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "tenant_id": 1,
                    "space_id": "other",
                    "raw_kb_id": "raw",
                    "wiki_kb_id": "wiki",
                    "preparation_id": "prep",
                    "status": "draft",
                },
            },
        )
    )
    assert hasattr(api, "create_preparation"), "platform release REST methods are missing"
    with pytest.raises(ValueError, match="scope"):
        asyncio.run(api.create_preparation(scope, "prep", json.dumps({"fixture": True}).encode()))


def test_list_read_requires_explicit_expected_type() -> None:
    api, scope = client(lambda _: httpx.Response(200, json={"success": True, "data": []}))
    assert "expected_data_type" in __import__("inspect").signature(api._request).parameters
    assert (
        asyncio.run(
            api._request(scope, "GET", "/releases/new/search?q=name", expected_data_type=list)
        )
        == []
    )
    with pytest.raises(NonRetryableJobError):
        asyncio.run(api._request(scope, "GET", "/current"))


def test_activation_receipt_is_explicitly_bound() -> None:
    api, scope = client(
        lambda _: httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "tenant_id": 1,
                    "space_id": "other",
                    "raw_kb_id": "raw",
                    "wiki_kb_id": "wiki",
                    "nonce": "nonce",
                    "authorization_digest": "0" * 64,
                    "previous_release_id": "parent",
                    "release_id": "new",
                    "activation_epoch": 10,
                },
            },
        )
    )
    auth = b'{"expected_activation_epoch":9,"expected_release_id":"parent","nonce":"nonce"}'
    with pytest.raises(ValueError, match="activation receipt"):
        asyncio.run(api.activate(scope, b"{}", auth))


def test_transport_failure_records_exception_kind_without_request_secrets(
    caplog: typing.Any,
) -> None:
    import logging

    def timeout(request: typing.Any) -> None:
        raise httpx.ReadTimeout("secret provider details", request=request)

    api, scope = client(timeout)
    with (
        caplog.at_level(logging.WARNING),
        pytest.raises(RetryableJobError, match="PLATFORM_TRANSPORT_UNAVAILABLE"),
    ):
        asyncio.run(api.current(scope))
    records = [r for r in caplog.records if getattr(r, "event", "") == "platform_transport_error"]
    assert records and records[0].error_type == "ReadTimeout"
    assert "secret provider details" not in caplog.text
    assert "fixture-secret" not in caplog.text
