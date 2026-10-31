"""Replace the live docreader container with a new image, keeping its runtime settings.

Same rules as the App/UI swap scripts: every check runs before any container is touched; env values
never reach stdout, argv or disk (they go from `docker inspect` in memory to `docker create -e KEY`
through the child environment); the original container is renamed once and kept stopped as the
rollback source, and every later swap (forward or back) is rebuilt from that original.

The new container takes the NEW image's entrypoint and command (v0.9.0 adds an ARM OpenSSL probe
entrypoint), so an override on the original container is refused rather than copied.

Usage (live defaults; staging passes --container/--network/--volume):
  python3 -I deploy/local-live/swap_docreader.py <image-id> [--dry-run] [--start]
  rollback: run again with the original image id, then --start.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

PREFIX = "upg-final-082-20260928-live"
DEFAULTS = {
    "container": f"{PREFIX}-docreader",
    "network": f"{PREFIX}-net",
    "volume": f"{PREFIX}-docreader-tmp",
}
BACKUP_SUFFIX = "-pre-v090"
TMP_DIR = "/tmp/docreader"
GRPC_PORT = 50051
RUNTIME_KEYS = {
    "DOCREADER_EXTERNAL_HTTPS_PROXY",
    "DOCREADER_EXTERNAL_HTTP_PROXY",
    "DOCREADER_GRPC_MAX_FILE_SIZE_MB",
    "DOCREADER_GRPC_PORT",
    "DOCREADER_ODL_HYBRID",
    "DOCREADER_ODL_HYBRID_URL",
}
READY_PROBE = (
    "import socket,sys;s=socket.socket();s.settimeout(2);"
    f"sys.exit(0 if s.connect_ex(('127.0.0.1',{GRPC_PORT}))==0 else 1)"
)


class Refused(SystemExit):
    """A check failed before any container was touched (or a docker call failed)."""


def docker(*args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, env=env)
    if result.returncode:
        raise Refused(f"docker {args[0]} {args[1] if len(args) > 1 else ''} failed")
    return result.stdout


def inspect(name: str, kind: str = "container") -> dict:
    return json.loads(docker(kind, "inspect", name))[0]


def env_map(rows: list[str] | None) -> dict[str, str]:
    return dict(row.split("=", 1) for row in rows or [])


def plan(new_image: str, container: str, network: str, volume: str) -> tuple[list[str], dict[str, str], dict]:
    """Validate the original container and build the `docker create` arguments (no side effects)."""
    new = inspect(new_image, "image")  # an unknown image stops here
    names = {c["Names"] for c in map(json.loads, docker("ps", "-a", "--format", "{{json .}}").splitlines())}
    backup = container + BACKUP_SUFFIX
    source_name = backup if backup in names else container
    if source_name not in names:
        raise Refused("no docreader container to read settings from; stop")
    old = inspect(source_name)
    old_image = inspect(old["Image"], "image")

    mounts = [(m.get("Type"), m.get("Name"), m["Destination"], m["RW"]) for m in old["Mounts"]]
    if mounts != [("volume", volume, TMP_DIR, True)]:
        raise Refused("docreader mount layout changed; stop")
    if old["HostConfig"].get("PortBindings"):
        raise Refused("docreader publishes host ports; stop")
    networks = old["NetworkSettings"]["Networks"]
    if network not in networks:
        raise Refused("docreader is not on the expected network; stop")
    if (old["Config"].get("Entrypoint"), old["Config"].get("Cmd")) != (
        old_image["Config"].get("Entrypoint"),
        old_image["Config"].get("Cmd"),
    ):
        raise Refused("original container overrides entrypoint/cmd; stop")
    if old["Config"].get("User") or new["Config"].get("User"):
        raise Refused("unexpected user setting; stop")

    image_env = env_map(old_image["Config"].get("Env"))
    runtime = {k: v for k, v in env_map(old["Config"].get("Env")).items() if image_env.get(k) != v}
    if set(runtime) - RUNTIME_KEYS:
        raise Refused("unexpected runtime env on docreader; stop")

    image_labels = old_image["Config"].get("Labels") or {}
    labels = {k: v for k, v in (old["Config"].get("Labels") or {}).items() if image_labels.get(k) != v}
    restart = old["HostConfig"].get("RestartPolicy") or {}

    args = ["create", "--name", container, "--network", network, "-v", f"{volume}:{TMP_DIR}"]
    aliases = [a for a in (networks[network].get("Aliases") or []) if a != old["Id"][:12]]
    for alias in aliases:
        args += ["--network-alias", alias]
    if restart.get("Name") and restart["Name"] != "no":
        policy = restart["Name"]
        if policy == "on-failure" and restart.get("MaximumRetryCount"):
            policy += f":{restart['MaximumRetryCount']}"
        args += ["--restart", policy]
    for key, value in sorted(labels.items()):
        args += ["--label", f"{key}={value}"]
    for key in sorted(runtime):
        args += ["-e", key]
    args.append(new_image)
    child_env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", ""), **runtime}
    if "DOCKER_CONTEXT" in os.environ:
        child_env["DOCKER_CONTEXT"] = os.environ["DOCKER_CONTEXT"]
    summary = {
        "container": container,
        "source": source_name,
        "backup": backup,
        "old_image": old["Image"],
        "new_image": new["Id"],
        "env_keys": sorted(runtime),
        "aliases": aliases,
        "extra_networks": sorted(set(networks) - {network}),
        "restart": restart.get("Name", "no"),
        "labels": sorted(labels),
    }
    return args, child_env, summary


def swap(args: list[str], child_env: dict[str, str], summary: dict) -> None:
    container, backup, source = summary["container"], summary["backup"], summary["source"]
    names = {c["Names"] for c in map(json.loads, docker("ps", "-a", "--format", "{{json .}}").splitlines())}
    if source == container:
        if inspect(container)["State"]["Running"]:
            docker("stop", "-t", "30", container)
        docker("rename", container, backup)
    elif container in names:
        if inspect(container)["State"]["Running"]:
            docker("stop", "-t", "30", container)
        docker("rm", container)
    docker(*args, env=child_env)
    for network in summary["extra_networks"]:
        docker("network", "connect", network, container)


def start_and_wait(container: str, timeout: float = 90.0) -> float:
    docker("start", container)
    began = time.monotonic()
    while time.monotonic() - began < timeout:
        probe = subprocess.run(
            ["docker", "exec", container, "python", "-c", READY_PROBE],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return round(time.monotonic() - began, 1)
        if not inspect(container)["State"]["Running"]:
            raise Refused("docreader exited during startup")
        time.sleep(2)
    raise Refused("docreader gRPC port not ready in time")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--start", action="store_true")
    for key, value in DEFAULTS.items():
        parser.add_argument(f"--{key}", default=value)
    opts = parser.parse_args(argv)
    args, child_env, summary = plan(opts.image, opts.container, opts.network, opts.volume)
    if opts.dry_run:
        print(json.dumps({"dry_run": True, **summary}, ensure_ascii=False))
        return 0
    swap(args, child_env, summary)
    created = inspect(opts.container)
    result = {**summary, "created_image": created["Image"]}
    if opts.start:
        result["ready_after_s"] = start_and_wait(opts.container)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
