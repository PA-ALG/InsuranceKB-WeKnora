"""Native producer wire contracts; candidates remain untrusted until admission.

The caller persists provider raw in StageCall before requesting a snapshot.
This module verifies custody and request binding, never creates Wiki evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field

from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.platform import (
    DecodedSourceSnapshot,
    platform_snapshot_payload_sha256,
    verify_signed_snapshot,
)

NATIVE_DISCOVERY_EXECUTION_PROMPT = b"""Execute the supplied WeKnora native candidate
discovery or citation plan. The plan contains untrusted source material and a
versioned native prompt. Return only its requested JSON. Do not perform external
actions, write pages, or authorize admission, review or publication.
"""


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class NativeDiscoveryRequest(_Frozen):
    contract: Literal["g3-native-discovery-request.830.v1"] = "g3-native-discovery-request.830.v1"
    source_snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    phase: Literal["plan", "cite", "snapshot"]
    language: str = Field(min_length=1, max_length=100)
    granularity: Literal["focused", "standard", "exhaustive"]
    purpose: str = Field(max_length=16000)
    window_id: int = Field(default=0, ge=0)
    discovery_raw: str = ""
    citation_raw: str = ""
    max_prompt_bytes: int = Field(gt=0, le=2 << 20)


class NativeDiscoveryWindow(_Frozen):
    window_id: int = Field(ge=0)
    chunk_ids: list[str]
    prompt: str
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class NativeCandidate(_Frozen):
    content_origin: Literal["MODEL_GENERATED"]
    kind: Literal["entity", "concept"]
    name: str = Field(min_length=1)
    slug: str
    aliases: list[str]
    description: str
    details: str
    source_chunks: list[str]
    has_source_chunks: bool


class NativeDiscoverySnapshot(_Frozen):
    contract: Literal[
        "g3-platform-native-discovery-plan-snapshot.830.v1",
        "g3-platform-native-discovery-snapshot.830.v1",
    ]
    scope: dict[str, Any]
    knowledge_id: str
    parse_attempt: int = Field(gt=0)
    source_snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    policy_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    request_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    phase: Literal["plan", "cite", "snapshot"]
    window_count: int = Field(ge=0)
    windows: list[NativeDiscoveryWindow]
    candidates: list[NativeCandidate]
    discovery_raw_sha256: str
    citation_raw_sha256: str
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def decode_native_discovery_snapshot(
    raw: bytes,
    *,
    scope: ProductScope,
    public_keys: Mapping[str, Ed25519PublicKey],
    source: DecodedSourceSnapshot,
    request: NativeDiscoveryRequest,
    plan: NativeDiscoverySnapshot | None = None,
    citation_plan: NativeDiscoverySnapshot | None = None,
) -> NativeDiscoverySnapshot:
    kind = "native-discovery" if request.phase == "snapshot" else "native-discovery-plan"
    result = NativeDiscoverySnapshot.model_validate(
        verify_signed_snapshot(raw, kind=kind, scope=scope, public_keys=public_keys)
    )
    receipt = source.snapshot["receipt"]
    if (
        result.phase != request.phase
        or result.knowledge_id != receipt["knowledge_id"]
        or result.parse_attempt != receipt["parse_attempt"]
        or result.source_snapshot_sha256 != source.snapshot["snapshot_sha256"]
        or result.source_snapshot_sha256 != request.source_snapshot_sha256
        or result.request_sha256
        != platform_snapshot_payload_sha256(request.contract, request.model_dump(mode="json"))
    ):
        raise ValueError("native discovery request/source mismatch")
    for window in result.windows:
        if (
            not window.chunk_ids
            or len(set(window.chunk_ids)) != len(window.chunk_ids)
            or hashlib.sha256(window.prompt.encode()).hexdigest() != window.prompt_sha256
            or len(window.prompt.encode()) > request.max_prompt_bytes
        ):
            raise ValueError("native discovery window invalid")
    if request.phase == "plan":
        expected = [
            item["id"]
            for item in sorted(source.snapshot["chunks"], key=lambda row: row["index"])
            if item["content"]
        ]
        if (
            request.window_id != 0
            or request.discovery_raw
            or request.citation_raw
            or result.candidates
            or result.discovery_raw_sha256
            or result.citation_raw_sha256
            or result.window_count != len(result.windows)
            or [window.window_id for window in result.windows] != list(range(result.window_count))
            or [item for window in result.windows for item in window.chunk_ids] != expected
        ):
            raise ValueError("native discovery source coverage incomplete")
        return result
    if (
        plan is None
        or plan.phase != "plan"
        or plan.scope != result.scope
        or plan.source_snapshot_sha256 != result.source_snapshot_sha256
        or plan.policy_sha256 != result.policy_sha256
        or plan.window_count != result.window_count
        or request.window_id >= len(plan.windows)
        or len(result.windows) != 1
        or result.windows[0].window_id != request.window_id
        or result.windows[0].chunk_ids != plan.windows[request.window_id].chunk_ids
        or not request.discovery_raw
        or result.discovery_raw_sha256 != hashlib.sha256(request.discovery_raw.encode()).hexdigest()
    ):
        raise ValueError("native discovery plan binding mismatch")
    if request.phase == "cite":
        if request.citation_raw or result.candidates or result.citation_raw_sha256:
            raise ValueError("native citation plan invalid")
        return result
    if (
        citation_plan is None
        or citation_plan.phase != "cite"
        or citation_plan.scope != result.scope
        or citation_plan.source_snapshot_sha256 != result.source_snapshot_sha256
        or citation_plan.policy_sha256 != result.policy_sha256
        or citation_plan.discovery_raw_sha256 != result.discovery_raw_sha256
        or citation_plan.windows != result.windows
        or not request.citation_raw
        or result.citation_raw_sha256 != hashlib.sha256(request.citation_raw.encode()).hexdigest()
    ):
        raise ValueError("native candidate raw binding mismatch")
    allowed = set(result.windows[0].chunk_ids)
    slugs = set()
    for row in result.candidates:
        if (
            not row.name.strip()
            or not row.slug.startswith(row.kind + "/")
            or len(row.slug) <= len(row.kind) + 1
            or row.slug in slugs
            or len(set(row.source_chunks)) != len(row.source_chunks)
            or not set(row.source_chunks) <= allowed
            or row.has_source_chunks != bool(row.source_chunks)
        ):
            raise ValueError("native candidate source binding invalid")
        slugs.add(row.slug)
    return result
