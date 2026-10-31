"""OpenSpec 023 R3.1/R3.2 ownership-safe local-live provisioning: shared module loader and fakes."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

import pytest


def _provision_module() -> Any:
    try:
        return import_module("insurance_harness.live_env.provision")
    except ModuleNotFoundError:
        pytest.fail("R3.1/R3.2 provisioner is missing")


class FakeBackend:
    def __init__(self) -> None:
        self.resources: list[Any] = []
        self.knowledge: list[Any] = []
        self.pages: list[Any] = []
        self.created: list[str] = []
        self.uploaded_to: list[str] = []

    async def list_resources(self, kind: str) -> list[Any]:
        return [resource for resource in self.resources if resource.kind == kind]

    async def create_resource(self, desired: Any) -> Any:
        module = _provision_module()
        record = module.OwnedResource(
            id=f"{desired.kind}-{len(self.resources) + 1}",
            kind=desired.kind,
            name=desired.name,
            tenant_id=desired.tenant_id,
            marker=desired.marker,
            role=desired.role,
            dimension=desired.dimension,
            model_type=desired.model_type,
            provider=desired.provider,
            model_name=desired.model_name,
            endpoint_fingerprint=desired.endpoint_fingerprint,
            supports_vision=desired.supports_vision,
            embedding_model_id=desired.embedding_model_id,
            vlm_enabled=desired.vlm_enabled,
            vlm_model_id=desired.vlm_model_id,
            capabilities=desired.capabilities,
            knowledge_base_ids=desired.knowledge_base_ids,
        )
        self.resources.append(record)
        self.created.append(desired.kind)
        return record

    async def list_knowledge(self, kb_id: str) -> list[Any]:
        return [item for item in self.knowledge if item.kb_id == kb_id]

    async def upload_pdf(self, kb_id: str, path: Path, digest: str, marker: str) -> Any:
        module = _provision_module()
        self.uploaded_to.append(kb_id)
        record = module.KnowledgeRecord(
            id=f"knowledge-{len(self.knowledge) + 1}",
            kb_id=kb_id,
            sha256=digest,
            status="processing",
            chunk_count=0,
            marker=marker,
        )
        self.knowledge.append(record)
        return record

    async def wait_completed(self, knowledge_id: str) -> Any:
        module = _provision_module()
        current = next(item for item in self.knowledge if item.id == knowledge_id)
        completed = module.KnowledgeRecord(
            id=current.id,
            kb_id=current.kb_id,
            sha256=current.sha256,
            status="completed",
            chunk_count=2,
            marker=current.marker,
        )
        self.knowledge[self.knowledge.index(current)] = completed
        return completed

    async def list_wiki_pages(self, kb_id: str) -> list[Any]:
        return [page for page in self.pages if page.kb_id == kb_id]


def _plan(pdf: Path) -> Any:
    module = _provision_module()
    return module.ProvisionPlan(
        marker="insurancekb-local-live-v1",
        tenant_name="insurancekb-local-live",
        chat_model="MiniMax-M2.5",
        embedding_model="Qwen3-VL-Embedding-8B",
        rerank_model="Qwen3-VL-Reranker-8B",
        vlm_model="qwen3.7-plus",
        embedding_dimension=3,
        raw_kb_name="KB-RAW",
        wiki_kb_name="KB-WIKI",
        api_key_name="insurancekb-live-contributor",
        space_name="insurancekb-live-space",
        pdf_path=pdf,
    )
