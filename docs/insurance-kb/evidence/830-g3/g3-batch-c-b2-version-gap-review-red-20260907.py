from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO = Path(
    "/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/.worktrees/830-g3-implementation"
)
TEST_MODULE = REPO / "harness/tests/test_batch_entity_resolution_830_g3.py"

spec = importlib.util.spec_from_file_location("g3_c_tests_b2_review", TEST_MODULE)
assert spec is not None and spec.loader is not None
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)

catalog = t.compile_catalog(
    t._WORKBOOK.read_bytes(),
    json.loads(t._CONFIG.read_text(encoding="utf-8")),
)
entry = t._entry(
    material_id="b2-version-gap",
    text=(
        "平安保险 产品甲 产品代码 CODE-A 医疗保险 "
        "平安保险 产品乙 产品代码 CODE-B 医疗保险 官方条款"
    ),
)
result = t._resolve(
    catalog,
    (entry,),
    (
        (
            {
                "proposal_ref": "a",
                "name": "产品甲",
                "product_code": "CODE-A",
                "version_label": None,
                "filing": None,
            },
            {
                "proposal_ref": "b",
                "name": "产品乙",
                "product_code": "CODE-B",
                "version_label": None,
                "filing": None,
            },
        ),
    ),
)
parent = result.decisions[0]
actual = {
    "parent_disposition": parent.disposition,
    "parent_reason_codes": list(parent.reason_codes),
    "children": [
        {
            "proposal_ref": child.proposal_ref,
            "disposition": child.disposition,
            "reason_codes": list(child.reason_codes),
            "entity_candidate": child.entity_candidate,
        }
        for child in parent.children
    ],
}
print(json.dumps(actual, ensure_ascii=False, indent=2, default=str))

# Frozen contract expectation: distinct, independently evidenced name/code identities
# retain parent MULTI while version-incomplete children remain human-only.
assert parent.disposition == "MULTI"
assert all(child.disposition == "NEEDS_CONFIRM" for child in parent.children)
assert all("VERSION_UNRESOLVED" in child.reason_codes for child in parent.children)
assert all(child.entity_candidate is None for child in parent.children)
