from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from insurance_harness.knowledge_compiler.g3_bounded_model_execution import (
    _call_terminal,
    g3_current_schema_specs,
    g3_openai_request_bytes,
)
from insurance_harness.model_policy import (
    ModelIdentity,
    ModelPolicyDenied,
    ProductionModelPolicy,
)
from insurance_harness.model_policy.g3_bounded_gateway import (
    G3BoundedRouteConfig,
    G3LedgerDenied,
    _parse_g3_gemini_provider_response,
    validate_g3_route,
)
from insurance_harness.run_admission.g3_models import canonical_g3_hash, canonical_json
from insurance_harness.run_admission.models import (
    canonical_model_identities_hash,
    canonical_model_plan_hash,
)
from insurance_harness.run_admission.profiles.g3_bounded_execution import (
    validate_g3_bounded_plan,
)
from tests.test_g3_bounded_gateway_830 import _complete_successful_stage
from tests.test_run_admission_g3_bounded_830 import _hashed, valid_c_plan


def _gemini_identity(*, role: str = "classify") -> ModelIdentity:
    return ModelIdentity(
        provider="g3-user-gateway",
        deployment_id="gemini-3.7-flash-medium",
        family="gemini",  # type: ignore[arg-type]
        role=role,  # type: ignore[arg-type]
        policy_version="g3-user-gemini-gateway-v1",
    )


def test_exact_user_gateway_gemini_identity_is_admitted_for_g3_roles() -> None:
    for role in ("classify", "extract", "verify"):
        identity = _gemini_identity(role=role)
        policy = ProductionModelPolicy((identity.identity_key,))
        assert policy.evaluate(identity) == identity


def test_exact_user_gateway_gemini_route_is_admitted() -> None:
    route = G3BoundedRouteConfig(
        endpoint_origin="http://8.148.158.241:3131",
        endpoint_path="/v1/chat/completions",  # type: ignore[arg-type]
        timeout_seconds=30,
        follow_redirects=False,
    )
    assert validate_g3_route(route) == route

    for origin in (
        "https://8.148.158.241:3131",
        "http://8.148.158.241",
        "http://user@8.148.158.241:3131",
        "http://8.148.158.241:3131?x=1",
    ):
        with pytest.raises(G3LedgerDenied):
            validate_g3_route(route.model_copy(update={"endpoint_origin": origin}))


def test_unscoped_gemini_identity_and_route_shapes_stay_rejected() -> None:
    for update in (
        {"provider": "google"},
        {"deployment_id": "gemini-3.7-flash"},
        {"policy_version": "g3-user-gemini-gateway-v2"},
        {"role": "gap"},
    ):
        with pytest.raises((ValidationError, ValueError, ModelPolicyDenied)):
            identity = _gemini_identity().model_copy(update=update)
            ProductionModelPolicy((identity.identity_key,)).evaluate(identity)


def test_gemini_request_and_schema_are_exact_and_identity_selected() -> None:
    identity = _gemini_identity()
    routing = SimpleNamespace(
        identity=identity,
        temperature_micros=0,
        thinking=True,
    )
    call = SimpleNamespace(
        identity=identity,
        endpoint_origin="http://8.148.158.241:3131",
        endpoint_path="/v1/chat/completions",
        output_token_ceiling=321,
    )
    raw = g3_openai_request_bytes(
        plan=SimpleNamespace(routing_lock=routing),
        call=call,
        system="fixed system",
        user="fixed user",
    )
    assert json.loads(raw) == {
        "model": "gemini-3.7-flash-medium",
        "temperature": 0,
        "max_tokens": 321,
        "messages": [
            {
                "role": "system",
                "content": (
                    "fixed system\n\n"
                    "Return only valid JSON, without Markdown fences or explanations."
                ),
            },
            {"role": "user", "content": "fixed user"},
        ],
        "response_format": {"type": "json_object"},
        "stream": False,
    }
    request_schema = g3_current_schema_specs("C_CLASSIFY", identity)[0][2]
    assert request_schema["required"] == [
        "max_tokens",
        "messages",
        "model",
        "response_format",
        "stream",
        "temperature",
    ]


