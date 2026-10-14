"""Immutable semantic exchanges and reporting boundaries, using synthetic answers."""

import json
from pathlib import Path

import pytest

from insurance_harness.eval.semantic_run import main


def inputs(
    path: Path, *, products: tuple[str, ...] = ("p", "q"), fields: int = 2,
    literal: bool = False,
) -> list[str]:
    path.mkdir(exist_ok=True)
    args = []
    bindings, predicted = [], []
    for number, product in enumerate(products):
        rows = []
        bindings.append({
            "entity_id": product, "display_name": product, "schema_pack_id": f"pack-{product}",
        })
        for i in range(fields):
            key = f"field_{i:03d}"
            rows.append({
                "product_id": product, "pack_id": f"pack-{product}", "field_key": key,
                "state": "present", "value": "保障意外身故", "judged_by": "human:synthetic",
                "evidence": [{"document": "terms.pdf", "document_sha256": "a" * 64,
                              "page": 1, "quote": "保障意外身故"}],
            })
            predicted.append({
                "entity_id": product, "field_key": key, "state": "present",
                "value": "保障意外身故" if literal else "意外身故属于保障范围",
            })
        golden = path / f"golden-{number}.jsonl"
        golden.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
        args += ["--golden", str(golden)]
    candidate = path / "candidate.json"
    candidate.write_text(json.dumps({
        "request": {"entity_bindings": bindings},
        "compile_result": {"output": {"fields": predicted}},
    }, ensure_ascii=False))
    mapping = path / "map.json"
    mapping.write_text(json.dumps({product: product for product in products}))
    return [*args, "--candidate", str(candidate), "--product-map", str(mapping)]


def complete(root: Path) -> None:
    for path in root.glob("*/requests/*.json"):
        request = json.loads(path.read_text())
        fields = json.loads("\n".join(request["user_lines"]))["fields"]
        (path.parent.parent / "responses" / path.name).write_text(json.dumps({"fields": [
            {"field_key": row["field_key"], "verdict": "equivalent", "reason": "同一事实"}
            for row in fields
        ]}, ensure_ascii=False))


def run_score(args: list[str], root: Path, output: Path) -> int:
    return main(["score", *args, "--run-root", str(root), "--judge-model", "fake",
                 "--out", str(output)])


@pytest.mark.parametrize("name", ["candidate.json", "map.json", "golden-0.jsonl"])
def test_score_binds_every_input_byte(tmp_path: Path, name: str) -> None:
    args = inputs(tmp_path)
    root = tmp_path / "run"
    assert main(["prepare", *args, "--run-root", str(root)]) == 0
    complete(root)
    source = tmp_path / name
    source.write_bytes(source.read_bytes() + b"\n")
    assert run_score(args, root, tmp_path / "report") == 2
    assert not (tmp_path / "report.json").exists()


def test_input_change_cannot_hide_a_previously_requested_product(tmp_path: Path) -> None:
    args = inputs(tmp_path)
    root = tmp_path / "run"
    assert main(["prepare", *args, "--run-root", str(root)]) == 0
    complete(root)
    candidate = tmp_path / "candidate.json"
    data = json.loads(candidate.read_text())
    for row in data["compile_result"]["output"]["fields"]:
        row["value"] = "保障意外身故"
    candidate.write_text(json.dumps(data, ensure_ascii=False))
    assert run_score(args, root, tmp_path / "changed") == 2


def test_zero_l2_questions_still_require_a_prepared_input_snapshot(tmp_path: Path) -> None:
    args = inputs(tmp_path, literal=True)
    root = tmp_path / "run"
    assert run_score(args, root, tmp_path / "unprepared") == 2
    assert main(["prepare", *args, "--run-root", str(root)]) == 0
    assert run_score(args, root, tmp_path / "all-l1") == 0
    result = json.loads((tmp_path / "all-l1.json").read_text())
    assert result["l2_raw"] == {}
    assert result["report"]["micro"]["tp"] == 4


