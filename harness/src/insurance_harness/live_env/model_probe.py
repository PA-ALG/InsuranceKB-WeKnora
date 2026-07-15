"""Redacted probes for local-live remote model roles."""

from collections.abc import Awaitable, Mapping
from dataclasses import dataclass
from math import isfinite
from time import monotonic
from typing import Any

import httpx

from insurance_harness.compiler.llm import OpenAICompatClient, TruncatedOutputError
from insurance_harness.live_env.config import LocalLiveConfig, ModelProfile


@dataclass(frozen=True)
class ProbeResult:
    role: str
    model: str
    ok: bool
    latency_ms: int
    embedding_dimension: int | None = None


class ModelProbeError(RuntimeError):
    """Sanitized role-level probe failure."""


async def _post(profile: ModelProfile, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(
        base_url=profile.base_url.rstrip("/"),
        headers={"Authorization": f"Bearer {profile.api_key.get_secret_value()}"},
        timeout=30.0,
        trust_env=False,
    ) as client:
        response = await client.post(path, json=payload)
        response.raise_for_status()
        document: dict[str, Any] = response.json()
        return document


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


async def _probe_chat(profile: ModelProfile) -> ProbeResult:
    started = monotonic()
    for attempt in range(2):
        document = await _post(
            profile,
            "/chat/completions",
            {
                "model": profile.model,
                "max_tokens": 4096,
                "messages": [{"role": "user", "content": "Reply with ok."}],
            },
        )
        choice = document["choices"][0]
        content = choice["message"]["content"]
        if isinstance(content, str) and content.strip():
            return _result("weknora_chat", profile, started)
        if choice.get("finish_reason") != "length" or attempt == 1:
            raise ValueError("weknora_chat probe returned invalid content")
    raise AssertionError("unreachable")


async def _probe_embedding(profile: ModelProfile) -> ProbeResult:
    started = monotonic()
    document = await _post(
        profile,
        "/embeddings",
        {"model": profile.model, "input": ["dimension probe"]},
    )
    vector = document["data"][0]["embedding"]
    if (
        not isinstance(vector, list)
        or not vector
        or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isfinite(value)
            for value in vector
        )
    ):
        raise ValueError("weknora_embedding probe returned invalid vector")
    return _result("weknora_embedding", profile, started, dimension=len(vector))


async def _probe_rerank(profile: ModelProfile) -> ProbeResult:
    started = monotonic()
    document = await _post(
        profile,
        "/rerank",
        {
            "model": profile.model,
            "query": "life insurance",
            "documents": ["unrelated", "life insurance policy"],
        },
    )
    results = document["results"]
    first = results[0] if isinstance(results, list) and results else None
    if not isinstance(first, Mapping):
        raise ValueError("weknora_rerank probe returned invalid results")
    index = first.get("index")
    score = first.get("relevance_score")
    if (
        not isinstance(index, int)
        or isinstance(index, bool)
        or index < 0
        or not isinstance(score, (int, float))
        or isinstance(score, bool)
        or not isfinite(score)
    ):
        raise ValueError("weknora_rerank probe returned invalid results")
    return _result("weknora_rerank", profile, started)


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
                await client.complete("You are a health check.", "Reply with probe-ok.")
                break
            except TruncatedOutputError:
                if attempt == 1:
                    raise
    finally:
        await client.aclose()
    return _result("extraction", profile, started)


async def _redacted(role: str, probe: Awaitable[ProbeResult]) -> ProbeResult:
    try:
        result: ProbeResult = await probe
    except Exception:
        raise ModelProbeError(f"{role} probe failed") from None
    return result


async def probe_all_models(config: LocalLiveConfig) -> dict[str, ProbeResult]:
    results = (
        await _redacted("weknora_chat", _probe_chat(config.weknora_chat)),
        await _redacted("weknora_embedding", _probe_embedding(config.weknora_embedding)),
        await _redacted("weknora_rerank", _probe_rerank(config.weknora_rerank)),
        await _redacted("extraction", _probe_extraction(config.extraction)),
    )
    return {result.role: result for result in results}
