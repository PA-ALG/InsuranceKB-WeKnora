"""OpenSpec 020 D1.2a/D1.2b: code-owned, zero-inference provider probes."""

from __future__ import annotations

import gzip
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
import pytest
from pydantic import ValidationError

from insurance_harness.goldenset.admission_models import ModelRolePlan
from insurance_harness.goldenset.admission_probe import (
    ProbeBlocker,
    ProbeRequest,
    ProbeResult,
    ProviderProbePolicyRegistry,
    SafeProviderProbe,
)

_NOW = datetime(2026, 7, 19, 8, 0, tzinfo=UTC)
_POLICY_ID = "bailian-deployment-detail-v1"
_DEPLOYED_MODEL = "golden-annotator-prod-20260719"
_METADATA_URL = (
    "https://dashscope.aliyuncs.com/api/v1/deployments/" f"{_DEPLOYED_MODEL}"
)
_FAKE_KEY = "fake-test-key-never-log"


def _role(
    *,
    provider: str = "bailian",
    model_id: str = _DEPLOYED_MODEL,
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    protocol: str = "https",
    policy: str = _POLICY_ID,
    revision: str | None = "2026-07-19T07:59:00Z",
    deployment: str | None = None,
    credential_env_name: str = "HARNESS_DASHSCOPE_API_KEY",
) -> ModelRolePlan:
    return ModelRolePlan(
        provider=provider,
        model_id=model_id,
        expected_model_revision=revision,
        immutable_deployment_id=deployment,
        protocol=protocol,
        base_url=base_url,
        provider_policy=policy,
        credential_env_name=credential_env_name,
    )


def _request(
    role_plan: ModelRolePlan | None = None,
    *,
    mode: Literal["static", "remote"] = "remote",
    probe_observed_at: datetime | None = None,
    price_observed_at: datetime | None = _NOW,
) -> ProbeRequest:
    return ProbeRequest(
        role="annotator",
        role_plan=role_plan or _role(),
        mode=mode,
        probe_observed_at=probe_observed_at,
        price_observed_at=price_observed_at,
    )


class _ClientFactory:
    def __init__(self, transport: httpx.BaseTransport) -> None:
        self.transport = transport
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> httpx.Client:
        self.calls.append(dict(kwargs))
        return httpx.Client(transport=self.transport, **kwargs)


class _ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks: tuple[bytes, ...]) -> None:
        self._chunks = chunks

    def __iter__(self):  # type: ignore[no-untyped-def]
        yield from self._chunks


class _ForbiddenBodyStream(httpx.SyncByteStream):
    def __iter__(self):  # type: ignore[no-untyped-def]
        raise AssertionError("compressed response body must not be decoded or iterated")
        yield b""  # pragma: no cover


def _probe(
    transport: httpx.BaseTransport,
    *,
    registry: ProviderProbePolicyRegistry | None = None,
) -> tuple[SafeProviderProbe, _ClientFactory]:
    factory = _ClientFactory(transport)
    return (
        SafeProviderProbe._for_testing(
            policy_registry=registry or ProviderProbePolicyRegistry.code_owned(),
            client_factory=factory,
            clock=lambda: _NOW,
            monotonic=lambda: 10.0,
        ),
        factory,
    )


def _codes(result: object) -> set[str]:
    return {blocker.code for blocker in result.blockers}  # type: ignore[attr-defined]


def test_d1_2a_static_mode_performs_zero_network_and_cannot_ready() -> None:
    def forbidden_factory(**_kwargs: Any) -> httpx.Client:
        raise AssertionError("D1.2a static admission must perform zero network")

    probe = SafeProviderProbe._for_testing(
        policy_registry=ProviderProbePolicyRegistry.code_owned(),
        client_factory=forbidden_factory,
        clock=lambda: _NOW,
        monotonic=lambda: 10.0,
    )

    result = probe.run(_request(mode="static"))

    assert result.verified is False
    assert "probe_not_performed" in _codes(result)
    assert result.observed_at is None


