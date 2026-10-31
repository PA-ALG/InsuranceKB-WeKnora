"""The rehearsal VM: created, verified and destroyed only as the resource this run owns.

Ownership is a record, not a name: `create` refuses any profile, Lima disk or external directory
that already exists, then records a creation id, the instance id and the canonical external disk
directory (with the creation id also written into that directory). Every later step re-checks the
record against the profile's real disk link, the canonical path under
<REHEARSAL_DISK_ROOT>/insurancekb-rehearsal/<profile>, the marker and the Docker context socket.
`destroy` validates everything before its first destructive call, deletes the external disk only
after colima confirms the profile is gone and Lima reports the disk unused, removes entries by name
inside directories opened without following links, and stops (keeping everything) on any failure
or unknown state.
"""

import json
import os
import re
import secrets
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import private

EXT_ROOT = "insurancekb-rehearsal"
MARKER = "owner"
OWNER = "owner.json"
# Private files a destroyed rehearsal leaves behind; removed by name once the VM and disks are gone.
STATE_FILES = ("owner.json", "secrets.env", "app.env", "pg.env", "redis.env", "spaces.env",
               "harness.env", "images.env", "state.json", "config.yaml", "instance-marker.txt")
_PROFILE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")


class VmError(Exception):
    """A fixed code; never a path, command output or secret."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: bytes = b""

    @property
    def text(self) -> str:
        return self.stdout.decode("utf-8", "replace")


Runner = Callable[..., Result]


def run_command(argv: list[str], *, env: dict[str, str] | None = None,
                stdin: bytes | None = None, pipe_to: list[str] | None = None,
                quiet: bool = False, timeout: float = 1800) -> Result:
    """Run one command (or `argv | pipe_to`, streamed) with its output captured, never echoed.

    quiet: no output is wanted, so stdin and output are /dev/null. colima start leaves daemons
    (Lima's ssh ControlMaster that carries port forwards) holding the descriptors it was given; a
    pipe would close when this process exits and take those daemons down with it.
    """
    try:
        if quiet:
            done = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, env=env, timeout=timeout)
            return Result(done.returncode)
        if pipe_to is None:
            done = subprocess.run(argv, input=stdin, capture_output=True, env=env,
                                  timeout=timeout)
            return Result(done.returncode, done.stdout)
        with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              env=env) as first:
            assert first.stdout is not None
            second = subprocess.run(pipe_to, stdin=first.stdout, capture_output=True, env=env,
                                    timeout=timeout)
            first.stdout.close()
            first.wait(timeout=timeout)
        return Result(first.returncode or second.returncode, second.stdout)
    except (OSError, subprocess.TimeoutExpired):
        return Result(127)


@dataclass(frozen=True)
class Settings:
    home: Path
    profile: str
    disk_root: Path | None
    colima_home: Path
    live_context: str
    live_port: int
    ui_port: int
    product: str
    repo: Path

    @classmethod
    def from_env(cls, env: dict[str, str], repo: Path) -> "Settings":
        user_home = Path(env.get("HOME", "/nonexistent"))
        disk_root = env.get("REHEARSAL_DISK_ROOT")
        try:
            settings = cls(
                home=Path(env.get("REHEARSAL_HOME") or user_home / "weknora-rehearsal"),
                profile=env.get("REHEARSAL_PROFILE", "rehearsal"),
                disk_root=Path(disk_root) if disk_root else None,
                colima_home=Path(env.get("REHEARSAL_COLIMA_HOME") or user_home / ".colima"),
                live_context=env.get("LIVE_CONTEXT", "colima"),
                live_port=int(env.get("LIVE_UI_PORT", "18295")),
                ui_port=int(env.get("REHEARSAL_UI_PORT", "18495")),
                product=env.get("REHEARSAL_PRODUCT", "1818"),
                repo=repo,
            )
        except ValueError:
            raise VmError("SETTINGS_INVALID") from None
        settings.validate()
        return settings

    def validate(self) -> None:
        if not _PROFILE.fullmatch(self.profile) or self.profile in {"default", "staging"}:
            raise VmError("PROFILE_REFUSED")
        if self.context == self.live_context or not 1024 <= self.ui_port <= 65535:
            raise VmError("SETTINGS_INVALID")
        if self.ui_port == self.live_port:
            raise VmError("LIVE_PORT")

    @property
    def context(self) -> str:
        return f"colima-{self.profile}"

    @property
    def lima_disk_dir(self) -> Path:
        return self.colima_home / "_lima" / "_disks" / self.context

    @property
    def lima_instance_dir(self) -> Path:
        return self.colima_home / "_lima" / self.context

    @property
    def socket(self) -> str:
        return f"unix://{self.colima_home / self.profile / 'docker.sock'}"

    def ext_dir(self) -> Path:
        if self.disk_root is None:
            raise VmError("DISK_ROOT_REQUIRED")
        return private.canonical(self.disk_root) / EXT_ROOT / self.profile


def profiles(run: Runner) -> dict[str, str]:
    """colima's profiles and their status; any failure is an unknown state."""
    listed = run(["colima", "list", "--json"])
    if listed.returncode != 0:
        raise VmError("COLIMA_STATE_UNKNOWN")
    found = {}
    try:
        for line in listed.text.splitlines():
            if line.strip():
                item = json.loads(line)
                found[item["name"]] = item.get("status", "")
    except (ValueError, KeyError, TypeError):
        raise VmError("COLIMA_STATE_UNKNOWN") from None
    return found


def lima_disk(settings: Settings, run: Runner) -> dict | None:
    """Lima's entry for the profile's data disk; any failure is an unknown state."""
    env = {**os.environ, "LIMA_HOME": str(settings.colima_home / "_lima")}
    listed = run(["limactl", "disk", "list", "--json"], env=env)
    if listed.returncode != 0:
        raise VmError("DISK_STATE_UNKNOWN")
    try:
        for line in listed.text.splitlines():
            if line.strip():
                item = json.loads(line)
                if item.get("name") == settings.context:
                    return item
    except (ValueError, AttributeError):
        raise VmError("DISK_STATE_UNKNOWN") from None
    return None


def _open_owned_dir(path: Path) -> int:
    private.canonical(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        raise VmError("EXT_DIR_INVALID") from None
    if os.fstat(fd).st_uid != os.getuid():
        os.close(fd)
        raise VmError("EXT_DIR_INVALID")
    return fd


def _marker(ext_dir: Path) -> str:
    fd = _open_owned_dir(ext_dir)
    try:
        handle = os.open(MARKER, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(handle, "rb") as marker:
            return marker.read().decode().strip()
    except OSError:
        raise VmError("NOT_OWNED") from None
    finally:
        os.close(fd)


def _owned_record(settings: Settings) -> dict:
    record = private.read_json(private.private_dir(settings.home), OWNER)
    if record is None:
        raise VmError("NOT_OWNED")
    expected = {"profile": settings.profile, "context": settings.context,
                "colima_home": str(settings.colima_home)}
    if any(record.get(key) != value for key, value in expected.items()):
        raise VmError("NOT_OWNED")
    ext_dir = Path(str(record.get("ext_dir", "")))
    if ext_dir.name != settings.profile or ext_dir.parent.name != EXT_ROOT:
        raise VmError("NOT_OWNED")
    if settings.disk_root is not None and ext_dir != settings.ext_dir():
        raise VmError("NOT_OWNED")
    return record


def _check_link(settings: Settings, datadisk: Path, *, required: bool) -> None:
    link = settings.lima_disk_dir / "datadisk"
    if not os.path.lexists(link):
        if required:
            raise VmError("DISK_LINK_MISSING")
        return
    if not os.path.islink(link) or os.readlink(link) != str(datadisk):
        raise VmError("DISK_LINK_FOREIGN")


def verify(settings: Settings, run: Runner) -> dict:
    """The ready, owned rehearsal: record, marker, disk link, live profile and context socket."""
    record = _owned_record(settings)
    if record.get("state") != "ready":
        raise VmError("NOT_READY")
    ext_dir = Path(record["ext_dir"])
    if _marker(ext_dir) != record.get("creation_id"):
        raise VmError("NOT_OWNED")
    datadisk = ext_dir / "datadisk"
    try:
        regular = stat.S_ISREG(os.lstat(datadisk).st_mode)
    except OSError:
        regular = False
    if not regular:
        raise VmError("DISK_INVALID")
    _check_link(settings, datadisk, required=True)
    if settings.profile not in profiles(run):
        raise VmError("PROFILE_MISSING")
    endpoint = run(["docker", "context", "inspect", settings.context,
                    "--format", "{{.Endpoints.docker.Host}}"])
    if endpoint.returncode != 0 or endpoint.text.strip() != settings.socket:
        raise VmError("CONTEXT_NOT_REHEARSAL")
    return record


def start(settings: Settings, run: Runner) -> None:
    """Start the owned VM if `down` stopped it (a stopped profile has no Docker context)."""
    record = _owned_record(settings)
    if record.get("state") != "ready":
        raise VmError("NOT_READY")
    if _marker(Path(record["ext_dir"])) != record.get("creation_id"):
        raise VmError("NOT_OWNED")
    _check_link(settings, Path(record["ext_dir"]) / "datadisk", required=True)
    if profiles(run).get(settings.profile) == "Stopped":
        try:
            _checked(run, ["colima", "start", "-p", settings.profile], "START_FAILED")
        finally:
            run(["docker", "context", "use", settings.live_context])


def _checked(run: Runner, argv: list[str], code: str) -> None:
    if run(argv, quiet=True).returncode != 0:
        raise VmError(code)


def create(settings: Settings, run: Runner) -> dict:
    home = private.private_dir(settings.home)
    previous = private.read_json(home, OWNER)
    leftovers = [name for name in os.listdir(home) if name != "logs"]
    if (previous or {}).get("state", "destroyed") != "destroyed" or (
            leftovers and leftovers != [OWNER]):
        raise VmError("HOME_NOT_EMPTY")
    ext_dir = settings.ext_dir()
    if settings.profile in profiles(run):
        raise VmError("PROFILE_EXISTS")
    if os.path.lexists(settings.lima_disk_dir) or os.path.lexists(settings.lima_instance_dir):
        raise VmError("LIMA_ENTRY_EXISTS")
    try:
        os.mkdir(ext_dir.parent, 0o700)
    except FileExistsError:
        pass
    os.close(_open_owned_dir(ext_dir.parent))
    try:
        os.mkdir(ext_dir, 0o700)
    except FileExistsError:
        raise VmError("EXT_DIR_EXISTS") from None
    record: dict[str, Any] = {
        "version": 1, "creation_id": secrets.token_hex(16), "instance_id": secrets.token_hex(16),
        "profile": settings.profile, "context": settings.context,
        "colima_home": str(settings.colima_home), "ext_dir": str(ext_dir),
        "ui_port": settings.ui_port, "state": "creating"}
    fd = _open_owned_dir(ext_dir)
    try:
        marker = os.open(MARKER, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600,
                         dir_fd=fd)
        os.write(marker, record["creation_id"].encode())
        os.close(marker)
    finally:
        os.close(fd)
    private.write_json(home, OWNER, record)
    try:
        _checked(run, ["colima", "start", "-p", settings.profile, "--cpu", "4", "--memory", "5",
                       "--disk", "40", "--vm-type", "vz"], "START_FAILED")
        _checked(run, ["colima", "stop", "-p", settings.profile], "STOP_FAILED")
        _move_disk(settings, ext_dir, run)
        _checked(run, ["colima", "start", "-p", settings.profile], "START_FAILED")
    finally:
        run(["docker", "context", "use", settings.live_context])
    record["state"] = "ready"
    private.write_json(home, OWNER, record)
    return {"profile": settings.profile, "state": "ready"}


def _move_disk(settings: Settings, ext_dir: Path, run: Runner) -> None:
    """Copy Lima's new data disk into the owned directory, then swap in a link atomically."""
    link = settings.lima_disk_dir / "datadisk"
    if not stat.S_ISREG(os.lstat(link).st_mode):
        raise VmError("DISK_INVALID")
    partial, datadisk = ext_dir / "datadisk.partial", ext_dir / "datadisk"
    if os.path.lexists(partial) or os.path.lexists(datadisk):
        raise VmError("EXT_DIR_EXISTS")
    if run(["cp", "-c", str(link), str(partial)]).returncode != 0:
        _checked(run, ["cp", str(link), str(partial)], "COPY_FAILED")
    copied = os.lstat(partial)
    if not stat.S_ISREG(copied.st_mode) or copied.st_size != os.lstat(link).st_size:
        raise VmError("COPY_FAILED")
    fd = _open_owned_dir(ext_dir)
    try:
        os.rename("datadisk.partial", "datadisk", src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        os.close(fd)
    staged = settings.lima_disk_dir / ".datadisk.rehearsal-link"
    os.symlink(datadisk, staged)
    os.replace(staged, link)
    _check_link(settings, datadisk, required=True)


def destroy(settings: Settings, run: Runner) -> dict:
    record = _owned_record(settings)
    if record.get("state") == "destroyed":
        return {"profile": settings.profile, "state": "destroyed", "already": True}
    if settings.disk_root is None:
        raise VmError("DISK_ROOT_REQUIRED")
    ext_dir = Path(record["ext_dir"])
    if _marker(ext_dir) != record.get("creation_id"):
        raise VmError("NOT_OWNED")
    _check_link(settings, ext_dir / "datadisk", required=False)
    listed = profiles(run)
    if settings.profile in listed:
        if listed[settings.profile] != "Stopped":
            _checked(run, ["colima", "stop", "-p", settings.profile], "STOP_FAILED")
        _checked(run, ["colima", "delete", "-p", settings.profile, "--force"], "DELETE_FAILED")
        if settings.profile in profiles(run):
            raise VmError("DELETE_UNCONFIRMED")
    if os.path.lexists(settings.lima_instance_dir):
        raise VmError("INSTANCE_REMAINS")
    entry = lima_disk(settings, run)
    if (entry and (entry.get("instance") or entry.get("instanceDir"))) or os.path.lexists(
            settings.lima_disk_dir / "in_use_by"):
        raise VmError("DISK_IN_USE")
    _remove_lima_entry(settings, ext_dir / "datadisk", run)
    _remove_ext_dir(ext_dir)
    home = private.private_dir(settings.home)
    fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in STATE_FILES:
            if name != OWNER and os.path.lexists(home / name):
                os.unlink(name, dir_fd=fd)
    finally:
        os.close(fd)
    record["state"] = "destroyed"
    private.write_json(home, OWNER, record)
    run(["docker", "context", "use", settings.live_context])
    # Run outputs (registry, compile and review responses) hold no secret and are kept as
    # evidence; move them away before the next `profile`, which needs an empty home.
    kept = sorted(name for name in os.listdir(home) if name != OWNER)
    return {"profile": settings.profile, "state": "destroyed", "kept": kept}


def _remove_lima_entry(settings: Settings, datadisk: Path, run: Runner) -> None:
    link = settings.lima_disk_dir / "datadisk"
    if os.path.islink(link):
        _check_link(settings, datadisk, required=True)
        os.unlink(link)
    elif os.path.lexists(link):  # creation stopped before the swap: Lima's own disk
        env = {**os.environ, "LIMA_HOME": str(settings.colima_home / "_lima")}
        if run(["limactl", "disk", "delete", settings.context], env=env).returncode != 0:
            raise VmError("DISK_DELETE_FAILED")
    if os.path.lexists(settings.lima_disk_dir):
        try:
            os.rmdir(settings.lima_disk_dir)
        except OSError:
            raise VmError("LIMA_ENTRY_NOT_EMPTY") from None


def _remove_ext_dir(ext_dir: Path) -> None:
    fd = _open_owned_dir(ext_dir)
    try:
        for name in ("datadisk", "datadisk.partial"):
            try:
                info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode):
                raise VmError("DISK_INVALID")
            os.unlink(name, dir_fd=fd)
        os.unlink(MARKER, dir_fd=fd)
    finally:
        os.close(fd)
    try:
        os.rmdir(ext_dir)
    except OSError:
        raise VmError("EXT_DIR_NOT_EMPTY") from None
