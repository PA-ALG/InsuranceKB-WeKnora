"""W0 spike phase 0: baseline (read-only), scratch KB/keys, upload, first parse."""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from w0lib import (  # noqa: E402
    Api,
    build_pdf,
    chunk_brief,
    envelope_summary,
    log_json,
    save_state,
    wait_parsed,
)


def main() -> None:
    api = Api()
    api.admin_login()
    run_id = time.strftime("%m%d%H%M%S")
    print(f"run_id={run_id} tenant={api.tenant_id}")

    # ---------------------------------------------------- read-only baseline
    kbs = api.admin("GET", "/knowledge-bases")
    kbs.raise_for_status()
    kb_list = kbs.json()["data"]
    baseline = {
        "knowledge_bases": [
            {"id": kb["id"], "name": kb["name"], "updated_at": kb.get("updated_at")}
            for kb in kb_list
        ],
        "knowledge_by_kb": {},
    }
    for kb in kb_list:
        resp = api.admin(
            "GET",
            f"/knowledge-bases/{kb['id']}/knowledge",
            params={"page": 1, "page_size": 100},
        )
        if resp.status_code == 200:
            items = resp.json().get("data") or []
            baseline["knowledge_by_kb"][kb["id"]] = [
                {
                    "id": item["id"],
                    "file_name": item.get("file_name"),
                    "updated_at": item.get("updated_at"),
                    "parse_status": item.get("parse_status"),
                }
                for item in items
            ]
        else:
            baseline["knowledge_by_kb"][kb["id"]] = {
                "error_status": resp.status_code
            }
    log_json("00_baseline_readonly", baseline)

    # ---------------------------------------------------------- scratch KB
    kb_name = f"w0-spike-kb-{run_id}"
    resp = api.admin(
        "POST",
        "/knowledge-bases",
        json_body={
            "name": kb_name,
            "description": f"w0-spike-{run_id} scratch KB (OpenSpec 037), safe to delete",
            "type": "document",
            "embedding_model_id": api.env["LOCAL_LIVE_EMBEDDING_MODEL_ID"],
            "vlm_config": {"enabled": False, "model_id": ""},
        },
    )
    resp.raise_for_status()
    kb = resp.json()["data"]
    kb_id = kb["id"]
    log_json("01_scratch_kb_created", {"request_name": kb_name, "response": kb})
    print(f"scratch kb id={kb_id}")

    # ------------------------------------------------------------ api keys
    rw_id, rw_token = api.create_api_key(
        f"w0-spike-key-rw-{run_id}", [kb_id], ["retrieve", "ingest"]
    )
    ro_id, ro_token = api.create_api_key(
        f"w0-spike-key-ro-{run_id}", [kb_id], ["retrieve"]
    )
    print(f"scratch keys rw={rw_id} ro={ro_id} (tokens in memory only)")

    # ------------------------------------------------------------- pdf + up
    pdf_bytes = build_pdf(pages=5, lines_per_page=25)
    pdf_path = Path(__file__).with_name(f"w0-spike-doc-{run_id}.pdf")
    pdf_path.write_bytes(pdf_bytes)
    digest = hashlib.sha256(pdf_bytes).hexdigest()
    md5 = hashlib.md5(pdf_bytes).hexdigest()
    print(f"pdf bytes={len(pdf_bytes)} sha256={digest[:16]}... md5={md5}")

    with pdf_path.open("rb") as fh:
        up = api.key_request(
            rw_token,
            "POST",
            f"/knowledge-bases/{kb_id}/knowledge/file",
            files={"file": (pdf_path.name, fh, "application/pdf")},
            data={
                "metadata": (
                    '{"owner": "w0-spike-' + run_id + '", "sha256": "' + digest + '"}'
                )
            },
            timeout=120.0,
        )
    up_summary = envelope_summary(up)
    log_json("02_upload_response", up_summary)
    up.raise_for_status()
    knowledge = up.json()["data"]
    kid = knowledge["id"]
    print(f"knowledge id={kid} initial parse_status={knowledge.get('parse_status')}")

    # -------------------------------------------------- first parse attempt
    completed = wait_parsed(api, rw_token, kid, timeout_s=420.0)
    spans = api.key_request(rw_token, "GET", f"/knowledge/{kid}/spans")
    chunks = api.key_request(
        rw_token,
        "GET",
        f"/chunks/{kid}",
        params={"page": 1, "page_size": 100},
    )
    chunks.raise_for_status()
    chunk_doc = chunks.json()
    log_json(
        "03_attempt1_completed",
        {
            "knowledge": completed,
            "spans": envelope_summary(spans),
            "chunks_total": chunk_doc.get("total"),
            "chunks_page": chunk_doc.get("page"),
            "chunks_page_size": chunk_doc.get("page_size"),
            "chunks": [chunk_brief(c) for c in chunk_doc.get("data") or []],
            "first_chunk_full": (chunk_doc.get("data") or [{}])[0],
        },
    )
    print(
        f"attempt1 completed: chunks_total={chunk_doc.get('total')} "
        f"file_hash={completed.get('file_hash')} md5_of_upload={md5} "
        f"processed_at={completed.get('processed_at')}"
    )

    save_state(
        {
            "run_id": run_id,
            "tenant_id": api.tenant_id,
            "kb_id": kb_id,
            "rw_key_id": rw_id,
            "ro_key_id": ro_id,
            "knowledge_id": kid,
            "pdf_path": str(pdf_path),
            "pdf_sha256": digest,
            "pdf_md5": md5,
        }
    )
    api.close()
    print("setup done")


if __name__ == "__main__":
    main()