def test_d1_2a_remote_probe_forces_https_tls_trust_env_false_no_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
    ):
        monkeypatch.setenv(name, "http://ambient-secret.invalid:9876")
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "output": {
                    "deployed_model": _DEPLOYED_MODEL,
                    "base_model": "deepseek-v4-flash",
                    "gmt_modified": "2026-07-19T07:59:00Z",
                    "status": "RUNNING",
                }
            },
        )

    prober, factory = _probe(httpx.MockTransport(handler))

    result = prober.run(_request())

    assert result.verified is True
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == _METADATA_URL
    assert requests[0].content == b""
    assert factory.calls == [
        {
            "verify": True,
            "trust_env": False,
            "follow_redirects": False,
        }
    ]

    loopback_requests: list[httpx.Request] = []
    loopback_registry = ProviderProbePolicyRegistry._for_testing_loopback(
        policy_id="test-loopback-deployment-detail-v1",
        origin="http://127.0.0.1:9876",
        path_template="/metadata/{deployed_model}",
    )

    def loopback_handler(request: httpx.Request) -> httpx.Response:
        loopback_requests.append(request)
        assert "authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "output": {
                    "deployed_model": _DEPLOYED_MODEL,
                    "base_model": "deepseek-v4-flash",
                    "gmt_modified": "2026-07-19T07:59:00Z",
                    "status": "RUNNING",
                }
            },
        )

    loopback_probe, _ = _probe(
        httpx.MockTransport(loopback_handler), registry=loopback_registry
    )
    loopback_result = loopback_probe.run(
        _request(
            _role(
                base_url="http://127.0.0.1:9876",
                protocol="http",
                policy="test-loopback-deployment-detail-v1",
                credential_env_name="TEST_NO_CREDENTIAL",
            )
        )
    )

    assert loopback_result.verified is True
    assert len(loopback_requests) == 1
    assert loopback_requests[0].method == "GET"
    assert str(loopback_requests[0].url) == (
        f"http://127.0.0.1:9876/metadata/{_DEPLOYED_MODEL}"
    )
    assert loopback_requests[0].content == b""


