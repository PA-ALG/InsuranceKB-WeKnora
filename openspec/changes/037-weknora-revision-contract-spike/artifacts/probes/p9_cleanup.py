"""W0 spike cleanup: remove all w0-spike- scratch objects, record evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from w0lib import Api, envelope_summary, load_state, log_json  # noqa: E402


def main() -> None:
    state = load_state()
    api = Api()
    api.admin_login()
    kb_id = state["kb_id"]
    evidence: dict = {"run_id": state["run_id"]}

    # residual knowledge inside scratch KB (should be none after T5 races)
    listing = api.admin(
        "GET", f"/knowledge-bases/{kb_id}/knowledge", params={"page": 1, "page_size": 100}
    )
    residual = listing.json().get("data") or [] if listing.status_code == 200 else []
    deletes = []
    for item in residual:
        resp = api.admin("DELETE", f"/knowledge/{item['id']}")
        deletes.append({"id": item["id"], "status": resp.status_code})
    evidence["residual_knowledge_before_kb_delete"] = [
        {"id": item["id"], "file_name": item.get("file_name")} for item in residual
    ]
    evidence["residual_knowledge_deletes"] = deletes

    # delete scratch KB
    resp = api.admin("DELETE", f"/knowledge-bases/{kb_id}")
    evidence["kb_delete_response"] = envelope_summary(resp)

    # delete scratch API keys
    for key_name in ("rw_key_id", "ro_key_id"):
        resp = api.admin(
            "DELETE", f"/tenants/{api.tenant_id}/api-keys/{state[key_name]}"
        )
        evidence[f"{key_name}_delete_status"] = resp.status_code

    # residue check: no w0-spike- anywhere visible
    kbs = api.admin("GET", "/knowledge-bases")
    kbs.raise_for_status()
    kb_list = kbs.json()["data"]
    evidence["kb_names_after"] = [kb["name"] for kb in kb_list]
    evidence["w0_spike_kb_residue"] = [
        kb["name"] for kb in kb_list if "w0-spike-" in (kb.get("name") or "")
    ]
    keys = api.admin("GET", f"/tenants/{api.tenant_id}/api-keys")
    key_names = [k.get("name") for k in keys.json().get("data") or []]
    evidence["api_key_names_after"] = key_names
    evidence["w0_spike_key_residue"] = [n for n in key_names if "w0-spike-" in (n or "")]

    # per-KB knowledge residue check + no-touch diff against baseline
    baseline = json.loads(
        (Path(__file__).with_name("results") / "00_baseline_readonly.json").read_text()
    )
    after_by_kb = {}
    knowledge_residue = []
    for kb in kb_list:
        resp = api.admin(
            "GET", f"/knowledge-bases/{kb['id']}/knowledge", params={"page": 1, "page_size": 100}
        )
        items = resp.json().get("data") or [] if resp.status_code == 200 else []
        after_by_kb[kb["id"]] = [
            {
                "id": item["id"],
                "file_name": item.get("file_name"),
                "updated_at": item.get("updated_at"),
                "parse_status": item.get("parse_status"),
            }
            for item in items
        ]
        knowledge_residue.extend(
            item.get("file_name")
            for item in items
            if "w0-spike" in (item.get("file_name") or "")
            or "w0-spike" in json.dumps(item.get("metadata") or {})
        )
    evidence["w0_spike_knowledge_residue"] = knowledge_residue

    pre_kbs = {kb["id"]: kb for kb in baseline["knowledge_bases"]}
    diff = {}
    for kb_id_pre, pre in pre_kbs.items():
        pre_items = baseline["knowledge_by_kb"].get(kb_id_pre)
        post_items = after_by_kb.get(kb_id_pre)
        if isinstance(pre_items, list):
            same = pre_items == post_items
        else:
            same = post_items is not None or pre_items is not None
        diff[kb_id_pre] = {
            "name": pre["name"],
            "knowledge_identical_to_baseline": same,
        }
    evidence["preexisting_kb_no_touch_diff"] = diff

    log_json("90_cleanup_evidence", evidence)
    ok = (
        not evidence["w0_spike_kb_residue"]
        and not evidence["w0_spike_key_residue"]
        and not evidence["w0_spike_knowledge_residue"]
        and all(d["knowledge_identical_to_baseline"] for d in diff.values())
    )
    print("kb delete:", evidence["kb_delete_response"]["status_code"])
    print("key deletes:", evidence["rw_key_id_delete_status"], evidence["ro_key_id_delete_status"])
    print("residue kb/key/knowledge:", evidence["w0_spike_kb_residue"],
          evidence["w0_spike_key_residue"], evidence["w0_spike_knowledge_residue"])
    print("pre-existing untouched:", all(d["knowledge_identical_to_baseline"] for d in diff.values()))
    print("CLEANUP", "OK" if ok else "ATTENTION-NEEDED")
    api.close()


if __name__ == "__main__":
    main()
