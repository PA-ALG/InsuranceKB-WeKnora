"""The scoring command reads a run root and the in-repo Golden v2; Golden scored as a run is perfect."""

from __future__ import annotations

from pathlib import Path

import pytest

from insurance_harness.compilers.schema_fields.engine import CompileOutput, FieldResult
from insurance_harness.eval.product_sources import source_directory, source_pages
from insurance_harness.eval.segment_score import GOLDEN_DIR, load_golden_v2, main
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
