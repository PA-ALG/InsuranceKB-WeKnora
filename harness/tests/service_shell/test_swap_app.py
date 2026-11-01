"""I4: the in-repo App swap tool (deploy/local-live/swap_app.py) and its managed env keys.

Offline: `docker` is a fake on PATH whose state lives in a temporary directory; the script runs as
`python -I` exactly as operators run it. Sentinel env values must never reach stdout/stderr, the
fake's argv log or any file other than the fake docker state and the private secrets fixture.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "deploy/local-live/swap_app.py"
NEW_IMAGE = "sha256:" + "a" * 64
OLD_DB = "SENTINEL-db-password-7f3a"
SIGNING = "SENTINEL-signing-key-91c2"
SPACES = '{"spaces":[{"id":"SENTINEL-space-55e1"}]}'
TYPES = "insurance_product"
OTHER_TYPES = "insurance_product,rider"
SENTINELS = (OLD_DB, SIGNING, "SENTINEL-space-55e1")

FAKE_DOCKER = r"""
import json, os, sys
from pathlib import Path
here = Path(__file__).resolve().parent
state_path = here / "state.json"
state = json.loads(state_path.read_text())
argv = sys.argv[1:]
with (here / "calls.jsonl").open("a") as log:
    log.write(json.dumps(argv) + "\n")
def fail():
    sys.exit(1)
def save():
    state_path.write_text(json.dumps(state))
if argv and argv[0] in state.get("fail", []):
    fail()
match argv:
    case ["ps", "-a", "--format", _]:
        for name in state["containers"]:
            print(json.dumps({"Names": name}))
    case [kind, "inspect", name] if kind in ("container", "image"):
        store = state["containers" if kind == "container" else "images"]
        if name not in store:
            fail()
        print(json.dumps([store[name]]))
    case ["rename", old, new]:
        state["containers"][new] = state["containers"].pop(old)
        save()
    case ["stop", "-t", _, name]:
        state["containers"][name]["State"]["Running"] = False
        save()
    case ["rm", name]:
        del state["containers"][name]
        save()
    case ["network", "connect", network, name]:
        state["containers"][name]["NetworkSettings"]["Networks"][network] = {}
        save()
    case ["create", *rest]:
        options, env_keys, mounts, i = {}, [], [], 0
        while rest[i].startswith("-"):
            flag, value = rest[i], rest[i + 1]
            if flag == "-e":
                env_keys.append(value)
            elif flag == "-v":
                mounts.append(value)
            else:
                options[flag] = value
            i += 2
        image, command = rest[i], rest[i + 1:]
        if image not in state["images"]:
            fail()
        env = list(state["images"][image]["Config"]["Env"])
        for key in env_keys:
            if key not in os.environ:
                fail()
            env.append(key + "=" + os.environ[key])
        parsed = []
        for spec in mounts:
            parts = spec.split(":")
            parsed.append({"Name": parts[0], "Destination": parts[1], "RW": parts[2:] != ["ro"]})
        state["containers"][options["--name"]] = {
            "Id": "c" * 64, "Image": image, "State": {"Running": False},
            "Config": {"Env": env, "Entrypoint": [options["--entrypoint"]], "Cmd": command,
                       "User": options["--user"]},
            "HostConfig": {"Memory": int(options["--memory"]),
                           "MemorySwap": int(options["--memory-swap"])},
            "Mounts": parsed, "NetworkSettings": {"Networks": {options["--network"]: {}}}}
        save()
    case _:
        fail()
