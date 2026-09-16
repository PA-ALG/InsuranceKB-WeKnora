"""Fixed-endpoint, scope-bound REST port; no transport retry or redirect."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from urllib.parse import urlsplit

import httpx

from insurance_harness.jobs import NonRetryableJobError, RetryableJobError
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.platform import _object


def _id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value):
        raise ValueError("invalid platform identifier")
    return value


class PlatformClient:
    def __init__(
        self,
        *,
        base_url: str,
        credential: str,
        scope: ProductScope,
        timeout_seconds: float,
        max_response_bytes: int,
        transport=None,
    ):
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or not credential
            or any(char.isspace() for char in credential)
            or timeout_seconds <= 0
            or max_response_bytes < 1
        ):
            raise ValueError("invalid platform connection configuration")
        self.scope, self.max_response_bytes = scope, max_response_bytes
        self.path = (
            f"/api/v1/knowledgebase/{_id(scope.wiki_knowledge_base_id)}"
            f"/wiki/release-scopes/{_id(scope.space_id)}"
            f"/raw/{_id(scope.raw_knowledge_base_id)}"
        )
        self.client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"X-API-Key": credential, "Accept": "application/json"},
            timeout=timeout_seconds,
            follow_redirects=False,
            transport=transport,
        )

    async def close(self):
        await self.client.aclose()

    async def _request(
        self, scope, method, suffix, *, payload=None, missing_ok=False, expected_data_type=dict
    ):
        if scope != self.scope:
            raise ValueError("platform scope does not match configured binding")
        if expected_data_type not in (dict, list) or (
            expected_data_type is list and method != "GET"
        ):
            raise ValueError("unsupported platform response type")
        started = time.monotonic()
        try:
            async with self.client.stream(
                method,
                self.path + suffix,
                content=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status_code == 404 and missing_ok:
                    return None
                if response.status_code in {408, 429, 502, 503, 504}:
                    raise RetryableJobError(f"PLATFORM_UNAVAILABLE_HTTP_{response.status_code}")
                if not 200 <= response.status_code < 300:
                    raise NonRetryableJobError(f"PLATFORM_REJECTED_HTTP_{response.status_code}")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > self.max_response_bytes:
                        raise NonRetryableJobError("PLATFORM_RESPONSE_LIMIT_EXCEEDED")
                    raw.extend(chunk)
        except httpx.HTTPError as error:
            details = {
                "event": "platform_transport_error", "error_type": type(error).__name__,
                "method": method, "elapsed_seconds": time.monotonic() - started,
                "space_id": scope.space_id,
            }
            logging.getLogger(__name__).warning(json.dumps(details), extra=details)
            raise RetryableJobError("PLATFORM_TRANSPORT_UNAVAILABLE") from None
        try:
            envelope = json.loads(raw, object_pairs_hook=_object)
            if envelope.get("success") is not True or not isinstance(
                envelope.get("data"), expected_data_type
            ):
                raise ValueError()
            return envelope["data"]
        except (ValueError, TypeError, AttributeError):
            raise NonRetryableJobError("PLATFORM_RESPONSE_INVALID") from None

    async def lookup_upload(self, scope, run_id, ordinal):
        if type(ordinal) is not int or ordinal < 0:
            raise ValueError("invalid upload ordinal")
        value = await self._request(
            scope, "GET", f"/platform/uploads/{_id(run_id)}/{ordinal}", missing_ok=True
        )
        if value is None:
            return None
        if (
            value.get("contract") != "g3-platform-upload-snapshot.830.v1"
            or value.get("run_id") != run_id
            or value.get("ordinal") != ordinal
        ):
            raise ValueError("platform upload binding mismatch")
        _id(value.get("knowledge_id"))
        if (
            not isinstance(value.get("file_name"), str)
            or not value["file_name"]
            or type(value.get("parse_attempt")) is not int
            or value["parse_attempt"] < 1
            or not isinstance(value.get("parse_status"), str)
        ):
            raise ValueError("platform parse status invalid")
        return value

    async def capture_source(self, scope, knowledge_id, attempt):
        if type(attempt) is not int or attempt < 1:
            raise ValueError("invalid parse attempt")
        value = await self._request(
            scope, "POST", f"/platform/sources/{_id(knowledge_id)}/attempts/{attempt}/snapshot"
        )
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    async def current(self, scope):
        value = await self._request(scope, "GET", "/current")
        _id(value.get("release_id"))
        if type(value.get("activation_epoch")) is not int or value["activation_epoch"] < 1:
            raise ValueError("platform active identity invalid")
        return value

    async def base_snapshot(self, scope, release_id, epoch):
        if type(epoch) is not int or epoch < 1:
            raise ValueError("invalid base epoch")
        value = await self._request(
            scope, "GET", f"/platform/bases/{_id(release_id)}/epochs/{epoch}"
        )
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    def _preparation_scope(self, scope, preparation_id, value):
        expected = {
            "tenant_id": int(scope.tenant_id),
            "space_id": scope.space_id,
            "raw_kb_id": scope.raw_knowledge_base_id,
            "wiki_kb_id": scope.wiki_knowledge_base_id,
            "preparation_id": preparation_id,
        }
        if any(value.get(name) != expected_value for name, expected_value in expected.items()):
            raise ValueError("platform preparation scope mismatch")
        return value

    async def create_preparation(
        self, scope, preparation_id, candidate_raw: bytes, *, base_body=None
    ):
        _id(preparation_id)
        if base_body is not None:
            from insurance_harness.product_ingestion.candidate_transfer import (
                encode_candidate_transfer,
            )

            encoded = await asyncio.to_thread(encode_candidate_transfer, candidate_raw, base_body)
            body_key = b"transfer"
        else:
            if not isinstance(
                await asyncio.to_thread(json.loads, candidate_raw, object_pairs_hook=_object), dict
            ):
                raise ValueError("candidate must be a JSON object")
            encoded, body_key = candidate_raw, b"bundle"
        payload = (
            b'{"'
            + body_key
            + b'":'
            + encoded
            + b',"preparation_id":'
            + json.dumps(preparation_id).encode()
            + b"}"
        )
        if len(payload) > 8 * 1024 * 1024:
            raise NonRetryableJobError("PLATFORM_CANDIDATE_LIMIT_EXCEEDED")
        value = await self._request(scope, "POST", "/platform/preparations", payload=payload)
        return self._preparation_scope(scope, preparation_id, value)

    async def review_preparation(self, scope, preparation_id, decision_raw: bytes):
        if len(decision_raw) > 1024 * 1024:
            raise NonRetryableJobError("PLATFORM_DECISION_LIMIT_EXCEEDED")
        value = await self._request(
            scope,
            "POST",
            f"/platform/preparations/{_id(preparation_id)}/review",
            payload=decision_raw,
        )
        return self._preparation_scope(scope, preparation_id, value)

    async def activate(self, scope, decision_raw: bytes, authorization_raw: bytes):
        if max(len(decision_raw), len(authorization_raw)) > 1024 * 1024:
            raise NonRetryableJobError("PLATFORM_AUTHORIZATION_LIMIT_EXCEEDED")
        # Preserve both original signatures' bytes across the REST envelope.
        payload = b'{"authorization":' + authorization_raw + b',"decision":' + decision_raw + b"}"
        result = await self._request(scope, "POST", "/platform/activate", payload=payload)
        authorization = json.loads(authorization_raw, object_pairs_hook=_object)
        expected = {
            "tenant_id": int(scope.tenant_id),
            "space_id": scope.space_id,
            "raw_kb_id": scope.raw_knowledge_base_id,
            "wiki_kb_id": scope.wiki_knowledge_base_id,
            "nonce": authorization["nonce"],
            "authorization_digest": hashlib.sha256(authorization_raw).hexdigest(),
            "previous_release_id": authorization["expected_release_id"],
            "activation_epoch": authorization["expected_activation_epoch"] + 1,
        }
        if any(result.get(name) != value for name, value in expected.items()):
            raise ValueError("platform activation receipt binding mismatch")
        _id(result.get("release_id"))
        return result