def _gemini_response(*, content: str = '{ "answer": true }') -> bytes:
    return json.dumps(
        {
            "id": "chatcmpl-fixture",
            "object": "chat.completion",
            "created": 1,
            "model": "gemini-3.7-flash-medium",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 101,
                "completion_tokens": 20,
                "total_tokens": 308,
                "completion_tokens_details": {"reasoning_tokens": 187},
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()


def _gemini_aggregate_usage_response(*, content: str = '{ "answer": true }') -> bytes:
    value = json.loads(_gemini_response(content=content))
    value["usage"] = {
        "prompt_tokens": 355_513,
        "completion_tokens": 12_020,
        "total_tokens": 367_533,
    }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()


def test_gemini_response_normalizes_reasoning_and_canonicalizes_content() -> None:
    content, semantic, usage = _parse_g3_gemini_provider_response(
        _gemini_identity(), _gemini_response()
    )
    assert content == '{"answer":true}'
    assert semantic == b'{"answer":true}'
    assert usage.model_dump() == {
        "prompt_tokens": 101,
        "completion_tokens": 207,
        "total_tokens": 308,
        "usage_verified": True,
    }


def test_gemini_response_accepts_exact_aggregate_usage_without_reasoning_detail() -> None:
    content, semantic, usage = _parse_g3_gemini_provider_response(
        _gemini_identity(), _gemini_aggregate_usage_response()
    )
    assert content == '{"answer":true}'
    assert semantic == b'{"answer":true}'
    assert usage.model_dump() == {
        "prompt_tokens": 355_513,
        "completion_tokens": 12_020,
        "total_tokens": 367_533,
        "usage_verified": True,
    }


@pytest.mark.parametrize(
    "mutate",
    (
        lambda usage: usage.update(prompt_tokens=True),
        lambda usage: usage.update(completion_tokens=-1, total_tokens=355_512),
        lambda usage: usage.update(total_tokens=367_532),
        lambda usage: usage.update(extra=0),
    ),
)
def test_gemini_response_rejects_invalid_aggregate_usage(mutate) -> None:
    value = json.loads(_gemini_aggregate_usage_response())
    mutate(value["usage"])
    with pytest.raises(G3LedgerDenied) as denied:
        _parse_g3_gemini_provider_response(
            _gemini_identity(),
            json.dumps(value, separators=(",", ":")).encode(),
        )
    assert denied.value.reason_code == "INVALID_PROVIDER_RESPONSE"


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value["usage"].update(total_tokens=307),
        lambda value: value["usage"].update(prompt_tokens=True),
        lambda value: value["usage"].pop("completion_tokens_details"),
        lambda value: value["usage"]["completion_tokens_details"].update(extra=0),
        lambda value: value.update(model="gemini-3.7-flash"),
        lambda value: value["choices"].append(value["choices"][0]),
        lambda value: value["choices"][0].update(finish_reason="length"),
        lambda value: value["choices"][0]["message"].update(role="tool"),
    ),
)
def test_gemini_response_rejects_nonexact_usage_and_response_shape(mutate) -> None:
    value = json.loads(_gemini_response())
    mutate(value)
    with pytest.raises(G3LedgerDenied) as denied:
        _parse_g3_gemini_provider_response(
            _gemini_identity(),
            json.dumps(value, separators=(",", ":")).encode(),
        )
    assert denied.value.reason_code == "INVALID_PROVIDER_RESPONSE"


@pytest.mark.parametrize(
    "content",
    (
        "```json\n{}\n```",
        '{"x":1,"x":2}',
        '{"x":NaN}',
        "",
    ),
)
def test_gemini_response_rejects_unusable_semantic_content(content: str) -> None:
    with pytest.raises(G3LedgerDenied) as denied:
        _parse_g3_gemini_provider_response(
            _gemini_identity(), _gemini_response(content=content)
        )
    assert denied.value.reason_code == "INVALID_PROVIDER_RESPONSE"