"""


def load_module() -> Any:
    spec = importlib.util.spec_from_file_location("swap_app_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class World:
    """A fake Docker host holding the stopped original app and, optionally, a current app."""

    def __init__(self, root: Path) -> None:
        self.swap: Any = load_module()
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        self.private = root / "private"
        (self.private / "contracts").mkdir(parents=True)
        (self.private / "config.yaml").write_text("app: {}\n")
        (self.private / "secrets.env").write_text(f"OTHER=x\nE2E_CITATION_SIGNING_KEY={SIGNING}\n")
        self.spaces = root / "spaces.json"
        self.spaces.write_text(SPACES)
        fake = self.bin / "docker"
        fake.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
        fake.chmod(0o755)
        s = self.swap
        original_image = {
            "Id": s.ORIGINAL_IMAGE,
            "Config": {"Env": ["PATH=/usr/bin", "GIN_MODE=release"]},
        }
        current_image = {"Id": "sha256:" + "b" * 64, "Config": {"Env": ["PATH=/usr/bin"]}}
        new_image = {"Id": NEW_IMAGE, "Config": {"Env": ["PATH=/usr/bin"]}}
        original = {
            "Id": "0" * 64,
            "Image": s.ORIGINAL_IMAGE,
            "State": {"Running": False},
            "Config": {
                "Env": ["PATH=/usr/bin", "GIN_MODE=release", f"DB_PASSWORD={OLD_DB}", "DB_HOST=pg"],
                "Entrypoint": ["/app/WeKnora"],
                "Cmd": [],
                "User": "1000:1000",
            },
            "HostConfig": {"Memory": 4096, "MemorySwap": 8192},
            "Mounts": [{"Name": n, "Destination": d, "RW": rw} for n, d, rw in s.VOLUMES],
            "NetworkSettings": {"Networks": {s.NETWORK: {}, "egress": {}}},
        }
        self.state: dict[str, Any] = {
            "containers": {s.BACKUP: original},
            "images": {i["Id"]: i for i in (original_image, current_image, new_image)},
            "fail": [],
        }

    def with_current(self, **env: str) -> World:
        s = self.swap
        rows = [
            "PATH=/usr/bin",
            f"DB_PASSWORD={OLD_DB}",
            "DB_HOST=pg",
            f"E2E_CITATION_SIGNING_KEY={SIGNING}",
            "ENTERPRISE_CONTRACTS_DIR=/app/contracts",
            f"ENTERPRISE_SPACES={SPACES}",
        ]
        rows += [f"{k}={v}" for k, v in env.items()]
        self.state["containers"][s.APP] = {
            "Id": "1" * 64,
            "Image": "sha256:" + "b" * 64,
            "State": {"Running": True},
            "Config": {"Env": rows, "Entrypoint": ["/app/WeKnora"], "Cmd": [], "User": "1000:1000"},
            "HostConfig": {"Memory": 4096, "MemorySwap": 8192},
            "Mounts": [],
            "NetworkSettings": {"Networks": {s.NETWORK: {}, "egress": {}}},
        }
        return self

    def run(self, *extra: str, spaces: bool = True) -> subprocess.CompletedProcess[str]:
        (self.bin / "state.json").write_text(json.dumps(self.state))
        (self.bin / "calls.jsonl").write_text("")
        argv = [sys.executable, "-I", str(SCRIPT), NEW_IMAGE, "--private-dir", str(self.private)]
        if spaces:
            argv += ["--spaces", str(self.spaces)]
        env = {"PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}", "HOME": str(self.root)}
        result = subprocess.run(
            [*argv, *extra], capture_output=True, text=True, env=env, cwd=self.root
        )
        self.state = json.loads((self.bin / "state.json").read_text())
        self.assert_no_leak(result)
        return result

    def calls(self) -> list[list[str]]:
        lines = (self.bin / "calls.jsonl").read_text().splitlines()
        return [json.loads(line) for line in lines]

    def writes(self) -> list[str]:
        return [c[0] for c in self.calls() if c[0] in ("rename", "stop", "rm", "create", "network")]

    def app_env(self) -> dict[str, str]:
        rows = self.state["containers"][self.swap.APP]["Config"]["Env"]
        return dict(row.split("=", 1) for row in rows)

    def assert_no_leak(self, result: subprocess.CompletedProcess[str]) -> None:
        allowed = {self.bin / "state.json", self.private / "secrets.env", self.spaces}
        texts = [result.stdout, result.stderr, (self.bin / "calls.jsonl").read_text()]
        texts += [
            p.read_text(errors="replace")
            for p in self.root.rglob("*")
            if p.is_file() and p not in allowed
        ]
        for sentinel in SENTINELS:
            assert all(sentinel not in text for text in texts), sentinel


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def summary(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    assert result.returncode == 0, result.stderr
    data: dict[str, Any] = json.loads(result.stdout)
    return data


def test_dry_run_touches_nothing_and_shows_names_only(world: World) -> None:
    world.with_current()
    out = summary(world.run("--set-env", f"ENTERPRISE_VERSIONED_ENTITY_TYPES={TYPES}", "--dry-run"))
    assert out["dry_run"] is True and world.writes() == []
    assert out["new_image"] == NEW_IMAGE and out["source"] == world.swap.BACKUP
    assert out["env_added"] == ["ENTERPRISE_VERSIONED_ENTITY_TYPES"] and out["env_removed"] == []
    assert out["managed"]["ENTERPRISE_VERSIONED_ENTITY_TYPES"].startswith("sha256:")
    assert TYPES not in json.dumps(out)


def test_swap_rebuilds_from_original_and_adds_the_managed_key(world: World) -> None:
    world.with_current()
    out = summary(world.run("--set-env", f"ENTERPRISE_VERSIONED_ENTITY_TYPES={TYPES}"))
    env = world.app_env()
    assert env["DB_PASSWORD"] == OLD_DB and env["E2E_CITATION_SIGNING_KEY"] == SIGNING
    assert (
        env["ENTERPRISE_SPACES"] == SPACES and env["ENTERPRISE_CONTRACTS_DIR"] == "/app/contracts"
    )
    assert env["ENTERPRISE_VERSIONED_ENTITY_TYPES"] == TYPES
    created = world.state["containers"][world.swap.APP]
    assert created["Image"] == NEW_IMAGE and "egress" in created["NetworkSettings"]["Networks"]
    assert world.swap.BACKUP in world.state["containers"]
    create = next(c for c in world.calls() if c[0] == "create")
    assert all("=" not in create[i + 1] for i, flag in enumerate(create) if flag == "-e")
    assert out["created_image"] == NEW_IMAGE


def test_first_swap_renames_the_original_once(world: World) -> None:
    s = world.swap
    world.state["containers"][s.APP] = world.state["containers"].pop(s.BACKUP)
    summary(world.run())
    assert world.calls()[[c[0] for c in world.calls()].index("rename")] == [
        "rename",
        s.APP,
        s.BACKUP,
    ]
    assert world.state["containers"][s.BACKUP]["Image"] == s.ORIGINAL_IMAGE


def test_managed_key_is_carried_over_by_a_plain_swap(world: World) -> None:
    world.with_current(ENTERPRISE_VERSIONED_ENTITY_TYPES=TYPES)
    out = summary(world.run())
    assert (
        world.app_env()["ENTERPRISE_VERSIONED_ENTITY_TYPES"] == TYPES and out["env_removed"] == []
    )


def test_different_value_needs_replace(world: World) -> None:
    world.with_current(ENTERPRISE_VERSIONED_ENTITY_TYPES=TYPES)
    refused = world.run("--set-env", f"ENTERPRISE_VERSIONED_ENTITY_TYPES={OTHER_TYPES}")
    assert refused.returncode != 0 and world.writes() == []
    summary(
        world.run("--set-env", f"ENTERPRISE_VERSIONED_ENTITY_TYPES={OTHER_TYPES}", "--replace-env")
    )
    assert world.app_env()["ENTERPRISE_VERSIONED_ENTITY_TYPES"] == OTHER_TYPES


def test_same_value_is_not_a_conflict(world: World) -> None:
    world.with_current(ENTERPRISE_VERSIONED_ENTITY_TYPES=TYPES)
    summary(world.run("--set-env", f"ENTERPRISE_VERSIONED_ENTITY_TYPES={TYPES}"))
    assert world.app_env()["ENTERPRISE_VERSIONED_ENTITY_TYPES"] == TYPES


def test_unset_removes_and_absent_is_a_no_op(world: World) -> None:
    world.with_current(ENTERPRISE_VERSIONED_ENTITY_TYPES=TYPES)
    out = summary(world.run("--unset-env", "ENTERPRISE_VERSIONED_ENTITY_TYPES"))
    assert "ENTERPRISE_VERSIONED_ENTITY_TYPES" not in world.app_env()
    assert out["env_removed"] == ["ENTERPRISE_VERSIONED_ENTITY_TYPES"] and out["unset_absent"] == []
    again = summary(world.run("--unset-env", "ENTERPRISE_VERSIONED_ENTITY_TYPES"))
    assert again["unset_absent"] == ["ENTERPRISE_VERSIONED_ENTITY_TYPES"]


@pytest.mark.parametrize(
    "extra",
    [
        ["--set-env", "DB_PASSWORD=x"],
        ["--set-env", "ENTERPRISE_VERSIONED_ENTITY_TYPES=bad value;rm"],
        ["--set-env", "ENTERPRISE_VERSIONED_ENTITY_TYPES"],
        [
            "--set-env",
            f"ENTERPRISE_VERSIONED_ENTITY_TYPES={TYPES}",
            "--set-env",
            f"ENTERPRISE_VERSIONED_ENTITY_TYPES={TYPES}",
        ],
        [
            "--set-env",
            f"ENTERPRISE_VERSIONED_ENTITY_TYPES={TYPES}",
            "--unset-env",
            "ENTERPRISE_VERSIONED_ENTITY_TYPES",
        ],
        ["--unset-env", "DB_PASSWORD"],
        [
            "--unset-env",
            "ENTERPRISE_VERSIONED_ENTITY_TYPES",
            "--unset-env",
            "ENTERPRISE_VERSIONED_ENTITY_TYPES",
        ],
    ],
)
def test_bad_env_arguments_are_refused_before_any_write(world: World, extra: list[str]) -> None:
    world.with_current()
    result = world.run(*extra)
    assert result.returncode != 0 and world.writes() == []


def test_source_carrying_a_managed_key_is_refused(world: World) -> None:
    original = world.state["containers"][world.swap.BACKUP]
    original["Config"]["Env"].append(f"ENTERPRISE_VERSIONED_ENTITY_TYPES={TYPES}")
    assert world.with_current().run().returncode != 0 and world.writes() == []


def test_missing_spaces_file_cannot_drop_current_spaces(world: World) -> None:
    result = world.with_current().run(spaces=False)
    assert result.returncode != 0 and world.writes() == []


def test_without_a_current_app_the_spaces_file_is_optional(world: World) -> None:
    out = summary(world.run(spaces=False))
    assert out["enterprise_spaces"] is False and "ENTERPRISE_SPACES" not in world.app_env()


@pytest.mark.parametrize("breakage", ["running", "image", "mounts", "entrypoint", "network"])
def test_changed_source_layout_is_refused(world: World, breakage: str) -> None:
    original = world.state["containers"][world.swap.BACKUP]
    match breakage:
        case "running":
            original["State"]["Running"] = True
        case "image":
            original["Image"] = "sha256:" + "b" * 64
        case "mounts":
            original["Mounts"] = original["Mounts"][:2]
        case "entrypoint":
            original["Config"]["Entrypoint"] = ["/bin/sh", "-c"]
        case "network":
            original["NetworkSettings"]["Networks"] = {"other": {}}
    assert world.with_current().run().returncode != 0 and world.writes() == []


def test_unknown_new_image_is_refused(world: World) -> None:
    del world.state["images"][NEW_IMAGE]
    assert world.with_current().run().returncode != 0 and world.writes() == []


@pytest.mark.parametrize("missing", ["config.yaml", "contracts", "secrets.env"])
def test_private_dir_must_hold_its_files(world: World, missing: str) -> None:
    target = world.private / missing
    if target.is_dir():
        target.rmdir()
    else:
        target.unlink()
    assert world.with_current().run().returncode != 0 and world.writes() == []


def test_signing_key_missing_from_private_env_is_refused(world: World) -> None:
    (world.private / "secrets.env").write_text("OTHER=x\n")
    assert world.with_current().run().returncode != 0 and world.writes() == []


def test_bad_spaces_file_is_refused(world: World) -> None:
    world.spaces.write_text("{not json")
    assert world.with_current().run().returncode != 0 and world.writes() == []
