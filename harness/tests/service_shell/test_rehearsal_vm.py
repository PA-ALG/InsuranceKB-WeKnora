"""I3a rehearsal safety (PR #480 review R1, R2, R4): owned VM resources and private files.

Offline: colima, limactl, cp and docker are a fake world on a temporary filesystem; nothing real
is started, deleted or contacted.
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

DEPLOY = Path(__file__).resolve().parents[3] / "deploy/rehearsal"
if str(DEPLOY) not in sys.path:
    sys.path.insert(0, str(DEPLOY))
private: Any = importlib.import_module("private")
vm: Any = importlib.import_module("vm")


class World:
    """colima/Lima as far as the rehearsal sees them, with injectable failures."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.disk_root = root / "ssd"
        self.disk_root.mkdir()
        self.colima = root / "colima"
        (self.colima / "_lima" / "_disks").mkdir(parents=True)
        self.profiles: dict[str, str] = {"default": "Running"}
        self.fail: dict[str, int] = {}
        self.in_use = False
        self.calls: list[list[str]] = []
        self.loud: list[list[str]] = []

    def settings(self, **changes: Any) -> Any:
        values: dict[str, Any] = {
            "home": self.home, "profile": "rehearsal", "disk_root": self.disk_root,
            "colima_home": self.colima, "live_context": "colima", "live_port": 18295,
            "ui_port": 18495, "product": "1818", "repo": self.root}
        values.update(changes)
        return vm.Settings(**values)

    def lima(self, name: str) -> Path:
        return self.colima / "_lima" / "_disks" / f"colima-{name}"

    def __call__(self, argv: list[str], *, quiet: bool = False, **_: Any) -> Any:
        self.calls.append(list(argv))
        if not quiet:
            self.loud.append(list(argv))
        result = vm.Result
        match argv:
            case ["colima", "list", "--json"]:
                if self.fail.get("list"):
                    return result(self.fail["list"])
                lines = [json.dumps({"name": n, "status": s}) for n, s in self.profiles.items()]
                return result(0, ("\n".join(lines) + "\n").encode())
            case ["colima", "start", "-p", name, *_rest]:
                if name not in self.profiles:
                    self.lima(name).mkdir()
                    (self.lima(name) / "datadisk").write_bytes(b"disk-image" * 4)
                    (self.colima / "_lima" / f"colima-{name}").mkdir()
                self.profiles[name] = "Running"
                return result(0)
            case ["colima", "stop", "-p", name]:
                self.profiles[name] = "Stopped"
                return result(self.fail.get("stop", 0))
            case ["colima", "delete", "-p", name, "--force"]:
                if self.fail.get("delete"):
                    return result(self.fail["delete"])
                self.profiles.pop(name, None)
                shutil.rmtree(self.colima / "_lima" / f"colima-{name}", ignore_errors=True)
                return result(0)
            case ["limactl", "disk", "list", "--json"]:
                if self.fail.get("disks"):
                    return result(self.fail["disks"])
                disks = sorted((self.colima / "_lima" / "_disks").iterdir())
                lines = [json.dumps({"name": d.name, "instance": d.name if self.in_use else "",
                                     "instanceDir": ""}) for d in disks]
                return result(0, "\n".join(lines).encode())
            case ["cp", "-c", source, target]:
                shutil.copyfile(source, target)
                return result(0)
            case ["docker", "context", "inspect", context, *_rest]:
                profile = context.removeprefix("colima-")
                return result(0, f"unix://{self.colima / profile / 'docker.sock'}\n".encode())
        return result(0)

    def called(self, *prefix: str) -> bool:
        return any(call[: len(prefix)] == list(prefix) for call in self.calls)


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path.resolve())


def owned(world: World) -> Any:
    settings = world.settings()
    vm.create(settings, world)
    return settings


def ext(world: World) -> Path:
    return world.disk_root / "insurancekb-rehearsal" / "rehearsal"


def kept(world: World) -> bool:
    link = world.lima("rehearsal") / "datadisk"
    return (ext(world) / "datadisk").is_file() and os.path.islink(link)


def code(error: pytest.ExceptionInfo[Exception]) -> str:
    return str(error.value.code)  # type: ignore[attr-defined]


# R1: destroy stops on failure or unknown state and deletes nothing.

