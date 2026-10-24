"""RV4c acceptance: the versioned spot-check policy (Spec §2.3).

Protected file: written by Claude. Sampling rates, minimums, target precision and must-check fields
are data, versioned like the review policy; while the critical illness pilot runs, every machine
reviewed claim is checked (rate 1.0), and the must-check fields are fields of that pack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.catalog import SCHEMA_PACK_CATALOG
from insurance_harness.catalog.spot_check import SpotCheckPolicyError, load_spot_check_policy

REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / SCHEMA_PACK_CATALOG
PILOT = "schemapack_critical_illness_insurance"


def test_the_shipped_policy_checks_every_machine_claim_of_the_pilot() -> None:
    policy = load_spot_check_policy()
    rule = policy.for_pack(PILOT)
    assert rule.rate == 1.0 and rule.minimum >= 1 and 0 < rule.target <= 1
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    [pack] = [e["pack"] for e in catalog["entries"] if e["pack"]["schema_pack_id"] == PILOT]
    assert rule.must_check and set(rule.must_check) <= {f["field_key"] for f in pack["fields"]}
    assert policy.for_pack("a_pack_without_rules") == policy.default


def policy(**changes: Any) -> dict[str, Any]:
    rule = {"rate": 0.5, "minimum": 3, "target": 0.9, "must_check": ["a"]}
    data: dict[str, Any] = {"version": "t", "default": rule, "packs": {"p": rule}}
    data.update(changes)
    return data


BAD_RULE = {"rate": 0.5, "minimum": 3, "target": 0.9, "must_check": ["a"]}


@pytest.mark.parametrize(
    "data",
    [
        policy(version=" "),
        policy(default={**BAD_RULE, "rate": 1.5}),
        policy(packs={"p": {**BAD_RULE, "target": 0}}),
        policy(packs={"p": {**BAD_RULE, "target": True}}),
        policy(packs={"p": {**BAD_RULE, "minimum": -1}}),
        policy(packs={"p": {**BAD_RULE, "must_check": ["a", "a"]}}),
        policy(packs={"p": {**BAD_RULE, "must_check": [" "]}}),
        policy(extra=1),
    ],
    ids=["blank version", "rate", "target zero", "target bool", "minimum", "dup", "blank", "extra"],
)
def test_a_malformed_policy_is_refused_with_a_fixed_code(tmp_path: Path, data: Any) -> None:
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(SpotCheckPolicyError) as refused:
        load_spot_check_policy(path)
    assert refused.value.code == "SPOT_CHECK_POLICY_INVALID"


def test_an_unreadable_policy_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SpotCheckPolicyError):
        load_spot_check_policy(tmp_path / "missing.json")
