"""W0 spike T4: reparse fired during slow pagination — 3 repetitions.

Reader walks pages (page_size=5, 400 ms think-time between pages) with a
GET /knowledge meta read before and after every page. Reparse fires after the
second page. Records what a client can and cannot detect.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from w0lib import Api, load_state, log_json, wait_parsed  # noqa: E402


def meta(api: Api, token: str, kid: str) -> dict:
    d = api.key_request(token, "GET", f"/knowledge/{kid}").json()["data"]
    return {
        "parse_status": d.get("parse_status"),
        "enable_status": d.get("enable_status"),
        "updated_at": d.get("updated_at"),
        "processed_at": d.get("processed_at"),
    }


def main() -> None:
    state = load_state()
    api = Api()
    api.admin_login()
    token = api.find_api_key_token(state["rw_key_id"])
    kid = state["knowledge_id"]

    reps = []
    for rep in range(1, 4):
        pre = api.key_request(
            token, "GET", f"/chunks/{kid}", params={"page": 1, "page_size": 100}
        ).json()
        pre_ids = {c["id"] for c in pre["data"]}
        pre_seq_max = max(c["seq_id"] for c in pre["data"])
        meta_before_walk = meta(api, token, kid)
        assert meta_before_walk["parse_status"] == "completed"

        pages = []
        reparse_fired_at_page = 2
        reparse_time_ms = None
        t0 = time.monotonic()
        page = 1
        while page <= 12:
            m1 = meta(api, token, kid)
            doc = api.key_request(
                token, "GET", f"/chunks/{kid}", params={"page": page, "page_size": 5}
            ).json()
            m2 = meta(api, token, kid)
            ids = [c["id"] for c in doc.get("data") or []]
            pages.append(
                {
                    "t_ms": round((time.monotonic() - t0) * 1000),
                    "page": page,
                    "total": doc.get("total"),
                    "returned": len(ids),
                    "chunk_index": [c["chunk_index"] for c in doc.get("data") or []],
                    "ids_from_old_set": sum(1 for i in ids if i in pre_ids),
                    "ids_from_new_set": sum(1 for i in ids if i not in pre_ids),
                    "min_seq_id": min((c["seq_id"] for c in doc.get("data") or []), default=None),
                    "meta_before_page": m1,
                    "meta_after_page": m2,
                }
            )
            if page == reparse_fired_at_page:
                rp = api.key_request(token, "POST", f"/knowledge/{kid}/reparse")
                rp.raise_for_status()
                reparse_time_ms = round((time.monotonic() - t0) * 1000)
            if len(doc.get("data") or []) < 5 and page > reparse_fired_at_page:
                # keep walking a few extra pages to observe the replaced set
                if page >= 10:
                    break
            page += 1
            time.sleep(0.4)

        # walk-level client detection analysis
        old_seen = sum(p["ids_from_old_set"] for p in pages)
        new_seen = sum(p["ids_from_new_set"] for p in pages)
        totals = sorted({p["total"] for p in pages})
        statuses = []
        for p in pages:
            for m in (p["meta_before_page"], p["meta_after_page"]):
                if not statuses or statuses[-1] != m["parse_status"]:
                    statuses.append(m["parse_status"])
        updated_at_values = sorted(
            {p["meta_before_page"]["updated_at"] for p in pages}
            | {p["meta_after_page"]["updated_at"] for p in pages}
        )
        detection = {
            "mixed_old_and_new_ids_in_one_walk": old_seen > 0 and new_seen > 0,
            "old_ids_seen": old_seen,
            "new_ids_seen": new_seen,
            "distinct_totals_observed": totals,
            "parse_status_sequence_observed": statuses,
            "distinct_updated_at_observed": updated_at_values,
            "new_set_min_seq_gt_old_max": all(
                (p["min_seq_id"] or 0) > pre_seq_max
                for p in pages
                if p["ids_from_new_set"] and p["returned"]
            ),
            "same_attempt_snapshot_provable_from_reads": False,
            "why_not_provable": (
                "no server field ties a page to a parse attempt; detection relies on "
                "comparing updated_at/processed_at/seq_id/id-set across reads, i.e. "
                "timestamp+heuristic comparison, and a page pair straddling the swap "
                "returns without any error or token change"
            ),
        }
        wait_parsed(api, token, kid, timeout_s=420.0)
        reps.append(
            {
                "rep": rep,
                "pre_total": pre.get("total"),
                "reparse_fired_after_page": reparse_fired_at_page,
                "reparse_time_ms": reparse_time_ms,
                "pages": pages,
                "detection": detection,
            }
        )
        print(
            f"rep{rep}: mixed={detection['mixed_old_and_new_ids_in_one_walk']} "
            f"old={old_seen} new={new_seen} totals={totals} statuses={statuses}"
        )
        time.sleep(2)

    log_json("40_t4_race_reps", reps)
    api.close()
    print("t4 done")


if __name__ == "__main__":
    main()
