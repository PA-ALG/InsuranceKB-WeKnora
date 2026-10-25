"""Both publishing entry points fail closed on registry errors before constructing clients."""

import json
from pathlib import Path
from types import ModuleType
from typing import NoReturn

import pytest

from insurance_harness.compilers.schema_fields import publish, publish_changes
from tests.changes.test_claim_changes_publish import active, setup, withdrawn  # noqa: F401
from tests.compilers.schema_fields.test_publish_cli import Platform
from tests.compilers.schema_fields.test_publish_cli import platform as prepared_files  # noqa: F401
from tests.compilers.schema_fields.test_publish_registry import (
    REGISTERED,
    first_argv,
    registry_file,
)


@pytest.fixture
def files(request: pytest.FixtureRequest) -> Platform:
    server: Platform = request.getfixturevalue("prepared_files")
    return server


def unexpected(*args: object, **kwargs: object) -> NoReturn:
    pytest.fail("registry preflight reached dataset, page reader or platform client")


@pytest.mark.parametrize("command", [publish, publish_changes], ids=["first", "changes"])
@pytest.mark.parametrize("failure,code", [
    ("unknown", "PRODUCT_UNKNOWN"), ("pack", "OUTPUT_MISMATCH"),
    ("missing", "REGISTRY_IO_ERROR"), ("invalid", "REGISTRY_INVALID"),
    ("unicode", "REGISTRY_INVALID"), ("both", "INVALID_ARGUMENTS"),
    ("neither", "INVALID_ARGUMENTS"),
])
def test_registry_errors_stop_before_any_client(
    tmp_path: Path, files: Platform, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], command: ModuleType, failure: str, code: str,
) -> None:
    registry = registry_file(tmp_path, product="other" if failure == "unknown" else "1828",
                             pack="other" if failure == "pack" else "pack")
    if failure == "missing":
        registry.unlink()
    elif failure in {"invalid", "unicode"}:
        registry.write_bytes(b"private material {broken" if failure == "invalid" else b"\xff")
    sources = [] if failure == "neither" else ["--registry", str(registry)]
    if failure == "both":
        sources += ["--source-map", str(tmp_path / "map.json")]
    for symbol in ("PlatformClient", "reader_from_env", "source_directory"):
        monkeypatch.setattr(command, symbol, unexpected)
    assert command.main(first_argv(tmp_path, *sources)) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"stopped": code}
    assert not captured.err and str(tmp_path) not in captured.out
    assert "private material" not in captured.out and files.seen == []


def test_registry_changes_uses_registered_page_and_preserves_dry_run(
    tmp_path: Path, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _, server, incoming = request.getfixturevalue("setup")
    server.active = active([withdrawn(incoming[0]), incoming[1]])
    registry = registry_file(tmp_path)
    monkeypatch.setattr(publish_changes, "source_directory", unexpected)
    args = first_argv(tmp_path, "--registry", str(registry))
    assert publish_changes.main([*args, "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["counts"]["supersede"] == 1 and report["candidate_id"] is None
    assert [path for _, path, _ in server.seen] == ["releases/active"]
    assert publish_changes.main(args) == 0
    assert json.loads(capsys.readouterr().out)["candidate_id"] == "cand_1"
    assert any(member["kind"] == "entity" and REGISTERED in member["payload"]["names"]
               for member in server.members)


def test_seeded_registry_and_source_map_publish_identical_members(
    tmp_path: Path, files: Platform, capsys: pytest.CaptureFixture[str],
) -> None:
    # Match the registry seed facts to the legacy dataset; both paths use the same source.
    from tests.compilers.schema_fields.test_publish_cli import NAME

    registry = registry_file(tmp_path)
    document = json.loads(registry.read_text())
    document["products"]["1828"].update(names=[NAME], origin="seeded")
    registry.write_text(json.dumps(document), encoding="utf-8")
    assert publish.main(first_argv(tmp_path, "--source-map", str(tmp_path / "map.json"))) == 0
    old_members = files.members
    capsys.readouterr()
    assert publish.main(first_argv(tmp_path, "--registry", str(registry))) == 0
    assert files.members == old_members
    capsys.readouterr()
