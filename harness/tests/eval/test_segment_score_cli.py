"""The scoring command reads a run root and the in-repo Golden v2.

Golden scored as if it were a run must come out perfect (metric self-check).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.eval.product_sources import source_directory, source_pages
from insurance_harness.eval.segment_score import (
    GOLDEN_DIR,
    GoldenV2,
    load_golden_v2,
    main,
    score_selection,
)
from insurance_harness.evidence.segments import SegmentedSource

REPO = Path(__file__).resolve().parents[3]
PRODUCT = "1824"


def golden_as_run(run_root: Path) -> None:
    golden = load_golden_v2(REPO / GOLDEN_DIR / f"{PRODUCT}.json")
    source = SegmentedSource(source_pages(source_directory(REPO, PRODUCT)))
    fields = [
        FieldResult(
            field_key=field.field_key,
            state=field.state,
            value=field.value,
            evidence=source.evidence([quote.segment_id or "" for quote in field.evidence]),
        )
        for field in golden.fields
    ]
    out = run_root / PRODUCT / "output.json"
    out.parent.mkdir(parents=True)
    output = CompileOutput(pack_id="pack", entity_id=PRODUCT, model="golden", fields=fields)
    out.write_text(output.model_dump_json(), encoding="utf-8")


def test_golden_scored_as_a_run_is_perfect(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    golden_as_run(tmp_path)
    assert main(["--repo", str(REPO), "--run-root", str(tmp_path), "--products", PRODUCT]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in lines] == [PRODUCT, "pooled"]
    for line in lines:
        assert "recall 1.000 precision 1.000" in line
        assert "unmapped golden 0 predicted 0" in line


def test_a_product_id_outside_the_catalogue_shape_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        main(["--repo", str(REPO), "--run-root", str(tmp_path), "--products", "../1824"])


def test_recorded_ids_survive_a_line_ending_change() -> None:
    """Page text keeps CRLF since S4c-1; a run saved with LF keeps its ids (S4f §2.3)."""

    class Page:
        def __init__(self, text: str) -> None:
            self.document, self.document_sha256, self.page, self.text = (
                "条款.pdf",
                "f" * 64,
                1,
                text,
            )

    repeated = "若被保险人在本合同生效前已发生某特定疾病，\n我们不承担保险责任。"
    saved = SegmentedSource([Page(f"{repeated}\n本合同终止。\n{repeated}\n")])
    now = SegmentedSource(
        [Page(f"{repeated}\r\n本合同终止。\r\n{repeated}\r\n".replace("，\n", "，\r\n"))]
    )
    result = FieldResult(
        field_key="exclusions",
        state="present",
        value="x",
        evidence=saved.evidence(["D1P1S3"]),
        segment_ids=["D1P1S3"],
    )
    assert now.evidence(["D1P1S3"]) != result.evidence, "the line endings really differ"
    golden = load_golden_v2_from(
        {"field_key": "exclusions", "segment_id": "D1P1S3", "quote": now.segments[2].text}
    )
    report = score_selection(now, golden, [result])
    assert report.unmapped_predicted_quotes == 0
    assert [(f.recall, f.precision) for f in report.fields] == [(1.0, 1.0)]


def load_golden_v2_from(evidence: dict[str, str]) -> GoldenV2:
    return GoldenV2.model_validate_json(
        json.dumps(
            {
                "product_id": "1818",
                "cards_version": "test",
                "fields": [
                    {
                        "field_key": evidence["field_key"],
                        "state": "present",
                        "value": "x",
                        "reason": "r",
                        "evidence": [
                            {
                                "document": "条款.pdf",
                                "document_sha256": "f" * 64,
                                "page": 1,
                                "quote": evidence["quote"],
                                "segment_id": evidence["segment_id"],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
