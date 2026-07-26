"""W0 spike T3: chunk enumeration ordering, pagination cursor semantics, manifest."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from w0lib import Api, chunk_brief, envelope_summary, load_state, log_json  # noqa: E402


def main() -> None:
    state = load_state()
    api = Api()
    api.admin_login()
    token = api.find_api_key_token(state["rw_key_id"])
    kid = state["knowledge_id"]
    out: dict = {}

    # 1. full listing ordering
    full = api.key_request(
        token, "GET", f"/chunks/{kid}", params={"page": 1, "page_size": 100}
    ).json()
    chunks = full["data"]
    idx = [c["chunk_index"] for c in chunks]
    seq = [c["seq_id"] for c in chunks]
    out["full_listing"] = {
        "total": full.get("total"),
        "page": full.get("page"),
        "page_size": full.get("page_size"),
        "chunk_index_ascending": idx == sorted(idx),
        "chunk_index_values": idx,
        "seq_id_ascending": seq == sorted(seq),
        "content_hash_values_distinct": sorted({c.get("content_hash") for c in chunks}),
        "chunk_has_attempt_or_version_field": sorted(
            k for k in chunks[0].keys() if "attempt" in k or "version" in k or "revision" in k
        ),
        "chunk_metadata_of_first": chunks[0].get("metadata"),
    }

    # 2. pagination walk page_size=5
    walk_pages = []
    collected = []
    page = 1
    while True:
        doc = api.key_request(
            token, "GET", f"/chunks/{kid}", params={"page": page, "page_size": 5}
        ).json()
        walk_pages.append(
            {
                "page_requested": page,
                "page_echoed": doc.get("page"),
                "page_size_echoed": doc.get("page_size"),
                "total": doc.get("total"),
                "ids": [c["id"] for c in doc.get("data") or []],
                "chunk_index": [c["chunk_index"] for c in doc.get("data") or []],
            }
        )
        batch = doc.get("data") or []
        collected.extend(c["id"] for c in batch)
        if len(batch) < 5:
            break
        page += 1
    out["walk_page_size_5"] = {
        "pages": walk_pages,
        "union_equals_full_listing": set(collected) == {c["id"] for c in chunks},
        "duplicates": len(collected) != len(set(collected)),
        "count": len(collected),
    }

    # 3. out-of-range page
    oor = api.key_request(
        token, "GET", f"/chunks/{kid}", params={"page": 99, "page_size": 5}
    )
    out["out_of_range_page"] = envelope_summary(oor)

    # 4. oversized page_size clamp
    clamp = api.key_request(
        token, "GET", f"/chunks/{kid}", params={"page": 1, "page_size": 1000}
    ).json()
    out["page_size_1000"] = {
        "page_size_echoed": clamp.get("page_size"),
        "returned": len(clamp.get("data") or []),
        "total": clamp.get("total"),
    }

    # 5. sort_order probe
    desc = api.key_request(
        token,
        "GET",
        f"/chunks/{kid}",
        params={"page": 1, "page_size": 5, "sort_order": "desc"},
    ).json()
    out["sort_order_desc"] = {
        "chunk_index": [c["chunk_index"] for c in desc.get("data") or []],
        "page_size": desc.get("page_size"),
    }

    # 6. typed chunk filter
    ocr = api.key_request(
        token,
        "GET",
        f"/chunks/{kid}",
        params={"page": 1, "page_size": 5, "chunk_type": "image_ocr"},
    ).json()
    out["chunk_type_image_ocr"] = {"total": ocr.get("total"), "returned": len(ocr.get("data") or [])}

    # 7. by-id single chunk read
    one = api.key_request(token, "GET", f"/chunks/by-id/{chunks[0]['id']}")
    body = one.json() if one.status_code == 200 else {}
    data = body.get("data") or {}
    out["chunk_by_id"] = {
        "status_code": one.status_code,
        "keys": sorted(data.keys()) if isinstance(data, dict) else None,
        "brief": chunk_brief(data) if isinstance(data, dict) and data else None,
    }

    # 8. client-side manifest computability (and its limits)
    manifest_lines = [
        f"{c['chunk_index']}:{c['id']}:{hashlib.sha256((c.get('content') or '').encode()).hexdigest()}"
        for c in chunks
    ]
    manifest_digest = hashlib.sha256("\n".join(manifest_lines).encode()).hexdigest()
    out["client_manifest"] = {
        "algorithm": "sha256 over newline-joined 'chunk_index:id:sha256(content)' in chunk_index order",
        "digest": manifest_digest,
        "server_side_manifest_digest_field_or_endpoint": None,
        "server_content_hash_populated": any(c.get("content_hash") for c in chunks),
        "limitation": (
            "computed from N offset-paginated reads with no snapshot token; "
            "not attributable to a parse attempt by any server-returned field"
        ),
    }

    log_json("30_t3_enumeration", out)
    print("full ordering asc:", out["full_listing"]["chunk_index_ascending"], "seq asc:", out["full_listing"]["seq_id_ascending"])
    print("walk union ok:", out["walk_page_size_5"]["union_equals_full_listing"], "pages:", len(walk_pages))
    print("oor page:", out["out_of_range_page"]["status_code"], "clamp:", out["page_size_1000"], )
    print("desc idx:", out["sort_order_desc"]["chunk_index"])
    print("by-id:", out["chunk_by_id"]["status_code"])
    api.close()
    print("t3 done")


if __name__ == "__main__":
    main()
