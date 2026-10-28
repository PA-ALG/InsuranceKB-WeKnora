"""RV7 acceptance, review round 1 (protected, written by Claude): what the judge saw is bound.

Spec docs/design/slices/RV7-模型评审批次命令.md §2.1–§2.3 (review R2, R4, R6, R7, R8). The judge
session can write its own directory, so nothing in it is trusted: requests and materials are
checked against the manifest prepare kept outside it, answers are strict JSON, and publishing
refuses inputs that changed after judging.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.eval.judge import JudgeRequest
from insurance_harness.eval.pdf_text import PageText
from insurance_harness.ingest.judge_batch import JudgeBatchError, ingest, prepare
from tests.compilers.schema_fields.test_publish_cli import PAGES
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.ingest.test_judge_batch import (  # noqa: F401
    POLICY,
    REVIEWER,
    answer,
    approve_all,
    prepared,
    publish,
    submitted,
    world,
)


class Library:
    """Serves the fixture's terms plus any added material."""

    def __init__(self, extra: dict[tuple[str, int], list[PageText]]) -> None:
        self.extra = extra

    def pages(self, space_id: str, knowledge_id: str, attempt: int) -> list[PageText]:
        assert space_id == "space-1"
        if (knowledge_id, attempt) == ("k-1", 2):
            return PAGES
        return self.extra[(knowledge_id, attempt)]


def add_material(case: dict[str, Any], knowledge_id: str, page: PageText) -> None:
    path = case["registry"]
    data = json.loads(path.read_text(encoding="utf-8"))
    data["products"]["1828"]["materials"].append(
        {
            "knowledge_id": knowledge_id,
            "parse_attempt": 1,
            "sha256": page.document_sha256,
            "role": "terms",
            "file_name": page.document,
        }
    )
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    case["reader"] = Library({(knowledge_id, 1): [page]})


def session(case: dict[str, Any]) -> Path:
    path: Path = case["run_root"] / "sessions" / "s01"
    return path


def nothing_ingested(case: dict[str, Any]) -> bool:
    run = case["run_root"]
    return not (run / "verdicts").exists() and not (run / "summary.json").exists()


def test_a_request_rewritten_together_with_its_own_hash_is_refused(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    path = session(world) / "requests" / "001.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    question = json.loads("\n".join(stored["user_lines"]))
    point = next(p for p in question["points"] if p["new"]["value"] == "90日")
    point["new"]["value"] = "180日"
    stored["user_lines"] = json.dumps(question, ensure_ascii=False, indent=1).split("\n")
    rewritten = JudgeRequest("\n".join(stored["system_lines"]), "\n".join(stored["user_lines"]))
    stored["request_sha256"] = rewritten.sha256
    path.write_text(json.dumps(stored, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    approve_all(world)
    with pytest.raises(JudgeBatchError) as refused:
        ingest(world["run_root"])
    assert refused.value.code == "REQUEST_CHANGED"
    assert nothing_ingested(world)


def test_a_material_text_changed_in_the_session_is_refused(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    text = next((session(world) / "sources" / "1828").glob("*.txt"))
    text.write_text("[page 1]\n自本合同生效之日起180日内为等待期。\n", encoding="utf-8")
    approve_all(world)
    with pytest.raises(JudgeBatchError) as refused:
        ingest(world["run_root"])
    assert refused.value.code == "SESSION_CHANGED"
    assert nothing_ingested(world)


def test_prepare_keeps_a_manifest_outside_the_sessions(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    manifest = json.loads((world["run_root"] / "manifest.json").read_text(encoding="utf-8"))
    listed = json.dumps(manifest, ensure_ascii=False)
    assert "requests/001.json" in listed and "AGENTS.md" in listed
    assert "k-1" in listed


def test_a_material_added_after_judging_stops_publishing(
    world: dict[str, Any],  # noqa: F811
) -> None:
    prepared(world)
    approve_all(world)
    ingest(world["run_root"])
    added = PageText("补充条款.pdf", "cd" * 32, 1, "补充条款\n阅读指引\n等待期改为180日。\n")
    add_material(world, "k-2", added)
    result = publish(world, live=True)
    assert result["stopped"] == {"product": "1828", "code": "INPUTS_CHANGED"}
    assert submitted(world) == []


def test_materials_with_the_same_stem_keep_their_own_text(
    world: dict[str, Any],  # noqa: F811
) -> None:
    text = "附加条款全文\n阅读指引\n身故保险金按基本保额给付。\n"
    other = PageText("保险条款.docx", "ef" * 32, 1, text)
    add_material(world, "k-9", other)
    prepared(world)
    texts = [p.read_text(encoding="utf-8") for p in (session(world) / "sources" / "1828").iterdir()]
    assert len(texts) == 2
    assert any("90日内为等待期" in text for text in texts)
    assert any("附加条款全文" in text for text in texts)


def test_a_session_directory_linked_into_git_is_refused_before_any_text_is_written(
    world: dict[str, Any],  # noqa: F811
) -> None:
    checkout = world["compile_root"] / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (world["run_root"] / "sessions").mkdir(parents=True)
    (world["run_root"] / "sessions" / "s01").symlink_to(checkout, target_is_directory=True)
    with pytest.raises(JudgeBatchError) as refused:
        prepared(world)
    assert refused.value.code == "RUN_EXISTS"
    assert [path.name for path in checkout.iterdir()] == [".git"]


def test_a_product_larger_than_a_session_is_refused(
    world: dict[str, Any],  # noqa: F811
) -> None:
    with pytest.raises(JudgeBatchError) as refused:
        prepare(
            world["run_root"],
            registry=world["registry"],
            compile_root=world["compile_root"],
            products=["1828"],
            reader=world["reader"],
            client=world["client"],
            policy_ref=POLICY,
            reviewer=REVIEWER,
            model="judge-test",
            points_per_session=1,
            repo=world["repo"],
        )
    assert refused.value.code == "PRODUCT_TOO_LARGE"
    run = world["run_root"]
    assert not run.exists() or not any(run.iterdir())


def _duplicate_key(raw: str, row: dict[str, Any]) -> str:
    """The first row says reject, then approve: a lenient parser keeps the last one."""
    lenient = json.dumps(row, ensure_ascii=False)
    strict = lenient.replace('"verdict": "approve"', '"verdict": "reject", "verdict": "approve"')
    return raw.replace(lenient, strict, 1)


@pytest.mark.parametrize(
    "damage", ["duplicate-key", "verdict-array", "category-list", "reason-number", "slug-object"]
)
def test_answers_are_strict_json_with_typed_values(
    world: dict[str, Any],  # noqa: F811
    damage: str,
) -> None:
    prepared(world)
    path = answer(world, {key: ("approve", "通过") for key in world["keys"]})
    data = json.loads(path.read_text(encoding="utf-8"))
    row = data["points"][0]
    if damage == "duplicate-key":
        text = _duplicate_key(json.dumps(data, ensure_ascii=False), row)
        assert text.count('"verdict"') == len(data["points"]) + 1
    else:
        if damage == "verdict-array":
            row["verdict"] = ["approve"]
        elif damage == "category-list":
            row["category"] = ["通过"]
        elif damage == "reason-number":
            row["reason"] = 1
        else:
            row["slug"] = {"slug": row["slug"]}
        text = json.dumps(data, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(JudgeBatchError) as refused:
        ingest(world["run_root"])
    assert refused.value.code == "ANSWER_INVALID"
    assert nothing_ingested(world)
