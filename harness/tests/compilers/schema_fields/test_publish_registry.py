"""S5b-4a acceptance (protected, written by Claude): publishing with the product registry.

Spec docs/design/slices/S5b-4a-编译与发布读产品登记表.md §2.2, §3 items 3–4. With --registry the
materials come from registry.source_map() and the name from registry.facts(); the dataset is not
read. Reuses the fake platform and files of test_publish_cli and the delta setup of
test_claim_changes_publish.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from insurance_harness.compilers.schema_fields import publish as first_publish
from insurance_harness.compilers.schema_fields import publish_changes
from insurance_harness.ingest.registry import (
    MaterialEntry,
    ProductEntry,
    ProductRegistry,
    save_registry,
)
from tests.changes.test_claim_changes_publish import setup as delta_setup  # noqa: F401
from tests.compilers.schema_fields.test_publish_cli import SHA, Platform
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401

REGISTERED = "登记表中的产品名称"


@pytest.fixture
def files(request: pytest.FixtureRequest) -> Platform:
    """The output, map, catalog and dataset of test_publish_cli, with its fake platform."""
    platform: Platform = request.getfixturevalue("prepared_files")
    return platform


@pytest.fixture
def delta(request: pytest.FixtureRequest) -> Any:
    """The delta-publishing setup of test_claim_changes_publish."""
    return request.getfixturevalue("delta_setup")


def registry_file(tmp_path: Path, *, product: str = "1828", pack: str = "pack") -> Path:
    registry = ProductRegistry(
        contract="product-registry.v1",
        space_id="space-1",
        raw_kb_id="raw-1",
        products={
            product: ProductEntry(
                names=[REGISTERED],
                clause_codes=["平安人寿〔2026〕疾病保险999号"],
                schema_pack_id=pack,
                origin="created",
                materials=[
                    MaterialEntry(
                        knowledge_id="k-1",
                        parse_attempt=2,
                        sha256=SHA,
                        role="terms",
                        file_name="保险条款.pdf",
                    )
                ],
            )
        },
        pending=[],
        decisions=[],
    )
    path = tmp_path / "registry.json"
    save_registry(registry, path)
    return path


def without_dataset(tmp_path: Path) -> None:
    for meta in (tmp_path / "repo" / "dataset").rglob("product_meta.json"):
        meta.unlink()


def first_argv(tmp_path: Path, *extra: str) -> list[str]:
    return [
        "--run-root",
        str(tmp_path),
        "--product",
        "1828",
        "--repo",
        str(tmp_path / "repo"),
        *extra,
    ]


def stopped(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> object:
    captured = capsys.readouterr()
    for text in (captured.out, captured.err):
        assert str(tmp_path) not in text and "Traceback" not in text
    return json.loads(captured.out)


# First publish ---------------------------------------------------------------------------------


def test_a_registry_product_without_a_dataset_folder_is_published_under_its_registered_name(
    tmp_path: Path, files: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    without_dataset(tmp_path)
    registry = registry_file(tmp_path)
    argv = first_argv(
        tmp_path, "--registry", str(registry), "--decide", "human", "--reason", "checked"
    )
    assert first_publish.main([*argv, "--activate"]) == 0
    assert any(
        member["kind"] == "entity" and REGISTERED in member["payload"].get("names", [])
        for member in files.members
    )
    capsys.readouterr()


@pytest.mark.parametrize(
    "registry_args, code",
    [
        ({"pack": "another_pack"}, "OUTPUT_MISMATCH"),
        ({"product": "9999"}, "PRODUCT_UNKNOWN"),
    ],
)
def test_a_registry_that_does_not_fit_the_output_stops_before_any_request(
    tmp_path: Path,
    files: Platform,
    capsys: pytest.CaptureFixture[str],
    registry_args: dict[str, str],
    code: str,
) -> None:
    registry = registry_file(tmp_path, **registry_args)
    assert first_publish.main(first_argv(tmp_path, "--registry", str(registry))) == 2
    assert stopped(capsys, tmp_path) == {"stopped": code}
    assert files.seen == []


@pytest.mark.parametrize("given", ["both", "neither"])
def test_the_registry_and_a_source_map_are_one_or_the_other(
    tmp_path: Path, files: Platform, capsys: pytest.CaptureFixture[str], given: str
) -> None:
    sources = [
        "--registry",
        str(registry_file(tmp_path)),
        "--source-map",
        str(tmp_path / "map.json"),
    ]
    assert first_publish.main(first_argv(tmp_path, *(sources if given == "both" else []))) == 2
    assert stopped(capsys, tmp_path) == {"stopped": "INVALID_ARGUMENTS"}
    assert files.seen == []


def test_an_unreadable_registry_stops_with_its_code(
    tmp_path: Path, files: Platform, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "registry.json"
    broken.write_text("{not json", encoding="utf-8")
    assert first_publish.main(first_argv(tmp_path, "--registry", str(broken))) == 2
    assert stopped(capsys, tmp_path) == {"stopped": "REGISTRY_INVALID"}
    assert files.seen == []


# Publishing changes ----------------------------------------------------------------------------


def changes_argv(argv: list[str], registry: Path) -> list[str]:
    """The delta setup's arguments with --registry in place of --source-map."""
    index = argv.index("--source-map")
    return [*argv[:index], *argv[index + 2 :], "--registry", str(registry)]


def test_publishing_changes_reads_the_registry_and_needs_no_dataset_folder(
    tmp_path: Path, delta: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    argv, server, _ = delta
    without_dataset(tmp_path)
    assert publish_changes.main(changes_argv(argv, registry_file(tmp_path))) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["no_changes"] is True and result["candidate_id"] is None
    assert [path for _, path, _ in server.seen] == ["releases/active"]


def test_publishing_changes_stops_on_a_pack_the_output_was_not_compiled_with(
    tmp_path: Path, delta: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    argv, server, _ = delta
    registry = registry_file(tmp_path, pack="another_pack")
    assert publish_changes.main(changes_argv(argv, registry)) == 2
    assert stopped(capsys, tmp_path) == {"stopped": "OUTPUT_MISMATCH"}
    assert server.seen == []
