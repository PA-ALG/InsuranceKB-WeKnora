#!/usr/bin/env python3
"""Validate and discover immutable WeKnora adoption targets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import NoReturn

# Both direct CLI execution and package imports load the sibling modules from the scripts package.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.adoption_discovery import (  # noqa: E402
    CHANNELS,
    DiscoveryResolver,
    render_discovery_proposal,
)
from scripts.adoption_migration_policy import check_preservations  # noqa: E402
from scripts.adoption_target import REPOSITORY, load_adoption_target  # noqa: E402
from scripts.adoption_validation import (  # noqa: E402
    REPOSITORY_REF_RE,
    AdoptionTargetError,
    DuplicateKeyError,
    expect_object,
    expect_sha,
    expect_string,
    fail,
    load_yaml,
    reject_duplicate_keys,
)
from scripts.plugin_contract_document import parse_plugin_contract  # noqa: E402
from scripts.plugin_contract_model import PluginContract  # noqa: E402

_OFFICIAL_MIGRATION_RE = re.compile(
    r"(?P<version>[0-9]{6})_(?P<name>[a-z0-9_]+)\.(?P<direction>up|down)\.sql"
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


PLUGIN_CONTRACT_SCHEMA_V1_SHA256 = (
    "548ef36ec27cd3175ff2c0d2de1654d3496a3233a3fa05514b51ef04e6d93d34"
)


def _validate_semantic_json(value: object) -> None:
    if value is None or type(value) in {str, int, bool}:
        return
    if isinstance(value, list):
        for item in value:
            _validate_semantic_json(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if type(key) is not str:
                fail("plugin contract canonical value is not semantic JSON")
            _validate_semantic_json(item)
        return
    fail("plugin contract canonical value is not semantic JSON")


def _canonical_semantic_json(value: object) -> bytes:
    _validate_semantic_json(value)
    try:
        canonical = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise AdoptionTargetError("plugin contract canonical value is not semantic JSON") from exc
    return canonical.encode("utf-8")


def load_plugin_contract(path: Path, *, repository_root: Path | None = None) -> PluginContract:
    """Load the closed Harness-to-WeKnora public plugin contract."""

    data = expect_object(load_yaml(path, "plugin contract"), "plugin contract")
    contract = parse_plugin_contract(data, repository_root or _REPOSITORY_ROOT)
    if re.fullmatch(r"[0-9a-f]{64}", PLUGIN_CONTRACT_SCHEMA_V1_SHA256) is None:
        fail("schema-version-1 plugin contract trust anchor is invalid")
    semantic_digest = hashlib.sha256(_canonical_semantic_json(data)).hexdigest()
    if semantic_digest != PLUGIN_CONTRACT_SCHEMA_V1_SHA256:
        fail("schema-version-1 plugin contract digest mismatch")
    return contract



def _run_git(cwd: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise AdoptionTargetError("git check failed") from exc
    return completed.stdout.strip()


def _load_runtime_source_lock(path: Path) -> tuple[str, str, str]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (DuplicateKeyError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AdoptionTargetError("runtime source lock is unreadable") from exc
    data = expect_object(value, "runtime source lock")
    if data.get("schema_version") != 1 or data.get("repository") != REPOSITORY:
        fail("runtime source lock identity is invalid")
    return (
        REPOSITORY,
        expect_sha(data.get("commit"), "runtime source lock commit"),
        expect_sha(data.get("tree"), "runtime source lock tree"),
    )


def _load_w1_paths(path: Path) -> tuple[str, ...]:
    data = expect_object(load_yaml(path, "patch inventory"), "patch inventory")
    patches = data.get("patches")
    if not isinstance(patches, list):
        fail("patch inventory patches must be a list")
    matches = [
        expect_object(item, "patch inventory entry")
        for item in patches
        if isinstance(item, dict) and item.get("patch_id") == "W1"
    ]
    if len(matches) != 1:
        fail("patch inventory must contain exactly one W1")
    raw_paths = matches[0].get("file_path")
    if not isinstance(raw_paths, list) or not raw_paths:
        fail("W1 file_path must be a non-empty list")
    paths = tuple(expect_string(item, "W1 file_path") for item in raw_paths)
    canonical_paths = all(
        PurePosixPath(item).as_posix() == item
        and bool(PurePosixPath(item).parts)
        and not PurePosixPath(item).is_absolute()
        and "." not in PurePosixPath(item).parts
        and "\\" not in item
        for item in paths
    )
    if (
        len(set(paths)) != len(paths)
        or not canonical_paths
        or any(REPOSITORY_REF_RE.fullmatch(item) is None for item in paths)
    ):
        fail("W1 file_path values must be unique repository paths")
    return tuple(sorted(paths))


def _empty_check_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "verdict": "block",
        "target": {},
        "hard_checks": {"code": "not_checked", "status": "block"},
        "overlaps": {
            "project_merge_base_to_target": [],
            "runtime_to_target": [],
        },
        "official_migrations": {"status": "not_checked", "head": 0, "files": []},
        "plugin_contract": {
            "digest": "",
            "existing": 0,
            "planned_artifact": 0,
            "planned_code": 0,
            "status": "not_checked",
        },
    }


def _blocked(report: dict[str, object], code: str) -> dict[str, object]:
    report["verdict"] = "block"
    report["hard_checks"] = {"code": code, "status": "block"}
    return report


def _official_migrations(
    checkout: Path, head: int
) -> tuple[list[dict[str, str]], dict[str, bytes]]:
    root = checkout / "migrations" / "versioned"
    pairs: dict[int, dict[str, tuple[str, Path]]] = {}
    for path in sorted(root.rglob("*.sql")):
        relative = path.relative_to(root).as_posix()
        match = _OFFICIAL_MIGRATION_RE.fullmatch(relative)
        if match is None:
            fail("official migration filename is invalid")
        version = int(match.group("version"))
        direction = match.group("direction")
        by_direction = pairs.setdefault(version, {})
        if direction in by_direction:
            fail("official migration direction is duplicated")
        by_direction[direction] = (match.group("name"), path)
    if set(pairs) != set(range(0, head + 1)):
        fail("official migration versions do not match the manifest head")
    files: list[dict[str, str]] = []
    raw: dict[str, bytes] = {}
    for version in sorted(pairs):
        pair = pairs[version]
        if set(pair) != {"up", "down"} or pair["up"][0] != pair["down"][0]:
            fail("official migration pair is invalid")
        for direction in ("up", "down"):
            path = pair[direction][1]
            relative = path.relative_to(checkout).as_posix()
            content = path.read_bytes()
            raw[relative] = content
            files.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest()})
    return files, raw


def _plugin_summary(contract: PluginContract) -> dict[str, object]:
    nodes = [node for lane in contract.validation_lanes for node in lane.nodes]
    return {
        "digest": PLUGIN_CONTRACT_SCHEMA_V1_SHA256,
        "existing": sum(node.status == "existing" for node in nodes),
        "planned_artifact": sum(
            node.status == "planned" and node.required_by == "artifact_pr" for node in nodes
        ),
        "planned_code": sum(
            node.status == "planned" and node.required_by == "code_pr" for node in nodes
        ),
        "status": "valid",
    }


def run_adoption_check(
    *,
    target_manifest: Path,
    project_checkout: Path,
    target_checkout: Path,
    runtime_source_lock: Path,
    inventory: Path,
    plugin_contract: Path,
) -> dict[str, object]:
    """Run the finite, read-only adoption check and return sanitized JSON data."""

    report = _empty_check_report()
    try:
        target = load_adoption_target(target_manifest)
    except AdoptionTargetError:
        return _blocked(report, "target_manifest_invalid")
    report["target"] = {
        "commit": target.commit,
        "repository": target.repository,
        "tree": target.tree,
    }

    try:
        if _run_git(target_checkout, "status", "--porcelain"):
            return _blocked(report, "target_dirty")
        origin = _run_git(target_checkout, "remote", "get-url", "origin")
        if origin.rstrip("/").removesuffix(".git") != REPOSITORY.removesuffix(".git"):
            return _blocked(report, "target_origin_mismatch")
        if _run_git(target_checkout, "rev-parse", "HEAD") != target.commit:
            return _blocked(report, "target_head_mismatch")
        if _run_git(target_checkout, "rev-parse", "HEAD^{tree}") != target.tree:
            return _blocked(report, "target_tree_mismatch")
        for ancestor in (
            target.release_ancestor.commit,
            *target.required_capability_commits,
        ):
            _run_git(
                target_checkout,
                "merge-base",
                "--is-ancestor",
                ancestor,
                target.commit,
            )
    except AdoptionTargetError:
        return _blocked(report, "target_ancestor_missing")

    try:
        contract = load_plugin_contract(plugin_contract, repository_root=project_checkout)
    except AdoptionTargetError:
        return _blocked(report, "plugin_contract_invalid")
    canonical_inventory = (project_checkout / contract.patch_inventory_ref).resolve()
    if inventory.resolve() != canonical_inventory:
        return _blocked(report, "inventory_path_mismatch")
    report["plugin_contract"] = _plugin_summary(contract)
    try:
        _, runtime_commit, runtime_tree = _load_runtime_source_lock(runtime_source_lock)
        w1_paths = set(_load_w1_paths(canonical_inventory))
    except AdoptionTargetError:
        return _blocked(report, "runtime_or_inventory_invalid")
    try:
        _run_git(project_checkout, "cat-file", "-e", f"{runtime_commit}^{{commit}}")
        if _run_git(project_checkout, "rev-parse", f"{runtime_commit}^{{tree}}") != runtime_tree:
            return _blocked(report, "runtime_tree_mismatch")
        project_head = _run_git(project_checkout, "rev-parse", "HEAD")
        merge_base = _run_git(project_checkout, "merge-base", project_head, target.commit)
        project_delta = set(
            _run_git(
                project_checkout,
                "diff",
                "--name-only",
                f"{merge_base}..{target.commit}",
            ).splitlines()
        )
        runtime_delta = set(
            _run_git(
                project_checkout,
                "diff",
                "--name-only",
                f"{runtime_commit}..{target.commit}",
            ).splitlines()
        )
    except AdoptionTargetError:
        return _blocked(report, "git_delta_invalid")
    report["overlaps"] = {
        "project_merge_base_to_target": sorted(w1_paths & project_delta),
        "runtime_to_target": sorted(w1_paths & runtime_delta),
    }

    try:
        migration_files, target_bytes = _official_migrations(
            target_checkout, target.official_migration_head
        )
    except (AdoptionTargetError, OSError):
        return _blocked(report, "official_migrations_invalid")
    merged = True
    try:
        _run_git(
            project_checkout,
            "merge-base",
            "--is-ancestor",
            target.commit,
            project_head,
        )
    except AdoptionTargetError:
        merged = False
    report["official_migrations"] = {
        "status": "merged" if merged else "pre_merge",
        "head": target.official_migration_head,
        "files": migration_files,
    }
    if merged:
        try:
            _, project_bytes = _official_migrations(
                project_checkout, target.official_migration_head
            )
        except (AdoptionTargetError, OSError):
            return _blocked(report, "project_migrations_mismatch")
        preservations = check_preservations(
            {"repository": target.repository, "commit": target.commit, "tree": target.tree},
            target.official_migration_head, target_bytes, project_bytes,
        )
        if preservations is None:
            return _blocked(report, "project_migrations_mismatch")
        if preservations:
            migration_report = report["official_migrations"]
            assert isinstance(migration_report, dict)
            migration_report["reviewed_preservations"] = preservations

    overlaps = report["overlaps"]
    assert isinstance(overlaps, dict)
    has_overlap = bool(overlaps["project_merge_base_to_target"] or overlaps["runtime_to_target"])
    migration_report = report["official_migrations"]
    assert isinstance(migration_report, dict)
    needs_review = has_overlap or bool(migration_report.get("reviewed_preservations"))
    report["verdict"] = "manual_review_required" if needs_review else "pass"
    report["hard_checks"] = {"code": "ok", "status": "pass"}
    return report


class _UsageError(ValueError):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    discover = subparsers.add_parser("discover")
    discover.add_argument("--channel", choices=CHANNELS)
    check = subparsers.add_parser("check")
    for name in (
        "target-manifest",
        "project-checkout",
        "target-checkout",
        "runtime-source-lock",
        "inventory",
        "plugin-contract",
    ):
        check.add_argument(f"--{name}", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None, *, resolver: DiscoveryResolver | None = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    except _UsageError as exc:
        parser.print_usage(sys.stderr)
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command is None:
        parser.print_usage(sys.stderr)
        print("error: a command is required", file=sys.stderr)
        return 2

    if args.command == "check":
        result = run_adoption_check(
            target_manifest=args.target_manifest,
            project_checkout=args.project_checkout,
            target_checkout=args.target_checkout,
            runtime_source_lock=args.runtime_source_lock,
            inventory=args.inventory,
            plugin_contract=args.plugin_contract,
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return int(result["verdict"] == "block")

    if args.channel is None:
        parser.print_usage(sys.stderr)
        print("error: discover and --channel are required", file=sys.stderr)
        return 2
    try:
        rendered = render_discovery_proposal(args.channel, resolver=resolver)
    except AdoptionTargetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
