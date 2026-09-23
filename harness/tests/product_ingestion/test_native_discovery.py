from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from insurance_harness.product_ingestion.models import ProductScope
from insurance_harness.product_ingestion.platform import verify_signed_snapshot

CONTRACT = "g3-platform-native-discovery-snapshot.830.v1"
SCOPE = ProductScope(
    tenant_id="42", space_id="space", raw_knowledge_base_id="raw", wiki_knowledge_base_id="wiki"
)
KEY = Ed25519PrivateKey.from_private_bytes(bytes(32))


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
        .encode()
    )


def signed(body: dict[str, Any]) -> bytes:
    value = {key: item for key, item in body.items() if key != "snapshot_sha256"}
    contract = body["contract"]
    digest = hashlib.sha256(contract.encode() + b"\0" + canonical(value)).hexdigest()
    value["snapshot_sha256"] = digest
    domain = "weknora." + contract
    return canonical(
        {
            "contract": contract.replace("g3-platform-", "g3-platform-signed-", 1),
            "snapshot": value,
            "authority": {
                "contract": "g3-platform-snapshot-authority.830.v1",
                "domain": domain,
                "key_id": "fixture",
                "payload_sha256": digest,
                "signature": base64.b64encode(
                    KEY.sign(domain.encode() + b"\0" + digest.encode())
                ).decode(),
            },
        }
    )


def test_native_snapshot_has_a_distinct_verified_signing_domain() -> None:
    body = {
        "contract": CONTRACT,
        "scope": {"tenant_id": 42, "space_id": "space", "raw_kb_id": "raw", "wiki_kb_id": "wiki"},
    }
    result = verify_signed_snapshot(
        signed(body),
        kind="native-discovery",
        scope=SCOPE,
        public_keys={"fixture": KEY.public_key()},
    )
    assert result["contract"] == CONTRACT
    with pytest.raises(ValueError):
        verify_signed_snapshot(
            signed(body), kind="source", scope=SCOPE, public_keys={"fixture": KEY.public_key()}
        )


@pytest.fixture
def native_vector() -> dict[str, Any]:
    path = (
        Path(__file__).resolve().parents[3]
        / "internal/application/service/testdata/g3_native_discovery_v1.json"
    )
    return json.loads(path.read_bytes())


def decode_vector(vector: dict[str, Any]) -> list[Any]:
    from insurance_harness.product_ingestion.native_discovery import (
        NativeDiscoveryRequest,
        decode_native_discovery_snapshot,
    )
    from insurance_harness.product_ingestion.platform import DecodedSourceSnapshot

    source = DecodedSourceSnapshot(
        snapshot=vector["source"],
        blocks=(),
        first_page_ranges={},
        unresolved_chunk_ids=(),
        native_bytes=b"",
    )
    results = []
    for i, (request, envelope) in enumerate(
        zip(vector["requests"], vector["envelopes"], strict=True)
    ):
        results.append(
            decode_native_discovery_snapshot(
                canonical(envelope),
                scope=SCOPE,
                public_keys={"fixture": KEY.public_key()},
                source=source,
                request=NativeDiscoveryRequest.model_validate(request),
                plan=results[0] if i else None,
                citation_plan=results[1] if i == 2 else None,
            )
        )
    return results


def test_native_go_signed_plan_and_candidates_roundtrip(native_vector: dict[str, Any]) -> None:
    plan, citation, snapshot = decode_vector(native_vector)
    assert plan.phase == "plan" and citation.phase == "cite" and snapshot.phase == "snapshot"
    assert snapshot.candidates[0].source_chunks == ["block-a"]
    assert snapshot.candidates[1].content_origin == "MODEL_GENERATED"
    assert not snapshot.candidates[1].has_source_chunks
    assert snapshot.candidates[1].details == "不得成为原文"


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "request",
        "coverage",
        "raw",
        "citation_prompt",
        "chunk",
        "origin",
        "duplicate",
        "claim_evidence",
    ],
)
def test_signed_native_projection_cannot_escape_plan_or_source(
    native_vector: dict[str, Any], change: str
) -> None:
    vector = deepcopy(native_vector)
    phase = 0 if change == "coverage" else 2
    body = vector["envelopes"][phase]["snapshot"]
    if change == "source":
        body["source_snapshot_sha256"] = "b" * 64
    elif change == "request":
        body["request_sha256"] = "b" * 64
    elif change == "coverage":
        body["windows"][0]["chunk_ids"].pop()
    elif change == "raw":
        body["discovery_raw_sha256"] = "b" * 64
    elif change == "citation_prompt":
        body["windows"][0]["prompt"] += " changed"
        body["windows"][0]["prompt_sha256"] = hashlib.sha256(
            body["windows"][0]["prompt"].encode()
        ).hexdigest()
    elif change == "chunk":
        body["candidates"][0]["source_chunks"] = ["other-source-block"]
    elif change == "origin":
        body["candidates"][0]["content_origin"] = "SOURCE_EXCERPT"
    elif change == "duplicate":
        body["candidates"].append(body["candidates"][0])
    else:
        body["candidates"][1]["has_source_chunks"] = True
    vector["envelopes"][phase] = json.loads(signed(body))
    with pytest.raises(ValueError):
        decode_vector(vector)
