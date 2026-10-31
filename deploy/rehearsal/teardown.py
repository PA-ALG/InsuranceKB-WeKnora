"""Destroy the owned rehearsal VM: check everything first, then delete in a fixed order.

`destroy` first inspects without side effects: the ownership record and its creation stage, the
external directory's exact contents and their types, Lima's disk entry and what its `datadisk` is,
colima's profile list and Lima's disk list. Anything unexpected, foreign or unreadable stops it
here with nothing stopped, deleted or rewritten. What each stage may have made is fixed:

    datadisk.partial (external)  only while copying
    datadisk (external)          from copying on
    Lima datadisk as Lima's file until the link swap (creating, stage <= linking)
    Lima datadisk as our link    from linking on, and it must point at the external datadisk
    the staged link              only while linking

Then the record becomes `destroying`, the profile is stopped and deleted, and the checks that only
make sense afterwards run again (profile gone, no Lima instance, disk not in use). A failure from
here on is reported with the record still `destroying`: the profile may already be deleted and
some entries removed, never anything outside the recorded paths, and running destroy again
continues from what is left. The external marker is removed last, so a retry still proves
ownership; an empty, markerless external directory of a `destroying` record is simply removed.
"""

import os
import stat
from dataclasses import dataclass
from pathlib import Path

import private
from vm import (
    MARKER,
    OWNER,
    STAGED_LINK,
    STAGES,
    STATE_FILES,
    Runner,
    Settings,
    VmError,
    checked,
    lima_disk,
    marker_in,
    open_owned_dir,
    owned_record,
    profiles,
)

_EXT_NAMES = {MARKER, "datadisk", "datadisk.partial"}
_LIMA_NAMES = {"datadisk", "in_use_by", STAGED_LINK}


@dataclass(frozen=True)
class _Plan:
    ext_files: tuple[str, ...]  # external data files present, verified regular
    ext_present: bool
    lima: str  # "absent" | "link" | "native"
    staged: bool
    profile_status: str | None


def _stage(record: dict) -> int:
    stage = "ready" if record.get("state") == "ready" else record.get("stage", "dir")
    if stage not in STAGES:
        raise VmError("NOT_OWNED")
    return STAGES.index(stage)


def _inspect_ext(record: dict, stage: int, destroying: bool) -> tuple[bool, tuple[str, ...]]:
    ext_dir = Path(record["ext_dir"])
    if not os.path.lexists(ext_dir):
        if destroying:
            return False, ()
        raise VmError("NOT_OWNED")
    fd = open_owned_dir(ext_dir)
    try:
        names = set(os.listdir(fd))
        if not names <= _EXT_NAMES:
            raise VmError("EXT_DIR_UNEXPECTED")
        if MARKER in names:
            if marker_in(fd) != record.get("creation_id"):
                raise VmError("NOT_OWNED")
        elif not destroying or names:
            raise VmError("NOT_OWNED")
        files = []
        for name, first in (("datadisk.partial", "copying"), ("datadisk", "copying")):
            if name not in names:
                continue
            allowed = stage == STAGES.index(first) if name.endswith(".partial") else (
                stage >= STAGES.index(first))
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or not allowed:
                raise VmError("EXT_DIR_UNEXPECTED")
            files.append(name)
        return True, tuple(files)
    finally:
        os.close(fd)


def _inspect_lima(settings: Settings, record: dict, stage: int,
                  destroying: bool) -> tuple[str, bool]:
    lima_dir = settings.lima_disk_dir
    linking, datadisk = STAGES.index("linking"), str(Path(record["ext_dir"]) / "datadisk")
    if not os.path.lexists(lima_dir):
        if destroying or stage <= STAGES.index("starting"):
            return "absent", False
        raise VmError("DISK_LINK_MISSING")
    if os.path.islink(lima_dir) or not os.path.isdir(lima_dir):
        raise VmError("LIMA_ENTRY_UNEXPECTED")
    names = set(os.listdir(lima_dir))
    if not names <= _LIMA_NAMES:
        raise VmError("LIMA_ENTRY_UNEXPECTED")
    link = lima_dir / "datadisk"
    if "datadisk" not in names:
        if not (destroying or stage <= STAGES.index("starting")):
            raise VmError("DISK_LINK_MISSING")
        kind = "absent"
    elif os.path.islink(link):
        if os.readlink(link) != datadisk or stage < linking:
            raise VmError("DISK_LINK_FOREIGN")
        kind = "link"
    elif stat.S_ISREG(os.lstat(link).st_mode) and stage <= linking:
        kind = "native"  # Lima's own disk, made by this creation before the swap
    else:
        raise VmError("DISK_LINK_FOREIGN")
    staged = STAGED_LINK in names
    if staged and (stage != linking or not os.path.islink(lima_dir / STAGED_LINK)
                   or os.readlink(lima_dir / STAGED_LINK) != datadisk):
        raise VmError("LIMA_ENTRY_UNEXPECTED")
    return kind, staged


