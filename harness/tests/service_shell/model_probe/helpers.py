"""OpenSpec 023 R1.2 model role probes: shared probe inputs, profiles and routes."""

import respx
from pydantic import SecretStr

from insurance_harness.live_env.config import LocalLiveConfig, ModelProfile

VLM_CANARY = "INSURANCEKBVLM023CANARY7F3A"
RERANK_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/"
    "rerank/text-rerank/text-rerank"
)
CHAT_PROMPT = "R1.2 chat health check: reply with probe-ok."
EMBEDDING_INPUT = "R1.2 embedding dimension probe"
RERANK_QUERY = "R1.2 life insurance query"
RERANK_DOCUMENTS = ["R1.2 unrelated document", "R1.2 life insurance policy"]
VLM_PROMPT = "Read the visual canary text exactly."
EXTRACTION_SYSTEM = "You are a health check."
EXTRACTION_USER = "Reply with probe-ok."


def _profile(
    base_url: str,
    model: str,
    secret: str,
    *,
    protocol: str = "openai_compatible",
) -> ModelProfile:
    return ModelProfile(
        base_url=base_url,
        api_key=SecretStr(secret),
        model=model,
        provider="aliyun",
        protocol=protocol,
    )


def _config() -> LocalLiveConfig:
    return LocalLiveConfig(
        weknora_chat=_profile(
            "https://chat.example/v1", "chat-model", "chat-secret"
        ),
        weknora_embedding=_profile(
            "https://embedding.example/v1", "embedding-model", "embedding-secret"
        ),
        weknora_rerank=_profile(
            RERANK_URL,
            "rerank-model",
            "rerank-secret",
            protocol="dashscope_native",
        ),
        weknora_vllm=_profile(
            "https://vlm.example/v1", "qwen3.7-plus", "vlm-secret"
        ),
        extraction=_profile(
            "https://bailian.example/v1", "deepseek-v4-flash", "bailian-secret"
        ),
    )


def _healthy_routes() -> dict[str, respx.Route]:
    return {
        "weknora_chat": respx.post(
            "https://chat.example/v1/chat/completions"
        ).respond(
            json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        ),
        "weknora_embedding": respx.post(
            "https://embedding.example/v1/embeddings"
        ).respond(json={"data": [{"embedding": [0.1, 0.2, 0.3]}]}),
        "weknora_rerank": respx.post(RERANK_URL).respond(
            json={
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.9},
                        {"index": 0, "relevance_score": 0.2},
                    ]
                }
            }
        ),
        "weknora_vllm": respx.post(
            "https://vlm.example/v1/chat/completions"
        ).respond(
            json={
                "choices": [
                    {
                        "message": {"content": f"visual text: {VLM_CANARY}"},
                        "finish_reason": "stop",
                    }
                ]
            }
        ),
        "extraction": respx.post(
            "https://bailian.example/v1/chat/completions"
        ).respond(
            json={
                "choices": [
                    {
                        "message": {
                            "content": "probe-ok",
                            "reasoning_content": "private",
                        },
                        "finish_reason": "stop",
                    }
                ]
            }
        ),
    }
