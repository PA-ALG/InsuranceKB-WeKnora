import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path("/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation")
TEST = ROOT / "harness/tests/test_batch_entity_resolution_830_g3.py"
spec = importlib.util.spec_from_file_location("g3_test_helpers", TEST)
assert spec is not None and spec.loader is not None
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)

catalog = helpers.catalog.__wrapped__()
wire = helpers._multi_wire_with_identity_sets(catalog)

# Simulate a self-consistent wire payload that admits one child with a global
# model/source trust blocker into a MULTI parent. Exact-input resolve would
# have cleared these sets; the single-argument wire validator must still reject
# the blocking state per design-2 section 4/6.
child = wire["decisions"][0]["children"][0]
child["disposition"] = "NEEDS_CONFIRM"
child["matched_entity_id"] = None
child["matched_entity_version"] = None
child["entity_candidate"] = None
child["reason_codes"] = ["MODEL_RECEIPT_INVALID"]
child["queue_id"] = "queue-g3"
child["queue_owner"] = "product-owner-g3"
wire = helpers._rehash_resolution_wire(copy.deepcopy(wire))

try:
    parsed = helpers.g.validate_batch(json.dumps(wire, ensure_ascii=False))
except helpers.g.BatchEntityResolutionError as exc:
    print(json.dumps({"status": "REJECTED", "reason_code": exc.reason_code}, sort_keys=True))
else:
    print(json.dumps({
        "status": "ACCEPTED_BLOCKER",
        "parent": parsed.decisions[0].disposition,
        "child": parsed.decisions[0].children[0].disposition,
        "child_reasons": list(parsed.decisions[0].children[0].reason_codes),
        "name_set_count": len(parsed.decisions[0].children[0].multi_identity_name_evidence_ids),
        "code_set_count": len(parsed.decisions[0].children[0].multi_identity_code_evidence_ids),
    }, ensure_ascii=False, sort_keys=True))
