"""WeKnora adoption check: target identity, merge base, migrations, inventory and CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts import prepare_weknora_adoption as adoption
from scripts.prepare_weknora_adoption import (
    AdoptionTargetError,
    main,
)
from tests.service_shell.weknora_adoption.helpers import (
    MANIFEST,
    PLUGIN_CONTRACT,
    REPOSITORY,
    REPOSITORY_ROOT,
    _replace,
    _write_manifest,
    _write_yaml,
)

CHECK_TARGET = "a" * 40
CHECK_TREE = "b" * 40
CHECK_RELEASE = "c" * 40
CHECK_CAPABILITY = "d" * 40
CHECK_RUNTIME = "e" * 40
CHECK_RUNTIME_TREE = "f" * 40
CHECK_PROJECT_HEAD = "1" * 40
CHECK_MERGE_BASE = "2" * 40


def _write_check_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    manifest = _write_manifest(
        tmp_path,
        _replace(
            MANIFEST,
            commit=CHECK_TARGET,
            tree=CHECK_TREE,
            release_ancestor={"tag": "v1.2.3", "commit": CHECK_RELEASE},
            required_capability_commits=[CHECK_CAPABILITY],
            official_migration_head=2,
        ),
    )
    target_checkout = tmp_path / "target"
    migrations = target_checkout / "migrations" / "versioned"
    migrations.mkdir(parents=True)
    for version in (0, 1, 2):
        for direction in ("up", "down"):
            (migrations / f"{version:06d}_migration_{version}.{direction}.sql").write_text(
                f"-- {version} {direction}\n",
                encoding="utf-8",
            )
    runtime_lock = tmp_path / "runtime-lock.json"
    runtime_lock.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repository": REPOSITORY,
                "commit": CHECK_RUNTIME,
                "tree": CHECK_RUNTIME_TREE,
                "ignored_v1_field": {"does_not_affect_check": True},
            }
        ),
        encoding="utf-8",
    )
    inventory = REPOSITORY_ROOT / "deploy" / "patches" / "enterprise-llm-wiki-patch-inventory.yaml"
    return manifest, target_checkout, runtime_lock, inventory


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("dirty", "target_dirty"),
        ("wrong_head", "target_head_mismatch"),
        ("missing_ancestor", "target_ancestor_missing"),
    ],
)
def test_check_blocks_sanitized_target_identity_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    expected_code: str,
) -> None:
    manifest, target_checkout, runtime_lock, inventory = _write_check_inputs(tmp_path)

    def fake_git(cwd: Path, *args: str) -> str:
        assert cwd == target_checkout
        command = tuple(args)
        if command == ("status", "--porcelain"):
            return " M secret-path" if failure == "dirty" else ""
        if command == ("remote", "get-url", "origin"):
            return REPOSITORY
        if command == ("rev-parse", "HEAD"):
            return "0" * 40 if failure == "wrong_head" else CHECK_TARGET
        if command == ("rev-parse", "HEAD^{tree}"):
            return CHECK_TREE
        if command[:2] == ("merge-base", "--is-ancestor"):
            if failure == "missing_ancestor":
                raise AdoptionTargetError("untrusted git stderr")
            return ""
        raise AssertionError(command)

    monkeypatch.setattr(adoption, "_run_git", fake_git)
    result = adoption.run_adoption_check(
        target_manifest=manifest,
        project_checkout=REPOSITORY_ROOT,
        target_checkout=target_checkout,
        runtime_source_lock=runtime_lock,
        inventory=inventory,
        plugin_contract=PLUGIN_CONTRACT,
    )

    assert result["verdict"] == "block"
    assert result["hard_checks"] == {"code": expected_code, "status": "block"}
    serialized = json.dumps(result, sort_keys=True)
    assert "secret-path" not in serialized
    assert str(target_checkout) not in serialized
    assert "untrusted git stderr" not in serialized


def test_check_uses_true_merge_base_and_runtime_as_separate_delta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, target_checkout, runtime_lock, inventory = _write_check_inputs(tmp_path)
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_git(cwd: Path, *args: str) -> str:
        command = tuple(args)
        calls.append((cwd, command))
        if cwd == target_checkout:
            if command == ("status", "--porcelain"):
                return ""
            if command == ("remote", "get-url", "origin"):
                return REPOSITORY.removesuffix(".git")
            if command == ("rev-parse", "HEAD"):
                return CHECK_TARGET
            if command == ("rev-parse", "HEAD^{tree}"):
                return CHECK_TREE
            if command[:2] == ("merge-base", "--is-ancestor"):
                return ""
        if cwd == REPOSITORY_ROOT:
            if command == ("cat-file", "-e", f"{CHECK_RUNTIME}^{{commit}}"):
                return ""
            if command == ("rev-parse", f"{CHECK_RUNTIME}^{{tree}}"):
                return CHECK_RUNTIME_TREE
            if command == ("rev-parse", "HEAD"):
                return CHECK_PROJECT_HEAD
            if command == ("merge-base", CHECK_PROJECT_HEAD, CHECK_TARGET):
                return CHECK_MERGE_BASE
            if command == (
                "diff",
                "--name-only",
                f"{CHECK_MERGE_BASE}..{CHECK_TARGET}",
            ):
                return "internal/handler/knowledge.go\nother/project.go\n"
            if command == ("diff", "--name-only", f"{CHECK_RUNTIME}..{CHECK_TARGET}"):
                return "other/runtime.go\ninternal/types/knowledge.go\n"
            if command == (
                "merge-base",
                "--is-ancestor",
                CHECK_TARGET,
                CHECK_PROJECT_HEAD,
            ):
                raise AdoptionTargetError("not an ancestor")
        raise AssertionError((cwd, command))

    monkeypatch.setattr(adoption, "_run_git", fake_git)
    result = adoption.run_adoption_check(
        target_manifest=manifest,
        project_checkout=REPOSITORY_ROOT,
        target_checkout=target_checkout,
        runtime_source_lock=runtime_lock,
        inventory=inventory,
        plugin_contract=PLUGIN_CONTRACT,
    )

    assert result["verdict"] == "manual_review_required"
    assert result["overlaps"] == {
        "project_merge_base_to_target": ["internal/handler/knowledge.go"],
        "runtime_to_target": ["internal/types/knowledge.go"],
    }
    official_migrations = result["official_migrations"]
    assert isinstance(official_migrations, dict)
    assert official_migrations["status"] == "pre_merge"
    assert official_migrations["head"] == 2
    assert len(official_migrations["files"]) == 6
    parsed_contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    nodes = [node for lane in parsed_contract.validation_lanes for node in lane.nodes]
    assert result["plugin_contract"] == {
        "digest": adoption.PLUGIN_CONTRACT_SCHEMA_V1_SHA256,
        "existing": sum(node.status == "existing" for node in nodes),
        "planned_artifact": sum(
            node.status == "planned" and node.required_by == "artifact_pr" for node in nodes
        ),
        "planned_code": sum(
            node.status == "planned" and node.required_by == "code_pr" for node in nodes
        ),
        "status": "valid",
    }
    assert (REPOSITORY_ROOT, ("merge-base", CHECK_PROJECT_HEAD, CHECK_TARGET)) in calls
    assert (REPOSITORY_ROOT, ("merge-base", CHECK_RUNTIME, CHECK_TARGET)) not in calls
    substitute = tmp_path / "same-inventory.yaml"
    substitute.write_bytes(inventory.read_bytes())
    substituted = adoption.run_adoption_check(
        target_manifest=manifest,
        project_checkout=REPOSITORY_ROOT,
        target_checkout=target_checkout,
        runtime_source_lock=runtime_lock,
        inventory=substitute,
        plugin_contract=PLUGIN_CONTRACT,
    )
    assert substituted["verdict"] == "block"
    assert substituted["hard_checks"] == {
        "code": "inventory_path_mismatch",
        "status": "block",
    }


@pytest.mark.parametrize(
    ("case", "expected_code"),
    [
        ("pair", "official_migrations_invalid"),
        ("head", "official_migrations_invalid"),
        ("mismatch", "project_migrations_mismatch"),
        ("extra", "project_migrations_mismatch"),
    ],
)
def test_check_blocks_migration_pair_head_and_postmerge_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_code: str,
) -> None:
    manifest, target_checkout, runtime_lock, inventory = _write_check_inputs(tmp_path)
    target_migrations = target_checkout / "migrations" / "versioned"
    project_checkout = tmp_path / "project"
    project_migrations = project_checkout / "migrations" / "versioned"
    project_migrations.mkdir(parents=True)
    for source in target_migrations.iterdir():
        (project_migrations / source.name).write_bytes(source.read_bytes())
    if case == "pair":
        (target_migrations / "000002_migration_2.down.sql").unlink()
    elif case == "head":
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["official_migration_head"] = 3
        manifest.write_text(json.dumps(value), encoding="utf-8")
    elif case == "mismatch":
        (project_migrations / "000001_migration_1.up.sql").write_text(
            "-- changed\n", encoding="utf-8"
        )
    else:
        for direction in ("up", "down"):
            (project_migrations / f"000003_extra.{direction}.sql").write_text(
                "-- extra\n", encoding="utf-8"
            )

    parsed_contract = adoption.load_plugin_contract(PLUGIN_CONTRACT)
    canonical_inventory = project_checkout / parsed_contract.patch_inventory_ref
    canonical_inventory.parent.mkdir(parents=True)
    canonical_inventory.write_bytes(inventory.read_bytes())
    inventory = canonical_inventory
    monkeypatch.setattr(
        adoption,
        "load_plugin_contract",
        lambda *_args, **_kwargs: parsed_contract,
    )

    def fake_git(cwd: Path, *args: str) -> str:
        command = tuple(args)
        if cwd == target_checkout:
            if command == ("status", "--porcelain"):
                return ""
            if command == ("remote", "get-url", "origin"):
                return REPOSITORY
            if command == ("rev-parse", "HEAD"):
                return CHECK_TARGET
            if command == ("rev-parse", "HEAD^{tree}"):
                return CHECK_TREE
            if command[:2] == ("merge-base", "--is-ancestor"):
                return ""
        if cwd == project_checkout:
            if command == ("cat-file", "-e", f"{CHECK_RUNTIME}^{{commit}}"):
                return ""
            if command == ("rev-parse", f"{CHECK_RUNTIME}^{{tree}}"):
                return CHECK_RUNTIME_TREE
            if command == ("rev-parse", "HEAD"):
                return CHECK_PROJECT_HEAD
            if command == ("merge-base", CHECK_PROJECT_HEAD, CHECK_TARGET):
                return CHECK_MERGE_BASE
            if command[0] == "diff":
                return ""
            if command == (
                "merge-base",
                "--is-ancestor",
                CHECK_TARGET,
                CHECK_PROJECT_HEAD,
            ):
                return ""
        raise AssertionError((cwd, command))

    monkeypatch.setattr(adoption, "_run_git", fake_git)
    result = adoption.run_adoption_check(
        target_manifest=manifest,
        project_checkout=project_checkout,
        target_checkout=target_checkout,
        runtime_source_lock=runtime_lock,
        inventory=inventory,
        plugin_contract=PLUGIN_CONTRACT,
    )

    assert result["verdict"] == "block"
    hard_checks = result["hard_checks"]
    assert isinstance(hard_checks, dict)
    assert hard_checks["code"] == expected_code


def test_check_runtime_lock_and_inventory_are_closed_but_format_invariant(
    tmp_path: Path,
) -> None:
    _, _, runtime_lock, inventory = _write_check_inputs(tmp_path)
    assert adoption._load_runtime_source_lock(runtime_lock) == (
        REPOSITORY,
        CHECK_RUNTIME,
        CHECK_RUNTIME_TREE,
    )
    reordered = yaml.safe_load(inventory.read_text(encoding="utf-8"))
    reformatted = tmp_path / "inventory-reformatted.yaml"
    reformatted.write_text(
        "# formatting is not semantic\n" + yaml.safe_dump(reordered, sort_keys=True),
        encoding="utf-8",
    )
    assert adoption._load_w1_paths(inventory) == adoption._load_w1_paths(reformatted)

    invalid = json.loads(runtime_lock.read_text(encoding="utf-8"))
    invalid["repository"] = "https://example.invalid/private.git"
    runtime_lock.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(AdoptionTargetError):
        adoption._load_runtime_source_lock(runtime_lock)


@pytest.mark.parametrize(
    "bad_path",
    [
        "internal/./handler.go",
        "internal//handler.go",
        ".",
        "/internal/handler.go",
        "internal/",
        r"internal\handler.go",
    ],
)
def test_check_inventory_rejects_noncanonical_paths(tmp_path: Path, bad_path: str) -> None:
    inventory = _write_yaml(
        tmp_path,
        "bad-inventory.yaml",
        {"patches": [{"patch_id": "W1", "file_path": [bad_path]}]},
    )
    with pytest.raises(AdoptionTargetError):
        adoption._load_w1_paths(inventory)


@pytest.mark.parametrize(
    "loader",
    [adoption.load_adoption_target, adoption._load_runtime_source_lock, adoption._load_w1_paths],
)
def test_check_loaders_sanitize_invalid_utf8(tmp_path: Path, loader: object) -> None:
    path = tmp_path / "invalid"
    path.write_bytes(b"\xff")
    with pytest.raises(AdoptionTargetError):
        loader(path)  # type: ignore[operator]


def test_check_cli_sanitizes_invalid_utf8_target(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["check"]
    for name in (
        "target-manifest",
        "project-checkout",
        "target-checkout",
        "runtime-source-lock",
        "inventory",
        "plugin-contract",
    ):
        args.extend((f"--{name}", str(tmp_path / name)))
    (tmp_path / "target-manifest").write_bytes(b"\xff")
    assert main(args) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["hard_checks"]["code"] == "target_manifest_invalid"
    assert str(tmp_path) not in captured.out


@pytest.mark.parametrize(
    ("verdict", "expected_status"), [("pass", 0), ("manual_review_required", 0), ("block", 1)]
)
def test_check_cli_renders_deterministic_json_and_exit_codes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verdict: str,
    expected_status: int,
) -> None:
    result = {
        "schema_version": 1,
        "verdict": verdict,
        "target": {},
        "hard_checks": {"code": "ok", "status": "pass"},
        "overlaps": {},
        "official_migrations": {},
        "plugin_contract": {},
    }
    monkeypatch.setattr(adoption, "run_adoption_check", lambda **_kwargs: result)
    args = [
        "check",
        "--target-manifest",
        str(tmp_path / "manifest"),
        "--project-checkout",
        str(tmp_path / "project"),
        "--target-checkout",
        str(tmp_path / "target"),
        "--runtime-source-lock",
        str(tmp_path / "lock"),
        "--inventory",
        str(tmp_path / "inventory"),
        "--plugin-contract",
        str(tmp_path / "plugin"),
    ]

    assert main(args) == expected_status
    captured = capsys.readouterr()
    assert captured.err == ""
    assert (
        captured.out
        == json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    )


def test_check_cli_missing_arguments_is_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["check"]) == 2
    captured = capsys.readouterr()
    assert "usage:" in captured.err
    assert captured.out == ""
