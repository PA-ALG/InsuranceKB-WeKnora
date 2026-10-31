"""OpenSpec 023 local-live CLI contracts: shared script loader, phases and private env fixtures."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Protocol

REPO_ROOT = Path(__file__).resolve().parents[4]
CLI_PATH = REPO_ROOT / "harness/scripts/local_live.py"


class PhaseRequestLike(Protocol):
    phase: str
    delete_volumes: bool
    knowledge_id: str | None


def _module() -> ModuleType:
    assert CLI_PATH.is_file(), "local-live CLI is missing"
    spec = importlib.util.spec_from_file_location("local_live_cli_023", CLI_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ResolvedLocks:
    def require_resolved(self) -> None:
        return None


def _write_local_envs(tmp_path: Path) -> tuple[Path, Path]:
    config = tmp_path / ".env.local-live"
    config.write_text(
        "LOCAL_LIVE_WEKNORA_CHAT_BASE_URL=https://chat.example/v1\n"
        "LOCAL_LIVE_WEKNORA_CHAT_API_KEY=chat-key\n"
        "LOCAL_LIVE_WEKNORA_CHAT_MODEL=chat-model\n"
        "LOCAL_LIVE_WEKNORA_CHAT_PROVIDER=aliyun\n"
        "LOCAL_LIVE_WEKNORA_CHAT_PROTOCOL=openai_compatible\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_BASE_URL=https://embedding.example/v1\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_API_KEY=embedding-key\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_MODEL=embedding-model\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_PROVIDER=aliyun\n"
        "LOCAL_LIVE_WEKNORA_EMBEDDING_PROTOCOL=openai_compatible\n"
        "LOCAL_LIVE_WEKNORA_RERANK_BASE_URL=https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank\n"
        "LOCAL_LIVE_WEKNORA_RERANK_API_KEY=rerank-key\n"
        "LOCAL_LIVE_WEKNORA_RERANK_MODEL=rerank-model\n"
        "LOCAL_LIVE_WEKNORA_RERANK_PROVIDER=aliyun\n"
        "LOCAL_LIVE_WEKNORA_RERANK_PROTOCOL=dashscope_native\n"
        "LOCAL_LIVE_WEKNORA_VLLM_BASE_URL=https://vlm.example/v1\n"
        "LOCAL_LIVE_WEKNORA_VLLM_API_KEY=vlm-key\n"
        "LOCAL_LIVE_WEKNORA_VLLM_MODEL=vlm-model\n"
        "LOCAL_LIVE_WEKNORA_VLLM_PROVIDER=aliyun\n"
        "LOCAL_LIVE_WEKNORA_VLLM_PROTOCOL=openai_compatible\n"
        "HARNESS_LLM_BASE_URL=https://bailian.example/v1\n"
        "HARNESS_LLM_API_KEY=private-api-key\n"
        "HARNESS_LLM_MODEL_WEAK=deepseek-v4-flash\n"
        "HARNESS_LLM_PROVIDER=aliyun\n"
        "HARNESS_LLM_PROTOCOL=openai_compatible\n"
    )
    runtime = tmp_path / ".env.local-live.runtime"
    runtime.write_text(
        "DB_USER=weknora\n"
        "DB_NAME=weknora\n"
        f"DB_PASSWORD={'d' * 32}\n"
        f"REDIS_PASSWORD={'r' * 32}\n"
        f"JWT_SECRET={'j' * 32}\n"
        f"SYSTEM_AES_KEY={'a' * 32}\n"
        f"HARNESS_POSTGRES_PASSWORD={'h' * 32}\n"
        "WEKNORA_VERSION=v0.6.3\n"
    )
    config.chmod(0o600)
    runtime.chmod(0o600)
    return config, runtime
