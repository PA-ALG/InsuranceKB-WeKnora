"""Implementation controls for S12c-12a's fixed-revision role transport."""

import json
from typing import Any

import pytest

from insurance_harness.eval.pdf_text import PageText
from insurance_harness.ingest.judge_batch import JudgeBatchError
from insurance_harness.ingest.judge_batch.points import materials_of
from tests.compilers.schema_fields.test_publish_cli import SHA
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import prepared
from tests.ingest.test_judge_batch import world as world  # noqa: F401


def test_role_lookup_uses_revision_and_hash_not_display_name() -> None:
    pages = {("synthetic", 3): [PageText("opaque.txt", SHA, 1, "合成材料")]}
    exact = f"synthetic:3:{SHA}"
    assert materials_of("p", pages, {exact: "terms"})[0].role == "terms"
    for wrong in (f"synthetic:2:{SHA}", f"synthetic:3:{'c' * 64}", "opaque.txt"):
        assert materials_of("p", pages, {wrong: "terms"})[0].role is None


def test_changed_recorded_role_refuses_before_writing_question(world: dict[str, Any]) -> None:
    output = world["compile_root"] / "1828/output.json"
    data = json.loads(output.read_text())
    data["materials"] = [f"k-1:2:{SHA}"]
    data["material_roles"] = {f"k-1:2:{SHA}": "brochure"}
    output.write_text(json.dumps(data))
    with pytest.raises(JudgeBatchError) as error:
        prepared(world)
    assert error.value.code == "INPUTS_CHANGED"
    assert not world["run_root"].exists()
    assert not any(method != "GET" for method, _, _ in world["server"].seen)
