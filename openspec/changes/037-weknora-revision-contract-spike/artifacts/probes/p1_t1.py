"""W0 spike T1: stable identity across reparse (2 reparse cycles + field diff)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from w0lib import (  # noqa: E402
    Api,
    chunk_brief,
    envelope_summary,
    load_state,
    log_json,
    wait_parsed,
)


def snapshot(api: Api, token: str, kid: str) -> dict:
    know = api.key_request(token, "GET", f"/knowledge/{kid}")
    know.raise_for_status()
    spans = api.key_request(token, "GET", f"/knowledge/{kid}/spans")
    chunks = api.key_request(
        token, "GET", f"/chunks/{kid}", params={"page": 1, "page_size": 100}
    )
    chunks.raise_for_status()
    cdoc = chunks.json()
    sp = spans.json() if spans.status_code == 200 else {"status": spans.status_code}
    sp_data = sp.get("data") or {}
    return {
        "knowledge": know.json()["data"],
        "spans_current_attempt": sp_data.get("current_attempt"),
        "spans_parse_status": sp_data.get("parse_status"),
        "spans_root_output": (sp_data.get("trace") or {}).get("output"),
        "chunks_total": cdoc.get("total"),
        "chunks": [chunk_brief(c) for c in cdoc.get("data") or []],
    }


def wait_summary_settled(api: Api, token: str, kid: str, timeout_s: float = 180.0) -> dict:
    deadline = time.monotonic() + timeout_s
    last = {}
    while time.monotonic() < deadline:
        resp = api.key_request(token, "GET", f"/knowledge/{kid}")
        resp.raise_for_status()
        last = resp.json()["data"]
        if last.get("summary_status") in ("completed", "failed", "none", ""):
            return last
        time.sleep(2.0)
    return last


def diff_fields(a: dict, b: dict) -> dict:
    keys = sorted(set(a) | set(b))
    stable, changed = [], {}
    for k in keys:
        if a.get(k) == b.get(k):
            stable.append(k)
        else:
            changed[k] = {"before": a.get(k), "after": b.get(k)}
    return {"stable": stable, "changed": changed}


def main() -> None:
    state = load_state()
    api = Api()
    api.admin_login()
    token = api.find_api_key_token(state["rw_key_id"])
    kid = state["knowledge_id"]

    wait_summary_settled(api, token, kid)
    snap1 = snapshot(api, token, kid)
    log_json("10_t1_attempt1_settled", snap1)
    print(
        f"attempt1 settled: summary={snap1['knowledge'].get('summary_status')} "
        f"attempt={snap1['spans_current_attempt']} chunks={snap1['chunks_total']}"
    )

    reparse_evidence = []
    snaps = [snap1]
    for n in (2, 3):
        rep = api.key_request(token, "POST", f"/knowledge/{kid}/reparse")
        summary = envelope_summary(rep)
        reparse_evidence.append(summary)
        rep.raise_for_status()
        immediately = summary["body"].get("data") or {}
        print(
            f"reparse -> {rep.status_code}; immediate parse_status="
            f"{immediately.get('parse_status')} enable_status={immediately.get('enable_status')}"
        )
        wait_parsed(api, token, kid, timeout_s=420.0)
        wait_summary_settled(api, token, kid)
        snap = snapshot(api, token, kid)
        snaps.append(snap)
        log_json(f"1{n - 1}_t1_attempt{n}_settled", snap)
        print(
            f"attempt{n} settled: attempt={snap['spans_current_attempt']} "
            f"chunks={snap['chunks_total']} processed_at={snap['knowledge'].get('processed_at')}"
        )

    analysis: dict = {"reparse_responses": reparse_evidence, "pairs": {}}
    for i in range(len(snaps) - 1):
        a, b = snaps[i], snaps[i + 1]
        ids_a = {c["id"] for c in a["chunks"]}
        ids_b = {c["id"] for c in b["chunks"]}
        seq_a = [c["seq_id"] for c in a["chunks"]]
        seq_b = [c["seq_id"] for c in b["chunks"]]
        analysis["pairs"][f"attempt{i + 1}->attempt{i + 2}"] = {
            "knowledge_field_diff": diff_fields(a["knowledge"], b["knowledge"]),
            "chunk_id_overlap": len(ids_a & ids_b),
            "chunk_count": [len(ids_a), len(ids_b)],
            "seq_id_range": [[min(seq_a), max(seq_a)], [min(seq_b), max(seq_b)]],
            "seq_strictly_increased": min(seq_b) > max(seq_a),
            "chunk_index_sequence_b": [c["chunk_index"] for c in b["chunks"]][:10],
            "spans_attempt": [a["spans_current_attempt"], b["spans_current_attempt"]],
        }
    log_json("13_t1_analysis", analysis)
    api.close()
    print("t1 done")


if __name__ == "__main__":
    main()
