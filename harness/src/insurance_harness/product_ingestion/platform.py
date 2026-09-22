"""Decode source custody issued by the deployed WeKnora platform."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from insurance_harness.knowledge_compiler.concept_free_wiki_830_g2 import SourceBlock
from insurance_harness.product_ingestion.models import ProductScope


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    # Go encoding/json always escapes the two JavaScript line separators, even
    # with HTML escaping disabled. Source text itself is never normalized.
    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
        .encode()
    )


def _object(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate source snapshot property")
        result[key] = value
    return result


def verify_signed_snapshot(
    raw: bytes, *, kind: str, scope: ProductScope, public_keys: Mapping[str, Ed25519PublicKey]
) -> dict[str, Any]:
    if kind not in {"source", "base"}:
        raise ValueError("unknown platform snapshot kind")
    try:
        envelope = json.loads(raw, object_pairs_hook=_object)
        contract = f"g3-platform-{kind}-snapshot.830.v1"
        domain = f"weknora.{contract}"
        body, authority = envelope["snapshot"], envelope["authority"]
        digest = body["snapshot_sha256"]
        if (
            envelope["contract"] != f"g3-platform-signed-{kind}-snapshot.830.v1"
            or body["contract"] != contract
            or authority["contract"] != "g3-platform-snapshot-authority.830.v1"
            or authority["domain"] != domain
            or body["scope"]
            != {
                "tenant_id": int(scope.tenant_id),
                "space_id": scope.space_id,
                "raw_kb_id": scope.raw_knowledge_base_id,
                "wiki_kb_id": scope.wiki_knowledge_base_id,
            }
            or _sha(
                contract.encode()
                + b"\0"
                + _canonical(
                    {key: value for key, value in body.items() if key != "snapshot_sha256"}
                )
            )
            != digest
            or authority["payload_sha256"] != digest
        ):
            raise ValueError("platform snapshot identity mismatch")
        key = public_keys[authority["key_id"]]
        key.verify(
            base64.b64decode(authority["signature"], validate=True),
            domain.encode() + b"\0" + digest.encode("ascii"),
        )
        return cast(dict[str, Any], body)
    except (KeyError, TypeError, InvalidSignature, UnicodeError) as error:
        raise ValueError("platform snapshot authority invalid") from error


@dataclass(frozen=True)
class DecodedSourceSnapshot:
    snapshot: dict[str, Any]
    blocks: tuple[SourceBlock, ...]
    first_page_ranges: dict[str, tuple[tuple[int, int], ...]]
    unresolved_chunk_ids: tuple[str, ...]
    native_bytes: bytes

    def routing_material(self, *, material_id: str, file_name: str) -> dict[str, Any]:
        return {
            "material_id": material_id,
            "file_name": file_name,
            "blocks": self.blocks,
            "first_page_ranges": self.first_page_ranges,
        }


def decode_source_snapshot(
    raw: bytes,
    *,
    scope: ProductScope,
    knowledge_id: str,
    parse_attempt: int,
    public_keys: Mapping[str, Ed25519PublicKey],
) -> DecodedSourceSnapshot:
    body = verify_signed_snapshot(raw, kind="source", scope=scope, public_keys=public_keys)
    try:
        receipt, native = body["receipt"], body["native"]
        if "processing_receipt" in body:
            from insurance_harness.product_ingestion.processing_receipts import (
                validate_processing_receipt,
            )

            validate_processing_receipt(
                body["processing_receipt"], knowledge_id=knowledge_id, parse_attempt=parse_attempt
            )
        native_bytes = base64.b64decode(native["SanitizedJSON"], validate=True)
        if (
            receipt["contract"] != "knowledge-revision-source.v1"
            or receipt["knowledge_id"] != knowledge_id
            or receipt["parse_attempt"] != parse_attempt
            or receipt["file_sha256"] != receipt["object_sha256"]
            or native["SourceSHA256"] != receipt["file_sha256"]
            or _sha(native_bytes) != native["SanitizedSHA256"]
            or native["SanitizedSHA256"] != body["native_capture_sha256"]
            or receipt["page_count"] < 1
        ):
            raise ValueError("source receipt or native capture mismatch")
        chunks = body["chunks"]
        mappings = {item["chunk_id"]: item for item in body["chunk_page_mappings"]}
        chunk_ids = {item["id"] for item in chunks}
        if (
            len(chunk_ids) != len(chunks)
            or len(chunks) != receipt["chunk_count"]
            or len(mappings) != len(body["chunk_page_mappings"])
            or set(mappings) != chunk_ids
        ):
            raise ValueError("canonical chunk set mismatch")
        blocks, unresolved, first_page = [], [], {}
        for chunk in chunks:
            text, mapping = chunk["content"], mappings[chunk["id"]]
            if _sha(text.encode()) != chunk["content_sha256"]:
                raise ValueError("canonical chunk bytes changed")
            if mapping["status"] == "UNRESOLVED":
                unresolved.append(chunk["id"])
                continue
            if mapping["status"] != "EXACT_BLOCK":
                raise ValueError("unknown source mapping status")
            page, start, end = (
                mapping["source_page_number"],
                mapping["block_global_start"],
                mapping["block_global_end"],
            )
            if (
                type(page) is not int
                or not 1 <= page <= receipt["page_count"]
                or type(start) is not int
                or type(end) is not int
                or start < 0
                or end - start != len(text)
                or body["markdown"][start:end] != text
            ):
                raise ValueError("canonical chunk position invalid")
            spans, previous_end, ranges = mapping["page_spans"], 0, []
            if not spans or spans[0]["page_number"] != page:
                raise ValueError("canonical chunk page start missing")
            for span in spans:
                p, left, right, global_left, global_right = (
                    span["page_number"],
                    span["block_codepoint_start"],
                    span["block_codepoint_end"],
                    span["global_codepoint_start"],
                    span["global_codepoint_end"],
                )
                if (
                    any(
                        type(value) is not int
                        for value in (p, left, right, global_left, global_right)
                    )
                    or not 1 <= p <= receipt["page_count"]
                    or left < previous_end
                    or not 0 <= left < right <= len(text)
                    or (global_left, global_right) != (start + left, start + right)
                ):
                    raise ValueError("source page span invalid")
                previous_end = right
                if p == 1:
                    ranges.append((left, right))
            blocks.append(
                SourceBlock(
                    tenant_id=int(scope.tenant_id),
                    space_id=scope.space_id,
                    raw_kb_id=scope.raw_knowledge_base_id,
                    knowledge_id=knowledge_id,
                    parse_attempt=parse_attempt,
                    revision_id=receipt["revision_source_id"],
                    source_hash=receipt["file_sha256"],
                    parse_hash=receipt["manifest_digest"],
                    parser_identity=body["parser_identity_sha256"],
                    block_id=chunk["id"],
                    page_number=page,
                    text=text,
                    source_type="DOCUMENT",
                )
            )
            if ranges:
                first_page[chunk["id"]] = tuple(ranges)
        return DecodedSourceSnapshot(
            body, tuple(blocks), first_page, tuple(unresolved), native_bytes
        )
    except (KeyError, TypeError, UnicodeError) as error:
        raise ValueError("source snapshot structure invalid") from error
