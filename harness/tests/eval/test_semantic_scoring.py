"""S2c acceptance: score candidates by semantic equivalence (blueprint §7.7).

Protected file: written by Claude. Pins §2-§3 of the S2c spec.

Literal component matching cannot measure long answers: the S2b Golden values
match their own components in only 21 of 108 present fields. L1 keeps the cheap
deterministic matches, L2 asks an independent judge whether the candidate
covers the Golden facts, and L3 records attributed rulings. Every missing or
unmatched decision fails closed instead of defaulting to a result.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import pytest

from insurance_harness.eval.equivalence import EQUIVALENCE_PROMPT_VERSION, EquivalenceQuestion
from insurance_harness.eval.evaluator import ItemOutcome, Report, evaluate, gate
from insurance_harness.eval.golden import (
    GoldenEvidence,
    GoldenItem,
    Prediction,
    State,
    ValueComponent,
)
from insurance_harness.eval.semantic import (
    Ruling,
    SemanticVerdict,
    evaluate_semantic,
    semantic_questions,
)
from insurance_harness.eval.semantic_run import main

SHA = "a" * 64
Verdict = Literal["equivalent", "contradicted", "insufficient"]


def gold(
    field: str, state: State, value: str | None = None, *, product: str = "prod-a",
    components: Sequence[tuple[str, str]] = (),
) -> GoldenItem:
    evidence = [] if state == "unknown" else [GoldenEvidence(
        document="terms.pdf", document_sha256=SHA, page=1, quote=value or "不承担",
    )]
    return GoldenItem(
        pack_id=f"pack-{product[-1]}", product_id=product, field_key=field, state=state,
        value=value, evidence=evidence, judged_by="model:test",
        components=[ValueComponent(name=name, accepted=(text,)) for name, text in components],
    )


def pred(
    field: str, state: State, value: str | None = None, *, product: str = "prod-a",
) -> Prediction:
    return Prediction(
        pack_id=f"pack-{product[-1]}", product_id=product, field_key=field, state=state,
        value=value,
    )


def verdict(field: str, value: Verdict, *, product: str = "prod-a") -> SemanticVerdict:
    return SemanticVerdict(product_id=product, field_key=field, verdict=value, reason="理由")


def ruling(field: str, source: str, target: str, *, product: str = "prod-a") -> Ruling:
    return Ruling.model_validate({
        "product_id": product, "field_key": field, "from": source, "to": target,
        "reason": "条款 2.1 / page 3 原文支持该裁定", "by": "Claude Code", "on": "2026-10-07",
    })


# Five Golden fields exercising every L2 verdict plus the deterministic cases.
GOLDEN = [
    gold("a_scope", "present", "意外身故与伤残"),
    gold("b_terms", "present", "10年交、15年交、20年交"),
    gold("c_wait", "present", "等待期30日"),
    gold("d_age", "unknown"),
    gold("e_limit", "present", "每次限额1万元"),
    gold("f_term", "present", "90日"),
]
PREDICTIONS = [
    pred("a_scope", "present", "保障意外身故及意外伤残"),
    pred("b_terms", "present", "交费期间由双方约定"),
    pred("c_wait", "present", "等待期90日"),
    pred("d_age", "present", "18至60周岁"),
    pred("e_limit", "unknown"),
    pred("f_term", "present", "90日"),
]
VERDICTS = [
    verdict("a_scope", "equivalent"),
    verdict("b_terms", "insufficient"),
    verdict("c_wait", "contradicted"),
]


def outcome(report: Report, field: str) -> ItemOutcome:
    return next(item for item in report.outcomes if item.field_key == field)


def test_l1_settles_literal_and_component_matches_and_questions_the_rest() -> None:
    golden = [
        gold("zeta", "present", "身故保险金"),
        gold("alpha", "present", "犹豫期20日"),
        gold("term", "present", "90日"),
        gold("deductible", "present", "免赔额1万元", components=[("免赔额", "1万元")]),
        gold("other", "present", "60日", product="prod-b"),
    ]
    predictions = [
        pred("zeta", "present", "给付身故保险金"),
        pred("alpha", "present", "签收后20日为犹豫期"),
        pred("term", "present", "90日"),
        pred("deductible", "present", "本合同年免赔额为1万元"),
        pred("other", "present", "60 日"),
    ]
    questions = semantic_questions(golden, predictions)
    assert questions == {"prod-a": [
        EquivalenceQuestion(
            field_key="alpha", reference="犹豫期20日", judged="签收后20日为犹豫期", components=[],
        ),
        EquivalenceQuestion(
            field_key="zeta", reference="身故保险金", judged="给付身故保险金", components=[],
        ),
    ]}


def test_l2_verdicts_map_to_correct_incomplete_and_wrong_value() -> None:
    report = evaluate_semantic(GOLDEN, PREDICTIONS, VERDICTS)
    expected = {
        "a_scope": ("correct", "L2", 1, 0, 0),
        "b_terms": ("incomplete", "L2", 0, 1, 1),
        "c_wait": ("wrong_value", "L2", 0, 1, 1),
        "d_age": ("hallucination", None, 0, 1, 0),
        "e_limit": ("missed", None, 0, 0, 1),
        "f_term": ("correct", "L1", 1, 0, 0),
    }
    for field, (result, basis, tp, fp, fn) in expected.items():
        item = outcome(report, field)
        assert (item.result, item.basis, item.tp, item.fp, item.fn) == (result, basis, tp, fp, fn)
    assert outcome(report, "b_terms").reason == "理由"
    metrics = report.per_pack["pack-a"]
    assert (metrics.tp, metrics.fp, metrics.fn) == (2, 3, 3)
    assert metrics.precision == pytest.approx(0.4)
    assert metrics.recall == pytest.approx(0.4)
    assert (report.incomplete, report.wrong_values, report.hallucinations) == (1, 1, 1)
    assert "hallucination" in gate(report, "pack-a").reasons


def test_literal_evaluate_keeps_its_component_measure() -> None:
    report = evaluate(GOLDEN, PREDICTIONS)
    assert outcome(report, "a_scope").result == "mismatch"
    assert outcome(report, "f_term").result == "correct"


@pytest.mark.parametrize("verdicts", [
    VERDICTS[:2],
    [*VERDICTS, verdict("f_term", "equivalent")],
    [*VERDICTS, verdict("a_scope", "contradicted")],
    [*VERDICTS, verdict("a_scope", "equivalent", product="prod-b")],
])
def test_each_question_needs_exactly_one_verdict(verdicts: list[SemanticVerdict]) -> None:
    with pytest.raises(ValueError):
        evaluate_semantic(GOLDEN, PREDICTIONS, verdicts)


def test_verdict_rejects_unknown_labels_and_blank_reasons() -> None:
    for label, reason in (("same", "理由"), ("equivalent", " ")):
        with pytest.raises(ValueError):
            SemanticVerdict.model_validate({
                "product_id": "prod-a", "field_key": "a", "verdict": label, "reason": reason,
            })


def test_rulings_move_items_and_record_l3_basis() -> None:
    rulings = [
        ruling("c_wait", "wrong_value", "correct"),
        ruling("d_age", "hallucination", "misfiled"),
        ruling("b_terms", "incomplete", "golden_defect"),
    ]
    report = evaluate_semantic(GOLDEN, PREDICTIONS, VERDICTS, rulings)
    fixed = outcome(report, "c_wait")
    assert (fixed.result, fixed.basis, fixed.tp, fixed.fp, fixed.fn) == ("correct", "L3", 1, 0, 0)
    assert fixed.reason == "条款 2.1 / page 3 原文支持该裁定"
    misfiled = outcome(report, "d_age")
    assert (misfiled.result, misfiled.fp) == ("misfiled", 1)
    defect = outcome(report, "b_terms")
    assert (defect.result, defect.tp, defect.fp, defect.fn) == ("golden_defect", 0, 0, 0)
    metrics = report.per_pack["pack-a"]
    assert (metrics.tp, metrics.fp, metrics.fn, metrics.hallucinations) == (3, 1, 1, 0)
    assert (report.misfiled, report.golden_defects, report.hallucinations) == (1, 1, 0)
    assert "hallucination" not in gate(report, "pack-a").reasons


def test_hallucination_can_be_ruled_a_golden_defect() -> None:
    report = evaluate_semantic(
        GOLDEN, PREDICTIONS, VERDICTS, [ruling("d_age", "hallucination", "golden_defect")],
    )
    item = outcome(report, "d_age")
    assert (item.result, item.fp, report.hallucinations) == ("golden_defect", 0, 0)


def test_only_l2_correct_items_can_be_tightened() -> None:
    report = evaluate_semantic(
        GOLDEN, PREDICTIONS, VERDICTS, [ruling("a_scope", "correct", "incomplete")],
    )
    assert (outcome(report, "a_scope").result, outcome(report, "a_scope").basis) == (
        "incomplete", "L3",
    )
    with pytest.raises(ValueError):
        evaluate_semantic(
            GOLDEN, PREDICTIONS, VERDICTS, [ruling("f_term", "correct", "incomplete")],
        )


@pytest.mark.parametrize(("source", "target"), [
    ("incomplete", "correct"),
    ("hallucination", "correct"),
    ("wrong_value", "misfiled"),
    ("correct", "golden_defect"),
])
def test_transitions_outside_the_table_are_rejected(source: str, target: str) -> None:
    with pytest.raises(ValueError):
        ruling("b_terms", source, target)


@pytest.mark.parametrize("rulings", [
    [ruling("b_terms", "wrong_value", "correct")],
    [ruling("missing_field", "wrong_value", "correct")],
    [ruling("c_wait", "wrong_value", "correct"), ruling("c_wait", "wrong_value", "incomplete")],
])
def test_rulings_must_match_exactly_one_current_result(rulings: list[Ruling]) -> None:
    with pytest.raises(ValueError):
        evaluate_semantic(GOLDEN, PREDICTIONS, VERDICTS, rulings)


def test_ruling_requires_attribution() -> None:
    with pytest.raises(ValueError):
        Ruling.model_validate({
            "product_id": "prod-a", "field_key": "c_wait", "from": "wrong_value", "to": "correct",
            "reason": "理由", "by": "", "on": "2026-10-07",
        })


# --- File exchange CLI -------------------------------------------------------


def write_inputs(tmp_path: Path) -> list[str]:
    rows = {
        "prod-a": [gold("scope", "present", "意外身故与伤残"), gold("age", "unknown"),
                   gold("term", "present", "90日")],
        "prod-b": [gold("limit", "present", "每次限额1万元", product="prod-b"),
                   gold("wait", "present", "30日", product="prod-b")],
    }
    args = []
    for product, items in rows.items():
        path = tmp_path / f"{product}.jsonl"
        path.write_text("".join(item.model_dump_json() + "\n" for item in items), encoding="utf-8")
        args += ["--golden", str(path)]
    fields = [
        ("prod-a", "scope", "present", "保障意外身故及意外伤残"),
        ("prod-a", "age", "present", "18至60周岁"),
        ("prod-a", "term", "present", "90日"),
        ("prod-b", "limit", "present", "限额为每次一万元"),
        ("prod-b", "wait", "unknown", None),
    ]
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps({
        "request": {"entity_bindings": [
            {"entity_id": product, "display_name": product, "schema_pack_id": f"pack-{product[-1]}"}
            for product in rows
        ]},
        "compile_result": {"output": {"fields": [
            {"entity_id": product, "field_key": key, "state": state, "value": value}
            for product, key, state, value in fields
        ]}},
    }, ensure_ascii=False), encoding="utf-8")
    mapping = tmp_path / "products.json"
    mapping.write_text(json.dumps({product: product for product in rows}))
    return [*args, "--candidate", str(candidate), "--product-map", str(mapping)]


def answer(root: Path, product: str, verdicts: dict[str, str]) -> None:
    stored = json.loads((root / product / "requests" / "001.json").read_text(encoding="utf-8"))
    fields = json.loads("\n".join(stored["user_lines"]))["fields"]
    assert sorted(field["field_key"] for field in fields) == sorted(verdicts)
    (root / product / "responses" / "001.json").write_text(json.dumps({"fields": [
        {"field_key": key, "verdict": value, "reason": "理由"} for key, value in verdicts.items()
    ]}, ensure_ascii=False), encoding="utf-8")


def score(tmp_path: Path, inputs: list[str], root: Path, name: str) -> int:
    return main([
        "score", *inputs, "--run-root", str(root), "--judge-model", "gpt-6-astra",
        "--out", str(tmp_path / "reports" / name),
    ])


def test_prepare_then_score_produces_semantic_and_literal_numbers(tmp_path: Path) -> None:
    inputs = write_inputs(tmp_path)
    root = tmp_path / "run"
    assert main(["prepare", *inputs, "--run-root", str(root)]) == 0
    assert (root / "AGENTS.md").is_file()
    run = json.loads((root / "prod-a" / "run.json").read_text())
    assert run["prompt_version"] == EQUIVALENCE_PROMPT_VERSION
    answer(root, "prod-a", {"scope": "equivalent"})
    answer(root, "prod-b", {"limit": "contradicted"})

    assert score(tmp_path, inputs, root, "raw") == 0
    raw = json.loads((tmp_path / "reports" / "raw.json").read_text())
    assert raw["metric_definition"]["metric_id"] == "golden.semantic_comparison.v1"
    pack_a, pack_b = raw["report"]["per_pack"]["pack-a"], raw["report"]["per_pack"]["pack-b"]
    assert (pack_a["tp"], pack_a["fp"], pack_a["fn"]) == (2, 1, 0)
    assert (pack_b["tp"], pack_b["fp"], pack_b["fn"]) == (0, 1, 2)
    assert raw["gates"]["pack-a"]["passed"] is False
    assert raw["l2_raw"]["prod-b"] == {"equivalent": 0, "contradicted": 1, "insufficient": 0}
    assert raw["literal_diagnostic"]["pack-a"]["precision"] == pytest.approx(1 / 3)
    assert raw["provenance"]["judge_model"] == "gpt-6-astra"
    assert raw["provenance"]["rulings_sha256"] is None
    assert (tmp_path / "reports" / "raw.md").is_file()

    (root / "rulings.json").write_text(json.dumps({"entries": [
        {"product_id": "prod-b", "field_key": "limit", "from": "wrong_value", "to": "correct",
         "reason": "条款 3 原文为每次限额1万元", "by": "Claude Code", "on": "2026-10-07"},
        {"product_id": "prod-a", "field_key": "age", "from": "hallucination", "to": "misfiled",
         "reason": "条款 1 原文有投保年龄，属 entry_age_range", "by": "Claude Code",
         "on": "2026-10-07"},
    ]}, ensure_ascii=False), encoding="utf-8")
    assert score(tmp_path, inputs, root, "final") == 0
    final = json.loads((tmp_path / "reports" / "final.json").read_text())
    pack_b = final["report"]["per_pack"]["pack-b"]
    assert (pack_b["tp"], pack_b["fp"], pack_b["fn"]) == (1, 0, 1)
    assert final["report"]["hallucinations"] == 0
    assert final["l2_raw"]["prod-b"]["contradicted"] == 1
    assert final["provenance"]["rulings_sha256"] is not None


def test_prepare_refuses_git_directories_and_existing_runs(tmp_path: Path) -> None:
    inputs = write_inputs(tmp_path)
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    assert main(["prepare", *inputs, "--run-root", str(tmp_path / "repo" / "run")]) == 2
    root = tmp_path / "run"
    assert main(["prepare", *inputs, "--run-root", str(root)]) == 0
    request = root / "prod-a" / "requests" / "001.json"
    before = request.read_bytes()
    assert main(["prepare", *inputs, "--run-root", str(root)]) == 2
    assert request.read_bytes() == before


def test_score_fails_closed_on_changed_inputs_or_missing_answers(tmp_path: Path) -> None:
    inputs = write_inputs(tmp_path)
    root = tmp_path / "run"
    assert main(["prepare", *inputs, "--run-root", str(root)]) == 0
    answer(root, "prod-a", {"scope": "equivalent"})
    assert score(tmp_path, inputs, root, "unanswered") == 2
    answer(root, "prod-b", {"limit": "equivalent"})
    golden = tmp_path / "prod-a.jsonl"
    golden.write_text(golden.read_text(encoding="utf-8").replace("90日", "60日"), encoding="utf-8")
    assert score(tmp_path, inputs, root, "changed") == 2
    assert not (tmp_path / "reports" / "changed.json").exists()
