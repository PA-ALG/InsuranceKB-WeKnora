"""Exact preservation of the reviewed 0.8.2 wiki-log migration pair."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import prepare_weknora_adoption as adoption

ROOT = Path(__file__).resolve().parents[2]
TARGET = "3e8b0bfc80b845b2d4b2ed683994748741450a97"
PAIR = tuple(f"migrations/versioned/000077_remove_wiki_log.{way}.sql" for way in ("up", "down"))


@pytest.fixture(scope="module")
def target_checkout(tmp_path_factory: pytest.TempPathFactory) -> Path:
    checkout = tmp_path_factory.mktemp("adoption-130") / "upstream"
    subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-checkout", str(ROOT), str(checkout)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "remote",
            "set-url",
            "origin",
            "https://github.com/Tencent/WeKnora.git",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "sparse-checkout", "set", "migrations/versioned"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "checkout", "--quiet", "--detach", TARGET],
        check=True,
        capture_output=True,
    )
    return checkout


@pytest.mark.parametrize(
    "mutation", ["none", "project_up", "target_up", "single_sided", "unrelated", "missing", "extra"]
)
def test_adoption_allows_only_the_exact_reviewed_migration_pair(
    target_checkout: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    read_migrations = adoption._official_migrations

    def read(checkout: Path, head: int) -> tuple[list[dict[str, str]], dict[str, bytes]]:
        files, raw = read_migrations(checkout, head)
        raw = dict(raw)
        project = checkout == ROOT
        if mutation == "project_up" and project:
            raw[PAIR[0]] += b"-- unexpected modification\n"
        elif mutation == "target_up" and not project:
            raw[PAIR[0]] += b"-- unexpected upstream\n"
        elif mutation == "single_sided" and project:
            raw[PAIR[1]] = read_migrations(target_checkout, head)[1][PAIR[1]]
        elif mutation == "unrelated" and project:
            raw[next(path for path in raw if path not in PAIR)] += b"-- unexpected\n"
        elif mutation == "missing" and project:
            del raw[PAIR[0]]
        elif mutation == "extra" and project:
            raw["migrations/versioned/000111_unreviewed.up.sql"] = b"SELECT 1;"
        return files, raw

    monkeypatch.setattr(adoption, "_official_migrations", read)
    # The exception requires review even when no W1 inventory paths overlap.
    monkeypatch.setattr(adoption, "_load_w1_paths", lambda _path: ())
    report = adoption.run_adoption_check(
        target_manifest=ROOT / "deploy/upstream/weknora-adoption-target.json",
        project_checkout=ROOT,
        target_checkout=target_checkout,
        runtime_source_lock=ROOT / "deploy/local-live/weknora-app-source.lock.json",
        inventory=ROOT / "deploy/patches/enterprise-llm-wiki-patch-inventory.yaml",
        plugin_contract=ROOT / "deploy/upstream/weknora-plugin-contract.yaml",
    )
    if mutation == "none":
        assert report["hard_checks"] == {"code": "ok", "status": "pass"}
        assert report["verdict"] == "manual_review_required"
        migrations = report["official_migrations"]
        assert isinstance(migrations, dict)
        assert migrations["status"] == "merged"
        preserved = migrations["reviewed_preservations"]
        assert isinstance(preserved, list)
        assert {item["path"] for item in preserved} == set(PAIR)
    else:
        assert report["verdict"] == "block"
        assert report["hard_checks"] == {"code": "project_migrations_mismatch", "status": "block"}