@pytest.mark.parametrize(
    "role_plan",
    (
        _role(
            protocol="http",
            base_url="http://dashscope.aliyuncs.com/compatible-mode/v1",
        ),
        _role(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1?probe=1"
        ),
        _role(
            base_url=(
                "https://user:secret@dashscope.aliyuncs.com/compatible-mode/v1"
            )
        ),
        _role(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1#metadata"
        ),
        _role(base_url="https://dashscope.aliyuncs.com/compatible-mode/%76%31"),
        _role(
            base_url=(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/models/extra"
            )
        ),
    ),
)
def test_d1_2a_rejects_post_query_userinfo_fragment_encoded_path_and_suffix(
    monkeypatch: pytest.MonkeyPatch,
    role_plan: ModelRolePlan,
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    requests: list[httpx.Request] = []

    def forbidden_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": []})

    prober, _ = _probe(httpx.MockTransport(forbidden_handler))

    result = prober.run(_request(role_plan))

    assert result.verified is False
    assert requests == []
    assert _codes(result) & {"unsafe_probe_configuration", "policy_mismatch"}

    with pytest.raises((TypeError, ValueError)):
        ProbeRequest.model_validate(
            {**_request().model_dump(), "method": "POST", "path": "/models"}
        )


def test_d1_2a_does_not_follow_3xx_or_cross_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    redirect_requests: list[httpx.Request] = []

    def redirect_handler(request: httpx.Request) -> httpx.Response:
        redirect_requests.append(request)
        return httpx.Response(
            302,
            headers={
                "location": "https://cross-origin.invalid/v1/chat/completions"
            },
            text="redirect-body-must-not-be-persisted",
        )

    redirect_probe, _ = _probe(httpx.MockTransport(redirect_handler))
    redirect_result = redirect_probe.run(_request())

    assert redirect_result.verified is False
    assert len(redirect_requests) == 1
    assert "redirect_rejected" in _codes(redirect_result)

    cross_origin_requests: list[httpx.Request] = []

    def cross_origin_handler(request: httpx.Request) -> httpx.Response:
        cross_origin_requests.append(request)
        return httpx.Response(200, json={"data": []})

    cross_origin_probe, _ = _probe(httpx.MockTransport(cross_origin_handler))
    cross_origin_result = cross_origin_probe.run(
        _request(
            _role(base_url="https://cross-origin.invalid/compatible-mode/v1")
        )
    )

    assert cross_origin_result.verified is False
    assert cross_origin_requests == []
    assert "policy_mismatch" in _codes(cross_origin_result)


def test_d1_2b_compares_signed_expected_revision_or_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)

    def run_with_metadata(
        role_plan: ModelRolePlan,
        metadata: dict[str, str],
    ) -> ProbeResult:
        prober, _ = _probe(
            httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={
                        "output": {
                            "deployed_model": role_plan.model_id,
                            "base_model": "deepseek-v4-flash",
                            "gmt_modified": "2026-07-19T07:59:00Z",
                            "status": "RUNNING",
                            **metadata,
                        }
                    },
                )
            )
        )
        result = prober.run(_request(role_plan))
        assert isinstance(result, ProbeResult)
        assert all(isinstance(blocker, ProbeBlocker) for blocker in result.blockers)
        return result

    matching_revision = run_with_metadata(_role(), {})
    suffix_revision = run_with_metadata(
        _role(), {"gmt_modified": "2026-07-19T07:58:00Z"}
    )
    matching_deployment = run_with_metadata(
        _role(revision=None, deployment=_DEPLOYED_MODEL),
        {},
    )
    wrong_deployment = run_with_metadata(
        _role(revision=None, deployment="another-deployment"),
        {},
    )
    stopped_deployment = run_with_metadata(_role(), {"status": "STOPPED"})

    assert matching_revision.verified is True
    assert matching_revision.observed_revision == "2026-07-19T07:59:00Z"
    assert matching_deployment.verified is True
    assert matching_deployment.observed_deployment_id == _DEPLOYED_MODEL
    assert suffix_revision.verified is False
    assert wrong_deployment.verified is False
    assert "model_identity_mismatch" in _codes(suffix_revision)
    assert "model_identity_mismatch" in _codes(wrong_deployment)
    assert "deployment_not_running" in _codes(stopped_deployment)


def test_d1_2b_redacts_key_url_secret_response_body_and_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    response_secret = "provider-response-body-secret"
    exception_secret = "transport-exception-secret"
    url_secret = "url-userinfo-secret"
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)

    auth_probe, _ = _probe(
        httpx.MockTransport(
            lambda _request: httpx.Response(401, text=response_secret)
        )
    )
    auth_result = auth_probe.run(_request())

    def raise_secret(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"{exception_secret}:{_FAKE_KEY}")

    exception_probe, _ = _probe(httpx.MockTransport(raise_secret))
    exception_result = exception_probe.run(_request())

    unsafe_url_probe, _ = _probe(
        httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"data": []})
        )
    )
    unsafe_url_result = unsafe_url_probe.run(
        _request(
            _role(
                base_url=(
                    f"https://user:{url_secret}@dashscope.aliyuncs.com/"
                    "compatible-mode/v1"
                )
            )
        )
    )

    rendered = "\n".join(
        (
            auth_result.model_dump_json(),
            exception_result.model_dump_json(),
            unsafe_url_result.model_dump_json(),
            repr(auth_result),
            repr(exception_result),
            repr(unsafe_url_result),
            caplog.text,
        )
    )
    assert auth_result.verified is False
    assert exception_result.verified is False
    assert unsafe_url_result.verified is False
    assert "authentication_failed" in _codes(auth_result)
    assert "probe_unreachable" in _codes(exception_result)
    for secret in (_FAKE_KEY, response_secret, exception_secret, url_secret):
        assert secret not in rendered