@pytest.mark.parametrize("mutation", ["request", "run", "extra_request", "extra_answer"])
def test_exchange_changes_fail_without_reports(tmp_path: Path, mutation: str) -> None:
    args = inputs(tmp_path)
    root = tmp_path / "run"
    assert main(["prepare", *args, "--run-root", str(root)]) == 0
    complete(root)
    if mutation in ("request", "run"):
        path = root / "p" / ("requests/001.json" if mutation == "request" else "run.json")
        data = json.loads(path.read_text())
        data["unexpected"] = True
        path.write_text(json.dumps(data))
    else:
        folder = "requests" if mutation == "extra_request" else "responses"
        (root / "p" / folder / "999.json").write_text('{}')
    assert run_score(args, root, tmp_path / "invalid") == 2
    assert not (tmp_path / "invalid.json").exists()


@pytest.mark.parametrize("products,fields", [(("p",), 121), (("p", "q", "r", "s", "t"), 61)])
def test_prepare_enforces_product_and_total_batch_budget(
    tmp_path: Path, products: tuple[str, ...], fields: int,
) -> None:
    args = inputs(tmp_path, products=products, fields=fields)
    root = tmp_path / "run"
    assert main(["prepare", *args, "--run-root", str(root)]) == 2
    assert not root.exists()


def test_prepare_rejects_unsafe_product_paths_and_git_symlinks(tmp_path: Path) -> None:
    args = inputs(tmp_path, products=("../escape",))
    root = tmp_path / "run"
    assert main(["prepare", *args, "--run-root", str(root)]) == 2
    args = inputs(tmp_path)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    alias = tmp_path / "alias"
    alias.symlink_to(repo, target_is_directory=True)
    assert main(["prepare", *args, "--run-root", str(alias / "run")]) == 2


def test_prepare_preflights_every_product_before_creating_files(tmp_path: Path) -> None:
    args = inputs(tmp_path)
    root = tmp_path / "run"
    (root / "q").mkdir(parents=True)
    original = root / "q" / "keep.txt"
    original.write_text("keep")
    assert main(["prepare", *args, "--run-root", str(root)]) == 2
    assert sorted(root.iterdir()) == [root / "q"]
    assert original.read_text() == "keep"


def test_score_never_overwrites_either_report(tmp_path: Path) -> None:
    args = inputs(tmp_path)
    root = tmp_path / "run"
    assert main(["prepare", *args, "--run-root", str(root)]) == 0
    complete(root)
    (tmp_path / "report.md").write_text("keep")
    assert run_score(args, root, tmp_path / "report") == 2
    assert (tmp_path / "report.md").read_text() == "keep"
    assert not (tmp_path / "report.json").exists()


def test_file_errors_do_not_echo_local_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    args = inputs(tmp_path)
    (tmp_path / "candidate.json").unlink()
    assert main(["prepare", *args, "--run-root", str(tmp_path / "run")]) == 2
    stderr = capsys.readouterr().err
    assert str(tmp_path) not in stderr
    assert "FileNotFoundError" in stderr


@pytest.mark.parametrize("extra_key", ["field_000", "unrequested_field"])
def test_invalid_verdict_diagnostics_name_the_offending_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra_key: str,
) -> None:
    args = inputs(tmp_path)
    root = tmp_path / "run"
    assert main(["prepare", *args, "--run-root", str(root)]) == 0
    complete(root)
    path = root / "p/responses/001.json"
    answer = json.loads(path.read_text())
    answer["fields"].append({
        "field_key": extra_key, "verdict": "equivalent", "reason": "synthetic answer",
    })
    path.write_text(json.dumps(answer))
    assert run_score(args, root, tmp_path / "invalid") == 2
    assert extra_key in capsys.readouterr().err


def test_two_sampled_equivalent_errors_stop_final_report(tmp_path: Path) -> None:
    args = inputs(tmp_path)
    root = tmp_path / "run"
    assert main(["prepare", *args, "--run-root", str(root)]) == 0
    complete(root)
    assert run_score(args, root, tmp_path / "raw") == 0
    (root / "rulings.json").write_text(json.dumps({"entries": [
        {"product_id": "p", "field_key": key, "from": "correct", "to": "incomplete",
         "reason": "条款 2 有遗漏", "by": "Claude Code", "on": "2026-10-07"}
        for key in ("field_000", "field_001")
    ]}))
    assert run_score(args, root, tmp_path / "final") == 2
    assert not (tmp_path / "final.json").exists()
