"""W0 spike T5: delete/disable surfaces, ACL granularity, delete-vs-read race x3.

Safety: mutates only w0-spike- scratch objects. Pre-existing KBs/knowledge are
touched with read-only GETs whose *expected and observed* outcome is 403.
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from w0lib import (  # noqa: E402
    Api,
    build_pdf,
    envelope_summary,
    load_state,
    log_json,
    wait_parsed,
)


def upload_scratch(api: Api, token: str, kb_id: str, run_id: str, variant: int) -> str:
    pdf = build_pdf(pages=3, lines_per_page=20 + variant)
    digest = hashlib.sha256(pdf).hexdigest()
    name = f"w0-spike-doc-{run_id}-race{variant}.pdf"
    path = Path(__file__).with_name(name)
    path.write_bytes(pdf)
    with path.open("rb") as fh:
        up = api.key_request(
            token,
            "POST",
            f"/knowledge-bases/{kb_id}/knowledge/file",
            files={"file": (name, fh, "application/pdf")},
            data={"metadata": f'{{"owner": "w0-spike-{run_id}", "sha256": "{digest}"}}'},
            timeout=120.0,
        )
    up.raise_for_status()
    kid = up.json()["data"]["id"]
    wait_parsed(api, token, kid, timeout_s=420.0)
    return kid


def delete_race(api: Api, token: str, kid: str) -> dict:
    reads = []
    delete_summary = None
    t0 = time.monotonic()
    for i in range(40):
        chunks = api.key_request(
            token, "GET", f"/chunks/{kid}", params={"page": 1, "page_size": 5}
        )
        know = api.key_request(token, "GET", f"/knowledge/{kid}")
        try:
            cbody = chunks.json()
        except Exception:
            cbody = {"_raw": chunks.text[:120]}
        try:
            kbody = know.json()
        except Exception:
            kbody = {"_raw": know.text[:120]}
        kdata = kbody.get("data") if isinstance(kbody, dict) else None
        reads.append(
            {
                "t_ms": round((time.monotonic() - t0) * 1000),
                "chunks_status": chunks.status_code,
                "chunks_total": cbody.get("total") if isinstance(cbody, dict) else None,
                "chunks_error": (cbody.get("error") or cbody.get("message"))
                if isinstance(cbody, dict) and chunks.status_code != 200
                else None,
                "knowledge_status": know.status_code,
                "knowledge_parse_status": (kdata or {}).get("parse_status")
                if isinstance(kdata, dict)
                else None,
                "knowledge_error": (kbody.get("error") or kbody.get("message"))
                if isinstance(kbody, dict) and know.status_code != 200
                else None,
            }
        )
        if i == 2:
            resp = api.key_request(token, "DELETE", f"/knowledge/{kid}")
            delete_summary = envelope_summary(resp)
            delete_summary["t_ms"] = round((time.monotonic() - t0) * 1000)
        if know.status_code in (403, 404) and chunks.status_code in (403, 404) and i > 6:
            break
        time.sleep(0.15)
    return {"delete_response": delete_summary, "reads": reads}


def main() -> None:
    state = load_state()
    api = Api()
    api.admin_login()
    rw = api.find_api_key_token(state["rw_key_id"])
    ro = api.find_api_key_token(state["ro_key_id"])
    main_key = api.find_api_key_token(int(api.env["LOCAL_LIVE_API_KEY_ID"]))
    kb_id = state["kb_id"]
    kid = state["knowledge_id"]
    out: dict = {}

    # ---------------------------------------------- disable surfaces (scratch)
    chunks = api.key_request(
        token=rw, method="GET", path=f"/chunks/{kid}", params={"page": 1, "page_size": 2}
    ).json()["data"]
    target_chunk = chunks[1]["id"]
    dis = api.key_request(
        rw,
        "PUT",
        f"/chunks/{kid}/{target_chunk}",
        json_body={"content": chunks[1]["content"], "is_enabled": False,
                   "chunk_index": chunks[1]["chunk_index"],
                   "start_at": chunks[1]["start_at"], "end_at": chunks[1]["end_at"]},
    )
    after = api.key_request(rw, "GET", f"/chunks/by-id/{target_chunk}").json().get("data") or {}
    reen = api.key_request(
        rw,
        "PUT",
        f"/chunks/{kid}/{target_chunk}",
        json_body={"content": chunks[1]["content"], "is_enabled": True,
                   "chunk_index": chunks[1]["chunk_index"],
                   "start_at": chunks[1]["start_at"], "end_at": chunks[1]["end_at"]},
    )
    out["chunk_disable"] = {
        "put_disable": envelope_summary(dis),
        "chunk_after_disable_is_enabled": after.get("is_enabled"),
        "chunk_after_disable_updated_at": after.get("updated_at"),
        "put_reenable_status": reen.status_code,
    }

    ke = api.key_request(rw, "PUT", f"/knowledge/{kid}", json_body={"enable_status": "disabled"})
    know_after = api.key_request(rw, "GET", f"/knowledge/{kid}").json()["data"]
    out["knowledge_disable_attempt"] = {
        "put_response": envelope_summary(ke),
        "enable_status_after": know_after.get("enable_status"),
        "finding": "PUT /knowledge/:id accepts the body but only title/description are updatable; enable_status silently unchanged",
    }

    cancel = api.key_request(rw, "POST", f"/knowledge/{kid}/cancel-parse")
    out["cancel_parse_on_completed"] = envelope_summary(cancel)

    # ------------------------------------------------------- ACL granularity
    acl: dict = {}
    acl["ro_key_read_chunks"] = envelope_summary(
        api.key_request(ro, "GET", f"/chunks/{kid}", params={"page": 1, "page_size": 1})
    )
    acl["ro_key_read_chunks"]["body"] = {"total": acl["ro_key_read_chunks"]["body"].get("total")}
    acl["ro_key_reparse"] = envelope_summary(
        api.key_request(ro, "POST", f"/knowledge/{kid}/reparse")
    )
    acl["ro_key_delete_knowledge"] = envelope_summary(
        api.key_request(ro, "DELETE", f"/knowledge/{kid}")
    )
    raw_kb = api.env["LOCAL_LIVE_RAW_KB_ID"]
    acl["scratch_rw_key_list_other_kb_readonly"] = envelope_summary(
        api.key_request(rw, "GET", f"/knowledge-bases/{raw_kb}/knowledge",
                        params={"page": 1, "page_size": 1})
    )
    acl["scratch_rw_key_get_other_knowledge_readonly"] = envelope_summary(
        api.key_request(rw, "GET", f"/knowledge/{api.env['LOCAL_LIVE_KNOWLEDGE_ID']}")
    )
    acl["main_key_list_scratch_kb_readonly"] = envelope_summary(
        api.key_request(main_key, "GET", f"/knowledge-bases/{kb_id}/knowledge",
                        params={"page": 1, "page_size": 1})
    )
    acl["scratch_rw_key_clear_kb_contents_requires_full_access"] = envelope_summary(
        api.key_request(rw, "DELETE", f"/knowledge-bases/{kb_id}/knowledge")
    )
    acl["scratch_rw_key_batch_delete_jwt_only"] = envelope_summary(
        api.key_request(rw, "POST", "/knowledge/batch-delete", json_body={"ids": [kid]})
    )
    out["acl"] = acl

    log_json("50_t5_disable_and_acl", out)
    print("chunk disable:", out["chunk_disable"]["put_disable"]["status_code"],
          "-> is_enabled", out["chunk_disable"]["chunk_after_disable_is_enabled"])
    print("knowledge disable attempt:", out["knowledge_disable_attempt"]["put_response"]["status_code"],
          "-> enable_status", out["knowledge_disable_attempt"]["enable_status_after"])
    for k, v in acl.items():
        print(f"acl {k}: {v['status_code']}")

    # --------------------------------------------------- delete race x3
    races = []
    race1 = delete_race(api, rw, kid)
    races.append({"rep": 1, "knowledge_id": kid, **race1})
    print("race1 last reads:", [(r['chunks_status'], r['knowledge_status']) for r in race1['reads'][-3:]])
    for rep in (2, 3):
        new_kid = upload_scratch(api, rw, kb_id, state["run_id"], rep)
        race = delete_race(api, rw, new_kid)
        races.append({"rep": rep, "knowledge_id": new_kid, **race})
        print(f"race{rep} last reads:", [(r['chunks_status'], r['knowledge_status']) for r in race['reads'][-3:]])
    log_json("51_t5_delete_race_reps", races)
    api.close()
    print("t5 done")


if __name__ == "__main__":
    main()
