"""Local-live provisioning: owned resource graph reuse, Space backends and fingerprints."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from insurance_harness.db.models import KnowledgeSpace
from tests.service_shell.local_provisioning.helpers import FakeBackend, _plan, _provision_module


async def test_r3_1_repeat_provision_reuses_exact_owned_resource_graph(tmp_path: Path) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"same life insurance PDF")
    backend = FakeBackend()
    module = _provision_module()

    first = await module.provision_local_live(backend, _plan(pdf))
    created_once = list(backend.created)
    second = await module.provision_local_live(backend, _plan(pdf))

    assert second == first
    assert backend.created == created_once
    assert {resource.kind for resource in backend.resources} == {
        "tenant",
        "model:chat",
        "model:embedding",
        "model:rerank",
        "model:vlm",
        "kb:raw",
        "kb:wiki",
        "api-key",
        "space",
    }
    assert {
        resource.role: resource.supports_vision
        for resource in backend.resources
        if resource.kind.startswith("model:")
    } == {
        "chat": False,
        "embedding": False,
        "rerank": False,
        "vlm": True,
    }
    api_key = next(resource for resource in backend.resources if resource.kind == "api-key")
    assert api_key.role == "contributor"
    assert api_key.name == (
        "insurancekb-live-contributor::owner=insurancekb-local-live-v1"
    )
    assert api_key.capabilities == ("retrieve", "ingest")
    assert api_key.knowledge_base_ids == (first.raw_kb_id, first.wiki_kb_id)


async def test_r3_1_stable_name_with_wrong_ownership_fails_closed(tmp_path: Path) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"life insurance PDF")
    backend = FakeBackend()
    module = _provision_module()
    backend.resources.append(
        module.OwnedResource(
            id="tenant-other",
            kind="tenant",
            name="insurancekb-local-live",
            tenant_id="other",
            marker="someone-else",
            role="tenant",
        )
    )

    with pytest.raises(module.OwnershipMismatch, match="tenant"):
        await module.provision_local_live(backend, _plan(pdf))

    assert backend.created == []


async def test_r3_1_embedding_dimension_mismatch_fails_closed(tmp_path: Path) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"life insurance PDF")
    backend = FakeBackend()
    module = _provision_module()
    plan = _plan(pdf)
    await module.provision_local_live(backend, plan)

    with pytest.raises(module.OwnershipMismatch, match="model:embedding"):
        await module.provision_local_live(
            backend,
            replace(plan, embedding_dimension=plan.embedding_dimension + 1),
        )


async def test_r3_1_space_backend_is_injected_not_weknora_rest(tmp_path: Path) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"life insurance PDF")
    weknora = FakeBackend()
    spaces = FakeBackend()
    module = _provision_module()

    result = await module.provision_local_live(weknora, _plan(pdf), space_backend=spaces)

    assert result.space_id.startswith("space-")
    assert "space" not in weknora.created
    assert spaces.created == ["space"]


async def test_r3_1_harness_space_backend_persists_owned_binding(
    tmp_path: Path,
) -> None:
    try:
        space_module = import_module("insurance_harness.live_env.space")
    except ModuleNotFoundError:
        pytest.fail("R3.1 Harness KnowledgeSpace backend is missing")
    engine = create_engine(f"sqlite:///{tmp_path / 'space.db'}")
    cast(Table, KnowledgeSpace.__table__).create(engine)
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
    plan = _plan(tmp_path / "policy.pdf")
    plan.pdf_path.write_bytes(b"life insurance PDF")
    weknora = FakeBackend()
    spaces = space_module.HarnessSpaceBackend(factory, marker=plan.marker)

    first = await _provision_module().provision_local_live(
        weknora,
        plan,
        space_backend=spaces,
    )
    second = await _provision_module().provision_local_live(
        weknora,
        plan,
        space_backend=spaces,
    )

    assert first.space_id == second.space_id
    with factory() as session:
        row = session.get(KnowledgeSpace, first.space_id)
        assert row is not None
        assert row.name == plan.space_name
        assert row.binding_status == "bound"
        assert row.tenant_id == first.tenant_id
        assert row.raw_kb_id == first.raw_kb_id
        assert row.wiki_kb_id == first.wiki_kb_id
        assert session.scalar(select(func.count()).select_from(KnowledgeSpace)) == 1
    engine.dispose()


async def test_r3_1_harness_space_backend_rejects_foreign_same_name(
    tmp_path: Path,
) -> None:
    space_module = import_module("insurance_harness.live_env.space")
    module = _provision_module()
    engine = create_engine(f"sqlite:///{tmp_path / 'space.db'}")
    cast(Table, KnowledgeSpace.__table__).create(engine)
    factory: sessionmaker[Session] = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
    plan = _plan(tmp_path / "policy.pdf")
    plan.pdf_path.write_bytes(b"life insurance PDF")
    with factory() as session:
        session.add(
            KnowledgeSpace(
                id="foreign-space-id",
                name=plan.space_name,
                binding_status="bound",
                tenant_id="foreign-tenant",
                raw_kb_id="foreign-raw",
                wiki_kb_id="foreign-wiki",
            )
        )
        session.commit()

    with pytest.raises(module.OwnershipMismatch, match="space"):
        await module.provision_local_live(
            FakeBackend(),
            plan,
            space_backend=space_module.HarnessSpaceBackend(
                factory,
                marker=plan.marker,
            ),
        )

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(KnowledgeSpace)) == 1
    engine.dispose()


async def test_r3_2_pdf_sha_reuse_upload_once_and_wiki_unknown_fail_closed(
    tmp_path: Path,
) -> None:
    pdf = tmp_path / "policy.pdf"
    pdf.write_bytes(b"life insurance PDF")
    backend = FakeBackend()
    module = _provision_module()
    first = await module.provision_local_live(backend, _plan(pdf))
    assert backend.uploaded_to == [first.raw_kb_id]
    assert first.knowledge.chunk_count > 0

    second = await module.provision_local_live(backend, _plan(pdf))
    assert second.knowledge.id == first.knowledge.id
    assert backend.uploaded_to == [first.raw_kb_id]
    assert first.wiki_kb_id not in backend.uploaded_to

    changed_pdf = tmp_path / "changed.pdf"
    changed_pdf.write_bytes(b"a different life insurance PDF")
    changed = await module.provision_local_live(backend, replace(_plan(pdf), pdf_path=changed_pdf))
    assert changed.knowledge.id != first.knowledge.id
    assert backend.uploaded_to == [first.raw_kb_id, first.raw_kb_id]

    backend.pages.append(
        module.WikiPageRecord(id="unknown", kb_id=first.wiki_kb_id, marker="foreign")
    )
    with pytest.raises(module.OwnershipMismatch, match="wiki"):
        await module.provision_local_live(backend, _plan(pdf))


@pytest.mark.parametrize(
    ("url", "canonical"),
    (
        ("HTTPS://Models.Example:443", "https://models.example/"),
        (
            "https://Models.Example:443/compatible-mode/%7e/",
            "https://models.example/compatible-mode/%7E",
        ),
        ("http://Models.Example:80/v1/", "http://models.example/v1"),
    ),
)
def test_r3_3_canonical_endpoint_fingerprint_normalizes_safe_urls(
    url: str,
    canonical: str,
) -> None:
    module = _provision_module()

    assert module.canonical_endpoint_fingerprint(url) == sha256(
        canonical.encode()
    ).hexdigest()


@pytest.mark.parametrize(
    "url",
    (
        "https://user:password@models.example/v1",
        "https://models.example/v1?api_key=secret",
        "https://models.example/v1#fragment",
        "https://models.example?",
        "https://models.example#",
        "https://models.example/v1/../private",
        "https://models.example/v1//embeddings",
        "https://models.example/v1/%2e%2e/private",
        "https://models.example/v1/%not-hex",
    ),
)
def test_r3_3_canonical_endpoint_fingerprint_rejects_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValueError, match="endpoint URL"):
        _provision_module().canonical_endpoint_fingerprint(url)