def test_create_then_destroy_removes_only_owned_resources(world: World) -> None:
    settings = owned(world)
    assert kept(world)
    assert os.readlink(world.lima("rehearsal") / "datadisk") == str(ext(world) / "datadisk")
    assert private.read_json(world.home, "owner.json")["state"] == "ready"
    assert vm.destroy(settings, world)["state"] == "destroyed"
    assert not ext(world).exists() and not os.path.lexists(world.lima("rehearsal"))
    assert private.read_json(world.home, "owner.json")["state"] == "destroyed"
    order = [call[:2] for call in world.calls]
    assert order.index(["colima", "delete"]) < order.index(["limactl", "disk"])
    assert vm.destroy(settings, world)["already"] is True
    # Lima's port-forward daemons outlive colima start: never hand them a pipe (finding F7).
    assert not [call for call in world.loud if call[:2] in (
        ["colima", "start"], ["colima", "stop"], ["colima", "delete"])]


def test_destroy_keeps_disks_when_colima_delete_fails(world: World) -> None:
    settings = owned(world)
    world.fail["delete"] = 42
    with pytest.raises(vm.VmError) as error:
        vm.destroy(settings, world)
    assert code(error) == "DELETE_FAILED"
    assert kept(world)
    assert private.read_json(world.home, "owner.json")["state"] == "ready"


@pytest.mark.parametrize(("failing", "expected"), [("list", "COLIMA_STATE_UNKNOWN"),
                                                    ("disks", "DISK_STATE_UNKNOWN"),
                                                    ("stop", "STOP_FAILED")])
def test_destroy_keeps_everything_on_unknown_state(world: World, failing: str,
                                                   expected: str) -> None:
    settings = owned(world)
    world.fail[failing] = 1
    with pytest.raises(vm.VmError) as error:
        vm.destroy(settings, world)
    assert code(error) == expected
    assert kept(world)


def test_destroy_keeps_a_disk_lima_reports_in_use(world: World) -> None:
    settings = owned(world)
    world.in_use = True
    with pytest.raises(vm.VmError) as error:
        vm.destroy(settings, world)
    assert code(error) == "DISK_IN_USE"
    assert kept(world)


def test_destroy_after_the_profile_is_already_gone(world: World) -> None:
    settings = owned(world)
    world.profiles.pop("rehearsal")
    shutil.rmtree(world.colima / "_lima" / "colima-rehearsal")
    assert vm.destroy(settings, world)["state"] == "destroyed"
    assert not world.called("colima", "delete")
    assert not ext(world).exists()


# R2: ownership is a record checked against the real resources, not a profile name.

def test_create_refuses_a_profile_it_did_not_make(world: World) -> None:
    world.profiles["rehearsal"] = "Stopped"
    with pytest.raises(vm.VmError) as error:
        vm.create(world.settings(), world)
    assert code(error) == "PROFILE_EXISTS"
    assert not world.called("colima", "start")


@pytest.mark.parametrize("existing", ["ext", "lima"])
def test_create_refuses_targets_that_already_exist(world: World, existing: str) -> None:
    target = ext(world) if existing == "ext" else world.lima("rehearsal")
    target.mkdir(parents=True)
    (target / "datadisk").write_bytes(b"someone else's")
    with pytest.raises(vm.VmError):
        vm.create(world.settings(), world)
    assert (target / "datadisk").read_bytes() == b"someone else's"
    assert not world.called("colima", "start")


def test_destroy_never_deletes_a_profile_without_its_record(world: World) -> None:
    world.profiles["other"] = "Running"
    with pytest.raises(vm.VmError) as error:
        vm.destroy(world.settings(profile="other"), world)
    assert code(error) == "NOT_OWNED"
    assert not world.called("colima", "delete")


def test_a_record_for_one_profile_does_not_own_another(world: World) -> None:
    owned(world)
    world.profiles["other"] = "Running"
    with pytest.raises(vm.VmError) as error:
        vm.destroy(world.settings(profile="other"), world)
    assert code(error) == "NOT_OWNED"
    assert not world.called("colima", "delete")


