"""S6c acceptance: the wiki page member contract (S6c Spec §2).

Protected file: written by Claude. A wiki page is model-written reading material from the native
Wiki: it belongs to at least one product, says it is model-generated, carries at most three
located quotes, and refuses any field the contract does not name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from insurance_harness.contracts import WikiPage
from insurance_harness.contracts.export import export


def evidence(page: int = 1) -> dict[str, Any]:
    return {
        "source_ref": "source:v1:k1:1:" + "a" * 64,
        "file_sha256": "a" * 64,
        "locator": {"kind": "PDF_TEXT_SPAN", "page": page, "start": 0, "end": 10},
        "quote": "被保险人于等待期后确诊。",
        "access_scope": "space",
    }


def page(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "page_key": "concept/deng-dai-qi",
        "entity_refs": ["1828"],
        "title": "等待期",
        "page_type": "concept",
        "summary": "等待期的定义与例外。",
        "content": "# 等待期\n\n见 [[wiki/1828/concept/bao-xian-ze-ren|保险责任]]。",
        "aliases": ["观察期"],
        "evidence": [evidence()],
        "origin": "MODEL_GENERATED",
        "generator": "weknora-native-wiki",
        "model": "deepseek-v4-flash",
    }
    data.update(changes)
    return data


def test_a_valid_page_parses_with_defaults() -> None:
    parsed = WikiPage.model_validate(page())
    assert parsed.entity_refs == ["1828"]
    minimal = WikiPage.model_validate(
        {
            key: value
            for key, value in page().items()
            if key not in {"summary", "aliases", "evidence"}
        }
    )
    assert (minimal.summary, minimal.aliases, minimal.evidence) == ("", [], [])


@pytest.mark.parametrize(
    "data",
    [
        page(origin="SOURCE_SUPPORTED"),
        page(entity_refs=[]),
        page(evidence=[evidence(1), evidence(2), evidence(3), evidence(4)]),
        page(page_type="summary"),
        page(content=" "),
        page(title=" "),
        page(reviewed=True),
    ],
    ids=[
        "not generated",
        "no product",
        "too much evidence",
        "summary page",
        "blank content",
        "blank title",
        "extra",
    ],
)
def test_an_invalid_page_is_refused(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        WikiPage.model_validate(data)


def test_the_wiki_page_schema_is_exported(tmp_path: Path) -> None:
    names = {path.name for path in export(tmp_path)}
    assert "wiki_page.schema.json" in names
    schema = json.loads((tmp_path / "wiki_page.schema.json").read_text(encoding="utf-8"))
    assert {"page_key", "entity_refs", "content", "evidence", "origin"} <= set(schema["properties"])
