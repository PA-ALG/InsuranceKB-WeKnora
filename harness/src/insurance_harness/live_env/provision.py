"""Ownership-safe domain orchestration for the local WeKnora environment."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Protocol, runtime_checkable


class OwnershipMismatch(RuntimeError):
    """A stable name belongs to a different environment or role."""


@dataclass(frozen=True)
class OwnedResource:
    id: str
    kind: str
    name: str
    tenant_id: str
    marker: str
    role: str
    dimension: int | None = None
    capabilities: tuple[str, ...] = ()
    knowledge_base_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DesiredResource:
    kind: str
    name: str
    tenant_id: str
    marker: str
    role: str
    dimension: int | None = None
    capabilities: tuple[str, ...] = ()
    knowledge_base_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeRecord:
    id: str
    kb_id: str
    sha256: str
    status: str
    chunk_count: int
    marker: str


@dataclass(frozen=True)
class WikiPageRecord:
    id: str
    kb_id: str
    marker: str


@dataclass(frozen=True)
class ProvisionPlan:
    marker: str
    tenant_name: str
    chat_model: str
    embedding_model: str
    rerank_model: str
    embedding_dimension: int
    raw_kb_name: str
    wiki_kb_name: str
    api_key_name: str
    space_name: str
    pdf_path: Path


@dataclass(frozen=True)
class ProvisionedEnvironment:
    tenant_id: str
    chat_model_id: str
    embedding_model_id: str
    rerank_model_id: str
    raw_kb_id: str
    wiki_kb_id: str
    api_key_id: str
    space_id: str
    knowledge: KnowledgeRecord


class ProvisioningBackend(Protocol):
    async def list_resources(self, kind: str) -> Sequence[OwnedResource]: ...

    async def create_resource(self, desired: DesiredResource) -> OwnedResource: ...

    async def list_knowledge(self, kb_id: str) -> Sequence[KnowledgeRecord]: ...

    async def upload_pdf(
        self,
        kb_id: str,
        path: Path,
        digest: str,
        marker: str,
    ) -> KnowledgeRecord: ...

    async def wait_completed(self, knowledge_id: str) -> KnowledgeRecord: ...

    async def list_wiki_pages(self, kb_id: str) -> Sequence[WikiPageRecord]: ...


class SpaceBackend(Protocol):
    async def list_resources(self, kind: str) -> Sequence[OwnedResource]: ...

    async def create_resource(self, desired: DesiredResource) -> OwnedResource: ...


@runtime_checkable
class TenantSelectable(Protocol):
    async def select_tenant(self, tenant_id: str) -> None: ...


@runtime_checkable
class ResourceSelectable(Protocol):
    async def select_resource(self, resource: OwnedResource) -> None: ...


def _same_resource(existing: OwnedResource, desired: DesiredResource) -> bool:
    return (
        existing.kind == desired.kind
        and existing.name == desired.name
        and existing.tenant_id == desired.tenant_id
        and existing.marker == desired.marker
        and existing.role == desired.role
        and existing.dimension == desired.dimension
        and existing.capabilities == desired.capabilities
        and existing.knowledge_base_ids == desired.knowledge_base_ids
    )


async def _ensure_resource(
    backend: SpaceBackend,
    desired: DesiredResource,
) -> OwnedResource:
    named = [
        resource
        for resource in await backend.list_resources(desired.kind)
        if resource.name == desired.name
    ]
    if len(named) > 1 or (named and not _same_resource(named[0], desired)):
        raise OwnershipMismatch(f"{desired.kind} ownership mismatch")
    if named:
        selected = named[0]
        if isinstance(backend, ResourceSelectable):
            await backend.select_resource(selected)
        return selected
    created = await backend.create_resource(desired)
    if not _same_resource(created, desired):
        raise OwnershipMismatch(f"{desired.kind} create attestation mismatch")
    if isinstance(backend, ResourceSelectable):
        await backend.select_resource(created)
    return created


def _desired(
    kind: str,
    name: str,
    tenant_id: str,
    marker: str,
    *,
    role: str,
    dimension: int | None = None,
    capabilities: tuple[str, ...] = (),
    knowledge_base_ids: tuple[str, ...] = (),
) -> DesiredResource:
    return DesiredResource(
        kind=kind,
        name=name,
        tenant_id=tenant_id,
        marker=marker,
        role=role,
        dimension=dimension,
        capabilities=capabilities,
        knowledge_base_ids=knowledge_base_ids,
    )


async def _ensure_pdf(
    backend: ProvisioningBackend,
    plan: ProvisionPlan,
    raw_kb_id: str,
) -> KnowledgeRecord:
    digest = sha256(plan.pdf_path.read_bytes()).hexdigest()
    matching = [item for item in await backend.list_knowledge(raw_kb_id) if item.sha256 == digest]
    if len(matching) > 1:
        raise OwnershipMismatch("PDF SHA ownership mismatch")
    if matching:
        item = matching[0]
        if (
            item.kb_id != raw_kb_id
            or item.marker != plan.marker
            or item.status != "completed"
            or item.chunk_count <= 0
        ):
            raise OwnershipMismatch("PDF SHA ownership mismatch")
        return item
    uploaded = await backend.upload_pdf(raw_kb_id, plan.pdf_path, digest, plan.marker)
    if uploaded.kb_id != raw_kb_id or uploaded.sha256 != digest or uploaded.marker != plan.marker:
        raise OwnershipMismatch("PDF upload attestation mismatch")
    completed = await backend.wait_completed(uploaded.id)
    if (
        completed.id != uploaded.id
        or completed.kb_id != raw_kb_id
        or completed.sha256 != digest
        or completed.marker != plan.marker
        or completed.status != "completed"
        or completed.chunk_count <= 0
    ):
        raise OwnershipMismatch("PDF did not complete with nonempty chunks")
    return completed


async def provision_local_live(
    backend: ProvisioningBackend,
    plan: ProvisionPlan,
    *,
    space_backend: SpaceBackend | None = None,
) -> ProvisionedEnvironment:
    tenant = await _ensure_resource(
        backend,
        _desired("tenant", plan.tenant_name, "", plan.marker, role="tenant"),
    )
    if isinstance(backend, TenantSelectable):
        await backend.select_tenant(tenant.id)
    models: dict[str, OwnedResource] = {}
    for role, name, dimension in (
        ("chat", plan.chat_model, None),
        ("embedding", plan.embedding_model, plan.embedding_dimension),
        ("rerank", plan.rerank_model, None),
    ):
        models[role] = await _ensure_resource(
            backend,
            _desired(
                f"model:{role}",
                name,
                tenant.id,
                plan.marker,
                role=role,
                dimension=dimension,
            ),
        )
    raw = await _ensure_resource(
        backend,
        _desired(
            "kb:raw",
            plan.raw_kb_name,
            tenant.id,
            plan.marker,
            role="raw",
            dimension=plan.embedding_dimension,
        ),
    )
    wiki = await _ensure_resource(
        backend,
        _desired(
            "kb:wiki",
            plan.wiki_kb_name,
            tenant.id,
            plan.marker,
            role="wiki",
            dimension=plan.embedding_dimension,
        ),
    )
    kb_ids = (raw.id, wiki.id)
    api_key = await _ensure_resource(
        backend,
        _desired(
            "api-key",
            f"{plan.api_key_name}::owner={plan.marker}",
            tenant.id,
            plan.marker,
            role="contributor",
            capabilities=("retrieve", "ingest"),
            knowledge_base_ids=kb_ids,
        ),
    )
    space = await _ensure_resource(
        backend if space_backend is None else space_backend,
        _desired(
            "space",
            plan.space_name,
            tenant.id,
            plan.marker,
            role="bound",
            knowledge_base_ids=kb_ids,
        ),
    )
    pages = await backend.list_wiki_pages(wiki.id)
    if any(page.kb_id != wiki.id or page.marker != plan.marker for page in pages):
        raise OwnershipMismatch("wiki page ownership mismatch")
    knowledge = await _ensure_pdf(backend, plan, raw.id)
    return ProvisionedEnvironment(
        tenant_id=tenant.id,
        chat_model_id=models["chat"].id,
        embedding_model_id=models["embedding"].id,
        rerank_model_id=models["rerank"].id,
        raw_kb_id=raw.id,
        wiki_kb_id=wiki.id,
        api_key_id=api_key.id,
        space_id=space.id,
        knowledge=knowledge,
    )