def test_destroy_refuses_an_external_directory_swapped_for_a_symlink(world: World) -> None:
    settings = owned(world)
    elsewhere = world.root / "elsewhere"
    shutil.move(str(ext(world)), str(elsewhere))
    ext(world).symlink_to(elsewhere)
    with pytest.raises((vm.VmError, private.PrivateError)):
        vm.destroy(settings, world)
    assert (elsewhere / "datadisk").is_file()
    assert not world.called("colima", "delete")


def test_create_refuses_a_disk_root_reached_through_a_symlink(world: World) -> None:
    link = world.root / "ssd-link"
    link.symlink_to(world.disk_root)
    with pytest.raises(private.PrivateError):
        vm.create(world.settings(disk_root=link), world)
    assert not world.called("colima", "start")


def test_a_disk_link_pointing_elsewhere_is_refused_before_any_delete(world: World) -> None:
    settings = owned(world)
    foreign = world.root / "foreign-disk"
    foreign.write_bytes(b"not ours")
    link = world.lima("rehearsal") / "datadisk"
    link.unlink()
    link.symlink_to(foreign)
    with pytest.raises(vm.VmError) as error:
        vm.verify(settings, world)
    assert code(error) == "DISK_LINK_FOREIGN"
    with pytest.raises(vm.VmError):
        vm.destroy(settings, world)
    assert foreign.read_bytes() == b"not ours" and (ext(world) / "datadisk").is_file()
    assert not world.called("colima", "delete")


def test_create_refuses_a_home_with_another_rehearsals_state(world: World) -> None:
    home = private.private_dir(world.home)
    private.write_env(home, "harness.env", {"HARNESS_WEKNORA_API_KEY": "old"})
    with pytest.raises(vm.VmError) as error:
        vm.create(world.settings(), world)
    assert code(error) == "HOME_NOT_EMPTY"


@pytest.mark.parametrize(("variable", "value", "expected"), [
    ("REHEARSAL_PROFILE", "default", "PROFILE_REFUSED"),
    ("REHEARSAL_UI_PORT", "18295", "LIVE_PORT"),
    ("LIVE_CONTEXT", "colima-rehearsal", "SETTINGS_INVALID")])
def test_settings_refuse_the_live_environment(tmp_path: Path, variable: str, value: str,
                                              expected: str) -> None:
    with pytest.raises(vm.VmError) as error:
        vm.Settings.from_env({"HOME": str(tmp_path), variable: value}, tmp_path)
    assert code(error) == expected


# R4: private files in a verified directory, atomic, never through a link, always 0600.

def test_write_tightens_an_existing_loose_file(tmp_path: Path) -> None:
    home = private.private_dir(tmp_path.resolve() / "home")
    loose = home / "secrets.env"
    loose.write_text("OLD=1\n")
    loose.chmod(0o644)
    private.write_env(home, "secrets.env", {"NEW": "2"})
    assert stat.S_IMODE(loose.stat().st_mode) == 0o600
    assert private.read_env(home, "secrets.env") == {"NEW": "2"}


def test_write_replaces_a_planted_symlink_without_touching_its_target(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    home = private.private_dir(root / "home")
    sentinel = root / "sentinel"
    sentinel.write_text("keep me")
    (home / "harness.env").symlink_to(sentinel)
    private.write_env(home, "harness.env", {"KEY": "value"})
    assert sentinel.read_text() == "keep me"
    assert not (home / "harness.env").is_symlink()
    assert stat.S_IMODE((home / "harness.env").stat().st_mode) == 0o600


def test_reads_refuse_symlinks_and_loose_secrets(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    home = private.private_dir(root / "home")
    (root / "outside").write_text("A=1\n")
    (home / "secrets.env").symlink_to(root / "outside")
    with pytest.raises(private.PrivateError):
        private.read_env(home, "secrets.env")
    (home / "app.env").write_text("A=1\n")
    (home / "app.env").chmod(0o644)
    with pytest.raises(private.PrivateError):
        private.read_env(home, "app.env")


def test_private_dir_is_real_owned_and_0700(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    (root / "real").mkdir(mode=0o755)
    assert stat.S_IMODE(private.private_dir(root / "real").stat().st_mode) == 0o700
    (root / "link").symlink_to(root / "real")
    with pytest.raises(private.PrivateError):
        private.private_dir(root / "link")
    (root / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(private.PrivateError):
        private.private_dir(root / "repo" / "home")
