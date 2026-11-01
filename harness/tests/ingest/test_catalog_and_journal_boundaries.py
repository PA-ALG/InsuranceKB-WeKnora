"""PV-1 review round 2 (written by Claude): the object reader and journal parser fail closed.

R2: a non-UTF-8 path, a missing object, a non-blob reply or an oversized blob in the pinned commit
is a typed CATALOG_INVALID (from the real command too: exit 1, the code only, registry unchanged,
lock released). R3: a journal with a repeated key is MIGRATION_JOURNAL_INVALID and nothing is
written.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from insurance_harness.ingest.registry import save_registry
from insurance_harness.ingest.registry_migration import MigrationError, migrate_registry
from insurance_harness.ingest.uploads import main
from insurance_harness.ingest.version_catalog import CatalogError, catalog_from_checkout
from tests.ingest.manifest_repo import git, meta, repository
from tests.ingest.version_helpers import catalog, of, rich_v1

REAL_REPLACE = os.replace
GOOD = json.dumps(meta("A1", 1, "甲产品", "平安人寿〔2025〕医疗保险001号"), ensure_ascii=False)


class Crash(BaseException):
    """The process dies here."""


def plumbing(root: Path, *args: str, data: bytes = b"") -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *args], input=data, capture_output=True, check=True
    )
    return done.stdout.decode("ascii").strip()


def tree(root: Path, entries: list[tuple[str, str, str, bytes]], missing: bool = False) -> str:
    """A tree object from (mode, type, oid, name) entries; names may be any bytes."""
    data = b"".join(
        f"{mode} {kind} {oid}\t".encode() + name + b"\0" for mode, kind, oid, name in entries
    )
    return plumbing(root, "mktree", "-z", *(["--missing"] if missing else []), data=data)


def blob(root: Path, data: bytes) -> str:
    return plumbing(root, "hash-object", "-w", "--stdin", data=data)


def committed(root: Path, folder: bytes, oid: str, missing: bool = False) -> str:
    """A commit whose 在售/<folder>/product_meta.json points at `oid`, built from objects."""
    meta_tree = tree(root, [("100644", "blob", oid, b"product_meta.json")], missing)
    folder_tree = tree(root, [("040000", "tree", meta_tree, folder)])
    top = tree(root, [("040000", "tree", folder_tree, "在售".encode())])
    names = {"NAME": "t", "EMAIL": "t@example.invalid"}
    environment = {
        f"GIT_{role}_{key}": value
        for role in ("AUTHOR", "COMMITTER")
        for key, value in names.items()
    }
    done = subprocess.run(
        ["git", "-C", str(root), "commit-tree", top, "-m", "crafted"],
        capture_output=True,
        check=True,
        env=os.environ | environment,
    )
    return done.stdout.decode("ascii").strip()


def broken_repo(tmp_path: Path, breakage: str) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    git(root, "init", "-q")
    if breakage == "non-utf8-path":
        return root, committed(root, b"\xff\xfe", blob(root, GOOD.encode()))
    if breakage == "missing-object":
        return root, committed(root, b"A", "1" * 40, missing=True)
    oversized = b"{" + b" " * (300 * 1024) + b"}"  # a valid object, too large to read
    return root, committed(root, b"A", blob(root, oversized))


def command(path: Path, repo: Path, commit: str) -> list[str]:
    return [
        "migrate-registry",
        "--registry",
        str(path),
        "--manifest-dir",
        str(repo),
        "--manifest-commit",
        commit,
    ]


# R2 --------------------------------------------------------------------------------------------

BREAKAGES = ["non-utf8-path", "missing-object", "oversized"]


@pytest.mark.parametrize("breakage", BREAKAGES)
def test_r2_a_broken_commit_is_a_typed_refusal(tmp_path: Path, breakage: str) -> None:
    root, commit = broken_repo(tmp_path, breakage)
    with pytest.raises(CatalogError) as caught:
        catalog_from_checkout(root, commit)
    assert caught.value.code == "CATALOG_INVALID"


@pytest.mark.parametrize("breakage", BREAKAGES)
def test_r2_the_command_prints_the_code_and_changes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], breakage: str
) -> None:
    root, commit = broken_repo(tmp_path, breakage)
    path = tmp_path / "registry.json"
    save_registry(rich_v1(), path)
    before = path.read_bytes()
    assert main(command(path, root, commit)) == 1
    assert capsys.readouterr().err == "CATALOG_INVALID\n"  # no traceback
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".lock").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["registry.json", "repo"]


def test_r2_the_reader_still_builds_a_good_commit(tmp_path: Path) -> None:
    commit = repository(tmp_path / "repo", ("在售", "A", GOOD))
    built = catalog_from_checkout(tmp_path / "repo", commit)
    assert [v.version_key for v in built.versions] == ["A1-1"]


# R3 --------------------------------------------------------------------------------------------


def journaled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A migration stopped after its journal, before the replace."""
    path = tmp_path / "registry.json"
    save_registry(rich_v1(), path)

    def crash(source: object, target: object) -> None:
        raise Crash

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(Crash):
        migrate_registry(path, catalog(of("1828"), of("1814")))
    monkeypatch.setattr(os, "replace", REAL_REPLACE)
    journal = path.with_name(path.name + ".migration-journal.json")
    text = journal.read_text(encoding="utf-8")
    journal.write_text('{"new_sha256": "' + "0" * 64 + '", ' + text[1:], encoding="utf-8")
    return path


def test_r3_a_journal_with_a_repeated_key_is_refused_and_nothing_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = journaled(tmp_path, monkeypatch)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(MigrationError) as caught:
        migrate_registry(path, catalog(of("1828"), of("1814")))
    assert caught.value.code == "MIGRATION_JOURNAL_INVALID"
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_r3_the_command_refuses_it_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = journaled(tmp_path, monkeypatch)
    commit = repository(tmp_path / "repo", ("在售", "A", GOOD))
    before = path.read_bytes()
    assert main(command(path, tmp_path / "repo", commit)) == 1
    assert capsys.readouterr().err == "MIGRATION_JOURNAL_INVALID\n"
    assert path.read_bytes() == before
    assert not path.with_name(path.name + ".lock").exists()
