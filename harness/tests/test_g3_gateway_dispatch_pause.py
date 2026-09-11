"""Shared gateway exhaustion pauses only unsent calls, with no provider traffic."""
from __future__ import annotations

import asyncio
import hashlib

import httpx
import pytest

from insurance_harness.knowledge_compiler import g3_bounded_model_execution as runtime
from insurance_harness.run_admission.g3_models import (
    G3CallTerminalReceiptV1,
    G3ProviderResponseMetaV1,
)


def _recorded_failure(status: int) -> G3CallTerminalReceiptV1:
    # Actual 2026-09-11 gateway response: text/plain, not model-output JSON.
    response = httpx.Response(
        status, content=b"Token error: All accounts limited. Wait 8s.",
        headers={"content-type": "text/plain"},
    )
    # The scheduler receives the already persisted terminal; custody validation
    # belongs to the gateway and is covered by its tests.
    return G3CallTerminalReceiptV1.model_construct(
        status="FAILED",
        response_meta=G3ProviderResponseMetaV1(
            http_status=response.status_code,
            content_type=response.headers["content-type"],
            provider_request_id=None,
            canonical_headers_sha256="a" * 64,
        ),
        response_body_sha256=hashlib.sha256(response.content).hexdigest(),
    )


@pytest.mark.parametrize("status", [429, 503])
def test_shared_gateway_failure_retains_inflight_and_leaves_unsent_resumable(status):
    sent = []
    failed = _recorded_failure(status)

    async def scenario():
        both_started = asyncio.Event()

        async def execute(call):
            sent.append(call)
            if call == 0:
                await both_started.wait()
                return failed
            if call == 1:
                both_started.set()
                # The first failure is observed while this request is in flight.
                await asyncio.sleep(0.01)
            return call

        outcomes = await runtime._run_bounded_call_tasks(
            tuple(range(8)), execute, worker_limit=2,
        )
        assert sent == [0, 1]
        assert outcomes[:2] == (failed, 1)
        assert outcomes[2:] == (None,) * 6
        # Explicit later recovery may send only the never-started calls. No
        # retry/timer is created by the scheduler and the successful leaf stays.
        assert await runtime._run_bounded_call_tasks(
            tuple(range(2, 8)), execute, worker_limit=2,
        ) == tuple(range(2, 8))
        assert sent == list(range(8))

    asyncio.run(scenario())


def test_recorded_field_validation_failure_does_not_pause_siblings():
    sent = []
    failed = _recorded_failure(200)

    async def execute(call):
        sent.append(call)
        return failed if call == 0 else call

    outcomes = asyncio.run(runtime._run_bounded_call_tasks(
        tuple(range(4)), execute, worker_limit=2,
    ))
    assert sent == [0, 1, 2, 3]
    assert outcomes == (failed, 1, 2, 3)
