"""A recorded provider may wrap one semantic JSON object in one JSON code fence."""

from __future__ import annotations

import json
import typing

import pytest

from insurance_harness.product_ingestion.extraction import _json
from tests.product_ingestion.test_extraction import Port, execute, response, row, tasks

pytest_plugins = ("tests.product_ingestion.test_extraction",)


def test_strict_semantic_parser_accepts_only_one_complete_json_fence() -> None:
    assert _json(b' \r\n```json\n{"result":1}\n```\n ') == {"result": 1}
    assert _json(b'{"result":1}') == {"result": 1}


@pytest.mark.parametrize(
    "content",
    [
        b'prefix\n```json\n{"result":1}\n```',
        b'```json\n{"result":1}\n```\ntrailing',
        b'```json\n{"result":1}\n```\n```json\n{"result":2}\n```',
        b'```json\n{"result":1,"result":2}\n```',
        b'```json\n{"result":NaN}\n```',
    ],
)
def test_strict_semantic_parser_rejects_prose_multiple_blocks_and_invalid_json(
    content: typing.Any,
) -> None:
    with pytest.raises(ValueError):
        _json(content)


def test_field_projection_accepts_single_fenced_json_and_keeps_recorded_raw(
    source: typing.Any,
) -> None:
    selected = tasks(source, ("benefit",))
    port = Port(lambda request: b"```json\n" + response([row(selected[0], request)]) + b"\n```")
    outcomes = execute(source, selected, port)
    assert outcomes[0].outcome == "verified"
    assert outcomes[0].validated_result.value == "100"
    assert port.saved_raw is not None
    assert port.saved_raw.startswith(b"```json\n")
    assert json.loads(port.saved_raw.split(b"\n", 1)[1].rsplit(b"\n", 1)[0])["fields"]
