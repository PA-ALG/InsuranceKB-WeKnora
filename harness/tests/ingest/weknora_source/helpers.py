"""OpenSpec 017 B1 WeKnora source transport contract: shared URLs, payloads and clients."""

import hashlib
from pathlib import Path

from insurance_harness.adapters.weknora import (
    WeKnoraClient,
    WeKnoraKnowledge,
)
from insurance_harness.config import HarnessSettings
from tests.conftest import BASE_URL

KID = "knowledge-017"
META_URL = f"{BASE_URL}/api/v1/knowledge/{KID}"
BODY = b"insurance source document"
MD5 = hashlib.md5(BODY).hexdigest()  # noqa: S324 - upstream WeKnora contract is MD5


def _metadata(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": KID,
        "tenant_id": "tenant-1",
        "knowledge_base_id": "kb-1",
        "title": "保险条款",
        "file_name": "terms.pdf",
        "file_type": "pdf",
        "file_size": len(BODY),
        "file_hash": MD5,
        "processed_at": "2026-07-13T08:30:00Z",
        "updated_at": "2026-07-13T08:31:00Z",
        "parse_status": "completed",
    }
    data.update(overrides)
    return data


def _knowledge(**overrides: object) -> WeKnoraKnowledge:
    return WeKnoraKnowledge.model_validate(_metadata(**overrides))


def _chunk(index: int, **overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "id": f"chunk-{index}",
        "tenant_id": "tenant-1",
        "knowledge_id": KID,
        "knowledge_base_id": "kb-1",
        "content": f"第 {index} 段",
        "chunk_index": index,
        "start_at": index * 10,
        "end_at": index * 10 + 9,
        "metadata": {"section": "保障责任"},
        "content_hash": f"hash-{index}",
    }
    data.update(overrides)
    return data


def _source_client(settings: HarnessSettings, tmp_path: Path) -> WeKnoraClient:
    configured = settings.model_copy(
        update={
            "source_max_file_bytes": 1024,
            "source_download_chunk_bytes": 4,
            "source_temp_dir": tmp_path,
        }
    )
    return WeKnoraClient(configured)
