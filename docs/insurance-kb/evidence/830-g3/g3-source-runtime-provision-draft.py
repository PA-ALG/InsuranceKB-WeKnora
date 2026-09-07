#!/usr/bin/env python3
"""Draft G3 source-runtime provisioner.

This file is deliberately inert unless invoked with either ``preflight`` or
``apply``.  ``preflight`` performs read-only Docker/PostgreSQL inspection and
writes a local receipt.  ``apply`` is a one-shot, fail-closed mutation runner;
it requires a matching preflight receipt and a separate authorization receipt.

The draft never starts an embedding guard, never sends provider traffic, and
never uploads PDFs.  It uses only locally present image digests with
``--pull=never``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request


os.umask(0o077)

CONTRACT = "830-g3-source-runtime-provision-draft.v1"
PREFLIGHT_CONTRACT = "830-g3-source-runtime-provision-preflight.v1"
AUTH_CONTRACT = "830-g3-source-runtime-provision-authorization.v1"
RECEIPT_CONTRACT = "830-g3-source-runtime-provision-apply.v1"

WORKTREE = Path(
    "/Users/houjing/Documents/LLM_wiki/insurancekb-weknora/"
    ".worktrees/830-g3-implementation"
)
EVIDENCE = WORKTREE / "docs/insurance-kb/evidence/830-g3"
FROZEN_FILES = {
    "runtime-config-readonly.json":
        "28756d379087d64133a665a15c61083df56983ea574ba3cfc18c4d82ba16e2cc",
    "runtime-readonly-preflight.json":
        "3d8fff08813ccbc2e9f437132644c5a39be2f60e69dfe5de598caf5187cd0765",
    "runtime-readonly-extra.json":
        "60f84b501f257dffa7dda759228993b40c57d46cd8dc4c52637e47865ffdeec1",
    "source-runtime-isolation-plan.md":
        "a5ebeb07fe01b5e2dfdef9cb2f830eefb4bf9ab66d454de052731f6b7fde9961",
}
PLAN_SHA256 = FROZEN_FILES["source-runtime-isolation-plan.md"]

SOURCE_APP = "weknora-g2-594-app"
SOURCE_DOCREADER = "weknora-g2-594-docreader"
PG_CONTAINER = "WeKnora-p0-clone-postgres-vsnd11r2"
SOURCE_DB = "weknora_g2_594"
TARGET_DB = "weknora_g3_830"
DB_USER = "p0clone"
TENANT_ID = 10003
RAW_KB_ID = "b1f1764c-443d-46b8-98e3-d5aa5e55eb42"
EMBEDDING_MODEL_ID = "42df7f04-f53f-42d5-909d-63b0e78a1223"
EXPECTED_SUMMARY_MODEL_ID = "b2034da8-942c-4a19-945d-1bc09459222e"
EXPECTED_AES_SHA256 = "376af9ff738810be97989f85cca89465509e3dd5059fba102ce6652e01617a54"
EXPECTED_CONFIG_SHA256 = "f0c30a2d9fef33d727e00f06845247d0137dac0376c4e23f1ec646445b478947"

APP_IMAGE = "sha256:600a5a1cf93f4d2ecbe5466b7733c8d82395cdcad99fb501fb50ddf224220b19"
DOCREADER_IMAGE = "sha256:ac944d934fcd30c77e4ff28d19f1b4d6dd147012a6553c4678274c1f0be35868"
REDIS_IMAGE = "sha256:02f2cc4882f8bf87c79a220ac958f58c700bdec0dfb9b9ea61b62fb0e8f1bfcf"

NETWORK = "weknora-g3-830-internal"
APP = "weknora-g3-830-app"
DOCREADER = "weknora-g3-830-docreader"
REDIS = "weknora-g3-830-redis"
SEED = "weknora-g3-830-seed"
FILES_VOLUME = "weknora-g3-830-files"
DOCREADER_TMP_VOLUME = "weknora-g3-830-docreader-tmp"
APP_PORT = 18294
GUARD_BASE_URL = "http://127.0.0.1:19030/compatible-mode/v1"

SOURCE_FILES_VOLUME = "weknora-g2-594-files"

EXPECTED_SOURCE_ROWS = [
    {"tenant_id": 10003, "knowledge_id": "5ad208d2-a9a1-4b66-a292-45ab06cb10c8", "parse_attempt": 3,
     "revision_source_id": "d82d39ff488f8965b62bb9cb1bb5f147b6690617ba1c45a06ce9ea37659c7cd3",
     "file_sha256": "7bfac182fe11866e9d4c6f2b970a3a56db79833476f51e83ddcafe127b4c9ce5",
     "page_count": 44, "retention_state": "pinned",
     "binding_digest": "3b3796a0376b469593bb7fd19c091d9ff29a991f8035635126c2ce752ce5a110",
     "resource_id": "ea1399d4-0410-4dff-8bcb-66f5a1a23e51"},
    {"tenant_id": 10003, "knowledge_id": "e7722140-3486-437b-9952-f3d66d6fb539", "parse_attempt": 1,
     "revision_source_id": "aed62bb6045daf632084f85970244cb840a2ea81932d3620bfa4efb1a4a03d0e",
     "file_sha256": "3c7b24cd12e1c6bb04c714be511077f85fa6e5c820ed18dde3f025e9e71b320f",
     "page_count": 17, "retention_state": "pinned",
     "binding_digest": "212b52240bd16a3cabe77841c1f6cf595c7f7a107efed71d4b470c55c601bec1",
     "resource_id": "10d8ea5c-97ed-4ce8-8a3e-6877e8e5c821"},
    {"tenant_id": 10003, "knowledge_id": "f987fc16-222a-4246-8ca0-22c1a81dd6d9", "parse_attempt": 2,
     "revision_source_id": "ea7160149d2fd99ea4a4960c50bfa6ca3641e4532956671b9956f4f8b57ad681",
     "file_sha256": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc",
     "page_count": 39, "retention_state": "pinned",
     "binding_digest": "299502a83c9f776c84f097c2ef5b05c92ce6afaabe5ceb722214be275cf418c0",
     "resource_id": "46ea6872-d26e-4bab-b3ad-151ab6eedd29"},
]

EXPECTED_FILE_REFS = [
    {"id": "1265a343-c408-4620-8eed-c4f6a2adadc2", "current_parse_attempt": 1,
     "file_path": "resource://M22i_VqDy9ruSBBBMxuoiw",
     "file_sha256": "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"},
    {"id": "5ad208d2-a9a1-4b66-a292-45ab06cb10c8", "current_parse_attempt": 3,
     "file_path": "resource://FVUX9FsxUDI9UpWjzS021g",
     "file_sha256": "7bfac182fe11866e9d4c6f2b970a3a56db79833476f51e83ddcafe127b4c9ce5"},
    {"id": "e7722140-3486-437b-9952-f3d66d6fb539", "current_parse_attempt": 1,
     "file_path": "resource://-tdrjtBIk-FRDhwN2Tehzg",
     "file_sha256": "3c7b24cd12e1c6bb04c714be511077f85fa6e5c820ed18dde3f025e9e71b320f"},
    {"id": "f987fc16-222a-4246-8ca0-22c1a81dd6d9", "current_parse_attempt": 2,
     "file_path": "resource://2hNe9Q-sAFtCOhdsLA8oNQ",
     "file_sha256": "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"},
]

EXPECTED_FILES = [
    ("10003/e7722140-3486-437b-9952-f3d66d6fb539/1788658223741084589.pdf", 395696,
     "3c7b24cd12e1c6bb04c714be511077f85fa6e5c820ed18dde3f025e9e71b320f"),
    ("10003/f987fc16-222a-4246-8ca0-22c1a81dd6d9/1786326932437537688.pdf", 1047811,
     "88b784c61f52a2e21a2a12f96ba5d73412de95e68a4453af03a27e8ab1245edc"),
    ("10003/1265a343-c408-4620-8eed-c4f6a2adadc2/1786340266849525928.pdf", 492101,
     "5e2aef32d319b5aca6d37268e99ee5252ea0c7a56885b1e4dfa1ebb0308e4279"),
    ("10003/5ad208d2-a9a1-4b66-a292-45ab06cb10c8/1788657074418341276.pdf", 1332078,
     "7bfac182fe11866e9d4c6f2b970a3a56db79833476f51e83ddcafe127b4c9ce5"),
]

SOURCE_ROWS_SQL = """
SELECT coalesce(json_agg(t),'[]'::json) FROM (
 SELECT tenant_id,knowledge_id,parse_attempt,revision_source_id,file_sha256,
        page_count,retention_state,binding_digest,resource_id
 FROM knowledge_revision_sources WHERE tenant_id=10003
 ORDER BY knowledge_id,parse_attempt
) t
"""
FILE_REFS_SQL = """
SELECT coalesce(json_agg(t),'[]'::json) FROM (
 SELECT id,current_parse_attempt,file_path,file_sha256 FROM knowledges
 WHERE tenant_id=10003 AND id IN
 ('f987fc16-222a-4246-8ca0-22c1a81dd6d9','1265a343-c408-4620-8eed-c4f6a2adadc2',
  '5ad208d2-a9a1-4b66-a292-45ab06cb10c8','e7722140-3486-437b-9952-f3d66d6fb539')
 ORDER BY id
) t
"""
IDLE_SQL = {
    "active_scheduled_datasources":
        "SELECT count(*) FROM data_sources WHERE deleted_at IS NULL AND status='active' "
        "AND coalesce(sync_schedule,'')<>''",
    "pending_knowledge":
        "SELECT count(*) FROM knowledges WHERE deleted_at IS NULL AND "
        "(parse_status IN ('pending','processing','finalizing') OR coalesce(pending_subtasks_count,0)>0)",
    "active_sync_logs": "SELECT count(*) FROM sync_logs WHERE status IN ('running','pending')",
}


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes())


def load_json(path: Path) -> object:
    return json.loads(path.read_text())


def atomic_json(path: Path, value: object, *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(value)
    if exclusive:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
    else:
        tmp = path.with_name(path.name + ".tmp-" + secrets.token_hex(6))
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


class Runner:
    def __init__(self, transport: str):
        self.prefix = (["colima", "ssh", "--profile", "default", "--", "sudo", "docker"]
                       if transport == "colima" else ["docker"])

    def docker(self, *args: str, data: bytes | None = None, allow_failure: bool = False) -> bytes:
        # Never include secret values in args.  Error text omits stderr because
        # a runtime may echo environment values in diagnostics.
        proc = subprocess.run(self.prefix + list(args), input=data, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, check=False)
        if proc.returncode and not allow_failure:
            raise RuntimeError(f"docker operation failed ({args[0] if args else 'unknown'}), rc={proc.returncode}")
        return proc.stdout

    def inspect(self, kind: str, name: str, *, allow_missing: bool = False) -> dict | None:
        out = self.docker(kind, "inspect", name, allow_failure=allow_missing)
        if not out and allow_missing:
            return None
        value = json.loads(out)
        if len(value) != 1:
            raise RuntimeError(f"unexpected inspect cardinality for {kind}/{name}")
        return value[0]

    def cp_out(self, container: str, path: str) -> bytes:
        return self.docker("cp", f"{container}:{path}", "-")

    def psql(self, database: str, sql: str, *, readonly: bool) -> str:
        wrapped = f"BEGIN {'READ ONLY' if readonly else ''};\n{sql.rstrip(';')};\nCOMMIT;\n"
        out = self.docker("exec", "-i", PG_CONTAINER, "psql", "-X", "-q", "-A", "-t",
                          "-v", "ON_ERROR_STOP=1", "-U", DB_USER, "-d", database,
                          data=wrapped.encode())
        lines = [line for line in out.decode().splitlines() if line not in {"BEGIN", "COMMIT"}]
        return "\n".join(lines).strip()


def env_map(inspect: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in inspect.get("Config", {}).get("Env", []):
        if "=" in item:
            key, value = item.split("=", 1)
            result[key] = value
    return result


def validate_relative(name: str) -> str:
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or "." in p.parts or "\x00" in name:
        raise RuntimeError("unsafe manifest-relative path")
    return str(p)


def tar_manifest(blob: bytes, *, select: set[str] | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tf:
        for member in tf.getmembers():
            name = member.name.removeprefix("./")
            if member.isdir():
                continue
            if not member.isfile():
                raise RuntimeError("tar contains a link or non-regular entry")
            name = validate_relative(name)
            if select is not None and name not in select:
                continue
            src = tf.extractfile(member)
            if src is None:
                raise RuntimeError("tar member cannot be read")
            data = src.read()
            result[name] = {"size": len(data), "sha256": sha256(data)}
    if select is not None and set(result) != select:
        raise RuntimeError("tar selection is incomplete")
    return dict(sorted(result.items()))


def extract_tar_member(blob: bytes, wanted: str) -> bytes:
    wanted = validate_relative(wanted)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tf:
        matches = []
        for member in tf.getmembers():
            name = member.name.removeprefix("./")
            if name == wanted and member.isfile():
                src = tf.extractfile(member)
                if src is not None:
                    matches.append(src.read())
        if len(matches) != 1:
            raise RuntimeError(f"expected one tar member: {wanted}")
        return matches[0]


def source_snapshot(r: Runner, database: str) -> dict:
    idle = {key: int(r.psql(database, sql, readonly=True)) for key, sql in IDLE_SQL.items()}
    rows = json.loads(r.psql(database, SOURCE_ROWS_SQL, readonly=True))
    refs = json.loads(r.psql(database, FILE_REFS_SQL, readonly=True))
    return {"idle": idle, "source_rows": rows, "knowledge_file_references": refs}


def require_frozen_evidence() -> dict[str, object]:
    values: dict[str, object] = {}
    for name, expected in FROZEN_FILES.items():
        path = EVIDENCE / name
        if file_sha(path) != expected:
            raise RuntimeError(f"frozen evidence drift: {name}")
        if path.suffix == ".json":
            values[name] = load_json(path)
    return values


def check_port_free() -> None:
    sock = socket.socket()
    try:
        if sock.connect_ex(("127.0.0.1", APP_PORT)) == 0:
            raise RuntimeError(f"127.0.0.1:{APP_PORT} is already in use")
    finally:
        sock.close()


def image_id(r: Runner, digest: str) -> str:
    obj = r.inspect("image", digest)
    assert obj is not None
    return obj["Id"]


def preflight(args: argparse.Namespace) -> None:
    frozen = require_frozen_evidence()
    r = Runner(args.transport)
    source_app = r.inspect("container", SOURCE_APP)
    source_doc = r.inspect("container", SOURCE_DOCREADER)
    pg = r.inspect("container", PG_CONTAINER)
    assert source_app and source_doc and pg
    if not source_app["State"]["Running"] or not source_doc["State"]["Running"] or not pg["State"]["Running"]:
        raise RuntimeError("a frozen source runtime dependency is not running")
    if source_app["Image"] != APP_IMAGE or source_doc["Image"] != DOCREADER_IMAGE:
        raise RuntimeError("source image identity drift")
    if image_id(r, APP_IMAGE) != APP_IMAGE or image_id(r, DOCREADER_IMAGE) != DOCREADER_IMAGE \
            or image_id(r, REDIS_IMAGE) != REDIS_IMAGE:
        raise RuntimeError("a pinned local image digest is absent or mismatched")

    app_env = env_map(source_app)
    if app_env.get("DB_NAME") != SOURCE_DB or app_env.get("DB_USER") != DB_USER:
        raise RuntimeError("source database identity drift")
    aes = app_env.get("SYSTEM_AES_KEY", "")
    if not aes or sha256(aes.encode()) != EXPECTED_AES_SHA256:
        raise RuntimeError("source SYSTEM_AES_KEY identity drift")
    mounts = {(m.get("Name"), m.get("Destination"), bool(m.get("RW"))) for m in source_app["Mounts"]}
    if (SOURCE_FILES_VOLUME, "/data/files", True) not in mounts:
        raise RuntimeError("source files mount drift")

    for kind, names in {
        "container": [APP, DOCREADER, REDIS, SEED],
        "network": [NETWORK],
        "volume": [FILES_VOLUME, DOCREADER_TMP_VOLUME],
    }.items():
        for name in names:
            if r.inspect(kind, name, allow_missing=True) is not None:
                raise RuntimeError(f"target already exists: {kind}/{name}")
    if int(r.psql("postgres", f"SELECT count(*) FROM pg_database WHERE datname='{TARGET_DB}'", readonly=True)) != 0:
        raise RuntimeError("target database already exists")
    check_port_free()

    snap = source_snapshot(r, SOURCE_DB)
    if snap["source_rows"] != EXPECTED_SOURCE_ROWS or snap["knowledge_file_references"] != EXPECTED_FILE_REFS:
        raise RuntimeError("source revision/file identity drift")
    if any(snap["idle"].values()):
        raise RuntimeError("source has active schedules, parsing work, or sync logs")

    observed_files = []
    for rel, expected_size, expected_sha in EXPECTED_FILES:
        out = r.docker("exec", SOURCE_APP, "sha256sum", f"/data/files/{rel}").decode().strip()
        observed_sha = out.split()[0] if out else ""
        stat = r.docker("exec", SOURCE_APP, "stat", "-c", "%s", f"/data/files/{rel}").decode().strip()
        if observed_sha != expected_sha or int(stat) != expected_size:
            raise RuntimeError("source resource bytes drift")
        observed_files.append({"path": rel, "size": expected_size, "sha256": expected_sha})

    config_tar = r.cp_out(SOURCE_APP, "/app/config/.")
    config_manifest = tar_manifest(config_tar)
    config_yaml = extract_tar_member(config_tar, "config.yaml")
    if sha256(config_yaml) != EXPECTED_CONFIG_SHA256:
        raise RuntimeError("source config.yaml identity drift")

    doc_env = env_map(source_doc)
    # Only parser-behaviour fields may cross into the receipt/target.  Do not
    # copy arbitrary DOCREADER_* values that could later carry credentials.
    parser_safe_prefixes = (
        "DOCREADER_GRPC_", "DOCREADER_DOCX_", "DOCREADER_MARKITDOWN_",
        "DOCREADER_PDF_", "DOCREADER_ODL_MAX_WORKERS",
        "DOCREADER_ODL_MARKDOWN_WITH_HTML",
    )
    parser_env = {k: v for k, v in doc_env.items() if k.startswith(parser_safe_prefixes)}
    # The isolated target must not inherit proxy/remote hybrid paths.
    parser_env["DOCREADER_EXTERNAL_HTTP_PROXY"] = ""
    parser_env["DOCREADER_EXTERNAL_HTTPS_PROXY"] = ""
    parser_env["DOCREADER_ODL_HYBRID"] = "off"
    parser_env["DOCREADER_GRPC_PORT"] = "50051"

    safe_source = {
        "app_image": source_app["Image"],
        "docreader_image": source_doc["Image"],
        "postgres_image": pg["Image"],
        "source_db": SOURCE_DB,
        "db_user": DB_USER,
        "system_aes_key_sha256": sha256(aes.encode()),
        # The source app's /run/c5 is the closed G2 serving bundle.  It is
        # intentionally not copied or mounted into this source-only runtime.
        "c5_registry_policy": "empty-registry-no-mount",
        "config_yaml_sha256": sha256(config_yaml),
        "config_tree": config_manifest,
        "parser_env": parser_env,
    }
    receipt = {
        "contract": PREFLIGHT_CONTRACT,
        "draft_contract": CONTRACT,
        "checked_at": utcnow(),
        "plan_sha256": PLAN_SHA256,
        "script_sha256": file_sha(Path(__file__).resolve()),
        "frozen_evidence_sha256": FROZEN_FILES,
        "effects": {"runtime_writes": 0, "database_writes": 0, "starts": 0,
                    "provider_calls": 0, "uploads": 0, "builds": 0, "pulls": 0},
        "source": safe_source,
        "source_snapshot": snap,
        "files": observed_files,
        "target_absence": {"database": True, "containers": True, "network": True,
                           "volumes": True, "port_18294": True},
        "frozen_contracts": {
            key: value.get("contract") for key, value in frozen.items() if isinstance(value, dict)
        },
    }
    atomic_json(args.output, receipt, exclusive=True)
    print(json.dumps({"status": "PREFLIGHT_PASS", "receipt": str(args.output),
                      "receipt_sha256": file_sha(args.output)}, sort_keys=True))


class ApplyState:
    def __init__(self, path: Path, initial: dict):
        self.path = path
        self.value = initial
        atomic_json(path, initial, exclusive=True)

    def checkpoint(self, step: str, evidence: dict | None = None) -> None:
        self.value["steps"].append({"step": step, "at": utcnow(), "evidence": evidence or {}})
        self.value["last_step"] = step
        atomic_json(self.path, self.value)

    def stop(self, message: str) -> None:
        self.value["status"] = "STOPPED"
        self.value["stopped_at"] = utcnow()
        self.value["failure"] = message
        try:
            atomic_json(self.path, self.value)
        except Exception:
            pass


def load_and_validate_authorization(path: Path, preflight_sha: str) -> dict:
    value = load_json(path)
    if not isinstance(value, dict):
        raise RuntimeError("authorization receipt must be an object")
    required = {
        "contract": AUTH_CONTRACT,
        "status": "APPROVED",
        "plan_sha256": PLAN_SHA256,
        "preflight_sha256": preflight_sha,
        "authorized_actions": ["provision", "configure"],
    }
    for key, expected in required.items():
        if value.get(key) != expected:
            raise RuntimeError(f"authorization receipt mismatch: {key}")
    if not isinstance(value.get("approved_at"), str) or not value["approved_at"]:
        raise RuntimeError("authorization receipt lacks approved_at")
    return value


def remote_secret_file(r: Runner, remote_path: str, data: bytes) -> None:
    if r.prefix[0] == "docker":
        # Native Docker cannot safely bind a host temp path into a remote daemon.
        # Refuse rather than falling back to a visible argv/env value.
        raise RuntimeError("apply secret staging requires --transport=colima")
    cmd = ["colima", "ssh", "--profile", "default", "--", "sudo", "/bin/sh", "-ceu",
           f"umask 077; mkdir -p /run/g3-830-private; cat > {remote_path}; chmod 600 {remote_path}"]
    proc = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode:
        raise RuntimeError("private runtime file staging failed")


def copy_tar(r: Runner, source_container: str, source_root: str, relative: list[str],
             target_container: str, target_root: str) -> None:
    for name in relative:
        validate_relative(name)
    blob = r.docker("exec", source_container, "tar", "-C", source_root, "-cf", "-", *relative)
    r.docker("exec", "-i", target_container, "tar", "-C", target_root, "-xf", "-", data=blob)


def verify_seed_file(r: Runner, root: str, rel: str, size: int, digest: str) -> None:
    got_hash = r.docker("exec", SEED, "sha256sum", f"{root}/{rel}").decode().split()[0]
    got_size = int(r.docker("exec", SEED, "stat", "-c", "%s", f"{root}/{rel}").decode())
    if got_hash != digest or got_size != size:
        raise RuntimeError("target volume byte verification failed")


def api_request(method: str, path: str, token: str | None = None,
                body: dict | None = None) -> dict:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    url = f"http://127.0.0.1:{APP_PORT}{path}"
    data = canonical_bytes(body) if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        # Explicitly disable inherited HTTP(S) proxies so the local bearer
        # token can only travel to the loopback socket named above.
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect).open(
                req, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"local API returned status {response.status}")
            value = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"local API returned status {exc.code}") from None
    if not isinstance(value, dict):
        raise RuntimeError("local API response is not an object")
    return value


def unwrap_data(value: dict) -> dict:
    data = value.get("data", value)
    if not isinstance(data, dict):
        raise RuntimeError("local API data is not an object")
    return data


def assert_no_credentials(value: object) -> None:
    forbidden = {"api_key", "app_secret", "authorization", "credential", "credentials"}
    if isinstance(value, dict):
        if forbidden.intersection(k.lower() for k in value):
            raise RuntimeError("credential-bearing field found in API update payload")
        for child in value.values():
            assert_no_credentials(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_credentials(child)


def configure_api(auth_path: Path) -> dict:
    if auth_path.stat().st_mode & 0o077:
        raise RuntimeError("private auth file permissions must be 0600 or stricter")
    auth = load_json(auth_path)
    if not isinstance(auth, dict) or set(auth) != {"email", "password"}:
        raise RuntimeError("private auth file must contain exactly email/password")
    login = api_request("POST", "/api/v1/auth/login", body=auth)
    token = login.get("token") or unwrap_data(login).get("token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("local login did not return a token")
    # Token remains only in memory.
    kb_before = unwrap_data(api_request(
        "GET", f"/api/v1/knowledge-bases/{RAW_KB_ID}", token=token))
    if kb_before.get("id") != RAW_KB_ID or kb_before.get("tenant_id") != TENANT_ID:
        raise RuntimeError("KB GET identity drift")
    required_kb = ["name", "description", "chunking_config", "image_processing_config",
                   "faq_config", "wiki_config", "indexing_strategy"]
    if any(key not in kb_before for key in required_kb):
        raise RuntimeError("KB GET lacks a full update field")
    chunking = json.loads(json.dumps(kb_before["chunking_config"]))
    indexing = json.loads(json.dumps(kb_before["indexing_strategy"]))
    chunking["token_limit"] = 0
    chunking["languages"] = []
    indexing["wiki_enabled"] = False
    indexing["graph_enabled"] = False
    kb_payload = {
        "name": kb_before["name"],
        "description": kb_before["description"],
        "config": {
            "chunking_config": chunking,
            "image_processing_config": kb_before["image_processing_config"],
            "faq_config": kb_before["faq_config"],
            "wiki_config": kb_before["wiki_config"],
            "indexing_strategy": indexing,
        },
    }
    api_request("PUT", f"/api/v1/knowledge-bases/{RAW_KB_ID}", token=token, body=kb_payload)

    model_before = unwrap_data(api_request("GET", f"/api/v1/models/{EMBEDDING_MODEL_ID}", token=token))
    if model_before.get("id") != EMBEDDING_MODEL_ID or model_before.get("tenant_id") != TENANT_ID:
        raise RuntimeError("embedding model GET identity drift")
    if model_before.get("is_builtin") is not False:
        raise RuntimeError("GET-derived model update requires the frozen tenant-owned model")
    params = json.loads(json.dumps(model_before.get("parameters")))
    if not isinstance(params, dict) or "base_url" not in params:
        raise RuntimeError("model GET lacks full non-secret parameters")
    assert_no_credentials(params)
    params["base_url"] = GUARD_BASE_URL
    model_payload = {
        "name": model_before["name"],
        "display_name": model_before.get("display_name", ""),
        "description": model_before.get("description", ""),
        "parameters": params,
        "source": model_before["source"],
        "type": model_before["type"],
    }
    assert_no_credentials(model_payload)
    api_request("PUT", f"/api/v1/models/{EMBEDDING_MODEL_ID}", token=token, body=model_payload)

    kb_after = unwrap_data(api_request("GET", f"/api/v1/knowledge-bases/{RAW_KB_ID}", token=token))
    model_after = unwrap_data(api_request("GET", f"/api/v1/models/{EMBEDDING_MODEL_ID}", token=token))
    if kb_after["indexing_strategy"].get("wiki_enabled") is not False \
            or kb_after["indexing_strategy"].get("graph_enabled") is not False \
            or kb_after["chunking_config"].get("token_limit", 0) != 0 \
            or kb_after["chunking_config"].get("languages", []) != []:
        raise RuntimeError("KB API configuration readback mismatch")
    if model_after.get("parameters", {}).get("base_url") != GUARD_BASE_URL:
        raise RuntimeError("embedding model base_url readback mismatch")
    return {
        "kb_before_sha256": sha256(canonical_bytes(kb_before)),
        "kb_after_sha256": sha256(canonical_bytes(kb_after)),
        "model_before_nonsecret_sha256": sha256(canonical_bytes(model_before)),
        "model_after_nonsecret_sha256": sha256(canonical_bytes(model_after)),
        "wiki_enabled": False, "graph_enabled": False, "token_limit": 0, "languages": [],
        "embedding_base_url": GUARD_BASE_URL,
        "credential_fields_sent": 0,
    }


def apply(args: argparse.Namespace) -> None:
    require_frozen_evidence()
    preflight_value = load_json(args.preflight)
    if not isinstance(preflight_value, dict) or preflight_value.get("contract") != PREFLIGHT_CONTRACT:
        raise RuntimeError("invalid preflight receipt contract")
    preflight_sha = file_sha(args.preflight)
    if preflight_value.get("plan_sha256") != PLAN_SHA256:
        raise RuntimeError("preflight receipt plan mismatch")
    current_script_sha = file_sha(Path(__file__).resolve())
    if preflight_value.get("script_sha256") != current_script_sha:
        raise RuntimeError("preflight receipt script mismatch")
    auth = load_and_validate_authorization(args.authorization, preflight_sha)
    if args.receipt.exists():
        raise RuntimeError("apply receipt already exists; retry/resume is forbidden")
    state = ApplyState(args.receipt, {
        "contract": RECEIPT_CONTRACT, "draft_contract": CONTRACT, "status": "STARTED",
        "started_at": utcnow(), "plan_sha256": PLAN_SHA256,
        "script_sha256": current_script_sha, "preflight_sha256": preflight_sha,
        "authorization_sha256": file_sha(args.authorization),
        "authorization_approved_at": auth["approved_at"], "steps": [], "last_step": None,
        "effects": {"provider_calls": 0, "uploads": 0, "builds": 0, "pulls": 0,
                    "guard_starts": 0},
    })
    r = Runner(args.transport)
    try:
        # Re-run the mutable-world absence/identity gates immediately before mutation.
        source_app = r.inspect("container", SOURCE_APP)
        source_doc = r.inspect("container", SOURCE_DOCREADER)
        assert source_app and source_doc
        if source_app["Image"] != APP_IMAGE or source_doc["Image"] != DOCREADER_IMAGE:
            raise RuntimeError("source image drift since preflight")
        source_env = env_map(source_app)
        aes = source_env.get("SYSTEM_AES_KEY", "")
        if sha256(aes.encode()) != EXPECTED_AES_SHA256:
            raise RuntimeError("AES identity drift since preflight")
        before_source = source_snapshot(r, SOURCE_DB)
        if before_source != preflight_value["source_snapshot"]:
            raise RuntimeError("source rows/jobs drift since preflight")
        for kind, names in {"container": [APP, DOCREADER, REDIS, SEED], "network": [NETWORK],
                            "volume": [FILES_VOLUME, DOCREADER_TMP_VOLUME]}.items():
            for name in names:
                if r.inspect(kind, name, allow_missing=True) is not None:
                    raise RuntimeError(f"target appeared since preflight: {kind}/{name}")
        if int(r.psql("postgres", f"SELECT count(*) FROM pg_database WHERE datname='{TARGET_DB}'", readonly=True)):
            raise RuntimeError("target database appeared since preflight")
        check_port_free()
        state.checkpoint("revalidated-preconditions", {"source_snapshot_sha256": sha256(canonical_bytes(before_source))})

        dump = r.docker("exec", PG_CONTAINER, "pg_dump", "-U", DB_USER,
                        "--format=custom", "--serializable-deferrable", "--no-owner", "--no-acl", SOURCE_DB)
        if not dump:
            raise RuntimeError("consistent pg_dump returned empty bytes")
        dump_sha = sha256(dump)
        state.checkpoint("captured-consistent-source-dump", {"dump_sha256": dump_sha, "bytes": len(dump)})

        r.docker("exec", PG_CONTAINER, "createdb", "-U", DB_USER, "-T", "template0", TARGET_DB)
        state.checkpoint("created-target-database")
        r.docker("exec", "-i", PG_CONTAINER, "pg_restore", "-U", DB_USER,
                 "--dbname", TARGET_DB, "--exit-on-error", "--single-transaction",
                 "--no-owner", "--no-acl", data=dump)
        dump = b""  # release clone bytes promptly; never persist them on the host.
        restored = source_snapshot(r, TARGET_DB)
        if restored != before_source:
            raise RuntimeError("restored DB source/job identity mismatch")
        state.checkpoint("restored-target-database", {"snapshot_sha256": sha256(canonical_bytes(restored))})

        kb_before = json.loads(r.psql(
            TARGET_DB,
            f"SELECT row_to_json(t) FROM (SELECT * FROM knowledge_bases WHERE tenant_id={TENANT_ID} "
            f"AND id='{RAW_KB_ID}') t", readonly=True))
        if kb_before.get("summary_model_id") != EXPECTED_SUMMARY_MODEL_ID:
            raise RuntimeError("target KB summary model drift before narrow SQL")
        if kb_before.get("question_generation_config") != {"enabled": True, "question_count": 3}:
            raise RuntimeError("target KB question generation drift before narrow SQL")
        update_sql = f"""
