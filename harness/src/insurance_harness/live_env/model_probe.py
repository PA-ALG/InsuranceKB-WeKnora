"""Redacted probes for local-live remote model roles."""

import base64
from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from math import isfinite
from time import monotonic
from typing import Any, cast

import httpx

from insurance_harness.compiler.llm import OpenAICompatClient, TruncatedOutputError
from insurance_harness.live_env.config import (
    DASHSCOPE_RERANK_ENDPOINT,
    LocalLiveConfig,
    ModelProfile,
)

_CHAT_PROMPT = "R1.2 chat health check: reply with probe-ok."
_EMBEDDING_INPUT = "R1.2 embedding dimension probe"
_RERANK_QUERY = "R1.2 life insurance query"
_RERANK_DOCUMENTS = ("R1.2 unrelated document", "R1.2 life insurance policy")
_RERANK_MIN_RESULTS = 2
_VLM_PROMPT = "Read the visual canary text exactly."
_VLM_CANARY = "INSURANCEKBVLM023CANARY7F3A"
_EXTRACTION_SYSTEM = "You are a health check."
_EXTRACTION_USER = "Reply with probe-ok."


@dataclass(frozen=True)
class ProbeResult:
    role: str
    model: str
    ok: bool
    latency_ms: int
    embedding_dimension: int | None = None


class ModelProbeError(RuntimeError):
    """Sanitized role-level probe failure."""


def _compatible_url(profile: ModelProfile, path: str) -> str:
    return f"{profile.base_url.rstrip('/')}{path}"


async def _post(
    profile: ModelProfile,
    url: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {profile.api_key.get_secret_value()}"},
        timeout=30.0,
        trust_env=False,
    ) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        document = response.json()
    if not isinstance(document, dict):
        raise ValueError("model probe returned invalid document")
    return cast(dict[str, Any], document)


def _result(
    role: str,
    profile: ModelProfile,
    started: float,
    *,
    dimension: int | None = None,
) -> ProbeResult:
    return ProbeResult(
        role=role,
        model=profile.model,
        ok=True,
        latency_ms=max(0, round((monotonic() - started) * 1000)),
        embedding_dimension=dimension,
    )


def _completion(document: Mapping[str, Any]) -> tuple[str, str]:
    choices = document.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("model probe returned invalid completion")
    choice = choices[0]
    if not isinstance(choice, Mapping):
        raise ValueError("model probe returned invalid completion")
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("model probe returned invalid completion")
    content = message.get("content")
    finish_reason = choice.get("finish_reason")
    return (
        content if isinstance(content, str) else "",
        finish_reason if isinstance(finish_reason, str) else "",
    )


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and isfinite(value)
    )


async def _probe_chat(profile: ModelProfile) -> ProbeResult:
    started = monotonic()
    for attempt in range(2):
        document = await _post(
            profile,
            _compatible_url(profile, "/chat/completions"),
            {
                "model": profile.model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": _CHAT_PROMPT}],
            },
        )
        content, finish_reason = _completion(document)
        if content.strip():
            return _result("weknora_chat", profile, started)
        if finish_reason != "length" or attempt == 1:
            raise ValueError("weknora_chat probe returned invalid content")
    raise AssertionError("unreachable")


async def _probe_embedding(profile: ModelProfile) -> ProbeResult:
    started = monotonic()
    document = await _post(
        profile,
        _compatible_url(profile, "/embeddings"),
        {"model": profile.model, "input": [_EMBEDDING_INPUT]},
    )
    data = document.get("data")
    first = data[0] if isinstance(data, list) and data else None
    vector = first.get("embedding") if isinstance(first, Mapping) else None
    if (
        not isinstance(vector, list)
        or not vector
        or not all(_finite_number(value) for value in vector)
    ):
        raise ValueError("weknora_embedding probe returned invalid vector")
    return _result("weknora_embedding", profile, started, dimension=len(vector))