def test_d1_2b_rejects_expired_probe_and_price_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    requests: list[httpx.Request] = []

    def stale_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "output": {
                    "deployed_model": _DEPLOYED_MODEL,
                    "base_model": "deepseek-v4-flash",
                    "gmt_modified": "2026-07-19T07:59:00Z",
                    "status": "RUNNING",
                }
            },
        )

    prober, _ = _probe(httpx.MockTransport(stale_handler))

    stale_probe = prober.run(
        _request(probe_observed_at=_NOW - timedelta(minutes=11))
    )
    stale_price = prober.run(
        _request(price_observed_at=_NOW - timedelta(hours=1, seconds=1))
    )
    missing_price = prober.run(_request(price_observed_at=None))

    assert stale_probe.verified is False
    assert stale_price.verified is False
    assert missing_price.verified is False
    assert "probe_observation_expired" in _codes(stale_probe)
    assert "price_observation_expired" in _codes(stale_price)
    assert "price_observation_missing" in _codes(missing_price)
    assert requests == []


def test_d1_2b_clock_and_ttl_are_code_owned_and_future_is_blocked() -> None:
    payload = _request().model_dump(mode="python")
    for injected in (
        {"now": _NOW},
        {"max_probe_age": timedelta(days=3650)},
        {"max_price_observation_age": timedelta(days=3650)},
    ):
        with pytest.raises(ValidationError):
            ProbeRequest.model_validate({**payload, **injected})

    calls = 0

    def forbidden_factory(**_kwargs: Any) -> httpx.Client:
        nonlocal calls
        calls += 1
        raise AssertionError("future observations must block before client creation")

    prober = SafeProviderProbe._for_testing(
        policy_registry=ProviderProbePolicyRegistry.code_owned(),
        client_factory=forbidden_factory,
        clock=lambda: _NOW,
        monotonic=lambda: 10.0,
    )
    result = prober.run(
        _request(
            probe_observed_at=_NOW + timedelta(seconds=1),
            price_observed_at=_NOW + timedelta(seconds=1),
        )
    )
    assert calls == 0
    assert "probe_observation_expired" in _codes(result)
    assert "price_observation_expired" in _codes(result)


@pytest.mark.parametrize(
    "credential_env_name",
    ("HOME", "AWS_SECRET_ACCESS_KEY", "A=B", "BAD\0NAME"),
)
def test_d1_2b_wrong_provider_and_env_exfiltration_block_before_reads(
    credential_env_name: str,
) -> None:
    reads: list[str] = []
    client_calls = 0

    def env_reader(name: str) -> str | None:
        reads.append(name)
        return "must-not-be-read"

    def forbidden_factory(**_kwargs: Any) -> httpx.Client:
        nonlocal client_calls
        client_calls += 1
        raise AssertionError("invalid identity/env must block before client construction")

    prober = SafeProviderProbe._for_testing(
        policy_registry=ProviderProbePolicyRegistry.code_owned(),
        client_factory=forbidden_factory,
        clock=lambda: _NOW,
        monotonic=lambda: 10.0,
        env_reader=env_reader,
    )
    invalid_env = prober.run(
        _request(_role(credential_env_name=credential_env_name))
    )
    wrong_provider = prober.run(_request(_role(provider="not-bailian")))

    assert reads == []
    assert client_calls == 0
    assert "credential_env_not_allowed" in _codes(invalid_env)
    assert "policy_mismatch" in _codes(wrong_provider)


def test_d1_2a_test_policy_is_sealed_from_production_constructor() -> None:
    registry = ProviderProbePolicyRegistry._for_testing_loopback(
        policy_id="test-loopback-deployment-detail-v1",
        origin="http://127.0.0.1:9876",
        path_template="/metadata/{deployed_model}",
    )
    with pytest.raises(TypeError):
        SafeProviderProbe(policy_registry=registry)  # type: ignore[call-arg]

    production_capability = SafeProviderProbe._for_testing(
        policy_registry=registry,
        client_factory=lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(500)
            ),
            **kwargs,
        ),
        clock=lambda: _NOW,
        monotonic=lambda: 10.0,
        allow_test_policy=False,
    )
    result = production_capability.run(
        _request(
            _role(
                base_url="http://127.0.0.1:9876",
                protocol="http",
                policy="test-loopback-deployment-detail-v1",
                credential_env_name="TEST_NO_CREDENTIAL",
            )
        )
    )
    assert "test_policy_not_allowed" in _codes(result)

    for unsafe_path in (
        "/metadata/{deployed_model}?x=1",
        "/metadata/{deployed_model}#fragment",
        "/metadata/%7Bdeployed_model%7D",
        "/v1/chat/completions/{deployed_model}",
        "/ocr/{deployed_model}",
        "/completions/{deployed_model}",
        "/generate/{deployed_model}",
    ):
        with pytest.raises(ValueError):
            ProviderProbePolicyRegistry._for_testing_loopback(
                policy_id="test-loopback-deployment-detail-v1",
                origin="http://127.0.0.1:9876",
                path_template=unsafe_path,
            )