UPDATE knowledge_bases
SET summary_model_id=NULL,
    question_generation_config='{{"enabled":false,"question_count":0}}'::jsonb
WHERE tenant_id={TENANT_ID} AND id='{RAW_KB_ID}'
  AND summary_model_id='{EXPECTED_SUMMARY_MODEL_ID}'
  AND question_generation_config::jsonb='{{"enabled":true,"question_count":3}}'::jsonb
RETURNING id
"""
        updated_id = r.psql(TARGET_DB, update_sql, readonly=False)
        if updated_id != RAW_KB_ID:
            raise RuntimeError("narrow target-only SQL did not update exactly the frozen KB")
        kb_after = json.loads(r.psql(
            TARGET_DB,
            f"SELECT row_to_json(t) FROM (SELECT * FROM knowledge_bases WHERE tenant_id={TENANT_ID} "
            f"AND id='{RAW_KB_ID}') t", readonly=True))
        comparable_before = {k: v for k, v in kb_before.items() if k not in {"summary_model_id", "question_generation_config", "updated_at"}}
        comparable_after = {k: v for k, v in kb_after.items() if k not in {"summary_model_id", "question_generation_config", "updated_at"}}
        if comparable_before != comparable_after or kb_after.get("summary_model_id") is not None \
                or kb_after.get("question_generation_config") != {"enabled": False, "question_count": 0}:
            raise RuntimeError("narrow SQL postcondition mismatch")
        target_idle = source_snapshot(r, TARGET_DB)["idle"]
        if any(target_idle.values()):
            raise RuntimeError("target contains active work before app start")
        state.checkpoint("disabled-summary-and-qgen-before-start", {
            "kb_before_sha256": sha256(canonical_bytes(kb_before)),
            "kb_after_sha256": sha256(canonical_bytes(kb_after)), "target_idle": target_idle})

        r.docker("network", "create", "--internal", "--label", "goal=830-g3", NETWORK)
        for volume in [FILES_VOLUME, DOCREADER_TMP_VOLUME]:
            r.docker("volume", "create", "--label", "goal=830-g3", volume)
        r.docker("network", "connect", "--alias", "postgres-g3", NETWORK, PG_CONTAINER)
        state.checkpoint("created-isolated-network-and-volumes")

        r.docker("create", "--pull=never", "--name", SEED, "--network", "none",
                 "--entrypoint", "/bin/sh",
                 "--mount", f"type=volume,src={FILES_VOLUME},dst=/data/files",
                 APP_IMAGE, "-ceu", "sleep 86400")
        r.docker("start", SEED)
        copy_tar(r, SOURCE_APP, "/data/files", [x[0] for x in EXPECTED_FILES], SEED, "/data/files")
        for rel, size, digest in EXPECTED_FILES:
            verify_seed_file(r, "/data/files", rel, size, digest)
        state.checkpoint("copied-and-verified-exact-resource-files", {
            "resource_count": len(EXPECTED_FILES), "c5_registry": "not-mounted-empty"})
        r.docker("stop", "--time", "3", SEED)
        r.docker("rm", SEED)
        state.checkpoint("removed-successful-seed-helper")

        redis_password = secrets.token_urlsafe(36)
        jwt_secret = secrets.token_urlsafe(48)
        private_env = {
            "DB_DRIVER": "postgres", "DB_HOST": "postgres-g3", "DB_PORT": "5432",
            "DB_USER": DB_USER, "DB_PASSWORD": source_env.get("DB_PASSWORD", ""), "DB_NAME": TARGET_DB,
            "REDIS_ADDR": "redis-g3:6379", "REDIS_USERNAME": "", "REDIS_PASSWORD": redis_password,
            "REDIS_DB": "0", "JWT_SECRET": jwt_secret, "SYSTEM_AES_KEY": aes,
            "GIN_MODE": "release", "PORT": "8080", "AUTO_MIGRATE": "false",
            "AUTO_RECOVER_DIRTY": "false", "RETRIEVE_DRIVER": "postgres",
            "STORAGE_TYPE": "local", "LOCAL_STORAGE_BASE_DIR": "/data/files",
            "DOCREADER_ADDR": "docreader-g3:50051", "DOCREADER_TRANSPORT": "grpc",
            "BATCH_EMBED_SIZE": "100", "SSRF_WHITELIST": "127.0.0.1",
            "DISABLE_REGISTRATION": "true", "WEKNORA_TENANT_ENABLE_CROSS_TENANT_ACCESS": "false",
            "KNOWLEDGE_REVISION_SOURCE_BACKFILL_ENABLED": "true",
        }
        if not private_env["DB_PASSWORD"]:
            raise RuntimeError("source DB password absent")
        env_bytes = "".join(f"{k}={v}\n" for k, v in private_env.items()).encode()
        redis_env_bytes = f"REDIS_PASSWORD={redis_password}\n".encode()
        app_env_path = "/run/g3-830-private/app.env"
        redis_env_path = "/run/g3-830-private/redis.env"
        remote_secret_file(r, app_env_path, env_bytes)
        remote_secret_file(r, redis_env_path, redis_env_bytes)
        # Receipts contain digests only, never credentials.
        state.checkpoint("staged-private-runtime-environment", {
            "app_env_sha256": sha256(env_bytes), "redis_env_sha256": sha256(redis_env_bytes),
            "system_aes_key_sha256": sha256(aes.encode())})

        parser_env = preflight_value["source"]["parser_env"]
        doc_args = ["create", "--pull=never", "--name", DOCREADER, "--network", NETWORK,
                    "--network-alias", "docreader-g3", "--label", "goal=830-g3",
                    "--mount", f"type=volume,src={DOCREADER_TMP_VOLUME},dst=/tmp/docreader"]
        for key, value in sorted(parser_env.items()):
            doc_args += ["-e", f"{key}={value}"]
        doc_args.append(DOCREADER_IMAGE)
        r.docker(*doc_args)
        r.docker("create", "--pull=never", "--name", REDIS, "--network", NETWORK,
                 "--network-alias", "redis-g3", "--label", "goal=830-g3",
                 "--env-file", redis_env_path, "--entrypoint", "/bin/sh", REDIS_IMAGE,
                 "-ceu", "exec redis-server --save '' --appendonly no --requirepass \"$REDIS_PASSWORD\"")
        r.docker("create", "--pull=never", "--name", APP, "--network", NETWORK,
                 "--network-alias", "app-g3", "--label", "goal=830-g3",
                 "--env-file", app_env_path,
                 "--publish", f"127.0.0.1:{APP_PORT}:8080",
                 "--mount", f"type=volume,src={FILES_VOLUME},dst=/data/files",
                 "--mount", f"type=volume,src={DOCREADER_TMP_VOLUME},dst=/tmp/docreader,readonly",
                 APP_IMAGE)
        # The source config may have been copied into that container's writable
        # layer after image creation. Re-read it, bind it to the preflight
        # manifest, then archive-copy those exact bytes into the still-stopped
        # G3 container. `--archive` preserves mode/owner metadata.
        source_config_tar = r.cp_out(SOURCE_APP, "/app/config/.")
        if tar_manifest(source_config_tar) != preflight_value["source"]["config_tree"]:
            raise RuntimeError("source config tree drift since preflight")
        r.docker("cp", "--archive", "-", f"{APP}:/app/config", data=source_config_tar)
        target_config_tar = r.cp_out(APP, "/app/config/.")
        target_config_manifest = tar_manifest(target_config_tar)
        if target_config_manifest != preflight_value["source"]["config_tree"]:
            raise RuntimeError("stopped target app config tree differs from frozen source")
        target_config_yaml = extract_tar_member(target_config_tar, "config.yaml")
        if sha256(target_config_yaml) != EXPECTED_CONFIG_SHA256:
            raise RuntimeError("stopped target app config.yaml digest mismatch")
        state.checkpoint("created-stopped-containers-and-verified-config", {
            "app_image": APP_IMAGE, "docreader_image": DOCREADER_IMAGE,
            "redis_image": REDIS_IMAGE, "config_yaml_sha256": sha256(target_config_yaml)})

        r.docker("start", REDIS)
        r.docker("start", DOCREADER)
        r.docker("start", APP)
        state.checkpoint("started-internal-runtime")
        deadline = time.monotonic() + 45
        while True:
            try:
                health = api_request("GET", "/health")
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise RuntimeError("local app health did not become ready within 45 seconds")
                time.sleep(1)
        state.checkpoint("local-health-ready", {"health_sha256": sha256(canonical_bytes(health))})

        api_evidence = configure_api(args.private_auth)
        state.checkpoint("applied-full-get-derived-api-configuration", api_evidence)

        final_target = source_snapshot(r, TARGET_DB)
        if final_target["source_rows"] != EXPECTED_SOURCE_ROWS \
                or final_target["knowledge_file_references"] != EXPECTED_FILE_REFS \
                or any(final_target["idle"].values()):
            raise RuntimeError("final target revision/source/job identity mismatch")
        final_source = source_snapshot(r, SOURCE_DB)
        if final_source != before_source:
            raise RuntimeError("source DB changed during provision")
        state.checkpoint("verified-source-and-target-identities", {
            "source_sha256": sha256(canonical_bytes(final_source)),
            "target_revision_identity_sha256": sha256(canonical_bytes({
                "source_rows": final_target["source_rows"],
                "knowledge_file_references": final_target["knowledge_file_references"]})),
            "target_idle": final_target["idle"]})
        state.value["status"] = "PASS"
        state.value["completed_at"] = utcnow()
        atomic_json(state.path, state.value)
        print(json.dumps({"status": "PASS", "receipt": str(state.path),
                          "receipt_sha256": file_sha(state.path)}, sort_keys=True))
    except Exception as exc:
        # No rollback and no retry: keep every partial object and the durable
        # receipt for inspection. Stop any target processes so a failed run
        # cannot continue background work; do not delete their state.
        r.docker("stop", "--time", "3", APP, DOCREADER, REDIS, allow_failure=True)
        # Do not include command stderr or secrets.
        state.stop(f"{type(exc).__name__}: {exc}")
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=["colima", "docker"], default="colima")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preflight", help="read-only runtime inspection")
    p.add_argument("--output", type=Path, required=True)
    a = sub.add_parser("apply", help="one-shot provision/configure; mutation")
    a.add_argument("--preflight", type=Path, required=True)
    a.add_argument("--authorization", type=Path, required=True)
    a.add_argument("--private-auth", type=Path, required=True)
    a.add_argument("--receipt", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "preflight":
        preflight(args)
    elif args.command == "apply":
        apply(args)
    else:
        raise AssertionError("unreachable")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Errors are intentionally terse. No captured stderr or secrets.
        print(json.dumps({"status": "STOP", "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True),
              file=sys.stderr)
        raise SystemExit(1)
