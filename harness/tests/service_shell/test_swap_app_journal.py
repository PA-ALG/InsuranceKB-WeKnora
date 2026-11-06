"""ST-1 journal timeout follows the real offline App swap CLI and its recovery record."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.service_shell.test_swap_app import TYPES, World, summary

KEY = "ENTERPRISE_MEMBER_JOURNAL_TIMEOUT_SECONDS"
TYPES_KEY = "ENTERPRISE_VERSIONED_ENTITY_TYPES"


@pytest.mark.parametrize("value", ["1", "15", "60"])
def test_journal_budget_is_set_and_carried_by_standard_swap(tmp_path: Path, value: str) -> None:
    world = World(tmp_path).with_current(**{TYPES_KEY: TYPES})
    first = summary(world.run("--set-env", f"{KEY}={value}"))
    assert world.app_env()[KEY] == value
    expected = "sha256:" + hashlib.sha256(value.encode()).hexdigest()[:12]
    assert first["managed"][KEY] == expected
    second = summary(world.run())
    assert world.app_env()[KEY] == value and second["managed"][KEY] == expected


@pytest.mark.parametrize("value", ["", "0", "61", "-1", "+15", "01", "15s", "1.5", " 15", "15\n"])
def test_journal_budget_invalid_input_refuses_before_container_writes(
    tmp_path: Path, value: str
) -> None:
    world = World(tmp_path).with_current()
    result = world.run("--set-env", f"{KEY}={value}")
    assert result.returncode != 0 and world.writes() == []
    assert world.calls() == []


def test_journal_budget_unset_returns_to_application_default(tmp_path: Path) -> None:
    world = World(tmp_path).with_current(**{KEY: "23"})
    summary(world.run())
    assert world.app_env()[KEY] == "23"
    summary(world.run("--unset-env", KEY))
    assert KEY not in world.app_env()


def test_missing_source_keeps_explicit_managed_key_requirement(tmp_path: Path) -> None:
    world = World(tmp_path)
    denied = world.run("--set-env", f"{TYPES_KEY}={TYPES}")
    assert denied.returncode != 0 and world.writes() == []
    summary(world.run("--set-env", f"{TYPES_KEY}={TYPES}", "--unset-env", KEY))
    assert KEY not in world.app_env() and world.app_env()[TYPES_KEY] == TYPES


def test_failed_create_retains_journal_budget_for_rerun(tmp_path: Path) -> None:
    world = World(tmp_path).with_current(**{KEY: "15"})
    world.state["fail"] = ["create"]
    failed = world.run()
    assert failed.returncode != 0
    world.state["fail"] = []
    summary(world.run())
    assert world.app_env()[KEY] == "15"
