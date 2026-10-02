"""S2a acceptance (blueprint 1001 §7.7). Protected file: written by Claude.

Contract for the pack-scoped Golden model, the fail-closed evaluator and the
two converters. Synthetic cases pin the scoring rules; one case converts the
real approved Golden gs-s0q-596-v1 against the v5 catalog.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from insurance_harness.eval.catalog import load_catalog
from insurance_harness.eval.convert import golden_from_legacy, predictions_from_candidate
from insurance_harness.eval.evaluator import evaluate, gate
from insurance_harness.eval.golden import (
    GoldenEvidence,
    GoldenItem,
    Prediction,
    ValueComponent,
)

REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / "internal/handler/schema_pack_catalog_830_g3.generated.json"
LEGACY_596 = REPO / "dataset/goldenset/gs-s0q-596-v1/596.jsonl"
DATASET_ROOT = REPO / "dataset/shouxian_product"
PACK = "schemapack_medical_insurance"


def ev(page: int = 3, quote: str = "等待期为90日", sha: str = "a" * 64) -> GoldenEvidence:
    return GoldenEvidence(document="保险条款.pdf", document_sha256=sha, page=page, quote=quote)


StateName = Literal["present", "absent_explicitly", "unknown"]


def golden(
    field: str,
    state: StateName = "present",
    value: str | None = "90日",
    *,
    evidence: list[GoldenEvidence] | None = None,
    components: list[ValueComponent] | None = None,
    forbidden: tuple[str, ...] = (),
) -> GoldenItem:
    if evidence is None:
        evidence = [ev()] if state != "unknown" else []
    return GoldenItem(
        pack_id=PACK,
        product_id="p1",
        field_key=field,
        state=state,
        value=value,
        evidence=evidence,
        components=components or [],
        forbidden=forbidden,
        judged_by="human:test",
    )


def pred(field: str, state: StateName = "present", value: str | None = "90日") -> Prediction:
    return Prediction(pack_id=PACK, product_id="p1", field_key=field, state=state, value=value)


# ---- Golden model invariants (blueprint §5.1 three-state rules) -------------------------


def test_present_requires_value_and_evidence() -> None:
    with pytest.raises(ValidationError):
        golden("waiting_period", value=None)
    with pytest.raises(ValidationError):
        golden("waiting_period", evidence=[])


def test_absent_explicitly_requires_null_value_and_evidence() -> None:
    golden("guaranteed_renewal_status", state="absent_explicitly", value=None)
    with pytest.raises(ValidationError):
        golden("guaranteed_renewal_status", state="absent_explicitly", value="不保证续保")
    with pytest.raises(ValidationError):
        golden("guaranteed_renewal_status", state="absent_explicitly", value=None, evidence=[])


def test_unknown_carries_no_value_or_evidence() -> None:
    golden("deductible_rules", state="unknown", value=None)
    with pytest.raises(ValidationError):
        golden("deductible_rules", state="unknown", value="1万", evidence=[])


def test_evidence_requires_document_hash() -> None:
    with pytest.raises(ValidationError):
        GoldenEvidence(document="保险条款.pdf", document_sha256="not-a-hash", page=1, quote="x")


# ---- Scoring rules -----------------------------------------------------------------------


def test_correct_mismatch_missed_and_hallucination_are_counted_per_field() -> None:
    items = [
        golden("waiting_period"),
        golden("cooling_off_period", value="15日"),
        golden("coverage_period", value="1年"),
        golden("deductible_rules", state="unknown", value=None),
    ]
    preds = [
        pred("waiting_period", value="90 日"),  # normalised equality -> correct
        pred("cooling_off_period", value="10日"),  # mismatch
        pred("deductible_rules", value="1万元"),  # golden unknown -> hallucination
    ]
    report = evaluate(items, preds)
    f = report.per_field
    assert (f["waiting_period"].tp, f["waiting_period"].fp, f["waiting_period"].fn) == (1, 0, 0)
    cooling = f["cooling_off_period"]
    assert (cooling.tp, cooling.fp, cooling.fn) == (0, 1, 1)
    assert (f["coverage_period"].tp, f["coverage_period"].fn) == (0, 1)
    assert f["deductible_rules"].fp == 1
    assert report.hallucinations == 1
    assert report.missing_predictions == 1


def test_present_against_absent_explicitly_is_contradiction_not_hallucination() -> None:
    items = [golden("guaranteed_renewal_status", state="absent_explicitly", value=None)]
    report = evaluate(items, [pred("guaranteed_renewal_status", value="保证续保5年")])
    assert report.contradictions == 1
    assert report.hallucinations == 0
    assert report.per_field["guaranteed_renewal_status"].fp == 1


def test_matching_non_present_states_are_correct_without_affecting_precision() -> None:
    items = [golden("deductible_rules", state="unknown", value=None)]
    report = evaluate(items, [pred("deductible_rules", state="unknown", value=None)])
    assert report.correct_non_present == 1
    assert report.per_pack[PACK].precision is None


def test_components_require_every_atom() -> None:
    components = [
        ValueComponent(name="时长", accepted=("90日", "90天")),
        ValueComponent(name="意外例外", accepted=("意外伤害", "意外")),
    ]
    items = [golden("waiting_period", value="90日，意外伤害无等待期", components=components)]
    assert evaluate(items, [pred("waiting_period", value="等待期90天，因意外伤害除外")]).per_field[
        "waiting_period"
    ].tp == 1
    partial = evaluate(items, [pred("waiting_period", value="等待期90天")])
    assert partial.per_field["waiting_period"].tp == 0
    assert partial.component_misses == {"p1/waiting_period": ["意外例外"]}


def test_forbidden_terms_reject_otherwise_matching_value() -> None:
    items = [golden("exclusions", value="既往症除外", forbidden=("等情形",))]
    report = evaluate(items, [pred("exclusions", value="既往症除外等情形")])
    assert report.per_field["exclusions"].tp == 0


def test_predictions_outside_golden_are_unscored_not_hallucinated() -> None:
    report = evaluate(
        [golden("waiting_period")],
        [pred("waiting_period"), pred("coverage_period", value="1年")],
    )
    assert report.unscored_predictions == 1
    assert report.hallucinations == 0


# ---- Fail-closed metrics and gate --------------------------------------------------------


def test_zero_denominator_is_none_not_one() -> None:
    report = evaluate([golden("deductible_rules", state="unknown", value=None)], [])
    assert report.per_pack[PACK].precision is None
    assert report.per_pack[PACK].recall is None
    assert report.micro.precision is None


def test_gate_fails_closed_without_denominator() -> None:
    report = evaluate([golden("deductible_rules", state="unknown", value=None)], [])
    verdict = gate(report, PACK)
    assert not verdict.passed
    assert "precision_undefined" in verdict.reasons


def test_gate_thresholds_and_hallucination() -> None:
    ok = evaluate([golden("waiting_period")], [pred("waiting_period")])
    assert gate(ok, PACK).passed
    halluc = evaluate(
        [golden("waiting_period"), golden("deductible_rules", state="unknown", value=None)],
        [pred("waiting_period"), pred("deductible_rules", value="1万")],
    )
    assert "hallucination" in gate(halluc, PACK).reasons


# ---- Converters ---------------------------------------------------------------------------


def test_catalog_resolves_pack_and_field_by_chinese_title() -> None:
    catalog = load_catalog(CATALOG)
    assert catalog.pack_id("医疗险") == PACK
    assert catalog.field_key(PACK, "等待期") == "waiting_period"
    assert len(catalog.fields(PACK)) == 67


def test_legacy_596_golden_converts_to_v5_keys() -> None:
    catalog = load_catalog(CATALOG)
    result = golden_from_legacy(
        LEGACY_596, catalog, pack_display_name="医疗险", dataset_root=DATASET_ROOT
    )
    assert len(result.items) == 40
    assert len(result.unmapped) == 20
    assert {i.state for i in result.items} == {"present", "unknown", "absent_explicitly"}
    assert all(i.pack_id == PACK and i.product_id == "596" for i in result.items)
    assert all(i.judged_by.startswith("legacy:") for i in result.items)
    # absent_explicitly values are moved to note, per the blueprint rule that absent has no value.
    absent = [i for i in result.items if i.state == "absent_explicitly"]
    assert absent and all(i.value is None and i.note for i in absent)
    terms = DATASET_ROOT / "平安e生保（尊享版）医疗保险" / "保险条款.pdf"
    want = hashlib.sha256(terms.read_bytes()).hexdigest()
    assert any(e.document_sha256 == want for i in result.items for e in i.evidence)


def test_candidate_predictions_map_entities_and_fail_on_unknown_names() -> None:
    bindings: list[dict[str, object]] = [
        {
            "entity_id": "e1",
            "display_name": "平安 e 生保（尊享版）医疗保险",
            "schema_pack_id": PACK,
        },
        {"entity_id": "e2", "display_name": "未登记产品", "schema_pack_id": PACK},
    ]
    field = {
        "entity_id": "e1",
        "field_key": "waiting_period",
        "state": "present",
        "value": "90日",
        "evidence": [{"page_number": 3, "quote": "等待期为90日"}],
    }
    candidate: dict[str, object] = {
        "request": {"entity_bindings": bindings},
        "compile_result": {"output": {"fields": [field]}},
    }
    names = {"平安e生保（尊享版）医疗保险": "596"}
    with pytest.raises(ValueError, match="未登记产品"):
        predictions_from_candidate(candidate, names)
    bindings.pop()
    preds = predictions_from_candidate(candidate, names)
    assert preds == [
        Prediction(
            pack_id=PACK,
            product_id="596",
            field_key="waiting_period",
            state="present",
            value="90日",
        )
    ]


def test_report_serialises_to_json() -> None:
    report = evaluate([golden("waiting_period")], [pred("waiting_period")])
    data = json.loads(report.model_dump_json())
    assert data["per_pack"][PACK]["precision"] == 1.0
