"""OpenSpec 047: bounded S0-Q input and diagnostic contracts."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
import respx
from pydantic import SecretStr

import insurance_harness.s0q_047 as s0q
from insurance_harness.adapters.weknora import admin_client as admin
from insurance_harness.adapters.weknora.admin_client import WeKnoraAdminClient

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64


def _revision_data() -> dict[str, object]:
    return {
        "knowledge_id": "knowledge-1",
        "parse_attempt": 3,
        "file_digest": {"algorithm": "sha256", "value": _DIGEST_A},
        "parser_identity": {
            "app_version": "v0.7.1",
            "app_commit": "80a5003cc99a427098afe184eee6601916d3d156",
            "docreader": "docreader@sha256:1234",
            "parser_engine": "docreader",
            "chunk_size": 512,
            "chunk_overlap": 64,
            "separators_digest": _DIGEST_B,
            "chunker_config_digest": _DIGEST_C,
            "embedding_model_id": "embedding-fixed",
        },
        "chunk_manifest": {
            "algorithm": "weknora.chunk_manifest.v1",
            "digest": _DIGEST_B,
            "chunk_count": 2,
        },
        "completed_at": "2026-07-30T10:00:00Z",
    }


@respx.mock
async def test_s0q_reads_typed_w1_revision_descriptor() -> None:
    route = respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/revision"
    ).respond(json={"success": True, "data": _revision_data()})
    client = WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        descriptor = await client.get_knowledge_revision(
            SecretStr("reader-key"),
            "knowledge-1",
        )
    finally:
        await client.aclose()

    assert route.call_count == 1
    assert descriptor.knowledge_id == "knowledge-1"
    assert descriptor.parse_attempt == 3
    assert descriptor.file_digest.value == _DIGEST_A
    assert descriptor.parser_identity.app_commit.startswith("80a5003")
    assert descriptor.chunk_manifest.algorithm == "weknora.chunk_manifest.v1"
    assert descriptor.chunk_manifest.chunk_count == 2


@respx.mock
async def test_s0q_revision_descriptor_rejects_missing_parser_identity() -> None:
    data = _revision_data()
    parser_identity = data["parser_identity"]
    assert isinstance(parser_identity, dict)
    parser_identity.pop("app_commit")
    respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/revision"
    ).respond(json={"success": True, "data": data})
    client = WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        with pytest.raises(ValueError, match="revision descriptor"):
            await client.get_knowledge_revision(
                SecretStr("reader-key"),
                "knowledge-1",
            )
    finally:
        await client.aclose()


def _chunk(
    *,
    chunk_id: str,
    chunk_index: int,
    attempt: int = 3,
) -> dict[str, object]:
    return {
        "id": chunk_id,
        "knowledge_id": "knowledge-1",
        "parse_attempt": attempt,
        "chunk_index": chunk_index,
        "content": f"content-{chunk_index}",
    }


def _chunk_page(
    *,
    page: int,
    items: list[dict[str, object]],
    attempt: int = 3,
) -> dict[str, object]:
    return {
        "success": True,
        "data": items,
        "total": 2,
        "page": page,
        "page_size": 1,
        "revision": {
            "knowledge_id": "knowledge-1",
            "parse_attempt": attempt,
            "manifest_digest": _DIGEST_B,
            "chunk_count": 2,
        },
    }


@respx.mock
async def test_s0q_walks_all_exact_attempt_chunk_pages() -> None:
    route = respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/revisions/3/chunks"
    ).mock(
        side_effect=[
            httpx.Response(
                200,
                json=_chunk_page(
                    page=1,
                    items=[_chunk(chunk_id="c1", chunk_index=0)],
                ),
            ),
            httpx.Response(
                200,
                json=_chunk_page(
                    page=2,
                    items=[_chunk(chunk_id="c2", chunk_index=1)],
                ),
            ),
        ]
    )
    client = WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        listing = await client.list_knowledge_revision_chunks(
            SecretStr("reader-key"),
            "knowledge-1",
            parse_attempt=3,
            page_size=1,
        )
    finally:
        await client.aclose()

    assert route.call_count == 2
    assert listing.revision.parse_attempt == 3
    assert listing.revision.chunk_count == listing.total == 2
    assert [item["id"] for item in listing.items] == ["c1", "c2"]


@respx.mock
async def test_s0q_rejects_cross_attempt_chunk_page() -> None:
    respx.get(
        "https://weknora.example/api/v1/knowledge/knowledge-1/revisions/3/chunks"
    ).mock(
        side_effect=[
            httpx.Response(
                200,
                json=_chunk_page(
                    page=1,
                    items=[_chunk(chunk_id="c1", chunk_index=0)],
                ),
            ),
            httpx.Response(
                200,
                json=_chunk_page(
                    page=2,
                    items=[_chunk(chunk_id="c2", chunk_index=1, attempt=4)],
                    attempt=4,
                ),
            ),
        ]
    )
    client = WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        with pytest.raises(ValueError, match="revision chunk response"):
            await client.list_knowledge_revision_chunks(
                SecretStr("reader-key"),
                "knowledge-1",
                parse_attempt=3,
                page_size=1,
            )
    finally:
        await client.aclose()


@respx.mock
async def test_s0q_deletes_only_the_exact_scratch_knowledge_base_id() -> None:
    route = respx.delete(
        "https://weknora.example/api/v1/knowledge-bases/s0q-scratch-047"
    ).respond(json={"success": True})
    client = WeKnoraAdminClient("https://weknora.example/api/v1")
    try:
        await client.delete_knowledge_base(
            SecretStr("admin-key"),
            "s0q-scratch-047",
        )
    finally:
        await client.aclose()

    assert route.call_count == 1
    request = route.calls[0].request
    assert isinstance(request.headers, Mapping)
    assert request.headers["X-API-Key"] == "admin-key"


def _reference_manifest_digest(
    chunks: list[dict[str, object]],
    *,
    knowledge_id: str = "knowledge-1",
    parse_attempt: int = 3,
) -> str:
    lines = [
        "weknora.chunk_manifest",
        "v1",
        knowledge_id,
        str(parse_attempt),
        str(len(chunks)),
    ]
    for chunk in chunks:
        content = chunk["content"]
        assert isinstance(content, str)
        lines.append(
            f"{chunk['chunk_index']}:{chunk['id']}:"
            f"{sha256(content.encode()).hexdigest()}"
        )
    return sha256(("\n".join(lines) + "\n").encode()).hexdigest()


def _bundle_payload() -> dict[str, object]:
    chunks: list[dict[str, object]] = [
        {
            "id": "chunk-1",
            "knowledge_id": "knowledge-1",
            "parse_attempt": 3,
            "chunk_index": 0,
            "content": "本合同为不保证续保合同。",
            "start_at": 0,
            "end_at": 13,
            "page_number": 30,
            "structural_type": "text",
        },
        {
            "id": "chunk-2",
            "knowledge_id": "knowledge-1",
            "parse_attempt": 3,
            "chunk_index": 1,
            "content": "计划一免赔额10000元；计划二免赔额0元。",
            "start_at": 14,
            "end_at": 36,
            "page_number": 31,
            "structural_type": "table",
        },
    ]
    return {
        "artifact_kind": "weknora_w1_exact_revision",
        "capture_state": "completed",
        "text_origin": "w1_exact_attempt_chunks",
        "source_path": "dataset/source/terms.pdf",
        "source_bytes": 1234,
        "source_sha256": _DIGEST_A,
        "knowledge_id": "knowledge-1",
        "parse_attempt": 3,
        "parser_identity": _revision_data()["parser_identity"],
        "completed_at": "2026-07-30T10:00:00Z",
        "manifest": {
            "algorithm": "weknora.chunk_manifest.v1",
            "digest": _reference_manifest_digest(chunks),
            "chunk_count": 2,
        },
        "chunks": chunks,
        "anchors": [
            {
                "page_number": 30,
                "chunk_id": "chunk-1",
                "quote": "不保证续保",
                "structural_type": "text",
            },
            {
                "page_number": 31,
                "chunk_id": "chunk-2",
                "quote": "计划一免赔额10000元",
                "structural_type": "table",
            },
        ],
    }


def test_s0q_canonical_json_is_mapping_order_independent() -> None:
    left = {"b": 2, "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "b": 2}

    assert s0q.canonical_json_bytes(left) == s0q.canonical_json_bytes(right)
    assert s0q.canonical_sha256(left) == s0q.canonical_sha256(right)


def test_s0q_admits_complete_digest_bound_w1_bundle() -> None:
    bundle = s0q.admit_frozen_w1_bundle(
        _bundle_payload(),
        expected_source_path="dataset/source/terms.pdf",
        expected_source_sha256=_DIGEST_A,
        required_table_page=31,
    )

    assert bundle.parse_attempt == 3
    assert bundle.manifest.chunk_count == len(bundle.chunks) == 2
    assert len(bundle.bundle_digest) == 64
    with pytest.raises(Exception, match="frozen"):
        bundle.source_path = "other.pdf"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda payload: payload["parser_identity"].pop("app_commit"),
            "parser identity",
        ),
        (
            lambda payload: payload["manifest"].__setitem__("digest", _DIGEST_C),
            "manifest digest",
        ),
        (
            lambda payload: payload["chunks"].reverse(),
            "chunk order",
        ),
        (
            lambda payload: payload["anchors"][1].__setitem__("quote", "不存在的引文"),
            "anchor",
        ),
    ],
)
def test_s0q_bundle_failures_are_typed_blocked_on_input(
    mutate: object,
    reason: str,
) -> None:
    payload = _bundle_payload()
    assert callable(mutate)
    mutate(payload)

    with pytest.raises(s0q.S0QBlockedOnInput, match=reason) as exc_info:
        s0q.admit_frozen_w1_bundle(
            payload,
            expected_source_path="dataset/source/terms.pdf",
            expected_source_sha256=_DIGEST_A,
            required_table_page=31,
        )

    assert exc_info.value.status == "BLOCKED_ON_INPUT"
    assert exc_info.value.bucket == s0q.S0QErrorBucket.INPUT_INTEGRITY


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("capture_state", "draft"),
        ("text_origin", "manually_cleaned_markdown"),
    ],
)
def test_s0q_rejects_draft_or_manually_cleaned_input(
    key: str,
    value: str,
) -> None:
    payload = _bundle_payload()
    payload[key] = value

    with pytest.raises(s0q.S0QBlockedOnInput):
        s0q.admit_frozen_w1_bundle(
            payload,
            expected_source_path="dataset/source/terms.pdf",
            expected_source_sha256=_DIGEST_A,
            required_table_page=31,
        )


def test_s0q_requires_table_anchor_on_the_frozen_page() -> None:
    payload = _bundle_payload()
    anchors = payload["anchors"]
    assert isinstance(anchors, list)
    anchors.pop()

    with pytest.raises(s0q.S0QBlockedOnInput, match="table anchor"):
        s0q.admit_frozen_w1_bundle(
            payload,
            expected_source_path="dataset/source/terms.pdf",
            expected_source_sha256=_DIGEST_A,
            required_table_page=31,
        )


async def test_s0q_frozen_document_source_uses_only_bundle_content(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "terms-w1.json"
    bundle_path.write_text(
        json.dumps(_bundle_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    source = s0q.FrozenW1DocumentSource(
        expected_sources={"dataset/source/terms.pdf": _DIGEST_A},
        required_table_pages={"dataset/source/terms.pdf": 31},
    )
    request = s0q.FrozenW1SourceRequest(bundle_paths=(bundle_path,))

    async with source.materialize(request) as batch:
        bundle_path.write_text("changed after materialization", encoding="utf-8")
        document = batch.documents[0]
        assert document.pages[29].page_no == 30
        assert "不保证续保" in document.pages[29].text
        assert document.pages[30].page_no == 31
        assert "计划一免赔额10000元" in document.pages[30].text
        assert document.chunks[1].metadata["structural_type"] == "table"
        assert document.source_revision.ordering.value == 3
        assert (
            document.source_revision.parser_fingerprint
            == s0q.canonical_sha256(_revision_data()["parser_identity"])
        )


async def test_s0q_frozen_document_source_identity_is_deterministic(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "terms-w1.json"
    bundle_path.write_text(
        json.dumps(_bundle_payload(), ensure_ascii=False),
        encoding="utf-8",
    )
    source = s0q.FrozenW1DocumentSource(
        expected_sources={"dataset/source/terms.pdf": _DIGEST_A},
        required_table_pages={"dataset/source/terms.pdf": 31},
    )
    request = s0q.FrozenW1SourceRequest(bundle_paths=(bundle_path,))

    async with source.materialize(request) as first:
        first_identity = first.documents[0].source_revision.value
    async with source.materialize(request) as second:
        second_identity = second.documents[0].source_revision.value

    assert first_identity == second_identity
    assert first.documents[0].source_id == second.documents[0].source_id


class _CaptureClient:
    def __init__(
        self,
        *,
        sources: dict[str, tuple[str, tuple[dict[str, object], ...]]],
    ) -> None:
        self.sources = sources
        self.knowledge_to_source: dict[str, str] = {}
        self.events: list[str] = []

    async def create_knowledge_base(
        self,
        credential: object,
        documented_payload: dict[str, object],
    ) -> dict[str, object]:
        self.events.append("create:kb")
        return {"id": "scratch-kb", "name": documented_payload["name"]}

    async def create_tenant_api_key(
        self,
        session: object,
        *,
        tenant_id: int,
        name: str,
        knowledge_base_ids: tuple[str, ...],
    ) -> admin.TenantAPIKey:
        self.events.append("create:key")
        return admin.TenantAPIKey(
            id=47,
            tenant_id=tenant_id,
            name=name,
            role="contributor",
            full_access=False,
            knowledge_base_ids=knowledge_base_ids,
            capabilities=("retrieve", "ingest"),
            token=SecretStr("scratch-key"),
        )

    async def upload_file(
        self,
        api_key: SecretStr,
        kb_id: str,
        path: Path,
        *,
        metadata: dict[str, str],
    ) -> dict[str, object]:
        knowledge_id = f"knowledge-{len(self.knowledge_to_source) + 1}"
        self.knowledge_to_source[knowledge_id] = path.name
        self.events.append(f"upload:{path.name}")
        return {"id": knowledge_id}

    async def get_knowledge(
        self,
        api_key: SecretStr,
        knowledge_id: str,
    ) -> dict[str, object]:
        name = self.knowledge_to_source[knowledge_id]
        digest, _ = self.sources[name]
        return {
            "id": knowledge_id,
            "parse_status": "completed",
            "file_sha256": digest,
        }

    async def get_knowledge_revision(
        self,
        api_key: SecretStr,
        knowledge_id: str,
    ) -> admin.W1RevisionDescriptor:
        name = self.knowledge_to_source[knowledge_id]
        digest, chunks = self.sources[name]
        manifest_digest = _reference_manifest_digest(
            list(chunks),
            knowledge_id=knowledge_id,
        )
        parser = _revision_data()["parser_identity"]
        assert isinstance(parser, dict)
        return admin.W1RevisionDescriptor(
            knowledge_id=knowledge_id,
            parse_attempt=3,
            file_digest=admin.W1FileDigest(algorithm="sha256", value=digest),
            parser_identity=admin.W1ParserIdentity(**parser),
            chunk_manifest=admin.W1ChunkManifest(
                algorithm="weknora.chunk_manifest.v1",
                digest=manifest_digest,
                chunk_count=len(chunks),
            ),
            completed_at="2026-07-30T10:00:00Z",
        )

    async def list_knowledge_revision_chunks(
        self,
        api_key: SecretStr,
        knowledge_id: str,
        *,
        parse_attempt: int,
        page_size: int,
    ) -> admin.W1ChunkListing:
        name = self.knowledge_to_source[knowledge_id]
        _, chunks = self.sources[name]
        exact_chunks = tuple(
            {**chunk, "knowledge_id": knowledge_id}
            for chunk in chunks
        )
        manifest_digest = _reference_manifest_digest(
            list(exact_chunks),
            knowledge_id=knowledge_id,
        )
        return admin.W1ChunkListing(
            items=exact_chunks,
            total=len(exact_chunks),
            page_size=page_size,
            revision=admin.W1ChunkBinding(
                knowledge_id=knowledge_id,
                parse_attempt=parse_attempt,
                manifest_digest=manifest_digest,
                chunk_count=len(exact_chunks),
            ),
        )

    async def delete_tenant_api_key(
        self,
        session: object,
        *,
        tenant_id: int,
        key_id: int,
    ) -> None:
        self.events.append("delete:key")

    async def delete_knowledge_base(
        self,
        credential: object,
        kb_id: str,
    ) -> None:
        self.events.append("delete:kb")


def _capture_chunk(
    *,
    page_number: int,
    structural_type: str,
    content: str,
) -> dict[str, object]:
    return {
        "id": "chunk-1",
        "knowledge_id": "placeholder",
        "parse_attempt": 3,
        "chunk_index": 0,
        "content": content,
        "start_at": 0,
        "end_at": len(content),
        "page_number": page_number,
        "structural_type": structural_type,
    }


def _capture_specs(
    tmp_path: Path,
) -> tuple[tuple[s0q.S0QCaptureSource, ...], dict[str, bytes]]:
    contents = {
        "terms.pdf": b"terms source",
        "brochure.pdf": b"brochure source",
    }
    for name, value in contents.items():
        (tmp_path / name).write_bytes(value)
    specs = (
        s0q.S0QCaptureSource(
            source_path="terms.pdf",
            source_bytes=len(contents["terms.pdf"]),
            source_sha256=sha256(contents["terms.pdf"]).hexdigest(),
            artifact_name="terms-w1.json",
            required_anchor_page=31,
            required_anchor_quote="免赔额",
            required_anchor_structural_type="table",
        ),
        s0q.S0QCaptureSource(
            source_path="brochure.pdf",
            source_bytes=len(contents["brochure.pdf"]),
            source_sha256=sha256(contents["brochure.pdf"]).hexdigest(),
            artifact_name="brochure-w1.json",
            required_anchor_page=1,
            required_anchor_quote="产品特色",
            required_anchor_structural_type="text",
        ),
    )
    return specs, contents


async def test_s0q_capture_writes_both_bundles_then_cleans_scratch(
    tmp_path: Path,
) -> None:
    specs, _ = _capture_specs(tmp_path)
    sources = {
        "terms.pdf": (
            specs[0].source_sha256,
            (
                _capture_chunk(
                    page_number=31,
                    structural_type="table",
                    content="免赔额计划一10000元，计划二0元",
                ),
            ),
        ),
        "brochure.pdf": (
            specs[1].source_sha256,
            (
                _capture_chunk(
                    page_number=1,
                    structural_type="text",
                    content="产品特色包括保证范围广",
                ),
            ),
        ),
    }
    client = _CaptureClient(sources=sources)
    session = admin.AdminSession(
        user_id="admin-1",
        tenant_id=7,
        token=SecretStr("admin-token"),
        refresh_token=SecretStr("refresh-token"),
    )
    output = tmp_path / "artifacts"

    report = await s0q.capture_s0q_w1_inputs(
        client=client,
        session=session,
        source_root=tmp_path,
        output_dir=output,
        sources=specs,
        scratch_kb_payload={
            "name": "insurancekb-s0q-047-scratch-test",
            "description": "owner=s0q-047",
        },
        poll_attempts=1,
        poll_interval_seconds=0,
    )

    assert report["status"] == "ADMITTED"
    assert (output / "terms-w1.json").is_file()
    assert (output / "brochure-w1.json").is_file()
    assert (output / "input-manifest.json").is_file()
    assert (output / "input-capture-report.json").is_file()
    assert client.events[-2:] == ["delete:key", "delete:kb"]


async def test_s0q_capture_missing_table_structure_delivers_blocked_report(
    tmp_path: Path,
) -> None:
    specs, _ = _capture_specs(tmp_path)
    sources = {
        "terms.pdf": (
            specs[0].source_sha256,
            (
                _capture_chunk(
                    page_number=31,
                    structural_type="unknown",
                    content="免赔额计划一10000元，计划二0元",
                ),
            ),
        ),
        "brochure.pdf": (
            specs[1].source_sha256,
            (
                _capture_chunk(
                    page_number=1,
                    structural_type="text",
                    content="产品特色包括保证范围广",
                ),
            ),
        ),
    }
    client = _CaptureClient(sources=sources)
    session = admin.AdminSession(
        user_id="admin-1",
        tenant_id=7,
        token=SecretStr("admin-token"),
        refresh_token=SecretStr("refresh-token"),
    )
    output = tmp_path / "artifacts"

    report = await s0q.capture_s0q_w1_inputs(
        client=client,
        session=session,
        source_root=tmp_path,
        output_dir=output,
        sources=specs,
        scratch_kb_payload={
            "name": "insurancekb-s0q-047-scratch-test",
            "description": "owner=s0q-047",
        },
        poll_attempts=1,
        poll_interval_seconds=0,
    )

    assert report["status"] == "BLOCKED_ON_INPUT"
    assert report["bucket"] == "input_integrity"
    assert "table structure" in report["reason"]
    assert sorted(path.name for path in output.iterdir()) == [
        "input-capture-report.json"
    ]
    assert client.events[-2:] == ["delete:key", "delete:kb"]


def test_s0q_capture_cli_exposes_only_the_bounded_capture_command() -> None:
    script = Path(__file__).parents[1] / "scripts" / "run_s0q_047.py"

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "{capture}" in result.stdout
    assert "diagnose" not in result.stdout

    capture_help = subprocess.run(
        [sys.executable, str(script), "capture", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert capture_help.returncode == 0
    assert "--raw-kb-id" in capture_help.stdout
