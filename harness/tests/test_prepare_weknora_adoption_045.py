from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from scripts.prepare_weknora_adoption import (
    AdoptionTargetError,
    DiscoveryRevision,
    GitHubDiscoveryResolver,
    load_adoption_target,
    main,
    render_discovery_proposal,
)

REPOSITORY = "https://github.com/Tencent/WeKnora.git"
TARGET_COMMIT = "80a5003cc99a427098afe184eee6601916d3d156"
TARGET_TREE = "18fcf68e7a008ce69929e32233f0b6914040c223"
RELEASE_COMMIT = "c64a48647cd6f7eb8b0fb020b2e8fec74ee375fb"
MANIFEST = {
    "schema_version": 1,
    "repository": REPOSITORY,
    "commit": TARGET_COMMIT,
    "tree": TARGET_TREE,
    "release_ancestor": {"tag": "v0.7.1", "commit": RELEASE_COMMIT},
    "required_capability_commits": [TARGET_COMMIT],
    "official_migration_head": 75,
}
COMMITTED_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "deploy"
    / "upstream"
    / "weknora-adoption-target.json"
)


def _write_manifest(tmp_path: Path, value: object = MANIFEST) -> Path:
    path = tmp_path / "target.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _replace(value: dict[str, object], **changes: object) -> dict[str, object]:
    return {**value, **changes}


