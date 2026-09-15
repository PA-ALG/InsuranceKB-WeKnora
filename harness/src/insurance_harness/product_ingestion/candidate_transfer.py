"""Bounded publication transport; the canonical candidate remains authoritative."""

from __future__ import annotations

import base64
import gzip
import hashlib
import json

from insurance_harness.product_ingestion.compilation import published_compile_members
from insurance_harness.product_ingestion.platform import _object

CONTRACT = "g3-platform-candidate-transfer.830.v1"
MAX_WIRE_BYTES = 8 << 20
MAX_DELTA_BYTES = 64 << 20
MAX_CANDIDATE_BYTES = 128 << 20

# These are protocol slots, never caller-provided JSON paths.
SLOTS = {
    "sources": (("request", "base_request"), "sources", "sources"),
    "existing_definitions": (("request", "base_request"), "existing_definitions", "definitions"),
    "existing_fields": (("request", "base_request"), "existing_fields", "fields"),
    "existing_pages": (("request", "base_request"), "existing_pages", "pages"),
    "definitions": (("compile_result", "output"), "definitions", "definitions"),
    "fields": (("compile_result", "output"), "fields", "fields"),
    "pages": (("compile_result", "output"), "pages", "pages"),
}


def _wire(value) -> bytes:
    # Transport is lossless, not a second domain validator. In particular raw
    # evidence and provider output may contain decomposed Unicode and CRLF.
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def encode_candidate_transfer(candidate_raw: bytes, base_body: dict) -> bytes:
    """Consume a verified published snapshot; preserve the exact canonical candidate.

    Signature/current-authority verification belongs to the existing caller and
    receiver. This pure codec neither fetches history nor authorizes publication.
    """
    if len(candidate_raw) > MAX_CANDIDATE_BYTES:
        raise ValueError("candidate expansion limit exceeded")
    candidate = json.loads(candidate_raw, object_pairs_hook=_object)
    canonical = _wire(candidate)
    if len(canonical) > MAX_CANDIDATE_BYTES:
        raise ValueError("candidate expansion limit exceeded")
    projection = base_body["published_projection"]
    pools = {
        kind: {
            _wire(row): index
            for index, row in enumerate(
                projection[kind]
                if kind == "sources"
                else published_compile_members(projection, kind)
            )
        }
        for kind in ("sources", "definitions", "fields", "pages")
    }
    members = {}
    for slot, (parents, key, kind) in SLOTS.items():
        parent = candidate
        for part in parents:
            parent = parent[part]
        rows = parent.pop(key)
        if not isinstance(rows, list):
            raise ValueError("candidate transfer requires an explicit member array")
        packed, used = [], set()
        for row in rows:
            index = pools[kind].get(_wire(row))
            if index is None:
                packed.append({"inline": row})
            else:
                if index in used:
                    raise ValueError("duplicate published member reference")
                used.add(index)
                packed.append({"base_index": index})
        members[slot] = packed
    payload = _wire({"candidate": candidate, "members": members})
    if len(payload) > MAX_DELTA_BYTES:
        raise ValueError("candidate delta limit exceeded")
    transfer = _wire(
        {
            "contract": CONTRACT,
            "base": {
                key: base_body[key]
                for key in (
                    "scope",
                    "release_id",
                    "activation_epoch",
                    "candidate_sha256",
                    "manifest_digest",
                )
            },
            "manifest_sha256": hashlib.sha256(canonical).hexdigest(),
            "encoding": "gzip+base64",
            "decoded_bytes": len(payload),
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload": base64.b64encode(gzip.compress(payload, mtime=0)).decode("ascii"),
        }
    )
    if len(transfer) > MAX_WIRE_BYTES:
        raise ValueError("candidate transfer limit exceeded")
    return transfer
