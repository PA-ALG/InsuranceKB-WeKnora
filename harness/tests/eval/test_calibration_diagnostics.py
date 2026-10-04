"""Calibration diagnostics explain mismatches without changing quality gates."""

import json
import re
from pathlib import Path

import pytest

from insurance_harness.eval.catalog import load_catalog
from insurance_harness.eval.compare import compare_value
from insurance_harness.eval.golden import GoldenEvidence, GoldenItem, State, ValueComponent
from insurance_harness.eval.judge import PROMPT_VERSION, JudgeAnnotator, JudgeRequest, calibrate


def item(
    key: str, value: str | None, *, state: State = "present",
    components: tuple[str, ...] = (), pack: str = "pack-a",
) -> GoldenItem:
    return GoldenItem(
        pack_id=pack, product_id="product", field_key=key, state=state, value=value,
        components=[ValueComponent(name="detail", accepted=components)] if components else [],
        judged_by="human:test",
        evidence=[] if state == "unknown" else [GoldenEvidence(
            document="terms.pdf", document_sha256="a" * 64, page=1, quote="原文",
        )],
    )


@pytest.mark.parametrize("pack", ["medical", "endowment"])
def test_atoms_match_individual_values_and_accepted_terms_without_changing_value_score(
    pack: str,
) -> None:
    reference = [item("terms", "ＡＢ；半年;住院。门诊，甲", pack=pack)]
    judged = [item("terms", "保障ab", components=("半 年", "包括住院", "门诊费用"), pack=pack)]
    report = calibrate(judged, reference).model_dump()
    assert report["reference_atom_coverage"] == 1.0
    assert report["reference_atom_compared"] == 1
    assert report["reference_atom_covered"] == 1
    assert report["present_value_agreement"] == 0
    assert report["disagreements"] == {"terms": "value"}


def test_atoms_require_all_matches_and_never_join_separate_accepted_terms() -> None:
    reference = [item("partial", "住院；门诊"), item("boundary", "甲乙")]
    judged = [item("partial", "住院"), item("boundary", "其他", components=("甲", "乙"))]
    report = calibrate(judged, reference).model_dump()
    assert report["reference_atom_coverage"] == 0.0
    assert report["reference_atom_compared"] == 2
    assert report["reference_atom_misses"] == {"partial": ["门诊"], "boundary": ["甲乙"]}


def test_diagnostic_excludes_component_references_missing_fields_and_empty_atoms() -> None:
    reference = [
        item("structured", "半年", components=("半年",)), item("short", "甲；Ａ"),
        item("missing", "住院"), item("unreported", None, state="unknown"),
    ]
    report = calibrate(reference[:2] + reference[3:], reference).model_dump()
    assert report["reference_atom_coverage"] is None
    assert report["reference_atom_compared"] == 0
    assert report["reference_atom_covered"] == 0
    assert report["not_judged"] == ["missing"]


def test_state_diagnostics_include_both_directions_with_no_field_specific_rules() -> None:
    reference = [item("alpha", None, state="unknown"), item("beta", "住院")]
    judged = [item("alpha", "半年"), item("beta", None, state="unknown")]
    report = calibrate(judged, reference).model_dump()
    assert report["state_disagreements"] == {
        "alpha": {"reference_state": "unknown", "judged_state": "present",
                  "reference_value": None, "judged_value": "半年"},
        "beta": {"reference_state": "present", "judged_state": "unknown",
                 "reference_value": "住院", "judged_value": None},
    }
    assert report["reference_atom_compared"] == 1
    assert report["reference_atom_coverage"] == 0.0
    assert report["reference_atom_misses"] == {"beta": ["住院"]}


def test_prompt_requires_concise_display_values_and_preserves_blind_input(tmp_path: Path) -> None:
    class UnusedJudge:
        model_id = "unused"

        def complete(self, request: JudgeRequest) -> str:
            raise AssertionError("prepare must not call a judge")

    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"entries": [{"pack": {
        "display_name": "Test", "schema_pack_id": "pack", "fields": [
            {"field_key": "duration", "short_title": "期限"},
        ],
    }}]}))
    annotator = JudgeAnnotator(UnusedJudge(), load_catalog(path), max_calls=1, batch_size=1)
    request = annotator.build_requests("product", "pack", ["duration"], [])[0]
    assert PROMPT_VERSION == "2"
    for rule in ("最简答案", "正例", "反例", "条件", "例外", "components", "evidence"):
        assert rule in request.system
    assert "禁止把整段条款" in request.system
    assert "reference" not in request.user and "candidate" not in request.user
    # The example itself must protect the main answer when downstream scoring
    # checks components instead of comparing the whole display value.
    match = re.search(r"components 为 (\[.*\])，evidence", request.system, flags=re.DOTALL)
    assert match is not None
    example = item("duration", "60日").model_copy(update={
        "components": [ValueComponent.model_validate(c) for c in json.loads(match.group(1))],
    })
    assert compare_value(example, "60日，续保不设等待期").correct
    assert not compare_value(example, "90日，续保不设等待期").correct