def _snapshot(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


class FakeResolver:
    def __init__(self) -> None:
        self.release_tag = "v1.2.3"
        self.release = DiscoveryRevision(
            commit="1" * 40,
            tree="2" * 40,
            official_migration_head=75,
        )
        self.mainline = DiscoveryRevision(
            commit="3" * 40,
            tree="4" * 40,
            official_migration_head=80,
        )
        self.calls: list[tuple[str, ...]] = []

    def latest_release_tag(self, repository: str) -> str:
        self.calls.append(("latest_release_tag", repository))
        return self.release_tag

    def resolve_revision(self, repository: str, ref: str) -> DiscoveryRevision:
        self.calls.append(("resolve_revision", repository, ref))
        if ref == f"refs/tags/{self.release_tag}":
            return self.release
        assert ref == "refs/heads/main"
        return self.mainline

    def is_ancestor(self, repository: str, ancestor: str, descendant: str) -> bool:
        self.calls.append(("is_ancestor", repository, ancestor, descendant))
        return True


def test_manifest_exact_target_passes_and_is_immutable(tmp_path: Path) -> None:
    target = load_adoption_target(_write_manifest(tmp_path))

    assert target.schema_version == 1
    assert target.repository == REPOSITORY
    assert target.commit == TARGET_COMMIT
    assert target.tree == TARGET_TREE
    assert target.release_ancestor.tag == "v0.7.1"
    assert target.release_ancestor.commit == RELEASE_COMMIT
    assert target.required_capability_commits == (TARGET_COMMIT,)
    assert target.official_migration_head == 75
    with pytest.raises(FrozenInstanceError):
        target.commit = "0" * 40  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        target.release_ancestor.tag = "v9.9.9"  # type: ignore[misc]


def test_committed_manifest_matches_approved_exact_target() -> None:
    target = load_adoption_target(COMMITTED_MANIFEST)

    assert json.loads(COMMITTED_MANIFEST.read_text(encoding="utf-8")) == MANIFEST
    assert target.commit == TARGET_COMMIT
    assert target.tree == TARGET_TREE
    assert target.release_ancestor.commit == RELEASE_COMMIT


def test_manifest_accepts_future_approved_immutable_target(tmp_path: Path) -> None:
    future = _replace(
        MANIFEST,
        commit="1" * 40,
        tree="2" * 40,
        release_ancestor={"tag": "v1.2.3", "commit": "3" * 40},
        required_capability_commits=["4" * 40],
        official_migration_head=80,
    )

    target = load_adoption_target(_write_manifest(tmp_path, future))

    assert target.commit == "1" * 40
    assert target.tree == "2" * 40
    assert target.release_ancestor.commit == "3" * 40
    assert target.required_capability_commits == ("4" * 40,)
    assert target.official_migration_head == 80


@pytest.mark.parametrize(
    "serialized",
    [
        json.dumps(MANIFEST).replace(
            f'"commit": "{TARGET_COMMIT}"',
            f'"commit": "{TARGET_COMMIT}", "commit": "{"0" * 40}"',
            1,
        ),
        json.dumps(MANIFEST).replace(
            '"tag": "v0.7.1"',
            '"tag": "v0.7.1", "tag": "v9.9.9"',
            1,
        ),
    ],
)
def test_manifest_rejects_duplicate_json_keys(
    tmp_path: Path, serialized: str
) -> None:
    path = tmp_path / "duplicate-target.json"
    path.write_text(serialized, encoding="utf-8")

    with pytest.raises(AdoptionTargetError, match="duplicate"):
        load_adoption_target(path)


@pytest.mark.parametrize(
    "value",
    [
        _replace(MANIFEST, extra=True),
        {key: item for key, item in MANIFEST.items() if key != "tree"},
        _replace(
            MANIFEST,
            release_ancestor={
                "tag": "v0.7.1",
                "commit": RELEASE_COMMIT,
                "extra": True,
            },
        ),
        _replace(MANIFEST, release_ancestor={"tag": "v0.7.1"}),
        _replace(MANIFEST, commit="main"),
        _replace(MANIFEST, commit="master"),
        _replace(MANIFEST, tree="main"),
        _replace(
            MANIFEST,
            release_ancestor={"tag": "v0.7.1", "commit": "master"},
        ),
        _replace(MANIFEST, required_capability_commits=["main"]),
        _replace(MANIFEST, commit=TARGET_COMMIT[:12]),
        _replace(MANIFEST, tree="g" * 40),
        _replace(
            MANIFEST,
            release_ancestor={"tag": "v0.7.1", "commit": "f" * 39},
        ),
        _replace(MANIFEST, repository="https://github.com/evil/WeKnora.git"),
        _replace(
            MANIFEST,
            required_capability_commits=[TARGET_COMMIT, TARGET_COMMIT],
        ),
        _replace(MANIFEST, commit="../refs/heads/main"),
        _replace(
            MANIFEST,
            release_ancestor={"tag": "../v0.7.1", "commit": RELEASE_COMMIT},
        ),
        _replace(MANIFEST, required_capability_commits=["refs/heads/main"]),
    ],
)
def test_manifest_rejects_invalid_or_mutable_identity(
    tmp_path: Path, value: dict[str, object]
) -> None:
    with pytest.raises(AdoptionTargetError):
        load_adoption_target(_write_manifest(tmp_path, value))


@pytest.mark.parametrize(
    "channel, expected_revision",
    [
        (
            "latest-stable",
            DiscoveryRevision(
                commit="1" * 40,
                tree="2" * 40,
                official_migration_head=75,
            ),
        ),
        (
            "mainline-head",
            DiscoveryRevision(
                commit="3" * 40,
                tree="4" * 40,
                official_migration_head=80,
            ),
        ),
    ],
)
def test_discover_resolves_full_immutable_proposal_with_fakes(
    channel: str, expected_revision: DiscoveryRevision
) -> None:
    resolver = FakeResolver()

    rendered = render_discovery_proposal(channel, resolver=resolver)
    proposal = json.loads(rendered)

    assert proposal == {
        "schema_version": 1,
        "repository": REPOSITORY,
        "commit": expected_revision.commit,
        "tree": expected_revision.tree,
        "release_ancestor": {"tag": "v1.2.3", "commit": "1" * 40},
        "required_capability_commits": [TARGET_COMMIT],
        "official_migration_head": expected_revision.official_migration_head,
    }
    assert "refs/" not in rendered
    assert "mainline-head" not in rendered
    assert "latest-stable" not in rendered


def test_discover_repeated_output_is_byte_identical() -> None:
    first = render_discovery_proposal("mainline-head", resolver=FakeResolver())
    second = render_discovery_proposal("mainline-head", resolver=FakeResolver())

    assert first.encode("utf-8") == second.encode("utf-8")
    assert first.endswith("\n")


def test_discover_uses_migration_head_from_resolved_immutable_revision() -> None:
    resolver = FakeResolver()
    resolver.mainline = DiscoveryRevision(
        commit="3" * 40,
        tree="4" * 40,
        official_migration_head=80,
    )

    proposal = json.loads(
        render_discovery_proposal("mainline-head", resolver=resolver)
    )

    assert proposal["official_migration_head"] == 80


def test_resolver_derives_head_from_official_versioned_migration_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolver = GitHubDiscoveryResolver()
    tree = "a" * 40

    def fake_fetch(endpoint: str) -> object:
        assert endpoint == f"/git/trees/{tree}?recursive=1"
        return {
            "truncated": False,
            "tree": [
                {
                    "path": (
                        "migrations/versioned/"
                        "000075_wiki_page_revisions.up.sql"
                    ),
                    "type": "blob",
                },
                {
                    "path": "migrations/versioned/000080_x.up.sql",
                    "type": "blob",
                },
                {
                    "path": "migrations/versioned/000080_x.down.sql",
                    "type": "blob",
                },
                {
                    "path": "migrations/999999_unrelated.sql",
                    "type": "blob",
                },
                {
                    "path": "examples/migrations/versioned/000100_demo.up.sql",
                    "type": "blob",
                },
            ],
        }

    monkeypatch.setattr(resolver, "_fetch_json", fake_fetch)

    assert resolver._migration_head(tree) == 80


def test_discover_writes_nothing_to_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"unchanged")
    before = _snapshot(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert main(["discover", "--channel", "mainline-head"], resolver=FakeResolver()) == 0

    assert _snapshot(tmp_path) == before
    assert json.loads(capsys.readouterr().out)["commit"] == "3" * 40


def test_discover_rejects_nonancestor_release() -> None:
    resolver = FakeResolver()
    resolver.is_ancestor = lambda *_args: False  # type: ignore[method-assign]

    with pytest.raises(AdoptionTargetError, match="ancestor"):
        render_discovery_proposal("mainline-head", resolver=resolver)


def test_cli_explicit_help_is_successful_and_prints_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(["--help"], resolver=FakeResolver())
    captured = capsys.readouterr()

    assert status == 0
    assert "usage:" in captured.out
    assert captured.err == ""


def test_cli_invalid_channel_is_usage_error_without_traceback_or_secrets(
    capsys: pytest.CaptureFixture[str],
) -> None:
    status = main(
        ["discover", "--channel", "nightly"],
        resolver=FakeResolver(),
    )
    captured = capsys.readouterr()

    assert status == 2
    assert "Traceback" not in captured.err
    assert TARGET_COMMIT not in captured.err
