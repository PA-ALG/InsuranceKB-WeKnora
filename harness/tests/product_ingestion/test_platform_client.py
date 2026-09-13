import asyncio
import hashlib
import importlib
import json

import httpx
import pytest

from insurance_harness.jobs import NonRetryableJobError, RetryableJobError
from insurance_harness.product_ingestion.models import ProductScope


def module():
    try:
        return importlib.import_module("insurance_harness.product_ingestion.platform_client")
    except ModuleNotFoundError:
        pytest.fail("scoped platform REST client is not implemented")


def client(transport, max_bytes=4096):
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


def test_upload_lookup_uses_fixed_scope_key_and_validates_binding():
    seen = []

    def respond(request):
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


@pytest.mark.parametrize("status", [302, 503, 403])
def test_no_redirect_or_automatic_retry_and_sanitized_errors(status):
    seen = []

    def respond(request):
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


def test_missing_upload_is_pending_but_oversized_or_duplicate_response_is_rejected():
    api, scope = client(lambda _: httpx.Response(404, json={"success": False}))
    assert asyncio.run(api.lookup_upload(scope, "run", 0)) is None
    for response in (b'{"success":true,"success":false,"data":{}}', b"x" * 5000):
        api, scope = client(lambda _, response=response: httpx.Response(200, content=response))
        with pytest.raises(NonRetryableJobError):
            asyncio.run(api.lookup_upload(scope, "run", 0))


def test_mismatched_upload_binding_is_not_accepted():
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


def test_release_methods_preserve_signed_bytes_and_bound_preparation_scope():
    seen = []

    def respond(request):
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


def test_release_preparation_response_scope_mismatch_is_refused():
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


def test_list_read_requires_explicit_expected_type():
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


def test_activation_receipt_is_explicitly_bound():
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
