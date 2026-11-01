"""Replace the live App container with a new image, keeping its runtime settings (I4).

Same rules as swap_docreader.py: every check runs before any container is touched; env values
never reach stdout or argv (they go from `docker inspect` and the private secrets file, in
memory, to `docker create -e KEY` through the child environment). The 09-28 original is renamed
once (`-pre-s4`) and kept stopped; every swap (forward or back) is rebuilt from it, plus the
contracts dir, the citation signing key, ENTERPRISE_SPACES and the managed env keys below.

Managed env keys are carried over from the CURRENT app container, so a later plain swap keeps
them; `--set-env KEY=VALUE` adds one (`--replace-env` to change its value) and `--unset-env KEY`
removes it. Before touching containers the tool writes the new container's managed values and
whether it has Spaces to an intent record in the private dir (0600), so a rerun after a failed
create recovers them. The record is bound to the docker context, the App name and the rebuild
source's container ID; a record from another environment is never inherited. Managed values are
type ids, not secrets; no other env value is written anywhere. The dry run shows key names only,
and managed values as a sha256 prefix.

Usage:
  python3 -I deploy/local-live/swap_app.py <image-id> --private-dir DIR [--spaces FILE]
      [--set-env KEY=VALUE ...] [--unset-env KEY ...] [--replace-env] [--dry-run]
  rollback: run again with the previous image id, unsetting any key the forward swap added.
The container is created, not started: starting and checking it belong to the deploy steps.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple, NoReturn

PREFIX = "upg-final-082-20260928-live"
APP = f"{PREFIX}-app"
BACKUP = f"{APP}-pre-s4"
NETWORK = f"{PREFIX}-net"
ORIGINAL_IMAGE = "sha256:1759adb029c6b2b902b720bcb8a3b85fe0ca79ecf65e47be27bae44da4316649"
VOLUMES = (
    (f"{PREFIX}-files", "/data/files", True),
    (f"{PREFIX}-c5", "/run/insurancekb/c5", False),
    (f"{PREFIX}-docreader-tmp", "/tmp/docreader", False),
)
CONTRACTS_DIR = "/app/contracts"
SIGNING_KEY = "E2E_CITATION_SIGNING_KEY"
SPACES_KEY = "ENTERPRISE_SPACES"
INTENT_RECORD = "swap_app.intent.json"
# The record belongs to an environment when these match: docker context, App name, rebuild source.
RECORD_IDENTITY = ("context", "container", "source_id")
RECORD_FIELDS = {"version", *RECORD_IDENTITY, "current_id", "managed", "spaces"}
PLAIN_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
TYPE_IDS = re.compile(r"[a-z][a-z0-9_]*(?:,[a-z][a-z0-9_]*)*")
# Env keys this tool may add, change or remove, with the accepted value format. Add a key only
# together with the platform setting that reads it.
MANAGED_ENV = {
    # PV-4a: entity types published per product version (comma-separated type ids).
    "ENTERPRISE_VERSIONED_ENTITY_TYPES": TYPE_IDS,
}


class Refused(SystemExit):
    """A check failed before any container was touched (or a docker call failed)."""


class Parser(argparse.ArgumentParser):
    """Parse errors print a fixed message: a mistyped option may carry an env value."""

    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: arguments rejected (not echoed); see --help\n")


class Plan(NamedTuple):
    args: list[str]
    child_env: dict[str, str]
    summary: dict
    record_path: Path
    record: dict


def docker(*args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, env=env)
    if result.returncode:
        raise Refused(f"docker {args[0]} {args[1] if len(args) > 1 else ''} failed")
    return result.stdout


def inspect(name: str, kind: str = "container") -> dict:
    return json.loads(docker(kind, "inspect", name))[0]


def container_names() -> set[str]:
    rows = docker("ps", "-a", "--format", "{{json .}}").splitlines()
    return {json.loads(row)["Names"] for row in rows}


def env_map(rows: list[str] | None) -> dict[str, str]:
    return dict(row.split("=", 1) for row in rows or [])


def fingerprint(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def passable(text: object) -> bool:
    """Whether a string reaches argv or the child environment unchanged (no NUL, encodable)."""
    if not isinstance(text, str) or "\0" in text:
        return False
    try:
        os.fsencode(text)
    except UnicodeError:
        return False
    return True


def env_requests(sets: list[str], unsets: list[str]) -> tuple[dict[str, str], list[str]]:
    """Validate --set-env/--unset-env. Messages name managed keys only, never a value."""
    allowed = ", ".join(MANAGED_ENV)
    wanted: dict[str, str] = {}
    for item in sets:
        key, sep, value = item.partition("=")
        if not sep:
            raise Refused("--set-env needs KEY=VALUE; stop")
        if key not in MANAGED_ENV:
            raise Refused(f"--set-env key is not managed by this tool (allowed: {allowed}); stop")
        if key in wanted:
            raise Refused(f"--set-env {key} given twice; stop")
        if not MANAGED_ENV[key].fullmatch(value):
            raise Refused(f"--set-env {key} value does not match its format; stop")
        wanted[key] = value
    removed: list[str] = []
    for key in unsets:
        if key not in MANAGED_ENV:
            raise Refused(f"--unset-env key is not managed by this tool (allowed: {allowed}); stop")
        if key in removed:
            raise Refused(f"--unset-env {key} given twice; stop")
        if key in wanted:
            raise Refused(f"{key} is both set and unset; stop")
        removed.append(key)
    return wanted, removed


def private_files(private_dir: str) -> Path:
    private = Path(private_dir).resolve()
    if ":" in str(private):
        raise Refused("private dir path contains ':', which docker -v cannot express; stop")
    if not (
        (private / "config.yaml").is_file()
        and (private / "contracts").is_dir()
        and (private / "secrets.env").is_file()
    ):
        raise Refused("private dir must hold config.yaml, contracts/ and secrets.env; stop")
    return private


def private_value(private: Path, key: str) -> str:
    for line in (private / "secrets.env").read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1]
    raise Refused(f"{key} missing from the private secrets file; stop")


def read_spaces(path: str | None) -> str | None:
    if path is None:
        return None
    try:
        spaces = Path(path).read_text(encoding="utf-8").strip()
        json.loads(spaces)  # malformed config must stop here, not at boot
    except (OSError, ValueError):
        raise Refused("spaces file is unreadable or not JSON; stop") from None
    return spaces


def unique_members(pairs: list[tuple[str, object]]) -> dict:
    """JSON object hook: a duplicate member makes the record ambiguous, so it counts as corrupt."""
    members = dict(pairs)
    if len(members) != len(pairs):
        raise ValueError("duplicate member")
    return members


def well_formed(record: object) -> bool:
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
        return False
    managed, current_id = record["managed"], record["current_id"]
    return (
        type(record["version"]) is int
        and record["version"] == 1
        and all(isinstance(record[k], str) for k in RECORD_IDENTITY)
        and (current_id is None or isinstance(current_id, str))
        and isinstance(managed, dict)
        and set(managed) <= set(MANAGED_ENV)
        and all(isinstance(v, str) for v in managed.values())
        and isinstance(record["spaces"], bool)
    )


def regular_or_absent(path: Path) -> bool:
    """True when nothing is at `path`; refuses anything but a regular file (links included)."""
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return True
    except OSError:
        raise Refused("intent_record_invalid: cannot stat the intent record; stop") from None
    if not stat.S_ISREG(info.st_mode):
        raise Refused("intent_record_invalid: intent record is not a regular file; stop")
    return False


def read_record(path: Path) -> dict | None:
    """The intent of the last swap that reached the write step; None when there is none."""
    if regular_or_absent(path):
        return None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, encoding="utf-8") as handle:
            record = json.loads(handle.read(), object_pairs_hook=unique_members)
    except (OSError, ValueError):
        raise Refused("intent_record_invalid: intent record is unreadable; stop") from None
    if not well_formed(record):
        raise Refused("intent_record_invalid: intent record is malformed; stop")
    return record


def write_record(path: Path, record: dict) -> None:
    """A fresh exclusive temp file in the private dir, fsynced, then renamed onto the record."""
    regular_or_absent(path)
    tmp: str | None = None
    try:
        # mkstemp opens O_CREAT|O_EXCL|O_NOFOLLOW under a random name: never an existing file.
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            made = os.fstat(handle.fileno())
            if made.st_uid != os.geteuid() or made.st_nlink != 1:
                raise OSError("temporary record file is not exclusively ours")
            json.dump(record, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)  # rename replaces a link at `path` itself, never its target
        tmp = None
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError:
        raise Refused(
            "intent_record_unwritable: cannot write the intent record; no container was touched"
        ) from None
    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp)


def carried_managed(
    current_env: dict[str, str] | None, record: dict | None, foreign: bool, explicit: set[str]
) -> dict[str, str]:
    """Managed values to carry: from the serving app, else from this environment's record.

    A record from another environment is never inherited, and with no source at all the values
    cannot be recovered: in both cases every managed key must be stated explicitly.
    """
    missing = sorted(set(MANAGED_ENV) - explicit)
    keys = ", ".join(missing)
    if foreign and missing:
        raise Refused(
            "intent_record_mismatch: the intent record belongs to another environment; "
            f"--set-env or --unset-env {keys}; stop"
        )
    if current_env is not None:
        carried = {k: current_env[k] for k in MANAGED_ENV if k in current_env}
        recorded = record["managed"] if record is not None else carried
        for key in missing:
            if carried.get(key) != recorded.get(key):
                raise Refused(
                    f"intent_record_disagrees: current app and intent record differ on {key}; "
                    "set or unset it; stop"
                )
        return carried
    if record is not None:
        return dict(record["managed"])
    if missing:
        raise Refused(
            f"intent_record_missing: no current app and no intent record; --set-env or --unset-env "
            f"{keys}; stop"
        )
    return {}


def plan(opts: argparse.Namespace) -> Plan:
    """Run every check and build the `docker create` arguments (no side effects)."""
    wanted, unset = env_requests(opts.set_env, opts.unset_env)
    private = private_files(opts.private_dir)
    record = read_record(private / INTENT_RECORD)
    spaces = read_spaces(opts.spaces)
    new = inspect(opts.image, "image")  # an unknown image stops here

    # Source of truth for runtime settings: the original container (renamed once).
    names = container_names()
    source = BACKUP if BACKUP in names else APP
    if source not in names:
        raise Refused("no app container to read settings from; stop")
    old = inspect(source)
    if old["Image"] != ORIGINAL_IMAGE or old["State"]["Running"]:
        raise Refused("source container is not the stopped 09-28 app; stop")
    mounts = {(m.get("Name"), m["Destination"], m["RW"]) for m in old["Mounts"]}
    networks = set(old["NetworkSettings"]["Networks"])
    if mounts != set(VOLUMES) or NETWORK not in networks:
        raise Refused("source container layout changed; stop")
    # The 09-28 app ran its binary directly as 1000:1000, bypassing the image's
    # privilege-dropping entrypoint script; keep exactly that.
    entrypoint, command = old["Config"].get("Entrypoint") or [], old["Config"].get("Cmd") or []
    if len(entrypoint) != 1:
        raise Refused("source container entrypoint changed; stop")

    image_env = env_map(inspect(ORIGINAL_IMAGE, "image")["Config"].get("Env"))
    runtime = {k: v for k, v in env_map(old["Config"].get("Env")).items() if image_env.get(k) != v}
    if set(runtime) & set(MANAGED_ENV):
        raise Refused("source container sets a managed env key; stop")

    # Managed keys and the Spaces guard read the serving container, else the intent record of
    # this environment (the backup's ID is stable: it is the container every swap rebuilds from).
    context = docker("context", "show").strip()
    identity = {"context": context, "container": APP, "source_id": old["Id"]}
    own = record is not None and all(record[k] == identity[k] for k in RECORD_IDENTITY)
    usable = record if own else None
    current = old if source == APP else inspect(APP) if APP in names else None
    current_env = env_map(current["Config"].get("Env")) if current else {}
    managed = carried_managed(
        current_env if current else None, usable, record is not None and not own, {*wanted, *unset}
    )
    if spaces is None and (SPACES_KEY in current_env or (usable or {}).get("spaces")):
        raise Refused(f"current app or intent record has {SPACES_KEY}; pass --spaces; stop")
    absent = [k for k in unset if k not in managed]
    for key in unset:
        managed.pop(key, None)
    for key, value in wanted.items():
        if managed.get(key, value) != value and not opts.replace_env:
            raise Refused(f"current app sets {key} to another value; pass --replace-env; stop")
        managed[key] = value

    runtime["ENTERPRISE_CONTRACTS_DIR"] = CONTRACTS_DIR
    runtime[SIGNING_KEY] = private_value(private, SIGNING_KEY)
    if spaces is not None:
        runtime[SPACES_KEY] = spaces
    runtime.update(managed)

    # Managed keys are judged on the container's effective env: new image defaults + runtime.
    effective_env = {**env_map(new["Config"].get("Env")), **runtime}
    for key in unset:
        if key in effective_env:
            raise Refused(f"new image sets {key} by default; --unset-env cannot remove it; stop")
    effective = {k: effective_env[k] for k in MANAGED_ENV if k in effective_env}
    for key, value in effective.items():
        if not MANAGED_ENV[key].fullmatch(value):
            raise Refused(f"effective {key} does not match its format; set or unset it; stop")

    args = ["create", "--name", APP, "--network", NETWORK, "--user", old["Config"]["User"]]
    args += ["--entrypoint", entrypoint[0]]
    args += ["--memory", str(old["HostConfig"]["Memory"])]
    args += ["--memory-swap", str(old["HostConfig"]["MemorySwap"])]
    args += ["--label", f"io.insurancekb.cutover-owner={PREFIX}"]
    for name, destination, writable in VOLUMES:
        args += ["-v", f"{name}:{destination}" + ("" if writable else ":ro")]
    args += ["-v", f"{private}/config.yaml:/app/config/config.yaml:ro"]
    args += ["-v", f"{private}/contracts:{CONTRACTS_DIR}:ro"]
    for key in sorted(runtime):
        args += ["-e", key]
    args += [new["Id"], *command]
    child_env = {"PATH": os.environ["PATH"], "HOME": str(Path.home()), **runtime}
    if "DOCKER_CONTEXT" in os.environ:
        child_env["DOCKER_CONTEXT"] = os.environ["DOCKER_CONTEXT"]
    # A string subprocess cannot pass would fail at `create`, after the current app is gone.
    if not all(passable(item) for item in args):
        raise Refused("a docker create argument cannot be passed safely; stop")
    for key, value in child_env.items():
        if not (key and "=" not in key and passable(key) and passable(value)):
            label = key if PLAIN_NAME.fullmatch(key) else "an env key"
            raise Refused(f"env value for {label} cannot be passed safely; stop")

    summary = {
        "container": APP,
        "source": source,
        "backup": BACKUP,
        "current_image": current["Image"] if current else None,
        "new_image": new["Id"],
        "env_keys": sorted(runtime),
        "env_added": sorted(set(effective_env) - set(current_env)),
        "env_removed": sorted(set(current_env) - set(effective_env)),
        "managed": {k: fingerprint(v) for k, v in sorted(effective.items())},
        "unset_absent": absent,
        "enterprise_spaces": spaces is not None,
        "intent_record": "absent" if record is None else "own" if own else "foreign",
        "extra_networks": sorted(networks - {NETWORK}),
    }
    record_next = {
        "version": 1,
        **identity,
        "current_id": current["Id"] if current else None,
        "managed": effective,
        "spaces": spaces is not None,
    }
    return Plan(args, child_env, summary, private / INTENT_RECORD, record_next)


def swap(plan: Plan) -> None:
    """Every check has passed: record the intent, then touch containers."""
    write_record(plan.record_path, plan.record)
    if plan.summary["source"] == APP:
        docker("rename", APP, BACKUP)
    elif APP in container_names():
        if inspect(APP)["State"]["Running"]:
            docker("stop", "-t", "30", APP)
        docker("rm", APP)
    docker(*plan.args, env=plan.child_env)
    # Extra networks (e.g. the provider egress network for model calls) are joined as well.
    for network in plan.summary["extra_networks"]:
        docker("network", "connect", network, APP)


def main(argv: list[str]) -> int:
    parser = Parser(description=__doc__.splitlines()[0], allow_abbrev=False)
    parser.add_argument("image")
    parser.add_argument("--private-dir", required=True, help="config.yaml, contracts/, secrets.env")
    parser.add_argument("--spaces", help="ENTERPRISE_SPACES JSON file")
    parser.add_argument("--set-env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--unset-env", action="append", default=[], metavar="KEY")
    parser.add_argument("--replace-env", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    opts = parser.parse_args(argv)
    planned = plan(opts)
    if opts.dry_run:
        print(json.dumps({"dry_run": True, **planned.summary}, ensure_ascii=False))
        return 0
    swap(planned)
    created = inspect(APP)
    result = {**planned.summary, "created_image": created["Image"]}
    result["networks"] = sorted(created["NetworkSettings"]["Networks"])
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
