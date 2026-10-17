"""Golden v2 becomes the GoldenItem JSONL the semantic judge reads (RV2b Spec §3.1, §4).

Synthetic fixtures only: two products in two packs, neutral field keys, made-up quotes. The
manifest supplies each product's pack and judge; Golden supplies state, value, reason and evidence.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.eval.golden import GoldenItem
from insurance_harness.eval.golden_items import main

FIXTURE = Path(__file__).parent / "fixtures" / "golden_items"
GOLDEN = Path("dataset/golden/v2")
A, B, C = "a" * 64, "b" * 64, "c" * 64
ORDER = [
    ("alpha", "field_a"),
    ("alpha", "field_b"),
    ("alpha", "field_c"),
    ("beta", "field_x"),
    ("beta", "field_y"),
]


def run(repo: Path, out: Path, *extra: str, products: tuple[str, ...] = ("beta", "alpha")) -> int:
    return main(["--repo", str(repo), "--products", *products, "--out", str(out), *extra])


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def copy_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    return repo


def edit(path: Path, change: Callable[[dict[str, Any]], None]) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_every_converted_item_is_a_valid_golden_item_in_product_and_key_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "golden.jsonl"
    assert run(FIXTURE, out) == 0
    lines = out.read_text(encoding="utf-8").splitlines()
    items = [GoldenItem.model_validate_json(line) for line in lines]
    assert [(item.product_id, item.field_key) for item in items] == ORDER
    assert {item.product_id: item.pack_id for item in items} == {
        "alpha": "pack_one",
        "beta": "pack_two",
    }
    # Success prints one JSON summary line: items per product, no paths.
    summary = capsys.readouterr().out.strip().splitlines()
    assert len(summary) == 1
    assert json.loads(summary[0]) == {"items": 5, "products": {"alpha": 3, "beta": 2}}
    assert str(tmp_path) not in summary[0]


def test_fields_and_evidence_are_carried_over_exactly(tmp_path: Path) -> None:
    out = tmp_path / "golden.jsonl"
    assert run(FIXTURE, out) == 0
    by_key = {(row["product_id"], row["field_key"]): row for row in rows(out)}
    # The segment id is not part of the GoldenEvidence contract; evidence keeps Golden's order.
    assert by_key["alpha", "field_c"] == {
        "pack_id": "pack_one",
        "product_id": "alpha",
        "field_key": "field_c",
        "state": "present",
        "value": "合成取值丙",
        "evidence": [
            {"document": "doc-one.pdf", "document_sha256": A, "page": 2, "quote": "合成引文一"},
            {"document": "doc-two.pdf", "document_sha256": B, "page": 1, "quote": "合成引文二"},
        ],
        "components": [],
        "forbidden": [],
        "judged_by": "model:judge-one",
        "note": "合成理由丙",
    }
    assert by_key["alpha", "field_a"] == {
        "pack_id": "pack_one",
        "product_id": "alpha",
        "field_key": "field_a",
        "state": "absent_explicitly",
        "value": None,
        "evidence": [
            {"document": "doc-one.pdf", "document_sha256": A, "page": 5, "quote": "合成引文三"},
        ],
        "components": [],
        "forbidden": [],
        "judged_by": "model:judge-one",
        "note": "合成理由甲",
    }
    assert by_key["alpha", "field_b"] == {
        "pack_id": "pack_one",
        "product_id": "alpha",
        "field_key": "field_b",
        "state": "unknown",
        "value": None,
        "evidence": [],
        "components": [],
        "forbidden": [],
        "judged_by": "model:judge-one",
        "note": "合成理由乙",
    }
    assert by_key["beta", "field_x"] == {
        "pack_id": "pack_two",
        "product_id": "beta",
        "field_key": "field_x",
        "state": "present",
        "value": "合成取值丁",
        "evidence": [
            {"document": "doc-three.pdf", "document_sha256": C, "page": 3, "quote": "合成引文四"},
        ],
        "components": [],
        "forbidden": [],
        "judged_by": "model:judge-two",
        "note": "合成理由丁",
    }
    assert by_key["beta", "field_y"]["judged_by"] == "model:judge-two"
    assert by_key["beta", "field_y"]["evidence"] == []


def test_judged_by_can_be_set_for_every_item(tmp_path: Path) -> None:
    out = tmp_path / "golden.jsonl"
    assert run(FIXTURE, out, "--judged-by", "human:expert") == 0
    assert {row["judged_by"] for row in rows(out)} == {"human:expert"}


def test_output_is_reproducible_whatever_the_product_order(tmp_path: Path) -> None:
    first, second = tmp_path / "first.jsonl", tmp_path / "second.jsonl"
    assert run(FIXTURE, first, products=("alpha", "beta")) == 0
    assert run(FIXTURE, second, products=("beta", "alpha")) == 0
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().endswith(b"\n")


def test_a_subset_of_products_converts_only_those(tmp_path: Path) -> None:
    out = tmp_path / "golden.jsonl"
    assert run(FIXTURE, out, products=("beta",)) == 0
    assert [(row["product_id"], row["field_key"]) for row in rows(out)] == ORDER[3:]


def _drop_manifest(repo: Path) -> None:
    (repo / GOLDEN / "manifest.json").unlink()


def _manifest_without_beta(repo: Path) -> None:
    edit(repo / GOLDEN / "manifest.json", lambda data: data["products"].pop("beta"))


def _manifest_without_judge(repo: Path) -> None:
    edit(repo / GOLDEN / "manifest.json", lambda data: data["products"]["alpha"].pop("model_id"))


def _blank_pack(repo: Path) -> None:
    def change(data: dict[str, Any]) -> None:
        data["products"]["beta"]["pack_id"] = "   "

    edit(repo / GOLDEN / "manifest.json", change)


def _evidence_without_quote(repo: Path) -> None:
    edit(repo / GOLDEN / "alpha.json", lambda data: data["fields"][0]["evidence"][0].pop("quote"))


def _evidence_without_page(repo: Path) -> None:
    edit(repo / GOLDEN / "beta.json", lambda data: data["fields"][1]["evidence"][0].pop("page"))


def _drop_golden_file(repo: Path) -> None:
    (repo / GOLDEN / "beta.json").unlink()


def _golden_names_another_product(repo: Path) -> None:
    def change(data: dict[str, Any]) -> None:
        data["product_id"] = "beta"

    edit(repo / GOLDEN / "alpha.json", change)


@pytest.mark.parametrize(
    ("damage", "code"),
    [
        (_drop_manifest, "MANIFEST_UNREADABLE"),
        (_manifest_without_beta, "PRODUCT_NOT_IN_MANIFEST"),
        (_manifest_without_judge, "JUDGE_NOT_RECORDED"),
        (_evidence_without_quote, "GOLDEN_INVALID"),
        (_evidence_without_page, "GOLDEN_INVALID"),
        (_drop_golden_file, "GOLDEN_INVALID"),
        (_golden_names_another_product, "GOLDEN_INVALID"),
        (_blank_pack, "GOLDEN_ITEM_INVALID"),
    ],
)
def test_a_bad_input_stops_with_a_code_and_writes_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    damage: Callable[[Path], None],
    code: str,
) -> None:
    repo = copy_repo(tmp_path)
    damage(repo)
    out = tmp_path / "golden.jsonl"
    # beta sorts after alpha: a failure on the second product must not leave a partial file.
    assert run(repo, out) == 2
    assert not out.exists()
    captured = capsys.readouterr()
    lines = captured.out.strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["stopped"] == code
    for secret in (str(tmp_path), "合成引文", "合成取值", "合成理由"):
        assert secret not in captured.out + captured.err


@pytest.mark.parametrize(
    "products",
    [("../alpha",), ("alpha", "alpha"), ("alpha/beta",)],
)
def test_bad_product_arguments_stop(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], products: tuple[str, ...]
) -> None:
    out = tmp_path / "golden.jsonl"
    assert run(FIXTURE, out, products=products) == 2
    assert not out.exists()
    assert json.loads(capsys.readouterr().out.strip())["stopped"] == "INVALID_ARGUMENTS"


def test_an_existing_output_is_never_replaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "golden.jsonl"
    out.write_text("earlier\n", encoding="utf-8")
    assert run(FIXTURE, out) == 2
    assert out.read_text(encoding="utf-8") == "earlier\n"
    assert json.loads(capsys.readouterr().out.strip())["stopped"] == "OUTPUT_EXISTS"
