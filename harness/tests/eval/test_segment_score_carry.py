"""S12c-4 acceptance (protected, written by Claude): segment scoring counts step one's selection
only. Evidence cut from segment_ids ∪ carried_segment_ids is consistent, and only segment_ids are
scored; evidence that matches neither still falls back to locating every quote (Spec
docs/design/slices/S12c-4-复用已审证据段.md §2.3; Codex R1 on #412).
"""

from __future__ import annotations

import json
from pathlib import Path

from insurance_harness.compilers.schema_fields.engine import FieldResult
from insurance_harness.eval.segment_score import load_golden_v2, score_selection
from tests.eval.test_segment_score import SOURCE, evidence

# D1P1S1 等待期 (step one's selection), D1P2S1 保险期间 (carried), D1P2S2 不设宽限期
S1 = ("1.4 等待期自本合同生效之日起90日内为等待期。", 1)
S4 = ("1.5 保险期间\n本合同保险期间为一年。", 2)


def compiled(cut: list[str], carried: list[str]) -> FieldResult:
    return FieldResult(
        field_key="waiting_period", state="present", value="x", evidence=SOURCE.evidence(cut),
        segment_ids=["D1P1S1"], carried_segment_ids=carried,
    )


def score(tmp_path: Path, result: FieldResult, gold: tuple[str, int]) -> tuple[object, object]:
    path = tmp_path / "1818.json"
    path.write_text(json.dumps({
        "product_id": "1818",
        "cards_version": "test",
        "fields": [{
            "field_key": "waiting_period", "state": "present", "value": "90日", "reason": "条款",
            "evidence": [evidence(*gold)],
        }],
    }, ensure_ascii=False), encoding="utf-8")
    [field] = score_selection(SOURCE, load_golden_v2(path), [result]).fields
    return field.recall, field.precision


def test_a_carried_segment_neither_earns_recall_nor_costs_precision(tmp_path: Path) -> None:
    result = compiled(["D1P1S1", "D1P2S1"], ["D1P2S1"])
    assert score(tmp_path, result, S4) == (0.0, 0.0), "Golden only on the carried segment"
    assert score(tmp_path, result, S1) == (1.0, 1.0), "Golden only on step one's selection"


def test_old_outputs_keep_their_score_and_evidence_matching_neither_falls_back(
    tmp_path: Path,
) -> None:
    assert score(tmp_path, compiled(["D1P1S1"], []), S1) == (1.0, 1.0)
    # Recorded ids that do not cut the saved evidence are not trusted: every quote is located.
    tampered = compiled(["D1P1S1", "D1P2S2"], ["D1P2S1"])
    assert score(tmp_path, tampered, S1) == (1.0, 0.5)
