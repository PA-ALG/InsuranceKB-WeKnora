"""I5: the App swap tool uses the contracts shipped in the image; old images need an explicit dir.

Same fake docker world as test_swap_app.py. Images built after I5 carry /app/contracts; a swap must
not shadow them with an outside directory, and an image without them is only accepted together
with --legacy-contracts-dir (rollback to a pre-I5 image).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests.service_shell.test_swap_app import CONTRACT_FILES, NEW_IMAGE, World, summary

PROBE = [
    "run",
    "--rm",
    "--network",
    "none",
    "--pull",
    "never",
    "--entrypoint",
    "test",
    NEW_IMAGE,
    "-f",
    "/app/contracts/candidate_bundle.schema.json",
    "-a",
    "-f",
    "/app/contracts/evidence.schema.json",
]
HEAD_LABEL = "io.insurancekb.app.build-source-head"


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def legacy_dir(world: World, *names: str) -> Path:
    directory = world.root / "exported" / "contracts"
    directory.mkdir(parents=True)
    for name in names or ("candidate_bundle.schema.json", "evidence.schema.json"):
        (directory / name).write_text("{}\n")
    return directory


def without_contracts(world: World) -> World:
    world.state["image_files"][NEW_IMAGE] = []
    return world


def contracts_mounts(world: World) -> list[dict[str, Any]]:
    created = world.state["containers"][world.swap.APP]
    return [m for m in created["Mounts"] if m["Destination"] == "/app/contracts"]


def refused_before_any_write(world: World, *extra: str) -> str:
    result = world.run(*extra)
    assert result.returncode != 0 and world.writes() == [], result.stderr
    return result.stderr


def test_image_with_contracts_is_used_without_a_mount(world: World) -> None:
    out = summary(world.with_current().run())
    assert out["contracts"] == "image" and contracts_mounts(world) == []
    assert world.app_env()["ENTERPRISE_CONTRACTS_DIR"] == "/app/contracts"


def test_probe_runs_isolated_before_any_write(world: World) -> None:
    out = summary(world.with_current().run("--dry-run"))
    assert out["contracts"] == "image" and world.writes() == []
    probes = [call for call in world.calls() if call[0] == "run"]
    assert probes == [PROBE]


def test_private_dir_without_contracts_is_accepted(world: World) -> None:
    shutil.rmtree(world.private / "contracts")
    summary(world.with_current().run())
    assert contracts_mounts(world) == []


def test_image_without_contracts_needs_the_legacy_dir(world: World) -> None:
    stderr = refused_before_any_write(without_contracts(world).with_current())
    assert "--legacy-contracts-dir" in stderr
    assert not (world.private / world.swap.INTENT_RECORD).exists()


def test_old_image_dry_run_names_its_build_source_then_the_rollback_proceeds(
    world: World,
) -> None:
    # #525 R1: Spec §4 starts the rollback from the dry run's build_source_head.
    without_contracts(world).with_current()
    world.state["images"][NEW_IMAGE]["Config"]["Labels"] = {HEAD_LABEL: "e" * 40}
    result = world.run("--dry-run")
    assert result.returncode == 3 and world.writes() == []
    out = json.loads(result.stdout)
    assert out["dry_run"] is True and out["contracts"] == "missing"
    assert out["new_image"] == NEW_IMAGE and out["build_source_head"] == "e" * 40
    assert "--legacy-contracts-dir" in result.stderr
    assert not (world.private / world.swap.INTENT_RECORD).exists()
    directory = legacy_dir(world)
    planned = summary(world.run("--legacy-contracts-dir", str(directory), "--dry-run"))
    assert planned["contracts"] == "legacy_dir" and world.writes() == []
    done = summary(world.run("--legacy-contracts-dir", str(directory)))
    assert done["contracts"] == "legacy_dir" and done["created_image"] == NEW_IMAGE


def test_old_image_without_a_build_source_label_still_reports_null(world: World) -> None:
    result = without_contracts(world).with_current().run("--dry-run")
    assert result.returncode == 3 and world.writes() == []
    out = json.loads(result.stdout)
    assert out["contracts"] == "missing" and out["build_source_head"] is None


def test_legacy_dir_is_mounted_read_only_for_an_old_image(world: World) -> None:
    directory = legacy_dir(without_contracts(world))
    out = summary(world.with_current().run("--legacy-contracts-dir", str(directory)))
    assert out["contracts"] == "legacy_dir"
    assert contracts_mounts(world) == [
        {"Name": str(directory.resolve()), "Destination": "/app/contracts", "RW": False}
    ]
    assert world.app_env()["ENTERPRISE_CONTRACTS_DIR"] == "/app/contracts"


def test_legacy_dir_cannot_shadow_contracts_in_the_image(world: World) -> None:
    directory = legacy_dir(world)
    refused_before_any_write(world.with_current(), "--legacy-contracts-dir", str(directory))


@pytest.mark.parametrize(
    "names",
    [("candidate_bundle.schema.json",), ("evidence.schema.json",)],
)
def test_legacy_dir_must_hold_both_schemas(world: World, names: tuple[str, ...]) -> None:
    directory = legacy_dir(without_contracts(world), *names)
    refused_before_any_write(world.with_current(), "--legacy-contracts-dir", str(directory))


def test_legacy_dir_must_be_a_directory(world: World) -> None:
    missing = world.root / "nowhere"
    refused_before_any_write(
        without_contracts(world).with_current(), "--legacy-contracts-dir", str(missing)
    )


def test_legacy_dir_with_a_colon_is_refused(world: World) -> None:
    directory = world.root / "a:b" / "contracts"
    directory.mkdir(parents=True)
    for name in ("candidate_bundle.schema.json", "evidence.schema.json"):
        (directory / name).write_text("{}\n")
    refused_before_any_write(
        without_contracts(world).with_current(), "--legacy-contracts-dir", str(directory)
    )


def test_image_missing_one_schema_counts_as_without_contracts(world: World) -> None:
    world.state["image_files"][NEW_IMAGE] = [CONTRACT_FILES[0]]
    refused_before_any_write(world.with_current())


@pytest.mark.parametrize("code", [125, 126, 127])
def test_failed_probe_is_refused_even_with_a_legacy_dir(world: World, code: int) -> None:
    directory = legacy_dir(world)
    world.state["probe_exit"] = code
    refused_before_any_write(world.with_current())
    refused_before_any_write(world, "--legacy-contracts-dir", str(directory))


def test_summary_names_the_build_source_head(world: World) -> None:
    out = summary(world.with_current().run("--dry-run"))
    assert out["build_source_head"] is None
    world.state["images"][NEW_IMAGE]["Config"]["Labels"] = {HEAD_LABEL: "f" * 40}
    assert summary(world.run("--dry-run"))["build_source_head"] == "f" * 40