@pytest.mark.parametrize(
    "body",
    (
        b'{"output":{"deployed_model":"a","deployed_model":"b",'
        b'"base_model":"qwen","gmt_modified":"x","status":"RUNNING"}}',
        b'{"output":{"deployed_model":"a","base_model":"qwen",'
        b'"gmt_modified":"x","status":"RUNNING","padding":"'
        + b"x" * (64 * 1024)
        + b'"}}',
    ),
)
def test_d1_2b_duplicate_json_or_decompressed_oversize_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    prober, _ = _probe(
        httpx.MockTransport(lambda _request: httpx.Response(200, content=body))
    )
    result = prober.run(
        _request(_role(credential_env_name="HARNESS_DASHSCOPE_API_KEY"))
    )
    assert result.verified is False
    assert "model_metadata_invalid" in _codes(result)


def test_d1_2b_compressed_metadata_is_rejected_before_body_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    wire_body = gzip.compress(b"x" * (32 * 1024 * 1024))
    assert len(wire_body) < 64 * 1024
    seen_accept_encoding: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_accept_encoding.append(request.headers.get("accept-encoding"))
        return httpx.Response(
            200,
            stream=_ForbiddenBodyStream(),
            headers={
                "Content-Encoding": "gzip",
                "X-Test-Wire-Size": str(len(wire_body)),
            },
        )

    prober, _ = _probe(httpx.MockTransport(handler))

    result = prober.run(
        _request(_role(credential_env_name="HARNESS_DASHSCOPE_API_KEY"))
    )

    assert result.verified is False
    assert "model_metadata_invalid" in _codes(result)
    assert seen_accept_encoding == ["identity"]


def test_d1_2b_deeply_nested_metadata_is_typed_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    body = b"[" * 20_000 + b"0" + b"]" * 20_000
    assert len(body) < 64 * 1024
    prober, _ = _probe(
        httpx.MockTransport(lambda _request: httpx.Response(200, content=body))
    )

    result = prober.run(
        _request(_role(credential_env_name="HARNESS_DASHSCOPE_API_KEY"))
    )

    assert result.verified is False
    assert "model_metadata_invalid" in _codes(result)
    assert result.observed_revision is None
    assert result.observed_deployment_id is None


