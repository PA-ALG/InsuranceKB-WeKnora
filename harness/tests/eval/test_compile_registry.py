"""S5b-4a acceptance (protected, written by Claude): compiling with the product registry's facts.

Spec docs/design/slices/S5b-4a-编译与发布读产品登记表.md §2.1, §3 items 1–2. A product the upload
attribution created has no dataset folder; its name and pack come from the registry. Reuses the
fake dataset, model and pages of test_compile_run.
"""

import hashlib
import json
from pathlib import Path

import pytest

from insurance_harness.compilers.schema_fields.engine import CompileOutput
from insurance_harness.eval import compile_run
from insurance_harness.eval.compile_run import compile_products
from insurance_harness.eval.pdf_text import PageText
from tests.eval.test_compile_run import TEXT, factory
from tests.eval.test_compile_run import repo as prepared_repo  # noqa: F401

CREATED = "sc-0a1b2c3d4e"


@pytest.fixture
def dataset(request: pytest.FixtureRequest) -> Path:
    """The fake dataset of test_compile_run: products p1 and p2 in pack-a."""
    path: Path = request.getfixturevalue("prepared_repo")
    return path


def pages(product: str) -> list[PageText]:
    return [PageText(f"{product}-条款.pdf", hashlib.sha256(product.encode()).hexdigest(), 1, TEXT)]


def output(root: Path, product: str) -> CompileOutput:
    return CompileOutput.model_validate_json(
        (root / product / "output.json").read_text(encoding="utf-8")
    )


def test_a_product_only_the_registry_knows_compiles_with_its_facts(
    dataset: Path, tmp_path: Path
) -> None:
    build, sent = factory(["example-flash-2026"] * 2)
    root = tmp_path / "run"
    runs = compile_products(
        dataset,
        [CREATED],
        completion_factory=build,
        run_root=root,
        max_sent=30,
        page_source=pages,
        facts={CREATED: ("新建的产品", "pack-a")}.__getitem__,
    )
    assert [(r.product_id, r.display_name, r.pack_id, r.reused) for r in runs] == [
        (CREATED, "新建的产品", "pack-a", False)
    ]
    assert (output(root, CREATED).entity_id, output(root, CREATED).pack_id) == (CREATED, "pack-a")
    assert len(sent) == 2


def test_registry_facts_of_a_seeded_product_give_the_same_compile(
    dataset: Path, tmp_path: Path
) -> None:
    plain, _ = factory(["example-flash-2026"] * 2)
    from_registry, _ = factory(["example-flash-2026"] * 2)
    without = compile_products(
        dataset,
        ["p1"],
        completion_factory=plain,
        run_root=tmp_path / "plain",
        max_sent=30,
        page_source=pages,
    )
    with_facts = compile_products(
        dataset,
        ["p1"],
        completion_factory=from_registry,
        run_root=tmp_path / "registry",
        max_sent=30,
        page_source=pages,
        facts={"p1": ("产品一", "pack-a")}.__getitem__,
    )
    assert [(r.display_name, r.pack_id, r.fields) for r in (*without, *with_facts)] == [
        ("产品一", "pack-a", 3)
    ] * 2
    assert output(tmp_path / "plain", "p1").fields == output(tmp_path / "registry", "p1").fields


def test_facts_without_a_page_source_are_refused_before_any_call(
    dataset: Path, tmp_path: Path
) -> None:
    build, sent = factory(["example-flash-2026"] * 2)
    with pytest.raises(ValueError):
        compile_products(
            dataset,
            [CREATED],
            completion_factory=build,
            run_root=tmp_path / "run",
            max_sent=30,
            facts={CREATED: ("新建的产品", "pack-a")}.__getitem__,
        )
    assert sent == []


def test_a_stored_output_of_another_pack_stops_the_compile(dataset: Path, tmp_path: Path) -> None:
    build, _ = factory(["example-flash-2026"] * 2)
    root = tmp_path / "run"
    compile_products(
        dataset,
        [CREATED],
        completion_factory=build,
        run_root=root,
        max_sent=30,
        page_source=pages,
        facts={CREATED: ("新建的产品", "pack-a")}.__getitem__,
    )
    again, sent = factory(["example-flash-2026"] * 2)
    with pytest.raises(ValueError):
        compile_products(
            dataset,
            [CREATED],
            completion_factory=again,
            run_root=root,
            max_sent=30,
            page_source=pages,
            facts={CREATED: ("新建的产品", "pack-b")}.__getitem__,
        )
    assert sent == []


def exit_code(argv: list[str]) -> int:
    try:
        return compile_run.main(argv)
    except SystemExit as stop:
        return int(stop.code or 0)


def test_the_command_takes_the_registry_or_a_source_map_not_both(tmp_path: Path) -> None:
    config = tmp_path / "stages.json"
    config.write_text(json.dumps({"stages": []}), encoding="utf-8")
    for path in ("registry.json", "map.json"):
        (tmp_path / path).write_text("{}", encoding="utf-8")
    code = exit_code(
        [
            "--products",
            "p1",
            "--stage",
            "schema_fields",
            "--stage-config",
            str(config),
            "--run-root",
            str(tmp_path / "run"),
            "--registry",
            str(tmp_path / "registry.json"),
            "--source-map",
            str(tmp_path / "map.json"),
        ]
    )
    assert code != 0
    assert not (tmp_path / "run" / "p1" / "output.json").exists()
