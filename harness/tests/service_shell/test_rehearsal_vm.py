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
teardown: Any = importlib.import_module("teardown")


class World:
    """colima/Lima as far as the rehearsal sees them, with scripted failures."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.disk_root = root / "ssd"
        self.disk_root.mkdir()
        self.colima = root / "colima"
        (self.colima / "_lima" / "_disks").mkdir(parents=True)
        self.profiles: dict[str, str] = {"default": "Running"}
        self.fail: dict[str, int] = {}  # command -> return code, every call
        self.script: dict[str, list[int]] = {}  # command -> return codes for the next calls
        self.in_use = ""  # the instance Lima reports holding the disk
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

    def rc(self, command: str) -> int:
        scripted = self.script.get(command)
        return scripted.pop(0) if scripted else self.fail.get(command, 0)

    def __call__(self, argv: list[str], *, quiet: bool = False, **_: Any) -> Any:
        self.calls.append(list(argv))
        if not quiet:
            self.loud.append(list(argv))
        result = vm.Result
        match argv:
            case ["colima", "list", "--json"]:
                if code := self.rc("list"):
                    return result(code)
                lines = [json.dumps({"name": n, "status": s}) for n, s in self.profiles.items()]
                return result(0, ("\n".join(lines) + "\n").encode())
            case ["colima", "start", "-p", name, *_rest]:
                if code := self.rc("start"):
                    return result(code)
                if name not in self.profiles:
                    self.lima(name).mkdir()
                    (self.lima(name) / "datadisk").write_bytes(b"disk-image" * 4)
                    (self.colima / "_lima" / f"colima-{name}").mkdir()
                self.profiles[name] = "Running"
                (self.lima(name) / "in_use_by").unlink(missing_ok=True)
                (self.lima(name) / "in_use_by").symlink_to(self.colima / "_lima" / f"colima-{name}")
                return result(0)
            case ["colima", "stop", "-p", name]:
                if code := self.rc("stop"):
                    return result(code)
                self.profiles[name] = "Stopped"
                (self.lima(name) / "in_use_by").unlink(missing_ok=True)
                return result(0)
            case ["colima", "delete", "-p", name, "--force"]:
                if code := self.rc("delete"):
                    return result(code)
                self.profiles.pop(name, None)
                shutil.rmtree(self.colima / "_lima" / f"colima-{name}", ignore_errors=True)
                return result(0)  # like colima: the Lima disk entry stays
            case ["limactl", "disk", "list", "--json"]:
                if code := self.rc("disks"):
                    return result(code)
                disks = sorted((self.colima / "_lima" / "_disks").iterdir())
                lines = [json.dumps({"name": d.name, "instance": self.in_use,
                                     "instanceDir": ""}) for d in disks]
                return result(0, "\n".join(lines).encode())
            case ["limactl", "disk", "delete", name]:
                if code := self.rc("disk-delete"):
                    return result(code)
                shutil.rmtree(self.colima / "_lima" / "_disks" / name)
                return result(0)
            case ["cp", *_flags, source, target]:
                if code := self.rc("cp"):
                    return result(code)
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


# R1: everything checkable is checked before the first stop, delete or unlink.

def untouched(world: World) -> bool:
    """No stop or delete was issued and every owned resource is still in place."""
    return (not world.called("colima", "stop") and not world.called("colima", "delete")
            and not world.called("limactl", "disk", "delete") and kept(world)
            and (ext(world) / "owner").is_file())


def state(world: World) -> str:
    return str(private.read_json(world.home, "owner.json")["state"])


def test_create_then_destroy_removes_only_owned_resources(world: World) -> None:
    settings = owned(world)
    assert kept(world)
    assert os.readlink(world.lima("rehearsal") / "datadisk") == str(ext(world) / "datadisk")
    assert state(world) == "ready"
    world.calls.clear()
    assert teardown.destroy(settings, world)["state"] == "destroyed"
    assert not ext(world).exists() and not os.path.lexists(world.lima("rehearsal"))
    assert state(world) == "destroyed"
    order = [call[:3] for call in world.calls]
    assert order.index(["limactl", "disk", "list"]) < order.index(["colima", "stop", "-p"])
    assert teardown.destroy(settings, world)["already"] is True
    # Lima's port-forward daemons outlive colima start: never hand them a pipe (finding F7).
    assert not [call for call in world.loud if call[:2] in (
        ["colima", "start"], ["colima", "stop"], ["colima", "delete"])]


@pytest.mark.parametrize(("failing", "expected"), [("list", "COLIMA_STATE_UNKNOWN"),
                                                    ("disks", "DISK_STATE_UNKNOWN")])
def test_an_unreadable_state_stops_destroy_before_anything_happens(
        world: World, failing: str, expected: str) -> None:
    settings = owned(world)
    world.calls.clear()
    world.fail[failing] = 1
    with pytest.raises(vm.VmError) as error:
        teardown.destroy(settings, world)
    assert code(error) == expected
    assert untouched(world) and "rehearsal" in world.profiles
    assert state(world) == "ready"


def test_a_disk_used_by_another_instance_stops_destroy_first(world: World) -> None:
    settings = owned(world)
    world.calls.clear()
    world.in_use = "colima-other"
    with pytest.raises(vm.VmError) as error:
        teardown.destroy(settings, world)
    assert code(error) == "DISK_IN_USE"
    assert untouched(world) and state(world) == "ready"


def test_unexpected_content_in_the_external_directory_stops_destroy_first(
        world: World) -> None:
    settings = owned(world)
    world.calls.clear()
    (ext(world) / "notes.txt").write_text("someone else's file")
    with pytest.raises(vm.VmError) as error:
        teardown.destroy(settings, world)
    assert code(error) == "EXT_DIR_UNEXPECTED"
    assert untouched(world) and state(world) == "ready"
    assert (ext(world) / "notes.txt").read_text() == "someone else's file"
    (ext(world) / "notes.txt").unlink()  # the operator moves it away: retrying still owns it
    assert teardown.destroy(settings, world)["state"] == "destroyed"


def test_a_failed_delete_keeps_disks_and_a_retry_finishes(world: World) -> None:
    settings = owned(world)
    world.script["delete"] = [42]
    with pytest.raises(vm.VmError) as error:
        teardown.destroy(settings, world)
    assert code(error) == "DELETE_FAILED"
    assert kept(world) and (ext(world) / "owner").is_file()
    assert state(world) == "destroying"
    assert teardown.destroy(settings, world)["state"] == "destroyed"
    assert not ext(world).exists() and not os.path.lexists(world.lima("rehearsal"))


def test_a_failed_recheck_after_delete_keeps_disks_and_a_retry_finishes(world: World) -> None:
    settings = owned(world)
    world.script["disks"] = [0, 1]  # readable before the delete, unreadable right after it
    with pytest.raises(vm.VmError) as error:
        teardown.destroy(settings, world)
    assert code(error) == "DISK_STATE_UNKNOWN"
    assert "rehearsal" not in world.profiles  # the documented residual: the VM is gone
    assert kept(world) and state(world) == "destroying"
    assert teardown.destroy(settings, world)["state"] == "destroyed"
    assert not ext(world).exists() and not os.path.lexists(world.lima("rehearsal"))


def test_a_failed_stop_keeps_everything_but_the_record_says_destroying(world: World) -> None:
    settings = owned(world)
    world.script["stop"] = [1]
    with pytest.raises(vm.VmError) as error:
        teardown.destroy(settings, world)
    assert code(error) == "STOP_FAILED"
    assert kept(world) and "rehearsal" in world.profiles and state(world) == "destroying"
    assert teardown.destroy(settings, world)["state"] == "destroyed"


def test_destroy_after_the_profile_is_already_gone(world: World) -> None:
    settings = owned(world)
    world.profiles.pop("rehearsal")
    shutil.rmtree(world.colima / "_lima" / "colima-rehearsal")
    (world.lima("rehearsal") / "in_use_by").unlink()
    assert teardown.destroy(settings, world)["state"] == "destroyed"
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
        teardown.destroy(world.settings(profile="other"), world)
    assert code(error) == "NOT_OWNED"
    assert not world.called("colima", "delete")


def test_a_record_for_one_profile_does_not_own_another(world: World) -> None:
    owned(world)
    world.profiles["other"] = "Running"
    with pytest.raises(vm.VmError) as error:
        teardown.destroy(world.settings(profile="other"), world)
    assert code(error) == "NOT_OWNED"
    assert not world.called("colima", "delete")


def test_destroy_refuses_an_external_directory_swapped_for_a_symlink(world: World) -> None:
    settings = owned(world)
    elsewhere = world.root / "elsewhere"
    shutil.move(str(ext(world)), str(elsewhere))
    ext(world).symlink_to(elsewhere)
    with pytest.raises((vm.VmError, private.PrivateError)):
        teardown.destroy(settings, world)
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
        teardown.destroy(settings, world)
    assert foreign.read_bytes() == b"not ours" and (ext(world) / "datadisk").is_file()
    assert not world.called("colima", "delete")


def test_create_refuses_a_home_with_another_rehearsals_state(world: World) -> None:
    home = private.private_dir(world.home)
    private.write_env(home, "harness.env", {"HARNESS_WEKNORA_API_KEY": "old"})
    with pytest.raises(vm.VmError) as error:
        vm.create(world.settings(), world)
    assert code(error) == "HOME_NOT_EMPTY"


@pytest.mark.parametrize(("command", "codes", "expected", "stage"), [
    ("stop", [1], "STOP_FAILED", "stopping"),
    ("cp", [1, 1], "COPY_FAILED", "copying"),
    ("start", [0, 1], "START_FAILED", "restarting")])
def test_a_failed_create_is_cleaned_up_by_its_recorded_stage(
        world: World, command: str, codes: list[int], expected: str, stage: str) -> None:
    settings = world.settings()
    world.script[command] = codes
    with pytest.raises(vm.VmError) as error:
        vm.create(settings, world)
    assert code(error) == expected
    record = private.read_json(world.home, "owner.json")
    assert (record["state"], record["stage"]) == ("creating", stage)
    assert teardown.destroy(settings, world)["state"] == "destroyed"
    assert world.called("colima", "delete")
    assert "rehearsal" not in world.profiles
    assert not os.path.lexists(world.lima("rehearsal")) and not ext(world).exists()
    assert vm.create(settings, world)["state"] == "ready"  # and `profile` can run again


def test_an_interrupted_link_swap_is_cleaned_up(world: World) -> None:
    settings = world.settings()
    world.script["start"] = [0, 1]
    with pytest.raises(vm.VmError):
        vm.create(settings, world)
    # The state a crash between staging and swapping the link leaves: Lima's own file in place,
    # our staged link beside it, the record at "linking".
    record = private.read_json(world.home, "owner.json")
    private.write_json(world.home, "owner.json", {**record, "stage": "linking"})
    link = world.lima("rehearsal") / "datadisk"
    link.unlink()
    link.write_bytes(b"lima's own disk")
    (world.lima("rehearsal") / vm.STAGED_LINK).symlink_to(ext(world) / "datadisk")
    assert teardown.destroy(settings, world)["state"] == "destroyed"
    assert not os.path.lexists(world.lima("rehearsal")) and not ext(world).exists()


def test_a_regular_disk_file_is_not_ours_once_the_link_was_made(world: World) -> None:
    settings = owned(world)
    world.calls.clear()
    link = world.lima("rehearsal") / "datadisk"
    link.unlink()
    link.write_bytes(b"someone else's disk")
    with pytest.raises(vm.VmError) as error:
        teardown.destroy(settings, world)
    assert code(error) == "DISK_LINK_FOREIGN"
    assert link.read_bytes() == b"someone else's disk" and (ext(world) / "datadisk").is_file()
    assert not world.called("colima", "stop") and not world.called("colima", "delete")
    assert state(world) == "ready"


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