@pytest.mark.parametrize(
    "metadata",
    (
        {
            "deployed_model": "SYNTHETIC_RESPONSE_SECRET",
            "gmt_modified": "2026-07-19T07:59:00Z",
            "status": "STOPPED",
        },
        {
            "deployed_model": _DEPLOYED_MODEL,
            "gmt_modified": "2026-07-19T07:58:00Z",
            "status": "RUNNING",
        },
    ),
)
def test_d1_2b_blocked_results_never_retain_legal_response_canaries(
    monkeypatch: pytest.MonkeyPatch,
    metadata: dict[str, str],
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    output = {"base_model": "deepseek-v4-flash", **metadata}
    prober, _ = _probe(
        httpx.MockTransport(lambda _request: httpx.Response(200, json={"output": output}))
    )

    result = prober.run(
        _request(_role(credential_env_name="HARNESS_DASHSCOPE_API_KEY"))
    )

    serialized = result.model_dump_json()
    assert result.verified is False
    assert result.observed_revision is None
    assert result.observed_deployment_id is None
    assert "SYNTHETIC_RESPONSE_SECRET" not in serialized
    assert "2026-07-19T07:58:00Z" not in serialized
    assert "SYNTHETIC_RESPONSE_SECRET" not in repr(result)


@pytest.mark.parametrize(
    ("field", "unsafe_value"),
    (
        ("deployed_model", "bad deployment fake-test-secret"),
        ("base_model", "deepseek-v4-flash\nfake-test-secret"),
        ("gmt_modified", "2026-07-19T07:59:00Z\x1b[fake-test-secret"),
        ("status", "RUNNING\nfake-test-secret"),
    ),
)
def test_d1_2b_unsafe_retained_provider_fields_never_enter_audit(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    unsafe_value: str,
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    output = {
        "deployed_model": _DEPLOYED_MODEL,
        "base_model": "deepseek-v4-flash",
        "gmt_modified": "2026-07-19T07:59:00Z",
        "status": "RUNNING",
    }
    output[field] = unsafe_value
    prober, _ = _probe(
        httpx.MockTransport(lambda _request: httpx.Response(200, json={"output": output}))
    )

    result = prober.run(
        _request(_role(credential_env_name="HARNESS_DASHSCOPE_API_KEY"))
    )

    serialized = result.model_dump_json()
    assert result.verified is False
    assert "model_metadata_invalid" in _codes(result)
    assert "fake-test-secret" not in serialized
    assert result.observed_revision is None
    assert result.observed_deployment_id is None


def test_d1_2b_overall_probe_deadline_blocks_slow_drip_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    ticks = iter((100.0, 104.0, 111.0, 112.0))
    factory = _ClientFactory(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                stream=_ChunkStream((b'{"output":', b"{}")),
            )
        )
    )
    prober = SafeProviderProbe._for_testing(
        policy_registry=ProviderProbePolicyRegistry.code_owned(),
        client_factory=factory,
        clock=lambda: _NOW,
        monotonic=lambda: next(ticks),
    )

    result = prober.run(
        _request(_role(credential_env_name="HARNESS_DASHSCOPE_API_KEY"))
    )

    assert result.verified is False
    assert "probe_unreachable" in _codes(result)


def test_d1_2b_public_alias_without_deployment_detail_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    prober, _ = _probe(
        httpx.MockTransport(lambda _request: httpx.Response(404, json={"code": "NotFound"}))
    )

    result = prober.run(
        _request(
            _role(
                model_id="deepseek-v4-flash",
                revision="2026-07-19T07:59:00Z",
                credential_env_name="HARNESS_DASHSCOPE_API_KEY",
            )
        )
    )

    assert result.verified is False
    assert "model_not_found" in _codes(result)
    assert result.observed_revision is None
    assert result.observed_deployment_id is None


def test_d1_2b_official_fixture_produces_safe_audit_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_DASHSCOPE_API_KEY", _FAKE_KEY)
    monotonic_values = iter((50.100, 50.142, 50.142))
    factory = _ClientFactory(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "request_id": "not-retained",
                    "output": {
                        "deployed_model": _DEPLOYED_MODEL,
                        "base_model": "deepseek-v4-flash",
                        "gmt_modified": "2026-07-19T07:59:00Z",
                        "status": "RUNNING",
                    },
                },
            )
        )
    )
    prober = SafeProviderProbe._for_testing(
        policy_registry=ProviderProbePolicyRegistry.code_owned(),
        client_factory=factory,
        clock=lambda: _NOW,
        monotonic=lambda: next(monotonic_values),
    )
    result = prober.run(
        _request(_role(credential_env_name="HARNESS_DASHSCOPE_API_KEY"))
    )

    assert result.verified is True
    assert result.provider == "bailian"
    assert result.model_id == _DEPLOYED_MODEL
    assert result.endpoint_origin == "https://dashscope.aliyuncs.com"
    assert result.status_class == "success"
    assert result.latency_ms == 42
    assert result.observed_at == _NOW
    assert "request_id" not in result.model_dump_json()
