from __future__ import annotations

# ruff: noqa: F811 -- fixture imports are intentionally reused by pytest.
import json
import typing

import pytest
from sqlalchemy import select

from insurance_harness.jobs import JobState
from insurance_harness.product_ingestion.artifact_tables import ProductArtifact
from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.upload_manifest import UploadManifest
from tests.product_ingestion.test_api import PATH, auth, environment  # noqa: F401
from tests.product_ingestion.test_platform import snapshot  # noqa: F401
from tests.product_ingestion.test_routing import catalog  # noqa: F401
from tests.product_ingestion.test_stages import stage_runtime  # noqa: F401


def manifest(count: int = 1) -> dict[str, typing.Any]:
    return {
        "contract": "product-upload-manifest.830.g3.v1",
        "materials": [
            {
                "ordinal": i,
                "original_filename": f"{i}.pdf",
                "file_size": 4,
                "file_sha256": f"{i + 1:064x}",
            }
            for i in range(count)
        ],
        "duplicate_upload_count": 0,
    }


def test_manifest_is_durable_before_upload_and_idempotency_rejects_changes(
    environment: typing.Any,
) -> None:  # noqa: F811
    client, factory, *_ = environment
    request: dict[str, typing.Any] = {
        "idempotency_key": "manifest",
        "expected_upload_count": 1,
        "upload_manifest": manifest(),
    }
    response = client.post(PATH, headers=auth(), json=request)
    assert response.status_code == 201, response.text
    with factory() as session:
        row = session.scalar(
            select(ProductArtifact).where(ProductArtifact.artifact_kind == "upload_manifest")
        )
        assert row is not None
        assert json.loads(row.payload) == manifest()
        assert row.producer_generation == 0  # Admission input, not a worker result.
    assert client.post(PATH, headers=auth(), json=request).status_code == 201
    request["upload_manifest"]["materials"][0]["file_sha256"] = "f" * 64
    assert client.post(PATH, headers=auth(), json=request).status_code == 409


def test_duplicate_upload_attaches_and_sources_resolve_existing_original(
    stage_runtime: typing.Any,
) -> None:  # noqa: F811
    scope, store, _artifacts, platform, execute = stage_runtime
    incoming = UploadManifest.model_validate_json(json.dumps(manifest(3)))
    run = store.create_run(
        scope=scope,
        idempotency_key="duplicate-manifest",
        expected_upload_count=3,
        upload_manifest=incoming,
    )
    calls: list[tuple[int, str | None]] = []

    async def missing(*_args: object) -> None:
        return None

    async def fingerprint(
        _scope: object, sha: typing.Any, *, knowledge_id: str | None = None
    ) -> dict[str, typing.Any]:
        ordinal = int(sha, 16) - 1
        calls.append((ordinal, knowledge_id))
        return {
            "contract": "g3-platform-file-fingerprint.830.v1",
            "knowledge_id": f"knowledge-{ordinal}",
            "file_name": f"old-{ordinal}.pdf",
            "file_sha256": sha,
            "file_size": 4,
            "type": "file",
            "parse_attempt": 1,
            "parse_status": "completed",
            "original_upload_run_id": "existing-upload-run",
            "original_upload_ordinal": ordinal,
        }

    platform.lookup_upload = missing
    platform.lookup_file_by_sha256 = fingerprint
    for _ in range(2):
        assert execute(run).state is JobState.SUCCEEDED
    assert len(store.get_run(scope=scope, run_id=run.run_id).materials) == 3
    assert [
        m.original_filename for m in store.get_run(scope=scope, run_id=run.run_id).materials
    ] == [f"{i}.pdf" for i in range(3)]
    assert calls[:3] == [(i, None) for i in range(3)]
    assert calls[3:] == [(i, f"knowledge-{i}") for i in range(3)]


def test_manifest_count_mismatch_does_not_admit_run(environment: typing.Any) -> None:  # noqa: F811
    client, *_ = environment
    response = client.post(
        PATH,
        headers=auth(),
        json={
            "idempotency_key": "bad-manifest",
            "expected_upload_count": 2,
            "upload_manifest": manifest(1),
        },
    )
    assert response.status_code in {409, 422}
    assert client.get(PATH, headers=auth()).json()["data"]["runs"] == []


def test_unbound_reused_original_does_not_invent_new_upload_binding() -> None:
    import asyncio
    from types import SimpleNamespace

    from insurance_harness.product_ingestion.upload_resolution import lookup_material

    async def missing(*_args: object) -> None:
        return None

    async def fingerprint(*_args: object, **_kwargs: object) -> dict[str, typing.Any]:
        return {
            "knowledge_id": "legacy",
            "file_sha256": "0" * 63 + "1",
            "file_size": 4,
            "type": "file",
            "parse_status": "failed",
        }

    result = asyncio.run(
        lookup_material(
            SimpleNamespace(lookup_upload=missing, lookup_file_by_sha256=fingerprint),
            ProductScope(
                tenant_id="tenant",
                space_id="space",
                raw_knowledge_base_id="raw",
                wiki_knowledge_base_id="wiki",
            ),
            "new-run",
            0,
            UploadManifest.model_validate_json(json.dumps(manifest())),
            knowledge_id="legacy",
        )
    )
    assert result is not None
    assert "original_upload_run_id" in result
    assert result["original_upload_run_id"] is None
    assert result["original_upload_ordinal"] is None


@pytest.mark.parametrize("failure", [AttributeError("missing port"), TypeError("bad adapter")])
def test_local_stage_contract_error_has_terminal_instead_of_repeated_dispatch(
    stage_runtime: typing.Any,
    failure: typing.Any,  # noqa: F811 -- imported pytest fixture
) -> None:
    scope, store, _artifacts, platform, execute = stage_runtime
    run = store.create_run(
        scope=scope, idempotency_key="local-contract-failure", expected_upload_count=1
    )
    calls = []

    async def broken(*_args: object) -> None:
        calls.append("lookup")
        raise failure

    platform.lookup_upload = broken
    result = execute(run)
    assert result.state is JobState.DEAD_LETTER
    assert calls == ["lookup"]
