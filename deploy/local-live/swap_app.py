"""Replace the live App container with a new image, keeping its runtime settings (I4).

Same rules as swap_docreader.py: every check runs before any container is touched; env values
never reach stdout, argv or disk (they go from `docker inspect` and the private secrets file, in
memory, to `docker create -e KEY` through the child environment). The 09-28 original is renamed
once (`-pre-s4`) and kept stopped; every swap (forward or back) is rebuilt from it, plus the
contracts dir, the citation signing key, ENTERPRISE_SPACES and the managed env keys below.

Managed env keys are carried over from the CURRENT app container, so a later plain swap keeps
them; `--set-env KEY=VALUE` adds one (`--replace-env` to change its value) and `--unset-env KEY`
removes it. The dry run shows key names only, and managed values as a sha256 prefix.

Usage:
  python3 -I deploy/local-live/swap_app.py <image-id> --private-dir DIR [--spaces FILE]
      [--set-env KEY=VALUE ...] [--unset-env KEY ...] [--replace-env] [--dry-run]
  rollback: run again with the previous image id, unsetting any key the forward swap added.
The container is created, not started: starting and checking it belong to the deploy steps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

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
TYPE_IDS = re.compile(r"[a-z][a-z0-9_]*(?:,[a-z][a-z0-9_]*)*")
# Env keys this tool may add, change or remove, with the accepted value format. Add a key only
# together with the platform setting that reads it.
MANAGED_ENV = {
    # PV-4a: entity types published per product version (comma-separated type ids).
    "ENTERPRISE_VERSIONED_ENTITY_TYPES": TYPE_IDS,
}


class Refused(SystemExit):
    """A check failed before any container was touched (or a docker call failed)."""


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


def plan(opts: argparse.Namespace) -> tuple[list[str], dict[str, str], dict]:
    """Run every check and build the `docker create` arguments (no side effects)."""
    wanted, unset = env_requests(opts.set_env, opts.unset_env)
    private = private_files(opts.private_dir)
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

    # Managed keys and the Spaces guard read the container that is serving now.
    current = old if source == APP else inspect(APP) if APP in names else None
    current_env = env_map(current["Config"].get("Env")) if current else {}
    if spaces is None and SPACES_KEY in current_env:
        raise Refused(f"current app sets {SPACES_KEY}; pass --spaces or it would be dropped; stop")
    managed = {k: current_env[k] for k in MANAGED_ENV if k in current_env}
    absent = [k for k in unset if k not in managed]
    for key in unset:
        managed.pop(key, None)
    for key, value in wanted.items():
        if managed.get(key, value) != value and not opts.replace_env:
            raise Refused(f"current app sets {key} to another value; pass --replace-env; stop")
        managed[key] = value
    for key, value in managed.items():
        if not MANAGED_ENV[key].fullmatch(value):
            raise Refused(f"current app's {key} does not match its format; set or unset it; stop")

    runtime["ENTERPRISE_CONTRACTS_DIR"] = CONTRACTS_DIR
    runtime[SIGNING_KEY] = private_value(private, SIGNING_KEY)
    if spaces is not None:
        runtime[SPACES_KEY] = spaces
    runtime.update(managed)

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

    planned = set(env_map(new["Config"].get("Env"))) | set(runtime)
    summary = {
        "container": APP,
        "source": source,
        "backup": BACKUP,
        "current_image": current["Image"] if current else None,
        "new_image": new["Id"],
        "env_keys": sorted(runtime),
        "env_added": sorted(planned - set(current_env)),
        "env_removed": sorted(set(current_env) - planned),
        "managed": {k: fingerprint(v) for k, v in sorted(managed.items())},
        "unset_absent": absent,
        "enterprise_spaces": spaces is not None,
        "extra_networks": sorted(networks - {NETWORK}),
    }
    return args, child_env, summary


def swap(args: list[str], child_env: dict[str, str], summary: dict) -> None:
    """Every check has passed: only now touch containers."""
    if summary["source"] == APP:
        docker("rename", APP, BACKUP)
    elif APP in container_names():
        if inspect(APP)["State"]["Running"]:
            docker("stop", "-t", "30", APP)
        docker("rm", APP)
    docker(*args, env=child_env)
    # Extra networks (e.g. the provider egress network for model calls) are joined as well.
    for network in summary["extra_networks"]:
        docker("network", "connect", network, APP)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image")
    parser.add_argument("--private-dir", required=True, help="config.yaml, contracts/, secrets.env")
    parser.add_argument("--spaces", help="ENTERPRISE_SPACES JSON file")
    parser.add_argument("--set-env", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--unset-env", action="append", default=[], metavar="KEY")
    parser.add_argument("--replace-env", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    opts = parser.parse_args(argv)
    args, child_env, summary = plan(opts)
    if opts.dry_run:
        print(json.dumps({"dry_run": True, **summary}, ensure_ascii=False))
        return 0
    swap(args, child_env, summary)
    created = inspect(APP)
    result = {**summary, "created_image": created["Image"]}
    result["networks"] = sorted(created["NetworkSettings"]["Networks"])
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
