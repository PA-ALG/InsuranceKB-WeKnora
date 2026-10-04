"""Additional negative protocol and evidence cases using a local fake judge."""

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.eval.catalog import load_catalog
from insurance_harness.eval.judge import JudgeAnnotator, JudgeBudgetExceeded, JudgeProtocolError
from insurance_harness.eval.pdf_text import PageText


class FakeJudge:
    model_id = "fake"

    def __init__(self, field: dict[str, Any]) -> None:
        self.field = field

    def complete(self, request: object) -> str:
        return json.dumps({"fields": [self.field]})


def builder(tmp_path: Path, field: dict[str, Any]) -> JudgeAnnotator:
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps({"entries": [{"pack": {
        "display_name": "Test", "schema_pack_id": "pack", "fields": [{
            "short_title": "Duration", "field_key": "duration",
        }],
    }}]}))
    return JudgeAnnotator(FakeJudge(field), load_catalog(path), max_calls=1, batch_size=1)


def field() -> dict[str, Any]:
    return {
        "field_key": "duration", "state": "present", "value": "90日", "components": [],
        "evidence": [{"document": "terms.pdf", "page": 1, "quote": "期限９０日"}],
    }


PAGES = [PageText("terms.pdf", "a" * 64, 1, "期限 90 日")]


@pytest.mark.parametrize("change", [
    {"state": "unknown"}, {"state": "absent_explicitly"}, {"value": None}, {"value": " "},
    {"evidence": []}, {"evidence": None}, {"components": [{"name": "time", "accepted": []}]},
    {"evidence": [{"document": "terms.pdf", "page": True, "quote": "期限"}]},
    {"evidence": [{"document": "terms.pdf", "page": "1", "quote": "期限"}]},
    {"evidence": [{"document": "terms.pdf", "page": 0, "quote": "期限"}]},
])
def test_malformed_state_and_evidence_are_protocol_errors(
    tmp_path: Path, change: dict[str, Any],
) -> None:
    with pytest.raises(JudgeProtocolError):
        builder(tmp_path, field() | change).annotate("product", "pack", ["duration"], PAGES)


def test_quote_normalizes_width_and_whitespace_but_preserves_document_identity(
    tmp_path: Path,
) -> None:
    valid = builder(tmp_path, field()).annotate("product", "pack", ["duration"], PAGES)
    assert valid.items[0].evidence[0].document_sha256 == "a" * 64
    wrong = field() | {"evidence": [{"document": "other.pdf", "page": 1, "quote": "期限９０日"}]}
    rejected = builder(tmp_path, wrong).annotate("product", "pack", ["duration"], PAGES)
    assert rejected.rejected == {"duration": "evidence_not_verified"}


def test_budget_survives_repeated_annotation_and_failed_parsing(tmp_path: Path) -> None:
    annotator = builder(tmp_path, field() | {"value": None})
    with pytest.raises(JudgeProtocolError):
        annotator.annotate("product", "pack", ["duration"], PAGES)
    with pytest.raises(JudgeBudgetExceeded):
        annotator.annotate("product", "pack", ["duration"], PAGES)
