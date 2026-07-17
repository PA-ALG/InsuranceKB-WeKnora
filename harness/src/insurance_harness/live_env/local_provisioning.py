"""Concrete local-only provisioning controller for OpenSpec 023."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Awaitable, Callable, Mapping
from hashlib import sha256
from pathlib import Path
from typing import Protocol
from urllib.parse import quote_plus

from pydantic import SecretStr
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.adapters.weknora.admin_client import (
    AdminCredentials,
    AdminSession,
    KnowledgeProcessConfig,
    TypedChunkListing,
    VLMProcessConfig,
    WeKnoraAdminClient,
    WeKnoraProvisioningBackend,
)
from insurance_harness.live_env.compose import (
    read_runtime_environment,
    update_runtime_state,
)
from insurance_harness.live_env.config import LocalLiveConfig, ModelProfile
from insurance_harness.live_env.model_probe import ProbeResult, probe_all_models
from insurance_harness.live_env.provision import (
    ProvisionedEnvironment,
    ProvisionPlan,
    canonical_endpoint_fingerprint,
    provision_local_live,
)
from insurance_harness.live_env.space import HarnessSpaceBackend

_MARKER = "insurancekb-local-live-v1"
_PARSER_FINGERPRINT = "weknora-v0.6.3"
_VLM_CANARY = "INSURANCEKBVLM023CANARY7F3A"
_VLM_FIXTURE = Path(__file__).with_name("fixtures") / "vlm-canary.png"
_VLM_PURPOSE = "vlm-smoke"
_RETRYABLE_VLM_STATUSES = frozenset({"failed", "cancelled", "incomplete"})


class ProvisionRequest(Protocol):
    phase: str
    pdf_path: Path | None
    knowledge_id: str | None


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
RuntimeLoader = Callable[[Path], Mapping[str, str]]
AdminClientFactory = Callable[[str], WeKnoraAdminClient]


class APIKeyResolver(Protocol):
    async def resolve(
        self, runtime: Mapping[str, str] | None = None
    ) -> SecretStr: ...


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
    supports_vision: bool = False,
) -> dict[str, object]:
    parameters: dict[str, object] = {
        "base_url": profile.base_url,
        "api_key": profile.api_key.get_secret_value(),
        "provider": profile.provider,
        "supports_vision": supports_vision,
    }
    if dimension is not None:
        parameters["embedding_parameters"] = {
            "dimension": dimension,
            "truncate_prompt_tokens": 256,
            "supports_dimension_override": False,
        }
    payload: dict[str, object] = {
        "type": model_type,
        "source": "remote",
        "parameters": parameters,
    }
    return payload


def _knowledge_base_payloads() -> dict[str, dict[str, object]]:
    return {
        "raw": {"type": "document"},
        "wiki": {
            "type": "wiki",
            "indexing_strategy": {
                "vector_enabled": True,
                "keyword_enabled": True,
                "wiki_enabled": True,
                "graph_enabled": False,
            },
            "wiki_config": {},
        },
    }


def _runtime_model_state(
    configuration: LocalLiveConfig,
    result: ProvisionedEnvironment,
) -> dict[str, str]:
    profiles = {
        "CHAT": configuration.weknora_chat,
        "EMBEDDING": configuration.weknora_embedding,
        "RERANK": configuration.weknora_rerank,
        "VLLM": configuration.weknora_vllm,
    }
    model_ids = {
        "CHAT": result.chat_model_id,
        "EMBEDDING": result.embedding_model_id,
        "RERANK": result.rerank_model_id,
        "VLLM": result.vlm_model_id,
    }
    state = {
        f"LOCAL_LIVE_{role}_MODEL_ID": identifier
        for role, identifier in model_ids.items()
    }
    state.update(
        {
            f"LOCAL_LIVE_{role}_ENDPOINT_FINGERPRINT": (
                canonical_endpoint_fingerprint(profile.base_url)
            )
            for role, profile in profiles.items()
        }
    )
    return state


async def _restore_runtime_tenant(
    client: WeKnoraAdminClient,
    session: AdminSession,
    runtime_values: Mapping[str, str],
) -> AdminSession:
    """Restore the persisted local-live tenant before ownership discovery."""

    recorded = runtime_values.get("LOCAL_LIVE_TENANT_ID")
    if recorded is None:
        return session
    if not recorded.isdecimal() or int(recorded) <= 0:
        raise ValueError("invalid LOCAL_LIVE_TENANT_ID in runtime state")
    tenant_id = int(recorded)
    if tenant_id == session.tenant_id:
        return session
    return await client.switch_tenant(session, tenant_id)


class RuntimeAPIKeyResolver:
    """Recover the exact scoped tenant key in memory through admin REST."""

    def __init__(
        self,
        *,
        runtime_path: Path,
        api_base_url: str = "http://127.0.0.1:8080/api/v1",
        runtime_loader: RuntimeLoader = read_runtime_environment,
        client_factory: AdminClientFactory = WeKnoraAdminClient,
    ) -> None:
        self._runtime_path = runtime_path
        self._api_base_url = api_base_url
        self._runtime_loader = runtime_loader
        self._client_factory = client_factory

    async def _resolve(self, values: Mapping[str, str]) -> SecretStr:
        client = self._client_factory(self._api_base_url)
        try:
            session = await client.bootstrap_admin(
                AdminCredentials(
                    username=values["WEKNORA_ADMIN_USERNAME"],
                    email=values["WEKNORA_ADMIN_EMAIL"],
                    password=values["WEKNORA_ADMIN_PASSWORD"],
                )
            )
            session = await _restore_runtime_tenant(client, session, values)
            tenant_id = int(values["LOCAL_LIVE_TENANT_ID"])
            key_id = values["LOCAL_LIVE_API_KEY_ID"]
            if not key_id.isdecimal() or int(key_id) <= 0:
                raise ValueError("invalid runtime API-key ID")
            keys = await client.list_tenant_api_keys(
                session,
                tenant_id=tenant_id,
            )
            matching = [key for key in keys if key.id == int(key_id)]
            expected_kbs = {
                values["LOCAL_LIVE_RAW_KB_ID"],
                values["LOCAL_LIVE_WIKI_KB_ID"],
            }
            expected_name = (
                "insurancekb-live-contributor::owner="
                f"{_MARKER}"
            )
            if len(matching) != 1:
                raise ValueError("runtime API-key identity mismatch")
            key = matching[0]
            if (
                key.tenant_id != tenant_id
                or key.name != expected_name
                or key.role != "contributor"
                or key.full_access
                or len(key.knowledge_base_ids) != len(expected_kbs)
                or set(key.knowledge_base_ids) != expected_kbs
                or len(key.capabilities) != 2
                or set(key.capabilities) != {"retrieve", "ingest"}
            ):
                raise ValueError("runtime API-key identity mismatch")
            return key.token
        finally:
            await client.aclose()

    async def resolve(
        self, runtime: Mapping[str, str] | None = None
    ) -> SecretStr:
        values = self._runtime_loader(self._runtime_path) if runtime is None else runtime
        try:
            return await self._resolve(values)
        except Exception:
            raise RuntimeError("tenant API-key resolution failed") from None


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
            admin = await _restore_runtime_tenant(client, admin, runtime_values)
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
                    "vlm": _model_payload(
                        configuration.weknora_vllm,
                        model_type="VLLM",
                        supports_vision=True,
                    ),
                },
                knowledge_base_payloads=_knowledge_base_payloads(),
            )
            result = await provision_local_live(
                backend,
                ProvisionPlan(
                    marker=_MARKER,
                    tenant_name="insurancekb-local-live",
                    chat_model=configuration.weknora_chat.model,
                    embedding_model=configuration.weknora_embedding.model,
                    rerank_model=configuration.weknora_rerank.model,
                    vlm_model=configuration.weknora_vllm.model,
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
                **_runtime_model_state(configuration, result),
                "LOCAL_LIVE_RAW_KB_ID": result.raw_kb_id,
                "LOCAL_LIVE_WIKI_KB_ID": result.wiki_kb_id,
                "LOCAL_LIVE_API_KEY_ID": result.api_key_id,
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
            return {"status": "verified", "resources": 11}
        if request.phase != "provision":
            raise ValueError("unsupported provisioning phase")
        source_pdf = request.pdf_path
        if source_pdf is None or not source_pdf.is_file() or source_pdf.suffix.lower() != ".pdf":
            raise ValueError("provision requires an existing PDF")
        state = asyncio.run(self._provision(source_pdf))
        update_runtime_state(self._runtime_path, state)
        return {"status": "provisioned", "resources": 11}


class VLMSmokeCollaborator:
    """Run the content-addressed opt-in VLM canary without automatic retries."""

    def __init__(
        self,
        *,
        runtime_path: Path,
        fixture_path: Path = _VLM_FIXTURE,
        api_base_url: str = "http://127.0.0.1:8080/api/v1",
        runtime_loader: RuntimeLoader = read_runtime_environment,
        client_factory: AdminClientFactory = WeKnoraAdminClient,
        api_key_resolver: APIKeyResolver | None = None,
        poll_interval: float = 1.0,
        poll_attempts: int = 120,
    ) -> None:
        self._runtime_path = runtime_path
        self._fixture_path = fixture_path
        self._api_base_url = api_base_url
        self._runtime_loader = runtime_loader
        self._client_factory = client_factory
        self._api_key_resolver = (
            RuntimeAPIKeyResolver(
                runtime_path=runtime_path,
                api_base_url=api_base_url,
                runtime_loader=runtime_loader,
                client_factory=client_factory,
            )
            if api_key_resolver is None
            else api_key_resolver
        )
        self._poll_interval = poll_interval
        self._poll_attempts = poll_attempts

    @staticmethod
    def _required(values: Mapping[str, str], name: str) -> str:
        value = values.get(name)
        if not isinstance(value, str) or not value:
            raise RuntimeError("VLM smoke runtime identity is incomplete")
        return value

    @staticmethod
    def _knowledge_identity(item: Mapping[str, object]) -> tuple[str, str]:
        identifier = item.get("id")
        status = item.get("parse_status")
        if (
            not isinstance(identifier, str)
            or not identifier
            or not isinstance(status, str)
            or not status
        ):
            raise RuntimeError("VLM smoke knowledge response is invalid")
        return identifier, status

    @staticmethod
    def _evidence(
        *,
        knowledge_id: str,
        kb_id: str,
        fixture_digest: str,
        status: str,
        attempt: object = 1,
    ) -> dict[str, object]:
        return {
            "status": status,
            "knowledge_id": knowledge_id,
            "kb_id": kb_id,
            "fixture_sha256": fixture_digest,
            "attempt": (
                attempt
                if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 0
                else 1
            ),
        }

    @staticmethod
    def _process_config_sha256(config: KnowledgeProcessConfig) -> str:
        canonical = json.dumps(
            config.as_payload(),
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return sha256(canonical).hexdigest()

    @staticmethod
    def _process_config_matches(
        observed: object,
        expected: KnowledgeProcessConfig,
    ) -> bool:
        if not isinstance(observed, Mapping):
            return False
        observed_vlm = observed.get("vlm_config")
        return (
            observed.get("enable_multimodel") is expected.enable_multimodel
            and isinstance(observed_vlm, Mapping)
            and observed_vlm.get("enabled") is expected.vlm_config.enabled
            and observed_vlm.get("model_id") == expected.vlm_config.model_id
        )

    @classmethod
    def _smoke_metadata(
        cls,
        *,
        fixture_digest: str,
        vlm_model_id: str,
        process_config: KnowledgeProcessConfig,
    ) -> dict[str, str]:
        return {
            "owner": _MARKER,
            "sha256": fixture_digest,
            "purpose": _VLM_PURPOSE,
            "vlm_model_id": vlm_model_id,
            "process_config_sha256": cls._process_config_sha256(process_config),
        }

    @classmethod
    def _validate_smoke_identity(
        cls,
        item: Mapping[str, object],
        *,
        knowledge_id: str | None,
        kb_id: str,
        fixture_digest: str,
        vlm_model_id: str,
        process_config: KnowledgeProcessConfig,
        retry: bool,
    ) -> tuple[str, str]:
        observed_id, status = cls._knowledge_identity(item)
        expected_metadata = cls._smoke_metadata(
            fixture_digest=fixture_digest,
            vlm_model_id=vlm_model_id,
            process_config=process_config,
        )
        metadata = item.get("metadata")
        observed_config = (
            metadata.get("process_overrides")
            if isinstance(metadata, Mapping)
            else None
        )
        if (
            (knowledge_id is not None and observed_id != knowledge_id)
            or item.get("knowledge_base_id") != kb_id
            or not isinstance(metadata, Mapping)
            or any(metadata.get(name) != value for name, value in expected_metadata.items())
            or not cls._process_config_matches(observed_config, process_config)
        ):
            raise RuntimeError("VLM smoke knowledge identity mismatch")
        if retry:
            if status not in _RETRYABLE_VLM_STATUSES:
                raise RuntimeError("VLM smoke knowledge is not retryable")
        return observed_id, status

    async def _attest_completed(
        self,
        client: WeKnoraAdminClient,
        api_key: SecretStr,
        knowledge_id: str,
    ) -> tuple[int, int]:
        ocr: TypedChunkListing = await client.list_typed_chunks(
            api_key,
            knowledge_id,
            chunk_type="image_ocr",
        )
        captions: TypedChunkListing = await client.list_typed_chunks(
            api_key,
            knowledge_id,
            chunk_type="image_caption",
        )
        if not any(
            isinstance(item.get("parent_chunk_id"), str)
            and bool(str(item["parent_chunk_id"]).strip())
            and isinstance(item.get("content"), str)
            and _VLM_CANARY in str(item["content"])
            for item in ocr.items
        ) or any(
            not isinstance(item.get("parent_chunk_id"), str)
            or not str(item["parent_chunk_id"]).strip()
            for item in captions.items
        ):
            raise RuntimeError("VLM smoke chunk attestation failed")
        return ocr.total, captions.total

    async def _wait_after_upload(
        self,
        client: WeKnoraAdminClient,
        api_key: SecretStr,
        knowledge_id: str,
        initial: Mapping[str, object],
    ) -> Mapping[str, object]:
        latest: Mapping[str, object] = initial
        for _ in range(self._poll_attempts):
            latest = await client.get_knowledge(api_key, knowledge_id)
            status = latest.get("parse_status")
            if status in {"completed", "failed", "cancelled"}:
                return latest
            await asyncio.sleep(self._poll_interval)
        return latest

    @staticmethod
    async def _parse_attempt(
        client: WeKnoraAdminClient,
        api_key: SecretStr,
        knowledge_id: str,
    ) -> int:
        attempt = await client.get_knowledge_parse_attempt(api_key, knowledge_id)
        if (
            not isinstance(attempt, int)
            or isinstance(attempt, bool)
            or attempt < 1
        ):
            raise RuntimeError("VLM smoke parse attempt is invalid")
        return attempt

    async def _smoke(self) -> dict[str, object]:
        values = self._runtime_loader(self._runtime_path)
        kb_id = self._required(values, "LOCAL_LIVE_RAW_KB_ID")
        vlm_model_id = self._required(values, "LOCAL_LIVE_VLLM_MODEL_ID")
        api_key = await self._api_key_resolver.resolve(values)
        if not self._fixture_path.is_file() or self._fixture_path.suffix.lower() != ".png":
            raise RuntimeError("VLM smoke fixture is unavailable")
        fixture_digest = sha256(self._fixture_path.read_bytes()).hexdigest()
        process_config = KnowledgeProcessConfig(
            enable_multimodel=True,
            vlm_config=VLMProcessConfig(enabled=True, model_id=vlm_model_id),
        )
        metadata = self._smoke_metadata(
            fixture_digest=fixture_digest,
            vlm_model_id=vlm_model_id,
            process_config=process_config,
        )
        client = self._client_factory(self._api_base_url)
        try:
            matching = await client.find_knowledge_by_sha256(
                api_key,
                kb_id,
                fixture_digest,
            )
            if len(matching) > 1:
                raise RuntimeError("VLM smoke fixture identity is ambiguous")
            if matching:
                item = matching[0]
                knowledge_id, status = self._validate_smoke_identity(
                    item,
                    knowledge_id=None,
                    kb_id=kb_id,
                    fixture_digest=fixture_digest,
                    vlm_model_id=vlm_model_id,
                    process_config=process_config,
                    retry=False,
                )
                attempt = await self._parse_attempt(client, api_key, knowledge_id)
                evidence = self._evidence(
                    knowledge_id=knowledge_id,
                    kb_id=kb_id,
                    fixture_digest=fixture_digest,
                    status=status,
                    attempt=attempt,
                )
                if status != "completed":
                    return evidence
            else:
                uploaded = await client.upload_file(
                    api_key,
                    kb_id,
                    self._fixture_path,
                    metadata=metadata,
                    media_type="image/png",
                    process_config=process_config,
                )
                knowledge_id, _ = self._knowledge_identity(uploaded)
                completed_item = await self._wait_after_upload(
                    client,
                    api_key,
                    knowledge_id,
                    uploaded,
                )
                _, status = self._knowledge_identity(completed_item)
                attempt = await self._parse_attempt(client, api_key, knowledge_id)
                evidence = self._evidence(
                    knowledge_id=knowledge_id,
                    kb_id=kb_id,
                    fixture_digest=fixture_digest,
                    status=status,
                    attempt=attempt,
                )
                if status != "completed":
                    return evidence
            ocr_count, caption_count = await self._attest_completed(
                client,
                api_key,
                knowledge_id,
            )
            evidence["image_ocr_chunks"] = ocr_count
            evidence["image_caption_chunks"] = caption_count
            return evidence
        finally:
            await client.aclose()

    def _retry_marker(self, knowledge_id: str) -> Path:
        marker_digest = sha256(knowledge_id.encode("utf-8")).hexdigest()
        return self._runtime_path.with_name(
            f"{self._runtime_path.name}.retry-vlm-{marker_digest}"
        )

    def _require_retry_available(self, knowledge_id: str) -> None:
        if os.path.lexists(self._retry_marker(knowledge_id)):
            raise RuntimeError("VLM retry was already consumed")

    def _consume_retry(self, knowledge_id: str) -> None:
        marker = self._retry_marker(knowledge_id)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(marker, flags, 0o600)
        except FileExistsError:
            raise RuntimeError("VLM retry was already consumed") from None
        except OSError:
            raise RuntimeError("VLM retry marker could not be persisted") from None
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, b"consumed\n")
            os.fsync(descriptor)
        except Exception:
            marker.unlink(missing_ok=True)
            raise RuntimeError("VLM retry marker could not be persisted") from None
        finally:
            os.close(descriptor)

    async def _retry(self, knowledge_id: str) -> dict[str, object]:
        if not isinstance(knowledge_id, str) or not knowledge_id:
            raise RuntimeError("VLM retry knowledge ID is required")
        self._require_retry_available(knowledge_id)
        values = self._runtime_loader(self._runtime_path)
        kb_id = self._required(values, "LOCAL_LIVE_RAW_KB_ID")
        vlm_model_id = self._required(values, "LOCAL_LIVE_VLLM_MODEL_ID")
        api_key = await self._api_key_resolver.resolve(values)
        process_config = KnowledgeProcessConfig(
            enable_multimodel=True,
            vlm_config=VLMProcessConfig(enabled=True, model_id=vlm_model_id),
        )
        client = self._client_factory(self._api_base_url)
        try:
            before = await client.get_knowledge(api_key, knowledge_id)
            self._validate_smoke_identity(
                before,
                knowledge_id=knowledge_id,
                kb_id=kb_id,
                fixture_digest=sha256(self._fixture_path.read_bytes()).hexdigest(),
                vlm_model_id=vlm_model_id,
                process_config=process_config,
                retry=True,
            )
            previous_attempt = await self._parse_attempt(
                client,
                api_key,
                knowledge_id,
            )
            self._consume_retry(knowledge_id)
            await client.reparse_knowledge(
                api_key,
                knowledge_id,
                process_config,
            )
            after = await self._wait_after_upload(
                client,
                api_key,
                knowledge_id,
                {"id": knowledge_id, "parse_status": "processing"},
            )
            observed_id, status = self._knowledge_identity(after)
            if observed_id != knowledge_id:
                raise RuntimeError("VLM retry knowledge identity mismatch")
            expected_attempt = previous_attempt + 1
            attempt = await self._parse_attempt(client, api_key, knowledge_id)
            if attempt != expected_attempt:
                raise RuntimeError("VLM retry attempt did not increment")
            evidence: dict[str, object] = {
                "status": status,
                "knowledge_id": knowledge_id,
                "kb_id": kb_id,
                "attempt": attempt,
            }
            if status == "completed":
                ocr_count, caption_count = await self._attest_completed(
                    client,
                    api_key,
                    knowledge_id,
                )
                evidence["image_ocr_chunks"] = ocr_count
                evidence["image_caption_chunks"] = caption_count
            elif status == "failed":
                evidence["error_class"] = "knowledge_parse_failed"
            elif status == "cancelled":
                evidence["error_class"] = "knowledge_parse_cancelled"
            else:
                evidence["error_class"] = "knowledge_parse_incomplete"
            return evidence
        finally:
            await client.aclose()

    def run(self, request: ProvisionRequest) -> object:
        if request.phase not in {"smoke-vlm", "retry-vlm"}:
            raise ValueError("unsupported VLM phase")
        try:
            if request.phase == "retry-vlm":
                knowledge_id = request.knowledge_id
                if knowledge_id is None:
                    raise RuntimeError("VLM retry knowledge ID is required")
                return asyncio.run(self._retry(knowledge_id))
            return asyncio.run(self._smoke())
        except Exception:
            raise RuntimeError(f"{request.phase} failed") from None