@pytest.mark.parametrize("tamper", ("semantic", "usage"))
def test_gemini_first_terminal_recomputes_persisted_response_closure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, tamper: str
) -> None:
    import insurance_harness.model_policy.g3_bounded_gateway as gateway

    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    _old_plan, old_terminal, _old_semantic, _policy, call_dir = (
        _complete_successful_stage(root)
    )
    (call_dir / "call-terminal.json").unlink()

    plan = _gemini_plan()
    call = plan.request_manifest.calls[0]
    response_bytes = _gemini_response()
    expected_semantic = b'{"answer":true}'
    _content, _semantic, expected_usage = _parse_g3_gemini_provider_response(
        call.identity, response_bytes
    )
    (call_dir / "response-body.private.json").write_bytes(response_bytes)
    (call_dir / "semantic-content.private.json").write_bytes(
        b'{"answer":false}' if tamper == "semantic" else expected_semantic
    )
    persisted_usage = (
        expected_usage.model_copy(update={"prompt_tokens": 100, "completion_tokens": 208})
        if tamper == "usage"
        else expected_usage
    )
    monkeypatch.setattr(
        gateway,
        "consume_g3_response_audit",
        lambda _capability: (old_terminal.response_meta, persisted_usage),
    )

    with pytest.raises(RuntimeError, match="Gemini response audit closure mismatch"):
        _call_terminal(
            plan=plan,
            call=call,
            admission_digest="8" * 64,
            verified_digest="7" * 64,
            call_dir=str(call_dir),
            projection_sha256="2" * 64,
            reservation_capability=object(),
        )
    assert not (call_dir / "call-terminal.json").exists()


def test_gemini_first_terminal_accepts_exact_aggregate_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import insurance_harness.model_policy.g3_bounded_gateway as gateway

    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    _old_plan, old_terminal, _old_semantic, _policy, call_dir = (
        _complete_successful_stage(root)
    )
    (call_dir / "call-terminal.json").unlink()

    plan = _gemini_plan()
    call = plan.request_manifest.calls[0]
    response_bytes = _gemini_aggregate_usage_response()
    _content, expected_semantic, expected_usage = (
        _parse_g3_gemini_provider_response(call.identity, response_bytes)
    )
    (call_dir / "response-body.private.json").write_bytes(response_bytes)
    (call_dir / "semantic-content.private.json").write_bytes(expected_semantic)
    monkeypatch.setattr(
        gateway,
        "consume_g3_response_audit",
        lambda _capability: (old_terminal.response_meta, expected_usage),
    )

    terminal = _call_terminal(
        plan=plan,
        call=call,
        admission_digest="8" * 64,
        verified_digest="7" * 64,
        call_dir=str(call_dir),
        projection_sha256="2" * 64,
        reservation_capability=object(),
    )
    assert terminal.status == "SUCCESS"
    assert terminal.provider_usage == expected_usage


def test_gemini_successful_reopen_reparses_exact_aggregate_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import insurance_harness.model_policy.g3_bounded_gateway as gateway
    import tests.test_g3_bounded_gateway_830 as bounded_tests

    root = tmp_path / "ledger"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(gateway, "G3_LEDGER_ROOT", str(root))
    monkeypatch.setattr(bounded_tests, "valid_c_plan", _gemini_plan)
    plan, old_terminal, _old_semantic, _policy, call_dir = (
        _complete_successful_stage(root)
    )
    (call_dir.parents[1] / "stage-terminals" / f"{plan.stage}.json").unlink()

    response_bytes = _gemini_aggregate_usage_response()
    _content, semantic, usage = _parse_g3_gemini_provider_response(
        plan.request_manifest.calls[0].identity, response_bytes
    )
    (call_dir / "response-body.private.json").write_bytes(response_bytes)
    (call_dir / "semantic-content.private.json").write_bytes(semantic)
    provisional = old_terminal.model_copy(
        update={
            "response_body_sha256": hashlib.sha256(response_bytes).hexdigest(),
            "response_bytes": len(response_bytes),
            "semantic_content_sha256": hashlib.sha256(semantic).hexdigest(),
            "provider_usage": usage,
            "receipt_sha256": "0" * 64,
        }
    )
    terminal = provisional.model_copy(
        update={
            "receipt_sha256": canonical_g3_hash(
                "g3-call-terminal-receipt.830.v1", provisional, "receipt_sha256"
            )
        }
    )
    (call_dir / "call-terminal.json").write_bytes(
        canonical_json(terminal.model_dump(mode="json", round_trip=True))
    )

    reopened = gateway._reopen_completed_g3_call(
        plan=plan,
        call=plan.request_manifest.calls[0],
        admission_artifact_digest="8" * 64,
    )
    assert reopened is not None
    assert reopened[0].provider_usage == usage
    assert reopened[1] == semantic


