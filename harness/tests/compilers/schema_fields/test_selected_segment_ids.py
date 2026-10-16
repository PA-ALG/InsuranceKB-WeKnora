"""S4f acceptance: compile output keeps the selected segment ids (Spec §2.3).

Protected file: written by Claude. The ids are the step-one selection in reading order. Scoring
uses them only while they reproduce the saved evidence exactly; otherwise it falls back to
locating the quotes, so a changed segmentation can never be scored against the wrong text.
"""

from __future__ import annotations

import json
from pathlib import Path

from insurance_harness.compilers.schema_fields.definitions import FieldDefinition
from insurance_harness.compilers.schema_fields.engine import (
    CompileOutput,
    FieldResult,
    SchemaFieldsCompiler,
)
from insurance_harness.eval.segment_score import GoldenV2, load_golden_v2, score_selection
from insurance_harness.evidence.segments import SegmentedSource

SHA = "e" * 64
REPEATED = "若被保险人在本合同生效前已发生某特定疾病，我们不承担保险责任。"


class Page:
    def __init__(self, text: str) -> None:
        self.document, self.document_sha256, self.page, self.text = "保险条款.pdf", SHA, 1, text


ENGINE_SOURCE = [Page("第一条 本合同等待期为90日。\n意外伤害无等待期。\n本合同不约定犹豫期。\n")]
# D1P1S1 等待期 · D1P1S2 意外无等待期 · D1P1S3 不约定犹豫期
SCORE_SOURCE = SegmentedSource([Page(f"{REPEATED}\n本合同终止。\n{REPEATED}\n")])
# D1P1S1 and D1P1S3 hold the same text on one page: a quote alone cannot tell them apart.


def definition(key: str, ordinal: int) -> FieldDefinition:
    return FieldDefinition(
        field_key=key, short_title=key, description=key, value_spec="文本", ordinal=ordinal
    )


class Completion:
    model = "recorded-offline"

    def __init__(self, *answers: dict[str, object]) -> None:
        self._answers = [json.dumps(a, ensure_ascii=False) for a in answers]

    def complete(self, *, system: str, user: str) -> str:
        return self._answers.pop(0)


def compile_once() -> CompileOutput:
    selection = {
        "fields": [
            {
                "ordinal": 0,
                "field_key": "waiting_period",
                "state": "present",
                "segments": ["D1P1S2", "D1P1S1"],
            },
            {
                "ordinal": 1,
                "field_key": "cooling_off_period",
                "state": "absent_explicitly",
                "segments": ["D1P1S3"],
            },
            {"ordinal": 2, "field_key": "coverage_period", "state": "unknown", "segments": []},
        ]
    }
    values = {"fields": [{"ordinal": 0, "field_key": "waiting_period", "value": "90日"}]}
    compiler = SchemaFieldsCompiler(Completion(selection, values), batch_size=10, max_calls=5)
    keys = ("waiting_period", "cooling_off_period", "coverage_period")
    return compiler.compile(
        "product", [definition(k, i) for i, k in enumerate(keys)], ENGINE_SOURCE
    )


def test_the_output_keeps_the_selection_in_reading_order() -> None:
    fields = {f.field_key: f for f in compile_once().fields}
    assert fields["waiting_period"].segment_ids == ["D1P1S1", "D1P1S2"]
    assert fields["cooling_off_period"].segment_ids == ["D1P1S3"]
    assert fields["coverage_period"].segment_ids == []
    source = SegmentedSource(ENGINE_SOURCE)
    for field in fields.values():
        assert field.evidence == source.evidence(field.segment_ids)


def test_an_output_written_before_segment_ids_still_loads() -> None:
    raw = compile_once().model_dump(mode="json")
    for field in raw["fields"]:
        del field["segment_ids"]
    loaded = CompileOutput.model_validate_json(json.dumps(raw, ensure_ascii=False))
    assert all(field.segment_ids == [] for field in loaded.fields)


def golden(tmp_path: Path, segment_id: str) -> GoldenV2:
    path = tmp_path / "1818.json"
    evidence = {
        "document": "保险条款.pdf",
        "document_sha256": SHA,
        "page": 1,
        "quote": REPEATED,
        "segment_id": segment_id,
    }
    path.write_text(
        json.dumps(
            {
                "product_id": "1818",
                "cards_version": "test",
                "fields": [
                    {
                        "field_key": "exclusions",
                        "state": "present",
                        "value": "x",
                        "reason": "r",
                        "evidence": [evidence],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return load_golden_v2(path)


def predicted(ids: list[str], evidence_ids: list[str]) -> FieldResult:
    return FieldResult(
        field_key="exclusions",
        state="present",
        value="x",
        evidence=SCORE_SOURCE.evidence(evidence_ids),
        segment_ids=ids,
    )


def test_recorded_ids_score_text_that_repeats_on_the_page(tmp_path: Path) -> None:
    report = score_selection(
        SCORE_SOURCE, golden(tmp_path, "D1P1S3"), [predicted(["D1P1S3"], ["D1P1S3"])]
    )
    assert report.unmapped_predicted_quotes == 0
    assert [(f.recall, f.precision) for f in report.fields] == [(1.0, 1.0)]


def test_ids_that_do_not_reproduce_the_evidence_are_not_trusted(tmp_path: Path) -> None:
    for ids in (["D1P1S2"], ["D9P9S9"], []):
        report = score_selection(
            SCORE_SOURCE, golden(tmp_path, "D1P1S3"), [predicted(ids, ["D1P1S3"])]
        )
        assert report.unmapped_predicted_quotes == 1, ids
        assert [(f.recall, f.precision) for f in report.fields] == [(0.0, None)], ids
