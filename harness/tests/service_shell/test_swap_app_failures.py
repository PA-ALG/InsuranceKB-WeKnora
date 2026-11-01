"""I4 review R1–R4: failure paths of the App swap tool.

Parse errors, new image defaults, a failed create and inputs that cannot be passed to docker; same
fake docker world as test_swap_app.py.
"""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from tests.service_shell.test_swap_app import NEW_IMAGE, OLD_DB, TYPES, World, summary

KEY = "ENTERPRISE_VERSIONED_ENTITY_TYPES"


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def fingerprint(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def record_path(world: World) -> Path:
    path: Path = world.private / world.swap.INTENT_RECORD
    return path


def refused_before_any_write(world: World, *extra: str, spaces: bool = True) -> str:
    result = world.run(*extra, spaces=spaces)
    assert result.returncode != 0 and world.writes() == [], result.stderr
    return result.stderr


# R1: parse errors must not echo the offending tokens (a mistyped option may carry a value).
@pytest.mark.parametrize(
    "extra",
    [
        ["--set-env-extra", f"DB_PASSWORD={OLD_DB}"],
        [f"DB_PASSWORD={OLD_DB}"],
        ["--set", f"DB_PASSWORD={OLD_DB}"],
        [f"--replace-env={OLD_DB}"],
    ],
)
def test_parse_errors_do_not_echo_arguments(world: World, extra: list[str]) -> None:
    result = world.with_current().run(*extra)
    assert result.returncode == 2 and world.calls() == []
    assert "arguments rejected" in result.stderr


# R2: managed keys are checked against the effective env (new image defaults + runtime).
def test_unset_cannot_remove_a_new_image_default(world: World) -> None:
    world.state["images"][NEW_IMAGE]["Config"]["Env"].append(f"{KEY}={TYPES}")
    world.with_current(**{KEY: TYPES})
    assert "by default" in refused_before_any_write(world, "--unset-env", KEY)
    assert not record_path(world).exists()


def test_new_image_default_is_validated_and_fingerprinted(world: World) -> None:
    world.state["images"][NEW_IMAGE]["Config"]["Env"].append(f"{KEY}={TYPES}")
    out = summary(world.with_current().run())
    assert out["managed"] == {KEY: fingerprint(TYPES)} and world.app_env()[KEY] == TYPES


def test_bad_new_image_default_is_refused(world: World) -> None:
    world.state["images"][NEW_IMAGE]["Config"]["Env"].append(f"{KEY}=Not Valid")
    refused_before_any_write(world.with_current())


# R3: the managed-key intent survives a failed create; no source means explicit keys.
def test_failed_create_keeps_the_managed_key_for_a_plain_rerun(world: World) -> None:
    world.with_current(**{KEY: TYPES})
    world.state["fail"] = ["create"]
    failed = world.run()
    assert failed.returncode != 0 and world.swap.APP not in world.state["containers"]
    assert world.swap.BACKUP in world.state["containers"]
    world.state["fail"] = []
    out = summary(world.run())
    assert world.app_env()[KEY] == TYPES and out["managed"] == {KEY: fingerprint(TYPES)}
    assert stat.S_IMODE(record_path(world).stat().st_mode) == 0o600


def test_failed_create_still_requires_spaces_on_rerun(world: World) -> None:
    world.with_current()
    world.state["fail"] = ["create"]
    assert world.run().returncode != 0 and world.swap.APP not in world.state["containers"]
    world.state["fail"] = []
    refused_before_any_write(world, spaces=False)


def test_record_disagreeing_with_current_app_needs_an_explicit_key(world: World) -> None:
    summary(world.with_current(**{KEY: TYPES}).run())
    world.with_current()  # e.g. replaced by another tool without the key
    assert KEY in refused_before_any_write(world)
    summary(world.run("--unset-env", KEY))
    assert KEY not in world.app_env()


def test_no_current_app_and_no_record_needs_explicit_keys(world: World) -> None:
    assert KEY in refused_before_any_write(world)
    summary(world.run("--set-env", f"{KEY}={TYPES}"))
    assert world.app_env()[KEY] == TYPES


@pytest.mark.parametrize(
    "content", ["{not json", json.dumps({"managed": {"DB_PASSWORD": "x"}, "spaces": True})]
)
def test_unreadable_record_is_refused(world: World, content: str) -> None:
    record_path(world).write_text(content)
    refused_before_any_write(world.with_current())


def test_record_holds_no_secret_and_stays_private(world: World) -> None:
    summary(world.with_current(**{KEY: TYPES}).run())
    record = json.loads(record_path(world).read_text())
    assert record["managed"] == {KEY: TYPES} and record["spaces"] is True
    assert stat.S_IMODE(record_path(world).stat().st_mode) == 0o600


# R4: anything that cannot be passed to docker is refused before any write or record.
def test_nul_in_signing_key_is_refused(world: World) -> None:
    (world.private / "secrets.env").write_text("E2E_CITATION_SIGNING_KEY=abc\x00def\n")
    refused_before_any_write(world.with_current())
    assert not record_path(world).exists()


@pytest.mark.parametrize("value", [f"{OLD_DB}\x00tail", "lone-\ud800-surrogate"])
def test_unpassable_original_runtime_env_is_refused(world: World, value: str) -> None:
    original = world.state["containers"][world.swap.BACKUP]
    original["Config"]["Env"].append(f"EXTRA={value}")
    refused_before_any_write(world.with_current())
    assert not record_path(world).exists()


def test_private_dir_with_a_colon_is_refused(world: World) -> None:
    moved = world.root / "pri:vate"
    world.private.rename(moved)
    world.private = moved
    refused_before_any_write(world.with_current())
    assert not record_path(world).exists()