def _disk_free(settings: Settings, run: Runner, profile_present: bool) -> None:
    """Lima's disk is used by nothing, or (before the delete) only by this profile."""
    entry = lima_disk(settings, run)
    users = {entry.get("instance") or "", entry.get("instanceDir") or ""} if entry else set()
    ours = {"", settings.context, str(settings.lima_instance_dir)}
    if not users <= (ours if profile_present else {""}):
        raise VmError("DISK_IN_USE")
    if not profile_present and os.path.lexists(settings.lima_disk_dir / "in_use_by"):
        raise VmError("DISK_IN_USE")


def _inspect(settings: Settings, run: Runner, record: dict) -> _Plan:
    destroying, stage = record.get("state") == "destroying", _stage(record)
    ext_present, ext_files = _inspect_ext(record, stage, destroying)
    lima, staged = _inspect_lima(settings, record, stage, destroying)
    status = profiles(run).get(settings.profile)
    if status is None and os.path.lexists(settings.lima_instance_dir):
        raise VmError("INSTANCE_REMAINS")
    _disk_free(settings, run, status is not None)
    return _Plan(ext_files, ext_present, lima, staged, status)


def destroy(settings: Settings, run: Runner) -> dict:
    record = owned_record(settings)
    if record.get("state") == "destroyed":
        return {"profile": settings.profile, "state": "destroyed", "already": True}
    if settings.disk_root is None:
        raise VmError("DISK_ROOT_REQUIRED")
    if record.get("state") not in {"creating", "ready", "destroying"}:
        raise VmError("NOT_OWNED")
    plan = _inspect(settings, run, record)  # no side effect before this line returns
    home = private.private_dir(settings.home)
    record["state"] = "destroying"
    private.write_json(home, OWNER, record)
    if plan.profile_status is not None:
        if plan.profile_status != "Stopped":
            checked(run, ["colima", "stop", "-p", settings.profile], "STOP_FAILED")
        checked(run, ["colima", "delete", "-p", settings.profile, "--force"], "DELETE_FAILED")
        if settings.profile in profiles(run):
            raise VmError("DELETE_UNCONFIRMED")
    if os.path.lexists(settings.lima_instance_dir):
        raise VmError("INSTANCE_REMAINS")
    _disk_free(settings, run, False)
    plan = _inspect(settings, run, record)  # the same rules, now that the profile is gone
    _remove_lima_entry(settings, plan, run)
    _remove_ext_dir(Path(record["ext_dir"]), plan)
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


def _remove_lima_entry(settings: Settings, plan: _Plan, run: Runner) -> None:
    lima_dir = settings.lima_disk_dir
    if plan.staged:
        os.unlink(lima_dir / STAGED_LINK)
    if plan.lima == "link":
        os.unlink(lima_dir / "datadisk")
    elif plan.lima == "native":  # Lima's own file: Lima deletes its disk entry itself
        env = {**os.environ, "LIMA_HOME": str(settings.colima_home / "_lima")}
        if run(["limactl", "disk", "delete", settings.context], env=env, quiet=True).returncode:
            raise VmError("DISK_DELETE_FAILED")
    if os.path.lexists(lima_dir):
        try:
            os.rmdir(lima_dir)
        except OSError:
            raise VmError("LIMA_ENTRY_NOT_EMPTY") from None


def _remove_ext_dir(ext_dir: Path, plan: _Plan) -> None:
    if not plan.ext_present:
        return
    fd = open_owned_dir(ext_dir)
    try:
        for name in plan.ext_files:
            os.unlink(name, dir_fd=fd)
        if MARKER in os.listdir(fd):
            os.unlink(MARKER, dir_fd=fd)  # last: until here a retry still proves ownership
    finally:
        os.close(fd)
    try:
        os.rmdir(ext_dir)
    except OSError:
        raise VmError("EXT_DIR_NOT_EMPTY") from None
