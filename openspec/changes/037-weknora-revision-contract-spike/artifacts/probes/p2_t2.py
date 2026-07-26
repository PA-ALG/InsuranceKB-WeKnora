"""W0 spike T2: completed-state binding + metadata/chunk swap atomicity sampler.

Per repetition: bracket every chunk-count read between two GET /knowledge reads
(meta double-read). A sample where both meta reads say parse_status=completed
with identical updated_at while the chunk total differs from the settled count
proves the swap is not atomic with the status row.
Repeated 3 times per Contract Card rule for concurrency probes.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from w0lib import BASE_URL, Api, load_state, log_json, wait_parsed  # noqa: E402


def meta_brief(d: dict) -> dict:
    return {
        "parse_status": d.get("parse_status"),
        "enable_status": d.get("enable_status"),
        "updated_at": d.get("updated_at"),
        "processed_at": d.get("processed_at"),
        "summary_status": d.get("summary_status"),
    }


def sampler(token: str, kid: str, stop: threading.Event, out: list) -> None:
    client = httpx.Client(base_url=BASE_URL, timeout=10.0, trust_env=False)
    headers = {"X-API-Key": token}
    t0 = time.monotonic()
    try:
        while not stop.is_set():
            try:
                m1 = client.get(f"/knowledge/{kid}", headers=headers).json()["data"]
                c = client.get(
                    f"/chunks/{kid}",
                    headers=headers,
                    params={"page": 1, "page_size": 1},
                ).json()
                m2 = client.get(f"/knowledge/{kid}", headers=headers).json()["data"]
            except Exception as exc:  # keep sampling through transient errors
                out.append({"t_ms": round((time.monotonic() - t0) * 1000), "error": str(exc)[:120]})
                continue
            first = (c.get("data") or [{}])[0]
            out.append(
                {
                    "t_ms": round((time.monotonic() - t0) * 1000),
                    "meta1": meta_brief(m1),
                    "chunk_total": c.get("total"),
                    "first_chunk_id": first.get("id"),
                    "first_seq_id": first.get("seq_id"),
                    "meta2": meta_brief(m2),
                }
            )
    finally:
        client.close()


def analyze(samples: list, c0: int, first_id0: str) -> dict:
    stale_completed_hits = []
    transitions = []
    last_status = None
    partial_new_visible = []
    for s in samples:
        if "error" in s:
            continue
        st = s["meta1"]["parse_status"]
        if st != last_status:
            transitions.append({"t_ms": s["t_ms"], "parse_status": st,
                               "enable_status": s["meta1"]["enable_status"],
                               "chunk_total": s["chunk_total"]})
            last_status = st
        both_completed = (
            s["meta1"]["parse_status"] == "completed"
            and s["meta2"]["parse_status"] == "completed"
            and s["meta1"]["updated_at"] == s["meta2"]["updated_at"]
        )
        if both_completed and s["chunk_total"] != c0 and s["first_chunk_id"] != first_id0:
            stale_completed_hits.append(s)
        elif both_completed and s["chunk_total"] != c0:
            stale_completed_hits.append(s)
        if s["meta1"]["parse_status"] in ("pending", "processing") and (s["chunk_total"] or 0) > 0:
            partial_new_visible.append(
                {"t_ms": s["t_ms"], "parse_status": s["meta1"]["parse_status"],
                 "chunk_total": s["chunk_total"], "first_seq_id": s["first_seq_id"]}
            )
    return {
        "samples_taken": len(samples),
        "status_transitions_seen": transitions,
        "stale_completed_window_hits": stale_completed_hits,
        "stale_completed_hit_count": len(stale_completed_hits),
        "chunks_visible_while_not_completed": partial_new_visible[:5]
        + ([{"note": f"... {len(partial_new_visible)} total"}] if len(partial_new_visible) > 5 else []),
    }


def main() -> None:
    state = load_state()
    api = Api()
    api.admin_login()
    token = api.find_api_key_token(state["rw_key_id"])
    kid = state["knowledge_id"]

    reps = []
    for rep in range(1, 4):
        pre = api.key_request(token, "GET", f"/knowledge/{kid}").json()["data"]
        cdoc = api.key_request(
            token, "GET", f"/chunks/{kid}", params={"page": 1, "page_size": 1}
        ).json()
        c0 = cdoc.get("total")
        first_id0 = (cdoc.get("data") or [{}])[0].get("id")
        assert pre.get("parse_status") == "completed", pre.get("parse_status")

        stop = threading.Event()
        samples: list = []
        thread = threading.Thread(
            target=sampler, args=(token, kid, stop, samples), daemon=True
        )
        thread.start()
        time.sleep(0.15)
        rp = api.key_request(token, "POST", f"/knowledge/{kid}/reparse")
        rp.raise_for_status()
        wait_parsed(api, token, kid, timeout_s=420.0)
        time.sleep(2.0)
        stop.set()
        thread.join(timeout=15)

        result = {
            "rep": rep,
            "pre_completed_total": c0,
            "pre_first_chunk_id": first_id0,
            "pre_updated_at": pre.get("updated_at"),
            "analysis": analyze(samples, c0, first_id0),
        }
        reps.append(result)
        a = result["analysis"]
        print(
            f"rep{rep}: samples={a['samples_taken']} "
            f"stale_completed_hits={a['stale_completed_hit_count']} "
            f"transitions={[t['parse_status'] for t in a['status_transitions_seen']]}"
        )

    log_json("20_t2_atomicity_reps", reps)

    # Completed-state binding: single-read field availability at completed
    final = api.key_request(token, "GET", f"/knowledge/{kid}").json()["data"]
    kb = api.admin("GET", f"/knowledge-bases/{state['kb_id']}").json()["data"]
    log_json(
        "21_t2_completed_binding",
        {
            "knowledge_completed_read": final,
            "kb_config_snapshot": kb,
            "note": (
                "parser/chunker identity fields available only as mutable KB-level "
                "config; knowledge carries embedding_model_id + file_hash(md5) + "
                "client metadata, no parser/chunker version, no attempt"
            ),
        },
    )
    api.close()
    print("t2 done")


if __name__ == "__main__":
    main()