def _gemini_plan():
    base = valid_c_plan()
    identity = _gemini_identity()
    calls = tuple(
        call.model_copy(
            update={
                "identity": identity,
                "endpoint_origin": "http://8.148.158.241:3131",
                "endpoint_path": "/v1/chat/completions",
            }
        )
        for call in base.request_manifest.calls
    )
    manifest = _hashed(
        type(base.request_manifest),
        "g3-request-manifest.830.v1",
        "manifest_hash",
        **{
            **base.request_manifest.model_dump(mode="python", exclude={"manifest_hash"}),
            "calls": calls,
        },
    )
    routing = _hashed(
        type(base.routing_lock),
        "g3-stage-routing.830.v1",
        "routing_policy_hash",
        **{
            **base.routing_lock.model_dump(mode="python", exclude={"routing_policy_hash"}),
            "identity": identity,
            "endpoint_origin": "http://8.148.158.241:3131",
            "endpoint_path": "/v1/chat/completions",
            "thinking": True,
        },
    )
    dispatch = _hashed(
        type(base.dispatch_lock),
        "g3-stage-dispatch.830.v1",
        "structured_dispatch_hash",
        **{
            **base.dispatch_lock.model_dump(
                mode="python", exclude={"structured_dispatch_hash"}
            ),
            "calls": calls,
        },
    )
    rights = _hashed(
        type(base.rights_lock),
        "g3-external-send-rights.830.v1",
        "rights_hash",
        **{
            **base.rights_lock.model_dump(mode="python", exclude={"rights_hash"}),
            "provider": identity.provider,
            "deployment_id": identity.deployment_id,
            "endpoint_origin": "http://8.148.158.241:3131",
            "endpoint_path": "/v1/chat/completions",
        },
    )
    return base.model_copy(
        update={
            "request_manifest": manifest,
            "manifest_hash": manifest.manifest_hash,
            "routing_lock": routing,
            "routing_policy_hash": routing.routing_policy_hash,
            "dispatch_lock": dispatch,
            "structured_dispatch_hash": dispatch.structured_dispatch_hash,
            "rights_lock": rights,
            "rights_hash": rights.rights_hash,
            "approved_identities": (identity,),
            "model_plan_hash": canonical_model_plan_hash((identity,)),
            "deployment_roles_hash": canonical_model_identities_hash((identity,)),
        }
    )


def test_gemini_plan_profile_requires_exact_cross_bound_route() -> None:
    plan = _gemini_plan()
    assert validate_g3_bounded_plan(plan) == plan
    crossed_routing = _hashed(
        type(plan.routing_lock),
        "g3-stage-routing.830.v1",
        "routing_policy_hash",
        **{
            **plan.routing_lock.model_dump(mode="python", exclude={"routing_policy_hash"}),
            "endpoint_origin": "https://dashscope.aliyuncs.com",
            "endpoint_path": "/compatible-mode/v1/chat/completions",
        },
    )
    with pytest.raises(ValueError, match="invalid G3 bounded admission plan"):
        validate_g3_bounded_plan(
            plan.model_copy(
                update={
                    "routing_lock": crossed_routing,
                    "routing_policy_hash": crossed_routing.routing_policy_hash,
                }
            )
        )
