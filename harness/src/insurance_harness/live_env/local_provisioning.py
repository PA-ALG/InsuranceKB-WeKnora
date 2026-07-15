"""Concrete local-only provisioning controller for OpenSpec 023."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.adapters.weknora.admin_client import (
    AdminCredentials,
    WeKnoraAdminClient,
    WeKnoraProvisioningBackend,
)
from insurance_harness.live_env.compose import (
    read_runtime_environment,
    update_runtime_state,
)
from insurance_harness.live_env.config import LocalLiveConfig, ModelProfile
from insurance_harness.live_env.model_probe import ProbeResult, probe_all_models
from insurance_harness.live_env.provision import ProvisionPlan, provision_local_live
from insurance_harness.live_env.space import HarnessSpaceBackend

_MARKER = "insurancekb-local-live-v1"
_PARSER_FINGERPRINT = "weknora-v0.6.3"


class ProvisionRequest(Protocol):
    phase: str
    pdf_path: Path | None


class ProvisionOperation(Protocol):
    async def provision(
        self,
        configuration: LocalLiveConfig,
        runtime: Path,
        source_pdf: Path,
        embedding_dimension: int,
    ) -> Mapping[str, str]: ...


ModelProber = Callable[
    [LocalLiveConfig], Awaitable[Mapping[str, ProbeResult]]
]


def _database_url(values: Mapping[str, str]) -> str:
    password = quote_plus(values["HARNESS_POSTGRES_PASSWORD"])
    return (
        "postgresql+psycopg://harness:"
        f"{password}@127.0.0.1:5442/insurance_kb"
    )


def _model_payload(
    profile: ModelProfile,
    *,
    model_type: str,
    dimension: int | None = None,
) -> dict[str, object]:
    parameters: dict[str, object] = {
        "base_url": profile.base_url,
        "api_key": profile.api_key.get_secret_value(),
        "provider": "siliconflow",
    }
    if dimension is not None:
        parameters["embedding_parameters"] = {
            "dimension": dimension,
            "truncate_prompt_tokens": 256,
            "supports_dimension_override": False,
        }
    return {
        "type": model_type,
        "source": "siliconflow",
        "parameters": parameters,
    }


class RealProvisioningOperation:
    """Own the real Alembic, WeKnora REST and Harness DB mutation sequence."""

    def __init__(
        self,
        *,
        repo_root: Path,
        api_base_url: str = "http://127.0.0.1:8080/api/v1",
    ) -> None:
        self._repo_root = repo_root
        self._api_base_url = api_base_url

    def _migrate(self, database_url: str) -> None:
        environment = dict(os.environ)
        environment["HARNESS_DB_URL"] = database_url
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=self._repo_root / "harness",
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError("Harness database migration failed")

    async def provision(
        self,
        configuration: LocalLiveConfig,
        runtime: Path,
        source_pdf: Path,
        embedding_dimension: int,
    ) -> Mapping[str, str]:
        runtime_values = read_runtime_environment(runtime)
        database_url = _database_url(runtime_values)
        self._migrate(database_url)
        engine = create_engine(database_url)
        factory: sessionmaker[Session] = sessionmaker(
            bind=engine,
            expire_on_commit=False,
        )
        client = WeKnoraAdminClient(self._api_base_url)
        try:
            admin = await client.bootstrap_admin(
                AdminCredentials(
                    username=runtime_values["WEKNORA_ADMIN_USERNAME"],
                    email=runtime_values["WEKNORA_ADMIN_EMAIL"],
                    password=runtime_values["WEKNORA_ADMIN_PASSWORD"],
                )
            )
            backend = WeKnoraProvisioningBackend(
                client,
                admin,
                model_payloads={
                    "chat": _model_payload(
                        configuration.weknora_chat,
                        model_type="KnowledgeQA",
                    ),
                    "embedding": _model_payload(
                        configuration.weknora_embedding,
                        model_type="Embedding",
                        dimension=embedding_dimension,
                    ),
                    "rerank": _model_payload(
                        configuration.weknora_rerank,
                        model_type="Rerank",
                    ),
                },
                knowledge_base_payloads={
                    "raw": {"type": "document"},
                    "wiki": {"type": "wiki"},
                },
            )
            result = await provision_local_live(
                backend,
                ProvisionPlan(
                    marker=_MARKER,
                    tenant_name="insurancekb-local-live",
                    chat_model=configuration.weknora_chat.model,
                    embedding_model=configuration.weknora_embedding.model,
                    rerank_model=configuration.weknora_rerank.model,
                    embedding_dimension=embedding_dimension,
                    raw_kb_name="KB-RAW",
                    wiki_kb_name="KB-WIKI",
                    api_key_name="insurancekb-live-contributor",
                    space_name="insurancekb-live-space",
                    pdf_path=source_pdf,
                ),
                space_backend=HarnessSpaceBackend(factory, marker=_MARKER),
            )
            return {
                "LOCAL_LIVE_TENANT_ID": result.tenant_id,
                "LOCAL_LIVE_CHAT_MODEL_ID": result.chat_model_id,
                "LOCAL_LIVE_EMBEDDING_MODEL_ID": result.embedding_model_id,
                "LOCAL_LIVE_RERANK_MODEL_ID": result.rerank_model_id,
                "LOCAL_LIVE_RAW_KB_ID": result.raw_kb_id,
                "LOCAL_LIVE_WIKI_KB_ID": result.wiki_kb_id,
                "LOCAL_LIVE_API_KEY_ID": result.api_key_id,
                "LOCAL_LIVE_API_KEY": backend.live_api_key().get_secret_value(),
                "LOCAL_LIVE_SPACE_ID": result.space_id,
                "LOCAL_LIVE_KNOWLEDGE_ID": result.knowledge.id,
                "LOCAL_LIVE_PARSER_FINGERPRINT": _PARSER_FINGERPRINT,
            }
        finally:
            await client.aclose()
            engine.dispose()


class ProvisionCollaborator:
    """Probe first, provision second, then atomically attest the identity graph."""

    def __init__(
        self,
        *,
        config: LocalLiveConfig,
        runtime_path: Path,
        prober: ModelProber = probe_all_models,
        operation: ProvisionOperation,
    ) -> None:
        self._config = config
        self._runtime_path = runtime_path
        self._prober = prober
        self._operation = operation

    async def _provision(self, source_pdf: Path) -> Mapping[str, str]:
        results = await self._prober(self._config)
        embedding = results.get("weknora_embedding")
        dimension = (
            embedding.embedding_dimension if embedding is not None else None
        )
        if (
            not isinstance(dimension, int)
            or isinstance(dimension, bool)
            or dimension <= 0
        ):
            raise RuntimeError("embedding probe has no observed dimension")
        return await self._operation.provision(
            self._config,
            self._runtime_path,
            source_pdf,
            dimension,
        )

    def run(self, request: ProvisionRequest) -> object:
        if request.phase == "verify":
            values = read_runtime_environment(self._runtime_path)
            if "LOCAL_LIVE_SPACE_ID" not in values:
                raise RuntimeError("local-live resources are not provisioned")
            return {"status": "verified", "resources": 10}
        if request.phase != "provision":
            raise ValueError("unsupported provisioning phase")
        source_pdf = request.pdf_path
        if source_pdf is None or not source_pdf.is_file() or source_pdf.suffix.lower() != ".pdf":
            raise ValueError("provision requires an existing PDF")
        state = asyncio.run(self._provision(source_pdf))
        update_runtime_state(self._runtime_path, state)
        return {"status": "provisioned", "resources": 10}