def _validate_rerank_results(document: Mapping[str, Any]) -> None:
    output = document.get("output")
    results = output.get("results") if isinstance(output, Mapping) else None
    if not isinstance(results, list) or len(results) < _RERANK_MIN_RESULTS:
        raise ValueError("weknora_rerank probe returned invalid results")
    seen_indices: set[int] = set()
    for raw_result in results:
        if not isinstance(raw_result, Mapping):
            raise ValueError("weknora_rerank probe returned invalid results")
        index = raw_result.get("index")
        score = raw_result.get("relevance_score")
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= len(_RERANK_DOCUMENTS)
            or index in seen_indices
            or not _finite_number(score)
        ):
            raise ValueError("weknora_rerank probe returned invalid results")
        seen_indices.add(index)


async def _probe_rerank(profile: ModelProfile) -> ProbeResult:
    started = monotonic()
    document = await _post(
        profile,
        profile.base_url,
        {
            "model": profile.model,
            "input": {
                "query": _RERANK_QUERY,
                "documents": list(_RERANK_DOCUMENTS),
            },
            "parameters": {"top_n": _RERANK_MIN_RESULTS},
        },
    )
    _validate_rerank_results(document)
    return _result("weknora_rerank", profile, started)


async def _probe_vllm(profile: ModelProfile) -> ProbeResult:
    started = monotonic()
    canary = (
        files("insurance_harness.live_env")
        .joinpath("fixtures", "vlm-canary.png")
        .read_bytes()
    )
    image_data = base64.b64encode(canary).decode("ascii")
    document = await _post(
        profile,
        _compatible_url(profile, "/chat/completions"),
        {
            "model": profile.model,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VLM_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_data}"
                            },
                        },
                    ],
                }
            ],
        },
    )
    content, _ = _completion(document)
    if _VLM_CANARY not in content:
        raise ValueError("weknora_vllm probe returned invalid content")
    return _result("weknora_vllm", profile, started)


async def _probe_extraction(profile: ModelProfile) -> ProbeResult:
    started = monotonic()
    client = OpenAICompatClient(
        base_url=profile.base_url,
        api_key=profile.api_key.get_secret_value(),
        model=profile.model,
        max_tokens=4096,
    )
    try:
        for attempt in range(2):
            try:
                await client.complete(_EXTRACTION_SYSTEM, _EXTRACTION_USER)
                break
            except TruncatedOutputError:
                if attempt == 1:
                    raise
    finally:
        await client.aclose()
    return _result("extraction", profile, started)


async def _validate_profile(
    profile: ModelProfile,
    *,
    expected_protocol: str,
    expected_endpoint: str | None = None,
) -> None:
    if (
        profile.provider != "aliyun"
        or profile.protocol != expected_protocol
        or (expected_endpoint is not None and profile.base_url != expected_endpoint)
    ):
        raise ValueError("model profile is invalid")


async def _redacted[T](role: str, probe: Awaitable[T]) -> T:
    try:
        return await probe
    except Exception:
        pass
    raise ModelProbeError(f"{role} probe failed")


async def probe_all_models(config: LocalLiveConfig) -> dict[str, ProbeResult]:
    contracts = (
        ("weknora_chat", config.weknora_chat, "openai_compatible", None),
        ("weknora_embedding", config.weknora_embedding, "openai_compatible", None),
        (
            "weknora_rerank",
            config.weknora_rerank,
            "dashscope_native",
            DASHSCOPE_RERANK_ENDPOINT,
        ),
        ("weknora_vllm", config.weknora_vllm, "openai_compatible", None),
        ("extraction", config.extraction, "openai_compatible", None),
    )
    for role, profile, protocol, endpoint in contracts:
        await _redacted(
            role,
            _validate_profile(
                profile,
                expected_protocol=protocol,
                expected_endpoint=endpoint,
            ),
        )

    results = (
        await _redacted("weknora_chat", _probe_chat(config.weknora_chat)),
        await _redacted(
            "weknora_embedding", _probe_embedding(config.weknora_embedding)
        ),
        await _redacted("weknora_rerank", _probe_rerank(config.weknora_rerank)),
        await _redacted("weknora_vllm", _probe_vllm(config.weknora_vllm)),
        await _redacted("extraction", _probe_extraction(config.extraction)),
    )
    return {result.role: result for result in results}
